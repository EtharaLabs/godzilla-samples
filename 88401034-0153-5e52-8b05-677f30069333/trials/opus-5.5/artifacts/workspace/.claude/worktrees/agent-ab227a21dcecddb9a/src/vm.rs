// The bytecode interpreter: frames, environments, calls, and the main dispatch loop.

use crate::bytecode::*;
use crate::object::*;
use crate::realm::Intrinsics;
use crate::value::*;
use std::cell::RefCell;
use std::collections::VecDeque;
use std::rc::Rc;

pub type JsResult<T> = Result<T, Value>;

pub const MAX_DEPTH: usize = 1500;

pub struct EnvData {
    pub vars: RefCell<Vec<Value>>,
    pub parent: Option<Env>,
    pub info: Option<Rc<ScopeInfo>>,
    pub with_obj: Option<Obj>,
    pub extra: RefCell<Vec<(JsStr, Value)>>,
}

#[derive(Clone)]
pub struct Env(pub Rc<EnvData>);

impl Env {
    pub fn new(info: Rc<ScopeInfo>, parent: Option<Env>) -> Env {
        let vals = info
            .kinds
            .iter()
            .map(|k| match k {
                BindKind::Let | BindKind::Const | BindKind::Class => Value::Empty,
                _ => Value::Undefined,
            })
            .collect();
        Env(Rc::new(EnvData { vars: RefCell::new(vals), parent, info: Some(info), with_obj: None, extra: RefCell::new(Vec::new()) }))
    }
    pub fn new_with(obj: Obj, parent: Option<Env>) -> Env {
        Env(Rc::new(EnvData { vars: RefCell::new(Vec::new()), parent, info: None, with_obj: Some(obj), extra: RefCell::new(Vec::new()) }))
    }
    pub fn new_empty(parent: Option<Env>) -> Env {
        Env(Rc::new(EnvData { vars: RefCell::new(Vec::new()), parent, info: None, with_obj: None, extra: RefCell::new(Vec::new()) }))
    }
    #[inline]
    pub fn ancestor(&self, depth: u16) -> &Env {
        let mut e = self;
        for _ in 0..depth {
            e = e.0.parent.as_ref().expect("env depth");
        }
        e
    }
}

#[derive(Clone)]
pub struct TryHandler {
    pub pc: u32,
    pub sp: u32,
    pub env: Option<Env>,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ResumeMode {
    Next,
    Throw,
    Return,
}

pub struct Frame {
    pub code: Rc<FunctionCode>,
    pub pc: usize,
    pub stack: Vec<Value>,
    pub locals: Vec<Value>,
    pub env: Option<Env>,
    pub this: Value,
    pub func: Option<Obj>,
    pub new_target: Value,
    pub args: Vec<Value>,
    pub handlers: Vec<TryHandler>,
    pub home: Option<Obj>,
    pub resume_mode: ResumeMode,
    pub pending_throw: Option<Value>,
    pub module: Option<Rc<crate::modules::ModuleRecord>>,
    pub disposables: Vec<(Value, Value, bool)>,
    /// is this frame executing in a generator/async context (for traces)
    pub is_coroutine: bool,
}

pub enum Completion {
    Return(Value),
    Yield(Value),
    /// yield* delegation in a sync generator: the inner result object is passed through
    YieldRaw(Value),
    Await(Value),
    GenStart,
}

pub enum Job {
    Reaction(Reaction, Value),
    ResolveThenable(Obj, Value, Value),
    Callback(Value, Vec<Value>),
    Native(fn(&mut Vm, Value) -> JsResult<()>, Value),
}

pub struct TraceEntry {
    pub name: JsStr,
}

pub struct GlobalLex {
    pub value: Value,
    pub mutable: bool,
}

pub struct Vm {
    pub intr: Intrinsics,
    pub global: Obj,
    pub global_lex: FxHashMap<JsStr, GlobalLex>,
    pub jobs: VecDeque<Job>,
    pub depth: usize,
    pub trace: Vec<TraceEntry>,
    pub symbol_registry: FxHashMap<JsStr, Sym>,
    pub template_cache: FxHashMap<usize, Obj>,
    pub promise_counter: u64,
    pub unhandled: Vec<Obj>,
    pub host: crate::runtime::Host,
    pub exit_code: i32,
    pub depth_offset: usize,
}

#[inline]
fn pop(stack: &mut Vec<Value>) -> Value {
    stack.pop().expect("stack underflow")
}

impl Vm {
    // ---------------- errors ----------------

    pub fn make_error(&mut self, kind: &str, msg: &str) -> Value {
        let proto = match kind {
            "TypeError" => self.intr.type_error_proto.clone(),
            "RangeError" => self.intr.range_error_proto.clone(),
            "ReferenceError" => self.intr.reference_error_proto.clone(),
            "SyntaxError" => self.intr.syntax_error_proto.clone(),
            "URIError" => self.intr.uri_error_proto.clone(),
            "EvalError" => self.intr.eval_error_proto.clone(),
            _ => self.intr.error_proto.clone(),
        };
        let o = Obj::with_class(Some(proto), ObjKind::Error, "Error");
        o.set_prop(PropKey::from_str("message"), Value::str(msg), WC);
        self.attach_stack(&o, kind, msg);
        Value::Obj(o)
    }

    /// Capture the current call frames on an error object; the header is computed lazily.
    pub fn attach_stack(&mut self, o: &Obj, _name: &str, _msg: &str) {
        let s = self.frames_string();
        o.borrow_mut().props.insert(PropKey::Sym(self.intr.stack_sym.clone()), Prop::Data { value: Value::Str(JsStr::from_str(&s)), flags: WC });
    }

    pub fn frames_string(&self) -> String {
        let mut s = String::new();
        for e in self.trace.iter().rev() {
            s.push_str("\n    at ");
            s.push_str(&e.name.to_rust_string());
        }
        s
    }

    pub fn throw_type<T>(&mut self, msg: impl AsRef<str>) -> JsResult<T> {
        Err(self.make_error("TypeError", msg.as_ref()))
    }
    pub fn throw_range<T>(&mut self, msg: impl AsRef<str>) -> JsResult<T> {
        Err(self.make_error("RangeError", msg.as_ref()))
    }
    pub fn throw_ref<T>(&mut self, msg: impl AsRef<str>) -> JsResult<T> {
        Err(self.make_error("ReferenceError", msg.as_ref()))
    }
    pub fn throw_syntax<T>(&mut self, msg: impl AsRef<str>) -> JsResult<T> {
        Err(self.make_error("SyntaxError", msg.as_ref()))
    }
    pub fn throw_error<T>(&mut self, kind: &str, msg: impl AsRef<str>) -> JsResult<T> {
        Err(self.make_error(kind, msg.as_ref()))
    }

    // ---------------- calls ----------------

    pub fn call(&mut self, f: &Value, this: Value, args: &[Value]) -> JsResult<Value> {
        match f {
            Value::Obj(o) => self.call_obj(o, this, args),
            _ => {
                let d = self.describe_for_call(f);
                self.throw_type(format!("{} is not a function", d))
            }
        }
    }

    pub fn describe_for_call(&self, v: &Value) -> String {
        match v {
            Value::Undefined => "undefined".into(),
            Value::Null => "null".into(),
            Value::Bool(_) => "boolean".into(),
            Value::Num(_) => "number".into(),
            Value::Str(_) => "string".into(),
            Value::Sym(_) => "symbol".into(),
            Value::BigInt(_) => "bigint".into(),
            Value::Obj(_) => "object".into(),
            Value::Empty => "undefined".into(),
        }
    }

    pub fn enter(&mut self) -> JsResult<()> {
        if self.depth + self.depth_offset >= MAX_DEPTH {
            return self.throw_range("Maximum call stack size exceeded");
        }
        self.depth += 1;
        Ok(())
    }

