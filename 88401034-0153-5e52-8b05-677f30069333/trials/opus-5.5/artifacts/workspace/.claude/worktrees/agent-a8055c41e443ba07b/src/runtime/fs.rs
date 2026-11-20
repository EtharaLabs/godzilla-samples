// node:fs — the file-system module, modelled on the reference runtime's observable behaviour:
//
// * every operation is synchronous underneath; the callback API runs the sync operation inside a
//   `process.nextTick` callback and the promise API runs it immediately and returns a settled
//   promise;
// * errors embed Rust `io::Error` texts with a per-operation template (see the error helpers);
// * file descriptors come from a private table numbered from 0 (stdio is not part of it);
// * Stats/Dirent/Dir/FileHandle are small classes whose instances carry plain own properties;
// * ReadStream/WriteStream sit on a self-contained Readable/Writable base that mirrors the
//   reference stream semantics (state in `_readableState` / `_writableState`, writes serialised
//   through a promise chain).

use crate::builtins::typedarray::{ta_bytes, ta_values_vec};
use crate::object::*;
use crate::value::*;
use crate::vm::{Job, JsResult, Vm};
use std::cell::{Cell, RefCell};
use std::collections::{HashMap, VecDeque};
use std::io::{Read, Seek, SeekFrom, Write};
use std::os::unix::fs::{MetadataExt, PermissionsExt};

type IoResult<T> = std::io::Result<T>;

// ============================================================================================
// module state
// ============================================================================================

#[derive(Default, Clone)]
struct Classes {
    stats: Option<Obj>,
    dirent: Option<Obj>,
    dir: Option<Obj>,
    file_handle: Option<Obj>,
    read_stream: Option<Obj>,
    write_stream: Option<Obj>,
    stat_watcher: Option<Obj>,
    list_iter: Option<Obj>,
    dir_iter: Option<Obj>,
}

/// The Readable/Writable constructors the file streams are built on (node:stream's classes).
#[allow(dead_code)]
pub fn stream_base_ctors(vm: &mut Vm) -> Option<(Obj, Obj)> {
    let c = crate::runtime::nodestream::classes(vm);
    Some((c.readable, c.writable))
}

struct Watch {
    path: String,
    watcher: Obj,
    listeners: Vec<Value>,
    prev: Value,
    timer: u64,
}

struct FsState {
    fds: HashMap<i64, std::fs::File>,
    next_fd: i64,
    tmp_counter: u32,
    classes: Classes,
    watchers: Vec<Watch>,
}

thread_local! {
    static FS: RefCell<FsState> = RefCell::new(FsState {
        fds: HashMap::new(),
        next_fd: 0,
        tmp_counter: 0,
        classes: Classes::default(),
        watchers: Vec::new(),
    });
}

fn class_proto(vm: &Vm, f: fn(&Classes) -> Option<Obj>) -> Obj {
    FS.with(|s| f(&s.borrow().classes)).unwrap_or_else(|| vm.intr.object_proto.clone())
}

// ============================================================================================
// small value helpers
// ============================================================================================

fn key(s: &str) -> PropKey {
    PropKey::from_str(s)
}

fn num_str(n: f64) -> String {
    crate::numconv::number_to_string(n)
}

/// `v.k` on any value (throws "cannot read property 'k' of undefined" on nullish bases).
fn getp(vm: &mut Vm, v: &Value, k: &str) -> JsResult<Value> {
    vm.get_prop_of(v, &key(k))
}

/// `v.k = x` (strict).
fn setp(vm: &mut Vm, v: &Value, k: &str, x: Value) -> JsResult<()> {
    vm.set_prop_of(v, key(k), x, true)
}

/// `options && options.k`
fn opt_get(vm: &mut Vm, opts: &Value, k: &str) -> JsResult<Value> {
    if opts.truthy() {
        getp(vm, opts, k)
    } else {
        Ok(opts.clone())
    }
}

fn to_num(vm: &mut Vm, v: &Value) -> JsResult<f64> {
    match v {
        Value::Num(n) => Ok(*n),
        Value::BigInt(b) => Ok(b.to_string_radix(10).parse::<f64>().unwrap_or(f64::NAN)),
        _ => vm.to_number(v),
    }
}

/// `this.m(...args)`
fn call_method(vm: &mut Vm, this: &Value, m: &str, args: &[Value]) -> JsResult<Value> {
    let f = getp(vm, this, m)?;
    if !f.is_callable() {
        return vm.throw_type(format!("(intermediate value).{} is not a function", m));
    }
    vm.call(&f, this.clone(), args)
}

fn emit(vm: &mut Vm, this: &Value, ev: &str, args: &[Value]) -> JsResult<Value> {
    let mut all = Vec::with_capacity(args.len() + 1);
    all.push(Value::str(ev));
    all.extend_from_slice(args);
    call_method(vm, this, "emit", &all)
}

/// Call a user callback the way the reference's arrow functions do (`cb(...)`).
fn call_cb(vm: &mut Vm, cb: &Value, args: &[Value]) -> JsResult<Value> {
    if !cb.is_callable() {
        return vm.throw_type("cb is not a function");
    }
    vm.call(cb, Value::Undefined, args)
}

fn closure(vm: &mut Vm, name: &str, len: u32, f: NativeFn, slots: Vec<Value>) -> Value {
    Value::Obj(vm.native_closure(name, len, f, slots))
}

/// process.nextTick(f)
fn next_tick(vm: &mut Vm, f: Value) -> JsResult<()> {
    if let Some(p) = vm.host.process_obj.clone() {
        let nt = vm.get_str(&p, "nextTick")?;
        if nt.is_callable() {
            vm.call(&nt, Value::Obj(p), &[f])?;
            return Ok(());
        }
    }
    vm.host.callbacks.push_back((f, Vec::new()));
    Ok(())
}

/// queueMicrotask(f) the reference way (a reaction on a resolved promise): same timing as a
/// plain microtask, but an exception surfaces as an unhandled rejection ("Uncaught (in promise)").
#[allow(dead_code)]
fn queue_microtask(vm: &mut Vm, f: Value) {
    match crate::builtins::promise::promise_resolve_intrinsic(vm, Value::Undefined) {
        Ok(p) => {
            let _ = crate::builtins::promise::promise_then(vm, &p, f, Value::Undefined);
        }
        Err(_) => vm.jobs.push_back(Job::Callback(f, Vec::new())),
    }
}

fn resolved(vm: &mut Vm, v: Value) -> Value {
    let cap = vm.new_promise_capability_intrinsic();
    let _ = vm.call(&cap.resolve, Value::Undefined, &[v]);
    cap.promise
}

fn rejected(vm: &mut Vm, e: Value) -> Value {
    let cap = vm.new_promise_capability_intrinsic();
    let _ = vm.call(&cap.reject, Value::Undefined, &[e]);
    cap.promise
}

/// promisedCall: the operation already ran; settle a fresh promise with its outcome.
fn settle(vm: &mut Vm, r: JsResult<Value>) -> Value {
    match r {
        Ok(v) => resolved(vm, v),
        Err(e) => rejected(vm, e),
    }
}

fn iter_result(vm: &mut Vm, v: Value, done: bool) -> Value {
    Value::Obj(vm.obj_from(vec![("value", v), ("done", Value::Bool(done))]))
}

fn new_date(vm: &mut Vm, t: f64) -> Value {
    Value::Obj(Obj::with_class(Some(vm.intr.date_proto.clone()), ObjKind::Date(crate::datetime::time_clip(t)), "Date"))
}

/// `new Date(v)` for a single argument.
fn date_from_value(vm: &mut Vm, v: &Value) -> JsResult<Value> {
    let t = match v {
        Value::Num(n) => *n,
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::Date(_)) => match &o.borrow().kind {
            ObjKind::Date(t) => *t,
            _ => f64::NAN,
        },
        _ => {
            let p = vm.to_primitive(v, crate::ops::Hint::Default)?;
            match &p {
                Value::Str(s) => crate::datetime::parse_for_constructor(&s.to_rust_string()),
                _ => vm.to_number(&p)?,
            }
        }
    };
    Ok(new_date(vm, t))
}

/// Run `f` with the reference's JS frames (outermost first) on the trace, so errors created
/// inside carry the same `stack` lines. The reference engine has proper tail calls, so only
/// frames that are still live at the throw site are listed by the callers of this helper.
fn with_frames<T>(vm: &mut Vm, names: &[&str], f: impl FnOnce(&mut Vm) -> JsResult<T>) -> JsResult<T> {
    for n in names {
        vm.trace.push(crate::vm::TraceEntry { name: JsStr::from_str(n) });
    }
    let r = f(vm);
    let keep = vm.trace.len().saturating_sub(names.len());
    vm.trace.truncate(keep);
    r
}

/// A native whose JS counterpart's frame(s) are live while it runs.
macro_rules! framed {
    ($name:ident, [$($frame:expr),*], $inner:ident) => {
        fn $name(vm: &mut Vm, a: &Args) -> JsResult<Value> {
            with_frames(vm, &[$($frame),*], |vm| $inner(vm, a))
        }
    };
    ($name:ident, $frame:expr, $inner:ident) => {
        fn $name(vm: &mut Vm, a: &Args) -> JsResult<Value> {
            with_frames(vm, &[$frame], |vm| $inner(vm, a))
        }
    };
}

fn require_new(vm: &mut Vm, a: &Args) -> JsResult<Obj> {
    match &a.new_target {
        Some(nt) => Ok(nt.clone()),
        None => vm.throw_type("Class constructor cannot be invoked without 'new'"),
    }
}

fn instance(vm: &mut Vm, a: &Args, fallback: fn(&Classes) -> Option<Obj>) -> JsResult<Obj> {
    let nt = require_new(vm, a)?;
    let fb = class_proto(vm, fallback);
    let proto = vm.proto_from_nt(&Some(nt), &fb)?;
    Ok(Obj::new(Some(proto), ObjKind::Ordinary))
}

// ============================================================================================
// errors
// ============================================================================================

fn error_with(vm: &mut Vm, kind: &str, msg: &str, props: &[(&str, &str)]) -> Value {
    let e = vm.make_error(kind, msg);
    if let Value::Obj(o) = &e {
        for (k, v) in props {
            o.set_prop(key(k), Value::str(v), WEC);
        }
    }
    e
}

fn plain_err(vm: &mut Vm, msg: &str) -> Value {
    vm.make_error("Error", msg)
}

/// The errno-like code the reference derives from an io::Error (by error kind).
fn kind_code(e: &std::io::Error) -> &'static str {
    use std::io::ErrorKind::*;
    match e.kind() {
        NotFound => "ENOENT",
        PermissionDenied => "EACCES",
        AlreadyExists => "EEXIST",
        NotADirectory => "ENOTDIR",
        IsADirectory => "EISDIR",
        DirectoryNotEmpty => "ENOTEMPTY",
        _ => "EIO",
    }
}

/// "<CODE>: <io error>, <syscall> '<path>'" with own `code`, `path`, `syscall`.
fn sys_err(vm: &mut Vm, e: &std::io::Error, syscall: &str, path: &str) -> Value {
    let code = kind_code(e);
    error_with(vm, "Error", &format!("{}: {}, {} '{}'", code, e, syscall, path), &[("code", code), ("path", path), ("syscall", syscall)])
}

/// Errors raised by the reference's JS layer: own `code`, `syscall`, `path` (in that order).
fn js_err(vm: &mut Vm, code: &str, syscall: &str, path: &str, msg: &str) -> Value {
    error_with(vm, "Error", &format!("{}: {}, {} '{}'", code, msg, syscall, path), &[("code", code), ("syscall", syscall), ("path", path)])
}

/// fsError() with a raw JS value as path: "<CODE>: <msg>, <syscall>[ '<String(path)>']"; the
/// `path` property holds the value itself and is absent when it is undefined.
fn js_err_raw(vm: &mut Vm, code: &str, syscall: &str, path: &Value, msg: &str) -> JsResult<Value> {
    let shown = if path.is_nullish() { String::new() } else { format!(" '{}'", string_of(vm, path)?) };
    let e = vm.make_error("Error", &format!("{}: {}, {}{}", code, msg, syscall, shown));
    if let Value::Obj(o) = &e {
        o.set_prop(key("code"), Value::str(code), WEC);
        o.set_prop(key("syscall"), Value::str(syscall), WEC);
        if !path.is_nullish() {
            o.set_prop(key("path"), path.clone(), WEC);
        }
    }
    Ok(e)
}

/// readFileSync failures: "cannot read '<path>': <io error>" with a coarse `code`.
fn read_err(vm: &mut Vm, path: &str, e: &std::io::Error) -> Value {
    let code = match e.kind() {
        std::io::ErrorKind::NotFound => "ENOENT",
        std::io::ErrorKind::PermissionDenied => "EACCES",
        _ => "EIO",
    };
    error_with(vm, "Error", &format!("cannot read '{}': {}", path, e), &[("code", code)])
}

fn bad_fd(vm: &mut Vm, n: f64) -> Value {
    vm.make_error("TypeError", &format!("bad file descriptor {}", num_str(n)))
}

fn nul_error() -> std::io::Error {
    std::io::Error::new(std::io::ErrorKind::InvalidInput, "file name contained an unexpected NUL byte")
}

/// Node-style error used by other runtime modules (process.chdir).
pub fn fs_error(vm: &mut Vm, code: &str, desc: &str, syscall: &str, path: &str, io: Option<&std::io::Error>) -> Value {
    let msg = match io {
        Some(e) => format!("{}: {}, {} '{}'", code, e, syscall, path),
        None => format!("{}: {}, {} '{}'", code, desc, syscall, path),
    };
    let e = vm.make_error("Error", &msg);
    if let Value::Obj(o) = &e {
        o.set_prop(key("code"), Value::str(code), WEC);
    }
    e
}

#[allow(dead_code)]
pub fn io_code(e: &std::io::Error) -> &'static str {
    match e.raw_os_error() {
        Some(n) => crate::runtime::util::errno_name(n),
        None => match e.kind() {
            std::io::ErrorKind::NotFound => "ENOENT",
            std::io::ErrorKind::PermissionDenied => "EACCES",
            std::io::ErrorKind::AlreadyExists => "EEXIST",
            _ => "EIO",
        },
    }
}

// ============================================================================================
// argument conversion
// ============================================================================================

/// `String(v)` (symbols allowed).
fn string_of(vm: &mut Vm, v: &Value) -> JsResult<String> {
    match v {
        Value::Sym(s) => Ok(s.descriptive_string()),
        _ => Ok(vm.to_string(v)?.to_rust_string()),
    }
}

fn is_uint8_array(o: &Obj) -> bool {
    matches!(&o.borrow().kind, ObjKind::TypedArray(t) if t.kind == TAKind::Uint8)
}

fn url_pathname(vm: &mut Vm, v: &Value) -> JsResult<Option<String>> {
    let url = match vm.global.get_own_str("URL") {
        Some(u) if u.is_callable() => u,
        _ => return Ok(None),
    };
    if !vm.instance_of(v, &url)? {
        return Ok(None);
    }
    let p = getp(vm, v, "pathname")?;
    Ok(Some(string_of(vm, &p)?))
}

/// toPath: URL → pathname, Uint8Array → UTF-8 text, anything else → String(v); a leading
/// "file://" is dropped.
pub fn to_path(vm: &mut Vm, v: &Value) -> JsResult<String> {
    let s = match v {
        Value::Str(s) => s.to_rust_string(),
        Value::Obj(o) => {
            if let Some(p) = url_pathname(vm, v)? {
                p
            } else if is_uint8_array(o) {
                String::from_utf8_lossy(&ta_bytes(o)).into_owned()
            } else {
                string_of(vm, v)?
            }
        }
        _ => string_of(vm, v)?,
    };
    Ok(match s.strip_prefix("file://") {
        Some(r) => r.to_string(),
        None => s,
    })
}

/// Kept for other runtime modules.
#[allow(dead_code)]
pub fn path_arg(vm: &mut Vm, v: &Value) -> JsResult<String> {
    to_path(vm, v)
}

/// encOf(options): a string is the encoding itself, otherwise `options && options.encoding`.
fn enc_of(vm: &mut Vm, opts: &Value) -> JsResult<Value> {
    match opts {
        Value::Str(_) => Ok(opts.clone()),
        v if v.truthy() => getp(vm, v, "encoding"),
        _ => Ok(Value::Undefined),
    }
}

fn is_buffer_enc(v: &Value) -> bool {
    matches!(v, Value::Str(s) if s.eq_str("buffer"))
}

/// Resolve an encoding argument the way the reference Buffer does (falsy → utf8).
fn encoding_name(vm: &mut Vm, enc: &Value) -> JsResult<&'static str> {
    match enc {
        v if !v.truthy() => Ok("utf8"),
        Value::Str(s) => {
            let st = s.to_rust_string();
            match crate::runtime::buffer::norm_encoding(&st) {
                Some(e) => Ok(e),
                None => vm.throw_type(format!("Unknown encoding: {}", st)),
            }
        }
        _ => vm.throw_type("undefined is not a function"),
    }
}

/// `buffer.toString(enc)`
fn bytes_to_string(vm: &mut Vm, bytes: &[u8], enc: &Value) -> JsResult<Value> {
    let e = encoding_name(vm, enc)?;
    Ok(Value::Str(crate::runtime::buffer::decode_bytes(bytes, e)))
}

fn check_len(vm: &mut Vm, n: usize) -> JsResult<()> {
    if n > crate::builtins::typedarray::MAX_TA_LENGTH {
        return vm.throw_range("Invalid typed array length");
    }
    Ok(())
}

fn to_u8(f: f64) -> u8 {
    if !f.is_finite() {
        0
    } else {
        f.trunc().rem_euclid(256.0) as u8
    }
}

