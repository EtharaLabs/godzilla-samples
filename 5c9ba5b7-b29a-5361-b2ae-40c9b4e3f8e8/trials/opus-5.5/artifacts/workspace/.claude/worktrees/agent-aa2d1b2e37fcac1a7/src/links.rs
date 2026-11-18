// Links: style cascade, routing orchestration, labels, label cut-outs and
// the `<g class="lini-links">` layer.

use crate::ast::{Decl, Stmt, Term, Value};
use crate::compile::{get, Ctx};
use crate::diag::Diag;
use crate::font::Family;
use crate::render::Out;
use crate::route::{self, Ob, ObKind, Rect, Side};
use crate::style::*;
use crate::types::Prim;
use crate::util::{f4, hash8, xml_escape};

#[derive(Clone, Debug, Default)]
pub struct LStyle {
    // full cascade (rules, classes, scoped rules, inline)
    pub props: Vec<(String, Value)>,
    // scoped rules + inline: rendered as the link's inline style
    pub own: Vec<(String, Value)>,
    // classes + own: label inline style
    pub label_props: Vec<(String, Value)>,
    pub sw: f64,
    pub line: String,
    pub start: Option<String>,
    pub end: Option<String>,
    pub k: f64,
    pub radius: Option<f64>,
    pub routing: String,
    pub along: Option<f64>,
    pub font_size: f64,
    pub weight: u32,
    pub family: Option<Family>,
}

#[derive(Clone, Debug)]
pub struct Label {
    pub text: String,
    pub x: f64,
    pub y: f64,
    pub tw: f64,
    pub fs: f64,
    // per-char advances in font units, and the font's units per em
    pub units: Vec<f64>,
    pub upem: f64,
    pub classes: Vec<String>,
    pub props: Vec<(String, Value)>,
}

impl Label {
    // The cut-out as the id key sees it: the text width summed glyph by
    // glyph (each advance scaled on its own).
    pub fn cut_exact(&self) -> (f64, f64, f64, f64) {
        let mut tw = 0.0;
        for &u in &self.units {
            tw += u / self.upem * self.fs;
        }
        let w = tw + 2.0 * (0.3 * self.fs);
        let h = self.fs + 2.0 * (0.15 * self.fs);
        (self.x - w / 2.0, self.y - h / 2.0, w, h)
    }
    pub fn cut(&self) -> Rect {
        let w = self.tw + 0.6 * self.fs;
        let h = 1.3 * self.fs;
        Rect::new(self.x - w / 2.0, self.y - h / 2.0, self.x + w / 2.0, self.y + h / 2.0)
    }
    fn hit_box(&self) -> Rect {
        Rect::new(self.x - self.tw / 2.0 - 1.0, self.y - self.fs / 2.0 - 1.0, self.x + self.tw / 2.0 + 1.0, self.y + self.fs / 2.0 + 1.0)
    }
}

#[derive(Clone, Debug, Default)]
pub struct LinkGeo {
    pub li: usize,
    pub stray: bool,
    // orthogonal polyline, boundary point to boundary point
    pub pts: Vec<(f64, f64)>,
    // natural routing: cubic between the two stubs
    pub curve: Option<[(f64, f64); 4]>,
    pub radii: Vec<f64>,
    pub style: LStyle,
    pub labels: Vec<Label>,
    // global label indices whose cut-outs fall in this link's mask
    pub cuts: Vec<(usize, usize)>,
    pub sa: Option<Side>,
    pub sb: Option<Side>,
}

// ------------------------------------------------------------ helpers

fn set(props: &mut Vec<(String, Value)>, k: &str, v: &Value) {
    if let Some(e) = props.iter_mut().find(|e| e.0 == k) {
        e.1 = v.clone();
    } else {
        props.push((k.to_string(), v.clone()));
    }
}

fn num_of(ctx: &Ctx, props: &[(String, Value)], k: &str) -> Option<f64> {
    get(props, k).and_then(|v| value_num(&ctx.sheet.env, v))
}

fn ident_prop(props: &[(String, Value)], k: &str) -> Option<String> {
    get(props, k).and_then(|v| ident_of(v)).map(|s| s.to_string())
}

// Ancestor chain of a node, root first, the node itself last.
fn chain(ctx: &Ctx, i: usize) -> Vec<usize> {
    let mut v = vec![i];
    let mut cur = i;
    while let Some(p) = ctx.nodes[cur].parent {
        v.push(p);
        cur = p;
    }
    v.reverse();
    v
}

pub fn is_ancestor(ctx: &Ctx, anc: usize, i: usize) -> bool {
    let mut cur = i;
    while let Some(p) = ctx.nodes[cur].parent {
        if p == anc {
            return true;
        }
        cur = p;
    }
    false
}

// Dotted id path of a node from the root.
pub fn path_of(ctx: &Ctx, i: usize) -> String {
    let mut parts = Vec::new();
    let mut cur = i;
    loop {
        if let Some(id) = &ctx.nodes[cur].id {
            parts.push(id.clone());
        }
        if cur == 0 {
            break;
        }
        let sc = ctx.nodes[cur].scope;
        if sc == cur {
            break;
        }
        cur = sc;
    }
    parts.reverse();
    parts.join(".")
}

// Absolute centre of a node (translations only).
pub fn abs_center(ctx: &Ctx, i: usize) -> (f64, f64) {
    let mut x = 0.0;
    let mut y = 0.0;
    let mut cur = i;
    while cur != 0 {
        let n = &ctx.nodes[cur];
        let c = &ctx.comp[cur];
        x += n.x + c.translate.0;
        y += n.y + c.translate.1;
        match n.parent {
            Some(p) => cur = p,
            None => break,
        }
    }
    (x, y)
}

// Absolute outer box of a node (stroke included).
pub fn abs_rect(ctx: &Ctx, i: usize) -> Rect {
    let (cx, cy) = abs_center(ctx, i);
    let (w, h) = crate::layout::outer(ctx, i);
    Rect::centered(cx, cy, w, h)
}

// Inner box (no stroke): what labels keep off.
pub fn abs_inner(ctx: &Ctx, i: usize) -> Rect {
    let (cx, cy) = abs_center(ctx, i);
    let n = &ctx.nodes[i];
    Rect::new(cx - n.w / 2.0, cy - n.h / 2.0, cx + n.w / 2.0, cy + n.h / 2.0)
}

// Split a link operator into (left end, line, right end).
pub fn split_op(op: &str) -> (String, String, String) {
    let chars: Vec<char> = op.chars().collect();
    let mut i = 0;
    let mut left = String::new();
    while i < chars.len() && chars[i] != '-' && chars[i] != '~' {
        left.push(chars[i]);
        i += 1;
    }
    let mut line = String::new();
    while i < chars.len() && (chars[i] == '-' || chars[i] == '~') {
        line.push(chars[i]);
        i += 1;
    }
    let right: String = chars[i..].iter().collect();
    (left, line, right)
}

