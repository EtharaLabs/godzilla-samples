// Map, Set, WeakMap, WeakSet, WeakRef, FinalizationRegistry

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let mp = vm.intr.map_proto.clone();
    let mc = vm.native_ctor("Map", 0, map_ctor, &mp);
    vm.def_method(&mc, "groupBy", 2, map_group_by);
    vm.def_sym_getter(&mc, &vm.intr.sym_species.clone(), "[Symbol.species]", species);
    vm.def_method(&mp, "get", 1, map_get);
    vm.def_method(&mp, "set", 2, map_set);
    vm.def_method(&mp, "has", 1, map_has);
    vm.def_method(&mp, "delete", 1, map_delete);
    vm.def_method(&mp, "clear", 0, map_clear);
    let entries = vm.def_method(&mp, "entries", 0, map_entries);
    vm.def_method(&mp, "forEach", 1, map_for_each);
    vm.def_method(&mp, "keys", 0, map_keys);
    vm.def_getter(&mp, "size", map_size);
    vm.def_method(&mp, "values", 0, map_values);
    vm.def_method(&mp, "getOrInsert", 2, map_get_or_insert);
    vm.def_method(&mp, "getOrInsertComputed", 2, map_get_or_insert_computed);
    mp.set_prop(PropKey::Sym(vm.intr.sym_iterator.clone()), Value::Obj(entries), WC);
    vm.set_tag(&mp, "Map");
    vm.def_global("Map", Value::Obj(mc));

    let sp = vm.intr.set_proto.clone();
    let sc = vm.native_ctor("Set", 0, set_ctor, &sp);
    vm.def_sym_getter(&sc, &vm.intr.sym_species.clone(), "[Symbol.species]", species);
    vm.def_method(&sp, "has", 1, set_has);
    vm.def_method(&sp, "add", 1, set_add);
    vm.def_method(&sp, "delete", 1, set_delete);
    vm.def_method(&sp, "clear", 0, set_clear);
    vm.def_method(&sp, "entries", 0, set_entries);
    vm.def_method(&sp, "forEach", 1, set_for_each);
    vm.def_getter(&sp, "size", set_size);
    let values = vm.def_method(&sp, "values", 0, set_values);
    sp.set_prop(PropKey::from_str("keys"), Value::Obj(values.clone()), WC);
    sp.set_prop(PropKey::Sym(vm.intr.sym_iterator.clone()), Value::Obj(values), WC);
    vm.def_method(&sp, "union", 1, set_union);
    vm.def_method(&sp, "intersection", 1, set_intersection);
    vm.def_method(&sp, "difference", 1, set_difference);
    vm.def_method(&sp, "symmetricDifference", 1, set_symmetric_difference);
    vm.def_method(&sp, "isSubsetOf", 1, set_is_subset_of);
    vm.def_method(&sp, "isSupersetOf", 1, set_is_superset_of);
    vm.def_method(&sp, "isDisjointFrom", 1, set_is_disjoint_from);
    vm.set_tag(&sp, "Set");
    vm.def_global("Set", Value::Obj(sc));

    let wmp = vm.intr.weakmap_proto.clone();
    let wmc = vm.native_ctor("WeakMap", 0, weakmap_ctor, &wmp);
    vm.def_method(&wmp, "delete", 1, weakmap_delete);
    vm.def_method(&wmp, "get", 1, weakmap_get);
    vm.def_method(&wmp, "set", 2, weakmap_set);
    vm.def_method(&wmp, "has", 1, weakmap_has);
    vm.def_method(&wmp, "getOrInsert", 2, weakmap_get_or_insert);
    vm.def_method(&wmp, "getOrInsertComputed", 2, weakmap_get_or_insert_computed);
    vm.set_tag(&wmp, "WeakMap");
    vm.def_global("WeakMap", Value::Obj(wmc));

    let wsp = vm.intr.weakset_proto.clone();
    let wsc = vm.native_ctor("WeakSet", 0, weakset_ctor, &wsp);
    vm.def_method(&wsp, "delete", 1, weakset_delete);
    vm.def_method(&wsp, "has", 1, weakset_has);
    vm.def_method(&wsp, "add", 1, weakset_add);
    vm.set_tag(&wsp, "WeakSet");
    vm.def_global("WeakSet", Value::Obj(wsc));

    let wrp = vm.intr.weakref_proto.clone();
    let wrc = vm.native_ctor("WeakRef", 1, weakref_ctor, &wrp);
    vm.def_method(&wrp, "deref", 0, weakref_deref);
    vm.set_tag(&wrp, "WeakRef");
    vm.def_global("WeakRef", Value::Obj(wrc));

    let frp = vm.intr.finreg_proto.clone();
    let frc = vm.native_ctor("FinalizationRegistry", 1, finreg_ctor, &frp);
    vm.def_method(&frp, "register", 2, finreg_register);
    vm.def_method(&frp, "unregister", 1, finreg_unregister);
    vm.set_tag(&frp, "FinalizationRegistry");
    vm.def_global("FinalizationRegistry", Value::Obj(frc));
}

