// Blob, File and FormData. State lives in symbol-keyed own properties like the reference's
// (`Symbol(blobBytes)`, `Symbol(blobType)`, `Symbol(fileName)`, `Symbol(fileLastModified)`,
// `Symbol(formEntries)`).

use super::url::{gen_method, GenKind};
use super::*;
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::cell::RefCell;

struct Keys {
    bytes: Sym,
    ty: Sym,
    name: Sym,
    last_mod: Sym,
    entries: Sym,
}

thread_local! {
    static KEYS: RefCell<Option<Keys>> = RefCell::new(None);
}

fn sym_key(which: u8) -> PropKey {
    KEYS.with(|k| {
        let mut k = k.borrow_mut();
        if k.is_none() {
            *k = Some(Keys {
                bytes: Sym::new(Some(JsStr::from_str("blobBytes"))),
                ty: Sym::new(Some(JsStr::from_str("blobType"))),
                name: Sym::new(Some(JsStr::from_str("fileName"))),
                last_mod: Sym::new(Some(JsStr::from_str("fileLastModified"))),
                entries: Sym::new(Some(JsStr::from_str("formEntries"))),
            });
        }
        let k = k.as_ref().unwrap();
        PropKey::Sym(match which {
            0 => k.bytes.clone(),
            1 => k.ty.clone(),
            2 => k.name.clone(),
            3 => k.last_mod.clone(),
            _ => k.entries.clone(),
        })
    })
}

fn k_bytes() -> PropKey {
    sym_key(0)
}
fn k_type() -> PropKey {
    sym_key(1)
}
fn k_name() -> PropKey {
    sym_key(2)
}
fn k_last_mod() -> PropKey {
    sym_key(3)
}
pub fn form_entries_key(_vm: &mut Vm) -> PropKey {
    sym_key(4)
}
fn k_entries() -> PropKey {
    sym_key(4)
}

pub fn setup(vm: &mut Vm) {
    let tag = vm.intr.sym_to_string_tag.clone();

    let (c, p) = make_class(vm, "Blob", "Blob.prototype", 0, blob_ctor, None);
    getter(vm, &p, "size", blob_size);
    getter(vm, &p, "type", blob_type);
    method(vm, &p, "slice", 3, blob_slice);
    method(vm, &p, "text", 0, blob_text);
    method(vm, &p, "arrayBuffer", 0, blob_array_buffer);
    method(vm, &p, "bytes", 0, blob_bytes);
    method(vm, &p, "stream", 0, blob_stream);
    vm.def_sym_getter(&p, &tag, "[Symbol.toStringTag]", |_vm, _a| Ok(Value::str("Blob")));
    set_global(vm, "Blob", Value::Obj(c));

    let (c, p) = make_class(vm, "File", "File.prototype", 2, file_ctor, Some("Blob"));
    getter(vm, &p, "name", file_name);
    getter(vm, &p, "lastModified", file_last_modified);
    vm.def_sym_getter(&p, &tag, "[Symbol.toStringTag]", |_vm, _a| Ok(Value::str("File")));
    set_global(vm, "File", Value::Obj(c));

    let (c, p) = make_class(vm, "FormData", "FormData.prototype", 0, form_data_ctor, None);
    method(vm, &p, "append", 3, fd_append);
    method(vm, &p, "set", 3, fd_set);
    method(vm, &p, "get", 1, fd_get);
    method(vm, &p, "getAll", 1, fd_get_all);
    method(vm, &p, "has", 1, fd_has);
    method(vm, &p, "delete", 1, fd_delete);
    gen_method(vm, &p, "entries", GenKind::FdEntries);
    gen_method(vm, &p, "keys", GenKind::FdKeys);
    gen_method(vm, &p, "values", GenKind::FdValues);
    method(vm, &p, "forEach", 2, fd_for_each);
    let it = vm.intr.sym_iterator.clone();
    vm.def_sym_method(&p, &it, "[Symbol.iterator]", 0, fd_iterator);
    vm.def_sym_getter(&p, &tag, "[Symbol.toStringTag]", |_vm, _a| Ok(Value::str("FormData")));
    set_global(vm, "FormData", Value::Obj(c));
}

fn u8_view(vm: &mut Vm, bytes: Vec<u8>) -> Value {
    Value::Obj(crate::builtins::typedarray::typed_array_from_bytes(vm, bytes))
}

