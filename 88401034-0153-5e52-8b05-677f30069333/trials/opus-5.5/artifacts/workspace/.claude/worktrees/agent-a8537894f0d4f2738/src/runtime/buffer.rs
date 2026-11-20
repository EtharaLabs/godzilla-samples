// node:buffer — `Buffer`, the `buffer` module and `string_decoder`.
//
// Modelled on the reference runtime, whose Buffer is a small JS class over Uint8Array:
// * `Buffer extends Uint8Array` with only a few own methods (toString, write, slice, equals,
//   compare, toJSON, readUInt8/16LE/16BE/32LE/32BE, writeUInt8, writeUInt32LE); everything else
//   (fill, indexOf, subarray, map, ...) is inherited from %TypedArray%.prototype.
// * Encodings: utf8/utf-8, hex, base64, base64url, latin1/binary, ascii, ucs2/ucs-2/utf16le (but
//   not 'utf-16le', which only `Buffer.isEncoding` knows). Decoders of hex/base64 skip invalid
//   characters; utf8 decoding is TextDecoder's (leading BOM stripped, WHATWG replacement).
// * The reference engine stores strings as UTF-8 with every lone surrogate U+D800..U+DFFF mapped
//   to U+10F800..U+10FFFF; Buffer's utf8 conversions expose that representation.
// * The internal helpers' names show up in error stacks (`at bytesFromString`, `at from`, ...)
//   and the encoding normaliser's `(enc || "utf8").toLowerCase()` reports a non-callable
//   `toLowerCase` with the engine's tier-dependent message (interpreter for the first 8 calls,
//   compiled code afterwards).

use crate::builtins::typedarray::{create_typed_array, ta_bytes, MAX_TA_LENGTH};
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, TraceEntry, Vm};
use std::cell::{Cell, RefCell};

#[derive(Clone)]
struct Intrinsics {
    proto: Obj,
    ctor: Obj,
    ta_subarray: Option<Obj>,
    ta_set: Option<Obj>,
}

thread_local! {
    static STATE: RefCell<Option<Intrinsics>> = RefCell::new(None);
    /// calls of the reference's `normEncoding` helper (tier-up after 8 calls)
    static ENC_CALLS: Cell<u32> = Cell::new(0);
    /// calls of `Buffer.prototype.slice`
    static SLICE_CALLS: Cell<u32> = Cell::new(0);
    static TOSTRING_CALLS: Cell<u32> = Cell::new(0);
    /// calls of the reference's JS `TextEncoder#encode` made by Buffer's utf8 conversions
    static ENCODE_CALLS: Cell<u32> = Cell::new(0);
    static SLOWBUF_CALLS: Cell<u32> = Cell::new(0);
}

/// Number of calls after which the reference engine runs a loop-free function compiled.
const TIER_UP_CALLS: u32 = 8;

fn bump(c: &'static std::thread::LocalKey<Cell<u32>>) -> u32 {
    c.with(|c| {
        let n = c.get();
        c.set(n.saturating_add(1));
        n
    })
}

fn state() -> Option<Intrinsics> {
    STATE.with(|s| s.borrow().clone())
}

pub fn buffer_proto() -> Option<Obj> {
    state().map(|s| s.proto)
}

pub fn buffer_ctor_obj() -> Option<Obj> {
    state().map(|s| s.ctor)
}

#[allow(dead_code)]
pub fn is_buffer_proto(_vm: &Vm, p: &Obj) -> bool {
    STATE.with(|s| s.borrow().as_ref().map_or(false, |st| st.proto.ptr_eq(p)))
}

/// `x instanceof Buffer` (walks the prototype chain; `Buffer.prototype` is immutable).
pub fn is_buffer(_vm: &mut Vm, v: &Value) -> bool {
    let bp = match buffer_proto() {
        Some(p) => p,
        None => return false,
    };
    let mut cur = match v {
        Value::Obj(o) => o.proto(),
        _ => return false,
    };
    let mut guard = 0;
    while let Some(p) = cur {
        if p.ptr_eq(&bp) {
            return true;
        }
        guard += 1;
        if guard > 100_000 {
            break;
        }
        cur = p.proto();
    }
    false
}

/// Run `f` with the reference's internal JS frames `names` (outermost first) on the stack, so
/// that errors created meanwhile list them in `stack`.
pub fn with_frames<T>(vm: &mut Vm, names: &[&str], f: impl FnOnce(&mut Vm) -> JsResult<T>) -> JsResult<T> {
    for n in names {
        vm.trace.push(TraceEntry { name: JsStr::from_str(n) });
    }
    let r = f(vm);
    let keep = vm.trace.len().saturating_sub(names.len());
    vm.trace.truncate(keep);
    r
}

/// The reference engine's TypeError message for calling a non-callable `x.<prop>(...)`: the
/// interpreter names the member expression, compiled code names the callee's type.
pub fn not_callable_msg(interpreted: bool, prop: &str, callee: &Value) -> String {
    if interpreted {
        format!("(intermediate value).{} is not a function", prop)
    } else {
        format!("{} is not a function", jit_type_name(callee))
    }
}

pub fn jit_type_name(v: &Value) -> &'static str {
    match v {
        Value::Undefined | Value::Empty => "undefined",
        Value::Null => "null",
        Value::Bool(_) => "boolean",
        Value::Num(_) => "number",
        Value::Str(_) => "string",
        Value::Sym(_) => "symbol",
        Value::BigInt(_) => "bigint",
        Value::Obj(_) => "value",
    }
}

fn key(s: &str) -> PropKey {
    PropKey::from_str(s)
}

fn type_error_code(vm: &mut Vm, kind: &str, msg: &str, code: &str) -> Value {
    let e = vm.make_error(kind, msg);
    if let Value::Obj(o) = &e {
        o.set_prop(key("code"), Value::str(code), WEC);
    }
    e
}

/// ToUint8
pub fn to_u8(f: f64) -> u8 {
    if !f.is_finite() {
        0
    } else {
        f.trunc().rem_euclid(256.0) as u8
    }
}

/// `x & 0xff` (ToNumeric; BigInt operands throw the mixing TypeError)
fn and_ff(vm: &mut Vm, v: &Value) -> JsResult<f64> {
    let n = int32_of(vm, v)?;
    Ok((n & 0xff) as f64)
}

/// ToInt32 through ToNumeric (BigInt -> mixing TypeError)
fn int32_of(vm: &mut Vm, v: &Value) -> JsResult<i32> {
    let n = vm.to_numeric(v)?;
    match n {
        Value::Num(f) => Ok(crate::builtins::number::to_uint32(f) as i32),
        _ => vm.throw_type("Cannot mix BigInt and other types, use explicit conversions"),
    }
}

fn uint32_of(vm: &mut Vm, v: &Value) -> JsResult<u32> {
    let n = vm.to_numeric(v)?;
    match n {
        Value::Num(f) => Ok(crate::builtins::number::to_uint32(f)),
        _ => vm.throw_type("Cannot mix BigInt and other types, use explicit conversions"),
    }
}

/// Math.min over already-converted numbers.
fn js_min(xs: &[f64]) -> f64 {
    let mut m = f64::INFINITY;
    for &x in xs {
        if x.is_nan() {
            return f64::NAN;
        }
        if x < m || (x == 0.0 && m == 0.0 && x.is_sign_negative()) {
            m = x;
        }
    }
    m
}

/// ToIndex with the reference engine's message.
fn to_index_ref(vm: &mut Vm, v: &Value) -> JsResult<usize> {
    if v.is_undefined() {
        return Ok(0);
    }
    let n = vm.to_integer_or_infinity(v)?;
    if !(0.0..=9007199254740991.0).contains(&n) {
        return vm.throw_range("index out of range");
    }
    Ok(n as usize)
}

/// Relative index as used by %TypedArray%.prototype.subarray.
fn relative(vm: &mut Vm, v: &Value, len: usize, default: usize) -> JsResult<usize> {
    if v.is_undefined() {
        return Ok(default);
    }
    let n = vm.to_integer_or_infinity(v)?;
    Ok(if n < 0.0 { (len as f64 + n).max(0.0) as usize } else { n.min(len as f64) as usize })
}

fn relative_f(n: f64, len: usize) -> usize {
    if n.is_nan() {
        return 0;
    }
    let n = n.trunc();
    if n < 0.0 {
        (len as f64 + n).max(0.0) as usize
    } else {
        n.min(len as f64) as usize
    }
}

/// (kind, element length, out of bounds) of a typed array
fn ta_info(o: &Obj) -> Option<(TAKind, usize, bool)> {
    match &o.borrow().kind {
        ObjKind::TypedArray(t) => Some((t.kind, t.len(), t.is_out_of_bounds())),
        _ => None,
    }
}

fn is_byte_kind(k: TAKind) -> bool {
    matches!(k, TAKind::Uint8 | TAKind::Int8 | TAKind::Uint8C)
}

/// Element values of a typed array converted to bytes (`new Uint8Array(ta)`).
fn ta_to_u8_values(vm: &mut Vm, o: &Obj) -> JsResult<Vec<u8>> {
    let (kind, _, oob) = match ta_info(o) {
        Some(i) => i,
        None => return Ok(Vec::new()),
    };
    if oob {
        return vm.throw_type("Cannot perform Construct on a detached ArrayBuffer");
    }
    if is_byte_kind(kind) {
        return Ok(ta_bytes(o));
    }
    if kind.is_bigint() {
        return vm.throw_type("Cannot convert a BigInt value to a number");
    }
    Ok(crate::builtins::typedarray::ta_values_vec(o).iter().map(|v| to_u8(v.as_num().unwrap_or(0.0))).collect())
}

// ============================================================================================
// encodings
// ============================================================================================

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Enc {
    Utf8,
    Hex,
    Base64,
    Base64Url,
    Latin1,
    Ascii,
    Ucs2,
}

