// Canonical pretty-printer for `pyfun parse`.

use crate::ast::*;

fn ind(n: usize) -> String {
    "    ".repeat(n)
}

pub fn escape_str(s: &str) -> String {
    let mut out = String::new();
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\t' => out.push_str("\\t"),
            '\r' => out.push_str("\\r"),
            c => out.push(c),
        }
    }
    out
}

pub fn fmt_float(f: f64) -> String {
    format!("{:?}", f)
}

pub fn print_program(p: &Program) -> String {
    let mut out = String::new();
    for d in &p.decls {
        out.push_str(&fmt_decl(d, 0));
        out.push('\n');
    }
    out
}

fn fmt_doc(doc: &Option<String>, indent: usize) -> String {
    let mut out = String::new();
    if let Some(d) = doc {
        for line in d.split('\n') {
            out.push_str(&ind(indent));
            if line.is_empty() {
                out.push_str("##\n");
            } else {
                out.push_str("## ");
                out.push_str(line);
                out.push('\n');
            }
        }
    }
    out
}

fn fmt_decl(d: &Decl, indent: usize) -> String {
    match d {
        Decl::Let(l) => format!("{}{}{}", fmt_doc(&l.doc, indent), ind(indent), fmt_let(l, indent)),
        Decl::Type(t) => {
            let mut s = fmt_doc(&t.doc, indent);
            s.push_str(&ind(indent));
            let params: String = t.params.iter().map(|p| format!(" {}", p)).collect();
            match &t.body {
                TypeBody::Opaque(ty) => {
                    s.push_str(&format!("opaque type {}{} = {}", t.name, params, fmt_type(ty)));
                }
                TypeBody::Record(fields) => {
                    let fs: Vec<String> = fields.iter().map(|(n, _, ty)| format!("{}: {}", n, fmt_type(ty))).collect();
                    s.push_str(&format!("type {}{} = {{ {} }}", t.name, params, fs.join(", ")));
                }
                TypeBody::Sum(vs) => {
                    let vs: Vec<String> = vs
                        .iter()
                        .map(|v| {
                            let mut x = v.name.clone();
                            for a in &v.args {
                                x.push(' ');
                                x.push_str(&fmt_type_atom(a));
                            }
                            x
                        })
                        .collect();
                    s.push_str(&format!("type {}{} = {}", t.name, params, vs.join(" | ")));
                }
            }
            s
        }
        Decl::Measure(n, u, _) => match u {
            Some(u) => format!("{}measure {} = {}", ind(indent), n, fmt_unit(u)),
            None => format!("{}measure {}", ind(indent), n),
        },
        Decl::Extern(e) => {
            let mut s = fmt_doc(&e.doc, indent);
            s.push_str(&ind(indent));
            s.push_str("extern ");
            if e.pure_ {
                s.push_str("pure ");
            }
            s.push_str(&format!("{}: {}", e.name, fmt_type(&e.ty)));
            // a target naming the extern itself is the default
            let default = matches!(&e.target, Some(ExternTarget::Path(p)) if p.len() == 1 && p[0] == e.name) && e.kwargs.as_ref().map_or(true, |k| k.is_empty());
            if let Some(t) = e.target.as_ref().filter(|_| !default) {
                s.push_str(" = ");
                match t {
                    ExternTarget::Path(p) => s.push_str(&p.join(".")),
                    ExternTarget::Member(n, call) => {
                        s.push('.');
                        s.push_str(n);
                        if *call && e.kwargs.is_none() {
                            s.push_str("()");
                        }
                    }
                }
                if let Some(kws) = &e.kwargs {
                    // `name()` with nothing pinned is just `name`
                    if !kws.is_empty() || matches!(t, ExternTarget::Member(..)) {
                        let ks: Vec<String> = kws.iter().map(|(k, v)| format!("{}={}", k, fmt_kw(v))).collect();
                        s.push_str(&format!("({})", ks.join(", ")));
                    }
                }
            }
            s
        }
        Decl::ExternType(n, ps, _, doc) => {
            let params: String = ps.iter().map(|p| format!(" {}", p)).collect();
            format!("{}{}extern type {}{}", fmt_doc(doc, indent), ind(indent), n, params)
        }
        Decl::ExternImport(p, a, _) => match a {
            Some(a) => format!("{}extern import {} as {}", ind(indent), p.join("."), a),
            None => format!("{}extern import {}", ind(indent), p.join(".")),
        },
        Decl::Module(n, _, ds) => {
            let mut s = format!("{}module {} =", ind(indent), n);
            for d in ds {
                s.push('\n');
                s.push_str(&fmt_decl(d, indent + 1));
            }
            s
        }
        Decl::Import(n, _) => format!("{}import {}", ind(indent), n),
        Decl::Expr(e) => match &e.kind {
            // a statement-level match keeps its arms on their own lines
            ExprKind::Match(scrut, arms) => {
                let mut s = format!("{}match {}:", ind(indent), fmt_expr(scrut));
                for a in arms {
                    s.push('\n');
                    s.push_str(&ind(indent + 1));
                    s.push_str(&format!("case {}", fmt_pat(&a.pat)));
                    if let Some(g) = &a.guard {
                        s.push_str(&format!(" if {}", fmt_expr(g)));
                    }
                    s.push(':');
                    s.push_str(&fmt_body(&a.body, indent + 1));
                }
                s
            }
            _ => format!("{}{}", ind(indent), fmt_expr(e)),
        },
        Decl::Assign(n, _, e, _) => format!("{}({} <- {})", ind(indent), n, fmt_expr(e)),
    }
}

