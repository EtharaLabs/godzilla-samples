// Intl (subset) and locale-sensitive helpers.

use crate::datetime as dt;
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let intl = vm.new_object();
    vm.def_method(&intl, "getCanonicalLocales", 1, get_canonical_locales);
    vm.def_method(&intl, "supportedValuesOf", 1, supported_values_of);
    // DateTimeFormat
    let dtfp = vm.new_object();
    let dtfc = vm.native_ctor("DateTimeFormat", 0, dtf_ctor, &dtfp);
    vm.def_getter(&dtfp, "format", dtf_format_getter);
    vm.def_method(&dtfp, "formatToParts", 1, dtf_format_to_parts);
    vm.def_method(&dtfp, "resolvedOptions", 0, dtf_resolved_options);
    vm.def_method(&dtfc, "supportedLocalesOf", 1, supported_locales_of);
    vm.set_tag(&dtfp, "Intl.DateTimeFormat");
    intl.set_prop(PropKey::from_str("DateTimeFormat"), Value::Obj(dtfc), WC);
    // NumberFormat (basic)
    let nfp = vm.new_object();
    let nfc = vm.native_ctor("NumberFormat", 0, nf_ctor, &nfp);
    vm.def_getter(&nfp, "format", nf_format_getter);
    vm.def_method(&nfp, "resolvedOptions", 0, nf_resolved_options);
    vm.def_method(&nfc, "supportedLocalesOf", 1, supported_locales_of);
    vm.set_tag(&nfp, "Intl.NumberFormat");
    intl.set_prop(PropKey::from_str("NumberFormat"), Value::Obj(nfc), WC);
    // Collator
    let cp = vm.new_object();
    let cc = vm.native_ctor("Collator", 0, collator_ctor, &cp);
    vm.def_getter(&cp, "compare", collator_compare_getter);
    vm.def_method(&cc, "supportedLocalesOf", 1, supported_locales_of);
    vm.set_tag(&cp, "Intl.Collator");
    intl.set_prop(PropKey::from_str("Collator"), Value::Obj(cc), WC);
    // PluralRules
    let pp = vm.new_object();
    let pc = vm.native_ctor("PluralRules", 0, plural_ctor, &pp);
    vm.def_method(&pp, "select", 1, plural_select);
    vm.set_tag(&pp, "Intl.PluralRules");
    intl.set_prop(PropKey::from_str("PluralRules"), Value::Obj(pc), WC);
    // ListFormat
    let lp = vm.new_object();
    let lc = vm.native_ctor("ListFormat", 0, list_ctor, &lp);
    vm.def_method(&lp, "format", 1, list_format);
    vm.set_tag(&lp, "Intl.ListFormat");
    intl.set_prop(PropKey::from_str("ListFormat"), Value::Obj(lc), WC);
    // RelativeTimeFormat
    let rp = vm.new_object();
    let rc = vm.native_ctor("RelativeTimeFormat", 0, rtf_ctor, &rp);
    vm.def_method(&rp, "format", 2, rtf_format);
    vm.set_tag(&rp, "Intl.RelativeTimeFormat");
    intl.set_prop(PropKey::from_str("RelativeTimeFormat"), Value::Obj(rc), WC);
    vm.set_tag(&intl, "Intl");
    vm.def_global("Intl", Value::Obj(intl));
}

pub fn throw_dt_error<T>(vm: &mut Vm, e: dt::DateTimeError) -> JsResult<T> {
    match e.kind {
        dt::ErrorKind::Range => vm.throw_range(e.message),
        dt::ErrorKind::Type => vm.throw_type(e.message),
    }
}

