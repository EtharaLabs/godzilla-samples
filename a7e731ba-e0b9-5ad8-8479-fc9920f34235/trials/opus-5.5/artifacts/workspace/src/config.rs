// yamark.toml discovery, validation and application.

use crate::options::{Options, TableWidths, Wrap};
use crate::toml::Value;
use std::path::{Path, PathBuf};

#[derive(Clone, Debug)]
pub enum TemplateLayer {
    Replace(Vec<(String, String)>),
    Add(Vec<(String, String)>),
}

#[derive(Clone, Debug, Default)]
pub struct TemplateCfg {
    pub replace: Option<Vec<(String, String)>>,
    pub add: Vec<(String, String)>,
}

#[derive(Clone, Debug)]
pub enum FormatterCfg {
    Builtin(String),
    Custom { command: Vec<String>, path_suffix: String },
}

#[derive(Clone, Debug, Default)]
pub struct Config {
    pub dir: PathBuf,
    pub wrap: Option<Wrap>,
    pub table_widths: Option<TableWidths>,
    pub compact: Option<bool>,
    pub hr: Option<String>,
    pub template: TemplateCfg,
    pub embedded: Vec<(String, FormatterCfg)>,
    pub paths: Vec<(String, Option<TemplateCfg>, Option<TemplateCfg>)>,
}

fn apply_template(base: &mut Vec<(String, String)>, t: &TemplateCfg) {
    if let Some(r) = &t.replace {
        *base = r.clone();
    }
    base.extend(t.add.iter().cloned());
}

impl Config {
    pub fn apply(&self, o: &mut Options, file: &Path) {
        if let Some(w) = self.wrap {
            o.wrap = w;
        }
        if let Some(t) = self.table_widths {
            o.table_widths = t;
        }
        if let Some(c) = self.compact {
            o.compact = c;
        }
        if let Some(h) = &self.hr {
            o.hr_marker = h.clone();
        }
        apply_template(&mut o.templates.pairs, &self.template);
        apply_template(&mut o.embedded_md_templates.pairs, &self.template);
        // Path layers from shallowest to deepest.
        let abs = std::fs::canonicalize(file).unwrap_or_else(|_| {
            let p = if file.is_absolute() { file.to_path_buf() } else { std::env::current_dir().unwrap_or_default().join(file) };
            p
        });
        let rel = abs.strip_prefix(&self.dir).map(|p| p.to_path_buf()).unwrap_or_default();
        let mut layers: Vec<&(String, Option<TemplateCfg>, Option<TemplateCfg>)> = self
            .paths
            .iter()
            .filter(|(k, _, _)| {
                let kp = Path::new(k.trim_end_matches('/'));
                rel.starts_with(kp)
            })
            .collect();
        layers.sort_by_key(|(k, _, _)| Path::new(k).components().count());
        for (_, t, em) in layers {
            if let Some(t) = t {
                apply_template(&mut o.templates.pairs, t);
                apply_template(&mut o.embedded_md_templates.pairs, t);
            }
            if let Some(em) = em {
                apply_template(&mut o.embedded_md_templates.pairs, em);
            }
        }
    }
}

type CfgErr = (String, String);

fn parse_delims(v: &Value, name: &str) -> Result<Vec<(String, String)>, String> {
    let arr = match v {
        Value::Array(a) => a,
        _ => return Err(format!("{} must be an array", name)),
    };
    let mut out = Vec::new();
    for item in arr {
        let t = match item {
            Value::Table(t) => t,
            _ => return Err(format!("{} entries must be tables", name)),
        };
        for (k, _) in t {
            if k != "open" && k != "close" {
                return Err(format!("unknown {} key: {}", name, k));
            }
        }
        let open = match item.get("open") {
            Some(Value::Str(s)) => s.clone(),
            Some(_) => return Err(format!("{}.open must be a string", name)),
            None => return Err(format!("{}.open is required", name)),
        };
        let close = match item.get("close") {
            Some(Value::Str(s)) => s.clone(),
            Some(_) => return Err(format!("{}.close must be a string", name)),
            None => return Err(format!("{}.close is required", name)),
        };
        if open.is_empty() {
            return Err(format!("{}.open must not be empty", name));
        }
        if close.is_empty() {
            return Err(format!("{}.close must not be empty", name));
        }
        out.push((open, close));
    }
    Ok(out)
}

