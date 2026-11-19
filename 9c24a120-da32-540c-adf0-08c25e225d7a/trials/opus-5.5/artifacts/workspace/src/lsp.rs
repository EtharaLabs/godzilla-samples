// The language server (`pyfun lsp`): JSON-RPC over stdio with
// `Content-Length` framing. Documents are re-analysed on each request.

use crate::ast::*;
use crate::builtins::BUILTINS;
use crate::diag::{Diag, Severity};
use crate::ide::{Doc, NO_DEF};
use crate::infer::Checker;
use crate::json::{self, Json};
use crate::source::Span;
use crate::types::*;
use std::collections::BTreeSet;
use std::io::{BufRead, Read, Write};
use std::path::{Path, PathBuf};

const KEYWORDS: &[&str] = &[
    "let", "mut", "pure", "type", "measure", "extern", "if", "then", "else", "match", "with", "fun", "and", "or", "not", "true", "false", "return", "in", "async", "seq", "result", "option",
];

const BUILTIN_TYPES: &[&str] = &["int", "float", "bool", "string", "unit", "Result", "Async", "Seq", "List", "Set", "Map", "Option", "Decoder"];

// ---- positions ------------------------------------------------------------

/// Byte offsets <-> LSP positions (lines and UTF-16 code units).
pub struct Lines<'a> {
    src: &'a str,
    starts: Vec<usize>,
}

impl<'a> Lines<'a> {
    pub fn new(src: &'a str) -> Lines<'a> {
        let mut starts = vec![0];
        for (i, b) in src.bytes().enumerate() {
            if b == b'\n' {
                starts.push(i + 1);
            }
        }
        Lines { src, starts }
    }

    pub fn pos(&self, off: usize) -> (usize, usize) {
        let off = off.min(self.src.len());
        let line = match self.starts.binary_search(&off) {
            Ok(i) => i,
            Err(i) => i - 1,
        };
        let ls = self.starts[line];
        let col: usize = self.src[ls..off].chars().map(|c| c.len_utf16()).sum();
        (line, col)
    }

    /// The offset of a position, clamped to its line; None past the end.
    pub fn offset(&self, line: usize, ch: usize) -> Option<usize> {
        let ls = *self.starts.get(line)?;
        let le = self.starts.get(line + 1).map(|e| e - 1).unwrap_or(self.src.len());
        let mut units = 0;
        for (i, c) in self.src[ls..le].char_indices() {
            if units >= ch {
                return Some(ls + i);
            }
            units += c.len_utf16();
        }
        Some(le)
    }

    pub fn range(&self, sp: Span) -> Json {
        let (l1, c1) = self.pos(sp.lo);
        let (l2, c2) = self.pos(sp.hi);
        Json::obj(vec![("start", position(l1, c1)), ("end", position(l2, c2))])
    }
}

fn position(line: usize, ch: usize) -> Json {
    Json::obj(vec![("line", Json::int(line as i64)), ("character", Json::int(ch as i64))])
}

// ---- analysis -------------------------------------------------------------

pub struct Analysis {
    pub src: String,
    pub prog: Program,
    /// lexer and parser errors, in position order
    pub syntax: Vec<Diag>,
    /// the checker of the document (None when its imports cannot load)
    pub checker: Option<Checker>,
    /// files of imported modules, by module name
    pub module_files: Vec<(String, PathBuf, Option<Checker>, Program)>,
    /// what each name refers to
    pub res: crate::resolve::Resolution,
}

pub fn uri_to_path(uri: &str) -> Option<PathBuf> {
    let rest = uri.strip_prefix("file://")?;
    let mut out: Vec<u8> = Vec::new();
    let b = rest.as_bytes();
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() + 0 && i + 2 <= b.len() - 1 {
            if let Ok(v) = u8::from_str_radix(std::str::from_utf8(&b[i + 1..i + 3]).unwrap_or("zz"), 16) {
                out.push(v);
                i += 3;
                continue;
            }
        }
        out.push(b[i]);
        i += 1;
    }
    Some(PathBuf::from(String::from_utf8_lossy(&out).to_string()))
}

pub fn path_to_uri(p: &Path) -> String {
    format!("file://{}", p.display())
}

