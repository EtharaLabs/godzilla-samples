//! Intl.Locale and likely subtags.
//!
//! Slots (own data properties, in this order): `__locale_tag` (canonical
//! tag), `__locale_basename`, `__locale_language`, `__locale_script`,
//! `__locale_region`, `__locale_variants` (joined with "-") when present,
//! then one `__locale_<key>` per -u- keyword (sorted by key; "" for a
//! keyword without value).  Getters and methods require an object
//! (`TypeError: not a Locale`) with an own string `__locale_tag`
//! (`TypeError: receiver is not an Intl.Locale`); `baseName` / `language`
//! additionally need their string slots.
//!
//! The constructor canonicalises the tag, applies the options (language,
//! script, region, variants, calendar, collation, firstDayOfWeek, hourCycle,
//! caseFirst, numeric, numberingSystem -- read and validated in this order)
//! and canonicalises again (so `drw` -> `prs` -> `fa-AF`).
//!
//! `maximize` / `minimize` use the original's likely-subtags data
//! (`locale_data.rs`, CLDR-based, extracted from the original).  The
//! `get*` info methods are trivial in the original: the -u- value or
//! `gregory` / `default` / `h23` / `latn`, time zones `["UTC"]` when a region
//! is present, text direction always `ltr`, week info
//! `{firstDay: fw (mon=1..sun=7, default 1), weekend: [6, 7]}`.

use super::*;

#[path = "locale_data.rs"]
mod data;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    let members = [
        Member::Getter("baseName", get_base_name),
        Member::Getter("language", get_language),
        Member::Getter("script", get_script),
        Member::Getter("region", get_region),
        Member::Getter("variants", get_variants),
        Member::Getter("calendar", get_calendar),
        Member::Getter("collation", get_collation),
        Member::Getter("hourCycle", get_hour_cycle),
        Member::Getter("caseFirst", get_case_first),
        Member::Getter("firstDayOfWeek", get_first_day_of_week),
        Member::Getter("numberingSystem", get_numbering_system),
        Member::Getter("numeric", get_numeric),
        Member::Method("toString", 0, locale_to_string),
        Member::Method("maximize", 0, locale_maximize),
        Member::Method("minimize", 0, locale_minimize),
        Member::Method("getCalendars", 0, get_calendars),
        Member::Method("getCollations", 0, get_collations),
        Member::Method("getHourCycles", 0, get_hour_cycles),
        Member::Method("getNumberingSystems", 0, get_numbering_systems),
        Member::Method("getTimeZones", 0, get_time_zones),
        Member::Method("getTextInfo", 0, get_text_info),
        Member::Method("getWeekInfo", 0, get_week_info),
    ];
    let (_, proto) = define_class(vm, intl, "Locale", 1, locale_ctor, &members, false);
    LOCALE_PROTO.with(|p| *p.borrow_mut() = Some(proto));
}

thread_local! {
    static LOCALE_PROTO: std::cell::RefCell<Option<Obj>> = std::cell::RefCell::new(None);
}

// ============================================================================
// Likely subtags
// ============================================================================

fn lookup3(table: &'static [(&'static str, &'static str, &'static str)], key: &str) -> Option<(&'static str, &'static str)> {
    table.binary_search_by(|e| e.0.cmp(key)).ok().map(|i| (table[i].1, table[i].2))
}

