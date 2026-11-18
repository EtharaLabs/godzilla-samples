// Byte spans and line/column lookup.

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Default, PartialOrd, Ord)]
pub struct Span {
    pub lo: usize,
    pub hi: usize,
}

impl Span {
    pub fn new(lo: usize, hi: usize) -> Span {
        Span { lo, hi }
    }
    pub fn to(self, other: Span) -> Span {
        Span { lo: self.lo.min(other.lo), hi: self.hi.max(other.hi) }
    }
}

/// 1-based line and byte column of an offset.
pub fn line_col(src: &str, off: usize) -> (usize, usize) {
    let bytes = src.as_bytes();
    let off = off.min(bytes.len());
    let mut line = 1;
    let mut ls = 0;
    for (i, &b) in bytes[..off].iter().enumerate() {
        if b == b'\n' {
            line += 1;
            ls = i + 1;
        }
    }
    (line, off - ls + 1)
}

/// The text of a 1-based line (without its newline).
pub fn line_text(src: &str, line: usize) -> &str {
    src.split('\n').nth(line - 1).unwrap_or("")
}
