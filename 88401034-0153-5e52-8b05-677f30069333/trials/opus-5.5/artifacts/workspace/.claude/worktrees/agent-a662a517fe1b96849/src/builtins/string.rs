// String constructor and String.prototype.

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let proto = vm.intr.string_proto.clone();
    let ctor = vm.native_ctor("String", 1, string_ctor, &proto);
    vm.def_method(&ctor, "fromCharCode", 1, from_char_code);
    vm.def_method(&ctor, "raw", 1, raw);
    vm.def_method(&ctor, "fromCodePoint", 1, from_code_point);
    let methods: &[(&str, u32, NativeFn)] = &[
        ("toString", 0, to_string),
        ("valueOf", 0, to_string),
        ("charAt", 1, char_at),
        ("charCodeAt", 1, char_code_at),
        ("indexOf", 1, index_of),
        ("lastIndexOf", 1, last_index_of),
        ("toLocaleLowerCase", 0, to_lower_case),
        ("toLocaleUpperCase", 0, to_upper_case),
        ("normalize", 0, normalize),
        ("includes", 1, includes),
        ("startsWith", 1, starts_with),
        ("endsWith", 1, ends_with),
        ("slice", 2, slice),
        ("substring", 2, substring),
        ("substr", 2, substr),
        ("anchor", 1, anchor),
        ("link", 1, link),
        ("fontcolor", 1, fontcolor),
        ("fontsize", 1, fontsize),
        ("big", 0, big),
        ("blink", 0, blink),
        ("bold", 0, bold),
        ("fixed", 0, fixed),
        ("italics", 0, italics),
        ("small", 0, small),
        ("strike", 0, strike),
        ("sub", 0, sub),
        ("sup", 0, sup),
        ("toUpperCase", 0, to_upper_case),
        ("toLowerCase", 0, to_lower_case),
        ("isWellFormed", 0, is_well_formed),
        ("toWellFormed", 0, to_well_formed),
        ("trim", 0, trim),
        ("localeCompare", 1, locale_compare),
        ("toLocaleString", 0, to_string),
        ("concat", 1, concat),
        ("repeat", 1, repeat),
        ("split", 2, split),
        ("at", 1, at),
        ("codePointAt", 1, code_point_at),
        ("trimStart", 0, trim_start),
        ("trimEnd", 0, trim_end),
        ("padStart", 1, pad_start),
        ("padEnd", 1, pad_end),
        ("match", 1, crate::builtins::regexp::string_match),
        ("search", 1, crate::builtins::regexp::string_search),
        ("matchAll", 1, crate::builtins::regexp::string_match_all),
        ("replace", 2, crate::builtins::regexp::string_replace),
        ("replaceAll", 2, crate::builtins::regexp::string_replace_all),
    ];
    for (n, l, f) in methods {
        let fo = vm.def_method(&proto, n, *l, *f);
        if *n == "trimStart" {
            proto.set_prop(PropKey::from_str("trimLeft"), Value::Obj(fo.clone()), WC);
        }
        if *n == "trimEnd" {
            proto.set_prop(PropKey::from_str("trimRight"), Value::Obj(fo.clone()), WC);
        }
    }
    // reorder trimLeft/trimRight after trimEnd (already inserted in sequence)
    move_to_end(&proto, &vm.intr.key_constructor.clone());
    vm.def_sym_method(&proto, &vm.intr.sym_iterator.clone(), "[Symbol.iterator]", 0, iterator);
    vm.def_global("String", Value::Obj(ctor));
}

fn string_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = if a.args.is_empty() {
        JsStr::empty()
    } else {
        match (&a.args[0], &a.new_target) {
            (Value::Sym(s), None) => JsStr::from_str(&s.descriptive_string()),
            (v, _) => vm.to_string(v)?,
        }
    };
    match &a.new_target {
        None => Ok(Value::Str(s)),
        Some(_) => {
            let proto = vm.proto_from_nt(&a.new_target, &vm.intr.string_proto.clone())?;
            Ok(Value::Obj(Obj::with_class(Some(proto), ObjKind::String(s), "String")))
        }
    }
}

