// Python and R source files: hashpipe YAML and marked Markdown targets.

use crate::format_cmd::Diagnostic;
use crate::options::{Options, Wrap};

#[derive(Debug, Clone)]
struct StrLit {
    /// Byte offset of the first char of the literal (prefix included).
    start: usize,
    /// Byte offset of the opening quote.
    quote_start: usize,
    /// Byte range of the content.
    content_start: usize,
    content_end: usize,
    /// Byte offset just after the closing delimiter.
    end: usize,
    triple: bool,
    raw: bool,
    bytes: bool,
    fstring: bool,
    /// Content begins with a line break.
    starts_nl: bool,
    /// Multi-line literal whose closing delimiter starts a line.
    ml: bool,
}

#[derive(Debug, Clone)]
struct Tokens {
    strings: Vec<StrLit>,
    /// Byte offsets of '#' that start comments.
    comments: Vec<usize>,
}

fn scan_python(src: &str) -> Tokens {
    let b = src.as_bytes();
    let mut i = 0;
    let mut strings = Vec::new();
    let mut comments = Vec::new();
    while i < b.len() {
        let c = b[i];
        if c == b'#' {
            comments.push(i);
            while i < b.len() && b[i] != b'\n' {
                i += 1;
            }
            continue;
        }
        if c == b'"' || c == b'\'' {
            // Prefix letters before the quote.
            let mut ps = i;
            while ps > 0 && (b[ps - 1] as char).is_ascii_alphabetic() {
                ps -= 1;
            }
            let prefix = src[ps..i].to_ascii_lowercase();
            let valid_prefix = matches!(prefix.as_str(), "" | "r" | "u" | "b" | "f" | "br" | "rb" | "fr" | "rf" | "t" | "tr" | "rt");
            // A prefix must not be part of a longer identifier.
            let ps_ok = ps == 0 || !((b[ps - 1] as char).is_ascii_alphanumeric() || b[ps - 1] == b'_');
            let (start, prefix) = if valid_prefix && ps_ok { (ps, prefix) } else { (i, String::new()) };
            let raw = prefix.contains('r');
            let triple = i + 2 < b.len() && b[i + 1] == c && b[i + 2] == c;
            let q = c;
            let content_start = if triple { i + 3 } else { i + 1 };
            let is_close = |j: usize| b[j] == q && (!triple || (j + 2 < b.len() && b[j + 1] == q && b[j + 2] == q));
            // A delimiter on the opening line closes the string; otherwise a triple-quoted
            // string runs to the first closing delimiter that starts a line.
            let mut found = None;
            let mut j = content_start;
            while j < b.len() && b[j] != b'\n' {
                if b[j] == b'\\' && b.get(j + 1) != Some(&b'\n') {
                    j += 2;
                    continue;
                }
                if is_close(j) {
                    found = Some(j);
                    break;
                }
                j += 1;
            }
            if found.is_none() && triple {
                let mut j = content_start;
                while j < b.len() {
                    if is_close(j) && closes_line_start(b, j) {
                        found = Some(j);
                        break;
                    }
                    j += 1;
                }
            }
            let ml = triple && found.map(|e| src[content_start..e].contains('\n')).unwrap_or(false);
            match found {
                Some(e) => {
                    let end = if triple { e + 3 } else { e + 1 };
                    strings.push(StrLit {
                        start,
                        quote_start: i,
                        content_start,
                        content_end: e,
                        end,
                        triple,
                        raw,
                        bytes: prefix.contains('b'),
                        fstring: prefix.contains('f') || prefix.contains('t'),
                        starts_nl: b.get(content_start) == Some(&b'\n'),
                        ml,
                    });
                    i = end;
                }
                None => {
                    // An unterminated opening delimiter is skipped.
                    i = content_start;
                }
            }
            continue;
        }
        i += 1;
    }
    Tokens { strings, comments }
}

/// Whether only spaces or tabs precede position `p` on its line.
fn closes_line_start(b: &[u8], p: usize) -> bool {
    let mut k = p;
    while k > 0 && matches!(b[k - 1], b' ' | b'\t') {
        k -= 1;
    }
    k > 0 && b[k - 1] == b'\n'
}

