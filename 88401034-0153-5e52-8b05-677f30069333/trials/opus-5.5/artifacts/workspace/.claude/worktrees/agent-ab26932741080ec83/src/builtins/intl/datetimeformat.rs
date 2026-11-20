//! Intl.DateTimeFormat: JS bindings over `crate::datetime` (which implements
//! the original's patterns, locales, calendars and time zones).
//!
//! Internal slots (own data properties, in this order):
//! `__dtf: true`, `__dtf_locale`, `__dtf_ca`, `__dtf_nu`, `__dtf_tz`, the
//! explicit components (`weekday era year month day dayperiod hour minute
//! second fracsec tzname`), then for styles `datestyle`, `timestyle` and the
//! expanded components `__dtfx_weekday __dtfx_month __dtfx_day __dtfx_year
//! __dtfx_hour __dtfx_minute __dtfx_second __dtfx_tzname`, then
//! `hourcycle`, `hour12`, `hourshown`, and finally
//! when no component was requested the defaults `year month day` (numeric)
//! and `defaults: true`.  `format` caches its bound function in
//! `__dtf_bound`.  The formatter is rebuilt from the slots for every call.
//!
//! Legacy constructor semantics (ECMA-402 ChainDateTimeFormat): calling
//! `Intl.DateTimeFormat` without `new` on a `this` that inherits from
//! `Intl.DateTimeFormat.prototype` stores the new formatter in
//! `this[Symbol(IntlLegacyConstructedSymbol)]` and returns `this`; the
//! `format` getter and `resolvedOptions` unwrap it.

use super::*;
use std::cell::RefCell;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    let (c, _) = define_class(
        vm,
        intl,
        "DateTimeFormat",
        0,
        dtf_ctor,
        &[
            Member::Method("formatToParts", 1, dtf_format_to_parts),
            Member::Method("resolvedOptions", 0, dtf_resolved_options),
            Member::Method("formatRange", 2, dtf_format_range),
            Member::Method("formatRangeToParts", 2, dtf_format_range_to_parts),
            Member::Getter("format", dtf_format_getter),
        ],
        true,
    );
    DTF_CTOR.with(|s| *s.borrow_mut() = Some(c));
}

thread_local! {
    static DTF_CTOR: RefCell<Option<Obj>> = RefCell::new(None);
    static LEGACY_SYM: RefCell<Option<Sym>> = RefCell::new(None);
}

/// The shared `Symbol(IntlLegacyConstructedSymbol)` (also used by
/// Intl.NumberFormat).
pub fn legacy_symbol() -> Sym {
    LEGACY_SYM.with(|s| {
        let mut b = s.borrow_mut();
        if b.is_none() {
            *b = Some(Sym::new(Some(JsStr::from_str("IntlLegacyConstructedSymbol"))));
        }
        b.clone().unwrap()
    })
}

/// Legacy constructor call: `C.call(thisObj, ...)` with `thisObj instanceof
/// C` stores `inst` under the legacy symbol and returns `thisObj`.
pub fn legacy_construct(vm: &mut Vm, a: &Args, ctor: &Obj, inst: Obj) -> JsResult<Value> {
    if a.new_target.is_none() {
        if let Value::Obj(t) = &a.this {
            if vm.ordinary_has_instance(ctor, &a.this)? {
                let key = PropKey::Sym(legacy_symbol());
                let desc = PropDesc {
                    value: Some(Value::Obj(inst)),
                    writable: Some(false),
                    enumerable: Some(false),
                    configurable: Some(false),
                    ..Default::default()
                };
                if !vm.define_own_property(t, key, desc)? {
                    return vm.throw_type("Cannot redefine property: Symbol(IntlLegacyConstructedSymbol)");
                }
                return Ok(a.this.clone());
            }
        }
    }
    Ok(Value::Obj(inst))
}

/// UnwrapDateTimeFormat / UnwrapNumberFormat: `this` itself when branded,
/// else (for instances of `ctor`) the legacy-constructed formatter.
pub fn unwrap_legacy(vm: &mut Vm, this: &Value, brand: &str, ctor: &Obj) -> JsResult<Obj> {
    if has_brand(this, brand) {
        return branded_this(vm, this, brand);
    }
    if let Value::Obj(t) = this {
        if vm.ordinary_has_instance(ctor, this)? {
            let v = vm.get(t, &PropKey::Sym(legacy_symbol()), this)?;
            if has_brand(&v, brand) {
                return branded_this(vm, &v, brand);
            }
        }
    }
    incompatible(vm)
}

