// Paint servers: `gradient(…)`, `linear-gradient(angle, …)` and
// `radial-gradient(…)` become <linearGradient>/<radialGradient> defs whose ids
// hash the gradient's resolved form; the paint itself is `url(#id)`.
//
// The id key is the reference compiler's resolved-value Debug text:
//   linear: "linear {f4(angle)} {stops:?}"   (gradient(…) is angle 135)
//   radial: "radial {stops:?}"
// with each stop a `KeyVal` (Ident / Number / Percent / Hex / String /
// LiveVar / Tuple / Call), Debug-formatted exactly as derived.

use crate::ast::Expr;
use crate::diag::{Diag, Span};
use crate::eval::{Env, EV};
use crate::util::{f4, hash8};
use std::cell::RefCell;
use std::collections::HashMap;

#[derive(Debug)]
#[allow(dead_code)]
enum KeyVal {
    Ident(String),
    Number(f64),
    Percent(f64),
    Hex(String),
    String(String),
    LiveVar { name: String, raw: bool },
    Tuple(Vec<KeyVal>),
    Call(ResolvedCall),
}

#[derive(Debug)]
#[allow(dead_code)]
struct ResolvedCall {
    name: String,
    args: Vec<KeyVal>,
}

pub struct Gradient {
    pub id: String,
    pub radial: bool,
    pub angle: f64,
    pub stops: Vec<String>,
    // the theme variables its stops read
    pub vars: Vec<String>,
}

thread_local! {
    static GRADIENTS: RefCell<Vec<Gradient>> = RefCell::new(Vec::new());
    static ENV: RefCell<Env> = RefCell::new(Env::default());
    static THEME: RefCell<Option<crate::theme::Theme>> = RefCell::new(None);
}

// Start a render: forget earlier gradients, remember the bindings and theme.
pub fn reset(env: &Env, theme: &str) {
    GRADIENTS.with(|g| g.borrow_mut().clear());
    ENV.with(|e| *e.borrow_mut() = env.clone());
    THEME.with(|t| *t.borrow_mut() = crate::theme::resolve(theme));
}

// A variable's literal value: the document's own declaration, else the
// theme's light side; nested var()s resolve the same way.
pub fn var_literal(ctx: &crate::compile::Ctx, name: &str) -> Option<String> {
    fn go(ctx: &crate::compile::Ctx, name: &str, depth: usize) -> Option<String> {
        if depth > 32 {
            return None;
        }
        let raw = match ctx.sheet.vars.iter().rev().find(|d| d.name == name) {
            Some(d) => crate::render::value_css_text(ctx, &d.value, &mut Vec::new()),
            None => THEME.with(|t| t.borrow().as_ref().and_then(|t| t.light_value(name)))?,
        };
        let mut out = String::new();
        let mut rest = raw.as_str();
        while let Some(p) = rest.find("var(--lini-") {
            out.push_str(&rest[..p]);
            let after = &rest[p + 11..];
            let end = after.find(')').unwrap_or(after.len());
            let inner = &after[..end];
            match go(ctx, inner, depth + 1) {
                Some(v) => out.push_str(&v),
                None => out.push_str(&rest[p..(p + 11 + end + 1).min(rest.len())]),
            }
            rest = &after[(end + 1).min(after.len())..];
        }
        out.push_str(rest);
        Some(match crate::theme::split_light_dark(&out) {
            Some((l, _)) => l,
            None => out,
        })
    }
    go(ctx, name, 0)
}

