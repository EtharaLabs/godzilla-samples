// An incremental session shared by the REPL and the Jupyter kernel engine:
// every input is checked and compiled together with the definitions entered
// before it, and only the new code (plus infrastructure not yet sent) is
// handed to Python.

use crate::ast::*;
use crate::diag::{render, Diag};
use crate::infer::Checker;
use crate::lower::Lowerer;
use crate::py::*;
use crate::types::Ty;
use std::collections::HashSet;

#[derive(Clone, Copy, PartialEq)]
pub enum Mode {
    Repl,
    Kernel,
}

pub struct Session {
    pub mode: Mode,
    pub entries: Vec<String>,
    /// infrastructure chunks already sent to Python
    pub sent: HashSet<String>,
    /// a definition in the session has code (the module is not empty)
    pub code_sent: bool,
    /// the code chunks the session's entries ran
    pub known: HashSet<String>,
}

pub enum EvalErr {
    /// a parse error of the input on its own
    Parse(String),
    /// type errors in the session
    Type(Vec<String>),
    /// compile errors (unfilled holes); echoes were computed
    Compile(Vec<String>, Vec<String>),
}

pub struct EvalOk {
    pub echoes: Vec<String>,
    pub code: String,
    /// the input was stored as a session entry
    pub stored: bool,
    /// every definition repeated one already entered
    pub all_dup: bool,
    /// the code is the `pass` an expression with nothing to run stands for
    pub fallback_pass: bool,
}

pub fn session_source(entries: &[String], input: &str) -> String {
    let mut s = String::from("\n");
    for e in entries {
        s.push_str(e);
        s.push('\n');
    }
    s.push_str(input);
    s
}

fn is_unit(t: &Ty) -> bool {
    matches!(t, Ty::Con(n, _) if n == "unit")
}

