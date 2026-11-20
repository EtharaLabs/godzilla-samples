// The global console object and the console.Console class.
//
// The reference's global console prints each argument with plain String() semantics (no
// format directives, no group indentation) straight to the process's stdout/stderr, while a
// `new Console(stream)` instance formats with util.format and indents groups by two spaces.

use crate::object::*;
use crate::runtime::util::{format_units, inspect_units, string_of};
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::cell::RefCell;
use std::collections::HashMap;
use std::io::Write;
use std::time::Instant;

fn key(s: &str) -> PropKey {
    PropKey::from_str(s)
}

fn u16s(s: &str) -> Vec<u16> {
    s.encode_utf16().collect()
}

fn jsv(units: Vec<u16>) -> Value {
    Value::Str(JsStr::from_units(units))
}

// ============================================================================================
// raw output
// ============================================================================================

/// UTF-16 -> bytes the way the reference writes strings: valid pairs become UTF-8, a lone
/// surrogate U+D800..U+DFFF is written as the 4-byte sequence of code point (unit + 0x102000).
pub fn units_to_bytes(u: &[u16]) -> Vec<u8> {
    let mut out = Vec::with_capacity(u.len());
    let mut i = 0;
    let push_cp = |out: &mut Vec<u8>, cp: u32| {
        if let Some(c) = char::from_u32(cp) {
            let mut b = [0u8; 4];
            out.extend_from_slice(c.encode_utf8(&mut b).as_bytes());
        } else {
            out.push(0xF0 | ((cp >> 18) & 0x07) as u8);
            out.push(0x80 | ((cp >> 12) & 0x3F) as u8);
            out.push(0x80 | ((cp >> 6) & 0x3F) as u8);
            out.push(0x80 | (cp & 0x3F) as u8);
        }
    };
    while i < u.len() {
        let c = u[i];
        if (0xD800..0xDC00).contains(&c) && i + 1 < u.len() && (0xDC00..0xE000).contains(&u[i + 1]) {
            let cp = 0x10000 + (((c as u32) - 0xD800) << 10) + ((u[i + 1] as u32) - 0xDC00);
            push_cp(&mut out, cp);
            i += 2;
            continue;
        }
        if (0xD800..0xE000).contains(&c) {
            push_cp(&mut out, c as u32 + 0x102000);
        } else {
            push_cp(&mut out, c as u32);
        }
        i += 1;
    }
    out
}

fn write_fd(err: bool, units: &[u16]) {
    let bytes = units_to_bytes(units);
    if err {
        let e = std::io::stderr();
        let mut l = e.lock();
        let _ = l.write_all(&bytes);
        let _ = l.flush();
    } else {
        let o = std::io::stdout();
        let mut l = o.lock();
        let _ = l.write_all(&bytes);
        let _ = l.flush();
    }
}

fn write_line(err: bool, mut units: Vec<u16>) {
    units.push(b'\n' as u16);
    write_fd(err, &units);
}

/// What the global console prints for one argument: String(v), "[object]" if that throws.
fn plain_string(vm: &mut Vm, v: &Value) -> Vec<u16> {
    match string_of(vm, v) {
        Ok(s) => s.units().to_vec(),
        Err(_) => u16s("[object]"),
    }
}

fn join_plain(vm: &mut Vm, args: &[Value]) -> Vec<u16> {
    let mut out = Vec::new();
    for (i, v) in args.iter().enumerate() {
        if i > 0 {
            out.push(b' ' as u16);
        }
        let s = plain_string(vm, v);
        out.extend(s);
    }
    out
}

// ============================================================================================
// shared pieces: labels, timers, table
// ============================================================================================

/// console.dir only takes an options object (a boolean is not the legacy showHidden flag).
fn dir_opts(v: &Value) -> Value {
    if v.is_object() {
        v.clone()
    } else {
        Value::Undefined
    }
}

/// count/time labels: String(label) (symbols allowed), "default" when omitted.
fn label_of(vm: &mut Vm, v: &Value) -> JsResult<String> {
    if v.is_undefined() {
        Ok("default".to_string())
    } else {
        Ok(string_of(vm, v)?.to_rust_string())
    }
}

