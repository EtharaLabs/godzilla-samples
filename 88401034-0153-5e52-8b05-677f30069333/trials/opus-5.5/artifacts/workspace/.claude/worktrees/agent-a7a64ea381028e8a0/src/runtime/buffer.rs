// node:buffer — Buffer (a Uint8Array subclass) and string_decoder.

use crate::builtins::typedarray::{create_typed_array, ta_bytes};
use crate::object::*;
use crate::runtime::encoding as enc;
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::cell::RefCell;
use std::rc::Rc;

thread_local! {
    static BUFFER_PROTO: RefCell<Option<Obj>> = RefCell::new(None);
    static BUFFER_CTOR: RefCell<Option<Obj>> = RefCell::new(None);
}

pub fn buffer_proto() -> Option<Obj> {
    BUFFER_PROTO.with(|b| b.borrow().clone())
}

pub fn is_buffer_proto(_vm: &Vm, p: &Obj) -> bool {
    BUFFER_PROTO.with(|b| b.borrow().as_ref().map_or(false, |bp| bp.ptr_eq(p)))
}

pub fn is_buffer(_vm: &mut Vm, v: &Value) -> bool {
    match v {
        Value::Obj(o) => {
            let p = o.borrow().proto.clone();
            matches!(o.borrow().kind, ObjKind::TypedArray(_)) && p.map_or(false, |p| BUFFER_PROTO.with(|b| b.borrow().as_ref().map_or(false, |bp| bp.ptr_eq(&p))))
        }
        _ => false,
    }
}

pub fn setup_global(vm: &mut Vm) {
    let m = create_module(vm);
    if let Value::Obj(mo) = &m {
        if let Some(b) = mo.get_own_str("Buffer") {
            vm.def_global("Buffer", b);
        }
    }
    vm.host.builtin_cache.insert("buffer".into(), m);
}

