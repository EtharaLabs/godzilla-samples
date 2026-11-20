// ArrayBuffer, SharedArrayBuffer, DataView, typed arrays, Atomics.

use crate::bigint::BigInt;
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::cell::RefCell;
use std::rc::Rc;

pub const MAX_TA_LENGTH: usize = 1 << 20;

pub fn f16_round(x: f64) -> f64 {
    f16_to_f64(f64_to_f16(x))
}

pub fn f64_to_f16(x: f64) -> u16 {
    if x.is_nan() {
        return 0x7e00;
    }
    let sign: u16 = if x.is_sign_negative() { 0x8000 } else { 0 };
    let a = x.abs();
    if a == f64::INFINITY {
        return sign | 0x7c00;
    }
    if a == 0.0 {
        return sign;
    }
    // max finite half 65504; values >= 65520 round to infinity
    if a >= 65520.0 {
        return sign | 0x7c00;
    }
    let e = a.log2().floor() as i32;
    if e < -14 {
        // subnormal: units of 2^-24
        let m = a / 2f64.powi(-24);
        let r = round_half_even(m) as u16;
        return sign | r;
    }
    let mant = a / 2f64.powi(e) - 1.0; // [0,1)
    let mut m = round_half_even(mant * 1024.0) as u32;
    let mut e = e;
    if m == 1024 {
        m = 0;
        e += 1;
    }
    if e > 15 {
        return sign | 0x7c00;
    }
    sign | (((e + 15) as u16) << 10) | m as u16
}

fn round_half_even(x: f64) -> f64 {
    let f = x.floor();
    let d = x - f;
    if d > 0.5 {
        f + 1.0
    } else if d < 0.5 {
        f
    } else if f % 2.0 == 0.0 {
        f
    } else {
        f + 1.0
    }
}

pub fn f16_to_f64(h: u16) -> f64 {
    let sign = if h & 0x8000 != 0 { -1.0 } else { 1.0 };
    let e = ((h >> 10) & 0x1f) as i32;
    let m = (h & 0x3ff) as f64;
    if e == 0 {
        return sign * m * 2f64.powi(-24);
    }
    if e == 31 {
        return if m == 0.0 { sign * f64::INFINITY } else { f64::NAN };
    }
    sign * (1.0 + m / 1024.0) * 2f64.powi(e - 15)
}

// ---------------- raw element access ----------------

pub fn read_elem(bytes: &[u8], off: usize, kind: TAKind, little: bool) -> Value {
    macro_rules! rd {
        ($t:ty, $n:expr) => {{
            let mut b = [0u8; $n];
            b.copy_from_slice(&bytes[off..off + $n]);
            if little {
                <$t>::from_le_bytes(b)
            } else {
                <$t>::from_be_bytes(b)
            }
        }};
    }
    match kind {
        TAKind::Int8 => Value::Num(bytes[off] as i8 as f64),
        TAKind::Uint8 | TAKind::Uint8C => Value::Num(bytes[off] as f64),
        TAKind::Int16 => Value::Num(rd!(i16, 2) as f64),
        TAKind::Uint16 => Value::Num(rd!(u16, 2) as f64),
        TAKind::Int32 => Value::Num(rd!(i32, 4) as f64),
        TAKind::Uint32 => Value::Num(rd!(u32, 4) as f64),
        TAKind::Float16 => Value::Num(f16_to_f64(rd!(u16, 2))),
        TAKind::Float32 => Value::Num(rd!(f32, 4) as f64),
        TAKind::Float64 => Value::Num(rd!(f64, 8)),
        TAKind::BigInt64 => Value::BigInt(Rc::new(BigInt::from_i64(rd!(i64, 8)))),
        TAKind::BigUint64 => Value::BigInt(Rc::new(BigInt::from_u64(rd!(u64, 8)))),
    }
}

/// numeric value already converted (Num for number kinds, BigInt for bigint kinds)
pub fn write_elem(bytes: &mut [u8], off: usize, kind: TAKind, v: &Value, little: bool) {
    macro_rules! wr {
        ($val:expr) => {{
            let b = if little { $val.to_le_bytes() } else { $val.to_be_bytes() };
            bytes[off..off + b.len()].copy_from_slice(&b);
        }};
    }
    match (kind, v) {
        (TAKind::BigInt64, Value::BigInt(b)) => wr!(b.to_i64_wrapping()),
        (TAKind::BigUint64, Value::BigInt(b)) => wr!(b.to_u64_wrapping()),
        (_, Value::Num(n)) => {
            let n = *n;
            use crate::builtins::number::{to_int32, to_uint32};
            match kind {
                TAKind::Int8 => bytes[off] = to_int32(n) as i8 as u8,
                TAKind::Uint8 => bytes[off] = to_uint32(n) as u8,
                TAKind::Uint8C => {
                    bytes[off] = if n.is_nan() {
                        0
                    } else if n <= 0.0 {
                        0
                    } else if n >= 255.0 {
                        255
                    } else {
                        round_half_even(n) as u8
                    }
                }
                TAKind::Int16 => wr!(to_int32(n) as i16),
                TAKind::Uint16 => wr!(to_uint32(n) as u16),
                TAKind::Int32 => wr!(to_int32(n)),
                TAKind::Uint32 => wr!(to_uint32(n)),
                TAKind::Float16 => wr!(f64_to_f16(n)),
                TAKind::Float32 => wr!(n as f32),
                TAKind::Float64 => wr!(n),
                _ => {}
            }
        }
        _ => {}
    }
}

pub fn ta_valid_index(t: &TypedArrayData, n: f64) -> bool {
    if n.fract() != 0.0 || (n == 0.0 && n.is_sign_negative()) || n < 0.0 || n.is_nan() || n.is_infinite() {
        return false;
    }
    (n as usize) < t.len()
}

pub fn ta_get_index(t: &TypedArrayData, n: f64) -> Option<Value> {
    if !ta_valid_index(t, n) {
        return None;
    }
    let i = n as usize;
    let b = t.buf.borrow();
    Some(read_elem(&b.bytes, t.offset + i * t.kind.size(), t.kind, true))
}

pub fn ta_set_index(vm: &mut Vm, o: &Obj, n: f64, v: &Value) -> JsResult<()> {
    let kind = match &o.borrow().kind {
        ObjKind::TypedArray(t) => t.kind,
        _ => return Ok(()),
    };
    let nv = if kind.is_bigint() { Value::BigInt(vm.to_bigint(v)?) } else { Value::Num(vm.to_number(v)?) };
    let b = o.borrow();
    if let ObjKind::TypedArray(t) = &b.kind {
        if t.buf.borrow().immutable {
            return Ok(());
        }
        if ta_valid_index(t, n) {
            let off = t.offset + (n as usize) * t.kind.size();
            let mut bb = t.buf.borrow_mut();
            write_elem(&mut bb.bytes, off, t.kind, &nv, true);
        }
    }
    Ok(())
}

pub fn ta_define_own_property(vm: &mut Vm, o: &Obj, n: f64, desc: PropDesc) -> JsResult<bool> {
    let valid = match &o.borrow().kind {
        ObjKind::TypedArray(t) => ta_valid_index(t, n),
        _ => false,
    };
    if !valid {
        return Ok(false);
    }
    if desc.configurable == Some(false) || desc.enumerable == Some(false) || desc.is_accessor() || desc.writable == Some(false) {
        return Ok(false);
    }
    if let Some(v) = &desc.value {
        ta_set_index(vm, o, n, v)?;
    }
    Ok(true)
}

// ---------------- setup ----------------