fn fmt_elapsed(d: std::time::Duration) -> String {
    let ms = d.as_secs_f64() * 1000.0;
    if ms < 1000.0 {
        format!("{:.3}ms", ms)
    } else if ms < 60_000.0 {
        format!("{:.3}s", ms / 1000.0)
    } else if ms < 3_600_000.0 {
        let m = (ms / 60_000.0).floor();
        format!("{}m{:.3}s", m, (ms - m * 60_000.0) / 1000.0)
    } else {
        let h = (ms / 3_600_000.0).floor();
        let rest = ms - h * 3_600_000.0;
        let m = (rest / 60_000.0).floor();
        format!("{}h{}m{:.3}s", h, m, (rest - m * 60_000.0) / 1000.0)
    }
}

fn depth0(vm: &mut Vm, v: &Value) -> JsResult<Vec<u16>> {
    inspect_units(vm, v, &Value::Undefined, &[("depth", Value::Num(0.0))])
}

fn center(s: &[u16], w: usize) -> Vec<u16> {
    let l = s.len().min(w);
    let left = (w - l) / 2;
    let right = w - l - left;
    let mut out = vec![b' ' as u16; left];
    out.extend_from_slice(s);
    out.extend(std::iter::repeat(b' ' as u16).take(right));
    out
}

/// console.table rendering; None when `data` is not tabular (printed like a log instead).
fn render_table(vm: &mut Vm, data: &Value, props: &Value) -> JsResult<Option<Vec<u16>>> {
    let o = match data {
        Value::Obj(o) if !o.is_callable() => o.clone(),
        _ => return Ok(None),
    };
    let mut rows: Vec<(Vec<u16>, Value)> = Vec::new();
    let map_proto = vm.intr.map_proto.clone();
    if crate::builtins::array::is_array(vm, data)? {
        let lv = vm.get(&o, &vm.intr.key_length.clone(), data)?;
        let len = vm.to_length(&lv)?;
        for i in 0..len {
            if !vm.has_own_property(&o, &PropKey::Str(index_to_jsstr(i)))? {
                return vm.throw_type("cannot read property '\u{0}1' of undefined");
            }
        }
        for i in 0..len {
            let v = vm.get(&o, &PropKey::Str(index_to_jsstr(i)), data)?;
            rows.push((u16s(&i.to_string()), v));
        }
    } else if proto_has(vm, data, &map_proto)? {
        let entries = vm.iterate_to_vec(data)?;
        for e in entries {
            let k = vm.get_prop_of(&e, &PropKey::from_index(0))?;
            let v = vm.get_prop_of(&e, &PropKey::from_index(1))?;
            let label = depth0(vm, &k)?;
            rows.push((label, v));
        }
    } else {
        for k in vm.enumerable_own_keys(&o)? {
            let v = vm.get(&o, &PropKey::Str(k.clone()), data)?;
            rows.push((k.units().to_vec(), v));
        }
    }
    let filter = if props.truthy() { Some(props.clone()) } else { None };
    let mut includes: Option<Value> = None;
    let mut columns: Vec<Vec<u16>> = Vec::new();
    let mut has_values = false;
    let mut cells: Vec<(Vec<u16>, Vec<(usize, Vec<u16>)>, Option<Vec<u16>>)> = Vec::new();
    for (label, v) in rows {
        let mut rc = Vec::new();
        let mut value_cell = None;
        match &v {
            Value::Obj(ro) if !ro.is_callable() => {
                for k in vm.enumerable_own_keys(ro)? {
                    if let Some(f) = &filter {
                        if includes.is_none() {
                            let inc = vm.get_prop_of(f, &key("includes"))?;
                            if !inc.is_callable() {
                                return vm.throw_type("(intermediate value).includes is not a function");
                            }
                            includes = Some(inc);
                        }
                        let inc = includes.clone().unwrap();
                        if !vm.call(&inc, f.clone(), &[Value::Str(k.clone())])?.truthy() {
                            continue;
                        }
                    }
                    let col = match columns.iter().position(|c| c[..] == *k.units()) {
                        Some(p) => p,
                        None => {
                            columns.push(k.units().to_vec());
                            columns.len() - 1
                        }
                    };
                    let cv = vm.get(ro, &PropKey::Str(k.clone()), &v)?;
                    let text = depth0(vm, &cv)?;
                    rc.push((col, text));
                }
            }
            other => {
                has_values = true;
                value_cell = Some(depth0(vm, other)?);
            }
        }
        cells.push((label, rc, value_cell));
    }
    let mut header: Vec<Vec<u16>> = vec![u16s("(index)")];
    header.extend(columns.iter().cloned());
    if has_values {
        header.push(u16s("Values"));
    }
    let ncol = header.len();
    let mut grid: Vec<Vec<Vec<u16>>> = Vec::new();
    for (label, rc, vc) in cells {
        let mut r: Vec<Vec<u16>> = vec![Vec::new(); ncol];
        r[0] = label;
        for (c, t) in rc {
            r[c + 1] = t;
        }
        if has_values {
            r[ncol - 1] = vc.unwrap_or_default();
        }
        grid.push(r);
    }
    let widths: Vec<usize> = (0..ncol).map(|i| grid.iter().map(|r| r[i].len()).chain(std::iter::once(header[i].len())).max().unwrap_or(0) + 2).collect();
    let line = |l: &str, m: &str, r: &str| -> Vec<u16> {
        let mut out = u16s(l);
        for (i, w) in widths.iter().enumerate() {
            if i > 0 {
                out.extend(u16s(m));
            }
            out.extend(u16s(&"─".repeat(*w)));
        }
        out.extend(u16s(r));
        out
    };
    let row = |cols: &[Vec<u16>]| -> Vec<u16> {
        let mut out = u16s("│");
        for (i, c) in cols.iter().enumerate() {
            if i > 0 {
                out.extend(u16s("│"));
            }
            out.extend(center(c, widths[i]));
        }
        out.extend(u16s("│"));
        out
    };
    let nl = b'\n' as u16;
    let mut out = line("┌", "┬", "┐");
    out.push(nl);
    out.extend(row(&header));
    out.push(nl);
    out.extend(line("├", "┼", "┤"));
    out.push(nl);
    for r in &grid {
        out.extend(row(r));
        out.push(nl);
    }
    out.extend(line("└", "┴", "┘"));
    Ok(Some(out))
}

