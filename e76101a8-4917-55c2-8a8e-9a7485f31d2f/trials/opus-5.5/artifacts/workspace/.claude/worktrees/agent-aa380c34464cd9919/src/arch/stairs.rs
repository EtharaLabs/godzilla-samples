//! Stairs, ramps and railings: a stair's risers and runs with landings, a ramp's runs at its slope,
//! and railings down a stair's or a ramp's sides or along a path; their rules.

use super::util::*;
use crate::commands::params::{self, R};
use crate::geom::{self, P2};
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

pub const STAIR_ORDER: &[&str] = &["level", "top_level", "height", "start", "angle", "width", "riser", "tread", "landings", "params"];
pub const RAMP_ORDER: &[&str] = &["level", "top_level", "height", "start", "angle", "width", "slope", "landings", "params"];
pub const RAILING_ORDER: &[&str] = &["type", "level", "path", "base_offset", "host", "side", "params"];

/// Landings as serde reads `Vec<Landing {at, turn}>`.
fn de_landings(v: &Value) -> Result<Vec<(f64, f64)>, String> {
    let Value::Arr(a) = v else {
        return Err(format!("invalid type: {}, expected a sequence", v.kind_name()));
    };
    let mut out = Vec::new();
    let num = |y: &Value| match y {
        Value::Num(n) => Ok(n.as_f64()),
        o => Err(format!("invalid type: {}, expected f64", o.kind_name())),
    };
    for x in a {
        // a sequence of its fields in order: at, then turn (0 when left out)
        if let Value::Arr(f) = x {
            let at = num(f.first().ok_or_else(|| "invalid length 0, expected struct Landing with 2 elements".to_string())?)?;
            let turn = match f.get(1) {
                Some(y) => num(y)?,
                None => 0.0,
            };
            if f.len() > 2 {
                return Err(format!("invalid length {}, expected fewer elements in array", f.len()));
            }
            out.push((at, turn));
            continue;
        }
        let Value::Obj(m) = x else {
            return Err(format!("invalid type: {}, expected struct Landing", x.kind_name()));
        };
        let mut at = None;
        let mut turn = None;
        for (k, y) in &m.items {
            match k.as_str() {
                "at" => match y {
                    Value::Num(n) => at = Some(n.as_f64()),
                    o => return Err(format!("invalid type: {}, expected f64", o.kind_name())),
                },
                "turn" => match y {
                    Value::Num(n) => turn = Some(n.as_f64()),
                    o => return Err(format!("invalid type: {}, expected f64", o.kind_name())),
                },
                other => return Err(format!("unknown field `{}`, expected `at` or `turn`", other)),
            }
        }
        let at = at.ok_or_else(|| "missing field `at`".to_string())?;
        out.push((at, turn.unwrap_or(0.0)));
    }
    Ok(out)
}

/// The angle (degrees from east) a stair climbs toward a point, to a billionth of a degree.
pub fn angle_to(a: P2, b: P2) -> f64 {
    let deg = (b[1] - a[1]).atan2(b[0] - a[0]).to_degrees();
    (deg * 1e9).round() / 1e9
}

/// The parameters stairs and ramps share: start, angle, level, top, height, width, landings,
/// railings.
struct Common {
    start: P2,
    angle: f64,
    level: u64,
    top: Option<u64>,
    height: Option<f64>,
    width: Option<f64>,
    landings: Option<Vec<(f64, f64)>>,
    railings: bool,
}

