// node:util (inspect, format, promisify, types, ...) and node:assert.

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn create_module(vm: &mut Vm) -> Value {
    let o = vm.new_object();
    let fns: &[(&str, u32, NativeFn)] = &[
        ("inherits", 2, inherits),
        ("inspect", 2, inspect_fn),
        ("format", 1, format_fn),
        ("formatWithOptions", 2, format_with_options),
        ("deprecate", 2, deprecate),
        ("promisify", 1, promisify),
        ("callbackify", 1, callbackify),
        ("isArray", 1, |vm, a| Ok(Value::Bool(crate::builtins::array::is_array(vm, &a.arg(0))?))),
        ("isDate", 1, |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::Date(_)))))),
        ("isRegExp", 1, |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::RegExp(_)))))),
        ("isError", 1, |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::Error))))),
        ("isFunction", 1, |_vm, a| Ok(Value::Bool(a.arg(0).is_callable()))),
        ("isString", 1, |_vm, a| Ok(Value::Bool(matches!(a.arg(0), Value::Str(_))))),
        ("isNumber", 1, |_vm, a| Ok(Value::Bool(matches!(a.arg(0), Value::Num(_))))),
        ("isBoolean", 1, |_vm, a| Ok(Value::Bool(matches!(a.arg(0), Value::Bool(_))))),
        ("isNull", 1, |_vm, a| Ok(Value::Bool(a.arg(0).is_null()))),
        ("isNullOrUndefined", 1, |_vm, a| Ok(Value::Bool(a.arg(0).is_nullish()))),
        ("isUndefined", 1, |_vm, a| Ok(Value::Bool(a.arg(0).is_undefined()))),
        ("isObject", 1, |_vm, a| Ok(Value::Bool(matches!(a.arg(0), Value::Obj(ref o) if !o.is_callable())))),
        ("isPrimitive", 1, |_vm, a| Ok(Value::Bool(!a.arg(0).is_object()))),
        ("isBuffer", 1, |vm, a| Ok(Value::Bool(crate::runtime::buffer::is_buffer(vm, &a.arg(0))))),
        ("isSymbol", 1, |_vm, a| Ok(Value::Bool(matches!(a.arg(0), Value::Sym(_))))),
        ("isDeepStrictEqual", 2, |vm, a| Ok(Value::Bool(deep_equal(vm, &a.arg(0), &a.arg(1), true)?))),
        ("stripVTControlCharacters", 1, strip_vt),
        ("toUSVString", 1, to_usv_string),
        ("styleText", 2, |vm, a| Ok(Value::Str(vm.to_string(&a.arg(1))?))),
        ("getSystemErrorName", 1, |vm, a| {
            let n = vm.to_number(&a.arg(0))? as i32;
            Ok(Value::str(errno_name(-n)))
        }),
        ("debuglog", 1, |vm, _a| Ok(Value::Obj(vm.native_fn("debug", 0, |_vm, _a| Ok(Value::Undefined))))),
        ("aborted", 2, |vm, _a| Ok(vm.new_promise_capability_intrinsic().promise)),
        ("parseArgs", 1, parse_args),
    ];
    for (n, l, f) in fns {
        vm.def_method(&o, n, *l, *f);
    }
    if let Some(Value::Obj(insp)) = o.get_own_str("inspect") {
        let custom = vm.symbol_for("nodejs.util.inspect.custom");
        insp.set_prop(PropKey::from_str("custom"), Value::Sym(custom), WEC);
        let dflt = vm.obj_from(vec![("depth", Value::Num(2.0))]);
        insp.set_prop(PropKey::from_str("defaultOptions"), Value::Obj(dflt), WEC);
    }
    if let Some(Value::Obj(p)) = o.get_own_str("promisify") {
        let custom = vm.symbol_for("nodejs.util.promisify.custom");
        p.set_prop(PropKey::from_str("custom"), Value::Sym(custom), WEC);
    }
    if let Some(Value::Obj(d)) = o.get_own_str("debuglog") {
        o.set_prop(PropKey::from_str("debug"), Value::Obj(d), WEC);
    }
    let types = create_types(vm);
    o.set_str("types", types, WEC);
    for n in ["TextEncoder", "TextDecoder"] {
        if let Some(v) = vm.global.get_own_str(n) {
            o.set_str(n, v, WEC);
        }
    }
    crate::runtime::reorder_enum(vm, &o, crate::runtime::UTIL_KEYS);
    Value::Obj(o)
}

fn kind_is(v: &Value, f: impl Fn(&ObjKind) -> bool) -> bool {
    match v {
        Value::Obj(o) => f(&o.borrow().kind),
        _ => false,
    }
}

