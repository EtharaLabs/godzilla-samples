// Pages (an ISO/ANSI drawing sheet: frame, ticks, centring marks, zone
// labels) and title blocks (field cells from their string properties).

use super::lower::{Cx, R};
use super::out::{Item, ONode};
use super::syntax::{Decl, Node};

// (property, field caption)
pub static FIELDS: &[(&str, &str)] = &[
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

// the decoded text of a canonical string term
pub fn unquote(s: &str) -> Option<String> {
    let inner = s.strip_prefix('"')?.strip_suffix('"')?;
    let mut out = String::new();
    let mut it = inner.chars();
    while let Some(c) = it.next() {
        if c == '\\' {
            match it.next() {
                Some('n') => out.push('\n'),
                Some('t') => out.push('\t'),
                Some(c) => out.push(c),
                None => {}
            }
        } else {
            out.push(c);
        }
    }
    Some(out)
}

// a field's text: the value's first term, when it is a string
pub fn single_string(d: &Decl) -> Option<String> {
    d.groups.first().and_then(|g| g.first()).and_then(|t| unquote(t))
}

pub fn num(s: &str) -> Option<f64> {
    s.parse::<f64>().ok()
}

pub fn fmt_num(v: f64) -> String {
    crate::format::parse::render_number(v)
}

// grid tracks of a `columns:` value
pub fn tracks(d: &Decl) -> i64 {
    let mut n: i64 = 0;
    for t in d.groups.iter().flatten() {
        let mut k: i64 = 1;
        if let Some(rest) = t.strip_prefix("repeat(") {
            let first = rest.split(|c| c == ',' || c == ')').next().unwrap_or("").trim();
            if let Ok(v) = first.parse::<f64>() {
                k = if v.is_nan() || v < 1.0 { 1 } else { v.trunc() as i64 };
            }
        }
        n += k;
    }
    n
}

// title block: the field cells come first
pub fn title_block(cx: &mut Cx, n: &Node, o: &mut ONode, in_page: bool) -> Vec<Item> {
    let mut found: Vec<Option<String>> = vec![None; FIELDS.len()];
    for d in &o.decls {
        if let Some(k) = FIELDS.iter().position(|(p, _)| *p == d.name) {
            if let Some(s) = single_string(d) {
                if found[k].is_none() {
                    found[k] = Some(s);
                }
            }
        }
    }
    // with any field cell, every field property is spent on the cells
    if found.iter().any(|f| f.is_some()) {
        o.decls.retain(|d| !FIELDS.iter().any(|(p, _)| *p == d.name));
    }
    if found[0].is_none() {
        if let Some(l) = n.label.as_ref().map(|l| l.trim().to_string()).filter(|l| !l.is_empty()) {
            found[0] = Some(l);
        }
    }
    let any = found.iter().any(|f| f.is_some());
    if any && !o.decls.iter().any(|d| d.name == "columns") {
        o.decls.push(Decl::val("columns", "auto, auto, auto"));
    }
    if in_page && !o.decls.iter().any(|d| d.name == "pin") {
        o.decls.push(Decl::val("pin", "bottom right"));
    }
    let cols = o.decls.iter().rev().find(|d| d.name == "columns").map(tracks).unwrap_or(3);
    let mut cells = Vec::new();
    for (k, f) in found.iter().enumerate() {
        let v = match f {
            Some(v) => v,
            None => continue,
        };
        let cap = FIELDS[k].1;
        let mut c = cx.typed("cell");
        c.decls = Decl::list(&format!(
            "direction: column; padding: 2 6; width: 96; gap: 4; field: \"{}\";",
            cap
        ));
        if k == 0 {
            c.decls.push(Decl::val("span", &format!("{} 1", cols)));
        }
        let mut fl = cx.typed("field");
        fl.children.push(Cx::text_item(cap));
        c.children.push(Item::Node(fl));
        c.children.push(Cx::text_item(v));
        cells.push(Item::Node(c));
    }
    cells
}

fn size_of(word: &str) -> Option<(f64, f64, bool)> {
    Some(match word {
        "a5" => (148.0, 210.0, true),
        "a4" => (210.0, 297.0, true),
        "a3" => (297.0, 420.0, false),
        "a2" => (420.0, 594.0, false),
        "a1" => (594.0, 841.0, false),
        "a0" => (841.0, 1189.0, false),
        "a" => (215.9, 279.4, true),
        "b" => (279.4, 431.8, false),
        "c" => (431.8, 558.8, false),
        "d" => (558.8, 863.6, false),
        "e" => (863.6, 1117.6, false),
        _ => return None,
    })
}

// the words of a `sheet:` value, in order (the last size and the last
// orientation win); Err(the word that is neither)
fn sheet_spec(spec: &[String]) -> Result<Option<(f64, f64)>, String> {
    let mut size: Option<(f64, f64, bool)> = None;
    let mut orient: Option<bool> = None;
    for w in spec {
        match w.as_str() {
            "portrait" => orient = Some(true),
            "landscape" => orient = Some(false),
            _ => match size_of(w) {
                Some(s) => size = Some(s),
                // a number, string or other non-word reads as no word at all
                None if !w.starts_with(|c: char| c.is_ascii_alphabetic() || c == '_') => return Err(String::new()),
                None => return Err(w.clone()),
            },
        }
    }
    let (w, h, pd) = match size {
        Some(s) => s,
        None => return Ok(None),
    };
    if orient.unwrap_or(pd) {
        Ok(Some((w, h)))
    } else {
        Ok(Some((h, w)))
    }
}

fn sheet_size(spec: &[String]) -> Option<(f64, f64)> {
    sheet_spec(spec).ok().flatten()
}

// the nearest sheet word (two edits at most; the first of equals)
fn sheet_hint(word: &str) -> Option<&'static str> {
    const NAMES: &[&str] = &["a0", "a1", "a2", "a3", "a4", "a5", "a", "b", "c", "d", "e", "portrait", "landscape"];
    let lw = word.to_lowercase();
    let mut best: Option<(usize, &str)> = None;
    for n in NAMES {
        let d = crate::util::levenshtein(&lw, n).min(crate::util::levenshtein(word, n));
        if d > 2 {
            continue;
        }
        if best.map_or(true, |(bd, _)| d < bd) {
            best = Some((d, n));
        }
    }
    best.map(|b| b.1)
}

