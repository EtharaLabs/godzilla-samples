// Floor plans [SPEC 15.11]: the drawing engine wearing an architect's
// vocabulary.
//
// - `|wall|` / `|partition|` are sketches whose `draw:` is the CENTRELINE;
//   `outline()` thickens it into the poché (mitred joints, bevelled past
//   miter limit 4, concentric arcs) and cuts every opening's gap out of it.
// - `|door|` / `|window|` ride their wall's `[ ]`: `on:` names a straight
//   tagged segment, `at:` stations the opening along the segment's drawing
//   direction, `width:` (900 / 1200 mm) its gap. The opening is a block on
//   the gap (rotated to the run) drawing its leaf + quarter swing arc
//   (`swing:` left|right of the pen's travel, `hinge:` start|end), two leaves
//   for `double`, two panels for `sliding`, or a window's sill pair.
// - `|stairs|` and the fixture families (`|bed|`, `|sofa|`, `|dining|`,
//   `|bath|`, `|appliance|`) draw true-size symbol bodies as one path,
//   stretched by an explicit width / height; a label reads beside the body
//   (an appliance's inside it).
// - `a:seg-in (-) b:seg-out` dimensions read clear spans between wall faces
//   (`-in` / `-out` derived from every tagged segment), stacked in tiers on
//   their side of the plan. Node anchors work too (a side is an edge, the
//   centre / a corner a point, a bare wall its pen origin).
// - A slanted face, a rotated side or two points off-axis make an ALIGNED
//   dimension: it reads along its own slant, sits left / right of
//   first → second (by default away from the plan's centre), 20 off its
//   anchors (32 with the text between), and is pushed past any dimension
//   whose band (line, arrows, upright text) or text box comes within 18.
// - Halos cut witness lines (and an aligned dimension's own line) where they
//   cross outlines at sin >= 0.1; gaps merge in crossing order, never open
//   under a laid arrowhead, nor reach back to a witness line's foot.
//
// Pipeline hooks: `expand` (after drawing::expand) validates and grows the
// generated linework nodes; drawing::lay_sketch calls `outline`;
// drawing::measure_part defers to `measure`; drawing::measure_frame calls
// `layout_dims`; render::render_node defers to `render_node`.

use crate::ast::Term;
use crate::compile::Ctx;
use crate::diag::{Diag, Span};
use crate::geom::BBox;
use crate::render::Out;
use crate::scene::Node;
use crate::sketch::{fmt3, pt, Seg, Shape, Sub, P};
use crate::style::{ident_of, single_term, value_num};
use crate::types::Prim;
use crate::util::{f4, xml_escape};
use std::collections::{HashMap, HashSet};

// Drafting constants (px).
const LABEL_GAP: f64 = 8.0;
const LABEL_STACK_GAP: f64 = 4.0;
const MITER_LIMIT: f64 = 4.0;
const DIM_TEXT: f64 = 12.0;
const DIM_TEXT_OFF: f64 = 8.0;
const EXT_GAP: f64 = 3.0;
const EXT_OVER: f64 = 3.0;
const ARROW_LEN: f64 = 12.0;
const ARROW_HALF: f64 = 2.0;
// the clearance an aligned dimension keeps from the others
const DIM_CLEAR: f64 = 18.0;

#[derive(Clone, Debug)]
pub enum Part {
    Leaf(usize),
    Swing(usize),
    Panel(usize),
    Sill(usize),
    Tread(usize),
    Arrow,
    Dim(usize),
}

#[derive(Clone, Debug, Default)]
pub struct Opening {
    pub wall: usize,
    // (subpath, segment) of the wall's pen result, when stationed
    pub seg: Option<(usize, usize)>,
    pub at: f64,
    pub width: f64,
    pub door: bool,
    pub right: bool,
    pub end: bool,
    pub symbol: String,
}

#[derive(Clone, Debug, Default)]
pub struct Dim {
    pub link: usize,
    pub frame: usize,
    pub node: usize,
    // laid out, in the frame's datum (px)
    pub ext: Vec<(P, P)>,
    pub line: (P, P),
    pub marks: Vec<[P; 3]>,
    pub text: String,
    pub text_at: P,
    pub text_rot: f64,
    pub laid: bool,
    // per ext line: the halo gaps (from, to) along it, and its mask number
    pub halos: Vec<Vec<(f64, f64)>>,
    pub mask_ids: Vec<Option<usize>>,
    // the dimension line's own halo gaps and mask number
    pub line_halos: Vec<(f64, f64)>,
    pub line_mask: Option<usize>,
    // a side the dimension's own geometry rules out (point anchors only
    // settle their axis once laid out)
    pub err: Option<Diag>,
    // the link's own text size and stroke weight
    pub fs: f64,
    pub sw: f64,
}

#[derive(Default)]
pub struct State {
    // generated linework nodes
    pub parts: HashMap<usize, Part>,
    pub openings: HashMap<usize, Opening>,
    // fixture node → (family, symbol)
    pub fixtures: HashMap<usize, (String, String)>,
    // laid-out linework: the element (unindented) per part node
    pub elems: HashMap<usize, String>,
    // parts drawn as a path (swing arcs, the stair arrow)
    pub as_path: HashSet<usize>,
    // label texts: their counter-rotation
    pub text_rot: HashMap<usize, f64>,
    pub dims: Vec<Dim>,
}

// ------------------------------------------------------------ helpers

fn is_fixture_family(n: &Node) -> Option<&'static str> {
    for f in ["bed", "sofa", "dining", "bath", "appliance"] {
        if n.is(f) {
            return Some(f);
        }
    }
    None
}

fn variants(family: &str) -> &'static [&'static str] {
    match family {
        "bed" => &["queen", "king", "double", "single"],
        "sofa" => &["three", "two", "one", "corner", "stool"],
        "dining" => &["six", "four", "round"],
        "bath" => &["tub", "shower", "toilet", "sink", "double-sink"],
        "appliance" => &["stove", "fridge", "washer", "dishwasher"],
        "door" => &["single", "double", "sliding"],
        _ => &[],
    }
}

fn doc_order(ctx: &Ctx) -> Vec<usize> {
    let mut out = Vec::new();
    let mut stack = vec![0usize];
    while let Some(i) = stack.pop() {
        out.push(i);
        for &c in ctx.nodes[i].children.iter().rev() {
            stack.push(c);
        }
    }
    out
}

fn decl_span(ctx: &Ctx, i: usize, name: &str) -> Span {
    let n = &ctx.nodes[i];
    if let Some(d) = n.inline.iter().rev().find(|d| d.name == name) {
        return d.span;
    }
    if let Some(id) = &n.id {
        for (rid, ds) in ctx.sheet.id_rules.iter().rev() {
            if rid == id {
                if let Some(d) = ds.iter().rev().find(|d| d.name == name) {
                    return d.span;
                }
            }
        }
    }
    for c in n.classes.iter().rev() {
        if let Some(cr) = ctx.sheet.class(c) {
            if let Some(d) = cr.decls.iter().rev().find(|d| d.name == name) {
                return d.span;
            }
        }
    }
    for t in &n.chain {
        if let Some(d) = ctx.sheet.type_rule(t).into_iter().rev().find(|d| d.name == name) {
            return d.span;
        }
        if let Some(df) = ctx.sheet.define(t) {
            if let Some(d) = df.decls.iter().rev().find(|d| d.name == name) {
                return d.span;
            }
        }
    }
    if i == 0 {
        if let Some(d) = ctx.sheet.root.iter().rev().find(|d| d.name == name) {
            return d.span;
        }
    }
    n.props.get(name).map(|v| v.span).unwrap_or(n.span)
}

fn num_prop(ctx: &Ctx, i: usize, name: &str) -> Option<f64> {
    ctx.nodes[i].props.get(name).and_then(|v| value_num(&ctx.sheet.env, v))
}

fn ident_prop(ctx: &Ctx, i: usize, name: &str) -> Option<String> {
    ctx.nodes[i].props.get(name).and_then(ident_of).map(|s| s.to_string())
}

// The nearest floor-plan frame at or above `i`.
fn plan_of(ctx: &Ctx, i: usize) -> Option<usize> {
    let mut cur = Some(i);
    while let Some(k) = cur {
        if crate::drawing::is_frame(ctx, k) && ctx.comp[k].layout == "floorplan" {
            return Some(k);
        }
        cur = ctx.nodes[k].parent;
    }
    None
}

fn in_plan(ctx: &Ctx, i: usize) -> bool {
    match ctx.nodes[i].parent {
        Some(p) => plan_of(ctx, p).is_some(),
        None => false,
    }
}

fn unit_mm_of(ctx: &Ctx, i: usize) -> f64 {
    let mut cur = Some(i);
    while let Some(k) = cur {
        if crate::drawing::is_frame(ctx, k) {
            if let Some(u) = ctx.nodes[k].props.get("unit").and_then(ident_of) {
                return match u {
                    "mm" => 1.0,
                    "cm" => 10.0,
                    "m" => 1000.0,
                    "in" => 25.4,
                    _ => 1.0,
                };
            }
        }
        cur = ctx.nodes[k].parent;
    }
    1.0
}

// px per millimetre at node i: true size whatever the drafting unit.
fn px_per_mm(ctx: &Ctx, i: usize) -> f64 {
    crate::drawing::ps(ctx, i) / unit_mm_of(ctx, i)
}

// A wall's thickness in units: its own, else the nearest ancestor's (walls),
// else 200 mm (walls) / 100 mm (partitions).
pub fn wall_thickness(ctx: &Ctx, i: usize) -> f64 {
    if let Some(t) = num_prop(ctx, i, "thickness") {
        return t;
    }
    let partition = ctx.nodes[i].is("partition");
    if !partition {
        let mut cur = ctx.nodes[i].parent;
        while let Some(p) = cur {
            if let Some(t) = num_prop(ctx, p, "thickness") {
                return t;
            }
            cur = ctx.nodes[p].parent;
        }
    }
    let mm = if partition { 100.0 } else { 200.0 };
    mm / unit_mm_of(ctx, i)
}

fn clean(v: f64) -> f64 {
    if v == 0.0 {
        0.0
    } else {
        v
    }
}

// The counter-rotation a label takes so it never reads upside down: the
// half-turns that bring its total into [-90, 90).
fn counter(deg: f64) -> f64 {
    let k = ((-90.0 - deg) / 180.0 - 1e-9).ceil();
    clean(180.0 * k)
}

fn add_part(ctx: &mut Ctx, parent: usize, chain: &[&str], prim: Prim, part: Part) -> usize {
    // generated after the host's statement
    let end = ctx.nodes[parent].span.end;
    let mut n = Node::new(prim, chain.iter().map(|s| s.to_string()).collect(), Span::new(end, end));
    n.parent = Some(parent);
    n.scope = ctx.nodes[parent].scope;
    let i = ctx.nodes.len();
    ctx.nodes.push(n);
    ctx.comp.push(ctx.comp[parent].clone());
    ctx.nodes[parent].children.push(i);
    // a host that lays its children out itself leaves its linework plain
    // lines (which then lack their points)
    let own = &ctx.nodes[parent].props;
    if !own.contains_key("layout") && !own.contains_key("direction") {
        ctx.sk.fp.parts.insert(i, part);
    }
    i
}

// ------------------------------------------------------------ validation

fn misused(prop: &str, on: &str, reads: &str, span: Span) -> Diag {
    Diag::error("misused-property", &format!("'{}' has no meaning on '|{}|' — it reads on {}", prop, on, reads), span)
}

const SYMBOL_READS: &str = "'|icon|' / '|surface-finish|' / '|label|' / the discrete parts ('|R|', '|C|', …) / '|door|' / '|bed|' / '|sofa|' / '|dining|' / '|bath|' / '|appliance|'";

fn check_thickness(ctx: &Ctx, i: usize) -> Result<(), Diag> {
    if let Some(v) = ctx.nodes[i].props.get("thickness") {
        let ok = single_term(v).is_some() && value_num(&ctx.sheet.env, v).map(|x| x > 0.0).unwrap_or(false);
        if !ok {
            return Err(Diag::error("malformed-value", "'thickness' takes a number > 0", decl_span(ctx, i, "thickness")));
        }
    }
    Ok(())
}

// The floor-plan properties of one node, in declaration order: values, and
// properties written on a type that never reads them.
fn check_props(ctx: &Ctx, i: usize) -> Result<(), Diag> {
    let n = &ctx.nodes[i];
    let tname = n.chain.first().cloned().unwrap_or_default();
    let is_plan = crate::drawing::is_frame(ctx, i) && ctx.comp[i].layout == "floorplan";
    let opening = n.is("door") || n.is("window");
    let mut names: Vec<String> = Vec::new();
    if let Some(id) = &n.id {
        for (rid, ds) in &ctx.sheet.id_rules {
            if rid == id {
                names.extend(ds.iter().map(|d| d.name.clone()));
            }
        }
    }
    names.extend(n.inline.iter().map(|d| d.name.clone()));
    let mut seen: Vec<String> = Vec::new();
    for name in names {
        if seen.contains(&name) {
            continue;
        }
        seen.push(name.clone());
        let sp = || decl_span(ctx, i, &name);
        match name.as_str() {
            "swing" | "hinge" => {
                if !n.is("door") {
                    return Err(misused(&name, &tname, "'|door|'", sp()));
                }
                let v = ident_prop(ctx, i, &name);
                let ok = if name == "swing" {
                    matches!(v.as_deref(), Some("left") | Some("right"))
                } else {
                    matches!(v.as_deref(), Some("start") | Some("end"))
                };
                if !ok {
                    let msg = if name == "swing" {
                        "'swing' opens the leaf left or right of the pen's travel"
                    } else {
                        "'hinge' hangs the leaf at the segment's start or end"
                    };
                    return Err(Diag::error("malformed-value", msg, sp()));
                }
            }
            "steps" => {
                if !n.is("stairs") {
                    return Err(misused("steps", &tname, "'|stairs|'", sp()));
                }
                let v = &n.props["steps"];
                let k = single_term(v).and_then(|_| value_num(&ctx.sheet.env, v));
                if !matches!(k, Some(x) if x >= 2.0 && x.fract() == 0.0) {
                    return Err(Diag::error("malformed-value", "'steps' takes a tread count ≥ 2", sp()));
                }
            }
            "on" if !opening => {
                return Err(misused("on", &tname, "a wall opening ('|door|' / '|window|')", sp()));
            }
            "at" if !opening && !n.is("mark") && !n.is("bubble") && !n.is("plane") => {
                return Err(misused("at", &tname, "'|mark|' / '|bubble|' / '|plane|' / a wall opening ('|door|' / '|window|')", sp()));
            }
            "thickness" => {
                if !is_plan && !n.is("wall") {
                    return Err(misused("thickness", &tname, "'|floorplan|' / '|wall|'", sp()));
                }
                check_thickness(ctx, i)?;
            }
            "symbol" => {
                const READS: &[&str] = &[
                    "icon", "surface-finish", "label", "gnd", "nc", "R", "C", "L", "D", "LED", "Q", "Y", "F", "FB", "SW", "BT", "V",
                    "I", "M", "BZ", "TP", "door", "bed", "sofa", "dining", "bath", "appliance",
                ];
                if !READS.iter().any(|t| n.is(t)) {
                    return Err(misused("symbol", &tname, SYMBOL_READS, sp()));
                }
            }
            _ => {}
        }
    }
    Ok(())
}

