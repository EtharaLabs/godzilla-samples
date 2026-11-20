//! Intl.DurationFormat.
//!
//! Slots (own data properties, in this order): `__df: true`, `__df_locale`,
//! `__df_style`, `__df_nu`, then for every unit (years .. nanoseconds)
//! `__df_u_<unit>` (style) and `__df_d_<unit>` (display), and `__df_frac`
//! when `fractionalDigits` was given.  `format` / `formatToParts` read the
//! slots back on every call.
//!
//! Constructor (an earlier ECMA-402 draft): styles are read in unit order;
//! years..days accept long/short/narrow, hours..seconds also
//! numeric/2-digit, milliseconds..nanoseconds also numeric (= fractional).
//! A unit without explicit style takes the digital base (short for
//! years..days, numeric otherwise) for style "digital", "numeric" after a
//! numeric/2-digit unit, else the base style; the display default is
//! "always" for explicit styles and the hours/minutes/seconds of "digital",
//! else "auto" (subsecond "numeric" units are "auto" too).  After a
//! numeric/2-digit unit, minutes/seconds become "2-digit" and a
//! non-numeric style is `RangeError: <unit> style conflicts with a
//! preceding numeric unit`.
//!
//! Formatting (slot values are re-validated with the NumberFormat messages:
//! locale, numberingSystem, then each unit's unitDisplay): every unit
//! shown (non-zero or display not "auto") is formatted with the
//! NumberFormat machinery (unit style, unitDisplay = the unit's style);
//! consecutive numeric/2-digit units form one "h:mm:ss" element (no
//! grouping, ":" between the shown units, minutes forced after shown hours
//! when any of seconds..nanoseconds is non-zero or the seconds display is
//! "always"); a unit followed by a "numeric" subsecond unit absorbs the
//! smaller units as fraction digits (0..9, or exactly fractionalDigits,
//! truncated) and ends the list.  Only the first shown unit carries the
//! sign ("-0" when its value is zero).  Elements are joined like
//! `Intl.ListFormat(locale, {type: "unit", style})` (digital -> short).
//! formatToParts adds `unit` (singular) to every part of an element.
//!
//! Durations: objects are read in unit order (ToNumber, must be integral:
//! `RangeError: invalid duration field <unit>`; none present: `TypeError:
//! duration has no recognized fields`), then checked for mixed signs,
//! |years|,|months|,|weeks| < 2^32 ("calendar unit out of range") and a
//! time total below 2^53 s ("duration time total out of range").  Primitive
//! strings are ISO 8601 durations (lenient, unchecked); anything else is
//! `TypeError: duration must be an object`.

use super::decimal::{Decimal, RoundingMode};
use super::numberformat::{format_parts, Grouping, MathValue, NfConfig, RoundingType, SignDisplay, Src, Style};
use super::*;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    define_class(
        vm,
        intl,
        "DurationFormat",
        0,
        df_ctor,
        &[
            Member::Method("format", 1, df_format),
            Member::Method("formatToParts", 1, df_format_to_parts),
            Member::Method("resolvedOptions", 0, df_resolved_options),
        ],
        true,
    );
}

/// (plural option name, singular NumberFormat unit)
const UNITS: [(&str, &str); 10] = [
    ("years", "year"),
    ("months", "month"),
    ("weeks", "week"),
    ("days", "day"),
    ("hours", "hour"),
    ("minutes", "minute"),
    ("seconds", "second"),
    ("milliseconds", "millisecond"),
    ("microseconds", "microsecond"),
    ("nanoseconds", "nanosecond"),
];

const IDX_HOURS: usize = 4;
const IDX_MINUTES: usize = 5;
const IDX_SECONDS: usize = 6;
const IDX_MS: usize = 7;

// ============================================================================
// Constructor
// ============================================================================

