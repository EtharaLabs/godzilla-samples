// Generator and async generator objects; GeneratorFunction & friends.

use crate::object::*;
use crate::value::*;
use crate::vm::{Completion, JsResult, ResumeMode, Vm};

pub fn setup(vm: &mut Vm) {
    let gp = vm.intr.generator_proto.clone();
    vm.def_method(&gp, "next", 1, gen_next);
    vm.def_method(&gp, "return", 1, gen_return);
    vm.def_method(&gp, "throw", 1, gen_throw);
    vm.set_tag(&gp, "Generator");
    let gfp = vm.intr.generator_function_proto.clone();
    gfp.set_prop(vm.intr.key_prototype.clone(), Value::Obj(gp.clone()), CONFIGURABLE);
    gp.set_prop(vm.intr.key_constructor.clone(), Value::Obj(gfp.clone()), CONFIGURABLE);
    vm.set_tag(&gfp, "GeneratorFunction");
    let gfc = vm.native_fn("GeneratorFunction", 1, generator_function_ctor);
    vm.make_ctor(&gfc);
    gfc.set_prop(vm.intr.key_prototype.clone(), Value::Obj(gfp.clone()), 0);
    gfc.borrow_mut().proto = Some(vm.intr.function_ctor.clone());
    gfp.set_prop(vm.intr.key_constructor.clone(), Value::Obj(gfc), CONFIGURABLE);

    let agp = vm.intr.async_generator_proto.clone();
    vm.def_method(&agp, "next", 1, async_gen_next);
    vm.def_method(&agp, "return", 1, async_gen_return);
    vm.def_method(&agp, "throw", 1, async_gen_throw);
    vm.set_tag(&agp, "AsyncGenerator");
    let agfp = vm.intr.async_generator_function_proto.clone();
    agfp.set_prop(vm.intr.key_prototype.clone(), Value::Obj(agp.clone()), CONFIGURABLE);
    agp.set_prop(vm.intr.key_constructor.clone(), Value::Obj(agfp.clone()), CONFIGURABLE);
    vm.set_tag(&agfp, "AsyncGeneratorFunction");
    let agfc = vm.native_fn("AsyncGeneratorFunction", 1, async_generator_function_ctor);
    vm.make_ctor(&agfc);
    agfc.set_prop(vm.intr.key_prototype.clone(), Value::Obj(agfp.clone()), 0);
    agfc.borrow_mut().proto = Some(vm.intr.function_ctor.clone());
    agfp.set_prop(vm.intr.key_constructor.clone(), Value::Obj(agfc), CONFIGURABLE);

    let afp = vm.intr.async_function_proto.clone();
    vm.set_tag(&afp, "AsyncFunction");
    let afc = vm.native_fn("AsyncFunction", 1, async_function_ctor);
    vm.make_ctor(&afc);
    afc.set_prop(vm.intr.key_prototype.clone(), Value::Obj(afp.clone()), 0);
    afc.borrow_mut().proto = Some(vm.intr.function_ctor.clone());
    afp.set_prop(vm.intr.key_constructor.clone(), Value::Obj(afc), CONFIGURABLE);
}

fn generator_function_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    crate::builtins::function::create_dynamic_function(vm, a.args, "generator", a.new_target.clone())
}
fn async_generator_function_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    crate::builtins::function::create_dynamic_function(vm, a.args, "asyncGenerator", a.new_target.clone())
}
fn async_function_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    crate::builtins::function::create_dynamic_function(vm, a.args, "async", a.new_target.clone())
}

fn this_gen(vm: &mut Vm, a: &Args, m: &str) -> JsResult<Obj> {
    match &a.this {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::Generator(_)) => Ok(o.clone()),
        _ => {
            let _ = m;
            vm.throw_type("Generator method called on a non-generator")
        }
    }
}

fn gen_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let g = this_gen(vm, a, "next")?;
    vm.generator_resume(&g, ResumeMode::Next, a.arg(0))
}
fn gen_return(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let g = this_gen(vm, a, "return")?;
    vm.generator_resume(&g, ResumeMode::Return, a.arg(0))
}
fn gen_throw(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let g = this_gen(vm, a, "throw")?;
    vm.generator_resume(&g, ResumeMode::Throw, a.arg(0))
}

