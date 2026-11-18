// Radial (spider) charts: categories around a circle, values outward.

use super::cart::{legend_row, line_style, mark_shape, marker_radius, outline_style, place_label, series_line_color, swatch, Geo, Lab, VAxis};
use super::model::*;
use super::pie::bbox_center;
use super::scale::*;
use super::*;
use crate::compile::Ctx;
use crate::diag::Diag;

pub fn draw(ctx: &Ctx, ch: &Chart, w: f64, h: f64) -> Result<Drawing, Diag> {
    let _ = ctx;
    let mut flags = Flags::default();
    let c = ch.clearance;
    let g = ch.gap;
    let (cl, cr, ct, cb) = (-w / 2.0, w / 2.0, -h / 2.0, h / 2.0);
    let cats: Vec<String> = match &ch.categories {
        Some(c) => c.clone(),
        None => {
            let n = ch.series.iter().map(|s| s.vals.len()).max().unwrap_or(0);
            (1..=n).map(|k| k.to_string()).collect()
        }
    };
    let n = cats.len().max(1);
    let named: Vec<usize> = (0..ch.series.len()).filter(|&k| ch.series[k].name.is_some() && ch.series[k].kind != Kind::Bubble).collect();
    let legend = named.len() >= 2;
    let mut region_top = ct + 8.0;
    let mut title_y = 0.0;
    if ch.title.is_some() {
        title_y = region_top + 10.5;
        region_top = region_top + (18.0 + g);
    }
    let region_bottom = if legend { (cb - 10.8) - 6.0 - g + 0.4 } else { cb - 8.0 };
    let cy = (region_top + region_bottom) / 2.0;
    let cx = 0.0;
    let half = ((region_bottom - region_top) / 2.0).min((cr - cl - 16.0) / 2.0);
    let rr = half - c - 8.8;
    // the value axis
    let ax = ch.axes.iter().position(|_| true);
    for a in &ch.axes {
        if a.side.is_some() {
            return Err(Diag::error("layout", "'side' has no meaning in a radial chart — it has one radius axis", a.node_span));
        }
        if let Some((l, h)) = a.range {
            if l == h {
                return Err(Diag::error("layout", "'range' needs distinct ends", Default::default()));
            }
        }
    }
    let mut vals = Vec::new();
    let mut run = vec![0.0f64; n];
    let mut run_any = vec![false; n];
    for s in &ch.series {
        if s.kind == Kind::Bars && ch.bars_mode == "stacked" {
            // only each category's total counts
            for (k, v) in s.vals.iter().enumerate() {
                if k < n {
                    run[k] += v;
                    run_any[k] = true;
                }
            }
            continue;
        }
        vals.extend(s.vals.iter().cloned());
        if let Some(a) = s.at {
            vals.push(a.1);
        }
    }
    for k in 0..n {
        if run_any[k] {
            vals.push(run[k]);
        }
    }
    let va = value_axis_radial(ch, ax, &vals);
    let rad = |v: f64| -> f64 { va.frac(v) * rr };
    let ang = |k: usize| -> f64 { (-90.0 + 360.0 * k as f64 / n as f64).to_radians() };
    let pt = |k: usize, r: f64| -> (f64, f64) {
        let a = ang(k);
        (cx + r * a.cos(), cy + r * a.sin())
    };
    let mut els = Vec::new();
    let grid = "stroke: var(--lini-grid); stroke-width: 1";
    if va.gridlines {
        for &t in &va.ticks {
            let r = rad(t);
            if r <= 1e-9 {
                continue;
            }
            let mut pts: Vec<(f64, f64)> = (0..n).map(|k| pt(k, r)).collect();
            pts.push(pts[0]);
            flags.line = true;
            els.push(path_el(&pts, grid));
        }
        for k in 0..n {
            let p = pt(k, rr);
            flags.line = true;
            els.push(line_el(cx, cy, p.0, p.1, grid));
        }
    }
    let chart_tips = ch.tooltip != "none";
    let mut hits: Vec<(f64, f64, String)> = Vec::new();
    let fmt = ch.format.clone();
    let point_tip = |s: &Series, k: usize, v: f64| -> String {
        let val = fmt_value(v, fmt.as_ref());
        let cat = cats.get(k).cloned().unwrap_or_default();
        match &s.name {
            Some(nm) => format!("{}: {}: {}", nm, cat, val),
            None => format!("{}: {}", cat, val),
        }
    };
    let tip_text = |s: &Series, k: usize, v: f64| -> String {
        let val = fmt_value(v, fmt.as_ref());
        let cat = cats.get(k).cloned().unwrap_or_default();
        match &s.name {
            Some(nm) => format!("{} · {}: {}", cat, nm, val),
            None => format!("{}: {}", cat, val),
        }
    };
    let mut labels: Vec<Lab> = Vec::new();
    let mut obstacles: Vec<Vec<(f64, f64)>> = Vec::new();
    let mode_of = |s: &Series| -> String { s.tooltip.clone().unwrap_or_else(|| ch.tooltip.clone()) };
    let mut order: Vec<usize> = Vec::new();
    for kind in [Kind::Area, Kind::Bars, Kind::Line, Kind::Dots] {
        for (k, s) in ch.series.iter().enumerate() {
            if s.kind == kind {
                order.push(k);
            }
        }
    }
    let bar_series: Vec<usize> = (0..ch.series.len()).filter(|&k| ch.series[k].kind == Kind::Bars).collect();
    let nb = bar_series.len().max(1) as f64;
    let mut bars_done = false;
    for &si in &order {
        let s = &ch.series[si];
        let hn = hue(s.index);
        let show_tips = chart_tips && s.tooltip.as_deref().unwrap_or(ch.tooltip.as_str()) != "none";
        match s.kind {
            Kind::Area | Kind::Line => {
                let pts: Vec<(f64, f64)> = s.vals.iter().enumerate().map(|(k, v)| pt(k, rad(*v))).collect();
                obstacles.push(pts.clone());
                if matches!(mode_of(s).as_str(), "auto" | "always") {
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
                    // one point draws no outline or markers
                    continue;
                }
                let mut closed = pts.clone();
                if let Some(f) = pts.first() {
                    closed.push(*f);
                }
                if s.kind == Kind::Area {
                    let fill = color_at(&s.fill, 0).unwrap_or_else(|| format!("var(--lini-{}-soft)", hn));
                    flags.poly = true;
                    els.push(poly_el("", &pts, &format!("fill: {}; stroke: none; stroke-width: 0; opacity: 0.82", fill), None));
                    let lc = color_at(&s.stroke, 0).unwrap_or_else(|| deep_of(&fill));
                    flags.line = true;
                    els.push(path_el(&closed, &outline_style(&lc, s)));
                } else {
                    let color = series_line_color(s);
                    flags.line = true;
                    els.push(path_el(&closed, &line_style(&color, s)));
                }
                if let Some(mk) = &s.marker {
                    let _ = mk;
                    let r = marker_radius(s);
                    // an area's markers take its fill; a line's its stroke
                    let color = if s.kind == Kind::Area {
                        color_at(&s.fill, 0).unwrap_or_else(|| format!("var(--lini-{}-soft)", hn))
                    } else {
                        series_line_color(s)
                    };
                    for (k, (&v, p)) in s.vals.iter().zip(pts.iter()).enumerate() {
                        let tt = point_tip(s, k, v);
                        let hk = hits.len();
                        els.push(mark_shape(
                            s.marker.as_deref() == Some("diamond"),
                            if show_tips { format!("lini-hit-{} ", hk) } else { String::new() },
                            format!("fill: {}; stroke: none; stroke-width: 0", color),
                            p.0,
                            p.1,
                            r,
                            if show_tips { Some(tt.clone()) } else { None },
                            &mut flags,
                        ));
                        if show_tips {
                            hits.push((p.0, p.1, tt));
                        }
                    }
                }
            }
            Kind::Dots => {
                let base = format!("var(--lini-{}-ink)", hn);
                for (k, &v) in s.vals.iter().enumerate() {
                    let p = pt(k, rad(v));
                    let dot_fill = if is_list(&s.fill) {
                        color_at(&s.fill, k).unwrap_or_else(|| base.clone())
                    } else {
                        // the fill, else a single stroke colour, else the walk's ink
                        raw_term(&s.fill)
                            .or_else(|| if is_list(&s.stroke) { None } else { raw_term(&s.stroke) })
                            .unwrap_or_else(|| base.clone())
                    };
                    let (style, r) = if is_list(&s.stroke) {
                        let st = color_at(&s.stroke, k).unwrap_or_else(|| deep_of(&dot_fill));
                        (format!("fill: {}; stroke: {}; stroke-width: 2", dot_fill, st), 2.5)
                    } else {
                        (format!("fill: {}; stroke: none; stroke-width: 0", dot_fill), 3.5)
                    };
                    if matches!(mode_of(s).as_str(), "auto" | "always") {
                        if let Some(l) = s.labels.get(k) {
                            if !l.is_empty() {
                                labels.push(Lab { always: mode_of(s) == "always", si: s.node, x: p.0, y: p.1, r: 3.5, text: l.clone(), bubble: false });
                            }
                        }
                    }
                    let tt = point_tip(s, k, v);
                    let hk = hits.len();
                    els.push(mark_shape(
                        s.marker.as_deref() == Some("diamond"),
                        if show_tips { format!("lini-hit-{} ", hk) } else { String::new() },
                        style,
                        p.0,
                        p.1,
                        r,
                        if show_tips { Some(tt.clone()) } else { None },
                        &mut flags,
                    ));
                    if show_tips {
                        hits.push((p.0, p.1, tt));
                    }
                }
            }
            Kind::Bars => {
                if bars_done {
                    continue;
                }
                bars_done = true;
                let sector = 360.0 / n as f64;
                let group = 0.72 * sector;
                let stacked = ch.bars_mode == "stacked";
                let overlay = ch.bars_mode == "overlay";
                let slot = if stacked || overlay { group } else { group / nb };
                let mut stack = vec![0.0f64; n];
                for k in 0..n {
                    for (bk, &bsi) in bar_series.iter().enumerate() {
                        let s = &ch.series[bsi];
                        let show_tips = chart_tips && s.tooltip.as_deref().unwrap_or(ch.tooltip.as_str()) != "none";
                        let v = match s.vals.get(k) {
                            Some(v) => *v,
                            None => continue,
                        };
                        let mid = -90.0 + sector * k as f64;
                        let a0 = if stacked || overlay { mid - group / 2.0 } else { mid - group / 2.0 + slot * bk as f64 };
                        let a1 = a0 + slot;
                        let (v0, v1) = if stacked {
                            let b = stack[k];
                            stack[k] += v;
                            (b, b + v)
                        } else {
                            (0.0, v)
                        };
                        let r = rad(v1);
                        let segs = (((a1 - a0) / 360.0 * 64.0 - 1e-9).ceil() as usize).max(1);
                        let mut pts = Vec::new();
                        for j in 0..=segs {
                            let a = (a0 + (a1 - a0) * j as f64 / segs as f64).to_radians();
                            pts.push((cx + r * a.cos(), cy + r * a.sin()));
                        }
                        if stacked && v0 != 0.0 {
                            let r0 = rad(v0);
                            for j in (0..=segs).rev() {
                                let a = (a0 + (a1 - a0) * j as f64 / segs as f64).to_radians();
                                pts.push((cx + r0 * a.cos(), cy + r0 * a.sin()));
                            }
                        } else {
                            pts.push((cx, cy));
                        }
                        let fill = color_at(&s.fill, k).unwrap_or_else(|| format!("var(--lini-{}-soft)", hue(s.index)));
                        let stroke = color_at(&s.stroke, k).unwrap_or_else(|| deep_of(&fill));
                        let tt = tip_text(s, k, v);
                        let hk = hits.len();
                        flags.poly = true;
                        let cls = if show_tips { format!("lini-hit-{} ", hk) } else { String::new() };
                        els.push(poly_el(
                            &cls,
                            &pts,
                            &format!("fill: {}; stroke: {}; stroke-width: 2; opacity: {}", fill, stroke, if overlay { "0.6" } else { "1" }),
                            if show_tips { Some(tt.clone()) } else { None },
                        ));
                        if show_tips {
                            let (bx, by) = bbox_center(&pts);
                            hits.push((bx, by, tt));
                        }
                        if matches!(mode_of(s).as_str(), "auto" | "always") {
                            if let Some(l) = s.labels.get(k) {
                                if !l.is_empty() {
                                    // on the category's spoke, at the bar's own value
                                    let (lx, ly) = pt(k, rad(v));
                                    labels.push(Lab { always: mode_of(s) == "always", si: s.node, x: lx, y: ly, r: 0.0, text: l.clone(), bubble: false });
                                }
                            }
                        }
                    }
                }
            }
            _ => {}
        }
    }
    // bubbles: at (category position, value), radius ∝ √value, the largest
    // 0.14 of the plot square's side
    let bubbles: Vec<usize> = (0..ch.series.len()).filter(|&k| ch.series[k].kind == Kind::Bubble).collect();
    if !bubbles.is_empty() {
        let vmax = bubbles.iter().map(|&k| ch.series[k].value.unwrap_or(0.0)).fold(0.0f64, f64::max);
        let rmax = 0.14 * (2.0 * rr);
        for &bk in &bubbles {
            let s = &ch.series[bk];
            let show_tips = chart_tips && mode_of(s) != "none";
            let (ax, ay) = s.at.unwrap_or((0.0, 0.0));
            let v = s.value.unwrap_or(0.0);
            let r = if vmax > 0.0 { rmax * (v / vmax).sqrt() } else { 0.0 };
            let a = (-90.0 + 360.0 * ax / n as f64).to_radians();
            let rv = rad(ay);
            let (px, py) = (cx + rv * a.cos(), cy + rv * a.sin());
            let fill = color_at(&s.fill, 0).unwrap_or_else(|| format!("var(--lini-{})", hue(s.index)));
            let hk = hits.len();
            let tt = match &s.name {
                Some(nm) => format!("{}: {}", nm, fmt_value(v, fmt.as_ref())),
                None => fmt_value(v, fmt.as_ref()),
            };
            flags.oval = true;
            els.push(El::G {
                cls: if show_tips { format!("lini-hit-{} lini-oval", hk) } else { "lini-oval".into() },
                style: format!("fill: {}; stroke: none; stroke-width: 0", fill),
                tx: px,
                ty: py,
                title: if show_tips { Some(tt.clone()) } else { None },
                inner: vec![format!("<ellipse cx=\"0\" cy=\"0\" rx=\"{}\" ry=\"{}\"/>", crate::util::f4(r), crate::util::f4(r))],
                kids: vec![],
            });
            if show_tips {
                hits.push((px, py, tt));
            }
            if matches!(mode_of(s).as_str(), "auto" | "always") {
                if let Some(nm) = &s.name {
                    labels.push(Lab { always: mode_of(s) == "always", si: s.node, x: px, y: py, r, text: nm.clone(), bubble: true });
                }
            }
        }
    }
    let muted = "fill: var(--lini-muted)";
    let lab_els = {
        labels.sort_by_key(|l| l.si);
        let geo = Geo { l: cx - rr, r: cx + rr, t: cy - rr, b: cy + rr, horiz: false };
        let mut placed: Vec<[f64; 4]> = Vec::new();
        let mut out = Vec::new();
        for l in &labels {
            let w = tw(&l.text);
            if l.bubble && (w / 2.0).hypot(FS / 2.0) + c <= l.r {
                // a label that fits sits inside its bubble
                let bx = [l.x - w / 2.0 - 2.0, l.y - FS / 2.0 - 2.0, l.x + w / 2.0 + 2.0, l.y + FS / 2.0 + 2.0];
                if bx[0] >= geo.l && bx[2] <= geo.r && bx[1] >= geo.t && bx[3] <= geo.b {
                    placed.push(bx);
                    out.push(text_el("lini-chart-label", l.x, l.y, "fill: var(--lini-accent-text)", &l.text));
                    continue;
                }
            }
            if let Some((lx, ly)) = place_label(l, w, &geo, c, &obstacles, &mut placed, l.always) {
                out.push(text_el("lini-chart-label", lx, ly, muted, &l.text));
            }
        }
        out
    };
    for (k, name) in cats.iter().enumerate() {
        let a = ang(k);
        let (dx, dy) = (a.cos(), a.sin());
        let d = dx.abs() * tw(name) / 2.0 + dy.abs() * FS / 2.0;
        let dist = rr + c + d;
        flags.text = true;
        els.push(text_el("lini-chart-text", cx + dist * dx, cy + dist * dy, muted, name));
    }
    for (t, l) in va.ticks.iter().zip(va.labels.iter()) {
        let r = rad(*t);
        if r <= 1e-9 {
            continue;
        }
        flags.text = true;
        els.push(text_el("lini-chart-text", cx + c + tw(l) / 2.0, cy - r, muted, l));
    }
    if let Some(t) = &ch.title {
        flags.title = true;
        els.push(text_el("lini-chart-title", 0.0, title_y, "", t));
    }
    if legend {
        flags.legend = true;
        let items: Vec<(String, El)> = named
            .iter()
            .map(|&k| {
                let s = &ch.series[k];
                let sw = swatch(s);
                (s.name.clone().unwrap(), sw)
            })
            .collect();
        legend_row(&mut els, items, cb - 10.8);
    }
    for e in lab_els {
        flags.label = true;
        els.push(e);
    }
    if chart_tips && !hits.is_empty() {
        flags.tip = true;
        flags.text = true;
        flags.hits = hits.len();
        for (k, (x, y, t)) in hits.iter().enumerate() {
            els.push(tip_el(k, *x, *y, t, [cl, ct, cr, cb]));
        }
    }
    Ok(Drawing { els, flags, bbox: None })
}

