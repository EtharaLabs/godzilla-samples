//! Fill patterns made of detail lines: `make_fill_pattern`, as pyRevit's Make Pattern makes one.
//!
//! The lines picked are cut to the tile (the rectangle between `from` and `to`); each chord of
//! what is left becomes a family of parallel lines that runs on into the next tiles' copies of
//! itself: one at a slope `(i W, j H)` of whole tiles (`i`, `j` at most 48), so one drawn at
//! another is turned to the simplest such slope within 0.25° (else the nearest). Its dashes are
//! its length and a space to the repeat `L = |(i W, j H)|`, its lines `W H / L` apart, each shifted
//! along by the lattice's other vector. The pattern is kept as `fill_pattern` keeps one.

use super::common::*;
use super::regions::curve::{self, P};
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;
use crate::styles::fills::{Hatch, Pattern};

const MP: &str = "make_fill_pattern";
/// The most tiles across or up a family's slope may step.
const MAX_STEPS: i64 = 48;
/// How far a line may be turned to a slope that repeats, in degrees.
const TURN: f64 = 0.25;

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "make_fill_pattern" => make(s, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

/// The model rules of this part, checked after every command.
pub fn check(pr: &Project) -> R<()> {
    let _ = pr;
    Ok(())
}

/// The scale (1 : n, its n) a view draws at: a sheet's paper is 1 : 1, a view's own scale, else
/// 1 : 100.
pub fn view_scale(pr: &Project, view: u64) -> f64 {
    let Some(e) = pr.el(view) else { return 100.0 };
    if cat(e) == "sheet" {
        return 1.0;
    }
    let own = |e: &Value| e.get("graphics").and_then(|g| g.get("scale")).and_then(|x| x.as_f64());
    if let Some(s) = own(e) {
        return s;
    }
    // a dependent view draws as its parent does
    if let Some(parent) = ref_id(pr, e, "parent").and_then(|p| pr.el(p)) {
        if let Some(s) = own(parent) {
            return s;
        }
    }
    100.0
}

/// The most families a pattern holds.
const MAX_FAMILIES: usize = 256;
/// The least distance between a family's lines.
const MIN_SPACING: f64 = 0.05;

/// `target`, as serde reads a unit enum (a string, or a map of one key to null): Some(true) for
/// model.
fn target_param(p: &Value) -> R<Option<bool>> {
    let err = |e: String| format!("{}: `target` is drafting or model: {}", MP, e);
    let variant = |s: &str| match s {
        "drafting" => Ok(false),
        "model" => Ok(true),
        _ => Err(format!("unknown variant `{}`, expected `drafting` or `model`", s)),
    };
    match p.get("target") {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Str(s)) => variant(s).map(Some).map_err(err),
        Some(Value::Obj(m)) => {
            if m.len() != 1 {
                return Err(err("invalid value: map, expected map with a single key".into()));
            }
            let (k, v) = &m.items[0];
            let t = variant(k).map_err(err)?;
            if !v.is_null() {
                return Err(err(crate::styles::common::invalid_type(v, "unit")));
            }
            Ok(Some(t))
        }
        Some(v) => Err(err(crate::styles::common::invalid_type(v, "string or map"))),
    }
}

/// The pattern's families as a fill pattern must have them ("the pattern line 1: …").
fn check_lines(lines: &[Hatch]) -> R<()> {
    for (i, h) in lines.iter().enumerate() {
        let at = format!("{}: the pattern line {}", MP, i + 1);
        let finite = h.angle.is_finite() && h.origin[0].is_finite() && h.origin[1].is_finite() && h.shift.is_finite();
        if !(finite && h.shift.abs() <= 100000.0) {
            return Err(format!("{}: its angle, origin and shift are numbers, the shift within 100000", at));
        }
        if h.origin[0].abs() > 100000.0 || h.origin[1].abs() > 100000.0 {
            return Err(format!("{}: its origin is within 100000 of the pattern's", at));
        }
        if !(h.spacing >= MIN_SPACING && h.spacing <= 100000.0) {
            return Err(format!("{}: its lines are 0.05 to 100000 apart, not {}", at, disp(h.spacing)));
        }
        if !h.dashes.is_empty() {
            if h.dashes.iter().any(|d| !(d.abs() <= 100000.0)) {
                return Err(format!("{}: a dash or a space is a length within 100000", at));
            }
            let dash = h.dashes.iter().any(|d| *d >= 0.0);
            let space = h.dashes.iter().any(|d| *d < 0.0);
            let total: f64 = h.dashes.iter().map(|d| d.abs()).sum();
            if !(dash && space && total >= MIN_SPACING) {
                return Err(format!(
                    "{}: dashes need a dash (0 is a dot) and a space (a negative length) among them, and 0.05 or more in all",
                    at
                ));
            }
        }
    }
    Ok(())
}

