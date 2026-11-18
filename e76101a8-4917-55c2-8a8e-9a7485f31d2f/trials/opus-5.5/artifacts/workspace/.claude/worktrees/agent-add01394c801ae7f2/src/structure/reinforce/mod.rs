//! `reinforce`: bars by rules for beams, columns, footings and floors. The engineer says how many
//! bars, how thick and how far apart; this lays them out in the host's own frame inside the
//! cover and checks that what is asked fits, saying what to change. Each bar is a `rebar`
//! element of the host on a `layer`; reinforcing again replaces the bars that have a layer and
//! leaves the ones drawn by hand.
//!
//! The order the original reads and checks things in (the first that fails is the refusal): the
//! `preset` (its parameters, given ones replacing them key by key), the hosts (each element,
//! then each one's level), the preset's kind against each host, `grade`, `grade_stirrup` and
//! `clearance`, the `check` (`aggressiveness`, `check`, `fck`), and then host by host (a refusal
//! naming the host where there are several) its cover, its kind and what its kind takes.

pub mod beam;
pub mod column;
pub mod de;
pub mod floor;
pub mod footing;
pub mod geom;
pub mod norm;
pub mod shapes;
pub mod stir;

use crate::commands::params::get;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;
use crate::structure::common::{add_element, R};
use crate::structure::rebar::{self, read_ref, resolve_ref, ElemRef, MAX_BARS, MAX_BARS_ALL, MAX_HOSTS};
use geom::V3;

const CMD: &str = "reinforce";

/// The most a length may be, mm.
pub const MAX_MM: f64 = 1e9;
/// The thinnest and thickest bar.
pub const MIN_D: f64 = 3.0;
pub const MAX_D: f64 = 100.0;
/// The most bars in a row, or of a column's face.
pub const MAX_COUNT: u64 = 1000;

/// A bar laid out: its path (heights over the host's level), diameter, grade and layer.
#[derive(Clone, Debug)]
pub struct Bar {
    pub path: Vec<V3>,
    pub diameter: f64,
    pub grade: String,
    pub layer: String,
}

/// A host being armed.
pub struct Host {
    pub id: u64,
    pub cat: String,
    pub level: u64,
    pub elevation: f64,
}

/// `grade`, `grade_stirrup` and `clearance`, read once for all hosts.
pub struct Common {
    pub grade: String,
    pub grade_stirrup: String,
    pub clearance: Option<f64>,
}

impl Common {
    /// The least gap between bars of these diameters: the one given, else the thickest of them
    /// and at least 20 mm.
    pub fn clearance_for(&self, ds: &[f64]) -> f64 {
        match self.clearance {
            Some(c) => c,
            None => ds.iter().fold(20.0f64, |a, b| a.max(*b)),
        }
    }
}

/// The cover of each face, mm.
#[derive(Clone, Copy, Debug)]
pub struct Cover {
    pub top: f64,
    pub bottom: f64,
    pub sides: f64,
}

/// What arming one host needs.
pub struct Ctx<'a> {
    pub pr: &'a Project,
    pub host: &'a Host,
    pub e: &'a Value,
    pub params: &'a Map,
    pub common: &'a Common,
    pub cover: Cover,
}

/// What a host is armed with: its bars, and what the check reads of them.
pub struct Armed {
    pub bars: Vec<Bar>,
    pub info: norm::Info,
}

/// The `check` asked for: the aggressiveness class and the concrete's strength.
#[derive(Clone, Copy, Debug)]
pub struct Check {
    pub aggressiveness: Option<u64>,
    pub fck: Option<f64>,
}

/// The kind of host a category is, as presets name them.
pub fn kind_of(cat: &str) -> &str {
    match cat {
        "beam" => "beam",
        "column" | "structuralcolumn" => "column",
        "footing" => "footing",
        "floor" => "floor",
        other => other,
    }
}

fn err(msg: String) -> String {
    format!("{}: {}", CMD, msg)
}

