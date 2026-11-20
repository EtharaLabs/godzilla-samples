//! ECMA-402 `Intl` for lumen.
//!
//! Everything here reproduces black-box observations of the original runtime.
//!
//! # Object model
//! The original implements Intl natively with a small built-in locale table
//! (languages `ar de en es fr gv hi it ja ko ln nl pl pt ru si sl sr sv th
//! zh`; anything else resolves to `en`).  Its Intl objects are *ordinary*
//! objects whose internal slots are own data properties (non-enumerable,
//! writable, configurable) named `__<brand>_<slot>`, e.g.
//! `new Intl.NumberFormat()` has `__nf: true, __nf_locale: "en", ...`.
//! Methods brand-check `this` by the presence of the own `__<brand>` data
//! property (any value; inherited / accessor properties and proxies fail with
//! `TypeError: method called on an incompatible receiver`) and read the
//! slots back as own data properties (getters are not invoked; missing slots
//! fall back to defaults).  This layout is observable
//! (`Object.getOwnPropertyNames(nf)`, `util.inspect(nf, {showHidden:true})`,
//! tampering with `nf.__nf_locale`), so every component stores its state the
//! same way: see [`set_slot`], [`slot`], [`branded_this`].
//!
//! # Shared behaviour
//! * Locale lists ([`locale_list`]): `undefined` -> `[]`; a string is
//!   canonicalised; an object with an own `__locale_tag` (an `Intl.Locale`)
//!   gives that tag verbatim; anything else goes through ToObject
//!   (`null` -> `TypeError: Cannot convert null to object`) and is read as an
//!   array-like (holes skipped); elements must be strings or objects
//!   (`TypeError: locale must be a string or object`), objects use their
//!   `__locale_tag` or ToString.  Invalid tags:
//!   `RangeError: Incorrect locale information provided: <tag>`.
//! * Locale resolution ([`resolve_locale`]): the first requested tag whose
//!   language has data, else `en`; the resolved locale is the tag's base name
//!   plus the supported `-u-` keywords the component keeps.
//! * Options: string options that are not allowed give
//!   `RangeError: invalid <name>: <value>`.

use crate::datetime as dt;
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub mod collator;
pub mod datetimeformat;
pub mod displaynames;
pub mod durationformat;
pub mod listformat;
pub mod locale;
pub mod numberformat;
pub mod pluralrules;
pub mod relativetime;
pub mod segmenter;

pub use datetimeformat::read_dtf_options;
pub use numberformat::{group_digits_str, number_to_locale_string};

pub fn setup(vm: &mut Vm) {
    let intl = vm.new_object();
    vm.def_method(&intl, "getCanonicalLocales", 1, get_canonical_locales);
    vm.def_method(&intl, "supportedValuesOf", 1, supported_values_of);
    locale::setup(vm, &intl);
    listformat::setup(vm, &intl);
    pluralrules::setup(vm, &intl);
    relativetime::setup(vm, &intl);
    numberformat::setup(vm, &intl);
    collator::setup(vm, &intl);
    displaynames::setup(vm, &intl);
    segmenter::setup(vm, &intl);
    durationformat::setup(vm, &intl);
    datetimeformat::setup(vm, &intl);
    vm.set_tag(&intl, "Intl");
    vm.def_global("Intl", Value::Obj(intl));
}

pub fn throw_dt_error<T>(vm: &mut Vm, e: dt::DateTimeError) -> JsResult<T> {
    match e.kind {
        dt::ErrorKind::Range => vm.throw_range(e.message),
        dt::ErrorKind::Type => vm.throw_type(e.message),
    }
}

// ============================================================================
// Locale data availability
// ============================================================================

/// Languages for which the original has locale data.
pub const DATA_LANGS: [&str; 21] = [
    "ar", "de", "en", "es", "fr", "gv", "hi", "it", "ja", "ko", "ln", "nl", "pl", "pt", "ru", "si", "sl",
    "sr", "sv", "th", "zh",
];

pub fn has_locale_data(lang: &str) -> bool {
    DATA_LANGS.contains(&lang)
}

// ============================================================================
// BCP 47 language tags
// ============================================================================

/// A structurally valid, canonicalised Unicode locale identifier.
#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct LangTag {
    pub language: String,
    pub script: Option<String>,
    pub region: Option<String>,
    /// sorted
    pub variants: Vec<String>,
    /// -u- attributes
    pub u_attributes: Vec<String>,
    /// -u- keywords sorted by key, de-duplicated (first wins); "" = true
    pub u_keywords: Vec<(String, String)>,
    /// other extensions (singleton, rest) sorted by singleton, lowercase
    pub other_ext: Vec<(char, String)>,
    /// private use subtags (after "x-")
    pub private_use: Option<String>,
}

fn is_alpha(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_alphabetic())
}
fn is_digit(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit())
}
fn is_alnum(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_alphanumeric())
}

