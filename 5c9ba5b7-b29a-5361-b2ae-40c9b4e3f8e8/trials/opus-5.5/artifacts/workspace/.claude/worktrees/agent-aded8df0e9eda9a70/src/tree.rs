// Trees and mindmaps on the compile side (`layout: tree`, `|mindmap|`).
//
// Building lowers a tree the way `lini desugar` prints it: a tree container
// (an explicit `layout: tree`, a node holding a |mindmap|, or the scene)
// gives its topics ids (`lini-topic-N` by sibling position), `.lini-level-N`
// depth classes, a side on a bilateral tree's first level and a palette hue
// per mindmap branch, and records the parent→child branch wires as links
// with anchored sides, in the statement order the desugared document has.
//
// Layout: levels stack along the growth axis in bands every topic of a
// level shares (both halves of a bilateral tree included), each topic
// centred in its band; across it siblings pack `gap`'s second value apart,
// a parent centred over its children's block. The container stacks the
// tree after its other content (that content reads backwards from the
// tree), the stack `gap`'s second value apart.
//
// Wires: natural curves run side centre to side centre; an orthogonal fan
// shares one trunk port on the parent, which slides off the centre only to
// let a child that faces the parent drop straight. A Z wire crosses midway
// along its channel (to its child, or to a sibling it passes over, a
// clearance off each); crossings on one side of the trunk keep a clearance
// apart, the outermost nearest the parent. Topics' absolute places run from
// their tree's root (`abs_center`), which the general router reads too.

use crate::ast::{Decl, NodeStmt, Stmt, Term};
use crate::compile::Ctx;
use crate::route::{Rect, Side};
use crate::scene::{Builder, Link, Node};
use std::cell::RefCell;
use std::collections::{BTreeSet, HashMap};

pub static HUES: &[&str] = &["rose", "orange", "amber", "lime", "green", "teal", "sky", "blue", "purple"];

// How the children of a tree container or topic lower.
#[derive(Clone, Debug)]
struct Mode {
    // hues on the first level
    mindmap: bool,
    dir: String,
    // the level the children take
    level: usize,
    side: Option<String>,
    hue: Option<String>,
    tree: usize,
    // the children sit inside a mindmap (its descendant rules reach them)
    in_mm: bool,
}

struct Frame {
    node: usize,
    mode: Mode,
    // tree nodes met so far among the children, and their count
    k: usize,
    n: usize,
    // the first mindmap's direction went to the container
    hoisted: bool,
    // so did its routing
    drop_routing: bool,
}

#[derive(Clone, Debug, Default)]
pub struct TreeBox {
    pub dir: String,
    pub roots: Vec<usize>,
}

#[derive(Clone, Debug)]
pub struct Topic {
    pub tree: usize,
    // the tree's root topic
    pub root: usize,
    pub level: usize,
    pub side: Option<String>,
    pub hue: Option<String>,
    pub mindmap: bool,
    pub kids: Vec<usize>,
}

// A topic whose branch wires wait for the end of the document.
struct Pending {
    topic: usize,
}

#[derive(Default)]
struct State {
    frames: Vec<Frame>,
    boxes: Vec<TreeBox>,
    box_of: HashMap<usize, usize>,
    topics: HashMap<usize, Topic>,
    // link index → the wire's hue (None: a plain branch wire)
    branches: HashMap<usize, Option<String>>,
    deferred: Vec<Pending>,
    mindmap_used: bool,
    levels: BTreeSet<usize>,
    hues: BTreeSet<String>,
    // each laid-out topic's centre relative to its tree's root
    at: HashMap<usize, (f64, f64)>,
    // topics given a generated id
    generated: std::collections::HashSet<usize>,
    // the scene tree's content size (its frame is built round it)
    root_content: Option<(f64, f64)>,
}

thread_local! {
    static ST: RefCell<State> = RefCell::new(State::default());
}

// ------------------------------------------------------------ queries

// The scene tree's frame: its content padded twice over, each side by its
// own padding (x0, y0, w, h).
pub fn root_frame(pad: [f64; 4]) -> Option<(f64, f64, f64, f64)> {
    let (cw, ch) = ST.with(|s| s.borrow().root_content)?;
    let w = cw + 2.0 * (pad[1] + pad[3]);
    let h = ch + 2.0 * (pad[0] + pad[2]);
    Some((-w / 2.0 - (pad[3] - pad[1]), -h / 2.0 - (pad[0] - pad[2]), w, h))
}

pub fn is_container(i: usize) -> bool {
    ST.with(|s| s.borrow().box_of.contains_key(&i))
}

pub fn tree_box(i: usize) -> Option<TreeBox> {
    ST.with(|s| {
        let s = s.borrow();
        s.box_of.get(&i).map(|&b| s.boxes[b].clone())
    })
}

pub fn topic(i: usize) -> Option<Topic> {
    ST.with(|s| s.borrow().topics.get(&i).cloned())
}

pub fn is_topic_node(i: usize) -> bool {
    ST.with(|s| s.borrow().topics.contains_key(&i))
}

// A child topic: laid out beside its parent topic, not inside it.
pub fn detached(ctx: &Ctx, i: usize) -> bool {
    match ctx.nodes[i].parent {
        Some(p) => ST.with(|s| {
            let s = s.borrow();
            s.topics.contains_key(&i) && s.topics.contains_key(&p)
        }),
        None => false,
    }
}

// a topic whose id the tree made (`lini-topic-N`)
pub fn generated_id(i: usize) -> bool {
    ST.with(|s| s.borrow().generated.contains(&i))
}

pub fn is_branch(li: usize) -> bool {
    ST.with(|s| s.borrow().branches.contains_key(&li))
}

pub fn branch_hue(li: usize) -> Option<String> {
    ST.with(|s| s.borrow().branches.get(&li).cloned().flatten())
}

// ------------------------------------------------------------ building

fn chain_has(chain: &[String], t: &str) -> bool {
    chain.iter().any(|c| c == t)
}

fn stmt_chain(b: &Builder, ns: &NodeStmt) -> Vec<String> {
    let t = ns.type_name.clone().unwrap_or_else(|| "box".to_string());
    crate::scene::type_chain(b.sheet, &t).map(|x| x.1).unwrap_or_default()
}