pub fn create_module(vm: &mut Vm) -> Value {
    if let Some(v) = vm.host.builtin_cache.get("buffer") {
        return v.clone();
    }
    let u8p = vm.intr.ta_protos[1].clone();
    let u8c = vm.intr.ta_ctors[1].clone();
    let proto = Obj::new(Some(u8p), ObjKind::Ordinary);
    let ctor = vm.native_ctor("Buffer", 2, buffer_ctor, &proto);
    ctor.borrow_mut().proto = Some(u8c);
    BUFFER_PROTO.with(|b| *b.borrow_mut() = Some(proto.clone()));
    BUFFER_CTOR.with(|b| *b.borrow_mut() = Some(ctor.clone()));
    let statics: &[(&str, u32, NativeFn)] = &[
        ("from", 3, buffer_from),
        ("alloc", 3, buffer_alloc),
        ("allocUnsafe", 1, buffer_alloc_unsafe),
        ("allocUnsafeSlow", 1, buffer_alloc_unsafe),
        ("isBuffer", 1, |vm, a| Ok(Value::Bool(is_buffer(vm, &a.arg(0))))),
        ("isEncoding", 1, |vm, a| {
            let s = match a.arg(0) {
                Value::Str(s) => s.to_rust_string(),
                _ => return Ok(Value::Bool(false)),
            };
            let _ = vm;
            Ok(Value::Bool(norm_encoding(&s).is_some()))
        }),
        ("byteLength", 2, byte_length),
        ("concat", 2, buffer_concat),
        ("compare", 2, buffer_compare_static),
    ];
    for (n, l, f) in statics {
        vm.def_method(&ctor, n, *l, *f);
    }
    ctor.set_prop(PropKey::from_str("poolSize"), Value::Num(8192.0), WEC);
    let methods: &[(&str, u32, NativeFn)] = &[
        ("toString", 3, buf_to_string),
        ("toLocaleString", 3, buf_to_string),
        ("write", 4, buf_write),
        ("toJSON", 0, buf_to_json),
        ("equals", 1, buf_equals),
        ("compare", 5, buf_compare),
        ("slice", 2, buf_subarray),
        ("subarray", 2, buf_subarray),
        ("indexOf", 3, |vm, a| buf_index_of(vm, a, false, false)),
        ("lastIndexOf", 3, |vm, a| buf_index_of(vm, a, true, false)),
        ("includes", 3, |vm, a| buf_index_of(vm, a, false, true)),
        ("fill", 4, buf_fill),
        ("copy", 4, buf_copy),
        ("swap16", 0, |vm, a| buf_swap(vm, a, 2)),
        ("swap32", 0, |vm, a| buf_swap(vm, a, 4)),
        ("swap64", 0, |vm, a| buf_swap(vm, a, 8)),
        ("inspect", 0, |vm, a| Ok(Value::str(&crate::runtime::util::inspect_value(vm, &a.this, 2)?))),
    ];
    for (n, l, f) in methods {
        vm.def_method(&proto, n, *l, *f);
    }
    // numeric read/write methods
    let rw: &[(&str, u8, usize, bool, bool)] = &[
        // name, kind(0 uint,1 int,2 float,3 double,4 bigint,5 biguint), size, little, is_write
        ("readUInt8", 0, 1, true, false),
        ("readUint8", 0, 1, true, false),
        ("readInt8", 1, 1, true, false),
        ("readUInt16LE", 0, 2, true, false),
        ("readUint16LE", 0, 2, true, false),
        ("readUInt16BE", 0, 2, false, false),
        ("readUint16BE", 0, 2, false, false),
        ("readInt16LE", 1, 2, true, false),
        ("readInt16BE", 1, 2, false, false),
        ("readUInt32LE", 0, 4, true, false),
        ("readUint32LE", 0, 4, true, false),
        ("readUInt32BE", 0, 4, false, false),
        ("readUint32BE", 0, 4, false, false),
        ("readInt32LE", 1, 4, true, false),
        ("readInt32BE", 1, 4, false, false),
        ("readFloatLE", 2, 4, true, false),
        ("readFloatBE", 2, 4, false, false),
        ("readDoubleLE", 3, 8, true, false),
        ("readDoubleBE", 3, 8, false, false),
        ("readBigInt64LE", 4, 8, true, false),
        ("readBigInt64BE", 4, 8, false, false),
        ("readBigUInt64LE", 5, 8, true, false),
        ("readBigUint64LE", 5, 8, true, false),
        ("readBigUInt64BE", 5, 8, false, false),
        ("readBigUint64BE", 5, 8, false, false),
        ("writeUInt8", 0, 1, true, true),
        ("writeUint8", 0, 1, true, true),
        ("writeInt8", 1, 1, true, true),
        ("writeUInt16LE", 0, 2, true, true),
        ("writeUint16LE", 0, 2, true, true),
        ("writeUInt16BE", 0, 2, false, true),
        ("writeUint16BE", 0, 2, false, true),
        ("writeInt16LE", 1, 2, true, true),
        ("writeInt16BE", 1, 2, false, true),
        ("writeUInt32LE", 0, 4, true, true),
        ("writeUint32LE", 0, 4, true, true),
        ("writeUInt32BE", 0, 4, false, true),
        ("writeUint32BE", 0, 4, false, true),
        ("writeInt32LE", 1, 4, true, true),
        ("writeInt32BE", 1, 4, false, true),
        ("writeFloatLE", 2, 4, true, true),
        ("writeFloatBE", 2, 4, false, true),
        ("writeDoubleLE", 3, 8, true, true),
        ("writeDoubleBE", 3, 8, false, true),
        ("writeBigInt64LE", 4, 8, true, true),
        ("writeBigInt64BE", 4, 8, false, true),
        ("writeBigUInt64LE", 5, 8, true, true),
        ("writeBigUint64LE", 5, 8, true, true),
        ("writeBigUInt64BE", 5, 8, false, true),
        ("writeBigUint64BE", 5, 8, false, true),
    ];
    for (n, kind, size, little, write) in rw {
        let f = vm.native_closure(n, if *write { 2 } else { 1 }, if *write { buf_write_num } else { buf_read_num }, vec![Value::Num(*kind as f64), Value::Num(*size as f64), Value::Bool(*little)]);
        proto.set_prop(PropKey::from_str(n), Value::Obj(f), WC);
    }
    for (n, signed, little, write) in [
        ("readUIntLE", false, true, false),
        ("readUintLE", false, true, false),
        ("readUIntBE", false, false, false),
        ("readUintBE", false, false, false),
        ("readIntLE", true, true, false),
        ("readIntBE", true, false, false),
        ("writeUIntLE", false, true, true),
        ("writeUintLE", false, true, true),
        ("writeUIntBE", false, false, true),
        ("writeUintBE", false, false, true),
        ("writeIntLE", true, true, true),
        ("writeIntBE", true, false, true),
    ] {
        let f = vm.native_closure(n, 2, if write { buf_write_var } else { buf_read_var }, vec![Value::Bool(signed), Value::Bool(little)]);
        proto.set_prop(PropKey::from_str(n), Value::Obj(f), WC);
    }
    let m = vm.new_object();
    m.set_str("Buffer", Value::Obj(ctor), WEC);
    m.set_str("kMaxLength", Value::Num(4294967296.0), WEC);
    m.set_str("kStringMaxLength", Value::Num(536870888.0), WEC);
    let constants = vm.obj_from(vec![("MAX_LENGTH", Value::Num(4294967296.0)), ("MAX_STRING_LENGTH", Value::Num(536870888.0))]);
    m.set_str("constants", Value::Obj(constants), WEC);
    m.set_str("INSPECT_MAX_BYTES", Value::Num(50.0), WEC);
    for n in ["atob", "btoa", "Blob", "File"] {
        if let Some(v) = vm.global.get_own_str(n) {
            m.set_str(n, v, WEC);
        }
    }
    vm.def_method(&m, "isUtf8", 1, |_vm, a| {
        let b = match &a.arg(0) {
            Value::Obj(o) => ta_bytes(o),
            _ => Vec::new(),
        };
        Ok(Value::Bool(std::str::from_utf8(&b).is_ok()))
    });
    vm.def_method(&m, "isAscii", 1, |_vm, a| {
        let b = match &a.arg(0) {
            Value::Obj(o) => ta_bytes(o),
            _ => Vec::new(),
        };
        Ok(Value::Bool(b.iter().all(|x| *x < 128)))
    });
    let mv = Value::Obj(m);
    vm.host.builtin_cache.insert("buffer".into(), mv.clone());
    mv
}