pub fn analyze(uri: &str, text: &str) -> Analysis {
    let (prog, lex_errors, parse_errors) = crate::parser::parse_program_recover(text);
    let mut syntax: Vec<Diag> = lex_errors;
    syntax.extend(parse_errors);
    syntax.sort_by_key(|d| d.span.lo);
    let imports: Vec<String> = prog.decls.iter().filter_map(|d| if let Decl::Import(n, _) = d { Some(n.clone()) } else { None }).collect();
    let mut module_files = Vec::new();
    let mut checker = Some(Checker::new());
    if !imports.is_empty() {
        // the modules this document imports come from disk, next to it
        let path = uri_to_path(uri).unwrap_or_else(|| PathBuf::from("main.pyfun"));
        match crate::project::load(&path, text.to_string()) {
            Ok(mods) => {
                let mut exports: std::collections::HashMap<String, crate::project::Exports> = Default::default();
                for m in &mods[..mods.len() - 1] {
                    let mut c = Checker::new();
                    for imp in &m.imports {
                        if let Some(ex) = exports.get(imp) {
                            crate::project::install_exports(&mut c, imp, ex);
                        }
                    }
                    c.check_program(&m.prog);
                    exports.insert(m.name.clone(), crate::project::collect_exports(&c, &m.prog));
                    module_files.push((m.name.clone(), m.path.clone(), Some(c), m.prog.clone()));
                }
                let c = checker.as_mut().unwrap();
                for imp in &imports {
                    if let Some(ex) = exports.get(imp) {
                        crate::project::install_exports(c, imp, ex);
                    }
                }
            }
            // modules that cannot be loaded are simply missing
            Err(_) => {}
        }
    }
    if let Some(c) = checker.as_mut() {
        c.source = text.to_string();
        c.check_program(&prog);
    }
    let res = crate::resolve::resolve(&prog);
    Analysis { src: text.to_string(), prog, syntax, checker, module_files, res }
}

impl Analysis {
    pub fn diagnostics(&self) -> Vec<Diag> {
        if !self.syntax.is_empty() {
            return self.syntax.clone();
        }
        let Some(c) = &self.checker else { return Vec::new() };
        let mut out = c.errors.clone();
        for h in &c.holes {
            out.push(Diag::note(crate::holes::hole_message(c, h), h.span));
        }
        out
    }
}

// ---- hover ----------------------------------------------------------------

/// Labels on the arrows a function type is made of.
fn spine_effects(st: &Store, t: &Ty) -> Vec<String> {
    let mut labels = BTreeSet::new();
    let mut cur = st.resolve(t);
    while let Ty::Fun(_, e, r) = cur {
        let e = st.eff(&e);
        labels.extend(e.labels.iter().cloned());
        cur = st.resolve(&r);
    }
    labels.iter().map(|l| label_name(*l, &st.other_labels)).collect()
}

fn builtin_doc(name: &str) -> Option<&'static str> {
    BUILTINS.iter().find(|b| b.name == name).map(|b| b.doc)
}

pub fn hover_text(c: &Checker, ty: Option<&Ty>, doc: &Doc) -> Option<String> {
    let mut parts: Vec<String> = Vec::new();
    if let Some(ty) = ty {
        let mut s = format!("```pyfun\n{}\n```", c.st.show(ty));
        let effs = spine_effects(&c.st, ty);
        if !effs.is_empty() {
            s.push_str(&format!("\n\n**Effect:** `{}`", effs.join(", ")));
        }
        parts.push(s);
    }
    let doc_text: Option<String> = match doc {
        Doc::None => None,
        // a definition without a comment shares the library's, by name
        Doc::Def(d) => c.ide.defs.get(*d).and_then(|d| d.doc.clone().or_else(|| builtin_doc(&d.name).map(|s| s.to_string()))),
        Doc::Builtin(n) => builtin_doc(n).map(|s| s.to_string()),
        Doc::Text(t) => Some(t.clone()),
    };
    // the comment's lines stay lines in markdown
    let doc_text = doc_text.map(|d| d.replace('\n', "  \n"));
    if let Some(d) = doc_text {
        parts.push(d);
    }
    if parts.is_empty() {
        None
    } else {
        Some(parts.join("\n\n---\n\n"))
    }
}

fn hover(a: &Analysis, off: usize) -> Json {
    let Some(c) = &a.checker else { return Json::Null };
    let mut best: Option<&crate::ide::Item> = None;
    for it in &c.ide.items {
        if it.span.lo <= off && off < it.span.hi {
            let w = it.span.hi - it.span.lo;
            if best.map_or(true, |b| w < b.span.hi - b.span.lo) {
                best = Some(it);
            }
        }
    }
    let lines = Lines::new(&a.src);
    // a library name the checker never reached still has its documentation
    let lib = a.res.builtin_uses.iter().chain(a.res.qual_builtin_uses.iter()).filter(|(sp, _)| sp.lo <= off && off < sp.hi).min_by_key(|(sp, _)| sp.hi - sp.lo);
    if let Some((sp, n)) = lib {
        let reached = c.ide.items.iter().any(|it| it.span == *sp);
        if !reached && best.map_or(true, |b| sp.hi - sp.lo <= b.span.hi - b.span.lo) {
            if let Some(d) = builtin_doc(n) {
                let text = d.replace('\n', "  \n");
                return Json::obj(vec![("contents", Json::obj(vec![("kind", Json::str("markdown")), ("value", Json::Str(text))])), ("range", lines.range(*sp))]);
            }
        }
    }
    let Some(it) = best else { return Json::Null };
    let Some(text) = hover_text(c, it.ty.as_ref(), &it.doc) else { return Json::Null };
    Json::obj(vec![("contents", Json::obj(vec![("kind", Json::str("markdown")), ("value", Json::Str(text))])), ("range", lines.range(it.span))])
}

