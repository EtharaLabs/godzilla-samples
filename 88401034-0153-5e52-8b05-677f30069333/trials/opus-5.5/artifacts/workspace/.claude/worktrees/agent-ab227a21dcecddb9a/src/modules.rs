// ES modules: records, linking, evaluation (with top-level await), namespaces.

use crate::ast::{ExportDecl, Stmt};
use crate::bytecode::FunctionCode;
use crate::object::*;
use crate::value::*;
use crate::vm::{Completion, Env, Frame, JsResult, Vm};
use std::cell::{Cell, RefCell};
use std::path::{Path, PathBuf};
use std::rc::Rc;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Status {
    New,
    Linking,
    Linked,
    Evaluating,
    Evaluated,
    Errored,
}

#[derive(Clone)]
pub enum Binding {
    Slot(Env, u32),
    Namespace(Rc<ModuleRecord>),
    Synthetic(Value, PropKey),
    SyntheticDefault(Value),
}

pub struct ImportEntry {
    pub specifier: Rc<str>,
    /// imported name; "*" for namespace imports
    pub name: Rc<str>,
}

pub struct ModuleRecord {
    pub path: String,
    pub url: String,
    pub dir: String,
    pub env: RefCell<Option<Env>>,
    pub env_names: Vec<Rc<str>>,
    pub frame: RefCell<Option<Box<Frame>>>,
    pub code: Option<Rc<FunctionCode>>,
    pub imports: Vec<ImportEntry>,
    pub import_bindings: RefCell<Vec<Option<Binding>>>,
    pub local_exports: Vec<(Rc<str>, Rc<str>)>,
    pub indirect_exports: Vec<(Rc<str>, Rc<str>, Rc<str>)>,
    pub star_exports: Vec<Rc<str>>,
    pub requested: Vec<Rc<str>>,
    pub resolved: RefCell<Vec<(Rc<str>, Rc<ModuleRecord>)>>,
    pub status: Cell<Status>,
    pub namespace: RefCell<Option<Obj>>,
    /// synthetic module (builtin / CommonJS): the exports value
    pub synthetic: Option<Value>,
    pub error: RefCell<Option<Value>>,
    pub has_tla: bool,
    pub meta: RefCell<Option<Obj>>,
}

pub fn file_url(p: &str) -> String {
    format!("file://{}", p)
}

fn not_found(vm: &mut Vm, spec: &str, from: &str) -> Value {
    vm.make_error("TypeError", &format!("module not found: {} (imported from {})", spec, from))
}

fn resolve_spec(spec: &str, dir: &str) -> Option<crate::runtime::node::Resolved> {
    let s = spec.strip_prefix("file://").unwrap_or(spec);
    crate::runtime::node::resolve_esm(s, dir)
}

/// Load (parse) a module record from a file, caching it.
pub fn load_module(vm: &mut Vm, path: &Path) -> JsResult<Rc<ModuleRecord>> {
    let key = path.to_string_lossy().to_string();
    if let Some(m) = vm.host.esm_cache.get(&key) {
        return Ok(m.clone());
    }
    let src = match std::fs::read(path) {
        Ok(b) => String::from_utf8_lossy(&b).to_string(),
        Err(_) => return vm.throw_type(format!("module not found: {}", key)),
    };
    let ext = path.extension().map(|e| e.to_string_lossy().to_string()).unwrap_or_default();
    // imported files: .mjs/.jsx are ES modules, .cjs/.json never; everything else follows the
    // nearest package.json "type" (CommonJS otherwise, where .ts/.cts get type-stripped)
    let is_esm = match ext.as_str() {
        "mjs" | "jsx" => true,
        "cjs" | "json" => false,
        _ => package_type_module(path),
    };
    let src = if ext == "jsx" { crate::runtime::jsx_transform(&src).unwrap_or(src) } else { src };
    if !is_esm && ext == "json" {
        // JSON: synthetic module
        let exports = crate::runtime::node::load_cjs(vm, path, None)?;
        let rec = synthetic_record(&key, exports);
        vm.host.esm_cache.insert(key, rec.clone());
        return Ok(rec);
    }
    if !is_esm {
        // CommonJS: runs when the graph is evaluated; importers link against names found in
        // its source text
        let names_src = if ext == "ts" || ext == "cts" { crate::runtime::strip_types(&src).unwrap_or_default() } else { src };
        let names = crate::runtime::node::cjs_export_names(&names_src);
        let cell = Obj::new(None, ObjKind::Host(Box::new(CjsCell { path: path.to_path_buf(), names, exports: RefCell::new(None) })));
        let rec = synthetic_record(&key, Value::Obj(cell));
        rec.status.set(Status::Linked);
        vm.host.esm_cache.insert(key, rec.clone());
        return Ok(rec);
    }
    let rec = compile_module_record(vm, &key, &src)?;
    vm.host.esm_cache.insert(key, rec.clone());
    Ok(rec)
}

