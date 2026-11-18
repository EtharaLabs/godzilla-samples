// Markdown formatting.

pub mod block;
pub mod format;
pub mod inline;
pub mod table;
pub mod width;
pub mod wrap;

use crate::format_cmd::Diagnostic;
use crate::options::{Options, TableWidths, Wrap};
use block::Block;

fn split_lines(text: &str) -> Vec<String> {
    let body = text.strip_suffix('\n').unwrap_or(text);
    if body.is_empty() && text.is_empty() {
        return Vec::new();
    }
    body.split('\n').map(|s| s.to_string()).collect()
}

/// Option words and scope of an option-only directive comment
/// (`<!-- fmt: wrap=40 scope=from-here -->`); the default scope is the file.
pub fn option_directive(line: &str) -> Option<(Vec<String>, &'static str)> {
    let d = directive_of(line)?;
    let mut words = Vec::new();
    // `markdown` options apply to the next block unless scoped otherwise.
    let (d, mut scope) = match d.strip_prefix("markdown") {
        Some(rest) if rest.is_empty() || rest.starts_with(char::is_whitespace) => (rest.to_string(), "next"),
        _ => (d, "file"),
    };
    for w in d.split_whitespace() {
        match w.strip_prefix("scope=") {
            Some("next") => scope = "next",
            Some("from-here") => scope = "from-here",
            Some(_) => scope = "file",
            None => words.push(w.to_string()),
        }
    }
    let is_option = |w: &String| w.contains('=') || w == "canonical";
    if words.is_empty() || !words.iter().all(is_option) {
        return None;
    }
    Some((words, scope))
}

/// Directive comment lines outside containers, in document order, as (0-based
/// line, line text). `line0` is the line of the first block.
fn directive_lines(blocks: &[Block], line0: usize, out: &mut Vec<(usize, String)>) {
    let mut line = line0;
    for b in blocks {
        match b {
            Block::Comment(ls) | Block::Para(ls) | Block::Raw(ls) => {
                for (k, l) in ls.iter().enumerate() {
                    if directive_of(l).is_some() {
                        out.push((line + k, l.clone()));
                    }
                }
            }
            Block::Div { inner, .. } => directive_lines(inner, line + 1, out),
            _ => {}
        }
        line += block::line_count(b);
    }
}

/// Check directive comments in document order, up to a `skip file` directive.
/// The block after a `skip` directive is checked too, `fmt: off` regions are not.
/// `lines` are the source lines from `line0` on.
fn check_directives(blocks: &[Block], lines: &[String], line0: usize) -> Result<bool, Diagnostic> {
    use crate::yaml::directive::{check_markdown, check_option_word, check_toggle, DirKind};
    let mut found = Vec::new();
    for b in blocks {
        match b {
            Block::Verbatim(ls) if directive_of(&ls[0]).is_some_and(|d| d.starts_with("skip")) => {
                directive_lines(&block::parse_blocks(&ls[1..]), 0, &mut found);
            }
            _ => directive_lines(std::slice::from_ref(b), 0, &mut found),
        }
    }
    // Locate the lines in the source, in order.
    let mut next = 0;
    let mut located = Vec::new();
    for (_, l) in found {
        if let Some(k) = lines[next..].iter().position(|s| *s == l) {
            located.push((line0 + next + k, l));
            next += k + 1;
        }
    }
    for (n, l) in located {
        let Some(d) = directive_of(&l) else { continue };
        let col = l[..l.find("fmt:").unwrap_or(0)].chars().count() + 1;
        let words: Vec<&str> = d.split_whitespace().collect();
        let r = match words.first().copied() {
            None => Err("invalid fmt directive: empty".to_string()),
            Some("skip" | "off" | "on") => match check_toggle(&words) {
                Ok(DirKind::SkipFile) => return Ok(true),
                r => r.map(|_| ()),
            },
            Some("markdown") => check_markdown(&words[1..]),
            Some(w) if w.contains('=') || w == "canonical" => words.iter().try_for_each(|w| check_option_word(w)),
            Some(_) => Err(format!("invalid fmt directive: {}", d)),
        };
        r.map_err(|m| Diagnostic::new(n + 1, col, m))?;
    }
    Ok(false)
}