fn create_types(vm: &mut Vm) -> Value {
    let t = vm.new_object();
    let fns: &[(&str, NativeFn)] = &[
        ("isDate", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::Date(_)))))),
        ("isRegExp", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::RegExp(_)))))),
        ("isMap", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::Map(_)))))),
        ("isSet", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::Set(_)))))),
        ("isWeakMap", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::WeakMap(_)))))),
        ("isWeakSet", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::WeakSet(_)))))),
        ("isPromise", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::Promise(_)))))),
        ("isProxy", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::Proxy(_)))))),
        ("isTypedArray", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::TypedArray(_)))))),
        ("isUint8Array", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::TypedArray(t) if t.kind == TAKind::Uint8))))),
        ("isArrayBuffer", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::ArrayBuffer(b) if !b.borrow().shared))))),
        ("isSharedArrayBuffer", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::ArrayBuffer(b) if b.borrow().shared))))),
        ("isAnyArrayBuffer", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::ArrayBuffer(_)))))),
        ("isArrayBufferView", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::TypedArray(_) | ObjKind::DataView(_)))))),
        ("isDataView", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::DataView(_)))))),
        ("isGeneratorObject", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::Generator(_)))))),
        ("isGeneratorFunction", |_vm, a| {
            Ok(Value::Bool(match &a.arg(0) {
                Value::Obj(o) => o.closure_code().map_or(false, |c| c.is_generator),
                _ => false,
            }))
        }),
        ("isAsyncFunction", |_vm, a| {
            Ok(Value::Bool(match &a.arg(0) {
                Value::Obj(o) => o.closure_code().map_or(false, |c| c.is_async),
                _ => false,
            }))
        }),
        ("isNativeError", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::Error))))),
        ("isBoxedPrimitive", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::Number(_) | ObjKind::String(_) | ObjKind::Boolean(_) | ObjKind::Symbol(_) | ObjKind::BigInt(_)))))),
        ("isNumberObject", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::Number(_)))))),
        ("isStringObject", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::String(_)))))),
        ("isBooleanObject", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::Boolean(_)))))),
        ("isSymbolObject", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::Symbol(_)))))),
        ("isBigIntObject", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::BigInt(_)))))),
        ("isMapIterator", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::Iterator(s) if matches!(**s, IterState::Map { .. })))))),
        ("isSetIterator", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::Iterator(s) if matches!(**s, IterState::Set { .. })))))),
        ("isArgumentsObject", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::Arguments(_)))))),
        ("isWeakRef", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::WeakRef(_)))))),
        ("isModuleNamespaceObject", |_vm, a| Ok(Value::Bool(kind_is(&a.arg(0), |k| matches!(k, ObjKind::Namespace(_)))))),
    ];
    for (n, f) in fns {
        vm.def_method(&t, n, 1, *f);
    }
    Value::Obj(t)
}

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
                let cname = constructor_name(vm, o);
                match cname {
                    Some(c) if !c.is_empty() => format!("an instance of {}", c),
                    _ => {
                        let s = inspect_value(vm, v, 0).unwrap_or_default();
                        s
                    }
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

fn is_ident_key(s: &str) -> bool {
    let mut chars = s.chars();
    match chars.next() {
        Some(c) if c == '_' || c == '$' || c.is_alphabetic() => {}
        _ => return false,
    }
    chars.all(|c| c == '_' || c == '$' || c.is_alphanumeric())
}

fn quote_str(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('\'');
    for c in s.chars() {
        match c {
            '\'' => out.push_str("\\'"),
            '\\' => out.push_str("\\\\"),
            _ => out.push(c),
        }
    }
    out.push('\'');
    out
}

pub fn inspect_value(vm: &mut Vm, v: &Value, depth: i32) -> JsResult<String> {
    let mut seen = Vec::new();
    fmt_value(vm, v, 0, depth, &mut seen, true)
}

pub fn inspect_with_options(vm: &mut Vm, v: &Value, opts: &Value) -> JsResult<String> {
    let mut depth = 2;
    if let Value::Obj(o) = opts {
        let d = vm.get_str(o, "depth")?;
        match d {
            Value::Num(n) => depth = if n.is_infinite() { 1000 } else { n as i32 },
            Value::Null => depth = 0,
            _ => {}
        }
    }
    let mut seen = Vec::new();
    fmt_value(vm, v, 0, depth, &mut seen, true)
}

fn fmt_value(vm: &mut Vm, v: &Value, level: i32, max_depth: i32, seen: &mut Vec<Obj>, top: bool) -> JsResult<String> {
    match v {
        Value::Str(s) => Ok(if top { s.to_rust_string() } else { quote_str(&s.to_rust_string()) }),
        Value::Num(n) => Ok(crate::numconv::number_to_string(*n)),
        Value::BigInt(b) => Ok(format!("{}n", b.to_string_radix(10))),
        Value::Bool(b) => Ok(b.to_string()),
        Value::Undefined | Value::Empty => Ok("undefined".into()),
        Value::Null => Ok("null".into()),
        Value::Sym(s) => Ok(s.descriptive_string()),
        Value::Obj(o) => fmt_object(vm, o, level, max_depth, seen),
    }
}

fn fmt_object(vm: &mut Vm, o: &Obj, level: i32, max_depth: i32, seen: &mut Vec<Obj>) -> JsResult<String> {
    if seen.iter().any(|s| s.ptr_eq(o)) {
        return Ok("[Circular *1]".into());
    }
    // custom inspect
    let custom = vm.symbol_for("nodejs.util.inspect.custom");
    let ov = Value::Obj(o.clone());
    if let Ok(f) = vm.get(o, &PropKey::Sym(custom), &ov) {
        if f.is_callable() {
            let opts = vm.obj_from(vec![("depth", Value::Num((max_depth - level) as f64))]);
            let r = vm.call(&f, ov.clone(), &[Value::Num((max_depth - level) as f64), Value::Obj(opts)])?;
            return match &r {
                Value::Str(s) => Ok(s.to_rust_string()),
                other => fmt_value(vm, other, level, max_depth, seen, false),
            };
        }
    }
    enum K {
        Func,
        Error,
        Date(f64),
        RegExp,
        Map,
        Set,
        Array,
        Named(&'static str),
        Buffer,
        Proxy(Option<Obj>),
        Plain,
    }
    let k = {
        let b = o.borrow();
        match &b.kind {
            ObjKind::Closure(_) | ObjKind::Native(_) | ObjKind::Bound(_) => K::Func,
            ObjKind::Proxy(p) => {
                if p.callable {
                    K::Func
                } else {
                    K::Proxy(p.target.clone())
                }
            }
            ObjKind::Error => K::Error,
            ObjKind::Date(t) => K::Date(*t),
            ObjKind::RegExp(_) => K::RegExp,
            ObjKind::Map(_) => K::Map,
            ObjKind::Set(_) => K::Set,
            ObjKind::Array(_) => K::Array,
            ObjKind::Promise(_) => K::Named("Promise"),
            ObjKind::WeakMap(_) => K::Named("WeakMap"),
            ObjKind::WeakSet(_) => K::Named("WeakSet"),
            ObjKind::WeakRef(_) => K::Named("WeakRef"),
            ObjKind::TypedArray(t) if t.kind == TAKind::Uint8 && b.proto.as_ref().map_or(false, |p| crate::runtime::buffer::is_buffer_proto(vm, p)) => K::Buffer,
            _ => K::Plain,
        }
    };
    match k {
        K::Func => {
            let name = match vm.get(o, &vm.intr.key_name.clone(), &Value::Obj(o.clone())) {
                Ok(Value::Str(s)) if !s.is_empty() => Some(s.to_rust_string()),
                _ => None,
            };
            Ok(match name {
                Some(n) => format!("[Function: {}]", n),
                None => "[Function (anonymous)]".into(),
            })
        }
        K::Error => {
            let st = vm.get(o, &PropKey::from_str("stack"), &Value::Obj(o.clone()))?;
            match st {
                Value::Str(s) => Ok(s.to_rust_string()),
                _ => Ok(crate::runtime::display_value(vm, &Value::Obj(o.clone()))),
            }
        }
        K::Date(t) => Ok(crate::datetime::to_iso_string(t).unwrap_or_else(|| "Invalid Date".into())),
        K::RegExp => Ok(crate::runtime::display_value(vm, &Value::Obj(o.clone()))),
        K::Named(n) => Ok(format!("{} {{}}", n)),
        K::Buffer => {
            let bytes = crate::builtins::typedarray::ta_bytes(o);
            let shown: Vec<String> = bytes.iter().take(50).map(|b| format!("{:02x}", b)).collect();
            let more = if bytes.len() > 50 { format!(" ... {} more bytes", bytes.len() - 50) } else { String::new() };
            Ok(format!("<Buffer{}{}{}>", if shown.is_empty() { "" } else { " " }, shown.join(" "), more))
        }
        K::Proxy(t) => match t {
            Some(t) => fmt_object(vm, &t, level, max_depth, seen),
            None => Ok("{}".into()),
        },
        K::Map | K::Set => {
            if level > max_depth {
                return Ok(if matches!(k, K::Map) { "[Map]".into() } else { "[Set]".into() });
            }
            let entries: Vec<(Value, Value)> = match &o.borrow().kind {
                ObjKind::Map(m) | ObjKind::Set(m) => m.entries.iter().flatten().cloned().collect(),
                _ => Vec::new(),
            };
            seen.push(o.clone());
            let mut parts = Vec::new();
            for (key, val) in &entries {
                if matches!(k, K::Map) {
                    let ks = fmt_value(vm, key, level + 1, max_depth, seen, false)?;
                    let vs = fmt_value(vm, val, level + 1, max_depth, seen, false)?;
                    parts.push(format!("{} => {}", ks, vs));
                } else {
                    parts.push(fmt_value(vm, key, level + 1, max_depth, seen, false)?);
                }
            }
            seen.pop();
            let name = if matches!(k, K::Map) { "Map" } else { "Set" };
            Ok(format!("{}({}) {{ {} }}", name, entries.len(), parts.join(", ")))
        }
        K::Array => {
            if level > max_depth {
                return Ok("[Array]".into());
            }
            let len = vm.length_of(o)?;
            seen.push(o.clone());
            let mut parts = Vec::new();
            for i in 0..len {
                let key = PropKey::from_index(i as u32);
                if vm.ordinary_get_own(o, &key).is_none() {
                    parts.push(String::new());
                    continue;
                }
                let val = vm.get(o, &key, &Value::Obj(o.clone()))?;
                parts.push(fmt_value(vm, &val, level + 1, max_depth, seen, false)?);
            }
            seen.pop();
            if parts.is_empty() {
                return Ok("[]".into());
            }
            Ok(format!("[ {} ]", parts.join(", ")))
        }
        K::Plain => {
            let prefix = {
                let proto = o.borrow().proto.clone();
                match proto {
                    None => String::new(),
                    Some(_) => match constructor_name(vm, o) {
                        Some(n) if n != "Object" && !n.is_empty() => format!("{} ", n),
                        _ => String::new(),
                    },
                }
            };
            if level > max_depth {
                return Ok("[Object]".into());
            }
            let keys = vm.own_property_keys(o)?;
            seen.push(o.clone());
            let mut parts = Vec::new();
            for key in keys {
                let s = match &key {
                    PropKey::Str(s) => s.to_rust_string(),
                    PropKey::Sym(_) => continue,
                };
                match vm.get_own_property(o, &key)? {
                    Some(d) if d.enumerable == Some(true) => {}
                    _ => continue,
                }
                let val = vm.get(o, &key, &Value::Obj(o.clone()))?;
                let vs = fmt_value(vm, &val, level + 1, max_depth, seen, false)?;
                let ks = if is_ident_key(&s) { s } else { quote_str(&s) };
                parts.push(format!("{}: {}", ks, vs));
            }
            seen.pop();
            if parts.is_empty() {
                return Ok(format!("{}{{}}", prefix));
            }
            Ok(format!("{}{{ {} }}", prefix, parts.join(", ")))
        }
    }
}

fn inspect_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = inspect_with_options(vm, &a.arg(0), &a.arg(1))?;
    Ok(Value::str(&s))
}

pub fn format_args(vm: &mut Vm, args: &[Value]) -> JsResult<String> {
    if args.is_empty() {
        return Ok(String::new());
    }
    let mut out = String::new();
    let mut rest_start = 1;
    if let Value::Str(fs) = &args[0] {
        let f = fs.to_rust_string();
        let chars: Vec<char> = f.chars().collect();
        let mut ai = 1;
        let mut i = 0;
        while i < chars.len() {
            let c = chars[i];
            if c == '%' && i + 1 < chars.len() {
                let n = chars[i + 1];
                match n {
                    '%' => {
                        out.push('%');
                        i += 2;
                        continue;
                    }
                    's' | 'd' | 'i' | 'f' | 'j' | 'o' | 'O' | 'c' => {
                        if ai >= args.len() {
                            out.push(c);
                            out.push(n);
                            i += 2;
                            continue;
                        }
                        let v = args[ai].clone();
                        ai += 1;
                        let piece = match n {
                            's' => match &v {
                                Value::Str(s) => s.to_rust_string(),
                                Value::Obj(_) => inspect_value(vm, &v, 1)?,
                                other => crate::runtime::display_value(vm, other),
                            },
                            'd' => match &v {
                                Value::Obj(_) => "NaN".into(),
                                Value::BigInt(b) => format!("{}n", b.to_string_radix(10)),
                                other => crate::numconv::number_to_string(vm.to_number(other).unwrap_or(f64::NAN)),
                            },
                            'i' => {
                                let s = vm.to_string(&v).unwrap_or_else(|_| JsStr::from_str("NaN"));
                                crate::numconv::number_to_string(crate::numconv::parse_int(s.units(), 10))
                            }
                            'f' => {
                                let s = vm.to_string(&v).unwrap_or_else(|_| JsStr::from_str("NaN"));
                                crate::numconv::number_to_string(crate::numconv::parse_float(s.units()))
                            }
                            'j' => match crate::builtins::json::json_stringify(vm, &v, &Value::Undefined, &Value::Undefined) {
                                Ok(Some(s)) => s.to_rust_string(),
                                Ok(None) => "undefined".into(),
                                Err(_) => "[Circular]".into(),
                            },
                            'c' => String::new(),
                            _ => inspect_value(vm, &v, 2)?,
                        };
                        out.push_str(&piece);
                        i += 2;
                        continue;
                    }
                    _ => {}
                }
            }
            out.push(c);
            i += 1;
        }
        rest_start = ai;
    } else {
        rest_start = 0;
    }
    for (j, v) in args[rest_start..].iter().enumerate() {
        if j > 0 || rest_start > 0 {
            out.push(' ');
        }
        let s = match v {
            Value::Str(s) => s.to_rust_string(),
            other => inspect_value(vm, other, 2)?,
        };
        out.push_str(&s);
    }
    Ok(out)
}

fn format_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::str(&format_args(vm, a.args)?))
}

