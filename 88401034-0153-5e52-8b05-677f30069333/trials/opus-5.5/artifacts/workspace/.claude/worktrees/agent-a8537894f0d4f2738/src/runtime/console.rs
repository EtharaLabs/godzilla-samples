// The console object.

use super::{display_value, write_stderr, write_stdout};
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let c = vm.new_object();
    let methods: &[(&str, NativeFn)] = &[
        ("log", log),
        ("info", log),
        ("debug", log),
        ("warn", warn),
        ("error", warn),
        ("dirxml", log),
        ("dir", dir),
        ("trace", trace),
        ("assert", assert),
        ("clear", noop),
        ("count", count),
        ("countReset", count_reset),
        ("group", group),
        ("groupCollapsed", group),
        ("groupEnd", noop),
        ("time", time),
        ("timeEnd", time_end),
        ("timeLog", time_log),
        ("timeStamp", noop),
        ("profile", noop),
        ("profileEnd", noop),
        ("table", table),
        ("createTask", create_task),
    ];
    for (n, f) in methods {
        let fo = vm.native_fn(n, 0, *f);
        c.set_prop(PropKey::from_str(n), Value::Obj(fo), WEC);
    }
    let cc = vm.native_fn("Console", 1, console_ctor);
    vm.make_ctor(&cc);
    let cp = vm.new_object();
    cc.set_prop(vm.intr.key_prototype.clone(), Value::Obj(cp.clone()), 0);
    cp.set_prop(vm.intr.key_constructor.clone(), Value::Obj(cc.clone()), WC);
    c.set_prop(PropKey::from_str("Console"), Value::Obj(cc), WEC);
    let ctx = vm.native_fn("context", 1, context);
    c.set_prop(PropKey::from_str("context"), Value::Obj(ctx), WEC);
    vm.def_global("console", Value::Obj(c));
}

fn fmt_args(vm: &mut Vm, args: &[Value]) -> String {
    let parts: Vec<String> = args.iter().map(|v| display_value(vm, v)).collect();
    parts.join(" ")
}

fn log(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = fmt_args(vm, a.args);
    write_stdout(vm, &format!("{}\n", s));
    Ok(Value::Undefined)
}

fn warn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = fmt_args(vm, a.args);
    write_stderr(&format!("{}\n", s));
    Ok(Value::Undefined)
}

fn noop(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Undefined)
}

fn group(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !a.args.is_empty() {
        let s = fmt_args(vm, a.args);
        write_stdout(vm, &format!("{}\n", s));
    }
    Ok(Value::Undefined)
}

fn dir(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = super::util::inspect_with_options(vm, &a.arg(0), &a.arg(1))?;
    write_stdout(vm, &format!("{}\n", s));
    Ok(Value::Undefined)
}

fn trace(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let msg = fmt_args(vm, a.args);
    let mut s = if a.args.is_empty() { "Trace".to_string() } else { format!("Trace: {}", msg) };
    s.push_str("\n    at trace");
    for e in vm.trace.iter().rev() {
        s.push_str("\n    at ");
        s.push_str(&e.name.to_rust_string());
    }
    write_stderr(&format!("{}\n", s));
    Ok(Value::Undefined)
}

fn assert(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.arg(0).truthy() {
        return Ok(Value::Undefined);
    }
    let rest = if a.args.len() > 1 { &a.args[1..] } else { &[][..] };
    if rest.is_empty() {
        write_stderr("Assertion failed\n");
    } else {
        let s = fmt_args(vm, rest);
        write_stderr(&format!("Assertion failed: {}\n", s));
    }
    Ok(Value::Undefined)
}

fn label_of(vm: &mut Vm, v: &Value) -> JsResult<String> {
    if v.is_undefined() {
        Ok("default".to_string())
    } else {
        Ok(vm.to_string(v)?.to_rust_string())
    }
}

fn count(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let l = label_of(vm, &a.arg(0))?;
    let c = vm.host.console_counts.entry(l.clone()).or_insert(0);
    *c += 1;
    let n = *c;
    write_stdout(vm, &format!("{}: {}\n", l, n));
    Ok(Value::Undefined)
}

fn count_reset(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let l = label_of(vm, &a.arg(0))?;
    if let Some(c) = vm.host.console_counts.get_mut(&l) {
        *c = 0;
    }
    Ok(Value::Undefined)
}

