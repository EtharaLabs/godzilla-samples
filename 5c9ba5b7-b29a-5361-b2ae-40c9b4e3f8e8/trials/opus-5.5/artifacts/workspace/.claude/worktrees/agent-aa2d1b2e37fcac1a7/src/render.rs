// SVG serialisation: the stylesheet, defs, scene, and links.

use crate::ast::{Term, Value};
use crate::compile::{get, Ctx};
use crate::diag::Diag;
use crate::style::*;
use crate::types::{self, Prim};
use crate::util::{f4, hash8, xml_escape};

pub struct Out {
    pub body: String,
    pub vars: Vec<String>,
    pub used_types: Vec<String>,
    pub used_classes: Vec<String>,
    pub any_text: bool,
    pub defs: Vec<String>,
    pub markers: bool,
    pub gutters: bool,
    // extra stylesheet rules registered by families: (slot, rule text)
    pub extra_rules: Vec<(String, String)>,
}

fn ind(n: usize) -> String {
    " ".repeat(n)
}

// CSS declarations for one property list, in canonical order.
pub fn css_decls(
    ctx: &Ctx,
    props: &[(String, Value)],
    vars: &mut Vec<String>,
    stroke_width_ctx: f64,
    text: bool,
) -> Result<Vec<(String, String)>, Diag> {
    let env = &ctx.sheet.env;
    let mut out = Vec::new();
    for &k in CSS_ORDER {
        let v = match get(props, k) {
            Some(v) => v,
            None => continue,
        };
        let span = v.span;
        match k {
            "fill" | "stroke" => {
                if let Some(t) = single_term(v) {
                    out.push((k.to_string(), color_css(t, vars, span)?));
                } else if v.groups.len() == 1 {
                    // a run of terms passes through, each term serialised
                    let mut parts = Vec::new();
                    for t in &v.groups[0] {
                        parts.push(color_css(t, vars, span)?);
                    }
                    out.push((k.to_string(), parts.join(" ")));
                }
            }
            "color" => {
                let name = if text { "fill" } else { "color" };
                if text && get(props, "fill").is_some() {
                    continue;
                }
                if let Some(t) = single_term(v) {
                    out.push((name.to_string(), color_css(t, vars, span)?));
                } else if v.groups.len() == 1 {
                    let mut parts = Vec::new();
                    for t in &v.groups[0] {
                        parts.push(color_css(t, vars, span)?);
                    }
                    out.push((name.to_string(), parts.join(" ")));
                }
            }
            "stroke-width" | "opacity" => {
                if let Some(x) = value_num(env, v) {
                    out.push((k.to_string(), f4(x)));
                } else {
                    out.push((k.to_string(), crate::paint::value_text(v, vars)));
                }
            }
            "font-family" => out.push((k.to_string(), font_family_css(v))),
            "font-size" => {
                if let Some(x) = value_num(env, v) {
                    out.push((k.to_string(), format!("{}px", f4(x))));
                } else {
                    out.push((k.to_string(), format!("{}px", crate::paint::value_text(v, vars))));
                }
            }
            "font-weight" => out.push((k.to_string(), weight_css(v, vars, span)?)),
            "font-style" | "text-decoration" => {
                out.push((k.to_string(), crate::paint::value_text(v, vars)));
            }
            "text-shadow" => out.push((k.to_string(), text_shadow_css(env, v, vars, span)?)),
            "stroke-style" => {
                let sw = get(props, "stroke-width").and_then(|w| value_num(env, w)).unwrap_or(stroke_width_ctx);
                // an unknown style draws solid
                let d = ident_of(v).and_then(|s| dasharray(s, sw)).unwrap_or_else(|| "none".to_string());
                out.push(("stroke-dasharray".to_string(), d));
            }
            _ => {}
        }
    }
    if text {
        // on text a colour is its fill, written first
        out.sort_by_key(|(k, _)| if k == "fill" { 0 } else { 1 });
    }
    Ok(out)
}

fn join_decls(d: &[(String, String)]) -> String {
    d.iter().map(|(k, v)| format!("{}: {}", k, v)).collect::<Vec<_>>().join("; ")
}

fn font_scale_size(ctx: &Ctx, props: &[(String, Value)]) -> Option<f64> {
    let v = get(props, "font-scale")?;
    let xs = value_nums(&ctx.sheet.env, v);
    if xs.len() == 2 {
        Some(xs[0] * ctx.root_font_size / xs[1])
    } else {
        None
    }
}

// The CSS rule body of one type, from its own defaults plus user rules.
fn type_rule_props(ctx: &Ctx, t: &str) -> Vec<(String, Value)> {
    let mut props: Vec<(String, Value)> = Vec::new();
    let mut set = |k: &str, v: &Value| {
        if let Some(e) = props.iter_mut().find(|e| e.0 == k) {
            e.1 = v.clone();
        } else {
            props.push((k.to_string(), v.clone()));
        }
    };
    for d in type_defaults(t) {
        set(&d.name, &d.value);
    }
    if let Some(df) = ctx.sheet.define(t) {
        for d in &df.decls {
            set(&d.name, &d.value);
        }
    }
    for d in ctx.sheet.type_rule(t) {
        set(&d.name, &d.value);
    }
    props
}

// The dashes the drawn types' rules show: the most specific type whose rule
// sets a stroke style, drawn for that rule's own stroke width.
fn type_dash(ctx: &Ctx, n: &crate::scene::Node) -> Option<String> {
    for t in &n.chain {
        let props = type_rule_props(ctx, t);
        if let Some(st) = get(&props, "stroke-style") {
            let sw = get(&props, "stroke-width").and_then(|w| value_num(&ctx.sheet.env, w)).unwrap_or(2.0);
            return Some(ident_of(st).and_then(|s| dasharray(s, sw)).unwrap_or_else(|| "none".to_string()));
        }
    }
    None
}

