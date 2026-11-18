// Core lowering: every node onto its primitive with its type chain as
// `.lini-*` classes, labels into children, define bodies materialised per
// instance, link chains split into hops, labels into `[ ]` with `along:`, and
// bare endpoint names that resolve nowhere declared as boxes around the link.

use super::out::{Item, OLink, ONode, OText};
use super::syntax::{Decl, Define, Endpoint, Link, Node, Stmt, Text};

use crate::diag::{Diag, Span};
use crate::format::parse::render_number;
use crate::types;
use std::collections::{HashMap, HashSet};

// a link waiting for its endpoints to resolve (after the whole tree exists)
#[derive(Clone, Debug)]
#[allow(dead_code)]
pub struct Pending {
    // written straight in a drawing: endpoints name its geometry
    pub in_drawing: bool,
    pub groups: Vec<Vec<Ep>>,
    pub ops: Vec<String>,
    pub classes: Vec<String>,
    pub decls: Vec<Decl>,
    pub labels: Vec<Item>,
    pub span: Span,
    // statements written right after the link's own (before the endpoints
    // it declares after itself): the scene tree's later branch wires
    pub trail: Vec<Item>,
}

#[derive(Clone, Debug)]
pub enum Ep {
    // a path: its rendered text and the first name
    Path { text: String, name: String, bare: bool },
    // a capsule: declared as a node
    Capsule { text: String, node: ONode },
}

impl Ep {
    fn text(&self) -> &str {
        match self {
            Ep::Path { text, .. } | Ep::Capsule { text, .. } => text,
        }
    }
}

#[allow(dead_code)]
pub struct Cx<'a> {
    pub src: &'a str,
    pub defines: Vec<Define>,
    pub used: HashSet<String>,
    pub cap: usize,
    pub pendings: Vec<Pending>,
    // contextual rules the lowering asks for (".lini-sequence .lini-note")
    pub ctx_rules: HashSet<&'static str>,
    pub root_layout: String,
    // a mindmap at the root turns the scene into a bilateral tree
    pub root_mindmap: bool,
    // the nodes being lowered, outermost first
    pub stack: Vec<Frame>,
    pub page_depth: usize,
    // the root's explicit `unit:`
    pub root_unit: Option<String>,
    pub root_pages: bool,
    // the scene's density: px per mm
    pub density: f64,
    pub root_tree: Option<super::tree::TreeMode>,
    pub mindmap_used: bool,
    pub mindmap_levels: std::collections::BTreeSet<usize>,
    pub mindmap_hues: HashSet<String>,
    pub sch_counters: HashMap<(usize, String), usize>,
    pub root_sch: Option<super::schematic::Plan>,
    pub root_sch_links: usize,
    pub in_body: usize,
    pub in_labels: usize,
    pub page_tree: Option<(bool, String, bool)>,
    pub root_mindmap_dir: String,
    // the scene's first mindmap's routing, should the scene take it
    pub root_mindmap_routing: Option<String>,
    pub next_cid: usize,
    // the scene's own wall `thickness:`
    pub root_thickness: Option<String>,
    // the tree pass: a dry run that reports only tree errors
    pub tree_check: bool,
    // errors later passes report: density, then units
    pub density_err: Option<Diag>,
    pub unit_err: Option<Diag>,
}

pub struct Frame {
    pub chain: Vec<String>,
    // the explicit unit a drawing context hands to its descendants
    pub unit: Option<String>,
    // a floorplan's wall `thickness:`, handed down the same way
    pub thickness: Option<String>,
    // set on a tree container: how its topics lower
    pub tree: Option<super::tree::TreeMode>,
    // set on a schematic scope: its wiring plan, and links lowered so far
    pub sch: Option<super::schematic::Plan>,
    pub sch_links: usize,
    pub caps: usize,
    pub sch_explicit: bool,
    // a layout container (row, column, grid, table, or an inline layout)
    pub breaks: bool,
    // a node whose lowering lays its content out (a component, a symbol, a
    // tree): it bounds a plan's measures
    pub plan_breaks: bool,
    // a unique container id
    pub cid: usize,
    // a mindmap outside any tree, or a topic in one: (level, the direction
    // `side:` reads)
    pub bare: Option<(usize, String)>,
}

pub type R<T> = Result<T, Diag>;

pub fn err(msg: &str, span: Span) -> Diag {
    Diag::error("parse", msg, span)
}

// a placeholder for a link: the index into `Cx::pendings`
pub const PENDING_PRIM: &str = "\u{0}pending";

impl<'a> Cx<'a> {
    pub fn new(src: &'a str, defines: Vec<Define>) -> Self {
        Cx {
            src,
            defines,
            used: HashSet::new(),
            cap: 0,
            pendings: Vec::new(),
            ctx_rules: HashSet::new(),
            root_layout: "flow".to_string(),
            root_mindmap: false,
            stack: Vec::new(),
            page_depth: 0,
            root_unit: None,
            root_pages: false,
            density: 4.0,
            root_tree: None,
            mindmap_used: false,
            mindmap_levels: std::collections::BTreeSet::new(),
            mindmap_hues: HashSet::new(),
            sch_counters: HashMap::new(),
            root_sch: None,
            root_sch_links: 0,
            in_body: 0,
            in_labels: 0,
            page_tree: None,
            root_mindmap_dir: "bilateral".to_string(),
            root_mindmap_routing: None,
            next_cid: 0,
            root_thickness: None,
            tree_check: false,
            density_err: None,
            unit_err: None,
        }
    }

