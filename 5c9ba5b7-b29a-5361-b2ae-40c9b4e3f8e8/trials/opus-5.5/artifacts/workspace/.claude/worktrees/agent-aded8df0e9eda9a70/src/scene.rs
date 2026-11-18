// The scene: the stylesheet model plus the node tree built from statements.

use crate::ast::*;
use crate::diag::{Diag, Span};
use crate::eval::{Env, Func, EV};
use crate::types::{self, Prim};
use std::collections::HashMap;

#[derive(Clone, Debug)]
pub struct DefineModel {
    pub name: String,
    pub base: String,
    pub decls: Vec<Decl>,
    pub body: Option<Vec<Stmt>>,
    pub span: Span,
}

#[derive(Clone, Debug)]
pub struct ClassRule {
    pub name: String,
    pub decls: Vec<Decl>,
    pub span: Span,
    pub used: bool,
}

#[derive(Default)]
pub struct SheetModel {
    pub root: Vec<Decl>,
    pub vars: Vec<Decl>,
    pub env: Env,
    pub type_rules: Vec<(String, Vec<Decl>)>,
    pub defines: Vec<DefineModel>,
    pub classes: Vec<ClassRule>,
    pub id_rules: Vec<(String, Vec<Decl>)>,
    pub link_rules: Vec<Decl>,
    pub scoped_link_rules: Vec<(String, Vec<Decl>)>,
}

impl SheetModel {
    pub fn define(&self, name: &str) -> Option<&DefineModel> {
        self.defines.iter().find(|d| d.name == name)
    }
    pub fn type_rule(&self, name: &str) -> Vec<&Decl> {
        let mut out = Vec::new();
        for (n, ds) in &self.type_rules {
            if n == name {
                out.extend(ds.iter());
            }
        }
        out
    }
    pub fn class(&self, name: &str) -> Option<&ClassRule> {
        self.classes.iter().find(|c| c.name == name)
    }
}

#[derive(Clone, Debug)]
pub struct Node {
    pub prim: Prim,
    pub chain: Vec<String>, // most-derived first
    pub id: Option<String>,
    pub auto: bool,
    pub classes: Vec<String>,
    pub inline: Vec<Decl>,
    pub text: Option<String>,
    pub children: Vec<usize>,
    pub parent: Option<usize>,
    pub span: Span,
    pub props: HashMap<String, Value>,
    pub inline_props: HashMap<String, Value>,
    // layout results: rect size and centre relative to the parent's centre
    pub w: f64,
    pub h: f64,
    pub x: f64,
    pub y: f64,
    pub lines: Vec<String>,
    pub gutters: Vec<(f64, f64, f64, f64)>,
    pub scope: usize,
    pub geo: Option<Geo>,
    pub geo_off: (f64, f64),
    // the statement's label ("…" after the head), whatever the primitive
    pub label: Option<String>,
    // generated classes (`level-1`, `hue-rose` …, src/tree.rs); '@' ones are markers
    pub tags: Vec<String>,
}

#[derive(Clone, Debug)]
pub enum Geo {
    Points(Vec<(f64, f64)>),
    Path(String),
}

impl Node {
    pub fn new(prim: Prim, chain: Vec<String>, span: Span) -> Node {
        Node {
            prim,
            chain,
            id: None,
            auto: false,
            classes: vec![],
            inline: vec![],
            text: None,
            children: vec![],
            parent: None,
            span,
            props: HashMap::new(),
            inline_props: HashMap::new(),
            w: 0.0,
            h: 0.0,
            x: 0.0,
            y: 0.0,
            lines: vec![],
            gutters: vec![],
            scope: 0,
            geo: None,
            geo_off: (0.0, 0.0),
            label: None,
            tags: vec![],
        }
    }
    pub fn is(&self, t: &str) -> bool {
        self.chain.iter().any(|c| c == t)
    }
}

#[derive(Clone, Debug)]
pub struct Link {
    pub from: usize,
    pub to: usize,
    pub op: String,
    pub label: Option<String>,
    pub labels: Vec<Stmt>,
    pub classes: Vec<String>,
    pub style: Vec<Decl>,
    pub from_anchor: Option<String>,
    pub to_anchor: Option<String>,
    pub from_index: Option<u32>,
    pub to_index: Option<u32>,
    pub span: Span,
    pub stmt_index: usize,
    // the container the statement was written in
    pub container: usize,
}