// ---- names ------------------------------------------------------------------

/// What the cursor is on.
enum Target {
    /// a value definition (by id) — `on_def` when the cursor is on the definition itself
    Value(usize, Span, bool),
    /// a constructor or type, and whether the cursor is on its declaration
    Ctor(String, Span, bool),
    Type(String, Span, bool),
    /// a library name
    Builtin(String, Span),
    /// a name that resolves to nothing
    Unbound(String, Span),
    /// a unit of measure's declaration
    Measure(Span),
}

fn smallest<'a, T>(items: impl Iterator<Item = (Span, T)>, off: usize) -> Option<(Span, T)> {
    let mut best: Option<(Span, T)> = None;
    for (sp, v) in items {
        if sp.lo <= off && off < sp.hi {
            if best.as_ref().map_or(true, |(b, _)| sp.hi - sp.lo < b.hi - b.lo) {
                best = Some((sp, v));
            }
        }
    }
    best
}

/// Spans of the case names in an active pattern's `(|A|B|)` header.
fn active_case_spans(src: &str, l: &LetDecl, cases: &[String]) -> Vec<(String, Span)> {
    let mut out = Vec::new();
    let mut pos = l.name_span.lo;
    let end = l.name_span.hi.min(src.len());
    for c in cases {
        if c == "_" {
            continue;
        }
        if let Some(i) = src[pos..end].find(c.as_str()) {
            let lo = pos + i;
            out.push((c.clone(), Span::new(lo, lo + c.len())));
            pos = lo + c.len();
        }
    }
    out
}

/// Constructor and type declarations in source order: (name, span, is_type).
fn upper_decls(src: &str, decls: &[Decl]) -> Vec<(String, Span, bool)> {
    let mut out = Vec::new();
    for d in decls {
        match d {
            Decl::Type(t) => {
                out.push((t.name.clone(), t.name_span, true));
                if let TypeBody::Sum(vs) = &t.body {
                    for v in vs {
                        out.push((v.name.clone(), v.span, false));
                    }
                }
            }
            Decl::ExternType(n, _, sp, _) => {
                if let Some(s) = name_in(src, *sp, n) {
                    out.push((n.clone(), s, true));
                }
            }
            Decl::Let(l) => {
                if let Some(cases) = &l.active {
                    for (n, s) in active_case_spans(src, l, cases) {
                        out.push((n, s, false));
                    }
                }
            }
            _ => {}
        }
    }
    out
}

/// The span of `name` as a word inside `within` (after its first keyword).
fn name_in(src: &str, within: Span, name: &str) -> Option<Span> {
    let text = &src[within.lo.min(src.len())..within.hi.min(src.len())];
    let b = text.as_bytes();
    let mut from = 0;
    while let Some(i) = text[from..].find(name) {
        let lo = from + i;
        let hi = lo + name.len();
        let before_ok = lo == 0 || !(b[lo - 1].is_ascii_alphanumeric() || b[lo - 1] == b'_');
        let after_ok = hi >= b.len() || !(b[hi].is_ascii_alphanumeric() || b[hi] == b'_');
        if before_ok && after_ok {
            return Some(Span::new(within.lo + lo, within.lo + hi));
        }
        from = lo + 1;
    }
    None
}

