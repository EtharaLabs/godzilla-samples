//! Intl.NumberFormat (and Number/BigInt.prototype.toLocaleString).
//!
//! Internal slots (own data properties, in this order): `__nf: true`,
//! `__nf_locale`, `__nf_nu`, `__nf_roundingincrement`,
//! `__nf_roundingpriority`, `__nf_trailingzero`, `__nf_style`, then for
//! currency `__nf_currency`, `__nf_currencydisplay`, `__nf_currencysign`,
//! when a unit was given `__nf_unit`, `__nf_unitdisplay`, then
//! `__nf_minint`, `__nf_minfrac`, `__nf_maxfrac`, [`__nf_minsig`,
//! `__nf_maxsig`], `__nf_notation`, `__nf_compactdisplay`, `__nf_grouping`,
//! `__nf_signdisplay`, `__nf_roundingmode`, `__nf_roundingtype`; the bound
//! `format` is cached in `__nf_boundformat`.
//!
//! Formatting follows ECMA-402 (exact decimal rounding of the shortest
//! round-trip digits, strings and BigInts exactly) with the original's data
//! (see numdata.rs) and quirks:
//! * compact notation ignores fraction-digit settings (2 significant digits,
//!   morePrecision) and never re-buckets (999999 -> "1000K");
//! * scientific/engineering take the exponent of the unrounded value
//!   ("10E0" for 9.9999), zero has no exponent, exponent digits are ASCII;
//! * formatToParts tokenizes the formatted string: any "E" starts the
//!   exponent (currency codes like EUR!), text before the number is the
//!   currency, text after it is split into leading spaces (literal) and the
//!   rest (currency / compact), percent suffixes are one percentSign part
//!   and text after the exponent belongs to exponentInteger.

use super::decimal::{Decimal, RoundingMode};
use super::numdata::{self, NumLocale};
use super::*;
use std::cell::RefCell;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    let (c, _) = define_class(
        vm,
        intl,
        "NumberFormat",
        0,
        nf_ctor,
        &[
            Member::Getter("format", nf_format_getter),
            Member::Method("formatToParts", 1, nf_format_to_parts),
            Member::Method("resolvedOptions", 0, nf_resolved_options),
            Member::Method("formatRange", 2, nf_format_range),
            Member::Method("formatRangeToParts", 2, nf_format_range_to_parts),
        ],
        true,
    );
    NF_CTOR.with(|s| *s.borrow_mut() = Some(c));
}

thread_local! {
    static NF_CTOR: RefCell<Option<Obj>> = RefCell::new(None);
}

fn nf_ctor_obj() -> Obj {
    NF_CTOR.with(|s| s.borrow().clone().unwrap())
}

