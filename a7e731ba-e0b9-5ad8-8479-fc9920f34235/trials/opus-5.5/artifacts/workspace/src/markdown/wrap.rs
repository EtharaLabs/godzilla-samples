// Line filling for Markdown prose.

use super::inline::{dangerous_start, Unit, UnitKind};
/// Prose is measured in characters.
fn width(s: &str) -> usize {
    s.chars().count()
}
use crate::options::Wrap;

#[derive(Debug, Clone)]
struct Piece {
    text: String,
    /// Forced alone on its own line with extra indentation (split link destination).
    dest: bool,
    /// Forces a new line before this piece.
    newline_before: bool,
    hard_break: bool,
    /// Index of the unit this piece came from.
    unit: usize,
}

fn merge_dangerous(units: &[Unit]) -> Vec<Unit> {
    let mut out: Vec<Unit> = Vec::new();
    for u in units {
        if u.kind == UnitKind::Text && !out.is_empty() && dangerous_start(&u.text) {
            let prev = out.last_mut().unwrap();
            if prev.kind == UnitKind::Text {
                prev.text.push(' ');
                prev.text.push_str(&u.text);
                prev.link_split = Vec::new();
                continue;
            }
        }
        out.push(u.clone());
    }
    out
}

fn to_pieces(units: &[Unit], max_width: usize) -> Vec<Piece> {
    let mut pieces = Vec::new();
    for (ui, u) in units.iter().enumerate() {
        if u.kind == UnitKind::HardBreak {
            pieces.push(Piece { text: u.text.clone(), dest: false, newline_before: false, hard_break: true, unit: ui });
            continue;
        }
        if !u.link_split.is_empty() && width(&u.text) > max_width {
            let mut pos = 0;
            let n = u.link_split.len();
            for (k, &(a, b)) in u.link_split.iter().enumerate() {
                let pre = &u.text[pos..a];
                pieces.push(Piece { text: pre.to_string(), dest: false, newline_before: k > 0, hard_break: false, unit: ui });
                pieces.push(Piece { text: u.text[a..b].to_string(), dest: true, newline_before: true, hard_break: false, unit: ui });
                pos = b;
                // Stop splitting once the remainder fits.
                if k + 1 < n && width(&u.text[b..]) <= max_width {
                    break;
                }
            }
            pieces.push(Piece { text: u.text[pos..].to_string(), dest: false, newline_before: true, hard_break: false, unit: ui });
            continue;
        }
        pieces.push(Piece { text: u.text.clone(), dest: false, newline_before: false, hard_break: false, unit: ui });
    }
    pieces
}

/// Runs of '-', '=', '*' or '_' only matter when they make up the whole line.
fn rule_char(t: &str) -> Option<char> {
    let c = t.chars().next()?;
    if !matches!(c, '-' | '=' | '*' | '_') || !t.chars().all(|x| x == c) {
        return None;
    }
    let n = t.chars().count();
    let ok = match c {
        '-' => n >= 2,
        '=' => n >= 1,
        _ => n >= 3,
    };
    if ok {
        Some(c)
    } else {
        None
    }
}

/// Whether a line beginning with these tokens would start a block construct.
fn line_start_dangerous(tokens: &[&str]) -> bool {
    let first = tokens[0];
    if let Some(c) = rule_char(first) {
        return tokens.iter().all(|t| t.chars().all(|x| x == c));
    }
    dangerous_start(first)
}

/// Escape a token that would otherwise start a block construct.
pub fn escape_token(tok: &str) -> Option<String> {
    escape_sentence_start(tok)
}

/// Greedy fill. `first_width` applies to the first line, `width` to the rest.
/// Destination pieces are emitted on their own line prefixed by two spaces.
/// Returns None when a block-starting token cannot be kept off a line start.
pub fn try_fill(units: &[Unit], first_width: usize, rest_width: usize) -> Option<Vec<String>> {
    try_fill_ex(units, first_width, rest_width, false).map(|(l, _)| l)
}