fn fmt_kw(v: &KwValue) -> String {
    match v {
        KwValue::Int(n) => n.to_string(),
        KwValue::Float(f) => fmt_float(*f),
        KwValue::Str(s) => format!("\"{}\"", escape_str(s)),
        KwValue::Bool(b) => b.to_string(),
        KwValue::Slot => "...".into(),
    }
}

fn fmt_let_head(l: &LetDecl) -> String {
    let mut s = String::from("let ");
    if l.mutable {
        s.push_str("mut ");
    }
    if l.pure_ {
        s.push_str("pure ");
    }
    s.push_str(&fmt_pat(&l.pat));
    for p in &l.params {
        s.push(' ');
        s.push_str(&fmt_param(p));
    }
    s
}

fn fmt_let(l: &LetDecl, indent: usize) -> String {
    format!("{} ={}", fmt_let_head(l), fmt_body(&l.value, indent))
}

fn fmt_param(p: &Pat) -> String {
    match &p.kind {
        PatKind::Record(..) => format!("({})", fmt_pat(p)),
        _ => fmt_pat(p),
    }
}

fn is_complex(e: &Expr) -> bool {
    match &e.kind {
        ExprKind::Block(_) | ExprKind::Match(..) => true,
        ExprKind::If(_, t, f) => is_complex(t) || is_complex(f),
        _ => false,
    }
}

/// A value in body position: blocks, matches and ifs over them go multi-line.
fn fmt_body(e: &Expr, indent: usize) -> String {
    match &e.kind {
        ExprKind::Block(stmts) => {
            let mut s = String::new();
            for st in stmts {
                s.push('\n');
                s.push_str(&ind(indent + 1));
                s.push_str(&fmt_stmt(st, indent + 1));
            }
            s
        }
        ExprKind::Match(scrut, arms) => {
            let mut s = format!("\n{}match {}:", ind(indent + 1), fmt_expr(scrut));
            for a in arms {
                s.push('\n');
                s.push_str(&ind(indent + 2));
                s.push_str(&format!("case {}", fmt_pat(&a.pat)));
                if let Some(g) = &a.guard {
                    s.push_str(&format!(" if {}", fmt_expr(g)));
                }
                s.push(':');
                s.push_str(&fmt_body(&a.body, indent + 2));
            }
            s
        }
        ExprKind::If(..) if is_complex(e) => {
            let mut s = String::new();
            let mut cur = e;
            let mut first = true;
            loop {
                match &cur.kind {
                    ExprKind::If(c, t, f) => {
                        s.push('\n');
                        s.push_str(&ind(indent + 1));
                        s.push_str(if first { "if " } else { "elif " });
                        s.push_str(&fmt_expr(c));
                        s.push_str(" then");
                        s.push_str(&fmt_body(t, indent + 1));
                        first = false;
                        if let ExprKind::If(..) = f.kind {
                            cur = f;
                            continue;
                        }
                        s.push('\n');
                        s.push_str(&ind(indent + 1));
                        s.push_str("else");
                        s.push_str(&fmt_body(f, indent + 1));
                        break;
                    }
                    _ => unreachable!(),
                }
            }
            s
        }
        _ => format!(" {}", fmt_expr(e)),
    }
}

