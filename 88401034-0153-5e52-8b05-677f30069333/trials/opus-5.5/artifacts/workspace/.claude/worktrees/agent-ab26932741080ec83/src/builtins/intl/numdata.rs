//! Number formatting data of the original runtime (symbols, currencies,
//! compact patterns, numbering systems; unit patterns in `unitdata.rs`).

#[path = "unitdata.rs"]
mod unitdata;

/// Per-locale number formatting data.
#[derive(Clone, Copy, Debug)]
pub struct NumLocale {
    pub decimal: &'static str,
    pub group: &'static str,
    /// Indian grouping (3;2)
    pub indian: bool,
    pub percent_suffix: &'static str,
    /// currency symbol after the number ("1,00 €")
    pub currency_suffix: bool,
    pub nan: &'static str,
    /// symbol of USD with currencyDisplay "symbol"
    pub usd: &'static str,
    pub default_nu: &'static str,
    pub compact_short: &'static [(i32, &'static str)],
    pub compact_long: &'static [(i32, &'static str)],
    /// index into the unit pattern groups
    pub unit_group: usize,
}

const CS_DEFAULT: &[(i32, &str)] = &[(3, "K"), (6, "M"), (9, "B"), (12, "T")];
const CL_DEFAULT: &[(i32, &str)] = &[(3, " thousand"), (6, " million"), (9, " billion"), (12, " trillion")];
const CS_EN_IN: &[(i32, &str)] = &[(3, "K"), (5, "L"), (7, "Cr")];
const CS_DE: &[(i32, &str)] = &[(6, "\u{a0}Mio."), (9, "\u{a0}Mrd."), (12, "\u{a0}Bio.")];
const CL_DE: &[(i32, &str)] = &[(3, " Tausend"), (6, " Millionen"), (9, " Milliarden"), (12, " Billionen")];
const C_JA: &[(i32, &str)] = &[(4, "万"), (8, "億"), (12, "兆")];
const C_KO: &[(i32, &str)] = &[(3, "천"), (4, "만"), (8, "억"), (12, "조")];
const C_ZH: &[(i32, &str)] = &[(4, "万"), (8, "亿"), (12, "兆")];
const C_ZH_HANT: &[(i32, &str)] = &[(4, "萬"), (8, "億"), (12, "兆")];

fn unit_group_index(key: &str) -> usize {
    unitdata::UNIT_GROUPS.iter().position(|g| *g == key).unwrap_or(0)
}

/// Number data for a language + region.
pub fn num_locale(lang: &str, region: Option<&str>) -> NumLocale {
    let mut l = NumLocale {
        decimal: ".",
        group: ",",
        indian: false,
        percent_suffix: "%",
        currency_suffix: false,
        nan: "NaN",
        usd: "US$",
        default_nu: "latn",
        compact_short: CS_DEFAULT,
        compact_long: CL_DEFAULT,
        unit_group: 0,
    };
    let comma_dec = |l: &mut NumLocale, group: &'static str| {
        l.decimal = ",";
        l.group = group;
    };
    let mut ug = lang;
    match lang {
        "en" => {
            l.usd = "$";
            if region == Some("IN") {
                l.indian = true;
                l.compact_short = CS_EN_IN;
                ug = "en-IN";
            }
        }
        "ar" => {
            if !matches!(region, Some("DZ" | "EH" | "LY" | "MA" | "MR" | "TN")) {
                l.default_nu = "arab";
            }
        }
        "de" => {
            comma_dec(&mut l, ".");
            l.percent_suffix = "\u{a0}%";
            l.currency_suffix = true;
            l.usd = "$";
            l.compact_short = CS_DE;
            l.compact_long = CL_DE;
        }
        "es" | "it" | "nl" => comma_dec(&mut l, "."),
        "fr" | "ru" | "sv" => {
            comma_dec(&mut l, "\u{202f}");
            l.percent_suffix = "\u{a0}%";
            l.currency_suffix = true;
        }
        "pl" => {
            comma_dec(&mut l, "\u{a0}");
            l.percent_suffix = "\u{a0}%";
            l.currency_suffix = true;
        }
        "pt" => {
            comma_dec(&mut l, if region == Some("PT") { "\u{a0}" } else { "." });
            l.currency_suffix = true;
        }
        "hi" => l.indian = true,
        "ja" => {
            l.usd = "$";
            l.compact_short = C_JA;
            l.compact_long = C_JA;
        }
        "ko" => {
            l.compact_short = C_KO;
            l.compact_long = C_KO;
        }
        "zh" => {
            if matches!(region, Some("TW" | "HK" | "MO")) {
                l.nan = "非數值";
                l.compact_short = C_ZH_HANT;
                l.compact_long = C_ZH_HANT;
                ug = "zh-TW";
            } else {
                l.compact_short = C_ZH;
                l.compact_long = C_ZH;
            }
        }
        _ => {}
    }
    // languages without unit data share the generic patterns
    l.unit_group = unit_group_index(match ug {
        "ln" | "si" | "sr" | "sv" | "gv" | "sl" | "th" => "hi",
        other => other,
    });
    l
}

