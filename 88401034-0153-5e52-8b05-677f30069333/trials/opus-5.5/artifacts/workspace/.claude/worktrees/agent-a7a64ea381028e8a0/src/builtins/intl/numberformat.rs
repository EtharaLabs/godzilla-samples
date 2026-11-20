//! Intl.NumberFormat (placeholder -- being rewritten).

use super::*;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    define_class(
        vm,
        intl,
        "NumberFormat",
        0,
        not_implemented,
        &[
            Member::Getter("format", not_implemented),
            Member::Method("formatToParts", 1, not_implemented),
            Member::Method("resolvedOptions", 0, not_implemented),
            Member::Method("formatRange", 2, not_implemented),
            Member::Method("formatRangeToParts", 2, not_implemented),
        ],
        true,
    );
}

pub fn group_digits_str(s: &str, sep: &str) -> String {
    let (neg, digits) = if let Some(rest) = s.strip_prefix('-') { (true, rest) } else { (false, s) };
    let mut out = String::new();
    let n = digits.len();
    for (i, c) in digits.chars().enumerate() {
        if i > 0 && (n - i) % 3 == 0 {
            out.push_str(sep);
        }
        out.push(c);
    }
    if neg {
        format!("-{}", out)
    } else {
        out
    }
}

pub fn number_to_locale_string(vm: &mut Vm, x: f64, locales: &Value, _opts: &Value) -> JsResult<Value> {
    let _ = locale_list(vm, locales)?;
    let s = crate::numconv::to_fixed(x.abs(), 3);
    let s = s.trim_end_matches('0').trim_end_matches('.').to_string();
    let (i, f) = match s.find('.') {
        Some(p) => (s[..p].to_string(), s[p..].to_string()),
        None => (s.clone(), String::new()),
    };
    let r = format!("{}{}{}", if x < 0.0 { "-" } else { "" }, group_digits_str(&i, ","), f);
    Ok(Value::str(&r))
}
