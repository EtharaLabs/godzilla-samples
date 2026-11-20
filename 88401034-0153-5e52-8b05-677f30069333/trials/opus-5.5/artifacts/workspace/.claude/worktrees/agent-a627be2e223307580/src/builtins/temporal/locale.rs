//! toLocaleString for the Temporal types: the date/time types go through
//! the Intl.DateTimeFormat subset in `crate::datetime` (with the Temporal
//! component filtering), Duration uses an Intl.DurationFormat subset (en).

use super::calendar::Cal;
use super::iso::*;
use super::*;
use crate::builtins::intl;
use crate::datetime as dt;

fn ms_of(d: &IsoDate, t: &Time) -> f64 {
    (utc_epoch_ns(d, t).div_euclid(1_000_000)) as f64
}

fn dt_err<T>(vm: &mut Vm, e: dt::DateTimeError) -> JsResult<T> {
    intl::throw_dt_error(vm, e)
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Kind {
    Date,
    Time,
    DateTime,
    YearMonth,
    MonthDay,
    Instant,
    Zoned,
}

/// Remove the components a Temporal kind cannot show.  Returns false when
/// explicit components were given but none of them is relevant.
fn filter_components(o: &mut dt::DateTimeFormatOptions, k: Kind) -> bool {
    let explicit = o.weekday.is_some()
        || (o.era.is_some() && k != Kind::Time)
        || o.year.is_some()
        || o.month.is_some()
        || o.day.is_some()
        || o.day_period.is_some()
        || o.hour.is_some()
        || o.minute.is_some()
        || o.second.is_some()
        || o.fractional_second_digits.is_some();
    let date_ok = matches!(k, Kind::Date | Kind::DateTime | Kind::Instant | Kind::Zoned);
    let time_ok = matches!(k, Kind::Time | Kind::DateTime | Kind::Instant | Kind::Zoned);
    if !matches!(k, Kind::Instant | Kind::Zoned) {
        o.time_zone_name = None;
    }
    if k == Kind::Time {
        o.era = None;
    }
    if !date_ok {
        o.weekday = None;
        if k != Kind::YearMonth {
            o.year = None;
        }
        if k != Kind::MonthDay {
            o.day = None;
        }
        if k == Kind::Time {
            o.month = None;
        }
    }
    if !time_ok {
        o.day_period = None;
        o.hour = None;
        o.minute = None;
        o.second = None;
        o.fractional_second_digits = None;
    }
    let remaining = o.weekday.is_some()
        || o.era.is_some()
        || o.year.is_some()
        || o.month.is_some()
        || o.day.is_some()
        || o.day_period.is_some()
        || o.hour.is_some()
        || o.minute.is_some()
        || o.second.is_some()
        || o.fractional_second_digits.is_some();
    !(explicit && !remaining)
}

fn resolved_calendar(f: &dt::DateTimeFormat) -> String {
    for (k, v) in f.resolved_options() {
        if k == "calendar" {
            if let dt::ResolvedValue::Str(s) = v {
                return s;
            }
        }
    }
    "gregory".to_string()
}

fn strip_zone_suffix(s: String) -> String {
    for suf in [" Coordinated Universal Time", " UTC"] {
        if let Some(p) = s.strip_suffix(suf) {
            return p.to_string();
        }
    }
    s
}

pub fn to_locale_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let which = a.slot(0).as_num().unwrap_or(0.0);
    let s = slot_of(&a.this);
    if which == 1.0 {
        // Temporal.Duration.prototype.toLocaleString
        return match s {
            Some(Slot::Duration(d)) => duration_to_locale_string(vm, &d, &a.arg(0), &a.arg(1)),
            _ => recv_err(vm, K::Duration),
        };
    }
    if which == 2.0 && !matches!(s, Some(Slot::Zoned(..))) {
        return vm.throw_type("Temporal.ZonedDateTime.prototype.toLocaleString called on an incompatible receiver");
    }
    let s = match s {
        Some(s) => s,
        None => return vm.throw_type("toLocaleString called on a non-Temporal receiver"),
    };
    if which == 0.0 {
        match &s {
            Slot::Zoned(..) => {
                return vm.throw_type(
                    "Intl.DateTimeFormat does not support Temporal.ZonedDateTime; use zonedDateTime.toLocaleString()",
                )
            }
            Slot::Duration(_) => {
                // formatted like an unsupported value: the epoch, Intl defaults
                let locales = intl::locale_list(vm, &a.arg(0))?;
                let opt_arg = if a.arg(1).is_object() { a.arg(1) } else { Value::Undefined };
                let opts = intl::read_dtf_options(vm, &opt_arg)?;
                let r = dt::DateTimeFormat::with_defaults(&locales, &opts, dt::RequiredComponents::Any, dt::DefaultComponents::Date)
                    .and_then(|f| f.format(0.0));
                return match r {
                    Ok(s) => Ok(Value::str(&s)),
                    Err(e) => dt_err(vm, e),
                };
            }
            _ => {}
        }
    }
    let locales = intl::locale_list(vm, &a.arg(0))?;
    if a.arg(1).is_null() {
        if matches!(s, Slot::Zoned(..)) {
            return vm.throw_type("options must be an object");
        }
        return vm.throw_type("options cannot be null");
    }
    if matches!(s, Slot::Zoned(..)) && !a.arg(1).is_object() && !a.arg(1).is_undefined() {
        return vm.throw_type("options must be an object");
    }
    let opt_arg = if a.arg(1).is_object() { a.arg(1) } else { Value::Undefined };
    if let Value::Obj(o) = &opt_arg {
        // the original peeks at the styles first
        vm.get_str(o, "dateStyle")?;
        vm.get_str(o, "timeStyle")?;
    }
    let mut opts = intl::read_dtf_options(vm, &opt_arg)?;
    // validate the combination (styles vs components, locale tags)
    if let Err(e) = dt::DateTimeFormat::with_defaults(&locales, &opts, dt::RequiredComponents::Any, dt::DefaultComponents::All) {
        return dt_err(vm, e);
    }
    let (kind, cal) = match &s {
        Slot::Date(_, c) => (Kind::Date, Some(*c)),
        Slot::Time(_) => (Kind::Time, None),
        Slot::DateTime(_, c) => (Kind::DateTime, Some(*c)),
        Slot::YearMonth(_, c) => (Kind::YearMonth, Some(*c)),
        Slot::MonthDay(_, c) => (Kind::MonthDay, Some(*c)),
        Slot::Instant(_) => (Kind::Instant, None),
        Slot::Zoned(_, _, c) => (Kind::Zoned, Some(*c)),
        Slot::Duration(_) => return Ok(Value::Undefined),
    };
    if kind == Kind::Zoned && opts.time_zone.is_some() {
        return vm.throw_type("the timeZone option is not allowed for Temporal.ZonedDateTime.prototype.toLocaleString");
    }
    if matches!(kind, Kind::Date | Kind::YearMonth | Kind::MonthDay) && opts.time_style.is_some() {
        return vm.throw_type("timeStyle cannot format a date-only Temporal value");
    }
    if kind == Kind::Time && opts.date_style.is_some() {
        return vm.throw_type("dateStyle cannot format a time-only Temporal value");
    }
    let had_components = opts.weekday.is_some()
        || opts.era.is_some()
        || opts.year.is_some()
        || opts.month.is_some()
        || opts.day.is_some()
        || opts.day_period.is_some()
        || opts.hour.is_some()
        || opts.minute.is_some()
        || opts.second.is_some()
        || opts.fractional_second_digits.is_some();
    if !filter_components(&mut opts, kind) {
        return vm.throw_type("no overlap between the formatter and the Temporal value");
    }
    let styles = opts.date_style.is_some() || opts.time_style.is_some();
    let (required, defaults) = match kind {
        Kind::Date | Kind::YearMonth | Kind::MonthDay => (dt::RequiredComponents::Date, dt::DefaultComponents::Date),
        Kind::Time => (dt::RequiredComponents::Time, dt::DefaultComponents::Time),
        Kind::Zoned if opts.era.is_some() && !had_components_besides_era(&opts) => {
            (dt::RequiredComponents::Date, dt::DefaultComponents::Date)
        }
        _ => (dt::RequiredComponents::Any, dt::DefaultComponents::All),
    };
    match kind {
        Kind::Instant => {}
        Kind::Zoned => {
            if let Slot::Zoned(_, tz, _) = &s {
                opts.time_zone = Some(tz.id());
            }
            if !had_components && !styles && opts.time_zone_name.is_none() {
                let _ = opts.set("timeZoneName", "short");
            }
        }
        _ => opts.time_zone = Some("UTC".to_string()),
    }
    if kind == Kind::YearMonth && !had_components && !styles {
        let _ = opts.set("year", "numeric");
        let _ = opts.set("month", "numeric");
    }
    if kind == Kind::MonthDay && !had_components && !styles {
        let _ = opts.set("month", "numeric");
        let _ = opts.set("day", "numeric");
    }
    let f = match dt::DateTimeFormat::with_defaults(&locales, &opts, required, defaults) {
        Ok(f) => f,
        Err(e) => return dt_err(vm, e),
    };
    if let Some(c) = cal {
        let fc = resolved_calendar(&f);
        let iso_ok = matches!(kind, Kind::Date | Kind::DateTime | Kind::Zoned) && c == Cal::Iso8601;
        if c.id() != fc && !iso_ok {
            return vm.throw_range(format!("calendar mismatch: {} vs {}", c.id(), fc));
        }
    }
    let t = match &s {
        Slot::Date(d, _) | Slot::YearMonth(d, _) | Slot::MonthDay(d, _) => ms_of(d, &Time::MIDNIGHT),
        Slot::Time(t) => ms_of(&IsoDate::new(1970, 1, 1), t),
        Slot::DateTime(d, _) => ms_of(&d.date, &d.time),
        Slot::Instant(ns) | Slot::Zoned(ns, _, _) => ns.div_euclid(1_000_000) as f64,
        Slot::Duration(_) => 0.0,
    };
    let out = match f.format(t) {
        Ok(s) => s,
        Err(e) => return dt_err(vm, e),
    };
    let out = if matches!(kind, Kind::Date | Kind::Time | Kind::DateTime | Kind::YearMonth | Kind::MonthDay)
        && opts.time_style.is_some()
    {
        strip_zone_suffix(out)
    } else {
        out
    };
    Ok(Value::str(&out))
}