fn dtf_ctor_obj() -> Obj {
    DTF_CTOR.with(|s| s.borrow().clone().unwrap())
}

// ---------------------------------------------------------------------------
// Options
// ---------------------------------------------------------------------------

const OPTION_ORDER: [&str; 20] = [
    "localeMatcher",
    "calendar",
    "numberingSystem",
    "hour12",
    "hourCycle",
    "timeZone",
    "weekday",
    "era",
    "year",
    "month",
    "day",
    "dayPeriod",
    "hour",
    "minute",
    "second",
    "fractionalSecondDigits",
    "timeZoneName",
    "formatMatcher",
    "dateStyle",
    "timeStyle",
];

fn read_options_obj(vm: &mut Vm, obj: &Obj) -> JsResult<dt::DateTimeFormatOptions> {
    let mut o = dt::DateTimeFormatOptions::new();
    for name in OPTION_ORDER {
        let val = vm.get_str(obj, name)?;
        if val.is_undefined() {
            continue;
        }
        match name {
            "hour12" => o.set_hour12(val.truthy()),
            "fractionalSecondDigits" => {
                let n = vm.to_number(&val)?;
                if let Err(e) = o.set_fractional_second_digits(n) {
                    return throw_dt_error(vm, e);
                }
            }
            _ => {
                let s = vm.to_string(&val)?.to_rust_string();
                if let Err(e) = o.set(name, &s) {
                    return throw_dt_error(vm, e);
                }
            }
        }
    }
    Ok(o)
}

/// Options of Date.prototype.toLocale{,Date,Time}String (non-object options:
/// `TypeError: options must be an object`).
pub fn read_dtf_options(vm: &mut Vm, v: &Value) -> JsResult<dt::DateTimeFormatOptions> {
    match v {
        Value::Undefined => Ok(dt::DateTimeFormatOptions::new()),
        Value::Obj(ob) => read_options_obj(vm, &ob.clone()),
        _ => vm.throw_type("options must be an object"),
    }
}

// ---------------------------------------------------------------------------
// Construction
// ---------------------------------------------------------------------------

fn dt_err<T>(vm: &mut Vm, r: Result<T, dt::DateTimeError>) -> JsResult<T> {
    match r {
        Ok(v) => Ok(v),
        Err(e) => throw_dt_error(vm, e),
    }
}