// The root block's own font family, weight and text colour, as CSS.
fn base_text(ctx: &Ctx) -> (Option<String>, Option<String>, Option<String>) {
    let get = |k: &str| ctx.sheet.root.iter().rev().find(|d| d.name == k);
    let mut tmp = Vec::new();
    let fam = get("font-family").map(|d| font_family_css(&d.value));
    let wt = get("font-weight").and_then(|d| weight_css(&d.value, &mut tmp, d.span).ok());
    let col = get("color").and_then(|d| single_term(&d.value).and_then(|t| color_css(t, &mut tmp, d.span).ok()));
    (fam, wt, col)
}

fn mk_value(t: Term) -> Value {
    let sp = t.span();
    Value { groups: vec![vec![t]], span: sp }
}

pub fn render(ctx: &Ctx, opts: &crate::Options) -> Result<String, Diag> {
    let mut out = Out { body: String::new(), vars: vec![], used_types: vec![], used_classes: vec![], any_text: false, defs: vec![], markers: false, gutters: false, extra_rules: vec![] };
    crate::paint::reset(&ctx.sheet.env, opts.theme.as_deref().unwrap_or("default"));
    let root = 0;
    // scene body
    let mut scene = String::new();
    let children = ctx.nodes[root].children.clone();
    // paint servers and shadow filters register in document order (the body
    // below paints in stacking order)
    fn meet(ctx: &Ctx, i: usize, out: &mut Out) {
        let n = &ctx.nodes[i];
        if i != 0 && n.prim != Prim::Text {
            crate::paint::meet_node(ctx, i);
            if !crate::drawing::is_chrome(ctx, i) && !crate::chart::is_chart(ctx, i) {
                let _ = shadow_filter(ctx, i, out);
            }
        }
        for &c in &n.children {
            meet(ctx, c, out);
        }
    }
    meet(ctx, root, &mut out);
    let ordered = paint_order(ctx, &children);
    for ch in ordered {
        render_node(ctx, ch, 4, &mut scene, &mut out)?;
    }
    // links (registers their stylesheet rules)
    for l in &ctx.links {
        crate::paint::meet_link(ctx, l);
    }
    // (the rules a link wears register with the stylesheet)
    let links_layer = crate::paint::dry(|| crate::links::render(ctx, &mut out))?;
    if scene.contains("lini-marker-open") && !out.extra_rules.iter().any(|(k, _)| k == "marker-open") {
        out.extra_rules.push((
            "marker-open".into(),
            ".lini-marker.lini-marker-open { fill: none; stroke: inherit; stroke-linecap: round; stroke-dasharray: none; }".to_string(),
        ));
    }
    // the rules' paint servers, in the order the stylesheet meets them
    let mut css_types: Vec<String> = out.used_types.iter().filter(|t| *t != "image").cloned().collect();
    css_types.sort_by_key(|t| {
        let slot = if types::find(t).is_some() { t.clone() } else { format!("@define:{:04}", ctx.sheet.defines.iter().position(|d| &d.name == t).unwrap_or(0)) };
        slot_rank(&slot)
    });
    crate::paint::meet_rules(ctx, &css_types);
    // stylesheet
    let theme = crate::theme::resolve(opts.theme.as_deref().unwrap_or("default")).unwrap();
    let mut slots: Vec<(String, String)> = Vec::new();
    let type_names: Vec<String> = out.used_types.clone();
    for t in &type_names {
        if t == "image" {
            continue; // an image's paint never reaches its pixels: no rule
        }
        let mut props = type_rule_props(ctx, t);
        if let Some(sz) = font_scale_size(ctx, &props) {
            if get(&props, "font-size").is_none() {
                props.push(("font-size".into(), mk_value(Term::Num(sz, f4(sz), Default::default()))));
            }
        }
        let is_prim = types::find(t).map(|d| d.base.is_none()).unwrap_or(false);
        if is_prim && get(&props, "stroke-style").is_none() {
            props.push(("stroke-style".into(), mk_value(Term::Ident("solid".into(), Default::default()))));
        }
        let sw = get(&props, "stroke-width").and_then(|w| value_num(&ctx.sheet.env, w)).unwrap_or(2.0);
        let decls = css_decls(ctx, &props, &mut out.vars, sw, false)?;
        if !decls.is_empty() {
            let slot = if types::find(t).is_some() {
                t.clone()
            } else {
                format!("@define:{:04}", ctx.sheet.defines.iter().position(|d| &d.name == t).unwrap_or(0))
            };
            slots.push((slot, format!(".lini-{} {{ {}; }}", t, join_decls(&decls))));
        }
    }
    if out.any_text {
        slots.push(("text".into(), ".lini-text { fill: currentColor; stroke: none; text-anchor: middle; }".to_string()));
    }
    if out.gutters {
        slots.push(("gutter".into(), ".lini-gutter { stroke: none; }".to_string()));
    }
    if out.markers {
        slots.push(("marker".into(), ".lini-marker { fill: var(--lini-stroke); stroke: none; }".to_string()));
        use_var(&mut out.vars, "stroke");
    }
    for (k, c) in ctx.sheet.classes.iter().enumerate() {
        if out.used_classes.contains(&c.name) {
            // a property repeated in the rule keeps its last value
            let mut props: Vec<(String, Value)> = Vec::new();
            for d in &c.decls {
                props.retain(|e| e.0 != d.name);
                props.push((d.name.clone(), d.value.clone()));
            }
            // (a stroke style's dashes follow the rule's own stroke width, else 0)
            let decls = css_decls(ctx, &props, &mut out.vars, 0.0, false)?;
            if !decls.is_empty() {
                slots.push((format!("@class:{:04}", k), format!(".lini-style-{} {{ {}; }}", c.name, join_decls(&decls))));
            }
        }
    }
    // plain-type descendant rules, when both types are drawn
    slots.extend(crate::scoped::css_rules(ctx, &out.used_types, &mut out.vars)?);
    // the canvas paints the root `fill:` (--static always paints, with --bg)
    let canvas_fill = match ctx.sheet.root.iter().rev().find(|d| d.name == "fill") {
        Some(d) => {
            let props = vec![("fill".to_string(), d.value.clone())];
            css_decls(ctx, &props, &mut out.vars, 2.0, false)?.into_iter().next().map(|(_, v)| v)
        }
        None if opts.static_ => {
            use_var(&mut out.vars, "bg");
            Some("var(--lini-bg)".to_string())
        }
        None => None,
    };
    if let Some(f) = &canvas_fill {
        slots.push(("canvas".into(), format!(".lini-canvas {{ fill: {}; }}", f)));
    }
    for (slot, rule) in &out.extra_rules {
        // a family's fallback rule for a primitive yields to the real type rule
        if type_names.contains(slot) {
            continue;
        }
        slots.push((slot.clone(), rule.clone()));
    }
    slots.sort_by(|a, b| slot_rank(&a.0).cmp(&slot_rank(&b.0)));
    let mut rules: Vec<String> = Vec::new();
    for (_, r) in slots {
        if !rules.contains(&r) {
            rules.push(r);
        }
    }
    // root variables
    let mut vars = out.vars.clone();
    crate::paint::register_stray(ctx);
    crate::paint::register_stray_links(ctx);
    for v in crate::paint::vars() {
        crate::style::use_var(&mut vars, &v);
    }
    for v in crate::paint::decl_vars(ctx, &out.used_types) {
        crate::style::use_var(&mut vars, &v);
    }
    // the base rules read the theme's font and text colour unless the root
    // block sets its own
    let base = base_text(ctx);
    for (v, own) in [("font-family", &base.0), ("font-weight", &base.1), ("text-color", &base.2)] {
        if own.is_none() {
            crate::style::use_var(&mut vars, v);
        }
    }
    let mut decl_vars: Vec<(String, String)> = Vec::new();
    let mut k = 0;
    while k < vars.len() {
        let v = vars[k].clone();
        k += 1;
        let user = ctx.sheet.vars.iter().rev().find(|d| d.name == v);
        let val = if let Some(d) = user {
            let mut vv = Vec::new();
            let s = value_css_text(ctx, &d.value, &mut vv);
            for x in vv {
                if !vars.contains(&x) {
                    vars.push(x);
                }
            }
            Some(s)
        } else if v == "font-family" && opts.embed_font && !opts.static_ && theme.css_value(&v).as_deref() == Some(crate::theme::FONT_FAMILY) {
            // the embedded face leads the stock stack (a theme file's own stack stands)
            theme.css_value(&v).map(|f| format!("\"Lini Sans\", {}", f))
        } else {
            theme.css_value(&v)
        };
        if let Some(val) = val {
            // nested var() references pull their targets in too
            let mut rest = val.as_str();
            while let Some(p) = rest.find("var(--lini-") {
                let after = &rest[p + 11..];
                let end = after.find(')').unwrap_or(after.len());
                let name = after[..end].to_string();
                if !vars.contains(&name) {
                    vars.push(name);
                }
                rest = &after[end..];
            }
            decl_vars.push((v, val));
        }
    }
    decl_vars.sort_by(|a, b| a.0.cmp(&b.0));
    // a light/dark pair anywhere in use switches the color-scheme on
    let paired = decl_vars.iter().any(|(_, v)| v.contains("light-dark("));
    let mut css = String::new();
    css.push_str("    @layer lini.defaults {\n");
    let mut root_line = String::from("      :root, .lini {");
    if paired {
        root_line.push_str(" color-scheme: light dark;");
    }
    for (k, v) in &decl_vars {
        root_line.push_str(&format!(" --lini-{}: {};", k, v));
    }
    root_line.push_str(" }\n");
    css.push_str(&root_line);
    if paired {
        css.push_str("      .lini[data-theme=\"dark\"], [data-theme=\"dark\"] .lini { color-scheme: dark; }\n");
        css.push_str("      .lini[data-theme=\"light\"], [data-theme=\"light\"] .lini { color-scheme: light; }\n");
    }
    css.push_str("    }\n");
    css.push_str(&format!(
        "    .lini, .lini text {{ font-family: {}; }}\n",
        base.0.clone().unwrap_or_else(|| "var(--lini-font-family)".to_string())
    ));
    css.push_str(&format!(
        "    .lini {{ font-size: {}px; font-weight: {}; color: {}; }}\n",
        f4(ctx.root_font_size),
        base.1.clone().unwrap_or_else(|| "var(--lini-font-weight)".to_string()),
        base.2.clone().unwrap_or_else(|| "var(--lini-text-color)".to_string())
    ));
    for r in &rules {
        css.push_str(&format!("    .lini {}\n", r));
    }
    let mut defs: Vec<String> = out.defs.clone();
    defs.extend(crate::paint::defs());
    // --static / --embed-font: replay the cascade over the text
    let mut scene = scene;
    let mut links_layer = links_layer;
    let mut font_faces = String::new();
    if opts.static_ || opts.embed_font {
        let vars = crate::outline::Vars::new(&decl_vars);
        let mut pass = crate::outline::Pass::new(&css, &vars, opts.static_, ctx);
        if opts.static_ {
            scene = crate::outline::drop_tips(&scene);
        }
        scene = pass.run(&scene);
        links_layer = pass.run(&links_layer);
        if opts.embed_font {
            font_faces = pass.font_faces();
        }
        if opts.static_ {
            css = vars.bake(&crate::outline::drop_tips_css(&crate::outline::drop_layer(&css)));
            scene = vars.bake(&pass.dedup(&scene));
            links_layer = vars.bake(&pass.dedup(&links_layer));
            defs = defs.iter().map(|d| crate::outline::stops_to_attrs(&vars.bake(d))).collect();
            defs.extend(pass.glyph_defs());
        }
    }
    let hash = hash8(&css);
    let scope = format!("lini-scope-{}", hash);
    let css_scoped = scope_css(&css, &scope);
    // the frame
    let (vx, vy, vw, vh) = viewbox(ctx);
    // a bare sheet document states its paper size in mm
    let (sw, sh) = match crate::page::svg_mm(ctx) {
        Some(k) => (format!("{}mm", f4(vw / k)), format!("{}mm", f4(vh / k))),
        None => (f4(vw), f4(vh)),
    };
    let mut s = String::new();
    s.push_str(&format!(
        "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"{} {} {} {}\" width=\"{}\" height=\"{}\" class=\"lini {}\">\n",
        f4(vx),
        f4(vy),
        f4(vw),
        f4(vh),
        sw,
        sh,
        scope
    ));
    s.push_str("  <style>\n");
    s.push_str(&font_faces);
    s.push_str(&css_scoped);
    s.push_str("  </style>\n");
    if defs.is_empty() {
        s.push_str("  <defs/>\n");
    } else {
        s.push_str("  <defs>\n");
        for d in &defs {
            s.push_str(&format!("    {}\n", d));
        }
        s.push_str("  </defs>\n");
    }
    if canvas_fill.is_some() {
        s.push_str(&format!(
            "  <rect class=\"lini-canvas\" x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\"/>\n",
            f4(vx),
            f4(vy),
            f4(vw),
            f4(vh)
        ));
    }
    s.push_str("  <g class=\"lini-scene\">\n");
    s.push_str(&scene);
    s.push_str("  </g>\n");
    s.push_str(&links_layer);
    s.push_str("</svg>\n");
    Ok(s)
}

