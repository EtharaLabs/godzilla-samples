// The stylesheet of the desugared document: the root scene config (defaults
// merged with the user's), variables, bindings, one `.lini-*` rule per type or
// class the canvas wears, then the user's other rules with their selectors
// lowered.

use super::lower::{err, Cx, R};
use super::out::SheetLine;
use super::registry;
use super::syntax::{Comp, Decl, Rule, SItem};
use crate::diag::Diag;
use crate::types;

// merge `add` into `base`: a known property keeps its place, a new one is
// appended
pub fn merge(base: &mut Vec<Decl>, add: &[Decl]) {
    for d in add {
        match base.iter_mut().find(|b| b.name == d.name) {
            Some(b) => b.groups = d.groups.clone(),
            None => base.push(d.clone()),
        }
    }
}

pub fn root_layout(items: &[(SItem, crate::diag::Span)]) -> Option<String> {
    let mut layout = None;
    for (it, _) in items {
        if let SItem::Decl(d) = it {
            if d.name == "layout" {
                layout = d.first().map(|s| s.to_string());
            }
        }
    }
    layout
}

// millimetres per unit (px: none — a pixel is a pixel)
pub fn unit_mm(u: &str) -> Option<Option<f64>> {
    Some(match u {
        "px" => None,
        "mm" => Some(1.0),
        "cm" => Some(10.0),
        "m" => Some(1000.0),
        "in" => Some(25.4),
        _ => return None,
    })
}

// a `unit:` is one of the unit words
pub fn unit_ok(d: &Decl) -> bool {
    d.groups.len() == 1 && d.groups[0].len() == 1 && unit_mm(&d.groups[0][0]).is_some()
}

// px per unit at the scene's density (px per mm, 4 by default)
pub fn px_per(unit: Option<&str>, density: f64, default_px: bool) -> String {
    let mm = match unit {
        Some(u) => unit_mm(u).unwrap_or(Some(1.0)),
        None => {
            if default_px {
                None
            } else {
                Some(1.0)
            }
        }
    };
    match mm {
        None => "1".to_string(),
        Some(m) => crate::format::parse::render_number(super::lower::round_px(m * density)),
    }
}

pub fn root_decls(cx: &Cx, user: &[Decl]) -> Vec<Decl> {
    let layout = cx.root_layout.clone();
    let pad = if cx.root_pages { "0" } else { "20" };
    let mut base = vec![Decl::val("layout", &layout), Decl::val("padding", pad)];
    let gap = match layout.as_str() {
        "flow" | "grid" | "chart" | "pie" => Some("36"),
        "sequence" => Some("32 32"),
        "schematic" => Some("100"),
        "tree" => Some("64 48"),
        _ => None,
    };
    if let Some(g) = gap {
        base.push(Decl::val("gap", g));
    }
    base.push(Decl::val("font-size", "15"));
    match layout.as_str() {
        "schematic" => {
            base.push(Decl::val("clearance", "10"));
            base.push(Decl::val("fill", "--sheet"));
        }
        _ => {}
    }
    let user: Vec<Decl> = user.iter().filter(|d| d.name != "layout").cloned().collect();
    merge(&mut base, &user);
    // a scene of mindmaps takes their direction and routing, after its own
    if layout == "tree" && cx.root_mindmap {
        for (k, v) in [("direction", cx.root_mindmap_dir.as_str()), ("routing", cx.root_mindmap_routing.as_deref().unwrap_or("natural"))] {
            if !base.iter().any(|d| d.name == k) {
                base.push(Decl::val(k, v));
            }
        }
    }
    let unit = base.iter().rev().find(|d| d.name == "unit").and_then(|d| d.first().map(|s| s.to_string()));
    let ppu = match layout.as_str() {
        "drawing" | "floorplan" => Some(px_per(unit.as_deref(), cx.density, false)),
        "stack" => Some(px_per(unit.as_deref(), cx.density, true)),
        _ => None,
    };
    if let Some(p) = ppu {
        base.push(Decl::val("px-per-unit", &p));
    }
    base
}

fn type_defaults(name: &str) -> Vec<Decl> {
    if let Some(t) = types::find(name) {
        return Decl::list(t.defaults);
    }
    match registry::class_defaults(name) {
        Some(s) => Decl::list(s),
        None => Vec::new(),
    }
}

// a selector written for the desugared document
fn selector(cx: &Cx, sel: &[(Comp, crate::diag::Span)]) -> R<String> {
    let mut parts = Vec::new();
    for (c, sp) in sel {
        parts.push(match c {
            Comp::Bars { ty, id } => {
                if let Some(t) = ty {
                    if t != "-" && cx.chain(t).is_none() {
                        return Err(Diag::error("unknown-type", &format!("unknown type '{}' in selector", t), *sp));
                    }
                }
                match (ty.as_deref(), id) {
                    (Some("-"), None) => ".lini-link".to_string(),
                    (Some(t), None) => format!(".lini-{}", t),
                    (None, Some(i)) => format!("#{}", i),
                    (Some(t), Some(i)) => {
                        let t = if t == "-" { "link" } else { t };
                        format!("|lini-{}#{}|", t, i)
                    }
                    (None, None) => String::new(),
                }
            }
            Comp::Class(c) => format!(".{}", c),
            Comp::Id(i) => format!("#{}", i),
            Comp::Dim(_) => ".lini-dimension".to_string(),
        });
    }
    Ok(parts.join(" "))
}

