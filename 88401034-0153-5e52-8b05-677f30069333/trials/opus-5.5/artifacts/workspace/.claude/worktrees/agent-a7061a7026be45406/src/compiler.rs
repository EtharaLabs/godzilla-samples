// Code generator: AST -> bytecode, using resolver scope information.

use crate::ast::*;
use crate::bytecode::*;
use crate::resolver::{is_function_like, RScope, Resolver, ScopeKind};
use crate::value::{JsStr, Value};
use crate::value::PropKey as VKey;
use std::collections::HashMap;
use std::rc::Rc;

#[derive(Debug)]
pub struct CompileError {
    pub msg: String,
    pub line: u32,
}

type CResult<T> = Result<T, CompileError>;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
struct Label(u32);

#[derive(Clone, Copy, Debug)]
enum Storage {
    Local(u32),
    Env(u32),
}

struct CScope {
    rid: usize,
    has_env: bool,
    names: Vec<(Rc<str>, Storage, BindKind)>,
    is_with: bool,
    /// function scope with sloppy direct eval
    dyn_eval: bool,
}

enum Ctl<'a> {
    Loop { labels: Vec<Rc<str>>, brk: Label, cont: Label },
    Breakable { labels: Vec<Rc<str>>, brk: Label },
    Scope,
    Try { finalizer: Option<&'a Block>, scope_depth: usize },
    Iter { is_async: bool },
    Stack(u32),
}

struct FuncState<'a> {
    ops: Vec<Op>,
    consts: Vec<Value>,
    keys: Vec<VKey>,
    key_index: HashMap<String, u32>,
    funcs: Vec<Rc<FunctionCode>>,
    scope_infos: Vec<Rc<ScopeInfo>>,
    templates: Vec<Rc<TemplateData>>,
    regexps: Vec<(JsStr, JsStr)>,
    strings: Vec<JsStr>,
    nlocals: u32,
    scopes: Vec<CScope>,
    ctl: Vec<Ctl<'a>>,
    label_pos: Vec<Option<u32>>,
    fixups: Vec<(usize, Label)>,
    ret_slot: Option<u32>,
    completion_slot: Option<u32>,
    kind: FuncKind,
    is_arrow: bool,
    is_async: bool,
    is_generator: bool,
    strict: bool,
    func_rid: usize,
    pending_labels: Vec<Rc<str>>,
    imports: Vec<Rc<str>>,
    opt_end: Option<Label>,
    pending_static: Vec<u32>,
    scope_marks: Vec<usize>,
}

pub struct Compiler<'a> {
    res: &'a Resolver,
    source: Rc<str>,
    fs: Vec<FuncState<'a>>,
    is_module: bool,
    /// eval code: unresolved names are dynamic
    eval_mode: bool,
    repl: bool,
    pub import_names: Vec<Rc<str>>,
}

fn cerr<T>(msg: impl Into<String>, line: u32) -> CResult<T> {
    Err(CompileError { msg: msg.into(), line })
}

fn set_target(op: &mut Op, t: u32) {
    match op {
        Op::Jump(x)
        | Op::JumpIfFalse(x)
        | Op::JumpIfTrue(x)
        | Op::JumpIfFalseKeep(x)
        | Op::JumpIfTrueKeep(x)
        | Op::JumpIfNullishKeep(x)
        | Op::JumpIfNotNullishKeep(x)
        | Op::JumpIfNotUndef(x)
        | Op::JumpIfNullish(x)
        | Op::TryStart(x)
        | Op::IterNext(x)
        | Op::ForInNext(x)
        | Op::GenResume(x)
        | Op::AsyncIterCheck(x)
        | Op::YieldStar(x, _) => *x = t,
        _ => panic!("not a jump op: {:?}", op),
    }
}

fn units(s: &str) -> Vec<u16> {
    s.encode_utf16().collect()
}

fn propkey_static_name(k: &PropKey) -> Option<String> {
    match k {
        PropKey::Ident(n) => Some(n.to_string()),
        PropKey::Str(s) => Some(String::from_utf16_lossy(s)),
        PropKey::Num(n) => Some(crate::numconv::number_to_string(*n)),
        _ => None,
    }
}

impl<'a> Compiler<'a> {
    pub fn new(res: &'a Resolver, source: Rc<str>, is_module: bool) -> Compiler<'a> {
        Compiler { res, source, fs: Vec::new(), is_module, eval_mode: false, repl: false, import_names: Vec::new() }
    }

    fn f(&mut self) -> &mut FuncState<'a> {
        self.fs.last_mut().unwrap()
    }