pub fn locale_list(vm: &mut Vm, v: &Value) -> JsResult<Vec<String>> {
    let raw: Vec<String> = match v {
        Value::Undefined => Vec::new(),
        Value::Null => return vm.throw_type("Cannot convert null to object"),
        Value::Str(s) => vec![s.to_rust_string()],
        Value::Obj(o) => {
            let vals = crate::builtins::array::array_like_to_vec(vm, &Value::Obj(o.clone()))?;
            let mut out = Vec::new();
            for x in vals {
                match x {
                    Value::Str(s) => out.push(s.to_rust_string()),
                    Value::Obj(_) => out.push(vm.to_string(&x)?.to_rust_string()),
                    _ => return vm.throw_type("locale must be a string or object"),
                }
            }
            out
        }
        _ => {
            let o = vm.to_object(v)?;
            let vals = crate::builtins::array::array_like_to_vec(vm, &Value::Obj(o))?;
            let mut out = Vec::new();
            for x in vals {
                out.push(vm.to_string(&x)?.to_rust_string());
            }
            out
        }
    };
    match dt::canonicalize_locale_list(&raw) {
        Ok(l) => Ok(l),
        Err(e) => throw_dt_error(vm, e),
    }
}

pub fn read_dtf_options(vm: &mut Vm, v: &Value) -> JsResult<dt::DateTimeFormatOptions> {
    let mut o = dt::DateTimeFormatOptions::new();
    let obj = match v {
        Value::Undefined => return Ok(o),
        Value::Obj(ob) => ob.clone(),
        Value::Null => return vm.throw_type("options must be an object"),
        _ => return vm.throw_type("options must be an object"),
    };
    let order = [
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
    for name in order {
        let val = vm.get_str(&obj, name)?;
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

fn get_canonical_locales(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let l = locale_list(vm, &a.arg(0))?;
    let v: Vec<Value> = l.into_iter().map(|s| Value::str(&s)).collect();
    Ok(Value::Obj(vm.new_array(v)))
}

fn supported_locales_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let l = locale_list(vm, &a.arg(0))?;
    let r = match dt::supported_locales_of(&l) {
        Ok(r) => r,
        Err(e) => return throw_dt_error(vm, e),
    };
    let v: Vec<Value> = r.into_iter().map(|s| Value::str(&s)).collect();
    Ok(Value::Obj(vm.new_array(v)))
}

fn supported_values_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let k = vm.to_string(&a.arg(0))?.to_rust_string();
    let vals: Vec<&str> = match k.as_str() {
        "calendar" => vec!["buddhist", "gregory", "iso8601", "japanese", "roc"],
        "collation" => vec!["default"],
        "currency" => vec!["EUR", "GBP", "JPY", "USD"],
        "numberingSystem" => vec!["arab", "latn"],
        "timeZone" => vec!["UTC"],
        "unit" => vec!["byte", "kilometer", "meter", "second"],
        _ => return vm.throw_range(format!("invalid key: {}", k)),
    };
    let v: Vec<Value> = vals.into_iter().map(Value::str).collect();
    Ok(Value::Obj(vm.new_array(v)))
}

struct DtfData(dt::DateTimeFormat);

fn dtf_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let locales = locale_list(vm, &a.arg(0))?;
    let opts = read_dtf_options(vm, &a.arg(1))?;
    let f = match dt::DateTimeFormat::new(&locales, &opts) {
        Ok(f) => f,
        Err(e) => return throw_dt_error(vm, e),
    };
    let nt = a.new_target.clone().or_else(|| Some(a.callee.clone()));
    let fallback = vm.get(a.callee, &vm.intr.key_prototype.clone(), &Value::Obj(a.callee.clone()))?.as_obj().cloned().unwrap();
    let proto = vm.proto_from_nt(&nt, &fallback)?;
    Ok(Value::Obj(Obj::new(Some(proto), ObjKind::Host(Box::new(DtfData(f))))))
}

fn with_dtf<R>(vm: &mut Vm, v: &Value, f: impl FnOnce(&dt::DateTimeFormat) -> R) -> JsResult<R> {
    if let Value::Obj(o) = v {
        if let ObjKind::Host(h) = &o.borrow().kind {
            if let Some(d) = h.downcast_ref::<DtfData>() {
                return Ok(f(&d.0));
            }
        }
    }
    vm.throw_type("Method Intl.DateTimeFormat.prototype.format called on incompatible receiver")
}

