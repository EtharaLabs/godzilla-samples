// node:util (inspect, format, promisify, types, parseArgs, MIMEType, ...), node:assert and
// node:async_hooks.
//
// The reference runtime ships its own small implementations of these modules: a single-line
// util.inspect without colors or line breaking, a format() built on it, and an assert module
// whose failures simply say "Assertion failed". Everything here reproduces that observable
// behavior (message texts, property orders, odd corner cases included).

use crate::bytecode::Op;
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

// ============================================================================================
// small helpers
// ============================================================================================

fn key(s: &str) -> PropKey {
    PropKey::from_str(s)
}

fn u16s(s: &str) -> Vec<u16> {
    s.encode_utf16().collect()
}

fn jsv(units: Vec<u16>) -> Value {
    Value::Str(JsStr::from_units(units))
}

/// `String(v)`: ToString, except that symbols become their descriptive string.
pub fn string_of(vm: &mut Vm, v: &Value) -> JsResult<JsStr> {
    match v {
        Value::Sym(s) => Ok(JsStr::from_str(&s.descriptive_string())),
        _ => vm.to_string(v),
    }
}

/// An error object of the given kind with an own enumerable `code` property (Node style).
fn coded_error(vm: &mut Vm, kind: &str, msg: &str, code: &str) -> Value {
    let e = vm.make_error(kind, msg);
    if let Value::Obj(o) = &e {
        o.set_prop(key("code"), Value::str(code), WEC);
    }
    e
}

/// Present a native as an ordinary JS `function`: constructible, with its own `prototype`.
pub fn plain_fn(vm: &mut Vm, name: &str, len: u32, f: NativeFn, slots: Vec<Value>) -> Obj {
    let inner = vm.native_closure(name, len, f, slots);
    let outer = vm.native_closure(name, len, plain_fn_shim, vec![Value::Obj(inner)]);
    vm.make_ctor(&outer);
    let proto = vm.new_object();
    proto.set_prop(vm.intr.key_constructor.clone(), Value::Obj(outer.clone()), WC);
    outer.set_prop(vm.intr.key_prototype.clone(), Value::Obj(proto), WRITABLE);
    outer
}

fn plain_fn_shim(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let inner = a.slot(0);
    match &a.new_target {
        None => vm.call(&inner, a.this.clone(), a.args),
        Some(nt) => {
            let fallback = vm.intr.object_proto.clone();
            let proto = vm.proto_from_nt(&Some(nt.clone()), &fallback)?;
            let obj = Value::Obj(Obj::new(Some(proto), ObjKind::Ordinary));
            let r = vm.call(&inner, obj.clone(), a.args)?;
            Ok(if r.is_object() { r } else { obj })
        }
    }
}

/// Define `name` on `target` as an enumerable plain function.
fn def_plain(vm: &mut Vm, target: &Obj, name: &str, len: u32, f: NativeFn) -> Obj {
    let fo = plain_fn(vm, name, len, f, Vec::new());
    target.set_prop(key(name), Value::Obj(fo.clone()), WEC);
    fo
}

/// Define `name` on `target` as an enumerable arrow-like function (no `prototype`).
fn def_arrow(vm: &mut Vm, target: &Obj, name: &str, len: u32, f: NativeFn) -> Obj {
    let fo = vm.native_fn(name, len, f);
    target.set_prop(key(name), Value::Obj(fo.clone()), WEC);
    fo
}

/// A class-like constructor (calling it without `new` throws).
fn make_class(vm: &mut Vm, name: &str, len: u32, f: NativeFn, parent_proto: Option<Obj>) -> (Obj, Obj) {
    let pp = parent_proto.unwrap_or_else(|| vm.intr.object_proto.clone());
    let proto = Obj::new(Some(pp), ObjKind::Ordinary);
    let c = vm.native_ctor(name, len, f, &proto);
    (c, proto)
}

fn class_call_error<T>(vm: &mut Vm) -> JsResult<T> {
    vm.throw_type("Class constructor cannot be invoked without 'new'")
}

/// Is `proto` on the prototype chain of `v` (`v instanceof C` for a builtin C)?
fn proto_chain_has(vm: &mut Vm, v: &Value, proto: &Obj) -> JsResult<bool> {
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

fn is_error_instance(vm: &mut Vm, v: &Value) -> JsResult<bool> {
    let ep = vm.intr.error_proto.clone();
    proto_chain_has(vm, v, &ep)
}

/// The tag `Object.prototype.toString` would report for an object (None for primitives).
fn tag_of(vm: &mut Vm, v: &Value) -> JsResult<Option<String>> {
    let o = match v {
        Value::Obj(o) => o.clone(),
        _ => return Ok(None),
    };
    let builtin = crate::builtins::object::builtin_tag(vm, &o)?;
    let t = vm.get(&o, &PropKey::Sym(vm.intr.sym_to_string_tag.clone()), v)?;
    Ok(Some(match t {
        Value::Str(s) => s.to_rust_string(),
        _ => builtin.to_string(),
    }))
}

/// `this.name(...args)`, failing like the reference does when the method is missing.
fn call_method(vm: &mut Vm, this: &Value, name: &str, args: &[Value]) -> JsResult<Value> {
    let f = vm.get_prop_of(this, &key(name))?;
    if !f.is_callable() {
        return vm.throw_type(format!("(intermediate value).{} is not a function", name));
    }
    vm.call(&f, this.clone(), args)
}

/// Account for `n` JS frames of the reference's recursive JS implementations, so deeply nested
/// structures hit "Maximum call stack size exceeded" at the same nesting level.
fn enter_frames(vm: &mut Vm, n: usize) -> JsResult<()> {
    if vm.depth + vm.depth_offset + n > crate::vm::MAX_DEPTH {
        return vm.throw_range("Maximum call stack size exceeded");
    }
    vm.depth += n;
    Ok(())
}

fn leave_frames(vm: &mut Vm, n: usize) {
    vm.depth -= n;
}

fn get_global(vm: &mut Vm, name: &str) -> Value {
    vm.global.get_own_str(name).unwrap_or(Value::Undefined)
}

fn new_null_proto_object() -> Obj {
    Obj::new(None, ObjKind::Ordinary)
}

// ============================================================================================
// util.inspect
// ============================================================================================

/// Per-call inspection state: the merged options object (also handed to custom inspectors),
/// the depth limit and the objects currently being formatted (for `[Circular *1]`).
struct Insp {
    depth: Value,
    show_hidden: bool,
    opts: Value,
    seen: Vec<Obj>,
}

impl Insp {
    /// options = Object.assign({ depth: 2, showHidden: false, colors: false }, user, extra);
    /// a boolean `user` is the legacy showHidden argument.
    fn new(vm: &mut Vm, user: &Value, extra: &[(&str, Value)]) -> JsResult<Insp> {
        let o = vm.new_object();
        o.set_str("depth", Value::Num(2.0), WEC);
        o.set_str("showHidden", Value::Bool(false), WEC);
        o.set_str("colors", Value::Bool(false), WEC);
        match user {
            Value::Obj(_) => vm.copy_data_properties(&o, user, &[])?,
            Value::Bool(b) => o.set_str("showHidden", Value::Bool(*b), WEC),
            _ => {}
        }
        for (k, v) in extra {
            vm.create_data_property(&o, key(k), v.clone())?;
        }
        let ov = Value::Obj(o.clone());
        let depth = vm.get(&o, &key("depth"), &ov)?;
        let show_hidden = vm.get(&o, &key("showHidden"), &ov)?.truthy();
        Ok(Insp { depth, show_hidden, opts: ov, seen: Vec::new() })
    }
}

enum Piece {
    U(Vec<u16>),
    /// a value returned as-is by the top-level call (stack/toISOString/toString results)
    Raw(Value),
}

fn quote_js(s: &[u16]) -> Vec<u16> {
    let mut out = Vec::with_capacity(s.len() + 2);
    out.push(b'\'' as u16);
    for &c in s {
        if c == b'\'' as u16 {
            out.push(b'\\' as u16);
        }
        out.push(c);
    }
    out.push(b'\'' as u16);
    out
}

fn is_ident_key(s: &[u16]) -> bool {
    let ok_start = |c: u16| c < 128 && ((c as u8).is_ascii_alphabetic() || c == b'_' as u16 || c == b'$' as u16);
    let ok_rest = |c: u16| ok_start(c) || (c < 128 && (c as u8).is_ascii_digit());
    match s.first() {
        Some(&c) if ok_start(c) => s[1..].iter().all(|&c| ok_rest(c)),
        _ => false,
    }
}

fn fmt_primitive(v: &Value, top: bool) -> Vec<u16> {
    match v {
        Value::Str(s) => {
            if top {
                s.units().to_vec()
            } else {
                quote_js(s.units())
            }
        }
        Value::Num(n) => u16s(&crate::numconv::number_to_string(*n)),
        Value::BigInt(b) => u16s(&format!("{}n", b.to_string_radix(10))),
        Value::Bool(b) => u16s(if *b { "true" } else { "false" }),
        Value::Undefined | Value::Empty => u16s("undefined"),
        Value::Null => u16s("null"),
        Value::Sym(s) => u16s(&s.descriptive_string()),
        Value::Obj(_) => Vec::new(),
    }
}

/// Format one value. Frame accounting mirrors the reference's recursive JS formatter: one
/// frame per value, one per container and one per property (see `fmt_nested`).
fn fmt_val(vm: &mut Vm, cx: &mut Insp, v: &Value, level: u32, top: bool) -> JsResult<Piece> {
    enter_frames(vm, 1)?;
    let r = fmt_val_body(vm, cx, v, level, top);
    leave_frames(vm, 1);
    r
}

fn fmt_val_body(vm: &mut Vm, cx: &mut Insp, v: &Value, level: u32, top: bool) -> JsResult<Piece> {
    let o = match v {
        Value::Obj(o) => o.clone(),
        _ => return Ok(Piece::U(fmt_primitive(v, top))),
    };
    if o.is_callable() {
        let name = vm.get(&o, &vm.intr.key_name.clone(), v)?;
        let mut out = Vec::new();
        if name.truthy() {
            out.extend(u16s("[Function: "));
            out.extend_from_slice(string_of(vm, &name)?.units());
            out.push(b']' as u16);
        } else {
            out.extend(u16s("[Function (anonymous)]"));
        }
        return Ok(Piece::U(out));
    }
    if cx.seen.iter().any(|s| s.ptr_eq(&o)) {
        return Ok(Piece::U(u16s("[Circular *1]")));
    }
    let csym = vm.symbol_for("nodejs.util.inspect.custom");
    let custom = vm.get(&o, &PropKey::Sym(csym), v)?;
    if custom.is_callable() {
        let opts = cx.opts.clone();
        let r = vm.call(&custom, v.clone(), &[Value::Num(level as f64), opts])?;
        return Ok(Piece::U(string_of(vm, &r)?.units().to_vec()));
    }
    if is_error_instance(vm, v)? {
        let stack = vm.get(&o, &key("stack"), v)?;
        if stack.truthy() {
            return Ok(Piece::Raw(stack));
        }
        let name = vm.get(&o, &vm.intr.key_name.clone(), v)?;
        let msg = vm.get(&o, &vm.intr.key_message.clone(), v)?;
        let mut out = vm.to_string(&name)?.units().to_vec();
        out.extend(u16s(": "));
        out.extend_from_slice(vm.to_string(&msg)?.units());
        return Ok(Piece::U(out));
    }
    let date_proto = vm.intr.date_proto.clone();
    if proto_chain_has(vm, v, &date_proto)? {
        let t = match &o.borrow().kind {
            ObjKind::Date(t) => Some(*t),
            _ => None,
        };
        return match t {
            None => vm.throw_type("this is not a Date object"),
            Some(t) if t.is_nan() => Ok(Piece::U(u16s("Invalid Date"))),
            Some(_) => Ok(Piece::Raw(call_method(vm, v, "toISOString", &[])?)),
        };
    }
    let re_proto = vm.intr.regexp_proto.clone();
    if proto_chain_has(vm, v, &re_proto)? {
        return Ok(Piece::Raw(call_method(vm, v, "toString", &[])?));
    }
    if let Some(bp) = crate::runtime::buffer::buffer_proto() {
        if proto_chain_has(vm, v, &bp)? {
            if !matches!(o.borrow().kind, ObjKind::TypedArray(_)) {
                return vm.throw_type("subarray on non-TypedArray");
            }
            let bytes = crate::builtins::typedarray::ta_bytes(&o);
            let shown: Vec<String> = bytes.iter().take(50).map(|b| format!("{:02x}", b)).collect();
            let more = if bytes.len() > 50 { " ..." } else { "" };
            return Ok(Piece::U(u16s(&format!("<Buffer {}{}>", shown.join(" "), more))));
        }
    }
    let depth = cx.depth.clone();
    if vm.op_compare(Op::Gt, &Value::Num(level as f64), &depth)? {
        let arr = crate::builtins::array::is_array(vm, v)?;
        return Ok(Piece::U(u16s(if arr { "[Array]" } else { "[Object]" })));
    }
    enter_frames(vm, 1)?;
    cx.seen.push(o.clone());
    let r = fmt_container(vm, cx, &o, v, level);
    cx.seen.pop();
    leave_frames(vm, 1);
    r.map(Piece::U)
}

/// Nested formatting: special results are stringified (as a template literal would).
fn fmt_nested(vm: &mut Vm, cx: &mut Insp, v: &Value, level: u32) -> JsResult<Vec<u16>> {
    enter_frames(vm, 1)?;
    let r = match fmt_val(vm, cx, v, level, false) {
        Ok(Piece::U(u)) => Ok(u),
        Ok(Piece::Raw(r)) => vm.to_string(&r).map(|s| s.units().to_vec()),
        Err(e) => Err(e),
    };
    leave_frames(vm, 1);
    r
}

fn fmt_container(vm: &mut Vm, cx: &mut Insp, o: &Obj, v: &Value, level: u32) -> JsResult<Vec<u16>> {
    if crate::builtins::array::is_array(vm, v)? {
        let lenv = vm.get(o, &vm.intr.key_length.clone(), v)?;
        let len = vm.to_length(&lenv)?;
        let mut body: Vec<u16> = Vec::new();
        for i in 0..len {
            if i > 0 {
                body.extend(u16s(", "));
            }
            let k = PropKey::Str(index_to_jsstr(i));
            if vm.has_property(o, &k)? {
                let ev = vm.get(o, &k, v)?;
                let s = fmt_nested(vm, cx, &ev, level + 1)?;
                body.extend(s);
            }
        }
        if body.is_empty() {
            return Ok(u16s("[]"));
        }
        let mut out = u16s("[ ");
        out.extend(body);
        out.extend(u16s(" ]"));
        return Ok(out);
    }
    let map_proto = vm.intr.map_proto.clone();
    let set_proto = vm.intr.set_proto.clone();
    let is_map = proto_chain_has(vm, v, &map_proto)?;
    let is_set = !is_map && proto_chain_has(vm, v, &set_proto)?;
    if is_map || is_set {
        let size = vm.get(o, &key("size"), v)?;
        let size_s = vm.to_string(&size)?;
        let items = vm.iterate_to_vec(v)?;
        let mut out = u16s(if is_map { "Map(" } else { "Set(" });
        out.extend_from_slice(size_s.units());
        out.extend(u16s(") { "));
        for (i, e) in items.iter().enumerate() {
            if i > 0 {
                out.extend(u16s(", "));
            }
            if is_map {
                let k = vm.get_prop_of(e, &PropKey::from_index(0))?;
                let val = vm.get_prop_of(e, &PropKey::from_index(1))?;
                let ks = fmt_nested(vm, cx, &k, level + 1)?;
                out.extend(ks);
                out.extend(u16s(" => "));
                let vs = fmt_nested(vm, cx, &val, level + 1)?;
                out.extend(vs);
            } else {
                let s = fmt_nested(vm, cx, e, level + 1)?;
                out.extend(s);
            }
        }
        out.extend(u16s(" }"));
        return Ok(out);
    }
    // ordinary object: "<constructor name> { k: v, ... }"
    let ctor = vm.get(o, &vm.intr.key_constructor.clone(), v)?;
    let name = if ctor.is_nullish() { Value::Undefined } else { vm.get_prop_of(&ctor, &vm.intr.key_name.clone())? };
    let mut out: Vec<u16> = Vec::new();
    let is_object_name = matches!(&name, Value::Str(s) if s.eq_str("Object"));
    if name.truthy() && !is_object_name {
        out.extend_from_slice(vm.to_string(&name)?.units());
        out.push(b' ' as u16);
    }
    let keys: Vec<PropKey> = if cx.show_hidden {
        vm.own_property_keys(o)?.into_iter().filter(|k| !k.is_private()).collect()
    } else {
        vm.enumerable_own_keys(o)?.into_iter().map(PropKey::Str).collect()
    };
    if keys.is_empty() {
        out.extend(u16s("{}"));
        return Ok(out);
    }
    out.extend(u16s("{ "));
    for (i, k) in keys.iter().enumerate() {
        if i > 0 {
            out.extend(u16s(", "));
        }
        match k {
            PropKey::Str(s) if is_ident_key(s.units()) => out.extend_from_slice(s.units()),
            PropKey::Str(s) => {
                out.push(b'\'' as u16);
                out.extend_from_slice(s.units());
                out.push(b'\'' as u16);
            }
            PropKey::Sym(s) => {
                out.push(b'[' as u16);
                out.extend(u16s(&s.descriptive_string()));
                out.push(b']' as u16);
            }
        }
        out.extend(u16s(": "));
        let val = vm.get(o, k, v)?;
        let s = fmt_nested(vm, cx, &val, level + 1)?;
        out.extend(s);
    }
    out.extend(u16s(" }"));
    Ok(out)
}

/// util.inspect(value, options[, extra overrides]) as a JS value (normally a string).
pub fn inspect_js(vm: &mut Vm, v: &Value, user: &Value, extra: &[(&str, Value)]) -> JsResult<Value> {
    let mut cx = Insp::new(vm, user, extra)?;
    match fmt_val(vm, &mut cx, v, 0, true)? {
        Piece::U(u) => Ok(jsv(u)),
        Piece::Raw(r) => Ok(r),
    }
}

/// util.inspect result converted to a string (as format() embeds it).
pub fn inspect_units(vm: &mut Vm, v: &Value, user: &Value, extra: &[(&str, Value)]) -> JsResult<Vec<u16>> {
    let r = inspect_js(vm, v, user, extra)?;
    match r {
        Value::Str(s) => Ok(s.units().to_vec()),
        other => Ok(vm.to_string(&other)?.units().to_vec()),
    }
}

/// Inspect with a numeric depth (used by other runtime modules for messages).
pub fn inspect_value(vm: &mut Vm, v: &Value, depth: i32) -> JsResult<String> {
    let u = inspect_units(vm, v, &Value::Undefined, &[("depth", Value::Num(depth as f64))])?;
    Ok(String::from_utf16_lossy(&u))
}

/// Inspect with a user options object (console.dir).
#[allow(dead_code)]
pub fn inspect_with_options(vm: &mut Vm, v: &Value, opts: &Value) -> JsResult<String> {
    let u = inspect_units(vm, v, opts, &[])?;
    Ok(String::from_utf16_lossy(&u))
}

fn inspect_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    inspect_js(vm, &a.arg(0), &a.arg(1), &[])
}