/// A length a parameter gives: a number over 0 and up to 1000 km.
pub fn positive(what: &str, x: f64) -> R<f64> {
    if x > 0.0 && x <= MAX_MM {
        Ok(x)
    } else {
        Err(format!("`{}` must be over 0 and up to 1000000000 mm, got {}", what, x))
    }
}

/// A length a parameter gives that may be 0: up to 1000 km.
pub fn not_negative(what: &str, x: f64) -> R<f64> {
    if x >= 0.0 && x <= MAX_MM {
        Ok(x)
    } else {
        Err(format!("`{}` {} mm must be 0 or more, up to 1000000000", what, x))
    }
}

/// A bar's diameter: 3 to 100 mm.
pub fn diameter(what: &str, d: f64) -> R<f64> {
    if (MIN_D..=MAX_D).contains(&d) {
        Ok(d)
    } else {
        Err(format!("`{}` diameter {} mm isn't between 3 and 100 mm", what, d))
    }
}

/// A spacing of bars of a diameter: more than the diameter, up to 1000 km.
pub fn spacing(what: &str, s: f64, d: f64) -> R<f64> {
    if s > d && s <= MAX_MM {
        Ok(s)
    } else {
        Err(format!("`{}` spacing {} mm must be more than the {} mm diameter, and up to 1000000000", what, s, d))
    }
}

/// A count of bars: 1 to 1000.
pub fn count(what: &str, n: u64) -> R<usize> {
    if (1..=MAX_COUNT).contains(&n) {
        Ok(n as usize)
    } else {
        Err(format!("`{}` count {} isn't 1 to 1000", what, n))
    }
}

/// The value of one of the host's parameters by its name, where it is a number.
fn host_param(pr: &Project, e: &Value, name: &str) -> Option<f64> {
    let ps = e.get("params")?.as_obj()?;
    for (k, v) in ps.iter() {
        if crate::styles::parameters::param_of_key(pr, k).as_deref() == Some(name) {
            if let Some(x) = v.as_f64() {
                return Some(x);
            }
        }
    }
    None
}

/// The cover of each face: what `cover` says (a number for all, or {top, bottom, sides}), else
/// the host's `Cobrimento` or `ConcreteCover` parameter; face by face.
fn read_cover(pr: &Project, e: &Value, params: &Map) -> R<Cover> {
    let faces: [Option<f64>; 3] = match params.get("cover") {
        None | Some(Value::Null) => [None, None, None],
        Some(Value::Num(n)) => {
            let x = n.as_f64();
            [Some(x), Some(x), Some(x)]
        }
        Some(v) => match de::de_struct(v, &shapes::FACES) {
            Ok(m) => [de::f(&m, "top"), de::f(&m, "bottom"), de::f(&m, "sides")],
            Err(_) => return Err("`cover`: data did not match any variant of untagged enum CoverArg".into()),
        },
    };
    let fallback = host_param(pr, e, "Cobrimento").or_else(|| host_param(pr, e, "ConcreteCover"));
    let mut out = [0.0; 3];
    for (i, name) in ["top", "bottom", "sides"].iter().enumerate() {
        let x = match faces[i].or(fallback) {
            Some(x) => x,
            None => {
                return Err(format!(
                    "no cover for the {}: give `cover` in mm (a number, or top, bottom and sides), or give the host a Cobrimento parameter",
                    name
                ))
            }
        };
        out[i] = positive("cover", x)?;
    }
    Ok(Cover { top: out[0], bottom: out[1], sides: out[2] })
}

/// The parameters of a kind, as the "isn't a parameter" refusal lists them.
fn kind_params(kind: &str) -> &'static [&'static str] {
    match kind {
        "beam" => &["cover", "grade", "grade_stirrup", "clearance", "bottom", "top", "stirrup", "skin", "anchor"],
        "column" => &["cover", "grade", "grade_stirrup", "clearance", "bars", "stirrup", "ties", "anchor"],
        "footing" => &["cover", "grade", "clearance", "mesh"],
        "floor" => &["cover", "grade", "clearance", "bottom", "top"],
        _ => &[],
    }
}

