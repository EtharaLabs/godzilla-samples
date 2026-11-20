// node:child_process — spawn / exec / execFile / fork (async, ChildProcess EventEmitter with
// stdio streams) and spawnSync / execSync / execFileSync, modelled on the reference runtime:
//
// * a child's stdout/stderr are read continuously by reader threads; chunks and EOFs reach the
//   event loop in the child's write order;
// * children are reaped by polling (try_wait) whenever child I/O is delivered and on a 20 ms
//   idle tick, so 'exit' normally follows the stdio data and simultaneous exits are reported in
//   spawn order; 'exit' is emitted from a promise reaction, 'close' one microtask later; the
//   signal argument is always null and kill() always SIGKILLs;
// * the sync APIs capture stdout/stderr (stdin is /dev/null unless `input` is given);
// * fork() talks to the child over its stdin/stdout with "\x1eLUMEN_IPC <json>\n" frames; a
//   process started with LUMEN_FORK_IPC=1 gets process.send / process.disconnect /
//   process.connected and 'message' events (see `setup`).

use crate::object::*;
use crate::runtime::nodestream::{buffer_call, call_method, closure, emit, getp, host_obj, key, new_buffer, plain_fn, queue_microtask, setp, string_of, with_host};
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::cell::{Cell, RefCell};
use std::collections::BTreeMap;
use std::io::{Read, Write};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Condvar, Mutex};

const IPC_PREFIX: &str = "\u{1e}LUMEN_IPC ";

/// The reaper's polling interval.
const REAP_TICK_MS: u64 = 20;

/// How long an exited child may wait for its stdio EOFs before the exit is reported anyway.
const REAP_GRACE_MS: u64 = 10;

extern "C" {
    fn kill(pid: i32, sig: i32) -> i32;
}

// ============================================================================================
// native child registry
// ============================================================================================

enum Ev {
    Data(u8, Vec<u8>),
    Eof(u8),
    Exit(Option<i32>),
}

struct ChildEntry {
    pid: u32,
    reaped: Arc<AtomicBool>,
    stdin: Option<std::process::ChildStdin>,
    rx: Option<mpsc::Receiver<Ev>>,
    stdout: Value,
    stderr: Value,
    wait_resolve: Value,
    ipc: Value,
    ipc_buf: Vec<u8>,
    eofs: u8,
    expected_eofs: u8,
    exited: bool,
    /// unref(): the pending event op does not keep the loop alive
    unrefd: bool,
    /// a recv op is in flight (counted in pending_ops unless unref'd)
    in_flight: bool,
    /// stdout / stderr pumps that died (a listener threw)
    dead: [bool; 2],
}

thread_local! {
    static CHILDREN: RefCell<BTreeMap<u64, ChildEntry>> = RefCell::new(BTreeMap::new());
    static NEXT_ID: Cell<u64> = Cell::new(1);
    static CLASS: RefCell<Option<(Obj, Obj)>> = RefCell::new(None);
}

fn with_child<R>(id: u64, f: impl FnOnce(&mut ChildEntry) -> R) -> Option<R> {
    CHILDREN.with(|c| c.borrow_mut().get_mut(&id).map(f))
}

#[derive(Clone, Copy, PartialEq)]
enum Io {
    Pipe,
    Inherit,
    Ignore,
}

fn io_name(io: Io) -> &'static str {
    match io {
        Io::Pipe => "pipe",
        Io::Inherit => "inherit",
        Io::Ignore => "ignore",
    }
}

fn to_stdio(io: Io) -> Stdio {
    match io {
        Io::Pipe => Stdio::piped(),
        Io::Inherit => Stdio::inherit(),
        Io::Ignore => Stdio::null(),
    }
}

fn spawn_error(vm: &mut Vm, cmd: &str, e: &std::io::Error) -> Value {
    vm.make_error("Error", &format!("spawn {}: {}", cmd, e))
}

#[repr(C)]
struct PollFd {
    fd: i32,
    events: i16,
    revents: i16,
}

extern "C" {
    fn poll(fds: *mut PollFd, nfds: std::os::raw::c_ulong, timeout: i32) -> i32;
}

const POLLIN: i16 = 0x001;

/// One reader per child multiplexing its stdout (fd 1) and stderr (fd 2) with poll(2): chunks
/// are sent in the order they become readable; within a wakeup the data goes out before any
/// EOF, and simultaneous EOFs follow the order of the streams' last reads.
fn reader_thread(out: Option<std::process::ChildStdout>, err: Option<std::process::ChildStderr>, tx: mpsc::Sender<Ev>, done: Arc<(Mutex<bool>, Condvar)>) {
    std::thread::spawn(move || {
        reader_loop(out, err, &tx);
        let (m, cv) = &*done;
        if let Ok(mut d) = m.lock() {
            *d = true;
        }
        cv.notify_all();
    });
}

fn reader_loop(out: Option<std::process::ChildStdout>, err: Option<std::process::ChildStderr>, tx: &mpsc::Sender<Ev>) {
    use std::os::unix::io::AsRawFd;
    {
        let mut out = out;
        let mut err = err;
        let mut seq: [u64; 2] = [1, 0];
        let mut counter = 1u64;
        let mut buf = vec![0u8; 65536];
        loop {
            let mut fds: Vec<(u8, PollFd)> = Vec::new();
            if let Some(o) = &out {
                fds.push((1, PollFd { fd: o.as_raw_fd(), events: POLLIN, revents: 0 }));
            }
            if let Some(e) = &err {
                fds.push((2, PollFd { fd: e.as_raw_fd(), events: POLLIN, revents: 0 }));
            }
            if fds.is_empty() {
                break;
            }
            let mut raw: Vec<PollFd> = fds.iter().map(|(_, p)| PollFd { fd: p.fd, events: p.events, revents: 0 }).collect();
            let r = unsafe { poll(raw.as_mut_ptr(), raw.len() as std::os::raw::c_ulong, -1) };
            if r < 0 {
                if std::io::Error::last_os_error().kind() == std::io::ErrorKind::Interrupted {
                    continue;
                }
                // poll unusable: fall back to plain blocking reads, stdout first
                for (which, _) in &fds {
                    loop {
                        let n = if *which == 1 { out.as_mut().map(|s| s.read(&mut buf)) } else { err.as_mut().map(|s| s.read(&mut buf)) };
                        match n {
                            Some(Ok(n)) if n > 0 => {
                                let _ = tx.send(Ev::Data(*which, buf[..n].to_vec()));
                            }
                            Some(Err(e)) if e.kind() == std::io::ErrorKind::Interrupted => continue,
                            _ => break,
                        }
                    }
                    let _ = tx.send(Ev::Eof(*which));
                }
                return;
            }
            let mut eofs: Vec<u8> = Vec::new();
            for (i, (which, _)) in fds.iter().enumerate() {
                if raw[i].revents == 0 {
                    continue;
                }
                let n = if *which == 1 { out.as_mut().map(|s| s.read(&mut buf)) } else { err.as_mut().map(|s| s.read(&mut buf)) };
                match n {
                    Some(Ok(n)) if n > 0 => {
                        counter += 1;
                        seq[(*which - 1) as usize] = counter;
                        if tx.send(Ev::Data(*which, buf[..n].to_vec())).is_err() {
                            return;
                        }
                    }
                    Some(Err(e)) if e.kind() == std::io::ErrorKind::Interrupted => {}
                    _ => eofs.push(*which),
                }
            }
            eofs.sort_by_key(|w| seq[(*w - 1) as usize]);
            for w in eofs {
                if w == 1 {
                    out = None;
                } else {
                    err = None;
                }
                let _ = tx.send(Ev::Eof(w));
            }
        }
    }
}

