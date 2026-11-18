// Trees and mindmaps: a `layout: tree` container holds one root `|topic|`; a
// `|mindmap|` makes its container a bilateral, naturally routed tree. Topics
// get ids (`lini-topic-N` by sibling position), `.lini-level-N` depth classes,
// a side on a bilateral tree's first level, a palette hue per mindmap branch,
// and the branch wires as plain `-` links after each parent topic.

use super::lower::{err, Cx, R};
use super::out::{Item, OLink};
use super::syntax::{Decl, Node, Stmt};

pub static HUES: &[&str] = &["rose", "orange", "amber", "lime", "green", "teal", "sky", "blue", "purple"];

#[derive(Clone, Debug)]
pub struct TreeMode {
    pub mindmap: bool,
    pub dir: String, // column | row | bilateral
    // the level the children being lowered take
    pub level: usize,
    // the branch's side and hue (inherited below the first level)
    pub side: Option<String>,
    pub hue: Option<String>,
    // the container took its first mindmap's direction
    pub hoisted: bool,
    // the direction `side:` is checked against: a mindmap's own (bilateral
    // unless it says), whatever its container lays out
    pub sem: String,
    // the container took its first mindmap's routing
    pub drop_routing: bool,
}

// any mindmaps among `stmts`
pub fn has_mindmap(cx: &Cx, stmts: &[Stmt]) -> bool {
    stmts.iter().any(|s| matches!(s, Stmt::Node(n) if is_mindmap(cx, n)))
}

// the direction the first mindmap among `stmts` hands its container
pub fn mindmap_dir(cx: &Cx, stmts: &[Stmt]) -> Option<(String, crate::diag::Span)> {
    for s in stmts {
        if let Stmt::Node(n) = s {
            if is_mindmap(cx, n) {
                return n.style.iter().rev().find(|d| d.name == "direction").map(|d| (d.value_text(), n.span));
            }
        }
    }
    None
}

// the routing the first mindmap among `stmts` hands its container
pub fn mindmap_routing(cx: &Cx, stmts: &[Stmt]) -> Option<String> {
    for s in stmts {
        if let Stmt::Node(n) = s {
            if is_mindmap(cx, n) {
                return n.style.iter().rev().find(|d| d.name == "routing").map(|d| d.value_text());
            }
        }
    }
    None
}

// a topic node (its type, or a define on it; mindmaps are topics)
pub fn is_topic(cx: &Cx, n: &Node) -> bool {
    let ty = n.ty.clone().unwrap_or_else(|| "box".into());
    cx.chain(&ty).map_or(false, |(_, c)| c.iter().any(|t| t == "topic"))
}

// the tree nodes among a container's statements: an implicit (mindmap)
// container takes only its mindmaps
pub fn tree_node(cx: &Cx, s: &Stmt, mode: &TreeMode) -> bool {
    match s {
        Stmt::Node(n) if mode.level == 0 && mode.mindmap => is_mindmap(cx, n),
        Stmt::Node(n) => is_topic(cx, n),
        _ => false,
    }
}

// a mindmap node (its type, or a define on it)
pub fn is_mindmap(cx: &Cx, n: &Node) -> bool {
    let ty = n.ty.clone().unwrap_or_else(|| "box".into());
    cx.chain(&ty).map_or(false, |(_, c)| c.iter().any(|t| t == "mindmap"))
}

fn own(n: &Node, name: &str) -> Option<String> {
    n.style.iter().rev().find(|d| d.name == name).and_then(|d| d.first().map(|s| s.to_string()))
}

// is this node a tree container? (Some(explicit))
pub fn container_kind(cx: &Cx, n: &Node) -> Option<bool> {
    match own(n, "layout").as_deref() {
        Some("tree") => return Some(true),
        Some(_) => return None,
        None => {}
    }
    if is_mindmap(cx, n) {
        return None;
    }
    if tree_content(cx, n).iter().any(|s| matches!(s, Stmt::Node(c) if is_mindmap(cx, c))) {
        return Some(false);
    }
    None
}

// the statements a container's tree reads: its define bodies and children
// (the tree pass reads the children alone)
pub fn tree_content(cx: &Cx, n: &Node) -> Vec<Stmt> {
    if cx.tree_check {
        return n.children.clone().unwrap_or_default();
    }
    let ty = n.ty.clone().unwrap_or_else(|| "box".into());
    match cx.chain(&ty) {
        Some((_, chain)) => cx.content(n, &chain).0,
        None => n.children.clone().unwrap_or_default(),
    }
}

// The tree errors are the tree pass's (the dry run): the lowering itself
// reads past them, as it does inside define bodies and link labels.

