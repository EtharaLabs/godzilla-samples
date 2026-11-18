//! `rebar`: reinforcing bars. A bar is one element of category `rebar`: a round bar of
//! `diameter` mm (3 to 100) bent sharply along `path` (points in mm, `z` over its level), of steel
//! `grade` (CA-50 unless told), with the `host` it reinforces (a beam, a column, a structural
//! column, a footing, a strip footing or a floor, by GUID) and the `layer` `reinforce` put it on
//! (none for one drawn by hand). As the file holds it:
//! `{guid, category, level, host?, path, diameter, grade, layer?}`.
//!
//! What other parts may want: [`length`] and [`weight_kg`] of a bar (schedules, IFC), [`area`]
//! (IFC's cross section), [`bars_of_host`] and [`delete_bars_of`] (a host's bars go with it: EDIT's
//! `delete`), [`bar_json`] (making one), [`HOST_CATS`].

use crate::commands::params::{get, mm_of};
use crate::json::{Map, Num, Value};
use crate::project::Project;
use crate::session::Session;
use crate::structure::common::{add_element, new_guid, R};
use crate::structure::members::read::{default_level, level_ref, parse_guid};

/// The thinnest and thickest bar, mm.
pub const MIN_DIAMETER: f64 = 3.0;
pub const MAX_DIAMETER: f64 = 100.0;
/// The most bars one `rebar` command (and one host of `reinforce`) makes.
pub const MAX_BARS: usize = 1000;
/// The most points a bar's path has, and the most all the bars of one `rebar` command have.
pub const MAX_POINTS: usize = 10000;
/// The most hosts one `reinforce` arms, and the most bars it makes for all of them.
pub const MAX_HOSTS: usize = 1000;
pub const MAX_BARS_ALL: usize = 20000;
/// The steel's density, kg/m³.
pub const STEEL_DENSITY: f64 = 7850.0;
/// The grade a bar is of unless told.
pub const DEFAULT_GRADE: &str = "CA-50";
/// The longest text a bar holds (grade, layer).
pub const MAX_TEXT: usize = 256;
/// A path this long or shorter (mm) has no length.
pub const MIN_LENGTH: f64 = 1.0;
/// How far a point of a path may be from the origin, mm.
pub const MAX_MM: f64 = 1e9;

/// The categories a bar may be in: beams, columns, structural columns, footings, strip footings
/// and floors.
pub const HOST_CATS: &[&str] = &["beam", "column", "structuralcolumn", "footing", "stripfooting", "floor"];

const CMD: &str = "rebar";

// ---------------------------------------------------------------- what a bar is

/// The length of a path: the sum of its straight pieces.
pub fn length(path: &[[f64; 3]]) -> f64 {
    let mut l = 0.0;
    for w in path.windows(2) {
        let dx = w[1][0] - w[0][0];
        let dy = w[1][1] - w[0][1];
        let dz = w[1][2] - w[0][2];
        l += (dx * dx + dy * dy + dz * dz).sqrt();
    }
    l
}

/// A bar's cross section, mm².
pub fn area(diameter: f64) -> f64 {
    std::f64::consts::PI * diameter * diameter / 4.0
}

/// The weight of a bar of this diameter and length (mm), kg: steel at 7850 kg/m³.
pub fn weight_kg(diameter: f64, length: f64) -> f64 {
    area(diameter) * length * STEEL_DENSITY / 1e9
}

/// Rounded to the thousandth, as replies show a weight in kg.
pub fn round3(x: f64) -> f64 {
    (x * 1000.0).round() / 1000.0
}

/// Rounded to the hundredth, as `elements` shows a length.
pub fn round2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

/// A bar's path as the file holds it (points [x, y, z]); None where it isn't one.
pub fn path_of(e: &Value) -> Option<Vec<[f64; 3]>> {
    let a = e.get("path")?.as_arr()?;
    let mut out = Vec::with_capacity(a.len());
    for p in a {
        let q = p.as_arr()?;
        if q.len() != 3 {
            return None;
        }
        out.push([q[0].as_f64()?, q[1].as_f64()?, q[2].as_f64()?]);
    }
    Some(out)
}

