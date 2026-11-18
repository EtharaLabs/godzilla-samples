mod ast;
mod chart;
mod cli;
mod color;
mod compile;
mod desugar;
mod format;
mod highlight;
mod icon;
mod image;
mod diag;
mod drawing;
mod eval;
mod font;
mod layout;
mod links;
mod geom;
mod lexer;
mod markers;
mod outline;
mod page;
mod paint;
mod parser;
mod render;
mod route;
mod scene;
mod scoped;
mod sketch;
mod style;
mod table;
mod theme;
mod types;
mod util;
mod validate;
mod wires;

use std::io::{Read, Write};

#[derive(Default, Clone)]
pub struct Options {
    pub output: Option<String>,
    pub format: String,
    pub static_: bool,
    pub embed_font: bool,
    pub check: bool,
    pub json: bool,
    pub theme: Option<String>,
    pub no_fs: bool,
    pub no_warn: bool,
    pub strict: bool,
    pub watch: bool,
}

fn read_input(path: &str) -> Result<String, String> {
    if path == "-" {
        let mut s = String::new();
        std::io::stdin().read_to_string(&mut s).map_err(|e| format!("error: failed to read stdin: {}", e))?;
        return Ok(s);
    }
    match std::fs::read(path) {
        Ok(b) => String::from_utf8(b).map_err(|_| format!("error: {}: stream did not contain valid UTF-8", path)),
        Err(e) => Err(format!("error: {}: {}", path, e)),
    }
}

pub fn compile_src(src: &str, file: &str, opts: &Options) -> Result<(String, Vec<diag::Diag>), (diag::Diag, Vec<diag::Diag>)> {
    let (doc, _comments) = parser::parse(src).map_err(|e| (e, vec![]))?;
    let sheet = scene::build_sheet(&doc).map_err(|e| (e, vec![]))?;
    // the V-phase: every declaration checked, all diagnostics kept
    let early = validate::validate(&doc, &sheet);
    if let Some(e) = early.iter().find(|d| d.severity == diag::Severity::Error) {
        return Err((e.clone(), vec![]));
    }
    // a failure later still reports the warnings gathered so far
    let fail = |e: diag::Diag, w: &[diag::Diag]| (e, w.to_vec());
    validate::check_types(&doc, &sheet).map_err(|e| fail(e, &early))?;
    validate::resolve(&doc, &sheet).map_err(|e| fail(e, &early))?;
    let root = compile::root_decls_node(&sheet);
    let mut b = scene::Builder::new(&sheet, src);
    b.add(root, None);
    let mut seen = early.clone();
    b.build_stmts(&doc.stmts, 0).map_err(|e| {
        seen.extend(b.warnings.iter().cloned());
        fail(e, &seen)
    })?;
    icon::validate(&b.nodes, b.sheet, file, opts).map_err(|e| {
        seen.extend(b.warnings.iter().cloned());
        fail(e, &seen)
    })?;
    b.resolve_links().map_err(|e| {
        seen.extend(b.warnings.iter().cloned());
        fail(e, &seen)
    })?;
    page::root_fixup(&mut b.nodes, b.sheet);
    let nodes = std::mem::take(&mut b.nodes);
    let links = std::mem::take(&mut b.links);
    let mut warnings = early;
    warnings.extend(std::mem::take(&mut b.warnings));
    drop(b);
    let mut ctx = compile::Ctx {
        src: src.to_string(),
        file: file.to_string(),
        sheet,
        nodes,
        comp: vec![],
        links,
        warnings: std::mem::take(&mut warnings),
        root_font_size: 15.0,
        sk: Default::default(),
        link_geo: vec![],
    };
    compile::compute(&mut ctx);
    validate::cascade_checks(&ctx).map_err(|e| fail(e, &ctx.warnings))?;
    if drawing::expand(&mut ctx).map_err(|e| fail(e, &ctx.warnings))? {
        compile::compute(&mut ctx);
    }
    chart::validate(&ctx).map_err(|e| fail(e, &ctx.warnings))?;
    if let Err(e) = validate::layout_values(&ctx, &[]) {
        // a max-width overflow the layout pass meets first reports instead
        let e = if (1..ctx.comp.len()).any(|i| layout::max_width_bounds(&ctx, i)) {
            let ov = layout::overflows(&mut ctx);
            validate::layout_values(&ctx, &ov).err().unwrap_or(e)
        } else {
            e
        };
        return Err(fail(e, &ctx.warnings));
    }
    page::scale_units(&mut ctx);
    drawing::prepare(&mut ctx);
    ctx.root_font_size = ctx.comp[0].font_size;
    image::check_sizes(&ctx).map_err(|e| fail(e, &ctx.warnings))?;
    layout::measure(&mut ctx, 0, None);
    if let Some(e) = layout::take_error() {
        return Err(fail(e, &ctx.warnings));
    }
    drawing::size_warnings(&mut ctx);
    links::compute(&mut ctx);
    let svg = render::render(&ctx, opts).map_err(|e| fail(e, &ctx.warnings))?;
    ctx.warnings.extend(outline::take_warnings());
    Ok((svg, ctx.warnings))
}

