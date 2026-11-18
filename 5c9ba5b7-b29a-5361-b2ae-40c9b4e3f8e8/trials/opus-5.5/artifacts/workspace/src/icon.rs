// Built-in icons: `|icon|` and its larger preset `|sign|`.
//
// The artwork table (data/icons.txt) holds every symbol on a 256×256 canvas in
// three layers: the duotone body (painted with the node's fill), the line work
// (stroked with the node's stroke, counter-scaled so the stroke width stays
// even at any size) and dots (filled with the stroke colour). Each entry also
// carries its artwork bounding box, which `fit: contain | cover | stretch`
// frame to the node; `fit: auto` maps the whole 256 canvas.
//
// An icon is a square: its side is the larger of its laid-out width and height
// (children flow inside it like a block's, gap 0 by default).

use crate::ast::{Decl, Term};
use crate::compile::{get, Ctx};
use crate::diag::Diag;
use crate::scene::{Node, SheetModel};
use crate::style::{color_css, ident_of, single_term, value_num};
use crate::types::Prim;
use crate::util::{f4, levenshtein};
use std::sync::OnceLock;

pub struct IconDef {
    pub name: &'static str,
    // translate that centres the artwork bbox, as printed (`-128`, `-128.028`)
    pub tx: &'static str,
    pub ty: &'static str,
    // artwork bbox size
    pub bw: f64,
    pub bh: f64,
    pub body: Vec<&'static str>,
    pub line: Vec<&'static str>,
    pub dots: Vec<&'static str>,
}

static DATA: &str = include_str!("../data/icons.txt");
static TABLE: OnceLock<Vec<IconDef>> = OnceLock::new();

// Every icon, sorted by name.
pub fn table() -> &'static [IconDef] {
    TABLE.get_or_init(|| {
        let mut out: Vec<IconDef> = Vec::new();
        for line in DATA.lines() {
            if line.starts_with('#') || line.is_empty() {
                continue;
            }
            if let Some(head) = line.strip_prefix('@') {
                let f: Vec<&'static str> = head.split(' ').collect();
                out.push(IconDef {
                    name: f[0],
                    tx: f[1],
                    ty: f[2],
                    bw: f[3].parse().unwrap_or(256.0),
                    bh: f[4].parse().unwrap_or(256.0),
                    body: vec![],
                    line: vec![],
                    dots: vec![],
                });
                continue;
            }
            let d = match out.last_mut() {
                Some(d) => d,
                None => continue,
            };
            let (kind, el) = line.split_at(2);
            match kind {
                "b " => d.body.push(el),
                "l " => d.line.push(el),
                "d " => d.dots.push(el),
                _ => {}
            }
        }
        out.sort_by(|a, b| a.name.cmp(b.name));
        out
    })
}

pub fn find(name: &str) -> Option<&'static IconDef> {
    let t = table();
    t.binary_search_by(|d| d.name.cmp(name)).ok().map(|k| &t[k])
}

// Up to three names within two edits, nearest first, then by name.
pub fn suggestions(name: &str) -> Vec<&'static str> {
    let mut c: Vec<(usize, &'static str)> = table()
        .iter()
        .filter_map(|d| {
            let k = levenshtein(name, d.name);
            if k <= 2 {
                Some((k, d.name))
            } else {
                None
            }
        })
        .collect();
    c.sort();
    c.into_iter().take(3).map(|(_, n)| n).collect()
}

pub fn unknown_icon(name: &str) -> String {
    let s = suggestions(name);
    if s.is_empty() {
        format!("unknown icon '{}'", name)
    } else {
        let q: Vec<String> = s.iter().map(|n| format!("'{}'", n)).collect();
        format!("unknown icon '{}'; did you mean {}?", name, q.join(", "))
    }
}

