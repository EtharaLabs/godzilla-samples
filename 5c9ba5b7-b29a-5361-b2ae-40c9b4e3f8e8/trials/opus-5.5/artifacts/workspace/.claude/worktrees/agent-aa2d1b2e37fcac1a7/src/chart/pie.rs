// Pie and donut charts.

use super::cart::{legend_row, swatch_filled, swatch_outlined};
use super::model::*;
use super::scale::*;
use super::*;
use crate::compile::Ctx;
use crate::diag::Diag;

pub fn draw(ctx: &Ctx, ch: &Chart, w: f64, h: f64) -> Result<Drawing, Diag> {
    let _ = ctx;
    let mut flags = Flags::default();
    let g = ch.gap;
    let (cl, cr, ct, cb) = (-w / 2.0, w / 2.0, -h / 2.0, h / 2.0);
    let named: Vec<usize> = (0..ch.slices.len()).filter(|&k| ch.slices[k].name.is_some()).collect();
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
    let r = ((region_bottom - region_top) / 2.0).min((cr - cl - 16.0) / 2.0) + 8.0 - ch.clearance;
    let rin = ch.hole * r;
    let total: f64 = ch.slices.iter().map(|s| s.value).sum();
    let show_tips = ch.tooltip != "none";
    let mut els = Vec::new();
    let mut hits: Vec<(f64, f64, String)> = Vec::new();
    let mut a0 = -90.0f64;
    for (k, s) in ch.slices.iter().enumerate() {
        let frac = if total > 0.0 { s.value / total } else { 0.0 };
        let a1 = a0 + frac * 360.0;
        if s.value <= 0.0 {
            a0 = a1;
            continue;
        }
        let n = ((frac * 64.0 - 1e-9).ceil() as usize).max(2);
        let mut pts = Vec::new();
        for j in 0..=n {
            let a = (a0 + (a1 - a0) * j as f64 / n as f64).to_radians();
            pts.push((cx + r * a.cos(), cy + r * a.sin()));
        }
        if rin > 0.0 {
            for j in (0..=n).rev() {
                let a = (a0 + (a1 - a0) * j as f64 / n as f64).to_radians();
                pts.push((cx + rin * a.cos(), cy + rin * a.sin()));
            }
        } else {
            pts.push((cx, cy));
        }
        let h_ = hue(k);
        let fill = color_at(&s.fill, 0).unwrap_or_else(|| format!("var(--lini-{}-soft)", h_));
        let stroke = color_at(&s.stroke, 0).unwrap_or_else(|| deep_of(&fill));
        let unstroked = s.stroke.as_ref().and_then(crate::style::ident_of) == Some("none");
        let paint = if unstroked {
            format!("fill: {}; stroke: none; stroke-width: 0; opacity: 1", fill)
        } else {
            format!("fill: {}; stroke: {}; stroke-width: {}; opacity: 1", fill, stroke, f4(s.stroke_width.unwrap_or(2.0)))
        };
        let pct = format!("{}%", fixed0(frac * 100.0));
        let val = fmt_value(s.value, ch.format.as_ref());
        let tt = match &s.name {
            Some(nm) => format!("{}: {} ({})", nm, val, pct),
            None => format!("{} ({})", val, pct),
        };
        let hk = hits.len();
        flags.poly = true;
        let cls = if show_tips { format!("lini-hit-{} ", hk) } else { String::new() };
        els.push(poly_el(
            &cls,
            &pts,
            &paint,
            if show_tips { Some(tt.clone()) } else { None },
        ));
        if show_tips {
            let (bx, by) = bbox_center(&pts);
            hits.push((bx, by, tt));
        }
        a0 = a1;
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
                let s = &ch.slices[k];
                let fill = color_at(&s.fill, 0).unwrap_or_else(|| format!("var(--lini-{}-soft)", hue(k)));
                let stroke = color_at(&s.stroke, 0).unwrap_or_else(|| deep_of(&fill));
                if s.stroke.as_ref().and_then(crate::style::ident_of) == Some("none") {
                    (s.name.clone().unwrap(), swatch_filled(&fill))
                } else {
                    (s.name.clone().unwrap(), swatch_outlined(&fill, &stroke))
                }
            })
            .collect();
        legend_row(&mut els, items, cb - 10.8);
    }
    if show_tips && !hits.is_empty() {
        flags.tip = true;
        flags.text = true;
        flags.hits = hits.len();
        for (k, (x, y, t)) in hits.iter().enumerate() {
            els.push(tip_el(k, *x, *y, t, [cl, ct, cr, cb]));
        }
    }
    Ok(Drawing { els, flags, bbox: None })
}

fn fixed0(v: f64) -> String {
    format!("{}", v.round() as i64)
}

pub fn bbox_center(pts: &[(f64, f64)]) -> (f64, f64) {
    let mut b = [f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY];
    for &(x, y) in pts {
        b[0] = b[0].min(x);
        b[1] = b[1].min(y);
        b[2] = b[2].max(x);
        b[3] = b[3].max(y);
    }
    ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)
}
