// node:readline and readline/promises, modelled on the reference runtime's small Interface:
// it listens to the input's 'data' / 'end' events, splits the text on "\n" (dropping a trailing
// "\r") and emits 'line' per complete line; a final unterminated line is not emitted. There is
// no prompt()/setPrompt() and the TTY helpers are no-ops returning true.
//
// readline/promises' createInterface replaces `question` with a promise wrapper that (as in the
// reference) re-enters itself instead of the callback API, so the promise never settles and no
// query is written.

use crate::object::*;
use crate::runtime::nodestream::{call_method, closure, emit, getp, host_obj, iter_result, key, make_class, new_instance, resolved, setp, with_host};
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::cell::{Cell, RefCell};

thread_local! {
    static CLASSES: RefCell<Option<(Obj, Obj, Obj)>> = RefCell::new(None);
    static KEYPRESS_SYM: RefCell<Option<Sym>> = RefCell::new(None);
}

/// (Interface ctor, Interface.prototype, Readline ctor)
fn classes(vm: &mut Vm) -> (Obj, Obj, Obj) {
    if let Some(c) = CLASSES.with(|c| c.borrow().clone()) {
        return c;
    }
    let sc = crate::runtime::nodestream::classes(vm);
    let (iface, ip) = make_class(vm, "Interface", 1, iface_ctor, Some((&sc.ee, &sc.ee_proto)));
    let methods: &[(&str, u32, NativeFn)] = &[
        ("_onData", 1, iface_on_data),
        ("question", 2, iface_question),
        ("close", 0, iface_close),
        ("pause", 0, return_this),
        ("resume", 0, return_this),
        ("write", 0, noop),
    ];
    for (n, l, f) in methods {
        vm.def_method(&ip, n, *l, *f);
    }
    let sai = vm.intr.sym_async_iterator.clone();
    vm.def_sym_method(&ip, &sai, "[Symbol.asyncIterator]", 0, iface_async_iterator);

    let (readline, rp) = make_class(vm, "Readline", 1, readline_ctor, None);
    let rmethods: &[(&str, u32, NativeFn)] = &[
        ("_push", 1, rl_push),
        ("clearLine", 1, rl_op),
        ("clearScreenDown", 0, rl_op),
        ("cursorTo", 2, rl_op),
        ("moveCursor", 2, rl_op),
        ("commit", 0, rl_commit),
        ("rollback", 0, rl_rollback),
    ];
    for (n, l, f) in rmethods {
        vm.def_method(&rp, n, *l, *f);
    }
    let c = (iface, ip, readline);
    CLASSES.with(|s| *s.borrow_mut() = Some(c.clone()));
    c
}

fn noop(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Undefined)
}

fn return_this(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(a.this.clone())
}

fn return_true(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(true))
}

// ============================================================================================
// Interface
// ============================================================================================

fn iface_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (_, ip, _) = classes(vm);
    let o = new_instance(vm, a, &ip)?;
    iface_init(vm, &o, &a.arg(0))?;
    Ok(Value::Obj(o))
}

fn iface_init(vm: &mut Vm, o: &Obj, options: &Value) -> JsResult<()> {
    crate::runtime::events::init_emitter(vm, o);
    let this = Value::Obj(o.clone());
    // const opts = options && options.input ? options : { input: options };
    let opts = if options.truthy() && getp(vm, options, "input")?.truthy() { options.clone() } else { Value::Obj(vm.obj_from(vec![("input", options.clone())])) };
    let input = getp(vm, &opts, "input")?;
    setp(vm, &this, "input", input)?;
    let output = getp(vm, &opts, "output")?;
    setp(vm, &this, "output", output)?;
    setp(vm, &this, "_buf", Value::str(""))?;
    setp(vm, &this, "_closed", Value::Bool(false))?;
    let input = getp(vm, &this, "input")?;
    if input.truthy() && getp(vm, &input, "on")?.is_callable() {
        let ondata = closure(vm, "", 1, iface_input_data, vec![this.clone()]);
        call_method(vm, &input, "on", &[Value::str("data"), ondata])?;
        let input = getp(vm, &this, "input")?;
        let onend = closure(vm, "", 0, iface_input_end, vec![this.clone()]);
        call_method(vm, &input, "on", &[Value::str("end"), onend])?;
    }
    Ok(())
}