// a tree's direction, checked in the tree pass
pub fn read_dir(cx: &Cx, d: Option<String>, span: crate::diag::Span) -> R<String> {
    if cx.tree_check {
        check_dir(d, span)
    } else {
        Ok(d.unwrap_or_else(|| "column".to_string()))
    }
}

// `side:` picks a bilateral tree's first-level half
pub fn check_side(cx: &Cx, n: &Node, sem: &str, level: usize) -> R<()> {
    if !cx.tree_check {
        return Ok(());
    }
    if n.style.iter().any(|d| d.name == "side") {
        let sd = own(n, "side").unwrap_or_default();
        if sem == "bilateral" && sd != "left" && sd != "right" {
            return Err(err("a bilateral tree grows left and right — 'side' takes left or right", n.span));
        }
        if sem != "bilateral" || level != 1 {
            return Err(err("'side' picks a bilateral branch's half — this tree has one growth direction", n.span));
        }
    }
    Ok(())
}

pub fn check_dir(d: Option<String>, span: crate::diag::Span) -> R<String> {
    match d.as_deref() {
        None => Ok("column".to_string()),
        Some("column") | Some("row") | Some("bilateral") => Ok(d.unwrap()),
        Some(x) => Err(err(&format!("unknown direction '{}' — a tree grows column, row, or bilateral", x), span)),
    }
}

// the one-root rule of an explicit tree
pub fn check_roots(cx: &Cx, stmts: &[Stmt], span: crate::diag::Span) -> R<()> {
    if !cx.tree_check {
        return Ok(());
    }
    let tops: Vec<&Node> = stmts
        .iter()
        .filter_map(|s| match s {
            Stmt::Node(n) if n.ty.as_deref() == Some("topic") => Some(n),
            _ => None,
        })
        .collect();
    if tops.is_empty() {
        return Err(err("a tree needs exactly one root '|topic|'", span));
    }
    if tops.len() > 1 {
        let l = tops[1].label.clone().unwrap_or_default();
        return Err(err(&format!("a tree has one root — '|topic|' '{}' is a second", l), tops[1].span));
    }
    Ok(())
}

// the decls a container gains
pub fn container_decls(o: &mut Vec<Decl>, explicit: bool, dir: &str, mindmaps: bool, routing: Option<&str>) {
    if !explicit || mindmaps {
        for d in Decl::list(&format!("layout: tree; direction: {}; routing: {};", dir, routing.unwrap_or("natural"))) {
            if !o.iter().any(|x| x.name == d.name) {
                o.push(d);
            }
        }
    }
    if !o.iter().any(|d| d.name == "gap") {
        o.push(Decl::val("gap", "64 48"));
    }
}

impl<'a> Cx<'a> {
    // lower a statement list whose topics are tree nodes under `mode`
    pub fn tree_stmts(&mut self, stmts: &[Stmt], mode: &TreeMode, out: &mut Vec<Item>) -> R<()> {
        let topics: Vec<usize> =
            stmts.iter().enumerate().filter(|(_, s)| tree_node(self, s, mode)).map(|(i, _)| i).collect();
        let n = topics.len();
        let half = (n + 1) / 2;
        let mut drop_next = mode.level == 0 && mode.hoisted;
        let mut drop_route = mode.level == 0 && mode.drop_routing;
        // the scene's own branch wires close the document
        let at_root = mode.level == 0 && self.stack.is_empty();
        let mut deferred: Vec<Item> = Vec::new();
        for (i, s) in stmts.iter().enumerate() {
            match topics.iter().position(|&t| t == i) {
                Some(k) => {
                    let node = match s {
                        Stmt::Node(n) => n,
                        _ => unreachable!(),
                    };
                    // the branch side: split on a bilateral root, else inherited
                    let side = if mode.dir == "bilateral" {
                        if mode.level == 1 {
                            Some(own(node, "side").unwrap_or_else(|| if k < half { "right".into() } else { "left".into() }))
                        } else {
                            mode.side.clone()
                        }
                    } else {
                        None
                    };
                    let hue = if mode.mindmap {
                        if mode.level == 1 {
                            Some(HUES[k % HUES.len()].to_string())
                        } else {
                            mode.hue.clone()
                        }
                    } else {
                        None
                    };
                    let drop_dir = drop_next && is_mindmap(self, node);
                    if drop_dir {
                        drop_next = false;
                    }
                    let drop_rt = drop_route && is_mindmap(self, node);
                    if drop_rt {
                        drop_route = false;
                    }
                    let mut items = self.topic(node, mode, k + 1, side, hue, drop_dir, drop_rt)?;
                    if at_root && items.len() > 1 {
                        deferred.extend(items.drain(1..));
                    }
                    out.extend(items);
                }
                None => self.stmts_plain(std::slice::from_ref(s), out)?,
            }
        }
        // after the last node: trailing link statements stay last
        let at = out
            .iter()
            .rposition(|e| !matches!(e, Item::Node(n) if n.prim == super::lower::PENDING_PRIM))
            .map_or(0, |k| k + 1);
        let tail: Vec<Item> = out.drain(at..).collect();
        // the scene's first branch wire goes before its trailing links, the
        // rest right after the first of them
        let first_link = tail.first().and_then(|e| match e {
            Item::Node(n) if n.prim == super::lower::PENDING_PRIM => n.id.as_ref().and_then(|s| s.parse::<usize>().ok()),
            _ => None,
        });
        match first_link {
            Some(k) if !deferred.is_empty() => {
                let mut it = deferred.into_iter();
                out.extend(it.next());
                self.pendings[k].trail.extend(it);
            }
            _ => out.extend(deferred),
        }
        out.extend(tail);
        Ok(())
    }

