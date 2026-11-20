// The process object.

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let p = vm.new_object();
    let fns: &[(&str, u32, NativeFn)] = &[
        ("cwd", 0, cwd),
        ("exit", 1, exit),
        ("nextTick", 1, next_tick),
    ];
    for (n, l, f) in fns {
        vm.def_method(&p, n, *l, *f);
    }
    // stdout / stderr
    let stdout = make_stream(vm, 1);
    p.set_prop(PropKey::from_str("stdout"), Value::Obj(stdout), WEC);
    let stderr = make_stream(vm, 2);
    p.set_prop(PropKey::from_str("stderr"), Value::Obj(stderr), WEC);
    let hr = vm.def_method(&p, "hrtime", 1, hrtime);
    vm.def_method(&hr, "bigint", 0, hrtime_bigint);
    vm.def_method(&p, "uptime", 0, uptime);
    p.set_prop(PropKey::from_str("version"), Value::str("v20.11.0"), WEC);
    let versions = vm.obj_from(vec![("node", Value::str("20.11.0")), ("lumen", Value::str("0.1.1")), ("v8", Value::str("0.0.0"))]);
    p.set_prop(PropKey::from_str("versions"), Value::Obj(versions), WEC);
    vm.def_method(&p, "chdir", 1, chdir);
    vm.def_method(&p, "abort", 0, abort);
    vm.def_method(&p, "umask", 0, |_vm, _a| Ok(Value::Num(18.0)));
    vm.def_method(&p, "getuid", 0, |_vm, _a| Ok(Value::Num(get_id("Uid") as f64)));
    vm.def_method(&p, "geteuid", 0, |_vm, _a| Ok(Value::Num(get_id("Uid") as f64)));
    vm.def_method(&p, "getgid", 0, |_vm, _a| Ok(Value::Num(get_id("Gid") as f64)));
    vm.def_method(&p, "getegid", 0, |_vm, _a| Ok(Value::Num(get_id("Gid") as f64)));
    vm.def_method(&p, "kill", 2, |_vm, _a| Ok(Value::Bool(true)));
    crate::runtime::events::install_methods(vm, &p);
    crate::runtime::events::init_emitter(vm, &p);
    p.set_prop(PropKey::from_str("execArgv"), Value::Obj(vm.new_array(Vec::new())), WEC);
    p.set_prop(PropKey::from_str("exitCode"), Value::Undefined, WEC);
    vm.def_method(&p, "emitWarning", 1, emit_warning);
    vm.def_method(&p, "memoryUsage", 0, memory_usage);
    vm.def_method(&p, "cpuUsage", 0, cpu_usage);
    vm.def_method(&p, "getBuiltinModule", 1, get_builtin_module);
    let argv: Vec<Value> = vm.host.argv.iter().map(|s| Value::str(s)).collect();
    let argv_arr = vm.new_array(argv);
    p.set_prop(PropKey::from_str("argv"), Value::Obj(argv_arr), WEC);
    p.set_prop(PropKey::from_str("argv0"), Value::str(vm.host.argv.first().map(|s| s.as_str()).unwrap_or("lumen")), WEC);
    let exe = std::env::current_exe().map(|p| p.to_string_lossy().to_string()).unwrap_or_default();
    p.set_prop(PropKey::from_str("execPath"), Value::str(&exe), WEC);
    p.set_prop(PropKey::from_str("title"), Value::str("lumen"), WEC);
    let env = vm.new_object();
    for (k, v) in std::env::vars_os() {
        env.set_prop(PropKey::from_str(&k.to_string_lossy()), Value::str(&v.to_string_lossy()), WEC);
    }
    p.set_prop(PropKey::from_str("env"), Value::Obj(env), WEC);
    p.set_prop(PropKey::from_str("platform"), Value::str(std::env::consts::OS), WEC);
    p.set_prop(PropKey::from_str("pid"), Value::Num(std::process::id() as f64), WEC);
    p.set_prop(PropKey::from_str("ppid"), Value::Num(parent_pid() as f64), WEC);
    let arch = match std::env::consts::ARCH {
        "aarch64" => "arm64",
        "x86_64" => "x64",
        "x86" => "ia32",
        other => other,
    };
    p.set_prop(PropKey::from_str("arch"), Value::str(arch), WEC);
    let release = vm.obj_from(vec![("name", Value::str("node"))]);
    p.set_prop(PropKey::from_str("release"), Value::Obj(release), WEC);
    let features = vm.new_object();
    p.set_prop(PropKey::from_str("features"), Value::Obj(features), WEC);
    let config = vm.obj_from(vec![("variables", Value::Obj(vm.new_object()))]);
    p.set_prop(PropKey::from_str("config"), Value::Obj(config), WEC);
    let stdin = crate::runtime::node::make_stdin(vm);
    p.set_prop(PropKey::from_str("stdin"), stdin, WEC);
    for (k, v) in [("debugPort", Value::Num(9229.0)), ("domain", Value::Null), ("sourceMapsEnabled", Value::Bool(false)), ("connected", Value::Bool(false)), ("_exiting", Value::Bool(false))] {
        p.set_prop(PropKey::from_str(k), v, WEC);
    }
    p.set_prop(PropKey::from_str("moduleLoadList"), Value::Obj(vm.new_array(Vec::new())), WEC);
    crate::runtime::reorder_enum(vm, &p, crate::runtime::PROCESS_KEYS);
    vm.set_tag(&p, "process");
    vm.host.process_obj = Some(p.clone());
    vm.def_global("process", Value::Obj(p));
}

