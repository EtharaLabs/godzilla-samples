// Style values: cascade, inheritance, and CSS serialisation.

use crate::ast::{Decl, Expr, Term, Value};
use crate::diag::{Diag, Span};
use crate::eval::{Env, EV};
use crate::util::f4;
use std::collections::HashMap;

// CSS properties in the order they are serialised.
pub const CSS_ORDER: &[&str] = &[
    "fill",
    "stroke",
    "stroke-width",
    "opacity",
    "color",
    "font-family",
    "font-size",
    "font-weight",
    "font-style",
    "text-decoration",
    "text-shadow",
    "stroke-style",
];

pub const INHERITED: &[&str] = &[
    "font-size",
    "font-weight",
    "font-family",
    "font-style",
    "color",
    "letter-spacing",
    "line-spacing",
    "text-transform",
    "text-decoration",
    "text-shadow",
];

pub fn parse_decls(src: &'static str) -> Vec<Decl> {
    let full = format!("{{{}}}", src);
    let lexed = crate::lexer::lex(&full).expect("defaults lex");
    let mut p = crate::parser::Parser::new(&lexed.tokens, &full);
    let (decls, _) = p.parse_style_block().expect("defaults parse");
    decls
}

static DEFAULTS_CACHE: std::sync::OnceLock<HashMap<&'static str, Vec<Decl>>> = std::sync::OnceLock::new();

pub fn type_defaults(name: &str) -> &'static [Decl] {
    let m = DEFAULTS_CACHE.get_or_init(|| {
        let mut m = HashMap::new();
        for t in crate::types::TYPES {
            m.insert(t.name, parse_decls(t.defaults));
        }
        // the schematic lowering's internal classes (src/schematic.rs)
        for (name, text) in crate::schematic::CLASS_DEFAULTS {
            m.entry(*name).or_insert_with(|| parse_decls(text));
        }
        m
    });
    match m.get(name) {
        Some(v) => v,
        None => &[],
    }
}

// --------------------------------------------------------------- values

pub fn single_term(v: &Value) -> Option<&Term> {
    if v.groups.len() == 1 && v.groups[0].len() == 1 {
        Some(&v.groups[0][0])
    } else {
        None
    }
}

pub fn ident_of(v: &Value) -> Option<&str> {
    match single_term(v) {
        Some(Term::Ident(s, _)) => Some(s.as_str()),
        _ => None,
    }
}

pub fn term_num(env: &Env, t: &Term) -> Option<f64> {
    match t {
        Term::Num(v, _, _) => Some(*v),
        Term::Group(e, _) => env.eval(e, &HashMap::new()).ok().and_then(|x| x.num()),
        Term::Call(..) => env.eval_term(t, &HashMap::new()).ok().and_then(|x| x.num()),
        Term::Ident(n, _) => match env.vars.get(n) {
            Some(EV::Num(v)) => Some(*v),
            _ => None,
        },
        _ => None,
    }
}

pub fn value_nums(env: &Env, v: &Value) -> Vec<f64> {
    let mut out = Vec::new();
    for g in &v.groups {
        for t in g {
            if let Some(x) = term_num(env, t) {
                out.push(x);
            }
        }
    }
    out
}

pub fn value_num(env: &Env, v: &Value) -> Option<f64> {
    single_term(v).and_then(|t| term_num(env, t))
}

// ---------------------------------------------------------------- colour

