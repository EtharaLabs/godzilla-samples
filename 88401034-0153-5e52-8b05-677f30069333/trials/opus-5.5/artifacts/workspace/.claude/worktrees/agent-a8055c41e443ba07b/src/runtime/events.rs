// node:events EventEmitter (state kept in JS-visible `_events`, like Node).

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn create_module(vm: &mut Vm) -> Value {
    let proto = vm.new_object();
    let ctor = vm.native_ctor("EventEmitter", 0, ee_ctor, &proto);
    install_methods(vm, &proto);
    ctor.set_prop(PropKey::from_str("EventEmitter"), Value::Obj(ctor.clone()), WC);
    ctor.set_prop(PropKey::from_str("defaultMaxListeners"), Value::Num(10.0), WEC);
    let em = Sym::new(Some(JsStr::from_str("events.errorMonitor")));
    ctor.set_prop(PropKey::from_str("errorMonitor"), Value::Sym(em), WEC);
    let cr = Sym::new(Some(JsStr::from_str("nodejs.rejection")));
    ctor.set_prop(PropKey::from_str("captureRejectionSymbol"), Value::Sym(cr), WEC);
    ctor.set_prop(PropKey::from_str("captureRejections"), Value::Bool(false), WEC);
    vm.def_method(&ctor, "once", 2, static_once);
    vm.def_method(&ctor, "on", 2, static_on);
    vm.def_method(&ctor, "listenerCount", 2, static_listener_count);
    vm.def_method(&ctor, "getEventListeners", 2, static_get_event_listeners);
    vm.def_method(&ctor, "setMaxListeners", 1, |_vm, _a| Ok(Value::Undefined));
    vm.def_method(&ctor, "init", 0, ee_init);
    Value::Obj(ctor)
}

pub fn install_methods(vm: &mut Vm, proto: &Obj) {
    let methods: &[(&str, u32, NativeFn)] = &[
        ("setMaxListeners", 1, set_max_listeners),
        ("getMaxListeners", 0, get_max_listeners),
        ("emit", 1, emit),
        ("addListener", 2, on),
        ("on", 2, on),
        ("prependListener", 2, prepend_listener),
        ("once", 2, once),
        ("prependOnceListener", 2, prepend_once_listener),
        ("removeListener", 2, remove_listener),
        ("off", 2, remove_listener),
        ("removeAllListeners", 1, remove_all_listeners),
        ("listeners", 1, listeners),
        ("rawListeners", 1, raw_listeners),
        ("listenerCount", 1, listener_count),
        ("eventNames", 0, event_names),
    ];
    for (n, l, f) in methods {
        vm.def_method(proto, n, *l, *f);
    }
}

pub fn init_emitter(vm: &mut Vm, o: &Obj) {
    let ev = Obj::new(None, ObjKind::Ordinary);
    o.set_prop(PropKey::from_str("_events"), Value::Obj(ev), WEC);
    o.set_prop(PropKey::from_str("_eventsCount"), Value::Num(0.0), WEC);
    o.set_prop(PropKey::from_str("_maxListeners"), Value::Undefined, WEC);
    let _ = vm;
}

fn ee_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match &a.new_target {
        Some(_) => {
            let fallback = vm.get(a.callee, &vm.intr.key_prototype.clone(), &Value::Obj(a.callee.clone()))?.as_obj().cloned().unwrap();
            let p = vm.proto_from_nt(&a.new_target, &fallback)?;
            Obj::new(Some(p), ObjKind::Ordinary)
        }
        None => match &a.this {
            Value::Obj(o) => o.clone(),
            _ => return Ok(Value::Undefined),
        },
    };
    init_emitter(vm, &o);
    if a.new_target.is_none() {
        return Ok(Value::Undefined);
    }
    Ok(Value::Obj(o))
}

fn ee_init(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let Value::Obj(o) = &a.this {
        init_emitter(vm, o);
    }
    Ok(Value::Undefined)
}

fn events_obj(vm: &mut Vm, this: &Value) -> JsResult<Obj> {
    let o = match this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("EventEmitter method called on non-object"),
    };
    let ev = vm.get_str(&o, "_events")?;
    match ev {
        Value::Obj(e) => Ok(e),
        _ => {
            init_emitter(vm, &o);
            match vm.get_str(&o, "_events")? {
                Value::Obj(e) => Ok(e),
                _ => vm.throw_type("cannot initialize events"),
            }
        }
    }
}

