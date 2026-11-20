// node:vm and node:v8, modelled on the reference runtime.
//
// vm: there is a single realm. runInThisContext is an indirect (global) eval; a "context" is a
// plain sandbox object registered in a weak set, and code run against it goes through a sloppy
// `with` over a proxy whose `has` answers true for every name: reads come from the sandbox (or
// fall back to the real global), writes land on the sandbox. So undeclared names read as
// undefined, assignments and `var` initialisers become sandbox properties, and `this` is the
// real global object.
//
// v8: serialize/deserialize use the reference's compact tag format (not V8's wire format):
// header ff 0f, then a tagged value tree with back-references; heap statistics are constant.

use crate::object::*;
use crate::runtime::nodestream::{call_method, getp, key, make_class, new_buffer, new_instance, plain_fn, resolved, setp};
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::cell::RefCell;
use std::rc::Weak;

// ============================================================================================
// vm
// ============================================================================================

thread_local! {
    static CONTEXTS: RefCell<Vec<Weak<RefCell<ObjectData>>>> = RefCell::new(Vec::new());
    static VM_CLASSES: RefCell<Option<(Obj, Obj)>> = RefCell::new(None);
    static V8_CLASSES: RefCell<Option<V8Classes>> = RefCell::new(None);
}

fn is_context(v: &Value) -> bool {
    match v {
        Value::Obj(o) => CONTEXTS.with(|c| c.borrow().iter().any(|w| w.upgrade().map_or(false, |rc| std::rc::Rc::ptr_eq(&rc, &o.0)))),
        _ => false,
    }
}

/// contextify(sandbox)
fn contextify(vm: &mut Vm, sandbox: &Value) -> JsResult<Value> {
    let s = if sandbox.is_nullish() { Value::Obj(vm.new_object()) } else { sandbox.clone() };
    match &s {
        Value::Obj(o) => {
            if !is_context(&s) {
                CONTEXTS.with(|c| {
                    let mut c = c.borrow_mut();
                    c.retain(|w| w.strong_count() > 0);
                    c.push(o.downgrade());
                });
            }
            Ok(s)
        }
        _ => vm.throw_type("Invalid value used in weak set"),
    }
}

fn not_context(vm: &mut Vm) -> Value {
    vm.make_error("TypeError", "The \"contextifiedObject\" argument must be a vm.Context.")
}

/// runInGlobal(code): an indirect eval.
fn run_in_global(vm: &mut Vm, code: Value) -> JsResult<Value> {
    let ev = Value::Obj(vm.intr.eval_fn.clone());
    vm.call(&ev, Value::Undefined, &[code])
}

fn sandbox_has(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(true))
}

fn sandbox_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let sandbox = a.slot(0);
    let k = vm.to_property_key(&a.arg(1))?;
    let so = match &sandbox {
        Value::Obj(o) => o.clone(),
        _ => return Ok(Value::Undefined),
    };
    if vm.has_property(&so, &k)? {
        return vm.get(&so, &k, &sandbox);
    }
    let g = vm.global.clone();
    vm.get(&g, &k, &Value::Obj(g.clone()))
}

fn sandbox_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let sandbox = a.slot(0);
    let k = vm.to_property_key(&a.arg(1))?;
    vm.set_prop_of(&sandbox, k, a.arg(2), false)?;
    Ok(Value::Bool(true))
}

/// runWithSandbox(code, sandbox)
fn run_with_sandbox(vm: &mut Vm, code: &str, sandbox: &Value) -> JsResult<Value> {
    let handler = vm.new_object();
    let has = vm.native_closure("has", 2, sandbox_has, vec![sandbox.clone()]);
    handler.set_prop(key("has"), Value::Obj(has), WEC);
    let get = vm.native_closure("get", 3, sandbox_get, vec![sandbox.clone()]);
    handler.set_prop(key("get"), Value::Obj(get), WEC);
    let set = vm.native_closure("set", 4, sandbox_set, vec![sandbox.clone()]);
    handler.set_prop(key("set"), Value::Obj(set), WEC);
    let target = Value::Obj(vm.new_object());
    let proxy_ctor = vm.global.get_own_str("Proxy").unwrap_or(Value::Undefined);
    let proxy = vm.construct(&proxy_ctor, &[target, Value::Obj(handler)], None)?;
    let lit = crate::builtins::json::json_stringify(vm, &Value::str(code), &Value::Undefined, &Value::Undefined)?.map(|s| s.to_rust_string()).unwrap_or_else(|| "\"\"".into());
    let body = format!("with (__lumen_vm_sandbox) {{ return eval({}); }}", lit);
    let fctor = Value::Obj(vm.intr.function_ctor.clone());
    let f = vm.construct(&fctor, &[Value::str("__lumen_vm_sandbox"), Value::str(&body)], None)?;
    vm.call(&f, Value::Undefined, &[proxy])
}

fn vm_run_in_this_context(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    run_in_global(vm, Value::Str(s))
}

fn vm_run_in_new_context(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let code = vm.to_string(&a.arg(0))?.to_rust_string();
    let sb = contextify(vm, &a.arg(1))?;
    run_with_sandbox(vm, &code, &sb)
}

fn vm_run_in_context(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !is_context(&a.arg(1)) {
        return Err(not_context(vm));
    }
    let code = vm.to_string(&a.arg(0))?.to_rust_string();
    run_with_sandbox(vm, &code, &a.arg(1))
}

fn vm_create_context(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    contextify(vm, &a.arg(0))
}

fn vm_is_context(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(is_context(&a.arg(0))))
}