/// Check the directives of a document unless its front matter is unreadable (the
/// document is then kept as written).
fn check_text_directives(all: &[String]) -> Result<(), Diagnostic> {
    let fm_end = front_matter_end(all);
    let fm_ok = fm_end.is_none_or(|end| end <= 1 || crate::yaml::parser::Parser::new(&format!("{}\n", all[1..end].join("\n"))).parse_stream().is_ok());
    if fm_ok {
        let body_start = fm_end.map_or(0, |e| e + 1);
        check_directives(&parse_with_directives(&all[body_start..], None), &all[body_start..], body_start)?;
    }
    Ok(())
}

fn directive_of(line: &str) -> Option<String> {
    let t = line.trim();
    let inner = t.strip_prefix("<!--")?.strip_suffix("-->")?.trim();
    let d = inner.strip_prefix("fmt:")?;
    Some(d.trim().to_string())
}

/// Find the end of YAML front matter starting at line 0.
fn front_matter_end(lines: &[String]) -> Option<usize> {
    if lines.is_empty() || lines[0].trim_end() != "---" {
        return None;
    }
    for (i, l) in lines.iter().enumerate().skip(1) {
        let t = l.trim_end();
        if t == "---" || t == "..." {
            return Some(i);
        }
    }
    None
}

/// Read editor_options.markdown settings from front matter YAML.
fn apply_front_matter_options(yaml: &str, opts: &mut Options) {
    let p = crate::yaml::parser::Parser::new(yaml);
    let src = yaml;
    let stream = match p.parse_stream() {
        Ok(s) => s,
        Err(_) => return,
    };
    // Options written after a structurally recovered line are not read.
    let recovered = crate::yaml::parser::last_struct_recovery();
    let root = match stream.docs.first().and_then(|d| d.root.as_ref()) {
        Some(r) => r,
        None => return,
    };
    let find = |n: &crate::yaml::parser::Node, key: &str| -> Option<crate::yaml::parser::Node> {
        if let crate::yaml::parser::Kind::Map(entries) = &n.kind {
            for e in entries {
                let k = &src[e.start..e.key_end];
                let k = k.trim_matches(|c| c == '"' || c == '\'');
                if k == key {
                    return Some(e.value.clone());
                }
            }
        }
        if let crate::yaml::parser::Kind::FlowMap(entries) = &n.kind {
            for e in entries {
                if let Some(k) = &e.key {
                    if let crate::yaml::parser::Kind::Scalar(sc) = &k.kind {
                        if sc.value == key {
                            return e.value.clone();
                        }
                    }
                }
            }
        }
        None
    };
    let md = match find(root, "editor_options").and_then(|eo| find(&eo, "markdown")) {
        Some(m) => Some(m),
        None => find(root, "editor").and_then(|e| find(&e, "markdown")),
    };
    let md = match md {
        Some(m) if recovered.is_none_or(|l| m.line < l) => m,
        _ => return,
    };
    let scalar = |n: Option<crate::yaml::parser::Node>| -> Option<String> {
        match n?.kind {
            crate::yaml::parser::Kind::Scalar(sc) => Some(sc.value),
            _ => None,
        }
    };
    if let Some(w) = scalar(find(&md, "wrap")) {
        if let Some(w) = crate::options::parse_wrap(&w) {
            opts.wrap = w;
        }
    }
    if let Some(c) = scalar(find(&md, "canonical")) {
        match c.as_str() {
            "true" | "yes" | "1" => opts.canonical = true,
            "false" | "no" | "0" => opts.canonical = false,
            _ => {}
        }
    }
    if let Some(f) = scalar(find(&md, "footnotes")) {
        match f.as_str() {
            "preserve" | "none" | "false" | "no" | "0" => opts.preserve_footnotes = true,
            "wrap" | "format" | "true" | "yes" | "1" => {}
            _ => {}
        }
    }
    if let Some(t) = scalar(find(&md, "table-widths")) {
        match t.as_str() {
            "fit" => opts.table_widths = TableWidths::Fit,
            "preserve" => opts.table_widths = TableWidths::Preserve,
            _ => {}
        }
    }
}