fn proto_has(vm: &mut Vm, v: &Value, proto: &Obj) -> JsResult<bool> {
    let mut cur = match v {
        Value::Obj(o) => vm.get_prototype_of(o)?,
        _ => return Ok(false),
    };
    while let Some(p) = cur {
        if p.ptr_eq(proto) {
            return Ok(true);
        }
        cur = vm.get_prototype_of(&p)?;
    }
    Ok(false)
}

fn trace_text(vm: &mut Vm, args: &[Value]) -> JsResult<Vec<u16>> {
    let mut s = u16s("Trace");
    if !args.is_empty() {
        s.extend(u16s(": "));
        let f = format_units(vm, &Value::Undefined, args)?;
        s.extend(f);
    }
    s.extend(u16s("\n    at trace"));
    let frames = vm.frames_string();
    s.extend(u16s(&frames));
    Ok(s)
}

fn assert_text(vm: &mut Vm, rest: &[Value]) -> JsResult<Vec<u16>> {
    let mut s = u16s("Assertion failed");
    if !rest.is_empty() {
        s.extend(u16s(": "));
        let f = format_units(vm, &Value::Undefined, rest)?;
        s.extend(f);
    }
    Ok(s)
}

fn create_task(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let name = string_of(vm, &a.arg(0))?;
    let o = vm.new_object();
    o.set_str("name", Value::Str(name), WEC);
    let run = vm.native_fn("run", 1, |vm, a| {
        let f = a.arg(0);
        if !f.is_callable() {
            return vm.throw_type("fn is not a function");
        }
        let rest = if a.args.len() > 1 { &a.args[1..] } else { &[][..] };
        vm.call(&f, Value::Undefined, rest)
    });
    o.set_str("run", Value::Obj(run), WEC);
    Ok(Value::Obj(o))
}

// ============================================================================================
// symbols / class registry
// ============================================================================================

#[derive(Clone)]
struct Syms {
    stdout: Sym,
    stderr: Sym,
    group_indent: Sym,
    write_stdout: Sym,
    write_stderr: Sym,
    times: Sym,
    counts: Sym,
}

thread_local! {
    static SYMS: RefCell<Option<Syms>> = const { RefCell::new(None) };
    static CONSOLE_CLASS: RefCell<Option<(Obj, Obj)>> = const { RefCell::new(None) };
}