fn had_components_besides_era(o: &dt::DateTimeFormatOptions) -> bool {
    o.weekday.is_some()
        || o.year.is_some()
        || o.month.is_some()
        || o.day.is_some()
        || o.day_period.is_some()
        || o.hour.is_some()
        || o.minute.is_some()
        || o.second.is_some()
        || o.fractional_second_digits.is_some()
}

// ---------------------------------------------------------------------------
// Duration (Intl.DurationFormat subset with the original's locale data)
// ---------------------------------------------------------------------------

use super::dur_locale_data::DUR_LOCALES;

#[derive(Clone, Copy, PartialEq, Eq)]
enum UStyle {
    Long,
    Short,
    Narrow,
    Numeric,
    TwoDigit,
    Fractional,
}

/// Number formatting of the resolved locale
struct NumStyle {
    group: &'static str,
    decimal: &'static str,
    arab: bool,
    indian: bool,
}

impl NumStyle {
    fn digits(&self, s: &str) -> String {
        if !self.arab {
            return s.to_string();
        }
        s.chars()
            .map(|c| match c.to_digit(10) {
                Some(d) => char::from_u32(0x660 + d).unwrap_or(c),
                None => c,
            })
            .collect()
    }

    fn int(&self, n: u128) -> String {
        let s = n.to_string();
        let b = s.as_bytes();
        let len = b.len();
        let mut out = String::new();
        for (i, &c) in b.iter().enumerate() {
            let left = len - i;
            if i > 0 {
                let sep = if self.indian { left == 3 || (left > 3 && (left - 3) % 2 == 0) } else { left % 3 == 0 };
                if sep {
                    out += self.group;
                }
            }
            out.push(c as char);
        }
        self.digits(&out)
    }
}

