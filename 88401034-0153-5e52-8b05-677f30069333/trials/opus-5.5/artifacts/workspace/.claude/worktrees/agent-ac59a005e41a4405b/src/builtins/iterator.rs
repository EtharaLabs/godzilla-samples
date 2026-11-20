// Iterator prototypes, builtin iterators and iterator helpers.

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let ip = vm.intr.iterator_proto.clone();
    let ictor = vm.native_ctor("Iterator", 0, iterator_ctor, &ip);
    vm.def_method(&ictor, "from", 1, iterator_from);
    vm.def_method(&ictor, "zip", 1, iterator_zip);
    vm.def_method(&ictor, "zipKeyed", 1, iterator_zip_keyed);
    vm.def_method(&ictor, "concat", 0, iterator_concat);
    // reorder prototype after statics
    move_to_end(&ictor, &vm.intr.key_prototype.clone());
    for (n, l, f) in [
        ("map", 1, helper_map as NativeFn),
        ("filter", 1, helper_filter),
        ("take", 1, helper_take),
        ("drop", 1, helper_drop),
        ("flatMap", 1, helper_flat_map),
        ("toArray", 0, iter_to_array),
        ("forEach", 1, iter_for_each),
        ("reduce", 1, iter_reduce),
        ("some", 1, iter_some),
        ("every", 1, iter_every),
        ("find", 1, iter_find),
    ] {
        vm.def_method(&ip, n, l, f);
    }
    // Iterator.prototype.constructor is an accessor
    {
        let g = vm.native_fn("get constructor", 0, iterator_ctor_get);
        let s = vm.native_fn("set constructor", 1, iterator_ctor_set);
        ip.borrow_mut().props.remove(&vm.intr.key_constructor.clone());
        ip.set_accessor(vm.intr.key_constructor.clone(), Some(g), Some(s), CONFIGURABLE);
    }
    vm.def_sym_method(&ip, &vm.intr.sym_iterator.clone(), "[Symbol.iterator]", 0, return_this);
    vm.def_sym_method(&ip, &vm.intr.sym_dispose.clone(), "[Symbol.dispose]", 0, iter_dispose);
    let tag_get = vm.native_fn("get [Symbol.toStringTag]", 0, iterator_tag_get);
    let tag_set = vm.native_fn("set [Symbol.toStringTag]", 1, iterator_tag_set);
    ip.set_accessor(PropKey::Sym(vm.intr.sym_to_string_tag.clone()), Some(tag_get), Some(tag_set), CONFIGURABLE);
    vm.intr.iterator_ctor = ictor.clone();
    vm.def_global("Iterator", Value::Obj(ictor));

    let aip = vm.intr.async_iterator_proto.clone();
    vm.def_sym_method(&aip, &vm.intr.sym_async_iterator.clone(), "[Symbol.asyncIterator]", 0, return_this);
    vm.def_sym_method(&aip, &vm.intr.sym_async_dispose.clone(), "[Symbol.asyncDispose]", 0, async_iter_dispose);

    let arr_ip = vm.intr.array_iterator_proto.clone();
    let next = vm.def_method(&arr_ip, "next", 0, array_iter_next);
    vm.intr.array_iter_next = next;
    vm.set_tag(&arr_ip, "Array Iterator");
    let mip = vm.intr.map_iterator_proto.clone();
    vm.def_method(&mip, "next", 0, map_iter_next);
    vm.set_tag(&mip, "Map Iterator");
    let sip = vm.intr.set_iterator_proto.clone();
    vm.def_method(&sip, "next", 0, set_iter_next);
    vm.set_tag(&sip, "Set Iterator");
    let strip = vm.intr.string_iterator_proto.clone();
    vm.def_method(&strip, "next", 0, string_iter_next);
    vm.set_tag(&strip, "String Iterator");
    let hp = vm.intr.iterator_helper_proto.clone();
    vm.def_method(&hp, "next", 0, helper_next);
    vm.def_method(&hp, "return", 0, helper_return);
    vm.set_tag(&hp, "Iterator Helper");
    let wp = vm.intr.wrap_iterator_proto.clone();
    vm.def_method(&wp, "next", 0, wrap_next);
    vm.def_method(&wp, "return", 0, wrap_return);
    let asp = vm.intr.async_from_sync_proto.clone();
    vm.def_method(&asp, "next", 1, async_from_sync_next);
    vm.def_method(&asp, "return", 1, async_from_sync_return);
    vm.def_method(&asp, "throw", 1, async_from_sync_throw);
}

fn return_this(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(a.this.clone())
}

fn iterator_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match &a.new_target {
        None => vm.throw_type("Abstract class Iterator not directly constructable"),
        Some(nt) if nt.ptr_eq(a.callee) => vm.throw_type("Abstract class Iterator not directly constructable"),
        Some(_) => {
            let p = vm.proto_from_nt(&a.new_target, &vm.intr.iterator_proto.clone())?;
            Ok(Value::Obj(Obj::new(Some(p), ObjKind::Ordinary)))
        }
    }
}

fn iterator_tag_get(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::str("Iterator"))
}

fn iterator_tag_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let k = PropKey::Sym(vm.intr.sym_to_string_tag.clone());
    setter_ignoring_proto(vm, a, k)
}

fn iterator_ctor_get(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Obj(vm.intr.iterator_ctor.clone()))
}

fn iterator_ctor_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let k = vm.intr.key_constructor.clone();
    setter_ignoring_proto(vm, a, k)
}


/// SetterThatIgnoresPrototypeProperties(this, %Iterator.prototype%, key, value)
fn setter_ignoring_proto(vm: &mut Vm, a: &Args, k: PropKey) -> JsResult<Value> {
    let o = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("cannot create property on a primitive"),
    };
    if o.ptr_eq(&vm.intr.iterator_proto) {
        return vm.throw_type("cannot assign to a property of Iterator.prototype");
    }
    if vm.get_own_property(&o, &k)?.is_none() {
        vm.create_data_property(&o, k, a.arg(0))?;
    } else {
        vm.set(&o, k, a.arg(0), &a.this)?;
    }
    Ok(Value::Undefined)
}

