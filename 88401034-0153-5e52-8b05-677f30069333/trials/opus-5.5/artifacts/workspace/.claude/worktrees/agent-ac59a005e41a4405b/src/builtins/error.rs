// Error constructors.

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let ep = vm.intr.error_proto.clone();
    let error_ctor = vm.native_ctor("Error", 1, error_ctor, &ep);
    vm.def_value(&ep, "name", Value::str("Error"), WC);
    vm.def_value(&ep, "message", Value::str(""), WC);
    vm.def_method(&ep, "toString", 0, error_to_string);
    vm.def_accessor(&ep, "stack", stack_get, stack_set);
    // move constructor after stack to match the original's property order
    let removed = ep.borrow_mut().props.remove(&vm.intr.key_constructor.clone());
    drop(removed);
    ep.set_prop(vm.intr.key_constructor.clone(), Value::Obj(error_ctor.clone()), WC);
    vm.def_method(&error_ctor, "isError", 1, is_error);
    // reorder: prototype after isError
    let proto_prop = error_ctor.borrow_mut().props.remove(&vm.intr.key_prototype.clone());
    if let Some(p) = proto_prop {
        error_ctor.borrow_mut().props.insert(vm.intr.key_prototype.clone(), p);
    }
    vm.def_value(&error_ctor, "stackTraceLimit", Value::Num(10.0), WEC);
    // (an enumerable, anonymous, constructible function in the reference engine)
    let cst_proto = vm.new_object();
    let cst = vm.native_ctor("", 2, capture_stack_trace, &cst_proto);
    // (a writable prototype property, like ordinary functions)
    cst.set_prop(vm.intr.key_prototype.clone(), Value::Obj(cst_proto), WRITABLE);
    error_ctor.set_prop(PropKey::from_str("captureStackTrace"), Value::Obj(cst), WEC);
    vm.def_global("Error", Value::Obj(error_ctor.clone()));

    let kinds: [(&str, Obj, crate::object::NativeFn); 6] = [
        ("TypeError", vm.intr.type_error_proto.clone(), type_error_ctor),
        ("RangeError", vm.intr.range_error_proto.clone(), range_error_ctor),
        ("ReferenceError", vm.intr.reference_error_proto.clone(), reference_error_ctor),
        ("SyntaxError", vm.intr.syntax_error_proto.clone(), syntax_error_ctor),
        ("EvalError", vm.intr.eval_error_proto.clone(), eval_error_ctor),
        ("URIError", vm.intr.uri_error_proto.clone(), uri_error_ctor),
    ];
    for (name, proto, f) in kinds {
        let c = vm.native_ctor(name, 1, f, &proto);
        c.borrow_mut().proto = Some(error_ctor.clone());
        vm.def_value(&proto, "name", Value::str(name), WC);
        vm.def_value(&proto, "message", Value::str(""), WC);
        vm.def_global(name, Value::Obj(c));
    }
    let ap = vm.intr.aggregate_error_proto.clone();
    let ac = vm.native_ctor("AggregateError", 2, aggregate_error_ctor, &ap);
    ac.borrow_mut().proto = Some(error_ctor.clone());
    vm.def_value(&ap, "name", Value::str("AggregateError"), WC);
    vm.def_value(&ap, "message", Value::str(""), WC);
    vm.def_global("AggregateError", Value::Obj(ac));
    let sp = vm.intr.suppressed_error_proto.clone();
    let sc = vm.native_ctor("SuppressedError", 3, suppressed_error_ctor, &sp);
    sc.borrow_mut().proto = Some(error_ctor);
    vm.def_value(&sp, "name", Value::str("SuppressedError"), WC);
    vm.def_value(&sp, "message", Value::str(""), WC);
    vm.def_global("SuppressedError", Value::Obj(sc));
}

fn make(vm: &mut Vm, a: &Args, fallback: Obj, name: &str, msg_index: usize) -> JsResult<Obj> {
    let nt = match &a.new_target {
        Some(nt) => Some(nt.clone()),
        None => Some(a.callee.clone()),
    };
    let proto = vm.proto_from_nt(&nt, &fallback)?;
    let o = Obj::with_class(Some(proto), ObjKind::Error, "Error");
    let msg = a.arg(msg_index);
    let mut msg_str = String::new();
    if !msg.is_undefined() {
        let s = vm.to_string(&msg)?;
        msg_str = s.to_rust_string();
        o.set_prop(vm.intr.key_message.clone(), Value::Str(s), WC);
    }
    let opts = a.arg(msg_index + 1);
    if let Value::Obj(oo) = &opts {
        let ck = PropKey::from_str("cause");
        if vm.has_property(oo, &ck)? {
            let c = vm.get(oo, &ck, &opts)?;
            o.set_prop(ck, c, WC);
        }
    }
    // stack uses the constructed object's name
    let n = match vm.get(&o, &vm.intr.key_name.clone(), &Value::Obj(o.clone()))? {
        Value::Str(s) => s.to_rust_string(),
        _ => name.to_string(),
    };
    vm.attach_stack(&o, &n, &msg_str);
    Ok(o)
}

