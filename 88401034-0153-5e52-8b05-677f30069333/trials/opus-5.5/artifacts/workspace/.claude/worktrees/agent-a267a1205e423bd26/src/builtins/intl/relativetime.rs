//! Intl.RelativeTimeFormat.
//!
//! The original only has relative-time data for English and Polish: every
//! other language uses the English patterns (with its own number symbols).
//! `numeric: "auto"` phrases ("yesterday", "next week", "now", ...) are
//! English for every language and every style; they apply when the value
//! truncated towards zero is -1, 0 or 1 and a phrase exists.  The pattern is
//! chosen by the sign bit (negative incl. -0 = past) and the plural category
//! of the raw value (English data, for every language but Polish: "one" for
//! exactly 1 whatever the locale's own rules say; Polish: one/few/many/other
//! under the original's rules).  The number is |value| formatted like a
//! default Intl.NumberFormat of the locale (Polish uses min2 grouping) with
//! the numbering system of the `__rtf_nu` slot (latn when missing).
//!
//! Slots: `__rtf: true`, `__rtf_locale`, `__rtf_numeric`, `__rtf_style`,
//! `__rtf_nu`.  At format time the locale slot is re-parsed
//! (`RangeError: Incorrect locale information provided: <tag>` if invalid,
//! non-strings mean `en`); an unknown style is formatted like "short", an
//! unknown numeric like "always".

use super::numberformat::{self, Grouping, MathValue, NfConfig};
use super::numdata;
use super::*;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    define_class(
        vm,
        intl,
        "RelativeTimeFormat",
        0,
        rtf_ctor,
        &[
            Member::Method("format", 2, rtf_format),
            Member::Method("formatToParts", 2, rtf_format_to_parts),
            Member::Method("resolvedOptions", 0, rtf_resolved_options),
        ],
        true,
    );
}

// ============================================================================
// Data
// ============================================================================

const UNITS: [&str; 8] = ["second", "minute", "hour", "day", "week", "month", "quarter", "year"];

/// English patterns: [unit][style long/short] -> (singular, plural) labels.
/// Short and narrow are identical.
const EN_LONG: [(&str, &str); 8] = [
    ("second", "seconds"),
    ("minute", "minutes"),
    ("hour", "hours"),
    ("day", "days"),
    ("week", "weeks"),
    ("month", "months"),
    ("quarter", "quarters"),
    ("year", "years"),
];
const EN_SHORT: [(&str, &str); 8] = [
    ("sec.", "sec."),
    ("min.", "min."),
    ("hr.", "hr."),
    ("day", "days"),
    ("wk.", "wk."),
    ("mo.", "mo."),
    ("qtr.", "qtrs."),
    ("yr.", "yr."),
];

/// Polish labels: [unit] -> [one, few, many, other].
const PL_LONG: [[&str; 4]; 8] = [
    ["sekundę", "sekundy", "sekund", "sekundy"],
    ["minutę", "minuty", "minut", "minuty"],
    ["godzinę", "godziny", "godzin", "godziny"],
    ["dzień", "dni", "dni", "dnia"],
    ["tydzień", "tygodnie", "tygodni", "tygodnia"],
    ["miesiąc", "miesiące", "miesięcy", "miesiąca"],
    ["kwartał", "kwartały", "kwartałów", "kwartału"],
    ["rok", "lata", "lat", "roku"],
];
const PL_SHORT: [[&str; 4]; 8] = [
    ["sek.", "sek.", "sek.", "sek."],
    ["min", "min", "min", "min"],
    ["godz.", "godz.", "godz.", "godz."],
    ["dzień", "dni", "dni", "dnia"],
    ["tydz.", "tyg.", "tyg.", "tyg."],
    ["mies.", "mies.", "mies.", "mies."],
    ["kw.", "kw.", "kw.", "kw."],
    ["rok", "lata", "lat", "roku"],
];
const PL_NARROW: [[&str; 4]; 8] = [
    ["s", "s", "s", "s"],
    ["min", "min", "min", "min"],
    ["g.", "g.", "g.", "g."],
    ["dzień", "dni", "dni", "dnia"],
    ["tydz.", "tyg.", "tyg.", "tyg."],
    ["mies.", "mies.", "mies.", "mies."],
    ["kw.", "kw.", "kw.", "kw."],
    ["rok", "lata", "lat", "roku"],
];