pub fn setup(vm: &mut Vm) {
    // ArrayBuffer
    let abp = vm.intr.array_buffer_proto.clone();
    let abc = vm.native_ctor("ArrayBuffer", 1, array_buffer_ctor, &abp);
    vm.intr.array_buffer_ctor = abc.clone();
    vm.def_method(&abc, "isView", 1, is_view);
    vm.def_sym_getter(&abc, &vm.intr.sym_species.clone(), "[Symbol.species]", |_vm, a| Ok(a.this.clone()));
    vm.def_getter(&abp, "byteLength", ab_byte_length);
    vm.def_getter(&abp, "maxByteLength", ab_max_byte_length);
    vm.def_getter(&abp, "resizable", ab_resizable);
    vm.def_getter(&abp, "detached", ab_detached);
    vm.def_method(&abp, "slice", 2, ab_slice);
    vm.def_method(&abp, "resize", 1, ab_resize);
    vm.def_method(&abp, "transfer", 0, ab_transfer);
    vm.def_method(&abp, "transferToFixedLength", 0, ab_transfer_fixed);
    vm.def_getter(&abp, "immutable", ab_immutable);
    vm.def_method(&abp, "transferToImmutable", 0, ab_transfer_immutable);
    vm.def_method(&abp, "sliceToImmutable", 2, ab_slice_immutable);
    vm.set_tag(&abp, "ArrayBuffer");
    vm.def_global("ArrayBuffer", Value::Obj(abc));

    let sabp = vm.intr.shared_array_buffer_proto.clone();
    let sabc = vm.native_ctor("SharedArrayBuffer", 1, shared_array_buffer_ctor, &sabp);
    vm.def_sym_getter(&sabc, &vm.intr.sym_species.clone(), "[Symbol.species]", |_vm, a| Ok(a.this.clone()));
    vm.def_getter(&sabp, "byteLength", ab_byte_length);
    vm.def_getter(&sabp, "maxByteLength", ab_max_byte_length);
    vm.def_getter(&sabp, "growable", ab_resizable);
    vm.def_method(&sabp, "slice", 2, ab_slice);
    vm.def_method(&sabp, "grow", 1, ab_resize);
    vm.set_tag(&sabp, "SharedArrayBuffer");
    vm.def_global("SharedArrayBuffer", Value::Obj(sabc));

    // DataView
    let dvp = vm.intr.data_view_proto.clone();
    let dvc = vm.native_ctor("DataView", 1, data_view_ctor, &dvp);
    vm.def_getter(&dvp, "buffer", dv_buffer);
    vm.def_getter(&dvp, "byteLength", dv_byte_length);
    vm.def_getter(&dvp, "byteOffset", dv_byte_offset);
    let dv_methods: &[(&str, TAKind)] = &[
        ("Int8", TAKind::Int8),
        ("Uint8", TAKind::Uint8),
        ("Int16", TAKind::Int16),
        ("Uint16", TAKind::Uint16),
        ("Int32", TAKind::Int32),
        ("Uint32", TAKind::Uint32),
        ("Float16", TAKind::Float16),
        ("Float32", TAKind::Float32),
        ("Float64", TAKind::Float64),
        ("BigInt64", TAKind::BigInt64),
        ("BigUint64", TAKind::BigUint64),
    ];
    for (n, k) in dv_methods {
        let g = vm.native_closure(&format!("get{}", n), 1, dv_get, vec![Value::Num(ta_kind_index(*k) as f64)]);
        dvp.set_prop(PropKey::from_str(&format!("get{}", n)), Value::Obj(g), WC);
        let s = vm.native_closure(&format!("set{}", n), 2, dv_set, vec![Value::Num(ta_kind_index(*k) as f64)]);
        dvp.set_prop(PropKey::from_str(&format!("set{}", n)), Value::Obj(s), WC);
    }
    vm.set_tag(&dvp, "DataView");
    vm.def_global("DataView", Value::Obj(dvc));

    // %TypedArray%
    let tap = vm.intr.typed_array_proto.clone();
    let tac = vm.native_ctor("TypedArray", 0, typed_array_abstract_ctor, &tap);
    vm.intr.typed_array_ctor = tac.clone();
    vm.def_method(&tac, "from", 1, ta_from);
    vm.def_method(&tac, "of", 0, ta_of);
    vm.def_sym_getter(&tac, &vm.intr.sym_species.clone(), "[Symbol.species]", |_vm, a| Ok(a.this.clone()));
    let methods: &[(&str, u32, NativeFn)] = &[
        ("forEach", 1, ta_for_each),
        ("map", 1, ta_map),
        ("filter", 1, ta_filter),
        ("reduce", 1, ta_reduce),
        ("reduceRight", 1, ta_reduce_right),
        ("some", 1, ta_some),
        ("every", 1, ta_every),
        ("find", 1, ta_find),
        ("findIndex", 1, ta_find_index),
        ("findLast", 1, ta_find_last),
        ("findLastIndex", 1, ta_find_last_index),
        ("indexOf", 1, ta_index_of),
        ("lastIndexOf", 1, ta_last_index_of),
        ("includes", 1, ta_includes),
        ("join", 1, ta_join),
        ("fill", 1, ta_fill),
        ("reverse", 0, ta_reverse),
        ("sort", 1, ta_sort),
        ("slice", 2, ta_slice),
        ("at", 1, ta_at),
        ("keys", 0, ta_keys),
        ("values", 0, ta_values),
        ("entries", 0, ta_entries),
        ("copyWithin", 2, ta_copy_within),
        ("toReversed", 0, ta_to_reversed),
        ("toSorted", 1, ta_to_sorted),
        ("with", 2, ta_with),
        ("set", 1, ta_set),
        ("subarray", 2, ta_subarray),
        ("toLocaleString", 0, ta_to_locale_string),
    ];
    for (n, l, f) in methods {
        let fo = vm.def_method(&tap, n, *l, *f);
        if *n == "values" {
            tap.set_prop(PropKey::Sym(vm.intr.sym_iterator.clone()), Value::Obj(fo), WC);
        }
        if *n == "with" {
            // Array.prototype.toString is shared
            let ts = vm.intr.array_proto.get_own_str("toString").unwrap();
            tap.set_prop(PropKey::from_str("toString"), ts, WC);
        }
    }
    vm.def_getter(&tap, "length", ta_length);
    vm.def_getter(&tap, "byteLength", ta_byte_length);
    vm.def_getter(&tap, "byteOffset", ta_byte_offset);
    vm.def_getter(&tap, "buffer", ta_buffer);
    move_to_end(&tap, &vm.intr.key_constructor.clone());
    vm.def_sym_getter(&tap, &vm.intr.sym_to_string_tag.clone(), "[Symbol.toStringTag]", ta_tag);

    for kind in TAKind::all() {
        let p = Obj::new(Some(tap.clone()), ObjKind::Ordinary);
        let c = vm.native_closure(kind.name(), 3, ta_ctor, vec![Value::Num(ta_kind_index(kind) as f64)]);
        vm.make_ctor(&c);
        c.set_prop(vm.intr.key_prototype.clone(), Value::Obj(p.clone()), 0);
        p.set_prop(vm.intr.key_constructor.clone(), Value::Obj(c.clone()), WC);
        c.borrow_mut().proto = Some(tac.clone());
        let bpe = Value::Num(kind.size() as f64);
        c.set_prop(PropKey::from_str("BYTES_PER_ELEMENT"), bpe.clone(), 0);
        p.set_prop(PropKey::from_str("BYTES_PER_ELEMENT"), bpe, 0);
        vm.intr.ta_protos.push(p);
        vm.intr.ta_ctors.push(c.clone());
        vm.def_global(kind.name(), Value::Obj(c));
    }
    // Uint8Array base64/hex methods
    let u8c = vm.intr.ta_ctors[1].clone();
    let u8p = vm.intr.ta_protos[1].clone();
    vm.def_method(&u8c, "fromBase64", 1, u8_from_base64);
    vm.def_method(&u8c, "fromHex", 1, u8_from_hex);
    vm.def_method(&u8p, "toBase64", 0, u8_to_base64);
    vm.def_method(&u8p, "toHex", 0, u8_to_hex);
    vm.def_method(&u8p, "setFromBase64", 1, u8_set_from_base64);
    vm.def_method(&u8p, "setFromHex", 1, u8_set_from_hex);

    // Atomics
    let at = vm.new_object();
    let atomics: &[(&str, u32, NativeFn)] = &[
        ("add", 3, |vm, a| atomic_rmw(vm, a, 0)),
        ("and", 3, |vm, a| atomic_rmw(vm, a, 1)),
        ("compareExchange", 4, atomic_compare_exchange),
        ("exchange", 3, |vm, a| atomic_rmw(vm, a, 2)),
        ("isLockFree", 1, atomic_is_lock_free),
        ("load", 2, atomic_load),
        ("or", 3, |vm, a| atomic_rmw(vm, a, 3)),
        ("store", 3, atomic_store),
        ("sub", 3, |vm, a| atomic_rmw(vm, a, 4)),
        ("wait", 4, atomic_wait),
        ("waitAsync", 4, atomic_wait),
        ("notify", 3, atomic_notify),
        ("xor", 3, |vm, a| atomic_rmw(vm, a, 5)),
        ("pause", 0, |_vm, _a| Ok(Value::Undefined)),
    ];
    for (n, l, f) in atomics {
        vm.def_method(&at, n, *l, *f);
    }
    vm.set_tag(&at, "Atomics");
    vm.def_global("Atomics", Value::Obj(at));
}

pub fn ta_kind_index(k: TAKind) -> usize {
    TAKind::all().iter().position(|x| *x == k).unwrap()
}

fn kind_from_slot(a: &Args) -> TAKind {
    TAKind::all()[a.slot(0).as_num().unwrap() as usize]
}

// ---------------- ArrayBuffer ----------------

pub fn new_array_buffer(vm: &Vm, bytes: Vec<u8>) -> Obj {
    let data = Rc::new(RefCell::new(BufferData { bytes, detached: false, max_len: None, shared: false, immutable: false }));
    Obj::with_class(Some(vm.intr.array_buffer_proto.clone()), ObjKind::ArrayBuffer(data), "ArrayBuffer")
}

