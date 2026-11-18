// The desugared document and its printer. The layout rules are the canonical
// ones of `lini fmt` (80 columns, 2-space indent, inline `{ }` / `[ ]` when
// they fit, aligned rows for bare cells, `draw:` subpaths on their own lines),
// except that a link's labels always stay in its `[ ]`.

use super::syntax::Decl;
use crate::format::parse::render_string;

pub const WIDTH: usize = 80;

#[derive(Clone, Debug)]
pub struct ONode {
    pub prim: String,
    pub id: Option<String>,
    pub label: Option<String>, // decoded; kept inline (lines, paths, images)
    pub classes: Vec<String>,  // without the dots
    pub decls: Vec<Decl>,
    pub children: Vec<Item>,
    // declared by a link (an auto-created endpoint or a capsule)
    pub gen: bool,
    // the label text: first when the children print as bare text, else at
    // this position (after the define bodies)
    pub text_label: Option<(String, usize)>,
}

impl ONode {
    pub fn new(prim: &str) -> ONode {
        ONode {
            prim: prim.to_string(),
            id: None,
            label: None,
            classes: vec![],
            decls: vec![],
            children: vec![],
            gen: false,
            text_label: None,
        }
    }
    pub fn decl(&self, name: &str) -> Option<&Decl> {
        self.decls.iter().rev().find(|d| d.name == name)
    }
}

#[derive(Clone, Debug)]
pub struct OText {
    pub text: String, // decoded
    pub classes: Vec<String>,
    pub decls: Vec<Decl>,
}

#[derive(Clone, Debug)]
pub struct OLink {
    pub head: String,
    pub classes: Vec<String>,
    pub decls: Vec<Decl>,
    pub labels: Vec<Item>,
}

#[derive(Clone, Debug)]
pub enum Item {
    Node(ONode),
    Text(OText),
    Link(OLink),
}

impl Item {
    pub fn text(s: &str) -> Item {
        Item::Text(OText { text: s.to_string(), classes: vec![], decls: vec![] })
    }
}

pub enum SheetLine {
    Decls(Vec<Decl>),       // printed on one line
    Line(String),           // a variable or a binding
    Rule(String, Vec<Decl>), // selector { decls }
}

fn pad(n: usize) -> String {
    " ".repeat(n)
}

fn is_move(t: &str) -> bool {
    t.starts_with("move(") && t.ends_with(')')
}

fn classes_text(cs: &[String]) -> String {
    cs.iter().map(|c| format!(".{}", c)).collect::<String>()
}

// grid tracks a `columns:` value stands for (repeat(n, …) counts n)
fn tracks(d: &Decl) -> i64 {
    let mut n: i64 = 0;
    for t in d.groups.iter().flatten() {
        let mut k: i64 = 1;
        if let Some(rest) = t.strip_prefix("repeat(") {
            let first = rest.split(|c| c == ',' || c == ')').next().unwrap_or("").trim();
            if let Ok(v) = first.parse::<f64>() {
                if v.is_nan() || v < 1.0 {
                    k = 1;
                } else if v.is_infinite() || v > 1e15 {
                    k = 1_000_000_000_000_000;
                } else {
                    k = v.trunc() as i64;
                }
            }
        }
        n = n.saturating_add(k);
    }
    n
}

pub struct Printer {
    lines: Vec<String>,
}

impl Printer {
    pub fn new() -> Self {
        Printer { lines: Vec::new() }
    }

    pub fn finish(self) -> String {
        if self.lines.is_empty() {
            return String::new();
        }
        let mut s = self.lines.join("\n");
        s.push('\n');
        s
    }

    fn line(&mut self, indent: usize, text: &str) {
        self.lines.push(format!("{}{}", pad(indent), text));
    }

    pub fn doc(&mut self, sheet: &[SheetLine], items: &[Item]) {
        let mut sheet_printed = false;
        if !sheet.is_empty() {
            self.line(0, "{");
            for l in sheet {
                match l {
                    SheetLine::Decls(ds) => {
                        let mut run: Vec<String> = Vec::new();
                        for d in ds {
                            if d.is_draw() {
                                if !run.is_empty() {
                                    self.line(2, &run.join(" "));
                                    run.clear();
                                }
                                self.draw(2, d);
                            } else {
                                run.push(d.text());
                            }
                        }
                        if !run.is_empty() {
                            self.line(2, &run.join(" "));
                        }
                    }
                    SheetLine::Line(s) => self.line(2, s),
                    SheetLine::Rule(sel, ds) => {
                        if ds.is_empty() {
                            self.line(2, &format!("{} {{}}", sel));
                        } else {
                            self.composite(2, sel.clone(), ds, Kids::None);
                        }
                    }
                }
            }
            self.line(0, "}");
            sheet_printed = true;
        }
        // a node a link declared stands with the links
        let last_non_link = items.iter().rposition(|e| !matches!(e, Item::Link(_)));
        let first_link = items.iter().position(|e| matches!(e, Item::Link(_)) || matches!(e, Item::Node(n) if n.gen));
        let link_break = match (last_non_link, first_link) {
            (Some(n), Some(l)) if l > n => Some(l),
            _ => None,
        };
        for (i, e) in items.iter().enumerate() {
            if (i == 0 && sheet_printed) || Some(i) == link_break {
                self.lines.push(String::new());
            }
            self.item(e, 0);
        }
    }

