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
    /// suspended at an async `yield*` delegation (throw resumptions go to the delegate)
    pub yield_star: bool,
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
    /// rejected promises without handlers, in report order (None = freed slot)
    pub unhandled: Vec<Option<Obj>>,
    pub host: crate::runtime::Host,
    pub exit_code: i32,
    pub depth_offset: usize,
    /// strictness of each executing JS frame (innermost last); builtins consult the
    /// innermost entry to pick strict/sloppy failure messages like the reference engine
    pub strict_stack: Vec<bool>,
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

    /// Call a promise resolving function (native) without the call-depth check, so promises
    /// still settle when the stack limit was hit.
    pub fn call_settle(&mut self, f: &Value, v: Value) -> JsResult<Value> {
        if let Value::Obj(o) = f {
            let nf = match &o.borrow().kind {
                ObjKind::Native(n) => Some(n.f),
                _ => None,
            };
            if let Some(nf) = nf {
                return nf(self, &Args { this: Value::Undefined, args: &[v], callee: o, new_target: None });
            }
        }
        self.call(f, Value::Undefined, &[v])
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
        if MULTI_REALM.load(std::sync::atomic::Ordering::Relaxed) {
            let r = fn_realm(o);
            if r != u32::MAX && r != self.intr.realm_id {
                let prev = self.intr.realm_id;
                self.switch_realm(r);
                let res = self.call_obj_in_realm(o, this, args);
                self.switch_realm(prev);
                return res;
            }
        }
        self.call_obj_in_realm(o, this, args)
    }

    fn call_obj_in_realm(&mut self, o: &Obj, this: Value, args: &[Value]) -> JsResult<Value> {
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
            K::NotCallable => self.throw_type("value is not a function"),
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
        self.call_closure_owned(f, code, env, home, this, args.to_vec(), new_target)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn call_closure_owned(
        &mut self,
        f: &Obj,
        code: Rc<FunctionCode>,
        env: Option<Env>,
        home: Option<Obj>,
        this: Value,
        args: Vec<Value>,
        new_target: Value,
    ) -> JsResult<Value> {
        if MULTI_REALM.load(std::sync::atomic::Ordering::Relaxed) {
            let r = fn_realm(f);
            if r != u32::MAX && r != self.intr.realm_id {
                let prev = self.intr.realm_id;
                self.switch_realm(r);
                let res = self.call_closure_owned(f, code, env, home, this, args, new_target);
                self.switch_realm(prev);
                return res;
            }
        }
        let this = if code.strict || code.is_arrow {
            this
        } else {
            match this {
                Value::Undefined | Value::Null => Value::Obj(self.global.clone()),
                Value::Obj(_) => this,
                other => Value::Obj(self.to_object(&other)?),
            }
        };
        let mut frame = Frame::new(code.clone(), env, this, Some(f.clone()), new_target, args, home);
        if code.is_generator {
            return self.start_generator(f, frame);
        }
        if code.is_async {
            return Ok(self.start_async(frame));
        }
        self.enter()?;
        let traced = !matches!(code.kind, crate::ast::FuncKind::ClassFieldInit | crate::ast::FuncKind::StaticBlock);
        if traced {
            self.trace.push(TraceEntry { name: closure_trace_name(f, &code) });
        }
        let r = self.run_frame(&mut frame);
        if traced {
            self.trace.pop();
        }
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
        if MULTI_REALM.load(std::sync::atomic::Ordering::Relaxed) {
            let r = fn_realm(fo);
            if r != u32::MAX && r != self.intr.realm_id {
                let prev = self.intr.realm_id;
                self.switch_realm(r);
                let res = self.construct_obj_in_realm(fo, args, nt);
                self.switch_realm(prev);
                return res;
            }
        }
        self.construct_obj_in_realm(fo, args, nt)
    }

    fn construct_obj_in_realm(&mut self, fo: &Obj, args: &[Value], nt: Value) -> JsResult<Value> {
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
                self.trace.push(TraceEntry { name: closure_trace_name(fo, &code) });
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
                        return self.throw_type("a derived constructor may only return an object or undefined");
                    }
                    if frame.this.is_empty() {
                        return self.throw_ref("derived constructor returned without calling super()");
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
                    return self.throw_type("cannot initialize private methods of a class twice on the same object");
                }
                if !obj.borrow().extensible {
                    return self.throw_type("cannot add private members to a non-extensible object");
                }
                obj.borrow_mut().props.insert(k, prop.clone());
            }
        }
        for f in fields.iter() {
            if let FieldKey::Initializer = &f.key {
                continue;
            }
            let mut v = match &f.init {
                Some(init) => self.call_obj(init, Value::Obj(obj.clone()), &[])?,
                None => Value::Undefined,
            };
            for ini in &f.extra_inits {
                v = self.call(ini, Value::Obj(obj.clone()), &[v])?;
            }
            match &f.key {
                FieldKey::Key(k) => {
                    if !self.create_data_property(obj, k.clone(), v)? {
                        return self.throw_type(format!("cannot define element '{}'", k.to_err_display()));
                    }
                }
                FieldKey::Private(sym) => {
                    let k = PropKey::Sym(sym.clone());
                    if obj.borrow().props.contains(&k) {
                        return self.throw_type("cannot initialize the same private field twice");
                    }
                    if !obj.borrow().extensible {
                        return self.throw_type("cannot add a private field to a non-extensible object");
                    }
                    obj.borrow_mut().props.insert(k, Prop::Data { value: v, flags: WRITABLE });
                }
                FieldKey::PrivateMethod(..) | FieldKey::Initializer => {}
            }
        }
        // decorator initializers run after all fields
        for f in fields.iter() {
            if let (FieldKey::Initializer, Some(init)) = (&f.key, &f.init) {
                self.call_obj(init, Value::Obj(obj.clone()), &[])?;
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
                        return self.throw_type("Generator method called on a non-generator");
                    }
                    let fr = if st == GenState::Completed { None } else { g.frame.take() };
                    if fr.is_some() {
                        g.state = GenState::Executing;
                    }
                    (st, fr)
                }
                _ => {
                    drop(b);
                    return self.throw_type("Generator method called on a non-generator");
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
        let at_yield_star = matches!(frame.code.ops.get(frame.pc), Some(Op::YieldStar(..)));
        match mode {
            ResumeMode::Throw if !at_yield_star => frame.pending_throw = Some(value),
            _ => {
                if state != GenState::SuspendedStart {
                    frame.stack.push(value);
                }
            }
        }
        frame.resume_mode = mode;
        // (the resumption itself does not count towards the call depth: the reference engine
        // counts the `next` call only)
        let r = self.run_frame(&mut frame);
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
                let n = match &frame.func {
                    Some(f) => closure_trace_name(f, &frame.code),
                    None => trace_name(&frame.code),
                };
                self.trace.push(TraceEntry { name: n });
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
                let _ = self.call_settle(&cap.resolve, v);
            }
            Ok(_) => {
                let _ = self.call_settle(&cap.resolve, Value::Undefined);
            }
            Err(e) => {
                let _ = self.call_settle(&cap.reject, e);
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
        self.strict_stack.push(frame.code.strict);
        let r = self.run_frame_inner(frame);
        self.strict_stack.pop();
        r
    }

    fn run_frame_inner(&mut self, frame: &mut Frame) -> Result<Completion, Value> {
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

    /// Is the innermost executing JS code strict?
    pub fn caller_strict(&self) -> bool {
        self.strict_stack.last().copied().unwrap_or(false)
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
                Op::SetLocalChk(s, n) => {
                    if frame.locals[s as usize].is_empty() {
                        return Err(self.tdz_error(&code.strings[n as usize]));
                    }
                    frame.locals[s as usize] = frame.stack.last().unwrap().clone();
                }
                Op::UpdateLocal(s, flags, n) => {
                    let old = match &frame.locals[s as usize] {
                        Value::Num(x) => Value::Num(*x),
                        Value::Empty if n != u32::MAX => return Err(self.tdz_error(&code.strings[n as usize])),
                        Value::BigInt(_) => frame.locals[s as usize].clone(),
                        other => {
                            let other = other.clone();
                            self.to_numeric(&other)?
                        }
                    };
                    let new = match &old {
                        Value::Num(x) => Value::Num(if flags & 1 != 0 { x + 1.0 } else { x - 1.0 }),
                        Value::BigInt(b) => {
                            let one = crate::bigint::BigInt::from_i64(if flags & 1 != 0 { 1 } else { -1 });
                            Value::BigInt(Rc::new(b.add(&one)))
                        }
                        _ => Value::Num(f64::NAN),
                    };
                    frame.locals[s as usize] = new.clone();
                    frame.stack.push(if flags & 2 != 0 { new } else { old });
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
                Op::DeclareAnnexBVar(k) => {
                    let key = code.keys[k as usize].clone();
                    self.declare_global_var(frame, key, true)?;
                }
                Op::GlobalCheck(k, mode) => {
                    let key = code.keys[k as usize].clone();
                    self.global_decl_check(frame, &key, mode)?;
                }
                Op::SetVarBinding(k, init) => {
                    let v = frame.stack.last().unwrap().clone();
                    let key = code.keys[k as usize].clone();
                    self.set_var_binding(frame, &key, v, init)?;
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
                Op::ThisChkReturn => {
                    if frame.this.is_empty() {
                        return Err(self.make_error("ReferenceError", "derived constructor returned without calling super()"));
                    }
                    frame.stack.push(frame.this.clone());
                }
                Op::SetThis | Op::BindThis => {
                    let v = pop(&mut frame.stack);
                    if !frame.this.is_empty() {
                        return Err(self.make_error("ReferenceError", "super() may only be called once"));
                    }
                    frame.this = v;
                }
                Op::BindThisEnv(d, s) => {
                    let v = pop(&mut frame.stack);
                    let e = frame.env.as_ref().unwrap().ancestor(d).clone();
                    if !e.0.vars.borrow()[s as usize].is_empty() {
                        return Err(self.make_error("ReferenceError", "super() may only be called once"));
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
                    let k = self.to_property_key(&key)?;
                    if obj.is_nullish() {
                        return Err(self.make_error("TypeError", &format!("cannot delete property '{}' of null or undefined", k.to_err_display())));
                    }
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
                        _ => return Err(self.make_error("TypeError", "the right-hand side of 'in' must be an object")),
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
                    let items = self.iterate_spread(&it, "value is not iterable")?;
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
                Op::DecStart => {
                    let n = frame.stack.len();
                    let f = frame.stack[n - 2].as_obj().unwrap().clone();
                    DEC_STACK.with(|s| s.borrow_mut().push(DecState { f, statics: Vec::new(), class_inits: Vec::new() }));
                }
                Op::Decorate(kf, key_slot, val_slot) => {
                    let dec = pop(&mut frame.stack);
                    let n = frame.stack.len();
                    let f = frame.stack[n - 2].as_obj().unwrap().clone();
                    let key = frame.locals[key_slot as usize].clone();
                    let value = frame.locals[val_slot as usize].clone();
                    let kind = kf & 15;
                    let arg = match kind {
                        3 => Value::Undefined,
                        _ => value.clone(),
                    };
                    let r = self.apply_member_decorator(&f, dec, kind, kf & 16 != 0, kf & 32 != 0, &key, arg)?;
                    match kind {
                        3 => {
                            // field: collect the returned initializer
                            if !r.is_undefined() {
                                if let Value::Obj(a) = &value {
                                    array_push_raw(a, r);
                                }
                            }
                        }
                        4 => {
                            // auto-accessor: replacement get/set and an initializer
                            if let (Value::Obj(ro), Value::Obj(pair)) = (&r, &value) {
                                // (a new pair: the decorator may keep using the one it was given)
                                let np = self.new_object();
                                for k in ["get", "set"] {
                                    let mut nv = self.get_str(ro, k)?;
                                    if nv.is_undefined() {
                                        nv = pair.get_own_data(&PropKey::from_str(k)).unwrap_or(Value::Undefined);
                                    } else if !nv.is_callable() {
                                        return self.throw_type(format!("accessor.{} must be a function", k));
                                    }
                                    np.set_prop(PropKey::from_str(k), nv, WEC);
                                }
                                frame.locals[val_slot as usize] = Value::Obj(np);
                                let init = self.get_str(ro, "init")?;
                                if !init.is_undefined() {
                                    if !init.is_callable() {
                                        return self.throw_type("accessor.init must be a function");
                                    }
                                    if let Value::Obj(a) = &frame.locals[val_slot as usize + 1] {
                                        array_push_raw(a, init);
                                    }
                                }
                            }
                        }
                        _ => frame.locals[val_slot as usize] = r,
                    }
                }
                Op::DecorateClass(ni) => {
                    let dec = pop(&mut frame.stack);
                    let n = frame.stack.len();
                    let f = frame.stack[n - 2].clone();
                    let name = Value::Str(code.strings[ni as usize].clone());
                    let r = self.apply_class_decorator(dec, f, name)?;
                    frame.stack[n - 2] = r;
                }
                Op::DecFinish => {
                    let st = DEC_STACK.with(|s| s.borrow_mut().pop());
                    if let Some(st) = st {
                        let n = frame.stack.len();
                        let f = frame.stack[n - 2].clone();
                        for ini in &st.statics {
                            self.call(ini, Value::Obj(st.f.clone()), &[])?;
                        }
                        for ini in &st.class_inits {
                            self.call(ini, f.clone(), &[])?;
                        }
                    }
                }
                Op::MakeMethod(target, mk, fi, key_slot) => {
                    let (t, _) = Self::class_target(frame, target);
                    let fcode = code.funcs[fi as usize].clone();
                    let unnamed = fcode.name.is_empty();
                    let m = self.make_closure(fcode, frame.env.clone(), Some(t));
                    if unnamed {
                        let prefix = match mk {
                            MKind::Getter => Some("get"),
                            MKind::Setter => Some("set"),
                            MKind::Method => None,
                        };
                        let kv = frame.locals[key_slot as usize].clone();
                        let key = self.to_property_key(&kv)?;
                        self.set_function_name(&m, &key, prefix);
                    }
                    frame.stack.push(Value::Obj(m));
                }
                Op::DefineMethodValue(target, mk) => {
                    let m = pop(&mut frame.stack);
                    let kv = pop(&mut frame.stack);
                    let key = self.to_property_key(&kv)?;
                    let (t, _) = Self::class_target(frame, target);
                    match mk {
                        MKind::Method => {
                            let d = PropDesc { value: Some(m), writable: Some(true), enumerable: Some(false), configurable: Some(true), get: None, set: None };
                            self.define_own_property(&t, key, d)?;
                        }
                        _ => self.define_accessor_part(&t, key, m, mk, CONFIGURABLE),
                    }
                }
                Op::AddPrivateMethodValue(mk, is_static) => {
                    let m = pop(&mut frame.stack);
                    let sym = pop(&mut frame.stack);
                    if let (Value::Sym(s), Value::Obj(mo)) = (sym, m) {
                        self.class_add_private_value(frame, s, mo, mk, is_static);
                    }
                }
                Op::MakeAutoAccessor => {
                    let storage = pop(&mut frame.stack);
                    let kv = pop(&mut frame.stack);
                    let key = match &kv {
                        Value::Sym(s) if s.is_private() => PropKey::Sym(s.clone()),
                        _ => self.to_property_key(&kv)?,
                    };
                    let g = self.native_closure("", 0, auto_accessor_get, vec![storage.clone()]);
                    self.set_function_name(&g, &key, Some("get"));
                    let s = self.native_closure("", 1, auto_accessor_set, vec![storage]);
                    self.set_function_name(&s, &key, Some("set"));
                    let pair = self.new_object();
                    pair.set_prop(PropKey::from_str("get"), Value::Obj(g), WEC);
                    pair.set_prop(PropKey::from_str("set"), Value::Obj(s), WEC);
                    frame.stack.push(Value::Obj(pair));
                }
                Op::DefineAccessorPair(target) => {
                    let pair = pop(&mut frame.stack);
                    let kv = pop(&mut frame.stack);
                    let key = self.to_property_key(&kv)?;
                    let (t, _) = Self::class_target(frame, target);
                    if let Value::Obj(p) = &pair {
                        let g = p.get_own_data(&PropKey::from_str("get")).unwrap_or(Value::Undefined);
                        let s = p.get_own_data(&PropKey::from_str("set")).unwrap_or(Value::Undefined);
                        let d = PropDesc { value: None, writable: None, enumerable: Some(false), configurable: Some(true), get: Some(g), set: Some(s) };
                        self.define_own_property(&t, key, d)?;
                    }
                }
                Op::AddPrivateAccessorPair(is_static) => {
                    let pair = pop(&mut frame.stack);
                    let sym = pop(&mut frame.stack);
                    if let (Value::Sym(s), Value::Obj(p)) = (sym, pair) {
                        if let Some(Value::Obj(g)) = p.get_own_data(&PropKey::from_str("get")) {
                            self.class_add_private_value(frame, s.clone(), g, MKind::Getter, is_static);
                        }
                        if let Some(Value::Obj(st)) = p.get_own_data(&PropKey::from_str("set")) {
                            self.class_add_private_value(frame, s, st, MKind::Setter, is_static);
                        }
                    }
                }
                Op::SetDecPending => {
                    let v = pop(&mut frame.stack);
                    DEC_PENDING.with(|p| *p.borrow_mut() = Some(v));
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
                        Value::Obj(o) => {
                            // fast path: ordinary (non-class) closures take the argument vector
                            let fast = match &o.borrow().kind {
                                ObjKind::Closure(c) if !c.is_class_ctor => Some((c.code.clone(), c.env.clone(), c.home_object.clone())),
                                _ => None,
                            };
                            match fast {
                                Some((fcode, env, home)) => self.call_closure_owned(o, fcode, env, home, this, args, Value::Undefined)?,
                                None if o.is_callable() => self.call_obj(o, this, &args)?,
                                None => {
                                    let d = if desc == u32::MAX { self.describe_for_call(&f) } else { code.strings[desc as usize].to_rust_string() };
                                    return Err(self.make_error("TypeError", &format!("{} is not a function", d)));
                                }
                            }
                        }
                        _ => {
                            let d = if desc == u32::MAX { self.describe_for_call(&f) } else { code.strings[desc as usize].to_rust_string() };
                            return Err(self.make_error("TypeError", &format!("{} is not a function", d)));
                        }
                    };
                    frame.stack.push(r);
                }
                Op::TailCall(argc, desc) => {
                    let argc = argc as usize;
                    let len = frame.stack.len();
                    let args: Vec<Value> = frame.stack.drain(len - argc..).collect();
                    let f = pop(&mut frame.stack);
                    let this = pop(&mut frame.stack);
                    let r = match &f {
                        Value::Obj(o) if o.is_callable() => {
                            let elide = frame.new_target.is_undefined();
                            let saved = if elide { (self.trace.pop(), self.strict_stack.pop()) } else { (None, None) };
                            let r = self.call_obj(o, this, &args);
                            if let Some(t) = saved.0 {
                                self.trace.push(t);
                            }
                            if let Some(s) = saved.1 {
                                self.strict_stack.push(s);
                            }
                            r?
                        }
                        _ => {
                            let d = if desc == u32::MAX { self.describe_for_call(&f) } else { code.strings[desc as usize].to_rust_string() };
                            return Err(self.make_error("TypeError", &format!("{} is not a function", d)));
                        }
                    };
                    frame.stack.push(r);
                }
                Op::TailCallArray(desc) => {
                    let arr = pop(&mut frame.stack);
                    let f = pop(&mut frame.stack);
                    let this = pop(&mut frame.stack);
                    let args = self.array_to_vec(&arr)?;
                    let r = match &f {
                        Value::Obj(o) if o.is_callable() => {
                            let elide = frame.new_target.is_undefined();
                            let saved = if elide { (self.trace.pop(), self.strict_stack.pop()) } else { (None, None) };
                            let r = self.call_obj(o, this, &args);
                            if let Some(t) = saved.0 {
                                self.trace.push(t);
                            }
                            if let Some(s) = saved.1 {
                                self.strict_stack.push(s);
                            }
                            r?
                        }
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
                    if !frame.this.is_empty() && self.super_call_again(&func, &frame.this.clone(), &args, nt.clone())? {
                        return Err(self.make_error("ReferenceError", "super() may only be called once"));
                    }
                    let r = self.super_call(&func, &args, nt)?;
                    frame.stack.push(r);
                }
                Op::SuperCallArray => {
                    let arr = pop(&mut frame.stack);
                    let nt = pop(&mut frame.stack);
                    let func = frame.stack.last().unwrap().clone();
                    let args = self.array_to_vec(&arr)?;
                    if !frame.this.is_empty() && self.super_call_again(&func, &frame.this.clone(), &args, nt.clone())? {
                        return Err(self.make_error("ReferenceError", "super() may only be called once"));
                    }
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
                Op::AsyncYieldStarCall(t_ret) => {
                    // [iter next received]
                    let received = pop(&mut frame.stack);
                    let n = frame.stack.len();
                    let next = frame.stack[n - 1].clone();
                    let it = frame.stack[n - 2].clone();
                    let mode = frame.resume_mode;
                    frame.resume_mode = ResumeMode::Next;
                    match mode {
                        ResumeMode::Next => {
                            let r = self.call(&next, it, &[received])?;
                            frame.stack.push(Value::Num(0.0));
                            frame.stack.push(r);
                        }
                        ResumeMode::Throw => match self.get_method(&it, &PropKey::from_str("throw"))? {
                            Some(f) => {
                                let r = self.call(&f, it, &[received])?;
                                frame.stack.push(Value::Num(0.0));
                                frame.stack.push(r);
                            }
                            None => match self.get_method(&it, &PropKey::from_str("return"))? {
                                Some(rf) => {
                                    let r = self.call(&rf, it, &[])?;
                                    frame.stack.push(Value::Num(2.0));
                                    frame.stack.push(r);
                                }
                                None => return Err(self.make_error("TypeError", "the delegated iterator has no 'throw' method")),
                            },
                        },
                        ResumeMode::Return => match self.get_method(&it, &PropKey::from_str("return"))? {
                            None => {
                                frame.stack.truncate(n - 2);
                                frame.stack.push(received);
                                frame.pc = t_ret as usize;
                            }
                            Some(rf) => {
                                let r = self.call(&rf, it, &[received])?;
                                frame.stack.push(Value::Num(1.0));
                                frame.stack.push(r);
                            }
                        },
                    }
                }
                Op::AsyncYieldStarResult(t_done, t_ret) => {
                    // [iter next mode result]
                    let res = pop(&mut frame.stack);
                    let mode = pop(&mut frame.stack);
                    let ro = match &res {
                        Value::Obj(o) => o.clone(),
                        _ => return Err(self.make_error("TypeError", "iterator result is not an object")),
                    };
                    if let Value::Num(m) = mode {
                        if m == 2.0 {
                            return Err(self.make_error("TypeError", "the delegated iterator has no 'throw' method"));
                        }
                    }
                    let done = self.get(&ro, &self.intr.key_done.clone(), &res)?.truthy();
                    let v = self.get(&ro, &self.intr.key_value.clone(), &res)?;
                    if done {
                        let n = frame.stack.len();
                        frame.stack.truncate(n - 2);
                        frame.stack.push(v);
                        frame.pc = if matches!(mode, Value::Num(m) if m == 1.0) { t_ret as usize } else { t_done as usize };
                    } else {
                        frame.stack.push(v);
                    }
                }
                Op::YieldStarYield => {
                    let v = pop(&mut frame.stack);
                    frame.yield_star = true;
                    frame.resume_mode = ResumeMode::Next;
                    return Ok(Completion::Yield(v));
                }
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
                Op::AddDisposableConsume(is_async) => {
                    let v = pop(&mut frame.stack);
                    self.add_disposable(frame, v, is_async)?;
                }
                Op::DisposeMark(s) => {
                    frame.locals[s as usize] = Value::Num(frame.disposables.len() as f64);
                }
                Op::DisposeResources(s, is_async) | Op::DisposeResourcesThrow(s, is_async) => {
                    let initial = if let Op::DisposeResourcesThrow(..) = op { Some(pop(&mut frame.stack)) } else { None };
                    let mark = match &frame.locals[s as usize] {
                        Value::Num(n) => *n as usize,
                        _ => 0,
                    };
                    let mark = mark.min(frame.disposables.len());
                    let items: Vec<(Value, Value, bool)> = frame.disposables.drain(mark..).collect();
                    if is_async {
                        let list = items.into_iter().map(|(v, m, a)| (v, m, 0u8, a)).collect();
                        let p = crate::builtins::disposable::dispose_async(self, list, initial);
                        frame.stack.push(p);
                    } else {
                        let list = items.into_iter().map(|(v, m, _)| (v, m, 0u8)).collect();
                        if let Some(e) = crate::builtins::disposable::dispose_sync(self, list, initial) {
                            return Err(e);
                        }
                    }
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
        if name.eq_str("%derived-return") {
            return self.make_error("ReferenceError", "derived constructor returned without calling super()");
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
                        return Err(self.make_error("TypeError", "the delegated iterator has no 'throw' method"));
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
            ObjKind::Closure(Box::new(Closure { code: code.clone(), env, home_object: home, fields: None, this_val: None, is_class_ctor: is_class, derived, realm: self.intr.realm_id })),
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
        let mut mapped = Vec::new();
        if !frame.code.mapped_args.is_empty() {
            if let Some(env) = &frame.env {
                let n = frame.args.len().min(frame.code.mapped_args.len());
                for i in 0..n {
                    let slot = frame.code.mapped_args[i];
                    mapped.push(if slot == u32::MAX { None } else { Some((env.clone(), slot)) });
                }
            }
        }
        let o = Obj::with_class(Some(self.intr.object_proto.clone()), ObjKind::Arguments(Box::new(ArgumentsData { mapped })), "Arguments");
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

    /// A second `super()` in a derived constructor: the reference engine re-runs a base class
    /// constructor on the already-bound `this` (re-initializing its fields) before reporting
    /// "super() may only be called once".
    fn super_call_again(&mut self, func: &Value, this: &Value, args: &[Value], nt: Value) -> JsResult<bool> {
        let f = match func {
            Value::Obj(o) => o.clone(),
            _ => return Ok(false),
        };
        let parent = match self.get_prototype_of(&f)? {
            Some(p) => p,
            None => return Ok(false),
        };
        let info = match &parent.borrow().kind {
            ObjKind::Closure(c) if c.is_class_ctor && !c.derived => Some((c.code.clone(), c.env.clone(), c.home_object.clone(), c.fields.clone())),
            _ => None,
        };
        let (code, env, home, fields) = match info {
            Some(x) => x,
            None => return Ok(false),
        };
        let this_obj = match this {
            Value::Obj(o) => o.clone(),
            _ => return Ok(false),
        };
        if let Some(fl) = &fields {
            self.init_fields(&this_obj, fl)?;
        }
        let mut frame = Frame::new(code.clone(), env, this.clone(), Some(parent.clone()), nt, args.to_vec(), home);
        self.enter()?;
        self.trace.push(TraceEntry { name: closure_trace_name(&parent, &code) });
        let r = self.run_frame(&mut frame);
        self.trace.pop();
        self.depth -= 1;
        r?;
        Ok(true)
    }

    fn super_call(&mut self, func: &Value, args: &[Value], nt: Value) -> JsResult<Value> {
        let f = match func {
            Value::Obj(o) => o.clone(),
            _ => return self.throw_type("super call outside constructor"),
        };
        let parent = self.get_prototype_of(&f)?;
        match parent {
            Some(p) if p.is_constructor() => self.construct_obj(&p, args, nt),
            _ => self.throw_type("super constructor is not a constructor"),
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
            Some(Prop::Accessor { get: None, .. }) => self.throw_type(format!("private accessor {} has no getter", Self::private_desc(sym))),
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
                    return self.throw_type(format!("private method {} is not writable", Self::private_desc(sym)));
                }
                o.borrow_mut().props.insert(key, Prop::Data { value: v, flags });
                Ok(())
            }
            Some(Prop::Accessor { set: Some(st), .. }) => {
                self.call_obj(&st, obj.clone(), &[v])?;
                Ok(())
            }
            Some(Prop::Accessor { set: None, .. }) => self.throw_type(format!("private accessor {} has no setter", Self::private_desc(sym))),
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
                        return self.throw_type("Class extends value is not a constructor or null");
                    }
                };
                let pp = self.get(&ho, &self.intr.key_prototype.clone(), h)?;
                let pp = match pp {
                    Value::Obj(o) => Some(o),
                    Value::Null => None,
                    _ => return self.throw_type("Class extends value does not have a valid prototype property"),
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
            let extra_inits = take_dec_pending();
            Rc::make_mut(fields).push(ClassField { key, init: init_fn, is_accessor: false, extra_inits });
        }
    }

    /// add a private method/accessor function (already created) to a class
    fn class_add_private_value(&mut self, frame: &mut Frame, s: Sym, m: Obj, mk: MKind, is_static: bool) {
        let n = frame.stack.len();
        let f = frame.stack[n - 2].as_obj().unwrap().clone();
        let key = PropKey::Sym(s.clone());
        if is_static {
            let mut b = f.borrow_mut();
            let existing = b.props.get(&key).cloned();
            let prop = merge_private(existing, m, mk);
            b.props.insert(key, prop);
        } else if let ObjKind::Closure(c) = &mut f.borrow_mut().kind {
            let fields = c.fields.get_or_insert_with(|| Rc::new(Vec::new()));
            let fv = Rc::make_mut(fields);
            if let Some(pos) = fv.iter().position(|x| matches!(&x.key, FieldKey::PrivateMethod(ss, _) if *ss == s)) {
                if let FieldKey::PrivateMethod(_, existing) = &fv[pos].key {
                    let prop = merge_private(Some(existing.clone()), m, mk);
                    fv[pos].key = FieldKey::PrivateMethod(s, prop);
                }
            } else {
                let prop = merge_private(None, m, mk);
                let insert_at = fv.iter().position(|x| !matches!(x.key, FieldKey::PrivateMethod(..))).unwrap_or(fv.len());
                fv.insert(insert_at, ClassField { key: FieldKey::PrivateMethod(s, prop), init: None, is_accessor: false, extra_inits: Vec::new() });
            }
        }
    }

    /// Call a class element decorator with its context object; validates the result.
    #[allow(clippy::too_many_arguments)]
    fn apply_member_decorator(&mut self, f: &Obj, dec: Value, kind: u8, is_static: bool, is_private: bool, key: &Value, value: Value) -> JsResult<Value> {
        if !dec.is_callable() {
            return self.throw_type("decorator is not callable");
        }
        let kind_name = match kind {
            0 => "method",
            1 => "getter",
            2 => "setter",
            3 => "field",
            _ => "accessor",
        };
        let name = match key {
            Value::Sym(s) if s.is_private() => Value::Str(s.0.description.clone().unwrap_or_else(JsStr::empty)),
            Value::Sym(_) => key.clone(),
            other => Value::Str(self.to_string(other)?),
        };
        let ctx = self.new_object();
        ctx.set_prop(PropKey::from_str("kind"), Value::str(kind_name), WEC);
        ctx.set_prop(PropKey::from_str("name"), name, WEC);
        ctx.set_prop(PropKey::from_str("static"), Value::Bool(is_static), WEC);
        ctx.set_prop(PropKey::from_str("private"), Value::Bool(is_private), WEC);
        let access = self.new_object();
        let slots = vec![key.clone(), Value::Bool(is_private)];
        if kind != 2 {
            let g = self.native_closure("get", 1, dec_access_get, slots.clone());
            access.set_prop(PropKey::from_str("get"), Value::Obj(g), WEC);
        }
        if kind >= 2 {
            let s = self.native_closure("set", 2, dec_access_set, slots);
            access.set_prop(PropKey::from_str("set"), Value::Obj(s), WEC);
        }
        ctx.set_prop(PropKey::from_str("access"), Value::Obj(access), WEC);
        let add = self.native_closure("addInitializer", 1, dec_add_initializer, vec![Value::Obj(f.clone()), Value::Num(if is_static { 1.0 } else { 0.0 })]);
        ctx.set_prop(PropKey::from_str("addInitializer"), Value::Obj(add), WEC);
        ctx.set_prop(PropKey::from_str("metadata"), Value::Undefined, WEC);
        let r = self.call(&dec, Value::Undefined, &[value.clone(), Value::Obj(ctx)])?;
        match kind {
            3 => {
                if !r.is_undefined() && !r.is_callable() {
                    return self.throw_type("field decorator must return a function or undefined");
                }
                Ok(r)
            }
            4 => {
                if !r.is_undefined() && !r.is_object() {
                    return self.throw_type("accessor decorator must return an object or undefined");
                }
                Ok(r)
            }
            _ => {
                if r.is_undefined() {
                    return Ok(value);
                }
                if !r.is_callable() {
                    return self.throw_type("decorator must return a function or undefined");
                }
                Ok(r)
            }
        }
    }

    /// Call a class decorator; returns the (possibly replaced) class.
    fn apply_class_decorator(&mut self, dec: Value, f: Value, name: Value) -> JsResult<Value> {
        if !dec.is_callable() {
            return self.throw_type("decorator is not callable");
        }
        let fo = DEC_STACK.with(|s| s.borrow().last().map(|st| st.f.clone()));
        let ctx = self.new_object();
        ctx.set_prop(PropKey::from_str("kind"), Value::str("class"), WEC);
        ctx.set_prop(PropKey::from_str("name"), name, WEC);
        ctx.set_prop(PropKey::from_str("static"), Value::Bool(false), WEC);
        ctx.set_prop(PropKey::from_str("private"), Value::Bool(false), WEC);
        let access = self.new_object();
        ctx.set_prop(PropKey::from_str("access"), Value::Obj(access), WEC);
        let owner = fo.map(Value::Obj).unwrap_or_else(|| f.clone());
        let add = self.native_closure("addInitializer", 1, dec_add_initializer, vec![owner, Value::Num(2.0)]);
        ctx.set_prop(PropKey::from_str("addInitializer"), Value::Obj(add), WEC);
        ctx.set_prop(PropKey::from_str("metadata"), Value::Undefined, WEC);
        let r = self.call(&dec, Value::Undefined, &[f.clone(), Value::Obj(ctx)])?;
        if r.is_undefined() {
            return Ok(f);
        }
        if !r.is_callable() {
            return self.throw_type("decorator must return a function or undefined");
        }
        Ok(r)
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
                fv.insert(insert_at, ClassField { key: FieldKey::PrivateMethod(s, prop), init: None, is_accessor: false, extra_inits: Vec::new() });
            }
        }
        Ok(())
    }

    fn class_static_field(&mut self, frame: &mut Frame, code: &FunctionCode, key: FieldKey, init: u32) -> JsResult<()> {
        let n = frame.stack.len();
        let f = frame.stack[n - 2].as_obj().unwrap().clone();
        let extra_inits = take_dec_pending();
        let mut v = if init == u32::MAX {
            Value::Undefined
        } else {
            let init_fn = self.make_closure(code.funcs[init as usize].clone(), frame.env.clone(), Some(f.clone()));
            self.call_obj(&init_fn, Value::Obj(f.clone()), &[])?
        };
        for ini in &extra_inits {
            v = self.call(ini, Value::Obj(f.clone()), &[v])?;
        }
        match key {
            FieldKey::Key(k) => {
                // (the reference engine ignores failures to define static fields)
                let _ = self.create_data_property(&f, k.clone(), v)?;
            }
            FieldKey::Private(s) => {
                if !f.borrow().extensible {
                    return self.throw_type("cannot add a private field to a non-extensible object");
                }
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
        // (`await using` falls back to Symbol.dispose)
        let m = match crate::builtins::disposable::dispose_method(self, &v, is_async)? {
            Some(m) => m,
            None => return Ok(()),
        };
        frame.disposables.push((v, m, is_async));
        Ok(())
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

    /// Declare a `var` of a script or sloppy eval code in its variable environment.
    /// `annexb`: the var binding of an Annex B block-level function in eval code, which is
    /// skipped when it would conflict with a lexical binding (or cannot be created).
    fn declare_global_var(&mut self, frame: &Frame, key: PropKey, annexb: bool) -> JsResult<()> {
        if annexb {
            let name = key.as_jsstr().unwrap().clone();
            if self.eval_var_conflict(frame, &name, false) {
                return Ok(());
            }
            if self.eval_var_env(frame).is_none() {
                let g = self.global.clone();
                let b = g.borrow();
                if !b.props.contains(&key) && !b.extensible {
                    return Ok(());
                }
            }
        }
        // eval inside a function: declare in the function's variable env (extra slots)
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
        // vars created by eval code are deletable
        let d = PropDesc { value: Some(Value::Undefined), writable: Some(true), enumerable: Some(true), configurable: Some(frame.code.is_eval), get: None, set: None };
        self.define_own_property(&g, key, d)?;
        Ok(())
    }

    /// Would a `var name` in the running (sloppy eval) code conflict with a binding between its
    /// lexical environment and its variable environment (EvalDeclarationInstantiation)?
    /// Simple catch parameters don't conflict for eval-declared vars (Annex B.3.4).
    fn eval_var_conflict(&self, frame: &Frame, name: &JsStr, exempt_catch: bool) -> bool {
        let mut e = frame.env.clone();
        while let Some(env) = e {
            if env.0.with_obj.is_none() {
                if let Some(info) = &env.0.info {
                    if let Some(i) = info.find(name) {
                        let k = info.kinds[i];
                        let conflict = if info.is_function {
                            matches!(k, BindKind::Let | BindKind::Const | BindKind::Class)
                        } else {
                            match k {
                                BindKind::Internal | BindKind::FuncName => false,
                                BindKind::CatchParam => !exempt_catch,
                                _ => true,
                            }
                        };
                        if conflict {
                            return true;
                        }
                    }
                    if info.is_function {
                        return false;
                    }
                }
            }
            e = env.0.parent.clone();
        }
        // the global environment is the variable environment
        self.global_lex.contains_key(name)
    }

    fn can_declare_global_function(&self, key: &PropKey) -> bool {
        let b = self.global.borrow();
        match b.props.get(key) {
            None => b.extensible,
            Some(p) => p.configurable() || (matches!(p, Prop::Data { .. }) && p.writable() && p.enumerable()),
        }
    }

    /// Declaration instantiation checks of scripts (modes 0-2) and sloppy eval code (4-6).
    fn global_decl_check(&mut self, frame: &Frame, key: &PropKey, mode: u8) -> JsResult<()> {
        let name = match key.as_jsstr() {
            Some(n) => n.clone(),
            None => return Ok(()),
        };
        let fail_syntax = match mode {
            // script lexical: conflicts with an earlier lexical or a non-configurable global property
            0 => self.global_lex.contains_key(&name) || self.global.borrow().props.get(key).map_or(false, |p| !p.configurable()),
            1 => self.global_lex.contains_key(&name),
            4 => self.eval_var_conflict(frame, &name, true),
            _ => false,
        };
        if fail_syntax {
            return Err(self.make_error("SyntaxError", &format!("Identifier '{}' has already been declared", name)));
        }
        match mode {
            2 => {
                if !self.can_declare_global_function(key) {
                    return self.throw_type(format!("cannot declare global function '{}'", name));
                }
            }
            5 => {
                if self.eval_var_env(frame).is_none() {
                    let b = self.global.borrow();
                    let ok = b.props.contains(key) || b.extensible;
                    drop(b);
                    if !ok {
                        return self.throw_type(format!("cannot declare global binding '{}'", name));
                    }
                }
            }
            6 => {
                if self.eval_var_env(frame).is_none() && !self.can_declare_global_function(key) {
                    return self.throw_type(format!("cannot declare global binding '{}'", name));
                }
            }
            _ => {}
        }
        Ok(())
    }

    /// Bind a var-scoped name directly in the variable environment of a script or sloppy eval:
    /// function declaration instantiation (`init`) or the Annex B copy of a block function.
    fn set_var_binding(&mut self, frame: &Frame, key: &PropKey, v: Value, init: bool) -> JsResult<()> {
        let name = key.as_jsstr().unwrap().clone();
        if frame.code.is_eval {
            if !init && self.eval_var_conflict(frame, &name, false) {
                return Ok(());
            }
            if let Some(env) = self.eval_var_env(frame) {
                if let Some(info) = &env.0.info {
                    if let Some(i) = info.find(&name) {
                        env.0.vars.borrow_mut()[i] = v;
                        return Ok(());
                    }
                }
                let mut ex = env.0.extra.borrow_mut();
                match ex.iter_mut().find(|(n, _)| *n == name) {
                    Some(slot) => slot.1 = v,
                    None => ex.push((name, v)),
                }
                return Ok(());
            }
        }
        if !init {
            return self.set_global(key, v, false);
        }
        // CreateGlobalFunctionBinding
        let g = self.global.clone();
        let replace = g.borrow().props.get(key).map_or(true, |p| p.configurable());
        let d = if replace {
            PropDesc { value: Some(v.clone()), writable: Some(true), enumerable: Some(true), configurable: Some(frame.code.is_eval), get: None, set: None }
        } else {
            PropDesc { value: Some(v.clone()), writable: None, enumerable: None, configurable: None, get: None, set: None }
        };
        self.define_own_property(&g, key.clone(), d)?;
        self.set(&g, key.clone(), v, &Value::Obj(g.clone()))?;
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
                    // GetBindingValue checks the property again
                    if !self.has_property(o, key)? {
                        if frame.code.strict {
                            return self.throw_ref(format!("{} is not defined", key.to_display()));
                        }
                        return Ok(Some(Value::Undefined));
                    }
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
                    // GetBindingValue checks the property again
                    if !self.has_property(o, key)? {
                        if frame.code.strict {
                            return self.throw_ref(format!("{} is not defined", key.to_display()));
                        }
                        return Ok((Value::Obj(o.clone()), Value::Undefined));
                    }
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
                    // SetMutableBinding checks the property again
                    let still = self.has_property(o, key)?;
                    if !still && strict {
                        return self.throw_ref(format!("{} is not defined", key.to_display()));
                    }
                    let ok = self.set(o, key.clone(), v, &Value::Obj(o.clone()))?;
                    if !ok && strict {
                        return self.throw_type(format!("cannot assign to read-only property '{}'", key.to_display()));
                    }
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

// ---------------- realms ----------------

/// A realm that is not the current one.
pub struct RealmData {
    pub intr: crate::realm::Intrinsics,
    pub global: Obj,
    pub global_lex: FxHashMap<JsStr, GlobalLex>,
}

/// set once a second realm exists (enables realm switching on calls)
pub static MULTI_REALM: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

thread_local! {
    /// realm records by id (None: the current realm, whose record lives in the VM)
    static REALMS: RefCell<Vec<Option<RealmData>>> = const { RefCell::new(Vec::new()) };
}

/// The realm of a function object (u32::MAX for other objects).
#[inline]
fn fn_realm(o: &Obj) -> u32 {
    match &o.borrow().kind {
        ObjKind::Closure(c) => c.realm,
        ObjKind::Native(n) => n.realm,
        _ => u32::MAX,
    }
}

// ---------------- decorators ----------------

/// The class definition being decorated: its constructor, and the initializers added for
/// static elements and for the class itself.
struct DecState {
    f: Obj,
    statics: Vec<Value>,
    class_inits: Vec<Value>,
}

thread_local! {
    static DEC_STACK: RefCell<Vec<DecState>> = const { RefCell::new(Vec::new()) };
    /// decorator initializers for the next field definition
    static DEC_PENDING: RefCell<Option<Value>> = const { RefCell::new(None) };
}

/// The decorator initializers (array) set for the next field, as a list.
fn take_dec_pending() -> Vec<Value> {
    let v = DEC_PENDING.with(|p| p.borrow_mut().take());
    match v {
        Some(Value::Obj(a)) => {
            let b = a.borrow();
            match &b.kind {
                ObjKind::Array(arr) => arr.dense.iter().filter(|x| !x.is_empty()).cloned().collect(),
                _ => Vec::new(),
            }
        }
        _ => Vec::new(),
    }
}

/// context.addInitializer (slots: class constructor, 0 instance / 1 static / 2 class)
fn dec_add_initializer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.arg(0);
    if !f.is_callable() {
        return vm.throw_type("addInitializer expects a callable");
    }
    let class = match a.slot(0) {
        Value::Obj(o) => o,
        _ => return Ok(Value::Undefined),
    };
    let mode = match a.slot(1) {
        Value::Num(n) => n as u8,
        _ => 0,
    };
    if mode == 0 {
        if let (ObjKind::Closure(c), Value::Obj(fo)) = (&mut class.borrow_mut().kind, &f) {
            let fields = c.fields.get_or_insert_with(|| Rc::new(Vec::new()));
            Rc::make_mut(fields).push(ClassField { key: FieldKey::Initializer, init: Some(fo.clone()), is_accessor: false, extra_inits: Vec::new() });
        }
    } else {
        DEC_STACK.with(|s| {
            let mut s = s.borrow_mut();
            if let Some(st) = s.iter_mut().rev().find(|st| st.f.ptr_eq(&class)) {
                if mode == 1 {
                    st.statics.push(f.clone());
                } else {
                    st.class_inits.push(f.clone());
                }
            }
        });
    }
    Ok(Value::Undefined)
}

/// context.access.get (slots: key, private)
fn dec_access_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let key = a.slot(0);
    let o = a.arg(0);
    if let Value::Sym(s) = &key {
        if s.is_private() {
            let ob = match &o {
                Value::Obj(ob) => ob.clone(),
                _ => return Ok(Value::Undefined),
            };
            let p = ob.borrow().props.get(&PropKey::Sym(s.clone())).cloned();
            return match p {
                Some(Prop::Data { value, .. }) => Ok(value),
                Some(Prop::Accessor { get: Some(g), .. }) => vm.call_obj(&g, o.clone(), &[]),
                _ => Ok(Value::Undefined),
            };
        }
    }
    let k = vm.to_property_key(&key)?;
    vm.get_prop_of(&o, &k)
}

/// context.access.set (slots: key, private)
fn dec_access_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let key = a.slot(0);
    let o = a.arg(0);
    let v = a.arg(1);
    if let Value::Sym(s) = &key {
        if s.is_private() {
            if let Value::Obj(ob) = &o {
                let pk = PropKey::Sym(s.clone());
                let p = ob.borrow().props.get(&pk).cloned();
                match p {
                    Some(Prop::Data { flags, .. }) => {
                        ob.borrow_mut().props.insert(pk, Prop::Data { value: v, flags });
                    }
                    Some(Prop::Accessor { set: Some(st), .. }) => {
                        vm.call_obj(&st, o.clone(), &[v])?;
                    }
                    _ => {}
                }
            }
            return Ok(Value::Undefined);
        }
    }
    let k = vm.to_property_key(&key)?;
    if let Value::Obj(ob) = &o {
        vm.set(ob, k, v, &o)?;
    }
    Ok(Value::Undefined)
}

/// getter of an auto-accessor (slot: the private storage name)
fn auto_accessor_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let (Value::Sym(s), Value::Obj(o)) = (a.slot(0), &a.this) {
        if let Some(Prop::Data { value, .. }) = o.borrow().props.get(&PropKey::Sym(s)) {
            return Ok(value.clone());
        }
    }
    vm.throw_type("cannot read auto-accessor backing field from an unrelated object")
}

/// setter of an auto-accessor (slot: the private storage name)
fn auto_accessor_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let (Value::Sym(s), Value::Obj(o)) = (a.slot(0), &a.this) {
        let pk = PropKey::Sym(s);
        let has = matches!(o.borrow().props.get(&pk), Some(Prop::Data { .. }));
        if has {
            o.borrow_mut().props.insert(pk, Prop::Data { value: a.arg(0), flags: WRITABLE });
            return Ok(Value::Undefined);
        }
    }
    vm.throw_type("cannot write auto-accessor backing field on an unrelated object")
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
        anonymous_trace_name(code)
    } else {
        code.name.clone()
    }
}

/// Stack-trace name of a function: its current `name` property (like the reference engine),
/// "<anonymous>" when empty.
pub fn closure_trace_name(f: &Obj, code: &FunctionCode) -> JsStr {
    thread_local! {
        static KEY_NAME: PropKey = PropKey::from_str("name");
    }
    let n = KEY_NAME.with(|k| {
        let b = f.borrow();
        match b.props.get(k) {
            Some(Prop::Data { value: Value::Str(s), .. }) => Some(s.clone()),
            _ => None,
        }
    });
    match n {
        Some(s) if !s.is_empty() => s,
        _ => anonymous_trace_name(code),
    }
}

fn anonymous_trace_name(code: &FunctionCode) -> JsStr {
    // the CommonJS module wrapper reports as "anonymous"
    if code.src_start == 1 && code.source.starts_with("(function (exports, require, module, __filename, __dirname) {") {
        return JsStr::from_str("anonymous");
    }
    JsStr::from_str("<anonymous>")
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
    // fast path: small integers (same result as the floating-point remainder)
    if !x.is_sign_negative() && y > 0.0 && x <= 4294967295.0 && y <= 4294967295.0 {
        let (xi, yi) = (x as u32, y as u32);
        if xi as f64 == x && yi as f64 == y {
            return (xi % yi) as f64;
        }
    }
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
            yield_star: false,
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
        let fallback = match kind {
            ProtoKind::Object => self.intr.object_proto.clone(),
            ProtoKind::Generator => self.intr.generator_proto.clone(),
            ProtoKind::AsyncGenerator => self.intr.async_generator_proto.clone(),
        };
        if let Value::Obj(o) = nt {
            let p = self.get(o, &self.intr.key_prototype.clone(), nt)?;
            if let Value::Obj(po) = p {
                return Ok(po);
            }
            return self.realm_fallback(o, &fallback);
        }
        Ok(fallback)
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
            return self.realm_fallback(o, fallback);
        }
        Ok(fallback.clone())
    }

    // ---------------- realms ----------------

    /// The intrinsic corresponding to `fallback` in the realm of the constructor `f`
    /// (GetPrototypeFromConstructor uses the constructor's realm).
    pub fn realm_fallback(&mut self, f: &Obj, fallback: &Obj) -> JsResult<Obj> {
        if !MULTI_REALM.load(std::sync::atomic::Ordering::Relaxed) {
            return Ok(fallback.clone());
        }
        let r = self.function_realm(f)?;
        if r == self.intr.realm_id {
            return Ok(fallback.clone());
        }
        let idx = self.intr.objs().iter().position(|o| o.ptr_eq(fallback));
        let other = idx.and_then(|i| REALMS.with(|rs| rs.borrow().get(r as usize).and_then(|d| d.as_ref().map(|d| d.intr.objs()[i].clone()))));
        Ok(other.unwrap_or_else(|| fallback.clone()))
    }

    /// GetFunctionRealm
    pub fn function_realm(&mut self, f: &Obj) -> JsResult<u32> {
        enum R {
            Id(u32),
            Next(Obj),
            Revoked,
            Current,
        }
        let r = match &f.borrow().kind {
            ObjKind::Closure(c) => R::Id(c.realm),
            ObjKind::Native(n) => R::Id(n.realm),
            ObjKind::Bound(b) => R::Next(b.target.clone()),
            ObjKind::Proxy(p) => match &p.target {
                Some(t) => R::Next(t.clone()),
                None => R::Revoked,
            },
            _ => R::Current,
        };
        match r {
            R::Id(i) => Ok(i),
            R::Next(t) => self.function_realm(&t),
            R::Revoked => self.throw_type("proxy is revoked"),
            R::Current => Ok(self.intr.realm_id),
        }
    }

    /// The realm's intrinsics with the given id (cloned objects), for cross-realm checks.
    pub fn realm_array_ctor(&self, r: u32) -> Option<Obj> {
        if r == self.intr.realm_id {
            return Some(self.intr.array_ctor.clone());
        }
        REALMS.with(|rs| rs.borrow().get(r as usize).and_then(|d| d.as_ref().map(|d| d.intr.array_ctor.clone())))
    }

    /// Make realm `to` the current realm (swapping the realm records).
    pub fn switch_realm(&mut self, to: u32) {
        let from = self.intr.realm_id;
        if to == from {
            return;
        }
        let incoming = REALMS.with(|rs| rs.borrow_mut().get_mut(to as usize).and_then(|d| d.take()));
        let incoming = match incoming {
            Some(d) => d,
            None => return,
        };
        let out = RealmData {
            intr: std::mem::replace(&mut self.intr, incoming.intr),
            global: std::mem::replace(&mut self.global, incoming.global),
            global_lex: std::mem::replace(&mut self.global_lex, incoming.global_lex),
        };
        REALMS.with(|rs| {
            let mut rs = rs.borrow_mut();
            while rs.len() <= from as usize {
                rs.push(None);
            }
            rs[from as usize] = Some(out);
        });
    }

    /// Create a new realm with its own intrinsics and global object; returns its id.
    pub fn create_realm(&mut self) -> u32 {
        MULTI_REALM.store(true, std::sync::atomic::Ordering::Relaxed);
        let id = REALMS.with(|rs| {
            let mut rs = rs.borrow_mut();
            let n = rs.len().max(1) as u32;
            while rs.len() <= n as usize {
                rs.push(None);
            }
            n
        });
        let mut intr = crate::realm::Intrinsics::new();
        intr.share_from(&self.intr);
        intr.realm_id = id;
        let global = Obj::new(Some(intr.object_proto.clone()), ObjKind::Ordinary);
        let prev = self.intr.realm_id;
        let saved = RealmData {
            intr: std::mem::replace(&mut self.intr, intr),
            global: std::mem::replace(&mut self.global, global),
            global_lex: std::mem::take(&mut self.global_lex),
        };
        crate::builtins::setup(self);
        crate::builtins::order::apply_global_order(self);
        let new_data = RealmData {
            intr: std::mem::replace(&mut self.intr, saved.intr),
            global: std::mem::replace(&mut self.global, saved.global),
            global_lex: std::mem::replace(&mut self.global_lex, saved.global_lex),
        };
        let _ = prev;
        REALMS.with(|rs| rs.borrow_mut()[id as usize] = Some(new_data));
        id
    }

    /// The global object of a realm.
    pub fn realm_global(&self, r: u32) -> Option<Obj> {
        if r == self.intr.realm_id {
            return Some(self.global.clone());
        }
        REALMS.with(|rs| rs.borrow().get(r as usize).and_then(|d| d.as_ref().map(|d| d.global.clone())))
    }
}
