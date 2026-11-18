// Circuit schematics on the compile path.
//
// The lowering is `lini desugar`'s own (src/desugar/schematic.rs): a document
// with schematic content is lowered once, and every schematic scope (a root
// `layout: schematic`, a `|schematic|`, a node or define laying out as one)
// is built from its lowered subtree — components as blocks of pin rows and
// columns with stubs and numbers, parts as drawn symbols with pin stations,
// net labels and symbols, and the wires as link statements between pins.
//
//   build.rs   the lowered items onto scene nodes and pending links
//   place.rs   the `layout: schematic` scope: anchors on the track grid,
//              satellites seated at the pins their wires touch, the flow
//              fallback for whatever has no placed end
//   wire.rs    the wires: routes between fixed ports, junction dots, net
//              names along the trace
//   draw.rs    the wires' SVG and stylesheet rules

mod build;
mod draw;
mod net;
mod place;
mod router;
mod seat;
mod wire;

use crate::ast::{Doc, Endpoint, NodeStmt, SheetItem, Stmt, Term, Value};
use crate::compile::Ctx;
use crate::desugar::{Item, Lowered, ONode};
use crate::diag::{Diag, Span};
use crate::scene::{Builder, SheetModel};
use std::cell::RefCell;

pub use draw::{extend_bbox, render_links};
pub use place::measure;
pub use wire::route;

// the default rule text of the classes the lowering introduces
pub static CLASS_DEFAULTS: &[(&str, &str)] = &[
    ("sch-line", "fill: none; stroke: --component-stroke; stroke-width: 1.5;"),
    ("sch-solid", "fill: --component-stroke; stroke: none;"),
    ("sch-tag-line", "fill: none; stroke: --label-ink; stroke-width: 1.5;"),
    ("pin-stub", "fill: none; stroke: --component-stroke; stroke-width: 1.5;"),
    ("pin-number", "color: --pin-number; font-size: 10;"),
    ("ref", "font-size: 12; font-weight: semibold;"),
    ("part-value", "font-size: 12;"),
    ("tag-outline", "stroke: --label-ink; stroke-width: 1.5; padding: 2 6;"),
    ("tag-round", "radius: 99;"),
    ("tag-flag-left", "padding: 2 6 2 14;"),
    ("tag-flag-right", "padding: 2 14 2 6;"),
    ("tag-flag-both", "padding: 2 14;"),
    ("net-run", "width: 40; padding: 0 4;"),
    ("net-run-turned", "height: 40; padding: 4 0;"),
    ("sheet-caption", "translate: 10 10; font-scale: 16 15; font-weight: semibold;"),
];

pub fn is_internal_class(name: &str) -> bool {
    CLASS_DEFAULTS.iter().any(|(n, _)| *n == name) || name.starts_with("pose-") || name.starts_with("mirror-")
}

// the part types (a drawn symbol with pin stations)
pub const PART_TYPES: &[&str] =
    &["R", "C", "L", "D", "LED", "Q", "Y", "F", "FB", "SW", "BT", "V", "I", "M", "BZ", "TP", "opamp"];

// every type of the schematic family
pub const FAMILY: &[&str] = &[
    "schematic", "component", "pin", "space", "label", "junction", "gnd", "nc", "opamp", "J", "R", "C", "L", "D", "LED",
    "Q", "Y", "F", "FB", "SW", "BT", "V", "I", "M", "BZ", "TP",
];

pub struct State {
    pub low: Lowered,
    // every lowered node with an origin, in document order: (origin, path)
    pub index: Vec<(Span, Vec<usize>)>,
    pub taken: Vec<bool>,
    pub root_scope: bool,
    pub src: String,
}

thread_local! {
    pub static STATE: RefCell<Option<State>> = const { RefCell::new(None) };
}

pub fn active() -> bool {
    STATE.with(|s| s.borrow().is_some())
}

fn index_items(items: &[Item], path: &mut Vec<usize>, out: &mut Vec<(Span, Vec<usize>)>) {
    for (k, it) in items.iter().enumerate() {
        if let Item::Node(o) = it {
            path.push(k);
            if let Some(sp) = o.origin {
                out.push((sp, path.clone()));
            }
            index_items(&o.children, path, out);
            path.pop();
        }
    }
}

fn node_at<'a>(items: &'a [Item], path: &[usize]) -> Option<&'a ONode> {
    let mut cur = items;
    let mut node = None;
    for &k in path {
        match cur.get(k) {
            Some(Item::Node(o)) => {
                node = Some(o);
                cur = &o.children;
            }
            _ => return None,
        }
    }
    node
}