// `shadow: dx dy blur [colour]` (1, 2 or 3 numbers, or 3 and a colour) →
// (dx, dy, blur, flood colour as a literal).
pub fn shadow_spec(ctx: &crate::compile::Ctx, v: &crate::ast::Value) -> Option<(f64, f64, f64, String)> {
    use crate::ast::Term;
    if v.groups.len() != 1 {
        return None;
    }
    let g = &v.groups[0];
    let env = &ctx.sheet.env;
    let mut nums = Vec::new();
    let mut k = 0;
    while k < g.len() {
        match &g[k] {
            Term::Num(..) | Term::Group(..) => match crate::style::term_num(env, &g[k]) {
                Some(x) => nums.push(x),
                None => return None,
            },
            _ => break,
        }
        k += 1;
    }
    let rest = &g[k..];
    let (dx, dy, blur) = match nums.len() {
        1 => (nums[0], nums[0], nums[0]),
        2 => (nums[0], nums[1], 0.0),
        3 => (nums[0], nums[1], nums[2]),
        _ => return None,
    };
    let col = match rest.len() {
        0 => var_literal(ctx, "shadow-color").unwrap_or_default(),
        1 if nums.len() == 3 => match &rest[0] {
            Term::Var(n, _) => var_literal(ctx, n).unwrap_or_else(|| format!("var(--lini-{})", n)),
            Term::Ident(n, _) => n.clone(),
            t => crate::style::color_css(t, &mut Vec::new(), v.span).ok()?,
        },
        _ => return None,
    };
    Some((dx, dy, blur, col))
}

pub fn is_gradient(name: &str) -> bool {
    matches!(name, "gradient" | "linear-gradient" | "radial-gradient")
}

// The registered gradients as <defs> lines (stops in `style` form).
pub fn defs() -> Vec<String> {
    GRADIENTS.with(|g| {
        g.borrow()
            .iter()
            .map(|gr| {
                let n = gr.stops.len();
                let mut stops = String::new();
                for (k, c) in gr.stops.iter().enumerate() {
                    let off = if n > 1 { 100.0 * k as f64 / (n - 1) as f64 } else { 0.0 };
                    stops.push_str(&format!("<stop offset=\"{}%\" style=\"stop-color: {}\"/>", f4(off), c));
                }
                if gr.radial {
                    format!("<radialGradient id=\"{}\">{}</radialGradient>", gr.id, stops)
                } else {
                    format!(
                        "<linearGradient id=\"{}\" gradientTransform=\"rotate({} 0.5 0.5)\">{}</linearGradient>",
                        gr.id,
                        f4(gr.angle - 90.0),
                        stops
                    )
                }
            })
            .collect()
    })
}

fn rerr(msg: &str, span: Span) -> Diag {
    Diag::error("resolve", msg, span)
}

fn num_of(env: &Env, e: &Expr) -> Result<f64, Diag> {
    match env.eval(e, &HashMap::new())? {
        EV::Num(v) => Ok(v),
        _ => Err(rerr("expected a number", e.span())),
    }
}