/// toBuffer(data, enc): strings are encoded, everything else goes through Buffer.from.
fn to_buffer(vm: &mut Vm, data: &Value, enc: &Value) -> JsResult<Vec<u8>> {
    let bytes = match data {
        Value::Str(s) => {
            let e = encoding_name(vm, enc)?;
            crate::runtime::buffer::encode_string(s, e)
        }
        Value::Obj(o) => object_bytes(vm, data, o)?,
        _ => return vm.throw_type("Buffer.from: unsupported value"),
    };
    check_len(vm, bytes.len())?;
    Ok(bytes)
}

fn object_bytes(vm: &mut Vm, v: &Value, o: &Obj) -> JsResult<Vec<u8>> {
    enum K {
        Ta(TAKind),
        Ab(bool),
        Dv,
        Other,
    }
    let k = match &o.borrow().kind {
        ObjKind::TypedArray(t) => K::Ta(t.kind),
        ObjKind::ArrayBuffer(b) => K::Ab(b.borrow().shared),
        ObjKind::DataView(_) => K::Dv,
        _ => K::Other,
    };
    match k {
        K::Ta(kind) => match kind {
            TAKind::Uint8 | TAKind::Int8 | TAKind::Uint8C => Ok(ta_bytes(o)),
            TAKind::BigInt64 | TAKind::BigUint64 => vm.throw_type("Cannot convert a BigInt value to a number"),
            _ => Ok(ta_values_vec(o).iter().map(|x| to_u8(x.as_num().unwrap_or(0.0))).collect()),
        },
        K::Ab(false) => Ok(ta_bytes(o)),
        K::Ab(true) => vm.throw_type("Buffer.from: unsupported value"),
        K::Dv => Ok(Vec::new()),
        K::Other => {
            let len = getp(vm, v, "length")?;
            if len.is_undefined() {
                return vm.throw_type("Buffer.from: unsupported value");
            }
            let n = vm.to_length(&len)? as usize;
            check_len(vm, n)?;
            let mut out = Vec::with_capacity(n);
            for i in 0..n {
                let x = vm.get_prop_of(v, &PropKey::from_index(i as u32))?;
                let f = vm.to_number(&x)?;
                out.push(to_u8(f));
            }
            Ok(out)
        }
    }
}

fn new_buffer(vm: &mut Vm, bytes: Vec<u8>) -> JsResult<Value> {
    crate::runtime::buffer::new_buffer_value(vm, bytes)
}

/// `Number(x) || 0`
fn num_or_zero(vm: &mut Vm, v: &Value) -> JsResult<f64> {
    let n = to_num(vm, v)?;
    Ok(if n.is_nan() || n == 0.0 { 0.0 } else { n })
}

/// toUnixSeconds(time) (exported as fs._toUnixTimestamp)
fn unix_seconds(vm: &mut Vm, t: &Value) -> JsResult<f64> {
    match t {
        Value::Undefined | Value::Null => Ok(crate::datetime::now_ms() / 1000.0),
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::Date(_)) => {
            let ms = match &o.borrow().kind {
                ObjKind::Date(x) => *x,
                _ => f64::NAN,
            };
            Ok(ms / 1000.0)
        }
        Value::Num(n) => Ok(if *n > 1e11 { n / 1000.0 } else { *n }),
        _ => {
            let n = to_num(vm, t)?;
            if !n.is_nan() {
                return Ok(n);
            }
            let d = date_from_value(vm, t)?;
            let ms = match &d {
                Value::Obj(o) => match &o.borrow().kind {
                    ObjKind::Date(x) => *x,
                    _ => f64::NAN,
                },
                _ => f64::NAN,
            };
            Ok(ms / 1000.0)
        }
    }
}

fn to_unix_timestamp(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Num(unix_seconds(vm, &a.arg(0))?))
}

// ============================================================================================
// low-level helpers: libc calls not covered by std
// ============================================================================================

#[repr(C)]
struct Timespec {
    tv_sec: i64,
    tv_nsec: i64,
}

extern "C" {
    fn utimensat(dirfd: i32, path: *const std::os::raw::c_char, times: *const Timespec, flags: i32) -> i32;
    fn futimens(fd: i32, times: *const Timespec) -> i32;
    fn statfs(path: *const std::os::raw::c_char, buf: *mut u64) -> i32;
}

const AT_FDCWD: i32 = -100;
const AT_SYMLINK_NOFOLLOW: i32 = 0x100;

/// seconds → (sec, nsec) with microsecond resolution
fn timespec(t: f64) -> Timespec {
    let us = (t * 1e6).round();
    let us = if us.is_nan() { 0 } else { us as i64 };
    Timespec { tv_sec: us.div_euclid(1_000_000), tv_nsec: us.rem_euclid(1_000_000) * 1000 }
}

fn c_path(p: &str) -> IoResult<std::ffi::CString> {
    std::ffi::CString::new(p).map_err(|_| nul_error())
}

fn set_times(path: &str, atime: f64, mtime: f64, nofollow: bool) -> IoResult<()> {
    let c = c_path(path)?;
    let ts = [timespec(atime), timespec(mtime)];
    let r = unsafe { utimensat(AT_FDCWD, c.as_ptr(), ts.as_ptr(), if nofollow { AT_SYMLINK_NOFOLLOW } else { 0 }) };
    if r != 0 {
        return Err(std::io::Error::last_os_error());
    }
    Ok(())
}

fn statfs_values(path: &str) -> IoResult<[f64; 7]> {
    let c = c_path(path)?;
    let mut buf = [0u64; 32];
    let r = unsafe { statfs(c.as_ptr(), buf.as_mut_ptr()) };
    if r != 0 {
        return Err(std::io::Error::last_os_error());
    }
    // the reference reports no filesystem type (always 0)
    let mut out = [0.0; 7];
    for (i, o) in out.iter_mut().enumerate().skip(1) {
        *o = buf[i] as f64;
    }
    Ok(out)
}

// ============================================================================================
// file descriptors
// ============================================================================================

#[derive(Clone, Copy, PartialEq)]
enum Mode {
    R,
    RW,
    W,
    WR,
    A,
    AR,
}

/// flagToMode: only the documented strings are recognised (everything else reads); numbers are
/// decoded with the reference's (BSD-valued) O_* constants.
fn flag_mode(flags: &Value) -> Mode {
    match flags {
        Value::Str(s) => match s.to_rust_string().as_str() {
            "r+" | "rs+" => Mode::RW,
            "w" | "wx" => Mode::W,
            "w+" | "wx+" => Mode::WR,
            "a" | "ax" => Mode::A,
            "a+" | "ax+" => Mode::AR,
            _ => Mode::R,
        },
        Value::Num(n) => {
            let f = crate::builtins::number::to_int32(*n);
            let acc = f & 3;
            if f & 8 != 0 {
                if acc != 0 {
                    Mode::AR
                } else {
                    Mode::A
                }
            } else if f & (512 | 1024) != 0 {
                if acc == 2 {
                    Mode::WR
                } else {
                    Mode::W
                }
            } else if acc == 2 {
                Mode::RW
            } else {
                Mode::R
            }
        }
        _ => Mode::R,
    }
}

fn open_file(path: &str, mode: Mode) -> IoResult<std::fs::File> {
    let mut o = std::fs::OpenOptions::new();
    match mode {
        Mode::R => o.read(true),
        Mode::RW => o.read(true).write(true),
        Mode::W => o.write(true).create(true).truncate(true),
        Mode::WR => o.read(true).write(true).create(true).truncate(true),
        Mode::A => o.append(true).create(true),
        Mode::AR => o.read(true).append(true).create(true),
    };
    o.open(path)
}

fn register_fd(file: std::fs::File) -> i64 {
    FS.with(|s| {
        let mut st = s.borrow_mut();
        let fd = st.next_fd;
        st.next_fd += 1;
        st.fds.insert(fd, file);
        fd
    })
}

fn open_fd(vm: &mut Vm, path: &str, mode: Mode) -> JsResult<i64> {
    match open_file(path, mode) {
        Ok(f) => Ok(register_fd(f)),
        Err(e) => Err(plain_err(vm, &format!("openSync '{}': {}", path, e))),
    }
}

fn close_fd_num(n: f64) {
    if let Some(k) = fd_key(n) {
        FS.with(|s| {
            s.borrow_mut().fds.remove(&k);
        });
    }
}

fn fd_key(n: f64) -> Option<i64> {
    if n.is_finite() && n.fract() == 0.0 && n >= 0.0 && n < 9.0e15 {
        Some(n as i64)
    } else {
        None
    }
}

/// Run `f` on the open file behind the JS fd value (TypeError "bad file descriptor N" otherwise).
/// The fd goes through ToNumber (BigInt/Symbol fds throw).
fn with_fd<T>(vm: &mut Vm, fdv: &Value, f: impl FnOnce(&mut std::fs::File) -> T) -> JsResult<T> {
    let n = vm.to_number(fdv)?;
    let r = FS.with(|s| {
        let mut st = s.borrow_mut();
        match fd_key(n).and_then(|k| st.fds.get_mut(&k)) {
            Some(file) => Some(f(file)),
            None => None,
        }
    });
    match r {
        Some(v) => Ok(v),
        None => Err(bad_fd(vm, n)),
    }
}

/// A position as the native layer reads it: only finite non-negative numbers select an offset;
/// anything else (null, -1, NaN, ±Infinity, strings, …) means "the current file position".
fn pos_arg(v: &Value) -> f64 {
    match v {
        Value::Num(n) if n.is_finite() && *n >= 0.0 => n.trunc(),
        _ => -1.0,
    }
}

/// A byte count as the native layer reads it (ToNumber; NaN/negative → 0).
fn len_arg(vm: &mut Vm, v: &Value) -> JsResult<f64> {
    let n = match v {
        Value::BigInt(_) => return vm.throw_type("Cannot convert a BigInt value to a number"),
        _ => vm.to_number(v)?,
    };
    Ok(if n.is_nan() || n <= 0.0 { 0.0 } else { n.trunc() })
}

/// preadSync(fd, length, position): position ≥ 0 seeks first; reads up to `len` bytes.
fn pread(vm: &mut Vm, fdv: &Value, len: f64, pos: f64) -> JsResult<Vec<u8>> {
    let len = if len.is_nan() || len <= 0.0 { 0u64 } else { len as u64 };
    let r = with_fd(vm, fdv, |f| -> IoResult<Vec<u8>> {
        if pos >= 0.0 {
            f.seek(SeekFrom::Start(pos as u64))?;
        }
        let mut out = Vec::new();
        let mut buf = vec![0u8; len.min(65536) as usize];
        if len == 0 {
            // a zero-length read still reaches the OS (and fails on write-only descriptors)
            f.read(&mut buf[..0])?;
        }
        while (out.len() as u64) < len {
            let want = ((len - out.len() as u64) as usize).min(buf.len());
            match f.read(&mut buf[..want]) {
                Ok(0) => break,
                Ok(n) => out.extend_from_slice(&buf[..n]),
                Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(e) => return Err(e),
            }
        }
        Ok(out)
    })?;
    r.map_err(|e| plain_err(vm, &format!("read 'fd': {}", e)))
}

/// pwriteSync(fd, bytes, position): position ≥ 0 seeks first; returns the byte count.
fn pwrite(vm: &mut Vm, fdv: &Value, data: &[u8], pos: f64) -> JsResult<usize> {
    let r = with_fd(vm, fdv, |f| -> IoResult<usize> {
        if pos >= 0.0 {
            f.seek(SeekFrom::Start(pos as u64))?;
        }
        f.write_all(data)?;
        Ok(data.len())
    })?;
    r.map_err(|e| plain_err(vm, &format!("write 'fd': {}", e)))
}

/// fd operation with the "<op> 'fd': <io error>" template.
fn fd_op(vm: &mut Vm, fdv: &Value, op: &str, f: impl FnOnce(&mut std::fs::File) -> IoResult<()>) -> JsResult<Value> {
    let r = with_fd(vm, fdv, f)?;
    match r {
        Ok(()) => Ok(Value::Undefined),
        Err(e) => Err(plain_err(vm, &format!("{} 'fd': {}", op, e))),
    }
}

// ============================================================================================
// Stats / Dirent
// ============================================================================================

const STAT_KEYS: [&str; 14] = ["dev", "ino", "mode", "nlink", "uid", "gid", "rdev", "size", "blksize", "blocks", "atimeMs", "mtimeMs", "ctimeMs", "birthtimeMs"];
const DATE_KEYS: [(&str, &str); 4] = [("atime", "atimeMs"), ("mtime", "mtimeMs"), ("ctime", "ctimeMs"), ("birthtime", "birthtimeMs")];

struct RawStat {
    nums: [f64; 14],
    kind: &'static str,
}

fn time_ms(t: IoResult<std::time::SystemTime>) -> f64 {
    match t {
        Ok(t) => match t.duration_since(std::time::UNIX_EPOCH) {
            Ok(d) => d.as_secs_f64() * 1000.0,
            Err(_) => 0.0,
        },
        Err(_) => 0.0,
    }
}

fn kind_of(ft: &std::fs::FileType) -> &'static str {
    if ft.is_file() {
        "file"
    } else if ft.is_dir() {
        "dir"
    } else if ft.is_symlink() {
        "symlink"
    } else {
        "other"
    }
}

fn raw_stat(md: &std::fs::Metadata) -> RawStat {
    RawStat {
        nums: [
            md.dev() as f64,
            md.ino() as f64,
            md.mode() as f64,
            md.nlink() as f64,
            md.uid() as f64,
            md.gid() as f64,
            md.rdev() as f64,
            md.size() as f64,
            md.blksize() as f64,
            md.blocks() as f64,
            time_ms(md.accessed()),
            time_ms(md.modified()),
            md.ctime() as f64 * 1000.0 + md.ctime_nsec() as f64 / 1e6,
            time_ms(md.created()),
        ],
        kind: kind_of(&md.file_type()),
    }
}

fn make_stats(vm: &mut Vm, r: &RawStat) -> Value {
    let proto = class_proto(vm, |c| c.stats.clone());
    let o = Obj::new(Some(proto), ObjKind::Ordinary);
    for (i, k) in STAT_KEYS.iter().enumerate() {
        o.set_prop(key(k), Value::Num(r.nums[i]), WEC);
    }
    for (i, (k, _)) in DATE_KEYS.iter().enumerate() {
        let d = new_date(vm, r.nums[10 + i]);
        o.set_prop(key(k), d, WEC);
    }
    o.set_prop(key("_kind"), Value::str(r.kind), WEC);
    Value::Obj(o)
}

// new Stats(raw)
framed!(stats_ctor, ["Stats"], stats_ctor_);

fn stats_ctor_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = instance(vm, a, |c| c.stats.clone())?;
    let raw = a.arg(0);
    for k in STAT_KEYS.iter() {
        let v = getp(vm, &raw, k)?;
        o.set_prop(key(k), v, WEC);
    }
    for (k, src) in DATE_KEYS.iter() {
        let v = getp(vm, &raw, src)?;
        let d = date_from_value(vm, &v)?;
        o.set_prop(key(k), d, WEC);
    }
    let kind = getp(vm, &raw, "kind")?;
    o.set_prop(key("_kind"), kind, WEC);
    Ok(Value::Obj(o))
}

fn make_dirent(vm: &mut Vm, name: Value, kind: &str, parent: &str) -> Value {
    let proto = class_proto(vm, |c| c.dirent.clone());
    let o = Obj::new(Some(proto), ObjKind::Ordinary);
    o.set_prop(key("name"), name, WEC);
    o.set_prop(key("parentPath"), Value::str(parent), WEC);
    o.set_prop(key("path"), Value::str(parent), WEC);
    o.set_prop(key("_kind"), Value::str(kind), WEC);
    Value::Obj(o)
}

/// new Dirent(name, kind, parentPath)
fn dirent_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = instance(vm, a, |c| c.dirent.clone())?;
    o.set_prop(key("name"), a.arg(0), WEC);
    o.set_prop(key("parentPath"), a.arg(2), WEC);
    o.set_prop(key("path"), a.arg(2), WEC);
    o.set_prop(key("_kind"), a.arg(1), WEC);
    Ok(Value::Obj(o))
}

fn kind_is(vm: &mut Vm, a: &Args, k: &str) -> JsResult<Value> {
    let v = getp(vm, &a.this, "_kind")?;
    Ok(Value::Bool(matches!(&v, Value::Str(s) if s.eq_str(k))))
}

fn install_kind_methods(vm: &mut Vm, proto: &Obj) {
    let methods: &[(&str, NativeFn)] = &[
        ("isFile", |vm, a| kind_is(vm, a, "file")),
        ("isDirectory", |vm, a| kind_is(vm, a, "dir")),
        ("isSymbolicLink", |vm, a| kind_is(vm, a, "symlink")),
        ("isBlockDevice", |_vm, _a| Ok(Value::Bool(false))),
        ("isCharacterDevice", |_vm, _a| Ok(Value::Bool(false))),
        ("isFIFO", |_vm, _a| Ok(Value::Bool(false))),
        ("isSocket", |_vm, _a| Ok(Value::Bool(false))),
    ];
    for (n, f) in methods {
        vm.def_method(proto, n, 0, *f);
    }
}

// ============================================================================================
// path-based native operations
// ============================================================================================

fn stat_path(vm: &mut Vm, path: &str, follow: bool) -> JsResult<Value> {
    let r = if follow { std::fs::metadata(path) } else { std::fs::symlink_metadata(path) };
    match r {
        Ok(md) => {
            let raw = raw_stat(&md);
            Ok(make_stats(vm, &raw))
        }
        Err(e) => Err(sys_err(vm, &e, if follow { "stat" } else { "lstat" }, path)),
    }
}

