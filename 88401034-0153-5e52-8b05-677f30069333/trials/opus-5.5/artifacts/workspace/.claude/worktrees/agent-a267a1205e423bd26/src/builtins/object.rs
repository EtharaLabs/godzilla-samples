// Object constructor and Object.prototype.

use crate::object::*;
use crate::realm::this_obj;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let proto = vm.intr.object_proto.clone();
    let ctor = vm.native_ctor("Object", 1, object_ctor, &proto);
    vm.intr.object_ctor = ctor.clone();
    vm.def_method(&ctor, "assign", 2, assign);
    vm.def_method(&ctor, "create", 2, create);
    vm.def_method(&ctor, "defineProperties", 2, define_properties);
    vm.def_method(&ctor, "defineProperty", 3, define_property);
    vm.def_method(&ctor, "entries", 1, entries);
    vm.def_method(&ctor, "freeze", 1, freeze);
    vm.def_method(&ctor, "fromEntries", 1, from_entries);
    vm.def_method(&ctor, "getOwnPropertyDescriptor", 2, get_own_property_descriptor);
    vm.def_method(&ctor, "getOwnPropertyDescriptors", 1, get_own_property_descriptors);
    vm.def_method(&ctor, "getOwnPropertyNames", 1, get_own_property_names);
    vm.def_method(&ctor, "getOwnPropertySymbols", 1, get_own_property_symbols);
    vm.def_method(&ctor, "getPrototypeOf", 1, get_prototype_of);
    vm.def_method(&ctor, "groupBy", 2, group_by);
    vm.def_method(&ctor, "hasOwn", 2, has_own);
    vm.def_method(&ctor, "is", 2, is);
    vm.def_method(&ctor, "isExtensible", 1, is_extensible);
    vm.def_method(&ctor, "isFrozen", 1, is_frozen);
    vm.def_method(&ctor, "isSealed", 1, is_sealed);
    vm.def_method(&ctor, "keys", 1, keys);
    vm.def_method(&ctor, "preventExtensions", 1, prevent_extensions);
    vm.def_method(&ctor, "seal", 1, seal);
    vm.def_method(&ctor, "setPrototypeOf", 2, set_prototype_of);
    vm.def_method(&ctor, "values", 1, values);

    vm.def_method(&proto, "__defineGetter__", 2, define_getter);
    vm.def_method(&proto, "__defineSetter__", 2, define_setter);
    vm.def_method(&proto, "hasOwnProperty", 1, has_own_property);
    vm.def_method(&proto, "__lookupGetter__", 1, lookup_getter);
    vm.def_method(&proto, "__lookupSetter__", 1, lookup_setter);
    vm.def_method(&proto, "isPrototypeOf", 1, is_prototype_of);
    vm.def_method(&proto, "propertyIsEnumerable", 1, property_is_enumerable);
    vm.def_method(&proto, "toString", 0, to_string);
    vm.def_method(&proto, "valueOf", 0, value_of);
    vm.def_method(&proto, "toLocaleString", 0, to_locale_string);
    vm.def_accessor(&proto, "__proto__", proto_getter, proto_setter);
    vm.def_global("Object", Value::Obj(ctor));
}

fn object_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let Some(nt) = &a.new_target {
        if !nt.ptr_eq(a.callee) {
            let p = vm.proto_from_nt(&a.new_target, &vm.intr.object_proto.clone())?;
            return Ok(Value::Obj(Obj::new(Some(p), ObjKind::Ordinary)));
        }
    }
    let v = a.arg(0);
    if v.is_nullish() {
        return Ok(Value::Obj(vm.new_object()));
    }
    Ok(Value::Obj(vm.to_object(&v)?))
}

fn to_obj_named(vm: &mut Vm, v: &Value, name: &str) -> JsResult<Obj> {
    match v {
        Value::Obj(o) => Ok(o.clone()),
        Value::Undefined | Value::Null => vm.throw_type(format!("{} called on null or undefined", name)),
        other => vm.to_object(other),
    }
}

