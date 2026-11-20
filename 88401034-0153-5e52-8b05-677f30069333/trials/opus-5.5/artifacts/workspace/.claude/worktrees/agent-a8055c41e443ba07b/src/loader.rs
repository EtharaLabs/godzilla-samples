// Compiling and running source code: scripts, eval code, dynamic functions.

use crate::bytecode::FunctionCode;
use crate::compiler::Compiler;
use crate::object::*;
use crate::parser;
use crate::resolver::{Resolver, ScopeKind};
use crate::value::*;
use crate::vm::{Completion, Env, Frame, JsResult, Vm};
use std::rc::Rc;

pub struct SyntaxErr {
    pub msg: String,
    pub line: u32,
}

pub fn compile_program(src: &str, kind: ScopeKind, opts: Option<&parser::ParseOptions>, repl: bool) -> Result<Rc<FunctionCode>, SyntaxErr> {
    let prog = match opts {
        Some(o) => parser::parse_with(src, o),
        None => {
            if repl {
                parser::parse_repl(src)
            } else {
                parser::parse(src, kind == ScopeKind::Module)
            }
        }
    }
    .map_err(|e| SyntaxErr { msg: e.msg, line: e.line })?;
    let mut res = Resolver::new();
    res.resolve_program(&prog, kind).map_err(|e| SyntaxErr { msg: e.msg, line: e.line })?;
    let comp = Compiler::new(&res, prog.source.clone(), false);
    let code = comp
        .compile_script(&prog, kind == ScopeKind::Eval, repl, false)
        .map_err(|e| SyntaxErr { msg: e.msg, line: e.line })?;
    Ok(code)
}

/// Run a global script. Syntax errors are returned as Err(Ok(SyntaxErr)), runtime errors as Err(Err(value)).
pub fn run_script(vm: &mut Vm, src: &str, repl: bool) -> Result<Value, Result<SyntaxErr, Value>> {
    let code = compile_program(src, ScopeKind::Script, None, repl).map_err(Ok)?;
    let this = Value::Obj(vm.global.clone());
    let mut frame = Frame::new(code, None, this, None, Value::Undefined, Vec::new(), None);
    let r = vm.run_frame(&mut frame);
    match r {
        Ok(Completion::Return(v)) => Ok(v),
        Ok(Completion::Await(v)) => {
            // top-level await in REPL: run as async
            Ok(run_repl_await(vm, frame, v))
        }
        Ok(_) => Ok(Value::Undefined),
        Err(e) => Err(Err(e)),
    }
}

fn run_repl_await(vm: &mut Vm, frame: Frame, v: Value) -> Value {
    let cap = vm.new_promise_capability_intrinsic();
    let co = Obj::new(None, ObjKind::AsyncFn(Box::new(AsyncFnData { frame: Some(Box::new(frame)), capability: cap.clone() })));
    vm.await_value(v, co);
    cap.promise
}

pub fn syntax_error_value(vm: &mut Vm, e: &SyntaxErr) -> Value {
    vm.make_error("SyntaxError", &e.msg)
}

/// Compile `function anonymous(...) {...}` source (Function constructor) into a closure in the global scope.
pub fn compile_function_source(vm: &mut Vm, src: &str) -> JsResult<Obj> {
    let wrapped = format!("({})", src);
    let opts = parser::ParseOptions {
        is_module: false,
        strict: false,
        in_function: false,
        allow_super_prop: false,
        allow_super_call: false,
        allow_new_target: false,
        in_field_init: false,
        allow_return: false,
        in_async: false,
        in_generator: false,
        repl: false,
    };
    let code = match compile_program(&wrapped, ScopeKind::Eval, Some(&opts), false) {
        Ok(c) => c,
        Err(e) => return Err(syntax_error_value(vm, &e)),
    };
    // the source text of the function excludes the wrapping parens: adjust offsets
    let this = Value::Obj(vm.global.clone());
    let mut frame = Frame::new(code, None, this, None, Value::Undefined, Vec::new(), None);
    let r = vm.run_frame(&mut frame)?;
    match r {
        Completion::Return(Value::Obj(f)) => Ok(f),
        _ => vm.throw_syntax("invalid function source"),
    }
}

/// Indirect eval: global scope.
pub fn indirect_eval(vm: &mut Vm, src: &JsStr) -> JsResult<Value> {
    let s = src.to_rust_string();
    let opts = parser::ParseOptions {
        is_module: false,
        strict: false,
        in_function: false,
        allow_super_prop: false,
        allow_super_call: false,
        allow_new_target: false,
        in_field_init: false,
        allow_return: false,
        in_async: false,
        in_generator: false,
        repl: false,
    };
    let code = match compile_program(&s, ScopeKind::Eval, Some(&opts), false) {
        Ok(c) => c,
        Err(e) => return Err(syntax_error_value(vm, &e)),
    };
    let this = Value::Obj(vm.global.clone());
    let mut frame = Frame::new(code, None, this, None, Value::Undefined, Vec::new(), None);
    match vm.run_frame(&mut frame)? {
        Completion::Return(v) => Ok(v),
        _ => Ok(Value::Undefined),
    }
}

/// Direct eval within a calling frame.
pub fn direct_eval(vm: &mut Vm, caller: &Frame, src: &JsStr) -> JsResult<Value> {
    let s = src.to_rust_string();
    let in_func = caller.func.is_some();
    let kind = caller.code.kind;
    let method_like = matches!(
        kind,
        crate::ast::FuncKind::Method
            | crate::ast::FuncKind::Getter
            | crate::ast::FuncKind::Setter
            | crate::ast::FuncKind::ClassConstructor
            | crate::ast::FuncKind::DerivedConstructor
            | crate::ast::FuncKind::ClassFieldInit
            | crate::ast::FuncKind::StaticBlock
    ) || caller.home.is_some();
    let opts = parser::ParseOptions {
        is_module: false,
        strict: caller.code.strict,
        in_function: in_func,
        allow_super_prop: method_like,
        allow_super_call: kind == crate::ast::FuncKind::DerivedConstructor,
        allow_new_target: in_func,
        in_field_init: kind == crate::ast::FuncKind::ClassFieldInit,
        allow_return: false,
        in_async: false,
        in_generator: false,
        repl: false,
    };
    let code = match compile_program(&s, ScopeKind::Eval, Some(&opts), false) {
        Ok(c) => c,
        Err(e) => return Err(syntax_error_value(vm, &e)),
    };
    let mut frame = Frame::new(
        code,
        caller.env.clone(),
        caller.this.clone(),
        caller.func.clone(),
        caller.new_target.clone(),
        Vec::new(),
        caller.home.clone(),
    );
    frame.module = caller.module.clone();
    match vm.run_frame(&mut frame)? {
        Completion::Return(v) => Ok(v),
        _ => Ok(Value::Undefined),
    }
}

/// Create a closure for a compiled function body in the given environment (used by module wrappers)
pub fn closure_in(vm: &mut Vm, code: Rc<FunctionCode>, env: Option<Env>) -> Obj {
    vm.make_closure(code, env, None)
}
