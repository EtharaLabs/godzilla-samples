// Sequence diagrams (`layout: sequence`): participants across the top,
// lifelines down, messages top-to-bottom in source order. Calls open
// activation bars, returns close them, fragments (`|loop|`, `|alt|` with
// `|else|` branches, `|opt|`) frame a span of messages, notes sit over or
// beside lifelines. The participants are ordinary nodes; everything else
// (lifelines, bars, frames, tabs, notes) is drawn here, and the messages are
// handed to the link layer as ready-made geometry.

use crate::ast::{Decl, Stmt, Term, Value};
use crate::compile::{get, Ctx};
use crate::diag::{Diag, Span};
use crate::font::Family;
use crate::links::{Label, LinkGeo};
use crate::render::Out;
use crate::scene::{Link, Node};
use crate::style::*;
use crate::types::Prim;
use crate::util::{f4, xml_escape};
use std::cell::RefCell;
use std::collections::HashMap;

// Raw float text as the drawing paths print it (shortest round-trip, "-0" kept).
fn raw(v: f64) -> String {
    format!("{}", v)
}

// ------------------------------------------------------------ kinds

fn is_frame_node(n: &Node) -> bool {
    n.is("loop") || n.is("alt") || n.is("opt")
}

fn is_else_node(n: &Node) -> bool {
    n.is("else")
}

fn is_fragment_node(n: &Node) -> bool {
    is_frame_node(n) || is_else_node(n)
}

fn is_note_node(n: &Node) -> bool {
    n.is("note")
}

// Is node `i` a sequence container this module lays out?
pub fn is_seq(ctx: &Ctx, i: usize) -> bool {
    ctx.nodes[i].prim == Prim::Block && ctx.comp[i].layout == "sequence"
}

// The sequence a node sits in: its nearest non-fragment ancestor, when that
// one lays out as a sequence.
fn host_seq(ctx: &Ctx, i: usize) -> Option<usize> {
    let mut cur = ctx.nodes[i].parent?;
    while is_fragment_node(&ctx.nodes[cur]) {
        cur = ctx.nodes[cur].parent?;
    }
    if is_seq(ctx, cur) {
        Some(cur)
    } else {
        None
    }
}

// ------------------------------------------------------------ scene hook

// A fragment's messages belong to the diagram around it: they resolve (and
// auto-create their endpoints) there, after the diagram's own messages, a
// fragment's own messages before its nested fragments'.
// Also returns, per link, the fragment it was hoisted out of.
#[allow(clippy::type_complexity)]
pub fn hoist_pending(
    nodes: &[Node],
    pending: Vec<(usize, crate::ast::LinkStmt, usize)>,
) -> (Vec<(usize, crate::ast::LinkStmt, usize)>, Vec<Option<usize>>) {
    let frag = |i: usize| is_fragment_node(&nodes[i]);
    if !pending.iter().any(|p| frag(p.0)) {
        let n = pending.len();
        return (pending, vec![None; n]);
    }
    let host = |mut i: usize| -> usize {
        while frag(i) {
            match nodes[i].parent {
                Some(p) => i = p,
                None => break,
            }
        }
        i
    };
    // fragments in pre-order
    let mut pre: HashMap<usize, usize> = HashMap::new();
    let mut stack = vec![0usize];
    let mut k = 0;
    while let Some(n) = stack.pop() {
        if frag(n) {
            pre.insert(n, k);
            k += 1;
        }
        for &c in nodes[n].children.iter().rev() {
            stack.push(c);
        }
    }
    let mut own = Vec::new();
    let mut hoisted: Vec<(usize, usize, usize, (usize, crate::ast::LinkStmt, usize))> = Vec::new();
    for (pos, p) in pending.into_iter().enumerate() {
        if frag(p.0) {
            let key = pre.get(&p.0).copied().unwrap_or(usize::MAX);
            let h = host(p.0);
            hoisted.push((key, pos, p.0, (h, p.1, p.2)));
        } else {
            own.push(p);
        }
    }
    hoisted.sort_by_key(|e| (e.0, e.1));
    let mut flags: Vec<Option<usize>> = vec![None; own.len()];
    for e in &hoisted {
        flags.push(Some(e.2));
    }
    own.extend(hoisted.into_iter().map(|e| e.3));
    (own, flags)
}

// "'x' auto-creates a new box; did you mean 'y'?" — the nearest candidate
// within two edits (one for two-letter names), ties by name.
// Candidates come in priority order: the names known before the statement
// (sorted), then those it made itself; the first nearest one wins.
pub fn typo_warning(name: &str, known: &[String], made: &[String], span: Span) -> Option<Diag> {
    let reach = name.chars().count().saturating_sub(1).min(2);
    // a numbered series (p1, p2, db, db2) is not a typo
    let stem = |s: &str| s.trim_end_matches(|c: char| c.is_ascii_digit()).to_string();
    let mut sorted: Vec<&String> = known.iter().filter(|k| !made.contains(k)).collect();
    sorted.sort();
    sorted.dedup();
    let mut best: Option<(usize, &String)> = None;
    for id in sorted.into_iter().chain(made.iter()) {
        if id == name || stem(id) == stem(name) {
            continue;
        }
        let d = crate::util::levenshtein(name, id);
        if d <= reach && best.map_or(true, |(bd, _)| d < bd) {
            best = Some((d, id));
        }
    }
    best.map(|(_, id)| Diag::warning("validate", &format!("'{}' auto-creates a new box; did you mean '{}'?", name, id), span))
}

// ------------------------------------------------------------ validation

fn place_decl<'a>(ctx: &'a Ctx, i: usize) -> Option<&'a Decl> {
    crate::icon::winning_decl(&ctx.sheet, &ctx.nodes[i], "place")
}

// `place: over a b` / `left a` / `right a` -> (mode, lifelines)
fn parse_place(v: &Value) -> Option<(String, Vec<String>)> {
    if v.groups.len() != 1 {
        return None;
    }
    let g = &v.groups[0];
    let mut names = Vec::new();
    for t in g {
        match t {
            Term::Ident(s, _) => names.push(s.clone()),
            _ => return None,
        }
    }
    if names.len() < 2 {
        return None;
    }
    let mode = names.remove(0);
    match mode.as_str() {
        "over" => {}
        "left" | "right" => {
            if names.len() != 1 {
                return None;
            }
        }
        _ => return None,
    }
    Some((mode, names))
}

const PLACE_ERR: &str = "'place' is a mode then its lifelines — 'place: over api db', 'place: left api'";

// Placement checks: fragments only live in a sequence, `|else|` only in an
// `|alt|`, a sequence note needs a well-formed `place`.
// Property checks on the written declarations, in document order, before
// the scene is built: `activation` reads only on a sequence, `place` only on
// a note in one.
pub fn precheck(doc: &crate::ast::Doc, sheet: &crate::scene::SheetModel) -> Result<(), Diag> {
    let root_seq = sheet.root.iter().rev().find(|d| d.name == "layout").and_then(|d| ident_of(&d.value)) == Some("sequence");
    if !root_seq {
        if let Some(d) = sheet.root.iter().find(|d| d.name == "activation") {
            return Err(Diag::error(
                "misused-property",
                "'activation' has no meaning on the root block — it reads on a 'layout: sequence'",
                d.span,
            ));
        }
    }
    precheck_stmts(&doc.stmts, sheet, root_seq)
}

fn precheck_stmts(stmts: &[Stmt], sheet: &crate::scene::SheetModel, in_seq: bool) -> Result<(), Diag> {
    for st in stmts {
        let Stmt::Node(ns) = st else { continue };
        let tname = ns.type_name.clone().unwrap_or_else(|| "box".to_string());
        let chain = crate::scene::type_chain(sheet, &tname).map(|(_, c)| c).unwrap_or_default();
        let has = |t: &str| chain.iter().any(|c| c == t);
        let decls: &[Decl] = ns.style.as_deref().unwrap_or(&[]);
        let own_layout = decls.iter().rev().find(|d| d.name == "layout").and_then(|d| ident_of(&d.value).map(|s| s.to_string()));
        let is_sequence = match own_layout.as_deref() {
            Some(l) => l == "sequence",
            None => has("sequence"),
        };
        for d in decls {
            if d.name == "activation" && !is_sequence {
                return Err(Diag::error("activation-outside-sequence", "'activation' is valid only in a 'layout: sequence'", d.span));
            }
            if d.name == "place" {
                if !in_seq {
                    return Err(Diag::error("place-outside-sequence", "'place' is valid only in a 'layout: sequence'", d.span));
                }
                if !has("note") {
                    return Err(Diag::error(
                        "misused-property",
                        &format!("'place' has no meaning on '|{}|' — it reads on '|note|'", tname),
                        d.span,
                    ));
                }
            }
        }
        if let Some(ch) = &ns.children {
            let fragment = has("loop") || has("alt") || has("opt") || has("else");
            let inner = if is_sequence { true } else if fragment { in_seq } else { false };
            precheck_stmts(ch, sheet, inner)?;
        }
    }
    Ok(())
}

