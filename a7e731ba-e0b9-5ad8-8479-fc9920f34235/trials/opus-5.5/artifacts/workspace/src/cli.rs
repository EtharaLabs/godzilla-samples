// Command-line parsing that mirrors the original clap-based interface.

use crate::help_text;
use std::collections::HashMap;

#[derive(Clone, Copy)]
pub struct OptDef {
    pub long: &'static str,
    pub value: Option<&'static str>,
}

pub struct CmdDef {
    pub path: &'static str,
    pub opts: &'static [OptDef],
    pub positional: Option<&'static str>,
    pub required: &'static [&'static str],
    pub help: &'static str,
    pub full_usage: &'static str,
}

const fn flag(long: &'static str) -> OptDef {
    OptDef { long, value: None }
}
const fn opt(long: &'static str, value: &'static str) -> OptDef {
    OptDef { long, value: Some(value) }
}

pub const FORMAT: CmdDef = CmdDef {
    path: "format",
    opts: &[
        flag("check"),
        flag("diff"),
        flag("diagnostics"),
        opt("stdin-file-path", "PATH"),
        opt("config", "PATH"),
        opt("wrap", "WRAP"),
        opt("table-widths", "TABLE_WIDTHS"),
        flag("canonical"),
        flag("preserve-footnotes"),
        opt("line-width", "LINE_WIDTH"),
        opt("prose-width", "PROSE_WIDTH"),
        opt("indent-width", "INDENT_WIDTH"),
        flag("compact"),
        flag("skip-embedded-formatters"),
    ],
    positional: Some("PATHS"),
    required: &[],
    help: help_text::FORMAT_HELP,
    full_usage: "format [OPTIONS] [PATHS]...",
};

pub const TO_YAML: CmdDef = CmdDef {
    path: "to-yaml",
    opts: &[
        opt("stdin-file-path", "PATH"),
        opt("config", "PATH"),
        opt("line-width", "LINE_WIDTH"),
        opt("prose-width", "PROSE_WIDTH"),
        opt("indent-width", "INDENT_WIDTH"),
        flag("compact"),
    ],
    positional: None,
    required: &["stdin-file-path"],
    help: help_text::TO_YAML_HELP,
    full_usage: "to-yaml [OPTIONS] --stdin-file-path <PATH>",
};

pub const GF_CLEAN: CmdDef = CmdDef {
    path: "git-filter clean",
    opts: &[opt("stdin-filename", "STDIN_FILENAME")],
    positional: None,
    required: &["stdin-filename"],
    help: help_text::GF_CLEAN,
    full_usage: "git-filter clean --stdin-filename <STDIN_FILENAME>",
};

pub const GF_SMUDGE: CmdDef = CmdDef {
    path: "git-filter smudge",
    opts: &[
        opt("stdin-filename", "STDIN_FILENAME"),
        opt("markdown-wrap-at-column", "MARKDOWN_WRAP_AT_COLUMN"),
    ],
    positional: None,
    required: &["stdin-filename"],
    help: help_text::GF_SMUDGE,
    full_usage: "git-filter smudge [OPTIONS] --stdin-filename <STDIN_FILENAME>",
};

pub const GF_ADOPT: CmdDef = CmdDef {
    path: "git-filter adopt",
    opts: &[
        opt("repo", "PATH"),
        opt("yamark", "PATH"),
        opt("markdown-wrap-at-column", "MARKDOWN_WRAP_AT_COLUMN"),
    ],
    positional: Some("PATHS"),
    required: &[],
    help: help_text::GF_ADOPT,
    full_usage: "git-filter adopt [OPTIONS] [PATHS]...",
};

pub const GF_JOIN: CmdDef = CmdDef {
    path: "git-filter join",
    opts: &[
        opt("repo", "PATH"),
        opt("yamark", "PATH"),
        opt("markdown-wrap-at-column", "MARKDOWN_WRAP_AT_COLUMN"),
    ],
    positional: None,
    required: &[],
    help: help_text::GF_JOIN,
    full_usage: "git-filter join [OPTIONS]",
};