fn syms() -> Syms {
    SYMS.with(|s| {
        if s.borrow().is_none() {
            let mk = |n: &str| Sym::new(Some(JsStr::from_str(n)));
            *s.borrow_mut() = Some(Syms {
                stdout: mk("kStdout"),
                stderr: mk("kStderr"),
                group_indent: mk("kGroupIndent"),
                write_stdout: mk("kWriteToStdout"),
                write_stderr: mk("kWriteToStderr"),
                times: mk("kTimes"),
                counts: mk("kCounts"),
            });
        }
        s.borrow().clone().unwrap()
    })
}

struct Counts(RefCell<HashMap<String, u64>>);
struct Times(RefCell<HashMap<String, Instant>>);

// ============================================================================================
// the global console
// ============================================================================================

const METHODS: &[(&str, u32)] = &[
    ("log", 0),
    ("info", 0),
    ("debug", 0),
    ("warn", 0),
    ("error", 0),
    ("dirxml", 0),
    ("dir", 2),
    ("trace", 0),
    ("assert", 1),
    ("clear", 0),
    ("count", 0),
    ("countReset", 0),
    ("group", 0),
    ("groupCollapsed", 0),
    ("groupEnd", 0),
    ("time", 0),
    ("timeEnd", 0),
    ("timeLog", 0),
    ("timeStamp", 0),
    ("profile", 0),
    ("profileEnd", 0),
    ("table", 2),
    ("createTask", 1),
];

fn global_method(name: &str) -> NativeFn {
    match name {
        "log" | "info" | "debug" => g_log,
        "group" | "groupCollapsed" => g_group,
        "groupEnd" => g_group_end,
        "warn" | "error" => g_warn,
        "dirxml" => g_dirxml,
        "dir" => g_dir,
        "trace" => g_trace,
        "assert" => g_assert,
        "count" => g_count,
        "countReset" => g_count_reset,
        "time" => g_time,
        "timeEnd" => g_time_end,
        "timeLog" => g_time_log,
        "table" => g_table,
        "createTask" => create_task,
        _ => noop,
    }
}

pub fn setup(vm: &mut Vm) {
    let c = vm.new_object();
    for (n, len) in METHODS {
        let fo = vm.native_fn(n, *len, global_method(n));
        c.set_prop(key(n), Value::Obj(fo), WEC);
    }
    let (cc, _) = console_class(vm);
    c.set_prop(key("Console"), Value::Obj(cc), WEC);
    let ctx = vm.native_fn("", 1, context);
    c.set_prop(key("context"), Value::Obj(ctx), WEC);
    let s = syms();
    let ws = vm.native_fn("value", 1, |vm, a| {
        let t = string_of(vm, &a.arg(0))?;
        write_line(false, t.units().to_vec());
        Ok(Value::Undefined)
    });
    let we = vm.native_fn("value", 1, |vm, a| {
        let t = string_of(vm, &a.arg(0))?;
        write_line(true, t.units().to_vec());
        Ok(Value::Undefined)
    });
    c.set_prop(PropKey::Sym(s.write_stdout), Value::Obj(ws), CONFIGURABLE);
    c.set_prop(PropKey::Sym(s.write_stderr), Value::Obj(we), CONFIGURABLE);
    c.set_prop(PropKey::Sym(s.group_indent), Value::str(""), WC);
    vm.def_global("console", Value::Obj(c));
}

fn noop(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Undefined)
}

thread_local! {
    /// group indentation of the global console (only its format-based methods honor it)
    static G_INDENT: RefCell<Vec<u16>> = const { RefCell::new(Vec::new()) };
}

fn indent_lines(indent: &[u16], text: Vec<u16>) -> Vec<u16> {
    if indent.is_empty() {
        return text;
    }
    let mut out: Vec<u16> = Vec::with_capacity(text.len() + indent.len());
    out.extend_from_slice(indent);
    for c in text {
        out.push(c);
        if c == b'\n' as u16 {
            out.extend_from_slice(indent);
        }
    }
    out
}

/// Write a line from one of the global console's indentation-aware methods.
fn gw(err: bool, text: Vec<u16>) {
    let indent = G_INDENT.with(|i| i.borrow().clone());
    write_line(err, indent_lines(&indent, text));
}

