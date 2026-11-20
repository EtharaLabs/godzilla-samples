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
    let strip = crate::runtime::typescript::make_strip_fn(vm);
    g.set_prop(PropKey::from_str("__lumenStripTypeScriptTypes"), Value::Obj(strip), CONFIGURABLE);
}

pub fn make_stdin(vm: &mut Vm) -> Value {
    let s = vm.new_object();
    crate::runtime::events::install_methods(vm, &s);
    crate::runtime::events::init_emitter(vm, &s);
    s.set_prop(PropKey::from_str("fd"), Value::Num(0.0), WEC);
    s.set_prop(PropKey::from_str("isTTY"), Value::Bool(false), WEC);
    vm.def_method(&s, "setEncoding", 1, |_vm, a| Ok(a.this.clone()));
    vm.def_method(&s, "resume", 0, stdin_resume);
    vm.def_method(&s, "pause", 0, |_vm, a| Ok(a.this.clone()));
    vm.def_method(&s, "setRawMode", 1, |_vm, a| Ok(a.this.clone()));
    vm.def_method(&s, "unref", 0, |_vm, a| Ok(a.this.clone()));
    vm.def_method(&s, "ref", 0, |_vm, a| Ok(a.this.clone()));
    Value::Obj(s)
}

/// Read all of stdin and emit 'data' + 'end' (used when a script listens to process.stdin).
fn stdin_resume(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let already = matches!(this.as_obj().and_then(|o| o.get_own_str("__reading")), Some(Value::Bool(true)));
    if already {
        return Ok(this);
    }
    if let Value::Obj(o) = &this {
        o.set_prop(PropKey::from_str("__reading"), Value::Bool(true), WC);
    }
    let target = this.clone();
    crate::runtime::spawn_op(
        vm,
        || {
            use std::io::Read;
            let mut buf = Vec::new();
            let _ = std::io::stdin().read_to_end(&mut buf);
            buf
        },
        move |vm: &mut Vm, buf: Vec<u8>| {
            if !buf.is_empty() {
                let s = String::from_utf8_lossy(&buf).to_string();
                let _ = crate::runtime::events::emit_event(vm, &target, &Value::str("data"), &[Value::str(&s)]);
            }
            let _ = crate::runtime::events::emit_event(vm, &target, &Value::str("end"), &[]);
            let _ = crate::runtime::events::emit_event(vm, &target, &Value::str("close"), &[]);
        },
    );
    Ok(this)
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

// ---------------- node:module ----------------

/// `require("module").builtinModules` (and the names `isBuiltin` accepts).
const MODULE_BUILTINS: &[&str] = &[
    "buffer", "path", "path/posix", "path/win32", "os", "events", "diagnostics_channel", "domain", "trace_events", "util/types",
    "util", "console", "timers/promises", "timers", "crypto", "punycode", "perf_hooks", "querystring", "url", "assert",
    "assert/strict", "string_decoder", "tty", "async_hooks", "zlib", "stream", "stream/web", "net", "fs", "fs/promises", "http",
    "https", "http2", "child_process", "dns", "dns/promises", "v8", "inspector", "inspector/promises", "sys", "stream/promises",
    "stream/consumers", "readline", "readline/promises", "process", "tls", "test", "worker_threads", "vm", "repl", "cluster",
    "dgram", "wasi", "constants", "bun:ffi", "bun:jsc", "bun:sqlite", "bun", "module",
];

thread_local! {
    /// module.getSourceMapsSupport(): enabled, nodeModules, generatedCode
    static SOURCE_MAPS: std::cell::Cell<(bool, bool, bool)> = const { std::cell::Cell::new((false, false, false)) };
}

fn is_module_builtin(spec: &str) -> bool {
    MODULE_BUILTINS.contains(&spec.strip_prefix("node:").unwrap_or(spec))
}

fn path_dirname(p: &str) -> String {
    match Path::new(p).parent() {
        Some(d) if !d.as_os_str().is_empty() => d.to_string_lossy().to_string(),
        Some(_) => ".".to_string(),
        None => p.to_string(),
    }
}

fn path_resolve(p: &str) -> PathBuf {
    let cwd = std::env::current_dir().unwrap_or_default();
    normalize(&cwd.join(p))
}

/// Directory a `parent` module resolves from: its filename's directory, else the cwd.
fn parent_dir(vm: &mut Vm, parent: &Value) -> JsResult<String> {
    if let Value::Obj(o) = parent {
        if let Value::Str(f) = vm.get_str(o, "filename")? {
            return Ok(path_dirname(&f.to_rust_string()));
        }
    }
    Ok(std::env::current_dir().map(|p| p.to_string_lossy().to_string()).unwrap_or_default())
}

/// String form of a path or file: URL (string or URL object).
fn to_fs_path(vm: &mut Vm, v: &Value) -> JsResult<String> {
    let mut p = match v {
        Value::Obj(o) => {
            let href = vm.get_str(o, "href")?;
            if href.truthy() {
                vm.to_string(&href)?.to_rust_string()
            } else {
                vm.to_string(v)?.to_rust_string()
            }
        }
        other => vm.to_string(other)?.to_rust_string(),
    };
    if let Some(rest) = p.strip_prefix("file://") {
        p = rest.to_string();
    }
    Ok(p)
}

fn module_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return vm.throw_type("Class constructor Module cannot be invoked without 'new'");
    }
    let proto = vm.global.clone();
    let fallback = match vm.get_str(&a.callee.clone(), "prototype")? {
        Value::Obj(p) => p,
        _ => proto,
    };
    let p = vm.proto_from_nt(&a.new_target, &fallback)?;
    let m = Obj::new(Some(p), ObjKind::Ordinary);
    let id = if a.arg(0).is_undefined() { Value::str("") } else { a.arg(0) };
    let id_s = vm.to_string(&id)?.to_rust_string();
    let path = if id.truthy() { path_dirname(&id_s) } else { ".".to_string() };
    m.set_str("id", id, WEC);
    m.set_str("path", Value::str(&path), WEC);
    let exports = vm.new_object();
    m.set_str("exports", Value::Obj(exports), WEC);
    m.set_str("filename", Value::Null, WEC);
    m.set_str("loaded", Value::Bool(false), WEC);
    let children = vm.new_array(Vec::new());
    m.set_str("children", Value::Obj(children), WEC);
    m.set_str("parent", a.arg(1), WEC);
    let paths = vm.new_array(Vec::new());
    m.set_str("paths", Value::Obj(paths), WEC);
    Ok(Value::Obj(m))
}

