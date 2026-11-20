// Array constructor and Array.prototype.

use crate::object::*;
use crate::realm::this_obj;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let proto = vm.intr.array_proto.clone();
    let ctor = vm.native_ctor("Array", 1, array_ctor, &proto);
    vm.intr.array_ctor = ctor.clone();
    vm.def_method(&ctor, "isArray", 1, is_array_fn);
    vm.def_method(&ctor, "of", 0, array_of);
    vm.def_method(&ctor, "from", 1, array_from);
    vm.def_method(&ctor, "fromAsync", 1, array_from_async);
    vm.def_sym_getter(&ctor, &vm.intr.sym_species.clone(), "[Symbol.species]", species_getter);
    let methods: &[(&str, u32, NativeFn)] = &[
        ("push", 1, push),
        ("pop", 0, pop),
        ("shift", 0, shift),
        ("unshift", 1, unshift),
        ("slice", 2, slice),
        ("indexOf", 1, index_of),
        ("includes", 1, includes),
        ("join", 1, join),
        ("concat", 1, concat),
        ("forEach", 1, for_each),
        ("map", 1, map),
        ("filter", 1, filter),
        ("reduce", 1, reduce),
        ("reverse", 0, reverse),
        ("toString", 0, to_string),
        ("toLocaleString", 0, to_locale_string),
        ("at", 1, at),
        ("find", 1, find),
        ("findIndex", 1, find_index),
        ("findLast", 1, find_last),
        ("findLastIndex", 1, find_last_index),
        ("some", 1, some),
        ("every", 1, every),
        ("fill", 1, fill),
        ("lastIndexOf", 1, last_index_of),
        ("flat", 0, flat),
        ("flatMap", 1, flat_map),
        ("splice", 2, splice),
        ("sort", 1, sort),
        ("toReversed", 0, to_reversed),
        ("toSorted", 1, to_sorted),
        ("with", 2, with),
        ("toSpliced", 2, to_spliced),
        ("reduceRight", 1, reduce_right),
        ("copyWithin", 2, copy_within),
        ("values", 0, values),
        ("keys", 0, keys),
        ("entries", 0, entries),
    ];
    for (n, l, f) in methods {
        let fo = vm.def_method(&proto, n, *l, *f);
        if *n == "values" {
            vm.intr.array_values = Value::Obj(fo.clone());
            proto.set_prop(PropKey::Sym(vm.intr.sym_iterator.clone()), Value::Obj(fo), WC);
        }
    }
    move_to_end(&proto, &vm.intr.key_constructor.clone());
    let unscopables = Obj::new(None, ObjKind::Ordinary);
    for n in [
        "at", "copyWithin", "entries", "fill", "find", "findIndex", "findLast", "findLastIndex", "flat", "flatMap", "includes", "keys", "toReversed", "toSorted", "toSpliced", "values",
    ] {
        unscopables.set_prop(PropKey::from_str(n), Value::Bool(true), WEC);
    }
    proto.set_prop(PropKey::Sym(vm.intr.sym_unscopables.clone()), Value::Obj(unscopables), CONFIGURABLE);
    vm.def_global("Array", Value::Obj(ctor));
}

fn species_getter(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(a.this.clone())
}

pub fn is_array(vm: &mut Vm, v: &Value) -> JsResult<bool> {
    match v {
        Value::Obj(o) => {
            let b = o.borrow();
            match &b.kind {
                ObjKind::Array(_) => Ok(true),
                ObjKind::Proxy(p) => match &p.target {
                    Some(t) => {
                        let t = t.clone();
                        drop(b);
                        is_array(vm, &Value::Obj(t))
                    }
                    None => {
                        drop(b);
                        vm.throw_type("proxy is revoked")
                    }
                },
                _ => Ok(false),
            }
        }
        _ => Ok(false),
    }
}

fn is_array_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(is_array(vm, &a.arg(0))?))
}

pub fn array_create(vm: &mut Vm, len: u64, proto: Option<Obj>) -> JsResult<Obj> {
    if len > 4294967295 {
        return vm.throw_range("Invalid array length");
    }
    let p = proto.unwrap_or_else(|| vm.intr.array_proto.clone());
    let mut ad = new_array_data(Vec::new());
    ad.len = len as u32;
    Ok(Obj::with_class(Some(p), ObjKind::Array(ad), "Array"))
}

fn array_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = a.new_target.clone().or_else(|| Some(a.callee.clone()));
    let proto = vm.proto_from_nt(&nt, &vm.intr.array_proto.clone())?;
    if a.args.len() == 1 {
        if let Value::Num(n) = a.args[0] {
            let u = crate::builtins::number::to_uint32(n);
            if u as f64 != n {
                return vm.throw_range("Invalid array length");
            }
            return Ok(Value::Obj(array_create(vm, u as u64, Some(proto))?));
        }
        let arr = array_create(vm, 0, Some(proto))?;
        if let ObjKind::Array(ad) = &mut arr.borrow_mut().kind {
            ad.dense.push(a.args[0].clone());
            ad.len = 1;
        }
        return Ok(Value::Obj(arr));
    }
    let arr = array_create(vm, 0, Some(proto))?;
    if let ObjKind::Array(ad) = &mut arr.borrow_mut().kind {
        ad.dense = a.args.to_vec();
        ad.len = a.args.len() as u32;
    }
    Ok(Value::Obj(arr))
}

fn array_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = a.this.clone();
    let arr = if let Value::Obj(co) = &c {
        if co.is_constructor() && !co.ptr_eq(&vm.intr.array_ctor) {
            let r = vm.construct(&c, &[Value::Num(a.args.len() as f64)], None)?;
            r.as_obj().cloned().unwrap()
        } else {
            vm.new_array(Vec::new())
        }
    } else {
        vm.new_array(Vec::new())
    };
    for (i, v) in a.args.iter().enumerate() {
        vm.create_data_property_or_throw(&arr, PropKey::from_index(i as u32), v.clone())?;
    }
    set_length(vm, &arr, a.args.len() as u64)?;
    Ok(Value::Obj(arr))
}

