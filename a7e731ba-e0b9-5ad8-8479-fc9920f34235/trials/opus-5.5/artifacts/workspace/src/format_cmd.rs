// The `format` command: path selection, per-file formatting, summaries and diffs.

use crate::cli::Matches;
use crate::config;
use crate::diff;
use crate::options::{Options, TableWidths};
use crate::walk::Walker;
use std::collections::HashSet;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FileKind {
    Yaml,
    Markdown,
    Python,
    R,
}

pub fn detect_kind(path: &str) -> Option<FileKind> {
    let name = Path::new(path).file_name()?.to_string_lossy().into_owned();
    let dot = name.rfind('.')?;
    if dot == 0 {
        return None;
    }
    let ext = name[dot + 1..].to_ascii_lowercase();
    match ext.as_str() {
        "yaml" | "yml" => Some(FileKind::Yaml),
        "md" | "qmd" | "rmd" => Some(FileKind::Markdown),
        "py" => Some(FileKind::Python),
        "r" => Some(FileKind::R),
        _ => None,
    }
}

#[derive(Debug, Clone)]
pub struct Diagnostic {
    pub line: usize,
    pub col: usize,
    pub msg: String,
}

impl Diagnostic {
    pub fn new(line: usize, col: usize, msg: impl Into<String>) -> Self {
        Diagnostic { line, col, msg: msg.into() }
    }
}

pub struct FormatOutcome {
    pub text: String,
    pub notes: Vec<Diagnostic>,
}

/// Format a whole file's text according to its kind.
pub fn format_text(kind: FileKind, text: &str, opts: &Options) -> Result<FormatOutcome, Diagnostic> {
    let mut notes = Vec::new();
    // A UTF-8 byte-order mark is set aside while formatting; it still counts as a
    // column of the first line. A BOM-prefixed YAML file is formatted only when it
    // opens with a fmt directive and is otherwise kept as written, which is an error
    // if it has directives elsewhere.
    if let Some(body) = text.strip_prefix('\u{feff}') {
        if kind == FileKind::Yaml {
            match bom_yaml_mode(body) {
                Some(true) => {}
                Some(false) => return Ok(FormatOutcome { text: text.to_string(), notes }),
                None => return Err(Diagnostic::new(1, 1, "formatting this BOM-prefixed YAML root is unsupported")),
            }
        }
        let shift = |mut d: Diagnostic| {
            if d.line == 1 {
                d.col += 1;
            }
            d
        };
        return match format_text(kind, body, opts) {
            Ok(mut o) => {
                o.text.insert(0, '\u{feff}');
                o.notes = o.notes.into_iter().map(shift).collect();
                Ok(o)
            }
            Err(d) => Err(shift(d)),
        };
    }
    let (normalized, eol) = normalize_eol(text);
    crate::markdown::take_fragment_error();
    let out = match kind {
        FileKind::Yaml => crate::yaml::format_yaml_file(&normalized, opts, &mut notes)?,
        FileKind::Markdown => crate::markdown::format_markdown_file(&normalized, opts, &mut notes)?,
        FileKind::Python => crate::source::format_source_file(&normalized, opts, false, &mut notes)?,
        FileKind::R => crate::source::format_source_file(&normalized, opts, true, &mut notes)?,
    };
    // An invalid directive in embedded Markdown fails the file.
    if let Some(d) = crate::markdown::take_fragment_error() {
        return Err(d);
    }
    let out = if text.contains("\r\n") && text.replace("\r\n", "").contains('\n') {
        restore_mixed_eol(text, &normalized, &out, kind == FileKind::Markdown, eol)
    } else {
        restore_eol(&out, eol)
    };
    Ok(FormatOutcome { text: out, notes })
}