fn scan_r(src: &str) -> Tokens {
    let b = src.as_bytes();
    let mut i = 0;
    let mut strings = Vec::new();
    let mut comments = Vec::new();
    while i < b.len() {
        let c = b[i];
        if c == b'#' {
            comments.push(i);
            while i < b.len() && b[i] != b'\n' {
                i += 1;
            }
            continue;
        }
        if (c == b'r' || c == b'R') && i + 1 < b.len() && (b[i + 1] == b'"' || b[i + 1] == b'\'') && (i == 0 || !((b[i - 1] as char).is_ascii_alphanumeric() || b[i - 1] == b'.' || b[i - 1] == b'_')) {
            // Raw string r"---( ... )---"
            let q = b[i + 1];
            let mut j = i + 2;
            let ds = j;
            while j < b.len() && b[j] == b'-' {
                j += 1;
            }
            let dashes = j - ds;
            if j < b.len() && matches!(b[j], b'(' | b'[' | b'{') {
                let open = b[j];
                let close = match open {
                    b'(' => b')',
                    b'[' => b']',
                    _ => b'}',
                };
                let content_start = j + 1;
                let mut k = content_start;
                let mut found = None;
                while k < b.len() {
                    if b[k] == close {
                        let mut m = k + 1;
                        let mut d = 0;
                        while m < b.len() && b[m] == b'-' && d < dashes {
                            m += 1;
                            d += 1;
                        }
                        if d == dashes && m < b.len() && b[m] == q {
                            found = Some((k, m + 1));
                            break;
                        }
                    }
                    k += 1;
                }
                if let Some((ce, end)) = found {
                    strings.push(StrLit {
                        start: i,
                        quote_start: i + 1,
                        content_start,
                        content_end: ce,
                        end,
                        triple: false,
                        raw: true,
                        bytes: false,
                        fstring: false,
                        starts_nl: b.get(content_start) == Some(&b'\n'),
                        ml: src[content_start..ce].contains('\n'),
                    });
                    i = end;
                    continue;
                }
            }
        }
        if c == b'"' || c == b'\'' {
            // A quote opens a string running to the first later line that starts
            // with the same quote; scanning resumes on the line after it. Without
            // such a line the string must close on its own line.
            let q = c;
            let content_start = i + 1;
            let le = b[i..].iter().position(|&x| x == b'\n').map(|p| i + p).unwrap_or(b.len());
            let mut ml_end = None;
            let mut j = le;
            while j < b.len() {
                if b[j] == q && closes_line_start(b, j) {
                    ml_end = Some(j);
                    break;
                }
                j += 1;
            }
            if let Some(e) = ml_end {
                strings.push(StrLit {
                    start: i,
                    quote_start: i,
                    content_start,
                    content_end: e,
                    end: e + 1,
                    triple: false,
                    raw: false,
                    bytes: false,
                    fstring: false,
                    starts_nl: b.get(content_start) == Some(&b'\n'),
                    ml: true,
                });
                i = b[e..].iter().position(|&x| x == b'\n').map(|p| e + p).unwrap_or(b.len());
                continue;
            }
            let mut j = content_start;
            let mut close = None;
            while j < le {
                if b[j] == b'\\' {
                    j += 2;
                    continue;
                }
                if b[j] == q {
                    close = Some(j);
                    break;
                }
                j += 1;
            }
            match close {
                Some(e) => {
                    strings.push(StrLit {
                        start: i,
                        quote_start: i,
                        content_start,
                        content_end: e,
                        end: e + 1,
                        triple: false,
                        raw: false,
                        bytes: false,
                        fstring: false,
                        starts_nl: false,
                        ml: false,
                    });
                    i = e + 1;
                }
                None => i += 1,
            }
            continue;
        }
        i += 1;
    }
    Tokens { strings, comments }
}

struct Lines {
    starts: Vec<usize>,
}

impl Lines {
    fn new(src: &str) -> Self {
        let mut starts = vec![0];
        for (i, c) in src.bytes().enumerate() {
            if c == b'\n' {
                starts.push(i + 1);
            }
        }
        Lines { starts }
    }
    fn line_of(&self, pos: usize) -> usize {
        match self.starts.binary_search(&pos) {
            Ok(i) => i,
            Err(i) => i - 1,
        }
    }
}

fn line_end(src: &str, pos: usize) -> usize {
    match src[pos..].find('\n') {
        Some(p) => pos + p,
        None => src.len(),
    }
}