// One stop argument → (key value, CSS text).
fn stop_of(e: &Expr, env: &Env, vars: &mut Vec<String>, span: Span) -> Result<(KeyVal, String), Diag> {
    Ok(match e {
        Expr::Ident(n, _) => {
            if !crate::style::is_named_color(n) {
                return Err(Diag::error("invalid-color", &format!("invalid color '{}'", n), span));
            }
            (KeyVal::Ident(n.clone()), n.clone())
        }
        Expr::Var(v, _) => {
            crate::style::use_var(vars, v);
            (KeyVal::LiveVar { name: v.clone(), raw: false }, format!("var(--lini-{})", v))
        }
        Expr::Hash(h, _) => (KeyVal::Hex(h.clone()), format!("#{}", h)),
        Expr::Str(s, _) => (KeyVal::String(s.clone()), format!("\"{}\"", s)),
        Expr::Num(v, _) => (KeyVal::Number(*v), f4(*v)),
        Expr::Percent(v, _) => (KeyVal::Percent(*v), format!("{}%", f4(*v))),
        Expr::Tuple(items, _) | Expr::Call(_, items, _) if !matches!(e, Expr::Call(n, _, _) if n != crate::parser::RUN) => {
            let mut ks = Vec::new();
            let mut cs = Vec::new();
            for it in items {
                // (a run's words ride through unchecked)
                let (k, c) = match it {
                    Expr::Ident(n, _) => (KeyVal::Ident(n.clone()), n.clone()),
                    _ => stop_of(it, env, vars, span)?,
                };
                ks.push(k);
                cs.push(c);
            }
            (KeyVal::Tuple(ks), cs.join(" "))
        }
        Expr::Call(name, args, _) if name == "oklch" => {
            let hex = crate::style::oklch_call_hex(args, span)?;
            (KeyVal::Hex(hex.trim_start_matches('#').to_string()), hex)
        }
        Expr::Call(name, args, _) if matches!(name.as_str(), "rgb" | "rgba" | "hsl" | "hsla") => {
            crate::validate::color_range(name, args, &|e: &Expr| num_of(env, e).ok())
                .map_err(|m| Diag::error("color-component-out-of-range", &m, span))?;
            let mut ks = Vec::new();
            let mut cs = Vec::new();
            for a in args {
                let (k, c) = stop_of(a, env, vars, span)?;
                ks.push(k);
                cs.push(c);
            }
            (KeyVal::Call(ResolvedCall { name: name.clone(), args: ks }), format!("{}({})", name, cs.join(", ")))
        }
        // any other builder rides through as written
        Expr::Call(name, args, _) if is_gradient(name) || matches!(name.as_str(), "hatch" | "repeat") => {
            let mut ks = Vec::new();
            let mut cs = Vec::new();
            for a in args {
                let (k, c) = stop_of(a, env, vars, span)?;
                ks.push(k);
                cs.push(c);
            }
            (KeyVal::Call(ResolvedCall { name: name.clone(), args: ks }), format!("{}({})", name, cs.join(", ")))
        }
        _ => {
            let v = env.eval(e, &HashMap::new()).map_err(|d| Diag { span, ..d })?;
            match v {
                EV::Num(x) => (KeyVal::Number(x), f4(x)),
                _ => return Err(rerr("expected a number", span)),
            }
        }
    })
}

// The gradient's shape alone (the R-phase): stops, angle, colours.
pub fn gradient_check(name: &str, args: &[Expr], env: &Env, span: Span) -> Result<(), Diag> {
    resolve_gradient(name, args, env, &mut Vec::new(), span).map(|_| ())
}

// A gradient call → `url(#lini-gradient-…)`, registering its def.
// `span` is the declaration's span (what the errors point at).
pub fn gradient_css(name: &str, args: &[Expr], vars: &mut Vec<String>, span: Span) -> Result<String, Diag> {
    let env = ENV.with(|e| e.borrow().clone());
    let (g, key_vars) = resolve_gradient(name, args, &env, vars, span)?;
    let id = g.id.clone();
    GRADIENTS.with(|gs| {
        let mut gs = gs.borrow_mut();
        if !gs.iter().any(|x| x.id == id) {
            gs.push(g);
        }
    });
    for v in key_vars {
        crate::style::use_var(vars, &v);
    }
    Ok(format!("url(#{})", id))
}

fn resolve_gradient(name: &str, args: &[Expr], env: &Env, _vars: &mut Vec<String>, span: Span) -> Result<(Gradient, Vec<String>), Diag> {
    let env = env.clone();
    // colour names are checked before the gradient's shape
    let mut stops_k = Vec::new();
    let mut stops_c = Vec::new();
    let (radial, angle, stop_args): (bool, f64, &[Expr]) = match name {
        "radial-gradient" => (true, 0.0, args),
        "linear-gradient" => {
            let first_ok = match args.first() {
                Some(Expr::Ident(n, _)) if !crate::style::is_named_color(n) => {
                    return Err(Diag::error("invalid-color", &format!("invalid color '{}'", n), span));
                }
                Some(a @ (Expr::Num(..) | Expr::Unary(..) | Expr::Bin(..) | Expr::Call(..) | Expr::Ternary(..) | Expr::Block(..))) => {
                    num_of(&env, a).ok()
                }
                _ => None,
            };
            for a in args.iter().skip(1) {
                stop_of(a, &env, &mut Vec::new(), span)?;
            }
            match first_ok {
                Some(v) => (false, v, &args[1..]),
                None => {
                    return Err(rerr(
                        "linear-gradient needs an angle first, then ≥ 2 colour stops — e.g. linear-gradient(135, --teal, --sky)",
                        span,
                    ))
                }
            }
        }
        _ => (false, 135.0, args),
    };
    let mut own_vars = Vec::new();
    for a in stop_args {
        let (k, c) = stop_of(a, &env, &mut own_vars, span)?;
        stops_k.push(k);
        stops_c.push(c);
    }
    if stops_k.len() < 2 {
        let what = if name == "gradient" { "gradient()" } else if radial { "radial-gradient()" } else { "linear-gradient()" };
        return Err(rerr(&format!("{} needs at least two colour stops", what), span));
    }
    let key = if radial { format!("radial {:?}", stops_k) } else { format!("linear {} {:?}", f4(angle), stops_k) };
    let id = format!("lini-gradient-{}", hash8(&key));
    Ok((Gradient { id, radial, angle, stops: stops_c, vars: own_vars.clone() }, own_vars))
}

