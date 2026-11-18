// Cartesian charts: a plot rectangle with value axes, a category or numeric
// x axis, and the series painted into it.

use super::model::*;
use super::scale::*;
use super::*;
use crate::ast::Term;
use crate::compile::Ctx;
use crate::diag::Diag;
use crate::eval::EV;

#[derive(Clone, Debug)]
pub struct VAxis {
    pub ax: Option<usize>, // index into ch.axes
    pub right: bool,       // right (column) / top (row) side
    pub lo: f64,
    pub hi: f64,
    pub log: bool,
    pub ticks: Vec<f64>,
    pub labels: Vec<String>,
    pub title: Option<String>,
    pub gridlines: bool,
}

impl VAxis {
    pub fn frac(&self, v: f64) -> f64 {
        if self.log {
            let a = self.lo.log10();
            let b = self.hi.log10();
            (v.max(1e-300).log10() - a) / (b - a)
        } else {
            (v - self.lo) / (self.hi - self.lo)
        }
    }
}

pub struct Geo {
    pub l: f64,
    pub r: f64,
    pub t: f64,
    pub b: f64,
    pub horiz: bool,
}

impl Geo {
    // position along the value direction
    pub fn vpos(&self, a: &VAxis, v: f64) -> f64 {
        let f = a.frac(v);
        if self.horiz {
            self.l + f * (self.r - self.l)
        } else {
            self.b - f * (self.b - self.t)
        }
    }
}

pub const CLIP_EPS: f64 = 1e-9;

pub fn eval_fn(ctx: &Ctx, t: &Term, x: f64, u: Option<f64>) -> Result<f64, Diag> {
    let mut locals = std::collections::HashMap::new();
    locals.insert("x".to_string(), EV::Num(x));
    if let Some(u) = u {
        locals.insert("u".to_string(), EV::Num(u));
    }
    let t = split_term(t);
    let r = ctx.sheet.env.eval_term(&t, &locals).map_err(|e| Diag::error("layout", &e.message, e.span))?;
    Ok(r.num().unwrap_or(0.0))
}

// In a formula `a-b` is a subtraction, never a hyphenated name.
fn split_term(t: &Term) -> Term {
    match t {
        Term::Group(e, s) => Term::Group(split_expr(e), *s),
        Term::Call(n, args, s) => Term::Call(n.clone(), args.iter().map(split_expr).collect(), *s),
        _ => t.clone(),
    }
}

fn split_expr(e: &crate::ast::Expr) -> crate::ast::Expr {
    use crate::ast::Expr;
    match e {
        Expr::Ident(n, s) if n.contains('-') && !n.starts_with('-') => {
            let mut parts: Vec<Expr> = Vec::new();
            let mut off = 0;
            for p in n.split('-') {
                let sp = crate::diag::Span::new(s.start + off, s.start + off + p.len());
                off += p.len() + 1;
                let pe = match p.parse::<f64>() {
                    Ok(v) if p.chars().next().map(|c| c.is_ascii_digit()).unwrap_or(false) => Expr::Num(v, sp),
                    _ => Expr::Ident(p.to_string(), sp),
                };
                parts.push(pe);
            }
            let mut it = parts.into_iter();
            let mut acc = it.next().unwrap();
            for p in it {
                acc = Expr::Bin("-".into(), Box::new(acc), Box::new(p), *s);
            }
            acc
        }
        Expr::Call(n, args, s) => Expr::Call(n.clone(), args.iter().map(split_expr).collect(), *s),
        Expr::Unary(o, a, s) => Expr::Unary(o.clone(), Box::new(split_expr(a)), *s),
        Expr::Bin(o, a, b, s) => Expr::Bin(o.clone(), Box::new(split_expr(a)), Box::new(split_expr(b)), *s),
        Expr::Ternary(a, b, c, s) => Expr::Ternary(Box::new(split_expr(a)), Box::new(split_expr(b)), Box::new(split_expr(c)), *s),
        Expr::Tuple(items, s) => Expr::Tuple(items.iter().map(split_expr).collect(), *s),
        Expr::Block(bs, body, s) => Expr::Block(bs.iter().map(|(n, x)| (n.clone(), split_expr(x))).collect(), Box::new(split_expr(body)), *s),
        _ => e.clone(),
    }
}

fn axis_labels(ax: Option<&Axis>, ch: &Chart, ticks: &[f64], step: f64, time: bool) -> Vec<String> {
    let unit = ax.map(|a| a.unit.clone()).unwrap_or_default();
    let fmt = ax.and_then(|a| a.format.clone()).or_else(|| ch.format.clone());
    ticks
        .iter()
        .map(|&v| {
            if time {
                fmt_month(v)
            } else {
                format!("{}{}", fmt_tick(v, step, fmt.as_ref()), unit)
            }
        })
        .collect()
}

// Domain and ticks of a value axis from the values it must show.
// Ticks on a log axis: 1-2-5 per decade over at most three decades, else decades.
pub fn log_ticks(lo: f64, hi: f64) -> Vec<f64> {
    let (a, b) = (lo.min(hi), lo.max(hi));
    let dec = (b / a).log10();
    let mut out = Vec::new();
    let e0 = a.log10().floor() as i32 - 1;
    let e1 = b.log10().ceil() as i32 + 1;
    for e in e0..=e1 {
        let ms: &[f64] = if dec <= 3.0 + 1e-9 { &[1.0, 2.0, 5.0] } else { &[1.0] };
        for &m in ms {
            let v = if e >= 0 { m * 10f64.powi(e) } else { m / 10f64.powi(-e) };
            if v >= a * (1.0 - 1e-9) && v <= b * (1.0 + 1e-9) {
                out.push(v);
            }
        }
    }
    out
}

// Log ticks for an axis `avail` px long: every 1-2-5 value when a label
// row (1.4 em) fits each, else the decades, else every k-th decade.
pub fn log_ticks_fit(lo: f64, hi: f64, avail: f64) -> Vec<f64> {
    let (a, b) = (lo.min(hi), lo.max(hi));
    let row = FS * 1.4;
    let inside = |v: f64| v >= a * (1.0 - 1e-9) && v <= b * (1.0 + 1e-9);
    let pow = |e: i32| if e >= 0 { 10f64.powi(e) } else { 1.0 / 10f64.powi(-e) };
    let e0 = a.log10().floor() as i32 - 1;
    let e1 = b.log10().ceil() as i32 + 1;
    let mut all = Vec::new();
    for e in e0..=e1 {
        for m in [1.0, 2.0, 5.0] {
            let v = if e >= 0 { m * 10f64.powi(e) } else { m / 10f64.powi(-e) };
            if inside(v) {
                all.push(v);
            }
        }
    }
    if all.len() as f64 * row <= avail {
        return all;
    }
    let decades: Vec<i32> = (e0..=e1).filter(|&e| inside(pow(e))).collect();
    let mut k = 1usize;
    loop {
        let t: Vec<f64> = decades.iter().step_by(k).map(|&e| pow(e)).collect();
        if t.len() as f64 * row <= avail || t.len() <= 1 {
            return t;
        }
        k += 1;
    }
}

fn log_labels(ch: &Chart, ax: Option<usize>, ticks: &[f64]) -> Vec<String> {
    let a = ax.map(|k| &ch.axes[k]);
    let fmt = a.and_then(|a| a.format.clone()).or_else(|| ch.format.clone()).filter(|f| !matches!(f, Fmt::Date(_)));
    let unit = a.map(|a| a.unit.clone()).unwrap_or_default();
    ticks.iter().map(|&v| format!("{}{}", fmt_with(v, fmt.as_ref()).unwrap_or_else(|| log_label(v)), unit)).collect()
}

pub fn log_label(v: f64) -> String {
    let d = decimals_of(v);
    let s = format!("{:.*}", d, v);
    if s.contains('.') {
        s.trim_end_matches('0').trim_end_matches('.').to_string()
    } else {
        s
    }
}

