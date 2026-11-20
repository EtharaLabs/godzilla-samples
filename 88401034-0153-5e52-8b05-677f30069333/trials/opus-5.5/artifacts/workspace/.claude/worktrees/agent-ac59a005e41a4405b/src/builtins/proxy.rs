// Proxy exotic objects and the Reflect namespace.

use crate::builtins::object::{from_property_descriptor, to_property_descriptor};
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let pc = vm.native_fn("Proxy", 2, proxy_ctor);
    vm.make_ctor(&pc);
    vm.def_method(&pc, "revocable", 2, proxy_revocable);
    vm.def_global("Proxy", Value::Obj(pc));

    let r = vm.new_object();
    let fns: &[(&str, u32, NativeFn)] = &[
        ("defineProperty", 3, reflect_define_property),
        ("deleteProperty", 2, reflect_delete_property),
        ("apply", 3, reflect_apply),
        ("construct", 2, reflect_construct),
        ("get", 2, reflect_get),
        ("getOwnPropertyDescriptor", 2, reflect_get_own_property_descriptor),
        ("getPrototypeOf", 1, reflect_get_prototype_of),
        ("has", 2, reflect_has),
        ("isExtensible", 1, reflect_is_extensible),
        ("ownKeys", 1, reflect_own_keys),
        ("preventExtensions", 1, reflect_prevent_extensions),
        ("set", 3, reflect_set),
        ("setPrototypeOf", 2, reflect_set_prototype_of),
    ];
    for (n, l, f) in fns {
        vm.def_method(&r, n, *l, *f);
    }
    vm.set_tag(&r, "Reflect");
    vm.def_global("Reflect", Value::Obj(r));
}

fn create_proxy(vm: &mut Vm, target: &Value, handler: &Value) -> JsResult<Obj> {
    let (t, h) = match (target, handler) {
        (Value::Obj(t), Value::Obj(h)) => (t.clone(), h.clone()),
        _ => return vm.throw_type("Cannot create proxy with a non-object as target or handler"),
    };
    let callable = t.is_callable();
    let constructor = t.is_constructor();
    Ok(Obj::with_class(None, ObjKind::Proxy(Box::new(ProxyData { target: Some(t), handler: Some(h), callable, constructor })), "Proxy"))
}

fn proxy_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return vm.throw_type("Constructor Proxy requires 'new'");
    }
    Ok(Value::Obj(create_proxy(vm, &a.arg(0), &a.arg(1))?))
}

fn proxy_revocable(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = create_proxy(vm, &a.arg(0), &a.arg(1))?;
    let revoke = vm.native_closure("", 0, revoke_fn, vec![Value::Obj(p.clone())]);
    let o = vm.new_object();
    o.set_str("proxy", Value::Obj(p), WEC);
    o.set_str("revoke", Value::Obj(revoke), WEC);
    Ok(Value::Obj(o))
}

fn revoke_fn(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let Value::Obj(p) = a.slot(0) {
        if let ObjKind::Proxy(pd) = &mut p.borrow_mut().kind {
            pd.target = None;
            pd.handler = None;
        }
    }
    // only the first call revokes
    if let ObjKind::Native(n) = &mut a.callee.borrow_mut().kind {
        n.slots.clear();
    }
    Ok(Value::Undefined)
}

fn parts(vm: &mut Vm, p: &Obj, trap: &str) -> JsResult<(Obj, Obj, Option<Value>)> {
    let (t, h) = match &p.borrow().kind {
        ObjKind::Proxy(pd) => (pd.target.clone(), pd.handler.clone()),
        _ => (None, None),
    };
    let (t, h) = match (t, h) {
        (Some(t), Some(h)) => (t, h),
        _ => {
            // reference engine messages for operations on revoked proxies
            return match trap {
                "has" => vm.throw_type("cannot perform 'has' on a revoked proxy"),
                "deleteProperty" => vm.throw_type("cannot delete on a revoked proxy"),
                "isExtensible" | "getOwnPropertyDescriptor" | "setPrototypeOf" | "preventExtensions" => vm.throw_type("proxy is revoked"),
                _ => vm.throw_type(format!("cannot read property '{}' of null", trap)),
            };
        }
    };
    let tr = vm.get(&h, &PropKey::from_str(trap), &Value::Obj(h.clone()))?;
    if tr.is_nullish() {
        return Ok((t, h, None));
    }
    if !tr.is_callable() {
        return vm.throw_type(format!("proxy '{}' trap is not callable", trap));
    }
    Ok((t, h, Some(tr)))
}