// Run every floor-plan check and grow the generated linework.
pub fn expand(ctx: &mut Ctx) -> Result<bool, Diag> {
    let order = doc_order(ctx);
    // property checks first, then the plan's own
    for &i in &order {
        if ctx.nodes[i].prim == Prim::Text {
            continue;
        }
        if i == 0 {
            if crate::drawing::is_frame(ctx, 0) && ctx.comp[0].layout == "floorplan" {
                check_thickness(ctx, 0)?;
            }
            continue;
        }
        check_props(ctx, i)?;
    }
    let mut grew = false;
    for &i in &order {
        if ctx.nodes[i].prim == Prim::Text {
            continue;
        }
        if ctx.nodes[i].is("wall") {
            if !in_plan(ctx, i) {
                let t = if ctx.nodes[i].is("partition") { "partition" } else { "wall" };
                return Err(Diag::error("floorplan-type", &format!("'|{}|' belongs in a 'layout: floorplan'", t), ctx.nodes[i].span));
            }
            check_wall(ctx, i)?;
        } else if ctx.nodes[i].is("door") || ctx.nodes[i].is("window") {
            opening(ctx, i)?;
            grew = true;
        } else if ctx.nodes[i].is("stairs") {
            stairs(ctx, i)?;
            grew = true;
        } else if let Some(f) = is_fixture_family(&ctx.nodes[i]) {
            if !in_plan(ctx, i) {
                return Err(Diag::error("floorplan-type", &format!("'|{}|' belongs in a 'layout: floorplan'", f), ctx.nodes[i].span));
            }
            let sym = ident_prop(ctx, i, "symbol").unwrap_or_else(|| variants(f)[0].to_string());
            if !variants(f).contains(&sym.as_str()) {
                let msg = format!("unknown symbol '{}' on '|{}|' — its variants are {}", sym, f, variants(f).join(", "));
                return Err(Diag::error("layout", &msg, ctx.nodes[i].span));
            }
            ctx.sk.fp.fixtures.insert(i, (f.to_string(), sym));
        }
    }
    dims_expand(ctx)?;
    Ok(grew)
}

fn check_wall(ctx: &Ctx, i: usize) -> Result<(), Diag> {
    let base = match ctx.sk.base.get(&i) {
        Some(b) => b,
        None => return Ok(()),
    };
    let h = wall_thickness(ctx, i) / 2.0;
    for s in &base.subs {
        for g in &s.segs {
            match g {
                Seg::Cubic { .. } => {
                    return Err(Diag::error("wall-curve", "a wall bends with 'arc()' — 'curve()' has no offset", ctx.nodes[i].span));
                }
                Seg::Arc { r, .. } => {
                    if *r < h - 1e-12 {
                        let msg = format!("arc radius {} is under thickness/2 — the inner face vanishes", fmt3(*r));
                        return Err(Diag::error("arc-under-thickness", &msg, ctx.nodes[i].span));
                    }
                }
                _ => {}
            }
        }
    }
    Ok(())
}

fn opening(ctx: &mut Ctx, i: usize) -> Result<(), Diag> {
    let door = ctx.nodes[i].is("door");
    let tname = if door { "door" } else { "window" };
    let span = ctx.nodes[i].span;
    if !in_plan(ctx, i) {
        return Err(Diag::error("floorplan-type", &format!("'|{}|' belongs in a 'layout: floorplan'", tname), span));
    }
    let wall = match ctx.nodes[i].parent {
        Some(p) if ctx.nodes[p].is("wall") => p,
        _ => return Err(Diag::error("opening-host", &format!("a '|{}|' rides in its wall's '[ ]'", tname), span)),
    };
    let on = match ctx.nodes[i].props.get("on") {
        Some(v) => v.clone(),
        None => {
            return Err(Diag::error(
                "missing-required-property",
                &format!("'|{}|' requires 'on' — the wall segment it stations on", tname),
                span,
            ))
        }
    };
    // an opening is stationed, never placed
    if ctx.nodes[i].props.contains_key("translate") {
        return Err(Diag::error("opening-placed", "an opening sits at 'on:' / 'at:' — move the station, or nudge the wall", span));
    }
    let symbol = if door { ident_prop(ctx, i, "symbol").unwrap_or_else(|| "single".to_string()) } else { String::new() };
    if door && !variants("door").contains(&symbol.as_str()) {
        let msg = format!("unknown symbol '{}' on '|door|' — its variants are single, double, sliding", symbol);
        return Err(Diag::error("layout", &msg, span));
    }
    if symbol == "sliding" && (ctx.nodes[i].props.contains_key("hinge") || ctx.nodes[i].props.contains_key("swing")) {
        return Err(Diag::error("sliding-door-leaf", "a sliding door has no leaf to hang — remove 'hinge:' / 'swing:'", span));
    }
    let right = ident_prop(ctx, i, "swing").as_deref() == Some("right");
    let end = ident_prop(ctx, i, "hinge").as_deref() == Some("end");
    let umm = unit_mm_of(ctx, i);
    let width = num_prop(ctx, i, "width").unwrap_or(if door { 900.0 } else { 1200.0 } / umm);
    let at = num_prop(ctx, i, "at").unwrap_or(0.0);
    let mut op = Opening { wall, seg: None, at, width, door, right, end, symbol: symbol.clone() };
    // the segment it stations on
    let tag = match single_term(&on) {
        Some(Term::Ident(s, _)) => Some(s.clone()),
        _ => None,
    };
    if let (Some(tag), Some(base)) = (tag, ctx.sk.base.get(&wall)) {
        let mut found: Option<(usize, usize)> = None;
        for (si, s) in base.subs.iter().enumerate() {
            for (gi, t) in s.tags.iter().enumerate() {
                if t.as_deref() == Some(tag.as_str()) {
                    found = Some((si, gi));
                }
            }
        }
        let is_point = base.points.iter().any(|(n, _)| *n == tag);
        match found {
            None if is_point => {
                let msg = format!("an opening sits on a straight run — ':{}' is a point", tag);
                return Err(Diag::error("opening-segment", &msg, span));
            }
            None => {
                // the one nearest name, two edits at most
                let best = base.tags().iter().map(|t| (crate::util::levenshtein(&tag, &t.name), t.name.clone())).filter(|(d, _)| *d <= 2).min_by_key(|(d, _)| *d);
                let hint = best.map(|(_, n)| format!("; did you mean '{}'?", n)).unwrap_or_default();
                let msg = format!("'{}' is not a segment of this wall{}", tag, hint);
                return Err(Diag::error("opening-segment", &msg, span));
            }
            Some((si, gi)) => {
                let g = &base.subs[si].segs[gi];
                if !g.is_line() {
                    let msg = format!("an opening sits on a straight run — ':{}' is an arc", tag);
                    return Err(Diag::error("opening-segment", &msg, span));
                }
                let len = g.length();
                if at < -1e-9 || at + width > len + 1e-9 {
                    let msg = format!(
                        "'|{}|' at {} + width {} overruns '{}' (length {})",
                        tname,
                        fmt3(at),
                        fmt3(width),
                        tag,
                        fmt3(len)
                    );
                    return Err(Diag::error("opening-overrun", &msg, span));
                }
                // openings share a run as long as they never overlap
                let (a0, a1) = (at, at + width);
                for &sib in &ctx.nodes[wall].children {
                    if sib == i {
                        break;
                    }
                    if let Some(p) = ctx.sk.fp.openings.get(&sib) {
                        if p.seg == Some((si, gi)) && a0 < p.at + p.width - 1e-9 && p.at < a1 - 1e-9 {
                            let other = if p.door { "door" } else { "window" };
                            let msg = format!("'|{}|' and '|{}|' overlap on '{}'", other, tname, tag);
                            return Err(Diag::error("opening-overlap", &msg, span));
                        }
                    }
                }
                op.seg = Some((si, gi));
            }
        }
    }
    ctx.sk.fp.openings.insert(i, op);
    // the linework
    if door {
        match symbol.as_str() {
            "double" => {
                add_part(ctx, i, &["door-leaf", "line"], Prim::Line, Part::Leaf(0));
                add_part(ctx, i, &["door-swing", "line"], Prim::Line, Part::Swing(0));
                add_part(ctx, i, &["door-leaf", "line"], Prim::Line, Part::Leaf(1));
                add_part(ctx, i, &["door-swing", "line"], Prim::Line, Part::Swing(1));
            }
            "sliding" => {
                add_part(ctx, i, &["door-leaf", "line"], Prim::Line, Part::Panel(0));
                add_part(ctx, i, &["door-leaf", "line"], Prim::Line, Part::Panel(1));
            }
            _ => {
                add_part(ctx, i, &["door-leaf", "line"], Prim::Line, Part::Leaf(0));
                add_part(ctx, i, &["door-swing", "line"], Prim::Line, Part::Swing(0));
            }
        }
    } else {
        add_part(ctx, i, &["window-sill", "line"], Prim::Line, Part::Sill(0));
        add_part(ctx, i, &["window-sill", "line"], Prim::Line, Part::Sill(1));
    }
    Ok(())
}

fn stairs(ctx: &mut Ctx, i: usize) -> Result<(), Diag> {
    let span = ctx.nodes[i].span;
    let steps = match ctx.nodes[i].props.get("steps") {
        Some(v) => {
            let n = single_term(v).and_then(|_| value_num(&ctx.sheet.env, v));
            match n {
                Some(x) if x >= 2.0 && x.fract() == 0.0 => x as usize,
                _ => return Err(Diag::error("malformed-value", "'steps' takes a tread count ≥ 2", decl_span(ctx, i, "steps"))),
            }
        }
        None => return Err(Diag::error("missing-required-property", "'|stairs|' requires 'steps' — its tread count", span)),
    };
    let _ = SYMBOL_READS;
    if !in_plan(ctx, i) {
        return Err(Diag::error("floorplan-type", "'|stairs|' belongs in a 'layout: floorplan'", span));
    }
    ctx.sk.fp.fixtures.insert(i, ("stairs".to_string(), steps.to_string()));
    // a pattern's wrapper draws only its copies
    if ctx.sk.wrappers.contains_key(&i) {
        return Ok(());
    }
    for k in 0..steps - 1 {
        add_part(ctx, i, &["stair-tread", "line"], Prim::Line, Part::Tread(k));
    }
    add_part(ctx, i, &["stair-arrow", "line"], Prim::Line, Part::Arrow);
    Ok(())
}

// ------------------------------------------------------------ walls

fn line_x(a1: P, d1: P, a2: P, d2: P) -> Option<P> {
    let den = d1.cross(d2);
    if den.abs() < 1e-12 {
        return None;
    }
    let t = a2.sub(a1).cross(d2) / den;
    Some(a1.add(d1.mul(t)))
}

fn set_start(g: &mut Seg, p: P) {
    match g {
        Seg::Line { a, .. } | Seg::Arc { a, .. } | Seg::Cubic { a, .. } => *a = p,
    }
}

fn set_end(g: &mut Seg, p: P) {
    match g {
        Seg::Line { b, .. } | Seg::Arc { b, .. } | Seg::Cubic { b, .. } => *b = p,
    }
}

// One side of a drawn run offset by `h` (side +1 = the pen's left).
fn offset_seg(g: &Seg, side: f64, h: f64) -> Seg {
    match g {
        Seg::Line { a, b } => {
            let n = b.sub(*a).unit().left().mul(side * h);
            Seg::Line { a: a.add(n), b: b.add(n) }
        }
        Seg::Arc { a, b, c, r, sweep, large } => {
            let rr = r + side * h * if *sweep > 0.0 { 1.0 } else { -1.0 };
            Seg::Arc {
                a: c.add(a.sub(*c).unit().mul(rr)),
                b: c.add(b.sub(*c).unit().mul(rr)),
                c: *c,
                r: rr.abs(),
                sweep: *sweep,
                large: *large,
            }
        }
        Seg::Cubic { a, c1, c2, b } => {
            let n0 = c1.sub(*a).unit().left().mul(side * h);
            let n1 = b.sub(*c2).unit().left().mul(side * h);
            Seg::Cubic { a: a.add(n0), c1: c1.add(n0), c2: c2.add(n1), b: b.add(n1) }
        }
    }
}

// Where two offset runs cross near the joint p (the inside of a turn).
fn cross_point(g1: &Seg, g2: &Seg, p: P) -> Option<P> {
    fn line_circle(a: P, b: P, c: P, r: f64, p: P) -> Option<P> {
        let d = b.sub(a);
        let dl = d.len();
        if dl == 0.0 {
            return None;
        }
        let u = d.mul(1.0 / dl);
        let f = a.sub(c);
        let bb = f.dot(u);
        let disc = bb * bb - (f.dot(f) - r * r);
        if disc < 0.0 {
            return None;
        }
        let s = disc.sqrt();
        let x1 = a.add(u.mul(-bb + s));
        let x2 = a.add(u.mul(-bb - s));
        Some(if x1.sub(p).len() <= x2.sub(p).len() { x1 } else { x2 })
    }
    match (g1, g2) {
        (Seg::Line { a: a1, b: b1 }, Seg::Line { a: a2, b: b2 }) => line_x(*a1, b1.sub(*a1), *a2, b2.sub(*a2)),
        (Seg::Line { a, b }, Seg::Arc { c, r, .. }) | (Seg::Arc { c, r, .. }, Seg::Line { a, b }) => line_circle(*a, *b, *c, *r, p),
        (Seg::Arc { c: c1, r: r1, .. }, Seg::Arc { c: c2, r: r2, .. }) => {
            let dv = c2.sub(*c1);
            let d = dv.len();
            if d == 0.0 {
                return None;
            }
            let a = (r1 * r1 - r2 * r2 + d * d) / (2.0 * d);
            let hh = r1 * r1 - a * a;
            if hh < 0.0 {
                return None;
            }
            let h = hh.sqrt();
            let u = dv.mul(1.0 / d);
            let m = c1.add(u.mul(a));
            let x1 = m.add(u.right().mul(h));
            let x2 = m.sub(u.right().mul(h));
            Some(if x1.sub(p).len() <= x2.sub(p).len() { x1 } else { x2 })
        }
        _ => None,
    }
}

// Where x sits along a run: 0 at its start, 1 at its end.
fn param_of(g: &Seg, x: P) -> f64 {
    match g {
        Seg::Line { a, b } => {
            let d = b.sub(*a);
            let l2 = d.dot(d);
            if l2 == 0.0 {
                0.0
            } else {
                x.sub(*a).dot(d) / l2
            }
        }
        Seg::Arc { a, c, sweep, .. } => {
            let u = a.sub(*c);
            let v = x.sub(*c);
            let ang = u.cross(v).atan2(u.dot(v));
            if *sweep == 0.0 {
                0.0
            } else {
                ang / sweep
            }
        }
        Seg::Cubic { .. } => 0.5,
    }
}