/// (index into DUR_LOCALES, number style) of the first supported locale
fn resolve_duration_locale(locales: &[String]) -> (usize, NumStyle) {
    const KNOWN: [&str; 21] = [
        "ar", "de", "en", "es", "fr", "gv", "hi", "it", "ja", "ko", "ln", "nl", "pl", "pt", "ru", "si", "sl", "sr", "sv", "th",
        "zh",
    ];
    let mut lang = "en".to_string();
    let mut region = String::new();
    for l in locales {
        let parts: Vec<&str> = l.split('-').collect();
        let lg = parts[0].to_ascii_lowercase();
        if KNOWN.contains(&lg.as_str()) {
            lang = lg;
            for p in &parts[1..] {
                if p.len() == 2 && p.chars().all(|c| c.is_ascii_alphabetic()) {
                    region = p.to_ascii_uppercase();
                    break;
                }
                if p.len() == 3 && p.chars().all(|c| c.is_ascii_digit()) {
                    region = p.to_string();
                    break;
                }
                if p.len() != 4 {
                    break;
                }
            }
            break;
        }
    }
    let tag = match lang.as_str() {
        "zh" if matches!(region.as_str(), "TW" | "HK" | "MO") => "zh-TW",
        "en" if region == "IN" => "en-IN",
        "gv" | "hi" | "ln" | "si" | "sl" | "sr" | "sv" | "th" => "hi",
        l => l,
    };
    let idx = DUR_LOCALES.iter().position(|d| d.tag == tag).unwrap_or(0);
    let mut ns = NumStyle { group: ",", decimal: ".", arab: false, indian: false };
    match lang.as_str() {
        "de" | "es" | "it" | "nl" => {
            ns.group = ".";
            ns.decimal = ",";
        }
        "pt" => {
            ns.group = if region == "PT" { "\u{a0}" } else { "." };
            ns.decimal = ",";
        }
        "fr" | "ru" | "sv" => {
            ns.group = "\u{202f}";
            ns.decimal = ",";
        }
        "pl" => {
            ns.group = "\u{a0}";
            ns.decimal = ",";
        }
        "ar" => {
            ns.arab = !matches!(region.as_str(), "MA" | "DZ" | "TN" | "LY" | "EH" | "MR");
        }
        "hi" => ns.indian = true,
        "en" if region == "IN" => ns.indian = true,
        _ => {}
    }
    (idx, ns)
}