/// Bytes of a part per the reference's partToBytes (None when a Blob-like has no bytes).
fn part_bytes(vm: &mut Vm, part: &Value) -> JsResult<Vec<u8>> {
    let blob_ctor = Value::Obj(reg(vm, "Blob"));
    if part.is_object() && vm.instance_of(part, &blob_ctor)? {
        let b = get_key(vm, part, &k_bytes())?;
        if let Value::Obj(o) = &b {
            if let ObjKind::TypedArray(_) = &o.borrow().kind {
                return Ok(crate::builtins::typedarray::ta_bytes(o));
            }
        }
        // `size += bytes.length` on a non-Uint8Array
        let len = get(vm, &b, "length")?;
        let n = vm.to_length(&len)? as usize;
        let mut out = Vec::with_capacity(n);
        for i in 0..n {
            let v = get_key(vm, &b, &PropKey::from_index(i as u32))?;
            out.push(vm.to_number(&v)? as i64 as u8);
        }
        return Ok(out);
    }
    if let Value::Obj(o) = part {
        let k = {
            let b = o.borrow();
            match &b.kind {
                ObjKind::ArrayBuffer(bd) => {
                    if bd.borrow().shared {
                        0
                    } else {
                        1
                    }
                }
                ObjKind::TypedArray(_) | ObjKind::DataView(_) => 2,
                _ => 0,
            }
        };
        if k == 1 || k == 2 {
            return Ok(crate::builtins::typedarray::ta_bytes(o));
        }
    }
    let s = js_string(vm, part)?;
    Ok(super::encoding::engine_utf8(s.units()))
}

fn blob_init(vm: &mut Vm, this: &Value, parts: &Value, options: &Value) -> JsResult<()> {
    let parts = if parts.is_undefined() { array(vm, Vec::new()) } else { parts.clone() };
    let options = if options.is_undefined() { Value::Obj(vm.new_object()) } else { options.clone() };
    if !parts.is_nullish() {
        let bad = if let Value::Str(_) = &parts {
            true
        } else {
            let k = PropKey::Sym(vm.intr.sym_iterator.clone());
            let it = get_key(vm, &parts, &k)?;
            !it.is_callable()
        };
        if bad {
            return vm.throw_type("Blob parts must be an iterable (e.g. an array)");
        }
    }
    let mut all: Vec<u8> = Vec::new();
    if !parts.is_nullish() {
        for part in vm.iterate_to_vec(&parts)? {
            let b = part_bytes(vm, &part)?;
            all.extend_from_slice(&b);
        }
    }
    let bytes = u8_view(vm, all);
    set_key(vm, this, k_bytes(), bytes)?;
    let ty = if options.truthy() {
        let t = get(vm, &options, "type")?;
        if t.truthy() {
            let t2 = get(vm, &options, "type")?;
            js_string(vm, &t2)?.to_rust_string()
        } else {
            String::new()
        }
    } else {
        String::new()
    };
    let ty = if ty.chars().any(|c| !(' '..='~').contains(&c)) { String::new() } else { ty.to_ascii_lowercase() };
    set_key(vm, this, k_type(), Value::str(&ty))?;
    Ok(())
}

fn blob_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = new_this(vm, a, "Blob.prototype")?;
    let ov = Value::Obj(o);
    blob_init(vm, &ov, &a.arg(0), &a.arg(1))?;
    Ok(ov)
}

/// `new Blob(parts, options)` from native code.
pub fn construct_blob(vm: &mut Vm, parts: &Value, options: &Value) -> JsResult<Value> {
    let p = reg(vm, "Blob.prototype");
    let ov = Value::Obj(Obj::new(Some(p), ObjKind::Ordinary));
    blob_init(vm, &ov, parts, options)?;
    Ok(ov)
}

// ---- helpers for other runtime modules (fetch bodies, streams) ----

/// A new Blob holding `bytes` with MIME `ty` (lowercased / dropped like the constructor does).
#[allow(dead_code)]
pub fn blob_from_bytes(vm: &mut Vm, bytes: Vec<u8>, ty: &str) -> JsResult<Value> {
    let empty = array(vm, Vec::new());
    let opts = Value::Obj(plain(vm, vec![("type", Value::str(ty))]));
    let b = construct_blob(vm, &empty, &opts)?;
    let view = u8_view(vm, bytes);
    set_key(vm, &b, k_bytes(), view)?;
    Ok(b)
}

/// `v instanceof Blob`
#[allow(dead_code)]
pub fn is_blob(vm: &mut Vm, v: &Value) -> bool {
    let c = Value::Obj(reg(vm, "Blob"));
    v.is_object() && vm.instance_of(v, &c).unwrap_or(false)
}

/// `v instanceof FormData`
#[allow(dead_code)]
pub fn is_form_data(vm: &mut Vm, v: &Value) -> bool {
    let c = Value::Obj(reg(vm, "FormData"));
    v.is_object() && vm.instance_of(v, &c).unwrap_or(false)
}

