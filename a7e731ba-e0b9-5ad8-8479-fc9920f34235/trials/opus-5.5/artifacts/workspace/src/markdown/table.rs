// GFM pipe table formatting.

use super::inline::collapse_ws;
use super::width::width;
use crate::options::TableWidths;

#[derive(Clone, Copy, PartialEq, Eq)]
enum Align {
    None,
    Left,
    Right,
    Center,
}

/// Split a table row into cells, honoring escapes and code spans.
fn split_row(line: &str) -> Vec<String> {
    split_row_raw(line).1.into_iter().map(|c| collapse_ws(c.trim())).collect()
}

/// Raw cell texts of a row, with whether it has leading and trailing pipes.
fn split_row_raw(line: &str) -> (bool, Vec<String>, bool) {
    let t = line.trim();
    let lead = t.starts_with('|');
    let trail = t.len() > 1 && t.ends_with('|') && !t.ends_with("\\|");
    let t = t.strip_prefix('|').unwrap_or(t);
    let chars: Vec<char> = t.chars().collect();
    let mut cells = Vec::new();
    let mut cur = String::new();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c == '\\' && i + 1 < chars.len() {
            cur.push(c);
            cur.push(chars[i + 1]);
            i += 2;
            continue;
        }
        if c == '`' {
            let mut n = 0;
            while i + n < chars.len() && chars[i + n] == '`' {
                n += 1;
            }
            // find closing run
            let mut j = i + n;
            let mut found = None;
            while j < chars.len() {
                if chars[j] == '`' {
                    let mut m = 0;
                    while j + m < chars.len() && chars[j + m] == '`' {
                        m += 1;
                    }
                    if m == n {
                        found = Some(j + m);
                        break;
                    }
                    j += m;
                } else {
                    j += 1;
                }
            }
            match found {
                Some(e) => {
                    cur.extend(&chars[i..e]);
                    i = e;
                }
                None => {
                    cur.extend(&chars[i..i + n]);
                    i += n;
                }
            }
            continue;
        }
        if c == '|' {
            cells.push(std::mem::take(&mut cur));
            i += 1;
            continue;
        }
        cur.push(c);
        i += 1;
    }
    if !cur.trim().is_empty() || !t.trim_end().ends_with('|') {
        cells.push(cur);
    }
    (lead, cells, trail)
}

fn parse_align(cell: &str) -> Align {
    let c = cell.trim();
    let l = c.starts_with(':');
    let r = c.ends_with(':') && c.len() > 1;
    match (l, r) {
        (true, true) => Align::Center,
        (true, false) => Align::Left,
        (false, true) => Align::Right,
        _ => Align::None,
    }
}

pub fn format_pipe_table(lines: &[String], widths: TableWidths, compact: bool) -> Option<Vec<String>> {
    format_pipe_table_c(lines, widths, compact, None)
}

pub fn format_pipe_table_c(lines: &[String], widths: TableWidths, compact: bool, canon: Option<&crate::options::TemplateDelims>) -> Option<Vec<String>> {
    // Tables holding non-ASCII spaces are kept as written.
    if lines.len() < 2 || lines.iter().any(|l| l.chars().any(|c| c.is_whitespace() && !c.is_ascii())) {
        return None;
    }
    let header = split_row(&lines[0]);
    let delim = split_row(&lines[1]);
    if header.len() != delim.len() {
        return None;
    }
    let aligns: Vec<Align> = delim.iter().map(|d| parse_align(d)).collect();
    let ncols = header.len();
    let mut rows: Vec<Vec<String>> = vec![header];
    for l in &lines[2..] {
        let r = split_row(l);
        if r.len() != ncols {
            return None;
        }
        rows.push(r);
    }
    if let Some(t) = canon {
        for r in rows.iter_mut() {
            for c in r.iter_mut() {
                *c = super::inline::canonicalize(c, t);
            }
        }
    }
    if widths == TableWidths::Preserve {
        return format_preserve(lines, &rows, &aligns);
    }
    if compact {
        let mut out = Vec::new();
        for (ri, r) in rows.iter().enumerate() {
            out.push(format!("| {} |", r.join(" | ")));
            if ri == 0 {
                let seps: Vec<String> = aligns
                    .iter()
                    .map(|a| match a {
                        Align::None => "---".to_string(),
                        Align::Left => ":---".to_string(),
                        Align::Right => "---:".to_string(),
                        Align::Center => ":---:".to_string(),
                    })
                    .collect();
                out.push(format!("| {} |", seps.join(" | ")));
            }
        }
        return Some(out);
    }
    let mut w = vec![0usize; ncols];
    for (c, a) in aligns.iter().enumerate() {
        w[c] = match a {
            Align::None => 3,
            Align::Left | Align::Right => 4,
            Align::Center => 5,
        };
    }
    for r in &rows {
        for (c, cell) in r.iter().enumerate() {
            w[c] = w[c].max(width(cell));
        }
    }
    let mut out = Vec::new();
    for (ri, r) in rows.iter().enumerate() {
        let cells: Vec<String> = r.iter().enumerate().map(|(c, cell)| pad_cell(cell, w[c], aligns[c], ri == 0)).collect();
        out.push(format!("| {} |", cells.join(" | ")));
        if ri == 0 {
            let seps: Vec<String> = aligns
                .iter()
                .enumerate()
                .map(|(c, a)| match a {
                    Align::None => "-".repeat(w[c]),
                    Align::Left => format!(":{}", "-".repeat(w[c] - 1)),
                    Align::Right => format!("{}:", "-".repeat(w[c] - 1)),
                    Align::Center => format!(":{}:", "-".repeat(w[c] - 2)),
                })
                .collect();
            out.push(format!("| {} |", seps.join(" | ")));
        }
    }
    Some(out)
}