    fn topic(
        &mut self,
        n: &Node,
        mode: &TreeMode,
        k: usize,
        side: Option<String>,
        hue: Option<String>,
        drop_dir: bool,
        drop_rt: bool,
    ) -> R<Vec<Item>> {
        if let Some(e) = self.head_err(n) {
            return Err(e);
        }
        let implicit_root = mode.level == 0 && mode.mindmap;
        if !implicit_root {
            check_side(self, n, &mode.sem, mode.level)?;
        }
        let ty = n.ty.clone().unwrap_or_else(|| "topic".to_string());
        let (prim, chain) = self.chain(&ty).unwrap();
        let mindmap = mode.mindmap || chain.iter().any(|c| c == "mindmap");
        let mut o = super::out::ONode::new(&prim);
        let id = n.id.clone().unwrap_or_else(|| format!("lini-topic-{}", k));
        o.id = Some(id.clone());
        for t in &chain {
            self.used.insert(t.clone());
            o.classes.push(format!("lini-{}", t));
        }
        o.classes.extend(n.classes.iter().cloned());
        let level = mode.level;
        if level == 1 && mode.dir == "bilateral" {
            if let Some(s) = &side {
                o.classes.push(format!("lini-side-{}", s));
            }
        }
        o.classes.push(format!("lini-level-{}", level));
        // every topic's level gets the mindmap scale, should a mindmap appear
        if level >= 1 {
            self.mindmap_levels.insert(level);
        }
        if mindmap {
            self.mindmap_used = true;
            if let Some(h) = &hue {
                o.classes.push(format!("lini-hue-{}", h));
                self.mindmap_hues.insert(h.clone());
            }
        }
        // `side:` is spent on the branch class
        o.decls = n.style.iter().filter(|d| !(d.name == "side" && mode.dir == "bilateral" && level == 1)).cloned().collect();
        if drop_dir {
            // its direction went to the container
            o.decls.retain(|d| d.name != "direction");
        }
        if drop_rt {
            // so did its routing
            o.decls.retain(|d| d.name != "routing");
        }
        // the content: label, define bodies, then the children with topics
        // lowered one level down
        // a mindmap checks its own direction; a scene's (or a container's)
        // own mindmap reads it, inside a tree the tree's direction rules
        let mut sem = mode.sem.clone();
        if chain.iter().any(|c| c == "mindmap") {
            if let Some(d) = own(n, "direction") {
                let d = read_dir(self, Some(d), n.span)?;
                if mode.level == 0 && mode.mindmap {
                    sem = d;
                }
            }
        }
        let child_mode = TreeMode {
            mindmap,
            dir: mode.dir.clone(),
            level: mode.level + 1,
            side: side.clone(),
            hue: hue.clone(),
            hoisted: false,
            sem,
            drop_routing: false,
        };
        let label = n.label.as_ref().map(|l| l.trim().to_string()).filter(|l| !l.is_empty());
        let (unit, thickness) = match self.stack.last() {
            Some(f) => (f.unit.clone(), f.thickness.clone()),
            None => (self.root_unit.clone(), None),
        };
        self.stack.push(super::lower::Frame { chain: chain.clone(), unit, thickness, tree: None,
            sch: None,
            sch_links: 0,
            caps: 0,
            sch_explicit: false,
            breaks: false,
            plan_breaks: false,
            bare: None,
            cid: {
                self.next_cid += 1;
                self.next_cid
            },
        });
        let mut text_label: Option<(String, usize)> = None;
        let r = (|| -> R<Vec<Item>> {
            let mut children = Vec::new();
            let bodies = self.bodies(&chain)?;
            if let Some(l) = &label {
                text_label = Some((l.clone(), bodies.len()));
            }
            children.extend(bodies);
            if let Some(ch) = &n.children {
                self.tree_stmts(ch, &child_mode, &mut children)?;
            }
            Ok(children)
        })();
        self.stack.pop();
        o.children = r?;
        o.text_label = text_label;
        // the branch wires to this topic's child topics
        let kids: Vec<(String, Option<String>, Option<String>)> = self.child_topics(n, &child_mode);
        let mut out = vec![Item::Node(o)];
        out.extend(self.branch_links(&id, level, &mode.dir, mindmap, &side, &hue, &kids));
        Ok(out)
    }