// ============================================================================================
// util.format / formatWithOptions
// ============================================================================================

fn num_units(n: f64) -> Vec<u16> {
    u16s(&crate::numconv::number_to_string(n))
}

/// util.formatWithOptions(opts, ...args) (format() passes undefined options).
pub fn format_units(vm: &mut Vm, opts: &Value, args: &[Value]) -> JsResult<Vec<u16>> {
    let mut out: Vec<u16> = Vec::new();
    if args.is_empty() {
        return Ok(out);
    }
    let mut rest = 0;
    if let Value::Str(fs) = &args[0] {
        if args.len() == 1 {
            return Ok(fs.units().to_vec());
        }
        let f = fs.units().to_vec();
        let mut ai = 1;
        let mut i = 0;
        let pct = b'%' as u16;
        while i < f.len() {
            let c = f[i];
            if c == pct && i + 1 < f.len() {
                let n = f[i + 1];
                if n == pct {
                    out.push(pct);
                    i += 2;
                    continue;
                }
                let spec = if n < 128 { n as u8 as char } else { '\0' };
                if matches!(spec, 's' | 'd' | 'i' | 'f' | 'j' | 'o' | 'O' | 'c') && ai < args.len() {
                    let v = args[ai].clone();
                    ai += 1;
                    let piece = format_spec(vm, opts, spec, &v)?;
                    out.extend(piece);
                    i += 2;
                    continue;
                }
            }
            out.push(c);
            i += 1;
        }
        rest = ai;
    }
    // remaining arguments are appended space-separated (no separator while still empty)
    for v in &args[rest..] {
        if !out.is_empty() {
            out.push(b' ' as u16);
        }
        match v {
            Value::Str(s) => out.extend_from_slice(s.units()),
            other => {
                let s = inspect_units(vm, other, opts, &[])?;
                out.extend(s);
            }
        }
    }
    Ok(out)
}

fn format_spec(vm: &mut Vm, opts: &Value, spec: char, v: &Value) -> JsResult<Vec<u16>> {
    Ok(match spec {
        's' => match v {
            Value::Str(s) => s.units().to_vec(),
            Value::BigInt(b) => u16s(&format!("{}n", b.to_string_radix(10))),
            Value::Sym(s) => u16s(&s.descriptive_string()),
            Value::Obj(o) if !o.is_callable() => inspect_units(vm, v, opts, &[("depth", Value::Num(0.0))])?,
            other => vm.to_string(other)?.units().to_vec(),
        },
        'd' => match v {
            Value::BigInt(b) => u16s(&format!("{}n", b.to_string_radix(10))),
            other => {
                let n = vm.to_number(other)?;
                num_units(n)
            }
        },
        'i' => {
            let s = vm.to_string(v)?;
            num_units(crate::numconv::parse_int(s.units(), 10))
        }
        'f' => {
            let s = vm.to_string(v)?;
            num_units(crate::numconv::parse_float(s.units()))
        }
        'j' => match crate::builtins::json::json_stringify(vm, v, &Value::Undefined, &Value::Undefined) {
            Ok(Some(s)) => s.units().to_vec(),
            Ok(None) => u16s("undefined"),
            Err(_) => u16s("[Circular]"),
        },
        'o' => inspect_units(vm, v, opts, &[("showHidden", Value::Bool(true))])?,
        'O' => inspect_units(vm, v, opts, &[])?,
        _ => Vec::new(), // %c
    })
}

/// util.format(...args) as a Rust string.
#[allow(dead_code)]
pub fn format_args(vm: &mut Vm, args: &[Value]) -> JsResult<String> {
    let u = format_units(vm, &Value::Undefined, args)?;
    Ok(String::from_utf16_lossy(&u))
}

fn format_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(jsv(format_units(vm, &Value::Undefined, a.args)?))
}

fn format_with_options_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let opts = a.arg(0);
    let opts = if opts.is_object() { opts } else { Value::Undefined };
    let rest = if a.args.len() > 1 { &a.args[1..] } else { &[][..] };
    Ok(jsv(format_units(vm, &opts, rest)?))
}

// ============================================================================================
// describe_received (Node-style "Received ..." used by other runtime modules)
// ============================================================================================

pub fn describe_received(vm: &mut Vm, v: &Value) -> String {
    match v {
        Value::Undefined => "undefined".into(),
        Value::Null => "null".into(),
        Value::Bool(b) => format!("type boolean ({})", b),
        Value::Num(n) => format!("type number ({})", crate::numconv::number_to_string(*n)),
        Value::Str(s) => {
            let st = s.to_rust_string();
            let shown = if st.chars().count() > 28 { format!("{}...", st.chars().take(25).collect::<String>()) } else { st };
            format!("type string ('{}')", shown)
        }
        Value::Sym(s) => format!("type symbol ({})", s.descriptive_string()),
        Value::BigInt(b) => format!("type bigint ({}n)", b.to_string_radix(10)),
        Value::Obj(o) => {
            if o.is_callable() {
                let n = match o.get_own_str("name") {
                    Some(Value::Str(s)) if !s.is_empty() => s.to_rust_string(),
                    _ => String::new(),
                };
                if n.is_empty() {
                    "function ".into()
                } else {
                    format!("function {}", n)
                }
            } else {
                match constructor_name(vm, o) {
                    Some(c) if !c.is_empty() => format!("an instance of {}", c),
                    _ => inspect_value(vm, v, 0).unwrap_or_default(),
                }
            }
        }
        Value::Empty => "undefined".into(),
    }
}

pub fn constructor_name(vm: &mut Vm, o: &Obj) -> Option<String> {
    let mut cur = Some(o.clone());
    while let Some(c) = cur {
        if let Some(Value::Obj(ctor)) = c.get_own_data(&vm.intr.key_constructor.clone()) {
            if let Some(Value::Str(n)) = ctor.get_own_data(&vm.intr.key_name.clone()) {
                return Some(n.to_rust_string());
            }
        }
        cur = c.borrow().proto.clone();
    }
    None
}

// ============================================================================================
// the util module object
// ============================================================================================

pub fn create_module(vm: &mut Vm) -> Value {
    let o = vm.new_object();
    let insp = def_plain(vm, &o, "inspect", 2, inspect_fn);
    def_plain(vm, &o, "inherits", 2, inherits);
    def_plain(vm, &o, "format", 0, format_fn);
    def_plain(vm, &o, "formatWithOptions", 1, format_with_options_fn);
    def_plain(vm, &o, "deprecate", 3, deprecate);
    let prom = def_plain(vm, &o, "promisify", 1, promisify);
    def_plain(vm, &o, "callbackify", 1, callbackify);
    let types = create_types(vm);
    o.set_prop(key("types"), Value::Obj(types.clone()), WEC);
    // legacy type checks (some are shared with util.types / Array.isArray)
    let array_ctor = vm.intr.array_ctor.clone();
    let is_array = array_ctor.get_own_str("isArray").unwrap_or(Value::Undefined);
    o.set_prop(key("isArray"), is_array, WEC);
    for n in ["isDate", "isRegExp"] {
        let f = types.get_own_str(n).unwrap_or(Value::Undefined);
        o.set_prop(key(n), f, WEC);
    }
    let ne = types.get_own_str("isNativeError").unwrap_or(Value::Undefined);
    o.set_prop(key("isError"), ne, WEC);
    let legacy: &[(&str, NativeFn)] = &[
        ("isFunction", |_vm, a| Ok(Value::Bool(a.arg(0).is_callable()))),
        ("isString", |_vm, a| Ok(Value::Bool(matches!(a.arg(0), Value::Str(_))))),
        ("isNumber", |_vm, a| Ok(Value::Bool(matches!(a.arg(0), Value::Num(_))))),
        ("isBoolean", |_vm, a| Ok(Value::Bool(matches!(a.arg(0), Value::Bool(_))))),
        ("isNull", |_vm, a| Ok(Value::Bool(a.arg(0).is_null()))),
        ("isNullOrUndefined", |_vm, a| Ok(Value::Bool(a.arg(0).is_nullish()))),
        ("isUndefined", |_vm, a| Ok(Value::Bool(a.arg(0).is_undefined()))),
        ("isObject", |_vm, a| Ok(Value::Bool(matches!(a.arg(0), Value::Obj(ref o) if !o.is_callable())))),
        ("isPrimitive", |_vm, a| Ok(Value::Bool(!a.arg(0).is_object()))),
        ("isBuffer", |vm, a| {
            let r = match crate::runtime::buffer::buffer_proto() {
                Some(bp) => proto_chain_has(vm, &a.arg(0), &bp)?,
                None => false,
            };
            Ok(Value::Bool(r))
        }),
        ("isSymbol", |_vm, a| Ok(Value::Bool(matches!(a.arg(0), Value::Sym(_))))),
    ];
    for (n, f) in legacy {
        def_arrow(vm, &o, n, 1, *f);
    }
    def_arrow(vm, &o, "_extend", 2, util_extend);
    def_plain(vm, &o, "isDeepStrictEqual", 2, |vm, a| Ok(Value::Bool(is_deep_strict_equal(vm, &a.arg(0), &a.arg(1))?)));
    def_plain(vm, &o, "log", 0, util_log);
    let dl = def_plain(vm, &o, "debuglog", 2, debuglog);
    o.set_prop(key("debug"), Value::Obj(dl), WEC);
    def_plain(vm, &o, "parseArgs", 1, parse_args);
    def_plain(vm, &o, "parseEnv", 1, parse_env);
    def_plain(vm, &o, "styleText", 3, style_text);
    def_plain(vm, &o, "stripVTControlCharacters", 1, strip_vt);
    def_plain(vm, &o, "toUSVString", 1, to_usv_string);
    def_plain(vm, &o, "diff", 2, util_diff);
    def_plain(vm, &o, "getSystemErrorName", 1, |vm, a| sys_error_lookup(vm, &a.arg(0), true));
    def_plain(vm, &o, "getSystemErrorMessage", 1, |vm, a| sys_error_lookup(vm, &a.arg(0), false));
    def_plain(vm, &o, "getSystemErrorMap", 0, sys_error_map);
    def_plain(vm, &o, "aborted", 2, util_aborted);
    def_plain(vm, &o, "transferableAbortController", 0, |vm, _a| {
        let c = get_global(vm, "AbortController");
        vm.construct(&c, &[], None)
    });
    def_plain(vm, &o, "transferableAbortSignal", 1, |_vm, a| Ok(a.arg(0)));
    let gcs = plain_fn(vm, "getCallSites", 0, |vm, _a| Ok(Value::Obj(vm.new_array(Vec::new()))), Vec::new());
    o.set_prop(key("getCallSite"), Value::Obj(gcs.clone()), WEC);
    o.set_prop(key("getCallSites"), Value::Obj(gcs), WEC);
    def_plain(vm, &o, "_errnoException", 3, errno_exception);
    def_plain(vm, &o, "_exceptionWithHostPort", 5, exception_with_host_port);
    let (mime, mime_params) = create_mime_classes(vm);
    o.set_prop(key("MIMEType"), Value::Obj(mime), WEC);
    o.set_prop(key("MIMEParams"), Value::Obj(mime_params), WEC);
    for n in ["TextEncoder", "TextDecoder"] {
        if let Some(v) = vm.global.get_own_str(n) {
            o.set_prop(key(n), v, WEC);
        }
    }
    // util.inspect.custom / defaultOptions, util.promisify.custom
    let custom = vm.symbol_for("nodejs.util.inspect.custom");
    insp.set_prop(key("custom"), Value::Sym(custom), WEC);
    let dflt = vm.obj_from(vec![("depth", Value::Num(2.0))]);
    insp.set_prop(key("defaultOptions"), Value::Obj(dflt), WEC);
    let pcustom = vm.symbol_for("nodejs.util.promisify.custom");
    prom.set_prop(key("custom"), Value::Sym(pcustom), WEC);
    let present: Vec<&str> = crate::runtime::UTIL_KEYS.iter().copied().filter(|k| o.borrow().props.contains(&key(k))).collect();
    crate::runtime::reorder_enum(vm, &o, &present);
    Value::Obj(o)
}

fn util_extend(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let target = a.arg(0);
    let src = a.arg(1);
    if !matches!(&src, Value::Obj(o) if !o.is_callable()) {
        return Ok(target);
    }
    let t = match &target {
        Value::Obj(t) => t.clone(),
        Value::Undefined | Value::Null => return vm.throw_type("Object.assign called on null or undefined"),
        other => vm.to_object(other)?,
    };
    let so = src.as_obj().cloned().unwrap();
    let keys = vm.own_property_keys(&so)?;
    for k in keys {
        if k.is_private() {
            continue;
        }
        if let Some(d) = vm.get_own_property(&so, &k)? {
            if d.enumerable == Some(true) {
                let v = vm.get(&so, &k, &src)?;
                vm.set(&t, k, v, &Value::Obj(t.clone()))?;
            }
        }
    }
    Ok(target)
}

// ---------------- util.types ----------------

/// `v` is an object whose Object.prototype.toString tag is `tag`.
fn tag_is(vm: &mut Vm, v: &Value, tag: &str) -> JsResult<bool> {
    Ok(tag_of(vm, v)?.as_deref() == Some(tag))
}

fn ta_kind_of(v: &Value) -> Option<TAKind> {
    match v {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::TypedArray(t) => Some(t.kind),
            _ => None,
        },
        _ => None,
    }
}

macro_rules! tagged {
    ($tag:expr) => {
        |vm: &mut Vm, a: &Args| Ok(Value::Bool(tag_is(vm, &a.arg(0), $tag)?))
    };
}

macro_rules! ta_is {
    ($k:expr) => {
        |_vm: &mut Vm, a: &Args| Ok(Value::Bool(ta_kind_of(&a.arg(0)) == Some($k)))
    };
}