/// Module.prototype.require(id): resolved from the module's `path`.
fn module_proto_require(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let spec = match a.arg(0) {
        Value::Sym(s) => s.descriptive_string(),
        other => vm.to_string(&other)?.to_rust_string(),
    };
    let dir = match &a.this {
        Value::Obj(o) => match vm.get_str(o, "path")? {
            Value::Str(s) => s.to_rust_string(),
            _ => ".".to_string(),
        },
        _ => ".".to_string(),
    };
    require_spec(vm, &spec, &dir, a.this.as_obj().cloned())
}

fn create_require(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = to_fs_path(vm, &a.arg(0))?;
    let dir = if Path::new(&p).is_dir() { p } else { path_dirname(&p) };
    Ok(Value::Obj(make_require(vm, &dir, None)))
}

fn module_is_builtin(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(match a.arg(0) {
        Value::Str(s) => is_module_builtin(&s.to_rust_string()),
        _ => false,
    }))
}

fn source_maps_object(vm: &mut Vm) -> Value {
    let (e, n, g) = SOURCE_MAPS.with(|c| c.get());
    Value::Obj(vm.obj_from(vec![("enabled", Value::Bool(e)), ("nodeModules", Value::Bool(n)), ("generatedCode", Value::Bool(g))]))
}

fn module_set_source_maps(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let enabled = a.arg(0).truthy();
    let (mut n, mut g) = (false, false);
    if let Value::Obj(o) = a.arg(1) {
        n = vm.get_str(&o, "nodeModules")?.truthy();
        g = vm.get_str(&o, "generatedCode")?.truthy();
    }
    SOURCE_MAPS.with(|c| c.set((enabled, n, g)));
    Ok(Value::Undefined)
}

fn module_find_package_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let base = a.arg(1);
    let from_input = if base.is_nullish() {
        std::env::current_dir().map(|p| p.to_string_lossy().to_string()).unwrap_or_default()
    } else {
        to_fs_path(vm, &base)?
    };
    let from_dir = if Path::new(&from_input).is_dir() { from_input } else { path_dirname(&from_input) };
    let spec = match a.arg(0) {
        Value::Sym(s) => s.descriptive_string(),
        other => vm.to_string(&other)?.to_rust_string(),
    };
    let resolved = match resolve(&spec, &from_dir) {
        Some(Resolved::File(p)) => p,
        _ => return Ok(Value::Undefined),
    };
    let mut dir = resolved.parent().map(|d| d.to_path_buf());
    while let Some(d) = dir {
        let pj = d.join("package.json");
        if pj.is_file() {
            return Ok(Value::str(&pj.to_string_lossy()));
        }
        dir = d.parent().map(|x| x.to_path_buf());
    }
    Ok(Value::Undefined)
}

fn module_register(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    vm.throw_error("Error", "node:module register() (async ESM loader hooks) is not supported in lumen; module.registerHooks (the sync API) is")
}

fn module_register_hooks(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let hooks = match a.arg(0) {
        Value::Obj(o) if !Value::Obj(o.clone()).is_callable() => o,
        other => {
            let what = if matches!(other, Value::Null) { "null".to_string() } else { other.type_of().to_string() };
            return vm.throw_type(format!("Cannot destructure property 'resolve' of 'hooks' as it is {}.", what));
        }
    };
    for name in ["resolve", "load"] {
        let v = vm.get_str(&hooks, name)?;
        if !v.is_undefined() && !v.is_callable() {
            let e = vm.make_error("TypeError", &format!("The \"hooks.{}\" property must be of type function. Received type {}", name, v.type_of()));
            if let Value::Obj(o) = &e {
                o.set_prop(PropKey::from_str("code"), Value::str("ERR_INVALID_ARG_TYPE"), WEC);
            }
            return Err(e);
        }
    }
    let handle = vm.new_object();
    let dereg = vm.native_fn("deregister", 0, |_vm, _a| Ok(Value::Undefined));
    handle.set_str("deregister", Value::Obj(dereg), WEC);
    Ok(Value::Obj(handle))
}

fn module_enable_compile_cache(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Obj(vm.obj_from(vec![("status", Value::Num(3.0)), ("message", Value::str("compile cache is not supported in lumen"))])))
}

fn module_run_main(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let entry = if a.arg(0).is_nullish() {
        match vm.host.argv.get(1) {
            Some(s) => s.clone(),
            None => String::new(),
        }
    } else {
        vm.to_string(&a.arg(0))?.to_rust_string()
    };
    if entry.is_empty() {
        return vm.throw_error("Error", "Module.runMain: no entry point (process.argv[1] is empty)");
    }
    let path = std::fs::canonicalize(&entry).unwrap_or_else(|_| PathBuf::from(&entry));
    load_cjs_with(vm, &path, None, 0)
}

/// node_modules directories looked up from `from` (outermost last; no `node_modules/node_modules`).
fn node_module_paths(from: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut dir = Some(path_resolve(from));
    while let Some(d) = dir {
        if d.file_name().map_or(true, |n| n != "node_modules") {
            out.push(d.join("node_modules").to_string_lossy().to_string());
        }
        dir = d.parent().map(|p| p.to_path_buf());
    }
    out
}

