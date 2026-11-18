// Inline scanning: split paragraph text into unbreakable wrapping units.

use crate::options::TemplateDelims;

#[derive(Debug, Clone, PartialEq)]
pub enum UnitKind {
    Text,
    /// A forced line break (rendered as the unit text, then a newline).
    HardBreak,
}

#[derive(Debug, Clone)]
pub struct Unit {
    pub text: String,
    pub kind: UnitKind,
    /// Byte ranges (within `text`) of a splittable link destination: (prefix_end, dest_end).
    pub link_split: Vec<(usize, usize)>,
    /// Whether the unit came from a single atom that contained a newline.
    pub multiline: bool,
}

impl Unit {
    pub fn text(s: String) -> Self {
        Unit { text: s, kind: UnitKind::Text, link_split: Vec::new(), multiline: false }
    }
}

pub struct Scanned {
    pub units: Vec<Unit>,
    /// Paragraph contains constructs we must not rewrap.
    pub unsupported: bool,
    /// Only raw HTML (comments, declarations) is unsupported; enclosing
    /// lists are still formatted.
    pub html_only: bool,
}

fn is_ws(c: char) -> bool {
    c == ' ' || c == '\t' || c == '\n'
}

/// Find the end of a code span starting at `i` (a backtick run). Returns index after closing run.
fn code_span_end(chars: &[char], i: usize) -> Option<usize> {
    let mut n = 0;
    while i + n < chars.len() && chars[i + n] == '`' {
        n += 1;
    }
    let mut j = i + n;
    while j < chars.len() {
        if chars[j] == '`' {
            let mut m = 0;
            while j + m < chars.len() && chars[j + m] == '`' {
                m += 1;
            }
            if m == n {
                return Some(j + m);
            }
            j += m;
        } else {
            j += 1;
        }
    }
    None
}

fn backtick_run(chars: &[char], i: usize) -> usize {
    let mut n = 0;
    while i + n < chars.len() && chars[i + n] == '`' {
        n += 1;
    }
    n
}

/// Find matching close bracket for '[' at i, honoring nesting, escapes and code spans.
fn bracket_end(chars: &[char], i: usize) -> Option<usize> {
    let mut depth = 0;
    let mut j = i;
    while j < chars.len() {
        let c = chars[j];
        if c == '\\' {
            j += 2;
            continue;
        }
        if c == '`' {
            match code_span_end(chars, j) {
                Some(e) => {
                    j = e;
                    continue;
                }
                None => {
                    j += backtick_run(chars, j);
                    continue;
                }
            }
        }
        if c == '[' {
            depth += 1;
        } else if c == ']' {
            depth -= 1;
            if depth == 0 {
                return Some(j);
            }
        }
        j += 1;
    }
    None
}

/// Find the closing ')' for a link destination starting after '(' at i.
fn paren_end(chars: &[char], i: usize) -> Option<usize> {
    let mut depth = 0;
    let mut j = i;
    let mut in_angle = false;
    while j < chars.len() {
        let c = chars[j];
        if c == '\\' {
            j += 2;
            continue;
        }
        if c == '<' && j == i + 1 {
            in_angle = true;
        } else if c == '>' && in_angle {
            in_angle = false;
        } else if !in_angle {
            if c == '"' || c == '\'' {
                // title string
                let q = c;
                let mut k = j + 1;
                while k < chars.len() && chars[k] != q {
                    if chars[k] == '\\' {
                        k += 1;
                    }
                    k += 1;
                }
                j = k + 1;
                continue;
            }
            if c == '(' {
                depth += 1;
            } else if c == ')' {
                depth -= 1;
                if depth == 0 {
                    return Some(j);
                }
            }
        }
        j += 1;
    }
    None
}

fn brace_end(chars: &[char], i: usize) -> Option<usize> {
    let mut j = i;
    while j < chars.len() {
        if chars[j] == '}' {
            return Some(j);
        }
        if chars[j] == '\n' && false {
            return None;
        }
        j += 1;
    }
    None
}

fn is_tag_name_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '-'
}