fn format_with_options(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let rest = if a.args.len() > 1 { &a.args[1..] } else { &[][..] };
    Ok(Value::str(&format_args(vm, rest)?))
}

fn inherits(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ctor = a.arg(0);
    let sup = a.arg(1);
    let (c, s) = match (&ctor, &sup) {
        (Value::Obj(c), Value::Obj(s)) => (c.clone(), s.clone()),
        _ => return vm.throw_type("The \"ctor\" and \"superCtor\" arguments must be functions"),
    };
    let sp = vm.get_str(&s, "prototype")?;
    let cp = vm.get_str(&c, "prototype")?;
    if let (Value::Obj(cpo), Value::Obj(spo)) = (&cp, &sp) {
        vm.set_prototype_of(cpo, Some(spo.clone()))?;
    }
    c.set_prop(PropKey::from_str("super_"), sup.clone(), WC);
    Ok(Value::Undefined)
}

fn deprecate(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.arg(0);
    let msg = a.arg(1);
    let code = a.arg(2);
    Ok(Value::Obj(vm.native_closure("deprecated", 0, deprecated_call, vec![f, msg, code, Value::Bool(false)])))
}

fn deprecated_call(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !a.slot(3).truthy() {
        if let ObjKind::Native(n) = &mut a.callee.borrow_mut().kind {
            n.slots[3] = Value::Bool(true);
        }
        let msg = crate::runtime::display_value(vm, &a.slot(1));
        let code = a.slot(2);
        let line = if code.is_undefined() {
            format!("(node:{}) DeprecationWarning: {}\n", std::process::id(), msg)
        } else {
            format!("(node:{}) [{}] DeprecationWarning: {}\n", std::process::id(), crate::runtime::display_value(vm, &code), msg)
        };
        crate::runtime::write_stderr(&line);
    }
    vm.call(&a.slot(0), a.this.clone(), a.args)
}

