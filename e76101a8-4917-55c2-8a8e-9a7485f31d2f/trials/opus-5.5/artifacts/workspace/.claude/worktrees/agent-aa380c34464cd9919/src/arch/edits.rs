//! The engine's judgment of the outlines a command makes or changes (the original's
//! `check_edits`, asked after each command): a floor's, ceiling's, roof's or shaft's boundary, an
//! opening or a courtyard that isn't simple is refused, saying which edges and what to do.

use super::util::*;
use crate::geom::{sketch, P2};
use crate::project::Project;
use std::cell::RefCell;

thread_local! {
    /// Elements the command just ran made over the walls (their outline was the walls').
    static FROM_WALLS: RefCell<Vec<u64>> = const { RefCell::new(Vec::new()) };
    /// What made an element otherwise (a mass, a dormer), for what the message tells to do.
    static MADE_BY: RefCell<Vec<(u64, &'static str)>> = const { RefCell::new(Vec::new()) };
}

/// Forgets what the last command noted (called as each command starts).
pub fn reset() {
    FROM_WALLS.with(|f| f.borrow_mut().clear());
    MADE_BY.with(|f| f.borrow_mut().clear());
}

/// Notes that an element's outline was taken from the walls.
pub fn note_walls(id: u64, yes: bool) {
    if yes {
        FROM_WALLS.with(|f| f.borrow_mut().push(id));
    }
}

/// Notes what made an element (`mass`, `dormer`).
pub fn note_made_by(id: u64, by: &'static str) {
    MADE_BY.with(|f| f.borrow_mut().push((id, by)));
}

fn from_walls(id: u64) -> bool {
    FROM_WALLS.with(|f| f.borrow().contains(&id))
}

fn made_by(id: u64) -> Option<&'static str> {
    MADE_BY.with(|f| f.borrow().iter().find(|x| x.0 == id).map(|x| x.1))
}

/// The rings of an outlined element: (what the message calls it, the ring), in order.
fn rings_of(e: &crate::json::Value) -> Vec<(String, Vec<P2>)> {
    let mut out = Vec::new();
    if let Some(b) = pts(e, "boundary") {
        out.push(("boundary".to_string(), b));
    }
    match cat(e) {
        "roof" => {
            for (i, r) in rings(e, "courtyards").into_iter().enumerate() {
                out.push((format!("courtyard {}", i), r));
            }
            for (i, r) in rings(e, "openings").into_iter().enumerate() {
                out.push((format!("opening {}", i), r));
            }
        }
        "floor" | "ceiling" => {
            for (i, r) in rings(e, "openings").into_iter().enumerate() {
                out.push((format!("opening {}", i), r));
            }
        }
        _ => {}
    }
    out
}

/// Each outline the command made or changed, judged as the sketch of its edges.
pub fn check_edits(before: &Project, after: &Project, cid: &str) -> Result<(), String> {
    // what moves, copies, turns or mirrors an outline makes it no worse
    if matches!(cid, "move" | "copy" | "rotate" | "mirror" | "align") {
        return Ok(());
    }
    for (id, e) in &after.elements {
        let c = cat(e);
        if !matches!(c, "floor" | "ceiling" | "roof" | "shaft") {
            continue;
        }
        let old = before.elements.get(id).filter(|o| cat(o) == c);
        let new_rings = rings_of(e);
        let old_rings = old.map(rings_of).unwrap_or_default();
        for (k, (what, ring)) in new_rings.iter().enumerate() {
            if let Some(o) = old_rings.get(k) {
                if o.0 == *what && o.1 == *ring {
                    continue;
                }
            }
            // a ring of too few points is the model's to refuse
            if ring.len() < 3 || ring.len() > 10000 {
                continue;
            }
            let probs = sketch::ring_problems(ring);
            if probs.is_empty() {
                continue;
            }
            let said = sketch::describe(&probs, "edge");
            let is_boundary = what == "boundary";
            if old.is_none() {
                let todo = match made_by(*id) {
                    Some("mass") => "redraw the mass whose outline it is".to_string(),
                    Some("dormer") => "from `dormer` change the dormer's width, height or position".to_string(),
                    _ => {
                        if is_boundary {
                            let mut t = "give a simple `boundary` or `sketch`".to_string();
                            if from_walls(*id) {
                                t.push_str(" (walls, or boxes of walls, that touch at a corner enclose no simple outline of their own)");
                            }
                            t
                        } else if what.starts_with("courtyard") {
                            "give simple `courtyards`".to_string()
                        } else {
                            "give simple `openings`".to_string()
                        }
                    }
                };
                let who = if cid == c || matches!(cid, "floor" | "ceiling" | "roof" | "shaft") { cid.to_string() } else { format!("{} {}", c, id) };
                return Err(format!("{}: its {} isn't a simple outline: {}; {}", who, what, said, todo));
            }
            let todo = if c == "roof" && what.starts_with("opening") {
                if cid == "dormer" {
                    "give `modify` a simple `openings`, or change the dormer's width, height or position"
                } else {
                    "give `modify` a simple `openings`"
                }
            } else {
                "redraw it with `edit_boundary`"
            };
            return Err(format!("{} {}: its {} isn't a simple outline: {}; {}", c, id, what, said, todo));
        }
    }
    Ok(())
}