fn own(decls: Option<&Vec<Decl>>, name: &str) -> Option<String> {
    let ds = decls?;
    let d = ds.iter().rev().find(|d| d.name == name)?;
    match d.value.groups.first().and_then(|g| g.first()) {
        Some(Term::Ident(s, _)) => Some(s.clone()),
        Some(Term::Str(s, _)) => Some(s.clone()),
        Some(Term::Num(_, s, _)) => Some(s.clone()),
        _ => None,
    }
}

fn is_mindmap_stmt(b: &Builder, s: &Stmt) -> bool {
    match s {
        Stmt::Node(n) => chain_has(&stmt_chain(b, n), "mindmap"),
        _ => false,
    }
}

fn tree_stmt(b: &Builder, s: &Stmt, mode: &Mode) -> bool {
    match s {
        Stmt::Node(n) => {
            let c = stmt_chain(b, n);
            if mode.level == 0 && mode.mindmap {
                chain_has(&c, "mindmap")
            } else {
                chain_has(&c, "topic")
            }
        }
        _ => false,
    }
}

// the direction the first mindmap among `stmts` hands its container
fn mindmap_dir(b: &Builder, stmts: &[Stmt]) -> Option<String> {
    for s in stmts {
        if let Stmt::Node(n) = s {
            if chain_has(&stmt_chain(b, n), "mindmap") {
                return own(n.style.as_ref(), "direction");
            }
        }
    }
    None
}

// the routing the first mindmap among `stmts` hands its container
fn mindmap_routing(b: &Builder, stmts: &[Stmt]) -> Option<String> {
    for s in stmts {
        if let Stmt::Node(n) = s {
            if chain_has(&stmt_chain(b, n), "mindmap") {
                return own(n.style.as_ref(), "routing");
            }
        }
    }
    None
}

fn decl(name: &str, value: &str) -> Decl {
    decls(&format!("{}: {};", name, value)).into_iter().next().unwrap()
}

thread_local! {
    static PARSED: RefCell<HashMap<String, Vec<Decl>>> = RefCell::new(HashMap::new());
}

// Declarations from text (parsed once per text).
fn decls(text: &str) -> Vec<Decl> {
    PARSED.with(|p| {
        if let Some(v) = p.borrow().get(text) {
            return v.clone();
        }
        let leaked: &'static str = Box::leak(text.to_string().into_boxed_str());
        let v = crate::style::parse_decls(leaked);
        p.borrow_mut().insert(text.to_string(), v.clone());
        v
    })
}

// the decls a tree container gains
fn container_decls(inline: &mut Vec<Decl>, explicit: bool, dir: &str, mindmaps: bool, routing: Option<&str>) {
    if !explicit || mindmaps {
        for (k, v) in [("layout", "tree"), ("direction", dir), ("routing", routing.unwrap_or("natural"))] {
            if !inline.iter().any(|d| d.name == k) {
                inline.push(decl(k, v));
            }
        }
    }
    if !inline.iter().any(|d| d.name == "gap") {
        inline.push(decl("gap", "64 48"));
    }
}

fn new_box(st: &mut State, node: usize, dir: &str) -> usize {
    st.boxes.push(TreeBox { dir: dir.to_string(), roots: vec![] });
    let b = st.boxes.len() - 1;
    st.box_of.insert(node, b);
    b
}

// The scene as a tree: `layout: tree` at the root, or mindmaps at the top.
pub fn begin(b: &mut Builder, stmts: &[Stmt]) {
    ST.with(|s| *s.borrow_mut() = State::default());
    let root = &b.sheet.root;
    let layout = root.iter().rev().find(|d| d.name == "layout").and_then(|d| crate::style::ident_of(&d.value).map(|s| s.to_string()));
    let own_dir = root.iter().rev().find(|d| d.name == "direction").and_then(|d| crate::style::ident_of(&d.value).map(|s| s.to_string()));
    let has_mm = stmts.iter().any(|s| is_mindmap_stmt(b, s));
    let (explicit, dir, hoisted, mindmap_root) = if layout.as_deref() == Some("tree") {
        let hoisted = has_mm && own_dir.is_none();
        let dir = if hoisted {
            mindmap_dir(b, stmts).unwrap_or_else(|| "bilateral".into())
        } else {
            own_dir.clone().unwrap_or_else(|| "column".into())
        };
        (true, dir, hoisted, has_mm)
    } else if layout.is_none() && has_mm {
        let hoisted = own_dir.is_none();
        let dir = match &own_dir {
            Some(d) => d.clone(),
            None => mindmap_dir(b, stmts).unwrap_or_else(|| "bilateral".into()),
        };
        (false, dir, hoisted, true)
    } else {
        return;
    };
    // the root's decls: a tree's gap, a mindmap's direction and routing
    let user = |k: &str| root.iter().any(|d| d.name == k);
    let routing = if mindmap_root && !explicit && !user("routing") { mindmap_routing(b, stmts) } else { None };
    let mut fix: Vec<Decl> = vec![decl("layout", "tree")];
    if !user("gap") {
        fix.push(decl("gap", "64 48"));
    }
    if mindmap_root {
        if !user("direction") {
            fix.push(decl("direction", &dir));
        }
        if !user("routing") {
            fix.push(decl("routing", routing.as_deref().unwrap_or("natural")));
        }
    }
    for d in fix {
        let inl = &mut b.nodes[0].inline;
        match inl.iter_mut().find(|e| e.name == d.name) {
            Some(e) => *e = d,
            None => inl.push(d),
        }
    }
    ST.with(|s| {
        let mut st = s.borrow_mut();
        let tree = new_box(&mut st, 0, &dir);
        let mode = Mode { mindmap: !explicit, dir, level: 0, side: None, hue: None, tree, in_mm: false };
        let n = stmts.iter().filter(|s| tree_stmt(b, s, &mode)).count();
        st.frames.push(Frame { node: 0, mode, k: 0, n, hoisted, drop_routing: routing.is_some() });
    });
}