// Append offset run `b` to one side's outline, joining it to the last piece
// at the centreline joint p: the inside of a turn trims both runs to where
// they cross (a run the crossing consumes is dropped, its neighbour left
// whole); the outside extends their tangents to a mitre (bevelled past the
// miter limit), bridging any arc to it with a straight piece.
fn join_into(out: &mut Vec<(Seg, bool)>, b: Seg, p: P, side: f64, h: f64) -> bool {
    let mut b = b;
    let ia = match out.len() {
        0 => {
            out.push((b, true));
            return true;
        }
        n => n - 1,
    };
    let a = out[ia].0.clone();
    let real_a = out[ia].1;
    let e = a.end();
    let s = b.start();
    let (da, db) = match (a.dir_end(), b.dir_start()) {
        (Some(x), Some(y)) => (x, y),
        _ => {
            if !e.near(s) {
                out.push((Seg::Line { a: e, b: s }, false));
            }
            out.push((b, true));
            return true;
        }
    };
    let cross = da.cross(db);
    let dot = da.dot(db);
    if cross.abs() < 1e-9 && dot > 0.0 {
        if !e.near(s) {
            out.push((Seg::Line { a: e, b: s }, false));
        }
        out.push((b, true));
        return true;
    }
    let right_turn = cross > 0.0;
    let outer = (side > 0.0) == right_turn;
    if outer {
        match line_x(e, da, s, db) {
            Some(m) if m.sub(p).len() <= MITER_LIMIT * h + 1e-9 => {
                if a.is_line() && real_a {
                    set_end(&mut out[ia].0, m);
                } else if !e.near(m) {
                    out.push((Seg::Line { a: e, b: m }, false));
                }
                if b.is_line() {
                    set_start(&mut b, m);
                } else if !m.near(s) {
                    out.push((Seg::Line { a: m, b: s }, false));
                }
            }
            _ => out.push((Seg::Line { a: e, b: s }, false)),
        }
        out.push((b, true));
        return true;
    }
    match cross_point(&a, &b, p) {
        Some(x) => {
            let ta = param_of(&a, x);
            let tb = param_of(&b, x);
            if tb >= 1.0 - 1e-9 {
                // the crossing eats this run: it never draws
                return false;
            }
            if real_a && ta <= 1e-9 {
                // the crossing eats the last run: drop it
                out.pop();
                match out.last() {
                    Some((g, _)) => {
                        let e2 = g.end();
                        if !e2.near(s) {
                            out.push((Seg::Line { a: e2, b: s }, false));
                        }
                    }
                    None => {}
                }
                out.push((b, true));
                return true;
            }
            if tb >= 1.0 - 1e-9 {
                // the crossing eats this run: it never draws
                return false;
            }
            set_end(&mut out[ia].0, x);
            set_start(&mut b, x);
            out.push((b, true));
            true
        }
        None => {
            out.push((Seg::Line { a: e, b: s }, false));
            out.push((b, true));
            true
        }
    }
}

// One side's offset outline of a run of centreline pieces.
fn join_side(cl: &[Seg], side: f64, h: f64, closed: bool) -> Vec<Seg> {
    let n = cl.len();
    let mut out: Vec<(Seg, bool)> = Vec::new();
    for k in 0..n {
        let p = if k == 0 { cl[0].start() } else { cl[k - 1].end() };
        join_into(&mut out, offset_seg(&cl[k], side, h), p, side, h);
    }
    if closed && out.len() > 1 {
        // the seam: join the last run back to the first
        let p = cl[n - 1].end();
        let last = out.len() - 1;
        let (a, b) = (out[last].0.clone(), out[0].0.clone());
        if let (Some(da), Some(db)) = (a.dir_end(), b.dir_start()) {
            let cross = da.cross(db);
            let dot = da.dot(db);
            let e = a.end();
            let s = b.start();
            if cross.abs() < 1e-9 && dot > 0.0 {
                if !e.near(s) {
                    out.push((Seg::Line { a: e, b: s }, false));
                }
            } else {
                let outer = (side > 0.0) == (cross > 0.0);
                if outer {
                    match line_x(e, da, s, db) {
                        Some(m) if m.sub(p).len() <= MITER_LIMIT * h + 1e-9 => {
                            if a.is_line() && out[last].1 {
                                set_end(&mut out[last].0, m);
                            } else {
                                out.push((Seg::Line { a: e, b: m }, false));
                            }
                            if b.is_line() {
                                set_start(&mut out[0].0, m);
                            } else {
                                out.push((Seg::Line { a: m, b: s }, false));
                            }
                        }
                        _ => out.push((Seg::Line { a: e, b: s }, false)),
                    }
                } else {
                    match cross_point(&a, &b, p) {
                        Some(x) => {
                            set_end(&mut out[last].0, x);
                            set_start(&mut out[0].0, x);
                        }
                        None => out.push((Seg::Line { a: e, b: s }, false)),
                    }
                }
            }
        }
    }
    out.into_iter().map(|(g, _)| g).collect()
}

fn mk_sub(start: P, segs: Vec<Seg>, closed: bool) -> Sub {
    let n = segs.len();
    Sub { start, segs, tags: vec![None; n], closed, circle: false }
}

// An open run of centreline pieces as one closed outline: the left face
// forward, the end cap, the right face back.
fn piece_outline(cl: &[Seg], h: f64) -> Sub {
    let left = join_side(cl, 1.0, h, false);
    let right = join_side(cl, -1.0, h, false);
    let mut segs = left.clone();
    let le = left.last().unwrap().end();
    let re = right.last().unwrap().end();
    segs.push(Seg::Line { a: le, b: re });
    for g in right.iter().rev() {
        segs.push(g.reversed());
    }
    segs.push(Seg::Line { a: right[0].start(), b: left[0].start() });
    mk_sub(left[0].start(), segs, true)
}

// A sub-run of a line between two stations (px along it).
fn sub_line(g: &Seg, s0: f64, s1: f64) -> Seg {
    match g {
        Seg::Line { a, b } => {
            let d = b.sub(*a).unit();
            Seg::Line { a: a.add(d.mul(s0)), b: a.add(d.mul(s1)) }
        }
        _ => g.clone(),
    }
}

// The centreline run from station (seg, off) to (seg, off), wrapping round a
// closed subpath.
fn extract(segs: &[Seg], from: (usize, f64), to: (usize, f64), closed: bool) -> Vec<Seg> {
    let n = segs.len();
    let mut out = Vec::new();
    let mut push = |g: Seg| {
        if g.length() > 1e-9 {
            out.push(g);
        }
    };
    let len = |k: usize| segs[k].length();
    if from.0 == to.0 && from.1 <= to.1 + 1e-12 {
        if segs[from.0].is_line() {
            push(sub_line(&segs[from.0], from.1, to.1));
        } else if from.1 < 1e-12 && to.1 >= len(from.0) - 1e-12 {
            push(segs[from.0].clone());
        }
        return out;
    }
    // the tail of the first run
    let first = &segs[from.0];
    if first.is_line() {
        push(sub_line(first, from.1, len(from.0)));
    } else if from.1 < 1e-12 {
        push(first.clone());
    }
    let mut k = from.0;
    loop {
        k += 1;
        if k >= n {
            if !closed {
                return out;
            }
            k = 0;
        }
        if k == to.0 {
            break;
        }
        push(segs[k].clone());
    }
    let last = &segs[to.0];
    if last.is_line() {
        push(sub_line(last, 0.0, to.1));
    } else if to.1 >= len(to.0) - 1e-12 {
        push(last.clone());
    }
    out
}

// The poché of a wall: its centreline thickened to t (px), cut at every
// opening's gap. `cuts`: (subpath, segment, from, to) in px along the run.
pub fn thicken(shape: &Shape, t: f64, cuts: &[(usize, usize, f64, f64)]) -> Shape {
    let h = t / 2.0;
    let mut subs = Vec::new();
    for (si, s) in shape.subs.iter().enumerate() {
        let mut segs = s.segs.clone();
        if s.closed && !s.end().near(s.start) {
            segs.push(Seg::Line { a: s.end(), b: s.start });
        }
        segs.retain(|g| g.length() > 1e-12);
        if segs.is_empty() {
            continue;
        }
        let mut mine: Vec<(usize, f64, f64)> =
            cuts.iter().filter(|c| c.0 == si && c.1 < segs.len() && c.3 >= c.2).map(|c| (c.1, c.2, c.3)).collect();
        mine.sort_by(|a, b| (a.0, a.1).partial_cmp(&(b.0, b.1)).unwrap_or(std::cmp::Ordering::Equal));
        if mine.is_empty() {
            if s.closed {
                let left = join_side(&segs, 1.0, h, true);
                let right = join_side(&segs, -1.0, h, true);
                subs.push(mk_sub(left[0].start(), left.clone(), true));
                let rs: Vec<Seg> = right.iter().rev().map(|g| g.reversed()).collect();
                subs.push(mk_sub(right.last().unwrap().end(), rs, true));
            } else {
                subs.push(piece_outline(&segs, h));
            }
            continue;
        }
        let n = segs.len();
        let mut pieces: Vec<Vec<Seg>> = Vec::new();
        if s.closed {
            let (j0, _, e0) = mine[0];
            let mut cur = (j0, e0);
            for c in mine.iter().skip(1) {
                pieces.push(extract(&segs, cur, (c.0, c.1), true));
                cur = (c.0, c.2);
            }
            pieces.push(extract(&segs, cur, (mine[0].0, mine[0].1), true));
        } else {
            let mut cur = (0usize, 0.0);
            for c in &mine {
                pieces.push(extract(&segs, cur, (c.0, c.1), false));
                cur = (c.0, c.2);
            }
            pieces.push(extract(&segs, cur, (n - 1, segs[n - 1].length()), false));
        }
        for p in pieces {
            if p.is_empty() {
                continue;
            }
            subs.push(piece_outline(&p, h));
        }
    }
    Shape { subs, points: shape.points.clone() }
}

// The laid-out outline of wall i: `shape` is its pen result in px.
pub fn outline(ctx: &Ctx, i: usize, shape: &Shape, k: f64) -> Shape {
    let t = wall_thickness(ctx, i) * k;
    let mut cuts = Vec::new();
    for &c in &ctx.nodes[i].children {
        if let Some(o) = ctx.sk.fp.openings.get(&c) {
            if let Some((si, gi)) = o.seg {
                cuts.push((si, gi, o.at * k, (o.at + o.width) * k));
            }
        }
    }
    thicken(shape, t, &cuts)
}

// ------------------------------------------------------------ measure

pub fn claims(ctx: &Ctx, i: usize) -> bool {
    let fp = &ctx.sk.fp;
    if ctx.sk.wrappers.contains_key(&i) {
        return false;
    }
    fp.parts.contains_key(&i) || fp.openings.contains_key(&i) || (fp.fixtures.contains_key(&i) && crate::drawing::in_drawing(ctx, i))
}

pub fn measure(ctx: &mut Ctx, i: usize) {
    if ctx.sk.fp.parts.contains_key(&i) {
        return;
    }
    if ctx.sk.fp.openings.contains_key(&i) {
        return measure_opening(ctx, i);
    }
    measure_fixture(ctx, i);
}

fn line_elem(a: P, b: P) -> String {
    format!("<line x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\"/>", f4(a.x), f4(a.y), f4(b.x), f4(b.y))
}

// Record a linework part: its element and box (in its owner's frame).
fn set_part(ctx: &mut Ctx, ch: usize, elem: String, bb: BBox, path: bool) {
    let n = &mut ctx.nodes[ch];
    n.w = bb.w();
    n.h = bb.h();
    n.geo_off = (-bb.cx(), -bb.cy());
    n.x = bb.cx();
    n.y = bb.cy();
    ctx.sk.fp.elems.insert(ch, elem);
    if path {
        ctx.sk.fp.as_path.insert(ch);
    }
}

fn set_line(ctx: &mut Ctx, ch: usize, a: P, b: P) {
    let mut bb = BBox::empty();
    bb.add(a.x, a.y);
    bb.add(b.x, b.y);
    set_part(ctx, ch, line_elem(a, b), bb, false);
}

fn set_path(ctx: &mut Ctx, ch: usize, d: String) {
    let bb = crate::geom::path_bbox(&d);
    let mut b2 = BBox::empty();
    if !bb.is_empty() {
        b2.add(bb.x0, bb.y0);
        b2.add(bb.x1, bb.y1);
    }
    set_part(ctx, ch, format!("<path d=\"{}\"/>", d), b2, true);
}

// The label children (text) of a fixture / opening, stacked on one side.
// `y0`: the offset of the stack's near edge (signed: the side).
fn place_labels(ctx: &mut Ctx, i: usize, near: f64, side: f64, centred: bool, rot: f64) {
    let texts: Vec<usize> = ctx.nodes[i].children.iter().copied().filter(|&c| ctx.nodes[c].prim == Prim::Text).collect();
    if texts.is_empty() {
        return;
    }
    for &t in &texts {
        crate::layout::measure_text(ctx, t, None);
    }
    let total: f64 = texts.iter().map(|&t| ctx.nodes[t].h).sum::<f64>() + LABEL_STACK_GAP * (texts.len() as f64 - 1.0);
    // the stack reads outward from the body
    let dir = if centred || side > 0.0 { 1.0 } else { -1.0 };
    let mut cur = if centred { -total / 2.0 } else { side * near };
    let cr = counter(rot);
    for &t in &texts {
        let th = ctx.nodes[t].h;
        let n = &mut ctx.nodes[t];
        n.x = 0.0;
        n.y = cur + dir * th / 2.0;
        n.geo_off = (0.0, 0.0);
        cur += dir * (th + LABEL_STACK_GAP);
        if cr != 0.0 {
            ctx.sk.fp.text_rot.insert(t, cr);
        }
    }
}

fn measure_opening(ctx: &mut Ctx, i: usize) {
    let o = ctx.sk.fp.openings[&i].clone();
    let wall = o.wall;
    let k = crate::drawing::ps(ctx, wall);
    let t = wall_thickness(ctx, wall) * k;
    let mut w = 0.0;
    let mut h = 0.0;
    let mut placed = false;
    let mut rotd = 0.0;
    if let (Some((si, gi)), Some(base)) = (o.seg, ctx.sk.base.get(&wall)) {
        if let Some(Seg::Line { a, b }) = base.subs.get(si).and_then(|s| s.segs.get(gi)) {
            let (a, b) = (a.mul(k), b.mul(k));
            let d = b.sub(a).unit();
            let c = a.add(d.mul((o.at + o.width / 2.0) * k));
            ctx.comp[i].translate = (clean(c.x), clean(c.y));
            rotd = clean(d.y.atan2(d.x).to_degrees());
            ctx.comp[i].rotate = rotd;
            w = o.width * k;
            h = t;
            placed = true;
        }
    }
    if !placed {
        ctx.comp[i].translate = (0.0, 0.0);
        ctx.comp[i].rotate = 0.0;
    }
    let sw = if ctx.comp[i].has_stroke { ctx.comp[i].stroke_width } else { 0.0 };
    {
        let n = &mut ctx.nodes[i];
        n.w = if placed { w - sw } else { 0.0 };
        n.h = if placed { h - sw } else { 0.0 };
        n.geo_off = (0.0, 0.0);
    }
    // the linework
    let kids = ctx.nodes[i].children.clone();
    let s = if o.right { 1.0 } else { -1.0 };
    let yf = s * h / 2.0;
    for ch in kids.iter().copied() {
        let part = match ctx.sk.fp.parts.get(&ch) {
            Some(p) => p.clone(),
            None => continue,
        };
        if !placed {
            continue;
        }
        match part {
            Part::Leaf(n) | Part::Swing(n) => {
                let double = o.symbol == "double";
                let (xh, len, end) = if double {
                    if n == 0 {
                        (-w / 2.0, w / 2.0, false)
                    } else {
                        (w / 2.0, w / 2.0, true)
                    }
                } else if o.end {
                    (w / 2.0, w, true)
                } else {
                    (-w / 2.0, w, false)
                };
                let tip = pt(xh, yf + s * len);
                if matches!(part, Part::Leaf(_)) {
                    set_line(ctx, ch, pt(xh, yf), tip);
                } else {
                    let far = if double { pt(0.0, yf) } else { pt(-xh, yf) };
                    let _ = end;
                    // the arc turns from the leaf toward the far jamb
                    let hinge = pt(xh, yf);
                    let sweep = if tip.sub(hinge).cross(far.sub(hinge)) > 0.0 { 1 } else { 0 };
                    let d = format!(
                        "M {} {} A {} {} 0 0 {} {} {}",
                        f4(tip.x),
                        f4(tip.y),
                        f4(len),
                        f4(len),
                        sweep,
                        f4(far.x),
                        f4(far.y)
                    );
                    set_path(ctx, ch, d);
                }
            }
            Part::Panel(n) => {
                if n == 0 {
                    set_line(ctx, ch, pt(-w / 2.0, -h / 2.0), pt(0.0, -h / 2.0));
                } else {
                    set_line(ctx, ch, pt(w / 2.0, h / 2.0), pt(0.0, h / 2.0));
                }
            }
            Part::Sill(n) => {
                let y = if n == 0 { -h / 6.0 } else { h / 6.0 };
                set_line(ctx, ch, pt(-w / 2.0, y), pt(w / 2.0, y));
            }
            _ => {}
        }
    }
    // the schedule tag: beside the gap, on the face the leaf never sweeps
    let side = if o.door && o.symbol != "sliding" { -s } else { 1.0 };
    if placed {
        place_labels(ctx, i, h / 2.0 + LABEL_GAP, side, false, rotd);
    } else {
        place_labels(ctx, i, 0.0, 1.0, true, 0.0);
    }
}