/// The bytes held by a Blob/File (None when `v` holds none).
#[allow(dead_code)]
pub fn blob_bytes_of(vm: &mut Vm, v: &Value) -> Option<Vec<u8>> {
    let b = get_key(vm, v, &k_bytes()).ok()?;
    match &b {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_)) => Some(crate::builtins::typedarray::ta_bytes(o)),
        _ => None,
    }
}

/// The MIME type of a Blob/File.
#[allow(dead_code)]
pub fn blob_type_of(vm: &mut Vm, v: &Value) -> String {
    match get_key(vm, v, &k_type()) {
        Ok(Value::Str(s)) => s.to_rust_string(),
        _ => String::new(),
    }
}

/// FormData entries as (name, value) pairs; values are strings or Files.
#[allow(dead_code)]
pub fn form_data_entries(vm: &mut Vm, v: &Value) -> JsResult<Vec<(JsStr, Value)>> {
    let list = get_key(vm, v, &k_entries())?;
    let mut out = Vec::new();
    for e in list_for(vm, &list, ITER)? {
        let n = get_key(vm, &e, &PropKey::from_index(0))?;
        let val = get_key(vm, &e, &PropKey::from_index(1))?;
        let n = js_string(vm, &n)?;
        out.push((n, val));
    }
    Ok(out)
}

/// `new FormData()` followed by `append(name, value)` for each pair (for Response.formData()).
#[allow(dead_code)]
pub fn form_data_from(vm: &mut Vm, pairs: Vec<(Value, Value, Value)>) -> JsResult<Value> {
    let p = reg(vm, "FormData.prototype");
    let ov = Value::Obj(Obj::new(Some(p), ObjKind::Ordinary));
    let e = array(vm, Vec::new());
    set_key(vm, &ov, k_entries(), e)?;
    for (n, v, f) in pairs {
        invoke(vm, &ov, "append", &[n, v, f])?;
    }
    Ok(ov)
}

fn blob_size(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = get_key(vm, &a.this, &k_bytes())?;
    get(vm, &b, "length")
}

fn blob_type(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    get_key(vm, &a.this, &k_type())
}

/// clampSlice(v, len): undefined stays undefined; negatives count from the end.
fn clamp_slice(vm: &mut Vm, v: &Value, len: f64) -> JsResult<Option<f64>> {
    if v.is_undefined() {
        return Ok(None);
    }
    let n = vm.to_number(v)?;
    let n = if n.is_nan() { 0.0 } else { n.trunc() };
    Ok(Some(if n < 0.0 { (len + n).max(0.0) } else { n.min(len) }))
}

fn blob_slice(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let bytes = get_key(vm, &a.this, &k_bytes())?;
    let len_v = get(vm, &bytes, "length")?;
    let len = vm.to_number(&len_v)?;
    let s = clamp_slice(vm, &a.arg(0), len)?.unwrap_or(0.0);
    let len_v = get(vm, &bytes, "length")?;
    let len2 = vm.to_number(&len_v)?;
    let e = match clamp_slice(vm, &a.arg(1), len2)? {
        Some(e) => e,
        None => len2,
    };
    let opts = Value::Obj(plain(vm, vec![("type", a.arg(2))]));
    let empty = array(vm, Vec::new());
    let b = construct_blob(vm, &empty, &opts)?;
    let sliced = invoke(vm, &bytes, "slice", &[Value::Num(s), Value::Num(s.max(e))])?;
    set_key(vm, &b, k_bytes(), sliced)?;
    Ok(b)
}

fn blob_text(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r: JsResult<Value> = (|| {
        let b = get_key(vm, &a.this, &k_bytes())?;
        if b.is_undefined() {
            return Ok(Value::str(""));
        }
        let mut input = b;
        let abp = vm.intr.array_buffer_proto.clone();
        if has_in_chain(vm, &input, &abp)? {
            if let Value::Obj(o) = &input {
                let bytes = crate::builtins::typedarray::ta_bytes(o);
                input = u8_view(vm, bytes);
            }
        }
        let bytes = match &input {
            Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_)) => crate::builtins::typedarray::ta_bytes(o),
            _ => return vm.throw_type("TextDecoder.decode expects a BufferSource"),
        };
        Ok(Value::Str(super::encoding::decode_default(&bytes)))
    })();
    Ok(settle(vm, r))
}