fn assign(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let target = to_obj_named(vm, &a.arg(0), "Object.assign")?;
    for src in a.args.iter().skip(1) {
        if src.is_nullish() {
            continue;
        }
        let from = vm.to_object(src)?;
        let keys = vm.own_property_keys(&from)?;
        for k in keys {
            if let Some(d) = vm.get_own_property(&from, &k)? {
                if d.enumerable == Some(true) {
                    let v = vm.get(&from, &k, &Value::Obj(from.clone()))?;
                    let tv = Value::Obj(target.clone());
                    vm.set_prop_of(&tv, k, v, true)?;
                }
            }
        }
    }
    Ok(Value::Obj(target))
}

fn create(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let proto = match a.arg(0) {
        Value::Obj(o) => Some(o),
        Value::Null => None,
        _ => return vm.throw_type("Object.create proto must be object or null"),
    };
    let o = Obj::new(proto, ObjKind::Ordinary);
    let props = a.arg(1);
    if !props.is_undefined() {
        object_define_properties(vm, &o, &props)?;
    }
    Ok(Value::Obj(o))
}

pub fn to_property_descriptor(vm: &mut Vm, v: &Value) -> JsResult<PropDesc> {
    let o = match v {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("Property description must be an object"),
    };
    let mut d = PropDesc::default();
    let has = |vm: &mut Vm, k: &str| vm.has_property(&o, &PropKey::from_str(k));
    if has(vm, "enumerable")? {
        d.enumerable = Some(vm.get_str(&o, "enumerable")?.truthy());
    }
    if has(vm, "configurable")? {
        d.configurable = Some(vm.get_str(&o, "configurable")?.truthy());
    }
    if has(vm, "value")? {
        d.value = Some(vm.get_str(&o, "value")?);
    }
    if has(vm, "writable")? {
        d.writable = Some(vm.get_str(&o, "writable")?.truthy());
    }
    if has(vm, "get")? {
        let g = vm.get_str(&o, "get")?;
        if !g.is_undefined() && !g.is_callable() {
            return vm.throw_type("Getter must be a function");
        }
        d.get = Some(g);
    }
    if has(vm, "set")? {
        let s = vm.get_str(&o, "set")?;
        if !s.is_undefined() && !s.is_callable() {
            return vm.throw_type("Setter must be a function");
        }
        d.set = Some(s);
    }
    if (d.get.is_some() || d.set.is_some()) && (d.value.is_some() || d.writable.is_some()) {
        return vm.throw_type("Invalid property descriptor. Cannot both specify accessors and a value or writable attribute");
    }
    Ok(d)
}

pub fn from_property_descriptor(vm: &mut Vm, d: &PropDesc) -> Value {
    let o = vm.new_object();
    if let Some(v) = &d.value {
        o.set_str("value", v.clone(), WEC);
    }
    if let Some(w) = d.writable {
        o.set_str("writable", Value::Bool(w), WEC);
    }
    if let Some(g) = &d.get {
        o.set_str("get", g.clone(), WEC);
    }
    if let Some(s) = &d.set {
        o.set_str("set", s.clone(), WEC);
    }
    if let Some(e) = d.enumerable {
        o.set_str("enumerable", Value::Bool(e), WEC);
    }
    if let Some(c) = d.configurable {
        o.set_str("configurable", Value::Bool(c), WEC);
    }
    Value::Obj(o)
}

fn object_define_properties(vm: &mut Vm, o: &Obj, props: &Value) -> JsResult<()> {
    let p = vm.to_object(props)?;
    let keys = vm.own_property_keys(&p)?;
    let mut descs = Vec::new();
    for k in keys {
        if let Some(pd) = vm.get_own_property(&p, &k)? {
            if pd.enumerable == Some(true) {
                let dv = vm.get(&p, &k, &Value::Obj(p.clone()))?;
                let d = to_property_descriptor(vm, &dv)?;
                descs.push((k, d));
            }
        }
    }
    for (k, d) in descs {
        if !vm.define_own_property(o, k.clone(), d)? {
            return vm.throw_type("Cannot redefine property");
        }
    }
    Ok(())
}