    pub fn define(&self, name: &str) -> Option<&Define> {
        self.defines.iter().find(|d| d.name == name)
    }

    // (primitive, chain most-derived first)
    pub fn chain(&self, name: &str) -> Option<(String, Vec<String>)> {
        let mut chain = Vec::new();
        let mut cur = name.to_string();
        for _ in 0..64 {
            if let Some(d) = self.define(&cur) {
                chain.push(cur.clone());
                cur = d.base.clone();
                continue;
            }
            let t = types::find(&cur)?;
            if t.name == "text" {
                return None;
            }
            chain.push(cur.clone());
            match t.base {
                Some(b) => cur = b.to_string(),
                None => return Some((t.prim.name().to_string(), chain)),
            }
        }
        None
    }

    pub fn mark(&mut self, name: &str) {
        self.used.insert(name.to_string());
    }

    // a node of a built-in type (or chrome class) with its chain classes
    pub fn typed(&mut self, ty: &str) -> ONode {
        let (prim, chain) = match super::registry::class_base(ty) {
            Some(base) => {
                let (p, mut c) = self.chain(base).unwrap_or_else(|| ("block".to_string(), vec![base.to_string()]));
                c.insert(0, ty.to_string());
                (p, c)
            }
            None => self.chain(ty).unwrap_or_else(|| ("block".to_string(), vec![ty.to_string()])),
        };
        let mut n = ONode::new(&prim);
        for t in &chain {
            self.used.insert(t.clone());
            n.classes.push(format!("lini-{}", t));
        }
        n
    }

    pub fn text_item(t: &str) -> Item {
        Item::Text(OText { text: t.to_string(), classes: vec![], decls: vec![] })
    }

    // ------------------------------------------------------------ statements
    pub fn stmts(&mut self, stmts: &[Stmt], out: &mut Vec<Item>) -> R<()> {
        let mode = match self.stack.last() {
            Some(f) => f.tree.clone(),
            None => self.root_tree.clone(),
        };
        match mode {
            Some(m) => self.tree_stmts(stmts, &m, out),
            None => self.stmts_plain(stmts, out),
        }
    }

    pub fn stmts_plain(&mut self, stmts: &[Stmt], out: &mut Vec<Item>) -> R<()> {
        for s in stmts {
            match s {
                Stmt::Node(n) => {
                    let o = self.node(n)?;
                    out.push(o);
                }
                Stmt::Text(t) => out.push(self.text(t)),
                Stmt::Link(_) if self.tree_check => {}
                Stmt::Link(l) => {
                    if self.in_sch_scope() {
                        self.sch_emit(l, out)?;
                        continue;
                    }
                    let p = self.link(l)?;
                    self.pendings.push(p);
                    let mut ph = ONode::new(PENDING_PRIM);
                    ph.id = Some((self.pendings.len() - 1).to_string());
                    out.push(Item::Node(ph));
                }
            }
        }
        Ok(())
    }

    // links directly inside a schematic scope
    pub fn in_sch_scope(&self) -> bool {
        match self.stack.last() {
            Some(f) => f.sch.is_some(),
            None => self.root_sch.is_some(),
        }
    }

    fn sch_emit(&mut self, l: &Link, out: &mut Vec<Item>) -> R<()> {
        let planned = {
            let (plan, k) = match self.stack.last_mut() {
                Some(f) => (f.sch.as_ref().unwrap(), &mut f.sch_links),
                None => (self.root_sch.as_ref().unwrap(), &mut self.root_sch_links),
            };
            let p = plan.links.get(*k).cloned().unwrap_or_default();
            *k += 1;
            p
        };
        let mut l2 = l.clone();
        if l.groups.len() == 1 {
            // the text became a net label
            l2.label = None;
        }
        let p = self.link(&l2)?;
        for nn in &planned.before {
            let mut it = self.node(nn)?;
            if let Item::Node(n) = &mut it {
                n.gen = true;
            }
            out.push(it);
        }
        // hops meeting at a term passed in place (a pin, a label) stay one chain
        let mut groups: Vec<(String, Vec<usize>)> = Vec::new();
        for (k, (a, b, op)) in planned.hops.iter().enumerate() {
            match groups.last_mut() {
                Some((head, ks)) if planned.hops[*ks.last().unwrap()].1 == *a => {
                    head.push_str(&format!(" {} {}", op, b));
                    ks.push(k);
                }
                _ => groups.push((format!("{} {} {}", a, op, b), vec![k])),
            }
        }
        for (head, ks) in groups {
            let mut labels = p.labels.clone();
            let mut decls = p.decls.clone();
            let extra: Vec<&String> = planned.extra.iter().filter(|(h, _)| ks.contains(h)).map(|(_, t)| t).collect();
            if !extra.is_empty() {
                for t in extra {
                    labels.push(Self::text_item(t));
                }
                decls.retain(|d| d.name != "along" || l.style.iter().any(|u| u.name == "along"));
                set_along(&mut decls, &labels, &l.style);
            }
            out.push(Item::Link(OLink { head, classes: p.classes.clone(), decls, labels }));
        }
        for nn in &planned.after {
            let mut it = self.node(nn)?;
            if let Item::Node(n) = &mut it {
                n.gen = true;
            }
            out.push(it);
        }
        Ok(())
    }