fn target_at(a: &Analysis, off: usize) -> Option<Target> {
    let r = &a.res;
    // every name the cursor is in; the narrowest wins, then in this order
    let mut cands: Vec<(Span, Target)> = Vec::new();
    for (i, d) in r.defs.iter().enumerate() {
        cands.push((d.span, Target::Value(i, d.span, true)));
    }
    for (s, d) in &r.uses {
        cands.push((*s, Target::Value(*d, *s, false)));
    }
    for (s, d) in &r.redefs {
        cands.push((*s, Target::Value(*d, *s, true)));
    }
    for d in &a.prog.decls {
        // a declaration only of itself
        if let Decl::Measure(_, _, sp) | Decl::Import(_, sp) = d {
            cands.push((*sp, Target::Measure(*sp)));
        }
    }
    for (n, s, t) in upper_decls(&a.src, &a.prog.decls) {
        cands.push((s, if t { Target::Type(n, s, true) } else { Target::Ctor(n, s, true) }));
    }
    for (s, n) in &r.ctor_uses {
        cands.push((*s, Target::Ctor(n.clone(), *s, false)));
    }
    for (s, n) in &r.type_uses {
        cands.push((*s, Target::Type(n.clone(), *s, false)));
    }
    for (s, n) in &r.builtin_uses {
        cands.push((*s, Target::Builtin(n.clone(), *s)));
    }
    for (s, n) in &r.unbound_uses {
        cands.push((*s, Target::Unbound(n.clone(), *s)));
    }
    let mut best: Option<(Span, Target)> = None;
    for (s, t) in cands {
        if s.lo <= off && off < s.hi && best.as_ref().map_or(true, |(b, _)| s.hi - s.lo < b.hi - b.lo) {
            best = Some((s, t));
        }
    }
    best.map(|(_, t)| t)
}

fn first_upper_decl(a: &Analysis, name: &str) -> Option<Span> {
    upper_decls(&a.src, &a.prog.decls).into_iter().find(|(n, _, _)| n == name).map(|(_, s, _)| s)
}

fn location(uri: &str, lines: &Lines, sp: Span) -> Json {
    Json::obj(vec![("uri", Json::str(uri)), ("range", lines.range(sp))])
}

fn definition(a: &Analysis, uri: &str, off: usize) -> Json {
    let lines = Lines::new(&a.src);
    match target_at(a, off) {
        Some(Target::Value(d, _, false)) => location(uri, &lines, a.res.defs[d].span),
        Some(Target::Ctor(n, _, false)) | Some(Target::Type(n, _, _)) => match first_upper_decl(a, &n) {
            Some(sp) => location(uri, &lines, sp),
            None => Json::Null,
        },
        _ => Json::Null,
    }
}

/// Every mention of what the cursor is on (the declaration included).
fn reference_spans(a: &Analysis, t: &Target) -> Vec<(Span, bool)> {
    let c = &a.res;
    match t {
        Target::Value(d, _, _) => {
            let mut v: Vec<(Span, bool)> = vec![(c.defs[*d].span, true)];
            for (sp, x) in c.uses.iter().chain(&c.redefs) {
                if x == d {
                    v.push((*sp, false));
                }
            }
            v.sort_by_key(|(s, _)| s.lo);
            v.dedup();
            v
        }
        Target::Measure(sp) => vec![(*sp, true)],
        Target::Builtin(n, _) => {
            let mut v: Vec<(Span, bool)> = c.builtin_uses.iter().filter(|(_, x)| x == n).map(|(s, _)| (*s, false)).collect();
            v.sort_by_key(|(s, _)| s.lo);
            v.dedup();
            v
        }
        Target::Unbound(n, _) => {
            let mut v: Vec<(Span, bool)> = c.unbound_uses.iter().filter(|(_, x)| x == n).map(|(s, _)| (*s, false)).collect();
            v.sort_by_key(|(s, _)| s.lo);
            v.dedup();
            v
        }
        Target::Ctor(n, _, _) => {
            let mut v: Vec<(Span, bool)> = Vec::new();
            for (name, sp, _) in upper_decls(&a.src, &a.prog.decls) {
                if &name == n {
                    v.push((sp, true));
                }
            }
            for (sp, name) in &c.ctor_uses {
                if name == n {
                    v.push((*sp, false));
                }
            }
            v.sort_by_key(|(s, _)| s.lo);
            v.dedup();
            v
        }
        Target::Type(n, _, _) => {
            let mut v: Vec<(Span, bool)> = Vec::new();
            for (sp, name) in &c.type_uses {
                if name == n {
                    v.push((*sp, false));
                }
            }
            v.sort_by_key(|(s, _)| s.lo);
            v.dedup();
            for (name, sp, is_type) in upper_decls(&a.src, &a.prog.decls) {
                if &name == n && is_type {
                    v.push((sp, true));
                    break;
                }
            }
            v
        }
    }
}

fn references(a: &Analysis, uri: &str, off: usize, include_decl: bool) -> Json {
    let lines = Lines::new(&a.src);
    let Some(t) = target_at(a, off) else { return Json::Arr(vec![]) };
    let spans = reference_spans(a, &t);
    Json::Arr(spans.into_iter().filter(|(_, d)| include_decl || !d).map(|(s, _)| location(uri, &lines, s)).collect())
}