fn left_marker(s: &str) -> Option<String> {
    Some(
        match s {
            "<" => "arrow",
            "*" => "dot",
            ">" => "crow",
            "+" => "one",
            ">+" => "one-or-many",
            ">o" => "zero-or-many",
            "+o" => "zero-or-one",
            _ => return None,
        }
        .to_string(),
    )
}

fn right_marker(s: &str) -> Option<String> {
    Some(
        match s {
            ">" => "arrow",
            "*" => "dot",
            "<" => "crow",
            "+" => "one",
            "+<" => "one-or-many",
            "o<" => "zero-or-many",
            "o+" => "zero-or-one",
            _ => return None,
        }
        .to_string(),
    )
}

// ------------------------------------------------------------ style

pub fn link_style(ctx: &Ctx, li: usize) -> LStyle {
    let l = &ctx.links[li];
    let mut props: Vec<(String, Value)> = Vec::new();
    let ch = chain(ctx, l.container);
    for &c in &ch {
        for k in ["clearance", "routing"] {
            if let Some(v) = ctx.nodes[c].props.get(k) {
                set(&mut props, k, v);
            }
        }
    }
    for d in &ctx.sheet.link_rules {
        set(&mut props, &d.name, &d.value);
    }
    let mut own: Vec<(String, Value)> = Vec::new();
    let mut label_props: Vec<(String, Value)> = Vec::new();
    // scoped link rules rank below classes and ride inline (src/scoped.rs)
    let scoped = crate::scoped::link_decls(ctx, l);
    for (k, v) in &scoped {
        set(&mut props, k, v);
        set(&mut label_props, k, v);
    }
    for cr in ctx.sheet.worn(&l.classes) {
        for d in &cr.decls {
            set(&mut props, &d.name, &d.value);
            set(&mut label_props, &d.name, &d.value);
        }
    }
    for (k, v) in crate::scoped::link_inline(ctx, l, &scoped) {
        set(&mut own, &k, &v);
    }
    for d in &l.style {
        set(&mut props, &d.name, &d.value);
        set(&mut own, &d.name, &d.value);
        set(&mut label_props, &d.name, &d.value);
    }
    let (lo, line, ro) = split_op(&l.op);
    let mut line_kind = match line.as_str() {
        "--" => "dashed",
        "---" => "dotted",
        "~" => "wavy",
        _ => "solid",
    }
    .to_string();
    if let Some(s) = ident_prop(&props, "stroke-style") {
        line_kind = s;
    }
    let mut start = left_marker(&lo);
    let mut end = right_marker(&ro);
    if let Some(m) = ident_prop(&props, "marker") {
        start = Some(m.clone());
        end = Some(m);
    }
    if let Some(m) = ident_prop(&props, "marker-start") {
        start = Some(m);
    }
    if let Some(m) = ident_prop(&props, "marker-end") {
        end = Some(m);
    }
    let norm = |m: Option<String>| m.filter(|s| s != "none" && crate::markers::is_known(s));
    let start = norm(start);
    let end = norm(end);
    let sw = num_of(ctx, &props, "stroke-width").unwrap_or(2.0);
    let k = num_of(ctx, &props, "clearance").unwrap_or(16.0);
    let radius = num_of(ctx, &props, "corner-radius");
    let routing = ident_prop(&props, "routing").unwrap_or_else(|| "orthogonal".to_string());
    let along = num_of(ctx, &props, "along");
    let font_size = num_of(ctx, &props, "font-size").unwrap_or(11.0);
    let weight = get(&props, "font-weight").map(weight_num).unwrap_or(400);
    let family = get(&props, "font-family").map(family_of);
    LStyle {
        props,
        own,
        label_props,
        sw,
        line: line_kind,
        start,
        end,
        k,
        radius,
        routing,
        along,
        font_size,
        weight,
        family,
    }
}

// ------------------------------------------------------------ ordering

// Links render container by container, depth first; within a container in
// statement order.
pub fn link_order(ctx: &Ctx) -> Vec<usize> {
    let mut order = Vec::new();
    let mut stack = vec![0usize];
    let mut visit: Vec<usize> = Vec::new();
    while let Some(n) = stack.pop() {
        visit.push(n);
        for &c in ctx.nodes[n].children.iter().rev() {
            stack.push(c);
        }
    }
    for n in visit {
        let mut here: Vec<usize> = (0..ctx.links.len()).filter(|&i| ctx.links[i].container == n).collect();
        here.sort_by_key(|&i| (ctx.links[i].stmt_index, i));
        order.extend(here);
    }
    order
}

// Links drawn by a layout family (sequence, tree…) are not routed here.
pub fn family_owned(ctx: &Ctx, li: usize) -> bool {
    let l = &ctx.links[li];
    for &c in &chain(ctx, l.container) {
        let lay = ctx.comp[c].layout.as_str();
        if matches!(lay, "sequence" | "tree" | "mindmap" | "schematic" | "drawing" | "floorplan" | "chart" | "pie") {
            return true;
        }
        if ctx.nodes[c].is("mindmap") {
            return true;
        }
    }
    false
}

// ------------------------------------------------------------ compute

