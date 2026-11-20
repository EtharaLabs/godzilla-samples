// node: builtin module registry and the CommonJS loader.

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, TraceEntry, Vm};
use std::path::{Path, PathBuf};

pub const BUILTIN_NAMES: &[&str] = &[
    "buffer", "path", "os", "fs", "module", "events", "util", "sys", "console", "timers", "timers/promises", "crypto",
    "querystring", "url", "net", "assert", "assert/strict", "string_decoder", "tty", "async_hooks", "zlib", "stream",
    "stream/web", "stream/promises", "stream/consumers", "http", "https", "http2", "perf_hooks", "fs/promises",
    "path/posix", "path/win32", "child_process", "dns", "dns/promises", "v8", "inspector", "inspector/promises",
    "worker_threads", "readline", "readline/promises", "test", "tls", "process", "diagnostics_channel", "domain",
    "trace_events", "vm", "repl", "cluster", "dgram", "wasi",
];

pub fn setup_globals(vm: &mut Vm) {
    let g = vm.global.clone();
    g.set_prop(PropKey::from_str("global"), Value::Obj(g.clone()), WC);
    let cwd = std::env::current_dir().map(|p| p.to_string_lossy().to_string()).unwrap_or_default();
    let r = make_require(vm, &cwd, None);
    vm.def_global("require", Value::Obj(r));
    let names: Vec<Value> = BUILTIN_NAMES.iter().map(|s| Value::str(s)).collect();
    let _ = names;
}

/// process.stdin: a node:stream Readable fed from fd 0 once resumed (see nodestream).
pub fn make_stdin(vm: &mut Vm) -> Value {
    crate::runtime::nodestream::make_stdin(vm)
}

/// Get (creating if necessary) a builtin module's exports.
pub fn builtin_module(vm: &mut Vm, name: &str) -> JsResult<Option<Value>> {
    let name = if name == "sys" { "util" } else { name };
    if let Some(v) = vm.host.builtin_cache.get(name) {
        return Ok(Some(v.clone()));
    }
    let v = match name {
        "path" | "path/posix" => crate::runtime::path::create_module(vm),
        "path/win32" => crate::runtime::path::create_module(vm),
        "fs" => crate::runtime::fs::create_module(vm),
        "fs/promises" => {
            let fs = builtin_module(vm, "fs")?.unwrap();
            vm.get_prop_of(&fs, &PropKey::from_str("promises"))?
        }
        "events" => crate::runtime::events::create_module(vm),
        "util" => crate::runtime::util::create_module(vm),
        "buffer" => crate::runtime::buffer::create_module(vm),
        "zlib" => crate::runtime::zlib::create_module(vm),
        "crypto" => crate::runtime::cryptomod::create_module(vm),
        "os" => create_os(vm),
        "process" => Value::Obj(vm.host.process_obj.clone().unwrap()),
        "console" => vm.global.get_own_str("console").unwrap_or(Value::Undefined),
        "timers" => create_timers(vm),
        "timers/promises" => crate::runtime::web::create_timers_promises(vm),
        "url" => crate::runtime::web::create_url_module(vm),
        "string_decoder" => crate::runtime::buffer::create_string_decoder_module(vm),
        "querystring" => crate::runtime::web::create_querystring_module(vm),
        "assert" | "assert/strict" => crate::runtime::util::create_assert_module(vm),
        "module" => create_module_module(vm),
        "perf_hooks" => {
            let o = vm.new_object();
            let p = vm.global.get_own_str("performance").unwrap_or(Value::Undefined);
            o.set_str("performance", p, WEC);
            Value::Obj(o)
        }
        "async_hooks" => crate::runtime::util::create_async_hooks_module(vm),
        "worker_threads" => {
            let o = vm.new_object();
            o.set_str("isMainThread", Value::Bool(true), WEC);
            o.set_str("parentPort", Value::Null, WEC);
            o.set_str("workerData", Value::Null, WEC);
            o.set_str("threadId", Value::Num(0.0), WEC);
            Value::Obj(o)
        }
        "stream" | "stream/promises" | "stream/consumers" | "stream/web" => crate::runtime::nodestream::create_module(vm, name),
        "child_process" => crate::runtime::child_process::create_module(vm, name),
        "readline" | "readline/promises" => crate::runtime::readline::create_module(vm, name),
        "http" | "https" | "http2" => crate::runtime::http::create_module(vm, name),
        "net" | "tls" | "dgram" | "dns" | "dns/promises" => crate::runtime::net::create_module(vm, name),
        "vm" | "v8" => crate::runtime::vmmod::create_module(vm, name),
        "tty" => {
            let o = vm.new_object();
            vm.def_method(&o, "isatty", 1, |_vm, _a| Ok(Value::Bool(false)));
            Value::Obj(o)
        }
        _ => {
            if BUILTIN_NAMES.contains(&name) {
                Value::Obj(vm.new_object())
            } else {
                return Ok(None);
            }
        }
    };
    vm.host.builtin_cache.insert(name.to_string(), v.clone());
    Ok(Some(v))
}

