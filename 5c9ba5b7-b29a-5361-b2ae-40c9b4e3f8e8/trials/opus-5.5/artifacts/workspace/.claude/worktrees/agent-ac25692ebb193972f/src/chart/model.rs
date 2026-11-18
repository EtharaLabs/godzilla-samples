// Chart model: the chart node, its axes and series, read from the cascaded
// properties of the node tree.

use crate::ast::{Decl, Term, Value};
use crate::compile::Ctx;
use crate::diag::{Diag, Span};
use crate::types::Prim;

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Kind {
    Bars,
    Line,
    Area,
    Dots,
    Bubble,
}

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Dir {
    Column,
    Row,
    Radial,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Fmt {
    Auto,
    Decimal(usize),
    Significant(usize),
    Scientific(usize),
    Engineering(usize),
    Percent(usize),
    Fraction(u64),
    Date(String),
}

#[derive(Clone, Debug)]
pub enum StepSpec {
    Num(f64),
    Cal(i64, String),
}

#[derive(Clone, Debug)]
pub struct Axis {
    pub node: usize,
    pub node_span: Span,
    pub id: Option<String>,
    pub title: Option<String>,
    pub side: Option<String>,
    pub range: Option<(f64, f64)>,
    pub range_time: bool,
    pub step: Option<StepSpec>,
    pub ticks: Option<Vec<f64>>,
    pub ticks_none: bool,
    pub gridlines: bool,
    pub unit: String,
    pub format: Option<Fmt>,
    pub log: bool,
    pub scale_time: bool,
    pub ticks_time: bool,
}

#[derive(Clone, Debug)]
pub struct Series {
    pub node: usize,
    pub kind: Kind,
    pub name: Option<String>,
    pub index: usize,
    // category data (one value per category)
    pub vals: Vec<f64>,
    // point data
    pub pts: Vec<(f64, f64)>,
    pub points: bool,
    pub time_x: bool,
    pub fns: Vec<Term>,
    pub labels: Vec<String>,
    pub fill: Option<Value>,
    pub stroke: Option<Value>,
    pub stroke_width: Option<f64>,
    pub stroke_style: Option<String>,
    pub axis: Option<String>,
    pub curve: String,
    pub marker: Option<String>,
    pub baseline: Option<f64>,
    pub at: Option<(f64, f64)>,
    pub value: Option<f64>,
    pub tooltip: Option<String>,
    pub span: Span,
}

#[derive(Clone, Debug)]
pub struct Band {
    pub node: usize,
    pub name: Option<String>,
    pub range: (f64, f64),
    pub axis: Option<String>,
    pub fill: Option<Value>,
    pub time: bool,
}

#[derive(Clone, Debug)]
#[allow(dead_code)]
pub struct Mark {
    pub node: usize,
    pub name: Option<String>,
    pub at: Vec<f64>,
    pub axis: Option<String>,
    pub stroke: Option<Value>,
    pub color: Option<Value>,
    pub stroke_style: Option<String>,
    pub stroke_width: Option<f64>,
    pub time: bool,
}

#[derive(Clone, Debug)]
#[allow(dead_code)]
pub struct Slice {
    pub node: usize,
    pub name: Option<String>,
    pub value: f64,
    pub fill: Option<Value>,
    pub stroke: Option<Value>,
    pub stroke_width: Option<f64>,
}

#[derive(Clone, Debug)]
pub struct Chart {
    pub node: usize,
    pub pie: bool,
    pub dir: Dir,
    pub categories: Option<Vec<String>>,
    pub bars_mode: String,
    pub tooltip: String,
    pub format: Option<Fmt>,
    pub clearance: f64,
    pub gap: f64,
    pub samples: usize,
    pub hole: f64,
    pub title: Option<String>,
    pub axes: Vec<Axis>,
    pub series: Vec<Series>,
    pub bands: Vec<Band>,
    pub marks: Vec<Mark>,
    pub slices: Vec<Slice>,
}

// The user-written declarations of a node: type rules, classes, id rules and
// inline style, without the built-in type defaults.
pub fn user_props(ctx: &Ctx, n: usize) -> Vec<(String, Value)> {
    let sheet = &ctx.sheet;
    let node = &ctx.nodes[n];
    let mut props: Vec<(String, Value)> = Vec::new();
    fn set(props: &mut Vec<(String, Value)>, d: &Decl) {
        if let Some(e) = props.iter_mut().find(|e| e.0 == d.name) {
            e.1 = d.value.clone();
        } else {
            props.push((d.name.clone(), d.value.clone()));
        }
    }
    for t in node.chain.iter().rev() {
        if let Some(df) = sheet.define(t) {
            for d in &df.decls {
                set(&mut props, d);
            }
        }
        for d in sheet.type_rule(t) {
            set(&mut props, d);
        }
    }
    for c in &node.classes {
        if let Some(cr) = sheet.class(c) {
            for d in &cr.decls {
                set(&mut props, d);
            }
        }
    }
    if let Some(id) = &node.id {
        for (rid, ds) in &sheet.id_rules {
            if rid == id {
                for d in ds {
                    set(&mut props, d);
                }
            }
        }
    }
    for d in &node.inline {
        set(&mut props, d);
    }
    props
}

pub fn get<'a>(p: &'a [(String, Value)], k: &str) -> Option<&'a Value> {
    p.iter().find(|e| e.0 == k).map(|e| &e.1)
}

