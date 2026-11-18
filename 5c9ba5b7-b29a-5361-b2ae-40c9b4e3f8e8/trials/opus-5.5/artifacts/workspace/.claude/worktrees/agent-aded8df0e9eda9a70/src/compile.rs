// The compile pipeline: scene → styles → layout → routes → SVG.

use crate::ast::*;
use crate::diag::{Diag, Span};
use crate::eval::Env;
use crate::font::Family;
use crate::scene::*;
use crate::style::*;
use crate::types::Prim;
use std::collections::HashMap;

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Dir {
    Row,
    Column,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Align {
    Start,
    Center,
    End,
    Stretch,
}

#[derive(Clone, Debug)]
pub struct Computed {
    pub font_size: f64,
    pub font_weight: u32,
    pub family: Family,
    pub letter_spacing: f64,
    pub line_spacing: f64,
    pub text_transform: Option<String>,
    pub padding: [f64; 4], // top right bottom left
    pub gap: (f64, f64),   // (row gap, column gap)
    pub direction: Dir,
    pub align: Align,
    pub justify: Align,
    pub width: Option<f64>,
    pub height: Option<f64>,
    pub max_width: Option<f64>,
    pub stroke_width: f64,
    pub has_stroke: bool,
    pub radius: f64,
    pub pin: Option<String>,
    pub translate: (f64, f64),
    pub rotate: f64,
    pub layout: String,
    pub nowrap: bool,
    pub family_css: Option<String>,
}

impl Default for Computed {
    fn default() -> Self {
        Computed {
            font_size: 15.0,
            font_weight: 500,
            family: Family::Sans,
            letter_spacing: 0.0,
            line_spacing: 0.0,
            text_transform: None,
            padding: [0.0; 4],
            gap: (36.0, 36.0),
            direction: Dir::Row,
            align: Align::Center,
            justify: Align::Center,
            width: None,
            height: None,
            max_width: None,
            stroke_width: 2.0,
            has_stroke: false,
            radius: 0.0,
            pin: None,
            translate: (0.0, 0.0),
            rotate: 0.0,
            layout: "flow".into(),
            nowrap: false,
            family_css: None,
        }
    }
}

pub struct Ctx {
    pub src: String,
    pub file: String,
    pub sheet: SheetModel,
    pub nodes: Vec<Node>,
    pub comp: Vec<Computed>,
    pub links: Vec<Link>,
    pub warnings: Vec<Diag>,
    pub root_font_size: f64,
    // sketch / drawing layout state (src/drawing.rs)
    pub sk: crate::drawing::State,
    // routed links (filled by links::compute after layout)
    pub link_geo: Vec<crate::links::LinkGeo>,
}

pub fn env(ctx: &Ctx) -> &Env {
    &ctx.sheet.env
}

// The cascade for one node: type chain (base first, defaults then user
// rules), classes, id rules, inline. Returns (rule-level props, all props).
pub fn cascade(sheet: &SheetModel, n: &Node) -> (Vec<(String, Value)>, Vec<(String, Value)>) {
    let mut props: Vec<(String, Value)> = Vec::new();
    fn set(props: &mut Vec<(String, Value)>, k: &str, v: &Value) {
        if let Some(e) = props.iter_mut().find(|e| e.0 == k) {
            e.1 = v.clone();
        } else {
            props.push((k.to_string(), v.clone()));
        }
    }
    // table column classes (.lini-align-*, .lini-justify-*) sit below every rule
    for t in n.chain.iter() {
        if let Some((k, v)) = crate::table::pseudo_class(t) {
            set(&mut props, k, &crate::table::pseudo_value(v));
        }
    }
    for t in n.chain.iter().rev() {
        for d in type_defaults(t) {
            set(&mut props, &d.name, &d.value);
        }
        if let Some(df) = sheet.define(t) {
            for d in &df.decls {
                set(&mut props, &d.name, &d.value);
            }
        }
        for d in sheet.type_rule(t) {
            set(&mut props, &d.name, &d.value);
        }
    }
    // a mindmap's descendant rules (src/tree.rs) sit between types and classes
    for d in crate::tree::context_decls(n) {
        set(&mut props, &d.name, &d.value);
    }
    for c in &n.classes {
        if let Some(cr) = sheet.class(c) {
            for d in &cr.decls {
                set(&mut props, &d.name, &d.value);
            }
        }
    }
    let rule_level = props.clone();
    if let Some(id) = &n.id {
        for (rid, ds) in &sheet.id_rules {
            if rid == id {
                for d in ds {
                    set(&mut props, &d.name, &d.value);
                }
            }
        }
    }
    for d in &n.inline {
        set(&mut props, &d.name, &d.value);
    }
    (rule_level, props)
}

pub fn get<'a>(props: &'a [(String, Value)], k: &str) -> Option<&'a Value> {
    props.iter().find(|e| e.0 == k).map(|e| &e.1)
}