/// Whether the locale uses the generic (English-rule) unit patterns.
pub fn generic_units(loc: &NumLocale) -> bool {
    unitdata::UNIT_GROUPS[loc.unit_group] == "hi"
}

/// Fraction digits of a currency.
pub fn currency_digits(code: &str) -> u32 {
    match code {
        "BHD" | "IQD" | "JOD" | "KWD" | "LYD" | "OMR" | "TND" => 3,
        "CLP" | "DJF" | "GNF" | "HUF" | "ISK" | "JPY" | "KMF" | "KRW" | "PYG" | "RWF" | "TWD" | "UGX" | "VND" | "VUV"
        | "XAF" | "XOF" | "XPF" => 0,
        _ => 2,
    }
}

/// The text shown for a currency (`display`: symbol / narrowSymbol / name /
/// code).  Unknown currencies (and the code display) are the code followed
/// by a no-break space.
pub fn currency_symbol(code: &str, display: &str, loc: &NumLocale) -> String {
    if display == "code" {
        return format!("{}\u{a0}", code);
    }
    let s = match code {
        "USD" => {
            if display == "symbol" {
                loc.usd
            } else {
                "$"
            }
        }
        "EUR" => "€",
        "JPY" => "¥",
        "GBP" => "£",
        "CNY" => "CN¥",
        "CAD" => "CA$",
        "AUD" => "A$",
        _ => return format!("{}\u{a0}", code),
    };
    s.to_string()
}

/// Simple units (sanctioned by the original).
pub const SIMPLE_UNITS: [&str; 45] = [
    "acre", "bit", "byte", "celsius", "centimeter", "day", "degree", "fahrenheit", "fluid-ounce", "foot", "gallon",
    "gigabit", "gigabyte", "gram", "hectare", "hour", "inch", "kilobit", "kilobyte", "kilogram", "kilometer", "liter",
    "megabit", "megabyte", "meter", "microsecond", "mile", "mile-scandinavian", "milliliter", "millimeter",
    "millisecond", "minute", "month", "nanosecond", "ounce", "percent", "petabyte", "pound", "second", "stone",
    "terabit", "terabyte", "week", "yard", "year",
];

/// IsWellFormedUnitIdentifier.
pub fn is_well_formed_unit(u: &str) -> bool {
    if SIMPLE_UNITS.contains(&u) {
        return true;
    }
    match u.split_once("-per-") {
        Some((a, b)) => SIMPLE_UNITS.contains(&a) && SIMPLE_UNITS.contains(&b),
        None => false,
    }
}

/// Unit pattern ("{0} km") for a unit, display (short/long/narrow) and
/// whether the plural category is "one"; the flag tells whether it comes
/// from locale data (else the generic fallback, whose formatToParts differs).
pub fn unit_pattern(loc: &NumLocale, unit: &str, display: &str, one: bool) -> (String, bool) {
    let di = match display {
        "long" => 2,
        "narrow" => 4,
        _ => 0,
    } + if one { 0 } else { 1 };
    if let Some(ui) = unitdata::UNIT_IDS.iter().position(|u| *u == unit) {
        let is_data = !generic_units(loc);
        return (unitdata::UNIT_PATTERNS[loc.unit_group][ui][di].to_string(), is_data);
    }
    (unit_fallback(unit, display, one), false)
}

fn unit_fallback(unit: &str, display: &str, one: bool) -> String {
    // generic fallback (compound units without data)
    match display {
        "long" => {
            let name = match unit.split_once("-per-") {
                Some((a, b)) => format!(
                    "{}{} per {}",
                    a.replace('-', " "),
                    if one { "" } else { "s" },
                    b.replace('-', " ")
                ),
                None => format!("{}{}", unit.replace('-', " "), if one { "" } else { "s" }),
            };
            format!("{{0}} {}", name)
        }
        "narrow" => format!("{{0}}{}", unit),
        _ => format!("{{0}} {}", unit),
    }
}