fn date_arg(vm: &mut Vm, v: &Value) -> JsResult<f64> {
    match v {
        Value::Undefined => Ok(dt::now_ms()),
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::Date(_)) => match &o.borrow().kind {
            ObjKind::Date(t) => Ok(*t),
            _ => unreachable!(),
        },
        other => vm.to_number(other),
    }
}

fn dtf_bound_format(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let fmt = a.slot(0);
    let t = date_arg(vm, &a.arg(0))?;
    let r = with_dtf(vm, &fmt, |f| f.format(t))?;
    match r {
        Ok(s) => Ok(Value::str(&s)),
        Err(e) => throw_dt_error(vm, e),
    }
}

fn dtf_format_getter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_dtf(vm, &a.this, |_| ())?;
    let f = vm.native_closure("", 1, dtf_bound_format, vec![a.this.clone()]);
    Ok(Value::Obj(f))
}

fn dtf_format_to_parts(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t = date_arg(vm, &a.arg(0))?;
    let r = with_dtf(vm, &a.this, |f| f.format_to_parts(t))?;
    match r {
        Ok(parts) => {
            let mut out = Vec::new();
            for p in parts {
                let o = vm.new_object();
                o.set_str("type", Value::str(p.kind), WEC);
                o.set_str("value", Value::str(&p.value), WEC);
                out.push(Value::Obj(o));
            }
            Ok(Value::Obj(vm.new_array(out)))
        }
        Err(e) => throw_dt_error(vm, e),
    }
}

fn dtf_resolved_options(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = with_dtf(vm, &a.this, |f| f.resolved_options())?;
    let o = vm.new_object();
    for (k, v) in r {
        let val = match v {
            dt::ResolvedValue::Str(s) => Value::str(&s),
            dt::ResolvedValue::Bool(b) => Value::Bool(b),
            dt::ResolvedValue::Number(n) => Value::Num(n as f64),
        };
        o.set_str(k, val, WEC);
    }
    Ok(Value::Obj(o))
}

// ---------------- numbers ----------------

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

#[derive(Clone)]
pub struct NumFmt {
    pub locale: String,
    pub style: String,
    pub currency: Option<String>,
    pub min_int: u32,
    pub min_frac: u32,
    pub max_frac: u32,
    pub grouping: bool,
    pub unit: Option<String>,
}

fn locale_seps(locale: &str) -> (&'static str, &'static str) {
    let lang = locale.split('-').next().unwrap_or("en");
    match lang {
        "de" | "es" | "it" | "nl" | "pt" | "id" | "tr" | "da" => (".", ","),
        "fr" => ("\u{202f}", ","),
        "ru" | "pl" | "cs" | "sv" | "fi" | "nb" | "uk" => ("\u{a0}", ","),
        _ => (",", "."),
    }
}