fn lookup2(table: &'static [(&'static str, &'static str)], key: &str) -> Option<&'static str> {
    table.binary_search_by(|e| e.0.cmp(key)).ok().map(|i| table[i].1)
}

/// Add Likely Subtags: the (language, script, region) the original's
/// `maximize` produces, or None when nothing is known for the language (the
/// tag is then left unchanged).
pub fn maximize_fields(lang: &str, script: Option<&str>, region: Option<&str>) -> Option<(String, String, String)> {
    let own = |l: &str, s: &str, r: &str| Some((l.to_string(), s.to_string(), r.to_string()));
    if lang == "und" {
        return match (script, region) {
            (Some(s), Some(r)) => {
                let l = if let Some(l) = lookup2(data::UND_SCRIPT_REGION, &format!("{}-{}", s, r)) {
                    l
                } else if let Some((l, _)) = lookup3(data::UND_REGION, r) {
                    l
                } else if let Some((l, _)) = lookup3(data::UND_SCRIPT, s) {
                    l
                } else {
                    "en"
                };
                own(l, s, r)
            }
            (Some(s), None) => match lookup3(data::UND_SCRIPT, s) {
                Some((l, r)) => own(l, s, r),
                None => own("en", s, "US"),
            },
            (None, Some(r)) => match lookup3(data::UND_REGION, r) {
                Some((l, s)) => own(l, s, r),
                None => own("en", "Latn", r),
            },
            (None, None) => own("en", "Latn", "US"),
        };
    }
    match (script, region) {
        (Some(s), Some(r)) => own(lang, s, r),
        (None, Some(r)) => {
            if let Some(s) = lookup2(data::LANG_REGION, &format!("{}-{}", lang, r)) {
                return own(lang, s, r);
            }
            lookup3(data::LANG, lang).and_then(|(s, _)| own(lang, s, r))
        }
        (Some(s), None) => {
            if let Some(r) = lookup2(data::LANG_SCRIPT, &format!("{}-{}", lang, s)) {
                return own(lang, s, r);
            }
            if let Some((_, r)) = lookup3(data::LANG, lang) {
                return own(lang, s, r);
            }
            // unknown language: the region of und-<script>
            lookup3(data::UND_SCRIPT, s).and_then(|(_, r)| own(lang, s, r))
        }
        (None, None) => lookup3(data::LANG, lang).and_then(|(s, r)| own(lang, s, r)),
    }
}

/// Remove Likely Subtags (favouring the region): (language, script, region).
pub fn minimize_fields(
    lang: &str,
    script: Option<&str>,
    region: Option<&str>,
) -> (String, Option<String>, Option<String>) {
    let max = match maximize_fields(lang, script, region) {
        Some(m) => m,
        None => return (lang.to_string(), script.map(|s| s.to_string()), region.map(|s| s.to_string())),
    };
    let (ml, ms, mr) = (max.0.as_str(), max.1.as_str(), max.2.as_str());
    if maximize_fields(ml, None, None).as_ref() == Some(&max) {
        return (ml.to_string(), None, None);
    }
    if maximize_fields(ml, None, Some(mr)).as_ref() == Some(&max) {
        return (ml.to_string(), None, Some(mr.to_string()));
    }
    if maximize_fields(ml, Some(ms), None).as_ref() == Some(&max) {
        return (ml.to_string(), Some(ms.to_string()), None);
    }
    (ml.to_string(), Some(ms.to_string()), Some(mr.to_string()))
}

// ============================================================================
// Construction
// ============================================================================

fn locale_proto(vm: &Vm) -> Obj {
    LOCALE_PROTO.with(|p| p.borrow().clone()).unwrap_or_else(|| vm.intr.object_proto.clone())
}

/// Write the slots of a Locale object for the (canonical) tag.
fn write_slots(o: &Obj, t: &LangTag) {
    set_slot(o, "__locale_tag", Value::str(&t.to_canonical_string()));
    set_slot(o, "__locale_basename", Value::str(&t.base_name()));
    set_slot(o, "__locale_language", Value::str(&t.language));
    if let Some(s) = &t.script {
        set_slot(o, "__locale_script", Value::str(s));
    }
    if let Some(r) = &t.region {
        set_slot(o, "__locale_region", Value::str(r));
    }
    if !t.variants.is_empty() {
        set_slot(o, "__locale_variants", Value::str(&t.variants.join("-")));
    }
    for (k, v) in &t.u_keywords {
        set_slot(o, &format!("__locale_{}", k), Value::str(v));
    }
}

/// A new Intl.Locale (intrinsic prototype) for a canonical tag.
fn new_locale_object(vm: &mut Vm, t: &LangTag) -> Value {
    let o = Obj::new(Some(locale_proto(vm)), ObjKind::Ordinary);
    write_slots(&o, t);
    Value::Obj(o)
}

fn is_language_subtag(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_alphabetic()) && (s.len() == 2 || s.len() == 3 || (5..=8).contains(&s.len()))
}

fn is_variant_subtag(s: &str) -> bool {
    s.bytes().all(|b| b.is_ascii_alphanumeric())
        && ((5..=8).contains(&s.len()) || (s.len() == 4 && s.as_bytes()[0].is_ascii_digit()))
}

