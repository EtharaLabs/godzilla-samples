// Loading, checking and lowering a single file or a multi-module project.

use crate::ast::*;
use crate::diag::{render, Diag};
use crate::infer::*;
use crate::lower::Lowerer;
use crate::types::*;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

pub struct ModSrc {
    /// Pyfun module name (`Geometry`)
    pub name: String,
    /// file name (`geometry.pyfun`)
    pub file: String,
    pub path: PathBuf,
    pub src: String,
    pub prog: Program,
    pub imports: Vec<String>,
}

pub fn module_name_of(path: &Path) -> String {
    let stem = path.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
    let mut c = stem.chars();
    match c.next() {
        Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
        None => stem,
    }
}

pub fn py_module_of(file: &str) -> String {
    file.trim_end_matches(".pyfun").to_string()
}

fn imports_of(p: &Program) -> Vec<String> {
    p.decls
        .iter()
        .filter_map(|d| if let Decl::Import(n, _) = d { Some(n.clone()) } else { None })
        .collect()
}

pub enum LoadError {
    /// a plain message line (already prefixed with `error: `)
    Msg(String),
    /// a parse error inside a module
    Parse { module: Option<(String, String)>, src: String, diag: Diag },
}

pub fn read_source(path: &Path) -> Result<String, String> {
    match std::fs::read_to_string(path) {
        Ok(s) => Ok(s),
        Err(e) => Err(format!("error: cannot read {}: {}", path.display(), e)),
    }
}

/// Load the main file and every module it imports, dependencies first.
pub fn load(main: &Path, main_src: String) -> Result<Vec<ModSrc>, LoadError> {
    let prog = match crate::parser::parse_program(&main_src) {
        Ok(p) => p,
        Err(d) => return Err(LoadError::Parse { module: None, src: main_src, diag: d }),
    };
    let imports = imports_of(&prog);
    let main_name = module_name_of(main);
    let file = main.file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
    let root = ModSrc { name: main_name.clone(), file, path: main.to_path_buf(), src: main_src, prog, imports };
    if root.imports.is_empty() {
        return Ok(vec![root]);
    }
    let dir = main.parent().map(|p| p.to_path_buf()).unwrap_or_else(|| PathBuf::from("."));
    let mut out: Vec<ModSrc> = Vec::new();
    let mut done: HashSet<String> = HashSet::new();
    let mut stack: Vec<String> = vec![main_name.clone()];
    let facades = crate::pkg::facade_dirs(main);
    visit(root, &dir, &facades, &mut out, &mut done, &mut stack)?;
    Ok(out)
}

fn visit(m: ModSrc, dir: &Path, facades: &[PathBuf], out: &mut Vec<ModSrc>, done: &mut HashSet<String>, stack: &mut Vec<String>) -> Result<(), LoadError> {
    for imp in m.imports.clone() {
        if done.contains(&imp) {
            continue;
        }
        if let Some(pos) = stack.iter().position(|s| *s == imp) {
            let mut cyc: Vec<String> = stack[pos..].to_vec();
            cyc.push(imp.clone());
            return Err(LoadError::Msg(format!("error: import cycle: {}", cyc.join(" -> "))));
        }
        let file = format!("{}.pyfun", imp.to_lowercase());
        // next to the program first, then in the vendored façades
        let mut path = dir.join(&file);
        let mut facade = false;
        if !path.exists() {
            if let Some(f) = facades.iter().map(|d| d.join(&file)).find(|p| p.exists()) {
                path = f;
                facade = true;
            }
        }
        // (a file that is not UTF-8 text is as good as missing)
        let src = match std::fs::read_to_string(&path) {
            Ok(s) => s,
            Err(_) => {
                return Err(LoadError::Msg(format!("error: cannot find module `{}` (expected `{}`), imported by `{}`", imp, file, m.name)));
            }
        };
        let prog = match crate::parser::parse_program(&src) {
            Ok(p) => p,
            Err(d) if facade => {
                return Err(LoadError::Msg(format!("error: in module `{}`: parse error: {} (at {}..{})", imp, d.msg, d.span.lo, d.span.hi)));
            }
            Err(d) => return Err(LoadError::Parse { module: Some((imp.clone(), file.clone())), src, diag: d }),
        };
        let imports = imports_of(&prog);
        let child = ModSrc { name: imp.clone(), file, path, src, prog, imports };
        stack.push(imp.clone());
        visit(child, dir, facades, out, done, stack)?;
        stack.pop();
    }
    done.insert(m.name.clone());
    out.push(m);
    Ok(())
}