fn df_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_new(vm, a, "DurationFormat")?;
    let locales = locale_list(vm, &a.arg(0))?;
    let opts = get_options(vm, &a.arg(1), OptionsMode::Strict)?;
    read_locale_matcher(vm, &opts)?;
    let nu_opt = get_opt_str(vm, &opts, "numberingSystem", &[])?;
    if let Some(nu) = &nu_opt {
        if !is_unicode_type(nu) {
            return vm.throw_range(format!("invalid numberingSystem: {}", nu));
        }
    }
    let style =
        get_opt_str(vm, &opts, "style", &["long", "short", "narrow", "digital"])?.unwrap_or_else(|| "short".into());
    let mut unit_opts: Vec<(String, String)> = Vec::with_capacity(10);
    let mut prev_style = String::new();
    for (i, (unit, _)) in UNITS.iter().enumerate() {
        let styles: &[&str] = if i < IDX_HOURS {
            &["long", "short", "narrow"]
        } else if i < IDX_MS {
            &["long", "short", "narrow", "numeric", "2-digit"]
        } else {
            &["long", "short", "narrow", "numeric"]
        };
        let digital_base = if i < IDX_HOURS { "short" } else { "numeric" };
        let mut ustyle = get_opt_str(vm, &opts, unit, styles)?;
        let mut display_default = "always";
        let prev_numeric = prev_style == "numeric" || prev_style == "2-digit";
        if ustyle.is_none() {
            if style == "digital" {
                if !(IDX_HOURS..=IDX_SECONDS).contains(&i) {
                    display_default = "auto";
                }
                ustyle = Some(digital_base.to_string());
            } else if prev_numeric {
                display_default = "auto";
                ustyle = Some("numeric".to_string());
            } else {
                display_default = "auto";
                ustyle = Some(style.clone());
            }
        }
        let mut ustyle = ustyle.unwrap();
        if ustyle == "numeric" && i >= IDX_MS {
            display_default = "auto";
        }
        let display = get_opt_str(vm, &opts, &format!("{}Display", unit), &["auto", "always"])?
            .unwrap_or_else(|| display_default.to_string());
        if prev_numeric {
            if ustyle != "numeric" && ustyle != "2-digit" {
                return vm.throw_range(format!("{} style conflicts with a preceding numeric unit", unit));
            }
            if i == IDX_MINUTES || i == IDX_SECONDS {
                ustyle = "2-digit".to_string();
            }
        }
        prev_style = ustyle.clone();
        unit_opts.push((ustyle, display));
    }
    let fd_v = get_opt(vm, &opts, "fractionalDigits")?;
    let fractional_digits = if fd_v.is_undefined() {
        None
    } else {
        let n = vm.to_number(&fd_v)?;
        if !(0.0..=9.0).contains(&n) || n.fract() != 0.0 {
            return vm.throw_range("fractionalDigits out of range");
        }
        Some(n)
    };

    // locale + numbering system (relevant extension key: nu)
    let r = resolve_locale(&locales);
    let default_nu = super::numdata::num_locale(r.lang(), r.region()).default_nu;
    let ext_nu = r.keyword("nu").filter(|n| super::numdata::numbering_system_supported(n)).map(|s| s.to_string());
    let mut keep_nu = ext_nu.clone();
    let mut nu = ext_nu.clone().unwrap_or_else(|| default_nu.to_string());
    if let Some(n) = nu_opt.as_deref().filter(|n| super::numdata::numbering_system_supported(n)) {
        if Some(n) != ext_nu.as_deref() {
            keep_nu = None;
        }
        nu = n.to_string();
    }
    let locale = match &keep_nu {
        Some(n) => r.locale_with(&[("nu", n.as_str())]),
        None => r.base.clone(),
    };

    let o = alloc_instance(vm, a)?;
    set_slot(&o, "__df", Value::Bool(true));
    set_slot(&o, "__df_locale", Value::str(&locale));
    set_slot(&o, "__df_style", Value::str(&style));
    set_slot(&o, "__df_nu", Value::str(&nu));
    for ((unit, _), (s, d)) in UNITS.iter().zip(unit_opts.iter()) {
        set_slot(&o, &format!("__df_u_{}", unit), Value::str(s));
        set_slot(&o, &format!("__df_d_{}", unit), Value::str(d));
    }
    if let Some(fd) = fractional_digits {
        set_slot(&o, "__df_frac", Value::Num(fd));
    }
    Ok(Value::Obj(o))
}

fn df_resolved_options(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.this, "__df")?;
    let r = vm.new_object();
    let copy = |r: &Obj, key: &str, name: &str| {
        if let Some(v) = slot(&o, name) {
            if !v.is_undefined() {
                r.set_str(key, v, WEC);
            }
        }
    };
    copy(&r, "locale", "__df_locale");
    copy(&r, "numberingSystem", "__df_nu");
    copy(&r, "style", "__df_style");
    for (unit, _) in UNITS.iter() {
        copy(&r, unit, &format!("__df_u_{}", unit));
        copy(&r, &format!("{}Display", unit), &format!("__df_d_{}", unit));
    }
    copy(&r, "fractionalDigits", "__df_frac");
    Ok(Value::Obj(r))
}