/// __node.mkdir(path, recursive): returns the path (recursive: undefined when it already exists
/// as a non-directory).
fn mkdir_impl(vm: &mut Vm, path: &str, recursive: bool) -> JsResult<Value> {
    let r = if recursive { std::fs::create_dir_all(path) } else { std::fs::create_dir(path) };
    match r {
        Ok(()) => Ok(Value::str(path)),
        Err(e) if recursive && e.kind() == std::io::ErrorKind::AlreadyExists => Ok(Value::Undefined),
        Err(e) => Err(sys_err(vm, &e, "mkdir", path)),
    }
}

/// __node.rm(path, recursive, force): directories (following symlinks) are removed as
/// directories, anything else is unlinked.
fn rm_impl(vm: &mut Vm, path: &str, recursive: bool, force: bool) -> JsResult<Value> {
    let r = if std::path::Path::new(path).is_dir() {
        if recursive {
            std::fs::remove_dir_all(path)
        } else {
            std::fs::remove_dir(path)
        }
    } else {
        std::fs::remove_file(path)
    };
    match r {
        Ok(()) => Ok(Value::Undefined),
        Err(e) if force && e.kind() == std::io::ErrorKind::NotFound => Ok(Value::Undefined),
        Err(e) => Err(sys_err(vm, &e, "rm", path)),
    }
}

fn name_of(e: &std::fs::DirEntry) -> String {
    e.file_name().to_string_lossy().into_owned()
}

/// __fs_native.readdirSync: sorted names
fn readdir_names(vm: &mut Vm, path: &str) -> JsResult<Vec<String>> {
    let r = (|| -> IoResult<Vec<String>> {
        let mut v = Vec::new();
        for e in std::fs::read_dir(path)? {
            v.push(name_of(&e?));
        }
        Ok(v)
    })();
    match r {
        Ok(mut v) => {
            v.sort();
            Ok(v)
        }
        Err(e) => Err(plain_err(vm, &format!("readdirSync '{}': {}", path, e))),
    }
}

/// __node.readdirTypes: (name, kind) pairs in directory order
fn readdir_types(vm: &mut Vm, path: &str) -> JsResult<Vec<(String, &'static str)>> {
    let r = (|| -> IoResult<Vec<(String, &'static str)>> {
        let mut v = Vec::new();
        for e in std::fs::read_dir(path)? {
            let e = e?;
            let k = match e.file_type() {
                Ok(ft) => kind_of(&ft),
                Err(_) => "other",
            };
            v.push((name_of(&e), k));
        }
        Ok(v)
    })();
    r.map_err(|e| sys_err(vm, &e, "scandir", path))
}

fn dirents_of(vm: &mut Vm, path: &str) -> JsResult<Vec<Value>> {
    let entries = readdir_types(vm, path)?;
    Ok(entries.into_iter().map(|(n, k)| make_dirent(vm, Value::str(&n), k, path)).collect())
}

fn realpath_impl(path: &str) -> String {
    match std::fs::canonicalize(path) {
        Ok(p) => p.to_string_lossy().into_owned(),
        Err(_) => path.to_string(),
    }
}

fn mkdtemp_impl(vm: &mut Vm, prefix: &str) -> JsResult<String> {
    let pid = std::process::id();
    loop {
        let n = FS.with(|s| {
            let mut st = s.borrow_mut();
            let n = st.tmp_counter;
            st.tmp_counter = st.tmp_counter.wrapping_add(1);
            n
        });
        let p = format!("{}{:06x}{:04x}", prefix, pid, n);
        match std::fs::create_dir(&p) {
            Ok(()) => return Ok(p),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(sys_err(vm, &e, "mkdtemp", &p)),
        }
    }
}

fn chown_args(vm: &mut Vm, uid: &Value, gid: &Value) -> JsResult<(u32, u32)> {
    let u = to_num(vm, uid)?;
    let g = to_num(vm, gid)?;
    Ok((u as u32, g as u32))
}

// ============================================================================================
// sync API
// ============================================================================================

/// readvBytes(fd): the whole file from position 0, in 64 KiB reads.
fn readv_bytes_impl(vm: &mut Vm, fdv: &Value) -> JsResult<Vec<u8>> {
    let mut out = Vec::new();
    loop {
        let chunk = pread(vm, fdv, 65536.0, out.len() as f64)?;
        if chunk.is_empty() {
            break;
        }
        out.extend_from_slice(&chunk);
        // the concatenated Buffer could never be created; stop reading early
        check_len(vm, out.len())?;
    }
    check_len(vm, out.len())?;
    Ok(out)
}

framed!(readv_bytes, "readvBytes", readv_bytes_);

fn readv_bytes_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = readv_bytes_impl(vm, &a.arg(0))?;
    new_buffer(vm, b)
}

/// `buffer.toString(enc)` with the reference's helper frames for encoding errors.
fn decode_framed(vm: &mut Vm, bytes: &[u8], enc: &Value) -> JsResult<Value> {
    let frames: &[&str] = if matches!(enc, Value::Str(_)) { &["stringFromBytes"] } else { &["stringFromBytes", "normEncoding"] };
    with_frames(vm, frames, |vm| bytes_to_string(vm, bytes, enc))
}

fn finish_read(vm: &mut Vm, bytes: Vec<u8>, opts: &Value) -> JsResult<Value> {
    check_len(vm, bytes.len())?;
    let enc = enc_of(vm, opts)?;
    if enc.truthy() {
        decode_framed(vm, &bytes, &enc)
    } else {
        new_buffer(vm, bytes)
    }
}

fn read_file_impl(vm: &mut Vm, p: &Value, opts: &Value) -> JsResult<Value> {
    let bytes = if let Value::Num(_) = p {
        with_frames(vm, &["readFileSync", "readvBytes"], |vm| readv_bytes_impl(vm, p))?
    } else {
        with_frames(vm, &["readFileSync"], |vm| {
            let path = to_path(vm, p)?;
            match std::fs::read(&path) {
                Ok(b) => {
                    check_len(vm, b.len())?;
                    Ok(b)
                }
                Err(e) => Err(read_err(vm, &path, &e)),
            }
        })?
    };
    finish_read(vm, bytes, opts)
}

fn read_file_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    read_file_impl(vm, &a.arg(0), &a.arg(1))
}

/// toBuffer(data, enc) as called from `caller` (frames: caller → Buffer.from → helpers).
fn to_buffer_framed(vm: &mut Vm, caller: &str, data: &Value, enc: &Value) -> JsResult<Vec<u8>> {
    let mut frames: Vec<&str> = Vec::new();
    if !caller.is_empty() {
        frames.push(caller);
    }
    frames.push("from");
    if let Value::Str(_) = data {
        frames.push("bytesFromString");
        if enc.truthy() && !matches!(enc, Value::Str(_)) {
            frames.push("normEncoding");
        }
    }
    with_frames(vm, &frames, |vm| to_buffer(vm, data, enc))
}

/// open + pwrite(-1) + close, the way writeFileSync/appendFileSync write paths.
fn write_whole(vm: &mut Vm, path: &str, mode: Mode, data: &[u8]) -> JsResult<Value> {
    let fd = open_fd(vm, path, mode)?;
    let fdv = Value::Num(fd as f64);
    let r = pwrite(vm, &fdv, data, -1.0);
    close_fd_num(fd as f64);
    r?;
    Ok(Value::Undefined)
}

fn write_file_impl(vm: &mut Vm, p: &Value, data: &Value, opts: &Value) -> JsResult<Value> {
    let enc = enc_of(vm, opts)?;
    let buf = to_buffer_framed(vm, "writeFileSync", data, &enc)?;
    with_frames(vm, &["writeFileSync"], |vm| {
        if let Value::Num(_) = p {
            pwrite(vm, p, &buf, -1.0)?;
            return Ok(Value::Undefined);
        }
        let flag = opt_get(vm, opts, "flag")?;
        let mode = if flag.truthy() { flag_mode(&flag) } else { Mode::W };
        let path = to_path(vm, p)?;
        write_whole(vm, &path, mode, &buf)
    })
}

fn write_file_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    write_file_impl(vm, &a.arg(0), &a.arg(1), &a.arg(2))
}

fn append_file_impl(vm: &mut Vm, p: &Value, data: &Value, opts: &Value) -> JsResult<Value> {
    let enc = enc_of(vm, opts)?;
    let buf = to_buffer_framed(vm, "appendFileSync", data, &enc)?;
    with_frames(vm, &["appendFileSync"], |vm| {
        if let Value::Num(_) = p {
            pwrite(vm, p, &buf, -1.0)?;
            return Ok(Value::Undefined);
        }
        let path = to_path(vm, p)?;
        write_whole(vm, &path, Mode::A, &buf)
    })
}

fn append_file_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    append_file_impl(vm, &a.arg(0), &a.arg(1), &a.arg(2))
}

fn exists_impl(vm: &mut Vm, p: &Value) -> bool {
    match to_path(vm, p) {
        Ok(path) => std::fs::metadata(&path).is_ok(),
        Err(_) => false,
    }
}

fn exists_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(exists_impl(vm, &a.arg(0))))
}

fn mkdir_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let path = to_path(vm, &a.arg(0))?;
    let rec = opt_get(vm, &a.arg(1), "recursive")?.truthy();
    mkdir_impl(vm, &path, rec)
}

framed!(rmdir_sync, "rmdirSync", rmdir_sync_);

fn rmdir_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let path = to_path(vm, &a.arg(0))?;
    let rec = opt_get(vm, &a.arg(1), "recursive")?.truthy();
    rm_impl(vm, &path, rec, false)
}

framed!(rm_sync, "rmSync", rm_sync_);

fn rm_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let path = to_path(vm, &a.arg(0))?;
    let rec = opt_get(vm, &a.arg(1), "recursive")?.truthy();
    let force = opt_get(vm, &a.arg(1), "force")?.truthy();
    rm_impl(vm, &path, rec, force)
}

framed!(readdir_sync, "readdirSync", readdir_sync_);

fn readdir_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let path = to_path(vm, &a.arg(0))?;
    let opts = a.arg(1);
    if opt_get(vm, &opts, "withFileTypes")?.truthy() {
        let d = dirents_of(vm, &path)?;
        return Ok(Value::Obj(vm.new_array(d)));
    }
    let names = readdir_names(vm, &path)?;
    let enc = enc_of(vm, &opts)?;
    let mut out = Vec::with_capacity(names.len());
    for n in names {
        if is_buffer_enc(&enc) {
            out.push(new_buffer(vm, n.into_bytes())?);
        } else {
            out.push(Value::str(&n));
        }
    }
    Ok(Value::Obj(vm.new_array(out)))
}

framed!(unlink_sync, "unlinkSync", unlink_sync_);

fn unlink_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let path = to_path(vm, &a.arg(0))?;
    match std::fs::remove_file(&path) {
        Ok(()) => Ok(Value::Undefined),
        Err(e) => Err(plain_err(vm, &format!("unlinkSync '{}': {}", path, e))),
    }
}

fn two_paths(vm: &mut Vm, a: &Args) -> JsResult<(String, String)> {
    let x = to_path(vm, &a.arg(0))?;
    let y = to_path(vm, &a.arg(1))?;
    Ok((x, y))
}

framed!(rename_sync, "renameSync", rename_sync_);

fn rename_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (from, to) = two_paths(vm, a)?;
    match std::fs::rename(&from, &to) {
        Ok(()) => Ok(Value::Undefined),
        Err(e) => Err(sys_err(vm, &e, "rename", &from)),
    }
}

fn copy_file_impl(vm: &mut Vm, from: &str, to: &str) -> JsResult<Value> {
    match std::fs::copy(from, to) {
        Ok(_) => Ok(Value::Undefined),
        Err(e) => Err(sys_err(vm, &e, "copyfile", from)),
    }
}

framed!(copy_file_sync, "copyFileSync", copy_file_sync_);

fn copy_file_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (from, to) = two_paths(vm, a)?;
    copy_file_impl(vm, &from, &to)
}

framed!(link_sync, "linkSync", link_sync_);

fn link_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (existing, new) = two_paths(vm, a)?;
    match std::fs::hard_link(&existing, &new) {
        Ok(()) => Ok(Value::Undefined),
        Err(e) => Err(sys_err(vm, &e, "link", &existing)),
    }
}

framed!(stat_sync, "statSync", stat_sync_);

fn stat_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let path = to_path(vm, &a.arg(0))?;
    stat_path(vm, &path, true)
}

framed!(lstat_sync, "lstatSync", lstat_sync_);

fn lstat_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let path = to_path(vm, &a.arg(0))?;
    stat_path(vm, &path, false)
}

fn readlink_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let path = to_path(vm, &a.arg(0))?;
    match std::fs::read_link(&path) {
        Ok(t) => Ok(Value::str(&t.to_string_lossy())),
        Err(e) => Err(sys_err(vm, &e, "readlink", &path)),
    }
}

framed!(symlink_sync, "symlinkSync", symlink_sync_);

fn symlink_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (target, path) = two_paths(vm, a)?;
    match std::os::unix::fs::symlink(&target, &path) {
        Ok(()) => Ok(Value::Undefined),
        Err(e) => Err(sys_err(vm, &e, "symlink", &path)),
    }
}

framed!(access_sync, "accessSync", access_sync_);

fn access_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let path = to_path(vm, &a.arg(0))?;
    match std::fs::metadata(&path) {
        Ok(_) => Ok(Value::Undefined),
        Err(e) => Err(sys_err(vm, &e, "access", &path)),
    }
}

fn mode_bits(m: f64) -> u32 {
    if m.is_nan() {
        0
    } else {
        m as u32
    }
}

framed!(chmod_sync, "chmodSync", chmod_sync_);

fn chmod_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let path = to_path(vm, &a.arg(0))?;
    let m = num_or_zero(vm, &a.arg(1))?;
    match std::fs::set_permissions(&path, std::fs::Permissions::from_mode(mode_bits(m))) {
        Ok(()) => Ok(Value::Undefined),
        Err(e) => Err(sys_err(vm, &e, "chmod", &path)),
    }
}

fn utimes_common(vm: &mut Vm, a: &Args, nofollow: bool) -> JsResult<Value> {
    let path = to_path(vm, &a.arg(0))?;
    let at = unix_seconds(vm, &a.arg(1))?;
    let mt = unix_seconds(vm, &a.arg(2))?;
    match set_times(&path, at, mt, nofollow) {
        Ok(()) => Ok(Value::Undefined),
        Err(e) => Err(sys_err(vm, &e, if nofollow { "lutime" } else { "utime" }, &path)),
    }
}

framed!(utimes_sync, "utimesSync", utimes_sync_);

fn utimes_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    utimes_common(vm, a, false)
}

framed!(lutimes_sync, "lutimesSync", lutimes_sync_);

fn lutimes_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    utimes_common(vm, a, true)
}

framed!(mkdtemp_sync, "mkdtempSync", mkdtemp_sync_);

fn mkdtemp_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let prefix = to_path(vm, &a.arg(0))?;
    let dir = mkdtemp_impl(vm, &prefix)?;
    let enc = enc_of(vm, &a.arg(1))?;
    if is_buffer_enc(&enc) {
        return new_buffer(vm, dir.into_bytes());
    }
    Ok(Value::str(&dir))
}

fn realpath_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let path = to_path(vm, &a.arg(0))?;
    Ok(Value::str(&realpath_impl(&path)))
}

fn statfs_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let path = to_path(vm, &a.arg(0))?;
    match statfs_values(&path) {
        Ok(v) => {
            let names = ["type", "bsize", "blocks", "bfree", "bavail", "files", "ffree"];
            let o = vm.new_object();
            for (i, n) in names.iter().enumerate() {
                o.set_prop(key(n), Value::Num(v[i]), WEC);
            }
            Ok(Value::Obj(o))
        }
        Err(e) => Err(sys_err(vm, &e, "statfs", &path)),
    }
}

fn open_impl(vm: &mut Vm, p: &Value, flags: &Value) -> JsResult<Value> {
    let path = to_path(vm, p)?;
    let fd = open_fd(vm, &path, flag_mode(flags))?;
    Ok(Value::Num(fd as f64))
}

fn open_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    open_impl(vm, &a.arg(0), &a.arg(1))
}

fn close_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let n = vm.to_number(&a.arg(0))?;
    close_fd_num(n);
    Ok(Value::Undefined)
}

/// `for (const buf of buffers)` (the reference engine words a nullish iterable this way)
fn buffer_list(vm: &mut Vm, buffers: &Value) -> JsResult<Vec<Value>> {
    if buffers.is_nullish() {
        let what = if buffers.is_null() { "null" } else { "undefined" };
        return vm.throw_type(format!("cannot read property '\u{0}1' of {}", what));
    }
    vm.iterate_to_vec(buffers)
}

fn fstat_impl(vm: &mut Vm, fdv: &Value) -> JsResult<Value> {
    let r = with_fd(vm, fdv, |f| f.metadata())?;
    match r {
        Ok(md) => {
            let raw = raw_stat(&md);
            Ok(make_stats(vm, &raw))
        }
        Err(e) => Err(plain_err(vm, &format!("fstat 'fd': {}", e))),
    }
}

framed!(fstat_sync, "fstatSync", fstat_sync_);

fn fstat_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    fstat_impl(vm, &a.arg(0))
}

fn ftruncate_impl(vm: &mut Vm, fdv: &Value, len: &Value) -> JsResult<Value> {
    let n = num_or_zero(vm, len)?;
    let len = if n.is_nan() || n <= 0.0 { 0 } else { n as u64 };
    fd_op(vm, fdv, "ftruncate", |f| f.set_len(len))
}