/// Own-line comment info: (line index, indent bytes, comment text from '#').
#[derive(Debug, Clone)]
struct OwnComment {
    line: usize,
    indent: String,
    text: String,
}

enum Directive {
    Markdown(Options),
    Embedded(String),
    Skip,
    SkipFile,
    Off,
    On,
    Other,
}

fn parse_directive(text: &str, base: &Options) -> Option<Result<Directive, String>> {
    let t = text.trim_start_matches('#').trim();
    let d = t.strip_prefix("fmt:")?.trim();
    let words: Vec<&str> = d.split_whitespace().collect();
    if words.is_empty() {
        return Some(Err("empty fmt directive".into()));
    }
    match words[0] {
        "skip" => {
            if words.len() > 1 && (words[1] == "file" || words[1] == "scope=file") {
                return Some(Ok(Directive::SkipFile));
            }
            return Some(Ok(Directive::Skip));
        }
        "off" => return Some(Ok(Directive::Off)),
        "on" => return Some(Ok(Directive::On)),
        "markdown" | "md" => {
            let mut o = base.clone();
            for w in &words[1..] {
                if let Some(v) = w.strip_prefix("wrap=") {
                    if let Some(wr) = crate::options::parse_wrap(v) {
                        o.wrap = wr;
                    }
                } else if *w == "canonical" || *w == "canonical=true" {
                    o.canonical = true;
                } else if let Some(v) = w.strip_prefix("footnotes=") {
                    o.preserve_footnotes = matches!(v, "preserve" | "none" | "false" | "no" | "0");
                } else if let Some(v) = w.strip_prefix("table-widths=") {
                    o.table_widths = if v == "preserve" { crate::options::TableWidths::Preserve } else { crate::options::TableWidths::Fit };
                }
            }
            return Some(Ok(Directive::Markdown(o)));
        }
        "embedded" => {
            if words.len() > 1 {
                return Some(Ok(Directive::Embedded(words[1].to_string())));
            }
            return Some(Err("embedded directive needs a name".into()));
        }
        _ => {}
    }
    let w0 = words[0];
    if w0.contains('=') || w0 == "canonical" || w0 == "compact" || w0 == "table" || w0.starts_with("template") {
        return Some(Ok(Directive::Other));
    }
    Some(Ok(Directive::Embedded(w0.to_string())))
}

const KNOWN_FORMATTERS: &[(&str, &str)] = &[
    ("python", "ruff"),
    ("ruff", "ruff"),
    ("r", "air"),
    ("air", "air"),
    ("mdformat", "mdformat"),
    ("json", "prettier"),
    ("prettier-json", "prettier"),
    ("jsonc", "prettier"),
    ("prettier-jsonc", "prettier"),
    ("json5", "prettier"),
    ("prettier-json5", "prettier"),
    ("graphql", "prettier"),
    ("gql", "prettier"),
    ("graphqls", "prettier"),
    ("prettier-graphql", "prettier"),
    ("css", "prettier"),
    ("prettier-css", "prettier"),
    ("scss", "prettier"),
    ("prettier-scss", "prettier"),
    ("less", "prettier"),
    ("prettier-less", "prettier"),
    ("postcss", "prettier"),
    ("pcss", "prettier"),
    ("prettier-postcss", "prettier"),
    ("html", "prettier"),
    ("prettier-html", "prettier"),
    ("js", "prettier"),
    ("javascript", "prettier"),
    ("prettier-js", "prettier"),
    ("jsx", "prettier"),
    ("prettier-jsx", "prettier"),
    ("ts", "prettier"),
    ("typescript", "prettier"),
    ("prettier-ts", "prettier"),
    ("tsx", "prettier"),
    ("prettier-tsx", "prettier"),
];

pub fn formatter_program(name: &str) -> Option<&'static str> {
    KNOWN_FORMATTERS.iter().find(|(n, _)| *n == name).map(|(_, p)| *p)
}

fn shrink_wrap(o: &Options, indent: usize) -> Options {
    let mut o = o.clone();
    o.wrap = match o.wrap {
        Wrap::Column(n) => Wrap::Column(n.saturating_sub(indent).max(1)),
        Wrap::Sentence(Some(n)) => Wrap::Sentence(Some(n.saturating_sub(indent).max(1))),
        w => w,
    };
    o
}

enum Job {
    Comment(Vec<OwnComment>, Options),
    Str(StrLit, Options),
    Hashpipe(Vec<OwnComment>),
}