pub fn norm_encoding(s: &str) -> Option<&'static str> {
    Some(match s.to_ascii_lowercase().as_str() {
        "utf8" | "utf-8" => "utf8",
        "hex" => "hex",
        "base64" => "base64",
        "base64url" => "base64url",
        "latin1" | "binary" => "latin1",
        "ascii" => "ascii",
        "ucs2" | "ucs-2" | "utf16le" | "utf-16le" => "utf16le",
        _ => return None,
    })
}

fn encoding_arg(vm: &mut Vm, v: &Value) -> JsResult<&'static str> {
    match v {
        Value::Undefined | Value::Null => Ok("utf8"),
        Value::Str(s) => {
            let st = s.to_rust_string();
            match norm_encoding(&st) {
                Some(e) => Ok(e),
                None => {
                    let e = vm.make_error("TypeError", &format!("Unknown encoding: {}", st));
                    if let Value::Obj(o) = &e {
                        o.set_prop(PropKey::from_str("code"), Value::str("ERR_UNKNOWN_ENCODING"), WC);
                    }
                    Err(e)
                }
            }
        }
        _ => Ok("utf8"),
    }
}

pub fn encode_string(s: &JsStr, encoding: &str) -> Vec<u8> {
    match encoding {
        "hex" => enc::hex_decode_lenient(&s.to_rust_string()),
        "base64" | "base64url" => enc::base64_decode_lenient(&s.to_rust_string()),
        "latin1" | "ascii" => s.units().iter().map(|&c| c as u8).collect(),
        "utf16le" => {
            let mut v = Vec::with_capacity(s.len() * 2);
            for &c in s.units() {
                v.push(c as u8);
                v.push((c >> 8) as u8);
            }
            v
        }
        _ => enc::utf16_to_utf8(s.units()),
    }
}

pub fn decode_bytes(b: &[u8], encoding: &str) -> JsStr {
    match encoding {
        "hex" => JsStr::from_str(&enc::hex_encode(b)),
        "base64" => JsStr::from_str(&enc::base64_encode(b, false)),
        "base64url" => {
            let s = enc::base64_encode(b, true);
            JsStr::from_str(s.trim_end_matches('='))
        }
        "latin1" => JsStr::from_units(enc::latin1_to_utf16(b)),
        "ascii" => JsStr::from_units(b.iter().map(|&x| (x & 0x7f) as u16).collect()),
        "utf16le" => {
            let v: Vec<u16> = b.chunks(2).filter(|c| c.len() == 2).map(|c| c[0] as u16 | ((c[1] as u16) << 8)).collect();
            JsStr::from_units(v)
        }
        _ => JsStr::from_units(enc::utf8_to_utf16(b)),
    }
}

pub fn new_buffer(vm: &mut Vm, bytes: Vec<u8>) -> JsResult<Obj> {
    if bytes.len() > crate::builtins::typedarray::MAX_TA_LENGTH {
        return vm.throw_range("Invalid typed array length");
    }
    let t = crate::builtins::typedarray::typed_array_from_bytes(vm, bytes);
    if let Some(p) = buffer_proto() {
        t.borrow_mut().proto = Some(p);
    }
    Ok(t)
}

pub fn new_buffer_value(vm: &mut Vm, bytes: Vec<u8>) -> JsResult<Value> {
    Ok(Value::Obj(new_buffer(vm, bytes)?))
}

fn buffer_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let first = a.arg(0);
    match &first {
        Value::Num(n) => {
            let n = *n as usize;
            new_buffer_value(vm, vec![0; n])
        }
        _ => buffer_from(vm, a),
    }
}

/// bytes of a Buffer/TypedArray/ArrayBuffer/DataView/string
pub fn bytes_of(vm: &mut Vm, v: &Value) -> JsResult<Vec<u8>> {
    match v {
        Value::Obj(o) => {
            let is_bin = matches!(o.borrow().kind, ObjKind::TypedArray(_) | ObjKind::ArrayBuffer(_) | ObjKind::DataView(_));
            if is_bin {
                return Ok(ta_bytes(o));
            }
            let vals = crate::builtins::array::array_like_to_vec(vm, v)?;
            let mut out = Vec::with_capacity(vals.len());
            for x in vals {
                out.push(crate::builtins::number::to_uint32(vm.to_number(&x)?) as u8);
            }
            Ok(out)
        }
        Value::Str(s) => Ok(enc::utf16_to_utf8(s.units())),
        _ => vm.throw_type("argument must be a Buffer, TypedArray, or string"),
    }
}