framed!(ftruncate_sync, "ftruncateSync", ftruncate_sync_);

fn ftruncate_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    ftruncate_impl(vm, &a.arg(0), &a.arg(1))
}

fn truncate_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = a.arg(0);
    if let Value::Num(_) = p {
        return with_frames(vm, &["ftruncateSync"], |vm| ftruncate_impl(vm, &p, &a.arg(1)));
    }
    with_frames(vm, &["truncateSync"], |vm| {
        let fd = open_impl(vm, &p, &Value::str("r+"))?;
        let r = with_frames(vm, &["ftruncateSync"], |vm| ftruncate_impl(vm, &fd, &a.arg(1)));
        if let Value::Num(n) = fd {
            close_fd_num(n);
        }
        r
    })
}

framed!(fsync_sync, "fsyncSync", fsync_sync_);

fn fsync_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    fd_op(vm, &a.arg(0), "fsync", |f| f.sync_all())
}

framed!(fdatasync_sync, "fdatasyncSync", fdatasync_sync_);

fn fdatasync_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    fd_op(vm, &a.arg(0), "fdatasync", |f| f.sync_data())
}

framed!(fchmod_sync, "fchmodSync", fchmod_sync_);

fn fchmod_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = num_or_zero(vm, &a.arg(1))?;
    let bits = mode_bits(m);
    fd_op(vm, &a.arg(0), "fchmod", |f| f.set_permissions(std::fs::Permissions::from_mode(bits)))
}

framed!(futimes_sync, "futimesSync", futimes_sync_);

fn futimes_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let at = unix_seconds(vm, &a.arg(1))?;
    let mt = unix_seconds(vm, &a.arg(2))?;
    fd_op(vm, &a.arg(0), "futime", |f| {
        use std::os::unix::io::AsRawFd;
        let ts = [timespec(at), timespec(mt)];
        let r = unsafe { futimens(f.as_raw_fd(), ts.as_ptr()) };
        if r != 0 {
            return Err(std::io::Error::last_os_error());
        }
        Ok(())
    })
}

framed!(fchown_sync, "fchownSync", fchown_sync_);

fn fchown_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (u, g) = chown_args(vm, &a.arg(1), &a.arg(2))?;
    fd_op(vm, &a.arg(0), "fchown", |f| std::os::unix::fs::fchown(&*f, Some(u), Some(g)))
}

framed!(chown_sync, "chownSync", chown_sync_);

fn chown_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let path = to_path(vm, &a.arg(0))?;
    let (u, g) = chown_args(vm, &a.arg(1), &a.arg(2))?;
    match std::os::unix::fs::chown(&path, Some(u), Some(g)) {
        Ok(()) => Ok(Value::Undefined),
        Err(e) => Err(sys_err(vm, &e, "chown", &path)),
    }
}

framed!(lchown_sync, "lchownSync", lchown_sync_);

fn lchown_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let path = to_path(vm, &a.arg(0))?;
    let (u, g) = chown_args(vm, &a.arg(1), &a.arg(2))?;
    match std::os::unix::fs::lchown(&path, Some(u), Some(g)) {
        Ok(()) => Ok(Value::Undefined),
        Err(e) => Err(sys_err(vm, &e, "lchown", &path)),
    }
}

framed!(lchmod_sync, "lchmodSync", lchmod_sync_);

fn lchmod_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let path = to_path(vm, &a.arg(0))?;
    num_or_zero(vm, &a.arg(1))?;
    Err(plain_err(vm, &format!("ENOSYS: lchmod is not supported on this platform, lchmod '{}'", path)))
}

/// TypedArray.prototype.set(bytes, offset) as used by readSync.
fn store_bytes(vm: &mut Vm, target: &Value, bytes: &[u8], offset: f64) -> JsResult<()> {
    let info = match target {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::TypedArray(t) => Some((t.kind, t.len())),
            _ => None,
        },
        _ => None,
    };
    let (kind, len) = match info {
        Some(x) => x,
        None => {
            if matches!(target, Value::Obj(o) if matches!(o.borrow().kind, ObjKind::DataView(_))) {
                return vm.throw_type("(intermediate value).set is not a function");
            }
            let arr = crate::builtins::typedarray::typed_array_from_bytes(vm, bytes.to_vec());
            let set = getp(vm, target, "set")?;
            if !set.is_callable() {
                return vm.throw_type("undefined is not a function");
            }
            vm.call(&set, target.clone(), &[Value::Obj(arr), Value::Num(offset)])?;
            return Ok(());
        }
    };
    let off = if offset.is_nan() { 0.0 } else { offset.trunc() };
    if off < 0.0 {
        return vm.throw_range("TypedArray.prototype.set offset is negative");
    }
    if off + bytes.len() as f64 > len as f64 {
        return vm.throw_range("source is too large for the target at offset");
    }
    let o = target.as_obj().unwrap().clone();
    let start = off as usize;
    if matches!(kind, TAKind::Uint8 | TAKind::Int8 | TAKind::Uint8C) {
        crate::runtime::buffer::write_bytes(&o, start, bytes);
    } else {
        for (i, b) in bytes.iter().enumerate() {
            crate::builtins::typedarray::ta_set_index(vm, &o, (start + i) as f64, &Value::Num(*b as f64))?;
        }
    }
    Ok(())
}

fn is_plain_object(v: &Value) -> bool {
    match v {
        Value::Obj(o) => !o.is_callable(),
        _ => false,
    }
}

fn is_view(v: &Value) -> bool {
    matches!(v, Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_) | ObjKind::DataView(_)))
}

/// `buffer.length - offset` with JS semantics (BigInt offsets throw the mixing TypeError).
fn length_minus(vm: &mut Vm, buffer: &Value, offset: &Value) -> JsResult<f64> {
    let bl = getp(vm, buffer, "length")?;
    let d = vm.op_arith(crate::bytecode::Op::Sub, &bl, offset)?;
    to_num(vm, &d)
}

fn read_sync_impl(vm: &mut Vm, fd: &Value, buffer: &Value, offset: &Value, length: &Value, position: &Value) -> JsResult<Value> {
    let (mut offset, mut length, mut position) = (offset.clone(), length.clone(), position.clone());
    if is_plain_object(&offset) {
        let o = offset.clone();
        let off = getp(vm, &o, "offset")?;
        offset = if off.truthy() { off } else { Value::Num(0.0) };
        let l = getp(vm, &o, "length")?;
        length = if l.is_nullish() { Value::Num(length_minus(vm, buffer, &offset)?) } else { l };
        let p = getp(vm, &o, "position")?;
        position = if p.is_nullish() { Value::Null } else { p };
    }
    let offset = if offset.truthy() { offset } else { Value::Num(0.0) };
    let len = if length.is_nullish() { length_minus(vm, buffer, &offset)? } else { len_arg(vm, &length)? };
    let off = to_num(vm, &offset)?;
    let len = if len.is_nan() || len <= 0.0 { 0.0 } else { len.trunc() };
    let pos = pos_arg(&position);
    let bytes = pread(vm, fd, len, pos)?;
    store_bytes(vm, buffer, &bytes, off)?;
    Ok(Value::Num(bytes.len() as f64))
}

framed!(read_sync, "readSync", read_sync_);

fn read_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    read_sync_impl(vm, &a.arg(0), &a.arg(1), &a.arg(2), &a.arg(3), &a.arg(4))
}

fn write_sync_impl(vm: &mut Vm, fd: &Value, data: &Value, x: &Value, y: &Value, z: &Value) -> JsResult<Value> {
    if let Value::Str(_) = data {
        let pos = pos_arg(x);
        let bytes = to_buffer_framed(vm, "writeSync", data, y)?;
        let n = pwrite(vm, fd, &bytes, pos)?;
        return Ok(Value::Num(n as f64));
    }
    let buf = to_buffer_framed(vm, "writeSync", data, &Value::Undefined)?;
    let offv = if x.truthy() { x.clone() } else { Value::Num(0.0) };
    let len = if y.is_nullish() {
        let d = vm.op_arith(crate::bytecode::Op::Sub, &Value::Num(buf.len() as f64), &offv)?;
        to_num(vm, &d)?
    } else {
        to_num(vm, y)?
    };
    let off = to_num(vm, &offv)?;
    let pos = pos_arg(z);
    // buf.subarray(offset, offset + length)
    let n = buf.len() as f64;
    let clamp = |v: f64| -> usize {
        let v = if v.is_nan() { 0.0 } else { v.trunc() };
        let v = if v < 0.0 { (n + v).max(0.0) } else { v.min(n) };
        v as usize
    };
    let start = clamp(off);
    let end = clamp(off + len).max(start);
    let w = pwrite(vm, fd, &buf[start..end], pos)?;
    Ok(Value::Num(w as f64))
}

fn write_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    write_sync_impl(vm, &a.arg(0), &a.arg(1), &a.arg(2), &a.arg(3), &a.arg(4))
}

fn readv_sync_impl(vm: &mut Vm, fd: &Value, buffers: &Value, position: &Value) -> JsResult<Value> {
    let mut total = 0.0;
    let mut pos = pos_arg(position);
    let list = buffer_list(vm, buffers)?;
    for buf in list {
        let bl = getp(vm, &buf, "length")?;
        let bl = to_num(vm, &bl)?;
        let bytes = pread(vm, fd, bl, pos)?;
        if bytes.is_empty() {
            break;
        }
        store_bytes(vm, &buf, &bytes, 0.0)?;
        total += bytes.len() as f64;
        if pos >= 0.0 {
            pos += bytes.len() as f64;
        }
    }
    Ok(Value::Num(total))
}

framed!(readv_sync, "readvSync", readv_sync_);

fn readv_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    readv_sync_impl(vm, &a.arg(0), &a.arg(1), &a.arg(2))
}

fn writev_sync_impl(vm: &mut Vm, fd: &Value, buffers: &Value, position: &Value) -> JsResult<Value> {
    let mut total = 0.0;
    let mut pos = pos_arg(position);
    let list = buffer_list(vm, buffers)?;
    for buf in list {
        // the native write takes typed arrays as raw memory and anything else as String(x)
        with_fd(vm, fd, |_| ())?;
        let bytes = match &buf {
            Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_)) => ta_bytes(o),
            _ => vm.to_string(&buf)?.to_rust_string().into_bytes(),
        };
        let n = pwrite(vm, fd, &bytes, pos)? as f64;
        total += n;
        if pos >= 0.0 {
            pos += n;
        }
    }
    Ok(Value::Num(total))
}

framed!(writev_sync, "writevSync", writev_sync_);

fn writev_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    writev_sync_impl(vm, &a.arg(0), &a.arg(1), &a.arg(2))
}

// ============================================================================================
// cp / opendir / glob
// ============================================================================================

/// path.join for two segments (normalising like Node)
fn path_join(a: &str, b: &str) -> String {
    let joined = if a.is_empty() {
        b.to_string()
    } else if b.is_empty() {
        a.to_string()
    } else {
        format!("{}/{}", a, b)
    };
    normalize_path(&joined)
}

fn normalize_path(p: &str) -> String {
    if p.is_empty() {
        return ".".into();
    }
    let abs = p.starts_with('/');
    let trailing = p.ends_with('/');
    let mut parts: Vec<&str> = Vec::new();
    for seg in p.split('/') {
        if seg.is_empty() || seg == "." {
            continue;
        }
        if seg == ".." {
            if !parts.is_empty() && *parts.last().unwrap() != ".." {
                parts.pop();
            } else if !abs {
                parts.push("..");
            }
            continue;
        }
        parts.push(seg);
    }
    let mut out = parts.join("/");
    if out.is_empty() && !abs {
        out = ".".into();
    }
    if trailing && !out.is_empty() {
        out.push('/');
    }
    if abs {
        format!("/{}", out)
    } else {
        out
    }
}

fn parent_dir(p: &str) -> String {
    let t = p.trim_end_matches('/');
    match t.rfind('/') {
        Some(0) => "/".into(),
        Some(i) => t[..i].to_string(),
        None => ".".into(),
    }
}

fn cp_rec(vm: &mut Vm, src: &str, raw_src: &Value, dest: &str, opts: &Value, nested: bool) -> JsResult<()> {
    with_frames(vm, &["cpSyncImpl"], |vm| cp_step(vm, src, raw_src, dest, opts, nested))
}

fn cp_step(vm: &mut Vm, src: &str, raw_src: &Value, dest: &str, opts: &Value, nested: bool) -> JsResult<()> {
    let md = match std::fs::symlink_metadata(src) {
        Ok(m) => m,
        Err(e) => return with_frames(vm, &["lstatSync"], |vm| Err(sys_err(vm, &e, "lstat", src))),
    };
    if md.is_dir() {
        if !getp(vm, opts, "recursive")?.truthy() {
            return with_frames(vm, &["fsError"], |vm| Err(js_err_raw(vm, "EISDIR", "cp", raw_src, "recursive option not set for a directory")?));
        }
        with_frames(vm, &["mkdirSync"], |vm| mkdir_impl(vm, dest, true))?;
        // each nested directory costs a JS call frame in the reference (deep recursion ends in
        // "Maximum call stack size exceeded")
        vm.enter()?;
        let r = (|| -> JsResult<()> {
            let names = with_frames(vm, &["readdirSync"], |vm| readdir_names(vm, src))?;
            for name in names {
                let s = path_join(src, &name);
                let d = path_join(dest, &name);
                cp_rec(vm, &s, &Value::str(&s), &d, opts, true)?;
            }
            Ok(())
        })();
        vm.depth -= 1;
        return r;
    }
    if md.file_type().is_symlink() && !getp(vm, opts, "dereference")?.truthy() {
        let target = match std::fs::read_link(src) {
            Ok(t) => t,
            Err(e) => return Err(sys_err(vm, &e, "readlink", src)),
        };
        let _ = std::fs::create_dir_all(parent_dir(dest));
        let _ = std::fs::remove_file(dest);
        if let Err(e) = std::os::unix::fs::symlink(&target, dest) {
            return with_frames(vm, &["symlinkSync"], |vm| Err(sys_err(vm, &e, "symlink", dest)));
        }
        return Ok(());
    }
    let filter = getp(vm, opts, "filter")?;
    if filter.truthy() {
        let keep = vm.call(&filter, opts.clone(), &[Value::str(src), Value::str(dest)])?;
        if !keep.truthy() {
            return Ok(());
        }
    }
    if std::fs::symlink_metadata(dest).is_ok() {
        let force = getp(vm, opts, "force")?;
        if matches!(force, Value::Bool(false)) {
            if getp(vm, opts, "errorOnExist")?.truthy() {
                return with_frames(vm, &["fsError"], |vm| Err(js_err(vm, "ERR_FS_CP_EEXIST", "cp", dest, "destination already exists")));
            }
            return Ok(());
        }
    }
    let _ = std::fs::create_dir_all(parent_dir(dest));
    vm.enter()?;
    let r = std::fs::copy(src, dest);
    vm.depth -= 1;
    match r {
        Ok(_) => Ok(()),
        // the reference's error path breaks for over-long destinations inside a directory copy
        Err(e) if nested && e.raw_os_error() == Some(36) => vm.throw_type("value is not a function"),
        Err(e) => with_frames(vm, &["copyFileSync"], |vm| Err(sys_err(vm, &e, "copyfile", src))),
    }
}

const CP_FRAMES: usize = 5;

fn cp_impl(vm: &mut Vm, src: &Value, dest: &Value, opts: &Value) -> JsResult<Value> {
    let s = to_path(vm, src)?;
    let d = to_path(vm, dest)?;
    let o = if opts.truthy() { opts.clone() } else { Value::Obj(vm.new_object()) };
    // the reference's cpSync → cpSyncImpl layers use a few JS frames before recursing
    let saved = vm.depth;
    for _ in 0..CP_FRAMES {
        vm.enter()?;
    }
    let r = cp_rec(vm, &s, src, &d, &o, false);
    vm.depth = saved;
    r?;
    Ok(Value::Undefined)
}

framed!(cp_sync, ["<anonymous>"], cp_sync_);

fn cp_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    cp_impl(vm, &a.arg(0), &a.arg(1), &a.arg(2))
}

fn opendir_impl(vm: &mut Vm, p: &Value) -> JsResult<Value> {
    with_frames(vm, &["opendirSyncImpl"], |vm| opendir_inner(vm, p))
}

fn opendir_inner(vm: &mut Vm, p: &Value) -> JsResult<Value> {
    let path = to_path(vm, p)?;
    let entries = dirents_of(vm, &path)?;
    let proto = class_proto(vm, |c| c.dir.clone());
    let o = Obj::new(Some(proto), ObjKind::Ordinary);
    let arr = vm.new_array(entries);
    o.set_prop(key("path"), Value::str(&path), WEC);
    o.set_prop(key("_entries"), Value::Obj(arr), WEC);
    o.set_prop(key("_i"), Value::Num(0.0), WEC);
    o.set_prop(key("_closed"), Value::Bool(false), WEC);
    Ok(Value::Obj(o))
}

fn opendir_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    opendir_impl(vm, &a.arg(0))
}

#[derive(Clone)]
enum GTok {
    Lit(char),
    Star,
    Any,
    Opt,
    One,
    Class(Vec<(char, char)>, bool),
    Never,
}

