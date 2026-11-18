// Tables: |table|, |entity| and |title-block| — grid blocks whose bare
// strings flow into `|cell|`s. The label is a caption (table), a header band
// spanning the first row (entity) or dropped (title-block); a plain table's
// first row of text cells becomes the `.lini-header` band; `align:` /
// `justify:` lists hand their entries to the auto-placed cells in turn (entry
// k mod columns, the first entry past the list's end) as `.lini-align-*` /
// `.lini-justify-*` classes; a title-block grows one `field` cell per ISO
// 7200 property. Also here: the layout-time checks on grids, and the knob a
// wrapped text's lines flush by.

use crate::ast::*;
use crate::diag::{Diag, Span};
use crate::eval::Env;
use crate::scene::{Builder, Node};
use crate::types::Prim;

pub fn is_table(chain: &[String]) -> bool {
    chain.iter().any(|c| c == "table")
}

fn has(chain: &[String], t: &str) -> bool {
    chain.iter().any(|c| c == t)
}

// The pseudo-type classes tables put on their cells: (property, value).
// They cascade below everything else (a user's |block| rule still wins).
pub fn pseudo_class(t: &str) -> Option<(&'static str, &'static str)> {
    match t {
        "align-start" => Some(("align", "start")),
        "align-end" => Some(("align", "end")),
        "justify-start" => Some(("justify", "start")),
        "justify-end" => Some(("justify", "end")),
        _ => None,
    }
}

pub fn pseudo_value(v: &str) -> Value {
    Value { groups: vec![vec![Term::Ident(v.to_string(), Span::default())]], span: Span::default() }
}

// Parse a declaration list written by the lowering (not user text).
pub fn parse_decls(src: &str) -> Vec<Decl> {
    let full = format!("{{{}}}", src);
    let lexed = match crate::lexer::lex(&full) {
        Ok(l) => l,
        Err(_) => return vec![],
    };
    let mut p = crate::parser::Parser::new(&lexed.tokens, &full);
    match p.parse_style_block() {
        Ok((decls, _)) => decls
            .into_iter()
            .map(|mut d| {
                d.span = Span::default();
                d.name_span = Span::default();
                d.value.span = Span::default();
                d
            })
            .collect(),
        Err(_) => vec![],
    }
}

fn set_decl(decls: &mut Vec<Decl>, d: Decl) {
    decls.retain(|e| e.name != d.name);
    decls.push(d);
}

// Number of column tracks a `columns:` value declares.
pub fn track_count(env: &Env, v: &Value) -> usize {
    let mut n = 0usize;
    for g in &v.groups {
        for t in g {
            match t {
                Term::Ident(s, _) if s == "auto" => n += 1,
                Term::Call(name, args, _) if name == "repeat" => {
                    let k = args
                        .first()
                        .and_then(|a| env.eval(a, &Default::default()).ok())
                        .and_then(|x| x.num())
                        .unwrap_or(1.0);
                    n += k.max(0.0) as usize;
                }
                _ => {
                    if crate::style::term_num(env, t).is_some() {
                        n += 1;
                    }
                }
            }
        }
    }
    n
}

fn get<'a>(props: &'a [(String, Value)], k: &str) -> Option<&'a Value> {
    props.iter().rev().find(|e| e.0 == k).map(|e| &e.1)
}

// The keyword list of an `align:` / `justify:` value, one entry per group.
fn keyword_list(v: &Value) -> Vec<String> {
    v.groups
        .iter()
        .map(|g| match g.first() {
            Some(Term::Ident(s, _)) => s.clone(),
            _ => String::new(),
        })
        .collect()
}

// ISO 7200 title-block fields: (property, caption), in grid order.
pub const FIELDS: &[(&str, &str)] = &[
    ("title", "Title"),
    ("drawing-number", "Dwg No."),
    ("revision", "Rev"),
    ("sheet-number", "Sheet"),
    ("date", "Date"),
    ("author", "Drawn"),
    ("approved", "Approved"),
    ("department", "Dept"),
    ("reference", "Reference"),
    ("document-type", "Type"),
    ("status", "Status"),
];