fn iface_input_data(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    call_method(vm, &a.slot(0), "_onData", &[a.arg(0)])?;
    Ok(Value::Undefined)
}

fn iface_input_end(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    call_method(vm, &a.slot(0), "close", &[])?;
    Ok(Value::Undefined)
}

fn iface_on_data(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let chunk = call_method(vm, &a.arg(0), "toString", &[])?;
    let buf = getp(vm, &this, "_buf")?;
    let joined = vm.op_add(&buf, &chunk)?;
    setp(vm, &this, "_buf", joined)?;
    loop {
        let buf = getp(vm, &this, "_buf")?;
        let s = vm.to_string(&buf)?;
        let units = s.units();
        let idx = match units.iter().position(|&u| u == b'\n' as u16) {
            Some(i) => i,
            None => break,
        };
        let mut line = units[..idx].to_vec();
        if line.last() == Some(&(b'\r' as u16)) {
            line.pop();
        }
        let rest = units[idx + 1..].to_vec();
        setp(vm, &this, "_buf", Value::Str(JsStr::from_units(rest)))?;
        emit(vm, &this, "line", &[Value::Str(JsStr::from_units(line))])?;
    }
    Ok(Value::Undefined)
}

fn iface_question(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let output = getp(vm, &this, "output")?;
    if output.truthy() && getp(vm, &output, "write")?.is_callable() {
        call_method(vm, &output, "write", &[a.arg(0)])?;
    }
    call_method(vm, &this, "once", &[Value::str("line"), a.arg(1)])?;
    Ok(Value::Undefined)
}

fn iface_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if !getp(vm, &this, "_closed")?.truthy() {
        setp(vm, &this, "_closed", Value::Bool(true))?;
        emit(vm, &this, "close", &[])?;
    }
    Ok(Value::Undefined)
}

// --- Interface.prototype[Symbol.asyncIterator] ---

struct LineIter {
    pending: RefCell<std::collections::VecDeque<Value>>,
    done: Cell<bool>,
    waiting: RefCell<Option<Value>>,
}

fn li<R>(v: &Value, f: impl FnOnce(&LineIter) -> R) -> Option<R> {
    with_host::<LineIter, R>(v, f)
}

fn li_on_line(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = a.slot(0);
    let line = a.arg(0);
    let w = li(&st, |s| s.waiting.borrow_mut().take()).flatten();
    match w {
        Some(resolve) => {
            let r = iter_result(vm, line, false);
            vm.call(&resolve, Value::Undefined, &[r])?;
        }
        None => {
            li(&st, |s| s.pending.borrow_mut().push_back(line));
        }
    }
    Ok(Value::Undefined)
}

fn li_on_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = a.slot(0);
    li(&st, |s| s.done.set(true));
    let w = li(&st, |s| s.waiting.borrow_mut().take()).flatten();
    if let Some(resolve) = w {
        let r = iter_result(vm, Value::Undefined, true);
        vm.call(&resolve, Value::Undefined, &[r])?;
    }
    Ok(Value::Undefined)
}

fn li_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = a.slot(0);
    let cap = vm.new_promise_capability_intrinsic();
    if let Some(v) = li(&st, |s| s.pending.borrow_mut().pop_front()).flatten() {
        let r = iter_result(vm, v, false);
        vm.call(&cap.resolve, Value::Undefined, &[r])?;
    } else if li(&st, |s| s.done.get()).unwrap_or(false) {
        let r = iter_result(vm, Value::Undefined, true);
        vm.call(&cap.resolve, Value::Undefined, &[r])?;
    } else {
        li(&st, |s| *s.waiting.borrow_mut() = Some(cap.resolve.clone()));
    }
    Ok(cap.promise)
}