fn module_node_module_paths(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let from = vm.to_string(&a.arg(0))?.to_rust_string();
    let items: Vec<Value> = node_module_paths(&from).iter().map(|s| Value::str(s)).collect();
    Ok(Value::Obj(vm.new_array(items)))
}

fn resolve_filename_from(vm: &mut Vm, request: &Value, parent: &Value) -> JsResult<String> {
    let spec = vm.to_string(request)?.to_rust_string();
    if is_module_builtin(&spec) {
        return Ok(spec);
    }
    let dir = parent_dir(vm, parent)?;
    match resolve(&spec, &dir) {
        Some(Resolved::File(p)) => Ok(p.to_string_lossy().to_string()),
        Some(Resolved::Builtin(n)) => Ok(format!("node:{}", n)),
        None => Err(not_found(vm, &spec, &dir)),
    }
}

fn module_resolve_filename(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = resolve_filename_from(vm, &a.arg(0), &a.arg(1))?;
    Ok(Value::str(&r))
}

fn module_resolve_lookup_paths(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let spec = vm.to_string(&a.arg(0))?.to_rust_string();
    if is_module_builtin(&spec) || spec.starts_with("./") || spec.starts_with("../") || spec.starts_with('/') {
        return Ok(Value::Null);
    }
    let dir = parent_dir(vm, &a.arg(1))?;
    let items: Vec<Value> = node_module_paths(&dir).iter().map(|s| Value::str(s)).collect();
    Ok(Value::Obj(vm.new_array(items)))
}

fn module_load(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let spec = vm.to_string(&a.arg(0))?.to_rust_string();
    let dir = parent_dir(vm, &a.arg(1))?;
    require_spec(vm, &spec, &dir, a.arg(1).as_obj().cloned())
}

fn module_find_path(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let request = vm.to_string(&a.arg(0))?.to_rust_string();
    let paths = if a.arg(1).is_nullish() { Vec::new() } else { crate::builtins::array::array_like_to_vec(vm, &a.arg(1))? };
    for p in paths {
        let base = vm.to_string(&p)?.to_rust_string();
        let target = path_resolve(&Path::new(&base).join(&request).to_string_lossy());
        if let Some(f) = try_file(&target, ResolveKind::Require).or_else(|| try_dir(&target, ResolveKind::Require)) {
            return Ok(Value::str(&f.to_string_lossy()));
        }
    }
    Ok(Value::Bool(false))
}

/// `Module._extensions[ext](module, filename)`: compile a file into the given module object.
fn module_extension_handler(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ext = match a.slot(0) {
        Value::Str(s) => s.to_rust_string(),
        _ => ".js".into(),
    };
    let module = match a.arg(0) {
        Value::Obj(o) => o,
        _ => return vm.throw_type("module must be an object"),
    };
    let filename = vm.to_string(&a.arg(1))?.to_rust_string();
    if ext == ".node" {
        return vm.throw_error("Error", format!("cannot load native addon '{}'", filename));
    }
    let src = match std::fs::read(&filename).map(String::from_utf8) {
        Ok(Ok(s)) => s,
        Ok(Err(_)) => return vm.throw_error("Error", format!("cannot read '{}': stream did not contain valid UTF-8", filename)),
        Err(_) => return vm.throw_error("Error", format!("cannot read '{}'", filename)),
    };
    if ext == ".json" {
        let v = crate::builtins::json::json_parse(vm, &JsStr::from_str(&src))?;
        module.set_str("exports", v, WEC);
        return Ok(Value::Undefined);
    }
    let code = handler_source(vm, Path::new(&filename), ext.trim_start_matches('.'), src)?;
    run_cjs_source(vm, &module, &filename, &code, false)?;
    Ok(Value::Undefined)
}

fn source_map_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return vm.throw_type("Class constructor SourceMap cannot be invoked without 'new'");
    }
    let fallback = match vm.get_str(&a.callee.clone(), "prototype")? {
        Value::Obj(p) => p,
        _ => vm.intr.object_proto.clone(),
    };
    let p = vm.proto_from_nt(&a.new_target, &fallback)?;
    let o = Obj::new(Some(p), ObjKind::Ordinary);
    let payload = a.arg(0);
    let line_lengths = match a.arg(1) {
        Value::Obj(opts) => {
            let l = vm.get_str(&opts, "lineLengths")?;
            if l.truthy() {
                l
            } else {
                Value::Obj(vm.new_array(Vec::new()))
            }
        }
        _ => Value::Obj(vm.new_array(Vec::new())),
    };
    let gp = vm.native_closure("get payload", 0, |_vm, a| Ok(a.slot(0)), vec![payload]);
    let gl = vm.native_closure("get lineLengths", 0, |_vm, a| Ok(a.slot(0)), vec![line_lengths]);
    o.borrow_mut().props.insert(PropKey::from_str("payload"), Prop::Accessor { get: Some(gp), set: None, flags: ENUMERABLE });
    o.borrow_mut().props.insert(PropKey::from_str("lineLengths"), Prop::Accessor { get: Some(gl), set: None, flags: ENUMERABLE });
    Ok(Value::Obj(o))
}

