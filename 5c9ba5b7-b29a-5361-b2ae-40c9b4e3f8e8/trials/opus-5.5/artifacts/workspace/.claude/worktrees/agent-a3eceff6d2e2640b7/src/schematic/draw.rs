// The wires' SVG: each wire a `lini-link` group with its path and net name,
// the junction dots after them; and their stylesheet rules. A root
// schematic restyles the links themselves; a schematic nested in another
// layout marks its wires `lini-schematic-wire`.

use super::wire::WIRING;
use crate::compile::Ctx;
use crate::render::Out;
use crate::style::use_var;
use crate::util::{f4, xml_escape};

pub fn reset() {
    super::wire::reset();
    super::place::reset();
}

fn label_width(ctx: &Ctx, text: &str) -> f64 {
    let fam = crate::font::Family::Sans;
    let w = if ctx.comp[0].layout == "schematic" { ctx.comp[0].font_weight } else { 400 };
    crate::font::text_width(fam, w, 11.0, text)
}

pub fn extend_bbox(ctx: &Ctx, b: &mut [f64; 4]) {
    WIRING.with(|w| {
        let w = w.borrow();
        for r in &w.wires {
            for &(x, y) in &r.pts {
                b[0] = b[0].min(x);
                b[1] = b[1].min(y);
                b[2] = b[2].max(x);
                b[3] = b[3].max(y);
            }
            for (t, x, y, rot) in &r.labels {
                let tw = label_width(ctx, t);
                let (hw, hh) = if *rot != 0.0 { (5.5, tw / 2.0) } else { (tw / 2.0, 5.5) };
                b[0] = b[0].min(x - hw);
                b[1] = b[1].min(y - hh);
                b[2] = b[2].max(x + hw);
                b[3] = b[3].max(y + hh);
            }
        }
    });
}