/// Split infrastructure text into top-level chunks.
pub fn chunks(text: &str) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let mut cur = String::new();
    let mut in_decorator = false;
    for line in text.split_inclusive('\n') {
        let top = !line.starts_with(' ') && !line.starts_with('\t');
        if top && !in_decorator && !cur.is_empty() {
            out.push(std::mem::take(&mut cur));
        }
        in_decorator = line.starts_with('@');
        cur.push_str(line);
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

fn dedupable(chunk: &str) -> bool {
    chunk.starts_with("import ")
        || chunk.starts_with("from ")
        || chunk.starts_with('@')
        || chunk.starts_with("class ")
        || chunk.starts_with("def ")
        || chunk.starts_with("async def ")
}

impl Session {
    pub fn new(mode: Mode) -> Session {
        Session { mode, entries: Vec::new(), sent: HashSet::new(), code_sent: false, known: HashSet::new() }
    }

    pub fn reset(&mut self) {
        self.entries.clear();
        self.sent.clear();
        self.code_sent = false;
        self.known.clear();
    }

    /// Compile every definition of the session as one module (for rebuilding
    /// a restarted worker).
    pub fn rebuild_code(&mut self) -> Option<String> {
        if self.entries.is_empty() {
            return None;
        }
        let src = session_source(&self.entries, "");
        let prog = crate::parser::parse_program(&src).ok()?;
        let mut c = Checker::new();
        c.check_program(&prog);
        let mut l = Lowerer::new(&c);
        l.collect_ordering();
        let code = l.lower_program(&prog.decls);
        let text = l.assemble(&prog.decls, &code);
        self.sent.clear();
        for ch in chunks(&text) {
            if dedupable(&ch) {
                self.sent.insert(ch);
            }
        }
        Some(text)
    }

    pub fn eval(&mut self, input: &str, block: bool) -> Result<EvalOk, EvalErr> {
        self.eval_part(input, block, false)
    }

    /// `head`: every declaration of the input is entered (a kernel cell's
    /// part before its trailing expression), expressions as statements.
    pub fn eval_part(&mut self, input: &str, block: bool, head: bool) -> Result<EvalOk, EvalErr> {
        // (a kernel cell's head is only read after the session's text)
        let parsed = match crate::parser::parse_program(input) {
            Ok(p) => Some(p),
            Err(_) if head => None,
            Err(d) => return Err(EvalErr::Parse(render(input, &d))),
        };
        let src = session_source(&self.entries, input);
        // (an input that parses alone but not after the session's text is
        // reported like the session's other errors: every one the text has)
        let prog = match crate::parser::parse_program(&src) {
            Ok(p) => p,
            Err(d) => {
                let (_, mut all, parse_errors) = crate::parser::parse_program_recover(&src);
                all.extend(parse_errors);
                all.sort_by_key(|d| d.span.lo);
                if all.is_empty() {
                    all.push(d);
                }
                return Err(EvalErr::Type(all.iter().map(|d| render(&src, d)).collect()));
            }
        };
        let k = match &parsed {
            Some(p) => p.decls.len(),
            None => {
                let lo = src.len() - input.len();
                prog.decls.iter().filter(|d| decl_span(d).lo >= lo).count()
            }
        };
        let n = prog.decls.len();
        let first = n.saturating_sub(k);
        // the kind of input (as the input reads on its own)
        // (an assignment is an expression too)
        let last_expr = match parsed.as_ref().and_then(|p| p.decls.last()) {
            Some(Decl::Expr(e)) => Some(e.span.lo),
            Some(Decl::Assign(_, _, _, whole)) => Some(whole.lo),
            _ => None,
        };
        let trailing_expr = k > 0 && last_expr.is_some();
        let expr_only = k == 1 && trailing_expr;
        let _ = block;
        let (defs_end, trailing) = match self.mode {
            Mode::Repl => {
                if expr_only {
                    (first, true)
                } else {
                    (n, false)
                }
            }
            Mode::Kernel => {
                if trailing_expr && !head {
                    (n.saturating_sub(1).max(first), true)
                } else {
                    (n, false)
                }
            }
        };
        let mut c = Checker::new();
        c.source = src.clone();
        c.check_program(&prog);
        if !c.errors.is_empty() {
            let errs = c.errors.iter().map(|d| render(&src, d)).collect();
            return Err(EvalErr::Type(errs));
        }
        // echoes for the input's let bindings
        let mut echoes = Vec::new();
        for d in &prog.decls[first..defs_end] {
            if let Decl::Let(l) = d {
                if l.active.is_some() {
                    continue;
                }
                match &l.pat.kind {
                    PatKind::Var(name) => {
                        let t = c.binding_types.get(&crate::infer::key(l.name_span)).cloned();
                        let shown = match t {
                            Some(t) => {
                                let s = if l.mutable { crate::types::Scheme::mono(t) } else { generalize_display(&mut c, &t) };
                                c.st.show(&s.ty)
                            }
                            None => c.globals.get(name).map(|g| c.st.show(&g.scheme.ty)).unwrap_or_default(),
                        };
                        echoes.push(format!("{} : {}", name, shown));
                    }
                    _ => {
                        let mut names = Vec::new();
                        crate::check_decl::pat_names(&l.pat, &mut names);
                        for nm in names {
                            if let Some(g) = c.globals.get(&nm) {
                                echoes.push(format!("{} : {}", nm, c.st.show(&g.scheme.ty)));
                            }
                        }
                    }
                }
            }
        }
        // a value to print is compiled as `print (…)`: the session is read
        // again with the input's expression wrapped (the rest of the input
        // goes inside the parentheses), and what that reading finds is
        // reported against it
        let input_lo = src.len() - input.len();
        let unit_last = match prog.decls.last() {
            Some(Decl::Expr(e)) => c.expr_types.get(&crate::infer::key(e.span)).map_or(false, |t| is_unit(&c.st.resolve(t))),
            Some(Decl::Assign(..)) => true,
            _ => false,
        };
        let (src, prog, c) = match last_expr {
            Some(lo) if trailing && !unit_last => {
                let at = input_lo + lo;
                let wrapped = format!("{}print ({})", &src[..at], &src[at..]);
                let wprog = match crate::parser::parse_program(&wrapped) {
                    Ok(p) => p,
                    Err(d) => return Err(EvalErr::Compile(echoes, vec![render(&wrapped, &d)])),
                };
                let mut wc = Checker::new();
                wc.source = wrapped.clone();
                wc.check_program(&wprog);
                if !wc.errors.is_empty() {
                    let errs = wc.errors.iter().map(|d| render(&wrapped, d)).collect();
                    return Err(EvalErr::Compile(echoes, errs));
                }
                (wrapped, wprog, wc)
            }
            _ => (src, prog, c),
        };
        let n = prog.decls.len();
        let first = n.saturating_sub(k);
        let defs_end = if trailing { if expr_only && self.mode == Mode::Repl { first } else { n.saturating_sub(1).max(first) } } else { n };
        // a hole blocks compilation (the first one met is reported)
        if let Some(h) = c.holes.iter().find(|h| h.span.lo >= input_lo) {
            let t = c.st.show(&h.ty);
            let name = match &h.name {
                Some(n) => format!("?{}", n),
                None => "?".to_string(),
            };
            let sugg = crate::holes::suggest_text(&c, h);
            let msg = format!("cannot compile: unfilled hole `{}` has type `{}`{} (fill it in)", name, t, sugg);
            return Err(EvalErr::Compile(echoes, vec![render(&src, &Diag::error(msg, h.span))]));
        }
        // texts of the definitions already in the session
        let prev_texts: HashSet<&str> = prog.decls[..first].iter().filter(|d| !matches!(d, Decl::Assign(..))).map(|d| decl_text(&src, d)).collect();
        let mut l = Lowerer::new(&c);
        l.collect_ordering();
        l.bind_externs(&prog.decls);
        l.collect_top_binds(&prog.decls);
        l.prepare_shadowing(&prog.decls);
        // (what the session's earlier definitions compile to was sent with
        // them, but a definition the input's own reading did not count, one
        // the session reads apart from it, is sent now)
        let printer = Printer { py311: false };
        let mut body = String::new();
        let mut new_known: Vec<String> = Vec::new();
        let mut kept = crate::lower::Needs::default();
        for d in &prog.decls[..first] {
            let saved = std::mem::take(&mut l.needs);
            let stmts = l.lower_decl(d, None);
            let needs = std::mem::replace(&mut l.needs, saved);
            if matches!(d, Decl::Assign(..)) {
                continue;
            }
            let mut text = String::new();
            printer.stmts(&stmts, 0, &mut text);
            let mut sent = false;
            for ch in chunks(&text) {
                if self.known.contains(&ch) || new_known.contains(&ch) {
                    continue;
                }
                body.push_str(&ch);
                new_known.push(ch);
                sent = true;
            }
            if sent {
                kept.merge(needs);
            }
        }
        l.needs = Default::default();
        l.collect_ordering();
        l.needs.merge(kept);
        // code already run for an earlier entry (a statement or definition
        // with the same text) is not run again; assignments always run
        let mut type_decls: Vec<Decl> = Vec::new();
        for (i, d) in prog.decls.iter().enumerate().skip(first) {
            // (the trailing expression is wrapped in `print` unless unit)
            let stmts = l.lower_decl(d, None);
            if i < defs_end && matches!(d, Decl::Type(_)) {
                type_decls.push(d.clone());
            }
            let mut text = String::new();
            printer.stmts(&stmts, 0, &mut text);
            let assign = matches!(d, Decl::Assign(..));
            for ch in chunks(&text) {
                if !assign && self.known.contains(&ch) {
                    continue;
                }
                body.push_str(&ch);
                if !assign && i < defs_end {
                    new_known.push(ch);
                }
            }
        }
        if let Some(msg) = l.error.take() {
            let d = crate::diag::Diag::error(msg, crate::source::Span::new(0, 0));
            return Err(EvalErr::Compile(echoes, vec![render("", &d)]));
        }
        // every type of the session: a class whose text changed (ordering
        // became needed) goes again; the others were sent already
        let _ = &type_decls;
        // (active patterns' case classes keep their places among the types)
        let all_types: Vec<Decl> = prog.decls.iter().filter(|d| matches!(d, Decl::Type(_)) || matches!(d, Decl::Let(l) if l.active.is_some())).cloned().collect();
        let types_text = l.type_classes(&all_types);
        let parts = l.parts(types_text);
        // infrastructure (imports, classes, helpers) goes once; other lines
        // of it (a shared instance) like any code an entry ran
        let stores = defs_end > first;
        let mut out = String::new();
        for ch in chunks(&parts.prelude).into_iter().chain(chunks(&parts.types)).chain(chunks(&parts.codecs)) {
            if dedupable(&ch) {
                if self.sent.contains(&ch) {
                    continue;
                }
                self.sent.insert(ch.clone());
            } else {
                if self.known.contains(&ch) {
                    continue;
                }
                if stores {
                    new_known.push(ch.clone());
                }
            }
            out.push_str(&ch);
        }
        out.push_str(&body);
        let all_dup = defs_end > first && (first..defs_end).all(|i| !matches!(prog.decls[i], Decl::Assign(..)) && prev_texts.contains(decl_text(&src, &prog.decls[i])));
        // nothing to run: an expression stands for `pass`; a module with no
        // code at all is `pass`, sent once like any other chunk (the
        // session's definitions are part of that module)
        let mut fallback_pass = false;
        if out.is_empty() && !all_dup && !self.code_sent {
            if trailing && defs_end == first {
                out.push_str("pass\n");
                fallback_pass = true;
            } else if !self.sent.contains("pass\n") {
                out.push_str("pass\n");
                self.sent.insert("pass\n".to_string());
            }
        }
        if !out.is_empty() && defs_end > first && out != "pass\n" {
            self.code_sent = true;
        }
        // remember the definitions
        // (an input of only comments is entered too: it keeps its lines)
        let stored = defs_end > first || k == 0;
        if stored {
            self.known.extend(new_known);
            self.entries.push(input.to_string());
        }
        Ok(EvalOk { echoes, code: out, stored, all_dup, fallback_pass })
    }

    /// `:type expr` / the kernel's `type` op.
    pub fn type_of(&mut self, expr: &str) -> Result<String, Vec<String>> {
        let src = session_source(&self.entries, expr);
        let lexed = crate::lexer::lex(&src);
        let mut diags: Vec<Diag> = Vec::new();
        if let Some(e) = lexed.error.clone() {
            diags.push(e);
        }
        let mut p = crate::parser::Parser::new(lexed.toks, lexed.docs);
        let prog = p.program();
        let prog = match prog {
            Ok(pr) => Some(pr),
            Err(d) => {
                diags.push(d);
                None
            }
        };
        if !diags.is_empty() {
            diags.sort_by_key(|d| d.span.lo);
            return Err(diags.iter().map(|d| render(&src, d)).collect());
        }
        let prog = prog.unwrap();
        let k = match crate::parser::parse_program(expr) {
            Ok(p) => p.decls.len(),
            Err(_) => 0,
        };
        let n = prog.decls.len();
        // the session is checked first: its errors come before the question
        // of whether the input is an expression
        let mut c = Checker::new();
        c.check_program(&prog);
        if !c.errors.is_empty() {
            return Err(c.errors.iter().map(|d| render(&src, d)).collect());
        }
        let is_expr = k == 1 && matches!(prog.decls.last(), Some(Decl::Expr(_)));
        if !is_expr {
            return Err(vec![format!("(could not determine a type — is `{}` an expression?)", expr.trim())]);
        }
        let Some(Decl::Expr(e)) = prog.decls.get(n - 1) else { unreachable!() };
        let t = c.expr_types.get(&crate::infer::key(e.span)).cloned();
        let shown = match t {
            Some(t) => {
                let s = generalize_display(&mut c, &t);
                c.st.show(&s.ty)
            }
            None => String::from("?"),
        };
        Ok(format!("{} : {}", expr.trim(), shown))
    }
}

/// Generalize a type for display (free variables become 'a, 'b, ...).
pub fn generalize_display(c: &mut Checker, t: &Ty) -> crate::types::Scheme {
    let saved = c.st.level;
    c.st.level = 0;
    let s = c.st.generalize(t);
    c.st.level = saved;
    s
}

pub fn decl_text<'s>(src: &'s str, d: &Decl) -> &'s str {
    let span = decl_span(d);
    &src[span.lo.min(src.len())..span.hi.min(src.len())]
}

fn decl_span(d: &Decl) -> crate::source::Span {
    match d {
        Decl::Let(l) => l.span,
        Decl::Type(t) => t.span,
        Decl::Measure(_, _, s) => *s,
        Decl::Extern(e) => e.span,
        Decl::ExternType(_, _, s, _) => *s,
        Decl::ExternImport(_, _, s) => *s,
        Decl::Module(_, s, _) => *s,
        Decl::Import(_, s) => *s,
        Decl::Expr(e) => e.span,
        Decl::Assign(_, _, _, whole) => *whole,
    }
}