fn species(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(a.this.clone())
}

fn incompatible<T>(vm: &mut Vm) -> JsResult<T> {
    vm.throw_type("method called on an incompatible receiver")
}

fn this_map(vm: &mut Vm, a: &Args) -> JsResult<Obj> {
    match &a.this {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::Map(_)) => Ok(o.clone()),
        _ => incompatible(vm),
    }
}

fn this_set(vm: &mut Vm, a: &Args) -> JsResult<Obj> {
    match &a.this {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::Set(_)) => Ok(o.clone()),
        _ => incompatible(vm),
    }
}

fn require_new(vm: &mut Vm, a: &Args, name: &str) -> JsResult<()> {
    if a.new_target.is_none() {
        return vm.throw_type(format!("Constructor {} requires 'new'", name));
    }
    Ok(())
}

fn map_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_new(vm, a, "Map")?;
    let proto = vm.proto_from_nt(&a.new_target, &vm.intr.map_proto.clone())?;
    let m = Obj::with_class(Some(proto), ObjKind::Map(Box::new(OrderedMap::new())), "Map");
    let it = a.arg(0);
    if !it.is_nullish() {
        let adder = vm.get(&m, &PropKey::from_str("set"), &Value::Obj(m.clone()))?;
        if !adder.is_callable() {
            return vm.throw_type("Map.prototype.set is not a function");
        }
        add_entries(vm, &m, &it, &adder)?;
    }
    Ok(Value::Obj(m))
}

fn add_entries(vm: &mut Vm, target: &Obj, it: &Value, adder: &Value) -> JsResult<()> {
    let (iter, next) = vm.get_iterator(it)?;
    let itv = Value::Obj(iter);
    loop {
        let item = match vm.iter_step(&itv, &next)? {
            Some(v) => v,
            None => break,
        };
        let r = (|| -> JsResult<()> {
            let io = match &item {
                Value::Obj(o) => o.clone(),
                _ => return vm.throw_type("Iterator value is not an entry object"),
            };
            let k = vm.get(&io, &PropKey::from_index(0), &item)?;
            let v = vm.get(&io, &PropKey::from_index(1), &item)?;
            vm.call(adder, Value::Obj(target.clone()), &[k, v])?;
            Ok(())
        })();
        if let Err(e) = r {
            let _ = vm.iterator_close(&itv);
            return Err(e);
        }
    }
    Ok(())
}

fn with_map<R>(o: &Obj, f: impl FnOnce(&mut OrderedMap) -> R) -> R {
    let mut b = o.borrow_mut();
    match &mut b.kind {
        ObjKind::Map(m) | ObjKind::Set(m) => f(m),
        _ => unreachable!(),
    }
}

fn map_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_map(vm, a)?;
    let k = a.arg(0);
    Ok(with_map(&m, |mm| mm.get(&k).cloned()).unwrap_or(Value::Undefined))
}

fn map_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_map(vm, a)?;
    let (k, v) = (a.arg(0), a.arg(1));
    with_map(&m, |mm| mm.set(k, v));
    Ok(Value::Obj(m))
}

fn map_has(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_map(vm, a)?;
    let k = a.arg(0);
    Ok(Value::Bool(with_map(&m, |mm| mm.has(&k))))
}

fn map_delete(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_map(vm, a)?;
    let k = a.arg(0);
    Ok(Value::Bool(with_map(&m, |mm| mm.delete(&k))))
}

