// `# fmt:` directives inside YAML documents.

use super::parser::*;
use crate::format_cmd::Diagnostic;

#[derive(Debug, Clone, PartialEq)]
pub enum DirKind {
    Skip,
    SkipFile,
    Off,
    On,
    Markdown(Vec<String>),
    Embedded(String),
    /// Option-only directive such as `canonical=true`.
    Options(Vec<String>),
    /// Align the next sequence of flow mappings (`true`: collapse block rows first).
    Table(bool),
    /// Enable or disable compaction with a scope.
    Compact(bool, Scope),
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Scope {
    Next,
    FromHere,
    File,
}

#[derive(Debug, Clone)]
pub struct Directive {
    pub line: usize,
    pub col: usize,
    pub kind: DirKind,
}

#[derive(Debug, Default)]
pub struct Directives {
    pub skip_file: bool,
    /// Inclusive line ranges kept verbatim (from `off` to `on`).
    pub off_regions: Vec<(usize, usize)>,
    /// Lines holding `skip` directives.
    pub skip_lines: Vec<usize>,
    pub markdown: Vec<(usize, Vec<String>)>,
    pub options: Vec<(usize, Vec<String>)>,
    pub embedded: Vec<(usize, String)>,
    /// Table directives (line, collapse block rows).
    pub tables: Vec<(usize, bool)>,
    /// Compaction directives (line, enabled, scope).
    pub compacts: Vec<(usize, bool, Scope)>,
}

fn err(line: usize, col: usize, msg: impl Into<String>) -> Diagnostic {
    Diagnostic { line: line + 1, col: col + 1, msg: msg.into() }
}

/// Parse the text of a comment (starting at '#'). Returns None if not a directive.
pub fn parse_comment(text: &str, line: usize, col: usize) -> Option<Result<Directive, Diagnostic>> {
    let body = text.strip_prefix('#')?.trim();
    let rest = body.strip_prefix("fmt:")?.trim();
    let words: Vec<&str> = rest.split_whitespace().collect();
    let fail = |m: String| Some(Err(err(line, col, m)));
    if words.is_empty() {
        return fail("invalid fmt directive: empty".into());
    }
    let kind = match words[0] {
        "skip" | "off" | "on" => match check_toggle(&words) {
            Ok(k) => k,
            Err(m) => return fail(m),
        },
        "markdown" => match check_markdown(&words[1..]) {
            Ok(()) => DirKind::Markdown(words[1..].iter().map(|s| s.to_string()).collect()),
            Err(m) => return fail(m),
        },
        "embedded" => match &words[1..] {
            [] => return fail("unknown embedded formatter: default".into()),
            [name] if crate::source::formatter_program(name).is_none() => return fail(format!("unknown embedded formatter: {}", name)),
            [name] => DirKind::Embedded(name.to_string()),
            _ => return fail(format!("invalid fmt directive: {}", rest)),
        },
        w if w == "table" || w == "compact" || w.starts_with("compact=") => match table_or_compact(&words) {
            Ok(k) => k,
            Err(m) => return fail(m),
        },
        w if w.contains('=') || w == "canonical" => match words.iter().try_for_each(|w| check_option_word(w)) {
            Ok(()) => DirKind::Options(words.iter().map(|s| s.to_string()).collect()),
            Err(m) => return fail(m),
        },
        _ if words.len() > 1 => return fail(format!("invalid fmt directive: {}", rest)),
        name => {
            if crate::source::formatter_program(name).is_none() {
                return fail(format!("unknown embedded formatter: {}", name));
            }
            DirKind::Embedded(name.to_string())
        }
    };
    Some(Ok(Directive { line, col, kind }))
}

/// Check a `skip`, `off` or `on` directive.
pub fn check_toggle(words: &[&str]) -> Result<DirKind, String> {
    match (words[0], &words[1..]) {
        ("skip", [] | ["scope=next"]) => Ok(DirKind::Skip),
        ("skip", ["file"] | ["scope=file"]) => Ok(DirKind::SkipFile),
        ("off", [] | ["scope=from-here"]) => Ok(DirKind::Off),
        ("on", []) => Ok(DirKind::On),
        ("on", _) => Err("fmt: on does not support explicit scope".into()),
        (k, [sc]) if sc.starts_with("scope=") => Err(format!("fmt: {} does not support {}", k, sc)),
        (k, _) => Err(format!("invalid fmt: {} directive", k)),
    }
}

/// Check the option words after `markdown`.
pub fn check_markdown(words: &[&str]) -> Result<(), String> {
    words.iter().try_for_each(|w| check_option_word(w))?;
    if let [sc] = words {
        if let Some(s) = sc.strip_prefix("scope=").filter(|s| *s != "next") {
            return Err(format!("fmt: markdown with scope={} requires at least one option", s));
        }
    }
    Ok(())
}

/// Check one option word of a directive (`wrap=40`, `scope=next`, ...).
pub fn check_option_word(w: &str) -> Result<(), String> {
    let ok = |b: bool, m: &str| if b { Ok(()) } else { Err(m.to_string()) };
    if let Some(v) = w.strip_prefix("scope=") {
        return ok(matches!(v, "next" | "from-here" | "file"), &format!("invalid fmt directive scope: {}", v));
    }
    if w == "canonical" {
        return Ok(());
    }
    if let Some(v) = w.strip_prefix("wrap=") {
        return ok(crate::options::parse_wrap(v).is_some(), "fmt: wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>");
    }
    if let Some(v) = w.strip_prefix("canonical=") {
        return ok(matches!(v, "true" | "yes" | "1" | "false" | "no" | "0"), "invalid fmt: canonical option");
    }
    if let Some(v) = w.strip_prefix("footnotes=") {
        return ok(matches!(v, "preserve" | "none" | "false" | "no" | "0" | "wrap" | "format" | "true" | "yes" | "1"), "invalid fmt: footnotes option");
    }
    if let Some(v) = w.strip_prefix("table-widths=") {
        return ok(matches!(v, "fit" | "preserve"), "fmt: table-widths must be fit or preserve");
    }
    Err(format!("invalid fmt directive option: {}", w))
}

fn table_or_compact(words: &[&str]) -> Result<DirKind, String> {
    let mut scope = Scope::Next;
    let mut scope_word = None;
    let mut rest: Vec<&str> = Vec::new();
    for w in words {
        match w.strip_prefix("scope=") {
            Some(sc) => {
                scope_word = Some(sc);
                scope = match sc {
                    "from-here" => Scope::FromHere,
                    "file" => Scope::File,
                    _ => Scope::Next,
                };
            }
            None => rest.push(w),
        }
    }
    let table = |rest: &[&str]| -> Result<DirKind, String> {
        let compact = match rest {
            [] => false,
            ["compact"] | ["compact=true"] => true,
            _ => return Err("invalid fmt: table directive".into()),
        };
        if let Some(sc) = scope_word.filter(|sc| *sc != "next") {
            return Err(format!("fmt: table does not support scope={}", sc));
        }
        Ok(DirKind::Table(compact))
    };
    if rest[0] == "table" {
        return table(&rest[1..]);
    }
    if rest.get(1) == Some(&"table") && rest[0] == "compact" {
        return table(&rest[2..]).map(|_| DirKind::Table(true));
    }
    if let Some(sc) = scope_word.filter(|sc| !matches!(*sc, "next" | "from-here" | "file")) {
        return Err(format!("invalid fmt directive scope: {}", sc));
    }
    if let Some(v) = rest[0].strip_prefix("compact=") {
        let on = match v {
            "true" | "yes" | "1" => true,
            "false" | "no" | "0" => false,
            _ => return Err("invalid fmt: compact option".into()),
        };
        if rest.len() > 1 {
            return Err("invalid fmt: compact directive".into());
        }
        return Ok(DirKind::Compact(on, scope));
    }
    match &rest[1..] {
        [] | ["true"] => Ok(DirKind::Compact(true, scope)),
        ["false"] => Ok(DirKind::Compact(false, scope)),
        _ => Err("invalid fmt: compact directive".into()),
    }
}

/// Collect directives from own-line comments; trailing directives are errors.
pub fn collect(src: &str, stream: &Stream, line_starts: &[usize]) -> Result<Directives, Diagnostic> {
    let lines: Vec<&str> = {
        let mut v: Vec<&str> = src.split('\n').collect();
        if src.ends_with('\n') {
            v.pop();
        }
        v
    };
    let mut d = Directives::default();
    let mut off_start: Option<usize> = None;
    let mut dirs: Vec<Directive> = Vec::new();
    for (i, l) in lines.iter().enumerate() {
        if stream.line_kinds.get(i) != Some(&LineKind::Comment) {
            continue;
        }
        let col = l.len() - l.trim_start().len();
        if let Some(r) = parse_comment(l.trim(), i, col) {
            dirs.push(r?);
        }
    }
    // Trailing comment directives are not supported, except on a collection
    // parent whose value starts on a later line.
    check_trailing(src, stream, line_starts, &lines)?;
    for (line, c) in parent_comments(stream) {
        if let Some(Ok(dir)) = parse_comment(c.trim(), line, 0) {
            if let DirKind::Table(compact) = dir.kind {
                dirs.push(Directive { line, col: 0, kind: DirKind::Table(compact) });
            }
        }
    }
    for dir in dirs {
        match dir.kind {
            DirKind::SkipFile => d.skip_file = true,
            DirKind::Skip => d.skip_lines.push(dir.line),
            DirKind::Off => {
                if off_start.is_some() {
                    return Err(err(dir.line, 0, "nested fmt: off"));
                }
                off_start = Some(dir.line);
            }
            DirKind::On => match off_start.take() {
                Some(s) => d.off_regions.push((s, dir.line)),
                None => return Err(err(dir.line, 0, "fmt: on without active fmt: off")),
            },
            DirKind::Markdown(opts) => d.markdown.push((dir.line, opts)),
            DirKind::Embedded(name) => d.embedded.push((dir.line, name)),
            DirKind::Options(w) => d.options.push((dir.line, w)),
            DirKind::Table(c) => d.tables.push((dir.line, c)),
            DirKind::Compact(on, sc) => d.compacts.push((dir.line, on, sc)),
        }
    }
    if d.skip_file {
        return Ok(d);
    }
    if off_start.is_some() {
        let (l, c) = eof_pos(src);
        return Err(Diagnostic { line: l, col: c, msg: "unterminated fmt: off".into() });
    }
    Ok(d)
}

/// Position of the last character of `src` (a final newline counts as the column
/// after its line).
pub fn eof_pos(src: &str) -> (usize, usize) {
    let body = src.strip_suffix('\n');
    let lines: Vec<&str> = body.unwrap_or(src).split('\n').collect();
    if src.is_empty() {
        return (1, 1);
    }
    let len = lines[lines.len() - 1].chars().count();
    (lines.len(), if body.is_some() { len + 1 } else { len.max(1) })
}

/// Comments after a mapping colon or sequence dash whose value starts later.
fn parent_comments(stream: &Stream) -> Vec<(usize, String)> {
    fn walk(n: &Node, out: &mut Vec<(usize, String)>) {
        match &n.kind {
            Kind::Map(es) => {
                for e in es {
                    if let Some(c) = &e.colon_comment {
                        out.push((e.line, c.clone()));
                    }
                    walk(&e.value, out);
                }
            }
            Kind::Seq(items) => {
                for it in items {
                    walk(&it.value, out);
                }
            }
            _ => {}
        }
    }
    let mut out = Vec::new();
    for doc in &stream.docs {
        if let Some(r) = &doc.root {
            walk(r, &mut out);
        }
    }
    out
}

fn check_trailing(src: &str, stream: &Stream, line_starts: &[usize], lines: &[&str]) -> Result<(), Diagnostic> {
    let _ = (src, line_starts);
    let mut found: Option<(usize, usize)> = None;
    let mut visit_comment = |c: &Option<String>, line: usize, parent: bool| {
        if parent {
            // Directives on a parent line are accepted; table directives apply.
            return;
        }
        if found.is_some() {
            return;
        }
        if let Some(c) = c {
            if c.strip_prefix('#').map(|b| b.trim().starts_with("fmt:")).unwrap_or(false) {
                if let Some(l) = lines.get(line) {
                    if let Some(p) = l.rfind(c.as_str()) {
                        found = Some((line, l[..p].chars().count()));
                    }
                }
            }
        }
    };
    fn walk(n: &Node, f: &mut dyn FnMut(&Option<String>, usize, bool)) {
        f(&n.comment, n.end_line, false);
        match &n.kind {
            Kind::Map(es) => {
                for e in es {
                    f(&e.colon_comment, e.line, true);
                    walk(&e.value, f);
                }
            }
            Kind::Seq(items) => {
                for it in items {
                    f(&it.dash_comment, it.line, true);
                    walk(&it.value, f);
                }
            }
            _ => {}
        }
    }
    for doc in &stream.docs {
        if let Some(r) = &doc.root {
            walk(r, &mut visit_comment);
        }
    }
    if let Some((l, c)) = found {
        return Err(err(l, c, "fmt directive is not supported in this position"));
    }
    Ok(())
}