/// Labels of the global console use String() (symbols allowed).
fn g_label(vm: &mut Vm, v: &Value) -> JsResult<String> {
    if v.is_undefined() {
        Ok("default".to_string())
    } else {
        Ok(string_of(vm, v)?.to_rust_string())
    }
}

fn g_log(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = join_plain(vm, a.args);
    write_line(false, s);
    Ok(Value::Undefined)
}

fn g_group(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !a.args.is_empty() {
        let s = join_plain(vm, a.args);
        write_line(false, s);
    }
    G_INDENT.with(|i| i.borrow_mut().extend(u16s("  ")));
    Ok(Value::Undefined)
}

fn g_group_end(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    G_INDENT.with(|i| {
        let mut b = i.borrow_mut();
        let n = b.len().saturating_sub(2);
        b.truncate(n);
    });
    Ok(Value::Undefined)
}

fn g_warn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = join_plain(vm, a.args);
    write_line(true, s);
    Ok(Value::Undefined)
}

fn g_dirxml(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = format_units(vm, &Value::Undefined, a.args)?;
    gw(false, s);
    Ok(Value::Undefined)
}

fn g_dir(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = inspect_units(vm, &a.arg(0), &dir_opts(&a.arg(1)), &[])?;
    gw(false, s);
    Ok(Value::Undefined)
}

fn g_trace(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = trace_text(vm, a.args)?;
    gw(true, s);
    Ok(Value::Undefined)
}

fn g_assert(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.arg(0).truthy() {
        return Ok(Value::Undefined);
    }
    let rest = if a.args.len() > 1 { &a.args[1..] } else { &[][..] };
    let s = assert_text(vm, rest)?;
    gw(true, s);
    Ok(Value::Undefined)
}

fn g_count(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let l = g_label(vm, &a.arg(0))?;
    let c = vm.host.console_counts.entry(l.clone()).or_insert(0);
    *c += 1;
    let n = *c;
    gw(false, u16s(&format!("{}: {}", l, n)));
    Ok(Value::Undefined)
}

fn g_count_reset(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    // the label is only converted when some counter exists
    if vm.host.console_counts.is_empty() {
        return Ok(Value::Undefined);
    }
    let l = g_label(vm, &a.arg(0))?;
    if let Some(c) = vm.host.console_counts.get_mut(&l) {
        *c = 0;
    }
    Ok(Value::Undefined)
}

fn g_time(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let l = g_label(vm, &a.arg(0))?;
    if vm.host.console_timers.contains_key(&l) {
        gw(true, u16s(&format!("Warning: Label '{}' already exists for console.time()", l)));
        return Ok(Value::Undefined);
    }
    vm.host.console_timers.insert(l, Instant::now());
    Ok(Value::Undefined)
}

fn g_time_end(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let l = g_label(vm, &a.arg(0))?;
    match vm.host.console_timers.remove(&l) {
        Some(t) => gw(false, u16s(&format!("{}: {}", l, fmt_elapsed(t.elapsed())))),
        None => gw(true, u16s(&format!("Warning: No such label '{}' for console.timeEnd()", l))),
    }
    Ok(Value::Undefined)
}

fn g_time_log(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let l = g_label(vm, &a.arg(0))?;
    let start = vm.host.console_timers.get(&l).copied();
    match start {
        Some(t) => {
            let mut s = u16s(&format!("{}: {}", l, fmt_elapsed(t.elapsed())));
            if a.args.len() > 1 {
                s.push(b' ' as u16);
                let f = format_units(vm, &Value::Undefined, &a.args[1..])?;
                s.extend(f);
            }
            gw(false, s);
        }
        None => gw(true, u16s(&format!("Warning: No such label '{}' for console.timeLog()", l))),
    }
    Ok(Value::Undefined)
}

fn g_table(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match render_table(vm, &a.arg(0), &a.arg(1))? {
        Some(t) => gw(false, t),
        None => {
            let s = format_units(vm, &Value::Undefined, &[a.arg(0)])?;
            gw(false, s);
        }
    }
    Ok(Value::Undefined)
}

fn context(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let (cc, _) = console_class(vm);
    let process = vm.host.process_obj.clone().map(Value::Obj).unwrap_or(Value::Undefined);
    let out = vm.get_prop_of(&process, &key("stdout"))?;
    let err = vm.get_prop_of(&process, &key("stderr"))?;
    vm.construct(&Value::Obj(cc), &[out, err], None)
}