impl Enc {
    /// Names accepted by the reference's string conversions (already lower-cased).
    pub fn parse(lower: &str) -> Option<Enc> {
        Some(match lower {
            "utf8" | "utf-8" => Enc::Utf8,
            "hex" => Enc::Hex,
            "base64" => Enc::Base64,
            "base64url" => Enc::Base64Url,
            "latin1" | "binary" => Enc::Latin1,
            "ascii" => Enc::Ascii,
            "ucs2" | "ucs-2" | "utf16le" => Enc::Ucs2,
            _ => return None,
        })
    }
    pub fn name(self) -> &'static str {
        match self {
            Enc::Utf8 => "utf8",
            Enc::Hex => "hex",
            Enc::Base64 => "base64",
            Enc::Base64Url => "base64url",
            Enc::Latin1 => "latin1",
            Enc::Ascii => "ascii",
            Enc::Ucs2 => "utf16le",
        }
    }
}

/// Canonical name of an encoding accepted by Buffer's string conversions (case-insensitive).
pub fn norm_encoding(s: &str) -> Option<&'static str> {
    Enc::parse(&s.to_lowercase()).map(Enc::name)
}

/// UTF-16 -> the reference's UTF-8 (lone surrogates become U+10F800 + (u - 0xD800); a valid
/// pair whose code point would collide with that range is stored as two lone surrogates).
pub fn utf8_encode(u: &[u16]) -> Vec<u8> {
    fn push(out: &mut Vec<u8>, cp: u32) {
        if cp < 0x80 {
            out.push(cp as u8);
        } else if cp < 0x800 {
            out.push(0xC0 | (cp >> 6) as u8);
            out.push(0x80 | (cp & 0x3F) as u8);
        } else if cp < 0x10000 {
            out.push(0xE0 | (cp >> 12) as u8);
            out.push(0x80 | ((cp >> 6) & 0x3F) as u8);
            out.push(0x80 | (cp & 0x3F) as u8);
        } else {
            out.push(0xF0 | (cp >> 18) as u8);
            out.push(0x80 | ((cp >> 12) & 0x3F) as u8);
            out.push(0x80 | ((cp >> 6) & 0x3F) as u8);
            out.push(0x80 | (cp & 0x3F) as u8);
        }
    }
    let mut out = Vec::with_capacity(u.len() + u.len() / 2);
    let mut i = 0;
    while i < u.len() {
        let c = u[i] as u32;
        if c < 0x80 {
            out.push(c as u8);
            i += 1;
            continue;
        }
        if (0xD800..0xDC00).contains(&c) && i + 1 < u.len() && (0xDC00..0xE000).contains(&(u[i + 1] as u32)) {
            let cp = 0x10000 + ((c - 0xD800) << 10) + (u[i + 1] as u32 - 0xDC00);
            if cp < 0x10F800 {
                push(&mut out, cp);
                i += 2;
                continue;
            }
        }
        if (0xD800..0xE000).contains(&c) {
            push(&mut out, c + 0x102000);
        } else {
            push(&mut out, c);
        }
        i += 1;
    }
    out
}

/// UTF-8 -> UTF-16 like the reference's TextDecoder: optional leading BOM stripped, WHATWG
/// replacement of invalid sequences, U+10F800..U+10FFFF read back as lone surrogates.
pub fn utf8_decode_opt(b: &[u8], strip_bom: bool) -> Vec<u16> {
    let mut out = Vec::with_capacity(b.len());
    let mut i = if strip_bom && b.starts_with(&[0xEF, 0xBB, 0xBF]) { 3 } else { 0 };
    while i < b.len() {
        let c = b[i];
        if c < 0x80 {
            out.push(c as u16);
            i += 1;
            continue;
        }
        let (need, mut cp, mut lo, mut hi) = match c {
            0xC2..=0xDF => (1usize, (c & 0x1F) as u32, 0x80u8, 0xBFu8),
            0xE0 => (2, (c & 0x0F) as u32, 0xA0, 0xBF),
            0xE1..=0xEC | 0xEE..=0xEF => (2, (c & 0x0F) as u32, 0x80, 0xBF),
            0xED => (2, (c & 0x0F) as u32, 0x80, 0x9F),
            0xF0 => (3, (c & 0x07) as u32, 0x90, 0xBF),
            0xF1..=0xF3 => (3, (c & 0x07) as u32, 0x80, 0xBF),
            0xF4 => (3, (c & 0x07) as u32, 0x80, 0x8F),
            _ => {
                out.push(0xFFFD);
                i += 1;
                continue;
            }
        };
        let mut j = 1;
        let mut ok = true;
        while j <= need {
            if i + j >= b.len() {
                ok = false;
                break;
            }
            let cc = b[i + j];
            if cc < lo || cc > hi {
                ok = false;
                break;
            }
            cp = (cp << 6) | (cc & 0x3F) as u32;
            lo = 0x80;
            hi = 0xBF;
            j += 1;
        }
        if !ok {
            out.push(0xFFFD);
            i += j;
            continue;
        }
        i += need + 1;
        if cp >= 0x10F800 {
            out.push((cp - 0x102000) as u16);
        } else if cp >= 0x10000 {
            let v = cp - 0x10000;
            out.push(0xD800 + (v >> 10) as u16);
            out.push(0xDC00 + (v & 0x3FF) as u16);
        } else {
            out.push(cp as u16);
        }
    }
    out
}

pub fn utf8_decode(b: &[u8]) -> Vec<u16> {
    utf8_decode_opt(b, true)
}

fn hex_val(c: u16) -> Option<u8> {
    match c {
        0x30..=0x39 => Some((c - 0x30) as u8),
        0x41..=0x46 => Some((c - 0x41 + 10) as u8),
        0x61..=0x66 => Some((c - 0x61 + 10) as u8),
        _ => None,
    }
}

/// Lenient hex: non-hex characters are dropped, then pairs are read (an odd last digit is
/// ignored).
fn hex_decode_loose(u: &[u16]) -> Vec<u8> {
    let digits: Vec<u8> = u.iter().filter_map(|&c| hex_val(c)).collect();
    digits.chunks_exact(2).map(|p| (p[0] << 4) | p[1]).collect()
}

fn b64_val(c: u16) -> Option<u32> {
    match c {
        0x41..=0x5A => Some((c - 0x41) as u32),
        0x61..=0x7A => Some((c - 0x61 + 26) as u32),
        0x30..=0x39 => Some((c - 0x30 + 52) as u32),
        0x2B | 0x2D => Some(62),
        0x2F | 0x5F => Some(63),
        _ => None,
    }
}

/// Lenient base64/base64url: every character outside both alphabets (including '=') is
/// dropped; each group of up to 4 symbols yields 1 + (n > 2) + (n > 3) bytes.
fn base64_decode_loose(u: &[u16]) -> Vec<u8> {
    let vals: Vec<u32> = u.iter().filter_map(|&c| b64_val(c)).collect();
    let mut out = Vec::with_capacity(vals.len() * 3 / 4 + 1);
    for chunk in vals.chunks(4) {
        let mut n = 0u32;
        for (j, v) in chunk.iter().enumerate() {
            n |= v << (18 - 6 * j);
        }
        out.push((n >> 16) as u8);
        if chunk.len() > 2 {
            out.push((n >> 8) as u8);
        }
        if chunk.len() > 3 {
            out.push(n as u8);
        }
    }
    out
}

pub fn encode_units(u: &[u16], e: Enc) -> Vec<u8> {
    match e {
        Enc::Utf8 => utf8_encode(u),
        Enc::Hex => hex_decode_loose(u),
        Enc::Base64 | Enc::Base64Url => base64_decode_loose(u),
        Enc::Latin1 | Enc::Ascii => u.iter().map(|&c| c as u8).collect(),
        Enc::Ucs2 => {
            let mut v = Vec::with_capacity(u.len() * 2);
            for &c in u {
                v.push(c as u8);
                v.push((c >> 8) as u8);
            }
            v
        }
    }
}

pub fn decode_units(b: &[u8], e: Enc) -> Vec<u16> {
    match e {
        Enc::Utf8 => utf8_decode(b),
        Enc::Hex => {
            const H: &[u8; 16] = b"0123456789abcdef";
            let mut v = Vec::with_capacity(b.len() * 2);
            for &x in b {
                v.push(H[(x >> 4) as usize] as u16);
                v.push(H[(x & 15) as usize] as u16);
            }
            v
        }
        Enc::Base64 => crate::runtime::encoding::base64_encode(b, false).encode_utf16().collect(),
        Enc::Base64Url => crate::runtime::encoding::base64_encode(b, true).trim_end_matches('=').encode_utf16().collect(),
        Enc::Latin1 => b.iter().map(|&x| x as u16).collect(),
        Enc::Ascii => b.iter().map(|&x| (x & 0x7f) as u16).collect(),
        Enc::Ucs2 => b.chunks_exact(2).map(|c| c[0] as u16 | ((c[1] as u16) << 8)).collect(),
    }
}

/// Encode a string with a canonical encoding name (see `norm_encoding`).
pub fn encode_string(s: &JsStr, encoding: &str) -> Vec<u8> {
    encode_units(s.units(), Enc::parse(encoding).unwrap_or(Enc::Utf8))
}

/// Decode bytes with a canonical encoding name (see `norm_encoding`).
pub fn decode_bytes(b: &[u8], encoding: &str) -> JsStr {
    JsStr::from_units(decode_units(b, Enc::parse(encoding).unwrap_or(Enc::Utf8)))
}

