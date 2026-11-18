// rustc-style diagnostics.

use crate::source::{line_col, line_text, Span};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Severity {
    Error,
    Note,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Diag {
    pub severity: Severity,
    pub msg: String,
    pub span: Span,
}

impl Diag {
    pub fn error(msg: impl Into<String>, span: Span) -> Diag {
        Diag { severity: Severity::Error, msg: msg.into(), span }
    }
    pub fn note(msg: impl Into<String>, span: Span) -> Diag {
        Diag { severity: Severity::Note, msg: msg.into(), span }
    }
}

/// Render one diagnostic against its source, without a trailing newline.
pub fn render(src: &str, d: &Diag) -> String {
    let head = match d.severity {
        Severity::Error => "error",
        Severity::Note => "note",
    };
    let (line, col) = line_col(src, d.span.lo);
    let text = line_text(src, line);
    let lnum = line.to_string();
    let pad = " ".repeat(lnum.len());
    // the caret covers the span's bytes on its first line, at least one
    let line_end = col - 1 + (text.len() + 1 - col.min(text.len() + 1));
    let hi_col = {
        let (hl, hc) = line_col(src, d.span.hi);
        if hl == line {
            hc - 1
        } else {
            line_end
        }
    };
    let n = if hi_col > col - 1 { hi_col - (col - 1) } else { 1 };
    format!(
        "{}: {}\n{}--> {}:{}\n{} |\n{} | {}\n{} | {}{}",
        head,
        d.msg,
        pad,
        line,
        col,
        pad,
        lnum,
        text,
        pad,
        " ".repeat(col - 1),
        "^".repeat(n)
    )
}
