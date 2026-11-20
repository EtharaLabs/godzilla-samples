//! Intl.Collator and the collation algorithm shared with
//! String.prototype.localeCompare.
//!
//! # The original's collation (black-box observations)
//! It is not CLDR/UCA.  Strings are put in NFD (lone surrogates kept as
//! their code unit value) and turned into a list of *elements*: every code
//! point with canonical combining class 0 (or a mark at the very start)
//! starts an element whose
//! * primary weight is its simple lowercase mapping (so the order is plain
//!   code point order of lowercased characters: control characters,
//!   punctuation and symbols are not ignorable, `_` sorts after `@` and
//!   before letters, `ß`/`æ`/`ø`/Greek/Cyrillic sort after `z`, Hangul
//!   syllables sort as their conjoining jamo, ...),
//! * secondary weight is the sequence of following combining marks
//!   (ccc != 0, code point order),
//! * tertiary weight is "is uppercase" (Unicode `Uppercase`; titlecase
//!   digraphs like `ǅ` count as lowercase).
//! Comparison: primaries lexicographically (shorter prefix first), then the
//! per-element mark lists (accent/variant), then the case flags (case /
//! variant; lowercase first unless caseFirst is "upper").  There is no
//! identical level: canonically equivalent strings compare equal.
//!
//! Options:
//! * `numeric`: runs of ASCII digits (marks between digits do not break a
//!   run) form one element compared by value; such an element sorts where
//!   the digits sort (after `/`, before `:`).  The total number of leading
//!   zeros of all runs is a tie-breaker: after the marks for accent/variant,
//!   after the case flags for case, unused for base.
//! * `ignorePunctuation` (default true for `th`): after NFD, ASCII
//!   punctuation/symbols, White_Space and U+2000..U+206F are removed before
//!   the elements are built (marks then attach to the previous character).
//! * German (`de`) with collation "phonebk" or usage "search": `a`, `o`, `u`
//!   (any case) immediately followed by U+0308 get an extra primary `e`
//!   (lowercase, no marks) after their marks: `ä` = `ae` + accent.
//! * Unknown/missing sensitivity behaves like "base".
//!
//! # Object model
//! Slots `__co: true, __co_locale, __co_usage, __co_sensitivity,
//! __co_ignorepunct, __co_numeric, __co_collation, __co_casefirst` (read
//! back when comparing), `compare` caches its bound function in
//! `__co_bound`.

use super::*;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    define_class(
        vm,
        intl,
        "Collator",
        0,
        collator_ctor,
        &[Member::Method("resolvedOptions", 0, collator_resolved_options), Member::Getter("compare", collator_compare_getter)],
        true,
    );
}

// ============================================================================
// Collation algorithm
// ============================================================================

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Sensitivity {
    Base,
    Accent,
    Case,
    Variant,
}

impl Sensitivity {
    pub fn from_str(s: &str) -> Sensitivity {
        match s {
            "variant" => Sensitivity::Variant,
            "case" => Sensitivity::Case,
            "accent" => Sensitivity::Accent,
            _ => Sensitivity::Base,
        }
    }
}

/// Effective comparison settings.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CollationConfig {
    pub sensitivity: Sensitivity,
    pub numeric: bool,
    pub upper_first: bool,
    pub ignore_punctuation: bool,
    /// German phonebook/search: umlauts expand to base + "e"
    pub expand_umlauts: bool,
}

impl Default for CollationConfig {
    fn default() -> Self {
        CollationConfig {
            sensitivity: Sensitivity::Variant,
            numeric: false,
            upper_first: false,
            ignore_punctuation: false,
            expand_umlauts: false,
        }
    }
}

/// Primary weight of an element.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Prim {
    Ch(u32),
    /// numeric run: range of its significant digits in `Keys::digits`
    /// (leading zeros stripped, "0" for zero)
    Num(u32, u32),
}