/// RequireObjectCoercible(this) + ToString
pub fn this_str(vm: &mut Vm, a: &Args) -> JsResult<JsStr> {
    match &a.this {
        Value::Str(s) => Ok(s.clone()),
        Value::Undefined | Value::Null => vm.throw_type("String.prototype method called on null or undefined"),
        v => vm.to_string(v),
    }
}

fn to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match &a.this {
        Value::Str(s) => Ok(Value::Str(s.clone())),
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::String(s) => Ok(Value::Str(s.clone())),
            _ => Err(vm.make_error("TypeError", "String.prototype.toString requires that 'this' be a String")),
        },
        _ => vm.throw_type("String.prototype.toString requires that 'this' be a String"),
    }
}

fn from_char_code(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut out = Vec::with_capacity(a.args.len());
    for v in a.args {
        let n = vm.to_number(v)?;
        out.push(crate::builtins::number::to_uint32(n) as u16);
    }
    Ok(Value::Str(JsStr::from_units(out)))
}

fn from_code_point(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut out = Vec::new();
    for v in a.args {
        let n = vm.to_number(v)?;
        if n.fract() != 0.0 || !(0.0..=1114111.0).contains(&n) || n.is_nan() {
            let s = vm.display_for_error(v);
            let _ = s;
            return vm.throw_range("Invalid code point");
        }
        push_cp(&mut out, n as u32);
    }
    Ok(Value::Str(JsStr::from_units(out)))
}

pub fn push_cp(out: &mut Vec<u16>, c: u32) {
    if c >= 0x10000 {
        let c = c - 0x10000;
        out.push(0xD800 + (c >> 10) as u16);
        out.push(0xDC00 + (c & 0x3ff) as u16);
    } else {
        out.push(c as u16);
    }
}

fn raw(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cooked = vm.to_object(&a.arg(0))?;
    let rawv = vm.get_str(&cooked, "raw")?;
    let raw = vm.to_object(&rawv)?;
    let len = vm.length_of(&raw)?;
    let mut out: Vec<u16> = Vec::new();
    for i in 0..len {
        let seg = vm.get(&raw, &PropKey::from_index(i as u32), &rawv)?;
        let s = vm.to_string(&seg)?;
        out.extend_from_slice(s.units());
        if i + 1 < len && (i as usize + 1) < a.args.len() {
            let sub = vm.to_string(&a.args[i as usize + 1])?;
            out.extend_from_slice(sub.units());
        }
    }
    Ok(Value::Str(JsStr::from_units(out)))
}

fn char_at(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    let p = vm.to_integer_or_infinity(&a.arg(0))?;
    if p < 0.0 || p >= s.len() as f64 {
        return Ok(Value::Str(JsStr::empty()));
    }
    Ok(Value::Str(JsStr::from_units(vec![s.units()[p as usize]])))
}

fn char_code_at(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    let p = match a.args.first() {
        Some(Value::Num(n)) if n.fract() == 0.0 => *n,
        _ => vm.to_integer_or_infinity(&a.arg(0))?,
    };
    if p < 0.0 || p >= s.len() as f64 {
        return Ok(Value::Num(f64::NAN));
    }
    Ok(Value::Num(s.units()[p as usize] as f64))
}

fn code_point_at(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    let p = vm.to_integer_or_infinity(&a.arg(0))?;
    if p < 0.0 || p >= s.len() as f64 {
        return Ok(Value::Undefined);
    }
    let u = s.units();
    let i = p as usize;
    let c = u[i];
    if (0xD800..0xDC00).contains(&c) && i + 1 < u.len() && (0xDC00..0xE000).contains(&u[i + 1]) {
        let cp = 0x10000 + (((c as u32) - 0xD800) << 10) + ((u[i + 1] as u32) - 0xDC00);
        return Ok(Value::Num(cp as f64));
    }
    Ok(Value::Num(c as f64))
}

fn at(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    let n = vm.to_integer_or_infinity(&a.arg(0))?;
    let k = if n >= 0.0 { n } else { s.len() as f64 + n };
    if k < 0.0 || k >= s.len() as f64 {
        return Ok(Value::Undefined);
    }
    Ok(Value::Str(JsStr::from_units(vec![s.units()[k as usize]])))
}

