// The runtime: host state, event loop, CLI entry.

pub mod buffer;
pub mod child_process;
pub mod fetch;
pub mod http;
pub mod jsx;
pub mod typescript;
pub mod net;
pub mod nodestream;
pub mod readline;
pub mod streams;
pub mod vmmod;
pub mod console;
pub mod encoding;
pub mod events;
pub mod fs;
pub mod node;
pub mod path;
pub mod process;
pub mod timers;
pub mod util;
pub mod web;
pub mod zlib;
pub mod cryptomod;

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::collections::{HashMap, VecDeque};
use std::io::Write;
use std::time::Instant;

pub struct Timer {
    pub id: u64,
    pub due: f64,
    pub interval: Option<f64>,
    pub callback: Value,
    pub args: Vec<Value>,
    pub seq: u64,
}

pub enum Completion {
    /// call a JS callback with args
    Call(Value, Vec<Value>),
    /// native continuation
    Native(Box<dyn FnOnce(&mut Vm)>),
}

pub type OpResult = Box<dyn std::any::Any + Send>;
pub type OpThen = Box<dyn FnOnce(&mut Vm, OpResult)>;

pub struct Host {
    pub timers: Vec<Timer>,
    pub next_timer_id: u64,
    pub timer_seq: u64,
    pub callbacks: VecDeque<(Value, Vec<Value>)>,
    pub kept_alive: Vec<Value>,
    pub out: Vec<u8>,
    pub start: Instant,
    pub argv: Vec<String>,
    pub exec_path: String,
    pub builtin_cache: HashMap<String, Value>,
    pub cjs_cache: HashMap<String, Obj>,
    pub esm_cache: HashMap<String, std::rc::Rc<crate::modules::ModuleRecord>>,
    pub main_module: Option<Obj>,
    pub process_obj: Option<Obj>,
    pub pending_ops: usize,
    pub completions_tx: std::sync::mpsc::Sender<(u64, OpResult)>,
    pub completions_rx: std::sync::mpsc::Receiver<(u64, OpResult)>,
    pub op_thens: HashMap<u64, OpThen>,
    pub next_op_id: u64,
    pub listeners: HashMap<String, Vec<Value>>,
    pub console_counts: HashMap<String, u64>,
    pub console_timers: HashMap<String, Instant>,
    pub group_indent: usize,
    pub repl: bool,
    pub main_esm_path: String,
}

impl Host {
    pub fn new() -> Host {
        let (tx, rx) = std::sync::mpsc::channel();
        Host {
            timers: Vec::new(),
            next_timer_id: 1,
            timer_seq: 0,
            callbacks: VecDeque::new(),
            kept_alive: Vec::new(),
            out: Vec::new(),
            start: Instant::now(),
            argv: Vec::new(),
            exec_path: String::new(),
            builtin_cache: HashMap::new(),
            cjs_cache: HashMap::new(),
            esm_cache: HashMap::new(),
            main_module: None,
            process_obj: None,
            pending_ops: 0,
            completions_tx: tx,
            completions_rx: rx,
            op_thens: HashMap::new(),
            next_op_id: 1,
            listeners: HashMap::new(),
            console_counts: HashMap::new(),
            console_timers: HashMap::new(),
            group_indent: 0,
            repl: false,
            main_esm_path: String::new(),
        }
    }

    pub fn now_ms(&self) -> f64 {
        self.start.elapsed().as_secs_f64() * 1000.0
    }
}

// ---------------- output ----------------

pub fn write_stdout(vm: &mut Vm, s: &str) {
    let _ = vm;
    let out = std::io::stdout();
    let mut l = out.lock();
    let _ = l.write_all(s.as_bytes());
    let _ = l.flush();
}

pub fn write_stdout_bytes(b: &[u8]) {
    let out = std::io::stdout();
    let mut l = out.lock();
    let _ = l.write_all(b);
    let _ = l.flush();
}

pub fn write_stderr(s: &str) {
    let err = std::io::stderr();
    let mut l = err.lock();
    let _ = l.write_all(s.as_bytes());
    let _ = l.flush();
}

/// String conversion used by console.log and uncaught-rejection reports.
pub fn display_value(vm: &mut Vm, v: &Value) -> String {
    match v {
        Value::Str(s) => s.to_rust_string(),
        Value::Sym(s) => s.descriptive_string(),
        Value::Num(n) => crate::numconv::number_to_string(*n),
        Value::Obj(_) => match vm.to_string(v) {
            Ok(s) => s.to_rust_string(),
            Err(_) => "[object]".to_string(),
        },
        other => match vm.to_string(other) {
            Ok(s) => s.to_rust_string(),
            Err(_) => "[object]".to_string(),
        },
    }
}