// ============================================================================
// Configuration
// ============================================================================

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Style {
    Decimal,
    Percent,
    Currency,
    Unit,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Notation {
    Standard,
    Scientific,
    Engineering,
    Compact,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RoundingType {
    Fraction,
    Significant,
    MorePrecision,
    LessPrecision,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Grouping {
    Auto,
    Always,
    Min2,
    Off,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SignDisplay {
    Auto,
    Always,
    Never,
    ExceptZero,
    Negative,
}

/// Resolved formatter configuration (read back from the slots).
#[derive(Clone, Debug)]
pub struct NfConfig {
    pub lang: String,
    pub region: Option<String>,
    pub nu: String,
    pub style: Style,
    pub currency: String,
    pub currency_display: String,
    pub currency_sign_accounting: bool,
    pub unit: String,
    pub unit_display: String,
    pub min_int: u32,
    pub min_frac: u32,
    pub max_frac: u32,
    pub min_sig: u32,
    pub max_sig: u32,
    pub rounding_type: RoundingType,
    pub rounding_increment: u32,
    pub rounding_mode: RoundingMode,
    pub strip_if_integer: bool,
    pub notation: Notation,
    pub compact_long: bool,
    pub grouping: Grouping,
    pub sign_display: SignDisplay,
}

impl NfConfig {
    /// A default decimal formatter for a locale tag and numbering system.
    pub fn decimal(locale: &str, nu: &str) -> NfConfig {
        let (lang, region) = match parse_tag(locale) {
            Some(t) => (t.language.clone(), t.region.clone()),
            None => ("en".to_string(), None),
        };
        NfConfig {
            lang,
            region,
            nu: nu.to_string(),
            style: Style::Decimal,
            currency: String::new(),
            currency_display: "symbol".into(),
            currency_sign_accounting: false,
            unit: String::new(),
            unit_display: "short".into(),
            min_int: 1,
            min_frac: 0,
            max_frac: 3,
            min_sig: 1,
            max_sig: 21,
            rounding_type: RoundingType::Fraction,
            rounding_increment: 1,
            rounding_mode: RoundingMode::HalfExpand,
            strip_if_integer: false,
            notation: Notation::Standard,
            compact_long: false,
            grouping: Grouping::Auto,
            sign_display: SignDisplay::Auto,
        }
    }

    pub fn num_locale(&self) -> NumLocale {
        numdata::num_locale(&self.lang, self.region.as_deref())
    }

    /// Read the configuration from the `__nf_*` slots.
    pub fn from_slots(o: &Obj) -> NfConfig {
        let locale = slot_str(o, "__nf_locale").unwrap_or_else(|| "en".to_string());
        let nu = slot_str(o, "__nf_nu").unwrap_or_else(|| "latn".to_string());
        let mut c = NfConfig::decimal(&locale, &nu);
        let s = |n: &str| slot_str(o, n);
        let num = |n: &str, d: u32| slot_num(o, n).map(|x| if x.is_finite() && x >= 0.0 { x as u32 } else { d }).unwrap_or(d);
        c.style = match s("__nf_style").as_deref() {
            Some("percent") => Style::Percent,
            Some("currency") => Style::Currency,
            Some("unit") => Style::Unit,
            _ => Style::Decimal,
        };
        c.currency = s("__nf_currency").unwrap_or_default();
        c.currency_display = s("__nf_currencydisplay").unwrap_or_else(|| "symbol".into());
        c.currency_sign_accounting = s("__nf_currencysign").as_deref() == Some("accounting");
        c.unit = s("__nf_unit").unwrap_or_default();
        c.unit_display = s("__nf_unitdisplay").unwrap_or_else(|| "short".into());
        c.min_int = num("__nf_minint", 1);
        c.min_frac = num("__nf_minfrac", 0);
        c.max_frac = num("__nf_maxfrac", 0);
        c.min_sig = num("__nf_minsig", 1);
        c.max_sig = num("__nf_maxsig", 21);
        c.rounding_type = match s("__nf_roundingtype").as_deref() {
            Some("significant") => RoundingType::Significant,
            Some("morePrecision") => RoundingType::MorePrecision,
            Some("lessPrecision") => RoundingType::LessPrecision,
            _ => RoundingType::Fraction,
        };
        c.rounding_increment = num("__nf_roundingincrement", 1).max(1);
        c.rounding_mode = s("__nf_roundingmode").and_then(|m| RoundingMode::parse(&m)).unwrap_or(RoundingMode::HalfExpand);
        c.strip_if_integer = s("__nf_trailingzero").as_deref() == Some("stripIfInteger");
        c.notation = match s("__nf_notation").as_deref() {
            Some("scientific") => Notation::Scientific,
            Some("engineering") => Notation::Engineering,
            Some("compact") => Notation::Compact,
            _ => Notation::Standard,
        };
        c.compact_long = s("__nf_compactdisplay").as_deref() == Some("long");
        c.grouping = match slot(o, "__nf_grouping") {
            Some(Value::Str(g)) => match g.to_rust_string().as_str() {
                "always" => Grouping::Always,
                "min2" => Grouping::Min2,
                _ => Grouping::Auto,
            },
            Some(Value::Bool(false)) => Grouping::Off,
            Some(v) if !v.truthy() => Grouping::Off,
            _ => Grouping::Auto,
        };
        c.sign_display = match s("__nf_signdisplay").as_deref() {
            Some("always") => SignDisplay::Always,
            Some("never") => SignDisplay::Never,
            Some("exceptZero") => SignDisplay::ExceptZero,
            Some("negative") => SignDisplay::Negative,
            _ => SignDisplay::Auto,
        };
        c
    }
}

// ============================================================================
// Values
// ============================================================================

/// An Intl mathematical value.
#[derive(Clone, Debug)]
pub enum MathValue {
    NaN,
    Inf(bool),
    /// (negative, |value|, source); negative zero is (true, 0, _)
    Finite(bool, Decimal, Src),
}

/// Where a finite value came from: the original keeps BigInts and numeric
/// strings exact only on some rounding paths.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Src {
    Number,
    BigInt,
    String,
}

impl MathValue {
    pub fn from_f64(x: f64) -> MathValue {
        if x.is_nan() {
            MathValue::NaN
        } else if x.is_infinite() {
            MathValue::Inf(x < 0.0)
        } else {
            MathValue::Finite(x.is_sign_negative(), Decimal::from_f64(x), Src::Number)
        }
    }

    pub fn is_nan(&self) -> bool {
        matches!(self, MathValue::NaN)
    }

    fn to_f64(&self) -> f64 {
        match self {
            MathValue::NaN => f64::NAN,
            MathValue::Inf(n) => {
                if *n {
                    f64::NEG_INFINITY
                } else {
                    f64::INFINITY
                }
            }
            MathValue::Finite(n, d, _) => {
                let v = d.to_f64();
                if *n {
                    -v
                } else {
                    v
                }
            }
        }
    }
}

/// ToIntlMathematicalValue.
pub fn to_math_value(vm: &mut Vm, v: &Value) -> JsResult<MathValue> {
    let p = match v {
        Value::Obj(_) => vm.to_primitive(v, crate::ops::Hint::Number)?,
        other => other.clone(),
    };
    match &p {
        Value::BigInt(b) => {
            let s = b.to_string_radix(10);
            let neg = s.starts_with('-');
            Ok(MathValue::Finite(neg, Decimal::from_int_str(s.trim_start_matches('-')), Src::BigInt))
        }
        Value::Str(s) => {
            let st = s.to_rust_string();
            match Decimal::parse_numeric_string(&st) {
                Ok((neg, d)) => Ok(MathValue::Finite(neg, d, Src::String)),
                Err(Some(neg)) => Ok(MathValue::Inf(neg)),
                Err(None) => Ok(MathValue::NaN),
            }
        }
        _ => {
            let n = vm.to_number(&p)?;
            Ok(MathValue::from_f64(n))
        }
    }
}

// ============================================================================
// Formatting core
// ============================================================================

/// Result of rounding: the value and the number of fraction digits shown.
struct Rounded {
    value: Decimal,
    frac_digits: u32,
}

fn round_fraction(x: &Decimal, min_frac: u32, max_frac: u32, inc: u32, mode: RoundingMode, neg: bool) -> Rounded {
    let v = if inc > 1 {
        x.round_increment(max_frac as i32, inc, mode, neg)
    } else {
        x.round_frac(max_frac as i32, mode, neg)
    };
    let fd = (v.frac_len().max(0) as u32).max(min_frac);
    Rounded { value: v, frac_digits: fd }
}

fn round_significant(x: &Decimal, min_sig: u32, max_sig: u32, mode: RoundingMode, neg: bool) -> Rounded {
    let v = x.round_sig(max_sig as i32, mode, neg);
    // fraction digits needed for min_sig significant digits
    let mag = if v.is_zero() { 1 } else { v.point };
    let need = min_sig as i32 - mag;
    let fd = (v.frac_len()).max(need).max(0) as u32;
    Rounded { value: v, frac_digits: fd }
}

/// Rounding magnitude (power of ten of the last kept digit).
fn sig_magnitude(x: &Decimal, max_sig: u32, mode: RoundingMode, neg: bool) -> i32 {
    let v = x.round_sig(max_sig as i32, mode, neg);
    let p = if v.is_zero() { if x.is_zero() { 1 } else { x.point } } else { v.point };
    p - max_sig as i32
}

fn apply_rounding(cfg: &NfConfig, x: &Decimal, neg: bool, compact: bool) -> Rounded {
    let mode = cfg.rounding_mode;
    // compact notation replaces fraction rounding by its defaults (and the
    // rounding mode by halfExpand)
    let compact_reset = compact && cfg.rounding_type == RoundingType::Fraction;
    let (rt, min_frac, max_frac, min_sig, max_sig) = if compact_reset {
        (RoundingType::MorePrecision, 0, 0, 1, 2)
    } else {
        (cfg.rounding_type, cfg.min_frac, cfg.max_frac, cfg.min_sig, cfg.max_sig)
    };
    let mode = if compact_reset { RoundingMode::HalfExpand } else { mode };
    let r = match rt {
        RoundingType::Fraction => round_fraction(x, min_frac, max_frac, cfg.rounding_increment, mode, neg),
        RoundingType::Significant => round_significant(x, min_sig, max_sig, mode, neg),
        RoundingType::MorePrecision | RoundingType::LessPrecision => {
            let smag = sig_magnitude(x, max_sig, mode, neg);
            let fmag = -(max_frac as i32);
            let pick_sig = if rt == RoundingType::MorePrecision { smag <= fmag } else { smag > fmag };
            if pick_sig {
                round_significant(x, min_sig, max_sig, mode, neg)
            } else {
                round_fraction(x, min_frac, max_frac, 1, mode, neg)
            }
        }
    };
    // trailingZeroDisplay "stripIfInteger" is accepted but has no effect in
    // the original
    let _ = cfg.strip_if_integer;
    r
}

/// Group an integer digit string.
fn group_int(s: &str, loc: &NumLocale, grouping: Grouping) -> String {
    let n = s.len();
    let use_group = match grouping {
        Grouping::Off => false,
        Grouping::Min2 => n >= 5,
        _ => true,
    };
    if !use_group || n <= 3 {
        return s.to_string();
    }
    let mut out = String::new();
    if loc.indian {
        let (head, tail) = s.split_at(n - 3);
        let hn = head.len();
        for (i, c) in head.chars().enumerate() {
            if i > 0 && (hn - i) % 2 == 0 {
                out.push_str(loc.group);
            }
            out.push(c);
        }
        out.push_str(loc.group);
        out.push_str(tail);
    } else {
        for (i, c) in s.chars().enumerate() {
            if i > 0 && (n - i) % 3 == 0 {
                out.push_str(loc.group);
            }
            out.push(c);
        }
    }
    out
}

/// The number body (digits with separators, optional exponent) of a
/// rounded value.
fn digits_string(cfg: &NfConfig, loc: &NumLocale, r: &Rounded) -> String {
    let mut int_s = r.value.int_string();
    while (int_s.len() as u32) < cfg.min_int {
        int_s.insert(0, '0');
    }
    let mut frac = r.value.frac_string();
    while (frac.len() as u32) < r.frac_digits {
        frac.push('0');
    }
    frac.truncate(r.frac_digits.max(r.value.frac_len() as u32) as usize);
    let mut s = group_int(&int_s, loc, cfg.grouping);
    if !frac.is_empty() {
        s.push_str(loc.decimal);
        s.push_str(&frac);
    }
    s
}

/// Sign shown for a value (after rounding).
fn sign_for(cfg: &NfConfig, neg: bool, is_zero: bool, is_nan: bool) -> &'static str {
    match cfg.sign_display {
        SignDisplay::Auto => {
            if neg {
                "-"
            } else {
                ""
            }
        }
        SignDisplay::Always => {
            if neg {
                "-"
            } else {
                "+"
            }
        }
        SignDisplay::Never => "",
        SignDisplay::ExceptZero => {
            if is_zero || is_nan {
                ""
            } else if neg {
                "-"
            } else {
                "+"
            }
        }
        SignDisplay::Negative => {
            if neg && !is_zero {
                "-"
            } else {
                ""
            }
        }
    }
}

/// Number portion of a formatted value: (sign, body, compact suffix,
/// plural operand for unit patterns, has exponent).
struct NumberPortion {
    sign: &'static str,
    body: String,
    compact_suffix: &'static str,
    operand: Option<Decimal>,
    exponent: bool,
}

fn number_portion(cfg: &NfConfig, loc: &NumLocale, v: &MathValue) -> NumberPortion {
    match v {
        MathValue::NaN => NumberPortion {
            sign: sign_for(cfg, false, false, true),
            body: loc.nan.to_string(),
            compact_suffix: "",
            operand: None,
            exponent: false,
        },
        MathValue::Inf(neg) => NumberPortion {
            sign: sign_for(cfg, *neg, false, false),
            body: "∞".to_string(),
            compact_suffix: "",
            operand: None,
            exponent: false,
        },
        MathValue::Finite(neg, d, src) => {
            let mut x = d.clone();
            // exactness: fraction rounding (without increment) keeps strings
            // and BigInts exact, significant rounding keeps BigInts exact;
            // every other path works on the double value
            let exact = match cfg.rounding_type {
                RoundingType::Fraction => cfg.rounding_increment <= 1,
                RoundingType::Significant => *src == Src::BigInt,
                _ => false,
            };
            if *src != Src::Number && !exact {
                x = Decimal::from_f64(d.to_f64());
            }
            if cfg.style == Style::Percent {
                // the original multiplies a double by 100
                x = Decimal::from_f64(d.to_f64() * 100.0);
            }
            match cfg.notation {
                Notation::Scientific | Notation::Engineering if !x.is_zero() => {
                    let mut e = x.magnitude();
                    if cfg.notation == Notation::Engineering {
                        e = e.div_euclid(3) * 3;
                    }
                    // the original divides a double by 10^e
                    let m = Decimal::from_f64(x.to_f64() / 10f64.powi(e));
                    let r = apply_rounding(cfg, &m, *neg, false);
                    let mut sci_cfg = cfg.clone();
                    sci_cfg.grouping = Grouping::Off;
                    let mut body = digits_string(&sci_cfg, loc, &r);
                    body.push('E');
                    if e < 0 {
                        body.push('-');
                    }
                    body.push_str(&e.abs().to_string());
                    NumberPortion {
                        sign: sign_for(cfg, *neg, r.value.is_zero(), false),
                        body,
                        compact_suffix: "",
                        operand: Some(m),
                        exponent: true,
                    }
                }
                Notation::Compact => {
                    let table = if cfg.compact_long { loc.compact_long } else { loc.compact_short };
                    let mut suffix = "";
                    let mut scaled = x.clone();
                    if !x.is_zero() {
                        let mag = x.magnitude();
                        if let Some((p, s)) = table.iter().rev().find(|(p, _)| *p <= mag) {
                            suffix = s;
                            // the original divides a double here
                            scaled = Decimal::from_f64(x.to_f64() / 10f64.powi(*p));
                        }
                    }
                    let r = apply_rounding(cfg, &scaled, *neg, true);
                    let mut ccfg = cfg.clone();
                    if cfg.rounding_type == RoundingType::Fraction {
                        ccfg.min_int = 1;
                    }
                    let body = digits_string(&ccfg, loc, &r);
                    NumberPortion {
                        sign: sign_for(cfg, *neg, r.value.is_zero(), false),
                        body,
                        compact_suffix: suffix,
                        operand: Some(scaled),
                        exponent: false,
                    }
                }
                _ => {
                    let r = apply_rounding(cfg, &x, *neg, false);
                    let body = digits_string(cfg, loc, &r);
                    NumberPortion {
                        sign: sign_for(cfg, *neg, r.value.is_zero(), false),
                        body,
                        compact_suffix: "",
                        operand: Some(x),
                        exponent: false,
                    }
                }
            }
        }
    }
}

/// Format to parts (formatToParts transliterates only integer and fraction
/// digits; the exponent stays ASCII).
pub fn format_parts(cfg: &NfConfig, v: &MathValue) -> Vec<Part> {
    let mut parts = format_parts_ascii(cfg, v);
    if cfg.nu != "latn" {
        for p in parts.iter_mut() {
            if p.kind == "integer" || p.kind == "fraction" {
                p.value = numdata::transliterate(&p.value, &cfg.nu);
            }
        }
    }
    parts
}

/// Parts with ASCII digits.
fn format_parts_ascii(cfg: &NfConfig, v: &MathValue) -> Vec<Part> {
    let loc = cfg.num_locale();
    let np = number_portion(cfg, &loc, v);
    let neg_shown = np.sign == "-";
    match cfg.style {
        Style::Unit => {
            let one = match &np.operand {
                Some(d) => super::pluralrules::plural_category_dec(&cfg.lang, d) == "one",
                None => false,
            };
            let (pat, is_data) = numdata::unit_pattern(&loc, &cfg.unit, &cfg.unit_display, one);
            let num_str = format!("{}{}{}", np.sign, np.body, np.compact_suffix);
            if !is_data {
                // generic patterns: the whole string is tokenized
                let full = pat.replacen("{0}", &num_str, 1);
                return tokenize(&full, TokStyle::UnitFallback, &loc);
            }
            let num_parts = tokenize(&num_str, TokStyle::Unit, &loc);
            match pat.find("{0}") {
                Some(i) => {
                    let mut out = Vec::new();
                    let prefix = &pat[..i];
                    let suffix = &pat[i + 3..];
                    if !prefix.is_empty() {
                        let t = prefix.trim_end_matches(|c| c == ' ' || c == '\u{a0}');
                        if !t.is_empty() {
                            out.push(Part::new("unit", t));
                        }
                        if t.len() < prefix.len() {
                            out.push(Part::new("literal", &prefix[t.len()..]));
                        }
                    }
                    out.extend(num_parts);
                    if !suffix.is_empty() {
                        let t = suffix.trim_start_matches(|c| c == ' ' || c == '\u{a0}');
                        if t.len() < suffix.len() {
                            out.push(Part::new("literal", &suffix[..suffix.len() - t.len()]));
                        }
                        if !t.is_empty() {
                            out.push(Part::new("unit", t));
                        }
                    }
                    out
                }
                None => tokenize(&pat, TokStyle::Currency, &loc),
            }
        }
        _ => {
            let s = match cfg.style {
                Style::Percent => format!("{}{}{}{}", np.sign, np.body, np.compact_suffix, loc.percent_suffix),
                Style::Currency => {
                    let sym = numdata::currency_symbol(&cfg.currency, &cfg.currency_display, &loc);
                    if loc.currency_suffix {
                        format!("{}{}{}\u{a0}{}", np.sign, np.body, np.compact_suffix, sym)
                    } else if cfg.currency_sign_accounting && neg_shown {
                        format!("({}{}{})", sym, np.body, np.compact_suffix)
                    } else {
                        format!("{}{}{}{}", np.sign, sym, np.body, np.compact_suffix)
                    }
                }
                _ => format!("{}{}{}", np.sign, np.body, np.compact_suffix),
            };
            let ts = match cfg.style {
                Style::Percent => TokStyle::Percent,
                Style::Currency => TokStyle::Currency,
                _ => TokStyle::Decimal,
            };
            let _ = np.exponent;
            tokenize(&s, ts, &loc)
        }
    }
}

/// format(): every ASCII digit of the result is transliterated.
pub fn format_string(cfg: &NfConfig, v: &MathValue) -> String {
    numdata::transliterate(&join_parts(&format_parts_ascii(cfg, v)), &cfg.nu)
}

// ============================================================================
// Parts tokenizer
// ============================================================================

#[derive(Clone, Copy, PartialEq, Eq)]
enum TokStyle {
    Decimal,
    Percent,
    Currency,
    Unit,
    UnitFallback,
}

fn is_ws(c: char) -> bool {
    c == ' ' || c == '\u{a0}'
}

fn tokenize(s: &str, style: TokStyle, loc: &NumLocale) -> Vec<Part> {
    let chars: Vec<char> = s.chars().collect();
    let n = chars.len();
    let nan: Vec<char> = loc.nan.chars().collect();
    let group: Vec<char> = loc.group.chars().collect();
    let decimal: Vec<char> = loc.decimal.chars().collect();
    let starts_with = |i: usize, pat: &[char]| -> bool { !pat.is_empty() && i + pat.len() <= n && chars[i..i + pat.len()] == *pat };
    let mut parts: Vec<Part> = Vec::new();
    let mut seen_number = false;
    let mut after_decimal = false;
    let mut i = 0;
    while i < n {
        let c = chars[i];
        if c == 'E' {
            parts.push(Part::new("exponentSeparator", "E"));
            i += 1;
            if i < n && chars[i] == '-' {
                parts.push(Part::new("exponentMinusSign", "-"));
                i += 1;
            }
            if i < n {
                let rest: String = chars[i..].iter().collect();
                parts.push(Part::new("exponentInteger", rest));
            }
            break;
        }
        if c == '-' && !seen_number {
            parts.push(Part::new("minusSign", "-"));
            i += 1;
            continue;
        }
        if c == '+' && !seen_number {
            parts.push(Part::new("plusSign", "+"));
            i += 1;
            continue;
        }
        if numdata::is_any_digit(c) {
            let st = i;
            while i < n && numdata::is_any_digit(chars[i]) {
                i += 1;
            }
            let v: String = chars[st..i].iter().collect();
            parts.push(Part::new(if after_decimal { "fraction" } else { "integer" }, v));
            seen_number = true;
            continue;
        }
        if seen_number && !after_decimal && i > 0 && numdata::is_any_digit(chars[i - 1]) {
            if starts_with(i, &decimal) && i + decimal.len() < n && numdata::is_any_digit(chars[i + decimal.len()]) {
                parts.push(Part::new("decimal", loc.decimal));
                i += decimal.len();
                after_decimal = true;
                continue;
            }
            if starts_with(i, &group) {
                parts.push(Part::new("group", loc.group));
                i += group.len();
                continue;
            }
        }
        if starts_with(i, &nan) {
            parts.push(Part::new("nan", loc.nan));
            i += nan.len();
            seen_number = true;
            continue;
        }
        if c == '∞' {
            parts.push(Part::new("infinity", "∞"));
            i += 1;
            seen_number = true;
            continue;
        }
        if c == '(' || c == ')' {
            parts.push(Part::new("literal", c.to_string()));
            i += 1;
            continue;
        }
        // text run
        let st = i;
        while i < n {
            let ch = chars[i];
            if ch == 'E'
                || ((ch == '-' || ch == '+') && !seen_number)
                || ch == '('
                || ch == ')'
                || ch == '∞'
                || numdata::is_any_digit(ch)
                || starts_with(i, &nan)
            {
                break;
            }
            i += 1;
        }
        let text: String = chars[st..i].iter().collect();
        match style {
            TokStyle::Percent => parts.push(Part::new("percentSign", text)),
            TokStyle::Unit => parts.push(Part::new("literal", text)),
            TokStyle::Currency | TokStyle::Decimal | TokStyle::UnitFallback => {
                let kind = match style {
                    TokStyle::Currency => "currency",
                    TokStyle::UnitFallback => "unit",
                    _ => "compact",
                };
                if !seen_number {
                    parts.push(Part::new(if style == TokStyle::Currency { "currency" } else { "literal" }, text));
                } else {
                    let t = text.trim_start_matches(is_ws);
                    if t.len() < text.len() {
                        parts.push(Part::new("literal", &text[..text.len() - t.len()]));
                    }
                    if !t.is_empty() {
                        // the text may itself contain an "E": continue scanning there
                        parts.push(Part::new(kind, t));
                    }
                }
            }
        }
    }
    parts
}

// ============================================================================
// Constructor / options
// ============================================================================

const ROUNDING_INCREMENTS: [u32; 15] = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000];

/// GetNumberOption with the original's messages ("<name> is NaN",
/// "<name> out of range").
fn nf_number_option(vm: &mut Vm, v: &Value, name: &str, min: f64, max: f64) -> JsResult<Option<f64>> {
    if v.is_undefined() {
        return Ok(None);
    }
    let n = vm.to_number(v)?;
    if n.is_nan() {
        return vm.throw_range(format!("{} is NaN", name));
    }
    if n < min || n > max {
        return vm.throw_range(format!("{} out of range", name));
    }
    Ok(Some(n.floor()))
}

fn nf_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let locales = locale_list(vm, &a.arg(0))?;
    let opts = get_options(vm, &a.arg(1), OptionsMode::Coerce)?;
    let o = alloc_instance(vm, a)?;
    init_number_format(vm, &o, &locales, &opts)?;
    let c = nf_ctor_obj();
    super::datetimeformat::legacy_construct(vm, a, &c, o)
}