/// What one module offers its importers.
#[derive(Clone, Default)]
pub struct Exports {
    pub values: HashMap<String, Scheme>,
    pub types: HashMap<String, TypeInfo>,
    pub ctors: HashMap<String, CtorInfo>,
    pub fields: HashMap<String, Vec<String>>,
    pub measures: HashMap<String, Option<Unit>>,
    /// arity of each exported function
    pub arities: HashMap<String, usize>,
}

pub struct Checked {
    pub mods: Vec<ModSrc>,
    pub checkers: Vec<Checker>,
    pub exports: HashMap<String, Exports>,
}

/// Check every module in order. On failure returns the rendered report.
/// A single file reports its errors (and holes); a project checks every
/// module and reports each one's errors under a header, with a total.
pub fn check_all(mods: Vec<ModSrc>, first_only: bool) -> Result<Checked, String> {
    let project = mods.len() > 1;
    let mut exports: HashMap<String, Exports> = HashMap::new();
    let mut checkers = Vec::new();
    let mut report = String::new();
    let mut total = 0;
    for m in &mods {
        let mut c = Checker::new();
        c.source = m.src.clone();
        for imp in &m.imports {
            if let Some(ex) = exports.get(imp) {
                install_exports(&mut c, imp, ex);
            }
        }
        c.check_program(&m.prog);
        if project {
            if !c.errors.is_empty() {
                report.push_str(&format!("-- module `{}` ({}) --\n", m.name, m.file));
                for d in &c.errors {
                    report.push_str(&render(&m.src, d));
                    report.push('\n');
                }
                total += c.errors.len();
            }
            exports.insert(m.name.clone(), collect_exports(&c, &m.prog));
            checkers.push(c);
            continue;
        }
        let hole_notes: Vec<Diag> = c.holes.iter().map(|h| Diag::note(crate::holes::hole_message(&c, h), h.span)).collect();
        if !hole_notes.is_empty() && c.errors.is_empty() && first_only {
            let h = &c.holes[0];
            let t = c.st.show(&h.ty);
            let name = match &h.name {
                Some(n) => format!("?{}", n),
                None => "?".to_string(),
            };
            let d = Diag::error(format!("cannot compile: unfilled hole `{}` has type `{}`{} (fill it in)", name, t, crate::holes::suggest_text(&c, h)), h.span);
            return Err(format!("{}\n", render(&m.src, &d)));
        }
        if !hole_notes.is_empty() && !first_only {
            let mut out = String::new();
            let all: Vec<&Diag> = c.errors.iter().chain(hole_notes.iter()).collect();
            let texts: Vec<String> = all.iter().map(|d| render(&m.src, d)).collect();
            out.push_str(&texts.join("\n\n"));
            out.push('\n');
            if !c.errors.is_empty() {
                let n = c.errors.len();
                out.push_str(&format!("\n{} error{}\n", n, if n == 1 { "" } else { "s" }));
            }
            let h = hole_notes.len();
            out.push_str(&format!("{} unfilled hole{}\n", h, if h == 1 { "" } else { "s" }));
            return Err(out);
        }
        if !c.errors.is_empty() {
            let mut out = String::new();
            if first_only {
                out.push_str(&render(&m.src, &c.errors[0]));
                out.push('\n');
            } else {
                for d in &c.errors {
                    out.push_str(&render(&m.src, d));
                    out.push_str("\n\n");
                }
                let n = c.errors.len();
                out.push_str(&format!("{} error{}\n", n, if n == 1 { "" } else { "s" }));
            }
            return Err(out);
        }
        exports.insert(m.name.clone(), collect_exports(&c, &m.prog));
        checkers.push(c);
    }
    if total > 0 {
        report.push_str(&format!("\n{} error{}\n", total, if total == 1 { "" } else { "s" }));
        return Err(report);
    }
    // a project is compiled whole: an unfilled hole anywhere stops it
    if project && first_only {
        for c in &checkers {
            if let Some(h) = c.holes.first() {
                let name = match &h.name {
                    Some(n) => format!("?{}", n),
                    None => "?".to_string(),
                };
                return Err(format!("error: lowering failed: cannot compile: unfilled hole `{}`\n", name));
            }
        }
    }
    Ok(Checked { mods, checkers, exports })
}