struct Edit {
    start: usize,
    end: usize,
    text: String,
}

pub fn format_source_file(src: &str, opts: &Options, is_r: bool, notes: &mut Vec<Diagnostic>) -> Result<String, Diagnostic> {
    let toks = if is_r { scan_r(src) } else { scan_python(src) };
    let lines = Lines::new(src);
    let line_texts: Vec<&str> = {
        let mut v: Vec<&str> = src.split('\n').collect();
        if src.ends_with('\n') {
            v.pop();
        }
        v
    };
    let nlines = line_texts.len();
    // Own-line comments.
    let mut own: Vec<OwnComment> = Vec::new();
    for &c in &toks.comments {
        let l = lines.line_of(c);
        let ls = lines.starts[l];
        if src[ls..c].trim().is_empty() {
            own.push(OwnComment { line: l, indent: src[ls..c].to_string(), text: src[c..line_end(src, c)].to_string() });
        }
    }
    let own_at = |line: usize| -> Option<&OwnComment> { own.iter().find(|o| o.line == line) };
    // Skip file.
    for o in &own {
        if let Some(Ok(Directive::SkipFile)) = parse_directive(&o.text, opts) {
            return Ok(src.to_string());
        }
    }
    let eof_pos = || crate::yaml::directive::eof_pos(src);
    let mut edits: Vec<Edit> = Vec::new();
    let mut jobs: Vec<Job> = Vec::new();
    let mut consumed_lines: Vec<bool> = vec![false; nlines + 1];
    let mut off = false;
    let mut skip_next = false;
    let mut skip_pos = 0usize;
    // A multi-line string literal after a `skip` directive takes the skip.
    let skip_taken = |from: usize, to: usize| toks.strings.iter().any(|s| s.ml && s.start > from && s.start < to);
    let mut i = 0;
    while i < own.len() {
        let o = own[i].clone();
        if skip_next && skip_taken(skip_pos, lines.starts[o.line]) {
            skip_next = false;
        }
        if consumed_lines[o.line] {
            i += 1;
            continue;
        }
        // A directive inside a larger comment block is ordinary comment text.
        let prev_is_comment = o.line > 0 && own_at(o.line - 1).map(|p| !p.text.starts_with("#|")).unwrap_or(false);
        if let Some(d) = if prev_is_comment { None } else { parse_directive(&o.text, opts) } {
            let d = match d {
                Ok(d) => d,
                Err(m) => return Err(Diagnostic { line: o.line + 1, col: 1, msg: m }),
            };
            match d {
                Directive::Off => {
                    off = true;
                    i += 1;
                    continue;
                }
                Directive::On => {
                    off = false;
                    i += 1;
                    continue;
                }
                Directive::Skip => {
                    skip_next = true;
                    skip_pos = lines.starts[o.line];
                    i += 1;
                    continue;
                }
                Directive::SkipFile | Directive::Other => {
                    i += 1;
                    continue;
                }
                Directive::Markdown(_) if off => {
                    i += 1;
                    continue;
                }
                Directive::Markdown(mo) => {
                    let next_line = o.line + 1;
                    // Comment block target directly below.
                    if let Some(nc) = own_at(next_line).cloned() {
                        if parse_directive(&nc.text, opts).is_none() && !nc.text.starts_with("#|") {
                            let mut block = vec![nc.clone()];
                            let mut l = next_line + 1;
                            while let Some(c) = own_at(l) {
                                if c.text.starts_with("#|") || parse_directive(&c.text, opts).is_some() {
                                    break;
                                }
                                block.push(c.clone());
                                l += 1;
                            }
                            // The block's lines must share one indentation.
                            if block.iter().any(|c| c.indent != nc.indent) {
                                return Err(Diagnostic { line: nc.line + 1, col: 1, msg: "fmt: markdown has no target".into() });
                            }
                            for b in &block {
                                consumed_lines[b.line] = true;
                            }
                            if !skip_next {
                                jobs.push(Job::Comment(block.clone(), mo.clone()));
                            }
                            skip_next = false;
                            i += 1;
                            continue;
                        }
                    }
                    // String target.
                    let after = lines.starts[o.line] + o.indent.len() + o.text.len();
                    let target = find_string_target(&toks, after, is_r);

                    if let Some(Ok(t)) = &target {
                        if !src[t.content_start..t.content_end].contains('\n') {
                            let l = lines.line_of(t.quote_start);
                            let col = src[lines.starts[l]..t.quote_start].chars().count() + 1;
                            return Err(Diagnostic { line: l + 1, col, msg: "fmt: markdown has no target".into() });
                        }
                    }
                    match target {
                        Some(Ok(s)) => {
                            let fl = lines.line_of(s.content_start);
                            for l in lines.line_of(s.start)..=lines.line_of(s.end.saturating_sub(1)) {
                                consumed_lines[l] = true;
                            }
                            let _ = fl;
                            if !skip_next {
                                jobs.push(Job::Str(s.clone(), mo.clone()));
                            }
                            skip_next = false;
                        }
                        Some(Err(pos)) => {
                            let l = lines.line_of(pos);
                            let col = src[lines.starts[l]..pos].chars().count() + 1;
                            return Err(Diagnostic { line: l + 1, col, msg: "fmt: markdown has no target".into() });
                        }
                        None => {
                            let (l, c) = eof_pos();
                            return Err(Diagnostic { line: l, col: c, msg: "fmt: markdown has no target".into() });
                        }
                    }
                    i += 1;
                    continue;
                }
                Directive::Embedded(name) => {
                    let after = lines.starts[o.line] + o.indent.len() + o.text.len();
                    let target = find_string_target(&toks, after, is_r);
                    match target {
                        Some(Ok(s)) => {
                            let cl = content_first_line(src, &lines, &s);
                            let prog = formatter_program(&name);
                            match prog {
                                None => {
                                    return Err(Diagnostic { line: cl + 1, col: 1, msg: format!("unknown embedded formatter: {}", name) });
                                }
                                Some(p) => {
                                    if !opts.skip_embedded {
                                        notes.push(Diagnostic { line: cl + 1, col: 1, msg: format!("missing optional embedded formatter `{}`; preserved source", p) });
                                    }
                                }
                            }
                            for l in lines.line_of(s.start)..=lines.line_of(s.end.saturating_sub(1)) {
                                consumed_lines[l] = true;
                            }
                        }
                        Some(Err(pos)) => {
                            let l = lines.line_of(pos);
                            let col = src[lines.starts[l]..pos].chars().count() + 1;
                            return Err(Diagnostic { line: l + 1, col, msg: format!("fmt: {} has no target", name) });
                        }
                        None => {
                            let (l, c) = eof_pos();
                            return Err(Diagnostic { line: l, col: c, msg: format!("fmt: {} has no target", name) });
                        }
                    }
                    i += 1;
                    continue;
                }
            }
        }
        // Hashpipe block, opened by `#| ` or a bare `#|`.
        if o.text.starts_with("#| ") || o.text.trim_end() == "#|" {
            let mut block = vec![o.clone()];
            let mut l = o.line + 1;
            while let Some(c) = own_at(l) {
                if !c.text.starts_with("#|") {
                    break;
                }
                block.push(c.clone());
                l += 1;
            }
            let n = block.len();
            if !off && !skip_next && block.iter().any(|c| c.indent != o.indent) {
                return Err(Diagnostic { line: o.line + 1, col: 1, msg: "hashpipe YAML has no target".into() });
            }
            if !off && !skip_next {
                jobs.push(Job::Hashpipe(block.clone()));
            }
            skip_next = false;
            i += n;
            continue;
        }
        i += 1;
    }
    // Targets are resolved first; formatting errors surface afterwards.
    for job in jobs {
        let e = match job {
            Job::Comment(block, mo) => self_format_comment_block(src, &lines, &block, &mo, notes)?,
            Job::Str(s, mo) => format_string_target(src, &lines, &s, &mo, is_r, notes)?,
            Job::Hashpipe(block) => format_hashpipe(src, &lines, &block, opts)?,
        };
        if let Some(e) = e {
            edits.push(e);
        }
    }
    // Apply edits.
    edits.sort_by_key(|e| e.start);
    let mut out = String::new();
    let mut pos = 0;
    for e in edits {
        if e.start < pos {
            continue;
        }
        out.push_str(&src[pos..e.start]);
        out.push_str(&e.text);
        pos = e.end;
    }
    out.push_str(&src[pos..]);
    Ok(out)
}