// A cell lowered from a bare string: |block| .lini-cell.lini-block [ "text" ].
fn string_cell(b: &mut Builder, t: &TextStmt, parent: usize) -> Result<usize, Diag> {
    b.check_classes(&t.classes, t.span)?;
    let cell = Node::new(Prim::Block, vec!["cell".to_string(), "block".to_string()], t.span);
    let ci = b.add(cell, Some(parent));
    if !t.text.is_empty() {
        b.text_node(&t.text, &t.classes, t.style.as_ref(), t.span, ci);
    }
    Ok(ci)
}

fn build_children(b: &mut Builder, stmts: &[Stmt], parent: usize, text_cells: &mut Vec<usize>) -> Result<(), Diag> {
    for s in stmts {
        match s {
            Stmt::Text(t) => {
                let ci = string_cell(b, t, parent)?;
                text_cells.push(ci);
            }
            _ => b.build_stmts(std::slice::from_ref(s), parent)?,
        }
    }
    Ok(())
}

// Build a table-family node's contents (the node itself is already added).
pub fn build(b: &mut Builder, ns: &NodeStmt, i: usize) -> Result<(), Diag> {
    let chain = b.nodes[i].chain.clone();
    let is_entity = has(&chain, "entity");
    let is_title = has(&chain, "title-block");
    let mut text_cells: Vec<usize> = Vec::new();
    let mut header: Option<usize> = None;
    if let Some((label, lspan)) = ns.label.as_ref().filter(|(l, _)| !l.is_empty()) {
        if is_entity {
            let mut hn = Node::new(Prim::Block, vec!["header".to_string(), "cell".to_string(), "block".to_string()], *lspan);
            hn.inline = parse_decls("cell: 1 1;");
            let hi = b.add(hn, Some(i));
            b.text_node(label, &[], None, *lspan, hi);
            header = Some(hi);
        } else if !is_title {
            let cn = Node::new(Prim::Block, vec!["caption".to_string(), "block".to_string()], *lspan);
            let ci = b.add(cn, Some(i));
            b.text_node(label, &[], None, *lspan, ci);
        }
    }
    if is_title {
        title_fields(b, i)?;
    }
    for t in chain.iter().rev() {
        if let Some(d) = b.sheet.define(t) {
            if let Some(body) = d.body.clone() {
                build_children(b, &body, i, &mut text_cells)?;
            }
        }
    }
    if let Some(ch) = &ns.children {
        build_children(b, ch, i, &mut text_cells)?;
    }
    finish(b, i, is_entity, header, &text_cells);
    Ok(())
}

// The generated field cells of a |title-block|: one per ISO 7200 property
// written in its own `{ }` (a quoted string; other values are skipped).
fn title_fields(b: &mut Builder, i: usize) -> Result<(), Diag> {
    let inline = b.nodes[i].inline.clone();
    for d in &inline {
        if !FIELDS.iter().any(|(p, _)| *p == d.name) {
            continue;
        }
        if d.value.groups.len() > 1 {
            return Err(Diag::error("malformed-value", &format!("'{}' takes one value, not a comma list", d.name), d.span));
        }
        if let Some(Term::Ident(..)) = d.value.groups.first().and_then(|g| g.first()) {
            return Err(Diag::error(
                "resolve",
                &format!("'{}' takes a quoted string — write {}: \"…\"", d.name, d.name),
                d.span,
            ));
        }
    }
    let (_, props) = crate::compile::cascade(b.sheet, &b.nodes[i]);
    let env = &b.sheet.env;
    let ncols = match get(&props, "columns") {
        Some(v) => track_count(env, v).max(1),
        None => {
            let mut inl = b.nodes[i].inline.clone();
            for d in parse_decls("columns: auto, auto, auto;") {
                set_decl(&mut inl, d);
            }
            b.nodes[i].inline = inl;
            3
        }
    };
    let span = b.nodes[i].span;
    for (prop, caption) in FIELDS {
        let text = match inline.iter().rev().find(|d| d.name == *prop).and_then(|d| d.value.groups.first()).and_then(|g| g.first()) {
            Some(Term::Str(s, _)) => s.clone(),
            _ => continue,
        };
        let mut decl = format!("direction: column; padding: 2 6; width: 96; gap: 4; field: \"{}\";", caption);
        if *prop == "title" {
            decl.push_str(&format!(" span: {} 1;", ncols));
        }
        let mut cell = Node::new(Prim::Block, vec!["cell".to_string(), "block".to_string()], span);
        cell.inline = parse_decls(&decl);
        let ci = b.add(cell, Some(i));
        let fnode = Node::new(Prim::Block, vec!["field".to_string(), "block".to_string()], span);
        let fi = b.add(fnode, Some(ci));
        b.text_node(caption, &[], None, span, fi);
        if !text.is_empty() {
            b.text_node(&text, &[], None, span, ci);
        }
    }
    Ok(())
}

