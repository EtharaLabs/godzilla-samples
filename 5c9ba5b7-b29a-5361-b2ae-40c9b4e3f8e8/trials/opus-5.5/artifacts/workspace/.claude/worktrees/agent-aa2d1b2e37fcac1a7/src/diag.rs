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
    // an earlier site the diagnostic points back to (a duplicate's first id)
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
        "misused-property" => "V002",
        "inert-on-every-wearer" => "V003",
        "class-never-worn" => "V004",
        "malformed-value" => "V005",
        "off-grid-placement" => "V006",
        "place-outside-sequence" => "V007",
        "activation-outside-sequence" => "V008",
        "wavy-outline" => "V009",
        "invalid-color" => "V010",
        "deferred-property" => "V011",
        "legacy-space-list" => "R013",
        "color-component-out-of-range" => "R023",
        "schematic-type" => "Y008",
        "floorplan-type" => "Y010",
        "resolve" => "R000",
        "unknown-type" => "R001",
        "shadows-builtin" => "R006",
        "unknown-class" => "R002",
        "duplicate-id" => "R003",
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
            o.push_str(if i + 1 < diags.len() { "      }\n    },\n" } else { "      }\n    }\n" });
            continue;
        }
        match d.fixes.first() {
            None => o.push_str("      }\n"),
            Some(f) => {
                // a machine-applicable suggestion (its applicability rides in `message`)
                let (fl, fc) = line_col(src, f.span.start);
                let (fel, fec) = line_col(src, f.span.end);
                o.push_str("      },\n");
                o.push_str("      \"suggestion\": {\n");
                o.push_str("        \"span\": {\n");
                o.push_str(&format!("          \"start\": {},\n", f.span.start));
                o.push_str(&format!("          \"end\": {},\n", f.span.end));
                o.push_str(&format!("          \"line\": {},\n", fl));
                o.push_str(&format!("          \"col\": {},\n", fc));
                o.push_str(&format!("          \"endLine\": {},\n", fel));
                o.push_str(&format!("          \"endCol\": {}\n", fec));
                o.push_str("        },\n");
                o.push_str(&format!("        \"replacement\": \"{}\",\n", json_escape(&f.replacement)));
                o.push_str(&format!("        \"applicability\": \"{}\"\n", json_escape(&f.message)));
                o.push_str("      }\n");
            }
        }
        o.push_str(if i + 1 < diags.len() { "    },\n" } else { "    }\n" });
    }
    o.push_str("  ]\n}\n");
    o
}
