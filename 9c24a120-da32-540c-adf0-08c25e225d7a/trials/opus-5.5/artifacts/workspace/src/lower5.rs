// Lowering: declarations and assembling the Python module.

use crate::ast::*;
use crate::infer::*;
use crate::lower::*;
use crate::lower4::fun_params;
use crate::py::*;
use crate::runtime::HELPERS;
use crate::types::*;
use std::collections::{BTreeSet, HashMap};

pub struct Parts {
    pub prelude: String,
    pub types: String,
    pub codecs: String,
}

pub fn field_annot(t: &Ty) -> &'static str {
    match t {
        Ty::Num(Kind::Int, _) => "int",
        Ty::Num(Kind::Float, _) => "float",
        Ty::Con(n, _) => match n.as_str() {
            "string" => "str",
            "bool" => "bool",
            "List" => "list",
            "Map" => "dict",
            "Set" => "set",
            _ => "object",
        },
        Ty::Tuple(_) => "tuple",
        _ => "object",
    }
}

pub fn adt_class(name: &str, annots: &[&str], ordered: Option<usize>, singleton: bool) -> String {
    let mut s = String::new();
    if ordered.is_some() {
        s.push_str("@total_ordering\n");
    }
    s.push_str("@dataclass(frozen=True, slots=True, repr=False)\n");
    s.push_str(&format!("class {}:\n", name));
    for (i, a) in annots.iter().enumerate() {
        s.push_str(&format!("    _{}: {}\n", i, a));
    }
    s.push_str("    def __repr__(self):\n");
    if annots.is_empty() {
        s.push_str(&format!("        return \"{}\"\n", name));
    } else {
        let parts: Vec<String> = (0..annots.len()).map(|i| format!("{{self._{}!r}}", i)).collect();
        s.push_str(&format!("        return f\"{}({})\"\n", name, parts.join(", ")));
    }
    if let Some(idx) = ordered {
        s.push_str("    def __lt__(self, other):\n");
        s.push_str("        return self._pf_order_key() < other._pf_order_key()\n");
        s.push_str("    def _pf_order_key(self):\n");
        if annots.is_empty() {
            s.push_str(&format!("        return ({},)\n", idx));
        } else {
            let parts: Vec<String> = (0..annots.len()).map(|i| format!("self._{}", i)).collect();
            s.push_str(&format!("        return ({}, {})\n", idx, parts.join(", ")));
        }
    }
    if singleton {
        s.push_str(&format!("_{} = {}()\n", name, name));
    }
    s
}

pub fn record_class(name: &str, fields: &[(String, &str)], ordered: bool) -> String {
    let mut s = String::new();
    if ordered {
        s.push_str("@dataclass(frozen=True, slots=True, order=True)\n");
    } else {
        s.push_str("@dataclass(frozen=True, slots=True)\n");
    }
    s.push_str(&format!("class {}:\n", name));
    for (f, a) in fields {
        s.push_str(&format!("    {}: {}\n", mangle(f), a));
    }
    s
}

pub fn runtime_module_native() -> String {
    use crate::native::adt_class_native_with;
    let any = vec!["Any".to_string()];
    let mut s = String::from("from dataclasses import dataclass\nfrom typing import Any\nimport contextvars\n");
    s.push_str(&adt_class_native_with("Ok", &any, Some(0), false, false));
    s.push_str(&adt_class_native_with("Error", &any, Some(1), false, false));
    s.push_str(&adt_class_native_with("Some", &any, Some(1), false, false));
    s.push_str(&adt_class_native_with("None_", &[], Some(0), true, false));
    s.push_str(EXCEPTION_CLASS);
    s.push_str("_pf_scope = contextvars.ContextVar(\"_pf_scope\")\n");
    s
}

pub fn runtime_module() -> String {
    let mut s = String::from("from dataclasses import dataclass\nfrom functools import total_ordering\nimport contextvars\n");
    s.push_str(&adt_class("Ok", &["object"], Some(0), false));
    s.push_str(&adt_class("Error", &["object"], Some(1), false));
    s.push_str(&adt_class("Some", &["object"], Some(1), false));
    s.push_str(&adt_class("None_", &[], Some(0), true));
    s.push_str(EXCEPTION_CLASS);
    s.push_str("_pf_scope = contextvars.ContextVar(\"_pf_scope\")\n");
    s
}