fn measure_fixture(ctx: &mut Ctx, i: usize) {
    let (family, symbol) = match ctx.sk.fp.fixtures.get(&i) {
        Some(f) => f.clone(),
        None => return,
    };
    let m = px_per_mm(ctx, i);
    let k = crate::drawing::ps(ctx, i);
    let _ = k;
    // the nominal body (mm) and its stretch
    // a body stretches to a larger box, never shrinks below true size
    let (w0, h0) = nominal(&family, &symbol);
    let wpx = ctx.comp[i].width.map(|w| w.max(w0 * m)).unwrap_or(w0 * m);
    let hpx = ctx.comp[i].height.map(|h| h.max(h0 * m)).unwrap_or(h0 * m);
    let sx = if w0 > 0.0 { wpx / w0 } else { m };
    let sy = if h0 > 0.0 { hpx / h0 } else { m };
    let d = symbol_path(&family, &symbol, sx, sy);
    {
        let n = &mut ctx.nodes[i];
        n.w = wpx;
        n.h = hpx;
        n.geo_off = (0.0, 0.0);
        n.geo = Some(crate::scene::Geo::Path(d));
    }
    if family == "stairs" {
        let steps: usize = symbol.parse().unwrap_or(2);
        let going = hpx / steps as f64;
        for ch in ctx.nodes[i].children.clone() {
            match ctx.sk.fp.parts.get(&ch).cloned() {
                Some(Part::Tread(t)) => {
                    let y = hpx / 2.0 - going * (t as f64 + 1.0);
                    set_line(ctx, ch, pt(-wpx / 2.0, y), pt(wpx / 2.0, y));
                }
                Some(Part::Arrow) => {
                    let hw = wpx * 11.0 / 90.0;
                    let hd = going * 0.44;
                    let top = -hpx / 2.0;
                    let d = format!(
                        "M 0 {} L 0 {} M {} {} L 0 {} L {} {}",
                        fmt3(hpx / 2.0 - going / 2.0),
                        fmt3(top),
                        fmt3(-hw),
                        fmt3(top + hd),
                        fmt3(top),
                        fmt3(hw),
                        fmt3(top + hd)
                    );
                    set_path(ctx, ch, d);
                }
                _ => {}
            }
        }
    }
    let rotd = ctx.comp[i].rotate;
    let centred = family == "appliance";
    place_labels(ctx, i, hpx / 2.0 + LABEL_GAP, 1.0, centred, rotd);
}

// ------------------------------------------------------------ symbols

// The nominal body of a fixture (mm): width × depth of its box.
fn nominal(family: &str, symbol: &str) -> (f64, f64) {
    match (family, symbol) {
        ("bed", "king") => (1800.0, 2000.0),
        ("bed", "double") => (1350.0, 1900.0),
        ("bed", "single") => (900.0, 2000.0),
        ("bed", _) => (1500.0, 2000.0),
        ("sofa", "two") => (1600.0, 900.0),
        ("sofa", "one") => (900.0, 900.0),
        ("sofa", "corner") => (2400.0, 2400.0),
        ("sofa", "stool") => (350.0, 350.0),
        ("sofa", _) => (2200.0, 900.0),
        ("dining", "four") => (1200.0, 1810.0),
        ("dining", "round") => (2010.0, 2010.0),
        ("dining", _) => (1800.0, 1910.0),
        ("bath", "shower") => (900.0, 900.0),
        ("bath", "toilet") => (700.0, 400.0),
        ("bath", "sink") => (500.0, 400.0),
        ("bath", "double-sink") => (800.0, 450.0),
        ("bath", _) => (1700.0, 750.0),
        ("appliance", _) => (600.0, 600.0),
        ("stairs", n) => (900.0, 250.0 * n.parse::<f64>().unwrap_or(2.0)),
        _ => (0.0, 0.0),
    }
}

struct PathB {
    d: Vec<String>,
    sx: f64,
    sy: f64,
}

impl PathB {
    fn x(&self, v: f64) -> String {
        fmt3(v * self.sx)
    }
    fn y(&self, v: f64) -> String {
        fmt3(v * self.sy)
    }
    fn p(&self, p: P) -> String {
        format!("{} {}", self.x(p.x), self.y(p.y))
    }
    fn rect(&mut self, x0: f64, y0: f64, x1: f64, y1: f64) {
        let s = format!(
            "M {} {} L {} {} L {} {} L {} {} Z",
            self.x(x0),
            self.y(y0),
            self.x(x1),
            self.y(y0),
            self.x(x1),
            self.y(y1),
            self.x(x0),
            self.y(y1)
        );
        self.d.push(s);
    }
    fn line(&mut self, pts: &[P]) {
        let mut s = format!("M {}", self.p(pts[0]));
        for q in &pts[1..] {
            s.push_str(&format!(" L {}", self.p(*q)));
        }
        self.d.push(s);
    }
    fn arc(&self, r: f64, large: bool, sweep: bool, to: P) -> String {
        format!(
            " A {} {} 0 {} {} {}",
            fmt3(r * self.sx),
            fmt3(r * self.sy),
            if large { 1 } else { 0 },
            if sweep { 1 } else { 0 },
            self.p(to)
        )
    }
    fn circle(&mut self, c: P, r: f64) {
        let w = pt(c.x - r, c.y);
        let e = pt(c.x + r, c.y);
        let s = format!("M {}{}{} Z", self.p(w), self.arc(r, true, true, e), self.arc(r, true, true, w));
        self.d.push(s);
    }
    // A polyline with every interior corner rounded to r (closed: every
    // corner, the path starting past the first one's fillet).
    fn filleted(&mut self, pts: &[P], r: f64, closed: bool) {
        let n = pts.len();
        // per vertex: (fillet start, fillet end, sweep) or None for an end
        let mut corners: Vec<Option<(P, P, bool)>> = vec![None; n];
        for k in 0..n {
            if !closed && (k == 0 || k == n - 1) {
                continue;
            }
            let prev = pts[(k + n - 1) % n];
            let next = pts[(k + 1) % n];
            let v = pts[k];
            let d1 = v.sub(prev).unit();
            let d2 = next.sub(v).unit();
            let turn = d1.cross(d2).atan2(d1.dot(d2));
            let tl = r * (turn.abs() / 2.0).tan();
            corners[k] = Some((v.sub(d1.mul(tl)), v.add(d2.mul(tl)), turn > 0.0));
        }
        let mut s = String::new();
        if closed {
            let (_, e0, _) = corners[0].unwrap();
            s.push_str(&format!("M {}", self.p(e0)));
            for k in 1..=n {
                let kk = k % n;
                let (a, b, sw) = corners[kk].unwrap();
                s.push_str(&format!(" L {}", self.p(a)));
                s.push_str(&self.arc(r, false, sw, b));
            }
            s.push_str(" Z");
        } else {
            s.push_str(&format!("M {}", self.p(pts[0])));
            for k in 1..n - 1 {
                let (a, b, sw) = corners[k].unwrap();
                s.push_str(&format!(" L {}", self.p(a)));
                s.push_str(&self.arc(r, false, sw, b));
            }
            s.push_str(&format!(" L {}", self.p(pts[n - 1])));
        }
        self.d.push(s);
    }
    fn rounded(&mut self, x0: f64, y0: f64, x1: f64, y1: f64, r: f64) {
        self.filleted(&[pt(x0, y0), pt(x1, y0), pt(x1, y1), pt(x0, y1)], r, true);
    }
}

fn symbol_path(family: &str, symbol: &str, sx: f64, sy: f64) -> String {
    let mut b = PathB { d: vec![], sx, sy };
    let (w, h) = nominal(family, symbol);
    let (hw, hh) = (w / 2.0, h / 2.0);
    match family {
        "bed" => {
            b.rect(-hw, -hh, hw, hh);
            if symbol == "single" {
                b.rect(-hw + 80.0, -hh + 80.0, hw - 80.0, -hh + 430.0);
            } else {
                b.rect(-hw + 80.0, -hh + 80.0, -40.0, -hh + 430.0);
                b.rect(40.0, -hh + 80.0, hw - 80.0, -hh + 430.0);
            }
            b.line(&[pt(-hw, -hh + 830.0), pt(hw, -hh + 830.0)]);
        }
        "sofa" => match symbol {
            "stool" => b.circle(pt(0.0, 0.0), 175.0),
            "corner" => {
                b.filleted(
                    &[
                        pt(-1200.0, -1200.0),
                        pt(1200.0, -1200.0),
                        pt(1200.0, -300.0),
                        pt(-300.0, -300.0),
                        pt(-300.0, 1200.0),
                        pt(-1200.0, 1200.0),
                    ],
                    80.0,
                    true,
                );
                b.filleted(
                    &[pt(-300.0, 1000.0), pt(-1000.0, 1000.0), pt(-1000.0, -1000.0), pt(1000.0, -1000.0), pt(1000.0, -300.0)],
                    80.0,
                    false,
                );
            }
            _ => {
                b.rounded(-hw, -hh, hw, hh, 80.0);
                b.filleted(
                    &[pt(-hw + 200.0, hh), pt(-hw + 200.0, -hh + 200.0), pt(hw - 200.0, -hh + 200.0), pt(hw - 200.0, hh)],
                    80.0,
                    false,
                );
            }
        },
        "dining" => {
            let chair = |b: &mut PathB, cx: f64, cy: f64| b.rounded(cx - 225.0, cy - 225.0, cx + 225.0, cy + 225.0, 50.0);
            match symbol {
                "round" => {
                    b.circle(pt(0.0, 0.0), 500.0);
                    chair(&mut b, 0.0, -780.0);
                    chair(&mut b, -780.0, 0.0);
                    chair(&mut b, 0.0, 780.0);
                    chair(&mut b, 780.0, 0.0);
                }
                "four" => {
                    b.rounded(-600.0, -400.0, 600.0, 400.0, 60.0);
                    for x in [-300.0, 300.0] {
                        chair(&mut b, x, -680.0);
                        chair(&mut b, x, 680.0);
                    }
                }
                _ => {
                    b.rounded(-900.0, -450.0, 900.0, 450.0, 60.0);
                    for x in [-600.0, 0.0, 600.0] {
                        chair(&mut b, x, -730.0);
                        chair(&mut b, x, 730.0);
                    }
                }
            }
        }
        "bath" => match symbol {
            "shower" => {
                b.rect(-450.0, -450.0, 450.0, 450.0);
                let s = format!(
                    "M {} L {} M {} L {}",
                    b.p(pt(-450.0, -450.0)),
                    b.p(pt(450.0, 450.0)),
                    b.p(pt(450.0, -450.0)),
                    b.p(pt(-450.0, 450.0))
                );
                b.d.push(s);
                b.circle(pt(0.0, 0.0), 70.0);
            }
            "toilet" => {
                let mut pts = vec![pt(-350.0, -200.0), pt(-170.0, -200.0), pt(-125.0, -165.0)];
                for kk in 0..=12 {
                    let th = if kk == 12 { std::f64::consts::PI } else { 2.0 * (kk as f64 / (12.0 - kk as f64)).atan() };
                    pts.push(pt(185.0 + 165.0 * th.sin(), -165.0 * th.cos()));
                }
                pts.extend([pt(-125.0, 165.0), pt(-170.0, 200.0), pt(-350.0, 200.0)]);
                b.filleted(&pts, 45.0, true);
            }
            "sink" => {
                b.rounded(-250.0, -200.0, 250.0, 200.0, 60.0);
                b.circle(pt(0.0, 0.0), 45.0);
            }
            "double-sink" => {
                b.rounded(-400.0, -225.0, 400.0, 225.0, 40.0);
                b.rounded(-340.0, -165.0, -30.0, 165.0, 50.0);
                b.circle(pt(-185.0, 0.0), 45.0);
                b.rounded(30.0, -165.0, 340.0, 165.0, 50.0);
                b.circle(pt(185.0, 0.0), 45.0);
            }
            _ => {
                b.rect(-850.0, -375.0, 850.0, 375.0);
                b.rounded(-760.0, -285.0, 760.0, 285.0, 150.0);
                b.circle(pt(570.0, 0.0), 45.0);
            }
        },
        "appliance" => {
            b.rect(-300.0, -300.0, 300.0, 300.0);
            match symbol {
                "fridge" => b.line(&[pt(-300.0, 180.0), pt(300.0, 180.0)]),
                "washer" => b.rect(-230.0, -230.0, 230.0, 230.0),
                "dishwasher" => {}
                _ => {
                    for (x, y) in [(-150.0, -150.0), (150.0, -150.0), (-150.0, 150.0), (150.0, 150.0)] {
                        b.circle(pt(x, y), 108.0);
                    }
                }
            }
        }
        "stairs" => b.rect(-hw, -hh, hw, hh),
        _ => {}
    }
    b.d.join(" ")
}

// ------------------------------------------------------------ dimensions

// A face of a wall run in the frame's datum: (a, b) of the offset line.
fn face_of(ctx: &Ctx, wall: usize, anchor: &str) -> Result<Option<(P, P)>, String> {
    let base = match ctx.sk.base.get(&wall) {
        Some(b) => b,
        None => return Ok(None),
    };
    let (name, face) = if let Some(n) = anchor.strip_suffix("-in") {
        (n, 1)
    } else if let Some(n) = anchor.strip_suffix("-out") {
        (n, -1)
    } else {
        (anchor, 0)
    };
    let mut hit: Option<(usize, usize)> = None;
    for (si, s) in base.subs.iter().enumerate() {
        for (gi, t) in s.tags.iter().enumerate() {
            if t.as_deref() == Some(name) {
                hit = Some((si, gi));
            }
        }
    }
    let (si, gi) = match hit {
        Some(x) => x,
        None => return Err(name.to_string()),
    };
    let k = crate::drawing::ps(ctx, wall);
    let s = &base.subs[si];
    let g = &s.segs[gi];
    let (a, b) = (g.start().mul(k), g.end().mul(k));
    let tr = ctx.comp[wall].translate;
    let off = pt(tr.0, tr.1);
    if face == 0 {
        return Ok(Some((a.add(off), b.add(off))));
    }
    let h = wall_thickness(ctx, wall) * k / 2.0;
    // `-in`: the loop's interior for a closed run, else the pen's left
    let mut in_left = true;
    if s.closed {
        let mut area = 0.0;
        let mut q = s.start;
        for g in &s.segs {
            let e = g.end();
            area += q.x * e.y - e.x * q.y;
            q = e;
        }
        area += q.x * s.start.y - s.start.x * q.y;
        in_left = area < 0.0;
    }
    let left = if face > 0 { in_left } else { !in_left };
    let n = b.sub(a).unit().left().mul(if left { h } else { -h });
    Ok(Some((a.add(n).add(off), b.add(n).add(off))))
}

