// Realm setup: intrinsic objects and helpers for defining builtins.

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub struct Intrinsics {
    pub object_proto: Obj,
    pub function_proto: Obj,
    pub array_proto: Obj,
    pub string_proto: Obj,
    pub number_proto: Obj,
    pub boolean_proto: Obj,
    pub symbol_proto: Obj,
    pub bigint_proto: Obj,
    pub error_proto: Obj,
    pub type_error_proto: Obj,
    pub range_error_proto: Obj,
    pub reference_error_proto: Obj,
    pub syntax_error_proto: Obj,
    pub uri_error_proto: Obj,
    pub eval_error_proto: Obj,
    pub aggregate_error_proto: Obj,
    pub suppressed_error_proto: Obj,
    pub iterator_proto: Obj,
    pub async_iterator_proto: Obj,
    pub array_iterator_proto: Obj,
    pub map_iterator_proto: Obj,
    pub set_iterator_proto: Obj,
    pub string_iterator_proto: Obj,
    pub regexp_string_iterator_proto: Obj,
    pub iterator_helper_proto: Obj,
    pub wrap_iterator_proto: Obj,
    pub async_from_sync_proto: Obj,
    pub generator_proto: Obj,
    pub generator_function_proto: Obj,
    pub async_generator_proto: Obj,
    pub async_generator_function_proto: Obj,
    pub async_function_proto: Obj,
    pub promise_proto: Obj,
    pub promise_ctor: Obj,
    pub regexp_proto: Obj,
    pub date_proto: Obj,
    pub map_proto: Obj,
    pub set_proto: Obj,
    pub weakmap_proto: Obj,
    pub weakset_proto: Obj,
    pub weakref_proto: Obj,
    pub finreg_proto: Obj,
    pub array_buffer_proto: Obj,
    pub shared_array_buffer_proto: Obj,
    pub data_view_proto: Obj,
    pub typed_array_proto: Obj,
    pub typed_array_ctor: Obj,
    pub ta_protos: Vec<Obj>,
    pub ta_ctors: Vec<Obj>,
    pub array_ctor: Obj,
    pub object_ctor: Obj,
    pub function_ctor: Obj,
    pub array_buffer_ctor: Obj,
    pub eval_fn: Obj,
    pub throw_type_error: Obj,
    pub array_values: Value,
    pub array_iter_next: Obj,
    pub function_has_instance: Obj,
    pub disposable_stack_proto: Obj,
    pub async_disposable_stack_proto: Obj,
    pub sym_iterator: Sym,
    pub sym_async_iterator: Sym,
    pub sym_has_instance: Sym,
    pub sym_to_primitive: Sym,
    pub sym_to_string_tag: Sym,
    pub sym_unscopables: Sym,
    pub sym_species: Sym,
    pub sym_is_concat_spreadable: Sym,
    pub sym_match: Sym,
    pub sym_match_all: Sym,
    pub sym_replace: Sym,
    pub sym_search: Sym,
    pub sym_split: Sym,
    pub sym_dispose: Sym,
    pub sym_async_dispose: Sym,
    pub stack_sym: Sym,
    pub key_length: PropKey,
    pub key_name: PropKey,
    pub key_prototype: PropKey,
    pub key_constructor: PropKey,
    pub key_value: PropKey,
    pub key_done: PropKey,
    pub key_next: PropKey,
    pub key_to_string: PropKey,
    pub key_value_of: PropKey,
    pub key_message: PropKey,
    pub key_then: PropKey,
    pub str_undefined: JsStr,
    pub str_null: JsStr,
    pub str_true: JsStr,
    pub str_false: JsStr,
}

fn blank(proto: Option<&Obj>) -> Obj {
    Obj::new(proto.cloned(), ObjKind::Ordinary)
}

fn wk(name: &str) -> Sym {
    Sym::new(Some(JsStr::from_str(&format!("Symbol.{}", name))))
}

pub fn dummy_native(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Undefined)
}