/// Parse and canonicalise a language tag (None if structurally invalid).
pub fn parse_tag(tag: &str) -> Option<LangTag> {
    if tag.is_empty() || !tag.is_ascii() {
        return None;
    }
    let lower = tag.to_ascii_lowercase();
    let subtags: Vec<&str> = lower.split('-').collect();
    if subtags.iter().any(|s| s.is_empty() || s.len() > 8) {
        return None;
    }
    let mut i = 0;
    let lang = subtags[0];
    if !(is_alpha(lang) && (lang.len() == 2 || lang.len() == 3 || (5..=8).contains(&lang.len()))) {
        return None;
    }
    i += 1;
    let mut script = None;
    if i < subtags.len() && subtags[i].len() == 4 && is_alpha(subtags[i]) {
        let s = subtags[i];
        script = Some(s[..1].to_ascii_uppercase() + &s[1..]);
        i += 1;
    }
    let mut region = None;
    if i < subtags.len() {
        let s = subtags[i];
        if (s.len() == 2 && is_alpha(s)) || (s.len() == 3 && is_digit(s)) {
            region = Some(s.to_ascii_uppercase());
            i += 1;
        }
    }
    let mut variants: Vec<String> = Vec::new();
    while i < subtags.len() {
        let s = subtags[i];
        let ok = is_alnum(s) && ((5..=8).contains(&s.len()) || (s.len() == 4 && s.as_bytes()[0].is_ascii_digit()));
        if !ok {
            break;
        }
        if variants.iter().any(|v| v == s) {
            return None;
        }
        variants.push(s.to_string());
        i += 1;
    }
    variants.sort();
    let mut u_attributes = Vec::new();
    let mut u_keywords: Vec<(String, String)> = Vec::new();
    let mut other_ext: Vec<(char, String)> = Vec::new();
    let mut seen_singletons: Vec<char> = Vec::new();
    let mut private_use = None;
    while i < subtags.len() {
        let s = subtags[i];
        if s.len() != 1 {
            return None;
        }
        let singleton = s.as_bytes()[0] as char;
        i += 1;
        if singleton == 'x' {
            let rest = &subtags[i..];
            if rest.is_empty() || !rest.iter().all(|p| is_alnum(p)) {
                return None;
            }
            private_use = Some(rest.join("-"));
            i = subtags.len();
            break;
        }
        if !singleton.is_ascii_alphanumeric() || seen_singletons.contains(&singleton) {
            return None;
        }
        seen_singletons.push(singleton);
        let start = i;
        while i < subtags.len() && subtags[i].len() > 1 {
            i += 1;
        }
        let body = &subtags[start..i];
        if body.is_empty() {
            return None;
        }
        match singleton {
            'u' => {
                let mut k = 0;
                while k < body.len() && body[k].len() >= 3 {
                    if !is_alnum(body[k]) {
                        return None;
                    }
                    u_attributes.push(body[k].to_string());
                    k += 1;
                }
                while k < body.len() {
                    let key = body[k];
                    let kb = key.as_bytes();
                    if key.len() != 2 || !kb[0].is_ascii_alphanumeric() || !kb[1].is_ascii_alphabetic() {
                        return None;
                    }
                    k += 1;
                    let vs = k;
                    while k < body.len() && body[k].len() >= 3 {
                        if !is_alnum(body[k]) {
                            return None;
                        }
                        k += 1;
                    }
                    let mut value = body[vs..k].join("-");
                    if value == "true" {
                        value.clear();
                    }
                    if key == "ca" {
                        match value.as_str() {
                            "islamicc" => value = "islamic-civil".to_string(),
                            "ethiopic-amete-alem" => value = "ethioaa".to_string(),
                            _ => {}
                        }
                    }
                    if !u_keywords.iter().any(|(kk, _)| kk == key) {
                        u_keywords.push((key.to_string(), value));
                    }
                }
            }
            't' => {
                if !valid_transformed_extension(body) {
                    return None;
                }
                other_ext.push(('t', body.join("-")));
            }
            _ => {
                if !body.iter().all(|p| is_alnum(p) && p.len() >= 2) {
                    return None;
                }
                other_ext.push((singleton, body.join("-")));
            }
        }
    }
    if i != subtags.len() {
        return None;
    }
    u_keywords.sort_by(|a, b| a.0.cmp(&b.0));
    other_ext.sort_by(|a, b| a.0.cmp(&b.0));
    let mut t = LangTag {
        language: lang.to_string(),
        script,
        region,
        variants,
        u_attributes,
        u_keywords,
        other_ext,
        private_use,
    };
    apply_language_alias(&mut t);
    Some(t)
}

