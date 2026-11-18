// Layout: sizes and centre positions for the node tree.

use crate::compile::{Align, Ctx, Dir};
use crate::font;
use crate::types::Prim;

pub fn outer(ctx: &Ctx, i: usize) -> (f64, f64) {
    let n = &ctx.nodes[i];
    let c = &ctx.comp[i];
    if n.prim == Prim::Text || n.prim == Prim::Icon || n.prim == Prim::Image {
        return (n.w, n.h);
    }
    let s = if c.has_stroke { c.stroke_width } else { 0.0 };
    (n.w + s, n.h + s)
}

pub fn transform_text(s: &str, tt: &Option<String>) -> String {
    match tt.as_deref() {
        Some("uppercase") => s.to_uppercase(),
        Some("lowercase") => s.to_lowercase(),
        Some("capitalize") => {
            let mut out = String::new();
            let mut start = true;
            for ch in s.chars() {
                if start && ch.is_alphabetic() {
                    out.extend(ch.to_uppercase());
                    start = false;
                } else {
                    out.push(ch);
                    if ch.is_whitespace() {
                        start = true;
                    } else {
                        start = false;
                    }
                }
            }
            out
        }
        _ => s.to_string(),
    }
}

pub fn line_width(ctx: &Ctx, i: usize, s: &str) -> f64 {
    let c = &ctx.comp[i];
    let w = font::text_width(c.family, c.font_weight, c.font_size, s);
    let n = s.chars().count();
    if n > 1 {
        w + c.letter_spacing * (n as f64 - 1.0)
    } else {
        w
    }
}

// Greedy word wrap at the given width.
pub fn wrap(ctx: &Ctx, i: usize, text: &str, maxw: f64) -> Vec<String> {
    let mut out = Vec::new();
    for para in text.split('\n') {
        let words: Vec<&str> = para.split(' ').filter(|w| !w.is_empty()).collect();
        if words.is_empty() {
            out.push(String::new());
            continue;
        }
        let mut cur = String::new();
        for w in words {
            if !cur.is_empty() {
                let cand = format!("{} {}", cur, w);
                if line_width(ctx, i, &cand) <= maxw {
                    cur = cand;
                    continue;
                }
                out.push(std::mem::take(&mut cur));
            }
            // a word wider than the line breaks at the last character that fits
            let mut rest: Vec<char> = w.chars().collect();
            while rest.len() > 1 && line_width(ctx, i, &rest.iter().collect::<String>()) > maxw {
                let mut k = 1;
                while k < rest.len() && line_width(ctx, i, &rest[..k + 1].iter().collect::<String>()) <= maxw {
                    k += 1;
                }
                out.push(rest[..k].iter().collect());
                rest = rest[k..].to_vec();
            }
            cur = rest.into_iter().collect();
        }
        out.push(cur);
    }
    out
}

pub fn text_block_height(ctx: &Ctx, i: usize, nlines: usize) -> f64 {
    let c = &ctx.comp[i];
    if nlines <= 1 {
        c.font_size
    } else {
        nlines as f64 * 1.2 * c.font_size + (nlines as f64 - 1.0) * c.line_spacing
    }
}

pub fn measure_text(ctx: &mut Ctx, i: usize, avail: Option<f64>) {
    let raw = ctx.nodes[i].text.clone().unwrap_or_default();
    let tt = ctx.comp[i].text_transform.clone();
    let text = transform_text(raw.trim(), &tt);
    let lines: Vec<String> = match avail {
        Some(m) if !ctx.comp[i].nowrap => wrap(ctx, i, &text, m),
        _ => text.split('\n').map(|s| s.to_string()).collect(),
    };
    let mut w: f64 = 0.0;
    for l in &lines {
        w = w.max(line_width(ctx, i, l));
    }
    let h = text_block_height(ctx, i, lines.len());
    let n = &mut ctx.nodes[i];
    n.lines = lines;
    n.w = w;
    n.h = h;
}