/// `normEncoding(enc)` = `(enc || "utf8").toLowerCase()`; returns the lowered value.
fn norm_enc_value(vm: &mut Vm, enc: &Value) -> JsResult<Value> {
    let calls = bump(&ENC_CALLS);
    if !enc.truthy() {
        return Ok(Value::str("utf8"));
    }
    if let Value::Str(s) = enc {
        if s.units().iter().all(|&u| u < 0x80) {
            let low: Vec<u16> = s.units().iter().map(|&u| if (0x41..=0x5A).contains(&u) { u + 32 } else { u }).collect();
            return Ok(Value::Str(JsStr::from_units(low)));
        }
    }
    with_frames(vm, &["normEncoding"], |vm| {
        let f = vm.get_prop_of(enc, &key("toLowerCase"))?;
        if !f.is_callable() {
            let m = not_callable_msg(calls < TIER_UP_CALLS, "toLowerCase", &f);
            return vm.throw_type(m);
        }
        vm.call(&f, enc.clone(), &[])
    })
}

/// The encoding switch of `bytesFromString` / `stringFromBytes`.
fn enc_of_lowered(vm: &mut Vm, low: &Value) -> JsResult<Enc> {
    if let Value::Str(s) = low {
        if let Some(e) = Enc::parse(&s.to_rust_string()) {
            return Ok(e);
        }
    }
    let s = vm.to_string(low)?;
    vm.throw_type(format!("Unknown encoding: {}", s))
}

/// Resolve an encoding argument like the reference's string conversions do.
pub fn resolve_encoding(vm: &mut Vm, enc: &Value) -> JsResult<Enc> {
    let low = norm_enc_value(vm, enc)?;
    enc_of_lowered(vm, &low)
}

/// Code units of a non-string value for the latin1/ascii/ucs2 conversions
/// (`s.length` / `s.charCodeAt(i)`).
fn char_codes_of(vm: &mut Vm, s: &Value, interpreted: bool) -> JsResult<Vec<u16>> {
    let len = vm.get_prop_of(s, &key("length"))?;
    let n = vm.to_number(&len)?;
    let mut out = Vec::new();
    let mut i = 0f64;
    while i < n {
        let f = vm.get_prop_of(s, &key("charCodeAt"))?;
        if !f.is_callable() {
            let m = not_callable_msg(interpreted, "charCodeAt", &f);
            return vm.throw_type(m);
        }
        let c = vm.call(&f, s.clone(), &[Value::Num(i)])?;
        out.push(int32_of(vm, &c)? as u16);
        i += 1.0;
        if out.len() > MAX_TA_LENGTH * 2 {
            break;
        }
    }
    Ok(out)
}

/// Code units of `s` as seen by one of the encoders (strings directly; other values only reach
/// this through `Buffer.prototype.write`).
fn units_for_encoding(vm: &mut Vm, s: &Value, e: Enc, interpreted: bool) -> JsResult<Vec<u16>> {
    if let Value::Str(st) = s {
        return Ok(st.units().to_vec());
    }
    match e {
        Enc::Utf8 => match s {
            Value::Undefined => Ok(Vec::new()),
            Value::Sym(sym) => Ok(sym.descriptive_string().encode_utf16().collect()),
            other => Ok(vm.to_string(other)?.units().to_vec()),
        },
        Enc::Hex | Enc::Base64 | Enc::Base64Url => {
            let f = vm.get_prop_of(s, &key("replace"))?;
            if !f.is_callable() {
                let m = not_callable_msg(interpreted, "replace", &f);
                return vm.throw_type(m);
            }
            // s.replace(/[^...]/g, "")
            let pattern = if e == Enc::Hex { "[^0-9a-fA-F]" } else { "[^A-Za-z0-9+/\\-_]" };
            let re = match vm.global.get_own_str("RegExp") {
                Some(rc) => vm.construct(&rc, &[Value::str(pattern), Value::str("g")], None)?,
                None => Value::Undefined,
            };
            let r = vm.call(&f, s.clone(), &[re, Value::str("")])?;
            Ok(vm.to_string(&r)?.units().to_vec())
        }
        Enc::Latin1 | Enc::Ascii | Enc::Ucs2 => char_codes_of(vm, s, interpreted),
    }
}

/// `bytesFromString(s, enc)`; the caller's frames must already be on the stack. The utf8 path
/// is a tail call in the reference (no `bytesFromString` frame for its size error).
fn bytes_from_string(vm: &mut Vm, s: &Value, enc: &Value) -> JsResult<Vec<u8>> {
    // the reference never compiles bytesFromString: its member-call errors keep the
    // interpreter's wording
    let (bytes, e) = with_frames(vm, &["bytesFromString"], |vm| {
        let e = resolve_encoding(vm, enc)?;
        let units = units_for_encoding(vm, s, e, true)?;
        let bytes = encode_units(&units, e);
        if e != Enc::Utf8 && bytes.len() > MAX_TA_LENGTH {
            return vm.throw_range("Invalid typed array length");
        }
        Ok((bytes, e))
    })?;
    if e == Enc::Utf8 {
        // `return textEncoder.encode(s)`: bytesFromString's frame is gone (tail call); the
        // JS `encode` keeps its own frame once it has been compiled (8 calls)
        let encode_calls = bump(&ENCODE_CALLS);
        if bytes.len() > MAX_TA_LENGTH {
            let frames: &[&str] = if encode_calls >= TIER_UP_CALLS { &["encode"] } else { &[] };
            return with_frames(vm, frames, |vm| vm.throw_range("Invalid typed array length"));
        }
    }
    Ok(bytes)
}

/// What `subarray` returned in `stringFromBytes` / `slice`: unsigned byte elements, or other
/// element values (with the raw bytes when it is a typed array).
enum Sub {
    Bytes(Vec<u8>),
    Elems { vals: Vec<Value>, raw: Option<Vec<u8>> },
}

impl Sub {
    /// The bytes `new Uint8Array(sub)` would hold.
    fn into_bytes(self, vm: &mut Vm) -> JsResult<Vec<u8>> {
        match self {
            Sub::Bytes(b) => Ok(b),
            Sub::Elems { vals, .. } => {
                let mut out = Vec::with_capacity(vals.len());
                for v in vals {
                    let n = match v {
                        Value::BigInt(b) => return vm.throw_type(format!("Cannot convert a BigInt value to a number{}", if b.is_zero() { "" } else { "" })),
                        other => vm.to_number(&other)?,
                    };
                    out.push(to_u8(n));
                }
                Ok(out)
            }
        }
    }
}

/// The reference's generic decoders over element values (non-byte typed arrays and
/// array-likes): hex uses `v.toString(16)`, base64 bit operations on the values,
/// latin1 `String.fromCharCode`, ascii `v & 0x7f`, ucs2 `b0 | (b1 << 8)`.
fn decode_elems(vm: &mut Vm, vals: &[Value], e: Enc) -> JsResult<Vec<u16>> {
    let i32_of = |vm: &mut Vm, v: &Value| -> JsResult<i32> { int32_of(vm, v) };
    match e {
        Enc::Hex => {
            let mut out: Vec<u16> = Vec::new();
            for v in vals {
                let h = call_member_compiled(vm, v, "toString", &[Value::Num(16.0)])?;
                let hs = vm.to_string(&h)?;
                // padStart(2, "0")
                if hs.len() < 2 {
                    out.extend(std::iter::repeat(0x30).take(2 - hs.len()));
                }
                out.extend_from_slice(hs.units());
            }
            Ok(out)
        }
        Enc::Base64 | Enc::Base64Url => {
            let t: &[u8; 64] = if e == Enc::Base64 { b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/" } else { b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" };
            let mut out = Vec::new();
            let mut i = 0;
            while i < vals.len() {
                let b0 = i32_of(vm, &vals[i])?;
                let b1 = if i + 1 < vals.len() { i32_of(vm, &vals[i + 1])? } else { 0 };
                let b2 = if i + 2 < vals.len() { i32_of(vm, &vals[i + 2])? } else { 0 };
                let n = b0.wrapping_shl(16) | b1.wrapping_shl(8) | b2;
                out.push(t[((n >> 18) & 63) as usize] as u16);
                out.push(t[((n >> 12) & 63) as usize] as u16);
                if i + 1 < vals.len() {
                    out.push(t[((n >> 6) & 63) as usize] as u16);
                } else if e == Enc::Base64 {
                    out.push(b'=' as u16);
                }
                if i + 2 < vals.len() {
                    out.push(t[(n & 63) as usize] as u16);
                } else if e == Enc::Base64 {
                    out.push(b'=' as u16);
                }
                i += 3;
            }
            Ok(out)
        }
        Enc::Latin1 => {
            let mut out = Vec::with_capacity(vals.len());
            for v in vals {
                out.push(i32_of(vm, v)? as u16);
            }
            Ok(out)
        }
        Enc::Ascii => {
            let mut out = Vec::with_capacity(vals.len());
            for v in vals {
                out.push((i32_of(vm, v)? & 0x7f) as u16);
            }
            Ok(out)
        }
        Enc::Ucs2 => {
            let mut out = Vec::with_capacity(vals.len() / 2);
            for p in vals.chunks_exact(2) {
                let a = i32_of(vm, &p[0])?;
                let b = i32_of(vm, &p[1])?;
                out.push((a | b.wrapping_shl(8)) as u16);
            }
            Ok(out)
        }
        Enc::Utf8 => Ok(Vec::new()),
    }
}