// Header band, entity header span, and per-column align/justify classes.
fn finish(b: &mut Builder, i: usize, is_entity: bool, header: Option<usize>, text_cells: &[usize]) {
    let (_, props) = crate::compile::cascade(b.sheet, &b.nodes[i]);
    let env = b.sheet.env.clone();
    let ncols = get(&props, "columns").map(|v| track_count(&env, v)).unwrap_or(1).max(1);
    if let Some(h) = header {
        let mut inl = b.nodes[h].inline.clone();
        for d in parse_decls(&format!("span: {} 1;", ncols)) {
            set_decl(&mut inl, d);
        }
        b.nodes[h].inline = inl;
    }
    // flow children: (node, explicit cell, column span, row span)
    let children = b.nodes[i].children.clone();
    let mut items: Vec<(usize, Option<(usize, usize)>, usize, usize)> = Vec::new();
    let mut spanned: Vec<bool> = Vec::new();
    for &ch in &children {
        if b.nodes[ch].prim == Prim::Text {
            continue;
        }
        let (_, cp) = crate::compile::cascade(b.sheet, &b.nodes[ch]);
        if get(&cp, "pin").is_some() {
            continue;
        }
        let span: Vec<f64> = get(&cp, "span").map(|v| crate::style::value_nums(&env, v)).unwrap_or_default();
        spanned.push(get(&cp, "span").is_some());
        let cs = span.first().map(|x| *x as usize).unwrap_or(1).max(1);
        let rs = span.get(1).map(|x| *x as usize).unwrap_or(1).max(1);
        let cell = get(&cp, "cell").map(|v| crate::style::value_nums(&env, v)).filter(|c| c.len() >= 2).map(|c| {
            ((c[0] as usize).max(1) - 1, (c[1] as usize).max(1) - 1)
        });
        items.push((ch, cell, cs, rs));
    }
    // the header band: the first row of auto-placed text cells
    if !is_entity {
        let autos: Vec<usize> = (0..items.len()).filter(|&k| items[k].1.is_none()).collect();
        if autos.len() >= ncols {
            let first = &autos[..ncols];
            // a header band is a first row of plain text cells (no `span:`)
            let ok = first.iter().all(|&k| !spanned[k] && is_text_cell(b, items[k].0, text_cells));
            if ok {
                for &k in first {
                    let ch = items[k].0;
                    b.nodes[ch].chain.insert(0, "header".to_string());
                }
            }
        }
    }
    // per-column alignment classes
    let user_align = get(&props, "align").map(keyword_list).filter(|l| !(l.len() == 1 && l[0] == "stretch"));
    let aligns: Vec<String> = match user_align {
        Some(l) => l,
        None if is_entity => vec!["start".to_string()],
        None => vec![],
    };
    let justs: Vec<String> = get(&props, "justify").map(keyword_list).unwrap_or_default();
    // the k-th auto-placed item reads entry (k mod columns); past the list's
    // end, its first entry
    let pick = |list: &[String], k: usize| -> String { list.get(k % ncols).or(list.first()).cloned().unwrap_or_default() };
    let mut ordinal = 0usize;
    for it in items.iter() {
        if it.1.is_some() {
            continue;
        }
        let k = ordinal;
        ordinal += 1;
        let ch = it.0;
        let mut extra: Vec<String> = Vec::new();
        if !aligns.is_empty() {
            match pick(&aligns, k).as_str() {
                "start" => extra.push("align-start".to_string()),
                "end" => extra.push("align-end".to_string()),
                _ => {}
            }
        }
        if !justs.is_empty() {
            match pick(&justs, k).as_str() {
                "start" => extra.push("justify-start".to_string()),
                "end" => extra.push("justify-end".to_string()),
                _ => {}
            }
        }
        if !extra.is_empty() {
            let n = &mut b.nodes[ch];
            let at = n.chain.len().saturating_sub(1);
            for (j, e) in extra.into_iter().enumerate() {
                n.chain.insert(at + j, e);
            }
        }
    }
}

