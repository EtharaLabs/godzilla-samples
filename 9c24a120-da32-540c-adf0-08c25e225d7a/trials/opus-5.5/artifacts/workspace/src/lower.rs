// Lowering: typed AST -> Python AST.

use crate::ast::*;
use crate::builtins::BUILTINS;
use crate::infer::*;
use crate::py::*;
use crate::types::*;
use std::collections::{BTreeSet, HashMap, HashSet};

pub const PY_KEYWORDS: &[&str] = &[
    "False", "None", "True", "and", "as", "assert", "async", "await", "break", "class", "continue", "def", "del", "elif", "else", "except", "finally", "for", "from",
    "global", "if", "import", "in", "is", "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try", "while", "with", "yield",
];
pub const MANGLED_BUILTINS: &[&str] = &[
    "bool", "bytearray", "bytes", "complex", "dict", "filter", "float", "frozenset", "int", "isinstance", "iter", "len", "list", "map", "memoryview", "next", "object",
    "range", "reversed", "set", "slice", "sorted", "str", "sum", "tuple", "zip",
];

pub fn mangle(n: &str) -> String {
    if PY_KEYWORDS.contains(&n) || MANGLED_BUILTINS.contains(&n) {
        format!("{}_", n)
    } else {
        n.to_string()
    }
}

#[derive(Clone, Debug)]
pub enum BKind {
    /// a `def` (or lambda-valued let) taking this many arguments
    Fn(usize),
    /// any other value: called with all its arguments at once
    Value,
    Extern(usize),
}

#[derive(Clone, Debug)]
pub struct Bind {
    pub py: String,
    pub kind: BKind,
    pub mutable: bool,
    /// scope depth where defined (0 = module)
    pub depth: usize,
}

#[derive(Clone, Debug, Default)]
pub struct Needs {
    pub helpers: BTreeSet<String>,
    pub imports: BTreeSet<String>,
    pub option: bool,
    pub result: bool,
    pub exception: bool,
    pub functools: bool,
    pub ordered_option: bool,
    pub ordered_result: bool,
    pub ordered_types: BTreeSet<String>,
    pub total_ordering: bool,
    pub dataclass: bool,
    pub codecs: Vec<String>,
    /// an annotation reads `Any` (`--native`)
    pub any: bool,
}

impl Needs {
    /// Everything `other` needs is needed too.
    pub fn merge(&mut self, other: Needs) {
        self.helpers.extend(other.helpers);
        self.imports.extend(other.imports);
        self.option |= other.option;
        self.result |= other.result;
        self.exception |= other.exception;
        self.functools |= other.functools;
        self.ordered_option |= other.ordered_option;
        self.ordered_result |= other.ordered_result;
        self.ordered_types.extend(other.ordered_types);
        self.total_ordering |= other.total_ordering;
        self.dataclass |= other.dataclass;
        for c in other.codecs {
            if !self.codecs.contains(&c) {
                self.codecs.push(c);
            }
        }
        self.any |= other.any;
    }
}

pub struct ExternInfo {
    pub decl: ExternDecl,
    pub arity: usize,
    /// argument positions that are thunks (`unit -> a`)
    pub thunks: Vec<usize>,
    /// returns Async (awaitable call, re-run per await)
    pub async_result: bool,
}

