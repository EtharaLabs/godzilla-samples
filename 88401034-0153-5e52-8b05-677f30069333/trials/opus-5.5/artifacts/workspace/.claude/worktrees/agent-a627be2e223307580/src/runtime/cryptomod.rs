// node:crypto bindings (initial subset)

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

/// global WebCrypto (crypto, Crypto, SubtleCrypto, CryptoKey)
#[allow(unused_variables)]
pub fn setup(vm: &mut Vm) {}

pub fn create_module(vm: &mut Vm) -> Value {
    let o = vm.new_object();
    vm.def_method(&o, "randomUUID", 0, random_uuid);
    Value::Obj(o)
}

pub fn random_uuid(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::str(&crate::crypto::random_uuid()))
}