fn scope_css(css: &str, scope: &str) -> String {
    // replace the '.lini' scope selector (not '.lini-xxx' classes)
    let mut o = String::new();
    let b = css.as_bytes();
    let mut i = 0;
    while i < b.len() {
        if css[i..].starts_with(".lini") {
            let next = b.get(i + 5).copied().unwrap_or(b' ');
            if next != b'-' {
                o.push('.');
                o.push_str(scope);
                i += 5;
                continue;
            }
        }
        let ch = css[i..].chars().next().unwrap();
        o.push(ch);
        i += ch.len_utf8();
    }
    o
}

pub fn value_css_text(ctx: &Ctx, v: &Value, vars: &mut Vec<String>) -> String {
    let mut parts = Vec::new();
    for g in &v.groups {
        let mut gp = Vec::new();
        for t in g {
            match t {
                Term::Num(x, _, _) => gp.push(f4(*x)),
                Term::Percent(x, _, _) => gp.push(format!("{}%", f4(*x))),
                Term::Var(n, _) => {
                    use_var(vars, n);
                    gp.push(format!("var(--lini-{})", n));
                }
                Term::Hash(h, _) => gp.push(format!("#{}", h)),
                Term::Ident(n, _) => gp.push(n.clone()),
                Term::Str(s, _) => gp.push(format!("\"{}\"", s)),
                _ => {
                    if let Ok(c) = color_css(t, vars, v.span) {
                        gp.push(c);
                    }
                }
            }
        }
        parts.push(gp.join(" "));
    }
    let _ = ctx;
    parts.join(", ")
}

