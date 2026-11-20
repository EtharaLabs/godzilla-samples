// Global functions: parseInt, eval, URI coding, etc.

use crate::object::*;
use crate::value::*;
use crate::vm::{Frame, JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let g = vm.global.clone();
    g.set_prop(PropKey::from_str("globalThis"), Value::Obj(g.clone()), WC);
    g.set_prop(PropKey::from_str("undefined"), Value::Undefined, 0);
    g.set_prop(PropKey::from_str("NaN"), Value::Num(f64::NAN), 0);
    g.set_prop(PropKey::from_str("Infinity"), Value::Num(f64::INFINITY), 0);
    let fns: &[(&str, u32, NativeFn)] = &[
        ("parseInt", 2, parse_int),
        ("parseFloat", 1, parse_float),
        ("isNaN", 1, is_nan),
        ("isFinite", 1, is_finite),
        ("escape", 1, escape),
        ("unescape", 1, unescape),
        ("encodeURIComponent", 1, encode_uri_component),
        ("encodeURI", 1, encode_uri),
        ("decodeURIComponent", 1, decode_uri_component),
        ("decodeURI", 1, decode_uri),
    ];
    for (n, l, f) in fns {
        vm.def_method(&g, n, *l, *f);
    }
    let ev = vm.def_method(&g, "eval", 1, indirect_eval);
    vm.intr.eval_fn = ev;
    crate::builtins::number::setup_number_parse_links(vm);
}

fn parse_int(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    let r = vm.to_int32(&a.arg(1))?;
    Ok(Value::Num(crate::numconv::parse_int(s.units(), r)))
}

fn parse_float(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    Ok(Value::Num(crate::numconv::parse_float(s.units())))
}

fn is_nan(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(vm.to_number(&a.arg(0))?.is_nan()))
}

fn is_finite(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(vm.to_number(&a.arg(0))?.is_finite()))
}

fn indirect_eval(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match a.arg(0) {
        Value::Str(s) => crate::loader::indirect_eval(vm, &s),
        other => Ok(other),
    }
}

pub fn direct_eval(vm: &mut Vm, frame: &mut Frame, args: &[Value]) -> JsResult<Value> {
    match args.first() {
        Some(Value::Str(s)) => {
            let s = s.clone();
            crate::loader::direct_eval(vm, frame, &s)
        }
        Some(other) => Ok(other.clone()),
        None => Ok(Value::Undefined),
    }
}

const URI_RESERVED: &str = ";/?:@&=+$,";
const URI_UNESCAPED_EXTRA: &str = "-_.!~*'()";

fn encode(vm: &mut Vm, s: &JsStr, unescaped: &str) -> JsResult<Value> {
    let u = s.units();
    let mut out = String::new();
    let mut i = 0;
    while i < u.len() {
        let c = u[i];
        if c < 128 && ((c as u8).is_ascii_alphanumeric() || URI_UNESCAPED_EXTRA.contains(c as u8 as char) || unescaped.contains(c as u8 as char)) {
            out.push(c as u8 as char);
            i += 1;
            continue;
        }
        let cp: u32 = if (0xDC00..0xE000).contains(&c) {
            return vm.throw_error("URIError", "URI malformed");
        } else if (0xD800..0xDC00).contains(&c) {
            if i + 1 >= u.len() || !(0xDC00..0xE000).contains(&u[i + 1]) {
                return vm.throw_error("URIError", "URI malformed");
            }
            let cp = 0x10000 + (((c as u32) - 0xD800) << 10) + ((u[i + 1] as u32) - 0xDC00);
            i += 1;
            cp
        } else {
            c as u32
        };
        let ch = char::from_u32(cp).unwrap();
        let mut buf = [0u8; 4];
        for b in ch.encode_utf8(&mut buf).bytes() {
            out.push_str(&format!("%{:02X}", b));
        }
        i += 1;
    }
    Ok(Value::str(&out))
}

fn encode_uri_component(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    encode(vm, &s, "")
}

fn encode_uri(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    encode(vm, &s, ";/?:@&=+$,#")
}