fn buffer_from(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = a.arg(0);
    match &v {
        Value::Str(s) => {
            let e = encoding_arg(vm, &a.arg(1))?;
            let b = encode_string(s, e);
            new_buffer_value(vm, b)
        }
        Value::Obj(o) => {
            let ab = match &o.borrow().kind {
                ObjKind::ArrayBuffer(b) => Some(b.clone()),
                _ => None,
            };
            if let Some(buf) = ab {
                // shares memory
                let blen = buf.borrow().bytes.len();
                let off = if a.arg(1).is_undefined() { 0 } else { vm.to_index(&a.arg(1))? };
                if off > blen {
                    return vm.throw_range("\"offset\" is outside of buffer bounds");
                }
                let len = if a.arg(2).is_undefined() { blen - off } else { vm.to_index(&a.arg(2))? };
                if off + len > blen {
                    return vm.throw_range("\"length\" is outside of buffer bounds");
                }
                let p = buffer_proto().unwrap();
                return Ok(Value::Obj(Obj::with_class(
                    Some(p),
                    ObjKind::TypedArray(Box::new(TypedArrayData { kind: TAKind::Uint8, buffer: o.clone(), buf, offset: off, length: Some(len) })),
                    "Uint8Array",
                )));
            }
            // valueOf / Symbol.toPrimitive objects returning strings
            let is_plain = !matches!(o.borrow().kind, ObjKind::TypedArray(_) | ObjKind::Array(_) | ObjKind::DataView(_));
            if is_plain {
                let tp = vm.get(o, &PropKey::Sym(vm.intr.sym_to_primitive.clone()), &v)?;
                if tp.is_callable() {
                    let p = vm.call(&tp, v.clone(), &[Value::str("string")])?;
                    if let Value::Str(s) = p {
                        let e = encoding_arg(vm, &a.arg(1))?;
                        return new_buffer_value(vm, encode_string(&s, e));
                    }
                }
                let ty = vm.get_str(o, "type")?;
                let data = vm.get_str(o, "data")?;
                if matches!(&ty, Value::Str(s) if s.eq_str("Buffer")) && data.is_object() {
                    let b = bytes_of(vm, &data)?;
                    return new_buffer_value(vm, b);
                }
                let len = vm.get_str(o, "length")?;
                if len.is_undefined() {
                    let d = crate::runtime::util::describe_received(vm, &v);
                    return vm.throw_type(format!("The first argument must be of type string or an instance of Buffer, ArrayBuffer, or Array or an Array-like Object. Received {}", d));
                }
            }
            let b = bytes_of(vm, &v)?;
            new_buffer_value(vm, b)
        }
        other => {
            let d = crate::runtime::util::describe_received(vm, other);
            let e = vm.make_error("TypeError", &format!("The first argument must be of type string or an instance of Buffer, ArrayBuffer, or Array or an Array-like Object. Received {}", d));
            if let Value::Obj(eo) = &e {
                eo.set_prop(PropKey::from_str("code"), Value::str("ERR_INVALID_ARG_TYPE"), WC);
            }
            Err(e)
        }
    }
}

fn size_arg(vm: &mut Vm, v: &Value) -> JsResult<usize> {
    match v {
        Value::Num(n) if *n >= 0.0 && n.is_finite() => Ok(*n as usize),
        Value::Num(n) => {
            let e = vm.make_error("RangeError", &format!("The value of \"size\" is out of range. It must be >= 0 && <= 4294967296. Received {}", crate::numconv::number_to_string(*n)));
            if let Value::Obj(o) = &e {
                o.set_prop(PropKey::from_str("code"), Value::str("ERR_OUT_OF_RANGE"), WC);
            }
            Err(e)
        }
        other => {
            let d = crate::runtime::util::describe_received(vm, other);
            let e = vm.make_error("TypeError", &format!("The \"size\" argument must be of type number. Received {}", d));
            if let Value::Obj(o) = &e {
                o.set_prop(PropKey::from_str("code"), Value::str("ERR_INVALID_ARG_TYPE"), WC);
            }
            Err(e)
        }
    }
}

fn buffer_alloc(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let n = size_arg(vm, &a.arg(0))?;
    let b = new_buffer(vm, vec![0; n])?;
    let fill = a.arg(1);
    if !fill.is_undefined() && n > 0 {
        let pattern = match &fill {
            Value::Str(s) => {
                let e = encoding_arg(vm, &a.arg(2))?;
                encode_string(s, e)
            }
            Value::Num(x) => vec![crate::builtins::number::to_uint32(*x) as u8],
            other => bytes_of(vm, other)?,
        };
        if !pattern.is_empty() {
            let data: Vec<u8> = (0..n).map(|i| pattern[i % pattern.len()]).collect();
            write_bytes(&b, 0, &data);
        }
    }
    Ok(Value::Obj(b))
}

fn buffer_alloc_unsafe(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let n = size_arg(vm, &a.arg(0))?;
    new_buffer_value(vm, vec![0; n])
}