pub struct Scene {
    pub sheet: SheetModel,
    pub nodes: Vec<Node>,
    pub root: usize,
    pub links: Vec<Link>,
    pub warnings: Vec<Diag>,
}

pub fn decls_to_map(decls: &[Decl]) -> Vec<(String, Value)> {
    decls.iter().map(|d| (d.name.clone(), d.value.clone())).collect()
}

pub fn build_sheet(doc: &Doc) -> Result<SheetModel, Diag> {
    let mut m = SheetModel::default();
    if let Some(sheet) = &doc.sheet {
        for item in &sheet.items {
            match item {
                SheetItem::Decl(d) => m.root.push(d.clone()),
                SheetItem::Var(d) => m.vars.push(d.clone()),
                SheetItem::Binding(b) => {
                    if let Some(params) = &b.params {
                        m.env.funcs.insert(b.name.clone(), Func { params: params.clone(), body: b.expr.clone() });
                    } else {
                        let v = m.env.eval_term(&b.expr, &HashMap::new())?;
                        m.env.vars.insert(b.name.clone(), v);
                    }
                }
                SheetItem::Rule(r) => {
                    // classify selector
                    if r.selector.len() == 1 {
                        let c = &r.selector[0];
                        if c.bars && c.type_name.as_deref() == Some("-") && c.id.is_none() && c.classes.is_empty() {
                            m.link_rules.extend(r.decls.iter().cloned());
                            continue;
                        }
                        if c.bars && c.id.is_none() && c.classes.is_empty() {
                            if let Some(t) = &c.type_name {
                                m.type_rules.push((t.clone(), r.decls.clone()));
                                continue;
                            }
                        }
                        if !c.bars && c.id.is_none() && c.classes.len() == 1 {
                            m.classes.push(ClassRule { name: c.classes[0].clone(), decls: r.decls.clone(), span: r.span, used: false });
                            continue;
                        }
                        if c.id.is_some() && c.classes.is_empty() {
                            m.id_rules.push((c.id.clone().unwrap(), r.decls.clone()));
                            continue;
                        }
                    }
                    if r.selector.len() == 2 {
                        let a = &r.selector[0];
                        let b = &r.selector[1];
                        if a.id.is_some() && !a.bars && b.bars && b.type_name.as_deref() == Some("-") {
                            m.scoped_link_rules.push((a.id.clone().unwrap(), r.decls.clone()));
                            continue;
                        }
                    }
                }
                SheetItem::Define(d) => {
                    m.defines.push(DefineModel {
                        name: d.name.clone(),
                        base: d.base.clone(),
                        decls: d.decls.clone(),
                        body: d.body.clone(),
                        span: d.span,
                    });
                }
            }
        }
    }
    Ok(m)
}

// The type chain of a (possibly user-defined) type, most-derived first.
pub fn type_chain(sheet: &SheetModel, name: &str) -> Option<(Prim, Vec<String>)> {
    let mut chain = Vec::new();
    let mut cur = name.to_string();
    let mut guard = 0;
    loop {
        guard += 1;
        if guard > 50 {
            return None;
        }
        if let Some(d) = sheet.define(&cur) {
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
            None => return Some((t.prim, chain)),
        }
    }
}

pub struct Builder<'a> {
    pub sheet: &'a SheetModel,
    pub src: &'a str,
    pub nodes: Vec<Node>,
    pub links: Vec<Link>,
    pub pending_links: Vec<(usize, LinkStmt, usize)>, // (container node, stmt, stmt index)
    pub warnings: Vec<Diag>,
    pub ids: HashMap<(usize, String), usize>,
    pub cap_counter: usize,
    pub stmt_counter: usize,
}

// an id the source writes in a node's head (not one made for a capsule)
pub fn written_id(src: &str, head: Span, id: &str) -> bool {
    src.get(head.start..head.end).map_or(false, |h| h.contains(&format!("#{}", id)))
}

// `lini-` ids are the compiler's own (generated topic ids and the like)
pub fn reserved_id(span: Span) -> Diag {
    Diag::error("reserved-id", "an id may not begin 'lini-' \u{2014} the prefix is reserved for generated names", span)
}

