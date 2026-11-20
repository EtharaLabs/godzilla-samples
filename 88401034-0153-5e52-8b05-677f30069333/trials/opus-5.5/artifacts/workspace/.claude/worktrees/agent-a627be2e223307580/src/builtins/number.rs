// Number and Boolean.

use crate::numconv;
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn to_int32(n: f64) -> i32 {
    if n.is_finite() && n.abs() < 2147483648.0 {
        return n as i32;
    }
    to_uint32(n) as i32
}

pub fn to_uint32(n: f64) -> u32 {
    if !n.is_finite() || n == 0.0 {
        return 0;
    }
    if (0.0..4294967296.0).contains(&n) {
        return n as u32;
    }
    let t = n.trunc();
    let m = t.rem_euclid(4294967296.0);
    m as u32
}

pub fn to_uint16(n: f64) -> u16 {
    to_uint32(n) as u16
}

pub fn setup(vm: &mut Vm) {
    let proto = vm.intr.number_proto.clone();
    let ctor = vm.native_ctor("Number", 1, number_ctor, &proto);
    for (n, v) in [
        ("MAX_SAFE_INTEGER", 9007199254740991.0),
        ("MIN_SAFE_INTEGER", -9007199254740991.0),
        ("MAX_VALUE", f64::MAX),
        ("MIN_VALUE", 5e-324),
        ("POSITIVE_INFINITY", f64::INFINITY),
        ("NEGATIVE_INFINITY", f64::NEG_INFINITY),
        ("NaN", f64::NAN),
        ("EPSILON", f64::EPSILON),
    ] {
        ctor.set_prop(PropKey::from_str(n), Value::Num(v), 0);
    }
    vm.def_method(&ctor, "isNaN", 1, is_nan);
    vm.def_method(&ctor, "isFinite", 1, is_finite);
    vm.def_method(&ctor, "isSafeInteger", 1, is_safe_integer);
    vm.def_method(&ctor, "isInteger", 1, is_integer);
    vm.def_method(&proto, "toLocaleString", 0, to_locale_string);
    vm.def_method(&proto, "toString", 1, to_string);
    vm.def_method(&proto, "valueOf", 0, value_of);
    vm.def_method(&proto, "toExponential", 1, to_exponential);
    vm.def_method(&proto, "toPrecision", 1, to_precision);
    vm.def_method(&proto, "toFixed", 1, to_fixed);
    move_to_end(&proto, &vm.intr.key_constructor.clone());
    vm.def_global("Number", Value::Obj(ctor.clone()));

    let bproto = vm.intr.boolean_proto.clone();
    let bctor = vm.native_ctor("Boolean", 1, boolean_ctor, &bproto);
    vm.def_method(&bproto, "toString", 0, bool_to_string);
    vm.def_method(&bproto, "valueOf", 0, bool_value_of);
    vm.def_global("Boolean", Value::Obj(bctor));
}

pub fn setup_number_parse_links(vm: &mut Vm) {
    let g = vm.global.clone();
    let ctor = g.get_own_str("Number").unwrap();
    let pi = g.get_own_str("parseInt").unwrap();
    let pf = g.get_own_str("parseFloat").unwrap();
    if let Value::Obj(c) = ctor {
        c.set_prop(PropKey::from_str("parseInt"), pi, WC);
        c.set_prop(PropKey::from_str("parseFloat"), pf, WC);
    }
}

fn number_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let n = if a.args.is_empty() {
        0.0
    } else {
        match vm.to_numeric(&a.args[0])? {
            Value::BigInt(b) => b.to_f64(),
            Value::Num(n) => n,
            _ => 0.0,
        }
    };
    match &a.new_target {
        None => Ok(Value::Num(n)),
        Some(_) => {
            let proto = vm.proto_from_nt(&a.new_target, &vm.intr.number_proto.clone())?;
            Ok(Value::Obj(Obj::with_class(Some(proto), ObjKind::Number(n), "Number")))
        }
    }
}