pub const EXCEPTION_CLASS: &str = "@dataclass(frozen=True, slots=True, repr=False)\nclass _Exception:\n    errorKind: str\n    errorMessage: str\n    def __repr__(self):\n        return f\"_Exception({self.errorKind!r}, {self.errorMessage!r})\"\n";

impl<'a> Lowerer<'a> {
    pub fn bind_externs(&mut self, decls: &[Decl]) {
        for d in decls {
            match d {
                Decl::ExternImport(p, alias, _) => self.extern_imports.push((p.clone(), alias.clone())),
                _ => {}
            }
        }
        // (a name a top-level `let` binds anywhere is that binding's, even
        // where the extern is meant: it is called like any value)
        let mut rebound = std::collections::HashSet::new();
        for d in decls {
            if let Decl::Let(l) = d {
                let mut names = Vec::new();
                crate::check_decl::pat_names(&l.pat, &mut names);
                rebound.extend(names);
            }
        }
        for d in decls {
            if let Decl::Extern(e) = d {
                if rebound.contains(&e.name) {
                    self.scopes[0].insert(e.name.clone(), Bind { py: mangle(&e.name), kind: BKind::Value, mutable: false, depth: 0 });
                    continue;
                }
                let t = self.extern_ty(&e.name);
                let (params, _) = fun_params(&t);
                let arity = params.len();
                self.scopes[0].insert(e.name.clone(), Bind { py: e.name.clone(), kind: BKind::Extern(arity), mutable: false, depth: 0 });
                self.externs.insert(e.name.clone(), ExternInfo { decl: e.clone(), arity, thunks: vec![], async_result: false });
            }
        }
    }

    pub fn lower_program(&mut self, decls: &[Decl]) -> Vec<PS> {
        self.bind_externs(decls);
        self.has_code = decls.iter().any(|d| matches!(d, Decl::Let(_) | Decl::Expr(_) | Decl::Module(..) | Decl::Assign(..)));
        self.collect_top_binds(decls);
        self.prepare_shadowing(decls);
        let mut out = Vec::new();
        for d in decls {
            out.extend(self.lower_decl(d, None));
        }
        out
    }

    /// How many top-level `let`s bind each name.
    pub fn collect_top_binds(&mut self, decls: &[Decl]) {
        for d in decls {
            if let Decl::Let(l) = d {
                let mut names = Vec::new();
                crate::check_decl::pat_names(&l.pat, &mut names);
                for n in names {
                    *self.top_binds.entry(n).or_insert(0) += 1;
                }
            }
        }
    }

    pub fn lower_decl(&mut self, d: &Decl, module: Option<&str>) -> Vec<PS> {
        match d {
            Decl::Let(l) => self.lower_top_let(l, module),
            Decl::Expr(e) => self.top_expr_stmt(e),
            Decl::Assign(n, _, v, _) => {
                let saved = std::mem::take(&mut self.pre);
                let val = self.expr(v);
                let mut out = std::mem::replace(&mut self.pre, saved);
                let py = self.assign_target(n);
                out.push(PS::Assign(name(&py), val));
                out
            }
            Decl::Extern(e) if self.project => {
                let v = self.extern_value(&e.name);
                vec![PS::Assign(name(&mangle(&e.name)), v)]
            }
            Decl::Module(m, _, ds) => {
                let mut out = Vec::new();
                // members see each other unqualified
                self.scopes.push(HashMap::new());
                for d in ds {
                    out.extend(self.lower_decl(d, Some(m)));
                }
                let inner = self.scopes.pop().unwrap();
                for (k, b) in inner {
                    self.scopes[0].insert(format!("{}.{}", m, k), b);
                }
                self.user_modules.insert(m.clone());
                out
            }
            _ => vec![],
        }
    }

    fn top_expr_stmt(&mut self, e: &Expr) -> Vec<PS> {
        match &e.kind {
            ExprKind::Match(s, arms) => {
                let (mut out, t) = self.match_value(s, arms, e.span);
                out.push(PS::Expr(name(&t)));
                out
            }
            _ => {
                let saved = std::mem::take(&mut self.pre);
                let v = self.expr(e);
                let mut out = std::mem::replace(&mut self.pre, saved);
                // a bare `()` does nothing
                if v != PE::NoneV || !out.is_empty() {
                    out.push(PS::Expr(v));
                }
                out
            }
        }
    }