// the first lowered node not yet built from this source span
pub fn take_onode(span: Span) -> Option<ONode> {
    STATE.with(|s| {
        let mut b = s.borrow_mut();
        let st = b.as_mut()?;
        let k = (0..st.index.len()).find(|&k| !st.taken[k] && st.index[k].0 == span)?;
        st.taken[k] = true;
        let path = st.index[k].1.clone();
        // its descendants are built with it
        for j in 0..st.index.len() {
            if st.index[j].1.len() > path.len() && st.index[j].1.starts_with(&path) {
                st.taken[j] = true;
            }
        }
        node_at(&st.low.items, &path).cloned()
    })
}

fn chain_has(chain: &[String], names: &[&str]) -> bool {
    chain.iter().any(|c| names.contains(&c.as_str()))
}

fn value_ident(v: &Value) -> Option<&str> {
    match v.groups.first().and_then(|g| g.first()) {
        Some(Term::Ident(s, _)) => Some(s.as_str()),
        _ => None,
    }
}

fn decls_layout_schematic(ds: &[crate::ast::Decl]) -> bool {
    ds.iter().any(|d| d.name == "layout" && value_ident(&d.value) == Some("schematic"))
}

fn stmts_need(sheet: &SheetModel, stmts: &[Stmt]) -> bool {
    for s in stmts {
        match s {
            Stmt::Node(n) => {
                if node_needs(sheet, n) {
                    return true;
                }
            }
            Stmt::Link(l) => {
                for g in &l.groups {
                    for ep in g {
                        if let Endpoint::Node(n) = ep {
                            if node_needs(sheet, n) {
                                return true;
                            }
                        }
                    }
                }
            }
            Stmt::Text(_) => {}
        }
    }
    false
}

fn node_needs(sheet: &SheetModel, n: &NodeStmt) -> bool {
    let ty = n.type_name.clone().unwrap_or_else(|| "box".to_string());
    if let Some((_, chain)) = crate::scene::type_chain(sheet, &ty) {
        if chain_has(&chain, FAMILY) {
            return true;
        }
    }
    if n.style.as_deref().map_or(false, decls_layout_schematic) {
        return true;
    }
    n.children.as_deref().map_or(false, |c| stmts_need(sheet, c))
}

// does the document need the schematic path?
pub fn detect(doc: &Doc, sheet: &SheetModel) -> bool {
    if let Some(sh) = &doc.sheet {
        for it in &sh.items {
            match it {
                SheetItem::Decl(d) if d.name == "layout" && value_ident(&d.value) == Some("schematic") => return true,
                SheetItem::Define(d) => {
                    if decls_layout_schematic(&d.decls) {
                        return true;
                    }
                    if crate::types::find(&d.base).map_or(false, |_| FAMILY.contains(&d.base.as_str())) {
                        return true;
                    }
                    if d.body.as_deref().map_or(false, |b| stmts_need(sheet, b)) {
                        return true;
                    }
                }
                SheetItem::Rule(r) if decls_layout_schematic(&r.decls) => return true,
                _ => {}
            }
        }
    }
    stmts_need(sheet, &doc.stmts)
}

// Lower the document when it has schematic content; a lowering error is the
// compile's error. The root scope takes the schematic's spacing and wash.
pub fn prepare(src: &str, doc: &Doc, sheet: &mut SheetModel) -> Result<(), Diag> {
    STATE.with(|s| *s.borrow_mut() = None);
    draw::reset();
    if !detect(doc, sheet) {
        return Ok(());
    }
    let low = crate::desugar::lower(src)?;
    let root_scope = sheet.root.iter().rev().find(|d| d.name == "layout").and_then(|d| value_ident(&d.value)) == Some("schematic");
    if root_scope {
        if let Some(crate::desugar::SheetLine::Decls(ds)) = low.sheet.first() {
            for d in ds {
                if matches!(d.name.as_str(), "gap" | "clearance" | "fill") && !sheet.root.iter().any(|x| x.name == d.name) {
                    sheet.root.extend(build::convert_decls(std::slice::from_ref(d), Span::default()));
                }
            }
        }
    }
    let mut index = Vec::new();
    index_items(&low.items, &mut Vec::new(), &mut index);
    let taken = vec![false; index.len()];
    STATE.with(|s| *s.borrow_mut() = Some(State { low, index, taken, root_scope, src: src.to_string() }));
    Ok(())
}

pub fn root_scope() -> bool {
    STATE.with(|s| s.borrow().as_ref().map_or(false, |st| st.root_scope))
}

// The root scene of a `layout: schematic` document, from the lowered items.
pub fn build_root(b: &mut Builder) -> Result<(), Diag> {
    let items = STATE.with(|s| s.borrow().as_ref().map(|st| st.low.items.clone())).unwrap_or_default();
    build::build_items(b, &items, 0, Span::default())
}