pub fn validate(ctx: &Ctx) -> Result<(), Diag> {
    for i in 1..ctx.nodes.len() {
        let n = &ctx.nodes[i];
        if n.prim == Prim::Text {
            continue;
        }
        let name = n.chain.first().cloned().unwrap_or_default();
        if is_frame_node(n) && host_seq(ctx, i).is_none() {
            return Err(Diag::error("layout", &format!("'|{}|' belongs in a 'layout: sequence'", name), n.span));
        }
        if is_else_node(n) {
            let in_alt = n.parent.map(|p| ctx.nodes[p].is("alt")).unwrap_or(false);
            if !in_alt {
                return Err(Diag::error("layout", "'|else|' separates an '|alt|' — write it inside one", n.span));
            }
        }
        let in_seq = host_seq(ctx, i).is_some();
        if is_note_node(n) && in_seq {
            match place_decl(ctx, i) {
                None => return Err(Diag::error("layout", "a sequence '|note|' needs 'place:'", n.span)),
                Some(d) => {
                    if parse_place(&d.value).is_none() {
                        return Err(Diag::error("layout", PLACE_ERR, n.span));
                    }
                }
            }
        }
    }
    for i in 0..ctx.nodes.len() {
        if is_seq(ctx, i) && ctx.nodes[i].prim == Prim::Block {
            if participants(ctx, i).is_empty() {
                return Err(Diag::error("layout", "a sequence needs at least one participant", ctx.nodes[i].span));
            }
        }
    }
    Ok(())
}

// ------------------------------------------------------------ layout model

#[derive(Clone, Debug, Default)]
pub struct Bar {
    pub part: usize,
    pub depth: usize,
    pub y0: f64,
    pub y1: f64,
}

#[derive(Clone, Debug, Default)]
pub struct Msg {
    pub li: usize,
    pub pts: Vec<(f64, f64)>,
    pub radii: Vec<f64>,
    pub label: Option<(String, f64, f64)>,
}

#[derive(Clone, Debug, Default)]
pub struct Frame {
    pub node: usize,
    pub depth: usize,
    pub top: f64,
    pub bottom: f64,
    // outer box edges (stroke included)
    pub left: f64,
    pub right: f64,
    pub drawn: bool,
    pub elses: Vec<(usize, f64)>,
    pub tab_w: f64,
}

#[derive(Clone, Debug, Default)]
pub struct NoteGeo {
    pub node: usize,
    pub cx: f64,
    pub cy: f64,
    // the outline's size (stroke included)
    pub w: f64,
    pub h: f64,
    pub drawn: bool,
}

#[derive(Clone, Debug, Default)]
pub struct Layout {
    pub parts: Vec<usize>,
    pub px: Vec<f64>,
    pub bottoms: Vec<f64>,
    pub end: f64,
    pub bars: Vec<Bar>,
    pub msgs: Vec<Msg>,
    pub frames: Vec<Frame>,
    pub notes: Vec<NoteGeo>,
}

thread_local! {
    static LAYOUTS: RefCell<HashMap<usize, Layout>> = RefCell::new(HashMap::new());
}

fn with_layout<R>(i: usize, f: impl FnOnce(&Layout) -> R) -> Option<R> {
    LAYOUTS.with(|m| m.borrow().get(&i).map(f))
}

// The participants of a sequence: its children that are neither fragments,
// notes nor bare text.
pub fn participants(ctx: &Ctx, s: usize) -> Vec<usize> {
    ctx.nodes[s]
        .children
        .iter()
        .copied()
        .filter(|&c| {
            let n = &ctx.nodes[c];
            n.prim != Prim::Text && !is_fragment_node(n) && !is_note_node(n)
        })
        .collect()
}

#[derive(Clone, Debug)]
enum Ev {
    Msg(usize),
    Note(usize),
    Open(usize),
    Else(usize, usize),
    Close(usize),
}

fn span_contains(outer: Span, inner: Span) -> bool {
    outer.start <= inner.start && inner.end <= outer.end
}

// The sequence's timeline: messages, notes and fragment edges in source order.
fn events(ctx: &Ctx, s: usize) -> Vec<Ev> {
    // every fragment under the sequence
    let mut frags = Vec::new();
    let mut stack: Vec<usize> = ctx.nodes[s].children.iter().rev().copied().collect();
    while let Some(n) = stack.pop() {
        if is_frame_node(&ctx.nodes[n]) {
            frags.push(n);
            for &c in ctx.nodes[n].children.iter().rev() {
                stack.push(c);
            }
        }
    }
    // a message belongs to the innermost fragment around its statement
    let mut owner: HashMap<usize, usize> = HashMap::new();
    let mut mine: Vec<usize> = Vec::new();
    for li in 0..ctx.links.len() {
        if ctx.links[li].container != s {
            continue;
        }
        mine.push(li);
        let sp = ctx.links[li].span;
        let mut best = s;
        let mut best_len = usize::MAX;
        for &f in &frags {
            let fs = ctx.nodes[f].span;
            if span_contains(fs, sp) && fs.end - fs.start < best_len {
                best = f;
                best_len = fs.end - fs.start;
            }
        }
        owner.insert(li, best);
    }
    let mut out = Vec::new();
    walk(ctx, s, s, &mine, &owner, &mut out);
    out
}

fn walk(ctx: &Ctx, s: usize, c: usize, mine: &[usize], owner: &HashMap<usize, usize>, out: &mut Vec<Ev>) {
    // (start, tie, item): item 0 = node, 1 = link
    let mut items: Vec<(usize, usize, usize, usize)> = Vec::new();
    for &ch in &ctx.nodes[c].children {
        let n = &ctx.nodes[ch];
        if n.prim == Prim::Text {
            continue;
        }
        if is_frame_node(n) || is_note_node(n) || (c != s && is_else_node(n)) {
            items.push((n.span.start, ch, 0, ch));
        }
    }
    for &li in mine {
        if owner.get(&li) == Some(&c) {
            items.push((ctx.links[li].span.start, li, 1, li));
        }
    }
    items.sort();
    for (_, _, kind, x) in items {
        if kind == 1 {
            out.push(Ev::Msg(x));
            continue;
        }
        let n = &ctx.nodes[x];
        if is_frame_node(n) {
            out.push(Ev::Open(x));
            walk(ctx, s, x, mine, owner, out);
            out.push(Ev::Close(x));
        } else if is_note_node(n) {
            out.push(Ev::Note(x));
        } else if is_else_node(n) {
            out.push(Ev::Else(x, c));
        }
    }
}

// ------------------------------------------------------------ helpers

fn label_of(l: &Link) -> Option<String> {
    if let Some(t) = &l.label {
        return Some(t.trim().to_string());
    }
    for st in &l.labels {
        if let Stmt::Text(t) = st {
            return Some(t.text.trim().to_string());
        }
    }
    None
}

// The line part of an operator decides the message's meaning.
#[derive(Clone, Copy, PartialEq, Debug)]
enum Kind {
    Call,
    Return,
    Async,
}

fn kind_of(op: &str) -> Kind {
    let (_, line, _) = crate::links::split_op(op);
    if line == "--" {
        Kind::Return
    } else if line.contains('~') {
        Kind::Async
    } else {
        Kind::Call
    }
}

fn msg_family(ctx: &Ctx, s: usize) -> Family {
    ctx.comp[s].family
}