fn time(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let l = label_of(vm, &a.arg(0))?;
    vm.host.console_timers.insert(l, std::time::Instant::now());
    Ok(Value::Undefined)
}

fn fmt_elapsed(d: std::time::Duration) -> String {
    let ms = d.as_secs_f64() * 1000.0;
    if ms >= 1000.0 {
        format!("{:.3}s", ms / 1000.0)
    } else {
        format!("{:.3}ms", ms)
    }
}

fn time_end(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let l = label_of(vm, &a.arg(0))?;
    match vm.host.console_timers.remove(&l) {
        Some(t) => {
            let s = format!("{}: {}\n", l, fmt_elapsed(t.elapsed()));
            write_stdout(vm, &s);
        }
        None => write_stderr(&format!("Warning: No such label '{}' for console.timeEnd()\n", l)),
    }
    Ok(Value::Undefined)
}

fn time_log(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let l = label_of(vm, &a.arg(0))?;
    match vm.host.console_timers.get(&l) {
        Some(t) => {
            let mut s = format!("{}: {}", l, fmt_elapsed(t.elapsed()));
            if a.args.len() > 1 {
                s.push(' ');
                s.push_str(&fmt_args(vm, &a.args[1..]));
            }
            write_stdout(vm, &format!("{}\n", s));
        }
        None => write_stderr(&format!("Warning: No such label '{}' for console.timeLog()\n", l)),
    }
    Ok(Value::Undefined)
}

fn create_task(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let o = vm.new_object();
    let run = vm.native_fn("run", 1, |vm, a| vm.call(&a.arg(0), Value::Undefined, &[]));
    o.set_str("run", Value::Obj(run), WEC);
    Ok(Value::Obj(o))
}

fn context(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let c = vm.global.get_own_str("console").unwrap_or(Value::Undefined);
    Ok(c)
}

fn console_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    // new Console(stdout, stderr) / new Console({stdout, stderr})
    let first = a.arg(0);
    let (out, err) = if let Value::Obj(o) = &first {
        let w = vm.get_str(o, "write")?;
        if w.is_callable() {
            let e = if a.arg(1).is_undefined() { first.clone() } else { a.arg(1) };
            (first.clone(), e)
        } else {
            let so = vm.get_str(o, "stdout")?;
            let se = vm.get_str(o, "stderr")?;
            let se = if se.is_undefined() { so.clone() } else { se };
            (so, se)
        }
    } else {
        (first.clone(), a.arg(1))
    };
    let ok = match &out {
        Value::Obj(o) => vm.get_str(o, "write")?.is_callable(),
        _ => false,
    };
    if !ok {
        return vm.throw_type("The \"stdout\" argument must be an instance of a writable stream");
    }
    let c = vm.new_object();
    for (n, which) in [("log", 0), ("info", 0), ("debug", 0), ("warn", 1), ("error", 1)] {
        let target = if which == 0 { out.clone() } else { err.clone() };
        let f = vm.native_closure(n, 0, console_stream_write, vec![target]);
        c.set_prop(PropKey::from_str(n), Value::Obj(f), WEC);
    }
    Ok(Value::Obj(c))
}

fn console_stream_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = fmt_args(vm, a.args);
    let stream = a.slot(0);
    let w = vm.get_prop_of(&stream, &PropKey::from_str("write"))?;
    vm.call(&w, stream, &[Value::str(&format!("{}\n", s))])?;
    Ok(Value::Undefined)
}

// ---------------- console.table ----------------

fn cell(vm: &mut Vm, v: &Value) -> String {
    match v {
        Value::Obj(_) => super::util::inspect_value(vm, v, 1).unwrap_or_default(),
        other => display_value(vm, other),
    }
}

fn str_width(s: &str) -> usize {
    s.chars().count()
}