/// `-t-` extension body: `tlang? tfield*` (at least one).
fn valid_transformed_extension(body: &[&str]) -> bool {
    let mut i = 0;
    let n = body.len();
    let is_lang = |s: &str| is_alpha(s) && (s.len() == 2 || s.len() == 3 || (5..=8).contains(&s.len()));
    if i < n && is_lang(body[i]) {
        i += 1;
        if i < n && body[i].len() == 4 && is_alpha(body[i]) {
            i += 1;
        }
        if i < n && ((body[i].len() == 2 && is_alpha(body[i])) || (body[i].len() == 3 && is_digit(body[i]))) {
            i += 1;
        }
        while i < n
            && is_alnum(body[i])
            && ((5..=8).contains(&body[i].len()) || (body[i].len() == 4 && body[i].as_bytes()[0].is_ascii_digit()))
        {
            i += 1;
        }
    }
    let had_lang = i > 0;
    let mut had_field = false;
    while i < n {
        let k = body[i].as_bytes();
        if !(k.len() == 2 && k[0].is_ascii_alphabetic() && k[1].is_ascii_digit()) {
            return false;
        }
        i += 1;
        let st = i;
        while i < n && (3..=8).contains(&body[i].len()) && is_alnum(body[i]) {
            i += 1;
        }
        if i == st {
            return false;
        }
        had_field = true;
    }
    had_lang || had_field
}

/// UN M.49 numeric region codes with an alpha-2 equivalent (common ones).
const REGION_ALIASES: &[(&str, &str)] = &[
    ("012", "DZ"), ("036", "AU"), ("040", "AT"), ("056", "BE"), ("076", "BR"), ("124", "CA"),
    ("156", "CN"), ("158", "TW"), ("250", "FR"), ("276", "DE"), ("344", "HK"), ("356", "IN"),
    ("380", "IT"), ("392", "JP"), ("410", "KR"), ("446", "MO"), ("484", "MX"), ("504", "MA"),
    ("528", "NL"), ("616", "PL"), ("620", "PT"), ("643", "RU"), ("682", "SA"), ("724", "ES"),
    ("752", "SE"), ("756", "CH"), ("764", "TH"), ("788", "TN"), ("818", "EG"), ("826", "GB"),
    ("840", "US"),
];

fn apply_language_alias(t: &mut LangTag) {
    if let Some(r) = t.region.as_deref() {
        if let Some((_, a)) = REGION_ALIASES.iter().find(|(n, _)| *n == r) {
            t.region = Some(a.to_string());
        }
    }
    let (lang, script): (&str, Option<&str>) = match t.language.as_str() {
        "sh" => ("sr", Some("Latn")),
        "cmn" => ("zh", None),
        "iw" => ("he", None),
        "in" => ("id", None),
        "ji" => ("yi", None),
        "jw" => ("jv", None),
        "mo" => ("ro", None),
        "tl" => ("fil", None),
        _ => return,
    };
    t.language = lang.to_string();
    if t.script.is_none() {
        t.script = script.map(|s| s.to_string());
    }
}

impl LangTag {
    /// language[-script][-region][-variants]
    pub fn base_name(&self) -> String {
        let mut s = self.language.clone();
        if let Some(sc) = &self.script {
            s.push('-');
            s.push_str(sc);
        }
        if let Some(r) = &self.region {
            s.push('-');
            s.push_str(r);
        }
        for v in &self.variants {
            s.push('-');
            s.push_str(v);
        }
        s
    }

    /// Value of a -u- keyword ("" for a keyword without value).
    pub fn keyword(&self, key: &str) -> Option<&str> {
        self.u_keywords.iter().find(|(k, _)| k == key).map(|(_, v)| v.as_str())
    }

    /// Full canonical form (as returned by Intl.getCanonicalLocales).
    pub fn to_canonical_string(&self) -> String {
        let mut s = self.base_name();
        let mut exts: Vec<(char, String)> = self.other_ext.clone();
        if !self.u_attributes.is_empty() || !self.u_keywords.is_empty() {
            let mut u = self.u_attributes.join("-");
            for (k, v) in &self.u_keywords {
                if !u.is_empty() {
                    u.push('-');
                }
                u.push_str(k);
                if !v.is_empty() {
                    u.push('-');
                    u.push_str(v);
                }
            }
            exts.push(('u', u));
        }
        exts.sort_by(|a, b| a.0.cmp(&b.0));
        for (c, body) in exts {
            s.push('-');
            s.push(c);
            s.push('-');
            s.push_str(&body);
        }
        if let Some(p) = &self.private_use {
            s.push_str("-x-");
            s.push_str(p);
        }
        s
    }
}

/// Canonicalise one language tag string (None if invalid).
pub fn canonicalize_tag(s: &str) -> Option<String> {
    parse_tag(s).map(|t| t.to_canonical_string())
}

fn bad_locale<T>(vm: &mut Vm, s: &str) -> JsResult<T> {
    vm.throw_range(format!("Incorrect locale information provided: {}", s))
}

/// The tag of an `Intl.Locale`-like object (own `__locale_tag` data
/// property; non-string values give "").
pub fn locale_object_tag(o: &Obj) -> Option<String> {
    o.get_own_str("__locale_tag").map(|v| match v {
        Value::Str(s) => s.to_rust_string(),
        _ => String::new(),
    })
}

