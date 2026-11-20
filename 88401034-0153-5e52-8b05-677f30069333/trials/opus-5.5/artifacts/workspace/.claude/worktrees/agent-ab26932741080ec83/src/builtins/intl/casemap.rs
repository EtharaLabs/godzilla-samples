//! String.prototype.toLocaleLowerCase / toLocaleUpperCase.
//!
//! The locale is the first element of CanonicalizeLocaleList(locales)
//! (errors as for Intl constructors).  Turkish/Azeri (`tr`, `az`) and
//! Lithuanian (`lt`) apply the conditional SpecialCasing rules (After_I,
//! Not_Before_Dot, More_Above, After_Soft_Dotted, precomposed Ì Í Ĩ) to the
//! string as given (no normalization) and, like the original, do not apply
//! the final-sigma rule; every other locale behaves like
//! toLowerCase / toUpperCase.

use super::*;
use std::sync::OnceLock;

fn this_string(vm: &mut Vm, a: &Args) -> JsResult<JsStr> {
    if a.this.is_nullish() {
        return vm.throw_type("String.prototype method called on null or undefined");
    }
    vm.to_string(&a.this)
}

fn special_lang(vm: &mut Vm, locales: &Value) -> JsResult<&'static str> {
    let list = locale_list(vm, locales)?;
    let lang = match list.first().and_then(|l| parse_tag(l)) {
        Some(t) => t.language,
        None => String::new(),
    };
    Ok(match lang.as_str() {
        "tr" | "az" => "tr",
        "lt" => "lt",
        _ => "",
    })
}

pub fn to_locale_lower_case(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_string(vm, a)?;
    let lang = special_lang(vm, &a.arg(0))?;
    let out = match lang {
        "tr" | "lt" => special_lower(s.units(), lang),
        _ => crate::unicode::str_to_lower(s.units()),
    };
    Ok(Value::Str(JsStr::from_units(out)))
}

pub fn to_locale_upper_case(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = this_string(vm, a)?;
    let lang = special_lang(vm, &a.arg(0))?;
    let out = match lang {
        "tr" | "lt" => special_upper(s.units(), lang),
        _ => crate::unicode::str_to_upper(s.units()),
    };
    Ok(Value::Str(JsStr::from_units(out)))
}

/// Code points (lone surrogates kept as their code unit).
fn code_points(s: &[u16]) -> Vec<u32> {
    char::decode_utf16(s.iter().copied())
        .map(|r| match r {
            Ok(c) => c as u32,
            Err(e) => e.unpaired_surrogate() as u32,
        })
        .collect()
}

fn push_cp(out: &mut Vec<u16>, c: u32) {
    if c >= 0x10000 {
        let v = c - 0x10000;
        out.push(0xD800 + (v >> 10) as u16);
        out.push(0xDC00 + (v & 0x3FF) as u16);
    } else {
        out.push(c as u16);
    }
}

fn ccc(c: u32) -> u8 {
    crate::unicode::canonical_combining_class(c)
}

fn soft_dotted(c: u32) -> bool {
    static R: OnceLock<Vec<(u32, u32)>> = OnceLock::new();
    let r = R.get_or_init(|| crate::unicode::property_ranges("Soft_Dotted", None).unwrap_or_default());
    r.binary_search_by(|&(lo, hi)| {
        if hi < c {
            std::cmp::Ordering::Less
        } else if lo > c {
            std::cmp::Ordering::Greater
        } else {
            std::cmp::Ordering::Equal
        }
    })
    .is_ok()
}

/// A combining dot above follows `i` (no intervening class 0 / 230).
fn before_dot(cps: &[u32], i: usize) -> bool {
    for &c in &cps[i + 1..] {
        if c == 0x307 {
            return true;
        }
        let k = ccc(c);
        if k == 0 || k == 230 {
            return false;
        }
    }
    false
}

/// A class-230 mark follows `i` (no intervening class 0 / 230), and which.
fn more_above(cps: &[u32], i: usize) -> Option<u32> {
    for &c in &cps[i + 1..] {
        let k = ccc(c);
        if k == 230 {
            return Some(c);
        }
        if k == 0 {
            return None;
        }
    }
    None
}

/// Preceded by `pred` (no intervening class 0 / 230).
fn after(cps: &[u32], i: usize, pred: impl Fn(u32) -> bool) -> bool {
    let mut j = i;
    while j > 0 {
        j -= 1;
        let c = cps[j];
        if pred(c) {
            return true;
        }
        let k = ccc(c);
        if k == 0 || k == 230 {
            return false;
        }
    }
    false
}

fn special_lower(s: &[u16], lang: &str) -> Vec<u16> {
    let cps = code_points(s);
    let mut out = Vec::with_capacity(s.len());
    for (i, &c) in cps.iter().enumerate() {
        if lang == "tr" {
            match c {
                0x130 => {
                    out.push('i' as u16);
                    continue;
                }
                0x307 if after(&cps, i, |p| p == 'I' as u32) => continue,
                0x49 => {
                    out.push(if before_dot(&cps, i) { 'i' as u16 } else { 0x131 });
                    continue;
                }
                _ => {}
            }
        } else {
            match c {
                0xCC => {
                    out.extend_from_slice(&[0x69, 0x307, 0x300]);
                    continue;
                }
                0xCD => {
                    out.extend_from_slice(&[0x69, 0x307, 0x301]);
                    continue;
                }
                0x128 => {
                    out.extend_from_slice(&[0x69, 0x307, 0x303]);
                    continue;
                }
                0x49 | 0x4A | 0x12E => {
                    for m in crate::unicode::to_lower_full(c) {
                        push_cp(&mut out, m);
                    }
                    if more_above(&cps, i).is_some() {
                        out.push(0x307);
                    }
                    continue;
                }
                _ => {}
            }
        }
        for m in crate::unicode::to_lower_full(c) {
            push_cp(&mut out, m);
        }
    }
    out
}

fn special_upper(s: &[u16], lang: &str) -> Vec<u16> {
    let cps = code_points(s);
    let mut out = Vec::with_capacity(s.len());
    for (i, &c) in cps.iter().enumerate() {
        if lang == "tr" && c == 'i' as u32 {
            out.push(0x130);
            continue;
        }
        if lang == "lt" && c == 0x307 && after(&cps, i, soft_dotted) {
            continue;
        }
        for m in crate::unicode::to_upper_full(c) {
            push_cp(&mut out, m);
        }
    }
    out
}