fn create_timers(vm: &mut Vm) -> Value {
    let o = vm.new_object();
    for n in ["setTimeout", "setInterval", "clearTimeout", "clearInterval", "setImmediate", "queueMicrotask"] {
        if let Some(v) = vm.global.get_own_str(n) {
            o.set_str(n, v, WEC);
        }
    }
    vm.def_method(&o, "clearImmediate", 1, |_vm, _a| Ok(Value::Undefined));
    Value::Obj(o)
}

fn create_module_module(vm: &mut Vm) -> Value {
    let o = vm.new_object();
    vm.def_method(&o, "createRequire", 1, create_require);
    let names: Vec<Value> = BUILTIN_NAMES.iter().map(|s| Value::str(s)).collect();
    let arr = vm.new_array(names);
    o.set_str("builtinModules", Value::Obj(arr), WEC);
    vm.def_method(&o, "isBuiltin", 1, |vm, a| {
        let s = vm.to_string(&a.arg(0))?.to_rust_string();
        let n = s.strip_prefix("node:").unwrap_or(&s);
        Ok(Value::Bool(BUILTIN_NAMES.contains(&n)))
    });
    Value::Obj(o)
}

fn create_require(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut p = vm.to_string(&a.arg(0))?.to_rust_string();
    if let Some(rest) = p.strip_prefix("file://") {
        p = rest.to_string();
    }
    let dir = Path::new(&p).parent().map(|d| d.to_string_lossy().to_string()).unwrap_or_else(|| ".".into());
    Ok(Value::Obj(make_require(vm, &dir, None)))
}