/// Like `try_fill`; with `prefer_escape` (sentence mode) an escapable
/// block-starting token is escaped in place instead of pulling earlier words
/// down, pulling words down may overflow the width, and a token that cannot be
/// placed safely stays on the current line. Also returns the indices of escaped
/// units with their escaped spelling.
fn try_fill_ex(units: &[Unit], first_width: usize, rest_width: usize, prefer_escape: bool) -> Option<(Vec<String>, Vec<(usize, String)>)> {
    let pieces = to_pieces(units, rest_width);
    let mut escaped: Vec<(usize, String)> = Vec::new();
    let mut lines: Vec<String> = Vec::new();
    // Current line as a list of piece texts.
    let mut cur: Vec<String> = Vec::new();
    let mut cur_w = 0usize;
    let line_w = |v: &Vec<String>| -> usize {
        if v.is_empty() {
            0
        } else {
            v.iter().map(|t| width(t)).sum::<usize>() + v.len() - 1
        }
    };
    for p in pieces {
        let avail = if lines.is_empty() { first_width } else { rest_width };
        if p.dest {
            if !cur.is_empty() {
                lines.push(cur.join(" "));
                cur.clear();
            }
            // Only a leading `fig-alt` value is wrapped.
            let alt_first = p.text.find('"').map(|q| p.text[..q].ends_with("fig-alt=")).unwrap_or(false);
            // Everything up to the first word of the text must fit on the first line.
            let head_fits = p.text.find('"').map(|q| {
                let head_end = p.text[q..].find(' ').map(|e| q + e).unwrap_or(p.text.len());
                2 + width(&p.text[..head_end]) <= rest_width
            });
            let is_attr = alt_first && head_fits == Some(true) && p.text.ends_with('"') && p.text.contains(' ');
            if is_attr && 2 + width(&p.text) > rest_width {
                // The text wraps like prose without indentation; continuation
                // lines stop one column short and the closing quote is not measured.
                let body = &p.text[..p.text.len() - 1];
                let words: Vec<&str> = body.split(' ').filter(|w| !w.is_empty()).collect();
                let mut line = String::from("  ");
                let mut lw = 2;
                let mut first = true;
                let mut first_line = true;
                for w in words {
                    let ww = width(w);
                    let limit = if first_line { rest_width } else { rest_width.saturating_sub(1) };
                    if first {
                        line.push_str(w);
                        lw += ww;
                        first = false;
                    } else if lw + 1 + ww <= limit {
                        line.push(' ');
                        line.push_str(w);
                        lw += 1 + ww;
                    } else {
                        lines.push(std::mem::take(&mut line));
                        first_line = false;
                        line.push_str(w);
                        lw = ww;
                    }
                }
                line.push('"');
                lines.push(line);
            } else {
                lines.push(format!("  {}", p.text));
            }
            cur_w = 0;
            continue;
        }
        if p.newline_before && !cur.is_empty() {
            lines.push(cur.join(" "));
            cur.clear();
            cur_w = 0;
        }
        if p.hard_break && p.text == "\\" {
            cur.push(p.text.clone());
            lines.push(cur.join(" "));
            cur.clear();
            cur_w = 0;
            continue;
        }
        // A trailing hard-break backslash is not measured.
        let pw = width(&p.text) - usize::from(p.hard_break && p.text.ends_with('\\'));
        if cur.is_empty() {
            cur.push(p.text.clone());
            cur_w = pw;
        } else if cur_w + 1 + pw <= avail {
            cur.push(p.text.clone());
            cur_w += 1 + pw;
        } else if !line_start_dangerous(&[p.text.as_str()]) {
            lines.push(cur.join(" "));
            cur.clear();
            cur.push(p.text.clone());
            cur_w = pw;
        } else if let Some(esc) = escape_token(&p.text).filter(|_| prefer_escape) {
            lines.push(cur.join(" "));
            cur.clear();
            cur_w = width(&esc);
            escaped.push((p.unit, esc.clone()));
            cur.push(esc);
        } else {
            let rest_avail = rest_width;
            // Move trailing units down until the new line starts safely.
            let mut moved: Option<usize> = None;
            let mut k = 1;
            while k < cur.len() {
                let tail = &cur[cur.len() - k..];
                let tw: usize = tail.iter().map(|t| width(t)).sum::<usize>() + tail.len() + pw;
                if tw > rest_avail && !prefer_escape {
                    break;
                }
                let mut cand: Vec<&str> = tail.iter().map(|t| t.as_str()).collect();
                cand.push(p.text.as_str());
                if !line_start_dangerous(&cand) {
                    moved = Some(k);
                    break;
                }
                k += 1;
            }
            if let Some(k) = moved {
                let tail: Vec<String> = cur.split_off(cur.len() - k);
                lines.push(cur.join(" "));
                cur.clear();
                cur.extend(tail);
                cur.push(p.text.clone());
                cur_w = line_w(&cur);
            } else if let Some(esc) = escape_token(&p.text) {
                lines.push(cur.join(" "));
                cur.clear();
                cur_w = width(&esc);
                escaped.push((p.unit, esc.clone()));
                cur.push(esc);
            } else if prefer_escape {
                // Sentence mode keeps the token on the current line instead.
                cur.push(p.text.clone());
                cur_w += 1 + pw;
            } else {
                return None;
            }
        }
        if p.hard_break {
            lines.push(cur.join(" "));
            cur.clear();
            cur_w = 0;
        }
    }
    if !cur.is_empty() || lines.is_empty() {
        lines.push(cur.join(" "));
    }
    Some((lines, escaped))
}