    pub fn text(&mut self, t: &Text) -> Item {
        Item::Text(OText { text: t.text.clone(), classes: t.classes.clone(), decls: t.style.clone() })
    }

    pub fn head_err(&self, n: &Node) -> Option<Diag> {
        let ty = n.ty.clone().unwrap_or_else(|| "box".to_string());
        if ty == "link" {
            let close = Span::new(n.head_span.end.saturating_sub(1), n.head_span.end);
            return Some(err("links are drawn by operators, not the '|link|' type", close));
        }
        if self.chain(&ty).is_none() {
            return Some(Diag::error("unknown-type", &format!("unknown type '{}'", ty), n.span));
        }
        if n.id.as_deref().map_or(false, |id| id.starts_with("lini-") && crate::scene::written_id(self.src, n.head_span, id)) {
            return Some(crate::scene::reserved_id(n.span));
        }
        None
    }

    pub fn node(&mut self, n: &Node) -> R<Item> {
        if !self.tree_check {
            if let Some(e) = self.head_err(n) {
                return Err(e);
            }
        }
        let ty = n.ty.clone().unwrap_or_else(|| "box".to_string());
        let (prim, chain) = match self.chain(&ty) {
            Some(c) => c,
            None => self.chain("box").unwrap(),
        };
        let mut o = ONode::new(&prim);
        o.id = n.id.clone();
        for t in &chain {
            self.used.insert(t.clone());
            o.classes.push(format!("lini-{}", t));
        }
        o.classes.extend(n.classes.iter().cloned());
        o.decls = n.style.clone();
        let is = |t: &str| chain.iter().any(|c| c == t);
        if is("chart") || is("pie") || is("sequence") {
            self.mark("line");
        }
        if is("mindmap") {
            self.mindmap_used = true;
        }
        if is("note") {
            self.ctx_rules.insert(".lini-sequence .lini-note");
            self.ctx_rules.insert(".lini-drawing .lini-note");
        }
        // the unit context
        let inherited = self.stack.last().map(|f| f.unit.clone()).unwrap_or_else(|| self.root_unit.clone());
        let context = is("drawing") || is("stack") || is("page");
        let own_unit = n.style.iter().rev().find(|d| d.name == "unit").and_then(|d| d.first().map(|s| s.to_string()));
        if context && self.in_labels == 0 && self.unit_err.is_none() {
            if let Some(d) = n.style.iter().rev().find(|d| d.name == "unit") {
                if !super::sheet::unit_ok(d) {
                    self.unit_err = Some(err("'unit' is px, mm, cm, m, or in", d.span));
                }
            }
        }
        let unit = if context { own_unit.clone().or(inherited.clone()) } else { inherited.clone() };
        let breaks = ["row", "column", "grid", "table", "chart", "pie", "sequence", "schematic"].iter().any(|t| is(t))
            || n.style.iter().any(|d| d.name == "direction" || d.name == "layout");
        let inherited_t = match self.stack.last() {
            Some(f) => f.thickness.clone(),
            None => self.root_thickness.clone(),
        };
        let thickness = if is("drawing") {
            n.style.iter().rev().find(|d| d.name == "thickness").and_then(thickness_of).or(inherited_t)
        } else {
            inherited_t
        };
        self.next_cid += 1;
        let cid = self.next_cid;
        self.stack.push(Frame {
            chain: chain.clone(),
            unit: unit.clone(),
            thickness,
            tree: None,
            sch: None,
            sch_links: 0,
            caps: 0,
            sch_explicit: false,
            breaks,
            plan_breaks: false,
            cid,
            bare: None,
        });
        let r = self.dispatch(n, o, &chain, unit);
        self.stack.pop();
        r.map(Item::Node)
    }

    // the chain of the node enclosing the one being lowered
    pub fn parent_is(&self, t: &str) -> bool {
        let k = self.stack.len();
        k >= 2 && self.stack[k - 2].chain.iter().any(|c| c == t)
    }