/// What every command takes whatever the host.
const GENERAL: &[&str] = &["host", "hosts", "check", "aggressiveness", "fck"];

/// Refuses a key the host's kind doesn't take (the first in sorted order).
pub fn check_keys(params: &Map, kind: &str) -> R<()> {
    let allowed = kind_params(kind);
    let mut keys: Vec<&String> = params.keys().collect();
    keys.sort();
    for k in keys {
        if GENERAL.contains(&k.as_str()) || allowed.contains(&k.as_str()) {
            continue;
        }
        if kind == "footing" && k == "grade_stirrup" {
            continue;
        }
        if kind == "floor" && k == "grade_stirrup" {
            continue;
        }
        let list = allowed.to_vec();
        let (last, rest) = list.split_last().unwrap();
        return Err(format!("`{}` isn't a parameter of a {}; it takes {} and {}", k, kind, rest.join(", "), last));
    }
    Ok(())
}

/// One of a kind's parameters read as its serde type: None when left out or null.
pub fn read_struct(params: &Map, key: &str, shape: &de::Shape) -> R<Option<Map>> {
    match params.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(v) => de::de_struct(v, shape).map(Some).map_err(|e| format!("`{}`: {}", key, e)),
    }
}

fn read_hosts(pr: &Project, params: &Map) -> R<Vec<u64>> {
    let host = params.get("host").filter(|v| !v.is_null());
    let hosts = params.get("hosts").filter(|v| !v.is_null());
    let ids: Vec<u64> = match (host, hosts) {
        (Some(_), Some(_)) => return Err(err("give `host` or `hosts`, not both".into())),
        (None, None) => return Err(err("`host` (an element) or `hosts` (a list of them) is required".into())),
        (Some(v), None) => {
            let r = read_ref(v)
                .ok_or_else(|| err(format!("`host` must be an element id or GUID, got {}", v.to_compact())))?;
            vec![resolve_ref(pr, &r).ok_or_else(|| err(format!("no element {}", r.text())))?]
        }
        (None, Some(v)) => {
            let a = match v.as_arr() {
                Some(a) if !a.is_empty() && a.len() <= MAX_HOSTS => a,
                _ => return Err(err("`hosts` is a list of 1 to 1000 elements".into())),
            };
            let mut out = Vec::with_capacity(a.len());
            for x in a {
                let r: ElemRef =
                    read_ref(x).ok_or_else(|| err(format!("{} is not an element id or GUID", x.to_compact())))?;
                out.push(resolve_ref(pr, &r).ok_or_else(|| err(format!("no element {}", r.text())))?);
            }
            out
        }
    };
    let mut seen: Vec<u64> = Vec::with_capacity(ids.len());
    for id in ids {
        if !seen.contains(&id) {
            seen.push(id);
        }
    }
    Ok(seen)
}

/// `grade`, `grade_stirrup` and `clearance` (a refusal's words without the command's name).
fn read_common(params: &Map) -> R<Common> {
    let text = |key: &str| -> R<Option<String>> {
        match params.get(key) {
            None | Some(Value::Null) => Ok(None),
            Some(v) => Ok(Some(de::de_str(v).map_err(|e| format!("`{}`: {}", key, e))?)),
        }
    };
    let grade = text("grade")?;
    let grade_stirrup = text("grade_stirrup")?;
    for g in [&grade, &grade_stirrup].into_iter().flatten() {
        if g.trim().is_empty() {
            return Err("a `grade` can't be blank".into());
        }
    }
    let grade = grade.unwrap_or_else(|| rebar::DEFAULT_GRADE.to_string());
    let grade_stirrup = grade_stirrup.unwrap_or_else(|| grade.clone());
    let clearance = match params.get("clearance") {
        None | Some(Value::Null) => None,
        Some(v) => {
            let c = de::de_f64(v).map_err(|e| format!("`clearance`: {}", e))?;
            Some(positive("clearance", c)?)
        }
    };
    Ok(Common { grade, grade_stirrup, clearance })
}