fn iter_dispose(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = vm.get_method(&a.this, &PropKey::from_str("return"))?;
    if let Some(r) = r {
        vm.call(&r, a.this.clone(), &[])?;
    }
    Ok(Value::Undefined)
}

fn async_iter_dispose(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let r = (|| -> JsResult<Value> {
        let r = vm.get_method(&a.this, &PropKey::from_str("return"))?;
        match r {
            Some(r) => vm.call(&r, a.this.clone(), &[]),
            None => Ok(Value::Undefined),
        }
    })();
    match r {
        Ok(v) => {
            let p = crate::builtins::promise::promise_resolve_intrinsic(vm, v)?;
            let f = vm.native_fn("", 0, |_vm, _a| Ok(Value::Undefined));
            let res = crate::builtins::promise::promise_then(vm, &p, Value::Obj(f), Value::Undefined)?;
            vm.call(&cap.resolve, Value::Undefined, &[res])?;
        }
        Err(e) => {
            vm.call(&cap.reject, Value::Undefined, &[e])?;
        }
    }
    Ok(cap.promise)
}

// ---------------- array / map / set / string iterators ----------------

pub fn create_array_iterator(vm: &mut Vm, obj: Value, kind: u8) -> Value {
    let o = Obj::new(Some(vm.intr.array_iterator_proto.clone()), ObjKind::Iterator(Box::new(IterState::Array { obj, index: 0, kind, done: false })));
    Value::Obj(o)
}

fn array_iter_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let it = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("Array Iterator next called on an incompatible receiver"),
    };
    let (obj, index, kind, done) = match &it.borrow().kind {
        ObjKind::Iterator(s) => match &**s {
            IterState::Array { obj, index, kind, done } => (obj.clone(), *index, *kind, *done),
            _ => return vm.throw_type("Array Iterator next called on an incompatible receiver"),
        },
        _ => return vm.throw_type("Array Iterator next called on an incompatible receiver"),
    };
    if done {
        return Ok(vm.iter_result(Value::Undefined, true));
    }
    let o = obj.as_obj().unwrap().clone();
    // fast path dense array
    let fast = {
        let b = o.borrow();
        match &b.kind {
            ObjKind::Array(ad) if !ad.sparse => Some((ad.len as usize, ad.dense.get(index).cloned())),
            _ => None,
        }
    };
    let len = match &fast {
        Some((l, _)) => *l,
        None => {
            let is_ta = matches!(o.borrow().kind, ObjKind::TypedArray(_));
            if is_ta {
                let (oob, l) = match &o.borrow().kind {
                    ObjKind::TypedArray(t) => (t.is_out_of_bounds(), t.len()),
                    _ => (false, 0),
                };
                if oob {
                    return vm.throw_type("Cannot perform %ArrayIteratorPrototype%.next on a detached ArrayBuffer");
                }
                l
            } else {
                vm.length_of(&o)? as usize
            }
        }
    };
    if index >= len {
        set_iter_done(&it);
        return Ok(vm.iter_result(Value::Undefined, true));
    }
    if let ObjKind::Iterator(s) = &mut it.borrow_mut().kind {
        if let IterState::Array { index: i, .. } = &mut **s {
            *i = index + 1;
        }
    }
    let r = match kind {
        0 => {
            // (the reference engine reads the element for keys() as well)
            let hole = matches!(&fast, Some((_, v)) if v.as_ref().map_or(true, |v| v.is_empty()));
            if (fast.is_none() || hole) && !matches!(o.borrow().kind, ObjKind::TypedArray(_)) {
                vm.get(&o, &PropKey::from_index(index as u32), &obj)?;
            }
            Value::Num(index as f64)
        }
        _ => {
            let v = match fast {
                Some((_, Some(v))) if !v.is_empty() => v,
                _ => vm.get(&o, &PropKey::from_index(index as u32), &obj)?,
            };
            if kind == 1 {
                v
            } else {
                Value::Obj(vm.new_array(vec![Value::Num(index as f64), v]))
            }
        }
    };
    Ok(vm.iter_result(r, false))
}

fn set_iter_done(it: &Obj) {
    if let ObjKind::Iterator(s) = &mut it.borrow_mut().kind {
        match &mut **s {
            IterState::Array { done, .. } | IterState::Map { done, .. } | IterState::Set { done, .. } | IterState::Str { done, .. } => *done = true,
            _ => {}
        }
    }
}

pub fn create_map_iterator(vm: &mut Vm, map: Obj, kind: u8) -> Value {
    Value::Obj(Obj::new(Some(vm.intr.map_iterator_proto.clone()), ObjKind::Iterator(Box::new(IterState::Map { map, index: 0, kind, done: false }))))
}

pub fn create_set_iterator(vm: &mut Vm, set: Obj, kind: u8) -> Value {
    Value::Obj(Obj::new(Some(vm.intr.set_iterator_proto.clone()), ObjKind::Iterator(Box::new(IterState::Set { set, index: 0, kind, done: false }))))
}

