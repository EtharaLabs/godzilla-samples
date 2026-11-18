// YAML emitter: re-renders parsed nodes with normalized layout, copying trivia verbatim.

use super::parser::*;
use super::scalar::*;
use crate::options::Options;
use crate::template::contains_template;

#[derive(Default, Debug, Clone)]
pub struct Stats {
    pub scalars: usize,
    pub flows: usize,
    pub block_flows: usize,
    pub emitted_nodes: usize,
}

pub struct Emitter<'a> {
    pub stats: Stats,
    /// Line of the first entry of a mapping written on the dash line of a
    /// sequence's first item.
    compact_first_line: Option<usize>,
    /// The mapping about to be written on a dash line belongs to the first item.
    first_item: bool,
    /// Whether the last emitted value counts as an emitted node.
    value_counted: bool,
    /// Source column minus output column of the current block context (layout
    /// decisions are measured at the authored indentation).
    col_delta: isize,
    /// `fmt: off` .. `fmt: on` line ranges.
    pub off_regions: Vec<(usize, usize)>,
    /// Lines of `fmt: skip` directives and those already applied.
    pub skip_lines: Vec<usize>,
    pub used_skips: Vec<usize>,
    /// `fmt: markdown` directives (line, options), option-only directives, and
    /// embedded formatter directives; each applies to the next scalar.
    pub md_dirs: Vec<(usize, Vec<String>)>,
    pub opt_dirs: Vec<(usize, Vec<String>)>,
    pub emb_dirs: Vec<(usize, String)>,
    used_dirs: Vec<usize>,
    /// Block sequences aligned as tables (keyed by node start; true collapses block rows).
    pub table_targets: std::collections::HashMap<usize, bool>,
    /// Compaction chosen for single collections, and scoped compaction directives.
    pub compact_override: std::collections::HashMap<usize, bool>,
    pub compact_scoped: Vec<(usize, bool, super::directive::Scope)>,
    root_compact_ok: bool,
    pub error: Option<crate::format_cmd::Diagnostic>,
    pub notes: Vec<crate::format_cmd::Diagnostic>,
    embedded_target: bool,
    pub src: &'a str,
    lines: Vec<&'a str>,
    kinds: Vec<LineKind>,
    line_starts: Vec<usize>,
    cursor: usize,
    pub out: Vec<String>,
    opts: &'a Options,
}

enum Rendered {
    Inline(String),
    Block(String, Vec<String>),
    /// Header plus source block lines re-indented from `ci`; trailing blank lines included.
    Raw(String, Vec<String>, usize),
    /// Header, refilled lines, then raw trailing lines re-indented from `ci`.
    Refilled(String, Vec<String>, Vec<String>, usize),
}

fn is_block_coll(n: &Node) -> bool {
    matches!(n.kind, Kind::Map(_) | Kind::Seq(_))
}

impl<'a> Emitter<'a> {
    pub fn new(src: &'a str, kinds: Vec<LineKind>, line_starts: Vec<usize>, opts: &'a Options) -> Self {
        let mut lines: Vec<&str> = src.split('\n').collect();
        if src.ends_with('\n') {
            lines.pop();
        }
        Emitter { stats: Stats::default(), compact_first_line: None, first_item: false, value_counted: true, col_delta: 0, off_regions: Vec::new(), skip_lines: Vec::new(), used_skips: Vec::new(), md_dirs: Vec::new(), opt_dirs: Vec::new(), emb_dirs: Vec::new(), used_dirs: Vec::new(), table_targets: Default::default(), compact_override: Default::default(), compact_scoped: Vec::new(), root_compact_ok: true, error: None, notes: Vec::new(), embedded_target: false, src, lines, kinds, line_starts, cursor: 0, out: Vec::new(), opts }
    }

    fn line_of(&self, pos: usize) -> usize {
        match self.line_starts.binary_search(&pos) {
            Ok(i) => i,
            Err(i) => i - 1,
        }
    }

    fn line_end_pos(&self, line: usize) -> usize {
        self.line_starts[line] + self.lines[line].len()
    }

    fn in_off_region(&self, line: usize) -> bool {
        self.off_regions.iter().any(|&(a, b)| line > a && line < b)
    }

    /// Consume a pending `fmt: skip` directive located before `line`.
    fn take_skip_before(&mut self, line: usize) -> bool {
        let pending: Vec<usize> = self.skip_lines.iter().copied().filter(|l| *l < line && !self.used_skips.contains(l)).collect();
        if pending.is_empty() {
            return false;
        }
        self.used_skips.extend(pending);
        true
    }

    /// Emit full source lines `a..=b` verbatim.
    fn emit_lines_verbatim(&mut self, a: usize, b: usize) {
        self.flush_to(a);
        for l in a..=b {
            let t = self.lines[l].to_string();
            self.push_line(t);
        }
        self.consume_through(b);
    }

    fn flush_to(&mut self, line: usize) {
        while self.cursor < line && self.cursor < self.lines.len() {
            if self.kinds[self.cursor] != LineKind::Content {
                self.out.push(self.lines[self.cursor].to_string());
            }
            self.cursor += 1;
        }
    }

    fn consume_through(&mut self, line: usize) {
        if line + 1 > self.cursor {
            self.cursor = line + 1;
        }
    }

    fn push_line(&mut self, s: String) {
        self.out.push(s);
    }

    fn append(&mut self, s: &str) {
        if let Some(l) = self.out.last_mut() {
            l.push_str(s);
        } else {
            self.out.push(s.to_string());
        }
    }

    fn cur_len(&self) -> usize {
        self.out.last().map(|l| l.chars().count()).unwrap_or(0)
    }

    /// Current line length measured at the authored indentation.
    /// Current line length measured at the larger of the authored and the output
    /// indentation.
    fn adj_len(&self) -> usize {
        (self.cur_len() as isize + self.col_delta.max(0)) as usize
    }

    fn templates(&self, s: &str) -> bool {
        contains_template(s, &self.opts.templates)
    }

    /// Whether a node's subtree contains a template expression.
    fn node_has_template(&self, n: &Node) -> bool {
        if let Some(c) = &n.comment {
            if self.templates(c) {
                return true;
            }
        }
        // Properties on an empty value pin the layout like templates do.
        if n.props.is_some() && matches!(n.kind, Kind::Null) {
            return true;
        }
        // Custom-tagged block collections pin their layout like templates do.
        if let Some(p) = &n.props {
            if let Some(t) = &p.tag {
                if is_block_coll(n) && t != "!!map" && t != "!!seq" {
                    return true;
                }
            }
        }
        match &n.kind {
            Kind::Null | Kind::Alias(_) => false,
            Kind::Scalar(sc) => {
                if let Some(b) = &sc.block {
                    // Irregularly indented content pins the layout like templates do.
                    b.irregular || b.lines.iter().any(|l| self.templates(l)) || b.comment.as_deref().map(|c| self.templates(c)).unwrap_or(false)
                } else {
                    self.templates(&self.src[sc.start..sc.end])
                }
            }
            Kind::FlowMap(_) | Kind::FlowSeq(_) => self.templates(&self.src[n.start..n.end]),
            Kind::Map(entries) => entries.iter().any(|e| self.entry_has_template(e)),
            Kind::Seq(items) => items.iter().any(|i| self.item_has_template(i)),
        }
    }

    fn entry_has_template(&self, e: &Entry) -> bool {
        self.templates(&self.src[e.start..e.key_end])
            || e.colon_comment.as_deref().map(|c| self.templates(c)).unwrap_or(false)
            || self.node_has_template(&e.value)
    }

    fn item_has_template(&self, i: &Item) -> bool {
        i.dash_comment.as_deref().map(|c| self.templates(c)).unwrap_or(false) || self.node_has_template(&i.value)
    }

    pub fn emit_stream(&mut self, stream: &Stream) {
        // Only a lone document without a start marker may compact its root.
        self.root_compact_ok = stream.docs.len() == 1 && stream.docs[0].start_marker.is_none();
        for doc in &stream.docs {
            self.emit_document(doc);
        }
        self.flush_to(self.lines.len());
    }

    fn emit_document(&mut self, doc: &Document) {
        if let Some(cs) = doc.marker_content_start {
            let ml = doc.start_marker.unwrap();
            self.flush_to(ml);
            let prefix = self.src[self.line_starts[ml]..cs].to_string();
            self.push_line(prefix);
            if let Some(root) = &doc.root {
                self.emit_inline_root(root, 0);
            }
            return;
        }
        if let Some(root) = &doc.root {
            self.emit_root(root);
        }
        for n in &doc.extra {
            self.emit_root(n);
        }
    }

    fn emit_inline_root(&mut self, n: &Node, col: usize) {
        // Node on the '---' line.
        if let Some(p) = &n.props {
            if p.newline_after {
                let t = self.src[p.start..p.end].to_string();
                self.append(&t);
                self.consume_through(n.line);
                let child_col = match &n.kind {
                    Kind::Map(_) | Kind::Seq(_) => self.col_of_content(n),
                    _ => 0,
                };
                self.emit_collection(n, child_col, false, false);
                return;
            }
        }
        self.emit_value_inline_or_block(n, col, false, false);
    }

