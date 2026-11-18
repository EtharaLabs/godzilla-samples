// Schematic symbol geometry, as `lini desugar` draws it at pose 0: each part
// variant's outline (`sch-line`), its filled marks (`sch-solid`) and its pin
// stations relative to the body centre; the label symbols' outlines.

pub struct PartGeo {
    pub ty: &'static str,
    pub variant: &'static str,
    pub line: &'static str,
    pub solid: Option<&'static str>,
    pub pins: &'static [(&'static str, f64, f64)],
}

const fn p(
    ty: &'static str,
    variant: &'static str,
    line: &'static str,
    solid: Option<&'static str>,
    pins: &'static [(&'static str, f64, f64)],
) -> PartGeo {
    PartGeo { ty, variant, line, solid, pins }
}

// the first variant of a type is its default
pub static PARTS: &[PartGeo] = &[
    p("R", "plain", "M 0 0 M 64 12 M 0 6 L 16 6 M 16 0 L 48 0 L 48 12 L 16 12 Z M 48 6 L 64 6", None, &[("p1", -32.0, 0.0), ("p2", 32.0, 0.0)]),
    p("R", "pot", "M 0 0 M 64 24 M 0 12 L 16 12 M 16 6 L 48 6 L 48 18 L 16 18 Z M 48 12 L 64 12 M 32 24 L 32 21", Some("M 0 0 M 64 24 M 32 18 L 28.8 21.6 L 35.2 21.6 Z"), &[("p1", -32.0, 0.0), ("p2", 32.0, 0.0), ("w", 0.0, 12.0)]),
    p("R", "ntc", "M 0 0 M 64 20 M 0 10 L 16 10 M 16 4 L 48 4 L 48 16 L 16 16 Z M 48 10 L 64 10 M 14 20 L 22 20 L 50 0", None, &[("p1", -32.0, 0.0), ("p2", 32.0, 0.0)]),
    p("C", "plain", "M 0 0 M 64 24 M 0 12 L 29 12 M 35 12 L 64 12", Some("M 0 0 M 64 24 M 27.5 0 L 30.5 0 L 30.5 24 L 27.5 24 Z M 33.5 0 L 36.5 0 L 36.5 24 L 33.5 24 Z"), &[("p1", -32.0, 0.0), ("p2", 32.0, 0.0)]),
    p("C", "polarized", "M 0 0 M 64 32 M 0 16 L 29 16 M 39 4 A 18 18 0 0 0 39 28 M 37 16 L 64 16 M 6 2 L 12 2 M 9 0 L 9 5", Some("M 0 0 M 64 32 M 27.5 4 L 30.5 4 L 30.5 28 L 27.5 28 Z"), &[("p1", -32.0, 0.0), ("p2", 32.0, 0.0)]),
    p("L", "plain", "M 0 0 M 64 10 M 0 5 L 12 5 A 5 5 0 0 1 22 5 A 5 5 0 0 1 32 5 A 5 5 0 0 1 42 5 A 5 5 0 0 1 52 5 L 64 5", None, &[("p1", -32.0, 0.0), ("p2", 32.0, 0.0)]),
    p("D", "plain", "M 0 0 M 64 16 M 0 8 L 24 8 M 24 0 L 40 8 L 24 16 Z M 40 0 L 40 16 M 40 8 L 64 8", None, &[("a", -32.0, 0.0), ("k", 32.0, 0.0)]),
    p("D", "zener", "M 0 0 M 64 16 M 0 8 L 24 8 M 24 0 L 40 8 L 24 16 Z M 44 0 L 40 2 L 40 14 L 36 16 M 40 8 L 64 8", None, &[("a", -32.0, 0.0), ("k", 32.0, 0.0)]),
    p("D", "tvs", "M 0 0 M 76 16 M 0 8 L 22 8 M 22 0 L 38 8 L 22 16 Z M 54 0 L 38 8 L 54 16 Z M 41 0 L 38 2 L 38 14 L 35 16 M 54 8 L 76 8", None, &[("a", -38.0, 0.0), ("k", 38.0, 0.0)]),
    p("D", "schottky", "M 0 0 M 64 16 M 0 8 L 24 8 M 24 0 L 40 8 L 24 16 Z M 36 2 L 36 0 L 40 0 L 40 16 L 44 16 L 44 14 M 40 8 L 64 8", None, &[("a", -32.0, 0.0), ("k", 32.0, 0.0)]),
    p("LED", "plain", "M 0 0 M 64 28 M 0 14 L 24 14 M 24 6 L 40 14 L 24 22 Z M 40 6 L 40 22 M 40 14 L 64 14 M 28 6 L 34 0 M 34 3 L 34 0 L 31 0 M 36 8 L 42 2 M 42 5 L 42 2 L 39 2", None, &[("a", -32.0, 0.0), ("k", 32.0, 0.0)]),
    p("Q", "npn", "M 0 0 M 56 48 M 10 24 A 20 20 0 1 1 50 24 A 20 20 0 1 1 10 24 M 0 24 L 24 24 M 24 20 L 40 4 L 56 4 M 24 28 L 40 44 L 56 44", Some("M 0 0 M 56 48 M 22.5 16 L 25.5 16 L 25.5 32 L 22.5 32 Z M 36.02 40.02 L 31.92 31.4 L 27.4 35.92 Z"), &[("b", -28.0, 0.0), ("c", 28.0, -20.0), ("e", 28.0, 20.0)]),
    p("Q", "pnp", "M 0 0 M 56 48 M 10 24 A 20 20 0 1 1 50 24 A 20 20 0 1 1 10 24 M 0 24 L 24 24 M 24 20 L 40 4 L 56 4 M 24 28 L 40 44 L 56 44", Some("M 0 0 M 56 48 M 22.5 16 L 25.5 16 L 25.5 32 L 22.5 32 Z M 26.12 30.12 L 34.75 34.23 L 30.23 38.75 Z"), &[("b", -28.0, 0.0), ("c", 28.0, -20.0), ("e", 28.0, 20.0)]),
    p("Q", "nfet", "M 0 0 M 56 48 M 10 24 A 20 20 0 1 1 50 24 A 20 20 0 1 1 10 24 M 0 24 L 20 24 M 20 14 L 20 34 M 28.5 16 L 44 16 L 44 4 L 56 4 M 28.5 32 L 44 32 L 44 44 L 56 44 M 28.5 24 L 44 24 L 44 32", Some("M 0 0 M 56 48 M 25.5 14 L 28.5 14 L 28.5 19.3 L 25.5 19.3 Z M 25.5 21.3 L 28.5 21.3 L 28.5 26.7 L 25.5 26.7 Z M 25.5 28.7 L 28.5 28.7 L 28.5 34 L 25.5 34 Z M 28 24 L 37 20.8 L 37 27.2 Z"), &[("g", -28.0, 0.0), ("d", 28.0, -20.0), ("s", 28.0, 20.0)]),
    p("Q", "pfet", "M 0 0 M 56 48 M 10 24 A 20 20 0 1 1 50 24 A 20 20 0 1 1 10 24 M 0 24 L 20 24 M 20 14 L 20 34 M 28.5 16 L 44 16 L 44 4 L 56 4 M 28.5 32 L 44 32 L 44 44 L 56 44 M 28.5 24 L 44 24 L 44 32", Some("M 0 0 M 56 48 M 25.5 14 L 28.5 14 L 28.5 19.3 L 25.5 19.3 Z M 25.5 21.3 L 28.5 21.3 L 28.5 26.7 L 25.5 26.7 Z M 25.5 28.7 L 28.5 28.7 L 28.5 34 L 25.5 34 Z M 37 24 L 28 27.2 L 28 20.8 Z"), &[("g", -28.0, 0.0), ("d", 28.0, -20.0), ("s", 28.0, 20.0)]),
    p("Y", "plain", "M 0 0 M 64 20 M 0 10 L 24 10 M 24 2 L 24 18 M 28 0 L 36 0 L 36 20 L 28 20 Z M 40 2 L 40 18 M 40 10 L 64 10", None, &[("p1", -32.0, 0.0), ("p2", 32.0, 0.0)]),
    p("F", "plain", "M 0 0 M 64 12 M 0 6 L 64 6 M 16 0 L 48 0 L 48 12 L 16 12 Z", None, &[("p1", -32.0, 0.0), ("p2", 32.0, 0.0)]),
    p("FB", "plain", "M 0 0 M 64 26 M 0 13 L 25.65 13 M 38.35 13 L 64 13 M 42.26 6.22 L 32.74 0.72 L 21.74 19.78 L 31.26 25.28 Z", None, &[("p1", -32.0, 0.0), ("p2", 32.0, 0.0)]),
    p("SW", "toggle", "M 0 0 M 64 24 M 0 12 L 20 12 M 20 12 L 44 0 M 44 12 L 64 12", None, &[("p1", -32.0, 0.0), ("p2", 32.0, 0.0)]),
    p("SW", "push", "M 0 0 M 64 28 M 0 14 L 24 14 M 40 14 L 64 14 M 20 8 L 44 8 M 32 8 L 32 0", None, &[("p1", -32.0, 0.0), ("p2", 32.0, 0.0)]),
    p("BT", "cell", "M 0 0 M 64 20 M 0 10 L 28 10 M 28 0 L 28 20 M 36 5 L 36 15 M 36 10 L 64 10", None, &[("plus", -32.0, 0.0), ("minus", 32.0, 0.0)]),
    p("BT", "battery", "M 0 0 M 72 20 M 0 10 L 24 10 M 24 0 L 24 20 M 32 5 L 32 15 M 40 0 L 40 20 M 48 5 L 48 15 M 48 10 L 72 10", None, &[("plus", -36.0, 0.0), ("minus", 36.0, 0.0)]),
    p("V", "dc", "M 0 0 M 64 24 M 0 12 L 20 12 M 20 12 A 12 12 0 1 0 44 12 A 12 12 0 1 0 20 12 M 44 12 L 64 12 M 29 8 L 35 8 M 32 5 L 32 11 M 29 17 L 35 17", None, &[("plus", -32.0, 0.0), ("minus", 32.0, 0.0)]),
    p("V", "ac", "M 0 0 M 64 24 M 0 12 L 20 12 M 20 12 A 12 12 0 1 0 44 12 A 12 12 0 1 0 20 12 M 44 12 L 64 12 M 26 12 Q 29 6 32 12 Q 35 18 38 12", None, &[("plus", -32.0, 0.0), ("minus", 32.0, 0.0)]),
    p("I", "dc", "M 0 0 M 64 24 M 0 12 L 20 12 M 20 12 A 12 12 0 1 0 44 12 A 12 12 0 1 0 20 12 M 44 12 L 64 12 M 26 12 L 38 12 M 34 8 L 38 12 L 34 16", None, &[("plus", -32.0, 0.0), ("minus", 32.0, 0.0)]),
    p("I", "ac", "M 0 0 M 64 24 M 0 12 L 20 12 M 20 12 A 12 12 0 1 0 44 12 A 12 12 0 1 0 20 12 M 44 12 L 64 12 M 26 7 Q 29 3 32 7 Q 35 11 38 7 M 26 16 L 38 16 M 34 12 L 38 16 L 34 20", None, &[("plus", -32.0, 0.0), ("minus", 32.0, 0.0)]),
    p("M", "plain", "M 0 0 M 64 24 M 0 12 L 20 12 M 20 12 A 12 12 0 1 0 44 12 A 12 12 0 1 0 20 12 M 44 12 L 64 12 M 26 17 L 26 7 L 32 13 L 38 7 L 38 17", None, &[("p1", -32.0, 0.0), ("p2", 32.0, 0.0)]),
    p("BZ", "plain", "M 0 0 M 64 24 M 0 12 L 24 12 M 24 22 L 24 2 A 10 10 0 0 1 24 22 Z M 34 12 L 64 12", None, &[("p1", -32.0, 0.0), ("p2", 32.0, 0.0)]),
    p("TP", "plain", "M 0 0 M 32 12 M 0 6 L 20 6 M 20 6 A 6 6 0 1 0 32 6 A 6 6 0 1 0 20 6", None, &[("p1", -16.0, 0.0)]),
    p("opamp", "plain", "M 0 0 M 64 64 M 12 4 L 60 32 L 12 60 Z M 0 12 L 12 12 M 0 52 L 12 52 M 60 32 L 64 32 M 17 17 L 25 17 M 21 13 L 21 21 M 17 47 L 25 47", None, &[("out", 32.0, 0.0), ("inp", -32.0, -20.0), ("inn", -32.0, 20.0)]),
];