/// Can the cursor's name be renamed? Returns its span.
fn renamable(a: &Analysis, off: usize) -> Option<(Span, Target)> {
    // a document that does not parse is not renamed
    if !a.syntax.is_empty() {
        return None;
    }
    let t = target_at(a, off)?;
    match &t {
        Target::Value(d, sp, _) => {
            // externs and library names stay as they are
            if a.res.defs[*d].external {
                return None;
            }
            Some((*sp, t))
        }
        // the program's own types, not the library's
        Target::Type(n, sp, _) if is_user_type(a, n) => Some((*sp, t)),
        _ => None,
    }
}

fn is_user_type(a: &Analysis, n: &str) -> bool {
    a.prog.decls.iter().any(|d| match d {
        Decl::Type(t) => t.name == n,
        Decl::ExternType(x, _, _, _) => x == n,
        _ => false,
    })
}

fn valid_name(n: &str, upper: bool) -> bool {
    let mut cs = n.chars();
    let Some(f) = cs.next() else { return false };
    let first_ok = if upper { f.is_ascii_uppercase() } else { f.is_ascii_lowercase() || f == '_' };
    first_ok && n.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') && !KEYWORDS.contains(&n) && !matches!(n, "elif" | "case" | "as" | "do" | "try" | "yield" | "import" | "module" | "opaque" | "for")
}

fn rename(a: &Analysis, uri: &str, off: usize, new_name: &str) -> Json {
    let lines = Lines::new(&a.src);
    let Some((_, t)) = renamable(a, off) else { return Json::Null };
    let upper = matches!(t, Target::Type(..));
    if !valid_name(new_name, upper) {
        return Json::Null;
    }
    let edits: Vec<Json> = reference_spans(a, &t)
        .into_iter()
        .map(|(s, _)| Json::obj(vec![("range", lines.range(s)), ("newText", Json::str(new_name))]))
        .collect();
    Json::obj(vec![("changes", Json::Obj(vec![(uri.to_string(), Json::Arr(edits))]))])
}

// ---- symbols ----------------------------------------------------------------

/// (name, symbol kind, completion kind, span)
pub fn symbols(src: &str, decls: &[Decl], prefix: &str) -> Vec<(String, i64, i64, Span)> {
    let mut out = Vec::new();
    for d in decls {
        match d {
            Decl::Let(l) => {
                if let Some(cases) = &l.active {
                    for (n, s) in active_case_spans(src, l, cases) {
                        out.push((n, 22, 4, s));
                    }
                    continue;
                }
                let mut vars = Vec::new();
                pat_vars(&l.pat, &mut vars);
                for (n, s) in vars {
                    out.push((format!("{}{}", prefix, n), 12, 12, s));
                }
            }
            Decl::Type(t) => {
                let kind = match &t.body {
                    TypeBody::Record(_) => 23,
                    _ => 10,
                };
                out.push((format!("{}{}", prefix, t.name), kind, 7, t.name_span));
                if let TypeBody::Sum(vs) = &t.body {
                    for v in vs {
                        out.push((format!("{}{}", prefix, v.name), 22, 4, v.span));
                    }
                }
            }
            Decl::Measure(n, _, sp) => out.push((n.clone(), 16, 11, *sp)),
            Decl::Extern(e) => out.push((e.name.clone(), 12, 3, e.span)),
            Decl::ExternType(n, _, sp, _) => {
                if let Some(s) = name_in(src, Span::new(sp.lo + 6, sp.hi), n) {
                    out.push((n.clone(), 10, 7, s));
                }
            }
            Decl::Import(n, sp) => out.push((n.clone(), 2, 9, *sp)),
            Decl::Module(m, _, ds) => {
                let p = format!("{}{}.", prefix, m);
                out.extend(symbols(src, ds, &p));
            }
            _ => {}
        }
    }
    out
}

/// Variables a pattern binds, with their spans, in order.
fn pat_vars(p: &Pat, out: &mut Vec<(String, Span)>) {
    match &p.kind {
        PatKind::Var(n) => out.push((n.clone(), p.span)),
        PatKind::Tuple(ps) | PatKind::Or(ps) => ps.iter().for_each(|x| pat_vars(x, out)),
        PatKind::Ctor(_, _, ps) => ps.iter().for_each(|x| pat_vars(x, out)),
        PatKind::List(es) => {
            for e in es {
                match e {
                    ListPatElem::Pat(x) => pat_vars(x, out),
                    ListPatElem::Star(Some(n), sp) => out.push((n.clone(), Span::new(sp.hi - n.len(), sp.hi))),
                    _ => {}
                }
            }
        }
        PatKind::Record(_, _, _, fs) => {
            for (f, fsp, sp) in fs {
                match sp {
                    Some(x) => pat_vars(x, out),
                    None => out.push((f.clone(), *fsp)),
                }
            }
        }
        PatKind::As(x, n, nsp) => {
            pat_vars(x, out);
            out.push((n.clone(), *nsp));
        }
        _ => {}
    }
}