    /// A top-level value whose evaluation binds a top-level name (in a
    /// block or `case` of its own) runs in a function, keeping the
    /// module's variable.
    fn lifts(&self, l: &LetDecl) -> bool {
        let mut sites = Vec::new();
        crate::shadow::inner_sites(&l.value, &mut sites);
        sites.iter().any(|(n, _)| self.top_binds.contains_key(n))
    }

    fn py_name_for(&self, n: &str, module: Option<&str>) -> String {
        match module {
            Some(m) => format!("{}_{}", m, n),
            None => mangle(n),
        }
    }

    pub fn lower_top_let(&mut self, l: &LetDecl, module: Option<&str>) -> Vec<PS> {
        if let Some(cases) = &l.active {
            let names: Vec<String> = cases.iter().filter(|c| *c != "_").cloned().collect();
            let fname = crate::lower3::ap_name(&names);
            if let PatKind::Var(tag) = &l.pat.kind {
                self.scopes[0].insert(tag.clone(), Bind { py: fname.clone(), kind: BKind::Fn(l.params.len()), mutable: false, depth: 0 });
            }
            self.active_order.push(names.clone());
            let d = self.def_stmt(&fname, &l.params, &l.value, None);
            return vec![d];
        }
        if !l.params.is_empty() {
            if let PatKind::Var(n) = &l.pat.kind {
                let py = self.py_name_for(n, module);
                let depth = self.depth();
                self.scopes.last_mut().unwrap().insert(n.clone(), Bind { py: py.clone(), kind: BKind::Fn(l.params.len()), mutable: false, depth });
                let saved = std::mem::take(&mut self.pre);
                self.annotate_top = module.is_none();
                let d = self.def_stmt(&py, &l.params, &l.value, Some(n));
                self.annotate_top = false;
                let mut out = std::mem::replace(&mut self.pre, saved);
                out.push(d);
                return out;
            }
        }
        match &l.pat.kind {
            PatKind::Var(n) => {
                let kind = match &l.value.kind {
                    ExprKind::Lambda(ps, _) => BKind::Fn(ps.len()),
                    _ => BKind::Value,
                };
                let saved = std::mem::take(&mut self.pre);
                let mut out = Vec::new();
                let v = match &l.value.kind {
                    _ if module.is_none() && self.lifts(l) => {
                        let f = self.new_fn();
                        out.push(self.def_stmt(&f, &[], &l.value, None));
                        call_n(&f, vec![])
                    }
                    ExprKind::Block(stmts) => {
                        // a top-level block runs at module level
                        let n2 = stmts.len();
                        for s in &stmts[..n2 - 1] {
                            out.extend(self.block_stmt(s));
                        }
                        match &stmts[n2 - 1] {
                            Stmt::Expr(x) => self.expr(x),
                            other => {
                                out.extend(self.block_stmt(other));
                                PE::NoneV
                            }
                        }
                    }
                    ExprKind::Match(s, arms) => {
                        let (st, t) = self.match_value(s, arms, l.value.span);
                        out.extend(st);
                        name(&t)
                    }
                    _ => self.expr(&l.value),
                };
                let pre = std::mem::replace(&mut self.pre, saved);
                out.extend(pre);
                let py = self.py_name_for(n, module);
                let depth = self.depth();
                self.scopes.last_mut().unwrap().insert(n.clone(), Bind { py: py.clone(), kind, mutable: l.mutable, depth });
                if !l.mutable {
                    self.value_asts.insert(py.clone(), l.value.clone());
                } else {
                    self.value_asts.remove(&py);
                }
                let once = module.is_none() && self.top_binds.get(n).copied().unwrap_or(0) <= 1;
                let bt = if once { self.ck.binding_types.get(&key(l.name_span)).cloned() } else { None };
                let target = if once { self.annotated_target(&py, bt) } else { py.clone() };
                out.push(PS::Assign(name(&target), v));
                out
            }
            _ => {
                let saved = std::mem::take(&mut self.pre);
                let v = match &l.value.kind {
                    _ if module.is_none() && self.lifts(l) => {
                        let f = self.new_fn();
                        let d = self.def_stmt(&f, &[], &l.value, None);
                        self.pre.push(d);
                        call_n(&f, vec![])
                    }
                    ExprKind::Match(s, arms) => {
                        let (st, t) = self.match_value(s, arms, l.value.span);
                        self.pre.extend(st);
                        name(&t)
                    }
                    _ => self.expr(&l.value),
                };
                let mut out = std::mem::replace(&mut self.pre, saved);
                out.extend(self.destructure(&l.pat, v));
                out
            }
        }
    }