pub fn compute(ctx: &mut Ctx) {
    let order = link_order(ctx);
    let mut geos: Vec<LinkGeo> = Vec::new();
    let mut reqs: Vec<crate::wires::LinkReq> = Vec::new();
    for &li in &order {
        if family_owned(ctx, li) {
            continue;
        }
        let style = link_style(ctx, li);
        let l = &ctx.links[li];
        let pull_s = style.start.as_deref().map(|m| crate::markers::marker_full(m, (0.0, 0.0), (1.0, 0.0), style.sw).pull).unwrap_or(0.0);
        let pull_e = style.end.as_deref().map(|m| crate::markers::marker_full(m, (0.0, 0.0), (1.0, 0.0), style.sw).pull).unwrap_or(0.0);
        let from = promote(ctx, l.from, l.to, style.k);
        let to = promote(ctx, l.to, l.from, style.k);
        reqs.push(crate::wires::LinkReq {
            from,
            to,
            anchor_a: l.from_anchor.as_deref().and_then(Side::parse),
            anchor_b: l.to_anchor.as_deref().and_then(Side::parse),
            k: style.k,
            radius: style.radius.unwrap_or(style.k),
            routing: style.routing.clone(),
            stmt: l.stmt_index,
            pull_s: if pull_s > 0.0 { pull_s - 0.5 } else { 0.0 },
            pull_e: if pull_e > 0.0 { pull_e - 0.5 } else { 0.0 },
            mark_len_s: if style.start.is_some() { crate::markers::arrow_len(style.sw) } else { 0.0 },
            mark_len_e: if style.end.is_some() { crate::markers::arrow_len(style.sw) } else { 0.0 },
        });
        geos.push(LinkGeo { li, style, ..Default::default() });
    }
    // a link with both a label and a label block
    let mut warned: Vec<usize> = Vec::new();
    for &li in &order {
        let l = &ctx.links[li];
        if l.label.is_some() && !l.labels.is_empty() && !warned.contains(&l.stmt_index) {
            warned.push(l.stmt_index);
            let d = Diag::warning("validate", "keep a link's labels together \u{2014} write 'a -> b [ \"x\" \"y\" ]'", l.span);
            ctx.warnings.push(d);
        }
    }
    let world = World::new(ctx);
    let routed = route_all(ctx, &world, &reqs);
    for (g, r) in geos.iter_mut().zip(routed.into_iter()) {
        g.stray = r.stray;
        g.pts = r.pts;
        g.radii = r.radii;
        g.curve = r.curve;
        g.sa = r.sa;
        g.sb = r.sb;
    }
    // warnings for impossible links
    for g in &geos {
        if g.stray {
            let l = &ctx.links[g.li];
            let msg = format!(
                "impossible ({} {} {}): no legal route: every side entry or channel is closed at this layout",
                path_of(ctx, l.from),
                l.op,
                path_of(ctx, l.to)
            );
            ctx.warnings.push(Diag::warning("impossible-link", &msg, l.span));
        }
    }
    place_labels(ctx, &world, &mut geos);
    compute_masks(&mut geos);
    ctx.link_geo = geos;
}

// Gap between two boxes (negative when they overlap).
fn box_gap(a: &Rect, b: &Rect) -> f64 {
    (b.x0 - a.x1).max(a.x0 - b.x1).max(b.y0 - a.y1).max(a.y0 - b.y1)
}

// A node packed closer than the clearance to a sibling cannot be reached on
// its own from outside its container: the wire attaches to the container.
pub fn promote(ctx: &Ctx, n: usize, other: usize, k: f64) -> usize {
    let mut cur = n;
    loop {
        let Some(p) = ctx.nodes[cur].parent else { return cur };
        if p == 0 || p == other || is_ancestor(ctx, p, other) {
            return cur;
        }
        let me = abs_rect(ctx, cur);
        let packed = ctx.nodes[p].children.iter().any(|&s| {
            s != cur && ctx.nodes[s].prim != Prim::Text && ctx.comp[s].pin.is_none() && box_gap(&me, &abs_rect(ctx, s)) < k
        });
        if !packed {
            return cur;
        }
        cur = p;
    }
}

// The scene as seen by the router: absolute boxes for every node.
pub struct World {
    pub rects: Vec<Rect>,
}

impl World {
    pub fn new(ctx: &Ctx) -> World {
        let rects: Vec<Rect> = (0..ctx.nodes.len()).map(|i| abs_rect(ctx, i)).collect();
        if std::env::var("LINI_DBG_RECT").is_ok() {
            for (i, r) in rects.iter().enumerate() {
                let (w, h) = crate::layout::outer(ctx, i);
                eprintln!("RECT {} {:?} x={:?} y={:?} w={:?} h={:?} nw={:?} nh={:?}", i, ctx.nodes[i].id, ctx.nodes[i].x, ctx.nodes[i].y, w, h, ctx.nodes[i].w, ctx.nodes[i].h);
                let _ = r;
            }
        }
        World { rects }
    }
}

pub fn is_obstacle_kind(ctx: &Ctx, i: usize) -> bool {
    let n = &ctx.nodes[i];
    if n.prim == Prim::Text {
        return false;
    }
    if ctx.comp[i].pin.is_some() && !n.is("caption") {
        return false;
    }
    true
}

// Obstacles for a link between `a` and `b`: maximal nodes that hold neither
// endpoint; containers of an endpoint become walls.
pub fn obstacles(ctx: &Ctx, world: &World, a: usize, b: usize) -> Vec<Ob> {
    let mut out = Vec::new();
    let mut stack: Vec<usize> = ctx.nodes[0].children.clone();
    while let Some(n) = stack.pop() {
        if n == a || n == b {
            continue;
        }
        if !is_obstacle_kind(ctx, n) {
            continue;
        }
        let ha = is_ancestor(ctx, n, a);
        let hb = is_ancestor(ctx, n, b);
        if ha || hb {
            let kind = if ha && hb {
                ObKind::WallBoth
            } else if ha {
                ObKind::WallA
            } else {
                ObKind::WallB
            };
            out.push(Ob { r: world.rects[n], kind, node: n });
            for &c in &ctx.nodes[n].children {
                stack.push(c);
            }
        } else {
            out.push(Ob { r: world.rects[n], kind: ObKind::Solid, node: n });
            // a container's caption sits outside its box
            for &c in &ctx.nodes[n].children {
                if ctx.comp[c].pin.is_some() && ctx.nodes[c].is("caption") && c != a && c != b {
                    out.push(Ob { r: world.rects[c], kind: ObKind::Solid, node: c });
                }
            }
        }
    }
    out.sort_by_key(|o| o.node);
    out
}

pub struct Routed {
    pub stray: bool,
    pub pts: Vec<(f64, f64)>,
    pub radii: Vec<f64>,
    pub curve: Option<[(f64, f64); 4]>,
    pub sa: Option<Side>,
    pub sb: Option<Side>,
}

fn route_all(ctx: &Ctx, world: &World, reqs: &[crate::wires::LinkReq]) -> Vec<Routed> {
    crate::wires::route_links(ctx, world, reqs)
}

// ------------------------------------------------------------ labels

fn poly_len(pts: &[(f64, f64)]) -> f64 {
    let mut t = 0.0;
    for w in pts.windows(2) {
        t += ((w[1].0 - w[0].0).powi(2) + (w[1].1 - w[0].1).powi(2)).sqrt();
    }
    t
}

fn point_at(pts: &[(f64, f64)], s: f64) -> (f64, f64) {
    let mut acc = 0.0;
    for w in pts.windows(2) {
        let l = ((w[1].0 - w[0].0).powi(2) + (w[1].1 - w[0].1).powi(2)).sqrt();
        if acc + l >= s && l > 0.0 {
            let t = (s - acc) / l;
            return (w[0].0 + (w[1].0 - w[0].0) * t, w[0].1 + (w[1].1 - w[0].1) * t);
        }
        acc += l;
    }
    *pts.last().unwrap_or(&(0.0, 0.0))
}