// Domain and ticks of a value axis from the values it must show.
fn value_axis(ch: &Chart, ax: Option<usize>, right: bool, vals: &[f64]) -> Result<VAxis, Diag> {
    let a = ax.map(|k| &ch.axes[k]);
    let log = a.map(|a| a.log).unwrap_or(false);
    if let Some(a) = a {
        if a.scale_time {
            return Err(Diag::error("layout", "the x (domain) axis is the time axis — a value axis is numeric", a.node_span));
        }
        if a.ticks_time {
            return Err(Diag::error("layout", "an axis reads dates or numbers, never both — one domain, one kind", a.node_span));
        }
        if matches!(a.format, Some(Fmt::Date(_))) {
            return Err(Diag::error("layout", "a date preset reads a time axis", a.node_span));
        }
        if let Some((l, h)) = a.range {
            if l == h {
                return Err(Diag::error("layout", "'range' needs distinct ends", Default::default()));
            }
        }
    }
    let fmt = a.and_then(|a| a.format.clone()).or_else(|| ch.format.clone()).filter(|f| !matches!(f, Fmt::Date(_)));
    let unit = a.map(|a| a.unit.clone()).unwrap_or_default();
    let (lo, hi, mut ticks, step);
    if log {
        let (l, h) = match a.and_then(|a| a.range) {
            Some(r) => r,
            None => {
                if vals.iter().any(|v| *v <= 0.0) || vals.is_empty() {
                    return Err(Diag::error("layout", "a 'scale: log' axis needs a domain above 0", Default::default()));
                }
                let mn = vals.iter().cloned().fold(f64::INFINITY, f64::min);
                let mx = vals.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
                (10f64.powf(mn.log10().floor()), 10f64.powf(mx.log10().ceil()))
            }
        };
        if l <= 0.0 || h <= 0.0 {
            return Err(Diag::error("layout", "a 'scale: log' axis needs a domain above 0", Default::default()));
        }
        let (l, h) = if l == h { (l, l * 10.0) } else { (l, h) };
        lo = l;
        hi = h;
        ticks = log_ticks(lo, hi);
        step = 1.0;
    } else {
        let explicit = match a.and_then(|a| a.step.clone()) {
            Some(StepSpec::Num(s)) if s > 0.0 => Some(s),
            _ => None,
        };
        match a.and_then(|a| a.range) {
            Some((l, h)) => {
                lo = l;
                hi = h;
                step = explicit.unwrap_or_else(|| nice_step((h - l).abs()));
                ticks = ticks_in(l, h, step);
            }
            None => {
                let mut mn = 0.0f64;
                let mut mx = 0.0f64;
                for &v in vals {
                    mn = mn.min(v);
                    mx = mx.max(v);
                }
                // zero is always shown; a positive-only domain is rounded up to a
                // whole step, one reaching below zero is kept as the data has it
                // each side of zero rounds out to its own nice step; an
                // empty side is 0 below and 1 above
                let l = if mn < 0.0 {
                    let s = nice_step(-mn);
                    snap(mn / s).floor() * s
                } else {
                    0.0
                };
                let h = if mx > 0.0 {
                    let s = nice_step(mx);
                    snap(mx / s).ceil() * s
                } else {
                    1.0
                };
                lo = l;
                hi = h;
                step = explicit.unwrap_or_else(|| nice_step(hi - lo));
                ticks = ticks_in(lo, hi, step);
            }
        }
    }
    if let Some(t) = a.and_then(|a| a.ticks.clone()) {
        ticks = t;
    }
    let labels = ticks
        .iter()
        .map(|&v| {
            let base = if log {
                fmt_with(v, fmt.as_ref()).unwrap_or_else(|| log_label(v))
            } else {
                fmt_tick(v, step, fmt.as_ref())
            };
            format!("{}{}", base, unit)
        })
        .collect();
    Ok(VAxis {
        ax,
        right,
        lo,
        hi,
        log,
        ticks,
        labels,
        title: a.and_then(|a| a.title.clone()),
        gridlines: a.map(|a| a.gridlines).unwrap_or(true),
    })
}

struct XNum {
    lo: f64,
    hi: f64,
    ticks: Vec<f64>,
    labels: Vec<String>,
    time: bool,
    log: bool,
}


