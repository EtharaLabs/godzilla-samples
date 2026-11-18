// --static and --embed-font: passes over the rendered SVG.
//
// The stylesheet is replayed as a small CSS cascade (class rules, descendant
// selectors, inline styles, inheritance through <g>) to find each <text>'s
// font. --static then draws text as <use> references to glyph outlines of the
// bundled faces and inlines every `var()` as its light-side literal;
// --embed-font embeds each face (family × weight) the text uses.

use crate::diag::{Diag, Span};
use crate::font::{self, Family};
use crate::util::{base64, f4};
use std::cell::RefCell;
use std::collections::{BTreeMap, BTreeSet, HashMap};

thread_local! {
    static WARNINGS: RefCell<Vec<Diag>> = RefCell::new(Vec::new());
    static EXACT: RefCell<HashMap<String, f64>> = RefCell::new(HashMap::new());
}

// Text emitters note the exact coordinates behind the 4-decimal attributes
// they write, so outlined glyphs are placed from unrounded positions.
pub fn note(v: f64) {
    EXACT.with(|m| {
        m.borrow_mut().insert(f4(v), v);
    });
}

fn exact(s: &str) -> Option<f64> {
    let s = s.trim();
    EXACT.with(|m| m.borrow().get(s).copied()).or_else(|| s.parse::<f64>().ok())
}

// Warnings raised while outlining (texts with no bundled glyph).
pub fn take_warnings() -> Vec<Diag> {
    WARNINGS.with(|w| std::mem::take(&mut *w.borrow_mut()))
}

// ---------------------------------------------------------------- variables

// The root `--lini-*` declarations, resolvable to light-side literals.
pub struct Vars {
    map: HashMap<String, String>,
}

fn light_side(v: &str) -> String {
    match crate::theme::split_light_dark(v.trim()) {
        Some((l, _)) => l,
        None => v.to_string(),
    }
}

impl Vars {
    pub fn new(decls: &[(String, String)]) -> Vars {
        Vars { map: decls.iter().cloned().collect() }
    }

    // Inline every resolvable `var(--lini-X)`; light-dark pairs take their light side.
    pub fn bake(&self, s: &str) -> String {
        self.bake_depth(s, 0)
    }

    fn bake_depth(&self, s: &str, depth: usize) -> String {
        if depth > 32 || !s.contains("var(--lini-") {
            return s.to_string();
        }
        let mut out = String::with_capacity(s.len());
        let mut rest = s;
        while let Some(p) = rest.find("var(--lini-") {
            out.push_str(&rest[..p]);
            let after = &rest[p + 11..];
            let end = match after.find(')') {
                Some(e) => e,
                None => {
                    out.push_str(&rest[p..]);
                    rest = "";
                    break;
                }
            };
            let name = &after[..end];
            match self.map.get(name) {
                Some(v) => out.push_str(&self.bake_depth(&light_side(v), depth + 1)),
                None => out.push_str(&rest[p..p + 11 + end + 1]),
            }
            rest = &after[end + 1..];
        }
        out.push_str(rest);
        out
    }
}

// ---------------------------------------------------------------- the cascade

struct Rule {
    // descendant chain of compounds, each a set of class names
    sel: Vec<Vec<String>>,
    spec: usize,
    order: usize,
    decls: Vec<(String, String)>,
}

pub struct Sheet {
    root: Vec<(String, String)>,
    text_family: Option<String>,
    rules: Vec<Rule>,
}

fn parse_decls(body: &str) -> Vec<(String, String)> {
    let mut out = Vec::new();
    for part in body.split(';') {
        if let Some(c) = part.find(':') {
            let k = part[..c].trim();
            let v = part[c + 1..].trim();
            if !k.is_empty() {
                out.push((k.to_string(), v.to_string()));
            }
        }
    }
    out
}

