mod ast;
mod builtins;
mod bundle;
mod check_ce;
mod check_decl;
mod codec;
mod check_expr;
mod diag;
mod exhaust;
mod fusion;
mod holes;
mod ide;
mod infer;
mod json;
mod kernel;
mod lexer;
mod lower;
mod lsp;
mod native;
mod lower2;
mod lower3;
mod lower4;
mod lower5;
mod parser;
mod pkg;
mod printer;
mod project;
mod py;
mod repl;
mod resolve;
mod runtime;
mod session;
mod shadow;
mod source;
mod types;

use std::path::{Path, PathBuf};
use std::process::exit;

pub const VERSION: &str = "0.10.0";

const USAGE: &str = "pyfun 0.10.0

usage:
  pyfun check   <file.pyfun>                type-check, report diagnostics
  pyfun compile <file.pyfun> [-o <out>]     type-check then lower to Python
                                            (-o is a file for one module, a dir for a project)
                [--target 3.11|3.12]        emission target (default 3.12; 3.11 avoids
                                            PEP 701 f-strings so the output runs on PyPy)
                [--native]                  lower matches on your own types to isinstance
                                            ladders, the form mypyc compiles
  pyfun run     <file.pyfun> [--] [args...] compile then execute with Python
  pyfun build   --native <file.pyfun> -o <dir>  compile to a C extension with mypyc;
                                            run the result with `python <dir>`
                                            (args after the path go to the program's sys.argv)
  pyfun parse   <file.pyfun>                canonical pretty-print
  pyfun bundle  <file.pyfun> -o <dir>       a static web page running the program
                [--asset <file>]... [--page <fragment.html>]   on Pyodide (CPython in WebAssembly)
  pyfun add     <package>...                install a Pyfun façade package and vendor
                                            its .pyfun files (records it in pyfun.toml)
  pyfun install                             install every façade pyfun.toml lists
  pyfun remove  <package>...                drop a façade from pyfun.toml and the project
  pyfun lsp                                 run the language server (stdio)
  pyfun repl                                interactive read-eval-print loop
  pyfun kernel-engine                       session engine for the Jupyter kernel (stdio)
  pyfun --version                           print the compiler version
  pyfun <file.pyfun>                        shorthand for `compile`
";

fn fail(msg: &str) -> ! {
    eprintln!("{}", msg);
    exit(1);
}

fn load_source(path: &str) -> String {
    match project::read_source(Path::new(path)) {
        Ok(s) => s,
        Err(e) => fail(&e),
    }
}

/// Load and check; on failure print the report and exit.
fn load_checked(path: &str, first_only: bool) -> project::Checked {
    let src = load_source(path);
    let mods = match project::load(Path::new(path), src) {
        Ok(m) => m,
        Err(project::LoadError::Msg(m)) => fail(&m),
        Err(project::LoadError::Parse { src, diag, .. }) => {
            eprintln!("{}", diag::render(&src, &diag));
            exit(1);
        }
    };
    match project::check_all(mods, first_only) {
        Ok(c) => c,
        Err(report) => {
            eprint!("{}", report);
            exit(1);
        }
    }
}

struct CompileArgs {
    file: String,
    out: Option<String>,
    py311: bool,
    native: bool,
}

fn parse_compile_args(cmd: &str, args: &[String]) -> CompileArgs {
    let mut file: Option<String> = None;
    let mut out = None;
    let mut py311 = false;
    let mut native = false;
    let mut i = 0;
    while i < args.len() {
        let a = &args[i];
        match a.as_str() {
            "-o" => {
                if i + 1 >= args.len() {
                    fail("error: `-o` needs a path");
                }
                out = Some(args[i + 1].clone());
                i += 2;
                continue;
            }
            "--target" => {
                if i + 1 >= args.len() {
                    fail("error: `--target` needs a version (3.11 or 3.12)");
                }
                match args[i + 1].as_str() {
                    "3.11" => py311 = true,
                    "3.12" => py311 = false,
                    other => fail(&format!("error: `--target` must be 3.11 or 3.12, got `{}`", other)),
                }
                i += 2;
                continue;
            }
            "--native" => {
                native = true;
            }
            _ => {
                if file.is_none() {
                    file = Some(a.clone());
                } else {
                    fail(&format!("error: unexpected argument `{}`", a));
                }
            }
        }
        i += 1;
    }
    let Some(file) = file else { fail(&format!("error: `{}` needs a file path", cmd)) };
    CompileArgs { file, out, py311, native }
}

fn cmd_check(args: &[String]) {
    let Some(path) = args.first() else { fail("error: `check` needs a file path") };
    let ck = load_checked(path, false);
    let n = ck.mods.len();
    if n > 1 {
        eprintln!("ok: no type errors ({} modules)", n);
    } else {
        eprintln!("ok: no type errors");
    }
}

fn cmd_compile(args: &[String]) {
    let a = parse_compile_args("compile", args);
    let ck = load_checked(&a.file, true);
    let em = project::emit_all(&ck, &project::EmitOpts { py311: a.py311, native: a.native });
    let project = ck.mods.len() > 1;
    match (&a.out, project) {
        (None, false) => print!("{}", em.files[0].1),
        (None, true) => {
            for (f, text) in &em.files {
                println!("# ==== {} ====", f);
                print!("{}", text);
                println!();
            }
        }
        (Some(o), false) => {
            if let Err(e) = std::fs::write(o, &em.files[0].1) {
                fail(&format!("error: cannot write {}: {}", o, e));
            }
            eprintln!("wrote {}", o);
        }
        (Some(o), true) => {
            if let Err(e) = std::fs::create_dir_all(o) {
                fail(&format!("error: cannot create {}: {}", o, e));
            }
            for (f, text) in &em.files {
                let p = Path::new(o).join(f);
                if let Err(e) = std::fs::write(&p, text) {
                    fail(&format!("error: cannot write {}: {}", p.display(), e));
                }
            }
            eprintln!("wrote {} files to {}", em.files.len(), o);
        }
    }
}

/// The Python interpreter to use: PYFUN_PYTHON, else `python`, else `python3`.
pub fn find_python(honor_env: bool) -> Result<String, String> {
    if honor_env {
        if let Ok(p) = std::env::var("PYFUN_PYTHON") {
            if !p.is_empty() {
                return Ok(p);
            }
        }
    }
    for cand in ["python", "python3"] {
        let ok = std::process::Command::new(cand)
            .arg("--version")
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false);
        if ok {
            return Ok(cand.to_string());
        }
    }
    Err("no Python interpreter found on PATH (tried `python`, `python3`)".to_string())
}