// ---------------- async generators ----------------

fn async_gen_enqueue(vm: &mut Vm, this: &Value, kind: u8, value: Value) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let g = match this {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::AsyncGenerator(_)) => o.clone(),
        _ => {
            let e = vm.make_error("TypeError", "AsyncGenerator method called on an incompatible receiver");
            vm.call(&cap.reject, Value::Undefined, &[e])?;
            return Ok(cap.promise);
        }
    };
    let run = {
        let mut b = g.borrow_mut();
        if let ObjKind::AsyncGenerator(ag) = &mut b.kind {
            ag.queue.push_back(AsyncGenRequest { kind, value, capability: cap.clone() });
            ag.state != GenState::Executing && !ag.awaiting_return
        } else {
            false
        }
    };
    if run {
        drain(vm, &g);
    }
    Ok(cap.promise)
}

fn async_gen_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    async_gen_enqueue(vm, &a.this, 0, a.arg(0))
}
fn async_gen_throw(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    async_gen_enqueue(vm, &a.this, 1, a.arg(0))
}
fn async_gen_return(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    async_gen_enqueue(vm, &a.this, 2, a.arg(0))
}

fn ag_state(g: &Obj) -> (GenState, bool) {
    match &g.borrow().kind {
        ObjKind::AsyncGenerator(ag) => (ag.state, ag.awaiting_return),
        _ => (GenState::Completed, false),
    }
}

fn ag_set_state(g: &Obj, st: GenState) {
    if let ObjKind::AsyncGenerator(ag) = &mut g.borrow_mut().kind {
        ag.state = st;
    }
}

fn complete_step(vm: &mut Vm, g: &Obj, ok: Result<Value, Value>, done: bool) {
    let req = match &mut g.borrow_mut().kind {
        ObjKind::AsyncGenerator(ag) => ag.queue.pop_front(),
        _ => None,
    };
    if let Some(r) = req {
        match ok {
            Ok(v) => {
                let res = vm.iter_result(v, done);
                let _ = vm.call(&r.capability.resolve, Value::Undefined, &[res]);
            }
            Err(e) => {
                let _ = vm.call(&r.capability.reject, Value::Undefined, &[e]);
            }
        }
    }
}

fn drain(vm: &mut Vm, g: &Obj) {
    loop {
        let (state, awaiting) = ag_state(g);
        if state == GenState::Executing || awaiting {
            return;
        }
        let front = match &g.borrow().kind {
            ObjKind::AsyncGenerator(ag) => ag.queue.front().map(|r| (r.kind, r.value.clone())),
            _ => None,
        };
        let (kind, value) = match front {
            Some(x) => x,
            None => return,
        };
        if kind != 0 && (state == GenState::SuspendedStart || state == GenState::Completed) {
            if state == GenState::SuspendedStart {
                ag_set_state(g, GenState::Completed);
                if let ObjKind::AsyncGenerator(ag) = &mut g.borrow_mut().kind {
                    ag.frame = None;
                }
            }
            if kind == 2 {
                if let ObjKind::AsyncGenerator(ag) = &mut g.borrow_mut().kind {
                    ag.awaiting_return = true;
                }
                match crate::builtins::promise::promise_resolve_intrinsic(vm, value) {
                    Ok(p) => {
                        crate::builtins::promise::perform_then_internal(
                            vm,
                            &p,
                            Handler::Native(await_return_fulfilled, Value::Obj(g.clone())),
                            Handler::Native(await_return_rejected, Value::Obj(g.clone())),
                            None,
                        );
                    }
                    Err(e) => {
                        if let ObjKind::AsyncGenerator(ag) = &mut g.borrow_mut().kind {
                            ag.awaiting_return = false;
                        }
                        complete_step(vm, g, Err(e), true);
                        continue;
                    }
                }
                return;
            }
            complete_step(vm, g, Err(value), true);
            continue;
        }
        if state == GenState::Completed {
            complete_step(vm, g, Ok(Value::Undefined), true);
            continue;
        }
        // resume the frame
        let frame = match &mut g.borrow_mut().kind {
            ObjKind::AsyncGenerator(ag) => {
                ag.state = GenState::Executing;
                ag.frame.take()
            }
            _ => None,
        };
        let mut frame = match frame {
            Some(f) => f,
            None => return,
        };
        match kind {
            0 => {
                if state != GenState::SuspendedStart {
                    frame.stack.push(value);
                }
                frame.resume_mode = ResumeMode::Next;
            }
            1 => {
                if frame.yield_star {
                    frame.stack.push(value);
                    frame.resume_mode = ResumeMode::Throw;
                } else {
                    frame.pending_throw = Some(value);
                }
            }
            _ => {
                frame.stack.push(value);
                frame.resume_mode = ResumeMode::Return;
            }
        }
        frame.yield_star = false;
        run_and_handle(vm, g, frame);
    }
}