fn blob_array_buffer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r: JsResult<Value> = (|| {
        let b = get_key(vm, &a.this, &k_bytes())?;
        let buf = get(vm, &b, "buffer")?;
        let off = get(vm, &b, "byteOffset")?;
        let off2 = get(vm, &b, "byteOffset")?;
        let bl = get(vm, &b, "byteLength")?;
        let end = vm.op_add(&off2, &bl)?;
        invoke(vm, &buf, "slice", &[off, end])
    })();
    Ok(settle(vm, r))
}

fn blob_bytes(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r: JsResult<Value> = (|| {
        let b = get_key(vm, &a.this, &k_bytes())?;
        invoke(vm, &b, "slice", &[])
    })();
    Ok(settle(vm, r))
}

fn blob_stream(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let bytes = get_key(vm, &a.this, &k_bytes())?;
    let rs = global_get(vm, "ReadableStream")?;
    let source = vm.new_object();
    let start = vm.native_closure("start", 1, blob_stream_start, vec![bytes]);
    source.set_prop(key("start"), Value::Obj(start), WEC);
    vm.construct(&rs, &[Value::Obj(source)], None)
}

fn blob_stream_start(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let bytes = a.slot(0);
    let controller = a.arg(0);
    let len = get(vm, &bytes, "length")?;
    if len.truthy() {
        let copy = invoke(vm, &bytes, "slice", &[])?;
        invoke(vm, &controller, "enqueue", &[copy])?;
    }
    invoke(vm, &controller, "close", &[])?;
    Ok(Value::Undefined)
}

// ---------------------------------------------------------------------------------------------
// File
// ---------------------------------------------------------------------------------------------

fn file_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return class_call_error(vm);
    }
    if a.args.len() < 2 {
        return vm.throw_type("File requires fileBits and fileName");
    }
    let o = new_this(vm, a, "File.prototype")?;
    let ov = Value::Obj(o);
    let options = if a.arg(2).is_undefined() { Value::Obj(vm.new_object()) } else { a.arg(2) };
    with_frame(vm, "Blob", |vm| blob_init(vm, &ov, &a.arg(0), &options))?;
    file_fields(vm, &ov, &a.arg(1), &options)?;
    Ok(ov)
}

fn file_fields(vm: &mut Vm, ov: &Value, name: &Value, options: &Value) -> JsResult<()> {
    let n = js_string(vm, name)?;
    set_key(vm, ov, k_name(), Value::Str(n))?;
    let lm = if options.truthy() {
        let l = get(vm, options, "lastModified")?;
        if l.is_undefined() {
            None
        } else {
            let l2 = get(vm, options, "lastModified")?;
            Some(vm.to_number(&l2)?)
        }
    } else {
        None
    };
    let lm = lm.unwrap_or_else(|| crate::datetime::now_ms().floor());
    set_key(vm, ov, k_last_mod(), Value::Num(lm))?;
    Ok(())
}

/// `new File(parts, name, options)` from native code.
fn construct_file(vm: &mut Vm, parts: &Value, name: &Value, options: &Value) -> JsResult<Value> {
    let p = reg(vm, "File.prototype");
    let ov = Value::Obj(Obj::new(Some(p), ObjKind::Ordinary));
    blob_init(vm, &ov, parts, options)?;
    file_fields(vm, &ov, name, options)?;
    Ok(ov)
}

fn file_name(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    get_key(vm, &a.this, &k_name())
}

fn file_last_modified(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    get_key(vm, &a.this, &k_last_mod())
}

// ---------------------------------------------------------------------------------------------
// FormData
// ---------------------------------------------------------------------------------------------

fn form_data_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = new_this(vm, a, "FormData.prototype")?;
    let ov = Value::Obj(o);
    let e = array(vm, Vec::new());
    set_key(vm, &ov, k_entries(), e)?;
    Ok(ov)
}

/// toEntryValue(value, filename)
fn to_entry_value(vm: &mut Vm, value: &Value, filename: &Value) -> JsResult<Value> {
    let blob_ctor = Value::Obj(reg(vm, "Blob"));
    let file_ctor = Value::Obj(reg(vm, "File"));
    if value.is_object() && vm.instance_of(value, &blob_ctor)? {
        let is_file = vm.instance_of(value, &file_ctor)?;
        if is_file && filename.is_undefined() {
            return Ok(value.clone());
        }
        let name = if !filename.is_undefined() {
            Value::Str(js_string(vm, filename)?)
        } else if is_file {
            get(vm, value, "name")?
        } else {
            Value::str("blob")
        };
        let ty = get(vm, value, "type")?;
        let opts = Value::Obj(plain(vm, vec![("type", ty)]));
        let parts = array(vm, vec![value.clone()]);
        return construct_file(vm, &parts, &name, &opts);
    }
    Ok(Value::Str(js_string(vm, value)?))
}