pub const GF_CHECK: CmdDef = CmdDef {
    path: "git-filter check",
    opts: &[
        opt("repo", "PATH"),
        opt("markdown-wrap-at-column", "MARKDOWN_WRAP_AT_COLUMN"),
    ],
    positional: None,
    required: &[],
    help: help_text::GF_CHECK,
    full_usage: "git-filter check [OPTIONS]",
};

pub const GF_SETUP: CmdDef = CmdDef {
    path: "git-filter setup",
    opts: &[
        opt("repo", "PATH"),
        opt("yamark", "PATH"),
        opt("markdown-wrap-at-column", "MARKDOWN_WRAP_AT_COLUMN"),
    ],
    positional: Some("PATHS"),
    required: &[],
    help: help_text::GF_SETUP,
    full_usage: "git-filter setup [OPTIONS] [PATHS]...",
};

pub const GF_TEARDOWN: CmdDef = CmdDef {
    path: "git-filter teardown",
    opts: &[opt("repo", "PATH")],
    positional: None,
    required: &[],
    help: help_text::GF_TEARDOWN,
    full_usage: "git-filter teardown [OPTIONS]",
};

/// Result of a successful parse.
pub struct Matches {
    pub values: HashMap<&'static str, String>,
    pub flags: Vec<&'static str>,
    pub positionals: Vec<String>,
    /// Present arguments in command-line order (option longs or the positional name).
    pub order: Vec<&'static str>,
}

impl Matches {
    pub fn flag(&self, name: &str) -> bool {
        self.flags.iter().any(|f| *f == name)
    }
    pub fn value(&self, name: &str) -> Option<&str> {
        self.values.get(name).map(|s| s.as_str())
    }
}

pub enum CliExit {
    /// Print to stdout, exit 0.
    Stdout(String),
    /// Print to stderr, exit code.
    Stderr(String, i32),
}

pub fn bin_name() -> String {
    let arg0 = std::env::args_os().next().unwrap_or_default();
    let p = std::path::Path::new(&arg0);
    match p.file_name() {
        Some(n) => n.to_string_lossy().into_owned(),
        None => arg0.to_string_lossy().into_owned(),
    }
}

pub fn render(text: &str, bin: &str) -> String {
    text.replace("{BIN}", bin)
}

fn opt_display(o: &OptDef) -> String {
    match o.value {
        Some(v) => format!("--{} <{}>", o.long, v),
        None => format!("--{}", o.long),
    }
}

fn error_tail() -> &'static str {
    "\nFor more information, try '--help'.\n"
}

fn full_usage(cmd: &CmdDef, bin: &str) -> String {
    format!("Usage: {} {}\n", bin, cmd.full_usage)
}

/// Smart usage built from used arguments (option longs, or "@pos" for positional).
fn smart_usage(cmd: &CmdDef, bin: &str, used: &[&str]) -> String {
    if used.is_empty() {
        return full_usage(cmd, bin);
    }
    required_usage(cmd, bin, used)
}

fn required_usage(cmd: &CmdDef, bin: &str, used: &[&str]) -> String {
    let mut parts: Vec<String> = Vec::new();
    let mut seen: Vec<&str> = Vec::new();
    for r in cmd.required.iter().copied().chain(used.iter().copied()) {
        if r == "@pos" || seen.contains(&r) {
            continue;
        }
        seen.push(r);
        if r == "help" {
            parts.push("--help".to_string());
        } else if let Some(o) = cmd.opts.iter().find(|o| o.long == r) {
            parts.push(opt_display(o));
        }
    }
    if let Some(p) = cmd.positional {
        if used.contains(&"@pos") {
            parts.push(format!("<{}>...", p));
        } else {
            parts.push(format!("[{}]...", p));
        }
    }
    let mut s = format!("Usage: {} {}", bin, cmd.path);
    for p in parts {
        s.push(' ');
        s.push_str(&p);
    }
    s.push('\n');
    s
}

