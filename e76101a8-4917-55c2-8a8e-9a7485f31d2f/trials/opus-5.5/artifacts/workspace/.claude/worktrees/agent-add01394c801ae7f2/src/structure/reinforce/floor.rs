//! A floor's bars: `bottom` and `top` meshes, each of a layer along east (`x`) and one along
//! north (`y`) on it, at most a spacing apart, stopping a cover short of the floor's outline and
//! of its openings (a scan line through the outline and the openings together: each piece of
//! it inside the floor is a bar), turned up from the bottom mesh and down from the top one by
//! `hook`. A sloped floor's layers are measured from its top, square to it, and follow it.
//!
//! The floor is read here from the element as the file holds it (`boundary`, `openings`,
//! `offset`, `slope` and `arrow`, its type's `thickness`): floors are ARCH's.

use super::de::{f, sub};
use super::geom::{gaps, station_count, stations, V3, TOL};
use super::shapes::GRID;
use super::{check_keys, diameter, norm, not_negative, read_struct, spacing, Armed, Bar, Ctx};
use crate::json::{Map, Value};
use crate::project::Project;
use crate::structure::common::R;
use crate::structure::rebar::MAX_BARS;

/// A floor as reinforcing it needs it.
pub struct Slab {
    pub outline: Vec<[f64; 2]>,
    pub openings: Vec<Vec<[f64; 2]>>,
    pub offset: f64,
    pub thickness: f64,
    /// degrees, and the arrow's tail and head
    pub slope: Option<(f64, [f64; 2], [f64; 2])>,
}

fn pts(v: Option<&Value>) -> Vec<[f64; 2]> {
    let mut out = Vec::new();
    if let Some(a) = v.and_then(|x| x.as_arr()) {
        for p in a {
            if let Some(q) = p.as_arr() {
                if let (Some(x), Some(y)) = (q.first().and_then(|x| x.as_f64()), q.get(1).and_then(|y| y.as_f64())) {
                    out.push([x, y]);
                }
            }
        }
    }
    out
}

/// The floor type's thickness (a type named by GUID or by name).
fn floor_thickness(pr: &Project, e: &Value) -> f64 {
    let t = e.get("type").and_then(|t| t.as_str()).unwrap_or("");
    let types = pr.section("types").and_then(|m| m.get("floor")).and_then(|f| f.as_obj());
    let types = match types {
        Some(t) => t,
        None => return 0.0,
    };
    let name = crate::structure::members::read::type_name_param(pr, t);
    let ty = types.get(&name).or_else(|| types.get(t));
    ty.and_then(|x| x.get("thickness")).and_then(|x| x.as_f64()).unwrap_or(0.0)
}

pub fn read_slab(pr: &Project, e: &Value) -> Slab {
    let outline = pts(e.get("boundary"));
    let openings = e
        .get("openings")
        .and_then(|o| o.as_arr())
        .map(|a| a.iter().map(|r| pts(Some(r))).filter(|r| r.len() >= 3).collect())
        .unwrap_or_default();
    let offset = e.get("offset").and_then(|x| x.as_f64()).unwrap_or(0.0);
    let slope = match (e.get("slope").and_then(|x| x.as_f64()), e.get("arrow")) {
        (Some(s), Some(a)) if s != 0.0 => {
            let ar = pts(Some(a));
            if ar.len() == 2 {
                Some((s, ar[0], ar[1]))
            } else {
                None
            }
        }
        _ => None,
    };
    Slab { outline, openings, offset, thickness: floor_thickness(pr, e), slope }
}

/// Where a line at `c` across (y for bars along x, x for bars along y) crosses the rings: the
/// pieces of it inside the floor, in order.
pub fn chords(rings: &[&[[f64; 2]]], c: f64, along_x: bool) -> Vec<(f64, f64)> {
    let mut xs: Vec<f64> = Vec::new();
    for ring in rings {
        let n = ring.len();
        for i in 0..n {
            let a = ring[i];
            let b = ring[(i + 1) % n];
            // (the coordinate the line runs along, the one it is at)
            let (au, av, bu, bv) = if along_x { (a[0], a[1], b[0], b[1]) } else { (a[1], a[0], b[1], b[0]) };
            if av == bv {
                continue;
            }
            let (lo, hi) = if av < bv { (av, bv) } else { (bv, av) };
            if c < lo || c >= hi {
                continue;
            }
            xs.push(au + (c - av) * (bu - au) / (bv - av));
        }
    }
    xs.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    xs.chunks(2).filter(|p| p.len() == 2).map(|p| (p[0], p[1])).collect()
}