fn map_iter_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let it = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("not a Map/Set Iterator"),
    };
    let (map, index, kind, done) = match &it.borrow().kind {
        ObjKind::Iterator(s) => match &**s {
            IterState::Map { map, index, kind, done } => (map.clone(), *index, *kind, *done),
            _ => return vm.throw_type("not a Map/Set Iterator"),
        },
        _ => return vm.throw_type("not a Map/Set Iterator"),
    };
    if done {
        return Ok(vm.iter_result(Value::Undefined, true));
    }
    let mut i = index;
    let found = {
        let b = map.borrow();
        let m = match &b.kind {
            ObjKind::Map(m) => m,
            _ => return Ok(Value::Undefined),
        };
        let mut f = None;
        while i < m.entries.len() {
            if let Some((k, v)) = &m.entries[i] {
                f = Some((k.clone(), v.clone()));
                i += 1;
                break;
            }
            i += 1;
        }
        f
    };
    if let ObjKind::Iterator(s) = &mut it.borrow_mut().kind {
        if let IterState::Map { index, done, .. } = &mut **s {
            *index = i;
            if found.is_none() {
                *done = true;
            }
        }
    }
    match found {
        None => Ok(vm.iter_result(Value::Undefined, true)),
        Some((k, v)) => {
            let r = match kind {
                0 => k,
                1 => v,
                _ => Value::Obj(vm.new_array(vec![k, v])),
            };
            Ok(vm.iter_result(r, false))
        }
    }
}

fn set_iter_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let it = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("not a Map/Set Iterator"),
    };
    let (set, index, kind, done) = match &it.borrow().kind {
        ObjKind::Iterator(s) => match &**s {
            IterState::Set { set, index, kind, done } => (set.clone(), *index, *kind, *done),
            _ => return vm.throw_type("not a Map/Set Iterator"),
        },
        _ => return vm.throw_type("not a Map/Set Iterator"),
    };
    if done {
        return Ok(vm.iter_result(Value::Undefined, true));
    }
    let mut i = index;
    let found = {
        let b = set.borrow();
        let m = match &b.kind {
            ObjKind::Set(m) => m,
            _ => return Ok(Value::Undefined),
        };
        let mut f = None;
        while i < m.entries.len() {
            if let Some((k, _)) = &m.entries[i] {
                f = Some(k.clone());
                i += 1;
                break;
            }
            i += 1;
        }
        f
    };
    if let ObjKind::Iterator(s) = &mut it.borrow_mut().kind {
        if let IterState::Set { index, done, .. } = &mut **s {
            *index = i;
            if found.is_none() {
                *done = true;
            }
        }
    }
    match found {
        None => Ok(vm.iter_result(Value::Undefined, true)),
        Some(k) => {
            let r = if kind == 2 { Value::Obj(vm.new_array(vec![k.clone(), k])) } else { k };
            Ok(vm.iter_result(r, false))
        }
    }
}

pub fn create_string_iterator(vm: &mut Vm, s: JsStr) -> Value {
    Value::Obj(Obj::new(Some(vm.intr.string_iterator_proto.clone()), ObjKind::Iterator(Box::new(IterState::Str { s, index: 0, done: false }))))
}

fn string_iter_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let it = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("String Iterator next called on an incompatible receiver"),
    };
    let r = {
        let mut b = it.borrow_mut();
        match &mut b.kind {
            ObjKind::Iterator(st) => match &mut **st {
                IterState::Str { s, index, done } => {
                    if *done || *index >= s.len() {
                        *done = true;
                        None
                    } else {
                        let u = s.units();
                        let c = u[*index];
                        let n = if (0xD800..0xDC00).contains(&c) && *index + 1 < u.len() && (0xDC00..0xE000).contains(&u[*index + 1]) { 2 } else { 1 };
                        let piece = JsStr::from_slice(&u[*index..*index + n]);
                        *index += n;
                        Some(piece)
                    }
                }
                _ => return vm.throw_type("String Iterator next called on an incompatible receiver"),
            },
            _ => return vm.throw_type("String Iterator next called on an incompatible receiver"),
        }
    };
    match r {
        Some(p) => Ok(vm.iter_result(Value::Str(p), false)),
        None => Ok(vm.iter_result(Value::Undefined, true)),
    }
}

// ---------------- iterator helpers ----------------

fn get_iterator_direct(vm: &mut Vm, v: &Value) -> JsResult<(Obj, Value)> {
    let o = match v {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("Iterator helper called on a non-object"),
    };
    let next = vm.get(&o, &vm.intr.key_next.clone(), v)?;
    Ok((o, next))
}

fn make_helper(vm: &mut Vm, kind: HelperKind, underlying: Obj, next: Value, func: Value, remaining: f64) -> Value {
    let h = IterHelper { kind, underlying, next_method: next, func, counter: 0.0, remaining, inner: None, done: false, running: false };
    Value::Obj(Obj::new(Some(vm.intr.iterator_helper_proto.clone()), ObjKind::Iterator(Box::new(IterState::Helper(Box::new(h))))))
}

fn require_callable(vm: &mut Vm, this: &Value, f: &Value) -> JsResult<()> {
    require_callable_msg(vm, this, f, "Iterator helper argument is not callable")
}

fn require_callable_msg(vm: &mut Vm, this: &Value, f: &Value, msg: &str) -> JsResult<()> {
    if !f.is_callable() {
        // close the underlying iterator per spec
        if this.is_object() {
            let _ = vm.iterator_close(this);
        }
        return vm.throw_type(msg);
    }
    Ok(())
}

fn helper_map(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !a.this.is_object() {
        return vm.throw_type("Iterator helper called on a non-object");
    }
    let f = a.arg(0);
    require_callable(vm, &a.this, &f)?;
    let (o, next) = get_iterator_direct(vm, &a.this)?;
    Ok(make_helper(vm, HelperKind::Map, o, next, f, 0.0))
}

fn helper_filter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !a.this.is_object() {
        return vm.throw_type("Iterator helper called on a non-object");
    }
    let f = a.arg(0);
    require_callable(vm, &a.this, &f)?;
    let (o, next) = get_iterator_direct(vm, &a.this)?;
    Ok(make_helper(vm, HelperKind::Filter, o, next, f, 0.0))
}

