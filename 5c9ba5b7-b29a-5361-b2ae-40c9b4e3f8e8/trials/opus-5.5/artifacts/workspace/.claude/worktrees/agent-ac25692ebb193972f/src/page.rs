// |page|: an ISO 5457 drawing sheet. `sheet: a4 landscape` sets the size in
// mm (× the root `density`, px per mm); the lowering adds the chrome — a
// frame inset 10 mm, zone ticks on every zone boundary, centring marks, and
// zone references (numbers along the top/bottom, letters down the sides) —
// and pins direct |title-block| children flush in the frame's bottom-right
// corner. The authored children flow inside the frame (5 mm clear of it, plus
// `padding:`); landscape sheets run as a row, portrait ones as a column.

use crate::ast::*;
use crate::compile::{Align, Ctx, Dir};
use crate::diag::Diag;
use crate::scene::{Builder, Geo, Node, SheetModel};
use crate::types::Prim;

pub fn is_page(chain: &[String]) -> bool {
    chain.iter().any(|c| c == "page")
}

// ISO A and ANSI sheets in their default orientation (w, h) mm.
pub fn sheet_size(name: &str) -> Option<(f64, f64)> {
    Some(match name {
        "a0" => (1189.0, 841.0),
        "a1" => (841.0, 594.0),
        "a2" => (594.0, 420.0),
        "a3" => (420.0, 297.0),
        "a4" => (210.0, 297.0),
        "a5" => (148.0, 210.0),
        "a" => (215.9, 279.4),
        "b" => (431.8, 279.4),
        "c" => (558.8, 431.8),
        "d" => (863.6, 558.8),
        "e" => (1117.6, 863.6),
        _ => return None,
    })
}

// Zones per edge: an even count of roughly 50 mm zones (round half down).
pub fn zone_count(len_mm: f64) -> usize {
    let n = (len_mm / 100.0 - 0.5).ceil();
    2 * (n.max(1.0) as usize)
}

fn idents(v: &Value) -> Vec<String> {
    let mut out = Vec::new();
    for g in &v.groups {
        for t in g {
            if let Term::Ident(s, _) = t {
                out.push(s.clone());
            }
        }
    }
    out
}

// The winning declaration of a property set anywhere above the built-in
// defaults (defines, user type rules, classes, id rules, inline).
fn user_decl(sheet: &SheetModel, n: &Node, name: &str) -> Option<Decl> {
    let mut found: Option<Decl> = None;
    for t in n.chain.iter().rev() {
        if let Some(df) = sheet.define(t) {
            for d in &df.decls {
                if d.name == name {
                    found = Some(d.clone());
                }
            }
        }
        for d in sheet.type_rule(t) {
            if d.name == name {
                found = Some(d.clone());
            }
        }
    }
    for c in &n.classes {
        if let Some(cr) = sheet.class(c) {
            for d in &cr.decls {
                if d.name == name {
                    found = Some(d.clone());
                }
            }
        }
    }
    if let Some(id) = &n.id {
        for (rid, ds) in &sheet.id_rules {
            if rid == id {
                for d in ds {
                    if d.name == name {
                        found = Some(d.clone());
                    }
                }
            }
        }
    }
    for d in &n.inline {
        if d.name == name {
            found = Some(d.clone());
        }
    }
    found
}

fn user_value(sheet: &SheetModel, n: &Node, name: &str) -> Option<Value> {
    user_decl(sheet, n, name).map(|d| d.value)
}

const SIZES: &[&str] = &["a0", "a1", "a2", "a3", "a4", "a5", "a", "b", "c", "d", "e"];