/// `stringFromBytes(bytes, enc, start, end)` with its frame.
fn string_from_bytes(vm: &mut Vm, bytes: &Value, enc: &Value, start: &Value, end: &Value) -> JsResult<Value> {
    with_frames(vm, &["stringFromBytes"], |vm| {
        let sub = subarray_of(vm, bytes, start, end, false)?;
        let e = resolve_encoding(vm, enc)?;
        let units = match sub {
            Sub::Bytes(b) => {
                if b.len() > (1 << 29) {
                    return vm.throw_range("Invalid string length");
                }
                decode_units(&b, e)
            }
            Sub::Elems { vals, raw } => {
                if e == Enc::Utf8 {
                    match raw {
                        Some(r) => decode_units(&r, e),
                        None => return with_frames(vm, &["decode"], |vm| vm.throw_type("TextDecoder.decode expects a BufferSource")),
                    }
                } else {
                    decode_elems(vm, &vals, e)?
                }
            }
        };
        Ok(Value::Str(JsStr::from_units(units)))
    })
}

/// `x.subarray(start, end)` evaluated for its bytes. `interpreted` selects the not-callable
/// message tier.
fn subarray_of(vm: &mut Vm, x: &Value, start: &Value, end: &Value, interpreted: bool) -> JsResult<Sub> {
    let f = vm.get_prop_of(x, &key("subarray"))?;
    let intrinsic = state().and_then(|s| s.ta_subarray).map_or(false, |i| matches!(&f, Value::Obj(fo) if fo.ptr_eq(&i)));
    if intrinsic {
        if let Value::Obj(o) = x {
            if let Some((kind, len, oob)) = ta_info(o) {
                if !oob && matches!(kind, TAKind::Uint8 | TAKind::Uint8C) {
                    let s = relative(vm, start, len, 0)?;
                    let e = relative(vm, end, len, len)?;
                    let all = ta_bytes(o);
                    let bytes = if e > s { all[s..e].to_vec() } else { Vec::new() };
                    return Ok(Sub::Bytes(bytes));
                }
            }
        }
    }
    if !f.is_callable() {
        let m = not_callable_msg(interpreted, "subarray", &f);
        return vm.throw_type(m);
    }
    let r = vm.call(&f, x.clone(), &[start.clone(), end.clone()])?;
    if let Value::Obj(o) = &r {
        if let Some((kind, _, _)) = ta_info(o) {
            if matches!(kind, TAKind::Uint8 | TAKind::Uint8C) {
                return Ok(Sub::Bytes(ta_bytes(o)));
            }
            let vals = crate::builtins::typedarray::ta_values_vec(o);
            return Ok(Sub::Elems { vals, raw: Some(ta_bytes(o)) });
        }
        let vals = crate::builtins::array::array_like_to_vec(vm, &r)?;
        return Ok(Sub::Elems { vals, raw: None });
    }
    Ok(Sub::Elems { vals: Vec::new(), raw: None })
}

// ============================================================================================
// construction
// ============================================================================================

/// A fresh Buffer holding `bytes` (RangeError beyond the engine's 1 MiB typed-array limit).
pub fn new_buffer(vm: &mut Vm, bytes: Vec<u8>) -> JsResult<Obj> {
    if bytes.len() > MAX_TA_LENGTH {
        return vm.throw_range("Invalid typed array length");
    }
    let t = crate::builtins::typedarray::typed_array_from_bytes(vm, bytes);
    if let Some(p) = buffer_proto() {
        t.borrow_mut().proto = Some(p);
    }
    Ok(t)
}

pub fn new_buffer_value(vm: &mut Vm, bytes: Vec<u8>) -> JsResult<Value> {
    Ok(Value::Obj(new_buffer(vm, bytes)?))
}

/// `Reflect.construct(Uint8Array, args, nt)` with the reference's messages for views on an
/// ArrayBuffer.
fn construct_u8(vm: &mut Vm, args: &[Value], nt: &Obj) -> JsResult<Value> {
    if let Some(Value::Obj(o)) = args.first() {
        let ab = match &o.borrow().kind {
            ObjKind::ArrayBuffer(b) if !b.borrow().detached && b.borrow().max_len.is_none() => Some(b.clone()),
            _ => None,
        };
        if let Some(buf) = ab {
            let off = to_index_ref(vm, args.get(1).unwrap_or(&Value::Undefined))?;
            let blen = buf.borrow().bytes.len();
            let len_arg = args.get(2).cloned().unwrap_or(Value::Undefined);
            let len = if len_arg.is_undefined() {
                if off > blen {
                    return vm.throw_range("byteOffset is out of bounds");
                }
                blen - off
            } else {
                let l = to_index_ref(vm, &len_arg)?;
                if off + l > blen {
                    return vm.throw_range("invalid typed array length");
                }
                l
            };
            let fallback = vm.intr.ta_protos[1].clone();
            let proto = vm.proto_from_nt(&Some(nt.clone()), &fallback)?;
            return Ok(Value::Obj(Obj::with_class(
                Some(proto),
                ObjKind::TypedArray(Box::new(TypedArrayData { kind: TAKind::Uint8, buffer: o.clone(), buf, offset: off, length: Some(len) })),
                "Uint8Array",
            )));
        }
    }
    let u8c = vm.intr.ta_ctors[1].clone();
    vm.construct(&Value::Obj(u8c), args, Some(&Value::Obj(nt.clone())))
}

/// `new Buffer(...args)` from the internal code (frame `Buffer`).
pub fn construct_buffer(vm: &mut Vm, args: &[Value]) -> JsResult<Obj> {
    let ctor = match buffer_ctor_obj() {
        Some(c) => c,
        None => return vm.throw_type("Buffer is not initialized"),
    };
    let r = with_frames(vm, &["Buffer"], |vm| construct_u8(vm, args, &ctor))?;
    match r {
        Value::Obj(o) => Ok(o),
        _ => vm.throw_type("Buffer construction failed"),
    }
}

/// A Buffer of `n` zero bytes, as `new Buffer(n)` (n already a valid length).
fn zeroed_buffer(vm: &mut Vm, n: usize) -> JsResult<Obj> {
    let p = buffer_proto();
    with_frames(vm, &["Buffer"], |vm| create_typed_array(vm, TAKind::Uint8, n, p))
}

fn buffer_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = match &a.new_target {
        Some(nt) => nt.clone(),
        None => return vm.throw_type("Class constructor cannot be invoked without 'new'"),
    };
    with_frames(vm, &["Buffer"], |vm| construct_u8(vm, a.args, &nt))
}

/// bytes of a string (utf8), Buffer/TypedArray/ArrayBuffer/DataView, or array-like.
#[allow(dead_code)]
pub fn bytes_of(vm: &mut Vm, v: &Value) -> JsResult<Vec<u8>> {
    match v {
        Value::Obj(o) => {
            let is_bin = matches!(o.borrow().kind, ObjKind::TypedArray(_) | ObjKind::ArrayBuffer(_) | ObjKind::DataView(_));
            if is_bin {
                return Ok(ta_bytes(o));
            }
            let vals = crate::builtins::array::array_like_to_vec(vm, v)?;
            let mut out = Vec::with_capacity(vals.len());
            for x in vals {
                out.push(to_u8(vm.to_number(&x)?));
            }
            Ok(out)
        }
        Value::Str(s) => Ok(utf8_encode(s.units())),
        _ => vm.throw_type("Buffer.from: unsupported value"),
    }
}

fn is_array_buffer_instance(vm: &mut Vm, v: &Value) -> bool {
    let abp = vm.intr.array_buffer_proto.clone();
    let mut cur = match v {
        Value::Obj(o) => o.proto(),
        _ => return false,
    };
    let mut guard = 0;
    while let Some(p) = cur {
        if p.ptr_eq(&abp) {
            return true;
        }
        guard += 1;
        if guard > 100_000 {
            break;
        }
        cur = p.proto();
    }
    false
}

/// `Buffer.from(value, encOrOffset, length)` without its frame.
fn from_impl(vm: &mut Vm, value: &Value, enc_or_off: &Value, length: &Value) -> JsResult<Value> {
    if let Value::Str(_) = value {
        let bytes = bytes_from_string(vm, value, enc_or_off)?;
        return new_buffer_value(vm, bytes);
    }
    if is_array_buffer_instance(vm, value) {
        let off = if enc_or_off.truthy() { enc_or_off.clone() } else { Value::Num(0.0) };
        let u8p = vm.intr.ta_ctors[1].clone();
        let args: Vec<Value> = if length.is_undefined() { vec![value.clone(), off] } else { vec![value.clone(), off, length.clone()] };
        let u = construct_u8(vm, &args, &u8p)?;
        let bytes = match &u {
            Value::Obj(o) => ta_to_u8_values(vm, o)?,
            _ => Vec::new(),
        };
        return new_buffer_value(vm, bytes);
    }
    if let Value::Obj(o) = value {
        let view = matches!(o.borrow().kind, ObjKind::TypedArray(_) | ObjKind::DataView(_));
        if view {
            let is_ta = ta_info(o).is_some();
            let bytes = if is_ta { ta_to_u8_values(vm, o)? } else { Vec::new() };
            return new_buffer_value(vm, bytes);
        }
    }
    let is_arr = crate::builtins::array::is_array(vm, value)?;
    let array_like = is_arr || (value.truthy() && matches!(vm.get_prop_of(value, &key("length"))?, Value::Num(_)));
    if array_like {
        let len_v = vm.get_prop_of(value, &key("length"))?;
        let b = construct_buffer(vm, &[len_v])?;
        let bv = Value::Obj(b.clone());
        let mut i = 0usize;
        // fast path for genuine dense arrays
        let dense: Option<Vec<Value>> = match value {
            Value::Obj(o) => match &o.borrow().kind {
                ObjKind::Array(ad) if !ad.sparse && ad.dense.iter().all(|x| !x.is_empty()) && ad.dense.len() == ad.len as usize => Some(ad.dense.clone()),
                _ => None,
            },
            _ => None,
        };
        if let Some(vals) = dense {
            for v in vals.iter() {
                let n = and_ff(vm, v)?;
                crate::builtins::typedarray::ta_set_index(vm, &b, i as f64, &Value::Num(n))?;
                i += 1;
            }
            return Ok(bv);
        }
        loop {
            let l = vm.get_prop_of(value, &key("length"))?;
            let lim = vm.to_number(&l)?;
            if !((i as f64) < lim) {
                break;
            }
            let x = vm.get_prop_of(value, &PropKey::from_index(i as u32))?;
            let n = and_ff(vm, &x)?;
            vm.set_elem(&bv, &Value::Num(i as f64), Value::Num(n), true)?;
            i += 1;
        }
        return Ok(bv);
    }
    vm.throw_type("Buffer.from: unsupported value")
}