fn anchor_suggest(name: &str, names: &[String]) -> String {
    let mut c: Vec<(usize, usize, &String)> = names
        .iter()
        .enumerate()
        .map(|(k, n)| (crate::util::levenshtein(name, n), k, n))
        .filter(|(d, _, _)| *d <= 2)
        .collect();
    c.sort_by_key(|(d, k, _)| (*d, *k));
    c.truncate(2);
    if c.is_empty() {
        return String::new();
    }
    let list: Vec<String> = c.iter().map(|(_, _, n)| format!("':{}'", n)).collect();
    format!("; did you mean {}?", list.join(", "))
}

// A dimension's end: a wall face (witness from its end nearest the
// dimension), a node's side (from its midpoint) or a point.
#[derive(Clone, Copy, Debug)]
enum Anch {
    Face(P, P),
    Edge(P, P),
    Point(P),
}

impl Anch {
    fn dir(&self) -> Option<P> {
        match self {
            Anch::Face(a, b) | Anch::Edge(a, b) => Some(b.sub(*a).unit()),
            Anch::Point(_) => None,
        }
    }
    // the point the dimension measures from: a face's or side's midpoint
    fn reference(&self) -> P {
        match self {
            Anch::Face(a, b) | Anch::Edge(a, b) => pt((a.x + b.x) / 2.0, (a.y + b.y) / 2.0),
            Anch::Point(p) => *p,
        }
    }
}

// The matrix from node i's group frame to the frame's datum.
fn frame_matrix(ctx: &Ctx, frame: usize, i: usize) -> [f64; 6] {
    let mut chain = Vec::new();
    let mut cur = Some(i);
    while let Some(k) = cur {
        if k == frame {
            break;
        }
        chain.push(k);
        cur = ctx.nodes[k].parent;
    }
    let mut m = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0];
    for &k in chain.iter().rev() {
        m = mat_mul(&m, &crate::render::group_matrix(ctx, k));
    }
    m
}

fn is_node_anchor(a: &str) -> bool {
    matches!(a, "center" | "top" | "bottom" | "left" | "right" | "top-left" | "top-right" | "bottom-left" | "bottom-right")
}

// A node's own anchor: its origin (bare), its side as an edge, its box's
// centre or a corner.
fn node_anchor(ctx: &Ctx, frame: usize, i: usize, anchor: Option<&str>) -> Option<Anch> {
    let n = &ctx.nodes[i];
    let m = frame_matrix(ctx, frame, i);
    let (cx, cy) = (-n.geo_off.0, -n.geo_off.1);
    let (hw, hh) = (n.w / 2.0, n.h / 2.0);
    let p = |x: f64, y: f64| apply(&m, pt(cx + x, cy + y));
    let anchor = match anchor {
        Some(a) => a,
        None => return Some(Anch::Point(apply(&m, pt(0.0, 0.0)))),
    };
    Some(match anchor {
        "center" => Anch::Point(p(0.0, 0.0)),
        "top" => Anch::Edge(p(-hw, -hh), p(hw, -hh)),
        "bottom" => Anch::Edge(p(-hw, hh), p(hw, hh)),
        "left" => Anch::Edge(p(-hw, -hh), p(-hw, hh)),
        "right" => Anch::Edge(p(hw, -hh), p(hw, hh)),
        "top-left" => Anch::Point(p(-hw, -hh)),
        "top-right" => Anch::Point(p(hw, -hh)),
        "bottom-left" => Anch::Point(p(-hw, hh)),
        "bottom-right" => Anch::Point(p(hw, hh)),
        _ => return None,
    })
}

// A node side's direction before layout: its rotation chain.
fn side_dir(ctx: &Ctx, i: usize, anchor: Option<&str>) -> Option<P> {
    let mut rot = 0.0;
    let mut cur = Some(i);
    while let Some(k) = cur {
        rot += ctx.comp[k].rotate;
        cur = ctx.nodes[k].parent;
    }
    match anchor {
        Some("top") | Some("bottom") => Some(rot_vec(pt(1.0, 0.0), rot)),
        Some("left") | Some("right") => Some(rot_vec(pt(0.0, 1.0), rot)),
        _ => None,
    }
}

fn dims_expand(ctx: &mut Ctx) -> Result<(), Diag> {
    'links: for li in 0..ctx.links.len() {
        if ctx.links[li].op != "(-)" {
            continue;
        }
        let frame = match plan_of(ctx, ctx.links[li].container) {
            Some(f) => f,
            None => continue,
        };
        let l = &ctx.links[li];
        // anchors
        let ends = [(l.from, l.from_anchor.clone(), l.from_span), (l.to, l.to_anchor.clone(), l.to_span)];
        let mut dirs: Vec<Option<P>> = Vec::new();
        for (n, anchor, sp) in ends.iter() {
            let a = anchor.as_deref();
            if !ctx.nodes[*n].is("wall") || a.map(is_node_anchor).unwrap_or(true) {
                if !a.map(is_node_anchor).unwrap_or(true) || ctx.nodes[*n].prim == Prim::Text {
                    continue 'links;
                }
                dirs.push(side_dir(ctx, *n, a));
                continue;
            }
            let anchor = anchor.clone().unwrap_or_default();
            match face_of(ctx, *n, &anchor) {
                Ok(Some(f)) => dirs.push(Some(f.1.sub(f.0).unit())),
                Ok(None) => continue 'links,
                Err(_) => {
                    let base = &ctx.sk.base[n];
                    let mut names: Vec<String> = Vec::new();
                    for t in base.tags() {
                        names.push(t.name.clone());
                        if matches!(t.kind, crate::sketch::TagKind::Seg(_)) {
                            names.push(format!("{}-in", t.name));
                            names.push(format!("{}-out", t.name));
                        }
                    }
                    let who = ctx.nodes[*n].id.clone().unwrap_or_default();
                    let msg = format!("no segment ':{}' on '{}'{}", anchor, who, anchor_suggest(&anchor, &names));
                    return Err(Diag::error("layout", &msg, *sp));
                }
            }
        }
        if let (Some(x), Some(y)) = (dirs[0], dirs[1]) {
            if x.cross(y).abs() > 1e-6 {
                let fs = ctx.links[li].from_span;
                let ts = ctx.links[li].to_span;
                let text = ctx.src.get(fs.start..ts.end).unwrap_or("").to_string();
                let msg = format!("'{}' — perpendicular faces have no shared normal; the angle between edges is '(<)'", text);
                return Err(Diag::error("layout", &msg, Span { start: fs.start, end: ts.end, ..fs }));
            }
        }
        // two points settle their axis once laid out; a face fixes it now
        if let Some(da) = dirs[0].or(dirs[1]) {
            let side = ctx.links[li].style.iter().rev().find(|d| d.name == "side").and_then(|d| ident_of(&d.value)).map(|s| s.to_string());
            if let Some(sd) = &side {
                if let Err(msg) = side_ok(axis_of(da), sd) {
                    return Err(Diag::error("layout", msg, ctx.links[li].span));
                }
            }
        }
        let span = ctx.links[li].span;
        let mut n = Node::new(Prim::Block, vec!["block".to_string()], span);
        n.parent = Some(frame);
        n.scope = ctx.nodes[frame].scope;
        let ni = ctx.nodes.len();
        ctx.nodes.push(n);
        // the frame's look, but no frame of its own
        let mut c = ctx.comp[frame].clone();
        c.layout = String::new();
        c.translate = (0.0, 0.0);
        c.rotate = 0.0;
        ctx.comp.push(c);
        // after the frame's flow children, before its pinned ones
        ctx.nodes[frame].children.push(ni);
        let di = ctx.sk.fp.dims.len();
        ctx.sk.fp.dims.push(Dim { link: li, frame, node: ni, ..Default::default() });
        ctx.sk.fp.parts.insert(ni, Part::Dim(di));
    }
    Ok(())
}

// A dimension's axis: measured along x, along y, or along its own slant.
#[derive(Clone, Copy, Debug, PartialEq)]
enum Axis {
    Horizontal,
    Vertical,
    Aligned,
}

// The axis a face (or side) running along unit `v` is measured on.
fn axis_of(v: P) -> Axis {
    if v.x.abs() < 1e-6 {
        Axis::Horizontal
    } else if v.y.abs() < 1e-6 {
        Axis::Vertical
    } else {
        Axis::Aligned
    }
}

// The axis of a span between two points.
fn axis_between(a: P, b: P) -> Axis {
    let u = b.sub(a).unit();
    if u.y.abs() < 1e-6 {
        Axis::Horizontal
    } else if u.x.abs() < 1e-6 {
        Axis::Vertical
    } else {
        Axis::Aligned
    }
}

fn side_ok(axis: Axis, side: &str) -> Result<(), &'static str> {
    match axis {
        Axis::Vertical if side != "left" && side != "right" => Err("a vertical dimension stacks on left or right"),
        Axis::Horizontal if side != "top" && side != "bottom" => Err("a horizontal dimension stacks on top or bottom"),
        Axis::Aligned if side != "left" && side != "right" => {
            Err("an aligned dimension sits left or right of its span — read along it, first anchor to second")
        }
        _ => Ok(()),
    }
}

fn round2(v: f64) -> String {
    let r = (v * 100.0).round() / 100.0;
    let s = format!("{:.2}", r);
    let s = s.trim_end_matches('0').trim_end_matches('.').to_string();
    if s == "-0" {
        "0".to_string()
    } else {
        s
    }
}

// A dimension already placed, as the later ones see it.
struct Placed {
    // an axis dimension's side; "" for an aligned one
    side: &'static str,
    // its line, arrows and text (datum box), and with the witness lines
    core: BBox,
    whole: BBox,
    // what a later dimension stands clear of: the band its line, arrows and
    // text sweep along its own axis, and its text's box
    band: Vec<P>,
    tbox: Vec<P>,
}

// Do two convex outlines overlap (touching never counts)?
fn overlap(a: &[P], b: &[P]) -> bool {
    if a.is_empty() || b.is_empty() {
        return false;
    }
    for poly in [a, b] {
        let n = poly.len();
        for k in 0..n {
            let e = poly[(k + 1) % n].sub(poly[k]);
            if e.len() == 0.0 {
                continue;
            }
            let ax = e.right().unit();
            let (a0, a1) = extent(a, ax);
            let (b0, b1) = extent(b, ax);
            if a1 <= b0 + 1e-9 || b1 <= a0 + 1e-9 {
                return false;
            }
        }
    }
    true
}