impl Intrinsics {
    pub fn new() -> Intrinsics {
        let object_proto = Obj::new(None, ObjKind::Ordinary);
        let function_proto = Obj::with_class(
            Some(object_proto.clone()),
            ObjKind::Native(NativeFunc { f: dummy_native, slots: Vec::new(), is_ctor: false, name: "" }),
            "Function",
        );
        let op = Some(&object_proto);
        let array_proto = Obj::with_class(Some(object_proto.clone()), ObjKind::Array(new_array_data(Vec::new())), "Array");
        let iterator_proto = blank(op);
        let async_iterator_proto = blank(op);
        let error_proto = blank(op);
        let ep = Some(&error_proto);
        let generator_proto = blank(Some(&iterator_proto));
        let async_generator_proto = blank(Some(&async_iterator_proto));
        let typed_array_proto = blank(op);
        let fp = Some(&function_proto);
        let dummy_fn = || Obj::new(Some(function_proto.clone()), ObjKind::Native(NativeFunc { f: dummy_native, slots: Vec::new(), is_ctor: false, name: "" }));
        Intrinsics {
            string_proto: Obj::with_class(Some(object_proto.clone()), ObjKind::String(JsStr::empty()), "String"),
            number_proto: Obj::with_class(Some(object_proto.clone()), ObjKind::Number(0.0), "Number"),
            boolean_proto: Obj::with_class(Some(object_proto.clone()), ObjKind::Boolean(false), "Boolean"),
            symbol_proto: blank(op),
            bigint_proto: blank(op),
            type_error_proto: blank(ep),
            range_error_proto: blank(ep),
            reference_error_proto: blank(ep),
            syntax_error_proto: blank(ep),
            uri_error_proto: blank(ep),
            eval_error_proto: blank(ep),
            aggregate_error_proto: blank(ep),
            suppressed_error_proto: blank(ep),
            array_iterator_proto: blank(Some(&iterator_proto)),
            map_iterator_proto: blank(Some(&iterator_proto)),
            set_iterator_proto: blank(Some(&iterator_proto)),
            string_iterator_proto: blank(Some(&iterator_proto)),
            regexp_string_iterator_proto: blank(Some(&iterator_proto)),
            iterator_helper_proto: blank(Some(&iterator_proto)),
            wrap_iterator_proto: blank(Some(&iterator_proto)),
            async_from_sync_proto: blank(Some(&async_iterator_proto)),
            generator_function_proto: blank(fp),
            async_generator_function_proto: blank(fp),
            async_function_proto: blank(fp),
            promise_proto: blank(op),
            promise_ctor: dummy_fn(),
            regexp_proto: blank(op),
            date_proto: blank(op),
            map_proto: blank(op),
            set_proto: blank(op),
            weakmap_proto: blank(op),
            weakset_proto: blank(op),
            weakref_proto: blank(op),
            finreg_proto: blank(op),
            array_buffer_proto: blank(op),
            shared_array_buffer_proto: blank(op),
            data_view_proto: blank(op),
            typed_array_ctor: dummy_fn(),
            ta_protos: Vec::new(),
            ta_ctors: Vec::new(),
            array_ctor: dummy_fn(),
            object_ctor: dummy_fn(),
            function_ctor: dummy_fn(),
            array_buffer_ctor: dummy_fn(),
            eval_fn: dummy_fn(),
            throw_type_error: dummy_fn(),
            array_values: Value::Undefined,
            array_iter_next: dummy_fn(),
            function_has_instance: dummy_fn(),
            disposable_stack_proto: blank(op),
            async_disposable_stack_proto: blank(op),
            sym_iterator: wk("iterator"),
            sym_async_iterator: wk("asyncIterator"),
            sym_has_instance: wk("hasInstance"),
            sym_to_primitive: wk("toPrimitive"),
            sym_to_string_tag: wk("toStringTag"),
            sym_unscopables: wk("unscopables"),
            sym_species: wk("species"),
            sym_is_concat_spreadable: wk("isConcatSpreadable"),
            sym_match: wk("match"),
            sym_match_all: wk("matchAll"),
            sym_replace: wk("replace"),
            sym_search: wk("search"),
            sym_split: wk("split"),
            sym_dispose: wk("dispose"),
            sym_async_dispose: wk("asyncDispose"),
            stack_sym: Sym::new_private(JsStr::from_str("[[stack]]")),
            key_length: PropKey::from_str("length"),
            key_name: PropKey::from_str("name"),
            key_prototype: PropKey::from_str("prototype"),
            key_constructor: PropKey::from_str("constructor"),
            key_value: PropKey::from_str("value"),
            key_done: PropKey::from_str("done"),
            key_next: PropKey::from_str("next"),
            key_to_string: PropKey::from_str("toString"),
            key_value_of: PropKey::from_str("valueOf"),
            key_message: PropKey::from_str("message"),
            key_then: PropKey::from_str("then"),
            str_undefined: JsStr::from_str("undefined"),
            str_null: JsStr::from_str("null"),
            str_true: JsStr::from_str("true"),
            str_false: JsStr::from_str("false"),
            object_proto,
            function_proto,
            array_proto,
            iterator_proto,
            async_iterator_proto,
            error_proto,
            generator_proto,
            async_generator_proto,
            typed_array_proto,
        }
    }
}

