// Schematics: components (pin rows and columns, stubs, numbers, value and
// reference labels), parts (drawn symbols with pin stations), net labels and
// symbols, and — inside a `layout: schematic` scope — the wires: chains pass
// through two-pin parts, text ends become net labels, and every part and
// label takes the pose the wiring gives it.

use super::lower::{err, Cx, R};
use super::out::{Item, ONode};
use super::sch_geo::{self, PartGeo};
use super::syntax::{Decl, Endpoint, Link, Node, Stmt};
use crate::diag::{Diag, Span};
use crate::format::parse::render_number;
use std::collections::HashMap;

// ------------------------------------------------------------------ poses
#[derive(Clone, Copy, Debug, PartialEq, Default)]
pub struct Pose {
    pub rot: u32,              // 0, 90, 180, 270 (clockwise)
    pub mirror: Option<char>, // 'x' (about the x-axis) or 'y'
}

impl Pose {
    pub fn is_zero(&self) -> bool {
        self.rot == 0 && self.mirror.is_none()
    }
    pub fn classes(&self) -> Vec<String> {
        let mut v = Vec::new();
        if self.rot != 0 {
            v.push(format!("lini-pose-{}", self.rot));
        }
        if let Some(m) = self.mirror {
            v.push(format!("lini-mirror-{}", m));
        }
        v
    }
    pub fn vertical(&self) -> bool {
        self.rot == 90 || self.rot == 270
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Dir {
    L,
    R,
    U,
    D,
}

impl Dir {
    pub fn opposite(self) -> Dir {
        match self {
            Dir::L => Dir::R,
            Dir::R => Dir::L,
            Dir::U => Dir::D,
            Dir::D => Dir::U,
        }
    }
    pub fn horizontal(self) -> bool {
        matches!(self, Dir::L | Dir::R)
    }
    fn of_side(s: &str) -> Option<Dir> {
        Some(match s {
            "left" => Dir::L,
            "right" => Dir::R,
            "top" => Dir::U,
            "bottom" => Dir::D,
            _ => return None,
        })
    }
    fn of_vec(dx: f64, dy: f64) -> Dir {
        if dx.abs() >= dy.abs() {
            if dx < 0.0 {
                Dir::L
            } else {
                Dir::R
            }
        } else if dy < 0.0 {
            Dir::U
        } else {
            Dir::D
        }
    }
}

fn num(v: f64) -> String {
    let r = (v * 10000.0).round() / 10000.0;
    let r = if r == 0.0 { 0.0 } else { r };
    render_number(r)
}

// a point of the symbol's frame (w x h) under the pose: mirror first, then
// the clockwise turn
fn map_pt(x: f64, y: f64, w: f64, h: f64, p: Pose) -> (f64, f64) {
    let (mut x, mut y) = (x, y);
    match p.mirror {
        Some('x') => y = h - y,
        Some('y') => x = w - x,
        _ => {}
    }
    match p.rot {
        90 => (h - y, x),
        180 => (w - x, h - y),
        270 => (y, w - x),
        _ => (x, y),
    }
}

pub fn map_vec(dx: f64, dy: f64, p: Pose) -> (f64, f64) {
    let (mut dx, mut dy) = (dx, dy);
    match p.mirror {
        Some('x') => dy = -dy,
        Some('y') => dx = -dx,
        _ => {}
    }
    match p.rot {
        90 => (-dy, dx),
        180 => (-dx, -dy),
        270 => (dy, -dx),
        _ => (dx, dy),
    }
}

// transform an SVG path ("M 0 0 M w h …" frame first)
pub fn map_path(path: &str, p: Pose) -> String {
    if p.is_zero() {
        return path.to_string();
    }
    let toks: Vec<&str> = path.split_whitespace().collect();
    // the frame: M 0 0 M w h
    let w: f64 = toks.get(4).and_then(|s| s.parse().ok()).unwrap_or(0.0);
    let h: f64 = toks.get(5).and_then(|s| s.parse().ok()).unwrap_or(0.0);
    let mut out: Vec<String> = Vec::new();
    let mut i = 0;
    let f = |s: &str| s.parse::<f64>().unwrap_or(0.0);
    while i < toks.len() {
        let t = toks[i];
        match t {
            "M" | "L" if i + 2 < toks.len() + 0 && i + 2 <= toks.len() - 1 => {
                let (x, y) = map_pt(f(toks[i + 1]), f(toks[i + 2]), w, h, p);
                out.push(t.to_string());
                out.push(num(x));
                out.push(num(y));
                i += 3;
            }
            "Q" if i + 4 < toks.len() => {
                let (x1, y1) = map_pt(f(toks[i + 1]), f(toks[i + 2]), w, h, p);
                let (x, y) = map_pt(f(toks[i + 3]), f(toks[i + 4]), w, h, p);
                out.push("Q".into());
                out.push(num(x1));
                out.push(num(y1));
                out.push(num(x));
                out.push(num(y));
                i += 5;
            }
            "A" if i + 7 < toks.len() => {
                let rx = toks[i + 1];
                let ry = toks[i + 2];
                let mut rot = f(toks[i + 3]);
                let large = toks[i + 4];
                let mut sweep = toks[i + 5].to_string();
                if p.mirror.is_some() {
                    rot = -rot;
                    sweep = if sweep == "1" { "0".into() } else { "1".into() };
                }
                rot += p.rot as f64;
                let rot = ((rot % 360.0) + 360.0) % 360.0;
                let (x, y) = map_pt(f(toks[i + 6]), f(toks[i + 7]), w, h, p);
                out.push("A".into());
                out.push(rx.to_string());
                out.push(ry.to_string());
                out.push(num(rot));
                out.push(large.to_string());
                out.push(sweep);
                out.push(num(x));
                out.push(num(y));
                i += 8;
            }
            _ => {
                out.push(t.to_string());
                i += 1;
            }
        }
    }
    out.join(" ")
}

fn own(n: &[Decl], name: &str) -> Option<String> {
    n.iter().rev().find(|d| d.name == name).and_then(|d| d.first().map(|s| s.to_string()))
}

// a property as it applies to a node: written on it, else from its defines
// (most derived first), else its types' defaults
pub fn prop_decl<'d>(cx: &'d Cx, style: &'d [Decl], chain: &[String], name: &str) -> Option<&'d Decl> {
    if let Some(d) = style.iter().rev().find(|d| d.name == name) {
        return Some(d);
    }
    for t in chain {
        if let Some(def) = cx.define(t) {
            if let Some(d) = def.decls.iter().rev().find(|d| d.name == name) {
                return Some(d);
            }
        }
    }
    None
}

pub fn prop(cx: &Cx, style: &[Decl], chain: &[String], name: &str) -> Option<String> {
    if let Some(d) = prop_decl(cx, style, chain, name) {
        return d.first().map(|s| s.to_string());
    }
    for t in chain {
        if cx.define(t).is_none() {
            if let Some(td) = crate::types::find(t) {
                if let Some(v) = own(&Decl::list(td.defaults), name) {
                    return Some(v);
                }
            }
        }
    }
    None
}

// a node of its own type (a define keeps its class), as a `base` otherwise
fn typed_as(cx: &mut Cx, n: &Node, base: &str) -> ONode {
    let ty = n.ty.clone().unwrap_or_else(|| base.to_string());
    match cx.chain(&ty) {
        Some((prim, chain)) if chain.iter().any(|c| c == base) => {
            let mut o = ONode::new(&prim);
            for t in &chain {
                cx.mark(t);
                o.classes.push(format!("lini-{}", t));
            }
            o
        }
        _ => cx.typed(base),
    }
}

// a statement's node of a type (or a define on it)
fn node_is<'s>(cx: &Cx, s: &'s Stmt, ty: &str) -> Option<&'s Node> {
    match s {
        Stmt::Node(c) => {
            let t = c.ty.clone().unwrap_or_else(|| "box".into());
            match cx.chain(&t) {
                Some((_, ch)) if ch.iter().any(|x| x == ty) => Some(c),
                _ => None,
            }
        }
        _ => None,
    }
}

fn chain_of(cx: &Cx, n: &Node) -> Vec<String> {
    let t = n.ty.clone().unwrap_or_else(|| "box".into());
    cx.chain(&t).map(|c| c.1).unwrap_or_default()
}