// ============================================================================================
// console.Console
// ============================================================================================

const INSTANCE_METHODS: &[&str] = &[
    "log", "info", "debug", "dirxml", "error", "warn", "dir", "trace", "assert", "clear", "count", "countReset", "group", "groupCollapsed",
    "groupEnd", "time", "timeEnd", "timeLog", "timeStamp", "profile", "profileEnd", "table", "createTask",
];

fn method_len(name: &str) -> u32 {
    METHODS.iter().find(|m| m.0 == name).map(|m| m.1).unwrap_or(0)
}

fn instance_method(name: &str) -> NativeFn {
    match name {
        "log" | "info" | "debug" | "dirxml" => i_log,
        "error" | "warn" => i_warn,
        "dir" => i_dir,
        "trace" => i_trace,
        "assert" => i_assert,
        "count" => i_count,
        "countReset" => i_count_reset,
        "group" | "groupCollapsed" => i_group,
        "groupEnd" => i_group_end,
        "time" => i_time,
        "timeEnd" => i_time_end,
        "timeLog" => i_time_log,
        "table" => i_table,
        "createTask" => create_task,
        _ => noop,
    }
}

/// (constructor, prototype) of console.Console, created once.
fn console_class(vm: &mut Vm) -> (Obj, Obj) {
    if let Some(c) = CONSOLE_CLASS.with(|c| c.borrow().clone()) {
        return c;
    }
    let proto = vm.new_object();
    let ctor = vm.native_ctor("Console", 2, console_ctor, &proto);
    proto.set_prop(key("Console"), Value::Obj(ctor.clone()), WEC);
    for n in INSTANCE_METHODS {
        let f = vm.native_fn(n, method_len(n), instance_method(n));
        proto.set_prop(key(n), Value::Obj(f), WEC);
    }
    CONSOLE_CLASS.with(|c| *c.borrow_mut() = Some((ctor.clone(), proto.clone())));
    (ctor, proto)
}

fn is_writable(vm: &mut Vm, v: &Value) -> JsResult<bool> {
    match v {
        Value::Obj(o) => Ok(vm.get(o, &key("write"), v)?.is_callable()),
        _ => Ok(false),
    }
}

fn console_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return vm.throw_type("Class constructor cannot be invoked without 'new'");
    }
    let first = a.arg(0);
    let (out, err) = if is_writable(vm, &first)? {
        (first.clone(), a.arg(1))
    } else if let Value::Obj(o) = &first {
        let so = vm.get(o, &key("stdout"), &first)?;
        let se = vm.get(o, &key("stderr"), &first)?;
        (so, se)
    } else {
        (first.clone(), Value::Undefined)
    };
    if !is_writable(vm, &out)? {
        return vm.throw_type("The \"stdout\" argument must be an instance of a writable stream");
    }
    let err = if err.is_undefined() { out.clone() } else { err };
    if !is_writable(vm, &err)? {
        return vm.throw_type("The \"stderr\" argument must be an instance of a writable stream");
    }
    let (_, proto) = console_class(vm);
    let p = vm.proto_from_nt(&a.new_target, &proto)?;
    let inst = Obj::new(Some(p.clone()), ObjKind::Ordinary);
    let s = syms();
    inst.set_prop(PropKey::Sym(s.stdout.clone()), out.clone(), WC);
    inst.set_prop(PropKey::Sym(s.stderr.clone()), err.clone(), WC);
    inst.set_prop(PropKey::Sym(s.group_indent.clone()), Value::str(""), WC);
    let ws = vm.native_closure("value", 1, stream_write, vec![out]);
    let we = vm.native_closure("value", 1, stream_write, vec![err]);
    inst.set_prop(PropKey::Sym(s.write_stdout.clone()), Value::Obj(ws), CONFIGURABLE);
    inst.set_prop(PropKey::Sym(s.write_stderr.clone()), Value::Obj(we), CONFIGURABLE);
    let times = Obj::new(None, ObjKind::Host(Box::new(Times(RefCell::new(HashMap::new())))));
    let counts = Obj::new(None, ObjKind::Host(Box::new(Counts(RefCell::new(HashMap::new())))));
    inst.set_prop(PropKey::Sym(s.times.clone()), Value::Obj(times), WC);
    inst.set_prop(PropKey::Sym(s.counts.clone()), Value::Obj(counts), WC);
    for n in INSTANCE_METHODS {
        let m = vm.get(&p, &key(n), &Value::Obj(inst.clone()))?;
        let b = vm.native_closure(&format!("bound {}", n), 0, bound_call, vec![Value::Obj(inst.clone()), m]);
        inst.set_prop(key(n), Value::Obj(b), WEC);
    }
    Ok(Value::Obj(inst))
}