pub fn jaro(a: &str, b: &str) -> f64 {
    let a: Vec<char> = a.chars().collect();
    let b: Vec<char> = b.chars().collect();
    if a.is_empty() && b.is_empty() {
        return 1.0;
    }
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    if a.len() == 1 && b.len() == 1 {
        return if a[0] == b[0] { 1.0 } else { 0.0 };
    }
    let search_range = (a.len().max(b.len()) / 2).saturating_sub(1);
    let mut b_consumed = vec![false; b.len()];
    let mut matches = 0usize;
    let mut transpositions = 0usize;
    let mut b_match_index = 0usize;
    for (i, ac) in a.iter().enumerate() {
        let min_bound = if i > search_range { i - search_range } else { 0 };
        let max_bound = (b.len() - 1).min(i + search_range);
        if min_bound > max_bound {
            continue;
        }
        for j in min_bound..=max_bound {
            if *ac == b[j] && !b_consumed[j] {
                b_consumed[j] = true;
                matches += 1;
                if j < b_match_index {
                    transpositions += 1;
                }
                b_match_index = j;
                break;
            }
        }
    }
    if matches == 0 {
        return 0.0;
    }
    let m = matches as f64;
    (1.0 / 3.0) * (m / a.len() as f64 + m / b.len() as f64 + (m - transpositions as f64) / m)
}

pub fn did_you_mean<'a>(v: &str, candidates: impl IntoIterator<Item = &'a str>) -> Option<&'a str> {
    let mut best: Vec<(f64, &str)> = candidates
        .into_iter()
        .map(|c| (jaro(v, c), c))
        .filter(|(conf, _)| *conf > 0.7)
        .collect();
    best.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    best.pop().map(|(_, c)| c)
}

fn is_new_arg(a: &str) -> bool {
    a.starts_with('-') && a != "-"
}

fn validate_value(name: &str, val: &str) -> Result<(), String> {
    match name {
        "wrap" => {
            if crate::options::parse_wrap(val).is_some() {
                Ok(())
            } else {
                Err("wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>".into())
            }
        }
        "table-widths" => {
            if val == "fit" || val == "preserve" {
                Ok(())
            } else {
                Err("table-widths must be fit or preserve".into())
            }
        }
        "line-width" | "prose-width" | "indent-width" | "markdown-wrap-at-column" => {
            match parse_positive(val) {
                Ok(_) => Ok(()),
                Err(e) => Err(e),
            }
        }
        _ => Ok(()),
    }
}

pub fn parse_positive(val: &str) -> Result<usize, String> {
    match val.parse::<usize>() {
        Ok(0) => Err("value must be greater than 0".into()),
        Ok(n) => Ok(n),
        Err(e) => Err(format!("invalid positive integer: {}", e)),
    }
}

