//! Sections and elevations: `section`, `elevation` (the four building elevations, `facing`, `at`).

use super::common::*;
use super::plans::shows;
use crate::commands::params::{opt_num, opt_point, opt_text, req_point};
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "section" => section(s, p),
        _ => elevation(s, p),
    }
}

// ---------------------------------------------------------------- names

pub const SECTION_WORD: [&str; 9] = ["Section", "Corte", "Sección", "Sektion", "Řez", "Coupe", "Doorsnede", "Schnitt", "Sezione"];
pub const ELEVATION_WORD: [&str; 9] = ["Elevation", "Elevação", "Elevación", "Fasad", "Pohled", "Élévation", "Gevel", "Ansicht", "Prospetto"];
const NORTH: [&str; 9] = ["North", "Norte", "Norte", "Norr", "Sever", "Nord", "Noord", "Norden", "Nord"];
const SOUTH: [&str; 9] = ["South", "Sul", "Sur", "Söder", "Jih", "Sud", "Zuid", "Süden", "Sud"];
const EAST: [&str; 9] = ["East", "Leste", "Este", "Öster", "Východ", "Est", "Oost", "Osten", "Est"];
const WEST: [&str; 9] = ["West", "Oeste", "Oeste", "Väster", "Západ", "Ouest", "West", "Westen", "Ovest"];

/// The categories whose names are views' names, which no two may share.
pub const NAMED_VIEWS: &[&str] = &["planview", "section", "elevation", "view3d", "schedule"];

/// Every name a view (or a level) goes by.
pub fn taken_names(pr: &Project) -> Vec<String> {
    pr.elements
        .values()
        .filter(|e| NAMED_VIEWS.contains(&cat(e)) || cat(e) == "level")
        .filter_map(|e| s_of(e, "name").map(|s| s.to_string()))
        .collect()
}

/// `<word> n`, the first n no view has.
pub fn numbered_name(pr: &Project, word: &str) -> String {
    let taken = taken_names(pr);
    let mut n = 1u64;
    loop {
        let c = format!("{} {}", word, n);
        if !taken.contains(&c) {
            return c;
        }
        n += 1;
    }
}

/// The word itself where no view has it, else `<word> 2`, `<word> 3`…
pub fn word_name(pr: &Project, word: &str) -> String {
    let taken = taken_names(pr);
    if !taken.iter().any(|t| t == word) {
        return word.to_string();
    }
    let mut n = 2u64;
    loop {
        let c = format!("{} {}", word, n);
        if !taken.contains(&c) {
            return c;
        }
        n += 1;
    }
}

// ---------------------------------------------------------------- section

fn section(s: &mut Session, p: &Value) -> R<Value> {
    let start = req_point(p, "section", "start")?;
    let end = req_point(p, "section", "end")?;
    let depth = opt_num(p, "section", "depth")?;
    let name = opt_text(p, "section", "name")?;
    let pr = &mut s.project;
    let name = match name {
        Some(n) => n,
        None => numbered_name(pr, word(pr, SECTION_WORD)),
    };
    let id = make_view(pr, "section", &name, start, end, depth);
    Ok(jobj! {"id" => id, "name" => name})
}

fn make_view(pr: &mut Project, cat: &str, name: &str, start: [f64; 2], end: [f64; 2], depth: Option<f64>) -> u64 {
    let id = pr.alloc_id();
    pr.elements.insert(
        id,
        jobj! {
            "guid" => crate::rand::guid(),
            "category" => cat,
            "name" => name,
            "start" => start,
            "end" => end,
            "depth" => match depth { Some(d) => Value::f(d), None => Value::Null },
        },
    );
    id
}

// ---------------------------------------------------------------- elevation

#[derive(Clone, Copy, PartialEq, Debug)]
enum Side {
    North,
    South,
    East,
    West,
}

impl Side {
    fn word(self, pr: &Project) -> &'static str {
        word(
            pr,
            match self {
                Side::North => NORTH,
                Side::South => SOUTH,
                Side::East => EAST,
                Side::West => WEST,
            },
        )
    }
}

/// An elevation's line round the box: 3 m out from the side it shows (or through `at`), a metre
/// past the box at each end, looking at the building.
fn side_line(side: Side, (lo, hi): shows::BBox, at: Option<[f64; 2]>) -> ([f64; 2], [f64; 2]) {
    const OUT: f64 = 3000.0;
    const PAST: f64 = 1000.0;
    match side {
        Side::North => {
            let y = at.map_or(hi[1] + OUT, |a| a[1]);
            ([hi[0] + PAST, y], [lo[0] - PAST, y])
        }
        Side::South => {
            let y = at.map_or(lo[1] - OUT, |a| a[1]);
            ([lo[0] - PAST, y], [hi[0] + PAST, y])
        }
        Side::East => {
            let x = at.map_or(hi[0] + OUT, |a| a[0]);
            ([x, lo[1] - PAST], [x, hi[1] + PAST])
        }
        Side::West => {
            let x = at.map_or(lo[0] - OUT, |a| a[0]);
            ([x, hi[1] + PAST], [x, lo[1] - PAST])
        }
    }
}