pub struct Lowerer<'a> {
    pub ck: &'a Checker,
    pub tmp: usize,
    pub fnc: usize,
    pub pre: Vec<PS>,
    pub scopes: Vec<HashMap<String, Bind>>,
    pub needs: Needs,
    /// the `let` being lowered is a module-level declaration (`--native`
    /// annotates its signature)
    pub annotate_top: bool,
    /// how often each name is bound at the top level (a name bound more
    /// than once keeps no annotation)
    pub top_binds: HashMap<String, usize>,
    /// the program has code (not only declarations of types and externs):
    /// its sum types get union aliases under `--native`
    pub has_code: bool,
    /// the module ends up with the Option / Result classes
    pub have_option: bool,
    pub have_result: bool,
    pub externs: HashMap<String, ExternInfo>,
    pub extern_imports: Vec<(Vec<String>, Option<String>)>,
    /// names assigned in the current function that live in an outer scope
    pub fn_stack: Vec<FnFrame>,
    pub module_names: HashMap<String, String>,
    pub in_module: Option<String>,
    pub py311: bool,
    pub native: bool,
    /// user CE builder modules
    pub user_modules: HashSet<String>,
    pub project_modules: HashMap<String, String>,
    /// the imported modules the code refers to (only those are imported)
    pub used_modules: std::cell::RefCell<HashSet<String>>,
    /// argument substitution for a partially applied lambda literal
    pub subst: Vec<HashMap<String, PE>>,
    /// lowering the operand of an await
    pub awaiting: bool,
    pub module_arities: HashMap<String, usize>,
    /// active patterns in declaration order (their case names)
    pub active_order: Vec<Vec<String>>,
    /// every user type gets ordering (projects)
    pub all_ordered: bool,
    /// function definitions by Python name (for inlining fold steps)
    pub fn_asts: HashMap<String, std::rc::Rc<(Vec<Pat>, Expr)>>,
    pub fold_depth: usize,
    /// immutable value bindings by Python name (for static decoders)
    pub value_asts: HashMap<String, Expr>,
    /// part of a multi-module project
    pub project: bool,
    /// (module file stem, local alias) for each import
    pub module_imports: Vec<(String, String)>,
    pub uses_rt: bool,
    pub rt_imports: String,
    /// a construct the lowering could not express
    pub error: Option<String>,
    /// binding sites that take a fresh name (they would overwrite an
    /// enclosing variable still in use), and the name
    pub renamed: HashMap<crate::shadow::Key, String>,
    /// the temporaries `Dest::Fresh` matches settled on (innermost last)
    pub fresh_tmp: Vec<String>,
}

#[derive(Default, Clone)]
pub struct FnFrame {
    pub depth: usize,
    pub globals: Vec<String>,
    pub nonlocals: Vec<String>,
    /// tail-call target: (name, params)
    pub self_name: Option<String>,
    /// self tail calls become parameter reassignment + `continue`
    pub tce: Option<(String, Vec<String>)>,
    /// the names the function binds anywhere in its body (Python makes
    /// them its own)
    pub bound: HashSet<String>,
}

fn builtin(name: &str) -> Option<&'static crate::builtins::Builtin> {
    BUILTINS.iter().find(|b| b.name == name)
}

pub fn ctor_py(name: &str) -> String {
    if name == "None" {
        "None_".into()
    } else {
        name.to_string()
    }
}