    fn dispatch(&mut self, n: &Node, o: ONode, chain: &[String], unit: Option<String>) -> R<ONode> {
        let is = |t: &str| chain.iter().any(|c| c == t);
        // a mindmap outside a tree lowers plainly, its topics with it (their
        // directions and sides still checked); any other topic needs a tree
        let parent_bare = match self.stack.len() {
            k if k >= 2 => self.stack[k - 2].bare.clone(),
            _ => None,
        };
        if is("mindmap") {
            let sem = match n.style.iter().rev().find(|d| d.name == "direction").and_then(|d| d.first().map(|s| s.to_string())) {
                Some(d) => super::tree::read_dir(self, Some(d), n.span)?,
                None => "bilateral".to_string(),
            };
            if let Some(f) = self.stack.last_mut() {
                f.bare = Some((0, sem));
            }
        } else if is("topic") {
            let (level, sem) = match parent_bare {
                Some((l, s)) => (l + 1, s),
                None if self.tree_check => {
                    return Err(err("'|topic|' builds a tree — it belongs in a 'layout: tree'", n.span))
                }
                None => (1, "bilateral".to_string()),
            };
            super::tree::check_side(self, n, &sem, level)?;
            if let Some(f) = self.stack.last_mut() {
                f.bare = Some((level, sem));
            }
        }
        let mut tree_decls: Option<(bool, String, bool)> = None;
        let mut hoisted = false;
        let mut routing: Option<String> = None;
        if let Some(explicit) = super::tree::container_kind(self, n) {
            let content = super::tree::tree_content(self, n);
            let kids = &content[..];
            let mindmaps = explicit && super::tree::has_mindmap(self, kids);
            let own_dir = n.style.iter().rev().find(|d| d.name == "direction").and_then(|d| d.first().map(|s| s.to_string()));
            if explicit {
                super::tree::check_roots(self, kids, n.span)?;
            }
            let dir = if explicit && !(mindmaps && own_dir.is_none()) {
                super::tree::read_dir(self, own_dir, n.span)?
            } else if explicit {
                // the first mindmap's direction goes to the container
                hoisted = true;
                match super::tree::mindmap_dir(self, kids) {
                    Some((d, sp)) => super::tree::read_dir(self, Some(d), sp)?,
                    None => "bilateral".to_string(),
                }
            } else if let Some(d) = n.style.iter().rev().find(|d| d.name == "direction").and_then(|d| d.first().map(|s| s.to_string())) {
                // the container's own direction rules (unchecked); the mindmap
                // keeps its own
                d
            } else if super::schematic::is_component(chain) {
                // a component stacks its content in a column
                "column".to_string()
            } else if is("page") {
                super::page::page_dir(n)
            } else {
                hoisted = true;
                match super::tree::mindmap_dir(self, kids) {
                    Some((d, sp)) => super::tree::read_dir(self, Some(d), sp)?,
                    None => "bilateral".to_string(),
                }
            };
            if !is("page") {
                tree_decls = Some((explicit, dir.clone(), mindmaps));
            } else {
                self.page_tree = Some((explicit, dir.clone(), mindmaps));
            }
            // `side:` reads the tree's own direction (a hoisted one aside)
            let sem = if !explicit {
                "bilateral".to_string()
            } else if hoisted {
                "column".to_string()
            } else {
                dir.clone()
            };
            // a mindmap's routing goes to a container without its own
            if !explicit && !n.style.iter().any(|d| d.name == "routing") {
                routing = super::tree::mindmap_routing(self, kids);
            }
            let mode = super::tree::TreeMode {
                mindmap: !explicit,
                dir,
                level: 0,
                side: None,
                hue: None,
                hoisted,
                sem,
                drop_routing: routing.is_some(),
            };
            if let Some(f) = self.stack.last_mut() {
                f.tree = Some(mode);
                f.plan_breaks = true;
            }
        }
        let is_page = is("page");
        let mut o = self.dispatch_family(n, o, chain)?;
        if let Some((_, e)) = self.stack.last().and_then(|f| f.sch.as_ref()).and_then(|p| p.error.as_ref()) {
            return Err(e.clone());
        }
        if is_page {
            return Ok(o);
        }
        // the family's own decls, then the tree's, then the drawing pass
        if self.in_drawing() {
            super::drawing::plane_chrome(&mut o, chain);
        }
        if let Some((explicit, dir, mindmaps)) = tree_decls {
            super::tree::container_decls(&mut o.decls, explicit, &dir, mindmaps, routing.as_deref());
        }
        if self.in_plan() {
            super::drawing::plan_decls(self, &mut o, chain);
        }
        if self.in_drawing() {
            super::drawing::chrome_after(self, &mut o, chain);
        }
        if (is("drawing") || is("stack")) && self.in_labels == 0 {
            let px = super::sheet::px_per(unit.as_deref(), self.density, !is("drawing"));
            o.decls.retain(|d| d.name != "px-per-unit");
            o.decls.push(Decl::val("px-per-unit", &px));
        }
        Ok(o)
    }