fn array_buffer_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return vm.throw_type("ArrayBuffer constructor requires 'new'");
    }
    let len = {
        let v = a.arg(0);
        let n = if v.is_undefined() { 0.0 } else { vm.to_integer_or_infinity(&v)? };
        if n < 0.0 || n.is_infinite() {
            return vm.throw_range("Invalid ArrayBuffer length");
        }
        if n > 2147483647.0 {
            return vm.throw_range("ArrayBuffer allocation too large");
        }
        n as usize
    };
    let mut max = None;
    if let Value::Obj(o) = a.arg(1) {
        let m = vm.get_str(&o, "maxByteLength")?;
        if !m.is_undefined() {
            let ml = vm.to_index_msg(&m, "Invalid maxByteLength")?;
            if ml > 0x7fff_ffff {
                return vm.throw_range("ArrayBuffer allocation too large");
            }
            if len > ml {
                return vm.throw_range("maxByteLength is below the length");
            }
            max = Some(ml);
        }
    }
    let proto = vm.proto_from_nt(&a.new_target, &vm.intr.array_buffer_proto.clone())?;
    if len > 0x7fff_ffff {
        return vm.throw_range("ArrayBuffer allocation too large");
    }
    let data = Rc::new(RefCell::new(BufferData { bytes: vec![0; len], detached: false, max_len: max, shared: false, immutable: false }));
    Ok(Value::Obj(Obj::with_class(Some(proto), ObjKind::ArrayBuffer(data), "ArrayBuffer")))
}

fn shared_array_buffer_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return vm.throw_type("SharedArrayBuffer constructor requires 'new'");
    }
    let len = vm.to_index_msg(&a.arg(0), "Invalid SharedArrayBuffer length")?;
    if len > 0x7fff_ffff {
        return vm.throw_range("SharedArrayBuffer allocation too large");
    }
    let mut max = None;
    if let Value::Obj(o) = a.arg(1) {
        let m = vm.get_str(&o, "maxByteLength")?;
        if !m.is_undefined() {
            let ml = vm.to_index_msg(&m, "Invalid maxByteLength")?;
            if len > ml {
                return vm.throw_range("maxByteLength is below the length");
            }
            max = Some(ml);
        }
    }
    let proto = vm.proto_from_nt(&a.new_target, &vm.intr.shared_array_buffer_proto.clone())?;
    let data = Rc::new(RefCell::new(BufferData { bytes: vec![0; len], detached: false, max_len: max, shared: true, immutable: false }));
    Ok(Value::Obj(Obj::with_class(Some(proto), ObjKind::ArrayBuffer(data), "SharedArrayBuffer")))
}

fn this_buffer(vm: &mut Vm, v: &Value) -> JsResult<Rc<RefCell<BufferData>>> {
    match v {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::ArrayBuffer(b) => Ok(b.clone()),
            _ => Err(vm.make_error("TypeError", "not an ArrayBuffer")),
        },
        _ => vm.throw_type("not an ArrayBuffer"),
    }
}

fn is_view(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(matches!(&a.arg(0), Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_) | ObjKind::DataView(_)))))
}

fn ab_byte_length(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = this_buffer(vm, &a.this)?;
    let b = b.borrow();
    Ok(Value::Num(if b.detached { 0.0 } else { b.bytes.len() as f64 }))
}

fn ab_max_byte_length(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = this_buffer(vm, &a.this)?;
    let b = b.borrow();
    if b.detached {
        return Ok(Value::Num(0.0));
    }
    Ok(Value::Num(b.max_len.unwrap_or(b.bytes.len()) as f64))
}

fn ab_resizable(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = this_buffer(vm, &a.this)?;
    let r = b.borrow().max_len.is_some();
    Ok(Value::Bool(r))
}

fn ab_immutable(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = this_buffer(vm, &a.this)?;
    let r = b.borrow().immutable;
    Ok(Value::Bool(r))
}

fn ab_transfer_immutable(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = transfer_impl(vm, a, true)?;
    if let Value::Obj(o) = &r {
        if let ObjKind::ArrayBuffer(b) = &o.borrow().kind {
            b.borrow_mut().immutable = true;
        }
    }
    Ok(r)
}

fn ab_slice_immutable(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = ab_slice(vm, a)?;
    if let Value::Obj(o) = &r {
        if let ObjKind::ArrayBuffer(b) = &o.borrow().kind {
            let mut bb = b.borrow_mut();
            bb.immutable = true;
            bb.max_len = None;
        }
    }
    Ok(r)
}

/// TypeError for writes through views of an immutable buffer
fn check_mutable(vm: &mut Vm, buf: &Rc<RefCell<BufferData>>) -> JsResult<()> {
    if buf.borrow().immutable {
        return vm.throw_type("Cannot write to an immutable ArrayBuffer");
    }
    Ok(())
}

fn ta_check_mutable(vm: &mut Vm, o: &Obj) -> JsResult<()> {
    let buf = match &o.borrow().kind {
        ObjKind::TypedArray(t) => t.buf.clone(),
        _ => return Ok(()),
    };
    check_mutable(vm, &buf)
}

fn ab_detached(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = this_buffer(vm, &a.this)?;
    let r = b.borrow().detached;
    Ok(Value::Bool(r))
}

fn ab_slice(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = match &a.this {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::ArrayBuffer(b) => Some(b.clone()),
            _ => None,
        },
        _ => None,
    };
    let b = match b {
        Some(b) => b,
        None => return vm.throw_type("ArrayBuffer.prototype.slice requires an ArrayBuffer"),
    };
    if b.borrow().detached {
        return vm.throw_type("Cannot slice a detached ArrayBuffer");
    }
    let len = b.borrow().bytes.len() as f64;
    let s = vm.to_integer_or_infinity(&a.arg(0))?;
    let first = if s < 0.0 { (len + s).max(0.0) } else { s.min(len) };
    let e = if a.arg(1).is_undefined() { len } else { vm.to_integer_or_infinity(&a.arg(1))? };
    let fin = if e < 0.0 { (len + e).max(0.0) } else { e.min(len) };
    let n = (fin - first).max(0.0) as usize;
    let shared = b.borrow().shared;
    // SpeciesConstructor(O, %ArrayBuffer% / %SharedArrayBuffer%)
    let this_obj = a.this.as_obj().unwrap().clone();
    let c = vm.get(&this_obj, &vm.intr.key_constructor.clone(), &a.this)?;
    let species = match &c {
        Value::Undefined => Value::Undefined,
        Value::Obj(co) => {
            let s = vm.get(co, &PropKey::Sym(vm.intr.sym_species.clone()), &c)?;
            if s.is_nullish() {
                Value::Undefined
            } else if matches!(&s, Value::Obj(so) if so.is_constructor()) {
                s
            } else {
                return vm.throw_type("@@species is not a constructor");
            }
        }
        _ => return vm.throw_type("constructor is not an object"),
    };
    let default_ctor = if shared { None } else { Some(vm.intr.array_buffer_ctor.clone()) };
    let use_species = match (&species, &default_ctor) {
        (Value::Undefined, _) => false,
        (Value::Obj(s), Some(d)) => !s.ptr_eq(d),
        _ => true,
    };
    if use_species {
        let nb = vm.construct(&species, &[Value::Num(n as f64)], None)?;
        let nbuf = match &nb {
            Value::Obj(o) => match &o.borrow().kind {
                ObjKind::ArrayBuffer(x) => Some(x.clone()),
                _ => None,
            },
            _ => None,
        };
        let kind_name = if shared { "SharedArrayBuffer" } else { "ArrayBuffer" };
        let nbuf = match nbuf {
            Some(x) => x,
            None => return vm.throw_type(format!("slice species did not create an {}", kind_name).replace("an Shared", "a Shared")),
        };
        if nbuf.borrow().shared != shared {
            if shared {
                return vm.throw_type("slice species did not create a SharedArrayBuffer");
            }
            return vm.throw_type("slice species returned a SharedArrayBuffer");
        }
        if !shared && nbuf.borrow().detached {
            return vm.throw_type("slice species returned a detached ArrayBuffer");
        }
        if Rc::ptr_eq(&nbuf, &b) {
            return vm.throw_type(format!("slice species returned the same {}", kind_name));
        }
        if nbuf.borrow().bytes.len() < n {
            return vm.throw_type("slice species buffer is too small");
        }
        if b.borrow().detached {
            return vm.throw_type("Cannot slice a detached ArrayBuffer");
        }
        let src_len = b.borrow().bytes.len();
        let start = (first as usize).min(src_len);
        let end = (first as usize + n).min(src_len);
        let chunk = b.borrow().bytes[start..end].to_vec();
        nbuf.borrow_mut().bytes[..chunk.len()].copy_from_slice(&chunk);
        return Ok(nb);
    }
    let bytes = b.borrow().bytes[first as usize..first as usize + n].to_vec();
    let proto = if shared { vm.intr.shared_array_buffer_proto.clone() } else { vm.intr.array_buffer_proto.clone() };
    let data = Rc::new(RefCell::new(BufferData { bytes, detached: false, max_len: None, shared, immutable: false }));
    Ok(Value::Obj(Obj::with_class(Some(proto), ObjKind::ArrayBuffer(data), if shared { "SharedArrayBuffer" } else { "ArrayBuffer" })))
}