/// Whether a `check` names NBR 6118 (its letters and digits, in any case, begin so).
fn is_nbr(s: &str) -> bool {
    let t: String = s.chars().filter(|c| c.is_alphanumeric()).flat_map(|c| c.to_lowercase()).collect();
    t.starts_with("nbr6118")
}

/// The `check` asked for, if any (a refusal's words without the command's name).
fn read_check(params: &Map) -> R<Option<Check>> {
    let field = |key: &str| params.get(key).filter(|v| !v.is_null());
    let aggressiveness = match field("aggressiveness") {
        None => None,
        Some(v) => Some(de::de_u8(v).map_err(|e| format!("`aggressiveness`: {}", e))?),
    };
    let check = match field("check") {
        None => None,
        Some(v) => Some(de::de_str(v).map_err(|e| format!("`check`: {}", e))?),
    };
    let fck = match field("fck") {
        None => None,
        Some(v) => Some(de::de_f64(v).map_err(|e| format!("`fck`: {}", e))?),
    };
    if let Some(c) = &check {
        if !is_nbr(c) {
            return Err(format!("`check` {} isn't one this knows: it is \"NBR 6118\"", Value::s(c).to_compact()));
        }
    }
    if check.is_none() {
        if aggressiveness.is_some() || fck.is_some() {
            return Err("`aggressiveness` and `fck` go with `check`: give `check` \"NBR 6118\"".into());
        }
        return Ok(None);
    }
    if let Some(a) = aggressiveness {
        if !(1..=4).contains(&a) {
            return Err("`aggressiveness` is the class 1 to 4 (I to IV)".into());
        }
    }
    if let Some(f) = fck {
        if !(10.0..=100.0).contains(&f) {
            return Err("`fck` is the concrete's strength in MPa, 10 to 100".into());
        }
    }
    Ok(Some(Check { aggressiveness, fck }))
}

/// Arms one host: its cover, its kind, and its kind's bars.
fn arm(pr: &Project, host: &Host, params: &Map, common: &Common) -> R<Armed> {
    let e = pr.el(host.id).ok_or_else(|| format!("no element {}", host.id))?;
    let cover = read_cover(pr, e, params)?;
    let ctx = Ctx { pr, host, e, params, common, cover };
    match host.cat.as_str() {
        "beam" => beam::arm(&ctx),
        "column" | "structuralcolumn" => column::arm(&ctx),
        "footing" => footing::arm(&ctx),
        "floor" => floor::arm(&ctx),
        other => Err(format!("a {} can't be armed: a beam, a column, a footing or a floor can", other)),
    }
}