pub fn package_type_module(path: &Path) -> bool {
    let mut d = path.parent();
    while let Some(dir) = d {
        let pj = dir.join("package.json");
        if pj.is_file() {
            if let Ok(s) = std::fs::read_to_string(&pj) {
                return crate::runtime::node::json_string_field(&s, "type").as_deref() == Some("module");
            }
            return false;
        }
        d = dir.parent();
    }
    false
}

pub fn synthetic_record(name: &str, exports: Value) -> Rc<ModuleRecord> {
    Rc::new(ModuleRecord {
        path: name.to_string(),
        url: name.to_string(),
        dir: String::new(),
        env: RefCell::new(None),
        env_names: Vec::new(),
        frame: RefCell::new(None),
        code: None,
        imports: Vec::new(),
        import_bindings: RefCell::new(Vec::new()),
        local_exports: Vec::new(),
        indirect_exports: Vec::new(),
        star_exports: Vec::new(),
        requested: Vec::new(),
        resolved: RefCell::new(Vec::new()),
        status: Cell::new(Status::Evaluated),
        namespace: RefCell::new(None),
        synthetic: Some(exports),
        error: RefCell::new(None),
        has_tla: false,
        meta: RefCell::new(None),
    })
}

/// Deferred CommonJS module imported from an ES module graph (the `synthetic` value of its
/// record until it has run).
pub struct CjsCell {
    pub path: PathBuf,
    pub names: Vec<String>,
    pub exports: RefCell<Option<Value>>,
}

fn with_cell<R>(v: &Value, f: impl FnOnce(&CjsCell) -> R) -> Option<R> {
    let o = v.as_obj()?;
    let b = o.borrow();
    match &b.kind {
        ObjKind::Host(h) => h.downcast_ref::<CjsCell>().map(f),
        _ => None,
    }
}

/// The value a synthetic export reads: a CommonJS cell yields its module.exports.
fn synthetic_value(v: &Value) -> Value {
    with_cell(v, |c| c.exports.borrow().clone().unwrap_or(Value::Undefined)).unwrap_or_else(|| v.clone())
}

/// Path of a CommonJS cell that has not run yet.
fn pending_cjs(m: &ModuleRecord) -> Option<PathBuf> {
    m.synthetic.as_ref().and_then(|v| with_cell(v, |c| if c.exports.borrow().is_none() { Some(c.path.clone()) } else { None })).flatten()
}

pub struct ModuleSyntaxError {
    pub msg: String,
    pub line: u32,
}

thread_local! {
    pub static MODULE_SYNTAX: RefCell<Option<ModuleSyntaxError>> = RefCell::new(None);
}