// A cell whose whole content is one text leaf (a bare string, or a |cell|
// holding one string).
fn is_text_cell(b: &Builder, ch: usize, text_cells: &[usize]) -> bool {
    let n = &b.nodes[ch];
    if !n.is("cell") {
        return false;
    }
    if text_cells.contains(&ch) {
        return true;
    }
    n.children.len() == 1 && b.nodes[n.children[0]].prim == Prim::Text
}

// `layout: grid` needs `columns:` — reported once the scene has rendered
// (after resolve and value errors).
// Layout-time checks, bottom-up as layout meets them: a node's width against
// its max-width; a grid's own `columns` once its children are done, then each
// placed child's `span:` / `cell:`.
pub fn check_grids(ctx: &crate::compile::Ctx) -> Result<(), Diag> {
    check_grid(ctx, 0)
}

fn check_grid(ctx: &crate::compile::Ctx, i: usize) -> Result<(), Diag> {
    let n = &ctx.nodes[i];
    if n.prim == Prim::Text {
        return Ok(());
    }
    for &ch in &n.children {
        check_grid(ctx, ch)?;
    }
    let env = &ctx.sheet.env;
    let num = |k: &str| n.props.get(k).and_then(|v| crate::style::value_num(env, v));
    if let (Some(w), Some(m)) = (num("width"), num("max-width")) {
        if w > m {
            let msg = format!("'width: {}' exceeds 'max-width: {}'", crate::util::f4(w), crate::util::f4(m));
            return Err(Diag::error("layout", &msg, n.span));
        }
    }
    // the rest only matters to a container with something in its flow
    if !n.children.iter().any(|&ch| ctx.comp[ch].pin.is_none()) {
        return Ok(());
    }
    if let Some(v) = n.props.get("gap") {
        if crate::style::value_nums(env, v).iter().any(|x| *x < 0.0) {
            return Err(Diag::error("layout", "a container's 'gap' must be ≥ 0", n.span));
        }
    }
    if ctx.comp[i].layout != "grid" || crate::chart::is_chart(ctx, i) {
        return Ok(());
    }
    let cols = match n.props.get("columns") {
        Some(v) => v,
        None => return Err(Diag::error("missing-required-property", "'layout: grid' requires 'columns'", n.span)),
    };
    for t in cols.groups.iter().flatten() {
        if let Term::Call(name, args, _) = t {
            if name == "repeat" {
                let k = args.first().and_then(|a| env.eval(a, &Default::default()).ok()).and_then(|x| x.num());
                if !matches!(k, Some(x) if x >= 1.0 && x.fract() == 0.0) {
                    return Err(Diag::error("resolve", "repeat() needs a positive integer count", n.span));
                }
            }
        }
    }
    let ncols = track_count(env, cols);
    for &ch in &n.children {
        let c = &ctx.nodes[ch];
        if c.prim == Prim::Text || ctx.comp[ch].pin.is_some() {
            continue;
        }
        let err = |m: String| Diag::error("layout", &m, c.span);
        let mut cs = 1.0;
        if let Some(v) = c.props.get("span") {
            let xs = layout_nums(env, v).map_err(err)?;
            match xs.len() {
                1 => positive_int("span", xs[0]).map_err(err)?,
                2 => {
                    positive_int("span column", xs[0]).map_err(err)?;
                    positive_int("span row", xs[1]).map_err(err)?;
                }
                k => return Err(err(format!("expected a 2-tuple, got {} value(s)", k))),
            }
            cs = xs[0];
            if cs > ncols as f64 {
                return Err(err(format!("span: {} _ exceeds columns={}", crate::util::f4(cs), ncols)));
            }
        }
        if let Some(v) = c.props.get("cell") {
            let xs = layout_nums(env, v).map_err(err)?;
            if xs.len() != 2 {
                return Err(err(format!("expected a 2-tuple, got {} value(s)", xs.len())));
            }
            positive_int("cell column", xs[0]).map_err(err)?;
            positive_int("cell row", xs[1]).map_err(err)?;
            if xs[0] + cs - 1.0 > ncols as f64 {
                return Err(err(format!("cell: {} _ exceeds columns={}", crate::util::f4(xs[0]), ncols)));
            }
        }
    }
    Ok(())
}