/// Parse the arguments of a leaf command.
pub fn parse_command(cmd: &CmdDef, args: &[String], bin: &str) -> Result<Matches, CliExit> {
    let mut m = Matches {
        values: HashMap::new(),
        flags: Vec::new(),
        positionals: Vec::new(),
        order: Vec::new(),
    };
    let mut trailing = false;
    let mut i = 0;
    while i < args.len() {
        let a = &args[i];
        i += 1;
        if trailing || !is_new_arg(a) {
            if a == "--" && !trailing {
                trailing = true;
                continue;
            }
            match cmd.positional {
                Some(_) => {
                    m.positionals.push(a.clone());
                    if !m.order.contains(&"@pos") {
                        m.order.push("@pos");
                    }
                }
                None => {
                    let msg = format!(
                        "error: unexpected argument '{}' found\n\n{}{}",
                        a,
                        full_usage(cmd, bin),
                        error_tail()
                    );
                    return Err(CliExit::Stderr(msg, 2));
                }
            }
            continue;
        }
        if a == "--" {
            trailing = true;
            continue;
        }
        if let Some(rest) = a.strip_prefix("--") {
            let (name, inline) = match rest.find('=') {
                Some(p) => (&rest[..p], Some(rest[p + 1..].to_string())),
                None => (rest, None),
            };
            if name == "help" {
                if let Some(v) = inline {
                    let mut used = m.order.clone();
                    used.push("help");
                    let msg = format!(
                        "error: unexpected value '{}' for '--help' found; no more were expected\n\n{}{}",
                        v,
                        smart_usage(cmd, bin, &used),
                        error_tail()
                    );
                    return Err(CliExit::Stderr(msg, 2));
                }
                return Err(CliExit::Stdout(render(cmd.help, bin)));
            }
            let def = cmd.opts.iter().find(|o| o.long == name);
            let def = match def {
                Some(d) => d,
                None => {
                    let mut longs: Vec<&str> = cmd.opts.iter().map(|o| o.long).collect();
                    longs.push("help");
                    let suggestion = did_you_mean(name, longs.iter().copied());
                    let mut used = m.order.clone();
                    let mut msg = format!("error: unexpected argument '--{}' found\n\n", name);
                    match suggestion {
                        Some(s) => {
                            msg.push_str(&format!("  tip: a similar argument exists: '--{}'\n\n", s));
                            let s_static: &'static str = if s == "help" {
                                "help"
                            } else {
                                cmd.opts.iter().find(|o| o.long == s).map(|o| o.long).unwrap()
                            };
                            if !used.contains(&s_static) {
                                used.push(s_static);
                            }
                        }
                        None => {
                            if cmd.positional.is_some() {
                                msg.push_str(&format!(
                                    "  tip: to pass '--{}' as a value, use '-- --{}'\n\n",
                                    name, name
                                ));
                            }
                        }
                    }
                    msg.push_str(&smart_usage(cmd, bin, &used));
                    msg.push_str(error_tail());
                    return Err(CliExit::Stderr(msg, 2));
                }
            };
            let present = m.order.contains(&def.long);
            match def.value {
                None => {
                    if let Some(v) = inline {
                        let mut used = m.order.clone();
                        if !used.contains(&def.long) {
                            used.push(def.long);
                        }
                        let msg = format!(
                            "error: unexpected value '{}' for '--{}' found; no more were expected\n\n{}{}",
                            v,
                            def.long,
                            smart_usage(cmd, bin, &used),
                            error_tail()
                        );
                        return Err(CliExit::Stderr(msg, 2));
                    }
                    if present {
                        let msg = format!(
                            "error: the argument '{}' cannot be used multiple times\n\n{}{}",
                            opt_display(def),
                            full_usage(cmd, bin),
                            error_tail()
                        );
                        return Err(CliExit::Stderr(msg, 2));
                    }
                    m.flags.push(def.long);
                    m.order.push(def.long);
                }
                Some(_) => {
                    let val = match inline {
                        Some(v) => v,
                        None => {
                            if i < args.len() && !is_new_arg(&args[i]) {
                                i += 1;
                                args[i - 1].clone()
                            } else {
                                // A following unknown argument is reported first.
                                if i < args.len() {
                                    let next = &args[i];
                                    if let Some(err) = unknown_follow_error(cmd, next, &m, bin) {
                                        return Err(err);
                                    }
                                }
                                let msg = format!(
                                    "error: a value is required for '{}' but none was supplied\n{}",
                                    opt_display(def),
                                    error_tail()
                                );
                                return Err(CliExit::Stderr(msg, 2));
                            }
                        }
                    };
                    if present {
                        let msg = format!(
                            "error: the argument '{}' cannot be used multiple times\n\n{}{}",
                            opt_display(def),
                            full_usage(cmd, bin),
                            error_tail()
                        );
                        return Err(CliExit::Stderr(msg, 2));
                    }
                    if let Err(e) = validate_value(def.long, &val) {
                        let msg = format!(
                            "error: invalid value '{}' for '{}': {}\n{}",
                            val,
                            opt_display(def),
                            e,
                            error_tail()
                        );
                        return Err(CliExit::Stderr(msg, 2));
                    }
                    m.values.insert(def.long, val);
                    m.order.push(def.long);
                }
            }
            continue;
        }
        // Short argument(s).
        let first = a[1..].chars().next().unwrap();
        if first == 'h' {
            return Err(CliExit::Stdout(render(cmd.help, bin)));
        }
        let mut msg = format!("error: unexpected argument '-{}' found\n\n", first);
        if cmd.positional.is_some() {
            msg.push_str(&format!(
                "  tip: to pass '-{}' as a value, use '-- -{}'\n\n",
                first, first
            ));
        }
        msg.push_str(&full_usage(cmd, bin));
        msg.push_str(error_tail());
        return Err(CliExit::Stderr(msg, 2));
    }

    // Conflicts.
    if cmd.path == "format" && m.flag("check") && m.flag("diff") {
        let ci = m.order.iter().position(|x| *x == "check").unwrap();
        let di = m.order.iter().position(|x| *x == "diff").unwrap();
        let (first, second) = if ci < di { ("check", "diff") } else { ("diff", "check") };
        let used: Vec<&str> = m.order.iter().copied().filter(|x| *x != second).collect();
        let msg = format!(
            "error: the argument '--{}' cannot be used with '--{}'\n\n{}{}",
            first,
            second,
            smart_usage(cmd, bin, &used),
            error_tail()
        );
        return Err(CliExit::Stderr(msg, 2));
    }
    // Required arguments.
    let missing: Vec<&str> = cmd
        .required
        .iter()
        .copied()
        .filter(|r| !m.order.contains(r))
        .collect();
    if !missing.is_empty() {
        let mut msg = String::from("error: the following required arguments were not provided:\n");
        for r in &missing {
            let o = cmd.opts.iter().find(|o| o.long == *r).unwrap();
            msg.push_str(&format!("  {}\n", opt_display(o)));
        }
        msg.push('\n');
        msg.push_str(&required_usage(cmd, bin, &m.order.clone()));
        msg.push_str(error_tail());
        return Err(CliExit::Stderr(msg, 2));
    }
    Ok(m)
}