/// Spawn a child; returns (childId, pid).
fn spawn_native(vm: &mut Vm, cmd: &str, argv: &[String], cwd: Option<String>, env: Option<Vec<(String, String)>>, stdio: [Io; 3]) -> JsResult<(u64, u32)> {
    let mut c = Command::new(cmd);
    c.args(argv);
    if let Some(d) = &cwd {
        c.current_dir(d);
    }
    if let Some(pairs) = &env {
        c.env_clear();
        for (k, v) in pairs {
            c.env(k, v);
        }
    }
    c.stdin(to_stdio(stdio[0]));
    c.stdout(to_stdio(stdio[1]));
    c.stderr(to_stdio(stdio[2]));
    let mut child = match c.spawn() {
        Ok(ch) => ch,
        Err(e) => return Err(spawn_error(vm, cmd, &e)),
    };
    let pid = child.id();
    let (tx, rx) = mpsc::channel::<Ev>();
    let out = child.stdout.take();
    let err = child.stderr.take();
    let readers = out.is_some() as u8 + err.is_some() as u8;
    let readers_done = Arc::new((Mutex::new(readers == 0), Condvar::new()));
    if readers > 0 {
        reader_thread(out, err, tx.clone(), readers_done.clone());
    }
    let stdin = child.stdin.take();
    // the reaper: try_wait right away, then every 20 ms (the reference's exit latency); the exit
    // is reported after the stdio EOFs unless a grandchild keeps the pipes open
    let reaped = Arc::new(AtomicBool::new(false));
    let reaped2 = reaped.clone();
    std::thread::spawn(move || loop {
        let code = match child.try_wait() {
            Ok(Some(status)) => status.code(),
            Ok(None) => {
                std::thread::sleep(std::time::Duration::from_millis(REAP_TICK_MS));
                continue;
            }
            Err(_) => None,
        };
        reaped2.store(true, Ordering::SeqCst);
        let (m, cv) = &*readers_done;
        if let Ok(g) = m.lock() {
            let _ = cv.wait_timeout_while(g, std::time::Duration::from_millis(REAP_GRACE_MS), |done| !*done);
        }
        let _ = tx.send(Ev::Exit(code));
        break;
    });
    let id = NEXT_ID.with(|n| {
        let v = n.get();
        n.set(v + 1);
        v
    });
    CHILDREN.with(|c| {
        c.borrow_mut().insert(
            id,
            ChildEntry {
                pid,
                reaped,
                stdin,
                rx: Some(rx),
                stdout: Value::Undefined,
                stderr: Value::Undefined,
                wait_resolve: Value::Undefined,
                ipc: Value::Undefined,
                ipc_buf: Vec::new(),
                eofs: 0,
                expected_eofs: readers,
                exited: false,
                unrefd: false,
                in_flight: false,
                dead: [false, false],
            },
        )
    });
    recv_next(vm, id);
    Ok((id, pid))
}

/// Pull the next stdio event(s) of child `id` from its channel on a worker thread.
fn recv_next(vm: &mut Vm, id: u64) {
    let rx = match with_child(id, |e| e.rx.take()) {
        Some(Some(r)) => r,
        _ => return,
    };
    crate::runtime::spawn_op(
        vm,
        move || {
            let mut batch = Vec::new();
            if let Ok(ev) = rx.recv() {
                batch.push(ev);
                // everything already produced is delivered in the same turn
                while let Ok(ev) = rx.try_recv() {
                    batch.push(ev);
                }
            }
            (batch, rx)
        },
        move |vm: &mut Vm, (batch, rx): (Vec<Ev>, mpsc::Receiver<Ev>)| {
            let empty = batch.is_empty();
            let unrefd = with_child(id, |e| {
                e.rx = Some(rx);
                e.in_flight = false;
                e.unrefd
            })
            .unwrap_or(false);
            if unrefd {
                // finish_op already took this op off the count it was never part of
                vm.host.pending_ops += 1;
            }
            let n = batch.len();
            for (i, ev) in batch.into_iter().enumerate() {
                handle_event(vm, id, ev);
                if i + 1 < n {
                    crate::runtime::checkpoint(vm);
                }
            }
            let done = empty || with_child(id, |e| e.exited && e.eofs >= e.expected_eofs).unwrap_or(true);
            if done {
                with_child(id, |e| e.rx = None);
            } else {
                recv_next(vm, id);
            }
        },
    );
    let unrefd = with_child(id, |e| {
        e.in_flight = true;
        e.unrefd
    })
    .unwrap_or(false);
    if unrefd {
        vm.host.pending_ops = vm.host.pending_ops.saturating_sub(1);
    }
}

fn set_ref(vm: &mut Vm, id: u64, referenced: bool) {
    let change = with_child(id, |e| {
        if e.unrefd == !referenced {
            return 0i32;
        }
        e.unrefd = !referenced;
        if !e.in_flight {
            0
        } else if referenced {
            1
        } else {
            -1
        }
    })
    .unwrap_or(0);
    if change > 0 {
        vm.host.pending_ops += 1;
    } else if change < 0 {
        vm.host.pending_ops = vm.host.pending_ops.saturating_sub(1);
    }
}

fn report(vm: &mut Vm, r: JsResult<()>) {
    if let Err(e) = r {
        crate::runtime::report_uncaught(vm, &e);
    }
}

/// A stdio pump threw (a listener of the pushed data): like the reference's async pump, the
/// error becomes an unhandled rejection and that stream gets nothing more.
fn pump_failed(vm: &mut Vm, id: u64, fd: u8, r: JsResult<()>) {
    if let Err(e) = r {
        with_child(id, |c| c.dead[(fd - 1) as usize] = true);
        crate::runtime::nodestream::rejected(vm, e);
    }
}