fn create_types(vm: &mut Vm) -> Obj {
    let t = vm.new_object();
    let fns: &[(&str, u32, NativeFn)] = &[
        ("isExternal", 0, |_vm, _a| Ok(Value::Bool(false))),
        ("isProxy", 1, |_vm, a| Ok(Value::Bool(matches!(a.arg(0), Value::Obj(ref o) if o.is_proxy())))),
        ("isKeyObject", 1, |_vm, _a| Ok(Value::Bool(false))),
        ("isDate", 1, tagged!("Date")),
        ("isRegExp", 1, tagged!("RegExp")),
        ("isArgumentsObject", 1, tagged!("Arguments")),
        ("isNativeError", 1, |vm, a| Ok(Value::Bool(is_error_instance(vm, &a.arg(0))?))),
        ("isMap", 1, tagged!("Map")),
        ("isSet", 1, tagged!("Set")),
        ("isMapIterator", 1, tagged!("Map Iterator")),
        ("isSetIterator", 1, tagged!("Set Iterator")),
        ("isWeakMap", 1, tagged!("WeakMap")),
        ("isWeakSet", 1, tagged!("WeakSet")),
        ("isPromise", 1, tagged!("Promise")),
        ("isGeneratorFunction", 1, tagged!("GeneratorFunction")),
        ("isAsyncFunction", 1, tagged!("AsyncFunction")),
        ("isGeneratorObject", 1, tagged!("Generator")),
        ("isModuleNamespaceObject", 1, tagged!("Module")),
        ("isNumberObject", 1, tagged!("Number")),
        ("isStringObject", 1, tagged!("String")),
        ("isBooleanObject", 1, tagged!("Boolean")),
        ("isSymbolObject", 1, tagged!("Symbol")),
        ("isBigIntObject", 1, tagged!("BigInt")),
        ("isBoxedPrimitive", 1, |vm, a| {
            let t = tag_of(vm, &a.arg(0))?;
            Ok(Value::Bool(matches!(t.as_deref(), Some("Number" | "String" | "Boolean" | "Symbol" | "BigInt"))))
        }),
        ("isArrayBuffer", 1, tagged!("ArrayBuffer")),
        ("isSharedArrayBuffer", 1, tagged!("SharedArrayBuffer")),
        ("isAnyArrayBuffer", 1, |vm, a| {
            let t = tag_of(vm, &a.arg(0))?;
            Ok(Value::Bool(matches!(t.as_deref(), Some("ArrayBuffer" | "SharedArrayBuffer"))))
        }),
        ("isDataView", 1, tagged!("DataView")),
        ("isArrayBufferView", 1, |_vm, a| {
            Ok(Value::Bool(matches!(a.arg(0), Value::Obj(ref o) if matches!(o.borrow().kind, ObjKind::TypedArray(_) | ObjKind::DataView(_)))))
        }),
        ("isTypedArray", 1, |_vm, a| Ok(Value::Bool(ta_kind_of(&a.arg(0)).is_some()))),
        ("isUint8Array", 1, ta_is!(TAKind::Uint8)),
        ("isUint8ClampedArray", 1, ta_is!(TAKind::Uint8C)),
        ("isUint16Array", 1, ta_is!(TAKind::Uint16)),
        ("isUint32Array", 1, ta_is!(TAKind::Uint32)),
        ("isInt8Array", 1, ta_is!(TAKind::Int8)),
        ("isInt16Array", 1, ta_is!(TAKind::Int16)),
        ("isInt32Array", 1, ta_is!(TAKind::Int32)),
        ("isFloat16Array", 1, ta_is!(TAKind::Float16)),
        ("isFloat32Array", 1, ta_is!(TAKind::Float32)),
        ("isFloat64Array", 1, ta_is!(TAKind::Float64)),
        ("isBigInt64Array", 1, ta_is!(TAKind::BigInt64)),
        ("isBigUint64Array", 1, ta_is!(TAKind::BigUint64)),
        ("isCryptoKey", 1, |_vm, _a| Ok(Value::Bool(false))),
    ];
    for (n, l, f) in fns {
        def_arrow(vm, &t, n, *l, *f);
    }
    t
}

// ---------------- inherits ----------------

fn inherits(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ctor = a.arg(0);
    let sup = a.arg(1);
    if ctor.is_nullish() {
        return vm.throw_type("The \"ctor\" argument must be a function");
    }
    if sup.is_nullish() {
        return vm.throw_type("The \"superCtor\" argument must be a function");
    }
    let sp = vm.get_prop_of(&sup, &vm.intr.key_prototype.clone())?;
    if sp.is_undefined() {
        return vm.throw_type("The \"superCtor.prototype\" property must not be undefined");
    }
    let c = match &ctor {
        Value::Obj(c) => c.clone(),
        _ => return vm.throw_type("Object.defineProperty called on non-object"),
    };
    let d = PropDesc { value: Some(sup.clone()), writable: Some(true), enumerable: Some(false), configurable: Some(true), ..Default::default() };
    vm.define_property_or_throw(&c, key("super_"), d)?;
    let cp = vm.get(&c, &vm.intr.key_prototype.clone(), &ctor)?;
    match &cp {
        Value::Obj(cpo) => {
            let np = match &sp {
                Value::Obj(s) => Some(s.clone()),
                Value::Null => None,
                _ => return vm.throw_type("Object prototype may only be an Object or null"),
            };
            if !vm.set_prototype_of(cpo, np)? {
                return vm.throw_type("Cyclic __proto__ value");
            }
        }
        Value::Undefined | Value::Null => return vm.throw_type("Object.setPrototypeOf called on null or undefined"),
        _ => {}
    }
    Ok(Value::Undefined)
}

// ---------------- deprecate ----------------

fn deprecate(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.arg(0);
    let msg = a.arg(1);
    let code = a.arg(2);
    let flag = Value::Obj(Obj::new(None, ObjKind::Ordinary));
    Ok(Value::Obj(plain_fn(vm, "deprecated", 0, deprecated_call, vec![f, msg, code, flag])))
}

fn deprecated_call(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let Value::Obj(flag) = a.slot(3) {
        if flag.get_own_str("warned").is_none() {
            flag.set_str("warned", Value::Bool(true), WEC);
            let msg = string_of(vm, &a.slot(1))?.to_rust_string();
            let code = a.slot(2);
            let line = if code.is_undefined() {
                format!("DeprecationWarning: {}\n", msg)
            } else {
                let c = string_of(vm, &code)?.to_rust_string();
                format!("DeprecationWarning: [{}] {}\n", c, msg)
            };
            crate::runtime::write_stderr(&line);
        }
    }
    let f = a.slot(0);
    if !f.is_callable() {
        return vm.throw_type("Reflect.apply target is not callable");
    }
    vm.call(&f, a.this.clone(), a.args)
}

// ---------------- promisify / callbackify ----------------

fn promisify(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.arg(0);
    if !f.is_callable() {
        return vm.throw_type("The \"original\" argument must be of type function");
    }
    let custom = vm.symbol_for("nodejs.util.promisify.custom");
    let c = vm.get_prop_of(&f, &PropKey::Sym(custom))?;
    if c.is_callable() {
        return Ok(c);
    }
    Ok(Value::Obj(plain_fn(vm, "fn", 0, promisified_call, vec![f])))
}

fn promisified_call(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let cb = vm.native_closure("", 2, promisify_cb, vec![cap.resolve.clone(), cap.reject.clone()]);
    let mut args = a.args.to_vec();
    args.push(Value::Obj(cb));
    if let Err(e) = vm.call(&a.slot(0), a.this.clone(), &args) {
        vm.call(&cap.reject, Value::Undefined, &[e])?;
    }
    Ok(cap.promise)
}

fn promisify_cb(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let err = a.arg(0);
    if err.truthy() {
        vm.call(&a.slot(1), Value::Undefined, &[err])?;
    } else {
        vm.call(&a.slot(0), Value::Undefined, &[a.arg(1)])?;
    }
    Ok(Value::Undefined)
}

fn callbackify(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.arg(0);
    if !f.is_callable() {
        return vm.throw_type("The \"original\" argument must be of type function");
    }
    Ok(Value::Obj(plain_fn(vm, "", 0, callbackified_call, vec![f])))
}

fn callbackified_call(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut args = a.args.to_vec();
    let cb = args.pop().unwrap_or(Value::Undefined);
    let p = vm.call(&a.slot(0), a.this.clone(), &args)?;
    let then = vm.get_prop_of(&p, &vm.intr.key_then.clone())?;
    if !then.is_callable() {
        return vm.throw_type("(intermediate value).then is not a function");
    }
    let on_ok = vm.native_closure("", 1, callbackify_settled, vec![cb.clone(), Value::Bool(true)]);
    let on_err = vm.native_closure("", 1, callbackify_settled, vec![cb, Value::Bool(false)]);
    vm.call(&then, p, &[Value::Obj(on_ok), Value::Obj(on_err)])?;
    Ok(Value::Undefined)
}

/// Settlement of a callbackified promise: the callback runs one microtask later; an exception
/// it throws becomes an unhandled rejection.
fn callbackify_settled(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ok = a.slot(1).truthy();
    let v = a.arg(0);
    let args = if ok {
        vec![Value::Null, v]
    } else if v.truthy() {
        vec![v]
    } else {
        vec![vm.make_error("Error", "Promise was rejected with a falsy value")]
    };
    let arr = Value::Obj(vm.new_array(args));
    let data = Value::Obj(vm.new_array(vec![a.slot(0), arr]));
    let resolved = vm.new_promise_capability_intrinsic();
    vm.call(&resolved.resolve, Value::Undefined, &[Value::Undefined])?;
    let cap = vm.new_promise_capability_intrinsic();
    if let Value::Obj(p) = &resolved.promise {
        crate::builtins::promise::perform_then_internal(vm, p, Handler::Native(callbackify_invoke, data), Handler::Thrower, Some(cap));
    }
    Ok(Value::Undefined)
}

fn callbackify_invoke(vm: &mut Vm, _v: Value, data: &Value) -> JsResult<Value> {
    let cb = vm.get_prop_of(data, &PropKey::from_index(0))?;
    let args = vm.get_prop_of(data, &PropKey::from_index(1))?;
    let list = crate::builtins::array::array_like_to_vec(vm, &args)?;
    if !cb.is_callable() {
        return vm.throw_type("cb is not a function");
    }
    vm.call(&cb, Value::Undefined, &list)
}

// ---------------- util.log / debuglog ----------------

fn util_log(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t = crate::datetime::local_time(crate::datetime::now_ms());
    const MONTHS: [&str; 12] = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    let stamp = format!(
        "{} {} {:02}:{:02}:{:02}",
        crate::datetime::date_from_time(t) as i64,
        MONTHS[(crate::datetime::month_from_time(t) as usize) % 12],
        crate::datetime::hour_from_time(t) as i64,
        crate::datetime::min_from_time(t) as i64,
        crate::datetime::sec_from_time(t) as i64
    );
    let msg = format_units(vm, &Value::Undefined, a.args)?;
    let console = get_global(vm, "console");
    let log = vm.get_prop_of(&console, &key("log"))?;
    vm.call(&log, console, &[Value::str("%s - %s"), Value::str(&stamp), jsv(msg)])?;
    Ok(Value::Undefined)
}

fn debug_enabled(section: &str) -> bool {
    let env = match std::env::var("NODE_DEBUG") {
        Ok(v) => v,
        Err(_) => return false,
    };
    let s = section.to_lowercase();
    env.split(',').any(|pat| glob_match(&pat.to_lowercase(), &s))
}

fn glob_match(p: &str, s: &str) -> bool {
    let p: Vec<char> = p.chars().collect();
    let s: Vec<char> = s.chars().collect();
    fn go(p: &[char], s: &[char]) -> bool {
        match p.first() {
            None => s.is_empty(),
            Some('*') => (0..=s.len()).any(|i| go(&p[1..], &s[i..])),
            Some(c) => !s.is_empty() && s[0] == *c && go(&p[1..], &s[1..]),
        }
    }
    go(&p, &s)
}

fn debuglog(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let set = string_of(vm, &a.arg(0))?.to_rust_string();
    let enabled = debug_enabled(&set);
    let state = Value::Obj(Obj::new(None, ObjKind::Ordinary));
    let f = plain_fn(vm, "logger", 0, debuglog_call, vec![Value::str(&set.to_uppercase()), Value::Bool(enabled), a.arg(1), state]);
    f.set_prop(key("enabled"), Value::Bool(enabled), WEC);
    Ok(Value::Obj(f))
}

fn debuglog_call(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !a.slot(1).truthy() {
        return Ok(Value::Undefined);
    }
    let cb = a.slot(2);
    if let Value::Obj(st) = a.slot(3) {
        if cb.is_callable() && st.get_own_str("called").is_none() {
            st.set_str("called", Value::Bool(true), WEC);
            vm.call(&cb, Value::Undefined, &[Value::Obj(a.callee.clone())])?;
        }
    }
    let msg = format_units(vm, &Value::Undefined, a.args)?;
    let console = get_global(vm, "console");
    let err = vm.get_prop_of(&console, &key("error"))?;
    vm.call(&err, console, &[Value::str("%s %d: %s"), a.slot(0), Value::Num(std::process::id() as f64), jsv(msg)])?;
    Ok(Value::Undefined)
}

// ---------------- stripVTControlCharacters / toUSVString / styleText ----------------

fn vt_final(c: u16) -> bool {
    if c >= 128 {
        return false;
    }
    let c = c as u8 as char;
    c.is_ascii_digit() || matches!(c, '<' | '=' | '>' | 'A'..='O' | 'R' | 'Z' | 'c' | 'f'..='n' | 'q' | 'r' | 'y' | '~')
}

fn vt_digit(c: u16) -> bool {
    (b'0' as u16..=b'9' as u16).contains(&c)
}

/// `(?:;\d{0,4})*` followed by a final character, greedy with backtracking.
fn vt_semis(s: &[u16], p: usize) -> Option<usize> {
    if p < s.len() && s[p] == b';' as u16 {
        let mut n = 0;
        while n < 4 && p + 1 + n < s.len() && vt_digit(s[p + 1 + n]) {
            n += 1;
        }
        for k in (0..=n).rev() {
            if let Some(e) = vt_semis(s, p + 1 + k) {
                return Some(e);
            }
        }
    }
    if p < s.len() && vt_final(s[p]) {
        Some(p + 1)
    } else {
        None
    }
}

/// Match `[\x1b\x9b][[\]()#;?]*(?:\d{1,4}(?:;\d{0,4})*)?[final]` at `i`.
fn vt_match(s: &[u16], i: usize) -> Option<usize> {
    if s[i] != 0x1b && s[i] != 0x9b {
        return None;
    }
    let mut p = i + 1;
    while p < s.len() && matches!(s[p], 0x5b | 0x5d | 0x28 | 0x29 | 0x23 | 0x3b | 0x3f) {
        p += 1;
    }
    let mut n = 0;
    while n < 4 && p + n < s.len() && vt_digit(s[p + n]) {
        n += 1;
    }
    for k in (1..=n).rev() {
        if let Some(e) = vt_semis(s, p + k) {
            return Some(e);
        }
    }
    if p < s.len() && vt_final(s[p]) {
        Some(p + 1)
    } else {
        None
    }
}

pub fn strip_vt_units(s: &[u16]) -> Vec<u16> {
    let mut out = Vec::with_capacity(s.len());
    let mut i = 0;
    while i < s.len() {
        if let Some(e) = vt_match(s, i) {
            i = e;
            continue;
        }
        out.push(s[i]);
        i += 1;
    }
    out
}

fn strip_vt(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match a.arg(0) {
        Value::Str(s) => Ok(jsv(strip_vt_units(s.units()))),
        _ => vm.throw_type("The \"str\" argument must be of type string."),
    }
}

fn to_usv_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    let u = s.units();
    let mut out = Vec::with_capacity(u.len());
    let mut i = 0;
    while i < u.len() {
        let c = u[i];
        if (0xD800..0xDC00).contains(&c) && i + 1 < u.len() && (0xDC00..0xE000).contains(&u[i + 1]) {
            out.push(c);
            out.push(u[i + 1]);
            i += 2;
            continue;
        }
        if (0xD800..0xE000).contains(&c) {
            out.push(0xFFFD);
        } else {
            out.push(c);
        }
        i += 1;
    }
    Ok(jsv(out))
}

const STYLES: &[(&str, u32, u32)] = &[
    ("reset", 0, 0),
    ("bold", 1, 22),
    ("dim", 2, 22),
    ("italic", 3, 23),
    ("underline", 4, 24),
    ("blink", 5, 25),
    ("inverse", 7, 27),
    ("hidden", 8, 28),
    ("strikethrough", 9, 29),
    ("doubleunderline", 21, 24),
    ("black", 30, 39),
    ("red", 31, 39),
    ("green", 32, 39),
    ("yellow", 33, 39),
    ("blue", 34, 39),
    ("magenta", 35, 39),
    ("cyan", 36, 39),
    ("white", 37, 39),
    ("bgBlack", 40, 49),
    ("bgRed", 41, 49),
    ("bgGreen", 42, 49),
    ("bgYellow", 43, 49),
    ("bgBlue", 44, 49),
    ("bgMagenta", 45, 49),
    ("bgCyan", 46, 49),
    ("bgWhite", 47, 49),
    ("framed", 51, 54),
    ("overlined", 53, 55),
    ("gray", 90, 39),
    ("redBright", 91, 39),
    ("greenBright", 92, 39),
    ("yellowBright", 93, 39),
    ("blueBright", 94, 39),
    ("magentaBright", 95, 39),
    ("cyanBright", 96, 39),
    ("whiteBright", 97, 39),
    ("bgGray", 100, 49),
    ("bgRedBright", 101, 49),
    ("bgGreenBright", 102, 49),
    ("bgYellowBright", 103, 49),
    ("bgBlueBright", 104, 49),
    ("bgMagentaBright", 105, 49),
    ("bgCyanBright", 106, 49),
    ("bgWhiteBright", 107, 49),
];

/// Names inherited from Object.prototype: accepted as a "style" but have no codes.
const PROTO_NAMES: &[&str] = &[
    "constructor", "__defineGetter__", "__defineSetter__", "hasOwnProperty", "__lookupGetter__", "__lookupSetter__",
    "isPrototypeOf", "propertyIsEnumerable", "toString", "valueOf", "__proto__", "toLocaleString",
];