/// Collation keys of a string (buffers are reused between comparisons).
#[derive(Default)]
struct Keys {
    /// decoded (NFD, filtered) code points
    cps: Vec<u32>,
    /// primary elements (a numeric run is one element)
    prims: Vec<Prim>,
    digits: Vec<u8>,
    /// flat secondary sequence: 0 for every non-mark code point (each digit
    /// of a numeric run included), the code point for every mark
    sec: Vec<u32>,
    /// flat tertiary sequence: "is uppercase" for every non-mark code point
    ter: Vec<bool>,
}

impl Keys {
    fn num(&self, a: u32, b: u32) -> &[u8] {
        &self.digits[a as usize..b as usize]
    }
}

fn cmp_prim(ka: &Keys, a: Prim, kb: &Keys, b: Prim) -> std::cmp::Ordering {
    use std::cmp::Ordering::*;
    match (a, b) {
        (Prim::Ch(x), Prim::Ch(y)) => x.cmp(&y),
        (Prim::Num(a0, a1), Prim::Num(b0, b1)) => {
            let (x, y) = (ka.num(a0, a1), kb.num(b0, b1));
            x.len().cmp(&y.len()).then_with(|| x.cmp(y))
        }
        (Prim::Num(..), Prim::Ch(y)) => {
            if y < 0x30 {
                Greater
            } else {
                Less
            }
        }
        (Prim::Ch(x), Prim::Num(..)) => {
            if x < 0x30 {
                Less
            } else {
                Greater
            }
        }
    }
}

/// Characters removed by ignorePunctuation (checked after NFD).
pub fn is_ignorable_punct(c: u32) -> bool {
    matches!(c, 0x21..=0x2F | 0x3A..=0x40 | 0x5B..=0x60 | 0x7B..=0x7E)
        || matches!(c, 0x09..=0x0D | 0x20 | 0x85 | 0xA0 | 0x1680 | 0x3000)
        || (0x2000..=0x206F).contains(&c)
}

fn decode_into(units: &[u16], out: &mut Vec<u32>) {
    let mut i = 0;
    while i < units.len() {
        let u = units[i] as u32;
        if (0xD800..0xDC00).contains(&u) && i + 1 < units.len() {
            let l = units[i + 1] as u32;
            if (0xDC00..0xE000).contains(&l) {
                out.push(0x10000 + ((u - 0xD800) << 10) + (l - 0xDC00));
                i += 2;
                continue;
            }
        }
        out.push(u);
        i += 1;
    }
}

#[inline]
fn lower_and_upper(c: u32) -> (u32, bool) {
    if c < 0x80 {
        let b = c as u8;
        return (b.to_ascii_lowercase() as u32, b.is_ascii_uppercase());
    }
    match char::from_u32(c) {
        Some(ch) => {
            let l = ch.to_lowercase().next().map(|x| x as u32).unwrap_or(c);
            (l, ch.is_uppercase())
        }
        None => (c, false),
    }
}

#[inline]
fn ccc(c: u32) -> u8 {
    if c < 0x300 {
        0
    } else {
        crate::unicode::canonical_combining_class(c)
    }
}