fn key_val(k: &PropKey) -> Value {
    match k {
        PropKey::Str(s) => Value::Str(s.clone()),
        PropKey::Sym(s) => Value::Sym(s.clone()),
    }
}

pub fn proxy_get_prototype_of(vm: &mut Vm, p: &Obj) -> JsResult<Option<Obj>> {
    let (t, h, trap) = parts(vm, p, "getPrototypeOf")?;
    let trap = match trap {
        None => return vm.get_prototype_of(&t),
        Some(f) => f,
    };
    let r = vm.call(&trap, Value::Obj(h), &[Value::Obj(t.clone())])?;
    let proto = match r {
        Value::Obj(o) => Some(o),
        Value::Null => None,
        _ => return vm.throw_type("getPrototypeOf trap must return an object or null"),
    };
    if vm.is_extensible(&t)? {
        return Ok(proto);
    }
    let tp = vm.get_prototype_of(&t)?;
    let same = match (&tp, &proto) {
        (Some(a), Some(b)) => a.ptr_eq(b),
        (None, None) => true,
        _ => false,
    };
    if !same {
        return vm.throw_type("getPrototypeOf trap result differs from a non-extensible target's prototype");
    }
    Ok(proto)
}

pub fn proxy_set_prototype_of(vm: &mut Vm, p: &Obj, v: Option<Obj>) -> JsResult<bool> {
    let (t, h, trap) = parts(vm, p, "setPrototypeOf")?;
    let trap = match trap {
        None => return vm.set_prototype_of(&t, v),
        Some(f) => f,
    };
    let vv = v.clone().map(Value::Obj).unwrap_or(Value::Null);
    let r = vm.call(&trap, Value::Obj(h), &[Value::Obj(t.clone()), vv])?.truthy();
    if !r {
        return Ok(false);
    }
    if vm.is_extensible(&t)? {
        return Ok(true);
    }
    let tp = vm.get_prototype_of(&t)?;
    let same = match (&tp, &v) {
        (Some(a), Some(b)) => a.ptr_eq(b),
        (None, None) => true,
        _ => false,
    };
    if !same {
        return vm.throw_type("proxy 'setPrototypeOf' changed a non-extensible target's prototype");
    }
    Ok(true)
}

pub fn proxy_is_extensible(vm: &mut Vm, p: &Obj) -> JsResult<bool> {
    let (t, h, trap) = parts(vm, p, "isExtensible")?;
    let trap = match trap {
        None => return vm.is_extensible(&t),
        Some(f) => f,
    };
    let r = vm.call(&trap, Value::Obj(h), &[Value::Obj(t.clone())])?.truthy();
    if r != vm.is_extensible(&t)? {
        return vm.throw_type("proxy 'isExtensible' must match the target");
    }
    Ok(r)
}

pub fn proxy_prevent_extensions(vm: &mut Vm, p: &Obj) -> JsResult<bool> {
    let (t, h, trap) = parts(vm, p, "preventExtensions")?;
    let trap = match trap {
        None => return vm.prevent_extensions(&t),
        Some(f) => f,
    };
    let r = vm.call(&trap, Value::Obj(h), &[Value::Obj(t.clone())])?.truthy();
    if r && vm.is_extensible(&t)? {
        return vm.throw_type("proxy 'preventExtensions' reported success but the target is extensible");
    }
    Ok(r)
}