pub fn draw(ctx: &Ctx, ch: &Chart, w: f64, h: f64) -> Result<Drawing, Diag> {
    let horiz = ch.dir == Dir::Row;
    let mut flags = Flags::default();
    let c = ch.clearance;
    let g = ch.gap;
    let (cl, cr, ct, cb) = (-w / 2.0, w / 2.0, -h / 2.0, h / 2.0);
    // ---- categories or a numeric x
    let numeric_x = ch.categories.is_none() && ch.series.iter().any(|s| s.points || !s.fns.is_empty() || s.kind == Kind::Bubble);
    let implicit_cats = ch.categories.is_none() && !numeric_x;
    let cats: Vec<String> = match &ch.categories {
        Some(c) => c.clone(),
        None => {
            if numeric_x {
                vec![]
            } else {
                let n = ch.series.iter().map(|s| s.vals.len()).max().unwrap_or(0);
                (1..=n).map(|k| k.to_string()).collect()
            }
        }
    };
    // ---- axes: which declared axes are value axes, which is the x axis
    let is_cross = |a: &Axis| -> bool {
        match a.side.as_deref() {
            Some("bottom") | Some("top") => !horiz,
            Some("left") | Some("right") => horiz,
            _ => false,
        }
    };
    let x_axis: Option<usize> = ch.axes.iter().position(|a| is_cross(a));
    let mut vaxes_idx: Vec<usize> = (0..ch.axes.len()).filter(|&k| !is_cross(&ch.axes[k])).collect();
    // band / mark axes that are the x axis by id
    let default_v: Option<usize> = vaxes_idx.first().cloned();
    let series_axis = |s: &Series| -> Option<usize> {
        match &s.axis {
            Some(id) => ch.axes.iter().position(|a| a.id.as_deref() == Some(id.as_str())),
            None => default_v,
        }
    };
    // ---- numeric x domain
    let mut xnum: Option<XNum> = None;
    if numeric_x {
        let xa = x_axis.map(|k| &ch.axes[k]);
        let time = ch.series.iter().any(|s| s.time_x) || xa.map(|a| a.range_time).unwrap_or(false);
        // one domain, one kind: dates or numbers along x, never both
        let mixed_err = |sp| Diag::error("layout", "an axis reads dates or numbers, never both — one domain, one kind", sp);
        if let Some(a) = xa {
            if a.scale_time && !time {
                return Err(mixed_err(ctx.nodes[ch.node].span));
            }
            if a.ticks.is_some() && a.ticks_time != time {
                return Err(mixed_err(a.node_span));
            }
        }
        let (lo, hi) = match xa.and_then(|a| a.range) {
            Some(r) => r,
            None => {
                let mut mn = f64::INFINITY;
                let mut mx = f64::NEG_INFINITY;
                for s in &ch.series {
                    for p in &s.pts {
                        mn = mn.min(p.0);
                        mx = mx.max(p.0);
                    }
                    if let Some(a) = s.at {
                        mn = mn.min(a.0);
                        mx = mx.max(a.0);
                    }
                }
                for b in &ch.bands {
                    mn = mn.min(b.range.0.min(b.range.1));
                    mx = mx.max(b.range.0.max(b.range.1));
                }
                let xlog = xa.map(|a| a.log).unwrap_or(false);
                if !mn.is_finite() {
                    (0.0, 1.0)
                } else if xlog {
                    if mn <= 0.0 {
                        return Err(Diag::error("layout", "a 'scale: log' axis needs a domain above 0", Default::default()));
                    }
                    (10f64.powf(mn.log10().floor()), 10f64.powf(mx.log10().ceil()))
                } else if ch.series.iter().any(|s| s.kind == Kind::Bubble) {
                    let pad = ((mx - mn) * 0.1).max(1.0);
                    (mn - pad, mx + pad)
                } else {
                    (mn, mx)
                }
            }
        };
        let (ticks, labels) = if time {
            let cal_err = || Diag::error("layout", "a time axis steps by calendar — 'step: month', 'step: 2 week'", xa.map(|a| ctx.nodes[a.node].span).unwrap_or_default());
            let (u, n) = match xa.and_then(|a| a.step.clone()) {
                Some(StepSpec::Cal(n, unit)) => match tunit_of(&unit) {
                    Some(u) if n >= 1 => (u, n),
                    _ => return Err(cal_err()),
                },
                Some(StepSpec::Num(_)) => return Err(cal_err()),
                None => auto_tstep((hi - lo).abs()),
            };
            let t = time_ticks(lo, hi, u, n);
            let tf = xa.and_then(|a| a.format.clone()).or_else(|| ch.format.clone());
            let l = t
                .iter()
                .map(|v| match &tf {
                    Some(Fmt::Date(p)) => fmt_date_preset(*v, p),
                    // a number format reads the instant as epoch seconds
                    Some(f) => fmt_with((v * 86400.0).round(), Some(f)).unwrap_or_else(|| time_label(*v, u)),
                    None => time_label(*v, u),
                })
                .collect();
            (t, l)
        } else {
            if let Some(a) = xa {
                if matches!(a.format, Some(Fmt::Date(_))) {
                    return Err(Diag::error("layout", "a date preset reads a time axis", a.node_span));
                }
            }
            let step = match xa.and_then(|a| a.step.clone()) {
                Some(StepSpec::Num(s)) if s > 0.0 => s,
                _ => nice_step((hi - lo).abs()),
            };
            let xlog = xa.map(|a| a.log).unwrap_or(false);
            let mut t = if xlog { log_ticks(lo, hi) } else { ticks_in(lo, hi, step) };
            if let Some(tt) = xa.and_then(|a| a.ticks.clone()) {
                t = tt;
            }
            if xa.map(|a| a.ticks_none).unwrap_or(false) {
                t = vec![];
            }
            let l = if xlog {
                let fmt = xa.and_then(|a| a.format.clone()).or_else(|| ch.format.clone());
                let unit = xa.map(|a| a.unit.clone()).unwrap_or_default();
                t.iter().map(|&v| format!("{}{}", fmt_with(v, fmt.as_ref()).unwrap_or_else(|| log_label(v)), unit)).collect()
            } else {
                axis_labels(xa, ch, &t, step, false)
            };
            (t, l)
        };
        let log = !time && xa.map(|a| a.log).unwrap_or(false);
        xnum = Some(XNum { lo, hi, ticks, labels, time, log });
    }
    // ---- sample formulas
    let mut series_pts: Vec<Vec<(f64, f64)>> = vec![];
    for s in &ch.series {
        if !s.fns.is_empty() {
            let xn = xnum.as_ref().unwrap();
            let n = ch.samples.max(2);
            let mut pts = Vec::new();
            if s.fns.len() == 1 || ch.bands.is_empty() {
                for k in 0..n {
                    let x = xn.lo + (xn.hi - xn.lo) * k as f64 / (n - 1) as f64;
                    let y = eval_fn(ctx, &s.fns[0], x, None).map_err(|e| Diag::error(&e.family, &e.message, s.span))?;
                    pts.push((x, y));
                }
            } else {
                for (bi, b) in ch.bands.iter().enumerate() {
                    let f = match s.fns.get(bi) {
                        Some(f) => f,
                        None => s.fns.last().unwrap(),
                    };
                    for k in 0..n {
                        let u = k as f64 / (n - 1) as f64;
                        let x = b.range.0 + (b.range.1 - b.range.0) * u;
                        let y = eval_fn(ctx, f, x, Some(u)).map_err(|e| Diag::error(&e.family, &e.message, s.span))?;
                        pts.push((x, y));
                    }
                }
            }
            series_pts.push(pts);
        } else if s.points {
            series_pts.push(s.pts.clone());
        } else {
            series_pts.push(vec![]);
        }
    }
    // ---- value axes
    if vaxes_idx.is_empty() {
        vaxes_idx = vec![];
    }
    let mut vax: Vec<VAxis> = Vec::new();
    let vlist: Vec<Option<usize>> = if vaxes_idx.is_empty() { vec![None] } else { vaxes_idx.iter().map(|k| Some(*k)).collect() };
    let stacked = ch.bars_mode == "stacked";
    for &ak in &vlist {
        let mut vals: Vec<f64> = Vec::new();
        let mut stack = vec![0.0; cats.len()];
        let mut stacked_any = vec![false; cats.len()];
        let mut has_bars = false;
        for (si, s) in ch.series.iter().enumerate() {
            let sa = series_axis(s);
            if sa != ak && !(ak.is_none() && sa.is_none()) {
                continue;
            }
            if s.kind == Kind::Bars {
                has_bars = true;
            }
            if s.kind == Kind::Bars && stacked && !s.points {
                // signed sums; only each category's total counts
                for (k, v) in s.vals.iter().enumerate() {
                    if k < cats.len() {
                        stack[k] += v;
                        stacked_any[k] = true;
                    }
                }
                continue;
            }
            vals.extend(s.vals.iter().cloned());
            for p in &series_pts[si] {
                vals.push(p.1);
            }
            if let Some(a) = s.at {
                vals.push(a.1);
            }
            if let Some(b) = s.baseline {
                vals.push(b);
            }
        }
        for (k, t) in stack.iter().enumerate() {
            if stacked_any[k] {
                vals.push(*t);
            }
        }
        if has_bars {
            // bars stand on zero: nothing below it widens the axis
            vals.retain(|v| *v >= 0.0);
        }
        let right = match ak.and_then(|k| ch.axes[k].side.clone()).as_deref() {
            Some("right") | Some("top") => true,
            _ => false,
        };
        vax.push(value_axis(ch, ak, right, &vals)?);
    }
    let vax_of = |s: &Series| -> usize {
        let sa = series_axis(s);
        vlist.iter().position(|a| *a == sa).unwrap_or(0)
    };
    // ---- legend entries
    let named: Vec<usize> = (0..ch.series.len()).filter(|&k| ch.series[k].name.is_some() && ch.series[k].kind != Kind::Bubble).collect();
    let legend = named.len() >= 2;
    // ---- frame
    let mut region_top = ct + 8.0;
    let mut title_y = 0.0;
    if ch.title.is_some() {
        title_y = region_top + 10.5;
        region_top = region_top + (18.0 + g);
    }
    // side labels
    let (mut left_w, mut right_w) = (None::<f64>, None::<f64>);
    let grow = |slot: &mut Option<f64>, wv: f64| {
        *slot = Some(slot.unwrap_or(0.0).max(wv));
    };
    let mut top_title = false;
    let mut bottom_title: Option<String> = None;
    // a row chart's 'side: top' value axis reads along the top
    let mut top_vtitle: Option<String> = None;
    let top_vax = horiz && vax.iter().any(|a| a.right);
    let bottom_labels = !horiz || vax.iter().any(|a| !a.right);
    if horiz {
        // categories (or a numeric x axis) on the left, values along the bottom
        for cname in &cats {
            grow(&mut left_w, tw(cname));
        }
        if let Some(xn) = &xnum {
            for l in &xn.labels {
                grow(&mut left_w, tw(l));
            }
        }
        if let Some(xk) = x_axis {
            if ch.axes[xk].title.is_some() {
                top_title = true;
            }
        }
        for a in &vax {
            if a.title.is_some() && !a.right && bottom_title.is_none() {
                bottom_title = a.title.clone();
            }
            if a.title.is_some() && a.right && top_vtitle.is_none() {
                top_vtitle = a.title.clone();
            }
        }
    } else {
        for a in &vax {
            for l in &a.labels {
                if a.right {
                    grow(&mut right_w, tw(l));
                } else {
                    grow(&mut left_w, tw(l));
                }
            }
            if a.title.is_some() {
                top_title = true;
            }
        }
        if let Some(xk) = x_axis {
            bottom_title = ch.axes[xk].title.clone();
        }
    }
    // the label gutter is summed first, then laid against the edge
    let pl = match left_w {
        Some(wv) => cl + (4.0 + (wv + c)),
        None => cl + 12.0,
    };
    let pr = match right_w {
        Some(wv) => cr - (4.0 + (wv + c)),
        None => cr - 12.0,
    };
    // from the top: axis titles at the top-left, a row chart's top value
    // axis title, its tick labels, then the plot
    let mut pt = if top_title { region_top + (FS * 1.4 + c) } else { region_top };
    let title_row_y = pt - c;
    let top_vtitle_y = pt + FS * 0.7;
    if top_vtitle.is_some() {
        pt += 16.8 + c;
    }
    if top_vax {
        pt += c + 16.8;
    }
    let band_labels = ch.bands.iter().any(|b| {
        let on_value = match b.axis.as_deref() {
            Some(id) => match ch.axes.iter().position(|a| a.id.as_deref() == Some(id)) {
                Some(k) => !is_cross(&ch.axes[k]),
                None => false,
            },
            None => false,
        };
        b.name.is_some() && (on_value == horiz)
    });
    // under the plot: n label rows (tick labels, the axis title), each
    // 1.4 em plus the clearance, less 2; then a row of band names; then
    // the legend (0.7 em) and the gap
    let row = FS * 1.4;
    let n_rows = (bottom_labels as usize + bottom_title.is_some() as usize) as f64;
    let mut pb = cb - 8.0;
    pb += 2.0;
    if band_labels && bottom_labels {
        pb -= 12.0;
    }
    if n_rows >= 1.0 {
        pb -= row;
    }
    if n_rows >= 2.0 {
        pb -= c;
    }
    if n_rows >= 1.0 {
        pb -= c;
    }
    if n_rows >= 2.0 {
        pb -= row;
    }
    if legend {
        pb -= g;
        pb -= FS * 0.7;
    }
    let pb = pb;
    // the axis title's row sits under the tick row (and any band names)
    let title_row_bottom_y = {
        let mut y = (pb + c) + row;
        if band_labels && bottom_labels {
            y += 12.0;
        }
        (y + c) + FS * 0.7
    };
    // a log axis shows as many ticks as its length fits (one label row
    // each): 1-2-5 per decade, else every decade, else every k-th
    let mut relabel = false;
    if !horiz {
        for a in vax.iter_mut() {
            let explicit = a.ax.map(|k| ch.axes[k].ticks.is_some()).unwrap_or(false);
            if a.log && !explicit {
                a.ticks = log_ticks_fit(a.lo, a.hi, (pb - pt).abs());
                a.labels = log_labels(ch, a.ax, &a.ticks);
                relabel = true;
            }
        }
    }
    let (pl, pr) = if relabel {
        let (mut lw, mut rw) = (None::<f64>, None::<f64>);
        for a in &vax {
            for l in &a.labels {
                let slot = if a.right { &mut rw } else { &mut lw };
                *slot = Some(slot.unwrap_or(0.0).max(tw(l)));
            }
        }
        (
            match lw {
                Some(wv) => cl + (4.0 + (wv + c)),
                None => cl + 12.0,
            },
            match rw {
                Some(wv) => cr - (4.0 + (wv + c)),
                None => cr - 12.0,
            },
        )
    } else {
        (pl, pr)
    };
    // the same fit along the width: a row chart's log value axis, a log x axis
    if horiz {
        for a in vax.iter_mut() {
            let explicit = a.ax.map(|k| ch.axes[k].ticks.is_some()).unwrap_or(false);
            if a.log && !explicit {
                a.ticks = log_ticks_fit(a.lo, a.hi, (pr - pl).abs());
                a.labels = log_labels(ch, a.ax, &a.ticks);
            }
        }
    }
    if let Some(xn) = xnum.as_mut() {
        let xa_ticks = x_axis.map(|k| ch.axes[k].ticks.is_some() || ch.axes[k].ticks_none).unwrap_or(false);
        if xn.log && !xn.time && !xa_ticks {
            xn.ticks = log_ticks_fit(xn.lo, xn.hi, (pr - pl).abs());
            xn.labels = log_labels(ch, x_axis, &xn.ticks);
        }
    }
    let geo = Geo { l: pl, r: pr, t: pt, b: pb, horiz };
    let clip_rect = [pl.min(pr), pt.min(pb), pl.max(pr), pt.max(pb)];
    let bounds = [cl, ct, cr, cb];
    // ---- positions
    let ncat = cats.len().max(1) as f64;
    let band_w = if horiz { (pb - pt) / ncat } else { (pr - pl) / ncat };
    let cat_pos = |k: usize| -> f64 {
        if horiz {
            pt + (pb - pt) * ((k as f64 + 0.5) / ncat)
        } else {
            pl + (pr - pl) * ((k as f64 + 0.5) / ncat)
        }
    };
    let xpos = |x: f64| -> f64 {
        let xn = xnum.as_ref().unwrap();
        if xn.hi == xn.lo {
            return if horiz { pt } else { pl };
        }
        if xn.log {
            let (a, b) = (xn.lo.log10(), xn.hi.log10());
            let (p0, p1) = if horiz { (pt, pb) } else { (pl, pr) };
            return p0 + (x.max(1e-300).log10() - a) / (b - a) * (p1 - p0);
        }
        // across a row chart x runs down the plot
        let (p0, p1) = if horiz { (pt, pb) } else { (pl, pr) };
        if xn.time {
            // instants are whole seconds: the ratio is taken on those
            let sec = |d: f64| (d * 86400.0).round();
            return p0 + (sec(x) - sec(xn.lo)) / (sec(xn.hi) - sec(xn.lo)) * (p1 - p0);
        }
        p0 + (x - xn.lo) / (xn.hi - xn.lo) * (p1 - p0)
    };
    // an x value along the domain: numeric, or a (fractional) category index
    let xmap = |v: f64| -> f64 {
        if xnum.is_some() {
            xpos(v)
        } else if horiz {
            pt + (pb - pt) * ((v + 0.5) / ncat)
        } else {
            pl + (pr - pl) * ((v + 0.5) / ncat)
        }
    };
    // point → (px, py)
    let to_xy = |s: &Series, k: usize, v: f64, xv: Option<f64>| -> (f64, f64) {
        let a = &vax[vax_of(s)];
        let along = match xv {
            Some(x) => xmap(x),
            None => cat_pos(k),
        };
        let vp = geo.vpos(a, v);
        if horiz {
            (vp, along)
        } else {
            (along, vp)
        }
    };
    let mut els: Vec<El> = Vec::new();
    // ---- bands: filled spans, or edge lines when unfilled
    let band_on_value = |b: &Band| -> Option<usize> {
        let id = b.axis.as_deref()?;
        let k = ch.axes.iter().position(|a| a.id.as_deref() == Some(id))?;
        if is_cross(&ch.axes[k]) {
            None
        } else {
            Some(vlist.iter().position(|a| *a == Some(k)).unwrap_or(0))
        }
    };
    for b in &ch.bands {
        // a value axis is numeric: a dated band cannot sit on it
        if b.time && band_on_value(b).is_some() {
            return Err(Diag::error("layout", "an axis reads dates or numbers, never both — one domain, one kind", ctx.nodes[b.node].span));
        }
    }
    let mut edges_drawn: Vec<(bool, f64)> = Vec::new();
    for b in &ch.bands {
        let fill = color_at(&b.fill, 0);
        let edges: (f64, f64, bool) = match band_on_value(b) {
            Some(vi) => (geo.vpos(&vax[vi], b.range.0), geo.vpos(&vax[vi], b.range.1), !horiz),
            None => (xmap(b.range.0), xmap(b.range.1), horiz),
        };
        let (e0, e1, across) = edges;
        // across = the band spans the plot horizontally (a y range in column charts)
        match fill {
            Some(fill) => {
                let (a, bb) = (e0.min(e1), e0.max(e1));
                let (cx, cy, bw, bh) = if across { ((pl + pr) / 2.0, (a + bb) / 2.0, pr - pl, bb - a) } else { ((a + bb) / 2.0, (pt + pb) / 2.0, bb - a, pb - pt) };
                els.push(El::G {
                    cls: "lini-block".into(),
                    style: format!("fill: {}; stroke-width: 0; opacity: 0.15", fill),
                    tx: cx,
                    ty: cy,
                    title: None,
                    inner: vec![rect(-bw / 2.0, -bh / 2.0, bw, bh, 0.0)],
                    kids: vec![],
                });
            }
            None => {
                for e in [e0, e1] {
                    // an edge on the plot's own border, or one already drawn, is skipped
                    let (lo_b, hi_b) = if across { (pt, pb) } else { (pl, pr) };
                    if (e - lo_b).abs() < 1e-6 || (e - hi_b).abs() < 1e-6 || edges_drawn.iter().any(|(ac, v)| *ac == across && (v - e).abs() < 1e-6) {
                        continue;
                    }
                    edges_drawn.push((across, e));
                    flags.line = true;
                    if across {
                        els.push(line_el(pl, e, pr, e, "stroke: var(--lini-muted); stroke-width: 1"));
                    } else {
                        els.push(line_el(e, pt, e, pb, "stroke: var(--lini-muted); stroke-width: 1"));
                    }
                }
            }
        }
    }
    // ---- gridlines
    let grid = "stroke: var(--lini-grid); stroke-width: 1";
    // only the first value axis rules the grid
    for a in vax.iter().take(1) {
        if !a.gridlines {
            continue;
        }
        for &t in &a.ticks {
            let p = geo.vpos(a, t);
            flags.line = true;
            if horiz {
                els.push(line_el(p, pt, p, pb, grid));
            } else {
                els.push(line_el(pl, p, pr, p, grid));
            }
        }
    }
    if let Some(xn) = &xnum {
        let gl = x_axis.map(|k| ch.axes[k].gridlines).unwrap_or(true);
        if gl {
            for &t in &xn.ticks {
                let p = xpos(t);
                flags.line = true;
                if horiz {
                    els.push(line_el(pl, p, pr, p, grid));
                } else {
                    els.push(line_el(p, pt, p, pb, grid));
                }
            }
        }
    }
    // ---- series
    let mut hits: Vec<(f64, f64, String)> = Vec::new();
    let mut labels: Vec<Lab> = Vec::new();
    // label obstacles: every line / area as straight runs through its points
    let mut obstacles: Vec<Vec<(f64, f64)>> = Vec::new();
    let chart_tips = ch.tooltip != "none";
    let mode_of = |s: &Series| -> String { s.tooltip.clone().unwrap_or_else(|| ch.tooltip.clone()) };
    let fmt = ch.format.clone();
    let x_fmt: Option<Fmt> = x_axis.and_then(|k| ch.axes[k].format.clone()).or_else(|| ch.format.clone());
    let fmt = fmt.filter(|f| !matches!(f, Fmt::Date(_)));
    let tip_text = |s: &Series, k: usize, v: f64, xv: Option<f64>, time: bool| -> String {
        let val = fmt_value(v, fmt.as_ref());
        match xv {
            Some(x) => {
                let xs = if time {
                    match &x_fmt {
                        Some(Fmt::Date(p)) => fmt_date_preset(x, p),
                        _ => fmt_date(x),
                    }
                } else {
                    fmt_value(x, x_fmt.as_ref().filter(|f| !matches!(f, Fmt::Date(_))))
                };
                match &s.name {
                    Some(n) => format!("{}: {}, {}", n, xs, val),
                    None => format!("{}, {}", xs, val),
                }
            }
            None => {
                if implicit_cats {
                    match &s.name {
                        Some(n) => format!("{}: {}", n, val),
                        None => val,
                    }
                } else {
                    let cat = cats.get(k).cloned().unwrap_or_default();
                    match &s.name {
                        Some(n) => format!("{} · {}: {}", cat, n, val),
                        None => format!("{}: {}", cat, val),
                    }
                }
            }
        }
    };
    let time_x = xnum.as_ref().map(|x| x.time).unwrap_or(false);
    // a point's tip: "name: x, y" / "name: category: value"
    let point_tip = |s: &Series, k: usize, v: f64, xv: Option<f64>| -> String {
        if xv.is_some() || implicit_cats {
            return tip_text(s, k, v, xv, time_x);
        }
        let val = fmt_value(v, fmt.as_ref());
        let cat = cats.get(k).cloned().unwrap_or_default();
        match &s.name {
            Some(n) => format!("{}: {}: {}", n, cat, val),
            None => format!("{}: {}", cat, val),
        }
    };
    let inside = |x: f64, y: f64| -> bool { x >= pl.min(pr) - CLIP_EPS && x <= pl.max(pr) + CLIP_EPS && y >= pt.min(pb) - CLIP_EPS && y <= pt.max(pb) + CLIP_EPS };
    // areas first
    let order: Vec<usize> = {
        let mut o: Vec<usize> = Vec::new();
        for kind in [Kind::Area, Kind::Bars, Kind::Line, Kind::Dots, Kind::Bubble] {
            for (k, s) in ch.series.iter().enumerate() {
                if s.kind == kind {
                    o.push(k);
                }
            }
        }
        o
    };
    let bar_series: Vec<usize> = (0..ch.series.len()).filter(|&k| ch.series[k].kind == Kind::Bars).collect();
    let nb = bar_series.len().max(1) as f64;
    let overlay = ch.bars_mode == "overlay";
    let mut stack_base_pos = vec![0.0; cats.len()];
    // bars are drawn category-major
    let mut bars_done = false;
    for &si in &order {
        let s = &ch.series[si];
        let hue_name = hue(s.index);
        let show_tips = chart_tips && mode_of(s) != "none";
        let show_labels = matches!(mode_of(s).as_str(), "auto" | "always");
        match s.kind {
            Kind::Area | Kind::Line => {
                let color = series_line_color(s);
                let pts: Vec<(f64, f64)> = if s.points || !s.fns.is_empty() {
                    series_pts[si].iter().map(|p| to_xy(s, 0, p.1, Some(p.0))).collect()
                } else {
                    s.vals.iter().enumerate().map(|(k, v)| to_xy(s, k, *v, None)).collect()
                };
                // a row chart lays its areas out straight
                let curve = if horiz && s.kind == Kind::Area { "linear" } else { s.curve.as_str() };
                let path = curve_points(&pts, curve, horiz);
                obstacles.push(pts.clone());
                if show_labels && s.fns.is_empty() {
                    let r = marker_radius(s);
                    for (k, p) in pts.iter().enumerate() {
                        if let Some(l) = s.labels.get(k) {
                            if !l.is_empty() {
                                labels.push(Lab { always: mode_of(s) == "always", si: s.node, x: p.0, y: p.1, r, text: l.clone(), bubble: false });
                            }
                        }
                    }
                }
                if pts.len() < 2 {
                    // one point draws no line, area, or markers
                    continue;
                }
                if s.kind == Kind::Area {
                    let fill = color_at(&s.fill, 0).unwrap_or_else(|| format!("var(--lini-{}-soft)", hue_name));
                    let base_v = s.baseline.unwrap_or(0.0);
                    let a = &vax[vax_of(s)];
                    let bp = geo.vpos(a, base_v);
                    let mut poly = path.clone();
                    if let (Some(first), Some(last)) = (path.first().cloned(), path.last().cloned()) {
                        if horiz {
                            poly.push((bp, last.1));
                            poly.push((bp, first.1));
                        } else {
                            poly.push((last.0, bp));
                            poly.push((first.0, bp));
                        }
                    }
                    let (ylo, yhi) = (pt.min(pb), pt.max(pb));
                    let (xlo, xhi) = (pl.min(pr), pl.max(pr));
                    let poly: Vec<(f64, f64)> = poly.iter().map(|&(x, y)| (x.max(xlo).min(xhi), y.max(ylo).min(yhi))).collect();
                    flags.poly = true;
                    els.push(poly_el("", &poly, &format!("fill: {}; stroke: none; stroke-width: 0; opacity: 0.82", fill), None));
                    let lc = match (&s.stroke, raw_term(&s.fill)) {
                        (Some(_), _) => color_at(&s.stroke, 0).unwrap_or_else(|| deep_of(&fill)),
                        _ => deep_of(&fill),
                    };
                    for run in clip_runs(&path, clip_rect) {
                        flags.line = true;
                        els.push(path_el(&run, &outline_style(&lc, s)));
                    }
                } else {
                    for run in clip_runs(&path, clip_rect) {
                        flags.line = true;
                        els.push(path_el(&run, &line_style(&color, s)));
                    }
                }
                // markers
                if let Some(m) = &s.marker {
                    let _ = m;
                    let r = marker_radius(s);
                    // an area's markers take its fill; a line's its stroke
                    let mcolor = if s.kind == Kind::Area {
                        color_at(&s.fill, 0).unwrap_or_else(|| format!("var(--lini-{}-soft)", hue_name))
                    } else {
                        color.clone()
                    };
                    let raw: Vec<(Option<f64>, f64, usize)> = if s.points {
                        s.pts.iter().enumerate().map(|(k, p)| (Some(p.0), p.1, k)).collect()
                    } else if s.fns.is_empty() {
                        s.vals.iter().enumerate().map(|(k, v)| (None, *v, k)).collect()
                    } else {
                        // a formula's markers sit on its samples
                        series_pts[si].iter().enumerate().map(|(k, p)| (Some(p.0), p.1, k)).collect()
                    };
                    for (xv, v, k) in raw {
                        let (px, py) = to_xy(s, k, v, xv);
                        if !inside(px, py) {
                            continue;
                        }
                        let hk = hits.len();
                        let tt = point_tip(s, k, v, xv);
                        let cls = if show_tips { format!("lini-hit-{} ", hk) } else { String::new() };
                        els.push(mark_shape(
                            s.marker.as_deref() == Some("diamond"),
                            cls,
                            format!("fill: {}; stroke: none; stroke-width: 0", mcolor),
                            px,
                            py,
                            r,
                            if show_tips { Some(tt.clone()) } else { None },
                            &mut flags,
                        ));
                        if show_tips {
                            hits.push((px, py, tt));
                        }
                    }
                }
            }
            Kind::Bars => {
                if bars_done {
                    continue;
                }
                bars_done = true;
                let group = 0.72 * band_w;
                let slot = if stacked || overlay { group } else { group / nb };
                let thick = 0.9 * slot;
                for k in 0..cats.len() {
                    for (bk, &bsi) in bar_series.iter().enumerate() {
                        let s = &ch.series[bsi];
                        let show_tips = chart_tips && mode_of(s) != "none";
                        let show_labels = matches!(mode_of(s).as_str(), "auto" | "always");
                        let v = match s.vals.get(k) {
                            Some(v) => *v,
                            None => continue,
                        };
                        let a = &vax[vax_of(s)];
                        let center = if stacked || overlay { cat_pos(k) } else { cat_pos(k) - group / 2.0 + slot * (bk as f64 + 0.5) };
                        let (v0, v1) = if stacked {
                            let b = stack_base_pos[k];
                            stack_base_pos[k] += v;
                            (b, b + v)
                        } else {
                            (if a.log { a.lo.min(a.hi) } else { 0.0 }, v)
                        };
                        // a label stays even where the bar has no length
                        if show_labels {
                            if let Some(l) = s.labels.get(k) {
                                if !l.is_empty() {
                                    // anchored at the bar's own value, unstacked
                                    let e = geo.vpos(a, v);
                                    // a grouped bar's label still centres on its category
                                    let (ex, ey) = if horiz { (e, cat_pos(k)) } else { (cat_pos(k), e) };
                                    labels.push(Lab { always: mode_of(s) == "always", si: s.node, x: ex, y: ey, r: 0.0, text: l.clone(), bubble: false });
                                }
                            }
                        }
                        // the bar's box, cut to the plot; nothing left, no bar
                        let (lim0, lim1) = if horiz { (pl.min(pr), pl.max(pr)) } else { (pt.min(pb), pt.max(pb)) };
                        let q0 = geo.vpos(a, v0);
                        let q1 = geo.vpos(a, v1);
                        let (lo_p, hi_p) = (q0.min(q1).max(lim0), q0.max(q1).min(lim1));
                        if !(hi_p > lo_p) {
                            continue;
                        }
                        // a span wholly outside the domain draws nothing
                        let (dlo, dhi) = (a.lo.min(a.hi), a.lo.max(a.hi));
                        if v0.max(v1) <= dlo || v0.min(v1) >= dhi {
                            continue;
                        }
                        let (p0, p1) = (lo_p, hi_p);
                        let (fill, stroke, sw) = bar_colors(s, k);
                        let len = (p1 - p0).abs();
                        let mid = (p0 + p1) / 2.0;
                        let (iw, ih, cx, cy) = if horiz { (len - sw, thick - sw, mid, center) } else { (thick - sw, len - sw, center, mid) };
                        let mut style = format!("fill: {}", fill);
                        match &stroke {
                            Some(st) => {
                                style.push_str(&format!("; stroke: {}", st));
                                if let Some(w) = s.stroke_width {
                                    style.push_str(&format!("; stroke-width: {}", f4(w)));
                                }
                            }
                            None => style.push_str("; stroke-width: 0"),
                        }
                        if overlay {
                            style.push_str("; opacity: 0.6");
                        }
                        let hk = hits.len();
                        let tt = tip_text(s, k, v, None, false);
                        let radius = crate::style::value_num(&ctx.sheet.env, ctx.nodes[s.node].props.get("radius").unwrap_or(&crate::ast::Value { groups: vec![], span: Default::default() })).unwrap_or(2.0);
                        els.push(El::G {
                            cls: if show_tips { format!("lini-hit-{} lini-block", hk) } else { "lini-block".into() },
                            style,
                            tx: cx,
                            ty: cy,
                            title: if show_tips { Some(tt.clone()) } else { None },
                            inner: if iw < 0.0 || ih < 0.0 { vec![] } else { vec![rect(-iw / 2.0, -ih / 2.0, iw, ih, radius)] },
                            kids: vec![],
                        });
                        if show_tips {
                            hits.push((cx, cy, tt));
                        }
                    }
                }
            }
            Kind::Dots => {
                let base = format!("var(--lini-{}-ink)", hue_name);
                let n = if s.points { s.pts.len() } else { s.vals.len() };
                for k in 0..n {
                    let (xv, v) = if s.points { (Some(s.pts[k].0), s.pts[k].1) } else { (None, s.vals[k]) };
                    let (px, py) = to_xy(s, k, v, xv);
                    if !inside(px, py) {
                        continue;
                    }
                    let dot_fill = if is_list(&s.fill) {
                        color_at(&s.fill, k).unwrap_or_else(|| base.clone())
                    } else {
                        // the fill, else a single stroke colour, else the walk's ink
                        raw_term(&s.fill)
                            .or_else(|| if is_list(&s.stroke) { None } else { raw_term(&s.stroke) })
                            .unwrap_or_else(|| base.clone())
                    };
                    let style = if is_list(&s.stroke) {
                        let st = color_at(&s.stroke, k).unwrap_or_else(|| deep_of(&dot_fill));
                        format!("fill: {}; stroke: {}; stroke-width: 2", dot_fill, st)
                    } else {
                        format!("fill: {}; stroke: none; stroke-width: 0", dot_fill)
                    };
                    let hk = hits.len();
                    let tt = point_tip(s, k, v, xv);
                    els.push(mark_shape(
                        s.marker.as_deref() == Some("diamond"),
                        if show_tips { format!("lini-hit-{} ", hk) } else { String::new() },
                        style,
                        px,
                        py,
                        if is_list(&s.stroke) { 2.5 } else { 3.5 },
                        if show_tips { Some(tt.clone()) } else { None },
                        &mut flags,
                    ));
                    if show_tips {
                        hits.push((px, py, tt));
                    }
                    if show_labels {
                        if let Some(l) = s.labels.get(k) {
                            if !l.is_empty() {
                                labels.push(Lab { always: mode_of(s) == "always", si: s.node, x: px, y: py, r: 3.5, text: l.clone(), bubble: false });
                            }
                        }
                    }
                }
            }
            Kind::Bubble => {}
        }
    }
    // bubbles: radius ∝ √value, the largest 0.14 of the plot's short side
    let bubbles: Vec<usize> = (0..ch.series.len()).filter(|&k| ch.series[k].kind == Kind::Bubble).collect();
    if !bubbles.is_empty() {
        let vmax = bubbles.iter().map(|&k| ch.series[k].value.unwrap_or(0.0)).fold(0.0f64, f64::max);
        let rmax = 0.14 * (pr - pl).min(pb - pt);
        for &bk in &bubbles {
            let s = &ch.series[bk];
            let show_tips = chart_tips && mode_of(s) != "none";
            let show_labels = matches!(mode_of(s).as_str(), "auto" | "always");
            let (ax, ay) = s.at.unwrap_or((0.0, 0.0));
            let v = s.value.unwrap_or(0.0);
            let r = if vmax > 0.0 { rmax * (v / vmax).sqrt() } else { 0.0 };
            let (px, py) = to_xy(s, 0, ay, Some(ax));
            let fill = color_at(&s.fill, 0).unwrap_or_else(|| format!("var(--lini-{})", hue(s.index)));
            let hk = hits.len();
            let tt = match &s.name {
                Some(n) => format!("{}: {}", n, fmt_value(v, fmt.as_ref())),
                None => fmt_value(v, fmt.as_ref()),
            };
            flags.oval = true;
            els.push(El::G {
                cls: if show_tips { format!("lini-hit-{} lini-oval", hk) } else { "lini-oval".into() },
                style: format!("fill: {}; stroke: none; stroke-width: 0", fill),
                tx: px,
                ty: py,
                title: if show_tips { Some(tt.clone()) } else { None },
                inner: vec![format!("<ellipse cx=\"0\" cy=\"0\" rx=\"{}\" ry=\"{}\"/>", f4(r), f4(r))],
                kids: vec![],
            });
            if show_tips {
                hits.push((px, py, tt));
            }
            if show_labels {
                if let Some(n) = &s.name {
                    labels.push(Lab { always: mode_of(s) == "always", si: s.node, x: px, y: py, r, text: n.clone(), bubble: true });
                }
            }
        }
    }
    // ---- marks
    for m in &ch.marks {
        let ak = ch.axes.iter().position(|a| a.id.as_deref() == m.axis.as_deref());
        let on_x = match ak {
            Some(k) => is_cross(&ch.axes[k]),
            None => false,
        };
        let stroke = color_at(&m.stroke, 0).unwrap_or_else(|| "var(--lini-muted)".into());
        let sw = 1.5;
        let mut style = format!("stroke: {}; stroke-width: {}", stroke, f4(sw));
        if let Some(st) = &m.stroke_style {
            if st != "solid" {
                if let Some(d) = crate::style::dasharray(st, sw) {
                    style.push_str(&format!("; stroke-dasharray: {}", d));
                }
            }
        }
        let tcolor = color_at(&m.stroke, 0).unwrap_or_else(|| "var(--lini-muted)".into());
        if m.at.len() == 2 {
            // a point: a dot at (x, y) with its name placed like a label
            let vi = if on_x { 0 } else { vlist.iter().position(|a| *a == ak).unwrap_or(0) };
            let (px, py) = if horiz { (geo.vpos(&vax[vi], m.at[1]), xmap(m.at[0])) } else { (xmap(m.at[0]), geo.vpos(&vax[vi], m.at[1])) };
            if !inside(px, py) {
                continue;
            }
            flags.oval = true;
            els.push(El::G {
                cls: "lini-oval".into(),
                style: format!("fill: {}; stroke: none; stroke-width: 0", tcolor),
                tx: px,
                ty: py,
                title: None,
                inner: vec!["<ellipse cx=\"0\" cy=\"0\" rx=\"2.5\" ry=\"2.5\"/>".into()],
                kids: vec![],
            });
            if let Some(n) = &m.name {
                labels.push(Lab { always: ch.tooltip == "always", si: m.node, x: px, y: py, r: 2.5, text: n.clone(), bubble: false });
            }
            continue;
        }
        let pos = if on_x { xmap(m.at[0]) } else { geo.vpos(&vax[vlist.iter().position(|a| *a == ak).unwrap_or(0)], m.at[0]) };
        // a mark off the plot is not drawn
        let (e0, e1) = if on_x != horiz { (pl.min(pr), pl.max(pr)) } else { (pt.min(pb), pt.max(pb)) };
        if !(pos >= e0 - CLIP_EPS && pos <= e1 + CLIP_EPS) {
            continue;
        }
        flags.line = true;
        if on_x != horiz {
            // a vertical line; its label at the top (at the bottom across a row chart)
            els.push(line_el(pos, pt, pos, pb, &style));
            if let Some(n) = &m.name {
                flags.text = true;
                let ly = if horiz { pb - 10.8 } else { pt + 10.8 };
                // right of the line, or left of it when it would run off the plot
                let wn = tw(n);
                let lx = if pos + c + wn > pl.max(pr) { pos - c - wn / 2.0 } else { pos + c + wn / 2.0 };
                els.push(text_el("lini-chart-text", lx, ly, &format!("fill: {}", tcolor), n));
            }
        } else {
            els.push(line_el(pl, pos, pr, pos, &style));
            if let Some(n) = &m.name {
                flags.text = true;
                els.push(text_el("lini-chart-text", pl + c + tw(n) / 2.0, pos - FS * 0.6, &format!("fill: {}", tcolor), n));
            }
        }
    }
    // ---- axis labels
    let muted = "fill: var(--lini-muted)";
    let tick_y = (pb + c) + FS * 0.7;
    if horiz {
        // value axes along the bottom ('side: top' ones along the top),
        // each followed by its title
        let (mut top_done, mut bottom_done) = (false, false);
        for a in &vax {
            let y = if a.right { (pt - c) - FS * 0.7 } else { tick_y };
            for (t, l) in a.ticks.iter().zip(a.labels.iter()) {
                flags.text = true;
                els.push(text_el("lini-chart-text", geo.vpos(a, *t), y, muted, l));
            }
            if a.title.is_some() {
                if a.right && !top_done {
                    top_done = true;
                    if let Some(tt) = &top_vtitle {
                        flags.text = true;
                        els.push(text_el("lini-chart-text", (pl + pr) / 2.0, top_vtitle_y, muted, tt));
                    }
                } else if !a.right && !bottom_done {
                    bottom_done = true;
                    if let Some(bt) = &bottom_title {
                        flags.text = true;
                        els.push(text_el("lini-chart-text", (pl + pr) / 2.0, title_row_bottom_y, muted, bt));
                    }
                }
            }
        }
        for (k, cname) in cats.iter().enumerate() {
            flags.text = true;
            els.push(text_el("lini-chart-text", pl - c - tw(cname) / 2.0, cat_pos(k), muted, cname));
        }
        if let Some(xn) = &xnum {
            for (t, l) in xn.ticks.iter().zip(xn.labels.iter()) {
                flags.text = true;
                els.push(text_el("lini-chart-text", pl - c - tw(l) / 2.0, xpos(*t), muted, l));
            }
        }
        if let Some(tt) = x_axis.and_then(|k| ch.axes[k].title.clone()) {
            flags.text = true;
            els.push(text_el("lini-chart-text", pl + tw(&tt) / 2.0, title_row_y, muted, &tt));
        }
    } else {
        for a in &vax {
            for (t, l) in a.ticks.iter().zip(a.labels.iter()) {
                let y = geo.vpos(a, *t);
                let x = if a.right { pr + c + tw(l) / 2.0 } else { pl - c - tw(l) / 2.0 };
                flags.text = true;
                els.push(text_el("lini-chart-text", x, y, muted, l));
            }
            if let Some(tt) = &a.title {
                let x = if a.right { pr - tw(tt) / 2.0 } else { pl + tw(tt) / 2.0 };
                flags.text = true;
                els.push(text_el("lini-chart-text", x, title_row_y, muted, tt));
            }
        }
        if let Some(xn) = &xnum {
            for (t, l) in xn.ticks.iter().zip(xn.labels.iter()) {
                flags.text = true;
                els.push(text_el("lini-chart-text", xpos(*t), tick_y, muted, l));
            }
        } else {
            for (k, cname) in cats.iter().enumerate() {
                flags.text = true;
                els.push(text_el("lini-chart-text", cat_pos(k), tick_y, muted, cname));
            }
        }
    }
    if !horiz {
        if let Some(bt) = &bottom_title {
            flags.text = true;
            els.push(text_el("lini-chart-text", (pl + pr) / 2.0, title_row_bottom_y, muted, bt));
        }
    }
    // ---- band labels: x bands in a row under the axis, y bands beside it
    for b in &ch.bands {
        if let Some(n) = &b.name {
            let fill = color_at(&b.fill, 0).unwrap_or_else(|| "var(--lini-muted)".into());
            flags.text = true;
            match band_on_value(b) {
                Some(vi) => {
                    let m = (geo.vpos(&vax[vi], b.range.0) + geo.vpos(&vax[vi], b.range.1)) / 2.0;
                    if horiz {
                        els.push(text_el("lini-chart-text", m, tick_y + FS * 1.4, &format!("fill: {}", fill), n));
                    } else {
                        els.push(text_el("lini-chart-text", pl - c - tw(n) / 2.0, m, &format!("fill: {}", fill), n));
                    }
                }
                None => {
                    let m = (xmap(b.range.0) + xmap(b.range.1)) / 2.0;
                    if horiz {
                        els.push(text_el("lini-chart-text", pl - c - tw(n) / 2.0, m, &format!("fill: {}", fill), n));
                    } else {
                        els.push(text_el("lini-chart-text", m, tick_y + FS * 1.4, &format!("fill: {}", fill), n));
                    }
                }
            }
        }
    }
    // ---- title
    if let Some(t) = &ch.title {
        flags.title = true;
        els.push(text_el("lini-chart-title", 0.0, title_y, "", t));
    }
    // ---- legend
    if legend {
        flags.legend = true;
        let ly = cb - 10.8;
        let items: Vec<(String, El)> = named
            .iter()
            .map(|&k| {
                let s = &ch.series[k];
                (s.name.clone().unwrap(), swatch(s))
            })
            .collect();
        legend_row(&mut els, items, ly);
    }
    // ---- labels: series by series, each point's first free spot
    labels.sort_by_key(|l| l.si);
    let mut placed: Vec<[f64; 4]> = Vec::new();
    for l in &labels {
        let w = tw(&l.text);
        // a point off the plot keeps no label
        if !inside(l.x, l.y) {
            continue;
        }
        if l.bubble && (w / 2.0).hypot(FS / 2.0) + c <= l.r {
            // a label that fits sits inside its bubble, if the plot has room
            let bx = [l.x - w / 2.0 - 2.0, l.y - FS / 2.0 - 2.0, l.x + w / 2.0 + 2.0, l.y + FS / 2.0 + 2.0];
            let clear = !obstacles.iter().any(|o| (1..o.len()).any(|k| seg_hits_box(o[k - 1], o[k], &bx)))
                && !placed.iter().any(|p| bx[0] < p[2] && p[0] < bx[2] && bx[1] < p[3] && p[1] < bx[3]);
            if clear && bx[0] >= geo.l && bx[2] <= geo.r && bx[1] >= geo.t && bx[3] <= geo.b {
                placed.push(bx);
                flags.label = true;
                els.push(text_el("lini-chart-label", l.x, l.y, "fill: var(--lini-accent-text)", &l.text));
                continue;
            }
        }
        if let Some((lx, ly)) = place_label(l, w, &geo, c, &obstacles, &mut placed, l.always) {
            flags.label = true;
            els.push(text_el("lini-chart-label", lx, ly, muted, &l.text));
        }
    }
    // ---- tips
    if chart_tips && !hits.is_empty() {
        flags.tip = true;
        flags.text = true;
        flags.hits = hits.len();
        for (k, (x, y, t)) in hits.iter().enumerate() {
            els.push(tip_el(k, *x, *y, t, bounds));
        }
    }
    Ok(Drawing { els, flags, bbox: None })
}