/// When an option is missing its value because the next token looks like a flag,
/// clap reports an unknown following flag before the missing value.
fn unknown_follow_error(cmd: &CmdDef, next: &str, m: &Matches, bin: &str) -> Option<CliExit> {
    if next == "--" {
        return None;
    }
    if let Some(rest) = next.strip_prefix("--") {
        let name = match rest.find('=') {
            Some(p) => &rest[..p],
            None => rest,
        };
        if name == "help" || cmd.opts.iter().any(|o| o.long == name) {
            return None;
        }
        let mut longs: Vec<&str> = cmd.opts.iter().map(|o| o.long).collect();
        longs.push("help");
        let suggestion = did_you_mean(name, longs.iter().copied());
        let mut used = m.order.clone();
        let mut msg = format!("error: unexpected argument '--{}' found\n\n", name);
        match suggestion {
            Some(s) => {
                msg.push_str(&format!("  tip: a similar argument exists: '--{}'\n\n", s));
                let s_static: &'static str = if s == "help" {
                    "help"
                } else {
                    cmd.opts.iter().find(|o| o.long == s).map(|o| o.long).unwrap()
                };
                if !used.contains(&s_static) {
                    used.push(s_static);
                }
            }
            None => {
                if cmd.positional.is_some() {
                    msg.push_str(&format!(
                        "  tip: to pass '--{}' as a value, use '-- --{}'\n\n",
                        name, name
                    ));
                }
            }
        }
        msg.push_str(&smart_usage(cmd, bin, &used));
        msg.push_str(error_tail());
        return Some(CliExit::Stderr(msg, 2));
    }
    let first = next[1..].chars().next()?;
    if first == 'h' {
        return None;
    }
    let mut msg = format!("error: unexpected argument '-{}' found\n\n", first);
    if cmd.positional.is_some() {
        msg.push_str(&format!(
            "  tip: to pass '-{}' as a value, use '-- -{}'\n\n",
            first, first
        ));
    }
    msg.push_str(&full_usage(cmd, bin));
    msg.push_str(error_tail());
    Some(CliExit::Stderr(msg, 2))
}

pub enum Parsed {
    Format(Matches),
    ToYaml(Matches),
    GitFilter(&'static str, Matches),
}

const TOP_SUBCOMMANDS: &[&str] = &["format", "to-yaml", "git-filter", "help"];
const GF_SUBCOMMANDS: &[&str] = &[
    "clean", "smudge", "adopt", "join", "check", "setup", "teardown", "help",
];

fn gf_cmd(name: &str) -> Option<&'static CmdDef> {
    match name {
        "clean" => Some(&GF_CLEAN),
        "smudge" => Some(&GF_SMUDGE),
        "adopt" => Some(&GF_ADOPT),
        "join" => Some(&GF_JOIN),
        "check" => Some(&GF_CHECK),
        "setup" => Some(&GF_SETUP),
        "teardown" => Some(&GF_TEARDOWN),
        _ => None,
    }
}

