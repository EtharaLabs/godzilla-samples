// Command-line parsing, mirroring clap's behaviour and messages.

pub static HELP_MAIN: &str = include_str!("../data/help/main.txt");
pub static HELP_FMT: &str = include_str!("../data/help/fmt.txt");
pub static HELP_SERVE: &str = include_str!("../data/help/serve.txt");
pub static HELP_DESUGAR: &str = include_str!("../data/help/desugar.txt");
pub static HELP_HIGHLIGHT: &str = include_str!("../data/help/highlight.txt");
pub static HELP_THEME: &str = include_str!("../data/help/theme.txt");
pub static HELP_HELP: &str = include_str!("../data/help/help.txt");
pub static HIGHLIGHT_CSS: &str = include_str!("../data/help/highlight.css");

pub enum Cmd {
    Compile { input: String },
    Fmt { input: String, check: bool, stdout: bool },
    Serve,
    Desugar { input: String },
    Highlight { input: Option<String>, css: bool },
    Theme { name: Option<String> },
}

pub struct Parsed {
    pub cmd: Cmd,
    pub opts: crate::Options,
}

pub enum Outcome {
    Run(Parsed),
    Print(String), // help / version text on stdout, exit 0
    Fail(String),  // error text on stderr, exit 3
}

struct OptDef {
    long: &'static str,
    short: Option<char>,
    value: Option<&'static str>, // value name when the option takes one
}

const MAIN_OPTS: &[OptDef] = &[
    OptDef { long: "output", short: Some('o'), value: Some("OUTPUT") },
    OptDef { long: "format", short: None, value: Some("FORMAT") },
    OptDef { long: "static", short: None, value: None },
    OptDef { long: "embed-font", short: None, value: None },
    OptDef { long: "check", short: None, value: None },
    OptDef { long: "json", short: None, value: None },
    OptDef { long: "theme", short: None, value: Some("NAME|FILE|A/B") },
    OptDef { long: "watch", short: None, value: None },
    OptDef { long: "no-fs", short: None, value: None },
    OptDef { long: "no-warn", short: None, value: None },
    OptDef { long: "strict", short: None, value: None },
    OptDef { long: "help", short: Some('h'), value: None },
    OptDef { long: "version", short: Some('V'), value: None },
];

const SUBCOMMANDS: &[&str] = &["fmt", "serve", "desugar", "highlight", "theme", "help"];

fn jaro(a: &str, b: &str) -> f64 {
    let a: Vec<char> = a.chars().collect();
    let b: Vec<char> = b.chars().collect();
    if a.is_empty() && b.is_empty() {
        return 1.0;
    }
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let range = (a.len().max(b.len()) / 2).saturating_sub(1);
    let mut am = vec![false; a.len()];
    let mut bm = vec![false; b.len()];
    let mut m = 0usize;
    for i in 0..a.len() {
        let lo = i.saturating_sub(range);
        let hi = (i + range + 1).min(b.len());
        for j in lo..hi {
            if !bm[j] && a[i] == b[j] {
                am[i] = true;
                bm[j] = true;
                m += 1;
                break;
            }
        }
    }
    if m == 0 {
        return 0.0;
    }
    let mut t = 0usize;
    let mut k = 0usize;
    for i in 0..a.len() {
        if am[i] {
            while !bm[k] {
                k += 1;
            }
            if a[i] != b[k] {
                t += 1;
            }
            k += 1;
        }
    }
    let m = m as f64;
    (m / a.len() as f64 + m / b.len() as f64 + (m - t as f64 / 2.0) / m) / 3.0
}

fn suggest(given: &str, cands: &[&str]) -> Option<String> {
    let mut best: Option<(f64, &str)> = None;
    for c in cands {
        let s = jaro(given, c);
        if s > 0.7 && best.map(|b| s > b.0).unwrap_or(true) {
            best = Some((s, c));
        }
    }
    best.map(|b| b.1.to_string())
}

pub fn sub_help(bin: &str, text: &str) -> String {
    text.replace("{bin}", bin)
}

fn generic_usage(bin: &str) -> String {
    format!("Usage: {} [OPTIONS] <INPUT>\n       {} <COMMAND>\n", bin, bin)
}

fn fail_with_usage(msg: &str, usage: &str) -> Outcome {
    Outcome::Fail(format!("error: {}\n\n{}\nFor more information, try '--help'.\n", msg, usage))
}