pub fn unknown_type(name: &str, span: Span) -> Diag {
    Diag::error("unknown-type", &format!("unknown type '{}'", name), span)
}

impl<'a> Builder<'a> {
    pub fn new(sheet: &'a SheetModel, src: &'a str) -> Self {
        Builder { sheet, src, nodes: vec![], links: vec![], pending_links: vec![], warnings: vec![], ids: HashMap::new(), cap_counter: 0, stmt_counter: 0 }
    }

    // The id scope children of `p` live in: `p` itself when it has an id, else p's scope.
    pub fn child_scope(&self, p: usize) -> usize {
        if p == 0 || self.nodes[p].id.is_some() {
            p
        } else {
            self.nodes[p].scope
        }
    }

    pub fn add(&mut self, mut n: Node, parent: Option<usize>) -> usize {
        n.parent = parent;
        if let Some(p) = parent {
            n.scope = self.child_scope(p);
        }
        let i = self.nodes.len();
        self.nodes.push(n);
        if let Some(p) = parent {
            self.nodes[p].children.push(i);
        }
        i
    }

    pub fn text_node(&mut self, text: &str, classes: &[String], style: Option<&Vec<Decl>>, span: Span, parent: usize) -> usize {
        let mut n = Node::new(Prim::Text, vec![], span);
        n.text = Some(text.to_string());
        n.classes = classes.to_vec();
        if let Some(s) = style {
            n.inline = s.clone();
        }
        self.add(n, Some(parent))
    }

    pub fn build_stmts(&mut self, stmts: &[Stmt], parent: usize) -> Result<(), Diag> {
        for s in stmts {
            match s {
                Stmt::Node(ns) => {
                    self.build_node(ns, parent)?;
                }
                Stmt::Text(t) => {
                    self.check_classes(&t.classes, t.span)?;
                    if !t.text.is_empty() {
                        self.text_node(&t.text, &t.classes, t.style.as_ref(), t.span, parent);
                    }
                }
                Stmt::Link(l) => {
                    // capsule endpoints are declared in statement order
                    let idx = self.stmt_counter;
                    self.stmt_counter += 1;
                    let mut l2 = l.clone();
                    for g in l2.groups.iter_mut() {
                        for ep in g.iter_mut() {
                            if let Endpoint::Node(ns) = ep {
                                let id = match &ns.id {
                                    Some(id) => id.clone(),
                                    None => {
                                        self.cap_counter += 1;
                                        format!("lini-cap-{}", self.cap_counter)
                                    }
                                };
                                let mut ns2 = (**ns).clone();
                                ns2.id = Some(id.clone());
                                let ni = self.build_node(&ns2, parent)?;
                                if ns.id.is_none() {
                                    self.nodes[ni].auto = false;
                                }
                                *ep = Endpoint::Path(PathRef { parts: vec![id], index: None, anchor: None, span: ns.span });
                            }
                        }
                    }
                    self.pending_links.push((parent, l2, idx));
                }
            }
        }
        Ok(())
    }

    pub fn check_classes(&mut self, classes: &[String], span: Span) -> Result<(), Diag> {
        for c in classes {
            if self.sheet.class(c).is_none() {
                return Err(Diag::error("unknown-class", &format!("unknown class '.{}'", c), span));
            }
        }
        Ok(())
    }

