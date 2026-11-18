// Markdown block formatting.

use super::block::*;
use super::inline;
use super::table;
use super::width::width;
use super::wrap;
use crate::format_cmd::Diagnostic;
use crate::options::{Options, Wrap};

pub struct Fmt<'a> {
    pub opts: Options,
    pub notes: &'a mut Vec<Diagnostic>,
    /// Count of paragraphs whose wrapping failed (forces list segment fallback).
    pub para_failures: usize,
    wrap_failed: std::cell::Cell<bool>,
    /// Nesting depth of list items, quotes and footnotes.
    pub container_depth: usize,
    /// Report notes for delegated fences (top-level documents only).
    pub emit_notes: bool,
    /// Nesting depth of block quotes; YAML fences inside them are kept.
    quote_depth: usize,
    /// Options from a `scope=next` directive waiting for the next block.
    pending_next: Option<Vec<String>>,
    /// The paragraph being formatted starts on a list marker line.
    marker_line: std::cell::Cell<bool>,
}

thread_local! {
    /// Embedded Markdown (comments, YAML scalars) keeps trailing whitespace on
    /// lines it reproduces as written.
    static KEEP_TRAILING: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

pub fn with_keep_trailing<T>(v: bool, f: impl FnOnce() -> T) -> T {
    let prev = KEEP_TRAILING.with(|c| c.replace(v));
    let r = f();
    KEEP_TRAILING.with(|c| c.set(prev));
    r
}

fn keep_trailing() -> bool {
    KEEP_TRAILING.with(|c| c.get())
}

fn rtrim(s: &str) -> String {
    if KEEP_TRAILING.with(|c| c.get()) {
        return s.to_string();
    }
    s.trim_end().to_string()
}

/// Whether a nested list sits two or more columns right of its parent item's content.
fn has_indented_sublist(blocks: &[Block]) -> bool {
    blocks.iter().any(|b| match b {
        Block::List(l) => l.items.iter().any(|it| {
            it.children.iter().any(|c| matches!(c, Block::List(sub) if sub.items.first().map(|f| f.col >= 2).unwrap_or(false))) || has_indented_sublist(&it.children)
        }),
        _ => false,
    })
}

fn wrap_col(w: Wrap) -> usize {
    match w {
        Wrap::Column(n) => n,
        Wrap::Sentence(Some(n)) => n,
        _ => usize::MAX / 4,
    }
}

impl<'a> Fmt<'a> {
    pub fn new(opts: Options, notes: &'a mut Vec<Diagnostic>) -> Self {
        Fmt { opts, notes, para_failures: 0, wrap_failed: std::cell::Cell::new(false), container_depth: 0, emit_notes: false, quote_depth: 0, pending_next: None, marker_line: std::cell::Cell::new(false) }
    }

    /// Total width available for content starting at `col`.
    fn avail(&self, total: usize, col: usize) -> usize {
        total.saturating_sub(col).max(1)
    }

    /// Format a paragraph's lines. Returns None if the paragraph must be kept as written.
    pub fn format_para(&self, lines: &[String], first_width: usize, rest_width: usize) -> Option<Vec<String>> {
        let text: String = lines.iter().map(|l| l.trim_start().to_string()).collect::<Vec<_>>().join("\n");
        let trailing_break = lines.last().map(|l| {
            let t = l.trim_end_matches(' ');
            l.len() - t.len() >= 2 && !t.trim().is_empty()
        }).unwrap_or(false);
        let text = text.trim_end().to_string();
        let text = if self.opts.canonical { inline::canonicalize(&text, &self.opts.templates) } else { text };
        self.wrap_failed.set(false);
        let unescape = matches!(self.opts.wrap, crate::options::Wrap::Column(_));
        let mut sc = inline::scan_opts(&text, &self.opts.templates, unescape);
        if sc.unsupported {
            if !sc.html_only {
                self.wrap_failed.set(true);
            }
            return None;
        }
        if trailing_break {
            sc.units.push(inline::Unit { text: "\\".into(), kind: inline::UnitKind::HardBreak, link_split: Vec::new(), multiline: false });
        }
        // A paragraph opening with an ordered list marker (written alone on its line)
        // escapes it, unmeasured, unless the marker ends up alone on the first line.
        let lead_escape = !self.marker_line.get()
            && sc.units.first().is_some_and(|u| u.kind == inline::UnitKind::Text && list_marker(&u.text).is_some_and(|m| m.ordered && m.empty));
        let mut r = wrap::wrap_units(&sc.units, self.opts.wrap, first_width, rest_width);
        if let Some(ls) = r.as_mut().filter(|_| lead_escape) {
            if ls[0] != sc.units[0].text {
                ls[0].insert(0, '\\');
            }
        }
        if r.is_none() {
            self.wrap_failed.set(true);
        }
        r
    }

    /// Format a definition's leading paragraph (without the marker).
    fn format_def(&self, first: &str, rest: &[String], raw: &[String], src_base: usize, total: usize) -> Option<Vec<String>> {
        let mut lines = vec![first.to_string()];
        lines.extend(rest[..def_lead(rest)].iter().cloned());
        let w = self.avail(total, src_base + indent_of(&raw[0]) + 2);
        self.format_para(&lines, w, w)
    }

    /// Format blocks of a container. `src_base` is the absolute source column of the
    /// container content and `out_base` the output column. `total` is the wrap column
    /// measured from the container's column 0.
    pub fn format_blocks(&mut self, blocks: &[Block], src_base: usize, out_base: usize, total: usize) -> Vec<String> {
        let mut total = total;
        let mut out: Vec<String> = Vec::new();
        let pad_out = " ".repeat(out_base);
        let pad_src = " ".repeat(src_base);
        for (bi, b) in blocks.iter().enumerate() {
            // Option directives: `from-here` changes the options for later blocks,
            // `next` for the following block only.
            if self.container_depth == 0 {
                if let Block::Comment(ls) | Block::Raw(ls) = b {
                    if let Some((words, scope)) = ls.first().filter(|_| ls.len() == 1).and_then(|l| super::option_directive(l)) {
                        match scope {
                            "from-here" => {
                                crate::yaml::emit::apply_md_words(&mut self.opts, &words);
                                total = wrap_col(self.opts.wrap);
                            }
                            "next" => self.pending_next = Some(words),
                            _ => {}
                        }
                    }
                } else if !matches!(b, Block::Blank(_)) {
                    if let Some(words) = self.pending_next.take() {
                        let saved = self.opts.clone();
                        crate::yaml::emit::apply_md_words(&mut self.opts, &words);
                        let t = wrap_col(self.opts.wrap);
                        let o = self.format_blocks(std::slice::from_ref(b), src_base, out_base, t);
                        self.opts = saved;
                        out.extend(o);
                        continue;
                    }
                }
            }
            let _ = bi;
            match b {
                Block::Blank(raw) => {
                    // Blank lines between two paragraphs collapse into one; embedded
                    // Markdown otherwise keeps a blank line's spaces.
                    let prev = blocks[..bi].iter().rev().find(|b| !matches!(b, Block::Blank(_)));
                    let next_at = blocks[bi + 1..].iter().position(|b| !matches!(b, Block::Blank(_))).map(|k| bi + 1 + k);
                    let next = next_at.map(|k| &blocks[k]);
                    // A definition term is not a paragraph here.
                    let next_para = match next {
                        Some(Block::Para(_)) => !matches!(next_at.and_then(|k| blocks.get(k + 1)), Some(Block::Def { .. })),
                        Some(Block::Setext { para, .. }) => !para.is_empty(),
                        _ => false,
                    };
                    let between_paras = matches!(prev, Some(Block::Para(_))) && next_para;
                    if between_paras {
                        if !matches!(blocks.get(bi.wrapping_sub(1)), Some(Block::Blank(_))) {
                            out.push(String::new());
                        }
                    } else if self.container_depth == 0 && keep_trailing() {
                        out.push(raw.clone());
                    } else {
                        out.push(String::new());
                    }
                }
                Block::Para(lines) if matches!(blocks.get(bi + 1), Some(Block::Def { .. })) => {
                    // Definition terms are kept as written.
                    for l in lines {
                        out.push(format!("{}{}", pad_src, l.trim_end()));
                    }
                }
                Block::Para(lines) if self.opts.wrap == Wrap::None && self.container_depth == 0 => {
                    // Unwrapped top-level paragraphs keep their lines; hard breaks are
                    // normalized unless the paragraph is unsupported.
                    let text: String = lines.iter().map(|l| l.trim().to_string()).collect::<Vec<_>>().join("\n");
                    let sc = inline::scan_opts(&text, &self.opts.templates, false);
                    let unsupported = sc.unsupported && !sc.html_only;
                    for (k, l) in lines.iter().enumerate() {
                        let t = l.trim_end_matches(' ');
                        let hard = l.len() - t.len() >= 2 && !t.trim().is_empty() && !unsupported;
                        let _ = k;
                        let mut line = format!("{}{}", pad_src, rtrim(t));
                        if hard {
                            line.push_str(" \\");
                        }
                        out.push(line);
                    }
                }
                Block::Para(lines) => {
                    let w = self.avail(total, out_base);
                    match self.format_para(lines, w, w) {
                        Some(ls) => {
                            for l in ls {
                                out.push(format!("{}{}", pad_out, l));
                            }
                        }
                        None => {
                            if self.wrap_failed.get() {
                                self.para_failures += 1;
                            }
                            for (k, l) in lines.iter().enumerate() {
                                if k == 0 {
                                    out.push(format!("{}{}", pad_out, rtrim(l.trim_start())));
                                } else {
                                    out.push(format!("{}{}", pad_src, rtrim(l)));
                                }
                            }
                        }
                    }
                }
                Block::Atx { level, content, indent } => {
                    out.push(format!("{}{}{}", pad_src, " ".repeat(*indent), self.format_heading(*level, content)));
                }
                Block::Setext { para, heading, level } => {
                    if !para.is_empty() {
                        let w = self.avail(total, out_base);
                        match self.format_para(para, w, w) {
                            Some(ls) => {
                                for l in ls {
                                    out.push(format!("{}{}", pad_out, l));
                                }
                            }
                            None => {
                                for l in para {
                                    out.push(format!("{}{}", pad_src, rtrim(l)));
                                }
                            }
                        }
                    }
                    let content = inline::collapse_ws(heading.trim());
                    out.push(format!("{}{}{}", pad_src, " ".repeat(indent_of(heading)), self.format_heading(*level, &content)));
                }
                Block::Hr => {
                    if src_base == 0 && out_base == 0 {
                        out.push(self.opts.hr_marker.clone());
                    } else {
                        out.push(format!("{}{}", pad_src, self.opts.hr_marker));
                    }
                }
                Block::Fence { open, body, close, info, indent, line } => {
                    let _ = indent;
                    out.extend(self.format_fence(open, body, close.as_deref(), info, src_base, *line));
                }
                Block::Raw(lines) | Block::Html(lines) | Block::Math(lines) | Block::RefDef(lines) | Block::Comment(lines) => {
                    for l in lines {
                        if l.trim().is_empty() {
                            out.push(String::new());
                        } else {
                            out.push(format!("{}{}", pad_src, rtrim(l)));
                        }
                    }
                }
                Block::Verbatim(lines) => {
                    for l in lines {
                        out.push(l.clone());
                    }
                }
                Block::Quote { raw, inner, lazy } => {
                    let bare_tex = inner.iter().any(|b| matches!(b, Block::Math(ls) if ls.len() == 1 && inline::has_bare_tex_command(&ls[0])));
                    // So does a quote whose lines are indented differently, and one without
                    // blank lines holding a heading, an HTML block, or a nested quote next to
                    // a paragraph.
                    let ragged = raw.iter().any(|l| indent_of(l) != indent_of(&raw[0]));
                    // So does a quote with a line indented four or more inside it.
                    let deep = raw.iter().any(|l| {
                        let t = l.trim_start().strip_prefix('>').unwrap_or("");
                        let t = t.strip_prefix(' ').unwrap_or(t);
                        !t.trim().is_empty() && indent_of(t) >= 4
                    });
                    let tangled = !inner.iter().any(|b| matches!(b, Block::Blank(_)))
                        && (inner.iter().any(|b| matches!(b, Block::Atx { .. } | Block::Setext { .. } | Block::Html(_) | Block::Quote { lazy: true, .. }))
                            || inner.windows(2).any(|w| matches!((&w[0], &w[1]), (Block::Para(_), Block::Quote { .. }) | (Block::Quote { .. }, Block::Para(_)))));
                    if *lazy || bare_tex || ragged || deep || tangled || has_indented_sublist(inner) {
                        for l in raw {
                            out.push(format!("{}{}", pad_src, rtrim(l)));
                        }
                        continue;
                    }
                    // The quote keeps the indentation of its first line.
                    let qind = indent_of(&raw[0]);
                    let inner_total = total.saturating_sub(src_base + qind + 2);
                    // Unwrapped multi-block quotes keep authored lines like the document.
                    let simple = inner.iter().filter(|b| !matches!(b, Block::Blank(_))).count() <= 1;
                    let bump = if self.opts.wrap == Wrap::None && !simple { 0 } else { 1 };
                    self.container_depth += bump;
                    self.quote_depth += 1;
                    let inner_out = self.format_blocks(inner, 0, 0, inner_total);
                    self.quote_depth -= 1;
                    self.container_depth -= bump;
                    let qpad = format!("{}{}", pad_src, " ".repeat(qind));
                    for l in inner_out {
                        if l.is_empty() {
                            out.push(format!("{}>", qpad));
                        } else {
                            out.push(format!("{}> {}", qpad, l));
                        }
                    }
                }
                Block::List(list) => {
                    out.extend(self.format_list(list, src_base, total));
                }
                Block::Table(lines) => {
                    let canon = if self.opts.canonical { Some(&self.opts.templates) } else { None };
                    let t = table::format_pipe_table_c(lines, self.opts.table_widths, self.opts.compact_tables, canon);
                    match t {
                        Some(ls) => {
                            for l in ls {
                                out.push(format!("{}{}", pad_src, l));
                            }
                        }
                        None => {
                            for l in lines {
                                out.push(format!("{}{}", pad_src, rtrim(l)));
                            }
                        }
                    }
                }
                Block::GridTable(lines) => {
                    let stripped: Vec<String> = lines.iter().map(|l| l.trim_start().to_string()).collect();
                    match table::format_grid_table(&stripped, self.opts.table_widths) {
                        Some(ls) => {
                            let ind = " ".repeat(indent_of(&lines[0]));
                            for l in ls {
                                out.push(format!("{}{}{}", pad_src, ind, l));
                            }
                        }
                        None => {
                            for l in lines {
                                out.push(format!("{}{}", pad_src, rtrim(l)));
                            }
                        }
                    }
                }
                Block::Div { open, inner, close, raw } => {
                    let _ = raw;
                    // Fence lines keep their indentation.
                    out.push(format!("{}{}", pad_src, rtrim(open)));
                    // Directly inside a div, adjacent divs are separated by a blank line.
                    let mut spaced: Vec<Block> = Vec::with_capacity(inner.len());
                    for (k, b) in inner.iter().enumerate() {
                        if k > 0 && matches!(b, Block::Div { .. }) && matches!(inner[k - 1], Block::Div { .. }) {
                            spaced.push(Block::Blank(String::new()));
                        }
                        spaced.push(b.clone());
                    }
                    let inner_out = self.format_blocks(&spaced, src_base, out_base, total);
                    out.extend(inner_out);
                    if let Some(c) = close {
                        out.push(format!("{}{}", pad_src, rtrim(c)));
                    }
                }
                Block::Footnote { label, first, rest, raw } => {
                    out.extend(self.format_footnote(label, first, rest, raw, src_base, total));
                }
                Block::Def { marker, first, rest, raw } => {
                    // A definition list with a definition continued by an indented code
                    // fence, or with a definition that cannot be formatted, is kept as
                    // written.
                    let (ls, le) = def_list_range(blocks, bi);
                    let group = &blocks[ls..le];
                    let has_fence = group.iter().any(raw_has_fence);
                    let fails = group.iter().any(|b| match b {
                        Block::Def { first, rest, raw, .. } => !first.trim().is_empty() && self.format_def(first, rest, raw, src_base, total).is_none(),
                        _ => false,
                    });
                    if has_fence || fails {
                        for l in raw {
                            out.push(format!("{}{}", pad_src, rtrim(l)));
                        }
                        continue;
                    }
                    let dpad = format!("{}{}", pad_src, " ".repeat(indent_of(&raw[0])));
                    // An empty definition keeps the lines below it as written.
                    if first.trim().is_empty() {
                        out.push(format!("{}{}", dpad, marker));
                        for l in rest {
                            out.push(format!("{}{}", pad_src, rtrim(l)));
                        }
                        continue;
                    }
                    let lead = def_lead(rest);
                    match self.format_def(first, rest, raw, src_base, total) {
                        Some(ls) => {
                            for (k, l) in ls.into_iter().enumerate() {
                                if k == 0 {
                                    out.push(format!("{}{} {}", dpad, marker, l));
                                } else {
                                    out.push(format!("{}  {}", dpad, l));
                                }
                            }
                            for l in &rest[lead..] {
                                out.push(format!("{}{}", pad_src, rtrim(l)));
                            }
                        }
                        None => {
                            for l in raw {
                                out.push(format!("{}{}", pad_src, rtrim(l)));
                            }
                        }
                    }
                }
            }
        }
        out
    }

    fn format_heading(&self, level: usize, content: &str) -> String {
        let hashes = "#".repeat(level);
        let content = normalize_heading_content(content);
        let content = if self.opts.canonical { inline::canonicalize(&content, &self.opts.templates) } else { content };
        if content.is_empty() {
            hashes
        } else {
            format!("{} {}", hashes, content)
        }
    }

    fn format_fence(&mut self, open: &str, body: &[String], close: Option<&str>, info: &str, src_base: usize, line: Option<usize>) -> Vec<String> {
        let pad = " ".repeat(src_base);
        let mut out = Vec::new();
        let open_t = rtrim(open);
        out.push(format!("{}{}", pad, open_t));
        let lang = fence_lang(info);
        let fence_ind = indent_of(open);
        let body_stripped: Vec<String> = body.iter().map(|l| strip_cols(l, fence_ind)).collect();
        let mut formatted: Option<Vec<String>> = None;
        if close.is_some() && !info.contains("fmt: skip") {
            if lang == "yaml" || lang == "yml" {
                let src = if body_stripped.is_empty() { String::new() } else { format!("{}\n", body_stripped.join("\n")) };
                if let Ok(f) = crate::yaml::format_yaml(&src, &self.yaml_opts()) {
                    let f = f.strip_suffix('\n').unwrap_or(&f).to_string();
                    formatted = Some(if f.is_empty() && body_stripped.is_empty() { Vec::new() } else { f.split('\n').map(|s| s.to_string()).collect() });
                }
            } else if lang == "markdown" || lang == "md" {
                let src = body_stripped.join("\n");
                let base = if self.emit_notes && self.container_depth == 0 { line.map(|l| l + 1) } else { None };
                let f = super::format_fragment_at(&src, &self.opts, self.notes, base, base.map(|b| (b, fence_ind)));
                formatted = Some(f);
            } else if let Some(prog) = crate::source::formatter_program(&lang) {
                // Delegated languages: the external formatter is unavailable.
                let skipped = body_stripped.iter().take_while(|l| l.starts_with("#|")).any(|l| l.contains("fmt: skip"));
                if self.emit_notes && self.container_depth == 0 && !skipped {
                    if let Some(l) = line {
                        self.notes.push(Diagnostic { line: l + 2, col: 1, msg: format!("missing optional embedded formatter `{}`; preserved source", prog) });
                    }
                }
            }
        }
        let fence_pad = " ".repeat(fence_ind);
        match formatted {
            Some(ls) => {
                for l in ls {
                    if l.is_empty() {
                        out.push(String::new());
                    } else {
                        out.push(format!("{}{}{}", pad, fence_pad, l));
                    }
                }
            }
            None => {
                for l in body {
                    if l.trim().is_empty() {
                        out.push(String::new());
                    } else {
                        out.push(format!("{}{}", pad, rtrim(l)));
                    }
                }
            }
        }
        if let Some(c) = close {
            out.push(format!("{}{}", pad, rtrim(c)));
        }
        out
    }

    fn yaml_opts(&self) -> Options {
        self.opts.clone()
    }

    fn format_footnote(&mut self, label: &str, first: &str, rest: &[String], raw: &[String], src_base: usize, total: usize) -> Vec<String> {
        let pad = " ".repeat(src_base);
        if self.opts.preserve_footnotes {
            return raw.iter().map(|l| if l.trim().is_empty() { String::new() } else { format!("{}{}", pad, rtrim(l)) }).collect();
        }
        // Multi-block footnotes, or ones whose text starts on the next line, use
        // block style with four-space indented content.
        if rest.iter().any(|l| is_blank(l)) || first.trim().is_empty() {
            let mut content: Vec<String> = Vec::new();
            if !first.trim().is_empty() {
                content.push(first.to_string());
            }
            for l in rest {
                content.push(strip_cols(l, 4.min(indent_of(l))));
            }
            let blocks = parse_blocks(&content);
            let mut out = vec![format!("{}[^{}]:", pad, label)];
            let bump = if self.opts.wrap == Wrap::None { 0 } else { 1 };
            self.container_depth += bump;
            let inner = self.format_blocks(&blocks, src_base + 4, src_base + 4, total);
            self.container_depth -= bump;
            out.extend(inner);
            return out;
        }
        let prefix = format!("[^{}]: ", label);
        let mut lines = vec![first.to_string()];
        lines.extend(rest.iter().cloned());
        let fw = self.avail(total, src_base + width(&prefix));
        let rw = self.avail(total, src_base + 2);
        match self.format_para(&lines, fw, rw) {
            Some(ls) => {
                let mut out = Vec::new();
                for (i, l) in ls.into_iter().enumerate() {
                    if i == 0 {
                        out.push(format!("{}{}{}", pad, prefix, l));
                    } else {
                        out.push(format!("{}  {}", pad, l));
                    }
                }
                out
            }
            None => raw.iter().map(|l| if l.trim().is_empty() { String::new() } else { format!("{}{}", pad, rtrim(l)) }).collect(),
        }
    }

    fn list_supported(&self, list: &List, depth: usize, shifted: bool) -> bool {
        let mut prev = usize::MAX;
        list.items.iter().all(|item| {
            let ok = self.item_supported(item, depth, shifted, prev);
            prev = item.col;
            ok
        })
    }

    /// `prev_col` is the marker column of the preceding sibling (usize::MAX for the first).
    fn item_supported(&self, item: &Item, depth: usize, shifted: bool, prev_col: usize) -> bool {
        if item.lazy || (prev_col != usize::MAX && item.col > prev_col) {
            return false;
        }
        let shift = shifted || item.content_col != item.col + norm_marker(&item.marker, item.ordered).len() + 1;
        let mut seen_list = false;
        let mut para_count = 0;
        let children = item_children(item);
        // Text right below an empty marker line joins it only in a bullet item, and only
        // when aligned with the content column.
        if item.empty_first {
            if let Some(Block::Para(lines)) = children.first() {
                if item.ordered || lines[0].starts_with([' ', '\t']) {
                    return false;
                }
            }
        }
        for c in children {
            match c {
                Block::Raw(_) => return false,
                Block::Math(ls) if ls.len() == 1 && inline::has_bare_tex_command(&ls[0]) => return false,
                Block::Atx { .. } | Block::Setext { .. } => return false,
                Block::Div { open, .. } if indent_of(open) > 0 => return false,
                Block::Quote { raw, .. } => {
                    let r = indent_of(&raw[0]);
                    if shift || (r > 0 && item.content_col - item.col + r >= 4) {
                        return false;
                    }
                }
                Block::List(sub) => {
                    if !self.list_supported(sub, depth + 1, shift) {
                        return false;
                    }
                    seen_list = true;
                }
                Block::Para(lines) => {
                    if seen_list {
                        return false;
                    }
                    // Lines indented past the content column and four or more past the
                    // marker (continuation lines four past a task item's text). The first
                    // line of the first paragraph sits on the marker line.
                    let deep = |l: &String| {
                        let r = indent_of(l);
                        if para_count == 0 && item.task_shift > 0 {
                            r >= 4
                        } else {
                            r > 0 && item.content_col - item.col + r >= 4
                        }
                    };
                    let skip = usize::from(para_count == 0);
                    if item.task_misaligned || lines.iter().skip(skip).any(deep) {
                        return false;
                    }
                    para_count += 1;
                    if depth > 0 && para_count > 1 {
                        return false;
                    }
                }
                _ => {}
            }
        }
        true
    }

    fn format_list(&mut self, list: &List, src_base: usize, total: usize) -> Vec<String> {
        // Items separated by blank lines form independent segments; a segment with an
        // unsupported item is kept as written.
        let mut segments: Vec<Vec<usize>> = Vec::new();
        let mut cur: Vec<usize> = Vec::new();
        for (k, item) in list.items.iter().enumerate() {
            cur.push(k);
            if matches!(item.children.last(), Some(Block::Blank(_))) {
                segments.push(std::mem::take(&mut cur));
            }
        }
        if !cur.is_empty() {
            segments.push(cur);
        }
        let mut out = Vec::new();
        for seg in segments {
            let ok = seg.iter().all(|&k| {
                let prev = if k == 0 { usize::MAX } else { list.items[k - 1].col };
                self.item_supported(&list.items[k], 0, false, prev)
            });
            if !ok {
                for &k in &seg {
                    for l in &list.items[k].raw {
                        out.push(if l.trim().is_empty() { String::new() } else { format!("{}{}", " ".repeat(src_base), rtrim(l)) });
                    }
                }
                continue;
            }
            let before = self.para_failures;
            let mut seg_out = Vec::new();
            for &k in &seg {
                let item = &list.items[k];
                seg_out.extend(self.format_item(item, src_base, total));
            }
            if self.para_failures > before {
                for &k in &seg {
                    for l in &list.items[k].raw {
                        out.push(if l.trim().is_empty() { String::new() } else { format!("{}{}", " ".repeat(src_base), rtrim(l)) });
                    }
                }
                continue;
            }
            out.extend(seg_out);
        }
        out
    }

    fn format_item(&mut self, item: &Item, src_base: usize, total: usize) -> Vec<String> {
        self.container_depth += 1;
        let r = self.format_item_inner(item, src_base, total);
        self.container_depth -= 1;
        r
    }

    fn format_item_inner(&mut self, item: &Item, src_base: usize, total: usize) -> Vec<String> {
        let mut out = Vec::new();
        {
            let marker = norm_marker(&item.marker, item.ordered);
            let abs_col = src_base + item.col;
            let new_cc = abs_col + width(&marker) + 1;
            let src_cc = src_base + item.content_col;
            let prefix = format!("{}{} ", " ".repeat(abs_col), marker);
            // Task list marker.
            let mut children = item_children(item).to_vec();
            let mut task: Option<String> = None;
            if let Some(Block::Para(lines)) = children.first() {
                let t = lines[0].trim_start();
                for tm in ["[ ]", "[x]", "[X]"] {
                    if let Some(rest) = t.strip_prefix(tm) {
                        if rest.starts_with(' ') || rest.is_empty() {
                            task = Some(tm.to_string());
                            let mut nl = lines.clone();
                            nl[0] = rest.trim_start().to_string();
                            children[0] = Block::Para(nl);
                        }
                        break;
                    }
                }
            }
            let mut item_out: Vec<String> = Vec::new();
            let mut first_done = false;
            for (ci, c) in children.iter().enumerate() {
                match c {
                    Block::Para(lines) if ci == 0 => {
                        let (fw, rw, cont_pad) = match &task {
                            Some(tm) => {
                                let fw = self.avail(total, new_cc + tm.len() + 1);
                                (fw, fw, new_cc + tm.len() + 1)
                            }
                            None => {
                                let w = self.avail(total, new_cc);
                                (w, w, new_cc)
                            }
                        };
                        let empty_para = lines.len() == 1 && lines[0].trim().is_empty();
                        self.marker_line.set(true);
                        let formatted = if empty_para { Some(vec![String::new()]) } else { self.format_para(lines, fw, rw) };
                        self.marker_line.set(false);
                        match formatted {
                            Some(ls) => {
                                for (k, l) in ls.into_iter().enumerate() {
                                    if k == 0 {
                                        let mut first = prefix.clone();
                                        if let Some(tm) = &task {
                                            first.push_str(tm);
                                            if !l.is_empty() {
                                                first.push(' ');
                                            }
                                        }
                                        first.push_str(&l);
                                        item_out.push(first.trim_end().to_string());
                                    } else {
                                        item_out.push(format!("{}{}", " ".repeat(cont_pad), l));
                                    }
                                }
                            }
                            None => {
                                if self.wrap_failed.get() {
                                    self.para_failures += 1;
                                }
                                for (k, l) in lines.iter().enumerate() {
                                    if k == 0 {
                                        let mut first = prefix.clone();
                                        if let Some(tm) = &task {
                                            first.push_str(tm);
                                            first.push(' ');
                                        }
                                        first.push_str(&rtrim(l.trim_start()));
                                        item_out.push(first);
                                    } else {
                                        item_out.push(format!("{}{}", " ".repeat(src_cc + item.task_shift), rtrim(l)));
                                    }
                                }
                            }
                        }
                        first_done = true;
                    }
                    _ => {
                        let mut sub = self.format_blocks(std::slice::from_ref(c), src_cc, new_cc, total);
                        // A table indented past the content column keeps its offset.
                        if let Block::Table(ls) = c {
                            let r = indent_of(&ls[0]);
                            if r > 0 && sub.len() == ls.len() && sub.iter().zip(ls).any(|(a, b)| a.trim() != b.trim()) {
                                sub = sub.into_iter().map(|l| format!("{}{}", " ".repeat(r), l)).collect();
                            }
                        }
                        if !first_done && item.empty_first && !matches!(c, Block::Blank(_)) {
                            // A block below an empty marker line stays there.
                            item_out.push(prefix.trim_end().to_string());
                            item_out.extend(sub);
                            first_done = true;
                            continue;
                        }
                        if !first_done {
                            // Item without leading paragraph (e.g. empty item or nested block first).
                            if let Block::Blank(_) = c {
                                item_out.push(prefix.trim_end().to_string());
                                first_done = true;
                                item_out.push(String::new());
                                continue;
                            }
                            let mut it = sub.into_iter();
                            if let Some(f) = it.next() {
                                let f_trim = f.trim_start().to_string();
                                item_out.push(format!("{}{}", prefix, f_trim).trim_end().to_string());
                            }
                            item_out.extend(it);
                            first_done = true;
                            continue;
                        }
                        item_out.extend(sub);
                    }
                }
            }
            if !first_done {
                item_out.push(prefix.trim_end().to_string());
            }
            out.extend(item_out);
        }
        out
    }
}

/// An item's blocks, without the blank line left by an empty marker line.
fn item_children(item: &Item) -> &[Block] {
    match item.children.first() {
        Some(Block::Blank(_)) if item.empty_first => &item.children[1..],
        _ => &item.children,
    }
}

fn raw_has_fence(b: &Block) -> bool {
    match b {
        Block::Raw(ls) => ls.iter().any(|l| {
            let t = l.trim_start();
            t.starts_with("```") || t.starts_with("~~~")
        }),
        _ => false,
    }
}

/// Whether the definition list containing the definition at `bi` has a fenced continuation.
/// Continuation lines indented four spaces join a definition; from the first
/// shallower line on, lines are kept as written.
fn def_lead(rest: &[String]) -> usize {
    rest.iter().take_while(|l| l.starts_with("    ")).count()
}

/// The range of blocks forming the definition list holding the definition at `bi`.
fn def_list_range(blocks: &[Block], bi: usize) -> (usize, usize) {
    // Find the start of the list: walk back over term/definition groups.
    let mut start = bi;
    loop {
        // start points at a Def; its term is the Para before it (if any).
        let mut k = start;
        while k > 0 && matches!(blocks[k - 1], Block::Def { .. }) {
            k -= 1;
        }
        if k > 0 && matches!(blocks[k - 1], Block::Para(_)) {
            k -= 1;
        }
        // Previous group?
        let mut j = k;
        while j > 0 && matches!(blocks[j - 1], Block::Blank(_) | Block::Raw(_)) {
            j -= 1;
        }
        if j > 0 && matches!(blocks[j - 1], Block::Def { .. }) && j < k {
            start = j - 1;
            continue;
        }
        start = k;
        break;
    }
    let mut k = start;
    while k < blocks.len() {
        match &blocks[k] {
            Block::Para(_) => {
                if k + 1 < blocks.len() && matches!(blocks[k + 1], Block::Def { .. }) {
                    k += 1;
                    continue;
                }
                break;
            }
            Block::Def { .. } | Block::Blank(_) | Block::Raw(_) => {}
            _ => break,
        }
        k += 1;
    }
    (start, k)
}

pub fn norm_marker(m: &str, ordered: bool) -> String {
    if ordered {
        m.to_string()
    } else {
        "-".to_string()
    }
}

fn fence_lang(info: &str) -> String {
    let t = info.trim();
    let t = t.strip_prefix('{').unwrap_or(t);
    let t = t.strip_prefix('.').unwrap_or(t);
    let word: String = t.chars().take_while(|c| !c.is_whitespace() && *c != '}' && *c != ',').collect();
    word.to_ascii_lowercase()
}

/// Normalize heading text: collapse whitespace and tidy trailing attributes.
fn normalize_heading_content(s: &str) -> String {
    let t = s.trim();
    // Attribute block at end.
    if t.ends_with('}') {
        if let Some(p) = t.rfind('{') {
            let before = t[..p].trim_end();
            let attrs = &t[p + 1..t.len() - 1];
            if !before.is_empty() && (attrs.trim_start().starts_with('#') || attrs.trim_start().starts_with('.') || attrs.contains('=')) {
                let a = collapse_attr_ws(attrs.trim());
                return format!("{} {{{}}}", inline::collapse_ws(before), a);
            }
        }
    }
    inline::collapse_ws(t)
}

fn collapse_attr_ws(s: &str) -> String {
    // Collapse whitespace outside quotes.
    let mut out = String::new();
    let mut in_q: Option<char> = None;
    let mut prev_ws = false;
    for c in s.chars() {
        if let Some(q) = in_q {
            out.push(c);
            if c == q {
                in_q = None;
            }
            continue;
        }
        if c == '"' || c == '\'' {
            in_q = Some(c);
            out.push(c);
            prev_ws = false;
            continue;
        }
        if c.is_whitespace() {
            if !prev_ws {
                out.push(' ');
            }
            prev_ws = true;
        } else {
            out.push(c);
            prev_ws = false;
        }
    }
    out
}