pub struct Lab {
    pub always: bool,
    pub si: usize,
    pub x: f64,
    pub y: f64,
    pub r: f64,
    pub text: String,
    pub bubble: bool,
}

fn seg_hits_box(a: (f64, f64), b: (f64, f64), bx: &[f64; 4]) -> bool {
    // Liang–Barsky clip of the segment against the box
    let (dx, dy) = (b.0 - a.0, b.1 - a.1);
    let mut t0 = 0.0f64;
    let mut t1 = 1.0f64;
    for (p, q) in [(-dx, a.0 - bx[0]), (dx, bx[2] - a.0), (-dy, a.1 - bx[1]), (dy, bx[3] - a.1)] {
        if p == 0.0 {
            if q < 0.0 {
                return false;
            }
        } else {
            let r = q / p;
            if p < 0.0 {
                if r > t1 {
                    return false;
                }
                if r > t0 {
                    t0 = r;
                }
            } else {
                if r < t0 {
                    return false;
                }
                if r < t1 {
                    t1 = r;
                }
            }
        }
    }
    t0 <= t1
}

pub fn place_label(l: &Lab, w: f64, geo: &Geo, c: f64, obstacles: &[Vec<(f64, f64)>], placed: &mut Vec<[f64; 4]>, always: bool) -> Option<(f64, f64)> {
    let h = FS;
    let d = l.r + c;
    let (x, y) = (l.x, l.y);
    let ax = d + w / 2.0;
    let ay = d + h / 2.0;
    let cands = [(x, y - ay), (x, y + ay), (x + ax, y), (x - ax, y), (x + ax, y - ay), (x - ax, y - ay), (x + ax, y + ay), (x - ax, y + ay)];
    let m = 2.0;
    for &(cx, cy) in &cands {
        let bx = [cx - w / 2.0 - m, cy - h / 2.0 - m, cx + w / 2.0 + m, cy + h / 2.0 + m];
        if bx[0] < geo.l || bx[2] > geo.r || bx[1] < geo.t || bx[3] > geo.b {
            continue;
        }
        let mut ok = true;
        'obs: for o in obstacles {
            for k in 1..o.len() {
                if seg_hits_box(o[k - 1], o[k], &bx) {
                    ok = false;
                    break 'obs;
                }
            }
        }
        if ok {
            for p in placed.iter() {
                if bx[0] < p[2] && p[0] < bx[2] && bx[1] < p[3] && p[1] < bx[3] {
                    ok = false;
                    break;
                }
            }
        }
        if ok {
            placed.push(bx);
            return Some((cx, cy));
        }
    }
    if always {
        // forced: the first spot that stays on the plot, else the first
        let pick = cands
            .iter()
            .find(|&&(cx, cy)| {
                let bx = [cx - w / 2.0 - m, cy - h / 2.0 - m, cx + w / 2.0 + m, cy + h / 2.0 + m];
                !(bx[0] < geo.l || bx[2] > geo.r || bx[1] < geo.t || bx[3] > geo.b)
            })
            .cloned()
            .unwrap_or(cands[0]);
        let (cx, cy) = pick;
        placed.push([cx - w / 2.0 - m, cy - h / 2.0 - m, cx + w / 2.0 + m, cy + h / 2.0 + m]);
        return Some((cx, cy));
    }
    None
}