// Before a node is added: a tree node takes its id and classes; a tree
// container opens a frame for its children.
pub fn enter(b: &Builder, ns: &NodeStmt, chain: &[String], parent: usize, n: &mut Node) {
    let i = b.nodes.len();
    let is_mm = chain_has(chain, "mindmap");
    ST.with(|s| {
        let mut st = s.borrow_mut();
        if is_mm {
            st.mindmap_used = true;
        }
        let top = st.frames.len().checked_sub(1).filter(|&f| st.frames[f].node == parent);
        if let Some(fi) = top {
            let mode = st.frames[fi].mode.clone();
            let tree_node = if mode.level == 0 && mode.mindmap { is_mm } else { chain_has(chain, "topic") };
            if tree_node {
                let k = st.frames[fi].k;
                st.frames[fi].k += 1;
                let half = (st.frames[fi].n + 1) / 2;
                let level = mode.level;
                let side = if mode.dir == "bilateral" {
                    if level == 1 {
                        Some(own(ns.style.as_ref(), "side").unwrap_or_else(|| if k < half { "right".into() } else { "left".into() }))
                    } else {
                        mode.side.clone()
                    }
                } else {
                    None
                };
                let hue = if mode.mindmap {
                    if level == 1 {
                        Some(HUES[k % HUES.len()].to_string())
                    } else {
                        mode.hue.clone()
                    }
                } else {
                    None
                };
                let drop_dir = st.frames[fi].hoisted && level == 0 && is_mm;
                if drop_dir {
                    st.frames[fi].hoisted = false;
                    n.inline.retain(|d| d.name != "direction");
                }
                if st.frames[fi].drop_routing && level == 0 && is_mm {
                    st.frames[fi].drop_routing = false;
                    n.inline.retain(|d| d.name != "routing");
                }
                let mindmap = mode.mindmap || is_mm;
                if n.id.is_none() {
                    n.id = Some(format!("lini-topic-{}", k + 1));
                    st.generated.insert(i);
                }
                if level == 1 && mode.dir == "bilateral" {
                    if let Some(sd) = &side {
                        n.tags.push(format!("side-{}", sd));
                    }
                    n.inline.retain(|d| d.name != "side");
                }
                n.tags.push(format!("level-{}", level));
                if level >= 1 {
                    st.levels.insert(level);
                }
                if mindmap {
                    if let Some(h) = &hue {
                        n.tags.push(format!("hue-{}", h));
                        st.hues.insert(h.clone());
                    }
                }
                if mode.in_mm {
                    n.tags.push("@mm".to_string());
                }
                let child = Mode {
                    mindmap,
                    dir: mode.dir.clone(),
                    level: level + 1,
                    side: side.clone(),
                    hue: hue.clone(),
                    tree: mode.tree,
                    in_mm: mode.in_mm || is_mm,
                };
                let cn = ns.children.as_ref().map_or(0, |c| c.iter().filter(|s| tree_stmt(b, s, &child)).count());
                let root = if level == 0 { i } else { st.topics.get(&parent).map_or(i, |t| t.root) };
                st.topics.insert(i, Topic { tree: mode.tree, root, level, side, hue, mindmap, kids: vec![] });
                if level == 0 {
                    let tb = mode.tree;
                    st.boxes[tb].roots.push(i);
                } else if let Some(t) = st.topics.get_mut(&parent) {
                    t.kids.push(i);
                }
                st.frames.push(Frame { node: i, mode: child, k: 0, n: cn, hoisted: false, drop_routing: false });
                return;
            }
        }
        // a tree container?
        if crate::table::is_table(chain) || chain_has(chain, "page") {
            return;
        }
        let layout = own(ns.style.as_ref(), "layout");
        let kids: &[Stmt] = ns.children.as_deref().unwrap_or(&[]);
        let explicit = match layout.as_deref() {
            Some("tree") => true,
            Some(_) => return,
            None => {
                if is_mm || !kids.iter().any(|s| is_mindmap_stmt(b, s)) {
                    return;
                }
                false
            }
        };
        let mindmaps = explicit && kids.iter().any(|s| is_mindmap_stmt(b, s));
        let own_dir = own(ns.style.as_ref(), "direction");
        let mut hoisted = false;
        let dir = if explicit && !(mindmaps && own_dir.is_none()) {
            own_dir.clone().unwrap_or_else(|| "column".into())
        } else if explicit {
            hoisted = true;
            mindmap_dir(b, kids).unwrap_or_else(|| "bilateral".into())
        } else if let Some(d) = own_dir.clone() {
            d
        } else {
            hoisted = true;
            mindmap_dir(b, kids).unwrap_or_else(|| "bilateral".into())
        };
        // a mindmap's routing goes to a container without its own
        let routing = if !explicit && own(ns.style.as_ref(), "routing").is_none() { mindmap_routing(b, kids) } else { None };
        container_decls(&mut n.inline, explicit, &dir, mindmaps, routing.as_deref());
        let tree = new_box(&mut st, i, &dir);
        let mode = Mode { mindmap: !explicit, dir, level: 0, side: None, hue: None, tree, in_mm: false };
        let cn = kids.iter().filter(|s| tree_stmt(b, s, &mode)).count();
        st.frames.push(Frame { node: i, mode, k: 0, n: cn, hoisted, drop_routing: routing.is_some() });
    });
}

// After a node's content is built: close its frame; a topic's branch wires
// follow it in its parent (the scene's own wait for the end).
pub fn leave(b: &mut Builder, i: usize) {
    let closing = ST.with(|s| {
        let mut st = s.borrow_mut();
        if st.frames.last().map(|f| f.node) == Some(i) {
            st.frames.pop();
            true
        } else {
            false
        }
    });
    if !closing || !is_topic_node(i) {
        return;
    }
    let parent = b.nodes[i].parent.unwrap_or(0);
    if parent == 0 {
        ST.with(|s| s.borrow_mut().deferred.push(Pending { topic: i }));
        return;
    }
    emit_branches(b, i);
}

// The scene's own branch wires close the document.
pub fn finish(b: &mut Builder) {
    let pend = ST.with(|s| {
        let mut st = s.borrow_mut();
        st.frames.clear();
        std::mem::take(&mut st.deferred)
    });
    for p in pend {
        emit_branches(b, p.topic);
    }
}