/// Parse an HTML open/close tag at i ('<'). Returns (end index after '>', tag name, is_close, self_closing).
pub fn html_tag_at(chars: &[char], i: usize) -> Option<(usize, String, bool, bool)> {
    if i >= chars.len() || chars[i] != '<' {
        return None;
    }
    let mut j = i + 1;
    let mut close = false;
    if j < chars.len() && chars[j] == '/' {
        close = true;
        j += 1;
    }
    if j >= chars.len() || !chars[j].is_ascii_alphabetic() {
        return None;
    }
    let ns = j;
    while j < chars.len() && is_tag_name_char(chars[j]) {
        j += 1;
    }
    let name: String = chars[ns..j].iter().collect::<String>().to_ascii_lowercase();
    if close {
        while j < chars.len() && is_ws(chars[j]) {
            j += 1;
        }
        if j < chars.len() && chars[j] == '>' {
            return Some((j + 1, name, true, false));
        }
        return None;
    }
    // attributes
    loop {
        let save = j;
        while j < chars.len() && is_ws(chars[j]) {
            j += 1;
        }
        if j >= chars.len() {
            return None;
        }
        if chars[j] == '>' {
            return Some((j + 1, name, false, false));
        }
        if chars[j] == '/' && j + 1 < chars.len() && chars[j + 1] == '>' {
            return Some((j + 2, name, false, true));
        }
        if j == save {
            return None;
        }
        // attribute name
        if !(chars[j].is_ascii_alphabetic() || chars[j] == '_' || chars[j] == ':') {
            return None;
        }
        while j < chars.len() && (chars[j].is_ascii_alphanumeric() || matches!(chars[j], '_' | '.' | ':' | '-')) {
            j += 1;
        }
        let save2 = j;
        while j < chars.len() && is_ws(chars[j]) {
            j += 1;
        }
        if j < chars.len() && chars[j] == '=' {
            j += 1;
            while j < chars.len() && is_ws(chars[j]) {
                j += 1;
            }
            if j >= chars.len() {
                return None;
            }
            let q = chars[j];
            if q == '"' || q == '\'' {
                j += 1;
                while j < chars.len() && chars[j] != q {
                    j += 1;
                }
                if j >= chars.len() {
                    return None;
                }
                j += 1;
            } else {
                let vs = j;
                while j < chars.len() && !is_ws(chars[j]) && !matches!(chars[j], '"' | '\'' | '=' | '<' | '>' | '`') {
                    j += 1;
                }
                if j == vs {
                    return None;
                }
            }
        } else {
            j = save2;
        }
    }
}

const VOID_TAGS: &[&str] = &[
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr",
];

/// Find the matching close tag for an element opened at `start` (after the open tag).
fn html_element_end(chars: &[char], start: usize, name: &str) -> Option<usize> {
    let mut depth = 1;
    let mut j = start;
    while j < chars.len() {
        if chars[j] == '<' {
            if let Some((e, n, close, selfc)) = html_tag_at(chars, j) {
                if n == name {
                    if close {
                        depth -= 1;
                        if depth == 0 {
                            return Some(e);
                        }
                    } else if !selfc {
                        depth += 1;
                    }
                }
                j = e;
                continue;
            }
        }
        j += 1;
    }
    None
}

/// Autolink `<scheme:...>` or `<email@host>`.
fn autolink_end(chars: &[char], i: usize) -> Option<usize> {
    let mut j = i + 1;
    let s = j;
    while j < chars.len() && chars[j] != '>' && !is_ws(chars[j]) && chars[j] != '<' {
        j += 1;
    }
    if j >= chars.len() || chars[j] != '>' {
        return None;
    }
    let inner: String = chars[s..j].iter().collect();
    if let Some(p) = inner.find(':') {
        let scheme = &inner[..p];
        if scheme.len() >= 2 && scheme.len() <= 32 && scheme.chars().next().unwrap().is_ascii_alphabetic()
            && scheme.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '+' | '.' | '-'))
        {
            return Some(j + 1);
        }
    }
    if inner.contains('@') && !inner.starts_with('@') {
        return Some(j + 1);
    }
    None
}

/// Find the closing delimiter run for emphasis opened with `delim` repeated `n` times at i.
fn emphasis_end(chars: &[char], i: usize, delim: char, n: usize) -> Option<usize> {
    // Opening must be left-flanking: next char not whitespace.
    let after = i + n;
    if after >= chars.len() || is_ws(chars[after]) {
        return None;
    }
    if delim == '_' && i > 0 && chars[i - 1].is_alphanumeric() {
        return None;
    }
    let mut j = after;
    while j < chars.len() {
        let c = chars[j];
        if c == '\\' {
            j += 2;
            continue;
        }
        if c == '`' {
            match code_span_end(chars, j) {
                Some(e) => {
                    j = e;
                    continue;
                }
                None => {
                    j += backtick_run(chars, j);
                    continue;
                }
            }
        }
        if c == delim {
            let mut m = 0;
            while j + m < chars.len() && chars[j + m] == delim {
                m += 1;
            }
            // Closing must be right-flanking: previous char not whitespace.
            if m >= n && j > after && !is_ws(chars[j - 1]) {
                if delim == '_' && j + m < chars.len() && chars[j + m].is_alphanumeric() {
                    j += m;
                    continue;
                }
                if m == n || (m > n && n == 1) || m >= n {
                    return Some(j + n.min(m).max(n));
                }
            }
            j += m;
            continue;
        }
        j += 1;
    }
    None
}

