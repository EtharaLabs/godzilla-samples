//! BCP 47 / UTS 35 language tags: structural validation and the original's
//! canonicalisation (`Intl.getCanonicalLocales`, locale lists of all Intl
//! constructors, `Intl.Locale`).
//!
//! Observed behaviour of the original (all reproduced here):
//! * Structure: `language` (2-3 or 5-8 letters) `[-script][-region]`
//!   `*(-variant)` (duplicates rejected) then extensions (duplicate
//!   singletons rejected), `-x-` private use last.  Irregular grandfathered
//!   tags (`i-klingon`, `zh-min-nan`, `en-GB-oed`) and bare private use tags
//!   are invalid; `art-lojban`, `cel-gaulish`, `zh-guoyu`, `zh-hakka` and
//!   `zh-xiang` are ordinary language+variant aliases.
//! * Case: language/variants/extensions lowercase, script titlecase, region
//!   uppercase.  Variants are sorted.
//! * Aliases (one pass, in this order): language+variant aliases (variants
//!   visited in input order), `sgn-<region>` sign languages, single
//!   language aliases (replacement script/region only fill empty fields),
//!   script `Qaai` -> `Zinh`, region aliases (`SU`/`810` pick the likely
//!   region of the language when it is a successor state, else `RU`),
//!   variants `hepburn-heploc`/`heploc` -> `alalc97`, `polytoni` ->
//!   `polyton`.  The tables are the original's (a subset of CLDR); aliases are
//!   not applied recursively (`drw` -> `prs`, although `prs` -> `fa-AF`).
//! * `-u-`: attributes sorted and de-duplicated, keywords de-duplicated (first
//!   wins) and sorted by key, value `true` dropped, `yes` -> true for
//!   kb/kc/kh/kk/kn, value aliases for ca, ks, ms, tz, rg, sd.
//! * `-t-`: the tlang is canonicalised like a tag (but kept lowercase), the
//!   fields are stably sorted by key, `m0-names` -> `m0-prprname`.
//! * Extensions are ordered by singleton.

use super::locale::maximize_fields;

/// A structurally valid, canonicalised Unicode locale identifier.
#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct LangTag {
    pub language: String,
    pub script: Option<String>,
    pub region: Option<String>,
    /// sorted
    pub variants: Vec<String>,
    /// -u- attributes (sorted, unique)
    pub u_attributes: Vec<String>,
    /// -u- keywords sorted by key, de-duplicated (first wins); "" = true
    pub u_keywords: Vec<(String, String)>,
    /// other extensions (singleton, canonical body) sorted by singleton
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

fn is_language(s: &str) -> bool {
    is_alpha(s) && (s.len() == 2 || s.len() == 3 || (5..=8).contains(&s.len()))
}
fn is_script(s: &str) -> bool {
    s.len() == 4 && is_alpha(s)
}
fn is_region(s: &str) -> bool {
    (s.len() == 2 && is_alpha(s)) || (s.len() == 3 && is_digit(s))
}
fn is_variant(s: &str) -> bool {
    is_alnum(s) && ((5..=8).contains(&s.len()) || (s.len() == 4 && s.as_bytes()[0].is_ascii_digit()))
}

fn title(s: &str) -> String {
    let l = s.to_ascii_lowercase();
    l[..1].to_ascii_uppercase() + &l[1..]
}

/// Base subtags of a tag (or of a -t- tlang).
#[derive(Clone, Debug, Default)]
struct Base {
    language: String,
    script: Option<String>,
    region: Option<String>,
    /// input order (canonical order after `canonicalize_base`)
    variants: Vec<String>,
}

/// Parse `language [-script] [-region] *(-variant)` from `subtags[*i..]`
/// (already lowercase).  Duplicate variants make the tag invalid.
fn parse_base(subtags: &[&str], i: &mut usize) -> Option<Base> {
    let lang = *subtags.get(*i)?;
    if !is_language(lang) {
        return None;
    }
    *i += 1;
    let mut b = Base { language: lang.to_string(), ..Default::default() };
    if *i < subtags.len() && is_script(subtags[*i]) {
        b.script = Some(title(subtags[*i]));
        *i += 1;
    }
    if *i < subtags.len() && is_region(subtags[*i]) {
        b.region = Some(subtags[*i].to_ascii_uppercase());
        *i += 1;
    }
    while *i < subtags.len() && is_variant(subtags[*i]) {
        let v = subtags[*i];
        if b.variants.iter().any(|x| x == v) {
            return None;
        }
        b.variants.push(v.to_string());
        *i += 1;
    }
    Some(b)
}