// `sheet:` must read a size and an optional orientation.
fn check_sheet(sheet: &SheetModel, n: &Node) -> Result<(), Diag> {
    let d = match user_decl(sheet, n, "sheet") {
        Some(d) => d,
        None => return Ok(()),
    };
    if d.value.groups.len() > 1 {
        return Err(Diag::error("malformed-value", "'sheet' takes one value, not a comma list", d.span));
    }
    let bad = |word: &str| {
        let mut msg = String::from("'sheet' takes a size — a5…a0 (ISO) or a…e (ANSI) — and an optional portrait / landscape");
        let mut best: Option<(usize, &str)> = None;
        for c in SIZES {
            let k = crate::util::levenshtein(word, c);
            if k <= 2 && best.map_or(true, |(b, _)| k < b) {
                best = Some((k, c));
            }
        }
        if let Some((_, c)) = best {
            msg.push_str(&format!("; did you mean '{}'?", c));
        }
        Diag::error("resolve", &msg, d.span)
    };
    let mut size = false;
    for t in d.value.groups.iter().flatten() {
        match t {
            Term::Ident(w, _) if w == "landscape" || w == "portrait" => {}
            Term::Ident(w, _) if sheet_size(w).is_some() => size = true,
            Term::Ident(w, _) => return Err(bad(w)),
            _ => return Err(bad("")),
        }
    }
    if !size {
        return Err(bad(""));
    }
    Ok(())
}

// The page's size in mm: `sheet:` (size + orientation), then any authored
// width / height, else the type's A4 portrait.
pub fn page_size(sheet: &SheetModel, n: &Node) -> (f64, f64) {
    let mut w = 210.0;
    let mut h = 297.0;
    if let Some(v) = user_value(sheet, n, "sheet") {
        let words = idents(&v);
        if let Some((sw, sh)) = words.iter().rev().find_map(|s| sheet_size(s)) {
            w = sw;
            h = sh;
            match words.iter().rev().find(|s| *s == "landscape" || *s == "portrait").map(|s| s.as_str()) {
                Some("landscape") if w < h => std::mem::swap(&mut w, &mut h),
                Some("portrait") if w > h => std::mem::swap(&mut w, &mut h),
                _ => {}
            }
        }
    }
    let env = &sheet.env;
    if let Some(x) = user_value(sheet, n, "width").and_then(|v| crate::style::value_num(env, &v)) {
        w = x;
    }
    if let Some(x) = user_value(sheet, n, "height").and_then(|v| crate::style::value_num(env, &v)) {
        h = x;
    }
    (w, h)
}

// Pixels per mm: the root `density` (4 by default).
pub fn ppu(sheet: &SheetModel) -> f64 {
    sheet
        .root
        .iter()
        .rev()
        .find(|d| d.name == "density")
        .and_then(|d| crate::style::value_num(&sheet.env, &d.value))
        .filter(|x| *x > 0.0)
        .unwrap_or(4.0)
}

fn chrome_node(b: &mut Builder, prim: Prim, chain: &[&str], decls: &str, parent: usize) -> usize {
    let span = b.nodes[parent].span;
    let mut n = Node::new(prim, chain.iter().map(|s| s.to_string()).collect(), span);
    n.inline = crate::table::parse_decls(decls);
    b.add(n, Some(parent))
}

fn zone_label(k: usize, letters: bool) -> String {
    if letters {
        let mut s = String::new();
        let mut x = k;
        loop {
            s.insert(0, (b'A' + (x % 26) as u8) as char);
            if x < 26 {
                break;
            }
            x = x / 26 - 1;
        }
        s
    } else {
        format!("{}", k + 1)
    }
}

