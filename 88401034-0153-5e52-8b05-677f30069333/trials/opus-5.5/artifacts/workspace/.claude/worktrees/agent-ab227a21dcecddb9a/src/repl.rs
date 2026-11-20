// Interactive REPL (line-buffered).
//
// Each input is parsed as a plain script first. A parse error raised at the very end of the
// buffered input means the input is incomplete (".. " continuation prompt). Any other parse
// error gives top-level `await` a chance: the input is retried as the body of an async arrow,
// first in expression form `(async () => (INPUT))()` and then in statement form
// `(async () => { INPUT })()`; if neither parses, the original syntax error is reported.
// After every evaluation the event loop runs to quiescence before the result is printed.

use crate::object::*;
use crate::parser::ParseOptions;
use crate::resolver::ScopeKind;
use crate::runtime;
use crate::value::*;
use crate::vm::{Completion, Frame, Vm};
use std::io::BufRead;

const HELP: &str = ".help   this text\n.exit   leave the repl\n_       the last result\nawait   allowed at the top level (expression form)\n";

enum Outcome {
    Value(Value),
    Thrown(Value),
    Syntax(String),
    NeverSettled,
}

fn script_opts() -> ParseOptions {
    ParseOptions {
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
    }
}

pub fn run_repl(vm: &mut Vm) -> i32 {
    vm.host.repl = true;
    runtime::write_stdout(vm, &format!("lumen {} (.help for help, .exit or Ctrl-D to quit)\n", crate::VERSION));
    let stdin = std::io::stdin();
    let mut lines = stdin.lock().lines();
    let mut buffer = String::new();
    loop {
        runtime::write_stdout(vm, if buffer.is_empty() { "> " } else { ".. " });
        let line = match lines.next() {
            Some(Ok(l)) => l,
            _ => {
                runtime::write_stdout(vm, "\n");
                break;
            }
        };
        if buffer.is_empty() {
            let t = line.trim();
            if t.is_empty() {
                continue;
            }
            if t.starts_with('.') && !t.starts_with("..") {
                match t {
                    ".exit" => break,
                    ".help" => runtime::write_stdout(vm, HELP),
                    _ => runtime::write_stdout(vm, &format!("unknown command {} (try .help)\n", t)),
                }
                continue;
            }
        }
        // every line keeps its own newline and gets one more appended (so a template literal
        // spanning lines contains blank lines between them)
        buffer.push_str(&line);
        buffer.push('\n');
        // incomplete input: the parse error is raised at the end of the input (checked without
        // the extra newline, so an error on the final line terminator also counts)
        if incomplete(&buffer) {
            buffer.push('\n');
            continue;
        }
        buffer.push('\n');
        let outcome = match crate::parser::parse_with(&buffer, &script_opts()) {
            Err(e) => match if buffer.contains("await") { run_await_forms(vm, &buffer) } else { None } {
                Some(o) => o,
                None => Outcome::Syntax(e.msg),
            },
            Ok(_) => run_plain(vm, &buffer),
        };
        buffer.clear();
        match outcome {
            Outcome::Value(v) => {
                print_result(vm, &v);
                vm.global.set_prop(PropKey::from_str("_"), v, WEC);
            }
            Outcome::Thrown(e) => {
                let s = runtime::format_thrown(vm, &e);
                runtime::write_stdout(vm, &format!("Uncaught {}\n", s));
            }
            Outcome::Syntax(msg) => {
                runtime::write_stdout(vm, &format!("SyntaxError: {}\n", msg));
            }
            Outcome::NeverSettled => {
                runtime::write_stdout(vm, "[promise never settled]\n");
            }
        }
    }
    0
}

/// The input fails to parse only because it ends too early.
fn incomplete(src: &str) -> bool {
    crate::parser::ERR_AT_EOF.with(|c| c.set(false));
    crate::parser::parse_with(src, &script_opts()).is_err() && crate::parser::ERR_AT_EOF.with(|c| c.get())
}

/// Compile `src` as a global script (completion value kept) and run it.
fn eval_script(vm: &mut Vm, src: &str) -> Result<Value, Result<String, Value>> {
    let code = crate::loader::compile_program(src, ScopeKind::Script, Some(&script_opts()), true).map_err(|e| Ok(e.msg))?;
    let this = Value::Obj(vm.global.clone());
    let mut frame = Frame::new(code, None, this, None, Value::Undefined, Vec::new(), None);
    match vm.run_frame(&mut frame) {
        Ok(Completion::Return(v)) => Ok(v),
        Ok(_) => Ok(Value::Undefined),
        Err(e) => Err(Err(e)),
    }
}

fn run_plain(vm: &mut Vm, src: &str) -> Outcome {
    let r = eval_script(vm, src);
    if let Err(Ok(msg)) = r {
        return Outcome::Syntax(msg);
    }
    runtime::run_event_loop(vm);
    match r {
        Ok(v) => Outcome::Value(v),
        Err(Err(e)) => Outcome::Thrown(e),
        Err(Ok(msg)) => Outcome::Syntax(msg),
    }
}

/// Top-level await: retry the input inside an async arrow (expression form, then statement form).
fn run_await_forms(vm: &mut Vm, src: &str) -> Option<Outcome> {
    let opts = script_opts();
    let expr = format!("(async () => ({}))()", src);
    let wrapped = if crate::parser::parse_with(&expr, &opts).is_ok() {
        expr
    } else {
        let body = format!("(async () => {{{}}})()", src);
        if crate::parser::parse_with(&body, &opts).is_err() {
            return None;
        }
        body
    };
    let p = match eval_script(vm, &wrapped) {
        Ok(v) => v,
        Err(Ok(msg)) => return Some(Outcome::Syntax(msg)),
        Err(Err(e)) => {
            runtime::run_event_loop(vm);
            return Some(Outcome::Thrown(e));
        }
    };
    // the REPL itself observes the wrapper promise: its rejection is not an unhandled one
    if let Value::Obj(o) = &p {
        if let ObjKind::Promise(pd) = &mut o.borrow_mut().kind {
            pd.is_handled = true;
        }
    }
    runtime::run_event_loop(vm);
    let state = match &p {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Promise(pd) => Some(pd.state.clone()),
            _ => None,
        },
        _ => None,
    };
    Some(match state {
        Some(PromiseState::Fulfilled(v)) => Outcome::Value(v),
        Some(PromiseState::Rejected(e)) => Outcome::Thrown(e),
        Some(_) => Outcome::NeverSettled,
        None => Outcome::Value(p),
    })
}

fn print_result(vm: &mut Vm, v: &Value) {
    let s = match v {
        Value::Str(s) => format!("'{}'", s),
        other => runtime::display_value(vm, other),
    };
    if !s.is_empty() {
        runtime::write_stdout(vm, &format!("{}\n", s));
    }
}