impl<'a> Lowerer<'a> {
    pub fn new(ck: &'a Checker) -> Lowerer<'a> {
        Lowerer {
            ck,
            tmp: 0,
            fnc: 0,
            pre: Vec::new(),
            scopes: vec![HashMap::new()],
            needs: Needs::default(),
            annotate_top: false,
            top_binds: HashMap::new(),
            has_code: false,
            have_option: false,
            have_result: false,
            externs: HashMap::new(),
            extern_imports: Vec::new(),
            fn_stack: Vec::new(),
            module_names: HashMap::new(),
            in_module: None,
            py311: false,
            native: false,
            user_modules: HashSet::new(),
            project_modules: HashMap::new(),
            used_modules: std::cell::RefCell::new(HashSet::new()),
            subst: Vec::new(),
            awaiting: false,
            module_arities: HashMap::new(),
            active_order: Vec::new(),
            all_ordered: false,
            fn_asts: HashMap::new(),
            fold_depth: 0,
            value_asts: HashMap::new(),
            project: false,
            module_imports: Vec::new(),
            uses_rt: false,
            rt_imports: String::new(),
            error: None,
            renamed: HashMap::new(),
            fresh_tmp: Vec::new(),
        }
    }

    /// Work out which nested bindings must not reuse their names.
    pub fn prepare_shadowing(&mut self, decls: &[Decl]) {
        let mut referenced = HashSet::new();
        let mut uses = Vec::new();
        for (u, d) in &self.ck.ide.uses {
            if let Some(def) = self.ck.ide.defs.get(*d) {
                referenced.insert((def.span.lo, def.span.hi));
                uses.push((*u, def.name.clone(), (def.span.lo, def.span.hi)));
            }
        }
        let mut sh = crate::shadow::Shadow::new(&referenced, &uses);
        sh.program(decls);
        self.renamed = sh.renamed;
    }

    /// Bind a pattern or `let` variable defined at `span`, under a fresh
    /// name when it would overwrite an enclosing variable still in use (an
    /// or-pattern's later alternatives reuse the first one's name).
    pub fn bind_site(&mut self, n: &str, span: crate::source::Span) -> String {
        self.bind_site_as(n, span, BKind::Value, false)
    }

    pub fn bind_site_as(&mut self, n: &str, span: crate::source::Span, kind: BKind, mutable: bool) -> String {
        let Some(py) = self.renamed.get(&(span.lo, span.hi)).cloned() else {
            return self.bind(n, kind, mutable);
        };
        let depth = self.depth();
        self.scopes.last_mut().unwrap().insert(n.to_string(), Bind { py: py.clone(), kind, mutable, depth });
        py
    }

    /// Something the lowering cannot express; the first one is reported.
    pub fn fail_lowering(&mut self, msg: &str) {
        if self.error.is_none() {
            self.error = Some(msg.to_string());
        }
    }

    /// A `case` guard: an expression that needs no statements before it.
    pub fn guard_expr(&mut self, g: &Expr) -> PE {
        let saved = std::mem::take(&mut self.pre);
        let v = self.expr(g);
        let pre = std::mem::replace(&mut self.pre, saved);
        if !pre.is_empty() {
            self.fail_lowering("a `case` guard must be a simple expression");
        }
        v
    }

    pub fn new_tmp(&mut self) -> String {
        let n = format!("_pf_t{}", self.tmp);
        self.tmp += 1;
        n
    }
    pub fn new_fn(&mut self) -> String {
        let n = format!("_pf_fn{}", self.fnc);
        self.fnc += 1;
        n
    }

    pub fn helper(&mut self, h: &str) {
        self.needs.helpers.insert(h.to_string());
    }

    pub fn depth(&self) -> usize {
        self.scopes.len() - 1
    }

    pub fn bind(&mut self, n: &str, kind: BKind, mutable: bool) -> String {
        let py = mangle(n);
        let depth = self.depth();
        self.scopes.last_mut().unwrap().insert(n.to_string(), Bind { py: py.clone(), kind, mutable, depth });
        py
    }

    pub fn lookup(&self, n: &str) -> Option<&Bind> {
        for s in self.scopes.iter().rev() {
            if let Some(b) = s.get(n) {
                return Some(b);
            }
        }
        None
    }

    // ---- types from the checker -------------------------------------------

    /// The Python name an imported module goes by, noting that it is used.
    pub fn module_alias(&self, m: &str) -> Option<&String> {
        let a = self.project_modules.get(m);
        if let Some(a) = a {
            self.used_modules.borrow_mut().insert(a.clone());
        }
        a
    }

    pub fn ty_of(&self, span: crate::source::Span) -> Option<Ty> {
        self.ck.expr_types.get(&key(span)).map(|t| self.ck.st.resolve(t))
    }

    pub fn pat_ty(&self, span: crate::source::Span) -> Option<Ty> {
        self.ck.pat_types.get(&key(span)).map(|t| self.ck.st.resolve(t))
    }

    fn lit_is_float(&self, span: crate::source::Span) -> bool {
        match self.ck.lit_kinds.get(&key(span)) {
            Some(k) => self.ck.st.kind(*k) == Kind::Float,
            None => false,
        }
    }

    // ---- expressions ------------------------------------------------------

    pub fn expr(&mut self, e: &Expr) -> PE {
        match &e.kind {
            ExprKind::Int(n) => {
                if self.lit_is_float(e.span) {
                    PE::Float(*n as f64)
                } else {
                    PE::Int(*n)
                }
            }
            ExprKind::Float(f) => PE::Float(*f),
            ExprKind::Str(s) => PE::Str(s.clone()),
            ExprKind::FStr(parts) => {
                let mut out = Vec::new();
                for p in parts {
                    match p {
                        FPart::Text(t) => out.push(FsPart::Lit(t.clone())),
                        FPart::Expr(x) => {
                            let v = self.expr(x);
                            out.push(FsPart::Expr(v));
                        }
                    }
                }
                PE::FStr(out)
            }
            ExprKind::Bool(b) => PE::Bool(*b),
            ExprKind::Unit => PE::NoneV,
            ExprKind::Measured(lit, _) => self.expr(lit),
            ExprKind::Var(n) => self.var_value(n),
            ExprKind::Ctor(path, n) => self.ctor_value(path, n),
            ExprKind::Qual(path, n, _) => {
                if path.len() == 1 && path[0] == "Decode" && n == "auto" {
                    if let Some(c) = self.ck.auto_codecs.get(&key(e.span)).cloned() {
                        let f = self.builtin_value("Decode.auto");
                        let d = self.codec_text(&c);
                        return PE::Call(Box::new(f), vec![PE::Raw(d)], Vec::new());
                    }
                }
                self.qual_value(path, n)
            }
            ExprKind::Field(b, f, _) => {
                let base = self.expr(b);
                attr(base, &mangle(f))
            }
            ExprKind::App(..) => self.app(e),
            ExprKind::Binary(op, l, r) => self.binary(*op, l, r, e),
            ExprKind::Chain(first, rest) => {
                let a = self.expr(first);
                let mut v = Vec::new();
                for (op, x) in rest {
                    let c = match op {
                        CmpOp::Eq => Cop::Eq,
                        CmpOp::Ne => Cop::Ne,
                        CmpOp::Lt => Cop::Lt,
                        CmpOp::Le => Cop::Le,
                        CmpOp::Gt => Cop::Gt,
                        CmpOp::Ge => Cop::Ge,
                    };
                    v.push((c, self.expr(x)));
                }
                PE::Cmp(Box::new(a), v)
            }
            ExprKind::Neg(x) => {
                let v = self.expr(x);
                match v {
                    PE::Int(n) if n >= 0 => PE::Int(-n),
                    PE::Float(f) if f >= 0.0 => PE::Float(-f),
                    other => PE::Neg(Box::new(other)),
                }
            }
            ExprKind::Not(x) => {
                let v = self.expr(x);
                PE::Not(Box::new(v))
            }
            ExprKind::Try(x) => self.try_expr(x),
            ExprKind::If(c, a, b) => self.if_expr(c, a, b),
            ExprKind::Match(s, arms) => {
                let (stmts, t) = self.match_value(s, arms, e.span);
                self.pre.extend(stmts);
                name(&t)
            }
            ExprKind::Lambda(ps, body) => self.lambda(ps, body),
            ExprKind::Block(stmts) => {
                self.scopes.push(HashMap::new());
                let n = stmts.len();
                for s in &stmts[..n - 1] {
                    let ss = self.block_stmt(s);
                    self.pre.extend(ss);
                }
                let last = match &stmts[n - 1] {
                    Stmt::Expr(x) => self.expr(x),
                    other => {
                        let ss = self.block_stmt(other);
                        self.pre.extend(ss);
                        PE::NoneV
                    }
                };
                self.scopes.pop();
                last
            }
            ExprKind::Tuple(xs) => {
                let v = xs.iter().map(|x| self.expr(x)).collect();
                PE::Tuple(v)
            }
            ExprKind::List(xs) => {
                let v = xs.iter().map(|x| self.expr(x)).collect();
                PE::List(v)
            }
            ExprKind::Record(path, n, _, fields) => self.record(path, n, fields),
            ExprKind::Update(b, fields) => self.update(b, fields),
            ExprKind::Section(op) => self.section(*op, &[]),
            ExprKind::Hole(_) => PE::NoneV,
            ExprKind::Assign(n, _, v) => {
                // the assignment runs first; its value is unit
                let val = self.expr(v);
                let py = self.assign_target(n);
                self.pre.push(PS::Assign(name(&py), val));
                PE::NoneV
            }
            ExprKind::Ce(path, n, items) => self.ce(path, n, items, e),
        }
    }

    pub fn var_value(&mut self, n: &str) -> PE {
        if let Some(m) = self.subst.last() {
            if let Some(v) = m.get(n) {
                return v.clone();
            }
        }
        if let Some(b) = self.lookup(n).cloned() {
            if let BKind::Extern(_) = b.kind {
                return self.extern_value(n);
            }
            return name(&b.py);
        }
        if builtin(n).is_some() {
            return self.builtin_value(n);
        }
        name(&mangle(n))
    }

    pub fn builtin_value(&mut self, full: &str) -> PE {
        let b = builtin(full).unwrap();
        let v = b.value;
        if v.starts_with("_pf_") {
            self.helper(v);
            return name(v);
        }
        if let Some(m) = v.strip_prefix("math.") {
            self.needs.imports.insert("math".into());
            return attr(name("math"), m);
        }
        match v {
            "set()" => call_n("set", vec![]),
            "dict()" => call_n("dict", vec![]),
            "iter([])" => call_n("iter", vec![PE::List(vec![])]),
            other => name(other),
        }
    }

    /// A codec descriptor as Python, naming classes as this module sees them.
    pub fn codec_text(&mut self, c: &crate::codec::Codec) -> String {
        let mut uses_result = false;
        let text = crate::codec::render(c, &|m: &Option<String>, n: &str, nullary: bool| {
            let prefix = match m.as_ref().and_then(|m| self.module_alias(m)) {
                Some(py) => format!("{}.", py),
                None => String::new(),
            };
            if nullary {
                format!("{}_{}", prefix, ctor_py(n))
            } else {
                format!("{}{}", prefix, ctor_py(n))
            }
        });
        if text.contains("(Ok, [") {
            uses_result = true;
        }
        if uses_result {
            self.note_ctor_type("Result");
        }
        text
    }

    pub fn ctor_value(&mut self, path: &[String], n: &str) -> PE {
        let c = self.ck.lookup_ctor(path, n);
        let Some(c) = c else {
            // an active-pattern case inside its recognizer
            if let Some(ac) = self.ck.active_ctors.get(n) {
                if ac.args.is_empty() {
                    return call_n(&format!("_{}", n), vec![]);
                }
                return name(&format!("_{}", n));
            }
            return name(n);
        };
        self.note_ctor_type(&c.type_name);
        // opaque types erase
        if let Some(TypeInfo { def: TypeDef::Opaque(_), .. }) = self.ck.types.get(&c.type_name) {
            return PE::Lambda(vec!["x".into()], Box::new(name("x")));
        }
        let prefix = self.module_prefix(path, &c);
        if c.args.is_empty() {
            name(&format!("{}_{}", prefix, ctor_py(n)))
        } else {
            name(&format!("{}{}", prefix, ctor_py(n)))
        }
    }

    fn module_prefix(&self, path: &[String], c: &CtorInfo) -> String {
        if path.is_empty() {
            if let Some(m) = &c.module {
                if let Some(py) = self.module_alias(m) {
                    return format!("{}.", py);
                }
            }
            return String::new();
        }
        let m = path.join(".");
        match self.module_alias(&m) {
            Some(py) => format!("{}.", py),
            None => String::new(),
        }
    }

    pub fn note_ctor_type(&mut self, tname: &str) {
        match tname {
            "Option" => self.needs.option = true,
            "Result" => self.needs.result = true,
            _ => {}
        }
    }

    pub fn qual_value(&mut self, path: &[String], n: &str) -> PE {
        let m = path.join(".");
        let full = format!("{}.{}", m, n);
        if builtin(&full).is_some() {
            return self.builtin_value(&full);
        }
        if let Some(py) = self.module_alias(&m).cloned() {
            return attr(name(&py), &mangle(n));
        }
        // in-file module member
        let key = format!("{}.{}", m, n);
        if let Some(b) = self.lookup(&key) {
            return name(&b.py.clone());
        }
        name(&format!("{}_{}", m, n))
    }

    // ---- application ------------------------------------------------------

    pub fn spine<'e>(e: &'e Expr) -> (&'e Expr, Vec<&'e Expr>) {
        let mut args = Vec::new();
        let mut f = e;
        loop {
            match &f.kind {
                ExprKind::App(g, a) => {
                    args.push(&**a);
                    f = g;
                }
                _ => break,
            }
        }
        args.reverse();
        (f, args)
    }