// ============================================================================
// Duration records
// ============================================================================

/// The ten fields of a duration record (integral doubles).
type Record = [f64; 10];

const TWO_32: f64 = 4294967296.0;

/// ToDurationRecord (objects: read in unit order, ToNumber, must be
/// integral; strings: ISO 8601 durations, not range checked).
fn to_duration_record(vm: &mut Vm, v: &Value) -> JsResult<Record> {
    let o = match v {
        Value::Obj(o) => o.clone(),
        Value::Str(s) => {
            let st = s.to_rust_string();
            return match parse_iso_duration(&st) {
                Some(r) => Ok(r),
                None => vm.throw_range("invalid ISO 8601 duration string"),
            };
        }
        _ => return vm.throw_type("duration must be an object"),
    };
    let mut rec: Record = [0.0; 10];
    let mut any = false;
    for (i, (unit, _)) in UNITS.iter().enumerate() {
        let x = vm.get_str(&o, unit)?;
        if x.is_undefined() {
            continue;
        }
        let n = vm.to_number(&x)?;
        if !n.is_finite() || n.fract() != 0.0 {
            return vm.throw_range(format!("invalid duration field {}", unit));
        }
        rec[i] = n;
        any = true;
    }
    if !any {
        return vm.throw_type("duration has no recognized fields");
    }
    // IsValidDuration
    let mut sign = 0;
    for &x in rec.iter() {
        let s = if x < 0.0 {
            -1
        } else if x > 0.0 {
            1
        } else {
            0
        };
        if s != 0 {
            if sign != 0 && s != sign {
                return vm.throw_range("duration fields have mixed signs");
            }
            sign = s;
        }
    }
    if rec[0].abs() >= TWO_32 || rec[1].abs() >= TWO_32 || rec[2].abs() >= TWO_32 {
        return vm.throw_range("calendar unit out of range");
    }
    if !time_total_in_range(&rec) {
        return vm.throw_range("duration time total out of range");
    }
    Ok(rec)
}

/// |days*86400 + hours*3600 + minutes*60 + seconds + ms/1e3 + us/1e6 +
/// ns/1e9| < 2^53 (exact).
fn time_total_in_range(rec: &Record) -> bool {
    // all fields have the same sign: work with magnitudes in nanoseconds
    let limit: i128 = (1i128 << 53) * 1_000_000_000;
    let factors: [i128; 7] = [
        86_400_000_000_000,
        3_600_000_000_000,
        60_000_000_000,
        1_000_000_000,
        1_000_000,
        1_000,
        1,
    ];
    let mut total: i128 = 0;
    for (k, f) in factors.iter().enumerate() {
        let v = rec[3 + k].abs();
        if v >= 1e30 {
            return false;
        }
        let iv = v as i128;
        let c = match iv.checked_mul(*f) {
            Some(c) => c,
            None => return false,
        };
        total = match total.checked_add(c) {
            Some(t) => t,
            None => return false,
        };
        if total >= limit {
            return false;
        }
    }
    total < limit
}

