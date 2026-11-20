// Global functions: parseInt, eval, URI coding, etc.

use crate::object::*;
use crate::value::*;
use crate::vm::{Frame, JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let g = vm.global.clone();
    g.set_prop(PropKey::from_str("globalThis"), Value::Obj(g.clone()), WC);
    g.set_prop(PropKey::from_str("undefined"), Value::Undefined, 0);
    g.set_prop(PropKey::from_str("NaN"), Value::Num(f64::NAN), 0);
    g.set_prop(PropKey::from_str("Infinity"), Value::Num(f64::INFINITY), 0);
    let fns: &[(&str, u32, NativeFn)] = &[
        ("parseInt", 2, parse_int),
        ("parseFloat", 1, parse_float),
        ("isNaN", 1, is_nan),
        ("isFinite", 1, is_finite),
        ("escape", 1, escape),
        ("unescape", 1, unescape),
        ("encodeURIComponent", 1, encode_uri_component),
        ("encodeURI", 1, encode_uri),
        ("decodeURIComponent", 1, decode_uri_component),
        ("decodeURI", 1, decode_uri),
    ];
    for (n, l, f) in fns {
        vm.def_method(&g, n, *l, *f);
    }
    let ev = vm.def_method(&g, "eval", 1, indirect_eval);
    vm.intr.eval_fn = ev;
    crate::builtins::number::setup_number_parse_links(vm);
    setup_262(vm);
}

/// The test262 host object `$262`.
fn setup_262(vm: &mut Vm) {
    let g = vm.global.clone();
    let o = vm.new_object();
    o.set_prop(PropKey::from_str("global"), Value::Obj(g.clone()), WC);
    vm.def_method(&o, "gc", 0, h262_gc);
    let dda = vm.native_fn("IsHTMLDDA", 0, h262_is_html_dda);
    if let ObjKind::Native(n) = &mut dda.borrow_mut().kind {
        n.name = HTMLDDA_TAG;
    }
    o.set_prop(PropKey::from_str("IsHTMLDDA"), Value::Obj(dda), WC);
    vm.def_method(&o, "createRealm", 0, h262_create_realm);
    vm.def_method(&o, "evalScript", 1, h262_eval_script);
    vm.def_method(&o, "detachArrayBuffer", 1, h262_detach);
    let agent = vm.new_object();
    for (n, l) in [("start", 1), ("broadcast", 2), ("getReport", 0), ("sleep", 1), ("setTimeout", 2), ("monotonicNow", 0), ("receiveBroadcast", 1), ("report", 1), ("leaving", 0)] {
        let f: NativeFn = match n {
            "getReport" => h262_null,
            "sleep" => h262_sleep,
            "monotonicNow" => h262_now,
            _ => h262_gc,
        };
        vm.def_method(&agent, n, l, f);
    }
    o.set_prop(PropKey::from_str("agent"), Value::Obj(agent), WEC);
    let ams_proto = vm.new_object();
    let ams = vm.native_ctor("AbstractModuleSource", 0, h262_abstract_module_source, &ams_proto);
    o.set_prop(PropKey::from_str("AbstractModuleSource"), Value::Obj(ams), WC);
    g.set_prop(PropKey::from_str("$262"), Value::Obj(o), WC);
    setup_shadow_realm(vm);
}

// ---------------- ShadowRealm ----------------

struct ShadowRealmData {
    realm: u32,
}

fn setup_shadow_realm(vm: &mut Vm) {
    let proto = vm.new_object();
    let ctor = vm.native_ctor("ShadowRealm", 0, shadow_ctor, &proto);
    let ck = vm.intr.key_constructor.clone();
    let cprop = proto.borrow_mut().props.remove(&ck);
    vm.def_method(&proto, "evaluate", 1, shadow_evaluate);
    vm.def_method(&proto, "importValue", 2, shadow_import_value);
    if let Some(p) = cprop {
        proto.borrow_mut().props.insert(ck, p);
    }
    vm.set_tag(&proto, "ShadowRealm");
    vm.def_global("ShadowRealm", Value::Obj(ctor));
}

fn shadow_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return vm.throw_type("ShadowRealm constructor requires 'new'");
    }
    let fallback = match a.callee.get_own_data(&vm.intr.key_prototype.clone()) {
        Some(Value::Obj(p)) => p,
        _ => vm.intr.object_proto.clone(),
    };
    let proto = vm.proto_from_nt(&a.new_target, &fallback)?;
    let id = vm.create_realm();
    Ok(Value::Obj(Obj::with_class(Some(proto), ObjKind::Host(Box::new(ShadowRealmData { realm: id })), "ShadowRealm")))
}