fn cmd_run(args: &[String]) {
    let Some(path) = args.first() else { fail("error: `run` needs a file path") };
    let mut rest: Vec<String> = args[1..].to_vec();
    if rest.first().map(|s| s.as_str()) == Some("--") {
        rest.remove(0);
    }
    let ck = load_checked(path, true);
    let em = project::emit_all(&ck, &project::EmitOpts { py311: false, native: false });
    let python = match find_python(true) {
        Ok(p) => p,
        Err(e) => fail(&format!("error: {}", e)),
    };
    let dir: PathBuf = std::env::temp_dir().join(format!("pyfun_run_{}", std::process::id()));
    let _ = std::fs::create_dir_all(&dir);
    let project = ck.mods.len() > 1;
    let main_file = if project { format!("{}.py", project::py_module_of(&ck.mods.last().unwrap().file)) } else { "_pyfun_main.py".to_string() };
    if project {
        for (f, text) in &em.files {
            let _ = std::fs::write(dir.join(f), text);
        }
    } else {
        let _ = std::fs::write(dir.join(&main_file), &em.files[0].1);
    }
    let script = dir.join(&main_file);
    let status = std::process::Command::new(&python).arg(&script).args(&rest).status();
    let _ = std::fs::remove_dir_all(&dir);
    match status {
        Ok(s) => exit(if s.success() { 0 } else { 1 }),
        Err(e) => fail(&format!("error: `{}` did not finish: {}", python, e)),
    }
}

fn cmd_parse(args: &[String]) {
    let Some(path) = args.first() else { fail("error: `parse` needs a file path") };
    let src = load_source(path);
    match parser::parse_program(&src) {
        Ok(p) => print!("{}", printer::print_program(&p)),
        Err(d) => {
            eprintln!("{}", diag::render(&src, &d));
            exit(1);
        }
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() || args[0] == "-h" || args[0] == "--help" {
        eprint!("{}", USAGE);
        exit(0);
    }
    let rest = &args[1..];
    match args[0].as_str() {
        "--version" | "-V" | "version" => println!("pyfun {}", VERSION),
        "check" => cmd_check(rest),
        "compile" => cmd_compile(rest),
        "run" => cmd_run(rest),
        "parse" => cmd_parse(rest),
        "bundle" => bundle::cmd_bundle(rest),
        "build" => bundle::cmd_build(rest),
        "add" => pkg::cmd_add(rest),
        "install" => pkg::cmd_install(rest),
        "remove" => pkg::cmd_remove(rest),
        "repl" => repl::run_repl(),
        "kernel-engine" => kernel::run_kernel(),
        "lsp" => lsp::run_lsp(),
        _ => cmd_compile(&args[..1]),
    }
}