/// CanonicalizeLocaleList (see module docs).
pub fn locale_list(vm: &mut Vm, v: &Value) -> JsResult<Vec<String>> {
    let mut out: Vec<String> = Vec::new();
    let push = |out: &mut Vec<String>, s: String| {
        if !out.contains(&s) {
            out.push(s);
        }
    };
    match v {
        Value::Undefined => return Ok(out),
        Value::Str(s) => {
            let s = s.to_rust_string();
            match canonicalize_tag(&s) {
                Some(c) => return Ok(vec![c]),
                None => return bad_locale(vm, &s),
            }
        }
        Value::Obj(o) => {
            if let Some(t) = locale_object_tag(o) {
                return Ok(vec![t]);
            }
        }
        _ => {}
    }
    let o = vm.to_object(v)?;
    let lenv = vm.get_str(&o, "length")?;
    let len = vm.to_length(&lenv)?;
    let mut k: u64 = 0;
    while k < len {
        let key = if k < u32::MAX as u64 { PropKey::from_index(k as u32) } else { PropKey::from_str(&k.to_string()) };
        k += 1;
        if !vm.has_property(&o, &key)? {
            continue;
        }
        let x = vm.get(&o, &key, &Value::Obj(o.clone()))?;
        let tag = match &x {
            Value::Str(s) => s.to_rust_string(),
            Value::Obj(xo) => {
                if let Some(t) = locale_object_tag(xo) {
                    push(&mut out, t);
                    continue;
                }
                vm.to_string(&x)?.to_rust_string()
            }
            _ => return vm.throw_type("locale must be a string or object"),
        };
        match canonicalize_tag(&tag) {
            Some(c) => push(&mut out, c),
            None => return bad_locale(vm, &tag),
        }
    }
    Ok(out)
}

/// Result of locale negotiation.
#[derive(Clone, Debug)]
pub struct Resolved {
    /// The chosen requested tag (all its extensions), or `en`.
    pub tag: LangTag,
    /// Base name of the chosen tag (`language[-script][-region][-variants]`).
    pub base: String,
}

impl Resolved {
    pub fn lang(&self) -> &str {
        &self.tag.language
    }
    pub fn region(&self) -> Option<&str> {
        self.tag.region.as_deref()
    }
    pub fn script(&self) -> Option<&str> {
        self.tag.script.as_deref()
    }
    /// A -u- keyword of the requested tag.
    pub fn keyword(&self, key: &str) -> Option<&str> {
        self.tag.keyword(key)
    }
    /// `base` plus `-u-k1-v1-k2-v2...` for the given kept keywords (in the
    /// given order; an empty value is written as the bare key).
    pub fn locale_with(&self, kept: &[(&str, &str)]) -> String {
        let mut s = self.base.clone();
        if !kept.is_empty() {
            s.push_str("-u");
            for (k, v) in kept {
                s.push('-');
                s.push_str(k);
                if !v.is_empty() {
                    s.push('-');
                    s.push_str(v);
                }
            }
        }
        s
    }
}

/// Pick the first requested locale whose language has data, else `en`.
/// (Tags of Intl.Locale objects are used verbatim, so they are re-parsed
/// leniently here: an unparsable tag is skipped.)
pub fn resolve_locale(requested: &[String]) -> Resolved {
    for r in requested {
        if let Some(t) = parse_tag(r) {
            if has_locale_data(&t.language) {
                let base = t.base_name();
                return Resolved { tag: t, base };
            }
        }
    }
    let t = parse_tag("en").unwrap();
    Resolved { tag: t, base: "en".to_string() }
}

/// Intl.X.supportedLocalesOf(locales, options) (shared by all services).
pub fn supported_locales_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let list = locale_list(vm, &a.arg(0))?;
    let opts = a.arg(1);
    if !opts.is_undefined() {
        let m = vm.get_prop_of(&opts, &PropKey::from_str("localeMatcher"))?;
        if !m.is_undefined() {
            let s = vm.to_string(&m)?.to_rust_string();
            if s != "lookup" && s != "best fit" {
                return vm.throw_range(format!("invalid localeMatcher: {}", s));
            }
        }
    }
    let mut out = Vec::new();
    for l in list {
        if let Some(t) = parse_tag(&l) {
            if has_locale_data(&t.language) {
                out.push(Value::str(&l));
            }
        }
    }
    Ok(Value::Obj(vm.new_array(out)))
}

// ============================================================================
// Options
// ============================================================================

/// How a constructor treats its `options` argument.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum OptionsMode {
    /// undefined -> none; null -> `TypeError: options cannot be null`;
    /// other primitives -> ToObject (NumberFormat, DateTimeFormat, Collator,
    /// RelativeTimeFormat, Locale).
    Coerce,
    /// undefined -> none; anything but an object ->
    /// `TypeError: options must be an object or undefined`.
    Strict,
}

pub fn get_options(vm: &mut Vm, v: &Value, mode: OptionsMode) -> JsResult<Option<Obj>> {
    match v {
        Value::Undefined => Ok(None),
        Value::Obj(o) => Ok(Some(o.clone())),
        Value::Null if mode == OptionsMode::Coerce => vm.throw_type("options cannot be null"),
        _ if mode == OptionsMode::Strict => vm.throw_type("options must be an object or undefined"),
        _ => Ok(Some(vm.to_object(v)?)),
    }
}