fn build_keys(keys: &mut Keys, s: &[u16], cfg: &CollationConfig) {
    keys.cps.clear();
    keys.prims.clear();
    keys.digits.clear();
    keys.sec.clear();
    keys.ter.clear();
    // NFD (code units below U+00C0 are unaffected)
    if s.iter().all(|&u| u < 0xC0) {
        keys.cps.extend(s.iter().map(|&u| u as u32));
    } else {
        let nfd = crate::unicode::normalize(s, crate::unicode::NormForm::Nfd);
        decode_into(&nfd, &mut keys.cps);
    }
    if cfg.ignore_punctuation {
        keys.cps.retain(|&c| !is_ignorable_punct(c));
    }
    let cps = std::mem::take(&mut keys.cps);
    let n = cps.len();
    // start of the numeric run being built (the last primary element)
    let mut run: Option<usize> = None;
    let mut pending_e = false;
    fn flush_run(keys: &mut Keys, run: &mut Option<usize>) {
        if let Some(st) = run.take() {
            let d = &keys.digits[st..];
            let lead = d.iter().take_while(|&&b| b == b'0').count();
            let lead = if lead == d.len() { lead - 1 } else { lead };
            let end = keys.digits.len() as u32;
            if let Some(p) = keys.prims.last_mut() {
                *p = Prim::Num((st + lead) as u32, end);
            }
        }
    }
    fn push_e(keys: &mut Keys) {
        keys.prims.push(Prim::Ch(0x65));
        keys.sec.push(0);
        keys.ter.push(false);
    }
    for i in 0..n {
        let c = cps[i];
        if ccc(c) != 0 && !keys.prims.is_empty() {
            keys.sec.push(c);
            continue;
        }
        if cfg.numeric && (0x30..=0x39).contains(&c) {
            if pending_e {
                pending_e = false;
                push_e(keys);
            }
            if run.is_none() {
                keys.prims.push(Prim::Num(0, 0));
                run = Some(keys.digits.len());
            }
            keys.digits.push(c as u8);
            keys.sec.push(0);
            keys.ter.push(false);
            continue;
        }
        flush_run(keys, &mut run);
        if pending_e {
            pending_e = false;
            push_e(keys);
        }
        let (l, up) = lower_and_upper(c);
        keys.prims.push(Prim::Ch(l));
        keys.sec.push(0);
        keys.ter.push(up);
        if cfg.expand_umlauts && matches!(l, 0x61 | 0x6F | 0x75) && i + 1 < n && cps[i + 1] == 0x308 {
            pending_e = true;
        }
    }
    flush_run(keys, &mut run);
    if pending_e {
        push_e(keys);
    }
    keys.cps = cps;
}

fn ord_to_i32(o: std::cmp::Ordering) -> i32 {
    match o {
        std::cmp::Ordering::Less => -1,
        std::cmp::Ordering::Equal => 0,
        std::cmp::Ordering::Greater => 1,
    }
}

/// ASCII-only fast path (no numeric / punctuation handling needed).
fn compare_ascii(a: &[u16], b: &[u16], cfg: &CollationConfig) -> i32 {
    let n = a.len().min(b.len());
    for i in 0..n {
        let x = (a[i] as u8).to_ascii_lowercase();
        let y = (b[i] as u8).to_ascii_lowercase();
        if x != y {
            return if x < y { -1 } else { 1 };
        }
    }
    if a.len() != b.len() {
        return if a.len() < b.len() { -1 } else { 1 };
    }
    if matches!(cfg.sensitivity, Sensitivity::Case | Sensitivity::Variant) {
        for i in 0..n {
            let x = (a[i] as u8).is_ascii_uppercase();
            let y = (b[i] as u8).is_ascii_uppercase();
            if x != y {
                let r = if x { 1 } else { -1 };
                return if cfg.upper_first { -r } else { r };
            }
        }
    }
    0
}

thread_local! {
    static KEY_BUFS: std::cell::RefCell<(Keys, Keys)> = std::cell::RefCell::new((Keys::default(), Keys::default()));
}

/// Compare two strings (UTF-16) with the original's collation.
pub fn compare(a: &[u16], b: &[u16], cfg: &CollationConfig) -> i32 {
    if !cfg.numeric && !cfg.ignore_punctuation && a.iter().all(|&u| u < 0x80) && b.iter().all(|&u| u < 0x80) {
        return compare_ascii(a, b, cfg);
    }
    KEY_BUFS.with(|cell| match cell.try_borrow_mut() {
        Ok(mut bufs) => {
            let (ka, kb) = &mut *bufs;
            compare_keys(ka, kb, a, b, cfg)
        }
        Err(_) => {
            let (mut ka, mut kb) = (Keys::default(), Keys::default());
            compare_keys(&mut ka, &mut kb, a, b, cfg)
        }
    })
}