    pub fn build_node(&mut self, ns: &NodeStmt, parent: usize) -> Result<usize, Diag> {
        let tname = match &ns.type_name {
            Some(t) => t.clone(),
            None => "box".to_string(),
        };
        if tname == "link" {
            return Err(Diag::error("resolve", "links are drawn by operators, not the '|link|' type", ns.head_span));
        }
        let (prim, chain) = match type_chain(self.sheet, &tname) {
            Some(x) => x,
            None => return Err(unknown_type(&tname, ns.span)),
        };
        if ns.id.as_deref().map_or(false, |id| id.starts_with("lini-") && written_id(self.src, ns.head_span, id)) {
            return Err(reserved_id(ns.span));
        }
        self.check_classes(&ns.classes, ns.span)?;
        let mut n = Node::new(prim, chain.clone(), ns.span);
        n.id = ns.id.clone();
        n.classes = ns.classes.clone();
        n.label = ns.label.as_ref().map(|l| l.0.clone());
        if let Some(st) = &ns.style {
            n.inline = st.clone();
        }
        crate::tree::enter(self, ns, &chain, parent, &mut n);
        let nid = n.id.clone();
        let scope = self.child_scope(parent);
        if let Some(id) = &nid {
            if let Some(&prev) = self.ids.get(&(scope, id.clone())) {
                let mut d = Diag::error("duplicate-id", &format!("duplicate id '{}'", id), ns.span);
                d.related = Some(self.nodes[prev].span);
                return Err(d);
            }
        }
        let i = self.add(n, Some(parent));
        if let Some(id) = &nid {
            self.ids.insert((scope, id.clone()), i);
        }
        // table family: strings lower into cells (src/table.rs)
        if crate::table::is_table(&chain) {
            crate::table::build(self, ns, i)?;
            return Ok(i);
        }
        // |page|: the sheet chrome (src/page.rs)
        if crate::page::is_page(&chain) {
            crate::page::build(self, ns, i)?;
            return Ok(i);
        }
        // the label
        let is_group = chain.iter().any(|c| c == "group") && !chain.iter().any(|c| c == "table");
        let is_drawing = chain.iter().any(|c| c == "drawing");
        if let Some((label, lspan)) = ns.label.as_ref().filter(|(l, _)| !l.is_empty()) {
            if is_drawing {
                // a drawing's title sits under it
                let cchain = vec!["footnote".to_string(), "caption".to_string(), "block".to_string()];
                let cn = Node::new(Prim::Block, cchain, *lspan);
                let ci = self.add(cn, Some(i));
                self.text_node(label, &[], None, *lspan, ci);
            } else if is_group {
                let cchain = vec!["caption".to_string(), "block".to_string()];
                let mut cn = Node::new(Prim::Block, cchain, *lspan);
                cn.span = *lspan;
                let ci = self.add(cn, Some(i));
                self.text_node(label, &[], None, *lspan, ci);
            } else {
                match prim {
                    Prim::Block | Prim::Oval | Prim::Hex | Prim::Slant | Prim::Cyl | Prim::Diamond | Prim::Sketch => {
                        self.text_node(label, &[], None, *lspan, i);
                    }
                    // an icon's label names its symbol
                    Prim::Icon => self.nodes[i].text = Some(label.clone()),
                    // a line keeps its label (a section plane's letter)
                    Prim::Line => self.nodes[i].text = Some(label.clone()),
                    _ => {}
                }
            }
        }
        // a define's body is materialised per instance
        for t in chain.iter().rev() {
            if let Some(d) = self.sheet.define(t) {
                if let Some(body) = d.body.clone() {
                    self.build_stmts(&body, i)?;
                }
            }
        }
        if let Some(ch) = &ns.children {
            self.build_stmts(ch, i)?;
        }
        crate::tree::leave(self, i);
        Ok(i)
    }
}

impl<'a> Builder<'a> {
    // Dotted id path of a node from the root ("g.c").
    pub fn path_of(&self, i: usize) -> String {
        let mut parts = Vec::new();
        let mut cur = i;
        loop {
            if let Some(id) = &self.nodes[cur].id {
                parts.push(id.clone());
            }
            if cur == 0 {
                break;
            }
            let sc = self.nodes[cur].scope;
            if sc == cur {
                break;
            }
            cur = sc;
        }
        parts.reverse();
        parts.join(".")
    }

    fn scope_name(&self, scope: usize) -> String {
        if scope == 0 {
            "scene root".to_string()
        } else {
            self.path_of(scope)
        }
    }

    pub fn lookup(&self, scope: usize, parts: &[String]) -> Option<usize> {
        let mut cur = scope;
        for p in parts {
            cur = *self.ids.get(&(cur, p.clone()))?;
        }
        Some(cur)
    }

    // First node with this id anywhere below `scope` (depth-first, document order).
    fn find_deep(&self, scope: usize, id: &str) -> Option<usize> {
        let mut stack: Vec<usize> = self.nodes[scope].children.iter().rev().cloned().collect();
        while let Some(n) = stack.pop() {
            // a generated id (a tree's `lini-topic-N`) names no scope here
            let mut sc = self.nodes[n].scope;
            while sc != 0 && crate::tree::generated_id(sc) {
                sc = self.nodes[sc].scope;
            }
            if self.nodes[n].id.as_deref() == Some(id) && sc != scope {
                return Some(n);
            }
            for &c in self.nodes[n].children.iter().rev() {
                stack.push(c);
            }
        }
        None
    }