fn vm_compile_function(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let params = a.arg(1);
    let mut args: Vec<Value> = if matches!(&params, Value::Obj(o) if o.is_array()) { crate::builtins::array::array_like_to_vec(vm, &params)? } else { Vec::new() };
    let code = a.arg(0);
    args.push(if code.is_undefined() { Value::str("") } else { Value::Str(vm.to_string(&code)?) });
    let fctor = Value::Obj(vm.intr.function_ctor.clone());
    vm.construct(&fctor, &args, None)
}

fn vm_create_script(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (sc, _) = vm_classes(vm);
    vm.construct(&Value::Obj(sc), &[a.arg(0), a.arg(1)], None)
}

fn vm_measure_memory(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let range = Value::Obj(vm.new_array(vec![Value::Num(0.0), Value::Num(0.0)]));
    let total = Value::Obj(vm.obj_from(vec![("jsMemoryEstimate", Value::Num(0.0)), ("jsMemoryRange", range)]));
    let r = Value::Obj(vm.obj_from(vec![("total", total)]));
    Ok(resolved(vm, r))
}

// --- vm.Script ---

fn vm_classes(vm: &mut Vm) -> (Obj, Obj) {
    if let Some(c) = VM_CLASSES.with(|c| c.borrow().clone()) {
        return c;
    }
    let (sc, sp) = make_class(vm, "Script", 1, script_ctor_f, None);
    vm.def_method(&sp, "runInThisContext", 0, script_run_in_this_context);
    vm.def_method(&sp, "runInContext", 1, script_run_in_context_f);
    vm.def_method(&sp, "runInNewContext", 1, script_run_in_new_context);
    vm.def_method(&sp, "createCachedData", 0, script_create_cached_data);
    VM_CLASSES.with(|c| *c.borrow_mut() = Some((sc.clone(), sp.clone())));
    (sc, sp)
}

fn script_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (_, sp) = vm_classes(vm);
    let o = new_instance(vm, a, &sp)?;
    let this = Value::Obj(o);
    let code = a.arg(0);
    let code = if code.is_undefined() { Value::str("undefined") } else { Value::Str(vm.to_string(&code)?) };
    setp(vm, &this, "code", code.clone())?;
    let options = if a.arg(1).is_undefined() { Value::Obj(vm.new_object()) } else { a.arg(1) };
    let fname = if options.truthy() { getp(vm, &options, "filename")? } else { Value::Undefined };
    setp(vm, &this, "filename", if fname.truthy() { fname } else { Value::str("evalmachine.<anonymous>") })?;
    // compile eagerly so a SyntaxError surfaces now (new Function parses without running)
    let fctor = Value::Obj(vm.intr.function_ctor.clone());
    if let Err(e) = vm.construct(&fctor, &[code], None) {
        let se = Value::Obj(vm.intr.syntax_error_proto.clone());
        let is_syntax = match &e {
            Value::Obj(eo) => {
                let mut p = eo.proto();
                let mut found = false;
                while let Some(pp) = p {
                    if Value::strict_eq(&Value::Obj(pp.clone()), &se) {
                        found = true;
                        break;
                    }
                    p = pp.proto();
                }
                found
            }
            _ => false,
        };
        if is_syntax {
            return Err(e);
        }
    }
    Ok(this)
}

fn script_code(vm: &mut Vm, this: &Value) -> JsResult<Value> {
    getp(vm, this, "code")
}

fn script_run_in_this_context(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = script_code(vm, &a.this)?;
    run_in_global(vm, c)
}

fn script_run_in_context(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !is_context(&a.arg(0)) {
        return Err(not_context(vm));
    }
    let c = script_code(vm, &a.this)?;
    let s = vm.to_string(&c)?.to_rust_string();
    run_with_sandbox(vm, &s, &a.arg(0))
}

fn script_run_in_new_context(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let sb = contextify(vm, &a.arg(0))?;
    let c = script_code(vm, &a.this)?;
    let s = vm.to_string(&c)?.to_rust_string();
    run_with_sandbox(vm, &s, &sb)
}

fn script_create_cached_data(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    vm.throw_error("Error", "vm.Script.createCachedData is not supported in lumen")
}

fn create_vm(vm: &mut Vm) -> Value {
    let (sc, _) = vm_classes(vm);
    let o = vm.new_object();
    o.set_prop(key("Script"), Value::Obj(sc), WEC);
    let f = vm.native_fn("compileFunction", 1, vm_compile_function);
    o.set_prop(key("compileFunction"), Value::Obj(f), WEC);
    let constants = vm.new_object();
    let s1 = Sym::new(Some(JsStr::from_str("vm_dynamic_import_main_context_default")));
    constants.set_prop(key("USE_MAIN_CONTEXT_DEFAULT_LOADER"), Value::Sym(s1), WEC);
    let s2 = Sym::new(Some(JsStr::from_str("vm_context_no_contextify")));
    constants.set_prop(key("DONT_CONTEXTIFY"), Value::Sym(s2), WEC);
    o.set_prop(key("constants"), Value::Obj(constants), WEC);
    let fns: &[(&str, u32, NativeFn)] = &[
        ("createContext", 1, vm_create_context),
        ("createScript", 2, vm_create_script),
        ("isContext", 1, vm_is_context),
        ("measureMemory", 0, vm_measure_memory),
        ("runInContext", 2, vm_run_in_context_f),
        ("runInNewContext", 2, vm_run_in_new_context),
        ("runInThisContext", 1, vm_run_in_this_context),
    ];
    for (n, l, f) in fns {
        let fo = vm.native_fn(n, *l, *f);
        o.set_prop(key(n), Value::Obj(fo), WEC);
    }
    Value::Obj(o)
}

// ============================================================================================
// v8
// ============================================================================================

