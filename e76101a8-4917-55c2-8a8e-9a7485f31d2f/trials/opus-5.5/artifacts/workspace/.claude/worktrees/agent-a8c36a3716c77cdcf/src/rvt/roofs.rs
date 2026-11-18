//! Roofs: a footprint roof by its sketch (level, at its box's bottom), a roof by face as its
//! box's footprint, an extrusion roof by its profile (the sketch, its underside a type's
//! thickness below, square to each slope) and the sweep its box gives. Walls that name a
//! footprint roof follow its underside.

use super::build::{self, mm, r3};
use super::cats;
use super::curves::{self, Curve};
use super::floors::{self, pts_value};
use super::import::Ctx;
use super::notes::Kind;
use super::openings::WallFate;
use super::records::Record;
use super::sketch::{self, SLine};
use super::types::Layers;
use crate::json::Value;
use std::collections::BTreeMap;

pub const NOTE_BY_FACE: &str =
    "it is a roof by face (over a mass, say), whose face is not read: it comes in as the footprint of its own box";
pub const NOTE_ATTACHED: &str = "its top follows the roof it names: it comes in cut by the roof's underside";
pub const NOTE_NO_HEIGHT: &str = "the roof it names leaves it no height: it comes in as its own box";

/// The most lines a profile may have.
const MAX_LINES: usize = 256;
/// How close (feet) two ends are to meet, and a point to lie in the profile's plane.
const MEET: f64 = 1e-6;

/// What a wall that names a roof can follow: the footprint roofs that came in level, by id
/// (their GUID and underside, mm).
pub type Undersides = BTreeMap<u64, (String, f64)>;

pub fn read(ctx: &mut Ctx, sketches: &BTreeMap<u64, Vec<SLine>>) -> Undersides {
    let kind = Kind::simple("roof");
    let mut under: Undersides = BTreeMap::new();
    let profile_tag = ctx.doc.schema.tag("ProfileRoof");
    let roof_tag = ctx.doc.schema.tag("Roof");
    for r in ctx.instances(cats::OST_ROOFS) {
        let b = match r.bbox {
            Some(b) => b,
            None => continue,
        };
        // a box with no volume has nothing to import
        if !(b[3] > b[0] && b[4] > b[1] && b[5] > b[2]) {
            continue;
        }
        let res = if Some(r.class_tag) == profile_tag {
            footprint(ctx, r, &b, sketches, &mut under)
        } else if Some(r.class_tag) == roof_tag {
            extrusion(ctx, r, &b, sketches)
        } else {
            by_face(ctx, r, &b)
        };
        match res {
            Ok(notes) => {
                for n in notes {
                    ctx.notes.note(&kind, &n, r.id);
                }
            }
            Err(reason) => ctx.notes.leave(&kind, &reason, r.id),
        }
    }
    under
}

/// The type a roof's layers make (or a stand-in as thick as its box), its name and thickness.
fn roof_type(ctx: &Ctx, tid: Option<u64>, box_h: f64, notes: &mut Vec<String>) -> (Value, String, f64) {
    if let Some(t) = tid {
        if let Layers::Read(ls) = ctx.type_layers(t) {
            let (v, th) = floors::layered_type(ctx, &ls, cats::OST_ROOFS, None);
            let name = ctx.type_name(t).unwrap_or_else(|| format!("Imported - {}mm", th));
            return (v, name, th);
        }
        notes.push(floors::NOTE_THIN.into());
    }
    (floors::standin_type(box_h, None), format!("Imported - {}mm", box_h), box_h)
}