    pub fn call_obj(&mut self, o: &Obj, this: Value, args: &[Value]) -> JsResult<Value> {
        enum K {
            Closure(Rc<FunctionCode>, Option<Env>, Option<Obj>, bool),
            Native(NativeFn),
            Bound(Obj, Value, Vec<Value>),
            Proxy,
            NotCallable,
        }
        let k = {
            let b = o.borrow();
            match &b.kind {
                ObjKind::Closure(c) => K::Closure(c.code.clone(), c.env.clone(), c.home_object.clone(), c.is_class_ctor),
                ObjKind::Native(n) => K::Native(n.f),
                ObjKind::Bound(bf) => K::Bound(bf.target.clone(), bf.this.clone(), bf.args.clone()),
                ObjKind::Proxy(p) if p.callable => K::Proxy,
                _ => K::NotCallable,
            }
        };
        match k {
            K::Closure(code, env, home, is_class) => {
                if is_class {
                    return self.throw_type("Class constructor cannot be invoked without 'new'");
                }
                self.call_closure(o, code, env, home, this, args, Value::Undefined)
            }
            K::Native(f) => {
                self.enter()?;
                let r = f(self, &Args { this, args, callee: o, new_target: None });
                self.depth -= 1;
                r
            }
            K::Bound(target, bthis, bargs) => {
                let mut all = bargs;
                all.extend_from_slice(args);
                self.enter()?;
                let r = self.call_obj(&target, bthis, &all);
                self.depth -= 1;
                r
            }
            K::Proxy => crate::builtins::proxy::proxy_call(self, o, this, args),
            K::NotCallable => self.throw_type("object is not a function"),
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub fn call_closure(
        &mut self,
        f: &Obj,
        code: Rc<FunctionCode>,
        env: Option<Env>,
        home: Option<Obj>,
        this: Value,
        args: &[Value],
        new_target: Value,
    ) -> JsResult<Value> {
        let this = if code.strict || code.is_arrow {
            this
        } else {
            match this {
                Value::Undefined | Value::Null => Value::Obj(self.global.clone()),
                Value::Obj(_) => this,
                other => Value::Obj(self.to_object(&other)?),
            }
        };
        let mut frame = Frame::new(code.clone(), env, this, Some(f.clone()), new_target, args.to_vec(), home);
        if code.is_generator {
            return self.start_generator(f, frame);
        }
        if code.is_async {
            return Ok(self.start_async(frame));
        }
        self.enter()?;
        self.trace.push(TraceEntry { name: trace_name(&code) });
        let r = self.run_frame(&mut frame);
        self.trace.pop();
        self.depth -= 1;
        match r {
            Ok(Completion::Return(v)) => Ok(v),
            Ok(_) => Ok(Value::Undefined),
            Err(e) => Err(e),
        }
    }

    pub fn construct(&mut self, f: &Value, args: &[Value], new_target: Option<&Value>) -> JsResult<Value> {
        let fo = match f {
            Value::Obj(o) if o.is_constructor() => o.clone(),
            _ => {
                let d = self.describe_for_new(f);
                return self.throw_type(format!("{} is not a constructor", d));
            }
        };
        let nt = new_target.cloned().unwrap_or_else(|| f.clone());
        self.construct_obj(&fo, args, nt)
    }

    pub fn describe_for_new(&self, v: &Value) -> String {
        self.describe_for_call(v)
    }

    pub fn construct_obj(&mut self, fo: &Obj, args: &[Value], nt: Value) -> JsResult<Value> {
        enum K {
            Closure(Rc<FunctionCode>, Option<Env>, Option<Obj>, bool, Option<Rc<Vec<ClassField>>>),
            Native(NativeFn),
            Bound(Obj, Vec<Value>),
            Proxy,
        }
        let k = {
            let b = fo.borrow();
            match &b.kind {
                ObjKind::Closure(c) => K::Closure(c.code.clone(), c.env.clone(), c.home_object.clone(), c.derived, c.fields.clone()),
                ObjKind::Native(n) => K::Native(n.f),
                ObjKind::Bound(bf) => K::Bound(bf.target.clone(), bf.args.clone()),
                ObjKind::Proxy(_) => K::Proxy,
                _ => return self.throw_type("object is not a constructor"),
            }
        };
        match k {
            K::Closure(code, env, home, derived, fields) => {
                let this = if derived {
                    Value::Empty
                } else {
                    let proto = self.get_prototype_from_ctor(&nt, ProtoKind::Object)?;
                    let obj = Obj::new(Some(proto), ObjKind::Ordinary);
                    if let Some(fl) = &fields {
                        self.init_fields(&obj, fl)?;
                    }
                    Value::Obj(obj)
                };
                let mut frame = Frame::new(code.clone(), env, this.clone(), Some(fo.clone()), nt, args.to_vec(), home);
                self.enter()?;
                self.trace.push(TraceEntry { name: trace_name(&code) });
                let r = self.run_frame(&mut frame);
                self.trace.pop();
                self.depth -= 1;
                let v = match r? {
                    Completion::Return(v) => v,
                    _ => Value::Undefined,
                };
                if let Value::Obj(_) = v {
                    return Ok(v);
                }
                if derived {
                    if !v.is_undefined() {
                        return self.throw_type("Derived constructors may only return object or undefined");
                    }
                    if frame.this.is_empty() {
                        return self.throw_ref("must call super constructor before accessing 'this' or returning from derived constructor");
                    }
                    return Ok(frame.this.clone());
                }
                Ok(this)
            }
            K::Native(f) => {
                self.enter()?;
                let nt_obj = nt.as_obj().cloned();
                let r = f(self, &Args { this: Value::Undefined, args, callee: fo, new_target: nt_obj });
                self.depth -= 1;
                r
            }
            K::Bound(target, bargs) => {
                let mut all = bargs;
                all.extend_from_slice(args);
                let nt = if let Value::Obj(n) = &nt {
                    if n.ptr_eq(fo) {
                        Value::Obj(target.clone())
                    } else {
                        nt
                    }
                } else {
                    nt
                };
                self.construct_obj(&target, &all, nt)
            }
            K::Proxy => crate::builtins::proxy::proxy_construct(self, fo, args, nt),
        }
    }

    pub fn init_fields(&mut self, obj: &Obj, fields: &Rc<Vec<ClassField>>) -> JsResult<()> {
        // private methods first
        for f in fields.iter() {
            if let FieldKey::PrivateMethod(sym, prop) = &f.key {
                let k = PropKey::Sym(sym.clone());
                if obj.borrow().props.contains(&k) {
                    return self.throw_type("Cannot initialize private methods of class twice on the same object");
                }
                obj.borrow_mut().props.insert(k, prop.clone());
            }
        }
        for f in fields.iter() {
            let v = match &f.init {
                Some(init) => self.call_obj(init, Value::Obj(obj.clone()), &[])?,
                None => Value::Undefined,
            };
            match &f.key {
                FieldKey::Key(k) => {
                    if !self.create_data_property(obj, k.clone(), v)? {
                        return self.throw_type(format!("Cannot redefine property: {}", k.to_display()));
                    }
                }
                FieldKey::Private(sym) => {
                    let k = PropKey::Sym(sym.clone());
                    if obj.borrow().props.contains(&k) {
                        return self.throw_type(format!(
                            "Cannot initialize {} twice on the same object",
                            sym.0.description.as_ref().map(|d| d.to_rust_string()).unwrap_or_default()
                        ));
                    }
                    obj.borrow_mut().props.insert(k, Prop::Data { value: v, flags: WRITABLE });
                }
                FieldKey::PrivateMethod(..) => {}
            }
        }
        Ok(())
    }

    // ---------------- generators & async ----------------

    fn start_generator(&mut self, f: &Obj, mut frame: Frame) -> JsResult<Value> {
        let code = frame.code.clone();
        // prologue runs at call time
        self.enter()?;
        let r = self.run_frame(&mut frame);
        self.depth -= 1;
        match r {
            Ok(Completion::GenStart) => {}
            Ok(_) => {}
            Err(e) => return Err(e),
        }
        frame.is_coroutine = true;
        let proto_kind = if code.is_async { ProtoKind::AsyncGenerator } else { ProtoKind::Generator };
        let proto = self.get_prototype_from_ctor_prop(f, proto_kind)?;
        let obj = if code.is_async {
            Obj::new(
                Some(proto),
                ObjKind::AsyncGenerator(Box::new(AsyncGenData {
                    state: GenState::SuspendedStart,
                    awaiting_return: false,
                    frame: Some(Box::new(frame)),
                    queue: VecDeque::new(),
                })),
            )
        } else {
            Obj::new(Some(proto), ObjKind::Generator(Box::new(GeneratorData { state: GenState::SuspendedStart, frame: Some(Box::new(frame)) })))
        };
        Ok(Value::Obj(obj))
    }

    /// Resume a sync generator. Returns an iterator result object.
    pub fn generator_resume(&mut self, gen: &Obj, mode: ResumeMode, value: Value) -> JsResult<Value> {
        let (state, frame) = {
            let mut b = gen.borrow_mut();
            match &mut b.kind {
                ObjKind::Generator(g) => {
                    let st = g.state;
                    if st == GenState::Executing {
                        drop(b);
                        return self.throw_type("Generator is already running");
                    }
                    let fr = if st == GenState::Completed { None } else { g.frame.take() };
                    if fr.is_some() {
                        g.state = GenState::Executing;
                    }
                    (st, fr)
                }
                _ => {
                    drop(b);
                    return self.throw_type("next method called on incompatible receiver");
                }
            }
        };
        let mut frame = match frame {
            Some(f) => f,
            None => {
                return match mode {
                    ResumeMode::Next => Ok(self.iter_result(Value::Undefined, true)),
                    ResumeMode::Return => Ok(self.iter_result(value, true)),
                    ResumeMode::Throw => Err(value),
                };
            }
        };
        if state == GenState::SuspendedStart && mode != ResumeMode::Next {
            self.set_gen_state(gen, GenState::Completed, None);
            return match mode {
                ResumeMode::Return => Ok(self.iter_result(value, true)),
                _ => Err(value),
            };
        }
        match mode {
            ResumeMode::Throw => frame.pending_throw = Some(value),
            _ => {
                if state != GenState::SuspendedStart {
                    frame.stack.push(value);
                }
            }
        }
        frame.resume_mode = mode;
        if let Err(e) = self.enter() {
            self.set_gen_state(gen, GenState::SuspendedYield, Some(frame));
            return Err(e);
        }
        let r = self.run_frame(&mut frame);
        self.depth -= 1;
        match r {
            Ok(Completion::Yield(v)) => {
                self.set_gen_state(gen, GenState::SuspendedYield, Some(frame));
                Ok(self.iter_result(v, false))
            }
            Ok(Completion::YieldRaw(v)) => {
                self.set_gen_state(gen, GenState::SuspendedYield, Some(frame));
                Ok(v)
            }
            Ok(Completion::Return(v)) => {
                self.set_gen_state(gen, GenState::Completed, None);
                Ok(self.iter_result(v, true))
            }
            Ok(_) => {
                self.set_gen_state(gen, GenState::Completed, None);
                Ok(self.iter_result(Value::Undefined, true))
            }
            Err(e) => {
                self.set_gen_state(gen, GenState::Completed, None);
                Err(e)
            }
        }
    }

    fn set_gen_state(&mut self, gen: &Obj, st: GenState, frame: Option<Box<Frame>>) {
        if let ObjKind::Generator(g) = &mut gen.borrow_mut().kind {
            g.state = st;
            g.frame = frame;
        }
    }

    pub fn iter_result(&mut self, value: Value, done: bool) -> Value {
        let o = Obj::new(Some(self.intr.object_proto.clone()), ObjKind::Ordinary);
        {
            let mut b = o.borrow_mut();
            b.props.insert(self.intr.key_value.clone(), Prop::Data { value, flags: WEC });
            b.props.insert(self.intr.key_done.clone(), Prop::Data { value: Value::Bool(done), flags: WEC });
        }
        Value::Obj(o)
    }

    fn start_async(&mut self, frame: Frame) -> Value {
        let cap = self.new_promise_capability_intrinsic();
        let co = Obj::new(None, ObjKind::AsyncFn(Box::new(AsyncFnData { frame: Some(Box::new(frame)), capability: cap.clone() })));
        self.async_step(&co, ResumeMode::Next, Value::Undefined, true);
        cap.promise
    }

    /// Run/resume an async function coroutine.
    pub fn async_step(&mut self, co: &Obj, mode: ResumeMode, value: Value, first: bool) {
        let (frame, cap) = {
            let mut b = co.borrow_mut();
            match &mut b.kind {
                ObjKind::AsyncFn(a) => (a.frame.take(), a.capability.clone()),
                _ => return,
            }
        };
        let mut frame = match frame {
            Some(f) => f,
            None => return,
        };
        if !first {
            match mode {
                ResumeMode::Throw => frame.pending_throw = Some(value),
                _ => frame.stack.push(value),
            }
        }
        let r = if self.enter().is_ok() {
            if first {
                self.trace.push(TraceEntry { name: trace_name(&frame.code) });
            }
            let r = self.run_frame(&mut frame);
            if first {
                self.trace.pop();
            }
            self.depth -= 1;
            r
        } else {
            Err(self.make_error("RangeError", "Maximum call stack size exceeded"))
        };
        frame.is_coroutine = true;
        match r {
            Ok(Completion::Await(v)) => {
                if let ObjKind::AsyncFn(a) = &mut co.borrow_mut().kind {
                    a.frame = Some(frame);
                }
                self.await_value(v, co.clone());
            }
            Ok(Completion::Return(v)) => {
                let _ = self.call(&cap.resolve, Value::Undefined, &[v]);
            }
            Ok(_) => {
                let _ = self.call(&cap.resolve, Value::Undefined, &[Value::Undefined]);
            }
            Err(e) => {
                let _ = self.call(&cap.reject, Value::Undefined, &[e]);
            }
        }
    }

    /// Subscribe coroutine `co` to the settlement of `v`.
    pub fn await_value(&mut self, v: Value, co: Obj) {
        let p = match crate::builtins::promise::promise_resolve_intrinsic(self, v) {
            Ok(p) => p,
            Err(e) => {
                // resume with throw
                let job = Job::Reaction(
                    Reaction { capability: None, is_reject: true, handler: Handler::Await(co) },
                    e,
                );
                self.jobs.push_back(job);
                return;
            }
        };
        crate::builtins::promise::perform_then_internal(self, &p, Handler::Await(co.clone()), Handler::Await(co), None);
    }

    pub fn resume_coroutine(&mut self, co: &Obj, mode: ResumeMode, value: Value) {
        let is_async_fn = matches!(co.borrow().kind, ObjKind::AsyncFn(_));
        if is_async_fn {
            self.async_step(co, mode, value, false);
        } else {
            crate::builtins::generators::async_gen_resume_from_await(self, co, mode, value);
        }
    }

    // ---------------- main loop ----------------

    pub fn run_frame(&mut self, frame: &mut Frame) -> Result<Completion, Value> {
        if let Some(e) = frame.pending_throw.take() {
            if !self.handle_throw(frame, e.clone()) {
                return Err(e);
            }
        }
        loop {
            match self.run_inner(frame) {
                Ok(c) => return Ok(c),
                Err(e) => {
                    if !self.handle_throw(frame, e.clone()) {
                        return Err(e);
                    }
                }
            }
        }
    }

    fn handle_throw(&mut self, frame: &mut Frame, e: Value) -> bool {
        match frame.handlers.pop() {
            Some(h) => {
                frame.stack.truncate(h.sp as usize);
                frame.env = h.env;
                frame.stack.push(e);
                frame.pc = h.pc as usize;
                true
            }
            None => false,
        }
    }

    fn run_inner(&mut self, frame: &mut Frame) -> Result<Completion, Value> {
        let code = frame.code.clone();
        let ops = &code.ops;
        loop {
            let op = ops[frame.pc];
            frame.pc += 1;
            match op {
                Op::Undef => frame.stack.push(Value::Undefined),
                Op::Null => frame.stack.push(Value::Null),
                Op::True => frame.stack.push(Value::Bool(true)),
                Op::False => frame.stack.push(Value::Bool(false)),
                Op::Int(i) => frame.stack.push(Value::Num(i as f64)),
                Op::Const(i) => frame.stack.push(code.consts[i as usize].clone()),
                Op::Empty => frame.stack.push(Value::Empty),
                Op::Pop => {
                    frame.stack.pop();
                }
                Op::Dup => {
                    let v = frame.stack.last().unwrap().clone();
                    frame.stack.push(v);
                }
                Op::Dup2 => {
                    let n = frame.stack.len();
                    let a = frame.stack[n - 2].clone();
                    let b = frame.stack[n - 1].clone();
                    frame.stack.push(a);
                    frame.stack.push(b);
                }
                Op::Swap => {
                    let n = frame.stack.len();
                    frame.stack.swap(n - 1, n - 2);
                }
                Op::Rot3 => {
                    let v = pop(&mut frame.stack);
                    let n = frame.stack.len();
                    frame.stack.insert(n - 2, v);
                }
                Op::Rot4 => {
                    let v = pop(&mut frame.stack);
                    let n = frame.stack.len();
                    frame.stack.insert(n - 3, v);
                }
                Op::Pick(n) => {
                    let len = frame.stack.len();
                    let v = frame.stack[len - 1 - n as usize].clone();
                    frame.stack.push(v);
                }
                Op::GetLocal(s) => {
                    let v = frame.locals[s as usize].clone();
                    frame.stack.push(v);
                }
                Op::GetLocalChk(s, n) => {
                    let v = frame.locals[s as usize].clone();
                    if v.is_empty() {
                        return Err(self.tdz_error(&code.strings[n as usize]));
                    }
                    frame.stack.push(v);
                }
                Op::SetLocal(s) => {
                    frame.locals[s as usize] = frame.stack.last().unwrap().clone();
                }
                Op::InitLocal(s) => {
                    frame.locals[s as usize] = pop(&mut frame.stack);
                }
                Op::ClearLocal(s) => {
                    frame.locals[s as usize] = Value::Empty;
                }
                Op::GetEnv(d, s) => {
                    let v = {
                        let e = frame.env.as_ref().unwrap().ancestor(d);
                        let vars = e.0.vars.borrow();
                        vars[s as usize].clone()
                    };
                    frame.stack.push(v);
                }
                Op::GetEnvChk(d, s, n) => {
                    let v = {
                        let e = frame.env.as_ref().unwrap().ancestor(d);
                        let vars = e.0.vars.borrow();
                        vars[s as usize].clone()
                    };
                    if v.is_empty() {
                        return Err(self.tdz_error(&code.strings[n as usize]));
                    }
                    frame.stack.push(v);
                }
                Op::SetEnv(d, s) => {
                    let v = frame.stack.last().unwrap().clone();
                    let e = frame.env.as_ref().unwrap().ancestor(d);
                    e.0.vars.borrow_mut()[s as usize] = v;
                }
                Op::SetEnvChk(d, s, n) => {
                    let v = frame.stack.last().unwrap().clone();
                    let e = frame.env.as_ref().unwrap().ancestor(d).clone();
                    if e.0.vars.borrow()[s as usize].is_empty() {
                        return Err(self.tdz_error(&code.strings[n as usize]));
                    }
                    e.0.vars.borrow_mut()[s as usize] = v;
                }
                Op::InitEnv(d, s) => {
                    let v = pop(&mut frame.stack);
                    let e = frame.env.as_ref().unwrap().ancestor(d);
                    e.0.vars.borrow_mut()[s as usize] = v;
                }
                Op::GetName(k) => {
                    let name = code.keys[k as usize].clone();
                    let v = self.get_name(frame, &name)?;
                    frame.stack.push(v);
                }
                Op::SetName(k) => {
                    let name = code.keys[k as usize].clone();
                    let v = frame.stack.last().unwrap().clone();
                    self.set_name(frame, &name, v, code.strict)?;
                }
                Op::TypeofName(k) => {
                    let name = code.keys[k as usize].clone();
                    let v = match self.lookup_name(frame, &name)? {
                        Some(v) => v,
                        None => Value::Undefined,
                    };
                    frame.stack.push(Value::str(v.type_of()));
                }
                Op::DeleteName(k) => {
                    let name = code.keys[k as usize].clone();
                    let r = self.delete_name(frame, &name)?;
                    frame.stack.push(Value::Bool(r));
                }
                Op::GetNameCall(k) => {
                    let name = code.keys[k as usize].clone();
                    let (this, v) = self.get_name_for_call(frame, &name)?;
                    frame.stack.push(this);
                    frame.stack.push(v);
                }
                Op::GetGlobal(k) => {
                    let v = self.get_global(&code.keys[k as usize])?;
                    frame.stack.push(v);
                }
                Op::SetGlobal(k) => {
                    let v = frame.stack.last().unwrap().clone();
                    self.set_global(&code.keys[k as usize], v, code.strict)?;
                }
                Op::TypeofGlobal(k) => {
                    let key = &code.keys[k as usize];
                    let v = match self.lookup_global(key)? {
                        Some(v) => v,
                        None => Value::Undefined,
                    };
                    frame.stack.push(Value::str(v.type_of()));
                }
                Op::DeclareGlobalVar(k) => {
                    let key = code.keys[k as usize].clone();
                    self.declare_global_var(frame, key, false)?;
                }
                Op::DeclareGlobalFunc(k) => {
                    let key = code.keys[k as usize].clone();
                    self.declare_global_var(frame, key, true)?;
                }
                Op::DeclareGlobalLex(k, is_const) => {
                    let key = code.keys[k as usize].clone();
                    let name = key.as_jsstr().unwrap().clone();
                    if self.global_lex.contains_key(&name) {
                        return Err(self.make_error("SyntaxError", &format!("Identifier '{}' has already been declared", name)));
                    }
                    self.global_lex.insert(name, GlobalLex { value: Value::Empty, mutable: !is_const });
                }
                Op::InitGlobalLex(k) => {
                    let v = pop(&mut frame.stack);
                    let key = &code.keys[k as usize];
                    let name = key.as_jsstr().unwrap().clone();
                    match self.global_lex.get_mut(&name) {
                        Some(g) => g.value = v,
                        None => {
                            self.set_global(key, v, false)?;
                        }
                    }
                }
                Op::PushScope(i) => {
                    let info = code.scopes[i as usize].clone();
                    frame.env = Some(Env::new(info, frame.env.take()));
                }
                Op::PopScope => {
                    let e = frame.env.take().unwrap();
                    frame.env = e.0.parent.clone();
                }
                Op::CopyScope => {
                    let e = frame.env.take().unwrap();
                    let vals = e.0.vars.borrow().clone();
                    frame.env = Some(Env(Rc::new(EnvData {
                        vars: RefCell::new(vals),
                        parent: e.0.parent.clone(),
                        info: e.0.info.clone(),
                        with_obj: None,
                        extra: RefCell::new(Vec::new()),
                    })));
                }
                Op::PushWith => {
                    let v = pop(&mut frame.stack);
                    let o = self.to_object(&v)?;
                    frame.env = Some(Env::new_with(o, frame.env.take()));
                }
                Op::ThrowConst(n) => {
                    return Err(self.make_error("TypeError", &format!("assignment to constant '{}'", code.strings[n as usize])));
                }
                Op::This => frame.stack.push(frame.this.clone()),
                Op::ThisChk => {
                    if frame.this.is_empty() {
                        return Err(self.make_error("ReferenceError", "cannot access 'this' before initialization"));
                    }
                    frame.stack.push(frame.this.clone());
                }
                Op::SetThis | Op::BindThis => {
                    let v = pop(&mut frame.stack);
                    if !frame.this.is_empty() {
                        return Err(self.make_error("ReferenceError", "Super constructor may only be called once"));
                    }
                    frame.this = v;
                }
                Op::BindThisEnv(d, s) => {
                    let v = pop(&mut frame.stack);
                    let e = frame.env.as_ref().unwrap().ancestor(d).clone();
                    if !e.0.vars.borrow()[s as usize].is_empty() {
                        return Err(self.make_error("ReferenceError", "Super constructor may only be called once"));
                    }
                    e.0.vars.borrow_mut()[s as usize] = v.clone();
                    if frame.this.is_empty() && d == 0 {
                        frame.this = v;
                    }
                }
                Op::NewTarget => frame.stack.push(frame.new_target.clone()),
                Op::GetArg(i) => {
                    let v = frame.args.get(i as usize).cloned().unwrap_or(Value::Undefined);
                    frame.stack.push(v);
                }
                Op::GetRest(i) => {
                    let rest: Vec<Value> = if (i as usize) < frame.args.len() { frame.args[i as usize..].to_vec() } else { Vec::new() };
                    let a = self.new_array(rest);
                    frame.stack.push(Value::Obj(a));
                }
                Op::CreateArguments(_) => {
                    let a = self.create_arguments(frame);
                    frame.stack.push(Value::Obj(a));
                }
                Op::Callee => frame.stack.push(frame.func.clone().map(Value::Obj).unwrap_or(Value::Undefined)),
                Op::Home => frame.stack.push(frame.home.clone().map(Value::Obj).unwrap_or(Value::Undefined)),
                Op::GetProp(k) => {
                    let obj = pop(&mut frame.stack);
                    let key = &code.keys[k as usize];
                    let v = self.get_prop_of(&obj, key)?;
                    frame.stack.push(v);
                }
                Op::GetPropOpt(k) => {
                    let obj = pop(&mut frame.stack);
                    if obj.is_nullish() {
                        frame.stack.push(Value::Undefined);
                    } else {
                        let v = self.get_prop_of(&obj, &code.keys[k as usize])?;
                        frame.stack.push(v);
                    }
                }
                Op::GetElem => {
                    let key = pop(&mut frame.stack);
                    let obj = pop(&mut frame.stack);
                    let v = self.get_elem(&obj, &key)?;
                    frame.stack.push(v);
                }
                Op::SetProp(k) => {
                    let v = pop(&mut frame.stack);
                    let obj = pop(&mut frame.stack);
                    self.set_prop_of(&obj, code.keys[k as usize].clone(), v.clone(), code.strict)?;
                    frame.stack.push(v);
                }
                Op::SetElem => {
                    let v = pop(&mut frame.stack);
                    let key = pop(&mut frame.stack);
                    let obj = pop(&mut frame.stack);
                    self.set_elem(&obj, &key, v.clone(), code.strict)?;
                    frame.stack.push(v);
                }
                Op::DeleteProp(k) => {
                    let obj = pop(&mut frame.stack);
                    let r = self.delete_prop_of(&obj, &code.keys[k as usize], code.strict)?;
                    frame.stack.push(Value::Bool(r));
                }
                Op::DeleteElem => {
                    let key = pop(&mut frame.stack);
                    let obj = pop(&mut frame.stack);
                    if obj.is_nullish() {
                        return Err(self.make_error("TypeError", "cannot convert undefined or null to object"));
                    }
                    let k = self.to_property_key(&key)?;
                    let r = self.delete_prop_of(&obj, &k, code.strict)?;
                    frame.stack.push(Value::Bool(r));
                }
                Op::GetSuper(k) => {
                    let this = pop(&mut frame.stack);
                    let v = self.super_get(frame, &code.keys[k as usize], &this)?;
                    frame.stack.push(v);
                }
                Op::GetSuperElem => {
                    let key = pop(&mut frame.stack);
                    let this = pop(&mut frame.stack);
                    let k = self.to_property_key(&key)?;
                    let v = self.super_get(frame, &k, &this)?;
                    frame.stack.push(v);
                }
                Op::SetSuper(k) => {
                    let v = pop(&mut frame.stack);
                    let this = pop(&mut frame.stack);
                    self.super_set(frame, code.keys[k as usize].clone(), v.clone(), &this, code.strict)?;
                    frame.stack.push(v);
                }
                Op::SetSuperElem => {
                    let v = pop(&mut frame.stack);
                    let key = pop(&mut frame.stack);
                    let this = pop(&mut frame.stack);
                    let k = self.to_property_key(&key)?;
                    self.super_set(frame, k, v.clone(), &this, code.strict)?;
                    frame.stack.push(v);
                }
                Op::GetPrivate => {
                    let sym = pop(&mut frame.stack);
                    let obj = pop(&mut frame.stack);
                    let v = self.private_get(&obj, &sym)?;
                    frame.stack.push(v);
                }
                Op::SetPrivate => {
                    let v = pop(&mut frame.stack);
                    let sym = pop(&mut frame.stack);
                    let obj = pop(&mut frame.stack);
                    self.private_set(&obj, &sym, v.clone())?;
                    frame.stack.push(v);
                }
                Op::PrivateIn => {
                    let obj = pop(&mut frame.stack);
                    let sym = pop(&mut frame.stack);
                    let o = match &obj {
                        Value::Obj(o) => o.clone(),
                        _ => return Err(self.make_error("TypeError", "'in' requires an object on the right")),
                    };
                    let s = match sym {
                        Value::Sym(s) => s,
                        _ => return Err(self.make_error("TypeError", "invalid private name")),
                    };
                    let has = o.borrow().props.contains(&PropKey::Sym(s));
                    frame.stack.push(Value::Bool(has));
                }
                Op::GetMethod(k) => {
                    let obj = frame.stack.last().unwrap().clone();
                    let key = &code.keys[k as usize];
                    let v = self.get_prop_of(&obj, key)?;
                    frame.stack.push(v);
                }
                Op::GetMethodElem => {
                    let key = pop(&mut frame.stack);
                    let obj = frame.stack.last().unwrap().clone();
                    let v = self.get_elem(&obj, &key)?;
                    frame.stack.push(v);
                }
                Op::ToPropKey => {
                    let v = pop(&mut frame.stack);
                    let k = self.to_property_key(&v)?;
                    frame.stack.push(match k {
                        PropKey::Str(s) => Value::Str(s),
                        PropKey::Sym(s) => Value::Sym(s),
                    });
                }
                Op::NewObject => {
                    let o = Obj::new(Some(self.intr.object_proto.clone()), ObjKind::Ordinary);
                    frame.stack.push(Value::Obj(o));
                }
                Op::NewArray(n) => {
                    let n = n as usize;
                    let len = frame.stack.len();
                    let elems: Vec<Value> = frame.stack.drain(len - n..).collect();
                    let a = self.new_array(elems);
                    frame.stack.push(Value::Obj(a));
                }
                Op::ArrayPush => {
                    let v = pop(&mut frame.stack);
                    let a = frame.stack.last().unwrap().as_obj().unwrap().clone();
                    array_push_raw(&a, v);
                }
                Op::ArrayHole => {
                    let a = frame.stack.last().unwrap().as_obj().unwrap().clone();
                    array_push_raw(&a, Value::Empty);
                }
                Op::ArraySpread => {
                    let it = pop(&mut frame.stack);
                    let a = frame.stack.last().unwrap().as_obj().unwrap().clone();
                    let items = self.iterate_to_vec(&it)?;
                    for v in items {
                        array_push_raw(&a, v);
                    }
                }
                Op::DefineField(k) => {
                    let v = pop(&mut frame.stack);
                    let o = frame.stack.last().unwrap().as_obj().unwrap().clone();
                    o.set_prop(code.keys[k as usize].clone(), v, WEC);
                }
                Op::DefineFieldComputed => {
                    let v = pop(&mut frame.stack);
                    let key = pop(&mut frame.stack);
                    let o = frame.stack.last().unwrap().as_obj().unwrap().clone();
                    let k = self.to_property_key(&key)?;
                    if o.is_array() {
                        self.create_data_property(&o, k, v)?;
                    } else {
                        o.set_prop(k, v, WEC);
                    }
                }
                Op::DefineAccessor(k, mk) => {
                    let f = pop(&mut frame.stack);
                    let o = frame.stack.last().unwrap().as_obj().unwrap().clone();
                    self.define_accessor_part(&o, code.keys[k as usize].clone(), f, mk, ENUMERABLE | CONFIGURABLE);
                }
                Op::DefineAccessorComputed(mk) => {
                    let f = pop(&mut frame.stack);
                    let key = pop(&mut frame.stack);
                    let o = frame.stack.last().unwrap().as_obj().unwrap().clone();
                    let k = self.to_property_key(&key)?;
                    self.define_accessor_part(&o, k, f, mk, ENUMERABLE | CONFIGURABLE);
                }
                Op::CopyDataProps => {
                    let src = pop(&mut frame.stack);
                    let o = frame.stack.last().unwrap().as_obj().unwrap().clone();
                    self.copy_data_properties(&o, &src, &[])?;
                }
                Op::CopyDataPropsExcept(n) => {
                    let n = n as usize;
                    let len = frame.stack.len();
                    let excl_vals: Vec<Value> = frame.stack.drain(len - n..).collect();
                    let src = pop(&mut frame.stack);
                    let mut excl = Vec::new();
                    for v in excl_vals {
                        excl.push(self.to_property_key(&v)?);
                    }
                    let o = Obj::new(Some(self.intr.object_proto.clone()), ObjKind::Ordinary);
                    self.copy_data_properties(&o, &src, &excl)?;
                    frame.stack.push(Value::Obj(o));
                }
                Op::SetProtoLit => {
                    let p = pop(&mut frame.stack);
                    let o = frame.stack.last().unwrap().as_obj().unwrap().clone();
                    match p {
                        Value::Obj(po) => o.borrow_mut().proto = Some(po),
                        Value::Null => o.borrow_mut().proto = None,
                        _ => {}
                    }
                }
                Op::RegExp(i) => {
                    let (p, f) = code.regexps[i as usize].clone();
                    let r = crate::builtins::regexp::regexp_create(self, &Value::Str(p), &Value::Str(f))?;
                    frame.stack.push(r);
                }
                Op::Template(i) => {
                    let t = code.templates[i as usize].clone();
                    let o = self.get_template_object(&t);
                    frame.stack.push(Value::Obj(o));
                }
                Op::Closure(i) => {
                    let fcode = code.funcs[i as usize].clone();
                    let home = if fcode.is_arrow { frame.home.clone() } else { None };
                    let f = self.make_closure(fcode, frame.env.clone(), home);
                    frame.stack.push(Value::Obj(f));
                }
                Op::Method(i) => {
                    let fcode = code.funcs[i as usize].clone();
                    let home = frame.stack.last().unwrap().as_obj().cloned();
                    let f = self.make_closure(fcode, frame.env.clone(), home);
                    frame.stack.push(Value::Obj(f));
                }
                Op::SetFunctionName(kind) => {
                    // [key fn]
                    let f = frame.stack.last().unwrap().clone();
                    let key = frame.stack[frame.stack.len() - 2].clone();
                    if let Value::Obj(fo) = &f {
                        let k = self.to_property_key(&key)?;
                        let prefix = match kind {
                            1 => Some("get"),
                            2 => Some("set"),
                            _ => None,
                        };
                        self.set_function_name(fo, &k, prefix);
                    }
                }
                Op::CreateClass(ci, has_heritage) => {
                    let heritage = if has_heritage { Some(pop(&mut frame.stack)) } else { None };
                    let (f, proto) = self.create_class(frame, code.funcs[ci as usize].clone(), heritage)?;
                    frame.stack.push(Value::Obj(f));
                    frame.stack.push(Value::Obj(proto));
                }
                Op::DefineMethod(k, target, mk, fi) => {
                    let key = code.keys[k as usize].clone();
                    self.class_define_method(frame, &code, key, target, mk, fi)?;
                }
                Op::DefineMethodComputed(target, mk, fi) => {
                    let keyv = pop(&mut frame.stack);
                    let key = self.to_property_key(&keyv)?;
                    self.class_define_method(frame, &code, key, target, mk, fi)?;
                }
                Op::AddField(k, init, _st) => {
                    let key = FieldKey::Key(code.keys[k as usize].clone());
                    self.class_add_field(frame, &code, key, init);
                }
                Op::AddFieldComputed(init, _st) => {
                    let keyv = pop(&mut frame.stack);
                    let key = self.to_property_key(&keyv)?;
                    self.class_add_field(frame, &code, FieldKey::Key(key), init);
                }
                Op::AddFieldPrivate(init) => {
                    let sym = pop(&mut frame.stack);
                    if let Value::Sym(s) = sym {
                        self.class_add_field(frame, &code, FieldKey::Private(s), init);
                    }
                }
                Op::AddPrivateMethod(fi, mk, is_static) => {
                    let sym = pop(&mut frame.stack);
                    self.class_add_private_method(frame, &code, sym, fi, mk, is_static)?;
                }
                Op::StaticField(k, init) => {
                    let key = code.keys[k as usize].clone();
                    self.class_static_field(frame, &code, FieldKey::Key(key), init)?;
                }
                Op::StaticFieldComputed(init) => {
                    let keyv = pop(&mut frame.stack);
                    let key = self.to_property_key(&keyv)?;
                    self.class_static_field(frame, &code, FieldKey::Key(key), init)?;
                }
                Op::StaticPrivateField(init) => {
                    let sym = pop(&mut frame.stack);
                    if let Value::Sym(s) = sym {
                        self.class_static_field(frame, &code, FieldKey::Private(s), init)?;
                    }
                }
                Op::StaticBlock(fi) => {
                    let n = frame.stack.len();
                    let fo = frame.stack[n - 2].as_obj().unwrap().clone();
                    let fcode = code.funcs[fi as usize].clone();
                    let f = self.make_closure(fcode, frame.env.clone(), Some(fo.clone()));
                    self.call_obj(&f, Value::Obj(fo), &[])?;
                }
                Op::NewPrivateName(si) => {
                    let s = Sym::new_private(JsStr::from_str(&format!("#{}", code.strings[si as usize])));
                    frame.stack.push(Value::Sym(s));
                }
                Op::Add => {
                    let b = pop(&mut frame.stack);
                    let a = pop(&mut frame.stack);
                    let r = match (&a, &b) {
                        (Value::Num(x), Value::Num(y)) => Value::Num(x + y),
                        (Value::Str(x), Value::Str(y)) => Value::Str(JsStr::concat(x, y)),
                        _ => self.op_add(&a, &b)?,
                    };
                    frame.stack.push(r);
                }
                Op::Sub | Op::Mul | Op::Div | Op::Mod | Op::Exp | Op::Shl | Op::Shr | Op::UShr | Op::BitAnd | Op::BitOr | Op::BitXor => {
                    let b = pop(&mut frame.stack);
                    let a = pop(&mut frame.stack);
                    let r = if let (Value::Num(x), Value::Num(y)) = (&a, &b) {
                        num_binop(op, *x, *y)
                    } else {
                        self.op_arith(op, &a, &b)?
                    };
                    frame.stack.push(r);
                }
                Op::Eq | Op::Ne => {
                    let b = pop(&mut frame.stack);
                    let a = pop(&mut frame.stack);
                    let r = self.loose_eq(&a, &b)?;
                    frame.stack.push(Value::Bool(if let Op::Eq = op { r } else { !r }));
                }
                Op::StrictEq => {
                    let b = pop(&mut frame.stack);
                    let a = pop(&mut frame.stack);
                    frame.stack.push(Value::Bool(Value::strict_eq(&a, &b)));
                }
                Op::StrictNe => {
                    let b = pop(&mut frame.stack);
                    let a = pop(&mut frame.stack);
                    frame.stack.push(Value::Bool(!Value::strict_eq(&a, &b)));
                }
                Op::Lt | Op::Le | Op::Gt | Op::Ge => {
                    let b = pop(&mut frame.stack);
                    let a = pop(&mut frame.stack);
                    let r = if let (Value::Num(x), Value::Num(y)) = (&a, &b) {
                        match op {
                            Op::Lt => x < y,
                            Op::Le => x <= y,
                            Op::Gt => x > y,
                            _ => x >= y,
                        }
                    } else {
                        self.op_compare(op, &a, &b)?
                    };
                    frame.stack.push(Value::Bool(r));
                }
                Op::In => {
                    let b = pop(&mut frame.stack);
                    let a = pop(&mut frame.stack);
                    let o = match &b {
                        Value::Obj(o) => o.clone(),
                        _ => return Err(self.make_error("TypeError", "'in' requires an object on the right")),
                    };
                    let k = self.to_property_key(&a)?;
                    let r = self.has_property(&o, &k)?;
                    frame.stack.push(Value::Bool(r));
                }
                Op::InstanceOf => {
                    let b = pop(&mut frame.stack);
                    let a = pop(&mut frame.stack);
                    let r = self.instance_of(&a, &b)?;
                    frame.stack.push(Value::Bool(r));
                }
                Op::Neg => {
                    let a = pop(&mut frame.stack);
                    let r = match a {
                        Value::Num(n) => Value::Num(-n),
                        _ => match self.to_numeric(&a)? {
                            Value::BigInt(b) => Value::BigInt(Rc::new(b.neg())),
                            Value::Num(n) => Value::Num(-n),
                            _ => unreachable!(),
                        },
                    };
                    frame.stack.push(r);
                }
                Op::Plus => {
                    let a = pop(&mut frame.stack);
                    let n = self.to_number(&a)?;
                    frame.stack.push(Value::Num(n));
                }
                Op::Not => {
                    let a = pop(&mut frame.stack);
                    frame.stack.push(Value::Bool(!a.truthy()));
                }
                Op::BitNot => {
                    let a = pop(&mut frame.stack);
                    let r = match self.to_numeric(&a)? {
                        Value::BigInt(b) => Value::BigInt(Rc::new(b.not())),
                        Value::Num(n) => Value::Num(!crate::builtins::number::to_int32(n) as f64),
                        _ => unreachable!(),
                    };
                    frame.stack.push(r);
                }
                Op::Typeof => {
                    let a = pop(&mut frame.stack);
                    frame.stack.push(Value::str(a.type_of()));
                }
                Op::Void => {
                    frame.stack.pop();
                    frame.stack.push(Value::Undefined);
                }
                Op::Inc | Op::Dec => {
                    let a = pop(&mut frame.stack);
                    let d = if let Op::Inc = op { 1.0 } else { -1.0 };
                    let r = match a {
                        Value::Num(n) => Value::Num(n + d),
                        Value::BigInt(b) => {
                            let one = crate::bigint::BigInt::from_i64(d as i64);
                            Value::BigInt(Rc::new(b.add(&one)))
                        }
                        other => {
                            let n = self.to_number(&other)?;
                            Value::Num(n + d)
                        }
                    };
                    frame.stack.push(r);
                }
                Op::ToNumeric => {
                    let a = pop(&mut frame.stack);
                    let r = match a {
                        Value::Num(_) | Value::BigInt(_) => a,
                        other => self.to_numeric(&other)?,
                    };
                    frame.stack.push(r);
                }
                Op::ToStr => {
                    let a = pop(&mut frame.stack);
                    let r = match a {
                        Value::Str(_) => a,
                        other => Value::Str(self.to_string(&other)?),
                    };
                    frame.stack.push(r);
                }
                Op::Jump(t) => frame.pc = t as usize,
                Op::JumpIfFalse(t) => {
                    let v = pop(&mut frame.stack);
                    if !v.truthy() {
                        frame.pc = t as usize;
                    }
                }
                Op::JumpIfTrue(t) => {
                    let v = pop(&mut frame.stack);
                    if v.truthy() {
                        frame.pc = t as usize;
                    }
                }
                Op::JumpIfFalseKeep(t) => {
                    if !frame.stack.last().unwrap().truthy() {
                        frame.pc = t as usize;
                    }
                }
                Op::JumpIfTrueKeep(t) => {
                    if frame.stack.last().unwrap().truthy() {
                        frame.pc = t as usize;
                    }
                }
                Op::JumpIfNullishKeep(t) => {
                    if frame.stack.last().unwrap().is_nullish() {
                        frame.pc = t as usize;
                    }
                }
                Op::JumpIfNotNullishKeep(t) => {
                    if !frame.stack.last().unwrap().is_nullish() {
                        frame.pc = t as usize;
                    }
                }
                Op::JumpIfNotUndef(t) => {
                    let v = pop(&mut frame.stack);
                    if !v.is_undefined() {
                        frame.pc = t as usize;
                    }
                }
                Op::JumpIfNullish(t) => {
                    let v = pop(&mut frame.stack);
                    if v.is_nullish() {
                        frame.pc = t as usize;
                    }
                }
                Op::Return => {
                    let v = pop(&mut frame.stack);
                    return Ok(Completion::Return(v));
                }
                Op::TryStart(t) => {
                    frame.handlers.push(TryHandler { pc: t, sp: frame.stack.len() as u32, env: frame.env.clone() });
                }
                Op::TryEnd => {
                    frame.handlers.pop();
                }
                Op::Throw => {
                    let v = pop(&mut frame.stack);
                    return Err(v);
                }
                Op::ThrowRef(n) => {
                    return Err(self.make_error("ReferenceError", &code.strings[n as usize].to_rust_string()));
                }
                Op::ThrowType(n) => {
                    return Err(self.make_error("TypeError", &code.strings[n as usize].to_rust_string()));
                }
                Op::Call(argc, desc) => {
                    let argc = argc as usize;
                    let len = frame.stack.len();
                    let args: Vec<Value> = frame.stack.drain(len - argc..).collect();
                    let f = pop(&mut frame.stack);
                    let this = pop(&mut frame.stack);
                    let r = match &f {
                        Value::Obj(o) => self.call_obj(o, this, &args)?,
                        _ => {
                            let d = if desc == u32::MAX { self.describe_for_call(&f) } else { code.strings[desc as usize].to_rust_string() };
                            return Err(self.make_error("TypeError", &format!("{} is not a function", d)));
                        }
                    };
                    frame.stack.push(r);
                }
                Op::CallArray(desc) => {
                    let arr = pop(&mut frame.stack);
                    let f = pop(&mut frame.stack);
                    let this = pop(&mut frame.stack);
                    let args = self.array_to_vec(&arr)?;
                    let r = match &f {
                        Value::Obj(o) if o.is_callable() => self.call_obj(o, this, &args)?,
                        _ => {
                            let d = if desc == u32::MAX { self.describe_for_call(&f) } else { code.strings[desc as usize].to_rust_string() };
                            return Err(self.make_error("TypeError", &format!("{} is not a function", d)));
                        }
                    };
                    frame.stack.push(r);
                }
                Op::CallEval(argc) => {
                    let argc = argc as usize;
                    let len = frame.stack.len();
                    let args: Vec<Value> = frame.stack.drain(len - argc..).collect();
                    let f = pop(&mut frame.stack);
                    let this = pop(&mut frame.stack);
                    let r = self.call_maybe_eval(frame, &f, this, &args)?;
                    frame.stack.push(r);
                }
                Op::CallEvalArray => {
                    let arr = pop(&mut frame.stack);
                    let f = pop(&mut frame.stack);
                    let this = pop(&mut frame.stack);
                    let args = self.array_to_vec(&arr)?;
                    let r = self.call_maybe_eval(frame, &f, this, &args)?;
                    frame.stack.push(r);
                }
                Op::New(argc) => {
                    let argc = argc as usize;
                    let len = frame.stack.len();
                    let args: Vec<Value> = frame.stack.drain(len - argc..).collect();
                    let f = pop(&mut frame.stack);
                    let r = self.construct(&f, &args, None)?;
                    frame.stack.push(r);
                }
                Op::NewArray_ => {
                    let arr = pop(&mut frame.stack);
                    let f = pop(&mut frame.stack);
                    let args = self.array_to_vec(&arr)?;
                    let r = self.construct(&f, &args, None)?;
                    frame.stack.push(r);
                }
                Op::SuperCall(argc) => {
                    let argc = argc as usize;
                    let len = frame.stack.len();
                    let args: Vec<Value> = frame.stack.drain(len - argc..).collect();
                    let nt = pop(&mut frame.stack);
                    let func = frame.stack.last().unwrap().clone();
                    let r = self.super_call(&func, &args, nt)?;
                    frame.stack.push(r);
                }
                Op::SuperCallArray => {
                    let arr = pop(&mut frame.stack);
                    let nt = pop(&mut frame.stack);
                    let func = frame.stack.last().unwrap().clone();
                    let args = self.array_to_vec(&arr)?;
                    let r = self.super_call(&func, &args, nt)?;
                    frame.stack.push(r);
                }
                Op::SuperCallForward => {
                    let nt = pop(&mut frame.stack);
                    let func = frame.stack.last().unwrap().clone();
                    let args = frame.args.clone();
                    let r = self.super_call(&func, &args, nt)?;
                    frame.stack.push(r);
                }
                Op::InitFields => {
                    let f = pop(&mut frame.stack);
                    let obj = frame.stack.last().unwrap().clone();
                    if let (Value::Obj(fo), Value::Obj(o)) = (&f, &obj) {
                        let fields = match &fo.borrow().kind {
                            ObjKind::Closure(c) => c.fields.clone(),
                            _ => None,
                        };
                        if let Some(fl) = fields {
                            self.init_fields(o, &fl)?;
                        }
                    }
                }
                Op::GetIterator => {
                    let v = pop(&mut frame.stack);
                    let (it, next) = self.get_iterator(&v)?;
                    frame.stack.push(Value::Obj(it));
                    frame.stack.push(next);
                }
                Op::GetAsyncIterator => {
                    let v = pop(&mut frame.stack);
                    let (it, next) = self.get_async_iterator(&v)?;
                    frame.stack.push(Value::Obj(it));
                    frame.stack.push(next);
                }
                Op::IterNext(t) => {
                    let n = frame.stack.len();
                    let next = frame.stack[n - 1].clone();
                    let it = frame.stack[n - 2].clone();
                    let res = self.call(&next, it, &[])?;
                    let ro = match &res {
                        Value::Obj(o) => o.clone(),
                        _ => return Err(self.make_error("TypeError", "iterator result is not an object")),
                    };
                    let done = self.get(&ro, &self.intr.key_done.clone(), &res)?.truthy();
                    if done {
                        frame.pc = t as usize;
                    } else {
                        let v = self.get(&ro, &self.intr.key_value.clone(), &res)?;
                        frame.stack.push(v);
                    }
                }
                Op::IterCallNext => {
                    let n = frame.stack.len();
                    let next = frame.stack[n - 1].clone();
                    let it = frame.stack[n - 2].clone();
                    let res = self.call(&next, it, &[])?;
                    frame.stack.push(res);
                }
                Op::AsyncIterCheck(t) => {
                    let res = pop(&mut frame.stack);
                    let ro = match &res {
                        Value::Obj(o) => o.clone(),
                        _ => return Err(self.make_error("TypeError", "iterator result is not an object")),
                    };
                    let done = self.get(&ro, &self.intr.key_done.clone(), &res)?.truthy();
                    if done {
                        frame.pc = t as usize;
                    } else {
                        let v = self.get(&ro, &self.intr.key_value.clone(), &res)?;
                        frame.stack.push(v);
                    }
                }
                Op::IterClose => {
                    let _next = pop(&mut frame.stack);
                    let it = pop(&mut frame.stack);
                    self.iterator_close(&it)?;
                }
                Op::IterCloseSilent => {
                    let _next = pop(&mut frame.stack);
                    let it = pop(&mut frame.stack);
                    let _ = self.iterator_close(&it);
                }
                Op::IterCloseAsync => {
                    let _next = pop(&mut frame.stack);
                    let it = pop(&mut frame.stack);
                    let ret = self.get_method(&it, &PropKey::from_str("return"))?;
                    match ret {
                        Some(f) => {
                            let r = self.call(&f, it, &[])?;
                            frame.stack.push(r);
                        }
                        None => frame.stack.push(Value::Undefined),
                    }
                }
                Op::IterCloseThrow => {
                    // [exc iter next (done)?]
                    let top = pop(&mut frame.stack);
                    let (it, exc, done) = if let Value::Bool(done) = top {
                        let _next = pop(&mut frame.stack);
                        let it = pop(&mut frame.stack);
                        let exc = pop(&mut frame.stack);
                        (it, exc, done)
                    } else {
                        let it = pop(&mut frame.stack);
                        let exc = pop(&mut frame.stack);
                        (it, exc, false)
                    };
                    if !done {
                        let _ = self.iterator_close(&it);
                    }
                    return Err(exc);
                }
                Op::DestructIter => {
                    let v = pop(&mut frame.stack);
                    if v.is_nullish() {
                        let s = if v.is_null() { "null" } else { "undefined" };
                        return Err(self.make_error("TypeError", &format!("cannot read property '\u{0}1' of {}", s)));
                    }
                    let (it, next) = self.get_iterator(&v)?;
                    frame.stack.push(Value::Obj(it));
                    frame.stack.push(next);
                    frame.stack.push(Value::Bool(false));
                }
                Op::IterValue => {
                    let n = frame.stack.len();
                    let done = frame.stack[n - 1].truthy();
                    if done {
                        frame.stack.push(Value::Undefined);
                    } else {
                        let next = frame.stack[n - 2].clone();
                        let it = frame.stack[n - 3].clone();
                        // mark done during the call so errors don't close the iterator
                        frame.stack[n - 1] = Value::Bool(true);
                        let res = self.call(&next, it, &[])?;
                        let ro = match &res {
                            Value::Obj(o) => o.clone(),
                            _ => return Err(self.make_error("TypeError", "iterator result is not an object")),
                        };
                        let d = self.get(&ro, &self.intr.key_done.clone(), &res)?.truthy();
                        if d {
                            frame.stack.push(Value::Undefined);
                        } else {
                            let v = self.get(&ro, &self.intr.key_value.clone(), &res)?;
                            frame.stack[n - 1] = Value::Bool(false);
                            frame.stack.push(v);
                        }
                    }
                }
                Op::IterRest => {
                    let n = frame.stack.len();
                    let mut out = Vec::new();
                    if !frame.stack[n - 1].truthy() {
                        let next = frame.stack[n - 2].clone();
                        let it = frame.stack[n - 3].clone();
                        frame.stack[n - 1] = Value::Bool(true);
                        loop {
                            let res = self.call(&next, it.clone(), &[])?;
                            let ro = match &res {
                                Value::Obj(o) => o.clone(),
                                _ => return Err(self.make_error("TypeError", "iterator result is not an object")),
                            };
                            if self.get(&ro, &self.intr.key_done.clone(), &res)?.truthy() {
                                break;
                            }
                            out.push(self.get(&ro, &self.intr.key_value.clone(), &res)?);
                        }
                    }
                    let a = self.new_array(out);
                    frame.stack.push(Value::Obj(a));
                }
                Op::IterDone => {
                    let done = pop(&mut frame.stack).truthy();
                    let _next = pop(&mut frame.stack);
                    let it = pop(&mut frame.stack);
                    if !done {
                        self.iterator_close(&it)?;
                    }
                }
                Op::ForInStart => {
                    let v = pop(&mut frame.stack);
                    let it = self.for_in_iterator(&v)?;
                    frame.stack.push(Value::Obj(it));
                }
                Op::ForInNext(t) => {
                    let it = frame.stack.last().unwrap().as_obj().unwrap().clone();
                    match self.for_in_next(&it)? {
                        Some(k) => frame.stack.push(Value::Str(k)),
                        None => frame.pc = t as usize,
                    }
                }
                Op::Yield => {
                    let v = pop(&mut frame.stack);
                    frame.resume_mode = ResumeMode::Next;
                    return Ok(Completion::Yield(v));
                }
                Op::GenStart => {
                    return Ok(Completion::GenStart);
                }
                Op::GenResume(t) => {
                    if frame.resume_mode == ResumeMode::Return {
                        frame.resume_mode = ResumeMode::Next;
                        frame.pc = t as usize;
                    }
                }
                Op::Await => {
                    let v = pop(&mut frame.stack);
                    return Ok(Completion::Await(v));
                }
                Op::YieldStar(t, is_async) => {
                    if let Some(c) = self.yield_star_step(frame, t, is_async)? {
                        return Ok(c);
                    }
                }
                Op::AsyncIterValue => {}
                Op::Debugger | Op::Nop => {}
                Op::ImportMeta => {
                    let v = crate::modules::import_meta(self, frame)?;
                    frame.stack.push(v);
                }
                Op::DynamicImport => {
                    let _opts = pop(&mut frame.stack);
                    let spec = pop(&mut frame.stack);
                    let v = crate::modules::dynamic_import(self, frame, spec);
                    frame.stack.push(v);
                }
                Op::CheckObj => {
                    if !frame.stack.last().unwrap().is_object() {
                        return Err(self.make_error("TypeError", "iterator result is not an object"));
                    }
                }
                Op::AddDisposable(is_async) => {
                    let v = frame.stack.last().unwrap().clone();
                    self.add_disposable(frame, v, is_async)?;
                }
                Op::DisposeScope(_) => {}
                Op::GetImport(i) => {
                    let v = crate::modules::get_import(self, frame, i)?;
                    frame.stack.push(v);
                }
                Op::ModuleBodyStart => {
                    return Ok(Completion::GenStart);
                }
                Op::SetCompletion(s) => {
                    let v = pop(&mut frame.stack);
                    frame.locals[s as usize] = v;
                }
                Op::RequireObjCoercible => {
                    if frame.stack.last().unwrap().is_nullish() {
                        return Err(self.make_error("TypeError", "cannot destructure null or undefined"));
                    }
                }
            }
        }
    }

    pub fn tdz_error(&mut self, name: &JsStr) -> Value {
        if name.eq_str("this") {
            return self.make_error("ReferenceError", "cannot access 'this' before initialization");
        }
        self.make_error("ReferenceError", &format!("cannot access '{}' before initialization", name))
    }

    fn yield_star_step(&mut self, frame: &mut Frame, ret_target: u32, is_async: bool) -> JsResult<Option<Completion>> {
        // stack: [iter next received]; frame.resume_mode tells how we were resumed
        // For async generators the awaited results come back through the received slot with
        // an internal state marker stored in frame (handled by async generator driver).
        let n = frame.stack.len();
        let received = frame.stack[n - 1].clone();
        let next = frame.stack[n - 2].clone();
        let it = frame.stack[n - 3].clone();
        let mode = frame.resume_mode;
        frame.resume_mode = ResumeMode::Next;
        let result = match mode {
            ResumeMode::Next => self.call(&next, it.clone(), &[received])?,
            ResumeMode::Throw => {
                let th = self.get_method(&it, &PropKey::from_str("throw"))?;
                match th {
                    Some(f) => self.call(&f, it.clone(), &[received])?,
                    None => {
                        // close iterator then throw TypeError
                        if is_async {
                            let _ = self.iterator_close(&it);
                        } else {
                            self.iterator_close(&it)?;
                        }
                        return Err(self.make_error("TypeError", "The iterator does not provide a 'throw' method"));
                    }
                }
            }
            ResumeMode::Return => {
                let rf = self.get_method(&it, &PropKey::from_str("return"))?;
                match rf {
                    Some(f) => {
                        let r = self.call(&f, it.clone(), &[received])?;
                        let r = if is_async { self.await_sync_hack(r)? } else { r };
                        let ro = match &r {
                            Value::Obj(o) => o.clone(),
                            _ => return Err(self.make_error("TypeError", "iterator result is not an object")),
                        };
                        let done = self.get(&ro, &self.intr.key_done.clone(), &r)?.truthy();
                        if done {
                            let v = self.get(&ro, &self.intr.key_value.clone(), &r)?;
                            frame.stack.truncate(n - 3);
                            frame.stack.push(v);
                            frame.pc = ret_target as usize;
                            return Ok(None);
                        }
                        // not done: yield the result again
                        frame.pc -= 1;
                        frame.resume_mode = ResumeMode::Next;
                        if is_async {
                            let v = self.get(&ro, &self.intr.key_value.clone(), &r)?;
                            frame.stack.pop();
                            return Ok(Some(Completion::Yield(v)));
                        }
                        frame.stack.pop();
                        return Ok(Some(Completion::YieldRaw(r)));
                    }
                    None => {
                        frame.stack.truncate(n - 3);
                        frame.stack.push(received);
                        frame.pc = ret_target as usize;
                        return Ok(None);
                    }
                }
            }
        };
        let result = if is_async { self.await_sync_hack(result)? } else { result };
        let ro = match &result {
            Value::Obj(o) => o.clone(),
            _ => return Err(self.make_error("TypeError", "iterator result is not an object")),
        };
        let done = self.get(&ro, &self.intr.key_done.clone(), &result)?.truthy();
        if done {
            let v = self.get(&ro, &self.intr.key_value.clone(), &result)?;
            frame.stack.truncate(n - 3);
            frame.stack.push(v);
            return Ok(None);
        }
        // suspend: re-execute this op on resume
        frame.pc -= 1;
        frame.stack.pop(); // received slot is re-pushed on resume
        if is_async {
            let v = self.get(&ro, &self.intr.key_value.clone(), &result)?;
            return Ok(Some(Completion::Yield(v)));
        }
        Ok(Some(Completion::YieldRaw(result)))
    }

    /// For async yield*: inner results are promises; we resolve already-settled native promises
    /// synchronously when possible (approximation), otherwise drain microtasks until settled.
    fn await_sync_hack(&mut self, v: Value) -> JsResult<Value> {
        let is_p = matches!(&v, Value::Obj(o) if matches!(o.borrow().kind, ObjKind::Promise(_)));
        if !is_p {
            return Ok(v);
        }
        if let Value::Obj(o) = &v {
            loop {
                let st = match &o.borrow().kind {
                    ObjKind::Promise(p) => p.state.clone(),
                    _ => unreachable!(),
                };
                match st {
                    PromiseState::Fulfilled(x) => return Ok(x),
                    PromiseState::Rejected(x) => {
                        if let ObjKind::Promise(p) = &mut o.borrow_mut().kind {
                            p.is_handled = true;
                        }
                        return Err(x);
                    }
                    PromiseState::Pending => {
                        if !self.run_one_job() {
                            return Ok(Value::Undefined);
                        }
                    }
                }
            }
        }
        Ok(v)
    }

    pub fn run_one_job(&mut self) -> bool {
        match self.jobs.pop_front() {
            Some(j) => {
                self.run_job(j);
                true
            }
            None => false,
        }
    }

    pub fn run_job(&mut self, job: Job) {
        match job {
            Job::Reaction(r, arg) => crate::builtins::promise::run_reaction(self, r, arg),
            Job::ResolveThenable(p, thenable, then) => crate::builtins::promise::run_resolve_thenable(self, p, thenable, then),
            Job::Callback(f, args) => {
                if let Err(e) = self.call(&f, Value::Undefined, &args) {
                    self.report_uncaught(e);
                }
            }
            Job::Native(f, v) => {
                if let Err(e) = f(self, v) {
                    self.report_uncaught(e);
                }
            }
        }
    }

    pub fn run_microtasks(&mut self) {
        while let Some(j) = self.jobs.pop_front() {
            self.run_job(j);
        }
    }

    pub fn report_uncaught(&mut self, e: Value) {
        crate::runtime::report_uncaught(self, &e);
    }

    // ---------------- helpers used by ops ----------------

    pub fn new_array(&self, elems: Vec<Value>) -> Obj {
        Obj::with_class(Some(self.intr.array_proto.clone()), ObjKind::Array(new_array_data(elems)), "Array")
    }

    pub fn new_object(&self) -> Obj {
        Obj::new(Some(self.intr.object_proto.clone()), ObjKind::Ordinary)
    }

    pub fn make_closure(&mut self, code: Rc<FunctionCode>, env: Option<Env>, home: Option<Obj>) -> Obj {
        let proto = if code.is_async && code.is_generator {
            self.intr.async_generator_function_proto.clone()
        } else if code.is_generator {
            self.intr.generator_function_proto.clone()
        } else if code.is_async {
            self.intr.async_function_proto.clone()
        } else {
            self.intr.function_proto.clone()
        };
        let is_class = matches!(code.kind, crate::ast::FuncKind::ClassConstructor | crate::ast::FuncKind::DerivedConstructor);
        let derived = code.kind == crate::ast::FuncKind::DerivedConstructor;
        let f = Obj::with_class(
            Some(proto),
            ObjKind::Closure(Box::new(Closure { code: code.clone(), env, home_object: home, fields: None, this_val: None, is_class_ctor: is_class, derived })),
            "Function",
        );
        {
            let mut b = f.borrow_mut();
            b.props.insert(self.intr.key_length.clone(), Prop::Data { value: Value::Num(code.length as f64), flags: CONFIGURABLE });
            b.props.insert(self.intr.key_name.clone(), Prop::Data { value: Value::Str(code.name.clone()), flags: CONFIGURABLE });
        }
        if code.is_generator {
            let pp = if code.is_async { self.intr.async_generator_proto.clone() } else { self.intr.generator_proto.clone() };
            let p = Obj::new(Some(pp), ObjKind::Ordinary);
            f.set_prop(self.intr.key_prototype.clone(), Value::Obj(p), WRITABLE);
        } else if !code.no_prototype && !is_class && !code.is_arrow {
            let p = Obj::new(Some(self.intr.object_proto.clone()), ObjKind::Ordinary);
            p.set_prop(self.intr.key_constructor.clone(), Value::Obj(f.clone()), WC);
            f.set_prop(self.intr.key_prototype.clone(), Value::Obj(p), WRITABLE);
        }
        f
    }

    pub fn set_function_name(&mut self, f: &Obj, key: &PropKey, prefix: Option<&str>) {
        let base = match key {
            PropKey::Str(s) => s.to_rust_string(),
            PropKey::Sym(s) => match &s.0.description {
                Some(d) => format!("[{}]", d),
                None => String::new(),
            },
        };
        let name = match prefix {
            Some(p) => format!("{} {}", p, base),
            None => base,
        };
        // only set if the function has no own name already (anonymous)
        let has_name = matches!(f.get_own_data(&self.intr.key_name), Some(Value::Str(ref s)) if !s.is_empty());
        if !has_name || prefix.is_some() {
            f.borrow_mut().props.insert(self.intr.key_name.clone(), Prop::Data { value: Value::str(&name), flags: CONFIGURABLE });
        }
    }

    fn define_accessor_part(&mut self, o: &Obj, key: PropKey, f: Value, mk: MKind, flags: u8) {
        let fo = f.as_obj().cloned();
        let mut b = o.borrow_mut();
        let existing = b.props.get(&key).cloned();
        let (mut g, mut s) = match existing {
            Some(Prop::Accessor { get, set, .. }) => (get, set),
            _ => (None, None),
        };
        match mk {
            MKind::Getter => g = fo,
            MKind::Setter => s = fo,
            MKind::Method => {}
        }
        b.props.insert(key, Prop::Accessor { get: g, set: s, flags });
    }

    pub fn create_arguments(&mut self, frame: &Frame) -> Obj {
        let o = Obj::with_class(Some(self.intr.object_proto.clone()), ObjKind::Arguments(Box::new(ArgumentsData { mapped: Vec::new() })), "Arguments");
        {
            let mut b = o.borrow_mut();
            for (i, a) in frame.args.iter().enumerate() {
                b.props.insert(PropKey::from_index(i as u32), Prop::Data { value: a.clone(), flags: WEC });
            }
            b.props.insert(self.intr.key_length.clone(), Prop::Data { value: Value::Num(frame.args.len() as f64), flags: WC });
            b.props.insert(PropKey::Sym(self.intr.sym_iterator.clone()), Prop::Data { value: self.intr.array_values.clone(), flags: WC });
        }
        if frame.code.strict || !frame.code.has_simple_params {
            let thrower = self.intr.throw_type_error.clone();
            o.set_accessor(PropKey::from_str("callee"), Some(thrower.clone()), Some(thrower), 0);
        } else if let Some(f) = &frame.func {
            o.set_prop(PropKey::from_str("callee"), Value::Obj(f.clone()), WC);
        }
        o
    }

    fn get_template_object(&mut self, t: &Rc<TemplateData>) -> Obj {
        if let Some(o) = self.template_cache.get(&t.id) {
            return o.clone();
        }
        let cooked: Vec<Value> = t.cooked.iter().map(|c| c.clone().map(Value::Str).unwrap_or(Value::Undefined)).collect();
        let raw: Vec<Value> = t.raw.iter().map(|r| Value::Str(r.clone())).collect();
        let raw_arr = self.new_array(raw);
        let arr = self.new_array(cooked);
        crate::builtins::object::freeze_obj(self, &raw_arr);
        arr.set_prop(PropKey::from_str("raw"), Value::Obj(raw_arr), 0);
        crate::builtins::object::freeze_obj(self, &arr);
        self.template_cache.insert(t.id, arr.clone());
        arr
    }

    pub fn array_to_vec(&mut self, arr: &Value) -> JsResult<Vec<Value>> {
        if let Value::Obj(o) = arr {
            if let ObjKind::Array(a) = &o.borrow().kind {
                if !a.sparse {
                    return Ok(a.dense.iter().map(|v| if v.is_empty() { Value::Undefined } else { v.clone() }).collect());
                }
            }
        }
        crate::builtins::array::array_like_to_vec(self, arr)
    }

    fn super_call(&mut self, func: &Value, args: &[Value], nt: Value) -> JsResult<Value> {
        let f = match func {
            Value::Obj(o) => o.clone(),
            _ => return self.throw_type("super call outside constructor"),
        };
        let parent = self.get_prototype_of(&f)?;
        match parent {
            Some(p) if p.is_constructor() => self.construct_obj(&p, args, nt),
            _ => self.throw_type("Super constructor is not a constructor"),
        }
    }

    fn super_base(&mut self, frame: &Frame) -> JsResult<Option<Obj>> {
        let home = match &frame.home {
            Some(h) => h.clone(),
            None => return self.throw_syntax("'super' keyword unexpected here"),
        };
        self.get_prototype_of(&home)
    }

    fn super_get(&mut self, frame: &Frame, key: &PropKey, this: &Value) -> JsResult<Value> {
        match self.super_base(frame)? {
            Some(b) => self.get(&b, key, this),
            None => {
                let k = key.to_display();
                self.throw_type(format!("cannot read property '{}' of null", k))
            }
        }
    }

    fn super_set(&mut self, frame: &Frame, key: PropKey, v: Value, this: &Value, strict: bool) -> JsResult<()> {
        match self.super_base(frame)? {
            Some(b) => {
                let ok = self.set(&b, key.clone(), v, this)?;
                if !ok && strict {
                    return self.throw_type(format!("cannot assign to read-only property '{}'", key.to_display()));
                }
                Ok(())
            }
            None => self.throw_type("cannot set property of null"),
        }
    }

    fn private_desc(sym: &Value) -> String {
        match sym {
            Value::Sym(s) => s.0.description.as_ref().map(|d| d.to_rust_string()).unwrap_or_default(),
            _ => String::new(),
        }
    }

    pub fn private_get(&mut self, obj: &Value, sym: &Value) -> JsResult<Value> {
        let s = match sym {
            Value::Sym(s) => s.clone(),
            _ => return self.throw_type("invalid private name"),
        };
        let o = match obj {
            Value::Obj(o) => o.clone(),
            _ => return self.throw_type(format!("cannot read private member {} from an object whose class did not declare it", Self::private_desc(sym))),
        };
        let p = o.borrow().props.get(&PropKey::Sym(s)).cloned();
        match p {
            Some(Prop::Data { value, .. }) => Ok(value),
            Some(Prop::Accessor { get: Some(g), .. }) => self.call_obj(&g, obj.clone(), &[]),
            Some(Prop::Accessor { get: None, .. }) => self.throw_type(format!("'{}' was defined without a getter", Self::private_desc(sym))),
            None => self.throw_type(format!("cannot read private member {} from an object whose class did not declare it", Self::private_desc(sym))),
        }
    }

    pub fn private_set(&mut self, obj: &Value, sym: &Value, v: Value) -> JsResult<()> {
        let s = match sym {
            Value::Sym(s) => s.clone(),
            _ => return self.throw_type("invalid private name"),
        };
        let o = match obj {
            Value::Obj(o) => o.clone(),
            _ => return self.throw_type(format!("cannot write private member {} to an object whose class did not declare it", Self::private_desc(sym))),
        };
        let key = PropKey::Sym(s);
        let p = o.borrow().props.get(&key).cloned();
        match p {
            Some(Prop::Data { flags, .. }) => {
                if flags & WRITABLE == 0 {
                    return self.throw_type(format!("cannot assign to private method {}", Self::private_desc(sym)));
                }
                o.borrow_mut().props.insert(key, Prop::Data { value: v, flags });
                Ok(())
            }
            Some(Prop::Accessor { set: Some(st), .. }) => {
                self.call_obj(&st, obj.clone(), &[v])?;
                Ok(())
            }
            Some(Prop::Accessor { set: None, .. }) => self.throw_type(format!("'{}' was defined without a setter", Self::private_desc(sym))),
            None => self.throw_type(format!("cannot write private member {} to an object whose class did not declare it", Self::private_desc(sym))),
        }
    }

    fn create_class(&mut self, frame: &Frame, ctor_code: Rc<FunctionCode>, heritage: Option<Value>) -> JsResult<(Obj, Obj)> {
        let (proto_parent, ctor_parent) = match &heritage {
            None => (Some(self.intr.object_proto.clone()), self.intr.function_proto.clone()),
            Some(Value::Null) => (None, self.intr.function_proto.clone()),
            Some(h) => {
                let ho = match h {
                    Value::Obj(o) if o.is_constructor() => o.clone(),
                    _ => {
                        let d = self.display_for_error(h);
                        return self.throw_type(format!("Class extends value {} is not a constructor or null", d));
                    }
                };
                let pp = self.get(&ho, &self.intr.key_prototype.clone(), h)?;
                let pp = match pp {
                    Value::Obj(o) => Some(o),
                    Value::Null => None,
                    _ => return self.throw_type("Class extends value does not have valid prototype property"),
                };
                (pp, ho)
            }
        };
        let proto = Obj::new(proto_parent, ObjKind::Ordinary);
        let f = self.make_closure(ctor_code, frame.env.clone(), Some(proto.clone()));
        {
            let mut b = f.borrow_mut();
            b.proto = Some(ctor_parent);
            if let ObjKind::Closure(c) = &mut b.kind {
                c.is_class_ctor = true;
                c.derived = heritage.is_some();
            }
        }
        f.set_prop(self.intr.key_prototype.clone(), Value::Obj(proto.clone()), 0);
        proto.set_prop(self.intr.key_constructor.clone(), Value::Obj(f.clone()), WC);
        Ok((f, proto))
    }

    pub fn display_for_error(&mut self, v: &Value) -> String {
        match v {
            Value::Str(s) => s.to_rust_string(),
            Value::Obj(o) => {
                if o.is_callable() {
                    "function".to_string()
                } else {
                    "[object Object]".to_string()
                }
            }
            Value::Sym(s) => s.descriptive_string(),
            other => self.to_string(other).map(|s| s.to_rust_string()).unwrap_or_default(),
        }
    }

    fn class_target(frame: &Frame, target: MethodTarget) -> (Obj, Obj) {
        let n = frame.stack.len();
        let f = frame.stack[n - 2].as_obj().unwrap().clone();
        let p = frame.stack[n - 1].as_obj().unwrap().clone();
        match target {
            MethodTarget::Proto => (p, f),
            MethodTarget::Ctor => (f, p),
        }
    }

    fn class_define_method(&mut self, frame: &mut Frame, code: &FunctionCode, key: PropKey, target: MethodTarget, mk: MKind, fi: u32) -> JsResult<()> {
        let (t, _) = Self::class_target(frame, target);
        let fcode = code.funcs[fi as usize].clone();
        let unnamed = fcode.name.is_empty();
        let m = self.make_closure(fcode, frame.env.clone(), Some(t.clone()));
        if unnamed {
            let prefix = match mk {
                MKind::Getter => Some("get"),
                MKind::Setter => Some("set"),
                MKind::Method => None,
            };
            self.set_function_name(&m, &key, prefix);
        }
        match mk {
            MKind::Method => {
                let d = PropDesc { value: Some(Value::Obj(m)), writable: Some(true), enumerable: Some(false), configurable: Some(true), get: None, set: None };
                self.define_own_property(&t, key, d)?;
            }
            _ => self.define_accessor_part(&t, key, Value::Obj(m), mk, CONFIGURABLE),
        }
        Ok(())
    }

    fn class_add_field(&mut self, frame: &mut Frame, code: &FunctionCode, key: FieldKey, init: u32) {
        let n = frame.stack.len();
        let f = frame.stack[n - 2].as_obj().unwrap().clone();
        let p = frame.stack[n - 1].as_obj().unwrap().clone();
        let init_fn = if init == u32::MAX {
            None
        } else {
            Some(self.make_closure(code.funcs[init as usize].clone(), frame.env.clone(), Some(p)))
        };
        let mut fb = f.borrow_mut();
        if let ObjKind::Closure(c) = &mut fb.kind {
            let fields = c.fields.get_or_insert_with(|| Rc::new(Vec::new()));
            Rc::make_mut(fields).push(ClassField { key, init: init_fn, is_accessor: false });
        }
    }

    fn class_add_private_method(&mut self, frame: &mut Frame, code: &FunctionCode, sym: Value, fi: u32, mk: MKind, is_static: bool) -> JsResult<()> {
        let s = match sym {
            Value::Sym(s) => s,
            _ => return Ok(()),
        };
        let n = frame.stack.len();
        let f = frame.stack[n - 2].as_obj().unwrap().clone();
        let p = frame.stack[n - 1].as_obj().unwrap().clone();
        let home = if is_static { f.clone() } else { p };
        let m = self.make_closure(code.funcs[fi as usize].clone(), frame.env.clone(), Some(home));
        let key = PropKey::Sym(s.clone());
        if is_static {
            let mut b = f.borrow_mut();
            let existing = b.props.get(&key).cloned();
            let prop = merge_private(existing, m, mk);
            b.props.insert(key, prop);
        } else if let ObjKind::Closure(c) = &mut f.borrow_mut().kind {
            let fields = c.fields.get_or_insert_with(|| Rc::new(Vec::new()));
            let fv = Rc::make_mut(fields);
            // merge getter/setter pairs
            if let Some(pos) = fv.iter().position(|x| matches!(&x.key, FieldKey::PrivateMethod(ss, _) if *ss == s)) {
                if let FieldKey::PrivateMethod(_, existing) = &fv[pos].key {
                    let prop = merge_private(Some(existing.clone()), m, mk);
                    fv[pos].key = FieldKey::PrivateMethod(s, prop);
                }
            } else {
                let prop = merge_private(None, m, mk);
                // private methods go before fields
                let insert_at = fv.iter().position(|x| !matches!(x.key, FieldKey::PrivateMethod(..))).unwrap_or(fv.len());
                fv.insert(insert_at, ClassField { key: FieldKey::PrivateMethod(s, prop), init: None, is_accessor: false });
            }
        }
        Ok(())
    }

    fn class_static_field(&mut self, frame: &mut Frame, code: &FunctionCode, key: FieldKey, init: u32) -> JsResult<()> {
        let n = frame.stack.len();
        let f = frame.stack[n - 2].as_obj().unwrap().clone();
        let v = if init == u32::MAX {
            Value::Undefined
        } else {
            let init_fn = self.make_closure(code.funcs[init as usize].clone(), frame.env.clone(), Some(f.clone()));
            self.call_obj(&init_fn, Value::Obj(f.clone()), &[])?
        };
        match key {
            FieldKey::Key(k) => {
                if !self.create_data_property(&f, k.clone(), v)? {
                    return self.throw_type(format!("Cannot redefine property: {}", k.to_display()));
                }
            }
            FieldKey::Private(s) => {
                f.borrow_mut().props.insert(PropKey::Sym(s), Prop::Data { value: v, flags: WRITABLE });
            }
            _ => {}
        }
        Ok(())
    }

    fn call_maybe_eval(&mut self, frame: &mut Frame, f: &Value, this: Value, args: &[Value]) -> JsResult<Value> {
        if let Value::Obj(fo) = f {
            if fo.ptr_eq(&self.intr.eval_fn) {
                return crate::builtins::global::direct_eval(self, frame, args);
            }
        }
        match f {
            Value::Obj(o) => self.call_obj(o, this, args),
            _ => self.throw_type("eval is not a function"),
        }
    }

    fn add_disposable(&mut self, frame: &mut Frame, v: Value, is_async: bool) -> JsResult<()> {
        if v.is_nullish() {
            return Ok(());
        }
        let key = if is_async { PropKey::Sym(self.intr.sym_async_dispose.clone()) } else { PropKey::Sym(self.intr.sym_dispose.clone()) };
        let m = self.get_method(&v, &key)?;
        match m {
            Some(m) => {
                frame.disposables.push((v, m, is_async));
                Ok(())
            }
            None => self.throw_type("Symbol.dispose is not a function"),
        }
    }

    // ---------------- names ----------------

    pub fn lookup_global(&mut self, key: &PropKey) -> JsResult<Option<Value>> {
        if let PropKey::Str(s) = key {
            if let Some(g) = self.global_lex.get(s) {
                if g.value.is_empty() {
                    return Err(self.tdz_error(s));
                }
                return Ok(Some(g.value.clone()));
            }
        }
        let g = self.global.clone();
        // fast path: own data property
        if let Some(v) = g.get_own_data(key) {
            return Ok(Some(v));
        }
        if self.has_property(&g, key)? {
            let v = self.get(&g, key, &Value::Obj(g.clone()))?;
            return Ok(Some(v));
        }
        Ok(None)
    }

    pub fn get_global(&mut self, key: &PropKey) -> JsResult<Value> {
        match self.lookup_global(key)? {
            Some(v) => Ok(v),
            None => self.throw_ref(format!("{} is not defined", key.to_display())),
        }
    }

    pub fn set_global(&mut self, key: &PropKey, v: Value, strict: bool) -> JsResult<()> {
        if let PropKey::Str(s) = key {
            if let Some(g) = self.global_lex.get_mut(s) {
                if g.value.is_empty() {
                    let s = s.clone();
                    return Err(self.tdz_error(&s));
                }
                if !g.mutable {
                    return self.throw_type(format!("assignment to constant '{}'", s));
                }
                g.value = v;
                return Ok(());
            }
        }
        let g = self.global.clone();
        if strict && !self.has_property(&g, key)? {
            return self.throw_ref(format!("{} is not defined", key.to_display()));
        }
        let ok = self.set(&g, key.clone(), v, &Value::Obj(g.clone()))?;
        if !ok && strict {
            return self.throw_type(format!("cannot assign to read-only property '{}'", key.to_display()));
        }
        Ok(())
    }

    fn declare_global_var(&mut self, frame: &Frame, key: PropKey, _is_fn: bool) -> JsResult<()> {
        // eval inside a function: declare in the function's variable env (extra slots)
        if frame.code.is_script && frame.func.is_some() {
            // not used
        }
        if let Some(env) = self.eval_var_env(frame) {
            let name = key.as_jsstr().unwrap().clone();
            let exists = env.0.info.as_ref().map_or(false, |i| i.find(&name).is_some()) || env.0.extra.borrow().iter().any(|(n, _)| *n == name);
            if !exists {
                env.0.extra.borrow_mut().push((name, Value::Undefined));
            }
            return Ok(());
        }
        let g = self.global.clone();
        if g.borrow().props.contains(&key) {
            return Ok(());
        }
        let d = PropDesc { value: Some(Value::Undefined), writable: Some(true), enumerable: Some(true), configurable: Some(false), get: None, set: None };
        self.define_own_property(&g, key, d)?;
        Ok(())
    }

    /// For sloppy direct eval inside functions: the variable environment receiving `var`s.
    fn eval_var_env(&self, frame: &Frame) -> Option<Env> {
        if !frame.code.is_eval || frame.code.strict {
            return None;
        }
        // eval frames carry the caller env; find the nearest function-level env
        let mut e = frame.env.clone();
        while let Some(env) = e {
            if let Some(info) = &env.0.info {
                if info.is_function {
                    return Some(env);
                }
            }
            e = env.0.parent.clone();
        }
        None
    }

    fn lookup_name(&mut self, frame: &Frame, key: &PropKey) -> JsResult<Option<Value>> {
        let name = key.as_jsstr().unwrap();
        let mut e = frame.env.clone();
        while let Some(env) = e {
            if let Some(o) = &env.0.with_obj {
                if self.has_property(o, key)? && !self.is_unscopable(o, key)? {
                    let v = self.get(o, key, &Value::Obj(o.clone()))?;
                    return Ok(Some(v));
                }
            } else {
                if let Some(info) = &env.0.info {
                    if let Some(i) = info.find(name) {
                        let v = env.0.vars.borrow()[i].clone();
                        if v.is_empty() {
                            return Err(self.tdz_error(name));
                        }
                        return Ok(Some(v));
                    }
                }
                if let Some((_, v)) = env.0.extra.borrow().iter().find(|(n, _)| n == name) {
                    return Ok(Some(v.clone()));
                }
            }
            e = env.0.parent.clone();
        }
        self.lookup_global(key)
    }

    fn is_unscopable(&mut self, o: &Obj, key: &PropKey) -> JsResult<bool> {
        let us = self.get(o, &PropKey::Sym(self.intr.sym_unscopables.clone()), &Value::Obj(o.clone()))?;
        if let Value::Obj(u) = us {
            return Ok(self.get(&u, key, &Value::Obj(u.clone()))?.truthy());
        }
        Ok(false)
    }

    fn get_name(&mut self, frame: &Frame, key: &PropKey) -> JsResult<Value> {
        match self.lookup_name(frame, key)? {
            Some(v) => Ok(v),
            None => self.throw_ref(format!("{} is not defined", key.to_display())),
        }
    }

    fn get_name_for_call(&mut self, frame: &Frame, key: &PropKey) -> JsResult<(Value, Value)> {
        let name = key.as_jsstr().unwrap();
        let mut e = frame.env.clone();
        while let Some(env) = e {
            if let Some(o) = &env.0.with_obj {
                if self.has_property(o, key)? && !self.is_unscopable(o, key)? {
                    let v = self.get(o, key, &Value::Obj(o.clone()))?;
                    return Ok((Value::Obj(o.clone()), v));
                }
            } else {
                if let Some(info) = &env.0.info {
                    if let Some(i) = info.find(name) {
                        let v = env.0.vars.borrow()[i].clone();
                        if v.is_empty() {
                            return Err(self.tdz_error(name));
                        }
                        return Ok((Value::Undefined, v));
                    }
                }
                if let Some((_, v)) = env.0.extra.borrow().iter().find(|(n, _)| n == name) {
                    return Ok((Value::Undefined, v.clone()));
                }
            }
            e = env.0.parent.clone();
        }
        let v = self.get_global(key)?;
        Ok((Value::Undefined, v))
    }

    fn set_name(&mut self, frame: &Frame, key: &PropKey, v: Value, strict: bool) -> JsResult<()> {
        let name = key.as_jsstr().unwrap();
        let mut e = frame.env.clone();
        while let Some(env) = e {
            if let Some(o) = &env.0.with_obj {
                if self.has_property(o, key)? && !self.is_unscopable(o, key)? {
                    self.set(o, key.clone(), v, &Value::Obj(o.clone()))?;
                    return Ok(());
                }
            } else {
                if let Some(info) = &env.0.info {
                    if let Some(i) = info.find(name) {
                        let cur = env.0.vars.borrow()[i].clone();
                        let k = info.kinds[i];
                        if cur.is_empty() && matches!(k, BindKind::Let | BindKind::Const | BindKind::Class) {
                            return Err(self.tdz_error(name));
                        }
                        if k == BindKind::Const {
                            return self.throw_type(format!("assignment to constant '{}'", name));
                        }
                        if k == BindKind::FuncName {
                            if strict {
                                return self.throw_type(format!("assignment to constant '{}'", name));
                            }
                            return Ok(());
                        }
                        env.0.vars.borrow_mut()[i] = v;
                        return Ok(());
                    }
                }
                let mut ex = env.0.extra.borrow_mut();
                if let Some(slot) = ex.iter_mut().find(|(n, _)| n == name) {
                    slot.1 = v;
                    return Ok(());
                }
            }
            e = env.0.parent.clone();
        }
        self.set_global(key, v, strict)
    }

    fn delete_name(&mut self, frame: &Frame, key: &PropKey) -> JsResult<bool> {
        let name = key.as_jsstr().unwrap();
        let mut e = frame.env.clone();
        while let Some(env) = e {
            if let Some(o) = &env.0.with_obj {
                if self.has_property(o, key)? {
                    return self.delete(o, key);
                }
            } else {
                if let Some(info) = &env.0.info {
                    if info.find(name).is_some() {
                        return Ok(false);
                    }
                }
                let mut ex = env.0.extra.borrow_mut();
                if let Some(pos) = ex.iter().position(|(n, _)| n == name) {
                    ex.remove(pos);
                    return Ok(true);
                }
            }
            e = env.0.parent.clone();
        }
        if self.global_lex.contains_key(name) {
            return Ok(false);
        }
        let g = self.global.clone();
        self.delete(&g, key)
    }
}

fn merge_private(existing: Option<Prop>, m: Obj, mk: MKind) -> Prop {
    match mk {
        MKind::Method => Prop::Data { value: Value::Obj(m), flags: 0 },
        MKind::Getter => match existing {
            Some(Prop::Accessor { set, .. }) => Prop::Accessor { get: Some(m), set, flags: 0 },
            _ => Prop::Accessor { get: Some(m), set: None, flags: 0 },
        },
        MKind::Setter => match existing {
            Some(Prop::Accessor { get, .. }) => Prop::Accessor { get, set: Some(m), flags: 0 },
            _ => Prop::Accessor { get: None, set: Some(m), flags: 0 },
        },
    }
}

pub fn trace_name(code: &FunctionCode) -> JsStr {
    if code.name.is_empty() {
        JsStr::from_str("anonymous")
    } else {
        code.name.clone()
    }
}

pub fn array_push_raw(a: &Obj, v: Value) {
    let mut b = a.borrow_mut();
    if let ObjKind::Array(ad) = &mut b.kind {
        if !ad.sparse {
            if ad.dense.len() as u32 == ad.len {
                ad.dense.push(v);
                ad.len += 1;
                return;
            }
        }
        let i = ad.len;
        ad.len += 1;
        if !v.is_empty() {
            drop(b);
            a.set_prop(PropKey::from_index(i), v, WEC);
        }
    }
}

pub fn num_binop(op: Op, x: f64, y: f64) -> Value {
    use crate::builtins::number::{to_int32, to_uint32};
    Value::Num(match op {
        Op::Sub => x - y,
        Op::Mul => x * y,
        Op::Div => x / y,
        Op::Mod => js_fmod(x, y),
        Op::Exp => js_pow(x, y),
        Op::Shl => (to_int32(x).wrapping_shl(to_uint32(y) & 31)) as f64,
        Op::Shr => (to_int32(x) >> (to_uint32(y) & 31)) as f64,
        Op::UShr => (to_uint32(x) >> (to_uint32(y) & 31)) as f64,
        Op::BitAnd => (to_int32(x) & to_int32(y)) as f64,
        Op::BitOr => (to_int32(x) | to_int32(y)) as f64,
        Op::BitXor => (to_int32(x) ^ to_int32(y)) as f64,
        _ => f64::NAN,
    })
}

pub fn js_fmod(x: f64, y: f64) -> f64 {
    if y.is_infinite() && x.is_finite() {
        return x;
    }
    let r = x % y;
    if r == 0.0 && x.is_sign_negative() {
        -0.0
    } else {
        r
    }
}

pub fn js_pow(x: f64, y: f64) -> f64 {
    if y.is_nan() {
        return f64::NAN;
    }
    if y == 0.0 {
        return 1.0;
    }
    if (x == 1.0 || x == -1.0) && y.is_infinite() {
        return f64::NAN;
    }
    x.powf(y)
}

impl Frame {
    pub fn new(code: Rc<FunctionCode>, env: Option<Env>, this: Value, func: Option<Obj>, new_target: Value, args: Vec<Value>, home: Option<Obj>) -> Frame {
        let n = code.nlocals as usize;
        Frame {
            code,
            pc: 0,
            stack: Vec::with_capacity(8),
            locals: vec![Value::Undefined; n],
            env,
            this,
            func,
            new_target,
            args,
            handlers: Vec::new(),
            home,
            resume_mode: ResumeMode::Next,
            pending_throw: None,
            module: None,
            disposables: Vec::new(),
            is_coroutine: false,
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum ProtoKind {
    Object,
    Generator,
    AsyncGenerator,
}

impl Vm {
    pub fn get_prototype_from_ctor(&mut self, nt: &Value, kind: ProtoKind) -> JsResult<Obj> {
        if let Value::Obj(o) = nt {
            let p = self.get(o, &self.intr.key_prototype.clone(), nt)?;
            if let Value::Obj(po) = p {
                return Ok(po);
            }
        }
        Ok(match kind {
            ProtoKind::Object => self.intr.object_proto.clone(),
            ProtoKind::Generator => self.intr.generator_proto.clone(),
            ProtoKind::AsyncGenerator => self.intr.async_generator_proto.clone(),
        })
    }

    fn get_prototype_from_ctor_prop(&mut self, f: &Obj, kind: ProtoKind) -> JsResult<Obj> {
        self.get_prototype_from_ctor(&Value::Obj(f.clone()), kind)
    }

    /// GetPrototypeFromConstructor with a specific intrinsic fallback
    pub fn proto_from_nt(&mut self, nt: &Option<Obj>, fallback: &Obj) -> JsResult<Obj> {
        if let Some(o) = nt {
            let p = self.get(o, &self.intr.key_prototype.clone(), &Value::Obj(o.clone()))?;
            if let Value::Obj(po) = p {
                return Ok(po);
            }
        }
        Ok(fallback.clone())
    }
}