fn emit_branches(b: &mut Builder, i: usize) {
    let Some(t) = topic(i) else { return };
    if t.kids.is_empty() {
        return;
    }
    let dir = ST.with(|s| s.borrow().boxes[t.tree].dir.clone());
    let kid_info: Vec<(usize, Option<String>, Option<String>)> = t
        .kids
        .iter()
        .map(|&k| {
            let kt = topic(k).unwrap();
            (k, kt.side, kt.hue)
        })
        .collect();
    // statements: (from side, to side, members, hue class)
    let mut stmts: Vec<(&str, &str, Vec<usize>, Option<String>)> = Vec::new();
    let all: Vec<usize> = t.kids.clone();
    if t.mindmap && dir != "bilateral" {
        let (f, to) = if dir == "row" { ("right", "left") } else { ("bottom", "top") };
        if t.level == 0 {
            for (k, _, h) in &kid_info {
                stmts.push((f, to, vec![*k], h.clone()));
            }
        } else {
            stmts.push((f, to, all, t.hue.clone()));
        }
    } else {
        match dir.as_str() {
            "column" => stmts.push(("bottom", "top", all, None)),
            "row" => stmts.push(("right", "left", all, None)),
            _ => {
                if t.level == 0 {
                    if t.mindmap {
                        for (k, sd, h) in &kid_info {
                            if sd.as_deref() == Some("left") {
                                stmts.push(("left", "right", vec![*k], h.clone()));
                            } else {
                                stmts.push(("right", "left", vec![*k], h.clone()));
                            }
                        }
                    } else {
                        let right: Vec<usize> = kid_info.iter().filter(|x| x.1.as_deref() != Some("left")).map(|x| x.0).collect();
                        let left: Vec<usize> = kid_info.iter().filter(|x| x.1.as_deref() == Some("left")).map(|x| x.0).collect();
                        if !right.is_empty() {
                            stmts.push(("right", "left", right, None));
                        }
                        if !left.is_empty() {
                            stmts.push(("left", "right", left, None));
                        }
                    }
                } else if t.side.as_deref() == Some("left") {
                    stmts.push(("left", "right", all, if t.mindmap { t.hue.clone() } else { None }));
                } else {
                    stmts.push(("right", "left", all, if t.mindmap { t.hue.clone() } else { None }));
                }
            }
        }
    }
    let container = b.nodes[i].parent.unwrap_or(0);
    // the scene's own wires close the document; the rest follow their topic
    let span = if container == 0 { crate::diag::Span::new(b.src.len(), b.src.len()) } else { b.nodes[i].span };
    for (f, to, members, hue) in stmts {
        let idx = b.stmt_counter;
        b.stmt_counter += 1;
        for m in members {
            let li = b.links.len();
            b.links.push(Link {
                from: i,
                to: m,
                op: "-".to_string(),
                label: None,
                labels: vec![],
                classes: vec![],
                style: vec![],
                from_anchor: Some(f.to_string()),
                to_anchor: Some(to.to_string()),
                from_index: None,
                to_index: None,
                span,
                stmt_index: idx,
                container,
            });
            ST.with(|s| s.borrow_mut().branches.insert(li, hue.clone()));
        }
    }
}

// ------------------------------------------------------------ errors

// The tree errors (`lini desugar`'s tree pass), reported before the scene
// resolves.
pub fn check(src: &str) -> Result<(), crate::diag::Diag> {
    if !(src.contains("topic") || src.contains("mindmap") || src.contains("tree")) {
        return Ok(());
    }
    match crate::desugar::tree_errors(src) {
        // the tree pass's own errors resolve; a head error keeps its family
        Some(e) if e.family == "parse" => Err(crate::diag::Diag::error("resolve", &e.message, e.span)),
        Some(e) => Err(e),
        None => Ok(()),
    }
}

// ------------------------------------------------------------ styles

fn level_size(l: usize) -> &'static str {
    match l {
        1 => "15",
        2 => "14",
        _ => "13",
    }
}

// The mindmap's descendant rules a node wears (`.lini-mindmap .lini-topic`,
// `.lini-mindmap .lini-level-N`, `.lini-mindmap .lini-hue-X`): above the
// type rules, below the classes.
pub fn context_decls(n: &Node) -> Vec<Decl> {
    if !n.tags.iter().any(|t| t == "@mm") {
        return vec![];
    }
    let mut out = Vec::new();
    if n.is("topic") {
        out.extend(decls("max-width: 160; font-weight: medium;"));
    }
    for t in &n.tags {
        if let Some(l) = t.strip_prefix("level-") {
            if let Ok(l) = l.parse::<usize>() {
                if l >= 1 {
                    out.push(decl("font-size", level_size(l)));
                }
            }
        }
    }
    for t in &n.tags {
        if let Some(h) = t.strip_prefix("hue-") {
            out.extend(decls(&format!("fill: --{h}-wash; stroke: --{h}-deep; color: --{h}-ink;", h = h)));
        }
    }
    out
}

// The stylesheet's mindmap rules (after the class rules).
pub fn css_rules(ctx: &Ctx, vars: &mut Vec<String>) -> Vec<String> {
    let (used, levels, hues) = ST.with(|s| {
        let s = s.borrow();
        (s.mindmap_used, s.levels.clone(), s.hues.clone())
    });
    if !used {
        return vec![];
    }
    let mut out = Vec::new();
    let rule = |sel: &str, text: &str, vars: &mut Vec<String>| -> Option<String> {
        let props: Vec<(String, crate::ast::Value)> = decls(text).into_iter().map(|d| (d.name, d.value)).collect();
        let d = crate::render::css_decls(ctx, &props, vars, 2.0, false).ok()?;
        if d.is_empty() {
            return None;
        }
        let body: Vec<String> = d.iter().map(|(k, v)| format!("{}: {}", k, v)).collect();
        Some(format!("{} {{ {}; }}", sel, body.join("; ")))
    };
    out.extend(rule(".lini-mindmap .lini-topic", "max-width: 160; font-weight: medium;", vars));
    for l in levels {
        out.extend(rule(&format!(".lini-mindmap .lini-level-{}", l), &format!("font-size: {};", level_size(l)), vars));
    }
    for h in HUES {
        if hues.contains(*h) {
            out.extend(rule(&format!(".lini-mindmap .lini-hue-{}", h), &format!("fill: --{h}-wash; stroke: --{h}-deep; color: --{h}-ink;", h = h), vars));
            out.extend(rule(&format!(".lini-links .lini-hue-{}", h), &format!("stroke: --{}-deep;", h), vars));
        }
    }
    out
}