fn template_end(chars: &[char], i: usize, delims: &TemplateDelims) -> Option<usize> {
    for (open, close) in &delims.pairs {
        let oc: Vec<char> = open.chars().collect();
        if i + oc.len() <= chars.len() && chars[i..i + oc.len()] == oc[..] {
            let cc: Vec<char> = close.chars().collect();
            let mut j = i + oc.len();
            let mut quote: Option<char> = None;
            let is_comment = open == "{#";
            while j < chars.len() {
                let c = chars[j];
                if c == '\n' {
                    return None;
                }
                if !is_comment {
                    if let Some(q) = quote {
                        if c == '\\' {
                            j += 2;
                            continue;
                        }
                        if c == q {
                            quote = None;
                        }
                        j += 1;
                        continue;
                    }
                    if c == '"' || c == '\'' {
                        quote = Some(c);
                        j += 1;
                        continue;
                    }
                }
                if j + cc.len() <= chars.len() && chars[j..j + cc.len()] == cc[..] {
                    return Some(j + cc.len());
                }
                j += 1;
            }
            return None;
        }
    }
    None
}

/// Math span `$...$` or `$$...$$` starting at i.
fn math_end(chars: &[char], i: usize) -> Option<usize> {
    if i + 1 < chars.len() && chars[i + 1] == '$' {
        let mut j = i + 2;
        while j + 1 < chars.len() {
            if chars[j] == '\\' {
                j += 2;
                continue;
            }
            if chars[j] == '$' && chars[j + 1] == '$' {
                return Some(j + 2);
            }
            j += 1;
        }
        return None;
    }
    // Inline math runs to the next unescaped dollar sign.
    let mut j = i + 1;
    while j < chars.len() {
        if chars[j] == '\\' {
            j += 2;
            continue;
        }
        if chars[j] == '$' {
            return Some(j + 1);
        }
        j += 1;
    }
    None
}

/// End of the group closed by `close` that opens at `i` (nesting aware).
fn group_end(chars: &[char], i: usize, open: char, close: char) -> Option<usize> {
    let mut depth = 0;
    let mut j = i;
    while j < chars.len() {
        if chars[j] == '\\' {
            j += 2;
            continue;
        }
        if chars[j] == open {
            depth += 1;
        } else if chars[j] == close {
            depth -= 1;
            if depth == 0 {
                return Some(j + 1);
            }
        }
        j += 1;
    }
    None
}

/// Whether prose outside code, math, links, braces and HTML holds a raw TeX
/// command (a backslash before letters) that is not followed by a brace group,
/// or opens TeX display math.
fn has_text_tex_command(chars: &[char]) -> bool {
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        let skip = match c {
            '\\' => {
                // `\[` opens TeX display math.
                if chars.get(i + 1) == Some(&'[') {
                    return true;
                }
                let mut j = i + 1;
                while chars.get(j).is_some_and(|c| c.is_alphabetic()) {
                    j += 1;
                }
                if j > i + 1 && chars.get(j) != Some(&'{') {
                    return true;
                }
                Some(j.max(i + 2))
            }
            '`' => Some(code_span_end(chars, i).unwrap_or(i + backtick_run(chars, i))),
            '$' => math_end(chars, i),
            '[' => bracket_end(chars, i).map(|e| match chars.get(e + 1) {
                Some('(') => group_end(chars, e + 1, '(', ')').unwrap_or(e + 1),
                Some('[') => bracket_end(chars, e + 1).map_or(e + 1, |f| f + 1),
                _ => e + 1,
            }),
            '{' => group_end(chars, i, '{', '}'),
            '<' => autolink_end(chars, i).or_else(|| {
                html_tag_at(chars, i).map(|(e, name, close, selfc)| {
                    if close || selfc || VOID_TAGS.contains(&name.as_str()) {
                        e
                    } else {
                        html_element_end(chars, e, &name).unwrap_or(e)
                    }
                })
            }),
            _ => None,
        };
        i = skip.unwrap_or(i + 1);
    }
    false
}

fn count_dollars(chars: &[char]) -> usize {
    let mut n = 0;
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c == '\\' {
            i += 2;
            continue;
        }
        if c == '`' {
            match code_span_end(chars, i) {
                Some(e) => {
                    i = e;
                    continue;
                }
                None => {
                    i += backtick_run(chars, i);
                    continue;
                }
            }
        }
        // Link destinations and reference labels, autolinks and HTML tags.
        if c == ']' && i + 1 < chars.len() && (chars[i + 1] == '(' || chars[i + 1] == '[') {
            let (open, close) = if chars[i + 1] == '(' { ('(', ')') } else { ('[', ']') };
            let mut depth = 0;
            let mut j = i + 1;
            while j < chars.len() {
                if chars[j] == '\\' {
                    j += 2;
                    continue;
                }
                if chars[j] == open {
                    depth += 1;
                } else if chars[j] == close {
                    depth -= 1;
                    if depth == 0 {
                        break;
                    }
                }
                j += 1;
            }
            if j < chars.len() {
                i = j + 1;
                continue;
            }
        }
        if c == '<' {
            if let Some(e) = autolink_end(chars, i).or_else(|| html_tag_at(chars, i).map(|t| t.0)) {
                i = e;
                continue;
            }
        }
        if c == '$' {
            n += 1;
        }
        i += 1;
    }
    n
}