    fn col_of_content(&self, n: &Node) -> usize {
        match &n.kind {
            Kind::Map(e) => e.first().map(|e| e.col).unwrap_or(0),
            Kind::Seq(i) => i.first().map(|i| i.col).unwrap_or(0),
            _ => n.col,
        }
    }

    fn emit_root(&mut self, n: &Node) {
        let lead_comment = (self.cursor..n.line).any(|l| self.kinds.get(l) == Some(&LineKind::Comment));
        self.flush_to(n.line);
        self.stats.emitted_nodes += 1;
        match &n.kind {
            Kind::Map(_) | Kind::Seq(_) => {
                if let Some(p) = &n.props {
                    // Properties on their own line before the collection.
                    let text = self.lines[n.line].trim_end().to_string();
                    let _ = p;
                    self.push_line(text);
                    self.consume_through(n.line);
                }
                let col = self.col_of_content(n);
                let leaf = match &n.kind {
                    Kind::Map(es) => es.iter().all(|e| matches!(e.value.kind, Kind::Scalar(_))),
                    Kind::Seq(items) => items.iter().all(|i| matches!(i.value.kind, Kind::Scalar(_))),
                    _ => false,
                };
                // Directives never compact a document root, and neither does a
                // comment before it.
                if n.props.is_none() && leaf && self.opts.compact && !lead_comment && self.root_compact_ok {
                    if let Some(flow) = self.compact_text_enabled(n) {
                        if col + flow.chars().count() <= self.opts.line_width {
                            self.push_line(format!("{}{}", " ".repeat(col), flow));
                            self.consume_through(n.end_line);
                            return;
                        }
                    }
                }
                let preserve = self.node_has_template(n);
                self.emit_collection(n, col, false, preserve);
            }
            Kind::FlowMap(_) | Kind::FlowSeq(_)
                if n.props.is_none() && !n.flow_has_comment && !self.templates(&self.src[n.start..n.end]) && !self.flow_has_custom_tag(n) =>
            {
                let indent = n.col;
                let inline = self.render_flow_inline(n);
                let multiline = n.end_line > n.line;
                let fits = indent + inline.chars().count() <= self.opts.line_width;
                if (!multiline && fits) || !self.flow_block_renderable(n) {
                    self.count_flow_inline(n);
                    // An inline root starts the line.
                    self.push_line(inline);
                    if let Some(c) = &n.comment {
                        self.append(" ");
                        self.append(c);
                    }
                } else {
                    self.stats.block_flows += 1;
                    if let Some(c) = &n.comment {
                        self.push_line(format!("{}{}", " ".repeat(indent), c));
                    }
                    match &n.kind {
                        Kind::FlowSeq(_) => self.emit_flow_as_block_seq(n, indent),
                        _ => self.emit_flow_as_block_map(n, indent, false, false),
                    }
                }
                self.consume_through(n.end_line);
            }
            _ => {
                let indent = n.col;
                self.push_line(" ".repeat(indent));
                self.emit_value_inline_or_block(n, 0, false, false);
            }
        }
    }

    fn emit_collection(&mut self, n: &Node, indent: usize, compact_item: bool, preserve: bool) {
        match &n.kind {
            Kind::Map(entries) => self.emit_block_map(entries, indent, false, compact_item, preserve),
            Kind::Seq(items) => self.emit_block_seq(items, indent, preserve),
            _ => {}
        }
    }

    fn emit_verbatim_from(&mut self, start: usize, end_line: usize) {
        // Append source text from `start` to the end of its line, then full lines through end_line.
        let l0 = self.line_of(start);
        let first = self.src[start..self.line_end_pos(l0)].to_string();
        self.append(&first);
        for l in l0 + 1..=end_line {
            let t = self.lines[l].to_string();
            self.push_line(t);
        }
        self.consume_through(end_line);
    }

    /// A block indented under a finished value keeps its own indentation.
    fn emit_orphans(&mut self, orphans: &[Node]) {
        for n in orphans {
            if n.line < self.cursor {
                continue;
            }
            self.flush_to(n.line);
            match &n.kind {
                Kind::Map(es) => self.emit_block_map(es, n.col, false, false, false),
                Kind::Seq(items) => self.emit_block_seq(items, n.col, false),
                _ => {
                    for l in n.line..=n.end_line {
                        let t = self.lines[l].trim_start().to_string();
                        self.push_line(t);
                    }
                    self.consume_through(n.end_line);
                }
            }
        }
    }

    fn emit_block_map(&mut self, entries: &[Entry], indent: usize, inline_first: bool, compact_item: bool, preserve: bool) {
        for (idx, e) in entries.iter().enumerate() {
            if idx > 0 {
                let prev = &entries[idx - 1].orphans;
                self.emit_orphans(prev);
            }
            let col = if preserve { e.col } else { indent };
            if self.in_off_region(e.line) || self.take_skip_before(e.line) {
                if idx == 0 && inline_first {
                    self.emit_verbatim_from(e.start, e.end_line);
                } else {
                    self.emit_lines_verbatim(e.line, e.end_line);
                }
                continue;
            }
            if !(idx == 0 && inline_first) {
                self.flush_to(e.line);
                self.push_line(" ".repeat(col));
            }
            if preserve && !is_block_coll(&e.value) && self.entry_has_template(e) {
                self.stats.scalars += 1;
                self.count_untemplated_value(&e.value);
                // A pending scalar directive targets this value even though it is kept.
                self.consume_dirs_before(e.value.line.max(e.line) + 1);
                self.emit_verbatim_from(e.start, e.end_line);
                continue;
            }
            if e.explicit {
                self.emit_verbatim_from(e.start, e.end_line);
                continue;
            }
            if e.quirk == 1 {
                self.emit_verbatim_from(e.start, e.end_line);
                if let Some(l) = self.out.last_mut() {
                    let t = l.trim_end().to_string();
                    *l = t;
                }
                continue;
            }
            if e.quirk == 3 {
                // Root-level plain scalar spanning the region.
                let joined: Vec<String> = (e.line..=e.end_line).map(|l| self.lines[l].trim().to_string()).collect();
                let value = joined.join(" ");
                if value.chars().count() > self.opts.prose_width && fold_eligible(&value) {
                    self.append(">-");
                    let ci = col + self.opts.indent_width;
                    for l in fill_words(&value, self.opts.prose_width) {
                        self.push_line(format!("{}{}", " ".repeat(ci), l));
                    }
                    self.consume_through(e.end_line);
                } else {
                    self.emit_verbatim_from(e.start, e.end_line);
                    if let Some(l) = self.out.last_mut() {
                        let t = l.trim_end().to_string();
                        *l = t;
                    }
                }
                continue;
            }
            if e.quirk == 4 {
                // A line without a key is kept as written, without its indentation;
                // long text is folded.
                let joined: Vec<String> = (e.line..=e.end_line).map(|l| self.lines[l].trim().to_string()).collect();
                let value = joined.join(" ");
                let has_blank = joined.iter().any(|l| l.is_empty());
                if !has_blank && value.chars().count() > self.opts.prose_width && fold_eligible(&value) && e.key.comment.is_none() {
                    if let Some(l) = self.out.last_mut() {
                        *l = ">-".to_string();
                    }
                    let ci = col + self.opts.indent_width;
                    for l in fill_words(&value, self.opts.prose_width) {
                        self.push_line(format!("{}{}", " ".repeat(ci), l));
                    }
                    self.consume_through(e.end_line);
                    continue;
                }
                let mut first = self.src[e.start..self.line_end_pos(e.line)].trim_end().to_string();
                if e.end_line == e.line {
                    let mut body = match &e.key.comment {
                        Some(c) => first[..first.len() - c.len()].trim_end().to_string(),
                        None => first.clone(),
                    };
                    // Text that cannot stand as a plain scalar is quoted.
                    if !plain_syntax_ok(&body, false) {
                        body = match requote(&body, ScalarStyle::Single, false) {
                            Requoted::Quoted(q) => q,
                            Requoted::Literal => single_quote_escaped(&body),
                        };
                    }
                    first = match &e.key.comment {
                        Some(c) => format!("{} {}", body, c),
                        None => body,
                    };
                }
                if let Some(l) = self.out.last_mut() {
                    *l = first;
                }
                for l in e.line + 1..=e.end_line {
                    let t = self.lines[l];
                    let lead = t.len() - t.trim_start_matches(' ').len();
                    let t = t[lead.min(e.col)..].trim_end().to_string();
                    self.push_line(t);
                }
                self.consume_through(e.end_line);
                continue;
            }
            if e.quirk == 2 {
                let t = self.src[e.start..e.key_end].trim_end().to_string();
                self.append(&single_quote_escaped(&t));
                self.consume_through(e.end_line);
                continue;
            }
            let key = self.src[e.start..e.key_end].to_string();
            self.append(&key);
            self.append(":");
            self.consume_through(e.line);
            self.stats.scalars += 1;
            let saved = self.col_delta;
            self.col_delta = e.col as isize - col as isize;
            self.value_counted = true;
            let saved_first = self.compact_first_line;
            self.compact_first_line = if idx == 0 && inline_first && std::mem::take(&mut self.first_item) { Some(e.line) } else { None };
            self.emit_map_value(e, col, compact_item, preserve);
            self.compact_first_line = saved_first;
            if self.value_counted {
                self.stats.emitted_nodes += 1;
            }
            self.value_counted = true;
            self.col_delta = saved;
        }
        if let Some(last) = entries.last() {
            self.emit_orphans(&last.orphans);
        }
    }