fn document_symbols(a: &Analysis) -> Json {
    let lines = Lines::new(&a.src);
    Json::Arr(
        symbols(&a.src, &a.prog.decls, "")
            .into_iter()
            .map(|(n, k, _, s)| Json::obj(vec![("name", Json::Str(n)), ("kind", Json::int(k)), ("range", lines.range(s)), ("selectionRange", lines.range(s))]))
            .collect(),
    )
}

fn completion(a: Option<&Analysis>, builtin_items: &[Json]) -> Json {
    let mut items = Vec::new();
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
    if let Some(a) = a {
        for (n, _, k, _) in symbols(&a.src, &a.prog.decls, "") {
            if seen.insert(n.clone()) {
                items.push(Json::obj(vec![("label", Json::Str(n)), ("kind", Json::int(k))]));
            }
        }
    }
    // a name defined in the document hides the library's
    for it in builtin_items {
        let label = it.get("label").and_then(|l| l.as_str()).unwrap_or("").to_string();
        if seen.insert(label) {
            items.push(it.clone());
        }
    }
    Json::Arr(items)
}

fn builtin_completions() -> Vec<Json> {
    let c = Checker::new();
    let mut items = Vec::new();
    for b in BUILTINS {
        let ty = c.st.show(&c.builtins[b.name].ty);
        items.push(Json::obj(vec![
            ("label", Json::str(b.name)),
            ("kind", Json::int(3)),
            ("detail", Json::Str(ty)),
            ("documentation", Json::obj(vec![("kind", Json::str("markdown")), ("value", Json::str(b.doc))])),
        ]));
    }
    for n in ["Ok", "Error", "Some", "None"] {
        items.push(Json::obj(vec![("label", Json::str(n)), ("kind", Json::int(4))]));
    }
    for n in BUILTIN_TYPES {
        items.push(Json::obj(vec![("label", Json::str(n)), ("kind", Json::int(7))]));
    }
    for k in KEYWORDS {
        items.push(Json::obj(vec![("label", Json::str(k)), ("kind", Json::int(14))]));
    }
    items
}

// ---- workspace symbols -------------------------------------------------------

fn workspace_symbols(docs: &[(String, String)], query: &str) -> Json {
    let q = query.to_lowercase();
    // every .pyfun file on disk next to an open document, open ones as edited
    let mut dirs: Vec<PathBuf> = Vec::new();
    for (uri, _) in docs {
        if let Some(p) = uri_to_path(uri) {
            if let Some(d) = p.parent() {
                if !dirs.contains(&d.to_path_buf()) {
                    dirs.push(d.to_path_buf());
                }
            }
        }
    }
    let mut out = Vec::new();
    for d in dirs {
        let mut files: Vec<PathBuf> = match std::fs::read_dir(&d) {
            Ok(rd) => rd.filter_map(|e| e.ok()).map(|e| e.path()).filter(|p| p.extension().map_or(false, |x| x == "pyfun") && p.is_file()).collect(),
            Err(_) => Vec::new(),
        };
        // (an open document not on disk is not among them)
        files.sort();
        for f in files {
            let uri = path_to_uri(&f);
            let text = match docs.iter().find(|(u, _)| uri_to_path(u).as_deref() == Some(f.as_path())) {
                Some((_, t)) => t.clone(),
                None => match std::fs::read_to_string(&f) {
                    Ok(t) => t,
                    Err(_) => continue,
                },
            };
            let (prog, _, _) = crate::parser::parse_program_recover(&text);
            let lines = Lines::new(&text);
            for (n, k, _, s) in symbols(&text, &prog.decls, "") {
                if n.to_lowercase().contains(&q) {
                    out.push(Json::obj(vec![("name", Json::Str(n)), ("kind", Json::int(k)), ("location", location(&uri, &lines, s))]));
                }
            }
        }
    }
    Json::Arr(out)
}

// ---- the server ---------------------------------------------------------------

struct Server {
    docs: Vec<(String, String)>,
    builtin_items: Option<Vec<Json>>,
    /// the last analysis, for the document text it was made from
    cache: Option<(String, String, std::rc::Rc<Analysis>)>,
}

fn send(msg: &Json) {
    let body = msg.to_string();
    let mut out = std::io::stdout().lock();
    let _ = write!(out, "Content-Length: {}\r\n\r\n{}", body.len(), body);
    let _ = out.flush();
}

fn respond(id: &Json, result: Json) {
    send(&Json::obj(vec![("jsonrpc", Json::str("2.0")), ("id", id.clone()), ("result", result)]));
}