impl Vm {
    /// Create a native function object.
    pub fn native_fn(&self, name: &str, len: u32, f: NativeFn) -> Obj {
        let o = Obj::with_class(
            Some(self.intr.function_proto.clone()),
            ObjKind::Native(NativeFunc { f, slots: Vec::new(), is_ctor: false, name: "" }),
            "Function",
        );
        {
            let mut b = o.borrow_mut();
            b.props.insert(self.intr.key_length.clone(), Prop::Data { value: Value::Num(len as f64), flags: CONFIGURABLE });
            b.props.insert(self.intr.key_name.clone(), Prop::Data { value: Value::str(name), flags: CONFIGURABLE });
        }
        o
    }

    /// Native function carrying captured values in slots.
    pub fn native_closure(&self, name: &str, len: u32, f: NativeFn, slots: Vec<Value>) -> Obj {
        let o = self.native_fn(name, len, f);
        if let ObjKind::Native(n) = &mut o.borrow_mut().kind {
            n.slots = slots;
        }
        o
    }

    /// Create a constructor function linked with `proto`.
    pub fn native_ctor(&self, name: &str, len: u32, f: NativeFn, proto: &Obj) -> Obj {
        let o = self.native_fn(name, len, f);
        if let ObjKind::Native(n) = &mut o.borrow_mut().kind {
            n.is_ctor = true;
        }
        o.set_prop(self.intr.key_prototype.clone(), Value::Obj(proto.clone()), 0);
        proto.set_prop(self.intr.key_constructor.clone(), Value::Obj(o.clone()), WC);
        o
    }

    pub fn make_ctor(&self, o: &Obj) {
        if let ObjKind::Native(n) = &mut o.borrow_mut().kind {
            n.is_ctor = true;
        }
    }

    pub fn def_method(&self, target: &Obj, name: &str, len: u32, f: NativeFn) -> Obj {
        let func = self.native_fn(name, len, f);
        target.set_prop(PropKey::from_str(name), Value::Obj(func.clone()), WC);
        func
    }

    pub fn def_sym_method(&self, target: &Obj, sym: &Sym, name: &str, len: u32, f: NativeFn) -> Obj {
        let func = self.native_fn(name, len, f);
        target.set_prop(PropKey::Sym(sym.clone()), Value::Obj(func.clone()), WC);
        func
    }

    pub fn def_getter(&self, target: &Obj, name: &str, f: NativeFn) -> Obj {
        let g = self.native_fn(&format!("get {}", name), 0, f);
        target.set_accessor(PropKey::from_str(name), Some(g.clone()), None, CONFIGURABLE);
        g
    }

    pub fn def_sym_getter(&self, target: &Obj, sym: &Sym, name: &str, f: NativeFn) -> Obj {
        let g = self.native_fn(&format!("get {}", name), 0, f);
        target.set_accessor(PropKey::Sym(sym.clone()), Some(g.clone()), None, CONFIGURABLE);
        g
    }

    pub fn def_accessor(&self, target: &Obj, name: &str, getter: NativeFn, setter: NativeFn) {
        let g = self.native_fn(&format!("get {}", name), 0, getter);
        let s = self.native_fn(&format!("set {}", name), 1, setter);
        target.set_accessor(PropKey::from_str(name), Some(g), Some(s), CONFIGURABLE);
    }

    pub fn def_value(&self, target: &Obj, name: &str, v: Value, flags: u8) {
        target.set_prop(PropKey::from_str(name), v, flags);
    }

    pub fn set_tag(&self, target: &Obj, tag: &str) {
        target.set_prop(PropKey::Sym(self.intr.sym_to_string_tag.clone()), Value::str(tag), CONFIGURABLE);
    }

    pub fn def_global(&self, name: &str, v: Value) {
        self.global.set_prop(PropKey::from_str(name), v, WC);
    }

    pub fn new_object_with_proto(&self, proto: Option<Obj>) -> Obj {
        Obj::new(proto, ObjKind::Ordinary)
    }

    /// create a plain object from (key, value) pairs
    pub fn obj_from(&self, pairs: Vec<(&str, Value)>) -> Obj {
        let o = self.new_object();
        for (k, v) in pairs {
            o.set_prop(PropKey::from_str(k), v, WEC);
        }
        o
    }
}

pub fn this_obj(vm: &mut Vm, a: &Args, method: &str) -> JsResult<Obj> {
    match &a.this {
        Value::Obj(o) => Ok(o.clone()),
        Value::Undefined | Value::Null => vm.throw_type(format!("{} called on null or undefined", method)),
        other => vm.to_object(other),
    }
}
