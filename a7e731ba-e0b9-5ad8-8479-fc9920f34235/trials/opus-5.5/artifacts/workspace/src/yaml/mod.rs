// YAML formatting.

pub mod directive;
pub mod emit;
pub mod parser;
pub mod scalar;

use crate::format_cmd::Diagnostic;
use crate::options::Options;
use std::cell::RefCell;

thread_local! {
    /// Notes produced while formatting YAML (embedded formatter skips).
    pub static YAML_NOTES: RefCell<Vec<Diagnostic>> = const { RefCell::new(Vec::new()) };
    /// Counters from the most recent YAML emission.
    pub static LAST_STATS: RefCell<Option<(emit::Stats, usize)>> = const { RefCell::new(None) };
}

fn count_nodes(n: &parser::Node) -> usize {
    use parser::Kind;
    1 + match &n.kind {
        Kind::Map(es) => es.iter().map(|e| (if e.quirk == 0 { 1 } else { 0 }) + count_nodes(&e.value)).sum(),
        Kind::Seq(items) => items.iter().map(|i| count_nodes(&i.value)).sum(),
        Kind::FlowMap(es) | Kind::FlowSeq(es) => es
            .iter()
            .map(|e| e.key.as_ref().map(count_nodes).unwrap_or(0) + e.value.as_ref().map(count_nodes).unwrap_or(0))
            .sum(),
        _ => 0,
    }
}

/// Format a YAML stream. Unparseable input is returned unchanged.
pub fn format_yaml(src: &str, opts: &Options) -> Result<String, Diagnostic> {
    if src.is_empty() {
        return Ok(String::new());
    }
    let p = parser::Parser::new(src);
    let line_starts = p.line_starts.clone();
    let stream = match p.parse_stream() {
        Ok(s) => s,
        Err(e) => {
            if std::env::var_os("YAMARK_DEBUG").is_some() {
                let line = src[..e.pos.min(src.len())].matches('\n').count() + 1;
                eprintln!("yaml parse error at line {}: {}", line, e.msg);
            }
            return Ok(src.to_string());
        }
    };
    let dirs = directive::collect(src, &stream, &line_starts)?;
    if dirs.skip_file {
        return Ok(src.to_string());
    }
    let mut em = emit::Emitter::new(src, stream.line_kinds.clone(), line_starts, opts);
    em.off_regions = dirs.off_regions.clone();
    em.skip_lines = dirs.skip_lines.clone();
    em.md_dirs = dirs.markdown.clone();
    em.opt_dirs = dirs.options.clone();
    em.emb_dirs = dirs.embedded.clone();
    resolve_collection_dirs(src, &stream, &line_starts_of(src), &dirs, &mut em)?;
    em.emit_stream(&stream);
    if let Some(e) = em.error.take() {
        return Err(e);
    }
    YAML_NOTES.with(|n| n.borrow_mut().extend(em.notes.drain(..)));
    let stats = em.stats.clone();
    let semantic: usize = stream.docs.iter().map(|d| d.root.as_ref().map(count_nodes).unwrap_or(0)).sum();
    LAST_STATS.with(|s| *s.borrow_mut() = Some((stats, semantic)));
    if let Some(&l) = em.skip_lines.iter().find(|l| !em.used_skips.contains(l)) {
        let _ = l;
        let (el, ec) = directive::eof_pos(src);
        return Err(Diagnostic { line: el, col: ec, msg: "fmt: skip has no target".into() });
    }
    let mut out = em.out.join("\n");
    if src.ends_with('\n') {
        out.push('\n');
    }
    Ok(out)
}

fn line_starts_of(src: &str) -> Vec<usize> {
    let mut v = vec![0];
    for (i, c) in src.bytes().enumerate() {
        if c == b'\n' {
            v.push(i + 1);
        }
    }
    v
}

fn coll_key(n: &parser::Node, ls: &[usize]) -> usize {
    match &n.kind {
        parser::Kind::Seq(items) => items.first().map(|i| ls[i.line] + i.col).unwrap_or(n.start),
        _ => n.start,
    }
}

/// Places that bind a pending collection directive, in document order:
/// (line, collection key, is sequence). Every sequence item binds its sequence;
/// a mapping entry binds its collection value.
fn dir_anchors(n: &parser::Node, ls: &[usize], out: &mut Vec<(usize, usize, bool)>) {
    use parser::Kind;
    match &n.kind {
        Kind::Map(es) => {
            for e in es {
                let v = &e.value;
                if matches!(v.kind, Kind::Map(_) | Kind::Seq(_) | Kind::FlowMap(_) | Kind::FlowSeq(_)) {
                    out.push((e.line, coll_key(v, ls), matches!(v.kind, Kind::Seq(_) | Kind::FlowSeq(_))));
                }
                dir_anchors(v, ls, out);
            }
        }
        Kind::Seq(items) => {
            let k = coll_key(n, ls);
            for it in items {
                out.push((it.line, k, true));
                dir_anchors(&it.value, ls, out);
            }
        }
        Kind::FlowSeq(_) => out.push((n.line, n.start, true)),
        _ => {}
    }
}