fn promisify(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.arg(0);
    if !f.is_callable() {
        let d = describe_received(vm, &f);
        return vm.throw_type(format!("The \"original\" argument must be of type function. Received {}", d));
    }
    let custom = vm.symbol_for("nodejs.util.promisify.custom");
    let c = vm.get_prop_of(&f, &PropKey::Sym(custom))?;
    if c.is_callable() {
        return Ok(c);
    }
    Ok(Value::Obj(vm.native_closure("promisified", 0, promisified_call, vec![f])))
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
    if !err.is_nullish() {
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
    Ok(Value::Obj(vm.native_closure("callbackified", 0, callbackified_call, vec![f])))
}

fn callbackified_call(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut args = a.args.to_vec();
    let cb = args.pop().unwrap_or(Value::Undefined);
    if !cb.is_callable() {
        return vm.throw_type("The last argument must be of type function");
    }
    let p = vm.call(&a.slot(0), a.this.clone(), &args)?;
    let p = crate::builtins::promise::promise_resolve_intrinsic(vm, p)?;
    let on_ok = vm.native_closure("", 1, |vm, a| {
        let cb = a.slot(0);
        vm.host.callbacks.push_back((cb, vec![Value::Null, a.arg(0)]));
        Ok(Value::Undefined)
    }, vec![cb.clone()]);
    let on_err = vm.native_closure("", 1, |vm, a| {
        let cb = a.slot(0);
        vm.host.callbacks.push_back((cb, vec![a.arg(0)]));
        Ok(Value::Undefined)
    }, vec![cb]);
    crate::builtins::promise::promise_then(vm, &p, Value::Obj(on_ok), Value::Obj(on_err))?;
    Ok(Value::Undefined)
}

fn strip_vt(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?.to_rust_string();
    let mut out = String::new();
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\u{1b}' {
            if chars.peek() == Some(&'[') {
                chars.next();
                while let Some(&n) = chars.peek() {
                    chars.next();
                    if n.is_ascii_alphabetic() {
                        break;
                    }
                }
            }
            continue;
        }
        out.push(c);
    }
    Ok(Value::str(&out))
}

fn to_usv_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    let r: String = char::decode_utf16(s.units().iter().copied()).map(|r| r.unwrap_or('\u{fffd}')).collect();
    Ok(Value::str(&r))
}