// a pose its defines set is written off on the instance (the rule keeps it)
fn cancel_define_pose(cx: &Cx, o: &mut ONode, chain: &[String]) {
    let set = |name: &str| chain.iter().any(|t| cx.define(t).map_or(false, |d| d.decls.iter().any(|d| d.name == name)));
    if set("rotate") {
        o.decls.push(Decl::val("rotate", "0"));
    }
    if set("mirror") {
        o.decls.push(Decl::val("mirror", "none"));
    }
}

// the pose written on a node or its defines (rotate:, mirror:), validated
pub fn written_pose(cx: &Cx, n: &Node, chain: &[String]) -> R<Pose> {
    let mut p = Pose::default();
    if let Some(r) = prop(cx, &n.style, chain, "rotate") {
        p.rot = match r.as_str() {
            "0" => 0,
            "90" => 90,
            "180" => 180,
            "270" => 270,
            _ => return Err(err("a schematic part rotates in 90° steps — 0, 90, 180, or 270", n.span)),
        };
    }
    if let Some(m) = prop(cx, &n.style, chain, "mirror") {
        p.mirror = match m.as_str() {
            "x-axis" => Some('x'),
            "y-axis" => Some('y'),
            "none" => None,
            _ => return Err(err("a schematic part mirrors about its own axis — x-axis, y-axis, or none", n.span)),
        };
    }
    Ok(p)
}

pub fn is_part(chain: &[String]) -> bool {
    chain.iter().any(|c| sch_geo::part_types().any(|t| t == c))
}

pub fn part_type(chain: &[String]) -> Option<String> {
    chain.iter().find(|c| sch_geo::part_types().any(|t| t == c.as_str())).cloned()
}

pub fn is_label(chain: &[String]) -> bool {
    chain.iter().any(|c| c == "label")
}

pub fn is_component(chain: &[String]) -> bool {
    chain.iter().any(|c| c == "component") && !is_part(chain)
}

// the prefix a reference designator counts with
fn prefix(cx: &Cx, n: &Node, chain: &[String]) -> String {
    if let Some(p) = n.style.iter().rev().find(|d| d.name == "prefix") {
        if let Some(s) = p.first().and_then(super::page::unquote) {
            return s;
        }
    }
    for t in chain {
        if let Some(d) = cx.define(t) {
            if let Some(p) = d.decls.iter().rev().find(|d| d.name == "prefix") {
                if let Some(s) = p.first().and_then(super::page::unquote) {
                    return s;
                }
            }
        }
        if let Some(td) = crate::types::find(t) {
            for d in Decl::list(td.defaults) {
                if d.name == "prefix" {
                    if let Some(s) = d.first().and_then(super::page::unquote) {
                        return s;
                    }
                }
            }
        }
        if sch_geo::part_types().any(|p| p == t.as_str()) && t != "opamp" {
            return t.clone();
        }
    }
    "U".to_string()
}

fn ref_text(cx: &mut Cx, n: &Node, chain: &[String]) -> String {
    match &n.id {
        Some(id) => id.clone(),
        None => {
            let p = prefix(cx, n, chain);
            let k = cx.sch_counter(&p);
            format!("{}{}", p, k)
        }
    }
}

fn block_with(cx: &mut Cx, ty: &str, decls: &str, text: Option<&str>) -> Item {
    let mut b = cx.typed(ty);
    b.decls = Decl::list(decls);
    if let Some(t) = text {
        b.children.push(Cx::text_item(t));
    }
    Item::Node(b)
}

// -------------------------------------------------------------- components
struct Slot {
    pin: Option<Node>, // None: a space
    space: Option<Node>,
    side: Option<String>, // explicit and valid
    generated: bool,
}


// the pose is spent on classes
fn drop_pose(o: &mut ONode) {
    o.decls.retain(|d| d.name != "rotate" && d.name != "mirror");
}

// the slots a `|space|` takes: a whole number of one or more (one otherwise)
fn space_span(cx: &Cx, sp: &Node) -> f64 {
    let ch = chain_of(cx, sp);
    let d = match prop_decl(cx, &sp.style, &ch, "span") {
        Some(d) => d,
        None => return 1.0,
    };
    match d.groups.as_slice() {
        [g] if g.len() == 1 => match g[0].parse::<f64>() {
            Ok(v) if v.trunc() >= 1.0 => v.trunc(),
            _ => 1.0,
        },
        _ => 1.0,
    }
}

