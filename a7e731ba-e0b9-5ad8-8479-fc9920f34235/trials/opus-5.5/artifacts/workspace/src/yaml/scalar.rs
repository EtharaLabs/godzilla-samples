// Scalar classification and rendering helpers.

/// Digits with single underscores between digit groups.
fn digits_with_underscores(s: &[u8], is_digit: fn(u8) -> bool) -> bool {
    if s.is_empty() || !is_digit(s[0]) || !is_digit(s[s.len() - 1]) {
        return false;
    }
    let mut prev_us = false;
    for &c in s {
        if c == b'_' {
            if prev_us {
                return false;
            }
            prev_us = true;
        } else if is_digit(c) {
            prev_us = false;
        } else {
            return false;
        }
    }
    true
}

fn is_dec(c: u8) -> bool {
    c.is_ascii_digit()
}
fn is_hex(c: u8) -> bool {
    c.is_ascii_hexdigit()
}
fn is_oct(c: u8) -> bool {
    (b'0'..=b'7').contains(&c)
}
fn is_bin(c: u8) -> bool {
    c == b'0' || c == b'1'
}

/// Whether a plain scalar would be read as a number (YAML 1.2 core plus common 1.1 forms).
pub fn looks_numeric(s: &str) -> bool {
    let b = s.as_bytes();
    if b.is_empty() {
        return false;
    }
    let body = if b[0] == b'-' || b[0] == b'+' { &b[1..] } else { b };
    if body.is_empty() {
        return false;
    }
    // inf / nan
    if matches!(body, b".inf" | b".Inf" | b".INF") {
        return true;
    }
    if matches!(b, b".nan" | b".NaN" | b".NAN") {
        return true;
    }
    if body.len() > 2 && body[0] == b'0' {
        let p = body[1];
        let rest = &body[2..];
        if p == b'x' || p == b'X' {
            return digits_with_underscores(rest, is_hex);
        }
        if p == b'o' || p == b'O' {
            return digits_with_underscores(rest, is_oct);
        }
        if p == b'b' || p == b'B' {
            return digits_with_underscores(rest, is_bin);
        }
    }
    // Decimal int or float: D (. D?)? (e[-+]?D)? | . D (e..)?
    let (mantissa, exp) = match body.iter().position(|&c| c == b'e' || c == b'E') {
        Some(p) => (&body[..p], Some(&body[p + 1..])),
        None => (body, None),
    };
    if let Some(e) = exp {
        let e = if !e.is_empty() && (e[0] == b'-' || e[0] == b'+') { &e[1..] } else { e };
        if !digits_with_underscores(e, is_dec) {
            return false;
        }
    }
    match mantissa.iter().position(|&c| c == b'.') {
        Some(p) => {
            let int = &mantissa[..p];
            let frac = &mantissa[p + 1..];
            if int.is_empty() {
                digits_with_underscores(frac, is_dec)
            } else {
                digits_with_underscores(int, is_dec) && (frac.is_empty() || digits_with_underscores(frac, is_dec))
            }
        }
        None => digits_with_underscores(mantissa, is_dec),
    }
}

pub fn is_null_word(s: &str) -> bool {
    matches!(s, "null" | "Null" | "NULL" | "~" | "")
}

pub fn is_bool_word(s: &str) -> bool {
    matches!(s, "true" | "True" | "TRUE" | "false" | "False" | "FALSE")
}

/// Resolves to a non-string under the core schema (as a plain scalar).
pub fn resolves_non_string(s: &str) -> bool {
    is_null_word(s) || is_bool_word(s) || looks_numeric(s)
}

/// Normalize core boolean/null spellings of a plain scalar.
pub fn normalize_plain(s: &str) -> String {
    match s {
        "True" | "TRUE" => "true".to_string(),
        "False" | "FALSE" => "false".to_string(),
        "Null" | "NULL" => "null".to_string(),
        _ => s.to_string(),
    }
}

fn is_printable(c: char) -> bool {
    match c {
        '\t' => false,
        '\u{20}'..='\u{7e}' => true,
        '\u{85}' => false,
        '\u{a0}'..='\u{d7ff}' => true,
        '\u{e000}'..='\u{fffd}' => c != '\u{feff}',
        '\u{10000}'..='\u{10ffff}' => true,
        _ => false,
    }
}