fn create_module_module(vm: &mut Vm) -> Value {
    let proto = vm.new_object();
    let m = vm.native_ctor("Module", 0, module_ctor, &proto);
    vm.def_method(&proto, "require", 1, module_proto_require);
    let set = |o: &Obj, k: &str, v: Value| o.set_prop(PropKey::from_str(k), v, WEC);
    set(&m, "Module", Value::Obj(m.clone()));
    let sm_proto = vm.new_object();
    let sm = vm.native_ctor("SourceMap", 2, source_map_ctor, &sm_proto);
    set(&m, "SourceMap", Value::Obj(sm));
    let names: Vec<Value> = MODULE_BUILTINS.iter().map(|s| Value::str(s)).collect();
    let list = vm.new_array(names);
    set(&m, "builtinModules", Value::Obj(list));
    let status = vm.obj_from(vec![
        ("FAILED", Value::Num(0.0)),
        ("ENABLED", Value::Num(1.0)),
        ("ALREADY_ENABLED", Value::Num(2.0)),
        ("DISABLED", Value::Num(3.0)),
    ]);
    let constants = vm.obj_from(vec![("compileCacheStatus", Value::Obj(status))]);
    set(&m, "constants", Value::Obj(constants));
    let fns: &[(&str, &str, u32, NativeFn)] = &[
        ("createRequire", "createRequire", 1, create_require),
        ("isBuiltin", "isBuiltin", 1, module_is_builtin),
        ("syncBuiltinESMExports", "syncBuiltinESMExports", 0, |_vm, _a| Ok(Value::Undefined)),
        ("findSourceMap", "findSourceMap", 0, |_vm, _a| Ok(Value::Undefined)),
        ("getSourceMapsSupport", "getSourceMapsSupport", 0, |vm, _a| Ok(source_maps_object(vm))),
        ("setSourceMapsSupport", "setSourceMapsSupport", 2, module_set_source_maps),
        ("findPackageJSON", "findPackageJSON", 2, module_find_package_json),
        ("register", "register", 0, module_register),
        ("registerHooks", "registerHooks", 1, module_register_hooks),
    ];
    for (key, name, len, f) in fns {
        let fo = vm.native_fn(name, *len, *f);
        set(&m, key, Value::Obj(fo));
    }
    let strip = vm.global.get_own_str("__lumenStripTypeScriptTypes").unwrap_or(Value::Undefined);
    set(&m, "stripTypeScriptTypes", strip);
    let fns: &[(&str, &str, u32, NativeFn)] = &[
        ("enableCompileCache", "enableCompileCache", 0, module_enable_compile_cache),
        ("getCompileCacheDir", "getCompileCacheDir", 0, |_vm, _a| Ok(Value::Undefined)),
        ("flushCompileCache", "flushCompileCache", 0, |_vm, _a| Ok(Value::Undefined)),
        ("runMain", "moduleRunMain", 1, module_run_main),
    ];
    for (key, name, len, f) in fns {
        let fo = vm.native_fn(name, *len, *f);
        set(&m, key, Value::Obj(fo));
    }
    let exts = vm.new_object();
    for ext in [".js", ".ts", ".cts", ".json", ".node"] {
        let h = vm.native_closure(ext, 2, module_extension_handler, vec![Value::str(ext)]);
        set(&exts, ext, Value::Obj(h));
    }
    set(&m, "_extensions", Value::Obj(exts));
    let path_cache = vm.new_object();
    set(&m, "_pathCache", Value::Obj(path_cache));
    let fns: &[(&str, &str, u32, NativeFn)] = &[
        ("_debug", "", 0, |_vm, _a| Ok(Value::Undefined)),
        ("_findPath", "_findPath", 2, module_find_path),
        ("_nodeModulePaths", "nodeModulePaths", 1, module_node_module_paths),
        ("_resolveFilename", "_resolveFilename", 2, module_resolve_filename),
        ("_resolveLookupPaths", "_resolveLookupPaths", 2, module_resolve_lookup_paths),
        ("_load", "_load", 3, module_load),
        ("_initPaths", "", 0, |_vm, _a| Ok(Value::Undefined)),
        ("_preloadModules", "", 0, |_vm, _a| Ok(Value::Undefined)),
    ];
    for (key, name, len, f) in fns {
        let fo = vm.native_fn(name, *len, *f);
        set(&m, key, Value::Obj(fo));
    }
    let cache = vm.new_object();
    let keys = CJS_ORDER.with(|o| o.borrow().clone());
    for k in keys {
        if let Some(mo) = vm.host.cjs_cache.get(&k) {
            cache.set_prop(PropKey::from_str(&k), Value::Obj(mo.clone()), WEC);
        }
    }
    MODULE_CACHE.with(|c| *c.borrow_mut() = Some(cache.clone()));
    set(&m, "_cache", Value::Obj(cache));
    let home = std::env::var("HOME").unwrap_or_default();
    let global_paths = vm.new_array(vec![Value::str(&format!("{}/.node_modules", home)), Value::str(&format!("{}/.node_libraries", home))]);
    set(&m, "globalPaths", Value::Obj(global_paths));
    Value::Obj(m)
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
    // like the original's JS function: an own `prototype`, an anonymous `resolve`
    let proto = vm.new_object();
    proto.set_prop(PropKey::from_str("constructor"), Value::Obj(r.clone()), WC);
    r.set_prop(PropKey::from_str("prototype"), Value::Obj(proto), WRITABLE);
    let resolve = vm.native_closure("", 1, require_resolve, vec![Value::str(dir)]);
    r.set_prop(PropKey::from_str("resolve"), Value::Obj(resolve), WEC);
    let getter = vm.native_fn("get cache", 0, require_cache_get);
    r.borrow_mut().props.insert(PropKey::from_str("cache"), Prop::Accessor { get: Some(getter), set: None, flags: ENUMERABLE | CONFIGURABLE });
    let main = vm.host.main_module.clone().map(Value::Obj).unwrap_or(Value::Null);
    r.set_prop(PropKey::from_str("main"), main, WEC);
    r
}

thread_local! {
    /// CommonJS module cache keys in load order (`require.cache` enumeration order)
    static CJS_ORDER: std::cell::RefCell<Vec<String>> = std::cell::RefCell::new(Vec::new());
}