fn glob_compile(p: &str) -> Vec<GTok> {
    let cs: Vec<char> = p.chars().collect();
    let mut out = Vec::new();
    let mut i = 0;
    while i < cs.len() {
        let c = cs[i];
        match c {
            '*' => {
                if i + 1 < cs.len() && cs[i + 1] == '*' {
                    if i + 2 < cs.len() && cs[i + 2] == '/' {
                        out.push(GTok::Opt);
                        i += 3;
                    } else {
                        out.push(GTok::Any);
                        i += 2;
                    }
                } else {
                    out.push(GTok::Star);
                    i += 1;
                }
            }
            '?' => {
                out.push(GTok::One);
                i += 1;
            }
            '[' => {
                let close = cs[i + 1..].iter().position(|&x| x == ']').map(|k| k + i + 1);
                match close {
                    None => {
                        out.push(GTok::Lit('['));
                        i += 1;
                    }
                    Some(end) => {
                        let mut body = &cs[i + 1..end];
                        let mut neg = false;
                        if let Some(&f) = body.first() {
                            if f == '!' || f == '^' {
                                neg = true;
                                body = &body[1..];
                            }
                        }
                        if body.is_empty() && !neg {
                            out.push(GTok::Never);
                        } else {
                            let mut ranges = Vec::new();
                            let mut k = 0;
                            while k < body.len() {
                                if k + 2 < body.len() && body[k + 1] == '-' {
                                    ranges.push((body[k], body[k + 2]));
                                    k += 3;
                                } else {
                                    ranges.push((body[k], body[k]));
                                    k += 1;
                                }
                            }
                            out.push(GTok::Class(ranges, neg));
                        }
                        i = end + 1;
                    }
                }
            }
            _ => {
                out.push(GTok::Lit(c));
                i += 1;
            }
        }
    }
    out
}

fn glob_match(toks: &[GTok], s: &[char]) -> bool {
    match toks.first() {
        None => s.is_empty(),
        Some(GTok::Lit(c)) => !s.is_empty() && s[0] == *c && glob_match(&toks[1..], &s[1..]),
        Some(GTok::One) => !s.is_empty() && s[0] != '/' && glob_match(&toks[1..], &s[1..]),
        Some(GTok::Never) => false,
        Some(GTok::Class(ranges, neg)) => {
            if s.is_empty() {
                return false;
            }
            let hit = ranges.iter().any(|(a, b)| s[0] >= *a && s[0] <= *b);
            hit != *neg && glob_match(&toks[1..], &s[1..])
        }
        Some(GTok::Star) => {
            for k in 0..=s.len() {
                if k > 0 && s[k - 1] == '/' {
                    break;
                }
                if glob_match(&toks[1..], &s[k..]) {
                    return true;
                }
            }
            false
        }
        Some(GTok::Any) => (0..=s.len()).any(|k| glob_match(&toks[1..], &s[k..])),
        Some(GTok::Opt) => glob_match(&toks[1..], s) || (0..s.len()).any(|k| s[k] == '/' && glob_match(&toks[1..], &s[k + 1..])),
    }
}

struct GlobCtx {
    pats: Vec<Vec<GTok>>,
    opts: Value,
    exclude: Value,
    with_types: bool,
    cwd: String,
    out: Vec<Value>,
}

fn glob_walk(vm: &mut Vm, ctx: &mut GlobCtx, dir: &str, rel: &str) -> JsResult<()> {
    let entries: Vec<(String, &'static str)> = match std::fs::read_dir(dir) {
        Ok(rd) => rd
            .filter_map(|e| e.ok())
            .map(|e| {
                let k = e.file_type().map(|ft| kind_of(&ft)).unwrap_or("other");
                (name_of(&e), k)
            })
            .collect(),
        Err(_) => return Ok(()),
    };
    for (name, kind) in entries {
        let relpath = if rel.is_empty() { name.clone() } else { format!("{}/{}", rel, name) };
        let chars: Vec<char> = relpath.chars().collect();
        if ctx.pats.iter().any(|p| glob_match(p, &chars)) {
            let item = if ctx.with_types {
                let parent = if rel.is_empty() { ctx.cwd.clone() } else { path_join(&ctx.cwd, rel) };
                make_dirent(vm, Value::str(&name), kind, &parent)
            } else {
                Value::str(&relpath)
            };
            let excluded = if ctx.exclude.is_callable() {
                let ex = ctx.exclude.clone();
                vm.call(&ex, ctx.opts.clone(), &[item.clone()])?.truthy()
            } else {
                false
            };
            if !excluded {
                ctx.out.push(item);
            }
        }
        if kind == "dir" {
            let child = format!("{}/{}", dir.trim_end_matches('/'), name);
            glob_walk(vm, ctx, &child, &relpath)?;
        }
    }
    Ok(())
}

fn glob_impl(vm: &mut Vm, pattern: &Value, options: &Value) -> JsResult<Vec<Value>> {
    with_frames(vm, &["globSyncImpl"], |vm| glob_inner(vm, pattern, options))
}

fn glob_inner(vm: &mut Vm, pattern: &Value, options: &Value) -> JsResult<Vec<Value>> {
    let pats = if crate::builtins::array::is_array(vm, pattern)? { crate::builtins::array::array_like_to_vec(vm, pattern)? } else { vec![pattern.clone()] };
    let mut compiled = Vec::new();
    for p in &pats {
        match p {
            Value::Str(s) => compiled.push(glob_compile(&s.to_rust_string())),
            Value::Undefined | Value::Null => {
                with_frames(vm, &["globToRegExp"], |vm| getp(vm, p, "length"))?;
            }
            _ => compiled.push(vec![GTok::Never]),
        }
    }
    let cwdv = opt_get(vm, options, "cwd")?;
    let cwd = if cwdv.is_nullish() || !options.truthy() {
        std::env::current_dir().map(|p| p.to_string_lossy().into_owned()).unwrap_or_default()
    } else {
        to_path(vm, &cwdv)?
    };
    let exclude = opt_get(vm, options, "exclude")?;
    let with_types = opt_get(vm, options, "withFileTypes")?.truthy();
    let mut ctx = GlobCtx { pats: compiled, opts: options.clone(), exclude, with_types, cwd: cwd.clone(), out: Vec::new() };
    let root = if cwd.is_empty() { ".".to_string() } else { cwd };
    glob_walk(vm, &mut ctx, &root, "")?;
    Ok(ctx.out)
}

fn glob_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = glob_impl(vm, &a.arg(0), &a.arg(1))?;
    Ok(Value::Obj(vm.new_array(v)))
}

// ============================================================================================
// async iterators (fs.promises.glob, Dir[Symbol.asyncIterator])
// ============================================================================================

struct ListIter {
    items: RefCell<VecDeque<Value>>,
    dir: Option<Value>,
    done: Cell<bool>,
}

fn new_list_iter(vm: &mut Vm, items: Vec<Value>, dir: Option<Value>) -> Value {
    let proto = if dir.is_some() { class_proto(vm, |c| c.dir_iter.clone()) } else { class_proto(vm, |c| c.list_iter.clone()) };
    let st = ListIter { items: RefCell::new(items.into_iter().collect()), dir, done: Cell::new(false) };
    Value::Obj(Obj::new(Some(proto), ObjKind::Host(Box::new(st))))
}

fn list_iter_state<R>(v: &Value, f: impl FnOnce(&ListIter) -> R) -> Option<R> {
    match v {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Host(h) => h.downcast_ref::<ListIter>().map(f),
            _ => None,
        },
        _ => None,
    }
}

fn list_iter_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = list_iter_state(&a.this, |s| (s.done.get(), s.dir.clone(), s.items.borrow_mut().pop_front()));
    let (done, dir, item) = match st {
        Some(x) => x,
        None => {
            let e = vm.make_error("TypeError", "next method called on incompatible receiver");
            return Ok(rejected(vm, e));
        }
    };
    if done {
        let r = iter_result(vm, Value::Undefined, true);
        return Ok(resolved(vm, r));
    }
    let next = match dir {
        Some(d) => match call_method(vm, &d, "readSync", &[]) {
            Ok(v) => {
                if v.is_null() {
                    None
                } else {
                    Some(v)
                }
            }
            Err(e) => {
                list_iter_state(&a.this, |s| s.done.set(true));
                return Ok(rejected(vm, e));
            }
        },
        None => item,
    };
    match next {
        Some(v) => {
            // an async generator's `yield v` awaits v first: the result settles one tick later
            let r = iter_result(vm, v, false);
            let cap = vm.new_promise_capability_intrinsic();
            let data = Value::Obj(vm.new_array(vec![cap.resolve.clone(), r]));
            vm.jobs.push_back(Job::Native(settle_later_job, data));
            Ok(cap.promise)
        }
        None => {
            list_iter_state(&a.this, |s| s.done.set(true));
            let r = iter_result(vm, Value::Undefined, true);
            Ok(resolved(vm, r))
        }
    }
}

fn settle_later_job(vm: &mut Vm, data: Value) -> JsResult<()> {
    let parts = crate::builtins::array::array_like_to_vec(vm, &data)?;
    if parts.len() == 2 {
        vm.call(&parts[0], Value::Undefined, &[parts[1].clone()])?;
    }
    Ok(())
}

fn list_iter_return(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    list_iter_state(&a.this, |s| s.done.set(true));
    let r = iter_result(vm, a.arg(0), true);
    let cap = vm.new_promise_capability_intrinsic();
    let data = Value::Obj(vm.new_array(vec![cap.resolve.clone(), r]));
    vm.jobs.push_back(Job::Native(settle_later_job, data));
    Ok(cap.promise)
}

fn list_iter_throw(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    list_iter_state(&a.this, |s| s.done.set(true));
    Ok(rejected(vm, a.arg(0)))
}

// ============================================================================================
// Dir / StatWatcher / FileHandle classes
// ============================================================================================

fn dir_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = instance(vm, a, |c| c.dir.clone())?;
    o.set_prop(key("path"), a.arg(0), WEC);
    o.set_prop(key("_entries"), a.arg(1), WEC);
    o.set_prop(key("_i"), Value::Num(0.0), WEC);
    o.set_prop(key("_closed"), Value::Bool(false), WEC);
    Ok(Value::Obj(o))
}

/// next entry or null (advancing `_i`)
fn dir_next(vm: &mut Vm, this: &Value) -> JsResult<Value> {
    let i = getp(vm, this, "_i")?;
    let entries = getp(vm, this, "_entries")?;
    let len = getp(vm, &entries, "length")?;
    let iv = to_num(vm, &i)?;
    let lv = to_num(vm, &len)?;
    if !(iv < lv) {
        return Ok(Value::Null);
    }
    let e = vm.get_elem(&entries, &Value::Num(iv))?;
    setp(vm, this, "_i", Value::Num(iv + 1.0))?;
    Ok(e)
}

fn dir_read_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    dir_next(vm, &a.this)
}

fn dir_read(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let next = dir_next(vm, &a.this)?;
    let cb = a.arg(0);
    if cb.truthy() {
        let t = closure(vm, "", 0, tick_cb_args, vec![cb, Value::Null, next]);
        next_tick(vm, t)?;
        return Ok(Value::Undefined);
    }
    Ok(resolved(vm, next))
}

fn dir_close_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    setp(vm, &a.this, "_closed", Value::Bool(true))?;
    Ok(Value::Undefined)
}

fn dir_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    setp(vm, &a.this, "_closed", Value::Bool(true))?;
    let cb = a.arg(0);
    if cb.truthy() {
        let t = closure(vm, "", 0, tick_cb_args, vec![cb, Value::Null]);
        next_tick(vm, t)?;
        return Ok(Value::Undefined);
    }
    Ok(resolved(vm, Value::Undefined))
}

fn dir_async_iter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(new_list_iter(vm, Vec::new(), Some(a.this.clone())))
}

// tick body: cb(...slots[1..])
framed!(tick_cb_args, ["<anonymous>"], tick_cb_args_);

fn tick_cb_args_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cb = a.slot(0);
    let mut args = Vec::new();
    let n = match &a.callee.borrow().kind {
        ObjKind::Native(nf) => nf.slots.len(),
        _ => 0,
    };
    for i in 1..n {
        args.push(a.slot(i));
    }
    call_cb(vm, &cb, &args)?;
    Ok(Value::Undefined)
}

fn stat_watcher_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = instance(vm, a, |c| c.stat_watcher.clone())?;
    crate::runtime::events::init_emitter(vm, &o);
    o.set_prop(key("_handle"), Value::Null, WEC);
    Ok(Value::Obj(o))
}

fn new_stat_watcher(vm: &mut Vm) -> Obj {
    let proto = class_proto(vm, |c| c.stat_watcher.clone());
    let o = Obj::new(Some(proto), ObjKind::Ordinary);
    crate::runtime::events::init_emitter(vm, &o);
    o.set_prop(key("_handle"), Value::Null, WEC);
    o
}

fn file_handle_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = instance(vm, a, |c| c.file_handle.clone())?;
    o.set_prop(key("fd"), a.arg(0), WEC);
    Ok(Value::Obj(o))
}

fn new_file_handle(vm: &mut Vm, fd: Value) -> Value {
    let proto = class_proto(vm, |c| c.file_handle.clone());
    let o = Obj::new(Some(proto), ObjKind::Ordinary);
    o.set_prop(key("fd"), fd, WEC);
    Value::Obj(o)
}

fn fh_fd(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    getp(vm, &a.this, "fd")
}

fn result_obj(vm: &mut Vm, k1: &str, v1: Value, k2: &str, v2: Value) -> Value {
    Value::Obj(vm.obj_from(vec![(k1, v1), (k2, v2)]))
}

framed!(fh_read, ["read", "<anonymous>"], fh_read_);

fn fh_read_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| -> JsResult<Value> {
        let (mut buffer, mut offset, mut length, mut position) = (a.arg(0), a.arg(1), a.arg(2), a.arg(3));
        if is_plain_object(&buffer) && !is_view(&buffer) {
            let o = buffer.clone();
            let b = getp(vm, &o, "buffer")?;
            buffer = if b.truthy() { b } else { new_buffer(vm, vec![0; 16384])? };
            let off = getp(vm, &o, "offset")?;
            offset = if off.truthy() { off } else { Value::Num(0.0) };
            let l = getp(vm, &o, "length")?;
            length = if l.is_nullish() { Value::Num(length_minus(vm, &buffer, &offset)?) } else { l };
            let p = getp(vm, &o, "position")?;
            position = if p.is_nullish() { Value::Null } else { p };
        }
        let fd = fh_fd(vm, a)?;
        let n = with_frames(vm, &["readSync"], |vm| read_sync_impl(vm, &fd, &buffer, &offset, &length, &position))?;
        Ok(result_obj(vm, "bytesRead", n, "buffer", buffer))
    })();
    Ok(settle(vm, r))
}

framed!(fh_write, ["write", "<anonymous>"], fh_write_);

fn fh_write_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| -> JsResult<Value> {
        let fd = fh_fd(vm, a)?;
        let n = write_sync_impl(vm, &fd, &a.arg(0), &a.arg(1), &a.arg(2), &a.arg(3))?;
        Ok(result_obj(vm, "bytesWritten", n, "buffer", a.arg(0)))
    })();
    Ok(settle(vm, r))
}

framed!(fh_readv, ["readv", "<anonymous>"], fh_readv_);

fn fh_readv_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| -> JsResult<Value> {
        let fd = fh_fd(vm, a)?;
        let n = with_frames(vm, &["readvSync"], |vm| readv_sync_impl(vm, &fd, &a.arg(0), &a.arg(1)))?;
        Ok(result_obj(vm, "bytesRead", n, "buffers", a.arg(0)))
    })();
    Ok(settle(vm, r))
}

framed!(fh_writev, ["writev", "<anonymous>"], fh_writev_);

fn fh_writev_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| -> JsResult<Value> {
        let fd = fh_fd(vm, a)?;
        let n = with_frames(vm, &["writevSync"], |vm| writev_sync_impl(vm, &fd, &a.arg(0), &a.arg(1)))?;
        Ok(result_obj(vm, "bytesWritten", n, "buffers", a.arg(0)))
    })();
    Ok(settle(vm, r))
}

framed!(fh_read_file, ["readFile", "<anonymous>"], fh_read_file_);

fn fh_read_file_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| -> JsResult<Value> {
        let fd = fh_fd(vm, a)?;
        let bytes = with_frames(vm, &["readvBytes"], |vm| readv_bytes_impl(vm, &fd))?;
        finish_read(vm, bytes, &a.arg(0))
    })();
    Ok(settle(vm, r))
}

framed!(fh_write_file, ["writeFile", "<anonymous>"], fh_write_file_);

fn fh_write_file_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| -> JsResult<Value> {
        let fd = fh_fd(vm, a)?;
        let enc = enc_of(vm, &a.arg(1))?;
        let b = to_buffer_framed(vm, "", &a.arg(0), &enc)?;
        let buf = new_buffer(vm, b)?;
        write_sync_impl(vm, &fd, &buf, &Value::Num(0.0), &Value::Undefined, &Value::Null)?;
        Ok(Value::Undefined)
    })();
    Ok(settle(vm, r))
}

framed!(fh_append_file, ["appendFile", "<anonymous>"], fh_append_file_);

fn fh_append_file_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| -> JsResult<Value> {
        let fd = fh_fd(vm, a)?;
        let enc = enc_of(vm, &a.arg(1))?;
        let b = to_buffer_framed(vm, "", &a.arg(0), &enc)?;
        let buf = new_buffer(vm, b)?;
        write_sync_impl(vm, &fd, &buf, &Value::Undefined, &Value::Undefined, &Value::Undefined)?;
        Ok(Value::Undefined)
    })();
    Ok(settle(vm, r))
}

framed!(fh_chmod, ["promisedCall", "<anonymous>", "fchmodSync"], fh_chmod_);

fn fh_chmod_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| -> JsResult<Value> {
        let fd = fh_fd(vm, a)?;
        let m = num_or_zero(vm, &a.arg(0))?;
        let bits = mode_bits(m);
        fd_op(vm, &fd, "fchmod", |f| f.set_permissions(std::fs::Permissions::from_mode(bits)))
    })();
    Ok(settle(vm, r))
}