/// InitializeNumberFormat: validate the options and write the slots.
pub fn init_number_format(vm: &mut Vm, o: &Obj, locales: &[String], opts: &Option<Obj>) -> JsResult<()> {
    read_locale_matcher(vm, opts)?;
    let nu_opt = get_opt_str(vm, opts, "numberingSystem", &[])?;
    if let Some(nu) = &nu_opt {
        if !is_unicode_type(nu) {
            return vm.throw_range(format!("invalid numberingSystem: {}", nu));
        }
    }
    let style = get_opt_str(vm, opts, "style", &["decimal", "percent", "currency", "unit"])?
        .unwrap_or_else(|| "decimal".into());
    let currency = get_opt_str(vm, opts, "currency", &[])?;
    let currency = match currency {
        None => {
            if style == "currency" {
                return vm.throw_type("currency is required for currency style");
            }
            None
        }
        Some(c) => {
            if !(c.len() == 3 && c.bytes().all(|b| b.is_ascii_alphabetic())) {
                return vm.throw_range(format!("invalid currency: {}", c));
            }
            Some(c.to_ascii_uppercase())
        }
    };
    let currency_display = get_opt_str(vm, opts, "currencyDisplay", &["code", "symbol", "narrowSymbol", "name"])?
        .unwrap_or_else(|| "symbol".into());
    let currency_sign =
        get_opt_str(vm, opts, "currencySign", &["standard", "accounting"])?.unwrap_or_else(|| "standard".into());
    let unit = get_opt_str(vm, opts, "unit", &[])?;
    let unit = match unit {
        None => {
            if style == "unit" {
                return vm.throw_type("unit is required for unit style");
            }
            None
        }
        Some(u) => {
            if !numdata::is_well_formed_unit(&u) {
                return vm.throw_range(format!("invalid unit: {}", u));
            }
            Some(u)
        }
    };
    let unit_display =
        get_opt_str(vm, opts, "unitDisplay", &["short", "narrow", "long"])?.unwrap_or_else(|| "short".into());
    let notation = get_opt_str(vm, opts, "notation", &["standard", "scientific", "engineering", "compact"])?
        .unwrap_or_else(|| "standard".into());
    // digit options
    let mnid_v = get_opt(vm, opts, "minimumIntegerDigits")?;
    let mnid = nf_number_option(vm, &mnid_v, "minimumIntegerDigits", 1.0, 21.0)?.unwrap_or(1.0);
    let mnfd_v = get_opt(vm, opts, "minimumFractionDigits")?;
    let mnfd = nf_number_option(vm, &mnfd_v, "minimumFractionDigits", 0.0, 100.0)?;
    let mxfd_v = get_opt(vm, opts, "maximumFractionDigits")?;
    let mxfd = nf_number_option(vm, &mxfd_v, "maximumFractionDigits", 0.0, 100.0)?;
    let mnsd_v = get_opt(vm, opts, "minimumSignificantDigits")?;
    let mnsd = nf_number_option(vm, &mnsd_v, "minimumSignificantDigits", 1.0, 21.0)?;
    let mxsd_v = get_opt(vm, opts, "maximumSignificantDigits")?;
    let mxsd = nf_number_option(vm, &mxsd_v, "maximumSignificantDigits", 1.0, 21.0)?;
    let ri_v = get_opt(vm, opts, "roundingIncrement")?;
    let rounding_increment = if ri_v.is_undefined() {
        1
    } else {
        let n = vm.to_number(&ri_v)?;
        if !(n >= 1.0 && n <= 5000.0) || n.fract() != 0.0 || !ROUNDING_INCREMENTS.contains(&(n as u32)) {
            return vm.throw_range("invalid roundingIncrement");
        }
        n as u32
    };
    let rounding_mode = get_opt_str(
        vm,
        opts,
        "roundingMode",
        &["ceil", "floor", "expand", "trunc", "halfCeil", "halfFloor", "halfExpand", "halfTrunc", "halfEven"],
    )?
    .unwrap_or_else(|| "halfExpand".into());
    let rounding_priority = get_opt_str(vm, opts, "roundingPriority", &["auto", "morePrecision", "lessPrecision"])?
        .unwrap_or_else(|| "auto".into());
    // SetNumberFormatDigitOptions
    let (mnfd_default, mut mxfd_default) = if style == "currency" && notation == "standard" {
        let d = numdata::currency_digits(currency.as_deref().unwrap_or("")) as f64;
        (d, d)
    } else {
        (0.0, if style == "percent" { 0.0 } else { 3.0 })
    };
    if rounding_increment != 1 {
        mxfd_default = mnfd_default;
    }
    let has_sd = mnsd.is_some() || mxsd.is_some();
    let has_fd = mnfd.is_some() || mxfd.is_some();
    let mut need_sd = true;
    let mut need_fd = true;
    if rounding_priority == "auto" {
        need_sd = has_sd;
        if need_sd || (!has_fd && notation == "compact") {
            need_fd = false;
        }
    }
    let mut min_sig = None;
    let mut max_sig = None;
    if need_sd {
        if has_sd {
            let lo = mnsd.unwrap_or(1.0);
            let hi = mxsd.unwrap_or(21.0);
            if lo > hi {
                return vm.throw_range("minimumSignificantDigits > maximumSignificantDigits");
            }
            min_sig = Some(lo);
            max_sig = Some(hi);
        } else {
            min_sig = Some(1.0);
            max_sig = Some(21.0);
        }
    }
    let mut min_frac = 0.0;
    let mut max_frac = 0.0;
    if need_fd {
        if has_fd {
            let (lo, hi) = match (mnfd, mxfd) {
                (None, Some(hi)) => (mnfd_default.min(hi), hi),
                (Some(lo), None) => (lo, mxfd_default.max(lo)),
                (Some(lo), Some(hi)) => {
                    if lo > hi {
                        return vm.throw_range("minimumFractionDigits > maximumFractionDigits");
                    }
                    (lo, hi)
                }
                (None, None) => (mnfd_default, mxfd_default),
            };
            min_frac = lo;
            max_frac = hi;
        } else {
            min_frac = mnfd_default;
            max_frac = mxfd_default;
        }
    }
    let rounding_type;
    if !need_sd && !need_fd {
        min_frac = 0.0;
        max_frac = 0.0;
        min_sig = Some(1.0);
        max_sig = Some(2.0);
        rounding_type = "morePrecision";
    } else if rounding_priority == "auto" {
        rounding_type = if need_sd { "significant" } else { "fraction" };
    } else {
        rounding_type = if rounding_priority == "morePrecision" { "morePrecision" } else { "lessPrecision" };
    }
    if rounding_increment != 1 {
        if rounding_type != "fraction" {
            return vm.throw_type("roundingIncrement is only supported with fractionDigits rounding");
        }
        if max_frac != min_frac {
            return vm.throw_range("maximumFractionDigits must equal minimumFractionDigits with roundingIncrement");
        }
    }
    let trailing_zero =
        get_opt_str(vm, opts, "trailingZeroDisplay", &["auto", "stripIfInteger"])?.unwrap_or_else(|| "auto".into());
    let compact_display = get_opt_str(vm, opts, "compactDisplay", &["short", "long"])?.unwrap_or_else(|| "short".into());
    let default_grouping = if notation == "compact" { "min2" } else { "auto" };
    let ug = get_opt(vm, opts, "useGrouping")?;
    let grouping: Value = if ug.is_undefined() {
        Value::str(default_grouping)
    } else if let Value::Bool(b) = ug {
        if b {
            Value::str("always")
        } else {
            Value::Bool(false)
        }
    } else if !ug.truthy() {
        Value::Bool(false)
    } else {
        let s = vm.to_string(&ug)?.to_rust_string();
        match s.as_str() {
            "min2" | "auto" | "always" => Value::str(&s),
            "true" | "false" => Value::str(default_grouping),
            _ => return vm.throw_range(format!("invalid useGrouping: {}", s)),
        }
    };
    let sign_display = get_opt_str(vm, opts, "signDisplay", &["auto", "never", "always", "exceptZero", "negative"])?
        .unwrap_or_else(|| "auto".into());

    // locale + numbering system
    let r = resolve_locale(locales);
    let loc = numdata::num_locale(r.lang(), r.region());
    let ext_nu = r.keyword("nu").filter(|n| numdata::numbering_system_supported(n)).map(|s| s.to_string());
    let mut keep_nu = ext_nu.clone();
    let mut nu = ext_nu.clone().unwrap_or_else(|| loc.default_nu.to_string());
    if let Some(n) = nu_opt.as_deref().filter(|n| numdata::numbering_system_supported(n)) {
        if Some(n) != ext_nu.as_deref() {
            keep_nu = None;
        }
        nu = n.to_string();
    }
    let locale = match &keep_nu {
        Some(n) => r.locale_with(&[("nu", n.as_str())]),
        None => r.base.clone(),
    };

    set_slot(o, "__nf", Value::Bool(true));
    set_slot(o, "__nf_locale", Value::str(&locale));
    set_slot(o, "__nf_nu", Value::str(&nu));
    set_slot(o, "__nf_roundingincrement", Value::Num(rounding_increment as f64));
    set_slot(o, "__nf_roundingpriority", Value::str(&rounding_priority));
    set_slot(o, "__nf_trailingzero", Value::str(&trailing_zero));
    set_slot(o, "__nf_style", Value::str(&style));
    if style == "currency" {
        set_slot(o, "__nf_currency", Value::str(currency.as_deref().unwrap_or("")));
        set_slot(o, "__nf_currencydisplay", Value::str(&currency_display));
        set_slot(o, "__nf_currencysign", Value::str(&currency_sign));
    }
    if let Some(u) = &unit {
        set_slot(o, "__nf_unit", Value::str(u));
        set_slot(o, "__nf_unitdisplay", Value::str(&unit_display));
    }
    set_slot(o, "__nf_minint", Value::Num(mnid));
    set_slot(o, "__nf_minfrac", Value::Num(min_frac));
    set_slot(o, "__nf_maxfrac", Value::Num(max_frac));
    if let (Some(lo), Some(hi)) = (min_sig, max_sig) {
        set_slot(o, "__nf_minsig", Value::Num(lo));
        set_slot(o, "__nf_maxsig", Value::Num(hi));
    }
    set_slot(o, "__nf_notation", Value::str(&notation));
    set_slot(o, "__nf_compactdisplay", Value::str(&compact_display));
    set_slot(o, "__nf_grouping", grouping);
    set_slot(o, "__nf_signdisplay", Value::str(&sign_display));
    set_slot(o, "__nf_roundingmode", Value::str(&rounding_mode));
    set_slot(o, "__nf_roundingtype", Value::str(rounding_type));
    Ok(())
}

