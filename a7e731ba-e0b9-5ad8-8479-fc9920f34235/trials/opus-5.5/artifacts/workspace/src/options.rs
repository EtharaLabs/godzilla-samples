// Formatting options shared by the formatters.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Wrap {
    None,
    Paragraph,
    Sentence(Option<usize>),
    Column(usize),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TableWidths {
    Fit,
    Preserve,
}

pub fn parse_wrap(s: &str) -> Option<Wrap> {
    match s {
        "none" => Some(Wrap::None),
        "paragraph" => Some(Wrap::Paragraph),
        "sentence" => Some(Wrap::Sentence(None)),
        _ => {
            if let Some(rest) = s.strip_prefix("sentence:") {
                match rest.parse::<usize>() {
                    Ok(n) if n > 0 => Some(Wrap::Sentence(Some(n))),
                    _ => None,
                }
            } else {
                match s.parse::<usize>() {
                    Ok(n) if n > 0 => Some(Wrap::Column(n)),
                    _ => None,
                }
            }
        }
    }
}

#[derive(Clone, Debug)]
pub struct TemplateDelims {
    pub pairs: Vec<(String, String)>,
}

impl Default for TemplateDelims {
    fn default() -> Self {
        TemplateDelims {
            pairs: vec![
                ("{{".to_string(), "}}".to_string()),
                ("{%".to_string(), "%}".to_string()),
                ("{#".to_string(), "#}".to_string()),
                ("<%".to_string(), "%>".to_string()),
            ],
        }
    }
}

#[derive(Clone, Debug)]
pub struct Options {
    pub wrap: Wrap,
    pub table_widths: TableWidths,
    pub canonical: bool,
    pub preserve_footnotes: bool,
    pub line_width: usize,
    pub prose_width: usize,
    pub indent_width: usize,
    pub compact: bool,
    pub skip_embedded: bool,
    pub diagnostics: bool,
    pub hr_marker: String,
    pub templates: TemplateDelims,
    pub embedded_md_templates: TemplateDelims,
    /// Compact pipe tables (git filter output).
    pub compact_tables: bool,
    /// Git filters ignore document Markdown options.
    pub ignore_document_options: bool,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            wrap: Wrap::Column(72),
            table_widths: TableWidths::Fit,
            canonical: false,
            preserve_footnotes: false,
            line_width: 80,
            prose_width: 72,
            indent_width: 2,
            compact: false,
            skip_embedded: false,
            diagnostics: false,
            hr_marker: "---".to_string(),
            templates: TemplateDelims::default(),
            embedded_md_templates: TemplateDelims::default(),
            compact_tables: false,
            ignore_document_options: false,
        }
    }
}