fn style_text(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let format = a.arg(0);
    let text = match a.arg(1) {
        Value::Str(s) => s,
        _ => return vm.throw_type("The \"text\" argument must be of type string."),
    };
    let formats: Vec<Value> = if crate::builtins::array::is_array(vm, &format)? {
        crate::builtins::array::array_like_to_vec(vm, &format)?
    } else {
        vec![format.clone()]
    };
    let mut codes: Vec<(String, String)> = Vec::new();
    for f in &formats {
        let name = match f {
            Value::Str(s) => Some(s.to_rust_string()),
            Value::Obj(_) => match vm.to_property_key(f)? {
                PropKey::Str(s) => Some(s.to_rust_string()),
                _ => None,
            },
            _ => None,
        };
        let found = name.as_deref().and_then(|n| STYLES.iter().find(|s| s.0 == n).map(|s| (s.1.to_string(), s.2.to_string())));
        match (found, &name) {
            (Some(c), _) => codes.push(c),
            (None, Some(n)) if PROTO_NAMES.contains(&n.as_str()) => codes.push(("undefined".into(), "undefined".into())),
            _ => {
                let shown = match crate::builtins::json::json_stringify(vm, f, &Value::Undefined, &Value::Undefined) {
                    Ok(Some(s)) => s.to_rust_string(),
                    _ => "undefined".to_string(),
                };
                let msg = format!("The argument 'format' must be a valid color/style. Received {}", shown);
                return Err(coded_error(vm, "TypeError", &msg, "ERR_INVALID_ARG_VALUE"));
            }
        }
    }
    // a non-TTY stream disables styling
    if let Value::Obj(opts) = a.arg(2) {
        let stream = vm.get(&opts, &key("stream"), &a.arg(2))?;
        if let Value::Obj(so) = &stream {
            let tty = vm.get(so, &key("isTTY"), &stream)?;
            if matches!(tty, Value::Bool(false)) {
                return Ok(Value::Str(text));
            }
        }
    }
    let mut out: Vec<u16> = Vec::new();
    for (open, _) in &codes {
        out.extend(u16s(&format!("\u{1b}[{}m", open)));
    }
    out.extend_from_slice(text.units());
    for (_, close) in codes.iter().rev() {
        out.extend(u16s(&format!("\u{1b}[{}m", close)));
    }
    Ok(jsv(out))
}

// ---------------- system errors ----------------

/// The reference's errno table (libuv names with its own numbering), in its Map order.
const SYS_ERRORS: &[(i32, &str, &str)] = &[
    (-7, "E2BIG", "argument list too long"),
    (-13, "EACCES", "permission denied"),
    (-48, "EADDRINUSE", "address already in use"),
    (-49, "EADDRNOTAVAIL", "address not available"),
    (-47, "EAFNOSUPPORT", "address family not supported"),
    (-35, "EAGAIN", "resource temporarily unavailable"),
    (-3000, "EAI_ADDRFAMILY", "address family not supported"),
    (-3001, "EAI_AGAIN", "temporary failure"),
    (-3002, "EAI_BADFLAGS", "bad ai_flags value"),
    (-3013, "EAI_BADHINTS", "invalid value for hints"),
    (-3003, "EAI_CANCELED", "request canceled"),
    (-3004, "EAI_FAIL", "permanent failure"),
    (-3005, "EAI_FAMILY", "ai_family not supported"),
    (-3006, "EAI_MEMORY", "out of memory"),
    (-3007, "EAI_NODATA", "no address"),
    (-3008, "EAI_NONAME", "unknown node or service"),
    (-3009, "EAI_OVERFLOW", "argument buffer overflow"),
    (-3014, "EAI_PROTOCOL", "resolved protocol is unknown"),
    (-3010, "EAI_SERVICE", "service not available for socket type"),
    (-3011, "EAI_SOCKTYPE", "socket type not supported"),
    (-37, "EALREADY", "connection already in progress"),
    (-9, "EBADF", "bad file descriptor"),
    (-16, "EBUSY", "resource busy or locked"),
    (-89, "ECANCELED", "operation canceled"),
    (-4080, "ECHARSET", "invalid Unicode character"),
    (-53, "ECONNABORTED", "software caused connection abort"),
    (-61, "ECONNREFUSED", "connection refused"),
    (-54, "ECONNRESET", "connection reset by peer"),
    (-39, "EDESTADDRREQ", "destination address required"),
    (-17, "EEXIST", "file already exists"),
    (-14, "EFAULT", "bad address in system call argument"),
    (-27, "EFBIG", "file too large"),
    (-65, "EHOSTUNREACH", "host is unreachable"),
    (-4, "EINTR", "interrupted system call"),
    (-22, "EINVAL", "invalid argument"),
    (-5, "EIO", "i/o error"),
    (-56, "EISCONN", "socket is already connected"),
    (-21, "EISDIR", "illegal operation on a directory"),
    (-62, "ELOOP", "too many symbolic links encountered"),
    (-24, "EMFILE", "too many open files"),
    (-40, "EMSGSIZE", "message too long"),
    (-63, "ENAMETOOLONG", "name too long"),
    (-50, "ENETDOWN", "network is down"),
    (-51, "ENETUNREACH", "network is unreachable"),
    (-23, "ENFILE", "file table overflow"),
    (-55, "ENOBUFS", "no buffer space available"),
    (-19, "ENODEV", "no such device"),
    (-2, "ENOENT", "no such file or directory"),
    (-12, "ENOMEM", "not enough memory"),
    (-4056, "ENONET", "machine is not on the network"),
    (-42, "ENOPROTOOPT", "protocol not available"),
    (-28, "ENOSPC", "no space left on device"),
    (-78, "ENOSYS", "function not implemented"),
    (-57, "ENOTCONN", "socket is not connected"),
    (-20, "ENOTDIR", "not a directory"),
    (-66, "ENOTEMPTY", "directory not empty"),
    (-38, "ENOTSOCK", "socket operation on non-socket"),
    (-45, "ENOTSUP", "operation not supported on socket"),
    (-84, "EOVERFLOW", "value too large for defined data type"),
    (-1, "EPERM", "operation not permitted"),
    (-32, "EPIPE", "broken pipe"),
    (-100, "EPROTO", "protocol error"),
    (-43, "EPROTONOSUPPORT", "protocol not supported"),
    (-41, "EPROTOTYPE", "protocol wrong type for socket"),
    (-34, "ERANGE", "result too large"),
    (-30, "EROFS", "read-only file system"),
    (-58, "ESHUTDOWN", "cannot send after transport endpoint shutdown"),
    (-29, "ESPIPE", "invalid seek"),
    (-3, "ESRCH", "no such process"),
    (-60, "ETIMEDOUT", "connection timed out"),
    (-26, "ETXTBSY", "text file is busy"),
    (-18, "EXDEV", "cross-device link not permitted"),
    (-4094, "UNKNOWN", "unknown error"),
    (-4095, "EOF", "end of file"),
    (-6, "ENXIO", "no such device or address"),
    (-31, "EMLINK", "too many links"),
    (-64, "EHOSTDOWN", "host is down"),
    (-4030, "EREMOTEIO", "remote I/O error"),
    (-25, "ENOTTY", "inappropriate ioctl for device"),
    (-79, "EFTYPE", "inappropriate file type or format"),
    (-92, "EILSEQ", "illegal byte sequence"),
    (-44, "ESOCKTNOSUPPORT", "socket type not supported"),
    (-96, "ENODATA", "no data available"),
    (-4023, "EUNATCH", "protocol driver not attached"),
];

fn sys_error_entry(n: f64) -> Option<&'static (i32, &'static str, &'static str)> {
    SYS_ERRORS.iter().find(|e| e.0 as f64 == n)
}

fn sys_error_lookup(vm: &mut Vm, v: &Value, want_name: bool) -> JsResult<Value> {
    let n = match v {
        Value::Num(n) => *n,
        _ => return vm.throw_type("The \"err\" argument must be of type number."),
    };
    if !(n < 0.0 && n.fract() == 0.0) {
        return vm.throw_range(format!(
            "The value of \"err\" is out of range. It must be a negative integer. Received {}",
            crate::numconv::number_to_string(n)
        ));
    }
    Ok(match sys_error_entry(n) {
        Some(e) => Value::str(if want_name { e.1 } else { e.2 }),
        None => Value::str(&format!("Unknown system error {}", crate::numconv::number_to_string(n))),
    })
}

fn sys_error_map(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let ctor = get_global(vm, "Map");
    let m = vm.construct(&ctor, &[], None)?;
    if let Value::Obj(mo) = &m {
        let mut pairs = Vec::new();
        for (n, name, msg) in SYS_ERRORS {
            let pair = vm.new_array(vec![Value::str(name), Value::str(msg)]);
            pairs.push((Value::Num(*n as f64), Value::Obj(pair)));
        }
        if let ObjKind::Map(map) = &mut mo.borrow_mut().kind {
            for (k, v) in pairs {
                map.set(k, v);
            }
        }
    }
    Ok(m)
}

fn sys_error_code(n: f64) -> String {
    match sys_error_entry(n) {
        Some(e) => e.1.to_string(),
        None => format!("Unknown system error {}", crate::numconv::number_to_string(n)),
    }
}

fn errno_exception(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let n = vm.to_number(&a.arg(0))?;
    let code = sys_error_code(n);
    let syscall = string_of(vm, &a.arg(1))?.to_rust_string();
    let original = a.arg(2);
    let mut msg = format!("{} {}", syscall, code);
    if original.truthy() {
        msg.push(' ');
        msg.push_str(&string_of(vm, &original)?.to_rust_string());
    }
    let e = vm.make_error("Error", &msg);
    if let Value::Obj(o) = &e {
        o.set_prop(key("errno"), a.arg(0), WEC);
        o.set_prop(key("code"), Value::str(&code), WEC);
        o.set_prop(key("syscall"), a.arg(1), WEC);
    }
    Ok(e)
}

fn exception_with_host_port(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let n = vm.to_number(&a.arg(0))?;
    let code = sys_error_code(n);
    let syscall = string_of(vm, &a.arg(1))?.to_rust_string();
    let address = string_of(vm, &a.arg(2))?.to_rust_string();
    let port = a.arg(3);
    let mut msg = format!("{} {} {}", syscall, code, address);
    if port.truthy() {
        msg.push(':');
        msg.push_str(&string_of(vm, &port)?.to_rust_string());
    }
    let extra = a.arg(4);
    if extra.truthy() {
        msg.push_str(&format!(" - Local ({})", string_of(vm, &extra)?.to_rust_string()));
    }
    let e = vm.make_error("Error", &msg);
    if let Value::Obj(o) = &e {
        o.set_prop(key("errno"), a.arg(0), WEC);
        o.set_prop(key("code"), Value::str(&code), WEC);
        o.set_prop(key("syscall"), a.arg(1), WEC);
        o.set_prop(key("address"), a.arg(2), WEC);
        if port.truthy() {
            o.set_prop(key("port"), port, WEC);
        }
    }
    Ok(e)
}

/// Linux errno -> code name (used by fs for OS errors).
pub fn errno_name(n: i32) -> &'static str {
    match n {
        1 => "EPERM",
        2 => "ENOENT",
        3 => "ESRCH",
        4 => "EINTR",
        5 => "EIO",
        6 => "ENXIO",
        7 => "E2BIG",
        9 => "EBADF",
        11 => "EAGAIN",
        12 => "ENOMEM",
        13 => "EACCES",
        14 => "EFAULT",
        16 => "EBUSY",
        17 => "EEXIST",
        18 => "EXDEV",
        19 => "ENODEV",
        20 => "ENOTDIR",
        21 => "EISDIR",
        22 => "EINVAL",
        23 => "ENFILE",
        24 => "EMFILE",
        25 => "ENOTTY",
        26 => "ETXTBSY",
        27 => "EFBIG",
        28 => "ENOSPC",
        29 => "ESPIPE",
        30 => "EROFS",
        31 => "EMLINK",
        32 => "EPIPE",
        36 => "ENAMETOOLONG",
        38 => "ENOSYS",
        39 => "ENOTEMPTY",
        40 => "ELOOP",
        95 => "ENOTSUP",
        98 => "EADDRINUSE",
        104 => "ECONNRESET",
        110 => "ETIMEDOUT",
        111 => "ECONNREFUSED",
        _ => "UNKNOWN",
    }
}

// ---------------- aborted ----------------

fn util_aborted(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let signal = a.arg(0);
    let sig_ctor = get_global(vm, "AbortSignal");
    let is_signal = match &sig_ctor {
        Value::Obj(c) => {
            let p = vm.get(c, &vm.intr.key_prototype.clone(), &sig_ctor)?;
            match &p {
                Value::Obj(po) => proto_chain_has(vm, &signal, po)?,
                _ => false,
            }
        }
        _ => false,
    };
    if !is_signal {
        return vm.throw_type("The \"signal\" argument must be an instance of AbortSignal.");
    }
    let cap = vm.new_promise_capability_intrinsic();
    let aborted = vm.get_prop_of(&signal, &key("aborted"))?;
    if aborted.truthy() {
        vm.call(&cap.resolve, Value::Undefined, &[Value::Undefined])?;
        return Ok(cap.promise);
    }
    let on_abort = vm.native_closure("", 0, |vm, a| vm.call(&a.slot(0), Value::Undefined, &[Value::Undefined]), vec![cap.resolve.clone()]);
    let opts = vm.obj_from(vec![("once", Value::Bool(true))]);
    let add = vm.get_prop_of(&signal, &key("addEventListener"))?;
    if add.is_callable() {
        vm.call(&add, signal.clone(), &[Value::str("abort"), Value::Obj(on_abort), Value::Obj(opts)])?;
    }
    Ok(cap.promise)
}

// ============================================================================================
// parseArgs
// ============================================================================================

struct ArgSpec {
    name: JsStr,
    ty_string: bool,
    short: Value,
    multiple: bool,
    default: Value,
}

fn pa_error(vm: &mut Vm, msg: &str, code: &str) -> Value {
    coded_error(vm, "TypeError", msg, code)
}

fn str_of(v: &Value) -> Option<JsStr> {
    match v {
        Value::Str(s) => Some(s.clone()),
        _ => None,
    }
}

struct ParseState {
    values: Obj,
    tokens: Vec<Value>,
}

fn pa_store(vm: &mut Vm, st: &ParseState, spec: Option<&ArgSpec>, name: &JsStr, value: Value) -> JsResult<()> {
    if name.eq_str("__proto__") {
        return Ok(());
    }
    let k = PropKey::Str(name.clone());
    if spec.map_or(false, |s| s.multiple) {
        let existing = vm.get(&st.values, &k, &Value::Obj(st.values.clone()))?;
        match existing {
            Value::Obj(arr) if arr.is_array() => crate::vm::array_push_raw(&arr, value),
            _ => {
                let arr = vm.new_array(vec![value]);
                st.values.set_prop(k, Value::Obj(arr), WEC);
            }
        }
    } else {
        st.values.set_prop(k, value, WEC);
    }
    Ok(())
}

fn pa_token(vm: &mut Vm, pairs: Vec<(&str, Value)>) -> Value {
    Value::Obj(vm.obj_from(pairs))
}