    fn rscope(&self, id: usize) -> &'a RScope {
        &self.res.scopes[id]
    }

    // ---------- emission helpers ----------

    fn emit(&mut self, op: Op) -> usize {
        let f = self.f();
        f.ops.push(op);
        f.ops.len() - 1
    }

    fn new_label(&mut self) -> Label {
        let f = self.f();
        f.label_pos.push(None);
        Label((f.label_pos.len() - 1) as u32)
    }

    fn place(&mut self, l: Label) {
        let f = self.f();
        f.label_pos[l.0 as usize] = Some(f.ops.len() as u32);
    }

    fn emit_jump(&mut self, op: Op, l: Label) -> usize {
        let i = self.emit(op);
        self.f().fixups.push((i, l));
        i
    }

    fn key_idx(&mut self, name: &str) -> u32 {
        let f = self.f();
        if let Some(i) = f.key_index.get(name) {
            return *i;
        }
        let i = f.keys.len() as u32;
        f.keys.push(VKey::Str(JsStr::from_str(name)));
        f.key_index.insert(name.to_string(), i);
        i
    }

    fn key_idx_units(&mut self, u: &[u16]) -> u32 {
        let s = String::from_utf16_lossy(u);
        if s.encode_utf16().eq(u.iter().copied()) {
            return self.key_idx(&s);
        }
        let f = self.f();
        let i = f.keys.len() as u32;
        f.keys.push(VKey::Str(JsStr::from_slice(u)));
        i
    }

    fn const_idx(&mut self, v: Value) -> u32 {
        let f = self.f();
        // dedupe strings & numbers
        for (i, c) in f.consts.iter().enumerate() {
            match (c, &v) {
                (Value::Num(a), Value::Num(b)) if a.to_bits() == b.to_bits() => return i as u32,
                (Value::Str(a), Value::Str(b)) if a == b => return i as u32,
                _ => {}
            }
            if i > 256 {
                break;
            }
        }
        f.consts.push(v);
        (f.consts.len() - 1) as u32
    }

    fn string_idx(&mut self, s: &str) -> u32 {
        let f = self.f();
        for (i, x) in f.strings.iter().enumerate() {
            if x.eq_str(s) {
                return i as u32;
            }
        }
        f.strings.push(JsStr::from_str(s));
        (f.strings.len() - 1) as u32
    }

    fn new_local(&mut self) -> u32 {
        let f = self.f();
        f.nlocals += 1;
        f.nlocals - 1
    }

    fn push_num(&mut self, n: f64) {
        if n.fract() == 0.0 && n.abs() < 2147483647.0 && !(n == 0.0 && n.is_sign_negative()) {
            self.emit(Op::Int(n as i32));
        } else {
            let i = self.const_idx(Value::Num(n));
            self.emit(Op::Const(i));
        }
    }

    fn push_str(&mut self, s: &[u16]) {
        let i = self.const_idx(Value::Str(JsStr::from_slice(s)));
        self.emit(Op::Const(i));
    }

    // ---------- scopes ----------

    /// Enter a resolver scope; emits PushScope if any binding is captured.
    fn enter_scope(&mut self, rid: usize, force_env: bool) -> bool {
        let rs = self.rscope(rid);
        let module_scope = rs.kind == ScopeKind::Module;
        let mut names = Vec::new();
        let mut env_names: Vec<JsStr> = Vec::new();
        let mut env_kinds = Vec::new();
        for d in &rs.decls {
            if d.kind == BindKind::Import {
                continue;
            }
            if d.kind == BindKind::Internal && !d.captured && !force_env && &*d.name != "arguments" && !d.name.starts_with('#') {
                // frame-level binding (this/new.target/%func/%home): accessed with frame ops
                continue;
            }
            if d.kind == BindKind::Internal && &*d.name == "arguments" && !rs.uses_arguments && !d.captured && !force_env {
                continue;
            }
            if rs.kind == ScopeKind::Eval && !rs.strict && matches!(d.kind, BindKind::Var | BindKind::Function) {
                // sloppy eval: vars live in the caller's variable environment (dynamic)
                continue;
            }
            let captured = d.captured || force_env || module_scope;
            if captured {
                names.push((d.name.clone(), Storage::Env(env_names.len() as u32), d.kind));
                env_names.push(JsStr::from_str(&d.name));
                env_kinds.push(d.kind);
            } else {
                let slot = self.new_local();
                names.push((d.name.clone(), Storage::Local(slot), d.kind));
            }
        }
        let has_env = !env_names.is_empty() || rs.kind == ScopeKind::With || (force_env && rs.kind == ScopeKind::Function);
        if has_env && rs.kind != ScopeKind::With {
            let info = Rc::new(ScopeInfo {
                names: env_names,
                kinds: env_kinds,
                is_function: is_function_like(rs.kind) && rs.kind != ScopeKind::Eval,
            });
            let f = self.f();
            f.scope_infos.push(info);
            let idx = (f.scope_infos.len() - 1) as u32;
            self.emit(Op::PushScope(idx));
        }
        let dyn_eval = is_function_like(rs.kind) && rs.has_eval;
        self.f().scopes.push(CScope { rid, has_env, names, is_with: rs.kind == ScopeKind::With, dyn_eval });
        // TDZ for lexical locals
        let mut clears = Vec::new();
        for (_, st, k) in &self.f().scopes.last().unwrap().names {
            if let Storage::Local(s) = st {
                if matches!(k, BindKind::Let | BindKind::Const | BindKind::Class) {
                    clears.push(*s);
                }
            }
        }
        for s in clears {
            self.emit(Op::ClearLocal(s));
        }
        has_env
    }

    fn exit_scope(&mut self) {
        let s = self.f().scopes.pop().unwrap();
        if s.has_env {
            self.emit(Op::PopScope);
        }
    }

    // ---------- name resolution ----------

    fn resolve(&self, name: &str) -> Resolved {
        let mut depth: u16 = 0;
        let mut dynamic = false;
        let nf = self.fs.len();
        for fi in (0..nf).rev() {
            let fstate = &self.fs[fi];
            for sc in fstate.scopes.iter().rev() {
                if sc.is_with {
                    dynamic = true;
                }
                if let Some((_, st, k)) = sc.names.iter().find(|(n, _, _)| &**n == name) {
                    if dynamic {
                        return Resolved::Dynamic;
                    }
                    return match st {
                        Storage::Local(s) => {
                            if fi == nf - 1 {
                                Resolved::Local(*s, *k)
                            } else {
                                Resolved::Dynamic
                            }
                        }
                        Storage::Env(s) => Resolved::Env(depth, *s, *k),
                    };
                }
                // imports (module scope)
                if self.rscope(sc.rid).kind == ScopeKind::Module {
                    let rs = self.rscope(sc.rid);
                    if rs.decls.iter().any(|d| &*d.name == name && d.kind == BindKind::Import) {
                        if let Some(i) = self.import_names.iter().position(|n| &**n == name) {
                            return Resolved::Import(i as u32);
                        }
                    }
                }
                if sc.has_env {
                    depth += 1;
                }
                if sc.dyn_eval {
                    dynamic = true;
                }
                // frame-level internal names stop at the nearest non-arrow function
                if (name == "this" || name == "new.target" || name.starts_with('%')) && !dynamic {
                    let rs = self.rscope(sc.rid);
                    if is_function_like(rs.kind) && !(rs.kind == ScopeKind::Function && rs.is_arrow) {
                        return Resolved::Global;
                    }
                }
            }
        }
        if dynamic || self.eval_mode {
            Resolved::Dynamic
        } else {
            Resolved::Global
        }
    }

    fn tdz_kind(k: BindKind) -> bool {
        matches!(k, BindKind::Let | BindKind::Const | BindKind::Class)
    }

    fn load_name(&mut self, name: &str) {
        match self.resolve(name) {
            Resolved::Local(s, k) => {
                if Self::tdz_kind(k) {
                    let n = self.string_idx(name);
                    self.emit(Op::GetLocalChk(s, n));
                } else {
                    self.emit(Op::GetLocal(s));
                }
            }
            Resolved::Env(d, s, k) => {
                if Self::tdz_kind(k) || (k == BindKind::Internal && name == "this") {
                    let n = self.string_idx(name);
                    self.emit(Op::GetEnvChk(d, s, n));
                } else {
                    self.emit(Op::GetEnv(d, s));
                }
            }
            Resolved::Global => {
                let k = self.key_idx(name);
                self.emit(Op::GetGlobal(k));
            }
            Resolved::Dynamic => {
                let k = self.key_idx(name);
                self.emit(Op::GetName(k));
            }
            Resolved::Import(i) => {
                self.emit(Op::GetImport(i));
            }
        }
    }

    /// store top of stack into a variable (value remains on stack)
    fn store_name(&mut self, name: &str, line: u32) -> CResult<()> {
        let _ = line;
        match self.resolve(name) {
            Resolved::Local(s, k) => match k {
                BindKind::Const | BindKind::Class if k == BindKind::Const => {
                    let n = self.string_idx(name);
                    self.emit(Op::GetLocalChk(s, n));
                    self.emit(Op::Pop);
                    self.emit(Op::ThrowConst(n));
                }
                BindKind::Let | BindKind::Class => {
                    let n = self.string_idx(name);
                    self.emit(Op::GetLocalChk(s, n));
                    self.emit(Op::Pop);
                    self.emit(Op::SetLocal(s));
                }
                BindKind::FuncName => {
                    if self.f().strict {
                        let n = self.string_idx(name);
                        self.emit(Op::ThrowConst(n));
                    }
                }
                _ => {
                    self.emit(Op::SetLocal(s));
                }
            },
            Resolved::Env(d, s, k) => match k {
                BindKind::Const => {
                    let n = self.string_idx(name);
                    self.emit(Op::GetEnvChk(d, s, n));
                    self.emit(Op::Pop);
                    self.emit(Op::ThrowConst(n));
                }
                BindKind::Let | BindKind::Class => {
                    let n = self.string_idx(name);
                    self.emit(Op::SetEnvChk(d, s, n));
                }
                BindKind::FuncName => {
                    if self.f().strict {
                        let n = self.string_idx(name);
                        self.emit(Op::ThrowConst(n));
                    }
                }
                _ => {
                    self.emit(Op::SetEnv(d, s));
                }
            },
            Resolved::Global => {
                let k = self.key_idx(name);
                self.emit(Op::SetGlobal(k));
            }
            Resolved::Dynamic => {
                let k = self.key_idx(name);
                self.emit(Op::SetName(k));
            }
            Resolved::Import(_) => {
                let n = self.string_idx(name);
                self.emit(Op::ThrowConst(n));
            }
        }
        Ok(())
    }

    /// initialize a binding (declaration); pops the value
    fn init_name(&mut self, name: &str) {
        match self.resolve(name) {
            Resolved::Local(s, _) => {
                self.emit(Op::InitLocal(s));
            }
            Resolved::Env(d, s, _) => {
                self.emit(Op::InitEnv(d, s));
            }
            Resolved::Global => {
                // top-level script lexical or var
                let k = self.key_idx(name);
                self.emit(Op::InitGlobalLex(k));
            }
            Resolved::Dynamic => {
                let k = self.key_idx(name);
                self.emit(Op::SetName(k));
                self.emit(Op::Pop);
            }
            Resolved::Import(_) => {
                self.emit(Op::Pop);
            }
        }
    }

    fn is_global_lexical(&self, name: &str) -> bool {
        self.res.global_names_lex.iter().any(|(n, _)| &**n == name)
    }

    // ---------- program ----------

    pub fn compile_script(mut self, p: &'a Program, is_eval: bool, repl: bool, strict_eval_vars: bool) -> CResult<Rc<FunctionCode>> {
        let _ = strict_eval_vars;
        self.eval_mode = is_eval;
        self.repl = repl;
        let rid = p.scope.get() as usize;
        self.fs.push(FuncState::new(FuncKind::Normal, false, false, false, p.strict, rid));
        let completion = if is_eval || repl {
            let s = self.new_local();
            self.f().completion_slot = Some(s);
            Some(s)
        } else {
            None
        };
        let rs = self.rscope(rid);
        // global declarations for scripts
        if rs.kind == ScopeKind::Script {
            for (n, _) in &self.res.global_names_lex {
                let is_const = self.is_const_lexical(&p.body, n);
                let k = self.key_idx(n);
                self.emit(Op::DeclareGlobalLex(k, is_const));
            }
            for (n, _) in &self.res.global_names_var {
                let k = self.key_idx(n);
                self.emit(Op::DeclareGlobalVar(k));
            }
        }
        self.enter_scope(rid, false);
        self.init_internal_bindings(rid);
        if rs.kind == ScopeKind::Eval && !p.strict {
            // sloppy eval: var declarations go to the caller's variable environment
            for d in &rs.decls {
                if matches!(d.kind, BindKind::Var | BindKind::Function) {
                    let k = self.key_idx(&d.name);
                    self.emit(Op::DeclareGlobalVar(k));
                }
            }
        }
        self.hoist_functions(&p.body, true)?;
        for s in &p.body {
            self.compile_stmt(s)?;
        }
        if let Some(c) = completion {
            self.emit(Op::GetLocal(c));
        } else {
            self.emit(Op::Undef);
        }
        self.emit(Op::Return);
        self.exit_scope_noemit();
        let fs = self.fs.pop().unwrap();
        let mut code = self.finish(fs, JsStr::empty(), 0, 0, 0, 0, true);
        code.is_script = true;
        code.is_eval = is_eval;
        Ok(Rc::new(code))
    }

    fn exit_scope_noemit(&mut self) {
        self.f().scopes.pop();
    }

    fn is_const_lexical(&self, body: &[Stmt], name: &str) -> bool {
        for s in body {
            if let Stmt::Var(d) = s {
                if d.kind == VarKind::Const {
                    for decl in &d.decls {
                        let mut ns = Vec::new();
                        crate::resolver::pattern_names(&decl.target, &mut ns);
                        if ns.iter().any(|(n, _)| &**n == name) {
                            return true;
                        }
                    }
                }
            }
        }
        false
    }

    pub fn compile_module(mut self, p: &'a Program) -> CResult<(Rc<FunctionCode>, Vec<Rc<str>>)> {
        let rid = p.scope.get() as usize;
        // import bindings in order of declaration
        for s in &p.body {
            if let Stmt::Import(imp) = s {
                if let Some(d) = &imp.default {
                    self.import_names.push(d.name.clone());
                }
                if let Some(ns) = &imp.namespace {
                    self.import_names.push(ns.name.clone());
                }
                for (_, l) in &imp.named {
                    self.import_names.push(l.name.clone());
                }
            }
        }
        self.fs.push(FuncState::new(FuncKind::Normal, false, p.has_top_level_await, false, true, rid));
        self.enter_scope(rid, true);
        self.init_internal_bindings(rid);
        self.hoist_functions(&p.body, true)?;
        self.emit(Op::ModuleBodyStart);
        for s in &p.body {
            self.compile_stmt(s)?;
        }
        self.emit(Op::Undef);
        self.emit(Op::Return);
        self.exit_scope_noemit();
        let fs = self.fs.pop().unwrap();
        let mut code = self.finish(fs, JsStr::empty(), 0, 0, 0, 0, true);
        code.is_module = true;
        let names = self.import_names.clone();
        Ok((Rc::new(code), names))
    }

    /// names of module-scope bindings in env order (for export linking)
    pub fn module_env_names(res: &Resolver, p: &Program) -> Vec<Rc<str>> {
        let rs = &res.scopes[p.scope.get() as usize];
        rs.decls.iter().filter(|d| d.kind != BindKind::Import).map(|d| d.name.clone()).collect()
    }

    fn init_internal_bindings(&mut self, rid: usize) {
        let rs = self.rscope(rid);
        for d in &rs.decls {
            if d.kind != BindKind::Internal {
                continue;
            }
            let (st, name) = {
                let sc = self.f().scopes.last().unwrap();
                match sc.names.iter().find(|(n, _, _)| *n == d.name) {
                    Some((n, st, _)) => (*st, n.clone()),
                    None => continue,
                }
            };
            let op = match &*name {
                "this" => Op::This,
                "new.target" => Op::NewTarget,
                "%home" => Op::Home,
                "%func" => Op::Callee,
                "arguments" => Op::CreateArguments(false),
                _ => continue,
            };
            // only materialize if captured or used
            if &*name == "arguments" && !rs.uses_arguments && !d.captured {
                continue;
            }
            self.emit(op);
            match st {
                Storage::Local(s) => {
                    self.emit(Op::InitLocal(s));
                }
                Storage::Env(s) => {
                    self.emit(Op::InitEnv(0, s));
                }
            }
        }
    }

    fn finish(&mut self, mut fs: FuncState<'a>, name: JsStr, length: u32, src_start: usize, src_end: usize, line: u32, simple: bool) -> FunctionCode {
        for (i, l) in fs.fixups.iter() {
            let t = fs.label_pos[l.0 as usize].expect("unplaced label");
            set_target(&mut fs.ops[*i], t);
        }
        FunctionCode {
            name,
            ops: fs.ops,
            consts: fs.consts,
            keys: fs.keys,
            funcs: fs.funcs,
            scopes: fs.scope_infos,
            templates: fs.templates,
            regexps: fs.regexps,
            strings: fs.strings,
            nlocals: fs.nlocals,
            length,
            kind: fs.kind,
            is_async: fs.is_async,
            is_generator: fs.is_generator,
            strict: fs.strict,
            source: self.source.clone(),
            src_start,
            src_end,
            is_arrow: fs.is_arrow,
            has_simple_params: simple,
            line,
            no_prototype: false,
            class_source: false,
            is_default_ctor: false,
            is_script: false,
            is_module: false,
            is_eval: false,
        }
    }

    // ---------- hoisting ----------

    fn hoist_functions(&mut self, stmts: &'a [Stmt], _top: bool) -> CResult<()> {
        for s in stmts {
            let mut s = s;
            while let Stmt::Labeled(_, inner) = s {
                s = inner;
            }
            let f = match s {
                Stmt::Function(f) => f,
                Stmt::Export(e) => match &**e {
                    ExportDecl::Decl(Stmt::Function(f)) => f,
                    ExportDecl::DefaultFunc(f) => {
                        let idx = self.compile_function(f, Some(JsStr::from_str("default")))?;
                        self.emit(Op::Closure(idx));
                        let name: String = match &f.name {
                            Some(n) => n.name.to_string(),
                            None => "*default*".to_string(),
                        };
                        self.init_name(&name);
                        continue;
                    }
                    _ => continue,
                },
                _ => continue,
            };
            let name = match &f.name {
                Some(n) => n.name.clone(),
                None => continue,
            };
            let idx = self.compile_function(f, None)?;
            self.emit(Op::Closure(idx));
            match self.resolve(&name) {
                Resolved::Global => {
                    let k = self.key_idx(&name);
                    self.emit(Op::SetGlobal(k));
                    self.emit(Op::Pop);
                }
                _ => self.init_name(&name),
            }
        }
        Ok(())
    }

    // ---------- control flow helpers ----------

    /// Emit cleanup code for leaving ctl entries above index `to` (exclusive).
    fn unwind_to(&mut self, to: usize) -> CResult<()> {
        let mut i = self.f().ctl.len();
        while i > to {
            i -= 1;
            match &self.f().ctl[i] {
                Ctl::Scope => {
                    self.emit(Op::PopScope);
                }
                Ctl::Try { finalizer, scope_depth } => {
                    let fin = *finalizer;
                    let depth = *scope_depth;
                    self.emit(Op::TryEnd);
                    if let Some(b) = fin {
                        // compile finally with ctl truncated and the compile-time scope chain as it
                        // was at the try statement (runtime envs were popped by PopScope above)
                        let saved: Vec<Ctl<'a>> = self.f().ctl.drain(i..).collect();
                        let saved_scopes: Vec<CScope> = self.f().scopes.drain(depth..).collect();
                        self.compile_block(b)?;
                        self.f().scopes.extend(saved_scopes);
                        self.f().ctl.extend(saved);
                    }
                }
                Ctl::Iter { is_async } => {
                    if *is_async {
                        self.emit(Op::IterCloseAsync);
                        self.emit(Op::Await);
                        self.emit(Op::Pop);
                    } else {
                        self.emit(Op::IterClose);
                    }
                }
                Ctl::Stack(n) => {
                    for _ in 0..*n {
                        self.emit(Op::Pop);
                    }
                }
                Ctl::Loop { .. } | Ctl::Breakable { .. } => {}
            }
        }
        Ok(())
    }

    fn find_break_target(&self, label: Option<&Rc<str>>, is_continue: bool) -> Option<(usize, Label)> {
        let ctl = &self.fs.last().unwrap().ctl;
        for i in (0..ctl.len()).rev() {
            match &ctl[i] {
                Ctl::Loop { labels, brk, cont } => match label {
                    None => return Some((i, if is_continue { *cont } else { *brk })),
                    Some(l) => {
                        if labels.contains(l) {
                            return Some((i, if is_continue { *cont } else { *brk }));
                        }
                    }
                },
                Ctl::Breakable { labels, brk } => {
                    if is_continue {
                        continue;
                    }
                    match label {
                        None => {
                            // unlabeled break targets switch (labels empty and marked) - Breakable with
                            // empty label list represents a switch
                            if labels.is_empty() {
                                return Some((i, *brk));
                            }
                        }
                        Some(l) => {
                            if labels.contains(l) {
                                return Some((i, *brk));
                            }
                        }
                    }
                }
                _ => {}
            }
        }
        None
    }

    // ---------- statements ----------

    fn compile_block(&mut self, b: &'a Block) -> CResult<()> {
        let rid = b.scope.get() as usize;
        let has_env = self.enter_scope(rid, false);
        if has_env {
            self.f().ctl.push(Ctl::Scope);
        }
        self.mark_scope_depth();
        self.hoist_functions(&b.body, false)?;
        for s in &b.body {
            self.compile_stmt(s)?;
        }
        if has_env {
            self.f().ctl.pop();
        }
        self.exit_scope();
        Ok(())
    }

    fn mark_scope_depth(&mut self) {}

    fn take_labels(&mut self) -> Vec<Rc<str>> {
        std::mem::take(&mut self.f().pending_labels)
    }

    fn compile_stmt(&mut self, s: &'a Stmt) -> CResult<()> {
        match s {
            Stmt::Expr(e) => {
                self.compile_expr(e)?;
                if let Some(c) = self.f().completion_slot {
                    self.emit(Op::SetCompletion(c));
                } else {
                    self.emit(Op::Pop);
                }
            }
            Stmt::Var(d) => self.compile_var_decl(d)?,
            Stmt::Function(f) => {
                // annex B: copy block-level function binding to var binding
                if let Some(n) = &f.name {
                    if !f.strict && !self.f().strict {
                        self.annexb_copy(&n.name, f)?;
                    }
                }
            }
            Stmt::Class(c) => {
                self.compile_class(c, None)?;
                let name = c.name.as_ref().unwrap().name.clone();
                self.init_name(&name);
            }
            Stmt::Return(e) => {
                match e {
                    Some(e) => self.compile_expr(e)?,
                    None => {
                        self.emit(Op::Undef);
                    }
                }
                self.emit_return()?;
            }
            Stmt::If(t, a, b) => {
                let l_else = self.new_label();
                self.compile_cond_jump(t, false, l_else)?;
                self.compile_sub_stmt(a)?;
                if let Some(b) = b {
                    let l_end = self.new_label();
                    self.emit_jump(Op::Jump(0), l_end);
                    self.place(l_else);
                    self.compile_sub_stmt(b)?;
                    self.place(l_end);
                } else {
                    self.place(l_else);
                }
            }
            Stmt::Block(b) => {
                let labels = self.take_labels();
                if !labels.is_empty() {
                    let brk = self.new_label();
                    self.f().ctl.push(Ctl::Breakable { labels, brk });
                    self.compile_block(b)?;
                    self.f().ctl.pop();
                    self.place(brk);
                } else {
                    self.compile_block(b)?;
                }
            }
            Stmt::For(f) => self.compile_for(f)?,
            Stmt::ForIn(f) => self.compile_for_in(f)?,
            Stmt::ForOf(f) => self.compile_for_of(f)?,
            Stmt::While(t, body) => {
                let labels = self.take_labels();
                let l_top = self.new_label();
                let l_end = self.new_label();
                self.place(l_top);
                self.compile_cond_jump(t, false, l_end)?;
                self.f().ctl.push(Ctl::Loop { labels, brk: l_end, cont: l_top });
                self.compile_sub_stmt(body)?;
                self.f().ctl.pop();
                self.emit_jump(Op::Jump(0), l_top);
                self.place(l_end);
            }
            Stmt::DoWhile(body, t) => {
                let labels = self.take_labels();
                let l_top = self.new_label();
                let l_cont = self.new_label();
                let l_end = self.new_label();
                self.place(l_top);
                self.f().ctl.push(Ctl::Loop { labels, brk: l_end, cont: l_cont });
                self.compile_sub_stmt(body)?;
                self.f().ctl.pop();
                self.place(l_cont);
                self.compile_cond_jump(t, true, l_top)?;
                self.place(l_end);
            }
            Stmt::Break(label) => {
                let (idx, target) = match self.find_break_target(label.as_ref(), false) {
                    Some(x) => x,
                    None => return cerr("illegal 'break' statement", 0),
                };
                self.unwind_to(idx + 1)?;
                self.emit_jump(Op::Jump(0), target);
            }
            Stmt::Continue(label) => {
                let (idx, target) = match self.find_break_target(label.as_ref(), true) {
                    Some(x) => x,
                    None => return cerr("illegal 'continue' statement", 0),
                };
                self.unwind_to(idx + 1)?;
                self.emit_jump(Op::Jump(0), target);
            }
            Stmt::Throw(e) => {
                self.compile_expr(e)?;
                self.emit(Op::Throw);
            }
            Stmt::Try(t) => self.compile_try(t)?,
            Stmt::Switch(sw) => self.compile_switch(sw)?,
            Stmt::Labeled(l, body) => {
                self.f().pending_labels.push(l.clone());
                match &**body {
                    Stmt::For(_) | Stmt::ForIn(_) | Stmt::ForOf(_) | Stmt::While(..) | Stmt::DoWhile(..) | Stmt::Labeled(..) | Stmt::Block(_) => {
                        self.compile_stmt(body)?;
                    }
                    _ => {
                        let labels = self.take_labels();
                        let brk = self.new_label();
                        self.f().ctl.push(Ctl::Breakable { labels, brk });
                        self.compile_stmt(body)?;
                        self.f().ctl.pop();
                        self.place(brk);
                    }
                }
            }
            Stmt::Empty | Stmt::Debugger => {}
            Stmt::With(obj, body, sid) => {
                self.compile_expr(obj)?;
                self.emit(Op::PushWith);
                let rid = sid.get() as usize;
                self.f().scopes.push(CScope { rid, has_env: true, names: Vec::new(), is_with: true, dyn_eval: false });
                self.f().ctl.push(Ctl::Scope);
                self.compile_sub_stmt(body)?;
                self.f().ctl.pop();
                self.exit_scope();
            }
            Stmt::Import(_) => {}
            Stmt::Export(e) => self.compile_export(e)?,
        }
        Ok(())
    }

    fn annexb_copy(&mut self, name: &Rc<str>, _f: &'a Function) -> CResult<()> {
        // if the name resolves (innermost) to a block-level function binding and the function
        // scope has a var binding with the same name, copy it
        let fs = self.fs.last().unwrap();
        let n = fs.scopes.len();
        if n == 0 {
            return Ok(());
        }
        // find innermost scope declaring name
        let mut inner_idx = None;
        for i in (0..n).rev() {
            if fs.scopes[i].names.iter().any(|(x, _, _)| x == name) {
                inner_idx = Some(i);
                break;
            }
        }
        let inner_idx = match inner_idx {
            Some(i) => i,
            None => {
                // top-level script function or sub-statement function: assign to var binding
                return self.annexb_assign_sub(name, _f);
            }
        };
        let rid = fs.scopes[inner_idx].rid;
        if is_function_like(self.rscope(rid).kind) {
            // declared at function level already (not a block function)
            if !self.is_hoisted_in(inner_idx, name) {
                return self.annexb_assign_sub(name, _f);
            }
            return Ok(());
        }
        // find function-level var binding
        let mut func_idx = None;
        for i in (0..inner_idx).rev() {
            let k = self.rscope(fs.scopes[i].rid).kind;
            if is_function_like(k) {
                func_idx = Some(i);
                break;
            }
        }
        // value from block binding
        self.load_name(name);
        match func_idx {
            Some(fi) => {
                let st = fs_find(&self.fs.last().unwrap().scopes[fi], name);
                match st {
                    Some((Storage::Local(s), BindKind::Var | BindKind::Function)) => {
                        self.emit(Op::SetLocal(s));
                    }
                    Some((Storage::Env(s), BindKind::Var | BindKind::Function)) => {
                        // compute depth from current position to scope fi
                        let mut depth = 0u16;
                        let fsr = self.fs.last().unwrap();
                        for j in ((fi + 1)..fsr.scopes.len()).rev() {
                            if fsr.scopes[j].has_env {
                                depth += 1;
                            }
                        }
                        self.emit(Op::SetEnv(depth, s));
                    }
                    _ => {
                        let rk = self.rscope(self.fs.last().unwrap().scopes[fi].rid).kind;
                        if rk == ScopeKind::Script || (rk == ScopeKind::Eval) {
                            let k = self.key_idx(name);
                            if rk == ScopeKind::Script {
                                self.emit(Op::SetGlobal(k));
                            } else {
                                self.emit(Op::SetName(k));
                            }
                        }
                    }
                }
            }
            None => {}
        }
        self.emit(Op::Pop);
        Ok(())
    }

    fn is_hoisted_in(&self, _idx: usize, _name: &str) -> bool {
        true
    }

    /// function declaration not hoisted by an enclosing block (e.g. `if (x) function f(){}`)
    fn annexb_assign_sub(&mut self, name: &Rc<str>, f: &'a Function) -> CResult<()> {
        let _ = (name, f);
        Ok(())
    }

    fn compile_sub_stmt(&mut self, s: &'a Stmt) -> CResult<()> {
        if let Stmt::Function(f) = s {
            // function declaration as substatement: evaluate and assign
            let idx = self.compile_function(f, None)?;
            self.emit(Op::Closure(idx));
            let name = f.name.as_ref().unwrap().name.clone();
            match self.resolve(&name) {
                Resolved::Global => {
                    let k = self.key_idx(&name);
                    self.emit(Op::SetGlobal(k));
                }
                _ => {
                    self.store_name(&name, 0)?;
                }
            }
            self.emit(Op::Pop);
            return Ok(());
        }
        self.compile_stmt(s)
    }

    fn emit_return(&mut self) -> CResult<()> {
        if self.f().kind == FuncKind::DerivedConstructor {
            // undefined -> this (with TDZ check)
            let l = self.new_label();
            self.emit(Op::Dup);
            self.emit_jump(Op::JumpIfNotUndef(0), l);
            self.emit(Op::Pop);
            self.load_this();
            self.place(l);
        }
        let needs_cleanup = self.f().ctl.iter().any(|c| matches!(c, Ctl::Try { .. } | Ctl::Iter { .. }));
        if needs_cleanup {
            let slot = self.ret_slot();
            self.emit(Op::SetLocal(slot));
            self.emit(Op::Pop);
            self.unwind_to(0)?;
            self.emit(Op::GetLocal(slot));
        }
        self.emit(Op::Return);
        Ok(())
    }

    fn ret_slot(&mut self) -> u32 {
        if let Some(s) = self.f().ret_slot {
            return s;
        }
        let s = self.new_local();
        self.f().ret_slot = Some(s);
        s
    }

    fn compile_var_decl(&mut self, d: &'a VarDecl) -> CResult<()> {
        for decl in &d.decls {
            match &decl.init {
                Some(init) => {
                    let hint = match &decl.target {
                        Pattern::Ident(id) if init.is_anonymous_fn() => Some(JsStr::from_str(&id.name)),
                        _ => None,
                    };
                    self.compile_expr_named(init, hint)?;
                    if matches!(d.kind, VarKind::Using | VarKind::AwaitUsing) {
                        self.emit(Op::AddDisposable(d.kind == VarKind::AwaitUsing));
                    }
                    self.compile_binding(&decl.target, d.kind)?;
                }
                None => {
                    if d.kind == VarKind::Var {
                        continue;
                    }
                    self.emit(Op::Undef);
                    self.compile_binding(&decl.target, d.kind)?;
                }
            }
        }
        Ok(())
    }

    /// Bind value on stack to pattern (declaration). Consumes the value.
    fn compile_binding(&mut self, p: &'a Pattern, kind: VarKind) -> CResult<()> {
        match p {
            Pattern::Ident(id) => {
                if kind == VarKind::Var {
                    match self.resolve(&id.name) {
                        Resolved::Global => {
                            let k = self.key_idx(&id.name);
                            self.emit(Op::SetGlobal(k));
                            self.emit(Op::Pop);
                        }
                        _ => {
                            self.store_name(&id.name, id.line)?;
                            self.emit(Op::Pop);
                        }
                    }
                } else {
                    self.init_name(&id.name);
                }
                Ok(())
            }
            _ => self.compile_pattern(p, Some(kind)),
        }
    }

    /// Destructure value on stack into pattern. kind None = assignment pattern. Consumes value.
    fn compile_pattern(&mut self, p: &'a Pattern, kind: Option<VarKind>) -> CResult<()> {
        match p {
            Pattern::Ident(id) => match kind {
                Some(k) => self.compile_binding(p, k),
                None => {
                    self.store_name(&id.name, id.line)?;
                    self.emit(Op::Pop);
                    Ok(())
                }
            },
            Pattern::Expr(e) => {
                // assignment target expression; value on stack
                self.compile_store_to_expr(e)?;
                self.emit(Op::Pop);
                Ok(())
            }
            Pattern::Object { props, rest } => {
                self.emit(Op::RequireObjCoercible);
                let mut computed_keys: Vec<u32> = Vec::new();
                for prop in props {
                    self.emit(Op::Dup);
                    match &prop.key {
                        PropKey::Computed(e) => {
                            self.compile_expr(e)?;
                            self.emit(Op::ToPropKey);
                            if rest.is_some() {
                                let t = self.new_local();
                                self.emit(Op::SetLocal(t));
                                computed_keys.push(t);
                            }
                            self.emit(Op::GetElem);
                        }
                        PropKey::Private(_) => return cerr("unexpected private name in pattern", 0),
                        k => {
                            let name = propkey_static_name(k).unwrap();
                            let ki = match k {
                                PropKey::Str(u) => self.key_idx_units(u),
                                _ => self.key_idx(&name),
                            };
                            self.emit(Op::GetProp(ki));
                        }
                    }
                    if let Some(d) = &prop.default {
                        let l = self.new_label();
                        self.emit(Op::Dup);
                        self.emit_jump(Op::JumpIfNotUndef(0), l);
                        self.emit(Op::Pop);
                        let hint = match &prop.target {
                            Pattern::Ident(id) if d.is_anonymous_fn() => Some(JsStr::from_str(&id.name)),
                            _ => None,
                        };
                        self.compile_expr_named(d, hint)?;
                        self.place(l);
                    }
                    self.compile_pattern(&prop.target, kind)?;
                }
                if let Some(r) = rest {
                    // excluded keys
                    let mut n = 0u32;
                    let mut ci = 0;
                    for prop in props {
                        match &prop.key {
                            PropKey::Computed(_) => {
                                self.emit(Op::GetLocal(computed_keys[ci]));
                                ci += 1;
                            }
                            k => {
                                let name = propkey_static_name(k).unwrap();
                                self.push_str(&units(&name));
                            }
                        }
                        n += 1;
                    }
                    self.emit(Op::CopyDataPropsExcept(n));
                    self.compile_pattern(r, kind)?;
                } else {
                    self.emit(Op::Pop);
                }
                Ok(())
            }
            Pattern::Array { elems, rest } => {
                self.emit(Op::DestructIter);
                // [iter next done]
                let try_label = self.new_label();
                let end_label = self.new_label();
                self.emit_jump(Op::TryStart(0), try_label);
                for el in elems {
                    match el {
                        None => {
                            self.emit(Op::IterValue);
                            self.emit(Op::Pop);
                        }
                        Some(el) => {
                            // assignment targets: evaluate reference first (simplified: after value)
                            self.emit(Op::IterValue);
                            if let Some(d) = &el.default {
                                let l = self.new_label();
                                self.emit(Op::Dup);
                                self.emit_jump(Op::JumpIfNotUndef(0), l);
                                self.emit(Op::Pop);
                                let hint = match &el.target {
                                    Pattern::Ident(id) if d.is_anonymous_fn() => Some(JsStr::from_str(&id.name)),
                                    _ => None,
                                };
                                self.compile_expr_named(d, hint)?;
                                self.place(l);
                            }
                            self.compile_pattern(&el.target, kind)?;
                        }
                    }
                }
                if let Some(r) = rest {
                    self.emit(Op::IterRest);
                    self.compile_pattern(r, kind)?;
                }
                self.emit(Op::TryEnd);
                self.emit(Op::IterDone);
                self.emit_jump(Op::Jump(0), end_label);
                // exception during destructuring: close iterator (if not done) and rethrow
                self.place(try_label);
                // stack: [iter next done exc]
                self.emit(Op::Rot4);
                // [exc iter next done]
                self.emit(Op::IterCloseThrow);
                self.place(end_label);
                Ok(())
            }
        }
    }

    /// store value on stack into member expression target (value remains)
    fn compile_store_to_expr(&mut self, e: &'a Expr) -> CResult<()> {
        match e.unparen() {
            Expr::Ident(id) => {
                self.store_name(&id.name, id.line)?;
            }
            Expr::Member { obj, prop, .. } => {
                self.compile_expr(obj)?;
                match prop {
                    MemberProp::Name(n) => {
                        self.emit(Op::Swap);
                        let k = self.key_idx(n);
                        self.emit(Op::SetProp(k));
                    }
                    MemberProp::Computed(k) => {
                        self.compile_expr(k)?;
                        self.emit(Op::Rot3);
                        self.emit(Op::SetElem);
                    }
                    MemberProp::Private(n) => {
                        self.load_name(&format!("#{}", n));
                        self.emit(Op::Rot3);
                        self.emit(Op::SetPrivate);
                    }
                }
            }
            Expr::SuperMember(prop) => {
                self.emit(Op::ThisChk);
                match prop {
                    MemberProp::Name(n) => {
                        self.emit(Op::Swap);
                        let k = self.key_idx(n);
                        self.emit(Op::SetSuper(k));
                    }
                    MemberProp::Computed(k) => {
                        self.compile_expr(k)?;
                        self.emit(Op::ToPropKey);
                        self.emit(Op::Rot3);
                        self.emit(Op::SetSuperElem);
                    }
                    MemberProp::Private(_) => return cerr("unexpected private", 0),
                }
            }
            _ => return cerr("invalid assignment target", 0),
        }
        Ok(())
    }

    fn compile_for(&mut self, f: &'a ForStmt) -> CResult<()> {
        let labels = self.take_labels();
        let rid = f.scope.get() as usize;
        let has_env = self.enter_scope(rid, false);
        if has_env {
            self.f().ctl.push(Ctl::Scope);
        }
        let per_iter = has_env
            && matches!(&f.init, Some(ForInit::Var(d)) if d.kind == VarKind::Let || d.kind == VarKind::Const);
        if let Some(init) = &f.init {
            match init {
                ForInit::Var(d) => self.compile_var_decl(d)?,
                ForInit::Expr(e) => {
                    self.compile_expr(e)?;
                    self.emit(Op::Pop);
                }
            }
        }
        if per_iter {
            self.emit(Op::CopyScope);
        }
        let l_top = self.new_label();
        let l_cont = self.new_label();
        let l_end = self.new_label();
        self.place(l_top);
        if let Some(t) = &f.test {
            self.compile_cond_jump(t, false, l_end)?;
        }
        self.f().ctl.push(Ctl::Loop { labels, brk: l_end, cont: l_cont });
        self.compile_sub_stmt(&f.body)?;
        self.f().ctl.pop();
        self.place(l_cont);
        if per_iter {
            self.emit(Op::CopyScope);
        }
        if let Some(u) = &f.update {
            self.compile_expr(u)?;
            self.emit(Op::Pop);
        }
        self.emit_jump(Op::Jump(0), l_top);
        self.place(l_end);
        if has_env {
            self.f().ctl.pop();
        }
        self.exit_scope();
        Ok(())
    }

    /// bind the iteration value (on stack) for for-in/of heads
    fn compile_for_head_binding(&mut self, head: &'a ForHead) -> CResult<()> {
        match head {
            ForHead::Decl(kind, p) => self.compile_binding(p, *kind),
            ForHead::Target(p) => self.compile_pattern(p, None),
        }
    }

    fn compile_for_in(&mut self, f: &'a ForInOf) -> CResult<()> {
        let labels = self.take_labels();
        let rid = f.scope.get() as usize;
        // legacy initializer: for (var x = init in obj)
        if let Some(vi) = &f.var_init {
            if let ForHead::Decl(_, Pattern::Ident(id)) = &f.head {
                self.compile_expr(vi)?;
                match self.resolve(&id.name) {
                    Resolved::Global => {
                        let k = self.key_idx(&id.name);
                        self.emit(Op::SetGlobal(k));
                    }
                    _ => {
                        self.store_name(&id.name, id.line)?;
                    }
                }
                self.emit(Op::Pop);
            }
        }
        // evaluate the object in a TDZ scope for the loop bindings
        let has_env = self.enter_scope(rid, false);
        self.compile_expr(&f.right)?;
        if has_env {
            self.emit(Op::PopScope);
        }
        self.f().scopes.pop();
        self.emit(Op::ForInStart);
        self.f().ctl.push(Ctl::Stack(1));
        let l_top = self.new_label();
        let l_end = self.new_label();
        let l_exit = self.new_label();
        self.place(l_top);
        self.emit_jump(Op::ForInNext(0), l_end);
        // per-iteration scope
        let has_env2 = self.enter_scope(rid, false);
        if has_env2 {
            self.f().ctl.push(Ctl::Scope);
        }
        self.compile_for_head_binding(&f.head)?;
        let l_cont = self.new_label();
        self.f().ctl.push(Ctl::Loop { labels, brk: l_exit, cont: l_cont });
        self.compile_sub_stmt(&f.body)?;
        self.f().ctl.pop();
        self.place(l_cont);
        if has_env2 {
            self.f().ctl.pop();
        }
        self.exit_scope();
        self.emit_jump(Op::Jump(0), l_top);
        // fix: continue must pop scope before jumping to top; handled since cont label is before exit_scope
        self.place(l_exit);
        self.place(l_end);
        self.f().ctl.pop();
        self.emit(Op::Pop);
        Ok(())
    }

    fn compile_for_of(&mut self, f: &'a ForInOf) -> CResult<()> {
        let labels = self.take_labels();
        let rid = f.scope.get() as usize;
        let has_env = self.enter_scope(rid, false);
        self.compile_expr(&f.right)?;
        if has_env {
            self.emit(Op::PopScope);
        }
        self.f().scopes.pop();
        if f.is_await {
            self.emit(Op::GetAsyncIterator);
        } else {
            self.emit(Op::GetIterator);
        }
        // [iter next]
        self.f().ctl.push(Ctl::Iter { is_async: f.is_await });
        let l_top = self.new_label();
        let l_done = self.new_label();
        let l_brk = self.new_label();
        let l_exc = self.new_label();
        let l_end = self.new_label();
        self.place(l_top);
        if f.is_await {
            self.emit(Op::IterCallNext);
            self.emit(Op::Await);
            self.emit_jump(Op::AsyncIterCheck(0), l_done);
        } else {
            self.emit_jump(Op::IterNext(0), l_done);
        }
        // [iter next value]
        self.f().ctl.push(Ctl::Loop { labels, brk: l_brk, cont: l_top });
        self.emit_jump(Op::TryStart(0), l_exc);
        { let d = self.f().scopes.len(); self.f().ctl.push(Ctl::Try { finalizer: None, scope_depth: d }); }
        let has_env2 = self.enter_scope(rid, false);
        if has_env2 {
            self.f().ctl.push(Ctl::Scope);
        }
        self.compile_for_head_binding(&f.head)?;
        self.compile_sub_stmt(&f.body)?;
        if has_env2 {
            self.f().ctl.pop();
        }
        self.exit_scope();
        self.f().ctl.pop(); // Try
        self.emit(Op::TryEnd);
        self.f().ctl.pop(); // Loop
        self.emit_jump(Op::Jump(0), l_top);
        // exception in body: [iter next exc]
        self.place(l_exc);
        if f.is_await {
            // async close: call return, await, ignore result; rethrow
            self.emit(Op::Rot3);
            // [exc iter next]
            self.emit(Op::IterCloseAsync);
            self.emit(Op::Await);
            self.emit(Op::Pop);
            self.emit(Op::Throw);
        } else {
            self.emit(Op::Rot3);
            self.emit(Op::IterCloseThrow);
        }
        // break
        self.place(l_brk);
        self.f().ctl.pop(); // Iter
        if f.is_await {
            self.emit(Op::IterCloseAsync);
            self.emit(Op::Await);
            self.emit(Op::Pop);
        } else {
            self.emit(Op::IterClose);
        }
        self.emit_jump(Op::Jump(0), l_end);
        self.place(l_done);
        self.emit(Op::Pop);
        self.emit(Op::Pop);
        self.place(l_end);
        Ok(())
    }

    fn compile_try(&mut self, t: &'a TryStmt) -> CResult<()> {
        let l_catch = self.new_label();
        let l_end = self.new_label();
        let has_finally = t.finalizer.is_some();
        let l_finally_exc = self.new_label();
        if has_finally {
            // outer handler for finally (covers try + catch)
            self.emit_jump(Op::TryStart(0), l_finally_exc);
            let d = self.f().scopes.len();
            self.f().ctl.push(Ctl::Try { finalizer: t.finalizer.as_ref(), scope_depth: d });
        }
        if t.handler.is_some() {
            self.emit_jump(Op::TryStart(0), l_catch);
            let d = self.f().scopes.len();
            self.f().ctl.push(Ctl::Try { finalizer: None, scope_depth: d });
        }
        self.compile_block(&t.block)?;
        if t.handler.is_some() {
            self.f().ctl.pop();
            self.emit(Op::TryEnd);
        }
        let l_after_catch = self.new_label();
        self.emit_jump(Op::Jump(0), l_after_catch);
        if let Some(h) = &t.handler {
            self.place(l_catch);
            // exception on stack
            let rid = t.catch_scope.get() as usize;
            let has_env = self.enter_scope(rid, false);
            if has_env {
                self.f().ctl.push(Ctl::Scope);
            }
            match &t.param {
                Some(p) => self.compile_binding(p, VarKind::Let)?,
                None => {
                    self.emit(Op::Pop);
                }
            }
            self.compile_block(h)?;
            if has_env {
                self.f().ctl.pop();
            }
            self.exit_scope();
        }
        self.place(l_after_catch);
        if has_finally {
            self.f().ctl.pop();
            self.emit(Op::TryEnd);
            // normal path finally
            self.compile_block(t.finalizer.as_ref().unwrap())?;
            self.emit_jump(Op::Jump(0), l_end);
            // exception path: [exc]
            self.place(l_finally_exc);
            let slot = self.new_local();
            self.emit(Op::SetLocal(slot));
            self.emit(Op::Pop);
            self.compile_block(t.finalizer.as_ref().unwrap())?;
            self.emit(Op::GetLocal(slot));
            self.emit(Op::Throw);
        }
        self.place(l_end);
        Ok(())
    }

    fn compile_switch(&mut self, sw: &'a SwitchStmt) -> CResult<()> {
        let labels = self.take_labels();
        self.compile_expr(&sw.disc)?;
        let tmp = self.new_local();
        self.emit(Op::SetLocal(tmp));
        self.emit(Op::Pop);
        let rid = sw.scope.get() as usize;
        let has_env = self.enter_scope(rid, false);
        if has_env {
            self.f().ctl.push(Ctl::Scope);
        }
        // hoist functions in all cases
        for c in &sw.cases {
            self.hoist_functions(&c.body, false)?;
        }
        let l_end = self.new_label();
        let case_labels: Vec<Label> = sw.cases.iter().map(|_| self.new_label()).collect();
        let mut default_idx = None;
        for (i, c) in sw.cases.iter().enumerate() {
            match &c.test {
                Some(t) => {
                    self.emit(Op::GetLocal(tmp));
                    self.compile_expr(t)?;
                    self.emit(Op::StrictEq);
                    self.emit_jump(Op::JumpIfTrue(0), case_labels[i]);
                }
                None => default_idx = Some(i),
            }
        }
        match default_idx {
            Some(i) => {
                self.emit_jump(Op::Jump(0), case_labels[i]);
            }
            None => {
                self.emit_jump(Op::Jump(0), l_end);
            }
        }
        let mut labels = labels;
        if labels.is_empty() {
            // unlabeled: marker (empty list) means switch
        } else {
            // labeled switch also handles unlabeled breaks: push two entries
        }
        let labeled = !labels.is_empty();
        if labeled {
            self.f().ctl.push(Ctl::Breakable { labels: std::mem::take(&mut labels), brk: l_end });
        }
        self.f().ctl.push(Ctl::Breakable { labels: Vec::new(), brk: l_end });
        for (i, c) in sw.cases.iter().enumerate() {
            self.place(case_labels[i]);
            for s in &c.body {
                self.compile_stmt(s)?;
            }
        }
        self.f().ctl.pop();
        if labeled {
            self.f().ctl.pop();
        }
        self.place(l_end);
        if has_env {
            self.f().ctl.pop();
        }
        self.exit_scope();
        Ok(())
    }

    fn compile_export(&mut self, e: &'a ExportDecl) -> CResult<()> {
        match e {
            ExportDecl::Decl(s) => self.compile_stmt(s),
            ExportDecl::DefaultExpr(e) => {
                let hint = if e.is_anonymous_fn() { Some(JsStr::from_str("default")) } else { None };
                self.compile_expr_named(e, hint)?;
                self.init_name("*default*");
                Ok(())
            }
            ExportDecl::DefaultFunc(_) => Ok(()),
            ExportDecl::DefaultClass(c) => {
                self.compile_class(c, Some(JsStr::from_str("default")))?;
                let name: String = match &c.name {
                    Some(n) => n.name.to_string(),
                    None => "*default*".to_string(),
                };
                self.init_name(&name);
                Ok(())
            }
            _ => Ok(()),
        }
    }

    // ---------- conditions ----------

    /// compile expression and jump to `target` if its truthiness equals `jump_if`
    fn compile_cond_jump(&mut self, e: &'a Expr, jump_if: bool, target: Label) -> CResult<()> {
        match e {
            Expr::Unary(UnaryOp::Not, inner) => return self.compile_cond_jump(inner, !jump_if, target),
            Expr::Logical(LogicalOp::And, a, b) => {
                if jump_if {
                    let skip = self.new_label();
                    self.compile_cond_jump(a, false, skip)?;
                    self.compile_cond_jump(b, true, target)?;
                    self.place(skip);
                } else {
                    self.compile_cond_jump(a, false, target)?;
                    self.compile_cond_jump(b, false, target)?;
                }
                return Ok(());
            }
            Expr::Logical(LogicalOp::Or, a, b) => {
                if jump_if {
                    self.compile_cond_jump(a, true, target)?;
                    self.compile_cond_jump(b, true, target)?;
                } else {
                    let skip = self.new_label();
                    self.compile_cond_jump(a, true, skip)?;
                    self.compile_cond_jump(b, false, target)?;
                    self.place(skip);
                }
                return Ok(());
            }
            Expr::Paren(inner) => return self.compile_cond_jump(inner, jump_if, target),
            _ => {}
        }
        self.compile_expr(e)?;
        if jump_if {
            self.emit_jump(Op::JumpIfTrue(0), target);
        } else {
            self.emit_jump(Op::JumpIfFalse(0), target);
        }
        Ok(())
    }

    // ---------- expressions ----------

    fn compile_expr_named(&mut self, e: &'a Expr, name: Option<JsStr>) -> CResult<()> {
        match (e, name) {
            (Expr::Function(f), Some(n)) if f.name.is_none() => {
                let idx = self.compile_function(f, Some(n))?;
                self.emit(Op::Closure(idx));
                Ok(())
            }
            (Expr::Arrow(f), Some(n)) => {
                let idx = self.compile_function(f, Some(n))?;
                self.emit(Op::Closure(idx));
                Ok(())
            }
            (Expr::Class(c), Some(n)) if c.name.is_none() => self.compile_class(c, Some(n)),
            (Expr::Paren(inner), Some(n)) if inner.is_anonymous_fn() => self.compile_expr_named(inner, Some(n)),
            (e, _) => self.compile_expr(e),
        }
    }

    pub fn compile_expr(&mut self, e: &'a Expr) -> CResult<()> {
        match e {
            Expr::Num(n) => self.push_num(*n),
            Expr::Str(s) => self.push_str(s),
            Expr::BigInt(s) => {
                let b = parse_bigint_literal(s);
                let i = self.const_idx(Value::BigInt(Rc::new(b)));
                self.emit(Op::Const(i));
            }
            Expr::Regex { pattern, flags } => {
                let f = self.f();
                f.regexps.push((JsStr::from_slice(pattern), JsStr::from_slice(flags)));
                let i = (f.regexps.len() - 1) as u32;
                self.emit(Op::RegExp(i));
            }
            Expr::Template { quasis, exprs } => {
                // concatenation with ToString
                let first = quasis[0].cooked.as_ref().unwrap();
                self.push_str(first);
                for (i, ex) in exprs.iter().enumerate() {
                    self.compile_expr(ex)?;
                    self.emit(Op::ToStr);
                    self.emit(Op::Add);
                    let q = quasis[i + 1].cooked.as_ref().unwrap();
                    if !q.is_empty() {
                        self.push_str(q);
                        self.emit(Op::Add);
                    }
                }
            }
            Expr::TaggedTemplate { tag, quasis, exprs, id } => {
                self.compile_callee(tag)?;
                let td = TemplateData {
                    cooked: quasis.iter().map(|q| q.cooked.as_ref().map(|c| JsStr::from_slice(c))).collect(),
                    raw: quasis.iter().map(|q| JsStr::from_slice(&q.raw)).collect(),
                    id: *id,
                };
                let f = self.f();
                f.templates.push(Rc::new(td));
                let ti = (f.templates.len() - 1) as u32;
                self.emit(Op::Template(ti));
                for ex in exprs {
                    self.compile_expr(ex)?;
                }
                let desc = match tag.unparen() {
                    Expr::Ident(id) => self.string_idx(&id.name),
                    _ => self.string_idx("tag"),
                };
                self.emit(Op::Call(exprs.len() as u32 + 1, desc));
            }
            Expr::Bool(true) => {
                self.emit(Op::True);
            }
            Expr::Bool(false) => {
                self.emit(Op::False);
            }
            Expr::Null => {
                self.emit(Op::Null);
            }
            Expr::Ident(id) => {
                if &*id.name == "undefined" {
                    if let Resolved::Global = self.resolve("undefined") {
                        self.emit(Op::Undef);
                        return Ok(());
                    }
                }
                if &*id.name == "arguments" {
                    self.load_arguments();
                    return Ok(());
                }
                self.load_name(&id.name);
            }
            Expr::This => self.load_this(),
            Expr::NewTarget => {
                match self.resolve("new.target") {
                    Resolved::Env(d, s, _) => {
                        self.emit(Op::GetEnv(d, s));
                    }
                    _ => {
                        self.emit(Op::NewTarget);
                    }
                }
            }
            Expr::ImportMeta => {
                self.emit(Op::ImportMeta);
            }
            Expr::SuperMember(prop) => {
                self.load_this();
                match prop {
                    MemberProp::Name(n) => {
                        let k = self.key_idx(n);
                        self.emit(Op::GetSuper(k));
                    }
                    MemberProp::Computed(k) => {
                        self.compile_expr(k)?;
                        self.emit(Op::ToPropKey);
                        self.emit(Op::GetSuperElem);
                    }
                    MemberProp::Private(_) => return cerr("unexpected private", 0),
                }
            }
            Expr::SuperCall(args) => {
                self.load_internal("%func", Op::Callee);
                self.load_internal("new.target", Op::NewTarget);
                let has_spread = args.iter().any(|a| matches!(a, ArrayElem::Spread(_)));
                if has_spread {
                    self.compile_args_array(args)?;
                    self.emit(Op::SuperCallArray);
                } else {
                    for a in args {
                        if let ArrayElem::Expr(e) = a {
                            self.compile_expr(e)?;
                        }
                    }
                    self.emit(Op::SuperCall(args.len() as u32));
                }
                // bind this
                self.bind_this_after_super()?;
            }
            Expr::Array(elems) => {
                let simple = elems.iter().all(|e| matches!(e, Some(ArrayElem::Expr(_))));
                if simple && elems.len() < 1024 {
                    for el in elems {
                        if let Some(ArrayElem::Expr(e)) = el {
                            self.compile_expr(e)?;
                        }
                    }
                    self.emit(Op::NewArray(elems.len() as u32));
                } else {
                    self.emit(Op::NewArray(0));
                    for el in elems {
                        match el {
                            None => {
                                self.emit(Op::ArrayHole);
                            }
                            Some(ArrayElem::Expr(e)) => {
                                self.compile_expr(e)?;
                                self.emit(Op::ArrayPush);
                            }
                            Some(ArrayElem::Spread(e)) => {
                                self.compile_expr(e)?;
                                self.emit(Op::ArraySpread);
                            }
                        }
                    }
                }
            }
            Expr::Object(props) => self.compile_object(props)?,
            Expr::Function(f) => {
                let idx = self.compile_function(f, None)?;
                self.emit(Op::Closure(idx));
            }
            Expr::Arrow(f) => {
                let idx = self.compile_function(f, None)?;
                self.emit(Op::Closure(idx));
            }
            Expr::Class(c) => self.compile_class(c, None)?,
            Expr::Unary(op, arg) => self.compile_unary(*op, arg)?,
            Expr::Update { inc, prefix, target } => self.compile_update(*inc, *prefix, target)?,
            Expr::Binary(op, a, b) => {
                self.compile_expr(a)?;
                self.compile_expr(b)?;
                self.emit(binop(*op));
            }
            Expr::Logical(op, a, b) => {
                let l = self.new_label();
                self.compile_expr(a)?;
                match op {
                    LogicalOp::And => self.emit_jump(Op::JumpIfFalseKeep(0), l),
                    LogicalOp::Or => self.emit_jump(Op::JumpIfTrueKeep(0), l),
                    LogicalOp::Nullish => self.emit_jump(Op::JumpIfNotNullishKeep(0), l),
                };
                self.emit(Op::Pop);
                self.compile_expr(b)?;
                self.place(l);
            }
            Expr::Assign { op, target, value } => self.compile_assign(*op, target, value)?,
            Expr::Cond(t, a, b) => {
                let l_else = self.new_label();
                let l_end = self.new_label();
                self.compile_cond_jump(t, false, l_else)?;
                self.compile_expr(a)?;
                self.emit_jump(Op::Jump(0), l_end);
                self.place(l_else);
                self.compile_expr(b)?;
                self.place(l_end);
            }
            Expr::Call { callee, args, optional } => {
                self.compile_call(callee, args, *optional, None)?;
            }
            Expr::New { callee, args } => {
                self.compile_expr(callee)?;
                let has_spread = args.iter().any(|a| matches!(a, ArrayElem::Spread(_)));
                if has_spread {
                    self.compile_args_array(args)?;
                    self.emit(Op::NewArray_);
                } else {
                    for a in args {
                        if let ArrayElem::Expr(e) = a {
                            self.compile_expr(e)?;
                        }
                    }
                    self.emit(Op::New(args.len() as u32));
                }
            }
            Expr::Member { obj, prop, optional } => {
                self.compile_expr(obj)?;
                if *optional {
                    self.emit_opt_check(1)?;
                }
                self.compile_member_get(prop)?;
            }
            Expr::OptChain(inner) => {
                let l_end = self.new_label();
                let saved = self.f().opt_end.replace(l_end);
                let r = self.compile_expr(inner);
                self.f().opt_end = saved;
                r?;
                self.place(l_end);
            }
            Expr::Seq(v) => {
                for (i, x) in v.iter().enumerate() {
                    self.compile_expr(x)?;
                    if i + 1 < v.len() {
                        self.emit(Op::Pop);
                    }
                }
            }
            Expr::Yield { arg, delegate } => {
                if *delegate {
                    self.compile_expr(arg.as_ref().unwrap())?;
                    let is_async = self.f().is_async;
                    if is_async {
                        self.emit(Op::GetAsyncIterator);
                    } else {
                        self.emit(Op::GetIterator);
                    }
                    self.emit(Op::Undef);
                    let ret = self.new_label();
                    let after = self.new_label();
                    self.emit_jump(Op::YieldStar(0, is_async), ret);
                    self.emit_jump(Op::Jump(0), after);
                    self.place(ret);
                    self.emit_return()?;
                    self.place(after);
                } else {
                    match arg {
                        Some(a) => self.compile_expr(a)?,
                        None => {
                            self.emit(Op::Undef);
                        }
                    }
                    if self.f().is_async {
                        // async generator: await the operand before yielding
                        self.emit(Op::Await);
                    }
                    self.emit(Op::Yield);
                    let ret = self.new_label();
                    let after = self.new_label();
                    self.emit_jump(Op::GenResume(0), ret);
                    self.emit_jump(Op::Jump(0), after);
                    self.place(ret);
                    if self.f().is_async {
                        self.emit(Op::Await);
                    }
                    self.emit_return()?;
                    self.place(after);
                }
            }
            Expr::Await(a) => {
                self.compile_expr(a)?;
                self.emit(Op::Await);
            }
            Expr::PrivateIn(n, obj) => {
                self.load_name(&format!("#{}", n));
                self.compile_expr(obj)?;
                self.emit(Op::PrivateIn);
            }
            Expr::ImportCall(spec, opts) => {
                self.compile_expr(spec)?;
                match opts {
                    Some(o) => self.compile_expr(o)?,
                    None => {
                        self.emit(Op::Undef);
                    }
                }
                self.emit(Op::DynamicImport);
            }
            Expr::Paren(inner) => self.compile_expr(inner)?,
        }
        Ok(())
    }

    fn opt_end_slot(&mut self) -> &mut Option<Label> {
        &mut self.f().opt_end
    }

    /// optional-chain short circuit: if top of stack is nullish, pop `pops` values and push undefined,
    /// then jump to the chain end.
    fn emit_opt_check(&mut self, pops: u32) -> CResult<()> {
        let end = match self.f().opt_end {
            Some(l) => l,
            None => return cerr("optional chain outside chain", 0),
        };
        let cont = self.new_label();
        self.emit_jump(Op::JumpIfNotNullishKeep(0), cont);
        for _ in 0..pops {
            self.emit(Op::Pop);
        }
        self.emit(Op::Undef);
        self.emit_jump(Op::Jump(0), end);
        self.place(cont);
        Ok(())
    }

    fn compile_member_get(&mut self, prop: &'a MemberProp) -> CResult<()> {
        match prop {
            MemberProp::Name(n) => {
                let k = self.key_idx(n);
                self.emit(Op::GetProp(k));
            }
            MemberProp::Computed(k) => {
                self.compile_expr(k)?;
                self.emit(Op::GetElem);
            }
            MemberProp::Private(n) => {
                self.load_name(&format!("#{}", n));
                self.emit(Op::GetPrivate);
            }
        }
        Ok(())
    }

    fn load_this(&mut self) {
        match self.resolve("this") {
            Resolved::Env(d, s, _) => {
                let n = self.string_idx("this");
                self.emit(Op::GetEnvChk(d, s, n));
            }
            Resolved::Local(s, _) => {
                let n = self.string_idx("this");
                self.emit(Op::GetLocalChk(s, n));
            }
            _ => {
                self.emit(Op::ThisChk);
            }
        }
    }

    fn bind_this_after_super(&mut self) -> CResult<()> {
        // stack: [F result]
        self.emit(Op::Dup);
        match self.resolve("this") {
            Resolved::Env(d, s, _) => {
                self.emit(Op::BindThisEnv(d, s));
            }
            _ => {
                self.emit(Op::BindThis);
            }
        }
        // [F result]
        self.emit(Op::Swap);
        self.emit(Op::InitFields);
        Ok(())
    }

    fn load_internal(&mut self, name: &str, fallback: Op) {
        match self.resolve(name) {
            Resolved::Env(d, s, _) => {
                self.emit(Op::GetEnv(d, s));
            }
            Resolved::Local(s, _) => {
                self.emit(Op::GetLocal(s));
            }
            _ => {
                self.emit(fallback);
            }
        }
    }

    fn load_arguments(&mut self) {
        match self.resolve("arguments") {
            Resolved::Local(s, _) => {
                self.emit(Op::GetLocal(s));
            }
            Resolved::Env(d, s, _) => {
                self.emit(Op::GetEnv(d, s));
            }
            Resolved::Global => {
                let k = self.key_idx("arguments");
                self.emit(Op::GetGlobal(k));
            }
            Resolved::Dynamic => {
                let k = self.key_idx("arguments");
                self.emit(Op::GetName(k));
            }
            Resolved::Import(i) => {
                self.emit(Op::GetImport(i));
            }
        }
    }

    fn compile_unary(&mut self, op: UnaryOp, arg: &'a Expr) -> CResult<()> {
        match op {
            UnaryOp::Typeof => {
                if let Expr::Ident(id) = arg.unparen() {
                    match self.resolve(&id.name) {
                        Resolved::Global => {
                            let k = self.key_idx(&id.name);
                            self.emit(Op::TypeofGlobal(k));
                            return Ok(());
                        }
                        Resolved::Dynamic => {
                            let k = self.key_idx(&id.name);
                            self.emit(Op::TypeofName(k));
                            return Ok(());
                        }
                        _ => {}
                    }
                }
                self.compile_expr(arg)?;
                self.emit(Op::Typeof);
            }
            UnaryOp::Delete => match arg.unparen() {
                Expr::Member { obj, prop, optional } => {
                    self.compile_expr(obj)?;
                    if *optional {
                        self.emit_opt_check_bool(1)?;
                    }
                    match prop {
                        MemberProp::Name(n) => {
                            let k = self.key_idx(n);
                            self.emit(Op::DeleteProp(k));
                        }
                        MemberProp::Computed(k) => {
                            self.compile_expr(k)?;
                            self.emit(Op::DeleteElem);
                        }
                        MemberProp::Private(_) => return cerr("private fields cannot be deleted", 0),
                    }
                }
                Expr::OptChain(inner) => {
                    let l_end = self.new_label();
                    let saved = self.f().opt_end.replace(l_end);
                    let r = self.compile_unary(UnaryOp::Delete, inner);
                    self.f().opt_end = saved;
                    r?;
                    self.place(l_end);
                }
                Expr::Ident(id) => match self.resolve(&id.name) {
                    Resolved::Global | Resolved::Dynamic => {
                        let k = self.key_idx(&id.name);
                        self.emit(Op::DeleteName(k));
                    }
                    _ => {
                        self.emit(Op::False);
                    }
                },
                Expr::SuperMember(_) => {
                    self.emit(Op::ThisChk);
                    self.emit(Op::Pop);
                    let s = self.string_idx("Unsupported reference to 'super'");
                    self.emit(Op::ThrowRef(s));
                }
                other => {
                    self.compile_expr(other)?;
                    self.emit(Op::Pop);
                    self.emit(Op::True);
                }
            },
            _ => {
                self.compile_expr(arg)?;
                self.emit(match op {
                    UnaryOp::Neg => Op::Neg,
                    UnaryOp::Plus => Op::Plus,
                    UnaryOp::Not => Op::Not,
                    UnaryOp::BitNot => Op::BitNot,
                    UnaryOp::Void => Op::Void,
                    _ => unreachable!(),
                });
            }
        }
        Ok(())
    }

    /// like emit_opt_check but the short-circuit value is `true` (for delete)
    fn emit_opt_check_bool(&mut self, pops: u32) -> CResult<()> {
        let end = match self.f().opt_end {
            Some(l) => l,
            None => return cerr("optional chain outside chain", 0),
        };
        let cont = self.new_label();
        self.emit_jump(Op::JumpIfNotNullishKeep(0), cont);
        for _ in 0..pops {
            self.emit(Op::Pop);
        }
        self.emit(Op::True);
        self.emit_jump(Op::Jump(0), end);
        self.place(cont);
        Ok(())
    }

    fn compile_update(&mut self, inc: bool, prefix: bool, target: &'a Expr) -> CResult<()> {
        let op = if inc { Op::Inc } else { Op::Dec };
        match target.unparen() {
            Expr::Ident(id) => {
                self.load_name(&id.name);
                self.emit(Op::ToNumeric);
                if !prefix {
                    self.emit(Op::Dup);
                }
                self.emit(op);
                self.store_name(&id.name, id.line)?;
                if !prefix {
                    self.emit(Op::Pop);
                }
            }
            Expr::Member { obj, prop, .. } => {
                self.compile_expr(obj)?;
                match prop {
                    MemberProp::Name(n) => {
                        let k = self.key_idx(n);
                        self.emit(Op::Dup);
                        self.emit(Op::GetProp(k));
                        self.emit(Op::ToNumeric);
                        if !prefix {
                            self.emit(Op::Dup);
                            self.emit(Op::Rot3);
                        }
                        self.emit(op);
                        self.emit(Op::SetProp(k));
                    }
                    MemberProp::Computed(kx) => {
                        self.compile_expr(kx)?;
                        self.emit(Op::ToPropKey);
                        self.emit(Op::Dup2);
                        self.emit(Op::GetElem);
                        self.emit(Op::ToNumeric);
                        if !prefix {
                            self.emit(Op::Dup);
                            self.emit(Op::Rot4);
                        }
                        self.emit(op);
                        self.emit(Op::SetElem);
                    }
                    MemberProp::Private(n) => {
                        self.load_name(&format!("#{}", n));
                        self.emit(Op::Dup2);
                        self.emit(Op::GetPrivate);
                        self.emit(Op::ToNumeric);
                        if !prefix {
                            self.emit(Op::Dup);
                            self.emit(Op::Rot4);
                        }
                        self.emit(op);
                        self.emit(Op::SetPrivate);
                    }
                }
                if !prefix {
                    self.emit(Op::Pop);
                }
            }
            Expr::SuperMember(prop) => {
                self.load_this();
                match prop {
                    MemberProp::Name(n) => {
                        let k = self.key_idx(n);
                        self.emit(Op::Dup);
                        self.emit(Op::GetSuper(k));
                        self.emit(Op::ToNumeric);
                        if !prefix {
                            self.emit(Op::Dup);
                            self.emit(Op::Rot3);
                        }
                        self.emit(op);
                        self.emit(Op::SetSuper(k));
                    }
                    MemberProp::Computed(kx) => {
                        self.compile_expr(kx)?;
                        self.emit(Op::ToPropKey);
                        self.emit(Op::Dup2);
                        self.emit(Op::GetSuperElem);
                        self.emit(Op::ToNumeric);
                        if !prefix {
                            self.emit(Op::Dup);
                            self.emit(Op::Rot4);
                        }
                        self.emit(op);
                        self.emit(Op::SetSuperElem);
                    }
                    _ => return cerr("unexpected private", 0),
                }
                if !prefix {
                    self.emit(Op::Pop);
                }
            }
            _ => return cerr("invalid increment/decrement operand", 0),
        }
        Ok(())
    }

    fn compile_assign(&mut self, op: AssignOp, target: &'a Pattern, value: &'a Expr) -> CResult<()> {
        match target {
            Pattern::Ident(id) => {
                let hint = if value.is_anonymous_fn() { Some(JsStr::from_str(&id.name)) } else { None };
                match op {
                    AssignOp::Assign => {
                        // unresolvable reference in strict mode must throw before evaluating? spec:
                        // reference resolved first, PutValue throws at assignment time
                        self.compile_expr_named(value, hint)?;
                        self.store_name(&id.name, id.line)?;
                    }
                    AssignOp::Bin(b) => {
                        self.load_name(&id.name);
                        self.compile_expr(value)?;
                        self.emit(binop(b));
                        self.store_name(&id.name, id.line)?;
                    }
                    AssignOp::Logical(l) => {
                        let end = self.new_label();
                        self.load_name(&id.name);
                        self.emit_logical_jump(l, end);
                        self.emit(Op::Pop);
                        self.compile_expr_named(value, hint)?;
                        self.store_name(&id.name, id.line)?;
                        self.place(end);
                    }
                }
            }
            Pattern::Expr(e) => match e.unparen() {
                Expr::Member { obj, prop, .. } => {
                    self.compile_expr(obj)?;
                    match prop {
                        MemberProp::Name(n) => {
                            let k = self.key_idx(n);
                            match op {
                                AssignOp::Assign => {
                                    self.compile_expr(value)?;
                                    self.emit(Op::SetProp(k));
                                }
                                AssignOp::Bin(b) => {
                                    self.emit(Op::Dup);
                                    self.emit(Op::GetProp(k));
                                    self.compile_expr(value)?;
                                    self.emit(binop(b));
                                    self.emit(Op::SetProp(k));
                                }
                                AssignOp::Logical(l) => {
                                    let short = self.new_label();
                                    let end = self.new_label();
                                    self.emit(Op::Dup);
                                    self.emit(Op::GetProp(k));
                                    self.emit_logical_jump(l, short);
                                    self.emit(Op::Pop);
                                    self.compile_expr(value)?;
                                    self.emit(Op::SetProp(k));
                                    self.emit_jump(Op::Jump(0), end);
                                    self.place(short);
                                    self.emit(Op::Swap);
                                    self.emit(Op::Pop);
                                    self.place(end);
                                }
                            }
                        }
                        MemberProp::Computed(kx) => {
                            self.compile_expr(kx)?;
                            match op {
                                AssignOp::Assign => {
                                    self.compile_expr(value)?;
                                    self.emit(Op::SetElem);
                                }
                                AssignOp::Bin(b) => {
                                    self.emit(Op::ToPropKey);
                                    self.emit(Op::Dup2);
                                    self.emit(Op::GetElem);
                                    self.compile_expr(value)?;
                                    self.emit(binop(b));
                                    self.emit(Op::SetElem);
                                }
                                AssignOp::Logical(l) => {
                                    let short = self.new_label();
                                    let end = self.new_label();
                                    self.emit(Op::ToPropKey);
                                    self.emit(Op::Dup2);
                                    self.emit(Op::GetElem);
                                    self.emit_logical_jump(l, short);
                                    self.emit(Op::Pop);
                                    self.compile_expr(value)?;
                                    self.emit(Op::SetElem);
                                    self.emit_jump(Op::Jump(0), end);
                                    self.place(short);
                                    self.emit(Op::Rot3);
                                    self.emit(Op::Pop);
                                    self.emit(Op::Pop);
                                    self.place(end);
                                }
                            }
                        }
                        MemberProp::Private(n) => {
                            self.load_name(&format!("#{}", n));
                            match op {
                                AssignOp::Assign => {
                                    self.compile_expr(value)?;
                                    self.emit(Op::SetPrivate);
                                }
                                AssignOp::Bin(b) => {
                                    self.emit(Op::Dup2);
                                    self.emit(Op::GetPrivate);
                                    self.compile_expr(value)?;
                                    self.emit(binop(b));
                                    self.emit(Op::SetPrivate);
                                }
                                AssignOp::Logical(l) => {
                                    let short = self.new_label();
                                    let end = self.new_label();
                                    self.emit(Op::Dup2);
                                    self.emit(Op::GetPrivate);
                                    self.emit_logical_jump(l, short);
                                    self.emit(Op::Pop);
                                    self.compile_expr(value)?;
                                    self.emit(Op::SetPrivate);
                                    self.emit_jump(Op::Jump(0), end);
                                    self.place(short);
                                    self.emit(Op::Rot3);
                                    self.emit(Op::Pop);
                                    self.emit(Op::Pop);
                                    self.place(end);
                                }
                            }
                        }
                    }
                }
                Expr::SuperMember(prop) => {
                    self.load_this();
                    match prop {
                        MemberProp::Name(n) => {
                            let k = self.key_idx(n);
                            match op {
                                AssignOp::Assign => {
                                    self.compile_expr(value)?;
                                    self.emit(Op::SetSuper(k));
                                }
                                AssignOp::Bin(b) => {
                                    self.emit(Op::Dup);
                                    self.emit(Op::GetSuper(k));
                                    self.compile_expr(value)?;
                                    self.emit(binop(b));
                                    self.emit(Op::SetSuper(k));
                                }
                                AssignOp::Logical(l) => {
                                    let short = self.new_label();
                                    let end = self.new_label();
                                    self.emit(Op::Dup);
                                    self.emit(Op::GetSuper(k));
                                    self.emit_logical_jump(l, short);
                                    self.emit(Op::Pop);
                                    self.compile_expr(value)?;
                                    self.emit(Op::SetSuper(k));
                                    self.emit_jump(Op::Jump(0), end);
                                    self.place(short);
                                    self.emit(Op::Swap);
                                    self.emit(Op::Pop);
                                    self.place(end);
                                }
                            }
                        }
                        MemberProp::Computed(kx) => {
                            self.compile_expr(kx)?;
                            self.emit(Op::ToPropKey);
                            match op {
                                AssignOp::Assign => {
                                    self.compile_expr(value)?;
                                    self.emit(Op::SetSuperElem);
                                }
                                AssignOp::Bin(b) => {
                                    self.emit(Op::Dup2);
                                    self.emit(Op::GetSuperElem);
                                    self.compile_expr(value)?;
                                    self.emit(binop(b));
                                    self.emit(Op::SetSuperElem);
                                }
                                AssignOp::Logical(l) => {
                                    let short = self.new_label();
                                    let end = self.new_label();
                                    self.emit(Op::Dup2);
                                    self.emit(Op::GetSuperElem);
                                    self.emit_logical_jump(l, short);
                                    self.emit(Op::Pop);
                                    self.compile_expr(value)?;
                                    self.emit(Op::SetSuperElem);
                                    self.emit_jump(Op::Jump(0), end);
                                    self.place(short);
                                    self.emit(Op::Rot3);
                                    self.emit(Op::Pop);
                                    self.emit(Op::Pop);
                                    self.place(end);
                                }
                            }
                        }
                        _ => return cerr("unexpected private", 0),
                    }
                }
                Expr::Ident(id) => {
                    // parenthesized identifier target
                    let pat = Pattern::Ident(id.clone());
                    let _ = pat;
                    match op {
                        AssignOp::Assign => {
                            self.compile_expr(value)?;
                            self.store_name(&id.name, id.line)?;
                        }
                        AssignOp::Bin(b) => {
                            self.load_name(&id.name);
                            self.compile_expr(value)?;
                            self.emit(binop(b));
                            self.store_name(&id.name, id.line)?;
                        }
                        AssignOp::Logical(l) => {
                            let end = self.new_label();
                            self.load_name(&id.name);
                            self.emit_logical_jump(l, end);
                            self.emit(Op::Pop);
                            self.compile_expr(value)?;
                            self.store_name(&id.name, id.line)?;
                            self.place(end);
                        }
                    }
                }
                _ => return cerr("invalid assignment target", 0),
            },
            Pattern::Array { .. } | Pattern::Object { .. } => {
                self.compile_expr(value)?;
                self.emit(Op::Dup);
                self.compile_pattern(target, None)?;
            }
        }
        Ok(())
    }

    fn emit_logical_jump(&mut self, l: LogicalOp, target: Label) {
        match l {
            LogicalOp::And => self.emit_jump(Op::JumpIfFalseKeep(0), target),
            LogicalOp::Or => self.emit_jump(Op::JumpIfTrueKeep(0), target),
            LogicalOp::Nullish => self.emit_jump(Op::JumpIfNotNullishKeep(0), target),
        };
    }

    /// compile callee producing [this, func]
    fn compile_callee(&mut self, callee: &'a Expr) -> CResult<()> {
        match callee {
            Expr::Paren(inner) if matches!(inner.unparen(), Expr::Member { .. } | Expr::SuperMember(_)) => {
                self.compile_callee(inner.unparen())
            }
            Expr::Member { obj, prop, optional } => {
                self.compile_expr(obj)?;
                if *optional {
                    self.emit_opt_check(1)?;
                }
                match prop {
                    MemberProp::Name(n) => {
                        let k = self.key_idx(n);
                        self.emit(Op::GetMethod(k));
                    }
                    MemberProp::Computed(k) => {
                        self.compile_expr(k)?;
                        self.emit(Op::GetMethodElem);
                    }
                    MemberProp::Private(n) => {
                        self.emit(Op::Dup);
                        self.load_name(&format!("#{}", n));
                        self.emit(Op::GetPrivate);
                    }
                }
                Ok(())
            }
            Expr::SuperMember(prop) => {
                self.load_this();
                self.emit(Op::Dup);
                match prop {
                    MemberProp::Name(n) => {
                        let k = self.key_idx(n);
                        self.emit(Op::GetSuper(k));
                    }
                    MemberProp::Computed(k) => {
                        self.compile_expr(k)?;
                        self.emit(Op::ToPropKey);
                        self.emit(Op::GetSuperElem);
                    }
                    _ => return cerr("unexpected private", 0),
                }
                Ok(())
            }
            Expr::Ident(id) => {
                match self.resolve(&id.name) {
                    Resolved::Dynamic => {
                        let k = self.key_idx(&id.name);
                        self.emit(Op::GetNameCall(k));
                    }
                    _ => {
                        self.emit(Op::Undef);
                        if &*id.name == "arguments" {
                            self.load_arguments();
                        } else {
                            self.load_name(&id.name);
                        }
                    }
                }
                Ok(())
            }
            Expr::OptChain(_) => {
                self.emit(Op::Undef);
                self.compile_expr(callee)
            }
            other => {
                self.emit(Op::Undef);
                self.compile_expr(other)
            }
        }
    }

    fn callee_desc(&mut self, callee: &Expr) -> u32 {
        match callee {
            Expr::Ident(id) => self.string_idx(&id.name),
            Expr::Paren(inner) => match inner.unparen() {
                Expr::Ident(id) => self.string_idx(&id.name),
                Expr::Member { prop: MemberProp::Name(n), .. } => self.string_idx(&format!("(intermediate value).{}", n)),
                _ => self.string_idx("expression"),
            },
            Expr::Member { prop: MemberProp::Name(n), .. } => self.string_idx(&format!("(intermediate value).{}", n)),
            Expr::SuperMember(_) => u32::MAX,
            _ => self.string_idx("expression"),
        }
    }

    fn compile_args_array(&mut self, args: &'a [ArrayElem]) -> CResult<()> {
        self.emit(Op::NewArray(0));
        for a in args {
            match a {
                ArrayElem::Expr(e) => {
                    self.compile_expr(e)?;
                    self.emit(Op::ArrayPush);
                }
                ArrayElem::Spread(e) => {
                    self.compile_expr(e)?;
                    self.emit(Op::ArraySpread);
                }
            }
        }
        Ok(())
    }

    fn compile_call(&mut self, callee: &'a Expr, args: &'a [ArrayElem], optional: bool, _x: Option<()>) -> CResult<()> {
        let is_direct_eval = matches!(callee.unparen(), Expr::Ident(id) if &*id.name == "eval")
            && matches!(self.resolve("eval"), Resolved::Global | Resolved::Dynamic);
        let desc = self.callee_desc(callee);
        self.compile_callee(callee)?;
        if optional {
            self.emit_opt_check(2)?;
        }
        let has_spread = args.iter().any(|a| matches!(a, ArrayElem::Spread(_)));
        if has_spread {
            self.compile_args_array(args)?;
            if is_direct_eval {
                self.emit(Op::CallEvalArray);
            } else {
                self.emit(Op::CallArray(desc));
            }
        } else {
            for a in args {
                if let ArrayElem::Expr(e) = a {
                    self.compile_expr(e)?;
                }
            }
            if is_direct_eval {
                self.emit(Op::CallEval(args.len() as u32));
            } else {
                self.emit(Op::Call(args.len() as u32, desc));
            }
        }
        Ok(())
    }

    fn compile_object(&mut self, props: &'a [PropDef]) -> CResult<()> {
        self.emit(Op::NewObject);
        for p in props {
            match p {
                PropDef::KeyValue(key, v) => match key {
                    PropKey::Computed(k) => {
                        self.compile_expr(k)?;
                        self.emit(Op::ToPropKey);
                        self.compile_expr(v)?;
                        if v.is_anonymous_fn() {
                            self.emit(Op::SetFunctionName(0));
                        }
                        self.emit(Op::DefineFieldComputed);
                    }
                    k => {
                        let name = propkey_static_name(k).unwrap();
                        let hint = if v.is_anonymous_fn() { Some(JsStr::from_str(&name)) } else { None };
                        self.compile_expr_named(v, hint)?;
                        let ki = match k {
                            PropKey::Str(u) => self.key_idx_units(u),
                            _ => self.key_idx(&name),
                        };
                        self.emit(Op::DefineField(ki));
                    }
                },
                PropDef::Shorthand(id) => {
                    if &*id.name == "arguments" {
                        self.load_arguments();
                    } else {
                        self.load_name(&id.name);
                    }
                    let k = self.key_idx(&id.name);
                    self.emit(Op::DefineField(k));
                }
                PropDef::Proto(v) => {
                    self.compile_expr(v)?;
                    self.emit(Op::SetProtoLit);
                }
                PropDef::Spread(e) => {
                    self.compile_expr(e)?;
                    self.emit(Op::CopyDataProps);
                }
                PropDef::Method { key, func, kind } => {
                    let mk = match kind {
                        MethodKind::Method => MKind::Method,
                        MethodKind::Getter => MKind::Getter,
                        MethodKind::Setter => MKind::Setter,
                    };
                    match key {
                        PropKey::Computed(k) => {
                            self.compile_expr(k)?;
                            self.emit(Op::ToPropKey);
                            let idx = self.compile_function(func, None)?;
                            // [obj key] -> method with home obj
                            self.emit(Op::Pick(1));
                            self.emit(Op::Method(idx));
                            // [obj key obj fn]
                            self.emit(Op::Swap);
                            self.emit(Op::Pop);
                            // [obj key fn]
                            match mk {
                                MKind::Method => {
                                    self.emit(Op::SetFunctionName(0));
                                    self.emit(Op::DefineFieldComputed);
                                }
                                MKind::Getter => {
                                    self.emit(Op::SetFunctionName(1));
                                    self.emit(Op::DefineAccessorComputed(MKind::Getter));
                                }
                                MKind::Setter => {
                                    self.emit(Op::SetFunctionName(2));
                                    self.emit(Op::DefineAccessorComputed(MKind::Setter));
                                }
                            }
                        }
                        k => {
                            let name = propkey_static_name(k).unwrap();
                            let fname = match mk {
                                MKind::Method => name.clone(),
                                MKind::Getter => format!("get {}", name),
                                MKind::Setter => format!("set {}", name),
                            };
                            let idx = self.compile_function(func, Some(JsStr::from_str(&fname)))?;
                            self.emit(Op::Method(idx));
                            // [obj fn]
                            let ki = match k {
                                PropKey::Str(u) => self.key_idx_units(u),
                                _ => self.key_idx(&name),
                            };
                            match mk {
                                MKind::Method => {
                                    self.emit(Op::DefineField(ki));
                                }
                                MKind::Getter | MKind::Setter => {
                                    self.emit(Op::DefineAccessor(ki, mk));
                                }
                            }
                        }
                    }
                }
            }
        }
        Ok(())
    }

    // ---------- functions ----------

    /// Compile a nested function; returns its index in the current function's funcs table.
    fn compile_function(&mut self, f: &'a Function, name_hint: Option<JsStr>) -> CResult<u32> {
        let code = self.compile_function_code(f, name_hint)?;
        let st = self.f();
        st.funcs.push(code);
        Ok((st.funcs.len() - 1) as u32)
    }

    fn compile_function_code(&mut self, f: &'a Function, name_hint: Option<JsStr>) -> CResult<Rc<FunctionCode>> {
        let rid = f.scope.get() as usize;
        let is_arrow = f.kind == FuncKind::Arrow;
        // named function expression scope
        let has_name_scope = f.is_expr && f.name.is_some() && f.kind == FuncKind::Normal;
        let mut name_scope_pushed = false;
        if has_name_scope {
            // the name scope is the parent of the function scope in the resolver
            let parent = self.rscope(rid).parent.unwrap();
            let ps = self.rscope(parent);
            if ps.kind == ScopeKind::FuncName {
                // a FuncName scope's binding is captured if referenced inside: it lives in an env
                // created when the closure is made. We represent it as an env scope entered in the
                // *inner* function prologue instead (the closure value itself).
                name_scope_pushed = true;
            }
        }
        let mut fs = FuncState::new(f.kind, is_arrow, f.is_async, f.is_generator, f.strict, rid);
        fs.is_arrow = is_arrow;
        self.fs.push(fs);
        if name_scope_pushed {
            let parent = self.rscope(rid).parent.unwrap();
            let ps = self.rscope(parent);
            let d = &ps.decls[0];
            // own name binding: store as local (or env if captured) initialized to callee
            let st = if d.captured {
                let info = Rc::new(ScopeInfo { names: vec![JsStr::from_str(&d.name)], kinds: vec![BindKind::FuncName], is_function: false });
                let fst = self.f();
                fst.scope_infos.push(info);
                let idx = (fst.scope_infos.len() - 1) as u32;
                self.emit(Op::PushScope(idx));
                Storage::Env(0)
            } else {
                Storage::Local(self.new_local())
            };
            self.f().scopes.push(CScope {
                rid: parent,
                has_env: d.captured,
                names: vec![(d.name.clone(), st, BindKind::FuncName)],
                is_with: false,
                dyn_eval: false,
            });
            self.emit(Op::Callee);
            match st {
                Storage::Local(s) => {
                    self.emit(Op::InitLocal(s));
                }
                Storage::Env(s) => {
                    self.emit(Op::InitEnv(0, s));
                }
            }
        }
        let rs = self.rscope(rid);
        let force_env = rs.has_eval || rs.contains_eval;
        self.enter_scope(rid, force_env);
        self.init_internal_bindings(rid);
        // parameters
        let mut length = 0u32;
        let mut seen_default = false;
        for (i, p) in f.params.iter().enumerate() {
            if p.rest {
                self.emit(Op::GetRest(i as u32));
                seen_default = true;
            } else {
                self.emit(Op::GetArg(i as u32));
                if let Some(d) = &p.default {
                    seen_default = true;
                    let l = self.new_label();
                    self.emit(Op::Dup);
                    self.emit_jump(Op::JumpIfNotUndef(0), l);
                    self.emit(Op::Pop);
                    let hint = match &p.pat {
                        Pattern::Ident(id) if d.is_anonymous_fn() => Some(JsStr::from_str(&id.name)),
                        _ => None,
                    };
                    self.compile_expr_named(d, hint)?;
                    self.place(l);
                } else if !seen_default {
                    length += 1;
                }
            }
            match &p.pat {
                Pattern::Ident(id) => {
                    // params are var-like (mutable)
                    match self.resolve(&id.name) {
                        Resolved::Local(s, _) => {
                            self.emit(Op::InitLocal(s));
                        }
                        Resolved::Env(d, s, _) => {
                            self.emit(Op::InitEnv(d, s));
                        }
                        _ => {
                            self.init_name(&id.name);
                        }
                    }
                }
                other => self.compile_pattern(other, Some(VarKind::Let))?,
            }
        }
        // `arguments` when shadowed by nothing is created in init_internal_bindings
        self.hoist_functions(&f.body, true)?;
        if f.is_generator {
            self.emit(Op::GenStart);
        }
        for s in &f.body {
            self.compile_stmt(s)?;
        }
        self.emit(Op::Undef);
        if f.kind == FuncKind::DerivedConstructor {
            self.emit_return()?;
        } else {
            self.emit(Op::Return);
        }
        self.exit_scope_noemit();
        if name_scope_pushed {
            self.f().scopes.pop();
        }
        let fs = self.fs.pop().unwrap();
        let name = match (&f.name, name_hint) {
            (Some(n), _) => JsStr::from_str(&n.name),
            (None, Some(h)) => h,
            (None, None) => JsStr::empty(),
        };
        let mut code = self.finish(fs, name, length, f.src_start, f.src_end, f.line, f.simple_params);
        code.no_prototype = !matches!(f.kind, FuncKind::Normal | FuncKind::ClassConstructor | FuncKind::DerivedConstructor) || (f.is_async && !f.is_generator);
        Ok(Rc::new(code))
    }

    // ---------- classes ----------

    fn compile_class(&mut self, c: &'a Class, name_hint: Option<JsStr>) -> CResult<()> {
        let rid = c.scope.get() as usize;
        let has_env = self.enter_scope(rid, false);
        if has_env {
            self.f().ctl.push(Ctl::Scope);
        }
        let class_name: JsStr = match (&c.name, &name_hint) {
            (Some(n), _) => JsStr::from_str(&n.name),
            (None, Some(h)) => h.clone(),
            (None, None) => JsStr::empty(),
        };
        // private names
        let rs = self.rscope(rid);
        for d in &rs.decls {
            if d.name.starts_with('#') {
                let si = self.string_idx(&d.name[1..]);
                self.emit(Op::NewPrivateName(si));
                self.init_name(&d.name.clone());
            }
        }
        if let Some(h) = &c.extends {
            self.compile_expr(h)?;
        }
        // constructor
        let ctor_code = match &c.constructor {
            Some(ctor) => {
                let mut code = self.compile_function_code(ctor, Some(class_name.clone()))?;
                if let Some(cm) = Rc::get_mut(&mut code) {
                    cm.src_start = c.src_start;
                    cm.src_end = c.src_end;
                    cm.class_source = true;
                }
                code
            }
            None => {
                let derived = c.extends.is_some();
                let fs = FuncState::new(
                    if derived { FuncKind::DerivedConstructor } else { FuncKind::ClassConstructor },
                    false,
                    false,
                    false,
                    true,
                    rid,
                );
                self.fs.push(fs);
                if derived {
                    self.emit(Op::Callee);
                    self.emit(Op::NewTarget);
                    self.emit(Op::SuperCallForward);
                    // [F result]
                    self.emit(Op::Dup);
                    self.emit(Op::BindThis);
                    self.emit(Op::Swap);
                    self.emit(Op::InitFields);
                    self.emit(Op::Pop);
                    self.emit(Op::ThisChk);
                    self.emit(Op::Return);
                } else {
                    self.emit(Op::Undef);
                    self.emit(Op::Return);
                }
                let fs = self.fs.pop().unwrap();
                let mut code = self.finish(fs, class_name.clone(), 0, c.src_start, c.src_end, 0, true);
                code.class_source = true;
                Rc::new(code)
            }
        };
        let st = self.f();
        st.funcs.push(ctor_code);
        let ctor_idx = (st.funcs.len() - 1) as u32;
        self.emit(Op::CreateClass(ctor_idx, c.extends.is_some()));
        // [F proto]
        let mut deferred: Vec<(&'a ClassMember, Option<u32>)> = Vec::new();
        for m in &c.members {
            match m {
                ClassMember::Method { key, func, kind, is_static } => {
                    let mk = match kind {
                        MethodKind::Method => MKind::Method,
                        MethodKind::Getter => MKind::Getter,
                        MethodKind::Setter => MKind::Setter,
                    };
                    let target = if *is_static { MethodTarget::Ctor } else { MethodTarget::Proto };
                    match key {
                        PropKey::Private(n) => {
                            let fname = match mk {
                                MKind::Method => format!("#{}", n),
                                MKind::Getter => format!("get #{}", n),
                                MKind::Setter => format!("set #{}", n),
                            };
                            let idx = self.compile_function(func, Some(JsStr::from_str(&fname)))?;
                            self.load_name(&format!("#{}", n));
                            self.emit(Op::AddPrivateMethod(idx, mk, *is_static));
                        }
                        PropKey::Computed(k) => {
                            self.compile_expr(k)?;
                            self.emit(Op::ToPropKey);
                            let idx = self.compile_function(func, None)?;
                            self.emit(Op::DefineMethodComputed(target, mk, idx));
                        }
                        k => {
                            let name = propkey_static_name(k).unwrap();
                            let fname = match mk {
                                MKind::Method => name.clone(),
                                MKind::Getter => format!("get {}", name),
                                MKind::Setter => format!("set {}", name),
                            };
                            let idx = self.compile_function(func, Some(JsStr::from_str(&fname)))?;
                            let ki = match k {
                                PropKey::Str(u) => self.key_idx_units(u),
                                _ => self.key_idx(&name),
                            };
                            self.emit(Op::DefineMethod(ki, target, mk, idx));
                        }
                    }
                }
                ClassMember::Field { key, value, is_static, is_accessor: _ } => {
                    let fname: Option<String> = match key {
                        PropKey::Private(n) => Some(format!("#{}", n)),
                        PropKey::Computed(_) => None,
                        k => propkey_static_name(k),
                    };
                    let init_idx = match value {
                        Some(v) => {
                            let hint = fname.as_ref().map(|s| JsStr::from_str(s));
                            let hint_for_value = match &v.body[0] {
                                Stmt::Return(Some(e)) if e.is_anonymous_fn() => hint,
                                _ => None,
                            };
                            self.compile_field_init(v, hint_for_value)?
                        }
                        None => u32::MAX,
                    };
                    if *is_static {
                        match key {
                            PropKey::Computed(k) => {
                                self.compile_expr(k)?;
                                self.emit(Op::ToPropKey);
                                let t = self.new_local();
                                self.emit(Op::SetLocal(t));
                                self.emit(Op::Pop);
                                deferred.push((m, Some(t)));
                            }
                            _ => deferred.push((m, None)),
                        }
                        // store init idx alongside via a side table
                        self.f().pending_static.push(init_idx);
                    } else {
                        match key {
                            PropKey::Computed(k) => {
                                self.compile_expr(k)?;
                                self.emit(Op::ToPropKey);
                                self.emit(Op::AddFieldComputed(init_idx, false));
                            }
                            PropKey::Private(n) => {
                                self.load_name(&format!("#{}", n));
                                self.emit(Op::AddFieldPrivate(init_idx));
                            }
                            k => {
                                let name = propkey_static_name(k).unwrap();
                                let ki = match k {
                                    PropKey::Str(u) => self.key_idx_units(u),
                                    _ => self.key_idx(&name),
                                };
                                self.emit(Op::AddField(ki, init_idx, false));
                            }
                        }
                    }
                }
                ClassMember::StaticBlock(f) => {
                    let idx = self.compile_field_init(f, None)?;
                    deferred.push((m, None));
                    self.f().pending_static.push(idx);
                }
            }
        }
        // class binding must be initialized before static initializers run
        let pending: Vec<u32> = std::mem::take(&mut self.f().pending_static);
        if let Some(n) = &c.name {
            // [F proto] -> init inner binding with F
            self.emit(Op::Pick(1));
            self.init_name(&n.name);
        }
        for ((m, tmp), init_idx) in deferred.into_iter().zip(pending.into_iter()) {
            match m {
                ClassMember::Field { key, .. } => match key {
                    PropKey::Computed(_) => {
                        self.emit(Op::GetLocal(tmp.unwrap()));
                        self.emit(Op::StaticFieldComputed(init_idx));
                    }
                    PropKey::Private(n) => {
                        self.load_name(&format!("#{}", n));
                        self.emit(Op::StaticPrivateField(init_idx));
                    }
                    k => {
                        let name = propkey_static_name(k).unwrap();
                        let ki = match k {
                            PropKey::Str(u) => self.key_idx_units(u),
                            _ => self.key_idx(&name),
                        };
                        self.emit(Op::StaticField(ki, init_idx));
                    }
                },
                ClassMember::StaticBlock(_) => {
                    self.emit(Op::StaticBlock(init_idx));
                }
                _ => {}
            }
        }
        self.emit(Op::Pop); // proto
        if has_env {
            self.f().ctl.pop();
        }
        self.exit_scope();
        Ok(())
    }

    fn compile_field_init(&mut self, f: &'a Function, name_hint: Option<JsStr>) -> CResult<u32> {
        // field initializer: body is `return expr` (or a static block body)
        let rid = f.scope.get() as usize;
        let fs = FuncState::new(f.kind, false, false, false, true, rid);
        self.fs.push(fs);
        let rs = self.rscope(rid);
        let force_env = rs.has_eval || rs.contains_eval;
        self.enter_scope(rid, force_env);
        self.init_internal_bindings(rid);
        self.hoist_functions(&f.body, true)?;
        if f.kind == FuncKind::ClassFieldInit {
            if let Some(Stmt::Return(Some(e))) = f.body.first() {
                self.compile_expr_named(e, name_hint)?;
                self.emit(Op::Return);
            }
        } else {
            for s in &f.body {
                self.compile_stmt(s)?;
            }
        }
        self.emit(Op::Undef);
        self.emit(Op::Return);
        self.exit_scope_noemit();
        let fs = self.fs.pop().unwrap();
        let mut code = self.finish(fs, JsStr::empty(), 0, f.src_start, f.src_end, f.line, true);
        code.no_prototype = true;
        let st = self.f();
        st.funcs.push(Rc::new(code));
        Ok((st.funcs.len() - 1) as u32)
    }
}