fn buffer_from(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["from"], |vm| from_impl(vm, &a.arg(0), &a.arg(1), &a.arg(2)))
}

/// `Buffer.from(value)` for the runtime's own modules (zlib, crypto, ...).
pub fn buffer_from_value(vm: &mut Vm, value: &Value, enc: &Value) -> JsResult<Value> {
    with_frames(vm, &["from"], |vm| from_impl(vm, value, enc, &Value::Undefined))
}

fn buffer_alloc(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["alloc"], |vm| {
        let size = a.arg(0);
        let b = construct_buffer(vm, &[size.clone()])?;
        let fill = a.arg(1);
        let is_zero = matches!(fill, Value::Num(n) if n == 0.0);
        if !fill.is_undefined() && !is_zero {
            let len = ta_info(&b).map(|i| i.1).unwrap_or(0);
            if let Value::Str(_) = fill {
                let src = bytes_from_string(vm, &fill, &a.arg(2))?;
                // for (let i = 0; i < size; i++) b[i] = src.length ? src[i % src.length] : 0;
                let lim = match vm.to_primitive(&size, crate::ops::Hint::Number)? {
                    Value::BigInt(bi) => bi.to_f64(),
                    p => vm.to_number(&p)?,
                };
                let count = if lim.is_nan() || lim <= 0.0 { 0 } else { (lim.ceil().min(len as f64)) as usize };
                let data: Vec<u8> = (0..count).map(|i| if src.is_empty() { 0 } else { src[i % src.len()] }).collect();
                write_bytes(&b, 0, &data);
            } else {
                let n = and_ff(vm, &fill)? as u8;
                write_bytes(&b, 0, &vec![n; len]);
            }
        }
        Ok(Value::Obj(b))
    })
}

/// `Buffer.alloc(size)` (zero-filled) for the runtime's own modules.
pub fn buffer_alloc_value(vm: &mut Vm, size: &Value) -> JsResult<Obj> {
    with_frames(vm, &["alloc"], |vm| construct_buffer(vm, &[size.clone()]))
}

/// `buf.toString(enc)` called from the runtime's own JS-like code (counts towards the
/// method's tier-up like a user call).
pub fn buffer_to_string(vm: &mut Vm, buf: &Value, enc: &Value) -> JsResult<Value> {
    if bump(&TOSTRING_CALLS) >= TIER_UP_CALLS {
        with_frames(vm, &["toString"], |vm| string_from_bytes(vm, buf, enc, &Value::Undefined, &Value::Undefined))
    } else {
        string_from_bytes(vm, buf, enc, &Value::Undefined, &Value::Undefined)
    }
}

fn buffer_alloc_unsafe(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["allocUnsafe"], |vm| Ok(Value::Obj(construct_buffer(vm, &[a.arg(0)])?)))
}

fn buffer_alloc_unsafe_slow(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["allocUnsafeSlow"], |vm| Ok(Value::Obj(construct_buffer(vm, &[a.arg(0)])?)))
}

fn buffer_is_buffer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ctor = match buffer_ctor_obj() {
        Some(c) => c,
        None => return Ok(Value::Bool(false)),
    };
    Ok(Value::Bool(vm.instance_of(&a.arg(0), &Value::Obj(ctor))?))
}

fn buffer_is_encoding(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(match a.arg(0) {
        Value::Str(s) => {
            let l = s.to_rust_string().to_lowercase();
            matches!(
                l.as_str(),
                "utf8" | "utf-8" | "hex" | "base64" | "base64url" | "latin1" | "binary" | "ascii" | "ucs2" | "ucs-2" | "utf16le" | "utf-16le"
            )
        }
        _ => false,
    }))
}

pub fn write_bytes(o: &Obj, start: usize, data: &[u8]) {
    let b = o.borrow();
    if let ObjKind::TypedArray(t) = &b.kind {
        let len = t.len() * t.kind.size();
        let mut bb = t.buf.borrow_mut();
        for (i, x) in data.iter().enumerate() {
            if start + i >= len {
                break;
            }
            bb.bytes[t.offset + start + i] = *x;
        }
    }
}

fn byte_length(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["byteLength"], |vm| {
        let s = a.arg(0);
        if let Value::Str(_) = s {
            let b = bytes_from_string(vm, &s, &a.arg(1))?;
            return Ok(Value::Num(b.len() as f64));
        }
        // str.byteLength ?? str.length ?? 0
        let bl = vm.get_prop_of(&s, &key("byteLength"))?;
        if !bl.is_nullish() {
            return Ok(bl);
        }
        let l = vm.get_prop_of(&s, &key("length"))?;
        if !l.is_nullish() {
            return Ok(l);
        }
        Ok(Value::Num(0.0))
    })
}

/// Calls `x.<prop>(args)` from a function the reference runs compiled (loops), reporting a
/// non-callable member with the compiled-code message.
fn call_member_compiled(vm: &mut Vm, x: &Value, prop: &str, args: &[Value]) -> JsResult<Value> {
    let f = vm.get_prop_of(x, &key(prop))?;
    if !f.is_callable() {
        let m = not_callable_msg(false, prop, &f);
        return vm.throw_type(m);
    }
    vm.call(&f, x.clone(), args)
}

fn buffer_concat(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["concat"], |vm| concat_impl(vm, &a.arg(0), &a.arg(1)))
}

/// `Buffer.concat(list)` for the runtime's own modules.
pub fn concat_value(vm: &mut Vm, list: &Value) -> JsResult<Value> {
    with_frames(vm, &["concat"], |vm| concat_impl(vm, list, &Value::Undefined))
}

fn concat_impl(vm: &mut Vm, list: &Value, total: &Value) -> JsResult<Value> {
    {
        let list = list.clone();
        let total = total.clone();
        // fast path: an array of byte-sized typed arrays
        let items: Option<Vec<Obj>> = match &list {
            Value::Obj(o) => match &o.borrow().kind {
                ObjKind::Array(ad) if !ad.sparse && ad.dense.len() == ad.len as usize => {
                    let mut v = Vec::with_capacity(ad.dense.len());
                    let mut ok = true;
                    for x in ad.dense.iter() {
                        match x {
                            Value::Obj(xo) if matches!(&xo.borrow().kind, ObjKind::TypedArray(t) if is_byte_kind(t.kind) && !t.is_out_of_bounds()) => v.push(xo.clone()),
                            _ => {
                                ok = false;
                                break;
                            }
                        }
                    }
                    if ok {
                        Some(v)
                    } else {
                        None
                    }
                }
                _ => None,
            },
            _ => None,
        };
        let total_is_simple = matches!(total, Value::Undefined | Value::Num(_));
        let array_iter_intact = vm.is_plain_array_iteration(&list);
        if let (Some(items), true, true) = (items, total_is_simple, array_iter_intact) {
            let lens: Vec<usize> = items.iter().map(|o| ta_info(o).map(|i| i.1).unwrap_or(0)).collect();
            let total_f = match total {
                Value::Num(n) => n,
                _ => lens.iter().sum::<usize>() as f64,
            };
            let out = construct_buffer(vm, &[Value::Num(total_f)])?;
            let mut data = Vec::new();
            let mut offset = 0f64;
            for (o, len) in items.iter().zip(lens.iter()) {
                if offset >= total_f {
                    break;
                }
                let m = js_min(&[*len as f64, total_f - offset]);
                let n = relative_f(m, *len);
                let bytes = ta_bytes(o);
                data.extend_from_slice(&bytes[..n]);
                offset += *len as f64;
            }
            write_bytes(&out, 0, &data);
            return Ok(Value::Obj(out));
        }
        // generic path, following the reference statement by statement
        if list.is_nullish() {
            // the reference engine's for-of message (its internal key for Symbol.iterator is "\0" "1")
            let what = if list.is_null() { "null" } else { "undefined" };
            return vm.throw_type(format!("cannot read property '\u{0}1' of {}", what));
        }
        let mut total_v = total.clone();
        if total_v.is_undefined() {
            let mut acc = Value::Num(0.0);
            let elems = vm.iterate_to_vec(&list)?;
            for b in elems {
                let l = vm.get_prop_of(&b, &key("length"))?;
                acc = vm.op_add(&acc, &l)?;
            }
            total_v = acc;
        }
        let out = construct_buffer(vm, &[total_v.clone()])?;
        let outv = Value::Obj(out);
        let mut offset = Value::Num(0.0);
        let elems = vm.iterate_to_vec(&list)?;
        for b in elems {
            if vm.op_compare(crate::bytecode::Op::Ge, &offset, &total_v)? {
                break;
            }
            let bl = vm.get_prop_of(&b, &key("length"))?;
            let rest = vm.op_arith(crate::bytecode::Op::Sub, &total_v, &offset)?;
            let x = vm.to_number(&bl)?;
            let y = vm.to_number(&rest)?;
            let m = js_min(&[x, y]);
            let sub = call_member_compiled(vm, &b, "subarray", &[Value::Num(0.0), Value::Num(m)])?;
            ta_set_value(vm, &outv, &sub, &offset)?;
            let bl2 = vm.get_prop_of(&b, &key("length"))?;
            offset = vm.op_add(&offset, &bl2)?;
        }
        Ok(outv)
    }
}