fn parse_template(v: &Value, prefix: &str) -> Result<TemplateCfg, String> {
    let t = match v {
        Value::Table(t) => t,
        _ => return Err(format!("{} config must be a table", prefix)),
    };
    let mut cfg = TemplateCfg::default();
    for (k, val) in t {
        match k.as_str() {
            "add_delimiters" => cfg.add = parse_delims(val, &format!("{}.add_delimiters", prefix))?,
            "replace_delimiters" => cfg.replace = Some(parse_delims(val, &format!("{}.replace_delimiters", prefix))?),
            _ => return Err(format!("unknown template config key: {}.{}", prefix, k)),
        }
    }
    Ok(cfg)
}

const SHORTHANDS: &[&str] = &[
    "ruff", "air", "mdformat", "prettier-json", "prettier-jsonc", "prettier-json5", "prettier-graphql", "prettier-css", "prettier-scss", "prettier-less", "prettier-postcss", "prettier-html", "prettier-js", "prettier-jsx", "prettier-ts", "prettier-tsx",
];

fn parse_config(text: &str, dir: &Path) -> Result<Config, String> {
    let root = match crate::toml::parse(text) {
        Ok(v) => v,
        Err(e) => {
            let line_text = text.lines().nth(e.line.saturating_sub(1)).unwrap_or("");
            let caret = format!("{}{}", " ".repeat(e.col.saturating_sub(1)), "^".repeat(e.span.max(1)));
            let msg = e.msg.replace("\\n", "\n");
            let w = e.line.to_string().len();
            return Err(format!(
                "invalid yamark.toml: TOML parse error at line {}, column {}\n{} |\n{} | {}\n{} | {}\n{}\n",
                e.line,
                e.col,
                " ".repeat(w),
                e.line,
                line_text,
                " ".repeat(w),
                caret,
                msg
            ));
        }
    };
    let mut cfg = Config { dir: dir.to_path_buf(), ..Default::default() };
    let top = match &root {
        Value::Table(t) => t,
        _ => return Err("invalid yamark.toml".into()),
    };
    for (k, v) in top {
        match k.as_str() {
            "format" => {
                let t = match v {
                    Value::Table(t) => t,
                    _ => return Err("format config must be a table".into()),
                };
                for (fk, fv) in t {
                    match fk.as_str() {
                        "wrap" => match fv {
                            Value::Str(s) => match crate::options::parse_wrap(s) {
                                Some(w) => cfg.wrap = Some(w),
                                None => return Err("format.wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>".into()),
                            },
                            _ => return Err("format.wrap must be a string".into()),
                        },
                        "table_widths" => match fv {
                            Value::Str(s) if s == "fit" => cfg.table_widths = Some(TableWidths::Fit),
                            Value::Str(s) if s == "preserve" => cfg.table_widths = Some(TableWidths::Preserve),
                            _ => return Err("format.table_widths must be fit or preserve".into()),
                        },
                        "compact" => match fv {
                            Value::Bool(b) => cfg.compact = Some(*b),
                            _ => return Err("format.compact must be a boolean".into()),
                        },
                        "markdown_horizontal_rule" => match fv {
                            Value::Str(s) if s == "---" || s == "***" => cfg.hr = Some(s.clone()),
                            _ => return Err("format.markdown_horizontal_rule must be \"---\" or \"***\"".into()),
                        },
                        _ => return Err(format!("unknown format config key: format.{}", fk)),
                    }
                }
            }
            "template" => cfg.template = parse_template(v, "template")?,
            "embedded" => {
                let t = match v {
                    Value::Table(t) => t,
                    _ => return Err("embedded config must be a table".into()),
                };
                for (name, ev) in t {
                    if name.is_empty() || name.trim() != name {
                        return Err("embedded formatter names must be non-empty and trimmed".into());
                    }
                    if matches!(name.as_str(), "skip" | "skip file" | "off" | "on" | "table") {
                        return Err(format!("reserved fmt directive name: {}", name));
                    }
                    let et = match ev {
                        Value::Table(t) => t,
                        _ => return Err(format!("embedded.{} must be a table", name)),
                    };
                    let f = match ev.get("formatter") {
                        Some(f) => f,
                        None => return Err("embedded formatter entries must contain formatter".into()),
                    };
                    for (ek, _) in et {
                        if ek != "formatter" {
                            return Err(format!("unknown embedded config key: embedded.{}.{}", name, ek));
                        }
                    }
                    let fc = match f {
                        Value::Str(s) => {
                            if !SHORTHANDS.contains(&s.as_str()) {
                                return Err(format!("unknown embedded formatter shorthand: {}", s));
                            }
                            FormatterCfg::Builtin(s.clone())
                        }
                        Value::Table(ft) => {
                            for (fk, _) in ft {
                                if fk != "command" && fk != "path_suffix" {
                                    return Err(format!("unknown embedded formatter key: {}", fk));
                                }
                            }
                            let command: Vec<String> = match f.get("command") {
                                Some(Value::Array(a)) => {
                                    let mut v = Vec::new();
                                    for x in a {
                                        match x {
                                            Value::Str(s) => v.push(s.clone()),
                                            _ => return Err("embedded formatter command must be an array of strings".into()),
                                        }
                                    }
                                    v
                                }
                                Some(_) => return Err("embedded formatter command must be an array of strings".into()),
                                None => return Err("missing embedded formatter command".into()),
                            };
                            if command.is_empty() {
                                return Err("embedded formatter command must not be empty".into());
                            }
                            if !command.iter().any(|a| a == "{path}") || command.iter().any(|a| a != "{path}" && a.contains("{path}")) {
                                return Err("embedded formatter command must contain {path} as an argv item".into());
                            }
                            let path_suffix = match f.get("path_suffix") {
                                Some(Value::Str(s)) if !s.is_empty() => s.clone(),
                                Some(_) => return Err("embedded formatter path_suffix must not be empty".into()),
                                None => return Err("missing embedded formatter path_suffix".into()),
                            };
                            FormatterCfg::Custom { command, path_suffix }
                        }
                        _ => return Err("embedded formatter must be a string or table".into()),
                    };
                    cfg.embedded.push((name.clone(), fc));
                }
            }
            "paths" => {
                let t = match v {
                    Value::Table(t) => t,
                    _ => return Err("paths config must be a table".into()),
                };
                for (pk, pv) in t {
                    if pk.is_empty() {
                        return Err("path config keys must not be empty".into());
                    }
                    if pk.starts_with('/') || Path::new(pk).components().any(|c| matches!(c, std::path::Component::ParentDir)) {
                        return Err("path config keys must be relative and must not contain ..".into());
                    }
                    let pt = match pv {
                        Value::Table(t) => t,
                        _ => return Err(format!("paths.{} must be a table", pk)),
                    };
                    let mut tmpl = None;
                    let mut emb = None;
                    for (sk, sv) in pt {
                        match sk.as_str() {
                            "template" => tmpl = Some(parse_template(sv, &format!("paths.{}.template", pk))?),
                            "embedded_markdown" => {
                                let et = match sv {
                                    Value::Table(t) => t,
                                    _ => return Err(format!("paths.{}.embedded_markdown must be a table", pk)),
                                };
                                for (ek, ev) in et {
                                    if ek != "template" {
                                        return Err(format!("unknown path config key: paths.{}.embedded_markdown.{}", pk, ek));
                                    }
                                    emb = Some(parse_template(ev, &format!("paths.{}.embedded_markdown.template", pk))?);
                                }
                            }
                            _ => return Err(format!("unknown path config key: paths.{}.{}", pk, sk)),
                        }
                    }
                    cfg.paths.push((pk.clone(), tmpl, emb));
                }
            }
            _ => return Err(format!("unknown config key: {}", k)),
        }
    }
    Ok(cfg)
}