fn create_os(vm: &mut Vm) -> Value {
    let o = vm.new_object();
    o.set_str("EOL", Value::str("\n"), WEC);
    let fns: &[(&str, NativeFn)] = &[
        ("platform", |_vm, _a| Ok(Value::str(std::env::consts::OS))),
        ("type", |_vm, _a| Ok(Value::str("Linux"))),
        ("arch", |_vm, _a| {
            Ok(Value::str(match std::env::consts::ARCH {
                "aarch64" => "arm64",
                "x86_64" => "x64",
                o => o,
            }))
        }),
        ("homedir", |_vm, _a| Ok(Value::str(&std::env::var("HOME").unwrap_or_else(|_| "/".into())))),
        ("tmpdir", |_vm, _a| Ok(Value::str(&std::env::var("TMPDIR").unwrap_or_else(|_| "/tmp".into())))),
        ("hostname", |_vm, _a| Ok(Value::str(std::fs::read_to_string("/etc/hostname").unwrap_or_else(|_| "localhost".into()).trim()))),
        ("release", |_vm, _a| Ok(Value::str(std::fs::read_to_string("/proc/sys/kernel/osrelease").unwrap_or_default().trim()))),
        ("uptime", |_vm, _a| {
            let u = std::fs::read_to_string("/proc/uptime").ok().and_then(|s| s.split_whitespace().next().and_then(|x| x.parse::<f64>().ok())).unwrap_or(0.0);
            Ok(Value::Num(u.floor()))
        }),
        ("totalmem", |_vm, _a| Ok(Value::Num(meminfo("MemTotal")))),
        ("freemem", |_vm, _a| Ok(Value::Num(meminfo("MemAvailable")))),
        ("endianness", |_vm, _a| Ok(Value::str("LE"))),
        ("availableParallelism", |_vm, _a| Ok(Value::Num(std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1) as f64))),
        ("loadavg", |vm, _a| {
            let s = std::fs::read_to_string("/proc/loadavg").unwrap_or_default();
            let v: Vec<Value> = s.split_whitespace().take(3).map(|x| Value::Num(x.parse().unwrap_or(0.0))).collect();
            Ok(Value::Obj(vm.new_array(v)))
        }),
        ("cpus", |vm, _a| {
            let n = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1);
            let mut v = Vec::new();
            for _ in 0..n {
                let times = vm.obj_from(vec![("user", Value::Num(0.0)), ("nice", Value::Num(0.0)), ("sys", Value::Num(0.0)), ("idle", Value::Num(0.0)), ("irq", Value::Num(0.0))]);
                let c = vm.obj_from(vec![("model", Value::str("cpu")), ("speed", Value::Num(0.0)), ("times", Value::Obj(times))]);
                v.push(Value::Obj(c));
            }
            Ok(Value::Obj(vm.new_array(v)))
        }),
        ("networkInterfaces", |vm, _a| Ok(Value::Obj(vm.new_object()))),
        ("userInfo", |vm, _a| {
            let user = std::env::var("USER").unwrap_or_else(|_| "user".into());
            let home = std::env::var("HOME").unwrap_or_else(|_| "/".into());
            Ok(Value::Obj(vm.obj_from(vec![
                ("uid", Value::Num(0.0)),
                ("gid", Value::Num(0.0)),
                ("username", Value::str(&user)),
                ("homedir", Value::str(&home)),
                ("shell", Value::str(&std::env::var("SHELL").unwrap_or_default())),
            ])))
        }),
        ("version", |_vm, _a| Ok(Value::str(std::fs::read_to_string("/proc/sys/kernel/version").unwrap_or_default().trim()))),
        ("machine", |_vm, _a| Ok(Value::str(std::env::consts::ARCH))),
    ];
    for (n, f) in fns {
        vm.def_method(&o, n, 0, *f);
    }
    let constants = vm.new_object();
    let signals = vm.obj_from(vec![("SIGINT", Value::Num(2.0)), ("SIGTERM", Value::Num(15.0)), ("SIGKILL", Value::Num(9.0)), ("SIGHUP", Value::Num(1.0))]);
    constants.set_str("signals", Value::Obj(signals), WEC);
    o.set_str("constants", Value::Obj(constants), WEC);
    o.set_str("devNull", Value::str("/dev/null"), WEC);
    Value::Obj(o)
}

fn meminfo(key: &str) -> f64 {
    if let Ok(s) = std::fs::read_to_string("/proc/meminfo") {
        for line in s.lines() {
            if let Some(rest) = line.strip_prefix(&format!("{}:", key)) {
                let kb: f64 = rest.trim().trim_end_matches("kB").trim().parse().unwrap_or(0.0);
                return kb * 1024.0;
            }
        }
    }
    0.0
}

// ---------------- CommonJS ----------------

pub fn make_require(vm: &mut Vm, dir: &str, module: Option<Obj>) -> Obj {
    let r = vm.native_closure("require", 1, require_fn, vec![Value::str(dir), module.clone().map(Value::Obj).unwrap_or(Value::Undefined)]);
    let resolve = vm.native_closure("resolve", 1, require_resolve, vec![Value::str(dir)]);
    r.set_prop(PropKey::from_str("resolve"), Value::Obj(resolve), WEC);
    let cache = vm.new_object();
    r.set_prop(PropKey::from_str("cache"), Value::Obj(cache), WEC);
    let main = vm.host.main_module.clone().map(Value::Obj).unwrap_or(Value::Undefined);
    r.set_prop(PropKey::from_str("main"), main, WEC);
    r
}