pub fn component(cx: &mut Cx, n: &Node, mut o: ONode, chain: &[String]) -> R<ONode> {
    if let Some(f) = cx.stack.last_mut() {
        f.plan_breaks = true;
    }
    let mut pose = written_pose(cx, n, chain)?;
    if prop(cx, &n.style, chain, "rotate").is_none() {
        if let Some(id) = &n.id {
            if let Some(p) = cx.sch_pose(id) {
                pose.rot = p.rot;
            }
        }
    }
    drop_pose(&mut o);
    cancel_define_pose(cx, &mut o, chain);
    o.classes.extend(pose.classes());
    let r = ref_text(cx, n, chain);
    for d in Decl::list("direction: column; gap: 0;") {
        if !o.decls.iter().any(|x| x.name == d.name) {
            o.decls.push(d);
        }
    }
    // the pins: generated (a connector's `pins: N`) then the children
    let mut slots: Vec<Slot> = Vec::new();
    if chain.iter().any(|c| c == "J") {
        if let Some(k) = prop(cx, &n.style, chain, "pins").and_then(|s| s.parse::<f64>().ok()) {
            for i in 1..=(k.max(0.0) as usize) {
                let pn = Node {
                    ty: Some("pin".into()),
                    id: Some(format!("p{}", i)),
                    label: None,
                    classes: vec![],
                    style: vec![Decl::val("number", &i.to_string()), Decl::val("side", "left")],
                    children: None,
                    span: n.span,
                    head_span: n.span,
                    ty_span: n.span,
                };
                slots.push(Slot { pin: Some(pn), space: None, side: Some("left".into()), generated: true });
            }
        }
    }
    let mut extra: Vec<&Stmt> = Vec::new();
    for s in n.children.as_deref().unwrap_or(&[]) {
        if let Some(c) = node_is(cx, s, "pin") {
            let side = prop(cx, &c.style, &chain_of(cx, c), "side").filter(|s| Dir::of_side(s).is_some());
            slots.push(Slot { pin: Some(c.clone()), space: None, side, generated: false });
        } else if let Some(c) = node_is(cx, s, "space") {
            slots.push(Slot { pin: None, space: Some(c.clone()), side: None, generated: false });
        } else {
            extra.push(s);
        }
    }
    // auto pins split left / right, spaces ride with their pin
    let autos: Vec<usize> = (0..slots.len()).filter(|&i| slots[i].pin.is_some() && slots[i].side.is_none()).collect();
    let half = (autos.len() + 1) / 2;
    let mut sides: Vec<String> = vec![String::new(); slots.len()];
    for (k, &i) in autos.iter().enumerate() {
        sides[i] = if k < half { "left".into() } else { "right".into() };
    }
    for i in 0..slots.len() {
        if let Some(s) = &slots[i].side {
            sides[i] = s.clone();
        }
    }
    for i in 0..slots.len() {
        if slots[i].pin.is_none() {
            let prev = (0..i).rev().find(|&j| slots[j].pin.is_some()).map(|j| sides[j].clone());
            let next = (i + 1..slots.len()).find(|&j| slots[j].pin.is_some()).map(|j| sides[j].clone());
            // a space without a pin to ride with is dropped
            sides[i] = prev.or(next).unwrap_or_default();
        }
    }
    // group by side (left/right top→bottom, top/bottom left→right), then pose
    let mut by: HashMap<&str, Vec<usize>> = HashMap::new();
    for (i, s) in sides.iter().enumerate() {
        if s.is_empty() {
            continue;
        }
        by.entry(match s.as_str() {
            "right" => "right",
            "top" => "top",
            "bottom" => "bottom",
            _ => "left",
        })
        .or_default()
        .push(i);
    }
    let get = |by: &HashMap<&str, Vec<usize>>, k: &str| by.get(k).cloned().unwrap_or_default();
    let (mut left, mut right, mut top, mut bottom) = (get(&by, "left"), get(&by, "right"), get(&by, "top"), get(&by, "bottom"));
    let rev = |v: &Vec<usize>| v.iter().rev().cloned().collect::<Vec<usize>>();
    match pose.mirror {
        Some('x') => {
            let (t, b) = (top.clone(), bottom.clone());
            top = b;
            bottom = t;
            left = rev(&left);
            right = rev(&right);
        }
        Some('y') => {
            let (l, r) = (left.clone(), right.clone());
            left = r;
            right = l;
            top = rev(&top);
            bottom = rev(&bottom);
        }
        _ => {}
    }
    for _ in 0..(pose.rot / 90) {
        let (l, r, t, b) = (left.clone(), right.clone(), top.clone(), bottom.clone());
        top = rev(&l);
        right = t;
        bottom = rev(&r);
        left = b;
    }
    let mut children: Vec<Item> = Vec::new();
    let connector = chain.iter().any(|c| c == "J");
    let lower_pins = |cx: &mut Cx, idx: &[usize], side: &str| -> R<Vec<Item>> {
        let mut v = Vec::new();
        for &i in idx {
            let s = &slots[i];
            if let Some(sp) = &s.space {
                let mut b = typed_as(cx, sp, "space");
                b.id = sp.id.clone();
                b.classes.extend(sp.classes.iter().cloned());
                b.decls = sp.style.clone();
                let k = space_span(cx, sp);
                if k != 1.0 {
                    let along = if side == "left" || side == "right" { "height" } else { "width" };
                    b.decls.push(Decl::val(along, &num(20.0 * k)));
                }
                v.push(Item::Node(b));
                continue;
            }
            let pn = s.pin.as_ref().unwrap();
            // a connector's pins go unnamed
            v.push(pin_node(cx, pn, side, s.side.is_some() || s.generated, s.generated || connector)?);
        }
        Ok(v)
    };
    let spans: Vec<f64> = slots.iter().map(|s| s.space.as_ref().map_or(1.0, |sp| space_span(cx, sp))).collect();
    let slots_of = |idx: &[usize]| -> f64 { idx.iter().map(|&i| spans[i]).sum() };
    let middle = !left.is_empty() || !right.is_empty();
    if !top.is_empty() {
        let even = slots_of(&top) % 2.0 == 0.0;
        let mut row = cx.typed("row");
        row.decls = Decl::list(&format!(
            "gap: 0; align: start;{} height: 20;",
            if even { " padding: 0 20 0 0;" } else { "" }
        ));
        row.children = lower_pins(cx, &top, "top")?;
        children.push(Item::Node(row));
    } else if middle && !bottom.is_empty() {
        let mut row = cx.typed("row");
        row.decls = Decl::list("height: 20;");
        children.push(Item::Node(row));
    }
    if middle {
        let mut cols = Vec::new();
        for (idx, side, align) in [(&left, "left", "start"), (&right, "right", "end")] {
            if idx.is_empty() {
                continue;
            }
            let even = slots_of(idx) % 2.0 == 0.0;
            let mut col = cx.typed("column");
            col.decls = Decl::list(&format!(
                "gap: 0; align: {};{}",
                align,
                if even { " padding: 0 0 20 0;" } else { "" }
            ));
            col.children = lower_pins(cx, idx, side)?;
            cols.push(Item::Node(col));
        }
        if cols.len() == 2 {
            let mut row = cx.typed("row");
            row.decls = Decl::list("gap: 24; align: center;");
            row.children = cols;
            children.push(Item::Node(row));
        } else {
            children.extend(cols);
        }
    }
    if !bottom.is_empty() {
        let even = slots_of(&bottom) % 2.0 == 0.0;
        let mut row = cx.typed("row");
        row.decls = Decl::list(&format!(
            "gap: 0; align: end;{} height: 20;",
            if even { " padding: 0 20 0 0;" } else { "" }
        ));
        row.children = lower_pins(cx, &bottom, "bottom")?;
        children.push(Item::Node(row));
    } else if middle && !top.is_empty() {
        let mut row = cx.typed("row");
        row.decls = Decl::list("height: 20;");
        children.push(Item::Node(row));
    }
    let lift = if top.is_empty() { 0.0 } else { 20.0 };
    if let Some(l) = n.label.as_ref().map(|l| l.trim().to_string()).filter(|l| !l.is_empty()) {
        children.push(block_with(cx, "part-value", &format!("pin: top; translate: 0 {};", num(-20.0 - lift)), Some(&l)));
    }
    if cx.in_labels == 0 {
        children.push(block_with(cx, "ref", &format!("pin: top; translate: 0 {};", num(-36.0 - lift)), Some(&r)));
    }
    let bodies = cx.bodies(chain)?;
    children.extend(bodies);
    for s in extra {
        cx.stmts(std::slice::from_ref(s), &mut children)?;
    }
    o.children = children;
    Ok(o)
}

fn pin_node(cx: &mut Cx, pn: &Node, side: &str, rewrite: bool, generated: bool) -> R<Item> {
    let mut p = typed_as(cx, pn, "pin");
    p.id = pn.id.clone();
    p.classes.extend(pn.classes.iter().cloned());
    p.decls = pn.style.clone();
    if rewrite {
        let old = own(&p.decls, "side");
        if old.as_deref() != Some(side) && old.is_some() {
            p.decls.retain(|d| d.name != "side");
            p.decls.push(Decl::val("side", side));
        }
    }
    let vertical = side == "top" || side == "bottom";
    if vertical {
        p.decls.push(Decl::val("width", "20"));
        p.decls.push(Decl::val("height", "auto"));
    }
    let label = pn.label.as_ref().map(|l| l.trim().to_string()).filter(|l| !l.is_empty());
    if label.is_none() && !generated {
        if let Some(id) = &pn.id {
            p.children.push(Cx::text_item(id));
        }
    }
    let (stub, numpos) = match side {
        "right" => ("points: 0 0, 20 0; pin: right; translate: 28 0;", "pin: right; translate: 28 -9; width: 20;"),
        "top" => ("points: 0 0, 0 20; pin: top; translate: 0 -28;", "pin: top; translate: 9 -28; height: 20;"),
        "bottom" => ("points: 0 0, 0 20; pin: bottom; translate: 0 28;", "pin: bottom; translate: 9 28; height: 20;"),
        _ => ("points: 0 0, 20 0; pin: left; translate: -28 0;", "pin: left; translate: -28 -9; width: 20;"),
    };
    let mut st = cx.typed("pin-stub");
    st.decls = Decl::list(stub);
    p.children.push(Item::Node(st));
    // a pin number is a number (its first term), written on the pin
    let number = own(&pn.style, "number").filter(|t| t.parse::<f64>().is_ok());
    if let Some(t) = number {
        p.children.push(block_with(cx, "pin-number", numpos, Some(&t)));
    }
    if let Some(l) = label {
        p.children.push(Cx::text_item(&l));
    }
    // a pin's own children follow
    if let Some(ch) = &pn.children {
        let mut v = Vec::new();
        cx.stmts(ch, &mut v)?;
        p.children.extend(v);
    }
    Ok(Item::Node(p))
}

// a wire is plain (-, --, ~); a text end's marker shapes its tag:
// (the plain operators, the tag's shape)
pub fn wire_ops(l: &Link) -> R<(Vec<String>, Option<&'static str>)> {
    let one_ended = l.groups.len() == 1;
    let plain = |o: &str| matches!(o, "-" | "--" | "~");
    let mut ops: Vec<String> = Vec::new();
    let mut text_shape: Option<&'static str> = None;
    for op in &l.ops {
        if plain(op) {
            ops.push(op.clone());
            continue;
        }
        let base = &op[..op.len() - 1];
        let shape = if op.ends_with('>') {
            Some("right")
        } else if op.ends_with('<') {
            Some("left")
        } else {
            None
        };
        if one_ended && l.label.is_some() && shape.is_some() && plain(base) {
            ops.push(base.to_string());
            text_shape = shape;
            continue;
        }
        let hint = if one_ended { "'a -> \"NET\"'" } else { "'a - b'" };
        return Err(err(&format!("a schematic wire is plain — markers shape a text label's tag; write {}", hint), l.span));
    }
    Ok((ops, text_shape))
}