fn iface_async_iterator(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let st = host_obj(LineIter { pending: RefCell::new(Default::default()), done: Cell::new(false), waiting: RefCell::new(None) });
    let online = closure(vm, "", 1, li_on_line, vec![st.clone()]);
    call_method(vm, &this, "on", &[Value::str("line"), online])?;
    let onclose = closure(vm, "", 0, li_on_close, vec![st.clone()]);
    call_method(vm, &this, "on", &[Value::str("close"), onclose])?;
    let it = vm.new_object();
    let next = vm.native_closure("next", 0, li_next, vec![st]);
    it.set_prop(key("next"), Value::Obj(next), WEC);
    let ai = vm.native_fn("[Symbol.asyncIterator]", 0, return_this);
    it.set_prop(PropKey::Sym(vm.intr.sym_async_iterator.clone()), Value::Obj(ai), WEC);
    Ok(Value::Obj(it))
}

// ============================================================================================
// createInterface / emitKeypressEvents
// ============================================================================================

fn create_interface(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (iface, _, _) = classes(vm);
    vm.construct(&Value::Obj(iface), &[a.arg(0)], None)
}

/// readline/promises: the question wrapper never reaches the callback API (see header).
fn question_promise(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    Ok(cap.promise)
}

fn create_interface_promises(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (iface, _, _) = classes(vm);
    let rl = vm.construct(&Value::Obj(iface), &[a.arg(0)], None)?;
    let q = vm.native_fn("", 1, question_promise);
    setp(vm, &rl, "question", Value::Obj(q))?;
    Ok(rl)
}

fn keypress_sym() -> Sym {
    if let Some(s) = KEYPRESS_SYM.with(|k| k.borrow().clone()) {
        return s;
    }
    let s = Sym::new(Some(JsStr::from_str("readline.keypressWired")));
    KEYPRESS_SYM.with(|k| *k.borrow_mut() = Some(s.clone()));
    s
}

fn emit_keypress_events(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let stream = a.arg(0);
    if !stream.truthy() {
        return Ok(Value::Undefined);
    }
    let k = PropKey::Sym(keypress_sym());
    if vm.get_prop_of(&stream, &k)?.truthy() {
        return Ok(Value::Undefined);
    }
    vm.set_prop_of(&stream, k, Value::Bool(true), true)?;
    let ondata = closure(vm, "", 1, keypress_data, vec![stream.clone()]);
    call_method(vm, &stream, "on", &[Value::str("data"), ondata])?;
    Ok(Value::Undefined)
}

fn keypress_data(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let stream = a.slot(0);
    let s = call_method(vm, &a.arg(0), "toString", &[])?;
    let s = vm.to_string(&s)?;
    let text = s.to_rust_string();
    let units = s.units().to_vec();
    // iterate by code points (lone surrogates come through as single units)
    let mut i = 0;
    let _ = text;
    while i < units.len() {
        let u = units[i];
        let len = if (0xD800..0xDC00).contains(&u) && i + 1 < units.len() && (0xDC00..0xE000).contains(&units[i + 1]) { 2 } else { 1 };
        let ch_units = units[i..i + len].to_vec();
        i += len;
        let ch = JsStr::from_units(ch_units.clone());
        let key_obj = vm.new_object();
        key_obj.set_prop(key("sequence"), Value::Str(ch.clone()), WEC);
        key_obj.set_prop(key("name"), Value::Undefined, WEC);
        key_obj.set_prop(key("ctrl"), Value::Bool(false), WEC);
        key_obj.set_prop(key("meta"), Value::Bool(false), WEC);
        key_obj.set_prop(key("shift"), Value::Bool(false), WEC);
        let first = ch_units[0];
        let name: Option<Value> = if first == b'\r' as u16 || first == b'\n' as u16 {
            Some(Value::str("return"))
        } else if first == b'\t' as u16 {
            Some(Value::str("tab"))
        } else if first == 0x7f {
            Some(Value::str("backspace"))
        } else if first >= 0x20 {
            let lower = call_method(vm, &Value::Str(ch.clone()), "toLowerCase", &[])?;
            Some(lower)
        } else {
            None
        };
        if let Some(n) = name {
            key_obj.set_prop(key("name"), n, WEC);
        }
        emit(vm, &stream, "keypress", &[Value::Str(ch), Value::Obj(key_obj)])?;
    }
    Ok(Value::Undefined)
}