    // Resolve one endpoint, auto-creating a bare name as |box#name| "name".
    fn endpoint(&mut self, container: usize, p: &PathRef) -> Result<usize, Diag> {
        let scope = self.child_scope(container);
        if let Some(n) = self.lookup(scope, &p.parts) {
            return Ok(n);
        }
        if p.parts.len() > 1 {
            let msg = if scope == 0 {
                format!("link endpoint '{}' not found at scene root", p.parts.join("."))
            } else {
                format!("link endpoint '{}' not found in '{}'", p.parts.join("."), self.path_of(scope))
            };
            return Err(Diag::error("unknown-endpoint", &msg, p.span));
        }
        let name = p.parts[0].clone();
        if name.starts_with("lini-") {
            return Err(reserved_id(p.span));
        }
        if let Some(other) = self.find_deep(scope, &name) {
            let full = self.path_of(other);
            let named: Vec<&str> = full.split('.').filter(|s| !s.starts_with("lini-")).collect();
            let msg = format!(
                "endpoint '{}' auto-created at {} — a node '{}' also exists at '{}'",
                name,
                self.scope_name(scope),
                name,
                named.join(".")
            );
            self.warnings.push(Diag::warning("validate", &msg, p.span));
        }
        let chain = vec!["box".to_string(), "block".to_string()];
        let mut n = Node::new(Prim::Block, chain, p.span);
        n.id = Some(name.clone());
        n.auto = true;
        let i = self.add(n, Some(container));
        self.ids.insert((scope, name.clone()), i);
        self.text_node(&name, &[], None, p.span, i);
        Ok(i)
    }

    pub fn resolve_links(&mut self) -> Result<(), Diag> {
        let pending = std::mem::take(&mut self.pending_links);
        for (container, l, idx) in pending {
            for c in &l.classes {
                if self.sheet.class(c).is_none() {
                    return Err(Diag::error("unknown-class", &format!("unknown class '.{}'", c), l.span));
                }
            }
            let mut groups: Vec<Vec<(usize, Option<String>, Option<u32>)>> = Vec::new();
            for g in &l.groups {
                let mut v = Vec::new();
                for ep in g {
                    match ep {
                        Endpoint::Path(p) => {
                            let n = self.endpoint(container, p)?;
                            v.push((n, p.anchor.clone(), p.index));
                        }
                        Endpoint::Node(_) | Endpoint::Text(..) => {}
                    }
                }
                groups.push(v);
            }
            if groups.len() < 2 {
                return Err(Diag::error("chain-too-short", "link requires at least two endpoints", l.span));
            }
            for k in 0..groups.len() - 1 {
                let op = l.ops.get(k).map(|o| o.0.clone()).unwrap_or_default();
                for a in &groups[k] {
                    for b in &groups[k + 1] {
                        self.links.push(Link {
                            from: a.0,
                            to: b.0,
                            op: op.clone(),
                            label: l.label.as_ref().map(|x| x.0.clone()),
                            labels: l.labels.clone().unwrap_or_default(),
                            classes: l.classes.clone(),
                            style: l.style.clone().unwrap_or_default(),
                            from_anchor: a.1.clone(),
                            to_anchor: b.1.clone(),
                            from_index: a.2,
                            to_index: b.2,
                            span: l.span,
                            stmt_index: idx,
                            container,
                        });
                    }
                }
            }
        }
        Ok(())
    }
}

impl<'a> Builder<'a> {
    pub fn unworn_class_warnings(&mut self) {
        for c in &self.sheet.classes {
            let worn = self.nodes.iter().any(|n| n.classes.contains(&c.name))
                || self.links.iter().any(|l| {
                    l.classes.contains(&c.name) || l.labels.iter().any(|s| matches!(s, Stmt::Text(t) if t.classes.contains(&c.name)))
                });
            if !worn {
                self.warnings.push(Diag::warning("class-never-worn", &format!("class '.{}' is never worn", c.name), c.span));
            }
        }
    }
}