    fn dispatch_family(&mut self, n: &Node, mut o: ONode, chain: &[String]) -> R<ONode> {
        let is = |t: &str| chain.iter().any(|c| c == t);
        if is("page") {
            return super::page::page(self, n, o, chain);
        }
        if self.tree_check {
            return self.plain(n, o, chain);
        }
        // a schematic scope plans its wiring before its children lower; a
        // container inside a schematic wires the same way
        let (explicit_sch, keeps_wiring) = self.sch_kind(n, chain);
        let parent_sch = match self.stack.len() {
            0 | 1 => self.root_sch.is_some(),
            k => self.stack[k - 2].sch.is_some(),
        };
        // the content wired: the define bodies, then the children
        let (content, from_bodies) = self.content(n, chain);
        let inherited_sch = !explicit_sch && !content.is_empty() && parent_sch && keeps_wiring;
        if inherited_sch || explicit_sch {
            // every wire's operators before any endpoint resolves
            self.sch_ops(&content)?;
        }
        if inherited_sch {
            let plan = self.sch_plan(&content, false, from_bodies)?;
            if let Some(f) = self.stack.last_mut() {
                f.sch = Some(plan);
            }
        }
        if explicit_sch {
            if let Some(f) = self.stack.last_mut() {
                f.sch_explicit = true;
            }
            if !is("schematic") {
                // a scope of its own: the schematic spacing unless the type sets it
                let has = |name: &str| -> bool {
                    n.style.iter().any(|d| d.name == name)
                        || chain.iter().any(|t| {
                            self.define(t).map_or(false, |d| d.decls.iter().any(|d| d.name == name))
                                || (t != "block"
                                    && crate::types::find(t).map_or(false, |td| Decl::list(td.defaults).iter().any(|d| d.name == name)))
                        })
                };
                let mut pre = Vec::new();
                if !has("gap") {
                    pre.push(Decl::val("gap", "100"));
                }
                if !has("clearance") {
                    pre.push(Decl::val("clearance", "10"));
                }
                pre.extend(o.decls.drain(..));
                o.decls = pre;
            }
            let plan = self.sch_plan(&content, true, from_bodies)?;
            if let Some(f) = self.stack.last_mut() {
                f.sch = Some(plan);
            }
        }
        if super::schematic::is_part(chain)
            || ["component", "pin", "space", "label", "junction"].iter().any(|t| is(t))
        {
            self.mark("junction");
        }
        if super::schematic::is_part(chain) {
            return super::schematic::part(self, n, o, chain);
        }
        if super::schematic::is_component(chain) {
            return super::schematic::component(self, n, o, chain);
        }
        if super::schematic::is_label(chain) {
            return super::schematic::label(self, n, o, chain);
        }
        if is("table") {
            return super::table::lower(self, n, o, chain);
        }
        self.plain(n, o, chain)
    }

    // under a drawing or a stack, the nearest unit context (a page is one too)
    pub fn in_plan(&self) -> bool {
        let k = self.stack.len();
        for f in self.stack[..k.saturating_sub(1)].iter().rev() {
            if f.chain.iter().any(|c| c == "drawing" || c == "stack") {
                return true;
            }
            if f.breaks || f.plan_breaks || f.chain.iter().any(|c| c == "page") {
                return false;
            }
        }
        matches!(self.root_layout.as_str(), "drawing" | "floorplan")
    }

    // inside a drawing (or a drawing scene): the nearest context decides
    pub fn in_drawing(&self) -> bool {
        let k = self.stack.len();
        for f in self.stack[..k.saturating_sub(1)].iter().rev() {
            if f.chain.iter().any(|c| c == "drawing") {
                return true;
            }
            // a layout container lays its children out itself
            if f.breaks || f.chain.iter().any(|c| c == "stack") {
                return false;
            }
        }
        matches!(self.root_layout.as_str(), "drawing" | "floorplan")
    }

    // a node's statements: its define bodies (base first), then its
    // children; and how many came from the bodies
    pub fn content(&self, n: &Node, chain: &[String]) -> (Vec<Stmt>, usize) {
        let mut v: Vec<Stmt> = Vec::new();
        for t in chain.iter().rev() {
            if let Some(b) = self.define(t).and_then(|d| d.body.as_ref()) {
                v.extend(b.iter().cloned());
            }
        }
        let k = v.len();
        v.extend(n.children.iter().flatten().cloned());
        (v, k)
    }

    // define bodies, base first, lowered for this instance
    pub fn bodies(&mut self, chain: &[String]) -> R<Vec<Item>> {
        let mut out = Vec::new();
        if self.tree_check {
            return Ok(out);
        }
        for t in chain.iter().rev() {
            if let Some(d) = self.define(t) {
                if let Some(body) = d.body.clone() {
                    // a body's links never invent endpoints
                    self.in_body += 1;
                    let r = self.stmts(&body, &mut out);
                    self.in_body -= 1;
                    r?;
                }
            }
        }
        Ok(out)
    }

    pub fn is_group(chain: &[String]) -> bool {
        chain.iter().any(|c| c == "group") && !chain.iter().any(|c| c == "table")
    }

    pub fn caption(&mut self, label: &str) -> Item {
        let mut c = self.typed("caption");
        c.children.push(Self::text_item(label));
        Item::Node(c)
    }

