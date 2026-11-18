// The lowered items onto scene nodes: a node's `.lini-*` classes are its
// type chain (its primitive's class last, as the original writes them), its
// other classes the user's; decls parse as written; a link statement waits in
// the builder like any other, its spans those of the statement it lowers.

use crate::ast::{Decl, Endpoint, Expr, LinkStmt, Stmt, Term, Value};
use crate::desugar::{Item, LDecl, OLink, ONode};
use crate::diag::{Diag, Span};
use crate::scene::{Builder, Node};
use crate::types::Prim;

fn prim_of(p: &str) -> Prim {
    match crate::types::find(p) {
        Some(t) => t.prim,
        None => Prim::Block,
    }
}

// (chain, user classes)
pub fn split_classes(classes: &[String], prim: &str) -> (Vec<String>, Vec<String>) {
    let mut chain = Vec::new();
    let mut user = Vec::new();
    let mut has_prim = false;
    for c in classes {
        match c.strip_prefix("lini-") {
            Some(t) if t == prim => has_prim = true,
            Some(t) => chain.push(t.to_string()),
            None => user.push(c.clone()),
        }
    }
    if has_prim || chain.is_empty() {
        chain.push(prim.to_string());
    }
    (chain, user)
}

fn set_expr_span(e: &mut Expr, sp: Span) {
    match e {
        Expr::Num(_, s) | Expr::Percent(_, s) | Expr::Ident(_, s) | Expr::Str(_, s) | Expr::Var(_, s) | Expr::Hash(_, s) => *s = sp,
        Expr::Call(_, args, s) => {
            *s = sp;
            for a in args {
                set_expr_span(a, sp);
            }
        }
        Expr::Unary(_, a, s) => {
            *s = sp;
            set_expr_span(a, sp);
        }
        Expr::Bin(_, a, b, s) => {
            *s = sp;
            set_expr_span(a, sp);
            set_expr_span(b, sp);
        }
        Expr::Ternary(a, b, c, s) => {
            *s = sp;
            set_expr_span(a, sp);
            set_expr_span(b, sp);
            set_expr_span(c, sp);
        }
        Expr::Tuple(xs, s) => {
            *s = sp;
            for x in xs {
                set_expr_span(x, sp);
            }
        }
        Expr::Block(bs, x, s) => {
            *s = sp;
            for (_, b) in bs {
                set_expr_span(b, sp);
            }
            set_expr_span(x, sp);
        }
    }
}

fn set_term_span(t: &mut Term, sp: Span) {
    match t {
        Term::Num(_, _, s) | Term::Percent(_, _, s) | Term::Ident(_, s) | Term::Str(_, s) | Term::Hash(_, s) | Term::Var(_, s) => {
            *s = sp
        }
        Term::Call(_, args, s) => {
            *s = sp;
            for a in args {
                set_expr_span(a, sp);
            }
        }
        Term::Group(e, s) => {
            *s = sp;
            set_expr_span(e, sp);
        }
        Term::Tagged(inner, _, s) => {
            *s = sp;
            set_term_span(inner, sp);
        }
    }
}

pub fn set_value_span(v: &mut Value, sp: Span) {
    v.span = sp;
    for g in v.groups.iter_mut() {
        for t in g.iter_mut() {
            set_term_span(t, sp);
        }
    }
}

pub fn set_decl_span(d: &mut Decl, sp: Span) {
    d.span = sp;
    d.name_span = sp;
    set_value_span(&mut d.value, sp);
}

// the lowered decls as the compile reads them
pub fn convert_decls(ds: &[LDecl], fallback: Span) -> Vec<Decl> {
    let mut out = Vec::new();
    for d in ds {
        let full = format!("{{{}}}", d.text());
        let lexed = match crate::lexer::lex(&full) {
            Ok(l) => l,
            Err(_) => continue,
        };
        let mut p = crate::parser::Parser::new(&lexed.tokens, &full);
        if let Ok((decls, _)) = p.parse_style_block() {
            for mut x in decls {
                let sp = if d.span == Span::default() { fallback } else { d.span };
                set_decl_span(&mut x, sp);
                out.push(x);
            }
        }
    }
    out
}

fn dup_check(b: &Builder, scope: usize, id: &str, span: Span) -> Result<(), Diag> {
    if let Some(&prev) = b.ids.get(&(scope, id.to_string())) {
        let (pl, pc) = crate::diag::line_col(b.src, b.nodes[prev].span.start);
        return Err(Diag {
            related: Some(b.nodes[prev].span),
            ..Diag::error("duplicate-id", &format!("duplicate id '{}' (previously at {}:{})", id, pl, pc), span)
        });
    }
    Ok(())
}