impl Sheet {
    // `css` is the stylesheet with `.lini` as its scope.
    pub fn parse(css: &str) -> Sheet {
        let mut sh = Sheet { root: vec![], text_family: None, rules: vec![] };
        let mut in_layer = false;
        for line in css.lines() {
            let l = line.trim();
            if l.starts_with("@layer") {
                in_layer = true;
                continue;
            }
            if in_layer {
                if line == "    }" {
                    in_layer = false;
                }
                continue;
            }
            let (sel, body) = match (l.find('{'), l.rfind('}')) {
                (Some(a), Some(b)) if b > a => (l[..a].trim(), &l[a + 1..b]),
                _ => continue,
            };
            let decls = parse_decls(body);
            if sel == ".lini, .lini text" {
                sh.text_family = decls.iter().find(|(k, _)| k == "font-family").map(|(_, v)| v.clone());
                continue;
            }
            if sel == ".lini" {
                sh.root.extend(decls);
                continue;
            }
            let rest = match sel.strip_prefix(".lini ") {
                Some(r) => r,
                None => continue,
            };
            if rest.contains(|c| matches!(c, ':' | '~' | '>' | '+' | ',' | '[')) {
                continue;
            }
            let mut chain = Vec::new();
            let mut spec = 1;
            for comp in rest.split_whitespace() {
                let classes: Vec<String> = comp.split('.').filter(|s| !s.is_empty()).map(|s| s.to_string()).collect();
                if classes.is_empty() || !comp.starts_with('.') {
                    chain.clear();
                    break;
                }
                spec += classes.len();
                chain.push(classes);
            }
            if chain.is_empty() {
                continue;
            }
            let order = sh.rules.len();
            sh.rules.push(Rule { sel: chain, spec, order, decls });
        }
        sh
    }

    // The winning declared value of `prop` for an element (classes `cls`,
    // ancestors' classes `anc`, root first), if any rule sets it.
    fn rule_value(&self, prop: &str, cls: &[String], anc: &[Vec<String>]) -> Option<String> {
        let mut best: Option<(usize, usize, &String)> = None;
        for r in &self.rules {
            let v = match r.decls.iter().rev().find(|(k, _)| k == prop) {
                Some((_, v)) => v,
                None => continue,
            };
            if !matches_rule(&r.sel, cls, anc) {
                continue;
            }
            if best.map(|b| (r.spec, r.order) >= (b.0, b.1)).unwrap_or(true) {
                best = Some((r.spec, r.order, v));
            }
        }
        best.map(|b| b.2.clone())
    }
}

fn has_all(cls: &[String], need: &[String]) -> bool {
    need.iter().all(|n| cls.iter().any(|c| c == n))
}

fn matches_rule(sel: &[Vec<String>], cls: &[String], anc: &[Vec<String>]) -> bool {
    let last = sel.len() - 1;
    if !has_all(cls, &sel[last]) {
        return false;
    }
    // remaining compounds right to left against the ancestors, innermost first
    let mut k = last;
    let mut a = anc.len();
    while k > 0 {
        k -= 1;
        loop {
            if a == 0 {
                return false;
            }
            a -= 1;
            if has_all(&anc[a], &sel[k]) {
                break;
            }
        }
    }
    true
}

// The inherited font state of an element.
#[derive(Clone, Debug)]
struct FontState {
    size: f64,
    weight: u32,
    family: String,
    anchor: String,
    decoration: String,
    italic: bool,
}

fn parse_size(v: &str) -> Option<f64> {
    v.trim().trim_end_matches("px").parse::<f64>().ok()
}

fn parse_weight(v: &str) -> Option<u32> {
    match v.trim() {
        "normal" => Some(400),
        "bold" => Some(700),
        "medium" => Some(500),
        "semibold" => Some(600),
        s => s.parse::<f64>().ok().map(|x| x as u32),
    }
}

fn attr<'a>(attrs: &'a [(String, String)], k: &str) -> Option<&'a str> {
    attrs.iter().find(|(n, _)| n == k).map(|(_, v)| v.as_str())
}

fn unescape(s: &str) -> String {
    s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"").replace("&apos;", "'").replace("&amp;", "&")
}

// Parse `name="value"` pairs of a start tag's attribute text.
fn parse_attrs(s: &str) -> Vec<(String, String)> {
    let mut out = Vec::new();
    let b = s.as_bytes();
    let mut i = 0;
    while i < b.len() {
        while i < b.len() && (b[i] as char).is_whitespace() {
            i += 1;
        }
        let ns = i;
        while i < b.len() && b[i] != b'=' && !(b[i] as char).is_whitespace() {
            i += 1;
        }
        if i >= b.len() || b[i] != b'=' {
            break;
        }
        let name = s[ns..i].to_string();
        i += 1;
        if i >= b.len() || b[i] != b'"' {
            break;
        }
        i += 1;
        let vs = i;
        while i < b.len() && b[i] != b'"' {
            i += 1;
        }
        out.push((name, s[vs..i.min(b.len())].to_string()));
        i += 1;
    }
    out
}