fn handle_event(vm: &mut Vm, id: u64, ev: Ev) {
    match ev {
        Ev::Data(fd, bytes) => {
            let (stream, ipc, dead) = with_child(id, |e| (if fd == 1 { e.stdout.clone() } else { e.stderr.clone() }, e.ipc.clone(), e.dead[(fd - 1) as usize]))
                .unwrap_or((Value::Undefined, Value::Undefined, true));
            if dead {
                return;
            }
            if fd == 1 && ipc.is_callable() {
                let r = ipc_data(vm, id, &stream, &ipc, bytes);
                pump_failed(vm, id, fd, r);
                return;
            }
            if stream.is_object() {
                let r = new_buffer(vm, bytes).and_then(|b| call_method(vm, &stream, "push", &[b]).map(|_| ()));
                pump_failed(vm, id, fd, r);
            }
        }
        Ev::Eof(fd) => {
            let (stream, dead) = with_child(id, |e| {
                e.eofs += 1;
                (if fd == 1 { e.stdout.clone() } else { e.stderr.clone() }, e.dead[(fd - 1) as usize])
            })
            .unwrap_or((Value::Undefined, true));
            if stream.is_object() && !dead {
                let r = call_method(vm, &stream, "push", &[Value::Null]).map(|_| ());
                pump_failed(vm, id, fd, r);
            }
        }
        Ev::Exit(code) => {
            let resolve = with_child(id, |e| {
                e.exited = true;
                std::mem::replace(&mut e.wait_resolve, Value::Undefined)
            })
            .unwrap_or(Value::Undefined);
            if resolve.is_callable() {
                let c = match code {
                    Some(c) => Value::Num(c as f64),
                    None => Value::Null,
                };
                let r = vm.call(&resolve, Value::Undefined, &[c]).map(|_| ());
                report(vm, r);
            }
        }
    }
}

/// fork(): split IPC frames out of the child's stdout.
fn ipc_data(vm: &mut Vm, id: u64, stream: &Value, ipc: &Value, bytes: Vec<u8>) -> JsResult<()> {
    let mut buf = with_child(id, |e| std::mem::take(&mut e.ipc_buf)).unwrap_or_default();
    buf.extend_from_slice(&bytes);
    let prefix = IPC_PREFIX.as_bytes();
    let mut plain: Vec<u8> = Vec::new();
    let mut items: Vec<Result<Vec<u8>, String>> = Vec::new(); // Ok(plain bytes) / Err(json)
    let mut start = 0;
    while start < buf.len() {
        let nl = buf[start..].iter().position(|&b| b == b'\n').map(|p| start + p);
        let line_end = match nl {
            Some(p) => p,
            None => {
                let rest = &buf[start..];
                let maybe_frame = rest.starts_with(prefix) || prefix.starts_with(rest);
                if maybe_frame {
                    break;
                }
                plain.extend_from_slice(rest);
                start = buf.len();
                break;
            }
        };
        let line = &buf[start..line_end];
        if line.starts_with(prefix) {
            if !plain.is_empty() {
                items.push(Ok(std::mem::take(&mut plain)));
            }
            items.push(Err(String::from_utf8_lossy(&line[prefix.len()..]).into_owned()));
        } else {
            plain.extend_from_slice(&buf[start..=line_end]);
        }
        start = line_end + 1;
    }
    let rest = buf[start..].to_vec();
    with_child(id, |e| e.ipc_buf = rest);
    if !plain.is_empty() {
        items.push(Ok(plain));
    }
    for it in items {
        match it {
            Ok(b) => {
                if stream.is_object() {
                    let bv = new_buffer(vm, b)?;
                    call_method(vm, stream, "push", &[bv])?;
                }
            }
            Err(json) => {
                let msg = crate::builtins::json::json_parse(vm, &JsStr::from_str(&json))?;
                vm.call(ipc, Value::Undefined, &[msg])?;
            }
        }
    }
    Ok(())
}

// ============================================================================================
// ChildProcess
// ============================================================================================

fn class(vm: &mut Vm) -> (Obj, Obj) {
    if let Some(c) = CLASS.with(|c| c.borrow().clone()) {
        return c;
    }
    let sc = crate::runtime::nodestream::classes(vm);
    let (ctor, proto) = crate::runtime::nodestream::make_class(vm, "ChildProcess", 4, child_ctor, Some((&sc.ee, &sc.ee_proto)));
    vm.def_method(&proto, "kill", 1, cp_kill);
    vm.def_method(&proto, "ref", 0, cp_ref);
    vm.def_method(&proto, "unref", 0, cp_unref);
    vm.def_method(&proto, "send", 4, cp_send);
    vm.def_method(&proto, "disconnect", 0, cp_disconnect);
    CLASS.with(|c| *c.borrow_mut() = Some((ctor.clone(), proto.clone())));
    (ctor, proto)
}

fn id_of(vm: &mut Vm, v: &Value) -> JsResult<Option<u64>> {
    let idv = getp(vm, v, "_id")?;
    Ok(match idv {
        Value::Num(n) if n >= 0.0 => Some(n as u64),
        _ => None,
    })
}

fn noop(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Undefined)
}

/// makeReadable(childId, fd, onIpcMessage)
fn make_readable(vm: &mut Vm) -> JsResult<Value> {
    let sc = crate::runtime::nodestream::classes(vm);
    let read = vm.native_fn("read", 0, noop);
    let opts = Value::Obj(vm.obj_from(vec![("read", Value::Obj(read))]));
    vm.construct(&Value::Obj(sc.readable), &[opts], None)
}

/// makeWritable(childId)
fn make_writable(vm: &mut Vm, id: u64) -> JsResult<Value> {
    let sc = crate::runtime::nodestream::classes(vm);
    let write = vm.native_closure("write", 3, stdin_write, vec![Value::Num(id as f64)]);
    let fin = vm.native_closure("final", 1, stdin_final, vec![Value::Num(id as f64)]);
    let opts = Value::Obj(vm.obj_from(vec![("write", Value::Obj(write)), ("final", Value::Obj(fin))]));
    vm.construct(&Value::Obj(sc.writable), &[opts], None)
}

fn stdin_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let id = a.slot(0).as_num().unwrap_or(-1.0) as u64;
    let (chunk, enc, cb) = (a.arg(0), a.arg(1), a.arg(2));
    let is_buf = crate::runtime::buffer::is_buffer(vm, &chunk);
    let bytes_v = if is_buf {
        chunk
    } else {
        let e = if matches!(enc, Value::Str(_)) { enc } else { Value::str("utf8") };
        buffer_call(vm, "from", &[chunk, e])?
    };
    let bytes = crate::runtime::buffer::bytes_of(vm, &bytes_v)?;
    let stdin = with_child(id, |e| e.stdin.take()).flatten();
    let mut stdin = match stdin {
        Some(s) => s,
        None => {
            let err = vm.make_error("Error", "Broken pipe (os error 32)");
            vm.call(&cb, Value::Undefined, &[err])?;
            return Ok(Value::Undefined);
        }
    };
    crate::runtime::spawn_op(
        vm,
        move || {
            let r = stdin.write_all(&bytes).and_then(|_| stdin.flush());
            (r.map_err(|e| e.to_string()), stdin)
        },
        move |vm: &mut Vm, (r, stdin): (Result<(), String>, std::process::ChildStdin)| {
            with_child(id, |e| e.stdin = Some(stdin));
            let res = match r {
                Ok(()) => vm.call(&cb, Value::Undefined, &[]),
                Err(msg) => {
                    let err = vm.make_error("Error", &msg);
                    vm.call(&cb, Value::Undefined, &[err])
                }
            };
            if let Err(e) = res {
                crate::runtime::report_uncaught(vm, &e);
            }
        },
    );
    Ok(Value::Undefined)
}