/// A bar's length (mm) as the file holds it.
pub fn bar_length(e: &Value) -> f64 {
    path_of(e).map(|p| length(&p)).unwrap_or(0.0)
}

/// A bar's weight (kg) as the file holds it.
pub fn bar_weight_kg(e: &Value) -> f64 {
    let d = e.get("diameter").and_then(|x| x.as_f64()).unwrap_or(0.0);
    weight_kg(d, bar_length(e))
}

/// A bar's grade (CA-50 where the file holds none).
pub fn bar_grade(e: &Value) -> String {
    e.get("grade").and_then(|g| g.as_str()).unwrap_or(DEFAULT_GRADE).to_string()
}

/// A bar as the file holds it.
pub fn bar_json(
    level_guid: &str,
    host_guid: Option<&str>,
    path: &[[f64; 3]],
    diameter: f64,
    grade: &str,
    layer: Option<&str>,
) -> Value {
    let mut m = Map::new();
    m.insert("guid", Value::s(&new_guid()));
    m.insert("category", Value::s("rebar"));
    m.insert("level", Value::s(level_guid));
    if let Some(h) = host_guid {
        m.insert("host", Value::s(h));
    }
    m.insert("path", Value::Arr(path.iter().map(|p| Value::from(*p)).collect()));
    m.insert("diameter", Value::f(diameter));
    m.insert("grade", Value::s(grade));
    if let Some(l) = layer.filter(|l| !l.is_empty()) {
        m.insert("layer", Value::s(l));
    }
    Value::Obj(m)
}

/// The bars whose host is the element with this GUID (any case), in id order.
pub fn bars_of_host(pr: &Project, host_guid: &str) -> Vec<u64> {
    let want = norm(host_guid);
    pr.elements
        .iter()
        .filter(|(_, e)| e.get("category").and_then(|c| c.as_str()) == Some("rebar"))
        .filter(|(_, e)| e.get("host").and_then(|h| h.as_str()).map(norm).as_deref() == Some(want.as_str()))
        .map(|(id, _)| *id)
        .collect()
}

/// Deletes the bars of a host (what goes with it when it is deleted); returns their ids.
pub fn delete_bars_of(pr: &mut Project, host_guid: &str) -> Vec<u64> {
    let ids = bars_of_host(pr, host_guid);
    for id in &ids {
        pr.elements.remove(id);
    }
    ids
}

fn norm(g: &str) -> String {
    parse_guid(g).unwrap_or_else(|| g.to_string())
}

// ---------------------------------------------------------------- element references

/// An element as a parameter names it.
#[derive(Clone, Debug, PartialEq)]
pub enum ElemRef {
    Id(u64),
    Guid(String),
}

impl ElemRef {
    /// As the original shows it ("no element …").
    pub fn text(&self) -> String {
        match self {
            ElemRef::Id(n) => n.to_string(),
            ElemRef::Guid(g) => g.clone(),
        }
    }
}

/// A GUID as the original takes one: hyphenated (in braces or not, any case), and not one whose
/// first 64 bits are all zero (that is how it writes an element's id).
pub fn real_guid(s: &str) -> Option<String> {
    let g = parse_guid(s)?;
    let hi: String = g.chars().filter(|c| *c != '-').take(16).collect();
    if hi.bytes().all(|b| b == b'0') {
        None
    } else {
        Some(g)
    }
}

/// An element named by a parameter as the original reads one: a whole number not below zero
/// (a float with nothing after the point too) or digits in a string (spaces round them) are an
/// id; a string GUID is a GUID. None for anything else.
pub fn read_ref(v: &Value) -> Option<ElemRef> {
    match v {
        Value::Num(Num::U(u)) => Some(ElemRef::Id(*u)),
        Value::Num(Num::I(_)) => None,
        Value::Num(Num::F(f)) => {
            let f = *f;
            if f.is_finite() && f >= 0.0 && f.fract() == 0.0 && f < 18446744073709551616.0 {
                Some(ElemRef::Id(f as u64))
            } else {
                None
            }
        }
        Value::Str(s) => {
            let t = s.trim();
            if !t.is_empty() && t.bytes().all(|b| b.is_ascii_digit()) {
                return t.parse::<u64>().ok().map(ElemRef::Id);
            }
            real_guid(s).map(ElemRef::Guid)
        }
        _ => None,
    }
}

