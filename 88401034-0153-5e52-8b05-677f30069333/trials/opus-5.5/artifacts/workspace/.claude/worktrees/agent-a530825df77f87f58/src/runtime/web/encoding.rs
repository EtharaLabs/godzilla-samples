// TextEncoder / TextDecoder / atob / btoa.
//
// The reference engine keeps strings as UTF-8 internally and escapes lone surrogates into the
// top of plane 16 (U+10F800..U+10FFFF = surrogate + 0x102000); TextEncoder exposes those
// internal bytes and TextDecoder maps that range back to lone surrogates.

use super::*;
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

const ESCAPE_BASE: u32 = 0x10F800;
const ESCAPE_OFFSET: u32 = 0x102000;

fn push_utf8(out: &mut Vec<u8>, cp: u32) {
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

/// UTF-16 string -> the engine's internal UTF-8 bytes.
pub fn engine_utf8(units: &[u16]) -> Vec<u8> {
    let mut out = Vec::with_capacity(units.len());
    let mut i = 0;
    while i < units.len() {
        let u = units[i] as u32;
        if (0xD800..0xDC00).contains(&u) && i + 1 < units.len() {
            let l = units[i + 1] as u32;
            if (0xDC00..0xE000).contains(&l) {
                let cp = 0x10000 + ((u - 0xD800) << 10) + (l - 0xDC00);
                if cp < ESCAPE_BASE {
                    push_utf8(&mut out, cp);
                    i += 2;
                    continue;
                }
            }
        }
        if (0xD800..0xE000).contains(&u) {
            push_utf8(&mut out, u + ESCAPE_OFFSET);
        } else {
            push_utf8(&mut out, u);
        }
        i += 1;
    }
    out
}

/// UTF-8 bytes -> UTF-16 (invalid sequences become U+FFFD, escaped surrogates come back).
pub fn engine_utf16(bytes: &[u8]) -> Vec<u16> {
    let s = String::from_utf8_lossy(bytes);
    let mut out = Vec::with_capacity(s.len());
    for c in s.chars() {
        let cp = c as u32;
        if cp >= ESCAPE_BASE {
            out.push((cp - ESCAPE_OFFSET) as u16);
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

pub fn setup(vm: &mut Vm) {
    let (c, p) = make_class(vm, "TextEncoder", "TextEncoder.prototype", 0, text_encoder_ctor, None);
    getter(vm, &p, "encoding", |_vm, _a| Ok(Value::str("utf-8")));
    method(vm, &p, "encode", 0, text_encoder_encode);
    set_global(vm, "TextEncoder", Value::Obj(c));

    let (c, p) = make_class(vm, "TextDecoder", "TextDecoder.prototype", 0, text_decoder_ctor, None);
    method(vm, &p, "decode", 1, text_decoder_decode);
    set_global(vm, "TextDecoder", Value::Obj(c));

    let f = plain_fn(vm, "btoa", 1, btoa);
    set_global(vm, "btoa", Value::Obj(f));
    let f = plain_fn(vm, "atob", 1, atob);
    set_global(vm, "atob", Value::Obj(f));
}

fn text_encoder_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Obj(new_this(vm, a, "TextEncoder.prototype")?))
}

/// `__encoding.encode(String(input))`
pub fn encode_to_u8(vm: &mut Vm, s: &JsStr) -> Value {
    let bytes = engine_utf8(s.units());
    Value::Obj(crate::builtins::typedarray::typed_array_from_bytes(vm, bytes))
}

fn text_encoder_encode(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let input = if a.arg(0).is_undefined() { Value::str("") } else { a.arg(0) };
    let s = js_string(vm, &input)?;
    Ok(encode_to_u8(vm, &s))
}

fn text_decoder_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = new_this(vm, a, "TextDecoder.prototype")?;
    let ov = Value::Obj(o);
    let label = if a.arg(0).is_undefined() { Value::str("utf-8") } else { a.arg(0) };
    let l = js_string(vm, &label)?.to_rust_string().to_lowercase();
    if l != "utf-8" && l != "utf8" && l != "unicode-1-1-utf-8" {
        let shown = vm.to_string(&label)?;
        return vm.throw_range(format!("TextDecoder: unsupported encoding '{}' (utf-8 only for now)", shown));
    }
    let options = if a.arg(1).is_undefined() { Value::Obj(vm.new_object()) } else { a.arg(1) };
    let options = if options.truthy() && is_object_type(&options) { options } else { Value::Obj(vm.new_object()) };
    set(vm, &ov, "encoding", Value::str("utf-8"))?;
    let fatal = get(vm, &options, "fatal")?.truthy();
    set(vm, &ov, "fatal", Value::Bool(fatal))?;
    let ib = get(vm, &options, "ignoreBOM")?.truthy();
    set(vm, &ov, "ignoreBOM", Value::Bool(ib))?;
    Ok(ov)
}

/// Bytes of a BufferSource accepted by `__encoding.decode` (typed arrays only).
fn typed_bytes(v: &Value) -> Option<Vec<u8>> {
    if let Value::Obj(o) = v {
        if let ObjKind::TypedArray(_) = &o.borrow().kind {
            return Some(crate::builtins::typedarray::ta_bytes(o));
        }
    }
    None
}

/// Decode UTF-8 bytes; `fatal` errors on malformed input.
pub fn decode_utf8(vm: &mut Vm, bytes: &[u8], fatal: bool) -> JsResult<JsStr> {
    if fatal && std::str::from_utf8(bytes).is_err() {
        return vm.throw_type("TextDecoder: invalid utf-8 (fatal)");
    }
    Ok(JsStr::from_units(engine_utf16(bytes)))
}

/// `new TextDecoder().decode(bytes)` (BOM stripped, replacement on errors)
pub fn decode_default(bytes: &[u8]) -> JsStr {
    let mut u = engine_utf16(bytes);
    if u.first() == Some(&0xFEFF) {
        u.remove(0);
    }
    JsStr::from_units(u)
}

fn text_decoder_decode(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut input = a.arg(0);
    if input.is_undefined() {
        return Ok(Value::str(""));
    }
    let abp = vm.intr.array_buffer_proto.clone();
    if has_in_chain(vm, &input, &abp)? {
        let ab_bytes = match &input {
            Value::Obj(o) if matches!(o.borrow().kind, ObjKind::ArrayBuffer(_)) => Some(crate::builtins::typedarray::ta_bytes(o)),
            _ => None,
        };
        if let Some(bytes) = ab_bytes {
            input = Value::Obj(crate::builtins::typedarray::typed_array_from_bytes(vm, bytes));
        }
    }
    let fatal = get(vm, &a.this, "fatal")?.truthy();
    let bytes = match typed_bytes(&input) {
        Some(b) => b,
        None => return vm.throw_type("TextDecoder.decode expects a BufferSource"),
    };
    let s = decode_utf8(vm, &bytes, fatal)?;
    let ib = get(vm, &a.this, "ignoreBOM")?.truthy();
    if !ib && s.units().first() == Some(&0xFEFF) {
        return Ok(Value::Str(s.substring(1, s.len())));
    }
    Ok(Value::Str(s))
}

const B64: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

fn btoa(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = js_string(vm, &a.arg(0))?;
    let u = s.units();
    let mut out = String::with_capacity(u.len() / 3 * 4 + 4);
    let mut i = 0;
    while i < u.len() {
        let c0 = u[i] as u32;
        let c1 = u.get(i + 1).map(|&x| x as u32);
        let c2 = u.get(i + 2).map(|&x| x as u32);
        if c0 > 255 || c1.map_or(false, |c| c > 255) || c2.map_or(false, |c| c > 255) {
            return throw_dom(vm, "btoa: character beyond latin1 range", "InvalidCharacterError");
        }
        let n = (c0 << 16) | (c1.unwrap_or(0) << 8) | c2.unwrap_or(0);
        out.push(B64[((n >> 18) & 63) as usize] as char);
        out.push(B64[((n >> 12) & 63) as usize] as char);
        out.push(if i + 1 < u.len() { B64[((n >> 6) & 63) as usize] as char } else { '=' });
        out.push(if i + 2 < u.len() { B64[(n & 63) as usize] as char } else { '=' });
        i += 3;
    }
    Ok(Value::str(&out))
}

fn b64_index(c: u16) -> Option<u32> {
    match c {
        0x41..=0x5A => Some((c - 0x41) as u32),
        0x61..=0x7A => Some((c - 0x61 + 26) as u32),
        0x30..=0x39 => Some((c - 0x30 + 52) as u32),
        0x2B => Some(62),
        0x2F => Some(63),
        _ => None,
    }
}

fn atob(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = js_string(vm, &a.arg(0))?;
    let mut u: Vec<u16> = s.units().iter().copied().filter(|&c| !matches!(c, 0x09 | 0x0A | 0x0C | 0x0D | 0x20)).collect();
    if u.len() % 4 == 0 && u.last() == Some(&0x3D) {
        u.pop();
        if u.last() == Some(&0x3D) {
            u.pop();
        }
    }
    if u.len() % 4 == 1 || u.iter().any(|&c| b64_index(c).is_none()) {
        return throw_dom(vm, "atob: invalid base64", "InvalidCharacterError");
    }
    let mut out: Vec<u16> = Vec::with_capacity(u.len() * 3 / 4);
    let mut i = 0;
    while i < u.len() {
        let bit = |j: usize| -> u32 { if i + j < u.len() { b64_index(u[i + j]).unwrap_or(0) } else { 0 } };
        let n = (bit(0) << 18) | (bit(1) << 12) | (bit(2) << 6) | bit(3);
        out.push(((n >> 16) & 255) as u16);
        if i + 2 < u.len() {
            out.push(((n >> 8) & 255) as u16);
        }
        if i + 3 < u.len() {
            out.push((n & 255) as u16);
        }
        i += 4;
    }
    Ok(Value::Str(JsStr::from_units(out)))
}