fn common(s: &Session, p: &Value, c: &str, own: &mut dyn FnMut() -> R<()>) -> R<Common> {
    let start = params::req_point(p, c, "start")?;
    let end = params::opt_point(p, c, "end")?;
    let angle = params::opt_num(p, c, "angle")?;
    let angle = match end {
        Some(e) => {
            if !(geom::dist(start, e) > 1.0) {
                return Err(format!("{}: `end` must be away from `start`: it says which way the {} climbs", c, c));
            }
            angle_to(start, e)
        }
        None => angle.unwrap_or(0.0),
    };
    let pr = &s.project;
    let level = crate::model::level_param(pr, c, p, "level")?;
    let height = params::opt_num(p, c, "height")?;
    let top_level = match params::get(p, "top_level") {
        Some(v) => Some(crate::model::resolve_level(pr, c, "top_level", v)?),
        None => None,
    };
    let width = params::opt_num(p, c, "width")?;
    own()?;
    let landings = match params::get(p, "landings") {
        None => None,
        Some(v) => match de_landings(v) {
            Ok(l) if l.len() <= 100 => Some(l),
            Ok(_) => return Err(format!("{}: `landings` is a list of at most 100 landings [{{at, turn?}}, …]", c)),
            Err(e) => {
                if matches!(v, Value::Arr(_)) {
                    return Err(format!("{}: `landings`: {}", c, e));
                }
                return Err(format!("{}: `landings` is a list of at most 100 landings [{{at, turn?}}, …]", c));
            }
        },
    };
    let railings = params::opt_bool(p, c, "railings")?.unwrap_or(false);
    let top = match top_level {
        Some(t) => Some(t),
        None if height.is_some() => None,
        None => crate::model::level_above(pr, level),
    };
    Ok(Common { start, angle, level, top, height, width, landings, railings })
}

fn landings_v(l: &[(f64, f64)]) -> Value {
    Value::Arr(l.iter().map(|(a, t)| jobj! {"at" => *a, "turn" => *t}).collect())
}

/// How tall a stair or ramp climbs: to its top level, else its height.
pub fn rise(pr: &Project, e: &Value) -> f64 {
    let base = level_of(pr, e).map(|l| elev(pr, l)).unwrap_or(0.0);
    match e.get("top_level").and_then(|v| by_ref(pr, v)).filter(|l| pr.category(*l) == Some("level")) {
        Some(t) => elev(pr, t) - base,
        None => numd(e, "height", 3000.0),
    }
}

/// A stair's risers: as many as keep each at most its riser.
pub fn risers(pr: &Project, e: &Value) -> i64 {
    let h = rise(pr, e);
    let r = numd(e, "riser", 180.0);
    (h / r).ceil() as i64
}

/// The length of a stair's runs along their walk lines: a tread for each riser but the last of
/// each run.
pub fn stair_length(pr: &Project, e: &Value) -> f64 {
    let n = risers(pr, e);
    let runs = e.get("landings").and_then(|l| l.as_arr()).map(|a| a.len()).unwrap_or(0) as i64 + 1;
    let tread = numd(e, "tread", 280.0);
    ((n - runs) as f64) * tread
}

/// The length of a ramp's runs: its rise over its slope, to a hundredth of a millimetre.
pub fn ramp_length(pr: &Project, e: &Value) -> f64 {
    let h = rise(pr, e);
    let s = numd(e, "slope", 100.0 / 12.0);
    let l = h * 100.0 / s;
    (l * 100.0).round() / 100.0
}

fn make_railings(s: &mut Session, host: u64, level: u64, sides: &[&str], ty: &str) -> Vec<u64> {
    let mut ids = Vec::new();
    for side in sides {
        let pr = &s.project;
        let mut e = jobj! {
            "guid" => crate::rand::guid(),
            "category" => "railing",
            "type" => type_ref(pr, "railing", ty),
            "level" => level_guid(pr, level),
            "host" => pr.guid_of(host).unwrap_or_default(),
            "side" => *side,
        };
        crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
        let id = s.project.alloc_id();
        s.project.elements.insert(id, e);
        ids.push(id);
    }
    ids
}