const UNIT_KEYS: [&str; 10] =
    ["years", "months", "weeks", "days", "hours", "minutes", "seconds", "milliseconds", "microseconds", "nanoseconds"];

fn duration_to_locale_string(vm: &mut Vm, d: &dur::Dur, locales: &Value, options: &Value) -> JsResult<Value> {
    let locales = intl::locale_list(vm, locales)?;
    let opts = match options {
        Value::Undefined => None,
        Value::Obj(o) => Some(o.clone()),
        _ => return vm.throw_type("options must be an object or undefined"),
    };
    let get = |vm: &mut Vm, name: &str| -> JsResult<Option<String>> { opt_string(vm, &opts, name) };
    let _ = get(vm, "localeMatcher")?;
    let _ = get(vm, "numberingSystem")?;
    let base = match get(vm, "style")?.as_deref() {
        None | Some("short") => "short",
        Some("long") => "long",
        Some("narrow") => "narrow",
        Some("digital") => "digital",
        Some(s) => return vm.throw_range(format!("invalid style: {}", s)),
    };
    let mut styles = [UStyle::Short; 10];
    let mut display_always = [false; 10];
    let mut prev: Option<UStyle> = None;
    for i in 0..10 {
        let key = UNIT_KEYS[i];
        let given = get(vm, key)?;
        let mut display_default_always = true;
        let mut style = match given.as_deref() {
            None => None,
            Some("long") => Some(UStyle::Long),
            Some("short") => Some(UStyle::Short),
            Some("narrow") => Some(UStyle::Narrow),
            Some("numeric") if i >= 4 => Some(UStyle::Numeric),
            Some("2-digit") if (4..=6).contains(&i) => Some(UStyle::TwoDigit),
            Some(s) => return vm.throw_range(format!("invalid {}: {}", key, s)),
        };
        if style.is_none() {
            if base == "digital" {
                if !(4..=6).contains(&i) {
                    display_default_always = false;
                }
                style = Some(if i < 4 {
                    UStyle::Short
                } else if i == 4 {
                    UStyle::Numeric
                } else if i <= 6 {
                    UStyle::TwoDigit
                } else {
                    UStyle::Fractional
                });
            } else if matches!(prev, Some(UStyle::Numeric) | Some(UStyle::TwoDigit) | Some(UStyle::Fractional)) {
                if !(5..=6).contains(&i) {
                    display_default_always = false;
                }
                style = Some(if i >= 7 { UStyle::Fractional } else { UStyle::Numeric });
            } else {
                display_default_always = false;
                style = Some(match base {
                    "long" => UStyle::Long,
                    "narrow" => UStyle::Narrow,
                    _ => UStyle::Short,
                });
            }
        }
        let mut st = style.unwrap_or(UStyle::Short);
        if st == UStyle::Numeric && i >= 7 {
            st = UStyle::Fractional;
            display_default_always = false;
        }
        let disp = get(vm, &format!("{}Display", key))?;
        display_always[i] = match disp.as_deref() {
            None => display_default_always,
            Some("always") => true,
            Some("auto") => false,
            Some(s) => return vm.throw_range(format!("invalid {}Display: {}", key, s)),
        };
        styles[i] = st;
        prev = Some(st);
    }
    let fd = opt_get(vm, &opts, "fractionalDigits")?;
    let frac_digits = if fd.is_undefined() {
        None
    } else {
        let n = vm.to_number(&fd)?;
        if !n.is_finite() || !(0.0..=9.0).contains(&n.floor()) {
            return vm.throw_range("fractionalDigits out of range");
        }
        Some(n.floor() as usize)
    };
    let (li, ns) = resolve_duration_locale(&locales);
    Ok(Value::str(&format_duration(d, base, &styles, &display_always, frac_digits, li, &ns)))
}