fn define_properties(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match a.arg(0) {
        Value::Obj(o) => o,
        _ => return vm.throw_type("Object.defineProperties called on non-object"),
    };
    object_define_properties(vm, &o, &a.arg(1))?;
    Ok(Value::Obj(o))
}

fn define_property(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match a.arg(0) {
        Value::Obj(o) => o,
        _ => return vm.throw_type("Object.defineProperty called on non-object"),
    };
    let k = vm.to_property_key(&a.arg(1))?;
    let d = to_property_descriptor(vm, &a.arg(2))?;
    if !vm.define_own_property(&o, k.clone(), d)? {
        return vm.throw_type("Cannot redefine property");
    }
    Ok(Value::Obj(o))
}

fn entries_impl(vm: &mut Vm, a: &Args, name: &str, kind: u8) -> JsResult<Value> {
    let o = to_obj_named(vm, &a.arg(0), name)?;
    let keys = vm.own_property_keys(&o)?;
    let mut out = Vec::new();
    for k in keys {
        if let PropKey::Str(s) = &k {
            let d = vm.get_own_property(&o, &k)?;
            if let Some(d) = d {
                if d.enumerable == Some(true) {
                    match kind {
                        0 => out.push(Value::Str(s.clone())),
                        1 => out.push(vm.get(&o, &k, &Value::Obj(o.clone()))?),
                        _ => {
                            let v = vm.get(&o, &k, &Value::Obj(o.clone()))?;
                            let pair = vm.new_array(vec![Value::Str(s.clone()), v]);
                            out.push(Value::Obj(pair));
                        }
                    }
                }
            }
        }
    }
    Ok(Value::Obj(vm.new_array(out)))
}

fn keys(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    // fast path for ordinary objects
    if let Value::Obj(o) = &a.arg(0) {
        if !o.is_proxy() {
            let ks = vm.enumerable_own_keys(o)?;
            return Ok(Value::Obj(vm.new_array(ks.into_iter().map(Value::Str).collect())));
        }
    }
    entries_impl(vm, a, "Object.keys", 0)
}
fn values(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    entries_impl(vm, a, "Object.values", 1)
}
fn entries(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    entries_impl(vm, a, "Object.entries", 2)
}

pub fn freeze_obj(vm: &mut Vm, o: &Obj) {
    let _ = set_integrity(vm, o, true);
}

fn set_integrity(vm: &mut Vm, o: &Obj, frozen: bool) -> JsResult<bool> {
    if !vm.prevent_extensions(o)? {
        return Ok(false);
    }
    // arrays: convert to sparse so element attributes can change
    let is_dense_array = matches!(&o.borrow().kind, ObjKind::Array(a) if !a.sparse);
    let keys = vm.own_property_keys(o)?;
    if is_dense_array && !keys.is_empty() {
        // define each element through the array path (forces sparse mode)
    }
    for k in keys {
        let d = if frozen {
            match vm.get_own_property(o, &k)? {
                Some(cur) => {
                    if cur.is_accessor() {
                        PropDesc { configurable: Some(false), ..Default::default() }
                    } else {
                        PropDesc { configurable: Some(false), writable: Some(false), ..Default::default() }
                    }
                }
                None => continue,
            }
        } else {
            PropDesc { configurable: Some(false), ..Default::default() }
        };
        if !vm.define_own_property(o, k.clone(), d)? {
            return vm.throw_type(format!("Cannot redefine property: {}", k.to_display()));
        }
    }
    Ok(true)
}