fn label_family(ctx: &Ctx, st: &LStyle) -> Family {
    st.family.unwrap_or(ctx.comp[0].family)
}

fn label_texts(ctx: &Ctx, li: usize) -> Vec<(String, Vec<String>, Vec<Decl>)> {
    let l = &ctx.links[li];
    let mut v = Vec::new();
    if let Some(t) = &l.label {
        v.push((t.clone(), vec![], vec![]));
    }
    for s in &l.labels {
        if let Stmt::Text(t) = s {
            v.push((t.text.clone(), t.classes.clone(), t.style.clone().unwrap_or_default()));
        }
    }
    v
}

fn place_labels(ctx: &Ctx, world: &World, geos: &mut [LinkGeo]) {
    // label keep-out: every leaf box
    let mut keep: Vec<Rect> = Vec::new();
    for i in 1..ctx.nodes.len() {
        let n = &ctx.nodes[i];
        if n.prim == Prim::Text {
            continue;
        }
        if n.children.iter().any(|&c| ctx.nodes[c].prim != Prim::Text && ctx.comp[c].pin.is_none()) {
            continue;
        }
        let _ = world;
        keep.push(abs_inner(ctx, i));
    }
    let mut placed: Vec<Rect> = Vec::new();
    for g in geos.iter_mut() {
        if g.stray || g.pts.len() < 2 {
            continue;
        }
        let texts = label_texts(ctx, g.li);
        if texts.is_empty() {
            continue;
        }
        let total = poly_len(&g.pts);
        let n = texts.len();
        let fam = label_family(ctx, &g.style);
        for (k, (text, classes, style)) in texts.into_iter().enumerate() {
            let mut props: Vec<(String, Value)> = g.style.label_props.iter().filter(|(k, _)| k != "translate" && k != "rotate").cloned().collect();
            for c in &classes {
                if let Some(cr) = ctx.sheet.class(c) {
                    for d in &cr.decls {
                        set(&mut props, &d.name, &d.value);
                    }
                }
            }
            for d in &style {
                set(&mut props, &d.name, &d.value);
            }
            let fs = num_of(ctx, &props, "font-size").unwrap_or(g.style.font_size);
            let wt = get(&props, "font-weight").map(weight_num).unwrap_or(g.style.weight);
            let tw = crate::font::text_width(fam, wt, fs, &text);
            let fnt = crate::font::font(fam, wt);
            let units: Vec<f64> = text.chars().map(|c| crate::font::char_advance_em(fam, wt, c) * fnt.upem).collect();
            let upem = fnt.upem;
            let frac = if n == 1 {
                g.style.along.unwrap_or(0.5)
            } else {
                ((k as f64 + 1.0) / (n as f64 + 1.0) * 100.0).round() / 100.0
            };
            let s0 = frac * total;
            let mk = |s: f64| {
                let (x, y) = point_at(&g.pts, s);
                Label { text: text.clone(), x, y, tw, fs, units: units.clone(), upem, classes: classes.clone(), props: props.clone() }
            };
            let ok = |lb: &Label| {
                let c = lb.cut();
                let hb = lb.hit_box();
                !keep.iter().any(|r| r.overlaps(&c)) && !placed.iter().any(|r| r.overlaps(&hb))
            };
            let mut chosen = mk(s0);
            if !ok(&chosen) {
                let mut step = 1;
                let mut found = None;
                loop {
                    let d = 4.0 * step as f64;
                    if s0 + d > total + 1e-9 && s0 - d < -1e-9 {
                        break;
                    }
                    for s in [s0 + d, s0 - d] {
                        if s < -1e-9 || s > total + 1e-9 {
                            continue;
                        }
                        let lb = mk(s);
                        if ok(&lb) {
                            found = Some(lb);
                            break;
                        }
                    }
                    if found.is_some() {
                        break;
                    }
                    step += 1;
                }
                if let Some(lb) = found {
                    chosen = lb;
                }
            }
            placed.push(chosen.hit_box());
            // a label's own translate nudges it off its place on the wire
            if let Some(v) = get(&chosen.props, "translate") {
                let xs = crate::style::value_nums(&ctx.sheet.env, v);
                if xs.len() == 2 {
                    chosen.x += xs[0];
                    chosen.y += xs[1];
                }
            }
            g.labels.push(chosen);
        }
    }
}

// The wire's box, grown by half the stroke plus one.
fn mask_box(g: &LinkGeo) -> Rect {
    let mut x0 = f64::INFINITY;
    let mut y0 = f64::INFINITY;
    let mut x1 = f64::NEG_INFINITY;
    let mut y1 = f64::NEG_INFINITY;
    for &(x, y) in &g.pts {
        x0 = x0.min(x);
        y0 = y0.min(y);
        x1 = x1.max(x);
        y1 = y1.max(y);
    }
    // a wavy wire also swings by its amplitude
    let m = g.style.sw / 2.0 + 1.0 + if g.style.line == "wavy" { 1.4 } else { 0.0 };
    Rect::new(x0 - m, y0 - m, x1 + m, y1 + m)
}

// The mask id hashes the background box and the cut-outs at full
// precision, as `x y w h [(x, y, w, h), ...]` with debug-formatted floats.
fn mask_key(mb: &Rect, cuts: &[(f64, f64, f64, f64)]) -> String {
    format!("{:?} {:?} {:?} {:?} {:?}", mb.x0, mb.y0, mb.w(), mb.h(), cuts)
}

fn compute_masks(geos: &mut [LinkGeo]) {
    let all: Vec<(usize, usize, Rect)> = geos
        .iter()
        .enumerate()
        .flat_map(|(gi, g)| g.labels.iter().enumerate().map(move |(k, lb)| (gi, k, lb.cut())))
        .collect();
    for g in geos.iter_mut() {
        if g.stray || g.pts.len() < 2 {
            continue;
        }
        let mb = mask_box(g);
        g.cuts = all.iter().filter(|(_, _, r)| r.overlaps(&mb)).map(|(gi, k, _)| (*gi, *k)).collect();
    }
}

// ------------------------------------------------------------ geometry out

// The link's bounds for the viewBox: the wire plus its label text boxes.
pub fn extend_bbox(ctx: &Ctx, b: &mut [f64; 4]) {
    for g in &ctx.link_geo {
        for &(x, y) in &g.pts {
            b[0] = b[0].min(x);
            b[1] = b[1].min(y);
            b[2] = b[2].max(x);
            b[3] = b[3].max(y);
        }
        if let Some(c) = &g.curve {
            for &(x, y) in c.iter() {
                b[0] = b[0].min(x);
                b[1] = b[1].min(y);
                b[2] = b[2].max(x);
                b[3] = b[3].max(y);
            }
        }
        for lb in &g.labels {
            b[0] = b[0].min(lb.x - lb.tw / 2.0);
            b[1] = b[1].min(lb.y - lb.fs / 2.0);
            b[2] = b[2].max(lb.x + lb.tw / 2.0);
            b[3] = b[3].max(lb.y + lb.fs / 2.0);
        }
    }
}

