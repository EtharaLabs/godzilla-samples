#![allow(dead_code)]
mod cli;
mod config;
mod diff;
mod format_cmd;
mod gitfilter;
mod help_text;
mod json;
mod markdown;
mod options;
mod source;
mod template;
mod toml;
mod walk;
mod yaml;

use std::io::Write;

fn main() {
    let args: Vec<String> = std::env::args_os()
        .skip(1)
        .map(|a| a.to_string_lossy().into_owned())
        .collect();
    let code = match cli::parse(&args) {
        Ok(cli::Parsed::Format(m)) => format_cmd::run_format(&m),
        Ok(cli::Parsed::ToYaml(m)) => json::run_to_yaml(&m),
        Ok(cli::Parsed::GitFilter(name, m)) => gitfilter::run(name, &m),
        Err(cli::CliExit::Stdout(s)) => {
            let mut out = std::io::stdout();
            let _ = out.write_all(s.as_bytes());
            let _ = out.flush();
            0
        }
        Err(cli::CliExit::Stderr(s, code)) => {
            let mut err = std::io::stderr();
            let _ = err.write_all(s.as_bytes());
            let _ = err.flush();
            code
        }
    };
    std::process::exit(code);
}