fn test_integrity(vm: &mut Vm, o: &Obj, frozen: bool) -> JsResult<bool> {
    if vm.is_extensible(o)? {
        return Ok(false);
    }
    let keys = vm.own_property_keys(o)?;
    for k in keys {
        if let Some(d) = vm.get_own_property(o, &k)? {
            if d.configurable == Some(true) {
                return Ok(false);
            }
            if frozen && d.is_data() && d.writable == Some(true) {
                return Ok(false);
            }
        }
    }
    Ok(true)
}

fn freeze(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = a.arg(0);
    if let Value::Obj(o) = &v {
        if matches!(&o.borrow().kind, ObjKind::TypedArray(t) if t.len() > 0) {
            return vm.throw_type("Cannot freeze array buffer views with elements");
        }
        if !set_integrity(vm, o, true)? {
            return vm.throw_type("cannot prevent extensions");
        }
    }
    Ok(v)
}

fn seal(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = a.arg(0);
    if let Value::Obj(o) = &v {
        if !set_integrity(vm, o, false)? {
            return vm.throw_type("cannot prevent extensions");
        }
    }
    Ok(v)
}

fn prevent_extensions(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = a.arg(0);
    if let Value::Obj(o) = &v {
        if !vm.prevent_extensions(o)? {
            return vm.throw_type("cannot prevent extensions");
        }
    }
    Ok(v)
}

fn is_frozen(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match a.arg(0) {
        Value::Obj(o) => Ok(Value::Bool(test_integrity(vm, &o, true)?)),
        _ => Ok(Value::Bool(true)),
    }
}
fn is_sealed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match a.arg(0) {
        Value::Obj(o) => Ok(Value::Bool(test_integrity(vm, &o, false)?)),
        _ => Ok(Value::Bool(true)),
    }
}
fn is_extensible(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match a.arg(0) {
        Value::Obj(o) => Ok(Value::Bool(vm.is_extensible(&o)?)),
        _ => Ok(Value::Bool(false)),
    }
}

fn from_entries(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let it = a.arg(0);
    if it.is_nullish() {
        return vm.throw_type("value is not iterable");
    }
    let o = vm.new_object();
    let (iter, next) = vm.get_iterator(&it)?;
    let itv = Value::Obj(iter);
    loop {
        let item = match vm.iter_step(&itv, &next)? {
            Some(v) => v,
            None => break,
        };
        let r: JsResult<()> = (|| {
            let io = match &item {
                Value::Obj(io) => io.clone(),
                _ => return vm.throw_type("Object.fromEntries entry is not an object"),
            };
            let k = vm.get(&io, &PropKey::from_index(0), &item)?;
            let v = vm.get(&io, &PropKey::from_index(1), &item)?;
            let pk = vm.to_property_key(&k)?;
            vm.create_data_property(&o, pk, v)?;
            Ok(())
        })();
        if let Err(e) = r {
            let _ = vm.iterator_close(&itv);
            return Err(e);
        }
    }
    Ok(Value::Obj(o))
}

fn get_own_property_descriptor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = to_obj_named(vm, &a.arg(0), "Object.getOwnPropertyDescriptor")?;
    let k = vm.to_property_key(&a.arg(1))?;
    match vm.get_own_property(&o, &k)? {
        Some(d) => Ok(from_property_descriptor(vm, &d)),
        None => Ok(Value::Undefined),
    }
}

fn get_own_property_descriptors(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = to_obj_named(vm, &a.arg(0), "Object.getOwnPropertyDescriptors")?;
    let out = vm.new_object();
    let keys = vm.own_property_keys(&o)?;
    for k in keys {
        if let Some(d) = vm.get_own_property(&o, &k)? {
            let dv = from_property_descriptor(vm, &d);
            vm.create_data_property(&out, k, dv)?;
        }
    }
    Ok(Value::Obj(out))
}

fn get_own_property_names(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = to_obj_named(vm, &a.arg(0), "Object.getOwnPropertyNames")?;
    let keys = vm.own_property_keys(&o)?;
    let v: Vec<Value> = keys.into_iter().filter_map(|k| if let PropKey::Str(s) = k { Some(Value::Str(s)) } else { None }).collect();
    Ok(Value::Obj(vm.new_array(v)))
}