fn unitv(p: (f64, f64), q: (f64, f64)) -> (f64, f64) {
    crate::markers::unit((q.0 - p.0, q.1 - p.1))
}

// Wire endpoints after marker pull-back, and the markers themselves.
struct Ends {
    s: (f64, f64),
    e: (f64, f64),
    marks: Vec<String>,
    open: bool,
    any: bool,
}

fn ends_and_markers(g: &LinkGeo, first: (f64, f64), second: (f64, f64), penult: (f64, f64), last: (f64, f64)) -> Ends {
    let sw = g.style.sw;
    let mut marks = Vec::new();
    let mut open = false;
    let mut any = false;
    let mut s = first;
    let mut e = last;
    // a pull-back longer than its end segment is dropped (the wire keeps
    // running to the outline)
    let dist = |a: (f64, f64), b: (f64, f64)| ((a.0 - b.0).powi(2) + (a.1 - b.1).powi(2)).sqrt();
    let pull_of = |m: &Option<String>| m.as_deref().map(|k| crate::markers::marker_full(k, (0.0, 0.0), (1.0, 0.0), sw).pull).unwrap_or(0.0);
    let pe = (pull_of(&g.style.end) - 0.5).max(0.0);
    let ps = (pull_of(&g.style.start) - 0.5).max(0.0);
    let single = g.pts.len() == 2 && g.curve.is_none();
    let drop_e = pe > dist(penult, last) + 1e-9;
    let drop_s = if single { ps > dist(first, second) - if drop_e { 0.0 } else { pe } + 1e-9 } else { ps > dist(first, second) + 1e-9 };
    if let Some(m) = &g.style.start {
        let u = unitv(second, first); // into the start node
        let tip = (first.0 + u.0 * 0.5, first.1 + u.1 * 0.5);
        let mk = crate::markers::marker_full(m, tip, u, sw);
        if mk.pull > 0.0 && !drop_s {
            s = (tip.0 - u.0 * mk.pull, tip.1 - u.1 * mk.pull);
        }
        open |= mk.open;
        any = true;
        marks.extend(mk.elems);
    }
    if let Some(m) = &g.style.end {
        let u = unitv(penult, last);
        let tip = (last.0 + u.0 * 0.5, last.1 + u.1 * 0.5);
        let mk = crate::markers::marker_full(m, tip, u, sw);
        if mk.pull > 0.0 && !drop_e {
            e = (tip.0 - u.0 * mk.pull, tip.1 - u.1 * mk.pull);
        }
        open |= mk.open;
        any = true;
        marks.extend(mk.elems);
    }
    Ends { s, e, marks, open, any }
}

fn cross(a: (f64, f64), b: (f64, f64)) -> f64 {
    a.0 * b.1 - a.1 * b.0
}

// SVG path data for the orthogonal wire with rounded corners.
fn ortho_d(pts: &[(f64, f64)], radii: &[f64]) -> String {
    let mut d = format!("M {} {}", f4(pts[0].0), f4(pts[0].1));
    let n = pts.len();
    for i in 1..n - 1 {
        let p = pts[i - 1];
        let c = pts[i];
        let q = pts[i + 1];
        let u0 = unitv(p, c);
        let u1 = unitv(c, q);
        let r = radii.get(i - 1).copied().unwrap_or(0.0);
        let a = (c.0 - u0.0 * r, c.1 - u0.1 * r);
        let b = (c.0 + u1.0 * r, c.1 + u1.1 * r);
        let sweep = if cross(u0, u1) > 0.0 { 1 } else { 0 };
        d.push_str(&format!(" L {} {} A {} {} 0 0 {} {} {}", f4(a.0), f4(a.1), f4(r), f4(r), sweep, f4(b.0), f4(b.1)));
    }
    d.push_str(&format!(" L {} {}", f4(pts[n - 1].0), f4(pts[n - 1].1)));
    d
}

// Wavy wire: a tapered sine sampled every quarter wave, joined by cubic
// segments whose handles follow the curve's tangent.
fn wave_d(p0: (f64, f64), p1: (f64, f64)) -> String {
    let l = ((p1.0 - p0.0).powi(2) + (p1.1 - p0.1).powi(2)).sqrt();
    let u = unitv(p0, p1);
    let nrm = (-u.1, u.0);
    let amp = 1.4;
    let lam = 12.0;
    let ramp = 6.0;
    let n = ((l / 3.0).round() as usize).max(1);
    let h = l / n as f64;
    let ss = |t: f64| {
        let t = t.clamp(0.0, 1.0);
        3.0 * t * t - 2.0 * t * t * t
    };
    let dss = |t: f64| if t <= 0.0 || t >= 1.0 { 0.0 } else { 6.0 * t - 6.0 * t * t };
    let w = 2.0 * std::f64::consts::PI / lam;
    let mut samples = Vec::new();
    for i in 0..=n {
        let x = i as f64 * h;
        let e1 = ss(x / ramp);
        let e2 = ss((l - x) / ramp);
        let (e, de) = if e1 < e2 { (e1, dss(x / ramp) / ramp) } else { (e2, -dss((l - x) / ramp) / ramp) };
        let y = amp * e * (w * x).sin();
        let dy = amp * (de * (w * x).sin() + e * w * (w * x).cos());
        samples.push((x, y, dy));
    }
    let to = |x: f64, y: f64| (p0.0 + u.0 * x + nrm.0 * y, p0.1 + u.1 * x + nrm.1 * y);
    let mut d = format!("M {} {}", f4(p0.0), f4(p0.1));
    for i in 0..n {
        let (xa, ya, da) = samples[i];
        let (xb, yb, db) = samples[i + 1];
        let ch = ((xb - xa).powi(2) + (yb - ya).powi(2)).sqrt() / 3.0;
        let la = (1.0 + da * da).sqrt();
        let lb = (1.0 + db * db).sqrt();
        let c1 = to(xa + ch / la, ya + da / la * ch);
        let c2 = to(xb - ch / lb, yb - db / lb * ch);
        let e = to(xb, yb);
        d.push_str(&format!(" C {} {} {} {} {} {}", f4(c1.0), f4(c1.1), f4(c2.0), f4(c2.1), f4(e.0), f4(e.1)));
    }
    d
}