fn shadow_realm_of(vm: &mut Vm, this: &Value, method: &str) -> JsResult<u32> {
    if let Value::Obj(o) = this {
        if let ObjKind::Host(h) = &o.borrow().kind {
            if let Some(d) = h.downcast_ref::<ShadowRealmData>() {
                return Ok(d.realm);
            }
        }
    }
    vm.throw_type(format!("ShadowRealm.prototype.{} called on a non-ShadowRealm", method))
}

/// GetWrappedValue: primitives pass, callables are wrapped (in the current realm), other
/// objects are rejected with `msg`.
fn get_wrapped_value(vm: &mut Vm, v: Value, msg: &str) -> JsResult<Value> {
    match &v {
        Value::Obj(o) => {
            if !o.is_callable() {
                return vm.throw_type(msg.to_string());
            }
            wrapped_function_create(vm, o, msg)
        }
        _ => Ok(v),
    }
}

/// a wrapped function exotic object for `target`, created in the current realm
fn wrapped_function_create(vm: &mut Vm, target: &Obj, msg: &str) -> JsResult<Value> {
    let f = vm.native_closure("", 0, wrapped_call, vec![Value::Obj(target.clone())]);
    if let ObjKind::Native(n) = &mut f.borrow_mut().kind {
        n.name = crate::builtins::function::WRAPPED_FN_TAG;
    }
    // CopyNameAndLength (failures surface as TypeErrors of the caller's realm)
    let r = (|| -> JsResult<(f64, JsStr)> {
        let mut len = 0.0;
        let lk = vm.intr.key_length.clone();
        if vm.has_own_property(target, &lk)? {
            if let Value::Num(n) = vm.get(target, &lk, &Value::Obj(target.clone()))? {
                len = if n == f64::INFINITY { n } else if n == f64::NEG_INFINITY { 0.0 } else { crate::ops::integer_or_infinity(n).max(0.0) };
            }
        }
        let name = match vm.get(target, &vm.intr.key_name.clone(), &Value::Obj(target.clone()))? {
            Value::Str(s) => s,
            _ => JsStr::empty(),
        };
        Ok((len, name))
    })();
    let (len, name) = match r {
        Ok(x) => x,
        Err(_) => return vm.throw_type(msg.to_string()),
    };
    {
        let mut b = f.borrow_mut();
        b.props.insert(vm.intr.key_length.clone(), Prop::Data { value: Value::Num(len), flags: CONFIGURABLE });
        b.props.insert(vm.intr.key_name.clone(), Prop::Data { value: Value::Str(name), flags: CONFIGURABLE });
    }
    Ok(Value::Obj(f))
}

/// [[Call]] of a wrapped function: arguments are wrapped into the target's realm, the result
/// back into the caller's realm.
fn wrapped_call(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let target = match a.slot(0) {
        Value::Obj(o) => o,
        _ => return Ok(Value::Undefined),
    };
    let caller = vm.intr.realm_id;
    let target_realm = vm.function_realm(&target)?;
    vm.switch_realm(target_realm);
    let wrapped = (|| -> JsResult<(Value, Vec<Value>)> {
        let msg = "ShadowRealm wrapped function: arguments must be primitives or callables";
        let this = get_wrapped_value(vm, a.this.clone(), msg)?;
        let mut args = Vec::new();
        for v in a.args {
            args.push(get_wrapped_value(vm, v.clone(), msg)?);
        }
        Ok((this, args))
    })();
    let (this, args) = match wrapped {
        Ok(x) => x,
        Err(e) => {
            vm.switch_realm(caller);
            return Err(e);
        }
    };
    let r = vm.call_obj(&target, this, &args);
    vm.switch_realm(caller);
    match r {
        Err(_) => vm.throw_type("a wrapped function threw inside the ShadowRealm"),
        Ok(v) => get_wrapped_value(vm, v, "a wrapped function returned a non-primitive"),
    }
}