    // the common lowering: label, define bodies, children
    pub fn plain(&mut self, n: &Node, mut o: ONode, chain: &[String]) -> R<ONode> {
        let label = n.label.as_ref().map(|l| l.trim().to_string()).filter(|l| !l.is_empty());
        let bodies = self.bodies(chain)?;
        let mut kids = Vec::new();
        if let Some(ch) = &n.children {
            self.stmts(ch, &mut kids)?;
        }
        let prim = o.prim.clone();
        let mut children = Vec::new();
        if Self::is_group(chain) {
            children.extend(bodies);
            if let Some(l) = &label {
                let c = if self.stack.last().map_or(false, |f| f.sch_explicit) {
                    let mut c = self.typed("sheet-caption");
                    c.children.push(Self::text_item(l));
                    Item::Node(c)
                } else {
                    self.caption(l)
                };
                children.push(c);
            }
        } else if chain.iter().any(|c| c == "drawing") {
            // a view's caption sits under it
            children.extend(bodies);
            if let Some(l) = &label {
                let mut f = self.typed("footnote");
                f.children.push(Self::text_item(l));
                children.push(Item::Node(f));
            } else if o.decls.iter().any(|d| d.name == "of") {
                let mut f = self.typed("footnote");
                f.decls.push(Decl::val("of-title", "view"));
                children.push(Item::Node(f));
            }
        } else {
            match prim.as_str() {
                "line" | "poly" | "path" | "image" => {
                    o.label = label.clone();
                    children.extend(bodies);
                }
                "icon" => {
                    if let Some(l) = &label {
                        if o.decls.iter().any(|d| d.name == "symbol") && !self.tree_check {
                            return Err(err("an icon's symbol is its label or 'symbol:', not both", n.span));
                        }
                        o.decls.push(Decl::new("symbol", l));
                    }
                    children.extend(bodies);
                }
                _ => {
                    if let Some(l) = &label {
                        o.text_label = Some((l.clone(), bodies.len()));
                    }
                    children.extend(bodies);
                }
            }
        }
        children.extend(kids);
        o.children = children;
        Ok(o)
    }

    // ----------------------------------------------------------------- links
    pub fn link(&mut self, l: &Link) -> R<Pending> {
        let mut groups = Vec::new();
        for g in &l.groups {
            let mut v = Vec::new();
            for ep in g {
                match ep {
                    Endpoint::Path { text, parts, .. } => {
                        v.push(Ep::Path { text: text.clone(), name: parts[0].clone(), bare: parts.len() == 1 });
                    }
                    Endpoint::Capsule { node, tail } => {
                        if let Some(e) = self.head_err(node) {
                            return Err(e);
                        }
                        let id = match &node.id {
                            Some(id) => id.clone(),
                            None => {
                                // capsules count per container
                                let c = match self.stack.last_mut() {
                                    Some(f) => &mut f.caps,
                                    None => &mut self.cap,
                                };
                                *c += 1;
                                format!("lini-cap-{}", c)
                            }
                        };
                        let mut n2 = node.clone();
                        n2.id = Some(id.clone());
                        let item = self.node(&n2)?;
                        let o = match item {
                            Item::Node(o) => o,
                            _ => unreachable!(),
                        };
                        v.push(Ep::Capsule { text: format!("{}{}", id, tail), node: o });
                    }
                    Endpoint::Text(_) => {}
                }
            }
            groups.push(v);
        }
        // labels: the inline one first, then the bracketed ones
        let mut labels = Vec::new();
        if let Some(t) = &l.label {
            labels.push(Self::text_item(t));
        }
        for s in &l.labels {
            match s {
                Stmt::Text(t) => labels.push(self.text(t)),
                Stmt::Node(n) => {
                    // annotation nodes are not laid out as scene nodes
                    self.in_labels += 1;
                    let r = self.node(n);
                    self.in_labels -= 1;
                    labels.push(r?)
                }
                Stmt::Link(_) => {}
            }
        }
        let mut decls = l.style.clone();
        set_along(&mut decls, &labels, &l.style);
        // a fragment's messages belong to the container around it
        let frag = |f: &&Frame| f.chain.iter().any(|c| matches!(c.as_str(), "loop" | "alt" | "opt" | "else"));
        let in_drawing = self.in_body > 0
            || match self.stack.iter().rev().find(|f| !frag(f)) {
                Some(f) => f.chain.iter().any(|c| c == "drawing"),
                None => matches!(self.root_layout.as_str(), "drawing" | "floorplan"),
            };
        Ok(Pending {
            in_drawing,
            groups,
            ops: l.ops.clone(),
            classes: l.classes.clone(),
            decls,
            labels,
            span: l.span,
            trail: Vec::new(),
        })
    }
}

// `|link|` names no type: checked first, define bodies and link labels too
pub fn link_check(defines: &[Define], stmts: &[Stmt]) -> R<()> {
    for d in defines {
        if let Some(b) = &d.body {
            link_stmts(b)?;
        }
    }
    link_stmts(stmts)
}

fn link_stmts(stmts: &[Stmt]) -> R<()> {
    for s in stmts {
        match s {
            Stmt::Node(n) => link_node(n)?,
            Stmt::Link(l) => {
                for g in &l.groups {
                    for ep in g {
                        if let Endpoint::Capsule { node, .. } = ep {
                            link_node(node)?;
                        }
                    }
                }
                link_stmts(&l.labels)?;
            }
            Stmt::Text(_) => {}
        }
    }
    Ok(())
}