fn fmt_stmt(s: &Stmt, indent: usize) -> String {
    match s {
        Stmt::Let(l) => fmt_let(l, indent),
        Stmt::Assign(n, _, e, _) => format!("({} <- {})", n, fmt_expr(e)),
        Stmt::Expr(e) => fmt_expr(e),
    }
}

pub fn fmt_expr(e: &Expr) -> String {
    match &e.kind {
        ExprKind::Int(n) => n.to_string(),
        ExprKind::Float(f) => fmt_float(*f),
        ExprKind::Str(s) => format!("\"{}\"", escape_str(s)),
        ExprKind::FStr(parts) => {
            let mut s = String::from("f\"");
            for p in parts {
                match p {
                    FPart::Text(t) => s.push_str(&escape_str(t).replace('{', "{{").replace('}', "}}")),
                    FPart::Expr(e) => {
                        s.push('{');
                        s.push_str(&fmt_expr(e));
                        s.push('}');
                    }
                }
            }
            s.push('"');
            s
        }
        ExprKind::Bool(b) => b.to_string(),
        ExprKind::Unit => "()".into(),
        ExprKind::Var(n) => n.clone(),
        ExprKind::Ctor(p, n) => qual(p, n),
        ExprKind::Qual(p, n, _) => qual(p, n),
        ExprKind::Field(b, f, _) => format!("{}.{}", fmt_expr(b), f),
        ExprKind::App(f, a) => format!("({} {})", fmt_expr(f), fmt_expr(a)),
        ExprKind::Binary(op, l, r) => format!("({} {} {})", fmt_expr(l), op.text(), fmt_expr(r)),
        ExprKind::Chain(first, rest) => {
            let mut s = format!("({}", fmt_expr(first));
            for (op, e) in rest {
                s.push_str(&format!(" {} {}", op.text(), fmt_expr(e)));
            }
            s.push(')');
            s
        }
        ExprKind::Neg(e) => format!("(- {})", fmt_expr(e)),
        ExprKind::Not(e) => format!("(not {})", fmt_expr(e)),
        ExprKind::Try(e) => format!("(try {})", fmt_expr(e)),
        ExprKind::If(c, t, f) => {
            let mut s = format!("(if {} then {}", fmt_expr(c), fmt_expr(t));
            let mut cur = f;
            loop {
                match &cur.kind {
                    ExprKind::If(c2, t2, f2) => {
                        s.push_str(&format!(" elif {} then {}", fmt_expr(c2), fmt_expr(t2)));
                        cur = f2;
                    }
                    _ => {
                        s.push_str(&format!(" else {})", fmt_expr(cur)));
                        break;
                    }
                }
            }
            s
        }
        ExprKind::Match(scrut, arms) => {
            let mut s = format!("(match {}:", fmt_expr(scrut));
            for a in arms {
                s.push_str(&format!(" case {}", fmt_pat(&a.pat)));
                if let Some(g) = &a.guard {
                    s.push_str(&format!(" if {}", fmt_expr(g)));
                }
                s.push_str(&format!(": {}", fmt_expr(&a.body)));
            }
            s.push(')');
            s
        }
        ExprKind::Lambda(ps, body) => {
            let ps: Vec<String> = ps.iter().map(fmt_param).collect();
            format!("(fun {} -> {})", ps.join(" "), fmt_expr(body))
        }
        ExprKind::Block(stmts) => {
            let mut s = String::new();
            for st in stmts {
                s.push('\n');
                s.push_str(&ind(1));
                s.push_str(&fmt_stmt(st, 1));
            }
            s
        }
        ExprKind::Tuple(items) => {
            let v: Vec<String> = items.iter().map(fmt_expr).collect();
            format!("({})", v.join(", "))
        }
        ExprKind::List(items) => {
            let v: Vec<String> = items.iter().map(fmt_expr).collect();
            format!("[{}]", v.join(", "))
        }
        ExprKind::Record(p, n, _, fields) => {
            let v: Vec<String> = fields.iter().map(|(f, _, e)| format!("{} = {}", f, fmt_expr(e))).collect();
            format!("{} {{ {} }}", qual(p, n), v.join(", "))
        }
        ExprKind::Update(b, fields) => {
            let v: Vec<String> = fields
                .iter()
                .map(|(path, e)| {
                    let p: Vec<&str> = path.iter().map(|(n, _)| n.as_str()).collect();
                    format!("{} = {}", p.join("."), fmt_expr(e))
                })
                .collect();
            format!("{{ {} with {} }}", fmt_expr(b), v.join(", "))
        }
        ExprKind::Section(op) => format!("({})", op.text()),
        ExprKind::Assign(n, _, v) => format!("({} <- {})", n, fmt_expr(v)),
        ExprKind::Hole(n) => match n {
            Some(n) => format!("?{}", n),
            None => "?".into(),
        },
        ExprKind::Measured(lit, u) => format!("{}<{}>", fmt_expr(lit), fmt_unit(u)),
        ExprKind::Ce(p, n, items) => {
            if ce_needs_block(items) {
                let mut s = format!("{} {{", qual(p, n));
                for it in items {
                    s.push('\n');
                    s.push_str(&ind(1));
                    s.push_str(&fmt_ce_block(it, 1));
                }
                s.push_str("\n}");
                return s;
            }
            let v: Vec<String> = items.iter().map(fmt_ce).collect();
            format!("{} {{ {} }}", qual(p, n), v.join(" "))
        }
    }
}