    // ---- assembly -----------------------------------------------------------

    /// The classes of the declared types and of the total active patterns'
    /// cases, in the order they are declared.
    pub fn type_classes(&mut self, decls: &[Decl]) -> String {
        let mut placed = Vec::new();
        let mut s = self.type_classes_rec(decls, &mut placed);
        for names in self.active_order.clone() {
            if !placed.contains(&names) {
                s.push_str(&self.active_case_classes(&names));
            }
        }
        s
    }

    fn active_case_classes(&mut self, names: &[String]) -> String {
        let mut s = String::new();
        if names.iter().any(|n| self.ck.active_cases.get(n).and_then(|t| self.ck.active_patterns.get(t)).map_or(true, |(_, partial)| *partial)) {
            return s;
        }
        for n in names {
            let arity = self.ck.active_ctors.get(n).map_or(0, |c| c.args.len());
            if self.native && arity > 0 {
                self.needs.any = true;
            }
            let annots: Vec<&str> = vec![if self.native { "Any" } else { "object" }; arity];
            s.push_str(&adt_class(&format!("_{}", n), &annots, None, false));
        }
        s
    }

    fn type_classes_rec(&mut self, decls: &[Decl], placed: &mut Vec<Vec<String>>) -> String {
        let mut s = String::new();
        for d in decls {
            match d {
                Decl::Type(t) => s.push_str(&self.type_decl_classes(t)),
                Decl::Module(_, _, ds) => s.push_str(&self.type_classes_rec(ds, placed)),
                Decl::Let(l) => {
                    if let Some(cases) = &l.active {
                        let names: Vec<String> = cases.iter().filter(|c| *c != "_").cloned().collect();
                        if self.active_order.contains(&names) && !placed.contains(&names) {
                            s.push_str(&self.active_case_classes(&names));
                            placed.push(names);
                        }
                    }
                }
                _ => {}
            }
        }
        s
    }

    fn type_decl_classes(&mut self, t: &TypeDecl) -> String {
        let ordered = self.needs.ordered_types.contains(&t.name) || self.all_ordered;
        if self.native {
            return self.type_decl_classes_native(t, ordered);
        }
        match &t.body {
            TypeBody::Sum(vs) => {
                let mut s = String::new();
                for (i, v) in vs.iter().enumerate() {
                    let c = self.ck.ctors.get(&v.name).cloned();
                    let annots: Vec<&str> = match &c {
                        Some(c) => c.args.iter().map(field_annot).collect(),
                        None => vec![],
                    };
                    s.push_str(&adt_class(&v.name, &annots, if ordered { Some(i) } else { None }, annots.is_empty()));
                }
                s
            }
            TypeBody::Record(_) => {
                let fs: Vec<(String, &str)> = match self.ck.types.get(&t.name) {
                    Some(TypeInfo { def: TypeDef::Record(fs), .. }) => fs.iter().map(|(f, ft)| (f.clone(), field_annot(ft))).collect(),
                    _ => vec![],
                };
                record_class(&t.name, &fs, ordered)
            }
            TypeBody::Opaque(_) => String::new(),
        }
    }

    fn type_decl_classes_native(&mut self, t: &TypeDecl, ordered: bool) -> String {
        match &t.body {
            TypeBody::Sum(vs) => {
                let mut s = String::new();
                for (i, v) in vs.iter().enumerate() {
                    let c = self.ck.ctors.get(&v.name).cloned();
                    let annots: Vec<String> = match &c {
                        Some(c) => c.args.iter().map(|a| self.native_field_ann(a)).collect(),
                        None => vec![],
                    };
                    s.push_str(&crate::native::adt_class_native_with(&v.name, &annots, if ordered { Some(i) } else { None }, annots.is_empty(), self.has_code));
                }
                // the type itself names the union of its cases
                if self.has_code && !vs.iter().any(|v| v.name == t.name) {
                    let names: Vec<&str> = vs.iter().map(|v| v.name.as_str()).collect();
                    s.push_str(&format!("{} = {}\n", t.name, names.join(" | ")));
                }
                s
            }
            TypeBody::Record(_) => {
                let fts: Vec<(String, Ty)> = match self.ck.types.get(&t.name) {
                    Some(TypeInfo { def: TypeDef::Record(fs), .. }) => fs.clone(),
                    _ => vec![],
                };
                let anns: Vec<(String, String)> = fts.iter().map(|(f, ft)| (f.clone(), self.native_field_ann(ft))).collect();
                let fs: Vec<(String, &str)> = anns.iter().map(|(f, a)| (f.clone(), a.as_str())).collect();
                record_class(&t.name, &fs, ordered)
            }
            TypeBody::Opaque(_) => String::new(),
        }
    }