pub fn proxy_get_own_property(vm: &mut Vm, p: &Obj, k: &PropKey) -> JsResult<Option<PropDesc>> {
    let (t, h, trap) = parts(vm, p, "getOwnPropertyDescriptor")?;
    let trap = match trap {
        None => return vm.get_own_property(&t, k),
        Some(f) => f,
    };
    let r = vm.call(&trap, Value::Obj(h), &[Value::Obj(t.clone()), key_val(k)])?;
    if !r.is_object() && !r.is_undefined() {
        return vm.throw_type("getOwnPropertyDescriptor trap must return an object or undefined");
    }
    let target_desc = vm.get_own_property(&t, k)?;
    if r.is_undefined() {
        if let Some(td) = &target_desc {
            if td.configurable == Some(false) {
                return vm.throw_type("gOPD trap reported undefined for a non-configurable property");
            }
            if !vm.is_extensible(&t)? {
                return vm.throw_type("gOPD trap reported undefined for a non-extensible target's property");
            }
        }
        return Ok(None);
    }
    let mut d = to_property_descriptor(vm, &r)?;
    // complete
    if !d.is_accessor() {
        if d.value.is_none() {
            d.value = Some(Value::Undefined);
        }
        if d.writable.is_none() {
            d.writable = Some(false);
        }
    } else {
        if d.get.is_none() {
            d.get = Some(Value::Undefined);
        }
        if d.set.is_none() {
            d.set = Some(Value::Undefined);
        }
    }
    if d.enumerable.is_none() {
        d.enumerable = Some(false);
    }
    if d.configurable.is_none() {
        d.configurable = Some(false);
    }
    let ext = vm.is_extensible(&t)?;
    let cur = target_desc.as_ref().map(|td| desc_to_prop(td));
    if !crate::props::validate_and_apply(None, k, ext, &d, cur.clone()) {
        if cur.is_none() && !ext {
            return vm.throw_type("gOPD trap reported a property missing from a non-extensible target");
        }
        return vm.throw_type("gOPD trap reported a descriptor incompatible with the target's property");
    }
    if d.configurable == Some(false) {
        match &target_desc {
            None => return vm.throw_type("gOPD trap reported a non-configurable descriptor the target lacks"),
            Some(td) => {
                if td.configurable == Some(true) {
                    return vm.throw_type("gOPD trap reported a non-configurable descriptor the target lacks");
                }
                if d.writable == Some(false) && td.writable == Some(true) {
                    return vm.throw_type("gOPD trap reported non-writable for a writable non-configurable property");
                }
            }
        }
    }
    Ok(Some(d))
}

fn desc_to_prop(d: &PropDesc) -> Prop {
    if d.is_accessor() {
        Prop::Accessor { get: d.get.clone().and_then(|v| v.as_obj().cloned()), set: d.set.clone().and_then(|v| v.as_obj().cloned()), flags: d.flags() & !WRITABLE }
    } else {
        Prop::Data { value: d.value.clone().unwrap_or(Value::Undefined), flags: d.flags() }
    }
}

pub fn proxy_define_own_property(vm: &mut Vm, p: &Obj, k: PropKey, d: PropDesc) -> JsResult<bool> {
    let (t, h, trap) = parts(vm, p, "defineProperty")?;
    let trap = match trap {
        None => return vm.define_own_property(&t, k, d),
        Some(f) => f,
    };
    let dv = from_property_descriptor(vm, &d);
    let r = vm.call(&trap, Value::Obj(h), &[Value::Obj(t.clone()), key_val(&k), dv])?.truthy();
    if !r {
        return Ok(false);
    }
    let target_desc = vm.get_own_property(&t, &k)?;
    let ext = vm.is_extensible(&t)?;
    let setting_nc = d.configurable == Some(false);
    match &target_desc {
        None => {
            if !ext {
                return vm.throw_type("proxy 'defineProperty' added a property to a non-extensible target");
            }
            if setting_nc {
                return vm.throw_type("proxy 'defineProperty' defined a non-configurable property the target lacks");
            }
        }
        Some(td) => {
            if !crate::props::validate_and_apply(None, &k, ext, &d, Some(desc_to_prop(td))) {
                return vm.throw_type("proxy 'defineProperty' is incompatible with the target's property");
            }
            if setting_nc && td.configurable == Some(true) {
                return vm.throw_type("proxy 'defineProperty' defined a non-configurable property the target lacks");
            }
            if td.is_data() && td.configurable == Some(false) && td.writable == Some(true) && d.writable == Some(false) {
                return vm.throw_type("proxy 'defineProperty' made a writable non-configurable property non-writable");
            }
        }
    }
    Ok(true)
}