fn label_width(ctx: &Ctx, s: usize, text: &str) -> f64 {
    let fam = msg_family(ctx, s);
    let mut w: f64 = 0.0;
    for line in text.split('\n') {
        w = w.max(crate::font::text_width(fam, 400, 13.0, line));
    }
    w
}

// The value a node's classes, id rules or own declarations give a property
// (what outranks a contextual rule).
fn own_value(ctx: &Ctx, i: usize, name: &str) -> Option<Value> {
    let n = &ctx.nodes[i];
    let mut v = None;
    for c in &n.classes {
        if let Some(cr) = ctx.sheet.class(c) {
            for d in &cr.decls {
                if d.name == name {
                    v = Some(d.value.clone());
                }
            }
        }
    }
    if let Some(id) = &n.id {
        for (rid, ds) in &ctx.sheet.id_rules {
            if rid == id {
                for d in ds {
                    if d.name == name {
                        v = Some(d.value.clone());
                    }
                }
            }
        }
    }
    for d in &n.inline {
        if d.name == name {
            v = Some(d.value.clone());
        }
    }
    v
}

fn pad4(ctx: &Ctx, v: &Value) -> Option<[f64; 4]> {
    let xs = value_nums(&ctx.sheet.env, v);
    match xs.len() {
        1 => Some([xs[0]; 4]),
        2 => Some([xs[0], xs[1], xs[0], xs[1]]),
        4 => Some([xs[0], xs[1], xs[2], xs[3]]),
        _ => None,
    }
}

// A sequence note reads the contextual rule `.lini-sequence .lini-note
// { padding: 6 10; font-size: 13 }` unless its classes, id or own
// declarations say otherwise.
fn note_context(ctx: &mut Ctx, i: usize) {
    let fs = own_value(ctx, i, "font-size").and_then(|v| value_num(&ctx.sheet.env, &v)).unwrap_or(13.0);
    let pad = own_value(ctx, i, "padding").and_then(|v| pad4(ctx, &v)).unwrap_or([6.0, 10.0, 6.0, 10.0]);
    let old = ctx.comp[i].font_size;
    ctx.comp[i].font_size = fs;
    ctx.comp[i].padding = pad;
    // descendants that inherited the old size take the new one
    let mut stack: Vec<usize> = ctx.nodes[i].children.clone();
    while let Some(c) = stack.pop() {
        let own = ctx.nodes[c].inline.iter().any(|d| d.name == "font-size" || d.name == "font-scale")
            || ctx.nodes[c].classes.iter().any(|k| ctx.sheet.class(k).map_or(false, |cr| cr.decls.iter().any(|d| d.name == "font-size")));
        if !own && (ctx.comp[c].font_size - old).abs() < 1e-12 {
            ctx.comp[c].font_size = fs;
            for &g in &ctx.nodes[c].children {
                stack.push(g);
            }
        }
    }
}

fn dbg() -> bool {
    std::env::var("LINI_DBG_SEQ").is_ok()
}

// ------------------------------------------------------------ measure

pub fn measure(ctx: &mut Ctx, s: usize, _avail: Option<f64>) {
    let parts = participants(ctx, s);
    for &p in &parts {
        crate::layout::measure(ctx, p, None);
        // a participant stands on its lifeline: no nudging off it
        ctx.comp[p].translate = (0.0, 0.0);
    }
    let n = parts.len();
    // a sequence root's gap defaults to the sequence type's
    let (gap_row, gap_col) = if s == 0 && !ctx.sheet.root.iter().any(|d| d.name == "gap") { (32.0, 32.0) } else { ctx.comp[s].gap };
    let activation = ctx.nodes[s].props.get("activation").and_then(|v| ident_of(v).map(|x| x.to_string())).as_deref() != Some("none");
    let sizes: Vec<(f64, f64)> = parts.iter().map(|&p| crate::layout::outer(ctx, p)).collect();
    let index: HashMap<usize, usize> = parts.iter().enumerate().map(|(k, &p)| (p, k)).collect();
    let evs = events(ctx, s);
    // ---- horizontal: a labelled message spreads the gaps it spans until
    // its label (plus 8 a side) fits between the two lifelines
    let ws: Vec<f64> = sizes.iter().map(|s| s.0).collect();
    let mut extra: Vec<f64> = vec![0.0; n.saturating_sub(1)];
    for ev in &evs {
        if let Ev::Msg(li) = ev {
            let l = &ctx.links[*li];
            let (Some(&a), Some(&b)) = (index.get(&l.from), index.get(&l.to)) else { continue };
            if a == b {
                continue;
            }
            let Some(text) = label_of(l) else { continue };
            let need = label_width(ctx, s, &text) + 16.0;
            let (i, j) = if a < b { (a, b) } else { (b, a) };
            let mut cur = ws[i] / 2.0 + ws[j] / 2.0;
            for k in i..j {
                cur += gap_col + extra[k];
                if k > i {
                    cur += ws[k];
                }
            }
            if cur < need {
                let add = (need - cur) / (j - i) as f64;
                for k in i..j {
                    extra[k] += add;
                }
            }
        }
    }
    let mut px = vec![0.0; n];
    let mut cur = 0.0;
    for k in 0..n {
        cur += ws[k] / 2.0;
        px[k] = cur;
        cur += ws[k] / 2.0;
        if k + 1 < n {
            cur += gap_col + extra[k];
        }
    }
    let row = cur;
    for x in px.iter_mut() {
        *x -= row / 2.0;
    }
    // ---- notes measure with the contextual rule
    let note_nodes: Vec<usize> = evs.iter().filter_map(|e| if let Ev::Note(i) = e { Some(*i) } else { None }).collect();
    for &nn in &note_nodes {
        note_context(ctx, nn);
        crate::layout::measure(ctx, nn, None);
    }
    // ---- vertical: the timeline runs in offsets below the participant row,
    // then hangs from the row's bottom once the whole height is known (the
    // content is centred on row + timeline)
    let header: f64 = sizes.iter().map(|s| s.1).fold(0.0, f64::max);
    let tl = Tl { s, evs: &evs, parts: &parts, index: &index, px: &px, gap_row, activation };
    let (mut bars, mut msgs, mut frames, mut notes, ext, tail) = timeline(ctx, &tl);
    let end_rel = header + tail;
    let mid = end_rel / 2.0;
    let top = -mid;
    let base = top + header;
    for b in bars.iter_mut() {
        b.y0 = base + b.y0;
        if !b.y1.is_nan() {
            b.y1 = base + b.y1;
        }
    }
    for m in msgs.iter_mut() {
        for p in m.pts.iter_mut() {
            p.1 = base + p.1;
        }
        if let Some(l) = m.label.as_mut() {
            l.2 = base + l.2;
        }
    }
    for fr in frames.iter_mut() {
        fr.top = base + fr.top;
        fr.bottom = base + fr.bottom;
        for e in fr.elses.iter_mut() {
            e.1 = base + e.1;
        }
    }
    for g in notes.iter_mut() {
        g.cy = base + g.cy;
    }
    let end = base + tail;
    // ---- frames across: the messages' lifelines, padded (inset per level)
    for (k, fr) in frames.iter_mut().enumerate() {
        let node = fr.node;
        if let Some((lo, hi)) = ext[k] {
            let p = ctx.comp[node].padding;
            let pl = (p[3] - 6.0 * fr.depth as f64).max(6.0);
            let pr = (p[1] - 6.0 * fr.depth as f64).max(6.0);
            fr.left = lo - pl;
            fr.right = hi + pr;
            fr.drawn = true;
        }
        let fam = ctx.comp[node].family;
        let fs = ctx.comp[node].font_size;
        let tab = fragment_name(&ctx.nodes[node]);
        fr.tab_w = crate::font::text_width(fam, 700, fs, &tab) + 14.0;
    }
    for b in bars.iter_mut() {
        if b.y1.is_nan() {
            b.y1 = end;
        }
    }
    // ---- extents: the content box is centred on the participant row
    let mut lo = f64::INFINITY;
    let mut hi = f64::NEG_INFINITY;
    // participants hang from the timeline's top
    for k in 0..n {
        let p = parts[k];
        ctx.nodes[p].x = px[k];
        ctx.nodes[p].y = top + sizes[k].1 / 2.0;
    }
    seq_rest(ctx, s, &parts, &sizes, px, bars, msgs, frames, notes, mid, top, end, &mut lo, &mut hi);
}

