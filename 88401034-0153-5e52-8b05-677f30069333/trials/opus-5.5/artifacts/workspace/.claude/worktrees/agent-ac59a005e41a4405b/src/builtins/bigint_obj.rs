// BigInt constructor and prototype.

use crate::bigint::{self, BigInt};
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::rc::Rc;

pub fn setup(vm: &mut Vm) {
    let proto = vm.intr.bigint_proto.clone();
    let ctor = vm.native_ctor("BigInt", 1, bigint_ctor, &proto);
    vm.def_method(&ctor, "asIntN", 2, as_int_n);
    vm.def_method(&ctor, "asUintN", 2, as_uint_n);
    vm.def_method(&proto, "toString", 0, to_string);
    vm.def_method(&proto, "toLocaleString", 0, to_locale_string);
    vm.def_method(&proto, "valueOf", 0, value_of);
    vm.set_tag(&proto, "BigInt");
    vm.def_global("BigInt", Value::Obj(ctor));
}

fn bigint_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_some() {
        return vm.throw_type(bigint::MSG_NOT_CONSTRUCTOR);
    }
    let v = a.arg(0);
    let p = vm.to_primitive(&v, crate::ops::Hint::Number)?;
    match p {
        Value::Num(n) => match BigInt::from_f64(n) {
            Some(b) => Ok(Value::BigInt(Rc::new(b))),
            None => vm.throw_range(bigint::MSG_NUMBER_NOT_INTEGER),
        },
        Value::Str(s) => match BigInt::parse(s.units()) {
            Some(b) => Ok(Value::BigInt(Rc::new(b))),
            None => vm.throw_syntax(bigint::MSG_INVALID_STRING),
        },
        other => Ok(Value::BigInt(vm.to_bigint(&other)?)),
    }
}

fn this_bigint(vm: &mut Vm, v: &Value) -> JsResult<Rc<BigInt>> {
    match v {
        Value::BigInt(b) => Ok(b.clone()),
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::BigInt(b) => Ok(b.clone()),
            _ => Err(vm.make_error("TypeError", bigint::MSG_INCOMPATIBLE_RECEIVER)),
        },
        _ => vm.throw_type(bigint::MSG_INCOMPATIBLE_RECEIVER),
    }
}

fn to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = this_bigint(vm, &a.this)?;
    let radix = if a.arg(0).is_undefined() { 10.0 } else { vm.to_integer_or_infinity(&a.arg(0))? };
    if !(2.0..=36.0).contains(&radix) {
        return vm.throw_range(bigint::MSG_RADIX);
    }
    Ok(Value::str(&b.to_string_radix(radix as u32)))
}

fn to_locale_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = this_bigint(vm, &a.this)?;
    if !a.arg(0).is_undefined() || !a.arg(1).is_undefined() {
        // with locales/options: new Intl.NumberFormat(locales, options).format(b)
        let g = vm.global.clone();
        if let Value::Obj(intl) = vm.get_str(&g, "Intl")? {
            let ctor = vm.get_str(&intl, "NumberFormat")?;
            if ctor.is_callable() {
                let nf = vm.construct(&ctor, &[a.arg(0), a.arg(1)], None)?;
                if let Value::Obj(no) = &nf {
                    let format = vm.get_str(no, "format")?;
                    return vm.call(&format, nf.clone(), &[Value::BigInt(b)]);
                }
            }
        }
    }
    let s = b.to_string_radix(10);
    Ok(Value::str(&crate::builtins::intl::group_digits_str(&s, ",")))
}

fn value_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::BigInt(this_bigint(vm, &a.this)?))
}

fn bits_arg(vm: &mut Vm, v: &Value) -> JsResult<u64> {
    let n = vm.to_index(v)?;
    Ok(n as u64)
}

fn as_int_n(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let bits = bits_arg(vm, &a.arg(0))?;
    let b = vm.to_bigint(&a.arg(1))?;
    match b.as_int_n(bits) {
        Ok(r) => Ok(Value::BigInt(Rc::new(r))),
        Err(e) => vm.throw_range(e.message()),
    }
}

fn as_uint_n(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let bits = bits_arg(vm, &a.arg(0))?;
    let b = vm.to_bigint(&a.arg(1))?;
    match b.as_uint_n(bits) {
        Ok(r) => Ok(Value::BigInt(Rc::new(r))),
        Err(e) => vm.throw_range(e.message()),
    }
}