// ------------------------------------------------------------ render

// The label rule's own fill / font-size / font-weight values.
fn label_rule_values(ctx: &Ctx) -> Result<(String, String, String), Diag> {
    let mut rprops: Vec<(String, Value)> = Vec::new();
    for d in &ctx.sheet.link_rules {
        set(&mut rprops, &d.name, &d.value);
    }
    let mut vars = Vec::new();
    let fill = match get(&rprops, "color").and_then(|v| single_term(v).map(|t| (t.clone(), v.span))) {
        Some((t, sp)) => color_css(&t, &mut vars, sp)?,
        None => "currentColor".to_string(),
    };
    let fs = format!("{}px", f4(num_of(ctx, &rprops, "font-size").unwrap_or(11.0)));
    let fw = match get(&rprops, "font-weight") {
        Some(v) => weight_css(v, &mut vars, v.span)?,
        None => "var(--lini-link-font-weight)".to_string(),
    };
    Ok((fill, fs, fw))
}

fn css_join(d: &[(String, String)]) -> String {
    d.iter().map(|(k, v)| format!("{}: {}", k, v)).collect::<Vec<_>>().join("; ")
}

fn stray_svg(ctx: &Ctx, g: &LinkGeo, s: &mut String, out: &mut Out) {
    let l = &ctx.links[g.li];
    use_var(&mut out.vars, "stray");
    use_var(&mut out.vars, "fill");
    let a = abs_rect(ctx, l.from);
    let b = abs_rect(ctx, l.to);
    let (p, q) = stray_line(&a, &b);
    let m = ((p.0 + q.0) / 2.0, (p.1 + q.1) / 2.0);
    s.push_str(&format!(
        "    <g class=\"lini-stray\" data-from=\"{}\" data-to=\"{}\">\n",
        xml_escape(&path_of(ctx, l.from)),
        xml_escape(&path_of(ctx, l.to))
    ));
    s.push_str(&format!(
        "      <path d=\"M {} {} L {} {}\" fill=\"none\" stroke=\"var(--lini-stray)\" stroke-width=\"1.5\" stroke-dasharray=\"6,4\"/>\n",
        f4(p.0),
        f4(p.1),
        f4(q.0),
        f4(q.1)
    ));
    s.push_str(&format!(
        "      <path d=\"M {} {} L {} {} L {} {} Z\" fill=\"var(--lini-fill)\" stroke=\"var(--lini-stray)\" stroke-width=\"1.5\" stroke-linejoin=\"round\"/>\n",
        f4(m.0),
        f4(m.1 - 6.5),
        f4(m.0 + 7.0),
        f4(m.1 + 5.5),
        f4(m.0 - 7.0),
        f4(m.1 + 5.5)
    ));
    s.push_str(&format!(
        "      <path d=\"M {} {} L {} {}\" stroke=\"var(--lini-stray)\" stroke-width=\"1.6\" stroke-linecap=\"round\"/>\n",
        f4(m.0),
        f4(m.1 - 2.5),
        f4(m.0),
        f4(m.1 + 1.0)
    ));
    s.push_str(&format!("      <circle cx=\"{}\" cy=\"{}\" r=\"0.9\" fill=\"var(--lini-stray)\"/>\n", f4(m.0), f4(m.1 + 3.6)));
    s.push_str("    </g>\n");
}

// The straight line between two boxes, clipped to their outlines.
pub fn stray_line(a: &Rect, b: &Rect) -> ((f64, f64), (f64, f64)) {
    let c0 = (a.cx(), a.cy());
    let c1 = (b.cx(), b.cy());
    (clip_out(a, c0, c1), clip_out(b, c1, c0))
}

fn clip_out(r: &Rect, c: (f64, f64), toward: (f64, f64)) -> (f64, f64) {
    let dx = toward.0 - c.0;
    let dy = toward.1 - c.1;
    let mut t = f64::INFINITY;
    if dx.abs() > 1e-12 {
        t = t.min((r.w() / 2.0) / dx.abs());
    }
    if dy.abs() > 1e-12 {
        t = t.min((r.h() / 2.0) / dy.abs());
    }
    if !t.is_finite() {
        return c;
    }
    (c.0 + dx * t, c.1 + dy * t)
}

struct RuleSet {
    stroke: Option<Value>,
    sw: f64,
}

fn rule_set(ctx: &Ctx) -> RuleSet {
    let mut props: Vec<(String, Value)> = Vec::new();
    for d in &ctx.sheet.link_rules {
        set(&mut props, &d.name, &d.value);
    }
    RuleSet { stroke: get(&props, "stroke").cloned(), sw: num_of(ctx, &props, "stroke-width").unwrap_or(2.0) }
}