// ------------------------------------------------------------------- parts
pub fn part_geo(cx: &Cx, n: &Node, chain: &[String], ty: &str) -> R<&'static PartGeo> {
    let sym = prop_decl(cx, &n.style, chain, "symbol").and_then(|d| d.first().map(|s| s.to_string()));
    if ty == "opamp" {
        return Ok(sch_geo::geo("opamp", None).unwrap());
    }
    match sym {
        None => Ok(sch_geo::geo(ty, None).unwrap()),
        Some(s) => match sch_geo::geo(ty, Some(&s)) {
            Some(g) => Ok(g),
            None => Err(err(
                &format!("unknown symbol '{}' on '|{}|' — its variants are {}", s, ty, sch_geo::variants(ty).join(", ")),
                n.span,
            )),
        },
    }
}

pub fn part(cx: &mut Cx, n: &Node, mut o: ONode, chain: &[String]) -> R<ONode> {
    let ty = part_type(chain).unwrap();
    let g = part_geo(cx, n, chain, &ty)?;
    let mut pose = written_pose(cx, n, chain)?;
    drop_pose(&mut o);
    cancel_define_pose(cx, &mut o, chain);
    if prop(cx, &n.style, chain, "rotate").is_none() {
        if let Some(id) = &n.id {
            if let Some(p) = cx.sch_pose(id) {
                pose.rot = p.rot;
            }
        }
    }
    o.classes.extend(pose.classes());
    let r = ref_text(cx, n, chain);
    let mut children = Vec::new();
    let mut line = cx.typed("sch-line");
    line.decls = vec![Decl::new("path", &format!("\"{}\"", map_path(g.line, pose)))];
    children.push(Item::Node(line));
    if let Some(s) = g.solid {
        let mut solid = cx.typed("sch-solid");
        solid.decls = vec![Decl::new("path", &format!("\"{}\"", map_path(s, pose))), Decl::val("pin", "center")];
        children.push(Item::Node(solid));
    }
    let vertical = pose.vertical();
    if let Some(l) = n.label.as_ref().map(|l| l.trim().to_string()).filter(|l| !l.is_empty()) {
        let d = if vertical { "pin: center; translate: 24 8;" } else { "pin: bottom; translate: 0 20;" };
        children.push(block_with(cx, "part-value", d, Some(&l)));
    }
    if n.id.is_some() {
        for (pin, dx, dy) in g.pins {
            let (x, y) = map_vec(*dx, *dy, pose);
            let mut b = cx.typed("block");
            b.id = Some(pin.to_string());
            b.decls = Decl::list(&format!("pin: center; translate: {} {};", num(x), num(y)));
            children.push(Item::Node(b));
        }
    }
    let d = if vertical { "pin: center; translate: 24 -8;" } else { "pin: top; translate: 0 -20;" };
    if cx.in_labels == 0 {
        children.push(block_with(cx, "ref", d, Some(&r)));
    }
    let bodies = cx.bodies(chain)?;
    children.extend(bodies);
    if let Some(ch) = &n.children {
        cx.stmts(ch, &mut children)?;
    }
    o.children = children;
    Ok(o)
}

// ------------------------------------------------------------------ labels
pub static SHAPES: &[&str] = &["plain", "left", "right", "both", "round"];

pub fn symbol_of(cx: &Cx, n: &Node, chain: &[String]) -> Option<String> {
    if let Some(s) = own(&n.style, "symbol") {
        return Some(s);
    }
    for t in chain {
        if let Some(d) = cx.define(t) {
            if let Some(s) = own(&d.decls, "symbol") {
                return Some(s);
            }
        }
        if let Some(td) = crate::types::find(t) {
            if let Some(s) = own(&Decl::list(td.defaults), "symbol") {
                return Some(s);
            }
        }
    }
    None
}

fn suggest(s: &str, options: &[&str]) -> Option<String> {
    let mut best: Option<(usize, &str)> = None;
    for o in options {
        let d = crate::util::levenshtein(s, o);
        if d <= 2 && best.map_or(true, |b| d < b.0) {
            best = Some((d, o));
        }
    }
    best.map(|b| b.1.to_string())
}

pub fn label(cx: &mut Cx, n: &Node, mut o: ONode, chain: &[String]) -> R<ONode> {
    let mut pose = written_pose(cx, n, chain)?;
    drop_pose(&mut o);
    cancel_define_pose(cx, &mut o, chain);
    let wired = n.id.as_ref().and_then(|id| cx.sch_pose(id));
    if pose.is_zero() {
        if let Some(p) = wired {
            pose = p;
        }
    }
    let sym = symbol_of(cx, n, chain);
    if sym.is_some() {
        if let Some(f) = cx.stack.last_mut() {
            f.plan_breaks = true;
        }
    }
    let shape = prop(cx, &n.style, chain, "shape").unwrap_or_else(|| "plain".to_string());
    let mut lead: Vec<String> = Vec::new();
    let mut children = Vec::new();
    let label = n.label.as_ref().map(|l| l.trim().to_string()).filter(|l| !l.is_empty());
    let bodies = cx.bodies(chain)?;
    match &sym {
        Some(s) => {
            let path = match sch_geo::SYMBOLS.iter().find(|(k, _)| k == s) {
                Some((_, p)) => *p,
                None => {
                    let names: Vec<&str> = sch_geo::SYMBOLS.iter().map(|(k, _)| *k).collect();
                    let msg = match suggest(s, &names) {
                        Some(h) => format!("unknown symbol '{}'; did you mean '{}'?", s, h),
                        None => format!("unknown symbol '{}'", s),
                    };
                    return Err(err(&msg, n.span));
                }
            };
            if !o.decls.iter().any(|d| d.name == "direction") {
                o.decls.insert(0, Decl::val("direction", "row"));
            }
            let mut t = cx.typed("sch-tag-line");
            t.decls = vec![Decl::new("path", &format!("\"{}\"", map_path(path, pose)))];
            children.push(Item::Node(t));
        }
        None => {
            if !SHAPES.contains(&shape.as_str()) {
                return Err(err(&format!("'shape' takes plain, left, right, both, or round — not '{}'", shape), n.span));
            }
            match shape.as_str() {
                "left" | "right" | "both" => {
                    lead.push(format!("lini-tag-flag-{}", shape));
                    cx.mark(&format!("tag-flag-{}", shape));
                    let mut t = cx.typed("sch-tag-line");
                    t.decls = Decl::list(&format!("chrome: tag {}; pin: center; path: \"M 0 0\";", shape));
                    children.push(Item::Node(t));
                }
                "round" => {
                    lead.push("lini-tag-outline".into());
                    lead.push("lini-tag-round".into());
                    cx.mark("tag-outline");
                    cx.mark("tag-round");
                }
                _ => {
                    let turned = pose.vertical();
                    let c = if turned { "net-run-turned" } else { "net-run" };
                    lead.push(format!("lini-{}", c));
                    cx.mark(c);
                }
            }
        }
    }
    let mut classes = lead;
    classes.extend(o.classes.drain(..));
    classes.extend(pose.classes());
    o.classes = classes;
    if let Some(l) = label {
        o.text_label = Some((l, children.len() + bodies.len()));
    }
    children.extend(bodies);
    if let Some(ch) = &n.children {
        cx.stmts(ch, &mut children)?;
    }
    o.children = children;
    Ok(o)
}

// ------------------------------------------------------------------ wiring
#[derive(Clone, Debug, PartialEq)]
enum Kind {
    // a device: its pins' directions (after a written pose)
    // `cell:` seats a device on the scope's track grid: an anchor
    Device { pins: Vec<(String, f64, f64)>, two_pin_part: bool, fixed_pose: bool, part: bool, cell: bool },
    // a tag (a shaped outline) never turns
    Label { sym: Option<String>, tag: bool },
    Other,
}

#[derive(Clone, Debug)]
struct Elem {
    kind: Kind,
}

// one end of a wire
#[derive(Clone, Debug, PartialEq)]
enum Term {
    Pin(String, String),
    Label(String),
    Other(String),
}