pub fn cmd_stair(s: &mut Session, p: &Value) -> R<Value> {
    let c = "stair";
    let mut riser = None;
    let mut tread = None;
    let cm = {
        let mut own = || -> R<()> {
            riser = params::opt_num(p, c, "riser")?;
            tread = params::opt_num(p, c, "tread")?;
            Ok(())
        };
        common(s, p, c, &mut own)?
    };
    let pr = &s.project;
    let mut e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => c,
        "level" => level_guid(pr, cm.level),
        "top_level" => match cm.top { Some(t) => Value::Str(level_guid(pr, t)), None => Value::Null },
        "height" => cm.height.unwrap_or(3000.0),
        "start" => pv(cm.start),
        "angle" => cm.angle,
        "width" => cm.width.unwrap_or(1000.0),
        "riser" => riser.unwrap_or(180.0),
        "tread" => tread.unwrap_or(280.0),
    };
    if let Some(l) = &cm.landings {
        if !l.is_empty() {
            e.set("landings", landings_v(l));
        }
    }
    crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
    let id = s.project.alloc_id();
    s.project.elements.insert(id, e);
    let rails = if cm.railings {
        let ty = default_type(&s.project, "railing").unwrap_or_default();
        make_railings(s, id, cm.level, &["left", "right"], &ty)
    } else {
        Vec::new()
    };
    let pr = &s.project;
    let e = pr.el(id).unwrap();
    Ok(jobj! {"id" => id, "length" => stair_length(pr, e), "railings" => rails, "risers" => risers(pr, e)})
}

pub fn cmd_ramp(s: &mut Session, p: &Value) -> R<Value> {
    let c = "ramp";
    let mut slope = None;
    let cm = {
        let mut own = || -> R<()> {
            slope = params::opt_num(p, c, "slope")?;
            Ok(())
        };
        common(s, p, c, &mut own)?
    };
    let pr = &s.project;
    let mut e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => c,
        "level" => level_guid(pr, cm.level),
        "top_level" => match cm.top { Some(t) => Value::Str(level_guid(pr, t)), None => Value::Null },
        "height" => cm.height.unwrap_or(3000.0),
        "start" => pv(cm.start),
        "angle" => cm.angle,
        "width" => cm.width.unwrap_or(1200.0),
        "slope" => slope.unwrap_or(100.0 / 12.0),
    };
    if let Some(l) = &cm.landings {
        if !l.is_empty() {
            e.set("landings", landings_v(l));
        }
    }
    crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
    let id = s.project.alloc_id();
    s.project.elements.insert(id, e);
    let rails = if cm.railings {
        let ty = default_type(&s.project, "railing").unwrap_or_default();
        make_railings(s, id, cm.level, &["left", "right"], &ty)
    } else {
        Vec::new()
    };
    let pr = &s.project;
    let e = pr.el(id).unwrap();
    Ok(jobj! {"id" => id, "length" => ramp_length(pr, e), "railings" => rails})
}