fn stdin_final(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let id = a.slot(0).as_num().unwrap_or(-1.0) as u64;
    with_child(id, |e| e.stdin = None);
    vm.call(&a.arg(0), Value::Undefined, &[])?;
    Ok(Value::Undefined)
}

fn child_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (_, proto) = class(vm);
    let o = crate::runtime::nodestream::new_instance(vm, a, &proto)?;
    child_init(vm, &o, a.arg(0), a.arg(1), a.arg(2), a.arg(3))?;
    Ok(Value::Obj(o))
}

fn stdio_is_pipe(vm: &mut Vm, stdio: &Value, i: u32) -> JsResult<bool> {
    let v = vm.get_prop_of(stdio, &PropKey::from_index(i))?;
    Ok(matches!(&v, Value::Str(s) if s.eq_str("pipe")))
}

fn child_init(vm: &mut Vm, o: &Obj, id: Value, pid: Value, stdio: Value, on_ipc: Value) -> JsResult<()> {
    crate::runtime::events::init_emitter(vm, o);
    let this = Value::Obj(o.clone());
    let nid = match &id {
        Value::Num(n) => Some(*n as u64),
        _ => None,
    };
    setp(vm, &this, "_id", id.clone())?;
    setp(vm, &this, "pid", pid)?;
    setp(vm, &this, "killed", Value::Bool(false))?;
    setp(vm, &this, "exitCode", Value::Null)?;
    setp(vm, &this, "signalCode", Value::Null)?;
    let stdin = if stdio_is_pipe(vm, &stdio, 0)? { make_writable(vm, nid.unwrap_or(u64::MAX))? } else { Value::Null };
    setp(vm, &this, "stdin", stdin.clone())?;
    let stdout = if stdio_is_pipe(vm, &stdio, 1)? { make_readable(vm)? } else { Value::Null };
    setp(vm, &this, "stdout", stdout.clone())?;
    let stderr = if stdio_is_pipe(vm, &stdio, 2)? { make_readable(vm)? } else { Value::Null };
    setp(vm, &this, "stderr", stderr.clone())?;
    let arr = Value::Obj(vm.new_array(vec![stdin, stdout.clone(), stderr.clone()]));
    setp(vm, &this, "stdio", arr)?;
    setp(vm, &this, "connected", Value::Bool(on_ipc.is_callable()))?;
    let spawn_job = closure(vm, "", 0, emit_spawn, vec![this.clone()]);
    queue_microtask(vm, spawn_job);
    // new Promise((resolve, reject) => __child.wait(childId, resolve, reject)).then(onExit, onError)
    let cap = vm.new_promise_capability_intrinsic();
    if let Some(n) = nid {
        with_child(n, |e| {
            e.stdout = stdout;
            e.stderr = stderr;
            e.wait_resolve = cap.resolve.clone();
            e.ipc = on_ipc;
        });
    }
    let on_exit = closure(vm, "", 1, child_on_exit, vec![this.clone()]);
    let on_err = closure(vm, "", 1, child_on_error, vec![this]);
    if let Value::Obj(p) = &cap.promise {
        crate::builtins::promise::promise_then(vm, p, on_exit, on_err)?;
    }
    Ok(())
}

fn emit_spawn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    emit(vm, &a.slot(0), "spawn", &[])?;
    Ok(Value::Undefined)
}

fn child_on_exit(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.slot(0);
    let code = a.arg(0);
    setp(vm, &this, "exitCode", code.clone())?;
    emit(vm, &this, "exit", &[code.clone(), Value::Null])?;
    let job = closure(vm, "", 0, emit_close, vec![this, code]);
    queue_microtask(vm, job);
    Ok(Value::Undefined)
}

fn emit_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    emit(vm, &a.slot(0), "close", &[a.slot(1), Value::Null])?;
    Ok(Value::Undefined)
}

fn child_on_error(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    emit(vm, &a.slot(0), "error", &[a.arg(0)])?;
    Ok(Value::Undefined)
}

fn cp_kill(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    setp(vm, &this, "killed", Value::Bool(true))?;
    let id = id_of(vm, &this)?;
    // the reference always SIGKILLs (whatever signal is asked for)
    let ok = id
        .and_then(|i| {
            with_child(i, |e| {
                if !e.reaped.load(Ordering::SeqCst) {
                    unsafe {
                        kill(e.pid as i32, 9);
                    }
                }
            })
        })
        .is_some();
    Ok(Value::Bool(ok))
}

fn cp_ref(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let Some(id) = id_of(vm, &a.this)? {
        set_ref(vm, id, true);
    }
    Ok(Value::Undefined)
}

fn cp_unref(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let Some(id) = id_of(vm, &a.this)? {
        set_ref(vm, id, false);
    }
    Ok(Value::Undefined)
}

fn send_err_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    vm.call(&a.slot(0), Value::Undefined, &[a.slot(1)])
}

fn cp_send(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let (message, send_handle, options) = (a.arg(0), a.arg(1), a.arg(2));
    let mut callback = a.arg(3);
    if send_handle.is_callable() {
        callback = send_handle.clone();
    } else if options.is_callable() {
        callback = options;
    }
    if !send_handle.is_nullish() && !send_handle.is_callable() {
        let error = vm.make_error("Error", "child_process.fork handle transfer is not supported in lumen");
        if callback.truthy() {
            let j = closure(vm, "", 0, send_err_job, vec![callback, error]);
            queue_microtask(vm, j);
            return Ok(Value::Bool(false));
        }
        return Err(error);
    }
    let connected = getp(vm, &this, "connected")?.truthy();
    let stdin = getp(vm, &this, "stdin")?;
    if !connected || !stdin.truthy() {
        let error = crate::runtime::nodestream::error_with_code(vm, "Error", "IPC channel is closed", "ERR_IPC_CHANNEL_CLOSED");
        if callback.truthy() {
            let j = closure(vm, "", 0, send_err_job, vec![callback, error]);
            queue_microtask(vm, j);
        } else {
            emit(vm, &this, "error", &[error])?;
        }
        return Ok(Value::Bool(false));
    }
    let m = if message.is_undefined() { Value::Null } else { message };
    let json = match crate::builtins::json::json_stringify(vm, &m, &Value::Undefined, &Value::Undefined) {
        Ok(s) => s.map(|s| s.to_rust_string()).unwrap_or_else(|| "undefined".into()),
        Err(error) => {
            if callback.truthy() {
                let j = closure(vm, "", 0, send_err_job, vec![callback, error]);
                queue_microtask(vm, j);
                return Ok(Value::Bool(false));
            }
            return Err(error);
        }
    };
    let frame = format!("{}{}\n", IPC_PREFIX, json);
    call_method(vm, &stdin, "write", &[Value::str(&frame), callback])?;
    Ok(Value::Bool(true))
}