// Children in paint order: a tree container paints its tree first, a topic
// its card before its child topics.
pub fn paint_order(ctx: &Ctx, i: usize, order: Vec<usize>) -> Vec<usize> {
    if let Some(bx) = tree_box(i) {
        let mut v: Vec<usize> = order.iter().cloned().filter(|c| bx.roots.contains(c)).collect();
        v.extend(order.iter().cloned().filter(|c| !bx.roots.contains(c)));
        return v;
    }
    if is_topic_node(i) {
        let mut v: Vec<usize> = order.iter().cloned().filter(|&c| !detached(ctx, c)).collect();
        v.extend(order.iter().cloned().filter(|&c| detached(ctx, c)));
        return v;
    }
    order
}

// ------------------------------------------------------------ layout

fn outer(ctx: &Ctx, i: usize) -> (f64, f64) {
    crate::layout::outer(ctx, i)
}

// A topic's card: its own content in its own flow, the child topics aside.
fn measure_card(ctx: &mut Ctx, t: usize) {
    let all = ctx.nodes[t].children.clone();
    let card: Vec<usize> = all.iter().cloned().filter(|&c| !detached(ctx, c)).collect();
    ctx.nodes[t].children = card;
    crate::layout::measure_flow(ctx, t, None);
    ctx.nodes[t].children = all;
    for k in topic(t).map(|x| x.kids).unwrap_or_default() {
        measure_card(ctx, k);
    }
}

// Lay a tree out around its root; returns the bounding box of every topic's
// outer box relative to the root's centre.
fn layout_tree(ctx: &mut Ctx, root: usize, dir: &str, lg: f64, sg: f64) -> [f64; 4] {
    measure_card(ctx, root);
    let col = dir == "column";
    let main_of = |ctx: &Ctx, t: usize| -> f64 {
        let (w, h) = outer(ctx, t);
        if col {
            h
        } else {
            w
        }
    };
    let cross_of = |ctx: &Ctx, t: usize| -> f64 {
        let (w, h) = outer(ctx, t);
        if col {
            w
        } else {
            h
        }
    };
    // depth bands (shared by both halves of a bilateral tree)
    let mut band: Vec<f64> = Vec::new();
    let mut stack = vec![(root, 0usize)];
    while let Some((t, d)) = stack.pop() {
        if band.len() <= d {
            band.resize(d + 1, 0.0);
        }
        band[d] = band[d].max(main_of(ctx, t));
        for k in topic(t).map(|x| x.kids).unwrap_or_default() {
            stack.push((k, d + 1));
        }
    }
    // each level's place along the growth axis, from the root
    let mut pos = vec![0.0; band.len()];
    for d in 1..band.len() {
        pos[d] = pos[d - 1] + band[d - 1] / 2.0 + lg + band[d] / 2.0;
    }
    // cross extents, bottom-up
    fn ext(ctx: &Ctx, t: usize, sg: f64, cross_of: &dyn Fn(&Ctx, usize) -> f64, memo: &mut HashMap<usize, f64>, bil_root: Option<usize>) -> f64 {
        let kids = topic(t).map(|x| x.kids).unwrap_or_default();
        let own = cross_of(ctx, t);
        let e = if kids.is_empty() {
            own
        } else {
            let mut groups: Vec<Vec<usize>> = vec![];
            let bil = bil_root == Some(t);
            if bil {
                let (r, l): (Vec<usize>, Vec<usize>) = kids.iter().partition(|&&k| topic(k).and_then(|x| x.side).as_deref() != Some("left"));
                groups.push(r);
                groups.push(l);
            } else {
                groups.push(kids.clone());
            }
            let mut m = own;
            for g in &groups {
                if g.is_empty() {
                    continue;
                }
                let mut s = 0.0;
                for (j, &k) in g.iter().enumerate() {
                    if j > 0 {
                        s += sg;
                    }
                    s += ext(ctx, k, sg, cross_of, memo, bil_root);
                }
                m = m.max(s);
            }
            m
        };
        memo.insert(t, e);
        e
    }
    let mut memo: HashMap<usize, f64> = HashMap::new();
    let bil_root = if dir == "bilateral" { Some(root) } else { None };
    ext(ctx, root, sg, &cross_of, &mut memo, bil_root);
    // place: positions relative to the root, each topic's transform the
    // difference from its parent's
    let mut bb = [f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY];
    let mut q: Vec<(usize, usize, f64, f64, f64)> = vec![(root, 0, 0.0, 0.0, 1.0)]; // (topic, depth, main, cross, sign)
    let mut at: HashMap<usize, (f64, f64)> = HashMap::new();
    while let Some((t, d, am, ac, sgn)) = q.pop() {
        let (w, h) = outer(ctx, t);
        let (ax, ay) = if col { (ac, am) } else { (am, ac) };
        at.insert(t, (ax, ay));
        bb[0] = bb[0].min(ax - w / 2.0);
        bb[1] = bb[1].min(ay - h / 2.0);
        bb[2] = bb[2].max(ax + w / 2.0);
        bb[3] = bb[3].max(ay + h / 2.0);
        let kids = topic(t).map(|x| x.kids).unwrap_or_default();
        if kids.is_empty() {
            continue;
        }
        let bil = d == 0 && bil_root.is_some();
        let mut groups: Vec<(Vec<usize>, f64)> = vec![];
        if bil {
            let (r, l): (Vec<usize>, Vec<usize>) = kids.iter().partition(|&&k| topic(k).and_then(|x| x.side).as_deref() != Some("left"));
            groups.push((r, 1.0));
            groups.push((l, -1.0));
        } else {
            groups.push((kids.clone(), sgn));
        }
        for (g, gs) in groups {
            if g.is_empty() {
                continue;
            }
            let total: f64 = g.iter().map(|k| memo[k]).sum::<f64>() + sg * (g.len() as f64 - 1.0);
            let mut cur = -total / 2.0;
            for &k in &g {
                let e = memo[&k];
                let c = ac + (cur + e / 2.0);
                cur += e + sg;
                let m = gs * pos[d + 1];
                let (kx, ky) = if col { (c, m) } else { (m, c) };
                ctx.nodes[k].x = kx - ax;
                ctx.nodes[k].y = ky - ay;
                q.push((k, d + 1, m, c, gs));
            }
        }
    }
    ST.with(|s| s.borrow_mut().at.extend(at.into_iter()));
    bb
}