fn get_id(which: &str) -> u32 {
    if let Ok(s) = std::fs::read_to_string("/proc/self/status") {
        for line in s.lines() {
            if let Some(rest) = line.strip_prefix(&format!("{}:", which)) {
                if let Some(first) = rest.split_whitespace().next() {
                    return first.parse().unwrap_or(0);
                }
            }
        }
    }
    0
}

fn parent_pid() -> u32 {
    if let Ok(s) = std::fs::read_to_string("/proc/self/stat") {
        let after = s.rsplit(')').next().unwrap_or("");
        let parts: Vec<&str> = after.split_whitespace().collect();
        if parts.len() > 1 {
            return parts[1].parse().unwrap_or(0);
        }
    }
    0
}

fn make_stream(vm: &mut Vm, fd: u32) -> Obj {
    let s = vm.new_object();
    let w = vm.native_closure("write", 1, stream_write, vec![Value::Num(fd as f64)]);
    s.set_prop(PropKey::from_str("write"), Value::Obj(w), WEC);
    s.set_prop(PropKey::from_str("fd"), Value::Num(fd as f64), WEC);
    s.set_prop(PropKey::from_str("isTTY"), Value::Bool(false), WEC);
    s.set_prop(PropKey::from_str("writable"), Value::Bool(true), WEC);
    s.set_prop(PropKey::from_str("columns"), Value::Num(80.0), WEC);
    s.set_prop(PropKey::from_str("rows"), Value::Num(24.0), WEC);
    crate::runtime::events::install_methods(vm, &s);
    crate::runtime::events::init_emitter(vm, &s);
    vm.def_method(&s, "end", 0, stream_end);
    vm.def_method(&s, "cork", 0, |_vm, _a| Ok(Value::Undefined));
    vm.def_method(&s, "uncork", 0, |_vm, _a| Ok(Value::Undefined));
    vm.def_method(&s, "getColorDepth", 0, |_vm, _a| Ok(Value::Num(1.0)));
    vm.def_method(&s, "hasColors", 0, |_vm, _a| Ok(Value::Bool(false)));
    vm.def_method(&s, "getWindowSize", 0, |vm, _a| Ok(Value::Obj(vm.new_array(vec![Value::Num(80.0), Value::Num(24.0)]))));
    s
}

fn stream_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let fd = a.slot(0).as_num().unwrap_or(1.0) as u32;
    let data = a.arg(0);
    let bytes = match &data {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_)) => crate::builtins::typedarray::ta_bytes(o),
        other => {
            let s = vm.to_string(other)?;
            crate::runtime::encoding::utf16_to_utf8(s.units())
        }
    };
    if fd == 2 {
        use std::io::Write;
        let _ = std::io::stderr().write_all(&bytes);
    } else {
        crate::runtime::write_stdout_bytes(&bytes);
    }
    // callback
    for i in 1..3 {
        let cb = a.arg(i);
        if cb.is_callable() {
            vm.host.callbacks.push_back((cb, Vec::new()));
            break;
        }
    }
    Ok(Value::Bool(true))
}

fn stream_end(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !a.arg(0).is_nullish() && !a.arg(0).is_callable() {
        let w = vm.get_prop_of(&a.this, &PropKey::from_str("write"))?;
        vm.call(&w, a.this.clone(), &[a.arg(0)])?;
    }
    Ok(Value::Undefined)
}

fn cwd(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::str(&std::env::current_dir().map(|p| p.to_string_lossy().to_string()).unwrap_or_default()))
}