pub fn format_number(nf: &NumFmt, x: f64) -> String {
    if x.is_nan() {
        return "NaN".to_string();
    }
    let (gsep, dsep) = locale_seps(&nf.locale);
    let neg = x < 0.0 || (x == 0.0 && x.is_sign_negative() && false);
    let mut v = x.abs();
    if nf.style == "percent" {
        v *= 100.0;
    }
    if v.is_infinite() {
        return format!("{}∞", if neg { "-" } else { "" });
    }
    let s = crate::numconv::to_fixed(v, nf.max_frac);
    let (int_part, frac_part) = match s.find('.') {
        Some(p) => (s[..p].to_string(), s[p + 1..].to_string()),
        None => (s.clone(), String::new()),
    };
    let mut frac = frac_part.trim_end_matches('0').to_string();
    while (frac.len() as u32) < nf.min_frac {
        frac.push('0');
    }
    let mut int_s = int_part;
    while (int_s.len() as u32) < nf.min_int {
        int_s.insert(0, '0');
    }
    let grouped = if nf.grouping {
        if nf.locale.starts_with("en-IN") || nf.locale.starts_with("hi") {
            // Indian grouping: last 3 then groups of 2
            let n = int_s.len();
            if n <= 3 {
                int_s.clone()
            } else {
                let (head, tail) = int_s.split_at(n - 3);
                let mut out = String::new();
                let hn = head.len();
                for (i, c) in head.chars().enumerate() {
                    if i > 0 && (hn - i) % 2 == 0 {
                        out.push_str(gsep);
                    }
                    out.push(c);
                }
                format!("{}{}{}", out, gsep, tail)
            }
        } else if nf.locale.starts_with("es") && int_s.len() <= 4 {
            int_s.clone()
        } else {
            group_digits_str(&int_s, gsep)
        }
    } else {
        int_s.clone()
    };
    let mut num = grouped;
    if !frac.is_empty() {
        num.push_str(dsep);
        num.push_str(&frac);
    }
    let sign = if neg && x != 0.0 { "-" } else { "" };
    match nf.style.as_str() {
        "percent" => format!("{}{}%", sign, num),
        "currency" => {
            let cur = nf.currency.clone().unwrap_or_default();
            let sym = match cur.as_str() {
                "USD" => "$",
                "EUR" => "€",
                "GBP" => "£",
                "JPY" => "¥",
                "INR" => "₹",
                "CNY" => "CN¥",
                _ => cur.as_str(),
            }
            .to_string();
            let lang = nf.locale.split('-').next().unwrap_or("en");
            if matches!(lang, "de" | "fr" | "es" | "it" | "nl" | "pt" | "ru" | "pl") {
                format!("{}{}\u{a0}{}", sign, num, sym)
            } else {
                format!("{}{}{}", sign, sym, num)
            }
        }
        "unit" => {
            let u = nf.unit.clone().unwrap_or_default();
            let short = match u.as_str() {
                "kilometer" => "km",
                "meter" => "m",
                "second" => "sec",
                "byte" => "byte",
                "kilogram" => "kg",
                "celsius" => "°C",
                "percent" => "%",
                other => other,
            };
            format!("{}{} {}", sign, num, short)
        }
        _ => format!("{}{}", sign, num),
    }
}

pub fn read_nf_options(vm: &mut Vm, locales: &Value, opts: &Value) -> JsResult<NumFmt> {
    let ll = locale_list(vm, locales)?;
    let locale = ll.first().cloned().unwrap_or_else(|| "en".to_string());
    let mut nf = NumFmt { locale, style: "decimal".into(), currency: None, min_int: 1, min_frac: 0, max_frac: 3, grouping: true, unit: None };
    if let Value::Obj(o) = opts {
        let st = vm.get_str(o, "style")?;
        if !st.is_undefined() {
            nf.style = vm.to_string(&st)?.to_rust_string();
        }
        let cur = vm.get_str(o, "currency")?;
        if !cur.is_undefined() {
            nf.currency = Some(vm.to_string(&cur)?.to_rust_string().to_uppercase());
        }
        if nf.style == "currency" {
            if nf.currency.is_none() {
                return vm.throw_type("Currency code is required with currency style.");
            }
            let c = nf.currency.clone().unwrap();
            let d = if c == "JPY" || c == "KRW" { 0 } else { 2 };
            nf.min_frac = d;
            nf.max_frac = d;
        }
        if nf.style == "percent" {
            nf.max_frac = 0;
        }
        let unit = vm.get_str(o, "unit")?;
        if !unit.is_undefined() {
            nf.unit = Some(vm.to_string(&unit)?.to_rust_string());
        }
        let mi = vm.get_str(o, "minimumIntegerDigits")?;
        if !mi.is_undefined() {
            nf.min_int = vm.to_number(&mi)? as u32;
        }
        let mnf = vm.get_str(o, "minimumFractionDigits")?;
        let mxf = vm.get_str(o, "maximumFractionDigits")?;
        if !mnf.is_undefined() {
            nf.min_frac = vm.to_number(&mnf)? as u32;
            if nf.max_frac < nf.min_frac {
                nf.max_frac = nf.min_frac;
            }
        }
        if !mxf.is_undefined() {
            nf.max_frac = vm.to_number(&mxf)? as u32;
            if nf.min_frac > nf.max_frac {
                nf.min_frac = nf.max_frac;
            }
        }
        let g = vm.get_str(o, "useGrouping")?;
        if !g.is_undefined() {
            nf.grouping = g.truthy();
        }
    }
    Ok(nf)
}

