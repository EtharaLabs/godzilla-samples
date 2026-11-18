//! The `check` "NBR 6118": notes where the bars made fall short of the usual limits for the kind
//! of host. A note never refuses; it reads only the bars made (and the host's section), so a
//! limit that needs shear, the load or the aggregate is not in it.
//!
//! In the order the original gives them: the cover of each face (Table 7.2, with an
//! `aggressiveness`); then for a beam the most steel, the least (up to C30; above it, that it
//! isn't coded), the skin bars over 600 mm deep, the stirrups' diameter (5 mm least, a tenth of
//! the width most) and how far apart they are; for a column its bars' diameter (10 mm least, an
//! eighth of the smaller side most), a round one's count, the steel's share, the bars' spacing
//! along a face, the stirrups' diameter and spacing; for a floor its bars' diameter (an eighth
//! of the thickness most) and each layer's spacing. A footing has only its cover's.

use super::{kind_of, Check, Cover, Host};
use crate::project::Project;
use crate::structure::rebar::area;

/// What the check reads of a host armed: its cover and its kind's bars.
#[derive(Clone, Debug, Default)]
pub struct Info {
    pub cover: Option<Cover>,
    pub kind: Kind,
}

/// The bars of each kind of host, as the check reads them.
#[derive(Clone, Debug, Default)]
pub enum Kind {
    #[default]
    None,
    Beam(Beam),
    Column(Column),
    Footing,
    Floor(Floor),
}

/// A beam's section and bars.
#[derive(Clone, Debug, Default)]
pub struct Beam {
    pub width: f64,
    pub depth: f64,
    /// The diameters of the bottom row's bars (the bent ones too), in the order they are made.
    pub bottom: Vec<f64>,
    /// The diameters of the top row's bars.
    pub top: Vec<f64>,
    /// The diameters of the skin bars, both faces, in the order they are made.
    pub skin: Vec<f64>,
    /// The diameters of one face's skin bars.
    pub skin_face: Vec<f64>,
    /// The stirrups' diameter and the most between two of them.
    pub stirrup: Option<(f64, f64)>,
    /// The effective depth: from the top to the bottom bars' centre (the stirrup's inside, with
    /// no bottom bars).
    pub d: f64,
}

/// A column's section and bars.
#[derive(Clone, Debug, Default)]
pub struct Column {
    pub round: bool,
    pub width: f64,
    /// Its depth; a round one's diameter.
    pub depth: f64,
    /// How many bars, their diameter, and (a rectangular column's) the most between two along a
    /// face.
    pub bars: Option<(usize, f64, Option<f64>)>,
    /// The stirrups' diameter and the most between two of them.
    pub stirrup: Option<(f64, f64)>,
}

