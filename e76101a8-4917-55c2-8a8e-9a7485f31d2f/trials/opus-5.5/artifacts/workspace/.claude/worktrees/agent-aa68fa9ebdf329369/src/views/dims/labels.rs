//! What a dimension's numbers read: lengths in its type's units (or the project's) and rounding,
//! as a continuous, baseline or ordinate string says, with its texts (prefix, suffix, Replace With
//! Text, Equality Display) and each segment's own over them.

use super::measure::Kind;
use super::super::common::*;
use crate::json::Value;
use crate::project::Project;

/// A length in mm as these units show it: millimetres, centimetres, metres, decimal feet,
/// fractional inches or feet and inches (to 1/16"); `decimals` where the type says (not for inches).
pub fn length_text(mm: f64, units: &str, decimals: Option<u64>) -> String {
    let fixed = |v: f64, d: u64| -> String {
        let k = 10f64.powi(d as i32);
        let n = (v * k).round();
        let x = n / k;
        let x = if x == 0.0 { 0.0 } else { x };
        format!("{:.*}", d as usize, x)
    };
    match units {
        "cm" => {
            let v = mm * 0.1;
            match decimals {
                Some(d) => fixed(v, d),
                None => {
                    let n = (v * 10.0).round();
                    let n = if n == 0.0 { 0.0 } else { n };
                    if n % 10.0 == 0.0 {
                        format!("{}", (n / 10.0) as i64)
                    } else {
                        format!("{:.1}", n / 10.0)
                    }
                }
            }
        }
        "m" => fixed(mm * 0.001, decimals.unwrap_or(2)),
        "ft" => format!("{}'", fixed(mm / 304.8, decimals.unwrap_or(2))),
        "in" => {
            let s = (mm / 25.4 * 16.0).round() as i64;
            inches_text(s)
        }
        "ft-in" => {
            let s = (mm / 25.4 * 16.0).round() as i64;
            let neg = s < 0;
            let s = s.abs();
            let feet = s / 192;
            let rest = s % 192;
            let inches = rest / 16;
            let frac = rest % 16;
            let f = if frac == 0 { format!("{}\"", inches) } else { format!("{} {}\"", inches, fraction(frac)) };
            format!("{}{}'-{}", if neg { "-" } else { "" }, feet, f)
        }
        _ => fixed(mm, decimals.unwrap_or(0)),
    }
}

/// Sixteenths of an inch as fractional inches: `39 3/8"`, `1/2"`, `12"`.
fn inches_text(s: i64) -> String {
    let neg = s < 0;
    let s = s.abs();
    let whole = s / 16;
    let frac = s % 16;
    let sign = if neg { "-" } else { "" };
    if frac == 0 {
        format!("{}{}\"", sign, whole)
    } else if whole == 0 {
        format!("{}{}\"", sign, fraction(frac))
    } else {
        format!("{}{} {}\"", sign, whole, fraction(frac))
    }
}

/// n/16 in lowest terms.
fn fraction(n: i64) -> String {
    let mut a = n;
    let mut b = 16;
    while a % 2 == 0 && b > 1 {
        a /= 2;
        b /= 2;
    }
    format!("{}/{}", a, b)
}

/// The dimension type's entry in `dimension_types` a dimension is of, by name.
pub fn type_of<'a>(pr: &'a Project, e: &Value) -> Option<(String, &'a Value)> {
    let name = lib_ref_name(pr, e, "type")?;
    let t = pr.section("dimension_types")?.get(&name)?;
    Some((name, t))
}

/// A dimension's or a segment's texts: prefix, suffix, above, below, replace.
#[derive(Clone, Debug, Default)]
pub struct Texts {
    pub prefix: Option<String>,
    pub suffix: Option<String>,
    pub above: Option<String>,
    pub below: Option<String>,
    pub replace: Option<String>,
}

pub const TEXT_KEYS: [&str; 5] = ["prefix", "suffix", "above", "below", "replace"];