pub fn measure(ctx: &mut Ctx, i: usize, avail: Option<f64>) {
    if crate::drawing::claims(ctx, i) {
        return crate::drawing::measure(ctx, i, avail);
    }
    if crate::tree::is_container(i) {
        return crate::tree::measure(ctx, i, avail);
    }
    let prim = ctx.nodes[i].prim;
    if prim == Prim::Block && ctx.nodes[i].is("page") {
        return crate::page::measure(ctx, i, avail);
    }
    match prim {
        Prim::Text => measure_text(ctx, i, avail),
        Prim::Line | Prim::Poly | Prim::Path => measure_geo(ctx, i),
        Prim::Icon | Prim::Image => crate::icon::measure(ctx, i, avail),
        _ => {
            if crate::chart::is_chart(ctx, i) {
                crate::chart::measure(ctx, i)
            } else if ctx.comp[i].layout == "grid" {
                measure_grid(ctx, i, avail)
            } else {
                measure_flow(ctx, i, avail)
            }
        }
    }
}

#[derive(Clone, Debug)]
pub enum Track {
    Auto,
    Fixed(f64),
}

pub fn parse_tracks(ctx: &Ctx, v: &crate::ast::Value) -> Vec<Track> {
    use crate::ast::{Expr, Term};
    let env = &ctx.sheet.env;
    let mut out = Vec::new();
    for g in &v.groups {
        for t in g {
            match t {
                Term::Ident(s, _) if s == "auto" => out.push(Track::Auto),
                Term::Call(name, args, _) if name == "repeat" => {
                    let n = args.first().and_then(|a| env.eval(a, &Default::default()).ok()).and_then(|x| x.num()).unwrap_or(1.0) as usize;
                    let tr = match args.get(1) {
                        Some(Expr::Ident(s, _)) if s == "auto" => Track::Auto,
                        Some(a) => match env.eval(a, &Default::default()).ok().and_then(|x| x.num()) {
                            Some(x) => Track::Fixed(x),
                            None => Track::Auto,
                        },
                        None => Track::Auto,
                    };
                    for _ in 0..n {
                        out.push(tr.clone());
                    }
                }
                _ => {
                    if let Some(x) = crate::style::term_num(env, t) {
                        out.push(Track::Fixed(x));
                    }
                }
            }
        }
    }
    out
}

// Grid placement in document order: an explicit `cell:` takes its slot, the
// rest take the first free slot (row-major) their span fits in. Items are (explicit cell,
// column span, row span); returns (col, row, colspan, rowspan) per item and
// the row count.
pub fn grid_place(ncols: usize, items: &[(Option<(usize, usize)>, usize, usize)]) -> (Vec<(usize, usize, usize, usize)>, usize) {
    let ncols = ncols.max(1);
    let mut occupied: Vec<Vec<bool>> = Vec::new();
    let mut place: Vec<(usize, usize, usize, usize)> = Vec::new();
    let ensure = |occ: &mut Vec<Vec<bool>>, r: usize| {
        while occ.len() <= r {
            occ.push(vec![false; ncols]);
        }
    };
    for &(cell, cs0, rs0) in items {
        let cs = cs0.max(1).min(ncols);
        let rs = rs0.max(1);
        if let Some((cc, rr)) = cell {
            ensure(&mut occupied, rr + rs - 1);
            for r in rr..rr + rs {
                for k in cc..(cc + cs).min(ncols) {
                    occupied[r][k] = true;
                }
            }
            place.push((cc, rr, cs, rs));
            continue;
        }
        // dense: every auto item takes the first slot it fits, holes included
        let mut cur_r = 0usize;
        let mut cur_c = 0usize;
        loop {
            ensure(&mut occupied, cur_r + rs - 1);
            if cur_c + cs > ncols {
                cur_c = 0;
                cur_r += 1;
                continue;
            }
            let mut free = true;
            for r in cur_r..cur_r + rs {
                ensure(&mut occupied, r);
                for k in cur_c..cur_c + cs {
                    if occupied[r][k] {
                        free = false;
                    }
                }
            }
            if free {
                break;
            }
            cur_c += 1;
        }
        for r in cur_r..cur_r + rs {
            for k in cur_c..cur_c + cs {
                occupied[r][k] = true;
            }
        }
        place.push((cur_c, cur_r, cs, rs));
    }
    let nrows = occupied.len();
    (place, nrows)
}