    fn emit_map_value(&mut self, e: &Entry, key_col: usize, compact_item: bool, parent_preserve: bool) {
        let v = &e.value;
        let _ = parent_preserve;
        if let Kind::Null = v.kind {
            if v.props.is_none() {
                self.value_counted = false;
            }
            if let Some(p) = &v.props {
                let t = self.src[p.start..p.end].to_string();
                self.append(" ");
                self.append(&t);
            }
            if let Some(c) = &e.colon_comment {
                self.append(" ");
                self.append(c);
            }
            return;
        }
        if is_block_coll(v) {
            if v.props.is_none() && e.colon_comment.is_none() && !e.trivia_before_value {
                if let Some(flow) = self.compact_text(v) {
                    let fl = flow.chars().count();
                    let vcol = self.col_of_content(v);
                    if self.adj_len() + 1 + fl <= self.opts.line_width && vcol + fl <= self.opts.line_width {
                        self.append(" ");
                        self.append(&flow);
                        self.consume_through(v.end_line);
                        return;
                    }
                }
            }
            if let Some(p) = &v.props {
                let t = self.props_text(p);
                if !t.is_empty() {
                    self.append(" ");
                    self.append(&t);
                }
                // Comment after the properties.
                let pl = self.line_of(p.start);
                let rest = self.src[p.end..self.line_end_pos(pl)].trim().to_string();
                if !rest.is_empty() {
                    self.append(" ");
                    self.append(&rest);
                }
                self.consume_through(pl);
            } else if let Some(c) = &e.colon_comment {
                self.append(" ");
                self.append(c);
            }
            let preserve = self.node_has_template(v);
            let child_indent = match &v.kind {
                Kind::Seq(_) => {
                    if compact_item {
                        key_col
                    } else {
                        key_col + self.opts.indent_width
                    }
                }
                _ => key_col + self.opts.indent_width,
            };
            self.emit_collection(v, child_indent, false, preserve);
            return;
        }
        // Scalar, alias or flow value.
        if !e.value_same_line && e.trivia_before_value {
            if let Some(c) = &e.colon_comment {
                self.append(" ");
                self.append(c);
            }
            self.flush_to(v.line);
            let start_line = v.line;
            let t = self.lines[start_line].to_string();
            self.push_line(t);
            for l in start_line + 1..=v.end_line {
                let t = self.lines[l].to_string();
                self.push_line(t);
            }
            self.consume_through(v.end_line);
            return;
        }
        if e.colon_comment.is_some() && matches!(v.kind, Kind::FlowMap(_) | Kind::FlowSeq(_)) {
            // A flow value on the next line moves up beside its key; the comment is dropped.
            self.append(" ");
            self.emit_value_inline_or_block(v, key_col, compact_item, true);
            return;
        }
        if e.colon_comment.is_some() {
            // Comment after "key:" with value on the next line: keep layout.
            let le = self.line_end_pos(e.line);
            let full = self.src[e.start..le].trim_end().to_string();
            let written = format!("{}:", &self.src[e.start..e.key_end]);
            if let Some(last) = self.out.last_mut() {
                if last.ends_with(&written) {
                    let n = last.len() - written.len();
                    last.truncate(n);
                    last.push_str(&full);
                }
            }
            self.push_line(String::new());
            let t = self.lines[v.line].to_string();
            if let Some(last) = self.out.last_mut() {
                *last = t;
            }
            for l in v.line + 1..=v.end_line {
                let t = self.lines[l].to_string();
                self.push_line(t);
            }
            self.consume_through(v.end_line);
            return;
        }
        self.append(" ");
        self.emit_value_inline_or_block(v, key_col, compact_item, true);
    }

    fn props_text(&self, p: &Props) -> String {
        let mut parts = Vec::new();
        // Keep source order of anchor and tag.
        let src = &self.src[p.start..p.end];
        let a_pos = src.find('&');
        let t_pos = src.find('!');
        let tag = p.tag.clone();
        let tag = tag.filter(|t| !(t == "!!map" || t == "!!seq"));
        match (a_pos, t_pos) {
            (Some(a), Some(t)) if t < a => {
                if let Some(t) = &tag {
                    parts.push(t.clone());
                }
                if let Some(an) = &p.anchor {
                    parts.push(format!("&{}", an));
                }
            }
            _ => {
                if let Some(an) = &p.anchor {
                    parts.push(format!("&{}", an));
                }
                if let Some(t) = &tag {
                    parts.push(t.clone());
                }
            }
        }
        parts.join(" ")
    }

    /// Emit a scalar/alias/flow value at the end of the current line (a space was already
    /// written if needed). `owner_col` is the column of the owning key or dash.
    /// Take the pending directive (by line) that applies to a scalar starting at `line`.
    fn take_dir<T: Clone>(dirs: &[(usize, T)], used: &mut Vec<usize>, line: usize) -> Option<T> {
        let mut found = None;
        for (l, v) in dirs {
            if *l < line && !used.contains(l) {
                found = Some((*l, v.clone()));
            }
        }
        let (l, v) = found?;
        // All earlier pending directives are consumed as well.
        for (l2, _) in dirs {
            if *l2 <= l && !used.contains(l2) {
                used.push(*l2);
            }
        }
        Some(v)
    }

    /// Mark scalar directives before `line` as used.
    fn consume_dirs_before(&mut self, line: usize) {
        let mut used = std::mem::take(&mut self.used_dirs);
        Self::take_dir(&self.md_dirs, &mut used, line);
        Self::take_dir(&self.emb_dirs, &mut used, line);
        Self::take_dir(&self.opt_dirs, &mut used, line);
        self.used_dirs = used;
    }

    /// Markdown/embedded handling for a scalar value. Returns true if emitted.
    fn emit_targeted_scalar(&mut self, v: &Node, owner_col: usize) -> bool {
        let sc = match &v.kind {
            Kind::Scalar(sc) => sc,
            _ => return false,
        };
        let line = self.line_of(sc.start);
        let mut used = std::mem::take(&mut self.used_dirs);
        let md = Self::take_dir(&self.md_dirs, &mut used, line);
        let emb = Self::take_dir(&self.emb_dirs, &mut used, line);
        let tagged = v.props.as_ref().and_then(|p| p.tag.clone()).map(|t| t == "!md" || t == "!markdown").unwrap_or(false);
        let opt_only = if tagged { Self::take_dir(&self.opt_dirs, &mut used, line) } else { None };
        self.used_dirs = used;
        if let Some(name) = emb {
            if sc.style != ScalarStyle::Literal {
                let col = self.src[self.line_starts[line]..sc.start].chars().count();
                if self.error.is_none() {
                    self.error = Some(crate::format_cmd::Diagnostic { line: line + 1, col: col + 1, msg: format!("fmt: {} targets a literal block scalar", name) });
                }
                return false;
            }
            self.value_counted = false;
            self.embedded_target = true;
            if !self.opts.skip_embedded {
                if let Some(prog) = crate::source::formatter_program(&name) {
                    let first = sc.block.as_ref().map(|b| b.first_line).unwrap_or(line + 1);
                    self.notes.push(crate::format_cmd::Diagnostic { line: first + 1, col: 1, msg: format!("missing optional embedded formatter `{}`; preserved source", prog) });
                }
            }
            return false;
        }
        let words = match (md, tagged) {
            (Some(w), _) => w,
            (None, true) => opt_only.unwrap_or_default(),
            _ => return false,
        };
        if sc.value.is_empty() {
            return false;
        }
        self.stats.scalars += 1;
        let mut o = self.opts.clone();
        apply_md_words(&mut o, &words);
        let origin = sc.block.as_ref().map_or((line, 0), |b| (b.first_line, b.content_indent));
        let lines = crate::markdown::format_fragment(&sc.value, &o, &mut Vec::new(), origin);
        // Props stay in front of the block indicator.
        if let Some(p) = &v.props {
            let t = self.props_text(p);
            if !t.is_empty() {
                self.append(&t);
                self.append(" ");
            }
        }
        // A block scalar keeps its chomping and indentation indicators.
        let header = match &sc.block {
            Some(b) => format!("|{}", b.raw),
            None => "|".to_string(),
        };
        self.append(&header);
        let ci = owner_col + self.opts.indent_width;
        let from_block = sc.block.is_some();
        for l in lines {
            if l.is_empty() {
                if from_block {
                    self.push_line(String::new());
                } else {
                    self.push_line(" ".repeat(ci));
                }
            } else {
                self.push_line(format!("{}{}", " ".repeat(ci), l));
            }
        }
        // Blank lines the block scalar consumed after its text stay.
        if let Some(b) = &sc.block {
            let trailing = b.raw_lines.iter().rev().take_while(|l| l.trim().is_empty()).count();
            let content = b.raw_lines.len() - trailing;
            if content > 0 && b.chomp != Chomp::Keep {
                for _ in 0..trailing {
                    self.push_line(String::new());
                }
            }
        }
        self.consume_through(v.end_line);
        true
    }