pub fn load_explicit(p: &str) -> Result<Config, CfgErr> {
    let text = std::fs::read_to_string(p).map_err(|e| (p.to_string(), format!("failed to read config: {}", e)))?;
    let dir = std::fs::canonicalize(p)
        .ok()
        .and_then(|c| c.parent().map(|x| x.to_path_buf()))
        .unwrap_or_default();
    parse_config(&text, &dir).map_err(|m| (p.to_string(), m))
}

/// Find the nearest yamark.toml from the file's directory upward.
pub fn discover(file: &Path) -> Result<Option<Config>, CfgErr> {
    let abs = if file.is_absolute() { file.to_path_buf() } else { std::env::current_dir().unwrap_or_default().join(file) };
    let mut dir = abs.parent().map(|p| p.to_path_buf());
    while let Some(d) = dir {
        let cand = d.join("yamark.toml");
        if cand.is_file() {
            let canon = std::fs::canonicalize(&cand).unwrap_or(cand.clone());
            let shown = canon.to_string_lossy().into_owned();
            let text = std::fs::read_to_string(&cand).map_err(|e| (shown.clone(), format!("failed to read config: {}", e)))?;
            let cdir = canon.parent().map(|x| x.to_path_buf()).unwrap_or_default();
            return parse_config(&text, &cdir).map(Some).map_err(|m| (shown, m));
        }
        dir = d.parent().map(|p| p.to_path_buf());
    }
    Ok(None)
}