fn ab_resize(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = match &a.this {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::ArrayBuffer(b) => Some(b.clone()),
            _ => None,
        },
        _ => None,
    };
    let b = match b {
        Some(b) => b,
        None => return vm.throw_type("ArrayBuffer is not resizable"),
    };
    let shared = b.borrow().shared;
    let max = match b.borrow().max_len {
        Some(m) if !b.borrow().detached && !b.borrow().immutable => m,
        _ => return Err(vm.make_error("TypeError", if shared { "SharedArrayBuffer is not growable" } else { "ArrayBuffer is not resizable" })),
    };
    let msg = if shared { "SharedArrayBuffer grow out of range" } else { "ArrayBuffer resize out of range" };
    let n = vm.to_index_msg(&a.arg(0), msg)?;
    // (a SharedArrayBuffer cannot shrink)
    if n > max || (shared && n < b.borrow().bytes.len()) {
        return vm.throw_range(msg);
    }
    b.borrow_mut().bytes.resize(n, 0);
    Ok(Value::Undefined)
}

fn transfer_impl(vm: &mut Vm, a: &Args, fixed: bool) -> JsResult<Value> {
    let b = this_buffer(vm, &a.this)?;
    if b.borrow().shared {
        return vm.throw_type("Cannot transfer a SharedArrayBuffer");
    }
    if b.borrow().immutable {
        return vm.throw_type("an immutable ArrayBuffer is not detachable");
    }
    let new_len = if a.arg(0).is_undefined() { b.borrow().bytes.len() } else { vm.to_index_msg(&a.arg(0), "Invalid ArrayBuffer length")? };
    if b.borrow().detached {
        return vm.throw_type("ArrayBuffer is detached");
    }
    let mut bytes = std::mem::take(&mut b.borrow_mut().bytes);
    bytes.resize(new_len, 0);
    let max = if fixed { None } else { b.borrow().max_len };
    b.borrow_mut().detached = true;
    let data = Rc::new(RefCell::new(BufferData { bytes, detached: false, max_len: max, shared: false, immutable: false }));
    Ok(Value::Obj(Obj::with_class(Some(vm.intr.array_buffer_proto.clone()), ObjKind::ArrayBuffer(data), "ArrayBuffer")))
}

fn ab_transfer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    transfer_impl(vm, a, false)
}
fn ab_transfer_fixed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    transfer_impl(vm, a, true)
}

pub fn detach_buffer(o: &Obj) {
    if let ObjKind::ArrayBuffer(b) = &o.borrow().kind {
        let mut bb = b.borrow_mut();
        bb.bytes = Vec::new();
        bb.detached = true;
    }
}

// ---------------- DataView ----------------

fn data_view_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return vm.throw_type("DataView constructor requires 'new'");
    }
    let (bo, buf) = match a.arg(0) {
        Value::Obj(o) => {
            let b = match &o.borrow().kind {
                ObjKind::ArrayBuffer(b) => Some(b.clone()),
                _ => None,
            };
            match b {
                Some(b) => (o.clone(), b),
                None => return vm.throw_type("DataView requires an ArrayBuffer"),
            }
        }
        _ => return vm.throw_type("DataView requires an ArrayBuffer"),
    };
    let off = vm.to_index(&a.arg(1))?;
    if buf.borrow().detached {
        return vm.throw_type("ArrayBuffer is detached");
    }
    let blen = buf.borrow().bytes.len();
    if off > blen {
        return vm.throw_range("DataView byteOffset is out of bounds");
    }
    let tracking = a.arg(2).is_undefined() && buf.borrow().max_len.is_some();
    let length = if a.arg(2).is_undefined() {
        if tracking {
            None
        } else {
            Some(blen - off)
        }
    } else {
        let l = vm.to_index(&a.arg(2))?;
        if off + l > blen {
            return vm.throw_range("DataView byteLength is out of bounds");
        }
        Some(l)
    };
    let proto = vm.proto_from_nt(&a.new_target, &vm.intr.data_view_proto.clone())?;
    Ok(Value::Obj(Obj::with_class(Some(proto), ObjKind::DataView(Box::new(DataViewData { buffer: bo, buf, offset: off, length })), "DataView")))
}

fn this_dv(vm: &mut Vm, v: &Value) -> JsResult<(Obj, Rc<RefCell<BufferData>>, usize, Option<usize>)> {
    match v {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::DataView(d) => Ok((d.buffer.clone(), d.buf.clone(), d.offset, d.length)),
            _ => Err(vm.make_error("TypeError", "not a DataView")),
        },
        _ => vm.throw_type("not a DataView"),
    }
}

fn dv_view_len(vm: &mut Vm, buf: &Rc<RefCell<BufferData>>, off: usize, len: Option<usize>) -> JsResult<usize> {
    let b = buf.borrow();
    if b.detached {
        drop(b);
        return vm.throw_type("DataView's buffer is detached or out of bounds");
    }
    let bl = b.bytes.len();
    match len {
        Some(l) => {
            if off + l > bl {
                drop(b);
                return vm.throw_type("DataView's buffer is detached or out of bounds");
            }
            Ok(l)
        }
        None => {
            if off > bl {
                drop(b);
                return vm.throw_type("DataView's buffer is detached or out of bounds");
            }
            Ok(bl - off)
        }
    }
}

fn dv_buffer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (bo, _, _, _) = this_dv(vm, &a.this).map_err(|_| vm.make_error("TypeError", "receiver is not a DataView"))?;
    Ok(Value::Obj(bo))
}
fn dv_byte_length(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (_, buf, off, len) = this_dv(vm, &a.this).map_err(|_| vm.make_error("TypeError", "receiver is not a DataView"))?;
    Ok(Value::Num(dv_view_len(vm, &buf, off, len)? as f64))
}
fn dv_byte_offset(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (_, buf, off, len) = this_dv(vm, &a.this).map_err(|_| vm.make_error("TypeError", "receiver is not a DataView"))?;
    dv_view_len(vm, &buf, off, len)?;
    Ok(Value::Num(off as f64))
}

fn dv_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let kind = kind_from_slot(a);
    let (_, buf, off, len) = this_dv(vm, &a.this)?;
    let idx = vm.to_index(&a.arg(0))?;
    let little = a.arg(1).truthy();
    let vl = dv_view_len(vm, &buf, off, len)?;
    if idx + kind.size() > vl {
        return vm.throw_range("Offset is outside the bounds of the DataView");
    }
    let b = buf.borrow();
    Ok(read_elem(&b.bytes, off + idx, kind, little))
}

fn dv_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let kind = kind_from_slot(a);
    let (_, buf, off, len) = this_dv(vm, &a.this)?;
    let idx = vm.to_index(&a.arg(0))?;
    check_mutable(vm, &buf)?;
    let v = if kind.is_bigint() { Value::BigInt(vm.to_bigint(&a.arg(1))?) } else { Value::Num(vm.to_number(&a.arg(1))?) };
    let little = a.arg(2).truthy();
    let vl = dv_view_len(vm, &buf, off, len)?;
    if idx + kind.size() > vl {
        return vm.throw_range("Offset is outside the bounds of the DataView");
    }
    let mut b = buf.borrow_mut();
    write_elem(&mut b.bytes, off + idx, kind, &v, little);
    Ok(Value::Undefined)
}

// ---------------- typed array construction ----------------

fn typed_array_abstract_ctor(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    vm.throw_type("Abstract class TypedArray not directly constructable")
}

pub fn create_typed_array(vm: &mut Vm, kind: TAKind, len: usize, proto: Option<Obj>) -> JsResult<Obj> {
    if len > MAX_TA_LENGTH {
        return vm.throw_range("Invalid typed array length");
    }
    let buf = Rc::new(RefCell::new(BufferData { bytes: vec![0; len * kind.size()], detached: false, max_len: None, shared: false, immutable: false }));
    let bo = Obj::with_class(Some(vm.intr.array_buffer_proto.clone()), ObjKind::ArrayBuffer(buf.clone()), "ArrayBuffer");
    let p = proto.unwrap_or_else(|| vm.intr.ta_protos[ta_kind_index(kind)].clone());
    Ok(Obj::with_class(Some(p), ObjKind::TypedArray(Box::new(TypedArrayData { kind, buffer: bo, buf, offset: 0, length: Some(len) })), kind.name()))
}

pub fn typed_array_from_bytes(vm: &mut Vm, bytes: Vec<u8>) -> Obj {
    let len = bytes.len();
    let buf = Rc::new(RefCell::new(BufferData { bytes, detached: false, max_len: None, shared: false, immutable: false }));
    let bo = Obj::with_class(Some(vm.intr.array_buffer_proto.clone()), ObjKind::ArrayBuffer(buf.clone()), "ArrayBuffer");
    let p = vm.intr.ta_protos[1].clone();
    Obj::with_class(Some(p), ObjKind::TypedArray(Box::new(TypedArrayData { kind: TAKind::Uint8, buffer: bo, buf, offset: 0, length: Some(len) })), "Uint8Array")
}