pub fn cmd_railing(s: &mut Session, p: &Value) -> R<Value> {
    let c = "railing";
    let ty = params::opt_text(p, c, "type")?;
    let host = opt_ref(p, c, "host")?;
    let pr = &s.project;
    if let Some(h) = host {
        let hid = match by_ref(pr, &h) {
            Some(id) if matches!(pr.category(id), Some("stair") | Some("ramp")) => id,
            _ => return Err(format!("railing: no stair or ramp {}", ref_word(pr, &h))),
        };
        let side = match params::opt_text(p, c, "side")? {
            None => None,
            Some(x) => match x.as_str() {
                "left" | "right" => Some(x),
                _ => return Err(format!("railing: `side` is left or right, going up, not `{}`", x)),
            },
        };
        let level = pr.el(hid).and_then(|e| level_of(pr, e)).unwrap_or(0);
        let ty = ty.or_else(|| default_type(pr, c)).unwrap_or_default();
        let sides: Vec<&str> = match &side {
            Some(x) => vec![x.as_str()],
            None => vec!["left", "right"],
        };
        let ids = make_railings(s, hid, level, &sides, &ty);
        return Ok(jobj! {"ids" => ids});
    }
    let level = crate::model::level_param(pr, c, p, "level")?;
    let path = match params::get(p, "path") {
        Some(Value::Arr(a)) => {
            let mut out = Vec::new();
            for x in a {
                match params::point_of(x) {
                    Some(q) => out.push(q),
                    None => return Err(format!("railing: `path`: {} is not a point [x, y] in mm", x.to_compact())),
                }
            }
            out
        }
        _ => return Err("railing: `path` [[x, y], …] is required".into()),
    };
    let base_offset = params::opt_num(p, c, "base_offset")?;
    let ty = ty.or_else(|| default_type(pr, c)).unwrap_or_default();
    let mut e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => c,
        "type" => type_ref(pr, c, &ty),
        "level" => level_guid(pr, level),
        "path" => ring_v(&path),
    };
    if let Some(b) = base_offset {
        if b != 0.0 {
            e.set("base_offset", Value::f(b));
        }
    }
    crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
    let id = s.project.alloc_id();
    s.project.elements.insert(id, e);
    Ok(jobj! {"ids" => vec![id]})
}

// ---------------------------------------------------------------- the rules

fn turn_ok(t: f64) -> bool {
    t == 0.0 || t == 90.0 || t == -90.0 || t == 180.0 || t == -180.0
}

const TURNS: &str = "a landing turns 0 (straight on), 90 or -90 (left or right), or 180 or -180 (back beside the run, to its left or its right)";

fn positive(c: &str, id: u64, e: &Value, k: &str, dflt: f64) -> R<()> {
    let x = numd(e, k, dflt);
    if !(x > 0.0) {
        return Err(format!("{} {} {} must be above zero, got {}", c, id, k, d(x)));
    }
    Ok(())
}

fn landings_of(e: &Value) -> Vec<(f64, f64)> {
    e.get("landings")
        .and_then(|l| l.as_arr())
        .map(|a| a.iter().map(|l| (numd(l, "at", 0.0), numd(l, "turn", 0.0))).collect())
        .unwrap_or_default()
}

pub fn check_stair(pr: &Project, id: u64, e: &Value) -> R<()> {
    let has_top = e.get("top_level").map(|v| !v.is_null()).unwrap_or(false);
    if !has_top {
        positive("stair", id, e, "height", 3000.0)?;
    }
    positive("stair", id, e, "width", 1000.0)?;
    positive("stair", id, e, "riser", 180.0)?;
    positive("stair", id, e, "tread", 280.0)?;
    let n = risers(pr, e);
    if !(2..=200).contains(&n) {
        return Err(format!(
            "stair {}: {} risers; a stair takes 2 to 200, so check its height and its riser ({} mm)",
            id,
            n,
            d(numd(e, "riser", 180.0))
        ));
    }
    let mut prev = 0.0;
    for (at, turn) in landings_of(e) {
        if !turn_ok(turn) {
            return Err(format!("stair {}: {}, not {}", id, TURNS, d(turn)));
        }
        if at.fract() != 0.0 {
            return Err(format!("stair {}: a landing goes after a whole number of risers, not {}", id, d(at)));
        }
        if at - prev < 2.0 || n as f64 - at < 2.0 {
            return Err(format!(
                "stair {}: a landing after {} risers leaves a run of fewer than 2 risers; each run needs 2 or more",
                id,
                d(at)
            ));
        }
        prev = at;
    }
    Ok(())
}