pub enum Resolved {
    Builtin(String),
    File(PathBuf),
}

fn try_file(p: &Path) -> Option<PathBuf> {
    if p.is_file() {
        return Some(p.to_path_buf());
    }
    for ext in ["js", "json", "cjs", "mjs", "node", "jsx", "ts"] {
        let mut s = p.as_os_str().to_owned();
        s.push(".");
        s.push(ext);
        let c = PathBuf::from(s);
        if c.is_file() {
            return Some(c);
        }
    }
    None
}

fn try_dir(p: &Path) -> Option<PathBuf> {
    if !p.is_dir() {
        return None;
    }
    let pj = p.join("package.json");
    if pj.is_file() {
        if let Ok(src) = std::fs::read_to_string(&pj) {
            if let Some(main) = json_string_field(&src, "main") {
                let m = p.join(&main);
                if let Some(f) = try_file(&m) {
                    return Some(f);
                }
                if let Some(f) = try_index(&m) {
                    return Some(f);
                }
            }
        }
    }
    try_index(p)
}

fn try_index(p: &Path) -> Option<PathBuf> {
    for n in ["index.js", "index.json", "index.cjs", "index.mjs"] {
        let c = p.join(n);
        if c.is_file() {
            return Some(c);
        }
    }
    None
}

/// Very small JSON field extractor for package.json ("main", "type")
pub fn json_string_field(src: &str, field: &str) -> Option<String> {
    let pat = format!("\"{}\"", field);
    let i = src.find(&pat)?;
    let rest = &src[i + pat.len()..];
    let rest = rest.trim_start();
    let rest = rest.strip_prefix(':')?.trim_start();
    let rest = rest.strip_prefix('"')?;
    let end = rest.find('"')?;
    Some(rest[..end].to_string())
}

fn normalize(p: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for c in p.components() {
        match c {
            std::path::Component::ParentDir => {
                out.pop();
            }
            std::path::Component::CurDir => {}
            other => out.push(other.as_os_str()),
        }
    }
    out
}

pub fn resolve(spec: &str, dir: &str) -> Option<Resolved> {
    if let Some(n) = spec.strip_prefix("node:") {
        return if BUILTIN_NAMES.contains(&n) { Some(Resolved::Builtin(n.to_string())) } else { None };
    }
    if BUILTIN_NAMES.contains(&spec) {
        return Some(Resolved::Builtin(spec.to_string()));
    }
    if spec.starts_with("./") || spec.starts_with("../") || spec.starts_with('/') || spec == "." || spec == ".." {
        let p = if spec.starts_with('/') { PathBuf::from(spec) } else { Path::new(dir).join(spec) };
        let p = normalize(&p);
        if let Some(f) = try_file(&p) {
            return Some(Resolved::File(f));
        }
        if let Some(f) = try_dir(&p) {
            return Some(Resolved::File(f));
        }
        return None;
    }
    // node_modules lookup
    let mut d = Some(PathBuf::from(dir));
    while let Some(cur) = d {
        let nm = cur.join("node_modules").join(spec);
        if let Some(f) = try_file(&nm) {
            return Some(Resolved::File(f));
        }
        if let Some(f) = try_dir(&nm) {
            return Some(Resolved::File(f));
        }
        d = cur.parent().map(|p| p.to_path_buf());
    }
    None
}

fn not_found(vm: &mut Vm, spec: &str, dir: &str) -> Value {
    let rel = spec.starts_with("./") || spec.starts_with("../") || spec.starts_with('/');
    let msg = if rel { format!("Cannot find module '{}' from '{}'", spec, dir) } else { format!("Cannot find module '{}'", spec) };
    let e = vm.make_error("Error", &msg);
    if let Value::Obj(o) = &e {
        o.set_prop(PropKey::from_str("code"), Value::str("MODULE_NOT_FOUND"), WEC);
    }
    e
}