fn is_regexp(vm: &mut Vm, v: &Value) -> JsResult<bool> {
    if let Value::Obj(o) = v {
        let m = vm.get(o, &PropKey::Sym(vm.intr.sym_match.clone()), v)?;
        if !m.is_undefined() {
            return Ok(m.truthy());
        }
        return Ok(matches!(o.borrow().kind, ObjKind::RegExp(_)));
    }
    Ok(false)
}

fn index_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    let search = vm.to_string(&a.arg(0))?;
    let pos = vm.to_integer_or_infinity(&a.arg(1))?;
    let start = pos.max(0.0).min(s.len() as f64) as usize;
    Ok(Value::Num(match s.index_of(search.units(), start) {
        Some(i) => i as f64,
        None => -1.0,
    }))
}

fn last_index_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    let search = vm.to_string(&a.arg(0))?;
    let n = vm.to_number(&a.arg(1))?;
    let pos = if n.is_nan() { f64::INFINITY } else { crate::ops::integer_or_infinity(n) };
    let len = s.len();
    let sl = search.len();
    let start = pos.max(0.0).min(len as f64) as usize;
    let su = s.units();
    let pu = search.units();
    if sl > len {
        return Ok(Value::Num(-1.0));
    }
    let mut i = start.min(len - sl) as i64;
    while i >= 0 {
        let iu = i as usize;
        if &su[iu..iu + sl] == pu {
            return Ok(Value::Num(i as f64));
        }
        i -= 1;
    }
    Ok(Value::Num(-1.0))
}

fn includes(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    if is_regexp(vm, &a.arg(0))? {
        return vm.throw_type("argument must not be a regular expression");
    }
    let search = vm.to_string(&a.arg(0))?;
    let pos = vm.to_integer_or_infinity(&a.arg(1))?;
    let start = pos.max(0.0).min(s.len() as f64) as usize;
    Ok(Value::Bool(s.index_of(search.units(), start).is_some()))
}

fn starts_with(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    if is_regexp(vm, &a.arg(0))? {
        return vm.throw_type("argument must not be a regular expression");
    }
    let search = vm.to_string(&a.arg(0))?;
    let pos = vm.to_integer_or_infinity(&a.arg(1))?;
    let start = pos.max(0.0).min(s.len() as f64) as usize;
    let u = s.units();
    let p = search.units();
    Ok(Value::Bool(start + p.len() <= u.len() && &u[start..start + p.len()] == p))
}

fn ends_with(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    if is_regexp(vm, &a.arg(0))? {
        return vm.throw_type("argument must not be a regular expression");
    }
    let search = vm.to_string(&a.arg(0))?;
    let len = s.len();
    let end = if a.arg(1).is_undefined() { len } else { vm.to_integer_or_infinity(&a.arg(1))?.max(0.0).min(len as f64) as usize };
    let p = search.units();
    if p.len() > end {
        return Ok(Value::Bool(false));
    }
    let start = end - p.len();
    Ok(Value::Bool(&s.units()[start..end] == p))
}

fn slice(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    let len = s.len() as f64;
    let st = vm.to_integer_or_infinity(&a.arg(0))?;
    let from = if st < 0.0 { (len + st).max(0.0) } else { st.min(len) };
    let en = if a.arg(1).is_undefined() { len } else { vm.to_integer_or_infinity(&a.arg(1))? };
    let to = if en < 0.0 { (len + en).max(0.0) } else { en.min(len) };
    if from >= to {
        return Ok(Value::Str(JsStr::empty()));
    }
    Ok(Value::Str(s.substring(from as usize, to as usize)))
}

fn substring(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    let len = s.len() as f64;
    let st = vm.to_integer_or_infinity(&a.arg(0))?.max(0.0).min(len);
    let en = if a.arg(1).is_undefined() { len } else { vm.to_integer_or_infinity(&a.arg(1))?.max(0.0).min(len) };
    let (f, t) = if st < en { (st, en) } else { (en, st) };
    Ok(Value::Str(s.substring(f as usize, t as usize)))
}