pub const NAMED_COLORS: &[&str] = &[
    "aliceblue", "antiquewhite", "aqua", "aquamarine", "azure", "beige", "bisque", "black", "blanchedalmond", "blue",
    "blueviolet", "brown", "burlywood", "cadetblue", "chartreuse", "chocolate", "coral", "cornflowerblue", "cornsilk",
    "crimson", "cyan", "darkblue", "darkcyan", "darkgoldenrod", "darkgray", "darkgreen", "darkgrey", "darkkhaki",
    "darkmagenta", "darkolivegreen", "darkorange", "darkorchid", "darkred", "darksalmon", "darkseagreen",
    "darkslateblue", "darkslategray", "darkslategrey", "darkturquoise", "darkviolet", "deeppink", "deepskyblue",
    "dimgray", "dimgrey", "dodgerblue", "firebrick", "floralwhite", "forestgreen", "fuchsia", "gainsboro",
    "ghostwhite", "gold", "goldenrod", "gray", "green", "greenyellow", "grey", "honeydew", "hotpink", "indianred",
    "indigo", "ivory", "khaki", "lavender", "lavenderblush", "lawngreen", "lemonchiffon", "lightblue", "lightcoral",
    "lightcyan", "lightgoldenrodyellow", "lightgray", "lightgreen", "lightgrey", "lightpink", "lightsalmon",
    "lightseagreen", "lightskyblue", "lightslategray", "lightslategrey", "lightsteelblue", "lightyellow", "lime",
    "limegreen", "linen", "magenta", "maroon", "mediumaquamarine", "mediumblue", "mediumorchid", "mediumpurple",
    "mediumseagreen", "mediumslateblue", "mediumspringgreen", "mediumturquoise", "mediumvioletred", "midnightblue",
    "mintcream", "mistyrose", "moccasin", "navajowhite", "navy", "oldlace", "olive", "olivedrab", "orange",
    "orangered", "orchid", "palegoldenrod", "palegreen", "paleturquoise", "palevioletred", "papayawhip",
    "peachpuff", "peru", "pink", "plum", "powderblue", "purple", "rebeccapurple", "red", "rosybrown", "royalblue",
    "saddlebrown", "salmon", "sandybrown", "seagreen", "seashell", "sienna", "silver", "skyblue", "slateblue",
    "slategray", "slategrey", "snow", "springgreen", "steelblue", "tan", "teal", "thistle", "tomato", "turquoise",
    "violet", "wheat", "white", "whitesmoke", "yellow", "yellowgreen", "transparent", "currentcolor", "none", "auto",
];

pub fn is_named_color(s: &str) -> bool {
    let l = s.to_ascii_lowercase();
    NAMED_COLORS.contains(&l.as_str())
}

pub fn valid_hex(h: &str) -> bool {
    matches!(h.len(), 3 | 4 | 6 | 8) && h.chars().all(|c| c.is_ascii_hexdigit())
}

// Serialise an expression argument of a colour function.
fn expr_text(e: &Expr) -> String {
    match e {
        Expr::Num(v, _) => f4(*v),
        Expr::Percent(v, _) => format!("{}%", f4(*v)),
        Expr::Ident(n, _) => n.clone(),
        Expr::Unary(op, a, _) => format!("{}{}", op, expr_text(a)),
        _ => String::new(),
    }
}

pub struct CssCtx<'a> {
    pub env: &'a Env,
    pub vars_used: &'a mut Vec<String>,
}

pub fn use_var(vars_used: &mut Vec<String>, name: &str) {
    if !vars_used.iter().any(|v| v == name) {
        vars_used.push(name.to_string());
    }
}

// A colour term → CSS text. Errors carry the declaration span.
pub fn color_css(t: &Term, vars_used: &mut Vec<String>, span: Span) -> Result<String, Diag> {
    match t {
        Term::Var(v, _) => {
            use_var(vars_used, v);
            Ok(format!("var(--lini-{})", v))
        }
        Term::Hash(h, sp) => {
            if !valid_hex(h) {
                return Err(Diag::error("parse", &format!("invalid hex color '#{}'", h), *sp));
            }
            Ok(format!("#{}", h))
        }
        Term::Ident(n, _) => {
            if is_named_color(n) {
                Ok(n.clone())
            } else {
                Err(Diag::error("invalid-color", &format!("invalid color '{}'", n), span))
            }
        }
        Term::Str(s, _) => Ok(format!("\"{}\"", s)),
        Term::Call(name, args, _) => match name.as_str() {
            "rgb" | "rgba" | "hsl" | "hsla" => {
                let parts: Vec<String> = args.iter().map(expr_text).collect();
                Ok(format!("{}({})", name, parts.join(", ")))
            }
            "oklch" => {
                let nums: Vec<f64> = args
                    .iter()
                    .map(|a| match a {
                        Expr::Num(v, _) => *v,
                        Expr::Unary(o, b, _) if o == "-" => match &**b {
                            Expr::Num(v, _) => -*v,
                            _ => f64::NAN,
                        },
                        _ => f64::NAN,
                    })
                    .collect();
                if (nums.len() != 3 && nums.len() != 4) || nums.iter().any(|x| x.is_nan()) {
                    return Err(Diag::error(
                        "malformed-value",
                        "oklch expects (L, C, H) or (L, C, H, A) — L and A in 0..1, C ≥ 0, H in degrees",
                        span,
                    ));
                }
                Ok(crate::color::oklch_hex(nums[0], nums[1], nums[2], nums.get(3).copied()))
            }
            _ => Err(Diag::error("invalid-color", &format!("invalid color '{}'", name), span)),
        },
        _ => Err(Diag::error("invalid-color", "invalid color", span)),
    }
}