const T_UNDEFINED: u8 = 0;
const T_NULL: u8 = 1;
const T_TRUE: u8 = 2;
const T_FALSE: u8 = 3;
const T_NUMBER: u8 = 4;
const T_STRING: u8 = 5;
const T_BIGINT: u8 = 6;
const T_ARRAY: u8 = 7;
const T_OBJECT: u8 = 8;
const T_MAP: u8 = 9;
const T_SET: u8 = 10;
const T_DATE: u8 = 11;
const T_REGEXP: u8 = 12;
const T_ARRAYBUFFER: u8 = 13;
const T_TYPEDARRAY: u8 = 14;
const T_BUFFER: u8 = 15;
const T_REF: u8 = 16;

const HEAP_LIMIT: f64 = 2147483648.0;

#[derive(Clone)]
struct V8Classes {
    serializer: Obj,
    serializer_proto: Obj,
    deserializer: Obj,
    deserializer_proto: Obj,
    default_serializer: Obj,
    default_deserializer: Obj,
}

fn v8_classes(vm: &mut Vm) -> V8Classes {
    if let Some(c) = V8_CLASSES.with(|c| c.borrow().clone()) {
        return c;
    }
    let (ser, sp) = make_class(vm, "Serializer", 0, serializer_ctor, None);
    let smethods: &[(&str, u32, NativeFn)] = &[
        ("_byte", 1, ser_byte),
        ("writeHeader", 0, ser_write_header),
        ("writeUint32", 1, ser_write_uint32),
        ("writeUint64", 1, ser_write_uint64),
        ("writeDouble", 1, ser_write_double),
        ("writeRawBytes", 1, ser_write_raw_bytes),
        ("_writeString", 1, ser_write_string),
        ("transferArrayBuffer", 0, noop),
        ("_setTreatArrayBufferViewsAsHostObjects", 0, noop),
        ("_writeHostObject", 0, ser_write_host_object),
        ("_ref", 1, ser_ref),
        ("writeValue", 1, ser_write_value),
        ("releaseBuffer", 0, ser_release_buffer),
    ];
    for (n, l, f) in smethods {
        vm.def_method(&sp, n, *l, *f);
    }
    let (de, dp) = make_class(vm, "Deserializer", 1, deserializer_ctor, None);
    let dmethods: &[(&str, u32, NativeFn)] = &[
        ("readHeader", 0, de_read_header),
        ("getWireFormatVersion", 0, de_wire_version),
        ("readUint32", 0, de_read_uint32),
        ("readUint64", 0, de_read_uint64),
        ("readDouble", 0, de_read_double),
        ("readRawBytes", 1, de_read_raw_bytes),
        ("_readString", 0, de_read_string),
        ("transferArrayBuffer", 0, noop),
        ("_readHostObject", 0, de_read_host_object),
        ("readValue", 0, de_read_value),
    ];
    for (n, l, f) in dmethods {
        vm.def_method(&dp, n, *l, *f);
    }
    let (dser, _) = make_class(vm, "DefaultSerializer", 0, serializer_ctor, Some((&ser, &sp)));
    let (dde, _) = make_class(vm, "DefaultDeserializer", 0, deserializer_ctor, Some((&de, &dp)));
    let c = V8Classes { serializer: ser, serializer_proto: sp, deserializer: de, deserializer_proto: dp, default_serializer: dser, default_deserializer: dde };
    V8_CLASSES.with(|s| *s.borrow_mut() = Some(c.clone()));
    c
}

fn noop(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Undefined)
}

// --- Serializer ---

fn serializer_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = v8_classes(vm);
    let o = new_instance(vm, a, &c.serializer_proto)?;
    let this = Value::Obj(o);
    let bytes = Value::Obj(vm.new_array(Vec::new()));
    setp(vm, &this, "_bytes", bytes)?;
    let map_ctor = vm.global.get_own_str("Map").unwrap_or(Value::Undefined);
    let ids = vm.construct(&map_ctor, &[], None)?;
    setp(vm, &this, "_ids", ids)?;
    setp(vm, &this, "_nextId", Value::Num(0.0))?;
    Ok(this)
}

fn push_bytes(vm: &mut Vm, this: &Value, bytes: &[u8]) -> JsResult<()> {
    let arr = getp(vm, this, "_bytes")?;
    if let Value::Obj(ao) = &arr {
        if ao.is_array() {
            for b in bytes {
                crate::vm::array_push_raw(ao, Value::Num(*b as f64));
            }
            return Ok(());
        }
    }
    for b in bytes {
        call_method(vm, &arr, "push", &[Value::Num(*b as f64)])?;
    }
    Ok(())
}

fn ser_byte(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let n = vm.to_int32(&a.arg(0))?;
    push_bytes(vm, &a.this, &[(n & 0xff) as u8])?;
    Ok(Value::Undefined)
}

fn ser_write_header(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    push_bytes(vm, &a.this, &[0xff, 0x0f])?;
    Ok(Value::Undefined)
}

fn u32_bytes(vm: &mut Vm, v: &Value) -> JsResult<[u8; 4]> {
    let n = vm.to_number(v)?;
    let i = crate::builtins::number::to_uint32(n);
    Ok(i.to_le_bytes())
}

fn ser_write_uint32(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = u32_bytes(vm, &a.arg(0))?;
    push_bytes(vm, &a.this, &b)?;
    Ok(Value::Undefined)
}

fn ser_write_uint64(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    // BigInt(v) & 0xffffffffn / >> 32n
    let v = a.arg(0);
    let n: u64 = match &v {
        Value::BigInt(b) => b.to_string_radix(10).parse::<i128>().map(|x| x as u64).unwrap_or(0),
        _ => {
            let f = vm.to_number(&v)?;
            if !f.is_finite() || f.fract() != 0.0 {
                return vm.throw_range(format!("The number {} cannot be converted to a BigInt because it is not an integer", crate::numconv::number_to_string(f)));
            }
            (f as i128) as u64
        }
    };
    let lo = (n & 0xffff_ffff) as u32;
    let hi = (n >> 32) as u32;
    let mut b = lo.to_le_bytes().to_vec();
    b.extend_from_slice(&hi.to_le_bytes());
    push_bytes(vm, &a.this, &b)?;
    Ok(Value::Undefined)
}