// A tree container: the tree, then its other content stacked before it.
pub fn measure(ctx: &mut Ctx, i: usize, _avail: Option<f64>) {
    let bx = match tree_box(i) {
        Some(b) => b,
        None => return,
    };
    let c = ctx.comp[i].clone();
    let pad = c.padding;
    let (lg, sg) = c.gap;
    let children = ctx.nodes[i].children.clone();
    let mut others: Vec<usize> = Vec::new();
    let mut pinned: Vec<usize> = Vec::new();
    for &ch in &children {
        if bx.roots.contains(&ch) {
            continue;
        }
        if ctx.comp[ch].pin.is_some() {
            pinned.push(ch);
        } else {
            others.push(ch);
        }
    }
    // the layout reads the container's direction as cascaded (a |row|'s own)
    let dir = match ctx.nodes[i].props.get("direction").and_then(crate::style::ident_of) {
        Some(d @ ("row" | "column" | "bilateral")) => d.to_string(),
        _ => "column".to_string(),
    };
    let tree = bx.roots.first().map(|&r| (r, layout_tree(ctx, r, &dir, lg, sg)));
    // further roots: measured, left at the first root's place
    for &r in bx.roots.iter().skip(1) {
        measure_card(ctx, r);
    }
    for &ch in &others {
        crate::layout::measure(ctx, ch, None);
    }
    for &ch in &pinned {
        crate::layout::measure(ctx, ch, None);
    }
    let col = dir != "row";
    // stack items, last first: (node or tree, w, h)
    let mut items: Vec<(Option<usize>, f64, f64)> = Vec::new();
    if let Some((_, bb)) = &tree {
        items.push((None, bb[2] - bb[0], bb[3] - bb[1]));
    }
    for &o in &others {
        let (w, h) = outer(ctx, o);
        items.push((Some(o), w, h));
    }
    items.reverse();
    let n = items.len();
    let mut main = 0.0;
    let mut cross: f64 = 0.0;
    for (k, it) in items.iter().enumerate() {
        if k > 0 {
            main += sg;
        }
        if col {
            main += it.2;
            cross = cross.max(it.1);
        } else {
            main += it.1;
            cross = cross.max(it.2);
        }
    }
    let (cw, chh) = if col { (cross, main) } else { (main, cross) };
    // the stack's places, around its own centre
    let mut placed: Vec<(Option<usize>, f64, f64)> = Vec::new();
    let mut cur = -main / 2.0;
    for it in &items {
        let size = if col { it.2 } else { it.1 };
        let mid = cur + size / 2.0;
        cur += size + sg;
        let (x, y) = if col { (0.0, mid) } else { (mid, 0.0) };
        placed.push((it.0, x, y));
    }
    // pinned content sits on the tree's box (a caption over it), the
    // container growing to hold it
    let mut cb = [-cw / 2.0, -chh / 2.0, cw / 2.0, chh / 2.0];
    let mut pins: Vec<(usize, f64, f64)> = Vec::new();
    if let Some(tb) = tree.as_ref().map(|(_, bb)| (bb[2] - bb[0], bb[3] - bb[1])) {
        let (_, tx, ty) = placed.iter().find(|p| p.0.is_none()).cloned().unwrap();
        let tbox = [tx - tb.0 / 2.0, ty - tb.1 / 2.0, tx + tb.0 / 2.0, ty + tb.1 / 2.0];
        for &p in &pinned {
            let (pw, ph) = outer(ctx, p);
            let words = ctx.comp[p].pin.clone().unwrap_or_default();
            let mut x = (tbox[0] + tbox[2]) / 2.0;
            let mut y = (tbox[1] + tbox[3]) / 2.0;
            for w in words.split_whitespace() {
                match w {
                    "top" => y = tbox[1] + ph / 2.0,
                    "bottom" => y = tbox[3] - ph / 2.0,
                    "left" => x = tbox[0] + pw / 2.0,
                    "right" => x = tbox[2] - pw / 2.0,
                    _ => {}
                }
            }
            let (dx, dy) = ctx.comp[p].translate;
            cb[0] = cb[0].min(x + dx - pw / 2.0);
            cb[1] = cb[1].min(y + dy - ph / 2.0);
            cb[2] = cb[2].max(x + dx + pw / 2.0);
            cb[3] = cb[3].max(y + dy + ph / 2.0);
            pins.push((p, x, y));
        }
    }
    let grown = cb != [-cw / 2.0, -chh / 2.0, cw / 2.0, chh / 2.0];
    let (cw, chh) = if grown { (cb[2] - cb[0], cb[3] - cb[1]) } else { (cw, chh) };
    if i == 0 {
        ST.with(|s| s.borrow_mut().root_content = Some((cw, chh)));
    }
    let mut w = cw + pad[1] + pad[3];
    let mut h = chh + pad[0] + pad[2];
    if let Some(fw) = c.width {
        w = if n == 0 { fw } else { w.max(fw) };
    }
    if let Some(fh) = c.height {
        h = if n == 0 { fh } else { h.max(fh) };
    }
    ctx.nodes[i].w = w;
    ctx.nodes[i].h = h;
    // the content sits centred in the box, whatever the padding's balance
    let (ox, oy) = if grown { (-(cb[0] + cb[2]) / 2.0, -(cb[1] + cb[3]) / 2.0) } else { (0.0, 0.0) };
    for (it, x, y) in placed {
        let (x, y) = (ox + x, oy + y);
        match it {
            Some(o) => {
                ctx.nodes[o].x = x;
                ctx.nodes[o].y = y;
            }
            None => {
                let (r, bb) = tree.as_ref().map(|t| (t.0, t.1)).unwrap();
                ctx.nodes[r].x = x - (bb[0] + bb[2]) / 2.0;
                ctx.nodes[r].y = y - (bb[1] + bb[3]) / 2.0;
            }
        }
    }
    if let Some((r, _)) = &tree {
        let (rx, ry) = (ctx.nodes[*r].x, ctx.nodes[*r].y);
        for &o in bx.roots.iter().skip(1) {
            ctx.nodes[o].x = rx;
            ctx.nodes[o].y = ry;
        }
    }
    for (p, x, y) in pins {
        ctx.nodes[p].x = ox + x;
        ctx.nodes[p].y = oy + y;
    }
    if tree.is_none() {
        for &p in &pinned {
            crate::layout::place_pinned(ctx, i, p);
        }
    }
}