pub fn proxy_has(vm: &mut Vm, p: &Obj, k: &PropKey) -> JsResult<bool> {
    let (t, h, trap) = parts(vm, p, "has")?;
    let trap = match trap {
        None => return vm.has_property(&t, k),
        Some(f) => f,
    };
    let r = vm.call(&trap, Value::Obj(h), &[Value::Obj(t.clone()), key_val(k)])?.truthy();
    if !r {
        if let Some(td) = vm.get_own_property(&t, k)? {
            if td.configurable == Some(false) {
                return vm.throw_type("proxy 'has' trap hid a non-configurable property");
            }
            if !vm.is_extensible(&t)? {
                return vm.throw_type("proxy 'has' trap hid a non-configurable property");
            }
        }
    }
    Ok(r)
}

pub fn proxy_get(vm: &mut Vm, p: &Obj, k: &PropKey, receiver: &Value) -> JsResult<Value> {
    let (t, h, trap) = parts(vm, p, "get")?;
    let trap = match trap {
        None => return vm.get(&t, k, receiver),
        Some(f) => f,
    };
    let v = vm.call(&trap, Value::Obj(h), &[Value::Obj(t.clone()), key_val(k), receiver.clone()])?;
    if let Some(td) = vm.get_own_property(&t, k)? {
        if td.configurable == Some(false) {
            if td.is_data() && td.writable == Some(false) && !Value::same_value(&v, td.value.as_ref().unwrap_or(&Value::Undefined)) {
                return vm.throw_type("proxy 'get' trap violated an invariant for a non-configurable property");
            }
            if td.is_accessor() && matches!(td.get, Some(Value::Undefined) | None) && !v.is_undefined() {
                return vm.throw_type("proxy 'get' trap violated an invariant for a non-configurable property");
            }
        }
    }
    Ok(v)
}

pub fn proxy_set(vm: &mut Vm, p: &Obj, k: PropKey, v: Value, receiver: &Value) -> JsResult<bool> {
    let (t, h, trap) = parts(vm, p, "set")?;
    let trap = match trap {
        None => return vm.set(&t, k, v, receiver),
        Some(f) => f,
    };
    let r = vm.call(&trap, Value::Obj(h), &[Value::Obj(t.clone()), key_val(&k), v.clone(), receiver.clone()])?.truthy();
    if !r {
        return Ok(false);
    }
    if let Some(td) = vm.get_own_property(&t, &k)? {
        if td.configurable == Some(false) {
            if td.is_data() && td.writable == Some(false) && !Value::same_value(&v, td.value.as_ref().unwrap_or(&Value::Undefined)) {
                return vm.throw_type("proxy 'set' trap violated an invariant for a non-configurable property");
            }
            if td.is_accessor() && matches!(td.set, Some(Value::Undefined) | None) {
                return vm.throw_type("proxy 'set' trap violated an invariant for a non-configurable property");
            }
        }
    }
    Ok(true)
}

pub fn proxy_delete(vm: &mut Vm, p: &Obj, k: &PropKey) -> JsResult<bool> {
    let (t, h, trap) = parts(vm, p, "deleteProperty")?;
    let trap = match trap {
        None => return vm.delete(&t, k),
        Some(f) => f,
    };
    let r = vm.call(&trap, Value::Obj(h), &[Value::Obj(t.clone()), key_val(k)])?.truthy();
    if !r {
        return Ok(false);
    }
    if let Some(td) = vm.get_own_property(&t, k)? {
        if td.configurable == Some(false) {
            return vm.throw_type("proxy 'deleteProperty' removed a non-configurable property");
        }
        if !vm.is_extensible(&t)? {
            return vm.throw_type("proxy 'deleteProperty' removed a non-extensible target's property");
        }
    }
    Ok(true)
}