fn get_list(vm: &mut Vm, ev: &Obj, key: &PropKey) -> JsResult<Vec<Value>> {
    let v = match ev.get_own_data(key) {
        Some(v) => v,
        None => return Ok(Vec::new()),
    };
    match &v {
        Value::Obj(o) if o.is_array() => crate::builtins::array::array_like_to_vec(vm, &v),
        Value::Undefined => Ok(Vec::new()),
        _ => Ok(vec![v]),
    }
}

fn set_list(vm: &mut Vm, this: &Value, ev: &Obj, key: &PropKey, list: Vec<Value>) {
    let had = ev.get_own_data(key).is_some();
    if list.is_empty() {
        ev.borrow_mut().props.remove(key);
        if had {
            adjust_count(vm, this, -1.0);
        }
    } else if list.len() == 1 {
        ev.set_prop(key.clone(), list[0].clone(), WEC);
        if !had {
            adjust_count(vm, this, 1.0);
        }
    } else {
        let arr = vm.new_array(list);
        ev.set_prop(key.clone(), Value::Obj(arr), WEC);
        if !had {
            adjust_count(vm, this, 1.0);
        }
    }
}

fn adjust_count(_vm: &mut Vm, this: &Value, d: f64) {
    if let Value::Obj(o) = this {
        let c = o.get_own_str("_eventsCount").and_then(|v| v.as_num()).unwrap_or(0.0);
        o.set_prop(PropKey::from_str("_eventsCount"), Value::Num((c + d).max(0.0)), WEC);
    }
}

fn check_listener(vm: &mut Vm, f: &Value) -> JsResult<()> {
    if !f.is_callable() {
        let d = crate::runtime::util::describe_received(vm, f);
        return vm.throw_type(format!("The \"listener\" argument must be of type function. Received {}", d));
    }
    Ok(())
}

pub fn add_listener(vm: &mut Vm, this: &Value, name: &Value, f: Value, prepend: bool) -> JsResult<()> {
    check_listener(vm, &f)?;
    let ev = events_obj(vm, this)?;
    // newListener event
    let nl = PropKey::from_str("newListener");
    if ev.get_own_data(&nl).is_some() {
        let real = match &f {
            Value::Obj(fo) => fo.get_own_str("listener").unwrap_or_else(|| f.clone()),
            _ => f.clone(),
        };
        emit_event(vm, this, &Value::str("newListener"), &[name.clone(), real])?;
    }
    let key = vm.to_property_key(name)?;
    let ev = events_obj(vm, this)?;
    let mut list = get_list(vm, &ev, &key)?;
    if prepend {
        list.insert(0, f);
    } else {
        list.push(f);
    }
    set_list(vm, this, &ev, &key, list);
    Ok(())
}

fn on(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    add_listener(vm, &a.this, &a.arg(0), a.arg(1), false)?;
    Ok(a.this.clone())
}

fn prepend_listener(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    add_listener(vm, &a.this, &a.arg(0), a.arg(1), true)?;
    Ok(a.this.clone())
}

fn once_wrapper(vm: &mut Vm, this: &Value, name: &Value, f: &Value) -> Value {
    let w = vm.native_closure("bound onceWrapper", 0, once_fire, vec![this.clone(), name.clone(), f.clone(), Value::Bool(false)]);
    w.set_prop(PropKey::from_str("listener"), f.clone(), WEC);
    Value::Obj(w)
}

fn once_fire(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let fired = a.slot(3).truthy();
    if fired {
        return Ok(Value::Undefined);
    }
    if let ObjKind::Native(n) = &mut a.callee.borrow_mut().kind {
        n.slots[3] = Value::Bool(true);
    }
    let target = a.slot(0);
    let name = a.slot(1);
    let f = a.slot(2);
    remove_one(vm, &target, &name, &Value::Obj(a.callee.clone()))?;
    vm.call(&f, target, a.args)
}

fn once(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.arg(1);
    check_listener(vm, &f)?;
    let w = once_wrapper(vm, &a.this, &a.arg(0), &f);
    add_listener(vm, &a.this, &a.arg(0), w, false)?;
    Ok(a.this.clone())
}