pub fn legend_row(els: &mut Vec<El>, items: Vec<(String, El)>, ly: f64) {
    let mut total = 0.0;
    for (k, (name, _)) in items.iter().enumerate() {
        if k > 0 {
            total += 16.0;
        }
        total += 11.0 + 5.0 + tw_legend(name);
    }
    let mut x = -total / 2.0;
    for (name, sw) in items {
        let mut sw = sw;
        if let El::G { tx, ty, .. } = &mut sw {
            *tx = x + 5.5;
            *ty = ly;
        }
        els.push(sw);
        let w = tw_legend(&name);
        els.push(text_el("lini-chart-legend", x + 16.0 + w / 2.0, ly, "", &name));
        x += 16.0 + w + 16.0;
    }
}

pub fn swatch_filled(color: &str) -> El {
    El::G {
        cls: "lini-block".into(),
        style: format!("fill: {}; stroke-width: 0", color),
        tx: 0.0,
        ty: 0.0,
        title: None,
        inner: vec![rect(-5.5, -5.5, 11.0, 11.0, 2.0)],
        kids: vec![],
    }
}

pub fn swatch_outlined(fill: &str, stroke: &str) -> El {
    El::G {
        cls: "lini-block".into(),
        style: format!("fill: {}; stroke: {}; stroke-width: 1", fill, stroke),
        tx: 0.0,
        ty: 0.0,
        title: None,
        inner: vec![rect(-5.0, -5.0, 10.0, 10.0, 2.0)],
        kids: vec![],
    }
}