pub fn ident(v: &Value) -> Option<String> {
    match crate::style::single_term(v) {
        Some(Term::Ident(s, _)) => Some(s.clone()),
        Some(Term::Str(s, _)) => Some(s.clone()),
        _ => None,
    }
}

pub fn num(ctx: &Ctx, v: &Value) -> Option<f64> {
    crate::style::value_num(&ctx.sheet.env, v)
}

pub fn term_num(ctx: &Ctx, t: &Term) -> Option<f64> {
    crate::style::term_num(&ctx.sheet.env, t)
}

// "YYYY-MM-DD", optionally "THH:MM[:SS]", optionally "Z" or "±HH:MM"
// → days since 1970-01-01 (UTC).
pub fn parse_date(s: &str) -> Option<f64> {
    let b = s.as_bytes();
    let num = |from: usize, to: usize| -> Option<i64> {
        if to > b.len() || !b[from..to].iter().all(|c| c.is_ascii_digit()) {
            return None;
        }
        s[from..to].parse().ok()
    };
    if b.len() < 10 || b[4] != b'-' || b[7] != b'-' {
        return None;
    }
    let (y, m, d) = (num(0, 4)?, num(5, 7)?, num(8, 10)?);
    if !(1..=12).contains(&m) {
        return None;
    }
    let leap = (y % 4 == 0 && y % 100 != 0) || y % 400 == 0;
    let dim = [31, if leap { 29 } else { 28 }, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][(m - 1) as usize];
    if d < 1 || d > dim {
        return None;
    }
    let mut i = 10;
    let mut secs: i64 = 0;
    if i < b.len() && b[i] == b'T' {
        if b.len() < i + 6 || b[i + 3] != b':' {
            return None;
        }
        let (hh, mm) = (num(i + 1, i + 3)?, num(i + 4, i + 6)?);
        if hh > 23 || mm > 59 {
            return None;
        }
        secs = hh * 3600 + mm * 60;
        i += 6;
        if i < b.len() && b[i] == b':' {
            let ss = num(i + 1, i + 3)?;
            if ss > 59 {
                return None;
            }
            secs += ss;
            i += 3;
        }
    }
    if i < b.len() {
        match b[i] {
            b'Z' => i += 1,
            b'+' | b'-' => {
                if b.len() < i + 6 || b[i + 3] != b':' {
                    return None;
                }
                let (oh, om) = (num(i + 1, i + 3)?, num(i + 4, i + 6)?);
                if oh > 23 || om > 59 {
                    return None;
                }
                let off = oh * 3600 + om * 60;
                if b[i] == b'+' {
                    secs -= off;
                } else {
                    secs += off;
                }
                i += 6;
            }
            _ => return None,
        }
    }
    if i != b.len() {
        return None;
    }
    if secs == 0 {
        return Some(days_from_civil(y, m, d) as f64);
    }
    if secs % 60 == 0 {
        // whole minutes keep the minute-based fraction
        return Some(days_from_civil(y, m, d) as f64 + (secs / 60) as f64 / 1440.0);
    }
    Some(days_from_civil(y, m, d) as f64 + secs as f64 / 86400.0)
}