impl Term {
    fn text(&self) -> String {
        match self {
            Term::Pin(d, p) => format!("{}.{}", d, p),
            Term::Label(l) | Term::Other(l) => l.clone(),
        }
    }
}

// a planned link statement
#[derive(Clone, Debug, Default)]
pub struct Planned {
    pub hops: Vec<(String, String, String)>,
    terms: Vec<(Term, Term)>,
    // each hop's ends as written (not a pass-through exit or a bare name)
    written: Vec<(bool, bool)>,
    // run names merged onto a hop: (hop, text)
    pub extra: Vec<(usize, String)>,
    pub before: Vec<Node>,
    pub after: Vec<Node>,
    // a text end waiting for its id: (terminal, text, flag shape)
    text_end: Option<(Term, String, Option<&'static str>, String, Span)>,
}

#[derive(Default, Debug)]
pub struct Plan {
    pub poses: HashMap<String, Pose>,
    pub links: Vec<Planned>, // by link statement order in the scope
    // the first wiring error, raised when its statement lowers
    pub error: Option<(usize, Diag)>,
}

fn gnd_like(s: &Option<String>) -> bool {
    matches!(s.as_deref(), Some("gnd") | Some("earth") | Some("chassis"))
}
fn power_like(s: &Option<String>) -> bool {
    matches!(s.as_deref(), Some("power") | Some("antenna"))
}

impl<'a> Cx<'a> {
    // reference designators count per container
    pub fn sch_counter(&mut self, prefix: &str) -> usize {
        let k = self.stack.len();
        let parent = if k >= 2 { self.stack[k - 2].cid } else { 0 };
        let key = (parent, prefix.to_string());
        let e = self.sch_counters.entry(key).or_insert(0);
        *e += 1;
        *e
    }

    pub fn sch_pose(&self, id: &str) -> Option<Pose> {
        let plan = match self.stack.iter().rev().skip(1).find_map(|f| f.sch.as_ref()) {
            Some(p) => p,
            None => self.root_sch.as_ref()?,
        };
        plan.poses.get(id).cloned()
    }

    fn elem_of(&self, n: &Node) -> Option<(String, Elem)> {
        let id = n.id.clone()?;
        let ty = n.ty.clone().unwrap_or_else(|| "box".into());
        let (_, chain) = self.chain(&ty)?;
        let kind = if is_part(&chain) {
            let pt = part_type(&chain).unwrap();
            let g = part_geo(self, n, &chain, &pt).ok()?;
            let pose = written_pose(self, n, &chain).unwrap_or_default();
            let pins: Vec<(String, f64, f64)> = g
                .pins
                .iter()
                .map(|(p, x, y)| {
                    let (a, b) = map_vec(*x, *y, pose);
                    (p.to_string(), a, b)
                })
                .collect();
            let two = g.pins.len() == 2;
            let fixed = prop(self, &n.style, &chain, "rotate").is_some();
            let cell = prop_decl(self, &n.style, &chain, "cell").is_some();
            Kind::Device { pins, two_pin_part: two, fixed_pose: fixed, part: true, cell }
        } else if is_component(&chain) {
            let pose = written_pose(self, n, &chain).unwrap_or_default();
            let mut pins = Vec::new();
            let mut list: Vec<(String, Option<String>)> = Vec::new();
            if chain.iter().any(|c| c == "J") {
                if let Some(k) = prop(self, &n.style, &chain, "pins").and_then(|s| s.parse::<f64>().ok()) {
                    for i in 1..=(k.max(0.0) as usize) {
                        list.push((format!("p{}", i), Some("left".into())));
                    }
                }
            }
            for s in n.children.as_deref().unwrap_or(&[]) {
                if let Some(c) = node_is(self, s, "pin") {
                    if let Some(pid) = &c.id {
                        let side = prop(self, &c.style, &chain_of(self, c), "side").filter(|s| Dir::of_side(s).is_some());
                        list.push((pid.clone(), side));
                    }
                }
            }
            let autos = list.iter().filter(|(_, s)| s.is_none()).count();
            let half = (autos + 1) / 2;
            let mut k = 0;
            for (pid, side) in &list {
                let s = match side {
                    Some(s) => s.clone(),
                    None => {
                        k += 1;
                        if k <= half {
                            "left".into()
                        } else {
                            "right".into()
                        }
                    }
                };
                let (dx, dy) = match s.as_str() {
                    "left" => (-1.0, 0.0),
                    "right" => (1.0, 0.0),
                    "top" => (0.0, -1.0),
                    _ => (0.0, 1.0),
                };
                let (a, b) = map_vec(dx, dy, pose);
                pins.push((pid.clone(), a, b));
            }
            let fixed = n.style.iter().any(|d| d.name == "rotate");
            let two = pins.len() == 2;
            let cell = n.style.iter().any(|d| d.name == "cell");
            Kind::Device { pins, two_pin_part: two, fixed_pose: fixed, part: false, cell }
        } else if is_label(&chain) {
            let sym = symbol_of(self, n, &chain);
            let tag = sym.is_none() && prop(self, &n.style, &chain, "shape").map_or(false, |s| s != "plain");
            Kind::Label { sym, tag }
        } else {
            Kind::Other
        };
        Some((id, Elem { kind }))
    }

    // every wire's operators in a scope (its own links: a container inside
    // checks its own as it lowers)
    pub fn sch_ops(&self, stmts: &[Stmt]) -> R<()> {
        for s in stmts {
            if let Stmt::Link(l) = s {
                wire_ops(l)?;
            }
        }
        Ok(())
    }

    // (a schematic scope of its own, a container that keeps its parent's wiring)
    pub fn sch_kind(&self, n: &Node, chain: &[String]) -> (bool, bool) {
        let is = |t: &str| chain.iter().any(|c| c == t);
        let own_layout = own(&n.style, "layout");
        let layout = own_layout.clone().or_else(|| {
            chain.iter().find_map(|t| {
                self.define(t).and_then(|d| d.decls.iter().rev().find(|d| d.name == "layout").and_then(|d| d.first().map(|s| s.to_string())))
            })
        });
        let explicit = is("schematic") || layout.as_deref() == Some("schematic");
        let keeps = !["drawing", "sequence", "chart", "pie", "topic"].iter().any(|t| is(t))
            && !matches!(own_layout.as_deref(), Some("drawing") | Some("floorplan") | Some("sequence") | Some("chart") | Some("pie") | Some("tree"));
        (explicit, keeps)
    }

