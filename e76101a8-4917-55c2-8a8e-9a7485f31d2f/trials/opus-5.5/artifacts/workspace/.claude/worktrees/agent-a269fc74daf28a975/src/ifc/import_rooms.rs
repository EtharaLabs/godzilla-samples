//! Rooms, from the file's spaces: a point inside each, its name and its colour.

use super::import::Ctx;
use super::import_build::r3;
use super::import_geom::{self as geom, Solid, V2};
use crate::json::Value;

/// The outline of a body in plan: an extrusion's profile (where it is extruded up), else the
/// biggest face that looks down.
pub fn footprint(solids: &[Solid]) -> Option<Vec<V2>> {
    for s in solids {
        if let Some(x) = &s.ext {
            let d = x.tf.dir(x.dir);
            if d[2].abs() > 0.999 {
                let v: Vec<V2> = x
                    .outer
                    .iter()
                    .map(|p| {
                        let q = x.tf.apply([p[0], p[1], 0.0]);
                        [q[0], q[1]]
                    })
                    .collect();
                return Some(v);
            }
        }
    }
    let mut best: Option<(f64, Vec<V2>)> = None;
    for s in solids {
        for f in &s.faces {
            let n = super::import_walls::face_normal(&f.outer);
            if n[2] < -0.999 {
                let v: Vec<V2> = f.outer.iter().map(|p| [p[0], p[1]]).collect();
                let a = geom::area2(&v).abs();
                if best.as_ref().map(|(b, _)| a > *b).unwrap_or(true) {
                    best = Some((a, v));
                }
            }
        }
    }
    best.map(|(_, v)| v)
}

fn cross(o: V2, a: V2, b: V2) -> f64 {
    (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
}

/// A point inside a polygon: the centre of the biggest triangle ear clipping cuts it into (the
/// polygon counter-clockwise from its lowest point, each ear the first from there; the last
/// of equal ones).
pub fn inside_point(poly: &[V2]) -> Option<V2> {
    let mut v: Vec<V2> = super::import_slabs::simplify(poly);
    if v.len() < 3 {
        return None;
    }
    if geom::area2(&v) < 0.0 {
        v.reverse();
    }
    let mut k = 0;
    for i in 1..v.len() {
        if v[i][1] < v[k][1] || (v[i][1] == v[k][1] && v[i][0] < v[k][0]) {
            k = i;
        }
    }
    v.rotate_left(k);
    let mut tris: Vec<[V2; 3]> = Vec::new();
    let mut guard = 0;
    while v.len() > 3 && guard < 100000 {
        guard += 1;
        let n = v.len();
        let mut clipped = false;
        for j in 0..n {
            let (a, b, c) = (v[(j + n - 1) % n], v[j], v[(j + 1) % n]);
            if cross(a, b, c) <= 0.0 {
                continue;
            }
            let mut ok = true;
            for q in &v {
                if *q == a || *q == b || *q == c {
                    continue;
                }
                if cross(a, b, *q) >= 0.0 && cross(b, c, *q) >= 0.0 && cross(c, a, *q) >= 0.0 {
                    ok = false;
                    break;
                }
            }
            if ok {
                tris.push([a, b, c]);
                v.remove(j);
                clipped = true;
                break;
            }
        }
        if !clipped {
            break;
        }
    }
    if v.len() == 3 {
        tris.push([v[0], v[1], v[2]]);
    }
    let mut best: Option<([V2; 3], f64)> = None;
    for t in tris {
        let a = ((t[1][0] - t[0][0]) * (t[2][1] - t[0][1]) - (t[1][1] - t[0][1]) * (t[2][0] - t[0][0])).abs() / 2.0;
        if best.map(|(_, b)| a >= b).unwrap_or(true) {
            best = Some((t, a));
        }
    }
    let (t, _) = best?;
    Some([(t[0][0] + t[1][0] + t[2][0]) / 3.0, (t[0][1] + t[1][1] + t[2][1]) / 3.0])
}

pub fn rooms(ctx: &mut Ctx) {
    let ids: Vec<u64> = ctx.m.of("IFCSPACE").to_vec();
    let mut given: Vec<String> = Vec::new();
    let mut pending: Vec<u64> = Vec::new();
    for id in ids {
        let (pid, number) = room(ctx, id);
        match number {
            Some(n) => given.push(n),
            None => pending.push(pid),
        }
    }
    // a room the file gives no number numbered on in the series
    for pid in pending {
        let n = super::import_walls::next_mark(&given);
        if let Some(e) = ctx.pr.elements.get_mut(&pid) {
            e.set("number", Value::s(&n));
        }
        given.push(n);
    }
}

/// A room from a space: its name the space's long name (else its name), its number the space's
/// name when it has a long name.
fn room(ctx: &mut Ctx, id: u64) -> (u64, Option<String>) {
    let e = ctx.m.get(id).unwrap().clone();
    let solids = geom::body(&ctx.m, id);
    let found = footprint(&solids).and_then(|f| inside_point(&f));
    let point = found.unwrap_or([0.0, 0.0]);
    let z = solids.iter().flat_map(|s| s.points().map(|p| p[2]).collect::<Vec<_>>()).fold(f64::INFINITY, f64::min);
    let level = ctx.level_of(id, if z.is_finite() { z } else { 0.0 });
    let long = e.p(7).str().map(|s| s.trim().to_string()).filter(|s| !s.is_empty());
    let short = e.p(2).str().map(|s| s.trim().to_string()).filter(|s| !s.is_empty());
    let number = if long.is_some() { short.clone() } else { None };
    let name = long.or(short).unwrap_or_else(|| "Room".to_string());
    let colour = solids.iter().find_map(|s| ctx.m.styled.get(&s.item).and_then(|si| super::import_types::styled_item_colour(ctx, *si))).and_then(|c| c.0);
    let g = ctx.guid_for(id);
    let mut v = crate::jobj! {
        "guid" => g.as_str(),
        "category" => "room",
        "level" => ctx.level_guid(level),
        "point" => Value::Arr(vec![Value::f(r3(point[0])), Value::f(r3(point[1]))]),
        "name" => name,
        "number" => number.clone().unwrap_or_default(),
    };
    if let Some(c) = colour {
        v.set("colour", Value::Arr(c.iter().map(|x| Value::u(*x)).collect()));
    }
    let pid = ctx.add(id, v);
    if found.is_none() {
        ctx.fixed.insert((pid, "point"));
    }
    (pid, number)
}