fn content_first_line(src: &str, lines: &Lines, s: &StrLit) -> usize {
    let l = lines.line_of(s.content_start);
    if src[s.content_start..].starts_with('\n') {
        l + 1
    } else {
        l
    }
}

/// Find the next string target after `pos`. Some(Err(pos)) reports an invalid candidate.
fn find_string_target(toks: &Tokens, pos: usize, is_r: bool) -> Option<Result<StrLit, usize>> {
    for s in &toks.strings {
        if s.start < pos {
            continue;
        }
        if is_r {
            if !s.ml {
                continue;
            }
            return Some(Ok(s.clone()));
        }
        if !s.triple {
            continue;
        }
        if s.bytes {
            return Some(Err(s.quote_start));
        }
        return Some(Ok(s.clone()));
    }
    None
}

fn self_format_comment_block(src: &str, lines: &Lines, block: &[OwnComment], mo: &Options, notes: &mut Vec<Diagnostic>) -> Result<Option<Edit>, Diagnostic> {
    // All lines use "# " or all use "#" directly followed by text; a bare "#" is blank.
    let first = &block[0];
    let mut spaced: Option<bool> = None;
    for c in block {
        if c.text.trim_end() == "#" {
            continue;
        }
        let sp = c.text[1..].starts_with(' ');
        match spaced {
            Some(s) if s != sp => {
                return Err(Diagnostic { line: first.line + 1, col: 1, msg: "fmt: markdown has no target".into() });
            }
            _ => spaced = Some(sp),
        }
    }
    let prefix = if spaced == Some(false) { "#" } else { "# " };
    let mut content = Vec::new();
    for c in block {
        let t = &c.text;
        if t.trim_end() == "#" {
            content.push(String::new());
        } else {
            content.push(t[prefix.len()..].to_string());
        }
    }
    let indent = first.indent.clone();
    let width_used = indent.chars().count() + prefix.len();
    let o = shrink_wrap(mo, width_used);
    let text = content.join("\n");
    // Markdown holding template expressions is left as written.
    if crate::template::contains_template(&text, &o.templates) {
        return Ok(None);
    }
    let formatted = crate::markdown::format_fragment(&text, &o, notes, (0, 0));
    let mut out = String::new();
    for (k, l) in formatted.iter().enumerate() {
        if k > 0 {
            out.push('\n');
        }
        if l.is_empty() {
            out.push_str(&format!("{}#", indent));
        } else {
            out.push_str(&format!("{}{}{}", indent, prefix, l));
        }
    }
    let start = lines.starts[block[0].line];
    let last = block.last().unwrap();
    let end = line_end(src, lines.starts[last.line]);
    Ok(Some(Edit { start, end, text: out }))
}