fn shadow_evaluate(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let realm = shadow_realm_of(vm, &a.this, "evaluate")?;
    let src = match a.arg(0) {
        Value::Str(s) => s.to_rust_string(),
        _ => return vm.throw_type("ShadowRealm.prototype.evaluate expects a string"),
    };
    // syntax errors are reported in the caller's realm
    if let Err(e) = crate::parser::parse(&src, false) {
        return Err(vm.make_error("SyntaxError", &e.msg));
    }
    let caller = vm.intr.realm_id;
    vm.switch_realm(realm);
    let r = crate::loader::run_script_completion(vm, &src);
    vm.switch_realm(caller);
    match r {
        Ok(v) => get_wrapped_value(vm, v, "only primitives and callables may cross a ShadowRealm boundary"),
        Err(Ok(se)) => Err(vm.make_error("SyntaxError", &se.msg)),
        Err(Err(_)) => vm.throw_type("ShadowRealm evaluate: the provided source threw an error"),
    }
}

fn shadow_import_value(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let realm = shadow_realm_of(vm, &a.this, "importValue")?;
    let spec = vm.to_string(&a.arg(0))?;
    let name = match a.arg(1) {
        Value::Str(s) => s,
        _ => return vm.throw_type("ShadowRealm.prototype.importValue expects a string export name"),
    };
    let cap = vm.new_promise_capability_intrinsic();
    let caller = vm.intr.realm_id;
    vm.switch_realm(realm);
    let p = match crate::loader::compile_program("", crate::resolver::ScopeKind::Script, None, false) {
        Ok(code) => {
            let dummy = Frame::new(code, None, Value::Undefined, None, Value::Undefined, Vec::new(), None);
            crate::modules::dynamic_import(vm, &dummy, Value::Str(spec))
        }
        Err(_) => Value::Undefined,
    };
    vm.switch_realm(caller);
    if let Value::Obj(po) = p {
        let data = Value::Obj(vm.new_array(vec![Value::Str(name), cap.resolve.clone(), cap.reject.clone()]));
        crate::builtins::promise::perform_then_internal(vm, &po, Handler::Native(import_value_fulfilled, data.clone()), Handler::Native(import_value_rejected, data), None);
    }
    Ok(cap.promise)
}

fn import_value_parts(d: &Value) -> (Value, Value, Value) {
    let o = d.as_obj().unwrap();
    let b = o.borrow();
    match &b.kind {
        ObjKind::Array(a) => (a.dense[0].clone(), a.dense[1].clone(), a.dense[2].clone()),
        _ => (Value::Undefined, Value::Undefined, Value::Undefined),
    }
}

fn import_value_fulfilled(vm: &mut Vm, ns: Value, d: &Value) -> JsResult<Value> {
    let (name, resolve, reject) = import_value_parts(d);
    let r = (|| -> JsResult<Value> {
        let key = vm.to_property_key(&name)?;
        let nso = match &ns {
            Value::Obj(o) => o.clone(),
            _ => return vm.throw_type("module namespace expected"),
        };
        if !vm.has_property(&nso, &key)? {
            let n = match &name {
                Value::Str(s) => s.to_rust_string(),
                _ => String::new(),
            };
            return vm.throw_type(format!("importValue: no export named '{}'", n));
        }
        let v = vm.get(&nso, &key, &ns)?;
        get_wrapped_value(vm, v, "only primitives and callables may cross a ShadowRealm boundary")
    })();
    match r {
        Ok(v) => vm.call(&resolve, Value::Undefined, &[v])?,
        Err(e) => vm.call(&reject, Value::Undefined, &[e])?,
    };
    Ok(Value::Undefined)
}

fn import_value_rejected(vm: &mut Vm, e: Value, d: &Value) -> JsResult<Value> {
    let (_, _, reject) = import_value_parts(d);
    // (the error is converted to a TypeError of the caller's realm)
    let msg = match &e {
        Value::Obj(o) => match o.get_own_data(&vm.intr.key_message.clone()) {
            Some(Value::Str(s)) => s.to_rust_string(),
            _ => String::new(),
        },
        _ => String::new(),
    };
    let msg = match msg.find(" (imported from") {
        Some(i) => msg[..i].to_string(),
        None => msg,
    };
    let te = vm.make_error("TypeError", &msg);
    vm.call(&reject, Value::Undefined, &[te])?;
    Ok(Value::Undefined)
}

fn h262_gc(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Undefined)
}

fn h262_null(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Null)
}

fn h262_is_html_dda(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Null)
}