fn array_from(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let items = a.arg(0);
    let mapfn = a.arg(1);
    let this_arg = a.arg(2);
    if !mapfn.is_undefined() && !mapfn.is_callable() {
        return vm.throw_type("Array.from: mapFn is not callable");
    }
    let c = a.this.clone();
    let use_ctor = matches!(&c, Value::Obj(co) if co.is_constructor() && !co.ptr_eq(&vm.intr.array_ctor));
    if items.is_nullish() {
        return vm.throw_type("Array.from called on null or undefined");
    }
    let iter_m = vm.get_prop_of(&items, &PropKey::Sym(vm.intr.sym_iterator.clone()))?;
    if !iter_m.is_nullish() {
        let arr = if use_ctor { vm.construct(&c, &[], None)?.as_obj().cloned().unwrap() } else { vm.new_array(Vec::new()) };
        // fast path
        if !use_ctor && mapfn.is_undefined() && vm.is_plain_array_iteration(&items) {
            let v = vm.iterate_to_vec(&items)?;
            return Ok(Value::Obj(vm.new_array(v)));
        }
        // (the iterator need not be an object; `next` is called when stepping)
        if !iter_m.is_callable() {
            return vm.throw_type("@@iterator is not callable");
        }
        let itv = vm.call(&iter_m, items.clone(), &[])?;
        let next = vm.loose_next(&itv)?;
        let mut k = 0u64;
        loop {
            let v = match vm.iter_step(&itv, &next)? {
                Some(v) => v,
                None => break,
            };
            let v = if mapfn.is_undefined() {
                v
            } else {
                match vm.call(&mapfn, this_arg.clone(), &[v, Value::Num(k as f64)]) {
                    Ok(x) => x,
                    Err(e) => {
                        let _ = vm.iterator_close(&itv);
                        return Err(e);
                    }
                }
            };
            if let Err(e) = vm.create_data_property_or_throw(&arr, PropKey::from_index(k as u32), v) {
                let _ = vm.iterator_close(&itv);
                return Err(e);
            }
            k += 1;
        }
        set_length(vm, &arr, k)?;
        return Ok(Value::Obj(arr));
    }
    let src = vm.to_object(&items)?;
    let len = vm.length_of(&src)?;
    let arr = if use_ctor { vm.construct(&c, &[Value::Num(len as f64)], None)?.as_obj().cloned().unwrap() } else { array_create(vm, len, None)? };
    for k in 0..len {
        let v = vm.get(&src, &PropKey::from_index(k as u32), &Value::Obj(src.clone()))?;
        let v = if mapfn.is_undefined() { v } else { vm.call(&mapfn, this_arg.clone(), &[v, Value::Num(k as f64)])? };
        vm.create_data_property_or_throw(&arr, PropKey::from_index(k as u32), v)?;
    }
    set_length(vm, &arr, len)?;
    Ok(Value::Obj(arr))
}

fn array_from_async(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    crate::builtins::promise::array_from_async(vm, a)
}

pub fn set_length(vm: &mut Vm, o: &Obj, len: u64) -> JsResult<()> {
    vm.set_or_throw(o, vm.intr.key_length.clone(), Value::Num(len as f64))
}

pub fn array_like_to_vec(vm: &mut Vm, v: &Value) -> JsResult<Vec<Value>> {
    let o = match v {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("CreateListFromArrayLike called on non-object"),
    };
    if let ObjKind::Array(ad) = &o.borrow().kind {
        if !ad.sparse {
            let mut out: Vec<Value> = ad.dense.iter().map(|x| if x.is_empty() { Value::Undefined } else { x.clone() }).collect();
            out.resize(ad.len as usize, Value::Undefined);
            // holes may be filled by prototype; ignore (rare)
            return Ok(out);
        }
    }
    let len = vm.length_of(&o)?;
    let mut out = Vec::with_capacity(len.min(1 << 20) as usize);
    for i in 0..len {
        out.push(vm.get(&o, &PropKey::from_index(i as u32), v)?);
    }
    Ok(out)
}

/// Dense snapshot of an array if it is a plain dense array with no holes.
fn dense_snapshot(o: &Obj) -> Option<Vec<Value>> {
    let b = o.borrow();
    match &b.kind {
        ObjKind::Array(ad) if !ad.sparse && ad.dense.len() as u32 == ad.len && !ad.dense.iter().any(|v| v.is_empty()) => Some(ad.dense.clone()),
        _ => None,
    }
}

fn get_idx(vm: &mut Vm, o: &Obj, i: u64) -> JsResult<Value> {
    if let ObjKind::Array(ad) = &o.borrow().kind {
        if !ad.sparse {
            if let Some(v) = ad.dense.get(i as usize) {
                if !v.is_empty() {
                    return Ok(v.clone());
                }
            }
        }
    }
    let k = idx_key(i);
    vm.get(o, &k, &Value::Obj(o.clone()))
}

fn idx_key(i: u64) -> PropKey {
    if i < 4294967295 {
        PropKey::from_index(i as u32)
    } else {
        PropKey::Str(JsStr::from_str(&i.to_string()))
    }
}

fn has_idx(vm: &mut Vm, o: &Obj, i: u64) -> JsResult<bool> {
    if let ObjKind::Array(ad) = &o.borrow().kind {
        if !ad.sparse {
            if let Some(v) = ad.dense.get(i as usize) {
                if !v.is_empty() {
                    return Ok(true);
                }
            }
        }
    }
    vm.has_property(o, &idx_key(i))
}

fn set_idx(vm: &mut Vm, o: &Obj, i: u64, v: Value) -> JsResult<()> {
    vm.set_or_throw(o, idx_key(i), v)
}