#[derive(Debug)]
enum Resolved {
    Local(u32, BindKind),
    Env(u16, u32, BindKind),
    Global,
    Dynamic,
    Import(u32),
}

fn fs_find(sc: &CScope, name: &str) -> Option<(Storage, BindKind)> {
    sc.names.iter().find(|(n, _, _)| &**n == name).map(|(_, s, k)| (*s, *k))
}

fn binop(op: BinOp) -> Op {
    match op {
        BinOp::Add => Op::Add,
        BinOp::Sub => Op::Sub,
        BinOp::Mul => Op::Mul,
        BinOp::Div => Op::Div,
        BinOp::Mod => Op::Mod,
        BinOp::Exp => Op::Exp,
        BinOp::Shl => Op::Shl,
        BinOp::Shr => Op::Shr,
        BinOp::UShr => Op::UShr,
        BinOp::BitAnd => Op::BitAnd,
        BinOp::BitOr => Op::BitOr,
        BinOp::BitXor => Op::BitXor,
        BinOp::Eq => Op::Eq,
        BinOp::Ne => Op::Ne,
        BinOp::StrictEq => Op::StrictEq,
        BinOp::StrictNe => Op::StrictNe,
        BinOp::Lt => Op::Lt,
        BinOp::Le => Op::Le,
        BinOp::Gt => Op::Gt,
        BinOp::Ge => Op::Ge,
        BinOp::In => Op::In,
        BinOp::InstanceOf => Op::InstanceOf,
    }
}