fn parse_args(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cfg = a.arg(0);
    let getc = |vm: &mut Vm, name: &str| -> JsResult<Value> {
        match &cfg {
            Value::Obj(c) => vm.get(c, &key(name), &cfg),
            _ => Ok(Value::Undefined),
        }
    };
    let args_v = getc(vm, "args")?;
    let args: Vec<Value> = if args_v.is_nullish() {
        let process = vm.host.process_obj.clone().map(Value::Obj).unwrap_or(Value::Undefined);
        let argv = vm.get_prop_of(&process, &key("argv"))?;
        let all = if argv.is_object() { crate::builtins::array::array_like_to_vec(vm, &argv)? } else { Vec::new() };
        all.into_iter().skip(2).collect()
    } else if crate::builtins::array::is_array(vm, &args_v)? {
        crate::builtins::array::array_like_to_vec(vm, &args_v)?
    } else {
        return vm.throw_type("undefined is not a function");
    };
    let mut options = getc(vm, "options")?;
    if options.is_nullish() {
        options = Value::Obj(vm.new_object());
    }
    let opts_obj = match &options {
        Value::Obj(o) if !o.is_callable() => o.clone(),
        _ => return Err(pa_error(vm, "The \"options\" argument must be of type object.", "ERR_INVALID_ARG_TYPE")),
    };
    let strict_v = getc(vm, "strict")?;
    let strict = if strict_v.is_nullish() { true } else { strict_v.truthy() };
    let allow_v = getc(vm, "allowPositionals")?;
    let allow_positionals = if allow_v.is_nullish() { !strict } else { allow_v.truthy() };
    let want_tokens = getc(vm, "tokens")?.truthy();

    let mut specs: Vec<ArgSpec> = Vec::new();
    for name in vm.enumerable_own_keys(&opts_obj)? {
        let spec = vm.get(&opts_obj, &PropKey::Str(name.clone()), &options)?;
        let (ty, short, multiple, default) = match &spec {
            Value::Obj(so) => {
                let t = vm.get(so, &key("type"), &spec)?;
                let s = vm.get(so, &key("short"), &spec)?;
                let m = vm.get(so, &key("multiple"), &spec)?;
                let d = vm.get(so, &key("default"), &spec)?;
                (t, s, m.truthy(), d)
            }
            _ => (Value::Undefined, Value::Undefined, false, Value::Undefined),
        };
        let ty_string = match &ty {
            Value::Str(s) if s.eq_str("string") => true,
            Value::Str(s) if s.eq_str("boolean") => false,
            _ => {
                let msg = format!("options.{}.type must be \"string\" or \"boolean\".", name.to_rust_string());
                return Err(pa_error(vm, &msg, "ERR_INVALID_ARG_TYPE"));
            }
        };
        specs.push(ArgSpec { name, ty_string, short, multiple, default });
    }
    let find_long = |specs: &[ArgSpec], n: &JsStr| -> Option<usize> { specs.iter().position(|s| s.name == *n) };
    // a short flag maps to the option declaring it, else to the option named like the flag
    let long_for_short = |specs: &[ArgSpec], c: &JsStr| -> (JsStr, Option<usize>) {
        let name = match specs.iter().position(|s| matches!(&s.short, Value::Str(x) if x == c)) {
            Some(k) => specs[k].name.clone(),
            None => c.clone(),
        };
        let i = specs.iter().position(|s| s.name == name);
        (name, i)
    };

    let st = ParseState { values: new_null_proto_object(), tokens: Vec::new() };
    let mut st = st;
    let mut positionals: Vec<Value> = Vec::new();
    let n_orig = args.len() as i64;
    let mut list = args;
    let mut i = 0usize;
    let dash = b'-' as u16;
    while i < list.len() {
        let idx = i as i64 - 2 * (list.len() as i64 - n_orig);
        let arg = list[i].clone();
        let s = str_of(&arg);
        // option terminator
        if s.as_ref().map_or(false, |s| s.eq_str("--")) {
            if want_tokens {
                let t = pa_token(vm, vec![("kind", Value::str("option-terminator")), ("index", Value::Num(idx as f64))]);
                st.tokens.push(t);
            }
            let mut j = i + 1;
            while j < list.len() {
                let jdx = j as i64 - 2 * (list.len() as i64 - n_orig);
                let p = list[j].clone();
                if !allow_positionals {
                    let msg = format!("Unexpected argument '{}'. This command does not take positional arguments", string_of(vm, &p)?.to_rust_string());
                    return Err(pa_error(vm, &msg, "ERR_PARSE_ARGS_UNEXPECTED_POSITIONAL"));
                }
                if want_tokens {
                    let t = pa_token(vm, vec![("kind", Value::str("positional")), ("index", Value::Num(jdx as f64)), ("value", p.clone())]);
                    st.tokens.push(t);
                }
                positionals.push(p);
                j += 1;
            }
            break;
        }
        let su = s.as_ref().map(|s| s.units().to_vec()).unwrap_or_default();
        let is_long = s.is_some() && su.len() > 2 && su[0] == dash && su[1] == dash;
        let is_short = s.is_some() && su.len() > 1 && su[0] == dash && !is_long;
        if is_long {
            let body = &su[2..];
            let (name, inline) = match body.iter().position(|&c| c == b'=' as u16) {
                Some(p) => (JsStr::from_slice(&body[..p]), Some(JsStr::from_slice(&body[p + 1..]))),
                None => (JsStr::from_slice(body), None),
            };
            let raw = JsStr::concat(&JsStr::from_str("--"), &name);
            let consumed = pa_option(vm, &mut st, &specs, find_long(&specs, &name), &name, &raw, inline, &list, i, idx, strict, want_tokens)?;
            i += 1 + consumed;
            continue;
        }
        if is_short {
            let first = JsStr::from_slice(&su[1..2]);
            let (name, spec_i) = long_for_short(&specs, &first);
            if su.len() == 2 {
                let raw = JsStr::from_slice(&su[..2]);
                let consumed = pa_option(vm, &mut st, &specs, spec_i, &name, &raw, None, &list, i, idx, strict, want_tokens)?;
                i += 1 + consumed;
                continue;
            }
            // "-fVALUE" for a string option
            if let Some(k) = spec_i {
                if specs[k].ty_string {
                    let raw = JsStr::from_slice(&su[..2]);
                    let inline = Some(JsStr::from_slice(&su[2..]));
                    let consumed = pa_option(vm, &mut st, &specs, spec_i, &name, &raw, inline, &list, i, idx, strict, want_tokens)?;
                    i += 1 + consumed;
                    continue;
                }
            }
            // short option group: expand in place
            let mut expanded: Vec<Value> = Vec::new();
            let mut j = 1;
            while j < su.len() {
                let c = JsStr::from_slice(&su[j..j + 1]);
                let is_str = long_for_short(&specs, &c).1.map_or(false, |k| specs[k].ty_string);
                if !is_str || j == su.len() - 1 {
                    let mut u = vec![dash];
                    u.push(su[j]);
                    expanded.push(jsv(u));
                } else {
                    let mut u = vec![dash];
                    u.extend_from_slice(&su[j..]);
                    expanded.push(jsv(u));
                    break;
                }
                j += 1;
            }
            list.splice(i..i + 1, expanded);
            continue;
        }
        // positional
        if !allow_positionals {
            let msg = format!("Unexpected argument '{}'. This command does not take positional arguments", string_of(vm, &arg)?.to_rust_string());
            return Err(pa_error(vm, &msg, "ERR_PARSE_ARGS_UNEXPECTED_POSITIONAL"));
        }
        if want_tokens {
            let t = pa_token(vm, vec![("kind", Value::str("positional")), ("index", Value::Num(idx as f64)), ("value", arg.clone())]);
            st.tokens.push(t);
        }
        positionals.push(arg);
        i += 1;
    }
    // defaults
    for s in &specs {
        if s.default.is_undefined() {
            continue;
        }
        let k = PropKey::Str(s.name.clone());
        let cur = vm.get(&st.values, &k, &Value::Obj(st.values.clone()))?;
        if cur.is_undefined() {
            st.values.set_prop(k, s.default.clone(), WEC);
        }
    }
    let r = vm.new_object();
    r.set_str("values", Value::Obj(st.values.clone()), WEC);
    let pa = vm.new_array(positionals);
    r.set_str("positionals", Value::Obj(pa), WEC);
    if want_tokens {
        let toks = std::mem::take(&mut st.tokens);
        let ta = vm.new_array(toks);
        r.set_str("tokens", Value::Obj(ta), WEC);
    }
    Ok(Value::Obj(r))
}

/// Handle one option occurrence; returns how many following args were consumed as its value.
#[allow(clippy::too_many_arguments)]
fn pa_option(
    vm: &mut Vm,
    st: &mut ParseState,
    specs: &[ArgSpec],
    spec_i: Option<usize>,
    name: &JsStr,
    raw: &JsStr,
    inline: Option<JsStr>,
    list: &[Value],
    i: usize,
    idx: i64,
    strict: bool,
    want_tokens: bool,
) -> JsResult<usize> {
    let raw_s = raw.to_rust_string();
    let spec = spec_i.map(|k| &specs[k]);
    let mut consumed = 0;
    // (value, is_inline) or None for a flag
    let value: Option<(Value, bool)> = match spec {
        None => {
            if strict {
                return Err(pa_error(vm, &format!("Unknown option '{}'", raw_s), "ERR_PARSE_ARGS_UNKNOWN_OPTION"));
            }
            inline.map(|v| (Value::Str(v), true))
        }
        Some(sp) if sp.ty_string => match inline {
            Some(v) => Some((Value::Str(v), true)),
            None => match list.get(i + 1) {
                None => {
                    if strict {
                        return Err(pa_error(vm, &format!("Option '{} <value>' argument missing", raw_s), "ERR_PARSE_ARGS_INVALID_OPTION_VALUE"));
                    }
                    None
                }
                Some(next) => {
                    let ambiguous = matches!(next, Value::Str(ns) if ns.len() > 1 && ns.units()[0] == b'-' as u16);
                    if ambiguous && strict {
                        let ns = string_of(vm, next)?.to_rust_string();
                        return Err(pa_error(vm, &format!("Option '{}' argument is ambiguous. Received '{}'", raw_s, ns), "ERR_PARSE_ARGS_INVALID_OPTION_VALUE"));
                    }
                    consumed = 1;
                    Some((next.clone(), false))
                }
            },
        },
        Some(_) => match inline {
            Some(v) => {
                if strict {
                    return Err(pa_error(vm, &format!("Option '{}' does not take an argument", raw_s), "ERR_PARSE_ARGS_INVALID_OPTION_VALUE"));
                }
                Some((Value::Str(v), true))
            }
            None => None,
        },
    };
    if want_tokens {
        let mut pairs: Vec<(&str, Value)> = vec![
            ("kind", Value::str("option")),
            ("name", Value::Str(name.clone())),
            ("rawName", Value::Str(raw.clone())),
            ("index", Value::Num(idx as f64)),
        ];
        if let Some((v, inl)) = &value {
            pairs.push(("value", v.clone()));
            pairs.push(("inlineValue", Value::Bool(*inl)));
        }
        let t = pa_token(vm, pairs);
        st.tokens.push(t);
    }
    let stored = value.map(|(v, _)| v).unwrap_or(Value::Bool(true));
    pa_store(vm, st, spec, name, stored)?;
    Ok(consumed)
}

// ============================================================================================
// parseEnv
// ============================================================================================

fn is_js_ws(c: u16) -> bool {
    matches!(c, 0x09 | 0x0a | 0x0b | 0x0c | 0x0d | 0x20 | 0xa0 | 0x1680 | 0x2000..=0x200a | 0x2028 | 0x2029 | 0x202f | 0x205f | 0x3000 | 0xfeff)
}

fn trim_units(s: &[u16]) -> &[u16] {
    let mut a = 0;
    let mut b = s.len();
    while a < b && is_js_ws(s[a]) {
        a += 1;
    }
    while b > a && is_js_ws(s[b - 1]) {
        b -= 1;
    }
    &s[a..b]
}

pub fn parse_env_units(s: &[u16]) -> Vec<(Vec<u16>, Vec<u16>)> {
    let mut out: Vec<(Vec<u16>, Vec<u16>)> = Vec::new();
    let nl = b'\n' as u16;
    let mut i = 0;
    while i < s.len() {
        let line_end = s[i..].iter().position(|&c| c == nl).map(|p| i + p).unwrap_or(s.len());
        // leading whitespace
        let mut p = i;
        while p < line_end && is_js_ws(s[p]) {
            p += 1;
        }
        if p >= line_end || s[p] == b'#' as u16 {
            i = line_end + 1;
            continue;
        }
        // "export " prefix
        let ex = u16s("export");
        if line_end - p > ex.len() && s[p..p + ex.len()] == ex[..] && (s[p + ex.len()] == b' ' as u16 || s[p + ex.len()] == b'\t' as u16) {
            p += ex.len();
            while p < line_end && (s[p] == b' ' as u16 || s[p] == b'\t' as u16) {
                p += 1;
            }
        }
        let eq = match s[p..line_end].iter().position(|&c| c == b'=' as u16) {
            Some(e) => p + e,
            None => {
                i = line_end + 1;
                continue;
            }
        };
        let k = trim_units(&s[p..eq]).to_vec();
        if k.is_empty() {
            i = line_end + 1;
            continue;
        }
        let mut v = eq + 1;
        while v < line_end && (s[v] == b' ' as u16 || s[v] == b'\t' as u16) {
            v += 1;
        }
        let q = if v < line_end { s[v] } else { 0 };
        if q == b'"' as u16 || q == b'\'' as u16 || q == b'`' as u16 {
            let start = v + 1;
            let mut j = start;
            let mut close = None;
            while j < s.len() {
                if q == b'"' as u16 && s[j] == b'\\' as u16 {
                    j += 2;
                    continue;
                }
                if s[j] == q {
                    close = Some(j);
                    break;
                }
                j += 1;
            }
            let end = close.unwrap_or(s.len());
            let raw = &s[start..end.min(s.len())];
            let val = if q == b'"' as u16 { unescape_env(raw) } else { raw.to_vec() };
            out.retain(|(ok, _)| *ok != k);
            out.push((k, val));
            i = match close {
                Some(c) => s[c..].iter().position(|&ch| ch == nl).map(|p| c + p + 1).unwrap_or(s.len()),
                None => s.len(),
            };
            continue;
        }
        let mut val = &s[v..line_end];
        let sp_hash = [b' ' as u16, b'#' as u16];
        if let Some(pos) = val.windows(2).position(|w| w == sp_hash) {
            val = &val[..pos];
        }
        let val = trim_units(val).to_vec();
        out.retain(|(ok, _)| *ok != k);
        out.push((k, val));
        i = line_end + 1;
    }
    out
}

fn unescape_env(raw: &[u16]) -> Vec<u16> {
    let mut out = Vec::with_capacity(raw.len());
    let mut i = 0;
    while i < raw.len() {
        let c = raw[i];
        if c == b'\\' as u16 && i + 1 < raw.len() {
            let n = raw[i + 1];
            let r = match n {
                0x6e => b'\n' as u16,
                0x72 => b'\r' as u16,
                0x74 => b'\t' as u16,
                other => other,
            };
            out.push(r);
            i += 2;
            continue;
        }
        out.push(c);
        i += 1;
    }
    out
}

fn parse_env(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = new_null_proto_object();
    if let Value::Str(s) = a.arg(0) {
        for (k, v) in parse_env_units(s.units()) {
            o.set_prop(PropKey::Str(JsStr::from_units(k)), jsv(v), WEC);
        }
    }
    Ok(Value::Obj(o))
}

// ============================================================================================
// util.diff
// ============================================================================================

/// Edit script between two sequences: an LCS table walked back from the end (ties prefer
/// taking from `expected`); 1 = only in actual, -1 = only in expected, 0 = common.
fn seq_diff(a: &[Value], b: &[Value]) -> Vec<(i32, Value)> {
    let n = a.len();
    let m = b.len();
    let w = m + 1;
    let mut dp = vec![0u32; (n + 1) * w];
    for i in 1..=n {
        for j in 1..=m {
            dp[i * w + j] = if Value::strict_eq(&a[i - 1], &b[j - 1]) { dp[(i - 1) * w + j - 1] + 1 } else { dp[(i - 1) * w + j].max(dp[i * w + j - 1]) };
        }
    }
    let (mut i, mut j) = (n, m);
    let mut out = Vec::with_capacity(n + m);
    while i > 0 || j > 0 {
        if i > 0 && j > 0 && Value::strict_eq(&a[i - 1], &b[j - 1]) {
            out.push((0, a[i - 1].clone()));
            i -= 1;
            j -= 1;
        } else if j == 0 || (i > 0 && dp[(i - 1) * w + j] > dp[i * w + j - 1]) {
            out.push((1, a[i - 1].clone()));
            i -= 1;
        } else {
            out.push((-1, b[j - 1].clone()));
            j -= 1;
        }
    }
    out.reverse();
    out
}

fn util_diff(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let actual = a.arg(0);
    let expected = a.arg(1);
    let to_units = |s: &JsStr| -> Vec<Value> { s.units().iter().map(|&c| jsv(vec![c])).collect() };
    let (xs, ys) = match (&actual, &expected) {
        (Value::Str(x), Value::Str(y)) => {
            if x == y {
                return Ok(Value::Obj(vm.new_array(Vec::new())));
            }
            (to_units(x), to_units(y))
        }
        (Value::Str(_), _) => return Err(coded_error(vm, "TypeError", "The \"expected\" argument must be of type string.", "ERR_INVALID_ARG_TYPE")),
        _ => {
            let both = crate::builtins::array::is_array(vm, &actual)? && crate::builtins::array::is_array(vm, &expected)?;
            if !both {
                let msg = "The \"actual\" and \"expected\" arguments must both be strings or both be arrays.";
                return Err(coded_error(vm, "TypeError", msg, "ERR_INVALID_ARG_TYPE"));
            }
            let xs = crate::builtins::array::array_like_to_vec(vm, &actual)?;
            let ys = crate::builtins::array::array_like_to_vec(vm, &expected)?;
            for (name, list) in [("actual", &xs), ("expected", &ys)] {
                for (i, v) in list.iter().enumerate() {
                    if !matches!(v, Value::Str(_)) {
                        let msg = format!("The \"{}[{}]\" argument must be of type string.", name, i);
                        return Err(coded_error(vm, "TypeError", &msg, "ERR_INVALID_ARG_TYPE"));
                    }
                }
            }
            (xs, ys)
        }
    };
    let d = seq_diff(&xs, &ys);
    let mut items = Vec::with_capacity(d.len());
    for (op, v) in d {
        let pair = vm.new_array(vec![Value::Num(op as f64), v]);
        items.push(Value::Obj(pair));
    }
    Ok(Value::Obj(vm.new_array(items)))
}

// ============================================================================================
// MIMEType / MIMEParams
// ============================================================================================

struct MimeData {
    ty: std::cell::RefCell<String>,
    subtype: std::cell::RefCell<String>,
    params: Obj,
}

struct MimeParamsData {
    entries: std::cell::RefCell<Vec<(String, String)>>,
}

thread_local! {
    static MIME_PROTOS: std::cell::RefCell<Option<(Obj, Obj)>> = const { std::cell::RefCell::new(None) };
}

fn is_token_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || "!#$%&'*+-.^_`|~".contains(c)
}

fn is_token(s: &str) -> bool {
    !s.is_empty() && s.chars().all(is_token_char)
}

fn http_ws(c: char) -> bool {
    matches!(c, ' ' | '\t' | '\n' | '\r')
}

type MimeParsed = (String, String, Vec<(String, String)>);