pub fn build_onode(b: &mut Builder, o: &ONode, parent: usize, fallback: Span) -> Result<usize, Diag> {
    let prim = prim_of(&o.prim);
    let (chain, user) = split_classes(&o.classes, &o.prim);
    let span = o.origin.unwrap_or(fallback);
    b.check_classes(&user, span)?;
    let mut n = Node::new(prim, chain, span);
    n.id = o.id.clone();
    n.classes = user;
    n.inline = convert_decls(&o.decls, span);
    n.label = o.label.clone();
    if prim == Prim::Line {
        n.text = o.label.clone();
    }
    let scope = b.child_scope(parent);
    if let Some(id) = &o.id {
        dup_check(b, scope, id, span)?;
    }
    let i = b.add(n, Some(parent));
    if let Some(id) = &o.id {
        b.ids.insert((scope, id.clone()), i);
    }
    build_children(b, o, i)?;
    Ok(i)
}

pub fn build_children(b: &mut Builder, o: &ONode, i: usize) -> Result<(), Diag> {
    let span = b.nodes[i].span;
    let kids = crate::desugar::print_children(o);
    build_items(b, &kids, i, span)
}

pub fn build_items(b: &mut Builder, items: &[Item], parent: usize, fallback: Span) -> Result<(), Diag> {
    for it in items {
        match it {
            Item::Node(o) => {
                build_onode(b, o, parent, fallback)?;
            }
            Item::Text(t) => {
                b.check_classes(&t.classes, fallback)?;
                if !t.text.is_empty() {
                    let decls = convert_decls(&t.decls, fallback);
                    let style = if decls.is_empty() { None } else { Some(decls) };
                    b.text_node(&t.text, &t.classes, style.as_ref(), fallback, parent);
                }
            }
            Item::Link(l) => {
                if let Some(ls) = link_stmt(b.src, l, fallback) {
                    let idx = b.stmt_counter;
                    b.stmt_counter += 1;
                    b.pending_links.push((parent, ls, idx));
                }
            }
        }
    }
    Ok(())
}

// an endpoint's span: where its text stands in the statement it lowers
fn find_in(src: &str, stmt: Span, text: &str) -> Option<Span> {
    let s = src.get(stmt.start..stmt.end)?;
    let b = s.as_bytes();
    let mut from = 0;
    while let Some(p) = s[from..].find(text) {
        let at = from + p;
        let end = at + text.len();
        let before_ok = at == 0 || !(b[at - 1].is_ascii_alphanumeric() || b[at - 1] == b'_' || b[at - 1] == b'-' || b[at - 1] == b'.');
        let after_ok = end >= b.len() || !(b[end].is_ascii_alphanumeric() || b[end] == b'_' || b[end] == b'-' || b[end] == b'.');
        if before_ok && after_ok {
            return Some(Span::new(stmt.start + at, stmt.start + end));
        }
        from = at + 1;
    }
    None
}

fn fix_stmt_spans(s: &mut Stmt, sp: Span) {
    match s {
        Stmt::Text(t) => {
            t.span = sp;
            if let Some(st) = t.style.as_mut() {
                for d in st.iter_mut() {
                    set_decl_span(d, sp);
                }
            }
        }
        Stmt::Node(n) => {
            n.span = sp;
            n.head_span = sp;
        }
        Stmt::Link(l) => l.span = sp,
    }
}

pub fn link_stmt(src: &str, l: &OLink, fallback: Span) -> Option<LinkStmt> {
    let text = crate::desugar::link_text(l);
    let (doc, _) = crate::parser::parse(&text).ok()?;
    let mut ls = match doc.stmts.into_iter().next() {
        Some(Stmt::Link(ls)) => ls,
        _ => return None,
    };
    let sp = l.origin.unwrap_or(fallback);
    ls.span = sp;
    for op in ls.ops.iter_mut() {
        op.1 = sp;
    }
    if let Some(lb) = ls.label.as_mut() {
        lb.1 = sp;
    }
    if let Some(st) = ls.style.as_mut() {
        for d in st.iter_mut() {
            set_decl_span(d, sp);
        }
    }
    if let Some(lbs) = ls.labels.as_mut() {
        for s in lbs.iter_mut() {
            fix_stmt_spans(s, sp);
        }
    }
    for g in ls.groups.iter_mut() {
        for ep in g.iter_mut() {
            match ep {
                Endpoint::Path(p) => {
                    let mut t = p.parts.join(".");
                    if let Some(a) = &p.anchor {
                        t.push(':');
                        t.push_str(a);
                    }
                    p.span = find_in(src, sp, &t).or_else(|| find_in(src, sp, &p.parts.join("."))).unwrap_or(sp);
                }
                Endpoint::Node(n) => {
                    n.span = sp;
                    n.head_span = sp;
                }
                Endpoint::Text(_, s) => *s = sp,
            }
        }
    }
    Some(ls)
}
