//! Intl.DisplayNames.
//!
//! The original only has a tiny English table (used for every locale and
//! every style): 14 regions, 12 languages + en-GB/en-US dialects, 7 scripts,
//! 5 currencies, the calendars, and no dateTimeField names at all.  Codes
//! are validated per type (`RangeError: invalid <type> code: <code>`,
//! `invalid dateTimeField: <code>`) and canonicalised (regions uppercase,
//! scripts titlecase, currencies uppercase, calendars lowercase with
//! aliases, languages via the tag canonicaliser); unknown codes give the
//! canonical code (fallback "code") or undefined (fallback "none").
//!
//! Slots: `__dn: true`, `__dn_locale`, `__dn_style`, `__dn_type`,
//! `__dn_fallback`, `__dn_langdisplay`.

use super::*;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    define_class(
        vm,
        intl,
        "DisplayNames",
        2,
        dn_ctor,
        &[Member::Method("of", 1, dn_of), Member::Method("resolvedOptions", 0, dn_resolved_options)],
        true,
    );
}

const REGIONS: &[(&str, &str)] = &[
    ("419", "Latin America"),
    ("BR", "Brazil"),
    ("CN", "China"),
    ("DE", "Germany"),
    ("ES", "Spain"),
    ("FR", "France"),
    ("GB", "United Kingdom"),
    ("IT", "Italy"),
    ("JP", "Japan"),
    ("KR", "South Korea"),
    ("NL", "Netherlands"),
    ("PT", "Portugal"),
    ("RU", "Russia"),
    ("US", "United States"),
];

const LANGUAGES: &[(&str, &str)] = &[
    ("ar", "Arabic"),
    ("de", "German"),
    ("en", "English"),
    ("en-GB", "British English"),
    ("en-US", "American English"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("it", "Italian"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("nl", "Dutch"),
    ("pt", "Portuguese"),
    ("ru", "Russian"),
    ("zh", "Chinese"),
];

const SCRIPTS: &[(&str, &str)] = &[
    ("Arab", "Arabic"),
    ("Cyrl", "Cyrillic"),
    ("Hans", "Simplified Han"),
    ("Hant", "Traditional Han"),
    ("Jpan", "Japanese"),
    ("Kore", "Korean"),
    ("Latn", "Latin"),
];

const CURRENCY_NAMES: &[(&str, &str)] = &[
    ("CNY", "Chinese Yuan"),
    ("EUR", "Euro"),
    ("GBP", "British Pound"),
    ("JPY", "Japanese Yen"),
    ("USD", "US Dollar"),
];

const CALENDAR_NAMES: &[(&str, &str)] = &[
    ("buddhist", "Buddhist Calendar"),
    ("chinese", "Chinese Calendar"),
    ("coptic", "Coptic Calendar"),
    ("dangi", "Dangi Calendar"),
    ("ethioaa", "Ethiopic Amete Alem Calendar"),
    ("ethiopic", "Ethiopic Calendar"),
    ("gregory", "Gregorian Calendar"),
    ("hebrew", "Hebrew Calendar"),
    ("indian", "Indian National Calendar"),
    ("islamic", "Islamic Calendar"),
    ("islamic-civil", "Islamic Calendar (tabular, civil epoch)"),
    ("islamic-rgsa", "Islamic Calendar (Saudi Arabia, sighting)"),
    ("islamic-tbla", "Islamic Calendar (tabular, astronomical epoch)"),
    ("islamic-umalqura", "Islamic Calendar (Umm al-Qura)"),
    ("iso8601", "ISO-8601 Calendar"),
    ("japanese", "Japanese Calendar"),
    ("persian", "Persian Calendar"),
    ("roc", "Minguo Calendar"),
];

const DATE_TIME_FIELDS: [&str; 12] = [
    "era", "year", "quarter", "month", "weekOfYear", "weekday", "day", "dayPeriod", "hour", "minute", "second",
    "timeZoneName",
];

fn find(table: &[(&'static str, &'static str)], key: &str) -> Option<&'static str> {
    table.iter().find(|(k, _)| *k == key).map(|(_, v)| *v)
}

fn dn_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_new(vm, a, "DisplayNames")?;
    let locales = locale_list(vm, &a.arg(0))?;
    let opts = match a.arg(1) {
        Value::Undefined => return vm.throw_type("options is required for Intl.DisplayNames"),
        Value::Obj(o) => Some(o),
        _ => return vm.throw_type("options must be an object or undefined"),
    };
    read_locale_matcher(vm, &opts)?;
    let style = get_opt_str(vm, &opts, "style", &["narrow", "short", "long"])?.unwrap_or_else(|| "long".into());
    let ty = match get_opt_str(vm, &opts, "type", &["language", "region", "script", "currency", "calendar", "dateTimeField"])? {
        Some(t) => t,
        None => return vm.throw_type("type option is required"),
    };
    let fallback = get_opt_str(vm, &opts, "fallback", &["code", "none"])?.unwrap_or_else(|| "code".into());
    let ld = get_opt_str(vm, &opts, "languageDisplay", &["dialect", "standard"])?.unwrap_or_else(|| "dialect".into());
    let r = resolve_locale(&locales);
    let o = alloc_instance(vm, a)?;
    set_slot(&o, "__dn", Value::Bool(true));
    set_slot(&o, "__dn_locale", Value::str(&r.base));
    set_slot(&o, "__dn_style", Value::str(&style));
    set_slot(&o, "__dn_type", Value::str(&ty));
    set_slot(&o, "__dn_fallback", Value::str(&fallback));
    set_slot(&o, "__dn_langdisplay", Value::str(&ld));
    Ok(Value::Obj(o))
}

