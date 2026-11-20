// Interactive REPL (line-buffered).

use crate::runtime;
use crate::value::*;
use crate::vm::Vm;
use std::io::BufRead;

fn is_incomplete(src: &str) -> bool {
    match crate::parser::parse_repl(src) {
        Ok(_) => false,
        Err(e) => {
            e.msg.contains("Eof") || e.msg.starts_with("unterminated template") || e.msg.starts_with("expected '}'") || e.msg.starts_with("expected ')'") || e.msg.starts_with("expected ']'")
        }
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
            if t == ".exit" {
                break;
            }
            if t == ".help" {
                runtime::write_stdout(vm, ".help   this text\n.exit   leave the repl\n_       the last result\nawait   allowed at the top level (expression form)\n");
                continue;
            }
            if t.is_empty() {
                continue;
            }
        }
        buffer.push_str(&line);
        buffer.push('\n');
        if is_incomplete(&buffer) {
            continue;
        }
        let src = std::mem::take(&mut buffer);
        let r = crate::loader::run_script(vm, &src, true);
        match r {
            Ok(v) => {
                runtime::run_event_loop(vm);
                // top-level await: v may be a promise from the REPL await wrapper
                let v = settle_if_await(vm, v, &src);
                print_result(vm, &v);
                vm.global.set_prop(PropKey::from_str("_"), v, crate::object::WC);
            }
            Err(Ok(se)) => {
                runtime::write_stdout(vm, &format!("Uncaught SyntaxError: {}\n", se.msg));
            }
            Err(Err(e)) => {
                runtime::run_event_loop(vm);
                let s = runtime::describe_thrown(vm, &e);
                runtime::write_stdout(vm, &format!("Uncaught {}\n", s));
            }
        }
    }
    0
}

fn settle_if_await(vm: &mut Vm, v: Value, src: &str) -> Value {
    if !src.contains("await") {
        return v;
    }
    if let Value::Obj(o) = &v {
        let st = match &o.borrow().kind {
            crate::object::ObjKind::Promise(p) => Some(p.state.clone()),
            _ => None,
        };
        if let Some(crate::object::PromiseState::Fulfilled(x)) = st {
            return x;
        }
    }
    v
}

fn print_result(vm: &mut Vm, v: &Value) {
    let s = match v {
        Value::Str(s) => format!("'{}'", s),
        other => runtime::display_value(vm, other),
    };
    runtime::write_stdout(vm, &format!("{}\n", s));
}