fn del_idx(vm: &mut Vm, o: &Obj, i: u64) -> JsResult<()> {
    vm.delete_or_throw(o, &idx_key(i))
}

fn rel_index(vm: &mut Vm, v: &Value, len: u64, default: u64) -> JsResult<u64> {
    if v.is_undefined() {
        return Ok(default);
    }
    let n = vm.to_integer_or_infinity(v)?;
    Ok(if n < 0.0 { (len as f64 + n).max(0.0) as u64 } else { n.min(len as f64) as u64 })
}

fn callback(vm: &mut Vm, a: &Args, name: &str) -> JsResult<Value> {
    let f = a.arg(0);
    if !f.is_callable() {
        return vm.throw_type(format!("Array.prototype.{} callback is not callable", name));
    }
    Ok(f)
}

fn this_array(vm: &mut Vm, a: &Args) -> JsResult<Obj> {
    match &a.this {
        Value::Obj(o) => Ok(o.clone()),
        Value::Undefined | Value::Null => vm.throw_type("Array.prototype method called on null or undefined"),
        other => vm.to_object(other),
    }
}

pub fn array_species_create(vm: &mut Vm, orig: &Obj, len: u64) -> JsResult<Obj> {
    if !is_array(vm, &Value::Obj(orig.clone()))? {
        return array_create(vm, len, None);
    }
    let mut c = vm.get(orig, &vm.intr.key_constructor.clone(), &Value::Obj(orig.clone()))?;
    if let Value::Obj(co) = &c {
        if co.ptr_eq(&vm.intr.array_ctor) {
            return array_create(vm, len, None);
        }
        // another realm's %Array%: create an array of this realm
        if co.is_constructor() {
            let rc = vm.function_realm(co)?;
            if rc != vm.intr.realm_id && vm.realm_array_ctor(rc).map_or(false, |a| a.ptr_eq(co)) {
                return array_create(vm, len, None);
            }
        }
        let s = vm.get(co, &PropKey::Sym(vm.intr.sym_species.clone()), &c)?;
        c = if s.is_null() { Value::Undefined } else { s };
    }
    if c.is_undefined() {
        return array_create(vm, len, None);
    }
    if !matches!(&c, Value::Obj(co) if co.is_constructor()) {
        return vm.throw_type("object constructor is not a constructor");
    }
    let r = vm.construct(&c, &[Value::Num(len as f64)], None)?;
    match r {
        Value::Obj(o) => Ok(o),
        _ => vm.throw_type("species constructor returned non-object"),
    }
}

fn push(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    {
        let mut b = o.borrow_mut();
        if let ObjKind::Array(ad) = &mut b.kind {
            // (the reference engine's dense fast path appends even to non-extensible arrays)
            if !ad.sparse && ad.length_writable && ad.dense.len() as u32 == ad.len {
                if ad.len as u64 + a.args.len() as u64 > 4294967295 {
                    drop(b);
                    return vm.throw_type("Pushing elements past 2^32-1 length");
                }
                ad.dense.extend_from_slice(a.args);
                ad.len = ad.dense.len() as u32;
                return Ok(Value::Num(ad.len as f64));
            }
        }
    }
    let len = vm.length_of(&o)?;
    if len + a.args.len() as u64 > 9007199254740991 {
        return vm.throw_type("Pushing elements past 2^53-1 length");
    }
    // the reference engine appends to (sealed / preventExtensions) arrays with a writable
    // length even when they are non-extensible
    let force_append = matches!(&o.borrow().kind, ObjKind::Array(ad) if ad.length_writable && ad.sparse) && !o.borrow().extensible;
    for (i, v) in a.args.iter().enumerate() {
        let k = idx_key(len + i as u64);
        if force_append && vm.ordinary_get_own(&o, &k).is_none() {
            if let Some(idx) = k.as_index() {
                o.borrow_mut().props.insert(k.clone(), Prop::Data { value: v.clone(), flags: WEC });
                if let ObjKind::Array(ad) = &mut o.borrow_mut().kind {
                    if ad.len < idx + 1 {
                        ad.len = idx + 1;
                    }
                }
                continue;
            }
        }
        set_idx(vm, &o, len + i as u64, v.clone())?;
    }
    let nl = len + a.args.len() as u64;
    set_length(vm, &o, nl)?;
    Ok(Value::Num(nl as f64))
}

fn pop(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    {
        let mut b = o.borrow_mut();
        if let ObjKind::Array(ad) = &mut b.kind {
            if !ad.sparse && ad.length_writable && ad.dense.len() as u32 == ad.len && !ad.dense.is_empty() {
                let v = ad.dense.pop().unwrap();
                ad.len -= 1;
                if !v.is_empty() {
                    return Ok(v);
                }
                drop(b);
                // hole: read through prototype
                let len = vm.length_of(&o)?;
                return get_idx(vm, &o, len);
            }
        }
    }
    let len = vm.length_of(&o)?;
    if len == 0 {
        set_length(vm, &o, 0)?;
        return Ok(Value::Undefined);
    }
    let v = get_idx(vm, &o, len - 1)?;
    del_idx(vm, &o, len - 1)?;
    set_length(vm, &o, len - 1)?;
    Ok(v)
}

fn shift(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    {
        let mut b = o.borrow_mut();
        if let ObjKind::Array(ad) = &mut b.kind {
            if !ad.sparse && ad.length_writable && ad.dense.len() as u32 == ad.len && !ad.dense.iter().any(|v| v.is_empty()) {
                if ad.dense.is_empty() {
                    return Ok(Value::Undefined);
                }
                let v = ad.dense.remove(0);
                ad.len -= 1;
                return Ok(v);
            }
        }
    }
    let len = vm.length_of(&o)?;
    if len == 0 {
        set_length(vm, &o, 0)?;
        return Ok(Value::Undefined);
    }
    let first = get_idx(vm, &o, 0)?;
    for k in 1..len {
        if has_idx(vm, &o, k)? {
            let v = get_idx(vm, &o, k)?;
            set_idx(vm, &o, k - 1, v)?;
        } else {
            del_idx(vm, &o, k - 1)?;
        }
    }
    del_idx(vm, &o, len - 1)?;
    set_length(vm, &o, len - 1)?;
    Ok(first)
}