framed!(fh_chown, ["promisedCall", "<anonymous>", "fchownSync"], fh_chown_);

fn fh_chown_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| -> JsResult<Value> {
        let fd = fh_fd(vm, a)?;
        let (u, g) = chown_args(vm, &a.arg(0), &a.arg(1))?;
        fd_op(vm, &fd, "fchown", |f| std::os::unix::fs::fchown(&*f, Some(u), Some(g)))
    })();
    Ok(settle(vm, r))
}

framed!(fh_stat, ["promisedCall", "<anonymous>", "fstatSync"], fh_stat_);

fn fh_stat_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| -> JsResult<Value> {
        let fd = fh_fd(vm, a)?;
        fstat_impl(vm, &fd)
    })();
    Ok(settle(vm, r))
}

framed!(fh_truncate, ["promisedCall", "<anonymous>", "ftruncateSync"], fh_truncate_);

fn fh_truncate_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| -> JsResult<Value> {
        let fd = fh_fd(vm, a)?;
        let len = if a.arg(0).truthy() { a.arg(0) } else { Value::Num(0.0) };
        ftruncate_impl(vm, &fd, &len)
    })();
    Ok(settle(vm, r))
}

framed!(fh_utimes, ["promisedCall", "<anonymous>", "futimesSync"], fh_utimes_);

fn fh_utimes_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| -> JsResult<Value> {
        let fd = fh_fd(vm, a)?;
        let at = unix_seconds(vm, &a.arg(0))?;
        let mt = unix_seconds(vm, &a.arg(1))?;
        fd_op(vm, &fd, "futime", |f| {
            use std::os::unix::io::AsRawFd;
            let ts = [timespec(at), timespec(mt)];
            let r = unsafe { futimens(f.as_raw_fd(), ts.as_ptr()) };
            if r != 0 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        })
    })();
    Ok(settle(vm, r))
}

framed!(fh_sync, ["promisedCall", "<anonymous>", "fsyncSync"], fh_sync_);

fn fh_sync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| -> JsResult<Value> {
        let fd = fh_fd(vm, a)?;
        fd_op(vm, &fd, "fsync", |f| f.sync_all())
    })();
    Ok(settle(vm, r))
}

framed!(fh_datasync, ["promisedCall", "<anonymous>", "fdatasyncSync"], fh_datasync_);

fn fh_datasync_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| -> JsResult<Value> {
        let fd = fh_fd(vm, a)?;
        fd_op(vm, &fd, "fdatasync", |f| f.sync_data())
    })();
    Ok(settle(vm, r))
}

fn fh_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| -> JsResult<Value> {
        let fd = fh_fd(vm, a)?;
        if !fd.is_nullish() {
            let n = vm.to_number(&fd)?;
            close_fd_num(n);
            setp(vm, &a.this, "fd", Value::Null)?;
        }
        Ok(Value::Undefined)
    })();
    Ok(settle(vm, r))
}

fn fh_stream_opts(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let base = normalize_stream_opts(vm, &a.arg(0))?;
    let o = vm.new_object();
    vm.copy_data_properties(&o, &base, &[])?;
    let fd = fh_fd(vm, a)?;
    vm.create_data_property(&o, key("fd"), fd)?;
    vm.create_data_property(&o, key("autoClose"), Value::Bool(false))?;
    Ok(Value::Obj(o))
}

fn fh_create_read_stream(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let opts = fh_stream_opts(vm, a)?;
    let ctor = class_ctor(vm, |c| c.read_stream.clone());
    vm.construct(&ctor, &[Value::Null, opts], None)
}

fn fh_create_write_stream(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let opts = fh_stream_opts(vm, a)?;
    let ctor = class_ctor(vm, |c| c.write_stream.clone());
    vm.construct(&ctor, &[Value::Null, opts], None)
}

fn fh_async_dispose(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    call_method(vm, &a.this, "close", &[])
}

/// constructor of a class from its prototype
fn class_ctor(vm: &mut Vm, f: fn(&Classes) -> Option<Obj>) -> Value {
    let p = class_proto(vm, f);
    p.get_own_data(&vm.intr.key_constructor.clone()).unwrap_or(Value::Undefined)
}

fn is_file_handle(vm: &mut Vm, v: &Value) -> bool {
    let proto = class_proto(vm, |c| c.file_handle.clone());
    let mut cur = match v {
        Value::Obj(o) => o.borrow().proto.clone(),
        _ => None,
    };
    while let Some(p) = cur {
        if p.ptr_eq(&proto) {
            return true;
        }
        cur = p.borrow().proto.clone();
    }
    false
}

// ============================================================================================
// callback API
// ============================================================================================

// Generic wrapper: `(...args, cb)` → nextTick → cb(err) / cb(null, result).
framed!(cb_wrapper, ["<anonymous>"], cb_wrapper_);

fn cb_wrapper_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut args = a.args.to_vec();
    let cb = args.pop().unwrap_or(Value::Undefined);
    if !cb.is_callable() {
        return vm.throw_type("callback is not a function");
    }
    let arr = Value::Obj(vm.new_array(args));
    let t = closure(vm, "", 0, cb_wrapper_tick, vec![a.slot(0), arr, cb]);
    next_tick(vm, t)?;
    Ok(Value::Undefined)
}

framed!(cb_wrapper_tick, ["<anonymous>"], cb_wrapper_tick_);

fn cb_wrapper_tick_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.slot(0);
    let args = crate::builtins::array::array_like_to_vec(vm, &a.slot(1))?;
    let cb = a.slot(2);
    match vm.call(&f, Value::Undefined, &args) {
        Err(e) => {
            call_cb(vm, &cb, &[e])?;
        }
        Ok(r) => {
            call_cb(vm, &cb, &[Value::Null, r])?;
        }
    }
    Ok(Value::Undefined)
}

/// `try { cb(null, ...ok) } catch (e) { cb(e) }` — the pattern of open/read/readv/... callbacks.
fn cb_try(vm: &mut Vm, cb: &Value, r: JsResult<Vec<Value>>) -> JsResult<()> {
    let res = match r {
        Ok(mut vals) => {
            vals.insert(0, Value::Null);
            call_cb(vm, cb, &vals).map(|_| ())
        }
        Err(e) => Err(e),
    };
    if let Err(e) = res {
        call_cb(vm, cb, &[e])?;
    }
    Ok(())
}

framed!(open_cb, ["<anonymous>"], open_cb_);

fn open_cb_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (path, mut flags, mut mode, mut cb) = (a.arg(0), a.arg(1), a.arg(2), a.arg(3));
    if flags.is_callable() {
        cb = flags;
        flags = Value::str("r");
        mode = Value::Undefined;
    } else if mode.is_callable() {
        cb = mode;
        mode = Value::Undefined;
    }
    let t = closure(vm, "", 0, open_cb_tick, vec![path, flags, mode, cb]);
    next_tick(vm, t)?;
    Ok(Value::Undefined)
}

framed!(open_cb_tick, ["<anonymous>"], open_cb_tick_);

fn open_cb_tick_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = open_impl(vm, &a.slot(0), &a.slot(1)).map(|fd| vec![fd]);
    cb_try(vm, &a.slot(3), r)?;
    Ok(Value::Undefined)
}

framed!(exists_cb, ["<anonymous>"], exists_cb_);

fn exists_cb_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t = closure(vm, "", 0, exists_cb_tick, vec![a.arg(0), a.arg(1)]);
    next_tick(vm, t)?;
    Ok(Value::Undefined)
}

framed!(exists_cb_tick, ["<anonymous>"], exists_cb_tick_);

fn exists_cb_tick_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = exists_impl(vm, &a.slot(0));
    call_cb(vm, &a.slot(1), &[Value::Bool(r)])?;
    Ok(Value::Undefined)
}

framed!(read_cb, ["<anonymous>"], read_cb_);

fn read_cb_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let fd = a.arg(0);
    let x = a.arg(1);
    let (buffer, offset, length, position, cb);
    if x.is_callable() {
        cb = x;
        buffer = new_buffer(vm, vec![0; 16384])?;
        offset = Value::Num(0.0);
        length = Value::Num(16384.0);
        position = Value::Null;
    } else if is_plain_object(&x) && !is_view(&x) {
        let b = getp(vm, &x, "buffer")?;
        buffer = if b.truthy() { b } else { new_buffer(vm, vec![0; 16384])? };
        let off = getp(vm, &x, "offset")?;
        offset = if off.truthy() { off } else { Value::Num(0.0) };
        let l = getp(vm, &x, "length")?;
        length = if l.is_nullish() { Value::Num(length_minus(vm, &buffer, &offset)?) } else { l };
        let p = getp(vm, &x, "position")?;
        position = if p.is_nullish() { Value::Null } else { p };
        cb = a.arg(2);
    } else {
        buffer = x;
        let b = a.arg(2);
        offset = if b.truthy() { b } else { Value::Num(0.0) };
        let c = a.arg(3);
        length = if c.is_nullish() { Value::Num(length_minus(vm, &buffer, &offset)?) } else { c };
        let d = a.arg(4);
        position = if d.is_nullish() { Value::Null } else { d };
        cb = a.arg(5);
    }
    let t = closure(vm, "", 0, read_cb_tick, vec![fd, buffer, offset, length, position, cb]);
    next_tick(vm, t)?;
    Ok(Value::Undefined)
}

framed!(read_cb_tick, ["<anonymous>"], read_cb_tick_);

fn read_cb_tick_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let buffer = a.slot(1);
    let r = with_frames(vm, &["readSync"], |vm| read_sync_impl(vm, &a.slot(0), &buffer, &a.slot(2), &a.slot(3), &a.slot(4))).map(|n| vec![n, buffer.clone()]);
    cb_try(vm, &a.slot(5), r)?;
    Ok(Value::Undefined)
}

framed!(write_cb, ["<anonymous>"], write_cb_);

fn write_cb_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let fd = a.arg(0);
    let data = a.arg(1);
    let mut rest: Vec<Value> = if a.args.len() > 2 { a.args[2..].to_vec() } else { Vec::new() };
    let cb = if rest.last().map_or(false, |v| v.is_callable()) { rest.pop().unwrap() } else { Value::Undefined };
    let g = |i: usize| rest.get(i).cloned().unwrap_or(Value::Undefined);
    let t = closure(vm, "", 0, write_cb_tick, vec![fd, data, g(0), g(1), g(2), cb]);
    next_tick(vm, t)?;
    Ok(Value::Undefined)
}

framed!(write_cb_tick, ["<anonymous>"], write_cb_tick_);

fn write_cb_tick_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let data = a.slot(1);
    let cb = a.slot(5);
    let r = write_sync_impl(vm, &a.slot(0), &data, &a.slot(2), &a.slot(3), &a.slot(4));
    let res = match r {
        Ok(n) => {
            if cb.truthy() {
                call_cb(vm, &cb, &[Value::Null, n, data]).map(|_| ())
            } else {
                Ok(())
            }
        }
        Err(e) => Err(e),
    };
    if let Err(e) = res {
        if cb.truthy() {
            call_cb(vm, &cb, &[e])?;
        }
    }
    Ok(Value::Undefined)
}

fn vec_cb(vm: &mut Vm, a: &Args, f: NativeFn) -> JsResult<Value> {
    let (fd, buffers, mut position, mut cb) = (a.arg(0), a.arg(1), a.arg(2), a.arg(3));
    if position.is_callable() {
        cb = position;
        position = Value::Null;
    }
    let t = closure(vm, "", 0, f, vec![fd, buffers, position, cb]);
    next_tick(vm, t)?;
    Ok(Value::Undefined)
}

framed!(readv_cb, ["<anonymous>"], readv_cb_);

fn readv_cb_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    vec_cb(vm, a, readv_cb_tick)
}

framed!(writev_cb, ["<anonymous>"], writev_cb_);

fn writev_cb_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    vec_cb(vm, a, writev_cb_tick)
}

framed!(readv_cb_tick, ["<anonymous>"], readv_cb_tick_);

fn readv_cb_tick_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = a.slot(1);
    let r = with_frames(vm, &["readvSync"], |vm| readv_sync_impl(vm, &a.slot(0), &b, &a.slot(2))).map(|n| vec![n, b.clone()]);
    cb_try(vm, &a.slot(3), r)?;
    Ok(Value::Undefined)
}

framed!(writev_cb_tick, ["<anonymous>"], writev_cb_tick_);

fn writev_cb_tick_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = a.slot(1);
    let r = with_frames(vm, &["writevSync"], |vm| writev_sync_impl(vm, &a.slot(0), &b, &a.slot(2))).map(|n| vec![n, b.clone()]);
    cb_try(vm, &a.slot(3), r)?;
    Ok(Value::Undefined)
}

/// (x, y?, options, cb) with `typeof options === "function"` shifting
fn opts_cb(vm: &mut Vm, slots_before: Vec<Value>, options: Value, cb: Value, f: NativeFn) -> JsResult<Value> {
    let (opts, cb) = if options.is_callable() { (Value::Obj(vm.new_object()), options) } else { (options, cb) };
    let mut slots = slots_before;
    slots.push(opts);
    slots.push(cb);
    let t = closure(vm, "", 0, f, slots);
    next_tick(vm, t)?;
    Ok(Value::Undefined)
}

framed!(cp_cb, ["<anonymous>"], cp_cb_);

fn cp_cb_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    opts_cb(vm, vec![a.arg(0), a.arg(1)], a.arg(2), a.arg(3), cp_cb_tick)
}

framed!(cp_cb_tick, ["<anonymous>"], cp_cb_tick_);

fn cp_cb_tick_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = cp_impl(vm, &a.slot(0), &a.slot(1), &a.slot(2)).map(|_| Vec::new());
    cb_try(vm, &a.slot(3), r)?;
    Ok(Value::Undefined)
}

framed!(glob_cb, ["<anonymous>"], glob_cb_);

fn glob_cb_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    opts_cb(vm, vec![a.arg(0)], a.arg(1), a.arg(2), glob_cb_tick)
}

framed!(glob_cb_tick, ["<anonymous>"], glob_cb_tick_);

fn glob_cb_tick_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = glob_impl(vm, &a.slot(0), &a.slot(1)).map(|v| vec![Value::Obj(vm.new_array(v))]);
    cb_try(vm, &a.slot(2), r)?;
    Ok(Value::Undefined)
}

framed!(opendir_cb, ["<anonymous>"], opendir_cb_);

fn opendir_cb_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    opts_cb(vm, vec![a.arg(0)], a.arg(1), a.arg(2), opendir_cb_tick)
}

framed!(opendir_cb_tick, ["<anonymous>"], opendir_cb_tick_);

fn opendir_cb_tick_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = opendir_impl(vm, &a.slot(0)).map(|d| vec![d]);
    cb_try(vm, &a.slot(2), r)?;
    Ok(Value::Undefined)
}

framed!(open_as_blob, ["<anonymous>"], open_as_blob_);

fn open_as_blob_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| -> JsResult<Value> {
        let path = to_path(vm, &a.arg(0))?;
        let bytes = match std::fs::read(&path) {
            Ok(b) => b,
            Err(e) => return Err(read_err(vm, &path, &e)),
        };
        check_len(vm, bytes.len())?;
        let arr = crate::builtins::typedarray::typed_array_from_bytes(vm, bytes);
        let ty = opt_get(vm, &a.arg(1), "type")?;
        let ty = if ty.truthy() { ty } else { Value::str("") };
        let blob = match vm.global.get_own_str("Blob") {
            Some(b) if b.is_callable() => b,
            _ => return vm.throw_ref("Blob is not defined"),
        };
        let parts = Value::Obj(vm.new_array(vec![Value::Obj(arr)]));
        let o = Value::Obj(vm.obj_from(vec![("type", ty)]));
        vm.construct(&blob, &[parts, o], None)
    })();
    Ok(settle(vm, r))
}

framed!(watch_fn, ["<anonymous>", "fsError"], watch_fn_);
framed!(p_watch, ["watch", "fsError"], watch_fn_);

fn watch_fn_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let path = to_path(vm, &a.arg(0))?;
    Err(js_err(vm, "ENOSYS", "watch", &path, "fs.watch requires a filesystem-event backend that is not available"))
}

/// pollStat: the file's Stats, or an all-zero Stats of kind "other" when it cannot be stat'ed.
fn poll_stat(vm: &mut Vm, path: &str) -> Value {
    match std::fs::metadata(path) {
        Ok(md) => {
            let raw = raw_stat(&md);
            make_stats(vm, &raw)
        }
        Err(_) => make_stats(vm, &RawStat { nums: [0.0; 14], kind: "other" }),
    }
}

/// watchFile: one StatWatcher + polling interval per path (the interval keeps the process alive
/// until unwatchFile); listeners get (curr, prev) when size or mtime changed — once directly and
/// once more through the watcher's 'change' event.
fn watch_file(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (filename, mut options, mut listener) = (a.arg(0), a.arg(1), a.arg(2));
    if options.is_callable() {
        listener = options;
        options = Value::Obj(vm.new_object());
    }
    let iv = opt_get(vm, &options, "interval")?;
    let interval = if iv.truthy() { to_num(vm, &iv)? } else { 5007.0 };
    let p = to_path(vm, &filename)?;
    let existing = FS.with(|s| s.borrow().watchers.iter().find(|w| w.path == p).map(|w| w.watcher.clone()));
    let watcher = match existing {
        Some(w) => w,
        None => {
            let w = new_stat_watcher(vm);
            let prev = poll_stat(vm, &p);
            let tick = closure(vm, "", 0, watch_poll, vec![Value::str(&p)]);
            let timer = crate::runtime::timers::add_timer(vm, tick, interval, Vec::new(), true);
            FS.with(|s| s.borrow_mut().watchers.push(Watch { path: p.clone(), watcher: w.clone(), listeners: Vec::new(), prev, timer }));
            w
        }
    };
    if listener.truthy() {
        let l = listener.clone();
        FS.with(|s| {
            let mut st = s.borrow_mut();
            if let Some(w) = st.watchers.iter_mut().find(|w| w.path == p) {
                if !w.listeners.iter().any(|x| Value::same_value_zero(x, &l)) {
                    w.listeners.push(l);
                }
            }
        });
        call_method(vm, &Value::Obj(watcher.clone()), "on", &[Value::str("change"), listener])?;
    }
    Ok(Value::Obj(watcher))
}