fn compare_keys(ka: &mut Keys, kb: &mut Keys, a: &[u16], b: &[u16], cfg: &CollationConfig) -> i32 {
    use std::cmp::Ordering;
    build_keys(ka, a, cfg);
    build_keys(kb, b, cfg);
    let (ka, kb) = (&*ka, &*kb);
    // primary
    for (x, y) in ka.prims.iter().zip(kb.prims.iter()) {
        let o = cmp_prim(ka, *x, kb, *y);
        if o != Ordering::Equal {
            return ord_to_i32(o);
        }
    }
    if ka.prims.len() != kb.prims.len() {
        return if ka.prims.len() < kb.prims.len() { -1 } else { 1 };
    }
    let secondary = || ka.sec.cmp(&kb.sec);
    let tertiary = || -> Ordering {
        let n = ka.ter.len().min(kb.ter.len());
        for i in 0..n {
            let (x, y) = (ka.ter[i], kb.ter[i]);
            if x != y {
                let o = if x { Ordering::Greater } else { Ordering::Less };
                return if cfg.upper_first { o.reverse() } else { o };
            }
        }
        ka.ter.len().cmp(&kb.ter.len())
    };
    let o = match cfg.sensitivity {
        Sensitivity::Base => Ordering::Equal,
        Sensitivity::Accent => secondary(),
        Sensitivity::Case => tertiary(),
        Sensitivity::Variant => secondary().then_with(tertiary),
    };
    ord_to_i32(o)
}

// ============================================================================
// Options / locale resolution
// ============================================================================

/// Collation types the original supports for a language (besides the
/// universal "emoji" and "eor").
fn lang_collations(lang: &str) -> &'static [&'static str] {
    match lang {
        "ar" => &["compat"],
        "de" => &["phonebk"],
        "es" => &["trad"],
        "ko" => &["searchjl"],
        "ln" => &["phonetic"],
        "si" => &["dict"],
        "sv" => &["reformed"],
        "zh" => &["big5han", "gb2312", "pinyin", "stroke", "unihan", "zhuyin"],
        _ => &[],
    }
}

fn collation_supported(lang: &str, co: &str) -> bool {
    co == "emoji" || co == "eor" || lang_collations(lang).contains(&co)
}

/// Resolved Collator state (the values of the internal slots).
#[derive(Clone, Debug, PartialEq)]
pub struct ResolvedCollator {
    pub locale: String,
    pub usage: String,
    pub sensitivity: String,
    pub ignore_punctuation: bool,
    pub numeric: bool,
    pub collation: String,
    pub case_first: String,
}

impl ResolvedCollator {
    pub fn config(&self) -> CollationConfig {
        config_from(
            Some(&self.locale),
            Some(&self.usage),
            Some(&self.sensitivity),
            self.ignore_punctuation,
            self.numeric,
            Some(&self.collation),
            Some(&self.case_first),
        )
    }
}

fn config_from(
    locale: Option<&str>,
    usage: Option<&str>,
    sensitivity: Option<&str>,
    ignore_punctuation: bool,
    numeric: bool,
    collation: Option<&str>,
    case_first: Option<&str>,
) -> CollationConfig {
    let lang = locale.map(|l| l.split('-').next().unwrap_or("")).unwrap_or("");
    let expand = lang == "de" && (collation == Some("phonebk") || usage == Some("search"));
    CollationConfig {
        sensitivity: Sensitivity::from_str(sensitivity.unwrap_or("")),
        numeric,
        upper_first: case_first == Some("upper"),
        ignore_punctuation,
        expand_umlauts: expand,
    }
}