struct Tl<'a> {
    s: usize,
    evs: &'a [Ev],
    parts: &'a [usize],
    index: &'a HashMap<usize, usize>,
    px: &'a [f64],
    gap_row: f64,
    activation: bool,
}

type TimelineOut = (Vec<Bar>, Vec<Msg>, Vec<Frame>, Vec<NoteGeo>, Vec<Option<(f64, f64)>>, f64);

// Walk the timeline in offsets below the participant row: message, note and
// fragment positions, activation bars, frame spans. Returns the timeline's
// length (last event plus a row gap) as the last value.
fn timeline(ctx: &Ctx, tl: &Tl) -> TimelineOut {
    let s = tl.s;
    let parts = tl.parts;
    let index = tl.index;
    let px = tl.px;
    let gap_row = tl.gap_row;
    let activation = tl.activation;
    let n = parts.len();
    let mut y = 0.0;
    let mut fresh = false;
    let mut bars: Vec<Bar> = Vec::new();
    let mut stacks: Vec<Vec<usize>> = vec![vec![]; n];
    let mut msgs: Vec<Msg> = Vec::new();
    let mut frames: Vec<Frame> = Vec::new();
    let mut open: Vec<usize> = Vec::new(); // indices into frames
    let mut notes: Vec<NoteGeo> = Vec::new();
    // frame extents: lifeline x range of the messages inside
    let mut ext: Vec<Option<(f64, f64)>> = Vec::new();
    let bar_x = |px: &[f64], b: &Bar| px[b.part] + 4.0 * b.depth as f64;
    for ev in tl.evs {
        match ev {
            Ev::Msg(li) => {
                let l = ctx.links[*li].clone();
                // only a participant's own lifeline carries a message
                let pa = index.get(&l.from).copied();
                let pb = index.get(&l.to).copied();
                let kind = kind_of(&l.op);
                let label = label_of(&l);
                let pad_top = open.last().map(|&f| frame_pads(ctx, frames[f].node).0);
                if pa.is_some() && pa == pb {
                    // a self-message: internal work, activation unchanged
                    let a = pa.unwrap();
                    y += if fresh { pad_top.unwrap_or(0.0) } else { gap_row };
                    fresh = false;
                    let lx = px[a];
                    let sx = match stacks[a].last() {
                        Some(&bi) => {
                            let bx = bar_x(&px, &bars[bi]);
                            if lx >= bx {
                                bx + 6.0
                            } else {
                                bx - 6.0
                            }
                        }
                        None => lx,
                    };
                    let pts = vec![(sx, y), (sx + 16.0, y), (sx + 16.0, y + 16.0), (sx, y + 16.0)];
                    let lab = label.map(|t| {
                        let tw = label_width(ctx, s, &t);
                        (t, sx + 8.0 + tw / 2.0, y - 11.5)
                    });
                    msgs.push(Msg { li: *li, pts, radii: vec![8.0, 8.0], label: lab });
                    for &f in &open {
                        let e = ext[f].get_or_insert((lx, lx + 21.0));
                        e.0 = e.0.min(lx);
                        e.1 = e.1.max(lx + 21.0);
                    }
                    y += 16.0;
                    continue;
                }
                y += if fresh { pad_top.unwrap_or(0.0).max(32.0) } else { gap_row };
                fresh = false;
                if kind == Kind::Call && activation {
                    if let Some(b) = pb {
                        let depth = stacks[b].len();
                        bars.push(Bar { part: b, depth, y0: y, y1: f64::NAN });
                        stacks[b].push(bars.len() - 1);
                    }
                }
                let (Some(a), Some(b)) = (pa, pb) else {
                    // drawn nowhere, but its lifeline end still spans the frames
                    for k in [pa, pb].into_iter().flatten() {
                        let x = px[k];
                        for &f in &open {
                            let e = ext[f].get_or_insert((x, x));
                            e.0 = e.0.min(x);
                            e.1 = e.1.max(x);
                        }
                    }
                    if kind == Kind::Return && activation {
                        if let Some(a) = pa {
                            if let Some(bi) = stacks[a].pop() {
                                bars[bi].y1 = y;
                            }
                        }
                    }
                    continue;
                };
                let (xa, xb) = (px[a], px[b]);
                let sx = match stacks[a].last() {
                    Some(&bi) => {
                        let bx = bar_x(&px, &bars[bi]);
                        if xb >= bx {
                            bx + 6.0
                        } else {
                            bx - 6.0
                        }
                    }
                    None => xa,
                };
                let ex = match stacks[b].last() {
                    Some(&bi) => {
                        let bx = bar_x(&px, &bars[bi]);
                        if xa >= bx {
                            bx + 6.0
                        } else {
                            bx - 6.0
                        }
                    }
                    None => xb,
                };
                if kind == Kind::Return && activation {
                    if let Some(bi) = stacks[a].pop() {
                        bars[bi].y1 = y;
                    }
                }
                let lab = label.map(|t| (t, (xa + xb) / 2.0, y - 11.5));
                msgs.push(Msg { li: *li, pts: vec![(sx, y), (ex, y)], radii: vec![], label: lab });
                let (lo, hi) = if xa < xb { (xa, xb) } else { (xb, xa) };
                for &f in &open {
                    let e = ext[f].get_or_insert((lo, hi));
                    e.0 = e.0.min(lo);
                    e.1 = e.1.max(hi);
                }
            }
            Ev::Note(i) => {
                let pad_top = open.last().map(|&f| frame_pads(ctx, frames[f].node).0);
                y += if fresh { pad_top.unwrap_or(0.0) } else { gap_row / 2.0 };
                fresh = false;
                let (nw, nh) = crate::layout::outer(ctx, *i);
                let place = place_decl(ctx, *i).and_then(|d| parse_place(&d.value));
                let mut g = NoteGeo { node: *i, cx: 0.0, cy: y + nh / 2.0, w: nw, h: nh, drawn: false };
                if let Some((mode, names)) = place {
                    let ks: Vec<Option<usize>> = names.iter().map(|nm| parts.iter().position(|&p| ctx.nodes[p].id.as_deref() == Some(nm.as_str()))).collect();
                    if ks.iter().all(|k| k.is_some()) && !ks.is_empty() {
                        let xs: Vec<f64> = ks.iter().map(|k| px[k.unwrap()]).collect();
                        let lo = xs.iter().cloned().fold(f64::INFINITY, f64::min);
                        let hi = xs.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
                        g.drawn = true;
                        match mode.as_str() {
                            "left" => g.cx = lo - nw / 2.0 - 12.0,
                            "right" => g.cx = hi + nw / 2.0 + 12.0,
                            _ => {
                                g.w = nw.max(hi - lo + 24.0);
                                g.cx = (lo + hi) / 2.0;
                            }
                        }
                    }
                }
                notes.push(g);
                y += nh;
            }
            Ev::Open(f) => {
                if !fresh {
                    y += gap_row;
                }
                fresh = true;
                frames.push(Frame { node: *f, depth: open.len(), top: y, ..Default::default() });
                ext.push(None);
                open.push(frames.len() - 1);
            }
            Ev::Else(e, f) => {
                let k = frames.iter().rposition(|fr| fr.node == *f).unwrap_or(0);
                y += frame_pads(ctx, *f).1;
                fresh = true;
                frames[k].elses.push((*e, y));
            }
            Ev::Close(f) => {
                let k = open.pop().unwrap_or(0);
                let (pt, pb) = frame_pads(ctx, *f);
                if fresh {
                    y += pt;
                }
                y += pb;
                fresh = false;
                frames[k].bottom = y;
            }
        }
    }
    let end = y + gap_row;
    (bars, msgs, frames, notes, ext, end)
}