pub fn zones(d: f64) -> usize {
    // a zone pair per 100 mm, halves rounding down
    let n = 2.0 * (d / 100.0 - 0.5).ceil();
    if n < 2.0 {
        2
    } else {
        n as usize
    }
}

pub fn page(cx: &mut Cx, n: &Node, mut o: ONode, chain: &[String]) -> R<ONode> {
    // sheet: → width/height in place
    let mut decls = Vec::new();
    for d in o.decls.drain(..) {
        if d.name == "sheet" {
            // only the first group speaks
            let spec: Vec<String> = d.groups.first().cloned().unwrap_or_default();
            let msg = "'sheet' takes a size — a5…a0 (ISO) or a…e (ANSI) — and an optional portrait / landscape";
            match sheet_spec(&spec) {
                Ok(Some((w, h))) => {
                    decls.push(Decl::val("width", &fmt_num(w)));
                    decls.push(Decl::val("height", &fmt_num(h)));
                }
                // the tree pass reads past a bad sheet
                _ if cx.tree_check => {}
                Ok(None) => return Err(super::lower::err(&format!("{}; did you mean 'a'?", msg), d.span)),
                Err(word) => {
                    let m = match sheet_hint(&word) {
                        Some(h) => format!("{}; did you mean '{}'?", msg, h),
                        None => msg.to_string(),
                    };
                    return Err(super::lower::err(&m, d.span));
                }
            }
            continue;
        }
        if d.name == "px-per-unit" {
            continue;
        }
        decls.push(d);
    }
    let last = |name: &str| decls.iter().rev().find(|d| d.name == name).and_then(|d| d.first()).and_then(num);
    let w = last("width").unwrap_or(210.0);
    let h = last("height").unwrap_or(297.0);
    if !decls.iter().any(|d| d.name == "direction" || d.name == "layout") {
        decls.push(Decl::val("direction", if w > h { "row" } else { "column" }));
    }
    if let Some((explicit, dir, mindmaps)) = cx.page_tree.take() {
        super::tree::container_decls(&mut decls, explicit, &dir, mindmaps);
    }
    if cx.in_labels == 0 {
        decls.push(Decl::val("px-per-unit", &fmt_num(super::lower::round_px(cx.density))));
    }
    o.decls = decls;
    // children: the label, the content, then the sheet chrome
    let label = n.label.as_ref().map(|l| l.trim().to_string()).filter(|l| !l.is_empty());
    let mut children = Vec::new();
    let bodies = cx.bodies(chain)?;
    children.extend(bodies);
    if let Some(l) = label {
        children.push(Cx::text_item(&l));
    }
    if let Some(ch) = &n.children {
        cx.page_depth += 1;
        let r = cx.stmts(ch, &mut children);
        cx.page_depth -= 1;
        r?;
    }
    let mut frame = cx.typed("frame");
    frame.decls = Decl::list("chrome: frame; pin: center;");
    children.push(Item::Node(frame));
    let nx = zones(w);
    let ny = zones(h);
    for (side, n) in [("top", nx), ("bottom", nx), ("left", ny), ("right", ny)] {
        for k in 1..n {
            if k == n / 2 {
                continue;
            }
            let mut t = cx.typed("tick");
            t.decls = Decl::list(&format!("chrome: tick {} {}; pin: center; points: 0 0, 0 0;", side, k));
            children.push(Item::Node(t));
        }
    }
    for side in ["top", "bottom", "left", "right"] {
        let mut t = cx.typed("tick");
        t.decls = Decl::list(&format!("chrome: mark {}; pin: center; points: 0 0, 0 0;", side));
        children.push(Item::Node(t));
    }
    for (side, n) in [("top", nx), ("bottom", nx), ("left", ny), ("right", ny)] {
        for k in 0..n {
            let label = if side == "top" || side == "bottom" {
                (k + 1).to_string()
            } else {
                ((b'A' + (k % 26) as u8) as char).to_string()
            };
            let mut z = cx.typed("zone");
            z.decls = Decl::list(&format!("chrome: zone {} {}; pin: center;", side, k));
            z.children.push(Cx::text_item(&label));
            children.push(Item::Node(z));
        }
    }
    o.children = children;
    Ok(o)
}

// the direction a page lays its content out in (landscape: row)
pub fn page_dir(n: &Node) -> String {
    if let Some(d) = n.style.iter().rev().find(|d| d.name == "direction").and_then(|d| d.first().map(|s| s.to_string())) {
        return d;
    }
    let (mut w, mut h) = (210.0, 297.0);
    for d in &n.style {
        match d.name.as_str() {
            "sheet" => {
                let spec: Vec<String> = d.groups.first().cloned().unwrap_or_default();
                if let Some((a, b)) = sheet_size(&spec) {
                    w = a;
                    h = b;
                }
            }
            "width" => {
                if let Some(v) = d.first().and_then(num) {
                    w = v;
                }
            }
            "height" => {
                if let Some(v) = d.first().and_then(num) {
                    h = v;
                }
            }
            _ => {}
        }
    }
    if w > h {
        "row".into()
    } else {
        "column".into()
    }
}