/// The side of the box a point is on, as seen from its middle.
fn side_of((lo, hi): shows::BBox, at: [f64; 2]) -> Side {
    let c = [(lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0];
    let dx = at[0] - c[0];
    let dy = at[1] - c[1];
    if dx.abs() > dy.abs() {
        if dx > 0.0 {
            Side::East
        } else {
            Side::West
        }
    } else if dy > 0.0 {
        Side::North
    } else {
        Side::South
    }
}

fn elevation(s: &mut Session, p: &Value) -> R<Value> {
    const CMD: &str = "elevation";
    let depth = opt_num(p, CMD, "depth")?;
    let name = opt_text(p, CMD, "name")?;
    let at = opt_point(p, CMD, "at")?;
    let facing = match opt_text(p, CMD, "facing")? {
        None => None,
        Some(f) => Some(match f.to_lowercase().as_str() {
            "north" => Side::North,
            "south" => Side::South,
            "east" => Side::East,
            "west" => Side::West,
            _ => return Err(format!("{}: `facing` is north, south, east or west, not `{}`", CMD, f)),
        }),
    };
    let start = opt_point(p, CMD, "start")?;
    let end = opt_point(p, CMD, "end")?;
    let pr = &mut s.project;
    match (start, end) {
        (Some(a), Some(b)) => {
            let name = match name {
                Some(n) => n,
                None => numbered_name(pr, word(pr, ELEVATION_WORD)),
            };
            let id = make_view(pr, "elevation", &name, a, b, depth);
            return Ok(jobj! {"id" => id, "name" => name});
        }
        (None, None) => {}
        _ => return Err(format!("{}: give both `start` and `end`, or neither", CMD)),
    }
    let Some(bx) = shows::walls_and_floors_box(pr) else {
        return Err(format!(
            "{}: there are no walls or floors to look at; draw some, or give `start` and `end`",
            CMD
        ));
    };
    let one = match (facing, at) {
        (Some(f), _) => Some(f),
        (None, Some(a)) => Some(side_of(bx, a)),
        (None, None) => None,
    };
    if let Some(side) = one {
        let (a, b) = side_line(side, bx, at);
        let name = match name {
            Some(n) => n,
            None => word_name(pr, side.word(pr)),
        };
        let id = make_view(pr, "elevation", &name, a, b, depth);
        return Ok(jobj! {"id" => id, "name" => name});
    }
    // the four building elevations not there yet
    let mut ids = Vec::new();
    let mut last = String::new();
    for side in [Side::North, Side::South, Side::East, Side::West] {
        let w = side.word(pr);
        let there = pr.elements.values().any(|e| cat(e) == "elevation" && s_of(e, "name") == Some(w));
        if there {
            continue;
        }
        let (a, b) = side_line(side, bx, None);
        let nm = match &name {
            Some(n) => n.clone(),
            None => word_name(pr, w),
        };
        ids.push(Value::u(make_view(pr, "elevation", &nm, a, b, depth)));
        last = nm;
    }
    match ids.len() {
        0 => Err(format!("{}: the four building elevations are there already", CMD)),
        // one made is one view, as `facing` makes it
        1 => Ok(jobj! {"id" => ids.pop().unwrap(), "name" => last}),
        _ => Ok(jobj! {"ids" => Value::Arr(ids)}),
    }
}

// ---------------------------------------------------------------- the model's rules

/// The model rules of this part, checked after every command: those of every view and sheet
/// this area keeps are checked in one pass, element by element, in `views_check`.
pub fn check(pr: &Project) -> R<()> {
    super::plans::views_check(pr)
}

/// A section's or an elevation's own rules: a name, a length, a depth, a crop that runs up.
pub fn check_line_view(pr: &Project, id: u64, e: &Value) -> R<()> {
    let c = cat(e);
    let name = s_of(e, "name").unwrap_or("");
    if name.trim().is_empty() {
        return Err(format!("{} {}: a view needs a name", c, id));
    }
    let (_, _, len, _) = shows::view_line(e);
    if !(len > 1.0) {
        return Err(format!("{} {}: too short ({} mm)", c, id, disp(len)));
    }
    if let Some(d) = f_of(e, "depth") {
        if !(d > 0.0) {
            return Err(format!("{} {} depth must be above zero, got {}", c, id, disp(d)));
        }
    }
    if let Some(a) = e.get("crop").and_then(|x| x.as_arr()) {
        if a.len() == 2 {
            let b = a[0].as_f64().unwrap_or(0.0);
            let t = a[1].as_f64().unwrap_or(0.0);
            if !(t - b > 1.0) {
                return Err(format!(
                    "{} {}: its crop runs from a bottom up to a top above it, not from {} to {}",
                    c,
                    id,
                    disp(b),
                    disp(t)
                ));
            }
        }
    }
    let _ = pr;
    Ok(())
}

/// What `elements` shows of this part's elements beyond their own fields: how long the line is,
/// and the way it looks.
pub fn element_view(pr: &Project, id: u64, x: &mut Value) {
    let Some(e) = pr.el(id) else { return };
    let s = pt_of(e, "start").unwrap_or([0.0, 0.0]);
    let t = pt_of(e, "end").unwrap_or([0.0, 0.0]);
    let dx = t[0] - s[0];
    let dy = t[1] - s[1];
    let len = (dx * dx + dy * dy).sqrt();
    x.set("length", Value::f(len));
    // a unit vector as the original makes one: times the reciprocal of its length
    let inv = 1.0 / len;
    let look = if len > 0.0 { [-(dy * inv), dx * inv] } else { [0.0, 0.0] };
    x.set("looking", Value::from([zero(look[0]), zero(look[1])]));
}

/// -0 as 0, as the original shows a direction.
fn zero(v: f64) -> f64 {
    if v == 0.0 {
        0.0
    } else {
        v
    }
}