    fn app(&mut self, e: &Expr) -> PE {
        let (f, args) = Self::spine(e);
        self.apply(f, &args, e)
    }

    /// The arity a callee is known to take, if any.
    fn callee_arity(&self, f: &Expr) -> Option<usize> {
        match &f.kind {
            ExprKind::Var(n) => match self.lookup(n) {
                Some(Bind { kind: BKind::Fn(k), .. }) => Some(*k),
                Some(Bind { kind: BKind::Extern(k), .. }) => Some(*k),
                Some(_) => None,
                None => builtin(n).map(|b| sig_arity(b.sig)),
            },
            ExprKind::Qual(p, n, _) => {
                let full = format!("{}.{}", p.join("."), n);
                if let Some(b) = builtin(&full) {
                    return Some(sig_arity(b.sig));
                }
                match self.lookup(&full) {
                    Some(Bind { kind: BKind::Fn(k), .. }) => Some(*k),
                    _ => self.module_member_arity(&p.join("."), n),
                }
            }
            ExprKind::Ctor(p, n) => self.ck.lookup_ctor(p, n).map(|c| c.args.len()).or_else(|| self.ck.active_ctors.get(n).map(|c| c.args.len())),
            ExprKind::Lambda(ps, _) => Some(ps.len()),
            ExprKind::Section(_) => Some(2),
            _ => None,
        }
    }