    fn emit_value_inline_or_block(&mut self, v: &Node, owner_col: usize, compact_item: bool, in_map: bool) {
        if self.emit_targeted_scalar(v, owner_col) {
            return;
        }
        // Block scalars keep their properties and are re-indented normally.
        if let (Some(p), Kind::Scalar(sc)) = (&v.props, &v.kind) {
            if sc.block.is_some() && !p.newline_after {
                let t = self.src[p.start..p.end].to_string();
                self.append(&t);
                self.append(" ");
                let mut v2 = v.clone();
                v2.props = None;
                self.emit_value_inline_or_block(&v2, owner_col, compact_item, in_map);
                return;
            }
        }
        // Properties and comments.
        if let Some(p) = &v.props {
            if matches!(v.kind, Kind::Scalar(_)) {
                self.stats.scalars += 1;
            }
            if matches!(v.kind, Kind::FlowMap(_) | Kind::FlowSeq(_)) && p.tag.is_some() {
                self.count_flow_scalars_only(v);
            }
            let core = p.anchor.is_none()
                && p.tag.as_deref().map(|t| matches!(t, "!!str" | "!!int" | "!!float" | "!!bool" | "!!null" | "!!map" | "!!seq")).unwrap_or(false);
            if !core || p.newline_after {
                if matches!(v.kind, Kind::FlowMap(_) | Kind::FlowSeq(_)) && p.tag.is_none() && !p.newline_after {
                    // Anchored flow collections stay inline.
                    let t = self.props_text(p);
                    self.append(&t);
                    self.append(" ");
                    let mut v2 = v.clone();
                    v2.props = None;
                    let inline = self.render_flow_inline(&v2);
                    if v2.flow_has_comment || v2.end_line > v2.line {
                        self.emit_value_inline_or_block(&v2, owner_col, compact_item, in_map);
                        return;
                    }
                    self.append(&inline);
                    if let Some(c) = &v.comment {
                        self.append(" ");
                        self.append(c);
                    }
                    self.consume_through(v.end_line);
                    return;
                }
                let end = v.end;
                let end_line = self.line_of(end.saturating_sub(1).max(p.start));
                let first_line = self.line_of(p.start);
                if first_line == end_line {
                    let t = self.src[p.start..end].to_string();
                    self.append(&t);
                    if let Some(c) = &v.comment {
                        self.append(" ");
                        self.append(c);
                    }
                    self.consume_through(end_line);
                } else {
                    self.emit_verbatim_from(p.start, end_line);
                }
                return;
            }
            // Core tags.
            let tag = p.tag.clone().unwrap();
            if tag == "!!map" || tag == "!!seq" {
                let mut v2 = v.clone();
                v2.props = None;
                self.emit_value_inline_or_block(&v2, owner_col, compact_item, in_map);
                return;
            }
            if let Kind::Scalar(sc) = &v.kind {
                if sc.block.is_none() && !sc.multiline {
                    let text = core_tagged_scalar(&tag, sc, self.src, false);
                    self.append(&tag);
                    self.append(" ");
                    self.append(&text);
                    if let Some(c) = &v.comment {
                        self.append(" ");
                        self.append(c);
                    }
                    self.consume_through(v.end_line);
                    return;
                }
            }
            let t = self.src[p.start..v.end].to_string();
            self.append(&t);
            if let Some(c) = &v.comment {
                self.append(" ");
                self.append(c);
            }
            self.consume_through(v.end_line);
            return;
        }
        match &v.kind {
            Kind::Alias(a) => {
                self.append(&format!("*{}", a));
                if let Some(c) = &v.comment {
                    self.append(" ");
                    self.append(c);
                }
                self.consume_through(v.end_line);
            }
            Kind::Scalar(sc) => {
                self.emit_scalar(v, sc, owner_col, false);
            }
            Kind::FlowMap(_) | Kind::FlowSeq(_) => {
                self.emit_flow(v, owner_col, compact_item, in_map);
            }
            Kind::Null => {}
            _ => {}
        }
    }

    fn emit_scalar(&mut self, v: &Node, sc: &Scalar, owner_col: usize, orig_flow: bool) {
        let content_indent = owner_col + self.opts.indent_width;
        if self.templates(&self.src[sc.start..sc.end]) || v.comment.as_deref().map(|c| self.templates(c)).unwrap_or(false) {
            // Template-bearing scalars are kept as written.
            self.value_counted = false;
            self.emit_verbatim_from(sc.start, v.end_line);
            return;
        }
        self.stats.scalars += 1;
        let nci = self.next_comment_indent(v.end_line);
        let mut r = self.render_scalar(sc, orig_flow, v.comment.is_some());
        let mut content_indent = content_indent;
        if let Some(ci) = nci {
            match sc.style {
                ScalarStyle::Literal | ScalarStyle::Folded => {
                    // Keep the authored content indentation so the comment stays outside.
                    content_indent = sc.block.as_ref().map(|b| b.content_indent).unwrap_or(content_indent);
                }
                _ => {
                    if ci >= content_indent && matches!(r, Some(Rendered::Block(..))) {
                        r = if sc.multiline {
                            None
                        } else if sc.style == ScalarStyle::Plain {
                            Some(Rendered::Inline(normalize_plain(&sc.value)))
                        } else if !sc.value.contains('\n') && plain_safe(&sc.value, orig_flow) {
                            Some(Rendered::Inline(sc.value.clone()))
                        } else {
                            Some(Rendered::Inline(self.src[sc.start..sc.end].to_string()))
                        };
                    }
                }
            }
        }
        match r {
            None => {
                // Verbatim (multi-line source kept as written).
                let l0 = self.line_of(sc.start);
                let first = self.src[sc.start..self.line_end_pos(l0)].trim_end().to_string();
                self.append(&first);
                for l in l0 + 1..=v.end_line {
                    let t = self.lines[l].to_string();
                    self.push_line(t);
                }
                self.consume_through(v.end_line);
                // A trailing comment is already part of the copied lines unless single-line.
                if l0 == v.end_line {
                    if let Some(c) = &v.comment {
                        // trailing comment was trimmed; re-add normalized
                        let l = self.out.last_mut().unwrap();
                        if let Some(p) = l.rfind(c.as_str()) {
                            l.truncate(p);
                            let t = l.trim_end().to_string();
                            *l = t;
                        }
                        self.append(" ");
                        self.append(c);
                    }
                }
            }
            Some(Rendered::Inline(s)) => {
                self.append(&s);
                if let Some(c) = &v.comment {
                    self.append(" ");
                    self.append(c);
                }
                self.consume_through(v.end_line);
            }
            Some(Rendered::Block(header, lines)) => {
                self.append(&header);
                let hc = sc.block.as_ref().and_then(|b| b.comment.clone()).or_else(|| v.comment.clone());
                if let Some(c) = hc {
                    self.append(" ");
                    self.append(&c);
                }
                for l in lines {
                    if l.is_empty() {
                        self.push_line(String::new());
                    } else {
                        self.push_line(format!("{}{}", " ".repeat(content_indent), l));
                    }
                }
                self.consume_through(v.end_line);
            }
            Some(Rendered::Raw(header, raw, ci)) => {
                self.append(&header);
                if let Some(c) = sc.block.as_ref().and_then(|b| b.comment.clone()) {
                    self.append(" ");
                    self.append(&c);
                }
                for l in reindent_raw(&raw, ci, content_indent) {
                    self.push_line(l);
                }
                self.consume_through(v.end_line);
            }
            Some(Rendered::Refilled(header, filled, trailing, ci)) => {
                self.append(&header);
                for l in filled {
                    self.push_line(format!("{}{}", " ".repeat(content_indent), l));
                }
                for l in reindent_raw(&trailing, ci, content_indent) {
                    self.push_line(l);
                }
                self.consume_through(v.end_line);
            }
        }
    }

    /// Indentation of the next non-blank line after `line` if it is a comment.
    fn next_comment_indent(&self, line: usize) -> Option<usize> {
        let mut l = line + 1;
        while l < self.lines.len() {
            let t = self.lines[l];
            let tt = t.trim_start();
            if tt.is_empty() {
                l += 1;
                continue;
            }
            if tt.starts_with('#') {
                return Some(t.len() - tt.len());
            }
            return None;
        }
        None
    }