fn positive_int(what: &str, x: f64) -> Result<(), String> {
    if x >= 1.0 && x.fract() == 0.0 {
        Ok(())
    } else {
        Err(format!("'{}' expects a positive integer, got {}", what, crate::util::f4(x)))
    }
}

fn term_kind(t: &Term) -> &'static str {
    match t {
        Term::Ident(..) => "identifier",
        Term::Str(..) => "string",
        Term::Hash(..) => "hex color",
        Term::Call(..) => "function call",
        Term::Percent(..) => "percentage",
        _ => "value",
    }
}

// The numbers of a layout attribute (a number, or a space-separated tuple).
fn layout_nums(env: &Env, v: &Value) -> Result<Vec<f64>, String> {
    let terms: Vec<&Term> = v.groups.iter().flatten().collect();
    let single = terms.len() == 1;
    let mut out = Vec::new();
    for t in terms {
        match crate::style::term_num(env, t) {
            Some(x) => out.push(x),
            None => {
                return Err(match t {
                    Term::Var(name, _) => format!(
                        "var(--lini-{}) is a visual variable; layout attrs require a number{}",
                        name,
                        if single { " or tuple" } else { "" }
                    ),
                    _ => format!("expected a number{}, got {}", if single { " or tuple" } else { "" }, term_kind(t)),
                })
            }
        }
    }
    Ok(out)
}

// The horizontal knob that flushes a wrapped text's lines: a lone text in a
// stretched grid item follows the item's own `align` (when set); otherwise
// the holding box's — `align` in a column box or a grid, `justify` in a row.
pub fn text_flush(ctx: &crate::compile::Ctx, t: usize) -> crate::compile::Align {
    use crate::compile::{Align, Dir};
    let p = match ctx.nodes[t].parent {
        Some(p) => p,
        None => return Align::Center,
    };
    let pc = &ctx.comp[p];
    if ctx.nodes[p].children.len() == 1 && ctx.nodes[p].props.contains_key("align") && grid_stretched(ctx, p) {
        return pc.align;
    }
    if pc.layout == "grid" || pc.direction == Dir::Column {
        pc.align
    } else {
        pc.justify
    }
}

// Was this item stretched by its grid along some axis?
fn grid_stretched(ctx: &crate::compile::Ctx, p: usize) -> bool {
    use crate::compile::Align;
    let g = match ctx.nodes[p].parent {
        Some(g) => g,
        None => return false,
    };
    if ctx.comp[g].layout != "grid" || ctx.comp[p].pin.is_some() {
        return false;
    }
    let (ga, gj) = if ctx.nodes[g].is("table") { (Align::Stretch, Align::Stretch) } else { (ctx.comp[g].align, ctx.comp[g].justify) };
    (ga == Align::Stretch && ctx.comp[p].width.is_none()) || (gj == Align::Stretch && ctx.comp[p].height.is_none())
}