/// The element a reference names, where the model has it.
pub fn resolve_ref(pr: &Project, r: &ElemRef) -> Option<u64> {
    match r {
        ElemRef::Id(n) => {
            if pr.elements.contains_key(n) {
                Some(*n)
            } else {
                None
            }
        }
        ElemRef::Guid(g) => find_by_guid(pr, g),
    }
}

/// An element by its GUID (lowercase), the file's in any case.
pub fn find_by_guid(pr: &Project, g: &str) -> Option<u64> {
    if let Some(id) = pr.find_guid(g) {
        return Some(id);
    }
    pr.elements
        .iter()
        .find(|(_, e)| e.get("guid").and_then(|x| x.as_str()).map(norm).as_deref() == Some(g))
        .map(|(id, _)| *id)
}

/// The level an element stands on (its `level`, a level's GUID), where it is one.
pub fn level_of(pr: &Project, e: &Value) -> Option<u64> {
    let r = read_ref(e.get("level")?)?;
    let id = resolve_ref(pr, &r)?;
    if pr.category(id) == Some("level") {
        Some(id)
    } else {
        None
    }
}

// ---------------------------------------------------------------- the command

fn not_point(v: &Value) -> String {
    format!("{}: `points`: {} is not a point [x, y, z] in mm", CMD, v.to_compact())
}

fn point3(v: &Value) -> Option<[f64; 3]> {
    let a = v.as_arr()?;
    if a.len() != 3 {
        return None;
    }
    Some([mm_of(&a[0])?, mm_of(&a[1])?, mm_of(&a[2])?])
}

/// A text parameter as `rebar` reads one (at most 256 characters).
fn opt_text(p: &Value, key: &str) -> R<Option<String>> {
    match get(p, key) {
        None => Ok(None),
        Some(Value::Str(s)) if s.chars().count() <= MAX_TEXT => Ok(Some(s.clone())),
        Some(v) => Err(format!("{}: `{}` must be text of at most 256 characters, got {}", CMD, key, v.to_compact())),
    }
}