fn link_node(n: &Node) -> R<()> {
    if n.ty.as_deref() == Some("link") {
        let close = Span::new(n.head_span.end.saturating_sub(1), n.head_span.end);
        return Err(err("links are drawn by operators, not the '|link|' type", close));
    }
    match &n.children {
        Some(ch) => link_stmts(ch),
        None => Ok(()),
    }
}

// a wall thickness: one positive number
pub fn thickness_of(d: &Decl) -> Option<String> {
    match d.groups.as_slice() {
        [g] if g.len() == 1 => match g[0].parse::<f64>() {
            Ok(v) if v > 0.0 => Some(render_number(v)),
            _ => None,
        },
        _ => None,
    }
}

// px-per-unit as written: a few decimals at most
pub fn round_px(v: f64) -> f64 {
    // the product as computed: no rounding
    v
}

// labels spread along the link unless the author placed them
pub fn set_along(decls: &mut Vec<Decl>, labels: &[Item], user: &[Decl]) {
    let ntext = labels.iter().filter(|i| matches!(i, Item::Text(_))).count();
    if ntext > 0 && !user.iter().any(|d| d.name == "along") {
        let vals: Vec<Vec<String>> =
            (1..=ntext).map(|k| vec![render_number(round2(k as f64 / (ntext + 1) as f64))]).collect();
        decls.insert(0, Decl::groups("along", vals));
    }
}

pub fn round2(v: f64) -> f64 {
    (v * 100.0).round() / 100.0
}

// ------------------------------------------------------------- resolution
// A link sees the ids in its container's subtree: through anonymous nodes,
// up to (and including) each node with an id. Capsules declared by other
// links count as declared.
fn visible(items: &[Item], name: &str, pendings: &[Pending]) -> bool {
    for it in items {
        if let Item::Node(n) = it {
            if n.prim == PENDING_PRIM {
                if let Some(Ok(k)) = n.id.as_ref().map(|s| s.parse::<usize>()) {
                    for g in &pendings[k].groups {
                        for ep in g {
                            if let Ep::Capsule { node, .. } = ep {
                                if node.id.as_deref() == Some(name) {
                                    return true;
                                }
                            }
                        }
                    }
                }
                continue;
            }
            match &n.id {
                Some(id) => {
                    if id == name {
                        return true;
                    }
                }
                None => {
                    if visible(&n.children, name, pendings) {
                        return true;
                    }
                }
            }
        }
    }
    false
}

// sequence fragments: their messages resolve in the diagram around them
fn is_fragment(n: &ONode) -> bool {
    n.classes.iter().any(|c| matches!(c.as_str(), "lini-loop" | "lini-alt" | "lini-opt" | "lini-else"))
}

impl<'a> Cx<'a> {
    // replace the link placeholders, declaring unresolved bare endpoints
    pub fn resolve(&mut self, items: Vec<Item>) -> Vec<Item> {
        let mut items = items;
        self.resolve_list(&mut items);
        items
    }

    // containers resolve inside out: a link sees the endpoints its
    // anonymous descendants declared
    fn resolve_list(&mut self, items: &mut Vec<Item>) {
        for it in items.iter_mut() {
            if let Item::Node(n) = it {
                if n.prim == PENDING_PRIM {
                    continue;
                }
                let mut kids = std::mem::take(&mut n.children);
                if is_fragment(n) {
                    self.resolve_nested(&mut kids);
                } else {
                    self.resolve_list(&mut kids);
                }
                n.children = kids;
            }
        }
        self.resolve_own(items);
    }

    // the scopes inside a fragment (its own messages wait for the diagram)
    fn resolve_nested(&mut self, kids: &mut Vec<Item>) {
        for it in kids.iter_mut() {
            if let Item::Node(n) = it {
                if n.prim == PENDING_PRIM {
                    continue;
                }
                let mut inner = std::mem::take(&mut n.children);
                if is_fragment(n) {
                    self.resolve_nested(&mut inner);
                } else {
                    self.resolve_list(&mut inner);
                }
                n.children = inner;
            }
        }
    }