// The declaration that wins the cascade for `name` (user-written decls only:
// type rules and defines base-first, classes, id rules, inline).
pub fn winning_decl<'a>(sheet: &'a SheetModel, n: &'a Node, name: &str) -> Option<&'a Decl> {
    let mut found: Option<&Decl> = None;
    for t in n.chain.iter().rev() {
        if let Some(df) = sheet.define(t) {
            for d in &df.decls {
                if d.name == name {
                    found = Some(d);
                }
            }
        }
        for d in sheet.type_rule(t) {
            if d.name == name {
                found = Some(d);
            }
        }
    }
    for c in &n.classes {
        if let Some(cr) = sheet.class(c) {
            for d in &cr.decls {
                if d.name == name {
                    found = Some(d);
                }
            }
        }
    }
    if let Some(id) = &n.id {
        for (rid, ds) in &sheet.id_rules {
            if rid == id {
                for d in ds {
                    if d.name == name {
                        found = Some(d);
                    }
                }
            }
        }
    }
    for d in &n.inline {
        if d.name == name {
            found = Some(d);
        }
    }
    found
}

pub const FITS: &[&str] = &["auto", "contain", "cover", "stretch"];

fn check_fit(props: &[(String, crate::ast::Value)], n: &Node) -> Result<(), Diag> {
    if let Some(v) = get(props, "fit") {
        if !ident_of(v).map(|s| FITS.contains(&s)).unwrap_or(false) {
            return Err(Diag::error("resolve", "'fit' must be auto, contain, cover, or stretch", n.span));
        }
    }
    Ok(())
}

// Resolve-time checks for every icon and image, in document order: 'fit',
// the icon symbol, the image source (read here, so a missing file fails
// before layout).
pub fn validate(nodes: &[Node], sheet: &SheetModel, file: &str, opts: &crate::Options) -> Result<(), Diag> {
    for n in nodes {
        if n.prim != Prim::Icon && n.prim != Prim::Image {
            continue;
        }
        let (_, props) = crate::compile::cascade(sheet, n);
        check_fit(&props, n)?;
        if n.prim == Prim::Icon {
            check_symbol(sheet, n, &props)?;
        } else {
            crate::image::check_src(sheet, n, file, opts)?;
        }
    }
    Ok(())
}

// A label names the symbol (trimmed; blank means none).
fn label_of(n: &Node) -> Option<String> {
    n.text.as_ref().map(|t| t.trim().to_string()).filter(|t| !t.is_empty())
}

fn check_symbol(sheet: &SheetModel, n: &Node, props: &[(String, crate::ast::Value)]) -> Result<(), Diag> {
    let sym = get(props, "symbol");
    if let Some(v) = sym {
        if v.groups.len() > 1 {
            let span = winning_decl(sheet, n, "symbol").map(|d| d.span).unwrap_or(v.span);
            return Err(Diag::error("malformed-value", "'symbol' takes one value, not a comma list", span));
        }
    }
    let label = label_of(n);
    // the label lowers to an inline `symbol:`, so only an inline one clashes
    if label.is_some() && n.inline.iter().any(|d| d.name == "symbol") {
        return Err(Diag::error("resolve", "an icon's symbol is its label or 'symbol:', not both", n.span));
    }
    let name = match (label, sym) {
        (Some(label), _) => label,
        (None, Some(v)) => {
            match single_term(v) {
                Some(Term::Ident(s, _)) | Some(Term::Str(s, _)) => s.clone(),
                _ => {
                    return Err(Diag::error("resolve", "'symbol' must be an icon name, e.g. { symbol: heart }", n.span));
                }
            }
        }
        (None, None) => {
            return Err(Diag::error("resolve", "'|icon|' needs a 'symbol' (e.g. { symbol: heart })", n.span));
        }
    };
    if find(&name).is_none() {
        return Err(Diag::error("resolve", &unknown_icon(&name), n.span));
    }
    Ok(())
}

// The symbol name of an icon node (its label, else `symbol:`).
pub fn symbol_of(ctx: &Ctx, i: usize) -> Option<String> {
    if let Some(l) = label_of(&ctx.nodes[i]) {
        return Some(l);
    }
    match ctx.nodes[i].props.get("symbol").and_then(single_term) {
        Some(Term::Ident(s, _)) | Some(Term::Str(s, _)) => Some(s.clone()),
        _ => None,
    }
}

pub fn fit_of(ctx: &Ctx, i: usize) -> &'static str {
    let f = ctx.nodes[i].props.get("fit").and_then(ident_of).unwrap_or("auto");
    FITS.iter().find(|x| **x == f).copied().unwrap_or("auto")
}

