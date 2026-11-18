//! Trim/Extend to Corner: two walls, or two detail lines, to where they meet.

use super::common::*;
use super::ops_geom::*;
use crate::commands::params::point_of;
use crate::json::Value;
use crate::session::Session;
use std::cell::Cell;

thread_local! {
    static ON_LINES: Cell<bool> = const { Cell::new(false) };
}

/// Whether the last corner makes an undo step even where it changed nothing: on two detail lines
/// it does (on walls it doesn't). For the session's always-step hook.
pub fn step_anyway() -> bool {
    ON_LINES.with(|c| c.get())
}

pub fn run(s: &mut Session, p: &Value) -> R<Value> {
    ON_LINES.with(|c| c.set(false));
    let p = lib_names(&s.project, p);
    let ids = ids_param(&s.project, "corner", &p)?;
    if ids.len() == 2 {
        let ca = s.project.category(ids[0]).unwrap_or("").to_string();
        let cb = s.project.category(ids[1]).unwrap_or("").to_string();
        if ca == "wall" && cb == "wall" {
            return walls(s, &p, ids[0], ids[1]);
        }
        if ca == "line" && cb == "line" {
            let r = super::ops_lines::corner_lines(s, &p, ids[0], ids[1]);
            ON_LINES.with(|c| c.set(r.is_ok()));
            return r;
        }
    }
    Err("corner: `ids` takes two walls".into())
}

/// `keep`: a point on each of the two, or none (an empty list is none).
pub fn keep_param(p: &Value, what: &str) -> R<Option<[P; 2]>> {
    match p.get("keep") {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Arr(a)) => {
            if a.is_empty() {
                return Ok(None);
            }
            let mut pts = Vec::new();
            for v in a {
                match point_of(v) {
                    Some(q) => pts.push(q),
                    None => return Err(format!("corner: `keep`: {} is not a point [x, y] in mm", v.to_compact())),
                }
            }
            if pts.len() != 2 {
                return Err(format!("corner: `keep` is a point on each {}, [[x, y], [x, y]]", what));
            }
            Ok(Some([pts[0], pts[1]]))
        }
        Some(_) => Err("corner: `keep` [[x, y], …] is required".into()),
    }
}

fn walls(s: &mut Session, p: &Value, ia: u64, ib: u64) -> R<Value> {
    let pr = &mut s.project;
    let la = wall_line(pr.el(ia).unwrap());
    let lb = wall_line(pr.el(ib).unwrap());
    if la.2 != 0.0 || lb.2 != 0.0 {
        return Err("corner: it trims and extends straight walls; a curved one changes by its ends or its `arc`".into());
    }
    let keep = keep_param(p, "wall")?;
    let Some(c) = line_cross(la.0, la.1, lb.0, lb.1) else {
        return Err("corner: the walls are parallel: they never meet".into());
    };
    let c = r3p(c);
    let ka = keep.map(|k| k[0]).unwrap_or(mul(add(la.0, la.1), 0.5));
    let kb = keep.map(|k| k[1]).unwrap_or(mul(add(lb.0, lb.1), 0.5));
    // which end of each goes to the corner: the start, where the part kept is past the corner
    // (a keep point at the corner keeps the part toward the start)
    let starts = [dot(sub(ka, c), sub(la.1, la.0)) > 0.0, dot(sub(kb, c), sub(lb.1, lb.0)) > 0.0];
    // each end moves to the corner as `move` moves a wall's end, the first wall's first: the
    // walls joined to it follow, the second among them
    for (id, start) in [(ia, starts[0]), (ib, starts[1])] {
        let old = wall_line(pr.el(id).unwrap());
        let p = if start { old.0 } else { old.1 };
        let np = add(p, sub(c, p));
        if np == p {
            continue;
        }
        let new = if start { (np, old.1, 0.0) } else { (old.0, np, 0.0) };
        set_pt(pr.el_mut(id).unwrap(), if start { "start" } else { "end" }, np);
        reoffset_openings(pr, id, old, new);
        follow_joins(pr, id, (old.0, old.1), (new.0, new.1));
    }
    Ok(crate::jobj! {"corner" => ptv(c)})
}