pub fn swatch(s: &Series) -> El {
    let h = hue(s.index);
    let mut s = s.clone();
    if is_list(&s.fill) {
        s.fill = None;
    }
    if is_list(&s.stroke) {
        s.stroke = None;
    }
    let s = &s;
    match s.kind {
        Kind::Bars => {
            let (fill, stroke, _) = bar_colors(s, 0);
            match stroke {
                Some(st) => swatch_outlined(&fill, &st),
                None => swatch_filled(&fill),
            }
        }
        Kind::Area => {
            let fill = color_at(&s.fill, 0).unwrap_or_else(|| format!("var(--lini-{}-soft)", h));
            let st = color_at(&s.stroke, 0).unwrap_or_else(|| deep_of(&fill));
            swatch_outlined(&fill, &st)
        }
        Kind::Line => {
            if s.stroke.is_some() {
                let c = series_line_color(s);
                swatch_outlined(&c, &c)
            } else {
                swatch_filled(&series_line_color(s))
            }
        }
        Kind::Dots => {
            let c = color_at(&s.fill, 0)
                .or_else(|| color_at(&s.stroke, 0))
                .unwrap_or_else(|| format!("var(--lini-{}-ink)", h));
            match color_at(&s.stroke, 0) {
                Some(st) => swatch_outlined(&c, &st),
                None => swatch_filled(&c),
            }
        }
        Kind::Bubble => swatch_filled(&color_at(&s.fill, 0).unwrap_or_else(|| format!("var(--lini-{})", h))),
    }
}