/// "Name: message" description of a thrown value for "Uncaught ..." reports.
pub fn describe_thrown(vm: &mut Vm, e: &Value) -> String {
    match e {
        Value::Undefined | Value::Empty => "undefined".into(),
        Value::Null => "null".into(),
        Value::Num(n) => format!("Number: {}", crate::numconv::number_to_string(*n)),
        Value::Str(s) => format!("String: {}", s),
        Value::Bool(b) => format!("Boolean: {}", b),
        Value::BigInt(b) => format!("BigInt: {}", b.to_string_radix(10)),
        Value::Sym(_) => "Symbol: ".into(),
        Value::Obj(o) => {
            let name = match vm.get(o, &vm.intr.key_name.clone(), e) {
                Ok(Value::Undefined) | Err(_) => {
                    // constructor name
                    match vm.get(o, &vm.intr.key_constructor.clone(), e) {
                        Ok(Value::Obj(c)) => match vm.get(&c, &vm.intr.key_name.clone(), &Value::Obj(c.clone())) {
                            Ok(Value::Str(s)) => s.to_rust_string(),
                            _ => String::new(),
                        },
                        _ => String::new(),
                    }
                }
                Ok(v) => display_value(vm, &v),
            };
            let msg = match vm.get(o, &vm.intr.key_message.clone(), e) {
                Ok(Value::Undefined) | Err(_) => String::new(),
                Ok(v) => display_value(vm, &v),
            };
            if name.is_empty() {
                msg
            } else {
                format!("{}: {}", name, msg)
            }
        }
    }
}

/// Description of a thrown value used by "Uncaught ..." / "Uncaught (in promise) ..." reports
/// (file scripts, timers, jobs): objects with a `name` print as "name: message" (or just
/// "name" when the message is empty); everything else prints via ToString.
pub fn format_thrown(vm: &mut Vm, e: &Value) -> String {
    match e {
        Value::Obj(o) => {
            let name = vm.get(o, &vm.intr.key_name.clone(), e);
            match name {
                Ok(n) if !n.is_undefined() => {
                    let ns = match vm.to_string(&n) {
                        Ok(s) => s.to_rust_string(),
                        Err(_) => "[object]".to_string(),
                    };
                    let msg = match vm.get(o, &vm.intr.key_message.clone(), e) {
                        Ok(m) if !m.is_undefined() => vm.to_string(&m).map(|s| s.to_rust_string()).unwrap_or_default(),
                        _ => String::new(),
                    };
                    if msg.is_empty() {
                        ns
                    } else {
                        format!("{}: {}", ns, msg)
                    }
                }
                _ => match vm.to_string(e) {
                    Ok(s) => s.to_rust_string(),
                    Err(_) => "[object]".to_string(),
                },
            }
        }
        Value::Sym(s) => s.descriptive_string(),
        Value::Empty => "undefined".to_string(),
        other => match vm.to_string(other) {
            Ok(s) => s.to_rust_string(),
            Err(_) => "[object]".to_string(),
        },
    }
}

pub fn report_uncaught(vm: &mut Vm, e: &Value) {
    let s = format_thrown(vm, e);
    write_stderr(&format!("Uncaught {}\n", s));
}

/// Report for an exception escaping a `-e` / stdin script (uses the "Type: message" form).
pub fn report_uncaught_script(vm: &mut Vm, e: &Value) {
    let s = describe_thrown(vm, e);
    write_stderr(&format!("Uncaught {}\n", s));
}

pub fn report_unhandled_rejections(vm: &mut Vm) {
    let list = std::mem::take(&mut vm.unhandled);
    for p in list.into_iter().flatten() {
        let (handled, reason) = match &p.borrow().kind {
            ObjKind::Promise(pd) => (
                pd.is_handled,
                match &pd.state {
                    PromiseState::Rejected(r) => Some(r.clone()),
                    _ => None,
                },
            ),
            _ => (true, None),
        };
        if handled {
            continue;
        }
        if let Some(r) = reason {
            // mark as handled so it is reported once
            if let ObjKind::Promise(pd) = &mut p.borrow_mut().kind {
                pd.is_handled = true;
            }
            let s = format_thrown(vm, &r);
            write_stderr(&format!("Uncaught (in promise) {}\n", s));
        }
    }
}