/// Parse blocks applying top-level preserve directives.
fn parse_with_directives(lines: &[String], base: Option<usize>) -> Vec<Block> {
    // Split at fmt: off/on regions and fmt: skip targets.
    let mut out: Vec<Block> = Vec::new();
    let mut seg_start = 0;
    let mut i = 0;
    let n = lines.len();
    let mut in_fence: Option<(char, usize)> = None;
    while i < n {
        let l = &lines[i];
        if let Some((ch, len)) = in_fence {
            let t = l.trim();
            if block::indent_of(l) <= 3 && t.chars().take_while(|&c| c == ch).count() >= len && t.chars().all(|c| c == ch) {
                in_fence = None;
            }
            i += 1;
            continue;
        }
        if let Some(f) = block::fence_open(l) {
            in_fence = Some((f.ch, f.len));
            i += 1;
            continue;
        }
        if block::indent_of(l) == 0 {
            if let Some(d) = directive_of(l) {
                if d == "off" || d == "off scope=from-here" {
                    out.extend(block::parse_blocks_at(&lines[seg_start..i], base.map(|b| b + seg_start)));
                    let s = i;
                    let mut j = i + 1;
                    while j < n {
                        if directive_of(&lines[j]).as_deref() == Some("on") {
                            break;
                        }
                        j += 1;
                    }
                    let e = if j < n { j + 1 } else { n };
                    out.push(Block::Verbatim(lines[s..e].to_vec()));
                    i = e;
                    seg_start = e;
                    continue;
                }
                if d == "skip" || d == "skip scope=next" {
                    out.extend(block::parse_blocks_at(&lines[seg_start..i], base.map(|b| b + seg_start)));
                    let s = i;
                    let mut j = i + 1;
                    while j < n && block::is_blank(&lines[j]) {
                        j += 1;
                    }
                    // Next block extent: parse from j and take the first block's line span.
                    let rest = &lines[j..];
                    let span = first_block_span(rest);
                    let e = (j + span).min(n);
                    out.push(Block::Verbatim(lines[s..e].to_vec()));
                    i = e;
                    seg_start = e;
                    continue;
                }
            }
        }
        i += 1;
    }
    out.extend(block::parse_blocks_at(&lines[seg_start..n], base.map(|b| b + seg_start)));
    out
}

/// Number of lines spanned by the first block of `lines`.
fn first_block_span(lines: &[String]) -> usize {
    if lines.is_empty() {
        return 0;
    }
    for k in 1..=lines.len() {
        let bs = block::parse_blocks(&lines[..k]);
        let full = block::parse_blocks(&lines[..lines.len().min(k + 1)]);
        if bs.len() == 1 && full.len() >= 2 {
            return k;
        }
        if full.len() == 1 && k == lines.len() {
            return k;
        }
    }
    lines.len()
}

fn has_skip_file(lines: &[String]) -> bool {
    let mut in_fence: Option<(char, usize)> = None;
    for l in lines {
        if let Some((ch, len)) = in_fence {
            let t = l.trim();
            if t.chars().take_while(|&c| c == ch).count() >= len && t.chars().all(|c| c == ch) {
                in_fence = None;
            }
            continue;
        }
        if let Some(f) = block::fence_open(l) {
            in_fence = Some((f.ch, f.len));
            continue;
        }
        if let Some(d) = directive_of(l) {
            if d == "skip file" || d == "skip scope=file" {
                return true;
            }
        }
    }
    false
}