fn helper_flat_map(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !a.this.is_object() {
        return vm.throw_type("Iterator helper called on a non-object");
    }
    let f = a.arg(0);
    require_callable(vm, &a.this, &f)?;
    let (o, next) = get_iterator_direct(vm, &a.this)?;
    Ok(make_helper(vm, HelperKind::FlatMap, o, next, f, 0.0))
}

fn limit_arg(vm: &mut Vm, this: &Value, v: &Value) -> JsResult<f64> {
    let n = match vm.to_number(v) {
        Ok(n) => n,
        Err(e) => {
            let _ = vm.iterator_close(this);
            return Err(e);
        }
    };
    if n.is_nan() {
        let _ = vm.iterator_close(this);
        return vm.throw_range("limit must be a non-negative number");
    }
    let n = crate::ops::integer_or_infinity(n);
    if n < 0.0 {
        let _ = vm.iterator_close(this);
        return vm.throw_range("limit must be a non-negative number");
    }
    Ok(n)
}

fn helper_take(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !a.this.is_object() {
        return vm.throw_type("Iterator helper called on a non-object");
    }
    let n = limit_arg(vm, &a.this, &a.arg(0))?;
    let (o, next) = get_iterator_direct(vm, &a.this)?;
    Ok(make_helper(vm, HelperKind::Take, o, next, Value::Undefined, n))
}

fn helper_drop(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !a.this.is_object() {
        return vm.throw_type("Iterator helper called on a non-object");
    }
    let n = limit_arg(vm, &a.this, &a.arg(0))?;
    let (o, next) = get_iterator_direct(vm, &a.this)?;
    Ok(make_helper(vm, HelperKind::Drop, o, next, Value::Undefined, n))
}

fn with_helper<R>(it: &Obj, f: impl FnOnce(&mut IterHelper) -> R) -> Option<R> {
    let mut b = it.borrow_mut();
    match &mut b.kind {
        ObjKind::Iterator(s) => match &mut **s {
            IterState::Helper(h) => Some(f(h)),
            _ => None,
        },
        _ => None,
    }
}

fn helper_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let it = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("next called on an incompatible receiver"),
    };
    let info = with_helper(&it, |h| (h.kind, Value::Obj(h.underlying.clone()), h.next_method.clone(), h.func.clone(), h.done, h.running));
    let (kind, und, next, func, done, running) = match info {
        Some(x) => x,
        None => return vm.throw_type("next called on an incompatible receiver"),
    };
    if running {
        return vm.throw_type("iterator helper is already running");
    }
    if done {
        return Ok(vm.iter_result(Value::Undefined, true));
    }
    with_helper(&it, |h| h.running = true);
    let r = helper_step(vm, &it, kind, &und, &next, &func);
    with_helper(&it, |h| h.running = false);
    match r {
        Ok(Some(v)) => Ok(vm.iter_result(v, false)),
        Ok(None) => {
            with_helper(&it, |h| h.done = true);
            Ok(vm.iter_result(Value::Undefined, true))
        }
        Err(e) => {
            with_helper(&it, |h| h.done = true);
            Err(e)
        }
    }
}

fn helper_step(vm: &mut Vm, it: &Obj, kind: HelperKind, und: &Value, next: &Value, func: &Value) -> JsResult<Option<Value>> {
    match kind {
        HelperKind::Map => {
            let v = match vm.iter_step(und, next)? {
                Some(v) => v,
                None => return Ok(None),
            };
            let c = with_helper(it, |h| {
                let c = h.counter;
                h.counter += 1.0;
                c
            })
            .unwrap();
            match vm.call(func, Value::Undefined, &[v, Value::Num(c)]) {
                Ok(r) => Ok(Some(r)),
                Err(e) => {
                    let _ = vm.iterator_close(und);
                    Err(e)
                }
            }
        }
        HelperKind::Filter => loop {
            let v = match vm.iter_step(und, next)? {
                Some(v) => v,
                None => return Ok(None),
            };
            let c = with_helper(it, |h| {
                let c = h.counter;
                h.counter += 1.0;
                c
            })
            .unwrap();
            match vm.call(func, Value::Undefined, &[v.clone(), Value::Num(c)]) {
                Ok(r) => {
                    if r.truthy() {
                        return Ok(Some(v));
                    }
                }
                Err(e) => {
                    let _ = vm.iterator_close(und);
                    return Err(e);
                }
            }
        },
        HelperKind::Take => {
            let rem = with_helper(it, |h| h.remaining).unwrap();
            if rem <= 0.0 {
                vm.iterator_close(und)?;
                return Ok(None);
            }
            if rem != f64::INFINITY {
                with_helper(it, |h| h.remaining -= 1.0);
            }
            vm.iter_step(und, next)
        }
        HelperKind::Drop => {
            loop {
                let rem = with_helper(it, |h| h.remaining).unwrap();
                if rem <= 0.0 {
                    break;
                }
                if rem != f64::INFINITY {
                    with_helper(it, |h| h.remaining -= 1.0);
                }
                if vm.iter_step(und, next)?.is_none() {
                    return Ok(None);
                }
            }
            vm.iter_step(und, next)
        }
        HelperKind::FlatMap => loop {
            let inner = with_helper(it, |h| h.inner.clone()).unwrap();
            if let Some((io, inext)) = inner {
                let iv = Value::Obj(io.clone());
                match vm.iter_step(&iv, &inext) {
                    Ok(Some(v)) => return Ok(Some(v)),
                    Ok(None) => {
                        with_helper(it, |h| h.inner = None);
                        continue;
                    }
                    Err(e) => {
                        let _ = vm.iterator_close(und);
                        return Err(e);
                    }
                }
            }
            let v = match vm.iter_step(und, next)? {
                Some(v) => v,
                None => return Ok(None),
            };
            let c = with_helper(it, |h| {
                let c = h.counter;
                h.counter += 1.0;
                c
            })
            .unwrap();
            let mapped = match vm.call(func, Value::Undefined, &[v, Value::Num(c)]) {
                Ok(m) => m,
                Err(e) => {
                    let _ = vm.iterator_close(und);
                    return Err(e);
                }
            };
            match get_iterator_flattenable_checked(vm, &mapped, true) {
                Ok((io, inext)) => {
                    with_helper(it, |h| h.inner = Some((io, inext)));
                }
                Err(e) => {
                    let _ = vm.iterator_close(und);
                    return Err(e);
                }
            }
        },
    }
}