pub fn install_exports(c: &mut Checker, module: &str, ex: &Exports) {
    let mut me = ModuleExports::default();
    let mut names: Vec<&String> = ex.values.keys().collect();
    names.sort();
    for k in names {
        me.values.insert(k.clone(), ex.values[k].clone());
        me.order.push(k.clone());
    }
    c.modules.insert(module.to_string(), me);
    for (k, t) in &ex.types {
        let mut t = t.clone();
        if t.module.is_none() {
            t.module = Some(module.to_string());
        }
        c.types.entry(k.clone()).or_insert_with(|| t.clone());
        c.types.insert(format!("{}.{}", module, k), t);
    }
    for (k, ci) in &ex.ctors {
        let mut ci = ci.clone();
        if ci.module.is_none() {
            ci.module = Some(module.to_string());
        }
        c.ctors.insert(format!("{}.{}", module, k), ci);
    }
    for (k, v) in &ex.fields {
        let e = c.fields.entry(k.clone()).or_default();
        for x in v {
            if !e.contains(x) {
                e.push(x.clone());
            }
        }
    }
    for (k, v) in &ex.measures {
        c.measures.entry(k.clone()).or_insert_with(|| v.clone());
    }
}

pub fn collect_exports(c: &Checker, prog: &Program) -> Exports {
    let mut ex = Exports::default();
    // what is left unknown in an exported type (a binding that failed to
    // check, a `let mut`) is quantified, so importers get fresh variables
    let st = &c.st;
    for d in &prog.decls {
        match d {
            Decl::Let(l) => {
                let mut names = Vec::new();
                crate::check_decl::pat_names(&l.pat, &mut names);
                for n in names {
                    if let Some(g) = c.globals.get(&n) {
                        let ty = st.resolve(&g.scheme.ty);
                        ex.values.insert(n.clone(), Scheme { ty: quantify_all(&st, &ty), ord: g.scheme.ord.clone() });
                    }
                    if !l.params.is_empty() {
                        ex.arities.insert(n.clone(), l.params.len());
                    }
                }
            }
            Decl::Extern(e) => {
                if let Some(g) = c.globals.get(&e.name) {
                    ex.values.insert(e.name.clone(), g.scheme.clone());
                }
            }
            Decl::Type(t) => {
                if let Some(ti) = c.types.get(&t.name) {
                    ex.types.insert(t.name.clone(), ti.clone());
                }
                if let TypeBody::Sum(vs) = &t.body {
                    for v in vs {
                        if let Some(ci) = c.ctors.get(&v.name) {
                            ex.ctors.insert(v.name.clone(), ci.clone());
                        }
                    }
                }
                if let TypeBody::Opaque(_) = &t.body {
                    if let Some(ci) = c.ctors.get(&t.name) {
                        ex.ctors.insert(t.name.clone(), ci.clone());
                    }
                }
                if let TypeBody::Record(fs) = &t.body {
                    for (f, _, _) in fs {
                        ex.fields.entry(f.clone()).or_default().push(t.name.clone());
                    }
                }
            }
            Decl::ExternType(n, _, _, _) => {
                if let Some(ti) = c.types.get(n) {
                    ex.types.insert(n.clone(), ti.clone());
                }
            }
            Decl::Measure(n, _, _) => {
                if let Some(u) = c.measures.get(n) {
                    ex.measures.insert(n.clone(), u.clone());
                }
            }
            _ => {}
        }
    }
    ex
}

pub struct Emitted {
    /// (file name, contents)
    pub files: Vec<(String, String)>,
}

pub struct EmitOpts {
    pub py311: bool,
    pub native: bool,
}

/// Lower every module to Python source; a construct the lowering cannot
/// express ends the command (reported at the start of a single file).
pub fn emit_all(ck: &Checked, opts: &EmitOpts) -> Emitted {
    match try_emit_all(ck, opts) {
        Ok(em) => em,
        Err(msg) => {
            if ck.mods.len() > 1 {
                eprintln!("error: lowering failed: {}", msg);
            } else {
                let d = crate::diag::Diag::error(msg, crate::source::Span::new(0, 0));
                eprintln!("{}", crate::diag::render(&ck.mods[0].src, &d));
            }
            std::process::exit(1);
        }
    }
}