    fn draw(&mut self, indent: usize, d: &Decl) {
        let prefix = format!("{}: ", d.name);
        let col = indent + prefix.len();
        let pieces: Vec<&String> = d.groups.iter().flatten().collect();
        if pieces.is_empty() {
            self.line(indent, &format!("{} ;", prefix.trim_end()));
            return;
        }
        let mut cur = format!("{}{}{}", pad(indent), prefix, pieces[0]);
        for p in pieces.iter().skip(1) {
            if is_move(p) || cur.len() + 1 + p.len() + 1 > WIDTH {
                self.lines.push(cur);
                cur = format!("{}{}", pad(col), p);
            } else {
                cur.push(' ');
                cur.push_str(p);
            }
        }
        cur.push(';');
        self.lines.push(cur);
    }

    fn decls(&mut self, ds: &[Decl], indent: usize) {
        let mut run: Vec<String> = Vec::new();
        for d in ds {
            if d.is_draw() {
                if !run.is_empty() {
                    self.line(indent, &run.join(" "));
                    run.clear();
                }
                self.draw(indent, d);
            } else {
                run.push(d.text());
            }
        }
        if !run.is_empty() {
            self.line(indent, &run.join(" "));
        }
    }

    fn style_inline(ds: &[Decl]) -> Option<String> {
        if ds.iter().any(|d| d.is_draw() && d.groups.iter().flatten().filter(|t| is_move(t)).count() >= 2) {
            return None;
        }
        let parts: Vec<String> = ds.iter().map(|d| d.text()).collect();
        Some(format!("{{ {} }}", parts.join(" ")))
    }

    fn composite(&mut self, indent: usize, prefix: String, style: &[Decl], kids: Kids) {
        let mut cur = prefix;
        if !style.is_empty() {
            let inline = Self::style_inline(style).map(|s| format!("{} {}", cur, s));
            match inline {
                Some(l) if indent + l.len() <= WIDTH => cur = l,
                _ => {
                    self.line(indent, &format!("{} {{", cur));
                    self.decls(style, indent + 2);
                    cur = "}".to_string();
                }
            }
        }
        match kids {
            Kids::None => self.line(indent, &cur),
            Kids::Items(b, cols) => self.children(indent, cur, b, cols),
        }
    }

    fn children(&mut self, indent: usize, cur: String, b: &[Item], cols: Option<i64>) {
        let texts: Option<Vec<&OText>> = b
            .iter()
            .map(|e| match e {
                Item::Text(t) => Some(t),
                _ => None,
            })
            .collect();
        if let Some(texts) = texts {
            if let Some(n) = cols {
                self.line(indent, &format!("{} [", cur));
                self.rows(&texts, n, indent + 2);
                self.line(indent, "]");
                return;
            } else if texts.iter().all(|t| t.classes.is_empty() && t.decls.is_empty()) {
                let items: Vec<String> = texts.iter().map(|t| render_string(&t.text)).collect();
                let l = format!("{} [ {} ]", cur, items.join(" "));
                if indent + l.len() <= WIDTH {
                    self.line(indent, &l);
                    return;
                }
            }
        }
        self.line(indent, &format!("{} [", cur));
        for e in b {
            self.item(e, indent + 2);
        }
        self.line(indent, "]");
    }

    // would `prefix { style } [ "a" "b" ]` print on one line?
    fn fits_inline(&self, indent: usize, prefix: &str, style: &[Decl], kids: &[Item]) -> bool {
        let mut cur = prefix.to_string();
        if !style.is_empty() {
            match Self::style_inline(style).map(|s| format!("{} {}", cur, s)) {
                Some(l) if indent + l.len() <= WIDTH => cur = l,
                _ => cur = "}".to_string(),
            }
        }
        let items: Vec<String> = kids
            .iter()
            .map(|e| match e {
                Item::Text(t) => render_string(&t.text),
                _ => String::new(),
            })
            .collect();
        let l = format!("{} [ {} ]", cur, items.join(" "));
        indent + l.len() <= WIDTH
    }