/// ISO 8601 duration strings as accepted by the original: optional sign
/// (+, -, U+2212), "P", date designators Y M W D, optional "T" followed by
/// at least one of H M S; designators in any order, repeated ones overwrite,
/// case-insensitive; only seconds may have a fraction ("." or ",", digits
/// optional on either side).  No range checks.
fn parse_iso_duration(s: &str) -> Option<Record> {
    let chars: Vec<char> = s.chars().collect();
    let n = chars.len();
    let mut i = 0;
    let mut neg = false;
    if i < n && (chars[i] == '+' || chars[i] == '-' || chars[i] == '\u{2212}') {
        neg = chars[i] != '+';
        i += 1;
    }
    if i >= n || !(chars[i] == 'P' || chars[i] == 'p') {
        return None;
    }
    i += 1;
    let mut rec: Record = [0.0; 10];
    let mut in_time = false;
    let mut any = false;
    let mut time_any = false;
    while i < n {
        let c = chars[i];
        if c == 'T' || c == 't' {
            if in_time {
                return None;
            }
            in_time = true;
            i += 1;
            continue;
        }
        let st = i;
        while i < n && chars[i].is_ascii_digit() {
            i += 1;
        }
        let int_digits: String = chars[st..i].iter().collect();
        let mut frac_digits: Option<String> = None;
        if i < n && (chars[i] == '.' || chars[i] == ',') {
            i += 1;
            let fs = i;
            while i < n && chars[i].is_ascii_digit() {
                i += 1;
            }
            frac_digits = Some(chars[fs..i].iter().collect());
        }
        if int_digits.is_empty() && frac_digits.as_deref().map(|f| f.is_empty()).unwrap_or(true) {
            return None;
        }
        if i >= n {
            return None;
        }
        let d = chars[i].to_ascii_uppercase();
        i += 1;
        let idx = if !in_time {
            match d {
                'Y' => 0,
                'M' => 1,
                'W' => 2,
                'D' => 3,
                _ => return None,
            }
        } else {
            match d {
                'H' => 4,
                'M' => 5,
                'S' => 6,
                _ => return None,
            }
        };
        if frac_digits.is_some() && idx != 6 {
            return None;
        }
        any = true;
        if in_time {
            time_any = true;
        }
        if idx == 6 {
            let text = format!(
                "{}.{}",
                if int_digits.is_empty() { "0" } else { &int_digits },
                frac_digits.as_deref().unwrap_or("")
            );
            let v: f64 = text.trim_end_matches('.').parse().unwrap_or(0.0);
            let secs = v.trunc();
            let frac = v - secs;
            let nanos = (frac * 1e9 + 0.5).floor();
            rec[6] = secs;
            rec[7] = (nanos / 1e6).floor();
            rec[8] = ((nanos / 1e3).floor()) % 1000.0;
            rec[9] = nanos % 1000.0;
        } else {
            rec[idx] = int_digits.parse::<f64>().unwrap_or(0.0);
        }
    }
    if !any || (in_time && !time_any) {
        return None;
    }
    if neg {
        for x in rec.iter_mut() {
            *x = -*x;
        }
    }
    Some(rec)
}

fn duration_sign(rec: &Record) -> i32 {
    for &x in rec.iter() {
        if x < 0.0 {
            return -1;
        }
        if x > 0.0 {
            return 1;
        }
    }
    0
}

/// Exact |value| of unit `idx` plus all smaller subsecond units folded in as
/// fraction digits (idx: seconds, milliseconds or microseconds).
fn add_fractional(rec: &Record, idx: usize) -> Decimal {
    // value in units of 10^-9 of unit idx
    let mut total: i128 = 0;
    let mut scale: i128 = 1_000_000_000;
    for k in idx..10 {
        let v = rec[k].abs();
        let iv = if v >= 1e30 { 0 } else { v as i128 };
        total = total.saturating_add(iv.saturating_mul(scale));
        scale /= 1000;
        if scale == 0 {
            break;
        }
    }
    let s = total.to_string();
    Decimal::from_int_str(&s).shift(-9)
}

// ============================================================================
// Formatting
// ============================================================================