// a lone `|type|` selects a type: its decls merge into the type's rule
fn type_rule_name(r: &Rule) -> Option<&str> {
    if r.sel.len() != 1 {
        return None;
    }
    match &r.sel[0].0 {
        Comp::Bars { ty: Some(t), id: None } if t != "-" => Some(t),
        _ => None,
    }
}

// the define table: no shadowing, no duplicates, known bases, no cycles
pub fn check_defines(cx: &Cx) -> R<()> {
    // the define table: no shadowing, no duplicates, known bases, no cycles
    const RESERVED: &[&str] = &["text", "canvas", "cut", "link", "marker", "node", "scene"];
    let mut seen: Vec<&str> = Vec::new();
    for d in &cx.defines {
        if types::find(&d.name).is_some() || RESERVED.contains(&d.name.as_str()) {
            return Err(Diag::error("define", &format!("'{}' shadows a built-in type", d.name), d.span));
        }
        if seen.contains(&d.name.as_str()) {
            return Err(Diag::error("define", &format!("duplicate type '{}'", d.name), d.span));
        }
        seen.push(&d.name);
    }
    for d in &cx.defines {
        let mut path = vec![d.name.clone()];
        let mut cur = d.base.clone();
        loop {
            if path.contains(&cur) {
                path.push(cur);
                return Err(Diag::error("define", &format!("cycle in '{}'", path.join(" → ")), d.span));
            }
            if let Some(next) = cx.define(&cur) {
                path.push(cur.clone());
                cur = next.base.clone();
                continue;
            }
            match types::find(&cur) {
                Some(t) if t.name != "text" => break,
                _ => return Err(Diag::error("unknown-type", &format!("unknown type '{}'", cur), d.span)),
            }
        }
    }
    Ok(())
}

// the selectors of the user's rules
pub fn check_selectors(cx: &Cx, items: &[(SItem, crate::diag::Span)]) -> R<()> {
    for (it, _) in items {
        if let SItem::Rule(r) = it {
            if type_rule_name(r).is_none() {
                selector(cx, &r.sel).map_err(|mut e| {
                    // reported at the selector's start
                    if let Some((_, sp)) = r.sel.first() {
                        e.span = *sp;
                    }
                    e
                })?;
            }
        }
    }
    Ok(())
}

pub fn build(cx: &Cx, items: &[(SItem, crate::diag::Span)]) -> R<Vec<SheetLine>> {
    let mut out = Vec::new();
    let user_root: Vec<Decl> = items
        .iter()
        .filter_map(|(it, _)| match it {
            SItem::Decl(d) => Some(d.clone()),
            _ => None,
        })
        .collect();
    out.push(SheetLine::Decls(root_decls(cx, &user_root)));
    for (it, _) in items {
        if let SItem::Var(d) = it {
            out.push(SheetLine::Line(d.text()));
        }
    }
    for (it, _) in items {
        if let SItem::Binding(b) = it {
            out.push(SheetLine::Line(b.clone()));
        }
    }
    // user decls for each type
    let user_rules = |name: &str| -> Vec<Decl> {
        let mut v = Vec::new();
        for (it, _) in items {
            if let SItem::Rule(r) = it {
                if type_rule_name(r) == Some(name) {
                    v.extend(r.decls.iter().cloned());
                }
            }
        }
        v
    };
    let push_rule = |out: &mut Vec<SheetLine>, name: &str, mut decls: Vec<Decl>| {
        merge(&mut decls, &user_rules(name));
        if !decls.is_empty() {
            out.push(SheetLine::Rule(format!(".lini-{}", name), decls));
        }
    };
    for name in registry::BUILTIN_ORDER {
        if cx.used.contains(*name) && cx.define(name).is_none() {
            push_rule(&mut out, name, type_defaults(name));
        }
    }
    for d in &cx.defines {
        if cx.used.contains(&d.name) {
            push_rule(&mut out, &d.name, d.decls.clone());
        }
    }
    for name in registry::UTILITY_ORDER {
        if cx.used.contains(*name) {
            push_rule(&mut out, name, type_defaults(name));
        }
    }
    for (sel, text) in super::CTX_RULES {
        if cx.ctx_rules.contains(sel) || (cx.mindmap_used && *sel == ".lini-mindmap .lini-topic") {
            out.push(SheetLine::Rule(sel.to_string(), Decl::list(text)));
        }
    }
    if cx.mindmap_used {
        for l in &cx.mindmap_levels {
            let size = match l {
                1 => "15",
                2 => "14",
                _ => "13",
            };
            out.push(SheetLine::Rule(format!(".lini-mindmap .lini-level-{}", l), Decl::list(&format!("font-size: {};", size))));
        }
        for h in super::tree::HUES {
            if cx.mindmap_hues.contains(*h) {
                out.push(SheetLine::Rule(
                    format!(".lini-mindmap .lini-hue-{}", h),
                    Decl::list(&format!("fill: --{h}-wash; stroke: --{h}-deep; color: --{h}-ink;", h = h)),
                ));
            }
        }
    }
    // the user's other rules, in order
    for (it, _) in items {
        if let SItem::Rule(r) = it {
            if type_rule_name(r).is_some() {
                // a lone type selector: merged above (or never worn)
                continue;
            }
            let sel = selector(cx, &r.sel)?;
            out.push(SheetLine::Rule(sel, r.decls.clone()));
        }
    }
    let _ = err;
    Ok(out)
}