// ============================================================================================
// readline/promises Readline
// ============================================================================================

fn readline_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (_, _, rc) = classes(vm);
    let fb = match rc.get_own_str("prototype") {
        Some(Value::Obj(p)) => p,
        _ => vm.intr.object_proto.clone(),
    };
    let o = new_instance(vm, a, &fb)?;
    let this = Value::Obj(o);
    let options = if a.arg(1).is_undefined() { Value::Obj(vm.new_object()) } else { a.arg(1) };
    setp(vm, &this, "_stream", a.arg(0))?;
    let ac = getp(vm, &options, "autoCommit")?.truthy();
    setp(vm, &this, "_autoCommit", Value::Bool(ac))?;
    let ops = Value::Obj(vm.new_array(Vec::new()));
    setp(vm, &this, "_ops", ops)?;
    Ok(this)
}

fn rl_push(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if getp(vm, &this, "_autoCommit")?.truthy() {
        return call_method(vm, &this, "commit", &[]);
    }
    let ops = getp(vm, &this, "_ops")?;
    call_method(vm, &ops, "push", &[a.arg(0)])?;
    Ok(this)
}

fn rl_op(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let op = vm.native_fn("", 0, noop);
    call_method(vm, &a.this, "_push", &[Value::Obj(op)])
}

fn rl_commit(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let ops = getp(vm, &this, "_ops")?;
    let list = crate::builtins::array::array_like_to_vec(vm, &ops)?;
    for op in list {
        vm.call(&op, Value::Undefined, &[])?;
    }
    let ops = Value::Obj(vm.new_array(Vec::new()));
    setp(vm, &this, "_ops", ops)?;
    Ok(resolved(vm, Value::Undefined))
}

fn rl_rollback(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ops = Value::Obj(vm.new_array(Vec::new()));
    setp(vm, &a.this, "_ops", ops)?;
    Ok(resolved(vm, Value::Undefined))
}

// ============================================================================================
// modules
// ============================================================================================

#[allow(unused_variables)]
#[allow(dead_code)]
pub fn setup(vm: &mut Vm) {}

fn promises_module(vm: &mut Vm) -> Value {
    if let Some(v) = vm.host.builtin_cache.get("readline/promises") {
        return v.clone();
    }
    let (iface, _, readline) = classes(vm);
    let o = vm.new_object();
    let ci = vm.native_fn("createInterface", 1, create_interface_promises);
    o.set_prop(key("createInterface"), Value::Obj(ci), WEC);
    o.set_prop(key("Interface"), Value::Obj(iface), WEC);
    o.set_prop(key("Readline"), Value::Obj(readline), WEC);
    let v = Value::Obj(o);
    vm.host.builtin_cache.insert("readline/promises".to_string(), v.clone());
    v
}

pub fn create_module(vm: &mut Vm, name: &str) -> Value {
    if name == "readline/promises" {
        return promises_module(vm);
    }
    let (iface, _, _) = classes(vm);
    let o = vm.new_object();
    let ci = vm.native_fn("createInterface", 1, create_interface);
    o.set_prop(key("createInterface"), Value::Obj(ci), WEC);
    o.set_prop(key("Interface"), Value::Obj(iface), WEC);
    for n in ["clearLine", "clearScreenDown", "cursorTo", "moveCursor"] {
        let f = vm.native_fn(n, 0, return_true);
        o.set_prop(key(n), Value::Obj(f), WEC);
    }
    let ek = vm.native_fn("emitKeypressEvents", 2, emit_keypress_events);
    o.set_prop(key("emitKeypressEvents"), Value::Obj(ek), WEC);
    let p = promises_module(vm);
    o.set_prop(key("promises"), p, WEC);
    Value::Obj(o)
}