/// Whether a BOM-prefixed YAML file is formatted (`Some(true)`: it opens with a fmt
/// directive), kept as written (`Some(false)`: it has no directives, or it would be
/// kept as written anyway) or rejected.
fn bom_yaml_mode(body: &str) -> Option<bool> {
    let is_directive = |c: &str| c.strip_prefix('#').is_some_and(|r| r.trim_start().starts_with("fmt:"));
    let lines: Vec<&str> = body.lines().collect();
    if lines.first().is_some_and(|l| is_directive(l.trim())) {
        return Some(true);
    }
    // Indentation of the line holding an open block scalar header.
    let mut block: Option<usize> = None;
    for l in &lines {
        let ind = l.len() - l.trim_start().len();
        if let Some(p) = block {
            if l.trim().is_empty() || ind > p {
                continue;
            }
            block = None;
        }
        let code = match yaml_comment_start(l) {
            Some(c) => {
                if is_directive(&l[c..]) {
                    let (normalized, _) = normalize_eol(body);
                    return crate::yaml::parser::Parser::new(&normalized).parse_stream().is_err().then_some(false);
                }
                &l[..c]
            }
            None => l,
        };
        let last = code.split_whitespace().last().unwrap_or("");
        let header = last.strip_prefix(['|', '>']).is_some_and(|r| r.len() <= 2 && r.chars().all(|c| matches!(c, '+' | '-' | '1'..='9')));
        if header {
            block = Some(ind);
        }
    }
    Some(false)
}