// Build a page's contents (the node itself is already added).
pub fn build(b: &mut Builder, ns: &NodeStmt, i: usize) -> Result<(), Diag> {
    let chain = b.nodes[i].chain.clone();
    check_sheet(b.sheet, &b.nodes[i])?;
    if let Some((label, lspan)) = ns.label.as_ref().filter(|(l, _)| !l.is_empty()) {
        b.text_node(label, &[], None, *lspan, i);
    }
    for t in chain.iter().rev() {
        if let Some(d) = b.sheet.define(t) {
            if let Some(body) = d.body.clone() {
                b.build_stmts(&body, i)?;
            }
        }
    }
    if let Some(ch) = &ns.children {
        b.build_stmts(ch, i)?;
    }
    // a direct |title-block| is pulled out of the flow, into the frame's corner
    for ch in b.nodes[i].children.clone() {
        if b.nodes[ch].is("title-block") {
            let mut inl = b.nodes[ch].inline.clone();
            inl.retain(|d| d.name != "pin");
            inl.extend(crate::table::parse_decls("pin: bottom right;"));
            b.nodes[ch].inline = inl;
        }
    }
    let (w, h) = page_size(b.sheet, &b.nodes[i]);
    let (nx, ny) = (zone_count(w), zone_count(h));
    chrome_node(b, Prim::Block, &["frame", "rect", "box", "block"], "chrome: frame; pin: center;", i);
    let tick = |b: &mut Builder, what: &str| {
        chrome_node(b, Prim::Line, &["tick", "line"], &format!("chrome: {}; pin: center; points: 0 0, 0 0;", what), i);
    };
    for side in ["top", "bottom"] {
        for k in 1..nx {
            if 2 * k != nx {
                tick(b, &format!("tick {} {}", side, k));
            }
        }
    }
    for side in ["left", "right"] {
        for k in 1..ny {
            if 2 * k != ny {
                tick(b, &format!("tick {} {}", side, k));
            }
        }
    }
    for side in ["top", "bottom", "left", "right"] {
        tick(b, &format!("mark {}", side));
    }
    for side in ["top", "bottom", "left", "right"] {
        let (n, letters) = if side == "top" || side == "bottom" { (nx, false) } else { (ny, true) };
        for k in 0..n {
            let z = chrome_node(b, Prim::Block, &["zone", "block"], &format!("chrome: zone {} {}; pin: center;", side, k), i);
            let span = b.nodes[i].span;
            b.text_node(&zone_label(k, letters), &[], None, span, z);
        }
    }
    Ok(())
}

fn chrome_parts(ctx: &Ctx, i: usize) -> Option<(String, String, usize)> {
    let d = ctx.nodes[i].inline.iter().rev().find(|d| d.name == "chrome")?;
    let mut words = Vec::new();
    let mut num = 0usize;
    for g in &d.value.groups {
        for t in g {
            match t {
                Term::Ident(s, _) => words.push(s.clone()),
                Term::Num(x, _, _) => num = *x as usize,
                _ => {}
            }
        }
    }
    let kind = words.first().cloned().unwrap_or_default();
    let side = words.get(1).cloned().unwrap_or_default();
    Some((kind, side, num))
}

// Is this document a bare sheet (every root child a page)?
pub fn sheet_document(nodes: &[Node]) -> bool {
    let kids = &nodes[0].children;
    !kids.is_empty() && kids.iter().all(|&k| nodes[k].is("page"))
}

// Root defaults for a sheet document: no padding around the paper.
pub fn root_fixup(nodes: &mut [Node], sheet: &SheetModel) {
    if !sheet_document(nodes) || sheet.root.iter().any(|d| d.name == "padding") {
        return;
    }
    for d in nodes[0].inline.iter_mut() {
        if d.name == "padding" {
            d.value = Value { groups: vec![vec![Term::Num(0.0, "0".into(), Default::default())]], span: Default::default() };
        }
    }
}

// The SVG's physical size: a sheet document is measured in mm.
pub fn svg_mm(ctx: &Ctx) -> Option<f64> {
    if sheet_document(&ctx.nodes) {
        Some(ppu(&ctx.sheet))
    } else {
        None
    }
}