fn prepend_once_listener(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.arg(1);
    check_listener(vm, &f)?;
    let w = once_wrapper(vm, &a.this, &a.arg(0), &f);
    add_listener(vm, &a.this, &a.arg(0), w, true)?;
    Ok(a.this.clone())
}

fn matches_listener(l: &Value, f: &Value) -> bool {
    if Value::strict_eq(l, f) {
        return true;
    }
    if let Value::Obj(lo) = l {
        if let Some(inner) = lo.get_own_str("listener") {
            return Value::strict_eq(&inner, f);
        }
    }
    false
}

fn remove_one(vm: &mut Vm, this: &Value, name: &Value, f: &Value) -> JsResult<bool> {
    let ev = events_obj(vm, this)?;
    let key = vm.to_property_key(name)?;
    let mut list = get_list(vm, &ev, &key)?;
    let pos = list.iter().rposition(|l| matches_listener(l, f));
    match pos {
        Some(p) => {
            let removed = list.remove(p);
            set_list(vm, this, &ev, &key, list);
            let rl = PropKey::from_str("removeListener");
            if ev.get_own_data(&rl).is_some() {
                let real = match &removed {
                    Value::Obj(ro) => ro.get_own_str("listener").unwrap_or(removed.clone()),
                    _ => removed.clone(),
                };
                emit_event(vm, this, &Value::str("removeListener"), &[name.clone(), real])?;
            }
            Ok(true)
        }
        None => Ok(false),
    }
}

fn remove_listener(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    check_listener(vm, &a.arg(1))?;
    remove_one(vm, &a.this, &a.arg(0), &a.arg(1))?;
    Ok(a.this.clone())
}

fn remove_all_listeners(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ev = events_obj(vm, &a.this)?;
    if a.arg(0).is_undefined() {
        let keys: Vec<PropKey> = ev.borrow().props.keys().to_vec();
        for k in keys {
            ev.borrow_mut().props.remove(&k);
        }
        if let Value::Obj(o) = &a.this {
            o.set_prop(PropKey::from_str("_eventsCount"), Value::Num(0.0), WEC);
        }
    } else {
        let key = vm.to_property_key(&a.arg(0))?;
        if ev.get_own_data(&key).is_some() {
            ev.borrow_mut().props.remove(&key);
            adjust_count(vm, &a.this, -1.0);
        }
    }
    Ok(a.this.clone())
}

pub fn emit_event(vm: &mut Vm, this: &Value, name: &Value, args: &[Value]) -> JsResult<bool> {
    let ev = events_obj(vm, this)?;
    let key = vm.to_property_key(name)?;
    let list = get_list(vm, &ev, &key)?;
    if list.is_empty() {
        if key.eq_str("error") {
            let err = args.first().cloned().unwrap_or(Value::Undefined);
            if let Value::Obj(_) = &err {
                if matches!(err.as_obj().unwrap().borrow().kind, ObjKind::Error) {
                    return Err(err);
                }
            }
            let d = crate::runtime::util::inspect_value(vm, &err, 2)?;
            let e = vm.make_error("Error", &format!("Unhandled error. ({})", d));
            if let Value::Obj(eo) = &e {
                eo.set_prop(PropKey::from_str("code"), Value::str("ERR_UNHANDLED_ERROR"), WC);
                eo.set_prop(PropKey::from_str("context"), err, WC);
            }
            return Err(e);
        }
        return Ok(false);
    }
    for l in list {
        vm.call(&l, this.clone(), args)?;
    }
    Ok(true)
}

fn emit(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let rest = if a.args.len() > 1 { &a.args[1..] } else { &[][..] };
    Ok(Value::Bool(emit_event(vm, &a.this, &a.arg(0), rest)?))
}

fn listeners(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ev = events_obj(vm, &a.this)?;
    let key = vm.to_property_key(&a.arg(0))?;
    let list = get_list(vm, &ev, &key)?;
    let unwrapped: Vec<Value> = list
        .into_iter()
        .map(|l| match &l {
            Value::Obj(o) => o.get_own_str("listener").unwrap_or(l.clone()),
            _ => l,
        })
        .collect();
    Ok(Value::Obj(vm.new_array(unwrapped)))
}