pub fn viewbox(ctx: &Ctx) -> (f64, f64, f64, f64) {
    let r = &ctx.nodes[0];
    let pad = ctx.comp[0].padding;
    let mut b = [-r.w / 2.0 + pad[3], -r.h / 2.0 + pad[0], r.w / 2.0 - pad[1], r.h / 2.0 - pad[2]];
    // a stack / drawing root keeps its datum: the view is its content
    let frame = crate::drawing::is_frame(ctx, 0);
    if frame {
        b = [f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY];
    }
    let ident = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0];
    for &ch in &r.children {
        bbox_walk(ctx, ch, &ident, &mut b);
    }
    if frame && b[0] > b[2] {
        b = [0.0, 0.0, 0.0, 0.0];
    }
    crate::links::extend_bbox(ctx, &mut b);
    let x0 = b[0] - pad[3];
    let y0 = b[1] - pad[0];
    let x1 = b[2] + pad[1];
    let y1 = b[3] + pad[2];
    (x0, y0, x1 - x0, y1 - y0)
}

// affine [a b c d e f]: x' = a x + c y + e, y' = b x + d y + f
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

pub fn node_matrix(ctx: &Ctx, i: usize) -> [f64; 6] {
    let n = &ctx.nodes[i];
    let c = &ctx.comp[i];
    let t = [1.0, 0.0, 0.0, 1.0, n.x + c.translate.0, n.y + c.translate.1];
    if c.rotate != 0.0 {
        let a = c.rotate.to_radians();
        let r = [a.cos(), a.sin(), -a.sin(), a.cos(), 0.0, 0.0];
        mul(&t, &r)
    } else {
        t
    }
}

// The frame a node's group draws in: translate(position + geometry offset)
// then its rotation — what `render_node` writes as its transform.
pub fn group_matrix(ctx: &Ctx, i: usize) -> [f64; 6] {
    let n = &ctx.nodes[i];
    let c = &ctx.comp[i];
    let t = [1.0, 0.0, 0.0, 1.0, n.x + c.translate.0 + n.geo_off.0, n.y + c.translate.1 + n.geo_off.1];
    if c.rotate != 0.0 {
        let a = c.rotate.to_radians();
        let r = [a.cos(), a.sin(), -a.sin(), a.cos(), 0.0, 0.0];
        mul(&t, &r)
    } else {
        t
    }
}

fn bbox_walk(ctx: &Ctx, i: usize, parent: &[f64; 6], b: &mut [f64; 4]) {
    let n = &ctx.nodes[i];
    let m = mul(parent, &group_matrix(ctx, i));
    let (ow, oh) = crate::layout::outer(ctx, i);
    let (cx, cy) = (-n.geo_off.0, -n.geo_off.1);
    let corners = if crate::drawing::skip_box(ctx, i) {
        vec![]
    } else {
        vec![(-ow / 2.0, -oh / 2.0), (ow / 2.0, -oh / 2.0), (ow / 2.0, oh / 2.0), (-ow / 2.0, oh / 2.0)]
    };
    for (px, py) in corners {
        let (px, py) = (px + cx, py + cy);
        let x = m[0] * px + m[2] * py + m[4];
        let y = m[1] * px + m[3] * py + m[5];
        b[0] = b[0].min(x);
        b[1] = b[1].min(y);
        b[2] = b[2].max(x);
        b[3] = b[3].max(y);
    }
    if let Some(cb) = crate::chart::content_bbox(i) {
        for (px, py) in [(cb[0], cb[1]), (cb[2], cb[1]), (cb[2], cb[3]), (cb[0], cb[3])] {
            if px.is_finite() && py.is_finite() {
                let x = m[0] * px + m[2] * py + m[4];
                let y = m[1] * px + m[3] * py + m[5];
                b[0] = b[0].min(x);
                b[1] = b[1].min(y);
                b[2] = b[2].max(x);
                b[3] = b[3].max(y);
            }
        }
        return;
    }
    if n.prim != Prim::Text {
        for &ch in &n.children {
            bbox_walk(ctx, ch, &m, b);
        }
    }
}

