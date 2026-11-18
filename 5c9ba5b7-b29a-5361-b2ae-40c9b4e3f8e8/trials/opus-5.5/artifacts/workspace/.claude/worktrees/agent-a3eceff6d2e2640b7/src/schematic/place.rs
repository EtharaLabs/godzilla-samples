// The `layout: schematic` scope. Its children split by role: anchors (3+-pin
// parts, components, plain blocks, anything with `cell:`) ride the scope's
// track grid, every part centre on the 20 px pin lattice; satellites (labels,
// 1–2-pin parts) are seated at the pins their wires touch; whatever has no
// placed end falls back to a flow row under the grid. The scope is laid out
// around its own centre, which sits on the lattice, and its box is the
// symmetric hull of what it holds.

use crate::compile::Ctx;
use crate::diag::Diag;
use crate::types::Prim;

pub const PITCH: f64 = 20.0;

thread_local! {
    // per scope: every body's lattice cells (scope-local)
    // per scope: every drawn box wires go around (device, box, the box's
    // stroke width), scope-local
    pub static BODIES: std::cell::RefCell<Vec<(usize, Vec<(usize, [f64; 4], f64)>)>> = const { std::cell::RefCell::new(Vec::new()) };
}

pub fn reset() {
    BODIES.with(|b| b.borrow_mut().clear());
}