// ---------------------------------------------------------------------------
// Alias data (the original's tables)
// ---------------------------------------------------------------------------

/// language + variant -> language (the variant is removed)
const LANG_VARIANT_ALIASES: &[(&str, &str, &str)] = &[
    ("art", "lojban", "jbo"),
    ("cel", "gaulish", "xtg"),
    ("hy", "arevela", "hy"),
    ("hy", "arevmda", "hyw"),
    ("zh", "guoyu", "zh"),
    ("zh", "hakka", "hak"),
    ("zh", "xiang", "hsn"),
];

/// sgn-<region> -> sign language (the region is removed)
const SIGN_LANGUAGES: &[(&str, &str)] = &[
    ("BR", "bzs"), ("CO", "csn"), ("DE", "gsg"), ("DK", "dsl"), ("ES", "ssp"), ("FR", "fsl"), ("GB", "bfi"),
    ("GR", "gss"), ("IE", "isg"), ("IT", "ise"), ("JP", "jsl"), ("MX", "mfs"), ("NI", "ncs"), ("NL", "dse"),
    ("NO", "nsl"), ("PT", "psr"), ("SE", "swl"), ("US", "ase"), ("ZA", "sfs"),
];

/// language -> language[-Script][-Region]
const LANGUAGE_ALIASES: &[(&str, &str)] = &[
    ("aam", "aas"), ("aar", "aa"), ("adp", "dz"), ("arb", "ar"), ("aue", "ktz"), ("ayx", "nun"), ("bgm", "bcg"),
    ("bh", "bho"), ("bjd", "drl"), ("ccq", "rki"), ("ces", "cs"), ("cjr", "mom"), ("cka", "cmr"), ("cmk", "xch"),
    ("cmn", "zh"), ("cnr", "sr-ME"), ("coy", "pij"), ("cqu", "quh"), ("drh", "khk"), ("drw", "prs"), ("gav", "dev"),
    ("gfx", "vaj"), ("ggn", "gvr"), ("gti", "nyc"), ("guv", "duz"), ("heb", "he"), ("hrr", "jal"), ("ibi", "opa"),
    ("ilw", "gal"), ("in", "id"), ("iw", "he"), ("jeg", "oyb"), ("ji", "yi"), ("jw", "jv"), ("kgc", "tdf"),
    ("kgh", "kml"), ("koj", "kwv"), ("krm", "bmf"), ("ktr", "dtp"), ("kvs", "gdj"), ("kwq", "yam"), ("kxe", "tvd"),
    ("kzj", "dtp"), ("kzt", "dtp"), ("lii", "raq"), ("lmm", "rmx"), ("meg", "cir"), ("mo", "ro"), ("mst", "mry"),
    ("mwj", "vaj"), ("myt", "mry"), ("nad", "xny"), ("ncp", "kdz"), ("nnx", "ngv"), ("nts", "pij"), ("oun", "vaj"),
    ("pcr", "adx"), ("pmc", "huw"), ("pmu", "phr"), ("ppa", "bfy"), ("ppr", "lcq"), ("prs", "fa-AF"), ("pry", "prt"),
    ("puz", "pub"), ("sca", "hle"), ("sh", "sr-Latn"), ("skk", "oyb"), ("swc", "sw-CD"), ("tdu", "dtp"),
    ("thc", "tpo"), ("thx", "oyb"), ("tie", "ras"), ("tkk", "twm"), ("tl", "fil"), ("tlw", "weo"), ("tmp", "tyj"),
    ("tne", "kak"), ("tnf", "prs"), ("tsf", "taj"), ("uok", "ema"), ("xba", "cax"), ("xia", "acn"), ("xkh", "waw"),
    ("xsj", "suj"), ("ybd", "rki"), ("yma", "lrr"), ("yos", "zom"), ("yuu", "yug"), ("zsm", "ms"),
];