fn mime_parse(input: &str) -> Result<MimeParsed, String> {
    let s = input.trim_matches(http_ws);
    let slash = match s.find('/') {
        Some(p) => p,
        None => return Err(format!("The MIME syntax for \"{}\" is invalid: missing \"/\"", input)),
    };
    let ty = &s[..slash];
    if !is_token(ty) {
        return Err(format!("The MIME syntax for \"{}\" is invalid", input));
    }
    let rest = &s[slash + 1..];
    let semi = rest.find(';').unwrap_or(rest.len());
    let sub = rest[..semi].trim_matches(http_ws);
    if !is_token(sub) {
        return Err(format!("The MIME syntax for \"{}\" is invalid", input));
    }
    let mut params: Vec<(String, String)> = Vec::new();
    let chars: Vec<char> = rest[semi..].chars().collect();
    let mut p = 0;
    while p < chars.len() {
        // at ';'
        p += 1;
        while p < chars.len() && http_ws(chars[p]) {
            p += 1;
        }
        let ns = p;
        while p < chars.len() && chars[p] != ';' && chars[p] != '=' {
            p += 1;
        }
        let name: String = chars[ns..p].iter().collect::<String>().trim_matches(http_ws).to_ascii_lowercase();
        if p < chars.len() && chars[p] == ';' {
            continue;
        }
        if p >= chars.len() {
            break;
        }
        p += 1; // '='
        while p < chars.len() && http_ws(chars[p]) {
            p += 1;
        }
        let value: String;
        if p < chars.len() && chars[p] == '"' {
            p += 1;
            let mut v = String::new();
            while p < chars.len() {
                let c = chars[p];
                if c == '\\' && p + 1 < chars.len() {
                    v.push(chars[p + 1]);
                    p += 2;
                    continue;
                }
                if c == '"' {
                    p += 1;
                    break;
                }
                v.push(c);
                p += 1;
            }
            while p < chars.len() && chars[p] != ';' {
                p += 1;
            }
            value = v;
        } else {
            let vs = p;
            while p < chars.len() && chars[p] != ';' {
                p += 1;
            }
            value = chars[vs..p].iter().collect::<String>().trim_matches(http_ws).to_string();
        }
        if is_token(&name) && !params.iter().any(|(n, _)| *n == name) {
            params.push((name, value));
        }
    }
    Ok((ty.to_ascii_lowercase(), sub.to_ascii_lowercase(), params))
}

fn mime_param_string(params: &[(String, String)]) -> String {
    let mut out = String::new();
    for (i, (n, v)) in params.iter().enumerate() {
        if i > 0 {
            out.push(';');
        }
        out.push_str(n);
        out.push('=');
        if is_token(v) {
            out.push_str(v);
        } else {
            out.push('"');
            for c in v.chars() {
                if c == '"' || c == '\\' {
                    out.push('\\');
                }
                out.push(c);
            }
            out.push('"');
        }
    }
    out
}

fn mime_this(vm: &mut Vm, this: &Value) -> JsResult<(String, String, Obj)> {
    if let Value::Obj(o) = this {
        if let ObjKind::Host(h) = &o.borrow().kind {
            if let Some(m) = h.downcast_ref::<MimeData>() {
                return Ok((m.ty.borrow().clone(), m.subtype.borrow().clone(), m.params.clone()));
            }
        }
    }
    vm.throw_type("Illegal invocation")
}

fn mime_params_entries(vm: &mut Vm, p: &Value) -> JsResult<Vec<(String, String)>> {
    if let Value::Obj(o) = p {
        if let ObjKind::Host(h) = &o.borrow().kind {
            if let Some(m) = h.downcast_ref::<MimeParamsData>() {
                return Ok(m.entries.borrow().clone());
            }
        }
    }
    vm.throw_type("Illegal invocation")
}

fn with_params<R>(p: &Value, f: impl FnOnce(&mut Vec<(String, String)>) -> R) -> Option<R> {
    if let Value::Obj(o) = p {
        if let ObjKind::Host(h) = &o.borrow().kind {
            if let Some(m) = h.downcast_ref::<MimeParamsData>() {
                return Some(f(&mut m.entries.borrow_mut()));
            }
        }
    }
    None
}

fn new_mime_params(vm: &mut Vm, entries: Vec<(String, String)>, proto: Option<Obj>) -> Obj {
    let proto = proto.unwrap_or_else(|| MIME_PROTOS.with(|m| m.borrow().as_ref().map(|p| p.1.clone())).unwrap_or_else(|| vm.intr.object_proto.clone()));
    Obj::new(Some(proto), ObjKind::Host(Box::new(MimeParamsData { entries: std::cell::RefCell::new(entries) })))
}

fn mime_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return class_call_error(vm);
    }
    let input = string_of(vm, &a.arg(0))?.to_rust_string();
    let (ty, sub, params) = match mime_parse(&input) {
        Ok(p) => p,
        Err(m) => return Err(coded_error(vm, "TypeError", &m, "ERR_INVALID_MIME_SYNTAX")),
    };
    let fallback = MIME_PROTOS.with(|m| m.borrow().as_ref().map(|p| p.0.clone())).unwrap_or_else(|| vm.intr.object_proto.clone());
    let proto = vm.proto_from_nt(&a.new_target, &fallback)?;
    let po = new_mime_params(vm, params, None);
    let data = MimeData { ty: std::cell::RefCell::new(ty), subtype: std::cell::RefCell::new(sub), params: po };
    Ok(Value::Obj(Obj::new(Some(proto), ObjKind::Host(Box::new(data)))))
}

fn mime_params_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return class_call_error(vm);
    }
    let fallback = MIME_PROTOS.with(|m| m.borrow().as_ref().map(|p| p.1.clone())).unwrap_or_else(|| vm.intr.object_proto.clone());
    let proto = vm.proto_from_nt(&a.new_target, &fallback)?;
    Ok(Value::Obj(new_mime_params(vm, Vec::new(), Some(proto))))
}

fn mime_to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ty, sub, params) = mime_this(vm, &a.this)?;
    let entries = mime_params_entries(vm, &Value::Obj(params))?;
    let mut s = format!("{}/{}", ty, sub);
    if !entries.is_empty() {
        s.push(';');
        s.push_str(&mime_param_string(&entries));
    }
    Ok(Value::str(&s))
}

fn mime_set_part(vm: &mut Vm, a: &Args, which: u8) -> JsResult<Value> {
    mime_this(vm, &a.this)?;
    let v = string_of(vm, &a.arg(0))?.to_rust_string();
    if !is_token(&v) {
        let what = if which == 0 { "type" } else { "subtype" };
        let msg = format!("The MIME {} \"{}\" is invalid", what, v);
        return Err(coded_error(vm, "TypeError", &msg, "ERR_INVALID_MIME_SYNTAX"));
    }
    if let Value::Obj(o) = &a.this {
        if let ObjKind::Host(h) = &o.borrow().kind {
            if let Some(m) = h.downcast_ref::<MimeData>() {
                if which == 0 {
                    *m.ty.borrow_mut() = v.to_ascii_lowercase();
                } else {
                    *m.subtype.borrow_mut() = v.to_ascii_lowercase();
                }
            }
        }
    }
    Ok(Value::Undefined)
}

fn mime_iter(vm: &mut Vm, a: &Args, kind: u8) -> JsResult<Value> {
    let entries = mime_params_entries(vm, &a.this)?;
    let items: Vec<Value> = entries
        .into_iter()
        .map(|(k, v)| match kind {
            0 => Value::str(&k),
            1 => Value::str(&v),
            _ => Value::Obj(vm.new_array(vec![Value::str(&k), Value::str(&v)])),
        })
        .collect();
    let arr = Value::Obj(vm.new_array(items));
    let values = vm.get_prop_of(&arr, &key("values"))?;
    vm.call(&values, arr, &[])
}

fn create_mime_classes(vm: &mut Vm) -> (Obj, Obj) {
    let (mime, mp) = make_class(vm, "MIMEType", 1, mime_ctor, None);
    let (params, pp) = make_class(vm, "MIMEParams", 0, mime_params_ctor, None);
    MIME_PROTOS.with(|m| *m.borrow_mut() = Some((mp.clone(), pp.clone())));
    vm.def_accessor(&mp, "type", |vm, a| Ok(Value::str(&mime_this(vm, &a.this)?.0)), |vm, a| mime_set_part(vm, a, 0));
    vm.def_accessor(&mp, "subtype", |vm, a| Ok(Value::str(&mime_this(vm, &a.this)?.1)), |vm, a| mime_set_part(vm, a, 1));
    vm.def_getter(&mp, "essence", |vm, a| {
        let (t, s, _) = mime_this(vm, &a.this)?;
        Ok(Value::str(&format!("{}/{}", t, s)))
    });
    vm.def_getter(&mp, "params", |vm, a| Ok(Value::Obj(mime_this(vm, &a.this)?.2)));
    vm.def_method(&mp, "toString", 0, mime_to_string);
    vm.def_method(&mp, "toJSON", 0, mime_to_string);
    vm.def_method(&pp, "delete", 1, |vm, a| {
        let n = string_of(vm, &a.arg(0))?.to_rust_string();
        with_params(&a.this, |e| e.retain(|(k, _)| *k != n));
        Ok(Value::Undefined)
    });
    vm.def_method(&pp, "get", 1, |vm, a| {
        let n = string_of(vm, &a.arg(0))?.to_rust_string();
        let r = with_params(&a.this, |e| e.iter().find(|(k, _)| *k == n).map(|(_, v)| v.clone())).flatten();
        Ok(r.map(|v| Value::str(&v)).unwrap_or(Value::Null))
    });
    vm.def_method(&pp, "has", 1, |vm, a| {
        let n = string_of(vm, &a.arg(0))?.to_rust_string();
        Ok(Value::Bool(with_params(&a.this, |e| e.iter().any(|(k, _)| *k == n)).unwrap_or(false)))
    });
    vm.def_method(&pp, "set", 2, |vm, a| {
        let n = string_of(vm, &a.arg(0))?.to_rust_string();
        let v = string_of(vm, &a.arg(1))?.to_rust_string();
        if !is_token(&n) {
            let msg = format!("The MIME parameter name \"{}\" is invalid", n);
            return Err(coded_error(vm, "TypeError", &msg, "ERR_INVALID_MIME_SYNTAX"));
        }
        with_params(&a.this, |e| match e.iter_mut().find(|(k, _)| *k == n) {
            Some(slot) => slot.1 = v,
            None => e.push((n, v)),
        });
        Ok(Value::Undefined)
    });
    vm.def_method(&pp, "entries", 0, |vm, a| mime_iter(vm, a, 2));
    vm.def_method(&pp, "keys", 0, |vm, a| mime_iter(vm, a, 0));
    vm.def_method(&pp, "values", 0, |vm, a| mime_iter(vm, a, 1));
    let it = vm.intr.sym_iterator.clone();
    vm.def_sym_method(&pp, &it, "entries", 0, |vm, a| mime_iter(vm, a, 2));
    (mime, params)
}

// ============================================================================================
// deep equality
// ============================================================================================

fn same_proto(vm: &mut Vm, x: &Obj, y: &Obj) -> JsResult<bool> {
    let px = vm.get_prototype_of(x)?;
    let py = vm.get_prototype_of(y)?;
    Ok(match (&px, &py) {
        (Some(p), Some(q)) => p.ptr_eq(q),
        (None, None) => true,
        _ => false,
    })
}

fn date_value(vm: &mut Vm, o: &Obj) -> JsResult<f64> {
    let t = match &o.borrow().kind {
        ObjKind::Date(t) => Some(*t),
        _ => None,
    };
    match t {
        Some(t) => Ok(t),
        None => vm.throw_type("this is not a Date object"),
    }
}

fn map_entries(o: &Obj) -> Vec<(Value, Value)> {
    match &o.borrow().kind {
        ObjKind::Map(m) | ObjKind::Set(m) => m.entries.iter().flatten().cloned().collect(),
        _ => Vec::new(),
    }
}

fn map_lookup(o: &Obj, k: &Value) -> Option<Value> {
    match &o.borrow().kind {
        ObjKind::Map(m) | ObjKind::Set(m) => m.get(k).cloned(),
        _ => None,
    }
}

fn map_has(o: &Obj, k: &Value) -> bool {
    match &o.borrow().kind {
        ObjKind::Map(m) | ObjKind::Set(m) => m.has(k),
        _ => false,
    }
}

/// assert.deepEqual / assert.deepStrictEqual semantics of the reference.
pub fn deep_equal(vm: &mut Vm, a: &Value, b: &Value, strict: bool) -> JsResult<bool> {
    let mut memo = Vec::new();
    enter_frames(vm, 1)?;
    let r = assert_deq(vm, a, b, strict, &mut memo);
    leave_frames(vm, 1);
    r
}

fn assert_deq(vm: &mut Vm, a: &Value, b: &Value, strict: bool, memo: &mut Vec<(Obj, Obj)>) -> JsResult<bool> {
    enter_frames(vm, 1)?;
    let r = assert_deq_body(vm, a, b, strict, memo);
    leave_frames(vm, 1);
    r
}

fn assert_deq_body(vm: &mut Vm, a: &Value, b: &Value, strict: bool, memo: &mut Vec<(Obj, Obj)>) -> JsResult<bool> {
    if strict {
        if Value::same_value(a, b) {
            return Ok(true);
        }
    } else if vm.loose_eq(a, b)? {
        return Ok(true);
    }
    let (x, y) = match (a, b) {
        (Value::Obj(x), Value::Obj(y)) if !x.is_callable() && !y.is_callable() => (x.clone(), y.clone()),
        _ => return Ok(false),
    };
    if memo.iter().any(|(p, q)| p.ptr_eq(&x) && q.ptr_eq(&y)) {
        return Ok(true);
    }
    if strict && !same_proto(vm, &x, &y)? {
        return Ok(false);
    }
    if crate::builtins::array::is_array(vm, a)? != crate::builtins::array::is_array(vm, b)? {
        return Ok(false);
    }
    let date_proto = vm.intr.date_proto.clone();
    if proto_chain_has(vm, a, &date_proto)? && proto_chain_has(vm, b, &date_proto)? {
        let tx = date_value(vm, &x)?;
        let ty = date_value(vm, &y)?;
        return Ok(tx == ty);
    }
    let re_proto = vm.intr.regexp_proto.clone();
    if proto_chain_has(vm, a, &re_proto)? && proto_chain_has(vm, b, &re_proto)? {
        let sx = vm.get(&x, &key("source"), a)?;
        let sy = vm.get(&y, &key("source"), b)?;
        let fx = vm.get(&x, &key("flags"), a)?;
        let fy = vm.get(&y, &key("flags"), b)?;
        return Ok(Value::strict_eq(&sx, &sy) && Value::strict_eq(&fx, &fy));
    }
    let both_ta = matches!(x.borrow().kind, ObjKind::TypedArray(_)) && matches!(y.borrow().kind, ObjKind::TypedArray(_));
    if both_ta {
        let lx = vm.get(&x, &vm.intr.key_length.clone(), a)?;
        let ly = vm.get(&y, &vm.intr.key_length.clone(), b)?;
        if !Value::strict_eq(&lx, &ly) {
            return Ok(false);
        }
        let n = vm.to_length(&lx)?;
        for i in 0..n {
            let k = PropKey::Str(index_to_jsstr(i));
            let ex = vm.get(&x, &k, a)?;
            let ey = vm.get(&y, &k, b)?;
            if !Value::strict_eq(&ex, &ey) {
                return Ok(false);
            }
        }
    }
    let map_proto = vm.intr.map_proto.clone();
    let set_proto = vm.intr.set_proto.clone();
    memo.push((x.clone(), y.clone()));
    let r = (|| -> JsResult<bool> {
        if proto_chain_has(vm, a, &map_proto)? && proto_chain_has(vm, b, &map_proto)? {
            let sx = vm.get(&x, &key("size"), a)?;
            let sy = vm.get(&y, &key("size"), b)?;
            if !Value::strict_eq(&sx, &sy) {
                return Ok(false);
            }
            for (k, v) in map_entries(&x) {
                if !map_has(&y, &k) {
                    return Ok(false);
                }
                let w = map_lookup(&y, &k).unwrap_or(Value::Undefined);
                if !assert_deq(vm, &v, &w, strict, memo)? {
                    return Ok(false);
                }
            }
        } else if proto_chain_has(vm, a, &set_proto)? && proto_chain_has(vm, b, &set_proto)? {
            let sx = vm.get(&x, &key("size"), a)?;
            let sy = vm.get(&y, &key("size"), b)?;
            if !Value::strict_eq(&sx, &sy) {
                return Ok(false);
            }
            for (k, _) in map_entries(&x) {
                if !map_has(&y, &k) {
                    return Ok(false);
                }
            }
        }
        let kx = vm.enumerable_own_keys(&x)?;
        let ky = vm.enumerable_own_keys(&y)?;
        if kx.len() != ky.len() {
            return Ok(false);
        }
        for k in &kx {
            let pk = PropKey::Str(k.clone());
            if !vm.has_own_property(&y, &pk)? {
                return Ok(false);
            }
            let vx = vm.get(&x, &pk, a)?;
            let vy = vm.get(&y, &pk, b)?;
            if !assert_deq(vm, &vx, &vy, strict, memo)? {
                return Ok(false);
            }
        }
        Ok(true)
    })();
    memo.pop();
    r
}

/// Own enumerable keys including symbols (isDeepStrictEqual compares both).
fn own_enum_keys_all(vm: &mut Vm, o: &Obj) -> JsResult<Vec<PropKey>> {
    let keys = vm.own_property_keys(o)?;
    let mut out = Vec::new();
    for k in keys {
        if k.is_private() {
            continue;
        }
        if let Some(d) = vm.get_own_property(o, &k)? {
            if d.enumerable == Some(true) {
                out.push(k);
            }
        }
    }
    Ok(out)
}