fn ser_write_double(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = vm.to_number(&a.arg(0))?;
    push_bytes(vm, &a.this, &f.to_le_bytes())?;
    Ok(Value::Undefined)
}

fn ser_write_raw_bytes(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = a.arg(0);
    let len = getp(vm, &v, "length")?;
    let n = vm.to_number(&len)?;
    let mut out = Vec::new();
    let mut i = 0.0;
    while i < n {
        let x = vm.get_prop_of(&v, &PropKey::from_index(i as u32))?;
        let b = vm.to_int32(&x)?;
        out.push((b & 0xff) as u8);
        i += 1.0;
    }
    push_bytes(vm, &a.this, &out)?;
    Ok(Value::Undefined)
}

fn utf8_of(vm: &mut Vm, v: &Value) -> JsResult<Vec<u8>> {
    let s = vm.to_string(v)?;
    Ok(crate::runtime::encoding::utf16_to_utf8(s.units()))
}

fn write_string_bytes(vm: &mut Vm, this: &Value, s: &Value) -> JsResult<()> {
    let enc = utf8_of(vm, s)?;
    let mut b = (enc.len() as u32).to_le_bytes().to_vec();
    b.extend_from_slice(&enc);
    push_bytes(vm, this, &b)
}

fn ser_write_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    write_string_bytes(vm, &a.this, &a.arg(0))?;
    Ok(Value::Undefined)
}

fn ser_write_host_object(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let e = crate::runtime::nodestream::error_with_code(vm, "Error", "Unserializable host object", "ERR_CANNOT_TRANSFER_OBJECT");
    Err(e)
}

/// _ref(obj): a back-reference if seen before (returns true), else registers the next id.
fn ser_ref_impl(vm: &mut Vm, this: &Value, obj: &Value) -> JsResult<bool> {
    let ids = getp(vm, this, "_ids")?;
    if call_method(vm, &ids, "has", &[obj.clone()])?.truthy() {
        push_bytes(vm, this, &[T_REF])?;
        let id = call_method(vm, &ids, "get", &[obj.clone()])?;
        let b = u32_bytes(vm, &id)?;
        push_bytes(vm, this, &b)?;
        return Ok(true);
    }
    let next = getp(vm, this, "_nextId")?;
    let n = vm.to_number(&next)?;
    setp(vm, this, "_nextId", Value::Num(n + 1.0))?;
    call_method(vm, &ids, "set", &[obj.clone(), Value::Num(n)])?;
    Ok(false)
}

fn ser_ref(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(ser_ref_impl(vm, &a.this, &a.arg(0))?))
}

fn view_index(vm: &mut Vm, v: &Value) -> JsResult<u8> {
    let c = getp(vm, v, "constructor")?;
    let co = match &c {
        Value::Obj(o) => o.clone(),
        _ => return Ok(255),
    };
    // VIEW_CTORS: Int8 Uint8 Uint8Clamped Int16 Uint16 Int32 Uint32 Float32 Float64 BigInt64 BigUint64 DataView
    let map: [(usize, u8); 11] = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6), (8, 7), (9, 8), (10, 9), (11, 10)];
    for (ki, vi) in map {
        if vm.intr.ta_ctors.get(ki).map_or(false, |t| t.ptr_eq(&co)) {
            return Ok(vi);
        }
    }
    if let Some(Value::Obj(dv)) = vm.global.get_own_str("DataView") {
        if dv.ptr_eq(&co) {
            return Ok(11);
        }
    }
    Ok(255)
}

fn write_value(vm: &mut Vm, this: &Value, value: &Value) -> JsResult<()> {
    crate::runtime::nodestream::with_frames(vm, &["writeValue"], |vm| write_value_inner(vm, this, value))
}