// Extents, the node's size, and the stored layout.
#[allow(clippy::too_many_arguments)]
fn seq_rest(
    ctx: &mut Ctx,
    s: usize,
    parts: &[usize],
    sizes: &[(f64, f64)],
    px: Vec<f64>,
    bars: Vec<Bar>,
    msgs: Vec<Msg>,
    frames: Vec<Frame>,
    mut notes: Vec<NoteGeo>,
    mid: f64,
    top: f64,
    end: f64,
    lo: &mut f64,
    hi: &mut f64,
) {
    let n = parts.len();
    // participants count with everything they carry (captions, badges)
    let mut vlo = f64::INFINITY;
    let mut vhi = f64::NEG_INFINITY;
    for &p in parts {
        let mut b = [f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY];
        crate::render::bbox_walk(ctx, p, &[1.0, 0.0, 0.0, 1.0, 0.0, 0.0], &mut b);
        *lo = lo.min(b[0]);
        *hi = hi.max(b[2]);
        vlo = vlo.min(b[1]);
        vhi = vhi.max(b[3]);
    }
    let mut take = |a: f64, b: f64| {
        *lo = lo.min(a);
        *hi = hi.max(b);
    };
    // nested bars can stand out of a narrow participant's column
    for b in &bars {
        let x = px[b.part] + 4.0 * b.depth as f64;
        take(x - 6.0, x + 6.0);
    }
    for g in &notes {
        if g.drawn {
            take(g.cx - g.w / 2.0, g.cx + g.w / 2.0);
        }
    }
    for fr in &frames {
        if !fr.drawn {
            continue;
        }
        take(fr.left, fr.right);
        take(fr.left, fr.left + fr.tab_w);
        let fam = ctx.comp[fr.node].family;
        let fs = ctx.comp[fr.node].font_size;
        if let Some(g) = guard_text(&ctx.nodes[fr.node]) {
            let gw = widest(fam, 400, fs, &g);
            let gl = fr.left + fr.tab_w + 4.0;
            take(gl, gl + gw);
        }
        for &(e, _) in &fr.elses {
            if let Some(g) = guard_text(&ctx.nodes[e]) {
                let gw = widest(fam, 400, fs, &g);
                take(fr.left, fr.left + gw);
            }
        }
    }
    for m in &msgs {
        for &(x, _) in &m.pts {
            take(x, x);
        }
        if let Some((_, x, _)) = &m.label {
            take(*x, *x);
        }
    }
    let half = if lo.is_finite() { (-*lo).max(*hi) } else { 0.0 };
    let cw = 2.0 * half;
    // a bar too short to see still claims a unit
    let mut vhalf = mid;
    for b in &bars {
        let cy = (b.y0 + b.y1) / 2.0;
        vhalf = vhalf.max(cy + (b.y1 - b.y0).max(1.0) / 2.0);
    }
    if vlo.is_finite() {
        vhalf = vhalf.max(-vlo).max(vhi);
    }
    let ch = 2.0 * vhalf;
    if s == 0 {
        // the root's padding frames the view
        let pad = ctx.comp[s].padding;
        ctx.nodes[s].w = cw + pad[1] + pad[3];
        ctx.nodes[s].h = ch + pad[0] + pad[2];
    } else {
        // a nested sequence is its content (a stroke draws inside it)
        let sw = if ctx.comp[s].has_stroke { ctx.comp[s].stroke_width } else { 0.0 };
        ctx.nodes[s].w = cw - sw;
        ctx.nodes[s].h = ch - sw;
    }
    let mut bottoms = vec![0.0; n];
    for k in 0..n {
        bottoms[k] = top + sizes[k].1;
    }
    for g in notes.iter_mut() {
        let i = g.node;
        ctx.nodes[i].x = g.cx;
        ctx.nodes[i].y = g.cy;
        if !g.drawn {
            // a note over no lifeline takes its row but draws (and spans) nothing
            let mut stack = vec![i];
            while let Some(k) = stack.pop() {
                ctx.nodes[k].w = 0.0;
                ctx.nodes[k].h = 0.0;
                stack.extend(ctx.nodes[k].children.iter().copied());
            }
        }
    }
    if dbg() {
        eprintln!("SEQ px={:?} sizes={:?}", px, sizes);
        for m in &msgs {
            eprintln!("MSG {} {:?}", m.li, m.pts);
        }
    }
    let lay = Layout { parts: parts.to_vec(), px, bottoms, end, bars, msgs, frames, notes };
    LAYOUTS.with(|m| {
        m.borrow_mut().insert(s, lay);
    });
}

// (top, bottom) padding of a fragment: never under the bar's half-width
fn frame_pads(ctx: &Ctx, f: usize) -> (f64, f64) {
    let p = ctx.comp[f].padding;
    (p[0].max(6.0), p[2].max(6.0))
}

fn fragment_name(n: &Node) -> String {
    for t in ["loop", "alt", "opt"] {
        if n.is(t) {
            return t.to_string();
        }
    }
    String::new()
}

fn guard_text(n: &Node) -> Option<String> {
    match n.label.as_deref().map(|l| l.trim()) {
        Some(l) if !l.is_empty() => Some(format!("[{}]", l)),
        _ => None,
    }
}

// The widest line of a (possibly multi-line) text.
fn widest(fam: Family, weight: u32, fs: f64, text: &str) -> f64 {
    let mut w: f64 = 0.0;
    for line in text.split('\n') {
        w = w.max(crate::font::text_width(fam, weight, fs, line));
    }
    w
}

// A centred text element; lines stack at 1.2 em of the drawn size.
fn text_elem(cls: &str, x: f64, y: f64, text: &str, drawn_fs: f64, style: &str) -> String {
    let lines: Vec<&str> = text.split('\n').collect();
    if lines.len() <= 1 {
        return format!(
            "<text class=\"{}\" x=\"{}\" y=\"{}\" dy=\"0.358em\"{}>{}</text>",
            cls,
            f4(x),
            f4(y),
            style,
            xml_escape(text)
        );
    }
    let pitch = 1.2 * drawn_fs;
    let total = (lines.len() as f64 - 1.0) * pitch;
    let first = y - total / 2.0 + 0.358 * drawn_fs;
    let mut t = String::new();
    for (k, l) in lines.iter().enumerate() {
        if k == 0 {
            t.push_str(&format!("<tspan x=\"{}\" y=\"{}\">{}</tspan>", f4(x), f4(first), xml_escape(l)));
        } else {
            t.push_str(&format!("<tspan x=\"{}\" dy=\"{}\">{}</tspan>", f4(x), f4(pitch), xml_escape(l)));
        }
    }
    format!("<text class=\"{}\" x=\"{}\" y=\"{}\"{}>{}</text>", cls, f4(x), f4(y), style, t)
}

// ------------------------------------------------------------ links

// The messages of every sequence as link geometry, in absolute coordinates.
pub fn link_geo(ctx: &Ctx, li: usize) -> Option<LinkGeo> {
    let s = ctx.links[li].container;
    if !is_seq(ctx, s) {
        return None;
    }
    let (ox, oy) = crate::links::abs_center(ctx, s);
    with_layout(s, |lay| {
        let m = lay.msgs.iter().find(|m| m.li == li)?;
        let style = crate::links::link_style(ctx, li);
        let pts: Vec<(f64, f64)> = m.pts.iter().map(|&(x, y)| (x + ox, y + oy)).collect();
        let mut labels = Vec::new();
        if let Some((t, x, y)) = &m.label {
            labels.push(Label {
                text: t.clone(),
                x: x + ox,
                y: y + oy,
                tw: 0.0,
                fs: 0.0,
                units: vec![],
                upem: 1000.0,
                classes: vec![],
                props: vec![],
            });
        }
        Some(LinkGeo { li, pts, radii: m.radii.clone(), style, labels, seq: true, ..Default::default() })
    })
    .flatten()
}

// ------------------------------------------------------------ render

fn ind(n: usize) -> String {
    " ".repeat(n)
}

// The CSS a type's own rule gives (defaults then user type rules).
fn type_rule(ctx: &Ctx, t: &str) -> Vec<(String, Value)> {
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
    for d in ctx.sheet.type_rule(t) {
        set(&d.name, &d.value);
    }
    props
}

fn css_of(ctx: &Ctx, props: &[(String, Value)], keys: &[&str], vars: &mut Vec<String>) -> Result<Vec<(String, String)>, Diag> {
    let env = &ctx.sheet.env;
    let sw = get(props, "stroke-width").and_then(|v| value_num(env, v)).unwrap_or(2.0);
    let mut out = Vec::new();
    for &k in keys {
        let Some(v) = get(props, k) else { continue };
        match k {
            "fill" | "stroke" => {
                if let Some(t) = single_term(v) {
                    out.push((k.to_string(), color_css(t, vars, v.span)?));
                }
            }
            "stroke-width" => {
                if let Some(x) = value_num(env, v) {
                    out.push((k.to_string(), f4(x)));
                }
            }
            "stroke-style" => {
                if let Some(st) = ident_of(v) {
                    if let Some(d) = dasharray(st, sw) {
                        out.push(("stroke-dasharray".to_string(), d));
                    }
                }
            }
            _ => {}
        }
    }
    Ok(out)
}