/// util.isDeepStrictEqual semantics of the reference (differs from assert's).
pub fn is_deep_strict_equal(vm: &mut Vm, a: &Value, b: &Value) -> JsResult<bool> {
    let mut memo = Vec::new();
    enter_frames(vm, 2)?;
    let r = dse(vm, a, b, &mut memo);
    leave_frames(vm, 2);
    r
}

fn primitive_of(o: &Obj) -> Option<Value> {
    match &o.borrow().kind {
        ObjKind::Number(n) => Some(Value::Num(*n)),
        ObjKind::String(s) => Some(Value::Str(s.clone())),
        ObjKind::Boolean(b) => Some(Value::Bool(*b)),
        ObjKind::Symbol(s) => Some(Value::Sym(s.clone())),
        ObjKind::BigInt(b) => Some(Value::BigInt(b.clone())),
        _ => None,
    }
}

fn dse(vm: &mut Vm, a: &Value, b: &Value, memo: &mut Vec<(Obj, Obj)>) -> JsResult<bool> {
    enter_frames(vm, 1)?;
    let r = dse_body(vm, a, b, memo);
    leave_frames(vm, 1);
    r
}

fn dse_body(vm: &mut Vm, a: &Value, b: &Value, memo: &mut Vec<(Obj, Obj)>) -> JsResult<bool> {
    if Value::same_value(a, b) {
        return Ok(true);
    }
    let (x, y) = match (a, b) {
        (Value::Obj(x), Value::Obj(y)) if !x.is_callable() && !y.is_callable() => (x.clone(), y.clone()),
        _ => return Ok(false),
    };
    if memo.iter().any(|(p, q)| p.ptr_eq(&x) && q.ptr_eq(&y)) {
        return Ok(true);
    }
    if !same_proto(vm, &x, &y)? {
        return Ok(false);
    }
    if tag_of(vm, a)? != tag_of(vm, b)? {
        return Ok(false);
    }
    if crate::builtins::array::is_array(vm, a)? != crate::builtins::array::is_array(vm, b)? {
        return Ok(false);
    }
    enum K {
        Date(f64, f64),
        Re,
        Boxed(Value, Value),
        Bytes(Vec<u8>, Vec<u8>),
        Ta(usize, usize),
        Map,
        Set,
        Plain,
    }
    let k = {
        let bx = x.borrow();
        let by = y.borrow();
        match (&bx.kind, &by.kind) {
            (ObjKind::Date(p), ObjKind::Date(q)) => K::Date(*p, *q),
            (ObjKind::RegExp(_), ObjKind::RegExp(_)) => K::Re,
            (ObjKind::ArrayBuffer(_), ObjKind::ArrayBuffer(_)) | (ObjKind::DataView(_), ObjKind::DataView(_)) => {
                drop(bx);
                drop(by);
                K::Bytes(crate::builtins::typedarray::ta_bytes(&x), crate::builtins::typedarray::ta_bytes(&y))
            }
            (ObjKind::TypedArray(p), ObjKind::TypedArray(q)) => K::Ta(p.len(), q.len()),
            (ObjKind::Map(_), ObjKind::Map(_)) => K::Map,
            (ObjKind::Set(_), ObjKind::Set(_)) => K::Set,
            _ => {
                drop(bx);
                drop(by);
                match (primitive_of(&x), primitive_of(&y)) {
                    (Some(p), Some(q)) => K::Boxed(p, q),
                    _ => K::Plain,
                }
            }
        }
    };
    match &k {
        K::Date(p, q) => return Ok(Value::same_value(&Value::Num(*p), &Value::Num(*q))),
        K::Re => {
            let sx = vm.get(&x, &key("source"), a)?;
            let sy = vm.get(&y, &key("source"), b)?;
            let fx = vm.get(&x, &key("flags"), a)?;
            let fy = vm.get(&y, &key("flags"), b)?;
            if !Value::strict_eq(&sx, &sy) || !Value::strict_eq(&fx, &fy) {
                return Ok(false);
            }
        }
        K::Boxed(p, q) => {
            if !Value::same_value(p, q) {
                return Ok(false);
            }
        }
        K::Bytes(p, q) => {
            if p != q {
                return Ok(false);
            }
        }
        K::Ta(p, q) => {
            // the reference never reports two distinct non-empty typed arrays as equal
            if *p != 0 || *q != 0 {
                return Ok(false);
            }
        }
        _ => {}
    }
    memo.push((x.clone(), y.clone()));
    let r = (|| -> JsResult<bool> {
        match &k {
            K::Map => {
                let ex = map_entries(&x);
                let ey = map_entries(&y);
                if ex.len() != ey.len() {
                    return Ok(false);
                }
                let mut used = vec![false; ey.len()];
                for (kx, vx) in &ex {
                    if map_has(&y, kx) {
                        let vy = map_lookup(&y, kx).unwrap_or(Value::Undefined);
                        if !dse(vm, vx, &vy, memo)? {
                            return Ok(false);
                        }
                        if let Some(p) = ey.iter().position(|(k2, _)| Value::same_value_zero(k2, kx)) {
                            used[p] = true;
                        }
                        continue;
                    }
                    if !kx.is_object() {
                        return Ok(false);
                    }
                    let mut found = false;
                    for (j, (ky, vy)) in ey.iter().enumerate() {
                        if used[j] || !ky.is_object() {
                            continue;
                        }
                        if dse(vm, kx, ky, memo)? && dse(vm, vx, vy, memo)? {
                            used[j] = true;
                            found = true;
                            break;
                        }
                    }
                    if !found {
                        return Ok(false);
                    }
                }
            }
            K::Set => {
                let ex = map_entries(&x);
                let ey = map_entries(&y);
                if ex.len() != ey.len() {
                    return Ok(false);
                }
                let mut used = vec![false; ey.len()];
                let mut pending = Vec::new();
                for (vx, _) in &ex {
                    if map_has(&y, vx) {
                        if let Some(p) = ey.iter().position(|(k2, _)| Value::same_value_zero(k2, vx)) {
                            used[p] = true;
                        }
                    } else if vx.is_object() {
                        pending.push(vx.clone());
                    } else {
                        return Ok(false);
                    }
                }
                for vx in pending {
                    let mut found = false;
                    for (j, (vy, _)) in ey.iter().enumerate() {
                        if used[j] || !vy.is_object() {
                            continue;
                        }
                        if dse(vm, &vx, vy, memo)? {
                            used[j] = true;
                            found = true;
                            break;
                        }
                    }
                    if !found {
                        return Ok(false);
                    }
                }
            }
            _ => {}
        }
        let kx = own_enum_keys_all(vm, &x)?;
        let ky = own_enum_keys_all(vm, &y)?;
        if kx.len() != ky.len() {
            return Ok(false);
        }
        for k in &kx {
            if !vm.has_own_property(&y, k)? {
                return Ok(false);
            }
            let vx = vm.get(&x, k, a)?;
            let vy = vm.get(&y, k, b)?;
            if !dse(vm, &vx, &vy, memo)? {
                return Ok(false);
            }
        }
        Ok(true)
    })();
    memo.pop();
    r
}

/// assert.partialDeepStrictEqual: every own enumerable key of `expected` must be present (`in`)
/// on `actual` with a partially-equal value; non-objects compare with Object.is.
fn partial_deq(vm: &mut Vm, actual: &Value, expected: &Value) -> JsResult<bool> {
    let mut memo = Vec::new();
    partial_inner(vm, actual, expected, &mut memo)
}

fn partial_inner(vm: &mut Vm, actual: &Value, expected: &Value, memo: &mut Vec<(Obj, Obj)>) -> JsResult<bool> {
    let (x, y) = match (actual, expected) {
        (Value::Obj(x), Value::Obj(y)) if !x.is_callable() && !y.is_callable() => (x.clone(), y.clone()),
        _ => return Ok(Value::same_value(actual, expected)),
    };
    if memo.iter().any(|(p, q)| p.ptr_eq(&x) && q.ptr_eq(&y)) {
        return Ok(true);
    }
    memo.push((x.clone(), y.clone()));
    let r = (|| -> JsResult<bool> {
        for k in vm.enumerable_own_keys(&y)? {
            let pk = PropKey::Str(k);
            if !vm.has_property(&x, &pk)? {
                return Ok(false);
            }
            let vx = vm.get(&x, &pk, actual)?;
            let vy = vm.get(&y, &pk, expected)?;
            if !partial_inner(vm, &vx, &vy, memo)? {
                return Ok(false);
            }
        }
        Ok(true)
    })();
    memo.pop();
    r
}

// ============================================================================================
// node:assert
// ============================================================================================

thread_local! {
    static AE_PROTO: std::cell::RefCell<Option<Obj>> = const { std::cell::RefCell::new(None) };
}

fn ae_proto(vm: &mut Vm) -> Obj {
    AE_PROTO.with(|p| p.borrow().clone()).unwrap_or_else(|| vm.intr.error_proto.clone())
}

/// Build an AssertionError the way `new AssertionError({message, actual, expected, operator})`
/// does; `frames` are the native frames shown before the JS call stack.
fn new_assertion_error(vm: &mut Vm, message: &Value, actual: Value, expected: Value, operator: Value, frames: &[&str], proto: Option<Obj>) -> JsResult<Value> {
    let proto = match proto {
        Some(p) => p,
        None => ae_proto(vm),
    };
    let msg = if message.truthy() { message.clone() } else { Value::str("Assertion failed") };
    let ms = vm.to_string(&msg)?;
    let o = Obj::with_class(Some(proto), ObjKind::Error, "Error");
    o.set_prop(vm.intr.key_message.clone(), Value::Str(ms), WC);
    o.set_prop(key("name"), Value::str("AssertionError"), WEC);
    o.set_prop(key("code"), Value::str("ERR_ASSERTION"), WEC);
    o.set_prop(key("actual"), actual, WEC);
    o.set_prop(key("expected"), expected, WEC);
    o.set_prop(key("operator"), operator, WEC);
    let mut s = String::new();
    for f in frames {
        s.push_str("\n    at ");
        s.push_str(f);
    }
    s.push_str(&vm.frames_string());
    o.borrow_mut().props.insert(PropKey::Sym(vm.intr.stack_sym.clone()), Prop::Data { value: Value::str(&s), flags: WC });
    Ok(Value::Obj(o))
}

/// Throw an AssertionError raised by assert function `fname`.
fn ae_fail<T>(vm: &mut Vm, message: &Value, actual: Value, expected: Value, op: &str, frames: &[&str]) -> JsResult<T> {
    let e = new_assertion_error(vm, message, actual, expected, Value::str(op), frames, None)?;
    Err(e)
}

fn or_default(m: &Value, d: &str) -> Value {
    if m.truthy() {
        m.clone()
    } else {
        Value::str(d)
    }
}

fn assertion_error_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return class_call_error(vm);
    }
    let opts = a.arg(0);
    if opts.is_null() {
        return vm.throw_type("cannot read property 'message' of null");
    }
    let get = |vm: &mut Vm, n: &str| -> JsResult<Value> {
        if opts.is_undefined() {
            Ok(Value::Undefined)
        } else {
            vm.get_prop_of(&opts, &key(n))
        }
    };
    let message = get(vm, "message")?;
    let actual = get(vm, "actual")?;
    let expected = get(vm, "expected")?;
    let operator = get(vm, "operator")?;
    let fallback = ae_proto(vm);
    let proto = vm.proto_from_nt(&a.new_target, &fallback)?;
    new_assertion_error(vm, &message, actual, expected, operator, &["AssertionError"], Some(proto))
}

fn assert_ok(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = a.arg(0);
    if v.truthy() {
        return Ok(Value::Undefined);
    }
    let m = or_default(&a.arg(1), "The expression evaluated to a falsy value:");
    ae_fail(vm, &m, v, Value::Bool(true), "==", &["AssertionError", "assert"])
}

fn assert_cmp(vm: &mut Vm, a: &Args, which: &str) -> JsResult<Value> {
    let x = a.arg(0);
    let y = a.arg(1);
    let (ok, op) = match which {
        "equal" => (vm.loose_eq(&x, &y)?, "=="),
        "notEqual" => (!vm.loose_eq(&x, &y)?, "!="),
        "strictEqual" => (Value::same_value(&x, &y), "strictEqual"),
        "notStrictEqual" => (!Value::same_value(&x, &y), "notStrictEqual"),
        "deepEqual" => (deep_equal(vm, &x, &y, false)?, "deepEqual"),
        "notDeepEqual" => (!deep_equal(vm, &x, &y, false)?, "notDeepEqual"),
        "deepStrictEqual" => (deep_equal(vm, &x, &y, true)?, "deepStrictEqual"),
        "notDeepStrictEqual" => (!deep_equal(vm, &x, &y, true)?, "notDeepStrictEqual"),
        _ => (partial_deq(vm, &x, &y)?, "partialDeepStrictEqual"),
    };
    if ok {
        return Ok(Value::Undefined);
    }
    let m = or_default(&a.arg(2), "Assertion failed");
    ae_fail(vm, &m, x, y, op, &["AssertionError", which])
}

fn assert_fail(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    fail_impl(vm, &a.arg(0), &["AssertionError", "fail"])
}

fn fail_impl(vm: &mut Vm, m: &Value, frames: &[&str]) -> JsResult<Value> {
    if is_error_instance(vm, m)? {
        return Err(m.clone());
    }
    let msg = match m {
        Value::Str(_) => m.clone(),
        _ => Value::str("Failed"),
    };
    ae_fail(vm, &msg, Value::Undefined, Value::Undefined, "fail", frames)
}

/// "Missing expected exception/rejection" message selection of throws()/rejects().
fn missing_message(vm: &mut Vm, expected: &Value, message: &Value, dflt: &str) -> JsResult<Value> {
    let m = if matches!(expected, Value::Str(_)) { expected.clone() } else { message.clone() };
    if !m.truthy() || is_error_instance(vm, &m)? {
        return Ok(Value::str(dflt));
    }
    Ok(match m {
        Value::Str(_) => m,
        _ => Value::str("Failed"),
    })
}

/// Does thrown value `e` satisfy `expected` (class, validation function, RegExp or object)?
fn check_expected(vm: &mut Vm, e: &Value, expected: &Value) -> JsResult<bool> {
    match expected {
        Value::Undefined | Value::Null | Value::Str(_) => Ok(true),
        Value::Obj(o) if o.is_callable() => {
            let proto = vm.get(o, &vm.intr.key_prototype.clone(), expected)?;
            if proto.is_object() && vm.instance_of(e, expected)? {
                return Ok(true);
            }
            if let Value::Obj(po) = &proto {
                let ep = vm.intr.error_proto.clone();
                if po.ptr_eq(&ep) || proto_chain_has(vm, &proto, &ep)? {
                    return Ok(false);
                }
            }
            let r = vm.call(expected, Value::Undefined, &[e.clone()])?;
            Ok(matches!(r, Value::Bool(true)))
        }
        Value::Obj(o) => {
            let re_proto = vm.intr.regexp_proto.clone();
            if proto_chain_has(vm, expected, &re_proto)? {
                let subject = match e {
                    Value::Undefined | Value::Null => e.clone(),
                    _ => {
                        let m = vm.get_prop_of(e, &vm.intr.key_message.clone())?;
                        if m.is_nullish() {
                            e.clone()
                        } else {
                            m
                        }
                    }
                };
                let r = call_method(vm, expected, "test", &[subject])?;
                return Ok(r.truthy());
            }
            let keys = vm.enumerable_own_keys(o)?;
            for k in keys {
                let pk = PropKey::Str(k);
                let ev = vm.get_prop_of(e, &pk)?;
                let xv = vm.get(o, &pk, expected)?;
                if !deep_equal(vm, &ev, &xv, true)? {
                    return Ok(false);
                }
            }
            Ok(true)
        }
        _ => Ok(false),
    }
}

fn call_fn_arg(vm: &mut Vm, f: &Value) -> JsResult<Value> {
    if !f.is_callable() {
        return vm.throw_type("fn is not a function");
    }
    vm.call(f, Value::Undefined, &[])
}

fn assert_throws(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let expected = a.arg(1);
    match call_fn_arg(vm, &a.arg(0)) {
        Ok(_) => {
            let m = missing_message(vm, &expected, &a.arg(2), "Missing expected exception.")?;
            fail_impl(vm, &m, &["AssertionError", "fail", "throws"])
        }
        Err(e) => {
            if !check_expected(vm, &e, &expected)? {
                let m = Value::str("The error did not match the expected criteria.");
                return ae_fail(vm, &m, e, expected, "throws", &["AssertionError", "throws"]);
            }
            Ok(Value::Undefined)
        }
    }
}

fn unwanted(vm: &mut Vm, e: Value, expected: &Value, message: &Value, what: &str, op: &str, frames: &[&str]) -> JsResult<Value> {
    let (exp, msg) = if matches!(expected, Value::Str(_)) { (Value::Undefined, expected.clone()) } else { (expected.clone(), message.clone()) };
    if !exp.is_nullish() && !check_expected(vm, &e, &exp)? {
        return Err(e);
    }
    let mut text = format!("Got unwanted {}.", what);
    if msg.truthy() {
        text.push(' ');
        text.push_str(&vm.to_string(&msg)?.to_rust_string());
    }
    ae_fail(vm, &Value::str(&text), e, Value::Undefined, op, frames)
}

fn assert_does_not_throw(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match call_fn_arg(vm, &a.arg(0)) {
        Ok(_) => Ok(Value::Undefined),
        Err(e) => unwanted(vm, e, &a.arg(1), &a.arg(2), "exception", "doesNotThrow", &["AssertionError", "doesNotThrow"]),
    }
}

