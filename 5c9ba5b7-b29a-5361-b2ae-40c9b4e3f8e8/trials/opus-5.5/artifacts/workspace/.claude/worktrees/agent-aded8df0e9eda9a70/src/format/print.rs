// The canonical printer: walks the concrete tree and lays it out line by line.

use super::cst::*;

pub const WIDTH: usize = 80;

pub struct Out {
    lines: Vec<String>,
    types: Option<std::collections::HashMap<String, String>>,
    // a blank line waits for the next line of its own; trailing comments
    // that come first still attach to the line above it
    pending_blank: bool,
}

fn pad(n: usize) -> String {
    " ".repeat(n)
}

// an untagged `move(…)` command opens a new subpath
fn is_move(t: &str) -> bool {
    t.starts_with("move(") && t.ends_with(')')
}

impl Out {
    pub fn new() -> Self {
        Out { lines: Vec::new(), pending_blank: false, types: None }
    }

    pub fn finish(mut self) -> String {
        self.flush_blank();
        if self.lines.is_empty() {
            return String::new();
        }
        let mut s = self.lines.join("\n");
        s.push('\n');
        s
    }

    fn flush_blank(&mut self) {
        if self.pending_blank {
            self.pending_blank = false;
            if !self.lines.is_empty() {
                self.lines.push(String::new());
            }
        }
    }

    fn push(&mut self, s: String) {
        self.flush_blank();
        self.lines.push(s);
    }

    fn line(&mut self, indent: usize, text: &str) {
        self.push(format!("{}{}", pad(indent), text));
    }

    fn blank(&mut self) {
        if !self.lines.is_empty() {
            self.pending_blank = true;
        }
    }

    fn trail(&mut self, indent: usize, c: &str) {
        match self.lines.last_mut() {
            Some(l) => {
                l.push_str("  ");
                l.push_str(c);
            }
            None => self.line(indent, c),
        }
    }

    fn trivia(&mut self, indent: usize, ts: &[Triv]) {
        for t in ts {
            match t {
                Triv::Blank => self.blank(),
                Triv::Comment { text, own: true } => self.line(indent, text),
                Triv::Comment { text, own: false } => self.trail(indent, text),
            }
        }
    }

    // ------------------------------------------------------------- document
    // grid columns a node's bare strings fill: its own `columns:`, else the
    // built-in default of its type (entity: 2), followed through defines
    fn node_columns(&self, n: &Node) -> Option<i64> {
        if n.columns.is_some() {
            return n.columns;
        }
        let types = self.types.as_ref()?;
        let mut t: &str = n.ty.as_deref()?;
        for _ in 0..64 {
            if t == "entity" {
                return Some(2);
            }
            t = types.get(t)?;
        }
        None
    }

    pub fn doc(&mut self, d: &Doc) {
        self.types = d.types.clone();
        let mut sheet_printed = false;
        if let Some(sheet) = &d.sheet {
            self.trivia(0, &d.sheet_lead);
            if sheet.entries.is_empty() {
                self.trivia(0, &sheet.close);
            } else {
                self.line(0, "{");
                self.sheet_items(sheet, 2);
                self.line(0, "}");
                sheet_printed = true;
            }
        }
        let entries = &d.stmts.entries;
        // when every link follows every node, a blank line sets the links off
        let last_non_link = entries.iter().rposition(|e| !matches!(e.item, Stmt::Link(_)));
        let first_link = entries.iter().position(|e| matches!(e.item, Stmt::Link(_)));
        let link_break = match (last_non_link, first_link) {
            (Some(n), Some(l)) if l > n => Some(l),
            _ => None,
        };
        for (i, e) in entries.iter().enumerate() {
            if (i == 0 && sheet_printed) || Some(i) == link_break {
                self.blank();
            }
            self.trivia(0, &e.lead);
            self.stmt(&e.item, 0);
        }
        self.trivia(0, &d.stmts.close);
    }