/// Drain microtasks then report unhandled rejections (a "microtask checkpoint").
pub fn checkpoint(vm: &mut Vm) {
    vm.run_microtasks();
    report_unhandled_rejections(vm);
    vm.host.kept_alive.clear();
}

// ---------------- event loop ----------------

pub fn run_event_loop(vm: &mut Vm) {
    checkpoint(vm);
    loop {
        // 1. queued callbacks (setImmediate / nextTick), snapshot
        let n = vm.host.callbacks.len();
        for _ in 0..n {
            if let Some((f, args)) = vm.host.callbacks.pop_front() {
                if let Err(e) = vm.call(&f, Value::Undefined, &args) {
                    report_uncaught(vm, &e);
                }
                checkpoint(vm);
            }
        }
        // 2. completions from background work
        loop {
            match vm.host.completions_rx.try_recv() {
                Ok((id, payload)) => {
                    finish_op(vm, id, payload);
                    checkpoint(vm);
                }
                Err(_) => break,
            }
        }
        // 3. due timers
        let now = vm.host.now_ms();
        let mut due: Vec<(f64, u64, u64)> = vm.host.timers.iter().filter(|t| t.due <= now).map(|t| (t.due, t.seq, t.id)).collect();
        due.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap().then(a.1.cmp(&b.1)));
        for (_, _, id) in due {
            let pos = match vm.host.timers.iter().position(|t| t.id == id) {
                Some(p) => p,
                None => continue,
            };
            let (cb, args, interval) = {
                let t = &vm.host.timers[pos];
                (t.callback.clone(), t.args.clone(), t.interval)
            };
            match interval {
                Some(iv) => {
                    let now2 = vm.host.now_ms();
                    vm.host.timer_seq += 1;
                    let seq = vm.host.timer_seq;
                    let t = &mut vm.host.timers[pos];
                    t.due = now2 + iv;
                    t.seq = seq;
                }
                None => {
                    vm.host.timers.remove(pos);
                }
            }
            if let Err(e) = vm.call(&cb, Value::Undefined, &args) {
                report_uncaught(vm, &e);
            }
            checkpoint(vm);
        }
        // anything left?
        if !vm.host.callbacks.is_empty() {
            continue;
        }
        if vm.host.timers.is_empty() && vm.host.pending_ops == 0 {
            break;
        }
        // wait for the next timer or a completion
        let next_due = vm.host.timers.iter().map(|t| t.due).fold(f64::INFINITY, f64::min);
        let now = vm.host.now_ms();
        if vm.host.pending_ops > 0 {
            let wait = if next_due.is_finite() { (next_due - now).max(0.0) } else { 3600_000.0 };
            match vm.host.completions_rx.recv_timeout(std::time::Duration::from_micros((wait * 1000.0) as u64)) {
                Ok((id, payload)) => {
                    finish_op(vm, id, payload);
                    checkpoint(vm);
                }
                Err(_) => {}
            }
        } else if next_due.is_finite() && next_due > now {
            std::thread::sleep(std::time::Duration::from_micros(((next_due - now) * 1000.0) as u64));
        }
    }
}

pub fn run_completion(vm: &mut Vm, c: Completion) {
    match c {
        Completion::Call(f, args) => {
            if let Err(e) = vm.call(&f, Value::Undefined, &args) {
                report_uncaught(vm, &e);
            }
        }
        Completion::Native(f) => f(vm),
    }
}

fn finish_op(vm: &mut Vm, id: u64, payload: OpResult) {
    vm.host.pending_ops = vm.host.pending_ops.saturating_sub(1);
    if let Some(then) = vm.host.op_thens.remove(&id) {
        then(vm, payload);
    }
}

/// Run `work` on a background thread; `then` runs on the loop thread with its result.
pub fn spawn_op<T: Send + 'static>(vm: &mut Vm, work: impl FnOnce() -> T + Send + 'static, then: impl FnOnce(&mut Vm, T) + 'static) {
    let id = vm.host.next_op_id;
    vm.host.next_op_id += 1;
    vm.host.pending_ops += 1;
    vm.host.op_thens.insert(
        id,
        Box::new(move |vm: &mut Vm, payload: OpResult| {
            if let Ok(v) = payload.downcast::<T>() {
                then(vm, *v);
            }
        }),
    );
    let tx = vm.host.completions_tx.clone();
    std::thread::spawn(move || {
        let r = work();
        let _ = tx.send((id, Box::new(r) as OpResult));
    });
}

// ---------------- runtime setup ----------------