// Icons and images lay their children out like a block (gap 0 unless set);
// an icon then squares itself, an image without children is exactly its
// width × height.
pub fn measure(ctx: &mut Ctx, i: usize, avail: Option<f64>) {
    let prim = ctx.nodes[i].prim;
    if !ctx.nodes[i].props.contains_key("gap") {
        ctx.comp[i].gap = (0.0, 0.0);
    }
    // `scale` (inherited: the nearest one wins) multiplies the authored size
    let s = inherited_scale(ctx, i);
    if s != 1.0 {
        let env = &ctx.sheet.env;
        let side = |k: &str| ctx.nodes[i].props.get(k).and_then(|v| value_num(env, v)).map(|x| x * s);
        let (w, h) = (side("width"), side("height"));
        ctx.comp[i].width = w;
        ctx.comp[i].height = h;
    }
    if prim == Prim::Image && ctx.nodes[i].children.is_empty() {
        ctx.nodes[i].w = ctx.comp[i].width.unwrap_or(0.0);
        ctx.nodes[i].h = ctx.comp[i].height.unwrap_or(0.0);
        return;
    }
    crate::layout::measure_flow(ctx, i, avail);
    if prim == Prim::Icon {
        let s = ctx.nodes[i].w.max(ctx.nodes[i].h);
        ctx.nodes[i].w = s;
        ctx.nodes[i].h = s;
    }
}

fn inherited_scale(ctx: &Ctx, i: usize) -> f64 {
    let mut cur = Some(i);
    while let Some(k) = cur {
        if let Some(v) = ctx.nodes[k].props.get("scale") {
            if let Some(x) = value_num(&ctx.sheet.env, v) {
                return x;
            }
        }
        cur = ctx.nodes[k].parent;
    }
    1.0
}

fn paint(ctx: &Ctx, i: usize, k: &str) -> String {
    match ctx.nodes[i].props.get(k) {
        Some(v) => match single_term(v) {
            Some(t) => {
                let mut tmp = Vec::new();
                color_css(t, &mut tmp, v.span).unwrap_or_else(|_| "none".to_string())
            }
            None => "none".to_string(),
        },
        None => "none".to_string(),
    }
}

// The artwork group (unindented lines, nested lines indented by two).
pub fn shape_lines(ctx: &Ctx, i: usize) -> Vec<String> {
    let def = match symbol_of(ctx, i).and_then(|s| find(&s)) {
        Some(d) => d,
        None => return vec![],
    };
    let side = ctx.nodes[i].w;
    let (scale, k, tx, ty) = match fit_of(ctx, i) {
        "contain" => {
            let s = side / def.bw.max(def.bh);
            (f4(s), s, def.tx, def.ty)
        }
        "cover" => {
            let s = side / def.bw.min(def.bh);
            (f4(s), s, def.tx, def.ty)
        }
        "stretch" => {
            let sx = side / def.bw;
            let sy = side / def.bh;
            let st = if (sx - sy).abs() < 1e-9 { f4(sx) } else { format!("{} {}", f4(sx), f4(sy)) };
            (st, (sx * sy).sqrt(), def.tx, def.ty)
        }
        _ => {
            let s = side / 256.0;
            (f4(s), s, "-128", "-128")
        }
    };
    let fill = paint(ctx, i, "fill");
    let stroke = paint(ctx, i, "stroke");
    let sw = ctx.comp[i].stroke_width / k;
    let mut v = Vec::new();
    v.push(format!("<g transform=\"scale({}) translate({} {})\">", scale, tx, ty));
    if fill != "none" && !def.body.is_empty() {
        v.push(format!("  <g fill=\"{}\" stroke=\"none\">", fill));
        for e in &def.body {
            v.push(format!("    {}", e));
        }
        v.push("  </g>".to_string());
    }
    if !def.line.is_empty() {
        v.push(format!(
            "  <g fill=\"none\" stroke=\"{}\" stroke-width=\"{}\" stroke-linecap=\"round\" stroke-linejoin=\"round\">",
            stroke,
            f4(sw)
        ));
        for e in &def.line {
            v.push(format!("    {}", e));
        }
        v.push("  </g>".to_string());
    }
    if !def.dots.is_empty() {
        v.push(format!("  <g fill=\"{}\" stroke=\"none\">", stroke));
        for e in &def.dots {
            v.push(format!("    {}", e));
        }
        v.push("  </g>".to_string());
    }
    v.push("</g>".to_string());
    v
}