// ------------------------------------------------------------ wires

pub struct Wire {
    pub pts: Vec<(f64, f64)>,
    pub curve: Option<[(f64, f64); 4]>,
    pub radii: Vec<f64>,
    pub sa: Side,
    pub sb: Side,
}

// A topic's absolute centre: its tree root's place plus where the tree put
// it (content inside a topic adds its own offsets to that).
pub fn abs_center(ctx: &Ctx, i: usize) -> Option<(f64, f64)> {
    let (mut dx, mut dy) = (0.0, 0.0);
    let mut cur = i;
    loop {
        if let Some(t) = topic(cur) {
            let (tx, ty) = ST.with(|s| s.borrow().at.get(&cur).cloned())?;
            let (rx, ry) = crate::links::chain_center(ctx, t.root);
            let (cx, cy) = (rx + tx, ry + ty);
            return Some(if cur == i { (cx, cy) } else { (cx + dx, cy + dy) });
        }
        dx += ctx.nodes[cur].x + ctx.comp[cur].translate.0;
        dy += ctx.nodes[cur].y + ctx.comp[cur].translate.1;
        cur = ctx.nodes[cur].parent?;
        if cur == 0 {
            return None;
        }
    }
}

// A topic's absolute box for its wires.
fn wire_rect(ctx: &Ctx, i: usize) -> Rect {
    crate::links::abs_rect(ctx, i)
}

// Corner radii: end legs may be used whole, inner legs are shared by their
// two corners in proportion to what they want.
fn cap_radii(pts: &[(f64, f64)], want: f64) -> Vec<f64> {
    let n = pts.len();
    if n < 3 {
        return vec![];
    }
    let seg = |i: usize| (pts[i + 1].0 - pts[i].0).abs() + (pts[i + 1].1 - pts[i].1).abs();
    let share = |len: f64, mine: f64, other: f64| if mine + other > len && mine + other > 0.0 { len * (mine / (mine + other)) } else { mine };
    let mut out = Vec::new();
    for c in 1..n - 1 {
        let before = if c == 1 { seg(0) } else { share(seg(c - 1), want, want) };
        let after = if c == n - 2 { seg(c) } else { share(seg(c), want, want) };
        out.push(want.min(before).min(after).max(0.0));
    }
    out
}

fn side_of(s: &Option<String>) -> Side {
    s.as_deref().and_then(Side::parse).unwrap_or(Side::Bottom)
}