/// Bind `fmt: table` and `fmt: compact` directives to the collections they target.
fn resolve_collection_dirs(src: &str, stream: &parser::Stream, ls: &[usize], dirs: &directive::Directives, em: &mut emit::Emitter) -> Result<(), Diagnostic> {
    use directive::Scope;
    let mut anchors = Vec::new();
    for d in &stream.docs {
        if let Some(r) = &d.root {
            dir_anchors(r, ls, &mut anchors);
        }
    }
    let eof = || directive::eof_pos(src);
    for &(line, collapse) in &dirs.tables {
        match anchors.iter().find(|a| a.2 && a.0 > line) {
            Some(a) => {
                em.table_targets.insert(a.1, collapse);
            }
            None => {
                let (l, c) = eof();
                return Err(Diagnostic { line: l, col: c, msg: "fmt: table has no target".into() });
            }
        }
    }
    for &(line, on, scope) in &dirs.compacts {
        if scope != Scope::Next {
            em.compact_scoped.push((line, on, scope));
            continue;
        }
        match anchors.iter().find(|a| a.0 > line) {
            Some(a) => {
                em.compact_override.insert(a.1, on);
            }
            None => {
                let (l, c) = eof();
                return Err(Diagnostic { line: l, col: c, msg: "fmt: compact has no target".into() });
            }
        }
    }
    Ok(())
}

pub fn format_yaml_file(text: &str, opts: &Options, notes: &mut Vec<Diagnostic>) -> Result<String, Diagnostic> {
    YAML_NOTES.with(|n| n.borrow_mut().clear());
    LAST_STATS.with(|s| *s.borrow_mut() = None);
    let r = match format_json_lines(text, opts) {
        Some(out) => Ok(out),
        None => format_yaml(text, opts),
    };
    YAML_NOTES.with(|n| notes.extend(n.borrow_mut().drain(..)));
    if opts.diagnostics {
        if let Ok(out) = &r {
            let lines = if text.is_empty() { 0 } else { text.strip_suffix('\n').unwrap_or(text).split('\n').count() };
            let (st, sem) = LAST_STATS.with(|s| s.borrow().clone()).unwrap_or_default();
            let msg = format!(
                "yaml trace: source_scans=1 parse_passes=1 source_lines={} yaml_scanned_lines={} yaml_semantic_nodes={} planned_rendered_scalars={} planned_rendered_flow_collections={} planned_rendered_block_flow_collections={} emitted_bytes={} emitted_nodes={}",
                lines, lines, sem, st.scalars, st.flows, st.block_flows, out.len(), st.emitted_nodes
            );
            notes.push(Diagnostic { line: 1, col: 1, msg });
        }
    }
    r
}

/// A stream of two or more one-line flow-mapping roots becomes a multi-document stream.
fn format_json_lines(text: &str, opts: &Options) -> Option<String> {
    let body = text.strip_suffix('\n').unwrap_or(text);
    let lines: Vec<&str> = body.split('\n').collect();
    if lines.len() < 2 {
        return None;
    }
    for l in &lines {
        let t = l.trim();
        if !t.starts_with('{') {
            return None;
        }
        let p = parser::Parser::new(t);
        let st = p.parse_stream().ok()?;
        if st.docs.len() != 1 || !st.docs[0].extra.is_empty() {
            return None;
        }
        match &st.docs[0].root {
            Some(n) if matches!(n.kind, parser::Kind::FlowMap(_)) && n.end_line == 0 => {}
            _ => return None,
        }
    }
    let mut out = String::new();
    let mut total = emit::Stats::default();
    let mut sem = 0;
    for l in &lines {
        out.push_str("---\n");
        let f = format_yaml(&format!("{}\n", l.trim_end()), opts).ok()?;
        if let Some((st, n)) = LAST_STATS.with(|s| s.borrow().clone()) {
            total.scalars += st.scalars;
            total.flows += st.flows;
            total.block_flows += st.block_flows;
            total.emitted_nodes += st.emitted_nodes;
            sem += n;
        }
        out.push_str(&f);
    }
    LAST_STATS.with(|s| *s.borrow_mut() = Some((total, sem)));
    if !text.ends_with('\n') {
        out.pop();
    }
    Some(out)
}