    fn module_member_arity(&self, _m: &str, _n: &str) -> Option<usize> {
        None
    }

    pub fn apply(&mut self, f: &Expr, args: &[&Expr], whole: &Expr) -> PE {
        // builtins with special lowering
        let bname = match &f.kind {
            ExprKind::Var(n) if self.lookup(n).is_none() && builtin(n).is_some() => Some(n.clone()),
            ExprKind::Qual(p, n, _) => {
                let full = format!("{}.{}", p.join("."), n);
                if builtin(&full).is_some() {
                    Some(full)
                } else {
                    None
                }
            }
            _ => None,
        };
        if let Some(bn) = bname {
            if let Some(v) = self.apply_builtin(&bn, f, args, whole) {
                return v;
            }
        }
        if let ExprKind::Var(n) = &f.kind {
            if let Some(Bind { kind: BKind::Extern(_), .. }) = self.lookup(n) {
                let n = n.clone();
                return self.apply_extern(&n, args, whole);
            }
        }
        if let ExprKind::Ctor(p, n) = &f.kind {
            if let Some(c) = self.ck.lookup_ctor(p, n) {
                if let Some(TypeInfo { def: TypeDef::Opaque(_), .. }) = self.ck.types.get(&c.type_name) {
                    // the wrap erases
                    let v = self.expr(args[0]);
                    if args.len() == 1 {
                        return v;
                    }
                    let rest: Vec<PE> = args[1..].iter().map(|a| self.expr(a)).collect();
                    return self.call_curried(v, rest);
                }
            }
        }
        if let ExprKind::Section(op) = &f.kind {
            if args.len() == 2 {
                let a = self.expr(args[0]);
                let b = self.expr(args[1]);
                let lam = self.section(*op, &[]);
                return PE::Call(Box::new(lam), vec![a, b], vec![]);
            }
            return self.section_partial(*op, args);
        }
        if let ExprKind::Lambda(ps, body) = &f.kind {
            if args.len() < ps.len() {
                return self.partial_lambda(ps, body, args);
            }
        }
        let arity = self.callee_arity_of(f);
        let fv = self.expr(f);
        let argv: Vec<PE> = args.iter().map(|a| self.expr(a)).collect();
        self.call_with_arity(fv, argv, arity)
    }

