//! Intl.PluralRules.
//!
//! The original's rules: `fr`, `gv`, `pl` and `sl` follow CLDR; `ja ko th
//! zh` only have "other"; every other language (including `ar` and `ru`,
//! whose pluralCategories nevertheless list all CLDR categories) has "one"
//! for exactly 1 (no visible fraction digits) and "other" otherwise.  The
//! `type` (cardinal/ordinal) and all digit options are stored but ignored by
//! `select`, which looks at the raw number.  `selectRange(x, y)` is
//! `select(y)`.
//!
//! Slots: `__pr: true`, `__pr_locale`, `__pr_type`, `__pr_minint`,
//! `__pr_minfrac`, `__pr_maxfrac`, `__pr_notation`, `__pr_compactdisplay`,
//! `__pr_roundingmode`, then `__pr_minsig` / `__pr_maxsig` when given.

use super::decimal::Decimal;
use super::*;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    define_class(
        vm,
        intl,
        "PluralRules",
        0,
        pr_ctor,
        &[
            Member::Method("select", 1, pr_select),
            Member::Method("selectRange", 2, pr_select_range),
            Member::Method("resolvedOptions", 0, pr_resolved_options),
        ],
        true,
    );
}

/// pluralCategories of a language.
pub fn plural_categories(lang: &str) -> &'static [&'static str] {
    match lang {
        "ar" => &["zero", "one", "two", "few", "many", "other"],
        "fr" => &["one", "many", "other"],
        "gv" => &["one", "two", "few", "many", "other"],
        "pl" | "ru" => &["one", "few", "many", "other"],
        "sl" => &["one", "two", "few", "other"],
        "ja" | "ko" | "th" | "zh" => &["other"],
        _ => &["one", "other"],
    }
}

/// i mod 10^k of the integer part of `d`.
fn int_mod(d: &Decimal, k: u32) -> u64 {
    let mut r: u64 = 0;
    let ip = d.point.max(0) as usize;
    let start = ip.saturating_sub(k as usize);
    for idx in start..ip {
        r = r * 10 + d.digits.get(idx).copied().unwrap_or(0) as u64;
    }
    r
}

fn int_is(d: &Decimal, v: u64) -> bool {
    // integer part equals v (v small)
    let ip = d.point.max(0) as usize;
    if ip > 20 {
        return false;
    }
    int_mod(d, 20) == v
}

/// Plural category of a decimal (absolute value; `v` = visible fraction
/// digits) under the original's rules.
pub fn plural_category_dec(lang: &str, d: &Decimal) -> &'static str {
    let v0 = d.is_integer();
    match lang {
        "ja" | "ko" | "th" | "zh" => "other",
        "fr" => {
            if int_is(d, 0) || int_is(d, 1) {
                "one"
            } else if v0 && d.point > 0 && int_mod(d, 6) == 0 && !int_is(d, 0) {
                "many"
            } else {
                "other"
            }
        }
        "gv" => {
            if !v0 {
                "many"
            } else if int_mod(d, 1) == 1 {
                "one"
            } else if int_mod(d, 1) == 2 {
                "two"
            } else if [0, 20, 40, 60, 80].contains(&int_mod(d, 2)) {
                "few"
            } else {
                "other"
            }
        }
        "pl" => {
            if !v0 {
                return "other";
            }
            let i10 = int_mod(d, 1);
            let i100 = int_mod(d, 2);
            if int_is(d, 1) {
                "one"
            } else if (2..=4).contains(&i10) && !(12..=14).contains(&i100) {
                "few"
            } else {
                "many"
            }
        }
        "sl" => {
            if !v0 {
                return "few";
            }
            match int_mod(d, 2) {
                1 => "one",
                2 => "two",
                3 | 4 => "few",
                _ => "other",
            }
        }
        _ => {
            if v0 && int_is(d, 1) {
                "one"
            } else {
                "other"
            }
        }
    }
}

/// Plural category of a JS number.
pub fn plural_category(lang: &str, x: f64) -> &'static str {
    if !x.is_finite() {
        return "other";
    }
    plural_category_dec(lang, &Decimal::from_f64(x))
}