// ============================================================================
// Methods
// ============================================================================

fn this_nf_unwrap(vm: &mut Vm, this: &Value) -> JsResult<Obj> {
    let c = nf_ctor_obj();
    super::datetimeformat::unwrap_legacy(vm, this, "__nf", &c)
}

fn bound_format(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.slot(0), "__nf")?;
    let v = to_math_value(vm, &a.arg(0))?;
    let cfg = NfConfig::from_slots(&o);
    Ok(Value::str(&format_string(&cfg, &v)))
}

fn nf_format_getter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_nf_unwrap(vm, &a.this)?;
    if let Some(b) = slot(&o, "__nf_boundformat") {
        return Ok(b);
    }
    let f = vm.native_closure("", 1, bound_format, vec![Value::Obj(o.clone())]);
    set_slot(&o, "__nf_boundformat", Value::Obj(f.clone()));
    Ok(Value::Obj(f))
}

fn nf_format_to_parts(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.this, "__nf")?;
    let v = to_math_value(vm, &a.arg(0))?;
    let cfg = NfConfig::from_slots(&o);
    let parts = format_parts(&cfg, &v);
    Ok(parts_to_array(vm, &parts, &[]))
}

fn nf_resolved_options(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_nf_unwrap(vm, &a.this)?;
    let r = vm.new_object();
    let copy = |r: &Obj, key: &str, name: &str| {
        if let Some(v) = slot(&o, name) {
            if !v.is_undefined() {
                r.set_str(key, v, WEC);
            }
        }
    };
    copy(&r, "locale", "__nf_locale");
    copy(&r, "numberingSystem", "__nf_nu");
    copy(&r, "style", "__nf_style");
    copy(&r, "currency", "__nf_currency");
    copy(&r, "currencyDisplay", "__nf_currencydisplay");
    copy(&r, "currencySign", "__nf_currencysign");
    copy(&r, "unit", "__nf_unit");
    copy(&r, "unitDisplay", "__nf_unitdisplay");
    copy(&r, "minimumIntegerDigits", "__nf_minint");
    let rt = slot_str(&o, "__nf_roundingtype");
    if matches!(rt.as_deref(), Some("fraction" | "morePrecision" | "lessPrecision")) {
        copy(&r, "minimumFractionDigits", "__nf_minfrac");
        copy(&r, "maximumFractionDigits", "__nf_maxfrac");
    }
    copy(&r, "minimumSignificantDigits", "__nf_minsig");
    copy(&r, "maximumSignificantDigits", "__nf_maxsig");
    let g = match slot(&o, "__nf_grouping") {
        Some(v) if !v.is_undefined() => v,
        _ => Value::str("auto"),
    };
    r.set_str("useGrouping", g, WEC);
    copy(&r, "notation", "__nf_notation");
    if slot_str(&o, "__nf_notation").as_deref() == Some("compact") {
        copy(&r, "compactDisplay", "__nf_compactdisplay");
    }
    copy(&r, "signDisplay", "__nf_signdisplay");
    copy(&r, "roundingIncrement", "__nf_roundingincrement");
    copy(&r, "roundingMode", "__nf_roundingmode");
    copy(&r, "roundingPriority", "__nf_roundingpriority");
    copy(&r, "trailingZeroDisplay", "__nf_trailingzero");
    Ok(Value::Obj(r))
}