fn map_clear(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_map(vm, a)?;
    with_map(&m, |mm| mm.clear());
    Ok(Value::Undefined)
}

fn map_size(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_map(vm, a)?;
    Ok(Value::Num(with_map(&m, |mm| mm.live) as f64))
}

fn map_get_or_insert(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_map(vm, a)?;
    let k = a.arg(0);
    if let Some(v) = with_map(&m, |mm| mm.get(&k).cloned()) {
        return Ok(v);
    }
    let v = a.arg(1);
    with_map(&m, |mm| mm.set(k, v.clone()));
    Ok(v)
}

fn map_get_or_insert_computed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_map(vm, a)?;
    let cb = a.arg(1);
    if !cb.is_callable() {
        return vm.throw_type("callback is not a function");
    }
    let k = a.arg(0);
    let k = if let Value::Num(n) = k { if n == 0.0 { Value::Num(0.0) } else { k } } else { k };
    if let Some(v) = with_map(&m, |mm| mm.get(&k).cloned()) {
        return Ok(v);
    }
    let v = vm.call(&cb, Value::Undefined, &[k.clone()])?;
    with_map(&m, |mm| mm.set(k, v.clone()));
    Ok(v)
}

fn map_for_each(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_map(vm, a)?;
    let f = a.arg(0);
    if !f.is_callable() {
        return vm.throw_type("Map.prototype.forEach callback is not callable");
    }
    let t = a.arg(1);
    let mut i = 0;
    loop {
        let e = {
            let b = m.borrow();
            match &b.kind {
                ObjKind::Map(mm) => {
                    let mut found = None;
                    while i < mm.entries.len() {
                        if let Some((k, v)) = &mm.entries[i] {
                            found = Some((k.clone(), v.clone()));
                            i += 1;
                            break;
                        }
                        i += 1;
                    }
                    found
                }
                _ => None,
            }
        };
        match e {
            Some((k, v)) => {
                vm.call(&f, t.clone(), &[v, k, Value::Obj(m.clone())])?;
            }
            None => break,
        }
    }
    Ok(Value::Undefined)
}

fn map_entries(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_map(vm, a)?;
    Ok(crate::builtins::iterator::create_map_iterator(vm, m, 2))
}
fn map_keys(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_map(vm, a)?;
    Ok(crate::builtins::iterator::create_map_iterator(vm, m, 0))
}
fn map_values(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_map(vm, a)?;
    Ok(crate::builtins::iterator::create_map_iterator(vm, m, 1))
}

fn map_group_by(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let items = a.arg(0);
    let cb = a.arg(1);
    if !cb.is_callable() {
        return vm.throw_type("callback is not a function");
    }
    let m = Obj::with_class(Some(vm.intr.map_proto.clone()), ObjKind::Map(Box::new(OrderedMap::new())), "Map");
    let (iter, next) = vm.get_iterator(&items)?;
    let itv = Value::Obj(iter);
    let mut k = 0usize;
    while let Some(v) = vm.iter_step(&itv, &next)? {
        let key = match vm.call(&cb, Value::Undefined, &[v.clone(), Value::Num(k as f64)]) {
            Ok(x) => x,
            Err(e) => {
                let _ = vm.iterator_close(&itv);
                return Err(e);
            }
        };
        let key = if let Value::Num(n) = key { if n == 0.0 { Value::Num(0.0) } else { key } } else { key };
        let existing = with_map(&m, |mm| mm.get(&key).cloned());
        match existing {
            Some(Value::Obj(arr)) => crate::vm::array_push_raw(&arr, v),
            _ => {
                let arr = vm.new_array(vec![v]);
                with_map(&m, |mm| mm.set(key, Value::Obj(arr)));
            }
        }
        k += 1;
    }
    Ok(Value::Obj(m))
}

// ---------------- Set ----------------