// The branch wires of one statement (a fan from one parent), in order:
// (link index, wire).
pub fn route_fan(ctx: &Ctx, rects: &[Rect], members: &[usize], natural: bool, k: f64, radius: f64) -> Vec<(usize, Wire)> {
    let mut out = Vec::new();
    if members.is_empty() {
        return out;
    }
    let _ = rects;
    let mut rects: HashMap<usize, Rect> = HashMap::new();
    let l0 = &ctx.links[members[0]];
    rects.insert(l0.from, wire_rect(ctx, l0.from));
    for &li in members {
        let to = ctx.links[li].to;
        rects.insert(to, wire_rect(ctx, to));
    }
    let sa = side_of(&l0.from_anchor);
    let sb = side_of(&l0.to_anchor);
    let p = rects[&l0.from];
    if natural {
        for &li in members {
            let c = rects[&ctx.links[li].to];
            let s = crate::route::side_point(&p, sa, 0.0);
            let e = crate::route::side_point(&c, sb, 0.0);
            let ds = sa.dir();
            let de = sb.dir();
            let s1 = (s.0 + ds.0 * 2.0, s.1 + ds.1 * 2.0);
            let e1 = (e.0 + de.0 * 2.0, e.1 + de.1 * 2.0);
            let dist = ((e1.0 - s1.0).powi(2) + (e1.1 - s1.1).powi(2)).sqrt();
            let along = if sa.horizontal() { (e1.1 - s1.1).abs() } else { (e1.0 - s1.0).abs() };
            let h = (dist / 2.0).min(along.max(dist / 4.0));
            let c1 = (s1.0 + ds.0 * h, s1.1 + ds.1 * h);
            let c2 = (e1.0 + de.0 * h, e1.1 + de.1 * h);
            out.push((li, Wire { pts: vec![s, e], curve: Some([s1, c1, c2, e1]), radii: vec![], sa, sb }));
        }
        return out;
    }
    // orthogonal: (cross, main) coordinates, main pointing out of the parent
    let vertical = sa.horizontal();
    let cross_span = |r: &Rect| if vertical { (r.x0, r.x1, r.cx()) } else { (r.y0, r.y1, r.cy()) };
    let edge = |r: &Rect, s: Side| match s {
        Side::Top => r.y0,
        Side::Bottom => r.y1,
        Side::Left => r.x0,
        Side::Right => r.x1,
    };
    let (p0, p1, pc) = cross_span(&p);
    let usable = |a: f64, b: f64, c: f64| -> (f64, f64) {
        let lo = a + k;
        let hi = b - k;
        if lo > hi {
            (c, c)
        } else {
            (lo, hi)
        }
    };
    let (pu0, pu1) = usable(p0, p1, pc);
    let ph = (p1 - p0) / 2.0;
    // the trunk port: the first member's wanted line, slid for a later
    // member that can drop straight
    let mut t = pc;
    let mut iv = (pu0, pu1);
    let mut straight: Vec<bool> = vec![false; members.len()];
    for (j, &li) in members.iter().enumerate() {
        let c = rects[&ctx.links[li].to];
        let (c0, c1, cc) = cross_span(&c);
        let ch = (c1 - c0) / 2.0;
        let (cu0, cu1) = usable(c0, c1, cc);
        let faces = (cc - pc).abs() < ph.min(ch) + k;
        let lo = cu0.max(iv.0);
        let hi = cu1.min(iv.1);
        if faces && lo <= hi + 1e-9 {
            if j == 0 {
                let mid = (pc + cc) / 2.0;
                t = mid.max(lo).min(hi);
            } else {
                t = t.max(lo).min(hi);
            }
            iv = (lo, hi);
            straight[j] = true;

        }
    }
    let at = |cr: f64, mn: f64| if vertical { (cr, mn) } else { (mn, cr) };
    let pe = edge(&p, sa);
    let dir = if sa.dir().0 + sa.dir().1 > 0.0 { 1.0 } else { -1.0 };
    // each Z wire's crossing runs midway along its channel: from the parent
    // to its child, or to a sibling it passes over, a clearance off each
    let kids: Vec<Rect> = members.iter().map(|&li| rects[&ctx.links[li].to]).collect();
    // (member, cross offset from the trunk, channel midpoint, preferred depth, channel width, channel ends)
    let mut zs: Vec<(usize, f64, f64, f64, f64, f64, f64)> = Vec::new();
    for (j, c) in kids.iter().enumerate() {
        let (_, _, cc) = cross_span(c);
        if straight[j] || (cc - t).abs() < 1e-9 {
            continue;
        }
        let (s0, s1) = (cc.min(t), cc.max(t));
        let mut far = edge(c, sb);
        for (o, r) in kids.iter().enumerate() {
            if o == j {
                continue;
            }
            let (o0, o1, _) = cross_span(r);
            if o0 - k < s1 - 1e-9 && o1 + k > s0 + 1e-9 {
                let e = edge(r, sb);
                if (e - far) * dir < 0.0 {
                    far = e;
                }
            }
        }
        let lo = pe + k * dir;
        let hi = far - k * dir;
        let mid = (lo + hi) / 2.0;
        zs.push((j, cc - t, mid, (mid - pe) * dir, (hi - lo) * dir, lo, hi));
    }
    // crossings on one side of the trunk share the channel: outermost
    // nearest the parent, a clearance apart (closer when the channel is
    // narrow), each pooled run centred on what its members prefer
    let mut place: HashMap<usize, f64> = HashMap::new();
    for side in [-1.0, 1.0] {
        let mut g: Vec<&(usize, f64, f64, f64, f64, f64, f64)> = zs.iter().filter(|z| z.1 * side > 0.0).collect();
        if g.is_empty() {
            continue;
        }
        // the group's channel: its first wire's
        let first = **g.iter().min_by_key(|z| z.0).unwrap();
        g.sort_by(|a, b| b.1.abs().partial_cmp(&a.1.abs()).unwrap_or(std::cmp::Ordering::Equal));
        let cnt = g.len();
        let width = first.4;
        let pitch = if cnt <= 1 { 0.0 } else { k.min((width / (cnt as f64 - 1.0)).max(0.0)) };
        // pool adjacent violators over q = preferred depth − rank·pitch
        let mut blocks: Vec<(f64, usize, usize)> = Vec::new(); // (sum, count, first rank)
        for (r, z) in g.iter().enumerate() {
            blocks.push((z.3 - r as f64 * pitch, 1, r));
            while blocks.len() >= 2 {
                let (s1, n1, _) = blocks[blocks.len() - 1];
                let (s0, n0, r0) = blocks[blocks.len() - 2];
                if s0 / n0 as f64 > s1 / n1 as f64 + 1e-12 {
                    blocks.pop();
                    blocks.pop();
                    blocks.push((s0 + s1, n0 + n1, r0));
                } else {
                    break;
                }
            }
        }
        for (_, n, r0) in blocks {
            let members_b: Vec<&(usize, f64, f64, f64, f64, f64, f64)> = g[r0..r0 + n].to_vec();
            let same = members_b.iter().all(|z| z.2 == members_b[0].2);
            let mut got: Vec<(usize, f64)> = Vec::new();
            let m = if same { members_b[0].2 } else { members_b.iter().map(|z| z.2).sum::<f64>() / n as f64 };
            let centre = (n as f64 - 1.0) / 2.0;
            for (i, z) in members_b.iter().enumerate() {
                got.push((z.0, m + (i as f64 - centre) * pitch * dir));
            }
            // a pooled run slides to keep each crossing in its channel
            if n >= 2 {
                let depth = |p: f64| (p - pe) * dir;
                let mut up = f64::NEG_INFINITY;
                let mut down = f64::INFINITY;
                for (z, gp) in members_b.iter().zip(got.iter()) {
                    up = up.max(depth(z.5) - depth(gp.1));
                    down = down.min(depth(z.6) - depth(gp.1));
                }
                let shift = if up > 1e-9 { up } else if down < -1e-9 { down } else { 0.0 };
                if shift != 0.0 {
                    for e in got.iter_mut() {
                        e.1 += shift * dir;
                    }
                }
            }
            place.extend(got);
        }
    }
    for (j, &li) in members.iter().enumerate() {
        let c = kids[j];
        let (_, _, cc) = cross_span(&c);
        let ce = edge(&c, sb);
        let Some(&mid) = place.get(&j) else {
            let x = if straight[j] { t } else { cc };
            out.push((li, Wire { pts: vec![at(x, pe), at(x, ce)], curve: None, radii: vec![], sa, sb }));
            continue;
        };
        let pts = vec![at(t, pe), at(t, mid), at(cc, mid), at(cc, ce)];
        let radii = cap_radii(&pts, radius);
        out.push((li, Wire { pts, curve: None, radii, sa, sb }));
    }
    out
}