    /// Render a scalar for block context. None means keep the source verbatim.
    fn render_scalar(&self, sc: &Scalar, orig_flow: bool, has_comment: bool) -> Option<Rendered> {
        let width = self.opts.prose_width;
        if sc.verbatim {
            return Some(Rendered::Inline(self.src[sc.start..sc.end].to_string()));
        }
        match sc.style {
            ScalarStyle::Plain => {
                if !sc.multiline {
                    let s = normalize_plain(&sc.value);
                    if !has_comment && s.chars().count() > width && fold_eligible(&s) {
                        return Some(Rendered::Block(">-".into(), fill_words(&s, width)));
                    }
                    if !plain_syntax_ok(&s, orig_flow) {
                        return Some(match requote(&s, ScalarStyle::Single, orig_flow) {
                            Requoted::Quoted(q) => Rendered::Inline(q),
                            Requoted::Literal => {
                                let (h, lines) = literal_block(&s, self.opts.indent_width);
                                Rendered::Block(h, lines)
                            }
                        });
                    }
                    Some(Rendered::Inline(s))
                } else if !has_comment && sc.value.chars().count() > width && fold_eligible(&sc.value) {
                    Some(Rendered::Block(">-".into(), fill_words(&sc.value, width)))
                } else {
                    None
                }
            }
            ScalarStyle::Single | ScalarStyle::Double => {
                let val = &sc.value;
                if val.contains('\n') {
                    if literal_eligible(val) {
                        let (h, lines) = literal_block(val, self.opts.indent_width);
                        return Some(Rendered::Block(h, lines));
                    }
                    if sc.multiline {
                        return None;
                    }
                    return Some(Rendered::Inline(self.src[sc.start..sc.end].to_string()));
                }
                if sc.multiline {
                    if !has_comment && val.chars().count() > width && fold_eligible(val) {
                        return Some(Rendered::Block(">-".into(), fill_words(val, width)));
                    }
                    return None;
                }
                if plain_safe(val, orig_flow) {
                    if !has_comment && val.chars().count() > width && fold_eligible(val) {
                        return Some(Rendered::Block(">-".into(), fill_words(val, width)));
                    }
                    return Some(Rendered::Inline(val.clone()));
                }
                match requote(val, sc.style, orig_flow) {
                    Requoted::Quoted(q) => {
                        if !has_comment && !needs_escape(val) && val.chars().count() > width && fold_eligible(val) {
                            return Some(Rendered::Block(">-".into(), fill_words(val, width)));
                        }
                        Some(Rendered::Inline(q))
                    }
                    Requoted::Literal => {
                        let (h, lines) = literal_block(val, self.opts.indent_width);
                        Some(Rendered::Block(h, lines))
                    }
                }
            }
            ScalarStyle::Literal => {
                let b = sc.block.as_ref().unwrap();
                let header = if b.indicator.is_some() {
                    let ch = match b.chomp {
                        Chomp::Strip => "-",
                        Chomp::Keep => "+",
                        Chomp::Clip => "",
                    };
                    // Keep the original order of indicator and chomping.
                    if b.raw.starts_with(['-', '+']) {
                        format!("|{}{}", ch, self.opts.indent_width)
                    } else {
                        format!("|{}{}", self.opts.indent_width, ch)
                    }
                } else {
                    format!("|{}", b.raw)
                };
                Some(Rendered::Raw(header, b.raw_lines.clone(), b.content_indent))
            }
            ScalarStyle::Folded => {
                let b = sc.block.as_ref().unwrap();
                let header = format!(">{}", b.raw);
                // Keep chomping and explicit indentation leave the text as written.
                if b.comment.is_none() && b.indicator.is_none() && b.chomp != Chomp::Keep && !b.irregular {
                    if let Some((filled, n_content)) = refold_lines(&b.lines, width) {
                        let trailing = b.raw_lines[n_content..].to_vec();
                        return Some(Rendered::Refilled(header, filled, trailing, b.content_indent));
                    }
                }
                Some(Rendered::Raw(header, b.raw_lines.clone(), b.content_indent))
            }
        }
    }

    // ---------------- Flow collections ----------------

    fn render_flow_scalar(&self, n: &Node) -> String {
        match &n.kind {
            Kind::Null => String::new(),
            Kind::Alias(a) => format!("*{}", a),
            Kind::Scalar(sc) if sc.verbatim => self.src[sc.start..sc.end].to_string(),
            Kind::Scalar(sc) => match sc.style {
                ScalarStyle::Plain => {
                    let v = if sc.multiline { sc.value.replace('\n', " ") } else { normalize_plain(&sc.value) };
                    if !plain_syntax_ok(&v, true) {
                        match requote(&v, ScalarStyle::Single, true) {
                            Requoted::Quoted(q) => q,
                            Requoted::Literal => single_quote_escaped(&v),
                        }
                    } else {
                        v
                    }
                }
                ScalarStyle::Single | ScalarStyle::Double => {
                    if !sc.value.contains('\n') && plain_safe(&sc.value, true) {
                        sc.value.clone()
                    } else if sc.value.contains('\n') {
                        double_quote(&sc.value)
                    } else {
                        match requote(&sc.value, sc.style, true) {
                            Requoted::Quoted(q) => q,
                            Requoted::Literal => single_quote_escaped(&sc.value),
                        }
                    }
                }
                _ => self.src[sc.start..sc.end].to_string(),
            },
            _ => self.render_flow_inline(n),
        }
    }

    fn render_flow_node(&self, n: &Node) -> String {
        let core_tag = n.props.as_ref().filter(|p| p.anchor.is_none()).and_then(|p| p.tag.as_deref()).filter(|t| is_core_tag(t));
        let body = match &n.kind {
            Kind::FlowMap(_) | Kind::FlowSeq(_) => self.render_flow_inline_body(n),
            Kind::Scalar(sc) if core_tag.is_some() && !sc.verbatim => core_tagged_scalar(core_tag.unwrap(), sc, self.src, true),
            _ => self.render_flow_scalar(n),
        };
        if let Some(p) = &n.props {
            let t = self.props_text(p);
            if body.is_empty() {
                return t;
            }
            if t.is_empty() {
                return body;
            }
            return format!("{} {}", t, body);
        }
        body
    }

    fn render_flow_inline(&self, n: &Node) -> String {
        self.render_flow_node(n)
    }

    fn render_flow_inline_body(&self, n: &Node) -> String {
        match &n.kind {
            Kind::FlowSeq(entries) => {
                let parts: Vec<String> = entries.iter().map(|e| self.render_flow_entry(e, false)).collect();
                format!("[{}]", parts.join(", "))
            }
            Kind::FlowMap(entries) => {
                let parts: Vec<String> = entries.iter().map(|e| self.render_flow_entry(e, true)).collect();
                format!("{{{}}}", parts.join(", "))
            }
            _ => self.render_flow_scalar(n),
        }
    }

    fn render_flow_entry(&self, e: &FlowEntry, in_map: bool) -> String {
        if !e.is_pair {
            return e.value.as_ref().map(|v| self.render_flow_node(v)).unwrap_or_default();
        }
        let k = e.key.as_ref().map(|k| self.render_flow_node(k)).unwrap_or_default();
        let _ = in_map;
        match &e.value {
            Some(v) => {
                let vs = self.render_flow_node(v);
                if e.explicit {
                    format!("? {}: {}", k, vs)
                } else {
                    format!("{}: {}", k, vs)
                }
            }
            None => {
                if e.explicit {
                    format!("? {}", k)
                } else {
                    k
                }
            }
        }
    }

    fn flow_block_renderable(&self, n: &Node) -> bool {
        match &n.kind {
            Kind::FlowSeq(entries) => entries.iter().all(|e| !e.is_pair && e.value.as_ref().map(|v| self.flow_child_ok(v)).unwrap_or(false)),
            Kind::FlowMap(entries) => entries.iter().all(|e| {
                !e.explicit
                    && e.key.as_ref().map(|k| matches!(k.kind, Kind::Scalar(_)) && k.props.is_none()).unwrap_or(false)
                    && e.value.as_ref().map(|v| self.flow_child_ok(v)).unwrap_or(true)
            }),
            _ => false,
        }
    }

    fn flow_child_ok(&self, v: &Node) -> bool {
        match &v.kind {
            Kind::Null => false,
            _ => true,
        }
    }

    fn flow_has_custom_tag(&self, n: &Node) -> bool {
        if let Some(p) = &n.props {
            if let Some(t) = &p.tag {
                if !is_core_tag(t) {
                    return true;
                }
            }
        }
        match &n.kind {
            Kind::FlowMap(es) | Kind::FlowSeq(es) => es.iter().any(|e| {
                e.key.as_ref().map(|k| self.flow_has_custom_tag(k)).unwrap_or(false)
                    || e.value.as_ref().map(|v| self.flow_has_custom_tag(v)).unwrap_or(false)
            }),
            _ => false,
        }
    }

    /// Flow rendering of a block collection for compact mode, if eligible.
    /// Whether compaction applies to collection `n`.
    fn compact_on(&self, n: &Node) -> bool {
        use super::directive::Scope;
        let key = match &n.kind {
            Kind::Seq(items) => items.first().map(|i| self.line_starts[i.line] + i.col).unwrap_or(n.start),
            _ => n.start,
        };
        if let Some(&v) = self.compact_override.get(&key) {
            return v;
        }
        let mut on = self.opts.compact;
        for &(_, v, sc) in &self.compact_scoped {
            if sc == Scope::File {
                on = v;
            }
        }
        for &(l, v, sc) in &self.compact_scoped {
            if sc == Scope::FromHere && l < n.line {
                on = v;
            }
        }
        on
    }