fn format_duration(
    d: &dur::Dur,
    base: &str,
    styles: &[UStyle; 10],
    always: &[bool; 10],
    frac: Option<usize>,
    li: usize,
    ns: &NumStyle,
) -> String {
    let data = &DUR_LOCALES[li];
    let f = d.fields();
    let negative = d.sign() < 0;
    let mut parts: Vec<String> = Vec::new();
    let mut sign_used = false;
    let mut i = 0;
    while i < 10 {
        let v = f[i].abs();
        let st = styles[i];
        if matches!(st, UStyle::Numeric | UStyle::TwoDigit) && i >= 4 {
            // numeric clock group: hours/minutes/seconds (+ fractional)
            let mut s = String::new();
            let mut j = i;
            let mut first = true;
            while j <= 6 && matches!(styles[j], UStyle::Numeric | UStyle::TwoDigit) {
                let carry = if j == 6 && styles[7] == UStyle::Fractional { ((f[7].abs() as u128) * 1_000_000 + (f[8].abs() as u128) * 1000 + f[9].abs() as u128) / 1_000_000_000 } else { 0 };
                let val = f[j].abs() as u128 + carry;
                if !first {
                    s.push(':');
                }
                if first && !(always[j] || val != 0) && j < 6 {
                    j += 1;
                    continue;
                }
                let two = styles[j] == UStyle::TwoDigit || !first;
                if two {
                    s += &format!("{:02}", val);
                } else {
                    s += &val.to_string();
                }
                first = false;
                j += 1;
            }
            // fractional sub-second units
            if j == 7 && styles[7] == UStyle::Fractional {
                let total = (f[7].abs() as u128) * 1_000_000 + (f[8].abs() as u128) * 1000 + f[9].abs() as u128;
                let digits = format!("{:09}", total % 1_000_000_000);
                let frac_s = match frac {
                    Some(n) => digits[..n].to_string(),
                    None => digits.trim_end_matches('0').to_string(),
                };
                if !frac_s.is_empty() {
                    s += ns.decimal;
                    s += &frac_s;
                }
                j = 10;
            }
            if !s.is_empty() {
                let mut s = ns.digits(&s);
                if negative && !sign_used {
                    s = format!("-{}", s);
                    sign_used = true;
                }
                parts.push(s);
            }
            i = j;
            continue;
        }
        if st == UStyle::Fractional {
            i += 1;
            continue;
        }
        if v == 0.0 && !always[i] {
            i += 1;
            continue;
        }
        let si = match st {
            UStyle::Long => 1,
            UStyle::Narrow => 2,
            _ => 0,
        };
        let pat = data.units[si][i][if v == 1.0 { 0 } else { 1 }];
        let mut n = ns.int(v as u128);
        if negative && !sign_used {
            n = format!("-{}", n);
            sign_used = true;
        }
        parts.push(pat.replace("{0}", &n));
        i += 1;
    }
    let li_style = match base {
        "long" => 1,
        "narrow" => 2,
        _ => 0,
    };
    let [pair, middle, end] = data.lists[li_style];
    match parts.len() {
        0 => String::new(),
        1 => parts.remove(0),
        2 => format!("{}{}{}", parts[0], pair, parts[1]),
        n => {
            let mut out = parts[0].clone();
            for p in &parts[1..n - 1] {
                out += middle;
                out += p;
            }
            out += end;
            out += &parts[n - 1];
            out
        }
    }
}