fn unrecognized_subcommand(name: &str, candidates: &[&str], usage: &str, suggest: bool) -> CliExit {
    let mut msg = format!("error: unrecognized subcommand '{}'\n\n", name);
    if suggest {
        if let Some(s) = did_you_mean(name, candidates.iter().copied()) {
            msg.push_str(&format!("  tip: a similar subcommand exists: '{}'\n\n", s));
        }
    }
    msg.push_str(usage);
    msg.push_str(error_tail());
    CliExit::Stderr(msg, 2)
}

fn top_unknown_arg(a: &str, bin: &str, used_help: bool) -> CliExit {
    let usage = if used_help {
        format!("Usage: {} --help <COMMAND>\n", bin)
    } else {
        format!("Usage: {} <COMMAND>\n", bin)
    };
    let display = if let Some(rest) = a.strip_prefix("--") {
        let name = match rest.find('=') {
            Some(p) => &rest[..p],
            None => rest,
        };
        format!("--{}", name)
    } else {
        format!("-{}", a[1..].chars().next().unwrap_or(' '))
    };
    let mut msg = format!("error: unexpected argument '{}' found\n\n", display);
    if let Some(rest) = a.strip_prefix("--") {
        let name = match rest.find('=') {
            Some(p) => &rest[..p],
            None => rest,
        };
        if let Some(s) = did_you_mean(name, ["help"].iter().copied()) {
            msg.push_str(&format!("  tip: a similar argument exists: '--{}'\n\n", s));
            msg.push_str(&format!("Usage: {} --help <COMMAND>\n", bin));
            msg.push_str(error_tail());
            return CliExit::Stderr(msg, 2);
        }
    }
    msg.push_str(&usage);
    msg.push_str(error_tail());
    CliExit::Stderr(msg, 2)
}

fn help_for_path(path: &[String], bin: &str) -> Result<String, CliExit> {
    if path.is_empty() {
        return Ok(render(help_text::HELP_LONG, bin));
    }
    let top_usage = format!("Usage: {} <COMMAND>\n", bin);
    match path[0].as_str() {
        "format" | "to-yaml" | "help" => {
            if path.len() > 1 {
                let usage = match path[0].as_str() {
                    "format" => format!("Usage: {} format [OPTIONS] [PATHS]...\n", bin),
                    "to-yaml" => format!("Usage: {} to-yaml [OPTIONS] --stdin-file-path <PATH>\n", bin),
                    _ => format!("Usage: {} help [COMMAND]...\n", bin),
                };
                return Err(unrecognized_subcommand(&path[1], &[], &usage, false));
            }
            Ok(render(
                match path[0].as_str() {
                    "format" => help_text::FORMAT_HELP,
                    "to-yaml" => help_text::TO_YAML_HELP,
                    _ => help_text::HELP_HELP,
                },
                bin,
            ))
        }
        "git-filter" => {
            if path.len() == 1 {
                return Ok(render(help_text::GF_LONG, bin));
            }
            match gf_cmd(&path[1]) {
                Some(c) => {
                    if path.len() > 2 {
                        let usage = format!("Usage: {} {}\n", bin, c.full_usage);
                        return Err(unrecognized_subcommand(&path[2], &[], &usage, false));
                    }
                    Ok(render(c.help, bin))
                }
                None => {
                    if path[1] == "help" && path.len() == 2 {
                        return Ok(render(help_text::GF_HELP_HELP, bin));
                    }
                    let usage = format!("Usage: {} git-filter <COMMAND>\n", bin);
                    Err(unrecognized_subcommand(&path[1], &[], &usage, false))
                }
            }
        }
        other => Err(unrecognized_subcommand(other, &[], &top_usage, false)),
    }
}