    pub fn call_with_arity(&mut self, fv: PE, mut argv: Vec<PE>, arity: Option<usize>) -> PE {
        match arity {
            None => PE::Call(Box::new(fv), argv, vec![]),
            Some(k) => {
                if argv.len() == k {
                    PE::Call(Box::new(fv), argv, vec![])
                } else if argv.len() < k {
                    self.needs.functools = true;
                    let mut v = vec![fv];
                    v.extend(argv);
                    PE::Call(Box::new(attr(name("functools"), "partial")), v, vec![])
                } else {
                    let rest = argv.split_off(k);
                    let first = PE::Call(Box::new(fv), argv, vec![]);
                    self.call_curried(first, rest)
                }
            }
        }
    }

    pub fn call_curried(&mut self, f: PE, rest: Vec<PE>) -> PE {
        let mut cur = f;
        for a in rest {
            cur = PE::Call(Box::new(cur), vec![a], vec![]);
        }
        cur
    }

    fn partial_lambda(&mut self, ps: &[Pat], body: &Expr, args: &[&Expr]) -> PE {
        // substitute simple arguments into the body
        let simple = args.iter().all(|a| matches!(a.kind, ExprKind::Var(_) | ExprKind::Int(_) | ExprKind::Float(_) | ExprKind::Str(_) | ExprKind::Bool(_)));
        let all_vars = ps.iter().all(|p| matches!(p.kind, PatKind::Var(_)));
        if simple && all_vars {
            let mut subst: HashMap<String, PE> = HashMap::new();
            for (p, a) in ps.iter().zip(args.iter()) {
                if let PatKind::Var(n) = &p.kind {
                    let v = self.expr(a);
                    subst.insert(n.clone(), v);
                }
            }
            let rest = &ps[args.len()..];
            let lam = self.lambda_with_subst(rest, body, &subst);
            return lam;
        }
        let lam = self.lambda(ps, body);
        let argv: Vec<PE> = args.iter().map(|a| self.expr(a)).collect();
        self.needs.functools = true;
        let mut v = vec![lam];
        v.extend(argv);
        PE::Call(Box::new(attr(name("functools"), "partial")), v, vec![])
    }