fn watch_poll(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = match a.slot(0) {
        Value::Str(s) => s.to_rust_string(),
        _ => return Ok(Value::Undefined),
    };
    let prev = match FS.with(|s| s.borrow().watchers.iter().find(|w| w.path == p).map(|w| w.prev.clone())) {
        Some(v) => v,
        None => return Ok(Value::Undefined),
    };
    let cur = poll_stat(vm, &p);
    let cm = getp(vm, &cur, "mtimeMs")?;
    let pm = getp(vm, &prev, "mtimeMs")?;
    let cs = getp(vm, &cur, "size")?;
    let ps = getp(vm, &prev, "size")?;
    if Value::strict_eq(&cm, &pm) && Value::strict_eq(&cs, &ps) {
        return Ok(Value::Undefined);
    }
    let found = FS.with(|s| {
        let mut st = s.borrow_mut();
        st.watchers.iter_mut().find(|w| w.path == p).map(|w| {
            w.prev = cur.clone();
            (w.listeners.clone(), w.watcher.clone())
        })
    });
    let (listeners, watcher) = match found {
        Some(x) => x,
        None => return Ok(Value::Undefined),
    };
    for l in listeners {
        vm.call(&l, Value::Undefined, &[cur.clone(), prev.clone()])?;
    }
    emit(vm, &Value::Obj(watcher), "change", &[cur, prev])?;
    Ok(Value::Undefined)
}

fn unwatch_file(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = to_path(vm, &a.arg(0))?;
    let listener = a.arg(1);
    let stop = FS.with(|s| {
        let mut st = s.borrow_mut();
        if let Some(i) = st.watchers.iter().position(|w| w.path == p) {
            if listener.truthy() {
                st.watchers[i].listeners.retain(|x| !Value::same_value_zero(x, &listener));
            } else {
                st.watchers[i].listeners.clear();
            }
            if st.watchers[i].listeners.is_empty() {
                let w = st.watchers.remove(i);
                return Some(w.timer);
            }
        }
        None
    });
    if let Some(t) = stop {
        crate::runtime::timers::clear_timer_id(vm, &Value::Num(t as f64));
    }
    Ok(Value::Undefined)
}

framed!(create_read_stream, ["<anonymous>"], create_read_stream_);

fn create_read_stream_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ctor = class_ctor(vm, |c| c.read_stream.clone());
    vm.construct(&ctor, &[a.arg(0), a.arg(1)], None)
}

framed!(create_write_stream, ["<anonymous>"], create_write_stream_);

fn create_write_stream_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ctor = class_ctor(vm, |c| c.write_stream.clone());
    vm.construct(&ctor, &[a.arg(0), a.arg(1)], None)
}

// ============================================================================================
// promise API
// ============================================================================================

// `(...args) => promisedCall(() => syncFn(...args))`
framed!(promise_wrapper, ["promisedCall", "<anonymous>"], promise_wrapper_);

fn promise_wrapper_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.slot(0);
    let r = vm.call(&f, Value::Undefined, a.args);
    Ok(settle(vm, r))
}

framed!(p_read_file, ["promisedCall", "<anonymous>"], p_read_file_);

fn p_read_file_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = a.arg(0);
    let r = (|| -> JsResult<Value> {
        let target = if is_file_handle(vm, &p) { getp(vm, &p, "fd")? } else { p.clone() };
        read_file_impl(vm, &target, &a.arg(1))
    })();
    Ok(settle(vm, r))
}

fn p_write_file(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = a.arg(0);
    if is_file_handle(vm, &p) {
        return call_method(vm, &p, "writeFile", &[a.arg(1), a.arg(2)]);
    }
    let r = with_frames(vm, &["promisedCall", "<anonymous>"], |vm| write_file_impl(vm, &p, &a.arg(1), &a.arg(2)));
    Ok(settle(vm, r))
}

framed!(p_append_file, ["promisedCall", "<anonymous>"], p_append_file_);

fn p_append_file_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = a.arg(0);
    let r = (|| -> JsResult<Value> {
        let target = if is_file_handle(vm, &p) { getp(vm, &p, "fd")? } else { p.clone() };
        append_file_impl(vm, &target, &a.arg(1), &a.arg(2))
    })();
    Ok(settle(vm, r))
}

framed!(p_open, ["promisedCall", "<anonymous>", "<anonymous>"], p_open_);

fn p_open_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| -> JsResult<Value> {
        let fd = open_impl(vm, &a.arg(0), &a.arg(1))?;
        Ok(new_file_handle(vm, fd))
    })();
    Ok(settle(vm, r))
}

framed!(p_glob, ["glob"], p_glob_);

fn p_glob_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let matches = glob_impl(vm, &a.arg(0), &a.arg(1))?;
    Ok(new_list_iter(vm, matches, None))
}

// ============================================================================================
// streams: ReadStream / WriteStream on node:stream's Readable / Writable
// ============================================================================================

use crate::runtime::nodestream::{readable_init, writable_init};

fn return_this(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(a.this.clone())
}

// --- fs.ReadStream / fs.WriteStream ---

/// normalizeStreamOpts: a string is the encoding, otherwise `options || {}`.
fn normalize_stream_opts(vm: &mut Vm, opts: &Value) -> JsResult<Value> {
    match opts {
        Value::Str(_) => Ok(Value::Obj(vm.obj_from(vec![("encoding", opts.clone())]))),
        v if v.truthy() => Ok(v.clone()),
        _ => Ok(Value::Obj(vm.new_object())),
    }
}

fn emit_error_tick(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    emit(vm, &a.slot(0), "error", &[a.slot(1)])?;
    Ok(Value::Undefined)
}

fn emit_close_tick(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    emit(vm, &a.slot(0), "close", &[])?;
    Ok(Value::Undefined)
}

/// open the stream's file (nodeFs.openSync(path, flags, mode)); on failure fd = null and the
/// error is emitted on the next tick. Returns false when opening failed.
fn stream_open(vm: &mut Vm, this: &Value, path: &Value, o: &Value) -> JsResult<bool> {
    let fd = getp(vm, o, "fd")?;
    if !fd.is_nullish() {
        setp(vm, this, "fd", fd)?;
        return Ok(true);
    }
    let flags = getp(vm, this, "flags")?;
    getp(vm, o, "mode")?;
    match open_impl(vm, path, &flags) {
        Ok(n) => {
            setp(vm, this, "fd", n)?;
            Ok(true)
        }
        Err(e) => {
            setp(vm, this, "fd", Value::Null)?;
            let t = closure(vm, "", 0, emit_error_tick, vec![this.clone(), e]);
            next_tick(vm, t)?;
            Ok(false)
        }
    }
}

framed!(read_stream_ctor, ["ReadStream"], read_stream_ctor_);

fn read_stream_ctor_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = instance(vm, a, |c| c.read_stream.clone())?;
    let this = Value::Obj(o.clone());
    let path = a.arg(0);
    let opts = normalize_stream_opts(vm, &a.arg(1))?;
    let enc = getp(vm, &opts, "encoding")?;
    let hwm = getp(vm, &opts, "highWaterMark")?;
    let ropts = Value::Obj(vm.obj_from(vec![("encoding", enc), ("highWaterMark", hwm.clone())]));
    readable_init(vm, &o, &ropts)?;
    setp(vm, &this, "path", path.clone())?;
    let flags = getp(vm, &opts, "flags")?;
    setp(vm, &this, "flags", if flags.truthy() { flags } else { Value::str("r") })?;
    setp(vm, &this, "bytesRead", Value::Num(0.0))?;
    let start = getp(vm, &opts, "start")?;
    setp(vm, &this, "pos", if start.truthy() { start } else { Value::Num(0.0) })?;
    let end = getp(vm, &opts, "end")?;
    setp(vm, &this, "_end", if end.is_nullish() { Value::Num(f64::INFINITY) } else { end })?;
    setp(vm, &this, "_chunk", if hwm.truthy() { hwm } else { Value::Num(65536.0) })?;
    let ac = getp(vm, &opts, "autoClose")?;
    setp(vm, &this, "_autoClose", Value::Bool(!matches!(ac, Value::Bool(false))))?;
    let fd = getp(vm, &opts, "fd")?;
    setp(vm, &this, "_ownFd", Value::Bool(fd.is_nullish()))?;
    if !stream_open(vm, &this, &path, &opts)? {
        return Ok(this);
    }
    let t = closure(vm, "", 0, read_stream_open_tick, vec![this.clone()]);
    next_tick(vm, t)?;
    Ok(this)
}

framed!(read_stream_open_tick, ["<anonymous>"], read_stream_open_tick_);

fn read_stream_open_tick_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.slot(0);
    let fd = getp(vm, &this, "fd")?;
    if fd.is_nullish() {
        return Ok(Value::Undefined);
    }
    emit(vm, &this, "open", &[fd])?;
    emit(vm, &this, "ready", &[])?;
    call_method(vm, &this, "_pump", &[])?;
    Ok(Value::Undefined)
}

framed!(read_stream_pump, ["_pump"], read_stream_pump_);

fn read_stream_pump_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let r = (|| -> JsResult<()> {
        loop {
            // JS semantics on purpose: `start`/`end` options are used as given
            let pos = getp(vm, &this, "pos")?;
            let end = getp(vm, &this, "_end")?;
            if !vm.op_compare(crate::bytecode::Op::Le, &pos, &end)? {
                break;
            }
            let chunk = getp(vm, &this, "_chunk")?;
            let want = if Value::strict_eq(&end, &Value::Num(f64::INFINITY)) {
                chunk
            } else {
                let diff = vm.op_arith(crate::bytecode::Op::Sub, &end, &pos)?;
                let rest = vm.op_add(&diff, &Value::Num(1.0))?;
                let a = vm.to_number(&chunk)?;
                let b = vm.to_number(&rest)?;
                Value::Num(if a.is_nan() || b.is_nan() { f64::NAN } else { a.min(b) })
            };
            let fd = getp(vm, &this, "fd")?;
            let len = len_arg(vm, &want)?;
            let bytes = pread(vm, &fd, len, pos_arg(&pos))?;
            if bytes.is_empty() {
                break;
            }
            let n = bytes.len() as f64;
            let p = getp(vm, &this, "pos")?;
            let p = vm.op_add(&p, &Value::Num(n))?;
            setp(vm, &this, "pos", p)?;
            let br = getp(vm, &this, "bytesRead")?;
            let br = vm.op_add(&br, &Value::Num(n))?;
            setp(vm, &this, "bytesRead", br)?;
            let buf = new_buffer(vm, bytes)?;
            call_method(vm, &this, "push", &[buf])?;
        }
        call_method(vm, &this, "push", &[Value::Null])?;
        call_method(vm, &this, "_closeStream", &[Value::Null])?;
        Ok(())
    })();
    if let Err(e) = r {
        call_method(vm, &this, "_closeStream", &[e])?;
    }
    Ok(Value::Undefined)
}

fn read_stream_close_stream(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let err = a.arg(0);
    let own = getp(vm, &this, "_ownFd")?.truthy();
    if own && getp(vm, &this, "_autoClose")?.truthy() {
        let fd = getp(vm, &this, "fd")?;
        if !fd.is_nullish() {
            if let Ok(n) = to_num(vm, &fd) {
                close_fd_num(n);
            }
        }
    }
    setp(vm, &this, "fd", Value::Null)?;
    if err.truthy() {
        let t = closure(vm, "", 0, emit_error_tick, vec![this.clone(), err]);
        next_tick(vm, t)?;
    }
    let t = closure(vm, "", 0, emit_close_tick, vec![this]);
    next_tick(vm, t)?;
    Ok(Value::Undefined)
}

fn read_stream_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let cb = a.arg(0);
    if cb.truthy() {
        call_method(vm, &this, "once", &[Value::str("close"), cb])?;
    }
    let fd = getp(vm, &this, "fd")?;
    if !fd.is_nullish() && getp(vm, &this, "_ownFd")?.truthy() {
        if let Ok(n) = to_num(vm, &fd) {
            close_fd_num(n);
        }
        setp(vm, &this, "fd", Value::Null)?;
    }
    Ok(Value::Undefined)
}

framed!(write_stream_ctor, ["WriteStream"], write_stream_ctor_);

fn write_stream_ctor_(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = instance(vm, a, |c| c.write_stream.clone())?;
    let this = Value::Obj(o.clone());
    let path = a.arg(0);
    let opts = normalize_stream_opts(vm, &a.arg(1))?;
    let empty = Value::Obj(vm.new_object());
    writable_init(vm, &o, &empty)?;
    setp(vm, &this, "path", path.clone())?;
    let flags = getp(vm, &opts, "flags")?;
    setp(vm, &this, "flags", if flags.truthy() { flags } else { Value::str("w") })?;
    setp(vm, &this, "bytesWritten", Value::Num(0.0))?;
    let start = getp(vm, &opts, "start")?;
    setp(vm, &this, "pos", start)?;
    let enc = getp(vm, &opts, "encoding")?;
    setp(vm, &this, "_encoding", if enc.truthy() { enc } else { Value::str("utf8") })?;
    let ac = getp(vm, &opts, "autoClose")?;
    setp(vm, &this, "_autoClose", Value::Bool(!matches!(ac, Value::Bool(false))))?;
    let fd = getp(vm, &opts, "fd")?;
    setp(vm, &this, "_ownFd", Value::Bool(fd.is_nullish()))?;
    if !stream_open(vm, &this, &path, &opts)? {
        return Ok(this);
    }
    let onfinish = closure(vm, "", 0, write_stream_on_finish, vec![this.clone()]);
    call_method(vm, &this, "on", &[Value::str("finish"), onfinish])?;
    let t = closure(vm, "", 0, write_stream_open_tick, vec![this.clone()]);
    next_tick(vm, t)?;
    Ok(this)
}

fn write_stream_on_finish(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.slot(0);
    if getp(vm, &this, "_autoClose")?.truthy() {
        let t = closure(vm, "", 0, emit_close_tick, vec![this]);
        next_tick(vm, t)?;
    }
    Ok(Value::Undefined)
}

fn write_stream_open_tick(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.slot(0);
    let fd = getp(vm, &this, "fd")?;
    if fd.is_nullish() {
        return Ok(Value::Undefined);
    }
    emit(vm, &this, "open", &[fd])?;
    emit(vm, &this, "ready", &[])?;
    Ok(Value::Undefined)
}

fn write_stream_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let (chunk, enc, cb) = (a.arg(0), a.arg(1), a.arg(2));
    let r = (|| -> JsResult<()> {
        let e = if enc.truthy() { enc.clone() } else { getp(vm, &this, "_encoding")? };
        let buf = to_buffer(vm, &chunk, &e)?;
        let posv = getp(vm, &this, "pos")?;
        let pos = pos_arg(&posv);
        let fd = getp(vm, &this, "fd")?;
        let n = pwrite(vm, &fd, &buf, pos)? as f64;
        let bw = getp(vm, &this, "bytesWritten")?;
        let bw = vm.op_add(&bw, &Value::Num(n))?;
        setp(vm, &this, "bytesWritten", bw)?;
        if !posv.is_nullish() {
            let p = getp(vm, &this, "pos")?;
            let p = vm.op_add(&p, &Value::Num(n))?;
            setp(vm, &this, "pos", p)?;
        }
        vm.call(&cb, Value::Undefined, &[])?;
        Ok(())
    })();
    if let Err(e) = r {
        vm.call(&cb, Value::Undefined, &[e])?;
    }
    Ok(Value::Undefined)
}

fn write_stream_final(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let cb = a.arg(0);
    let own = getp(vm, &this, "_ownFd")?.truthy() && getp(vm, &this, "_autoClose")?.truthy();
    let fd = getp(vm, &this, "fd")?;
    if own && !fd.is_nullish() {
        let r = (|| -> JsResult<()> {
            let n = vm.to_number(&fd)?;
            close_fd_num(n);
            setp(vm, &this, "fd", Value::Null)?;
            vm.call(&cb, Value::Undefined, &[])?;
            Ok(())
        })();
        if let Err(e) = r {
            vm.call(&cb, Value::Undefined, &[e])?;
        }
    } else {
        vm.call(&cb, Value::Undefined, &[])?;
    }
    Ok(Value::Undefined)
}

fn write_stream_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let cb = a.arg(0);
    if cb.truthy() {
        call_method(vm, &this, "once", &[Value::str("close"), cb])?;
    }
    call_method(vm, &this, "end", &[])?;
    Ok(Value::Undefined)
}

// ============================================================================================
// module assembly
// ============================================================================================