fn locale_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_new(vm, a, "Locale")?;
    let tag_v = a.arg(0);
    let tag = match &tag_v {
        Value::Str(s) => s.to_rust_string(),
        Value::Obj(o) => match locale_object_tag(o) {
            Some(t) => t,
            None => vm.to_string(&tag_v)?.to_rust_string(),
        },
        _ => return vm.throw_type("locale tag must be a string or Locale"),
    };
    let mut t = match parse_tag(&tag) {
        Some(t) => t,
        None => return vm.throw_range(format!("invalid language tag: {}", tag)),
    };
    let opts = get_options(vm, &a.arg(1), OptionsMode::Coerce)?;
    // ApplyOptionsToTag
    if let Some(l) = get_opt_str(vm, &opts, "language", &[])? {
        if !is_language_subtag(&l) {
            return vm.throw_range("invalid language option");
        }
        t.language = l.to_ascii_lowercase();
    }
    if let Some(s) = get_opt_str(vm, &opts, "script", &[])? {
        if !(s.len() == 4 && s.bytes().all(|b| b.is_ascii_alphabetic())) {
            return vm.throw_range("invalid script option");
        }
        t.script = Some(s[..1].to_ascii_uppercase() + &s[1..].to_ascii_lowercase());
    }
    if let Some(r) = get_opt_str(vm, &opts, "region", &[])? {
        let ok = (r.len() == 2 && r.bytes().all(|b| b.is_ascii_alphabetic()))
            || (r.len() == 3 && r.bytes().all(|b| b.is_ascii_digit()));
        if !ok {
            return vm.throw_range("invalid region option");
        }
        t.region = Some(r.to_ascii_uppercase());
    }
    if let Some(v) = get_opt_str(vm, &opts, "variants", &[])? {
        let parts: Vec<&str> = v.split('-').collect();
        if v.is_empty() || !parts.iter().all(|p| is_variant_subtag(p)) {
            return vm.throw_range("invalid variants option");
        }
        t.variants = parts.iter().map(|p| p.to_ascii_lowercase()).collect();
    }
    // Unicode extension keywords
    let mut kws: Vec<(&str, String)> = Vec::new();
    if let Some(c) = get_opt_str(vm, &opts, "calendar", &[])? {
        if !is_unicode_type(&c) {
            return vm.throw_range(format!("invalid calendar option: {}", c));
        }
        kws.push(("ca", c));
    }
    if let Some(c) = get_opt_str(vm, &opts, "collation", &[])? {
        if !is_unicode_type(&c) {
            return vm.throw_range(format!("invalid collation option: {}", c));
        }
        kws.push(("co", c));
    }
    if let Some(f) = get_opt_str(vm, &opts, "firstDayOfWeek", &[])? {
        let mapped = match f.as_str() {
            "0" | "7" => "sun".to_string(),
            "1" => "mon".to_string(),
            "2" => "tue".to_string(),
            "3" => "wed".to_string(),
            "4" => "thu".to_string(),
            "5" => "fri".to_string(),
            "6" => "sat".to_string(),
            _ => f.clone(),
        };
        if !is_unicode_type(&mapped) {
            return vm.throw_range(format!("invalid firstDayOfWeek: {}", f));
        }
        kws.push(("fw", mapped));
    }
    if let Some(h) = get_opt_str(vm, &opts, "hourCycle", &[])? {
        if !["h11", "h12", "h23", "h24"].contains(&h.as_str()) {
            return vm.throw_range(format!("invalid hourCycle option: {}", h));
        }
        kws.push(("hc", h));
    }
    if let Some(c) = get_opt_str(vm, &opts, "caseFirst", &[])? {
        if !["upper", "lower", "false"].contains(&c.as_str()) {
            return vm.throw_range(format!("invalid caseFirst option: {}", c));
        }
        kws.push(("kf", c));
    }
    if let Some(n) = get_opt_bool(vm, &opts, "numeric")? {
        kws.push(("kn", if n { "true".to_string() } else { "false".to_string() }));
    }
    if let Some(n) = get_opt_str(vm, &opts, "numberingSystem", &[])? {
        if !is_unicode_type(&n) {
            return vm.throw_range(format!("invalid numberingSystem option: {}", n));
        }
        kws.push(("nu", n));
    }
    for (k, v) in kws {
        let v = v.to_ascii_lowercase();
        if let Some(e) = t.u_keywords.iter_mut().find(|(kk, _)| kk == k) {
            e.1 = v;
        } else {
            t.u_keywords.push((k.to_string(), v));
        }
    }
    t.u_keywords.sort_by(|a, b| a.0.cmp(&b.0));
    // canonicalise the result again
    let s = t.to_canonical_string();
    let t = match parse_tag(&s) {
        Some(t) => t,
        None => return vm.throw_range("invalid locale"),
    };
    let o = alloc_instance(vm, a)?;
    write_slots(&o, &t);
    Ok(Value::Obj(o))
}

// ============================================================================
// Getters / methods
// ============================================================================

/// The receiver of Locale getters/methods.
fn this_locale(vm: &mut Vm, this: &Value) -> JsResult<Obj> {
    match this {
        Value::Obj(o) => {
            if let Some(Value::Str(_)) = o.get_own_str("__locale_tag") {
                Ok(o.clone())
            } else {
                vm.throw_type("receiver is not an Intl.Locale")
            }
        }
        _ => vm.throw_type("not a Locale"),
    }
}

fn required_str(vm: &mut Vm, a: &Args, name: &str) -> JsResult<Value> {
    let o = this_locale(vm, &a.this)?;
    match slot_str(&o, name) {
        Some(s) => Ok(Value::str(&s)),
        None => vm.throw_type("receiver is not an Intl.Locale"),
    }
}