// Gap-fill gutters as segments: a boundary between two tracks is drawn
// wherever the slots on its two sides belong to different items and at
// least one is filled; runs end at mid-gap, or at the track area's edge.
pub fn grid_gutters(
    owner: &[Vec<Option<usize>>],
    colx: &[f64],
    colw: &[f64],
    rowy: &[f64],
    rowh: &[f64],
    gc: f64,
    gr: f64,
) -> Vec<(f64, f64, f64, f64)> {
    let ncols = colx.len();
    let nrows = rowy.len();
    let mut g = Vec::new();
    if ncols == 0 || nrows == 0 {
        return g;
    }
    let left = colx[0];
    let right = colx[ncols - 1] + colw[ncols - 1];
    let top = rowy[0];
    let bottom = rowy[nrows - 1] + rowh[nrows - 1];
    if gc > 0.0 {
        for k in 0..ncols - 1 {
            let open: Vec<bool> = (0..nrows)
                .map(|r| {
                    let a = owner[r][k];
                    let b = owner[r][k + 1];
                    a != b && (a.is_some() || b.is_some())
                })
                .collect();
            let mut r = 0;
            while r < nrows {
                if !open[r] {
                    r += 1;
                    continue;
                }
                let r0 = r;
                while r + 1 < nrows && open[r + 1] {
                    r += 1;
                }
                let y0 = if r0 == 0 { top } else { rowy[r0] - gr / 2.0 };
                let y1 = if r == nrows - 1 { bottom } else { rowy[r] + rowh[r] + gr / 2.0 };
                g.push((colx[k] + colw[k], y0, gc, y1 - y0));
                r += 1;
            }
        }
    }
    if gr > 0.0 {
        for r in 0..nrows - 1 {
            let open: Vec<bool> = (0..ncols)
                .map(|k| {
                    let a = owner[r][k];
                    let b = owner[r + 1][k];
                    a != b && (a.is_some() || b.is_some())
                })
                .collect();
            let mut k = 0;
            while k < ncols {
                if !open[k] {
                    k += 1;
                    continue;
                }
                let k0 = k;
                while k + 1 < ncols && open[k + 1] {
                    k += 1;
                }
                let x0 = if k0 == 0 { left } else { colx[k0] - gc / 2.0 };
                let x1 = if k == ncols - 1 { right } else { colx[k] + colw[k] + gc / 2.0 };
                g.push((x0, rowy[r] + rowh[r], x1 - x0, gr));
                k += 1;
            }
        }
    }
    g
}