    // ---------------------------------------------------------------- sheet
    fn sheet_items(&mut self, b: &Block<SheetItem>, indent: usize) {
        let es = &b.entries;
        let mut i = 0;
        while i < es.len() {
            let e = &es[i];
            self.trivia(indent, &e.lead);
            match &e.item {
                SheetItem::Decl(d) if !d.draw => {
                    let mut j = i;
                    while j + 1 < es.len()
                        && es[j + 1].lead.is_empty()
                        && matches!(&es[j + 1].item, SheetItem::Decl(d2) if !d2.draw)
                    {
                        j += 1;
                    }
                    let text: Vec<String> = es[i..=j]
                        .iter()
                        .map(|x| match &x.item {
                            SheetItem::Decl(d) => d.text(),
                            _ => unreachable!(),
                        })
                        .collect();
                    self.line(indent, &text.join(" "));
                    i = j + 1;
                    continue;
                }
                SheetItem::Decl(d) => self.draw(indent, d),
                SheetItem::Var(d) => self.line(indent, &d.text()),
                SheetItem::Binding(s) => self.line(indent, s),
                SheetItem::Rule { selector, block } => {
                    if block.entries.is_empty() {
                        // an empty rule keeps its braces — unless a comment
                        // sat in them
                        if block.any_comment {
                            self.line(indent, selector);
                        } else {
                            self.line(indent, &format!("{} {{}}", selector));
                        }
                    } else {
                        self.composite(indent, selector.clone(), Some(block), Kids::None);
                    }
                }
                SheetItem::Define { head, style, body } => {
                    let kids = match body {
                        Some(b) => Kids::Define(b),
                        None => Kids::None,
                    };
                    self.composite(indent, head.clone(), style.as_ref(), kids);
                }
            }
            i += 1;
        }
        self.trivia(indent, &b.close);
    }