fn add_roof(ctx: &mut Ctx, rid: u64, tv: Value, tname: &str, level: usize, shape: Vec<(&str, Value)>, offset: f64) -> String {
    let name = build::add_type(&mut ctx.pr, "roof", tname, tv);
    let tg = ctx.lib_guid(&build::type_kind("roof"), &name);
    let g = crate::rand::guid();
    let mut v = jobj! {
        "guid" => g.as_str(),
        "category" => "roof",
        "type" => tg.as_str(),
        "level" => ctx.level_guid(level),
    };
    let mut extrusion = None;
    for (k, x) in shape {
        if k == "extrusion" {
            extrusion = Some(x);
        } else {
            v.set(k, x);
        }
    }
    v.set("slope", Value::f(0.0));
    v.set("overhang", Value::f(0.0));
    v.set("offset", Value::f(offset));
    if let Some(x) = extrusion {
        v.set("extrusion", x);
    }
    ctx.add(rid, "roof", v);
    g
}

fn footprint(ctx: &mut Ctx, r: &Record, b: &[f64; 6], sketches: &BTreeMap<u64, Vec<SLine>>, under: &mut Undersides) -> Result<Vec<String>, String> {
    let lines = match sketches.get(&r.id) {
        Some(l) if !l.is_empty() => l.clone(),
        _ => return Err("it has no sketch lines".into()),
    };
    let tid = ctx.one_type(r, cats::OST_ROOFS).ok_or("its record does not name one roof type")?;
    let (bottom, top) = (mm(b[2]), mm(b[5]));
    let level = ctx.base_level(&r.refs, b[2]).ok_or(super::walls::NO_LEVEL)?;
    let mut notes: Vec<String> = Vec::new();
    let loops = floors::boundaries(&lines, b, "roof", &mut notes);
    let box_h = r3(top - bottom);
    let (tv, tname, thick) = roof_type(ctx, Some(tid), box_h, &mut notes);
    let sloped = (box_h - thick).abs() > 1.0;
    if sloped {
        notes.push(format!(
            "its box is {} mm tall and its type {} mm thick: it is sloped or stepped, and its slopes are not read: it comes in level",
            box_h, thick
        ));
    }
    let offset = r3(bottom - ctx.levels[level].elevation);
    let mut first: Option<String> = None;
    for (outer, voids) in loops {
        let mut shape = vec![("boundary", pts_value(&outer))];
        if !voids.is_empty() {
            shape.push(("courtyards", Value::Arr(voids.iter().map(|p| pts_value(p)).collect())));
        }
        let g = add_roof(ctx, r.id, tv.clone(), &tname, level, shape, offset);
        first.get_or_insert(g);
    }
    if !sloped {
        if let Some(g) = first {
            under.insert(r.id, (g, ctx.levels[level].elevation + offset));
        }
    }
    Ok(notes)
}

fn by_face(ctx: &mut Ctx, r: &Record, b: &[f64; 6]) -> Result<Vec<String>, String> {
    let (bottom, top) = (mm(b[2]), mm(b[5]));
    let level = ctx.base_level(&r.refs, b[2]).ok_or(super::walls::NO_LEVEL)?;
    let mut notes = vec![NOTE_BY_FACE.to_string()];
    let tid = ctx.one_type(r, cats::OST_ROOFS);
    let (tv, tname, _) = roof_type(ctx, tid, r3(top - bottom), &mut notes);
    let offset = r3(bottom - ctx.levels[level].elevation);
    add_roof(ctx, r.id, tv, &tname, level, vec![("boundary", pts_value(&sketch::footprint(b)))], offset);
    Ok(notes)
}

type P3 = [f64; 3];

fn d3(a: P3, b: P3) -> f64 {
    ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt()
}

/// The lines (feet) joined end to end into one open chain: its points in order.
fn chain(lines: &[(P3, P3)]) -> Option<Vec<P3>> {
    let n = lines.len();
    let end = |e: usize| if e % 2 == 0 { lines[e / 2].0 } else { lines[e / 2].1 };
    // each end meets at most one other line's end
    let mut mate: Vec<Option<usize>> = vec![None; 2 * n];
    for e in 0..2 * n {
        for f in 0..2 * n {
            if f / 2 == e / 2 || d3(end(e), end(f)) > MEET {
                continue;
            }
            if mate[e].is_some() {
                return None;
            }
            mate[e] = Some(f);
        }
    }
    let free: Vec<usize> = (0..2 * n).filter(|e| mate[*e].is_none()).collect();
    if free.len() != 2 {
        return None;
    }
    let mut pts = vec![end(free[0])];
    let mut used = vec![false; n];
    let mut e = free[0];
    loop {
        let li = e / 2;
        if used[li] {
            return None;
        }
        used[li] = true;
        let other = e ^ 1;
        pts.push(end(other));
        match mate[other] {
            Some(f) => e = f,
            None => break,
        }
    }
    if used.iter().any(|u| !u) {
        return None;
    }
    Some(pts)
}