/// Whether `s` can be written as a plain scalar with the same string value.
pub fn plain_safe(s: &str, flow: bool) -> bool {
    if s.is_empty() {
        return false;
    }
    if s.starts_with([' ', '\t']) || s.ends_with([' ', '\t']) {
        return false;
    }
    if !s.chars().all(is_printable) {
        return false;
    }
    let b = s.as_bytes();
    let c0 = b[0];
    if matches!(c0, b',' | b'[' | b']' | b'{' | b'}' | b'#' | b'&' | b'*' | b'!' | b'|' | b'>' | b'\'' | b'"' | b'%' | b'@' | b'`') {
        return false;
    }
    if matches!(c0, b'-' | b'?' | b':') {
        if b.len() == 1 {
            return false;
        }
        let c1 = b[1];
        if c1 == b' ' || c1 == b'\t' {
            return false;
        }
        if flow && matches!(c1, b',' | b'[' | b']' | b'{' | b'}') {
            return false;
        }
    }
    if s.contains(": ") || s.contains(":\t") || s.ends_with(':') {
        return false;
    }
    if s.contains(" #") || s.contains("\t#") {
        return false;
    }
    if flow && s.bytes().any(|c| matches!(c, b',' | b'[' | b']' | b'{' | b'}' | b'"' | b'\'')) {
        return false;
    }
    if resolves_non_string(s) {
        return false;
    }
    true
}

/// Whether an existing plain scalar's text is syntactically valid as plain in this context.
pub fn plain_syntax_ok(s: &str, flow: bool) -> bool {
    if resolves_non_string(s) {
        return true;
    }
    plain_safe(s, flow)
}

/// Greedy fill of `text` into lines of at most `width` chars, breaking only at single spaces.
pub fn fill_words(text: &str, width: usize) -> Vec<String> {
    // Split into segments at single spaces surrounded by non-space characters.
    let chars: Vec<char> = text.chars().collect();
    let mut segs: Vec<String> = Vec::new();
    let mut cur = String::new();
    let n = chars.len();
    for i in 0..n {
        let c = chars[i];
        if c == ' ' && i > 0 && i + 1 < n && chars[i - 1] != ' ' && chars[i + 1] != ' ' {
            segs.push(std::mem::take(&mut cur));
        } else {
            cur.push(c);
        }
    }
    segs.push(cur);
    let mut lines = Vec::new();
    let mut line = String::new();
    let mut line_len = 0usize;
    for seg in segs {
        let sl = seg.chars().count();
        if line.is_empty() {
            line = seg;
            line_len = sl;
        } else if line_len + 1 + sl <= width {
            line.push(' ');
            line.push_str(&seg);
            line_len += 1 + sl;
        } else {
            lines.push(std::mem::take(&mut line));
            line = seg;
            line_len = sl;
        }
    }
    lines.push(line);
    lines
}

/// Whether a single-line string value can be written as a folded block scalar.
pub fn fold_eligible(s: &str) -> bool {
    if s.is_empty() || s.contains('\n') {
        return false;
    }
    if s.starts_with([' ', '\t']) || s.ends_with([' ', '\t']) {
        return false;
    }
    if !s.chars().all(is_printable) {
        return false;
    }
    // Needs at least one break opportunity.
    let chars: Vec<char> = s.chars().collect();
    (1..chars.len().saturating_sub(1)).any(|i| chars[i] == ' ' && chars[i - 1] != ' ' && chars[i + 1] != ' ')
}

/// Whether a multi-line string can be written as a literal block scalar.
pub fn literal_eligible(s: &str) -> bool {
    if !s.contains('\n') {
        return false;
    }
    if s.trim_matches('\n').is_empty() {
        return false;
    }
    for c in s.chars() {
        if c == '\n' || c == '\t' {
            continue;
        }
        if !is_printable(c) {
            return false;
        }
    }
    true
}

/// Build literal block header and lines for a value with newlines.
pub fn literal_block(s: &str, indent_width: usize) -> (String, Vec<String>) {
    let trailing = s.len() - s.trim_end_matches('\n').len();
    let body = s.trim_end_matches('\n');
    let chomp = match trailing {
        0 => "-",
        1 => "",
        _ => "+",
    };
    let mut lines: Vec<String> = body.split('\n').map(|l| l.to_string()).collect();
    if trailing > 1 {
        for _ in 0..trailing - 1 {
            lines.push(String::new());
        }
    }
    // Leading spaces in the first non-empty line need an indentation indicator.
    let first_nonempty = lines.iter().find(|l| !l.is_empty());
    let needs_indicator = first_nonempty.map(|l| l.starts_with(' ')).unwrap_or(false);
    let header = if needs_indicator {
        format!("|{}{}", indent_width, chomp)
    } else {
        format!("|{}", chomp)
    };
    (header, lines)
}