/// Shared comparison loop of `Buffer.compare` / `Buffer.prototype.compare`.
fn compare_values(vm: &mut Vm, a: &Value, b: &Value) -> JsResult<Value> {
    // fast path: two byte-sized typed arrays
    if let (Value::Obj(x), Value::Obj(y)) = (a, b) {
        if let (Some((kx, _, false)), Some((ky, _, false))) = (ta_info(x), ta_info(y)) {
            if kx == TAKind::Uint8 && ky == TAKind::Uint8 && x.borrow().props.is_empty() && y.borrow().props.is_empty() {
                let bx = ta_bytes(x);
                let by = ta_bytes(y);
                return Ok(Value::Num(match bx.cmp(&by) {
                    std::cmp::Ordering::Less => -1.0,
                    std::cmp::Ordering::Equal => 0.0,
                    std::cmp::Ordering::Greater => 1.0,
                }));
            }
        }
    }
    let al = vm.get_prop_of(a, &key("length"))?;
    let bl = vm.get_prop_of(b, &key("length"))?;
    let x = vm.to_number(&al)?;
    let y = vm.to_number(&bl)?;
    let n = js_min(&[x, y]);
    let mut i = 0f64;
    while i < n {
        let ai = vm.get_elem(a, &Value::Num(i))?;
        let bi = vm.get_elem(b, &Value::Num(i))?;
        if !Value::strict_eq(&ai, &bi) {
            let ai2 = vm.get_elem(a, &Value::Num(i))?;
            let bi2 = vm.get_elem(b, &Value::Num(i))?;
            let lt = vm.op_compare(crate::bytecode::Op::Lt, &ai2, &bi2)?;
            return Ok(Value::Num(if lt { -1.0 } else { 1.0 }));
        }
        i += 1.0;
    }
    let al = vm.get_prop_of(a, &key("length"))?;
    let bl = vm.get_prop_of(b, &key("length"))?;
    if Value::strict_eq(&al, &bl) {
        return Ok(Value::Num(0.0));
    }
    let al = vm.get_prop_of(a, &key("length"))?;
    let bl = vm.get_prop_of(b, &key("length"))?;
    let lt = vm.op_compare(crate::bytecode::Op::Lt, &al, &bl)?;
    Ok(Value::Num(if lt { -1.0 } else { 1.0 }))
}

fn buffer_compare_static(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["compare"], |vm| {
        let ctor = buffer_ctor_obj().map(Value::Obj).unwrap_or(Value::Undefined);
        let (x, y) = (a.arg(0), a.arg(1));
        if !vm.instance_of(&x, &ctor)? || !vm.instance_of(&y, &ctor)? {
            return vm.throw_type("Arguments must be Buffers");
        }
        compare_values(vm, &x, &y)
    })
}

// ============================================================================================
// Buffer.prototype
// ============================================================================================

fn buf_to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    // `return stringFromBytes(this, enc, start, end)`: a tail call (no `toString` frame) until
    // the method gets compiled
    if bump(&TOSTRING_CALLS) >= TIER_UP_CALLS {
        with_frames(vm, &["toString"], |vm| string_from_bytes(vm, &a.this, &a.arg(0), &a.arg(1), &a.arg(2)))
    } else {
        string_from_bytes(vm, &a.this, &a.arg(0), &a.arg(1), &a.arg(2))
    }
}

/// `target.set(src, offset)` for any source, with the reference's range messages.
fn ta_set_value(vm: &mut Vm, target: &Value, src: &Value, offset: &Value) -> JsResult<()> {
    let f = vm.get_prop_of(target, &key("set"))?;
    let intrinsic = state().and_then(|s| s.ta_set).map_or(false, |i| matches!(&f, Value::Obj(fo) if fo.ptr_eq(&i)));
    if intrinsic {
        if let Value::Obj(t) = target {
            if let Some((_, tlen, false)) = ta_info(t) {
                let off = vm.to_integer_or_infinity(offset)?;
                if off < 0.0 {
                    return vm.throw_range("TypedArray.prototype.set offset is negative");
                }
                let slen = match src {
                    Value::Obj(so) => match ta_info(so) {
                        Some((_, l, _)) => l as f64,
                        None => {
                            let l = vm.get_prop_of(src, &key("length"))?;
                            vm.to_length(&l)? as f64
                        }
                    },
                    _ => 0.0,
                };
                if off + slen > tlen as f64 {
                    return vm.throw_range("source is too large for the target at offset");
                }
            }
        }
    }
    if !f.is_callable() {
        let m = not_callable_msg(false, "set", &f);
        return vm.throw_type(m);
    }
    vm.call(&f, target.clone(), &[src.clone(), offset.clone()])?;
    Ok(())
}

/// `this.set(src, offset)` with the reference's %TypedArray%.prototype.set messages.
fn ta_set_bytes(vm: &mut Vm, this: &Value, src: &[u8], offset: &Value) -> JsResult<()> {
    let f = vm.get_prop_of(this, &key("set"))?;
    let intrinsic = state().and_then(|s| s.ta_set).map_or(false, |i| matches!(&f, Value::Obj(fo) if fo.ptr_eq(&i)));
    if intrinsic {
        if let Value::Obj(o) = this {
            if let Some((kind, len, oob)) = ta_info(o) {
                if !oob {
                    let off = vm.to_integer_or_infinity(offset)?;
                    if off < 0.0 {
                        return vm.throw_range("TypedArray.prototype.set offset is negative");
                    }
                    if off + src.len() as f64 > len as f64 {
                        return vm.throw_range("source is too large for the target at offset");
                    }
                    let off = off as usize;
                    if is_byte_kind(kind) {
                        write_bytes(o, off, src);
                    } else {
                        for (i, b) in src.iter().enumerate() {
                            crate::builtins::typedarray::ta_set_index(vm, o, (off + i) as f64, &Value::Num(*b as f64))?;
                        }
                    }
                    return Ok(());
                }
            }
        }
    }
    if !f.is_callable() {
        let m = not_callable_msg(false, "set", &f);
        return vm.throw_type(m);
    }
    let u = crate::builtins::typedarray::typed_array_from_bytes(vm, src.to_vec());
    vm.call(&f, this.clone(), &[Value::Obj(u), offset.clone()])?;
    Ok(())
}

fn buf_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["write"], |vm| {
        let this = a.this.clone();
        let string = a.arg(0);
        let mut offset = a.arg(1);
        let mut length = a.arg(2);
        let mut enc = a.arg(3);
        if let Value::Str(_) = offset {
            enc = offset.clone();
            offset = Value::Num(0.0);
            length = vm.get_prop_of(&this, &key("length"))?;
        } else if let Value::Str(_) = length {
            enc = length.clone();
            let tl = vm.get_prop_of(&this, &key("length"))?;
            length = vm.op_arith(crate::bytecode::Op::Sub, &tl, &offset)?;
        }
        if !offset.truthy() {
            offset = Value::Num(0.0);
        }
        let src = bytes_from_string(vm, &string, &enc)?;
        let l1 = if length.is_undefined() {
            let tl = vm.get_prop_of(&this, &key("length"))?;
            vm.op_arith(crate::bytecode::Op::Sub, &tl, &offset)?
        } else {
            length.clone()
        };
        let tl = vm.get_prop_of(&this, &key("length"))?;
        let l2 = vm.op_arith(crate::bytecode::Op::Sub, &tl, &offset)?;
        let x = vm.to_number(&l1)?;
        let y = vm.to_number(&l2)?;
        let n = js_min(&[src.len() as f64, x, y]);
        let cnt = relative_f(n, src.len());
        ta_set_bytes(vm, &this, &src[..cnt], &offset)?;
        Ok(Value::Num(n))
    })
}

fn buf_slice(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let calls = bump(&SLICE_CALLS);
    with_frames(vm, &["slice"], |vm| {
        let sub = subarray_of(vm, &a.this, &a.arg(0), &a.arg(1), calls < TIER_UP_CALLS)?;
        let bytes = sub.into_bytes(vm)?;
        let b = zeroed_buffer(vm, bytes.len())?;
        write_bytes(&b, 0, &bytes);
        Ok(Value::Obj(b))
    })
}

fn buf_equals(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["equals"], |vm| {
        let this = a.this.clone();
        let other = a.arg(0);
        let u8c = Value::Obj(vm.intr.ta_ctors[1].clone());
        if !vm.instance_of(&other, &u8c)? {
            return Ok(Value::Bool(false));
        }
        let ol = vm.get_prop_of(&other, &key("length"))?;
        let tl = vm.get_prop_of(&this, &key("length"))?;
        if !Value::strict_eq(&ol, &tl) {
            return Ok(Value::Bool(false));
        }
        if let (Value::Obj(x), Value::Obj(y)) = (&this, &other) {
            if let (Some((kx, _, false)), Some((ky, _, false))) = (ta_info(x), ta_info(y)) {
                if kx == TAKind::Uint8 && ky == TAKind::Uint8 {
                    return Ok(Value::Bool(ta_bytes(x) == ta_bytes(y)));
                }
            }
        }
        let mut i = 0f64;
        loop {
            let tl = vm.get_prop_of(&this, &key("length"))?;
            let lim = vm.to_number(&tl)?;
            if !(i < lim) {
                break;
            }
            let x = vm.get_elem(&this, &Value::Num(i))?;
            let y = vm.get_elem(&other, &Value::Num(i))?;
            if !Value::strict_eq(&x, &y) {
                return Ok(Value::Bool(false));
            }
            i += 1.0;
        }
        Ok(Value::Bool(true))
    })
}

fn buf_compare(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["compare"], |vm| compare_values(vm, &a.this, &a.arg(0)))
}