fn error_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = vm.intr.error_proto.clone();
    Ok(Value::Obj(make(vm, a, p, "Error", 0)?))
}
fn type_error_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = vm.intr.type_error_proto.clone();
    Ok(Value::Obj(make(vm, a, p, "TypeError", 0)?))
}
fn range_error_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = vm.intr.range_error_proto.clone();
    Ok(Value::Obj(make(vm, a, p, "RangeError", 0)?))
}
fn reference_error_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = vm.intr.reference_error_proto.clone();
    Ok(Value::Obj(make(vm, a, p, "ReferenceError", 0)?))
}
fn syntax_error_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = vm.intr.syntax_error_proto.clone();
    Ok(Value::Obj(make(vm, a, p, "SyntaxError", 0)?))
}
fn eval_error_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = vm.intr.eval_error_proto.clone();
    Ok(Value::Obj(make(vm, a, p, "EvalError", 0)?))
}
fn uri_error_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = vm.intr.uri_error_proto.clone();
    Ok(Value::Obj(make(vm, a, p, "URIError", 0)?))
}

fn aggregate_error_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = vm.intr.aggregate_error_proto.clone();
    let o = make(vm, a, p, "AggregateError", 1)?;
    let errs = vm.iterate_spread(&a.arg(0), "value is not iterable")?;
    let arr = vm.new_array(errs);
    o.set_prop(PropKey::from_str("errors"), Value::Obj(arr), WC);
    Ok(Value::Obj(o))
}

fn suppressed_error_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = vm.intr.suppressed_error_proto.clone();
    let o = make(vm, a, p, "SuppressedError", 2)?;
    o.set_prop(PropKey::from_str("error"), a.arg(0), WC);
    o.set_prop(PropKey::from_str("suppressed"), a.arg(1), WC);
    Ok(Value::Obj(o))
}

fn error_to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("Error.prototype.toString called on a non-object"),
    };
    let name = vm.get(&o, &vm.intr.key_name.clone(), &a.this)?;
    let name = if name.is_undefined() { JsStr::from_str("Error") } else { vm.to_string(&name)? };
    let msg = vm.get(&o, &vm.intr.key_message.clone(), &a.this)?;
    let msg = if msg.is_undefined() { JsStr::empty() } else { vm.to_string(&msg)? };
    if name.is_empty() {
        return Ok(Value::Str(msg));
    }
    if msg.is_empty() {
        return Ok(Value::Str(name));
    }
    Ok(Value::str(&format!("{}: {}", name, msg)))
}

fn stack_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let Value::Obj(o) = &a.this {
        let k = PropKey::Sym(vm.intr.stack_sym.clone());
        let frames = match o.borrow().props.get(&k) {
            Some(Prop::Data { value, .. }) => Some(value.clone()),
            _ => None,
        };
        if let Some(Value::Str(fr)) = frames {
            let header = error_to_string(vm, a)?;
            let h = vm.to_string(&header)?;
            return Ok(Value::Str(JsStr::concat(&h, &fr)));
        }
    }
    Ok(Value::Undefined)
}

fn stack_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let Value::Obj(o) = &a.this {
        o.set_prop(PropKey::from_str("stack"), a.arg(0), WC);
    }
    let _ = vm;
    Ok(Value::Undefined)
}

fn is_error(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(matches!(&a.arg(0), Value::Obj(o) if matches!(o.borrow().kind, ObjKind::Error))))
}

fn capture_stack_trace(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match a.arg(0) {
        Value::Obj(o) => {
            let name = match vm.get(&o, &vm.intr.key_name.clone(), &Value::Obj(o.clone()))? {
                Value::Str(s) => s.to_rust_string(),
                _ => "Error".to_string(),
            };
            let msg = match vm.get(&o, &vm.intr.key_message.clone(), &Value::Obj(o.clone()))? {
                Value::Str(s) => s.to_rust_string(),
                _ => String::new(),
            };
            let s = format!("{}: {}\n    at <lumen>:0:0", name, msg);
            o.set_prop(PropKey::from_str("stack"), Value::str(&s), WC);
            Ok(Value::Undefined)
        }
        _ => vm.throw_type("Invalid argument"),
    }
}