// ---------------------------------------------------------------- glyphs

fn fmt_unit(v: f64) -> String {
    if v.fract() == 0.0 {
        format!("{}", v as i64)
    } else {
        f4(v)
    }
}

// A glyph's outline as path data in font units (y up). Quadratic contours:
// off-curve runs get implied on-curve midpoints; each contour closes with an
// explicit segment back to its start, then Z.
pub fn glyph_path(f: &font::Font, gid: u16) -> String {
    let mut d = String::new();
    let pt = |x: f64, y: f64| format!("{} {}", fmt_unit(x), fmt_unit(y));
    for contour in f.outline(gid) {
        if contour.is_empty() {
            continue;
        }
        let mut first_on: Option<(f64, f64)> = None;
        let mut first_off: Option<(f64, f64)> = None;
        let mut last_off: Option<(f64, f64)> = None;
        for &(x, y, on) in &contour {
            let p = (x, y);
            if first_on.is_none() {
                if on {
                    first_on = Some(p);
                    d.push_str(&format!("M{}", pt(x, y)));
                } else if let Some(off) = first_off {
                    let mid = ((off.0 + x) / 2.0, (off.1 + y) / 2.0);
                    first_on = Some(mid);
                    last_off = Some(p);
                    d.push_str(&format!("M{}", pt(mid.0, mid.1)));
                } else {
                    first_off = Some(p);
                }
                continue;
            }
            match (last_off, on) {
                (Some(off), true) => {
                    last_off = None;
                    d.push_str(&format!("Q{} {}", pt(off.0, off.1), pt(x, y)));
                }
                (Some(off), false) => {
                    last_off = Some(p);
                    let mid = ((off.0 + x) / 2.0, (off.1 + y) / 2.0);
                    d.push_str(&format!("Q{} {}", pt(off.0, off.1), pt(mid.0, mid.1)));
                }
                (None, true) => d.push_str(&format!("L{}", pt(x, y))),
                (None, false) => last_off = Some(p),
            }
        }
        if let (Some(o1), Some(o2)) = (first_off, last_off) {
            last_off = None;
            let mid = ((o2.0 + o1.0) / 2.0, (o2.1 + o1.1) / 2.0);
            d.push_str(&format!("Q{} {}", pt(o2.0, o2.1), pt(mid.0, mid.1)));
        }
        if let (Some(p), Some(o1)) = (first_on, first_off) {
            d.push_str(&format!("Q{} {}", pt(o1.0, o1.1), pt(p.0, p.1)));
        } else if let (Some(p), Some(o2)) = (first_on, last_off) {
            d.push_str(&format!("Q{} {}", pt(o2.0, o2.1), pt(p.0, p.1)));
        } else if let Some(p) = first_on {
            d.push_str(&format!("L{}", pt(p.0, p.1)));
        }
        if first_on.is_some() {
            d.push('Z');
        }
    }
    d
}

// The bundled glyph a char draws with: '⌀' borrows 'Ø'.
fn glyph_of(f: &font::Font, c: char) -> Option<u16> {
    f.glyph_for(if c == '\u{2300}' { '\u{d8}' } else { c })
}

fn family_digit(f: Family) -> u32 {
    match f {
        Family::Code => 0,
        Family::Sans => 1,
    }
}

fn weight_class(w: u32) -> u32 {
    [400, 500, 600, 700][font::weight_index(w)]
}

// (underline position, thickness, strikeout position, size) in font units
fn deco_metrics(fam: Family, weight: u32) -> (f64, f64, f64, f64) {
    let d = font::font_bytes(fam, weight);
    let rd16 = |o: usize| i16::from_be_bytes([d[o], d[o + 1]]) as f64;
    let n = u16::from_be_bytes([d[4], d[5]]) as usize;
    let mut post = 0;
    let mut os2 = 0;
    for i in 0..n {
        let o = 12 + 16 * i;
        let off = u32::from_be_bytes([d[o + 8], d[o + 9], d[o + 10], d[o + 11]]) as usize;
        match &d[o..o + 4] {
            b"post" => post = off,
            b"OS/2" => os2 = off,
            _ => {}
        }
    }
    (rd16(post + 8), rd16(post + 10), rd16(os2 + 28), rd16(os2 + 26))
}