pub fn write_bytes(o: &Obj, start: usize, data: &[u8]) {
    let b = o.borrow();
    if let ObjKind::TypedArray(t) = &b.kind {
        let len = t.len();
        let mut bb = t.buf.borrow_mut();
        for (i, x) in data.iter().enumerate() {
            if start + i >= len {
                break;
            }
            bb.bytes[t.offset + start + i] = *x;
        }
    }
}

fn byte_length(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match a.arg(0) {
        Value::Str(s) => {
            let e = encoding_arg(vm, &a.arg(1))?;
            Ok(Value::Num(encode_string(&s, e).len() as f64))
        }
        Value::Obj(o) => Ok(Value::Num(ta_bytes(&o).len() as f64)),
        other => {
            let d = crate::runtime::util::describe_received(vm, &other);
            vm.throw_type(format!("The \"string\" argument must be of type string or an instance of Buffer or ArrayBuffer. Received {}", d))
        }
    }
}

fn buffer_concat(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let list = a.arg(0);
    if !crate::builtins::array::is_array(vm, &list)? {
        let d = crate::runtime::util::describe_received(vm, &list);
        return vm.throw_type(format!("The \"list\" argument must be an instance of Array. Received {}", d));
    }
    let items = crate::builtins::array::array_like_to_vec(vm, &list)?;
    let mut out = Vec::new();
    for it in items {
        match &it {
            Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_)) => out.extend(ta_bytes(o)),
            other => {
                let d = crate::runtime::util::describe_received(vm, other);
                return vm.throw_type(format!("The \"list[0]\" argument must be an instance of Buffer or Uint8Array. Received {}", d));
            }
        }
    }
    if !a.arg(1).is_undefined() {
        let n = vm.to_index(&a.arg(1))?;
        out.resize(n, 0);
    }
    new_buffer_value(vm, out)
}

fn this_bytes(vm: &mut Vm, v: &Value) -> JsResult<(Obj, Vec<u8>)> {
    match v {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_)) => Ok((o.clone(), ta_bytes(o))),
        _ => vm.throw_type("argument must be a buffer"),
    }
}

fn buffer_compare_static(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (_, x) = this_bytes(vm, &a.arg(0))?;
    let (_, y) = this_bytes(vm, &a.arg(1))?;
    Ok(Value::Num(match x.cmp(&y) {
        std::cmp::Ordering::Less => -1.0,
        std::cmp::Ordering::Equal => 0.0,
        std::cmp::Ordering::Greater => 1.0,
    }))
}

fn clamp_idx(vm: &mut Vm, v: &Value, len: usize, default: usize) -> JsResult<usize> {
    if v.is_undefined() {
        return Ok(default);
    }
    let n = vm.to_integer_or_infinity(v)?;
    Ok(if n < 0.0 { 0 } else { (n as usize).min(len) })
}

fn buf_to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (_, b) = this_bytes(vm, &a.this)?;
    let e = encoding_arg(vm, &a.arg(0))?;
    let s = clamp_idx(vm, &a.arg(1), b.len(), 0)?;
    let en = clamp_idx(vm, &a.arg(2), b.len(), b.len())?;
    if s >= en {
        return Ok(Value::str(""));
    }
    Ok(Value::Str(decode_bytes(&b[s..en], e)))
}

fn buf_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, b) = this_bytes(vm, &a.this)?;
    let s = vm.to_string(&a.arg(0))?;
    let mut offset = 0usize;
    let mut length = b.len();
    let mut encv = Value::Undefined;
    match a.arg(1) {
        Value::Str(_) => encv = a.arg(1),
        Value::Undefined => {}
        v => {
            offset = vm.to_index(&v)?;
            match a.arg(2) {
                Value::Str(_) => encv = a.arg(2),
                Value::Undefined => {}
                l => {
                    length = vm.to_index(&l)?;
                    encv = a.arg(3);
                }
            }
        }
    }
    if offset > b.len() {
        return vm.throw_range("The value of \"offset\" is out of range.");
    }
    let e = encoding_arg(vm, &encv)?;
    let data = encode_string(&s, e);
    let n = data.len().min(length).min(b.len() - offset);
    write_bytes(&o, offset, &data[..n]);
    Ok(Value::Num(n as f64))
}

fn buf_to_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (_, b) = this_bytes(vm, &a.this)?;
    let data: Vec<Value> = b.iter().map(|x| Value::Num(*x as f64)).collect();
    let arr = vm.new_array(data);
    let o = vm.obj_from(vec![("type", Value::str("Buffer")), ("data", Value::Obj(arr))]);
    Ok(Value::Obj(o))
}

fn buf_equals(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (_, x) = this_bytes(vm, &a.this)?;
    let y = match &a.arg(0) {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_)) => ta_bytes(o),
        other => {
            let d = crate::runtime::util::describe_received(vm, other);
            return vm.throw_type(format!("The \"otherBuffer\" argument must be an instance of Buffer or Uint8Array. Received {}", d));
        }
    };
    Ok(Value::Bool(x == y))
}

