// DisposableStack and AsyncDisposableStack.

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let p = vm.intr.disposable_stack_proto.clone();
    let c = vm.native_ctor("DisposableStack", 0, ds_ctor, &p);
    vm.def_method(&p, "use", 1, ds_use);
    vm.def_method(&p, "adopt", 2, ds_adopt);
    vm.def_method(&p, "defer", 1, ds_defer);
    vm.def_method(&p, "move", 0, ds_move);
    let dispose = vm.def_method(&p, "dispose", 0, ds_dispose);
    vm.def_getter(&p, "disposed", ds_disposed);
    p.set_prop(PropKey::Sym(vm.intr.sym_dispose.clone()), Value::Obj(dispose), WC);
    vm.set_tag(&p, "DisposableStack");
    vm.def_global("DisposableStack", Value::Obj(c));
    let ap = vm.intr.async_disposable_stack_proto.clone();
    let ac = vm.native_ctor("AsyncDisposableStack", 0, ds_ctor_async, &ap);
    vm.def_method(&ap, "use", 1, ds_use);
    vm.def_method(&ap, "adopt", 2, ds_adopt);
    vm.def_method(&ap, "defer", 1, ds_defer);
    vm.def_method(&ap, "move", 0, ds_move);
    let ad = vm.def_method(&ap, "disposeAsync", 0, ds_dispose_async);
    vm.def_getter(&ap, "disposed", ds_disposed);
    ap.set_prop(PropKey::Sym(vm.intr.sym_async_dispose.clone()), Value::Obj(ad), WC);
    vm.set_tag(&ap, "AsyncDisposableStack");
    vm.def_global("AsyncDisposableStack", Value::Obj(ac));
}

pub struct DisposableState {
    pub disposed: bool,
    pub items: Vec<(Value, Value, u8)>, // (value, method, kind: 0 use, 1 adopt, 2 defer)
    pub is_async: bool,
}

fn make(vm: &mut Vm, a: &Args, is_async: bool) -> JsResult<Value> {
    if a.new_target.is_none() {
        return vm.throw_type("Constructor requires 'new'");
    }
    let fallback = if is_async { vm.intr.async_disposable_stack_proto.clone() } else { vm.intr.disposable_stack_proto.clone() };
    let proto = vm.proto_from_nt(&a.new_target, &fallback)?;
    Ok(Value::Obj(Obj::new(Some(proto), ObjKind::Host(Box::new(std::cell::RefCell::new(DisposableState { disposed: false, items: Vec::new(), is_async }))))))
}

fn ds_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    make(vm, a, false)
}
fn ds_ctor_async(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    make(vm, a, true)
}

fn with_state<R>(vm: &mut Vm, v: &Value, f: impl FnOnce(&mut DisposableState) -> R) -> JsResult<R> {
    if let Value::Obj(o) = v {
        if let ObjKind::Host(h) = &o.borrow().kind {
            if let Some(st) = h.downcast_ref::<std::cell::RefCell<DisposableState>>() {
                return Ok(f(&mut st.borrow_mut()));
            }
        }
    }
    vm.throw_type("method called on incompatible receiver")
}

fn check_live(vm: &mut Vm, v: &Value) -> JsResult<()> {
    if with_state(vm, v, |s| s.disposed)? {
        return vm.throw_error("ReferenceError", "DisposableStack already disposed");
    }
    Ok(())
}

fn ds_use(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    check_live(vm, &a.this)?;
    let v = a.arg(0);
    if v.is_nullish() {
        return Ok(v);
    }
    let is_async = with_state(vm, &a.this, |s| s.is_async)?;
    let mut m = Value::Undefined;
    if is_async {
        m = vm.get_prop_of(&v, &PropKey::Sym(vm.intr.sym_async_dispose.clone()))?;
    }
    if m.is_undefined() {
        m = vm.get_prop_of(&v, &PropKey::Sym(vm.intr.sym_dispose.clone()))?;
    }
    if !m.is_callable() {
        return vm.throw_type("Symbol.dispose is not a function");
    }
    let vv = v.clone();
    with_state(vm, &a.this, |s| s.items.push((vv, m, 0)))?;
    Ok(v)
}

fn ds_adopt(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    check_live(vm, &a.this)?;
    let f = a.arg(1);
    if !f.is_callable() {
        return vm.throw_type("onDispose is not a function");
    }
    let v = a.arg(0);
    let vv = v.clone();
    with_state(vm, &a.this, |s| s.items.push((vv, f, 1)))?;
    Ok(v)
}

fn ds_defer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    check_live(vm, &a.this)?;
    let f = a.arg(0);
    if !f.is_callable() {
        return vm.throw_type("onDispose is not a function");
    }
    with_state(vm, &a.this, |s| s.items.push((Value::Undefined, f, 2)))?;
    Ok(Value::Undefined)
}

fn ds_move(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    check_live(vm, &a.this)?;
    let (items, is_async) = with_state(vm, &a.this, |s| {
        s.disposed = true;
        (std::mem::take(&mut s.items), s.is_async)
    })?;
    let proto = if is_async { vm.intr.async_disposable_stack_proto.clone() } else { vm.intr.disposable_stack_proto.clone() };
    Ok(Value::Obj(Obj::new(Some(proto), ObjKind::Host(Box::new(std::cell::RefCell::new(DisposableState { disposed: false, items, is_async }))))))
}

fn ds_disposed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(with_state(vm, &a.this, |s| s.disposed)?))
}

pub fn run_disposals(vm: &mut Vm, items: Vec<(Value, Value, u8)>) -> JsResult<()> {
    let mut err: Option<Value> = None;
    for (v, m, kind) in items.into_iter().rev() {
        let r = match kind {
            0 => vm.call(&m, v, &[]),
            1 => vm.call(&m, Value::Undefined, &[v]),
            _ => vm.call(&m, Value::Undefined, &[]),
        };
        if let Err(e) = r {
            err = Some(match err {
                None => e,
                Some(prev) => {
                    let o = Obj::with_class(Some(vm.intr.suppressed_error_proto.clone()), ObjKind::Error, "Error");
                    o.set_prop(PropKey::from_str("error"), e, WC);
                    o.set_prop(PropKey::from_str("suppressed"), prev, WC);
                    o.set_prop(vm.intr.key_message.clone(), Value::str("An error was suppressed during disposal"), WC);
                    Value::Obj(o)
                }
            });
        }
    }
    match err {
        Some(e) => Err(e),
        None => Ok(()),
    }
}

fn ds_dispose(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let already = with_state(vm, &a.this, |s| s.disposed)?;
    if already {
        return Ok(Value::Undefined);
    }
    let items = with_state(vm, &a.this, |s| {
        s.disposed = true;
        std::mem::take(&mut s.items)
    })?;
    run_disposals(vm, items)?;
    Ok(Value::Undefined)
}

fn ds_dispose_async(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let r = ds_dispose(vm, a);
    match r {
        Ok(_) => vm.call(&cap.resolve, Value::Undefined, &[Value::Undefined])?,
        Err(e) => vm.call(&cap.reject, Value::Undefined, &[e])?,
    };
    Ok(cap.promise)
}
