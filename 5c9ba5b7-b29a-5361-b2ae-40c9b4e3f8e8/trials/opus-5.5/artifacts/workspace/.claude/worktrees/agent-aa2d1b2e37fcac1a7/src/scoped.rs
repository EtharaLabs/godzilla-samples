// Scoped (descendant) rules: `|box| .c { … }`, `.a .b { … }`, `#a |oval| { … }`,
// `|group| |box| { … }`.
//
// A rule whose selector has two or more compounds applies to a node matching
// its last compound inside ancestors matching the rest, in order. Between two
// plain types (`|A| |B|`) it is written to the stylesheet as `.lini-A
// .lini-B`; any other shape resolves onto each matching node's inline style.
// In the cascade a scoped rule sits after the type rules and before classes.

use crate::ast::{Compound, Decl, Term, Value};
use crate::compile::Ctx;
use crate::diag::Diag;
use crate::scene::{Node, SheetModel};

// Is this selector a plain two-type descendant (emitted as CSS)?
pub fn is_css(sel: &[Compound]) -> bool {
    sel.len() == 2 && sel.iter().all(|c| c.bars && c.id.is_none() && c.classes.is_empty() && c.type_name.as_deref() != Some("-"))
}

fn compound_matches(c: &Compound, n: &Node) -> bool {
    if let Some(t) = &c.type_name {
        if !n.is(t) {
            return false;
        }
    }
    if let Some(id) = &c.id {
        if n.id.as_deref() != Some(id.as_str()) {
            return false;
        }
    }
    c.classes.iter().all(|cl| n.classes.contains(cl))
}

// Do the compounds match ancestors from `from` outwards, innermost last?
fn within(scope: &[Compound], nodes: &[Node], from: Option<usize>) -> bool {
    let mut k = scope.len();
    let mut cur = from;
    while k > 0 {
        k -= 1;
        loop {
            let p = match cur {
                Some(p) if p != 0 => p,
                _ => return false,
            };
            cur = nodes[p].parent;
            if compound_matches(&scope[k], &nodes[p]) {
                break;
            }
        }
    }
    true
}

// Does node `i` match the selector (last compound on it, the rest on its
// ancestors)?
fn matches(sel: &[Compound], nodes: &[Node], i: usize) -> bool {
    let (last, scope) = sel.split_last().unwrap();
    compound_matches(last, &nodes[i]) && within(scope, nodes, nodes[i].parent)
}

// A link's scoped rules (`|box| |-| { … }`, `#g |-| { … }`): those whose
// leading compounds match its container and the container's ancestors.
pub fn link_decls(ctx: &Ctx, l: &crate::scene::Link) -> Vec<(String, Value)> {
    let mut out: Vec<(String, Value)> = Vec::new();
    for (scope, ds) in &ctx.sheet.scoped_link_rules {
        if within(scope, &ctx.nodes, Some(l.container)) {
            for d in ds {
                out.retain(|e| e.0 != d.name);
                out.push((d.name.clone(), d.value.clone()));
            }
        }
    }
    out
}

// What of them rides inline: whatever the link's classes leave alone.
pub fn link_inline(ctx: &Ctx, l: &crate::scene::Link, scoped: &[(String, Value)]) -> Vec<(String, Value)> {
    let by_class = |k: &str| ctx.sheet.worn(&l.classes).any(|cr| cr.decls.iter().any(|d| d.name == k));
    scoped.iter().filter(|(k, _)| !by_class(k)).cloned().collect()
}

// The scoped rules that reach node `i`, in source order: (decls, is_css).
pub fn matching<'a>(sheet: &'a SheetModel, nodes: &[Node], i: usize) -> Vec<(&'a [Decl], bool)> {
    if i == 0 || nodes[i].prim == crate::types::Prim::Text {
        return vec![];
    }
    sheet
        .scoped_rules
        .iter()
        .filter(|(sel, _, _)| matches(sel, nodes, i))
        .map(|(sel, decls, _)| (decls.as_slice(), is_css(sel)))
        .collect()
}

// Their declarations as cascade entries.
pub fn decls(sheet: &SheetModel, nodes: &[Node], i: usize) -> Vec<(String, Value)> {
    let mut out = Vec::new();
    for (ds, _) in matching(sheet, nodes, i) {
        out.extend(ds.iter().map(|d| (d.name.clone(), d.value.clone())));
    }
    out
}