fn unshift(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    {
        let mut b = o.borrow_mut();
        let ext = b.extensible;
        if let ObjKind::Array(ad) = &mut b.kind {
            if !ad.sparse && ext && ad.length_writable && ad.dense.len() as u32 == ad.len && !ad.dense.iter().any(|v| v.is_empty()) {
                let mut nv = a.args.to_vec();
                nv.append(&mut ad.dense);
                ad.dense = nv;
                ad.len = ad.dense.len() as u32;
                return Ok(Value::Num(ad.len as f64));
            }
        }
    }
    let len = vm.length_of(&o)?;
    let n = a.args.len() as u64;
    if n > 0 {
        if len + n > 9007199254740991 {
            return vm.throw_type("Unshift past 2^53-1 length");
        }
        let mut k = len;
        while k > 0 {
            let from = k - 1;
            let to = k + n - 1;
            if has_idx(vm, &o, from)? {
                let v = get_idx(vm, &o, from)?;
                set_idx(vm, &o, to, v)?;
            } else {
                del_idx(vm, &o, to)?;
            }
            k -= 1;
        }
        for (j, v) in a.args.iter().enumerate() {
            set_idx(vm, &o, j as u64, v.clone())?;
        }
    }
    set_length(vm, &o, len + n)?;
    Ok(Value::Num((len + n) as f64))
}

fn slice(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let start = rel_index(vm, &a.arg(0), len, 0)?;
    let end = rel_index(vm, &a.arg(1), len, len)?;
    let count = end.saturating_sub(start);
    let plain = {
        let b = o.borrow();
        matches!(&b.kind, ObjKind::Array(ad) if !ad.sparse) && b.proto.as_ref().map_or(false, |p| p.ptr_eq(&vm.intr.array_proto)) && !b.props.contains(&vm.intr.key_constructor)
    };
    if plain {
        let b = o.borrow();
        if let ObjKind::Array(ad) = &b.kind {
            let mut out = Vec::with_capacity(count as usize);
            for i in start..end {
                out.push(ad.dense.get(i as usize).cloned().unwrap_or(Value::Empty));
            }
            let has_holes = out.iter().any(|v| v.is_empty());
            drop(b);
            let arr = vm.new_array(out);
            if has_holes {
                // holes stay holes
                if let ObjKind::Array(nd) = &mut arr.borrow_mut().kind {
                    while matches!(nd.dense.last(), Some(Value::Empty)) {
                        nd.dense.pop();
                    }
                    nd.len = count as u32;
                }
            }
            return Ok(Value::Obj(arr));
        }
    }
    let arr = array_species_create(vm, &o, count)?;
    let mut n = 0u64;
    for k in start..end {
        if has_idx(vm, &o, k)? {
            let v = get_idx(vm, &o, k)?;
            vm.create_data_property_or_throw(&arr, idx_key(n), v)?;
        }
        n += 1;
    }
    set_length(vm, &arr, n)?;
    Ok(Value::Obj(arr))
}

fn index_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    if len == 0 {
        return Ok(Value::Num(-1.0));
    }
    let n = vm.to_integer_or_infinity(&a.arg(1))?;
    if n >= len as f64 {
        return Ok(Value::Num(-1.0));
    }
    let start = if n >= 0.0 { n as u64 } else { (len as f64 + n).max(0.0) as u64 };
    let target = a.arg(0);
    if let Some(d) = dense_snapshot(&o) {
        for i in start as usize..d.len() {
            if Value::strict_eq(&d[i], &target) {
                return Ok(Value::Num(i as f64));
            }
        }
        return Ok(Value::Num(-1.0));
    }
    for k in start..len {
        if has_idx(vm, &o, k)? {
            let v = get_idx(vm, &o, k)?;
            if Value::strict_eq(&v, &target) {
                return Ok(Value::Num(k as f64));
            }
        }
    }
    Ok(Value::Num(-1.0))
}

fn last_index_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    if len == 0 {
        return Ok(Value::Num(-1.0));
    }
    let n = if a.args.len() > 1 { vm.to_integer_or_infinity(&a.arg(1))? } else { len as f64 - 1.0 };
    let start: i64 = if n >= 0.0 { n.min(len as f64 - 1.0) as i64 } else { (len as f64 + n) as i64 };
    let target = a.arg(0);
    let mut k = start;
    while k >= 0 {
        if has_idx(vm, &o, k as u64)? {
            let v = get_idx(vm, &o, k as u64)?;
            if Value::strict_eq(&v, &target) {
                return Ok(Value::Num(k as f64));
            }
        }
        k -= 1;
    }
    Ok(Value::Num(-1.0))
}

fn includes(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    if len == 0 {
        return Ok(Value::Bool(false));
    }
    let n = vm.to_integer_or_infinity(&a.arg(1))?;
    let start = if n >= 0.0 { n.min(len as f64) as u64 } else { (len as f64 + n).max(0.0) as u64 };
    let target = a.arg(0);
    for k in start..len {
        let v = get_idx(vm, &o, k)?;
        if Value::same_value_zero(&v, &target) {
            return Ok(Value::Bool(true));
        }
    }
    Ok(Value::Bool(false))
}