fn buf_compare(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (_, x) = this_bytes(vm, &a.this)?;
    let (_, y) = this_bytes(vm, &a.arg(0))?;
    let ts = clamp_idx(vm, &a.arg(1), y.len(), 0)?;
    let te = clamp_idx(vm, &a.arg(2), y.len(), y.len())?;
    let ss = clamp_idx(vm, &a.arg(3), x.len(), 0)?;
    let se = clamp_idx(vm, &a.arg(4), x.len(), x.len())?;
    let xs = if ss < se { &x[ss..se] } else { &x[0..0] };
    let ys = if ts < te { &y[ts..te] } else { &y[0..0] };
    Ok(Value::Num(match xs.cmp(ys) {
        std::cmp::Ordering::Less => -1.0,
        std::cmp::Ordering::Equal => 0.0,
        std::cmp::Ordering::Greater => 1.0,
    }))
}

fn buf_subarray(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match &a.this {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_)) => o.clone(),
        _ => return vm.throw_type("argument must be a buffer"),
    };
    let (len, buffer, buf, offset) = match &o.borrow().kind {
        ObjKind::TypedArray(t) => (t.len(), t.buffer.clone(), t.buf.clone(), t.offset),
        _ => unreachable!(),
    };
    let rel = |vm: &mut Vm, v: &Value, d: usize| -> JsResult<usize> {
        if v.is_undefined() {
            return Ok(d);
        }
        let n = vm.to_integer_or_infinity(v)?;
        Ok(if n < 0.0 { (len as f64 + n).max(0.0) as usize } else { (n as usize).min(len) })
    };
    let s = rel(vm, &a.arg(0), 0)?;
    let e = rel(vm, &a.arg(1), len)?;
    let e = e.max(s);
    let p = o.borrow().proto.clone();
    Ok(Value::Obj(Obj::with_class(p, ObjKind::TypedArray(Box::new(TypedArrayData { kind: TAKind::Uint8, buffer, buf, offset: offset + s, length: Some(e - s) })), "Uint8Array")))
}

fn buf_index_of(vm: &mut Vm, a: &Args, last: bool, includes: bool) -> JsResult<Value> {
    let (_, b) = this_bytes(vm, &a.this)?;
    let needle: Vec<u8> = match &a.arg(0) {
        Value::Str(s) => {
            let e = encoding_arg(vm, &a.arg(2))?;
            encode_string(s, e)
        }
        Value::Num(n) => vec![crate::builtins::number::to_uint32(*n) as u8],
        other => bytes_of(vm, other)?,
    };
    let len = b.len() as f64;
    let start = if a.arg(1).is_undefined() {
        if last {
            len
        } else {
            0.0
        }
    } else {
        let n = vm.to_integer_or_infinity(&a.arg(1))?;
        if n < 0.0 {
            (len + n).max(0.0)
        } else {
            n
        }
    };
    let result: f64 = if needle.is_empty() {
        start.min(len)
    } else if last {
        let mut i = (start as i64).min(b.len() as i64 - needle.len() as i64);
        let mut r = -1.0;
        while i >= 0 {
            let iu = i as usize;
            if b[iu..iu + needle.len()] == needle[..] {
                r = i as f64;
                break;
            }
            i -= 1;
        }
        r
    } else {
        let mut r = -1.0;
        let mut i = start as usize;
        while i + needle.len() <= b.len() {
            if b[i..i + needle.len()] == needle[..] {
                r = i as f64;
                break;
            }
            i += 1;
        }
        r
    };
    if includes {
        return Ok(Value::Bool(result >= 0.0));
    }
    Ok(Value::Num(result))
}

fn buf_fill(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, b) = this_bytes(vm, &a.this)?;
    let mut encv = Value::Undefined;
    let (s, e) = match a.arg(1) {
        Value::Str(_) => {
            encv = a.arg(1);
            (0, b.len())
        }
        v => {
            let s = clamp_idx(vm, &v, b.len(), 0)?;
            match a.arg(2) {
                Value::Str(_) => {
                    encv = a.arg(2);
                    (s, b.len())
                }
                v2 => {
                    encv = a.arg(3);
                    (s, clamp_idx(vm, &v2, b.len(), b.len())?)
                }
            }
        }
    };
    let pattern = match &a.arg(0) {
        Value::Str(st) => {
            let en = encoding_arg(vm, &encv)?;
            encode_string(st, en)
        }
        Value::Num(x) => vec![crate::builtins::number::to_uint32(*x) as u8],
        Value::Bool(x) => vec![*x as u8],
        other => bytes_of(vm, other)?,
    };
    if !pattern.is_empty() && s < e {
        let data: Vec<u8> = (0..e - s).map(|i| pattern[i % pattern.len()]).collect();
        write_bytes(&o, s, &data);
    }
    Ok(a.this.clone())
}

fn buf_copy(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (_, src) = this_bytes(vm, &a.this)?;
    let (t, tb) = this_bytes(vm, &a.arg(0))?;
    let ts = clamp_idx(vm, &a.arg(1), tb.len(), 0)?;
    let ss = clamp_idx(vm, &a.arg(2), src.len(), 0)?;
    let se = clamp_idx(vm, &a.arg(3), src.len(), src.len())?;
    if ss >= se || ts >= tb.len() {
        return Ok(Value::Num(0.0));
    }
    let n = (se - ss).min(tb.len() - ts);
    write_bytes(&t, ts, &src[ss..ss + n]);
    Ok(Value::Num(n as f64))
}