// Every `--var` a declaration mentions, in any property: the reference
// compiler declares each one at the root whether or not CSS reads it.
fn value_vars(v: &crate::ast::Value, out: &mut Vec<String>) {
    use crate::ast::Term;
    fn expr(e: &Expr, out: &mut Vec<String>) {
        match e {
            Expr::Var(n, _) => crate::style::use_var(out, n),
            Expr::Call(_, args, _) | Expr::Tuple(args, _) => args.iter().for_each(|a| expr(a, out)),
            Expr::Unary(_, a, _) => expr(a, out),
            Expr::Bin(_, a, b, _) => {
                expr(a, out);
                expr(b, out);
            }
            Expr::Ternary(a, b, c, _) => {
                expr(a, out);
                expr(b, out);
                expr(c, out);
            }
            Expr::Block(binds, body, _) => {
                binds.iter().for_each(|(_, e)| expr(e, out));
                expr(body, out);
            }
            _ => {}
        }
    }
    fn term(t: &Term, out: &mut Vec<String>) {
        match t {
            Term::Var(n, _) => crate::style::use_var(out, n),
            Term::Call(_, args, _) => args.iter().for_each(|a| expr(a, out)),
            Term::Group(e, _) => expr(e, out),
            Term::Tagged(t, _, _) => term(t, out),
            _ => {}
        }
    }
    for g in &v.groups {
        for t in g {
            term(t, out);
        }
    }
}

pub fn decl_vars(ctx: &crate::compile::Ctx, used_types: &[String]) -> Vec<String> {
    let mut out = Vec::new();
    let sheet = &ctx.sheet;
    for d in &sheet.root {
        value_vars(&d.value, &mut out);
    }
    for c in &sheet.classes {
        for d in &c.decls {
            value_vars(&d.value, &mut out);
        }
    }
    for d in &sheet.link_rules {
        value_vars(&d.value, &mut out);
    }
    // the drawn types' rules (a value a node overrides still counts)
    for t in used_types {
        if let Some(df) = sheet.define(t) {
            for d in &df.decls {
                value_vars(&d.value, &mut out);
            }
        }
        for d in sheet.type_rule(t) {
            value_vars(&d.value, &mut out);
        }
    }
    // each node's cascaded declarations (what its type, classes, id and
    // inline style leave standing)
    for n in ctx.nodes.iter().skip(1) {
        for v in n.props.values() {
            value_vars(v, &mut out);
        }
    }
    for l in &ctx.links {
        for d in &l.style {
            value_vars(&d.value, &mut out);
        }
    }
    out
}