// the schematic wires and junctions inside the links layer ("" when none)
pub fn render_links(ctx: &Ctx, out: &mut Out) -> Result<String, crate::diag::Diag> {
    super::sheet_vars(&mut out.vars);
    let mut s = String::new();
    WIRING.with(|w| {
        let w = w.borrow();
        if w.wires.is_empty() && w.strays.is_empty() {
            return;
        }
        let root = ctx.comp[0].layout == "schematic";
        let mut any_label = false;
        for r in &w.wires {
            let l = &ctx.links[r.li];
            let cls = if root { "lini-link".to_string() } else { "lini-link lini-schematic-wire".to_string() };
            s.push_str(&format!(
                "    <g class=\"{}\" data-from=\"{}\" data-to=\"{}\">\n",
                cls,
                xml_escape(&crate::links::path_of(ctx, l.from)),
                xml_escape(&crate::links::path_of(ctx, l.to))
            ));
            let mut d = String::new();
            for (k, &(x, y)) in r.pts.iter().enumerate() {
                if k > 0 {
                    d.push(' ');
                }
                d.push_str(&format!("{} {} {}", if k == 0 { "M" } else { "L" }, f4(x), f4(y)));
            }
            s.push_str(&format!("      <path d=\"{}\"/>\n", d));
            for (t, x, y, rot) in &r.labels {
                any_label = true;
                let style = if root {
                    String::new()
                } else {
                    " style=\"fill: var(--lini-label-ink); font-weight: var(--lini-font-weight)\"".to_string()
                };
                let turn = if *rot != 0.0 { format!(" transform=\"rotate({} {} {})\"", f4(*rot), f4(*x), f4(*y)) } else { String::new() };
                s.push_str(&format!(
                    "      <text class=\"lini-link-label\" x=\"{}\" y=\"{}\" dy=\"0.358em\"{}{}>{}</text>\n",
                    f4(*x),
                    f4(*y),
                    style,
                    turn,
                    xml_escape(t)
                ));
            }
            s.push_str("    </g>\n");
        }
        // the wires no route was found for: a dashed line between their
        // ends' boxes, a warning sign halfway
        for (li, a, b) in &w.strays {
            let l = &ctx.links[*li];
            use_var(&mut out.vars, "stray");
            use_var(&mut out.vars, "fill");
            let (p, q) = crate::links::stray_line(a, b);
            let m = ((p.0 + q.0) / 2.0, (p.1 + q.1) / 2.0);
            s.push_str(&format!(
                "    <g class=\"lini-stray\" data-from=\"{}\" data-to=\"{}\">\n",
                xml_escape(&crate::links::path_of(ctx, l.from)),
                xml_escape(&crate::links::path_of(ctx, l.to))
            ));
            s.push_str(&format!(
                "      <path d=\"M {} {} L {} {}\" fill=\"none\" stroke=\"var(--lini-stray)\" stroke-width=\"1.5\" stroke-dasharray=\"6,4\"/>\n",
                f4(p.0),
                f4(p.1),
                f4(q.0),
                f4(q.1)
            ));
            s.push_str(&format!(
                "      <path d=\"M {} {} L {} {} L {} {} Z\" fill=\"var(--lini-fill)\" stroke=\"var(--lini-stray)\" stroke-width=\"1.5\" stroke-linejoin=\"round\"/>\n",
                f4(m.0),
                f4(m.1 - 6.5),
                f4(m.0 + 7.0),
                f4(m.1 + 5.5),
                f4(m.0 - 7.0),
                f4(m.1 + 5.5)
            ));
            s.push_str(&format!(
                "      <path d=\"M {} {} L {} {}\" stroke=\"var(--lini-stray)\" stroke-width=\"1.6\" stroke-linecap=\"round\"/>\n",
                f4(m.0),
                f4(m.1 - 2.5),
                f4(m.0),
                f4(m.1 + 1.0)
            ));
            s.push_str(&format!("      <circle cx=\"{}\" cy=\"{}\" r=\"0.9\" fill=\"var(--lini-stray)\"/>\n", f4(m.0), f4(m.1 + 3.6)));
            s.push_str("    </g>\n");
        }
        for &(x, y) in &w.junctions {
            s.push_str(&format!("    <g class=\"lini-node lini-junction lini-oval\" transform=\"translate({},{})\">\n", f4(x), f4(y)));
            s.push_str("      <ellipse cx=\"0\" cy=\"0\" rx=\"4\" ry=\"4\"/>\n");
            s.push_str("    </g>\n");
        }
        // the stylesheet
        if root {
            out.extra_rules.push((
                "link".into(),
                ".lini-link { fill: none; stroke: var(--lini-wire); stroke-width: 1.5; stroke-dasharray: none; }".to_string(),
            ));
            // the root's link rule names the net-name ink whether or not a name is drawn
            use_var(&mut out.vars, "wire");
            use_var(&mut out.vars, "label-ink");
            if any_label {
                out.extra_rules.push((
                    "link-label".into(),
                    ".lini-link-label { fill: var(--lini-label-ink); stroke: none; text-anchor: middle; font-size: 11px; font-weight: var(--lini-font-weight); }"
                        .to_string(),
                ));
                use_var(&mut out.vars, "label-ink");
            }
        } else {
            out.extra_rules.push((
                "link".into(),
                ".lini-link { fill: none; stroke: var(--lini-stroke); stroke-width: 2; stroke-dasharray: none; }".to_string(),
            ));
            use_var(&mut out.vars, "stroke");
            use_var(&mut out.vars, "label-ink");
            if any_label {
                out.extra_rules.push((
                    "link-label".into(),
                    ".lini-link-label { fill: currentColor; stroke: none; text-anchor: middle; font-size: 11px; font-weight: var(--lini-link-font-weight); }"
                        .to_string(),
                ));
                use_var(&mut out.vars, "link-font-weight");
                use_var(&mut out.vars, "label-ink");
            }
            out.extra_rules.push((
                "schematic-wire".into(),
                ".lini-links .lini-schematic-wire { stroke: var(--lini-wire); stroke-width: 1.5; }".to_string(),
            ));
            use_var(&mut out.vars, "wire");
        }
        if !w.junctions.is_empty() {
            out.extra_rules.push(("oval".into(), ".lini-oval { stroke-dasharray: none; }".to_string()));
            out.extra_rules.push(("junction".into(), ".lini-junction { fill: var(--lini-wire); stroke: none; }".to_string()));
            use_var(&mut out.vars, "wire");
        }
    });
    Ok(s)
}