    fn resolve_own(&mut self, items: &mut Vec<Item>) {
        // the container's own links first
        let mut i = 0;
        while i < items.len() {
            let pending = match &items[i] {
                Item::Node(n) if n.prim == PENDING_PRIM => n.id.as_ref().and_then(|s| s.parse::<usize>().ok()),
                _ => None,
            };
            if let Some(idx) = pending {
                let p = self.pendings[idx].clone();
                let mut out = Vec::new();
                self.emit_link(p, items, &[], &mut out, None);
                let k = out.len();
                items.splice(i..i + 1, out);
                i += k;
                continue;
            }
            i += 1;
        }
        // then the fragments: a sequence fragment's messages belong to the
        // diagram around it, and so do the endpoints they declare (they see
        // what the diagram sees: inside an id'd fragment, nothing)
        let mut i = 0;
        while i < items.len() {
            if !matches!(&items[i], Item::Node(n) if is_fragment(n)) {
                i += 1;
                continue;
            }
            let scope = items.clone();
            let mut kids = match &mut items[i] {
                Item::Node(n) => std::mem::take(&mut n.children),
                _ => unreachable!(),
            };
            let mut hoist: Vec<(usize, Item)> = Vec::new();
            self.resolve_fragment(&mut kids, &scope, &mut hoist);
            if let Item::Node(n) = &mut items[i] {
                n.children = kids;
            }
            // the declared endpoints follow the fragment, in the order of the
            // messages that declared them
            hoist.sort_by_key(|(k, _)| *k);
            let decl: Vec<Item> = hoist.into_iter().map(|(_, it)| it).collect();
            let n = decl.len();
            items.splice(i + 1..i + 1, decl);
            i += 1 + n;
        }
    }

    // a fragment's own messages first, then its nested fragments'; each
    // declaration keyed by the message that made it
    fn resolve_fragment(&mut self, kids: &mut Vec<Item>, outer: &[Item], hoist: &mut Vec<(usize, Item)>) {
        let mut i = 0;
        while i < kids.len() {
            let pending = match &kids[i] {
                Item::Node(n) if n.prim == PENDING_PRIM => n.id.as_ref().and_then(|s| s.parse::<usize>().ok()),
                _ => None,
            };
            match pending {
                Some(idx) => {
                    let p = self.pendings[idx].clone();
                    let mut out = Vec::new();
                    let seen: Vec<Item> = hoist.iter().map(|(_, it)| it.clone()).collect();
                    let mut made = Vec::new();
                    self.emit_link(p, outer, &seen, &mut out, Some(&mut made));
                    hoist.extend(made.into_iter().map(|it| (idx, it)));
                    let k = out.len();
                    kids.splice(i..i + 1, out);
                    i += k;
                }
                None => i += 1,
            }
        }
        for it in kids.iter_mut() {
            if let Item::Node(n) = it {
                if is_fragment(n) {
                    let mut inner = std::mem::take(&mut n.children);
                    self.resolve_fragment(&mut inner, outer, hoist);
                    n.children = inner;
                }
            }
        }
    }

    pub fn auto_box(&mut self, name: &str) -> ONode {
        let mut b = self.typed("box");
        b.id = Some(name.to_string());
        b.children.push(Self::text_item(name));
        b.gen = true;
        b
    }

    fn emit_link(
        &mut self,
        p: Pending,
        scope: &[Item],
        also: &[Item],
        out: &mut Vec<Item>,
        hoist: Option<&mut Vec<Item>>,
    ) {
        let mut before = Vec::new();
        let mut after = Vec::new();
        let mut made: Vec<String> = Vec::new();
        let mut first = true;
        for g in &p.groups {
            for ep in g {
                let decl = match ep {
                    Ep::Path { name, bare, .. } => {
                        let known = made.contains(name)
                            || visible(scope, name, &self.pendings)
                            || visible(also, name, &self.pendings);
                        if *bare && !known && !p.in_drawing {
                            made.push(name.clone());
                            Some(self.auto_box(name))
                        } else {
                            None
                        }
                    }
                    Ep::Capsule { node, .. } => {
                        let mut n = node.clone();
                        n.gen = true;
                        Some(n)
                    }
                };
                if let Some(d) = decl {
                    if first {
                        before.push(Item::Node(d));
                    } else {
                        after.push(Item::Node(d));
                    }
                }
                first = false;
            }
        }
        let mut hoist = hoist;
        match hoist.as_mut() {
            Some(h) => h.extend(before),
            None => out.extend(before),
        }
        let gtext = |g: &Vec<Ep>| g.iter().map(|e| e.text().to_string()).collect::<Vec<_>>().join(" & ");
        let link_op = p.ops.first().map_or(false, |o| !(o.starts_with('(') || o == "||"));
        if p.groups.len() < 2 || !link_op {
            // one-ended, or a dimension / flush chain: one statement
            let mut head = gtext(&p.groups[0]);
            for (k, op) in p.ops.iter().enumerate() {
                head.push(' ');
                head.push_str(op);
                if let Some(g) = p.groups.get(k + 1) {
                    head.push(' ');
                    head.push_str(&gtext(g));
                }
            }
            out.push(Item::Link(OLink { head, classes: p.classes.clone(), decls: p.decls.clone(), labels: p.labels.clone() }));
        } else {
            for k in 0..p.groups.len() - 1 {
                let op = p.ops.get(k).cloned().unwrap_or_default();
                let head = format!("{} {} {}", gtext(&p.groups[k]), op, gtext(&p.groups[k + 1]));
                out.push(Item::Link(OLink {
                    head,
                    classes: p.classes.clone(),
                    decls: p.decls.clone(),
                    labels: p.labels.clone(),
                }));
            }
        }
        out.extend(p.trail.iter().cloned());
        // hoisted declarations keep the order they were made in
        match hoist {
            Some(h) => h.extend(after),
            None => out.extend(after),
        }
    }
}