pub fn compile_module_record(vm: &mut Vm, path: &str, src: &str) -> JsResult<Rc<ModuleRecord>> {
    let prog = match crate::parser::parse(src, true) {
        Ok(p) => p,
        Err(e) => {
            MODULE_SYNTAX.with(|m| *m.borrow_mut() = Some(ModuleSyntaxError { msg: e.msg.clone(), line: e.line }));
            return vm.throw_syntax(e.msg);
        }
    };
    let mut res = crate::resolver::Resolver::new();
    if let Err(e) = res.resolve_program(&prog, crate::resolver::ScopeKind::Module) {
        MODULE_SYNTAX.with(|m| *m.borrow_mut() = Some(ModuleSyntaxError { msg: e.msg.clone(), line: e.line }));
        return vm.throw_syntax(e.msg);
    }
    let env_names = crate::compiler::Compiler::module_env_names(&res, &prog);
    let comp = crate::compiler::Compiler::new(&res, prog.source.clone(), true);
    let (code, _import_names) = match comp.compile_module(&prog) {
        Ok(c) => c,
        Err(e) => {
            MODULE_SYNTAX.with(|m| *m.borrow_mut() = Some(ModuleSyntaxError { msg: e.msg.clone(), line: e.line }));
            return vm.throw_syntax(e.msg);
        }
    };
    let mut imports = Vec::new();
    let mut local_exports = Vec::new();
    let mut indirect_exports = Vec::new();
    let mut star_exports = Vec::new();
    let mut requested: Vec<Rc<str>> = Vec::new();
    let mut add_req = |s: &Rc<str>, requested: &mut Vec<Rc<str>>| {
        if !requested.contains(s) {
            requested.push(s.clone());
        }
    };
    for s in &prog.body {
        match s {
            Stmt::Import(imp) => {
                add_req(&imp.specifier, &mut requested);
                if imp.default.is_some() {
                    imports.push(ImportEntry { specifier: imp.specifier.clone(), name: Rc::from("default") });
                }
                if imp.namespace.is_some() {
                    imports.push(ImportEntry { specifier: imp.specifier.clone(), name: Rc::from("*") });
                }
                for (n, _) in &imp.named {
                    imports.push(ImportEntry { specifier: imp.specifier.clone(), name: n.clone() });
                }
            }
            Stmt::Export(e) => match &**e {
                ExportDecl::Named(names) => {
                    for (local, exported) in names {
                        // re-export of an imported binding?
                        let imported = prog.body.iter().find_map(|st| {
                            if let Stmt::Import(imp) = st {
                                if imp.default.as_ref().map_or(false, |d| d.name == *local) {
                                    return Some((imp.specifier.clone(), Rc::from("default")));
                                }
                                if imp.namespace.as_ref().map_or(false, |d| d.name == *local) {
                                    return Some((imp.specifier.clone(), Rc::from("*")));
                                }
                                for (n, l) in &imp.named {
                                    if l.name == *local {
                                        return Some((imp.specifier.clone(), n.clone()));
                                    }
                                }
                            }
                            None
                        });
                        match imported {
                            Some((spec, name)) => indirect_exports.push((exported.clone(), spec, name)),
                            None => local_exports.push((exported.clone(), local.clone())),
                        }
                    }
                }
                ExportDecl::From { specifier, names } => {
                    add_req(specifier, &mut requested);
                    for (imported, exported) in names {
                        indirect_exports.push((exported.clone(), specifier.clone(), imported.clone()));
                    }
                }
                ExportDecl::All { specifier } => {
                    add_req(specifier, &mut requested);
                    star_exports.push(specifier.clone());
                }
                ExportDecl::AllAs { specifier, name } => {
                    add_req(specifier, &mut requested);
                    indirect_exports.push((name.clone(), specifier.clone(), Rc::from("*")));
                }
                ExportDecl::Decl(st) => {
                    let mut names = Vec::new();
                    match st {
                        Stmt::Var(d) => {
                            for decl in &d.decls {
                                crate::resolver::pattern_names(&decl.target, &mut names);
                            }
                        }
                        Stmt::Function(f) => {
                            if let Some(n) = &f.name {
                                names.push((n.name.clone(), 0));
                            }
                        }
                        Stmt::Class(c) => {
                            if let Some(n) = &c.name {
                                names.push((n.name.clone(), 0));
                            }
                        }
                        _ => {}
                    }
                    for (n, _) in names {
                        local_exports.push((n.clone(), n));
                    }
                }
                ExportDecl::DefaultExpr(_) => local_exports.push((Rc::from("default"), Rc::from("*default*"))),
                ExportDecl::DefaultFunc(f) => {
                    let n: Rc<str> = f.name.as_ref().map(|n| n.name.clone()).unwrap_or_else(|| Rc::from("*default*"));
                    local_exports.push((Rc::from("default"), n));
                }
                ExportDecl::DefaultClass(c) => {
                    let n: Rc<str> = c.name.as_ref().map(|n| n.name.clone()).unwrap_or_else(|| Rc::from("*default*"));
                    local_exports.push((Rc::from("default"), n));
                }
            },
            _ => {}
        }
    }
    let dir = Path::new(path).parent().map(|d| d.to_string_lossy().to_string()).unwrap_or_else(|| ".".into());
    let n_imports = imports.len();
    Ok(Rc::new(ModuleRecord {
        path: path.to_string(),
        url: file_url(path),
        dir,
        env: RefCell::new(None),
        env_names,
        frame: RefCell::new(None),
        code: Some(code),
        imports,
        import_bindings: RefCell::new(vec![None; n_imports]),
        local_exports,
        indirect_exports,
        star_exports,
        requested,
        resolved: RefCell::new(Vec::new()),
        status: Cell::new(Status::New),
        namespace: RefCell::new(None),
        synthetic: None,
        error: RefCell::new(None),
        has_tla: prog.has_top_level_await,
        meta: RefCell::new(None),
    }))
}