pub fn join_impl(vm: &mut Vm, o: &Obj, sep: &JsStr) -> JsResult<JsStr> {
    let len = vm.length_of(o)?;
    let mut out: Vec<u16> = Vec::new();
    vm.enter()?;
    let r = (|| -> JsResult<()> {
        for k in 0..len {
            if k > 0 {
                out.extend_from_slice(sep.units());
            }
            let v = get_idx(vm, o, k)?;
            if !v.is_nullish() {
                let s = vm.to_string(&v)?;
                out.extend_from_slice(s.units());
            }
        }
        Ok(())
    })();
    vm.depth -= 1;
    r?;
    Ok(JsStr::from_units(out))
}

fn join(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let sep = if a.arg(0).is_undefined() { JsStr::from_str(",") } else { vm.to_string(&a.arg(0))? };
    Ok(Value::Str(join_impl(vm, &o, &sep)?))
}

fn to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let j = vm.get(&o, &PropKey::from_str("join"), &Value::Obj(o.clone()))?;
    if j.is_callable() {
        return vm.call(&j, Value::Obj(o), &[]);
    }
    let f = vm.intr.object_proto.get_own_str("toString").unwrap_or(Value::Undefined);
    vm.call(&f, Value::Obj(o), &[])
}

fn to_locale_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let mut out: Vec<u16> = Vec::new();
    for k in 0..len {
        if k > 0 {
            out.push(b',' as u16);
        }
        let v = get_idx(vm, &o, k)?;
        if !v.is_nullish() {
            let f = vm.get_prop_of(&v, &PropKey::from_str("toLocaleString"))?;
            let r = vm.call(&f, v, &[])?;
            let s = vm.to_string(&r)?;
            out.extend_from_slice(s.units());
        }
    }
    Ok(Value::Str(JsStr::from_units(out)))
}

fn is_concat_spreadable(vm: &mut Vm, v: &Value) -> JsResult<bool> {
    let o = match v {
        Value::Obj(o) => o.clone(),
        _ => return Ok(false),
    };
    let s = vm.get(&o, &PropKey::Sym(vm.intr.sym_is_concat_spreadable.clone()), v)?;
    if !s.is_undefined() {
        return Ok(s.truthy());
    }
    is_array(vm, v)
}

fn concat(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let arr = array_species_create(vm, &o, 0)?;
    let mut n: u64 = 0;
    let mut items = vec![Value::Obj(o)];
    items.extend_from_slice(a.args);
    for e in items {
        if is_concat_spreadable(vm, &e)? {
            let eo = e.as_obj().unwrap().clone();
            let len = vm.length_of(&eo)?;
            if n + len > 9007199254740991 {
                return vm.throw_type("Concatenated array length exceeds 2^53-1");
            }
            if let Some(d) = dense_snapshot(&eo) {
                for v in d {
                    vm.create_data_property_or_throw(&arr, idx_key(n), v)?;
                    n += 1;
                }
                continue;
            }
            for k in 0..len {
                if has_idx(vm, &eo, k)? {
                    let v = get_idx(vm, &eo, k)?;
                    vm.create_data_property_or_throw(&arr, idx_key(n), v)?;
                }
                n += 1;
            }
        } else {
            vm.create_data_property_or_throw(&arr, idx_key(n), e)?;
            n += 1;
        }
    }
    set_length(vm, &arr, n)?;
    Ok(Value::Obj(arr))
}

fn for_each(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let f = callback(vm, a, "forEach")?;
    let t = a.arg(1);
    let ov = Value::Obj(o.clone());
    for k in 0..len {
        if has_idx(vm, &o, k)? {
            let v = get_idx(vm, &o, k)?;
            vm.call(&f, t.clone(), &[v, Value::Num(k as f64), ov.clone()])?;
        }
    }
    Ok(Value::Undefined)
}

fn map(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let f = callback(vm, a, "map")?;
    let t = a.arg(1);
    let arr = array_species_create(vm, &o, len)?;
    let ov = Value::Obj(o.clone());
    for k in 0..len {
        if has_idx(vm, &o, k)? {
            let v = get_idx(vm, &o, k)?;
            let r = vm.call(&f, t.clone(), &[v, Value::Num(k as f64), ov.clone()])?;
            vm.create_data_property_or_throw(&arr, idx_key(k), r)?;
        }
    }
    Ok(Value::Obj(arr))
}

fn filter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let f = callback(vm, a, "filter")?;
    let t = a.arg(1);
    let arr = array_species_create(vm, &o, 0)?;
    let ov = Value::Obj(o.clone());
    let mut n = 0u64;
    for k in 0..len {
        if has_idx(vm, &o, k)? {
            let v = get_idx(vm, &o, k)?;
            let r = vm.call(&f, t.clone(), &[v.clone(), Value::Num(k as f64), ov.clone()])?;
            if r.truthy() {
                vm.create_data_property_or_throw(&arr, idx_key(n), v)?;
                n += 1;
            }
        }
    }
    Ok(Value::Obj(arr))
}

fn reduce(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let f = callback(vm, a, "reduce")?;
    let ov = Value::Obj(o.clone());
    let mut k = 0u64;
    let mut acc = if a.args.len() >= 2 {
        a.arg(1)
    } else {
        let mut found = None;
        while k < len {
            if has_idx(vm, &o, k)? {
                found = Some(get_idx(vm, &o, k)?);
                k += 1;
                break;
            }
            k += 1;
        }
        match found {
            Some(v) => v,
            None => return vm.throw_type("Reduce of empty array with no initial value"),
        }
    };
    while k < len {
        if has_idx(vm, &o, k)? {
            let v = get_idx(vm, &o, k)?;
            acc = vm.call(&f, Value::Undefined, &[acc, v, Value::Num(k as f64), ov.clone()])?;
        }
        k += 1;
    }
    Ok(acc)
}

