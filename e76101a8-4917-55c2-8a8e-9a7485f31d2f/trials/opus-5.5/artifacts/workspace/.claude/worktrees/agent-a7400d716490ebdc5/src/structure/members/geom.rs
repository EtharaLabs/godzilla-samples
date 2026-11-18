//! Where a run and a column are: a run's centre line and section, a column's base, top and plan.
//! What IFC export, schedules, plans and rebar ask of a member, from the element as the file holds it.

use super::read::{element_by_guid, lib_by_guid, parse_guid};
use crate::json::Value;
use crate::project::Project;
use crate::structure::common::{type_kind, type_of, types_of};

/// Within this (mm) in plan a run's ends are one over the other: it stands.
pub const TOL: f64 = 1.0;

/// The steepest a beam or a strip footing may slope, degrees.
pub const MAX_SLOPE: f64 = 75.0;

/// A member's section, from its type: `width` across by `depth` deep, or round (`width` across).
#[derive(Clone, Debug, PartialEq)]
pub struct Section {
    pub width: f64,
    pub depth: f64,
    pub round: bool,
    /// The material's GUID (a run type's; a column type has none).
    pub material: Option<String>,
}

/// The line of a run's section its heights are given at.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Justify {
    Top,
    Centre,
    Bottom,
}

impl Justify {
    pub fn parse(s: &str) -> Option<Justify> {
        match s.to_lowercase().as_str() {
            "top" => Some(Justify::Top),
            "centre" | "center" => Some(Justify::Centre),
            "bottom" => Some(Justify::Bottom),
            _ => None,
        }
    }
    pub fn name(self) -> &'static str {
        match self {
            Justify::Top => "top",
            Justify::Centre => "centre",
            Justify::Bottom => "bottom",
        }
    }
    /// IFC's cardinal point of the line: top 8, middle 5, bottom 2.
    pub fn cardinal_point(self) -> u32 {
        match self {
            Justify::Top => 8,
            Justify::Centre => 5,
            Justify::Bottom => 2,
        }
    }
}

/// The justification a category's runs take unless told: a beam's and a strip footing's top,
/// any other's middle.
pub fn default_justify(cat: &str) -> Justify {
    match cat {
        "beam" | "stripfooting" => Justify::Top,
        _ => Justify::Centre,
    }
}

/// Whether a run of this category may stand upright (a riser): all but beams and strip footings.
pub fn may_stand(cat: &str) -> bool {
    !matches!(cat, "beam" | "stripfooting")
}

/// The type an element names (its `type`: a GUID of the category's library kind, or a name):
/// its name, if the project has a type of that name.
pub fn type_name(pr: &Project, e: &Value) -> Option<String> {
    let cat = e.get("category")?.as_str()?;
    let t = e.get("type")?.as_str()?;
    let types = types_of(pr, cat)?;
    if parse_guid(t).is_some() {
        if let Some(id) = lib_by_guid(pr, t) {
            let le = pr.library.get(&id)?;
            if le.get("kind").and_then(|k| k.as_str()) == Some(type_kind(cat).as_str()) {
                let n = le.get("name")?.as_str()?;
                return if types.contains(n) { Some(n.to_string()) } else { None };
            }
        }
    }
    if types.contains(t) {
        Some(t.to_string())
    } else {
        None
    }
}

/// The GUID of the type an element is of.
pub fn type_guid(pr: &Project, e: &Value) -> Option<String> {
    let cat = e.get("category")?.as_str()?;
    let name = type_name(pr, e)?;
    pr.lib_guid(&type_kind(cat), &name)
}

/// A type's section, as `types` holds it.
pub fn section_of_type(t: &Value) -> Section {
    let width = t.get("width").and_then(|x| x.as_f64()).unwrap_or(0.0);
    let round = t.get("round").and_then(|x| x.as_bool()).unwrap_or(false);
    let depth = t.get("depth").and_then(|x| x.as_f64()).unwrap_or(width);
    let material = t.get("material").and_then(|x| x.as_str()).map(|s| s.to_string());
    Section { width, depth, round, material }
}

/// The section of a run or a column, from its type.
pub fn section(pr: &Project, e: &Value) -> Option<Section> {
    let cat = e.get("category")?.as_str()?;
    let name = type_name(pr, e)?;
    Some(section_of_type(type_of(pr, cat, &name)?))
}