/// InitializeCollator: read `locales` / `options` (in the original's order,
/// with its error messages) and resolve the collator.
pub fn resolve_collator(vm: &mut Vm, locales: &Value, options: &Value) -> JsResult<ResolvedCollator> {
    let requested = locale_list(vm, locales)?;
    let opts = get_options(vm, options, OptionsMode::Coerce)?;
    let usage = get_opt_str(vm, &opts, "usage", &["sort", "search"])?.unwrap_or_else(|| "sort".to_string());
    read_locale_matcher(vm, &opts)?;
    let opt_collation = get_opt_str(vm, &opts, "collation", &[])?;
    let opt_numeric = get_opt_bool(vm, &opts, "numeric")?;
    let opt_case_first = get_opt_str(vm, &opts, "caseFirst", &["upper", "lower", "false"])?;
    let opt_sensitivity = get_opt_str(vm, &opts, "sensitivity", &["base", "accent", "case", "variant"])?;
    let opt_ignore = get_opt_bool(vm, &opts, "ignorePunctuation")?;

    let r = resolve_locale(&requested);
    let lang = r.lang().to_string();
    let mut kept: Vec<(&str, String)> = Vec::new();

    // co
    let mut collation = "default".to_string();
    let mut keep_co: Option<String> = None;
    if let Some(v) = r.keyword("co") {
        if collation_supported(&lang, v) {
            collation = v.to_string();
            keep_co = Some(v.to_string());
        }
    }
    if let Some(c) = &opt_collation {
        if collation_supported(&lang, c) && *c != collation {
            collation = c.clone();
            keep_co = None;
        }
    }
    // kf
    let mut case_first = "false".to_string();
    let mut keep_kf: Option<String> = None;
    let ext_kf = r.keyword("kf").map(|s| s.to_string());
    if let Some(v) = &ext_kf {
        case_first = v.clone();
        if ["upper", "lower", "false"].contains(&v.as_str()) {
            keep_kf = Some(v.clone());
        }
    }
    if let Some(c) = &opt_case_first {
        if Some(c) != ext_kf.as_ref() {
            case_first = c.clone();
            keep_kf = None;
        }
    }
    // kn
    let mut numeric = false;
    let mut keep_kn: Option<String> = None;
    let ext_kn = r.keyword("kn").map(|v| v != "false");
    if let Some(b) = ext_kn {
        numeric = b;
        keep_kn = Some(if b { String::new() } else { "false".to_string() });
    }
    if let Some(b) = opt_numeric {
        if Some(b) != ext_kn {
            numeric = b;
            keep_kn = None;
        }
    }
    if let Some(v) = keep_co {
        kept.push(("co", v));
    }
    if let Some(v) = keep_kf {
        kept.push(("kf", v));
    }
    if let Some(v) = keep_kn {
        kept.push(("kn", v));
    }
    let kept_ref: Vec<(&str, &str)> = kept.iter().map(|(k, v)| (*k, v.as_str())).collect();
    let locale = r.locale_with(&kept_ref);
    let sensitivity = opt_sensitivity.unwrap_or_else(|| "variant".to_string());
    let ignore_punctuation = opt_ignore.unwrap_or(lang == "th");
    Ok(ResolvedCollator { locale, usage, sensitivity, ignore_punctuation, numeric, collation, case_first })
}

/// String.prototype.localeCompare(that, locales, options) after the two
/// strings have been converted.
pub fn locale_compare_strings(vm: &mut Vm, s: &[u16], t: &[u16], locales: &Value, options: &Value) -> JsResult<i32> {
    let cfg = if locales.is_undefined() && options.is_undefined() {
        CollationConfig::default()
    } else {
        resolve_collator(vm, locales, options)?.config()
    };
    Ok(compare(s, t, &cfg))
}

// ============================================================================
// JS bindings
// ============================================================================