pub fn fill(units: &[Unit], first_width: usize, rest_width: usize) -> Vec<String> {
    match try_fill(units, first_width, rest_width) {
        Some(l) => l,
        None => {
            let merged = merge_dangerous(units);
            try_fill(&merged, first_width, rest_width).unwrap_or_default()
        }
    }
}

/// Units of a paragraph on one line per hard-break segment.
pub fn join_all(units: &[Unit]) -> Vec<String> {
    fill(units, usize::MAX / 2, usize::MAX / 2)
}

fn strip_closers(s: &str) -> &str {
    s.trim_end_matches(['"', '\'', ')', ']', '\u{201d}', '\u{2019}', '*', '_'])
}

fn ends_sentence(tok: &str) -> bool {
    let core = tok.trim_start_matches(['(', '"', '\'', '[', '\u{201c}', '\u{2018}']);
    let lower = core.to_lowercase();
    if lower == "e.g." || lower == "i.e." {
        return false;
    }
    let t = tok.trim_end_matches(['"', '\'', ')', ']', '}']);
    let _ = strip_closers;
    if !(t.ends_with('.') || t.ends_with('!') || t.ends_with('?')) {
        return false;
    }
    // An escaped punctuation mark does not end a sentence.
    let slashes = t[..t.len() - 1].chars().rev().take_while(|&c| c == '\\').count();
    slashes % 2 == 0
}

/// Sentence-start classification: None = safe, Some(Some(esc)) = escaped spelling,
/// Some(None) = cannot start a line.
fn sentence_start_hazard(tok: &str) -> Option<Option<String>> {
    if let Some(e) = escape_sentence_start(tok) {
        return Some(Some(e));
    }
    let c0 = tok.chars().next()?;
    if c0 == '|' || c0 == ':' || tok == "~" {
        return Some(None);
    }
    if c0 == '[' && tok.find(']').is_some_and(|p| p > 1 && tok[p + 1..].starts_with(':')) {
        return Some(None);
    }
    if c0 == '<' {
        let chars: Vec<char> = tok.chars().collect();
        if let Some((_, name, _, _)) = super::inline::html_tag_at(&chars, 0) {
            if super::inline::BLOCK_TAG_NAMES.contains(&name.as_str()) {
                return Some(None);
            }
        }
    }
    None
}