/// Byte offset of a comment on a YAML line, skipping quoted text on that line.
fn yaml_comment_start(l: &str) -> Option<usize> {
    let mut quote: Option<char> = None;
    let mut prev = ' ';
    let mut chars = l.char_indices().peekable();
    while let Some((i, c)) = chars.next() {
        match quote {
            Some('"') if c == '\\' => {
                chars.next();
            }
            Some(q) if c == q => {
                if q == '\'' && chars.peek().is_some_and(|&(_, n)| n == '\'') {
                    chars.next();
                } else {
                    quote = None;
                }
            }
            Some(_) => {}
            None if c == '#' && prev.is_whitespace() => return Some(i),
            None if (c == '"' || c == '\'') && (prev.is_whitespace() || "[{,:-".contains(prev)) => quote = Some(c),
            None => {}
        }
        prev = c;
    }
    None
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Eol {
    Lf,
    CrLf,
    Cr,
}

pub fn normalize_eol(text: &str) -> (String, Eol) {
    if !text.contains('\r') {
        return (text.to_string(), Eol::Lf);
    }
    let crlf = text.matches("\r\n").count();
    let lone_cr = text.matches('\r').count() - crlf;
    let lf = text.matches('\n').count() - crlf;
    let eol = if crlf >= lf && crlf >= lone_cr {
        Eol::CrLf
    } else if lone_cr > lf && lone_cr > crlf {
        Eol::Cr
    } else {
        Eol::Lf
    };
    let s = text.replace("\r\n", "\n").replace('\r', "\n");
    (s, eol)
}

/// Line endings for a file mixing CRLF and LF lines: an output line takes the
/// ending of the source line it comes from. Lines formatted together take the
/// ending of the first source line among them, or in Markdown of the last one
/// (table rows count as formatted together). Lines are matched through their
/// words.
fn restore_mixed_eol(text: &str, normalized: &str, out: &str, markdown: bool, eol: Eol) -> String {
    let src_lines: Vec<&str> = normalized.strip_suffix('\n').unwrap_or(normalized).split('\n').collect();
    let raw_lines: Vec<&str> = text.split('\n').collect();
    let crlf: Vec<bool> = (0..src_lines.len()).map(|i| raw_lines.get(i).is_some_and(|l| l.ends_with('\r'))).collect();
    let body = out.strip_suffix('\n');
    let out_lines: Vec<&str> = body.unwrap_or(out).split('\n').collect();
    let (n, m) = (src_lines.len(), out_lines.len());
    // Words are runs of letters and digits: formatting adds or drops quotes,
    // brackets, markers and spacing around them.
    let words = |l: &str| -> Vec<String> { l.split(|c: char| !c.is_alphanumeric()).filter(|t| !t.is_empty()).map(str::to_string).collect() };
    let src_tokens: Vec<(String, usize)> = src_lines.iter().enumerate().flat_map(|(i, l)| words(l).into_iter().map(move |t| (t, i))).collect();
    // Union-find over output lines (0..m) and source lines (m..m+n).
    let mut parent: Vec<usize> = (0..m + n).collect();
    fn find(p: &mut [usize], x: usize) -> usize {
        let mut r = x;
        while p[r] != r {
            r = p[r];
        }
        let mut y = x;
        while p[y] != r {
            let next = p[y];
            p[y] = r;
            y = next;
        }
        r
    }
    // Output tokens match source tokens in order: the next one, or a later one
    // followed by the same two tokens.
    let out_tokens: Vec<(String, usize)> = out_lines.iter().enumerate().flat_map(|(j, l)| words(l).into_iter().map(move |t| (t, j))).collect();
    let mut next = 0;
    for (p, (t, j)) in out_tokens.iter().enumerate() {
        let j = *j;
        let same = |k: usize, d: usize| match (src_tokens.get(k + d), out_tokens.get(p + d)) {
            (Some(a), Some(b)) => a.0 == b.0,
            (None, None) => true,
            _ => false,
        };
        let found = (next..(next + 64).min(src_tokens.len())).find(|&k| src_tokens[k].0 == *t && (k == next || (same(k, 1) && same(k, 2))));
        if let Some(k) = found {
            let i = src_tokens[k].1;
            let (a, b) = (find(&mut parent, j), find(&mut parent, m + i));
            parent[a] = b;
            next = k + 1;
        }
    }
    if markdown {
        for j in 1..m {
            if out_lines[j - 1].trim_start().starts_with('|') && out_lines[j].trim_start().starts_with('|') {
                let (a, b) = (find(&mut parent, j - 1), find(&mut parent, j));
                parent[a] = b;
            }
        }
    }
    // Folded block scalar content belongs together.
    {
        let mut j = 0;
        while j < m {
            let t = out_lines[j].trim_end();
            let header = t.rsplit(' ').next().is_some_and(|w| w.starts_with('>') && w[1..].chars().all(|c| matches!(c, '+' | '-' | '1'..='9')));
            if header {
                let ind = out_lines[j].len() - out_lines[j].trim_start().len();
                let mut k = j + 1;
                while k < m && (out_lines[k].trim().is_empty() || out_lines[k].len() - out_lines[k].trim_start().len() > ind) {
                    if k > j + 1 && !out_lines[k].trim().is_empty() {
                        let (a, b) = (find(&mut parent, j + 1), find(&mut parent, k));
                        parent[a] = b;
                    }
                    k += 1;
                }
                j = k;
                continue;
            }
            j += 1;
        }
    }
    // The first output line of each group.
    let mut first_out: Vec<Option<usize>> = vec![None; m + n];
    for j in 0..m {
        let r = find(&mut parent, j);
        first_out[r].get_or_insert(j);
    }
    // Source line range of each group.
    let mut range: Vec<Option<(usize, usize)>> = vec![None; m + n];
    for i in 0..n {
        let r = find(&mut parent, m + i);
        range[r] = Some(range[r].map_or((i, i), |(a, b)| (a.min(i), b.max(i))));
    }
    let mut res = String::new();
    let mut frontier = 0;
    for (j, l) in out_lines.iter().enumerate() {
        let r = find(&mut parent, j);
        // Lines without words consume source lines in order; a document marker
        // added between YAML documents takes the file's prevailing ending.
        let is_crlf = match range[r] {
            Some((a, b)) => {
                frontier = b + 1;
                // Markdown blocks end like their last line, a setext heading like its
                // underline; list items and quotes, like YAML nodes, like their first.
                let mut b = b;
                if markdown && l.trim_start().starts_with('#') && src_lines.get(b + 1).is_some_and(|u| !u.trim().is_empty() && u.trim().chars().all(|c| c == '=' || c == '-')) {
                    b += 1;
                    frontier = b + 1;
                }
                let lead = out_lines[first_out[r].unwrap_or(j)];
                let container = lead.trim_start().starts_with('>') || crate::markdown::block::list_marker(lead).is_some();
                let scalar = first_out[r].is_some_and(|f| {
                    f > 0 && out_lines[f - 1].trim_end().rsplit(' ').next().is_some_and(|w| w.starts_with('>') && w[1..].chars().all(|c| matches!(c, '+' | '-' | '1'..='9')))
                });
                crlf[if (markdown && !container) || scalar { b } else { a }]
            }
            None if !markdown && *l == "---" && src_lines.get(frontier).is_some_and(|s| s.trim_end() == "---") => {
                frontier += 1;
                crlf[frontier - 1]
            }
            None if !markdown && *l == "---" => eol == Eol::CrLf,
            // Inside output made from one source line, a line without words ends
            // like the rest.
            None if !l.trim().is_empty() && (j + 1..m).find_map(|k| range[find(&mut parent, k)]).is_some_and(|(a, _)| a < frontier) => {
                let (a, _) = (j + 1..m).find_map(|k| range[find(&mut parent, k)]).unwrap();
                crlf[a]
            }
            None => {
                // A blank line takes a nearby blank source line.
                if l.trim().is_empty() {
                    if let Some(k) = (frontier..(frontier + 3).min(n)).find(|&k| src_lines[k].trim().is_empty()) {
                        frontier = k;
                    }
                }
                frontier += 1;
                crlf.get((frontier - 1).min(n.saturating_sub(1))).copied().unwrap_or(false)
            }
        };
        res.push_str(l);
        if j + 1 < m || body.is_some() {
            res.push_str(if is_crlf { "\r\n" } else { "\n" });
        }
    }
    res
}

pub fn restore_eol(text: &str, eol: Eol) -> String {
    match eol {
        Eol::Lf => text.to_string(),
        Eol::CrLf => text.replace('\n', "\r\n"),
        Eol::Cr => text.replace('\n', "\r"),
    }
}

pub fn decode(bytes: &[u8]) -> Result<String, String> {
    if bytes.starts_with(&[0xFF, 0xFE]) || bytes.starts_with(&[0xFE, 0xFF]) {
        return Err("unsupported encoding: UTF-16 BOM".to_string());
    }
    match std::str::from_utf8(bytes) {
        Ok(s) => Ok(s.to_string()),
        Err(e) => Err(format!("invalid UTF-8: {}", e)),
    }
}

fn base_options(m: &Matches) -> Options {
    let mut o = Options::default();
    if let Some(n) = m.value("line-width") {
        o.line_width = n.parse().unwrap_or(80);
    }
    if let Some(n) = m.value("prose-width") {
        o.prose_width = n.parse().unwrap_or(72);
    }
    if let Some(n) = m.value("indent-width") {
        o.indent_width = n.parse().unwrap_or(2);
    }
    o.canonical = m.flag("canonical");
    o.preserve_footnotes = m.flag("preserve-footnotes");
    o.compact = m.flag("compact");
    o.skip_embedded = m.flag("skip-embedded-formatters");
    o.diagnostics = m.flag("diagnostics");
    o
}

/// Apply config and CLI overrides to produce the effective options for one file.
pub fn effective_options(m: &Matches, cfg: Option<&config::Config>, file: &Path) -> Options {
    let mut o = base_options(m);
    if let Some(c) = cfg {
        c.apply(&mut o, file);
    }
    if m.flag("compact") {
        o.compact = true;
    }
    if let Some(w) = m.value("wrap") {
        if let Some(w) = crate::options::parse_wrap(w) {
            o.wrap = w;
        }
    }
    if let Some(t) = m.value("table-widths") {
        o.table_widths = if t == "preserve" { TableWidths::Preserve } else { TableWidths::Fit };
    }
    o
}

fn print_diag(path: &str, d: &Diagnostic, kind: &str) -> String {
    format!("{}:{}:{}: {}: {}\n", path, d.line, d.col, kind, d.msg)
}

fn run_stdin(m: &Matches, path: &str) -> i32 {
    let kind = match detect_kind(path) {
        Some(k) => k,
        None => {
            eprint!("{}:1:1: error: unsupported file type\n", path);
            return 1;
        }
    };
    let cfg = match load_config_for(m, Path::new(path)) {
        Ok(c) => c,
        Err((p, msg)) => {
            eprint!("{}:1:1: error: {}\n", p, msg);
            return 1;
        }
    };
    let mut bytes = Vec::new();
    let _ = std::io::stdin().read_to_end(&mut bytes);
    let text = match decode(&bytes) {
        Ok(t) => t,
        Err(e) => {
            eprint!("{}:1:1: error: {}\n", path, e);
            return 1;
        }
    };
    let opts = effective_options(m, cfg.as_ref(), Path::new(path));
    match format_text(kind, &text, &opts) {
        Ok(out) => {
            let mut err = String::new();
            if opts.diagnostics {
                for n in &out.notes {
                    err.push_str(&print_diag(path, n, "note"));
                }
            }
            eprint!("{}", err);
            let mut so = std::io::stdout();
            let _ = so.write_all(out.text.as_bytes());
            let _ = so.flush();
            0
        }
        Err(d) => {
            eprint!("{}", print_diag(path, &d, "error"));
            1
        }
    }
}

type ConfigResult = Result<Option<config::Config>, (String, String)>;

fn load_config_for(m: &Matches, file: &Path) -> ConfigResult {
    if let Some(p) = m.value("config") {
        return config::load_explicit(p).map(Some);
    }
    config::discover(file)
}

pub fn run_format(m: &Matches) -> i32 {
    if let Some(p) = m.value("stdin-file-path") {
        if !m.positionals.is_empty() {
            eprint!("error: --stdin-file-path cannot be used with PATHS\n");
            return 2;
        }
        if m.flag("check") || m.flag("diff") {
            eprint!("error: --stdin-file-path cannot be used with --check or --diff\n");
            return 2;
        }
        let p = p.to_string();
        return run_stdin(m, &p);
    }
    let check = m.flag("check");
    let diff_mode = m.flag("diff");
    let roots: Vec<String> = if m.positionals.is_empty() {
        vec![".".to_string()]
    } else {
        m.positionals.clone()
    };
    for r in &roots {
        if std::fs::symlink_metadata(r).is_err() && !Path::new(r).exists() {
            eprint!("{}:1:1: error: path does not exist\n", r);
            return 1;
        }
    }
    // Explicit config is loaded once up front.
    let explicit_cfg = if let Some(p) = m.value("config") {
        match config::load_explicit(p) {
            Ok(c) => Some(c),
            Err((p, msg)) => {
                eprint!("{}:1:1: error: {}\n", p, msg);
                return 1;
            }
        }
    } else {
        None
    };
    let mut files: Vec<PathBuf> = Vec::new();
    let mut seen: HashSet<PathBuf> = HashSet::new();
    let mut walker = Walker::new();
    for r in &roots {
        let p = Path::new(r);
        let list = if p.is_dir() { walker.walk(p) } else { vec![p.to_path_buf()] };
        for f in list {
            let key = std::fs::canonicalize(&f).unwrap_or_else(|_| f.clone());
            if seen.insert(key) {
                files.push(f);
            }
        }
    }

    // Configurations are resolved for every selected file before any formatting.
    let mut configs: Vec<Option<config::Config>> = Vec::new();
    {
        let mut cache: std::collections::HashMap<PathBuf, Option<config::Config>> = std::collections::HashMap::new();
        for f in &files {
            if explicit_cfg.is_some() || detect_kind(&f.to_string_lossy()).is_none() {
                configs.push(None);
                continue;
            }
            let dir = f.parent().map(|p| p.to_path_buf()).unwrap_or_default();
            if let Some(c) = cache.get(&dir) {
                configs.push(c.clone());
                continue;
            }
            match config::discover(f) {
                Ok(c) => {
                    cache.insert(dir, c.clone());
                    configs.push(c);
                }
                Err((p, msg)) => {
                    eprint!("{}:1:1: error: {}\n", p, msg);
                    return 1;
                }
            }
        }
    }
    let mut scanned = 0usize;
    let mut formatted = 0usize;
    let mut unchanged = 0usize;
    let mut skipped = 0usize;
    let mut failed = 0usize;
    // (path, is_note, text)
    let mut msgs: Vec<(String, bool, String)> = Vec::new();
    let mut stdout = std::io::stdout();
    for (fi, f) in files.iter().enumerate() {
        scanned += 1;
        let display = f.to_string_lossy().into_owned();
        let kind = match detect_kind(&display) {
            Some(k) => k,
            None => {
                skipped += 1;
                continue;
            }
        };
        let cfg: Option<&config::Config> = if let Some(c) = &explicit_cfg { Some(c) } else { configs[fi].as_ref() };
        let bytes = match std::fs::read(f) {
            Ok(b) => b,
            Err(e) => {
                failed += 1;
                msgs.push((display.clone(), false, format!("{}:1:1: error: failed to read file: {}\n", display, io_error_text(&e))));
                continue;
            }
        };
        let text = match decode(&bytes) {
            Ok(t) => t,
            Err(e) => {
                failed += 1;
                msgs.push((display.clone(), false, format!("{}:1:1: error: failed to read file: {}\n", display, e)));
                continue;
            }
        };
        let opts = effective_options(m, cfg, f);
        match format_text(kind, &text, &opts) {
            Ok(out) => {
                for n in &out.notes {
                    msgs.push((display.clone(), true, print_diag(&display, n, "note")));
                }
                if out.text == text {
                    unchanged += 1;
                } else {
                    formatted += 1;
                    if diff_mode {
                        let d = diff::unified_diff(&text, &out.text, &display, &display);
                        let _ = stdout.write_all(d.as_bytes());
                    } else if !check {
                        if let Err(e) = std::fs::write(f, out.text.as_bytes()) {
                            failed += 1;
                            formatted -= 1;
                            msgs.push((display.clone(), false, format!("{}:1:1: error: failed to write file: {}\n", display, io_error_text(&e))));
                        }
                    }
                }
            }
            Err(d) => {
                failed += 1;
                msgs.push((display.clone(), false, print_diag(&display, &d, "error")));
            }
        }
    }
    let show_notes = m.flag("diagnostics") || failed > 0;
    msgs.sort_by(|a, b| a.0.cmp(&b.0));
    let mut messages = String::new();
    for (_, is_note, text) in &msgs {
        if *is_note && !show_notes {
            continue;
        }
        messages.push_str(text);
    }
    let _ = stdout.flush();
    let summary = format!(
        "{} files scanned, {} formatted, {} unchanged, {} skipped, {} failed\n",
        scanned, formatted, unchanged, skipped, failed
    );
    if check || diff_mode {
        eprint!("{}{}", summary, messages);
    } else {
        let _ = stdout.write_all(summary.as_bytes());
        let _ = stdout.flush();
        eprint!("{}", messages);
    }
    if failed > 0 {
        return 1;
    }
    if (check || diff_mode) && formatted > 0 {
        return 1;
    }
    0
}

pub fn io_error_text(e: &std::io::Error) -> String {
    e.to_string()
}