fn reduce_right(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let f = callback(vm, a, "reduceRight")?;
    let ov = Value::Obj(o.clone());
    let mut k = len as i64 - 1;
    let mut acc = if a.args.len() >= 2 {
        a.arg(1)
    } else {
        let mut found = None;
        while k >= 0 {
            if has_idx(vm, &o, k as u64)? {
                found = Some(get_idx(vm, &o, k as u64)?);
                k -= 1;
                break;
            }
            k -= 1;
        }
        match found {
            Some(v) => v,
            None => return vm.throw_type("Reduce of empty array with no initial value"),
        }
    };
    while k >= 0 {
        if has_idx(vm, &o, k as u64)? {
            let v = get_idx(vm, &o, k as u64)?;
            acc = vm.call(&f, Value::Undefined, &[acc, v, Value::Num(k as f64), ov.clone()])?;
        }
        k -= 1;
    }
    Ok(acc)
}

fn reverse(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    {
        let mut b = o.borrow_mut();
        if let ObjKind::Array(ad) = &mut b.kind {
            if !ad.sparse && ad.dense.len() as u32 == ad.len && !ad.dense.iter().any(|v| v.is_empty()) {
                ad.dense.reverse();
                drop(b);
                return Ok(Value::Obj(o));
            }
        }
    }
    let len = vm.length_of(&o)?;
    let mut lower = 0u64;
    while lower < len / 2 {
        let upper = len - lower - 1;
        let le = has_idx(vm, &o, lower)?;
        let lv = if le { get_idx(vm, &o, lower)? } else { Value::Undefined };
        let ue = has_idx(vm, &o, upper)?;
        let uv = if ue { get_idx(vm, &o, upper)? } else { Value::Undefined };
        match (le, ue) {
            (true, true) => {
                set_idx(vm, &o, lower, uv)?;
                set_idx(vm, &o, upper, lv)?;
            }
            (false, true) => {
                set_idx(vm, &o, lower, uv)?;
                del_idx(vm, &o, upper)?;
            }
            (true, false) => {
                del_idx(vm, &o, lower)?;
                set_idx(vm, &o, upper, lv)?;
            }
            _ => {}
        }
        lower += 1;
    }
    Ok(Value::Obj(o))
}

fn at(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let n = vm.to_integer_or_infinity(&a.arg(0))?;
    let k = if n >= 0.0 { n } else { len as f64 + n };
    if k < 0.0 || k >= len as f64 {
        return Ok(Value::Undefined);
    }
    get_idx(vm, &o, k as u64)
}

fn find_generic(vm: &mut Vm, a: &Args, from_end: bool, want_index: bool) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let f = a.arg(0);
    if !f.is_callable() {
        return vm.throw_type("predicate is not callable");
    }
    let t = a.arg(1);
    let ov = Value::Obj(o.clone());
    for i in 0..len {
        let k = if from_end { len - 1 - i } else { i };
        let v = get_idx(vm, &o, k)?;
        let r = vm.call(&f, t.clone(), &[v.clone(), Value::Num(k as f64), ov.clone()])?;
        if r.truthy() {
            return Ok(if want_index { Value::Num(k as f64) } else { v });
        }
    }
    Ok(if want_index { Value::Num(-1.0) } else { Value::Undefined })
}

fn find(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    find_generic(vm, a, false, false)
}
fn find_index(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    find_generic(vm, a, false, true)
}
fn find_last(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    find_generic(vm, a, true, false)
}
fn find_last_index(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    find_generic(vm, a, true, true)
}

fn some(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let f = a.arg(0);
    if !f.is_callable() {
        return vm.throw_type("predicate is not callable");
    }
    let t = a.arg(1);
    let ov = Value::Obj(o.clone());
    for k in 0..len {
        if has_idx(vm, &o, k)? {
            let v = get_idx(vm, &o, k)?;
            if vm.call(&f, t.clone(), &[v, Value::Num(k as f64), ov.clone()])?.truthy() {
                return Ok(Value::Bool(true));
            }
        }
    }
    Ok(Value::Bool(false))
}

fn every(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let f = a.arg(0);
    if !f.is_callable() {
        return vm.throw_type("predicate is not callable");
    }
    let t = a.arg(1);
    let ov = Value::Obj(o.clone());
    for k in 0..len {
        if has_idx(vm, &o, k)? {
            let v = get_idx(vm, &o, k)?;
            if !vm.call(&f, t.clone(), &[v, Value::Num(k as f64), ov.clone()])?.truthy() {
                return Ok(Value::Bool(false));
            }
        }
    }
    Ok(Value::Bool(true))
}

fn fill(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let start = rel_index(vm, &a.arg(1), len, 0)?;
    let end = rel_index(vm, &a.arg(2), len, len)?;
    let v = a.arg(0);
    {
        let mut b = o.borrow_mut();
        let ext = b.extensible;
        if let ObjKind::Array(ad) = &mut b.kind {
            if !ad.sparse && ext && (end as usize) <= ad.len as usize {
                if ad.dense.len() < end as usize {
                    ad.dense.resize(end as usize, Value::Empty);
                }
                for i in start..end {
                    ad.dense[i as usize] = v.clone();
                }
                drop(b);
                return Ok(Value::Obj(o));
            }
        }
    }
    for k in start..end {
        set_idx(vm, &o, k, v.clone())?;
    }
    Ok(Value::Obj(o))
}

fn flatten_into(vm: &mut Vm, target: &Obj, src: &Obj, src_len: u64, start: u64, depth: f64, mapper: Option<(&Value, &Value)>) -> JsResult<u64> {
    let mut ti = start;
    let sv = Value::Obj(src.clone());
    for si in 0..src_len {
        if !has_idx(vm, src, si)? {
            continue;
        }
        let mut el = get_idx(vm, src, si)?;
        if let Some((f, t)) = mapper {
            el = vm.call(f, t.clone(), &[el, Value::Num(si as f64), sv.clone()])?;
        }
        let should_flatten = depth > 0.0 && is_array(vm, &el)?;
        if should_flatten {
            let eo = el.as_obj().unwrap().clone();
            let el_len = vm.length_of(&eo)?;
            vm.enter()?;
            let r = flatten_into(vm, target, &eo, el_len, ti, depth - 1.0, None);
            vm.depth -= 1;
            ti = r?;
        } else {
            vm.create_data_property_or_throw(target, idx_key(ti), el)?;
            ti += 1;
        }
    }
    Ok(ti)
}