fn cp_disconnect(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if !getp(vm, &this, "connected")?.truthy() {
        return Ok(Value::Undefined);
    }
    setp(vm, &this, "connected", Value::Bool(false))?;
    let stdin = getp(vm, &this, "stdin")?;
    if stdin.truthy() {
        call_method(vm, &stdin, "end", &[])?;
    }
    let j = closure(vm, "", 0, emit_disconnect, vec![this]);
    queue_microtask(vm, j);
    Ok(Value::Undefined)
}

fn emit_disconnect(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    emit(vm, &a.slot(0), "disconnect", &[])?;
    Ok(Value::Undefined)
}

// ============================================================================================
// argument helpers
// ============================================================================================

fn is_array(v: &Value) -> bool {
    matches!(v, Value::Obj(o) if o.is_array())
}

fn strings_of(vm: &mut Vm, v: &Value) -> JsResult<Vec<String>> {
    if v.is_nullish() || (matches!(v, Value::Bool(false))) {
        return Ok(Vec::new());
    }
    let items = crate::builtins::array::array_like_to_vec(vm, v)?;
    let mut out = Vec::with_capacity(items.len());
    for it in items {
        out.push(string_of(vm, &it)?);
    }
    Ok(out)
}

/// normalizeStdio(options.stdio)
fn normalize_stdio(vm: &mut Vm, s: &Value) -> JsResult<[Io; 3]> {
    let one = |v: &Value| -> Io {
        match v {
            Value::Str(s) if s.eq_str("inherit") => Io::Inherit,
            Value::Str(s) if s.eq_str("ignore") => Io::Ignore,
            _ => Io::Pipe,
        }
    };
    match s {
        Value::Str(_) => {
            let x = one(s);
            Ok([x, x, x])
        }
        v if is_array(v) => {
            let mut out = [Io::Pipe; 3];
            for (i, slot) in out.iter_mut().enumerate() {
                let e = vm.get_prop_of(v, &PropKey::from_index(i as u32))?;
                *slot = one(&e);
            }
            Ok(out)
        }
        _ => Ok([Io::Pipe; 3]),
    }
}

/// envPairs(options.env)
fn env_pairs(vm: &mut Vm, env: &Value) -> JsResult<Option<Vec<(String, String)>>> {
    let o = match env {
        Value::Obj(o) => o.clone(),
        _ => return Ok(None),
    };
    let keys = vm.enumerable_own_keys(&o)?;
    let mut out = Vec::new();
    for k in keys {
        let v = vm.get(&o, &PropKey::Str(k.clone()), env)?;
        out.push((k.to_rust_string(), string_of(vm, &v)?));
    }
    Ok(Some(out))
}

fn opt(vm: &mut Vm, options: &Value, k: &str) -> JsResult<Value> {
    if options.is_object() {
        getp(vm, options, k)
    } else {
        Ok(Value::Undefined)
    }
}

fn cwd_opt(vm: &mut Vm, options: &Value) -> JsResult<Option<String>> {
    let c = opt(vm, options, "cwd")?;
    if c.is_nullish() {
        Ok(None)
    } else {
        Ok(Some(string_of(vm, &c)?))
    }
}

/// `options.shell` → (cmd, argv) rewritten to run through the shell.
fn apply_shell(vm: &mut Vm, options: &Value, cmd: String, argv: Vec<String>) -> JsResult<(String, Vec<String>)> {
    let sh = opt(vm, options, "shell")?;
    if !sh.truthy() {
        return Ok((cmd, argv));
    }
    let shell = match &sh {
        Value::Str(s) => s.to_rust_string(),
        _ => "/bin/sh".to_string(),
    };
    let mut parts = vec![cmd];
    parts.extend(argv);
    Ok((shell, vec!["-c".to_string(), parts.join(" ")]))
}

/// The (args, options) normalisation shared by spawn/spawnSync/execFileSync/fork.
fn split_args(a1: Value, a2: Value) -> (Value, Value) {
    if is_array(&a1) {
        (a1, a2)
    } else {
        (Value::Undefined, a1)
    }
}

fn or_empty(vm: &mut Vm, v: Value) -> Value {
    if v.truthy() {
        v
    } else {
        Value::Obj(vm.new_object())
    }
}

// ============================================================================================
// async API
// ============================================================================================

fn spawn_impl(vm: &mut Vm, command: &Value, args: Value, options: Value) -> JsResult<Value> {
    crate::runtime::nodestream::with_frames(vm, &["spawn"], |vm| spawn_impl_inner(vm, command, args, options))
}

fn spawn_impl_inner(vm: &mut Vm, command: &Value, args: Value, options: Value) -> JsResult<Value> {
    let (args, options) = split_args(args, options);
    let options = or_empty(vm, options);
    let cmd = string_of(vm, command)?;
    let argv = strings_of(vm, &args)?;
    let (cmd, argv) = apply_shell(vm, &options, cmd, argv)?;
    let stdio_v = opt(vm, &options, "stdio")?;
    let stdio = normalize_stdio(vm, &stdio_v)?;
    let cwd = cwd_opt(vm, &options)?;
    let envv = opt(vm, &options, "env")?;
    let env = env_pairs(vm, &envv)?;
    let ipc = opt(vm, &options, "_ipc")?.truthy();
    let (id, pid) = spawn_native(vm, &cmd, &argv, cwd, env, stdio)?;
    let (ctor, proto) = class(vm);
    let _ = ctor;
    let o = Obj::new(Some(proto), ObjKind::Ordinary);
    let names: Vec<Value> = stdio.iter().map(|s| Value::str(io_name(*s))).collect();
    let stdio_arr = Value::Obj(vm.new_array(names));
    let on_ipc = if ipc { closure(vm, "", 1, ipc_message, vec![Value::Obj(o.clone())]) } else { Value::Undefined };
    child_init(vm, &o, Value::Num(id as f64), Value::Num(pid as f64), stdio_arr, on_ipc)?;
    Ok(Value::Obj(o))
}

fn ipc_message(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    emit(vm, &a.slot(0), "message", &[a.arg(0), Value::Null])?;
    Ok(Value::Undefined)
}

fn cp_spawn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    spawn_impl(vm, &a.arg(0), a.arg(1), a.arg(2))
}

struct Collect {
    out: RefCell<Vec<Value>>,
    err: RefCell<Vec<Value>>,
    encoding: Value,
    callback: Value,
}

fn collect_data(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = a.slot(0);
    let which = a.slot(1).truthy();
    let c = a.arg(0);
    let _ = vm;
    with_host::<Collect, ()>(&st, |s| if which { s.err.borrow_mut().push(c) } else { s.out.borrow_mut().push(c) });
    Ok(Value::Undefined)
}