fn get_own_property_symbols(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = to_obj_named(vm, &a.arg(0), "Object.getOwnPropertySymbols")?;
    let keys = vm.own_property_keys(&o)?;
    let v: Vec<Value> = keys.into_iter().filter_map(|k| if let PropKey::Sym(s) = k { Some(Value::Sym(s)) } else { None }).collect();
    Ok(Value::Obj(vm.new_array(v)))
}

fn get_prototype_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match a.arg(0) {
        Value::Obj(o) => o,
        Value::Undefined | Value::Null => return vm.throw_type("called on null or undefined"),
        other => vm.to_object(&other)?,
    };
    Ok(vm.get_prototype_of(&o)?.map(Value::Obj).unwrap_or(Value::Null))
}

fn set_prototype_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = a.arg(0);
    if v.is_nullish() {
        return vm.throw_type("Object.setPrototypeOf called on null or undefined");
    }
    let p = match a.arg(1) {
        Value::Obj(o) => Some(o),
        Value::Null => None,
        _ => return vm.throw_type("Object prototype may only be an Object or null"),
    };
    if let Value::Obj(o) = &v {
        if !vm.set_prototype_of(o, p)? {
            return vm.throw_type("could not set prototype");
        }
    }
    Ok(v)
}

fn group_by(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let items = a.arg(0);
    let cb = a.arg(1);
    if !cb.is_callable() {
        return vm.throw_type("callback is not a function");
    }
    let out = Obj::new(None, ObjKind::Ordinary);
    let mut groups: Vec<(PropKey, Vec<Value>)> = Vec::new();
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
        let pk = vm.to_property_key(&key)?;
        match groups.iter_mut().find(|(g, _)| *g == pk) {
            Some((_, list)) => list.push(v),
            None => groups.push((pk, vec![v])),
        }
        k += 1;
    }
    for (g, list) in groups {
        let arr = vm.new_array(list);
        out.set_prop(g, Value::Obj(arr), WEC);
    }
    Ok(Value::Obj(out))
}

fn has_own(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = to_obj_named(vm, &a.arg(0), "Object.hasOwn")?;
    let k = vm.to_property_key(&a.arg(1))?;
    Ok(Value::Bool(vm.has_own_property(&o, &k)?))
}

fn is(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(Value::same_value(&a.arg(0), &a.arg(1))))
}

fn has_own_property(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let k = vm.to_property_key(&a.arg(0))?;
    let o = match &a.this {
        Value::Undefined | Value::Null => return vm.throw_type("Object.prototype.hasOwnProperty called on null or undefined"),
        v => vm.to_object(v)?,
    };
    Ok(Value::Bool(vm.has_own_property(&o, &k)?))
}

fn is_prototype_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = match a.arg(0) {
        Value::Obj(o) => o,
        _ => return Ok(Value::Bool(false)),
    };
    let o = this_obj(vm, a, "Object.prototype.isPrototypeOf")?;
    let mut cur = vm.get_prototype_of(&v)?;
    while let Some(p) = cur {
        if p.ptr_eq(&o) {
            return Ok(Value::Bool(true));
        }
        cur = vm.get_prototype_of(&p)?;
    }
    Ok(Value::Bool(false))
}

fn property_is_enumerable(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let k = vm.to_property_key(&a.arg(0))?;
    let o = this_obj(vm, a, "Object.prototype.propertyIsEnumerable")?;
    Ok(Value::Bool(matches!(vm.get_own_property(&o, &k)?, Some(d) if d.enumerable == Some(true))))
}