// a box grown out to the lattice cells' edges (halfway between lines)
pub fn snap_cells(b: [f64; 4]) -> [f64; 4] {
    let lo = |v: f64| ((v - PITCH / 2.0) / PITCH + 1e-9).floor() * PITCH + PITCH / 2.0;
    let hi = |v: f64| ((v - PITCH / 2.0) / PITCH - 1e-9).ceil() * PITCH + PITCH / 2.0;
    [lo(b[0]), lo(b[1]), hi(b[2]), hi(b[3])]
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Role {
    Anchor,
    Satellite,
}

pub fn has(ctx: &Ctx, i: usize, t: &str) -> bool {
    ctx.nodes[i].chain.iter().any(|c| c == t)
}

pub fn is_part(ctx: &Ctx, i: usize) -> bool {
    ctx.nodes[i].chain.iter().any(|c| super::PART_TYPES.contains(&c.as_str()))
}

pub fn is_component(ctx: &Ctx, i: usize) -> bool {
    has(ctx, i, "component") && !is_part(ctx, i)
}

pub fn is_label(ctx: &Ctx, i: usize) -> bool {
    has(ctx, i, "label")
}

// the pins of a component (its `|pin|` descendants) or a part (its symbol's)
pub fn pins_of(ctx: &Ctx, i: usize) -> Vec<usize> {
    let mut out = Vec::new();
    let mut stack: Vec<usize> = ctx.nodes[i].children.iter().rev().cloned().collect();
    while let Some(k) = stack.pop() {
        if has(ctx, k, "pin") {
            out.push(k);
            continue;
        }
        if has(ctx, k, "row") || has(ctx, k, "column") {
            for &c in ctx.nodes[k].children.iter().rev() {
                stack.push(c);
            }
        }
    }
    out
}

pub fn pin_count(ctx: &Ctx, i: usize) -> usize {
    if is_component(ctx, i) {
        return pins_of(ctx, i).len();
    }
    if is_part(ctx, i) {
        let ty = ctx.nodes[i].chain.iter().find(|c| super::PART_TYPES.contains(&c.as_str())).cloned().unwrap_or_default();
        let sym = crate::render::prop_str(ctx, i, "symbol");
        return crate::desugar::part_pins(&ty, sym.as_deref()).len();
    }
    0
}

pub fn has_cell(ctx: &Ctx, i: usize) -> bool {
    ctx.nodes[i].props.contains_key("cell")
}

pub fn role(ctx: &Ctx, i: usize) -> Role {
    if has_cell(ctx, i) {
        return Role::Anchor;
    }
    if is_label(ctx, i) {
        return Role::Satellite;
    }
    if is_part(ctx, i) || is_component(ctx, i) {
        let k = pin_count(ctx, i);
        if (1..=2).contains(&k) {
            return Role::Satellite;
        }
    }
    Role::Anchor
}

// the name a diagnostic gives a node: its id, its reference, or its type
pub fn display_name(ctx: &Ctx, i: usize) -> String {
    if let Some(id) = &ctx.nodes[i].id {
        return id.clone();
    }
    for &c in &ctx.nodes[i].children {
        if has(ctx, c, "ref") {
            if let Some(&t) = ctx.nodes[c].children.first() {
                if let Some(s) = &ctx.nodes[t].text {
                    return s.clone();
                }
            }
        }
    }
    format!("|{}|", ctx.nodes[i].chain.first().cloned().unwrap_or_default())
}

pub fn round_lattice(v: f64) -> f64 {
    (v / PITCH).round() * PITCH
}

pub fn ceil_lattice(v: f64) -> f64 {
    (v / PITCH - 1e-9).ceil() * PITCH
}

// ---------------------------------------------------------------- extents

fn mul(m: &[f64; 6], n: &[f64; 6]) -> [f64; 6] {
    [
        m[0] * n[0] + m[2] * n[1],
        m[1] * n[0] + m[3] * n[1],
        m[0] * n[2] + m[2] * n[3],
        m[1] * n[2] + m[3] * n[3],
        m[0] * n[4] + m[2] * n[5] + m[4],
        m[1] * n[4] + m[3] * n[5] + m[5],
    ]
}

fn walk(ctx: &Ctx, i: usize, parent: &[f64; 6], b: &mut [f64; 4]) {
    let n = &ctx.nodes[i];
    let m = mul(parent, &crate::render::group_matrix(ctx, i));
    let (ow, oh) = crate::layout::outer(ctx, i);
    let (cx, cy) = (-n.geo_off.0, -n.geo_off.1);
    for (px, py) in [(-ow / 2.0, -oh / 2.0), (ow / 2.0, -oh / 2.0), (ow / 2.0, oh / 2.0), (-ow / 2.0, oh / 2.0)] {
        let (px, py) = (px + cx, py + cy);
        let x = m[0] * px + m[2] * py + m[4];
        let y = m[1] * px + m[3] * py + m[5];
        b[0] = b[0].min(x);
        b[1] = b[1].min(y);
        b[2] = b[2].max(x);
        b[3] = b[3].max(y);
    }
    if n.prim != Prim::Text {
        for &ch in &n.children {
            walk(ctx, ch, &m, b);
        }
    }
}

// what a wire goes around: a body, its stubs, its value and reference, a
// label's outline (pin rows, numbers and the invisible rows aside)
fn obstacle(ctx: &Ctx, i: usize, top: bool) -> bool {
    let n = &ctx.nodes[i];
    if n.prim == Prim::Text {
        return false;
    }
    if top {
        // a part is its drawing
        return !is_part(ctx, i);
    }
    ["pin-stub", "part-value", "ref", "sch-line", "sch-solid", "sch-tag-line"].iter().any(|t| has(ctx, i, t))
}

// every box a wire goes around of a node and its descendants, in its
// parent's frame (geometry alone: strokes aside)
pub fn drawn_boxes(ctx: &Ctx, i: usize) -> Vec<([f64; 4], f64)> {
    let mut out = Vec::new();
    fn go(ctx: &Ctx, i: usize, parent: &[f64; 6], out: &mut Vec<([f64; 4], f64)>, top: bool) {
        let n = &ctx.nodes[i];
        let m = mul(parent, &crate::render::group_matrix(ctx, i));
        let (mut ow, mut oh) = (n.w, n.h);
        // a turned run's name stands on end
        if n.prim == Prim::Text && n.parent.map_or(false, |p| has(ctx, p, "net-run-turned")) {
            std::mem::swap(&mut ow, &mut oh);
        }
        // a tag's outline: its label's box
        if ow == 0.0 && oh == 0.0 && has(ctx, i, "sch-tag-line") && n.props.contains_key("chrome") {
            if let Some(p) = n.parent {
                ow = ctx.nodes[p].w;
                oh = ctx.nodes[p].h;
            }
        }
        if obstacle(ctx, i, top) && (ow > 0.0 || oh > 0.0) {
            let (cx, cy) = (-n.geo_off.0, -n.geo_off.1);
            let mut b = [f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY];
            for (px, py) in [(-ow / 2.0, -oh / 2.0), (ow / 2.0, -oh / 2.0), (ow / 2.0, oh / 2.0), (-ow / 2.0, oh / 2.0)] {
                let (px, py) = (px + cx, py + cy);
                let x = m[0] * px + m[2] * py + m[4];
                let y = m[1] * px + m[3] * py + m[5];
                b[0] = b[0].min(x);
                b[1] = b[1].min(y);
                b[2] = b[2].max(x);
                b[3] = b[3].max(y);
            }
            let c = &ctx.comp[i];
            let mut sw = if c.has_stroke { c.stroke_width } else { 0.0 };
            if let Ok(v) = std::env::var("LINI_SCH_GROW") {
                // experiment: classes listed get no stroke allowance
                for t in v.split(',') {
                    if !t.is_empty() && (has(ctx, i, t) || (t == "top" && top)) {
                        sw = 0.0;
                    }
                }
            }
            // a reference keeps a line's width more above and below
            if has(ctx, i, "ref") {
                b[1] -= 1.5;
                b[3] += 1.5;
            }
            out.push((b, sw));
        }
        if n.prim != Prim::Text {
            for &ch in &n.children {
                go(ctx, ch, &m, out, false);
            }
        }
    }
    go(ctx, i, &[1.0, 0.0, 0.0, 1.0, 0.0, 0.0], &mut out, true);
    out
}

// a node's drawn extent around its own origin (its group's frame)
pub fn extent(ctx: &Ctx, i: usize) -> [f64; 4] {
    let mut b = [f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY];
    let n = &ctx.nodes[i];
    walk(ctx, i, &[1.0, 0.0, 0.0, 1.0, -n.x - n.geo_off.0, -n.y - n.geo_off.1], &mut b);
    b
}

// ------------------------------------------------------- component bodies

// A component's body centres on its pins: a column of an even count is
// padded by a slot to keep its middle on a pin, and the drawn body (with the
// labels pinned to it) shifts back by half a slot.
pub fn seat_component(ctx: &mut Ctx, i: usize) {
    let kids = ctx.nodes[i].children.clone();
    let mut sides = false;
    let mut ends = false;
    // (rows: real x extents), (columns: real y extents), relative to the node
    let mut xs: Vec<(f64, f64)> = Vec::new();
    let mut ys: Vec<(f64, f64)> = Vec::new();
    for &k in &kids {
        if ctx.comp[k].pin.is_some() {
            continue;
        }
        let (kx, ky) = (ctx.nodes[k].x, ctx.nodes[k].y);
        let cols: Vec<(usize, f64, f64)> = if has(ctx, k, "column") {
            vec![(k, 0.0, 0.0)]
        } else if has(ctx, k, "row") {
            let sub = ctx.nodes[k].children.clone();
            if sub.iter().any(|&s| has(ctx, s, "column")) {
                sub.iter().filter(|&&s| has(ctx, s, "column")).map(|&s| (s, kx, ky)).collect()
            } else {
                // a pin row (top / bottom) or a filler
                let pad = ctx.comp[k].padding;
                let w = ctx.nodes[k].w;
                if sub.iter().any(|&s| has(ctx, s, "pin") || has(ctx, s, "space")) {
                    ends = true;
                    xs.push((kx - w / 2.0 + pad[3], kx + w / 2.0 - pad[1]));
                } else {
                    ends = true;
                }
                continue;
            }
        } else {
            continue;
        };
        for (col, ox, oy) in cols {
            if !ctx.nodes[col].children.iter().any(|&s| has(ctx, s, "pin")) {
                continue;
            }
            sides = true;
            let (cx, cy) = (ox + ctx.nodes[col].x, oy + ctx.nodes[col].y);
            let _ = cx;
            let h = ctx.nodes[col].h;
            let pad = ctx.comp[col].padding;
            ys.push((cy - h / 2.0 + pad[0], cy + h / 2.0 - pad[2]));
        }
    }
    let mut dx = 0.0;
    let mut dy = 0.0;
    if !ends && !ys.is_empty() {
        let lo = ys.iter().map(|v| v.0).fold(f64::INFINITY, f64::min);
        let hi = ys.iter().map(|v| v.1).fold(f64::NEG_INFINITY, f64::max);
        dy = (lo + hi) / 2.0;
    }
    if !sides && !xs.is_empty() {
        let lo = xs.iter().map(|v| v.0).fold(f64::INFINITY, f64::min);
        let hi = xs.iter().map(|v| v.1).fold(f64::NEG_INFINITY, f64::max);
        dx = (lo + hi) / 2.0;
    }
    if dx == 0.0 && dy == 0.0 {
        return;
    }
    // the box centre moves to (dx, dy) from the origin
    ctx.nodes[i].geo_off = (-dx, -dy);
    for &k in &kids {
        if ctx.comp[k].pin.is_some() {
            ctx.nodes[k].x += dx;
            ctx.nodes[k].y += dy;
        }
    }
}

// a flag label's outline: its box inset by half the line, the pointed
// ends as deep as half the height
fn tag_chrome(ctx: &mut Ctx, label: usize) {
    for k in ctx.nodes[label].children.clone() {
        let shape = match ctx.nodes[k].props.get("chrome") {
            Some(v) => {
                let words: Vec<String> = v
                    .groups
                    .iter()
                    .flatten()
                    .filter_map(|t| match t {
                        crate::ast::Term::Ident(s, _) => Some(s.clone()),
                        _ => None,
                    })
                    .collect();
                if words.first().map(|s| s.as_str()) != Some("tag") {
                    continue;
                }
                words.get(1).cloned().unwrap_or_default()
            }
            None => continue,
        };
        let sw = ctx.comp[k].stroke_width;
        let hw = ctx.nodes[label].w / 2.0 - sw / 2.0;
        let hh = ctx.nodes[label].h / 2.0 - sw / 2.0;
        let t = hh;
        let f = crate::sketch::fmt3;
        let d = match shape.as_str() {
            "left" => format!(
                "M {} {} L {} {} L {} {} L {} {} L {} {} Z",
                f(-hw + t), f(-hh), f(hw), f(-hh), f(hw), f(hh), f(-hw + t), f(hh), f(-hw), f(0.0)
            ),
            "both" => format!(
                "M {} {} L {} {} L {} {} L {} {} L {} {} L {} {} Z",
                f(-hw + t), f(-hh), f(hw - t), f(-hh), f(hw), f(0.0), f(hw - t), f(hh), f(-hw + t), f(hh), f(-hw), f(0.0)
            ),
            _ => format!(
                "M {} {} L {} {} L {} {} L {} {} L {} {} Z",
                f(-hw), f(-hh), f(hw - t), f(-hh), f(hw), f(0.0), f(hw - t), f(hh), f(-hw), f(hh)
            ),
        };
        ctx.nodes[k].geo = Some(crate::scene::Geo::Path(d));
    }
}

// a part stood on end reads its value and reference beside it, flush left
fn side_labels(ctx: &mut Ctx, i: usize) {
    let (rot, _) = super::net::pose_of(ctx, i);
    if rot != 90 && rot != 270 {
        return;
    }
    for k in ctx.nodes[i].children.clone() {
        if (has(ctx, k, "part-value") || has(ctx, k, "ref")) && ctx.comp[k].pin.as_deref() == Some("center") {
            let (w, _) = crate::layout::outer(ctx, k);
            ctx.nodes[k].x += w / 2.0;
        }
    }
}

// a part in a pin's row stacks its reference and value on one side, away
// from the side's other pins (-1 above, +1 below)
fn stack_labels(ctx: &mut Ctx, i: usize, stack: i8) {
    if stack == 0 || !is_part(ctx, i) {
        return;
    }
    let (rot, _) = super::net::pose_of(ctx, i);
    if rot == 90 || rot == 270 {
        return;
    }
    let h = ctx.nodes[i].h;
    let mut val = None;
    let mut rf = None;
    for k in ctx.nodes[i].children.clone() {
        if has(ctx, k, "part-value") {
            val = Some(k);
        } else if has(ctx, k, "ref") {
            rf = Some(k);
        }
    }
    let edge = if stack < 0 { -h / 2.0 } else { h / 2.0 };
    let s = stack as f64;
    // the nearer label sits where a pinned label would (20 off the body),
    // the other one stacked 16 further out
    let (near, far) = if stack < 0 { (val, rf) } else { (rf, val) };
    let mut next = None;
    // (a label's own `translate` rides on top of its place)
    if let Some(n) = near {
        let nh = crate::layout::outer(ctx, n).1;
        let at = edge + s * (20.0 - nh / 2.0);
        ctx.nodes[n].y = at - ctx.comp[n].translate.1;
        next = Some(at + s * 16.0);
    }
    if let Some(fk) = far {
        let fh = crate::layout::outer(ctx, fk).1;
        let at = next.unwrap_or(edge + s * (20.0 - fh / 2.0));
        ctx.nodes[fk].y = at - ctx.comp[fk].translate.1;
    }
}

// a part stood on end left of its anchor reads its labels on its far side,
// flush right
fn flip_side_labels(ctx: &mut Ctx, i: usize) {
    if !is_part(ctx, i) {
        return;
    }
    let (rot, _) = super::net::pose_of(ctx, i);
    if rot != 90 && rot != 270 {
        return;
    }
    for k in ctx.nodes[i].children.clone() {
        if (has(ctx, k, "part-value") || has(ctx, k, "ref")) && ctx.comp[k].pin.as_deref() == Some("center") {
            // mirror the place across the part's axis
            let t = ctx.comp[k].translate.0;
            let at = ctx.nodes[k].x + t;
            ctx.nodes[k].x = -at - t;
        }
    }
}

// a wired run carries its name over the trace; a turned run beside it,
// on its lane's far side
pub fn raise_run(ctx: &mut Ctx, i: usize, side: Option<super::net::Dir>) {
    if has(ctx, i, "net-run-turned") {
        let w = ctx.nodes[i].w;
        let gap = ctx.comp[i].gap.0;
        let s = if side == Some(super::net::Dir::L) { -1.0 } else { 1.0 };
        for k in ctx.nodes[i].children.clone() {
            if ctx.nodes[k].prim == crate::types::Prim::Text {
                ctx.nodes[k].x = s * (w / 2.0 + gap);
                ctx.nodes[k].y = 0.0;
            }
        }
        return;
    }
    if !has(ctx, i, "net-run") {
        return;
    }
    let h = ctx.nodes[i].h;
    let gap = ctx.comp[i].gap.0;
    for k in ctx.nodes[i].children.clone() {
        if ctx.nodes[k].prim == crate::types::Prim::Text {
            ctx.nodes[k].y = -(h / 2.0 + gap);
        }
    }
}

// a turned run stands its name on end: the box the name would take lying
// down, turned
fn turn_run(ctx: &mut Ctx, i: usize) {
    if !has(ctx, i, "net-run-turned") {
        return;
    }
    let t = match ctx.nodes[i].children.iter().cloned().find(|&k| ctx.nodes[k].prim == crate::types::Prim::Text) {
        Some(t) => t,
        None => return,
    };
    let (tw, th) = (ctx.nodes[t].w, ctx.nodes[t].h);
    let c = &ctx.comp[i];
    let pad = c.padding;
    let min_h = c.height.unwrap_or(0.0);
    ctx.nodes[i].w = th + pad[1] + pad[3];
    ctx.nodes[i].h = (tw + pad[0] + pad[2]).max(min_h);
}

fn seat_all(ctx: &mut Ctx, i: usize) {
    if is_component(ctx, i) {
        seat_component(ctx, i);
    }
    if is_part(ctx, i) {
        side_labels(ctx, i);
    }
    if is_label(ctx, i) {
        tag_chrome(ctx, i);
        turn_run(ctx, i);
    }
    // a nested scope seats its own
    if ctx.comp[i].layout == "schematic" {
        return;
    }
    for ch in ctx.nodes[i].children.clone() {
        seat_all(ctx, ch);
    }
}

// --------------------------------------------------------------- the scope

pub fn measure(ctx: &mut Ctx, i: usize, _avail: Option<f64>) {
    let c = ctx.comp[i].clone();
    let pad = c.padding;
    let children = ctx.nodes[i].children.clone();
    let mut flow = Vec::new();
    let mut pinned = Vec::new();
    for &ch in &children {
        if ctx.comp[ch].pin.is_some() {
            pinned.push(ch);
        } else {
            flow.push(ch);
        }
    }
    for &ch in &children {
        crate::layout::measure(ctx, ch, None);
    }
    for &ch in &flow {
        seat_all(ctx, ch);
    }
    let (row_gap, col_gap) = c.gap;
    // roles
    let mut anchors = Vec::new();
    let mut sats = Vec::new();
    for &ch in &flow {
        match role(ctx, ch) {
            Role::Anchor => anchors.push(ch),
            Role::Satellite => sats.push(ch),
        }
    }
    // satellites seated off the anchors' pins, anchor by anchor
    let wires = super::net::wires(ctx, i);
    let mut clusters: Vec<(usize, Vec<super::seat::Seat>)> = Vec::new();
    let mut seated: std::collections::HashSet<usize> = Default::default();
    // the anchors' grid rows (an uncelled anchor rides the first)
    let row_of = |ctx: &Ctx, a: usize| -> usize {
        ctx.nodes[a]
            .props
            .get("cell")
            .map(|v| crate::style::value_nums(&ctx.sheet.env, v))
            .filter(|v| v.len() >= 2)
            .map(|v| v[1].max(1.0) as usize)
            .unwrap_or(1)
    };
    let mut seaters: Vec<super::seat::Seater> = Vec::new();
    let mut straights: Vec<Vec<super::seat::Straight>> = Vec::new();
    let mut turns: Vec<Vec<super::seat::Turn>> = Vec::new();
    // bridges across a grid gap stand between their anchors, seated with the
    // grid
    let bridges: Vec<Bridge> = find_bridges(ctx, &anchors, &wires).into_iter().filter(|b| bridge_spans(ctx, &anchors, b)).collect();
    for b in &bridges {
        for &(d, _) in &b.parts {
            seated.insert(d);
        }
    }
    for &a in &anchors {
        let mut st = super::seat::Seater::new(ctx, &wires, col_gap);
        for &k in &seated {
            st.placed.insert(k, (f64::NAN, f64::NAN));
        }
        let aext = extent(ctx, a);
        // first hops off this anchor's pins: (pin node, pin term, far term)
        let mut hops: Vec<(usize, super::net::Term, super::net::Term)> = Vec::new();
        for w in &wires {
            for (p, q) in [(&w.a, &w.b), (&w.b, &w.a)] {
                if p.dev == a
                    && q.dev != a
                    && matches!(p.kind, super::net::Kind::Pin | super::net::Kind::Station)
                    && role(ctx, q.dev) == Role::Satellite
                {
                    hops.push((p.node, p.clone(), q.clone()));
                }
            }
        }
        // every wired pin of the anchor
        let mut wired: Vec<super::net::Term> = Vec::new();
        for w in &wires {
            for t in [&w.a, &w.b] {
                if t.dev == a && matches!(t.kind, super::net::Kind::Pin | super::net::Kind::Station) && !wired.iter().any(|x| x.node == t.node) {
                    wired.push(t.clone());
                }
            }
        }
        let (sv, tv) = st.seat_first(aext, &hops, &wired);
        for s in &sv {
            for e in &s.els {
                seated.insert(e.0);
            }
        }
        for t in &tv {
            seated.insert(t.2.dev);
        }
        seaters.push(st);
        straights.push(sv);
        turns.push(tv);
    }
    // the first elements standing in their pins' rows align: up and down
    // across the anchors of a grid row, left and right across those of a
    // grid column
    let cells = anchor_cells(ctx, &anchors);
    {
        let key = |k: usize, f: super::net::Dir| (if f.horizontal() { cells[k].0 } else { cells[k].1 + 10000 }, f);
        let mut deepest: std::collections::HashMap<(usize, super::net::Dir), f64> = Default::default();
        for (k, sv) in straights.iter().enumerate() {
            for s in sv.iter().filter(|s| s.aligns) {
                let e = deepest.entry(key(k, s.f)).or_insert(s.a);
                if super::seat::sgn(s.f) * (s.a - *e) > 0.0 {
                    *e = s.a;
                }
            }
        }
        for (k, sv) in straights.iter_mut().enumerate() {
            let a_of: Vec<f64> = sv.iter().map(|s| if s.aligns { deepest[&key(k, s.f)] } else { s.a }).collect();
            seaters[k].seat_straight(std::mem::take(sv), &a_of);
        }
    }
    // up and down chains align across the anchors of a grid row; left and
    // right ones per anchor
    let rows: Vec<usize> = cells.iter().map(|c| c.1).collect();
    let _ = row_of;
    let mut row_ids: Vec<usize> = rows.clone();
    row_ids.sort();
    row_ids.dedup();
    for r in row_ids {
        let mut refs: Vec<&mut super::seat::Turn> = Vec::new();
        for (k, tv) in turns.iter_mut().enumerate() {
            if rows[k] == r {
                for t in tv.iter_mut() {
                    refs.push(t);
                }
            }
        }
        super::seat::align(&mut refs, &[super::net::Dir::U, super::net::Dir::D]);
    }
    for tv in turns.iter_mut() {
        let mut refs: Vec<&mut super::seat::Turn> = tv.iter_mut().collect();
        super::seat::align(&mut refs, &[super::net::Dir::L, super::net::Dir::R]);
    }
    for (k, mut st) in seaters.into_iter().enumerate() {
        let tv = std::mem::take(&mut turns[k]);
        st.seat_lanes(tv);
        let seats: Vec<super::seat::Seat> = st.seats.clone();
        if std::env::var("LINI_SCH_DBG").is_ok() {
            for s in &seats {
                eprintln!("seat {} of {} at ({}, {}) res {:?}", ctx.nodes[s.node].id.clone().unwrap_or_default(), ctx.nodes[anchors[k]].id.clone().unwrap_or_default(), s.x, s.y, s.res);
            }
        }
        for s in &seats {
            seated.insert(s.node);
        }
        clusters.push((anchors[k], seats));
    }
    // what no anchor seated falls back to the flow, chain by chain: breadth
    // first along the wires from the first of it
    let unseated: Vec<usize> = sats.iter().cloned().filter(|s| !seated.contains(s)).collect();
    let mut loose: Vec<usize> = Vec::new();
    for &start in &unseated {
        if loose.contains(&start) {
            continue;
        }
        let mut queue = std::collections::VecDeque::new();
        queue.push_back(start);
        loose.push(start);
        while let Some(d) = queue.pop_front() {
            for w in &wires {
                for (p, q) in [(&w.a, &w.b), (&w.b, &w.a)] {
                    if p.dev == d && unseated.contains(&q.dev) && !loose.contains(&q.dev) {
                        loose.push(q.dev);
                        queue.push_back(q.dev);
                    }
                }
            }
        }
    }
    for &s in &loose {
        let name = display_name(ctx, s);
        let span = ctx.nodes[s].span;
        ctx.warnings.push(Diag::warning(
            "schematic-seat",
            &format!("'{}' has no placed end — its chain falls back to the flow", name),
            span,
        ));
    }
    // each anchor's reach: its own drawn extent and its satellites' cells
    let mut reach: Vec<[f64; 4]> = Vec::new();
    // (the satellites' alone)
    let mut sat_reach: Vec<[f64; 4]> = Vec::new();
    for (a, seats) in clusters.iter() {
        let mut e = extent(ctx, *a);
        let mut sr = [f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY];
        for s in seats {
            e[0] = e[0].min(s.res[0]);
            e[1] = e[1].min(s.res[1]);
            e[2] = e[2].max(s.res[2]);
            e[3] = e[3].max(s.res[3]);
            sr[0] = sr[0].min(s.res[0]);
            sr[1] = sr[1].min(s.res[1]);
            sr[2] = sr[2].max(s.res[2]);
            sr[3] = sr[3].max(s.res[3]);
        }
        reach.push(e);
        sat_reach.push(sr);
    }
    // positions in lattice coordinates (origin: the first track's line)
    let mut pos: Vec<(usize, f64, f64)> = Vec::new();
    let mut ext = [f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY];
    if !anchors.is_empty() {
        let gap_margin = PITCH / 2.0 + PITCH * (col_gap / (2.0 * PITCH)).floor();
        let mut plans: Vec<BridgePlan> = bridges.iter().map(|b| plan_bridge(ctx, b, gap_margin, col_gap)).collect();
        grid(ctx, i, &anchors, &reach, &sat_reach, row_gap, col_gap, &mut pos, &wires, &mut plans);
        // the bridges' parts join their first anchor's cluster
        for (b, pl) in bridges.iter().zip(&plans) {
            if !pl.used {
                continue;
            }
            for (k, &(dev, _)) in b.parts.iter().enumerate() {
                let (x, y, res) = pl.seats[k];
                clusters[b.a].1.push(super::seat::Seat { node: dev, x, y, res, stack: 0, side: None });
                reach[b.a][0] = reach[b.a][0].min(res[0]);
                reach[b.a][1] = reach[b.a][1].min(res[1]);
                reach[b.a][2] = reach[b.a][2].max(res[2]);
                reach[b.a][3] = reach[b.a][3].max(res[3]);
            }
        }
        for (k, &(_, x, y)) in pos.iter().enumerate() {
            let e = reach[k];
            ext[0] = ext[0].min(x + e[0]);
            ext[1] = ext[1].min(y + e[1]);
            ext[2] = ext[2].max(x + e[2]);
            ext[3] = ext[3].max(y + e[3]);
        }
    }
    // the fallback row under the grid, centred on the lattice origin
    let mut row: Vec<(usize, f64, f64)> = Vec::new();
    let mut rbox = [f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY];
    if !loose.is_empty() {
        let sizes: Vec<(f64, f64)> = loose.iter().map(|&k| crate::layout::outer(ctx, k)).collect();
        let total: f64 = sizes.iter().map(|s| s.0).sum::<f64>() + col_gap * (loose.len() as f64 - 1.0);
        let hmax = sizes.iter().map(|s| s.1).fold(0.0, f64::max);
        let top = if anchors.is_empty() { -hmax / 2.0 } else { ext[3] + ceil_lattice(row_gap) };
        let cy = top + hmax / 2.0;
        let mut x = -total / 2.0;
        for (k, &ch) in loose.iter().enumerate() {
            let (w, _) = sizes[k];
            row.push((ch, x + w / 2.0, cy));
            x += w + col_gap;
        }
        rbox = [-total / 2.0, top, total / 2.0, top + hmax];
    }
    // centre the whole on the lattice
    let mut all = ext;
    all[0] = all[0].min(rbox[0]);
    all[1] = all[1].min(rbox[1]);
    all[2] = all[2].max(rbox[2]);
    all[3] = all[3].max(rbox[3]);
    let (ox, oy) = if anchors.is_empty() {
        (-(all[0] + all[2]) / 2.0, -(all[1] + all[3]) / 2.0)
    } else {
        (round_lattice(-(all[0] + all[2]) / 2.0), round_lattice(-(all[1] + all[3]) / 2.0))
    };
    if std::env::var("LINI_SCH_DBG").is_ok() {
        eprintln!("ext {:?} all {:?} o ({}, {}) pos {:?}", ext, all, ox, oy, pos);
    }
    // every body's lattice cells, scope-local: what the wires go around
    let mut bodies: Vec<(usize, [f64; 4], f64)> = Vec::new();
    for (k, &(a, x, y)) in pos.iter().enumerate() {
        place_node(ctx, a, x + ox, y + oy);
        for (b, sw) in drawn_boxes(ctx, a) {
            bodies.push((a, b, sw));
        }
        for s in &clusters[k].1 {
            // seated in lattice coordinates, then centred
            place_node(ctx, s.node, (x + s.x) + ox, (y + s.y) + oy);
            raise_run(ctx, s.node, s.side);
            stack_labels(ctx, s.node, s.stack);
            if s.side == Some(super::net::Dir::L) {
                flip_side_labels(ctx, s.node);
            }
            for (b, sw) in drawn_boxes(ctx, s.node) {
                bodies.push((s.node, b, sw));
            }
        }
    }
    for &(k, x, y) in &row {
        ctx.nodes[k].x = x + ox;
        ctx.nodes[k].y = y + oy;
        for (b, sw) in drawn_boxes(ctx, k) {
            bodies.push((k, b, sw));
        }
    }
    BODIES.with(|b| b.borrow_mut().push((i, bodies)));
    // the symmetric hull
    let mut hw: f64 = 0.0;
    let mut hh: f64 = 0.0;
    if !anchors.is_empty() {
        hw = hw.max((ext[0] + ox).abs()).max((ext[2] + ox).abs());
        hh = hh.max((ext[1] + oy).abs()).max((ext[3] + oy).abs());
    }
    if !loose.is_empty() {
        hw = hw.max((rbox[0] + ox).abs()).max((rbox[2] + ox).abs());
        hh = hh.max((rbox[1] + oy).abs()).max((rbox[3] + oy).abs());
    }
    let mut w = 2.0 * hw + pad[1] + pad[3];
    let mut h = 2.0 * hh + pad[0] + pad[2];
    if let Some(fw) = c.width {
        w = w.max(fw);
    }
    if let Some(fh) = c.height {
        h = h.max(fh);
    }
    ctx.nodes[i].w = w;
    ctx.nodes[i].h = h;
    for &p in &pinned {
        crate::layout::place_pinned(ctx, i, p);
    }
}

// a node's origin to (x, y): its box centre sits off it by its seat
pub fn place_node(ctx: &mut Ctx, k: usize, x: f64, y: f64) {
    let off = ctx.nodes[k].geo_off;
    ctx.nodes[k].x = x - off.0;
    ctx.nodes[k].y = y - off.1;
}

// anchors on the track grid: `cell: c r` (ordinal, empty tracks collapsing),
// the rest along the first row; each track pitch clears the extents of its
// neighbours by a pin pitch, at least the scope's gap, on the lattice
// the anchors' grid tracks (column, row): `cell: c r`, the rest filling the
// first row's free tracks in order
pub fn anchor_cells(ctx: &Ctx, anchors: &[usize]) -> Vec<(usize, usize)> {
    let env = &ctx.sheet.env;
    let mut cells: Vec<(usize, usize)> = Vec::new();
    let mut taken: Vec<(usize, usize)> = Vec::new();
    for &k in anchors {
        if let Some(v) = ctx.nodes[k].props.get("cell") {
            let xs = crate::style::value_nums(env, v);
            if xs.len() >= 2 {
                let cc = (xs[0].max(1.0)) as usize;
                let rr = (xs[1].max(1.0)) as usize;
                cells.push((cc, rr));
                taken.push((cc, rr));
                continue;
            }
        }
        cells.push((0, 0));
    }
    let mut next = 1usize;
    for c in cells.iter_mut() {
        if c.0 == 0 {
            while taken.contains(&(next, 1)) {
                next += 1;
            }
            *c = (next, 1);
            taken.push((next, 1));
            next += 1;
        }
    }
    cells
}

#[allow(clippy::too_many_arguments)]
fn grid(
    ctx: &Ctx,
    _scope: usize,
    anchors: &[usize],
    reach: &[[f64; 4]],
    sat_reach: &[[f64; 4]],
    row_gap: f64,
    col_gap: f64,
    pos: &mut Vec<(usize, f64, f64)>,
    wires: &[super::net::Wire],
    bridges: &mut [BridgePlan],
) {
    use super::net::{Dir, Kind};
    let cells: Vec<(usize, usize, usize)> = anchor_cells(ctx, anchors).into_iter().zip(anchors).map(|((c, r), &k)| (k, c, r)).collect();
    // collapse empty tracks
    let mut cols: Vec<usize> = cells.iter().map(|c| c.1).collect();
    cols.sort();
    cols.dedup();
    let mut rows: Vec<usize> = cells.iter().map(|c| c.2).collect();
    rows.sort();
    rows.dedup();
    let exts: Vec<[f64; 4]> = reach.to_vec();
    let col_of = |c: usize| cols.iter().position(|&x| x == c).unwrap();
    let row_of = |r: usize| rows.iter().position(|&x| x == r).unwrap();
    // wires straight across a gap: the pitch keeps a pitch per wire, and the
    // first wire between two anchors lines their pins up (the anchor to the
    // right, or below, steps to the other's pin)
    let mut shift = vec![(0.0f64, 0.0f64); anchors.len()];
    let mut col_wires = vec![0usize; cols.len()];
    let mut row_wires = vec![0usize; rows.len()];
    let mut paired: Vec<(usize, usize)> = Vec::new();
    for w in wires {
        let at = |dev: usize| anchors.iter().position(|&a| a == dev);
        let (ia, ib) = match (at(w.a.dev), at(w.b.dev)) {
            (Some(a), Some(b)) if a != b => (a, b),
            _ => continue,
        };
        if !matches!(w.a.kind, Kind::Pin | Kind::Station) || !matches!(w.b.kind, Kind::Pin | Kind::Station) {
            continue;
        }
        let (ca, ra) = (col_of(cells[ia].1), row_of(cells[ia].2));
        let (cb, rb) = (col_of(cells[ib].1), row_of(cells[ib].2));
        if ra == rb && ca.abs_diff(cb) == 1 {
            let (l, r, tl, tr) = if ca < cb { (ia, ib, &w.a, &w.b) } else { (ib, ia, &w.b, &w.a) };
            col_wires[ca.max(cb)] += 1;
            if tl.dir == Dir::R && tr.dir == Dir::L {
                if !paired.contains(&(l, r)) {
                    paired.push((l, r));
                    let (yl, yr) = (shift[l].1 + tl.off.1, shift[r].1 + tr.off.1);
                    shift[r].1 += yl - yr;
                }
            }
        } else if ca == cb && ra.abs_diff(rb) == 1 {
            let (u, d, tu, td) = if ra < rb { (ia, ib, &w.a, &w.b) } else { (ib, ia, &w.b, &w.a) };
            row_wires[ra.max(rb)] += 1;
            if tu.dir == Dir::D && td.dir == Dir::U {
                if !paired.contains(&(u, d)) {
                    paired.push((u, d));
                    let (xu, xd) = (shift[u].0 + tu.off.0, shift[d].0 + td.off.0);
                    shift[d].0 += xu - xd;
                }
            }
        }
    }
    // a bridge across a gap lines its pins up like a wire
    for b in bridges.iter_mut() {
        let (ca, ra) = (col_of(cells[b.a].1), row_of(cells[b.a].2));
        let (cb, rb) = (col_of(cells[b.b].1), row_of(cells[b.b].2));
        if ra != rb || ca.abs_diff(cb) != 1 {
            continue;
        }
        let facing = if ca < cb { b.pa.dir == Dir::R && b.pb.dir == Dir::L } else { b.pa.dir == Dir::L && b.pb.dir == Dir::R };
        if !facing {
            continue;
        }
        b.used = true;
        let (l, r) = if ca < cb { (b.a, b.b) } else { (b.b, b.a) };
        if !paired.contains(&(l, r)) {
            paired.push((l, r));
            let (ya, yb) = (shift[b.a].1 + b.pa.off.1, shift[b.b].1 + b.pb.off.1);
            if r == b.b {
                shift[b.b].1 += ya - yb;
            } else {
                shift[b.a].1 += yb - ya;
            }
        }
    }
    let mut left = vec![0.0f64; cols.len()];
    let mut right = vec![0.0f64; cols.len()];
    let mut top = vec![0.0f64; rows.len()];
    let mut bottom = vec![0.0f64; rows.len()];
    for (k, c) in cells.iter().enumerate() {
        let (ci, ri) = (col_of(c.1), row_of(c.2));
        let (sx, sy) = shift[k];
        left[ci] = left[ci].max(-(exts[k][0] + sx));
        right[ci] = right[ci].max(exts[k][2] + sx);
        top[ri] = top[ri].max(-(exts[k][1] + sy));
        bottom[ri] = bottom[ri].max(exts[k][3] + sy);
    }
    let mut colx = vec![0.0; cols.len()];
    for k in 1..cols.len() {
        let need = ceil_lattice(right[k - 1] + left[k] + PITCH * col_wires[k].max(1) as f64);
        let mut pitch = need.max(ceil_lattice(col_gap));
        // a bridge's first part stands the margin past its first anchor's
        // satellites, or a pitch more past its own drawing; its parts a gap
        // apart, and the next anchor whole gaps past the last one, as many as
        // its own satellites on that side ask with the margin (its drawing
        // asks none)
        for b in bridges.iter_mut().filter(|b| b.used) {
            let (ca, cb) = (col_of(cells[b.a].1), col_of(cells[b.b].1));
            if ca.max(cb) != k {
                continue;
            }
            let (oa, sa, sb) = (extent(ctx, anchors[b.a]), &sat_reach[b.a], &sat_reach[b.b]);
            let (sxa, sxb) = (shift[b.a].0, shift[b.b].0);
            let (own_a, sat_a, sat_b) = if ca < cb { (oa[2] + sxa, sa[2] + sxa, -(sb[0] + sxb)) } else { (-(oa[0] + sxa), -(sa[0] + sxa), sb[2] + sxb) };
            let near_a = own_a.max(if sat_a.is_finite() { sat_a } else { f64::NEG_INFINITY }) + PITCH;
            let near_b = if sat_b.is_finite() { sat_b.max(0.0) } else { 0.0 };
            let first = ceil_lattice(near_a + b.h_first);
            let gaps = if col_gap > 0.0 { ((near_b + b.h_last) / col_gap - 1e-9).ceil().max(1.0) } else { 1.0 };
            let tail = col_gap * gaps;
            b.first = first;
            if std::env::var("LINI_SCH_DBG").is_ok() {
                let id = |k: usize| ctx.nodes[k].id.clone().unwrap_or_default();
                eprintln!(
                    "bridge {} {} {} near_a {} near_b {} first {} span {} tail {} need {} gap {} hl {}",
                    id(anchors[b.a]),
                    id(anchors[b.b]),
                    b.devs.iter().map(|&d| id(d)).collect::<Vec<_>>().join(","),
                    near_a,
                    near_b,
                    first,
                    b.span,
                    tail,
                    need,
                    col_gap,
                    b.h_last
                );
            }
            pitch = pitch.max(first + b.span + tail);
        }
        colx[k] = colx[k - 1] + pitch;
    }
    let mut rowy = vec![0.0; rows.len()];
    for k in 1..rows.len() {
        let need = ceil_lattice(bottom[k - 1] + top[k] + PITCH * row_wires[k].max(1) as f64);
        rowy[k] = rowy[k - 1] + need.max(ceil_lattice(row_gap));
    }
    for (k, c) in cells.iter().enumerate() {
        pos.push((c.0, colx[col_of(c.1)] + shift[k].0, rowy[row_of(c.2)] + shift[k].1));
    }
    // the bridges' parts, from their first anchor
    for b in bridges.iter_mut().filter(|b| b.used) {
        let dir = if b.pa.dir == Dir::R { 1.0 } else { -1.0 };
        let mut seats = Vec::new();
        for &(rx, ry, res) in &b.rel {
            let x = dir * b.first + rx;
            let y = b.pa.off.1 + ry;
            let res = if dir > 0.0 {
                [res[0] + b.first, res[1] + b.pa.off.1, res[2] + b.first, res[3] + b.pa.off.1]
            } else {
                [res[0] - b.first, res[1] + b.pa.off.1, res[2] - b.first, res[3] + b.pa.off.1]
            };
            seats.push((x, y, res));
        }
        b.seats = seats;
    }
}

// a chain of two-pin parts between pins of two anchors
pub struct Bridge {
    // anchor indices: the chain's first end, its last
    pub a: usize,
    pub b: usize,
    pub pa: super::net::Term,
    pub pb: super::net::Term,
    // (part, its entry term)
    pub parts: Vec<(usize, super::net::Term)>,
}

pub struct BridgePlan {
    a: usize,
    b: usize,
    pa: super::net::Term,
    pb: super::net::Term,
    // the parts relative to the first one's place on its anchor's side:
    // (x, y off the pin's row, reserved box)
    rel: Vec<(f64, f64, [f64; 4])>,
    // the first part's reach toward its anchor, the last one's away
    h_first: f64,
    h_last: f64,
    // the last part's centre from the first's
    span: f64,
    // the first part's centre from its anchor (set by the grid)
    first: f64,
    used: bool,
    seats: Vec<(f64, f64, [f64; 4])>,
    devs: Vec<usize>,
}

fn bridge_spans(ctx: &Ctx, anchors: &[usize], b: &Bridge) -> bool {
    let cells = anchor_cells(ctx, anchors);
    let (ca, ra) = cells[b.a];
    let (cb, rb) = cells[b.b];
    let mut cols: Vec<usize> = cells.iter().map(|c| c.0).collect();
    cols.sort();
    cols.dedup();
    let ia = cols.iter().position(|&c| c == ca).unwrap_or(0);
    let ib = cols.iter().position(|&c| c == cb).unwrap_or(0);
    if ra != rb || ia.abs_diff(ib) != 1 {
        return false;
    }
    use super::net::Dir;
    if ia < ib {
        b.pa.dir == Dir::R && b.pb.dir == Dir::L
    } else {
        b.pa.dir == Dir::L && b.pb.dir == Dir::R
    }
}

// chains of two-pin parts from one anchor's pin to another anchor's, in
// statement order
pub fn find_bridges(ctx: &Ctx, anchors: &[usize], wires: &[super::net::Wire]) -> Vec<Bridge> {
    use super::net::Kind;
    let mut out: Vec<Bridge> = Vec::new();
    let at = |dev: usize| anchors.iter().position(|&a| a == dev);
    let pinlike = |t: &super::net::Term| matches!(t.kind, Kind::Pin | Kind::Station);
    for w in wires {
        for (p, q) in [(&w.a, &w.b), (&w.b, &w.a)] {
            let ia = match at(p.dev) {
                Some(k) if pinlike(p) => k,
                _ => continue,
            };
            if at(q.dev).is_some() || q.kind != Kind::Station || pin_count(ctx, q.dev) != 2 {
                continue;
            }
            if out.iter().any(|b| b.parts.iter().any(|x| x.0 == q.dev)) {
                continue;
            }
            // walk the chain
            let mut parts: Vec<(usize, super::net::Term)> = vec![(q.dev, q.clone())];
            let mut cur = q.clone();
            let mut end: Option<(usize, super::net::Term)> = None;
            for _ in 0..32 {
                let exit = match super::seat::exit_of(ctx, &cur) {
                    Some(e) => e,
                    None => break,
                };
                let mut next: Option<super::net::Term> = None;
                for w2 in wires {
                    for (u, v) in [(&w2.a, &w2.b), (&w2.b, &w2.a)] {
                        if u.node == exit.node && v.dev != cur.dev && next.is_none() {
                            next = Some(v.clone());
                        }
                    }
                }
                let n = match next {
                    Some(n) => n,
                    None => break,
                };
                if let Some(ib) = at(n.dev) {
                    if pinlike(&n) && ib != ia {
                        end = Some((ib, n));
                    }
                    break;
                }
                if n.kind != Kind::Station || pin_count(ctx, n.dev) != 2 || parts.iter().any(|x| x.0 == n.dev) {
                    break;
                }
                parts.push((n.dev, n.clone()));
                cur = n;
            }
            if let Some((ib, pb)) = end {
                out.push(Bridge { a: ia, b: ib, pa: p.clone(), pb, parts });
            }
        }
    }
    out
}

// a bridge's parts laid along its first pin's facing, each clear of the one
// before by a pitch; toward the anchors a part keeps the gap margin
fn plan_bridge(ctx: &Ctx, b: &Bridge, margin: f64, gap: f64) -> BridgePlan {
    let d = b.pa.dir;
    let sg = if d == super::net::Dir::R || d == super::net::Dir::D { 1.0 } else { -1.0 };
    let mut rel: Vec<(f64, f64, [f64; 4])> = Vec::new();
    let mut h_first = 0.0;
    let mut h_last = 0.0;
    let mut prev_far: Option<f64> = None;
    let mut first_x = 0.0;
    let mut last_x = 0.0;
    for (k, (dev, entry)) in b.parts.iter().enumerate() {
        let body = super::seat::body(ctx, *dev);
        // the reach behind and ahead of the centre along the facing
        let (behind, ahead) = if sg > 0.0 { (-body[0], body[2]) } else { (body[2], -body[0]) };
        let _ = (behind, prev_far);
        let x = sg * gap * k as f64;
        let hb = margin;
        let ha = margin;
        if k == 0 {
            h_first = hb;
            first_x = x;
        }
        h_last = ha;
        last_x = x;
        let y = -entry.off.1;
        let (cy0, cy1) = (y - super::seat::cell_half(-body[1]), y + super::seat::cell_half(body[3]));
        let res = [x - if sg > 0.0 { hb } else { ha }, cy0, x + if sg > 0.0 { ha } else { hb }, cy1];
        rel.push((x, y, res));
        prev_far = Some(x + sg * ahead);
    }
    BridgePlan {
        a: b.a,
        b: b.b,
        pa: b.pa.clone(),
        pb: b.pb.clone(),
        rel,
        h_first,
        h_last,
        span: (last_x - first_x).abs(),
        first: 0.0,
        used: false,
        seats: Vec::new(),
        devs: b.parts.iter().map(|p| p.0).collect(),
    }
}