fn set_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_new(vm, a, "Set")?;
    let proto = vm.proto_from_nt(&a.new_target, &vm.intr.set_proto.clone())?;
    let s = Obj::with_class(Some(proto), ObjKind::Set(Box::new(OrderedMap::new())), "Set");
    let it = a.arg(0);
    if !it.is_nullish() {
        let adder = vm.get(&s, &PropKey::from_str("add"), &Value::Obj(s.clone()))?;
        if !adder.is_callable() {
            return vm.throw_type("Set.prototype.add is not a function");
        }
        // fast path for arrays with the builtin add
        let vals = vm.iterate_to_vec(&it)?;
        for v in vals {
            vm.call(&adder, Value::Obj(s.clone()), &[v])?;
        }
    }
    Ok(Value::Obj(s))
}

fn set_has(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_set(vm, a)?;
    let k = a.arg(0);
    Ok(Value::Bool(with_map(&s, |m| m.has(&k))))
}

fn set_add(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_set(vm, a)?;
    let k = a.arg(0);
    with_map(&s, |m| {
        if !m.has(&k) {
            m.set(k.clone(), k)
        }
    });
    Ok(Value::Obj(s))
}

fn set_delete(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_set(vm, a)?;
    let k = a.arg(0);
    Ok(Value::Bool(with_map(&s, |m| m.delete(&k))))
}

fn set_clear(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_set(vm, a)?;
    with_map(&s, |m| m.clear());
    Ok(Value::Undefined)
}

fn set_size(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_set(vm, a)?;
    Ok(Value::Num(with_map(&s, |m| m.live) as f64))
}

fn set_for_each(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_set(vm, a)?;
    let f = a.arg(0);
    if !f.is_callable() {
        return vm.throw_type("Set.prototype.forEach callback is not callable");
    }
    let t = a.arg(1);
    let mut i = 0;
    loop {
        let e = {
            let b = s.borrow();
            match &b.kind {
                ObjKind::Set(m) => {
                    let mut found = None;
                    while i < m.entries.len() {
                        if let Some((k, _)) = &m.entries[i] {
                            found = Some(k.clone());
                            i += 1;
                            break;
                        }
                        i += 1;
                    }
                    found
                }
                _ => None,
            }
        };
        match e {
            Some(k) => {
                vm.call(&f, t.clone(), &[k.clone(), k, Value::Obj(s.clone())])?;
            }
            None => break,
        }
    }
    Ok(Value::Undefined)
}

fn set_entries(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_set(vm, a)?;
    Ok(crate::builtins::iterator::create_set_iterator(vm, s, 2))
}
fn set_values(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_set(vm, a)?;
    Ok(crate::builtins::iterator::create_set_iterator(vm, s, 1))
}

fn set_values_vec(s: &Obj) -> Vec<Value> {
    let b = s.borrow();
    match &b.kind {
        ObjKind::Set(m) => m.entries.iter().flatten().map(|(k, _)| k.clone()).collect(),
        _ => Vec::new(),
    }
}

struct SetRecord {
    obj: Value,
    size: f64,
    has: Value,
    keys: Value,
}

fn get_set_record(vm: &mut Vm, v: &Value) -> JsResult<SetRecord> {
    let o = match v {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("set-like argument must be an object"),
    };
    let raw = vm.get_str(&o, "size")?;
    let n = vm.to_number(&raw)?;
    if n.is_nan() {
        return vm.throw_type("set-like size is not a number");
    }
    let size = crate::ops::integer_or_infinity(n);
    if size < 0.0 {
        return vm.throw_range("set-like size must be non-negative");
    }
    let has = vm.get_str(&o, "has")?;
    if !has.is_callable() {
        return vm.throw_type("set-like has is not a function");
    }
    let keys = vm.get_str(&o, "keys")?;
    if !keys.is_callable() {
        return vm.throw_type("set-like keys is not a function");
    }
    Ok(SetRecord { obj: v.clone(), size, has, keys })
}

fn new_set_from(vm: &mut Vm, vals: Vec<Value>) -> Value {
    let mut m = OrderedMap::new();
    for v in vals {
        if !m.has(&v) {
            m.set(v.clone(), v);
        }
    }
    Value::Obj(Obj::with_class(Some(vm.intr.set_proto.clone()), ObjKind::Set(Box::new(m)), "Set"))
}