fn collator_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = resolve_collator(vm, &a.arg(0), &a.arg(1))?;
    let o = alloc_instance(vm, a)?;
    set_slot(&o, "__co", Value::Bool(true));
    set_slot(&o, "__co_locale", Value::str(&r.locale));
    set_slot(&o, "__co_usage", Value::str(&r.usage));
    set_slot(&o, "__co_sensitivity", Value::str(&r.sensitivity));
    set_slot(&o, "__co_ignorepunct", Value::Bool(r.ignore_punctuation));
    set_slot(&o, "__co_numeric", Value::Bool(r.numeric));
    set_slot(&o, "__co_collation", Value::str(&r.collation));
    set_slot(&o, "__co_casefirst", Value::str(&r.case_first));
    Ok(Value::Obj(o))
}

thread_local! {
    static SLOT_KEYS: [PropKey; 7] = [
        PropKey::from_str("__co_locale"),
        PropKey::from_str("__co_usage"),
        PropKey::from_str("__co_sensitivity"),
        PropKey::from_str("__co_ignorepunct"),
        PropKey::from_str("__co_numeric"),
        PropKey::from_str("__co_collation"),
        PropKey::from_str("__co_casefirst"),
    ];
}

/// Comparison settings from the slots of a (branded) collator object (read
/// at every call, like the original).
fn config_from_slots(o: &Obj) -> CollationConfig {
    let vals: Vec<Option<Value>> = SLOT_KEYS.with(|keys| keys.iter().map(|k| o.get_own_data(k)).collect());
    let as_str = |v: &Option<Value>| match v {
        Some(Value::Str(s)) => Some(s.to_rust_string()),
        _ => None,
    };
    let as_true = |v: &Option<Value>| matches!(v, Some(Value::Bool(true)));
    let locale = as_str(&vals[0]);
    let usage = as_str(&vals[1]);
    let sensitivity = as_str(&vals[2]);
    let collation = as_str(&vals[5]);
    let case_first = as_str(&vals[6]);
    config_from(
        locale.as_deref(),
        usage.as_deref(),
        sensitivity.as_deref(),
        as_true(&vals[3]),
        as_true(&vals[4]),
        collation.as_deref(),
        case_first.as_deref(),
    )
}

fn bound_compare(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    // the captured collator is brand-checked at every call (before the
    // arguments are converted)
    let o = branded_this(vm, &a.slot(0), "__co")?;
    let x = vm.to_string(&a.arg(0))?;
    let y = vm.to_string(&a.arg(1))?;
    let cfg = config_from_slots(&o);
    Ok(Value::Num(compare(x.units(), y.units(), &cfg) as f64))
}

/// HasOwnProperty without invoking anything (data or accessor property).
fn has_own(o: &Obj, name: &str) -> bool {
    o.borrow().props.get(&PropKey::from_str(name)).is_some()
}

fn collator_compare_getter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.this, "__co")?;
    // an existing own `__co_bound` is returned as is (its data value;
    // undefined for an accessor)
    if has_own(&o, "__co_bound") {
        return Ok(slot(&o, "__co_bound").unwrap_or(Value::Undefined));
    }
    let f = vm.native_closure("", 2, bound_compare, vec![Value::Obj(o.clone())]);
    set_slot(&o, "__co_bound", Value::Obj(f.clone()));
    Ok(Value::Obj(f))
}

fn collator_resolved_options(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.this, "__co")?;
    let r = vm.new_object();
    for (key, slot_name) in [
        ("locale", "__co_locale"),
        ("usage", "__co_usage"),
        ("sensitivity", "__co_sensitivity"),
        ("ignorePunctuation", "__co_ignorepunct"),
        ("collation", "__co_collation"),
        ("numeric", "__co_numeric"),
        ("caseFirst", "__co_casefirst"),
    ] {
        if let Some(v) = slot(&o, slot_name) {
            if !v.is_undefined() {
                r.set_str(key, v, WEC);
            }
        }
    }
    Ok(Value::Obj(r))
}
