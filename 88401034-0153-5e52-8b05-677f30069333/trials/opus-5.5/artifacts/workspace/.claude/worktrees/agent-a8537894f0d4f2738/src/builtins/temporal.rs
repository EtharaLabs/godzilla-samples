// Temporal (minimal subset).

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let t = vm.new_object();
    let now = vm.new_object();
    vm.def_method(&now, "instant", 0, now_instant);
    vm.set_tag(&now, "Temporal.Now");
    t.set_prop(PropKey::from_str("Now"), Value::Obj(now), WC);
    vm.set_tag(&t, "Temporal");
    vm.def_global("Temporal", Value::Obj(t));
}

fn now_instant(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    instant_from_ms(vm, crate::datetime::now_ms())
}

pub fn instant_from_ms(vm: &mut Vm, t: f64) -> JsResult<Value> {
    if t.is_nan() {
        return vm.throw_range("Invalid time value");
    }
    let o = vm.new_object();
    o.set_str("epochMilliseconds", Value::Num(t), WEC);
    Ok(Value::Obj(o))
}
