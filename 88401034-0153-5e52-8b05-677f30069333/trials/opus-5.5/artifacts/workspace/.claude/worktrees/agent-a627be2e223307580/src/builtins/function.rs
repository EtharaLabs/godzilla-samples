// Function constructor and Function.prototype.

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let proto = vm.intr.function_proto.clone();
    {
        let mut b = proto.borrow_mut();
        b.props.insert(vm.intr.key_length.clone(), Prop::Data { value: Value::Num(0.0), flags: CONFIGURABLE });
        b.props.insert(vm.intr.key_name.clone(), Prop::Data { value: Value::str(""), flags: CONFIGURABLE });
    }
    let ctor = vm.native_ctor("Function", 1, function_ctor, &proto);
    vm.intr.function_ctor = ctor.clone();
    vm.def_method(&proto, "apply", 2, apply);
    vm.def_method(&proto, "bind", 1, bind);
    vm.def_method(&proto, "call", 1, call);
    vm.def_method(&proto, "toString", 0, to_string);
    let hi = vm.native_fn("[Symbol.hasInstance]", 1, has_instance);
    proto.set_prop(PropKey::Sym(vm.intr.sym_has_instance.clone()), Value::Obj(hi.clone()), 0);
    vm.intr.function_has_instance = hi;
    let thrower = vm.native_fn("", 0, throw_type_error);
    thrower.borrow_mut().extensible = false;
    {
        let mut b = thrower.borrow_mut();
        b.props.insert(vm.intr.key_length.clone(), Prop::Data { value: Value::Num(0.0), flags: 0 });
        b.props.insert(vm.intr.key_name.clone(), Prop::Data { value: Value::str(""), flags: 0 });
    }
    vm.intr.throw_type_error = thrower.clone();
    proto.set_accessor(PropKey::from_str("caller"), Some(thrower.clone()), Some(thrower.clone()), CONFIGURABLE);
    proto.set_accessor(PropKey::from_str("arguments"), Some(thrower.clone()), Some(thrower), CONFIGURABLE);
    vm.def_global("Function", Value::Obj(ctor));
}

fn throw_type_error(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    vm.throw_type("'caller', 'callee', and 'arguments' properties may not be accessed on strict mode functions or the arguments objects for calls to them")
}

pub fn create_dynamic_function(vm: &mut Vm, args: &[Value], kind: &str, nt: Option<Obj>) -> JsResult<Value> {
    let mut params = Vec::new();
    let n = args.len();
    for a in args.iter().take(n.saturating_sub(1)) {
        params.push(vm.to_string(a)?.to_rust_string());
    }
    let body = if n > 0 { vm.to_string(&args[n - 1])?.to_rust_string() } else { String::new() };
    let prefix = match kind {
        "generator" => "function*",
        "async" => "async function",
        "asyncGenerator" => "async function*",
        _ => "function",
    };
    let src = format!("{} anonymous({}\n) {{\n{}\n}}", prefix, params.join(","), body);
    let f = crate::loader::compile_function_source(vm, &src)?;
    if let Some(nt) = nt {
        let fallback = match kind {
            "generator" => vm.intr.generator_function_proto.clone(),
            "async" => vm.intr.async_function_proto.clone(),
            "asyncGenerator" => vm.intr.async_generator_function_proto.clone(),
            _ => vm.intr.function_proto.clone(),
        };
        let p = vm.proto_from_nt(&Some(nt), &fallback)?;
        f.borrow_mut().proto = Some(p);
    }
    Ok(Value::Obj(f))
}

fn function_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    create_dynamic_function(vm, a.args, "normal", a.new_target.clone())
}

fn apply(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !a.this.is_callable() {
        let d = vm.describe_for_call(&a.this);
        return vm.throw_type(format!("{} is not a function", d));
    }
    let arr = a.arg(1);
    let args = if arr.is_nullish() {
        Vec::new()
    } else {
        if !arr.is_object() {
            return vm.throw_type("apply: argument list must be array-like");
        }
        crate::builtins::array::array_like_to_vec(vm, &arr)?
    };
    vm.call(&a.this, a.arg(0), &args)
}

fn call(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !a.this.is_callable() {
        let d = vm.describe_for_call(&a.this);
        return vm.throw_type(format!("{} is not a function", d));
    }
    let rest = if a.args.is_empty() { &[][..] } else { &a.args[1..] };
    vm.call(&a.this, a.arg(0), rest)
}

fn bind(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let target = match &a.this {
        Value::Obj(o) if o.is_callable() => o.clone(),
        _ => return vm.throw_type("bind must be called on a function"),
    };
    let bound_args: Vec<Value> = if a.args.len() > 1 { a.args[1..].to_vec() } else { Vec::new() };
    let proto = vm.get_prototype_of(&target)?;
    let f = Obj::with_class(proto, ObjKind::Bound(Box::new(BoundFunc { target: target.clone(), this: a.arg(0), args: bound_args.clone() })), "Function");
    // length
    let mut len = 0.0;
    if vm.has_own_property(&target, &vm.intr.key_length.clone())? {
        let l = vm.get(&target, &vm.intr.key_length.clone(), &a.this)?;
        if let Value::Num(n) = l {
            if n == f64::INFINITY {
                len = f64::INFINITY;
            } else if n.is_finite() {
                let t = crate::ops::integer_or_infinity(n);
                len = (t - bound_args.len() as f64).max(0.0);
            }
        }
    }
    let name = vm.get(&target, &vm.intr.key_name.clone(), &a.this)?;
    let name = match name {
        Value::Str(s) => s.to_rust_string(),
        _ => String::new(),
    };
    {
        let mut b = f.borrow_mut();
        b.props.insert(vm.intr.key_length.clone(), Prop::Data { value: Value::Num(len), flags: CONFIGURABLE });
        b.props.insert(vm.intr.key_name.clone(), Prop::Data { value: Value::str(&format!("bound {}", name)), flags: CONFIGURABLE });
    }
    Ok(Value::Obj(f))
}

pub fn function_to_string(vm: &mut Vm, f: &Obj) -> Option<String> {
    let b = f.borrow();
    match &b.kind {
        ObjKind::Closure(c) => {
            if c.code.is_default_ctor || (c.code.class_source && c.code.src_end == 0) {
                return Some(format!("class {} {{ }}", c.code.name));
            }
            Some(c.code.source_text())
        }
        ObjKind::Native(_) => {
            let name = match b.props.get(&vm.intr.key_name) {
                Some(Prop::Data { value: Value::Str(s), .. }) => s.to_rust_string(),
                _ => String::new(),
            };
            Some(format!("function {}() {{ [native code] }}", name))
        }
        ObjKind::Bound(_) => Some("function () { [native code] }".to_string()),
        ObjKind::Proxy(p) if p.callable => Some("function () { [native code] }".to_string()),
        _ => None,
    }
}

fn to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let Value::Obj(o) = &a.this {
        if let Some(s) = function_to_string(vm, o) {
            return Ok(Value::str(&s));
        }
    }
    vm.throw_type("Function.prototype.toString requires that 'this' be a Function")
}

fn has_instance(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match &a.this {
        Value::Obj(o) => Ok(Value::Bool(vm.ordinary_has_instance(o, &a.arg(0))?)),
        _ => Ok(Value::Bool(false)),
    }
}