// ---------------------------------------------------------------------------
// Ranges
// ---------------------------------------------------------------------------

fn range_parts(vm: &mut Vm, a: &Args) -> JsResult<Vec<(Part, &'static str)>> {
    let o = branded_this(vm, &a.this, "__nf")?;
    let (s, e) = (a.arg(0), a.arg(1));
    if s.is_undefined() || e.is_undefined() {
        return vm.throw_type("formatRange requires two arguments");
    }
    let x = to_math_value(vm, &s)?;
    let y = to_math_value(vm, &e)?;
    if x.is_nan() || y.is_nan() {
        return vm.throw_range("formatRange arguments must not be NaN");
    }
    let cfg = NfConfig::from_slots(&o);
    let p1 = format_parts(&cfg, &x);
    let p2 = format_parts(&cfg, &y);
    let mut out = Vec::new();
    if p1 == p2 {
        out.push((Part::new("approximatelySign", "~"), "shared"));
        for p in p1 {
            out.push((p, "shared"));
        }
        return Ok(out);
    }
    let sep = if cfg.style == Style::Currency { " \u{2013} " } else { "\u{2013}" };
    let mut p2 = p2;
    let mut sep = sep;
    if cfg.style == Style::Currency && !cfg.num_locale().currency_suffix {
        // "-$3.00–5.00": a negative start drops the end's currency symbol
        if p1.first().map(|p| p.kind) == Some("minusSign") && p2.first().map(|p| p.kind) == Some("currency") {
            p2.remove(0);
            sep = "\u{2013}";
        }
    }
    for p in p1 {
        out.push((p, "startRange"));
    }
    out.push((Part::new("literal", sep), "shared"));
    for p in p2 {
        out.push((p, "endRange"));
    }
    let _ = &x.to_f64();
    Ok(out)
}