fn collect_decode(vm: &mut Vm, chunks: Vec<Value>, enc: &Value) -> JsResult<Value> {
    let arr = Value::Obj(vm.new_array(chunks));
    let b = buffer_call(vm, "concat", &[arr])?;
    if matches!(enc, Value::Str(s) if s.eq_str("buffer")) {
        return Ok(b);
    }
    call_method(vm, &b, "toString", &[enc.clone()])
}

fn collect_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = a.slot(0);
    let code = a.arg(0);
    let (out, err, enc, cb) = with_host::<Collect, _>(&st, |s| (s.out.borrow().clone(), s.err.borrow().clone(), s.encoding.clone(), s.callback.clone())).unwrap();
    let so = collect_decode(vm, out, &enc)?;
    let se = collect_decode(vm, err, &enc)?;
    let ok = matches!(code, Value::Num(n) if n == 0.0);
    if ok {
        vm.call(&cb, Value::Undefined, &[Value::Null, so, se])?;
    } else {
        let c = crate::runtime::display_value(vm, &code);
        let e = vm.make_error("Error", &format!("Command failed with exit code {}", c));
        setp(vm, &e, "code", code)?;
        vm.call(&cb, Value::Undefined, &[e, so, se])?;
    }
    Ok(Value::Undefined)
}

fn collect_error(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = a.slot(0);
    let cb = with_host::<Collect, _>(&st, |s| s.callback.clone()).unwrap();
    vm.call(&cb, Value::Undefined, &[a.arg(0)])?;
    Ok(Value::Undefined)
}

/// collect(child, encoding, callback)
fn collect(vm: &mut Vm, child: &Value, encoding: Value, callback: Value) -> JsResult<()> {
    let st = host_obj(Collect { out: RefCell::new(Vec::new()), err: RefCell::new(Vec::new()), encoding, callback });
    let stdout = getp(vm, child, "stdout")?;
    if stdout.truthy() {
        let f = closure(vm, "", 1, collect_data, vec![st.clone(), Value::Bool(false)]);
        call_method(vm, &stdout, "on", &[Value::str("data"), f])?;
    }
    let stderr = getp(vm, child, "stderr")?;
    if stderr.truthy() {
        let f = closure(vm, "", 1, collect_data, vec![st.clone(), Value::Bool(true)]);
        call_method(vm, &stderr, "on", &[Value::str("data"), f])?;
    }
    let fe = closure(vm, "", 1, collect_error_f, vec![st.clone()]);
    call_method(vm, child, "on", &[Value::str("error"), fe])?;
    let fc = closure(vm, "", 1, collect_close_f, vec![st]);
    call_method(vm, child, "on", &[Value::str("close"), fc])?;
    Ok(())
}

fn encoding_opt(vm: &mut Vm, options: &Value) -> JsResult<Value> {
    let e = opt(vm, options, "encoding")?;
    Ok(if e.is_nullish() { Value::str("utf8") } else { e })
}

fn cp_exec(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let command = a.arg(0);
    let (mut options, mut callback) = (a.arg(1), a.arg(2));
    if options.is_callable() {
        callback = options;
        options = Value::Obj(vm.new_object());
    }
    let options = or_empty(vm, options);
    // { ...options, shell: options.shell || "/bin/sh" }
    let copy = vm.new_object();
    copy_props(vm, &options, &copy)?;
    let sh = getp(vm, &options, "shell")?;
    copy.set_prop(key("shell"), if sh.truthy() { sh } else { Value::str("/bin/sh") }, WEC);
    let child = spawn_impl(vm, &command, Value::Obj(copy), Value::Undefined)?;
    if callback.truthy() {
        let enc = encoding_opt(vm, &options)?;
        collect(vm, &child, enc, callback)?;
    }
    Ok(child)
}

fn cp_exec_file(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let file = a.arg(0);
    let (mut args, mut options, mut callback) = (a.arg(1), a.arg(2), a.arg(3));
    if args.is_callable() {
        callback = args;
        args = Value::Obj(vm.new_array(Vec::new()));
        options = Value::Obj(vm.new_object());
    } else if options.is_callable() {
        callback = options;
        options = Value::Obj(vm.new_object());
    }
    let args = if args.truthy() { args } else { Value::Obj(vm.new_array(Vec::new())) };
    let opts2 = or_empty(vm, options.clone());
    let child = spawn_impl(vm, &file, args, opts2)?;
    if callback.truthy() {
        let enc = if options.truthy() { encoding_opt(vm, &options)? } else { Value::str("utf8") };
        collect(vm, &child, enc, callback)?;
    }
    Ok(child)
}

fn cp_fork(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let module_path = a.arg(0);
    let (args, options) = split_args(a.arg(1), a.arg(2));
    let options = or_empty(vm, options);
    // env = { ...process.env, ...(options.env || {}), LUMEN_FORK_IPC: "1" }
    let env = vm.new_object();
    if let Some(p) = vm.host.process_obj.clone() {
        let pe = vm.get_str(&p, "env")?;
        copy_props(vm, &pe, &env)?;
    }
    let oe = getp(vm, &options, "env")?;
    if oe.truthy() {
        copy_props(vm, &oe, &env)?;
    }
    env.set_prop(key("LUMEN_FORK_IPC"), Value::str("1"), WEC);
    let mut argv = vec![Value::str(&string_of(vm, &module_path)?)];
    for s in strings_of(vm, &args)? {
        argv.push(Value::str(&s));
    }
    let silent = getp(vm, &options, "silent")?.truthy();
    let stdio = vm.new_array(vec![Value::str("pipe"), Value::str("pipe"), Value::str(if silent { "pipe" } else { "inherit" })]);
    let o2 = vm.new_object();
    copy_props(vm, &options, &o2)?;
    o2.set_prop(key("env"), Value::Obj(env), WEC);
    o2.set_prop(key("stdio"), Value::Obj(stdio), WEC);
    o2.set_prop(key("_ipc"), Value::Bool(true), WEC);
    let exec_path = match vm.host.process_obj.clone() {
        Some(p) => vm.get_str(&p, "execPath")?,
        None => Value::str(&std::env::current_exe().map(|p| p.to_string_lossy().into_owned()).unwrap_or_default()),
    };
    let argv_arr = Value::Obj(vm.new_array(argv));
    spawn_impl(vm, &exec_path, argv_arr, Value::Obj(o2))
}

fn copy_props(vm: &mut Vm, from: &Value, to: &Obj) -> JsResult<()> {
    if let Value::Obj(src) = from {
        let keys = vm.enumerable_own_keys(src)?;
        for k in keys {
            let pk = PropKey::Str(k);
            let v = vm.get(src, &pk, from)?;
            to.set_prop(pk, v, WEC);
        }
    }
    Ok(())
}

// ============================================================================================
// sync API
// ============================================================================================

struct SyncRes {
    status: Option<i32>,
    stdout: Vec<u8>,
    stderr: Vec<u8>,
}