pub fn run(s: &mut Session, cid: &str, p0: &Value) -> R<Value> {
    let _ = cid;
    let p = &crate::structure::types::names_for_guids(&s.project, p0);
    let pr = &s.project;
    // the points, closed or not, and their length
    let mut path: Vec<[f64; 3]> = match get(p, "points").and_then(|v| v.as_arr()) {
        None => return Err(format!("{}: `points` [[x, y, z], …] is required", CMD)),
        Some(a) => {
            let mut out = Vec::with_capacity(a.len());
            for x in a {
                out.push(point3(x).ok_or_else(|| not_point(x))?);
            }
            out
        }
    };
    if path.len() < 2 {
        return Err(format!("{}: `points` needs at least 2 points", CMD));
    }
    let closed = match get(p, "closed") {
        None => false,
        Some(Value::Bool(b)) => *b,
        Some(v) => return Err(format!("{}: `closed` must be true or false, got {}", CMD, v.to_compact())),
    };
    if closed {
        path.push(path[0]);
    }
    if length(&path) <= MIN_LENGTH {
        return Err(format!("{}: the bar is too short: its points are all in one place", CMD));
    }
    let diameter = match get(p, "diameter") {
        None => return Err(format!("{}: `diameter` in mm is required", CMD)),
        Some(v) => mm_of(v).ok_or_else(|| format!("{}: `diameter` must be a number in mm, got {}", CMD, v.to_compact()))?,
    };
    if !(MIN_DIAMETER..=MAX_DIAMETER).contains(&diameter) {
        return Err(format!("{}: `diameter` {} mm isn't between 3 and 100 mm", CMD, diameter));
    }
    let grade = match opt_text(p, "grade")? {
        Some(g) => {
            if g.trim().is_empty() {
                return Err(format!("{}: `grade` can't be blank", CMD));
            }
            g
        }
        None => DEFAULT_GRADE.to_string(),
    };
    let layer = opt_text(p, "layer")?.filter(|l| !l.is_empty());
    let count = match get(p, "count") {
        None => 1u64,
        Some(Value::Num(Num::U(u))) => *u,
        Some(v) => return Err(format!("{}: `count` must be a whole number, got {}", CMD, v.to_compact())),
    };
    if count == 0 || count > MAX_BARS as u64 || count * path.len() as u64 > MAX_POINTS as u64 {
        return Err(format!(
            "{}: `count` is 1 to 1000 bars, and the bars' points together up to 10000",
            CMD
        ));
    }
    let step = match get(p, "step") {
        None => None,
        Some(v) => Some(point3(v).ok_or_else(|| format!("{}: `step` must be [dx, dy, dz] in mm, got {}", CMD, v.to_compact()))?),
    };
    if count > 1 && step.is_none() {
        return Err(format!("{}: `step` [dx, dy, dz] is required for more than one bar", CMD));
    }
    let host = match get(p, "host") {
        None => None,
        Some(v) => {
            let r = read_ref(v)
                .ok_or_else(|| format!("{}: `host` must be an element id or GUID, got {}", CMD, v.to_compact()))?;
            Some(resolve_ref(pr, &r).ok_or_else(|| format!("{}: no element {}", CMD, r.text()))?)
        }
    };
    let level = match get(p, "level") {
        Some(v) => level_ref(pr, CMD, "level", v)?,
        None => match host.and_then(|h| pr.el(h)).and_then(|e| level_of(pr, e)) {
            Some(l) => l,
            None => default_level(pr, CMD)?,
        },
    };
    let level_guid = pr.guid_of(level).unwrap_or_default();
    let host_guid = host.and_then(|h| pr.guid_of(h)).map(|g| norm(&g));
    let step = step.unwrap_or([0.0, 0.0, 0.0]);
    let mut ids = Vec::with_capacity(count as usize);
    for i in 0..count {
        let k = i as f64;
        let pts: Vec<[f64; 3]> =
            path.iter().map(|q| [q[0] + step[0] * k, q[1] + step[1] * k, q[2] + step[2] * k]).collect();
        let e = bar_json(&level_guid, host_guid.as_deref(), &pts, diameter, &grade, layer.as_deref());
        ids.push(Value::u(add_element(s, e)));
    }
    Ok(crate::jobj! {"ids" => Value::Arr(ids)})
}

// ---------------------------------------------------------------- the model's rules

/// A reference an element holds, as the model's rules show it: (what it names, as shown).
fn held_ref(pr: &Project, v: Option<&Value>) -> (Option<u64>, String) {
    match v {
        None | Some(Value::Null) => (None, "null".to_string()),
        Some(v) => match read_ref(v) {
            Some(r) => (resolve_ref(pr, &r), r.text()),
            None => (
                None,
                match v {
                    Value::Str(s) => s.clone(),
                    other => other.to_compact(),
                },
            ),
        },
    }
}

/// The model rules of bars, checked after every command: bar by bar in id order, each one's
/// level, its texts, its grade, its diameter, its path and its host in turn.
pub fn check(pr: &Project) -> R<()> {
    for (id, e) in &pr.elements {
        if e.get("category").and_then(|c| c.as_str()) != Some("rebar") {
            continue;
        }
        check_bar(pr, *id, e)?;
    }
    Ok(())
}