fn ta_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let kind = kind_from_slot(a);
    if a.new_target.is_none() {
        return vm.throw_type("TypedArray constructor requires 'new'");
    }
    let proto = vm.proto_from_nt(&a.new_target, &vm.intr.ta_protos[ta_kind_index(kind)].clone())?;
    let first = a.arg(0);
    match &first {
        Value::Obj(o) => {
            enum Src {
                Buffer(Rc<RefCell<BufferData>>),
                Typed(TAKind, Vec<Value>),
                Other,
            }
            let src = match &o.borrow().kind {
                ObjKind::ArrayBuffer(b) => Src::Buffer(b.clone()),
                ObjKind::TypedArray(t) if t.is_out_of_bounds() => {
                    drop(t);
                    return vm.throw_type("Cannot perform operation on a detached or out-of-bounds TypedArray");
                }
                ObjKind::TypedArray(t) => {
                    let n = t.len();
                    let b = t.buf.borrow();
                    let vals: Vec<Value> = (0..n).map(|i| read_elem(&b.bytes, t.offset + i * t.kind.size(), t.kind, true)).collect();
                    Src::Typed(t.kind, vals)
                }
                _ => Src::Other,
            };
            match src {
                Src::Buffer(buf) => {
                    let off = vm.to_index(&a.arg(1))?;
                    if off % kind.size() != 0 {
                        return vm.throw_range("byteOffset is not aligned to the element size");
                    }
                    if buf.borrow().detached {
                        return vm.throw_type("ArrayBuffer is detached");
                    }
                    let blen = buf.borrow().bytes.len();
                    let length = if a.arg(2).is_undefined() {
                        if buf.borrow().max_len.is_some() {
                            if off > blen {
                                return vm.throw_range("byteOffset is out of bounds");
                            }
                            None
                        } else {
                            if blen % kind.size() != 0 {
                                return vm.throw_range("buffer length is not a multiple of the element size");
                            }
                            if off > blen {
                                return vm.throw_range("byteOffset is out of bounds");
                            }
                            Some((blen - off) / kind.size())
                        }
                    } else {
                        let l = vm.to_index(&a.arg(2))?;
                        if off + l * kind.size() > blen {
                            return vm.throw_range("invalid typed array length");
                        }
                        Some(l)
                    };
                    Ok(Value::Obj(Obj::with_class(Some(proto), ObjKind::TypedArray(Box::new(TypedArrayData { kind, buffer: o.clone(), buf, offset: off, length })), kind.name())))
                }
                Src::Typed(sk, vals) => {
                    let _ = sk;
                    let t = create_typed_array(vm, kind, vals.len(), Some(proto))?;
                    fill_from_values(vm, &t, &vals)?;
                    Ok(Value::Obj(t))
                }
                Src::Other => {
                    let im = vm.get(o, &PropKey::Sym(vm.intr.sym_iterator.clone()), &first)?;
                    let vals = if !im.is_nullish() {
                        vm.iterate_spread(&first, "@@iterator is not callable")?
                    } else {
                        crate::builtins::array::array_like_to_vec(vm, &first)?
                    };
                    let t = create_typed_array(vm, kind, vals.len(), Some(proto))?;
                    fill_from_values(vm, &t, &vals)?;
                    Ok(Value::Obj(t))
                }
            }
        }
        _ => {
            let n = if first.is_undefined() {
                0
            } else {
                let x = vm.to_integer_or_infinity(&first)?;
                if !(0.0..=9007199254740991.0).contains(&x) {
                    return vm.throw_range("index out of range");
                }
                x as usize
            };
            Ok(Value::Obj(create_typed_array(vm, kind, n, Some(proto))?))
        }
    }
}

fn fill_from_values(vm: &mut Vm, t: &Obj, vals: &[Value]) -> JsResult<()> {
    for (i, v) in vals.iter().enumerate() {
        ta_set_index(vm, t, i as f64, v)?;
    }
    Ok(())
}

pub fn this_ta(vm: &mut Vm, v: &Value) -> JsResult<(Obj, TAKind, usize)> {
    match v {
        Value::Obj(o) => {
            let r = match &o.borrow().kind {
                ObjKind::TypedArray(t) => Some((t.kind, t.len(), t.is_out_of_bounds())),
                _ => None,
            };
            match r {
                Some((k, l, oob)) => {
                    if oob {
                        return vm.throw_type("Cannot perform operation on a detached or out-of-bounds TypedArray");
                    }
                    Ok((o.clone(), k, l))
                }
                None => vm.throw_type("method called on a non-TypedArray receiver"),
            }
        }
        _ => vm.throw_type("method called on a non-TypedArray receiver"),
    }
}

pub fn ta_values_vec(o: &Obj) -> Vec<Value> {
    let b = o.borrow();
    match &b.kind {
        ObjKind::TypedArray(t) => {
            let n = t.len();
            let bb = t.buf.borrow();
            (0..n).map(|i| read_elem(&bb.bytes, t.offset + i * t.kind.size(), t.kind, true)).collect()
        }
        _ => Vec::new(),
    }
}

pub fn ta_bytes(o: &Obj) -> Vec<u8> {
    let b = o.borrow();
    match &b.kind {
        ObjKind::TypedArray(t) => {
            let n = t.len() * t.kind.size();
            let bb = t.buf.borrow();
            bb.bytes[t.offset..t.offset + n].to_vec()
        }
        ObjKind::ArrayBuffer(bd) => bd.borrow().bytes.clone(),
        ObjKind::DataView(d) => {
            let bb = d.buf.borrow();
            let l = d.length.unwrap_or(bb.bytes.len() - d.offset);
            bb.bytes[d.offset..d.offset + l].to_vec()
        }
        _ => Vec::new(),
    }
}

fn ta_get(o: &Obj, i: usize) -> Value {
    let b = o.borrow();
    match &b.kind {
        ObjKind::TypedArray(t) => ta_get_index(t, i as f64).unwrap_or(Value::Undefined),
        _ => Value::Undefined,
    }
}

fn ta_species_create(vm: &mut Vm, exemplar: &Obj, kind: TAKind, args: &[Value]) -> JsResult<Obj> {
    let default = Value::Obj(vm.intr.ta_ctors[ta_kind_index(kind)].clone());
    let c = vm.get(exemplar, &vm.intr.key_constructor.clone(), &Value::Obj(exemplar.clone()))?;
    let ctor = if c.is_undefined() {
        default
    } else if let Value::Obj(co) = &c {
        let s = vm.get(co, &PropKey::Sym(vm.intr.sym_species.clone()), &c)?;
        if s.is_nullish() {
            default
        } else {
            s
        }
    } else {
        return vm.throw_type("constructor is not an object");
    };
    let r = vm.construct(&ctor, args, None)?;
    match &r {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_)) => Ok(o.clone()),
        _ => vm.throw_type("species constructor did not return a TypedArray"),
    }
}

fn ta_from(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = a.this.clone();
    if !matches!(&c, Value::Obj(co) if co.is_constructor()) {
        return vm.throw_type("TypedArray.from requires a constructor receiver");
    }
    let mapfn = a.arg(1);
    if !mapfn.is_undefined() && !mapfn.is_callable() {
        return vm.throw_type("mapfn is not callable");
    }
    let src = a.arg(0);
    let im = vm.get_prop_of(&src, &PropKey::Sym(vm.intr.sym_iterator.clone()))?;
    let vals = if !im.is_nullish() {
        vm.iterate_spread(&src, "@@iterator is not callable")?
    } else {
        let so = vm.to_object(&src)?;
        crate::builtins::array::array_like_to_vec(vm, &Value::Obj(so))?
    };
    let t = vm.construct(&c, &[Value::Num(vals.len() as f64)], None)?;
    let to = match &t {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_)) => o.clone(),
        _ => return vm.throw_type("TypedArray constructor did not return a TypedArray"),
    };
    for (i, v) in vals.into_iter().enumerate() {
        let v = if mapfn.is_undefined() { v } else { vm.call(&mapfn, a.arg(2), &[v, Value::Num(i as f64)])? };
        let tv = t.clone();
        vm.set_prop_of(&tv, PropKey::from_index(i as u32), v, true)?;
    }
    Ok(Value::Obj(to))
}

fn ta_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = a.this.clone();
    if !matches!(&c, Value::Obj(co) if co.is_constructor()) {
        return vm.throw_type("TypedArray.of requires a constructor receiver");
    }
    let t = vm.construct(&c, &[Value::Num(a.args.len() as f64)], None)?;
    if !matches!(&t, Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_))) {
        return vm.throw_type("TypedArray constructor did not return a TypedArray");
    }
    for (i, v) in a.args.iter().enumerate() {
        vm.set_prop_of(&t, PropKey::from_index(i as u32), v.clone(), true)?;
    }
    Ok(t)
}