fn get_requested(vm: &mut Vm, m: &Rc<ModuleRecord>, spec: &str) -> JsResult<Rc<ModuleRecord>> {
    if let Some((_, r)) = m.resolved.borrow().iter().find(|(s, _)| &**s == spec) {
        return Ok(r.clone());
    }
    let r = match resolve_spec(spec, &m.dir) {
        Some(crate::runtime::node::Resolved::Builtin(n)) => {
            let key = format!("node:{}", n);
            if let Some(rec) = vm.host.esm_cache.get(&key) {
                rec.clone()
            } else {
                let exports = crate::runtime::node::builtin_module(vm, &n)?.unwrap_or(Value::Undefined);
                let rec = synthetic_record(&key, exports);
                vm.host.esm_cache.insert(key, rec.clone());
                rec
            }
        }
        Some(crate::runtime::node::Resolved::File(p)) => load_module(vm, &p)?,
        None => {
            let from = m.path.clone();
            return Err(not_found(vm, spec, &from));
        }
    };
    m.resolved.borrow_mut().push((Rc::from(spec), r.clone()));
    Ok(r)
}

/// Instantiate: load dependencies, run module prologues (hoisting), resolve imports.
pub fn link(vm: &mut Vm, m: &Rc<ModuleRecord>) -> JsResult<()> {
    if m.status.get() != Status::New {
        return Ok(());
    }
    m.status.set(Status::Linking);
    for spec in m.requested.clone() {
        let dep = get_requested(vm, m, &spec)?;
        link(vm, &dep)?;
    }
    // run prologue (creates env, hoists functions)
    if let Some(code) = &m.code {
        let mut frame = Frame::new(code.clone(), None, Value::Undefined, None, Value::Undefined, Vec::new(), None);
        frame.module = Some(m.clone());
        frame.is_coroutine = true;
        match vm.run_frame(&mut frame)? {
            Completion::GenStart => {}
            _ => {}
        }
        *m.env.borrow_mut() = frame.env.clone();
        *m.frame.borrow_mut() = Some(Box::new(frame));
    }
    // resolve import bindings
    for (i, imp) in m.imports.iter().enumerate() {
        let dep = get_requested(vm, m, &imp.specifier)?;
        let b = if &*imp.name == "*" {
            Binding::Namespace(dep.clone())
        } else {
            match resolve_export(vm, &dep, &imp.name, &mut Vec::new())? {
                Some(b) => b,
                None => {
                    let shown = if dep.synthetic.is_some() { dep.path.clone() } else { dep.path.clone() };
                    return vm.throw_syntax(format!("the requested module '{}' does not provide an export named '{}'", shown, imp.name));
                }
            }
        };
        m.import_bindings.borrow_mut()[i] = Some(b);
    }
    m.status.set(Status::Linked);
    Ok(())
}

pub fn resolve_export(vm: &mut Vm, m: &Rc<ModuleRecord>, name: &str, visited: &mut Vec<(String, String)>) -> JsResult<Option<Binding>> {
    let key = (m.path.clone(), name.to_string());
    if visited.contains(&key) {
        return Ok(None);
    }
    visited.push(key);
    if let Some(exp) = &m.synthetic {
        if name == "default" {
            return Ok(Some(Binding::SyntheticDefault(exp.clone())));
        }
        // JSON modules only have a default export
        if m.path.ends_with(".json") {
            return Ok(None);
        }
        if let Some(found) = with_cell(exp, |c| c.names.iter().any(|n| n == name)) {
            return Ok(if found { Some(Binding::Synthetic(exp.clone(), PropKey::from_str(name))) } else { None });
        }
        if let Value::Obj(o) = exp {
            let k = PropKey::from_str(name);
            if vm.has_property(o, &k)? {
                return Ok(Some(Binding::Synthetic(exp.clone(), k)));
            }
        }
        return Ok(None);
    }
    for (exported, local) in &m.local_exports {
        if &**exported == name {
            let env = m.env.borrow().clone();
            if let Some(env) = env {
                if let Some(idx) = env.0.info.as_ref().and_then(|i| i.find(&JsStr::from_str(local))) {
                    return Ok(Some(Binding::Slot(env, idx as u32)));
                }
            }
            return Ok(None);
        }
    }
    for (exported, spec, imported) in &m.indirect_exports {
        if &**exported == name {
            let dep = get_requested(vm, m, spec)?;
            if &**imported == "*" {
                return Ok(Some(Binding::Namespace(dep)));
            }
            return resolve_export(vm, &dep, imported, visited);
        }
    }
    if name == "default" {
        return Ok(None);
    }
    for spec in &m.star_exports {
        let dep = get_requested(vm, m, spec)?;
        if let Some(b) = resolve_export(vm, &dep, name, visited)? {
            return Ok(Some(b));
        }
    }
    Ok(None)
}