fn format_string_target(src: &str, lines: &Lines, s: &StrLit, mo: &Options, is_r: bool, notes: &mut Vec<Diagnostic>) -> Result<Option<Edit>, Diagnostic> {
    let mut content_start = s.content_start;
    if !s.raw && !is_r && src[content_start..s.content_end].starts_with("\\\n") {
        // Escaped line break directly after the opening delimiter.
        content_start += 1;
    }
    let content = &src[content_start..s.content_end];
    if !content.contains('\n') {
        let l = lines.line_of(s.quote_start);
        let col = src[lines.starts[l]..s.quote_start].chars().count() + 1;
        return Err(Diagnostic { line: l + 1, col, msg: "fmt: markdown has no target".into() });
    }
    // Errors point at the first content character.
    let content_pos = || -> (usize, usize) {
        let fl = lines.line_of(content_start);
        if content.starts_with('\n') {
            (fl + 2, 1)
        } else {
            (fl + 1, src[lines.starts[fl]..content_start].chars().count() + 1)
        }
    };
    if !s.raw && content.contains('\\') {
        let (line, col) = content_pos();
        let what = if is_r { "R" } else { "Python" };
        return Err(Diagnostic { line, col, msg: format!("non-raw {} Markdown strings must not contain backslashes", what) });
    }
    let _ = s.fstring;
    // Split: first line (after opening delimiter), middle lines, closing line prefix.
    let parts: Vec<&str> = content.split('\n').collect();
    let first = parts[0];
    let last = parts[parts.len() - 1];
    let closing_ws = last.trim().is_empty();
    let mut body: Vec<String> = Vec::new();
    if !first.trim().is_empty() {
        body.push(first.to_string());
    }
    let mid_end = if closing_ws { parts.len() - 1 } else { parts.len() };
    for p in &parts[1..mid_end] {
        body.push(p.to_string());
    }
    // Drop trailing blank lines.
    while body.last().map(|l| l.trim().is_empty()).unwrap_or(false) {
        body.pop();
    }
    let indent = body
        .iter()
        .skip(if first.trim().is_empty() { 0 } else { 1 })
        .filter(|l| !l.trim().is_empty())
        .map(|l| l.len() - l.trim_start_matches(' ').len())
        .min()
        .unwrap_or(0);
    let mut dedented: Vec<String> = Vec::new();
    let mut leading_blank = 0;
    let mut started = false;
    for (k, l) in body.iter().enumerate() {
        if k == 0 && !first.trim().is_empty() {
            dedented.push(l.trim_start().to_string());
            started = true;
            continue;
        }
        if l.trim().is_empty() {
            if !started {
                leading_blank += 1;
                continue;
            }
            // Spaces on a blank line past the common indentation are kept.
            dedented.push(l.get(indent..).unwrap_or("").to_string());
        } else {
            started = true;
            dedented.push(l[indent.min(l.len())..].to_string());
        }
    }
    let o = shrink_wrap(mo, indent);
    let text = dedented.join("\n");
    // Markdown holding template expressions is left as written.
    if crate::template::contains_template(&text, &o.templates) {
        return Ok(None);
    }
    let formatted = if text.trim().is_empty() { Vec::new() } else { crate::markdown::format_fragment(&text, &o, notes, (0, 0)) };
    if !s.raw && formatted.iter().any(|l| l.contains('\\')) {
        let (line, col) = content_pos();
        let what = if is_r { "R" } else { "Python" };
        return Err(Diagnostic { line, col, msg: format!("non-raw {} Markdown strings must not contain backslashes", what) });
    }
    let q = src.as_bytes()[s.quote_start] as char;
    if is_r && !s.raw && formatted.iter().any(|l| l.contains(q)) {
        let (line, col) = content_pos();
        return Err(Diagnostic { line, col, msg: "formatted Markdown conflicts with string delimiter".into() });
    }
    let pad = " ".repeat(indent);
    let mut out = String::new();
    if !first.trim().is_empty() {
        // Content starts on the opening line.
        for (k, l) in formatted.iter().enumerate() {
            if k == 0 {
                out.push_str(l);
            } else {
                out.push('\n');
                if !l.is_empty() {
                    out.push_str(&pad);
                    out.push_str(l);
                }
            }
        }
    } else {
        for _ in 0..leading_blank {
            out.push('\n');
        }
        for l in formatted.iter() {
            out.push('\n');
            if !l.is_empty() {
                out.push_str(&pad);
                out.push_str(l);
            }
        }
    }
    out.push('\n');
    if closing_ws {
        out.push_str(last);
    } else {
        // Closing delimiter followed content on the same line.
        return Ok(None);
    }
    Ok(Some(Edit { start: content_start, end: s.content_end, text: out }))
}

