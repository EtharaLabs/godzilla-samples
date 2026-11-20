// node:zlib bindings (initial subset)

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn create_module(vm: &mut Vm) -> Value {
    let o = vm.new_object();
    Value::Obj(o)
}

pub fn _unused(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Undefined)
}