pub fn measure_grid(ctx: &mut Ctx, i: usize, avail: Option<f64>) {
    let c = ctx.comp[i].clone();
    let pad = c.padding;
    let _ = avail;
    // a table reads align/justify per column; its own tracks always stretch
    let is_table = ctx.nodes[i].is("table");
    let (galign, gjustify) = if is_table { (Align::Stretch, Align::Stretch) } else { (c.align, c.justify) };
    let props = ctx.nodes[i].props.clone();
    let cols = props.get("columns").map(|v| parse_tracks(ctx, v)).unwrap_or_else(|| vec![Track::Auto]);
    let row_specs = props.get("rows").map(|v| parse_tracks(ctx, v)).unwrap_or_default();
    let ncols = cols.len().max(1);
    let children = ctx.nodes[i].children.clone();
    let mut flow = Vec::new();
    let mut pinned = Vec::new();
    for &ch in &children {
        if ctx.comp[ch].pin.is_some() {
            pinned.push(ch);
        } else {
            flow.push(ch);
        }
    }
    for &ch in &children {
        measure(ctx, ch, None);
    }
    // placement: (col, row, colspan, rowspan)
    let env = ctx.sheet.env.clone();
    let mut items = Vec::new();
    for &ch in &flow {
        let p = &ctx.nodes[ch].props;
        let span: Vec<f64> = p.get("span").map(|v| crate::style::value_nums(&env, v)).unwrap_or_default();
        let cs = span.first().map(|x| *x as usize).unwrap_or(1).max(1);
        let rs = span.get(1).map(|x| *x as usize).unwrap_or(1).max(1);
        let cell = p
            .get("cell")
            .map(|v| crate::style::value_nums(&env, v))
            .filter(|cell| cell.len() >= 2)
            .map(|cell| ((cell[0] as usize).max(1) - 1, (cell[1] as usize).max(1) - 1));
        items.push((cell, cs, rs));
    }
    let (place, nrows) = grid_place(ncols, &items);
    // declared rows count even when empty; a grid with no items has no tracks
    let nrows = if flow.is_empty() { 0 } else { nrows.max(row_specs.len()) };
    let (gr, gc) = c.gap;
    let mut colw: Vec<f64> = vec![0.0; ncols];
    let mut rowh: Vec<f64> = vec![0.0; nrows];
    let col_fixed: Vec<Option<f64>> = (0..ncols).map(|k| match cols.get(k) { Some(Track::Fixed(x)) => Some(*x), _ => None }).collect();
    let row_fixed: Vec<Option<f64>> = (0..nrows).map(|k| match row_specs.get(k) { Some(Track::Fixed(x)) => Some(*x), _ => None }).collect();
    for k in 0..ncols {
        if let Some(x) = col_fixed[k] {
            colw[k] = x;
        }
    }
    for k in 0..nrows {
        if let Some(x) = row_fixed[k] {
            rowh[k] = x;
        }
    }
    let sizes: Vec<(f64, f64)> = flow.iter().map(|&ch| outer(ctx, ch)).collect();
    for (idx, &(cc, rr, cs, rs)) in place.iter().enumerate() {
        let (w, h) = sizes[idx];
        if cs == 1 && cc < ncols && col_fixed[cc].is_none() {
            colw[cc] = colw[cc].max(w);
        }
        if rs == 1 && row_fixed[rr].is_none() {
            rowh[rr] = rowh[rr].max(h);
        }
    }
    for (idx, &(cc, rr, cs, rs)) in place.iter().enumerate() {
        let (w, h) = sizes[idx];
        if cs > 1 && cc < ncols {
            let ce = (cc + cs).min(ncols);
            let cur: f64 = colw[cc..ce].iter().sum::<f64>() + gc * ((ce - cc) as f64 - 1.0);
            if w > cur {
                let autos: Vec<usize> = (cc..ce).filter(|k| col_fixed[*k].is_none()).collect();
                if !autos.is_empty() {
                    let extra = (w - cur) / autos.len() as f64;
                    for k in autos {
                        colw[k] += extra;
                    }
                }
            }
        }
        if rs > 1 {
            let re = (rr + rs).min(nrows);
            let cur: f64 = rowh[rr..re].iter().sum::<f64>() + gr * ((re - rr) as f64 - 1.0);
            if h > cur {
                let autos: Vec<usize> = (rr..re).filter(|k| row_fixed[*k].is_none()).collect();
                if !autos.is_empty() {
                    let extra = (h - cur) / autos.len() as f64;
                    for k in autos {
                        rowh[k] += extra;
                    }
                }
            }
        }
    }
    let cw: f64 = if flow.is_empty() { 0.0 } else { colw.iter().sum::<f64>() + gc * (ncols as f64 - 1.0).max(0.0) };
    let chh: f64 = rowh.iter().sum::<f64>() + gr * (nrows as f64 - 1.0).max(0.0);
    let mut w = cw + pad[1] + pad[3];
    let mut h = chh + pad[0] + pad[2];
    if let Some(fw) = c.width {
        // with nothing in the flow, a set size is the size
        w = if flow.is_empty() { fw } else { w.max(fw) };
    }
    if let Some(fh) = c.height {
        h = if flow.is_empty() { fh } else { h.max(fh) };
    }
    ctx.nodes[i].w = w;
    ctx.nodes[i].h = h;
    let x0 = -w / 2.0 + pad[3] + (w - pad[1] - pad[3] - cw) / 2.0;
    let y0 = -h / 2.0 + pad[0] + (h - pad[0] - pad[2] - chh) / 2.0;
    let mut colx = vec![0.0; ncols];
    let mut acc = x0;
    for k in 0..ncols {
        colx[k] = acc;
        acc += colw[k] + gc;
    }
    let mut rowy = vec![0.0; nrows];
    let mut acc = y0;
    for k in 0..nrows {
        rowy[k] = acc;
        acc += rowh[k] + gr;
    }
    if ctx.nodes[i].props.contains_key("gap-fill") {
        let mut owner: Vec<Vec<Option<usize>>> = vec![vec![None; ncols]; nrows];
        for (idx, &(cc, rr, cs, rs)) in place.iter().enumerate() {
            for r in rr..(rr + rs).min(nrows) {
                for k in cc..(cc + cs).min(ncols) {
                    owner[r][k] = Some(idx);
                }
            }
        }
        ctx.nodes[i].gutters = grid_gutters(&owner, &colx, &colw, &rowy, &rowh, gc, gr);
    }
    // centred cells: each cell's span is found from the content's corner
    // and its middle taken there, then the content is centred
    let sym = (w - pad[1] - pad[3] - cw).abs() < 1e-9 && (h - pad[0] - pad[2] - chh).abs() < 1e-9 && pad[1] == pad[3] && pad[0] == pad[2];
    let mut ccolx = vec![0.0; ncols];
    let mut acc = 0.0;
    for k in 0..ncols {
        ccolx[k] = acc;
        acc += colw[k] + gc;
    }
    let ccw = acc - gc;
    let mut crowy = vec![0.0; nrows];
    let mut acc = 0.0;
    for k in 0..nrows {
        crowy[k] = acc;
        acc += rowh[k] + gr;
    }
    let cch = acc - gr;
    for (idx, &ch) in flow.iter().enumerate() {
        let (cc, rr, cs, rs) = place[idx];
        let cc = cc.min(ncols - 1);
        let cx0 = colx[cc];
        let ce = (cc + cs).min(ncols);
        let cwid: f64 = colw[cc..ce].iter().sum::<f64>() + gc * ((ce - cc) as f64 - 1.0);
        let ry0 = if rr < nrows { rowy[rr] } else { 0.0 };
        let re = (rr + rs).min(nrows);
        let rhei: f64 = if rr < re { rowh[rr..re].iter().sum::<f64>() + gr * ((re - rr) as f64 - 1.0) } else { 0.0 };
        let stretched = stretch_child(ctx, ch, galign == Align::Stretch, gjustify == Align::Stretch, cwid, rhei);
        let (ow, oh) = if stretched { outer(ctx, ch) } else { sizes[idx] };
        let x = match galign {
            Align::Start => cx0 + ow / 2.0,
            Align::End => cx0 + cwid - ow / 2.0,
            _ if sym => {
                let l = ccolx[cc];
                (l + (l + cwid)) / 2.0 - ccw / 2.0
            }
            _ => cx0 + cwid / 2.0,
        };
        let y = match gjustify {
            Align::Start => ry0 + oh / 2.0,
            Align::End => ry0 + rhei - oh / 2.0,
            _ if sym => {
                let t = crowy[rr];
                (t + (t + rhei)) / 2.0 - cch / 2.0
            }
            _ => ry0 + rhei / 2.0,
        };
        ctx.nodes[ch].x = x;
        ctx.nodes[ch].y = y;
    }
    for &p in &pinned {
        place_pinned(ctx, i, p);
    }
}