fn cache_module(vm: &mut Vm, key: &str, m: &Obj) {
    vm.host.cjs_cache.insert(key.to_string(), m.clone());
    CJS_ORDER.with(|o| o.borrow_mut().push(key.to_string()));
    if let Some(c) = MODULE_CACHE.with(|c| c.borrow().clone()) {
        c.set_prop(PropKey::from_str(key), Value::Obj(m.clone()), WEC);
    }
}

thread_local! {
    /// `Module._cache` once `node:module` has been loaded (kept in sync by cache_module)
    static MODULE_CACHE: std::cell::RefCell<Option<Obj>> = const { std::cell::RefCell::new(None) };
}

/// `require.cache`: a fresh null-prototype snapshot of the module cache (filename -> module).
fn require_cache_get(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let o = Obj::new(None, ObjKind::Ordinary);
    let keys = CJS_ORDER.with(|o| o.borrow().clone());
    for k in keys {
        if let Some(m) = vm.host.cjs_cache.get(&k) {
            o.set_prop(PropKey::from_str(&k), Value::Obj(m.clone()), WEC);
        }
    }
    Ok(Value::Obj(o))
}

pub enum Resolved {
    Builtin(String),
    File(PathBuf),
}

/// Extensions tried (in order) when a `require` target has none.
const REQUIRE_EXTS: &[&str] = &["js", "json", "cjs", "ts", "cts", "node"];
/// Extensions tried (in order) when an `import` target has none.
const IMPORT_EXTS: &[&str] = &["mjs", "js", "jsx", "json", "cjs"];

#[derive(Clone, Copy, PartialEq)]
enum ResolveKind {
    Require,
    Import,
}

impl ResolveKind {
    fn exts(self) -> &'static [&'static str] {
        match self {
            ResolveKind::Require => REQUIRE_EXTS,
            ResolveKind::Import => IMPORT_EXTS,
        }
    }
}

fn found(p: PathBuf) -> PathBuf {
    std::fs::canonicalize(&p).unwrap_or(p)
}

fn try_file(p: &Path, kind: ResolveKind) -> Option<PathBuf> {
    if p.is_file() {
        return Some(found(p.to_path_buf()));
    }
    for ext in kind.exts() {
        let mut s = p.as_os_str().to_owned();
        s.push(".");
        s.push(ext);
        let c = PathBuf::from(s);
        if c.is_file() {
            return Some(found(c));
        }
    }
    None
}

fn try_index(p: &Path, kind: ResolveKind) -> Option<PathBuf> {
    for ext in kind.exts() {
        let c = p.join(format!("index.{}", ext));
        if c.is_file() {
            return Some(found(c));
        }
    }
    None
}

fn try_target(base: &Path, target: &str, kind: ResolveKind) -> Option<PathBuf> {
    let t = normalize(&base.join(target));
    try_file(&t, kind).or_else(|| if t.is_dir() { try_index(&t, kind) } else { None })
}

/// Package entry named by `exports` (only the package root is mapped): `require` reads the
/// "." entry (or the whole value) and takes a string, or the first string among the require /
/// node / default conditions; `import` takes a string `exports`, or else the first "import" /
/// "default" string field anywhere in package.json. None when nothing usable is named.
fn exports_target(src: &str, kind: ResolveKind) -> Option<String> {
    match kind {
        ResolveKind::Require => {
            let pkg = Json::parse(src)?;
            let exp = pkg.get("exports")?;
            let target = match exp {
                Json::Obj(_) => exp.get(".").unwrap_or(exp),
                other => other,
            };
            match target {
                Json::Str(s) => Some(s.clone()),
                Json::Obj(_) => ["require", "node", "default"].iter().find_map(|c| match target.get(c) {
                    Some(Json::Str(s)) => Some(s.clone()),
                    _ => None,
                }),
                _ => None,
            }
        }
        ResolveKind::Import => {
            if !src.contains("\"exports\"") {
                return None;
            }
            json_string_field(src, "exports").or_else(|| json_string_field(src, "import")).or_else(|| json_string_field(src, "default"))
        }
    }
}

fn try_dir(p: &Path, kind: ResolveKind) -> Option<PathBuf> {
    if !p.is_dir() {
        return None;
    }
    let pj = p.join("package.json");
    if let Ok(src) = std::fs::read_to_string(&pj) {
        if let Some(target) = exports_target(&src, kind) {
            // a named entry that does not exist falls back to the index file only
            return try_target(p, &target, kind).or_else(|| try_index(p, kind));
        }
        let fields: &[&str] = if kind == ResolveKind::Import { &["module", "main"] } else { &["main"] };
        for field in fields {
            if let Some(main) = json_string_field(&src, field) {
                if let Some(f) = try_target(p, &main, kind) {
                    return Some(f);
                }
            }
        }
    }
    try_index(p, kind)
}

/// Minimal JSON value (object keys in source order) for package.json reading.
#[allow(dead_code)]
enum Json {
    Null,
    Bool(bool),
    Num(f64),
    Str(String),
    Arr(Vec<Json>),
    Obj(Vec<(String, Json)>),
}

impl Json {
    fn parse(src: &str) -> Option<Json> {
        let cs: Vec<char> = src.chars().collect();
        let mut i = 0;
        let v = json_value(&cs, &mut i)?;
        json_ws(&cs, &mut i);
        if i == cs.len() {
            Some(v)
        } else {
            None
        }
    }

    fn get(&self, k: &str) -> Option<&Json> {
        match self {
            Json::Obj(kv) => kv.iter().find(|(n, _)| n == k).map(|(_, v)| v),
            _ => None,
        }
    }
}

fn json_ws(cs: &[char], i: &mut usize) {
    while *i < cs.len() && matches!(cs[*i], ' ' | '\t' | '\n' | '\r') {
        *i += 1;
    }
}