pub fn paint_order(ctx: &Ctx, children: &[usize]) -> Vec<usize> {
    let mut flow: Vec<usize> = Vec::new();
    let mut pinned: Vec<usize> = Vec::new();
    for &c in children {
        if ctx.comp[c].pin.is_some() {
            pinned.push(c);
        } else {
            flow.push(c);
        }
    }
    flow.extend(pinned);
    flow
}

pub fn node_classes(ctx: &Ctx, i: usize, out: &mut Out) -> String {
    let n = &ctx.nodes[i];
    let mut cls = vec!["lini-node".to_string()];
    for t in &n.chain {
        cls.push(format!("lini-{}", t));
        if !out.used_types.contains(t) {
            out.used_types.push(t.clone());
        }
    }
    for c in &n.classes {
        cls.push(format!("lini-style-{}", c));
        if !out.used_classes.contains(c) {
            out.used_classes.push(c.clone());
        }
    }
    cls.join(" ")
}

// Inline CSS: the node's own declarations minus what its rules already say.
pub fn inline_style(ctx: &Ctx, i: usize, out: &mut Out, text: bool) -> Result<String, Diag> {
    let n = &ctx.nodes[i];
    let (mut rule_props, _) = crate::compile::cascade(&ctx.sheet, n);
    let scoped = crate::scoped::decls(&ctx.sheet, &ctx.nodes, i);
    let (_, all) = crate::compile::cascade_with(&ctx.sheet, n, &scoped);
    let mut own: Vec<(String, Value)> = Vec::new();
    // no `.lini-image` rule is emitted: the image type's own rules ride inline
    let sw_default = if n.prim == Prim::Image { crate::image::inline_type_rules(ctx, n, &mut own, &mut rule_props) } else { 2.0 };
    crate::scoped::adjust_inline(ctx, i, &mut rule_props, &mut own);
    if let Some(id) = &n.id {
        for (rid, ds) in &ctx.sheet.id_rules {
            if rid == id {
                for d in ds {
                    own.retain(|e| e.0 != d.name);
                    own.push((d.name.clone(), d.value.clone()));
                }
            }
        }
    }
    for d in &n.inline {
        own.retain(|e| e.0 != d.name);
        own.push((d.name.clone(), d.value.clone()));
    }
    let sw_all = get(&all, "stroke-width").and_then(|w| value_num(&ctx.sheet.env, w)).unwrap_or(sw_default);
    let mut tmp = Vec::new();
    let own_d = css_decls(ctx, &own, &mut tmp, sw_all, text)?;
    let mut tmp2 = Vec::new();
    // the primitive's rule always states a solid stroke style
    if get(&rule_props, "stroke-style").is_none() && n.prim != Prim::Image {
        rule_props.push(("stroke-style".into(), mk_value(Term::Ident("solid".into(), Default::default()))));
    }
    let sw_rule = get(&rule_props, "stroke-width").and_then(|w| value_num(&ctx.sheet.env, w)).unwrap_or(sw_default);
    let mut rule_d = crate::paint::dry(|| css_decls(ctx, &rule_props, &mut tmp2, sw_rule, text))?;
    // the dashes the stylesheet shows were drawn for the width of the rule
    // that sets the style: a class or descendant rule's own, else the type's
    let shown = crate::scoped::shown_dash(ctx, i).or_else(|| type_dash(ctx, n));
    if let Some(d) = &shown {
        if let Some(e) = rule_d.iter_mut().find(|(k, _)| k == "stroke-dasharray") {
            e.1 = d.clone();
        }
    }
    let mut keep = Vec::new();
    let mut own_d = own_d;
    if text {
        if let Some(fam) = &ctx.comp[i].family_css {
            if !own_d.iter().any(|(k, _)| k == "font-family") {
                own_d.push(("font-family".into(), fam.clone()));
                let pos = |k: &str| CSS_ORDER.iter().position(|x| *x == k || (*x == "stroke-style" && k == "stroke-dasharray") || (*x == "color" && k == "fill" && false)).unwrap_or(99);
                own_d.sort_by_key(|(k, _)| if k == "fill" { 0 } else { pos(k) });
            }
        }
    }
    for (k, v) in own_d {
        if rule_d.iter().any(|(rk, rv)| rk == &k && rv == &v) {
            continue;
        }
        keep.push((k, v));
    }
    // stroke-style depends on the effective stroke width
    if get(&own, "stroke-style").is_none() {
        if let Some(st) = get(&all, "stroke-style").and_then(ident_of) {
            if st != "solid" {
                if let Some(d) = dasharray(st, sw_all) {
                    if shown.as_ref() != Some(&d) && !keep.iter().any(|(k, _)| k == "stroke-dasharray") {
                        keep.push(("stroke-dasharray".into(), d));
                    }
                }
            }
        }
    }
    // a font-scale resolves against the parent's size, the rule against the root's
    if !text && get(&own, "font-size").is_none() && get(&all, "font-size").is_none() {
        if let Some(rule_sz) = font_scale_size(ctx, &all) {
            let sz = ctx.comp[i].font_size;
            if (sz - rule_sz).abs() > 1e-9 {
                let pos = |k: &str| CSS_ORDER.iter().position(|x| *x == k || (*x == "stroke-style" && k == "stroke-dasharray")).unwrap_or(99);
                let at = keep.iter().position(|(k, _)| pos(k) > pos("font-size")).unwrap_or(keep.len());
                keep.insert(at, ("font-size".to_string(), format!("{}px", f4(sz))));
            }
        }
    }
    let mut vars = Vec::new();
    let _ = css_decls(ctx, &own, &mut vars, sw_all, text)?;
    for (k, _) in &keep {
        let _ = k;
    }
    for v in vars {
        // only vars that survive into the emitted style count
        if keep.iter().any(|(_, val)| val.contains(&format!("var(--lini-{})", v))) {
            use_var(&mut out.vars, &v);
        }
    }
    Ok(join_decls(&keep))
}