pub fn date_err(lit: &str, span: Span) -> Diag {
    layout_err(&format!("'{}' is not a date — ISO-8601: '2026-01-31', optionally 'T09:30' and 'Z'", lit), span)
}

pub fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let mp = (m + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

pub fn civil_from_days(z: i64) -> (i64, i64, i64) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (if m <= 2 { y + 1 } else { y }, m, d)
}

// A number or a date literal.
fn term_val(ctx: &Ctx, t: &Term) -> Option<(f64, bool)> {
    match t {
        Term::Str(s, _) => parse_date(s).map(|d| (d, true)),
        _ => term_num(ctx, t).map(|x| (x, false)),
    }
}

const FMT_ERR: &str = "'format' takes auto, decimal N, significant N, scientific N, engineering N, percent N, fraction D, or a date preset";

pub(crate) fn parse_fmt(v: &Value, span: Span) -> Result<Fmt, Diag> {
    let bad = || layout_err(FMT_ERR, span);
    if v.groups.len() != 1 {
        return Err(bad());
    }
    let g = &v.groups[0];
    let name = match g.first() {
        Some(Term::Ident(s, _)) => s.clone(),
        _ => return Err(bad()),
    };
    let arg = match g.get(1) {
        Some(Term::Num(x, _, _)) => Some(*x),
        Some(_) => return Err(bad()),
        None => None,
    };
    if g.len() > 2 {
        return Err(bad());
    }
    let digits = |label: &str, what: &str, lo: f64| -> Result<usize, Diag> {
        match arg {
            Some(x) if x.fract() == 0.0 && x >= lo && x <= 12.0 => Ok(x as usize),
            Some(_) => Err(layout_err(&format!("'format: {} N' takes {}..12 {}", label, lo as i64, what), span)),
            None => Err(bad()),
        }
    };
    match name.as_str() {
        "auto" if arg.is_none() => Ok(Fmt::Auto),
        "decimal" => Ok(Fmt::Decimal(digits("decimal", "decimals", 0.0)?)),
        "significant" => Ok(Fmt::Significant(digits("significant", "digits", 1.0)?)),
        "scientific" => Ok(Fmt::Scientific(digits("scientific", "decimals", 0.0)?)),
        "engineering" => Ok(Fmt::Engineering(digits("engineering", "decimals", 0.0)?)),
        "percent" => Ok(Fmt::Percent(digits("percent", "decimals", 0.0)?)),
        "fraction" => match arg {
            Some(x) if x.fract() == 0.0 && (2.0..=1024.0).contains(&x) => Ok(Fmt::Fraction(x as u64)),
            Some(_) => Err(layout_err("'format: fraction D' takes a whole denominator 2..1024", span)),
            None => Err(bad()),
        },
        "year" | "month" | "day" | "hour" | "minute" if arg.is_none() => Ok(Fmt::Date(name)),
        _ => Err(bad()),
    }
}

fn texts_of(ctx: &Ctx, n: usize) -> Option<String> {
    if let Some(l) = &ctx.nodes[n].label {
        return Some(l.clone());
    }
    for &c in &ctx.nodes[n].children {
        if ctx.nodes[c].prim == Prim::Text {
            return ctx.nodes[c].text.clone();
        }
    }
    None
}

fn strings(v: &Value) -> Vec<String> {
    let mut out = Vec::new();
    for g in &v.groups {
        let mut parts = Vec::new();
        for t in g {
            match t {
                Term::Str(s, _) | Term::Ident(s, _) => parts.push(s.clone()),
                Term::Num(_, raw, _) => parts.push(raw.clone()),
                _ => {}
            }
        }
        out.push(parts.join(" "));
    }
    out
}

fn layout_err(msg: &str, span: Span) -> Diag {
    Diag::error("layout", msg, span)
}

fn data_err(msg: &str, span: Span) -> Diag {
    Diag::error("chart-data", msg, span)
}