pub fn errno_name(n: i32) -> &'static str {
    match n {
        1 => "EPERM",
        2 => "ENOENT",
        13 => "EACCES",
        17 => "EEXIST",
        20 => "ENOTDIR",
        21 => "EISDIR",
        22 => "EINVAL",
        39 => "ENOTEMPTY",
        _ => "UNKNOWN",
    }
}

fn parse_args(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cfg = a.arg(0);
    let args_v = match &cfg {
        Value::Obj(c) => vm.get_str(c, "args")?,
        _ => Value::Undefined,
    };
    let args: Vec<String> = if args_v.is_undefined() {
        vm.host.argv.iter().skip(2).cloned().collect()
    } else {
        let v = crate::builtins::array::array_like_to_vec(vm, &args_v)?;
        let mut out = Vec::new();
        for x in v {
            out.push(vm.to_string(&x)?.to_rust_string());
        }
        out
    };
    let options = match &cfg {
        Value::Obj(c) => vm.get_str(c, "options")?,
        _ => Value::Undefined,
    };
    let allow_positionals = match &cfg {
        Value::Obj(c) => vm.get_str(c, "allowPositionals")?.truthy(),
        _ => false,
    };
    let values = Obj::new(None, ObjKind::Ordinary);
    let mut positionals = Vec::new();
    // option specs
    let mut specs: Vec<(String, String, Option<String>, bool)> = Vec::new();
    if let Value::Obj(oo) = &options {
        let keys = vm.enumerable_own_keys(oo)?;
        for k in keys {
            let spec = vm.get(oo, &PropKey::Str(k.clone()), &options)?;
            let (ty, short, multiple, default) = match &spec {
                Value::Obj(so) => {
                    let t = vm.get_str(so, "type")?;
                    let s = vm.get_str(so, "short")?;
                    let m = vm.get_str(so, "multiple")?.truthy();
                    let d = vm.get_str(so, "default")?;
                    (
                        if t.is_undefined() { "boolean".to_string() } else { vm.to_string(&t)?.to_rust_string() },
                        if s.is_undefined() { None } else { Some(vm.to_string(&s)?.to_rust_string()) },
                        m,
                        d,
                    )
                }
                _ => ("boolean".into(), None, false, Value::Undefined),
            };
            if !default.is_undefined() {
                values.set_prop(PropKey::Str(k.clone()), default, WEC);
            }
            specs.push((k.to_rust_string(), ty, short, multiple));
        }
    }
    let mut i = 0;
    while i < args.len() {
        let arg = &args[i];
        if arg == "--" {
            for p in &args[i + 1..] {
                positionals.push(Value::str(p));
            }
            break;
        }
        let (name, inline): (Option<String>, Option<String>) = if let Some(long) = arg.strip_prefix("--") {
            match long.find('=') {
                Some(p) => (Some(long[..p].to_string()), Some(long[p + 1..].to_string())),
                None => (Some(long.to_string()), None),
            }
        } else if arg.starts_with('-') && arg.len() > 1 {
            let s = &arg[1..2];
            let found = specs.iter().find(|sp| sp.2.as_deref() == Some(s)).map(|sp| sp.0.clone());
            (Some(found.unwrap_or_else(|| s.to_string())), if arg.len() > 2 { Some(arg[2..].to_string()) } else { None })
        } else {
            if !allow_positionals {
                return vm.throw_type(format!("Unexpected argument '{}'. This command does not take positional arguments", arg));
            }
            positionals.push(Value::str(arg));
            i += 1;
            continue;
        };
        let name = name.unwrap();
        let spec = specs.iter().find(|s| s.0 == name).cloned();
        match spec {
            None => return vm.throw_type(format!("Unknown option '--{}'", name)),
            Some((n, ty, _, multiple)) => {
                let val = if ty == "string" {
                    match inline {
                        Some(v) => Value::str(&v),
                        None => {
                            i += 1;
                            match args.get(i) {
                                Some(v) => Value::str(v),
                                None => return vm.throw_type(format!("Option '--{} <value>' argument missing", n)),
                            }
                        }
                    }
                } else {
                    Value::Bool(true)
                };
                if multiple {
                    let k = PropKey::from_str(&n);
                    let existing = values.get_own_data(&k);
                    match existing {
                        Some(Value::Obj(arr)) if arr.is_array() => crate::vm::array_push_raw(&arr, val),
                        _ => {
                            let arr = vm.new_array(vec![val]);
                            values.set_prop(k, Value::Obj(arr), WEC);
                        }
                    }
                } else {
                    values.set_prop(PropKey::from_str(&n), val, WEC);
                }
            }
        }
        i += 1;
    }
    let r = vm.new_object();
    r.set_str("values", Value::Obj(values), WEC);
    let pa = vm.new_array(positionals);
    r.set_str("positionals", Value::Obj(pa), WEC);
    Ok(Value::Obj(r))
}

// ---------------- deep equality ----------------

pub fn deep_equal(vm: &mut Vm, a: &Value, b: &Value, strict: bool) -> JsResult<bool> {
    let mut memo = Vec::new();
    deep_eq_inner(vm, a, b, strict, &mut memo)
}

