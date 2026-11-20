// lumen-cli entry point.

mod ast;
mod bigint;
mod builtins;
mod bytecode;
mod compiler;
mod compress;
mod crypto;
mod datetime;
mod lexer;
mod loader;
mod modules;
mod numconv;
mod object;
mod ops;
mod parser;
mod props;
mod realm;
mod regexp;
mod repl;
mod resolver;
mod runtime;
mod unicode;
mod value;
mod vm;

use std::path::Path;
use value::*;

pub const VERSION: &str = "0.1.3";
const USAGE: &str = "usage: lumen-cli [repl | file.js [args...] | -e code] [--tier=interp|bytecode]";

pub fn new_vm() -> vm::Vm {
    let intr = realm::Intrinsics::new();
    let global = object::Obj::new(Some(intr.object_proto.clone()), object::ObjKind::Ordinary);
    let mut vm = vm::Vm {
        intr,
        global,
        global_lex: new_fx_map(),
        jobs: std::collections::VecDeque::new(),
        depth: 0,
        trace: Vec::new(),
        symbol_registry: new_fx_map(),
        template_cache: new_fx_map(),
        promise_counter: 0,
        unhandled: Vec::new(),
        host: runtime::Host::new(),
        exit_code: 0,
        depth_offset: 0,
        strict_stack: Vec::new(),
    };
    builtins::setup(&mut vm);
    vm
}

enum Mode {
    Eval(String),
    File(String),
    Repl,
    Stdin,
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let child = std::thread::Builder::new().stack_size(1 << 30).spawn(move || real_main(args)).expect("thread");
    let code = child.join().unwrap_or(70);
    std::process::exit(code);
}

fn real_main(args: Vec<String>) -> i32 {
    let mut mode: Option<Mode> = None;
    let mut eval_code: Option<String> = None;
    let mut repl = false;
    let mut i = 1;
    while i < args.len() {
        let a = &args[i];
        if let Some(t) = a.strip_prefix("--tier=") {
            if t != "interp" && t != "bytecode" {
                eprintln!("unknown tier '{}' (interp|bytecode)", t);
                return 2;
            }
            i += 1;
            continue;
        }
        match a.as_str() {
            "-e" | "--eval" => {
                if i + 1 >= args.len() {
                    eprintln!("-e expects code");
                    return 2;
                }
                eval_code = Some(args[i + 1].clone());
                i += 2;
                continue;
            }
            "-h" | "--help" => {
                println!("{}", USAGE);
                return 0;
            }
            "-v" | "--version" => {
                println!("lumen {}", VERSION);
                return 0;
            }
            "repl" => {
                repl = true;
                i += 1;
                continue;
            }
            _ => {
                if eval_code.is_some() || repl {
                    i += 1;
                    continue;
                }
                mode = Some(Mode::File(a.clone()));
                break;
            }
        }
    }
    let mode = if let Some(c) = eval_code {
        Mode::Eval(c)
    } else if let Some(m) = mode {
        m
    } else if repl {
        Mode::Repl
    } else if is_tty_stdin() {
        Mode::Repl
    } else {
        Mode::Stdin
    };
    if let Mode::File(f) = &mode {
        if !Path::new(f).is_file() {
            eprintln!("cannot read {}: not a file", f);
            return 2;
        }
    }
    let mut vm = new_vm();
    runtime::setup_runtime(&mut vm, args.clone());
    match mode {
        Mode::Repl => repl::run_repl(&mut vm),
        Mode::Eval(code) => run_script_mode(&mut vm, &code),
        Mode::Stdin => {
            use std::io::Read;
            let mut s = String::new();
            let _ = std::io::stdin().read_to_string(&mut s);
            run_script_mode(&mut vm, &s)
        }
        Mode::File(f) => run_file(&mut vm, &f),
    }
}

fn is_tty_stdin() -> bool {
    // isatty(0) without libc: check /proc/self/fd/0 target
    match std::fs::read_link("/proc/self/fd/0") {
        Ok(p) => {
            let s = p.to_string_lossy();
            s.starts_with("/dev/pts") || s.starts_with("/dev/tty")
        }
        Err(_) => false,
    }
}

fn run_script_mode(vm: &mut vm::Vm, code: &str) -> i32 {
    let r = loader::run_script(vm, code, false);
    match r {
        Ok(_) => {
            runtime::run_event_loop(vm);
            0
        }
        Err(Ok(se)) => {
            runtime::write_stderr(&format!("SyntaxError: {} (line {})\n", se.msg, se.line));
            1
        }
        Err(Err(e)) => {
            runtime::run_event_loop(vm);
            runtime::report_uncaught_script(vm, &e);
            1
        }
    }
}

fn run_file(vm: &mut vm::Vm, f: &str) -> i32 {
    let p = Path::new(f);
    let abs = std::fs::canonicalize(p).unwrap_or_else(|_| p.to_path_buf());
    let ext = abs.extension().map(|e| e.to_string_lossy().to_string()).unwrap_or_default();
    let src = match std::fs::read(&abs) {
        Ok(b) => String::from_utf8_lossy(&b).to_string(),
        Err(_) => {
            eprintln!("cannot read {}: not a file", f);
            return 2;
        }
    };
    let is_esm = ext == "mjs" || ext == "jsx" || (ext == "js" && modules::package_type_module(&abs));
    if ext == "json" {
        if let Err(e) = builtins::json::json_parse(vm, &JsStr::from_str(&src)) {
            runtime::run_event_loop(vm);
            runtime::report_uncaught(vm, &e);
            return 1;
        }
        runtime::run_event_loop(vm);
        return 0;
    }
    if is_esm {
        vm.host.main_esm_path = abs.to_string_lossy().to_string();
        let src2 = if ext == "jsx" { runtime::jsx_transform(&src) } else { src };
        let r = modules::run_module_file(vm, &abs, Some(&src2));
        match r {
            Ok((_m, p)) => {
                runtime::run_event_loop(vm);
                if let Value::Obj(po) = &p {
                    let st = match &po.borrow().kind {
                        object::ObjKind::Promise(pd) => pd.state.clone(),
                        _ => object::PromiseState::Pending,
                    };
                    if let object::PromiseState::Rejected(e) = st {
                        runtime::report_uncaught(vm, &e);
                        return 1;
                    }
                }
                0
            }
            Err(e) => {
                runtime::run_event_loop(vm);
                runtime::report_uncaught(vm, &e);
                1
            }
        }
    } else {
        let src2 = if ext == "ts" || ext == "mts" || ext == "cts" { runtime::strip_types(&src) } else { src };
        let r = runtime::node::run_cjs_main(vm, &abs, &src2);
        runtime::run_event_loop(vm);
        match r {
            Ok(()) => 0,
            Err(e) => {
                runtime::report_uncaught(vm, &e);
                1
            }
        }
    }
}