fn substr(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    let len = s.len() as f64;
    let st = vm.to_integer_or_infinity(&a.arg(0))?;
    let start = if st < 0.0 { (len + st).max(0.0) } else { st.min(len) };
    let l = if a.arg(1).is_undefined() { len } else { vm.to_integer_or_infinity(&a.arg(1))? };
    let end = (start + l.max(0.0)).min(len);
    if start >= end {
        return Ok(Value::Str(JsStr::empty()));
    }
    Ok(Value::Str(s.substring(start as usize, end as usize)))
}

fn html(vm: &mut Vm, a: &Args, tag: &str, attr: Option<&str>) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    let mut out = format!("<{}", tag);
    if let Some(at) = attr {
        let v = vm.to_string(&a.arg(0))?.to_rust_string().replace('"', "&quot;");
        out.push_str(&format!(" {}=\"{}\"", at, v));
    }
    out.push('>');
    out.push_str(&s.to_rust_string());
    out.push_str(&format!("</{}>", tag));
    Ok(Value::str(&out))
}

fn anchor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    html(vm, a, "a", Some("name"))
}
fn link(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    html(vm, a, "a", Some("href"))
}
fn fontcolor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    html(vm, a, "font", Some("color"))
}
fn fontsize(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    html(vm, a, "font", Some("size"))
}
fn big(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    html(vm, a, "big", None)
}
fn blink(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    html(vm, a, "blink", None)
}
fn bold(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    html(vm, a, "b", None)
}
fn fixed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    html(vm, a, "tt", None)
}
fn italics(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    html(vm, a, "i", None)
}
fn small(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    html(vm, a, "small", None)
}
fn strike(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    html(vm, a, "strike", None)
}
fn sub(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    html(vm, a, "sub", None)
}
fn sup(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    html(vm, a, "sup", None)
}

fn to_upper_case(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    if s.is_ascii() {
        let v: Vec<u16> = s.units().iter().map(|&c| if (b'a' as u16..=b'z' as u16).contains(&c) { c - 32 } else { c }).collect();
        return Ok(Value::Str(JsStr::from_units(v)));
    }
    Ok(Value::Str(JsStr::from_units(crate::unicode::str_to_upper(s.units()))))
}

fn to_lower_case(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    if s.is_ascii() {
        let v: Vec<u16> = s.units().iter().map(|&c| if (b'A' as u16..=b'Z' as u16).contains(&c) { c + 32 } else { c }).collect();
        return Ok(Value::Str(JsStr::from_units(v)));
    }
    Ok(Value::Str(JsStr::from_units(crate::unicode::str_to_lower(s.units()))))
}

fn normalize(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    let f = if a.arg(0).is_undefined() { "NFC".to_string() } else { vm.to_string(&a.arg(0))?.to_rust_string() };
    let form = match f.as_str() {
        "NFC" => crate::unicode::NormForm::Nfc,
        "NFD" => crate::unicode::NormForm::Nfd,
        "NFKC" => crate::unicode::NormForm::Nfkc,
        "NFKD" => crate::unicode::NormForm::Nfkd,
        _ => return vm.throw_range("The normalization form should be one of NFC, NFD, NFKC, NFKD"),
    };
    if s.is_ascii() {
        return Ok(Value::Str(s));
    }
    Ok(Value::Str(JsStr::from_units(crate::unicode::normalize(s.units(), form))))
}

fn is_well_formed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    let u = s.units();
    let mut i = 0;
    while i < u.len() {
        let c = u[i];
        if (0xD800..0xDC00).contains(&c) {
            if i + 1 < u.len() && (0xDC00..0xE000).contains(&u[i + 1]) {
                i += 2;
                continue;
            }
            return Ok(Value::Bool(false));
        }
        if (0xDC00..0xE000).contains(&c) {
            return Ok(Value::Bool(false));
        }
        i += 1;
    }
    Ok(Value::Bool(true))
}