pub fn build(ctx: &Ctx, i: usize) -> Result<Chart, Diag> {
    let pie = ctx.comp[i].layout == "pie";
    let node = &ctx.nodes[i];
    let props: Vec<(String, Value)> = node.props.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
    let p = |k: &str| get(&props, k);
    let nospan = Span::default();
    let dir = match p("direction").and_then(ident).as_deref() {
        None | Some("column") => Dir::Column,
        Some("row") => Dir::Row,
        Some("radial") => Dir::Radial,
        Some(_) => return Err(layout_err("'direction' is column, row, or radial", nospan)),
    };
    let bars_mode = match p("bars").and_then(ident) {
        None => "grouped".to_string(),
        Some(s) if s == "grouped" || s == "stacked" || s == "overlay" => s,
        Some(_) => return Err(layout_err("'bars' is grouped, stacked, or overlay", nospan)),
    };
    let tooltip = match p("tooltip").and_then(ident) {
        None => "auto".to_string(),
        Some(s) if s == "none" || s == "hover" || s == "auto" || s == "always" => s,
        Some(_) => return Err(layout_err("'tooltip' is none, hover, auto, or always", nospan)),
    };
    let categories = match p("categories") {
        Some(v) => {
            if v.groups.iter().any(|g| g.len() != 1 || matches!(g[0], Term::Num(..))) {
                return Err(layout_err("'categories' takes comma-separated quoted strings — 'categories: \"a\", \"b\"'", node.span));
            }
            Some(strings(v))
        }
        None => None,
    };
    let format = match p("format") {
        Some(v) => Some(parse_fmt(v, ctx.nodes[i].span)?),
        None => None,
    };
    let clearance = p("clearance").and_then(|v| num(ctx, v)).unwrap_or(6.0);
    let gap = ctx.comp[i].gap.0;
    // fewer than two samples falls back to the default 24
    let samples = p("samples").and_then(|v| num(ctx, v)).filter(|x| *x >= 2.0).map(|x| x as usize).unwrap_or(24);
    let hole = match p("hole").and_then(|v| num(ctx, v)) {
        Some(h) => {
            if !(0.0..1.0).contains(&h) {
                return Err(layout_err("'hole' is a fraction 0..1", nospan));
            }
            h
        }
        None => 0.0,
    };
    let mut ch = Chart {
        node: i,
        pie,
        dir,
        categories,
        bars_mode,
        tooltip,
        format,
        clearance,
        gap,
        samples,
        hole,
        title: None,
        axes: vec![],
        series: vec![],
        bands: vec![],
        marks: vec![],
        slices: vec![],
    };
    let mut sidx = 0;
    // bubbles walk the palette on their own
    let mut bidx = 0;
    let children = node.children.clone();
    for &c in &children {
        let cn = &ctx.nodes[c];
        if cn.prim == Prim::Text {
            if ch.title.is_none() {
                ch.title = cn.text.clone();
            }
            continue;
        }
        let up = user_props(ctx, c);
        let u = |k: &str| get(&up, k).or_else(|| ctx.nodes[c].props.get(k));
        let name = texts_of(ctx, c);
        if pie {
            if !cn.is("slice") {
                return Err(layout_err("a pie's children are '|slice|' only", cn.span));
            }
            let value = match u("value").and_then(|v| num(ctx, v)) {
                Some(v) => v,
                None => return Err(layout_err("a '|slice|' needs a 'value:'", cn.span)),
            };
            if value < 0.0 {
                return Err(layout_err("a '|slice|' value must be ≥ 0", cn.span));
            }
            ch.slices.push(Slice {
                node: c,
                name,
                value,
                fill: get(&up, "fill").cloned(),
                stroke: get(&up, "stroke").cloned(),
                stroke_width: get(&up, "stroke-width").and_then(|v| num(ctx, v)),
            });
            continue;
        }
        if cn.is("slice") {
            return Err(Diag::error("chart-type", "'|slice|' belongs in a 'layout: pie'", cn.span));
        }
        if cn.is("axis") {
            let side = u("side").and_then(ident);
            if let Some(s) = &side {
                if !matches!(s.as_str(), "bottom" | "top" | "left" | "right") {
                    return Err(layout_err("'side' is bottom, top, left, or right", cn.span));
                }
            }
            let mut range = None;
            let mut range_time = false;
            if let Some(v) = u("range") {
                let ts: Vec<&Term> = v.groups.iter().flatten().collect();
                if ts.len() >= 2 {
                    if let (Some(a), Some(b)) = (term_val(ctx, ts[0]), term_val(ctx, ts[1])) {
                        range = Some((a.0, b.0));
                        range_time = a.1 || b.1;
                    }
                }
            }
            let step = u("step").and_then(|v| {
                let g = v.groups.first()?;
                match (g.first(), g.get(1)) {
                    (Some(Term::Ident(s, _)), None) => Some(StepSpec::Cal(1, s.clone())),
                    (Some(Term::Num(n, _, _)), Some(Term::Ident(s, _))) => Some(StepSpec::Cal(if n.fract() == 0.0 { *n as i64 } else { 0 }, s.clone())),
                    (Some(t), None) => term_num(ctx, t).map(StepSpec::Num),
                    _ => None,
                }
            });
            let ticks_none = false;
            let mut ticks_time = false;
            let ticks = match u("ticks") {
                Some(v) => {
                    let mut xs = Vec::new();
                    for g in &v.groups {
                        if g.len() != 1 {
                            return Err(layout_err("'ticks' takes comma-separated numbers — 'ticks: 0, 50, 100'", cn.span));
                        }
                        if let Term::Str(..) = &g[0] {
                            // a quoted tick reads as a date
                            ticks_time = true;
                            xs.push(term_val(ctx, &g[0]).map(|t| t.0).unwrap_or(f64::NAN));
                            continue;
                        }
                        match term_val(ctx, &g[0]) {
                            Some((x, _)) => xs.push(x),
                            None => return Err(layout_err("'ticks' takes comma-separated numbers — 'ticks: 0, 50, 100'", cn.span)),
                        }
                    }
                    Some(xs)
                }
                None => None,
            };
            let scale = u("scale").and_then(ident);
            if let Some(sc) = &scale {
                if !matches!(sc.as_str(), "linear" | "log" | "time") {
                    return Err(layout_err("'scale' is linear, log, or time", cn.span));
                }
            }
            let gridlines = u("gridlines").and_then(ident).as_deref() != Some("none");
            let unit = u("unit").and_then(ident).unwrap_or_default();
            let format = match u("format") {
                Some(v) => Some(parse_fmt(v, cn.span)?),
                None => None,
            };
            let log = scale.as_deref() == Some("log");
            let scale_time = scale.as_deref() == Some("time");
            ch.axes.push(Axis {
                node: c,
                node_span: cn.span,
                id: cn.id.clone(),
                title: name,
                side,
                range,
                range_time,
                step,
                ticks,
                ticks_none,
                gridlines,
                unit,
                format,
                log,
                scale_time,
                ticks_time,
            });
            continue;
        }
        if cn.is("band") {
            let mut range = (0.0, 0.0);
            let mut time = false;
            let mut ok = false;
            if let Some(v) = u("range") {
                let ts: Vec<&Term> = v.groups.iter().flatten().collect();
                if ts.len() == 2 {
                    if let (Some(a), Some(b)) = (term_val(ctx, ts[0]), term_val(ctx, ts[1])) {
                        range = (a.0, b.0);
                        time = a.1 || b.1;
                        ok = true;
                    }
                }
            }
            if !ok {
                return Err(layout_err("a '|band|' needs 'range: a b'", cn.span));
            }
            ch.bands.push(Band { node: c, name, range, axis: u("axis").and_then(ident), fill: get(&up, "fill").cloned(), time });
            continue;
        }
        if cn.is("mark") {
            let mut at = Vec::new();
            let mut time = false;
            if let Some(v) = u("at") {
                for t in v.groups.iter().flatten() {
                    match term_val(ctx, t) {
                        Some((x, tm)) => {
                            if at.is_empty() {
                                time = tm;
                            }
                            at.push(x);
                        }
                        None => at.push(f64::NAN),
                    }
                }
            }
            let axis = u("axis").and_then(ident);
            if axis.is_none() {
                return Err(layout_err("a '|mark|' needs 'axis:' to place it", cn.span));
            }
            if at.is_empty() || at.len() > 2 || at.iter().any(|x| x.is_nan()) {
                return Err(layout_err("'at' takes one value (a line) or two (a point)", cn.span));
            }
            ch.marks.push(Mark {
                node: c,
                name,
                at,
                axis,
                stroke: get(&up, "stroke").cloned(),
                color: get(&up, "color").cloned(),
                stroke_style: get(&up, "stroke-style").and_then(ident),
                stroke_width: get(&up, "stroke-width").and_then(|v| num(ctx, v)),
                time,
            });
            continue;
        }
        let kind = if cn.is("bars") {
            Kind::Bars
        } else if cn.is("area") {
            Kind::Area
        } else if cn.is("dots") {
            Kind::Dots
        } else if cn.is("bubble") {
            Kind::Bubble
        } else if cn.is("line") {
            Kind::Line
        } else {
            return Err(layout_err("a chart's children are series (e.g. '|bars|', '|line|') and '|axis|'", cn.span));
        };
        let mut s = Series {
            node: c,
            kind,
            name,
            index: if kind == Kind::Bubble { bidx } else { sidx },
            vals: vec![],
            pts: vec![],
            points: false,
            time_x: false,
            fns: vec![],
            labels: vec![],
            fill: get(&up, "fill").cloned(),
            stroke: get(&up, "stroke").cloned(),
            stroke_width: get(&up, "stroke-width").and_then(|v| num(ctx, v)),
            stroke_style: get(&up, "stroke-style").and_then(ident),
            axis: u("axis").and_then(ident),
            curve: "linear".into(),
            marker: None,
            baseline: u("baseline").and_then(|v| num(ctx, v)),
            at: None,
            value: u("value").and_then(|v| num(ctx, v)),
            tooltip: u("tooltip").and_then(ident),
            span: cn.span,
        };
        if kind == Kind::Bubble {
            bidx += 1;
        } else {
            sidx += 1;
        }
        if let Some(v) = u("curve").and_then(ident) {
            if !matches!(v.as_str(), "linear" | "smooth" | "step") {
                return Err(layout_err("'curve' is linear, smooth, or step", nospan));
            }
            s.curve = v;
        }
        if let Some(mv) = get(&up, "marker") {
            let v = match crate::style::single_term(mv) {
                Some(Term::Ident(v, _)) => v.clone(),
                _ => return Err(Diag::error("resolve", "marker requires an identifier value", cn.span)),
            };
            match v.as_str() {
                "dot" | "circle" | "diamond" | "none" => {}
                // the ER glyphs and datum have a dot for their centred form
                "datum" | "one" | "exactly-one" | "zero-or-one" | "one-or-many" | "zero-or-many" => {}
                "arrow" | "crow" | "many" => {
                    let canon = if v == "many" { "crow" } else { v.as_str() };
                    return Err(Diag::error(
                        "layout",
                        &format!("'marker: {}' has no centred form on a chart — use dot, circle, or diamond", canon),
                        cn.span,
                    ));
                }
                _ => return Err(Diag::error("resolve", &format!("invalid marker value '{}'", v), cn.span)),
            }
            match v.as_str() {
                "none" => {}
                "dot" | "circle" | "diamond" => s.marker = Some(v),
                _ => s.marker = Some("dot".into()),
            }
        }
        if kind == Kind::Bubble {
            if let Some(v) = u("at") {
                let ts: Vec<&Term> = v.groups.iter().flatten().collect();
                if ts.len() == 2 {
                    if let (Some(a), Some(b)) = (term_val(ctx, ts[0]), term_val(ctx, ts[1])) {
                        s.at = Some((a.0, b.0));
                        s.time_x = a.1;
                    }
                }
            }
            if s.at.is_none() || s.value.is_none() {
                return Err(layout_err("a '|bubble|' needs 'at:' (x y) and 'value:'", cn.span));
            }
        } else {
            let data = u("data");
            let fnv = u("fn");
            if data.is_some() && fnv.is_some() {
                return Err(data_err("a series takes 'data' or 'fn', not both", cn.span));
            }
            if let Some(v) = fnv {
                for g in &v.groups {
                    if let Some(t) = g.first() {
                        s.fns.push(t.clone());
                    }
                }
            } else if let Some(v) = data {
                let pairs = v.groups.iter().any(|g| g.len() >= 2);
                if pairs || v.groups.iter().any(|g| matches!(g.first(), Some(Term::Str(..)))) {
                    let (mut dates, mut nums) = (false, false);
                    for g in &v.groups {
                        if g.len() != 2 {
                            return Err(data_err("point data is 'x y' pairs", cn.span));
                        }
                        for t in g.iter() {
                            if let Term::Str(lit, _) = t {
                                if parse_date(lit).is_none() {
                                    return Err(date_err(lit, cn.span));
                                }
                            }
                        }
                        let a = term_val(ctx, &g[0]);
                        let b = term_val(ctx, &g[1]);
                        match (a, b) {
                            (Some(a), Some(b)) => {
                                if a.1 {
                                    dates = true;
                                } else {
                                    nums = true;
                                }
                                s.time_x = s.time_x || a.1;
                                s.pts.push((a.0, b.0));
                            }
                            _ => return Err(data_err("point data is 'x y' pairs", cn.span)),
                        }
                    }
                    if dates && nums {
                        return Err(data_err("'data' mixes dates and numbers — one domain, one kind", cn.span));
                    }
                    if kind == Kind::Bars {
                        return Err(data_err("'|bars|' takes categorical data ('data: 9, 15, 24'), not 'x y' points", cn.span));
                    }
                    s.points = true;
                } else {
                    for g in &v.groups {
                        match g.first().and_then(|t| term_num(ctx, t)) {
                            Some(x) => s.vals.push(x),
                            None => return Err(data_err("point data is 'x y' pairs", cn.span)),
                        }
                    }
                }
            } else {
                return Err(data_err("a series needs 'data' or 'fn'", cn.span));
            }
        }
        if let Some(v) = u("labels") {
            if !s.fns.is_empty() {
                return Err(layout_err("'labels' needs explicit 'data' — a sampled 'fn' has no points to label", cn.span));
            }
            s.labels = strings(v);
        }
        ch.series.push(s);
    }
    if pie {
        if ch.slices.is_empty() {
            return Err(layout_err("a pie needs at least one '|slice|'", ctx.nodes[i].span));
        }
        if ch.slices.iter().map(|s| s.value).sum::<f64>() == 0.0 {
            return Err(layout_err("a pie's slice values sum to zero", ctx.nodes[i].span));
        }
    } else if ch.series.is_empty() {
        return Err(layout_err("a chart needs at least one series", ctx.nodes[i].span));
    }
    // category / data consistency
    if !pie {
        for s in &ch.series {
            if s.kind == Kind::Bubble {
                continue;
            }
            if let Some(cats) = &ch.categories {
                if s.points || !s.fns.is_empty() {
                    return Err(layout_err("point / formula data needs a numeric x axis, not 'categories'", s.span));
                }
                if s.vals.len() != cats.len() {
                    return Err(layout_err(
                        &format!("series data has {} values but the chart has {} categories", s.vals.len(), cats.len()),
                        s.span,
                    ));
                }
            }
            let n = if s.points { s.pts.len() } else { s.vals.len() };
            if !s.labels.is_empty() && s.fns.is_empty() && s.labels.len() != n {
                return Err(data_err(
                    &format!("'labels' has {} entries but the series has {} data points", s.labels.len(), n),
                    s.span,
                ));
            }
        }
        // a series reads a value axis; a band or mark may sit on either
        let horiz = ch.dir == Dir::Row;
        let radial = ch.dir == Dir::Radial;
        let is_cross = |a: &Axis| -> bool {
            if radial {
                return false;
            }
            match a.side.as_deref() {
                Some("bottom") | Some("top") => !horiz,
                Some("left") | Some("right") => horiz,
                _ => false,
            }
        };
        let mut errs: Vec<(usize, Diag)> = Vec::new();
        for s in &ch.series {
            if let Some(a) = &s.axis {
                if !ch.axes.iter().any(|x| x.id.as_deref() == Some(a.as_str()) && !is_cross(x)) {
                    errs.push((s.span.start, layout_err(&format!("axis '{}' not found", a), s.span)));
                }
            }
        }
        let refs = ch.bands.iter().map(|b| (b.node, b.axis.clone())).chain(ch.marks.iter().map(|m| (m.node, m.axis.clone())));
        for (node, axis) in refs {
            if let Some(a) = axis {
                if !ch.axes.iter().any(|x| x.id.as_deref() == Some(a.as_str())) {
                    let sp = ctx.nodes[node].span;
                    errs.push((sp.start, layout_err(&format!("axis '{}' not found", a), sp)));
                }
            }
        }
        if let Some((_, e)) = errs.into_iter().min_by_key(|e| e.0) {
            return Err(e);
        }
    }
    Ok(ch)
}