fn capabilities() -> Json {
    Json::obj(vec![
        (
            "capabilities",
            Json::obj(vec![
                ("textDocumentSync", Json::int(1)),
                ("hoverProvider", Json::Bool(true)),
                ("definitionProvider", Json::Bool(true)),
                ("referencesProvider", Json::Bool(true)),
                ("renameProvider", Json::obj(vec![("prepareProvider", Json::Bool(true))])),
                ("completionProvider", Json::Obj(vec![])),
                ("documentSymbolProvider", Json::Bool(true)),
                ("workspaceSymbolProvider", Json::Bool(true)),
            ]),
        ),
        ("serverInfo", Json::obj(vec![("name", Json::str("pyfun-lsp")), ("version", Json::str(crate::VERSION))])),
    ])
}

impl Server {
    fn text(&self, uri: &str) -> Option<&String> {
        self.docs.iter().find(|(u, _)| u == uri).map(|(_, t)| t)
    }

    fn set_text(&mut self, uri: &str, text: String) {
        match self.docs.iter_mut().find(|(u, _)| u == uri) {
            Some(slot) => slot.1 = text,
            None => self.docs.push((uri.to_string(), text)),
        }
    }

    fn publish(&mut self, uri: &str) {
        let diags = match self.analysis(uri) {
            Some(a) => {
                let lines = Lines::new(&a.src);
                a.diagnostics()
                    .iter()
                    .map(|d| {
                        Json::obj(vec![
                            ("range", lines.range(d.span)),
                            ("severity", Json::int(if d.severity == Severity::Error { 1 } else { 3 })),
                            ("source", Json::str("pyfun")),
                            ("message", Json::Str(d.msg.clone())),
                        ])
                    })
                    .collect()
            }
            None => Vec::new(),
        };
        send(&Json::obj(vec![
            ("jsonrpc", Json::str("2.0")),
            ("method", Json::str("textDocument/publishDiagnostics")),
            ("params", Json::obj(vec![("uri", Json::str(uri)), ("diagnostics", Json::Arr(diags))])),
        ]));
    }

    fn analysis(&mut self, uri: &str) -> Option<std::rc::Rc<Analysis>> {
        let text = self.text(uri)?.clone();
        if let Some((u, t, a)) = &self.cache {
            if u == uri && *t == text {
                return Some(a.clone());
            }
        }
        let a = std::rc::Rc::new(analyze(uri, &text));
        self.cache = Some((uri.to_string(), text, a.clone()));
        Some(a)
    }

    /// The analysis of a request's document and the offset of its position.
    fn at(&mut self, params: Option<&Json>) -> Option<(String, std::rc::Rc<Analysis>, Option<usize>)> {
        let p = params?;
        let uri = p.path(&["textDocument", "uri"])?.as_str()?.to_string();
        let a = self.analysis(&uri)?;
        let off = (|| {
            // anything but a number counts as 0
            let num = |k: &str| p.path(&["position", k]).and_then(|v| v.as_f64()).unwrap_or(0.0);
            let (line, ch) = (num("line"), num("character"));
            if line < 0.0 || ch < 0.0 {
                return None;
            }
            Lines::new(&a.src).offset(line as usize, ch as usize)
        })();
        Some((uri, a, off))
    }