fn gcd(a: i64, b: i64) -> i64 {
    if b == 0 {
        a.abs()
    } else {
        gcd(b, a % b)
    }
}

/// x, y with a x + b y = gcd(a, b).
fn ext_gcd(a: i64, b: i64) -> (i64, i64, i64) {
    if b == 0 {
        (a, 1, 0)
    } else {
        let (g, x, y) = ext_gcd(b, a % b);
        (g, y, x - (a / b) * y)
    }
}

/// The slope a line of direction `deg` (0 to 180) is turned to: (i, j) tiles across and up.
/// The slopes a family may run at in a tile `w` by `h`: (i, j) tiles across and up, none a
/// multiple of another, its lines at least 0.05 apart; with their angles.
fn slopes(w: f64, h: f64) -> Vec<(i64, i64, f64)> {
    let mut out = Vec::new();
    for j in 0..=MAX_STEPS {
        for i in -MAX_STEPS..=MAX_STEPS {
            if (i == 0 && j == 0) || (j == 0 && i < 0) || gcd(i, j) != 1 {
                continue;
            }
            let l = (i as f64 * w).hypot(j as f64 * h);
            if w * h / l < MIN_SPACING {
                continue;
            }
            out.push((i, j, (j as f64 * h).atan2(i as f64 * w).to_degrees()));
        }
    }
    out
}

fn slope(deg: f64, all: &[(i64, i64, f64)]) -> (i64, i64) {
    let cands: Vec<(i64, i64, f64)> = all
        .iter()
        .map(|(i, j, a)| {
            let mut d = (a - deg).abs();
            if d > 90.0 {
                d = 180.0 - d;
            }
            (*i, *j, d)
        })
        .collect();
    let simple = |c: &(i64, i64, f64)| (c.0.abs().max(c.1), c.0.abs() + c.1);
    let within: Vec<&(i64, i64, f64)> = cands.iter().filter(|c| c.2 <= TURN + 1e-12).collect();
    let best = if !within.is_empty() {
        within
            .into_iter()
            .min_by(|a, b| simple(a).cmp(&simple(b)).then(a.2.partial_cmp(&b.2).unwrap_or(std::cmp::Ordering::Equal)))
            .unwrap()
    } else {
        cands
            .iter()
            .min_by(|a, b| a.2.partial_cmp(&b.2).unwrap_or(std::cmp::Ordering::Equal).then(simple(a).cmp(&simple(b))))
            .unwrap()
    };
    (best.0, best.1)
}

/// The part of the chord from `a` to `b` inside the box, if any (Liang-Barsky).
fn clip(a: P, b: P, lo: P, hi: P) -> Option<(P, P)> {
    let d = [b[0] - a[0], b[1] - a[1]];
    let mut t0 = 0.0f64;
    let mut t1 = 1.0f64;
    let checks = [(-d[0], a[0] - lo[0]), (d[0], hi[0] - a[0]), (-d[1], a[1] - lo[1]), (d[1], hi[1] - a[1])];
    for (p, q) in checks {
        if p == 0.0 {
            if q < 0.0 {
                return None;
            }
        } else {
            let r = q / p;
            if p < 0.0 {
                if r > t1 {
                    return None;
                }
                if r > t0 {
                    t0 = r;
                }
            } else {
                if r < t0 {
                    return None;
                }
                if r < t1 {
                    t1 = r;
                }
            }
        }
    }
    if t1 <= t0 {
        return None;
    }
    // a chord runs from its start along its direction: its end is its start and its direction
    let pa = [a[0] + d[0] * t0, a[1] + d[1] * t0];
    let pb = [a[0] + d[0] * t1, a[1] + d[1] * t1];
    Some((pa, pb))
}

struct Family {
    ij: (i64, i64),
    origin: P,
    len: f64,
    hatch: Hatch,
}