fn record_keys(vm: &mut Vm, r: &SetRecord) -> JsResult<Vec<Value>> {
    let it = vm.call(&r.keys, r.obj.clone(), &[])?;
    let io = match &it {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("keys() result is not an object"),
    };
    let next = vm.get(&io, &vm.intr.key_next.clone(), &it)?;
    let mut out = Vec::new();
    while let Some(v) = vm.iter_step(&it, &next)? {
        let v = if let Value::Num(n) = v { if n == 0.0 { Value::Num(0.0) } else { v } } else { v };
        out.push(v);
    }
    Ok(out)
}

fn set_union(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_set(vm, a)?;
    let r = get_set_record(vm, &a.arg(0))?;
    let mut vals = set_values_vec(&s);
    vals.extend(record_keys(vm, &r)?);
    Ok(new_set_from(vm, vals))
}

fn set_intersection(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_set(vm, a)?;
    let r = get_set_record(vm, &a.arg(0))?;
    let mine = set_values_vec(&s);
    let mut out = Vec::new();
    if (mine.len() as f64) <= r.size {
        for v in mine {
            if vm.call(&r.has, r.obj.clone(), &[v.clone()])?.truthy() {
                out.push(v);
            }
        }
    } else {
        for v in record_keys(vm, &r)? {
            if with_map(&s, |m| m.has(&v)) {
                out.push(v);
            }
        }
    }
    Ok(new_set_from(vm, out))
}

fn set_difference(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_set(vm, a)?;
    let r = get_set_record(vm, &a.arg(0))?;
    let mine = set_values_vec(&s);
    let mut out = Vec::new();
    if (mine.len() as f64) <= r.size {
        for v in mine {
            if !vm.call(&r.has, r.obj.clone(), &[v.clone()])?.truthy() {
                out.push(v);
            }
        }
    } else {
        let other = record_keys(vm, &r)?;
        let mut m = OrderedMap::new();
        for v in &other {
            m.set(v.clone(), Value::Undefined);
        }
        for v in mine {
            if !m.has(&v) {
                out.push(v);
            }
        }
    }
    Ok(new_set_from(vm, out))
}

fn set_symmetric_difference(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_set(vm, a)?;
    let r = get_set_record(vm, &a.arg(0))?;
    let mine = set_values_vec(&s);
    let other = record_keys(vm, &r)?;
    let mut result = mine.clone();
    let mut mm = OrderedMap::new();
    for v in &mine {
        mm.set(v.clone(), Value::Undefined);
    }
    for v in other {
        if mm.has(&v) {
            result.retain(|x| !Value::same_value_zero(x, &v));
        } else if !result.iter().any(|x| Value::same_value_zero(x, &v)) {
            result.push(v);
        }
    }
    Ok(new_set_from(vm, result))
}

fn set_is_subset_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_set(vm, a)?;
    let r = get_set_record(vm, &a.arg(0))?;
    let mine = set_values_vec(&s);
    if (mine.len() as f64) > r.size {
        return Ok(Value::Bool(false));
    }
    for v in mine {
        if !vm.call(&r.has, r.obj.clone(), &[v])?.truthy() {
            return Ok(Value::Bool(false));
        }
    }
    Ok(Value::Bool(true))
}

fn set_is_superset_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_set(vm, a)?;
    let r = get_set_record(vm, &a.arg(0))?;
    let n = with_map(&s, |m| m.live);
    if (n as f64) < r.size {
        return Ok(Value::Bool(false));
    }
    for v in record_keys(vm, &r)? {
        if !with_map(&s, |m| m.has(&v)) {
            return Ok(Value::Bool(false));
        }
    }
    Ok(Value::Bool(true))
}

fn set_is_disjoint_from(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_set(vm, a)?;
    let r = get_set_record(vm, &a.arg(0))?;
    let mine = set_values_vec(&s);
    if (mine.len() as f64) <= r.size {
        for v in mine {
            if vm.call(&r.has, r.obj.clone(), &[v])?.truthy() {
                return Ok(Value::Bool(false));
            }
        }
    } else {
        for v in record_keys(vm, &r)? {
            if with_map(&s, |m| m.has(&v)) {
                return Ok(Value::Bool(false));
            }
        }
    }
    Ok(Value::Bool(true))
}

// ---------------- WeakMap / WeakSet ----------------

fn can_be_held_weakly(v: &Value) -> Option<Obj> {
    match v {
        Value::Obj(o) => Some(o.clone()),
        _ => None,
    }
}