pub fn parse(args: &[String]) -> Result<Parsed, CliExit> {
    let bin = bin_name();
    // Top-level help requested with only help flags uses the canonical program name.
    if !args.is_empty() && args.iter().all(|a| a == "-h" || a == "--help") {
        let long = args.iter().any(|a| a == "--help");
        return Err(CliExit::Stdout(
            if long { help_text::TOP_LONG } else { help_text::TOP_SHORT }.to_string(),
        ));
    }
    if args.is_empty() {
        return Err(CliExit::Stderr(render(help_text::NOARGS, &bin), 2));
    }
    let mut idx = 0;
    // Leading flags at top level.
    while idx < args.len() && is_new_arg(&args[idx]) {
        let a = &args[idx];
        if a == "--" {
            idx += 1;
            break;
        }
        if a == "--help" || a == "-h" {
            let long = a == "--help";
            return Err(CliExit::Stdout(render(
                if long { help_text::HELP_LONG } else { help_text::TOP_SHORT_BIN },
                &bin,
            )));
        }
        if a.starts_with("--help=") {
            let v = &a[7..];
            let msg = format!(
                "error: unexpected value '{}' for '--help' found; no more were expected\n\nUsage: {} --help <COMMAND>\n{}",
                v,
                bin,
                error_tail()
            );
            return Err(CliExit::Stderr(msg, 2));
        }
        return Err(top_unknown_arg(a, &bin, false));
    }
    if idx >= args.len() {
        return Err(CliExit::Stderr(render(help_text::NOARGS, &bin), 2));
    }
    let sub = args[idx].as_str();
    let rest = &args[idx + 1..];
    let top_usage = format!("Usage: {} <COMMAND>\n", bin);
    match sub {
        "format" => Ok(Parsed::Format(parse_command(&FORMAT, rest, &bin)?)),
        "to-yaml" => Ok(Parsed::ToYaml(parse_command(&TO_YAML, rest, &bin)?)),
        "help" => {
            let s = help_for_path(rest, &bin)?;
            Err(CliExit::Stdout(s))
        }
        "git-filter" => {
            let mut j = 0;
            while j < rest.len() && is_new_arg(&rest[j]) {
                let a = &rest[j];
                if a == "--" {
                    j += 1;
                    break;
                }
                if a == "--help" {
                    return Err(CliExit::Stdout(render(help_text::GF_LONG, &bin)));
                }
                if a == "-h" {
                    return Err(CliExit::Stdout(render(help_text::GF_SHORT, &bin)));
                }
                let display = if let Some(r) = a.strip_prefix("--") {
                    let name = match r.find('=') {
                        Some(p) => &r[..p],
                        None => r,
                    };
                    format!("--{}", name)
                } else {
                    format!("-{}", a[1..].chars().next().unwrap_or(' '))
                };
                let msg = format!(
                    "error: unexpected argument '{}' found\n\nUsage: {} git-filter <COMMAND>\n{}",
                    display,
                    bin,
                    error_tail()
                );
                return Err(CliExit::Stderr(msg, 2));
            }
            if j >= rest.len() {
                return Err(CliExit::Stderr(render(help_text::GF_SHORT, &bin), 2));
            }
            let name = rest[j].as_str();
            let rest2 = &rest[j + 1..];
            if name == "help" {
                let mut path = vec!["git-filter".to_string()];
                path.extend(rest2.iter().cloned());
                let s = help_for_path(&path, &bin)?;
                return Err(CliExit::Stdout(s));
            }
            match gf_cmd(name) {
                Some(c) => {
                    let m = parse_command(c, rest2, &bin)?;
                    let key: &'static str = match name {
                        "clean" => "clean",
                        "smudge" => "smudge",
                        "adopt" => "adopt",
                        "join" => "join",
                        "check" => "check",
                        "setup" => "setup",
                        _ => "teardown",
                    };
                    Ok(Parsed::GitFilter(key, m))
                }
                None => {
                    let usage = format!("Usage: {} git-filter <COMMAND>\n", bin);
                    Err(unrecognized_subcommand(name, GF_SUBCOMMANDS, &usage, true))
                }
            }
        }
        other => Err(unrecognized_subcommand(other, TOP_SUBCOMMANDS, &top_usage, true)),
    }
}