// A node that is a schematic scope builds its content from its lowered self.
pub fn claims(b: &mut Builder, ns: &NodeStmt, i: usize) -> Result<bool, Diag> {
    if !active() {
        return Ok(false);
    }
    let chain = b.nodes[i].chain.clone();
    let explicit = chain.iter().any(|c| c == "schematic")
        || ns.style.as_deref().map_or(false, decls_layout_schematic)
        || chain.iter().any(|t| b.sheet.define(t).map_or(false, |d| decls_layout_schematic(&d.decls)));
    if !explicit {
        return Ok(false);
    }
    let o = match take_onode(ns.span) {
        Some(o) => o,
        None => return Ok(false),
    };
    b.nodes[i].inline = build::convert_decls(&o.decls, ns.span);
    build::build_children(b, &o, i)?;
    Ok(true)
}

// ---------------------------------------------------------------- helpers

pub fn in_family(ctx: &Ctx, i: usize) -> bool {
    chain_has(&ctx.nodes[i].chain, FAMILY)
}

pub fn is_scope(ctx: &Ctx, i: usize) -> bool {
    ctx.comp[i].layout == "schematic"
}

// A turned run's name reads up its length.
pub fn text_rotation(ctx: &Ctx, i: usize) -> Option<f64> {
    let p = ctx.nodes[i].parent?;
    if place::has(ctx, p, "net-run-turned") && in_scope(ctx, p) {
        return Some(270.0);
    }
    None
}

fn in_scope(ctx: &Ctx, i: usize) -> bool {
    let mut cur = ctx.nodes[i].parent;
    while let Some(k) = cur {
        if is_scope(ctx, k) {
            return true;
        }
        cur = ctx.nodes[k].parent;
    }
    false
}

// A seated component's body: its box centre sits off its origin.
pub fn shape_override(ctx: &Ctx, i: usize) -> Option<Vec<String>> {
    let n = &ctx.nodes[i];
    if n.prim != crate::types::Prim::Block || n.geo_off == (0.0, 0.0) || !place::is_component(ctx, i) {
        return None;
    }
    if n.w == 0.0 || n.h == 0.0 {
        return Some(vec![]);
    }
    let r = ctx.comp[i].radius;
    let f4 = crate::util::f4;
    Some(vec![format!(
        "<rect x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" rx=\"{}\" ry=\"{}\"/>",
        f4(-n.w / 2.0 - n.geo_off.0),
        f4(-n.h / 2.0 - n.geo_off.1),
        f4(n.w),
        f4(n.h),
        f4(r),
        f4(r)
    )])
}

// every variable the lowered stylesheet names is declared
pub fn sheet_vars(vars: &mut Vec<String>) {
    STATE.with(|s| {
        if let Some(st) = s.borrow().as_ref() {
            for l in &st.low.sheet {
                let ds = match l {
                    crate::desugar::SheetLine::Rule(_, ds) => ds,
                    _ => continue,
                };
                for d in ds {
                    for g in &d.groups {
                        for t in g {
                            if let Some(v) = t.strip_prefix("--") {
                                if v.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
                                    crate::style::use_var(vars, v);
                                }
                            }
                        }
                    }
                }
            }
        }
    });
}

// A part, pin, net label or junction outside every schematic scope is an
// error: the first one in document order.
pub fn check_scopes(ctx: &Ctx) -> Result<(), Diag> {
    // a wire drawn twice between the same two points
    let mut seen: Vec<(usize, usize, usize)> = Vec::new();
    for (k, l) in ctx.links.iter().enumerate() {
        if ctx.comp[l.container].layout != "schematic" {
            continue;
        }
        let key = (l.from.min(l.to), l.from.max(l.to));
        if let Some(&(_, _, first)) = seen.iter().find(|s| (s.0, s.1) == key) {
            let rel = |i: usize| -> String {
                let full = crate::links::path_of(ctx, i);
                let base = crate::links::path_of(ctx, l.container);
                match full.strip_prefix(&format!("{}.", base)) {
                    Some(r) if !base.is_empty() => r.to_string(),
                    _ => full,
                }
            };
            let (pl, pc) = crate::diag::line_col(&ctx.src, ctx.links[first].span.start);
            return Err(Diag {
                related: Some(ctx.links[first].span),
                ..Diag::error(
                "duplicate-wire",
                &format!(
                    "'{} - {}' is already wired — a repeated wire means nothing on a sheet (previously at {}:{})",
                    rel(l.from),
                    rel(l.to),
                    pl,
                    pc
                ),
                l.span,
            )
            });
        }
        seen.push((key.0, key.1, k));
    }
    let mut stack = vec![0usize];
    while let Some(i) = stack.pop() {
        if ctx.comp[i].layout == "schematic" {
            continue;
        }
        let n = &ctx.nodes[i];
        if i != 0 && chain_has(&n.chain, FAMILY) {
            let ty = n.chain.first().cloned().unwrap_or_default();
            return Err(Diag::error("schematic-type", &format!("'|{}|' belongs in a 'layout: schematic'", ty), n.span));
        }
        for &c in n.children.iter().rev() {
            stack.push(c);
        }
    }
    Ok(())
}