/// A formatted part with its (singular) unit.
type UPart = (Part, Option<&'static str>);

struct Ctx {
    locale: String,
    nu: String,
    frac: Option<u32>,
}

fn element_cfg(ctx: &Ctx) -> NfConfig {
    NfConfig::decimal(&ctx.locale, &ctx.nu)
}

fn value_of(neg: bool, d: Decimal) -> MathValue {
    MathValue::Finite(neg, d, Src::Number)
}

fn with_unit(parts: Vec<Part>, unit: &'static str) -> Vec<UPart> {
    parts.into_iter().map(|p| (p, Some(unit))).collect()
}

/// Resolve the numbering system the way `new Intl.NumberFormat(locale,
/// {numberingSystem})` would.
fn resolve_nu(vm: &mut Vm, locale: &str, nu: &str) -> JsResult<String> {
    if !is_unicode_type(nu) {
        return vm.throw_range(format!("invalid numberingSystem: {}", nu));
    }
    if super::numdata::numbering_system_supported(nu) {
        return Ok(nu.to_string());
    }
    let r = resolve_locale(&[locale.to_string()]);
    if let Some(k) = r.keyword("nu") {
        if super::numdata::numbering_system_supported(k) {
            return Ok(k.to_string());
        }
    }
    Ok(super::numdata::num_locale(r.lang(), r.region()).default_nu.to_string())
}

fn format_duration(vm: &mut Vm, o: &Obj, rec: &Record) -> JsResult<Vec<UPart>> {
    // the original builds NumberFormat(locale, {numberingSystem, ...})
    // objects here: the locale is canonicalised, then the numbering system
    // validated
    let locale = slot_str(o, "__df_locale").unwrap_or_default();
    let locale = match canonicalize_tag(&locale) {
        Some(c) => c,
        None => return vm.throw_range(format!("Incorrect locale information provided: {}", locale)),
    };
    let nu_slot = slot_str(o, "__df_nu").unwrap_or_default();
    let nu = resolve_nu(vm, &locale, &nu_slot)?;
    let frac = match slot(o, "__df_frac") {
        Some(Value::Num(n)) if n.is_finite() && (0.0..=9.0).contains(&n) => Some(n as u32),
        _ => None,
    };
    let ctx = Ctx { locale, nu, frac };
    let styles: Vec<String> =
        UNITS.iter().map(|(u, _)| slot_str(o, &format!("__df_u_{}", u)).unwrap_or_default()).collect();
    let displays: Vec<String> =
        UNITS.iter().map(|(u, _)| slot_str(o, &format!("__df_d_{}", u)).unwrap_or_default()).collect();
    let negative = duration_sign(rec) < 0;
    let mut sign_displayed = true;
    let mut elements: Vec<Vec<UPart>> = Vec::new();
    let is_numeric = |s: &str| s == "numeric" || s == "2-digit";
    // a unit followed by a "numeric" (fractional) unit absorbs the smaller
    // units as fraction digits and ends the list
    let folds = |k: usize| (IDX_SECONDS..=8).contains(&k) && styles[k + 1] == "numeric";
    let mut i = 0;
    while i < 10 {
        let style = styles[i].as_str();
        if is_numeric(style) {
            // a run of consecutive numeric / 2-digit units: one "h:mm:ss" element
            let mut end = i;
            while end < 9 && !folds(end) && is_numeric(&styles[end + 1]) {
                end += 1;
            }
            let parts =
                numeric_group(&ctx, rec, &styles, &displays, i, end, folds(end), negative, &mut sign_displayed);
            if !parts.is_empty() {
                elements.push(parts);
            }
            if folds(end) {
                break;
            }
            i = end + 1;
            continue;
        }
        // unit element (possibly absorbing smaller units)
        let folds = folds(i);
        let mag = if folds { add_fractional(rec, i) } else { Decimal::from_f64(rec[i]) };
        let display = displays[i].as_str();
        // (the unit's NumberFormat is created -- and its unitDisplay
        // validated -- whether or not the unit is displayed)
        if !["short", "narrow", "long"].contains(&style) {
            return vm.throw_range(format!("invalid unitDisplay: {}", style));
        }
        if display != "auto" || !mag.is_zero() {
            let mut cfg = element_cfg(&ctx);
            cfg.style = Style::Unit;
            cfg.unit = UNITS[i].1.to_string();
            cfg.unit_display = style.to_string();
            if folds {
                let (lo, hi) = match ctx.frac {
                    Some(f) => (f, f),
                    None => (0, 9),
                };
                cfg.min_frac = lo;
                cfg.max_frac = hi;
                cfg.rounding_type = RoundingType::Fraction;
                cfg.rounding_mode = RoundingMode::Trunc;
            }
            let neg = if sign_displayed {
                sign_displayed = false;
                negative
            } else {
                cfg.sign_display = SignDisplay::Never;
                false
            };
            let parts = format_parts(&cfg, &value_of(neg, mag));
            elements.push(with_unit(parts, UNITS[i].1));
        }
        if folds {
            break;
        }
        i += 1;
    }
    // list joining (Intl.ListFormat type "unit")
    let df_style = slot_str(o, "__df_style").unwrap_or_default();
    let list_style = if df_style == "digital" { "short".to_string() } else { df_style };
    if !["long", "short", "narrow"].contains(&list_style.as_str()) {
        return vm.throw_range(format!("invalid style: {}", list_style));
    }
    let (two, middle, last) = unit_list_joiners(&ctx.locale, &list_style);
    let n = elements.len();
    let mut out: Vec<UPart> = Vec::new();
    for (k, e) in elements.into_iter().enumerate() {
        if k > 0 {
            let sep = if n == 2 {
                two
            } else if k == n - 1 {
                last
            } else {
                middle
            };
            out.push((Part::new("literal", sep), None));
        }
        out.extend(e);
    }
    Ok(out)
}

/// The "h:mm:ss" element for the numeric units `first..=last` (the last one
/// absorbing the smaller units when `last_folds`).  A unit is shown when
/// non-zero or its display is not "auto"; minutes are forced between shown
/// hours and seconds; ":" separates the shown units.
#[allow(clippy::too_many_arguments)]
fn numeric_group(
    ctx: &Ctx,
    rec: &Record,
    styles: &[String],
    displays: &[String],
    first: usize,
    last: usize,
    last_folds: bool,
    negative: bool,
    sign_displayed: &mut bool,
) -> Vec<UPart> {
    let n = last - first + 1;
    let mut values: Vec<Decimal> = Vec::with_capacity(n);
    let mut shown: Vec<bool> = Vec::with_capacity(n);
    for k in first..=last {
        let v = if k == last && last_folds { add_fractional(rec, k) } else { Decimal::from_f64(rec[k]) };
        shown.push(!v.is_zero() || displays[k] != "auto");
        values.push(v);
    }
    // minutes are forced between shown hours and "formatted" seconds; the
    // seconds test counts the subsecond fields (and the seconds display)
    // even when the seconds are not part of this run
    if first <= IDX_HOURS && IDX_MINUTES <= last && shown[IDX_HOURS - first] {
        let seconds_formatted = rec[IDX_SECONDS..].iter().any(|&x| x != 0.0) || displays[IDX_SECONDS] != "auto";
        if seconds_formatted {
            shown[IDX_MINUTES - first] = true;
        }
    }
    let mut out: Vec<UPart> = Vec::new();
    let mut emitted = false;
    for (j, k) in (first..=last).enumerate() {
        if !shown[j] {
            continue;
        }
        if emitted {
            out.push((Part::new("literal", ":"), None));
        }
        emitted = true;
        let mut cfg = element_cfg(ctx);
        cfg.grouping = Grouping::Off;
        if styles[k] == "2-digit" {
            cfg.min_int = 2;
        }
        if k == last && last_folds {
            let (lo, hi) = match ctx.frac {
                Some(f) => (f, f),
                None => (0, 9),
            };
            cfg.min_frac = lo;
            cfg.max_frac = hi;
            cfg.rounding_type = RoundingType::Fraction;
            cfg.rounding_mode = RoundingMode::Trunc;
        }
        let neg = if *sign_displayed {
            *sign_displayed = false;
            negative
        } else {
            cfg.sign_display = SignDisplay::Never;
            false
        };
        let parts = format_parts(&cfg, &value_of(neg, values[j].clone()));
        out.extend(with_unit(parts, UNITS[k].1));
    }
    out
}

/// Joiners of the original's ListFormat for type "unit": (two items,
/// middle, last).  Only Spanish has its own data.
fn unit_list_joiners(locale: &str, style: &str) -> (&'static str, &'static str, &'static str) {
    let es = locale == "es" || locale.starts_with("es-");
    if es {
        return match style {
            "long" => (" y ", ", ", " y "),
            "short" => (" y ", ", ", ", "),
            _ => (" ", " ", " "),
        };
    }
    match style {
        "narrow" => (" ", " ", " "),
        _ => (", ", ", ", ", "),
    }
}

// ============================================================================
// Methods
// ============================================================================

fn df_format(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.this, "__df")?;
    let rec = to_duration_record(vm, &a.arg(0))?;
    let parts = format_duration(vm, &o, &rec)?;
    let s: String = parts.iter().map(|(p, _)| p.value.as_str()).collect();
    Ok(Value::str(&s))
}

fn df_format_to_parts(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.this, "__df")?;
    let rec = to_duration_record(vm, &a.arg(0))?;
    let parts = format_duration(vm, &o, &rec)?;
    let mut out = Vec::with_capacity(parts.len());
    for (p, unit) in parts {
        let po = vm.new_object();
        po.set_str("type", Value::str(p.kind), WEC);
        po.set_str("value", Value::str(&p.value), WEC);
        if let Some(u) = unit {
            po.set_str("unit", Value::str(u), WEC);
        }
        out.push(Value::Obj(po));
    }
    Ok(Value::Obj(vm.new_array(out)))
}