    fn compact_text(&self, n: &Node) -> Option<String> {
        if !self.compact_on(n) {
            return None;
        }
        self.compact_text_enabled(n)
    }

    fn compact_text_enabled(&self, n: &Node) -> Option<String> {
        if self.node_has_template(n) {
            return None;
        }
        // Blank or comment lines inside the collection keep block style.
        for l in n.line..=n.end_line.min(self.lines.len().saturating_sub(1)) {
            if l > n.line && self.kinds[l] != LineKind::Content {
                return None;
            }
        }
        self.compact_node(n)
    }

    fn compact_scalar(&self, sc: &Scalar) -> Option<String> {
        if sc.block.is_some() || sc.multiline {
            return None;
        }
        let v = match sc.style {
            ScalarStyle::Plain => normalize_plain(&sc.value),
            _ => sc.value.clone(),
        };
        if v.contains('\n') {
            return None;
        }
        if sc.style == ScalarStyle::Plain {
            if plain_syntax_ok(&v, true) {
                return Some(v);
            }
            return Some(match requote(&v, ScalarStyle::Single, true) {
                Requoted::Quoted(q) => q,
                Requoted::Literal => single_quote_escaped(&v),
            });
        }
        if plain_safe(&v, true) {
            return Some(v);
        }
        Some(match requote(&v, sc.style, true) {
            Requoted::Quoted(q) => q,
            Requoted::Literal => single_quote_escaped(&v),
        })
    }

    fn compact_node(&self, n: &Node) -> Option<String> {
        if n.props.is_some() || n.comment.is_some() {
            return None;
        }
        match &n.kind {
            Kind::Scalar(sc) => self.compact_scalar(sc),
            Kind::Alias(a) => Some(format!("*{}", a)),
            Kind::FlowMap(_) | Kind::FlowSeq(_) => {
                if n.flow_has_comment || self.flow_has_custom_tag(n) || n.end_line > n.line {
                    return None;
                }
                Some(self.render_flow_inline(n))
            }
            Kind::Map(entries) => {
                let mut parts = Vec::new();
                for e in entries {
                    if e.explicit || e.quirk != 0 || e.colon_comment.is_some() || e.key.props.is_some() {
                        return None;
                    }
                    let k = match &e.key.kind {
                        Kind::Scalar(sc) => self.compact_scalar(sc)?,
                        _ => return None,
                    };
                    if matches!(e.value.kind, Kind::Null) {
                        return None;
                    }
                    let v = self.compact_node(&e.value)?;
                    parts.push(format!("{}: {}", k, v));
                }
                Some(format!("{{{}}}", parts.join(", ")))
            }
            Kind::Seq(items) => {
                let mut parts = Vec::new();
                for it in items {
                    if it.dash_comment.is_some() || matches!(it.value.kind, Kind::Null) {
                        return None;
                    }
                    parts.push(self.compact_node(&it.value)?);
                }
                Some(format!("[{}]", parts.join(", ")))
            }
            _ => None,
        }
    }

    /// Count scalars and flow collections of an inline-rendered flow node.
    fn count_flow_inline(&mut self, n: &Node) {
        match &n.kind {
            Kind::FlowMap(es) | Kind::FlowSeq(es) => {
                self.stats.flows += 1;
                for e in es {
                    if let Some(k) = &e.key {
                        self.count_flow_inline(k);
                    }
                    if let Some(v) = &e.value {
                        self.count_flow_inline(v);
                    }
                }
            }
            Kind::Scalar(_) => self.stats.scalars += 1,
            _ => {}
        }
    }

    fn count_flow_scalars_only(&mut self, n: &Node) {
        match &n.kind {
            Kind::FlowMap(es) | Kind::FlowSeq(es) => {
                for e in es {
                    if let Some(k) = &e.key {
                        self.count_flow_scalars_only(k);
                    }
                    if let Some(v) = &e.value {
                        self.count_flow_scalars_only(v);
                    }
                }
            }
            Kind::Scalar(_) => self.stats.scalars += 1,
            _ => {}
        }
    }

    /// Count scalars of a node kept verbatim (flows inside are not planned).
    fn count_untemplated_value(&mut self, n: &Node) {
        let _ = n;
    }

    fn emit_flow(&mut self, v: &Node, owner_col: usize, compact_item: bool, in_map: bool) {
        if v.flow_has_comment || self.templates(&self.src[v.start..v.end]) || self.flow_has_custom_tag(v) {
            self.count_flow_scalars_only(v);
            self.emit_verbatim_from(v.start, v.end_line);
            if let Some(c) = &v.comment {
                if v.line == v.end_line {
                    let l = self.out.last_mut().unwrap();
                    let t = l.trim_end().to_string();
                    *l = t;
                    let _ = c;
                }
            }
            return;
        }
        let multiline = v.end_line > v.line;
        // A flow collection over several lines is kept as written when a comment
        // follows it, or when it is the first value of a mapping on the dash line of
        // a sequence's first item.
        if multiline && (v.comment.is_some() || self.compact_first_line == Some(v.line)) {
            self.count_flow_scalars_only(v);
            self.emit_verbatim_from(v.start, v.end_line);
            return;
        }
        let inline = self.render_flow_inline(v);
        let fits = self.adj_len() + inline.chars().count() <= self.opts.line_width;
        if (!multiline && fits) || !self.flow_block_renderable(v) {
            self.count_flow_inline(v);
            self.append(&inline);
            if let Some(c) = &v.comment {
                self.append(" ");
                self.append(c);
            }
            self.consume_through(v.end_line);
            return;
        }
        self.stats.block_flows += 1;
        self.value_counted = false;
        // A flow mapping item of a block sequence expands to the compact "- key: value" form.
        if !in_map && matches!(v.kind, Kind::FlowMap(_)) && v.comment.is_none() {
            self.consume_through(v.end_line);
            self.emit_flow_as_block_map(v, owner_col + 2, true, true);
            return;
        }
        // Expand to block style. Remove the trailing space written before the value.
        if let Some(l) = self.out.last_mut() {
            if l.ends_with(' ') {
                l.pop();
            }
        }
        if let Some(c) = &v.comment {
            self.append(" ");
            self.append(c);
        }
        self.consume_through(v.end_line);
        match &v.kind {
            Kind::FlowSeq(_) => {
                let _ = (in_map, compact_item);
                let indent = owner_col + self.opts.indent_width;
                self.emit_flow_as_block_seq(v, indent);
            }
            Kind::FlowMap(_) => {
                let indent = owner_col + self.opts.indent_width;
                self.emit_flow_as_block_map(v, indent, false, false);
            }
            _ => {}
        }
    }

    fn emit_flow_as_block_seq(&mut self, v: &Node, indent: usize) {
        let entries = match &v.kind {
            Kind::FlowSeq(e) => e,
            _ => return,
        };
        for e in entries {
            let item = e.value.as_ref().unwrap();
            self.push_line(" ".repeat(indent));
            self.append("-");
            self.emit_flow_child_value(item, indent, true, false);
        }
    }

    fn emit_flow_as_block_map(&mut self, v: &Node, indent: usize, inline_first: bool, compact_item: bool) {
        let entries = match &v.kind {
            Kind::FlowMap(e) => e,
            _ => return,
        };
        for (i, e) in entries.iter().enumerate() {
            if !(i == 0 && inline_first) {
                self.push_line(" ".repeat(indent));
            }
            let k = e.key.as_ref().map(|k| self.render_flow_node(k)).unwrap_or_default();
            self.append(&k);
            self.append(":");
            self.stats.scalars += 1;
            if let Some(val) = &e.value {
                self.emit_flow_child_value(val, indent, false, compact_item);
            }
        }
    }

    /// Emit a child of an expanded flow collection after "-" or "key:".
    fn emit_flow_child_value(&mut self, n: &Node, owner_col: usize, is_seq_item: bool, compact_item: bool) {
        match &n.kind {
            Kind::FlowSeq(_) | Kind::FlowMap(_) => {
                let inline = self.render_flow_inline(n);
                let fits = self.adj_len() + 1 + inline.chars().count() <= self.opts.line_width;
                if fits || !self.flow_block_renderable(n) {
                    self.count_flow_inline(n);
                    self.append(" ");
                    self.append(&inline);
                    return;
                }
                self.stats.block_flows += 1;
                if is_seq_item {
                    match &n.kind {
                        Kind::FlowSeq(_) => {
                            self.emit_flow_as_block_seq(n, owner_col + self.opts.indent_width);
                        }
                        _ => {
                            self.append(" ");
                            self.emit_flow_as_block_map(n, owner_col + 2, true, true);
                        }
                    }
                } else {
                    match &n.kind {
                        Kind::FlowSeq(_) => {
                            let _ = compact_item;
                            let ind = owner_col + self.opts.indent_width;
                            self.emit_flow_as_block_seq(n, ind);
                        }
                        _ => {
                            self.emit_flow_as_block_map(n, owner_col + self.opts.indent_width, false, false);
                        }
                    }
                }
            }
            Kind::Scalar(sc) => {
                self.append(" ");
                self.stats.scalars += 1;
                if n.props.is_some() {
                    let t = self.render_flow_node(n);
                    self.append(&t);
                    return;
                }
                let content_indent = owner_col + self.opts.indent_width;
                let r = self.render_scalar_from_flow(sc);
                match r {
                    Rendered::Inline(s) => self.append(&s),
                    Rendered::Block(h, lines) => {
                        self.append(&h);
                        for l in lines {
                            if l.is_empty() {
                                self.push_line(String::new());
                            } else {
                                self.push_line(format!("{}{}", " ".repeat(content_indent), l));
                            }
                        }
                    }
                    Rendered::Raw(..) | Rendered::Refilled(..) => {}
                }
            }
            _ => {
                self.append(" ");
                let t = self.render_flow_node(n);
                self.append(&t);
            }
        }
    }