/// __child.execSync(cmd, argv, input, cwd)
fn exec_sync_native(vm: &mut Vm, cmd: &str, argv: &[String], input: Option<Vec<u8>>, cwd: Option<String>) -> JsResult<SyncRes> {
    let mut c = Command::new(cmd);
    c.args(argv);
    if let Some(d) = &cwd {
        c.current_dir(d);
    }
    c.stdin(if input.is_some() { Stdio::piped() } else { Stdio::null() });
    c.stdout(Stdio::piped());
    c.stderr(Stdio::piped());
    let mut child = match c.spawn() {
        Ok(ch) => ch,
        Err(e) => return Err(spawn_error(vm, cmd, &e)),
    };
    let writer = match (input, child.stdin.take()) {
        (Some(bytes), Some(mut si)) => Some(std::thread::spawn(move || {
            let _ = si.write_all(&bytes);
        })),
        _ => None,
    };
    let out = child.wait_with_output();
    if let Some(w) = writer {
        let _ = w.join();
    }
    match out {
        Ok(o) => Ok(SyncRes { status: o.status.code(), stdout: o.stdout, stderr: o.stderr }),
        Err(e) => Err(spawn_error(vm, cmd, &e)),
    }
}

/// options.input → bytes (Buffer.from for non-Buffers); falsy → none
fn input_opt(vm: &mut Vm, options: &Value) -> JsResult<Option<Vec<u8>>> {
    let i = opt(vm, options, "input")?;
    if !i.truthy() {
        return Ok(None);
    }
    let b = if crate::runtime::buffer::is_buffer(vm, &i) { i } else { buffer_call(vm, "from", &[i])? };
    Ok(Some(crate::runtime::buffer::bytes_of(vm, &b)?))
}

fn sync_encoding(vm: &mut Vm, options: &Value) -> JsResult<Option<Value>> {
    let e = opt(vm, options, "encoding")?;
    if e.truthy() && !matches!(&e, Value::Str(s) if s.eq_str("buffer")) {
        Ok(Some(e))
    } else {
        Ok(None)
    }
}

fn decode_out(vm: &mut Vm, bytes: Vec<u8>, enc: &Option<Value>) -> JsResult<Value> {
    let b = new_buffer(vm, bytes)?;
    match enc {
        Some(e) => call_method(vm, &b, "toString", &[e.clone()]),
        None => Ok(b),
    }
}

fn status_value(s: Option<i32>) -> Value {
    match s {
        Some(c) => Value::Num(c as f64),
        None => Value::Null,
    }
}

fn cp_exec_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let command = a.arg(0);
    let options = or_empty(vm, a.arg(1));
    let input = input_opt(vm, &options)?;
    let cmd_s = string_of(vm, &command)?;
    let cwd = cwd_opt(vm, &options)?;
    let res = exec_sync_native(vm, "/bin/sh", &["-c".to_string(), cmd_s.clone()], input, cwd)?;
    if let Some(st) = res.status {
        if st != 0 {
            let e = vm.make_error("Error", &format!("Command failed: {}", cmd_s));
            setp(vm, &e, "status", Value::Num(st as f64))?;
            let se = new_buffer(vm, res.stderr)?;
            setp(vm, &e, "stderr", se)?;
            return Err(e);
        }
    }
    let enc = sync_encoding(vm, &options)?;
    decode_out(vm, res.stdout, &enc)
}

fn cp_exec_file_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let file = a.arg(0);
    let (args, options) = split_args(a.arg(1), a.arg(2));
    let options = or_empty(vm, options);
    let input = input_opt(vm, &options)?;
    let f = string_of(vm, &file)?;
    let argv = strings_of(vm, &args)?;
    let cwd = cwd_opt(vm, &options)?;
    let res = exec_sync_native(vm, &f, &argv, input, cwd)?;
    if let Some(st) = res.status {
        if st != 0 {
            let e = vm.make_error("Error", &format!("Command failed: {}", f));
            setp(vm, &e, "status", Value::Num(st as f64))?;
            let so = new_buffer(vm, res.stdout)?;
            setp(vm, &e, "stdout", so)?;
            let se = new_buffer(vm, res.stderr)?;
            setp(vm, &e, "stderr", se)?;
            return Err(e);
        }
    }
    let enc = sync_encoding(vm, &options)?;
    decode_out(vm, res.stdout, &enc)
}

fn cp_spawn_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let command = a.arg(0);
    let (args, options) = split_args(a.arg(1), a.arg(2));
    let options = or_empty(vm, options);
    let cmd = string_of(vm, &command)?;
    let argv = strings_of(vm, &args)?;
    let (cmd, argv) = apply_shell(vm, &options, cmd, argv)?;
    let input = input_opt(vm, &options)?;
    let cwd = cwd_opt(vm, &options)?;
    let res = exec_sync_native(vm, &cmd, &argv, input, cwd)?;
    let enc = sync_encoding(vm, &options)?;
    let so = decode_out(vm, res.stdout, &enc)?;
    let se = decode_out(vm, res.stderr, &enc)?;
    let output = Value::Obj(vm.new_array(vec![Value::Null, so.clone(), se.clone()]));
    Ok(Value::Obj(vm.obj_from(vec![
        ("pid", Value::Num(0.0)),
        ("status", status_value(res.status)),
        ("signal", Value::Null),
        ("stdout", so),
        ("stderr", se),
        ("output", output),
    ])))
}

// ============================================================================================
// fork child side (LUMEN_FORK_IPC=1)
// ============================================================================================

struct ForkState {
    started: Cell<bool>,
    connected: Cell<bool>,
    buf: RefCell<Vec<u8>>,
}

thread_local! {
    static FORK: RefCell<Option<Value>> = RefCell::new(None);
}

fn fork_state() -> Option<Value> {
    FORK.with(|f| f.borrow().clone())
}

fn fork_connected() -> bool {
    fork_state().and_then(|s| with_host::<ForkState, bool>(&s, |f| f.connected.get())).unwrap_or(false)
}

fn start_fork_ipc(vm: &mut Vm) {
    let st = match fork_state() {
        Some(s) => s,
        None => return,
    };
    if with_host::<ForkState, bool>(&st, |f| f.started.get()).unwrap_or(true) {
        return;
    }
    with_host::<ForkState, ()>(&st, |f| {
        f.started.set(true);
        f.connected.set(true);
    });
    fork_read(vm);
}