fn buf_swap(vm: &mut Vm, a: &Args, size: usize) -> JsResult<Value> {
    let (o, mut b) = this_bytes(vm, &a.this)?;
    if b.len() % size != 0 {
        return vm.throw_range(format!("Buffer size must be a multiple of {}-bits", size * 8));
    }
    for chunk in b.chunks_mut(size) {
        chunk.reverse();
    }
    write_bytes(&o, 0, &b);
    Ok(a.this.clone())
}

fn out_of_range(vm: &mut Vm, name: &str, range: &str, got: &str) -> Value {
    let e = vm.make_error("RangeError", &format!("The value of \"{}\" is out of range. It must be {}. Received {}", name, range, got));
    if let Value::Obj(o) = &e {
        o.set_prop(PropKey::from_str("code"), Value::str("ERR_OUT_OF_RANGE"), WC);
    }
    e
}

fn offset_arg(vm: &mut Vm, v: &Value, len: usize, size: usize) -> JsResult<usize> {
    let off = if v.is_undefined() { 0.0 } else { vm.to_number(v)? };
    if off.fract() != 0.0 || off < 0.0 || off as usize + size > len {
        if len < size {
            let e = vm.make_error("RangeError", "Attempt to access memory outside buffer bounds");
            if let Value::Obj(o) = &e {
                o.set_prop(PropKey::from_str("code"), Value::str("ERR_BUFFER_OUT_OF_BOUNDS"), WC);
            }
            return Err(e);
        }
        return Err(out_of_range(vm, "offset", &format!(">= 0 and <= {}", len - size), &crate::numconv::number_to_string(off)));
    }
    Ok(off as usize)
}

fn buf_read_num(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let kind = a.slot(0).as_num().unwrap() as u8;
    let size = a.slot(1).as_num().unwrap() as usize;
    let little = a.slot(2).truthy();
    let (_, b) = this_bytes(vm, &a.this)?;
    let off = offset_arg(vm, &a.arg(0), b.len(), size)?;
    let tk = match (kind, size) {
        (0, 1) => TAKind::Uint8,
        (1, 1) => TAKind::Int8,
        (0, 2) => TAKind::Uint16,
        (1, 2) => TAKind::Int16,
        (0, 4) => TAKind::Uint32,
        (1, 4) => TAKind::Int32,
        (2, _) => TAKind::Float32,
        (3, _) => TAKind::Float64,
        (4, _) => TAKind::BigInt64,
        _ => TAKind::BigUint64,
    };
    Ok(crate::builtins::typedarray::read_elem(&b, off, tk, little))
}

fn buf_write_num(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let kind = a.slot(0).as_num().unwrap() as u8;
    let size = a.slot(1).as_num().unwrap() as usize;
    let little = a.slot(2).truthy();
    let (o, b) = this_bytes(vm, &a.this)?;
    let off = offset_arg(vm, &a.arg(1), b.len(), size)?;
    let tk = match (kind, size) {
        (0, 1) => TAKind::Uint8,
        (1, 1) => TAKind::Int8,
        (0, 2) => TAKind::Uint16,
        (1, 2) => TAKind::Int16,
        (0, 4) => TAKind::Uint32,
        (1, 4) => TAKind::Int32,
        (2, _) => TAKind::Float32,
        (3, _) => TAKind::Float64,
        (4, _) => TAKind::BigInt64,
        _ => TAKind::BigUint64,
    };
    let v = if kind >= 4 {
        Value::BigInt(vm.to_bigint(&a.arg(0))?)
    } else {
        let n = vm.to_number(&a.arg(0))?;
        if kind <= 1 {
            let (lo, hi) = match (kind, size) {
                (0, s) => (0.0, 2f64.powi(8 * s as i32) - 1.0),
                (_, s) => (-(2f64.powi(8 * s as i32 - 1)), 2f64.powi(8 * s as i32 - 1) - 1.0),
            };
            if n < lo || n > hi || n.is_nan() {
                let range = if kind == 0 { format!(">= 0 and <= {}", crate::numconv::number_to_string(hi)) } else { format!(">= {} and <= {}", crate::numconv::number_to_string(lo), crate::numconv::number_to_string(hi)) };
                return Err(out_of_range(vm, "value", &range, &crate::numconv::number_to_string(n)));
            }
        }
        Value::Num(n)
    };
    let mut tmp = vec![0u8; size];
    crate::builtins::typedarray::write_elem(&mut tmp, 0, tk, &v, little);
    write_bytes(&o, off, &tmp);
    Ok(Value::Num((off + size) as f64))
}