fn helper_return(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let it = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("return called on an incompatible receiver"),
    };
    let info = with_helper(&it, |h| (Value::Obj(h.underlying.clone()), h.done, h.running, h.inner.clone()));
    let (und, done, running, inner) = match info {
        Some(x) => x,
        None => return vm.throw_type("return called on an incompatible receiver"),
    };
    if running {
        return vm.throw_type("iterator helper is already running");
    }
    if !done {
        with_helper(&it, |h| h.done = true);
        if let Some((io, _)) = inner {
            let _ = vm.iterator_close(&Value::Obj(io));
        }
        vm.iterator_close(&und)?;
    }
    Ok(vm.iter_result(Value::Undefined, true))
}

pub fn get_iterator_flattenable(vm: &mut Vm, v: &Value, reject_strings: bool) -> JsResult<(Obj, Value)> {
    match v {
        Value::Obj(_) => {}
        Value::Str(_) if !reject_strings => {}
        _ => return vm.throw_type("value is not iterable"),
    }
    let m = vm.get_prop_of(v, &PropKey::Sym(vm.intr.sym_iterator.clone()))?;
    let it = if m.is_nullish() {
        v.clone()
    } else {
        if !m.is_callable() {
            return vm.throw_type("@@iterator is not callable");
        }
        vm.call(&m, v.clone(), &[])?
    };
    let io = match &it {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("iterator is not an object"),
    };
    let next = vm.get(&io, &vm.intr.key_next.clone(), &it)?;
    Ok((io, next))
}

/// GetIteratorFlattenable with an up-front check of `next` (flatMap, zip, concat)
fn get_iterator_flattenable_checked(vm: &mut Vm, v: &Value, reject_strings: bool) -> JsResult<(Obj, Value)> {
    let (io, next) = get_iterator_flattenable(vm, v, reject_strings)?;
    if !next.is_callable() {
        return vm.throw_type("iterator.next is not a function");
    }
    Ok((io, next))
}

fn iterator_from(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = a.arg(0);
    let (io, next) = get_iterator_flattenable(vm, &v, false)?;
    // if it already inherits from %Iterator.prototype%, return it
    let ip = vm.intr.iterator_proto.clone();
    let mut cur = vm.get_prototype_of(&io)?;
    while let Some(p) = cur {
        if p.ptr_eq(&ip) {
            return Ok(Value::Obj(io));
        }
        cur = vm.get_prototype_of(&p)?;
    }
    let w = Obj::new(Some(vm.intr.wrap_iterator_proto.clone()), ObjKind::Iterator(Box::new(IterState::Wrap { iterated: io, next })));
    Ok(Value::Obj(w))
}

fn wrap_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (it, next) = match &a.this {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Iterator(s) => match &**s {
                IterState::Wrap { iterated, next } => (iterated.clone(), next.clone()),
                _ => return Err(vm.make_error("TypeError", "next called on an incompatible receiver")),
            },
            _ => return Err(vm.make_error("TypeError", "next called on an incompatible receiver")),
        },
        _ => return vm.throw_type("next called on an incompatible receiver"),
    };
    vm.call(&next, Value::Obj(it), &[])
}

fn wrap_return(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let it = match &a.this {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Iterator(s) => match &**s {
                IterState::Wrap { iterated, .. } => iterated.clone(),
                _ => return Err(vm.make_error("TypeError", "return called on an incompatible receiver")),
            },
            _ => return Err(vm.make_error("TypeError", "return called on an incompatible receiver")),
        },
        _ => return vm.throw_type("return called on an incompatible receiver"),
    };
    let r = vm.get_method(&Value::Obj(it.clone()), &PropKey::from_str("return"))?;
    match r {
        None => Ok(vm.iter_result(Value::Undefined, true)),
        Some(r) => vm.call(&r, Value::Obj(it), &[]),
    }
}

fn iterator_concat(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut items = Vec::new();
    for v in a.args {
        if !v.is_object() {
            return vm.throw_type("Iterator.concat requires iterable objects");
        }
        let m = vm.get_prop_of(v, &PropKey::Sym(vm.intr.sym_iterator.clone()))?;
        if !m.is_callable() {
            return vm.throw_type("Iterator.concat requires iterable objects");
        }
        items.push((v.clone(), m));
    }
    // implemented as a generator-like helper via a native closure state
    let st = IterState::Concat { iterables: items, index: 0, inner: None };
    let o = Obj::new(Some(vm.intr.iterator_helper_proto.clone()), ObjKind::Iterator(Box::new(st)));
    // concat iterators use their own next: install own methods
    let nf = vm.native_fn("next", 0, concat_next);
    o.set_prop(vm.intr.key_next.clone(), Value::Obj(nf), WC);
    let rf = vm.native_fn("return", 0, concat_return);
    o.set_prop(PropKey::from_str("return"), Value::Obj(rf), WC);
    Ok(Value::Obj(o))
}