pub fn exported_names(vm: &mut Vm, m: &Rc<ModuleRecord>, visited: &mut Vec<String>) -> Vec<String> {
    if visited.contains(&m.path) {
        return Vec::new();
    }
    visited.push(m.path.clone());
    let mut out = Vec::new();
    if let Some(exp) = &m.synthetic {
        out.push("default".to_string());
        if m.path.ends_with(".json") {
            return out;
        }
        if let Some(names) = with_cell(exp, |c| c.names.clone()) {
            out.extend(names);
            return out;
        }
        if let Value::Obj(o) = exp {
            // (a function's own length/name/prototype are not exports)
            let callable = o.is_callable();
            if let Ok(keys) = vm.own_property_keys(o) {
                for k in keys {
                    let enumerable = matches!(o.borrow().props.get(&k), Some(p) if p.enumerable());
                    if let PropKey::Str(s) = k {
                        let s = s.to_rust_string();
                        let intrinsic = callable && !enumerable && matches!(s.as_str(), "length" | "name" | "prototype");
                        if !intrinsic && s != "default" && !out.contains(&s) {
                            out.push(s);
                        }
                    }
                }
            }
        }
        return out;
    }
    for (e, _) in &m.local_exports {
        out.push(e.to_string());
    }
    for (e, _, _) in &m.indirect_exports {
        out.push(e.to_string());
    }
    for spec in m.star_exports.clone() {
        if let Ok(dep) = get_requested(vm, m, &spec) {
            for n in exported_names(vm, &dep, visited) {
                if n != "default" && !out.contains(&n) {
                    out.push(n);
                }
            }
        }
    }
    out
}

fn binding_value(vm: &mut Vm, b: &Binding, name: &str) -> JsResult<Value> {
    match b {
        Binding::Slot(env, i) => {
            let v = env.0.vars.borrow()[*i as usize].clone();
            if v.is_empty() {
                return vm.throw_ref(format!("cannot access '{}' before initialization", name));
            }
            Ok(v)
        }
        Binding::Namespace(m) => Ok(Value::Obj(get_namespace(vm, m))),
        Binding::Synthetic(exp, k) => vm.get_prop_of(&synthetic_value(exp), k),
        Binding::SyntheticDefault(exp) => Ok(synthetic_value(exp)),
    }
}

pub fn get_import(vm: &mut Vm, frame: &Frame, i: u32) -> JsResult<Value> {
    let m = match &frame.module {
        Some(m) => m.clone(),
        None => return vm.throw_ref("import outside module"),
    };
    let b = m.import_bindings.borrow().get(i as usize).cloned().flatten();
    match b {
        Some(b) => {
            let name = m.imports[i as usize].name.to_string();
            binding_value(vm, &b, &name)
        }
        None => vm.throw_ref("unresolved import"),
    }
}

pub fn get_namespace(vm: &mut Vm, m: &Rc<ModuleRecord>) -> Obj {
    if let Some(ns) = m.namespace.borrow().as_ref() {
        return ns.clone();
    }
    let ns = Obj::with_class(None, ObjKind::Namespace(m.clone()), "Module");
    ns.borrow_mut().extensible = false;
    ns.borrow_mut().props.insert(PropKey::Sym(vm.intr.sym_to_string_tag.clone()), Prop::Data { value: Value::str("Module"), flags: 0 });
    *m.namespace.borrow_mut() = Some(ns.clone());
    ns
}

fn ns_module(o: &Obj) -> Option<Rc<ModuleRecord>> {
    match &o.borrow().kind {
        ObjKind::Namespace(m) => Some(m.clone()),
        _ => None,
    }
}

fn sorted_names(vm: &mut Vm, m: &Rc<ModuleRecord>) -> Vec<String> {
    let mut names = exported_names(vm, m, &mut Vec::new());
    names.sort_by(|a, b| {
        let au: Vec<u16> = a.encode_utf16().collect();
        let bu: Vec<u16> = b.encode_utf16().collect();
        au.cmp(&bu)
    });
    names.dedup();
    names
}

pub fn namespace_get(vm: &mut Vm, o: &Obj, key: &PropKey) -> JsResult<Value> {
    let m = match ns_module(o) {
        Some(m) => m,
        None => return Ok(Value::Undefined),
    };
    match key {
        PropKey::Sym(_) => Ok(o.borrow().props.get(key).map(|p| match p {
            Prop::Data { value, .. } => value.clone(),
            _ => Value::Undefined,
        }).unwrap_or(Value::Undefined)),
        PropKey::Str(s) => {
            let name = s.to_rust_string();
            match resolve_export(vm, &m, &name, &mut Vec::new())? {
                Some(b) => binding_value(vm, &b, &name),
                None => Ok(Value::Undefined),
            }
        }
    }
}