fn minus(own: Vec<(String, String)>, rule: &[(String, String)]) -> Vec<(String, String)> {
    own.into_iter().filter(|(k, v)| !rule.iter().any(|(rk, rv)| rk == k && rv == v)).collect()
}

fn join(d: &[(String, String)]) -> String {
    d.iter().map(|(k, v)| format!("{}: {}", k, v)).collect::<Vec<_>>().join("; ")
}

fn style_attr(d: &[(String, String)]) -> String {
    if d.is_empty() {
        String::new()
    } else {
        format!(" style=\"{}\"", xml_escape(&join(d)))
    }
}

fn mark_type(out: &mut Out, t: &str) {
    if !out.used_types.iter().any(|x| x == t) {
        out.used_types.push(t.to_string());
    }
}

fn push_rule(out: &mut Out, slot: &str, rule: &str) {
    if !out.extra_rules.iter().any(|(k, r)| k == slot && r == rule) {
        out.extra_rules.push((slot.to_string(), rule.to_string()));
    }
}

fn use_vars(out: &mut Out, vars: Vec<String>, kept: &[(String, String)]) {
    for v in vars {
        if kept.iter().any(|(_, val)| val.contains(&format!("var(--lini-{})", v))) {
            use_var(&mut out.vars, &v);
        }
    }
}

// The scene part of a sequence: frames, lifelines, bars, participants,
// tabs and guards, notes.
pub fn render_children(ctx: &Ctx, s: usize, ci: usize, out: &mut Out, buf: &mut String) -> Result<(), Diag> {
    let Some(lay) = with_layout(s, |l| l.clone()) else { return Ok(()) };
    // bars and frame boxes are blocks, lifelines and branch rules lines
    if !lay.bars.is_empty() || lay.frames.iter().any(|f| f.drawn) {
        mark_type(out, "block");
    }
    mark_type(out, "line");
    // a fragment's type rule resolves its paint (not emitted, but its
    // variables are), whatever the fragment's own declarations say
    for fr in &lay.frames {
        let mut nodes = vec![fr.node];
        nodes.extend(fr.elses.iter().map(|e| e.0));
        for i in nodes {
            for t in ctx.nodes[i].chain.iter().filter(|t| t.as_str() != "block") {
                let r = type_rule(ctx, t);
                let mut vars = Vec::new();
                let _ = css_of(ctx, &r, &["fill", "stroke"], &mut vars);
                for v in vars {
                    use_var(&mut out.vars, &v);
                }
            }
        }
    }
    let block_rule = {
        let mut r = type_rule(ctx, "block");
        if get(&r, "stroke-style").is_none() {
            r.push(("stroke-style".into(), Value { groups: vec![vec![Term::Ident("solid".into(), Span::default())]], span: Span::default() }));
        }
        let mut tmp = Vec::new();
        css_of(ctx, &r, &["fill", "stroke", "stroke-width", "stroke-style"], &mut tmp)?
    };
    let line_rule = {
        let r = type_rule(ctx, "line");
        let mut tmp = Vec::new();
        css_of(ctx, &r, &["fill", "stroke", "stroke-width"], &mut tmp)?
    };
    // frame boxes and their branch lines
    for fr in &lay.frames {
        if !fr.drawn {
            continue;
        }
        let f = fr.node;
        let props: Vec<(String, Value)> = ctx.nodes[f].props.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        let props = ordered(&props);
        let mut vars = Vec::new();
        let own = css_of(ctx, &props, &["fill", "stroke", "stroke-width", "stroke-style"], &mut vars)?;
        let keep = minus(own, &block_rule);
        use_vars(out, vars, &keep);
        let sw = frame_sw(ctx, f);
        let ow = fr.right - fr.left;
        let oh = fr.bottom - fr.top;
        let (w, h) = (ow - sw, oh - sw);
        let cx = (fr.left + fr.right) / 2.0;
        let cy = (fr.top + fr.bottom) / 2.0;
        let r = ctx.comp[f].radius;
        buf.push_str(&format!(
            "{}<g class=\"lini-node lini-block\"{} transform=\"translate({},{})\">\n",
            ind(ci),
            style_attr(&keep),
            f4(cx),
            f4(cy)
        ));
        buf.push_str(&format!(
            "{}<rect x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" rx=\"{}\" ry=\"{}\"/>\n",
            ind(ci + 2),
            f4(-w / 2.0),
            f4(-h / 2.0),
            f4(w),
            f4(h),
            f4(r),
            f4(r)
        ));
        buf.push_str(&format!("{}</g>\n", ind(ci)));
        for &(_, ey) in &fr.elses {
            let mut vars = Vec::new();
            let mut d = Vec::new();
            if let Some(v) = get(&props, "stroke") {
                if let Some(t) = single_term(v) {
                    d.push(("stroke".to_string(), color_css(t, &mut vars, v.span)?));
                }
            }
            d.push(("stroke-width".to_string(), "1".to_string()));
            d.push(("stroke-dasharray".to_string(), dasharray("dashed", 1.0).unwrap_or_default()));
            let keep = minus(d, &line_rule);
            use_vars(out, vars, &keep);
            buf.push_str(&format!(
                "{}<g class=\"lini-node lini-line\"{} transform=\"translate(0,0)\">\n",
                ind(ci),
                style_attr(&keep)
            ));
            buf.push_str(&format!(
                "{}<line x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\"/>\n",
                ind(ci + 2),
                f4(fr.left),
                f4(ey),
                f4(fr.right),
                f4(ey)
            ));
            buf.push_str(&format!("{}</g>\n", ind(ci)));
        }
    }
    // lifelines
    for (k, &p) in lay.parts.iter().enumerate() {
        let props: Vec<(String, Value)> = ctx.nodes[p].props.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        let props = ordered(&props);
        let mut vars = Vec::new();
        let own = css_of(ctx, &props, &["stroke", "stroke-width"], &mut vars)?;
        let keep = minus(own, &line_rule);
        use_vars(out, vars, &keep);
        let x = lay.px[k];
        buf.push_str(&format!(
            "{}<g class=\"lini-node lini-line\"{} transform=\"translate(0,0)\">\n",
            ind(ci),
            style_attr(&keep)
        ));
        buf.push_str(&format!(
            "{}<line x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\"/>\n",
            ind(ci + 2),
            f4(x),
            f4(lay.bottoms[k]),
            f4(x),
            f4(lay.end)
        ));
        buf.push_str(&format!("{}</g>\n", ind(ci)));
    }
    // activation bars
    for b in &lay.bars {
        let p = lay.parts[b.part];
        let props: Vec<(String, Value)> = ctx.nodes[p].props.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        let props = ordered(&props);
        let mut vars = Vec::new();
        let own = css_of(ctx, &props, &["fill", "stroke", "stroke-width"], &mut vars)?;
        let keep = minus(own, &block_rule);
        use_vars(out, vars, &keep);
        let sw = if ctx.comp[p].has_stroke { ctx.comp[p].stroke_width } else { 0.0 };
        let x = lay.px[b.part] + 4.0 * b.depth as f64;
        // a bar too short to see still claims a unit
        let len = (b.y1 - b.y0).max(1.0);
        let cy = (b.y0 + b.y1) / 2.0;
        let (w, h) = (12.0 - sw, len - sw);
        buf.push_str(&format!(
            "{}<g class=\"lini-node lini-block\"{} transform=\"translate({},{})\">\n",
            ind(ci),
            style_attr(&keep),
            f4(x),
            f4(cy)
        ));
        // a bar with no length draws nothing
        if w > 0.0 && h > 0.0 {
            buf.push_str(&format!(
                "{}<rect x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" rx=\"0\" ry=\"0\"/>\n",
                ind(ci + 2),
                f4(-w / 2.0),
                f4(-h / 2.0),
                f4(w),
                f4(h)
            ));
        }
        buf.push_str(&format!("{}</g>\n", ind(ci)));
    }
    // participants
    for p in crate::render::paint_order(ctx, &lay.parts) {
        crate::render::render_node(ctx, p, ci, buf, out)?;
    }
    // tabs and guards
    let mut any_tab = false;
    let mut any_guard = false;
    for fr in &lay.frames {
        let guarded = guard_text(&ctx.nodes[fr.node]).is_some() || fr.elses.iter().any(|&(e, _)| guard_text(&ctx.nodes[e]).is_some());
        if !fr.drawn {
            continue;
        }
        let f = fr.node;
        let props: Vec<(String, Value)> = ctx.nodes[f].props.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        let props = ordered(&props);
        // the tab sits on the stroke's centre line, drawn or not
        let sw = ctx.comp[f].stroke_width;
        let mut vars = Vec::new();
        let mut d: Vec<(String, String)> = Vec::new();
        use_var(&mut vars, "fill");
        d.push(("fill".into(), "var(--lini-fill)".into()));
        if let Some(v) = get(&props, "stroke") {
            if let Some(t) = single_term(v) {
                d.push(("stroke".into(), color_css(t, &mut vars, v.span)?));
            }
        }
        d.push(("stroke-width".into(), f4(sw)));
        use_vars(out, vars, &d);
        push_rule(out, "path", ".lini-path { stroke-dasharray: none; }");
        let left = fr.left + sw / 2.0;
        let top = fr.top + sw / 2.0;
        let r = ctx.comp[f].radius;
        let th = 16.0;
        let cut = 0.42 * th;
        let right = left + fr.tab_w;
        let mut path = format!(
            "M {} {} L {} {} L {} {} L {} {} L {} {} L {} {}",
            raw(left + r),
            raw(top),
            raw(right),
            raw(top),
            raw(right),
            raw(top + th - cut),
            raw(right - cut),
            raw(top + th),
            raw(left),
            raw(top + th),
            raw(left),
            raw(top + r)
        );
        if r > 0.0 {
            path.push_str(&format!(" A {} {} 0 0 1 {} {}", raw(r), raw(r), raw(left + r), raw(top)));
        }
        path.push_str(" Z");
        buf.push_str(&format!(
            "{}<g class=\"lini-node lini-path\" style=\"{}\" transform=\"translate(0,0)\">\n",
            ind(ci),
            xml_escape(&join(&d))
        ));
        buf.push_str(&format!("{}<path d=\"{}\"/>\n", ind(ci + 2), path));
        buf.push_str(&format!("{}</g>\n", ind(ci)));
        out.any_text = true;
        any_tab = true;
        let tab = fragment_name(&ctx.nodes[f]);
        let tx = left + (fr.tab_w - cut / 2.0) / 2.0;
        buf.push_str(&format!(
            "{}<text class=\"lini-text lini-sequence-tab\" x=\"{}\" y=\"{}\" dy=\"0.358em\">{}</text>\n",
            ind(ci),
            f4(tx),
            f4(top + th / 2.0),
            xml_escape(&tab)
        ));
        let fam = ctx.comp[f].family;
        let fs = ctx.comp[f].font_size;
        let mut gvars = Vec::new();
        let gstyle = match get(&props, "color").and_then(|v| single_term(v).map(|t| (t.clone(), v.span))) {
            Some((t, sp)) => vec![("fill".to_string(), color_css(&t, &mut gvars, sp)?)],
            None => vec![],
        };
        if guarded {
            use_vars(out, gvars, &gstyle);
        }
        if let Some(g) = guard_text(&ctx.nodes[f]) {
            any_guard = true;
            let gw = widest(fam, 400, fs, &g);
            let gx = fr.left + fr.tab_w + 4.0 + gw / 2.0;
            let el = text_elem("lini-text lini-sequence-guard", gx, fr.top + 9.0, &g, 11.0, &style_attr(&gstyle));
            buf.push_str(&format!("{}{}\n", ind(ci), el));
        }
        for &(e, ey) in &fr.elses {
            if let Some(g) = guard_text(&ctx.nodes[e]) {
                any_guard = true;
                let gw = widest(fam, 400, fs, &g);
                let gx = fr.left + gw / 2.0;
                let el = text_elem("lini-text lini-sequence-guard", gx, ey + fs, &g, 11.0, &style_attr(&gstyle));
                buf.push_str(&format!("{}{}\n", ind(ci), el));
            }
        }
    }
    if any_tab {
        push_rule(out, "sequence-tab", ".lini-sequence-tab { font-size: 12px; font-weight: 600; }");
    }
    if any_guard {
        push_rule(out, "sequence-guard", ".lini-sequence-guard { font-size: 11px; font-weight: normal; }");
    }
    // notes
    for g in &lay.notes {
        if !g.drawn {
            continue;
        }
        render_note(ctx, s, g, ci, out, buf)?;
    }
    Ok(())
}