pub fn proxy_own_keys(vm: &mut Vm, p: &Obj) -> JsResult<Vec<PropKey>> {
    let (t, h, trap) = parts(vm, p, "ownKeys")?;
    let trap = match trap {
        None => return vm.own_property_keys(&t),
        Some(f) => f,
    };
    let r = vm.call(&trap, Value::Obj(h), &[Value::Obj(t.clone())])?;
    let ro = match &r {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("ownKeys trap must return an array-like object"),
    };
    let len = vm.length_of(&ro)?;
    let mut keys: Vec<PropKey> = Vec::new();
    for i in 0..len {
        let v = vm.get(&ro, &PropKey::from_index(i as u32), &r)?;
        let k = match v {
            Value::Str(s) => PropKey::Str(s),
            Value::Sym(s) => PropKey::Sym(s),
            _ => return vm.throw_type("ownKeys trap result must contain only strings and symbols"),
        };
        if keys.contains(&k) {
            return vm.throw_type("ownKeys trap result has duplicate keys");
        }
        keys.push(k);
    }
    let ext = vm.is_extensible(&t)?;
    let target_keys = vm.own_property_keys(&t)?;
    let mut nonconfig = Vec::new();
    let mut config = Vec::new();
    for k in target_keys {
        match vm.get_own_property(&t, &k)? {
            Some(d) if d.configurable == Some(false) => nonconfig.push(k),
            _ => config.push(k),
        }
    }
    if ext && nonconfig.is_empty() {
        return Ok(keys);
    }
    let mut unchecked = keys.clone();
    for k in nonconfig {
        match unchecked.iter().position(|x| *x == k) {
            Some(i) => {
                unchecked.remove(i);
            }
            None => return vm.throw_type("ownKeys trap omitted a non-configurable target key"),
        }
    }
    if ext {
        return Ok(keys);
    }
    for k in config {
        match unchecked.iter().position(|x| *x == k) {
            Some(i) => {
                unchecked.remove(i);
            }
            None => return vm.throw_type("ownKeys trap omitted a key of a non-extensible target"),
        }
    }
    if !unchecked.is_empty() {
        return vm.throw_type("ownKeys trap added a key to a non-extensible target");
    }
    Ok(keys)
}

pub fn proxy_call(vm: &mut Vm, p: &Obj, this: Value, args: &[Value]) -> JsResult<Value> {
    let (t, h, trap) = parts(vm, p, "apply")?;
    let trap = match trap {
        None => return vm.call(&Value::Obj(t), this, args),
        Some(f) => f,
    };
    let arr = vm.new_array(args.to_vec());
    vm.call(&trap, Value::Obj(h), &[Value::Obj(t), this, Value::Obj(arr)])
}

pub fn proxy_construct(vm: &mut Vm, p: &Obj, args: &[Value], nt: Value) -> JsResult<Value> {
    let (t, h, trap) = parts(vm, p, "construct")?;
    let trap = match trap {
        None => return vm.construct(&Value::Obj(t), args, Some(&nt)),
        Some(f) => f,
    };
    let arr = vm.new_array(args.to_vec());
    let r = vm.call(&trap, Value::Obj(h), &[Value::Obj(t), Value::Obj(arr), nt])?;
    if !r.is_object() {
        return vm.throw_type("proxy construct trap returned a non-object");
    }
    Ok(r)
}

// ---------------- Reflect ----------------

fn target_obj(vm: &mut Vm, v: &Value, name: &str) -> JsResult<Obj> {
    match v {
        Value::Obj(o) => Ok(o.clone()),
        // (the reference engine words two of these differently)
        _ if name == "defineProperty" || name == "getOwnPropertyDescriptor" => vm.throw_type(format!("Reflect.{} on non-object", name)),
        _ => vm.throw_type(format!("Reflect.{} called on non-object", name)),
    }
}