pub fn weight_css(v: &Value, vars_used: &mut Vec<String>, span: Span) -> Result<String, Diag> {
    let bad = || {
        Diag::error(
            "malformed-value",
            "'font-weight' takes normal, medium, semibold, bold, or 400, 500, 600, 700",
            span,
        )
    };
    match single_term(v) {
        Some(Term::Ident(n, _)) => Ok(match n.as_str() {
            "normal" => "normal".into(),
            "bold" => "bold".into(),
            "medium" => "500".into(),
            "semibold" => "600".into(),
            "light" => "normal".into(),
            _ => return Err(bad()),
        }),
        Some(Term::Num(x, _, _)) => {
            if [400.0, 500.0, 600.0, 700.0].contains(x) {
                Ok(f4(*x))
            } else {
                Err(bad())
            }
        }
        Some(Term::Var(n, _)) => {
            use_var(vars_used, n);
            Ok(format!("var(--lini-{})", n))
        }
        _ => Err(bad()),
    }
}

// Numeric weight for metrics (vars resolve to their theme value).
pub fn weight_num(v: &Value) -> u32 {
    match single_term(v) {
        Some(Term::Ident(n, _)) => match n.as_str() {
            "bold" => 700,
            "semibold" => 600,
            "medium" => 500,
            _ => 400,
        },
        Some(Term::Num(x, _, _)) => *x as u32,
        Some(Term::Var(n, _)) => match n.as_str() {
            "caption-font-weight" | "link-font-weight" => 400,
            "font-weight" => 500,
            _ => 500,
        },
        _ => 500,
    }
}

pub fn dasharray(style: &str, sw: f64) -> Option<String> {
    match style {
        "solid" => Some("none".into()),
        "dashed" => Some(format!("{},{}", f4(2.0 * sw + 3.0), f4(1.5 * sw + 2.5))),
        "dotted" => Some(format!("{},{}", f4(sw), f4(1.5 * sw))),
        "center" => {
            let g = f4(1.5 * sw + 1.5);
            Some(format!("{},{},{},{}", f4(5.0 * sw + 5.0), g, f4(sw), g))
        }
        "phantom" => {
            let g = f4(1.5 * sw + 1.5);
            Some(format!("{},{},{},{},{},{}", f4(5.0 * sw + 5.0), g, f4(sw), g, f4(sw), g))
        }
        _ => None,
    }
}

pub fn text_shadow_css(env: &Env, v: &Value, vars_used: &mut Vec<String>, span: Span) -> Result<String, Diag> {
    let mut parts = Vec::new();
    for g in &v.groups {
        let mut gp = Vec::new();
        for t in g {
            match t {
                Term::Num(..) | Term::Group(..) => {
                    let x = term_num(env, t).unwrap_or(0.0);
                    gp.push(format!("{}px", f4(x)));
                }
                _ => gp.push(color_css(t, vars_used, span)?),
            }
        }
        parts.push(gp.join(" "));
    }
    Ok(parts.join(", "))
}

pub fn font_family_css(v: &Value) -> String {
    let mut parts = Vec::new();
    for g in &v.groups {
        let mut gp = Vec::new();
        for t in g {
            match t {
                Term::Str(s, _) => gp.push(format!("\"{}\"", s)),
                Term::Ident(s, _) => gp.push(s.clone()),
                _ => {}
            }
        }
        parts.push(gp.join(" "));
    }
    parts.join(", ")
}

pub fn family_of(v: &Value) -> crate::font::Family {
    let mut s = String::new();
    for g in &v.groups {
        for t in g {
            match t {
                Term::Str(x, _) | Term::Ident(x, _) => {
                    s = x.to_ascii_lowercase();
                }
                _ => {}
            }
        }
        break;
    }
    if s.contains("mono") || s.contains("code") || s == "monospace" {
        crate::font::Family::Code
    } else {
        crate::font::Family::Sans
    }
}