fn make(s: &mut Session, p: &Value) -> R<Value> {
    use crate::commands::params::req_point;
    crate::styles::common::check_keys(p, MP, &["ids", "from", "to", "name", "target"])?;
    let pr = &mut s.project;
    let ids = super::groups::ids_param(pr, MP, p)?;
    let from = req_point(p, MP, "from")?;
    let to = req_point(p, MP, "to")?;
    let Some(name) = crate::styles::common::opt_name(p, MP, "name")? else {
        return Err(format!("{}: `name` the new pattern's is required", MP));
    };
    let exists = pr.section("fill_patterns").map(|s| s.contains(&name)).unwrap_or(false);
    if exists {
        return Err(format!("{}: there's already a fill pattern `{}`", MP, name));
    }
    let model = target_param(p)?.unwrap_or(true);
    if ids.is_empty() {
        return Err(format!("{}: pick the detail lines the pattern is made of", MP));
    }
    for id in &ids {
        let c = cat_of(pr, *id);
        if c != "line" {
            return Err(format!("{}: {} {} is not a detail line; a pattern is made of detail lines", MP, c, id));
        }
    }
    let view = s_of(pr.el(ids[0]).unwrap(), "view").map(|v| v.to_string());
    for id in &ids[1..] {
        if s_of(pr.el(*id).unwrap(), "view").map(|v| v.to_string()) != view {
            return Err(format!("{}: the lines are in different views; a pattern's lines are all in one", MP));
        }
    }
    let lo = [from[0].min(to[0]), from[1].min(to[1])];
    let hi = [from[0].max(to[0]), from[1].max(to[1])];
    let w = hi[0] - lo[0];
    let h = hi[1] - lo[1];
    let side_ok = |x: f64| (0.05..=100000.0).contains(&x);
    if !side_ok(w) || !side_ok(h) {
        return Err(format!("{}: the tile is {:.3} by {:.3}; each side is 0.05 to 100000", MP, w, h));
    }
    let scale = view.as_deref().and_then(|g| pr.find_guid(g)).map(|v| view_scale(pr, v)).unwrap_or(100.0);
    let lattice = slopes(w, h);
    let mut fams: Vec<Family> = Vec::new();
    for id in &ids {
        let e = pr.el(*id).unwrap();
        let Some(shape) = curve::Shape::from_fields(e) else { continue };
        let d = shape.drawn();
        for k in 0..d.len().saturating_sub(1) {
            let Some((mut a, mut b)) = clip(d[k], d[k + 1], lo, hi) else { continue };
            let len = (b[0] - a[0]).hypot(b[1] - a[1]);
            if len <= 1e-9 {
                continue;
            }
            let mut deg = (b[1] - a[1]).atan2(b[0] - a[0]).to_degrees();
            if deg < 0.0 || deg >= 180.0 {
                std::mem::swap(&mut a, &mut b);
                deg = (b[1] - a[1]).atan2(b[0] - a[0]).to_degrees();
                if deg >= 180.0 {
                    deg -= 180.0;
                }
            }
            let (i, j) = slope(deg, &lattice);
            let v = [i as f64 * w, j as f64 * h];
            let l = (v[0] * v[0] + v[1] * v[1]).sqrt();
            let k = 1.0 / l;
            let u = [v[0] * k, v[1] * k];
            // the lattice's other vector: i d - j c = 1
            let (g, x, y) = ext_gcd(i, j);
            let (x, y) = if g < 0 { (-x, -y) } else { (x, y) };
            let (c, dd) = (-y, x);
            let other = [c as f64 * w, dd as f64 * h];
            let mut shift = (other[0] * u[0] + other[1] * u[1]) % l;
            if shift < 0.0 {
                shift += l;
            }
            // where it starts in the tile (a line on its far edge starts on the near one)
            let origin = [(a[0] - lo[0]).rem_euclid(w), (a[1] - lo[1]).rem_euclid(h)];
            let angle = v[1].atan2(v[0]).to_degrees();
            let dashes = if len < l - 1e-9 { vec![len, -(l - len)] } else { Vec::new() };
            // a line on the tile's edge and its copy on the opposite one are one family
            let same = fams.iter().any(|f| {
                if f.ij != (i, j) || (f.len - len).abs() > 1e-6 {
                    return false;
                }
                let dx = (origin[0] - f.origin[0]) / w;
                let dy = (origin[1] - f.origin[1]) / h;
                (dx - dx.round()).abs() < 1e-9 && (dy - dy.round()).abs() < 1e-9
            });
            if same {
                continue;
            }
            let hatch = Hatch { angle, origin, shift, spacing: w * h / l, dashes };
            fams.push(Family { ij: (i, j), origin, len, hatch });
        }
    }
    if fams.is_empty() {
        return Err(format!("{}: no line lies inside the tile: pick lines that cross the rectangle between its corners", MP));
    }
    if fams.len() > MAX_FAMILIES {
        return Err(format!("{}: {} lines inside the tile; a pattern holds at most {}", MP, fams.len(), MAX_FAMILIES));
    }
    let mut lines: Vec<Hatch> = fams.into_iter().map(|f| f.hatch).collect();
    if !model {
        // the drawing on paper at the view's scale
        let k = 1.0 / scale;
        for hch in &mut lines {
            hch.origin = [hch.origin[0] * k, hch.origin[1] * k];
            hch.shift *= k;
            hch.spacing *= k;
            for d in &mut hch.dashes {
                *d *= k;
            }
        }
    }
    check_lines(&lines)?;
    let pat = Pattern { model, lines, drawn: Some(scale) };
    pr.section_mut("fill_patterns").insert_sorted(&name, pat.to_value());
    crate::styles::common::lib_ensure(pr, "fill-pattern", &name);
    Ok(jobj! {"name" => name, "pattern" => pat.to_value()})
}