fn render_text(ctx: &Ctx, i: usize, ind_n: usize, s: &mut String, out: &mut Out) -> Result<(), Diag> {
    out.any_text = true;
    let n = &ctx.nodes[i];
    let c = &ctx.comp[i];
    let style = inline_style(ctx, i, out, true)?;
    let mut extra = String::new();
    let x = n.x + c.translate.0;
    let y = n.y + c.translate.1;
    let fam_attr = if let Some(v) = n.inline.iter().find(|d| d.name == "font-family") {
        Some(font_family_css(&v.value))
    } else {
        None
    };
    let _ = fam_attr;
    if !style.is_empty() {
        extra = format!(" style=\"{}\"", xml_escape(&style));
    }
    // worn classes ride the text element
    let mut tcls = String::from("lini-text");
    for k in &n.classes {
        tcls.push_str(&format!(" lini-style-{}", k));
        if !out.used_classes.contains(k) {
            out.used_classes.push(k.clone());
        }
    }
    let lines = &n.lines;
    let ls = c.letter_spacing;
    let dx_for = |l: &str| -> String {
        let cnt = l.chars().count();
        if ls != 0.0 && cnt > 1 {
            let mut v = vec!["0".to_string()];
            for _ in 1..cnt {
                v.push(f4(ls));
            }
            format!(" dx=\"{}\"", v.join(" "))
        } else {
            String::new()
        }
    };
    crate::outline::note(x);
    crate::outline::note(y);
    if lines.len() <= 1 {
        let l = lines.first().cloned().unwrap_or_default();
        s.push_str(&format!(
            "{}<text class=\"{}\" x=\"{}\" y=\"{}\" dy=\"0.358em\"{}{}>{}</text>\n",
            ind(ind_n),
            tcls,
            f4(x),
            f4(y),
            dx_for(&l),
            extra,
            xml_escape(&l)
        ));
    } else {
        let pitch = 1.2 * c.font_size + c.line_spacing;
        let total = (lines.len() as f64 - 1.0) * pitch;
        let first = y - total / 2.0 + 0.358 * c.font_size;
        let mut t = String::new();
        // lines flush by the holding box's horizontal knob
        let knob = crate::table::text_flush(ctx, i);
        for (k, l) in lines.iter().enumerate() {
            let slack = n.w - crate::layout::line_width(ctx, i, l);
            let lx = match knob {
                crate::compile::Align::Start => x - slack / 2.0,
                crate::compile::Align::End => x + slack / 2.0,
                _ => x,
            };
            crate::outline::note(lx);
            crate::outline::note(first);
            crate::outline::note(pitch);
            if k == 0 {
                t.push_str(&format!("<tspan x=\"{}\" y=\"{}\"{}>{}</tspan>", f4(lx), f4(first), dx_for(l), xml_escape(l)));
            } else {
                t.push_str(&format!("<tspan x=\"{}\" dy=\"{}\"{}>{}</tspan>", f4(lx), f4(pitch), dx_for(l), xml_escape(l)));
            }
        }
        s.push_str(&format!("{}<text class=\"{}\" x=\"{}\" y=\"{}\"{}>{}</text>\n", ind(ind_n), tcls, f4(x), f4(y), extra, t));
    }
    Ok(())
}

pub fn prop_str(ctx: &Ctx, i: usize, k: &str) -> Option<String> {
    let v = ctx.nodes[i].props.get(k)?;
    match single_term(v)? {
        Term::Str(x, _) => Some(x.clone()),
        Term::Ident(x, _) => Some(x.clone()),
        _ => None,
    }
}

pub fn prop_nums(ctx: &Ctx, i: usize, k: &str) -> Vec<f64> {
    match ctx.nodes[i].props.get(k) {
        Some(v) => value_nums(&ctx.sheet.env, v),
        None => vec![],
    }
}