pub fn namespace_get_own(vm: &mut Vm, o: &Obj, key: &PropKey) -> JsResult<Option<PropDesc>> {
    let m = match ns_module(o) {
        Some(m) => m,
        None => return Ok(None),
    };
    match key {
        PropKey::Sym(_) => Ok(o.borrow().props.get(key).map(PropDesc::from_prop)),
        PropKey::Str(s) => {
            let name = s.to_rust_string();
            if !exported_names(vm, &m, &mut Vec::new()).contains(&name) {
                return Ok(None);
            }
            let v = namespace_get(vm, o, key)?;
            Ok(Some(PropDesc { value: Some(v), writable: Some(true), enumerable: Some(true), configurable: Some(false), get: None, set: None }))
        }
    }
}

pub fn namespace_keys(vm: &mut Vm, o: &Obj) -> Vec<PropKey> {
    let m = match ns_module(o) {
        Some(m) => m,
        None => return Vec::new(),
    };
    let mut out: Vec<PropKey> = sorted_names(vm, &m).into_iter().map(|n| PropKey::from_str(&n)).collect();
    out.push(PropKey::Sym(vm.intr.sym_to_string_tag.clone()));
    out
}

pub fn namespace_define(vm: &mut Vm, o: &Obj, key: &PropKey, desc: &PropDesc) -> JsResult<bool> {
    let cur = namespace_get_own(vm, o, key)?;
    match cur {
        None => Ok(false),
        Some(c) => {
            if desc.configurable == Some(true) || desc.enumerable == Some(false) || desc.is_accessor() || desc.writable == Some(false) {
                return Ok(false);
            }
            if let Some(v) = &desc.value {
                return Ok(Value::same_value(v, c.value.as_ref().unwrap_or(&Value::Undefined)));
            }
            Ok(true)
        }
    }
}

pub fn namespace_delete(vm: &mut Vm, o: &Obj, key: &PropKey) -> JsResult<bool> {
    Ok(namespace_get_own(vm, o, key)?.is_none())
}

pub fn import_meta(_vm: &mut Vm, frame: &Frame) -> JsResult<Value> {
    let m = match &frame.module {
        Some(m) => m.clone(),
        None => return Ok(Value::Undefined),
    };
    if let Some(o) = m.meta.borrow().as_ref() {
        return Ok(Value::Obj(o.clone()));
    }
    let o = Obj::new(None, ObjKind::Ordinary);
    o.set_prop(PropKey::from_str("url"), Value::str(&m.url), WEC);
    o.set_prop(PropKey::from_str("filename"), Value::str(&m.path), WEC);
    o.set_prop(PropKey::from_str("dirname"), Value::str(&m.dir), WEC);
    // (the original runtime has no import.meta.resolve / import.meta.main)
    let _ = meta_resolve;
    *m.meta.borrow_mut() = Some(o.clone());
    Ok(Value::Obj(o))
}

fn meta_resolve(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let spec = vm.to_string(&a.arg(0))?.to_rust_string();
    let dir = match a.slot(0) {
        Value::Str(s) => s.to_rust_string(),
        _ => ".".into(),
    };
    match crate::runtime::node::resolve_esm(&spec, &dir) {
        Some(crate::runtime::node::Resolved::Builtin(n)) => Ok(Value::str(&format!("node:{}", n))),
        Some(crate::runtime::node::Resolved::File(p)) => Ok(Value::str(&file_url(&p.to_string_lossy()))),
        None => Ok(Value::str(&file_url(&Path::new(&dir).join(&spec).to_string_lossy()))),
    }
}

impl crate::runtime::Host {
    pub fn main_path(&self) -> String {
        self.main_esm_path.clone()
    }
}

// ---------------- evaluation ----------------

/// Collect modules in evaluation (post-)order.
fn eval_order(m: &Rc<ModuleRecord>, out: &mut Vec<Rc<ModuleRecord>>, visiting: &mut Vec<String>) {
    if out.iter().any(|x| Rc::ptr_eq(x, m)) || visiting.contains(&m.path) {
        return;
    }
    visiting.push(m.path.clone());
    let deps: Vec<Rc<ModuleRecord>> = m.resolved.borrow().iter().map(|(_, r)| r.clone()).collect();
    // keep requested order
    let mut ordered = Vec::new();
    for spec in &m.requested {
        if let Some(d) = deps.iter().find(|_| true).and_then(|_| m.resolved.borrow().iter().find(|(s, _)| s == spec).map(|(_, r)| r.clone())) {
            ordered.push(d);
        }
    }
    for d in ordered {
        eval_order(&d, out, visiting);
    }
    if m.synthetic.is_none() || pending_cjs(m).is_some() {
        out.push(m.clone());
    }
}