    fn render_scalar_from_flow(&self, sc: &Scalar) -> Rendered {
        let width = self.opts.prose_width;
        match sc.style {
            ScalarStyle::Plain => {
                let s = normalize_plain(&sc.value);
                if s.chars().count() > width && fold_eligible(&s) {
                    return Rendered::Block(">-".into(), fill_words(&s, width));
                }
                if !plain_syntax_ok(&s, true) {
                    return match requote(&s, ScalarStyle::Single, true) {
                        Requoted::Quoted(q) => Rendered::Inline(q),
                        Requoted::Literal => {
                            let (h, lines) = literal_block(&s, self.opts.indent_width);
                            Rendered::Block(h, lines)
                        }
                    };
                }
                Rendered::Inline(s)
            }
            _ => {
                let val = &sc.value;
                if val.contains('\n') {
                    if literal_eligible(val) {
                        let (h, lines) = literal_block(val, self.opts.indent_width);
                        return Rendered::Block(h, lines);
                    }
                    return Rendered::Inline(if sc.multiline { double_quote(val) } else { self.src[sc.start..sc.end].to_string() });
                }
                if plain_safe(val, true) {
                    if val.chars().count() > width && fold_eligible(val) {
                        return Rendered::Block(">-".into(), fill_words(val, width));
                    }
                    return Rendered::Inline(val.clone());
                }
                match requote(val, sc.style, true) {
                    Requoted::Quoted(q) => {
                        if !needs_escape(val) && val.chars().count() > width && fold_eligible(val) {
                            return Rendered::Block(">-".into(), fill_words(val, width));
                        }
                        Rendered::Inline(q)
                    }
                    Requoted::Literal => {
                        if val.chars().count() > width && fold_eligible(val) {
                            return Rendered::Block(">-".into(), fill_words(val, width));
                        }
                        Rendered::Inline(single_quote_escaped(val))
                    }
                }
            }
        }
    }

    // ---------------- Block sequences ----------------

    fn emit_block_seq(&mut self, items: &[Item], indent: usize, preserve: bool) {
        let saved_delta = self.col_delta;
        self.emit_block_seq_inner(items, indent, preserve);
        if let Some(last) = items.last() {
            self.emit_orphans(&last.orphans);
        }
        self.col_delta = saved_delta;
    }

    /// Cells of each row when a `fmt: table` sequence can be aligned.
    fn table_rows(&self, items: &[Item], collapse: bool) -> Option<Vec<Vec<String>>> {
        let mut rows = Vec::new();
        for it in items {
            let v = &it.value;
            if it.dash_comment.is_some() || !it.value_same_line || it.trivia_before_value || v.props.is_some() {
                return None;
            }
            if self.in_off_region(it.line) || self.skip_lines.iter().any(|&l| l < it.line && !self.used_skips.contains(&l)) {
                return None;
            }
            let cells: Vec<String> = match &v.kind {
                Kind::FlowMap(es) if !es.is_empty() => {
                    if v.flow_has_comment || self.flow_has_custom_tag(v) || self.templates(&self.src[v.start..v.end]) {
                        return None;
                    }
                    es.iter().map(|e| self.render_flow_entry(e, true)).collect()
                }
                Kind::Map(es) if collapse && v.comment.is_none() => {
                    if (it.line + 1..=v.end_line).any(|l| self.kinds[l] != LineKind::Content) || self.node_has_template(v) {
                        return None;
                    }
                    let mut cells = Vec::new();
                    for e in es {
                        if e.explicit || e.quirk != 0 || e.colon_comment.is_some() || e.key.props.is_some() || is_block_coll(&e.value) || matches!(e.value.kind, Kind::Null) {
                            return None;
                        }
                        let k = match &e.key.kind {
                            Kind::Scalar(sc) => self.compact_scalar(sc)?,
                            _ => return None,
                        };
                        cells.push(format!("{}: {}", k, self.compact_node(&e.value)?));
                    }
                    cells
                }
                _ => return None,
            };
            rows.push(cells);
        }
        Some(rows)
    }

    /// Emit an aligned table; blank and comment lines between rows start new groups.
    fn emit_table(&mut self, items: &[Item], rows: &[Vec<String>], indent: usize) {
        let mut groups: Vec<Vec<usize>> = Vec::new();
        for k in 0..items.len() {
            let split = k == 0 || (items[k - 1].end_line.max(items[k - 1].line) + 1..items[k].line).any(|l| self.kinds[l] != LineKind::Content);
            if split {
                groups.push(Vec::new());
            }
            groups.last_mut().unwrap().push(k);
        }
        for g in groups {
            let ncols = g.iter().map(|&k| rows[k].len()).max().unwrap_or(0);
            let widths: Vec<usize> = (0..ncols).map(|j| g.iter().filter_map(|&k| rows[k].get(j)).map(|c| c.chars().count() + 1).max().unwrap_or(0)).collect();
            for &k in &g {
                let it = &items[k];
                let cells = &rows[k];
                let mut text = String::from("{");
                for (j, c) in cells.iter().enumerate() {
                    if j + 1 < cells.len() {
                        let cell = format!("{},", c);
                        let pad = widths[j].saturating_sub(cell.chars().count());
                        text.push_str(&cell);
                        text.push_str(&" ".repeat(pad + 1));
                    } else {
                        text.push_str(c);
                    }
                }
                text.push('}');
                self.flush_to(it.line);
                self.push_line(format!("{}- {}", " ".repeat(indent), text));
                if let Some(c) = &it.value.comment {
                    self.append(" ");
                    self.append(c);
                }
                self.consume_through(it.value.end_line.max(it.end_line));
            }
        }
    }