fn table(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let data = a.arg(0);
    let o = match &data {
        Value::Obj(o) => o.clone(),
        _ => return log(vm, a),
    };
    let filter: Option<Vec<String>> = match a.arg(1) {
        Value::Obj(f) => {
            let vals = crate::builtins::array::array_like_to_vec(vm, &Value::Obj(f))?;
            let mut v = Vec::new();
            for x in vals {
                v.push(vm.to_string(&x)?.to_rust_string());
            }
            Some(v)
        }
        _ => None,
    };
    // rows: (index label, value)
    let mut rows: Vec<(String, Value)> = Vec::new();
    let is_map = matches!(o.borrow().kind, ObjKind::Map(_));
    let is_set = matches!(o.borrow().kind, ObjKind::Set(_));
    if is_map || is_set {
        let entries: Vec<(Value, Value)> = match &o.borrow().kind {
            ObjKind::Map(m) | ObjKind::Set(m) => m.entries.iter().flatten().cloned().collect(),
            _ => Vec::new(),
        };
        for (i, (k, v)) in entries.into_iter().enumerate() {
            if is_map {
                let ks = display_value(vm, &k);
                rows.push((ks, v));
            } else {
                rows.push((i.to_string(), k));
            }
        }
    } else {
        let keys = vm.own_property_keys(&o)?;
        for k in keys {
            if let PropKey::Str(s) = &k {
                if let Some(d) = vm.get_own_property(&o, &k)? {
                    if d.enumerable == Some(true) {
                        let v = vm.get(&o, &k, &data)?;
                        rows.push((s.to_rust_string(), v));
                    }
                }
            }
        }
    }
    let mut columns: Vec<String> = Vec::new();
    let mut has_values = false;
    let mut row_cells: Vec<(String, Vec<(String, String)>, Option<String>)> = Vec::new();
    for (label, v) in rows {
        let mut cells = Vec::new();
        let mut value_cell = None;
        match &v {
            Value::Obj(ro) if !ro.is_callable() => {
                let keys = vm.own_property_keys(ro)?;
                for k in keys {
                    if let PropKey::Str(s) = &k {
                        if let Some(d) = vm.get_own_property(ro, &k)? {
                            if d.enumerable != Some(true) {
                                continue;
                            }
                        }
                        let name = s.to_rust_string();
                        if let Some(f) = &filter {
                            if !f.contains(&name) {
                                continue;
                            }
                        }
                        let cv = vm.get(ro, &k, &v)?;
                        let text = cell(vm, &cv);
                        if !columns.contains(&name) {
                            columns.push(name.clone());
                        }
                        cells.push((name, text));
                    }
                }
            }
            other => {
                has_values = true;
                value_cell = Some(cell(vm, other));
            }
        }
        row_cells.push((label, cells, value_cell));
    }
    if let Some(f) = &filter {
        columns = f.clone();
    }
    let mut headers = vec!["(index)".to_string()];
    headers.extend(columns.iter().cloned());
    if has_values {
        headers.push("Values".to_string());
    }
    let mut grid: Vec<Vec<String>> = Vec::new();
    for (label, cells, vc) in &row_cells {
        let mut r = vec![label.clone()];
        for c in &columns {
            r.push(cells.iter().find(|(n, _)| n == c).map(|(_, t)| t.clone()).unwrap_or_default());
        }
        if has_values {
            r.push(vc.clone().unwrap_or_default());
        }
        grid.push(r);
    }
    let widths: Vec<usize> = (0..headers.len())
        .map(|i| {
            let mut w = str_width(&headers[i]);
            for r in &grid {
                w = w.max(str_width(&r[i]));
            }
            w + 2
        })
        .collect();
    let center = |s: &str, w: usize| -> String {
        let l = str_width(s);
        let left = (w - l) / 2;
        let right = w - l - left;
        format!("{}{}{}", " ".repeat(left), s, " ".repeat(right))
    };
    let line = |l: &str, m: &str, r: &str| -> String {
        let segs: Vec<String> = widths.iter().map(|w| "─".repeat(*w)).collect();
        format!("{}{}{}", l, segs.join(m), r)
    };
    let mut out = String::new();
    out.push_str(&line("┌", "┬", "┐"));
    out.push('\n');
    let hdr: Vec<String> = headers.iter().enumerate().map(|(i, h)| center(h, widths[i])).collect();
    out.push_str(&format!("│{}│\n", hdr.join("│")));
    out.push_str(&line("├", "┼", "┤"));
    out.push('\n');
    for r in &grid {
        let cs: Vec<String> = r.iter().enumerate().map(|(i, c)| center(c, widths[i])).collect();
        out.push_str(&format!("│{}│\n", cs.join("│")));
    }
    out.push_str(&line("└", "┴", "┘"));
    out.push('\n');
    write_stdout(vm, &out);
    Ok(Value::Undefined)
}
