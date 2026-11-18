// Engineering drawings: the chrome a part grows inside a drawing — the
// centerlines of mirrored and turned outlines, shoulder edges, thread and
// break lines, a hole's cross of centerlines, a cutting plane's mark — and
// the caption a view carries under it.

use super::lower::Cx;
use super::out::{Item, ONode};
use super::syntax::Decl;

fn chrome(cx: &mut Cx, ty: &str, what: &str) -> Item {
    let mut l = cx.typed(ty);
    l.decls = vec![Decl::val("chrome", what)];
    Item::Node(l)
}

// the first declaration of a property speaks for the drawing pass
fn first_term(o: &ONode, name: &str) -> Option<String> {
    o.decls.iter().find(|d| d.name == name).and_then(|d| d.first().map(|s| s.to_string()))
}

// a datum plane in a drawing draws as chrome (written with its own decls)
pub fn plane_chrome(o: &mut ONode, chain: &[String]) {
    if chain.iter().any(|c| c == "plane") {
        o.decls.push(Decl::val("chrome", "plane"));
    }
}

// the plan's measures (wall thickness, the size unit): under a drawing or a
// stack, whichever unit context is nearest
pub fn plan_decls(cx: &mut Cx, o: &mut ONode, chain: &[String]) {
    floorplan(cx, o, chain, true, false);
}

// a drawing's chrome: centre lines, thread and break lines, plane chrome,
// floor-plan linework
pub fn chrome_after(cx: &mut Cx, o: &mut ONode, chain: &[String]) {
    let is = |t: &str| chain.iter().any(|c| c == t);
    if o.prim == "sketch" {
        let mut extra = Vec::new();
        if let Some(m) = first_term(o, "mirror") {
            // an open outline fuses across its axis and draws it
            if m != "none" && any_open(o) {
                extra.push(chrome(cx, "centerline", &m));
            }
        }
        if let Some(r) = first_term(o, "revolve") {
            extra.push(chrome(cx, "centerline", &r));
            extra.push(chrome(cx, "shoulder", "edges"));
            if o.decls.iter().any(|d| d.name == "thread") {
                extra.push(chrome(cx, "threadline", "thread"));
            }
        }
        if o.decls.iter().any(|d| d.name == "break") {
            extra.push(chrome(cx, "breakline", "break 0"));
            extra.push(chrome(cx, "breakline", "break 1"));
        }
        o.children.extend(extra);
    } else if is("hole") {
        let mut extra = vec![chrome(cx, "centerline", "x-axis"), chrome(cx, "centerline", "y-axis")];
        // a thread is one positive number
        let thread = o.decls.iter().find(|d| d.name == "thread").and_then(|d| match d.groups.as_slice() {
            [g] if g.len() == 1 && g[0].parse::<f64>().map_or(false, |v| v > 0.0) => Some(g[0].clone()),
            _ => None,
        });
        if let Some(t) = thread {
            extra.push(chrome(cx, "threadline", &format!("thread-arc internal {}", t)));
        }
        if first_term(o, "pattern").map_or(false, |p| p.starts_with("radial(")) {
            extra.push(chrome(cx, "pitch-circle", "ring"));
        }
        o.children.extend(extra);
    }
    floorplan(cx, o, chain, false, true);
}

fn unit_mm(cx: &Cx) -> f64 {
    let unit = cx.stack.last().and_then(|f| f.unit.clone());
    match unit.as_deref().and_then(super::sheet::unit_mm) {
        Some(Some(m)) => m,
        _ => 1.0,
    }
}

fn num(v: f64) -> String {
    crate::format::parse::render_number(v)
}

// floor plans: wall thickness and the size unit, door/window/stair linework
fn floorplan(cx: &mut Cx, o: &mut ONode, chain: &[String], decls: bool, linework: bool) {
    let is = |t: &str| chain.iter().any(|c| c == t);
    if is("wall") {
        if decls && !o.decls.iter().any(|d| d.name == "thickness") {
            let t = if is("partition") {
                num(100.0 / unit_mm(cx))
            } else {
                match cx.stack.last().and_then(|f| f.thickness.clone()) {
                    Some(t) => t,
                    None => num(200.0 / unit_mm(cx)),
                }
            };
            o.decls.push(Decl::val("wall-thickness", &t));
        }
        return;
    }
    let fixture = ["door", "window", "stairs", "bed", "sofa", "dining", "bath", "appliance"];
    if !fixture.iter().any(|f| is(f)) {
        return;
    }
    if decls {
        o.decls.push(Decl::val("unit-mm", &num(unit_mm(cx))));
    }
    if !linework {
        return;
    }
    let mut extra = Vec::new();
    if is("door") {
        match first_term(o, "symbol").as_deref() {
            Some("double") => {
                extra.push(chrome(cx, "door-leaf", "leaf 0"));
                extra.push(chrome(cx, "door-swing", "swing 0"));
                extra.push(chrome(cx, "door-leaf", "leaf 1"));
                extra.push(chrome(cx, "door-swing", "swing 1"));
            }
            Some("sliding") => {
                extra.push(chrome(cx, "door-leaf", "panel 0"));
                extra.push(chrome(cx, "door-leaf", "panel 1"));
            }
            _ => {
                extra.push(chrome(cx, "door-leaf", "leaf 0"));
                extra.push(chrome(cx, "door-swing", "swing 0"));
            }
        }
    } else if is("window") {
        extra.push(chrome(cx, "window-sill", "sill 0"));
        extra.push(chrome(cx, "window-sill", "sill 1"));
    } else if is("stairs") {
        if let Some(n) = first_term(o, "steps").and_then(|s| s.parse::<f64>().ok()) {
            let n = n.trunc();
            if n >= 2.0 {
                for k in 0..(n as i64 - 1) {
                    extra.push(chrome(cx, "stair-tread", &format!("tread {}", k)));
                }
                extra.push(chrome(cx, "stair-arrow", "arrow 0"));
            }
        }
    }
    o.children.extend(extra);
}

// does any subpath of the outline stay open (not ended by close() or a circle)?
fn any_open(o: &ONode) -> bool {
    let d = match o.decls.iter().rev().find(|d| d.name == "draw") {
        Some(d) => d,
        None => return false,
    };
    let terms: Vec<&String> = d.groups.iter().flatten().collect();
    let mut subpaths: Vec<Vec<&String>> = vec![Vec::new()];
    for t in terms {
        if t.starts_with("move(") {
            if !subpaths.last().unwrap().is_empty() {
                subpaths.push(Vec::new());
            }
            continue;
        }
        subpaths.last_mut().unwrap().push(t);
    }
    // circles stand apart and corner modifiers draw nothing: a subpath is
    // open unless its strokes end in close()
    subpaths.iter().any(|s| {
        let strokes: Vec<&str> = s
            .iter()
            .map(|t| t.split(':').next().unwrap_or(""))
            .filter(|h| {
                !(h.starts_with("circle(") || h.starts_with("fillet(") || h.starts_with("chamfer(") || h.starts_with("point("))
            })
            .collect();
        match strokes.last() {
            None => false,
            Some(h) => *h != "close()",
        }
    })
}