/// A floor's thickness and layers.
#[derive(Clone, Debug, Default)]
pub struct Floor {
    pub thickness: f64,
    /// Each layer's name ("bottom x"), diameter, and how far apart its bars are (none with a
    /// single row).
    pub layers: Vec<(&'static str, f64, Option<f64>)>,
}

/// The most between consecutive stations, 0 with fewer than two.
pub fn largest_gap(ts: &[f64]) -> f64 {
    ts.windows(2).map(|w| w[1] - w[0]).fold(0.0, f64::max)
}

/// Areas summed as the original sums them (an empty sum is -0).
fn areas(ds: &[f64]) -> f64 {
    ds.iter().map(|d| area(*d)).fold(-0.0, |a, x| a + x)
}

const ROMAN: [&str; 4] = ["I", "II", "III", "IV"];

/// Table 7.2's least cover for a kind of host and a class (1 to 4), mm.
fn least_cover(kind: &str, class: u64) -> f64 {
    let t: [f64; 4] = match kind {
        "floor" => [20.0, 25.0, 35.0, 45.0],
        "footing" => [30.0, 30.0, 40.0, 50.0],
        _ => [25.0, 30.0, 40.0, 50.0],
    };
    t[(class.clamp(1, 4) - 1) as usize]
}

fn cover_notes(kind: &str, cover: &Cover, class: u64, out: &mut Vec<String>) {
    let least = least_cover(kind, class);
    for (face, c) in [("top", cover.top), ("bottom", cover.bottom), ("sides", cover.sides)] {
        if c < least {
            out.push(format!(
                "NBR 6118 7.4.7.2: the {}'s {} cover of {} mm is under the {} mm that Table 7.2 gives for class {}",
                kind,
                face,
                c,
                least,
                ROMAN[(class.clamp(1, 4) - 1) as usize]
            ));
        }
    }
}

fn beam_notes(b: &Beam, check: &Check, out: &mut Vec<String>) {
    let ac = b.width * b.depth;
    let bottom = areas(&b.bottom);
    // the longitudinal bars: bottom, top and skin
    let mut all: Vec<f64> = b.bottom.clone();
    all.extend_from_slice(&b.top);
    all.extend_from_slice(&b.skin);
    let most = areas(&all) / ac * 100.0;
    if most > 4.0 {
        out.push(format!(
            "NBR 6118 17.3.5.2: the longitudinal bars are {:.1} % of the section, over the 4 % most",
            most
        ));
    }
    if !b.bottom.is_empty() {
        match check.fck {
            Some(fck) if fck > 30.0 => out.push(format!(
                "NBR 6118 17.3.5.2: the minimum steel for C{} isn't coded here (Table 17.3): only up to C30 is",
                fck
            )),
            _ => {
                let least = bottom / ac * 100.0;
                if least < 0.15 {
                    out.push(format!(
                        "NBR 6118 17.3.5.2: the bottom bars are {:.3} % of the section, under the 0.15 % Table 17.3 gives up to C30",
                        least
                    ));
                }
            }
        }
    }
    if b.depth > 600.0 {
        let skin = areas(&b.skin_face) / ac * 100.0;
        if skin < 0.10 {
            out.push(format!(
                "NBR 6118 17.3.5.2.3: a beam over 600 mm deep wants skin bars of 0.10 % of the section on each face, and these have {:.3} %",
                skin
            ));
        }
    }
    if let Some((ds, s)) = b.stirrup {
        if ds < 5.0 {
            out.push(format!("NBR 6118 17.4.1.1: stirrups of {} mm are under the 5 mm least", ds));
        }
        let tenth = b.width / 10.0;
        if ds > tenth {
            out.push(format!(
                "NBR 6118 17.4.1.1: stirrups of {} mm are over a tenth of the beam's width ({:.1} mm)",
                ds, tenth
            ));
        }
        let lim = (0.6 * b.d).min(300.0);
        if s > lim {
            out.push(format!(
                "NBR 6118 17.4.1.1: stirrups {:.0} mm apart, over min(0.6 d, 300) = {:.0} mm (0.3 d and 200 mm where shear is high)",
                s, lim
            ));
        }
    }
}

fn column_notes(c: &Column, out: &mut Vec<String>) {
    let side = if c.round { c.width } else { c.width.min(c.depth) };
    let mut bar_d = None;
    if let Some((n, d, face)) = c.bars {
        bar_d = Some(d);
        if d < 10.0 {
            out.push(format!("NBR 6118 18.4.2.1: bars of {} mm are under the 10 mm least for a column", d));
        }
        let eighth = side / 8.0;
        if d > eighth {
            out.push(format!(
                "NBR 6118 18.4.2.1: bars of {} mm are over an eighth of the column's smaller side ({:.1} mm)",
                d, eighth
            ));
        }
        if c.round && n < 6 {
            out.push(format!("NBR 6118 18.4.2.1: a round column has at least 6 bars, and this has {}", n));
        }
        let ac = if c.round { std::f64::consts::PI * c.width * c.width / 4.0 } else { c.width * c.depth };
        let ds: Vec<f64> = vec![d; n];
        let pct = areas(&ds) / ac * 100.0;
        if pct < 0.4 {
            out.push(format!("NBR 6118 17.3.5.3: the bars are {:.2} % of the section, under the 0.4 % least", pct));
        } else if pct > 8.0 {
            out.push(format!("NBR 6118 17.3.5.3: the bars are {:.2} % of the section, over the 8 % most", pct));
        }
        if let Some(s) = face {
            let lim = (2.0 * side).min(400.0);
            if s > lim {
                out.push(format!(
                    "NBR 6118 18.4.2.2: bars {:.0} mm apart along a face, over the {:.0} mm most",
                    s, lim
                ));
            }
        }
    }
    if let Some((ds, s)) = c.stirrup {
        let least = 5.0f64.max(bar_d.unwrap_or(0.0) / 4.0);
        if ds < least {
            out.push(format!(
                "NBR 6118 18.4.3: stirrups of {} mm are under the {} mm least (5 mm, or a quarter of the bars' diameter)",
                ds, least
            ));
        }
        if let Some(d) = bar_d {
            let lim = 200.0f64.min(side).min(12.0 * d);
            if s > lim {
                out.push(format!(
                    "NBR 6118 18.4.3: stirrups {:.0} mm apart, over min(200, the smaller side, 12 bar diameters) = {:.0} mm",
                    s, lim
                ));
            }
        }
    }
}

fn floor_notes(f: &Floor, out: &mut Vec<String>) {
    let th = f.thickness;
    let dmax = f.layers.iter().map(|l| l.1).fold(f64::NEG_INFINITY, f64::max);
    let eighth = th / 8.0;
    if !f.layers.is_empty() && dmax > eighth {
        out.push(format!(
            "NBR 6118 20.1: bars of {} mm are over an eighth of the slab's thickness ({:.1} mm)",
            dmax, eighth
        ));
    }
    let lim = (2.0 * th).min(200.0);
    for (name, _, step) in &f.layers {
        if let Some(s) = step {
            if *s > lim {
                out.push(format!(
                    "NBR 6118 20.1: the {} bars are {:.0} mm apart, over the {:.0} mm most (2 h, and 200 mm)",
                    name, s, lim
                ));
            }
        }
    }
}

/// The notes on a host armed, in the order the original gives them.
pub fn notes(pr: &Project, host: &Host, info: &Info, check: &Check) -> Vec<String> {
    let _ = pr;
    let kind = kind_of(&host.cat);
    let mut out = Vec::new();
    if let (Some(class), Some(cover)) = (check.aggressiveness, &info.cover) {
        cover_notes(kind, cover, class, &mut out);
    }
    match &info.kind {
        Kind::Beam(b) => beam_notes(b, check, &mut out),
        Kind::Column(c) => column_notes(c, &mut out),
        Kind::Floor(f) => floor_notes(f, &mut out),
        Kind::Footing | Kind::None => {}
    }
    out
}
