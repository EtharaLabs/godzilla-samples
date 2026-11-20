// nodestream (to be implemented)

use crate::value::*;
use crate::vm::Vm;

#[allow(unused_variables)]
pub fn setup(vm: &mut Vm) {}

#[allow(unused_variables)]
pub fn create_module(vm: &mut Vm, name: &str) -> Value {
    Value::Obj(vm.new_object())
}