// What a chain's links share: an axis dimension's side, an aligned one's
// outward direction.
#[derive(Clone, Copy)]
enum Key {
    Side(&'static str),
    Dir(P),
}

fn bbox_of(pts: &[P]) -> BBox {
    let mut b = BBox::empty();
    for p in pts {
        b.add(p.x, p.y);
    }
    b
}

fn corners(b: &BBox) -> Vec<P> {
    vec![pt(b.x0, b.y0), pt(b.x1, b.y0), pt(b.x1, b.y1), pt(b.x0, b.y1)]
}

// The range of points along a unit direction.
fn extent(pts: &[P], v: P) -> (f64, f64) {
    let mut lo = f64::INFINITY;
    let mut hi = f64::NEG_INFINITY;
    for p in pts {
        let t = p.dot(v);
        lo = lo.min(t);
        hi = hi.max(t);
    }
    (lo, hi)
}

// The extent a plan's dimensions clear: every part's box, but a layout
// container (a room's stacked name and area) only through what it holds
// besides text.
fn plan_bbox(ctx: &Ctx, i: usize, m: &[f64; 6], bb: &mut BBox) {
    if crate::drawing::is_layout_container(ctx, i) {
        let mi = mat_mul(m, &crate::render::group_matrix(ctx, i));
        for &ch in &ctx.nodes[i].children {
            if ctx.nodes[ch].prim != Prim::Text {
                plan_bbox(ctx, ch, &mi, bb);
            }
        }
    } else {
        crate::drawing::deep_bbox(ctx, i, m, bb);
    }
}

// Lay out the dimensions of a floor plan frame (after its parts are
// measured, before the frame wraps them).
pub fn layout_dims(ctx: &mut Ctx, frame: usize) {
    let mine: Vec<usize> = (0..ctx.sk.fp.dims.len()).filter(|&d| ctx.sk.fp.dims[d].frame == frame).collect();
    if mine.is_empty() {
        return;
    }
    // the plan's content box (datum frame)
    let mut bb = BBox::empty();
    let ident = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0];
    for &ch in &ctx.nodes[frame].children.clone() {
        // the plan's own loose text (room names) never pushes a dimension out
        if ctx.comp[ch].pin.is_some() || ctx.sk.fp.parts.contains_key(&ch) || ctx.nodes[ch].prim == Prim::Text {
            continue;
        }
        plan_bbox(ctx, ch, &ident, &mut bb);
    }
    if bb.is_empty() {
        bb.add(0.0, 0.0);
    }
    // per side: its rows (position, runs with their whole boxes)
    let mut placed: Vec<Placed> = Vec::new();
    let mut tiers: HashMap<&'static str, Vec<(f64, Vec<(f64, f64, BBox)>)>> = HashMap::new();
    let mut last_stmt: Option<(usize, Key, f64)> = None;
    let mut last_row: Option<usize> = None;
    let ppu = crate::drawing::ps(ctx, frame);
    let obstacles = collect_obstacles(ctx, frame);
    let mut next_mask = 0usize;
    // every arrowhead and dimension text laid so far: no halo opens under one
    let mut all_marks: Vec<BBox> = Vec::new();
    for d in mine {
        let li = ctx.sk.fp.dims[d].link;
        let l = &ctx.links[li];
        let anch = |n: usize, a: Option<&str>| -> Option<Anch> {
            match a {
                Some(x) if ctx.nodes[n].is("wall") && !is_node_anchor(x) => {
                    face_of(ctx, n, x).ok().flatten().map(|(p, q)| Anch::Face(p, q))
                }
                _ => node_anchor(ctx, frame, n, a),
            }
        };
        let fa = anch(l.from, l.from_anchor.as_deref());
        let fb = anch(l.to, l.to_anchor.as_deref());
        let (fa, fb) = match (fa, fb) {
            (Some(a), Some(b)) => (a, b),
            _ => continue,
        };
        let side_s = l.style.iter().rev().find(|d| d.name == "side").and_then(|d| ident_of(&d.value)).map(|s| s.to_string());
        let axis = match fa.dir().or(fb.dir()) {
            Some(v) => axis_of(v),
            None => axis_between(fa.reference(), fb.reference()),
        };
        // two points only know their axis now
        if fa.dir().is_none() && fb.dir().is_none() {
            if let Some(sd) = &side_s {
                if let Err(msg) = side_ok(axis, sd) {
                    ctx.sk.fp.dims[d].err = Some(Diag::error("layout", msg, l.span));
                    continue;
                }
            }
        }
        let stmt = l.stmt_index;
        let label = l.label.clone();
        // the link's own text size and stroke weight (plain numbers only)
        let num_decl = |name: &str| -> Option<f64> {
            l.style.iter().rev().find(|d| d.name == name).and_then(|d| match single_term(&d.value) {
                Some(Term::Num(v, _, _)) => Some(*v),
                _ => None,
            })
        };
        let fs = num_decl("font-size").unwrap_or(DIM_TEXT);
        let sw = num_decl("stroke-width").unwrap_or(1.0);
        // the text's centre off the line, the arrowheads, the line's run
        // into them (inside) or past the tips (outside)
        let toff = 2.0 + fs / 2.0;
        let (alen, ahalf) = (ARROW_LEN * sw, ARROW_HALF * sw);
        let inset = 2.0 * sw;
        let over = alen + 2.0;
        // the band about the line (outward): beyond — arrows inward, the
        // text (or overrun) outward; between — the text inward, the overrun
        // outward. A dimension keeps its band 18 clear of what it stands off.
        let band_k = |beyond: bool| -> (f64, f64) {
            if beyond {
                (-ahalf, (toff + fs / 2.0).max(EXT_OVER).max(ahalf))
            } else {
                (-(toff + fs / 2.0).max(ahalf), EXT_OVER.max(ahalf))
            }
        };
        let laid = if axis == Axis::Aligned {
            // ---------------------------------------------- aligned
            let (ra, rb) = (fa.reference(), fb.reference());
            // measured along n, first anchor → second
            let n_ab = match fa.dir().or(fb.dir()) {
                Some(v) => {
                    let nrm = v.right();
                    if rb.sub(ra).dot(nrm) < 0.0 {
                        nrm.mul(-1.0)
                    } else {
                        nrm
                    }
                }
                None => rb.sub(ra).unit(),
            };
            // read upright
            let mut r = n_ab;
            if r.x < -1e-9 || (r.x.abs() <= 1e-9 && r.y > 0.0) {
                r = r.mul(-1.0);
            }
            let up = r.left();
            // the side: left / right of the reading first → second, else
            // away from the plan's centre
            let o = match side_s.as_deref() {
                Some("left") => n_ab.left(),
                Some("right") => n_ab.right(),
                _ => {
                    let mid = pt((ra.x + rb.x) / 2.0, (ra.y + rb.y) / 2.0);
                    let c = pt((bb.x0 + bb.x1) / 2.0, (bb.y0 + bb.y1) / 2.0);
                    if mid.sub(c).dot(up) < 0.0 {
                        up.mul(-1.0)
                    } else {
                        up
                    }
                }
            };
            let above = o.dot(up) > 0.0;
            let gap = DIM_CLEAR - band_k(above).0;
            let (ca, cb) = (ra.dot(r), rb.dot(r));
            let (lo, hi) = (ca.min(cb), ca.max(cb));
            let span = hi - lo;
            let text = match &label {
                Some(t) => t.clone(),
                None => round2(span / ppu),
            };
            let tw = crate::font::text_width(crate::font::Family::Sans, 400, fs, &text);
            let inside = span >= tw + 2.0 * alen + 6.0 - 1e-9;
            let text_in = span >= tw + 4.0 - 1e-9;
            let (mut olo, mut ohi) = if inside { (lo, hi) } else { (lo - over, hi + over) };
            // a text that does not fit reads past the far end of a
            // shallow dimension, past the near end of a steep one
            let shallow = r.y.abs() <= r.x.abs() + 1e-9;
            if !text_in {
                if shallow {
                    ohi = hi + over + 4.0 + tw;
                } else {
                    olo = lo - over - 4.0 - tw;
                }
            }
            // the line: a chain's links along one axis share it; else it
            // stands off its anchors, past every dimension across its run
            // the band's reach across the axis, about the line: arrows (or
            // the text) on the near side, the text (or the witness lines'
            // overrun) on the far side
            let (k0, k1) = band_k(above);
            let mut pos = None;
            if let Some((s0, Key::Dir(o0), p0)) = last_stmt {
                if s0 == stmt && (o0.x - o.x).abs() < 1e-9 && (o0.y - o.y).abs() < 1e-9 {
                    pos = Some(p0);
                }
            }
            let pos = match pos {
                Some(p) => p,
                None => {
                    // the band the line, arrows and text sweep across the
                    // axis (about the line), kept 18 clear of any other
                    // dimension: one in the way pushes it past that one
                    let mut p = ra.dot(o).max(rb.dot(o)) + gap;
                    for _ in 0..64 {
                        let (c0, c1) = (p + k0 - DIM_CLEAR, p + k1 + DIM_CLEAR);
                        let me = vec![r.mul(olo).add(o.mul(c0)), r.mul(ohi).add(o.mul(c0)), r.mul(ohi).add(o.mul(c1)), r.mul(olo).add(o.mul(c1))];
                        let mut moved = false;
                        for q in &placed {
                            for part in [&q.band, &q.tbox] {
                                if overlap(&me, part) {
                                    let to = extent(part, o).1 + gap;
                                    if to > p + 1e-9 {
                                        p = to;
                                        moved = true;
                                    }
                                }
                            }
                        }
                        if !moved {
                            break;
                        }
                    }
                    p
                }
            };
            last_stmt = Some((stmt, Key::Dir(o), pos));
            last_row = None;
            let tip = |f: P| r.mul(f.dot(r)).add(o.mul(pos));
            let (ta, tb) = (tip(ra), tip(rb));
            let (tlo, thi) = if ca <= cb { (ta, tb) } else { (tb, ta) };
            let (l0, l1, m0, m1);
            if inside {
                l0 = tlo.add(r.mul(inset));
                l1 = thi.sub(r.mul(inset));
                m0 = arrow(tlo, r.mul(-1.0), alen, ahalf);
                m1 = arrow(thi, r, alen, ahalf);
            } else {
                l0 = tlo.sub(r.mul(over));
                l1 = thi.add(r.mul(over));
                m0 = arrow(tlo, r, alen, ahalf);
                m1 = arrow(thi, r.mul(-1.0), alen, ahalf);
            }
            let text_at = if text_in {
                pt((tlo.x + thi.x) / 2.0, (tlo.y + thi.y) / 2.0).add(up.mul(toff))
            } else {
                let past = if shallow { thi.add(r.mul(over + 4.0 + tw / 2.0)) } else { tlo.sub(r.mul(over + 4.0 + tw / 2.0)) };
                past.add(up.mul(toff))
            };
            let rotd = r.y.atan2(r.x).to_degrees();
            // witness lines: from a face's end on the dimension's side, a
            // side's midpoint or a point, out past the line
            let mut exts = Vec::new();
            for (f, t) in [(fa, ta), (fb, tb)] {
                let nr = match f {
                    Anch::Face(a, b) => {
                        if a.dot(o) >= b.dot(o) {
                            a
                        } else {
                            b
                        }
                    }
                    Anch::Edge(a, b) => pt((a.x + b.x) / 2.0, (a.y + b.y) / 2.0),
                    Anch::Point(p) => p,
                };
                let s = if pos - nr.dot(o) >= 0.0 { o } else { o.mul(-1.0) };
                exts.push((nr.add(s.mul(EXT_GAP)), t.add(s.mul(EXT_OVER))));
            }
            // the text's box upright in the datum
            let (cs, sn) = (r.x.abs(), r.y.abs());
            let (hwt, hht) = (tw / 2.0 * cs + fs / 2.0 * sn, tw / 2.0 * sn + fs / 2.0 * cs);
            let tbox = vec![
                pt(text_at.x - hwt, text_at.y - hht),
                pt(text_at.x + hwt, text_at.y - hht),
                pt(text_at.x + hwt, text_at.y + hht),
                pt(text_at.x - hwt, text_at.y + hht),
            ];
            // the band along the dimension's own axis
            let mut band_pts = vec![l0, l1];
            band_pts.extend(m0.iter().copied());
            band_pts.extend(m1.iter().copied());
            for (sa, sc) in [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)] {
                band_pts.push(text_at.add(r.mul(sa * tw / 2.0)).add(up.mul(sc * fs / 2.0)));
            }
            let (a0, a1) = extent(&band_pts, r);
            let (c0, c1) = (pos + k0, pos + k1);
            let mut band: Vec<P> = Vec::new();
            for (a, c) in [(a0, c0), (a1, c0), (a1, c1), (a0, c1)] {
                band.push(r.mul(a).add(o.mul(c)));
            }
            let sb = bbox_of(&band);
            let mut all = vec![l0, l1];
            all.extend(m0.iter().copied());
            all.extend(m1.iter().copied());
            for (a, b) in &exts {
                all.push(*a);
                all.push(*b);
            }
            all.extend(tbox.iter().copied());
            let db = bbox_of(&all);
            placed.push(Placed { side: "", core: sb, whole: sb, band, tbox });
            (exts, (l0, l1), vec![m0, m1], text, text_at, rotd, db, true)
        } else {
            // ---------------------------------------------- along an axis
            let vertical = axis == Axis::Vertical;
            // two corners on one side of their boxes stack on that side
            let corner_side = |w: &str| -> bool {
                let (fa_, ta_) = (l.from_anchor.as_deref().unwrap_or(""), l.to_anchor.as_deref().unwrap_or(""));
                let is_corner = |a: &str| matches!(a, "top-left" | "top-right" | "bottom-left" | "bottom-right");
                is_corner(fa_) && is_corner(ta_) && fa_.split('-').any(|x| x == w) && ta_.split('-').any(|x| x == w)
            };
            let side: &'static str = match (vertical, side_s.as_deref()) {
                (true, Some("left")) => "left",
                (true, Some(_)) => "right",
                (true, None) => {
                    if corner_side("left") {
                        "left"
                    } else {
                        "right"
                    }
                }
                (false, Some("top")) => "top",
                (false, Some(_)) => "bottom",
                (false, None) => {
                    if corner_side("top") {
                        "top"
                    } else {
                        "bottom"
                    }
                }
            };
            // the measured coordinates, and where each witness line springs: a
            // face's end nearest the side, a side's midpoint, a point
            let coord = |f: Anch| match f {
                Anch::Face(a, b) | Anch::Edge(a, b) => {
                    let m = pt((a.x + b.x) / 2.0, (a.y + b.y) / 2.0);
                    if vertical {
                        m.y
                    } else {
                        m.x
                    }
                }
                Anch::Point(p) => {
                    if vertical {
                        p.y
                    } else {
                        p.x
                    }
                }
            };
            let near = |f: Anch| -> f64 {
                match f {
                    Anch::Face(a, b) => match side {
                        "right" => a.x.max(b.x),
                        "left" => a.x.min(b.x),
                        "top" => a.y.min(b.y),
                        _ => a.y.max(b.y),
                    },
                    Anch::Edge(a, b) => {
                        if vertical {
                            (a.x + b.x) / 2.0
                        } else {
                            (a.y + b.y) / 2.0
                        }
                    }
                    Anch::Point(p) => {
                        if vertical {
                            p.x
                        } else {
                            p.y
                        }
                    }
                }
            };
            let (c1, c2) = (coord(fa), coord(fb));
            let (lo, hi) = (c1.min(c2), c1.max(c2));
            let value = (hi - lo) / ppu;
            let text = match &label {
                Some(t) => t.clone(),
                None => round2(value),
            };
            let tw = crate::font::text_width(crate::font::Family::Sans, 400, fs, &text);
            let outward = if side == "right" || side == "bottom" { 1.0 } else { -1.0 };
            let between = side == "right" || side == "bottom";
            let edge = |bb: &BBox| -> f64 {
                match side {
                    "right" => bb.x1,
                    "left" => bb.x0,
                    "top" => bb.y0,
                    _ => bb.y1,
                }
            };
            // arrows and text inside the span, or outside it
            let span = hi - lo;
            let inside = span >= tw + 2.0 * alen + 6.0 - 1e-9;
            let text_in = span >= tw + 4.0 - 1e-9;
            // the run the dimension occupies along its line
            let (mut olo, mut ohi) = if inside { (lo, hi) } else { (lo - over, hi + over) };
            if !text_in {
                if vertical {
                    olo = lo - over - 4.0 - tw;
                } else {
                    ohi = hi + over + 4.0 + tw;
                }
            }
            // the line: a chain's links share their first link's line. Any
            // other dimension takes the first row of its side it fits in (no
            // overlap with that row's runs) — a new row clears the plan and the
            // rows it would cross — then steps past any other dimension whose
            // line, arrows or text stand across its run.
            let mut pos: Option<f64> = None;
            let mut chain_row = None;
            if let Some((s0, Key::Side(sd), p0)) = last_stmt {
                if s0 == stmt && sd == side {
                    pos = Some(p0);
                    chain_row = last_row;
                }
            }
            let mut row_of = None;
            if pos.is_none() {
                let gap = outward * (DIM_CLEAR - band_k(!between).0);
                let further = |a: f64, b: f64| if outward > 0.0 { a.max(b) } else { a.min(b) };
                let rows = tiers.entry(side).or_default();
                let mut base = None;
                for (k, (b, runs)) in rows.iter().enumerate() {
                    if runs.iter().all(|(a, z, _)| ohi <= *a + 1e-9 || olo >= *z - 1e-9) {
                        base = Some(*b);
                        row_of = Some(k);
                        break;
                    }
                }
                let base = match base {
                    Some(b) => b,
                    None => {
                        let mut e = edge(&bb);
                        for (_, runs) in rows.iter() {
                            for (a, z, whole) in runs {
                                if ohi > *a + 1e-9 && olo < *z - 1e-9 {
                                    e = further(e, edge(whole));
                                }
                            }
                        }
                        rows.push((e, vec![]));
                        row_of = Some(rows.len() - 1);
                        e
                    }
                };
                let mut e = base;
                for q in &placed {
                    if q.side == side {
                        continue;
                    }
                    // an aligned one: its band and its text, each
                    let parts = if q.side.is_empty() { vec![bbox_of(&q.band), bbox_of(&q.tbox)] } else { vec![q.core] };
                    for (k, c) in parts.iter().enumerate() {
                        let (plo, phi) = if vertical { (c.y0, c.y1) } else { (c.x0, c.x1) };
                        if phi > olo + 1e-9 && plo < ohi - 1e-9 {
                            e = further(e, edge(if q.side.is_empty() { &parts[k] } else { &q.whole }));
                        }
                    }
                }
                pos = Some(e + gap);
            }
            let p = pos.unwrap();
            last_stmt = Some((stmt, Key::Side(side), p));
            // ext lines
            let mut exts = Vec::new();
            for (f, c) in [(fa, c1), (fb, c2)] {
                let nr = near(f);
                if vertical {
                    exts.push((pt(nr + outward * EXT_GAP, c), pt(p + outward * EXT_OVER, c)));
                } else {
                    exts.push((pt(c, nr + outward * EXT_GAP), pt(c, p + outward * EXT_OVER)));
                }
            }
            let at = |v: f64| if vertical { pt(p, v) } else { pt(v, p) };
            let (l0, l1, m0, m1);
            if inside {
                l0 = at(lo + inset);
                l1 = at(hi - inset);
                let d0 = if vertical { pt(0.0, -1.0) } else { pt(-1.0, 0.0) };
                m0 = arrow(at(lo), d0, alen, ahalf);
                m1 = arrow(at(hi), d0.mul(-1.0), alen, ahalf);
            } else {
                l0 = at(lo - over);
                l1 = at(hi + over);
                let d0 = if vertical { pt(0.0, 1.0) } else { pt(1.0, 0.0) };
                m0 = arrow(at(lo), d0, alen, ahalf);
                m1 = arrow(at(hi), d0.mul(-1.0), alen, ahalf);
            }
            let mid = (lo + hi) / 2.0;
            let (text_at, rotd) = if vertical {
                let y = if text_in { mid } else { lo - over - 4.0 - tw / 2.0 };
                (pt(p - toff, y), -90.0)
            } else {
                let x = if text_in { mid } else { hi + over + 4.0 + tw / 2.0 };
                (pt(x, p - toff), 0.0)
            };
            // the dimension's core (line, arrows, text) and its whole box (with
            // the witness lines)
            let mut core = BBox::empty();
            core.add(l0.x, l0.y);
            core.add(l1.x, l1.y);
            for m in [&m0, &m1] {
                for q in m.iter() {
                    core.add(q.x, q.y);
                }
            }
            let (hwt, hht) = if vertical { (fs / 2.0, tw / 2.0) } else { (tw / 2.0, fs / 2.0) };
            core.add(text_at.x - hwt, text_at.y - hht);
            core.add(text_at.x + hwt, text_at.y + hht);
            let mut db = core;
            for (a, b) in &exts {
                db.add(a.x, a.y);
                db.add(b.x, b.y);
            }
            let mut band = core;
            for (_, b) in &exts {
                band.add(b.x, b.y);
            }
            let tb = corners(&BBox { x0: text_at.x - hwt, y0: text_at.y - hht, x1: text_at.x + hwt, y1: text_at.y + hht });
            placed.push(Placed { side, core, whole: db, band: corners(&band), tbox: tb });
            let row = row_of.or(chain_row);
            if let Some(k) = row {
                if let Some(rows) = tiers.get_mut(side) {
                    if let Some(r) = rows.get_mut(k) {
                        r.1.push((olo, ohi, db));
                    }
                }
            }
            last_row = row;
            (exts, (l0, l1), vec![m0, m1], text, text_at, rotd, db, false)
        };
        let (exts, line, marks, text, text_at, rotd, db, aligned) = laid;
        for m in &marks {
            all_marks.push(bbox_of(m));
        }
        // halos where a witness line (or an aligned dimension's own line)
        // crosses another outline — never under the dimension's arrows
        let mut halos = Vec::new();
        let mut mask_ids = Vec::new();
        for (a, b) in &exts {
            let hs = clear_marks(halo_gaps(&obstacles, *a, *b, true), *a, *b, &all_marks, sw / 2.0);
            if hs.is_empty() {
                mask_ids.push(None);
            } else {
                mask_ids.push(Some(next_mask));
                next_mask += 1;
            }
            halos.push(hs);
        }
        let mut line_halos = Vec::new();
        let mut line_mask = None;
        if aligned {
            line_halos = clear_marks(halo_gaps(&obstacles, line.0, line.1, false), line.0, line.1, &all_marks, sw / 2.0);
            if !line_halos.is_empty() {
                line_mask = Some(next_mask);
                next_mask += 1;
            }
        }
        let dm = &mut ctx.sk.fp.dims[d];
        dm.halos = halos;
        dm.mask_ids = mask_ids;
        dm.line_halos = line_halos;
        dm.line_mask = line_mask;
        dm.ext = exts;
        dm.line = line;
        dm.marks = marks;
        dm.text = text;
        dm.text_at = text_at;
        dm.text_rot = rotd;
        dm.fs = fs;
        dm.sw = sw;
        dm.laid = true;
        let ni = dm.node;
        let n = &mut ctx.nodes[ni];
        n.w = db.w();
        n.h = db.h();
        n.geo_off = (-db.cx(), -db.cy());
        n.x = db.cx();
        n.y = db.cy();
    }
}