pub fn parse_bigint_literal(s: &str) -> crate::bigint::BigInt {
    let (digits, radix) = if s.len() > 2 && s.as_bytes()[0] == b'0' {
        match s.as_bytes()[1] {
            b'x' | b'X' => (&s[2..], 16),
            b'o' | b'O' => (&s[2..], 8),
            b'b' | b'B' => (&s[2..], 2),
            _ => (s, 10),
        }
    } else {
        (s, 10)
    };
    crate::bigint::BigInt::parse_literal(digits, radix)
}

impl<'a> FuncState<'a> {
    fn new(kind: FuncKind, is_arrow: bool, is_async: bool, is_generator: bool, strict: bool, rid: usize) -> FuncState<'a> {
        FuncState {
            ops: Vec::new(),
            consts: Vec::new(),
            keys: Vec::new(),
            key_index: HashMap::new(),
            funcs: Vec::new(),
            scope_infos: Vec::new(),
            templates: Vec::new(),
            regexps: Vec::new(),
            strings: Vec::new(),
            nlocals: 0,
            scopes: Vec::new(),
            ctl: Vec::new(),
            label_pos: Vec::new(),
            fixups: Vec::new(),
            ret_slot: None,
            completion_slot: None,
            kind,
            is_arrow,
            is_async,
            is_generator,
            strict,
            func_rid: rid,
            pending_labels: Vec::new(),
            imports: Vec::new(),
            opt_end: None,
            pending_static: Vec::new(),
            scope_marks: Vec::new(),
        }
    }
}