fn parse_align(s: &str) -> Option<Align> {
    match s {
        "start" | "top" | "left" => Some(Align::Start),
        "center" | "middle" => Some(Align::Center),
        "end" | "bottom" | "right" => Some(Align::End),
        "stretch" => Some(Align::Stretch),
        _ => None,
    }
}

pub fn compute(ctx: &mut Ctx) {
    let n = ctx.nodes.len();
    ctx.comp = vec![Computed::default(); n];
    // nodes are created parent-before-child, so a forward pass sees parents first
    for i in 0..n {
        let parent = ctx.nodes[i].parent;
        let pc = parent.map(|p| ctx.comp[p].clone());
        let (_, props) = if i == 0 { (vec![], ctx.nodes[0].inline.iter().map(|d| (d.name.clone(), d.value.clone())).collect()) } else { cascade(&ctx.sheet, &ctx.nodes[i]) };
        let env = &ctx.sheet.env;
        let mut c = Computed::default();
        if let Some(p) = &pc {
            c.font_size = p.font_size;
            c.font_weight = p.font_weight;
            c.family = p.family;
            c.letter_spacing = p.letter_spacing;
            c.line_spacing = p.line_spacing;
            c.text_transform = p.text_transform.clone();
            c.family_css = p.family_css.clone();
        }
        let num = |k: &str| get(&props, k).and_then(|v| value_num(env, v));
        if let Some(v) = num("font-size") {
            c.font_size = v;
        } else if let Some(v) = get(&props, "font-scale") {
            let xs = value_nums(env, v);
            if xs.len() == 2 {
                let base = pc.as_ref().map(|p| p.font_size).unwrap_or(15.0);
                c.font_size = xs[0] * base / xs[1];
            }
        }
        if let Some(v) = get(&props, "font-weight") {
            c.font_weight = weight_num(v);
        }
        if let Some(v) = get(&props, "font-family") {
            c.family = family_of(v);
            c.family_css = Some(font_family_css(v));
        }
        if let Some(v) = num("letter-spacing") {
            c.letter_spacing = v;
        }
        if let Some(v) = num("line-spacing") {
            c.line_spacing = v;
        }
        if let Some(v) = get(&props, "text-transform") {
            c.text_transform = ident_of(v).map(|s| s.to_string());
        }
        if let Some(v) = get(&props, "padding") {
            let xs = value_nums(env, v);
            c.padding = match xs.len() {
                1 => [xs[0]; 4],
                2 => [xs[0], xs[1], xs[0], xs[1]],
                4 => [xs[0], xs[1], xs[2], xs[3]],
                _ => [0.0; 4],
            };
        }
        if let Some(v) = get(&props, "gap") {
            let xs = value_nums(env, v);
            c.gap = match xs.len() {
                1 => (xs[0], xs[0]),
                2 => (xs[0], xs[1]),
                _ => c.gap,
            };
        }
        if let Some(v) = get(&props, "direction") {
            if ident_of(v) == Some("column") {
                c.direction = Dir::Column;
            }
        }
        if let Some(v) = get(&props, "align") {
            if let Some(a) = ident_of(v).and_then(parse_align) {
                c.align = a;
            }
        }
        if let Some(v) = get(&props, "justify") {
            if let Some(a) = ident_of(v).and_then(parse_align) {
                c.justify = a;
            }
        }
        c.width = num("width");
        c.height = num("height");
        c.max_width = num("max-width");
        if let Some(v) = num("stroke-width") {
            c.stroke_width = v;
        }
        if let Some(v) = get(&props, "stroke") {
            c.has_stroke = ident_of(v) != Some("none");
        }
        if let Some(v) = num("radius") {
            c.radius = v;
        }
        if let Some(v) = get(&props, "pin") {
            let mut parts = Vec::new();
            for g in &v.groups {
                for t in g {
                    if let Term::Ident(s, _) = t {
                        parts.push(s.clone());
                    }
                }
            }
            c.pin = Some(parts.join(" "));
        }
        if let Some(v) = get(&props, "translate") {
            let xs = value_nums(env, v);
            if xs.len() == 2 {
                c.translate = (xs[0], xs[1]);
            }
        }
        if let Some(v) = num("rotate") {
            c.rotate = v;
        }
        if let Some(v) = get(&props, "layout") {
            if let Some(s) = ident_of(v) {
                c.layout = s.to_string();
            }
        }
        if let Some(v) = get(&props, "text-wrap") {
            c.nowrap = ident_of(v) == Some("nowrap");
        }
        ctx.nodes[i].props = props.into_iter().collect();
        ctx.comp[i] = c;
    }
}

pub fn root_decls_node(sheet: &SheetModel) -> Node {
    let mut n = Node::new(Prim::Block, vec![], Span::default());
    let defaults = parse_decls("layout: flow; padding: 20; gap: 36; font-size: 15;");
    let mut inline = defaults;
    for d in &sheet.root {
        if let Some(e) = inline.iter_mut().find(|e| e.name == d.name) {
            *e = d.clone();
        } else {
            inline.push(d.clone());
        }
    }
    n.inline = inline;
    n
}