/// The level an element stands on (its `level`), when it is one.
pub fn level_of_element(pr: &Project, e: &Value, key: &str) -> Option<u64> {
    let g = e.get(key)?.as_str()?;
    let id = element_by_guid(pr, g)?;
    if pr.category(id) == Some("level") {
        Some(id)
    } else {
        None
    }
}

pub fn elevation(pr: &Project, level: u64) -> f64 {
    pr.el(level).and_then(|e| e.get("elevation")).and_then(|x| x.as_f64()).unwrap_or(0.0)
}

fn f(e: &Value, k: &str) -> Option<f64> {
    e.get(k).and_then(|x| x.as_f64())
}

fn pt(e: &Value, k: &str) -> Option<[f64; 2]> {
    let a = e.get(k)?.as_arr()?;
    Some([a.first()?.as_f64()?, a.get(1)?.as_f64()?])
}

/// A run's line where its heights are given: plan ends and their heights over its level.
#[derive(Clone, Debug, PartialEq)]
pub struct RunLine {
    pub start: [f64; 2],
    pub end: [f64; 2],
    /// `offset` and `end_offset` (the same when it has none), mm over the level.
    pub offset: f64,
    pub end_offset: f64,
    pub justify: Justify,
}

impl RunLine {
    /// Its length in plan.
    pub fn plan_length(&self) -> f64 {
        let dx = self.end[0] - self.start[0];
        let dy = self.end[1] - self.start[1];
        (dx * dx + dy * dy).sqrt()
    }
    /// How far its end is over its start.
    pub fn rise(&self) -> f64 {
        self.end_offset - self.offset
    }
    /// Its length along the slope.
    pub fn length(&self) -> f64 {
        let dx = self.end[0] - self.start[0];
        let dy = self.end[1] - self.start[1];
        let dz = self.rise();
        (dx * dx + dy * dy + dz * dz).sqrt()
    }
    /// Its ends are one over the other (within `TOL` in plan).
    pub fn stands(&self) -> bool {
        self.plan_length() <= TOL
    }
    /// Its slope from the horizontal, degrees (90 when it stands).
    pub fn slope_degrees(&self) -> f64 {
        self.rise().abs().atan2(self.plan_length()).to_degrees()
    }
}

/// The line a run's heights are given at, from the element.
pub fn run_line(e: &Value) -> Option<RunLine> {
    let start = pt(e, "start")?;
    let end = pt(e, "end")?;
    let offset = f(e, "offset").unwrap_or(0.0);
    let end_offset = f(e, "end_offset").unwrap_or(offset);
    let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("");
    let justify = e
        .get("justify")
        .and_then(|j| j.as_str())
        .and_then(Justify::parse)
        .unwrap_or_else(|| default_justify(cat));
    Some(RunLine { start, end, offset, end_offset, justify })
}

/// A run in the model: its centre line (absolute heights), its section, its length.
#[derive(Clone, Debug, PartialEq)]
pub struct RunGeom {
    pub line: RunLine,
    pub section: Section,
    /// The elevation of its level.
    pub elevation: f64,
    /// The centre line's ends, [x, y, z] with z absolute (the level's elevation added).
    pub axis: [[f64; 3]; 2],
    /// Along the slope, mm.
    pub length: f64,
    /// Half its section's depth measured plumb (depth / 2 / cos θ; 0 when it stands).
    pub half: f64,
    pub stands: bool,
}

/// How far below (or above) the justify line the centre line is, plumb: half the depth over the
/// cosine of the slope, or none for a run that stands.
pub fn plumb_half(line: &RunLine, sec: &Section) -> f64 {
    if line.stands() {
        return 0.0;
    }
    let h = line.plan_length();
    sec.depth / 2.0 * (line.length() / h)
}

/// The centre line's height at a point of the justify line.
pub fn centre_height(z: f64, justify: Justify, half: f64) -> f64 {
    match justify {
        Justify::Top => z - half,
        Justify::Centre => z,
        Justify::Bottom => z + half,
    }
}

