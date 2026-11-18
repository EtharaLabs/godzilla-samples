// Git clean/smudge filter helpers.

use crate::cli::Matches;
use crate::format_cmd::{decode, FileKind};
use crate::options::{Options, Wrap};
use std::io::{Read, Write};

fn filter(m: &Matches, wrap: Wrap) -> i32 {
    let path = m.value("stdin-filename").unwrap_or("").to_string();
    if crate::format_cmd::detect_kind(&path) != Some(FileKind::Markdown) {
        eprint!("{}:1:1: error: unsupported Git filter path\n", path);
        return 1;
    }
    let mut bytes = Vec::new();
    let _ = std::io::stdin().read_to_end(&mut bytes);
    let text = match decode(&bytes) {
        Ok(t) => t,
        Err(e) => {
            eprint!("{}:1:1: error: {}\n", path, e);
            return 1;
        }
    };
    let mut opts = Options::default();
    opts.wrap = wrap;
    opts.compact_tables = true;
    opts.ignore_document_options = true;
    let mut notes = Vec::new();
    match crate::format_cmd::format_text(FileKind::Markdown, &text, &opts) {
        Ok(out) => {
            notes.extend(out.notes);
            let mut so = std::io::stdout();
            let _ = so.write_all(out.text.as_bytes());
            let _ = so.flush();
            0
        }
        Err(d) => {
            eprint!("{}:{}:{}: error: {}\n", path, d.line, d.col, d.msg);
            1
        }
    }
}

pub fn run(name: &str, m: &Matches) -> i32 {
    match name {
        "clean" => filter(m, Wrap::Sentence(None)),
        "smudge" => {
            let col = m.value("markdown-wrap-at-column").and_then(|v| v.parse().ok()).unwrap_or(72);
            filter(m, Wrap::Column(col))
        }
        _ => run_repo_command(name, m),
    }
}

fn git(args: &[&str], repo: &str) -> Result<String, String> {
    let out = std::process::Command::new("git")
        .arg("-C")
        .arg(repo)
        .args(args)
        .output()
        .map_err(|e| e.to_string())?;
    if !out.status.success() {
        return Err(String::from_utf8_lossy(&out.stderr).trim().to_string());
    }
    Ok(String::from_utf8_lossy(&out.stdout).to_string())
}

const PATTERNS: &[&str] = &["*.md", "*.qmd", "*.Rmd", "*.rmd"];

fn run_repo_command(name: &str, m: &Matches) -> i32 {
    let repo = m.value("repo").unwrap_or(".").to_string();
    let top = match git(&["rev-parse", "--show-toplevel"], &repo) {
        Ok(t) => t.trim().to_string(),
        Err(e) => {
            eprintln!("error: {}", e);
            return 1;
        }
    };
    let exe = m
        .value("yamark")
        .map(|s| s.to_string())
        .unwrap_or_else(|| std::env::current_exe().map(|p| p.to_string_lossy().into_owned()).unwrap_or_else(|_| "yamark".into()));
    let col = m.value("markdown-wrap-at-column").unwrap_or("72").to_string();
    match name {
        "setup" | "adopt" | "join" => {
            let clean = format!("{} git-filter clean --stdin-filename %f", exe);
            let smudge = format!("{} git-filter smudge --stdin-filename %f --markdown-wrap-at-column {}", exe, col);
            for (k, v) in [
                ("filter.yamark-md.clean", clean.as_str()),
                ("filter.yamark-md.smudge", smudge.as_str()),
                ("filter.yamark-md.required", "true"),
                ("merge.renormalize", "true"),
            ] {
                if let Err(e) = git(&["config", k, v], &top) {
                    eprintln!("error: {}", e);
                    return 1;
                }
                println!("set {} = {}", k, v);
            }
            let patterns: Vec<String> = if m.positionals.is_empty() {
                PATTERNS.iter().map(|s| s.to_string()).collect()
            } else {
                m.positionals.clone()
            };
            let attr_path = if name == "setup" {
                std::path::Path::new(&top).join(".git").join("info").join("attributes")
            } else {
                std::path::Path::new(&top).join(".gitattributes")
            };
            if name != "join" {
                let existing = std::fs::read_to_string(&attr_path).unwrap_or_default();
                let mut content = existing.clone();
                for p in &patterns {
                    let line = format!("{} filter=yamark-md", p);
                    if !existing.lines().any(|l| l.trim() == line) {
                        if !content.is_empty() && !content.ends_with('\n') {
                            content.push('\n');
                        }
                        content.push_str(&line);
                        content.push('\n');
                    }
                }
                if let Some(parent) = attr_path.parent() {
                    let _ = std::fs::create_dir_all(parent);
                }
                if let Err(e) = std::fs::write(&attr_path, content) {
                    eprintln!("error: {}", e);
                    return 1;
                }
                println!("updated {}", attr_path.display());
            }
            0
        }
        "teardown" => {
            for k in ["filter.yamark-md.clean", "filter.yamark-md.smudge", "filter.yamark-md.required"] {
                let _ = git(&["config", "--unset", k], &top);
            }
            let attr_path = std::path::Path::new(&top).join(".git").join("info").join("attributes");
            if let Ok(existing) = std::fs::read_to_string(&attr_path) {
                let kept: Vec<&str> = existing.lines().filter(|l| !l.trim().ends_with("filter=yamark-md")).collect();
                let mut content = kept.join("\n");
                if !content.is_empty() {
                    content.push('\n');
                }
                let _ = std::fs::write(&attr_path, content);
            }
            0
        }
        "check" => 0,
        _ => 0,
    }
}