// Inline-style adjustments for a node a scoped rule reaches. The stylesheet
// (`rule_props`) gains the plain-type descendant rules, which outrank classes
// there; the node's own declarations (`own`) gain what the cascade wants for
// every property a scoped rule touches (a class outranks them all). What
// the stylesheet already shows is dropped later.
pub fn adjust_inline(ctx: &Ctx, i: usize, rule_props: &mut Vec<(String, Value)>, own: &mut Vec<(String, Value)>) {
    let found = matching(&ctx.sheet, &ctx.nodes, i);
    if found.is_empty() {
        return;
    }
    let set = |v: &mut Vec<(String, Value)>, k: &str, val: &Value| {
        v.retain(|e| e.0 != k);
        v.push((k.to_string(), val.clone()));
    };
    let mut touched: Vec<(String, Value)> = Vec::new();
    for (ds, css) in found {
        for d in ds {
            if css {
                if is_gradient(&d.value) {
                    // the rule shows the gradient's text; its paint rides inline
                    rule_props.retain(|e| e.0 != d.name);
                } else {
                    set(rule_props, &d.name, &d.value);
                }
            }
            set(&mut touched, &d.name, &d.value);
        }
    }
    let n = &ctx.nodes[i];
    let mut class_vals: Vec<(String, Value)> = Vec::new();
    for cr in ctx.sheet.worn(&n.classes) {
        for d in &cr.decls {
            set(&mut class_vals, &d.name, &d.value);
        }
    }
    for (k, v) in touched {
        let want = class_vals.iter().find(|e| e.0 == k).map(|e| e.1.clone()).unwrap_or(v);
        set(own, &k, &want);
    }
}

// The stroke dasharray the stylesheet shows a node: each rule writes its
// own from its own stroke width (else 0), and the last rule in CSS order
// that sets a stroke style wins (descendant rules, then classes in sheet
// order); `None` leaves the type's.
pub fn shown_dash(ctx: &Ctx, i: usize) -> Option<String> {
    let mut shown = None;
    for (ds, css) in matching(&ctx.sheet, &ctx.nodes, i) {
        if css {
            if let Some(d) = rule_dash(ctx, ds) {
                shown = Some(d);
            }
        }
    }
    shown.or_else(|| class_dash(ctx, &ctx.nodes[i].classes))
}

// (a rule's own dashes, when it sets a stroke style)
fn rule_dash(ctx: &Ctx, ds: &[Decl]) -> Option<String> {
    let env = &ctx.sheet.env;
    let st = ds.iter().rev().find(|d| d.name == "stroke-style")?;
    let sw = ds.iter().rev().find(|d| d.name == "stroke-width").and_then(|d| crate::style::value_num(env, &d.value)).unwrap_or(0.0);
    Some(crate::style::ident_of(&st.value).and_then(|s| crate::style::dasharray(s, sw)).unwrap_or_else(|| "none".to_string()))
}

// The dashes the worn classes show (the last in sheet order that sets a
// stroke style).
pub fn class_dash(ctx: &Ctx, classes: &[String]) -> Option<String> {
    let mut shown = None;
    for c in &ctx.sheet.classes {
        if classes.contains(&c.name) {
            if let Some(d) = rule_dash(ctx, &c.decls) {
                shown = Some(d);
            }
        }
    }
    shown
}

fn is_gradient(v: &Value) -> bool {
    matches!(crate::style::single_term(v), Some(Term::Call(name, _, _)) if crate::paint::is_gradient(name))
}

// The plain-type descendant rules whose types are both drawn, as
// stylesheet slots. A gradient is written as its text (the nodes it reaches
// carry the paint server inline).
pub fn css_rules(ctx: &Ctx, used_types: &[String], vars: &mut Vec<String>) -> Result<Vec<(String, String)>, Diag> {
    let mut slots = Vec::new();
    for (k, (sel, decls, _)) in ctx.sheet.scoped_rules.iter().enumerate() {
        if !is_css(sel) {
            continue;
        }
        let (a, b) = (sel[0].type_name.clone().unwrap_or_default(), sel[1].type_name.clone().unwrap_or_default());
        if !used_types.contains(&a) || !used_types.contains(&b) {
            continue;
        }
        let mut props: Vec<(String, Value)> = Vec::new();
        for d in decls {
            props.retain(|e| e.0 != d.name);
            props.push((d.name.clone(), d.value.clone()));
        }
        let plain: Vec<(String, Value)> = props.iter().filter(|(_, v)| !is_gradient(v)).cloned().collect();
        let mut ds = crate::render::css_decls(ctx, &plain, vars, 0.0, false)?;
        for (name, v) in props.iter().filter(|(_, v)| is_gradient(v)) {
            ds.push((name.clone(), crate::paint::value_raw(v, vars)));
        }
        let rank = |k: &str| crate::style::CSS_ORDER.iter().position(|x| *x == k || (*x == "stroke-style" && k == "stroke-dasharray")).unwrap_or(99);
        ds.sort_by_key(|(k, _)| rank(k));
        if !ds.is_empty() {
            let body = ds.iter().map(|(k, v)| format!("{}: {}", k, v)).collect::<Vec<_>>().join("; ");
            slots.push((format!("@scoped:{:04}", k), format!(".lini-{} .lini-{} {{ {}; }}", a, b, body)));
        }
    }
    Ok(slots)
}