fn nf_format_range(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let parts = range_parts(vm, a)?;
    let s: String = parts.iter().map(|(p, _)| p.value.as_str()).collect();
    Ok(Value::str(&s))
}

fn nf_format_range_to_parts(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let parts = range_parts(vm, a)?;
    let mut out = Vec::with_capacity(parts.len());
    for (p, src) in parts {
        let o = vm.new_object();
        o.set_str("type", Value::str(p.kind), WEC);
        o.set_str("value", Value::str(&p.value), WEC);
        o.set_str("source", Value::str(src), WEC);
        out.push(Value::Obj(o));
    }
    Ok(Value::Obj(vm.new_array(out)))
}

// ============================================================================
// toLocaleString helpers
// ============================================================================

/// Format with a fresh `new Intl.NumberFormat(locales, options)`.
fn format_with_new(vm: &mut Vm, v: MathValue, locales: &Value, opts: &Value) -> JsResult<Value> {
    let locales = locale_list(vm, locales)?;
    let opts = get_options(vm, opts, OptionsMode::Coerce)?;
    let o = vm.new_object();
    init_number_format(vm, &o, &locales, &opts)?;
    let cfg = NfConfig::from_slots(&o);
    Ok(Value::str(&format_string(&cfg, &v)))
}

/// Number.prototype.toLocaleString.
pub fn number_to_locale_string(vm: &mut Vm, x: f64, locales: &Value, opts: &Value) -> JsResult<Value> {
    format_with_new(vm, MathValue::from_f64(x), locales, opts)
}

/// BigInt.prototype.toLocaleString (decimal digits of the BigInt, with sign).
pub fn bigint_to_locale_string(vm: &mut Vm, digits: &str, locales: &Value, opts: &Value) -> JsResult<Value> {
    let neg = digits.starts_with('-');
    let v = MathValue::Finite(neg, Decimal::from_int_str(digits.trim_start_matches('-')), Src::BigInt);
    format_with_new(vm, v, locales, opts)
}

/// Group a decimal digit string with `sep` every three digits.
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