fn optional_str(vm: &mut Vm, a: &Args, name: &str) -> JsResult<Value> {
    let o = this_locale(vm, &a.this)?;
    Ok(match slot_str(&o, name) {
        Some(s) => Value::str(&s),
        None => Value::Undefined,
    })
}

fn get_base_name(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    required_str(vm, a, "__locale_basename")
}
fn get_language(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    required_str(vm, a, "__locale_language")
}
fn get_script(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    optional_str(vm, a, "__locale_script")
}
fn get_region(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    optional_str(vm, a, "__locale_region")
}
fn get_variants(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    optional_str(vm, a, "__locale_variants")
}
fn get_calendar(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    optional_str(vm, a, "__locale_ca")
}
fn get_collation(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    optional_str(vm, a, "__locale_co")
}
fn get_hour_cycle(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    optional_str(vm, a, "__locale_hc")
}
fn get_case_first(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    optional_str(vm, a, "__locale_kf")
}
fn get_first_day_of_week(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    optional_str(vm, a, "__locale_fw")
}
fn get_numbering_system(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    optional_str(vm, a, "__locale_nu")
}
fn get_numeric(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_locale(vm, &a.this)?;
    Ok(Value::Bool(match slot(&o, "__locale_kn") {
        None => false,
        Some(Value::Str(s)) => !s.eq_str("false"),
        Some(_) => true,
    }))
}

fn locale_to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_locale(vm, &a.this)?;
    Ok(slot(&o, "__locale_tag").unwrap_or(Value::Undefined))
}

fn this_tag(vm: &mut Vm, a: &Args) -> JsResult<(String, Option<LangTag>)> {
    let o = this_locale(vm, &a.this)?;
    let s = slot_str(&o, "__locale_tag").unwrap_or_default();
    let t = parse_tag(&s);
    Ok((s, t))
}

fn rebuild(vm: &mut Vm, t: &LangTag, lang: String, script: Option<String>, region: Option<String>) -> Value {
    // (the result is not canonicalised again: `sgn-Shaw` -> `sgn-Shaw-GB`)
    let mut n = t.clone();
    n.language = lang;
    n.script = script;
    n.region = region;
    new_locale_object(vm, &n)
}

fn locale_maximize(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (s, t) = this_tag(vm, a)?;
    let t = match t {
        Some(t) => t,
        None => return vm.throw_range(format!("invalid language tag: {}", s)),
    };
    match maximize_fields(&t.language, t.script.as_deref(), t.region.as_deref()) {
        Some((l, sc, r)) => Ok(rebuild(vm, &t, l, Some(sc), Some(r))),
        None => Ok(new_locale_object(vm, &t)),
    }
}

fn locale_minimize(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (s, t) = this_tag(vm, a)?;
    let t = match t {
        Some(t) => t,
        None => return vm.throw_range(format!("invalid language tag: {}", s)),
    };
    let (l, sc, r) = minimize_fields(&t.language, t.script.as_deref(), t.region.as_deref());
    Ok(rebuild(vm, &t, l, sc, r))
}

/// A one-element array with the -u- value of `key`, or `default`.
fn info_list(vm: &mut Vm, a: &Args, key: &str, default: &str) -> JsResult<Value> {
    let o = this_locale(vm, &a.this)?;
    let v = match slot_str(&o, key) {
        Some(s) if !s.is_empty() => s,
        _ => default.to_string(),
    };
    Ok(str_array(vm, &[v]))
}

fn get_calendars(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    info_list(vm, a, "__locale_ca", "gregory")
}
fn get_collations(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    info_list(vm, a, "__locale_co", "default")
}
fn get_hour_cycles(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    info_list(vm, a, "__locale_hc", "h23")
}
fn get_numbering_systems(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    info_list(vm, a, "__locale_nu", "latn")
}

fn get_time_zones(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_locale(vm, &a.this)?;
    match slot_str(&o, "__locale_region") {
        Some(r) if !r.is_empty() => Ok(str_array(vm, &["UTC".to_string()])),
        _ => Ok(Value::Undefined),
    }
}

fn get_text_info(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    this_locale(vm, &a.this)?;
    let o = vm.obj_from(vec![("direction", Value::str("ltr"))]);
    Ok(Value::Obj(o))
}

fn get_week_info(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = this_locale(vm, &a.this)?;
    let first = match slot_str(&o, "__locale_fw").as_deref() {
        Some("mon") => 1,
        Some("tue") => 2,
        Some("wed") => 3,
        Some("thu") => 4,
        Some("fri") => 5,
        Some("sat") => 6,
        Some("sun") => 7,
        _ => 1,
    };
    let weekend = vm.new_array(vec![Value::Num(6.0), Value::Num(7.0)]);
    let r = vm.obj_from(vec![("firstDay", Value::Num(first as f64)), ("weekend", Value::Obj(weekend))]);
    Ok(Value::Obj(r))
}