fn run_and_handle(vm: &mut Vm, g: &Obj, mut frame: Box<crate::vm::Frame>) {
    let r = if vm.enter().is_ok() {
        let r = vm.run_frame(&mut frame);
        vm.depth -= 1;
        r
    } else {
        Err(vm.make_error("RangeError", "Maximum call stack size exceeded"))
    };
    match r {
        Ok(Completion::Await(v)) => {
            if let ObjKind::AsyncGenerator(ag) = &mut g.borrow_mut().kind {
                ag.frame = Some(frame);
            }
            vm.await_value(v, g.clone());
        }
        Ok(Completion::Yield(v)) | Ok(Completion::YieldRaw(v)) => {
            if let ObjKind::AsyncGenerator(ag) = &mut g.borrow_mut().kind {
                ag.frame = Some(frame);
                ag.state = GenState::SuspendedYield;
            }
            complete_step(vm, g, Ok(v), false);
            drain(vm, g);
        }
        Ok(Completion::Return(v)) => {
            ag_set_state(g, GenState::Completed);
            complete_step(vm, g, Ok(v), true);
            drain(vm, g);
        }
        Ok(Completion::GenStart) => {
            if let ObjKind::AsyncGenerator(ag) = &mut g.borrow_mut().kind {
                ag.frame = Some(frame);
                ag.state = GenState::SuspendedStart;
            }
        }
        Err(e) => {
            ag_set_state(g, GenState::Completed);
            complete_step(vm, g, Err(e), true);
            drain(vm, g);
        }
    }
}

pub fn async_gen_resume_from_await(vm: &mut Vm, g: &Obj, mode: ResumeMode, value: Value) {
    let frame = match &mut g.borrow_mut().kind {
        ObjKind::AsyncGenerator(ag) => ag.frame.take(),
        _ => None,
    };
    let mut frame = match frame {
        Some(f) => f,
        None => return,
    };
    match mode {
        ResumeMode::Throw => frame.pending_throw = Some(value),
        _ => frame.stack.push(value),
    }
    run_and_handle(vm, g, frame);
}

fn await_return_fulfilled(vm: &mut Vm, v: Value, g: &Value) -> JsResult<Value> {
    let g = g.as_obj().unwrap().clone();
    if let ObjKind::AsyncGenerator(ag) = &mut g.borrow_mut().kind {
        ag.awaiting_return = false;
        ag.state = GenState::Completed;
    }
    complete_step(vm, &g, Ok(v), true);
    drain(vm, &g);
    Ok(Value::Undefined)
}

fn await_return_rejected(vm: &mut Vm, e: Value, g: &Value) -> JsResult<Value> {
    let g = g.as_obj().unwrap().clone();
    if let ObjKind::AsyncGenerator(ag) = &mut g.borrow_mut().kind {
        ag.awaiting_return = false;
        ag.state = GenState::Completed;
    }
    complete_step(vm, &g, Err(e), true);
    drain(vm, &g);
    Ok(Value::Undefined)
}