    // plan a schematic scope: the wires of its link statements and the poses
    // (the first `lenient` statements come from define bodies: their unknown
    // names pass as written)
    pub fn sch_plan(&mut self, stmts: &[Stmt], placed: bool, lenient: usize) -> R<Plan> {
        let mut elems: HashMap<String, Elem> = HashMap::new();
        for s in stmts {
            if let Stmt::Node(n) = s {
                if let Some((id, e)) = self.elem_of(n) {
                    elems.insert(id, e);
                }
            }
        }
        let mut plan = Plan::default();
        // pins named anywhere in the scope are not handed to bare references
        let mut used: HashMap<String, Vec<String>> = HashMap::new();
        for s in stmts {
            if let Stmt::Link(l) = s {
                for g in &l.groups {
                    for ep in g {
                        if let Endpoint::Path { parts, .. } = ep {
                            if parts.len() > 1 {
                                if let Some(Elem { kind: Kind::Device { two_pin_part: true, .. } }) = elems.get(&parts[0]) {
                                    used.entry(parts[0].clone()).or_default().push(parts[1].clone());
                                }
                            }
                        }
                    }
                }
            }
        }
        let mut caps = 0usize;
        let mut syms: HashMap<String, Option<String>> = HashMap::new();
        for (id, e) in &elems {
            if let Kind::Label { sym, .. } = &e.kind {
                syms.insert(id.clone(), sym.clone());
            }
        }
        for (si, s) in stmts.iter().enumerate() {
            let l = match s {
                Stmt::Link(l) => l,
                _ => continue,
            };
            let mut planned = Planned::default();
            let lax = si < lenient;
            if let Err(e) = self.sch_link(l, &elems, &mut used, &mut caps, &mut planned, &mut syms, lax) {
                plan.error = Some((plan.links.len(), e));
                break;
            }
            plan.links.push(planned);
        }
        // plain runs on a wired terminal ride its first wire; the other text
        // ends become net labels, numbered in order
        let mut labels = 0usize;
        for i in 0..plan.links.len() {
            let te = match plan.links[i].text_end.clone() {
                Some(t) => t,
                None => continue,
            };
            let (term, text, shape, op, text_span) = te;
            if shape.is_none() {
                let mut hit = None;
                'find: for (j, pl) in plan.links.iter().enumerate() {
                    for (k, (a, b)) in pl.terms.iter().enumerate() {
                        let (xa, xb) = pl.written.get(k).cloned().unwrap_or((true, true));
                        if (*a == term && xa) || (*b == term && xb) {
                            hit = Some((j, k));
                            break 'find;
                        }
                    }
                }
                if let Some((j, k)) = hit {
                    plan.links[j].extra.push((k, text.clone()));
                    continue;
                }
            }
            labels += 1;
            let id = format!("lini-label-{}", labels);
            let mut style = Vec::new();
            if let Some(s) = shape {
                style.push(Decl::val("shape", s));
            }
            let span = text_span;
            let nn = Node {
                ty: Some("label".into()),
                id: Some(id.clone()),
                label: Some(text.clone()),
                classes: vec![],
                style,
                children: None,
                span,
                head_span: span,
                ty_span: span,
            };
            syms.insert(id.clone(), None);
            let pl = &mut plan.links[i];
            pl.after.push(nn);
            pl.hops.push((term.text(), id.clone(), op));
            pl.terms.push((term.clone(), Term::Label(id)));
            pl.written.push((false, false));
        }
        // flags never turn
        let mut flags: Vec<String> = plan
            .links
            .iter()
            .flat_map(|p| p.after.iter())
            .filter(|n| n.style.iter().any(|d| d.name == "shape"))
            .filter_map(|n| n.id.clone())
            .collect();
        for (id, e) in &elems {
            if let Kind::Label { tag: true, .. } = &e.kind {
                flags.push(id.clone());
            }
        }
        let chains: Vec<Vec<(Term, Term)>> = plan.links.iter().map(|p| p.terms.clone()).collect();
        let mut poses: HashMap<String, Pose> = HashMap::new();
        if placed {
            solve(&elems, &chains, &syms, &mut poses);
        }
        for f in flags {
            poses.remove(&f);
        }
        plan.poses = poses;
        Ok(plan)
    }

    fn sch_link(
        &mut self,
        l: &Link,
        elems: &HashMap<String, Elem>,
        used: &mut HashMap<String, Vec<String>>,
        caps: &mut usize,
        planned: &mut Planned,
        syms: &mut HashMap<String, Option<String>>,
        lax: bool,
    ) -> R<()> {
        let one_ended = l.groups.len() == 1;
        let (ops, text_shape) = wire_ops(l)?;
        // the chain's elements: (entry, exit)
        let n = l.groups.len();
        let mut xs: Vec<(bool, bool)> = Vec::new();
        let mut seq: Vec<(Term, Term)> = Vec::new();
        for (gi, g) in l.groups.iter().enumerate() {
            let ep = match g.first() {
                Some(e) => e,
                None => continue,
            };
            let middle = gi > 0 && gi + 1 < n;
            match ep {
                Endpoint::Path { parts, text, span } => {
                    let name = &parts[0];
                    let pin_named = parts.len() > 1;
                    match elems.get(name).map(|e| &e.kind) {
                        Some(Kind::Device { pins, two_pin_part, .. }) => {
                            if pin_named {
                                let p = parts[1].clone();
                                if middle && *two_pin_part {
                                    let other =
                                        pins.iter().find(|(q, _, _)| *q != p).map(|x| x.0.clone()).unwrap_or_default();
                                    let u = used.entry(name.clone()).or_default();
                                    u.push(p.clone());
                                    u.push(other.clone());
                                    seq.push((Term::Pin(name.clone(), p), Term::Pin(name.clone(), other)));
                                    xs.push((true, false));
                                } else {
                                    used.entry(name.clone()).or_default().push(p.clone());
                                    let t = Term::Pin(name.clone(), p);
                                    seq.push((t.clone(), t));
                                    xs.push((true, true));
                                }
                            } else if *two_pin_part {
                                let u = used.entry(name.clone()).or_default();
                                let free: Vec<String> =
                                    pins.iter().map(|x| x.0.clone()).filter(|p| !u.contains(p)).collect();
                                if middle && free.is_empty() {
                                    return Err(err(
                                        &format!("both pins of '{}' are wired — name one ('{}.{}')", name, name, pins[0].0),
                                        *span,
                                    ));
                                }
                                if middle {
                                    let a = free.first().cloned().unwrap_or_else(|| pins[0].0.clone());
                                    let b = pins.iter().map(|x| x.0.clone()).find(|p| *p != a).unwrap_or_default();
                                    u.push(a.clone());
                                    u.push(b.clone());
                                    seq.push((Term::Pin(name.clone(), a), Term::Pin(name.clone(), b)));
                                    xs.push((false, false));
                                } else {
                                    let a = match free.first() {
                                        Some(a) => a.clone(),
                                        None => {
                                            return Err(err(
                                                &format!(
                                                    "both pins of '{}' are wired — name one ('{}.{}')",
                                                    name, name, pins[0].0
                                                ),
                                                *span,
                                            ))
                                        }
                                    };
                                    u.push(a.clone());
                                    let t = Term::Pin(name.clone(), a);
                                    seq.push((t.clone(), t));
                                    xs.push((false, false));
                                }
                            } else if pins.len() == 1 {
                                // a one-pin device names its pin
                                let t = Term::Pin(name.clone(), pins[0].0.clone());
                                seq.push((t.clone(), t));
                                xs.push((false, false));
                            } else {
                                let t = Term::Other(text.clone());
                                seq.push((t.clone(), t));
                                xs.push((true, true));
                            }
                        }
                        Some(Kind::Label { .. }) if !pin_named => {
                            let t = Term::Label(name.clone());
                            seq.push((t.clone(), t));
                            xs.push((true, true));
                        }
                        Some(_) => {
                            let t = Term::Other(text.clone());
                            seq.push((t.clone(), t));
                            xs.push((true, true));
                        }
                        None => {
                            if !pin_named && !lax {
                                return Err(err(
                                    &format!(
                                        "'{}' is unknown — a schematic never invents a box; did you mean '- \"{}\"' (a net label)?",
                                        name, name
                                    ),
                                    *span,
                                ));
                            }
                            let t = Term::Other(text.clone());
                            seq.push((t.clone(), t));
                            xs.push((true, true));
                        }
                    }
                }
                Endpoint::Capsule { node, tail } => {
                    let id = match &node.id {
                        Some(id) => id.clone(),
                        None => {
                            *caps += 1;
                            format!("lini-cap-{}", caps)
                        }
                    };
                    let mut nn = node.clone();
                    nn.id = Some(id.clone());
                    let ty = nn.ty.clone().unwrap_or_else(|| "box".into());
                    let chain = self.chain(&ty).map(|c| c.1).unwrap_or_default();
                    let t = if is_label(&chain) {
                        syms.insert(id.clone(), symbol_of(self, &nn, &chain));
                        Term::Label(id.clone())
                    } else {
                        Term::Other(format!("{}{}", id, tail))
                    };
                    if gi == 0 {
                        planned.before.push(nn);
                    } else {
                        planned.after.push(nn);
                    }
                    seq.push((t.clone(), t));
                    xs.push((true, true));
                }
                Endpoint::Text(_) => {}
            }
        }
        for (k, w) in seq.windows(2).enumerate() {
            let a = &w[0].1;
            let b = &w[1].0;
            let op = ops.get(k).cloned().unwrap_or_else(|| "-".to_string());
            planned.hops.push((a.text(), b.text(), op));
            planned.terms.push((a.clone(), b.clone()));
            planned.written.push((xs[k].1, xs[k + 1].0));
        }
        // a one-ended wire to text: a net label (or a run, merged later)
        if one_ended {
            if let (Some(text), Some(first)) = (&l.label, seq.first()) {
                let op = ops.first().cloned().unwrap_or_else(|| "-".to_string());
                planned.text_end = Some((first.1.clone(), text.clone(), text_shape, op, l.label_span));
            }
        }
        Ok(())
    }
}