fn fork_read(vm: &mut Vm) {
    crate::runtime::spawn_op(
        vm,
        || {
            let mut buf = vec![0u8; 65536];
            loop {
                match std::io::stdin().read(&mut buf) {
                    Ok(n) => {
                        buf.truncate(n);
                        return buf;
                    }
                    Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
                    Err(_) => return Vec::new(),
                }
            }
        },
        |vm: &mut Vm, bytes: Vec<u8>| {
            let st = match fork_state() {
                Some(s) => s,
                None => return,
            };
            let proc_v = match vm.host.process_obj.clone() {
                Some(p) => Value::Obj(p),
                None => return,
            };
            if bytes.is_empty() {
                let was = with_host::<ForkState, bool>(&st, |f| f.connected.replace(false)).unwrap_or(false);
                if was {
                    let j = closure(vm, "", 0, emit_disconnect, vec![proc_v]);
                    queue_microtask(vm, j);
                }
                return;
            }
            let lines = with_host::<ForkState, Vec<Vec<u8>>>(&st, |f| {
                let mut b = f.buf.borrow_mut();
                b.extend_from_slice(&bytes);
                let mut out = Vec::new();
                while let Some(p) = b.iter().position(|&c| c == b'\n') {
                    let line: Vec<u8> = b.drain(..=p).collect();
                    out.push(line[..line.len() - 1].to_vec());
                }
                out
            })
            .unwrap_or_default();
            let prefix = IPC_PREFIX.as_bytes();
            for line in lines {
                if let Some(json) = line.strip_prefix(prefix) {
                    let s = String::from_utf8_lossy(json).into_owned();
                    let r = crate::builtins::json::json_parse(vm, &JsStr::from_str(&s)).and_then(|m| emit(vm, &proc_v, "message", &[m]).map(|_| ()));
                    if let Err(e) = r {
                        crate::runtime::report_uncaught(vm, &e);
                    }
                }
            }
            fork_read(vm);
        },
    );
}

fn proc_send_getter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    start_fork_ipc(vm);
    let _ = a;
    Ok(Value::Obj(vm.native_fn("", 4, proc_send)))
}

fn proc_send(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (message, send_handle, options) = (a.arg(0), a.arg(1), a.arg(2));
    let mut callback = a.arg(3);
    if send_handle.is_callable() {
        callback = send_handle.clone();
    } else if options.is_callable() {
        callback = options;
    }
    if !send_handle.is_nullish() && !send_handle.is_callable() {
        let error = vm.make_error("Error", "child_process.fork handle transfer is not supported in lumen");
        if callback.truthy() {
            let j = closure(vm, "", 0, send_err_job, vec![callback, error]);
            queue_microtask(vm, j);
            return Ok(Value::Bool(false));
        }
        return Err(error);
    }
    start_fork_ipc(vm);
    if !fork_connected() {
        return Ok(Value::Bool(false));
    }
    let m = if message.is_undefined() { Value::Null } else { message };
    let r: JsResult<()> = (|| {
        let json = crate::builtins::json::json_stringify(vm, &m, &Value::Undefined, &Value::Undefined)?.map(|s| s.to_rust_string()).unwrap_or_else(|| "undefined".into());
        let p = vm.host.process_obj.clone().map(Value::Obj).unwrap_or(Value::Undefined);
        let out = getp(vm, &p, "stdout")?;
        call_method(vm, &out, "write", &[Value::str(&format!("{}{}\n", IPC_PREFIX, json))])?;
        Ok(())
    })();
    match r {
        Ok(()) => {
            if callback.truthy() {
                let j = closure(vm, "", 0, send_err_job, vec![callback, Value::Null]);
                queue_microtask(vm, j);
            }
            Ok(Value::Bool(true))
        }
        Err(error) => {
            if callback.truthy() {
                let j = closure(vm, "", 0, send_err_job, vec![callback, error]);
                queue_microtask(vm, j);
                Ok(Value::Bool(false))
            } else {
                Err(error)
            }
        }
    }
}

fn proc_disconnect(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let st = match fork_state() {
        Some(s) => s,
        None => return Ok(Value::Undefined),
    };
    if !with_host::<ForkState, bool>(&st, |f| f.connected.get()).unwrap_or(false) {
        return Ok(Value::Undefined);
    }
    with_host::<ForkState, ()>(&st, |f| f.connected.set(false));
    if let Some(p) = vm.host.process_obj.clone() {
        let j = closure(vm, "", 0, emit_disconnect, vec![Value::Obj(p)]);
        queue_microtask(vm, j);
    }
    Ok(Value::Undefined)
}

fn proc_connected(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(fork_connected()))
}

fn proc_on(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ev = a.arg(0);
    if matches!(&ev, Value::Str(s) if s.eq_str("message") || s.eq_str("disconnect")) {
        start_fork_ipc(vm);
    }
    let orig = a.slot(0);
    vm.call(&orig, a.this.clone(), a.args)
}

/// Install the forked-child IPC surface on `process` when started by fork().
pub fn setup(vm: &mut Vm) {
    if std::env::var("LUMEN_FORK_IPC").ok().as_deref() != Some("1") {
        return;
    }
    let p = match vm.host.process_obj.clone() {
        Some(p) => p,
        None => return,
    };
    FORK.with(|f| *f.borrow_mut() = Some(host_obj(ForkState { started: Cell::new(false), connected: Cell::new(false), buf: RefCell::new(Vec::new()) })));
    let g = vm.native_fn("get", 0, proc_send_getter);
    p.set_accessor(key("send"), Some(g), None, ENUMERABLE | CONFIGURABLE);
    let c = vm.native_fn("get", 0, proc_connected);
    p.set_accessor(key("connected"), Some(c), None, ENUMERABLE | CONFIGURABLE);
    let d = vm.native_fn("", 0, proc_disconnect);
    p.set_prop(key("disconnect"), Value::Obj(d), WEC);
    for name in ["on", "addListener"] {
        if let Some(orig) = p.get_own_str(name).or_else(|| vm.get_str(&p, name).ok()) {
            let f = vm.native_closure("", 2, proc_on, vec![orig]);
            p.set_prop(key(name), Value::Obj(f), WEC);
        }
    }
}

// ============================================================================================
// module
// ============================================================================================

pub fn create_module(vm: &mut Vm, _name: &str) -> Value {
    let (ctor, _) = class(vm);
    let o = vm.new_object();
    let fns: &[(&str, u32, NativeFn)] = &[
        ("spawn", 3, cp_spawn),
        ("exec", 3, cp_exec_f),
        ("execFile", 4, cp_exec_file_f),
        ("execFileSync", 3, cp_exec_file_sync_f),
        ("execSync", 2, cp_exec_sync_f),
        ("spawnSync", 3, cp_spawn_sync_f),
        ("fork", 3, cp_fork),
        ("_forkChild", 0, noop),
    ];
    for (n, l, f) in fns {
        let fo = plain_fn(vm, n, *l, *f);
        o.set_prop(key(n), Value::Obj(fo), WEC);
    }
    o.set_prop(key("ChildProcess"), Value::Obj(ctor), WEC);
    Value::Obj(o)
}

// the reference's JS frames for errors raised synchronously by these entry points
crate::framed_native!(cp_exec_f, ["exec"], cp_exec);
crate::framed_native!(cp_exec_file_f, ["execFile"], cp_exec_file);
crate::framed_native!(cp_exec_file_sync_f, ["execFileSync"], cp_exec_file_sync);
crate::framed_native!(cp_exec_sync_f, ["execSync"], cp_exec_sync);
crate::framed_native!(cp_spawn_sync_f, ["spawnSync"], cp_spawn_sync);
crate::framed_native!(collect_close_f, ["emit", "invoke", "finish"], collect_close);
crate::framed_native!(collect_error_f, ["emit", "invoke", "finish"], collect_error);