fn reflect_apply(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.arg(0);
    if !f.is_callable() {
        return vm.throw_type("Reflect.apply target is not callable");
    }
    let list = a.arg(2);
    if !list.is_object() {
        return vm.throw_type("CreateListFromArrayLike called on a non-object");
    }
    let args = crate::builtins::array::array_like_to_vec(vm, &list)?;
    vm.call(&f, a.arg(1), &args)
}

fn reflect_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.arg(0);
    if !matches!(&f, Value::Obj(o) if o.is_constructor()) {
        return vm.throw_type("Reflect.construct target is not a constructor");
    }
    let nt = if a.args.len() > 2 { a.arg(2) } else { f.clone() };
    if !matches!(&nt, Value::Obj(o) if o.is_constructor()) {
        return vm.throw_type("Reflect.construct newTarget is not a constructor");
    }
    let list = a.arg(1);
    if !list.is_object() {
        return vm.throw_type("CreateListFromArrayLike called on a non-object");
    }
    let args = crate::builtins::array::array_like_to_vec(vm, &list)?;
    vm.construct(&f, &args, Some(&nt))
}

fn reflect_define_property(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = target_obj(vm, &a.arg(0), "defineProperty")?;
    let k = vm.to_property_key(&a.arg(1))?;
    let d = to_property_descriptor(vm, &a.arg(2))?;
    Ok(Value::Bool(vm.define_own_property(&o, k, d)?))
}

fn reflect_delete_property(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    // (the key is converted before the target is checked, like the reference engine)
    let k = vm.to_property_key(&a.arg(1))?;
    let o = target_obj(vm, &a.arg(0), "deleteProperty")?;
    Ok(Value::Bool(vm.delete(&o, &k)?))
}

fn reflect_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = target_obj(vm, &a.arg(0), "get")?;
    let k = vm.to_property_key(&a.arg(1))?;
    let recv = if a.args.len() > 2 { a.arg(2) } else { Value::Obj(o.clone()) };
    vm.get(&o, &k, &recv)
}

fn reflect_get_own_property_descriptor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = target_obj(vm, &a.arg(0), "getOwnPropertyDescriptor")?;
    let k = vm.to_property_key(&a.arg(1))?;
    match vm.get_own_property(&o, &k)? {
        Some(d) => Ok(from_property_descriptor(vm, &d)),
        None => Ok(Value::Undefined),
    }
}

fn reflect_get_prototype_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = target_obj(vm, &a.arg(0), "getPrototypeOf")?;
    Ok(vm.get_prototype_of(&o)?.map(Value::Obj).unwrap_or(Value::Null))
}

fn reflect_has(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = target_obj(vm, &a.arg(0), "has")?;
    let k = vm.to_property_key(&a.arg(1))?;
    Ok(Value::Bool(vm.has_property(&o, &k)?))
}

fn reflect_is_extensible(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = target_obj(vm, &a.arg(0), "isExtensible")?;
    Ok(Value::Bool(vm.is_extensible(&o)?))
}

fn reflect_own_keys(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = target_obj(vm, &a.arg(0), "ownKeys")?;
    let keys = vm.own_property_keys(&o)?;
    let v: Vec<Value> = keys.iter().map(key_val).collect();
    Ok(Value::Obj(vm.new_array(v)))
}

fn reflect_prevent_extensions(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = target_obj(vm, &a.arg(0), "preventExtensions")?;
    Ok(Value::Bool(vm.prevent_extensions(&o)?))
}

fn reflect_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = target_obj(vm, &a.arg(0), "set")?;
    let k = vm.to_property_key(&a.arg(1))?;
    let recv = if a.args.len() > 3 { a.arg(3) } else { Value::Obj(o.clone()) };
    Ok(Value::Bool(vm.set(&o, k, a.arg(2), &recv)?))
}

fn reflect_set_prototype_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = target_obj(vm, &a.arg(0), "setPrototypeOf")?;
    let p = match a.arg(1) {
        Value::Obj(p) => Some(p),
        Value::Null => None,
        _ => return vm.throw_type("prototype must be an object or null"),
    };
    Ok(Value::Bool(vm.set_prototype_of(&o, p)?))
}