// Stretch a grid item to its slot (outer size = slot, along each stretched
// axis the item does not fix itself). Its content keeps its place, except a
// lone text leaf, which re-seats by the item's own `align` (x) and
// `justify` (y) where those are set. Returns whether anything stretched.
pub fn stretch_child(ctx: &mut Ctx, ch: usize, sx: bool, sy: bool, slot_w: f64, slot_h: f64) -> bool {
    match ctx.nodes[ch].prim {
        Prim::Text | Prim::Line | Prim::Poly | Prim::Path => return false,
        _ => {}
    }
    let c = ctx.comp[ch].clone();
    let sx = sx && c.width.is_none();
    let sy = sy && c.height.is_none();
    if !sx && !sy {
        return false;
    }
    let s = if c.has_stroke { c.stroke_width } else { 0.0 };
    if sx {
        ctx.nodes[ch].w = (slot_w - s).max(0.0);
    }
    if sy {
        ctx.nodes[ch].h = (slot_h - s).max(0.0);
    }
    let w = ctx.nodes[ch].w;
    let h = ctx.nodes[ch].h;
    let kids = ctx.nodes[ch].children.clone();
    if kids.len() == 1 && ctx.nodes[kids[0]].prim == Prim::Text {
        let t = kids[0];
        let pad = c.padding;
        let (tw, th) = (ctx.nodes[t].w, ctx.nodes[t].h);
        // the seat is the item's outer box (its slot, stroke included)
        let (ow, oh) = (w + s, h + s);
        let (l, r) = (-ow / 2.0 + pad[3], ow / 2.0 - pad[1]);
        let (top, bot) = (-oh / 2.0 + pad[0], oh / 2.0 - pad[2]);
        // only a start / end knob moves it; centre keeps its natural place
        match c.align {
            Align::Start => ctx.nodes[t].x = l + tw / 2.0,
            Align::End => ctx.nodes[t].x = r - tw / 2.0,
            _ => {}
        }
        match c.justify {
            Align::Start => ctx.nodes[t].y = top + th / 2.0,
            Align::End => ctx.nodes[t].y = bot - th / 2.0,
            _ => {}
        }
    }
    for k in kids {
        if ctx.comp[k].pin.is_some() {
            place_pinned(ctx, ch, k);
        }
    }
    true
}