fn deep_eq_inner(vm: &mut Vm, a: &Value, b: &Value, strict: bool, memo: &mut Vec<(Obj, Obj)>) -> JsResult<bool> {
    match (a, b) {
        (Value::Obj(x), Value::Obj(y)) => {
            if x.ptr_eq(y) {
                return Ok(true);
            }
            if memo.iter().any(|(p, q)| p.ptr_eq(x) && q.ptr_eq(y)) {
                return Ok(true);
            }
            if strict {
                let px = vm.get_prototype_of(x)?;
                let py = vm.get_prototype_of(y)?;
                let same = match (&px, &py) {
                    (Some(p), Some(q)) => p.ptr_eq(q),
                    (None, None) => true,
                    _ => false,
                };
                if !same {
                    return Ok(false);
                }
            }
            let xa = x.is_array();
            if xa != y.is_array() {
                return Ok(false);
            }
            enum Spec {
                Date(f64, f64),
                Re(String, String),
                Map,
                Set,
                Boxed,
                Ta(Vec<u8>, Vec<u8>),
                Err,
                None,
            }
            let spec = {
                let bx = x.borrow();
                let by = y.borrow();
                match (&bx.kind, &by.kind) {
                    (ObjKind::Date(p), ObjKind::Date(q)) => Spec::Date(*p, *q),
                    (ObjKind::RegExp(p), ObjKind::RegExp(q)) => Spec::Re(format!("{}/{}", p.source, p.flags), format!("{}/{}", q.source, q.flags)),
                    (ObjKind::Map(_), ObjKind::Map(_)) => Spec::Map,
                    (ObjKind::Set(_), ObjKind::Set(_)) => Spec::Set,
                    (ObjKind::Number(_), ObjKind::Number(_)) | (ObjKind::String(_), ObjKind::String(_)) | (ObjKind::Boolean(_), ObjKind::Boolean(_)) => Spec::Boxed,
                    (ObjKind::TypedArray(_), ObjKind::TypedArray(_)) => {
                        drop(bx);
                        drop(by);
                        Spec::Ta(crate::builtins::typedarray::ta_bytes(x), crate::builtins::typedarray::ta_bytes(y))
                    }
                    (ObjKind::Error, ObjKind::Error) => Spec::Err,
                    (ObjKind::Date(_), _) | (_, ObjKind::Date(_)) | (ObjKind::RegExp(_), _) | (_, ObjKind::RegExp(_)) | (ObjKind::Map(_), _) | (_, ObjKind::Map(_)) | (ObjKind::Set(_), _) | (_, ObjKind::Set(_)) => {
                        return Ok(false)
                    }
                    _ => Spec::None,
                }
            };
            match spec {
                Spec::Date(p, q) => {
                    if !(p == q || (p.is_nan() && q.is_nan())) {
                        return Ok(false);
                    }
                }
                Spec::Re(p, q) => {
                    if p != q {
                        return Ok(false);
                    }
                }
                Spec::Boxed => {
                    let p = vm.to_primitive(a, crate::ops::Hint::Default)?;
                    let q = vm.to_primitive(b, crate::ops::Hint::Default)?;
                    if !Value::same_value(&p, &q) {
                        return Ok(false);
                    }
                }
                Spec::Ta(p, q) => {
                    if p != q {
                        return Ok(false);
                    }
                }
                Spec::Err => {
                    let mx = vm.get_str(x, "message")?;
                    let my = vm.get_str(y, "message")?;
                    let nx = vm.get_str(x, "name")?;
                    let ny = vm.get_str(y, "name")?;
                    if !Value::strict_eq(&mx, &my) || !Value::strict_eq(&nx, &ny) {
                        return Ok(false);
                    }
                }
                Spec::Map => {
                    let ex: Vec<(Value, Value)> = match &x.borrow().kind {
                        ObjKind::Map(m) => m.entries.iter().flatten().cloned().collect(),
                        _ => Vec::new(),
                    };
                    let ey: Vec<(Value, Value)> = match &y.borrow().kind {
                        ObjKind::Map(m) => m.entries.iter().flatten().cloned().collect(),
                        _ => Vec::new(),
                    };
                    if ex.len() != ey.len() {
                        return Ok(false);
                    }
                    memo.push((x.clone(), y.clone()));
                    for (k, v) in &ex {
                        let other = match &y.borrow().kind {
                            ObjKind::Map(m) => m.get(k).cloned(),
                            _ => None,
                        };
                        let found = match other {
                            Some(ov) => deep_eq_inner(vm, v, &ov, strict, memo)?,
                            None => {
                                let mut f = false;
                                for (k2, v2) in &ey {
                                    if deep_eq_inner(vm, k, k2, strict, memo)? && deep_eq_inner(vm, v, v2, strict, memo)? {
                                        f = true;
                                        break;
                                    }
                                }
                                f
                            }
                        };
                        if !found {
                            memo.pop();
                            return Ok(false);
                        }
                    }
                    memo.pop();
                }
                Spec::Set => {
                    let ex: Vec<Value> = match &x.borrow().kind {
                        ObjKind::Set(m) => m.entries.iter().flatten().map(|(k, _)| k.clone()).collect(),
                        _ => Vec::new(),
                    };
                    let ey: Vec<Value> = match &y.borrow().kind {
                        ObjKind::Set(m) => m.entries.iter().flatten().map(|(k, _)| k.clone()).collect(),
                        _ => Vec::new(),
                    };
                    if ex.len() != ey.len() {
                        return Ok(false);
                    }
                    for k in &ex {
                        let has = match &y.borrow().kind {
                            ObjKind::Set(m) => m.has(k),
                            _ => false,
                        };
                        if !has {
                            let mut f = false;
                            for k2 in &ey {
                                if k2.is_object() && deep_eq_inner(vm, k, k2, strict, memo)? {
                                    f = true;
                                    break;
                                }
                            }
                            if !f {
                                return Ok(false);
                            }
                        }
                    }
                }
                Spec::None => {}
            }
            let kx = own_enum_keys(vm, x)?;
            let ky = own_enum_keys(vm, y)?;
            if kx.len() != ky.len() {
                return Ok(false);
            }
            memo.push((x.clone(), y.clone()));
            for k in &kx {
                if !ky.contains(k) {
                    memo.pop();
                    return Ok(false);
                }
                let vx = vm.get(x, k, a)?;
                let vy = vm.get(y, k, b)?;
                if !deep_eq_inner(vm, &vx, &vy, strict, memo)? {
                    memo.pop();
                    return Ok(false);
                }
            }
            memo.pop();
            Ok(true)
        }
        (Value::Obj(_), _) | (_, Value::Obj(_)) => {
            if strict {
                Ok(false)
            } else {
                Ok(vm.loose_eq(a, b)?)
            }
        }
        _ => {
            if strict {
                Ok(Value::same_value(a, b))
            } else {
                Ok(Value::strict_eq(a, b) || vm.loose_eq(a, b)? || (matches!((a, b), (Value::Num(x), Value::Num(y)) if x.is_nan() && y.is_nan())))
            }
        }
    }
}