// ------------------------------------------------------------- the solver
struct Solver<'s> {
    elems: &'s HashMap<String, Elem>,
    syms: &'s HashMap<String, Option<String>>,
    // every hop with its statement
    hops: Vec<(usize, Term, Term)>,
    poses: HashMap<String, Pose>,
    visited: Vec<String>,
    // (device, entry pin) a wire passed through an already posed device by
    passed: Vec<(String, String)>,
    // past an already posed device: labels only
    passing: bool,
    labels_done: Vec<String>,
    // the device the current walk set out from
    origin: Option<String>,
}

// where a run ends: a direction (or none), or back at the device it left
enum End {
    // the direction (and whether a seated pin set it: it then rules on any
    // axis)
    At(Option<(Dir, bool)>),
    Tie,
}

fn dev_kind<'k>(elems: &'k HashMap<String, Elem>, dev: &str) -> Option<&'k Kind> {
    elems.get(dev).map(|e| &e.kind)
}

impl<'s> Solver<'s> {
    fn pin_dir(&self, dev: &str, pin: &str) -> Option<Dir> {
        if let Some(Kind::Device { pins, part, .. }) = dev_kind(self.elems, dev) {
            let (_, x, y) = pins.iter().find(|p| p.0 == pin)?;
            let _ = part;
            let (x, y) = match self.poses.get(dev) {
                Some(p) => map_vec(*x, *y, Pose { rot: p.rot, mirror: None }),
                None => (*x, *y),
            };
            return Some(Dir::of_vec(x, y));
        }
        None
    }

    fn anchor(&self, dev: &str) -> bool {
        matches!(dev_kind(self.elems, dev), Some(Kind::Device { pins, cell, .. }) if pins.len() >= 3 || *cell)
    }

    // a wire passes through a two-pin part, or a component of one or two pins
    fn two_pin(&self, dev: &str) -> bool {
        match dev_kind(self.elems, dev) {
            Some(Kind::Device { two_pin_part: true, .. }) => true,
            Some(Kind::Device { pins, part: false, .. }) => !pins.is_empty() && pins.len() <= 2,
            _ => false,
        }
    }

    // a one-pin component: the wire leaves by the pin it came in on
    fn one_pin(&self, dev: &str) -> bool {
        matches!(dev_kind(self.elems, dev), Some(Kind::Device { pins, part: false, .. }) if pins.len() == 1)
    }

    fn fixed(&self, dev: &str) -> bool {
        matches!(dev_kind(self.elems, dev), Some(Kind::Device { fixed_pose: true, .. }))
    }

    fn other_pin(&self, dev: &str, pin: &str) -> Option<String> {
        if !self.two_pin(dev) {
            return None;
        }
        if self.one_pin(dev) {
            return Some(pin.to_string());
        }
        if let Some(Kind::Device { pins, .. }) = dev_kind(self.elems, dev) {
            return pins.iter().find(|p| p.0 != pin).map(|p| p.0.clone());
        }
        None
    }

    // hops at a term, except the one indexed `skip`
    fn at(&self, t: &Term, skip: Option<usize>) -> Vec<(usize, Term)> {
        let mut v = Vec::new();
        for (i, (_, a, b)) in self.hops.iter().enumerate() {
            if Some(i) == skip {
                continue;
            }
            if a == t {
                v.push((i, b.clone()));
            } else if b == t {
                v.push((i, a.clone()));
            }
        }
        v
    }

    fn stops(&self, dev: &str) -> bool {
        self.anchor(dev) || self.fixed(dev) || !self.two_pin(dev)
    }

    // the way a run must travel into its end, walking on from `t` (reached
    // over hop `via`) through free devices and plain labels: down onto a
    // ground, up into a supply, against a fixed pin's facing. At a junction
    // the latest wire leads; a branch that ties back to the device the run
    // left is no end.
    fn dest_dir(&self, t: &Term, via: usize) -> Option<(Dir, bool)> {
        let from = match t {
            Term::Pin(d, p) => Term::Pin(d.clone(), self.other_pin(d, p)?),
            Term::Label(_) => t.clone(),
            Term::Other(_) => return None,
        };
        match self.dest_walk(&from, via, 0) {
            End::At(d) => d,
            End::Tie => None,
        }
    }

    fn dest_walk(&self, from: &Term, skip: usize, depth: usize) -> End {
        if depth > 64 {
            return End::At(None);
        }
        let hops = self.at(from, Some(skip));
        if hops.is_empty() {
            return End::At(None);
        }
        for (i, n) in hops.into_iter().rev() {
            match self.dest_branch(&n, i, depth) {
                End::Tie => continue,
                e => return e,
            }
        }
        End::Tie
    }

    fn dest_branch(&self, n: &Term, via: usize, depth: usize) -> End {
        match n {
            Term::Pin(d, p) => {
                if self.stops(d) {
                    if self.origin.as_deref() == Some(d.as_str()) {
                        return End::Tie;
                    }
                    // a seated device takes the run on its pin's axis, read
                    // left to right or top to bottom; a fixed part's pin is
                    // entered against its facing
                    return End::At(self.pin_dir(d, p).map(|f| {
                        if !self.anchor(d) {
                            (f.opposite(), false)
                        } else if f.horizontal() {
                            (Dir::R, true)
                        } else {
                            (Dir::D, true)
                        }
                    }));
                }
                match self.other_pin(d, p) {
                    Some(o) => self.dest_walk(&Term::Pin(d.clone(), o), via, depth + 1),
                    None => End::At(None),
                }
            }
            Term::Label(l) => {
                let s = self.syms.get(l).cloned().unwrap_or(None);
                if gnd_like(&s) {
                    End::At(Some((Dir::D, false)))
                } else if power_like(&s) {
                    End::At(Some((Dir::U, false)))
                } else if s.is_some() {
                    End::At(None)
                } else {
                    self.dest_walk(n, via, depth + 1)
                }
            }
            Term::Other(_) => End::At(None),
        }
    }

    // an anchor's pin that also wires straight to a device's pin
    fn tied(&self, from: &Term, via: usize) -> bool {
        match from {
            Term::Pin(dev, _) if self.anchor(dev) => self.at(from, Some(via)).into_iter().any(|(_, n)| match &n {
                Term::Pin(d2, _) => self.stops(d2),
                _ => false,
            }),
            _ => false,
        }
    }

    fn label_pose(&mut self, l: &str, d: Dir, upright: bool) {
        let sym = self.syms.get(l).cloned().unwrap_or(None);
        self.poses.insert(l.to_string(), label_pose(&sym, d, upright));
    }