pub fn parse(args: &[String]) -> Outcome {
    let bin = std::path::Path::new(&args[0]).file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or_else(|| "lini".into());
    let mut opts = crate::Options { format: "svg".into(), ..Default::default() };
    let mut input: Option<String> = None;
    let mut seen: Vec<&'static str> = Vec::new(); // long names in order seen
    let mut i = 1;
    let mut only_pos = false;
    let mut want_help = false;
    let mut want_version = false;
    let used_usage = |seen: &Vec<&'static str>, extra: Option<&str>| -> String {
        let mut parts = vec![bin.clone()];
        for d in MAIN_OPTS {
            if seen.contains(&d.long) || extra == Some(d.long) {
                match d.value {
                    Some(v) => parts.push(format!("--{} <{}>", d.long, v)),
                    None => parts.push(format!("--{}", d.long)),
                }
            }
        }
        parts.push("<INPUT>".into());
        format!("Usage: {}\n", parts.join(" "))
    };
    while i < args.len() {
        let a = args[i].clone();
        i += 1;
        if !only_pos && a == "--" {
            only_pos = true;
            continue;
        }
        if !only_pos && a.starts_with("--") {
            let body = &a[2..];
            let (name, inline_val) = match body.find('=') {
                Some(p) => (&body[..p], Some(body[p + 1..].to_string())),
                None => (body, None),
            };
            let def = match MAIN_OPTS.iter().find(|d| d.long == name) {
                Some(d) => d,
                None => {
                    let names: Vec<&str> = MAIN_OPTS.iter().map(|d| d.long).collect();
                    if let Some(s) = suggest(name, &names) {
                        let sname = MAIN_OPTS.iter().find(|d| d.long == s).unwrap().long;
                        return Outcome::Fail(format!(
                            "error: unexpected argument '{}' found\n\n  tip: a similar argument exists: '--{}'\n\n{}\nFor more information, try '--help'.\n",
                            a,
                            s,
                            used_usage(&seen, Some(sname))
                        ));
                    }
                    return Outcome::Fail(format!(
                        "error: unexpected argument '{}' found\n\n  tip: to pass '{}' as a value, use '-- {}'\n\n{}\nFor more information, try '--help'.\n",
                        a,
                        a,
                        a,
                        generic_usage(&bin)
                    ));
                }
            };
            if let Some(o) = handle_opt(def, inline_val, args, &mut i, &mut opts, &mut seen, &mut want_help, &mut want_version, &bin) {
                return o;
            }
            continue;
        }
        if !only_pos && a.starts_with('-') && a.len() > 1 {
            let chars: Vec<char> = a[1..].chars().collect();
            let mut k = 0;
            while k < chars.len() {
                let c = chars[k];
                k += 1;
                let def = match MAIN_OPTS.iter().find(|d| d.short == Some(c)) {
                    Some(d) => d,
                    None => {
                        let shown = format!("-{}", c);
                        return Outcome::Fail(format!(
                            "error: unexpected argument '{}' found\n\n  tip: to pass '{}' as a value, use '-- {}'\n\n{}\nFor more information, try '--help'.\n",
                            shown,
                            shown,
                            shown,
                            generic_usage(&bin)
                        ));
                    }
                };
                if def.value.is_some() {
                    let rest: String = chars[k..].iter().collect();
                    let iv = if rest.is_empty() { None } else { Some(rest) };
                    if let Some(o) = handle_opt(def, iv, args, &mut i, &mut opts, &mut seen, &mut want_help, &mut want_version, &bin) {
                        return o;
                    }
                    break;
                }
                if let Some(o) = handle_opt(def, None, args, &mut i, &mut opts, &mut seen, &mut want_help, &mut want_version, &bin) {
                    return o;
                }
                if want_help || want_version {
                    break;
                }
            }
            if want_help {
                return Outcome::Print(sub_help(&bin, HELP_MAIN));
            }
            if want_version {
                return Outcome::Print("lini 1.1.0\n".into());
            }
            continue;
        }
        // positional
        if input.is_none() && !only_pos && seen.is_empty() && SUBCOMMANDS.contains(&a.as_str()) {
            return parse_sub(&bin, &a, &args[i..]);
        }
        if input.is_none() {
            input = Some(a);
        } else {
            return fail_with_usage(&format!("the subcommand '{}' cannot be used with '<INPUT>'", a), &generic_usage(&bin));
        }
        if want_help || want_version {
            break;
        }
    }
    if want_help {
        return Outcome::Print(sub_help(&bin, HELP_MAIN));
    }
    if want_version {
        return Outcome::Print("lini 1.1.0\n".into());
    }
    if opts.no_warn && opts.strict {
        let first = if seen.iter().position(|s| *s == "no-warn") < seen.iter().position(|s| *s == "strict") { ("no-warn", "strict") } else { ("strict", "no-warn") };
        return Outcome::Fail(format!(
            "error: the argument '--{}' cannot be used with '--{}'\n\nUsage: {} --{} <INPUT>\n\nFor more information, try '--help'.\n",
            first.0, first.1, bin, first.0
        ));
    }
    let input = match input {
        Some(x) => x,
        None => {
            return Outcome::Fail(format!(
                "error: the following required arguments were not provided:\n  <INPUT>\n\n{}\nFor more information, try '--help'.\n",
                used_usage(&seen, None)
            ));
        }
    };
    if seen.contains(&"watch") && opts.output.is_none() {
        let mut s2 = seen.clone();
        s2.push("output");
        return Outcome::Fail(format!(
            "error: the following required arguments were not provided:\n  --output <OUTPUT>\n\n{}\nFor more information, try '--help'.\n",
            used_usage(&s2, None)
        ));
    }
    Outcome::Run(Parsed { cmd: Cmd::Compile { input }, opts })
}