/// Read a raw option value (undefined when there are no options).
pub fn get_opt(vm: &mut Vm, opts: &Option<Obj>, name: &str) -> JsResult<Value> {
    match opts {
        Some(o) => vm.get_str(o, name),
        None => Ok(Value::Undefined),
    }
}

/// GetOption(options, name, "string", allowed, undefined):
/// `RangeError: invalid <name>: <value>` for values not in `allowed`
/// (empty `allowed` = any string).
pub fn get_opt_str(vm: &mut Vm, opts: &Option<Obj>, name: &str, allowed: &[&str]) -> JsResult<Option<String>> {
    let v = get_opt(vm, opts, name)?;
    if v.is_undefined() {
        return Ok(None);
    }
    let s = vm.to_string(&v)?.to_rust_string();
    if !allowed.is_empty() && !allowed.contains(&s.as_str()) {
        return vm.throw_range(format!("invalid {}: {}", name, s));
    }
    Ok(Some(s))
}

/// GetOption(options, name, "boolean", ...): ToBoolean.
pub fn get_opt_bool(vm: &mut Vm, opts: &Option<Obj>, name: &str) -> JsResult<Option<bool>> {
    let v = get_opt(vm, opts, name)?;
    if v.is_undefined() {
        return Ok(None);
    }
    Ok(Some(v.truthy()))
}

/// GetNumberOption: ToNumber, must be within [min, max] (else
/// `RangeError: <name> out of range`), floored.
pub fn get_opt_num(vm: &mut Vm, opts: &Option<Obj>, name: &str, min: f64, max: f64) -> JsResult<Option<f64>> {
    let v = get_opt(vm, opts, name)?;
    if v.is_undefined() {
        return Ok(None);
    }
    let n = vm.to_number(&v)?;
    if n.is_nan() || n < min || n > max {
        return vm.throw_range(format!("{} out of range", name));
    }
    Ok(Some(n.floor()))
}

/// Read and validate `localeMatcher` ("lookup" | "best fit").
pub fn read_locale_matcher(vm: &mut Vm, opts: &Option<Obj>) -> JsResult<()> {
    get_opt_str(vm, opts, "localeMatcher", &["lookup", "best fit"])?;
    Ok(())
}

/// `type` production of UTS 35: (3*8alphanum) *("-" (3*8alphanum))
pub fn is_unicode_type(v: &str) -> bool {
    !v.is_empty() && v.split('-').all(|p| (3..=8).contains(&p.len()) && p.bytes().all(|b| b.is_ascii_alphanumeric()))
}

// ============================================================================
// Instances / internal slots
// ============================================================================

/// Store an internal slot (own non-enumerable writable configurable data
/// property, like the original).
pub fn set_slot(o: &Obj, name: &str, v: Value) {
    o.set_prop(PropKey::from_str(name), v, WC);
}

/// Read an internal slot: own data property only (None if missing/accessor).
pub fn slot(o: &Obj, name: &str) -> Option<Value> {
    o.get_own_str(name)
}

/// String slot (None if missing or not a string).
pub fn slot_str(o: &Obj, name: &str) -> Option<String> {
    match o.get_own_str(name) {
        Some(Value::Str(s)) => Some(s.to_rust_string()),
        _ => None,
    }
}

/// Number slot (None if missing or not a number).
pub fn slot_num(o: &Obj, name: &str) -> Option<f64> {
    match o.get_own_str(name) {
        Some(Value::Num(n)) => Some(n),
        _ => None,
    }
}

/// Boolean slot (None if missing or not a boolean).
pub fn slot_bool(o: &Obj, name: &str) -> Option<bool> {
    match o.get_own_str(name) {
        Some(Value::Bool(b)) => Some(b),
        _ => None,
    }
}

pub fn incompatible<T>(vm: &mut Vm) -> JsResult<T> {
    vm.throw_type("method called on an incompatible receiver")
}

/// Brand check: `this` must be an object with an own `brand` data property.
pub fn branded_this(vm: &mut Vm, this: &Value, brand: &str) -> JsResult<Obj> {
    if let Value::Obj(o) = this {
        if o.get_own_str(brand).is_some() {
            return Ok(o.clone());
        }
    }
    incompatible(vm)
}

/// Brand check without throwing.
pub fn has_brand(v: &Value, brand: &str) -> bool {
    match v {
        Value::Obj(o) => o.get_own_str(brand).is_some(),
        _ => false,
    }
}

/// `TypeError: Intl.<name> requires 'new'` when called without new.
pub fn require_new(vm: &mut Vm, a: &Args, name: &str) -> JsResult<()> {
    if a.new_target.is_none() {
        return vm.throw_type(format!("Intl.{} requires 'new'", name));
    }
    Ok(())
}