pub fn check_ramp(pr: &Project, id: u64, e: &Value) -> R<()> {
    let has_top = e.get("top_level").map(|v| !v.is_null()).unwrap_or(false);
    if !has_top {
        positive("ramp", id, e, "height", 3000.0)?;
    }
    positive("ramp", id, e, "width", 1200.0)?;
    let slope = numd(e, "slope", 100.0 / 12.0);
    if !(1.0..=50.0).contains(&slope) {
        return Err(format!("ramp {}: slope {}% isn't from 1% to 50%", id, d(slope)));
    }
    let h = rise(pr, e);
    if !(h > 0.0) {
        return Err(format!("ramp {}: its top must be above its base", id));
    }
    let mut prev = 0.0;
    for (at, turn) in landings_of(e) {
        if !turn_ok(turn) {
            return Err(format!("ramp {}: {}, not {}", id, TURNS, d(turn)));
        }
        if !(at - prev > 1.0) {
            return Err(format!("ramp {}: a landing {} mm up isn't above its foot or the landing before it", id, d(at)));
        }
        if !(h - at > 1.0) {
            return Err(format!("ramp {}: a landing {} mm up isn't below its top, {} mm up", id, d(at), d(h)));
        }
        prev = at;
    }
    Ok(())
}

pub fn check_railing(pr: &Project, id: u64, e: &Value) -> R<()> {
    check_type(pr, id, e, "railing")?;
    if let Some(h) = e.get("host") {
        if !h.is_null() {
            return Ok(());
        }
    }
    let path = pts(e, "path").unwrap_or_default();
    if path.len() < 2 || path.len() > 10000 {
        return Err(format!("railing {}: a path needs 2 to 10000 points", id));
    }
    let len: f64 = path.windows(2).map(|w| geom::dist(w[0], w[1])).sum();
    if !(len > 1.0) {
        return Err(format!("railing {}: its path has no length", id));
    }
    Ok(())
}

// ---------------------------------------------------------------- the layout

/// A stair's or a ramp's runs in plan: each run's walk line (its centre, foot to head) and its
/// direction, the landings' turns between them, and where the last run ends.
#[derive(Clone, Debug)]
pub struct Layout {
    pub runs: Vec<(P2, P2)>,
    pub dirs: Vec<P2>,
    pub turns: Vec<f64>,
    pub width: f64,
    pub end: P2,
    /// the runs' lengths in all (the landings aside)
    pub length: f64,
}

/// The runs of a stair (a tread for each riser but the last of each run) or a ramp (its rise
/// between landings over its slope): from `start` toward `angle`, each landing as deep as the
/// stair is wide, turning left (90), right (-90), or back beside the run (180 to its left, -180
/// to its right).
pub fn layout(pr: &Project, e: &Value) -> Layout {
    let ramp = cat(e) == "ramp";
    let start = pt(e, "start").unwrap_or([0.0, 0.0]);
    let angle = numd(e, "angle", 0.0).to_radians();
    let width = numd(e, "width", if ramp { 1200.0 } else { 1000.0 });
    let lands = landings_of(e);
    let mut lens = Vec::new();
    if ramp {
        let h = rise(pr, e);
        let per = 100.0 / numd(e, "slope", 100.0 / 12.0);
        let mut prev = 0.0;
        for (at, _) in &lands {
            lens.push((at - prev) * per);
            prev = *at;
        }
        lens.push((h - prev) * per);
    } else {
        let n = risers(pr, e) as f64;
        let tread = numd(e, "tread", 280.0);
        let mut prev = 0.0;
        for (at, _) in &lands {
            lens.push((at - prev - 1.0) * tread);
            prev = *at;
        }
        lens.push((n - prev - 1.0) * tread);
    }
    let mut u = [angle.cos(), angle.sin()];
    let mut p = start;
    let mut runs = Vec::new();
    let mut dirs = Vec::new();
    let mut turns = Vec::new();
    for (k, len) in lens.iter().enumerate() {
        let q = geom::add(p, geom::scale(u, *len));
        runs.push((p, q));
        dirs.push(u);
        if let Some((_, turn)) = lands.get(k) {
            let l = geom::left(u);
            let t = *turn;
            turns.push(t);
            if t == 90.0 || t == -90.0 {
                let side = if t > 0.0 { 1.0 } else { -1.0 };
                p = geom::add(q, geom::add(geom::scale(u, width / 2.0), geom::scale(l, side * width / 2.0)));
                u = geom::scale(l, side);
            } else if t == 180.0 || t == -180.0 {
                let side = if t > 0.0 { 1.0 } else { -1.0 };
                p = geom::add(q, geom::scale(l, side * width));
                u = geom::scale(u, -1.0);
            } else {
                p = geom::add(q, geom::scale(u, width));
            }
        }
    }
    let end = runs.last().map(|r| r.1).unwrap_or(start);
    Layout { runs, dirs, turns, width, end, length: lens.iter().sum() }
}