fn is_nan(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(matches!(a.arg(0), Value::Num(n) if n.is_nan())))
}
fn is_finite(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(matches!(a.arg(0), Value::Num(n) if n.is_finite())))
}
fn is_integer(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(matches!(a.arg(0), Value::Num(n) if n.is_finite() && n.trunc() == n)))
}
fn is_safe_integer(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(matches!(a.arg(0), Value::Num(n) if n.is_finite() && n.trunc() == n && n.abs() <= 9007199254740991.0)))
}

pub fn this_number(vm: &mut Vm, v: &Value) -> JsResult<f64> {
    match v {
        Value::Num(n) => Ok(*n),
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Number(n) => Ok(*n),
            _ => Err(vm.make_error("TypeError", numconv::MSG_NUMBER_INCOMPATIBLE_RECEIVER)),
        },
        _ => vm.throw_type(numconv::MSG_NUMBER_INCOMPATIBLE_RECEIVER),
    }
}

fn to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let x = this_number(vm, &a.this)?;
    let radix = if a.arg(0).is_undefined() { 10.0 } else { vm.to_integer_or_infinity(&a.arg(0))? };
    if !(2.0..=36.0).contains(&radix) {
        return vm.throw_range(numconv::MSG_TO_STRING_RADIX);
    }
    if radix == 10.0 {
        return Ok(Value::Str(crate::ops::num_to_jsstr(x)));
    }
    Ok(Value::str(&numconv::number_to_string_radix(x, radix as u32)))
}

fn to_locale_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let x = this_number(vm, &a.this)?;
    crate::builtins::intl::number_to_locale_string(vm, x, &a.arg(0), &a.arg(1))
}

fn value_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Num(this_number(vm, &a.this)?))
}

fn to_fixed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let x = this_number(vm, &a.this)?;
    let f = vm.to_integer_or_infinity(&a.arg(0))?;
    if !(0.0..=100.0).contains(&f) {
        return vm.throw_range(numconv::MSG_TO_FIXED_RANGE);
    }
    if !x.is_finite() {
        return Ok(Value::str(&numconv::number_to_string(x)));
    }
    Ok(Value::str(&numconv::to_fixed(x, f as u32)))
}

fn to_exponential(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let x = this_number(vm, &a.this)?;
    let f = vm.to_integer_or_infinity(&a.arg(0))?;
    if !x.is_finite() {
        return Ok(Value::str(&numconv::number_to_string(x)));
    }
    if !(0.0..=100.0).contains(&f) {
        return vm.throw_range(numconv::MSG_TO_EXPONENTIAL_RANGE);
    }
    let d = if a.arg(0).is_undefined() { None } else { Some(f as u32) };
    Ok(Value::str(&numconv::to_exponential(x, d)))
}

fn to_precision(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let x = this_number(vm, &a.this)?;
    if a.arg(0).is_undefined() {
        return Ok(Value::Str(crate::ops::num_to_jsstr(x)));
    }
    let p = vm.to_integer_or_infinity(&a.arg(0))?;
    if !x.is_finite() {
        return Ok(Value::str(&numconv::number_to_string(x)));
    }
    if !(1.0..=100.0).contains(&p) {
        return vm.throw_range(numconv::MSG_TO_PRECISION_RANGE);
    }
    Ok(Value::str(&numconv::to_precision(x, p as u32)))
}

fn boolean_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = a.arg(0).truthy();
    match &a.new_target {
        None => Ok(Value::Bool(b)),
        Some(_) => {
            let proto = vm.proto_from_nt(&a.new_target, &vm.intr.boolean_proto.clone())?;
            Ok(Value::Obj(Obj::with_class(Some(proto), ObjKind::Boolean(b), "Boolean")))
        }
    }
}

fn this_bool(vm: &mut Vm, v: &Value) -> JsResult<bool> {
    match v {
        Value::Bool(b) => Ok(*b),
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Boolean(b) => Ok(*b),
            _ => Err(vm.make_error("TypeError", "Boolean method called on incompatible receiver")),
        },
        _ => vm.throw_type("Boolean method called on incompatible receiver"),
    }
}

fn bool_to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = this_bool(vm, &a.this)?;
    Ok(Value::str(if b { "true" } else { "false" }))
}

fn bool_value_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(this_bool(vm, &a.this)?))
}