// The colour of a line series: stroke, else fill, else the walk's deep tier.
pub fn series_line_color(s: &Series) -> String {
    if let Some(c) = color_at(&s.stroke, 0) {
        return c;
    }
    if let Some(c) = color_at(&s.fill, 0) {
        return c;
    }
    format!("var(--lini-{}-deep)", hue(s.index))
}

// An area's outline: its colour and width, never a dash pattern.
pub fn outline_style(color: &str, s: &Series) -> String {
    let mut st = format!("stroke: {}", color);
    if let Some(w) = s.stroke_width {
        st.push_str(&format!("; stroke-width: {}", f4(w)));
    }
    st
}

pub fn line_style(color: &str, s: &Series) -> String {
    let mut st = format!("stroke: {}", color);
    if let Some(w) = s.stroke_width {
        st.push_str(&format!("; stroke-width: {}", f4(w)));
    }
    if let Some(ss) = &s.stroke_style {
        if ss != "solid" {
            if let Some(d) = crate::style::dasharray(ss, s.stroke_width.unwrap_or(2.0)) {
                st.push_str(&format!("; stroke-dasharray: {}", d));
            }
        }
    }
    st
}

// (fill, stroke or None for no outline, stroke width) of bar k.
pub fn bar_colors(s: &Series, k: usize) -> (String, Option<String>, f64) {
    let h = hue(s.index);
    let fill = match &s.fill {
        Some(v) if crate::style::single_term(v).map(|t| matches!(t, Term::Var(n, _) if n == "fill")).unwrap_or(false) => format!("var(--lini-{}-soft)", h),
        _ => color_at(&s.fill, k).unwrap_or_else(|| format!("var(--lini-{}-soft)", h)),
    };
    let none = s.stroke.as_ref().and_then(|v| crate::style::ident_of(v)) == Some("none");
    if none {
        return (fill, None, 0.0);
    }
    let stroke = color_at(&s.stroke, k).unwrap_or_else(|| deep_of(&fill));
    (fill, Some(stroke), s.stroke_width.unwrap_or(2.0))
}