fn write_value_inner(vm: &mut Vm, this: &Value, value: &Value) -> JsResult<()> {
    match value {
        Value::Undefined | Value::Empty => return push_bytes(vm, this, &[T_UNDEFINED]),
        Value::Null => return push_bytes(vm, this, &[T_NULL]),
        Value::Bool(b) => return push_bytes(vm, this, &[if *b { T_TRUE } else { T_FALSE }]),
        Value::Num(n) => {
            let mut b = vec![T_NUMBER];
            b.extend_from_slice(&n.to_le_bytes());
            return push_bytes(vm, this, &b);
        }
        Value::Str(_) => {
            push_bytes(vm, this, &[T_STRING])?;
            return write_string_bytes(vm, this, value);
        }
        Value::BigInt(b) => {
            push_bytes(vm, this, &[T_BIGINT])?;
            let s = Value::str(&b.to_string_radix(10));
            return write_string_bytes(vm, this, &s);
        }
        Value::Sym(_) => {
            let e = crate::runtime::nodestream::error_with_code(vm, "Error", "Unsupported value type: symbol", "ERR_CANNOT_TRANSFER_OBJECT");
            return Err(e);
        }
        Value::Obj(_) => {}
    }
    let o = value.as_obj().unwrap().clone();
    if ser_ref_impl(vm, this, value)? {
        return Ok(());
    }
    enum K {
        Array,
        Date(f64),
        RegExp,
        Map,
        Set,
        ArrayBuffer,
        View,
        Other,
    }
    let k = match &o.borrow().kind {
        ObjKind::Array(_) => K::Array,
        ObjKind::Date(t) => K::Date(*t),
        ObjKind::RegExp(_) => K::RegExp,
        ObjKind::Map(_) => K::Map,
        ObjKind::Set(_) => K::Set,
        ObjKind::ArrayBuffer(_) => K::ArrayBuffer,
        ObjKind::TypedArray(_) | ObjKind::DataView(_) => K::View,
        _ => K::Other,
    };
    match k {
        K::Array => {
            push_bytes(vm, this, &[T_ARRAY])?;
            let len = getp(vm, value, "length")?;
            let n = vm.to_number(&len)?;
            let b = u32_bytes(vm, &Value::Num(n))?;
            push_bytes(vm, this, &b)?;
            let mut i = 0.0;
            while i < n {
                let e = vm.get_prop_of(value, &PropKey::from_index(i as u32))?;
                write_value(vm, this, &e)?;
                i += 1.0;
            }
            Ok(())
        }
        K::Date(t) => {
            let mut b = vec![T_DATE];
            b.extend_from_slice(&t.to_le_bytes());
            push_bytes(vm, this, &b)
        }
        K::RegExp => {
            push_bytes(vm, this, &[T_REGEXP])?;
            let src = getp(vm, value, "source")?;
            write_string_bytes(vm, this, &src)?;
            let fl = getp(vm, value, "flags")?;
            write_string_bytes(vm, this, &fl)
        }
        K::Map => {
            push_bytes(vm, this, &[T_MAP])?;
            let size = getp(vm, value, "size")?;
            let b = u32_bytes(vm, &size)?;
            push_bytes(vm, this, &b)?;
            let entries = vm.iterate_to_vec(value)?;
            for e in entries {
                let k = vm.get_prop_of(&e, &PropKey::from_index(0))?;
                let v = vm.get_prop_of(&e, &PropKey::from_index(1))?;
                write_value(vm, this, &k)?;
                write_value(vm, this, &v)?;
            }
            Ok(())
        }
        K::Set => {
            push_bytes(vm, this, &[T_SET])?;
            let size = getp(vm, value, "size")?;
            let b = u32_bytes(vm, &size)?;
            push_bytes(vm, this, &b)?;
            let items = vm.iterate_to_vec(value)?;
            for v in items {
                write_value(vm, this, &v)?;
            }
            Ok(())
        }
        K::ArrayBuffer => {
            let bytes = crate::builtins::typedarray::ta_bytes(&o);
            let mut b = vec![T_ARRAYBUFFER];
            b.extend_from_slice(&(bytes.len() as u32).to_le_bytes());
            b.extend_from_slice(&bytes);
            push_bytes(vm, this, &b)
        }
        K::View => {
            if crate::runtime::buffer::is_buffer(vm, value) {
                let bytes = crate::builtins::typedarray::ta_bytes(&o);
                let mut b = vec![T_BUFFER];
                b.extend_from_slice(&(bytes.len() as u32).to_le_bytes());
                b.extend_from_slice(&bytes);
                return push_bytes(vm, this, &b);
            }
            let idx = view_index(vm, value)?;
            let bytes = crate::builtins::typedarray::ta_bytes(&o);
            let mut b = vec![T_TYPEDARRAY, idx];
            b.extend_from_slice(&(bytes.len() as u32).to_le_bytes());
            b.extend_from_slice(&bytes);
            push_bytes(vm, this, &b)
        }
        K::Other => {
            push_bytes(vm, this, &[T_OBJECT])?;
            let keys = vm.enumerable_own_keys(&o)?;
            let b = (keys.len() as u32).to_le_bytes();
            push_bytes(vm, this, &b)?;
            for k in keys {
                let kv = Value::Str(k.clone());
                write_string_bytes(vm, this, &kv)?;
                let v = vm.get(&o, &PropKey::Str(k), value)?;
                write_value(vm, this, &v)?;
            }
            Ok(())
        }
    }
}

fn ser_write_value(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    write_value(vm, &a.this, &a.arg(0))?;
    Ok(Value::Undefined)
}

fn ser_release_buffer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let arr = getp(vm, &a.this, "_bytes")?;
    let vals = crate::builtins::array::array_like_to_vec(vm, &arr)?;
    let mut bytes = Vec::with_capacity(vals.len());
    for v in vals {
        let n = vm.to_int32(&v)?;
        bytes.push((n & 0xff) as u8);
    }
    new_buffer(vm, bytes)
}

// --- Deserializer ---

fn deserializer_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = v8_classes(vm);
    let o = new_instance(vm, a, &c.deserializer_proto)?;
    let this = Value::Obj(o);
    let buffer = a.arg(0);
    let u8c = Value::Obj(vm.intr.ta_ctors[1].clone());
    let buf = if vm.instance_of(&buffer, &u8c)? { buffer } else { vm.construct(&u8c, &[buffer], None)? };
    setp(vm, &this, "_buf", buf.clone())?;
    let ab = getp(vm, &buf, "buffer")?;
    let off = getp(vm, &buf, "byteOffset")?;
    let len = getp(vm, &buf, "byteLength")?;
    let dv_ctor = vm.global.get_own_str("DataView").unwrap_or(Value::Undefined);
    let view = vm.construct(&dv_ctor, &[ab, off, len], None)?;
    setp(vm, &this, "_view", view)?;
    setp(vm, &this, "_pos", Value::Num(0.0))?;
    let objs = Value::Obj(vm.new_array(Vec::new()));
    setp(vm, &this, "_objs", objs)?;
    Ok(this)
}

fn de_pos(vm: &mut Vm, this: &Value) -> JsResult<f64> {
    let p = getp(vm, this, "_pos")?;
    vm.to_number(&p)
}

fn de_set_pos(vm: &mut Vm, this: &Value, p: f64) -> JsResult<()> {
    setp(vm, this, "_pos", Value::Num(p))
}