#[allow(clippy::too_many_arguments)]
fn handle_opt(
    def: &OptDef,
    inline_val: Option<String>,
    args: &[String],
    i: &mut usize,
    opts: &mut crate::Options,
    seen: &mut Vec<&'static str>,
    want_help: &mut bool,
    want_version: &mut bool,
    bin: &str,
) -> Option<Outcome> {
    if def.long == "help" {
        *want_help = true;
        return Some(Outcome::Print(sub_help(bin, HELP_MAIN)));
    }
    if def.long == "version" {
        *want_version = true;
        return Some(Outcome::Print("lini 1.1.0\n".into()));
    }
    if seen.contains(&def.long) {
        let shown = match def.value {
            Some(v) => format!("--{} <{}>", def.long, v),
            None => format!("--{}", def.long),
        };
        return Some(fail_with_usage(&format!("the argument '{}' cannot be used multiple times", shown), &generic_usage(bin)));
    }
    seen.push(def.long);
    let val = if def.value.is_some() {
        match inline_val {
            Some(v) => Some(v),
            None => {
                if *i < args.len() {
                    let v = args[*i].clone();
                    *i += 1;
                    Some(v)
                } else {
                    return Some(Outcome::Fail(format!(
                        "error: a value is required for '--{} <{}>' but none was supplied\n\nFor more information, try '--help'.\n",
                        def.long,
                        def.value.unwrap()
                    )));
                }
            }
        }
    } else {
        None
    };
    match def.long {
        "output" => opts.output = val,
        "format" => opts.format = val.unwrap_or_default(),
        "theme" => opts.theme = val,
        "static" => opts.static_ = true,
        "embed-font" => opts.embed_font = true,
        "check" => opts.check = true,
        "json" => opts.json = true,
        "watch" => opts.watch = true,
        "no-fs" => opts.no_fs = true,
        "no-warn" => opts.no_warn = true,
        "strict" => opts.strict = true,
        _ => {}
    }
    None
}

fn sub_usage_err(bin: &str, sub: &str, used: &[&str], required: &str) -> Outcome {
    let mut parts = vec![bin.to_string(), sub.to_string()];
    for u in used {
        parts.push(u.to_string());
    }
    parts.push(required.to_string());
    Outcome::Fail(format!(
        "error: the following required arguments were not provided:\n  {}\n\nUsage: {}\n\nFor more information, try '--help'.\n",
        required,
        parts.join(" ")
    ))
}

fn unexpected(bin: &str, arg: &str, usage: &str) -> Outcome {
    let _ = bin;
    if arg.starts_with('-') && arg.len() > 1 {
        Outcome::Fail(format!(
            "error: unexpected argument '{}' found\n\n  tip: to pass '{}' as a value, use '-- {}'\n\n{}\nFor more information, try '--help'.\n",
            arg, arg, arg, usage
        ))
    } else {
        Outcome::Fail(format!("error: unexpected argument '{}' found\n\n{}\nFor more information, try '--help'.\n", arg, usage))
    }
}