/// numeric "auto" phrases for -1, 0, 1 (English, every style).
const AUTO: [[Option<&str>; 3]; 8] = [
    [None, Some("now"), None],
    [None, Some("this minute"), None],
    [None, Some("this hour"), None],
    [Some("yesterday"), Some("today"), Some("tomorrow")],
    [Some("last week"), Some("this week"), Some("next week")],
    [Some("last month"), Some("this month"), Some("next month")],
    [Some("last quarter"), Some("this quarter"), Some("next quarter")],
    [Some("last year"), Some("this year"), Some("next year")],
];

#[derive(Clone, Copy, PartialEq, Eq)]
enum Style {
    Long,
    Short,
    Narrow,
}

/// (prefix, suffix) around the number.
fn pattern(lang: &str, style: Style, unit: usize, past: bool, x: f64) -> (String, String) {
    // the English data is used with the English plural rule for every
    // language without its own data
    let rules = if lang == "pl" { "pl" } else { "en" };
    let cat = super::pluralrules::plural_category(rules, x.abs());
    if lang == "pl" {
        let table = match style {
            Style::Long => &PL_LONG,
            Style::Short => &PL_SHORT,
            Style::Narrow => &PL_NARROW,
        };
        let idx = match cat {
            "one" => 0,
            "few" => 1,
            "many" => 2,
            _ => 3,
        };
        let label = table[unit][idx];
        if past {
            (String::new(), format!(" {} temu", label))
        } else {
            ("za ".to_string(), format!(" {}", label))
        }
    } else {
        let table = if style == Style::Long { &EN_LONG } else { &EN_SHORT };
        let (one, other) = table[unit];
        let label = if cat == "one" { one } else { other };
        if past {
            (String::new(), format!(" {} ago", label))
        } else {
            ("in ".to_string(), format!(" {}", label))
        }
    }
}

/// SingularRelativeTimeUnit.
fn unit_index(u: &str) -> Option<usize> {
    let s = u.strip_suffix('s').unwrap_or(u);
    UNITS.iter().position(|x| *x == s)
}

// ============================================================================
// Constructor
// ============================================================================

fn rtf_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_new(vm, a, "RelativeTimeFormat")?;
    let locales = locale_list(vm, &a.arg(0))?;
    let opts = get_options(vm, &a.arg(1), OptionsMode::Coerce)?;
    read_locale_matcher(vm, &opts)?;
    let nu_opt = get_opt_str(vm, &opts, "numberingSystem", &[])?;
    if let Some(nu) = &nu_opt {
        if !is_unicode_type(nu) {
            return vm.throw_range(format!("invalid numberingSystem: {}", nu));
        }
    }
    let style = get_opt_str(vm, &opts, "style", &["long", "short", "narrow"])?.unwrap_or_else(|| "long".into());
    let numeric = get_opt_str(vm, &opts, "numeric", &["always", "auto"])?.unwrap_or_else(|| "always".into());

    let r = resolve_locale(&locales);
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

    let o = alloc_instance(vm, a)?;
    set_slot(&o, "__rtf", Value::Bool(true));
    set_slot(&o, "__rtf_locale", Value::str(&locale));
    set_slot(&o, "__rtf_numeric", Value::str(&numeric));
    set_slot(&o, "__rtf_style", Value::str(&style));
    set_slot(&o, "__rtf_nu", Value::str(&nu));
    Ok(Value::Obj(o))
}

// ============================================================================
// Formatting
// ============================================================================