    /// Decide which types need ordering methods from the comparisons seen.
    pub fn collect_ordering(&mut self) {
        let ordered: Vec<Ty> = self.ck.ordered.iter().map(|t| self.ck.st.resolve(t)).collect();
        for t in ordered {
            self.mark_ordered(&t);
        }
    }

    fn mark_ordered(&mut self, t: &Ty) {
        match t {
            Ty::Con(n, args) => {
                match n.as_str() {
                    "Option" => self.needs.ordered_option = true,
                    "Result" => self.needs.ordered_result = true,
                    "List" | "Set" | "Seq" | "Map" => {}
                    other => {
                        if self.ck.types.contains_key(other) && !self.needs.ordered_types.contains(other) {
                            self.needs.ordered_types.insert(other.to_string());
                        }
                    }
                }
                for a in args {
                    self.mark_ordered(a);
                }
            }
            Ty::Tuple(ts) => {
                for x in ts {
                    self.mark_ordered(x);
                }
            }
            _ => {}
        }
    }

    /// The `_pf_codecs` registry `Decode.auto` descriptors refer to.
    fn codec_registry(&mut self) -> String {
        if self.ck.codecs.is_empty() {
            return String::new();
        }
        let entries: Vec<(String, crate::codec::Codec)> = self.ck.codecs.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        let items: Vec<String> = entries.iter().map(|(k, c)| format!("\"{}\": {}", k.replace('\\', "\\\\").replace('"', "\\\""), self.codec_text(c))).collect();
        format!("_pf_codecs = {{{}}}\n", items.join(", "))
    }

    pub fn assemble(&mut self, decls: &[Decl], code: &[PS]) -> String {
        let printer = Printer { py311: self.py311 };
        let mut body = String::new();
        printer.stmts(code, 0, &mut body);
        let types_text = self.type_classes(decls);
        let p = self.parts(types_text);
        let body = crate::native::resolve_annotations(&body, self.have_option, self.have_result);
        let mut s = p.prelude;
        s.push_str(&p.types);
        s.push_str(&p.codecs);
        s.push_str(&body);
        if s.is_empty() {
            s.push_str("pass\n");
        }
        s
    }