fn parse_sub(bin: &str, sub: &str, rest: &[String]) -> Outcome {
    let opts = crate::Options { format: "svg".into(), ..Default::default() };
    match sub {
        "fmt" => {
            let usage = format!("Usage: {} fmt [OPTIONS] <INPUT>\n", bin);
            let mut check = false;
            let mut stdout = false;
            let mut used: Vec<&str> = Vec::new();
            let mut input = None;
            let mut only_pos = false;
            for a in rest {
                if !only_pos && a == "--" {
                    only_pos = true;
                    continue;
                }
                if !only_pos && (a == "-h" || a == "--help") {
                    return Outcome::Print(sub_help(bin, HELP_FMT));
                }
                if !only_pos && a == "--check" {
                    check = true;
                    used.push("--check");
                    continue;
                }
                if !only_pos && a == "--stdout" {
                    stdout = true;
                    used.push("--stdout");
                    continue;
                }
                if !only_pos && a.starts_with('-') && a != "-" {
                    return unexpected(bin, a, &usage);
                }
                if input.is_none() {
                    input = Some(a.clone());
                } else {
                    return unexpected(bin, a, &usage);
                }
            }
            match input {
                Some(input) => Outcome::Run(Parsed { cmd: Cmd::Fmt { input, check, stdout }, opts }),
                None => sub_usage_err(bin, "fmt", &used, "<INPUT>"),
            }
        }
        "desugar" => {
            let usage = format!("Usage: {} desugar <INPUT>\n", bin);
            let mut input = None;
            // `--` ends the options: what follows is positional
            let mut only_pos = false;
            for a in rest {
                if !only_pos && a == "--" {
                    only_pos = true;
                    continue;
                }
                if !only_pos && (a == "-h" || a == "--help") {
                    return Outcome::Print(sub_help(bin, HELP_DESUGAR));
                }
                if !only_pos && a.starts_with('-') && a != "-" {
                    return unexpected(bin, a, &usage);
                }
                if input.is_none() {
                    input = Some(a.clone());
                } else if only_pos {
                    return Outcome::Fail(format!(
                        "error: unexpected argument '{}' found\n\n{}\nFor more information, try '--help'.\n",
                        a, usage
                    ));
                } else {
                    return unexpected(bin, a, &usage);
                }
            }
            match input {
                Some(input) => Outcome::Run(Parsed { cmd: Cmd::Desugar { input }, opts }),
                None => sub_usage_err(bin, "desugar", &[], "<INPUT>"),
            }
        }
        "highlight" => {
            let usage = format!("Usage: {} highlight [OPTIONS] [INPUT]\n", bin);
            let mut input = None;
            let mut css = false;
            for a in rest {
                if a == "-h" || a == "--help" {
                    return Outcome::Print(sub_help(bin, HELP_HIGHLIGHT));
                }
                if a == "--css" {
                    css = true;
                    continue;
                }
                if a.starts_with('-') && a != "-" {
                    return unexpected(bin, a, &usage);
                }
                if input.is_none() {
                    input = Some(a.clone());
                } else {
                    return unexpected(bin, a, &usage);
                }
            }
            if !css && input.is_none() {
                return Outcome::Fail("error: an input file is required — or '--css' for the palette\n".into());
            }
            Outcome::Run(Parsed { cmd: Cmd::Highlight { input, css }, opts })
        }
        "theme" => {
            let usage = format!("Usage: {} theme [NAME]\n", bin);
            let mut name = None;
            for a in rest {
                if a == "-h" || a == "--help" {
                    return Outcome::Print(sub_help(bin, HELP_THEME));
                }
                if a.starts_with('-') && a != "-" {
                    return unexpected(bin, a, &usage);
                }
                if name.is_none() {
                    name = Some(a.clone());
                } else {
                    return unexpected(bin, a, &usage);
                }
            }
            Outcome::Run(Parsed { cmd: Cmd::Theme { name }, opts })
        }
        "serve" => {
            for a in rest {
                if a == "-h" || a == "--help" {
                    return Outcome::Print(sub_help(bin, HELP_SERVE));
                }
            }
            Outcome::Run(Parsed { cmd: Cmd::Serve, opts })
        }
        "help" => {
            if rest.is_empty() {
                return Outcome::Print(sub_help(bin, HELP_MAIN));
            }
            let first = rest[0].as_str();
            let text = match first {
                "fmt" => HELP_FMT,
                "serve" => HELP_SERVE,
                "desugar" => HELP_DESUGAR,
                "highlight" => HELP_HIGHLIGHT,
                "theme" => HELP_THEME,
                "help" => HELP_HELP,
                _ => {
                    return fail_with_usage(&format!("unrecognized subcommand '{}'", first), &generic_usage(bin));
                }
            };
            if rest.len() > 1 {
                let u = match first {
                    "fmt" => format!("Usage: {} fmt [OPTIONS] <INPUT>\n", bin),
                    "desugar" => format!("Usage: {} desugar <INPUT>\n", bin),
                    "highlight" => format!("Usage: {} highlight [OPTIONS] [INPUT]\n", bin),
                    "theme" => format!("Usage: {} theme [NAME]\n", bin),
                    "serve" => format!("Usage: {} serve [OPTIONS] [PATH]\n", bin),
                    _ => format!("Usage: {} help [COMMAND]...\n", bin),
                };
                return fail_with_usage(&format!("unrecognized subcommand '{}'", rest[1]), &u);
            }
            Outcome::Print(sub_help(bin, text))
        }
        _ => Outcome::Fail(String::new()),
    }
}