fn resolved_str(ro: &[(&'static str, dt::ResolvedValue)], key: &str) -> Option<String> {
    ro.iter().find(|(k, _)| *k == key).and_then(|(_, v)| match v {
        dt::ResolvedValue::Str(s) => Some(s.clone()),
        _ => None,
    })
}

/// datetime.rs maps numeric regions (zh-158 -> zh-TW, ar-504 -> ar-MA)
/// that the original keeps as plain regions: drop them before handing tags
/// to it (CanonicalizeLocaleList has already applied the real aliases).
pub fn dt_locales(locales: &[String]) -> Vec<String> {
    locales
        .iter()
        .map(|l| {
            let mut out: Vec<&str> = Vec::new();
            let mut in_ext = false;
            for (i, p) in l.split('-').enumerate() {
                if p.len() == 1 {
                    in_ext = true;
                }
                if i > 0 && !in_ext && p.len() == 3 && p.bytes().all(|b| b.is_ascii_digit()) {
                    continue;
                }
                out.push(p);
            }
            out.join("-")
        })
        .collect()
}

fn dtf_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let locales = locale_list(vm, &a.arg(0))?;
    let opts = match get_options(vm, &a.arg(1), OptionsMode::Coerce)? {
        Some(o) => read_options_obj(vm, &o)?,
        None => dt::DateTimeFormatOptions::new(),
    };
    let f = dt_err(vm, dt::DateTimeFormat::new(&dt_locales(&locales), &opts))?;
    let o = alloc_instance(vm, a)?;
    write_slots(vm, &o, &locales, &opts, &f)?;
    let c = dtf_ctor_obj();
    legacy_construct(vm, a, &c, o)
}

fn write_slots(
    vm: &mut Vm,
    o: &Obj,
    locales: &[String],
    opts: &dt::DateTimeFormatOptions,
    f: &dt::DateTimeFormat,
) -> JsResult<()> {
    let ro = f.resolved_options();
    let s = |x: &str| Value::str(x);
    set_slot(o, "__dtf", Value::Bool(true));
    // datetime.rs maps numeric regions the original keeps (en-724): take the
    // base name from our own negotiation and the -u- keywords from dt.
    let base = resolve_locale(locales).base;
    let loc = match f.locale().find("-u-") {
        Some(i) => format!("{}{}", base, &f.locale()[i..]),
        None => base,
    };
    set_slot(o, "__dtf_locale", s(&loc));
    set_slot(o, "__dtf_ca", s(&resolved_str(&ro, "calendar").unwrap_or_default()));
    set_slot(o, "__dtf_nu", s(&resolved_str(&ro, "numberingSystem").unwrap_or_default()));
    set_slot(o, "__dtf_tz", s(&resolved_str(&ro, "timeZone").unwrap_or_default()));
    let styles = opts.date_style.is_some() || opts.time_style.is_some();
    if let Some(x) = opts.weekday {
        set_slot(o, "__dtf_weekday", s(x.as_str()));
    }
    if let Some(x) = opts.era {
        set_slot(o, "__dtf_era", s(x.as_str()));
    }
    if let Some(x) = opts.year {
        set_slot(o, "__dtf_year", s(x.as_str()));
    }
    if let Some(x) = opts.month {
        set_slot(o, "__dtf_month", s(x.as_str()));
    }
    if let Some(x) = opts.day {
        set_slot(o, "__dtf_day", s(x.as_str()));
    }
    if let Some(x) = opts.day_period {
        set_slot(o, "__dtf_dayperiod", s(x.as_str()));
    }
    if let Some(x) = opts.hour {
        set_slot(o, "__dtf_hour", s(x.as_str()));
    }
    if let Some(x) = opts.minute {
        set_slot(o, "__dtf_minute", s(x.as_str()));
    }
    if let Some(x) = opts.second {
        set_slot(o, "__dtf_second", s(x.as_str()));
    }
    if let Some(x) = opts.fractional_second_digits {
        set_slot(o, "__dtf_fracsec", Value::Num(x as f64));
    }
    if let Some(x) = opts.time_zone_name {
        set_slot(o, "__dtf_tzname", s(x.as_str()));
    }
    if styles {
        if let Some(ds) = opts.date_style {
            set_slot(o, "__dtf_datestyle", s(ds.as_str()));
        }
        if let Some(ts) = opts.time_style {
            set_slot(o, "__dtf_timestyle", s(ts.as_str()));
        }
        if let Some(ds) = opts.date_style {
            let (wd, mo, yr) = match ds.as_str() {
                "full" => (Some("long"), "long", "numeric"),
                "long" => (None, "long", "numeric"),
                "medium" => (None, "short", "numeric"),
                _ => (None, "numeric", "2-digit"),
            };
            if let Some(w) = wd {
                set_slot(o, "__dtfx_weekday", s(w));
            }
            set_slot(o, "__dtfx_month", s(mo));
            set_slot(o, "__dtfx_day", s("numeric"));
            set_slot(o, "__dtfx_year", s(yr));
        }
        if let Some(ts) = opts.time_style {
            set_slot(o, "__dtfx_hour", s("numeric"));
            set_slot(o, "__dtfx_minute", s("2-digit"));
            match ts.as_str() {
                "full" => {
                    set_slot(o, "__dtfx_second", s("2-digit"));
                    set_slot(o, "__dtfx_tzname", s("long"));
                }
                "long" => {
                    set_slot(o, "__dtfx_second", s("2-digit"));
                    set_slot(o, "__dtfx_tzname", s("short"));
                }
                "medium" => {
                    set_slot(o, "__dtfx_second", s("2-digit"));
                }
                _ => {}
            }
        }
    }
    // hour cycle (also computed when no hour is shown)
    let hc = match resolved_str(&ro, "hourCycle") {
        Some(h) => h,
        None => {
            let mut o2 = opts.clone();
            o2.date_style = None;
            o2.time_style = None;
            o2.weekday = None;
            o2.era = None;
            o2.year = None;
            o2.month = None;
            o2.day = None;
            o2.day_period = None;
            o2.minute = None;
            o2.second = None;
            o2.fractional_second_digits = None;
            o2.time_zone_name = None;
            o2.hour = opts.hour.or(Some(dt::NumericStyle::Numeric));
            match dt::DateTimeFormat::new(&dt_locales(locales), &o2) {
                Ok(f2) => resolved_str(&f2.resolved_options(), "hourCycle").unwrap_or_else(|| "h23".into()),
                Err(_) => "h23".to_string(),
            }
        }
    };
    let hour12 = hc == "h11" || hc == "h12";
    set_slot(o, "__dtf_hourcycle", s(&hc));
    set_slot(o, "__dtf_hour12", Value::Bool(hour12));
    let hour_shown = opts.hour.is_some() || opts.time_style.is_some();
    set_slot(o, "__dtf_hourshown", Value::Bool(hour_shown));
    if !styles {
        let any = opts.weekday.is_some()
            || opts.year.is_some()
            || opts.month.is_some()
            || opts.day.is_some()
            || opts.day_period.is_some()
            || opts.hour.is_some()
            || opts.minute.is_some()
            || opts.second.is_some()
            || opts.fractional_second_digits.is_some();
        if !any {
            set_slot(o, "__dtf_year", s("numeric"));
            set_slot(o, "__dtf_month", s("numeric"));
            set_slot(o, "__dtf_day", s("numeric"));
            set_slot(o, "__dtf_defaults", Value::Bool(true));
        }
    }
    let _ = vm;
    Ok(())
}

/// Rebuild the formatter from the slots.
fn formatter_from_slots(vm: &mut Vm, o: &Obj) -> JsResult<dt::DateTimeFormat> {
    formatter_from_slots_nu(vm, o, None)
}

/// Rebuild the formatter from the slots, optionally forcing the numbering
/// system (formatRange's string always uses latn digits in the original).
fn formatter_from_slots_nu(vm: &mut Vm, o: &Obj, nu: Option<&str>) -> JsResult<dt::DateTimeFormat> {
    let locale = slot_str(o, "__dtf_locale").unwrap_or_else(|| "en".to_string());
    let mut opts = dt::DateTimeFormatOptions::new();
    let set = |opts: &mut dt::DateTimeFormatOptions, slot_name: &str, opt: &str| -> Result<(), dt::DateTimeError> {
        if let Some(v) = slot_str(o, slot_name) {
            opts.set(opt, &v)?;
        }
        Ok(())
    };
    let r = (|| -> Result<(), dt::DateTimeError> {
        set(&mut opts, "__dtf_ca", "calendar")?;
        match nu {
            Some(n) => opts.set("numberingSystem", n)?,
            None => set(&mut opts, "__dtf_nu", "numberingSystem")?,
        }
        set(&mut opts, "__dtf_tz", "timeZone")?;
        set(&mut opts, "__dtf_weekday", "weekday")?;
        set(&mut opts, "__dtf_era", "era")?;
        set(&mut opts, "__dtf_year", "year")?;
        set(&mut opts, "__dtf_month", "month")?;
        set(&mut opts, "__dtf_day", "day")?;
        set(&mut opts, "__dtf_dayperiod", "dayPeriod")?;
        set(&mut opts, "__dtf_hour", "hour")?;
        set(&mut opts, "__dtf_minute", "minute")?;
        set(&mut opts, "__dtf_second", "second")?;
        if let Some(n) = slot_num(o, "__dtf_fracsec") {
            opts.set_fractional_second_digits(n)?;
        }
        set(&mut opts, "__dtf_tzname", "timeZoneName")?;
        set(&mut opts, "__dtf_datestyle", "dateStyle")?;
        set(&mut opts, "__dtf_timestyle", "timeStyle")?;
        if let Some(hc) = slot_str(o, "__dtf_hourcycle") {
            let hc = if ["h11", "h12", "h23", "h24"].contains(&hc.as_str()) { hc } else { "h23".to_string() };
            opts.set("hourCycle", &hc)?;
        }
        Ok(())
    })();
    dt_err(vm, r)?;
    let locales = dt_locales(&[locale]);
    dt_err(vm, dt::DateTimeFormat::new(&locales, &opts))
}

// ---------------------------------------------------------------------------
// Methods
// ---------------------------------------------------------------------------

/// The `date` argument of format/formatToParts: undefined is the epoch in
/// the original (not "now"), else ToNumber.
fn date_value(vm: &mut Vm, v: &Value) -> JsResult<f64> {
    match v {
        Value::Undefined => Ok(0.0),
        other => vm.to_number(other),
    }
}

fn this_dtf(vm: &mut Vm, this: &Value) -> JsResult<Obj> {
    branded_this(vm, this, "__dtf")
}

fn this_dtf_unwrap(vm: &mut Vm, this: &Value) -> JsResult<Obj> {
    let c = dtf_ctor_obj();
    unwrap_legacy(vm, this, "__dtf", &c)
}

fn bound_format(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.slot(0), "__dtf")?;
    let t = date_value(vm, &a.arg(0))?;
    let f = formatter_from_slots(vm, &o)?;
    let s = dt_err(vm, f.format(t))?;
    Ok(Value::str(&s))
}