fn json_string(cs: &[char], i: &mut usize) -> Option<String> {
    if cs.get(*i) != Some(&'"') {
        return None;
    }
    *i += 1;
    let mut out = String::new();
    loop {
        let c = *cs.get(*i)?;
        *i += 1;
        match c {
            '"' => return Some(out),
            '\\' => {
                let e = *cs.get(*i)?;
                *i += 1;
                match e {
                    'n' => out.push('\n'),
                    't' => out.push('\t'),
                    'r' => out.push('\r'),
                    'b' => out.push('\u{8}'),
                    'f' => out.push('\u{c}'),
                    'u' => {
                        let h: String = cs.get(*i..*i + 4)?.iter().collect();
                        *i += 4;
                        out.push(char::from_u32(u32::from_str_radix(&h, 16).ok()?).unwrap_or('\u{fffd}'));
                    }
                    other => out.push(other),
                }
            }
            c => out.push(c),
        }
    }
}

fn json_value(cs: &[char], i: &mut usize) -> Option<Json> {
    json_ws(cs, i);
    match *cs.get(*i)? {
        '{' => {
            *i += 1;
            let mut kv = Vec::new();
            json_ws(cs, i);
            if cs.get(*i) == Some(&'}') {
                *i += 1;
                return Some(Json::Obj(kv));
            }
            loop {
                json_ws(cs, i);
                let k = json_string(cs, i)?;
                json_ws(cs, i);
                if cs.get(*i) != Some(&':') {
                    return None;
                }
                *i += 1;
                let v = json_value(cs, i)?;
                kv.push((k, v));
                json_ws(cs, i);
                match cs.get(*i)? {
                    ',' => *i += 1,
                    '}' => {
                        *i += 1;
                        return Some(Json::Obj(kv));
                    }
                    _ => return None,
                }
            }
        }
        '[' => {
            *i += 1;
            let mut items = Vec::new();
            json_ws(cs, i);
            if cs.get(*i) == Some(&']') {
                *i += 1;
                return Some(Json::Arr(items));
            }
            loop {
                items.push(json_value(cs, i)?);
                json_ws(cs, i);
                match cs.get(*i)? {
                    ',' => *i += 1,
                    ']' => {
                        *i += 1;
                        return Some(Json::Arr(items));
                    }
                    _ => return None,
                }
            }
        }
        '"' => json_string(cs, i).map(Json::Str),
        't' if cs.get(*i..*i + 4) == Some(&['t', 'r', 'u', 'e'][..]) => {
            *i += 4;
            Some(Json::Bool(true))
        }
        'f' if cs.get(*i..*i + 5) == Some(&['f', 'a', 'l', 's', 'e'][..]) => {
            *i += 5;
            Some(Json::Bool(false))
        }
        'n' if cs.get(*i..*i + 4) == Some(&['n', 'u', 'l', 'l'][..]) => {
            *i += 4;
            Some(Json::Null)
        }
        _ => {
            let start = *i;
            while *i < cs.len() && matches!(cs[*i], '0'..='9' | '-' | '+' | '.' | 'e' | 'E') {
                *i += 1;
            }
            let t: String = cs[start..*i].iter().collect();
            t.parse::<f64>().ok().map(Json::Num)
        }
    }
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

/// Resolve a `require` specifier from directory `dir`.
pub fn resolve(spec: &str, dir: &str) -> Option<Resolved> {
    resolve_with(spec, dir, ResolveKind::Require)
}

/// Resolve an `import` specifier from directory `dir` (ES module extension order, .jsx).
pub fn resolve_esm(spec: &str, dir: &str) -> Option<Resolved> {
    resolve_with(spec, dir, ResolveKind::Import)
}

fn resolve_with(spec: &str, dir: &str, kind: ResolveKind) -> Option<Resolved> {
    if let Some(n) = spec.strip_prefix("node:") {
        return if BUILTIN_NAMES.contains(&n) { Some(Resolved::Builtin(n.to_string())) } else { None };
    }
    if BUILTIN_NAMES.contains(&spec) {
        return Some(Resolved::Builtin(spec.to_string()));
    }
    if spec.starts_with("./") || spec.starts_with("../") || spec.starts_with('/') {
        let p = if spec.starts_with('/') { PathBuf::from(spec) } else { Path::new(dir).join(spec) };
        let p = normalize(&p);
        if let Some(f) = try_file(&p, kind) {
            return Some(Resolved::File(f));
        }
        if let Some(f) = try_dir(&p, kind) {
            return Some(Resolved::File(f));
        }
        return None;
    }
    // node_modules lookup
    let mut d = Some(PathBuf::from(dir));
    while let Some(cur) = d {
        let nm = cur.join("node_modules").join(spec);
        if let Some(f) = try_file(&nm, kind) {
            return Some(Resolved::File(f));
        }
        if let Some(f) = try_dir(&nm, kind) {
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
        Some(Resolved::Builtin(n)) => Ok(Value::str(&format!("node:{}", n))),
        Some(Resolved::File(p)) => Ok(Value::str(&p.to_string_lossy())),
        None => Err(not_found(vm, &spec, &dir)),
    }
}

fn require_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    // the specifier goes through String(): require(5) looks for a module named '5'
    let spec = match a.arg(0) {
        Value::Str(s) => s.to_rust_string(),
        Value::Sym(s) => s.descriptive_string(),
        other => vm.to_string(&other)?.to_rust_string(),
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
        Some(Resolved::File(p)) => load_cjs_with(vm, &p, parent, 4),
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

/// Load a CommonJS module for an ES module `import` (the original routes these through `require`).
pub fn load_cjs(vm: &mut Vm, path: &Path, parent: Option<Obj>) -> JsResult<Value> {
    load_cjs_with(vm, path, parent, 5)
}

/// Name of the `Module._extensions` handler compiling a file (shows up in stack traces).
fn handler_name(ext: &str) -> &'static str {
    match ext {
        "ts" => ".ts",
        "cts" => ".cts",
        "json" => ".json",
        _ => ".js",
    }
}

fn ext_of(path: &Path) -> String {
    path.extension().map(|e| e.to_string_lossy().to_string()).unwrap_or_default()
}

/// The source a module's extension handler compiles: TypeScript is type-stripped.
fn handler_source(vm: &mut Vm, path: &Path, ext: &str, src: String) -> JsResult<String> {
    if ext == "ts" || ext == "cts" {
        return match crate::runtime::typescript::strip_types(&src) {
            Ok(code) => Ok(format!("{}\n\n//# sourceURL={};", code, path.to_string_lossy())),
            Err(msg) => vm.throw_syntax(msg),
        };
    }
    Ok(src)
}

/// `extra_depth`: call-stack budget used by the original's JS loader frames (require,
/// loadModule, the extension handler, compileCommonJS) that have no counterpart here.
fn load_cjs_with(vm: &mut Vm, path: &Path, parent: Option<Obj>, extra_depth: usize) -> JsResult<Value> {
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
    let ext = ext_of(path);
    let m = new_module_obj(vm, &key, &key, parent);
    cache_module(vm, &key, &m);
    let src = match std::fs::read(path) {
        Ok(b) => match String::from_utf8(b) {
            Ok(s) => s,
            Err(_) => return Err(vm.make_error("Error", &format!("cannot read '{}': stream did not contain valid UTF-8", key))),
        },
        Err(_) => return Err(not_found(vm, &key, "")),
    };
    if ext == "json" {
        let v = crate::builtins::json::json_parse(vm, &JsStr::from_str(&src))?;
        m.set_str("exports", v.clone(), WEC);
        m.set_str("loaded", Value::Bool(true), WEC);
        return Ok(v);
    }
    let code = handler_source(vm, path, &ext, src)?;
    let names = ["require", "loadModule", handler_name(&ext), "compileCommonJS"];
    for n in names {
        vm.trace.push(TraceEntry { name: JsStr::from_str(n) });
    }
    vm.depth_offset += extra_depth;
    let r = run_cjs_source(vm, &m, &key, &code, false);
    vm.depth_offset -= extra_depth;
    let keep = vm.trace.len().saturating_sub(names.len());
    vm.trace.truncate(keep);
    r?;
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
    vm.call(&Value::Obj(f), exports, &args)?;
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
    let mut code = match crate::loader::compile_program(wrapped, crate::resolver::ScopeKind::Eval, Some(&opts), false) {
        Ok(c) => c,
        Err(e) => {
            LAST_SYNTAX.with(|l| *l.borrow_mut() = Some(CjsSyntaxError { msg: e.msg.clone(), line: e.line }));
            return Err(crate::loader::syntax_error_value(vm, &e));
        }
    };
    // the module wrapper shows up as "anonymous" in stack traces (without a name binding)
    if let Some(script) = std::rc::Rc::get_mut(&mut code) {
        if let Some(wrapper) = script.funcs.first_mut().and_then(std::rc::Rc::get_mut) {
            wrapper.name = JsStr::from_str("anonymous");
        }
    }
    let this = Value::Obj(vm.global.clone());
    let mut frame = crate::vm::Frame::new(code, None, this, None, Value::Undefined, Vec::new(), None);
    match vm.run_frame(&mut frame)? {
        crate::vm::Completion::Return(Value::Obj(f)) => Ok(f),
        _ => vm.throw_syntax("invalid module"),
    }
}

/// Run the main CommonJS module (`src`: the file contents; TypeScript is stripped here).
pub fn run_cjs_main(vm: &mut Vm, path: &Path, src: &str) -> JsResult<()> {
    let key = path.to_string_lossy().to_string();
    let m = new_module_obj(vm, &key, ".", None);
    vm.host.main_module = Some(m.clone());
    cache_module(vm, &key, &m);
    let ext = ext_of(path);
    if ext == "json" {
        let v = crate::builtins::json::json_parse(vm, &JsStr::from_str(src))?;
        m.set_str("exports", v, WEC);
        m.set_str("loaded", Value::Bool(true), WEC);
        return Ok(());
    }
    let code = handler_source(vm, path, &ext, src.to_string())?;
    let names = ["runMain", handler_name(&ext), "compileCommonJS"];
    for n in names {
        vm.trace.push(TraceEntry { name: JsStr::from_str(n) });
    }
    vm.depth_offset += 4;
    let r = run_cjs_source(vm, &m, &key, &code, true);
    vm.depth_offset -= 4;
    let keep = vm.trace.len().saturating_sub(names.len());
    vm.trace.truncate(keep);
    r?;
    m.set_str("loaded", Value::Bool(true), WEC);
    Ok(())
}

// ---------------- CommonJS export names (for ES module imports) ----------------

/// Named exports an ES module may import from a CommonJS module, found by scanning its source
/// text (the module has not run yet when importers are linked): `exports.X =` /
/// `module.exports.X =`, `Object.defineProperty(exports, "X", ...)` and the entries of
/// `module.exports = { ... }` object literals. Like the original, this is a plain text scan
/// (comments and strings are not excluded).
pub fn cjs_export_names(src: &str) -> Vec<String> {
    let cs: Vec<char> = src.chars().collect();
    let n = cs.len();
    let mut names: Vec<String> = Vec::new();
    const RESERVED: &[&str] = &[
        "break", "case", "catch", "class", "const", "continue", "debugger", "default", "delete", "do", "else", "enum", "export",
        "extends", "false", "finally", "for", "function", "if", "import", "in", "instanceof", "new", "null", "return", "super",
        "switch", "this", "throw", "true", "try", "typeof", "var", "void", "while", "with", "yield", "let", "static",
        "implements", "interface", "package", "private", "protected", "public", "await",
    ];
    let add = |names: &mut Vec<String>, s: String| {
        if s != "__esModule" && !RESERVED.contains(&s.as_str()) && !names.contains(&s) {
            names.push(s);
        }
    };
    let is_start = |c: char| c.is_ascii_alphabetic() || c == '_' || c == '$';
    let is_part = |c: char| c.is_ascii_alphanumeric() || c == '_' || c == '$';
    let at = |i: usize, w: &str| -> bool {
        let wc: Vec<char> = w.chars().collect();
        i + wc.len() <= n && cs[i..i + wc.len()] == wc[..]
    };
    let ident_at = |i: usize| -> Option<(String, usize)> {
        if i < n && is_start(cs[i]) {
            let mut j = i;
            while j < n && is_part(cs[j]) {
                j += 1;
            }
            Some((cs[i..j].iter().collect(), j))
        } else {
            None
        }
    };
    let mut i = 0;
    while i < n {
        if at(i, "exports.") {
            if let Some((name, mut j)) = ident_at(i + 8) {
                while j < n && (cs[j] == ' ' || cs[j] == '\t') {
                    j += 1;
                }
                if j < n && cs[j] == '=' {
                    add(&mut names, name);
                }
            }
            i += 8;
            continue;
        }
        if at(i, "Object.defineProperty(") {
            let mut j = i + 22;
            while j < n && cs[j].is_whitespace() {
                j += 1;
            }
            if at(j, "module.") {
                j += 7;
            }
            if at(j, "exports") {
                j += 7;
                while j < n && cs[j].is_whitespace() {
                    j += 1;
                }
                if j < n && cs[j] == ',' {
                    j += 1;
                    while j < n && cs[j].is_whitespace() {
                        j += 1;
                    }
                    if j < n && (cs[j] == '"' || cs[j] == '\'') {
                        let q = cs[j];
                        let start = j + 1;
                        let mut k = start;
                        while k < n && cs[k] != q && cs[k] != '\n' {
                            k += 1;
                        }
                        if k < n && cs[k] == q {
                            add(&mut names, cs[start..k].iter().collect());
                        }
                    }
                }
            }
            i += 22;
            continue;
        }
        if at(i, "module.exports") {
            let mut j = i + 14;
            while j < n && cs[j].is_whitespace() {
                j += 1;
            }
            if j < n && cs[j] == '=' && !(j + 1 < n && cs[j + 1] == '=') {
                j += 1;
                while j < n && cs[j].is_whitespace() {
                    j += 1;
                }
                if j < n && cs[j] == '{' {
                    for entry in object_literal_entries(&cs, j) {
                        if let Some(name) = entry_key(&entry) {
                            add(&mut names, name);
                        }
                    }
                }
            }
            // `module.exports.X =` is found at its `exports.`
            i += 7;
            continue;
        }
        i += 1;
    }
    names
}

/// Top-level entries of the object literal starting at `open` (split at commas outside
/// brackets, strings, templates and regex literals; comments are not special).
fn object_literal_entries(cs: &[char], open: usize) -> Vec<String> {
    let n = cs.len();
    let mut entries = Vec::new();
    let mut cur = String::new();
    let mut depth = 0usize;
    let mut i = open + 1;
    let mut prev_sig = '{';
    while i < n {
        let c = cs[i];
        match c {
            '"' | '\'' | '`' => {
                let q = c;
                cur.push(c);
                i += 1;
                while i < n && cs[i] != q {
                    if cs[i] == '\\' && i + 1 < n {
                        cur.push(cs[i]);
                        i += 1;
                    }
                    cur.push(cs[i]);
                    i += 1;
                }
                if i < n {
                    cur.push(cs[i]);
                }
                prev_sig = q;
                i += 1;
                continue;
            }
            '/' if !matches!(cs.get(i + 1), Some('*') | Some('/')) && matches!(prev_sig, ':' | ',' | '(' | '[' | '{' | '=' | '!' | '&' | '|' | '?') => {
                // regular expression literal
                cur.push(c);
                i += 1;
                let mut in_class = false;
                while i < n && cs[i] != '\n' {
                    let d = cs[i];
                    cur.push(d);
                    i += 1;
                    if d == '\\' && i < n {
                        cur.push(cs[i]);
                        i += 1;
                    } else if d == '[' {
                        in_class = true;
                    } else if d == ']' {
                        in_class = false;
                    } else if d == '/' && !in_class {
                        break;
                    }
                }
                prev_sig = '/';
                continue;
            }
            '{' | '[' | '(' => depth += 1,
            '}' | ']' | ')' => {
                if depth == 0 {
                    entries.push(std::mem::take(&mut cur));
                    return entries;
                }
                depth -= 1;
            }
            ',' if depth == 0 => {
                entries.push(std::mem::take(&mut cur));
                prev_sig = ',';
                i += 1;
                continue;
            }
            _ => {}
        }
        cur.push(c);
        if !c.is_whitespace() {
            prev_sig = c;
        }
        i += 1;
    }
    entries
}

/// Exported name of one object literal entry: its leading identifier (after whitespace,
/// comment openers and a spread's `...`), or a quoted key that is a whole identifier.
fn entry_key(entry: &str) -> Option<String> {
    let t = entry.trim_start_matches(|c: char| c.is_whitespace() || c == '/' || c == '*' || c == '.');
    let mut chars = t.chars();
    let first = chars.next()?;
    if first == '"' || first == '\'' {
        let rest: String = chars.collect();
        let end = rest.find(first)?;
        let key = &rest[..end];
        let mut kc = key.chars();
        let ok = kc.next().map_or(false, |c| c.is_ascii_alphabetic() || c == '_' || c == '$') && kc.all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '$');
        return if ok { Some(key.to_string()) } else { None };
    }
    if !(first.is_ascii_alphabetic() || first == '_' || first == '$') {
        return None;
    }
    Some(t.chars().take_while(|c| c.is_ascii_alphanumeric() || *c == '_' || *c == '$').collect())
}