/// Escape a token that would start a block construct at the start of a line.
fn escape_sentence_start(tok: &str) -> Option<String> {
    if tok == "-" || tok == "+" || tok == "*" {
        return Some(format!("\\{}", tok));
    }
    if tok.starts_with('#') && tok.chars().all(|c| c == '#') && tok.len() <= 6 {
        return Some(format!("\\{}", tok));
    }
    if tok.starts_with('>') {
        return Some(format!("\\{}", tok));
    }
    // Parenthesized markers: escape the closing parenthesis.
    if tok.starts_with('(') && tok.ends_with(')') && tok.len() > 2 {
        let label = &tok[1..tok.len() - 1];
        if super::block::is_list_label(label, true) {
            return Some(format!("({}\\)", label));
        }
    }
    // Ordered markers: escape the delimiter.
    for d in ['.', ')'] {
        if let Some(b) = tok.strip_suffix(d) {
            if super::block::is_list_label(b, false) {
                return Some(format!("{}\\{}", b, d));
            }
        }
    }
    None
}

/// Split units into sentences (each a list of units).
fn sentences(units: &[Unit], limited: bool) -> Vec<Vec<Unit>> {
    let mut out: Vec<Vec<Unit>> = Vec::new();
    let mut cur: Vec<Unit> = Vec::new();
    let n = units.len();
    let mut i = 0;
    while i < n {
        let u = units[i].clone();
        let is_break = u.kind == UnitKind::HardBreak;
        if is_break && u.text == "\\" && cur.is_empty() {
            if let Some(prev) = out.last_mut() {
                prev.push(u);
                i += 1;
                continue;
            }
        }
        cur.push(u.clone());
        if is_break {
            out.push(std::mem::take(&mut cur));
            i += 1;
            continue;
        }
        if i + 1 < n && ends_sentence(&u.text) {
            let next = &units[i + 1];
            if next.kind == UnitKind::Text {
                let mut hazard = sentence_start_hazard(&next.text);
                if hazard.is_none() {
                    if let Some(c) = rule_char(&next.text) {
                        // With a width limit the token may end up alone on a line;
                        // otherwise the rest of the paragraph forms the line.
                        let rule_line = limited
                            || units[i + 1..]
                                .iter()
                                .take_while(|u| u.kind != UnitKind::HardBreak)
                                .all(|u| u.kind == UnitKind::Text && u.text.chars().all(|x| x == c));
                        if rule_line {
                            hazard = Some(None);
                        }
                    }
                }
                match hazard {
                    Some(Some(esc)) => {
                        out.push(std::mem::take(&mut cur));
                        let mut nu = next.clone();
                        nu.text = esc;
                        cur.push(nu);
                        i += 2;
                        continue;
                    }
                    Some(None) => {
                        // Cannot start a line here; keep in the same sentence.
                        i += 1;
                        continue;
                    }
                    None => {}
                }
            }
            out.push(std::mem::take(&mut cur));
        }
        i += 1;
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

pub fn wrap_units(units: &[Unit], wrap: Wrap, first_width: usize, rest_width: usize) -> Option<Vec<String>> {
    match wrap {
        Wrap::Column(_) => try_fill(units, first_width, rest_width),
        Wrap::Paragraph | Wrap::None => Some(join_all(units)),
        Wrap::Sentence(None) => Some(sentences(units, false).iter().flat_map(|s| join_all(s)).collect()),
        Wrap::Sentence(Some(_)) => {
            // Escaping a sentence-final token makes it no longer end the
            // sentence, so the split is recomputed after each such escape.
            let mut units = units.to_vec();
            'retry: loop {
                let sents = sentences(&units, true);
                let mut lines = Vec::new();
                let mut base = 0;
                for (si, s) in sents.iter().enumerate() {
                    let fw = if lines.is_empty() { first_width } else { rest_width };
                    let (l, escaped) = try_fill_ex(s, fw, rest_width, true)?;
                    for (k, esc) in escaped {
                        if si + 1 < sents.len() && ends_sentence(&s[k].text) && !ends_sentence(&esc) {
                            units[base + k].text = esc;
                            continue 'retry;
                        }
                    }
                    lines.extend(l);
                    base += s.len();
                }
                return Some(lines);
            }
        }
    }
}