fn raw_listeners(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ev = events_obj(vm, &a.this)?;
    let key = vm.to_property_key(&a.arg(0))?;
    let list = get_list(vm, &ev, &key)?;
    Ok(Value::Obj(vm.new_array(list)))
}

fn listener_count(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ev = events_obj(vm, &a.this)?;
    let key = vm.to_property_key(&a.arg(0))?;
    let list = get_list(vm, &ev, &key)?;
    let n = if a.arg(1).is_undefined() { list.len() } else { list.iter().filter(|l| matches_listener(l, &a.arg(1))).count() };
    Ok(Value::Num(n as f64))
}

fn event_names(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ev = events_obj(vm, &a.this)?;
    let keys = vm.own_property_keys(&ev)?;
    let v: Vec<Value> = keys
        .into_iter()
        .map(|k| match k {
            PropKey::Str(s) => Value::Str(s),
            PropKey::Sym(s) => Value::Sym(s),
        })
        .collect();
    Ok(Value::Obj(vm.new_array(v)))
}

fn set_max_listeners(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let n = vm.to_number(&a.arg(0))?;
    if n.is_nan() || n < 0.0 {
        return vm.throw_range(format!("The value of \"n\" is out of range. It must be a non-negative number. Received {}", crate::numconv::number_to_string(n)));
    }
    if let Value::Obj(o) = &a.this {
        o.set_prop(PropKey::from_str("_maxListeners"), Value::Num(n), WEC);
    }
    Ok(a.this.clone())
}

fn get_max_listeners(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let Value::Obj(o) = &a.this {
        let m = vm.get_str(o, "_maxListeners")?;
        if !m.is_undefined() {
            return Ok(m);
        }
    }
    Ok(Value::Num(10.0))
}

fn static_once(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let emitter = a.arg(0);
    let name = a.arg(1);
    let cap = vm.new_promise_capability_intrinsic();
    let resolver = vm.native_closure("", 0, static_once_resolve, vec![cap.resolve.clone()]);
    let w = once_wrapper(vm, &emitter, &name, &Value::Obj(resolver));
    let add = vm.get_prop_of(&emitter, &PropKey::from_str("on"))?;
    if add.is_callable() {
        vm.call(&add, emitter.clone(), &[name.clone(), w])?;
        if !name.is_object() {
            let is_error = matches!(&name, Value::Str(s) if s.eq_str("error"));
            if !is_error {
                let rej = vm.native_closure("", 1, static_once_reject, vec![cap.reject.clone()]);
                let w2 = once_wrapper(vm, &emitter, &Value::str("error"), &Value::Obj(rej));
                vm.call(&add, emitter, &[Value::str("error"), w2])?;
            }
        }
    } else {
        // EventTarget
        let ael = vm.get_prop_of(&emitter, &PropKey::from_str("addEventListener"))?;
        let resolver2 = vm.native_closure("", 0, static_once_resolve, vec![cap.resolve.clone()]);
        let opts = vm.obj_from(vec![("once", Value::Bool(true))]);
        vm.call(&ael, emitter, &[name, Value::Obj(resolver2), Value::Obj(opts)])?;
    }
    Ok(cap.promise)
}

fn static_once_resolve(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let arr = vm.new_array(a.args.to_vec());
    vm.call(&a.slot(0), Value::Undefined, &[Value::Obj(arr)])?;
    Ok(Value::Undefined)
}

fn static_once_reject(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    vm.call(&a.slot(0), Value::Undefined, &[a.arg(0)])?;
    Ok(Value::Undefined)
}

fn static_on(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    vm.throw_type("events.on is not supported")
}

fn static_listener_count(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = vm.get_prop_of(&a.arg(0), &PropKey::from_str("listenerCount"))?;
    vm.call(&f, a.arg(0), &[a.arg(1)])
}

fn static_get_event_listeners(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = vm.get_prop_of(&a.arg(0), &PropKey::from_str("listeners"))?;
    if f.is_callable() {
        return vm.call(&f, a.arg(0), &[a.arg(1)]);
    }
    Ok(Value::Obj(vm.new_array(Vec::new())))
}