// Halo gaps along a → b that reach under one of the dimension's own
// arrowheads (their box, half a pixel out) never open.
fn clear_marks(gaps: Vec<(f64, f64)>, a: P, b: P, boxes: &[BBox], grow: f64) -> Vec<(f64, f64)> {
    if gaps.is_empty() {
        return gaps;
    }
    let u = b.sub(a).unit();
    let mut spans: Vec<(f64, f64)> = Vec::new();
    for bx in boxes {
        let (x0, x1, y0, y1) = (bx.x0 - grow, bx.x1 + grow, bx.y0 - grow, bx.y1 + grow);
        // the line's run inside the box
        let mut t0 = f64::NEG_INFINITY;
        let mut t1 = f64::INFINITY;
        for (p, v, lo, hi) in [(a.x, u.x, x0, x1), (a.y, u.y, y0, y1)] {
            if v.abs() < 1e-12 {
                if p <= lo || p >= hi {
                    t0 = f64::INFINITY;
                }
                continue;
            }
            let (s0, s1) = ((lo - p) / v, (hi - p) / v);
            t0 = t0.max(s0.min(s1));
            t1 = t1.min(s0.max(s1));
        }
        if t0 < t1 {
            spans.push((t0, t1));
        }
    }
    gaps.into_iter().filter(|(g0, g1)| !spans.iter().any(|(s0, s1)| g0 < s1 && g1 > s0)).collect()
}

// ------------------------------------------------------------ halos

// The outline a witness line may cross (in the frame's datum), with the
// crossed node's stroke width.
#[derive(Clone, Debug)]
enum Ob {
    Seg(P, P, f64),
    // centre, radius, start point, signed sweep (radians)
    Arc(P, f64, P, f64, f64),
    // centre, rx, ry, rotation (deg), sw
    Ellipse(P, f64, f64, f64, f64),
    // a node's box: centre, half sizes, rotation (deg), sw
    Box(P, f64, f64, f64, f64),
}

fn mat_mul(m: &[f64; 6], n: &[f64; 6]) -> [f64; 6] {
    [
        m[0] * n[0] + m[2] * n[1],
        m[1] * n[0] + m[3] * n[1],
        m[0] * n[2] + m[2] * n[3],
        m[1] * n[2] + m[3] * n[3],
        m[0] * n[4] + m[2] * n[5] + m[4],
        m[1] * n[4] + m[3] * n[5] + m[5],
    ]
}

fn apply(m: &[f64; 6], p: P) -> P {
    pt(m[0] * p.x + m[2] * p.y + m[4], m[1] * p.x + m[3] * p.y + m[5])
}

// Every outline under a floor-plan frame a witness line can cross: walls'
// poché, node boxes, ovals, lines — never text or generated linework.
fn collect_obstacles(ctx: &Ctx, frame: usize) -> Vec<(Ob, usize)> {
    let mut out = Vec::new();
    let ident = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0];
    for &ch in &ctx.nodes[frame].children {
        if ctx.comp[ch].pin.is_some() {
            continue;
        }
        obstacles_of(ctx, ch, &ident, &mut out);
    }
    out
}

fn obstacles_of(ctx: &Ctx, i: usize, parent: &[f64; 6], out: &mut Vec<(Ob, usize)>) {
    let n = &ctx.nodes[i];
    if n.prim == Prim::Text || ctx.sk.fp.parts.contains_key(&i) || ctx.sk.chrome.contains_key(&i) || ctx.sk.planes.contains_key(&i) {
        return;
    }
    let m = mat_mul(parent, &crate::render::group_matrix(ctx, i));
    let sw = ctx.comp[i].stroke_width;
    if !ctx.sk.wrappers.contains_key(&i) {
        match n.prim {
            Prim::Sketch => {
                if let Some(l) = ctx.sk.laid.get(&i) {
                    for s in &l.shape.subs {
                        let mut segs = s.segs.clone();
                        if s.closed && !s.end().near(s.start) {
                            segs.push(Seg::Line { a: s.end(), b: s.start });
                        }
                        for g in &segs {
                            match g {
                                Seg::Line { a, b } => out.push((Ob::Seg(apply(&m, *a), apply(&m, *b), sw), i)),
                                Seg::Arc { a, c, r, sweep, .. } => {
                                    out.push((Ob::Arc(apply(&m, *c), *r, apply(&m, *a), *sweep, sw), i));
                                }
                                Seg::Cubic { a, b, .. } => out.push((Ob::Seg(apply(&m, *a), apply(&m, *b), sw), i)),
                            }
                        }
                    }
                }
            }
            Prim::Line | Prim::Poly => {
                if let Some(crate::scene::Geo::Points(pts)) = &n.geo {
                    let ps: Vec<P> = pts.iter().map(|&(x, y)| apply(&m, pt(x, y))).collect();
                    for w in ps.windows(2) {
                        out.push((Ob::Seg(w[0], w[1], sw), i));
                    }
                    if n.prim == Prim::Poly && ps.len() > 2 {
                        out.push((Ob::Seg(*ps.last().unwrap(), ps[0], sw), i));
                    }
                }
            }
            Prim::Oval => {
                let c = apply(&m, pt(-n.geo_off.0, -n.geo_off.1));
                let rot = m[1].atan2(m[0]).to_degrees();
                out.push((Ob::Ellipse(c, n.w / 2.0, n.h / 2.0, rot, sw), i));
            }
            _ => {
                // a layout container's box is its flowed content's, never an
                // outline of its own
                if n.w > 0.0 && n.h > 0.0 && !crate::drawing::is_layout_container(ctx, i) {
                    let c = apply(&m, pt(-n.geo_off.0, -n.geo_off.1));
                    let rot = clean(m[1].atan2(m[0]).to_degrees());
                    out.push((Ob::Box(c, n.w / 2.0, n.h / 2.0, rot, sw), i));
                }
            }
        }
    }
    for &ch in &n.children {
        obstacles_of(ctx, ch, &m, out);
    }
}

fn rot_vec(v: P, deg: f64) -> P {
    let (s, c) = deg.to_radians().sin_cos();
    pt(v.x * c - v.y * s, v.x * s + v.y * c)
}

// Halo gaps along the witness line a → b: (from, to) distances, merged.
fn halo_gaps(obs: &[(Ob, usize)], a: P, b: P, foot: bool) -> Vec<(f64, f64)> {
    let d = b.sub(a);
    let len = d.len();
    if len == 0.0 {
        return vec![];
    }
    let u = d.unit();
    // crossings (t, half, owner) and corner touches (t, half, owner)
    let mut hits3: Vec<(f64, f64, usize)> = Vec::new();
    let mut touches: Vec<(f64, f64, usize)> = Vec::new();
    let half_of = |tangent: P, sw: f64| -> Option<f64> {
        let tl = tangent.len();
        if tl == 0.0 {
            return None;
        }
        let s = (u.cross(tangent) / tl).abs();
        if s < 0.1 {
            return None;
        }
        Some((sw / 2.0 + 2.0) / s)
    };
    for (ob, owner) in obs {
        let owner = *owner;
        let mut add = |t: f64, tangent: P, sw: f64| {
            if t < -1e-9 || t > len + 1e-9 {
                return;
            }
            if let Some(half) = half_of(tangent, sw) {
                hits3.push((t, half, owner));
            }
        };
        let mut touch = |t: f64, tangent: P, sw: f64| {
            if t < -1e-9 || t > len + 1e-9 {
                return;
            }
            if let Some(half) = half_of(tangent, sw) {
                touches.push((t, half, owner));
            }
        };
        match ob {
            Ob::Box(c, hw, hh, rot, sw) => {
                // in the box's own frame
                let (sn, cs) = (-rot.to_radians()).sin_cos();
                let tr = |p: P| pt(p.x * cs - p.y * sn, p.x * sn + p.y * cs);
                let a0 = tr(a.sub(*c));
                let u0 = tr(u);
                // the two vertical sides, then the two horizontal ones; a
                // corner met across both its sides counts once, one met
                // running along a side only touches
                for x in [-*hw, *hw] {
                    if u0.x.abs() < 1e-12 {
                        continue;
                    }
                    let t = (x - a0.x) / u0.x;
                    let y = a0.y + u0.y * t;
                    if y > -*hh + 1e-9 && y < *hh - 1e-9 {
                        add(t, rot_vec(pt(0.0, 1.0), *rot), *sw);
                    } else if (y.abs() - *hh).abs() <= 1e-9 {
                        if u0.y.abs() >= 1e-12 {
                            // a corner opens as wide as its flatter side asks
                            let (tv, th) = (rot_vec(pt(0.0, 1.0), *rot), rot_vec(pt(1.0, 0.0), *rot));
                            let wide = match (half_of(tv, *sw), half_of(th, *sw)) {
                                (Some(a), Some(b)) if b > a => th,
                                (None, Some(_)) => th,
                                _ => tv,
                            };
                            add(t, wide, *sw);
                        } else {
                            touch(t, rot_vec(pt(0.0, 1.0), *rot), *sw);
                        }
                    }
                }
                for y in [-*hh, *hh] {
                    if u0.y.abs() < 1e-12 {
                        continue;
                    }
                    let t = (y - a0.y) / u0.y;
                    let x = a0.x + u0.x * t;
                    if x > -*hw + 1e-9 && x < *hw - 1e-9 {
                        add(t, rot_vec(pt(1.0, 0.0), *rot), *sw);
                    } else if (x.abs() - *hw).abs() <= 1e-9 && u0.x.abs() < 1e-12 {
                        touch(t, rot_vec(pt(1.0, 0.0), *rot), *sw);
                    }
                }
            }
            Ob::Seg(p, q, sw) => {
                let lv = q.sub(*p).len();
                if lv == 0.0 {
                    continue;
                }
                let v = q.sub(*p).unit();
                let den = u.cross(v);
                if den.abs() < 1e-12 {
                    continue;
                }
                let w = p.sub(a);
                let t = w.cross(v) / den;
                let s = w.cross(u) / den;
                // a vertex met across counts once (from the run it starts);
                // one where the line runs along the outline only touches
                if s <= 1e-9 || s >= lv - 1e-9 {
                    if s >= -1e-9 && s <= lv + 1e-9 {
                        let x = a.add(u.mul(t));
                        let along = obs.iter().any(|(o2, w2)| {
                            *w2 == owner
                                && match o2 {
                                    Ob::Seg(p2, q2, _) => {
                                        let v2 = q2.sub(*p2);
                                        v2.len() > 0.0
                                            && u.cross(v2.unit()).abs() < 1e-12
                                            && u.cross(p2.sub(a)).abs() < 1e-7
                                            && (p2.sub(x).len() < 1e-6 || q2.sub(x).len() < 1e-6)
                                    }
                                    _ => false,
                                }
                        });
                        if along {
                            touch(t, v, *sw);
                        } else if s <= 1e-9 {
                            // as wide as the flatter of the vertex's two runs
                            let prev = obs.iter().find_map(|(o2, w2)| match o2 {
                                Ob::Seg(p2, q2, _) if *w2 == owner && q2.sub(x).len() < 1e-6 && q2.sub(*p2).len() > 0.0 => Some(q2.sub(*p2).unit()),
                                _ => None,
                            });
                            let wide = match prev {
                                Some(pv) => match (half_of(v, *sw), half_of(pv, *sw)) {
                                    (Some(a), Some(b)) if b > a => pv,
                                    (None, Some(_)) => pv,
                                    _ => v,
                                },
                                None => v,
                            };
                            add(t, wide, *sw);
                        } else {
                            // the vertex's own run starts here unless this
                            // outline's run ends free
                            let next = obs.iter().any(|(o2, w2)| {
                                *w2 == owner
                                    && match o2 {
                                        Ob::Seg(p2, q2, _) => p2.sub(x).len() < 1e-6 && q2.sub(*p2).len() > 0.0 && u.cross(q2.sub(*p2).unit()).abs() >= 1e-12,
                                        _ => false,
                                    }
                            });
                            if !next {
                                add(t, v, *sw);
                            }
                        }
                    }
                    continue;
                }
                add(t, v, *sw);
            }
            Ob::Arc(c, r, start, sweep, sw) => {
                let f = a.sub(*c);
                let bb = f.dot(u);
                let disc = bb * bb - (f.dot(f) - r * r);
                if disc < 0.0 {
                    continue;
                }
                let sq = disc.sqrt();
                for t in [-bb - sq, -bb + sq] {
                    let x = a.add(u.mul(t));
                    // on the arc's sweep?
                    let v0 = start.sub(*c);
                    let v1 = x.sub(*c);
                    let mut ang = v0.cross(v1).atan2(v0.dot(v1));
                    if *sweep >= 0.0 {
                        if ang < -1e-9 {
                            ang += 2.0 * std::f64::consts::PI;
                        }
                        if ang > *sweep + 1e-9 {
                            continue;
                        }
                    } else {
                        if ang > 1e-9 {
                            ang -= 2.0 * std::f64::consts::PI;
                        }
                        if ang < *sweep - 1e-9 {
                            continue;
                        }
                    }
                    let tangent = v1.right();
                    add(t, tangent, *sw);
                }
            }
            Ob::Ellipse(c, rx, ry, rot, sw) => {
                if *rx <= 0.0 || *ry <= 0.0 {
                    continue;
                }
                // into the ellipse's own frame
                let (sn, cs) = (-rot.to_radians()).sin_cos();
                let tr = |p: P| pt(p.x * cs - p.y * sn, p.x * sn + p.y * cs);
                let a0 = tr(a.sub(*c));
                let u0 = tr(u);
                let (ax, ay) = (a0.x / rx, a0.y / ry);
                let (ux, uy) = (u0.x / rx, u0.y / ry);
                let qa = ux * ux + uy * uy;
                let qb = 2.0 * (ax * ux + ay * uy);
                let qc = ax * ax + ay * ay - 1.0;
                let disc = qb * qb - 4.0 * qa * qc;
                if disc < 0.0 || qa == 0.0 {
                    continue;
                }
                let sq = disc.sqrt();
                for t in [(-qb - sq) / (2.0 * qa), (-qb + sq) / (2.0 * qa)] {
                    let x0 = a0.add(u0.mul(t));
                    // the tangent of x²/rx² + y²/ry² = 1 at x0, back in the frame
                    let tl = pt(-x0.y / (ry * ry), x0.x / (rx * rx));
                    let (sn2, cs2) = rot.to_radians().sin_cos();
                    let tangent = pt(tl.x * cs2 - tl.y * sn2, tl.x * sn2 + tl.y * cs2);
                    add(t, tangent, *sw);
                }
            }
        }
    }
    // an outline only touched at a corner opens a gap only where another
    // outline crosses or touches the very same point
    // (crossing, gap from, gap to)
    let mut hits: Vec<(f64, f64, f64)> = hits3.iter().map(|(t, h, _)| (*t, t - h, t + h)).collect();
    for (t, half, owner) in &touches {
        let other = hits3.iter().any(|(c, _, o)| o != owner && (c - t).abs() < 1e-6)
            || touches.iter().any(|(c, _, o)| o != owner && (c - t).abs() < 1e-6);
        if other {
            hits.push((*t, t - half, t + half));
        }
    }
    // in crossing order, each gap runs on into the next it reaches
    hits.sort_by(|x, y| (x.0, x.1).partial_cmp(&(y.0, y.1)).unwrap_or(std::cmp::Ordering::Equal));
    let mut merged: Vec<(f64, f64)> = Vec::new();
    for (_, h0, h1) in hits {
        if let Some(last) = merged.last_mut() {
            if h0 <= last.1 + 1e-9 {
                last.1 = last.1.max(h1);
                continue;
            }
        }
        merged.push((h0, h1));
    }
    // a gap reaching back to a witness line's foot never opens: it leaves
    // its own wall there
    if foot {
        merged.retain(|h| h.0 > 2.0);
    }
    merged
}