fn pr_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_new(vm, a, "PluralRules")?;
    let locales = locale_list(vm, &a.arg(0))?;
    let opts = get_options(vm, &a.arg(1), OptionsMode::Strict)?;
    read_locale_matcher(vm, &opts)?;
    let ty = get_opt_str(vm, &opts, "type", &["cardinal", "ordinal"])?.unwrap_or_else(|| "cardinal".into());
    let notation = get_opt_str(vm, &opts, "notation", &["standard", "scientific", "engineering", "compact"])?
        .unwrap_or_else(|| "standard".into());
    let compact = get_opt_str(vm, &opts, "compactDisplay", &["short", "long"])?.unwrap_or_else(|| "short".into());
    let minint = get_opt_num(vm, &opts, "minimumIntegerDigits", 1.0, 21.0)?.unwrap_or(1.0);
    let minfrac = get_opt_num(vm, &opts, "minimumFractionDigits", 0.0, 100.0)?.unwrap_or(0.0);
    let maxfrac = get_opt_num(vm, &opts, "maximumFractionDigits", minfrac, 100.0)?.unwrap_or(minfrac.max(3.0));
    let mnsd = get_opt(vm, &opts, "minimumSignificantDigits")?;
    let mxsd = get_opt(vm, &opts, "maximumSignificantDigits")?;
    let mut sig = None;
    if !mnsd.is_undefined() || !mxsd.is_undefined() {
        let lo = num_in_range(vm, &mnsd, "minimumSignificantDigits", 1.0, 21.0, 1.0)?;
        let hi = num_in_range(vm, &mxsd, "maximumSignificantDigits", 1.0, 21.0, 21.0)?;
        sig = Some((lo, hi));
    }
    let _ = get_opt(vm, &opts, "roundingIncrement")?;
    let mode = get_opt_str(
        vm,
        &opts,
        "roundingMode",
        &["ceil", "floor", "expand", "trunc", "halfCeil", "halfFloor", "halfExpand", "halfTrunc", "halfEven"],
    )?
    .unwrap_or_else(|| "halfExpand".into());
    get_opt_str(vm, &opts, "roundingPriority", &["auto", "morePrecision", "lessPrecision"])?;
    get_opt_str(vm, &opts, "trailingZeroDisplay", &["auto", "stripIfInteger"])?;
    let r = resolve_locale(&locales);
    let o = alloc_instance(vm, a)?;
    set_slot(&o, "__pr", Value::Bool(true));
    set_slot(&o, "__pr_locale", Value::str(&r.base));
    set_slot(&o, "__pr_type", Value::str(&ty));
    set_slot(&o, "__pr_minint", Value::Num(minint));
    set_slot(&o, "__pr_minfrac", Value::Num(minfrac));
    set_slot(&o, "__pr_maxfrac", Value::Num(maxfrac));
    set_slot(&o, "__pr_notation", Value::str(&notation));
    set_slot(&o, "__pr_compactdisplay", Value::str(&compact));
    set_slot(&o, "__pr_roundingmode", Value::str(&mode));
    if let Some((lo, hi)) = sig {
        set_slot(&o, "__pr_minsig", Value::Num(lo));
        set_slot(&o, "__pr_maxsig", Value::Num(hi));
    }
    Ok(Value::Obj(o))
}

/// DefaultNumberOption-like read: undefined -> default; NaN or outside
/// [min, max] -> `RangeError: <name> out of range`.
fn num_in_range(vm: &mut Vm, v: &Value, name: &str, min: f64, max: f64, default: f64) -> JsResult<f64> {
    if v.is_undefined() {
        return Ok(default);
    }
    let n = vm.to_number(v)?;
    if n.is_nan() || n < min || n > max {
        return vm.throw_range(format!("{} out of range", name));
    }
    Ok(n.floor())
}

fn pr_lang(o: &Obj) -> String {
    let loc = slot_str(o, "__pr_locale").unwrap_or_else(|| "en".to_string());
    match parse_tag(&loc) {
        Some(t) => t.language,
        None => "en".to_string(),
    }
}

fn pr_select(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.this, "__pr")?;
    let n = vm.to_number(&a.arg(0))?;
    Ok(Value::str(plural_category(&pr_lang(&o), n)))
}

fn pr_select_range(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.this, "__pr")?;
    let (s, e) = (a.arg(0), a.arg(1));
    if s.is_undefined() || e.is_undefined() {
        return vm.throw_type("selectRange requires two numbers");
    }
    let x = vm.to_number(&s)?;
    let y = vm.to_number(&e)?;
    if x.is_nan() || y.is_nan() {
        return vm.throw_range("selectRange arguments must not be NaN");
    }
    Ok(Value::str(plural_category(&pr_lang(&o), y)))
}

fn pr_resolved_options(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.this, "__pr")?;
    let r = vm.new_object();
    let copy = |r: &Obj, key: &str, name: &str| {
        if let Some(v) = slot(&o, name) {
            if !v.is_undefined() {
                r.set_str(key, v, WEC);
            }
        }
    };
    copy(&r, "locale", "__pr_locale");
    copy(&r, "type", "__pr_type");
    copy(&r, "notation", "__pr_notation");
    if slot_str(&o, "__pr_notation").as_deref() == Some("compact") {
        copy(&r, "compactDisplay", "__pr_compactdisplay");
    }
    copy(&r, "minimumIntegerDigits", "__pr_minint");
    copy(&r, "minimumFractionDigits", "__pr_minfrac");
    copy(&r, "maximumFractionDigits", "__pr_maxfrac");
    copy(&r, "minimumSignificantDigits", "__pr_minsig");
    copy(&r, "maximumSignificantDigits", "__pr_maxsig");
    let cats: Vec<String> = plural_categories(&pr_lang(&o)).iter().map(|s| s.to_string()).collect();
    let arr = str_array(vm, &cats);
    r.set_str("pluralCategories", arr, WEC);
    copy(&r, "roundingMode", "__pr_roundingmode");
    Ok(Value::Obj(r))
}