/// The underside of a profile (u, z in mm, u rising): each stretch let down square to itself by
/// the thickness, the stretches next to each other met, the ends cut upright.
fn underside(top: &[(f64, f64)], t: f64) -> Vec<(f64, f64)> {
    let segs: Vec<(f64, f64, f64)> = top
        .windows(2)
        .map(|w| {
            let s = (w[1].1 - w[0].1) / (w[1].0 - w[0].0);
            (w[0].0, w[0].1 - t * (1.0 + s * s).sqrt(), s)
        })
        .collect();
    let mut pts = vec![(top[0].0, segs[0].1)];
    for w in segs.windows(2) {
        let ((ua, za, sa), (ub, zb, sb)) = (w[0], w[1]);
        let u = if (sa - sb).abs() < 1e-12 { ub } else { (zb - za + sa * ua - sb * ub) / (sa - sb) };
        pts.push((u, za + sa * (u - ua)));
    }
    let (ul, zl, sl) = segs[segs.len() - 1];
    let ue = top[top.len() - 1].0;
    pts.push((ue, zl + sl * (ue - ul)));
    pts
}

fn extrusion(ctx: &mut Ctx, r: &Record, b: &[f64; 6], sketches: &BTreeMap<u64, Vec<SLine>>) -> Result<Vec<String>, String> {
    let ids: Vec<u64> = match sketches.get(&r.id) {
        Some(l) if !l.is_empty() => l.iter().map(|l| l.id).collect(),
        _ => return Err("it has no sketch lines".into()),
    };
    let tid = ctx.one_type(r, cats::OST_ROOFS).ok_or("its record does not name one roof type")?;
    let ls = match ctx.type_layers(tid) {
        Layers::Read(ls) => ls,
        _ => return Err("its type has no layers the reader can read".into()),
    };
    if ids.len() > MAX_LINES {
        return Err(format!("its profile has {} lines", ids.len()));
    }
    let mut lines: Vec<(P3, P3)> = Vec::new();
    for id in &ids {
        match ctx.first_data(*id, curves::first) {
            Some((Curve::Line(l), _)) => lines.push((l.start, l.end)),
            _ => return Err("its profile has a line that is not a straight one the reader can read (an arc, or no curve in its data)".into()),
        }
    }
    let mut pts = chain(&lines).ok_or("its profile's lines do not make one open chain")?;
    let (p0, p1) = (pts[0], pts[pts.len() - 1]);
    let (dx, dy) = (p1[0] - p0[0], p1[1] - p0[1]);
    let len = (dx * dx + dy * dy).sqrt();
    if len <= MEET {
        return Err("its profile does not run along a plan line".into());
    }
    // the axis it runs along: 0 for x, 1 for y
    let axis = if dx.abs() <= 1e-9 * len {
        1
    } else if dy.abs() <= 1e-9 * len {
        0
    } else {
        return Err("its profile's plane is not square to an axis, so its box does not say how far it is swept".into());
    };
    if pts[pts.len() - 1][axis] < pts[0][axis] {
        pts.reverse();
    }
    let across = 1 - axis;
    let not_upright = "its profile is not one upright plane running one way along its line";
    let c0 = pts[0][across];
    if pts.iter().any(|p| (p[across] - c0).abs() > MEET) {
        return Err(not_upright.into());
    }
    let top: Vec<(f64, f64)> = pts.iter().map(|p| (p[axis] * 304.8, p[2] * 304.8)).collect();
    if top.windows(2).any(|w| !(w[1].0 - w[0].0 > 1.0)) {
        return Err(not_upright.into());
    }
    let t: f64 = ls.iter().map(|l| l.width).sum::<f64>() * 304.8;
    let low = underside(&top, t);
    if low.windows(2).any(|w| !(w[1].0 - w[0].0 > 1.0)) {
        return Err("its type is thicker than its profile's stretches allow".into());
    }
    let zmin = low.iter().map(|p| p.1).fold(f64::INFINITY, f64::min);
    let zmax = top.iter().map(|p| p.1).fold(f64::NEG_INFINITY, f64::max);
    let bm: Vec<f64> = b.iter().map(|x| x * 304.8).collect();
    let (u0, u1) = (top[0].0, top[top.len() - 1].0);
    let sweep = bm[across + 3] - bm[across];
    let fits = (bm[axis] - u0).abs() <= 1.0
        && (bm[axis + 3] - u1).abs() <= 1.0
        && (bm[2] - zmin).abs() <= 1.0
        && (bm[5] - zmax).abs() <= 1.0
        && sweep > 1.0;
    if !fits {
        return Err("its box is not the one its profile and its type's thickness square to each slope make".into());
    }
    let level = ctx.base_level(&r.refs, zmin / 304.8).ok_or(super::walls::NO_LEVEL)?;
    let (v, th) = floors::layered_type(ctx, &ls, cats::OST_ROOFS, None);
    let tname = ctx.type_name(tid).unwrap_or_else(|| format!("Imported - {}mm", th));
    // across the line, to its left: +y for a line along +x, -x for one along +y
    let c0mm = c0 * 304.8;
    let (from, to) = if axis == 0 { (bm[1] - c0mm, bm[4] - c0mm) } else { (c0mm - bm[3], c0mm - bm[0]) };
    let line = Value::Arr(vec![
        Value::Arr(vec![Value::f(mm(pts[0][0])), Value::f(mm(pts[0][1]))]),
        Value::Arr(vec![Value::f(mm(p1_of(&pts)[0])), Value::f(mm(p1_of(&pts)[1]))]),
    ]);
    let profile = Value::Arr(low.iter().map(|p| Value::Arr(vec![Value::f(r3(p.0 - u0)), Value::f(r3(p.1 - zmin))])).collect());
    let ext = jobj! {"line" => line, "profile" => profile, "from" => r3(from), "to" => r3(to)};
    let offset = r3(zmin - ctx.levels[level].elevation);
    add_roof(ctx, r.id, v, &tname, level, vec![("extrusion", ext)], offset);
    Ok(Vec::new())
}

fn p1_of(pts: &[P3]) -> P3 {
    pts[pts.len() - 1]
}

/// Walls that name a footprint roof that came in level: their tops follow its underside, when
/// it leaves them more than a millimetre over their bases.
pub fn attach(ctx: &mut Ctx, fates: &BTreeMap<u64, WallFate>, under: &Undersides) {
    let kind = Kind::simple("wall");
    for (rid, fate) in fates {
        let base = match fate {
            WallFate::In { base, .. } => *base,
            _ => continue,
        };
        let r = match ctx.record(*rid) {
            Some(r) => r,
            None => continue,
        };
        let roof = r.refs.iter().find_map(|id| under.get(id));
        let (g, u) = match roof {
            Some(x) => x.clone(),
            None => continue,
        };
        if u - base > 1.0 {
            if let Some((pid, _)) = ctx.made.get(&(*rid, "wall")).cloned() {
                if let Some(e) = ctx.pr.elements.get_mut(&pid) {
                    e.set("attach_top", Value::s(&g));
                }
            }
            ctx.notes.note(&kind, NOTE_ATTACHED, *rid);
        } else {
            ctx.notes.note(&kind, NOTE_NO_HEIGHT, *rid);
        }
    }
}