fn buf_to_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["toJSON"], |vm| {
        let this = a.this.clone();
        let data = match &this {
            Value::Obj(o) if matches!(ta_info(o), Some((TAKind::Uint8, _, false))) => {
                let vals: Vec<Value> = ta_bytes(o).iter().map(|x| Value::Num(*x as f64)).collect();
                Value::Obj(vm.new_array(vals))
            }
            _ if this.is_nullish() => return vm.throw_type("Array.from called on null or undefined"),
            _ => {
                let arr = Value::Obj(vm.intr.array_ctor.clone());
                let from = vm.get_prop_of(&arr, &key("from"))?;
                vm.call(&from, arr, &[this.clone()])?
            }
        };
        let o = vm.new_object();
        o.set_prop(key("type"), Value::str("Buffer"), WEC);
        o.set_prop(key("data"), data, WEC);
        Ok(Value::Obj(o))
    })
}

fn offset_arg(a: &Args, i: usize) -> Value {
    match a.arg(i) {
        Value::Undefined => Value::Num(0.0),
        v => v,
    }
}

fn idx(vm: &mut Vm, this: &Value, o: &Value, k: f64) -> JsResult<Value> {
    if k == 0.0 {
        return vm.get_elem(this, o);
    }
    let key = vm.op_add(o, &Value::Num(k))?;
    vm.get_elem(this, &key)
}

fn buf_read_u8(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["readUInt8"], |vm| {
        let o = offset_arg(a, 0);
        vm.get_elem(&a.this, &o)
    })
}

fn buf_read_u16le(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["readUInt16LE"], |vm| {
        let o = offset_arg(a, 0);
        let x = idx(vm, &a.this, &o, 0.0)?;
        let y = idx(vm, &a.this, &o, 1.0)?;
        let y = int32_of(vm, &y)?.wrapping_shl(8);
        let x = int32_of(vm, &x)?;
        Ok(Value::Num((x | y) as f64))
    })
}

fn buf_read_u16be(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["readUInt16BE"], |vm| {
        let o = offset_arg(a, 0);
        let x = idx(vm, &a.this, &o, 0.0)?;
        let x = int32_of(vm, &x)?.wrapping_shl(8);
        let y = idx(vm, &a.this, &o, 1.0)?;
        let y = int32_of(vm, &y)?;
        Ok(Value::Num((x | y) as f64))
    })
}

fn buf_read_u32le(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["readUInt32LE"], |vm| {
        let o = offset_arg(a, 0);
        let mut acc = 0i32;
        let v0 = idx(vm, &a.this, &o, 0.0)?;
        let v1 = idx(vm, &a.this, &o, 1.0)?;
        let s1 = int32_of(vm, &v1)?.wrapping_shl(8);
        acc |= int32_of(vm, &v0)? | s1;
        let v2 = idx(vm, &a.this, &o, 2.0)?;
        acc |= int32_of(vm, &v2)?.wrapping_shl(16);
        let v3 = idx(vm, &a.this, &o, 3.0)?;
        acc |= int32_of(vm, &v3)?.wrapping_shl(24);
        Ok(Value::Num(acc as u32 as f64))
    })
}

fn buf_read_u32be(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["readUInt32BE"], |vm| {
        let o = offset_arg(a, 0);
        let v0 = idx(vm, &a.this, &o, 0.0)?;
        let mut acc = int32_of(vm, &v0)?.wrapping_shl(24);
        let v1 = idx(vm, &a.this, &o, 1.0)?;
        acc |= int32_of(vm, &v1)?.wrapping_shl(16);
        let v2 = idx(vm, &a.this, &o, 2.0)?;
        acc |= int32_of(vm, &v2)?.wrapping_shl(8);
        let v3 = idx(vm, &a.this, &o, 3.0)?;
        acc |= int32_of(vm, &v3)?;
        Ok(Value::Num(acc as u32 as f64))
    })
}

fn set_idx(vm: &mut Vm, this: &Value, o: &Value, k: f64, v: f64) -> JsResult<()> {
    let key = if k == 0.0 { o.clone() } else { vm.op_add(o, &Value::Num(k))? };
    vm.set_elem(this, &key, Value::Num(v), true)
}

fn buf_write_u8(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["writeUInt8"], |vm| {
        let o = offset_arg(a, 1);
        let v = and_ff(vm, &a.arg(0))?;
        set_idx(vm, &a.this, &o, 0.0, v)?;
        vm.op_add(&o, &Value::Num(1.0))
    })
}

fn buf_write_u32le(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["writeUInt32LE"], |vm| {
        let o = offset_arg(a, 1);
        let v = a.arg(0);
        let b0 = and_ff(vm, &v)?;
        set_idx(vm, &a.this, &o, 0.0, b0)?;
        for (k, sh) in [(1.0, 8), (2.0, 16), (3.0, 24)] {
            let key = vm.op_add(&o, &Value::Num(k))?;
            let x = (uint32_of(vm, &v)? >> sh) & 0xff;
            vm.set_elem(&a.this, &key, Value::Num(x as f64), true)?;
        }
        vm.op_add(&o, &Value::Num(4.0))
    })
}

/// `util.inspect` text of a Buffer: `<Buffer 68 69>` (at most 50 bytes, then ` ...`).
pub fn inspect_buffer(vm: &mut Vm, v: &Value) -> JsResult<String> {
    let o = match v {
        Value::Obj(o) if ta_info(o).is_some() => o.clone(),
        _ => return vm.throw_type("subarray on non-TypedArray"),
    };
    let (kind, len, _) = ta_info(&o).unwrap();
    let vals: Vec<u8> = if is_byte_kind(kind) { ta_bytes(&o) } else { Vec::new() };
    let shown: Vec<String> = vals.iter().take(50).map(|b| format!("{:02x}", b)).collect();
    Ok(format!("<Buffer {}{}>", shown.join(" "), if len > 50 { " ..." } else { "" }))
}

// ============================================================================================
// module-level functions
// ============================================================================================

/// Present a native as a plain `function` (own `prototype`; `new f()` yields an object unless
/// the body returns one).
pub fn plain_function(vm: &mut Vm, name: &str, len: u32, f: NativeFn) -> Obj {
    let inner = vm.native_fn(name, len, f);
    let outer = vm.native_closure(name, len, plain_function_shim, vec![Value::Obj(inner)]);
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

pub fn typeof_name(v: &Value) -> &'static str {
    match v {
        Value::Undefined | Value::Empty => "undefined",
        Value::Null => "object",
        Value::Bool(_) => "boolean",
        Value::Num(_) => "number",
        Value::Str(_) => "string",
        Value::Sym(_) => "symbol",
        Value::BigInt(_) => "bigint",
        Value::Obj(o) => {
            if o.is_callable() {
                "function"
            } else {
                "object"
            }
        }
    }
}

/// `bytesOf(input, name)` of isAscii/isUtf8.
fn bytes_of_input(vm: &mut Vm, input: &Value, name: &str) -> JsResult<Vec<u8>> {
    with_frames(vm, &["bytesOf"], |vm| {
        if let Value::Obj(o) = input {
            let ok = match &o.borrow().kind {
                ObjKind::ArrayBuffer(b) => !b.borrow().shared,
                ObjKind::TypedArray(_) | ObjKind::DataView(_) => true,
                _ => false,
            };
            if ok {
                return Ok(ta_bytes(o));
            }
        }
        let msg = format!(
            "The \"{}\" argument must be an instance of ArrayBuffer, Buffer, TypedArray, or DataView. Received {}",
            name,
            typeof_name(input)
        );
        Err(type_error_code(vm, "TypeError", &msg, "ERR_INVALID_ARG_TYPE"))
    })
}

fn mod_is_ascii(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["isAscii"], |vm| {
        let b = bytes_of_input(vm, &a.arg(0), "input")?;
        Ok(Value::Bool(b.iter().all(|&x| x <= 0x7f)))
    })
}

/// The reference's isUtf8 validation (rejects overlongs, surrogates and > U+10FFFF).
fn utf8_valid(b: &[u8]) -> bool {
    let n = b.len();
    let mut i = 0;
    while i < n {
        let c = b[i];
        if c < 0x80 {
            i += 1;
            continue;
        }
        let (extra, min, mut cp) = if c & 0xe0 == 0xc0 {
            (1, 0x80u32, (c & 0x1f) as u32)
        } else if c & 0xf0 == 0xe0 {
            (2, 0x800, (c & 0x0f) as u32)
        } else if c & 0xf8 == 0xf0 {
            (3, 0x10000, (c & 0x07) as u32)
        } else {
            return false;
        };
        if i + extra >= n {
            return false;
        }
        for j in 1..=extra {
            let cc = b[i + j];
            if cc & 0xc0 != 0x80 {
                return false;
            }
            cp = (cp << 6) | (cc & 0x3f) as u32;
        }
        if cp < min || cp > 0x10ffff || (0xd800..=0xdfff).contains(&cp) {
            return false;
        }
        i += extra + 1;
    }
    true
}

fn mod_is_utf8(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["isUtf8"], |vm| {
        let b = bytes_of_input(vm, &a.arg(0), "input")?;
        Ok(Value::Bool(utf8_valid(&b)))
    })
}

fn mod_transcode(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["transcode"], |vm| {
        let source = a.arg(0);
        let is_view = matches!(&source, Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_) | ObjKind::DataView(_)));
        let is_ab = is_array_buffer_instance(vm, &source);
        if !is_view && !is_ab {
            return Err(type_error_code(vm, "TypeError", "The \"source\" argument must be an instance of Buffer or Uint8Array.", "ERR_INVALID_ARG_TYPE"));
        }
        for enc in [a.arg(1), a.arg(2)] {
            let ok = buffer_is_encoding(vm, &Args { this: Value::Undefined, args: &[enc.clone()], callee: a.callee, new_target: None })?;
            if !ok.truthy() {
                let s = vm.to_string(&enc)?;
                return Err(type_error_code(vm, "Error", &format!("Unknown encoding: {}", s), "ERR_UNKNOWN_ENCODING"));
            }
        }
        let bytes = match &source {
            Value::Obj(o) => ta_bytes(o),
            _ => Vec::new(),
        };
        let u = crate::builtins::typedarray::typed_array_from_bytes(vm, bytes);
        let s = string_from_bytes(vm, &Value::Obj(u), &a.arg(1), &Value::Undefined, &Value::Undefined)?;
        let out = bytes_from_string(vm, &s, &a.arg(2))?;
        new_buffer_value(vm, out)
    })
}