pub fn run(s: &mut Session, cid: &str, p0: &Value) -> R<Value> {
    let _ = cid;
    let p = crate::structure::types::names_for_guids(&s.project, p0);
    let pr = &s.project;
    let mut params: Map = p.as_obj().cloned().unwrap_or_default();
    // the preset's parameters, those given replacing them key by key
    let mut preset: Option<(String, String)> = None;
    match get(&p, "preset") {
        None => {}
        Some(Value::Str(name)) if name.chars().count() <= 256 => {
            let e = pr
                .section(crate::styles::presets::SECTION)
                .and_then(|m| m.get(name))
                .ok_or_else(|| err(format!("there's no reinforcement preset `{}`", name)))?;
            let kind = e.get("kind").and_then(|k| k.as_str()).unwrap_or("").to_string();
            let mut merged = e.get("params").and_then(|x| x.as_obj()).cloned().unwrap_or_default();
            for (k, v) in params.items.iter() {
                if k != "preset" {
                    merged.insert(k, v.clone());
                }
            }
            params = merged;
            preset = Some((name.clone(), kind));
        }
        Some(v) => {
            return Err(err(format!("`preset` must be text of at most 256 characters, got {}", v.to_compact())))
        }
    }
    let ids = read_hosts(pr, &params)?;
    let mut hosts: Vec<Host> = Vec::with_capacity(ids.len());
    for id in &ids {
        let e = &pr.elements[id];
        let level = rebar::level_of(pr, e).ok_or_else(|| err("that element has no level".into()))?;
        let elevation = pr.el(level).and_then(|l| l.get("elevation")).and_then(|x| x.as_f64()).unwrap_or(0.0);
        let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("").to_string();
        hosts.push(Host { id: *id, cat, level, elevation });
    }
    if let Some((name, kind)) = &preset {
        for h in &hosts {
            if kind_of(&h.cat) != kind.as_str() {
                return Err(err(format!("preset `{}` is for a {}, and {} is a {}", name, kind, h.id, h.cat)));
            }
        }
    }
    // host by host: the parameters every host takes, the check, then the host's own (a refusal
    // naming the host where there are several)
    let many = hosts.len() > 1;
    let wrap = |h: &Host, e: String| if many { err(format!("{} (for the {} {})", e, h.cat, h.id)) } else { err(e) };
    let mut check: Option<Check> = None;
    let mut armed: Vec<Armed> = Vec::with_capacity(hosts.len());
    let mut total = 0usize;
    for h in &hosts {
        let common = read_common(&params).map_err(|e| wrap(h, e))?;
        check = read_check(&params).map_err(|e| wrap(h, e))?;
        let a = arm(pr, h, &params, &common).map_err(|e| wrap(h, e))?;
        total += a.bars.len();
        if total > MAX_BARS_ALL {
            return Err(err(format!(
                "that is more than the {} bars a command makes: arm fewer elements at once, or widen a spacing",
                MAX_BARS_ALL
            )));
        }
        armed.push(a);
    }
    let mut notes: Vec<Value> = Vec::new();
    if let Some(c) = &check {
        for (h, a) in hosts.iter().zip(armed.iter()) {
            for n in norm::notes(pr, h, &a.info, c) {
                notes.push(Value::s(&if many { format!("{} (for the {} {})", n, h.cat, h.id) } else { n }));
            }
        }
    }
    // the bars made before by this command (those on a layer) go
    let mut old: Vec<u64> = Vec::new();
    for h in &hosts {
        let g = pr.guid_of(h.id).unwrap_or_default();
        old.extend(rebar::bars_of_host(pr, &g).into_iter().filter(|b| {
            pr.el(*b).and_then(|e| e.get("layer")).and_then(|l| l.as_str()).map(|l| !l.is_empty()).unwrap_or(false)
        }));
    }
    let removed = old.len();
    for b in old {
        s.project.elements.remove(&b);
    }
    let mut out_ids: Vec<Value> = Vec::new();
    let mut weight = 0.0;
    for (h, a) in hosts.iter().zip(armed.into_iter()) {
        let level_guid = s.project.guid_of(h.level).unwrap_or_default();
        let host_guid = s.project.guid_of(h.id).map(|g| crate::structure::members::read::norm_ref(&g));
        for b in a.bars {
            let path: Vec<[f64; 3]> = b.path.clone();
            weight += rebar::weight_kg(b.diameter, rebar::length(&path));
            let e = rebar::bar_json(&level_guid, host_guid.as_deref(), &path, b.diameter, &b.grade, Some(&b.layer));
            out_ids.push(Value::u(add_element(s, e)));
        }
    }
    let _ = MAX_BARS;
    Ok(crate::jobj! {
        "count" => out_ids.len(),
        "hosts" => hosts.len(),
        "ids" => Value::Arr(out_ids),
        "notes" => Value::Arr(notes),
        "removed" => removed,
        "weight_kg" => rebar::round3(weight),
    })
}

/// The model rules of this part, checked after every command (a bar's own are `rebar`'s).
pub fn check(pr: &Project) -> R<()> {
    let _ = pr;
    Ok(())
}