/// region -> region (SU / 810 are resolved with likely subtags)
const REGION_ALIASES: &[(&str, &str)] = &[
    ("004", "AF"), ("008", "AL"), ("230", "ET"), ("280", "DE"), ("530", "CW"), ("532", "CW"), ("536", "SA"),
    ("554", "NZ"), ("582", "FM"), ("756", "CH"), ("810", "RU"), ("840", "US"), ("886", "YE"), ("890", "RS"),
    ("AN", "CW"), ("BU", "MM"), ("CS", "RS"), ("CT", "KI"), ("DD", "DE"), ("DY", "BJ"), ("FQ", "AQ"), ("FX", "FR"),
    ("HV", "BF"), ("JT", "UM"), ("MI", "UM"), ("NH", "VU"), ("NQ", "AQ"), ("NT", "SA"), ("PU", "UM"), ("PZ", "PA"),
    ("QU", "EU"), ("RH", "ZW"), ("SU", "RU"), ("TP", "TL"), ("UK", "GB"), ("VD", "VN"), ("WK", "UM"), ("YD", "YE"),
    ("YU", "RS"), ("ZR", "CD"),
];

/// Successor states of the Soviet Union (replacement candidates of SU/810).
const SU_REPLACEMENTS: [&str; 15] =
    ["RU", "AM", "AZ", "BY", "EE", "GE", "KZ", "KG", "LV", "LT", "MD", "TJ", "TM", "UA", "UZ"];

/// Canonicalise base subtags (one pass of the alias tables, see module docs).
fn canonicalize_base(b: &mut Base) {
    // language + variant aliases, variants visited in input order
    let snapshot = b.variants.clone();
    for v in &snapshot {
        if let Some((_, _, rep)) = LANG_VARIANT_ALIASES.iter().find(|(l, var, _)| *l == b.language && var == v) {
            b.language = rep.to_string();
            b.variants.retain(|x| x != v);
        }
    }
    // sign languages
    if b.language == "sgn" {
        if let Some(r) = b.region.as_deref() {
            if let Some((_, rep)) = SIGN_LANGUAGES.iter().find(|(k, _)| *k == r) {
                b.language = rep.to_string();
                b.region = None;
            }
        }
    }
    // language aliases
    if let Some((_, rep)) = LANGUAGE_ALIASES.iter().find(|(k, _)| *k == b.language) {
        let mut parts = rep.split('-');
        b.language = parts.next().unwrap_or_default().to_string();
        for p in parts {
            if p.len() == 4 {
                if b.script.is_none() {
                    b.script = Some(p.to_string());
                }
            } else if b.region.is_none() {
                b.region = Some(p.to_string());
            }
        }
    }
    // script aliases
    if b.script.as_deref() == Some("Qaai") {
        b.script = Some("Zinh".to_string());
    }
    // region aliases
    if let Some(r) = b.region.clone() {
        if r == "SU" || r == "810" {
            let likely = maximize_fields(&b.language, b.script.as_deref(), None).map(|(_, _, reg)| reg);
            let rep = match likely {
                Some(l) if SU_REPLACEMENTS.contains(&l.as_str()) => l,
                _ => "RU".to_string(),
            };
            b.region = Some(rep);
        } else if let Some((_, rep)) = REGION_ALIASES.iter().find(|(k, _)| *k == r) {
            b.region = Some(rep.to_string());
        }
    }
    // variant aliases
    let has = |b: &Base, v: &str| b.variants.iter().any(|x| x == v);
    if has(b, "heploc") {
        if has(b, "hepburn") {
            b.variants.retain(|x| x != "hepburn");
        }
        for x in b.variants.iter_mut() {
            if x == "heploc" {
                *x = "alalc97".to_string();
            }
        }
    }
    for x in b.variants.iter_mut() {
        if x == "polytoni" {
            *x = "polyton".to_string();
        }
    }
    b.variants.sort();
    b.variants.dedup();
}