fn de_buf_bytes(vm: &mut Vm, this: &Value) -> JsResult<Vec<u8>> {
    let b = getp(vm, this, "_buf")?;
    match &b {
        Value::Obj(o) => Ok(crate::builtins::typedarray::ta_bytes(o)),
        _ => Ok(Vec::new()),
    }
}

fn de_read_header(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = de_pos(vm, &a.this)?;
    de_set_pos(vm, &a.this, p + 2.0)?;
    Ok(Value::Num(15.0))
}

fn de_wire_version(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Num(15.0))
}

fn out_of_bounds(vm: &mut Vm) -> Value {
    vm.make_error("RangeError", "Offset is outside the bounds of the DataView")
}

fn read_fixed<const N: usize>(vm: &mut Vm, this: &Value) -> JsResult<[u8; N]> {
    let p = de_pos(vm, this)?;
    let bytes = de_buf_bytes(vm, this)?;
    let start = p as usize;
    if p < 0.0 || start + N > bytes.len() {
        return Err(out_of_bounds(vm));
    }
    let mut out = [0u8; N];
    out.copy_from_slice(&bytes[start..start + N]);
    de_set_pos(vm, this, p + N as f64)?;
    Ok(out)
}

fn read_u32(vm: &mut Vm, this: &Value) -> JsResult<u32> {
    Ok(u32::from_le_bytes(read_fixed::<4>(vm, this)?))
}

fn de_read_uint32(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Num(read_u32(vm, &a.this)? as f64))
}

fn de_read_uint64(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let lo = read_u32(vm, &a.this)? as u64;
    let hi = read_u32(vm, &a.this)? as u64;
    Ok(Value::Num(((hi << 32) | lo) as f64))
}

fn de_read_double(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Num(f64::from_le_bytes(read_fixed::<8>(vm, &a.this)?)))
}

/// readRawBytes(len): a subarray view of the input
fn read_raw(vm: &mut Vm, this: &Value, len: f64) -> JsResult<Value> {
    let p = de_pos(vm, this)?;
    let buf = getp(vm, this, "_buf")?;
    let out = call_method(vm, &buf, "subarray", &[Value::Num(p), Value::Num(p + len)])?;
    de_set_pos(vm, this, p + len)?;
    Ok(out)
}

fn de_read_raw_bytes(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let n = vm.to_number(&a.arg(0))?;
    read_raw(vm, &a.this, n)
}

fn read_string(vm: &mut Vm, this: &Value) -> JsResult<Value> {
    let len = read_u32(vm, this)? as f64;
    let raw = read_raw(vm, this, len)?;
    let bytes = match &raw {
        Value::Obj(o) => crate::builtins::typedarray::ta_bytes(o),
        _ => Vec::new(),
    };
    Ok(Value::Str(JsStr::from_str(&String::from_utf8_lossy(&bytes))))
}

fn de_read_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    read_string(vm, &a.this)
}

fn de_read_host_object(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    vm.throw_error("Error", "Unserializable host object")
}

/// `view.slice().buffer`: a new ArrayBuffer holding a copy of the view's bytes.
fn fresh_array_buffer(vm: &mut Vm, view: &Value) -> Value {
    let bytes = match view {
        Value::Obj(o) => crate::builtins::typedarray::ta_bytes(o),
        _ => Vec::new(),
    };
    Value::Obj(crate::builtins::typedarray::new_array_buffer(vm, bytes))
}

fn push_obj(vm: &mut Vm, this: &Value, v: &Value) -> JsResult<()> {
    let objs = getp(vm, this, "_objs")?;
    call_method(vm, &objs, "push", &[v.clone()])?;
    Ok(())
}

fn read_value(vm: &mut Vm, this: &Value) -> JsResult<Value> {
    crate::runtime::nodestream::with_frames(vm, &["readValue"], |vm| read_value_inner(vm, this))
}