fn require_resolve(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let spec = vm.to_string(&a.arg(0))?.to_rust_string();
    let dir = a.slot(0).as_obj().map(|_| String::new()).unwrap_or_else(|| match a.slot(0) {
        Value::Str(s) => s.to_rust_string(),
        _ => ".".into(),
    });
    match resolve(&spec, &dir) {
        Some(Resolved::Builtin(n)) => Ok(Value::str(&n)),
        Some(Resolved::File(p)) => Ok(Value::str(&p.to_string_lossy())),
        None => Err(not_found(vm, &spec, &dir)),
    }
}

fn require_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let spec = match a.arg(0) {
        Value::Str(s) => s.to_rust_string(),
        other => {
            let d = crate::runtime::util::describe_received(vm, &other);
            return vm.throw_type(format!("The \"id\" argument must be of type string. Received {}", d));
        }
    };
    let dir = match a.slot(0) {
        Value::Str(s) => s.to_rust_string(),
        _ => ".".into(),
    };
    let parent = a.slot(1).as_obj().cloned();
    require_spec(vm, &spec, &dir, parent)
}

pub fn require_spec(vm: &mut Vm, spec: &str, dir: &str, parent: Option<Obj>) -> JsResult<Value> {
    match resolve(spec, dir) {
        Some(Resolved::Builtin(n)) => match builtin_module(vm, &n)? {
            Some(v) => Ok(v),
            None => Err(not_found(vm, spec, dir)),
        },
        Some(Resolved::File(p)) => load_cjs(vm, &p, parent),
        None => Err(not_found(vm, spec, dir)),
    }
}

fn new_module_obj(vm: &mut Vm, path: &str, id: &str, parent: Option<Obj>) -> Obj {
    let m = vm.new_object();
    m.set_str("id", Value::str(id), WEC);
    m.set_str("filename", Value::str(path), WEC);
    m.set_str("loaded", Value::Bool(false), WEC);
    let exports = vm.new_object();
    m.set_str("exports", Value::Obj(exports), WEC);
    m.set_str("parent", parent.clone().map(Value::Obj).unwrap_or(Value::Null), WEC);
    let children = vm.new_array(Vec::new());
    m.set_str("children", Value::Obj(children), WEC);
    let paths = vm.new_array(Vec::new());
    m.set_str("paths", Value::Obj(paths), WEC);
    if let Some(p) = parent {
        if let Some(Value::Obj(ch)) = p.get_own_str("children") {
            crate::vm::array_push_raw(&ch, Value::Obj(m.clone()));
        }
    }
    m
}

pub fn load_cjs(vm: &mut Vm, path: &Path, parent: Option<Obj>) -> JsResult<Value> {
    let key = path.to_string_lossy().to_string();
    if let Some(m) = vm.host.cjs_cache.get(&key).cloned() {
        if let Some(p) = &parent {
            if let Some(Value::Obj(ch)) = p.get_own_str("children") {
                let already = crate::builtins::array::array_like_to_vec(vm, &Value::Obj(ch.clone()))?.iter().any(|c| matches!(c, Value::Obj(co) if co.ptr_eq(&m)));
                if !already {
                    crate::vm::array_push_raw(&ch, Value::Obj(m.clone()));
                }
            }
        }
        return vm.get_str(&m, "exports");
    }
    let ext = path.extension().map(|e| e.to_string_lossy().to_string()).unwrap_or_default();
    if ext == "mjs" {
        let ns = crate::modules::load_esm_sync(vm, path)?;
        return Ok(ns);
    }
    let m = new_module_obj(vm, &key, &key, parent);
    vm.host.cjs_cache.insert(key.clone(), m.clone());
    let src = match std::fs::read(path) {
        Ok(b) => String::from_utf8_lossy(&b).to_string(),
        Err(_) => return Err(not_found(vm, &key, "")),
    };
    if ext == "json" {
        let v = crate::builtins::json::json_parse(vm, &JsStr::from_str(&src))?;
        m.set_str("exports", v.clone(), WEC);
        m.set_str("loaded", Value::Bool(true), WEC);
        return Ok(v);
    }
    run_cjs_source(vm, &m, &key, &src, false)?;
    m.set_str("loaded", Value::Bool(true), WEC);
    vm.get_str(&m, "exports")
}