fn check_bar(pr: &Project, id: u64, e: &Value) -> R<()> {
    let (lv, shown) = held_ref(pr, e.get("level"));
    match lv {
        Some(l) if pr.category(l) == Some("level") => {}
        Some(l) => return Err(format!("rebar {}: level {} doesn't exist", id, l)),
        None => return Err(format!("rebar {}: level {} doesn't exist", id, shown)),
    }
    let grade = e.get("grade").and_then(|g| g.as_str());
    if grade.map(|g| g.chars().count() > MAX_TEXT).unwrap_or(false) {
        return Err(format!("rebar {}: grade is longer than 256 characters", id));
    }
    if e.get("layer").and_then(|g| g.as_str()).map(|g| g.chars().count() > MAX_TEXT).unwrap_or(false) {
        return Err(format!("rebar {}: layer is longer than 256 characters", id));
    }
    if grade.map(|g| g.trim().is_empty()).unwrap_or(false) {
        return Err(format!("rebar {}: a bar needs a steel grade", id));
    }
    let d = e.get("diameter").and_then(|x| x.as_f64()).unwrap_or(0.0);
    if !(MIN_DIAMETER..=MAX_DIAMETER).contains(&d) {
        return Err(format!("rebar {}: diameter {} mm isn't between 3 and 100 mm", id, d));
    }
    let n = e.get("path").and_then(|p| p.as_arr()).map(|a| a.len()).unwrap_or(0);
    if !(2..=MAX_POINTS).contains(&n) {
        return Err(format!("rebar {}: a path needs 2 to 10000 points", id));
    }
    let path = path_of(e).unwrap_or_default();
    if path.iter().any(|p| p.iter().any(|c| !(c.is_finite() && c.abs() <= MAX_MM))) {
        return Err(format!(
            "rebar {}: a point of its path is not finite or reaches past 1000000000 mm",
            id
        ));
    }
    if length(&path) <= MIN_LENGTH {
        return Err(format!("rebar {}: its path has no length", id));
    }
    match e.get("host") {
        None | Some(Value::Null) => {}
        hv => {
            let (h, shown) = held_ref(pr, hv);
            match h {
                None => return Err(format!("rebar {}: host {} doesn't exist", id, shown)),
                Some(h) => {
                    let cat = pr.category(h).unwrap_or("");
                    if !HOST_CATS.contains(&cat) {
                        return Err(format!(
                            "rebar {}: {} {} is no host for bars; a beam, a column, a footing or a floor is",
                            id, cat, h
                        ));
                    }
                }
            }
        }
    }
    Ok(())
}

// ---------------------------------------------------------------- the elements view

fn f_or_null(v: &Value) -> Value {
    match v.as_f64() {
        Some(x) => Value::f(x),
        None => v.clone(),
    }
}

/// What `elements` shows of a bar: the bar as the original holds it (its grade CA-50 where the
/// file has none, no empty layer, numbers as floats, nothing it doesn't know), its `length`
/// (mm, to the hundredth) and `weight_kg` (to the thousandth).
pub fn element_view(pr: &Project, id: u64, x: &mut Value) {
    let _ = pr;
    let e = x.clone();
    let mut m = Map::new();
    for k in ["guid", "category", "level"] {
        if let Some(v) = e.get(k) {
            let v = match (k, v) {
                ("level", Value::Str(s)) => Value::s(&norm(s)),
                _ => v.clone(),
            };
            m.insert(k, v);
        }
    }
    match e.get("host") {
        None | Some(Value::Null) => {}
        Some(Value::Str(s)) => m.insert("host", Value::s(&norm(s))),
        Some(v) => m.insert("host", v.clone()),
    }
    if let Some(Value::Arr(a)) = e.get("path") {
        let pts: Vec<Value> = a
            .iter()
            .map(|p| match p {
                Value::Arr(q) => Value::Arr(q.iter().map(f_or_null).collect()),
                other => other.clone(),
            })
            .collect();
        m.insert("path", Value::Arr(pts));
    }
    if let Some(d) = e.get("diameter") {
        m.insert("diameter", f_or_null(d));
    }
    m.insert("grade", Value::s(&bar_grade(&e)));
    if let Some(l) = e.get("layer").and_then(|l| l.as_str()).filter(|l| !l.is_empty()) {
        m.insert("layer", Value::s(l));
    }
    m.insert("id", Value::u(id));
    m.insert("length", Value::f(round2(bar_length(&e))));
    m.insert("weight_kg", Value::f(round3(bar_weight_kg(&e))));
    *x = Value::Obj(m);
}