fn pad_cell(cell: &str, w: usize, a: Align, _header: bool) -> String {
    let cw = width(cell);
    let extra = w.saturating_sub(cw);
    match a {
        Align::Right => format!("{}{}", " ".repeat(extra), cell),
        Align::Center => {
            let l = extra / 2;
            format!("{}{}{}", " ".repeat(l), cell, " ".repeat(extra - l))
        }
        _ => format!("{}{}", cell, " ".repeat(extra)),
    }
}

/// Preserved widths: each cell keeps its written width and is realigned in it.
fn format_preserve(lines: &[String], _rows: &[Vec<String>], aligns: &[Align]) -> Option<Vec<String>> {
    let mut out = Vec::new();
    for (li, l) in lines.iter().enumerate() {
        if li == 1 {
            out.push(l.trim_end().to_string());
            continue;
        }
        let (lead, segs, trail) = split_row_raw(l);
        let cells: Vec<String> = segs
            .iter()
            .enumerate()
            .map(|(k, seg)| {
                let content = collapse_ws(seg.trim());
                let cw = width(&content);
                let inner = width(seg).saturating_sub(2).max(cw);
                let pad = inner - cw;
                let (left, right) = match aligns.get(k).copied().unwrap_or(Align::None) {
                    Align::Right => (pad, 0),
                    Align::Center => (pad / 2, pad - pad / 2),
                    _ => (0, pad),
                };
                format!(" {}{}{} ", " ".repeat(left), content, " ".repeat(right))
            })
            .collect();
        let mut line = String::new();
        if lead {
            line.push('|');
        }
        line.push_str(&cells.join("|"));
        if trail {
            line.push('|');
        }
        out.push(line);
    }
    Some(out)
}

/// Pandoc grid tables: refit column widths to their contents.
pub fn format_grid_table(lines: &[String], widths: TableWidths) -> Option<Vec<String>> {
    if widths == TableWidths::Preserve {
        return None;
    }
    let first = lines.first()?.trim_end();
    if !first.starts_with('+') || !first.ends_with('+') {
        return None;
    }
    let ncols = first.matches('+').count() - 1;
    if ncols == 0 {
        return None;
    }
    enum Row {
        Sep(char, Vec<(bool, bool)>),
        Content(Vec<String>),
    }
    let mut rows = Vec::new();
    for l in lines {
        let t = l.trim_end();
        if t.starts_with('+') {
            if !t.ends_with('+') {
                return None;
            }
            let segs: Vec<&str> = t[1..t.len() - 1].split('+').collect();
            if segs.len() != ncols {
                return None;
            }
            let mut fill = '-';
            let mut colons = Vec::new();
            for seg in segs {
                let left = seg.starts_with(':');
                let right = seg.ends_with(':') && seg.len() > 1;
                let inner = seg.trim_matches(':');
                if inner.is_empty() || !(inner.chars().all(|x| x == '-') || inner.chars().all(|x| x == '=')) {
                    return None;
                }
                if inner.starts_with('=') {
                    fill = '=';
                }
                colons.push((left, right));
            }
            rows.push(Row::Sep(fill, colons));
        } else if t.starts_with('|') {
            if !t.ends_with('|') {
                return None;
            }
            let cells = split_row(t);
            if cells.len() != ncols {
                return None;
            }
            rows.push(Row::Content(cells));
        } else {
            return None;
        }
    }
    let mut w = vec![0usize; ncols];
    for r in &rows {
        if let Row::Content(cells) = r {
            for (c, cell) in cells.iter().enumerate() {
                w[c] = w[c].max(width(cell));
            }
        }
    }
    let mut out = Vec::new();
    for r in &rows {
        match r {
            Row::Sep(fill, colons) => {
                let mut line = String::from("+");
                for c in 0..ncols {
                    let n = w[c] + 2;
                    let (l, rr) = colons[c];
                    let mut seg: Vec<char> = std::iter::repeat(*fill).take(n).collect();
                    if l {
                        seg[0] = ':';
                    }
                    if rr {
                        seg[n - 1] = ':';
                    }
                    line.extend(seg);
                    line.push('+');
                }
                out.push(line);
            }
            Row::Content(cells) => {
                let mut line = String::from("|");
                for c in 0..ncols {
                    let pad = w[c] - width(&cells[c]);
                    line.push(' ');
                    line.push_str(&cells[c]);
                    line.push_str(&" ".repeat(pad + 1));
                    line.push('|');
                }
                out.push(line);
            }
        }
    }
    Some(out)
}