// A term as written (numbers in canonical form, groups evaluated).
pub fn term_text(t: &crate::ast::Term, vars: &mut Vec<String>) -> String {
    use crate::ast::Term;
    match t {
        Term::Num(v, _, _) => f4(*v),
        Term::Percent(v, _, _) => format!("{}%", f4(*v)),
        Term::Ident(s, _) => s.clone(),
        Term::Str(s, _) => format!("\"{}\"", s),
        Term::Hash(h, _) => format!("#{}", h),
        Term::Var(n, _) => {
            crate::style::use_var(vars, n);
            format!("var(--lini-{})", n)
        }
        Term::Group(e, _) => {
            let env = ENV.with(|e| e.borrow().clone());
            match env.eval(e, &HashMap::new()) {
                Ok(EV::Num(x)) => f4(x),
                _ => String::new(),
            }
        }
        Term::Call(name, args, _) => {
            let parts: Vec<String> = args.iter().map(expr_raw).collect();
            format!("{}({})", name, parts.join(", "))
        }
        Term::Tagged(t, _, _) => term_text(t, vars),
    }
}

fn expr_raw(e: &Expr) -> String {
    match e {
        Expr::Num(v, _) => f4(*v),
        Expr::Percent(v, _) => format!("{}%", f4(*v)),
        Expr::Ident(n, _) => n.clone(),
        Expr::Str(s, _) => format!("\"{}\"", s),
        Expr::Var(v, _) => format!("var(--lini-{})", v),
        Expr::Hash(h, _) => format!("#{}", h),
        Expr::Unary(op, a, _) => format!("{}{}", op, expr_raw(a)),
        Expr::Call(n, items, _) if n == crate::parser::RUN => items.iter().map(expr_raw).collect::<Vec<_>>().join(" "),
        Expr::Call(n, items, _) => format!("{}({})", n, items.iter().map(expr_raw).collect::<Vec<_>>().join(", ")),
        _ => String::new(),
    }
}

// A whole value as CSS: terms space-joined, groups comma-joined, a
// gradient as its paint server.
pub fn value_text(v: &crate::ast::Value, vars: &mut Vec<String>) -> String {
    use crate::ast::Term;
    v.groups
        .iter()
        .map(|g| {
            g.iter()
                .map(|t| match t {
                    Term::Call(name, args, sp) if is_gradient(name) => gradient_css(name, args, vars, *sp).unwrap_or_default(),
                    _ => term_text(t, vars),
                })
                .collect::<Vec<_>>()
                .join(" ")
        })
        .collect::<Vec<_>>()
        .join(", ")
}

// A whole value as written (a gradient as its call text).
pub fn value_raw(v: &crate::ast::Value, vars: &mut Vec<String>) -> String {
    v.groups.iter().map(|g| g.iter().map(|t| term_text(t, vars)).collect::<Vec<_>>().join(" ")).collect::<Vec<_>>().join(", ")
}

// A single bare word or variable, as CSS text (values a property passes
// through without checking).
pub fn word_css(v: &crate::ast::Value, vars: &mut Vec<String>) -> Option<String> {
    use crate::ast::Term;
    match crate::style::single_term(v)? {
        Term::Ident(s, _) => Some(s.clone()),
        Term::Var(n, _) => {
            crate::style::use_var(vars, n);
            Some(format!("var(--lini-{})", n))
        }
        _ => None,
    }
}

// A gradient written in any other property still resolves (and so gets
// its def): register those of every node's cascade.
pub fn register_stray(ctx: &crate::compile::Ctx) {
    use crate::ast::Term;
    for n in ctx.nodes.iter().skip(1) {
        let (_, props) = crate::compile::cascade(&ctx.sheet, n);
        for (k, v) in &props {
            // paint resolves on its own; list properties read keywords and sizes
            if matches!(k.as_str(), "fill" | "stroke" | "color" | "align" | "along" | "columns" | "justify" | "rows") {
                continue;
            }
            for t in v.groups.iter().flat_map(|g| g.iter()) {
                if let Term::Call(name, args, sp) = t {
                    if is_gradient(name) {
                        let _ = gradient_css(name, args, &mut Vec::new(), *sp);
                    }
                }
            }
        }
    }
}