fn read_value_inner(vm: &mut Vm, this: &Value) -> JsResult<Value> {
    let p = de_pos(vm, this)?;
    let bytes = de_buf_bytes(vm, this)?;
    de_set_pos(vm, this, p + 1.0)?;
    let tag = match bytes.get(p as usize) {
        Some(t) => *t as i64,
        None => -1,
    };
    let g = |vm: &mut Vm, n: &str| vm.global.get_own_str(n).unwrap_or(Value::Undefined);
    match tag {
        0 => Ok(Value::Undefined),
        1 => Ok(Value::Null),
        2 => Ok(Value::Bool(true)),
        3 => Ok(Value::Bool(false)),
        4 => Ok(Value::Num(f64::from_le_bytes(read_fixed::<8>(vm, this)?))),
        5 => read_string(vm, this),
        6 => {
            let s = read_string(vm, this)?;
            let bi = g(vm, "BigInt");
            vm.call(&bi, Value::Undefined, &[s])
        }
        16 => {
            let id = read_u32(vm, this)?;
            let objs = getp(vm, this, "_objs")?;
            vm.get_prop_of(&objs, &PropKey::from_index(id))
        }
        7 => {
            let n = read_u32(vm, this)?;
            let arr = Value::Obj(vm.new_array(Vec::new()));
            push_obj(vm, this, &arr)?;
            for _ in 0..n {
                let v = read_value(vm, this)?;
                call_method(vm, &arr, "push", &[v])?;
            }
            Ok(arr)
        }
        8 => {
            let n = read_u32(vm, this)?;
            let obj = Value::Obj(vm.new_object());
            push_obj(vm, this, &obj)?;
            for _ in 0..n {
                let k = read_string(vm, this)?;
                let v = read_value(vm, this)?;
                let pk = vm.to_property_key(&k)?;
                vm.set_prop_of(&obj, pk, v, true)?;
            }
            Ok(obj)
        }
        9 => {
            let n = read_u32(vm, this)?;
            let mc = g(vm, "Map");
            let map = vm.construct(&mc, &[], None)?;
            push_obj(vm, this, &map)?;
            for _ in 0..n {
                let k = read_value(vm, this)?;
                let v = read_value(vm, this)?;
                call_method(vm, &map, "set", &[k, v])?;
            }
            Ok(map)
        }
        10 => {
            let n = read_u32(vm, this)?;
            let sc = g(vm, "Set");
            let set = vm.construct(&sc, &[], None)?;
            push_obj(vm, this, &set)?;
            for _ in 0..n {
                let v = read_value(vm, this)?;
                call_method(vm, &set, "add", &[v])?;
            }
            Ok(set)
        }
        11 => {
            let t = f64::from_le_bytes(read_fixed::<8>(vm, this)?);
            let dc = g(vm, "Date");
            let d = vm.construct(&dc, &[Value::Num(t)], None)?;
            push_obj(vm, this, &d)?;
            Ok(d)
        }
        12 => {
            let src = read_string(vm, this)?;
            let fl = read_string(vm, this)?;
            let rc = g(vm, "RegExp");
            let re = vm.construct(&rc, &[src, fl], None)?;
            push_obj(vm, this, &re)?;
            Ok(re)
        }
        13 => {
            let n = read_u32(vm, this)? as f64;
            let raw = read_raw(vm, this, n)?;
            let ab = fresh_array_buffer(vm, &raw);
            push_obj(vm, this, &ab)?;
            Ok(ab)
        }
        15 => {
            let n = read_u32(vm, this)? as f64;
            let raw = read_raw(vm, this, n)?;
            let b = crate::runtime::nodestream::buffer_call(vm, "from", &[raw])?;
            push_obj(vm, this, &b)?;
            Ok(b)
        }
        14 => {
            let pk = de_pos(vm, this)?;
            de_set_pos(vm, this, pk + 1.0)?;
            let kind = bytes.get(pk as usize).copied().unwrap_or(255);
            let n = read_u32(vm, this)? as f64;
            let raw = read_raw(vm, this, n)?;
            let ab = fresh_array_buffer(vm, &raw);
            let map: [usize; 11] = [0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 11];
            let view = if kind == 11 {
                let dv = g(vm, "DataView");
                vm.construct(&dv, &[ab], None)?
            } else if (kind as usize) < map.len() {
                let c = Value::Obj(vm.intr.ta_ctors[map[kind as usize]].clone());
                vm.construct(&c, &[ab], None)?
            } else {
                // VIEW_CTORS[kind] is undefined: `new undefined(...)`
                return vm.throw_type("undefined is not a constructor");
            };
            push_obj(vm, this, &view)?;
            Ok(view)
        }
        t => {
            let s = if t < 0 { "undefined".to_string() } else { t.to_string() };
            vm.throw_error("Error", format!("v8.deserialize: unknown tag {}", s))
        }
    }
}

fn de_read_value(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    read_value(vm, &a.this)
}

// --- module functions ---

fn v8_serialize(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = v8_classes(vm);
    let s = vm.construct(&Value::Obj(c.default_serializer), &[], None)?;
    call_method(vm, &s, "writeHeader", &[])?;
    call_method(vm, &s, "writeValue", &[a.arg(0)])?;
    call_method(vm, &s, "releaseBuffer", &[])
}

fn v8_deserialize(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = v8_classes(vm);
    let d = vm.construct(&Value::Obj(c.default_deserializer), &[a.arg(0)], None)?;
    call_method(vm, &d, "readHeader", &[])?;
    call_method(vm, &d, "readValue", &[])
}

fn v8_heap_stats(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let z = Value::Num(0.0);
    Ok(Value::Obj(vm.obj_from(vec![
        ("total_heap_size", z.clone()),
        ("total_heap_size_executable", z.clone()),
        ("total_physical_size", z.clone()),
        ("total_available_size", Value::Num(HEAP_LIMIT)),
        ("used_heap_size", z.clone()),
        ("heap_size_limit", Value::Num(HEAP_LIMIT)),
        ("malloced_memory", z.clone()),
        ("peak_malloced_memory", z.clone()),
        ("does_zap_garbage", z.clone()),
        ("number_of_native_contexts", Value::Num(1.0)),
        ("number_of_detached_contexts", z.clone()),
        ("total_global_handles_size", z.clone()),
        ("used_global_handles_size", z.clone()),
        ("external_memory", z),
    ])))
}

const HEAP_SPACES: &[&str] = &[
    "read_only_space",
    "new_space",
    "old_space",
    "code_space",
    "shared_space",
    "trusted_space",
    "new_large_object_space",
    "large_object_space",
    "code_large_object_space",
    "shared_large_object_space",
    "trusted_large_object_space",
];

fn v8_heap_space_stats(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let mut out = Vec::new();
    for n in HEAP_SPACES {
        let z = Value::Num(0.0);
        out.push(Value::Obj(vm.obj_from(vec![
            ("space_name", Value::str(n)),
            ("space_size", z.clone()),
            ("space_used_size", z.clone()),
            ("space_available_size", z.clone()),
            ("physical_space_size", z),
        ])));
    }
    Ok(Value::Obj(vm.new_array(out)))
}

fn v8_heap_code_stats(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let z = Value::Num(0.0);
    Ok(Value::Obj(vm.obj_from(vec![
        ("code_and_metadata_size", z.clone()),
        ("bytecode_and_metadata_size", z.clone()),
        ("external_script_source_size", z.clone()),
        ("cpu_profiler_metadata_size", z),
    ])))
}

fn v8_cpp_heap_stats(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let z = Value::Num(0.0);
    let a1 = Value::Obj(vm.new_array(Vec::new()));
    let a2 = Value::Obj(vm.new_array(Vec::new()));
    Ok(Value::Obj(vm.obj_from(vec![
        ("committed_size_bytes", z.clone()),
        ("resident_size_bytes", z.clone()),
        ("used_size_bytes", z),
        ("space_statistics", a1),
        ("type_names", a2),
        ("detail_level", Value::str("brief")),
    ])))
}

