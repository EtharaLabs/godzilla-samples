// Line-end markers: arrow, dot, diamond and the ER cardinality glyphs.

use crate::util::f4;

pub fn unit(d: (f64, f64)) -> (f64, f64) {
    let l = (d.0 * d.0 + d.1 * d.1).sqrt();
    if l == 0.0 {
        (1.0, 0.0)
    } else {
        (d.0 / l, d.1 / l)
    }
}

pub fn arrow_len(sw: f64) -> f64 {
    (4.0 * sw + 1.0).max(6.0)
}

// Marker elements at end point `p`, pointing along `dir` (outward).
// Returns the elements and how far the wire is pulled back.
pub fn marker(kind: &str, p: (f64, f64), dir: (f64, f64), sw: f64) -> (Vec<String>, f64) {
    let m = marker_full(kind, p, dir, sw);
    (m.elems, m.pull)
}

pub struct Marker {
    pub elems: Vec<String>,
    // how far back from the tip the wire stops (0: the wire runs to the end)
    pub pull: f64,
    // open (stroked) glyphs need the `.lini-marker-open` rule
    pub open: bool,
    // filled glyphs (arrow, dot, diamond)
    pub filled: bool,
}

// Normalise the many spellings of an end glyph.
pub fn canonical(kind: &str) -> &str {
    match kind {
        "many" => "crow",
        _ => kind,
    }
}

pub fn is_known(kind: &str) -> bool {
    matches!(
        canonical(kind),
        "arrow" | "dot" | "diamond" | "crow" | "one" | "exactly-one" | "zero-or-one" | "one-or-many" | "zero-or-many"
    )
}

// Full marker geometry. `p` is the tip, `dir` points outward (from the wire
// towards the tip).
pub fn marker_full(kind: &str, p: (f64, f64), dir: (f64, f64), sw: f64) -> Marker {
    let d = unit(dir);
    let l = arrow_len(sw);
    let perp = (-d.1, d.0);
    let pt = |x: f64, y: f64| format!("{},{}", f4(x), f4(y));
    let at = |k: f64| (p.0 - d.0 * k, p.1 - d.1 * k);
    let bar = |k: f64| -> String {
        let c = at(k);
        let h = l / 2.0;
        format!(
            "<path class=\"lini-marker lini-marker-open\" d=\"M {} {} L {} {}\"/>",
            f4(c.0 + perp.0 * h),
            f4(c.1 + perp.1 * h),
            f4(c.0 - perp.0 * h),
            f4(c.1 - perp.1 * h)
        )
    };
    let crow = || -> String {
        let s = 0.55 * l;
        let a = at(l);
        format!(
            "<path class=\"lini-marker lini-marker-open\" d=\"M {} {} L {} {} L {} {} M {} {} L {} {}\"/>",
            f4(p.0 + perp.0 * s),
            f4(p.1 + perp.1 * s),
            f4(a.0),
            f4(a.1),
            f4(p.0 - perp.0 * s),
            f4(p.1 - perp.1 * s),
            f4(p.0),
            f4(p.1),
            f4(a.0),
            f4(a.1)
        )
    };
    let ring = |k: f64| -> String {
        let c = at(k);
        format!("<circle class=\"lini-marker lini-marker-open\" cx=\"{}\" cy=\"{}\" r=\"{}\"/>", f4(c.0), f4(c.1), f4(0.4 * l))
    };
    let joint = |from_k: f64, to_k: f64| -> String {
        let a = at(from_k);
        let b = at(to_k);
        format!("<path class=\"lini-marker lini-marker-open\" d=\"M {} {} L {} {}\"/>", f4(a.0), f4(a.1), f4(b.0), f4(b.1))
    };
    match canonical(kind) {
        "arrow" => {
            let bx = p.0 - d.0 * l;
            let by = p.1 - d.1 * l;
            let h = l / 2.0;
            let s = format!(
                "<polygon class=\"lini-marker lini-marker-arrow\" points=\"{} {} {}\"/>",
                pt(p.0, p.1),
                pt(bx + perp.0 * h, by + perp.1 * h),
                pt(bx - perp.0 * h, by - perp.1 * h)
            );
            Marker { elems: vec![s], pull: 2.0 * sw, open: false, filled: true }
        }
        "dot" => {
            let r = 0.4375 * l;
            let s = format!(
                "<circle class=\"lini-marker lini-marker-dot\" cx=\"{}\" cy=\"{}\" r=\"{}\"/>",
                f4(p.0 - d.0 * r),
                f4(p.1 - d.1 * r),
                f4(r)
            );
            Marker { elems: vec![s], pull: 2.0 * sw, open: false, filled: true }
        }
        "diamond" => {
            let h = l / 2.0;
            let m = (p.0 - d.0 * h, p.1 - d.1 * h);
            let b = (p.0 - d.0 * l, p.1 - d.1 * l);
            let s = format!(
                "<polygon class=\"lini-marker lini-marker-diamond\" points=\"{} {} {} {}\"/>",
                pt(p.0, p.1),
                pt(m.0 + perp.0 * h, m.1 + perp.1 * h),
                pt(b.0, b.1),
                pt(m.0 - perp.0 * h, m.1 - perp.1 * h)
            );
            Marker { elems: vec![s], pull: 2.0 * sw, open: false, filled: true }
        }
        "crow" => Marker { elems: vec![crow()], pull: l, open: true, filled: false },
        "one" => Marker { elems: vec![bar(0.7 * l)], pull: 0.0, open: true, filled: false },
        "exactly-one" => Marker { elems: vec![bar(0.7 * l), bar(1.2 * l)], pull: 0.0, open: true, filled: false },
        "one-or-many" => Marker { elems: vec![crow(), bar(1.5 * l)], pull: l, open: true, filled: false },
        "zero-or-many" => {
            let r = 0.4 * l;
            Marker { elems: vec![crow(), ring(1.7 * l), joint(1.7 * l - r, l)], pull: 1.7 * l + r, open: true, filled: false }
        }
        "zero-or-one" => {
            let r = 0.4 * l;
            Marker { elems: vec![ring(1.5 * l), joint(1.5 * l - r, 0.0), bar(0.6 * l)], pull: 1.5 * l + r, open: true, filled: false }
        }
        _ => Marker { elems: vec![], pull: 0.0, open: false, filled: false },
    }
}