pub fn measure_flow(ctx: &mut Ctx, i: usize, avail: Option<f64>) {
    let c = ctx.comp[i].clone();
    let pad = c.padding;
    let mut inner_avail = avail.map(|a| a - pad[1] - pad[3]);
    if let Some(m) = c.max_width {
        // the wrap width clears the padding and the stroke-width (drawn or not)
        let a = m - pad[1] - pad[3] - c.stroke_width;
        inner_avail = Some(inner_avail.map_or(a, |x: f64| x.min(a)));
    }
    let children = ctx.nodes[i].children.clone();
    let mut flow = Vec::new();
    let mut pinned = Vec::new();
    for &ch in &children {
        if ctx.comp[ch].pin.is_some() {
            pinned.push(ch);
        } else {
            flow.push(ch);
        }
    }
    for &ch in &children {
        measure(ctx, ch, if ctx.comp[ch].pin.is_some() { None } else { inner_avail });
    }
    let sizes: Vec<(f64, f64)> = flow.iter().map(|&ch| outer(ctx, ch)).collect();
    let (gap_main, row) = match c.direction {
        Dir::Row => (c.gap.1, true),
        Dir::Column => (c.gap.0, false),
    };
    let n = sizes.len();
    let mut main: f64 = 0.0;
    let mut cross: f64 = 0.0;
    for &(w, h) in &sizes {
        if row {
            main += w;
            cross = cross.max(h);
        } else {
            main += h;
            cross = cross.max(w);
        }
    }
    if n > 1 {
        main += gap_main * (n as f64 - 1.0);
    }
    let (cw, ch) = if row { (main, cross) } else { (cross, main) };
    let mut w = cw + pad[1] + pad[3];
    let mut h = ch + pad[0] + pad[2];
    // with nothing in flow, an explicit size replaces the padding box
    if let Some(fw) = c.width {
        w = if n == 0 { fw } else { w.max(fw) };
    }
    if let Some(fh) = c.height {
        h = if n == 0 { fh } else { h.max(fh) };
    }
    ctx.nodes[i].w = w;
    ctx.nodes[i].h = h;
    // place flow children
    let inner_l = -w / 2.0 + pad[3];
    let inner_t = -h / 2.0 + pad[0];
    let inner_w = w - pad[1] - pad[3];
    let inner_h = h - pad[0] - pad[2];
    let free = if row { inner_w - main } else { inner_h - main };
    let start = match c.justify {
        Align::Start | Align::Stretch => 0.0,
        Align::Center => free / 2.0,
        Align::End => free,
    };
    let mut cursor = start;
    // centred content with even padding: the cursor runs from -main/2
    let centred = free.abs() < 1e-9 && if row { pad[1] == pad[3] } else { pad[0] == pad[2] };
    let base = if centred { -main / 2.0 } else { 0.0 };
    if centred {
        cursor = base;
    }
    for (k, &chi) in flow.iter().enumerate() {
        let (ow, oh) = sizes[k];
        if row {
            let x = if centred { cursor + ow / 2.0 } else { inner_l + cursor + ow / 2.0 };
            let y = match c.align {
                Align::Start => inner_t + oh / 2.0,
                Align::End => inner_t + inner_h - oh / 2.0,
                _ => inner_t + inner_h / 2.0,
            };
            ctx.nodes[chi].x = x;
            ctx.nodes[chi].y = y;
            cursor += ow + gap_main;
        } else {
            let y = if centred { cursor + oh / 2.0 } else { inner_t + cursor + oh / 2.0 };
            let x = match c.align {
                Align::Start => inner_l + ow / 2.0,
                Align::End => inner_l + inner_w - ow / 2.0,
                _ => inner_l + inner_w / 2.0,
            };
            ctx.nodes[chi].x = x;
            ctx.nodes[chi].y = y;
            cursor += oh + gap_main;
        }
    }
    if ctx.nodes[i].props.contains_key("gap-fill") && n > 1 && gap_main > 0.0 {
        let mut g = Vec::new();
        let mut cur = start;
        for k in 0..n - 1 {
            let (ow, oh) = sizes[k];
            cur += if row { ow } else { oh };
            if row {
                g.push((inner_l + cur, -h / 2.0, gap_main, h));
            } else {
                g.push((-w / 2.0, inner_t + cur, w, gap_main));
            }
            cur += gap_main;
        }
        ctx.nodes[i].gutters = g;
    }
    if ctx.nodes[i].prim == Prim::Cyl {
        let (_, oh) = outer(ctx, i);
        let dy = 0.03 * oh;
        for &chi in &flow {
            ctx.nodes[chi].y += dy;
        }
    }
    for &p in &pinned {
        place_pinned(ctx, i, p);
    }
}