fn concat_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("incompatible receiver"),
    };
    loop {
        let (inner, idx, item) = match &o.borrow().kind {
            ObjKind::Iterator(s) => match &**s {
                IterState::Concat { iterables, index, inner } => (inner.clone(), *index, iterables.get(*index).cloned()),
                _ => return Err(vm.make_error("TypeError", "incompatible receiver")),
            },
            _ => return Err(vm.make_error("TypeError", "incompatible receiver")),
        };
        if let Some((io, next)) = inner {
            let iv = Value::Obj(io);
            match vm.iter_step(&iv, &next)? {
                Some(v) => return Ok(vm.iter_result(v, false)),
                None => {
                    if let ObjKind::Iterator(s) = &mut o.borrow_mut().kind {
                        if let IterState::Concat { inner, .. } = &mut **s {
                            *inner = None;
                        }
                    }
                    continue;
                }
            }
        }
        let (v, m) = match item {
            Some(x) => x,
            None => return Ok(vm.iter_result(Value::Undefined, true)),
        };
        let (io, next) = vm.get_iterator_from_method(&v, &m)?;
        if !next.is_callable() {
            return vm.throw_type("iterator.next is not a function");
        }
        if let ObjKind::Iterator(s) = &mut o.borrow_mut().kind {
            if let IterState::Concat { inner, index, .. } = &mut **s {
                *inner = Some((io, next));
                *index = idx + 1;
            }
        }
    }
}

fn concat_return(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let Value::Obj(o) = &a.this {
        let inner = match &mut o.borrow_mut().kind {
            ObjKind::Iterator(s) => match &mut **s {
                IterState::Concat { inner, index, iterables } => {
                    *index = iterables.len();
                    inner.take()
                }
                _ => None,
            },
            _ => None,
        };
        if let Some((io, _)) = inner {
            vm.iterator_close(&Value::Obj(io))?;
        }
    }
    Ok(vm.iter_result(Value::Undefined, true))
}

fn iterator_zip(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    zip_impl(vm, a, false)
}
fn iterator_zip_keyed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    zip_impl(vm, a, true)
}

fn zip_impl(vm: &mut Vm, a: &Args, keyed: bool) -> JsResult<Value> {
    let iterables = a.arg(0);
    if !iterables.is_object() {
        return vm.throw_type("Iterator.zip requires an iterable object");
    }
    let opts = a.arg(1);
    let mut mode = 0u8; // 0 shortest, 1 longest, 2 strict
    let mut padding_v = Value::Undefined;
    if let Value::Obj(o) = &opts {
        let m = vm.get_str(o, "mode")?;
        if !m.is_undefined() {
            let ms = match &m {
                Value::Str(s) => s.to_rust_string(),
                _ => return vm.throw_type("mode must be a string"),
            };
            mode = match ms.as_str() {
                "shortest" => 0,
                "longest" => 1,
                "strict" => 2,
                _ => return vm.throw_type("invalid mode"),
            };
        }
        if mode == 1 {
            padding_v = vm.get_str(o, "padding")?;
        }
    } else if !opts.is_undefined() {
        return vm.throw_type("options must be an object");
    }
    let mut iters: Vec<Option<(Obj, Value)>> = Vec::new();
    let mut keys = None;
    if keyed {
        let o = iterables.as_obj().unwrap().clone();
        let ks = vm.own_property_keys(&o)?;
        let mut kv = Vec::new();
        for k in ks {
            if let Some(d) = vm.get_own_property(&o, &k)? {
                if d.enumerable == Some(true) {
                    let v = vm.get(&o, &k, &iterables)?;
                    if !v.is_undefined() {
                        iters.push(Some(get_iterator_flattenable_checked(vm, &v, true)?));
                        kv.push(k);
                    }
                }
            }
        }
        keys = Some(kv);
    } else {
        let all = vm.iterate_to_vec(&iterables)?;
        for v in all {
            iters.push(Some(get_iterator_flattenable_checked(vm, &v, true)?));
        }
    }
    let mut padding = vec![Value::Undefined; iters.len()];
    if mode == 1 && !padding_v.is_undefined() {
        if keyed {
            if let (Value::Obj(po), Some(ks)) = (&padding_v, &keys) {
                for (i, k) in ks.iter().enumerate() {
                    padding[i] = vm.get(po, k, &padding_v)?;
                }
            }
        } else {
            let pv = vm.iterate_to_vec(&padding_v)?;
            for (i, v) in pv.into_iter().enumerate() {
                if i < padding.len() {
                    padding[i] = v;
                }
            }
        }
    }
    let st = IterState::Zip(Box::new(ZipState { iters, mode, padding, done: false, keys }));
    let o = Obj::new(Some(vm.intr.iterator_helper_proto.clone()), ObjKind::Iterator(Box::new(st)));
    let nf = vm.native_fn("next", 0, zip_next);
    o.set_prop(vm.intr.key_next.clone(), Value::Obj(nf), WC);
    let rf = vm.native_fn("return", 0, zip_return);
    o.set_prop(PropKey::from_str("return"), Value::Obj(rf), WC);
    Ok(Value::Obj(o))
}