fn wrap_total(w: Wrap) -> usize {
    match w {
        Wrap::Column(n) => n,
        Wrap::Sentence(Some(n)) => n,
        _ => usize::MAX / 4,
    }
}

thread_local! {
    /// The first invalid directive found in embedded Markdown.
    static FRAGMENT_ERROR: std::cell::RefCell<Option<Diagnostic>> = const { std::cell::RefCell::new(None) };
}

/// Take the directive error recorded while formatting embedded Markdown.
pub fn take_fragment_error() -> Option<Diagnostic> {
    FRAGMENT_ERROR.with(|e| e.borrow_mut().take())
}

/// Format a Markdown fragment (no final newline handling); returns lines.
/// Invalid directives are recorded with positions offset by `origin`
/// (0-based line, column).
pub fn format_fragment(text: &str, opts: &Options, notes: &mut Vec<Diagnostic>, origin: (usize, usize)) -> Vec<String> {
    format::with_keep_trailing(true, || format_fragment_at(text, opts, notes, None, Some(origin)))
}

/// Format a fragment whose first line is absolute line `line_base` (for notes).
pub fn format_fragment_at(text: &str, opts: &Options, notes: &mut Vec<Diagnostic>, line_base: Option<usize>, origin: Option<(usize, usize)>) -> Vec<String> {
    let lines = split_lines(text);
    if let Some((l0, c0)) = origin {
        if let Err(mut d) = check_text_directives(&lines) {
            d.line += l0;
            d.col += c0;
            FRAGMENT_ERROR.with(|e| {
                e.borrow_mut().get_or_insert(d);
            });
        }
    }
    if has_skip_file(&lines) {
        return lines;
    }
    let mut opts = opts.clone();
    let mut out: Vec<String> = Vec::new();
    let mut body_start = 0;
    if let Some(end) = front_matter_end(&lines) {
        let yaml_src = if end > 1 { format!("{}\n", lines[1..end].join("\n")) } else { String::new() };
        if !yaml_src.is_empty() && crate::yaml::parser::Parser::new(&yaml_src).parse_stream().is_err() {
            return lines;
        }
        if !opts.ignore_document_options {
            apply_front_matter_options(&yaml_src, &mut opts);
        }
        let formatted = crate::yaml::format_yaml(&yaml_src, &opts).unwrap_or(yaml_src.clone());
        out.push(lines[0].trim_end().to_string());
        for l in formatted.strip_suffix('\n').unwrap_or(&formatted).split('\n') {
            if end > 1 {
                out.push(l.to_string());
            }
        }
        out.push(lines[end].trim_end().to_string());
        body_start = end + 1;
    }
    // File-scope option directives apply to the whole document.
    let blocks = parse_with_directives(&lines[body_start..], line_base.map(|b| b + body_start));
    let mut found = Vec::new();
    directive_lines(&blocks, 0, &mut found);
    for (_, l) in found {
        if let Some((words, "file")) = option_directive(&l) {
            crate::yaml::emit::apply_md_words(&mut opts, &words);
        }
    }
    let total = wrap_total(opts.wrap);
    let mut f = format::Fmt::new(opts, notes);
    f.emit_notes = line_base.is_some() && !f.opts.skip_embedded;
    out.extend(f.format_blocks(&blocks, 0, 0, total));
    out
}

pub fn format_markdown_file(text: &str, opts: &Options, notes: &mut Vec<Diagnostic>) -> Result<String, Diagnostic> {
    if text.is_empty() {
        return Ok(String::new());
    }
    check_text_directives(&split_lines(text))?;
    let lines = format::with_keep_trailing(false, || format_fragment_at(text, opts, notes, Some(0), None));
    let mut out = lines.join("\n");
    out.push('\n');
    Ok(out)
}