/// Allocate an ordinary instance object whose prototype comes from
/// new.target (or the callee when called as a function).
pub fn alloc_instance(vm: &mut Vm, a: &Args) -> JsResult<Obj> {
    let fallback = match a.callee.get_own_str("prototype") {
        Some(Value::Obj(p)) => p,
        _ => vm.intr.object_proto.clone(),
    };
    let nt = a.new_target.clone().or_else(|| Some(a.callee.clone()));
    let proto = vm.proto_from_nt(&nt, &fallback)?;
    Ok(Obj::new(Some(proto), ObjKind::Ordinary))
}

/// A prototype member of an Intl class.
pub enum Member {
    /// method (name, length, function)
    Method(&'static str, u32, NativeFn),
    /// getter (name, function) -- the getter function is named "get <name>"
    Getter(&'static str, NativeFn),
}

/// Install `Intl.<name>`: constructor (`length` = `len`) + prototype with the
/// given members in order, then `Symbol.toStringTag` = "Intl.<name>", and a
/// static `supportedLocalesOf` when `supported_locales` is set.  Returns
/// (constructor, prototype).
pub fn define_class(
    vm: &mut Vm,
    intl: &Obj,
    name: &str,
    len: u32,
    ctor: NativeFn,
    members: &[Member],
    supported_locales: bool,
) -> (Obj, Obj) {
    let proto = vm.new_object();
    let c = vm.native_ctor(name, len, ctor, &proto);
    for m in members {
        match m {
            Member::Method(n, l, f) => {
                vm.def_method(&proto, n, *l, *f);
            }
            Member::Getter(n, f) => {
                vm.def_getter(&proto, n, *f);
            }
        }
    }
    vm.set_tag(&proto, &format!("Intl.{}", name));
    if supported_locales {
        vm.def_method(&c, "supportedLocalesOf", 1, supported_locales_of);
    }
    intl.set_prop(PropKey::from_str(name), Value::Obj(c.clone()), WC);
    (c, proto)
}

/// Placeholder for not yet implemented members.
pub fn not_implemented(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    vm.throw_type("not implemented")
}

/// Array of strings.
pub fn str_array(vm: &mut Vm, items: &[String]) -> Value {
    let v: Vec<Value> = items.iter().map(|s| Value::str(s)).collect();
    Value::Obj(vm.new_array(v))
}

/// Plain object with enumerable string-keyed properties in order.
pub fn plain_object(vm: &mut Vm, pairs: Vec<(&str, Value)>) -> Obj {
    vm.obj_from(pairs)
}

/// A formatToParts-style part.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Part {
    pub kind: &'static str,
    pub value: String,
}

impl Part {
    pub fn new(kind: &'static str, value: impl Into<String>) -> Part {
        Part { kind, value: value.into() }
    }
}

/// `[{type, value}, ...]` (extra properties appended per part by `extra`).
pub fn parts_to_array(vm: &mut Vm, parts: &[Part], extra: &[(&str, Value)]) -> Value {
    let mut out = Vec::with_capacity(parts.len());
    for p in parts {
        let o = vm.new_object();
        o.set_str("type", Value::str(p.kind), WEC);
        o.set_str("value", Value::str(&p.value), WEC);
        for (k, v) in extra {
            o.set_str(k, v.clone(), WEC);
        }
        out.push(Value::Obj(o));
    }
    Value::Obj(vm.new_array(out))
}

pub fn join_parts(parts: &[Part]) -> String {
    parts.iter().map(|p| p.value.as_str()).collect()
}

// ============================================================================
// Intl.getCanonicalLocales / Intl.supportedValuesOf
// ============================================================================

fn get_canonical_locales(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let l = locale_list(vm, &a.arg(0))?;
    Ok(str_array(vm, &l))
}

pub const CALENDARS: [&str; 16] = [
    "buddhist", "chinese", "coptic", "dangi", "ethioaa", "ethiopic", "gregory", "hebrew", "indian",
    "islamic-civil", "islamic-tbla", "islamic-umalqura", "iso8601", "japanese", "persian", "roc",
];

pub const COLLATIONS: [&str; 15] = [
    "big5han", "compat", "dict", "emoji", "eor", "gb2312", "phonebk", "phonetic", "pinyin", "reformed",
    "searchjl", "stroke", "trad", "unihan", "zhuyin",
];

pub const CURRENCIES: [&str; 5] = ["CNY", "EUR", "GBP", "JPY", "USD"];

pub const NUMBERING_SYSTEMS: [&str; 79] = [
    "adlm", "ahom", "arab", "arabext", "bali", "beng", "bhks", "brah", "cakm", "cham", "chis", "deva",
    "diak", "fullwide", "gara", "gong", "gonm", "gujr", "gukh", "guru", "hanidec", "hmng", "hmnp",
    "java", "kali", "kawi", "khmr", "knda", "krai", "lana", "lanatham", "laoo", "latn", "lepc", "limb",
    "mathbold", "mathdbl", "mathmono", "mathsanb", "mathsans", "mlym", "modi", "mong", "mroo", "mtei",
    "mymr", "mymrepka", "mymrpao", "mymrshan", "mymrtlng", "nagm", "newa", "nkoo", "olck", "onao",
    "orya", "osma", "outlined", "rohg", "saur", "segment", "shrd", "sind", "sinh", "sora", "sund",
    "sunu", "takr", "talu", "tamldec", "telu", "thai", "tibt", "tirh", "tnsa", "tols", "vaii", "wara",
    "wcho",
];

pub const UNITS: [&str; 45] = [
    "acre", "bit", "byte", "celsius", "centimeter", "day", "degree", "fahrenheit", "fluid-ounce", "foot",
    "gallon", "gigabit", "gigabyte", "gram", "hectare", "hour", "inch", "kilobit", "kilobyte", "kilogram",
    "kilometer", "liter", "megabit", "megabyte", "meter", "microsecond", "mile", "mile-scandinavian",
    "milliliter", "millimeter", "millisecond", "minute", "month", "nanosecond", "ounce", "percent",
    "petabyte", "pound", "second", "stone", "terabit", "terabyte", "week", "yard", "year",
];

/// Intl.supportedValuesOf("timeZone") of the original (340 zones).
pub const TIME_ZONES: &str = "Africa/Abidjan Africa/Addis_Ababa Africa/Algiers Africa/Bangui Africa/Bissau Africa/Blantyre \
    Africa/Cairo Africa/Casablanca Africa/Ceuta Africa/El_Aaiun Africa/Johannesburg Africa/Juba \
    Africa/Khartoum Africa/Monrovia Africa/Ndjamena Africa/Sao_Tome Africa/Tripoli Africa/Tunis \
    Africa/Windhoek America/Adak America/Anchorage America/Anguilla America/Araguaina \
    America/Argentina/Buenos_Aires America/Argentina/Catamarca America/Argentina/Cordoba \
    America/Argentina/Jujuy America/Argentina/La_Rioja America/Argentina/Mendoza \
    America/Argentina/Rio_Gallegos America/Argentina/Salta America/Argentina/San_Juan \
    America/Argentina/San_Luis America/Argentina/Tucuman America/Argentina/Ushuaia America/Asuncion \
    America/Atikokan America/Bahia America/Bahia_Banderas America/Barbados America/Belem \
    America/Belize America/Boa_Vista America/Bogota America/Boise America/Cambridge_Bay \
    America/Campo_Grande America/Cancun America/Caracas America/Cayenne America/Chicago \
    America/Chihuahua America/Ciudad_Juarez America/Costa_Rica America/Coyhaique America/Creston \
    America/Cuiaba America/Danmarkshavn America/Dawson America/Dawson_Creek America/Denver \
    America/Detroit America/Edmonton America/Eirunepe America/El_Salvador America/Fort_Nelson \
    America/Fortaleza America/Glace_Bay America/Goose_Bay America/Grand_Turk America/Guatemala \
    America/Guayaquil America/Guyana America/Halifax America/Havana America/Hermosillo \
    America/Indiana/Indianapolis America/Indiana/Knox America/Indiana/Marengo \
    America/Indiana/Petersburg America/Indiana/Tell_City America/Indiana/Vevay \
    America/Indiana/Vincennes America/Indiana/Winamac America/Inuvik America/Iqaluit \
    America/Jamaica America/Juneau America/Kentucky/Louisville America/Kentucky/Monticello \
    America/La_Paz America/Lima America/Los_Angeles America/Maceio America/Managua America/Manaus \
    America/Martinique America/Matamoros America/Mazatlan America/Menominee America/Merida \
    America/Metlakatla America/Mexico_City America/Miquelon America/Moncton America/Monterrey \
    America/Montevideo America/Nassau America/New_York America/Nome America/Noronha \
    America/North_Dakota/Beulah America/North_Dakota/Center America/North_Dakota/New_Salem \
    America/Nuuk America/Ojinaga America/Paramaribo America/Port-au-Prince America/Porto_Velho \
    America/Punta_Arenas America/Rankin_Inlet America/Recife America/Regina America/Resolute \
    America/Rio_Branco America/Santarem America/Santiago America/Santo_Domingo America/Sao_Paulo \
    America/Scoresbysund America/Sitka America/St_Johns America/Swift_Current America/Tegucigalpa \
    America/Thule America/Tijuana America/Vancouver America/Whitehorse America/Winnipeg \
    America/Yakutat Antarctica/Casey Antarctica/Davis Antarctica/DumontDUrville \
    Antarctica/Macquarie Antarctica/Mawson Antarctica/McMurdo Antarctica/Palmer Antarctica/Rothera \
    Antarctica/Syowa Antarctica/Troll Antarctica/Vostok Arctic/Longyearbyen Asia/Almaty Asia/Amman \
    Asia/Anadyr Asia/Aqtau Asia/Aqtobe Asia/Ashgabat Asia/Atyrau Asia/Baghdad Asia/Bahrain \
    Asia/Baku Asia/Bangkok Asia/Barnaul Asia/Beirut Asia/Bishkek Asia/Brunei Asia/Chita \
    Asia/Colombo Asia/Damascus Asia/Dhaka Asia/Dili Asia/Dubai Asia/Dushanbe Asia/Famagusta \
    Asia/Gaza Asia/Hebron Asia/Ho_Chi_Minh Asia/Hong_Kong Asia/Hovd Asia/Irkutsk Asia/Jakarta \
    Asia/Jayapura Asia/Jerusalem Asia/Kabul Asia/Kamchatka Asia/Karachi Asia/Kathmandu \
    Asia/Khandyga Asia/Kolkata Asia/Krasnoyarsk Asia/Kuala_Lumpur Asia/Macau Asia/Magadan \
    Asia/Makassar Asia/Manila Asia/Nicosia Asia/Novokuznetsk Asia/Novosibirsk Asia/Omsk Asia/Oral \
    Asia/Pontianak Asia/Pyongyang Asia/Qostanay Asia/Qyzylorda Asia/Sakhalin Asia/Samarkand \
    Asia/Seoul Asia/Shanghai Asia/Srednekolymsk Asia/Taipei Asia/Tashkent Asia/Tbilisi Asia/Tehran \
    Asia/Thimphu Asia/Tokyo Asia/Tomsk Asia/Ulaanbaatar Asia/Urumqi Asia/Ust-Nera Asia/Vladivostok \
    Asia/Yakutsk Asia/Yangon Asia/Yekaterinburg Asia/Yerevan Atlantic/Azores Atlantic/Bermuda \
    Atlantic/Canary Atlantic/Cape_Verde Atlantic/Faroe Atlantic/Madeira Atlantic/South_Georgia \
    Atlantic/Stanley Australia/Adelaide Australia/Brisbane Australia/Broken_Hill Australia/Darwin \
    Australia/Eucla Australia/Hobart Australia/Lindeman Australia/Lord_Howe Australia/Melbourne \
    Australia/Perth Australia/Sydney Etc/GMT+1 Etc/GMT+10 Etc/GMT+11 Etc/GMT+12 Etc/GMT+2 Etc/GMT+3 \
    Etc/GMT+4 Etc/GMT+5 Etc/GMT+6 Etc/GMT+7 Etc/GMT+8 Etc/GMT+9 Etc/GMT-1 Etc/GMT-10 Etc/GMT-11 \
    Etc/GMT-12 Etc/GMT-13 Etc/GMT-14 Etc/GMT-2 Etc/GMT-3 Etc/GMT-4 Etc/GMT-5 Etc/GMT-6 Etc/GMT-7 \
    Etc/GMT-8 Etc/GMT-9 Europe/Amsterdam Europe/Andorra Europe/Astrakhan Europe/Athens \
    Europe/Belgrade Europe/Bratislava Europe/Bucharest Europe/Budapest Europe/Busingen \
    Europe/Chisinau Europe/Dublin Europe/Gibraltar Europe/Guernsey Europe/Helsinki Europe/Istanbul \
    Europe/Kaliningrad Europe/Kirov Europe/Kyiv Europe/Lisbon Europe/Madrid Europe/Malta \
    Europe/Minsk Europe/Monaco Europe/Moscow Europe/Riga Europe/Rome Europe/Samara Europe/Saratov \
    Europe/Simferopol Europe/Sofia Europe/Tallinn Europe/Tirane Europe/Ulyanovsk Europe/Vienna \
    Europe/Vilnius Europe/Volgograd Europe/Warsaw Factory Indian/Chagos Indian/Kerguelen \
    Indian/Mauritius Pacific/Apia Pacific/Bougainville Pacific/Chatham Pacific/Easter Pacific/Efate \
    Pacific/Fakaofo Pacific/Fiji Pacific/Funafuti Pacific/Galapagos Pacific/Gambier \
    Pacific/Guadalcanal Pacific/Guam Pacific/Honolulu Pacific/Kanton Pacific/Kiritimati \
    Pacific/Kosrae Pacific/Kwajalein Pacific/Marquesas Pacific/Midway Pacific/Nauru Pacific/Niue \
    Pacific/Norfolk Pacific/Noumea Pacific/Palau Pacific/Pitcairn Pacific/Rarotonga Pacific/Tahiti \
    Pacific/Tongatapu UTC";

fn supported_values_of(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let k = vm.to_string(&a.arg(0))?.to_rust_string();
    let vals: Vec<String> = match k.as_str() {
        "calendar" => CALENDARS.iter().map(|s| s.to_string()).collect(),
        "collation" => COLLATIONS.iter().map(|s| s.to_string()).collect(),
        "currency" => CURRENCIES.iter().map(|s| s.to_string()).collect(),
        "numberingSystem" => NUMBERING_SYSTEMS.iter().map(|s| s.to_string()).collect(),
        "timeZone" => TIME_ZONES.split(' ').map(|s| s.to_string()).collect(),
        "unit" => UNITS.iter().map(|s| s.to_string()).collect(),
        _ => return vm.throw_range(format!("invalid key: {}", k)),
    };
    Ok(str_array(vm, &vals))
}