fn flat(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let depth = if a.arg(0).is_undefined() {
        1.0
    } else {
        let d = vm.to_integer_or_infinity(&a.arg(0))?;
        if d < 0.0 {
            0.0
        } else {
            d
        }
    };
    let arr = array_species_create(vm, &o, 0)?;
    flatten_into(vm, &arr, &o, len, 0, depth, None)?;
    Ok(Value::Obj(arr))
}

fn flat_map(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let f = a.arg(0);
    if !f.is_callable() {
        return vm.throw_type("Array.prototype.flatMap mapper is not callable");
    }
    let t = a.arg(1);
    let arr = array_species_create(vm, &o, 0)?;
    flatten_into(vm, &arr, &o, len, 0, 1.0, Some((&f, &t)))?;
    Ok(Value::Obj(arr))
}

fn splice(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let start = rel_index(vm, &a.arg(0), len, 0)?;
    let del_count = if a.args.is_empty() {
        0
    } else if a.args.len() == 1 {
        len - start
    } else {
        let dc = vm.to_integer_or_infinity(&a.arg(1))?;
        dc.max(0.0).min((len - start) as f64) as u64
    };
    let items: Vec<Value> = if a.args.len() > 2 { a.args[2..].to_vec() } else { Vec::new() };
    if len + items.len() as u64 - del_count > 9007199254740991 {
        return vm.throw_type("Splice result exceeds 2^53-1 length");
    }
    // fast path for plain dense arrays
    let plain = {
        let b = o.borrow();
        let ok_proto = b.proto.as_ref().map_or(false, |p| p.ptr_eq(&vm.intr.array_proto)) && !b.props.contains(&vm.intr.key_constructor);
        b.extensible && ok_proto && matches!(&b.kind, ObjKind::Array(ad) if !ad.sparse && ad.length_writable && ad.dense.len() as u32 == ad.len && !ad.dense.iter().any(|v| v.is_empty()))
    };
    if plain {
        let removed: Vec<Value> = {
            let mut b = o.borrow_mut();
            if let ObjKind::Array(ad) = &mut b.kind {
                let r: Vec<Value> = ad.dense.splice(start as usize..(start + del_count) as usize, items).collect();
                ad.len = ad.dense.len() as u32;
                r
            } else {
                Vec::new()
            }
        };
        return Ok(Value::Obj(vm.new_array(removed)));
    }
    let removed = array_species_create(vm, &o, del_count)?;
    for k in 0..del_count {
        if has_idx(vm, &o, start + k)? {
            let v = get_idx(vm, &o, start + k)?;
            vm.create_data_property_or_throw(&removed, idx_key(k), v)?;
        }
    }
    set_length(vm, &removed, del_count)?;
    let item_count = items.len() as u64;
    if item_count < del_count {
        for k in start..(len - del_count) {
            let from = k + del_count;
            let to = k + item_count;
            if has_idx(vm, &o, from)? {
                let v = get_idx(vm, &o, from)?;
                set_idx(vm, &o, to, v)?;
            } else {
                del_idx(vm, &o, to)?;
            }
        }
        let mut k = len;
        while k > len - del_count + item_count {
            del_idx(vm, &o, k - 1)?;
            k -= 1;
        }
    } else if item_count > del_count {
        let mut k = len - del_count;
        while k > start {
            let from = k + del_count - 1;
            let to = k + item_count - 1;
            if has_idx(vm, &o, from)? {
                let v = get_idx(vm, &o, from)?;
                set_idx(vm, &o, to, v)?;
            } else {
                del_idx(vm, &o, to)?;
            }
            k -= 1;
        }
    }
    for (i, v) in items.into_iter().enumerate() {
        set_idx(vm, &o, start + i as u64, v)?;
    }
    set_length(vm, &o, len - del_count + item_count)?;
    Ok(Value::Obj(removed))
}

pub fn sort_values(vm: &mut Vm, mut v: Vec<Value>, cmp: &Value) -> JsResult<Vec<Value>> {
    // merge sort (stable), with comparator possibly throwing
    fn compare(vm: &mut Vm, a: &Value, b: &Value, cmp: &Value) -> JsResult<bool> {
        // returns true if a > b (should swap)
        if a.is_undefined() {
            return Ok(!b.is_undefined());
        }
        if b.is_undefined() {
            return Ok(false);
        }
        if !cmp.is_undefined() {
            let r = vm.call(cmp, Value::Undefined, &[a.clone(), b.clone()])?;
            let n = vm.to_number(&r)?;
            return Ok(n > 0.0);
        }
        if let (Value::Num(x), Value::Num(y)) = (a, b) {
            if x.fract() == 0.0 && y.fract() == 0.0 && x.abs() < 1e15 && y.abs() < 1e15 && *x >= 0.0 && *y >= 0.0 {
                // string comparison of non-negative integers
                let sx = crate::numconv::number_to_string(*x);
                let sy = crate::numconv::number_to_string(*y);
                return Ok(sx > sy);
            }
        }
        let sa = vm.to_string(a)?;
        let sb = vm.to_string(b)?;
        Ok(sa.units() > sb.units())
    }
    let n = v.len();
    if n < 2 {
        return Ok(v);
    }
    // insertion sort for small arrays
    if n <= 10 {
        for i in 1..n {
            let mut j = i;
            while j > 0 && compare(vm, &v[j - 1], &v[j], cmp)? {
                v.swap(j - 1, j);
                j -= 1;
            }
        }
        return Ok(v);
    }
    let mut buf = v.clone();
    let mut width = 1;
    // bottom-up merge sort
    let mut src = v;
    while width < n {
        let mut i = 0;
        while i < n {
            let mid = (i + width).min(n);
            let hi = (i + 2 * width).min(n);
            let (mut l, mut r, mut k) = (i, mid, i);
            while l < mid && r < hi {
                if compare(vm, &src[l], &src[r], cmp)? {
                    buf[k] = src[r].clone();
                    r += 1;
                } else {
                    buf[k] = src[l].clone();
                    l += 1;
                }
                k += 1;
            }
            while l < mid {
                buf[k] = src[l].clone();
                l += 1;
                k += 1;
            }
            while r < hi {
                buf[k] = src[r].clone();
                r += 1;
                k += 1;
            }
            i += 2 * width;
        }
        std::mem::swap(&mut src, &mut buf);
        width *= 2;
    }
    Ok(src)
}