    fn lambda_with_subst(&mut self, ps: &[Pat], body: &Expr, subst: &HashMap<String, PE>) -> PE {
        self.scopes.push(HashMap::new());
        let mut names = Vec::new();
        for p in ps {
            if let PatKind::Var(n) = &p.kind {
                names.push(self.bind(n, BKind::Value, false));
            }
        }
        self.subst.push(subst.clone());
        let b = self.expr(body);
        self.subst.pop();
        self.scopes.pop();
        PE::Lambda(names, Box::new(b))
    }
}

/// Number of arrows in a builtin signature (its arity).
pub fn sig_arity(sig: &str) -> usize {
    // count top-level `->` arrows
    let b = sig.as_bytes();
    let mut depth = 0i32;
    let mut n = 0;
    let mut i = 0;
    while i < b.len() {
        match b[i] {
            b'(' => depth += 1,
            b')' => depth -= 1,
            b'-' if i + 1 < b.len() && b[i + 1] == b'>' && depth == 0 => {
                n += 1;
                i += 1;
            }
            _ => {}
        }
        i += 1;
    }
    n
}

#[derive(Clone, Debug, PartialEq)]
pub enum Dest {
    Return,
    /// `return await <value>` (an async tail position)
    ReturnAwait,
    Assign(String),
    /// statement position: the value is dropped
    Discard,
    /// a temporary of its own, taken once the scrutinee is lowered (its
    /// name is left in `fresh_tmp`)
    Fresh,
}

#[allow(dead_code)]
fn _unused(_: &HashSet<String>) {}
