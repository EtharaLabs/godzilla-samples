// Builtin objects of the ECMAScript standard library.

pub mod array;
pub mod bigint_obj;
pub mod date;
pub mod disposable;
pub mod error;
pub mod function;
pub mod generators;
pub mod global;
pub mod intl;
pub mod iterator;
pub mod json;
pub mod map_set;
pub mod math;
pub mod number;
pub mod object;
pub mod order;
pub mod promise;
pub mod proxy;
pub mod regexp;
pub mod string;
pub mod symbol;
pub mod temporal;
pub mod typedarray;

use crate::vm::Vm;

pub fn setup(vm: &mut Vm) {
    object::setup(vm);
    function::setup(vm);
    symbol::setup(vm);
    error::setup(vm);
    iterator::setup(vm);
    array::setup(vm);
    string::setup(vm);
    number::setup(vm);
    bigint_obj::setup(vm);
    math::setup(vm);
    json::setup(vm);
    map_set::setup(vm);
    promise::setup(vm);
    generators::setup(vm);
    regexp::setup(vm);
    date::setup(vm);
    typedarray::setup(vm);
    proxy::setup(vm);
    global::setup(vm);
    disposable::setup(vm);
    intl::setup(vm);
    temporal::setup(vm);
    order::apply_orders(vm);
}