fn dtf_format_getter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_dtf_unwrap(vm, &a.this)?;
    if let Some(b) = slot(&o, "__dtf_bound") {
        return Ok(b);
    }
    let f = vm.native_closure("", 1, bound_format, vec![Value::Obj(o.clone())]);
    set_slot(&o, "__dtf_bound", Value::Obj(f.clone()));
    Ok(Value::Obj(f))
}

fn parts_value(vm: &mut Vm, parts: &[dt::DateTimePart]) -> Value {
    let ps: Vec<Part> = parts.iter().map(|p| Part::new(p.kind, p.value.clone())).collect();
    parts_to_array(vm, &ps, &[])
}

fn dtf_format_to_parts(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_dtf(vm, &a.this)?;
    let t = date_value(vm, &a.arg(0))?;
    let f = formatter_from_slots(vm, &o)?;
    let parts = dt_err(vm, f.format_to_parts(t))?;
    Ok(parts_value(vm, &parts))
}

fn dtf_resolved_options(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_dtf_unwrap(vm, &a.this)?;
    let r = vm.new_object();
    let copy = |r: &Obj, key: &str, slot_name: &str| {
        if let Some(v) = slot(&o, slot_name) {
            if !v.is_undefined() {
                r.set_str(key, v, WEC);
            }
        }
    };
    copy(&r, "locale", "__dtf_locale");
    copy(&r, "calendar", "__dtf_ca");
    copy(&r, "numberingSystem", "__dtf_nu");
    copy(&r, "timeZone", "__dtf_tz");
    if slot(&o, "__dtf_hourshown").map(|v| v.truthy()).unwrap_or(false) {
        copy(&r, "hourCycle", "__dtf_hourcycle");
        copy(&r, "hour12", "__dtf_hour12");
    }
    copy(&r, "weekday", "__dtf_weekday");
    copy(&r, "era", "__dtf_era");
    copy(&r, "year", "__dtf_year");
    copy(&r, "month", "__dtf_month");
    copy(&r, "day", "__dtf_day");
    copy(&r, "dayPeriod", "__dtf_dayperiod");
    copy(&r, "hour", "__dtf_hour");
    copy(&r, "minute", "__dtf_minute");
    copy(&r, "second", "__dtf_second");
    copy(&r, "fractionalSecondDigits", "__dtf_fracsec");
    copy(&r, "timeZoneName", "__dtf_tzname");
    copy(&r, "dateStyle", "__dtf_datestyle");
    copy(&r, "timeStyle", "__dtf_timestyle");
    Ok(Value::Obj(r))
}