// The drawn path through the points for a curve style.
pub fn curve_points(pts: &[(f64, f64)], curve: &str, horiz: bool) -> Vec<(f64, f64)> {
    match curve {
        "step" => {
            let mut out = Vec::new();
            for (k, p) in pts.iter().enumerate() {
                if k == 0 {
                    out.push(*p);
                } else {
                    let prev = pts[k - 1];
                    let _ = horiz;
                    out.push((p.0, prev.1));
                    out.push(*p);
                }
            }
            out
        }
        "smooth" => smooth(pts),
        _ => pts.to_vec(),
    }
}

// Monotone cubic (Fritsch–Carlson) through the points, 16 samples per
// segment, evaluated in Hermite form.
pub fn smooth(pts: &[(f64, f64)]) -> Vec<(f64, f64)> {
    let n = pts.len();
    if n < 3 {
        return pts.to_vec();
    }
    let mut d = vec![0.0; n - 1];
    let mut hs = vec![0.0; n - 1];
    for k in 0..n - 1 {
        hs[k] = pts[k + 1].0 - pts[k].0;
        // a riser (no run) has no slope: flat tangents at both its ends
        d[k] = if hs[k] == 0.0 { 0.0 } else { (pts[k + 1].1 - pts[k].1) / hs[k] };
    }
    let mut m = vec![0.0; n];
    m[0] = d[0];
    m[n - 1] = d[n - 2];
    for k in 1..n - 1 {
        m[k] = if d[k - 1] * d[k] <= 0.0 { 0.0 } else { (d[k - 1] + d[k]) / 2.0 };
    }
    for k in 0..n - 1 {
        if d[k] == 0.0 {
            m[k] = 0.0;
            m[k + 1] = 0.0;
            continue;
        }
        let a = m[k] / d[k];
        let b = m[k + 1] / d[k];
        let s = a * a + b * b;
        if s > 9.0 {
            let t = 3.0 / s.sqrt();
            m[k] = t * a * d[k];
            m[k + 1] = t * b * d[k];
        }
    }
    let mut out = vec![pts[0]];
    for k in 0..n - 1 {
        let (x0, y0) = pts[k];
        let (_, y1) = pts[k + 1];
        let h = hs[k];
        for j in 1..=16 {
            let t = j as f64 / 16.0;
            let t2 = t * t;
            let t3 = t2 * t;
            let x = x0 + h * t;
            let y = (2.0 * t3 - 3.0 * t2 + 1.0) * y0 + (t3 - 2.0 * t2 + t) * h * m[k] + (-2.0 * t3 + 3.0 * t2) * y1 + (t3 - t2) * h * m[k + 1];
            out.push((x, y));
        }
    }
    out
}

// A centred marker at (px, py): a diamond polygon for 'marker: diamond',
// else an ellipse. `cls` is the hit-class prefix ("lini-hit-k " or "").
#[allow(clippy::too_many_arguments)]
pub fn mark_shape(diamond: bool, cls: String, style: String, px: f64, py: f64, r: f64, title: Option<String>, flags: &mut Flags) -> El {
    let (cls, inner) = if diamond {
        flags.diamond = true;
        (format!("{}lini-diamond", cls), format!("<polygon points=\"0,{} {},0 0,{} {},0\"/>", f4(-r), f4(r), f4(r), f4(-r)))
    } else {
        flags.oval = true;
        (format!("{}lini-oval", cls), format!("<ellipse cx=\"0\" cy=\"0\" rx=\"{}\" ry=\"{}\"/>", f4(r), f4(r)))
    };
    El::G { cls, style, tx: px, ty: py, title, inner: vec![inner], kids: vec![] }
}

// A line marker's radius: a dot grows with the line's width, a circle
// (or diamond) is 3 wider.
pub fn marker_radius(s: &Series) -> f64 {
    let dot = (1.25 * s.stroke_width.unwrap_or(2.0)).max(2.5);
    match s.marker.as_deref() {
        Some("circle") | Some("diamond") => dot + 3.0,
        Some(_) => dot,
        None => 0.0,
    }
}