impl Texts {
    pub fn of(v: &Value) -> Texts {
        let g = |k: &str| s_of(v, k).filter(|s| !s.is_empty()).map(|s| s.to_string());
        Texts { prefix: g("prefix"), suffix: g("suffix"), above: g("above"), below: g("below"), replace: g("replace") }
    }
    pub fn get(&self, k: &str) -> &Option<String> {
        match k {
            "prefix" => &self.prefix,
            "suffix" => &self.suffix,
            "above" => &self.above,
            "below" => &self.below,
            _ => &self.replace,
        }
    }
    pub fn set(&mut self, k: &str, v: Option<String>) {
        let v = v.filter(|s| !s.is_empty());
        match k {
            "prefix" => self.prefix = v,
            "suffix" => self.suffix = v,
            "above" => self.above = v,
            "below" => self.below = v,
            _ => self.replace = v,
        }
    }
    pub fn is_empty(&self) -> bool {
        TEXT_KEYS.iter().all(|k| self.get(k).is_none())
    }
    /// This segment's own over the dimension's where it says something.
    pub fn over(&self, base: &Texts) -> Texts {
        let mut t = base.clone();
        for k in TEXT_KEYS {
            if let Some(x) = self.get(k) {
                t.set(k, Some(x.clone()));
            }
        }
        t
    }
    /// A number with its texts: in place of it, or between the prefix and the suffix.
    pub fn around(&self, number: &str) -> String {
        if let Some(r) = &self.replace {
            return r.clone();
        }
        format!("{}{}{}", self.prefix.as_deref().unwrap_or(""), number, self.suffix.as_deref().unwrap_or(""))
    }
}

/// A dimension's segment texts, by segment.
pub fn segment_texts(e: &Value) -> Vec<(usize, Texts)> {
    let mut out = Vec::new();
    if let Some(a) = e.get("texts").and_then(|t| t.as_arr()) {
        for t in a {
            if let Some(s) = t.get("segment").and_then(|s| s.as_u64()) {
                out.push((s as usize, Texts::of(t)));
            }
        }
    }
    out
}

/// What a dimension's numbers read, from its values (unrounded).
pub fn labels(pr: &Project, e: &Value, kind: Kind, values: &[f64]) -> Vec<String> {
    let t = type_of(pr, e).map(|(_, t)| t.clone()).unwrap_or(Value::Null);
    let units = s_of(&t, "units").map(|s| s.to_string()).unwrap_or_else(|| crate::styles::weights::project_units(pr));
    let decimals = t.get("decimals").and_then(|d| d.as_u64());
    let len = |v: f64| length_text(v, &units, decimals);
    let own = Texts::of(e);
    let segs = segment_texts(e);
    let texts_of = |i: usize| -> Texts {
        match segs.iter().find(|(s, _)| *s == i) {
            Some((_, t)) => t.over(&own),
            None => own.clone(),
        }
    };
    match kind {
        Kind::Aligned | Kind::Linear => {
            if e.get("equality").and_then(|x| x.as_bool()) == Some(true) {
                let eq = s_of(&t, "equality_text").unwrap_or("EQ").to_string();
                let n = match s_of(&t, "string") {
                    Some("ordinate") => values.len() + 1,
                    _ => values.len(),
                };
                return vec![eq; n];
            }
            let numbers: Vec<f64> = match s_of(&t, "string") {
                Some("baseline") => {
                    let mut acc = 0.0;
                    values.iter().map(|v| {
                        acc += v;
                        acc
                    }).collect()
                }
                Some("ordinate") => {
                    let mut acc = 0.0;
                    let mut v = vec![0.0];
                    for x in values {
                        acc += x;
                        v.push(acc);
                    }
                    v
                }
                _ => values.to_vec(),
            };
            numbers.iter().enumerate().map(|(i, v)| texts_of(i).around(&len(*v))).collect()
        }
        Kind::Angular => values.iter().enumerate().map(|(i, v)| texts_of(i).around(&format!("{}°", super::measure::r2(*v)))).collect(),
        Kind::Radial | Kind::Diameter => {
            let key = if kind == Kind::Radial { "radius_symbol" } else { "diameter_symbol" };
            let sym = s_of(&t, key).unwrap_or(if kind == Kind::Radial { "R" } else { "Ø" }).to_string();
            values
                .iter()
                .enumerate()
                .map(|(i, v)| {
                    let n = if sym.is_empty() { len(*v) } else { format!("{} {}", sym, len(*v)) };
                    texts_of(i).around(&n)
                })
                .collect()
        }
        Kind::ArcLength => values.iter().enumerate().map(|(i, v)| texts_of(i).around(&len(*v))).collect(),
    }
}