pub fn try_emit_all(ck: &Checked, opts: &EmitOpts) -> Result<Emitted, String> {
    let project = ck.mods.len() > 1;
    let mut files = Vec::new();
    let mut need_rt = false;
    for (i, m) in ck.mods.iter().enumerate() {
        let c = &ck.checkers[i];
        let mut l = Lowerer::new(c);
        l.py311 = opts.py311;
        l.native = opts.native;
        if project {
            l.project = true;
            l.all_ordered = true;
            // the names this module defines at top level
            let mut top: HashSet<String> = HashSet::new();
            for d in &m.prog.decls {
                match d {
                    Decl::Let(lt) => {
                        let mut names = Vec::new();
                        crate::check_decl::pat_names(&lt.pat, &mut names);
                        for n in names {
                            top.insert(crate::lower::mangle(&n));
                        }
                    }
                    Decl::Extern(e) => {
                        top.insert(crate::lower::mangle(&e.name));
                    }
                    _ => {}
                }
            }
            for imp in &m.imports {
                let file = format!("{}.pyfun", imp.to_lowercase());
                let pym = py_module_of(&file);
                let alias = if top.contains(&pym) { format!("_pf_{}", pym) } else { pym.clone() };
                l.project_modules.insert(imp.clone(), alias.clone());
                l.module_imports.push((pym, alias));
                if let Some(ex) = ck.exports.get(imp) {
                    for (k, a) in &ex.arities {
                        l.module_arities.insert(format!("{}.{}", imp, k), *a);
                    }
                }
            }
            for (k, ci) in c.ctors.iter() {
                if let Some((modname, _)) = k.split_once('.') {
                    let _ = (modname, ci);
                }
            }
        }
        l.collect_ordering();
        let code = l.lower_program(&m.prog.decls);
        if let Some(e) = l.error.take() {
            return Err(e);
        }
        let text = l.assemble(&m.prog.decls, &code);
        if l.uses_rt {
            need_rt = true;
        }
        files.push((format!("{}.py", py_module_of(&m.file)), text));
    }
    if project && need_rt {
        let rt = if opts.native { crate::lower5::runtime_module_native() } else { crate::lower5::runtime_module() };
        files.push(("_pyfun_rt.py".to_string(), rt));
    }
    Ok(Emitted { files })
}

/// Quantify every variable still free in `t`, after its existing ones.
fn quantify_all(st: &Store, t: &Ty) -> Ty {
    fn max_gen(t: &Ty, m: &mut [usize; 4]) {
        match t {
            Ty::Gen(i) => m[0] = m[0].max(i + 1),
            Ty::Con(_, args) => args.iter().for_each(|a| max_gen(a, m)),
            Ty::Tuple(ts) => ts.iter().for_each(|a| max_gen(a, m)),
            Ty::Fun(a, e, r) => {
                max_gen(a, m);
                if let Some(EffTail::Gen(i)) = e.tail {
                    m[3] = m[3].max(i + 1);
                }
                max_gen(r, m);
            }
            Ty::Num(k, u) => {
                if let Kind::Gen(i) = k {
                    m[1] = m[1].max(i + 1);
                }
                for a in u.0.keys() {
                    if let UAtom::Gen(i) = a {
                        m[2] = m[2].max(i + 1);
                    }
                }
            }
            Ty::Var(_) => {}
        }
    }
    #[derive(Default)]
    struct Q {
        next: [usize; 4],
        t: HashMap<usize, usize>,
        k: HashMap<usize, usize>,
        u: HashMap<usize, usize>,
        e: HashMap<usize, usize>,
    }
    fn fresh(map: &mut HashMap<usize, usize>, next: &mut usize, v: usize) -> usize {
        *map.entry(v).or_insert_with(|| {
            let i = *next;
            *next += 1;
            i
        })
    }
    fn go(st: &Store, t: &Ty, q: &mut Q) -> Ty {
        match st.shallow(t) {
            Ty::Var(v) => Ty::Gen(fresh(&mut q.t, &mut q.next[0], v)),
            Ty::Gen(i) => Ty::Gen(i),
            Ty::Con(n, args) => Ty::Con(n, args.iter().map(|a| go(st, a, q)).collect()),
            Ty::Tuple(ts) => Ty::Tuple(ts.iter().map(|a| go(st, a, q)).collect()),
            Ty::Fun(a, e, r) => {
                let a = go(st, &a, q);
                let mut e = st.eff(&e);
                if let Some(EffTail::Var(v)) = e.tail {
                    e.tail = Some(EffTail::Gen(fresh(&mut q.e, &mut q.next[3], v)));
                }
                let r = go(st, &r, q);
                Ty::Fun(Box::new(a), e, Box::new(r))
            }
            Ty::Num(k, u) => {
                let k = match st.kind(k) {
                    Kind::Var(v) => Kind::Gen(fresh(&mut q.k, &mut q.next[1], v)),
                    other => other,
                };
                let u = st.unit(&u);
                let mut out = std::collections::BTreeMap::new();
                for (a, e) in u.0 {
                    let a = match a {
                        UAtom::Var(v) => UAtom::Gen(fresh(&mut q.u, &mut q.next[2], v)),
                        other => other,
                    };
                    *out.entry(a).or_insert(0) += e;
                }
                Ty::Num(k, Unit(out))
            }
        }
    }
    let t = st.resolve(t);
    let mut q = Q::default();
    max_gen(&t, &mut q.next);
    go(st, &t, &mut q)
}
