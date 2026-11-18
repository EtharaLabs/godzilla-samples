//! `beam`, `strip_footing`, `pipe`, `duct`, `conduit`, `cable_tray`, `wire`, `down_conductor`,
//! `ground_conductor`, `cabling`: a run for each segment of a chain of points.

use super::geom::{default_justify, Justify};
use super::read::{chain_points, level_param, type_name_param};
use crate::commands::params::{opt_bool, opt_num, opt_text};
use crate::json::{Map, Value};
use crate::session::Session;
use crate::structure::common::{add_element, new_guid, type_guid, R};

/// The category a run command makes.
pub fn category_of(cid: &str) -> Option<&'static str> {
    Some(match cid {
        "beam" => "beam",
        "strip_footing" => "stripfooting",
        "pipe" => "pipe",
        "duct" => "duct",
        "conduit" => "conduit",
        "cable_tray" => "cabletray",
        "wire" => "wire",
        "down_conductor" => "downconductor",
        "ground_conductor" => "groundconductor",
        "cabling" => "cable",
        _ => return None,
    })
}

/// What a run command was asked, read and checked as the original does.
pub struct RunArgs {
    pub points: Vec<[f64; 2]>,
    pub closed: bool,
    pub level: u64,
    /// The type's name (or what was given, where the project has no such type: the model's check
    /// refuses it).
    pub type_name: String,
    pub offset: f64,
    pub end_offset: Option<f64>,
    pub justify: Justify,
    pub system: Option<String>,
}

impl RunArgs {
    /// The segments, one run each.
    pub fn segments(&self) -> Vec<([f64; 2], [f64; 2])> {
        segments(&self.points, self.closed)
    }
}

/// The segments of a chain: each point to the next, and the last back to the first when closed.
pub fn segments(points: &[[f64; 2]], closed: bool) -> Vec<([f64; 2], [f64; 2])> {
    let mut out: Vec<([f64; 2], [f64; 2])> = points.windows(2).map(|w| (w[0], w[1])).collect();
    if closed && points.len() >= 2 {
        out.push((points[points.len() - 1], points[0]));
    }
    out
}

pub fn read_args(s: &Session, cid: &str, cat: &str, p: &Value) -> R<RunArgs> {
    let pr = &s.project;
    let points = chain_points(p, cid)?;
    let closed = opt_bool(p, cid, "closed")?.unwrap_or(false);
    let level = level_param(pr, cid, p)?;
    let type_name = match opt_text(p, cid, "type")? {
        Some(t) => type_name_param(pr, &t),
        None => match crate::structure::types::default_type(pr, cat) {
            Some(t) => t,
            None => return Err(format!("{}: the model has no types for this", cid)),
        },
    };
    let offset = opt_num(p, cid, "offset")?.unwrap_or(0.0);
    let end_offset = opt_num(p, cid, "end_offset")?;
    let n = segments(&points, closed).len();
    if end_offset.is_some() && n != 1 {
        return Err(format!("{}: `end_offset` is the height of one run's end: give 2 points", cid));
    }
    let justify = match opt_text(p, cid, "justify")? {
        Some(j) => match Justify::parse(&j) {
            Some(x) => x,
            None => return Err(format!("{}: `justify` is top, centre or bottom, not `{}`", cid, j)),
        },
        None => default_justify(cat),
    };
    let system = opt_text(p, cid, "system")?.filter(|x| !x.is_empty());
    Ok(RunArgs { points, closed, level, type_name, offset, end_offset, justify, system })
}

/// A run as the file holds it.
pub fn run_json(
    cat: &str,
    type_ref: &str,
    level_guid: &str,
    a: [f64; 2],
    b: [f64; 2],
    offset: f64,
    end_offset: Option<f64>,
    justify: Justify,
    system: Option<&str>,
) -> Value {
    let mut m = Map::new();
    m.insert("guid", Value::s(&new_guid()));
    m.insert("category", Value::s(cat));
    m.insert("type", Value::s(type_ref));
    m.insert("level", Value::s(level_guid));
    m.insert("start", Value::from(a));
    m.insert("end", Value::from(b));
    m.insert("offset", Value::f(offset));
    if let Some(e) = end_offset {
        m.insert("end_offset", Value::f(e));
    }
    m.insert("justify", Value::s(justify.name()));
    if let Some(sys) = system {
        m.insert("system", Value::s(sys));
    }
    Value::Obj(m)
}

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let cat = category_of(cid).ok_or_else(|| format!("{}: not supported here", cid))?;
    let a = read_args(s, cid, cat, p)?;
    let level_guid = s.project.guid_of(a.level).unwrap_or_default();
    // the type by its GUID; a name the project hasn't stays a name, which the check refuses
    let type_ref = type_guid(&s.project, cat, &a.type_name).unwrap_or_else(|| a.type_name.clone());
    let mut ids = Vec::new();
    for (x, y) in a.segments() {
        let e = run_json(cat, &type_ref, &level_guid, x, y, a.offset, a.end_offset, a.justify, a.system.as_deref());
        ids.push(Value::u(add_element(s, e)));
    }
    Ok(crate::jobj! {"ids" => Value::Arr(ids)})
}