pub fn number_to_locale_string(vm: &mut Vm, x: f64, locales: &Value, opts: &Value) -> JsResult<Value> {
    let nf = read_nf_options(vm, locales, opts)?;
    Ok(Value::str(&format_number(&nf, x)))
}

struct NfData(NumFmt);

fn nf_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nf = read_nf_options(vm, &a.arg(0), &a.arg(1))?;
    let nt = a.new_target.clone().or_else(|| Some(a.callee.clone()));
    let fallback = vm.get(a.callee, &vm.intr.key_prototype.clone(), &Value::Obj(a.callee.clone()))?.as_obj().cloned().unwrap();
    let proto = vm.proto_from_nt(&nt, &fallback)?;
    Ok(Value::Obj(Obj::new(Some(proto), ObjKind::Host(Box::new(NfData(nf))))))
}

fn get_nf(vm: &mut Vm, v: &Value) -> JsResult<NumFmt> {
    if let Value::Obj(o) = v {
        if let ObjKind::Host(h) = &o.borrow().kind {
            if let Some(d) = h.downcast_ref::<NfData>() {
                return Ok(d.0.clone());
            }
        }
    }
    vm.throw_type("Method Intl.NumberFormat.prototype.format called on incompatible receiver")
}

fn nf_bound_format(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nf = get_nf(vm, &a.slot(0))?;
    let x = match vm.to_numeric(&a.arg(0))? {
        Value::BigInt(b) => b.to_f64(),
        Value::Num(n) => n,
        _ => f64::NAN,
    };
    Ok(Value::str(&format_number(&nf, x)))
}

fn nf_format_getter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    get_nf(vm, &a.this)?;
    Ok(Value::Obj(vm.native_closure("", 1, nf_bound_format, vec![a.this.clone()])))
}

fn nf_resolved_options(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nf = get_nf(vm, &a.this)?;
    let o = vm.new_object();
    o.set_str("locale", Value::str(&nf.locale), WEC);
    o.set_str("numberingSystem", Value::str("latn"), WEC);
    o.set_str("style", Value::str(&nf.style), WEC);
    if let Some(c) = &nf.currency {
        o.set_str("currency", Value::str(c), WEC);
    }
    o.set_str("minimumIntegerDigits", Value::Num(nf.min_int as f64), WEC);
    o.set_str("minimumFractionDigits", Value::Num(nf.min_frac as f64), WEC);
    o.set_str("maximumFractionDigits", Value::Num(nf.max_frac as f64), WEC);
    o.set_str("useGrouping", Value::str("auto"), WEC);
    o.set_str("notation", Value::str("standard"), WEC);
    o.set_str("signDisplay", Value::str("auto"), WEC);
    o.set_str("roundingIncrement", Value::Num(1.0), WEC);
    o.set_str("roundingMode", Value::str("halfExpand"), WEC);
    o.set_str("roundingPriority", Value::str("auto"), WEC);
    o.set_str("trailingZeroDisplay", Value::str("auto"), WEC);
    Ok(Value::Obj(o))
}

// ---------------- Collator ----------------

struct CollatorData {
    sensitivity: u8,
    numeric: bool,
}