fn format_hashpipe(src: &str, lines: &Lines, block: &[OwnComment], opts: &Options) -> Result<Option<Edit>, Diagnostic> {
    let mut yaml = String::new();
    for c in block {
        let t = &c.text;
        if t == "#|" || t.trim_end() == "#|" {
            yaml.push('\n');
        } else if let Some(r) = t.strip_prefix("#| ") {
            yaml.push_str(r);
            yaml.push('\n');
        } else {
            return Err(Diagnostic { line: block[0].line + 1, col: 1, msg: "hashpipe YAML has no target".into() });
        }
    }
    if crate::template::contains_template(&yaml, &opts.templates) {
        return Ok(None);
    }
    let formatted = crate::yaml::format_yaml(&yaml, opts)?;
    let indent = &block[0].indent;
    let mut out = String::new();
    let fl: Vec<&str> = formatted.strip_suffix('\n').unwrap_or(&formatted).split('\n').collect();
    for (k, l) in fl.iter().enumerate() {
        if k > 0 {
            out.push('\n');
        }
        if l.is_empty() {
            out.push_str(&format!("{}#|", indent));
        } else {
            out.push_str(&format!("{}#| {}", indent, l));
        }
    }
    let start = lines.starts[block[0].line];
    let last = block.last().unwrap();
    let end = line_end(src, lines.starts[last.line]);
    Ok(Some(Edit { start, end, text: out }))
}