fn own_enum_keys(vm: &mut Vm, o: &Obj) -> JsResult<Vec<PropKey>> {
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

// ---------------- assert ----------------

pub fn create_assert_module(vm: &mut Vm) -> Value {
    let a = vm.native_fn("ok", 2, assert_ok);
    let fns: &[(&str, u32, NativeFn)] = &[
        ("ok", 2, assert_ok),
        ("equal", 3, |vm, a| assert_cmp(vm, a, "==")),
        ("notEqual", 3, |vm, a| assert_cmp(vm, a, "!=")),
        ("strictEqual", 3, |vm, a| assert_cmp(vm, a, "===")),
        ("notStrictEqual", 3, |vm, a| assert_cmp(vm, a, "!==")),
        ("deepEqual", 3, |vm, a| assert_cmp(vm, a, "deepEqual")),
        ("deepStrictEqual", 3, |vm, a| assert_cmp(vm, a, "deepStrictEqual")),
        ("notDeepEqual", 3, |vm, a| assert_cmp(vm, a, "notDeepEqual")),
        ("notDeepStrictEqual", 3, |vm, a| assert_cmp(vm, a, "notDeepStrictEqual")),
        ("throws", 3, assert_throws),
        ("doesNotThrow", 3, assert_does_not_throw),
        ("rejects", 3, assert_rejects),
        ("doesNotReject", 3, |vm, _a| Ok(vm.new_promise_capability_intrinsic().promise)),
        ("fail", 1, assert_fail),
        ("match", 3, |vm, a| assert_match(vm, a, true)),
        ("doesNotMatch", 3, |vm, a| assert_match(vm, a, false)),
        ("ifError", 1, |_vm, a| if a.arg(0).is_nullish() { Ok(Value::Undefined) } else { Err(a.arg(0)) }),
    ];
    for (n, l, f) in fns {
        vm.def_method(&a, n, *l, *f);
    }
    a.set_prop(PropKey::from_str("strict"), Value::Obj(a.clone()), WEC);
    let aep = Obj::new(Some(vm.intr.error_proto.clone()), ObjKind::Ordinary);
    let aec = vm.native_ctor("AssertionError", 1, assertion_error_ctor, &aep);
    aep.set_prop(PropKey::from_str("name"), Value::str("AssertionError"), WC);
    a.set_prop(PropKey::from_str("AssertionError"), Value::Obj(aec), WEC);
    Value::Obj(a)
}

fn assertion_error_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let msg = match a.arg(0) {
        Value::Obj(o) => vm.get_str(&o, "message")?,
        _ => Value::Undefined,
    };
    let m = if msg.is_undefined() { "Failed".to_string() } else { vm.to_string(&msg)?.to_rust_string() };
    Ok(make_assertion_error(vm, &m, Value::Undefined, Value::Undefined, "fail"))
}

pub fn make_assertion_error(vm: &mut Vm, msg: &str, actual: Value, expected: Value, op: &str) -> Value {
    let e = vm.make_error("Error", msg);
    if let Value::Obj(o) = &e {
        o.set_prop(PropKey::from_str("name"), Value::str("AssertionError"), WC);
        o.set_prop(PropKey::from_str("generatedMessage"), Value::Bool(false), WEC);
        o.set_prop(PropKey::from_str("code"), Value::str("ERR_ASSERTION"), WEC);
        o.set_prop(PropKey::from_str("actual"), actual, WEC);
        o.set_prop(PropKey::from_str("expected"), expected, WEC);
        o.set_prop(PropKey::from_str("operator"), Value::str(op), WEC);
        vm.attach_stack(o, "AssertionError", msg);
    }
    e
}

fn assert_ok(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.arg(0).truthy() {
        return Ok(Value::Undefined);
    }
    let m = a.arg(1);
    if let Value::Obj(o) = &m {
        if matches!(o.borrow().kind, ObjKind::Error) {
            return Err(m);
        }
    }
    let msg = if m.is_undefined() {
        if a.args.is_empty() {
            "No value argument passed to `assert.ok()`".to_string()
        } else {
            "The expression evaluated to a falsy value".to_string()
        }
    } else {
        vm.to_string(&m)?.to_rust_string()
    };
    Err(make_assertion_error(vm, &msg, a.arg(0), Value::Bool(true), "=="))
}

fn assert_cmp(vm: &mut Vm, a: &Args, op: &str) -> JsResult<Value> {
    let x = a.arg(0);
    let y = a.arg(1);
    let ok = match op {
        "==" => vm.loose_eq(&x, &y)? || (matches!((&x, &y), (Value::Num(p), Value::Num(q)) if p.is_nan() && q.is_nan())),
        "!=" => !vm.loose_eq(&x, &y)?,
        "===" => Value::same_value(&x, &y),
        "!==" => !Value::same_value(&x, &y),
        "deepEqual" => deep_equal(vm, &x, &y, false)?,
        "deepStrictEqual" => deep_equal(vm, &x, &y, true)?,
        "notDeepEqual" => !deep_equal(vm, &x, &y, false)?,
        _ => !deep_equal(vm, &x, &y, true)?,
    };
    if ok {
        return Ok(Value::Undefined);
    }
    let m = a.arg(2);
    if let Value::Obj(o) = &m {
        if matches!(o.borrow().kind, ObjKind::Error) {
            return Err(m);
        }
    }
    let msg = if m.is_undefined() {
        let xs = inspect_value(vm, &x, 2)?;
        let ys = inspect_value(vm, &y, 2)?;
        let xs = if let Value::Str(_) = x { format!("'{}'", xs) } else { xs };
        let ys = if let Value::Str(_) = y { format!("'{}'", ys) } else { ys };
        match op {
            "===" => format!("Expected values to be strictly equal:\n\n{} !== {}\n", xs, ys),
            "deepStrictEqual" => format!("Expected values to be strictly deep-equal:\n{} !== {}", xs, ys),
            "!==" => format!("Expected \"actual\" to be strictly unequal to: {}", ys),
            _ => format!("{} {} {}", xs, op, ys),
        }
    } else {
        vm.to_string(&m)?.to_rust_string()
    };
    Err(make_assertion_error(vm, &msg, x, y, op))
}