fn zip_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("incompatible receiver"),
    };
    let (iters, mode, padding, done, keys) = match &o.borrow().kind {
        ObjKind::Iterator(s) => match &**s {
            IterState::Zip(z) => (z.iters.clone(), z.mode, z.padding.clone(), z.done, z.keys.clone()),
            _ => return Err(vm.make_error("TypeError", "incompatible receiver")),
        },
        _ => return Err(vm.make_error("TypeError", "incompatible receiver")),
    };
    if done || iters.is_empty() {
        return Ok(vm.iter_result(Value::Undefined, true));
    }
    let mut results = Vec::new();
    let mut new_iters = iters.clone();
    let mut any_done = false;
    let mut all_done = true;
    for (i, it) in iters.iter().enumerate() {
        match it {
            None => results.push(padding[i].clone()),
            Some((io, next)) => {
                let iv = Value::Obj(io.clone());
                match vm.iter_step(&iv, next)? {
                    Some(v) => {
                        all_done = false;
                        results.push(v)
                    }
                    None => {
                        any_done = true;
                        new_iters[i] = None;
                        if mode == 0 {
                            for (j, other) in iters.iter().enumerate() {
                                if j != i {
                                    if let Some((oo, _)) = other {
                                        let _ = vm.iterator_close(&Value::Obj(oo.clone()));
                                    }
                                }
                            }
                            set_zip_done(&o);
                            return Ok(vm.iter_result(Value::Undefined, true));
                        }
                        if mode == 2 && i > 0 && results.len() == i {
                            for other in iters.iter().flatten() {
                                let _ = vm.iterator_close(&Value::Obj(other.0.clone()));
                            }
                            return vm.throw_type("iterators have different lengths");
                        }
                        results.push(padding[i].clone());
                    }
                }
            }
        }
    }
    if mode == 2 && any_done && !all_done {
        return vm.throw_type("iterators have different lengths");
    }
    if (mode == 1 || mode == 2) && new_iters.iter().all(|x| x.is_none()) {
        set_zip_done(&o);
        return Ok(vm.iter_result(Value::Undefined, true));
    }
    if let ObjKind::Iterator(s) = &mut o.borrow_mut().kind {
        if let IterState::Zip(z) = &mut **s {
            z.iters = new_iters;
        }
    }
    let r = match keys {
        Some(ks) => {
            let ro = Obj::new(None, ObjKind::Ordinary);
            for (k, v) in ks.into_iter().zip(results.into_iter()) {
                ro.set_prop(k, v, WEC);
            }
            Value::Obj(ro)
        }
        None => Value::Obj(vm.new_array(results)),
    };
    Ok(vm.iter_result(r, false))
}

fn set_zip_done(o: &Obj) {
    if let ObjKind::Iterator(s) = &mut o.borrow_mut().kind {
        if let IterState::Zip(z) = &mut **s {
            z.done = true;
        }
    }
}

fn zip_return(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let Value::Obj(o) = &a.this {
        let iters = match &mut o.borrow_mut().kind {
            ObjKind::Iterator(s) => match &mut **s {
                IterState::Zip(z) => {
                    z.done = true;
                    std::mem::take(&mut z.iters)
                }
                _ => Vec::new(),
            },
            _ => Vec::new(),
        };
        for (io, _) in iters.into_iter().flatten() {
            vm.iterator_close(&Value::Obj(io))?;
        }
    }
    Ok(vm.iter_result(Value::Undefined, true))
}

fn eager_prelude(vm: &mut Vm, a: &Args, name: &str, need_fn: bool) -> JsResult<(Value, Value, Value)> {
    if !a.this.is_object() {
        let _ = name;
        return vm.throw_type("Iterator method called on a non-object");
    }
    let f = a.arg(0);
    if need_fn {
        let msg = match name {
            "reduce" => "reducer is not callable",
            "forEach" => "Iterator.prototype.forEach argument is not callable",
            _ => "predicate is not callable",
        };
        require_callable_msg(vm, &a.this, &f, msg)?;
    }
    let (o, next) = get_iterator_direct(vm, &a.this)?;
    Ok((Value::Obj(o), next, f))
}

fn iter_to_array(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (it, next, _) = eager_prelude(vm, a, "toArray", false)?;
    let mut out = Vec::new();
    while let Some(v) = vm.iter_step(&it, &next)? {
        out.push(v);
    }
    Ok(Value::Obj(vm.new_array(out)))
}

fn iter_for_each(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (it, next, f) = eager_prelude(vm, a, "forEach", true)?;
    let mut c = 0.0;
    while let Some(v) = vm.iter_step(&it, &next)? {
        if let Err(e) = vm.call(&f, Value::Undefined, &[v, Value::Num(c)]) {
            let _ = vm.iterator_close(&it);
            return Err(e);
        }
        c += 1.0;
    }
    Ok(Value::Undefined)
}

fn iter_reduce(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (it, next, f) = eager_prelude(vm, a, "reduce", true)?;
    let mut c = 0.0;
    let mut acc = if a.args.len() >= 2 {
        a.arg(1)
    } else {
        match vm.iter_step(&it, &next)? {
            Some(v) => {
                c = 1.0;
                v
            }
            None => return vm.throw_type("Reduce of empty iterator with no initial value"),
        }
    };
    while let Some(v) = vm.iter_step(&it, &next)? {
        acc = match vm.call(&f, Value::Undefined, &[acc, v, Value::Num(c)]) {
            Ok(r) => r,
            Err(e) => {
                let _ = vm.iterator_close(&it);
                return Err(e);
            }
        };
        c += 1.0;
    }
    Ok(acc)
}

fn iter_some_every_find(vm: &mut Vm, a: &Args, name: &str, mode: u8) -> JsResult<Value> {
    let (it, next, f) = eager_prelude(vm, a, name, true)?;
    let mut c = 0.0;
    while let Some(v) = vm.iter_step(&it, &next)? {
        let r = match vm.call(&f, Value::Undefined, &[v.clone(), Value::Num(c)]) {
            Ok(r) => r.truthy(),
            Err(e) => {
                let _ = vm.iterator_close(&it);
                return Err(e);
            }
        };
        match mode {
            0 if r => {
                vm.iterator_close(&it)?;
                return Ok(Value::Bool(true));
            }
            1 if !r => {
                vm.iterator_close(&it)?;
                return Ok(Value::Bool(false));
            }
            2 if r => {
                vm.iterator_close(&it)?;
                return Ok(v);
            }
            _ => {}
        }
        c += 1.0;
    }
    Ok(match mode {
        0 => Value::Bool(false),
        1 => Value::Bool(true),
        _ => Value::Undefined,
    })
}

fn iter_some(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    iter_some_every_find(vm, a, "some", 0)
}
fn iter_every(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    iter_some_every_find(vm, a, "every", 1)
}
fn iter_find(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    iter_some_every_find(vm, a, "find", 2)
}

