//! bimcraft-cli: the command line of a BIM modeler.

#[macro_use]
pub mod json;
pub mod catalog;
pub mod check;
pub mod cloud;
pub mod commands;
pub mod ifc;
pub mod inflate;
pub mod inspect;
pub mod load;
pub mod model;
pub mod project;
pub mod rvt;
pub mod rand;
pub mod script;
pub mod session;
pub mod templates;
pub mod util;

use std::process::exit;

pub const VERSION: &str = "0.10.0";

fn usage_exit(prefix: Option<String>) -> ! {
    if let Some(p) = prefix {
        eprint!("{}\n\n", p);
    }
    eprint!("{}", catalog::USAGE);
    exit(1);
}

enum Action {
    Open(String),
    Sample,
    Highrise,
    Cmd(String),
    Script(String),
    Save(String),
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        usage_exit(None);
    }
    match args[0].as_str() {
        "--version" | "-V" if args.len() == 1 => {
            println!("bimcraft-cli {}", VERSION);
        }
        "commands" if args.len() == 1 => {
            let v = json::parse(catalog::CATALOG).unwrap();
            println!("{}", v.to_pretty());
        }
        "info" if args.len() == 2 => cmd_info(&args[1]),
        "convert" if args.len() == 3 => cmd_convert(&args[1], &args[2]),
        "run" => cmd_run(&args[1..]),
        "mcp" => commands::mcp_main(&args[1..]),
        _ => usage_exit(None),
    }
}

fn cmd_run(args: &[String]) {
    let mut actions = Vec::new();
    let mut i = 0;
    while i < args.len() {
        let a = &args[i];
        match a.as_str() {
            "--sample" => actions.push(Action::Sample),
            "--highrise" => actions.push(Action::Highrise),
            "--cmd" | "--script" | "--save" => {
                if i + 1 >= args.len() {
                    usage_exit(Some(format!("{} needs a value", a)));
                }
                let v = args[i + 1].clone();
                i += 1;
                actions.push(match a.as_str() {
                    "--cmd" => Action::Cmd(v),
                    "--script" => Action::Script(v),
                    _ => Action::Save(v),
                });
            }
            _ if a.starts_with("--") => usage_exit(Some(format!("unknown option `{}`", a))),
            _ => actions.push(Action::Open(a.clone())),
        }
        i += 1;
    }
    let mut s = session::Session::new();
    for act in actions {
        match act {
            Action::Open(path) => match commands::open_path(&mut s, &path) {
                Ok(v) => println!("{}", v.sorted().to_compact()),
                Err(e) => {
                    // a Revit import's error is a whole message, the path first
                    if rvt::is_revit_path(&path) {
                        eprintln!("{}", e);
                    } else {
                        eprintln!("open: {}", e);
                    }
                    exit(1);
                }
            },
            Action::Sample => {
                if let Err(e) = commands::build_sample(&mut s) {
                    eprintln!("{}", e);
                    exit(1);
                }
            }
            Action::Highrise => match commands::build_highrise(&mut s, 20) {
                Ok(v) => println!("{}", v.sorted().to_compact()),
                Err(e) => {
                    eprintln!("{}", e);
                    exit(1);
                }
            },
            Action::Cmd(text) => run_script_text(&mut s, &text),
            Action::Script(path) => match std::fs::read(&path) {
                Ok(bytes) => {
                    let text = String::from_utf8_lossy(&bytes).to_string();
                    run_script_text(&mut s, &text)
                }
                Err(e) => {
                    eprintln!("{}: {}", path, commands::io_err(&e));
                    exit(1);
                }
            },
            Action::Save(path) => {
                let p = json::Value::Obj({
                    let mut m = json::Map::new();
                    m.insert("path", json::Value::s(&path));
                    m
                });
                match s.execute("save", &p) {
                    Ok(v) => println!("{}", v.sorted().to_compact()),
                    Err(e) => {
                        eprintln!("save: {}", e);
                        exit(1);
                    }
                }
            }
        }
    }
}

fn run_script_text(s: &mut session::Session, text: &str) {
    let lines = match script::parse(text) {
        Ok(l) => l,
        Err(e) => {
            eprintln!("{}", e);
            exit(1);
        }
    };
    for l in lines {
        match s.execute(&l.id, &l.params) {
            Ok(v) => println!("{}", v.sorted().to_compact()),
            Err(e) => {
                eprintln!("line {} ({}): {}", l.line, l.id, e);
                exit(1);
            }
        }
    }
}

fn cmd_info(path: &str) {
    match commands::info(path) {
        Ok(v) => println!("{}", v.sorted().to_pretty()),
        Err(e) => {
            eprintln!("{}", e);
            exit(1);
        }
    }
}

fn cmd_convert(input: &str, output: &str) {
    let mut s = session::Session::new();
    match commands::open_path(&mut s, input) {
        Ok(_) => {}
        Err(e) => {
            // a Revit import's error is a whole message, the path first
            if rvt::is_revit_path(input) {
                eprintln!("{}", e);
            } else {
                eprintln!("open: {}", e);
            }
            exit(1);
        }
    }
    let mut m = json::Map::new();
    m.insert("path", json::Value::s(output));
    match s.execute("save", &json::Value::Obj(m)) {
        Ok(v) => println!("{}", v.sorted().to_compact()),
        Err(e) => {
            eprintln!("save: {}", e);
            exit(1);
        }
    }
}