fn h262_create_realm(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let id = vm.create_realm();
    let g = match vm.realm_global(id) {
        Some(g) => g,
        None => return vm.throw_type("createRealm failed"),
    };
    Ok(g.get_own_data(&PropKey::from_str("$262")).unwrap_or(Value::Undefined))
}

fn h262_eval_script(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let src = vm.to_string(&a.arg(0))?.to_rust_string();
    match crate::loader::run_script_completion(vm, &src) {
        Ok(v) => Ok(v),
        Err(Ok(se)) => Err(crate::loader::syntax_error_value(vm, &se)),
        Err(Err(e)) => Err(e),
    }
}

fn h262_detach(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let Value::Obj(o) = a.arg(0) {
        let shared = matches!(&o.borrow().kind, ObjKind::ArrayBuffer(b) if b.borrow().shared);
        if !shared {
            crate::builtins::typedarray::detach_buffer(&o);
        }
    }
    Ok(Value::Undefined)
}

fn h262_sleep(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ms = vm.to_number(&a.arg(0))?;
    if ms > 0.0 && ms.is_finite() {
        std::thread::sleep(std::time::Duration::from_millis(ms as u64));
    }
    Ok(Value::Undefined)
}

fn h262_now(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    thread_local! {
        static START: std::time::Instant = std::time::Instant::now();
    }
    Ok(Value::Num(START.with(|s| s.elapsed().as_secs_f64() * 1000.0)))
}

fn h262_abstract_module_source(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    vm.throw_type("Abstract class AbstractModuleSource not directly constructable")
}

fn parse_int(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    let r = vm.to_int32(&a.arg(1))?;
    Ok(Value::Num(crate::numconv::parse_int(s.units(), r)))
}

fn parse_float(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    Ok(Value::Num(crate::numconv::parse_float(s.units())))
}

fn is_nan(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(vm.to_number(&a.arg(0))?.is_nan()))
}

fn is_finite(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(vm.to_number(&a.arg(0))?.is_finite()))
}

fn indirect_eval(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match a.arg(0) {
        Value::Str(s) => crate::loader::indirect_eval(vm, &s),
        other => Ok(other),
    }
}

pub fn direct_eval(vm: &mut Vm, frame: &mut Frame, args: &[Value]) -> JsResult<Value> {
    match args.first() {
        Some(Value::Str(s)) => {
            let s = s.clone();
            crate::loader::direct_eval(vm, frame, &s)
        }
        Some(other) => Ok(other.clone()),
        None => Ok(Value::Undefined),
    }
}

const URI_RESERVED: &str = ";/?:@&=+$,";
const URI_UNESCAPED_EXTRA: &str = "-_.!~*'()";

fn encode(vm: &mut Vm, s: &JsStr, unescaped: &str) -> JsResult<Value> {
    let u = s.units();
    let mut out = String::new();
    let mut i = 0;
    while i < u.len() {
        let c = u[i];
        if c < 128 && ((c as u8).is_ascii_alphanumeric() || URI_UNESCAPED_EXTRA.contains(c as u8 as char) || unescaped.contains(c as u8 as char)) {
            out.push(c as u8 as char);
            i += 1;
            continue;
        }
        let cp: u32 = if (0xDC00..0xE000).contains(&c) {
            return vm.throw_error("URIError", "URI malformed");
        } else if (0xD800..0xDC00).contains(&c) {
            if i + 1 >= u.len() || !(0xDC00..0xE000).contains(&u[i + 1]) {
                return vm.throw_error("URIError", "URI malformed");
            }
            let cp = 0x10000 + (((c as u32) - 0xD800) << 10) + ((u[i + 1] as u32) - 0xDC00);
            i += 1;
            cp
        } else {
            c as u32
        };
        let ch = char::from_u32(cp).unwrap();
        let mut buf = [0u8; 4];
        for b in ch.encode_utf8(&mut buf).bytes() {
            out.push_str(&format!("%{:02X}", b));
        }
        i += 1;
    }
    Ok(Value::str(&out))
}

fn encode_uri_component(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    encode(vm, &s, "")
}

fn encode_uri(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    encode(vm, &s, ";/?:@&=+$,#")
}

fn hexval(c: u16) -> Option<u8> {
    match c {
        0x30..=0x39 => Some((c - 0x30) as u8),
        0x41..=0x46 => Some((c - 0x41 + 10) as u8),
        0x61..=0x66 => Some((c - 0x61 + 10) as u8),
        _ => None,
    }
}