// Lengths inside a page read in mm: width / height / translate / max-width
// scale by the sheet's px per mm. Tables and annotation types keep screen
// units (their own `scale:`), drawings and charts size themselves.
// Scale every page's subtree once, before layout (a nested page scales its
// own).
pub fn scale_units(ctx: &mut Ctx) {
    let k = ppu(&ctx.sheet);
    for i in 0..ctx.nodes.len() {
        if ctx.nodes[i].prim == Prim::Block && ctx.nodes[i].is("page") {
            scale_subtree(ctx, i, k);
        }
    }
}

fn scale_subtree(ctx: &mut Ctx, i: usize, f: f64) {
    for ch in ctx.nodes[i].children.clone() {
        if ctx.nodes[ch].prim == Prim::Text || chrome_parts(ctx, ch).is_some() || ctx.nodes[ch].is("page") {
            continue;
        }
        let layout = ctx.comp[ch].layout.clone();
        if matches!(layout.as_str(), "drawing" | "floorplan" | "schematic" | "chart" | "pie" | "sequence") {
            continue;
        }
        let annot = ctx.nodes[ch].chain.iter().any(|t| crate::style::type_defaults(t).iter().any(|d| d.name == "scale"));
        let own = ctx.nodes[ch].props.get("scale").and_then(|v| crate::style::value_num(&ctx.sheet.env, v));
        let g = if annot { own.unwrap_or(1.0) } else { f * own.unwrap_or(1.0) };
        if g != 1.0 {
            let c = &mut ctx.comp[ch];
            c.width = c.width.map(|x| x * g);
            c.height = c.height.map(|x| x * g);
            c.max_width = c.max_width.map(|x| x * g);
            // a pinned node's offset stays in px
            if c.pin.is_none() {
                c.translate = (c.translate.0 * g, c.translate.1 * g);
            }
        }
        scale_subtree(ctx, ch, g);
    }
}

// Where a laid-out child's own origin (a |drawing|'s datum, 0 0 in its
// coordinates) sits relative to its centre. Plain nodes are their own
// centre; the drawing family hooks in here once it lays views out.
pub fn origin_of(ctx: &Ctx, i: usize) -> (f64, f64) {
    crate::annot::datum_offset(ctx, i)
}

// `align: origin`: the views' datums share the cross-axis centre line.
fn origin_align(ctx: &mut Ctx, i: usize) {
    if ctx.nodes[i].props.get("align").and_then(crate::style::ident_of) == Some("origin") {
        let pad = ctx.comp[i].padding;
        let row = ctx.comp[i].direction == Dir::Row;
        for ch in ctx.nodes[i].children.clone() {
            if ctx.comp[ch].pin.is_some() {
                continue;
            }
            let (ox, oy) = origin_of(ctx, ch);
            if row {
                ctx.nodes[ch].y = (pad[0] - pad[2]) / 2.0 - oy;
            } else {
                ctx.nodes[ch].x = (pad[3] - pad[1]) / 2.0 - ox;
            }
        }
    }
}

// The pinned title block's box (left, right, top), seated at `corner`.
fn title_block_box(ctx: &Ctx, i: usize, corner: (f64, f64)) -> Option<(f64, f64, f64)> {
    let tb = ctx.nodes[i].children.iter().copied().find(|&ch| ctx.nodes[ch].is("title-block") && ctx.comp[ch].pin.as_deref() == Some("bottom right"))?;
    let (ow, oh) = crate::layout::outer(ctx, tb);
    let (tx, ty) = ctx.comp[tb].translate;
    let right = corner.0 + tx;
    let bottom = corner.1 + ty;
    Some((right - ow, right, bottom - oh))
}

// The union box of the page's flow children (left, right, top, bottom).
fn flow_box(ctx: &Ctx, i: usize) -> Option<(f64, f64, f64, f64)> {
    let mut b: Option<(f64, f64, f64, f64)> = None;
    for &ch in &ctx.nodes[i].children {
        if ctx.comp[ch].pin.is_some() {
            continue;
        }
        let (ow, oh) = crate::layout::outer(ctx, ch);
        let n = &ctx.nodes[ch];
        let r = (n.x - ow / 2.0, n.x + ow / 2.0, n.y - oh / 2.0, n.y + oh / 2.0);
        b = Some(match b {
            None => r,
            Some(o) => (o.0.min(r.0), o.1.max(r.1), o.2.min(r.2), o.3.max(r.3)),
        });
    }
    b
}