fn frame_sw(ctx: &Ctx, f: usize) -> f64 {
    if ctx.comp[f].has_stroke {
        ctx.comp[f].stroke_width
    } else {
        0.0
    }
}

// Props in a stable order (the node's map is unordered).
fn ordered(props: &[(String, Value)]) -> Vec<(String, Value)> {
    let mut v = props.to_vec();
    v.sort_by(|a, b| a.0.cmp(&b.0));
    v
}

fn render_note(ctx: &Ctx, s: usize, g: &NoteGeo, ci: usize, out: &mut Out, buf: &mut String) -> Result<(), Diag> {
    let i = g.node;
    mark_type(out, "note");
    push_rule(out, "path", ".lini-path { stroke-dasharray: none; }");
    let nested = s != 0;
    // the note's effective look minus what its rules say
    let (_, all) = crate::compile::cascade(&ctx.sheet, &ctx.nodes[i]);
    // an ink the note inherits from a fragment around it resolves too
    if get(&all, "color").is_none() {
        let mut cur = ctx.nodes[i].parent;
        while let Some(p) = cur {
            if p == s || !is_fragment_node(&ctx.nodes[p]) {
                break;
            }
            if let Some(v) = ctx.nodes[p].props.get("color") {
                if let Some(t) = single_term(v) {
                    let mut vars = Vec::new();
                    let _ = color_css(t, &mut vars, v.span);
                    for x in vars {
                        use_var(&mut out.vars, &x);
                    }
                }
                break;
            }
            cur = ctx.nodes[p].parent;
        }
    }
    let mut eff: Vec<(String, Value)> = all.clone();
    let fs = ctx.comp[i].font_size;
    let set = |props: &mut Vec<(String, Value)>, k: &str, v: Value| {
        if let Some(e) = props.iter_mut().find(|e| e.0 == k) {
            e.1 = v;
        } else {
            props.push((k.to_string(), v));
        }
    };
    if own_value(ctx, i, "font-size").is_none() {
        set(&mut eff, "font-size", Value { groups: vec![vec![Term::Num(fs, f4(fs), Span::default())]], span: Span::default() });
    }
    let mut rule: Vec<(String, Value)> = type_rule(ctx, "note");
    for c in &ctx.nodes[i].classes {
        if let Some(cr) = ctx.sheet.class(c) {
            for d in &cr.decls {
                set(&mut rule, &d.name, d.value.clone());
            }
        }
    }
    if nested {
        // the contextual rule is emitted as a stylesheet rule
        push_rule(out, "seq-note-ctx", ".lini-sequence .lini-note { font-size: 13px; }");
        if own_value(ctx, i, "font-size").is_none() {
            set(&mut rule, "font-size", Value { groups: vec![vec![Term::Num(13.0, "13".into(), Span::default())]], span: Span::default() });
        }
    }
    // `.lini-path` only says the dash
    set(&mut rule, "stroke-style", Value { groups: vec![vec![Term::Ident("solid".into(), Span::default())]], span: Span::default() });
    let mut vars = Vec::new();
    let own_d = crate::render::css_decls(ctx, &eff, &mut vars, ctx.comp[i].stroke_width, false)?;
    let mut tmp = Vec::new();
    let rule_d = crate::render::css_decls(ctx, &rule, &mut tmp, 2.0, false)?;
    let keep = minus(own_d, &rule_d);
    use_vars(out, vars, &keep);
    // classes ride along
    let mut cls = String::from("lini-node lini-note lini-path");
    for c in &ctx.nodes[i].classes {
        cls.push_str(&format!(" lini-style-{}", c));
        if !out.used_classes.contains(c) {
            out.used_classes.push(c.clone());
        }
    }
    let mut head = format!("{}<g class=\"{}\"", ind(ci), cls);
    if let Some(id) = &ctx.nodes[i].id {
        head.push_str(&format!(" data-id=\"{}\"", xml_escape(id)));
    }
    head.push_str(&style_attr(&keep));
    head.push_str(&format!(" transform=\"translate({},{})\">\n", f4(g.cx), f4(g.cy)));
    buf.push_str(&head);
    let hw = g.w / 2.0;
    let hh = g.h / 2.0;
    let fold = (0.34 * g.h).min(15.0).min(g.w / 2.0);
    buf.push_str(&format!(
        "{}<path d=\"M {} {} L {} {} L {} {} L {} {} L {} {} Z\"/>\n",
        ind(ci + 2),
        raw(-hw),
        raw(-hh),
        raw(hw - fold),
        raw(-hh),
        raw(hw),
        raw(-hh + fold),
        raw(hw),
        raw(hh),
        raw(-hw),
        raw(hh)
    ));
    // the folded corner takes the note's stroke colour
    let mut fvars = Vec::new();
    let fold_fill = match get(&all, "stroke").and_then(|v| single_term(v).map(|t| (t.clone(), v.span))) {
        Some((t, sp)) => color_css(&t, &mut fvars, sp)?,
        None => {
            use_var(&mut fvars, "stroke");
            "var(--lini-stroke)".to_string()
        }
    };
    for v in fvars {
        use_var(&mut out.vars, &v);
    }
    buf.push_str(&format!(
        "{}<g class=\"lini-node lini-path\" style=\"fill: {}; stroke: none; stroke-width: 0\" transform=\"translate(0,0)\">\n",
        ind(ci + 2),
        xml_escape(&fold_fill)
    ));
    buf.push_str(&format!(
        "{}<path d=\"M {} {} L {} {} L {} {} Z\"/>\n",
        ind(ci + 4),
        raw(hw - fold),
        raw(-hh),
        raw(hw),
        raw(-hh + fold),
        raw(hw - fold),
        raw(-hh + fold)
    ));
    buf.push_str(&format!("{}</g>\n", ind(ci + 2)));
    for &c in &ctx.nodes[i].children {
        crate::render::render_node(ctx, c, ci + 2, buf, out)?;
    }
    buf.push_str(&format!("{}</g>\n", ind(ci)));
    Ok(())
}