    // `draw:` on its own line(s): every subpath (`move(…)`) starts a line,
    // long runs wrap under the first command; commas are dropped.
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
            // one column stays free for the ';' or the next separator
            if is_move(p) || cur.len() + 1 + p.len() + 1 > WIDTH {
                self.push(cur);
                cur = format!("{}{}", pad(col), p);
            } else {
                cur.push(' ');
                cur.push_str(p);
            }
        }
        cur.push(';');
        self.push(cur);
    }

    fn decls(&mut self, b: &Block<Decl>, indent: usize) {
        let es = &b.entries;
        let mut i = 0;
        while i < es.len() {
            let e = &es[i];
            self.trivia(indent, &e.lead);
            if e.item.draw {
                self.draw(indent, &e.item);
                i += 1;
                continue;
            }
            let mut j = i;
            while j + 1 < es.len() && es[j + 1].lead.is_empty() && !es[j + 1].item.draw {
                j += 1;
            }
            let text: Vec<String> = es[i..=j].iter().map(|x| x.item.text()).collect();
            self.line(indent, &text.join(" "));
            i = j + 1;
        }
        self.trivia(indent, &b.close);
    }

    fn style_inline(b: &Block<Decl>) -> Option<String> {
        if b.any_trivia {
            return None;
        }
        // a drawing with several subpaths never fits one line
        if b.entries.iter().any(|e| e.item.draw && e.item.groups.iter().flatten().filter(|t| is_move(t)).count() >= 2) {
            return None;
        }
        let parts: Vec<String> = b.entries.iter().map(|e| e.item.text()).collect();
        Some(format!("{{ {} }}", parts.join(" ")))
    }

    // `prefix { style } [ kids ]`
    fn composite(&mut self, indent: usize, prefix: String, style: Option<&Block<Decl>>, kids: Kids) {
        let mut cur = prefix;
        if let Some(b) = style {
            let inline = Self::style_inline(b).map(|s| format!("{} {}", cur, s));
            match inline {
                Some(l) if indent + l.len() <= WIDTH => cur = l,
                _ => {
                    self.line(indent, &format!("{} {{", cur));
                    self.decls(b, indent + 2);
                    cur = "}".to_string();
                }
            }
        }
        match kids {
            Kids::None => self.line(indent, &cur),
            Kids::Define(b) => {
                self.line(indent, &format!("{} [", cur));
                self.stmt_entries(b, indent + 2);
                self.line(indent, "]");
            }
            Kids::Node(b, cols) => self.children(indent, cur, b, cols),
            Kids::Labels(b) => self.children(indent, cur, b, None),
        }
    }

    fn plain_texts<'b>(b: &'b Block<Stmt>) -> Option<Vec<&'b Text>> {
        let mut v = Vec::new();
        for e in &b.entries {
            match &e.item {
                Stmt::Text(t) => v.push(t),
                _ => return None,
            }
        }
        Some(v)
    }

    fn children(&mut self, indent: usize, cur: String, b: &Block<Stmt>, cols: Option<i64>) {
        if let Some(texts) = Self::plain_texts(b) {
            if let Some(n) = cols {
                if !b.trivia_among {
                    // rows: what precedes the first cell is dropped
                    self.line(indent, &format!("{} [", cur));
                    self.rows(&texts, n, indent + 2);
                    self.trivia(indent + 2, &b.close);
                    self.line(indent, "]");
                    return;
                }
            } else if !b.any_trivia && texts.iter().all(|t| t.classes.is_empty() && t.style.is_none()) {
                let items: Vec<&str> = texts.iter().map(|t| t.text.as_str()).collect();
                let l = format!("{} [ {} ]", cur, items.join(" "));
                if indent + l.len() <= WIDTH {
                    self.line(indent, &l);
                    return;
                }
            }
        }
        self.line(indent, &format!("{} [", cur));
        self.stmt_entries(b, indent + 2);
        self.line(indent, "]");
    }

    fn rows(&mut self, texts: &[&Text], n: i64, indent: usize) {
        let n = if n < 1 { 1 } else { n.min(1_000_000) as usize };
        let rows: Vec<&[&Text]> = texts.chunks(n).collect();
        let lifted = |r: &[&Text]| r.iter().any(|t| !t.classes.is_empty() || t.style.is_some());
        let mut widths = vec![0usize; n.min(texts.len().max(1))];
        for r in &rows {
            if lifted(r) {
                continue;
            }
            for (c, t) in r.iter().enumerate() {
                widths[c] = widths[c].max(t.text.len());
            }
        }
        for r in &rows {
            if lifted(r) {
                // cells follow one another; a style that will not fit opens
                // up and the row continues after its '}'
                let mut cur = String::new();
                for (c, t) in r.iter().enumerate() {
                    if c > 0 {
                        cur.push(' ');
                    }
                    cur.push_str(&t.text);
                    if !t.classes.is_empty() {
                        cur.push(' ');
                        cur.push_str(&t.classes);
                    }
                    if let Some(st) = &t.style {
                        match Self::style_inline(st) {
                            Some(s) if indent + cur.len() + 1 + s.len() <= WIDTH => {
                                cur.push(' ');
                                cur.push_str(&s);
                            }
                            _ => {
                                self.line(indent, &format!("{} {{", cur));
                                self.decls(st, indent + 2);
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
            for (c, t) in r.iter().enumerate() {
                s.push_str(&t.text);
                if c < last {
                    s.push_str(&pad(widths[c] - t.text.len() + 1));
                }
            }
            self.line(indent, &s);
        }
    }

    fn stmt_entries(&mut self, b: &Block<Stmt>, indent: usize) {
        for e in &b.entries {
            self.trivia(indent, &e.lead);
            self.stmt(&e.item, indent);
        }
        self.trivia(indent, &b.close);
    }

    fn stmt(&mut self, s: &Stmt, indent: usize) {
        match s {
            Stmt::Node(n) => {
                let mut prefix = n.head.clone();
                if let Some(l) = &n.label {
                    prefix.push(' ');
                    prefix.push_str(l);
                }
                if !n.classes.is_empty() {
                    prefix.push(' ');
                    prefix.push_str(&n.classes);
                }
                let kids = match &n.children {
                    Some(b) => Kids::Node(b, self.node_columns(n)),
                    None => Kids::None,
                };
                self.composite(indent, prefix, n.style.as_ref(), kids);
            }
            Stmt::Text(t) => {
                let mut prefix = t.text.clone();
                if !t.classes.is_empty() {
                    prefix.push(' ');
                    prefix.push_str(&t.classes);
                }
                self.composite(indent, prefix, t.style.as_ref(), Kids::None);
            }
            Stmt::Link(l) => {
                let mut prefix = l.head.clone();
                let single = l.labels.entries.len() == 1 && !l.has_comment;
                let mut kids = Kids::None;
                match l.labels.entries.first().map(|e| &e.item) {
                    Some(Stmt::Text(t)) if single && t.style.is_none() => {
                        prefix.push(' ');
                        prefix.push_str(&t.text);
                        if !t.classes.is_empty() {
                            prefix.push(' ');
                            prefix.push_str(&t.classes);
                        }
                    }
                    Some(_) => kids = Kids::Labels(&l.labels),
                    None => {}
                }
                if !l.classes.is_empty() {
                    prefix.push(' ');
                    prefix.push_str(&l.classes);
                }
                self.composite(indent, prefix, l.style.as_ref(), kids);
            }
        }
    }
}

enum Kids<'a> {
    None,
    Define(&'a Block<Stmt>),
    Node(&'a Block<Stmt>, Option<i64>),
    Labels(&'a Block<Stmt>),
}