fn weakmap_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_new(vm, a, "WeakMap")?;
    let proto = vm.proto_from_nt(&a.new_target, &vm.intr.weakmap_proto.clone())?;
    let m = Obj::with_class(Some(proto), ObjKind::WeakMap(Box::new(WeakTable::new())), "WeakMap");
    let it = a.arg(0);
    if !it.is_nullish() {
        let adder = vm.get(&m, &PropKey::from_str("set"), &Value::Obj(m.clone()))?;
        add_entries(vm, &m, &it, &adder)?;
    }
    Ok(Value::Obj(m))
}

fn this_weakmap(vm: &mut Vm, a: &Args) -> JsResult<Obj> {
    match &a.this {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::WeakMap(_)) => Ok(o.clone()),
        _ => incompatible(vm),
    }
}

fn with_weak<R>(o: &Obj, f: impl FnOnce(&mut WeakTable) -> R) -> R {
    let mut b = o.borrow_mut();
    match &mut b.kind {
        ObjKind::WeakMap(m) | ObjKind::WeakSet(m) => f(m),
        _ => unreachable!(),
    }
}

fn weakmap_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_weakmap(vm, a)?;
    match can_be_held_weakly(&a.arg(0)) {
        Some(k) => Ok(with_weak(&m, |t| t.get(&k)).unwrap_or(Value::Undefined)),
        None => Ok(Value::Undefined),
    }
}

fn weakmap_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_weakmap(vm, a)?;
    match can_be_held_weakly(&a.arg(0)) {
        Some(k) => {
            let v = a.arg(1);
            with_weak(&m, |t| t.set(&k, v));
            Ok(Value::Obj(m))
        }
        None => vm.throw_type("Invalid value used as weak map key"),
    }
}

fn weakmap_has(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_weakmap(vm, a)?;
    match can_be_held_weakly(&a.arg(0)) {
        Some(k) => Ok(Value::Bool(with_weak(&m, |t| t.has(&k)))),
        None => Ok(Value::Bool(false)),
    }
}

fn weakmap_delete(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_weakmap(vm, a)?;
    match can_be_held_weakly(&a.arg(0)) {
        Some(k) => Ok(Value::Bool(with_weak(&m, |t| t.delete(&k)))),
        None => Ok(Value::Bool(false)),
    }
}

fn weakmap_get_or_insert(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_weakmap(vm, a)?;
    let k = match can_be_held_weakly(&a.arg(0)) {
        Some(k) => k,
        None => return vm.throw_type("Invalid value used as weak map key"),
    };
    if let Some(v) = with_weak(&m, |t| t.get(&k)) {
        return Ok(v);
    }
    let v = a.arg(1);
    with_weak(&m, |t| t.set(&k, v.clone()));
    Ok(v)
}

fn weakmap_get_or_insert_computed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = this_weakmap(vm, a)?;
    let k = match can_be_held_weakly(&a.arg(0)) {
        Some(k) => k,
        None => return vm.throw_type("Invalid value used as weak map key"),
    };
    let cb = a.arg(1);
    if !cb.is_callable() {
        return vm.throw_type("callback is not a function");
    }
    if let Some(v) = with_weak(&m, |t| t.get(&k)) {
        return Ok(v);
    }
    let v = vm.call(&cb, Value::Undefined, &[Value::Obj(k.clone())])?;
    with_weak(&m, |t| t.set(&k, v.clone()));
    Ok(v)
}

fn weakset_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_new(vm, a, "WeakSet")?;
    let proto = vm.proto_from_nt(&a.new_target, &vm.intr.weakset_proto.clone())?;
    let s = Obj::with_class(Some(proto), ObjKind::WeakSet(Box::new(WeakTable::new())), "WeakSet");
    let it = a.arg(0);
    if !it.is_nullish() {
        let adder = vm.get(&s, &PropKey::from_str("add"), &Value::Obj(s.clone()))?;
        let vals = vm.iterate_to_vec(&it)?;
        for v in vals {
            vm.call(&adder, Value::Obj(s.clone()), &[v])?;
        }
    }
    Ok(Value::Obj(s))
}