// ---------------------------------------------------------------- the pass

pub struct Pass<'a> {
    pub sheet: Sheet,
    pub vars: &'a Vars,
    // font weights resolve against the default palette (the compile measured
    // text with it) whatever `--theme` says; the document's variables apply
    weights: Vars,
    pub outline: bool,
    // (family digit, weight) of every text met
    pub used: BTreeSet<(u32, u32)>,
    // (family digit, weight, gid) → path data
    pub glyphs: BTreeMap<(u32, u32, u16), String>,
    // text nodes' (text, span), to place warnings
    texts: Vec<(String, Span, bool)>,
}

struct Elem {
    name: String,
    classes: Vec<String>,
    state: FontState,
}

impl<'a> Pass<'a> {
    pub fn new(css: &str, vars: &'a Vars, outline: bool, ctx: &crate::compile::Ctx) -> Pass<'a> {
        // the scene's texts in the order the body draws them (pinned ones after
        // their siblings), so equal texts take their own spans
        let mut texts = Vec::new();
        fn walk(ctx: &crate::compile::Ctx, i: usize, out: &mut Vec<(String, Span, bool)>) {
            let n = &ctx.nodes[i];
            if n.prim == crate::types::Prim::Text {
                out.push((n.lines.join("\n"), n.span, false));
            }
            for c in crate::render::paint_order(ctx, &n.children) {
                walk(ctx, c, out);
            }
        }
        walk(ctx, 0, &mut texts);
        // (any text the walk missed keeps its place after)
        for n in &ctx.nodes {
            if n.prim == crate::types::Prim::Text && !texts.iter().any(|t| t.1 == n.span && t.0 == n.lines.join("\n")) {
                texts.push((n.lines.join("\n"), n.span, false));
            }
        }
        for l in &ctx.links {
            if let Some(t) = &l.label {
                texts.push((t.clone(), l.span, false));
            }
        }
        let def = crate::theme::builtin("default");
        let weights = Vars {
            map: vars
                .map
                .iter()
                .map(|(k, v)| {
                    let user = ctx.sheet.vars.iter().any(|d| &d.name == k);
                    let d = if user { None } else { def.as_ref().and_then(|t| t.css_value(k)) };
                    (k.clone(), d.unwrap_or_else(|| v.clone()))
                })
                .collect(),
        };
        Pass { sheet: Sheet::parse(css), vars, weights, outline, used: BTreeSet::new(), glyphs: BTreeMap::new(), texts }
    }

    fn root_state(&self) -> FontState {
        let get = |k: &str| self.sheet.root.iter().rev().find(|(n, _)| n == k).map(|(_, v)| self.vars.bake(v));
        FontState {
            size: get("font-size").and_then(|v| parse_size(&v)).unwrap_or(15.0),
            weight: self.sheet.root.iter().rev().find(|(n, _)| n == "font-weight").map(|(_, v)| self.weights.bake(v)).and_then(|v| parse_weight(&v)).unwrap_or(500),
            family: self.sheet.text_family.as_ref().map(|v| self.vars.bake(v)).unwrap_or_default(),
            anchor: "start".to_string(),
            decoration: String::new(),
            italic: false,
        }
    }

    // The element's state: inline style, then rules, then inheritance.
    fn state_of(&self, parent: &FontState, cls: &[String], anc: &[Vec<String>], style: Option<&str>, is_text: bool) -> FontState {
        let inline = style.map(|s| parse_decls(&unescape(s))).unwrap_or_default();
        let pick = |k: &str| -> Option<String> {
            if let Some((_, v)) = inline.iter().rev().find(|(n, _)| n == k) {
                return Some(self.vars.bake(v));
            }
            self.sheet.rule_value(k, cls, anc).map(|v| self.vars.bake(&v))
        };
        let mut s = parent.clone();
        if let Some(v) = pick("font-size").and_then(|v| parse_size(&v)) {
            s.size = v;
        }
        let weight = match inline.iter().rev().find(|(n, _)| n == "font-weight") {
            Some((_, v)) => Some(self.weights.bake(v)),
            None => self.sheet.rule_value("font-weight", cls, anc).map(|v| self.weights.bake(&v)),
        };
        if let Some(v) = weight.and_then(|v| parse_weight(&v)) {
            s.weight = v;
        }
        if let Some(v) = pick("text-anchor") {
            s.anchor = v;
        }
        if let Some(v) = pick("text-decoration") {
            s.decoration = v;
        }
        if let Some(v) = pick("font-style") {
            s.italic = v.trim() == "italic";
        }
        match pick("font-family") {
            Some(v) => s.family = v,
            None => {
                if is_text {
                    if let Some(f) = &self.sheet.text_family {
                        s.family = self.vars.bake(f);
                    }
                }
            }
        }
        s
    }

    // Walk a body fragment (scene or links layer): outline texts (--static)
    // and record the faces they use.
    pub fn run(&mut self, body: &str) -> String {
        let mut out = String::with_capacity(body.len());
        let root = self.root_state();
        let mut stack: Vec<Elem> = Vec::new();
        let mut i = 0;
        let b = body.as_bytes();
        while i < b.len() {
            let lt = match body[i..].find('<') {
                Some(p) => i + p,
                None => {
                    out.push_str(&body[i..]);
                    break;
                }
            };
            out.push_str(&body[i..lt]);
            let gt = match body[lt..].find('>') {
                Some(p) => lt + p,
                None => {
                    out.push_str(&body[lt..]);
                    break;
                }
            };
            let tag = &body[lt + 1..gt];
            if let Some(name) = tag.strip_prefix('/') {
                let name = name.trim();
                if let Some(pos) = stack.iter().rposition(|e| e.name == name) {
                    stack.truncate(pos);
                }
                out.push_str(&body[lt..=gt]);
                i = gt + 1;
                continue;
            }
            if tag.starts_with('!') || tag.starts_with('?') {
                out.push_str(&body[lt..=gt]);
                i = gt + 1;
                continue;
            }
            let self_close = tag.ends_with('/');
            let inner = tag.trim_end_matches('/');
            let (name, rest) = match inner.find(char::is_whitespace) {
                Some(p) => (&inner[..p], &inner[p..]),
                None => (inner, ""),
            };
            let attrs = parse_attrs(rest);
            let classes: Vec<String> = attr(&attrs, "class").map(|c| c.split_whitespace().map(|s| s.to_string()).collect()).unwrap_or_default();
            let parent = stack.last().map(|e| e.state.clone()).unwrap_or_else(|| root.clone());
            let anc: Vec<Vec<String>> = stack.iter().map(|e| e.classes.clone()).collect();
            if name == "text" && !self_close {
                let end = match body[gt + 1..].find("</text>") {
                    Some(p) => gt + 1 + p,
                    None => {
                        out.push_str(&body[lt..]);
                        break;
                    }
                };
                let content = &body[gt + 1..end];
                let st = self.state_of(&parent, &classes, &anc, attr(&attrs, "style"), true);
                let line_start = out.rfind('\n').map(|p| p + 1).unwrap_or(0);
                let indent = out[line_start..].len();
                let whole = &body[lt..end + 7];
                // a drawing's dimension/plane letters embed at their node's
                // weight; their class rule only restyles them in CSS
                let face_weight = if !self.outline && classes.iter().any(|c| c == "lini-dim-text") { parent.weight } else { st.weight };
                match self.text(&attrs, content, &st, indent, face_weight) {
                    Some(g) => out.push_str(&g),
                    None => out.push_str(whole),
                }
                i = end + 7;
                continue;
            }
            let st = self.state_of(&parent, &classes, &anc, attr(&attrs, "style"), false);
            if !self_close {
                stack.push(Elem { name: name.to_string(), classes, state: st });
            }
            out.push_str(&body[lt..=gt]);
            i = gt + 1;
        }
        out
    }

    // One <text>: its lines as (x, baseline, dx list, text).
    fn text(&mut self, attrs: &[(String, String)], content: &str, st: &FontState, indent: usize, face_weight: u32) -> Option<String> {
        let fam = crate::style::family_of_name(first_family(&st.family));
        let weight = weight_class(st.weight);
        let fd = family_digit(fam);
        self.used.insert((fd, weight_class(face_weight)));
        if !self.outline {
            return None;
        }
        let num = |v: Option<&str>| v.and_then(exact);
        let dxs = |v: Option<&str>| -> Vec<f64> { v.map(|s| s.split_whitespace().filter_map(|x| x.parse().ok()).collect()).unwrap_or_default() };
        let size = st.size;
        let mut lines: Vec<(f64, f64, Vec<f64>, String)> = Vec::new();
        if content.contains("<tspan") {
            let mut base = num(attr(attrs, "y")).unwrap_or(0.0);
            let mut rest = content;
            while let Some(p) = rest.find("<tspan") {
                let gt = p + rest[p..].find('>')?;
                let ta = parse_attrs(&rest[p + 6..gt]);
                let close = gt + rest[gt..].find("</tspan>")?;
                let text = unescape(&rest[gt + 1..close]);
                if let Some(y) = num(attr(&ta, "y")) {
                    base = y;
                }
                if let Some(dy) = num(attr(&ta, "dy")) {
                    base += dy;
                }
                let x = num(attr(&ta, "x")).unwrap_or(0.0);
                lines.push((x, base, dxs(attr(&ta, "dx")), text));
                rest = &rest[close + 8..];
            }
        } else {
            let x = num(attr(attrs, "x")).unwrap_or(0.0);
            let mut y = num(attr(attrs, "y")).unwrap_or(0.0);
            if let Some(dy) = attr(attrs, "dy") {
                if let Some(em) = dy.strip_suffix("em") {
                    y += em.parse::<f64>().unwrap_or(0.0) * size;
                } else {
                    y += dy.parse::<f64>().unwrap_or(0.0);
                }
            }
            lines.push((x, y, dxs(attr(attrs, "dx")), unescape(content)));
        }
        let f = font::font(fam, weight);
        // every char needs a bundled glyph, else the text stays <text>
        let mut missing: Vec<char> = Vec::new();
        for (_, _, _, t) in &lines {
            for c in t.chars() {
                if glyph_of(f, c).is_none() && !missing.contains(&c) {
                    missing.push(c);
                }
            }
        }
        if !missing.is_empty() {
            let full: String = lines.iter().map(|l| l.3.clone()).collect::<Vec<_>>().join("\n");
            let span = match self.texts.iter_mut().find(|(t, _, used)| !*used && *t == full) {
                Some(e) => {
                    e.2 = true;
                    e.1
                }
                None => Span::default(),
            };
            let mut list: Vec<String> = missing.iter().take(4).map(|c| format!("'{}'", c)).collect();
            if missing.len() > 4 {
                list.push("…".to_string());
            }
            let msg = format!(
                "no bundled glyph for {} in \"{}\" — under --static this text stays <text>, drawn by the viewer's fonts",
                list.join(", "),
                full.replace('\n', "\\n")
            );
            WARNINGS.with(|w| w.borrow_mut().push(Diag::warning("validate", &msg, span)));
            return None;
        }
        let full: String = lines.iter().map(|l| l.3.clone()).collect::<Vec<_>>().join("\n");
        if let Some(e) = self.texts.iter_mut().find(|(t, _, used)| !*used && *t == full) {
            e.2 = true;
        }
        let s = size / f.upem;
        let ind = " ".repeat(indent);
        let mut g = String::from("<g");
        for k in ["class", "style", "transform"] {
            if let Some((n, v)) = attrs.iter().find(|(n, _)| n == k) {
                g.push_str(&format!(" {}=\"{}\"", n, v));
            }
        }
        g.push_str(">\n");
        let (upos, uthk, spos, ssize) = deco_metrics(fam, weight);
        let mut any = false;
        for (x, base, dx, text) in &lines {
            let chars: Vec<char> = text.chars().collect();
            let mut width = 0.0;
            for (k, c) in chars.iter().enumerate() {
                width += font::outline_advance(f, fam, *c) / f.upem * size;
                if k > 0 {
                    width += dx.get(k).copied().unwrap_or(0.0);
                }
            }
            let start = match st.anchor.as_str() {
                "middle" => x - width / 2.0,
                "end" => x - width,
                _ => *x,
            };
            let mut pen = start;
            for (k, c) in chars.iter().enumerate() {
                if k > 0 {
                    pen += dx.get(k).copied().unwrap_or(0.0);
                }
                let gid = glyph_of(f, *c).unwrap();
                let key = (fd, weight, gid);
                if !self.glyphs.contains_key(&key) {
                    let d = glyph_path(f, gid);
                    if !d.is_empty() {
                        self.glyphs.insert(key, d);
                    }
                }
                if self.glyphs.contains_key(&key) {
                    any = true;
                    g.push_str(&format!(
                        "{}  <use href=\"#lini-g{}{}-{}\" transform=\"translate({} {}){} scale({} {})\"/>\n",
                        ind,
                        fd,
                        weight,
                        gid,
                        f4(pen),
                        f4(*base),
                        if st.italic { " skewX(-12)" } else { "" },
                        f4(s),
                        f4(-s)
                    ));
                }
                pen += font::outline_advance(f, fam, *c) / f.upem * size;
            }
            let deco = st.decoration.trim();
            let (pos, thk) = match deco {
                "underline" => (upos, uthk),
                "line-through" => (spos, ssize),
                _ => (f64::NAN, 0.0),
            };
            if !pos.is_nan() {
                g.push_str(&format!(
                    "{}  <rect x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\"/>\n",
                    ind,
                    f4(start),
                    f4(base - (pos + thk / 2.0) * s),
                    f4(width),
                    f4(thk * s)
                ));
            }
        }
        g.push_str(&format!("{}</g>", ind));
        if any {
            // the face's .notdef rides along with any glyph drawn from it
            let k0 = (fd, weight, 0u16);
            if !self.glyphs.contains_key(&k0) {
                self.glyphs.insert(k0, glyph_path(f, 0));
            }
        }
        Some(g)
    }

    // --static compares inline styles with their rules once both are baked:
    // a declaration that now repeats its rule is dropped.
    pub fn dedup(&self, body: &str) -> String {
        let mut out = String::with_capacity(body.len());
        let mut stack: Vec<(String, Vec<String>)> = Vec::new();
        let mut i = 0;
        while i < body.len() {
            let lt = match body[i..].find('<') {
                Some(p) => i + p,
                None => {
                    out.push_str(&body[i..]);
                    break;
                }
            };
            out.push_str(&body[i..lt]);
            let gt = match body[lt..].find('>') {
                Some(p) => lt + p,
                None => {
                    out.push_str(&body[lt..]);
                    break;
                }
            };
            let tag = &body[lt + 1..gt];
            i = gt + 1;
            if let Some(name) = tag.strip_prefix('/') {
                let name = name.trim();
                if let Some(pos) = stack.iter().rposition(|e| e.0 == name) {
                    stack.truncate(pos);
                }
                out.push_str(&body[lt..=gt]);
                continue;
            }
            let self_close = tag.ends_with('/');
            let inner = tag.trim_end_matches('/');
            let (name, rest) = match inner.find(char::is_whitespace) {
                Some(p) => (&inner[..p], &inner[p..]),
                None => (inner, ""),
            };
            let attrs = parse_attrs(rest);
            let classes: Vec<String> = attr(&attrs, "class").map(|c| c.split_whitespace().map(|s| s.to_string()).collect()).unwrap_or_default();
            let anc: Vec<Vec<String>> = stack.iter().map(|e| e.1.clone()).collect();
            let mut text = body[lt..=gt].to_string();
            if let Some(style) = attr(&attrs, "style") {
                if !classes.is_empty() {
                    let decls = parse_decls(&unescape(style));
                    let kept: Vec<String> = decls
                        .iter()
                        .filter(|(k, v)| match self.sheet.rule_value(k, &classes, &anc) {
                            // (equal only once a variable on either side is baked)
                            Some(r) if r.contains("var(") || v.contains("var(") => self.vars.bake(&r) != self.vars.bake(v),
                            _ => true,
                        })
                        .map(|(k, v)| format!("{}: {}", k, v))
                        .collect();
                    let old_attr = format!(" style=\"{}\"", style);
                    let new_attr = if kept.is_empty() { String::new() } else { format!(" style=\"{}\"", crate::util::xml_escape(&kept.join("; "))) };
                    text = text.replacen(&old_attr, &new_attr, 1);
                }
            }
            if !self_close {
                stack.push((name.to_string(), classes));
            }
            out.push_str(&text);
        }
        out
    }

    pub fn glyph_defs(&self) -> Vec<String> {
        self.glyphs.iter().map(|((fd, w, gid), d)| format!("<path id=\"lini-g{}{}-{}\" d=\"{}\"/>", fd, w, gid, d)).collect()
    }

    // `@font-face` lines for every face the text used.
    pub fn font_faces(&self) -> String {
        let mut s = String::new();
        for &(fd, w) in &self.used {
            let (fam, name) = if fd == 0 { (Family::Code, "Lini Sans Code") } else { (Family::Sans, "Lini Sans") };
            s.push_str(&format!(
                "    @font-face {{ font-family: \"{}\"; font-weight: {}; src: url(data:font/ttf;base64,{}) format(\"truetype\"); }}\n",
                name,
                w,
                base64(font::font_bytes(fam, w))
            ));
        }
        s
    }
}

// The first family of a font-family list, unquoted.
fn first_family(v: &str) -> &str {
    let first = v.split(',').next().unwrap_or("").trim();
    first.trim_matches('"').trim_matches('\'')
}

// --static drops the charts' hover tooltips: the tip groups, the `lini-hit-N`
// classes that trigger them, and their stylesheet rules.
pub fn drop_tips_css(css: &str) -> String {
    css.split_inclusive('\n').filter(|l| !(l.contains(".lini-chart-tip {") || (l.contains(":hover ~ .lini-tip-")))).collect()
}

pub fn drop_tips(body: &str) -> String {
    if !body.contains("lini-chart-tip") && !body.contains("lini-hit-") {
        return body.to_string();
    }
    let mut out = String::with_capacity(body.len());
    let mut rest = body;
    // whole tip groups (their own line through the matching </g>)
    while let Some(p) = rest.find("<g class=\"lini-node lini-chart-tip") {
        let line_start = rest[..p].rfind('\n').map(|q| q + 1).unwrap_or(0);
        out.push_str(&rest[..line_start]);
        let mut depth = 0usize;
        let mut i = p;
        let mut end = rest.len();
        while i < rest.len() {
            let next_open = rest[i..].find("<g").map(|q| i + q);
            let next_close = rest[i..].find("</g>").map(|q| i + q);
            match (next_open, next_close) {
                (Some(o), Some(c)) if o < c => {
                    let gt = rest[o..].find('>').map(|q| o + q).unwrap_or(rest.len() - 1);
                    if !rest[o..=gt].ends_with("/>") {
                        depth += 1;
                    }
                    i = gt + 1;
                }
                (_, Some(c)) => {
                    depth = depth.saturating_sub(1);
                    i = c + 4;
                    if depth == 0 {
                        end = i;
                        break;
                    }
                }
                _ => break,
            }
        }
        rest = &rest[end..];
        if rest.starts_with('\n') {
            rest = &rest[1..];
        }
    }
    out.push_str(rest);
    // the hover triggers
    let mut o2 = String::with_capacity(out.len());
    let mut r = out.as_str();
    while let Some(p) = r.find(" lini-hit-") {
        let digits = r[p + 10..].chars().take_while(|c| c.is_ascii_digit()).count();
        if digits == 0 {
            o2.push_str(&r[..p + 10]);
            r = &r[p + 10..];
            continue;
        }
        o2.push_str(&r[..p]);
        r = &r[p + 10 + digits..];
    }
    o2.push_str(r);
    o2
}

// Drop the `@layer lini.defaults { … }` block (--static has no live vars).
pub fn drop_layer(css: &str) -> String {
    let mut out = String::new();
    let mut in_layer = false;
    for line in css.split_inclusive('\n') {
        if line.trim_start().starts_with("@layer") {
            in_layer = true;
            continue;
        }
        if in_layer {
            if line == "    }\n" {
                in_layer = false;
            }
            continue;
        }
        out.push_str(line);
    }
    out
}

// --static gradient stops carry their colour as an attribute.
pub fn stops_to_attrs(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut rest = s;
    let pat = " style=\"stop-color: ";
    while let Some(p) = rest.find(pat) {
        out.push_str(&rest[..p]);
        let after = &rest[p + pat.len()..];
        // the colour runs to the attribute's closing quote before '/>'
        match after.find("\"/>") {
            Some(e) => {
                out.push_str(&format!(" stop-color=\"{}\"/>", &after[..e]));
                rest = &after[e + 3..];
            }
            None => {
                out.push_str(&rest[p..]);
                rest = "";
            }
        }
    }
    out.push_str(rest);
    out
}