/// A railing's path: its own, or down its host's side 50 mm in from its edge, round the landings.
pub fn railing_path(pr: &Project, e: &Value) -> Vec<P2> {
    let host = e.get("host").filter(|h| !h.is_null()).and_then(|h| by_ref(pr, h)).and_then(|h| pr.el(h));
    let Some(h) = host else {
        return pts(e, "path").unwrap_or_default();
    };
    let lay = layout(pr, h);
    let left = text(e, "side") != Some("right");
    let sgn = if left { 1.0 } else { -1.0 };
    let off = lay.width / 2.0 - 50.0;
    let side = |k: usize, q: P2| geom::add(q, geom::scale(geom::left(lay.dirs[k]), sgn * off));
    let mut out = Vec::new();
    for (k, (a, b)) in lay.runs.iter().enumerate() {
        if k == 0 {
            out.push(side(0, *a));
        }
        let eb = side(k, *b);
        out.push(eb);
        if let Some(t) = lay.turns.get(k) {
            let next = side(k + 1, lay.runs[k + 1].0);
            if *t != 0.0 {
                let inner = (*t > 0.0) == left;
                let dd = if inner { 50.0 } else { lay.width - 50.0 };
                out.push(geom::add(eb, geom::scale(lay.dirs[k], dd)));
                if *t == 180.0 || *t == -180.0 {
                    out.push(geom::add(next, geom::scale(lay.dirs[k], dd)));
                }
            }
            out.push(next);
        }
    }
    out
}

#[cfg(test)]
mod layout_tests {
    /// Prints each stair's or ramp's runs and its railings' paths, a line of commands from
    /// STAIRS_FILE at a time, as `elements` rounds them.
    #[test]
    fn runs_and_rails() {
        let Ok(path) = std::env::var("STAIRS_FILE") else { return };
        let text = std::fs::read_to_string(path).unwrap();
        let r3 = |p: super::P2| [(p[0] * 1000.0).round() / 1000.0, (p[1] * 1000.0).round() / 1000.0];
        for line in text.lines().filter(|l| !l.trim().is_empty()) {
            let mut s = crate::session::Session::new();
            let (cmd, rest) = line.split_once(' ').unwrap();
            let p = crate::json::parse(rest).unwrap();
            if let Err(e) = s.execute(cmd, &p) {
                println!("== {}\n  ERR {}", line, e);
                continue;
            }
            let _ = s.execute("railing", &crate::json::parse(r#"{"host": 100002}"#).unwrap());
            let pr = &s.project;
            let e = pr.el(100002).unwrap();
            let lay = super::layout(pr, e);
            let runs: Vec<String> = lay.runs.iter().map(|(a, b)| format!("[{:?}, {:?}]", r3(*a), r3(*b))).collect();
            println!("== {}\n  end {:?} length {} runs [{}]", line, r3(lay.end), lay.length, runs.join(", "));
            for id in [100003u64, 100004] {
                if let Some(r) = pr.el(id) {
                    let path: Vec<String> = super::railing_path(pr, r).iter().map(|q| format!("{:?}", r3(*q))).collect();
                    println!("   rail {} [{}]", super::text(r, "side").unwrap_or(""), path.join(", "));
                }
            }
        }
    }
}