// (links' own styles)
pub fn register_stray_links(ctx: &crate::compile::Ctx) {
    use crate::ast::Term;
    for l in &ctx.links {
        for d in &l.style {
            if matches!(d.name.as_str(), "stroke" | "align" | "along" | "columns" | "justify" | "rows") {
                continue;
            }
            for t in d.value.groups.iter().flat_map(|g| g.iter()) {
                if let Term::Call(name, args, sp) = t {
                    if is_gradient(name) {
                        let _ = gradient_css(name, args, &mut Vec::new(), *sp);
                    }
                }
            }
        }
    }
}

// Paint servers register as the reference meets them: drawing the scene
// (each node's cascaded fill then stroke, in paint order; then each link's
// stroke), then the drawn types' rules in stylesheet order, then every other
// rule in source order (classes, worn or not, and link rules), then the
// canvas. The defs keep that order; whatever registers later appends.
fn meet(v: Option<&crate::ast::Value>) {
    use crate::ast::Term;
    let Some(v) = v else { return };
    for t in v.groups.iter().flat_map(|g| g.iter()) {
        if let Term::Call(name, args, sp) = t {
            if is_gradient(name) {
                let _ = gradient_css(name, args, &mut Vec::new(), *sp);
            }
        }
    }
}

// Run `f` without keeping the paint servers it registers (a comparison
// that must not move a gradient ahead of where the reference meets it).
pub fn dry<T>(f: impl FnOnce() -> T) -> T {
    let n = GRADIENTS.with(|g| g.borrow().len());
    let r = f();
    GRADIENTS.with(|g| g.borrow_mut().truncate(n));
    r
}

// (a rule's last fill, then its last stroke)
fn meet_decls(decls: &[crate::ast::Decl]) {
    for k in ["fill", "stroke"] {
        meet(decls.iter().rev().find(|d| d.name == k).map(|d| &d.value));
    }
}

pub fn meet_node(ctx: &crate::compile::Ctx, i: usize) {
    let n = &ctx.nodes[i];
    meet(n.props.get("fill"));
    meet(n.props.get("stroke"));
}

// A link's cascaded stroke: link rules, scoped link rules, its classes, its own.
pub fn meet_link(ctx: &crate::compile::Ctx, l: &crate::scene::Link) {
    let mut stroke: Option<crate::ast::Value> = ctx.sheet.link_rules.iter().rev().find(|d| d.name == "stroke").map(|d| d.value.clone());
    for (k, v) in crate::scoped::link_decls(ctx, l) {
        if k == "stroke" {
            stroke = Some(v);
        }
    }
    for cr in ctx.sheet.worn(&l.classes) {
        if let Some(d) = cr.decls.iter().rev().find(|d| d.name == "stroke") {
            stroke = Some(d.value.clone());
        }
    }
    if let Some(d) = l.style.iter().rev().find(|d| d.name == "stroke") {
        stroke = Some(d.value.clone());
    }
    meet(stroke.as_ref());
}

// The rules, once the scene is drawn: `types` are the drawn types in
// stylesheet order.
pub fn meet_rules(ctx: &crate::compile::Ctx, types: &[String]) {
    let sheet = &ctx.sheet;
    for t in types {
        let mut ds: Vec<crate::ast::Decl> = Vec::new();
        if let Some(df) = sheet.define(t) {
            ds.extend(df.decls.iter().cloned());
        }
        ds.extend(sheet.type_rule(t).iter().map(|d| (*d).clone()));
        meet_decls(&ds);
    }
    // classes and link rules, by where they are written
    let mut rest: Vec<(usize, Vec<crate::ast::Decl>)> = sheet.classes.iter().map(|c| (c.span.start, c.decls.clone())).collect();
    for d in &sheet.link_rules {
        rest.push((d.span.start, vec![d.clone()]));
    }
    rest.sort_by_key(|(p, _)| *p);
    for (_, ds) in &rest {
        meet_decls(ds);
    }
    meet_decls(&sheet.root);
}

// Every variable the registered gradients read.
pub fn vars() -> Vec<String> {
    GRADIENTS.with(|g| g.borrow().iter().flat_map(|x| x.vars.clone()).collect())
}