fn dn_resolved_options(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.this, "__dn")?;
    let r = vm.new_object();
    for (key, name) in [
        ("locale", "__dn_locale"),
        ("style", "__dn_style"),
        ("type", "__dn_type"),
        ("fallback", "__dn_fallback"),
        ("languageDisplay", "__dn_langdisplay"),
    ] {
        if let Some(v) = slot(&o, name) {
            if !v.is_undefined() {
                r.set_str(key, v, WEC);
            }
        }
    }
    Ok(Value::Obj(r))
}

fn invalid<T>(vm: &mut Vm, what: &str, code: &str) -> JsResult<T> {
    vm.throw_range(format!("invalid {} code: {}", what, code))
}

fn dn_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.this, "__dn")?;
    let code = vm.to_string(&a.arg(0))?.to_rust_string();
    let ty = slot_str(&o, "__dn_type").unwrap_or_default();
    let none = slot_str(&o, "__dn_fallback").as_deref() == Some("none");
    let (canonical, name): (String, Option<&str>) = match ty.as_str() {
        "region" => {
            let ok = (code.len() == 2 && code.bytes().all(|b| b.is_ascii_alphabetic()))
                || (code.len() == 3 && code.bytes().all(|b| b.is_ascii_digit()));
            if !ok {
                return invalid(vm, "region", &code);
            }
            let c = code.to_ascii_uppercase();
            let n = find(REGIONS, &c);
            (c, n)
        }
        "script" => {
            if !(code.len() == 4 && code.bytes().all(|b| b.is_ascii_alphabetic())) {
                return invalid(vm, "script", &code);
            }
            let c = code[..1].to_ascii_uppercase() + &code[1..].to_ascii_lowercase();
            let n = find(SCRIPTS, &c);
            (c, n)
        }
        "language" => {
            let t = match parse_tag(&code) {
                Some(t) if t.u_attributes.is_empty()
                    && t.u_keywords.is_empty()
                    && t.other_ext.is_empty()
                    && t.private_use.is_none() =>
                {
                    t
                }
                _ => return invalid(vm, "language", &code),
            };
            let c = t.base_name();
            let n = find(LANGUAGES, &c);
            (c, n)
        }
        "currency" => {
            if !(code.len() == 3 && code.bytes().all(|b| b.is_ascii_alphabetic())) {
                return invalid(vm, "currency", &code);
            }
            let c = code.to_ascii_uppercase();
            let n = find(CURRENCY_NAMES, &c);
            (c, n)
        }
        "calendar" => {
            if !is_unicode_type(&code) {
                return invalid(vm, "calendar", &code);
            }
            let mut c = code.to_ascii_lowercase();
            match c.as_str() {
                "islamicc" => c = "islamic-civil".to_string(),
                "ethiopic-amete-alem" => c = "ethioaa".to_string(),
                _ => {}
            }
            let n = find(CALENDAR_NAMES, &c);
            (c, n)
        }
        "dateTimeField" => {
            if !DATE_TIME_FIELDS.contains(&code.as_str()) {
                return vm.throw_range(format!("invalid dateTimeField: {}", code));
            }
            (code.clone(), None)
        }
        _ => (code.clone(), None),
    };
    Ok(match name {
        Some(n) => Value::str(n),
        None if none => Value::Undefined,
        None => Value::str(&canonical),
    })
}