// The node's outline elements (unindented), centred on its origin.
pub fn shape_lines(ctx: &Ctx, i: usize) -> Vec<String> {
    let n = &ctx.nodes[i];
    let c = &ctx.comp[i];
    let (w, h) = (n.w, n.h);
    if let Some(v) = crate::drawing::shape_override(ctx, i) {
        return v;
    }
    let mut v = Vec::new();
    match n.prim {
        Prim::Block if w == 0.0 || h == 0.0 => {}
        Prim::Block => {
            v.push(format!(
                "<rect x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" rx=\"{}\" ry=\"{}\"/>",
                f4(-w / 2.0),
                f4(-h / 2.0),
                f4(w),
                f4(h),
                f4(c.radius),
                f4(c.radius)
            ));
        }
        Prim::Oval => {
            v.push(format!("<ellipse cx=\"0\" cy=\"0\" rx=\"{}\" ry=\"{}\"/>", f4(w / 2.0), f4(h / 2.0)));
        }
        Prim::Hex => {
            v.push(format!(
                "<polygon points=\"{},0 {},{} {},{} {},0 {},{} {},{}\"/>",
                f4(-w / 2.0),
                f4(-w / 4.0),
                f4(-h / 2.0),
                f4(w / 4.0),
                f4(-h / 2.0),
                f4(w / 2.0),
                f4(w / 4.0),
                f4(h / 2.0),
                f4(-w / 4.0),
                f4(h / 2.0)
            ));
        }
        Prim::Diamond => {
            v.push(format!(
                "<polygon points=\"0,{} {},0 0,{} {},0\"/>",
                f4(-h / 2.0),
                f4(w / 2.0),
                f4(h / 2.0),
                f4(-w / 2.0)
            ));
        }
        Prim::Slant => {
            let skew = prop_nums(ctx, i, "skew").first().copied().unwrap_or(15.0);
            let off = (skew.to_radians()).tan() * h / 2.0;
            v.push(format!(
                "<polygon points=\"{},{} {},{} {},{} {},{}\"/>",
                f4(-w / 2.0 + off),
                f4(-h / 2.0),
                f4(w / 2.0 + off),
                f4(-h / 2.0),
                f4(w / 2.0 - off),
                f4(h / 2.0),
                f4(-w / 2.0 - off),
                f4(h / 2.0)
            ));
        }
        Prim::Cyl => {
            let ry = (h * 0.1).max(2.0);
            let rx = w / 2.0;
            let t = h / 2.0 - ry;
            v.push(format!(
                "<path d=\"M {} {} L {} {} A {} {} 0 0 0 {} {} L {} {} A {} {} 0 0 0 {} {} Z\"/>",
                f4(-rx),
                f4(-t),
                f4(-rx),
                f4(t),
                f4(rx),
                f4(ry),
                f4(rx),
                f4(t),
                f4(rx),
                f4(-t),
                f4(rx),
                f4(ry),
                f4(-rx),
                f4(-t)
            ));
            v.push(format!("<ellipse cx=\"0\" cy=\"{}\" rx=\"{}\" ry=\"{}\"/>", f4(-t), f4(rx), f4(ry)));
        }
        Prim::Line | Prim::Poly | Prim::Path => {
            let sw = c.stroke_width;
            match &n.geo {
                Some(crate::scene::Geo::Path(d)) => v.push(format!("<path d=\"{}\"/>", xml_escape(d))),
                Some(crate::scene::Geo::Points(pts)) => {
                    let mut pts = pts.clone();
                    let ms = prop_str(ctx, i, "marker-start").or_else(|| prop_str(ctx, i, "marker"));
                    let me = prop_str(ctx, i, "marker-end").or_else(|| prop_str(ctx, i, "marker"));
                    let mut marks = Vec::new();
                    if n.prim == Prim::Line && pts.len() >= 2 {
                        let k = pts.len();
                        if let Some(m) = ms.as_deref() {
                            if m != "none" {
                                let (p, q) = (pts[0], pts[1]);
                                let (lines, pull) = crate::markers::marker(m, p, (p.0 - q.0, p.1 - q.1), sw);
                                marks.extend(lines);
                                let d = crate::markers::unit((q.0 - p.0, q.1 - p.1));
                                pts[0] = (p.0 + d.0 * pull, p.1 + d.1 * pull);
                            }
                        }
                        if let Some(m) = me.as_deref() {
                            if m != "none" {
                                let (p, q) = (pts[k - 1], pts[k - 2]);
                                let (lines, pull) = crate::markers::marker(m, p, (p.0 - q.0, p.1 - q.1), sw);
                                marks.extend(lines);
                                let d = crate::markers::unit((q.0 - p.0, q.1 - p.1));
                                pts[k - 1] = (p.0 + d.0 * pull, p.1 + d.1 * pull);
                            }
                        }
                    }
                    let ps: Vec<String> = pts.iter().map(|(x, y)| format!("{},{}", f4(*x), f4(*y))).collect();
                    if n.prim == Prim::Poly {
                        v.push(format!("<polygon points=\"{}\"/>", ps.join(" ")));
                    } else if pts.len() == 2 {
                        v.push(format!(
                            "<line x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\"/>",
                            f4(pts[0].0),
                            f4(pts[0].1),
                            f4(pts[1].0),
                            f4(pts[1].1)
                        ));
                    } else {
                        v.push(format!("<polyline points=\"{}\"/>", ps.join(" ")));
                    }
                    let stroke_style = ctx.nodes[i].inline.iter().rev().find(|d| d.name == "stroke").map(|d| d.value.clone());
                    for m in marks {
                        let mut m = m;
                        if let Some(sv) = &stroke_style {
                            if let Some(t) = single_term(sv) {
                                let mut tmp = Vec::new();
                                if let Ok(col) = color_css(t, &mut tmp, sv.span) {
                                    if m.contains("lini-marker-open") {
                                        // open glyphs inherit the line's stroke
                                    } else {
                                        m = m.replacen("/>", &format!(" style=\"fill: {}\"/>", col), 1);
                                    }
                                }
                            }
                        }
                        v.push(m);
                    }
                }
                None => {}
            }
        }
        Prim::Icon => v.extend(crate::icon::shape_lines(ctx, i)),
        Prim::Image => v.extend(crate::image::shape_lines(ctx, i)),
        _ => {}
    }
    v
}

fn shadow_filter(ctx: &Ctx, i: usize, out: &mut Out) -> Option<String> {
    let (dx, dy, blur, col) = crate::paint::shadow_spec(ctx, ctx.nodes[i].props.get("shadow")?)?;
    let xs = [dx, dy, blur];
    let key = format!("{},{},{},{}", f4(xs[0]), f4(xs[1]), f4(xs[2]), col);
    let id = format!("lini-shadow-{}", hash8(&key));
    let def = format!(
        "<filter id=\"{}\" x=\"-50%\" y=\"-50%\" width=\"200%\" height=\"200%\"><feDropShadow dx=\"{}\" dy=\"{}\" stdDeviation=\"{}\" flood-color=\"{}\"/></filter>",
        id,
        f4(xs[0]),
        f4(xs[1]),
        f4(xs[2]),
        col
    );
    if !out.defs.contains(&def) {
        out.defs.push(def);
    }
    Some(id)
}