fn check_expected_error(vm: &mut Vm, e: &Value, expected: &Value) -> JsResult<bool> {
    match expected {
        Value::Undefined => Ok(true),
        Value::Obj(o) if o.is_callable() => {
            if o.is_constructor() {
                let proto = vm.get_str(o, "prototype")?;
                if proto.is_object() {
                    if vm.instance_of(e, expected)? {
                        return Ok(true);
                    }
                    // error class that doesn't match
                    if let Value::Obj(po) = &proto {
                        let err_proto = vm.intr.error_proto.clone();
                        let mut cur = Some(po.clone());
                        while let Some(c) = cur {
                            if c.ptr_eq(&err_proto) {
                                return Ok(false);
                            }
                            cur = c.borrow().proto.clone();
                        }
                    }
                }
            }
            let r = vm.call(expected, Value::Undefined, &[e.clone()])?;
            Ok(r.truthy())
        }
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::RegExp(_)) => {
            let s = crate::runtime::display_value(vm, e);
            let t = vm.get_str(o, "test")?;
            Ok(vm.call(&t, expected.clone(), &[Value::str(&s)])?.truthy())
        }
        Value::Obj(o) => {
            let keys = vm.enumerable_own_keys(o)?;
            for k in keys {
                let ev = vm.get_prop_of(e, &PropKey::Str(k.clone()))?;
                let xv = vm.get(o, &PropKey::Str(k), expected)?;
                let ok = if let Value::Obj(xo) = &xv {
                    if matches!(xo.borrow().kind, ObjKind::RegExp(_)) {
                        let s = crate::runtime::display_value(vm, &ev);
                        let t = vm.get_str(xo, "test")?;
                        vm.call(&t, xv.clone(), &[Value::str(&s)])?.truthy()
                    } else {
                        deep_equal(vm, &ev, &xv, true)?
                    }
                } else {
                    deep_equal(vm, &ev, &xv, true)?
                };
                if !ok {
                    return Ok(false);
                }
            }
            Ok(true)
        }
        _ => Ok(true),
    }
}

fn assert_throws(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.arg(0);
    match vm.call(&f, Value::Undefined, &[]) {
        Ok(_) => {
            let m = if let Value::Str(s) = a.arg(1) { s.to_rust_string() } else if let Value::Str(s) = a.arg(2) { s.to_rust_string() } else { String::new() };
            let msg = if m.is_empty() { "Missing expected exception.".to_string() } else { format!("Missing expected exception: {}", m) };
            Err(make_assertion_error(vm, &msg, Value::Undefined, a.arg(1), "throws"))
        }
        Err(e) => {
            let exp = a.arg(1);
            if let Value::Str(_) = exp {
                return Ok(Value::Undefined);
            }
            if check_expected_error(vm, &e, &exp)? {
                Ok(Value::Undefined)
            } else {
                Err(e)
            }
        }
    }
}

fn assert_does_not_throw(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match vm.call(&a.arg(0), Value::Undefined, &[]) {
        Ok(_) => Ok(Value::Undefined),
        Err(e) => {
            let mv = vm.get_prop_of(&e, &PropKey::from_str("message")).unwrap_or(Value::Undefined);
            let m = crate::runtime::display_value(vm, &mv);
            Err(make_assertion_error(vm, &format!("Got unwanted exception.\nActual message: \"{}\"", m), e, Value::Undefined, "doesNotThrow"))
        }
    }
}

fn assert_rejects(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = if a.arg(0).is_callable() { vm.call(&a.arg(0), Value::Undefined, &[])? } else { a.arg(0) };
    let p = crate::builtins::promise::promise_resolve_intrinsic(vm, p)?;
    let ok = vm.native_closure("", 1, |vm, _a| {
        let e = make_assertion_error(vm, "Missing expected rejection.", Value::Undefined, Value::Undefined, "rejects");
        Err(e)
    }, vec![]);
    let err = vm.native_closure("", 1, |vm, a| {
        let exp = a.slot(0);
        if check_expected_error(vm, &a.arg(0), &exp)? {
            Ok(Value::Undefined)
        } else {
            Err(a.arg(0))
        }
    }, vec![a.arg(1)]);
    crate::builtins::promise::promise_then(vm, &p, Value::Obj(ok), Value::Obj(err))
}

fn assert_fail(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = a.arg(0);
    if let Value::Obj(o) = &m {
        if matches!(o.borrow().kind, ObjKind::Error) {
            return Err(m);
        }
    }
    let msg = if m.is_undefined() { "Failed".to_string() } else { vm.to_string(&m)?.to_rust_string() };
    Err(make_assertion_error(vm, &msg, Value::Undefined, Value::Undefined, "fail"))
}

fn assert_match(vm: &mut Vm, a: &Args, want: bool) -> JsResult<Value> {
    let s = a.arg(0);
    let re = a.arg(1);
    let t = vm.get_prop_of(&re, &PropKey::from_str("test"))?;
    let r = vm.call(&t, re.clone(), &[s.clone()])?.truthy();
    if r == want {
        return Ok(Value::Undefined);
    }
    let m = a.arg(2);
    let msg = if m.is_undefined() {
        let rs = crate::runtime::display_value(vm, &re);
        let ss = inspect_value(vm, &s, 2)?;
        if want {
            format!("The input did not match the regular expression {}. Input:\n\n'{}'\n", rs, ss)
        } else {
            format!("The input was expected to not match the regular expression {}. Input:\n\n'{}'\n", rs, ss)
        }
    } else {
        vm.to_string(&m)?.to_rust_string()
    };
    Err(make_assertion_error(vm, &msg, s, re, if want { "match" } else { "doesNotMatch" }))
}

// ---------------- async_hooks ----------------

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