    /// The module's infrastructure (imports, classes, helpers), its type
    /// classes and its codec helpers, as separate texts.
    pub fn parts(&mut self, types_text: String) -> Parts {
        // (rendered first: the classes it names may come from modules)
        let registry = self.codec_registry();
        // helper closure
        let mut helpers: BTreeSet<String> = self.needs.helpers.clone();
        loop {
            let mut added = Vec::new();
            for h in &helpers {
                if let Some(hd) = HELPERS.iter().find(|x| x.name == h) {
                    for d in hd.deps {
                        if d.starts_with("_pf_") && !helpers.contains(*d) {
                            added.push(d.to_string());
                        }
                    }
                }
            }
            if added.is_empty() {
                break;
            }
            helpers.extend(added);
        }
        let mut imports: BTreeSet<String> = self.needs.imports.clone();
        for h in &helpers {
            if let Some(hd) = HELPERS.iter().find(|x| x.name == h) {
                for d in hd.deps {
                    match *d {
                        "#option" => self.needs.option = true,
                        "#result" => self.needs.result = true,
                        "#exception" => {
                            self.needs.exception = true;
                            self.needs.result = true;
                        }
                        x if x.starts_with('@') => {
                            if x == "@functools" {
                                self.needs.functools = true;
                            } else {
                                imports.insert(x[1..].to_string());
                            }
                        }
                        _ => {}
                    }
                }
            }
        }
        if self.needs.exception {
            self.needs.result = true;
        }
        let mut s = String::new();
        if self.project {
            let used = self.used_modules.borrow().clone();
            for (m, alias) in self.module_imports.iter().filter(|(_, a)| used.contains(a)) {
                if m == alias {
                    imports.insert(m.clone());
                } else {
                    imports.insert(format!("{} as {}", m, alias));
                }
            }
            // the core classes come from the shared runtime module
            self.have_option = self.needs.option;
            self.have_result = self.needs.result;
            let mut rt = String::new();
            if self.needs.result {
                rt.push_str("from _pyfun_rt import Ok, Error\n");
            }
            if self.needs.option {
                rt.push_str("from _pyfun_rt import Some, None_, _None_\n");
            }
            if self.needs.exception {
                rt.push_str("from _pyfun_rt import _Exception\n");
            }
            if !rt.is_empty() {
                self.uses_rt = true;
            }
            self.rt_imports = rt;
            self.needs.option = false;
            self.needs.result = false;
            self.needs.exception = false;
        }
        if !self.project {
            self.have_option = self.needs.option;
            self.have_result = self.needs.result;
        }
        let any_dataclass = self.needs.option || self.needs.result || self.needs.exception || types_text.contains("@dataclass");
        let any_ordering = !self.native && (types_text.contains("@total_ordering") || (self.needs.option && self.needs.ordered_option) || (self.needs.result && self.needs.ordered_result));
        if self.native && (self.needs.option || self.needs.result) {
            self.needs.any = true;
        }
        if any_dataclass {
            s.push_str("from dataclasses import dataclass\n");
        }
        if any_ordering {
            s.push_str("from functools import total_ordering\n");
        }
        if self.native && self.needs.any {
            s.push_str("from typing import Any\n");
        }
        if self.needs.functools {
            s.push_str("import functools\n");
        }
        for i in &imports {
            s.push_str(&format!("import {}\n", i));
        }
        s.push_str(&self.rt_imports.clone());
        if self.native {
            let any = vec!["Any".to_string()];
            if self.needs.result {
                s.push_str(&crate::native::adt_class_native("Ok", &any, if self.needs.ordered_result { Some(0) } else { None }, false));
                s.push_str(&crate::native::adt_class_native("Error", &any, if self.needs.ordered_result { Some(1) } else { None }, false));
            }
            if self.needs.option {
                s.push_str(&crate::native::adt_class_native("Some", &any, if self.needs.ordered_option { Some(1) } else { None }, false));
                s.push_str(&crate::native::adt_class_native("None_", &[], if self.needs.ordered_option { Some(0) } else { None }, true));
            }
        } else {
            if self.needs.result {
                s.push_str(&adt_class("Ok", &["object"], if self.needs.ordered_result { Some(0) } else { None }, false));
                s.push_str(&adt_class("Error", &["object"], if self.needs.ordered_result { Some(1) } else { None }, false));
            }
            if self.needs.option {
                s.push_str(&adt_class("Some", &["object"], if self.needs.ordered_option { Some(1) } else { None }, false));
                s.push_str(&adt_class("None_", &[], if self.needs.ordered_option { Some(0) } else { None }, true));
            }
        }
        if self.needs.exception {
            s.push_str(EXCEPTION_CLASS);
        }
        for group in 1..=5u8 {
            let mut names: Vec<&str> = HELPERS.iter().filter(|h| h.group == group && helpers.contains(h.name)).map(|h| h.name).collect();
            names.sort();
            if group == 5 {
                if let Some(i) = names.iter().position(|n| *n == "_pf_scope") {
                    let x = names.remove(i);
                    names.insert(0, x);
                }
            }
            for n in names {
                let h = HELPERS.iter().find(|x| x.name == n).unwrap();
                s.push_str(h.text);
                s.push('\n');
            }
        }
        let mut codecs = String::new();
        let mut names: Vec<&str> = HELPERS.iter().filter(|h| h.group == 6 && helpers.contains(h.name)).map(|h| h.name).collect();
        names.sort();
        for n in names {
            let h = HELPERS.iter().find(|x| x.name == n).unwrap();
            codecs.push_str(h.text);
            codecs.push('\n');
        }
        codecs.push_str(&registry);
        Parts { prelude: s, types: types_text, codecs }

    }
}