/// A run's geometry, where its type and level are the model's.
pub fn run_geom(pr: &Project, e: &Value) -> Option<RunGeom> {
    let line = run_line(e)?;
    let section = section(pr, e)?;
    let elevation = level_of_element(pr, e, "level").map(|l| self::elevation(pr, l)).unwrap_or(0.0);
    Some(run_geom_of(line, section, elevation))
}

impl RunGeom {
    /// The way the run goes (a unit vector along its centre line) and the way its section's
    /// width lies (a unit vector across it, level: to the left of the line in plan, or east for
    /// one that stands); its depth lies along the first crossed with the second. As IFC writes a
    /// run: an extrusion along the first, its profile's x the second.
    pub fn frame(&self) -> ([f64; 3], [f64; 3]) {
        let a = self.axis[0];
        let b = self.axis[1];
        let d = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
        let len = (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt();
        let along = if len > 0.0 { [d[0] / len, d[1] / len, d[2] / len] } else { [0.0, 0.0, 1.0] };
        let h = (d[0] * d[0] + d[1] * d[1]).sqrt();
        let across = if self.stands || h == 0.0 { [1.0, 0.0, 0.0] } else { [-d[1] / h, d[0] / h, 0.0] };
        (along, across)
    }
    /// The centre line's start, its height over the run's level.
    pub fn start_over_level(&self) -> [f64; 3] {
        let a = self.axis[0];
        [a[0], a[1], a[2] - self.elevation]
    }
}

pub fn run_geom_of(line: RunLine, section: Section, elevation: f64) -> RunGeom {
    let half = plumb_half(&line, &section);
    let z0 = centre_height(elevation + line.offset, line.justify, half);
    let z1 = centre_height(elevation + line.end_offset, line.justify, half);
    let axis = [[line.start[0], line.start[1], z0], [line.end[0], line.end[1], z1]];
    let length = line.length();
    let stands = line.stands();
    RunGeom { line, section, elevation, axis, length, half, stands }
}

/// A column, a structural column or an isolated footing: where it stands and how high.
#[derive(Clone, Debug, PartialEq)]
pub struct ColumnGeom {
    pub at: [f64; 2],
    /// Degrees its width runs at, counter-clockwise from east.
    pub angle: f64,
    /// Absolute heights of its base and its top.
    pub base: f64,
    pub top: f64,
    pub section: Section,
}

impl ColumnGeom {
    pub fn height(&self) -> f64 {
        self.top - self.base
    }
}

/// The height a column has: from its base up to its top level, else to its own `height` over
/// its base (top less base, as the original works it out).
pub fn column_height(pr: &Project, e: &Value) -> Option<f64> {
    let (base, top) = column_span(pr, e)?;
    Some(top - base)
}

/// A column's top level, where it has one that is a level.
pub fn top_level_of(pr: &Project, e: &Value) -> Option<u64> {
    match e.get("top_level") {
        Some(Value::Str(_)) => level_of_element(pr, e, "top_level"),
        _ => None,
    }
}

/// A column's base and top, absolute.
pub fn column_span(pr: &Project, e: &Value) -> Option<(f64, f64)> {
    let level = level_of_element(pr, e, "level")?;
    let base = elevation(pr, level) + f(e, "base_offset").unwrap_or(0.0);
    let top = match top_level_of(pr, e) {
        Some(t) => elevation(pr, t),
        None => base + f(e, "height").unwrap_or(0.0),
    };
    Some((base, top))
}

pub fn column_geom(pr: &Project, e: &Value) -> Option<ColumnGeom> {
    let at = pt(e, "at")?;
    let angle = f(e, "angle").unwrap_or(0.0);
    let (base, top) = column_span(pr, e)?;
    let section = section(pr, e)?;
    Some(ColumnGeom { at, angle, base, top, section })
}

/// The corners of a rectangular column's plan, counter-clockwise (its width along `angle`).
pub fn column_outline(g: &ColumnGeom) -> Vec<[f64; 2]> {
    let (s, c) = g.angle.to_radians().sin_cos();
    let hw = g.section.width / 2.0;
    let hd = g.section.depth / 2.0;
    [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]]
        .iter()
        .map(|p| [g.at[0] + p[0] * c - p[1] * s, g.at[1] + p[0] * s + p[1] * c])
        .collect()
}