fn to_well_formed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    let u = s.units();
    let mut out = Vec::with_capacity(u.len());
    let mut i = 0;
    while i < u.len() {
        let c = u[i];
        if (0xD800..0xDC00).contains(&c) {
            if i + 1 < u.len() && (0xDC00..0xE000).contains(&u[i + 1]) {
                out.push(c);
                out.push(u[i + 1]);
                i += 2;
                continue;
            }
            out.push(0xFFFD);
        } else if (0xDC00..0xE000).contains(&c) {
            out.push(0xFFFD);
        } else {
            out.push(c);
        }
        i += 1;
    }
    Ok(Value::Str(JsStr::from_units(out)))
}

pub fn is_ws(c: u16) -> bool {
    crate::numconv::is_js_whitespace(c)
}

fn trim_impl(s: &JsStr, start: bool, end: bool) -> JsStr {
    let u = s.units();
    let mut a = 0;
    let mut b = u.len();
    if start {
        while a < b && is_ws(u[a]) {
            a += 1;
        }
    }
    if end {
        while b > a && is_ws(u[b - 1]) {
            b -= 1;
        }
    }
    s.substring(a, b)
}

fn trim(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    Ok(Value::Str(trim_impl(&s, true, true)))
}
fn trim_start(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    Ok(Value::Str(trim_impl(&s, true, false)))
}
fn trim_end(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    Ok(Value::Str(trim_impl(&s, false, true)))
}

/// Collation key-based comparison approximating the root locale.
pub fn locale_cmp(a: &[u16], b: &[u16], sensitivity: u8) -> i32 {
    // sensitivity: 0 base, 1 accent, 2 case, 3 variant
    let da = crate::unicode::normalize(a, crate::unicode::NormForm::Nfd);
    let db = crate::unicode::normalize(b, crate::unicode::NormForm::Nfd);
    fn keys(s: &[u16]) -> (Vec<u32>, Vec<u32>, Vec<u32>) {
        let mut prim = Vec::new();
        let mut sec = Vec::new();
        let mut ter = Vec::new();
        let chars: Vec<u32> = char::decode_utf16(s.iter().copied()).map(|r| r.map(|c| c as u32).unwrap_or(0xFFFD)).collect();
        for &c in &chars {
            if crate::unicode::canonical_combining_class(c) != 0 {
                sec.push(c);
                continue;
            }
            let ch = char::from_u32(c).unwrap_or('\u{fffd}');
            let lower: Vec<char> = ch.to_lowercase().collect();
            let l = lower[0] as u32;
            // primary weight: punctuation/whitespace < digits < letters
            let w = if ch.is_whitespace() {
                0x100 + l
            } else if ch.is_ascii_punctuation() || (!ch.is_alphanumeric() && c < 0x3000) {
                0x1000 + l
            } else if ch.is_numeric() {
                0x10000 + l
            } else {
                0x100000 + l
            };
            prim.push(w);
            sec.push(0);
            ter.push(if ch.is_uppercase() { 1 } else { 0 });
        }
        (prim, sec, ter)
    }
    let (pa, sa, ta) = keys(&da);
    let (pb, sb, tb) = keys(&db);
    let c = pa.cmp(&pb);
    if c != std::cmp::Ordering::Equal {
        return if c == std::cmp::Ordering::Less { -1 } else { 1 };
    }
    if sensitivity >= 1 {
        let c = sa.cmp(&sb);
        if c != std::cmp::Ordering::Equal {
            return if c == std::cmp::Ordering::Less { -1 } else { 1 };
        }
    }
    if sensitivity >= 2 {
        let c = ta.cmp(&tb);
        if c != std::cmp::Ordering::Equal {
            return if c == std::cmp::Ordering::Less { -1 } else { 1 };
        }
    }
    if sensitivity >= 3 {
        let c = da.cmp(&db);
        if c != std::cmp::Ordering::Equal {
            return if c == std::cmp::Ordering::Less { -1 } else { 1 };
        }
    }
    0
}

fn locale_compare(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    let t = vm.to_string(&a.arg(0))?;
    let mut sens = 3u8;
    if let Value::Obj(o) = a.arg(2) {
        let sv = vm.get_str(&o, "sensitivity")?;
        if let Value::Str(x) = sv {
            sens = match x.to_rust_string().as_str() {
                "base" => 0,
                "accent" => 1,
                "case" => 2,
                _ => 3,
            };
        }
    }
    Ok(Value::Num(locale_cmp(s.units(), t.units(), sens) as f64))
}