fn write_out(opts: &Options, text: &str) -> Result<(), String> {
    match &opts.output {
        Some(path) => std::fs::write(path, text.as_bytes()).map_err(|e| format!("error: write {}: {}", path, e)),
        None => {
            let mut so = std::io::stdout();
            let _ = so.write_all(text.as_bytes());
            Ok(())
        }
    }
}

fn html_wrap(svg: &str) -> String {
    format!(
        "<!doctype html>\n<html>\n<head>\n  <meta charset=\"utf-8\">\n  <title>lini</title>\n</head>\n<body>\n{}</body>\n</html>\n",
        svg
    )
}

fn run_compile(input: &str, opts: &Options) -> i32 {
    if opts.format != "svg" && opts.format != "html" {
        eprintln!("error: invalid --format '{}' (expected svg|html)", opts.format);
        return 3;
    }
    if let Some(t) = &opts.theme {
        match theme::load(t, opts.no_fs) {
            Ok(_) => {}
            Err(theme::ThemeErr::Io(m)) => {
                eprintln!("{}", m);
                return 2;
            }
            Err(theme::ThemeErr::NoFs(m)) => {
                eprintln!("{}", m);
                return 3;
            }
        }
    }
    let src = match read_input(input) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("{}", e);
            return 2;
        }
    };
    let file = if input == "-" { "<stdin>".to_string() } else { input.to_string() };
    let result = compile_src(&src, &file, opts);
    if opts.json {
        let (diags, failed) = match &result {
            Ok((_, w)) => (w.clone(), false),
            Err((e, w)) => {
                // a failed V-phase reports its whole list
                let phase = validate::take_phase_diags();
                if !phase.is_empty() {
                    (phase, true)
                } else {
                    let mut d = w.clone();
                    d.push(e.clone());
                    (d, true)
                }
            }
        };
        print!("{}", diag::render_json(&file, &src, &diags));
        if failed || (opts.strict && !diags.is_empty()) {
            return 1;
        }
        return 0;
    }
    match result {
        Ok((svg, warns)) => {
            if !opts.no_warn {
                for w in &warns {
                    eprintln!("{}", diag::render_text(&file, &src, w));
                }
            }
            if !opts.check {
                let text = if opts.format == "html" { html_wrap(&svg) } else { svg };
                if let Err(e) = write_out(opts, &text) {
                    eprintln!("{}", e);
                    return 2;
                }
            }
            if opts.strict && !warns.is_empty() {
                return 1;
            }
            0
        }
        Err((e, _warns)) => {
            // a failed compile prints its error alone
            eprintln!("{}", diag::render_text(&file, &src, &e));
            1
        }
    }
}

fn run_fmt(input: &str, check: bool, stdout: bool) -> i32 {
    let src = match read_input(input) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("{}", e);
            return 2;
        }
    };
    let file = if input == "-" { "<stdin>".to_string() } else { input.to_string() };
    let out = match format::format(&src) {
        Ok(o) => o,
        Err(e) => {
            eprintln!("{}", diag::render_text(&file, &src, &e));
            return 1;
        }
    };
    if check {
        if out != src {
            eprintln!("{}: would reformat", file);
            return 1;
        }
        return 0;
    }
    if stdout || input == "-" {
        print!("{}", out);
        return 0;
    }
    if out != src {
        let _ = std::fs::write(input, out.as_bytes());
    }
    0
}

fn run_theme(name: &Option<String>) -> i32 {
    match name {
        None => {
            print!("{}", theme::LIST);
            0
        }
        Some(n) => match theme::css_of(n) {
            Some(css) => {
                print!("{}", css);
                0
            }
            None => {
                eprintln!("error: unknown theme '{}' (try one of: default, light, dark, high-contrast, blueprint)", n);
                3
            }
        },
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let code = match cli::parse(&args) {
        cli::Outcome::Print(s) => {
            print!("{}", s);
            0
        }
        cli::Outcome::Fail(s) => {
            eprint!("{}", s);
            3
        }
        cli::Outcome::Run(p) => match &p.cmd {
            cli::Cmd::Compile { input } => run_compile(input, &p.opts),
            cli::Cmd::Theme { name } => run_theme(name),
            cli::Cmd::Highlight { input: _, css: true } => {
                print!("{}", cli::HIGHLIGHT_CSS);
                0
            }
            cli::Cmd::Highlight { input: Some(input), css: false } => match read_input(input) {
                Ok(src) => {
                    print!("{}", highlight::highlight(&src));
                    0
                }
                Err(e) => {
                    eprintln!("{}", e);
                    2
                }
            },
            cli::Cmd::Fmt { input, check, stdout } => run_fmt(input, *check, *stdout),
            cli::Cmd::Desugar { input } => match read_input(input) {
                Ok(src) => {
                    let file = if input == "-" { "<stdin>".to_string() } else { input.clone() };
                    match desugar::desugar(&src) {
                        Ok(out) => {
                            print!("{}", out);
                            0
                        }
                        Err(e) => {
                            eprintln!("{}", diag::render_text(&file, &src, &e));
                            1
                        }
                    }
                }
                Err(e) => {
                    eprintln!("{}", e);
                    2
                }
            },
            _ => 0,
        },
    };
    let _ = std::io::stdout().flush();
    std::process::exit(code);
}