pub fn place_pinned(ctx: &mut Ctx, parent: usize, i: usize) {
    let pin = ctx.comp[i].pin.clone().unwrap_or_default();
    let pw = ctx.nodes[parent].w;
    let ph = ctx.nodes[parent].h;
    let (cw, chh) = outer(ctx, i);
    let words: Vec<&str> = pin.split_whitespace().collect();
    let mut x = 0.0;
    let mut y = 0.0;
    for w in &words {
        match *w {
            "top" => y = -ph / 2.0 + chh / 2.0,
            "bottom" => y = ph / 2.0 - chh / 2.0,
            "left" => x = -pw / 2.0 + cw / 2.0,
            "right" => x = pw / 2.0 - cw / 2.0,
            _ => {}
        }
    }
    ctx.nodes[i].x = x;
    ctx.nodes[i].y = y;
}

pub fn eval_points(ctx: &Ctx, i: usize) -> Vec<(f64, f64)> {
    use crate::ast::Term;
    use crate::eval::EV;
    let env = &ctx.sheet.env;
    let v = match ctx.nodes[i].props.get("points") {
        Some(v) => v.clone(),
        None => return vec![],
    };
    let samples = ctx.nodes[i].props.get("samples").and_then(|s| crate::style::value_num(env, s)).unwrap_or(2.0).max(2.0) as usize;
    let mut pts = Vec::new();
    for g in &v.groups {
        let nums: Vec<f64> = g.iter().filter_map(|t| crate::style::term_num(env, t)).collect();
        if g.len() == 2 && nums.len() == 2 {
            pts.push((nums[0], nums[1]));
            continue;
        }
        if g.len() == 1 {
            // a parametric point: sample u over [0, 1]
            let t = &g[0];
            for k in 0..samples {
                let u = k as f64 / (samples as f64 - 1.0);
                let mut locals = std::collections::HashMap::new();
                locals.insert("u".to_string(), EV::Num(u));
                let r = match t {
                    Term::Group(e, _) => env.eval(e, &locals),
                    Term::Call(..) => env.eval_term(t, &locals),
                    _ => continue,
                };
                if let Ok(EV::Tuple(xs)) = r {
                    if xs.len() >= 2 {
                        pts.push((xs[0].num().unwrap_or(0.0), xs[1].num().unwrap_or(0.0)));
                    }
                }
            }
        }
    }
    pts
}

pub fn measure_geo(ctx: &mut Ctx, i: usize) {
    use crate::geom::{path_bbox, BBox};
    use crate::scene::Geo;
    let prim = ctx.nodes[i].prim;
    let mut bb = BBox::empty();
    let geo = if prim == Prim::Path {
        let d = match ctx.nodes[i].props.get("path").and_then(crate::style::single_term) {
            Some(crate::ast::Term::Str(s, _)) => s.clone(),
            _ => String::new(),
        };
        bb = path_bbox(&d);
        Geo::Path(d)
    } else {
        let pts = eval_points(ctx, i);
        for &(x, y) in &pts {
            bb.add(x, y);
        }
        Geo::Points(pts)
    };
    let n = &mut ctx.nodes[i];
    n.w = bb.w();
    n.h = bb.h();
    n.geo_off = (-bb.cx(), -bb.cy());
    n.geo = Some(geo);
}