    fn rows(&mut self, texts: &[&OText], n: i64, indent: usize) {
        let n = if n < 1 { 1 } else { n.min(1_000_000) as usize };
        let rendered: Vec<String> = texts.iter().map(|t| render_string(&t.text)).collect();
        let idx: Vec<usize> = (0..texts.len()).collect();
        let rows: Vec<&[usize]> = idx.chunks(n).collect();
        let lifted = |r: &[usize]| r.iter().any(|&i| !texts[i].classes.is_empty() || !texts[i].decls.is_empty());
        let mut widths = vec![0usize; n.min(texts.len().max(1))];
        for r in &rows {
            if lifted(r) {
                continue;
            }
            for (c, &i) in r.iter().enumerate() {
                widths[c] = widths[c].max(rendered[i].len());
            }
        }
        for r in &rows {
            if lifted(r) {
                let mut cur = String::new();
                for (c, &i) in r.iter().enumerate() {
                    let t = texts[i];
                    if c > 0 {
                        cur.push(' ');
                    }
                    cur.push_str(&rendered[i]);
                    if !t.classes.is_empty() {
                        cur.push(' ');
                        cur.push_str(&classes_text(&t.classes));
                    }
                    if !t.decls.is_empty() {
                        match Self::style_inline(&t.decls) {
                            Some(s) if indent + cur.len() + 1 + s.len() <= WIDTH => {
                                cur.push(' ');
                                cur.push_str(&s);
                            }
                            _ => {
                                self.line(indent, &format!("{} {{", cur));
                                self.decls(&t.decls, indent + 2);
                                cur = "}".to_string();
                            }
                        }
                    }
                }
                self.line(indent, &cur);
                continue;
            }
            let mut s = String::new();
            let last = r.len() - 1;
            for (c, &i) in r.iter().enumerate() {
                s.push_str(&rendered[i]);
                if c < last {
                    s.push_str(&pad(widths[c] - rendered[i].len() + 1));
                }
            }
            self.line(indent, &s);
        }
    }

    fn item(&mut self, s: &Item, indent: usize) {
        match s {
            Item::Node(n) => {
                let mut prefix = String::from("|");
                prefix.push_str(&n.prim);
                if let Some(id) = &n.id {
                    prefix.push('#');
                    prefix.push_str(id);
                }
                prefix.push('|');
                if let Some(l) = &n.label {
                    prefix.push(' ');
                    prefix.push_str(&render_string(l));
                }
                if !n.classes.is_empty() {
                    prefix.push(' ');
                    prefix.push_str(&classes_text(&n.classes));
                }
                let cols = n.decl("columns").map(tracks);
                match &n.text_label {
                    Some((l, at)) => {
                        // bare text keeps the label first; a block of
                        // children has it after the define bodies
                        let mut first = vec![Item::text(l)];
                        first.extend(n.children.iter().cloned());
                        let all_text = first.iter().all(|e| matches!(e, Item::Text(_)));
                        let plain = first.iter().all(|e| matches!(e, Item::Text(t) if t.classes.is_empty() && t.decls.is_empty()));
                        let fits = |me: &Self| -> bool {
                            let _ = me;
                            true
                        };
                        let _ = fits;
                        let use_first = all_text && (cols.is_some() || (plain && self.fits_inline(indent, &prefix, &n.decls, &first)));
                        let list = if use_first {
                            first
                        } else {
                            let mut v = n.children.clone();
                            let k = (*at).min(v.len());
                            v.insert(k, Item::text(l));
                            v
                        };
                        self.composite(indent, prefix, &n.decls, Kids::Items(&list, cols));
                    }
                    None => {
                        let kids = if n.children.is_empty() { Kids::None } else { Kids::Items(&n.children, cols) };
                        self.composite(indent, prefix, &n.decls, kids);
                    }
                }
            }
            Item::Text(t) => {
                let mut prefix = render_string(&t.text);
                if !t.classes.is_empty() {
                    prefix.push(' ');
                    prefix.push_str(&classes_text(&t.classes));
                }
                self.composite(indent, prefix, &t.decls, Kids::None);
            }
            Item::Link(l) => {
                let mut prefix = l.head.clone();
                if !l.classes.is_empty() {
                    prefix.push(' ');
                    prefix.push_str(&classes_text(&l.classes));
                }
                let kids = if l.labels.is_empty() { Kids::None } else { Kids::Items(&l.labels, None) };
                self.composite(indent, prefix, &l.decls, kids);
            }
        }
    }
}

enum Kids<'a> {
    None,
    Items(&'a [Item], Option<i64>),
}