    // arrive at `t` over hop `via`, travelling `d`, from `from`; past a
    // fixed part the wire no longer turns toward its end (`turn`)
    #[allow(clippy::too_many_arguments)]
    fn arrive(&mut self, t: &Term, via: usize, d: Dir, d0: Dir, from: &Term, turn: bool, depth: usize) {
        if depth > 256 {
            return;
        }
        match t {
            Term::Pin(dev, pin) => {
                if self.anchor(dev) || !self.two_pin(dev) {
                    return;
                }
                // a part already posed: the wire passes it as it lies, on to
                // the labels beyond (the parts there wait for their own wires)
                let again = self.visited.contains(dev);
                if !again && self.passing {
                    return;
                }
                if again {
                    let key = (dev.clone(), pin.clone());
                    if self.passed.contains(&key) {
                        return;
                    }
                    self.passed.push(key);
                } else {
                    self.visited.push(dev.clone());
                }
                if !again && !self.fixed(dev) {
                    // a wire turns toward its end when that end lies across
                    // the axis the chain set out on
                    // (a seated end rules on any axis): the entry faces
                    // back against the end's travel, else against the wire's
                    let dest = if turn { self.dest_dir(t, via) } else { None };
                    // a chain with no end off a pin wired straight to
                    // another device's pin turns aside, read top to bottom
                    // (left to right off an upright pin)
                    let toward = match dest {
                        Some((dd, strong)) if strong || dd.horizontal() != d0.horizontal() => dd,
                        _ if turn && self.tied(from, via) => {
                            if d.horizontal() {
                                Dir::D
                            } else {
                                Dir::R
                            }
                        }
                        _ => d,
                    };
                    let p = pose_for(self.elems, dev, pin, toward.opposite());
                    self.poses.insert(dev.clone(), p);
                }
                // a label we left from faces the way the wire went
                if let (Term::Label(l), false) = (from, again) {
                    if let Some(e) = self.pin_dir(dev, pin) {
                        self.label_pose(l, e.opposite(), false);
                    }
                }
                let fixed = again || self.fixed(dev);
                if let Some(o) = self.other_pin(dev, pin) {
                    if let Some(mut nd) = self.pin_dir(dev, &o) {
                        // an exit facing back along the wire: the wire runs on
                        if self.one_pin(dev) || (fixed && nd == d.opposite()) {
                            nd = if self.one_pin(dev) { nd.opposite() } else { d };
                        }
                        let exit = Term::Pin(dev.clone(), o);
                        let turn = turn && !fixed;
                        let skip = if self.one_pin(dev) { Some(via) } else { None };
                        let saved = self.passing;
                        self.passing = saved || again;
                        self.leave(&exit, nd, d0, skip, turn, depth + 1);
                        self.passing = saved;
                    }
                }
                // the other wires at the pin it came in by carry the travel on
                if !again && !self.one_pin(dev) {
                    self.leave(t, d, d0, Some(via), turn, depth + 1);
                }
            }
            Term::Label(l) => {
                // a symbol on a component's pin only flips along its axis; on
                // a junction (other wires, ties back aside) it keeps its pose
                // (a symbol on an upright pin wired straight to another
                // device's pin turns aside like a chain, to the right)
                // (one that would stand on its head there, that is)
                // (its attach facing the way the pin faces)
                let flips = {
                    let sym = self.syms.get(l).cloned().unwrap_or(None);
                    let natural = match sym.as_deref() {
                        Some("gnd") | Some("earth") | Some("chassis") => Some(Dir::U),
                        Some("power") | Some("antenna") => Some(Dir::D),
                        Some("nc") => Some(Dir::L),
                        _ => None,
                    };
                    match from {
                        Term::Pin(dev, pin) => natural.is_some() && self.pin_dir(dev, pin) == natural,
                        _ => false,
                    }
                };
                let tied_upright = flips && self.tied(from, via);
                let aside = if d.horizontal() { Dir::D } else { Dir::R };

                let (upright, junction) = match from {
                    Term::Pin(dev, _) if self.anchor(dev) => (!tied_upright, false),
                    Term::Pin(_, _) => {
                        let others = self.at(from, Some(via)).into_iter().any(|(_, n)| match &n {
                            Term::Pin(d, _) => !self.stops(d),
                            _ => true,
                        });
                        (false, others)
                    }
                    _ => (false, false),
                };
                if junction && self.syms.get(l).map_or(false, |s| s.is_some()) {
                    self.poses.insert(l.to_string(), Pose::default());
                    if !self.labels_done.contains(l) {
                        self.labels_done.push(l.clone());
                        self.leave(t, d, d0, Some(via), turn, depth + 1);
                    }
                    return;
                }
                // inside a run a label turns toward the run's end like a part
                // (a supply or ground symbol is an end itself)
                let mut td = if tied_upright { aside } else { d };
                if turn && !self.at(t, Some(via)).is_empty() {
                    let sym = self.syms.get(l).cloned().unwrap_or(None);
                    let own_end = if gnd_like(&sym) {
                        Some((Dir::D, false))
                    } else if power_like(&sym) {
                        Some((Dir::U, false))
                    } else {
                        None
                    };
                    if let Some((dd, strong)) = own_end.or_else(|| self.dest_dir(t, via)) {
                        if strong || dd.horizontal() != d0.horizontal() {
                            td = dd;
                        }
                    }
                }
                if !self.labels_done.contains(l) {
                    self.label_pose(l, td, upright);
                    self.labels_done.push(l.clone());
                    self.leave(t, td, d0, Some(via), turn, depth + 1);
                }
            }
            Term::Other(_) => {}
        }
    }

    fn leave(&mut self, from: &Term, d: Dir, d0: Dir, skip: Option<usize>, turn: bool, depth: usize) {
        for (i, next) in self.at(from, skip) {
            self.arrive(&next, i, d, d0, from, turn, depth);
        }
    }
}

fn pose_for(elems: &HashMap<String, Elem>, dev: &str, entry: &str, toward: Dir) -> Pose {
    if let Some(Kind::Device { pins, .. }) = dev_kind(elems, dev) {
        // `pins` already wear the written mirror
        if let Some((_, x, y)) = pins.iter().find(|p| p.0 == entry) {
            for rot in [0, 90, 180, 270] {
                let p = Pose { rot, mirror: None };
                let (a, b) = map_vec(*x, *y, p);
                if Dir::of_vec(a, b) == toward {
                    return p;
                }
            }
        }
    }
    Pose::default()
}

// a label turns so the end it attaches by faces back along the wire; a
// symbol on a component's own pin only flips along its axis
fn label_pose(sym: &Option<String>, d: Dir, upright: bool) -> Pose {
    let natural = match sym.as_deref() {
        Some("gnd") | Some("earth") | Some("chassis") => Dir::U,
        Some("power") | Some("antenna") => Dir::D,
        Some("nc") => Dir::L,
        Some(_) => return Pose::default(),
        None => Dir::R,
    };
    let want = d.opposite();
    if sym.is_some() && upright && natural.horizontal() != want.horizontal() {
        return Pose::default();
    }
    let v = |x: Dir| -> (f64, f64) {
        match x {
            Dir::L => (-1.0, 0.0),
            Dir::R => (1.0, 0.0),
            Dir::U => (0.0, -1.0),
            Dir::D => (0.0, 1.0),
        }
    };
    let (x, y) = v(natural);
    for rot in [0, 90, 180, 270] {
        let p = Pose { rot, mirror: None };
        let (a, b) = map_vec(x, y, p);
        if Dir::of_vec(a, b) == want {
            return p;
        }
    }
    Pose::default()
}

fn solve(
    elems: &HashMap<String, Elem>,
    chains: &[Vec<(Term, Term)>],
    syms: &HashMap<String, Option<String>>,
    poses: &mut HashMap<String, Pose>,
) {
    let mut s = Solver {
        elems,
        syms,
        hops: Vec::new(),
        poses: HashMap::new(),
        visited: Vec::new(),
        passed: Vec::new(),
        passing: false,
        labels_done: Vec::new(),
        origin: None,
    };
    let mut firsts: Vec<Option<usize>> = Vec::new();
    let mut lasts: Vec<Option<usize>> = Vec::new();
    for (k, c) in chains.iter().enumerate() {
        firsts.push(if c.is_empty() { None } else { Some(s.hops.len()) });
        for (a, b) in c {
            s.hops.push((k, a.clone(), b.clone()));
        }
        lasts.push(if c.is_empty() { None } else { Some(s.hops.len() - 1) });
    }
    // chains leaving a fixed pin, in order
    for k in 0..chains.len() {
        if let Some(i) = firsts[k] {
            let (_, a, b) = s.hops[i].clone();
            if let Term::Pin(dev, pin) = &a {
                if s.anchor(dev) {
                    if let Some(d) = s.pin_dir(dev, pin) {
                        s.origin = Some(dev.clone());
                        s.arrive(&b, i, d, d, &a, true, 0);
                    }
                }
            }
        }
    }
    // chains ending on one
    for k in 0..chains.len() {
        if let Some(i) = lasts[k] {
            let (_, a, b) = s.hops[i].clone();
            if let Term::Pin(dev, pin) = &b {
                if s.anchor(dev) {
                    let reached = match &a {
                        Term::Label(l) => s.labels_done.contains(l),
                        Term::Pin(d, _) => s.visited.contains(d),
                        Term::Other(_) => true,
                    };
                    if reached {
                        continue;
                    }
                    if let Some(d) = s.pin_dir(dev, pin) {
                        s.origin = Some(dev.clone());
                        s.arrive(&a, i, d, d, &b, true, 0);
                    }
                }
            }
        }
    }
    *poses = s.poses;
}