fn value_axis_radial(ch: &Chart, ax: Option<usize>, vals: &[f64]) -> VAxis {
    let a = ax.map(|k| &ch.axes[k]);
    let (lo, hi, step) = match a.and_then(|a| a.range) {
        Some((l, h)) => {
            let s = match a.and_then(|a| a.step.clone()) {
                Some(StepSpec::Num(s)) if s > 0.0 => s,
                _ => nice_step((h - l).abs()),
            };
            (l, h, s)
        }
        None => {
            let mut mn = 0.0f64;
            let mut mx = 0.0f64;
            for &v in vals {
                mn = mn.min(v);
                mx = mx.max(v);
            }
            let s = match a.and_then(|a| a.step.clone()) {
                Some(StepSpec::Num(s)) if s > 0.0 => s,
                _ => nice_step(mx - mn),
            };
            let (l, h) = if mx == mn { (0.0, 1.0) } else { nice_domain(mn, mx, s) };
            (l, h, s)
        }
    };
    let mut ticks = ticks_in(lo, hi, step);
    if let Some(t) = a.and_then(|a| a.ticks.clone()) {
        ticks = t;
    }
    let unit = a.map(|a| a.unit.clone()).unwrap_or_default();
    let f = a.and_then(|a| a.format.clone()).or_else(|| ch.format.clone());
    let labels = ticks.iter().map(|v| format!("{}{}", fmt_tick(*v, step, f.as_ref()), unit)).collect();
    VAxis {
        ax,
        right: false,
        lo,
        hi,
        log: false,
        ticks,
        labels,
        title: a.and_then(|a| a.title.clone()),
        gridlines: true,
    }
}