// ---------------------------------------------------------------------------
// Ranges
// ---------------------------------------------------------------------------

const SRC_SHARED: &str = "shared";
const SRC_START: &str = "startRange";
const SRC_END: &str = "endRange";

fn is_time_part(kind: &str) -> bool {
    matches!(kind, "hour" | "minute" | "second" | "fractionalSecond" | "dayPeriod")
}

fn is_date_part(kind: &str) -> bool {
    matches!(kind, "weekday" | "era" | "year" | "month" | "day" | "relatedYear" | "yearName")
}

/// FormatDateTimeRange: parts with their `source`.
///
/// Equal parts -> one shared formatted date.  When a time field differs,
/// the date fields must all be equal: the parts before the first time
/// field are shared and the rest is shown for both dates, else both dates
/// are shown in full.  When only date fields differ, a different year/era
/// or a numeric month shows both dates in full; textual months share the
/// parts before the first and after the last differing part.
fn range_parts(
    p1: &[dt::DateTimePart],
    p2: &[dt::DateTimePart],
    textual: bool,
) -> Vec<(dt::DateTimePart, &'static str)> {
    let mut out: Vec<(dt::DateTimePart, &'static str)> = Vec::new();
    if p1 == p2 {
        for p in p1 {
            out.push((p.clone(), SRC_SHARED));
        }
        return out;
    }
    let sep = dt::DateTimePart { kind: "literal", value: "\u{2009}\u{2013}\u{2009}".to_string() };
    let emit = |out: &mut Vec<(dt::DateTimePart, &'static str)>, pre: usize, post: usize| {
        for p in &p1[..pre] {
            out.push((p.clone(), SRC_SHARED));
        }
        for p in &p1[pre..p1.len() - post] {
            out.push((p.clone(), SRC_START));
        }
        out.push((sep.clone(), SRC_SHARED));
        for p in &p2[pre..p2.len() - post] {
            out.push((p.clone(), SRC_END));
        }
        for p in &p1[p1.len() - post..] {
            out.push((p.clone(), SRC_SHARED));
        }
    };
    if p1.len() != p2.len() || p1.iter().zip(p2).any(|(a, b)| a.kind != b.kind) {
        emit(&mut out, 0, 0);
        return out;
    }
    let diffs: Vec<usize> = (0..p1.len()).filter(|&i| p1[i].value != p2[i].value).collect();
    let time_diff = diffs.iter().any(|&i| is_time_part(p1[i].kind));
    let date_diff = diffs.iter().any(|&i| is_date_part(p1[i].kind));
    if time_diff {
        if date_diff {
            emit(&mut out, 0, 0);
        } else {
            let ft = p1.iter().position(|p| is_time_part(p.kind)).unwrap_or(0);
            let has_date = p1[..ft].iter().any(|p| is_date_part(p.kind));
            emit(&mut out, if has_date { ft } else { 0 }, 0);
        }
        return out;
    }
    let year_diff = diffs.iter().any(|&i| matches!(p1[i].kind, "year" | "era" | "relatedYear" | "yearName"));
    if !textual || year_diff || diffs.is_empty() {
        emit(&mut out, 0, 0);
        return out;
    }
    // a weekday is never part of the shared prefix
    let first = if p1.iter().any(|p| p.kind == "weekday") { 0 } else { diffs[0] };
    let last = *diffs.last().unwrap();
    emit(&mut out, first, p1.len() - last - 1);
    out
}

fn range_common(vm: &mut Vm, a: &Args, latn: bool) -> JsResult<Vec<(dt::DateTimePart, &'static str)>> {
    let o = this_dtf(vm, &a.this)?;
    let (s, e) = (a.arg(0), a.arg(1));
    if s.is_undefined() || e.is_undefined() {
        return vm.throw_type("formatRange requires two dates");
    }
    let x = vm.to_number(&s)?;
    let y = vm.to_number(&e)?;
    let f = formatter_from_slots(vm, &o)?;
    let mut p1 = dt_err(vm, f.format_to_parts(x))?;
    let mut p2 = dt_err(vm, f.format_to_parts(y))?;
    if latn {
        // formatRange's string has ASCII digits (separators stay localized)
        let nu = slot_str(&o, "__dtf_nu").unwrap_or_else(|| "latn".to_string());
        for p in p1.iter_mut().chain(p2.iter_mut()) {
            p.value = super::numdata::to_ascii_digits(&p.value, &nu);
        }
    }
    let month = slot_str(&o, "__dtf_month").or_else(|| slot_str(&o, "__dtfx_month"));
    // months written with digits only (zh/ja narrow) count as numeric
    let digits_only = |ps: &[dt::DateTimePart]| {
        ps.iter().any(|p| p.kind == "month" && p.value.chars().all(|c| c.is_numeric()))
    };
    let textual = matches!(month.as_deref(), Some("long" | "short" | "narrow")) && !digits_only(&p1) && !digits_only(&p2);
    Ok(range_parts(&p1, &p2, textual))
}

fn dtf_format_range(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let parts = range_common(vm, a, true)?;
    let s: String = parts.iter().map(|(p, _)| p.value.as_str()).collect();
    Ok(Value::str(&s))
}

fn dtf_format_range_to_parts(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let parts = range_common(vm, a, false)?;
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
