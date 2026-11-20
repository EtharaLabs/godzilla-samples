// Web platform APIs (initial subset)

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let perf = vm.new_object();
    vm.def_method(&perf, "now", 0, |vm, _a| Ok(Value::Num(vm.host.now_ms())));
    perf.set_str("timeOrigin", Value::Num(crate::datetime::now_ms()), WEC);
    vm.def_global("performance", Value::Obj(perf));
    let nav = vm.obj_from(vec![("userAgent", Value::str("lumen")), ("hardwareConcurrency", Value::Num(std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1) as f64)), ("language", Value::str("en-US"))]);
    vm.def_global("navigator", Value::Obj(nav));
    let g = vm.global.clone();
    vm.def_global("self", Value::Obj(g));
}

pub fn create_timers_promises(vm: &mut Vm) -> Value {
    Value::Obj(vm.new_object())
}

pub fn create_url_module(vm: &mut Vm) -> Value {
    Value::Obj(vm.new_object())
}

pub fn create_querystring_module(vm: &mut Vm) -> Value {
    Value::Obj(vm.new_object())
}

pub fn _unused(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Undefined)
}