// ---------------- async-from-sync iterator ----------------

pub fn create_async_from_sync(vm: &mut Vm, it: Obj, next: Value) -> (Obj, Value) {
    let o = Obj::new(Some(vm.intr.async_from_sync_proto.clone()), ObjKind::Iterator(Box::new(IterState::AsyncFromSync { iter: it, next })));
    let n = vm.get(&o, &vm.intr.key_next.clone(), &Value::Obj(o.clone())).unwrap_or(Value::Undefined);
    (o, n)
}

fn afs_parts(vm: &mut Vm, this: &Value) -> JsResult<(Obj, Value)> {
    match this {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Iterator(s) => match &**s {
                IterState::AsyncFromSync { iter, next } => Ok((iter.clone(), next.clone())),
                _ => Err(vm.make_error("TypeError", "incompatible receiver")),
            },
            _ => Err(vm.make_error("TypeError", "incompatible receiver")),
        },
        _ => vm.throw_type("incompatible receiver"),
    }
}

fn afs_continuation(vm: &mut Vm, result: Value, cap: &Capability, sync_iter: Option<Obj>) -> JsResult<Value> {
    let ro = match &result {
        Value::Obj(o) => o.clone(),
        _ => {
            let e = vm.make_error("TypeError", "iterator result is not an object");
            vm.call(&cap.reject, Value::Undefined, &[e])?;
            return Ok(cap.promise.clone());
        }
    };
    let done = match vm.get(&ro, &vm.intr.key_done.clone(), &result) {
        Ok(d) => d.truthy(),
        Err(e) => {
            vm.call(&cap.reject, Value::Undefined, &[e])?;
            return Ok(cap.promise.clone());
        }
    };
    let value = match vm.get(&ro, &vm.intr.key_value.clone(), &result) {
        Ok(v) => v,
        Err(e) => {
            vm.call(&cap.reject, Value::Undefined, &[e])?;
            return Ok(cap.promise.clone());
        }
    };
    let vw = match crate::builtins::promise::promise_resolve_intrinsic(vm, value) {
        Ok(p) => p,
        Err(e) => {
            if !done {
                if let Some(si) = &sync_iter {
                    let _ = vm.iterator_close(&Value::Obj(si.clone()));
                }
            }
            vm.call(&cap.reject, Value::Undefined, &[e])?;
            return Ok(cap.promise.clone());
        }
    };
    let unwrap = vm.native_closure("", 1, afs_unwrap, vec![Value::Bool(done)]);
    let on_reject = if done || sync_iter.is_none() {
        Value::Undefined
    } else {
        Value::Obj(vm.native_closure("", 1, afs_close_on_reject, vec![Value::Obj(sync_iter.unwrap())]))
    };
    crate::builtins::promise::perform_then_internal(
        vm,
        &vw,
        Handler::Callable(Value::Obj(unwrap)),
        if on_reject.is_undefined() { Handler::Thrower } else { Handler::Callable(on_reject) },
        Some(cap.clone()),
    );
    Ok(cap.promise.clone())
}

fn afs_unwrap(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let done = a.slot(0).truthy();
    Ok(vm.iter_result(a.arg(0), done))
}

fn afs_close_on_reject(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let it = a.slot(0);
    let _ = vm.iterator_close(&it);
    Err(a.arg(0))
}

fn async_from_sync_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let (it, next) = afs_parts(vm, &a.this)?;
    let r = if a.args.is_empty() { vm.call(&next, Value::Obj(it.clone()), &[]) } else { vm.call(&next, Value::Obj(it.clone()), &[a.arg(0)]) };
    match r {
        Ok(res) => afs_continuation(vm, res, &cap, Some(it)),
        Err(e) => {
            vm.call(&cap.reject, Value::Undefined, &[e])?;
            Ok(cap.promise)
        }
    }
}

fn async_from_sync_return(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let (it, _) = afs_parts(vm, &a.this)?;
    let itv = Value::Obj(it.clone());
    let m = match vm.get_method(&itv, &PropKey::from_str("return")) {
        Ok(m) => m,
        Err(e) => {
            vm.call(&cap.reject, Value::Undefined, &[e])?;
            return Ok(cap.promise);
        }
    };
    match m {
        None => {
            let r = vm.iter_result(a.arg(0), true);
            vm.call(&cap.resolve, Value::Undefined, &[r])?;
            Ok(cap.promise)
        }
        Some(m) => {
            let r = if a.args.is_empty() { vm.call(&m, itv, &[]) } else { vm.call(&m, itv, &[a.arg(0)]) };
            match r {
                Ok(res) => afs_continuation(vm, res, &cap, None),
                Err(e) => {
                    vm.call(&cap.reject, Value::Undefined, &[e])?;
                    Ok(cap.promise)
                }
            }
        }
    }
}

fn async_from_sync_throw(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let (it, _) = afs_parts(vm, &a.this)?;
    let itv = Value::Obj(it.clone());
    let m = match vm.get_method(&itv, &PropKey::from_str("throw")) {
        Ok(m) => m,
        Err(e) => {
            vm.call(&cap.reject, Value::Undefined, &[e])?;
            return Ok(cap.promise);
        }
    };
    match m {
        None => {
            let _ = vm.iterator_close(&itv);
            let e = vm.make_error("TypeError", "The iterator does not provide a 'throw' method");
            vm.call(&cap.reject, Value::Undefined, &[e])?;
            Ok(cap.promise)
        }
        Some(m) => {
            let r = if a.args.is_empty() { vm.call(&m, itv, &[]) } else { vm.call(&m, itv, &[a.arg(0)]) };
            match r {
                Ok(res) => afs_continuation(vm, res, &cap, Some(it)),
                Err(e) => {
                    vm.call(&cap.reject, Value::Undefined, &[e])?;
                    Ok(cap.promise)
                }
            }
        }
    }
}