// An arrowhead with its tip at p, pointing along d.
fn arrow(p: P, d: P, len: f64, half: f64) -> [P; 3] {
    let base = p.sub(d.mul(len));
    let r = d.right().mul(half);
    [p, base.add(r), base.sub(r)]
}

// ------------------------------------------------------------ render

pub fn skip_box(ctx: &Ctx, i: usize) -> bool {
    ctx.sk.fp.parts.contains_key(&i) && !ctx.sk.fp.elems.contains_key(&i) && !matches!(ctx.sk.fp.parts.get(&i), Some(Part::Dim(_)))
}

pub fn text_rotation(ctx: &Ctx, i: usize) -> Option<f64> {
    ctx.sk.fp.text_rot.get(&i).copied()
}

fn push_rule(out: &mut Out, slot: &str, rule: &str) {
    let r = (slot.to_string(), rule.to_string());
    if !out.extra_rules.contains(&r) {
        out.extra_rules.push(r);
    }
}

fn user_prim(ctx: &Ctx, prim: &str) -> bool {
    ctx.nodes.iter().enumerate().any(|(k, m)| m.is(prim) && !ctx.sk.fp.parts.contains_key(&k) && !ctx.sk.chrome.contains_key(&k))
}

// Classes of a node drawn as another primitive (the chain's own primitive
// class swapped for `lini-path`).
fn path_classes(ctx: &Ctx, i: usize, out: &mut Out) -> String {
    let n = &ctx.nodes[i];
    let mut cls = vec!["lini-node".to_string()];
    let last = n.chain.len().saturating_sub(1);
    for (k, t) in n.chain.iter().enumerate() {
        if k == last {
            break;
        }
        cls.push(format!("lini-{}", t));
        if !out.used_types.contains(t) {
            out.used_types.push(t.clone());
        }
    }
    cls.push("lini-path".to_string());
    for c in &n.classes {
        cls.push(format!("lini-style-{}", c));
        if !out.used_classes.contains(c) {
            out.used_classes.push(c.clone());
        }
    }
    if !user_prim(ctx, "path") {
        push_rule(out, "path", ".lini-path { stroke-dasharray: none; }");
    }
    cls.join(" ")
}

pub fn render_node(ctx: &Ctx, i: usize, ind_n: usize, s: &mut String, out: &mut Out) -> Option<Result<(), Diag>> {
    if let Some(p) = ctx.sk.fp.parts.get(&i) {
        if let Part::Dim(d) = p {
            return Some(render_dim(ctx, *d, ind_n, s, out));
        }
        return Some(render_part(ctx, i, ind_n, s, out));
    }
    if ctx.sk.fp.fixtures.contains_key(&i)
        && (ctx.nodes[i].geo.is_some() || ctx.sk.wrappers.contains_key(&i))
        && crate::drawing::in_drawing(ctx, i)
    {
        return Some(render_fixture(ctx, i, ind_n, s, out));
    }
    None
}

fn render_part(ctx: &Ctx, i: usize, ind_n: usize, s: &mut String, out: &mut Out) -> Result<(), Diag> {
    let pad = " ".repeat(ind_n);
    let elem = ctx.sk.fp.elems.get(&i);
    let cls = if ctx.sk.fp.as_path.contains(&i) && elem.is_some() {
        path_classes(ctx, i, out)
    } else {
        crate::render::node_classes(ctx, i, out)
    };
    s.push_str(&format!("{}<g class=\"{}\" transform=\"translate(0,0)\">\n", pad, cls));
    if let Some(e) = elem {
        s.push_str(&format!("{}  {}\n", pad, e));
    }
    s.push_str(&format!("{}</g>\n", pad));
    Ok(())
}

fn render_fixture(ctx: &Ctx, i: usize, ind_n: usize, s: &mut String, out: &mut Out) -> Result<(), Diag> {
    let n = &ctx.nodes[i];
    let c = &ctx.comp[i];
    let pad = " ".repeat(ind_n);
    let cls = path_classes(ctx, i, out);
    let style = crate::render::inline_style(ctx, i, out, false)?;
    let mut head = format!("{}<g class=\"{}\"", pad, cls);
    if let Some(id) = &n.id {
        head.push_str(&format!(" data-id=\"{}\"", xml_escape(id)));
    }
    if !style.is_empty() {
        head.push_str(&format!(" style=\"{}\"", xml_escape(&style)));
    }
    let tx = n.x + c.translate.0 + n.geo_off.0;
    let ty = n.y + c.translate.1 + n.geo_off.1;
    head.push_str(&format!(" transform=\"translate({},{})", f4(tx), f4(ty)));
    if c.rotate != 0.0 {
        head.push_str(&format!(" rotate({})", f4(c.rotate)));
    }
    head.push_str("\">\n");
    s.push_str(&head);
    if let Some(crate::scene::Geo::Path(d)) = &n.geo {
        s.push_str(&format!("{}  <path d=\"{}\"/>\n", pad, xml_escape(d)));
    }
    for ch in crate::render::paint_order(ctx, &n.children) {
        crate::render::render_node(ctx, ch, ind_n + 2, s, out)?;
    }
    s.push_str(&format!("{}</g>\n", pad));
    Ok(())
}

// A line, cut by its halos through a mask when it has any.
#[allow(clippy::too_many_arguments)]
fn masked_line(a: P, b: P, mask: Option<usize>, halos: &[(f64, f64)], frame_id: &Option<String>, pad: &str, sw: f64, s: &mut String, out: &mut Out) {
    let mi = match mask {
        Some(m) => m,
        None => {
            s.push_str(&format!("{}  {}\n", pad, line_elem(a, b)));
            return;
        }
    };
    let id = match frame_id {
        Some(f) => format!("lini-halo-{}-{}", f, mi),
        None => format!("lini-halo-{}", mi),
    };
    // the cut is the line's own width plus a pixel either side
    let cut = sw + 2.0;
    let (x0, y0) = (a.x.min(b.x) - cut / 2.0, a.y.min(b.y) - cut / 2.0);
    let (w, h) = ((a.x - b.x).abs() + cut, (a.y - b.y).abs() + cut);
    let mut m = format!(
        "<mask id=\"{}\" maskUnits=\"userSpaceOnUse\" x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\"><rect class=\"lini-cut-bg\" x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\"/>",
        xml_escape(&id),
        f4(x0),
        f4(y0),
        f4(w),
        f4(h),
        f4(x0),
        f4(y0),
        f4(w),
        f4(h)
    );
    let u = b.sub(a).unit();
    for (h0, h1) in halos {
        let p0 = a.add(u.mul(*h0));
        let p1 = a.add(u.mul(*h1));
        m.push_str(&format!(
            "<polyline class=\"lini-halo\" fill=\"none\" stroke-width=\"{}\" points=\"{},{} {},{}\"/>",
            f4(cut),
            f4(p0.x),
            f4(p0.y),
            f4(p1.x),
            f4(p1.y)
        ));
    }
    m.push_str("</mask>");
    s.push_str(&format!("{}  {}\n", pad, m));
    s.push_str(&format!(
        "{}  <line x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\" mask=\"url(#{})\"/>\n",
        pad,
        f4(a.x),
        f4(a.y),
        f4(b.x),
        f4(b.y),
        xml_escape(&id)
    ));
    push_rule(out, "dim-cut-bg", ".lini-cut-bg { fill: white; stroke: none; }");
    push_rule(out, "dim-halo", ".lini-halo { stroke: black; }");
}

fn render_dim(ctx: &Ctx, d: usize, ind_n: usize, s: &mut String, out: &mut Out) -> Result<(), Diag> {
    let dm = &ctx.sk.fp.dims[d];
    if let Some(e) = &dm.err {
        return Err(e.clone());
    }
    if !dm.laid {
        return Ok(());
    }
    let n = &ctx.nodes[dm.node];
    // the datum: the dimension node's own frame origin
    let ox = n.x + n.geo_off.0;
    let oy = n.y + n.geo_off.1;
    let pad = " ".repeat(ind_n);
    let l = &ctx.links[dm.link];
    // the link's own stroke rides inline
    let mut line_decls: Vec<String> = Vec::new();
    let mut fill_style = String::new();
    if let Some(dl) = l.style.iter().rev().find(|d| d.name == "stroke") {
        if let Some(t) = single_term(&dl.value) {
            let mut vars = Vec::new();
            if let Ok(col) = crate::style::color_css(t, &mut vars, dl.value.span) {
                for v in vars {
                    crate::style::use_var(&mut out.vars, &v);
                }
                line_decls.push(format!("stroke: {}", col));
                fill_style = format!(" style=\"fill: {}\"", xml_escape(&col));
            }
        }
    }
    if dm.sw != 1.0 {
        line_decls.push(format!("stroke-width: {}", f4(dm.sw)));
    }
    let line_style = if line_decls.is_empty() { String::new() } else { format!(" style=\"{}\"", xml_escape(&line_decls.join("; "))) };
    let tr = format!(" transform=\"translate({},{})\"", f4(ox), f4(oy));
    let frame_id = ctx.nodes[dm.frame].id.clone();
    for (k, (a, b)) in dm.ext.iter().enumerate() {
        s.push_str(&format!("{}<g class=\"lini-node lini-ext-line lini-line\"{}{}>\n", pad, line_style, tr));
        masked_line(*a, *b, dm.mask_ids.get(k).copied().flatten(), &dm.halos[k], &frame_id, &pad, dm.sw, s, out);
        s.push_str(&format!("{}</g>\n", pad));
    }
    s.push_str(&format!("{}<g class=\"lini-node lini-dim-line lini-line\"{}{}>\n", pad, line_style, tr));
    masked_line(dm.line.0, dm.line.1, dm.line_mask, &dm.line_halos, &frame_id, &pad, dm.sw, s, out);
    s.push_str(&format!("{}</g>\n", pad));
    for m in &dm.marks {
        s.push_str(&format!("{}<g class=\"lini-node lini-marker lini-marker-dim lini-poly\"{}{}>\n", pad, fill_style, tr));
        let pts: Vec<String> = m.iter().map(|q| format!("{},{}", f4(q.x), f4(q.y))).collect();
        s.push_str(&format!("{}  <polygon points=\"{}\"/>\n", pad, pts.join(" ")));
        s.push_str(&format!("{}</g>\n", pad));
    }
    let tx = ox + dm.text_at.x;
    let ty = oy + dm.text_at.y;
    let rot = if dm.text_rot != 0.0 { format!(" transform=\"rotate({} {} {})\"", f4(dm.text_rot), f4(tx), f4(ty)) } else { String::new() };
    let size = if dm.fs != DIM_TEXT { format!(" style=\"font-size: {}px\"", f4(dm.fs)) } else { String::new() };
    s.push_str(&format!(
        "{}<text class=\"lini-text lini-dim-text\" x=\"{}\" y=\"{}\" dy=\"0.358em\"{}{}>{}</text>\n",
        pad,
        f4(tx),
        f4(ty),
        size,
        rot,
        xml_escape(&dm.text)
    ));
    out.any_text = true;
    out.markers = true;
    if !user_prim(ctx, "line") {
        push_rule(out, "line", ".lini-line { stroke-dasharray: none; }");
    }
    push_rule(out, "dim-line", ".lini-dim-line { fill: none; stroke: var(--lini-stroke-dark); stroke-width: 1; }");
    push_rule(out, "ext-line", ".lini-ext-line { fill: none; stroke: var(--lini-stroke-light); stroke-width: 1; }");
    push_rule(out, "dim-text", ".lini-dim-text { font-size: 12px; font-weight: var(--lini-link-font-weight); }");
    push_rule(out, "marker-dim", ".lini-marker-dim { fill: var(--lini-stroke-dark); }");
    for v in ["stroke-dark", "stroke-light", "link-font-weight"] {
        crate::style::use_var(&mut out.vars, v);
    }
    if !user_prim(ctx, "poly") {
        push_rule(out, "poly", ".lini-poly { stroke-dasharray: none; }");
    }
    Ok(())
}