fn ce_needs_block(items: &[CeStmt]) -> bool {
    items.iter().any(|i| matches!(i, CeStmt::For(_, _, body, _) if body.len() > 1 || ce_needs_block(body)))
}

fn fmt_ce_block(s: &CeStmt, depth: usize) -> String {
    match s {
        CeStmt::For(p, src, body, _) if body.len() > 1 => {
            let mut out = format!("for {} in {}:", fmt_pat(p), fmt_expr(src));
            for it in body {
                out.push('\n');
                out.push_str(&ind(depth + 1));
                out.push_str(&fmt_ce_block(it, depth + 1));
            }
            out
        }
        CeStmt::For(p, src, body, _) => {
            let v: Vec<String> = body.iter().map(|i| fmt_ce_block(i, depth)).collect();
            format!("for {} in {}: {}", fmt_pat(p), fmt_expr(src), v.join(" "))
        }
        other => fmt_ce(other),
    }
}

fn fmt_ce(s: &CeStmt) -> String {
    match s {
        CeStmt::LetBang(p, e, _) => format!("let! {} = {}", fmt_pat(p), fmt_expr(e)),
        CeStmt::DoBang(e, _) => format!("do! {}", fmt_expr(e)),
        CeStmt::Let(l) => format!("{} = {}", fmt_let_head(l), fmt_expr(&l.value)),
        CeStmt::Return(e, _) => format!("return {}", fmt_expr(e)),
        CeStmt::ReturnBang(e, _) => format!("return! {}", fmt_expr(e)),
        CeStmt::Yield(e, _) => format!("yield {}", fmt_expr(e)),
        CeStmt::YieldBang(e, _) => format!("yield! {}", fmt_expr(e)),
        CeStmt::For(p, src, body, _) => {
            let v: Vec<String> = body.iter().map(fmt_ce).collect();
            format!("for {} in {}: {}", fmt_pat(p), fmt_expr(src), v.join(" "))
        }
        CeStmt::Assign(n, _, e) => format!("({} <- {})", n, fmt_expr(e)),
    }
}

fn qual(p: &[String], n: &str) -> String {
    if p.is_empty() {
        n.to_string()
    } else {
        format!("{}.{}", p.join("."), n)
    }
}