fn entries_of(vm: &mut Vm, this: &Value) -> JsResult<Value> {
    get_key(vm, this, &k_entries())
}

fn fd_append(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let list = entries_of(vm, &a.this)?;
    let n = js_string(vm, &a.arg(0))?;
    let v = to_entry_value(vm, &a.arg(1), &a.arg(2))?;
    let pair = array(vm, vec![Value::Str(n), v]);
    arr_push(vm, &list, pair)?;
    Ok(Value::Undefined)
}

fn fd_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let name = Value::Str(js_string(vm, &a.arg(0))?);
    let v = to_entry_value(vm, &a.arg(1), &a.arg(2))?;
    let list = entries_of(vm, &a.this)?;
    let mut out = Vec::new();
    let mut done = false;
    for e in list_for(vm, &list, ITER)? {
        let kv = vm.iterate_to_vec(&e)?;
        let n = kv.first().cloned().unwrap_or(Value::Undefined);
        let val = kv.get(1).cloned().unwrap_or(Value::Undefined);
        if Value::strict_eq(&n, &name) {
            if !done {
                out.push(array(vm, vec![name.clone(), v.clone()]));
                done = true;
            }
        } else {
            out.push(array(vm, vec![n, val]));
        }
    }
    if !done {
        out.push(array(vm, vec![name, v]));
    }
    let nl = array(vm, out);
    set_key(vm, &a.this, k_entries(), nl)?;
    Ok(Value::Undefined)
}

fn fd_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let name = Value::Str(js_string(vm, &a.arg(0))?);
    let list = entries_of(vm, &a.this)?;
    for e in list_for(vm, &list, "find")? {
        let n = get_key(vm, &e, &PropKey::from_index(0))?;
        if Value::strict_eq(&n, &name) {
            return get_key(vm, &e, &PropKey::from_index(1));
        }
    }
    Ok(Value::Null)
}

fn fd_get_all(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let name = Value::Str(js_string(vm, &a.arg(0))?);
    let list = entries_of(vm, &a.this)?;
    let mut out = Vec::new();
    for e in list_for(vm, &list, "filter")? {
        let n = get_key(vm, &e, &PropKey::from_index(0))?;
        if Value::strict_eq(&n, &name) {
            out.push(get_key(vm, &e, &PropKey::from_index(1))?);
        }
    }
    Ok(array(vm, out))
}

fn fd_has(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let name = Value::Str(js_string(vm, &a.arg(0))?);
    let list = entries_of(vm, &a.this)?;
    for e in list_for(vm, &list, "some")? {
        let n = get_key(vm, &e, &PropKey::from_index(0))?;
        if Value::strict_eq(&n, &name) {
            return Ok(Value::Bool(true));
        }
    }
    Ok(Value::Bool(false))
}

fn fd_delete(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let name = Value::Str(js_string(vm, &a.arg(0))?);
    let list = entries_of(vm, &a.this)?;
    let mut keep = Vec::new();
    for e in list_for(vm, &list, "filter")? {
        let n = get_key(vm, &e, &PropKey::from_index(0))?;
        if !Value::strict_eq(&n, &name) {
            keep.push(e);
        }
    }
    let nl = array(vm, keep);
    set_key(vm, &a.this, k_entries(), nl)?;
    Ok(Value::Undefined)
}

fn fd_for_each(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cb = a.arg(0);
    let this_arg = a.arg(1);
    let list = entries_of(vm, &a.this)?;
    if list.is_nullish() {
        list_for(vm, &list, ITER)?;
    }
    let mut i: u32 = 0;
    loop {
        let len = match &list {
            Value::Obj(o) => vm.length_of(o)?,
            _ => {
                let l = get(vm, &list, "length")?;
                vm.to_length(&l)?
            }
        };
        if i as u64 >= len {
            break;
        }
        let e = get_key(vm, &list, &PropKey::from_index(i))?;
        let kv = vm.iterate_to_vec(&e)?;
        let n = kv.first().cloned().unwrap_or(Value::Undefined);
        let v = kv.get(1).cloned().unwrap_or(Value::Undefined);
        let call = get(vm, &cb, "call")?;
        if !call.is_callable() {
            return vm.throw_type("(intermediate value).call is not a function");
        }
        vm.call(&call, cb.clone(), &[this_arg.clone(), v, n, a.this.clone()])?;
        i += 1;
    }
    Ok(Value::Undefined)
}

fn fd_iterator(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    invoke(vm, &a.this, "entries", &[])
}