/// A layer of a mesh.
struct Layer {
    name: &'static str,
    along_x: bool,
    d: f64,
    spacing: f64,
    /// How far below the top its bars' centre lines are, square to it.
    off: f64,
    /// Up (+1, a bottom mesh's hooks) or down (-1, a top one's).
    hook_dir: f64,
    hook: f64,
}

pub fn arm(ctx: &Ctx) -> R<Armed> {
    let pr = ctx.pr;
    let slab = read_slab(pr, ctx.e);
    let params = ctx.params;
    let bottom = read_struct(params, "bottom", &GRID)?;
    let top = read_struct(params, "top", &GRID)?;
    check_keys(params, "floor")?;
    let has = |m: &Option<Map>| m.as_ref().map(|m| m.contains("x") || m.contains("y")).unwrap_or(false);
    if !has(&bottom) && !has(&top) {
        return Err("nothing to reinforce with: give a `bottom` or a `top` mesh with `x` or `y` bars".into());
    }
    let cv = ctx.cover;
    // the meshes' hooks and diameters
    let mut meshes: Vec<(&'static str, &Map, f64)> = Vec::new();
    for (name, m) in [("bottom", &bottom), ("top", &top)] {
        let m = match m {
            Some(m) if m.contains("x") || m.contains("y") => m,
            _ => continue,
        };
        let hook = match f(m, "hook") {
            Some(h) => not_negative("hook", h)?,
            None => 0.0,
        };
        for k in ["x", "y"] {
            if let Some(l) = sub(m, k) {
                diameter(name, f(l, "diameter").unwrap_or(0.0))?;
            }
        }
        meshes.push((name, m, hook));
    }
    let th = slab.thickness;
    let room = th - cv.top - cv.bottom;
    let mesh_thick = |m: &Map| -> f64 {
        ["x", "y"].iter().filter_map(|k| sub(m, k)).map(|l| f(l, "diameter").unwrap_or(0.0)).sum()
    };
    let all_d: Vec<f64> = meshes
        .iter()
        .flat_map(|(_, m, _)| ["x", "y"].iter().filter_map(|k| sub(m, k)).map(|l| f(l, "diameter").unwrap_or(0.0)).collect::<Vec<_>>())
        .collect();
    if meshes.len() == 2 {
        let gap = room - mesh_thick(meshes[0].1) - mesh_thick(meshes[1].1);
        let c = ctx.common.clearance_for(&all_d);
        if gap < c - TOL {
            return Err(format!(
                "the meshes at the top and the bottom meet: {:.1} mm between them, less than the {} mm clearance",
                gap, c
            ));
        }
    } else if mesh_thick(meshes[0].1) > room {
        return Err(format!("the mesh doesn't fit the floor's {} mm thickness between the covers", th));
    }
    // the layers, each its depth below the top
    let mut layers: Vec<Layer> = Vec::new();
    for (name, m, hook) in &meshes {
        let bottom_mesh = *name == "bottom";
        // what lies between the face and the layer: the cover and the layers before it
        let mut below = if bottom_mesh { cv.bottom } else { cv.top };
        for (k, along_x) in [("x", true), ("y", false)] {
            let l = match sub(m, k) {
                Some(l) => l,
                None => continue,
            };
            let d = f(l, "diameter").unwrap_or(0.0);
            let lname: &'static str = match (bottom_mesh, along_x) {
                (true, true) => "bottom x",
                (true, false) => "bottom y",
                (false, true) => "top x",
                (false, false) => "top y",
            };
            let sp = f(l, "spacing").unwrap_or(0.0);
            let off = if bottom_mesh { th - below - d / 2.0 } else { below + d / 2.0 };
            below += d;
            layers.push(Layer {
                name: lname,
                along_x,
                d,
                spacing: sp,
                off,
                hook_dir: if bottom_mesh { 1.0 } else { -1.0 },
                hook: *hook,
            });
        }
    }
    // the outline's extent
    let (mut x0, mut y0, mut x1, mut y1) = (f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY);
    for p in &slab.outline {
        x0 = x0.min(p[0]);
        y0 = y0.min(p[1]);
        x1 = x1.max(p[0]);
        y1 = y1.max(p[1]);
    }
    let mut rings: Vec<&[[f64; 2]]> = vec![&slab.outline];
    for o in &slab.openings {
        rings.push(o);
    }
    // the top: its height at a point (over the level) and the way square to it
    let elev = ctx.host.elevation;
    let z0 = elev + slab.offset;
    // the top's plane: z = a x + b y + c, rising `slope` degrees along the arrow from its tail
    let (pa, pb, pc, sec, normal) = match slab.slope {
        Some((s, tail, head)) => {
            let r = s.to_radians();
            let dx = head[0] - tail[0];
            let dy = head[1] - tail[1];
            // (the arrow's length as `hypot` gives it)
            let k = 1.0 / dx.hypot(dy);
            let u = [dx * k, dy * k];
            let tan = r.tan();
            let a = u[0] * tan;
            let b = u[1] * tan;
            // square to the top: (-a, -b, 1) over its length; a layer `off` below the top
            // square to it is `off` times that length below it plumb
            let l = (a * a + b * b + 1.0).sqrt();
            (a, b, z0 - (a * tail[0] + b * tail[1]), (1.0 + tan * tan).sqrt(), [-a / l, -b / l, 1.0 / l])
        }
        None => (0.0, 0.0, z0, 1.0, [0.0, 0.0, 1.0]),
    };
    let sloped = slab.slope.is_some();
    // a layer's height over the level at a point
    let height = |x: f64, y: f64, off: f64| -> f64 {
        if sloped {
            ((pa * x + pb * y + pc) - elev) - off * sec
        } else {
            (z0 - elev) - off
        }
    };
    let gb = ctx.common.grade.clone();
    let mut out: Vec<Bar> = Vec::new();
    // what the check reads: each layer's diameter and how far apart its bars are
    let mut checked: Vec<(&'static str, f64, Option<f64>)> = Vec::new();
    for l in &layers {
        spacing(l.name, l.spacing, l.d)?;
        let (lo, hi) = if l.along_x { (y0, y1) } else { (x0, x1) };
        let a = lo + cv.sides + l.d / 2.0;
        let b = hi - cv.sides - l.d / 2.0;
        if b < a {
            return Err(format!("the {} bars don't fit inside that cover", l.name));
        }
        let span = b - a;
        let mut layer_step = None;
        if span > 0.0 {
            let n = gaps(span, l.spacing);
            let step = span / n as f64;
            layer_step = Some(step);
            let gap = step - l.d;
            let c = ctx.common.clearance_for(&[l.d]);
            if gap < c - TOL {
                return Err(format!(
                    "{} bars of {} mm each {:.1} mm leave {:.1} mm between them, less than the {} mm clearance: widen the spacing",
                    l.name, l.d, step, gap, c
                ));
            }
        }
        // a leg from one face to the cover on the other
        let reach = th - cv.top - cv.bottom - l.d
            - if l.hook_dir > 0.0 { (th - cv.bottom - l.d / 2.0) - l.off } else { l.off - l.d / 2.0 - cv.top };
        if l.hook > TOL && l.hook > reach + TOL {
            return Err(format!(
                "a hook of {} mm doesn't fit the {} bars, which have {:.1} mm to the cover on the other face",
                l.hook, l.name, reach
            ));
        }
        if station_count(a, b, l.spacing) > (MAX_BARS + 1) as f64 {
            return Err(format!(
                "that is more than the {} bars a command makes: widen a spacing or use fewer bars",
                MAX_BARS
            ));
        }
        checked.push((l.name, l.d, layer_step));
        let lines = if span > 0.0 { stations(a, b, l.spacing) } else { vec![a] };
        for c in lines {
            for (u0, u1) in chords(&rings, c, l.along_x) {
                let s0 = u0 + cv.sides;
                let s1 = u1 - cv.sides;
                if s1 - s0 <= TOL {
                    continue;
                }
                let point = |u: f64| -> V3 {
                    let (x, y) = if l.along_x { (u, c) } else { (c, u) };
                    [x, y, height(x, y, l.off)]
                };
                let p0 = point(s0);
                let p1 = point(s1);
                let leg = |p: V3| -> V3 {
                    let h = l.hook * l.hook_dir;
                    [p[0] + normal[0] * h, p[1] + normal[1] * h, p[2] + normal[2] * h]
                };
                let mut path = Vec::with_capacity(4);
                if l.hook > TOL {
                    path.push(leg(p0));
                }
                path.push(p0);
                path.push(p1);
                if l.hook > TOL {
                    path.push(leg(p1));
                }
                out.push(Bar { path, diameter: l.d, grade: gb.clone(), layer: l.name.into() });
                if out.len() > MAX_BARS {
                    return Err(format!(
                        "that is more than the {} bars a command makes: widen a spacing or use fewer bars",
                        MAX_BARS
                    ));
                }
            }
        }
    }
    let nf = norm::Floor { thickness: th, layers: checked };
    Ok(Armed { bars: out, info: norm::Info { cover: Some(cv), kind: norm::Kind::Floor(nf) } })
}