struct Evaluator {
    queue: Vec<Rc<ModuleRecord>>,
    index: Cell<usize>,
    capability: Capability,
}

/// Evaluate a linked module graph; returns a promise resolved when done.
pub fn evaluate(vm: &mut Vm, m: &Rc<ModuleRecord>) -> Value {
    let cap = vm.new_promise_capability_intrinsic();
    let mut order = Vec::new();
    eval_order(m, &mut order, &mut Vec::new());
    let order: Vec<Rc<ModuleRecord>> = order.into_iter().filter(|x| x.status.get() == Status::Linked).collect();
    for x in &order {
        x.status.set(Status::Evaluating);
    }
    let ev = Value::Obj(Obj::new(None, ObjKind::Host(Box::new(Evaluator { queue: order, index: Cell::new(0), capability: cap.clone() }))));
    step(vm, &ev, None);
    cap.promise
}

fn with_eval<R>(ev: &Value, f: impl FnOnce(&Evaluator) -> R) -> R {
    let o = ev.as_obj().unwrap();
    let b = o.borrow();
    match &b.kind {
        ObjKind::Host(h) => f(h.downcast_ref::<Evaluator>().unwrap()),
        _ => unreachable!(),
    }
}

/// Run modules until done or an await suspends. `resume` carries a value/throw for the current module.
fn step(vm: &mut Vm, ev: &Value, mut resume: Option<(bool, Value)>) {
    loop {
        let (m, cap) = with_eval(ev, |e| (e.queue.get(e.index.get()).cloned(), e.capability.clone()));
        let m = match m {
            Some(m) => m,
            None => {
                let _ = vm.call(&cap.resolve, Value::Undefined, &[Value::Undefined]);
                return;
            }
        };
        let frame = m.frame.borrow_mut().take();
        let mut frame = match frame {
            Some(f) => f,
            None => {
                if let Some(path) = pending_cjs(&m) {
                    match crate::runtime::node::load_cjs(vm, &path, None) {
                        Ok(exports) => {
                            if let Some(v) = &m.synthetic {
                                with_cell(v, |c| *c.exports.borrow_mut() = Some(exports));
                            }
                            m.status.set(Status::Evaluated);
                        }
                        Err(e) => {
                            fail_evaluation(vm, ev, &m, e);
                            return;
                        }
                    }
                }
                with_eval(ev, |e| e.index.set(e.index.get() + 1));
                continue;
            }
        };
        if let Some((is_throw, v)) = resume.take() {
            if is_throw {
                frame.pending_throw = Some(v);
            } else {
                frame.stack.push(v);
            }
        }
        let r = vm.run_frame(&mut frame);
        match r {
            Ok(Completion::Await(v)) => {
                *m.frame.borrow_mut() = Some(frame);
                let p = match crate::builtins::promise::promise_resolve_intrinsic(vm, v) {
                    Ok(p) => p,
                    Err(e) => {
                        resume = Some((true, e));
                        continue;
                    }
                };
                crate::builtins::promise::perform_then_internal(vm, &p, Handler::Native(on_fulfilled, ev.clone()), Handler::Native(on_rejected, ev.clone()), None);
                return;
            }
            Ok(_) => {
                m.status.set(Status::Evaluated);
                with_eval(ev, |e| e.index.set(e.index.get() + 1));
            }
            Err(e) => {
                fail_evaluation(vm, ev, &m, e);
                return;
            }
        }
    }
}

/// `m` threw while the graph evaluated: the remaining modules are errored and the evaluation
/// promise rejects. Every module that (transitively) imports `m`, `m` included, has its own
/// evaluation promise rejected without a handler, except the graph's root whose rejection is
/// the evaluation promise itself.
fn fail_evaluation(vm: &mut Vm, ev: &Value, m: &Rc<ModuleRecord>, e: Value) {
    let cap = with_eval(ev, |x| x.capability.clone());
    m.status.set(Status::Errored);
    *m.error.borrow_mut() = Some(e.clone());
    let rest: Vec<Rc<ModuleRecord>> = with_eval(ev, |x| x.queue[x.index.get()..].to_vec());
    for r in rest {
        r.status.set(Status::Errored);
        *r.error.borrow_mut() = Some(e.clone());
    }
    let queue: Vec<Rc<ModuleRecord>> = with_eval(ev, |x| x.queue.clone());
    with_eval(ev, |x| x.index.set(x.queue.len()));
    if let Some(root) = queue.last() {
        for q in &queue {
            if Rc::ptr_eq(q, root) || !depends_on(q, m, &mut Vec::new()) {
                continue;
            }
            let c = vm.new_promise_capability_intrinsic();
            let _ = vm.call(&c.reject, Value::Undefined, &[e.clone()]);
        }
    }
    let _ = vm.call(&cap.reject, Value::Undefined, &[e]);
}

