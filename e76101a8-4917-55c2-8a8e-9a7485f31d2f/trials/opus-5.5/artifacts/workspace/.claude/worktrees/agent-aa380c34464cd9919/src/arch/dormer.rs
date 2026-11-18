//! Dormers: on a slope of a roof, a front wall across the slope and two side walls running back up
//! it until the slope reaches the dormer's eaves, under a gable roof of its own that runs back
//! into the host, which is opened under it; and a window in the front.

use super::hosts::{self, Piece};
use super::util::*;
use crate::commands::params::{self, R};
use crate::geom::{self, P2};
use crate::json::Value;
use crate::session::Session;

fn r3(p: P2) -> P2 {
    [(p[0] * 1000.0).round() / 1000.0, (p[1] * 1000.0).round() / 1000.0]
}

pub fn cmd_dormer(s: &mut Session, p: &Value) -> R<Value> {
    let c = "dormer";
    let pr = &s.project;
    let host_v = match params::get(p, "host") {
        None => return Err("dormer: `host`, the roof it stands on, is required".into()),
        Some(_) => opt_ref(p, c, "host")?.unwrap(),
    };
    let host = by_ref(pr, &host_v)
        .filter(|h| pr.category(*h) == Some("roof"))
        .filter(|h| pr.el(*h).and_then(|e| e.get("join")).map(|j| j.is_null()).unwrap_or(true));
    let Some(host) = host else {
        let word = match &host_v {
            Value::Str(g) => g.clone(),
            v => v.to_compact(),
        };
        return Err(format!("dormer: {} isn't a roof that joins none", word));
    };
    let at = params::req_point(p, c, "at")?;
    let width = params::opt_num(p, c, "width")?.unwrap_or(1600.0);
    let height = params::opt_num(p, c, "height")?.unwrap_or(1200.0);
    let slope = params::opt_num(p, c, "slope")?.unwrap_or(30.0);
    let ty = params::opt_text(p, c, "type")?;
    let ty = ty.or_else(|| default_type(pr, "wall")).ok_or_else(|| "dormer: the model has no types for this".to_string())?;
    let t = thickness(pr, "wall", &ty);
    if !(width - t > 1.0) || !(height > 1.0) || !(slope > 0.0 && slope <= 75.0) {
        return Err(format!(
            "dormer: it needs `width` wider than its walls ({} mm), some `height`, and `slope` from 0 to 75 degrees",
            d(t)
        ));
    }
    let he = pr.el(host).cloned().unwrap_or(Value::Null);
    let tops = hosts::pieces(pr, &he, true);
    let Some(face) = tops.iter().find(|f| f.ring.len() >= 3 && geom::inside_raw(&f.ring, at)).cloned() else {
        return Err(format!("dormer: {} isn't over roof {}", dp(at), host));
    };
    let tan_h = face.tan;
    if !(tan_h > 1e-12) {
        return Err(format!("dormer: roof {} is level at {}: a dormer stands on a slope", host, dp(at)));
    }
    let up = face.up;
    let u = [up[1], -up[0]];
    let roof_ty = type_name(pr, &he).unwrap_or_default();
    let tr = thickness(pr, "roof", &roof_ty);
    let sd = slope.to_radians();
    let half = width / 2.0;
    let at_off = |a: f64, b: f64| -> P2 { r3(geom::add(at, geom::add(geom::scale(u, a), geom::scale(up, b)))) };
    // how far up the slope the host's top climbs to a height above where the dormer stands
    let back = |rise: f64| rise / tan_h;
    let l_side = back(height);
    let l_back = back(height + half * sd.tan() + tr / sd.cos());
    let l_inner = back(height + t / 2.0 * sd.tan());
    let l_apex = back(height + half * sd.tan());
    if !inside_face(&face, geom::add(at, geom::scale(up, l_back))) {
        return Err(format!(
            "dormer: it runs back over roof {}'s ridge; set it lower down the slope, or make it lower or narrower",
            host
        ));
    }
    let window = params::opt_text(p, c, "window")?;
    let pr = &s.project;
    let level = level_of(pr, &he).unwrap_or(0);
    let base_z = face.z_at(at);
    let base_offset = base_z - elev(pr, level);
    let wall_height = (base_z + height + half * sd.tan()) - base_z;
    let host_guid = pr.guid_of(host).unwrap_or_default();
    // the dormer's roof: over the walls' outer faces, its ends upright
    let o = half + t / 2.0;
    let boundary = vec![at_off(-o, -t / 2.0), at_off(o, -t / 2.0), at_off(o, l_back), at_off(-o, l_back)];
    let mut roof = jobj! {
        "guid" => crate::rand::guid(),
        "category" => "roof",
        "type" => he.get("type").cloned().unwrap_or(Value::Null),
        "level" => he.get("level").cloned().unwrap_or(Value::Null),
        "boundary" => ring_v(&boundary),
        "slope" => Value::f(slope),
        "overhang" => Value::f(t / 2.0),
        "gables" => Value::Arr(vec![Value::u(0), Value::u(2)]),
        "offset" => Value::f(base_offset + height),
        "join" => Value::s(&host_guid),
    };
    crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut roof);
    // the host opened under it: inside the walls, up to where the dormer's roof meets the slope
    let i = half - t / 2.0;
    let hole = vec![at_off(-i, t / 2.0), at_off(-i, l_inner), at_off(0.0, l_apex), at_off(i, l_inner), at_off(i, t / 2.0)];
    let roof_id = s.project.alloc_id();
    let roof_guid = text(&roof, "guid").unwrap_or("").to_string();
    s.project.elements.insert(roof_id, roof);
    super::edits::note_made_by(roof_id, "dormer");
    if let Some(h) = s.project.elements.get_mut(&host) {
        let mut ops = rings(h, "openings");
        ops.push(hole);
        put(h, super::roofs::ORDER, "openings", rings_v(&ops));
    }
    // the walls: the front across the slope, then the sides back up it
    let sa = at_off(half, 0.0);
    let ea = at_off(-half, 0.0);
    let run = |q: P2| r3(geom::add(q, geom::scale(up, l_side)));
    let segs = [(sa, ea), (ea, run(ea)), (run(sa), sa)];
    let top_ref = Value::s(&roof_guid);
    let base_ref = Value::s(&host_guid);
    let mut walls = Vec::new();
    for (a, b) in segs {
        let e = super::walls::make_wall(
            s,
            &ty,
            level,
            a,
            b,
            None,
            Some(wall_height),
            Some(base_offset),
            None,
            None,
            None,
            &Some(top_ref.clone()),
            &Some(base_ref.clone()),
            None,
        );
        let id = s.project.alloc_id();
        s.project.elements.insert(id, e);
        walls.push(id);
    }
    let win = match window {
        None => Value::Null,
        Some(wt) => {
            let pr = &s.project;
            let mark = super::openings::next_mark(pr, "window");
            let mut e = jobj! {
                "guid" => crate::rand::guid(),
                "category" => "window",
                "type" => type_ref(pr, "window", &wt),
                "host" => Value::s(&pr.guid_of(walls[0]).unwrap_or_default()),
                "offset" => Value::f(half),
                "sill" => Value::f(100.0),
                "mark" => Value::s(&mark),
                "flip_facing" => Value::Bool(false),
                "flip_hand" => Value::Bool(false),
            };
            crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
            let id = s.project.alloc_id();
            s.project.elements.insert(id, e);
            Value::u(id)
        }
    };
    let _ = hosts::z_at;
    Ok(jobj! {"roof" => roof_id, "walls" => walls, "window" => win})
}

fn inside_face(f: &Piece, q: P2) -> bool {
    geom::inside_raw(&f.ring, q)
}