// A message's label in the link layer: `.lini-sequence-message`, centred
// on its anchor, lines stacked at 1.2 em.
pub fn message_label(lb: &Label) -> String {
    format!("      {}\n", text_elem("lini-sequence-message", lb.x, lb.y, &lb.text, 13.0, ""))
}

// A wavy wire along a rounded polyline: corners flattened into chords (nine
// a quarter turn), then the tapered sine of a straight wavy wire laid along
// the arc length, joined by cubics whose handles follow the offset curve.
pub fn wave_path_d(pts: &[(f64, f64)], radii: &[f64]) -> String {
    let unit = crate::markers::unit;
    let n = pts.len();
    let mut fl: Vec<(f64, f64)> = vec![pts[0]];
    for i in 1..n.saturating_sub(1) {
        let (p, c, q) = (pts[i - 1], pts[i], pts[i + 1]);
        let u0 = unit((c.0 - p.0, c.1 - p.1));
        let u1 = unit((q.0 - c.0, q.1 - c.1));
        let r = radii.get(i - 1).copied().unwrap_or(0.0);
        let a = (c.0 - u0.0 * r, c.1 - u0.1 * r);
        let b = (c.0 + u1.0 * r, c.1 + u1.1 * r);
        fl.push(a);
        if r > 0.0 {
            let cross = u0.0 * u1.1 - u0.1 * u1.0;
            let nrm = if cross > 0.0 { (-u0.1, u0.0) } else { (u0.1, -u0.0) };
            let ctr = (a.0 + nrm.0 * r, a.1 + nrm.1 * r);
            let a0 = (a.1 - ctr.1).atan2(a.0 - ctr.0);
            let a1 = (b.1 - ctr.1).atan2(b.0 - ctr.0);
            let mut da = a1 - a0;
            while da > std::f64::consts::PI {
                da -= 2.0 * std::f64::consts::PI;
            }
            while da < -std::f64::consts::PI {
                da += 2.0 * std::f64::consts::PI;
            }
            let k = ((da.abs() / (std::f64::consts::PI / 2.0)) * 9.0).round().max(1.0) as usize;
            for j in 1..=k {
                let t = a0 + da * j as f64 / k as f64;
                fl.push((ctr.0 + r * t.cos(), ctr.1 + r * t.sin()));
            }
        } else {
            fl.push(b);
        }
    }
    fl.push(pts[n - 1]);
    // zero-length runs carry no direction
    let mut segs: Vec<((f64, f64), (f64, f64), f64)> = Vec::new();
    for w in fl.windows(2) {
        let l = ((w[1].0 - w[0].0).powi(2) + (w[1].1 - w[0].1).powi(2)).sqrt();
        if l > 0.0 {
            segs.push((w[0], w[1], l));
        }
    }
    if segs.is_empty() {
        return format!("M {} {}", f4(pts[0].0), f4(pts[0].1));
    }
    let total: f64 = segs.iter().map(|s| s.2).sum();
    let at = |s: f64| -> ((f64, f64), (f64, f64)) {
        let mut acc = 0.0;
        for (k, &(a, b, l)) in segs.iter().enumerate() {
            if acc + l >= s - 1e-12 || k + 1 == segs.len() {
                let t = ((s - acc) / l).clamp(0.0, 1.0);
                let u = ((b.0 - a.0) / l, (b.1 - a.1) / l);
                return ((a.0 + (b.0 - a.0) * t, a.1 + (b.1 - a.1) * t), u);
            }
            acc += l;
        }
        (pts[0], (1.0, 0.0))
    };
    let amp = 1.4;
    let lam = 12.0;
    let ramp = 6.0;
    let cnt = ((total / 3.0).round() as usize).max(1);
    let _h = total / cnt as f64;
    let ss = |t: f64| {
        let t = t.clamp(0.0, 1.0);
        3.0 * t * t - 2.0 * t * t * t
    };
    let dss = |t: f64| if t <= 0.0 || t >= 1.0 { 0.0 } else { 6.0 * t - 6.0 * t * t };
    let w = 2.0 * std::f64::consts::PI / lam;
    // (point, unit tangent of the offset curve)
    let mut samples: Vec<((f64, f64), (f64, f64))> = Vec::new();
    for i in 0..=cnt {
        let x = total * i as f64 / cnt as f64;
        let e1 = ss(x / ramp);
        let e2 = ss((total - x) / ramp);
        let (e, de) = if e1 < e2 { (e1, dss(x / ramp) / ramp) } else { (e2, -dss((total - x) / ramp) / ramp) };
        let y = amp * e * (w * x).sin();
        let dy = amp * (de * (w * x).sin() + e * w * (w * x).cos());
        let (p, u) = at(x);
        let nr = (-u.1, u.0);
        let q = (p.0 + nr.0 * y, p.1 + nr.1 * y);
        let l = (1.0 + dy * dy).sqrt();
        let t = ((u.0 + nr.0 * dy) / l, (u.1 + nr.1 * dy) / l);
        samples.push((q, t));
    }
    let mut d = format!("M {} {}", f4(pts[0].0), f4(pts[0].1));
    for i in 0..cnt {
        let (qa, ta) = samples[i];
        let (qb, tb) = samples[i + 1];
        let ch = ((qb.0 - qa.0).powi(2) + (qb.1 - qa.1).powi(2)).sqrt() / 3.0;
        let c1 = (qa.0 + ta.0 * ch, qa.1 + ta.1 * ch);
        let c2 = (qb.0 - tb.0 * ch, qb.1 - tb.1 * ch);
        d.push_str(&format!(" C {} {} {} {} {} {}", f4(c1.0), f4(c1.1), f4(c2.0), f4(c2.1), f4(qb.0), f4(qb.1)));
    }
    d
}