fn this_weakset(vm: &mut Vm, a: &Args) -> JsResult<Obj> {
    match &a.this {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::WeakSet(_)) => Ok(o.clone()),
        _ => incompatible(vm),
    }
}

fn weakset_add(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_weakset(vm, a)?;
    match can_be_held_weakly(&a.arg(0)) {
        Some(k) => {
            with_weak(&s, |t| t.set(&k, Value::Bool(true)));
            Ok(Value::Obj(s))
        }
        None => vm.throw_type("Invalid value used in weak set"),
    }
}

fn weakset_has(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_weakset(vm, a)?;
    match can_be_held_weakly(&a.arg(0)) {
        Some(k) => Ok(Value::Bool(with_weak(&s, |t| t.has(&k)))),
        None => Ok(Value::Bool(false)),
    }
}

fn weakset_delete(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_weakset(vm, a)?;
    match can_be_held_weakly(&a.arg(0)) {
        Some(k) => Ok(Value::Bool(with_weak(&s, |t| t.delete(&k)))),
        None => Ok(Value::Bool(false)),
    }
}

// ---------------- WeakRef / FinalizationRegistry ----------------

fn weakref_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_new(vm, a, "WeakRef")?;
    let t = match can_be_held_weakly(&a.arg(0)) {
        Some(t) => t,
        None => return vm.throw_type("WeakRef: target must be an object"),
    };
    let proto = vm.proto_from_nt(&a.new_target, &vm.intr.weakref_proto.clone())?;
    // keep the target alive until the end of the current job (like KeepDuringJob)
    vm.host.kept_alive.push(Value::Obj(t.clone()));
    Ok(Value::Obj(Obj::with_class(Some(proto), ObjKind::WeakRef(t.downgrade()), "WeakRef")))
}

fn weakref_deref(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match &a.this {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::WeakRef(w) => Ok(match w.upgrade() {
                Some(rc) => Value::Obj(Obj(rc)),
                None => Value::Undefined,
            }),
            _ => Err(vm.make_error("TypeError", "WeakRef.prototype.deref called on incompatible receiver")),
        },
        _ => vm.throw_type("WeakRef.prototype.deref called on incompatible receiver"),
    }
}

fn finreg_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_new(vm, a, "FinalizationRegistry")?;
    let cb = a.arg(0);
    if !cb.is_callable() {
        return vm.throw_type("FinalizationRegistry: cleanup must be callable");
    }
    let proto = vm.proto_from_nt(&a.new_target, &vm.intr.finreg_proto.clone())?;
    Ok(Value::Obj(Obj::with_class(Some(proto), ObjKind::FinalizationRegistry(Box::new(Vec::new()), cb), "FinalizationRegistry")))
}

fn finreg_register(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = match &a.this {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::FinalizationRegistry(..)) => o.clone(),
        _ => return incompatible(vm),
    };
    let t = match can_be_held_weakly(&a.arg(0)) {
        Some(t) => t,
        None => return vm.throw_type("FinalizationRegistry.prototype.register: invalid target"),
    };
    if let Value::Obj(h) = &a.arg(1) {
        if h.ptr_eq(&t) {
            return vm.throw_type("FinalizationRegistry.prototype.register: target and holdings must not be same");
        }
    }
    let token = a.arg(2);
    if !token.is_undefined() && !token.is_object() {
        return vm.throw_type("FinalizationRegistry.prototype.register: invalid unregister token");
    }
    if let ObjKind::FinalizationRegistry(list, _) = &mut r.borrow_mut().kind {
        list.push((t.downgrade(), a.arg(1), if token.is_undefined() { None } else { Some(token) }));
    }
    Ok(Value::Undefined)
}

fn finreg_unregister(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = match &a.this {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::FinalizationRegistry(..)) => o.clone(),
        _ => return incompatible(vm),
    };
    let token = a.arg(0);
    if !token.is_object() {
        return vm.throw_type("FinalizationRegistry.prototype.unregister: invalid unregister token");
    }
    let mut removed = false;
    if let ObjKind::FinalizationRegistry(list, _) = &mut r.borrow_mut().kind {
        let before = list.len();
        list.retain(|(_, _, t)| !matches!(t, Some(tv) if Value::strict_eq(tv, &token)));
        removed = list.len() != before;
    }
    Ok(Value::Bool(removed))
}