/// Decimal numbering systems: (name, code point of zero); hanidec is special.
pub const NUMBERING_SYSTEMS: &[(&str, u32)] = &[
    ("adlm", 0x1E950), ("ahom", 0x11730), ("arab", 0x0660), ("arabext", 0x06F0),
    ("bali", 0x1B50), ("beng", 0x09E6), ("bhks", 0x11C50), ("brah", 0x11066),
    ("cakm", 0x11136), ("cham", 0xAA50), ("chis", 0x16DA0), ("deva", 0x0966), ("diak", 0x11950),
    ("fullwide", 0xFF10), ("gara", 0x10D40), ("gong", 0x11DA0), ("gonm", 0x11D50),
    ("gujr", 0x0AE6), ("gukh", 0x16130), ("guru", 0x0A66), ("hanidec", 0),
    ("hmng", 0x16B50), ("hmnp", 0x1E140), ("java", 0xA9D0), ("kali", 0xA900),
    ("kawi", 0x11F50), ("khmr", 0x17E0), ("knda", 0x0CE6), ("krai", 0x16D70),
    ("lana", 0x1A80), ("lanatham", 0x1A90), ("laoo", 0x0ED0), ("latn", 0x30),
    ("lepc", 0x1C40), ("limb", 0x1946), ("mathbold", 0x1D7CE), ("mathdbl", 0x1D7D8),
    ("mathmono", 0x1D7F6), ("mathsanb", 0x1D7EC), ("mathsans", 0x1D7E2), ("mlym", 0x0D66),
    ("modi", 0x11650), ("mong", 0x1810), ("mroo", 0x16A60), ("mtei", 0xABF0),
    ("mymr", 0x1040), ("mymrepka", 0x116DA), ("mymrpao", 0x116D0), ("mymrshan", 0x1090),
    ("mymrtlng", 0xA9F0), ("nagm", 0x1E4F0), ("newa", 0x11450), ("nkoo", 0x07C0),
    ("olck", 0x1C50), ("onao", 0x1E5F1), ("orya", 0x0B66), ("osma", 0x104A0),
    ("outlined", 0x1CCF0), ("rohg", 0x10D30), ("saur", 0xA8D0), ("segment", 0x1FBF0),
    ("shrd", 0x111D0), ("sind", 0x112F0), ("sinh", 0x0DE6), ("sora", 0x110F0),
    ("sund", 0x1BB0), ("sunu", 0x11BF0), ("takr", 0x116C0), ("talu", 0x19D0),
    ("tamldec", 0x0BE6), ("telu", 0x0C66), ("thai", 0x0E50), ("tibt", 0x0F20),
    ("tirh", 0x114D0), ("tnsa", 0x16AC0), ("tols", 0x11DE0), ("vaii", 0xA620), ("wara", 0x118E0),
    ("wcho", 0x1E2F0),
];

pub const HANIDEC_DIGITS: [char; 10] = ['〇', '一', '二', '三', '四', '五', '六', '七', '八', '九'];

pub fn numbering_system_supported(nu: &str) -> bool {
    NUMBERING_SYSTEMS.iter().any(|(n, _)| *n == nu)
}

/// Replace ASCII digits by the digits of numbering system `nu`.
pub fn transliterate(s: &str, nu: &str) -> String {
    if nu == "latn" {
        return s.to_string();
    }
    let zero = match NUMBERING_SYSTEMS.iter().find(|(n, _)| *n == nu) {
        Some((_, z)) => *z,
        None => return s.to_string(),
    };
    s.chars()
        .map(|c| {
            if c.is_ascii_digit() {
                let d = c as u32 - '0' as u32;
                if nu == "hanidec" {
                    HANIDEC_DIGITS[d as usize]
                } else {
                    char::from_u32(zero + d).unwrap_or(c)
                }
            } else {
                c
            }
        })
        .collect()
}

/// Is `c` a decimal digit of some numbering system (for the parts tokenizer).
pub fn is_any_digit(c: char) -> bool {
    if c.is_ascii_digit() || HANIDEC_DIGITS.contains(&c) {
        return true;
    }
    let cp = c as u32;
    NUMBERING_SYSTEMS.iter().any(|(_, z)| *z != 0 && cp >= *z && cp <= *z + 9)
}

/// Replace the digits of numbering system `nu` by ASCII digits.
pub fn to_ascii_digits(s: &str, nu: &str) -> String {
    if nu == "latn" {
        return s.to_string();
    }
    let zero = match NUMBERING_SYSTEMS.iter().find(|(n, _)| *n == nu) {
        Some((_, z)) => *z,
        None => return s.to_string(),
    };
    s.chars()
        .map(|c| {
            if nu == "hanidec" {
                if let Some(i) = HANIDEC_DIGITS.iter().position(|d| *d == c) {
                    return (b'0' + i as u8) as char;
                }
                return c;
            }
            let cp = c as u32;
            if cp >= zero && cp <= zero + 9 {
                (b'0' + (cp - zero) as u8) as char
            } else {
                c
            }
        })
        .collect()
}