pub fn render_node(ctx: &Ctx, i: usize, ind_n: usize, s: &mut String, out: &mut Out) -> Result<(), Diag> {
    crate::paint::meet_node(ctx, i);
    let n = &ctx.nodes[i];
    let c = &ctx.comp[i];
    if n.prim == Prim::Text {
        return render_text(ctx, i, ind_n, s, out);
    }
    if crate::drawing::is_chrome(ctx, i) {
        return crate::drawing::render_chrome(ctx, i, ind_n, s, out);
    }
    let href = prop_str(ctx, i, "href");
    let mut ind_n = ind_n;
    if let Some(h) = &href {
        s.push_str(&format!("{}<a href=\"{}\">\n", ind(ind_n), xml_escape(h)));
        ind_n += 2;
    }
    let cls = node_classes(ctx, i, out);
    if n.is("table") {
        // a table resolves its header band's look whether or not a band is drawn
        let hp = type_rule_props(ctx, "header");
        let _ = css_decls(ctx, &hp, &mut out.vars, 2.0, false)?;
    }
    let style = inline_style(ctx, i, out, false)?;
    let mut head = format!("{}<g class=\"{}\"", ind(ind_n), cls);
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
    let ci = ind_n + 2;
    if let Some(hint) = prop_str(ctx, i, "hint") {
        s.push_str(&format!("{}<title>{}</title>\n", ind(ci), xml_escape(&hint)));
    }
    if crate::chart::is_chart(ctx, i) {
        crate::chart::render(ctx, i, ci, s, out)?;
        s.push_str(&format!("{}</g>\n", ind(ind_n)));
        if href.is_some() {
            s.push_str(&format!("{}</a>\n", ind(ind_n - 2)));
        }
        return Ok(());
    }
    // a box with no area is not drawn (other outlines still are)
    let empty = n.prim == Prim::Block && (n.w <= 0.0 || n.h <= 0.0);
    let shape = if empty { vec![] } else { shape_lines(ctx, i) };
    if shape.iter().any(|l| l.contains("lini-marker")) {
        out.markers = true;
    }
    let multiple = {
        let xs = prop_nums(ctx, i, "multiple");
        match xs.len() {
            0 => None,
            1 => Some((xs[0], -xs[0])),
            _ => Some((xs[0], xs[1])),
        }
    };
    let shadow = shadow_filter(ctx, i, out);
    let mut si = ci;
    if let Some(id) = &shadow {
        s.push_str(&format!("{}<g filter=\"url(#{})\">\n", ind(si), id));
        si += 2;
    }
    if let Some((mx, my)) = multiple {
        s.push_str(&format!("{}<g transform=\"translate({},{})\">\n", ind(si), f4(mx), f4(my)));
        for l in &shape {
            s.push_str(&format!("{}{}\n", ind(si + 2), l));
        }
        s.push_str(&format!("{}</g>\n", ind(si)));
    }
    for l in &shape {
        s.push_str(&format!("{}{}\n", ind(si), l));
    }
    if shadow.is_some() {
        s.push_str(&format!("{}</g>\n", ind(ci)));
    }
    if !n.gutters.is_empty() {
        let fill = match ctx.nodes[i].props.get("gap-fill").and_then(single_term) {
            Some(t) => color_css(t, &mut out.vars, t.span())?,
            None => String::new(),
        };
        out.gutters = true;
        for &(x, y, w, h) in &n.gutters {
            s.push_str(&format!(
                "{}<rect class=\"lini-gutter\" x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" fill=\"{}\"/>\n",
                ind(ci),
                f4(x),
                f4(y),
                f4(w),
                f4(h),
                xml_escape(&fill)
            ));
        }
    }
    let ordered = paint_order(ctx, &n.children);
    for ch in ordered {
        render_node(ctx, ch, ci, s, out)?;
    }
    s.push_str(&format!("{}</g>\n", ind(ind_n)));
    if href.is_some() {
        s.push_str(&format!("{}</a>\n", ind(ind_n - 2)));
    }
    Ok(())
}

// Stylesheet rule order. Type rules use their type name as the slot; user
// defines and classes use "@define:NNNN" / "@class:NNNN".
pub static SLOT_ORDER: &[&str] = &[
    "canvas",
    "block", "oval", "hex", "slant", "cyl", "diamond", "poly", "path", "sketch", "line", "dim-text", "text", "icon", "image",
    "chart-title", "chart-text", "chart-label", "chart-legend", "gutter",
    "box", "rect", "group", "row", "column", "grid", "caption", "footnote", "badge", "table", "cell", "header", "entity",
    "sign", "note", "topic", "mindmap", "chart", "bars", "area", "dots", "bubble", "band", "mark", "axis", "pie", "slice",
    "sequence", "loop", "alt", "opt", "else", "stack", "drawing", "floorplan", "hole", "centerline",
    "pitch-circle", "breakline", "hidden", "shoulder", "threadline", "plane", "magnifier", "feature-control", "datum",
    "surface-finish", "balloon", "page", "title-block",
    "field", "frame", "zone", "tick", "wall", "partition", "door", "window", "stairs", "bed", "sofa", "dining",
    "appliance", "bath", "schematic", "sch-line", "ref", "component", "pin", "space", "label",
    "@define",
    "link", "link-dashed", "link-dotted", "link-label", "cut-bg", "cut", "marker", "marker-dim", "plane-end",
    "plane-shaft", "plane-arrow", "link-marker", "chart-label-pe",
    "@class",
    "@scoped",
    "marker-open",
    "chart-tip", "chart-hit",
];

pub fn slot_rank(slot: &str) -> (usize, String) {
    if let Some(rest) = slot.strip_prefix("@define:") {
        let p = SLOT_ORDER.iter().position(|s| *s == "@define").unwrap();
        return (p, rest.to_string());
    }
    if let Some(rest) = slot.strip_prefix("@class:") {
        let p = SLOT_ORDER.iter().position(|s| *s == "@class").unwrap();
        return (p, rest.to_string());
    }
    if let Some(rest) = slot.strip_prefix("@scoped:") {
        let p = SLOT_ORDER.iter().position(|s| *s == "@scoped").unwrap();
        return (p, rest.to_string());
    }
    match SLOT_ORDER.iter().position(|s| *s == slot) {
        Some(p) => (p, String::new()),
        None => (SLOT_ORDER.len(), slot.to_string()),
    }
}