pub static SYMBOLS: &[(&str, &str)] = &[
    ("gnd", "M 0 0 M 16 15 M 8 0 L 8 6 M 0 6 L 16 6 M 1 6 L 8 15 L 15 6"),
    ("earth", "M 0 0 M 16 14 M 8 0 L 8 6 M 0 6 L 16 6 M 3 10 L 13 10 M 6 14 L 10 14"),
    ("chassis", "M 0 0 M 16 12 M 8 0 L 8 6 M 2 6 L 16 6 M 5 6 L 2 12 M 10 6 L 7 12 M 15 6 L 12 12"),
    ("power", "M 0 0 M 16 20 M 8 20 L 8 0 M 3 9 L 8 0 L 13 9"),
    ("antenna", "M 0 0 M 20 20 M 10 20 L 10 6 M 0 0 L 10 6 L 20 0"),
    ("nc", "M 0 0 M 12 10 M 0 5 L 8 5 M 4 1 L 12 9 M 12 1 L 4 9"),
];

pub fn part_types() -> impl Iterator<Item = &'static str> {
    let mut seen: Vec<&'static str> = Vec::new();
    PARTS.iter().filter_map(move |g| {
        if seen.contains(&g.ty) {
            None
        } else {
            seen.push(g.ty);
            Some(g.ty)
        }
    })
}

pub fn variants(ty: &str) -> Vec<&'static str> {
    PARTS.iter().filter(|g| g.ty == ty).map(|g| g.variant).collect()
}

pub fn geo(ty: &str, variant: Option<&str>) -> Option<&'static PartGeo> {
    match variant {
        Some(v) => PARTS.iter().find(|g| g.ty == ty && g.variant == v),
        None => PARTS.iter().find(|g| g.ty == ty),
    }
}