/// Canonical value of a -u- keyword (after "true" removal).
fn canonical_keyword_value(key: &str, value: &str) -> String {
    let rep = match (key, value) {
        ("ca", "islamicc") => "islamic-civil",
        ("ca", "ethiopic-amete-alem") => "ethioaa",
        ("kb" | "kc" | "kh" | "kk" | "kn", "yes") => "",
        ("ks", "primary") => "level1",
        ("ks", "tertiary") => "level3",
        ("ms", "imperial") => "uksystem",
        ("tz", "cnckg") => "cnsha",
        ("tz", "eire") => "iedub",
        ("tz", "est") => "papty",
        ("tz", "gmt0") => "gmt",
        ("tz", "uct") | ("tz", "zulu") => "utc",
        ("rg" | "sd", "cn11") => "cnbj",
        ("rg" | "sd", "no23") => "no50",
        ("rg" | "sd", "cz10a") => "cz110",
        ("rg" | "sd", "fra") | ("rg" | "sd", "frg") => "frges",
        ("rg" | "sd", "lud") => "lucl",
        _ => value,
    };
    rep.to_string()
}

/// Validate and canonicalise a -t- extension body (lowercase subtags).
fn canonicalize_transformed(body: &[&str]) -> Option<String> {
    let mut i = 0;
    let mut out = String::new();
    if i < body.len() && is_language(body[i]) {
        let mut b = parse_base(body, &mut i)?;
        canonicalize_base(&mut b);
        out.push_str(&b.language);
        if let Some(s) = &b.script {
            out.push('-');
            out.push_str(&s.to_ascii_lowercase());
        }
        if let Some(r) = &b.region {
            out.push('-');
            out.push_str(&r.to_ascii_lowercase());
        }
        for v in &b.variants {
            out.push('-');
            out.push_str(v);
        }
    }
    let had_lang = !out.is_empty();
    let mut fields: Vec<(String, String)> = Vec::new();
    while i < body.len() {
        let k = body[i].as_bytes();
        if !(k.len() == 2 && k[0].is_ascii_alphabetic() && k[1].is_ascii_digit()) {
            return None;
        }
        i += 1;
        let st = i;
        while i < body.len() && (3..=8).contains(&body[i].len()) && is_alnum(body[i]) {
            i += 1;
        }
        if i == st {
            return None;
        }
        let key = body[st - 1].to_string();
        let mut value = body[st..i].join("-");
        if key == "m0" && value == "names" {
            value = "prprname".to_string();
        }
        fields.push((key, value));
    }
    if !had_lang && fields.is_empty() {
        return None;
    }
    fields.sort_by(|a, b| a.0.cmp(&b.0));
    for (k, v) in fields {
        if !out.is_empty() {
            out.push('-');
        }
        out.push_str(&k);
        out.push('-');
        out.push_str(&v);
    }
    Some(out)
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
    let mut base = parse_base(&subtags, &mut i)?;
    let mut u_attributes: Vec<String> = Vec::new();
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
                    if !u_keywords.iter().any(|(kk, _)| kk == key) {
                        let v = canonical_keyword_value(key, &value);
                        u_keywords.push((key.to_string(), v));
                    }
                }
            }
            't' => {
                let c = canonicalize_transformed(body)?;
                other_ext.push(('t', c));
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
    canonicalize_base(&mut base);
    u_attributes.sort();
    u_attributes.dedup();
    u_keywords.sort_by(|a, b| a.0.cmp(&b.0));
    other_ext.sort_by(|a, b| a.0.cmp(&b.0));
    Some(LangTag {
        language: base.language,
        script: base.script,
        region: base.region,
        variants: base.variants,
        u_attributes,
        u_keywords,
        other_ext,
        private_use,
    })
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

    /// The -u- extension body (attributes then keywords), "" if none.
    pub fn unicode_extension_body(&self) -> String {
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
        u
    }

    /// Everything after the base name (extensions and private use), with a
    /// leading "-" when not empty.
    pub fn extensions_string(&self) -> String {
        let mut s = String::new();
        let mut exts: Vec<(char, String)> = self.other_ext.clone();
        if !self.u_attributes.is_empty() || !self.u_keywords.is_empty() {
            exts.push(('u', self.unicode_extension_body()));
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

    /// Full canonical form (as returned by Intl.getCanonicalLocales).
    pub fn to_canonical_string(&self) -> String {
        let mut s = self.base_name();
        s.push_str(&self.extensions_string());
        s
    }
}

/// Canonicalise one language tag string (None if invalid).
pub fn canonicalize_tag(s: &str) -> Option<String> {
    parse_tag(s).map(|t| t.to_canonical_string())
}