/// Present a native as an ordinary `function` (the reference defines these as function
/// expressions): it gets a `prototype` object and `new f(...)` yields an object.
fn plain_function(vm: &mut Vm, inner: Obj) -> Obj {
    let (name, len) = {
        let b = inner.borrow();
        let n = match b.props.get(&vm.intr.key_name) {
            Some(Prop::Data { value: Value::Str(s), .. }) => s.to_rust_string(),
            _ => String::new(),
        };
        let l = match b.props.get(&vm.intr.key_length) {
            Some(Prop::Data { value: Value::Num(n), .. }) => *n as u32,
            _ => 0,
        };
        (n, l)
    };
    let outer = vm.native_closure(&name, len, plain_function_shim, vec![Value::Obj(inner)]);
    vm.make_ctor(&outer);
    let proto = vm.new_object();
    proto.set_prop(key("constructor"), Value::Obj(outer.clone()), WC);
    outer.set_prop(key("prototype"), Value::Obj(proto), WRITABLE);
    outer
}

fn plain_function_shim(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let inner = a.slot(0);
    match &a.new_target {
        None => vm.call(&inner, a.this.clone(), a.args),
        Some(nt) => {
            let fb = vm.intr.object_proto.clone();
            let proto = vm.proto_from_nt(&Some(nt.clone()), &fb)?;
            let obj = Value::Obj(Obj::new(Some(proto), ObjKind::Ordinary));
            let r = vm.call(&inner, obj.clone(), a.args)?;
            Ok(if r.is_object() { r } else { obj })
        }
    }
}

fn make_class(vm: &mut Vm, name: &str, len: u32, ctor: NativeFn, parent: Option<Obj>) -> (Obj, Obj) {
    let proto = Obj::new(Some(parent.unwrap_or_else(|| vm.intr.object_proto.clone())), ObjKind::Ordinary);
    let c = vm.native_ctor(name, len, ctor, &proto);
    (c, proto)
}

struct Built {
    stats: Obj,
    dirent: Obj,
    dir: Obj,
    stat_watcher: Obj,
    read_stream: Obj,
    write_stream: Obj,
    file_handle: Obj,
}

fn setup_classes(vm: &mut Vm) -> JsResult<Built> {
    let ee = crate::runtime::node::builtin_module(vm, "events")?.unwrap_or(Value::Undefined);
    let ee_ctor = ee.as_obj().cloned();
    let ee_proto = match &ee {
        Value::Obj(_) => getp(vm, &ee, "prototype")?.as_obj().cloned(),
        _ => None,
    };

    let (stats, sp) = make_class(vm, "Stats", 1, stats_ctor, None);
    install_kind_methods(vm, &sp);
    let (dirent, dp) = make_class(vm, "Dirent", 3, dirent_ctor, None);
    install_kind_methods(vm, &dp);

    let (dir, dirp) = make_class(vm, "Dir", 2, dir_ctor, None);
    vm.def_method(&dirp, "readSync", 0, dir_read_sync);
    vm.def_method(&dirp, "read", 1, dir_read);
    vm.def_method(&dirp, "closeSync", 0, dir_close_sync);
    vm.def_method(&dirp, "close", 1, dir_close);
    let sai = vm.intr.sym_async_iterator.clone();
    vm.def_sym_method(&dirp, &sai, "[Symbol.asyncIterator]", 0, dir_async_iter);

    let (stat_watcher, swp) = make_class(vm, "StatWatcher", 0, stat_watcher_ctor, ee_proto.clone());
    if let Some(ec) = &ee_ctor {
        stat_watcher.borrow_mut().proto = Some(ec.clone());
    }
    vm.def_method(&swp, "start", 0, |_vm, _a| Ok(Value::Undefined));
    vm.def_method(&swp, "stop", 0, |_vm, _a| Ok(Value::Undefined));
    vm.def_method(&swp, "ref", 0, return_this);
    vm.def_method(&swp, "unref", 0, return_this);

    // stream bases shared with node:stream (ReadStream / WriteStream extend them)
    let sc = crate::runtime::nodestream::classes(vm);
    let (readable, rp) = (sc.readable.clone(), sc.readable_proto.clone());
    let (writable, wp) = (sc.writable.clone(), sc.writable_proto.clone());

    let (read_stream, rsp) = make_class(vm, "ReadStream", 2, read_stream_ctor, Some(rp));
    read_stream.borrow_mut().proto = Some(readable.clone());
    vm.def_method(&rsp, "_pump", 0, read_stream_pump);
    vm.def_method(&rsp, "_closeStream", 1, read_stream_close_stream);
    vm.def_method(&rsp, "close", 1, read_stream_close);

    let (write_stream, wsp) = make_class(vm, "WriteStream", 2, write_stream_ctor, Some(wp));
    write_stream.borrow_mut().proto = Some(writable.clone());
    vm.def_method(&wsp, "_write", 3, write_stream_write);
    vm.def_method(&wsp, "_final", 1, write_stream_final);
    vm.def_method(&wsp, "close", 1, write_stream_close);

    let (file_handle, fhp) = make_class(vm, "FileHandle", 1, file_handle_ctor, None);
    let fmethods: &[(&str, u32, NativeFn)] = &[
        ("read", 4, fh_read),
        ("write", 4, fh_write),
        ("readv", 2, fh_readv),
        ("writev", 2, fh_writev),
        ("readFile", 1, fh_read_file),
        ("writeFile", 2, fh_write_file),
        ("appendFile", 2, fh_append_file),
        ("chmod", 1, fh_chmod),
        ("chown", 2, fh_chown),
        ("stat", 1, fh_stat),
        ("truncate", 1, fh_truncate),
        ("utimes", 2, fh_utimes),
        ("sync", 0, fh_sync),
        ("datasync", 0, fh_datasync),
        ("close", 0, fh_close),
        ("createReadStream", 1, fh_create_read_stream),
        ("createWriteStream", 1, fh_create_write_stream),
    ];
    for (n, l, f) in fmethods {
        vm.def_method(&fhp, n, *l, *f);
    }
    let sad = vm.intr.sym_async_dispose.clone();
    vm.def_sym_method(&fhp, &sad, "[Symbol.asyncDispose]", 0, fh_async_dispose);

    // async iterator objects (fs.promises.glob / Dir iteration) stand in for async generator
    // objects: an empty per-"generator function" prototype over the shared next/return/throw
    let lip = Obj::new(Some(vm.intr.async_generator_proto.clone()), ObjKind::Ordinary);
    vm.def_method(&lip, "next", 1, list_iter_next);
    vm.def_method(&lip, "return", 1, list_iter_return);
    vm.def_method(&lip, "throw", 1, list_iter_throw);
    let glob_iter = Obj::new(Some(lip.clone()), ObjKind::Ordinary);
    let dir_iter = Obj::new(Some(lip), ObjKind::Ordinary);

    FS.with(|s| {
        let c = &mut s.borrow_mut().classes;
        c.stats = Some(sp);
        c.dirent = Some(dp);
        c.dir = Some(dirp);
        c.file_handle = Some(fhp);
        c.read_stream = Some(rsp);
        c.write_stream = Some(wsp);
        c.stat_watcher = Some(swp);
        c.list_iter = Some(glob_iter);
        c.dir_iter = Some(dir_iter);
    });
    Ok(Built { stats, dirent, dir, stat_watcher, read_stream, write_stream, file_handle })
}

const CONSTANTS: &[(&str, f64)] = &[
    ("F_OK", 0.0),
    ("R_OK", 4.0),
    ("W_OK", 2.0),
    ("X_OK", 1.0),
    ("O_RDONLY", 0.0),
    ("O_WRONLY", 1.0),
    ("O_RDWR", 2.0),
    ("O_CREAT", 512.0),
    ("O_EXCL", 2048.0),
    ("O_NOCTTY", 131072.0),
    ("O_TRUNC", 1024.0),
    ("O_APPEND", 8.0),
    ("O_DIRECTORY", 1048576.0),
    ("O_NOFOLLOW", 256.0),
    ("O_SYNC", 128.0),
    ("O_DSYNC", 4194304.0),
    ("O_SYMLINK", 2097152.0),
    ("O_NONBLOCK", 4.0),
    ("S_IFMT", 61440.0),
    ("S_IFREG", 32768.0),
    ("S_IFDIR", 16384.0),
    ("S_IFCHR", 8192.0),
    ("S_IFBLK", 24576.0),
    ("S_IFIFO", 4096.0),
    ("S_IFLNK", 40960.0),
    ("S_IFSOCK", 49152.0),
    ("S_IRWXU", 448.0),
    ("S_IRUSR", 256.0),
    ("S_IWUSR", 128.0),
    ("S_IXUSR", 64.0),
    ("S_IRWXG", 56.0),
    ("S_IRGRP", 32.0),
    ("S_IWGRP", 16.0),
    ("S_IXGRP", 8.0),
    ("S_IRWXO", 7.0),
    ("S_IROTH", 4.0),
    ("S_IWOTH", 2.0),
    ("S_IXOTH", 1.0),
    ("COPYFILE_EXCL", 1.0),
    ("COPYFILE_FICLONE", 2.0),
    ("COPYFILE_FICLONE_FORCE", 4.0),
    ("UV_FS_O_FILEMAP", 0.0),
];

const SYNC_FNS: &[(&str, u32, NativeFn)] = &[
    ("readFileSync", 2, read_file_sync),
    ("writeFileSync", 3, write_file_sync),
    ("appendFileSync", 3, append_file_sync),
    ("existsSync", 1, exists_sync),
    ("mkdirSync", 2, mkdir_sync),
    ("rmdirSync", 2, rmdir_sync),
    ("rmSync", 2, rm_sync),
    ("readdirSync", 2, readdir_sync),
    ("unlinkSync", 1, unlink_sync),
    ("renameSync", 2, rename_sync),
    ("copyFileSync", 2, copy_file_sync),
    ("linkSync", 2, link_sync),
    ("statSync", 1, stat_sync),
    ("lstatSync", 1, lstat_sync),
    ("readlinkSync", 1, readlink_sync),
    ("symlinkSync", 2, symlink_sync),
    ("accessSync", 2, access_sync),
    ("chmodSync", 2, chmod_sync),
    ("utimesSync", 3, utimes_sync),
    ("lutimesSync", 3, lutimes_sync),
    ("mkdtempSync", 2, mkdtemp_sync),
    ("realpathSync", 1, realpath_sync),
    ("statfsSync", 1, statfs_sync),
    ("openSync", 3, open_sync),
    ("closeSync", 1, close_sync),
    ("fstatSync", 1, fstat_sync),
    ("ftruncateSync", 2, ftruncate_sync),
    ("truncateSync", 2, truncate_sync),
    ("fsyncSync", 1, fsync_sync),
    ("fdatasyncSync", 1, fdatasync_sync),
    ("fchmodSync", 2, fchmod_sync),
    ("futimesSync", 3, futimes_sync),
    ("readvBytes", 1, readv_bytes),
    ("readSync", 5, read_sync),
    ("writeSync", 5, write_sync),
    ("readvSync", 3, readv_sync),
    ("writevSync", 3, writev_sync),
    ("chownSync", 3, chown_sync),
    ("lchownSync", 3, lchown_sync),
    ("fchownSync", 3, fchown_sync),
    ("lchmodSync", 2, lchmod_sync),
];

/// callback API name → sync function it runs
const CB_FNS: &[(&str, &str)] = &[
    ("readFile", "readFileSync"),
    ("writeFile", "writeFileSync"),
    ("appendFile", "appendFileSync"),
    ("mkdir", "mkdirSync"),
    ("rmdir", "rmdirSync"),
    ("rm", "rmSync"),
    ("readdir", "readdirSync"),
    ("unlink", "unlinkSync"),
    ("rename", "renameSync"),
    ("copyFile", "copyFileSync"),
    ("link", "linkSync"),
    ("stat", "statSync"),
    ("lstat", "lstatSync"),
    ("fstat", "fstatSync"),
    ("statfs", "statfsSync"),
    ("readlink", "readlinkSync"),
    ("symlink", "symlinkSync"),
    ("access", "accessSync"),
    ("chmod", "chmodSync"),
    ("fchmod", "fchmodSync"),
    ("lchmod", "lchmodSync"),
    ("chown", "chownSync"),
    ("lchown", "lchownSync"),
    ("fchown", "fchownSync"),
    ("utimes", "utimesSync"),
    ("lutimes", "lutimesSync"),
    ("futimes", "futimesSync"),
    ("mkdtemp", "mkdtempSync"),
    ("realpath", "realpathSync"),
    ("close", "closeSync"),
    ("truncate", "truncateSync"),
    ("ftruncate", "ftruncateSync"),
    ("fsync", "fsyncSync"),
    ("fdatasync", "fdatasyncSync"),
];

const PROMISE_GENERIC: &[(&str, &str)] = &[
    ("mkdir", "mkdirSync"),
    ("rmdir", "rmdirSync"),
    ("rm", "rmSync"),
    ("readdir", "readdirSync"),
    ("unlink", "unlinkSync"),
    ("rename", "renameSync"),
    ("copyFile", "copyFileSync"),
    ("link", "linkSync"),
    ("cp", "cpSync"),
    ("stat", "statSync"),
    ("lstat", "lstatSync"),
    ("statfs", "statfsSync"),
    ("readlink", "readlinkSync"),
    ("symlink", "symlinkSync"),
    ("access", "accessSync"),
    ("chmod", "chmodSync"),
    ("lchmod", "lchmodSync"),
    ("chown", "chownSync"),
    ("lchown", "lchownSync"),
    ("utimes", "utimesSync"),
    ("lutimes", "lutimesSync"),
    ("truncate", "truncateSync"),
    ("mkdtemp", "mkdtempSync"),
    ("realpath", "realpathSync"),
    ("opendir", "opendirSync"),
];

pub fn create_module(vm: &mut Vm) -> Value {
    let built = match setup_classes(vm) {
        Ok(b) => b,
        Err(_) => return Value::Obj(vm.new_object()),
    };
    let m = vm.new_object();
    let mut fns: HashMap<&'static str, Obj> = HashMap::new();
    let put = |m: &Obj, k: &str, v: Value| m.set_prop(key(k), v, WEC);

    for (n, l, f) in SYNC_FNS {
        let fo = vm.native_fn(n, *l, *f);
        put(&m, n, Value::Obj(fo.clone()));
        fns.insert(n, fo);
    }
    let ts = vm.native_fn("toUnixSeconds", 1, to_unix_timestamp);
    let ts = plain_function(vm, ts);
    put(&m, "_toUnixTimestamp", Value::Obj(ts));

    for (n, sync) in CB_FNS {
        let target = fns.get(sync).cloned().map(Value::Obj).unwrap_or(Value::Undefined);
        let w = vm.native_closure("", 0, cb_wrapper, vec![target]);
        let w = plain_function(vm, w);
        put(&m, n, Value::Obj(w.clone()));
        fns.insert(n, w);
    }

    let specials: &[(&str, u32, NativeFn)] = &[
        ("open", 4, open_cb),
        ("exists", 2, exists_cb),
        ("read", 6, read_cb),
        ("write", 2, write_cb),
        ("readv", 4, readv_cb),
        ("writev", 4, writev_cb),
        ("cpSync", 3, cp_sync),
        ("cp", 4, cp_cb),
        ("globSync", 2, glob_sync),
        ("glob", 3, glob_cb),
        ("opendirSync", 2, opendir_sync),
        ("opendir", 3, opendir_cb),
        ("openAsBlob", 2, open_as_blob),
        ("watchFile", 3, watch_file),
        ("unwatchFile", 2, unwatch_file),
        ("watch", 3, watch_fn),
        ("createReadStream", 2, create_read_stream),
        ("createWriteStream", 2, create_write_stream),
    ];
    for (n, l, f) in specials {
        let fo = vm.native_fn("", *l, *f);
        let fo = plain_function(vm, fo);
        put(&m, n, Value::Obj(fo.clone()));
        fns.insert(n, fo);
    }

    let constants = vm.new_object();
    for (k, v) in CONSTANTS {
        constants.set_prop(key(k), Value::Num(*v), WEC);
    }
    put(&m, "constants", Value::Obj(constants.clone()));
    for (k, v) in &CONSTANTS[..4] {
        put(&m, k, Value::Num(*v));
    }
    put(&m, "Stats", Value::Obj(built.stats));
    put(&m, "Dirent", Value::Obj(built.dirent));
    put(&m, "Dir", Value::Obj(built.dir));
    put(&m, "StatWatcher", Value::Obj(built.stat_watcher));
    put(&m, "ReadStream", Value::Obj(built.read_stream.clone()));
    put(&m, "WriteStream", Value::Obj(built.write_stream.clone()));
    put(&m, "FileReadStream", Value::Obj(built.read_stream));
    put(&m, "FileWriteStream", Value::Obj(built.write_stream));

    // fs.promises
    let p = vm.new_object();
    let named: &[(&str, u32, NativeFn)] = &[("readFile", 2, p_read_file), ("writeFile", 3, p_write_file), ("appendFile", 3, p_append_file), ("open", 3, p_open)];
    for (n, l, f) in named {
        let fo = vm.native_fn(n, *l, *f);
        put(&p, n, Value::Obj(fo));
    }
    for (n, sync) in PROMISE_GENERIC {
        let target = fns.get(sync).cloned().map(Value::Obj).unwrap_or(Value::Undefined);
        let w = vm.native_closure("", 0, promise_wrapper, vec![target]);
        put(&p, n, Value::Obj(w));
    }
    let g = vm.native_fn("glob", 2, p_glob);
    put(&p, "glob", Value::Obj(g));
    let w = vm.native_fn("watch", 2, p_watch);
    put(&p, "watch", Value::Obj(w));
    put(&p, "FileHandle", Value::Obj(built.file_handle));
    put(&p, "constants", Value::Obj(constants));
    put(&m, "promises", Value::Obj(p));

    // realpathSync.native / realpath.native
    for n in ["realpathSync", "realpath"] {
        if let Some(f) = fns.get(n) {
            f.set_prop(key("native"), Value::Obj(f.clone()), WEC);
        }
    }
    Value::Obj(m)
}