/// One formatted part: (type, value, unit of the number parts).
type RtfPart = (&'static str, String, Option<&'static str>);

fn format_impl(vm: &mut Vm, a: &Args) -> JsResult<Vec<RtfPart>> {
    let o = branded_this(vm, &a.this, "__rtf")?;
    let x = vm.to_number(&a.arg(0))?;
    if !x.is_finite() {
        return vm.throw_range("value must be finite");
    }
    let u = vm.to_string(&a.arg(1))?.to_rust_string();
    let ui = match unit_index(&u) {
        Some(i) => i,
        None => return vm.throw_range(format!("invalid unit: {}", u)),
    };
    // locale (re-parsed from the slot)
    let locale = match slot(&o, "__rtf_locale") {
        Some(Value::Str(s)) => {
            let s = s.to_rust_string();
            match canonicalize_tag(&s) {
                Some(_) => s,
                None => return vm.throw_range(format!("Incorrect locale information provided: {}", s)),
            }
        }
        _ => "en".to_string(),
    };
    let tag = parse_tag(&locale);
    let lang = tag.as_ref().map(|t| t.language.clone()).unwrap_or_else(|| "en".to_string());
    let style = match slot_str(&o, "__rtf_style").as_deref() {
        None | Some("long") => Style::Long,
        Some("narrow") => Style::Narrow,
        Some(_) => Style::Short,
    };
    let numeric_auto = slot_str(&o, "__rtf_numeric").as_deref() == Some("auto");
    let nu = slot_str(&o, "__rtf_nu").filter(|n| numdata::numbering_system_supported(n)).unwrap_or_else(|| "latn".to_string());

    let unit_name: &'static str = UNITS[ui];
    if numeric_auto {
        let t = x.trunc();
        if t == -1.0 || t == 0.0 || t == 1.0 {
            let idx = (t as i32 + 1) as usize;
            if let Some(p) = AUTO[ui][idx] {
                return Ok(vec![("literal", p.to_string(), None)]);
            }
        }
    }
    let past = x.is_sign_negative();
    let (prefix, suffix) = pattern(&lang, style, ui, past, x);
    let mut cfg = NfConfig::decimal(&locale, &nu);
    if lang == "pl" {
        cfg.grouping = Grouping::Min2;
    }
    let num_parts = numberformat::format_parts(&cfg, &MathValue::from_f64(x.abs()));
    let mut out: Vec<RtfPart> = Vec::new();
    if !prefix.is_empty() {
        out.push(("literal", prefix, None));
    }
    for p in num_parts {
        out.push((p.kind, p.value, Some(unit_name)));
    }
    if !suffix.is_empty() {
        out.push(("literal", suffix, None));
    }
    Ok(out)
}

fn rtf_format(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let parts = format_impl(vm, a)?;
    let s: String = parts.iter().map(|(_, v, _)| v.as_str()).collect();
    Ok(Value::str(&s))
}

fn rtf_format_to_parts(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let parts = format_impl(vm, a)?;
    let mut out = Vec::with_capacity(parts.len());
    for (kind, value, unit) in parts {
        let o = vm.new_object();
        o.set_str("type", Value::str(kind), WEC);
        o.set_str("value", Value::str(&value), WEC);
        if let Some(u) = unit {
            o.set_str("unit", Value::str(u), WEC);
        }
        out.push(Value::Obj(o));
    }
    Ok(Value::Obj(vm.new_array(out)))
}

fn rtf_resolved_options(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.this, "__rtf")?;
    let r = vm.new_object();
    for (key, name) in [
        ("locale", "__rtf_locale"),
        ("style", "__rtf_style"),
        ("numeric", "__rtf_numeric"),
        ("numberingSystem", "__rtf_nu"),
    ] {
        if let Some(v) = slot(&o, name) {
            if !v.is_undefined() {
                r.set_str(key, v, WEC);
            }
        }
    }
    Ok(Value::Obj(r))
}