fn ta_length(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match &a.this {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::TypedArray(t) => Ok(Value::Num(t.len() as f64)),
            _ => Err(vm.make_error("TypeError", "TypedArray.prototype accessor called on a non-TypedArray")),
        },
        _ => vm.throw_type("TypedArray.prototype accessor called on a non-TypedArray"),
    }
}
fn ta_byte_length(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match &a.this {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::TypedArray(t) => Ok(Value::Num((t.len() * t.kind.size()) as f64)),
            _ => Err(vm.make_error("TypeError", "TypedArray.prototype accessor called on a non-TypedArray")),
        },
        _ => vm.throw_type("TypedArray.prototype accessor called on a non-TypedArray"),
    }
}
fn ta_byte_offset(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match &a.this {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::TypedArray(t) => Ok(Value::Num(if t.is_out_of_bounds() { 0.0 } else { t.offset as f64 })),
            _ => Err(vm.make_error("TypeError", "TypedArray.prototype accessor called on a non-TypedArray")),
        },
        _ => vm.throw_type("TypedArray.prototype accessor called on a non-TypedArray"),
    }
}
fn ta_buffer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match &a.this {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::TypedArray(t) => Ok(Value::Obj(t.buffer.clone())),
            _ => Err(vm.make_error("TypeError", "TypedArray.prototype accessor called on a non-TypedArray")),
        },
        _ => vm.throw_type("TypedArray.prototype accessor called on a non-TypedArray"),
    }
}
fn ta_tag(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match &a.this {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::TypedArray(t) => Ok(Value::str(t.kind.name())),
            _ => Ok(Value::Undefined),
        },
        _ => Ok(Value::Undefined),
    }
}

fn cb(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.arg(0);
    if !f.is_callable() {
        return vm.throw_type("callback is not a function");
    }
    Ok(f)
}

fn ta_for_each(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, _, len) = this_ta(vm, &a.this)?;
    let f = cb(vm, a)?;
    for i in 0..len {
        let v = ta_get(&o, i);
        vm.call(&f, a.arg(1), &[v, Value::Num(i as f64), a.this.clone()])?;
    }
    Ok(Value::Undefined)
}

fn ta_map(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, k, len) = this_ta(vm, &a.this)?;
    let f = cb(vm, a)?;
    let r = ta_species_create(vm, &o, k, &[Value::Num(len as f64)])?;
    for i in 0..len {
        let v = ta_get(&o, i);
        let m = vm.call(&f, a.arg(1), &[v, Value::Num(i as f64), a.this.clone()])?;
        vm.set_prop_of(&Value::Obj(r.clone()), PropKey::from_index(i as u32), m, true)?;
    }
    Ok(Value::Obj(r))
}

fn ta_filter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, k, len) = this_ta(vm, &a.this)?;
    let f = cb(vm, a)?;
    let mut kept = Vec::new();
    for i in 0..len {
        let v = ta_get(&o, i);
        if vm.call(&f, a.arg(1), &[v.clone(), Value::Num(i as f64), a.this.clone()])?.truthy() {
            kept.push(v);
        }
    }
    let r = ta_species_create(vm, &o, k, &[Value::Num(kept.len() as f64)])?;
    for (i, v) in kept.into_iter().enumerate() {
        vm.set_prop_of(&Value::Obj(r.clone()), PropKey::from_index(i as u32), v, true)?;
    }
    Ok(Value::Obj(r))
}

fn ta_reduce(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, _, len) = this_ta(vm, &a.this)?;
    let f = cb(vm, a)?;
    let mut i = 0;
    let mut acc = if a.args.len() >= 2 {
        a.arg(1)
    } else {
        if len == 0 {
            return vm.throw_type("Reduce of empty array with no initial value");
        }
        i = 1;
        ta_get(&o, 0)
    };
    while i < len {
        let v = ta_get(&o, i);
        acc = vm.call(&f, Value::Undefined, &[acc, v, Value::Num(i as f64), a.this.clone()])?;
        i += 1;
    }
    Ok(acc)
}

fn ta_reduce_right(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, _, len) = this_ta(vm, &a.this)?;
    let f = cb(vm, a)?;
    let mut i = len as i64 - 1;
    let mut acc = if a.args.len() >= 2 {
        a.arg(1)
    } else {
        if len == 0 {
            return vm.throw_type("Reduce of empty array with no initial value");
        }
        i -= 1;
        ta_get(&o, len - 1)
    };
    while i >= 0 {
        let v = ta_get(&o, i as usize);
        acc = vm.call(&f, Value::Undefined, &[acc, v, Value::Num(i as f64), a.this.clone()])?;
        i -= 1;
    }
    Ok(acc)
}

fn ta_some(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, _, len) = this_ta(vm, &a.this)?;
    let f = cb(vm, a)?;
    for i in 0..len {
        let v = ta_get(&o, i);
        if vm.call(&f, a.arg(1), &[v, Value::Num(i as f64), a.this.clone()])?.truthy() {
            return Ok(Value::Bool(true));
        }
    }
    Ok(Value::Bool(false))
}

fn ta_every(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, _, len) = this_ta(vm, &a.this)?;
    let f = cb(vm, a)?;
    for i in 0..len {
        let v = ta_get(&o, i);
        if !vm.call(&f, a.arg(1), &[v, Value::Num(i as f64), a.this.clone()])?.truthy() {
            return Ok(Value::Bool(false));
        }
    }
    Ok(Value::Bool(true))
}

fn ta_find_gen(vm: &mut Vm, a: &Args, rev: bool, idx: bool) -> JsResult<Value> {
    let (o, _, len) = this_ta(vm, &a.this)?;
    let f = cb(vm, a)?;
    for j in 0..len {
        let i = if rev { len - 1 - j } else { j };
        let v = ta_get(&o, i);
        if vm.call(&f, a.arg(1), &[v.clone(), Value::Num(i as f64), a.this.clone()])?.truthy() {
            return Ok(if idx { Value::Num(i as f64) } else { v });
        }
    }
    Ok(if idx { Value::Num(-1.0) } else { Value::Undefined })
}
fn ta_find(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    ta_find_gen(vm, a, false, false)
}
fn ta_find_index(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    ta_find_gen(vm, a, false, true)
}
fn ta_find_last(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    ta_find_gen(vm, a, true, false)
}
fn ta_find_last_index(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    ta_find_gen(vm, a, true, true)
}

fn ta_index_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, _, len) = this_ta(vm, &a.this)?;
    if len == 0 {
        return Ok(Value::Num(-1.0));
    }
    let n = vm.to_integer_or_infinity(&a.arg(1))?;
    let start = if n >= 0.0 { n.min(len as f64) as usize } else { (len as f64 + n).max(0.0) as usize };
    let t = a.arg(0);
    for i in start..len {
        if Value::strict_eq(&ta_get(&o, i), &t) {
            return Ok(Value::Num(i as f64));
        }
    }
    Ok(Value::Num(-1.0))
}

fn ta_last_index_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, _, len) = this_ta(vm, &a.this)?;
    if len == 0 {
        return Ok(Value::Num(-1.0));
    }
    let n = if a.args.len() > 1 { vm.to_integer_or_infinity(&a.arg(1))? } else { len as f64 - 1.0 };
    let mut k: i64 = if n >= 0.0 { n.min(len as f64 - 1.0) as i64 } else { (len as f64 + n) as i64 };
    let t = a.arg(0);
    while k >= 0 {
        if Value::strict_eq(&ta_get(&o, k as usize), &t) {
            return Ok(Value::Num(k as f64));
        }
        k -= 1;
    }
    Ok(Value::Num(-1.0))
}

fn ta_includes(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, _, len) = this_ta(vm, &a.this)?;
    if len == 0 {
        return Ok(Value::Bool(false));
    }
    let n = vm.to_integer_or_infinity(&a.arg(1))?;
    let start = if n >= 0.0 { n.min(len as f64) as usize } else { (len as f64 + n).max(0.0) as usize };
    let t = a.arg(0);
    for i in start..len {
        if Value::same_value_zero(&ta_get(&o, i), &t) {
            return Ok(Value::Bool(true));
        }
    }
    Ok(Value::Bool(false))
}

fn ta_join(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, _, len) = this_ta(vm, &a.this)?;
    let sep = if a.arg(0).is_undefined() { JsStr::from_str(",") } else { vm.to_string(&a.arg(0))? };
    let mut out: Vec<u16> = Vec::new();
    for i in 0..len {
        if i > 0 {
            out.extend_from_slice(sep.units());
        }
        let v = ta_get(&o, i);
        if !v.is_undefined() {
            let s = vm.to_string(&v)?;
            out.extend_from_slice(s.units());
        }
    }
    Ok(Value::Str(JsStr::from_units(out)))
}

fn rel(vm: &mut Vm, v: &Value, len: usize, default: usize) -> JsResult<usize> {
    if v.is_undefined() {
        return Ok(default);
    }
    let n = vm.to_integer_or_infinity(v)?;
    Ok(if n < 0.0 { (len as f64 + n).max(0.0) as usize } else { n.min(len as f64) as usize })
}