    // (id, side, hue) of a topic's child topics, as `tree_stmts` assigns them
    fn child_topics(&self, n: &Node, mode: &TreeMode) -> Vec<(String, Option<String>, Option<String>)> {
        let ch = match &n.children {
            Some(c) => c,
            None => return Vec::new(),
        };
        let tops: Vec<&Node> = ch
            .iter()
            .filter(|s| tree_node(self, s, mode))
            .filter_map(|s| match s {
                Stmt::Node(n) => Some(n),
                _ => None,
            })
            .collect();
        let half = (tops.len() + 1) / 2;
        tops.iter()
            .enumerate()
            .map(|(k, t)| {
                let id = t.id.clone().unwrap_or_else(|| format!("lini-topic-{}", k + 1));
                let side = if mode.dir == "bilateral" {
                    if mode.level == 1 {
                        Some(own(t, "side").unwrap_or_else(|| if k < half { "right".into() } else { "left".into() }))
                    } else {
                        mode.side.clone()
                    }
                } else {
                    None
                };
                let hue = if mode.mindmap {
                    if mode.level == 1 {
                        Some(HUES[k % HUES.len()].to_string())
                    } else {
                        mode.hue.clone()
                    }
                } else {
                    None
                };
                (id, side, hue)
            })
            .collect()
    }

    #[allow(clippy::too_many_arguments)]
    fn branch_links(
        &mut self,
        id: &str,
        level: usize,
        dir: &str,
        mindmap: bool,
        side: &Option<String>,
        hue: &Option<String>,
        kids: &[(String, Option<String>, Option<String>)],
    ) -> Vec<Item> {
        if kids.is_empty() {
            return Vec::new();
        }
        let link = |from: &str, to: &str, members: &[&(String, Option<String>, Option<String>)], class: Option<&String>| {
            let ends: Vec<String> = members.iter().map(|(c, _, _)| format!("{}.{}:{}", id, c, to)).collect();
            Item::Link(OLink {
                head: format!("{}:{} - {}", id, from, ends.join(" & ")),
                classes: class.map(|c| vec![format!("lini-hue-{}", c)]).unwrap_or_default(),
                decls: vec![],
                labels: vec![],
            })
        };
        let all: Vec<&(String, Option<String>, Option<String>)> = kids.iter().collect();
        if mindmap && dir != "bilateral" {
            let (f, t) = if dir == "row" { ("right", "left") } else { ("bottom", "top") };
            if level == 0 {
                return kids.iter().map(|k| link(f, t, &[k], k.2.as_ref())).collect();
            }
            return vec![link(f, t, &all, hue.as_ref())];
        }
        match dir {
            "column" => vec![link("bottom", "top", &all, None)],
            "row" => vec![link("right", "left", &all, None)],
            _ => {
                if level == 0 {
                    if mindmap {
                        return kids
                            .iter()
                            .map(|k| {
                                let s = k.1.as_deref().unwrap_or("right");
                                let (f, t) = if s == "left" { ("left", "right") } else { ("right", "left") };
                                link(f, t, &[k], k.2.as_ref())
                            })
                            .collect();
                    }
                    let right: Vec<&(String, Option<String>, Option<String>)> =
                        kids.iter().filter(|k| k.1.as_deref() != Some("left")).collect();
                    let left: Vec<&(String, Option<String>, Option<String>)> =
                        kids.iter().filter(|k| k.1.as_deref() == Some("left")).collect();
                    let mut v = Vec::new();
                    if !right.is_empty() {
                        v.push(link("right", "left", &right, None));
                    }
                    if !left.is_empty() {
                        v.push(link("left", "right", &left, None));
                    }
                    v
                } else {
                    let (f, t) = if side.as_deref() == Some("left") { ("left", "right") } else { ("right", "left") };
                    vec![link(f, t, &all, if mindmap { hue.as_ref() } else { None })]
                }
            }
        }
    }
}
