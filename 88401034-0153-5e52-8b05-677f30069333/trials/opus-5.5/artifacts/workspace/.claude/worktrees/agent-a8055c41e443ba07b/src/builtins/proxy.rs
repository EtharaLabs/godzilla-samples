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
        _ => return vm.throw_type(format!("Cannot perform '{}' on a proxy that has been revoked", trap)),
    };
    let tr = vm.get(&h, &PropKey::from_str(trap), &Value::Obj(h.clone()))?;
    if tr.is_nullish() {
        return Ok((t, h, None));
    }
    if !tr.is_callable() {
        return vm.throw_type(format!("{} is not a function", trap));
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
        _ => return vm.throw_type("'getPrototypeOf' on proxy: trap returned neither object nor null"),
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
        return vm.throw_type("'getPrototypeOf' on proxy: proxy target is non-extensible but the trap did not return its actual prototype");
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
        return vm.throw_type("'setPrototypeOf' on proxy: trap returned truish for setting a new prototype on the non-extensible proxy target");
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
        return vm.throw_type("'isExtensible' on proxy: trap result does not reflect extensibility of proxy target");
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
        return vm.throw_type("'preventExtensions' on proxy: trap returned truish but the proxy target is extensible");
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
        return vm.throw_type("'getOwnPropertyDescriptor' on proxy: trap returned neither object nor undefined");
    }
    let target_desc = vm.get_own_property(&t, k)?;
    if r.is_undefined() {
        if let Some(td) = &target_desc {
            if td.configurable == Some(false) {
                return vm.throw_type(format!("'getOwnPropertyDescriptor' on proxy: trap returned undefined for property '{}' which is non-configurable in the proxy target", k.to_display()));
            }
            if !vm.is_extensible(&t)? {
                return vm.throw_type(format!("'getOwnPropertyDescriptor' on proxy: trap returned undefined for property '{}' which exists in the non-extensible proxy target", k.to_display()));
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
    if !crate::props::validate_and_apply(None, k, ext, &d, cur) {
        return vm.throw_type(format!("'getOwnPropertyDescriptor' on proxy: trap returned descriptor for property '{}' that is incompatible with the existing property in the proxy target", k.to_display()));
    }
    if d.configurable == Some(false) {
        match &target_desc {
            None => {
                return vm.throw_type(format!("'getOwnPropertyDescriptor' on proxy: trap reported non-configurability for property '{}' which is either non-existent or configurable in the proxy target", k.to_display()))
            }
            Some(td) => {
                if td.configurable == Some(true) {
                    return vm.throw_type(format!("'getOwnPropertyDescriptor' on proxy: trap reported non-configurability for property '{}' which is either non-existent or configurable in the proxy target", k.to_display()));
                }
                if d.writable == Some(false) && td.writable == Some(true) {
                    return vm.throw_type(format!("'getOwnPropertyDescriptor' on proxy: trap reported non-configurable and writable for property '{}' which is non-configurable, non-writable in the proxy target", k.to_display()));
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
                return vm.throw_type(format!("'defineProperty' on proxy: trap returned truish for adding property '{}'  to the non-extensible proxy target", k.to_display()));
            }
            if setting_nc {
                return vm.throw_type(format!("'defineProperty' on proxy: trap returned truish for defining non-configurable property '{}' which is either non-existent or configurable in the proxy target", k.to_display()));
            }
        }
        Some(td) => {
            if !crate::props::validate_and_apply(None, &k, ext, &d, Some(desc_to_prop(td))) {
                return vm.throw_type(format!("'defineProperty' on proxy: trap returned truish for adding property '{}'  that is incompatible with the existing property in the proxy target", k.to_display()));
            }
            if setting_nc && td.configurable == Some(true) {
                return vm.throw_type(format!("'defineProperty' on proxy: trap returned truish for defining non-configurable property '{}' which is either non-existent or configurable in the proxy target", k.to_display()));
            }
            if td.is_data() && td.configurable == Some(false) && td.writable == Some(true) && d.writable == Some(false) {
                return vm.throw_type(format!("'defineProperty' on proxy: trap returned truish for defining non-configurable property '{}' which cannot be non-writable, unless there exists a corresponding non-configurable, non-writable own property of the target object.", k.to_display()));
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
                return vm.throw_type(format!("'has' on proxy: trap returned falsish for property '{}' which exists in the proxy target as non-configurable", k.to_display()));
            }
            if !vm.is_extensible(&t)? {
                return vm.throw_type(format!("'has' on proxy: trap returned falsish for property '{}' but the proxy target is not extensible", k.to_display()));
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
                return vm.throw_type(format!("'get' on proxy: property '{}' is a read-only and non-configurable data property on the proxy target but the proxy did not return its actual value", k.to_display()));
            }
            if td.is_accessor() && matches!(td.get, Some(Value::Undefined) | None) && !v.is_undefined() {
                return vm.throw_type(format!("'get' on proxy: property '{}' is a non-configurable accessor property on the proxy target and does not have a getter function, but the trap did not return 'undefined'", k.to_display()));
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
                return vm.throw_type(format!("'set' on proxy: trap returned truish for property '{}' which exists in the proxy target as a non-configurable and non-writable data property with a different value", k.to_display()));
            }
            if td.is_accessor() && matches!(td.set, Some(Value::Undefined) | None) {
                return vm.throw_type(format!("'set' on proxy: trap returned truish for property '{}' which exists in the proxy target as a non-configurable and non-writable accessor property without a setter", k.to_display()));
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
            return vm.throw_type(format!("'deleteProperty' on proxy: trap returned truish for property '{}' which is non-configurable in the proxy target", k.to_display()));
        }
        if !vm.is_extensible(&t)? {
            return vm.throw_type(format!("'deleteProperty' on proxy: trap returned truish for property '{}' but the proxy target is non-extensible", k.to_display()));
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
        _ => return vm.throw_type("CreateListFromArrayLike called on non-object"),
    };
    let len = vm.length_of(&ro)?;
    let mut keys: Vec<PropKey> = Vec::new();
    for i in 0..len {
        let v = vm.get(&ro, &PropKey::from_index(i as u32), &r)?;
        let k = match v {
            Value::Str(s) => PropKey::Str(s),
            Value::Sym(s) => PropKey::Sym(s),
            _ => return vm.throw_type(format!("{} is not a valid property name", vm.describe_for_call(&v))),
        };
        if keys.contains(&k) {
            return vm.throw_type(format!("'ownKeys' on proxy: trap returned duplicate entries"));
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
            None => return vm.throw_type(format!("'ownKeys' on proxy: trap result did not include '{}'", k.to_display())),
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
            None => return vm.throw_type(format!("'ownKeys' on proxy: trap result did not include '{}'", k.to_display())),
        }
    }
    if !unchecked.is_empty() {
        return vm.throw_type("'ownKeys' on proxy: trap returned extra keys but proxy target is non-extensible");
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
        return vm.throw_type("proxy [[Construct]] must return an object");
    }
    Ok(r)
}

// ---------------- Reflect ----------------

fn target_obj(vm: &mut Vm, v: &Value, name: &str) -> JsResult<Obj> {
    match v {
        Value::Obj(o) => Ok(o.clone()),
        _ => vm.throw_type(format!("Reflect.{} called on non-object", name)),
    }
}

fn reflect_apply(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.arg(0);
    if !f.is_callable() {
        return vm.throw_type(format!("{} is not a function", vm.describe_for_call(&f)));
    }
    let list = a.arg(2);
    if !list.is_object() {
        return vm.throw_type("CreateListFromArrayLike called on non-object");
    }
    let args = crate::builtins::array::array_like_to_vec(vm, &list)?;
    vm.call(&f, a.arg(1), &args)
}

fn reflect_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.arg(0);
    if !matches!(&f, Value::Obj(o) if o.is_constructor()) {
        return vm.throw_type(format!("{} is not a constructor", vm.describe_for_call(&f)));
    }
    let nt = if a.args.len() > 2 { a.arg(2) } else { f.clone() };
    if !matches!(&nt, Value::Obj(o) if o.is_constructor()) {
        return vm.throw_type(format!("{} is not a constructor", vm.describe_for_call(&nt)));
    }
    let list = a.arg(1);
    if !list.is_object() {
        return vm.throw_type("CreateListFromArrayLike called on non-object");
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
    let o = target_obj(vm, &a.arg(0), "deleteProperty")?;
    let k = vm.to_property_key(&a.arg(1))?;
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
        _ => return vm.throw_type("Object prototype may only be an Object or null"),
    };
    Ok(Value::Bool(vm.set_prototype_of(&o, p)?))
}