fn depends_on(q: &Rc<ModuleRecord>, m: &Rc<ModuleRecord>, seen: &mut Vec<String>) -> bool {
    if Rc::ptr_eq(q, m) {
        return true;
    }
    if seen.contains(&q.path) {
        return false;
    }
    seen.push(q.path.clone());
    let deps: Vec<Rc<ModuleRecord>> = q.resolved.borrow().iter().map(|(_, r)| r.clone()).collect();
    deps.iter().any(|d| depends_on(d, m, seen))
}

fn on_fulfilled(vm: &mut Vm, v: Value, ev: &Value) -> JsResult<Value> {
    step(vm, ev, Some((false, v)));
    Ok(Value::Undefined)
}

fn on_rejected(vm: &mut Vm, e: Value, ev: &Value) -> JsResult<Value> {
    step(vm, ev, Some((true, e)));
    Ok(Value::Undefined)
}

/// Load, link and evaluate a module file; returns the evaluation promise.
pub fn run_module_file(vm: &mut Vm, path: &Path, src: Option<&str>) -> JsResult<(Rc<ModuleRecord>, Value)> {
    let key = path.to_string_lossy().to_string();
    let m = match src {
        Some(s) => {
            let rec = compile_module_record(vm, &key, s)?;
            vm.host.esm_cache.insert(key.clone(), rec.clone());
            rec
        }
        None => load_module(vm, path)?,
    };
    link(vm, &m)?;
    let p = evaluate(vm, &m);
    Ok((m, p))
}

/// Synchronous load used by require() of an ES module
#[allow(dead_code)]
pub fn load_esm_sync(vm: &mut Vm, path: &Path) -> JsResult<Value> {
    let (m, p) = run_module_file(vm, path, None)?;
    vm.run_microtasks();
    if let Value::Obj(po) = &p {
        if let ObjKind::Promise(pd) = &po.borrow().kind {
            if let PromiseState::Rejected(e) = &pd.state {
                return Err(e.clone());
            }
        }
    }
    Ok(Value::Obj(get_namespace(vm, &m)))
}

pub fn dynamic_import(vm: &mut Vm, frame: &Frame, spec: Value) -> Value {
    let cap = vm.new_promise_capability_intrinsic();
    let r = (|| -> JsResult<Value> {
        let s = vm.to_string(&spec)?.to_rust_string();
        let (dir, from) = match &frame.module {
            Some(m) => (m.dir.clone(), m.url.clone()),
            None => {
                let cwd = std::env::current_dir().map(|p| p.to_string_lossy().to_string()).unwrap_or_default();
                let from = vm.host.main_esm_path.clone();
                (cwd, if from.is_empty() { "main".to_string() } else { file_url(&from) })
            }
        };
        let rec = match resolve_spec(&s, &dir) {
            Some(crate::runtime::node::Resolved::Builtin(n)) => {
                let key = format!("node:{}", n);
                match vm.host.esm_cache.get(&key) {
                    Some(r) => r.clone(),
                    None => {
                        let exports = crate::runtime::node::builtin_module(vm, &n)?.unwrap_or(Value::Undefined);
                        let rec = synthetic_record(&key, exports);
                        vm.host.esm_cache.insert(key, rec.clone());
                        rec
                    }
                }
            }
            Some(crate::runtime::node::Resolved::File(p)) => load_module(vm, &p)?,
            None => return Err(vm.make_error("TypeError", &format!("module not found: {} (imported from {})", s, from))),
        };
        link(vm, &rec)?;
        let ev = if rec.status.get() == Status::Errored {
            let e = rec.error.borrow().clone().unwrap_or(Value::Undefined);
            return Err(e);
        } else {
            evaluate(vm, &rec)
        };
        let ns = get_namespace(vm, &rec);
        let f = vm.native_closure("", 0, |_vm, a| Ok(a.slot(0)), vec![Value::Obj(ns)]);
        let evp = ev.as_obj().unwrap().clone();
        crate::builtins::promise::promise_then(vm, &evp, Value::Obj(f), Value::Undefined)
    })();
    match r {
        Ok(p) => {
            let _ = vm.call(&cap.resolve, Value::Undefined, &[p]);
        }
        Err(e) => {
            let _ = vm.call(&cap.reject, Value::Undefined, &[e]);
        }
    }
    cap.promise
}

pub fn _unused(_: PathBuf) {}