fn ta_fill(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, k, len) = this_ta(vm, &a.this)?;
    ta_check_mutable(vm, &o)?;
    let v = if k.is_bigint() { Value::BigInt(vm.to_bigint(&a.arg(0))?) } else { Value::Num(vm.to_number(&a.arg(0))?) };
    let s = rel(vm, &a.arg(1), len, 0)?;
    let e = rel(vm, &a.arg(2), len, len)?;
    for i in s..e {
        ta_set_index(vm, &o, i as f64, &v)?;
    }
    Ok(a.this.clone())
}

fn ta_reverse(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, _, _) = this_ta(vm, &a.this)?;
    ta_check_mutable(vm, &o)?;
    let mut vals = ta_values_vec(&o);
    vals.reverse();
    fill_from_values(vm, &o, &vals)?;
    Ok(a.this.clone())
}

fn ta_sort_vals(vm: &mut Vm, mut vals: Vec<Value>, cmp: &Value) -> JsResult<Vec<Value>> {
    if cmp.is_undefined() {
        vals.sort_by(|x, y| match (x, y) {
            (Value::Num(a), Value::Num(b)) => {
                if a.is_nan() && b.is_nan() {
                    std::cmp::Ordering::Equal
                } else if a.is_nan() {
                    std::cmp::Ordering::Greater
                } else if b.is_nan() {
                    std::cmp::Ordering::Less
                } else if a == b {
                    if *a == 0.0 {
                        b.is_sign_negative().cmp(&a.is_sign_negative())
                    } else {
                        std::cmp::Ordering::Equal
                    }
                } else {
                    a.partial_cmp(b).unwrap()
                }
            }
            (Value::BigInt(a), Value::BigInt(b)) => a.cmp(b),
            _ => std::cmp::Ordering::Equal,
        });
        return Ok(vals);
    }
    // comparator: reuse array sort (undefined handling not relevant)
    let mut v = vals;
    let n = v.len();
    for i in 1..n {
        let mut j = i;
        while j > 0 {
            let r = vm.call(cmp, Value::Undefined, &[v[j - 1].clone(), v[j].clone()])?;
            let x = vm.to_number(&r)?;
            if x > 0.0 {
                v.swap(j - 1, j);
                j -= 1;
            } else {
                break;
            }
        }
    }
    Ok(v)
}

fn ta_sort(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cmp = a.arg(0);
    if !cmp.is_undefined() && !cmp.is_callable() {
        return vm.throw_type("comparefn must be a function");
    }
    let (o, _, _) = this_ta(vm, &a.this)?;
    ta_check_mutable(vm, &o)?;
    let vals = ta_values_vec(&o);
    let sorted = ta_sort_vals(vm, vals, &cmp)?;
    fill_from_values(vm, &o, &sorted)?;
    Ok(a.this.clone())
}

fn ta_to_sorted(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cmp = a.arg(0);
    if !cmp.is_undefined() && !cmp.is_callable() {
        return vm.throw_type("comparefn must be a function");
    }
    let (o, k, len) = this_ta(vm, &a.this)?;
    let vals = ta_values_vec(&o);
    let sorted = ta_sort_vals(vm, vals, &cmp)?;
    let r = create_typed_array(vm, k, len, None)?;
    fill_from_values(vm, &r, &sorted)?;
    Ok(Value::Obj(r))
}

fn ta_to_reversed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, k, len) = this_ta(vm, &a.this)?;
    let mut vals = ta_values_vec(&o);
    vals.reverse();
    let r = create_typed_array(vm, k, len, None)?;
    fill_from_values(vm, &r, &vals)?;
    Ok(Value::Obj(r))
}

fn ta_with(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, k, len) = this_ta(vm, &a.this)?;
    let rel_i = vm.to_integer_or_infinity(&a.arg(0))?;
    let idx = if rel_i >= 0.0 { rel_i } else { len as f64 + rel_i };
    let v = if k.is_bigint() { Value::BigInt(vm.to_bigint(&a.arg(1))?) } else { Value::Num(vm.to_number(&a.arg(1))?) };
    if idx < 0.0 || idx >= len as f64 {
        return vm.throw_range("invalid TypedArray index");
    }
    let mut vals = ta_values_vec(&o);
    vals[idx as usize] = v;
    let r = create_typed_array(vm, k, len, None)?;
    fill_from_values(vm, &r, &vals)?;
    Ok(Value::Obj(r))
}

fn ta_slice(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, k, len) = this_ta(vm, &a.this)?;
    let s = rel(vm, &a.arg(0), len, 0)?;
    let e = rel(vm, &a.arg(1), len, len)?;
    let n = e.saturating_sub(s);
    let r = ta_species_create(vm, &o, k, &[Value::Num(n as f64)])?;
    let vals = ta_values_vec(&o);
    for (j, i) in (s..e).enumerate() {
        if i < vals.len() {
            ta_set_index(vm, &r, j as f64, &vals[i])?;
        }
    }
    Ok(Value::Obj(r))
}

fn ta_at(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, _, len) = this_ta(vm, &a.this)?;
    let n = vm.to_integer_or_infinity(&a.arg(0))?;
    let k = if n >= 0.0 { n } else { len as f64 + n };
    if k < 0.0 || k >= len as f64 {
        return Ok(Value::Undefined);
    }
    Ok(ta_get(&o, k as usize))
}

fn ta_keys(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, _, _) = this_ta(vm, &a.this)?;
    Ok(crate::builtins::iterator::create_array_iterator(vm, Value::Obj(o), 0))
}
fn ta_values(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, _, _) = this_ta(vm, &a.this)?;
    Ok(crate::builtins::iterator::create_array_iterator(vm, Value::Obj(o), 1))
}
fn ta_entries(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, _, _) = this_ta(vm, &a.this)?;
    Ok(crate::builtins::iterator::create_array_iterator(vm, Value::Obj(o), 2))
}

fn ta_copy_within(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, _, len) = this_ta(vm, &a.this)?;
    ta_check_mutable(vm, &o)?;
    let to = rel(vm, &a.arg(0), len, 0)?;
    let from = rel(vm, &a.arg(1), len, 0)?;
    let fin = rel(vm, &a.arg(2), len, len)?;
    let count = fin.saturating_sub(from).min(len - to);
    let vals = ta_values_vec(&o);
    for i in 0..count {
        ta_set_index(vm, &o, (to + i) as f64, &vals[from + i])?;
    }
    Ok(a.this.clone())
}

fn ta_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let is_ta = matches!(&a.this, Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_)));
    if !is_ta {
        return vm.throw_type("set on non-TypedArray");
    }
    let (o, k, len) = this_ta(vm, &a.this).map_err(|_| vm.make_error("TypeError", "TypedArray target is out of bounds"))?;
    ta_check_mutable(vm, &o)?;
    let off = vm.to_integer_or_infinity(&a.arg(1))?;
    if off < 0.0 {
        return vm.throw_range("TypedArray.prototype.set offset is negative");
    }
    let src = a.arg(0);
    let vals = match &src {
        Value::Obj(so) if matches!(so.borrow().kind, ObjKind::TypedArray(_)) => {
            let sk = match &so.borrow().kind {
                ObjKind::TypedArray(t) => t.kind,
                _ => unreachable!(),
            };
            if sk.is_bigint() != k.is_bigint() {
                return vm.throw_type("TypedArray content types (BigInt vs Number) differ");
            }
            ta_values_vec(so)
        }
        _ => {
            if src.is_nullish() {
                return vm.throw_type("TypedArray.prototype.set called on null or undefined");
            }
            let so = vm.to_object(&src)?;
            crate::builtins::array::array_like_to_vec(vm, &Value::Obj(so))?
        }
    };
    if off + vals.len() as f64 > len as f64 {
        return vm.throw_range("source is too large for the target at offset");
    }
    for (i, v) in vals.iter().enumerate() {
        ta_set_index(vm, &o, off + i as f64, v)?;
    }
    Ok(Value::Undefined)
}

fn ta_subarray(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match &a.this {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_)) => o.clone(),
        _ => return vm.throw_type("subarray on non-TypedArray"),
    };
    let (k, len, buffer, offset, tracking) = match &o.borrow().kind {
        ObjKind::TypedArray(t) => (t.kind, t.len(), t.buffer.clone(), t.offset, t.length.is_none()),
        _ => unreachable!(),
    };
    let s = rel(vm, &a.arg(0), len, 0)?;
    let e = rel(vm, &a.arg(1), len, len)?;
    let begin_off = offset + s * k.size();
    let mut args = vec![Value::Obj(buffer), Value::Num(begin_off as f64)];
    if !(tracking && a.arg(1).is_undefined()) {
        args.push(Value::Num(e.saturating_sub(s) as f64));
    }
    Ok(Value::Obj(ta_species_create(vm, &o, k, &args)?))
}