fn v8_one_byte(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match a.arg(0) {
        Value::Str(s) => Ok(Value::Bool(s.units().iter().all(|&u| u <= 0xff))),
        _ => {
            let e = crate::runtime::nodestream::error_with_code(vm, "TypeError", "The \"content\" argument must be of type string.", "ERR_INVALID_ARG_TYPE");
            Err(e)
        }
    }
}

fn v8_cached_tag(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Num(0x6c756d65 as f64))
}

fn gc_profiler_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let fb = vm.intr.object_proto.clone();
    let o = new_instance(vm, a, &fb)?;
    Ok(Value::Obj(o))
}

fn now_ms() -> f64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_millis() as f64).unwrap_or(0.0)
}

fn gc_start(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    setp(vm, &a.this, "_start", Value::Num(now_ms()))?;
    Ok(Value::Undefined)
}

fn gc_stop(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = getp(vm, &a.this, "_start")?;
    let start = if s.truthy() { s } else { Value::Num(now_ms()) };
    let stats = Value::Obj(vm.new_array(Vec::new()));
    Ok(Value::Obj(vm.obj_from(vec![("version", Value::Num(1.0)), ("startTime", start), ("statistics", stats), ("endTime", Value::Num(now_ms()))])))
}

fn noop_stop(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Obj(vm.native_fn("noopStop", 0, noop)))
}

fn return_false(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(false))
}

fn snapshot_unsupported(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    vm.throw_error("Error", "node:v8 heap snapshots is not supported in lumen")
}

fn query_unsupported(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    vm.throw_error("Error", "node:v8 queryObjects is not supported in lumen")
}

fn create_v8(vm: &mut Vm) -> Value {
    let c = v8_classes(vm);
    let o = vm.new_object();
    let put = |o: &Obj, k: &str, v: Value| o.set_prop(key(k), v, WEC);
    let f = vm.native_fn("serialize", 1, v8_serialize_f);
    put(&o, "serialize", Value::Obj(f));
    let f = vm.native_fn("deserialize", 1, v8_deserialize);
    put(&o, "deserialize", Value::Obj(f));
    put(&o, "Serializer", Value::Obj(c.serializer));
    put(&o, "Deserializer", Value::Obj(c.deserializer));
    put(&o, "DefaultSerializer", Value::Obj(c.default_serializer));
    put(&o, "DefaultDeserializer", Value::Obj(c.default_deserializer));
    let fns: &[(&str, u32, NativeFn)] = &[
        ("getHeapStatistics", 0, v8_heap_stats),
        ("getHeapSpaceStatistics", 0, v8_heap_space_stats),
        ("getHeapCodeStatistics", 0, v8_heap_code_stats),
        ("getCppHeapStatistics", 0, v8_cpp_heap_stats),
        ("isStringOneByteRepresentation", 1, v8_one_byte_f),
        ("cachedDataVersionTag", 0, v8_cached_tag),
    ];
    for (n, l, f) in fns {
        let fo = vm.native_fn(n, *l, *f);
        put(&o, n, Value::Obj(fo));
    }
    let (gc, gp) = make_class(vm, "GCProfiler", 0, gc_profiler_ctor, None);
    vm.def_method(&gp, "start", 0, gc_start);
    vm.def_method(&gp, "stop", 0, gc_stop);
    put(&o, "GCProfiler", Value::Obj(gc));
    let ph = vm.new_object();
    for n in ["createHook", "onInit", "onBefore", "onAfter", "onSettled"] {
        let f = vm.native_fn(n, 0, noop_stop);
        put(&ph, n, Value::Obj(f));
    }
    put(&o, "promiseHooks", Value::Obj(ph));
    let ss = vm.new_object();
    for n in ["addDeserializeCallback", "addSerializeCallback", "setDeserializeMainFunction"] {
        let f = vm.native_fn(n, 0, noop);
        put(&ss, n, Value::Obj(f));
    }
    let f = vm.native_fn("isBuildingSnapshot", 0, return_false);
    put(&ss, "isBuildingSnapshot", Value::Obj(f));
    put(&o, "startupSnapshot", Value::Obj(ss));
    for n in ["setFlagsFromString", "setHeapSnapshotNearHeapLimit", "takeCoverage", "stopCoverage"] {
        let f = vm.native_fn(n, 0, noop);
        put(&o, n, Value::Obj(f));
    }
    let f = vm.native_fn("", 0, query_unsupported);
    put(&o, "queryObjects", Value::Obj(f));
    let f = vm.native_fn("", 0, snapshot_unsupported);
    put(&o, "getHeapSnapshot", Value::Obj(f));
    let f = vm.native_fn("", 0, snapshot_unsupported);
    put(&o, "writeHeapSnapshot", Value::Obj(f));
    let _ = plain_fn;
    Value::Obj(o)
}

#[allow(unused_variables)]
#[allow(dead_code)]
pub fn setup(vm: &mut Vm) {}

pub fn create_module(vm: &mut Vm, name: &str) -> Value {
    match name {
        "vm" => create_vm(vm),
        _ => create_v8(vm),
    }
}

// the reference's JS frames for errors raised synchronously by these entry points
crate::framed_native!(vm_run_in_context_f, ["runInContext"], vm_run_in_context);
crate::framed_native!(script_ctor_f, ["Script"], script_ctor);
crate::framed_native!(script_run_in_context_f, ["runInContext"], script_run_in_context);
crate::framed_native!(v8_one_byte_f, ["isStringOneByteRepresentation"], v8_one_byte);
crate::framed_native!(v8_serialize_f, ["serialize"], v8_serialize);