pub fn fmt_pat(p: &Pat) -> String {
    match &p.kind {
        PatKind::Wild => "_".into(),
        PatKind::Var(n) => n.clone(),
        PatKind::Int(n) => n.to_string(),
        PatKind::Str(s) => format!("\"{}\"", escape_str(s)),
        PatKind::Bool(b) => b.to_string(),
        PatKind::Unit => "()".into(),
        PatKind::Ctor(path, n, args) => {
            if args.is_empty() {
                qual(path, n)
            } else {
                let a: Vec<String> = args.iter().map(fmt_pat).collect();
                format!("({} {})", qual(path, n), a.join(" "))
            }
        }
        PatKind::Tuple(ps) => {
            let a: Vec<String> = ps.iter().map(fmt_pat).collect();
            format!("({})", a.join(", "))
        }
        PatKind::List(es) => {
            let a: Vec<String> = es
                .iter()
                .map(|e| match e {
                    ListPatElem::Pat(p) => fmt_pat(p),
                    ListPatElem::Star(Some(n), _) => format!("*{}", n),
                    ListPatElem::Star(None, _) => "*_".into(),
                })
                .collect();
            format!("[{}]", a.join(", "))
        }
        PatKind::Record(path, n, _, fs) => {
            let a: Vec<String> = fs
                .iter()
                .map(|(f, _, p)| match p {
                    Some(p) => format!("{} = {}", f, fmt_pat(p)),
                    None => f.clone(),
                })
                .collect();
            format!("{} {{ {} }}", qual(path, n), a.join(", "))
        }
        PatKind::Or(ps) => {
            let a: Vec<String> = ps.iter().map(fmt_pat).collect();
            format!("({})", a.join(" | "))
        }
        PatKind::As(p, n, _) => format!("({} as {})", fmt_pat(p), n),
    }
}

pub fn fmt_unit(u: &UnitExpr) -> String {
    let nonzero = |v: &Vec<(String, i64)>| -> Vec<(String, i64)> { v.iter().filter(|(_, e)| *e != 0).cloned().collect() };
    let u = &UnitExpr { num: nonzero(&u.num), den: nonzero(&u.den), span: u.span };
    let f = |v: &Vec<(String, i64)>| -> String {
        v.iter()
            .map(|(n, e)| if *e == 1 { n.clone() } else { format!("{}^{}", n, e) })
            .collect::<Vec<_>>()
            .join(" ")
    };
    if u.num.is_empty() && u.den.is_empty() {
        return "1".into();
    }
    let num = if u.num.is_empty() { "1".to_string() } else { f(&u.num) };
    if u.den.is_empty() {
        num
    } else {
        format!("{}/{}", num, f(&u.den))
    }
}

pub fn fmt_type(t: &TypeExpr) -> String {
    match &t.kind {
        TypeKind::Fun(a, effs, r) => {
            let arrow = match effs {
                Some(es) => format!("->{{{}}}", es.join(", ")),
                None => "->".into(),
            };
            format!("{} {} {}", fmt_type_arg(a), arrow, fmt_type(r))
        }
        TypeKind::Con(p, n, args) => {
            let mut s = qual(p, n);
            for a in args {
                s.push(' ');
                s.push_str(&fmt_type_atom(a));
            }
            s
        }
        TypeKind::Var(v) => v.clone(),
        TypeKind::Tuple(ts) => {
            let v: Vec<String> = ts.iter().map(fmt_type).collect();
            format!("({})", v.join(", "))
        }
        TypeKind::Measured(b, u) => format!("{}<{}>", fmt_type(b), fmt_unit(u)),
    }
}

/// The argument of an arrow: applied types and arrows get parentheses.
fn fmt_type_arg(t: &TypeExpr) -> String {
    match &t.kind {
        TypeKind::Fun(..) => format!("({})", fmt_type(t)),
        TypeKind::Con(_, _, args) if !args.is_empty() => format!("({})", fmt_type(t)),
        _ => fmt_type(t),
    }
}

fn fmt_type_atom(t: &TypeExpr) -> String {
    fmt_type_arg(t)
}