fn sort(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cmp = a.arg(0);
    if !cmp.is_undefined() && !cmp.is_callable() {
        return vm.throw_type("the comparator must be a function or undefined");
    }
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let mut vals = Vec::new();
    for k in 0..len {
        if has_idx(vm, &o, k)? {
            vals.push(get_idx(vm, &o, k)?);
        }
    }
    let n = vals.len() as u64;
    let sorted = sort_values(vm, vals, &cmp)?;
    for (i, v) in sorted.into_iter().enumerate() {
        if !vm.set(&o, idx_key(i as u64), v, &Value::Obj(o.clone()))? {
            if vm.caller_strict() {
                let msg = vm.set_failure_message(&o, &idx_key(i as u64))?;
                return vm.throw_type(msg);
            }
            return vm.throw_type(format!("cannot assign to read-only element {}", i));
        }
    }
    for k in n..len {
        if has_idx(vm, &o, k)? {
            del_idx(vm, &o, k)?;
        }
    }
    Ok(Value::Obj(o))
}

fn to_sorted(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cmp = a.arg(0);
    if !cmp.is_undefined() && !cmp.is_callable() {
        return vm.throw_type("comparator is not callable");
    }
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    if len > 4294967295 {
        return vm.throw_range("Invalid array length");
    }
    let mut vals = Vec::new();
    for k in 0..len {
        vals.push(get_idx(vm, &o, k)?);
    }
    let sorted = sort_values(vm, vals, &cmp)?;
    Ok(Value::Obj(vm.new_array(sorted)))
}

fn to_reversed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    if len > 4294967295 {
        return vm.throw_range("Invalid array length");
    }
    let mut vals = Vec::new();
    for k in (0..len).rev() {
        vals.push(get_idx(vm, &o, k)?);
    }
    Ok(Value::Obj(vm.new_array(vals)))
}

fn with(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let rel = vm.to_integer_or_infinity(&a.arg(0))?;
    let idx = if rel >= 0.0 { rel } else { len as f64 + rel };
    if idx >= len as f64 || idx < 0.0 {
        return vm.throw_range("invalid index");
    }
    if len > 4294967295 {
        return vm.throw_range("Invalid array length");
    }
    let mut vals = Vec::new();
    for k in 0..len {
        if k == idx as u64 {
            vals.push(a.arg(1));
        } else {
            vals.push(get_idx(vm, &o, k)?);
        }
    }
    Ok(Value::Obj(vm.new_array(vals)))
}

fn to_spliced(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let start = rel_index(vm, &a.arg(0), len, 0)?;
    let skip = if a.args.is_empty() {
        0
    } else if a.args.len() == 1 {
        len - start
    } else {
        let dc = vm.to_integer_or_infinity(&a.arg(1))?;
        dc.max(0.0).min((len - start) as f64) as u64
    };
    let items: Vec<Value> = if a.args.len() > 2 { a.args[2..].to_vec() } else { Vec::new() };
    let new_len = len + items.len() as u64 - skip;
    if new_len > 9007199254740991 {
        return vm.throw_type("Invalid array length");
    }
    if new_len > 4294967295 {
        return vm.throw_range("Invalid array length");
    }
    let mut vals = Vec::new();
    for k in 0..start {
        vals.push(get_idx(vm, &o, k)?);
    }
    vals.extend(items);
    for k in (start + skip)..len {
        vals.push(get_idx(vm, &o, k)?);
    }
    Ok(Value::Obj(vm.new_array(vals)))
}

fn copy_within(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    let len = vm.length_of(&o)?;
    let to = rel_index(vm, &a.arg(0), len, 0)?;
    let from = rel_index(vm, &a.arg(1), len, 0)?;
    let fin = rel_index(vm, &a.arg(2), len, len)?;
    let count = (fin.saturating_sub(from)).min(len - to);
    if count == 0 {
        return Ok(Value::Obj(o));
    }
    let (mut f, mut t, dir): (i64, i64, i64) = if from < to && to < from + count {
        ((from + count - 1) as i64, (to + count - 1) as i64, -1)
    } else {
        (from as i64, to as i64, 1)
    };
    for _ in 0..count {
        if has_idx(vm, &o, f as u64)? {
            let v = get_idx(vm, &o, f as u64)?;
            set_idx(vm, &o, t as u64, v)?;
        } else {
            del_idx(vm, &o, t as u64)?;
        }
        f += dir;
        t += dir;
    }
    Ok(Value::Obj(o))
}

fn values(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    Ok(crate::builtins::iterator::create_array_iterator(vm, Value::Obj(o), 1))
}
fn keys(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    Ok(crate::builtins::iterator::create_array_iterator(vm, Value::Obj(o), 0))
}
fn entries(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_array(vm, a)?;
    Ok(crate::builtins::iterator::create_array_iterator(vm, Value::Obj(o), 2))
}