pub fn setup_runtime(vm: &mut Vm, argv: Vec<String>) {
    vm.host.argv = argv.clone();
    vm.host.exec_path = argv.first().cloned().unwrap_or_default();
    console::setup(vm);
    timers::setup(vm);
    process::setup(vm);
    web::setup(vm);
    streams::setup(vm);
    fetch::setup(vm);
    cryptomod::setup(vm);
    buffer::setup_global(vm);
    nodestream::setup(vm);
    node::setup_globals(vm);
    let print = vm.native_fn("print", 1, print_fn);
    vm.def_global("print", Value::Obj(print));
    // core: global property order of the reference engine
    crate::builtins::order::apply_global_order(vm);
}

fn print_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let parts: Vec<String> = a.args.iter().map(|v| display_value(vm, v)).collect();
    write_stdout(vm, &format!("{}\n", parts.join(" ")));
    Ok(Value::Undefined)
}

pub use jsx::jsx_transform;
pub use typescript::strip_types;

fn noop_fn(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Undefined)
}

/// Make `obj` have exactly-ordered enumerable keys `names` (missing ones become no-op functions),
/// followed by any other keys.
pub fn reorder_enum(vm: &mut Vm, obj: &Obj, names: &[&str]) {
    for n in names {
        let k = PropKey::from_str(n);
        let existing = obj.borrow_mut().props.remove(&k);
        let prop = match existing {
            Some(Prop::Data { value, .. }) => Prop::Data { value, flags: WEC },
            Some(Prop::Accessor { get, set, .. }) => Prop::Accessor { get, set, flags: ENUMERABLE | CONFIGURABLE },
            None => Prop::Data { value: Value::Obj(vm.native_fn(n, 0, noop_fn)), flags: WEC },
        };
        obj.borrow_mut().props.insert(k, prop);
    }
}

pub const PROCESS_KEYS: &[&str] = &[
    "cwd", "exit", "nextTick", "stdout", "stderr", "hrtime", "uptime", "version", "versions", "chdir", "abort", "umask", "ppid", "execve", "getuid",
    "geteuid", "getgid", "getegid", "setuid", "seteuid", "setgid", "setegid", "getgroups", "setgroups", "initgroups", "kill", "on", "off", "once",
    "emit", "addListener", "removeListener", "removeAllListeners", "prependListener", "prependOnceListener", "listeners", "rawListeners",
    "listenerCount", "eventNames", "setMaxListeners", "getMaxListeners", "_events", "_eventsCount", "_maxListeners", "execArgv", "exitCode",
    "debugPort", "domain", "moduleLoadList", "config", "sourceMapsEnabled", "allowedNodeEnvironmentFlags", "reallyExit", "emitWarning",
    "getBuiltinModule", "loadEnvFile", "dlopen", "setSourceMapsEnabled", "memoryUsage", "availableMemory", "constrainedMemory", "cpuUsage",
    "resourceUsage", "getActiveResourcesInfo", "features", "release", "report", "permission", "finalization", "binding", "_linkedBinding",
    "setUncaughtExceptionCaptureCallback", "hasUncaughtExceptionCaptureCallback", "assert", "ref", "unref", "stdin", "openStdin", "send",
    "connected", "disconnect", "_getActiveHandles", "_getActiveRequests", "_rawDebug", "_tickCallback", "_fatalException", "_exiting", "_kill",
    "_eval", "_print_eval", "_preload_modules", "_debugProcess", "_debugEnd", "_startProfilerIdleNotifier", "_stopProfilerIdleNotifier", "argv",
    "argv0", "execPath", "title", "env", "platform", "pid", "arch",
];

pub const UTIL_KEYS: &[&str] = &[
    "inherits", "inspect", "format", "formatWithOptions", "deprecate", "promisify", "callbackify", "types", "isArray", "isDate", "isRegExp",
    "isError", "isFunction", "isString", "isNumber", "isBoolean", "isNull", "isNullOrUndefined", "isUndefined", "isObject", "isPrimitive",
    "isBuffer", "isSymbol", "_extend", "isDeepStrictEqual", "log", "debuglog", "debug", "parseArgs", "parseEnv", "styleText",
    "stripVTControlCharacters", "toUSVString", "diff", "getSystemErrorName", "getSystemErrorMessage", "getSystemErrorMap", "aborted",
    "transferableAbortController", "transferableAbortSignal", "getCallSite", "getCallSites", "_errnoException", "_exceptionWithHostPort",
    "MIMEType", "MIMEParams", "TextEncoder", "TextDecoder",
];
