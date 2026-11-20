// Symbol constructor and prototype.

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let proto = vm.intr.symbol_proto.clone();
    let ctor = vm.native_ctor("Symbol", 0, symbol_ctor, &proto);
    let wks = [
        ("asyncIterator", vm.intr.sym_async_iterator.clone()),
        ("hasInstance", vm.intr.sym_has_instance.clone()),
        ("isConcatSpreadable", vm.intr.sym_is_concat_spreadable.clone()),
        ("iterator", vm.intr.sym_iterator.clone()),
        ("match", vm.intr.sym_match.clone()),
        ("matchAll", vm.intr.sym_match_all.clone()),
        ("replace", vm.intr.sym_replace.clone()),
        ("search", vm.intr.sym_search.clone()),
        ("species", vm.intr.sym_species.clone()),
        ("split", vm.intr.sym_split.clone()),
        ("toPrimitive", vm.intr.sym_to_primitive.clone()),
        ("toStringTag", vm.intr.sym_to_string_tag.clone()),
        ("unscopables", vm.intr.sym_unscopables.clone()),
        ("dispose", vm.intr.sym_dispose.clone()),
        ("asyncDispose", vm.intr.sym_async_dispose.clone()),
    ];
    for (n, s) in wks {
        ctor.set_prop(PropKey::from_str(n), Value::Sym(s), 0);
    }
    vm.def_method(&ctor, "for", 1, symbol_for);
    vm.def_method(&ctor, "keyFor", 1, symbol_key_for);
    vm.def_method(&proto, "toString", 0, to_string);
    vm.def_method(&proto, "valueOf", 0, value_of);
    vm.def_getter(&proto, "description", description);
    let tp = vm.native_fn("[Symbol.toPrimitive]", 1, value_of);
    proto.set_prop(PropKey::Sym(vm.intr.sym_to_primitive.clone()), Value::Obj(tp), CONFIGURABLE);
    vm.set_tag(&proto, "Symbol");
    vm.def_global("Symbol", Value::Obj(ctor));
}

fn symbol_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_some() {
        return vm.throw_type("Symbol is not a constructor");
    }
    let d = a.arg(0);
    let desc = if d.is_undefined() { None } else { Some(vm.to_string(&d)?) };
    Ok(Value::Sym(Sym::new(desc)))
}

fn symbol_for(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let k = vm.to_string(&a.arg(0))?;
    if let Some(s) = vm.symbol_registry.get(&k) {
        return Ok(Value::Sym(s.clone()));
    }
    let s = Sym(std::rc::Rc::new(SymbolData { description: Some(k.clone()), registered: true, private: false }));
    vm.symbol_registry.insert(k, s.clone());
    Ok(Value::Sym(s))
}

fn symbol_key_for(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match a.arg(0) {
        Value::Sym(s) => {
            if s.0.registered {
                Ok(s.0.description.clone().map(Value::Str).unwrap_or(Value::Undefined))
            } else {
                Ok(Value::Undefined)
            }
        }
        v => {
            let d = vm.display_for_error(&v);
            vm.throw_type(format!("{} is not a symbol", d))
        }
    }
}

fn this_symbol(vm: &mut Vm, v: &Value) -> JsResult<Sym> {
    match v {
        Value::Sym(s) => Ok(s.clone()),
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Symbol(s) => Ok(s.clone()),
            _ => Err(vm.make_error("TypeError", "Symbol method called on incompatible receiver")),
        },
        _ => vm.throw_type("Symbol method called on incompatible receiver"),
    }
}

fn to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_symbol(vm, &a.this)?;
    Ok(Value::str(&s.descriptive_string()))
}

fn value_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Sym(this_symbol(vm, &a.this)?))
}

fn description(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_symbol(vm, &a.this)?;
    Ok(s.0.description.clone().map(Value::Str).unwrap_or(Value::Undefined))
}