fn concat(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut s = this_str(vm, a)?;
    for v in a.args {
        let t = vm.to_string(v)?;
        s = JsStr::concat(&s, &t);
    }
    Ok(Value::Str(s))
}

fn repeat(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    let n = vm.to_integer_or_infinity(&a.arg(0))?;
    if n < 0.0 || n.is_infinite() {
        return vm.throw_range("invalid count value");
    }
    if s.is_empty() || n == 0.0 {
        return Ok(Value::Str(JsStr::empty()));
    }
    if (s.len() as f64) * n > 536870888.0 {
        return vm.throw_range("Invalid string length");
    }
    let mut out = Vec::with_capacity(s.len() * n as usize);
    for _ in 0..n as usize {
        out.extend_from_slice(s.units());
    }
    Ok(Value::Str(JsStr::from_units(out)))
}

fn split(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let sep = a.arg(0);
    if a.this.is_nullish() {
        return vm.throw_type("String.prototype.split called on null or undefined");
    }
    if !sep.is_nullish() {
        let splitter = vm.get_method(&sep, &PropKey::Sym(vm.intr.sym_split.clone()))?;
        if let Some(f) = splitter {
            return vm.call(&f, sep.clone(), &[a.this.clone(), a.arg(1)]);
        }
    }
    let s = vm.to_string(&a.this)?;
    let lim = if a.arg(1).is_undefined() { u32::MAX } else { vm.to_uint32(&a.arg(1))? };
    let r = vm.to_string(&sep)?;
    if lim == 0 {
        return Ok(Value::Obj(vm.new_array(Vec::new())));
    }
    if sep.is_undefined() {
        return Ok(Value::Obj(vm.new_array(vec![Value::Str(s)])));
    }
    let su = s.units();
    let ru = r.units();
    let mut out = Vec::new();
    if ru.is_empty() {
        for &c in su.iter().take(lim as usize) {
            out.push(Value::Str(JsStr::from_units(vec![c])));
        }
        return Ok(Value::Obj(vm.new_array(out)));
    }
    if su.is_empty() {
        return Ok(Value::Obj(vm.new_array(vec![Value::Str(s)])));
    }
    let mut p = 0;
    let mut q = 0;
    while q + ru.len() <= su.len() {
        if &su[q..q + ru.len()] == ru {
            out.push(Value::Str(JsStr::from_slice(&su[p..q])));
            if out.len() as u32 >= lim {
                return Ok(Value::Obj(vm.new_array(out)));
            }
            q += ru.len();
            p = q;
        } else {
            q += 1;
        }
    }
    out.push(Value::Str(JsStr::from_slice(&su[p..])));
    Ok(Value::Obj(vm.new_array(out)))
}

fn pad(vm: &mut Vm, a: &Args, at_start: bool) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    let max = vm.to_length(&a.arg(0))? as usize;
    let len = s.len();
    if max <= len {
        return Ok(Value::Str(s));
    }
    let fill = if a.arg(1).is_undefined() { JsStr::from_str(" ") } else { vm.to_string(&a.arg(1))? };
    if fill.is_empty() {
        return Ok(Value::Str(s));
    }
    if max > 536870888 {
        return vm.throw_range("Invalid string length");
    }
    let need = max - len;
    let fu = fill.units();
    let mut padv = Vec::with_capacity(need);
    while padv.len() < need {
        let take = (need - padv.len()).min(fu.len());
        padv.extend_from_slice(&fu[..take]);
    }
    let mut out = Vec::with_capacity(max);
    if at_start {
        out.extend(padv);
        out.extend_from_slice(s.units());
    } else {
        out.extend_from_slice(s.units());
        out.extend(padv);
    }
    Ok(Value::Str(JsStr::from_units(out)))
}

fn pad_start(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    pad(vm, a, true)
}
fn pad_end(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    pad(vm, a, false)
}

fn iterator(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_str(vm, a)?;
    Ok(crate::builtins::iterator::create_string_iterator(vm, s))
}