pub fn measure(ctx: &mut Ctx, i: usize, avail: Option<f64>) {
    let (w_mm, h_mm) = page_size(&ctx.sheet, &ctx.nodes[i]);
    let k = ppu(&ctx.sheet);
    let (pw, ph) = (w_mm * k, h_mm * k);
    let user_dir = user_value(&ctx.sheet, &ctx.nodes[i], "direction").is_some();
    let pad = ctx.comp[i].padding;
    {
        let c = &mut ctx.comp[i];
        c.width = None;
        c.height = None;
        if !user_dir {
            c.direction = if w_mm > h_mm { Dir::Row } else { Dir::Column };
        }
    }
    let grid = ctx.comp[i].layout == "grid";
    // the content's natural size (laid out tight)
    if grid {
        crate::layout::measure_grid(ctx, i, avail);
    } else {
        crate::layout::measure_flow(ctx, i, avail);
    }
    let (nw, nh) = (ctx.nodes[i].w, ctx.nodes[i].h);
    // content keeps 5 mm clear of the frame where it fits; a sheet too
    // small for it grows to the content, the clearance collapsing first
    let (pw0, ph0) = (pw, ph);
    let (pw, ph) = (pw.max(nw), ph.max(nh));
    let ix = ((pw - nw) / 2.0).clamp(0.0, 15.0 * k);
    let iy = ((ph - nh) / 2.0).clamp(0.0, 15.0 * k);
    // zones are counted on the sheet as written, spaced over the grown paper
    let (nx, ny) = (zone_count(w_mm), zone_count(h_mm));
    {
        let c = &mut ctx.comp[i];
        c.width = Some(pw);
        c.height = Some(ph);
        c.padding = [pad[0] + iy, pad[1] + ix, pad[2] + iy, pad[3] + ix];
    }
    ctx.nodes[i].w = pw;
    ctx.nodes[i].h = ph;
    // the content was laid out tight; seat it in the sheet without measuring
    // anything twice: a grid's tracks stay centred, a flow moves by its knobs
    if !grid {
        let c = ctx.comp[i].clone();
        let (cw, ch) = (nw - pad[1] - pad[3], nh - pad[0] - pad[2]);
        let (fl, ft) = (-pw / 2.0 + pad[3] + ix, -ph / 2.0 + pad[0] + iy);
        let (fr, fb) = (pw / 2.0 - pad[1] - ix, ph / 2.0 - pad[2] - iy);
        let (ol, ot) = (-nw / 2.0 + pad[3], -nh / 2.0 + pad[0]);
        let (or, ob) = (nw / 2.0 - pad[1], nh / 2.0 - pad[2]);
        let main = |free: f64| match c.justify {
            Align::Center => free / 2.0,
            Align::End => free,
            _ => 0.0,
        };
        let cross = |a0: f64, a1: f64, b0: f64, b1: f64| match c.align {
            Align::Start => b0 - a0,
            Align::End => b1 - a1,
            _ => (b0 + b1) / 2.0 - (a0 + a1) / 2.0,
        };
        let (dx, dy) = if c.direction == Dir::Row {
            (fl + main(fr - fl - cw) - ol, cross(ot, ob, ft, fb))
        } else {
            (cross(ol, or, fl, fr), ft + main(fb - ft - ch) - ot)
        };
        for kid in ctx.nodes[i].children.clone() {
            if ctx.comp[kid].pin.is_none() {
                ctx.nodes[kid].x += dx;
                ctx.nodes[kid].y += dy;
            }
        }
        origin_align(ctx, i);
    }
    for kid in ctx.nodes[i].children.clone() {
        if ctx.comp[kid].pin.is_some() {
            crate::layout::place_pinned(ctx, i, kid);
        }
    }
    // content that would run into the title block rises above it (5 mm
    // clear) when it fits there; otherwise it keeps its place
    let corner = (pw0 / 2.0 - 10.0 * k, ph0 / 2.0 - 10.0 * k);
    if let Some((tl, tr, tt)) = title_block_box(ctx, i, corner) {
        if let Some((bl, br, bt, bb)) = flow_box(ctx, i) {
            let limit = tt - 5.0 * k;
            let top = -ph / 2.0 + ctx.comp[i].padding[0];
            if br > tl && bl < tr && bb > limit && bb - bt <= limit - top {
                // the whole flow rises just enough
                let delta = bb - limit;
                for ch in ctx.nodes[i].children.clone() {
                    if ctx.comp[ch].pin.is_none() {
                        ctx.nodes[ch].y -= delta;
                    }
                }
            }
        }
    }
    ctx.nodes[i].w = pw;
    ctx.nodes[i].h = ph;
    // the chrome
    let (hw, hh) = (pw / 2.0, ph / 2.0);
    let (fw, fh) = (hw - 10.0 * k, hh - 10.0 * k);
    let (zx, zy) = (pw / nx as f64, ph / ny as f64);
    for ch in ctx.nodes[i].children.clone() {
        if ctx.nodes[ch].is("title-block") && ctx.comp[ch].pin.as_deref() == Some("bottom right") {
            let (ow, oh) = crate::layout::outer(ctx, ch);
            // seated in the frame of the sheet as written, even when the paper grew
            ctx.nodes[ch].x = (pw0 / 2.0 - 10.0 * k) - ow / 2.0;
            ctx.nodes[ch].y = (ph0 / 2.0 - 10.0 * k) - oh / 2.0;
            continue;
        }
        let (kind, side, n) = match chrome_parts(ctx, ch) {
            Some(x) => x,
            None => continue,
        };
        match kind.as_str() {
            "frame" => {
                ctx.nodes[ch].w = 2.0 * fw;
                ctx.nodes[ch].h = 2.0 * fh;
                ctx.nodes[ch].x = 0.0;
                ctx.nodes[ch].y = 0.0;
            }
            "tick" | "mark" => {
                let (a, b) = if kind == "tick" { (0.0, 10.0 * k) } else { (0.0, 15.0 * k) };
                let pts = match side.as_str() {
                    "top" | "bottom" => {
                        let x = if kind == "tick" { -hw + n as f64 * zx } else { 0.0 };
                        if side == "top" {
                            vec![(x, -hh + a), (x, -hh + b)]
                        } else {
                            vec![(x, hh - b), (x, hh - a)]
                        }
                    }
                    _ => {
                        let y = if kind == "tick" { -hh + n as f64 * zy } else { 0.0 };
                        if side == "left" {
                            vec![(-hw + a, y), (-hw + b, y)]
                        } else {
                            vec![(hw - b, y), (hw - a, y)]
                        }
                    }
                };
                let node = &mut ctx.nodes[ch];
                node.geo = Some(Geo::Points(pts));
                node.geo_off = (0.0, 0.0);
                node.x = 0.0;
                node.y = 0.0;
                node.w = 0.0;
                node.h = 0.0;
            }
            "zone" => {
                let m = 5.0 * k;
                let (x, y) = match side.as_str() {
                    "top" => (-hw + (n as f64 + 0.5) * zx, -hh + m),
                    "bottom" => (-hw + (n as f64 + 0.5) * zx, hh - m),
                    "left" => (-hw + m, -hh + (n as f64 + 0.5) * zy),
                    _ => (hw - m, -hh + (n as f64 + 0.5) * zy),
                };
                ctx.nodes[ch].x = x;
                ctx.nodes[ch].y = y;
            }
            _ => {}
        }
    }
}