fn hexval(c: u16) -> Option<u8> {
    match c {
        0x30..=0x39 => Some((c - 0x30) as u8),
        0x41..=0x46 => Some((c - 0x41 + 10) as u8),
        0x61..=0x66 => Some((c - 0x61 + 10) as u8),
        _ => None,
    }
}

fn decode(vm: &mut Vm, s: &JsStr, reserved: &str) -> JsResult<Value> {
    let u = s.units();
    let mut out: Vec<u16> = Vec::new();
    let mut i = 0;
    while i < u.len() {
        let c = u[i];
        if c != b'%' as u16 {
            out.push(c);
            i += 1;
            continue;
        }
        let start = i;
        if i + 2 >= u.len() {
            return vm.throw_error("URIError", "URI malformed");
        }
        let b = match (hexval(u[i + 1]), hexval(u[i + 2])) {
            (Some(h), Some(l)) => h * 16 + l,
            _ => return vm.throw_error("URIError", "URI malformed"),
        };
        i += 3;
        if b < 0x80 {
            if reserved.contains(b as char) {
                out.extend_from_slice(&u[start..i]);
            } else {
                out.push(b as u16);
            }
            continue;
        }
        let n = if b & 0xE0 == 0xC0 {
            2
        } else if b & 0xF0 == 0xE0 {
            3
        } else if b & 0xF8 == 0xF0 {
            4
        } else {
            return vm.throw_error("URIError", "URI malformed");
        };
        let mut bytes = vec![b];
        for _ in 1..n {
            if i + 2 >= u.len() || u[i] != b'%' as u16 {
                return vm.throw_error("URIError", "URI malformed");
            }
            let bb = match (hexval(u[i + 1]), hexval(u[i + 2])) {
                (Some(h), Some(l)) => h * 16 + l,
                _ => return vm.throw_error("URIError", "URI malformed"),
            };
            if bb & 0xC0 != 0x80 {
                return vm.throw_error("URIError", "URI malformed");
            }
            bytes.push(bb);
            i += 3;
        }
        match std::str::from_utf8(&bytes) {
            Ok(st) => {
                for ch in st.chars() {
                    let mut buf = [0u16; 2];
                    out.extend_from_slice(ch.encode_utf16(&mut buf));
                }
            }
            Err(_) => return vm.throw_error("URIError", "URI malformed"),
        }
    }
    Ok(Value::Str(JsStr::from_units(out)))
}

fn decode_uri_component(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    decode(vm, &s, "")
}

fn decode_uri(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    decode(vm, &s, ";/?:@&=+$,#")
}

fn escape(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    let mut out = String::new();
    for &c in s.units() {
        if c < 128 && ((c as u8).is_ascii_alphanumeric() || "@*_+-./".contains(c as u8 as char)) {
            out.push(c as u8 as char);
        } else if c < 256 {
            out.push_str(&format!("%{:02X}", c));
        } else {
            out.push_str(&format!("%u{:04X}", c));
        }
    }
    let _ = URI_RESERVED;
    Ok(Value::str(&out))
}

fn unescape(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    let u = s.units();
    let mut out = Vec::new();
    let mut i = 0;
    while i < u.len() {
        let c = u[i];
        if c == b'%' as u16 {
            if i + 6 <= u.len() && u[i + 1] == b'u' as u16 {
                let h: Option<Vec<u8>> = u[i + 2..i + 6].iter().map(|&x| hexval(x)).collect();
                if let Some(h) = h {
                    out.push(((h[0] as u16) << 12) | ((h[1] as u16) << 8) | ((h[2] as u16) << 4) | h[3] as u16);
                    i += 6;
                    continue;
                }
            }
            if i + 3 <= u.len() {
                if let (Some(h), Some(l)) = (hexval(u[i + 1]), hexval(u[i + 2])) {
                    out.push((h * 16 + l) as u16);
                    i += 3;
                    continue;
                }
            }
        }
        out.push(c);
        i += 1;
    }
    Ok(Value::Str(JsStr::from_units(out)))
}