    fn handle(&mut self, msg: &Json) {
        let Some(method) = msg.get("method").and_then(|m| m.as_str()) else { return };
        let id = msg.get("id");
        let params = msg.get("params");
        match method {
            "initialize" => {
                if let Some(id) = id {
                    respond(id, capabilities());
                }
            }
            "shutdown" => {
                if let Some(id) = id {
                    respond(id, Json::Null);
                }
            }
            "exit" => std::process::exit(0),
            "textDocument/didOpen" => {
                let Some(td) = params.and_then(|p| p.get("textDocument")) else { return };
                let (Some(uri), Some(text)) = (td.get("uri").and_then(|u| u.as_str()), td.get("text").and_then(|t| t.as_str())) else { return };
                let uri = uri.to_string();
                self.set_text(&uri, text.to_string());
                self.publish(&uri);
            }
            "textDocument/didChange" => {
                let Some(p) = params else { return };
                let Some(uri) = p.path(&["textDocument", "uri"]).and_then(|u| u.as_str()) else { return };
                let uri = uri.to_string();
                let Some(changes) = p.get("contentChanges").and_then(|c| c.as_arr()) else { return };
                // full sync: the last change carries the whole text
                let Some(text) = changes.last().and_then(|c| c.get("text")).and_then(|t| t.as_str()) else { return };
                self.set_text(&uri, text.to_string());
                self.publish(&uri);
            }
            "textDocument/didClose" => {
                let Some(uri) = params.and_then(|p| p.path(&["textDocument", "uri"])).and_then(|u| u.as_str()) else { return };
                let uri = uri.to_string();
                self.docs.retain(|(u, _)| *u != uri);
                self.publish(&uri);
            }
            "textDocument/hover" => {
                let r = match self.at(params) {
                    Some((_, a, Some(off))) => hover(&a, off),
                    _ => Json::Null,
                };
                if let Some(id) = id {
                    respond(id, r);
                }
            }
            "textDocument/definition" => {
                let r = match self.at(params) {
                    Some((uri, a, Some(off))) => definition(&a, &uri, off),
                    _ => Json::Null,
                };
                if let Some(id) = id {
                    respond(id, r);
                }
            }
            "textDocument/references" => {
                let include = params.and_then(|p| p.path(&["context", "includeDeclaration"])).and_then(|b| b.as_bool()).unwrap_or(true);
                let r = match self.at(params) {
                    Some((uri, a, Some(off))) => references(&a, &uri, off, include),
                    _ => Json::Arr(vec![]),
                };
                if let Some(id) = id {
                    respond(id, r);
                }
            }
            "textDocument/prepareRename" => {
                let r = match self.at(params) {
                    Some((_, a, Some(off))) => match renamable(&a, off) {
                        Some((sp, _)) => Lines::new(&a.src).range(sp),
                        None => Json::Null,
                    },
                    _ => Json::Null,
                };
                if let Some(id) = id {
                    respond(id, r);
                }
            }
            "textDocument/rename" => {
                let new_name = params.and_then(|p| p.get("newName")).and_then(|n| n.as_str()).unwrap_or("").to_string();
                let r = match self.at(params) {
                    Some((uri, a, Some(off))) => rename(&a, &uri, off, &new_name),
                    _ => Json::Null,
                };
                if let Some(id) = id {
                    respond(id, r);
                }
            }
            "textDocument/completion" => {
                if self.builtin_items.is_none() {
                    self.builtin_items = Some(builtin_completions());
                }
                let a = self.at(params).map(|(_, a, _)| a);
                let r = completion(a.as_deref(), self.builtin_items.as_ref().unwrap());
                if let Some(id) = id {
                    respond(id, r);
                }
            }
            "textDocument/documentSymbol" => {
                let r = match self.at(params) {
                    Some((_, a, _)) => document_symbols(&a),
                    None => Json::Arr(vec![]),
                };
                if let Some(id) = id {
                    respond(id, r);
                }
            }
            "workspace/symbol" => {
                let q = params.and_then(|p| p.get("query")).and_then(|q| q.as_str()).unwrap_or("").to_string();
                let r = workspace_symbols(&self.docs, &q);
                if let Some(id) = id {
                    respond(id, r);
                }
            }
            _ => {
                if let Some(id) = id {
                    send(&Json::obj(vec![
                        ("jsonrpc", Json::str("2.0")),
                        ("id", id.clone()),
                        ("error", Json::obj(vec![("code", Json::int(-32601)), ("message", Json::str("method not found"))])),
                    ]));
                }
            }
        }
    }
}

/// Read one message's headers; the body length, or None at the end.
fn read_headers(r: &mut impl BufRead) -> Option<usize> {
    let mut len: Option<usize> = None;
    let mut bad = false;
    loop {
        let mut line = Vec::new();
        match r.read_until(b'\n', &mut line) {
            Ok(0) | Err(_) => return None,
            Ok(_) => {}
        }
        let text = String::from_utf8_lossy(&line);
        let t = text.trim();
        if t.is_empty() {
            break;
        }
        if let Some(v) = t.strip_prefix("Content-Length:") {
            match v.trim().parse::<usize>() {
                Ok(n) => len = Some(n),
                Err(_) => bad = true,
            }
        }
    }
    if bad {
        return None;
    }
    len
}

pub fn run_lsp() -> ! {
    let stdin = std::io::stdin();
    let mut input = stdin.lock();
    let mut server = Server { docs: Vec::new(), builtin_items: None, cache: None };
    loop {
        let Some(n) = read_headers(&mut input) else { std::process::exit(0) };
        let mut body = vec![0u8; n];
        if let Err(e) = input.read_exact(&mut body) {
            eprintln!("error: lsp server error: {}", e);
            std::process::exit(1);
        }
        let Ok(text) = String::from_utf8(body) else { continue };
        let Some(msg) = json::parse(&text) else { continue };
        server.handle(&msg);
    }
}

#[allow(dead_code)]
fn unused(_: &[usize]) -> usize {
    NO_DEF
}