fn chdir(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let d = vm.to_string(&a.arg(0))?.to_rust_string();
    if std::env::set_current_dir(&d).is_err() {
        let e = crate::runtime::fs::fs_error(vm, "ENOENT", "no such file or directory", "chdir", &d, None);
        return Err(e);
    }
    Ok(Value::Undefined)
}

pub fn do_exit(vm: &mut Vm, code: i32) -> ! {
    let _ = vm;
    use std::io::Write;
    let _ = std::io::stdout().flush();
    let _ = std::io::stderr().flush();
    std::process::exit(code)
}

fn exit(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let code = if a.arg(0).is_undefined() {
        match vm.host.process_obj.clone() {
            Some(p) => match p.get_own_str("exitCode") {
                Some(Value::Num(n)) => n as i32,
                _ => 0,
            },
            None => 0,
        }
    } else {
        vm.to_number(&a.arg(0))? as i32
    };
    // emit 'exit'
    if let Some(p) = vm.host.process_obj.clone() {
        let _ = crate::runtime::events::emit_event(vm, &Value::Obj(p), &Value::str("exit"), &[Value::Num(code as f64)]);
    }
    do_exit(vm, code)
}

fn abort(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    do_exit(vm, 134)
}

fn next_tick(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cb = a.arg(0);
    if !cb.is_callable() {
        return vm.throw_type("process.nextTick expects a function");
    }
    let args = if a.args.len() > 1 { a.args[1..].to_vec() } else { Vec::new() };
    vm.host.callbacks.push_back((cb, args));
    Ok(Value::Undefined)
}

fn hrtime(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let d = vm.host.start.elapsed();
    let mut secs = d.as_secs() as f64;
    let mut nanos = d.subsec_nanos() as f64;
    if let Value::Obj(prev) = a.arg(0) {
        let ps = vm.get(&prev, &PropKey::from_index(0), &a.arg(0))?;
        let pn = vm.get(&prev, &PropKey::from_index(1), &a.arg(0))?;
        let ps = vm.to_number(&ps)?;
        let pn = vm.to_number(&pn)?;
        secs -= ps;
        nanos -= pn;
        if nanos < 0.0 {
            secs -= 1.0;
            nanos += 1e9;
        }
    }
    Ok(Value::Obj(vm.new_array(vec![Value::Num(secs), Value::Num(nanos)])))
}

fn hrtime_bigint(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let d = vm.host.start.elapsed();
    let n = d.as_nanos() as i128;
    Ok(Value::BigInt(std::rc::Rc::new(crate::bigint::BigInt::from_i128(n))))
}

fn uptime(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Num(vm.host.start.elapsed().as_secs_f64()))
}

fn emit_warning(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let w = a.arg(0);
    let msg = match &w {
        Value::Obj(o) => {
            let n = vm.get_str(o, "name")?;
            let m = vm.get_str(o, "message")?;
            format!("{}: {}", crate::runtime::display_value(vm, &n), crate::runtime::display_value(vm, &m))
        }
        other => {
            let t = match a.arg(1) {
                Value::Str(s) => s.to_rust_string(),
                Value::Obj(o) => match vm.get_str(&o, "type")? {
                    Value::Str(s) => s.to_rust_string(),
                    _ => "Warning".to_string(),
                },
                _ => "Warning".to_string(),
            };
            format!("{}: {}", t, crate::runtime::display_value(vm, other))
        }
    };
    crate::runtime::write_stderr(&format!("(node:{}) {}\n", std::process::id(), msg));
    Ok(Value::Undefined)
}

fn memory_usage(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let rss = std::fs::read_to_string("/proc/self/statm")
        .ok()
        .and_then(|s| s.split_whitespace().nth(1).and_then(|x| x.parse::<f64>().ok()))
        .map(|p| p * 4096.0)
        .unwrap_or(0.0);
    let o = vm.obj_from(vec![
        ("rss", Value::Num(rss)),
        ("heapTotal", Value::Num(rss)),
        ("heapUsed", Value::Num(rss / 2.0)),
        ("external", Value::Num(0.0)),
        ("arrayBuffers", Value::Num(0.0)),
    ]);
    Ok(Value::Obj(o))
}

fn cpu_usage(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let us = vm.host.start.elapsed().as_micros() as f64;
    Ok(Value::Obj(vm.obj_from(vec![("user", Value::Num(us)), ("system", Value::Num(0.0))])))
}

fn get_builtin_module(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let n = vm.to_string(&a.arg(0))?.to_rust_string();
    let name = n.strip_prefix("node:").unwrap_or(&n).to_string();
    match crate::runtime::node::builtin_module(vm, &name)? {
        Some(v) => Ok(v),
        None => Ok(Value::Undefined),
    }
}