/// Compile and run CommonJS source with the module wrapper.
pub fn run_cjs_source(vm: &mut Vm, module: &Obj, filename: &str, src: &str, is_main: bool) -> JsResult<()> {
    let dir = Path::new(filename).parent().map(|d| d.to_string_lossy().to_string()).unwrap_or_else(|| ".".into());
    let mut body = src.to_string();
    if body.starts_with("#!") {
        body = format!("//{}", &body[2..]);
    }
    let wrapped = format!("(function (exports, require, module, __filename, __dirname) {{{}\n}})", body);
    let f = match compile_wrapper(vm, &wrapped) {
        Ok(f) => f,
        Err(e) => return Err(e),
    };
    let req = make_require(vm, &dir, Some(module.clone()));
    if is_main {
        req.set_prop(PropKey::from_str("main"), Value::Obj(module.clone()), WEC);
    }
    let exports = vm.get_str(module, "exports")?;
    let args = vec![exports.clone(), Value::Obj(req), Value::Obj(module.clone()), Value::str(filename), Value::str(&dir)];
    if is_main {
        vm.trace.push(TraceEntry { name: JsStr::from_str("runMain") });
        vm.trace.push(TraceEntry { name: JsStr::from_str(".js") });
        vm.trace.push(TraceEntry { name: JsStr::from_str("compileCommonJS") });
        vm.depth_offset += 4;
        let r = vm.call(&Value::Obj(f), exports, &args);
        vm.depth_offset -= 4;
        vm.trace.truncate(vm.trace.len() - 3);
        r?;
    } else {
        vm.call(&Value::Obj(f), exports, &args)?;
    }
    Ok(())
}

pub struct CjsSyntaxError {
    pub msg: String,
    pub line: u32,
}

thread_local! {
    pub static LAST_SYNTAX: std::cell::RefCell<Option<CjsSyntaxError>> = std::cell::RefCell::new(None);
}

fn compile_wrapper(vm: &mut Vm, wrapped: &str) -> JsResult<Obj> {
    let opts = crate::parser::ParseOptions {
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
    let code = match crate::loader::compile_program(wrapped, crate::resolver::ScopeKind::Eval, Some(&opts), false) {
        Ok(c) => c,
        Err(e) => {
            LAST_SYNTAX.with(|l| *l.borrow_mut() = Some(CjsSyntaxError { msg: e.msg.clone(), line: e.line }));
            return Err(crate::loader::syntax_error_value(vm, &e));
        }
    };
    let this = Value::Obj(vm.global.clone());
    let mut frame = crate::vm::Frame::new(code, None, this, None, Value::Undefined, Vec::new(), None);
    match vm.run_frame(&mut frame)? {
        crate::vm::Completion::Return(Value::Obj(f)) => Ok(f),
        _ => vm.throw_syntax("invalid module"),
    }
}

/// Run the main CommonJS module.
pub fn run_cjs_main(vm: &mut Vm, path: &Path, src: &str) -> JsResult<()> {
    let key = path.to_string_lossy().to_string();
    let m = new_module_obj(vm, &key, ".", None);
    vm.host.main_module = Some(m.clone());
    vm.host.cjs_cache.insert(key.clone(), m.clone());
    run_cjs_source(vm, &m, &key, src, true)?;
    m.set_str("loaded", Value::Bool(true), WEC);
    Ok(())
}