fn collator_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let _ = locale_list(vm, &a.arg(0))?;
    let mut sens = 3u8;
    let mut numeric = false;
    if let Value::Obj(o) = a.arg(1) {
        let s = vm.get_str(&o, "sensitivity")?;
        if let Value::Str(x) = s {
            sens = match x.to_rust_string().as_str() {
                "base" => 0,
                "accent" => 1,
                "case" => 2,
                _ => 3,
            };
        }
        numeric = vm.get_str(&o, "numeric")?.truthy();
    }
    let nt = a.new_target.clone().or_else(|| Some(a.callee.clone()));
    let fallback = vm.get(a.callee, &vm.intr.key_prototype.clone(), &Value::Obj(a.callee.clone()))?.as_obj().cloned().unwrap();
    let proto = vm.proto_from_nt(&nt, &fallback)?;
    Ok(Value::Obj(Obj::new(Some(proto), ObjKind::Host(Box::new(CollatorData { sensitivity: sens, numeric })))))
}

fn collator_compare_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (sens, numeric) = match &a.slot(0) {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Host(h) => match h.downcast_ref::<CollatorData>() {
                Some(c) => (c.sensitivity, c.numeric),
                None => (3, false),
            },
            _ => (3, false),
        },
        _ => (3, false),
    };
    let x = vm.to_string(&a.arg(0))?;
    let y = vm.to_string(&a.arg(1))?;
    if numeric {
        let xs = x.to_rust_string();
        let ys = y.to_rust_string();
        if let (Ok(xn), Ok(yn)) = (xs.parse::<f64>(), ys.parse::<f64>()) {
            return Ok(Value::Num(if xn < yn { -1.0 } else if xn > yn { 1.0 } else { 0.0 }));
        }
    }
    Ok(Value::Num(crate::builtins::string::locale_cmp(x.units(), y.units(), sens) as f64))
}

fn collator_compare_getter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Obj(vm.native_closure("", 2, collator_compare_fn, vec![a.this.clone()])))
}

// ---------------- PluralRules ----------------

struct PluralData {
    ordinal: bool,
}

fn plural_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut ordinal = false;
    if let Value::Obj(o) = a.arg(1) {
        let t = vm.get_str(&o, "type")?;
        if let Value::Str(s) = t {
            ordinal = s.eq_str("ordinal");
        }
    }
    let nt = a.new_target.clone().or_else(|| Some(a.callee.clone()));
    let fallback = vm.get(a.callee, &vm.intr.key_prototype.clone(), &Value::Obj(a.callee.clone()))?.as_obj().cloned().unwrap();
    let proto = vm.proto_from_nt(&nt, &fallback)?;
    Ok(Value::Obj(Obj::new(Some(proto), ObjKind::Host(Box::new(PluralData { ordinal })))))
}

fn plural_select(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ordinal = match &a.this {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Host(h) => h.downcast_ref::<PluralData>().map(|p| p.ordinal).unwrap_or(false),
            _ => false,
        },
        _ => false,
    };
    let n = vm.to_number(&a.arg(0))?;
    if ordinal {
        return Ok(Value::str("other"));
    }
    Ok(Value::str(if n == 1.0 { "one" } else { "other" }))
}

// ---------------- ListFormat ----------------

struct ListData {
    kind: String,
    style: String,
}

fn list_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut kind = "conjunction".to_string();
    let mut style = "long".to_string();
    if let Value::Obj(o) = a.arg(1) {
        let t = vm.get_str(&o, "type")?;
        if let Value::Str(s) = t {
            kind = s.to_rust_string();
        }
        let s = vm.get_str(&o, "style")?;
        if let Value::Str(x) = s {
            style = x.to_rust_string();
        }
    }
    let nt = a.new_target.clone().or_else(|| Some(a.callee.clone()));
    let fallback = vm.get(a.callee, &vm.intr.key_prototype.clone(), &Value::Obj(a.callee.clone()))?.as_obj().cloned().unwrap();
    let proto = vm.proto_from_nt(&nt, &fallback)?;
    Ok(Value::Obj(Obj::new(Some(proto), ObjKind::Host(Box::new(ListData { kind, style })))))
}