fn buf_read_var(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let signed = a.slot(0).truthy();
    let little = a.slot(1).truthy();
    let (_, b) = this_bytes(vm, &a.this)?;
    let bl = vm.to_number(&a.arg(1))? as usize;
    let off = offset_arg(vm, &a.arg(0), b.len(), bl)?;
    let bytes = &b[off..off + bl];
    let mut v: u64 = 0;
    if little {
        for (i, x) in bytes.iter().enumerate() {
            v |= (*x as u64) << (8 * i);
        }
    } else {
        for x in bytes {
            v = (v << 8) | *x as u64;
        }
    }
    let r = if signed && bl < 8 && v & (1 << (8 * bl - 1)) != 0 { v as i64 - (1i64 << (8 * bl)) } else { v as i64 };
    Ok(Value::Num(r as f64))
}

fn buf_write_var(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let little = a.slot(1).truthy();
    let (o, b) = this_bytes(vm, &a.this)?;
    let n = vm.to_number(&a.arg(0))?;
    let bl = vm.to_number(&a.arg(2))? as usize;
    let off = offset_arg(vm, &a.arg(1), b.len(), bl)?;
    let v = n as i64 as u64;
    let mut tmp = vec![0u8; bl];
    for i in 0..bl {
        let byte = ((v >> (8 * i)) & 0xff) as u8;
        if little {
            tmp[i] = byte;
        } else {
            tmp[bl - 1 - i] = byte;
        }
    }
    write_bytes(&o, off, &tmp);
    Ok(Value::Num((off + bl) as f64))
}

// ---------------- string_decoder ----------------

pub fn create_string_decoder_module(vm: &mut Vm) -> Value {
    let proto = vm.new_object();
    let ctor = vm.native_ctor("StringDecoder", 1, sd_ctor, &proto);
    vm.def_method(&proto, "write", 1, sd_write);
    vm.def_method(&proto, "end", 1, sd_end);
    let m = vm.new_object();
    m.set_str("StringDecoder", Value::Obj(ctor), WEC);
    Value::Obj(m)
}

struct SdState {
    encoding: &'static str,
    pending: RefCell<Vec<u8>>,
}

fn sd_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let e = encoding_arg(vm, &a.arg(0))?;
    let fallback = vm.get(a.callee, &vm.intr.key_prototype.clone(), &Value::Obj(a.callee.clone()))?.as_obj().cloned().unwrap();
    let p = vm.proto_from_nt(&a.new_target, &fallback)?;
    let o = Obj::new(Some(p), ObjKind::Host(Box::new(SdState { encoding: e, pending: RefCell::new(Vec::new()) })));
    o.set_prop(PropKey::from_str("encoding"), Value::str(e), WEC);
    Ok(Value::Obj(o))
}

fn utf8_complete_prefix(b: &[u8]) -> usize {
    // length of the longest prefix that does not end in an incomplete sequence
    let n = b.len();
    let mut i = n;
    let mut back = 0;
    while i > 0 && back < 4 {
        i -= 1;
        back += 1;
        let c = b[i];
        if c & 0xC0 == 0x80 {
            continue;
        }
        let need = if c & 0x80 == 0 {
            1
        } else if c & 0xE0 == 0xC0 {
            2
        } else if c & 0xF0 == 0xE0 {
            3
        } else if c & 0xF8 == 0xF0 {
            4
        } else {
            1
        };
        return if n - i >= need { n } else { i };
    }
    n
}

fn sd_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let data = bytes_of(vm, &a.arg(0))?;
    let st = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("incompatible receiver"),
    };
    let b = st.borrow();
    let s = match &b.kind {
        ObjKind::Host(h) => h.downcast_ref::<SdState>().unwrap(),
        _ => return Ok(Value::str("")),
    };
    let mut p = s.pending.borrow_mut();
    p.extend(data);
    let out = match s.encoding {
        "utf8" => {
            let k = utf8_complete_prefix(&p);
            let r = decode_bytes(&p[..k], "utf8");
            p.drain(..k);
            r
        }
        "utf16le" => {
            let k = p.len() / 2 * 2;
            let r = decode_bytes(&p[..k], "utf16le");
            p.drain(..k);
            r
        }
        "base64" => {
            let k = p.len() / 3 * 3;
            let r = decode_bytes(&p[..k], "base64");
            p.drain(..k);
            r
        }
        e => {
            let r = decode_bytes(&p, e);
            p.clear();
            r
        }
    };
    Ok(Value::Str(out))
}

fn sd_end(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut prefix = JsStr::empty();
    if !a.arg(0).is_undefined() {
        if let Value::Str(s) = sd_write(vm, a)? {
            prefix = s;
        }
    }
    let st = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("incompatible receiver"),
    };
    let b = st.borrow();
    let rest = match &b.kind {
        ObjKind::Host(h) => {
            let s = h.downcast_ref::<SdState>().unwrap();
            let mut p = s.pending.borrow_mut();
            let r = if p.is_empty() { JsStr::empty() } else { decode_bytes(&p, s.encoding) };
            p.clear();
            r
        }
        _ => JsStr::empty(),
    };
    Ok(Value::Str(JsStr::concat(&prefix, &rest)))
}

pub fn _unused(_: Rc<()>) {}