fn bound_call(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    vm.call(&a.slot(1), a.slot(0), a.args)
}

fn stream_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let stream = a.slot(0);
    let mut s = string_of(vm, &a.arg(0))?.units().to_vec();
    s.push(b'\n' as u16);
    let w = vm.get_prop_of(&stream, &key("write"))?;
    vm.call(&w, stream, &[jsv(s)])?;
    Ok(Value::Undefined)
}

/// The Console instance `this`, or the reference's error for a foreign receiver.
fn inst_of(vm: &mut Vm, this: &Value) -> JsResult<Obj> {
    let s = syms();
    if let Value::Obj(o) = this {
        if o.get_own_data(&PropKey::Sym(s.stdout)).is_some() {
            return Ok(o.clone());
        }
    }
    vm.throw_type("expression is not a function")
}

/// Write `text` (indented by the current group indentation) plus a newline to the stream.
fn inst_write(vm: &mut Vm, inst: &Obj, err: bool, text: Vec<u16>) -> JsResult<()> {
    let s = syms();
    let indent = match inst.get_own_data(&PropKey::Sym(s.group_indent.clone())) {
        Some(Value::Str(i)) => i.units().to_vec(),
        _ => Vec::new(),
    };
    let mut out = indent_lines(&indent, text);
    out.push(b'\n' as u16);
    let stream = inst.get_own_data(&PropKey::Sym(if err { s.stderr } else { s.stdout })).unwrap_or(Value::Undefined);
    let w = vm.get_prop_of(&stream, &key("write"))?;
    vm.call(&w, stream, &[jsv(out)])?;
    Ok(())
}

fn i_log(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let inst = inst_of(vm, &a.this)?;
    let s = format_units(vm, &Value::Undefined, a.args)?;
    inst_write(vm, &inst, false, s)?;
    Ok(Value::Undefined)
}

fn i_warn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let inst = inst_of(vm, &a.this)?;
    let s = format_units(vm, &Value::Undefined, a.args)?;
    inst_write(vm, &inst, true, s)?;
    Ok(Value::Undefined)
}

fn i_dir(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let inst = inst_of(vm, &a.this)?;
    let s = inspect_units(vm, &a.arg(0), &dir_opts(&a.arg(1)), &[])?;
    inst_write(vm, &inst, false, s)?;
    Ok(Value::Undefined)
}

fn i_trace(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let inst = inst_of(vm, &a.this)?;
    let s = trace_text(vm, a.args)?;
    inst_write(vm, &inst, true, s)?;
    Ok(Value::Undefined)
}

fn i_assert(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let inst = inst_of(vm, &a.this)?;
    if a.arg(0).truthy() {
        return Ok(Value::Undefined);
    }
    let rest = if a.args.len() > 1 { &a.args[1..] } else { &[][..] };
    let s = assert_text(vm, rest)?;
    inst_write(vm, &inst, true, s)?;
    Ok(Value::Undefined)
}

fn with_counts<R>(inst: &Obj, f: impl FnOnce(&mut HashMap<String, u64>) -> R) -> Option<R> {
    let s = syms();
    if let Some(Value::Obj(c)) = inst.get_own_data(&PropKey::Sym(s.counts)) {
        if let ObjKind::Host(h) = &c.borrow().kind {
            if let Some(m) = h.downcast_ref::<Counts>() {
                return Some(f(&mut m.0.borrow_mut()));
            }
        }
    }
    None
}

fn with_times<R>(inst: &Obj, f: impl FnOnce(&mut HashMap<String, Instant>) -> R) -> Option<R> {
    let s = syms();
    if let Some(Value::Obj(c)) = inst.get_own_data(&PropKey::Sym(s.times)) {
        if let ObjKind::Host(h) = &c.borrow().kind {
            if let Some(m) = h.downcast_ref::<Times>() {
                return Some(f(&mut m.0.borrow_mut()));
            }
        }
    }
    None
}