fn decode(vm: &mut Vm, s: &JsStr, reserved: &str) -> JsResult<Value> {
    let u = s.units();
    let mut out: Vec<u16> = Vec::new();
    let mut i = 0;
    while i < u.len() {
        let c = u[i];
        if c != b'%' as u16 {
            out.push(c);
            i += 1;
            continue;
        }
        let start = i;
        if i + 2 >= u.len() {
            return vm.throw_error("URIError", "URI malformed");
        }
        let b = match (hexval(u[i + 1]), hexval(u[i + 2])) {
            (Some(h), Some(l)) => h * 16 + l,
            _ => return vm.throw_error("URIError", "URI malformed"),
        };
        i += 3;
        if b < 0x80 {
            if reserved.contains(b as char) {
                out.extend_from_slice(&u[start..i]);
            } else {
                out.push(b as u16);
            }
            continue;
        }
        let n = if b & 0xE0 == 0xC0 {
            2
        } else if b & 0xF0 == 0xE0 {
            3
        } else if b & 0xF8 == 0xF0 {
            4
        } else {
            return vm.throw_error("URIError", "URI malformed");
        };
        let mut bytes = vec![b];
        for _ in 1..n {
            if i + 2 >= u.len() || u[i] != b'%' as u16 {
                return vm.throw_error("URIError", "URI malformed");
            }
            let bb = match (hexval(u[i + 1]), hexval(u[i + 2])) {
                (Some(h), Some(l)) => h * 16 + l,
                _ => return vm.throw_error("URIError", "URI malformed"),
            };
            if bb & 0xC0 != 0x80 {
                return vm.throw_error("URIError", "URI malformed");
            }
            bytes.push(bb);
            i += 3;
        }
        match std::str::from_utf8(&bytes) {
            Ok(st) => {
                for ch in st.chars() {
                    let mut buf = [0u16; 2];
                    out.extend_from_slice(ch.encode_utf16(&mut buf));
                }
            }
            Err(_) => return vm.throw_error("URIError", "URI malformed"),
        }
    }
    Ok(Value::Str(JsStr::from_units(out)))
}

fn decode_uri_component(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    decode(vm, &s, "")
}

fn decode_uri(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    decode(vm, &s, ";/?:@&=+$,#")
}

fn escape(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    let mut out = String::new();
    for &c in s.units() {
        if c < 128 && ((c as u8).is_ascii_alphanumeric() || "@*_+-./".contains(c as u8 as char)) {
            out.push(c as u8 as char);
        } else if c < 256 {
            out.push_str(&format!("%{:02X}", c));
        } else {
            out.push_str(&format!("%u{:04X}", c));
        }
    }
    let _ = URI_RESERVED;
    Ok(Value::str(&out))
}

fn unescape(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    let u = s.units();
    let mut out = Vec::new();
    let mut i = 0;
    while i < u.len() {
        let c = u[i];
        if c == b'%' as u16 {
            if i + 6 <= u.len() && u[i + 1] == b'u' as u16 {
                let h: Option<Vec<u8>> = u[i + 2..i + 6].iter().map(|&x| hexval(x)).collect();
                if let Some(h) = h {
                    out.push(((h[0] as u16) << 12) | ((h[1] as u16) << 8) | ((h[2] as u16) << 4) | h[3] as u16);
                    i += 6;
                    continue;
                }
            }
            if i + 3 <= u.len() {
                if let (Some(h), Some(l)) = (hexval(u[i + 1]), hexval(u[i + 2])) {
                    out.push((h * 16 + l) as u16);
                    i += 3;
                    continue;
                }
            }
        }
        // the reference engine copies other characters as code points truncated to 16 bits;
        // lone surrogates come out shifted by 0x2000
        if (0xD800..0xDC00).contains(&c) && i + 1 < u.len() && (0xDC00..0xE000).contains(&u[i + 1]) {
            let cp = 0x10000 + (((c as u32) - 0xD800) << 10) + ((u[i + 1] as u32) - 0xDC00);
            out.push((cp & 0xFFFF) as u16);
            i += 2;
            continue;
        }
        if (0xD800..0xE000).contains(&c) {
            out.push(c + 0x2000);
            i += 1;
            continue;
        }
        out.push(c);
        i += 1;
    }
    Ok(Value::Str(JsStr::from_units(out)))
}