pub fn builtin_tag(vm: &mut Vm, o: &Obj) -> JsResult<&'static str> {
    if crate::builtins::array::is_array(vm, &Value::Obj(o.clone()))? {
        return Ok("Array");
    }
    let b = o.borrow();
    Ok(match &b.kind {
        ObjKind::Arguments(_) => "Arguments",
        ObjKind::Closure(_) | ObjKind::Native(_) | ObjKind::Bound(_) => "Function",
        ObjKind::Proxy(p) if p.callable => "Function",
        ObjKind::Error => "Error",
        ObjKind::Boolean(_) => "Boolean",
        ObjKind::Number(_) => "Number",
        ObjKind::String(_) => "String",
        ObjKind::Date(_) => "Date",
        ObjKind::RegExp(_) => "RegExp",
        _ => "Object",
    })
}

fn to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match &a.this {
        Value::Undefined => return Ok(Value::str("[object Undefined]")),
        Value::Null => return Ok(Value::str("[object Null]")),
        v => vm.to_object(v)?,
    };
    let builtin = builtin_tag(vm, &o)?;
    let tag = vm.get(&o, &PropKey::Sym(vm.intr.sym_to_string_tag.clone()), &Value::Obj(o.clone()))?;
    let t = match tag {
        Value::Str(s) => s.to_rust_string(),
        _ => builtin.to_string(),
    };
    Ok(Value::str(&format!("[object {}]", t)))
}

fn value_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_obj(vm, a, "Object.prototype.valueOf")?;
    Ok(Value::Obj(o))
}

fn to_locale_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = vm.get_prop_of(&a.this, &vm.intr.key_to_string.clone())?;
    vm.call(&f, a.this.clone(), &[])
}

fn proto_getter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_obj(vm, a, "Object.prototype.__proto__")?;
    Ok(vm.get_prototype_of(&o)?.map(Value::Obj).unwrap_or(Value::Null))
}

fn proto_setter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.this.is_nullish() {
        return vm.throw_type("Object.prototype.__proto__ called on null or undefined");
    }
    let p = match a.arg(0) {
        Value::Obj(o) => Some(o),
        Value::Null => None,
        _ => return Ok(Value::Undefined),
    };
    if let Value::Obj(o) = &a.this {
        if !vm.set_prototype_of(o, p)? {
            return vm.throw_type("could not set prototype");
        }
    }
    Ok(Value::Undefined)
}

fn define_getter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_obj(vm, a, "__defineGetter__")?;
    let g = a.arg(1);
    if !g.is_callable() {
        return vm.throw_type("Object.prototype.__defineGetter__: Expecting function");
    }
    let k = vm.to_property_key(&a.arg(0))?;
    let d = PropDesc { get: Some(g), enumerable: Some(true), configurable: Some(true), ..Default::default() };
    vm.define_property_or_throw(&o, k, d)?;
    Ok(Value::Undefined)
}

fn define_setter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_obj(vm, a, "__defineSetter__")?;
    let s = a.arg(1);
    if !s.is_callable() {
        return vm.throw_type("Object.prototype.__defineSetter__: Expecting function");
    }
    let k = vm.to_property_key(&a.arg(0))?;
    let d = PropDesc { set: Some(s), enumerable: Some(true), configurable: Some(true), ..Default::default() };
    vm.define_property_or_throw(&o, k, d)?;
    Ok(Value::Undefined)
}

fn lookup_accessor(vm: &mut Vm, a: &Args, getter: bool) -> JsResult<Value> {
    let o = this_obj(vm, a, "__lookupGetter__")?;
    let k = vm.to_property_key(&a.arg(0))?;
    let mut cur = Some(o);
    while let Some(c) = cur {
        if let Some(d) = vm.get_own_property(&c, &k)? {
            if d.is_accessor() {
                return Ok(if getter { d.get.unwrap_or(Value::Undefined) } else { d.set.unwrap_or(Value::Undefined) });
            }
            return Ok(Value::Undefined);
        }
        cur = vm.get_prototype_of(&c)?;
    }
    Ok(Value::Undefined)
}
fn lookup_getter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    lookup_accessor(vm, a, true)
}
fn lookup_setter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    lookup_accessor(vm, a, false)
}