fn ta_to_locale_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, _, len) = this_ta(vm, &a.this)?;
    let mut out: Vec<u16> = Vec::new();
    for i in 0..len {
        if i > 0 {
            out.push(b',' as u16);
        }
        let v = ta_get(&o, i);
        let f = vm.get_prop_of(&v, &PropKey::from_str("toLocaleString"))?;
        let r = vm.call(&f, v, &[])?;
        let s = vm.to_string(&r)?;
        out.extend_from_slice(s.units());
    }
    Ok(Value::Str(JsStr::from_units(out)))
}

// ---------------- Uint8Array base64/hex ----------------

fn this_u8(vm: &mut Vm, v: &Value) -> JsResult<Obj> {
    match v {
        Value::Obj(o) if matches!(&o.borrow().kind, ObjKind::TypedArray(t) if t.kind == TAKind::Uint8) => Ok(o.clone()),
        _ => vm.throw_type("this is not a Uint8Array"),
    }
}

fn u8_to_base64(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_u8(vm, &a.this)?;
    let mut url = false;
    let mut omit = false;
    if let Value::Obj(opts) = a.arg(0) {
        let al = vm.get_str(&opts, "alphabet")?;
        if let Value::Str(s) = al {
            url = s.eq_str("base64url");
        }
        omit = vm.get_str(&opts, "omitPadding")?.truthy();
    }
    let bytes = ta_bytes(&o);
    let mut s = crate::runtime::encoding::base64_encode(&bytes, url);
    if omit {
        while s.ends_with('=') {
            s.pop();
        }
    }
    Ok(Value::str(&s))
}

fn u8_to_hex(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_u8(vm, &a.this)?;
    let bytes = ta_bytes(&o);
    let s: String = bytes.iter().map(|b| format!("{:02x}", b)).collect();
    Ok(Value::str(&s))
}

fn u8_from_base64(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = match a.arg(0) {
        Value::Str(s) => s.to_rust_string(),
        _ => return vm.throw_type("fromBase64 requires a string"),
    };
    match crate::runtime::encoding::base64_decode_strict(&s) {
        Some(b) => Ok(Value::Obj(typed_array_from_bytes(vm, b))),
        None => vm.throw_syntax("invalid base64 string"),
    }
}

fn u8_from_hex(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = match a.arg(0) {
        Value::Str(s) => s.to_rust_string(),
        _ => return vm.throw_type("fromHex requires a string"),
    };
    match crate::runtime::encoding::hex_decode(&s) {
        Some(b) => Ok(Value::Obj(typed_array_from_bytes(vm, b))),
        None => vm.throw_syntax("invalid hex string"),
    }
}

fn u8_set_from(vm: &mut Vm, a: &Args, bytes: Option<Vec<u8>>) -> JsResult<Value> {
    let o = this_u8(vm, &a.this)?;
    let bytes = match bytes {
        Some(b) => b,
        None => return vm.throw_syntax("invalid input string"),
    };
    let len = match &o.borrow().kind {
        ObjKind::TypedArray(t) => t.len(),
        _ => 0,
    };
    let n = bytes.len().min(len);
    for (i, b) in bytes.iter().take(n).enumerate() {
        ta_set_index(vm, &o, i as f64, &Value::Num(*b as f64))?;
    }
    let r = vm.new_object();
    r.set_str("read", Value::Num(0.0), WEC);
    r.set_str("written", Value::Num(n as f64), WEC);
    Ok(Value::Obj(r))
}

fn u8_set_from_base64(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = match a.arg(0) {
        Value::Str(s) => s.to_rust_string(),
        _ => return vm.throw_type("setFromBase64 requires a string"),
    };
    let b = crate::runtime::encoding::base64_decode_strict(&s);
    u8_set_from(vm, a, b)
}

fn u8_set_from_hex(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = match a.arg(0) {
        Value::Str(s) => s.to_rust_string(),
        _ => return vm.throw_type("setFromHex requires a string"),
    };
    let b = crate::runtime::encoding::hex_decode(&s);
    u8_set_from(vm, a, b)
}

// ---------------- Atomics ----------------

fn atomic_target(vm: &mut Vm, a: &Args) -> JsResult<(Obj, TAKind, usize)> {
    let (o, k, len) = match &a.arg(0) {
        Value::Obj(o) => {
            let r = match &o.borrow().kind {
                ObjKind::TypedArray(t) => Some((t.kind, t.len())),
                _ => None,
            };
            match r {
                Some((k, l)) => (o.clone(), k, l),
                None => return vm.throw_type("Atomics: not an integer TypedArray"),
            }
        }
        _ => return vm.throw_type("Atomics: not an integer TypedArray"),
    };
    if matches!(k, TAKind::Float16 | TAKind::Float32 | TAKind::Float64 | TAKind::Uint8C) {
        return vm.throw_type("Atomics requires an integer TypedArray");
    }
    let idx = vm.to_index_msg(&a.arg(1), "Atomics: index out of range")?;
    if idx >= len {
        return vm.throw_range("Atomics: index out of range");
    }
    Ok((o, k, idx))
}

fn atomic_load(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, _, i) = atomic_target(vm, a)?;
    Ok(ta_get(&o, i))
}

fn atomic_store(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, k, i) = atomic_target(vm, a)?;
    let v = if k.is_bigint() { Value::BigInt(vm.to_bigint(&a.arg(2))?) } else { Value::Num(vm.to_integer_or_infinity(&a.arg(2))?) };
    ta_set_index(vm, &o, i as f64, &v)?;
    Ok(v)
}

fn atomic_rmw(vm: &mut Vm, a: &Args, op: u8) -> JsResult<Value> {
    let (o, k, i) = atomic_target(vm, a)?;
    let old = ta_get(&o, i);
    let newv = if k.is_bigint() {
        let x = match &old {
            Value::BigInt(b) => b.clone(),
            _ => unreachable!(),
        };
        let y = vm.to_bigint(&a.arg(2))?;
        Value::BigInt(Rc::new(match op {
            0 => x.add(&y),
            1 => x.bitand(&y),
            2 => (*y).clone(),
            3 => x.bitor(&y),
            4 => x.sub(&y),
            _ => x.bitxor(&y),
        }))
    } else {
        let x = old.as_num().unwrap();
        let y = vm.to_number(&a.arg(2))?;
        use crate::builtins::number::to_int32;
        let (xi, yi) = (x as i64, to_int32(y) as i64);
        Value::Num(match op {
            0 => x + y,
            1 => (xi & yi) as f64,
            2 => y,
            3 => (xi | yi) as f64,
            4 => x - y,
            _ => (xi ^ yi) as f64,
        })
    };
    ta_set_index(vm, &o, i as f64, &newv)?;
    Ok(old)
}

fn atomic_compare_exchange(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, k, i) = atomic_target(vm, a)?;
    let expected = if k.is_bigint() { Value::BigInt(vm.to_bigint(&a.arg(2))?) } else { Value::Num(vm.to_integer_or_infinity(&a.arg(2))?) };
    let replacement = if k.is_bigint() { Value::BigInt(vm.to_bigint(&a.arg(3))?) } else { Value::Num(vm.to_integer_or_infinity(&a.arg(3))?) };
    let old = ta_get(&o, i);
    // compare after conversion to element type
    let tmp = create_typed_array(vm, k, 1, None)?;
    ta_set_index(vm, &tmp, 0.0, &expected)?;
    let exp_conv = ta_get(&tmp, 0);
    if Value::strict_eq(&old, &exp_conv) {
        ta_set_index(vm, &o, i as f64, &replacement)?;
    }
    Ok(old)
}

fn atomic_is_lock_free(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let n = vm.to_integer_or_infinity(&a.arg(0))?;
    Ok(Value::Bool(matches!(n as i64, 1 | 2 | 4 | 8)))
}

fn atomic_wait(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (o, k, i) = atomic_target(vm, a)?;
    if !matches!(k, TAKind::Int32 | TAKind::BigInt64) {
        return vm.throw_type("Atomics.wait/notify requires an Int32Array or BigInt64Array");
    }
    let shared = match &o.borrow().kind {
        ObjKind::TypedArray(t) => t.buf.borrow().shared,
        _ => false,
    };
    if !shared {
        return vm.throw_type("Atomics.wait requires a SharedArrayBuffer-backed array");
    }
    let cur = ta_get(&o, i);
    let v = vm.to_number(&a.arg(2))?;
    if cur.as_num() != Some(v) {
        return Ok(Value::str("not-equal"));
    }
    Ok(Value::str("timed-out"))
}

fn atomic_notify(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let is_ta = matches!(&a.arg(0), Value::Obj(o) if matches!(&o.borrow().kind, ObjKind::TypedArray(t) if matches!(t.kind, TAKind::Int32 | TAKind::BigInt64)));
    if !is_ta {
        return vm.throw_type("Atomics.wait/notify requires an Int32Array or BigInt64Array");
    }
    atomic_target(vm, a)?;
    Ok(Value::Num(0.0))
}