fn mod_slow_buffer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    // `return Buffer.allocUnsafeSlow(length)` (a tail call until compiled)
    if bump(&SLOWBUF_CALLS) >= TIER_UP_CALLS {
        with_frames(vm, &["SlowBuffer"], |vm| buffer_alloc_unsafe_slow(vm, a))
    } else {
        buffer_alloc_unsafe_slow(vm, a)
    }
}

// ============================================================================================
// setup
// ============================================================================================

pub fn setup_global(vm: &mut Vm) {
    let m = create_module(vm);
    if let Value::Obj(mo) = &m {
        if let Some(b) = mo.get_own_str("Buffer") {
            vm.global.set_prop(key("Buffer"), b, WEC);
        }
    }
    vm.host.builtin_cache.insert("buffer".into(), m);
}

pub fn create_module(vm: &mut Vm) -> Value {
    if let Some(v) = vm.host.builtin_cache.get("buffer") {
        return v.clone();
    }
    let u8p = vm.intr.ta_protos[1].clone();
    let u8c = vm.intr.ta_ctors[1].clone();
    let proto = Obj::new(Some(u8p), ObjKind::Ordinary);
    let ctor = vm.native_ctor("Buffer", 0, buffer_ctor, &proto);
    ctor.borrow_mut().proto = Some(u8c);
    let tap = vm.intr.typed_array_proto.clone();
    let ta_subarray = tap.get_own_str("subarray").and_then(|v| v.as_obj().cloned());
    let ta_set = tap.get_own_str("set").and_then(|v| v.as_obj().cloned());
    STATE.with(|s| *s.borrow_mut() = Some(Intrinsics { proto: proto.clone(), ctor: ctor.clone(), ta_subarray, ta_set }));
    let statics: &[(&str, u32, NativeFn)] = &[
        ("from", 3, buffer_from),
        ("alloc", 3, buffer_alloc),
        ("allocUnsafe", 1, buffer_alloc_unsafe),
        ("allocUnsafeSlow", 1, buffer_alloc_unsafe_slow),
        ("isBuffer", 1, buffer_is_buffer),
        ("isEncoding", 1, buffer_is_encoding),
        ("compare", 2, buffer_compare_static),
        ("byteLength", 2, byte_length),
        ("concat", 2, buffer_concat),
    ];
    for (n, l, f) in statics {
        vm.def_method(&ctor, n, *l, *f);
    }
    let methods: &[(&str, u32, NativeFn)] = &[
        ("toString", 3, buf_to_string),
        ("write", 4, buf_write),
        ("slice", 2, buf_slice),
        ("equals", 1, buf_equals),
        ("compare", 1, buf_compare),
        ("toJSON", 0, buf_to_json),
        ("readUInt8", 0, buf_read_u8),
        ("writeUInt8", 1, buf_write_u8),
        ("readUInt16LE", 0, buf_read_u16le),
        ("readUInt16BE", 0, buf_read_u16be),
        ("readUInt32LE", 0, buf_read_u32le),
        ("readUInt32BE", 0, buf_read_u32be),
        ("writeUInt32LE", 1, buf_write_u32le),
    ];
    for (n, l, f) in methods {
        vm.def_method(&proto, n, *l, *f);
    }
    let m = vm.new_object();
    m.set_str("Buffer", Value::Obj(ctor), WEC);
    let slow = plain_function(vm, "SlowBuffer", 1, mod_slow_buffer);
    m.set_str("SlowBuffer", Value::Obj(slow), WEC);
    let max = 9007199254740991.0;
    let constants = vm.obj_from(vec![("MAX_LENGTH", Value::Num(max)), ("MAX_STRING_LENGTH", Value::Num(536870888.0))]);
    m.set_str("constants", Value::Obj(constants), WEC);
    m.set_str("kMaxLength", Value::Num(max), WEC);
    m.set_str("kStringMaxLength", Value::Num(536870888.0), WEC);
    m.set_str("INSPECT_MAX_BYTES", Value::Num(50.0), WEC);
    for n in ["atob", "btoa", "Blob", "File"] {
        let v = vm.global.get_own_str(n).unwrap_or(Value::Undefined);
        m.set_str(n, v, WEC);
    }
    let fns: &[(&str, u32, NativeFn)] = &[
        ("isAscii", 1, mod_is_ascii),
        ("isUtf8", 1, mod_is_utf8),
        ("transcode", 3, mod_transcode),
        ("resolveObjectURL", 1, |_vm, _a| Ok(Value::Undefined)),
    ];
    for (n, l, f) in fns {
        let fo = plain_function(vm, n, *l, *f);
        m.set_str(n, Value::Obj(fo), WEC);
    }
    let mv = Value::Obj(m);
    vm.host.builtin_cache.insert("buffer".into(), mv.clone());
    mv
}

// ============================================================================================
// string_decoder
// ============================================================================================

pub fn create_string_decoder_module(vm: &mut Vm) -> Value {
    let ctor = plain_function(vm, "StringDecoder", 1, sd_ctor);
    let proto = vm.get_prop_of(&Value::Obj(ctor.clone()), &key("prototype")).ok().and_then(|p| p.as_obj().cloned()).unwrap_or_else(|| vm.new_object());
    let w = vm.native_fn("", 1, sd_write);
    proto.set_prop(key("write"), Value::Obj(w), WEC);
    let e = vm.native_fn("", 1, sd_end);
    proto.set_prop(key("end"), Value::Obj(e), WEC);
    let m = vm.new_object();
    m.set_str("StringDecoder", Value::Obj(ctor), WEC);
    Value::Obj(m)
}

/// `function StringDecoder(encoding)`: encoding = String(encoding || "utf8").toLowerCase()
/// .replace("-", ""); utf8 decoders own a (non-streaming) TextDecoder in `_dec`.
fn sd_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let e = a.arg(0);
    let e = if e.truthy() { e } else { Value::str("utf8") };
    let s = vm.to_string(&e)?.to_rust_string().to_lowercase().replacen('-', "", 1);
    vm.set_prop_of(&this, key("encoding"), Value::str(&s), true)?;
    let is_utf8 = s == "utf8";
    vm.set_prop_of(&this, key("_utf8"), Value::Bool(is_utf8), true)?;
    if is_utf8 {
        let dec = new_text_decoder(vm)?;
        vm.set_prop_of(&this, key("_dec"), dec, true)?;
    }
    Ok(Value::Undefined)
}

/// `new TextDecoder("utf-8")` when the global exists, else a stand-in with the same `decode`.
fn new_text_decoder(vm: &mut Vm) -> JsResult<Value> {
    if let Some(td) = vm.global.get_own_str("TextDecoder") {
        if let Value::Obj(c) = &td {
            if c.is_constructor() {
                return vm.construct(&td, &[Value::str("utf-8")], None);
            }
        }
    }
    let o = vm.new_object();
    vm.def_method(&o, "decode", 0, text_decode_fallback);
    Ok(Value::Obj(o))
}

/// TextDecoder.prototype.decode as the reference implements it (no streaming state).
fn text_decode_fallback(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["decode"], |vm| text_decode_value(vm, &a.arg(0)))
}

/// The reference's `TextDecoder#decode(input)` for utf-8 (no streaming state).
fn text_decode_value(vm: &mut Vm, input: &Value) -> JsResult<Value> {
    if input.is_undefined() {
        return Ok(Value::str(""));
    }
    let bytes = match input {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_) | ObjKind::DataView(_) | ObjKind::ArrayBuffer(_)) => ta_bytes(o),
        _ => return vm.throw_type("TextDecoder.decode expects a BufferSource"),
    };
    Ok(Value::Str(JsStr::from_units(utf8_decode(&bytes))))
}

fn sd_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let buffer = a.arg(0);
    let utf8 = vm.get_prop_of(&this, &key("_utf8"))?;
    if utf8.truthy() {
        // `this._dec.decode(buffer, { stream: true })`: the reference's TextDecoder ignores
        // `stream`, so every chunk is decoded on its own (decoded natively here so the result
        // does not depend on the global TextDecoder)
        let _ = vm.get_prop_of(&this, &key("_dec"))?;
        return with_frames(vm, &["decode"], |vm| text_decode_value(vm, &buffer));
    }
    let b = buffer_from_value(vm, &buffer, &Value::Undefined)?;
    let enc = vm.get_prop_of(&this, &key("encoding"))?;
    string_from_bytes(vm, &b, &enc, &Value::Undefined, &Value::Undefined)
}

fn sd_end(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let buffer = a.arg(0);
    let mut out = Value::str("");
    if buffer.truthy() {
        let l = vm.get_prop_of(&buffer, &key("length"))?;
        if l.truthy() {
            let w = call_member_compiled(vm, &this, "write", &[buffer.clone()])?;
            out = vm.op_add(&out, &w)?;
        }
    }
    let utf8 = vm.get_prop_of(&this, &key("_utf8"))?;
    if utf8.truthy() {
        // `this._dec.decode()` flushes nothing (no streaming state)
        let _ = vm.get_prop_of(&this, &key("_dec"))?;
        out = vm.op_add(&out, &Value::str(""))?;
    }
    Ok(out)
}