/// Collapse whitespace runs (including newlines) to single spaces.
pub fn collapse_ws(s: &str) -> String {
    let mut out = String::new();
    let mut prev_ws = false;
    for c in s.chars() {
        if is_ws(c) {
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

pub fn scan(text: &str, templates: &TemplateDelims) -> Scanned {
    scan_opts(text, templates, true)
}

pub fn scan_opts(text: &str, templates: &TemplateDelims, unescape: bool) -> Scanned {
    let chars: Vec<char> = text.chars().collect();
    let mut units: Vec<Unit> = Vec::new();
    let mut cur = String::new();
    let mut cur_multi = false;
    let mut cur_split: Vec<(usize, usize)> = Vec::new();
    let mut cur_has_link = 0;
    let mut unsupported = false;
    let mut html_unsupported = false;
    // Odd dollar signs and inline TeX environments and commands are left as written.
    if count_dollars(&chars) % 2 == 1 || text.contains("\\begin{") || has_text_tex_command(&chars) {
        unsupported = true;
    }
    let n = chars.len();
    let mut i = 0;
    let push_cur = |units: &mut Vec<Unit>, cur: &mut String, multi: &mut bool, split: &mut Vec<(usize, usize)>, links: &mut usize| {
        if !cur.is_empty() {
            let mut u = Unit::text(std::mem::take(cur));
            u.multiline = *multi;
            u.link_split = if *links == 1 { std::mem::take(split) } else { Vec::new() };
            units.push(u);
        }
        *multi = false;
        split.clear();
        *links = 0;
    };
    while i < n {
        let c = chars[i];
        if c == '\n' {
            // Hard break detection: trailing two spaces or backslash before newline.
            let line_before: String = cur.clone();
            let _ = line_before;
            // Check spaces before the newline in source.
            let mut k = i;
            let mut spaces = 0;
            while k > 0 && chars[k - 1] == ' ' {
                spaces += 1;
                k -= 1;
            }
            if cur.ends_with('\\') && spaces == 0 && !cur.ends_with("\\\\") {
                push_cur(&mut units, &mut cur, &mut cur_multi, &mut cur_split, &mut cur_has_link);
                if let Some(last) = units.last_mut() {
                    last.kind = UnitKind::HardBreak;
                }
            } else if spaces >= 2 {
                push_cur(&mut units, &mut cur, &mut cur_multi, &mut cur_split, &mut cur_has_link);
                units.push(Unit { text: "\\".into(), kind: UnitKind::HardBreak, link_split: Vec::new(), multiline: false });
            } else {
                push_cur(&mut units, &mut cur, &mut cur_multi, &mut cur_split, &mut cur_has_link);
            }
            i += 1;
            continue;
        }
        if c == ' ' || c == '\t' {
            push_cur(&mut units, &mut cur, &mut cur_multi, &mut cur_split, &mut cur_has_link);
            i += 1;
            continue;
        }
        if c == '\\' && i + 1 < n {
            if chars[i + 1] == '\n' {
                cur.push('\\');
                i += 1;
                continue;
            }
            cur.push(c);
            cur.push(chars[i + 1]);
            i += 2;
            continue;
        }
        // Templates.
        if c == '{' || c == '<' {
            if let Some(e) = template_end(&chars, i, templates) {
                cur.extend(&chars[i..e]);
                i = e;
                continue;
            }
        }
        // A brace group on one line starting a word is unbreakable.
        if c == '{' && cur.is_empty() {
            if let Some(e) = group_end(&chars, i, '{', '}').filter(|&e| !chars[i..e].contains(&'\n')) {
                cur.extend(&chars[i..e]);
                i = e;
                continue;
            }
        }
        if c == '`' {
            match code_span_end(&chars, i) {
                Some(e) => {
                    let s: String = chars[i..e].iter().collect();
                    if s.contains('\n') {
                        cur_multi = true;
                    }
                    cur.push_str(&s);
                    i = e;
                    continue;
                }
                None => {
                    unsupported = true;
                    let r = backtick_run(&chars, i);
                    cur.extend(&chars[i..i + r]);
                    i += r;
                    continue;
                }
            }
        }
        if c == '$' {
            if let Some(e) = math_end(&chars, i) {
                let s: String = chars[i..e].iter().collect();
                if s.contains('\n') {
                    cur_multi = true;
                }
                // Display math inside prose with a bare TeX command is left as written.
                if s.starts_with("$$") && has_bare_tex_command(&s) {
                    unsupported = true;
                }
                cur.push_str(&s);
                i = e;
                continue;
            }
            if i + 1 < n && chars[i + 1] == '$' {
                unsupported = true;
                cur.push_str("$$");
                i += 2;
                continue;
            }
            cur.push('$');
            i += 1;
            continue;
        }
        if c == '<' {
            if i + 3 < n && chars[i + 1] == '!' && chars[i + 2] == '-' && chars[i + 3] == '-' {
                html_unsupported = true;
                cur.push(c);
                i += 1;
                continue;
            }
            if i + 1 < n && (chars[i + 1] == '?' || chars[i + 1] == '!') {
                html_unsupported = true;
                cur.push(c);
                i += 1;
                continue;
            }
            if let Some(e) = autolink_end(&chars, i) {
                cur.extend(&chars[i..e]);
                i = e;
                continue;
            }
            if let Some((e, name, close, selfc)) = html_tag_at(&chars, i) {
                if !close && !selfc && !VOID_TAGS.contains(&name.as_str()) {
                    if let Some(end) = html_element_end(&chars, e, &name) {
                        let s: String = chars[i..end].iter().collect();
                        cur.push_str(&s);
                        i = end;
                        continue;
                    }
                }
                let s: String = chars[i..e].iter().collect();
                cur.push_str(&s);
                i = e;
                continue;
            }
            cur.push(c);
            i += 1;
            continue;
        }
        if c == '!' && i + 1 < n && chars[i + 1] == '[' {
            if let Some((e, split)) = scan_link(&chars, i + 1) {
                let s: String = chars[i..e].iter().collect();
                if has_template(&chars[i..e], templates) || angle_dest_has_space(&s) {
                    unsupported = true;
                }
                let s = normalize_link_attrs(&s);
                let multi = s.contains('\n');
                let s = if multi { collapse_link_text(&s) } else { s };
                if !split.is_empty() && cur.is_empty() {
                    push_split_link(&chars, i, e, &split, multi, &mut cur, &mut cur_split);
                } else {
                    cur.push_str(&s);
                }
                cur_has_link += 1;
                i = e;
                continue;
            }
        }
        if c == '^' && i + 1 < n && chars[i + 1] == '[' {
            if let Some(e) = bracket_end(&chars, i + 1) {
                let s: String = chars[i..=e].iter().collect();
                let s = if s.contains('\n') { collapse_ws(&s) } else { s };
                cur.push_str(&s);
                i = e + 1;
                continue;
            }
        }
        if c == '[' {
            if let Some((e, split)) = scan_link(&chars, i) {
                let s: String = chars[i..e].iter().collect();
                if has_template(&chars[i..e], templates) || angle_dest_has_space(&s) {
                    unsupported = true;
                }
                let s = normalize_link_attrs(&s);
                let multi = s.contains('\n');
                if !split.is_empty() && cur.is_empty() {
                    push_split_link(&chars, i, e, &split, multi, &mut cur, &mut cur_split);
                } else {
                    let s = if multi { collapse_link_text(&s) } else { s };
                    cur.push_str(&s);
                }
                cur_has_link += 1;
                i = e;
                continue;
            }
            unsupported = true;
            cur.push(c);
            i += 1;
            continue;
        }
        if c == '*' || c == '_' {
            let mut r = 0;
            while i + r < n && chars[i + r] == c {
                r += 1;
            }
            let try_n = r.min(3);
            // Emphasis is an unbreakable unit only when it starts a word.
            let at_start = cur.is_empty();
            if let Some(e) = if at_start { emphasis_end(&chars, i, c, try_n) } else { None } {
                let s: String = chars[i..e].iter().collect();
                if has_template(&chars[i..e], templates) {
                    unsupported = true;
                }
                let s = if s.contains('\n') { collapse_ws(&s) } else { s };
                cur.push_str(&s);
                i = e;
                continue;
            }
            cur.extend(&chars[i..i + r]);
            i += r;
            continue;
        }
        if c == '~' && i + 1 < n && chars[i + 1] == '~' && cur.is_empty() {
            // Strikethrough.
            let mut j = i + 2;
            let mut found = None;
            while j + 1 < n {
                if chars[j] == '~' && chars[j + 1] == '~' {
                    found = Some(j + 2);
                    break;
                }
                j += 1;
            }
            match found {
                Some(e) => {
                    let s: String = chars[i..e].iter().collect();
                    let s = if s.contains('\n') { collapse_ws(&s) } else { s };
                    cur.push_str(&s);
                    i = e;
                }
                None => {
                    unsupported = true;
                    cur.push_str("~~");
                    i += 2;
                }
            }
            continue;
        }
        // Text holding a non-ASCII space (no-break, thin, ideographic...) is left
        // as written.
        if c.is_whitespace() && !c.is_ascii() {
            unsupported = true;
        }
        cur.push(c);
        i += 1;
    }
    push_cur(&mut units, &mut cur, &mut cur_multi, &mut cur_split, &mut cur_has_link);
    // Escaped block markers standing alone are re-derived when wrapping; the
    // first one and those after a hard break always start a line and stay as
    // written.
    for k in 1..units.len() {
        if unescape && units[k].kind == UnitKind::Text && units[k - 1].kind != UnitKind::HardBreak {
            if let Some(t) = unescape_marker(&units[k].text) {
                // An escaped `*` stays escaped while a later `*` could pair with it.
                if t == "*" && units[k + 1..].iter().any(|u| strip_code_spans(&u.text).contains('*')) {
                    continue;
                }
                units[k].text = t;
            }
        }
    }
    Scanned { units, unsupported: unsupported || html_unsupported, html_only: html_unsupported && !unsupported }
}

/// Whether TeX holds a control word not followed by a brace argument (`\le b`).
pub fn has_bare_tex_command(t: &str) -> bool {
    let c: Vec<char> = t.chars().collect();
    let mut i = 0;
    while i < c.len() {
        if c[i] == '\\' {
            let mut j = i + 1;
            while j < c.len() && c[j].is_ascii_alphabetic() {
                j += 1;
            }
            if j > i + 1 && c.get(j) != Some(&'{') {
                return true;
            }
            i = j.max(i + 2);
            continue;
        }
        i += 1;
    }
    false
}

/// Whether a link's `<...>` destination contains whitespace.
fn angle_dest_has_space(link: &str) -> bool {
    match link.find("](<") {
        Some(p) => {
            let rest = &link[p + 3..];
            let end = rest.find('>').unwrap_or(rest.len());
            rest[..end].contains([' ', '\t'])
        }
        None => false,
    }
}

/// Text with backtick code spans removed.
fn strip_code_spans(s: &str) -> String {
    let chars: Vec<char> = s.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < chars.len() {
        if chars[i] == '`' {
            if let Some(e) = code_span_end(&chars, i) {
                i = e;
                continue;
            }
        }
        out.push(chars[i]);
        i += 1;
    }
    out
}

/// `\*`, `\#`, `1\.` and similar escaped markers map back to the bare marker.
fn unescape_marker(tok: &str) -> Option<String> {
    if !tok.contains('\\') || tok.matches('\\').count() != 1 {
        return None;
    }
    let bare = tok.replacen('\\', "", 1);
    if super::wrap::escape_token(&bare).as_deref() == Some(tok) {
        return Some(bare);
    }
    None
}

fn has_template(chars: &[char], templates: &TemplateDelims) -> bool {
    let s: String = chars.iter().collect();
    for (open, _) in &templates.pairs {
        if s.contains(open.as_str()) {
            let cs: Vec<char> = s.chars().collect();
            for k in 0..cs.len() {
                if template_end(&cs, k, templates).is_some() {
                    return true;
                }
            }
        }
    }
    false
}

/// Normalize whitespace inside a trailing `{...}` attribute block of a link or span.
fn normalize_link_attrs(s: &str) -> String {
    if !s.ends_with('}') {
        return s.to_string();
    }
    // Find the attribute block following the closing ')' or ']'.
    let bytes = s.as_bytes();
    let mut depth = 0;
    let mut open = None;
    for k in (0..bytes.len()).rev() {
        if bytes[k] == b'}' {
            depth += 1;
        } else if bytes[k] == b'{' {
            depth -= 1;
            if depth == 0 {
                open = Some(k);
                break;
            }
        }
    }
    let o = match open {
        Some(o) => o,
        None => return s.to_string(),
    };
    if o == 0 || !(bytes[o - 1] == b')' || bytes[o - 1] == b']') {
        return s.to_string();
    }
    let inner = &s[o + 1..s.len() - 1];
    let norm = collapse_ws(inner.trim());
    format!("{}{{{}}}", &s[..o], norm)
}

/// Normalize an attribute block in the tail of a link (text after its destination).
fn normalize_attr_tail(rest: &str) -> String {
    match rest.find('{') {
        Some(p) if rest.ends_with('}') => {
            let inner = &rest[p + 1..rest.len() - 1];
            format!("{}{{{}}}", &rest[..p], collapse_ws(inner.trim()))
        }
        _ => rest.to_string(),
    }
}

fn collapse_link_text(s: &str) -> String {
    collapse_ws(s)
}

/// Scan a link/span starting with '[' at i. Returns (end, split range of destination).
/// Append a link whose destinations may be split, recording dest byte ranges.
fn push_split_link(chars: &[char], i: usize, e: usize, split: &[(usize, usize)], multi: bool, cur: &mut String, cur_split: &mut Vec<(usize, usize)>) {
    let mut pos = i;
    for &(a, b) in split {
        let pre: String = chars[pos..a].iter().collect();
        let pre = if multi { collapse_ws(&pre) } else { pre };
        cur.push_str(&pre);
        let ds = cur.len();
        let dest: String = chars[a..b].iter().collect();
        let dest = if a > 0 && chars[a - 1] == '{' { collapse_ws(dest.trim()) } else { dest };
        cur.push_str(&dest);
        cur_split.push((ds, cur.len()));
        pos = b;
    }
    let rest: String = chars[pos..e].iter().collect();
    cur.push_str(&normalize_attr_tail(&rest));
}

fn scan_link(chars: &[char], i: usize) -> Option<(usize, Vec<(usize, usize)>)> {
    let close = bracket_end(chars, i)?;
    let mut e = close + 1;
    let mut split = Vec::new();
    // A nested image splits at its own destination first.
    if i + 2 < close && chars[i + 1] == '!' && chars[i + 2] == '[' && close + 1 < chars.len() && chars[close + 1] == '(' {
        if let Some((ie, isplit)) = scan_link(chars, i + 2) {
            if ie == close && !isplit.is_empty() {
                split = isplit;
            }
        }
    }
    if e < chars.len() && chars[e] == '(' {
        let pe = paren_end(chars, e)?;
        // Destination without title is splittable.
        let inner: String = chars[e + 1..pe].iter().collect();
        let inner_t = inner.trim();
        if !valid_dest_and_title(inner_t) {
            return None;
        }
        if !inner_t.is_empty() && !inner_t.contains(char::is_whitespace) {
            split.push((e + 1, pe));
        }
        e = pe + 1;
    } else if e < chars.len() && chars[e] == '[' {
        let be = bracket_end(chars, e)?;
        e = be + 1;
    } else if close == i + 1 {
        // Empty brackets alone are not a link.
        return None;
    }
    if e < chars.len() && chars[e] == '{' {
        if let Some(be) = brace_end(chars, e) {
            // Images with attributes split inside the attribute block.
            if i > 0 && chars[i - 1] == '!' && be > e + 1 {
                split = vec![(e + 1, be)];
            }
            e = be + 1;
        }
    }
    Some((e, split))
}

/// Whether the text inside a link's parentheses is a destination with an optional
/// quoted or parenthesized title.
fn valid_dest_and_title(t: &str) -> bool {
    let rest = if let Some(r) = t.strip_prefix('<') {
        match r.find('>') {
            Some(p) => &r[p + 1..],
            None => return false,
        }
    } else {
        t.find(char::is_whitespace).map_or("", |p| &t[p..])
    };
    let rest = rest.trim();
    rest.is_empty()
        || [('"', '"'), ('\'', '\''), ('(', ')')].iter().any(|&(o, c)| rest.len() >= 2 && rest.starts_with(o) && rest.ends_with(c))
}

/// Tokens that must not begin a wrapped line (they would change block structure).
pub fn dangerous_start(tok: &str) -> bool {
    let t = tok;
    if t.is_empty() {
        return false;
    }
    let c0 = t.chars().next().unwrap();
    if c0 == '>' || c0 == '|' || c0 == ':' {
        return true;
    }
    if t == "~" {
        return true;
    }
    if t.chars().all(|c| c == '#') && t.len() <= 6 {
        return true;
    }
    if t == "-" || t == "+" || t == "*" {
        return true;
    }
    if t.len() >= 2 && t.chars().all(|c| c == '-') {
        return true;
    }
    if t.chars().all(|c| c == '=') {
        return true;
    }
    if t.len() >= 3 && (t.chars().all(|c| c == '*') || t.chars().all(|c| c == '_')) {
        return true;
    }
    // Ordered list markers.
    let body: &str = if let Some(b) = t.strip_suffix('.') {
        b
    } else if let Some(b) = t.strip_suffix(')') {
        if let Some(b2) = b.strip_prefix('(') {
            if super::block::is_list_label(b2, true) {
                return true;
            }
            ""
        } else {
            b
        }
    } else {
        ""
    };
    if !body.is_empty() && super::block::is_list_label(body, false) {
        return true;
    }
    // Reference definitions.
    if c0 == '[' && t.find(']').is_some_and(|p| p > 1 && t[p + 1..].starts_with(':')) {
        return true;
    }
    // HTML tags (a complete element is safe).
    if c0 == '<' {
        let chars: Vec<char> = t.chars().collect();
        if let Some((_, name, close, _)) = html_tag_at(&chars, 0) {
            if !close && t.contains(&format!("</{}>", name)) && !BLOCK_TAG_NAMES.contains(&name.as_str()) {
                return false;
            }
            return true;
        }
    }
    false
}


pub const BLOCK_TAG_NAMES: &[&str] = &[
    "address", "article", "aside", "base", "basefont", "blockquote", "body", "caption", "center", "col", "colgroup", "dd", "details", "dialog", "dir", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "frame", "frameset", "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hr", "html", "iframe", "legend", "li", "link", "main", "menu", "menuitem", "nav", "noframes", "ol", "optgroup", "option", "p", "param", "search", "section", "summary", "table", "tbody", "td", "tfoot", "th", "thead", "title", "tr", "track", "ul", "script", "pre", "style", "textarea",
];

fn is_md_punct(c: char) -> bool {
    c.is_ascii_punctuation() || (!c.is_alphanumeric() && !c.is_whitespace() && c as u32 > 127)
}

/// Rewrite `_`-delimited emphasis as `*` (canonical spelling), using the CommonMark
/// delimiter algorithm. Code spans, math, raw HTML and templates are left alone.
pub fn canonicalize(text: &str, templates: &TemplateDelims) -> String {
    let mut chars: Vec<char> = text.chars().collect();
    let n = chars.len();
    // Protected ranges.
    let mut protected = vec![false; n];
    let mut i = 0;
    while i < n {
        let c = chars[i];
        if c == '\\' {
            i += 2;
            continue;
        }
        let end = if c == '`' {
            code_span_end(&chars, i)
        } else if c == '$' {
            math_end(&chars, i)
        } else if c == '<' {
            autolink_end(&chars, i).or_else(|| html_tag_at(&chars, i).map(|t| t.0))
        } else if c == '{' {
            template_end(&chars, i, templates)
        } else {
            None
        };
        match end {
            Some(e) => {
                for p in protected.iter_mut().take(e).skip(i) {
                    *p = true;
                }
                i = e;
            }
            None => i += 1,
        }
    }
    struct Delim {
        ch: char,
        start: usize,
        len: usize,
        orig_len: usize,
        can_open: bool,
        can_close: bool,
        active: bool,
    }
    let mut delims: Vec<Delim> = Vec::new();
    let mut i = 0;
    while i < n {
        if protected[i] {
            i += 1;
            continue;
        }
        let c = chars[i];
        if c == '\\' {
            i += 2;
            continue;
        }
        if c == '_' || c == '*' {
            let s = i;
            while i < n && chars[i] == c && !protected[i] {
                i += 1;
            }
            let prev = if s == 0 { ' ' } else { chars[s - 1] };
            let next = if i >= n { ' ' } else { chars[i] };
            let lf = !next.is_whitespace() && (!is_md_punct(next) || prev.is_whitespace() || is_md_punct(prev));
            let rf = !prev.is_whitespace() && (!is_md_punct(prev) || next.is_whitespace() || is_md_punct(next));
            let (co, cc) = if c == '_' {
                (lf && (!rf || is_md_punct(prev)), rf && (!lf || is_md_punct(next)))
            } else {
                (lf, rf)
            };
            delims.push(Delim { ch: c, start: s, len: i - s, orig_len: i - s, can_open: co, can_close: cc, active: true });
            continue;
        }
        i += 1;
    }
    // Pairs of (opener char positions, closer char positions) to rewrite.
    let mut rewrite: Vec<usize> = Vec::new();
    let mut ci = 0;
    while ci < delims.len() {
        if !delims[ci].active || !delims[ci].can_close || delims[ci].len == 0 {
            ci += 1;
            continue;
        }
        let mut found = None;
        let mut oi = ci;
        while oi > 0 {
            oi -= 1;
            let o = &delims[oi];
            let c = &delims[ci];
            if !o.active || o.len == 0 || o.ch != c.ch || !o.can_open {
                continue;
            }
            if (o.can_close || c.can_open) && (o.orig_len + c.orig_len) % 3 == 0 && !(o.orig_len % 3 == 0 && c.orig_len % 3 == 0) {
                continue;
            }
            found = Some(oi);
            break;
        }
        match found {
            Some(oi) => {
                let use_n = if delims[oi].len >= 2 && delims[ci].len >= 2 { 2 } else { 1 };
                // Opener: consume from its end; closer: from its start.
                let o_end = delims[oi].start + delims[oi].len;
                let c_start = delims[ci].start;
                if delims[oi].ch == '_' {
                    for k in 0..use_n {
                        rewrite.push(o_end - 1 - k);
                        rewrite.push(c_start + k);
                    }
                }
                delims[oi].len -= use_n;
                delims[ci].len -= use_n;
                delims[ci].start += use_n;
                for d in delims.iter_mut().take(ci).skip(oi + 1) {
                    d.active = false;
                }
                if delims[oi].len == 0 {
                    delims[oi].active = false;
                }
                if delims[ci].len == 0 {
                    ci += 1;
                }
            }
            None => {
                ci += 1;
            }
        }
    }
    for p in rewrite {
        chars[p] = '*';
    }
    chars.into_iter().collect()
}