fn i_count(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let inst = inst_of(vm, &a.this)?;
    let l = label_of(vm, &a.arg(0))?;
    let n = with_counts(&inst, |m| {
        let c = m.entry(l.clone()).or_insert(0);
        *c += 1;
        *c
    })
    .unwrap_or(1);
    inst_write(vm, &inst, false, u16s(&format!("{}: {}", l, n)))?;
    Ok(Value::Undefined)
}

fn i_count_reset(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let inst = inst_of(vm, &a.this)?;
    // the label is only converted when some counter exists
    if with_counts(&inst, |m| m.is_empty()).unwrap_or(true) {
        return Ok(Value::Undefined);
    }
    let l = label_of(vm, &a.arg(0))?;
    with_counts(&inst, |m| {
        if let Some(c) = m.get_mut(&l) {
            *c = 0;
        }
    });
    Ok(Value::Undefined)
}

fn i_group(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let inst = inst_of(vm, &a.this)?;
    if !a.args.is_empty() {
        let s = format_units(vm, &Value::Undefined, a.args)?;
        inst_write(vm, &inst, false, s)?;
    }
    let s = syms();
    let k = PropKey::Sym(s.group_indent);
    let cur = match inst.get_own_data(&k) {
        Some(Value::Str(i)) => i.units().to_vec(),
        _ => Vec::new(),
    };
    let mut next = cur;
    next.extend(u16s("  "));
    inst.set_prop(k, jsv(next), WC);
    Ok(Value::Undefined)
}

fn i_group_end(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let inst = inst_of(vm, &a.this)?;
    let s = syms();
    let k = PropKey::Sym(s.group_indent);
    let mut cur = match inst.get_own_data(&k) {
        Some(Value::Str(i)) => i.units().to_vec(),
        _ => Vec::new(),
    };
    let n = cur.len().saturating_sub(2);
    cur.truncate(n);
    inst.set_prop(k, jsv(cur), WC);
    Ok(Value::Undefined)
}

fn i_time(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let inst = inst_of(vm, &a.this)?;
    let l = label_of(vm, &a.arg(0))?;
    let exists = with_times(&inst, |m| {
        if m.contains_key(&l) {
            true
        } else {
            m.insert(l.clone(), Instant::now());
            false
        }
    })
    .unwrap_or(false);
    if exists {
        inst_write(vm, &inst, true, u16s(&format!("Warning: Label '{}' already exists for console.time()", l)))?;
    }
    Ok(Value::Undefined)
}

fn i_time_end(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let inst = inst_of(vm, &a.this)?;
    let l = label_of(vm, &a.arg(0))?;
    match with_times(&inst, |m| m.remove(&l)).flatten() {
        Some(t) => inst_write(vm, &inst, false, u16s(&format!("{}: {}", l, fmt_elapsed(t.elapsed()))))?,
        None => inst_write(vm, &inst, true, u16s(&format!("Warning: No such label '{}' for console.timeEnd()", l)))?,
    }
    Ok(Value::Undefined)
}

fn i_time_log(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let inst = inst_of(vm, &a.this)?;
    let l = label_of(vm, &a.arg(0))?;
    match with_times(&inst, |m| m.get(&l).copied()).flatten() {
        Some(t) => {
            let mut s = u16s(&format!("{}: {}", l, fmt_elapsed(t.elapsed())));
            if a.args.len() > 1 {
                s.push(b' ' as u16);
                let f = format_units(vm, &Value::Undefined, &a.args[1..])?;
                s.extend(f);
            }
            inst_write(vm, &inst, false, s)?;
        }
        None => inst_write(vm, &inst, true, u16s(&format!("Warning: No such label '{}' for console.timeLog()", l)))?,
    }
    Ok(Value::Undefined)
}

fn i_table(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let inst = inst_of(vm, &a.this)?;
    let s = match render_table(vm, &a.arg(0), &a.arg(1))? {
        Some(t) => t,
        None => format_units(vm, &Value::Undefined, &[a.arg(0)])?,
    };
    inst_write(vm, &inst, false, s)?;
    Ok(Value::Undefined)
}
