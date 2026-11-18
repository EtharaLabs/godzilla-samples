//! Stand-ins for model rules other areas own (ARCH's openings), checked after every command until
//! theirs are in: a door or a window fits its wall (within a millimetre at each end), and two
//! openings of one wall don't overlap (by more than a millimetre). The texts are the original's.

use super::common::*;
use crate::project::Project;

/// A door's or a window's height: its family type's `Height`, or its type's.
fn opening_height(pr: &Project, e: &crate::json::Value) -> f64 {
    let kind = cat_of(e).to_string();
    let name_of = |k: &str| e.get(k).and_then(|g| g.as_str()).and_then(|g| pr.lib_name(g));
    if let Some(fam) = name_of("family") {
        let typ = name_of("type").unwrap_or_default();
        let tname = typ.strip_prefix(&format!("{}: ", fam)).unwrap_or(&typ).to_string();
        if let Some(f) = pr.section("families").and_then(|m| m.get(&fam)) {
            if let Some(v) = f.get("types").and_then(|t| t.get(&tname)).and_then(|t| t.get("Height")).and_then(|x| x.as_f64()) {
                return v;
            }
            if let Some(ps) = f.get("parameters").and_then(|x| x.as_arr()) {
                for p in ps {
                    if p.get("name").and_then(|n| n.as_str()) == Some("Height") {
                        if let Some(v) = p.get("value").and_then(|x| x.as_f64()) {
                            return v;
                        }
                    }
                }
            }
        }
    }
    if let Some(name) = name_of("type") {
        if let Some(v) = pr
            .section("types")
            .and_then(|t| t.get(&kind))
            .and_then(|t| t.get(&name))
            .and_then(|t| t.get("height"))
            .and_then(|x| x.as_f64())
        {
            return v;
        }
    }
    0.0
}

pub fn check(pr: &Project) -> R<()> {
    let mut by_wall: std::collections::BTreeMap<u64, Vec<(u64, f64, f64)>> = Default::default();
    for (id, e) in &pr.elements {
        let cat = cat_of(e);
        if cat == "wall" {
            let l = super::transform::wall_line(e);
            let len = super::transform::line_len(&l);
            if !(len > 1.0) {
                return Err(format!("wall {}: too short ({} mm)", id, len));
            }
            continue;
        }
        if !matches!(cat, "door" | "window") {
            continue;
        }
        let Some(w) = e.get("host").and_then(|h| h.as_str()).and_then(|g| pr.find_guid(g)) else { continue };
        let Some(we) = pr.el(w) else { continue };
        if cat_of(we) != "wall" {
            continue;
        }
        let l = super::transform::wall_line(we);
        let len = if l.arc == 0.0 { (l.b[0] - l.a[0]).hypot(l.b[1] - l.a[1]) } else { super::transform::line_len(&l) };
        let width = super::ops_geom::opening_width(pr, e);
        let off = e.get("offset").and_then(|x| x.as_f64()).unwrap_or(0.0);
        if !(off - width / 2.0 >= -1.0 && off + width / 2.0 <= len + 1.0) {
            return Err(format!(
                "{} {}: {} mm wide at offset {} doesn't fit wall {}, {} mm long",
                cat, id, width, off, w, len
            ));
        }
        // and up the wall (one that follows a roof or a floor is left to its owner)
        let attached = ["attach_top", "attach_base"].iter().any(|k| we.get(k).map(|x| !x.is_null()).unwrap_or(false));
        let (z0, z1) = super::transform::wall_span(pr, w);
        // (a wall no taller than nothing is its own rule's to refuse)
        if !attached && z1 > z0 {
            let sill = e.get("sill").and_then(|x| x.as_f64()).unwrap_or(0.0);
            let height = opening_height(pr, e);
            if !(sill >= 0.0 && sill + height <= (z1 - z0) + 1.0) {
                return Err(format!("{} {}: sill {} + height {} doesn't fit wall {}'s height", cat, id, sill, height, w));
            }
        }
        by_wall.entry(w).or_default().push((*id, off, width));
    }
    for (w, ops) in by_wall.iter_mut() {
        // along the wall, from its start
        ops.sort_by(|x, y| x.1.partial_cmp(&y.1).unwrap_or(std::cmp::Ordering::Equal));
        for i in 0..ops.len() {
            for j in i + 1..ops.len() {
                let (a, oa, wa) = ops[i];
                let (b, ob, wb) = ops[j];
                if (oa - ob).abs() < (wa + wb) / 2.0 - 1.0 {
                    let ca = pr.category(a).unwrap_or("door");
                    let cb = pr.category(b).unwrap_or("door");
                    return Err(format!(
                        "{} {} and {} {} overlap in wall {}",
                        ca,
                        a,
                        cb,
                        b,
                        pr.guid_of(*w).unwrap_or_default()
                    ));
                }
            }
        }
    }
    Ok(())
}