    fn emit_block_seq_inner(&mut self, items: &[Item], indent: usize, preserve: bool) {
        if let Some(first) = items.first() {
            let key = self.line_starts[first.line] + first.col;
            if let Some(&collapse) = self.table_targets.get(&key) {
                match self.table_rows(items, collapse) {
                    Some(rows) => {
                        let indent = if preserve { first.col } else { indent };
                        self.emit_table(items, &rows, indent);
                    }
                    // An incompatible target is kept as written.
                    None => {
                        for it in items {
                            self.emit_lines_verbatim(it.line, it.end_line.max(it.line));
                        }
                    }
                }
                return;
            }
        }
        let mut verbatim_rest = false;
        for (k, it) in items.iter().enumerate() {
            if k > 0 {
                let prev = &items[k - 1].orphans;
                self.emit_orphans(prev);
            }
            if !verbatim_rest && self.take_skip_before(it.line) {
                verbatim_rest = true;
            }
            if verbatim_rest || self.in_off_region(it.line) {
                self.emit_lines_verbatim(it.line, it.end_line.max(it.line));
                continue;
            }
            let col = if preserve { it.col } else { indent };
            self.col_delta = it.col as isize - col as isize;
            self.flush_to(it.line);
            self.push_line(" ".repeat(col));
            self.append("-");
            self.consume_through(it.line);
            let v = &it.value;
            let item_tpl = preserve && self.item_has_template(it);
            if item_tpl && !is_block_coll(v) {
                // Keep the whole item as written.
                self.consume_dirs_before(v.line.max(it.line) + 1);
                let ls = self.line_starts[it.line] + it.col + 1;
                let end_line = it.end_line.max(it.line);
                if let Some(l) = self.out.last_mut() {
                    l.pop();
                }
                self.emit_verbatim_from(ls - 1, end_line);
                continue;
            }
            let compact_map = matches!(v.kind, Kind::Map(_)) && it.value_same_line && v.props.is_none();
            if (is_block_coll(v) && !compact_map) || (matches!(v.kind, Kind::Null) && v.props.is_some()) {
                self.stats.emitted_nodes += 1;
            }
            let multi_map = matches!(&v.kind, Kind::Map(es) if es.len() >= 2 || es.iter().any(|e| is_block_coll(&e.value)));
            if (matches!(v.kind, Kind::Seq(_)) || multi_map) && v.props.is_none() && it.dash_comment.is_none() && !it.trivia_before_value {
                if let Some(flow) = self.compact_text(v) {
                    if self.adj_len() + 1 + flow.chars().count() <= self.opts.line_width {
                        self.append(" ");
                        self.append(&flow);
                        self.consume_through(v.end_line);
                        continue;
                    }
                }
            }
            match &v.kind {
                Kind::Null => {
                    if let Some(p) = &v.props {
                        let t = self.src[p.start..p.end].to_string();
                        self.append(" ");
                        self.append(&t);
                    }
                    if let Some(c) = &it.dash_comment {
                        self.append(" ");
                        self.append(c);
                    }
                }
                Kind::Map(entries) => {
                    let child_preserve = self.node_has_template(v);
                    if let Some(p) = &v.props {
                        let t = self.props_text(p);
                        if !t.is_empty() {
                            self.append(" ");
                            self.append(&t);
                        }
                        let pl = self.line_of(p.start);
                        let rest = self.src[p.end..self.line_end_pos(pl)].trim().to_string();
                        if !rest.is_empty() {
                            self.append(" ");
                            self.append(&rest);
                        }
                        self.consume_through(pl);
                        let ci = if child_preserve { entries[0].col } else { col + self.opts.indent_width };
                        self.emit_block_map(entries, ci, false, false, child_preserve);
                    } else if it.value_same_line {
                        if child_preserve {
                            let gap = entries[0].col.saturating_sub(col + 1).max(1);
                            self.append(&" ".repeat(gap));
                        } else {
                            self.append(" ");
                        }
                        let ci = col + 2;
                        self.first_item = k == 0;
                        self.emit_block_map(entries, ci, true, true, child_preserve);
                        self.first_item = false;
                    } else {
                        if let Some(c) = &it.dash_comment {
                            self.append(" ");
                            self.append(c);
                        }
                        let ci = col + self.opts.indent_width;
                        self.emit_block_map(entries, ci, false, false, child_preserve);
                    }
                }
                Kind::Seq(sub) => {
                    let child_preserve = self.node_has_template(v);
                    if let Some(p) = &v.props {
                        let t = self.props_text(p);
                        if !t.is_empty() {
                            self.append(" ");
                            self.append(&t);
                        }
                        let pl = self.line_of(p.start);
                        let rest = self.src[p.end..self.line_end_pos(pl)].trim().to_string();
                        if !rest.is_empty() {
                            self.append(" ");
                            self.append(&rest);
                        }
                        self.consume_through(pl);
                    } else if let Some(c) = &it.dash_comment {
                        self.append(" ");
                        self.append(c);
                    }
                    let ci = col + self.opts.indent_width;
                    self.emit_block_seq(sub, ci, child_preserve);
                }
                _ => {
                    if it.verbatim_line {
                        let le = self.line_end_pos(v.line);
                        let t = self.src[v.start..le].trim_end().to_string();
                        self.append(" ");
                        self.append(&t);
                        self.consume_through(v.end_line);
                        continue;
                    }
                    if !it.value_same_line && (it.trivia_before_value || it.dash_comment.is_some()) {
                        if let Some(c) = &it.dash_comment {
                            self.append(" ");
                            self.append(c);
                        }
                        self.flush_to(v.line);
                        for l in v.line..=v.end_line {
                            let t = self.lines[l].to_string();
                            self.push_line(t);
                        }
                        self.consume_through(v.end_line);
                        continue;
                    }
                    self.append(" ");
                    self.value_counted = true;
                    self.emit_value_inline_or_block(v, col, false, false);
                    if self.value_counted {
                        self.stats.emitted_nodes += 1;
                    }
                    self.value_counted = true;
                }
            }
        }
    }
}

/// Rewrap folded block scalar content lines. Only a single plain paragraph that
/// exceeds the width is refilled; returns the filled lines and the number of
/// source content lines replaced.
fn refold_lines(lines: &[String], width: usize) -> Option<(Vec<String>, usize)> {
    let mut content: Vec<&String> = lines.iter().collect();
    while let Some(l) = content.last() {
        if l.is_empty() {
            content.pop();
        } else {
            break;
        }
    }
    let single_para = !content.is_empty()
        && content.iter().all(|l| !l.is_empty() && !l.starts_with(' ') && !l.starts_with('\t') && !l.ends_with(' ') && !l.ends_with('\t'));
    if !single_para {
        return None;
    }
    let joined = content.iter().map(|s| s.as_str()).collect::<Vec<_>>().join(" ");
    if joined.chars().count() <= width {
        return None;
    }
    Some((fill_words(&joined, width), content.len()))
}

/// Re-indent raw block scalar lines from content indent `ci` to `new_ci`.
fn reindent_raw(raw: &[String], ci: usize, new_ci: usize) -> Vec<String> {
    if ci == new_ci {
        return raw.to_vec();
    }
    raw.iter()
        .map(|l| {
            let ind = l.len() - l.trim_start_matches(' ').len();
            let blank = l.trim_start_matches(' ').is_empty();
            if blank {
                if ind >= ci && ci > 0 {
                    " ".repeat(new_ci + ind - ci)
                } else {
                    String::new()
                }
            } else if ind >= ci {
                format!("{}{}", " ".repeat(new_ci), &l[ci..])
            } else {
                l.clone()
            }
        })
        .collect()
}

pub fn double_quote(s: &str) -> String {
    let mut out = String::from("\"");
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\t' => out.push_str("\\t"),
            '\r' => out.push_str("\\r"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\x{:02x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

/// Tags of the YAML core schema and the other `!!` tags YAML defines.
fn is_core_tag(t: &str) -> bool {
    t.strip_prefix("!!").is_some_and(|n| matches!(n, "str" | "int" | "float" | "bool" | "null" | "map" | "seq" | "omap" | "pairs" | "set" | "binary" | "timestamp" | "merge" | "value" | "yaml"))
}

fn core_tagged_scalar(tag: &str, sc: &Scalar, src: &str, in_flow: bool) -> String {
    let val = &sc.value;
    match tag {
        "!!str" => {
            if plain_safe(val, in_flow) {
                val.clone()
            } else if !val.contains('\'') && !val.contains('\n') && val.chars().all(|c| c != '\t') {
                format!("'{}'", val)
            } else {
                src[sc.start..sc.end].to_string()
            }
        }
        "!!null" => {
            if val.is_empty() || is_null_word(val) {
                "null".to_string()
            } else {
                src[sc.start..sc.end].to_string()
            }
        }
        _ => {
            if sc.style != ScalarStyle::Plain && !val.is_empty() && !val.contains(['\n', ' ', '#', ':', ',', '[', ']', '{', '}']) {
                val.clone()
            } else {
                src[sc.start..sc.end].to_string()
            }
        }
    }
}

pub enum Requoted {
    Quoted(String),
    Literal,
}

/// Characters that only a double-quoted scalar can carry (as escapes).
pub fn needs_escape(val: &str) -> bool {
    val.chars().any(|c| c == '\t' || !is_yaml_printable(c))
}

fn is_yaml_printable(c: char) -> bool {
    match c {
        '\u{20}'..='\u{7e}' => true,
        '\u{a0}'..='\u{d7ff}' => true,
        '\u{e000}'..='\u{fffd}' => c != '\u{feff}',
        '\u{10000}'..='\u{10ffff}' => true,
        _ => false,
    }
}

/// Choose a quoted spelling that avoids escapes where possible.
pub fn requote(val: &str, orig: ScalarStyle, _flow: bool) -> Requoted {
    if needs_escape(val) {
        return Requoted::Quoted(double_quote(val));
    }
    let single_ok = !val.contains('\'');
    let double_ok = !val.contains('"') && !val.contains('\\');
    let prefer_single = orig == ScalarStyle::Single;
    if prefer_single {
        if single_ok {
            return Requoted::Quoted(format!("'{}'", val));
        }
        if double_ok {
            return Requoted::Quoted(format!("\"{}\"", val));
        }
    } else {
        if double_ok {
            return Requoted::Quoted(format!("\"{}\"", val));
        }
        if single_ok {
            return Requoted::Quoted(format!("'{}'", val));
        }
    }
    Requoted::Literal
}

pub fn single_quote_escaped(val: &str) -> String {
    format!("'{}'", val.replace('\'', "''"))
}

/// Apply Markdown option words from a directive (`wrap=`, `canonical`, ...).
pub fn apply_md_words(o: &mut Options, words: &[String]) {
    for w in words {
        if let Some(v) = w.strip_prefix("wrap=") {
            if let Some(wr) = crate::options::parse_wrap(v) {
                o.wrap = wr;
            }
        } else if w == "canonical" {
            o.canonical = true;
        } else if let Some(v) = w.strip_prefix("canonical=") {
            o.canonical = matches!(v, "true" | "yes" | "1");
        } else if let Some(v) = w.strip_prefix("footnotes=") {
            o.preserve_footnotes = matches!(v, "preserve" | "none" | "false" | "no" | "0");
        } else if let Some(v) = w.strip_prefix("table-widths=") {
            o.table_widths = if v == "preserve" { crate::options::TableWidths::Preserve } else { crate::options::TableWidths::Fit };
        }
    }
}