pub fn render(ctx: &Ctx, out: &mut Out) -> Result<String, Diag> {
    let geos = &ctx.link_geo;
    if geos.is_empty() {
        return Ok("  <g class=\"lini-links\"/>\n".to_string());
    }
    let rules = rule_set(ctx);
    let mut s = String::from("  <g class=\"lini-links\">\n");
    let mut any_link = false;
    let mut any_label = false;
    let mut any_mask = false;
    let mut any_marker = false;
    let mut any_open = false;
    let mut dashed = false;
    let mut dotted = false;
    let mut class_marker: Vec<String> = Vec::new();
    for (gi, g) in geos.iter().enumerate() {
        let l = &ctx.links[g.li];
        if g.stray {
            stray_svg(ctx, g, &mut s, out);
            continue;
        }
        any_link = true;
        let st = &g.style;
        let mut cls = vec!["lini-link".to_string()];
        match st.line.as_str() {
            "dashed" => {
                cls.push("lini-link-dashed".into());
                dashed = true;
            }
            "dotted" => {
                cls.push("lini-link-dotted".into());
                dotted = true;
            }
            _ => {}
        }
        for c in &l.classes {
            cls.push(format!("lini-style-{}", c));
            if !out.used_classes.contains(c) {
                out.used_classes.push(c.clone());
            }
        }
        // inline style: own stroke decls
        let mut inline: Vec<(String, String)> = Vec::new();
        let mut tmpvars = Vec::new();
        for k in ["stroke", "stroke-width", "opacity"] {
            if let Some(v) = get(&st.own, k) {
                match k {
                    "stroke" => {
                        if let Some(t) = single_term(v) {
                            inline.push((k.into(), color_css(t, &mut tmpvars, v.span)?));
                        }
                    }
                    _ => {
                        if let Some(x) = value_num(&ctx.sheet.env, v) {
                            inline.push((k.into(), f4(x)));
                        }
                    }
                }
            }
        }
        if matches!(st.line.as_str(), "dashed" | "dotted") && (get(&st.own, "stroke-width").is_some() || get(&st.own, "stroke-style").is_some()) {
            if let (Some(dv), Some(rv)) = (dasharray(&st.line, st.sw), dasharray(&st.line, rules.sw)) {
                if dv != rv {
                    inline.push(("stroke-dasharray".into(), dv));
                }
            }
        }
        // a class's dashes were drawn for its own stroke width (else 0)
        if get(&st.own, "stroke-style").is_none() && !inline.iter().any(|(k, _)| k == "stroke-dasharray") {
            if let (Some(shown), Some(dv)) = (crate::scoped::class_dash(ctx, &l.classes), dasharray(&st.line, st.sw)) {
                if dv != shown {
                    inline.push(("stroke-dasharray".into(), dv));
                }
            }
        }
        for v in tmpvars {
            use_var(&mut out.vars, &v);
        }
        let mut head = format!("    <g class=\"{}\"", cls.join(" "));
        if !inline.is_empty() {
            head.push_str(&format!(" style=\"{}\"", xml_escape(&css_join(&inline))));
        }
        head.push_str(&format!(
            " data-from=\"{}\" data-to=\"{}\">\n",
            xml_escape(&path_of(ctx, l.from)),
            xml_escape(&path_of(ctx, l.to))
        ));
        s.push_str(&head);
        // geometry
        let pts = &g.pts;
        let n = pts.len();
        let (first, second, penult, last) = if let Some(c) = &g.curve {
            (pts[0], c[0], c[3], pts[n - 1])
        } else {
            (pts[0], pts[1], pts[n - 2], pts[n - 1])
        };
        let ends = ends_and_markers(g, first, second, penult, last);
        any_marker |= ends.any;
        any_open |= ends.open;
        let d = if let Some(c) = &g.curve {
            format!(
                "M {} {} L {} {} C {} {} {} {} {} {} L {} {}",
                f4(ends.s.0),
                f4(ends.s.1),
                f4(c[0].0),
                f4(c[0].1),
                f4(c[1].0),
                f4(c[1].1),
                f4(c[2].0),
                f4(c[2].1),
                f4(c[3].0),
                f4(c[3].1),
                f4(ends.e.0),
                f4(ends.e.1)
            )
        } else {
            let mut wp = pts.clone();
            wp[0] = ends.s;
            wp[n - 1] = ends.e;
            if st.line == "wavy" && n == 2 {
                wave_d(wp[0], wp[1])
            } else {
                ortho_d(&wp, &g.radii)
            }
        };
        let mask_attr = if !g.cuts.is_empty() {
            any_mask = true;
            let mb = mask_box(g);
            let mut inner = format!(
                "<rect class=\"lini-cut-bg\" x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\"/>",
                f4(mb.x0),
                f4(mb.y0),
                f4(mb.w()),
                f4(mb.h())
            );
            for &(ggi, k) in &g.cuts {
                let (cx, cy, cw, ch) = geos[ggi].labels[k].cut_exact();
                inner.push_str(&format!(
                    "<rect class=\"lini-cut\" x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\"/>",
                    f4(cx),
                    f4(cy),
                    f4(cw),
                    f4(ch)
                ));
            }
            if std::env::var("LINI_DBG_MASK").is_ok() {
                let (mut x0, mut y0, mut x1, mut y1) = (f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY);
                for &(x, y) in &g.pts {
                    x0 = x0.min(x);
                    y0 = y0.min(y);
                    x1 = x1.max(x);
                    y1 = y1.max(y);
                }
                let mut v = format!("MASK {:?} {:?} {:?} {:?} {:?} {}", x0, y0, x1, y1, g.style.sw, st.line == "wavy");
                if std::env::var("LINI_DBG_PTS").is_ok() {
                    eprintln!("PTS {:?}", g.pts);
                }
                for &(ggi, k) in &g.cuts {
                    let lb = &geos[ggi].labels[k];
                    v.push_str(&format!(" | {:?} {:?} {:?} {:?} {:?} {:?}", lb.x, lb.y, lb.tw, lb.fs, lb.upem, lb.units));
                }
                eprintln!("{}", v);
            }
            let exact: Vec<(f64, f64, f64, f64)> = g.cuts.iter().map(|&(ggi, k)| geos[ggi].labels[k].cut_exact()).collect();
            let id = format!("lini-label-cut-{}", hash8(&mask_key(&mb, &exact)));
            s.push_str(&format!(
                "      <mask id=\"{}\" maskUnits=\"userSpaceOnUse\" x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\">{}</mask>\n",
                id,
                f4(mb.x0),
                f4(mb.y0),
                f4(mb.w()),
                f4(mb.h()),
                inner
            ));
            format!(" mask=\"url(#{})\"", id)
        } else {
            String::new()
        };
        let _ = gi;
        s.push_str(&format!("      <path d=\"{}\"{}/>\n", d, mask_attr));
        // markers, filled ones take the link's own stroke colour
        let own_stroke = get(&st.own, "stroke").and_then(|v| single_term(v).map(|t| (t.clone(), v.span)));
        for m in &ends.marks {
            let mut m = m.clone();
            if !m.contains("lini-marker-open") {
                if let Some((t, sp)) = &own_stroke {
                    let mut tmp = Vec::new();
                    let col = color_css(t, &mut tmp, *sp)?;
                    m = m.replacen("/>", &format!(" style=\"fill: {}\"/>", col), 1);
                }
            }
            s.push_str(&format!("      {}\n", m));
        }
        for c in &l.classes {
            if let Some(cr) = ctx.sheet.class(c) {
                if cr.decls.iter().any(|d| d.name == "stroke") && ends.any && !class_marker.contains(c) {
                    class_marker.push(c.clone());
                }
            }
        }
        // labels
        for lb in &g.labels {
            any_label = true;
            let mut lc = vec!["lini-link-label".to_string()];
            // label classes are inlined; they add no stylesheet rule
            for c in &lb.classes {
                lc.push(format!("lini-style-{}", c));
            }
            let mut vars = Vec::new();
            let mut ls: Vec<(String, String)> = Vec::new();
            // only what differs from the label rule
            let (rule_fill, rule_fs, rule_fw) = label_rule_values(ctx)?;
            if let Some(v) = get(&lb.props, "color") {
                if let Some(t) = single_term(v) {
                    let c = color_css(t, &mut vars, v.span)?;
                    if c != rule_fill {
                        ls.push(("fill".into(), c));
                    }
                }
            }
            if let Some(v) = get(&lb.props, "font-size") {
                if let Some(x) = value_num(&ctx.sheet.env, v) {
                    let fs = format!("{}px", f4(x));
                    if fs != rule_fs {
                        ls.push(("font-size".into(), fs));
                    }
                }
            }
            if let Some(v) = get(&lb.props, "font-weight") {
                let w = weight_css(v, &mut vars, v.span)?;
                if w != rule_fw {
                    ls.push(("font-weight".into(), w));
                }
            }
            // further text styling the label carries itself
            let mut more: Vec<(String, Value)> = Vec::new();
            for k in ["font-style", "text-decoration", "text-shadow"] {
                if let Some(v) = get(&lb.props, k) {
                    more.push((k.to_string(), v.clone()));
                }
            }
            if !more.is_empty() {
                ls.extend(crate::render::css_decls(ctx, &more, &mut vars, 2.0, true)?);
            }
            for v in vars {
                use_var(&mut out.vars, &v);
            }
            let style = if ls.is_empty() { String::new() } else { format!(" style=\"{}\"", xml_escape(&css_join(&ls))) };
            let turn = match get(&lb.props, "rotate").and_then(|v| value_num(&ctx.sheet.env, v)) {
                Some(a) if a != 0.0 => format!(" transform=\"rotate({} {} {})\"", f4(a), f4(lb.x), f4(lb.y)),
                _ => String::new(),
            };
            crate::outline::note(lb.x);
            crate::outline::note(lb.y);
            s.push_str(&format!(
                "      <text class=\"{}\" x=\"{}\" y=\"{}\" dy=\"0.358em\"{}{}>{}</text>\n",
                lc.join(" "),
                f4(lb.x),
                f4(lb.y),
                style,
                turn,
                xml_escape(&lb.text)
            ));
        }
        s.push_str("    </g>\n");
    }
    s.push_str("  </g>\n");
    // stylesheet
    if any_link {
        if !ctx.sheet.link_rules.iter().any(|d| d.name == "font-weight") {
            use_var(&mut out.vars, "link-font-weight");
        }
        let mut vars = Vec::new();
        let stroke = match &rules.stroke {
            Some(v) => match single_term(v) {
                Some(t) => color_css(t, &mut vars, v.span)?,
                None => "var(--lini-stroke)".to_string(),
            },
            None => {
                use_var(&mut vars, "stroke");
                "var(--lini-stroke)".to_string()
            }
        };
        let mut rprops: Vec<(String, Value)> = Vec::new();
        for d in &ctx.sheet.link_rules {
            set(&mut rprops, &d.name, &d.value);
        }
        let style = ident_prop(&rprops, "stroke-style").unwrap_or_else(|| "solid".into());
        let dash = dasharray(&style, rules.sw).unwrap_or_else(|| "none".into());
        let mut base = format!("fill: none; stroke: {}; stroke-width: {}; stroke-dasharray: {}", stroke, f4(rules.sw), dash);
        let mut extra: Vec<(String, Value)> = Vec::new();
        for k in ["fill", "opacity"] {
            if let Some(v) = get(&rprops, k) {
                extra.push((k.to_string(), v.clone()));
            }
        }
        let ed = crate::render::css_decls(ctx, &extra, &mut vars, rules.sw, false)?;
        if !ed.is_empty() {
            base.push_str("; ");
            base.push_str(&css_join(&ed));
        }
        out.extra_rules.push(("link".into(), format!(".lini-link {{ {}; }}", base)));
        if dashed {
            out.extra_rules.push(("link-dashed".into(), format!(".lini-link-dashed {{ stroke-dasharray: {}; }}", dasharray("dashed", rules.sw).unwrap())));
        }
        if dotted {
            out.extra_rules.push(("link-dotted".into(), format!(".lini-link-dotted {{ stroke-dasharray: {}; }}", dasharray("dotted", rules.sw).unwrap())));
        }
        if any_label {
            let fill = match get(&rprops, "color").and_then(|v| single_term(v).map(|t| (t.clone(), v.span))) {
                Some((t, sp)) => color_css(&t, &mut vars, sp)?,
                None => "currentColor".to_string(),
            };
            let fs = num_of(ctx, &rprops, "font-size").unwrap_or(11.0);
            let fw = match get(&rprops, "font-weight") {
                Some(v) => weight_css(v, &mut vars, v.span)?,
                None => "var(--lini-link-font-weight)".to_string(),
            };
            out.extra_rules.push((
                "link-label".into(),
                format!(".lini-link-label {{ fill: {}; stroke: none; text-anchor: middle; font-size: {}px; font-weight: {}; }}", fill, f4(fs), fw),
            ));
        }
        if any_mask {
            out.extra_rules.push(("cut-bg".into(), ".lini-cut-bg { fill: white; stroke: none; }".to_string()));
            out.extra_rules.push(("cut".into(), ".lini-cut { fill: black; stroke: none; }".to_string()));
        }
        if any_marker {
            out.markers = true;
            if rules.stroke.is_some() {
                out.extra_rules.push(("link-marker".into(), format!(".lini-link .lini-marker {{ fill: {}; }}", stroke)));
            }
        }
        if any_open {
            out.extra_rules.push((
                "marker-open".into(),
                ".lini-marker.lini-marker-open { fill: none; stroke: inherit; stroke-linecap: round; stroke-dasharray: none; }".to_string(),
            ));
        }
        // every class in use that strokes paints markers inside it too
        let _ = &class_marker;
        if any_marker || out.markers {
            for (k, cr) in ctx.sheet.classes.iter().enumerate() {
                if !out.used_classes.contains(&cr.name) {
                    continue;
                }
                if let Some(d) = cr.decls.iter().rev().find(|d| d.name == "stroke") {
                    if let Some(t) = single_term(&d.value) {
                        let col = color_css(t, &mut vars, d.value.span)?;
                        out.extra_rules.push((format!("@class:{:04}m", k), format!(".lini-style-{} .lini-marker {{ fill: {}; }}", cr.name, col)));
                    }
                }
            }
        }
        for v in vars {
            use_var(&mut out.vars, &v);
        }
    } else {
        // only stray links: the base rule still applies
        let mut vars = Vec::new();
        let stroke = match &rules.stroke {
            Some(v) => match single_term(v) {
                Some(t) => color_css(t, &mut vars, v.span)?,
                None => "var(--lini-stroke)".to_string(),
            },
            None => {
                use_var(&mut vars, "stroke");
                "var(--lini-stroke)".to_string()
            }
        };
        out.extra_rules.push(("link".into(), format!(".lini-link {{ fill: none; stroke: {}; stroke-width: {}; stroke-dasharray: none; }}", stroke, f4(rules.sw))));
        for v in vars {
            use_var(&mut out.vars, &v);
        }
    }
    let _ = Term::Ident(String::new(), Default::default());
    Ok(s)
}