fn list_format(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (kind, style) = match &a.this {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Host(h) => match h.downcast_ref::<ListData>() {
                Some(l) => (l.kind.clone(), l.style.clone()),
                None => ("conjunction".into(), "long".into()),
            },
            _ => ("conjunction".into(), "long".into()),
        },
        _ => ("conjunction".into(), "long".into()),
    };
    let items = vm.iterate_to_vec(&a.arg(0))?;
    let mut strs = Vec::new();
    for i in items {
        strs.push(vm.to_string(&i)?.to_rust_string());
    }
    let word = match (kind.as_str(), style.as_str()) {
        ("disjunction", _) => " or ",
        ("unit", "narrow") => " ",
        ("unit", _) => ", ",
        (_, "short") | (_, "narrow") => if style == "narrow" { ", " } else { " & " },
        _ => " and ",
    };
    let r = match strs.len() {
        0 => String::new(),
        1 => strs[0].clone(),
        2 => {
            if kind == "unit" {
                format!("{}{}{}", strs[0], word, strs[1])
            } else {
                format!("{}{}{}", strs[0], word, strs[1])
            }
        }
        n => {
            let head = strs[..n - 1].join(", ");
            if kind == "unit" {
                format!("{}{}{}", head, word, strs[n - 1])
            } else {
                format!("{},{}{}", head, word, strs[n - 1])
            }
        }
    };
    Ok(Value::str(&r))
}

// ---------------- RelativeTimeFormat ----------------

struct RtfData {
    numeric_auto: bool,
}

fn rtf_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut auto = false;
    if let Value::Obj(o) = a.arg(1) {
        let n = vm.get_str(&o, "numeric")?;
        if let Value::Str(s) = n {
            auto = s.eq_str("auto");
        }
    }
    let nt = a.new_target.clone().or_else(|| Some(a.callee.clone()));
    let fallback = vm.get(a.callee, &vm.intr.key_prototype.clone(), &Value::Obj(a.callee.clone()))?.as_obj().cloned().unwrap();
    let proto = vm.proto_from_nt(&nt, &fallback)?;
    Ok(Value::Obj(Obj::new(Some(proto), ObjKind::Host(Box::new(RtfData { numeric_auto: auto })))))
}

fn rtf_format(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let auto = match &a.this {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Host(h) => h.downcast_ref::<RtfData>().map(|r| r.numeric_auto).unwrap_or(false),
            _ => false,
        },
        _ => false,
    };
    let v = vm.to_number(&a.arg(0))?;
    let unit = vm.to_string(&a.arg(1))?.to_rust_string();
    let u = unit.trim_end_matches('s').to_string();
    if auto {
        let special = match (u.as_str(), v as i64) {
            ("day", -1) => Some("yesterday"),
            ("day", 0) => Some("today"),
            ("day", 1) => Some("tomorrow"),
            ("year", -1) => Some("last year"),
            ("year", 0) => Some("this year"),
            ("year", 1) => Some("next year"),
            ("month", -1) => Some("last month"),
            ("month", 0) => Some("this month"),
            ("month", 1) => Some("next month"),
            ("week", -1) => Some("last week"),
            ("week", 0) => Some("this week"),
            ("week", 1) => Some("next week"),
            ("second", 0) => Some("now"),
            _ => None,
        };
        if let Some(s) = special {
            if v.fract() == 0.0 {
                return Ok(Value::str(s));
            }
        }
    }
    let n = v.abs();
    let ns = crate::numconv::number_to_string(n);
    let plural = if n == 1.0 { u.clone() } else { format!("{}s", u) };
    let r = if v < 0.0 || (v == 0.0 && v.is_sign_negative()) { format!("{} {} ago", ns, plural) } else { format!("in {} {}", ns, plural) };
    Ok(Value::str(&r))
}
