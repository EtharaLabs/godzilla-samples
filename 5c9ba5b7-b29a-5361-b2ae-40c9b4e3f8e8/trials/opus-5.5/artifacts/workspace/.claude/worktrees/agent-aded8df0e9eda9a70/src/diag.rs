// Diagnostics: errors and warnings with stable codes and source spans.

#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct Span {
    pub start: usize,
    pub end: usize,
}

impl Span {
    pub fn new(start: usize, end: usize) -> Span {
        Span { start, end }
    }
    pub fn to(self, other: Span) -> Span {
        Span { start: self.start.min(other.start), end: self.end.max(other.end) }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum Severity {
    Error,
    Warning,
}

#[derive(Debug, Clone)]
pub struct Diag {
    pub family: String,
    pub severity: Severity,
    pub message: String,
    pub span: Span,
    pub fixes: Vec<Fix>,
    // a second place the diagnostic points at (a duplicate's first use)
    pub related: Option<Span>,
}

#[derive(Debug, Clone)]
pub struct Fix {
    pub message: String,
    pub span: Span,
    pub replacement: String,
}

impl Diag {
    pub fn error(family: &str, message: &str, span: Span) -> Diag {
        Diag { family: family.to_string(), severity: Severity::Error, message: message.to_string(), span, fixes: vec![], related: None }
    }
    pub fn warning(family: &str, message: &str, span: Span) -> Diag {
        Diag { family: family.to_string(), severity: Severity::Warning, message: message.to_string(), span, fixes: vec![], related: None }
    }
    pub fn code(&self) -> &'static str {
        family_code(&self.family)
    }
}

pub fn family_code(family: &str) -> &'static str {
    match family {
        "lex" => "L000",
        "unterminated-string" => "L001",
        "bad-escape" => "L002",
        "unexpected-char" => "L004",
        "parse" => "P000",
        "expected-token" => "P001",
        "empty-bars" => "P002",
        "invalid-id" => "P003",
        "declaration-outside-block" => "P004",
        "stylesheet-after-canvas" => "P005",
        "text-carries-children" => "P006",
        "spaced-call-paren" => "P007",
        "validate" => "V000",
        "unknown-property" => "V001",
        "class-never-worn" => "V004",
        "malformed-value" => "V005",
        "invalid-color" => "V010",
        "resolve" => "R000",
        "unknown-type" => "R001",
        "unknown-class" => "R002",
        "duplicate-id" => "R003",
        "reserved-id" => "R007",
        "unknown-endpoint" => "R008",
        "chain-too-short" => "R009",
        "asset-not-found" => "R010",
        "asset-no-fs" => "R024",
        "layout" => "Y000",
        "missing-required-property" => "Y001",
        "chart-data" => "Y002",
        "chart-type" => "Y009",
        "impossible-link" => "T001",
        "law-breach" => "T002",
        _ => "X000",
    }
}

// Line/column (1-based, columns counted in chars) of a byte offset.
pub fn line_col(src: &str, off: usize) -> (usize, usize) {
    let mut line = 1;
    let mut col = 1;
    for (i, c) in src.char_indices() {
        if i >= off {
            break;
        }
        if c == '\n' {
            line += 1;
            col = 1;
        } else {
            col += 1;
        }
    }
    (line, col)
}

pub fn render_text(file: &str, src: &str, d: &Diag) -> String {
    let (l, c) = line_col(src, d.span.start);
    let sev = match d.severity {
        Severity::Error => "error",
        Severity::Warning => "warning",
    };
    match d.related {
        Some(r) => {
            let (rl, rc) = line_col(src, r.start);
            format!("{}:{}:{}: {}: {} (previously at {}:{})", file, l, c, sev, d.message, rl, rc)
        }
        None => format!("{}:{}:{}: {}: {}", file, l, c, sev, d.message),
    }
}

pub fn json_escape(s: &str) -> String {
    let mut o = String::new();
    for c in s.chars() {
        match c {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            '\n' => o.push_str("\\n"),
            '\r' => o.push_str("\\r"),
            '\t' => o.push_str("\\t"),
            c if (c as u32) < 0x20 => o.push_str(&format!("\\u{:04x}", c as u32)),
            c => o.push(c),
        }
    }
    o
}

pub fn render_json(file: &str, src: &str, diags: &[Diag]) -> String {
    let mut o = String::new();
    o.push_str("{\n");
    o.push_str(&format!("  \"file\": \"{}\",\n", json_escape(file)));
    if diags.is_empty() {
        o.push_str("  \"diagnostics\": []\n}\n");
        return o;
    }
    o.push_str("  \"diagnostics\": [\n");
    for (i, d) in diags.iter().enumerate() {
        let (l, c) = line_col(src, d.span.start);
        let (el, ec) = line_col(src, d.span.end);
        let sev = match d.severity {
            Severity::Error => "error",
            Severity::Warning => "warning",
        };
        o.push_str("    {\n");
        o.push_str(&format!("      \"code\": \"{}\",\n", d.code()));
        o.push_str(&format!("      \"family\": \"{}\",\n", json_escape(&d.family)));
        o.push_str(&format!("      \"severity\": \"{}\",\n", sev));
        o.push_str(&format!("      \"message\": \"{}\",\n", json_escape(&d.message)));
        o.push_str("      \"span\": {\n");
        o.push_str(&format!("        \"start\": {},\n", d.span.start));
        o.push_str(&format!("        \"end\": {},\n", d.span.end));
        o.push_str(&format!("        \"line\": {},\n", l));
        o.push_str(&format!("        \"col\": {},\n", c));
        o.push_str(&format!("        \"endLine\": {},\n", el));
        o.push_str(&format!("        \"endCol\": {}\n", ec));
        if let Some(r) = d.related {
            let (rl, rc) = line_col(src, r.start);
            let (rel, rec) = line_col(src, r.end);
            o.push_str("      },\n");
            o.push_str("      \"related\": {\n");
            o.push_str(&format!("        \"start\": {},\n", r.start));
            o.push_str(&format!("        \"end\": {},\n", r.end));
            o.push_str(&format!("        \"line\": {},\n", rl));
            o.push_str(&format!("        \"col\": {},\n", rc));
            o.push_str(&format!("        \"endLine\": {},\n", rel));
            o.push_str(&format!("        \"endCol\": {}\n", rec));
        }
        if d.fixes.is_empty() {
            o.push_str("      }\n");
        } else {
            o.push_str("      },\n");
            o.push_str("      \"fixes\": [\n");
            for (k, f) in d.fixes.iter().enumerate() {
                o.push_str("        {\n");
                o.push_str(&format!("          \"message\": \"{}\",\n", json_escape(&f.message)));
                o.push_str(&format!("          \"start\": {},\n", f.span.start));
                o.push_str(&format!("          \"end\": {},\n", f.span.end));
                o.push_str(&format!("          \"replacement\": \"{}\"\n", json_escape(&f.replacement)));
                o.push_str(if k + 1 < d.fixes.len() { "        },\n" } else { "        }\n" });
            }
            o.push_str("      ]\n");
        }
        o.push_str(if i + 1 < diags.len() { "    },\n" } else { "    }\n" });
    }
    o.push_str("  ]\n}\n");
    o
}