/// rejects / doesNotReject: settle the returned promise from the awaited value.
fn assert_async(vm: &mut Vm, a: &Args, rejects: bool) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let data = Value::Obj(vm.new_array(vec![cap.resolve.clone(), cap.reject.clone(), a.arg(1), a.arg(2), Value::Bool(rejects)]));
    let target = a.arg(0);
    let awaited = if target.is_callable() {
        match vm.call(&target, Value::Undefined, &[]) {
            Ok(v) => v,
            Err(e) => {
                async_settle(vm, &data, Err(e), true);
                return Ok(cap.promise);
            }
        }
    } else {
        target
    };
    let p = match crate::builtins::promise::promise_resolve_intrinsic(vm, awaited) {
        Ok(p) => p,
        Err(e) => {
            async_settle(vm, &data, Err(e), true);
            return Ok(cap.promise);
        }
    };
    crate::builtins::promise::perform_then_internal(vm, &p, Handler::Native(async_on_ok, data.clone()), Handler::Native(async_on_err, data), None);
    Ok(cap.promise)
}

fn async_on_ok(vm: &mut Vm, v: Value, data: &Value) -> JsResult<Value> {
    async_settle(vm, data, Ok(v), false);
    Ok(Value::Undefined)
}

fn async_on_err(vm: &mut Vm, e: Value, data: &Value) -> JsResult<Value> {
    async_settle(vm, data, Err(e), false);
    Ok(Value::Undefined)
}

fn async_settle(vm: &mut Vm, data: &Value, outcome: Result<Value, Value>, sync: bool) {
    let part = |vm: &mut Vm, i: u32| vm.get_prop_of(data, &PropKey::from_index(i)).unwrap_or(Value::Undefined);
    let resolve = part(vm, 0);
    let reject = part(vm, 1);
    let expected = part(vm, 2);
    let message = part(vm, 3);
    let rejects = part(vm, 4).truthy();
    let result: JsResult<Value> = (|| {
        if rejects {
            match outcome {
                Ok(_) => {
                    let m = missing_message(vm, &expected, &message, "Missing expected rejection.")?;
                    let frames: &[&str] = if sync { &["AssertionError", "fail", "rejects"] } else { &["AssertionError", "fail"] };
                    fail_impl(vm, &m, frames)
                }
                Err(e) => {
                    if !check_expected(vm, &e, &expected)? {
                        let m = Value::str("The error did not match the expected criteria.");
                        let frames: &[&str] = if sync { &["AssertionError", "rejects"] } else { &["AssertionError"] };
                        return ae_fail(vm, &m, e, expected.clone(), "rejects", frames);
                    }
                    Ok(Value::Undefined)
                }
            }
        } else {
            match outcome {
                Ok(_) => Ok(Value::Undefined),
                Err(e) => {
                    let frames: &[&str] = if sync { &["AssertionError", "doesNotReject"] } else { &["AssertionError"] };
                    unwanted(vm, e, &expected, &message, "rejection", "doesNotReject", frames)
                }
            }
        }
    })();
    let _ = match result {
        Ok(_) => vm.call(&resolve, Value::Undefined, &[Value::Undefined]),
        Err(e) => vm.call(&reject, Value::Undefined, &[e]),
    };
}

fn assert_match(vm: &mut Vm, a: &Args, want: bool) -> JsResult<Value> {
    let s = a.arg(0);
    let re = a.arg(1);
    let r = call_method(vm, &re, "test", &[s.clone()])?.truthy();
    if r == want {
        return Ok(Value::Undefined);
    }
    let m = or_default(&a.arg(2), "Assertion failed");
    let name = if want { "match" } else { "doesNotMatch" };
    ae_fail(vm, &m, s, re, name, &["AssertionError", name])
}

fn assert_if_error(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = a.arg(0);
    if v.is_nullish() {
        return Ok(Value::Undefined);
    }
    let m = vm.get_prop_of(&v, &vm.intr.key_message.clone())?;
    let shown = if m.truthy() { m } else { v.clone() };
    let text = format!("ifError got unwanted exception: {}", vm.to_string(&shown)?.to_rust_string());
    ae_fail(vm, &Value::str(&text), v, Value::Null, "ifError", &["AssertionError", "ifError"])
}

// ---------------- CallTracker ----------------

fn call_tracker_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return class_call_error(vm);
    }
    let fallback = vm.intr.object_proto.clone();
    let proto = vm.proto_from_nt(&a.new_target, &fallback)?;
    let o = Obj::new(Some(proto), ObjKind::Ordinary);
    let recs = vm.new_array(Vec::new());
    o.set_prop(key("_records"), Value::Obj(recs), WEC);
    Ok(Value::Obj(o))
}

fn tracker_records(vm: &mut Vm, this: &Value) -> JsResult<Obj> {
    match vm.get_prop_of(this, &key("_records"))? {
        Value::Obj(o) => Ok(o),
        _ => vm.throw_type("cannot read property 'push' of undefined"),
    }
}

fn tracker_calls(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let recs = tracker_records(vm, &a.this)?;
    let f = if a.arg(0).is_undefined() { Value::Obj(vm.native_fn("", 0, |_vm, _a| Ok(Value::Undefined))) } else { a.arg(0) };
    let exact = if a.arg(1).is_undefined() { Value::Num(1.0) } else { a.arg(1) };
    let rec = vm.obj_from(vec![("fn", f), ("exact", exact), ("actual", Value::Num(0.0))]);
    crate::vm::array_push_raw(&recs, Value::Obj(rec.clone()));
    Ok(Value::Obj(plain_fn(vm, "", 0, tracked_call, vec![Value::Obj(rec)])))
}

fn tracked_call(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let rec = a.slot(0);
    if let Value::Obj(r) = &rec {
        let n = match r.get_own_str("actual") {
            Some(Value::Num(n)) => n,
            _ => 0.0,
        };
        r.set_str("actual", Value::Num(n + 1.0), WEC);
        let f = r.get_own_str("fn").unwrap_or(Value::Undefined);
        return vm.call(&f, a.this.clone(), a.args);
    }
    Ok(Value::Undefined)
}

fn tracker_failures(vm: &mut Vm, this: &Value) -> JsResult<Vec<(String, Value, Value, String)>> {
    let recs = tracker_records(vm, this)?;
    let list = crate::builtins::array::array_like_to_vec(vm, &Value::Obj(recs))?;
    let mut out = Vec::new();
    for r in list {
        let actual = vm.get_prop_of(&r, &key("actual"))?;
        let exact = vm.get_prop_of(&r, &key("exact"))?;
        if Value::strict_eq(&actual, &exact) {
            continue;
        }
        let f = vm.get_prop_of(&r, &key("fn"))?;
        let name = vm.get_prop_of(&f, &vm.intr.key_name.clone())?;
        let n = if name.truthy() { string_of(vm, &name)?.to_rust_string() } else { "<anonymous>".to_string() };
        let msg = format!(
            "Expected the {} function to be executed {} time(s) but was executed {} time(s).",
            n,
            string_of(vm, &exact)?.to_rust_string(),
            string_of(vm, &actual)?.to_rust_string()
        );
        out.push((msg, actual, exact, n));
    }
    Ok(out)
}

fn tracker_report(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let fails = tracker_failures(vm, &a.this)?;
    let mut items = Vec::new();
    for (msg, actual, exact, n) in fails {
        let stack = vm.new_object();
        let o = vm.obj_from(vec![
            ("message", Value::str(&msg)),
            ("actual", actual),
            ("expected", exact),
            ("operator", Value::str(&n)),
            ("stack", Value::Obj(stack)),
        ]);
        items.push(Value::Obj(o));
    }
    Ok(Value::Obj(vm.new_array(items)))
}

fn tracker_verify(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let fails = tracker_failures(vm, &a.this)?;
    if fails.is_empty() {
        return Ok(Value::Undefined);
    }
    let msg: Vec<String> = fails.into_iter().map(|f| f.0).collect();
    ae_fail(vm, &Value::str(&msg.join("\n")), Value::Undefined, Value::Undefined, "verify", &["AssertionError", "verify"])
}

fn tracker_reset(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let recs = tracker_records(vm, &a.this)?;
    if a.arg(0).is_undefined() {
        let empty = vm.new_array(Vec::new());
        if let Value::Obj(t) = &a.this {
            t.set_prop(key("_records"), Value::Obj(empty), WEC);
        }
        return Ok(Value::Undefined);
    }
    let list = crate::builtins::array::array_like_to_vec(vm, &Value::Obj(recs))?;
    for r in list {
        if let Value::Obj(ro) = &r {
            ro.set_str("actual", Value::Num(0.0), WEC);
        }
    }
    Ok(Value::Undefined)
}

// ---------------- module assembly ----------------

fn build_assert(vm: &mut Vm) -> Obj {
    let (aec, aep) = make_class(vm, "AssertionError", 0, assertion_error_ctor, Some(vm.intr.error_proto.clone()));
    if let Some(Value::Obj(ector)) = vm.global.get_own_str("Error") {
        aec.borrow_mut().proto = Some(ector);
    }
    AE_PROTO.with(|p| *p.borrow_mut() = Some(aep));
    let (ctc, ctp) = make_class(vm, "CallTracker", 0, call_tracker_ctor, None);
    vm.def_method(&ctp, "calls", 0, tracker_calls);
    vm.def_method(&ctp, "report", 0, tracker_report);
    vm.def_method(&ctp, "getCalls", 1, |vm, _a| Ok(Value::Obj(vm.new_array(Vec::new()))));
    vm.def_method(&ctp, "verify", 0, tracker_verify);
    vm.def_method(&ctp, "reset", 1, tracker_reset);

    let assert = plain_fn(vm, "assert", 2, assert_ok, Vec::new());
    let strict = plain_fn(vm, "strict", 2, assert_ok, Vec::new());
    let mk = |vm: &mut Vm, name: &str, len: u32, f: NativeFn| -> Value { Value::Obj(vm.native_fn(name, len, f)) };
    let fail = mk(vm, "fail", 1, assert_fail);
    let strict_equal = mk(vm, "strictEqual", 3, |vm, a| assert_cmp(vm, a, "strictEqual"));
    let not_strict_equal = mk(vm, "notStrictEqual", 3, |vm, a| assert_cmp(vm, a, "notStrictEqual"));
    let equal = mk(vm, "equal", 3, |vm, a| assert_cmp(vm, a, "equal"));
    let not_equal = mk(vm, "notEqual", 3, |vm, a| assert_cmp(vm, a, "notEqual"));
    let deep_eq = mk(vm, "deepEqual", 3, |vm, a| assert_cmp(vm, a, "deepEqual"));
    let not_deep_eq = mk(vm, "notDeepEqual", 3, |vm, a| assert_cmp(vm, a, "notDeepEqual"));
    let deep_strict = mk(vm, "deepStrictEqual", 3, |vm, a| assert_cmp(vm, a, "deepStrictEqual"));
    let not_deep_strict = mk(vm, "notDeepStrictEqual", 3, |vm, a| assert_cmp(vm, a, "notDeepStrictEqual"));
    let partial = mk(vm, "partialDeepStrictEqual", 3, |vm, a| assert_cmp(vm, a, "partialDeepStrictEqual"));
    let match_f = mk(vm, "match", 3, |vm, a| assert_match(vm, a, true));
    let not_match = mk(vm, "doesNotMatch", 3, |vm, a| assert_match(vm, a, false));
    let throws = Value::Obj(plain_fn(vm, "throws", 3, assert_throws, Vec::new()));
    let not_throw = Value::Obj(plain_fn(vm, "doesNotThrow", 3, assert_does_not_throw, Vec::new()));
    let rejects = mk(vm, "rejects", 3, |vm, a| assert_async(vm, a, true));
    let not_reject = mk(vm, "doesNotReject", 3, |vm, a| assert_async(vm, a, false));
    let if_error = mk(vm, "ifError", 1, assert_if_error);
    for (target, loose) in [(&assert, true), (&strict, false)] {
        let pick = |l: &Value, s: &Value| if loose { l.clone() } else { s.clone() };
        let entries: Vec<(&str, Value)> = vec![
            ("ok", Value::Obj(target.clone())),
            ("fail", fail.clone()),
            ("strictEqual", strict_equal.clone()),
            ("notStrictEqual", not_strict_equal.clone()),
            ("equal", pick(&equal, &strict_equal)),
            ("notEqual", pick(&not_equal, &not_strict_equal)),
            ("deepEqual", pick(&deep_eq, &deep_strict)),
            ("notDeepEqual", pick(&not_deep_eq, &not_deep_strict)),
            ("deepStrictEqual", deep_strict.clone()),
            ("notDeepStrictEqual", not_deep_strict.clone()),
            ("partialDeepStrictEqual", partial.clone()),
            ("match", match_f.clone()),
            ("doesNotMatch", not_match.clone()),
            ("throws", throws.clone()),
            ("doesNotThrow", not_throw.clone()),
            ("rejects", rejects.clone()),
            ("doesNotReject", not_reject.clone()),
            ("ifError", if_error.clone()),
            ("AssertionError", Value::Obj(aec.clone())),
            ("CallTracker", Value::Obj(ctc.clone())),
            ("strict", Value::Obj(strict.clone())),
        ];
        for (n, v) in entries {
            target.set_prop(key(n), v, WEC);
        }
    }
    assert
}

/// The assert module object for `name` ("assert" or "assert/strict"); both share one build.
pub fn create_assert_module_named(vm: &mut Vm, name: &str) -> Value {
    let main = match vm.host.builtin_cache.get("assert") {
        Some(v) => v.clone(),
        None => {
            let m = Value::Obj(build_assert(vm));
            vm.host.builtin_cache.insert("assert".into(), m.clone());
            m
        }
    };
    if name == "assert/strict" {
        if let Value::Obj(m) = &main {
            if let Some(s) = m.get_own_str("strict") {
                return s;
            }
        }
    }
    main
}

#[allow(dead_code)]
pub fn create_assert_module(vm: &mut Vm) -> Value {
    create_assert_module_named(vm, "assert")
}

/// AssertionError used by other modules.
#[allow(dead_code)]
pub fn make_assertion_error(vm: &mut Vm, msg: &str, actual: Value, expected: Value, op: &str) -> Value {
    match new_assertion_error(vm, &Value::str(msg), actual, expected, Value::str(op), &["AssertionError"], None) {
        Ok(v) => v,
        Err(e) => e,
    }
}

// ============================================================================================
// async_hooks
// ============================================================================================

pub fn create_async_hooks_module(vm: &mut Vm) -> Value {
    let o = vm.new_object();
    let proto = vm.new_object();
    let ctor = vm.native_ctor("AsyncLocalStorage", 0, als_ctor, &proto);
    vm.def_method(&proto, "getStore", 0, |vm, a| match &a.this {
        Value::Obj(o) => vm.get_str(o, "__store"),
        _ => Ok(Value::Undefined),
    });
    vm.def_method(&proto, "run", 2, als_run);
    vm.def_method(&proto, "enterWith", 1, |_vm, a| {
        if let Value::Obj(o) = &a.this {
            o.set_prop(PropKey::from_str("__store"), a.arg(0), WC);
        }
        Ok(Value::Undefined)
    });
    vm.def_method(&proto, "exit", 1, |vm, a| {
        let rest = if a.args.len() > 1 { &a.args[1..] } else { &[][..] };
        vm.call(&a.arg(0), Value::Undefined, rest)
    });
    vm.def_method(&proto, "disable", 0, |_vm, _a| Ok(Value::Undefined));
    o.set_str("AsyncLocalStorage", Value::Obj(ctor), WEC);
    vm.def_method(&o, "createHook", 1, |vm, _a| {
        let h = vm.new_object();
        vm.def_method(&h, "enable", 0, |_vm, a| Ok(a.this.clone()));
        vm.def_method(&h, "disable", 0, |_vm, a| Ok(a.this.clone()));
        Ok(Value::Obj(h))
    });
    vm.def_method(&o, "executionAsyncId", 0, |_vm, _a| Ok(Value::Num(1.0)));
    vm.def_method(&o, "triggerAsyncId", 0, |_vm, _a| Ok(Value::Num(0.0)));
    Value::Obj(o)
}

fn als_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let fallback = vm.get(a.callee, &vm.intr.key_prototype.clone(), &Value::Obj(a.callee.clone()))?.as_obj().cloned().unwrap();
    let p = vm.proto_from_nt(&a.new_target, &fallback)?;
    Ok(Value::Obj(Obj::new(Some(p), ObjKind::Ordinary)))
}

fn als_run(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("incompatible receiver"),
    };
    let prev = o.get_own_str("__store").unwrap_or(Value::Undefined);
    o.set_prop(PropKey::from_str("__store"), a.arg(0), WC);
    let rest = if a.args.len() > 2 { &a.args[2..] } else { &[][..] };
    let r = vm.call(&a.arg(1), Value::Undefined, rest);
    o.set_prop(PropKey::from_str("__store"), prev, WC);
    r
}

impl Vm {
    pub fn symbol_for(&mut self, key: &str) -> Sym {
        let k = JsStr::from_str(key);
        if let Some(s) = self.symbol_registry.get(&k) {
            return s.clone();
        }
        let s = Sym(std::rc::Rc::new(SymbolData { description: Some(k.clone()), registered: true, private: false }));
        self.symbol_registry.insert(k, s.clone());
        s
    }
}
