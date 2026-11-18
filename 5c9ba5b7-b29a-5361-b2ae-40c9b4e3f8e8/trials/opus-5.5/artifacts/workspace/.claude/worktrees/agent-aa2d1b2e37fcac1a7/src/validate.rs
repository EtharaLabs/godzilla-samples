// Declaration validation, before the scene is built.
//
// The V-phase walks every declaration in document order — the stylesheet's
// root block, rules and defines, then the class rules' wear checks, then the
// statements — and collects every diagnostic (--json lists them all; text
// output shows the first error). Per declaration, in order: the property must
// exist (with a "did you mean"), then the value's shape (one value, the
// property's own checks, no bare '%', colour names), then where it applies
// (scene config, misuse on a type, the root block or a link, grid placement).
//
// The R-phase (`resolve`) runs once types are known and stops at the first
// error: gradient shapes, colour-function ranges, quoted-string properties,
// comma lists written as runs, expressions, and text that would need a box.

use crate::ast::*;
use crate::diag::{Diag, Fix, Span};
use crate::scene::SheetModel;
use std::cell::RefCell;

#[derive(Clone, Copy)]
enum Own {
    All,
    Scene,
    Types(&'static [&'static str]),
}

#[derive(Clone, Copy)]
enum Root {
    Yes,
    No,
    Layouts(&'static [&'static str]),
}

struct P {
    name: &'static str,
    own: Own,
    // "it reads on …" text
    msg: &'static str,
    root: Root,
    link: bool,
    // takes a comma list
    list: bool,
    color: bool,
    // meaningful on bare text
    text: bool,
    // order the "did you mean" candidates are tried in
    rank: usize,
}

// The documented properties (the "did you mean" candidates).
static PROPS: &[P] = &[
    P { name: "activation", own: Own::All, msg: "a 'layout: sequence'", root: Root::Layouts(&["sequence"]), link: false, list: false, color: false, text: false, rank: 0 },
    P { name: "align", own: Own::All, msg: "a 'layout: flow' / a 'layout: grid'", root: Root::Layouts(&["flow", "grid"]), link: false, list: true, color: false, text: false, rank: 63 },
    P { name: "along", own: Own::Types(&[]), msg: "links", root: Root::No, link: true, list: true, color: false, text: false, rank: 111 },
    P { name: "approved", own: Own::Types(&["title-block"]), msg: "the '|title-block|' fields", root: Root::No, link: false, list: false, color: false, text: false, rank: 1 },
    P { name: "at", own: Own::Types(&["bubble", "door", "mark", "plane", "window"]), msg: "'|mark|' / '|bubble|' / '|plane|' / a wall opening ('|door|' / '|window|')", root: Root::No, link: false, list: false, color: false, text: false, rank: 85 },
    P { name: "author", own: Own::Types(&["title-block"]), msg: "the '|title-block|' fields", root: Root::No, link: false, list: false, color: false, text: false, rank: 98 },
    P { name: "axis", own: Own::Types(&["area", "band", "bars", "bubble", "dots", "line", "mark"]), msg: "a chart series / '|mark|' / '|band|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 81 },
    P { name: "bars", own: Own::Types(&["chart"]), msg: "'|chart|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 82 },
    P { name: "baseline", own: Own::Types(&["area"]), msg: "'|area|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 2 },
    P { name: "break", own: Own::Types(&["sketch"]), msg: "'|sketch|'", root: Root::No, link: false, list: true, color: false, text: false, rank: 70 },
    P { name: "categories", own: Own::Types(&["chart"]), msg: "'|chart|'", root: Root::No, link: false, list: true, color: false, text: false, rank: 3 },
    P { name: "cell", own: Own::All, msg: "a 'layout: grid' / a 'layout: schematic'", root: Root::Layouts(&["grid", "schematic"]), link: false, list: false, color: false, text: false, rank: 74 },
    P { name: "characteristic", own: Own::Types(&["control", "feature-control"]), msg: "'|feature-control|' / '|control|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 4 },
    P { name: "clearance", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: false, rank: 5 },
    P { name: "color", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: true, text: true, rank: 12 },
    P { name: "columns", own: Own::All, msg: "a 'layout: grid' / a 'layout: schematic'", root: Root::Layouts(&["grid", "schematic"]), link: false, list: true, color: false, text: false, rank: 13 },
    P { name: "corner-radius", own: Own::Types(&[]), msg: "links", root: Root::No, link: true, list: false, color: false, text: false, rank: 6 },
    P { name: "curve", own: Own::Types(&["area", "line"]), msg: "'|line|' / '|area|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 75 },
    P { name: "data", own: Own::Types(&["area", "bars", "bubble", "dots", "line"]), msg: "a chart series", root: Root::No, link: false, list: true, color: false, text: false, rank: 79 },
    P { name: "date", own: Own::Types(&["title-block"]), msg: "the '|title-block|' fields", root: Root::No, link: false, list: false, color: false, text: false, rank: 104 },
    P { name: "datums", own: Own::Types(&["control", "feature-control"]), msg: "'|feature-control|' / '|control|'", root: Root::No, link: false, list: true, color: false, text: false, rank: 86 },
    P { name: "density", own: Own::Scene, msg: "", root: Root::Yes, link: false, list: false, color: false, text: false, rank: 96 },
    P { name: "department", own: Own::Types(&["title-block"]), msg: "the '|title-block|' fields", root: Root::No, link: false, list: false, color: false, text: false, rank: 7 },
    P { name: "direction", own: Own::All, msg: "a 'layout: flow' / a 'layout: chart' / a 'layout: tree'", root: Root::Layouts(&["flow", "tree"]), link: false, list: false, color: false, text: false, rank: 8 },
    P { name: "document-type", own: Own::Types(&["title-block"]), msg: "the '|title-block|' fields", root: Root::No, link: false, list: false, color: false, text: false, rank: 9 },
    P { name: "draw", own: Own::Types(&["sketch"]), msg: "'|sketch|'", root: Root::No, link: false, list: true, color: false, text: false, rank: 65 },
    P { name: "drawing-number", own: Own::Types(&["title-block"]), msg: "the '|title-block|' fields", root: Root::No, link: false, list: false, color: false, text: false, rank: 10 },
    P { name: "facing", own: Own::Types(&["plane"]), msg: "'|plane|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 90 },
    P { name: "fill", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: true, text: true, rank: 11 },
    P { name: "fit", own: Own::Types(&["icon", "image"]), msg: "'|icon|' / '|image|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 62 },
    P { name: "fn", own: Own::Types(&["area", "bars", "bubble", "dots", "line"]), msg: "a chart series", root: Root::No, link: false, list: true, color: false, text: false, rank: 80 },
    P { name: "font-family", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: true, rank: 14 },
    P { name: "font-size", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: true, rank: 15 },
    P { name: "font-style", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: true, rank: 16 },
    P { name: "font-weight", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: true, rank: 17 },
    P { name: "format", own: Own::Types(&["area", "axis", "bars", "bubble", "chart", "dots", "drawing", "line", "pie"]), msg: "'|chart|' / '|pie|' / '|axis|' / a chart series / '|drawing|' / a '(-)' dimension", root: Root::No, link: true, list: false, color: false, text: false, rank: 87 },
    P { name: "gap", own: Own::All, msg: "a 'layout: flow' / a 'layout: grid' / a 'layout: sequence' / a 'layout: chart' / a 'layout: pie' / a 'layout: tree' / a 'layout: schematic' / a '||' mate", root: Root::Layouts(&["flow", "grid", "tree", "sequence", "schematic"]), link: true, list: false, color: false, text: false, rank: 71 },
    P { name: "gap-fill", own: Own::All, msg: "a 'layout: flow' / a 'layout: grid' / a 'layout: sequence'", root: Root::Layouts(&["flow", "grid", "sequence"]), link: false, list: false, color: true, text: false, rank: 18 },
    P { name: "gridlines", own: Own::Types(&["axis"]), msg: "'|axis|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 19 },
    P { name: "height", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: false, rank: 20 },
    P { name: "hinge", own: Own::Types(&["door"]), msg: "'|door|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 105 },
    P { name: "hint", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: false, rank: 58 },
    P { name: "hole", own: Own::Types(&["pie"]), msg: "'|pie|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 83 },
    P { name: "href", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: false, rank: 57 },
    P { name: "justify", own: Own::All, msg: "a 'layout: flow' / a 'layout: grid'", root: Root::Layouts(&["flow", "grid"]), link: false, list: true, color: false, text: false, rank: 21 },
    P { name: "labels", own: Own::Types(&["area", "bars", "bubble", "dots", "line"]), msg: "a chart series", root: Root::No, link: false, list: true, color: false, text: false, rank: 76 },
    P { name: "layer", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: true, rank: 22 },
    P { name: "layout", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: false, rank: 34 },
    P { name: "legend", own: Own::Types(&[]), msg: "", root: Root::Yes, link: true, list: true, color: false, text: false, rank: 77 },
    P { name: "letter-spacing", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: true, rank: 23 },
    P { name: "line-spacing", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: true, rank: 24 },
    P { name: "marker", own: Own::Types(&["area", "bars", "bubble", "dots", "line", "mark"]), msg: "'|line|' / '|mark|' / a chart series / links", root: Root::No, link: true, list: false, color: false, text: false, rank: 66 },
    P { name: "marker-end", own: Own::Types(&["area", "bars", "bubble", "dots", "line", "mark"]), msg: "'|line|' / '|mark|' / a chart series / links", root: Root::No, link: true, list: false, color: false, text: false, rank: 67 },
    P { name: "marker-start", own: Own::Types(&["area", "bars", "bubble", "dots", "line", "mark"]), msg: "'|line|' / '|mark|' / a chart series / links", root: Root::No, link: true, list: false, color: false, text: false, rank: 25 },
    P { name: "material", own: Own::Types(&["control", "feature-control"]), msg: "'|feature-control|' / '|control|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 26 },
    P { name: "max-width", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: false, rank: 55 },
    P { name: "mirror", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: false, rank: 27 },
    P { name: "modifiers", own: Own::Types(&["control", "feature-control"]), msg: "'|feature-control|' / '|control|'", root: Root::No, link: false, list: true, color: false, text: false, rank: 28 },
    P { name: "multiple", own: Own::Types(&["block", "cyl", "diamond", "hex", "icon", "oval", "path", "poly", "sketch", "slant"]), msg: "closed shapes", root: Root::No, link: false, list: false, color: false, text: false, rank: 29 },
    P { name: "number", own: Own::Types(&["pin"]), msg: "'|pin|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 99 },
    P { name: "of", own: Own::Types(&["drawing"]), msg: "'|drawing|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 101 },
    P { name: "on", own: Own::Types(&["door", "window"]), msg: "a wall opening ('|door|' / '|window|')", root: Root::No, link: false, list: false, color: false, text: false, rank: 102 },
    P { name: "opacity", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: true, rank: 30 },
    P { name: "padding", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: false, rank: 35 },
    P { name: "path", own: Own::Types(&["path"]), msg: "'|path|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 60 },
    P { name: "pattern", own: Own::All, msg: "", root: Root::Yes, link: true, list: true, color: false, text: false, rank: 31 },
    P { name: "pin", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: false, rank: 56 },
    P { name: "pins", own: Own::Types(&["J"]), msg: "'|J|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 110 },
    P { name: "place", own: Own::Types(&["note"]), msg: "'|note|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 91 },
    P { name: "points", own: Own::Types(&["line", "poly"]), msg: "'|line|' / '|poly|'", root: Root::No, link: false, list: true, color: false, text: false, rank: 59 },
    P { name: "prefix", own: Own::Types(&["BT", "BZ", "C", "D", "F", "FB", "I", "L", "LED", "M", "Q", "R", "SW", "TP", "V", "Y", "component"]), msg: "'|component|' / the discrete parts ('|R|', '|C|', …)", root: Root::No, link: false, list: false, color: false, text: false, rank: 72 },
    P { name: "project", own: Own::Types(&[]), msg: "a '(-)' dimension", root: Root::No, link: true, list: false, color: false, text: false, rank: 32 },
    P { name: "radius", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: false, rank: 33 },
    P { name: "range", own: Own::Types(&["axis", "band"]), msg: "'|axis|' / '|band|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 89 },
    P { name: "reference", own: Own::Types(&["title-block"]), msg: "the '|title-block|' fields", root: Root::No, link: false, list: false, color: false, text: false, rank: 36 },
    P { name: "revision", own: Own::Types(&["title-block"]), msg: "the '|title-block|' fields", root: Root::No, link: false, list: false, color: false, text: false, rank: 37 },
    P { name: "revolve", own: Own::Types(&["sketch"]), msg: "'|sketch|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 38 },
    P { name: "rotate", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: true, rank: 39 },
    P { name: "routing", own: Own::All, msg: "", root: Root::Yes, link: false, list: false, color: false, text: false, rank: 108 },
    P { name: "rows", own: Own::All, msg: "a 'layout: grid'", root: Root::Layouts(&["grid"]), link: false, list: true, color: false, text: false, rank: 73 },
    P { name: "samples", own: Own::Types(&["chart", "line", "poly"]), msg: "'|line|' / '|poly|' / '|chart|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 44 },
    P { name: "scale", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: false, rank: 43 },
    P { name: "shadow", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: false, rank: 40 },
    P { name: "shape", own: Own::Types(&["label"]), msg: "'|label|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 112 },
    P { name: "sheet", own: Own::Types(&["page"]), msg: "'|page|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 69 },
    P { name: "sheet-number", own: Own::Types(&["title-block"]), msg: "the '|title-block|' fields", root: Root::No, link: false, list: false, color: false, text: false, rank: 41 },
    P { name: "side", own: Own::Types(&["axis", "label", "pin", "topic"]), msg: "'|axis|' / '|topic|' / '|pin|' / '|label|' / links / a '(-)' dimension", root: Root::No, link: true, list: false, color: false, text: false, rank: 88 },
    P { name: "skew", own: Own::Types(&["slant"]), msg: "'|slant|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 64 },
    P { name: "span", own: Own::All, msg: "a 'layout: grid' / '|space|'", root: Root::Layouts(&["grid"]), link: false, list: false, color: false, text: false, rank: 78 },
    P { name: "src", own: Own::Types(&["image"]), msg: "'|image|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 61 },
    P { name: "status", own: Own::Types(&["title-block"]), msg: "the '|title-block|' fields", root: Root::No, link: false, list: false, color: false, text: false, rank: 106 },
    P { name: "step", own: Own::Types(&["axis"]), msg: "'|axis|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 92 },
    P { name: "steps", own: Own::Types(&["stairs"]), msg: "'|stairs|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 109 },
    P { name: "stroke", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: true, text: false, rank: 42 },
    P { name: "stroke-style", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: false, rank: 45 },
    P { name: "stroke-width", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: false, rank: 46 },
    P { name: "swing", own: Own::Types(&["door"]), msg: "'|door|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 107 },
    P { name: "symbol", own: Own::Types(&["BT", "BZ", "C", "D", "F", "FB", "I", "L", "LED", "M", "Q", "R", "SW", "TP", "V", "Y", "appliance", "bath", "bed", "dining", "door", "icon", "label", "sofa", "surface-finish"]), msg: "'|icon|' / '|surface-finish|' / '|label|' / the discrete parts ('|R|', '|C|', …) / '|door|' / '|bed|' / '|sofa|' / '|dining|' / '|bath|' / '|appliance|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 47 },
    P { name: "text-decoration", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: true, rank: 48 },
    P { name: "text-shadow", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: true, rank: 49 },
    P { name: "text-transform", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: true, rank: 50 },
    P { name: "text-wrap", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: false, rank: 51 },
    P { name: "thickness", own: Own::Types(&["floorplan", "wall"]), msg: "'|floorplan|' / '|wall|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 94 },
    P { name: "thread", own: Own::Types(&["hole", "sketch"]), msg: "'|sketch|' / '|hole|'", root: Root::No, link: false, list: true, color: false, text: false, rank: 68 },
    P { name: "ticks", own: Own::Types(&["axis"]), msg: "'|axis|'", root: Root::No, link: false, list: true, color: false, text: false, rank: 93 },
    P { name: "title", own: Own::Types(&["title-block"]), msg: "the '|title-block|' fields", root: Root::No, link: false, list: false, color: false, text: false, rank: 103 },
    P { name: "tol", own: Own::Types(&["control", "feature-control"]), msg: "a '(-)' dimension / '|feature-control|' / '|control|'", root: Root::No, link: true, list: false, color: false, text: false, rank: 97 },
    P { name: "tooltip", own: Own::Types(&["area", "bars", "bubble", "chart", "dots", "line", "pie"]), msg: "'|chart|' / '|pie|' / a chart series", root: Root::No, link: false, list: false, color: false, text: false, rank: 52 },
    P { name: "translate", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: true, rank: 53 },
    P { name: "unit", own: Own::All, msg: "a 'layout: stack' / '|stack|' / '|drawing|' / '|axis|'", root: Root::Layouts(&["stack", "drawing", "floorplan"]), link: false, list: false, color: false, text: false, rank: 95 },
    P { name: "value", own: Own::Types(&["bubble", "slice"]), msg: "'|slice|' / '|bubble|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 84 },
    P { name: "width", own: Own::All, msg: "", root: Root::Yes, link: true, list: false, color: false, text: false, rank: 54 },
    P { name: "zone", own: Own::Types(&["control", "feature-control"]), msg: "'|feature-control|' / '|control|'", root: Root::No, link: false, list: false, color: false, text: false, rank: 100 },
];

// Internal properties the documentation leaves out: accepted, never suggested.
const HIDDEN: &[&str] = &["font-scale", "chrome", "clip"];

fn prop(name: &str) -> Option<&'static P> {
    PROPS.iter().find(|p| p.name == name)
}

pub fn is_known(name: &str) -> bool {
    prop(name).is_some() || HIDDEN.contains(&name)
}

// The closest documented property within two edits, earliest rank on ties.
pub fn suggest(name: &str) -> Option<&'static str> {
    let mut best: Option<(usize, usize, &'static str)> = None;
    for p in PROPS {
        let d = crate::util::levenshtein(name, p.name);
        if d > 2 {
            continue;
        }
        let key = (d, p.rank);
        if best.map(|b| key < (b.0, b.1)).unwrap_or(true) {
            best = Some((d, p.rank, p.name));
        }
    }
    best.map(|b| b.2)
}

// Where a declaration sits.
#[derive(Clone)]
enum Target {
    Root(String),
    Node { name: String, chain: Vec<String>, parent_layout: String, own_layout: Option<Value> },
    Link,
    Class,
    Id,
    Text,
}

#[derive(Clone)]
enum Wearer {
    Node(Vec<String>),
    Link,
    Text,
}

fn meaningful(p: &P, w: &Wearer) -> bool {
    match w {
        Wearer::Node(chain) => match p.own {
            Own::All => true,
            Own::Scene => false,
            Own::Types(ts) => chain.iter().any(|c| ts.contains(&c.as_str())),
        },
        Wearer::Link => p.link,
        Wearer::Text => p.text,
    }
}

fn verr(family: &str, msg: &str, span: Span) -> Diag {
    Diag::error(family, msg, span)
}

thread_local! {
    // the V-phase's full diagnostic list when it failed (for --json)
    static PHASE: RefCell<Vec<Diag>> = RefCell::new(Vec::new());
}

// The whole ordered diagnostic list of a failed V-phase, once.
pub fn take_phase_diags() -> Vec<Diag> {
    PHASE.with(|p| std::mem::take(&mut *p.borrow_mut()))
}

struct V<'a> {
    sheet: &'a SheetModel,
    out: Vec<Diag>,
}

fn top_terms(v: &Value) -> impl Iterator<Item = &Term> {
    v.groups.iter().flat_map(|g| g.iter())
}

fn plain_num(v: &Value) -> Option<f64> {
    match crate::style::single_term(v) {
        Some(Term::Num(x, _, _)) => Some(*x),
        _ => None,
    }
}

impl<'a> V<'a> {
    fn decl(&mut self, d: &Decl, t: &Target) {
        if HIDDEN.contains(&d.name.as_str()) {
            return;
        }
        let p = match prop(&d.name) {
            Some(p) => p,
            None => {
                let mut msg = format!("unknown property '{}'", d.name);
                let mut fixes = vec![];
                if let Some(s) = suggest(&d.name) {
                    msg.push_str(&format!("; did you mean '{}'?", s));
                    fixes.push(Fix { message: "machine-applicable".into(), span: d.name_span, replacement: s.to_string() });
                }
                let mut e = verr("unknown-property", &msg, d.span);
                e.fixes = fixes;
                self.out.push(e);
                return;
            }
        };
        let sp = d.span;
        let v = &d.value;
        let name = p.name;
        if name == "legend" {
            self.out.push(verr("deferred-property", "'legend' is named but not built yet — see SPEC 24", sp));
            return;
        }
        let mal = |m: String| verr("malformed-value", &m, sp);
        // bars and dots paint per datum
        let per_datum = matches!(name, "fill" | "stroke" | "opacity")
            && matches!(t, Target::Node { chain, .. } if chain.iter().any(|c| c == "bars" || c == "dots"));
        if !p.list && !per_datum && v.groups.len() > 1 {
            self.out.push(mal(format!("'{}' takes one value, not a comma list", name)));
        }
        // the property's own value checks
        let single = crate::style::single_term(v);
        let ident = crate::style::ident_of(v);
        match name {
            "hinge" => {
                if !matches!(ident, Some("start") | Some("end")) {
                    self.out.push(mal("'hinge' hangs the leaf at the segment's start or end".into()));
                }
            }
            "swing" => {
                if !matches!(ident, Some("left") | Some("right")) {
                    self.out.push(mal("'swing' opens the leaf left or right of the pen's travel".into()));
                }
            }
            "steps" => {
                if !matches!(plain_num(v), Some(x) if x >= 2.0 && x.fract() == 0.0) {
                    self.out.push(mal("'steps' takes a tread count ≥ 2".into()));
                }
            }
            "number" => {
                if !matches!(plain_num(v), Some(x) if x.fract() == 0.0) {
                    self.out.push(mal("'number' takes an integer".into()));
                }
            }
            "pins" => {
                if !matches!(plain_num(v), Some(x) if x >= 1.0 && x.fract() == 0.0) {
                    self.out.push(mal("'pins' takes a count ≥ 1".into()));
                }
            }
            "thickness" => {
                if !matches!(plain_num(v), Some(x) if x > 0.0) {
                    self.out.push(mal("'thickness' takes a number > 0".into()));
                }
            }
            "translate" => {
                let n = top_terms(v).count();
                let lone_num = n == 1 && matches!(single, Some(Term::Num(..)));
                if v.groups.len() > 1 || n > 2 || lone_num {
                    self.out.push(mal("'translate' takes 'x y'".into()));
                }
            }
            "opacity" => {
                if let Some(x) = plain_num(v) {
                    if !(0.0..=1.0).contains(&x) {
                        self.out.push(mal("'opacity' is a fraction 0..1".into()));
                    }
                }
            }
            "font-weight" => {
                if let Some(Term::Num(x, _, _)) = single {
                    if ![400.0, 500.0, 600.0, 700.0].contains(x) {
                        self.out.push(mal("'font-weight' takes normal, medium, semibold, bold, or 400, 500, 600, 700".into()));
                    }
                }
            }
            _ => {}
        }
        if name == "stroke-style" && ident == Some("wavy") && matches!(t, Target::Node { .. } | Target::Root(_)) {
            self.out.push(verr(
                "wavy-outline",
                "'wavy' waves a link's wire — a shape's outline takes solid, dashed, dotted, center, or phantom",
                sp,
            ));
        }
        if top_terms(v).any(|t| matches!(t, Term::Percent(..))) {
            self.out.push(mal(format!("'{}' takes a number — a '%' is a colour component", name)));
        }
        if p.color {
            let flat = name == "color" || matches!(t, Target::Text);
            if flat && top_terms(v).any(|t| matches!(t, Term::Call(n, _, _) if crate::paint::is_gradient(n))) {
                self.out.push(mal(format!("'{}' takes a flat colour — a gradient fills a shape, and gradient-on-text is deferred", name)));
            }
            for bad in bad_colors(v) {
                self.out.push(verr("invalid-color", &format!("invalid color '{}'", bad), sp));
            }
        }
        // where it applies
        let misuse = |on: &str| verr("misused-property", &format!("'{}' has no meaning on {} — it reads on {}", name, on, p.msg), sp);
        match t {
            Target::Root(layout) => match p.root {
                Root::Yes => {}
                Root::No => self.out.push(misuse("the root block")),
                Root::Layouts(ls) => {
                    if !ls.contains(&layout.as_str()) {
                        self.out.push(misuse("the root block"));
                    }
                }
            },
            Target::Link => {
                if name == "density" {
                    self.out.push(verr("misused-property", "'density' is scene config — set it in the root block", sp));
                } else if name == "routing" {
                    self.out.push(verr(
                        "misused-property",
                        "'routing' is a scope's strategy — one scope, one strategy; set it on the container",
                        sp,
                    ));
                } else if !p.link {
                    self.out.push(misuse("a link"));
                }
            }
            Target::Node { name: tname, chain, parent_layout, own_layout: v_layout } => {
                if let Own::Scene = p.own {
                    self.out.push(verr("misused-property", &format!("'{}' is scene config — set it in the root block", name), sp));
                } else if !meaningful(p, &Wearer::Node(chain.clone())) {
                    self.out.push(misuse(&format!("'|{}|'", tname)));
                } else if name == "radius"
                    && chain.last().and_then(|b| crate::types::find(b)).is_some_and(|d| matches!(d.prim, crate::types::Prim::Slant | crate::types::Prim::Hex | crate::types::Prim::Diamond))
                {
                    self.out.push(verr(
                        "misused-property",
                        &format!("'radius' rounds a rect or a polyline join — rounding a '|{}|' is deferred", tname),
                        sp,
                    ));
                } else if !parent_layout.is_empty() {
                    match name {
                        "cell" if !matches!(parent_layout.as_str(), "grid" | "schematic") => self.out.push(verr(
                            "off-grid-placement",
                            &format!("'cell' places a grid or schematic child — this box sits in a 'layout: {}'", parent_layout),
                            sp,
                        )),
                        "span" if parent_layout != "grid" && !chain.iter().any(|c| c == "space") => self.out.push(verr(
                            "off-grid-placement",
                            &format!("'span' spans grid tracks — this box sits in a 'layout: {}'", parent_layout),
                            sp,
                        )),
                        "place" if parent_layout != "sequence" => self.out.push(verr(
                            "place-outside-sequence",
                            "'place' is valid only in a 'layout: sequence'",
                            sp,
                        )),
                        "activation" if !matches!(own_layout(v_layout), Some("sequence") | None) => self.out.push(verr(
                            "activation-outside-sequence",
                            "'activation' is valid only in a 'layout: sequence'",
                            sp,
                        )),
                        _ => {}
                    }
                }
            }
            Target::Class | Target::Id | Target::Text => {}
        }
    }

    fn node_layout_value(&self, chain: &[String], ns: &NodeStmt) -> Option<Value> {
        let mut n = crate::scene::Node::new(crate::types::Prim::Block, chain.to_vec(), ns.span);
        n.classes = ns.classes.clone();
        n.id = ns.id.clone();
        if let Some(st) = &ns.style {
            n.inline = st.clone();
        }
        let (_, props) = crate::compile::cascade(self.sheet, &n);
        crate::compile::get(&props, "layout").cloned()
    }

    // A node statement's cascaded layout (for its children's placement checks).
    fn node_layout(&self, chain: &[String], ns: &NodeStmt) -> String {
        let mut n = crate::scene::Node::new(crate::types::Prim::Block, chain.to_vec(), ns.span);
        n.classes = ns.classes.clone();
        n.id = ns.id.clone();
        if let Some(st) = &ns.style {
            n.inline = st.clone();
        }
        let (_, props) = crate::compile::cascade(self.sheet, &n);
        crate::compile::get(&props, "layout").and_then(crate::style::ident_of).unwrap_or("flow").to_string()
    }

    // A container's nodes and texts first, then its links.
    fn stmts(&mut self, stmts: &[Stmt], parent_layout: &str) {
        for s in stmts {
            match s {
                Stmt::Node(ns) => self.node(ns, parent_layout),
                Stmt::Text(t) => {
                    if let Some(st) = &t.style {
                        for d in st {
                            self.decl(d, &Target::Text);
                        }
                    }
                }
                Stmt::Link(_) => {}
            }
        }
        for s in stmts {
            match s {
                Stmt::Node(_) | Stmt::Text(_) => {}
                Stmt::Link(l) => {
                    for g in &l.groups {
                        for ep in g {
                            if let Endpoint::Node(ns) = ep {
                                self.node(ns, parent_layout);
                            }
                        }
                    }
                    if let Some(st) = &l.style {
                        for d in st {
                            self.decl(d, &Target::Link);
                        }
                    }
                    if let Some(ls) = &l.labels {
                        for s in ls {
                            if let Stmt::Text(t) = s {
                                if let Some(st) = &t.style {
                                    for d in st {
                                        self.decl(d, &Target::Text);
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    fn node(&mut self, ns: &NodeStmt, parent_layout: &str) {
        let tname = ns.type_name.clone().unwrap_or_else(|| "box".to_string());
        // an unknown type is reported once the scene is built (its children
        // are still read)
        let chain = match crate::scene::type_chain(self.sheet, &tname) {
            Some((_, c)) => c,
            None => {
                if let Some(ch) = &ns.children {
                    let lay = ns
                        .style
                        .as_ref()
                        .and_then(|st| st.iter().rev().find(|d| d.name == "layout"))
                        .and_then(|d| crate::style::ident_of(&d.value))
                        .unwrap_or("flow")
                        .to_string();
                    self.stmts(ch, &lay);
                }
                return;
            }
        };
        if let Some(st) = &ns.style {
            let t = Target::Node {
                name: tname.clone(),
                chain: chain.clone(),
                parent_layout: parent_layout.to_string(),
                own_layout: self.node_layout_value(&chain, ns),
            };
            for d in st {
                self.decl(d, &t);
            }
        }
        if let Some(ch) = &ns.children {
            let lay = self.node_layout(&chain, ns);
            self.stmts(ch, &lay);
        }
    }
}

// A node's cascaded layout: Some(word), or None when it is not a plain word.
fn own_layout(v: &Option<Value>) -> Option<&str> {
    match v {
        None => Some("flow"),
        Some(v) => crate::style::ident_of(v),
    }
}

// The bare names in a colour value that are not colours (gradient stops included).
fn bad_colors(v: &Value) -> Vec<String> {
    fn expr(e: &Expr, out: &mut Vec<String>) {
        match e {
            Expr::Ident(n, _) if !crate::style::is_named_color(n) => out.push(n.clone()),
            Expr::Tuple(items, _) => items.iter().for_each(|i| expr(i, out)),
            // (a run of words is the resolver's to judge)
            Expr::Call(n, args, _) if crate::paint::is_gradient(n) => args.iter().for_each(|i| expr(i, out)),
            _ => {}
        }
    }
    let mut out = Vec::new();
    for t in top_terms(v) {
        match t {
            Term::Ident(n, _) if !crate::style::is_named_color(n) => out.push(n.clone()),
            Term::Call(n, args, _) if crate::paint::is_gradient(n) => args.iter().for_each(|i| expr(i, &mut out)),
            _ => {}
        }
    }
    out
}

fn rule_target(r: &Rule, sheet: &SheetModel) -> Option<Target> {
    if r.selector.len() == 1 {
        let c = &r.selector[0];
        if c.bars && c.type_name.as_deref() == Some("-") && c.id.is_none() && c.classes.is_empty() {
            return Some(Target::Link);
        }
        if c.bars && c.id.is_none() && c.classes.is_empty() {
            let t = c.type_name.clone()?;
            // (an unknown type's rule still checks its properties and values)
            let Some((_, chain)) = crate::scene::type_chain(sheet, &t) else { return Some(Target::Class) };
            return Some(Target::Node { name: t, chain, parent_layout: String::new(), own_layout: None });
        }
        if !c.bars && c.id.is_none() && c.classes.len() == 1 {
            return Some(Target::Class);
        }
        if c.id.is_some() && c.classes.is_empty() {
            return Some(Target::Id);
        }
    }
    if r.selector.len() >= 2 {
        // a scoped rule checks against what its last compound names
        let b = r.selector.last().unwrap();
        if b.bars && b.type_name.as_deref() == Some("-") {
            return Some(Target::Link);
        }
        if b.bars && b.id.is_none() && b.classes.is_empty() {
            if let Some(t) = &b.type_name {
                if let Some((_, chain)) = crate::scene::type_chain(sheet, t) {
                    return Some(Target::Node { name: t.clone(), chain, parent_layout: String::new(), own_layout: None });
                }
            }
            return Some(Target::Class);
        }
        if b.id.is_some() && b.classes.is_empty() {
            return Some(Target::Id);
        }
        return Some(Target::Class);
    }
    None
}

// Who wears each class: (class name → wearers), from every statement.
fn wearers(doc: &Doc, sheet: &SheetModel) -> Vec<(String, Wearer)> {
    let mut out = Vec::new();
    fn walk(stmts: &[Stmt], sheet: &SheetModel, out: &mut Vec<(String, Wearer)>) {
        for s in stmts {
            match s {
                Stmt::Node(ns) => node(ns, sheet, out),
                Stmt::Text(t) => {
                    for c in &t.classes {
                        out.push((c.clone(), Wearer::Text));
                    }
                }
                Stmt::Link(l) => {
                    for c in &l.classes {
                        out.push((c.clone(), Wearer::Link));
                    }
                    for g in &l.groups {
                        for ep in g {
                            if let Endpoint::Node(ns) = ep {
                                node(ns, sheet, out);
                            }
                        }
                    }
                    if let Some(ls) = &l.labels {
                        walk(ls, sheet, out);
                    }
                }
            }
        }
    }
    fn node(ns: &NodeStmt, sheet: &SheetModel, out: &mut Vec<(String, Wearer)>) {
        let tname = ns.type_name.clone().unwrap_or_else(|| "box".to_string());
        // (a node of an unknown type wears nothing; its children still do)
        if let Some((_, chain)) = crate::scene::type_chain(sheet, &tname) {
            for c in &ns.classes {
                out.push((c.clone(), Wearer::Node(chain.clone())));
            }
        }
        if let Some(ch) = &ns.children {
            walk(ch, sheet, out);
        }
    }
    walk(&doc.stmts, sheet, &mut out);
    for d in &sheet.defines {
        if let Some(b) = &d.body {
            walk(b, sheet, &mut out);
        }
    }
    out
}

// The V-phase. Returns every diagnostic in order; any error stops the compile.
pub fn validate(doc: &Doc, sheet: &SheetModel) -> Vec<Diag> {
    if let Some(e) = check_defines(doc, sheet) {
        return vec![e];
    }
    let mut v = V { sheet, out: Vec::new() };
    let root_layout = sheet
        .root
        .iter()
        .rev()
        .find(|d| d.name == "layout")
        .and_then(|d| crate::style::ident_of(&d.value))
        .unwrap_or("flow")
        .to_string();
    if let Some(sh) = &doc.sheet {
        for item in &sh.items {
            match item {
                SheetItem::Decl(d) => v.decl(d, &Target::Root(root_layout.clone())),
                SheetItem::Rule(r) => {
                    if let Some(t) = rule_target(r, sheet) {
                        for d in &r.decls {
                            v.decl(d, &t);
                        }
                    }
                }
                SheetItem::Define(df) => {
                    if let Some((_, chain)) = crate::scene::type_chain(sheet, &df.name) {
                        let t = Target::Node { name: df.name.clone(), chain, parent_layout: String::new(), own_layout: None };
                        for d in &df.decls {
                            v.decl(d, &t);
                        }
                    }
                }
                _ => {}
            }
        }
        // classes: never worn, or a declaration that no wearer reads
        let worn = wearers(doc, sheet);
        for item in &sh.items {
            if let SheetItem::Rule(r) = item {
                let c = &r.selector[0];
                if r.selector.len() != 1 || c.bars || c.id.is_some() || c.classes.len() != 1 {
                    continue;
                }
                let cname = &r.selector[0].classes[0];
                let ws: Vec<&Wearer> = worn.iter().filter(|(c, _)| c == cname).map(|(_, w)| w).collect();
                if ws.is_empty() {
                    v.out.push(Diag::warning("class-never-worn", &format!("class '.{}' is never worn", cname), r.span));
                    continue;
                }
                for d in &r.decls {
                    if let Some(p) = prop(&d.name) {
                        if !ws.iter().any(|w| meaningful(p, w)) {
                            v.out.push(Diag::warning(
                                "inert-on-every-wearer",
                                &format!("'.{} {{ {}: … }}' is inert on every wearer", cname, d.name),
                                d.span,
                            ));
                        }
                    }
                }
            }
        }
    }
    v.stmts(&doc.stmts, &root_layout);
    v.out.extend(endpoint_warnings(doc));
    if v.out.iter().any(|d| d.severity == crate::diag::Severity::Error) {
        PHASE.with(|p| *p.borrow_mut() = v.out.clone());
    }
    v.out
}

// ------------------------------------------------------------------ endpoints

// The warnings link endpoints raise as they resolve, once every node is
// built: a bare name that auto-creates a box while a declared node of that
// name lives elsewhere, and one that looks like a typo of a name under the
// link's container (its own scope; boxes auto-created so far included). A
// container's links resolve before those of the containers inside it.
fn endpoint_warnings(doc: &Doc) -> Vec<Diag> {
    struct Named {
        id: String,
        scope: String,
        path: String,
        // the containers it sits under (0 = the scene)
        under: Vec<usize>,
    }
    struct Container<'d> {
        scope: String,
        under: Vec<usize>,
        links: Vec<&'d LinkStmt>,
        kids: Vec<usize>,
    }
    fn walk<'d>(stmts: &'d [Stmt], c: usize, all: &mut Vec<Container<'d>>, named: &mut Vec<Named>) {
        for s in stmts {
            match s {
                Stmt::Node(ns) => node(ns, c, all, named),
                Stmt::Link(l) => {
                    for ep in l.groups.iter().flatten() {
                        if let Endpoint::Node(ns) = ep {
                            node(ns, c, all, named);
                        }
                    }
                    all[c].links.push(l);
                }
                Stmt::Text(_) => {}
            }
        }
    }
    fn node<'d>(ns: &'d NodeStmt, c: usize, all: &mut Vec<Container<'d>>, named: &mut Vec<Named>) {
        let scope = all[c].scope.clone();
        let mut under = all[c].under.clone();
        under.push(c);
        let inner = match &ns.id {
            Some(id) => {
                let path = if scope.is_empty() { id.clone() } else { format!("{}.{}", scope, id) };
                named.push(Named { id: id.clone(), scope: scope.clone(), path: path.clone(), under: under.clone() });
                path
            }
            None => scope,
        };
        if let Some(ch) = &ns.children {
            let k = all.len();
            all.push(Container { scope: inner, under, links: Vec::new(), kids: Vec::new() });
            all[c].kids.push(k);
            walk(ch, k, all, named);
        }
    }
    let mut all = vec![Container { scope: String::new(), under: Vec::new(), links: Vec::new(), kids: Vec::new() }];
    let mut named = Vec::new();
    walk(&doc.stmts, 0, &mut all, &mut named);
    let declared = named.len();
    // containers in resolution order: each before the ones inside it
    let mut order = Vec::new();
    let mut stack = vec![0usize];
    while let Some(c) = stack.pop() {
        order.push(c);
        for &k in all[c].kids.iter().rev() {
            stack.push(k);
        }
    }
    let mut out = Vec::new();
    for c in order {
        let scope = all[c].scope.clone();
        for l in all[c].links.clone() {
            for ep in l.groups.iter().flatten() {
                let p = match ep {
                    Endpoint::Path(p) if p.parts.len() == 1 => p,
                    _ => continue,
                };
                let name = &p.parts[0];
                if named.iter().any(|n| n.scope == scope && &n.id == name) {
                    continue;
                }
                if let Some(other) = named[..declared].iter().find(|n| &n.id == name) {
                    let at = if scope.is_empty() { "scene root".to_string() } else { scope.clone() };
                    let msg = format!("endpoint '{}' auto-created at {} — a node '{}' also exists at '{}'", name, at, name, other.path);
                    out.push(Diag::warning("validate", &msg, p.span));
                }
                // nearest first; on a tie a declared name (alphabetically) before
                // an auto-created one (the earliest)
                let mut best: Option<(usize, usize, String, usize)> = None;
                for (k, n) in named.iter().enumerate() {
                    if n.scope != scope || !n.under.contains(&c) {
                        continue;
                    }
                    if let Some(d) = near_distance(name, &n.id) {
                        let key = if k < declared { (d, 0, n.id.clone(), 0) } else { (d, 1, String::new(), k) };
                        if best.as_ref().map(|b| key < *b).unwrap_or(true) {
                            best = Some(key);
                        }
                    }
                }
                if let Some(near) = best.map(|b| named[if b.1 == 0 { named.iter().position(|n| n.id == b.2).unwrap_or(0) } else { b.3 }].id.clone()) {
                    let msg = format!("'{}' auto-creates a new box; did you mean '{}'?", name, near);
                    out.push(Diag::warning("validate", &msg, p.span));
                }
                let mut under = all[c].under.clone();
                under.push(c);
                named.push(Named { id: name.clone(), scope: scope.clone(), path: String::new(), under });
            }
        }
    }
    out
}

// ------------------------------------------------------------------ points

// Is a `points:` term parametric — does it read the curve parameter `u` or
// any of the document's own bindings (directly or through a function)?
pub fn term_uses_u(env: &crate::eval::Env, t: &Term) -> bool {
    fn expr(env: &crate::eval::Env, e: &Expr, depth: usize) -> bool {
        if depth > 32 {
            return false;
        }
        match e {
            Expr::Ident(n, _) => n == "u" || env.vars.contains_key(n) || env.funcs.contains_key(n),
            Expr::Call(name, args, _) => {
                if args.iter().any(|a| expr(env, a, depth + 1)) {
                    return true;
                }
                env.funcs.contains_key(name)
            }
            Expr::Unary(_, a, _) => expr(env, a, depth + 1),
            Expr::Bin(_, a, b, _) => expr(env, a, depth + 1) || expr(env, b, depth + 1),
            Expr::Ternary(a, b, c, _) => expr(env, a, depth + 1) || expr(env, b, depth + 1) || expr(env, c, depth + 1),
            Expr::Tuple(items, _) => items.iter().any(|i| expr(env, i, depth + 1)),
            Expr::Block(binds, body, _) => binds.iter().any(|(_, e)| expr(env, e, depth + 1)) || expr(env, body, depth + 1),
            _ => false,
        }
    }
    fn term(env: &crate::eval::Env, t: &Term, depth: usize) -> bool {
        match t {
            Term::Group(e, _) => expr(env, e, depth),
            Term::Call(n, args, sp) => expr(env, &Expr::Call(n.clone(), args.clone(), *sp), depth),
            Term::Ident(n, _) => n == "u",
            _ => false,
        }
    }
    term(env, t, 0)
}

fn term_parametric(env: &crate::eval::Env, t: &Term) -> bool {
    matches!(t, Term::Group(..) | Term::Call(..)) && term_uses_u(env, t)
}

// ------------------------------------------------------------------ links

// Checks made as a link resolves: dimension-only keys outside a drawing,
// then its label texts (text cannot carry box properties).
pub fn link_checks(sheet: &SheetModel, l: &LinkStmt, container_layout: &str) -> Result<(), Diag> {
    if !matches!(container_layout, "drawing" | "floorplan") {
        const IN_DRAWING: &str = "it belongs in a 'layout: drawing' (or its 'floorplan' dialect)";
        // the link's cascade: link rules, its classes, its own style
        let mut all: Vec<&Decl> = sheet.link_rules.iter().collect();
        for c in &l.classes {
            if let Some(cr) = sheet.class(c) {
                all.extend(cr.decls.iter());
            }
        }
        all.extend(l.style.iter().flatten());
        for d in all {
            let what = match d.name.as_str() {
                "tol" => "composes a dimension's text",
                "project" => "picks a dimension's axis",
                _ => continue,
            };
            return Err(Diag::error("resolve", &format!("'{}' {} — {}", d.name, what, IN_DRAWING), l.span));
        }
    }
    if let Some(ls) = &l.labels {
        for s in ls {
            if let Stmt::Text(t) = s {
                if let Some(st) = &t.style {
                    stmt_decls(sheet, st, Some("a link label is text"))?;
                }
            }
        }
    }
    Ok(())
}

// ------------------------------------------------------------------ markers

const MARKERS: &[&str] = &[
    "none", "arrow", "dot", "circle", "diamond", "datum", "crow", "many", "one", "exactly-one", "zero-or-one",
    "one-or-many", "zero-or-many",
];

// A marker property's value must name a known marker (declarations in
// cascade order; the first bad one is reported).
pub fn marker_error(props: &[(String, Value)]) -> Option<String> {
    for (k, v) in props {
        if !matches!(k.as_str(), "marker" | "marker-end" | "marker-start") {
            continue;
        }
        match crate::style::single_term(v) {
            Some(Term::Ident(s, _)) => {
                if !MARKERS.contains(&s.as_str()) {
                    return Some(format!("invalid marker value '{}'", s));
                }
            }
            _ => return Some("marker requires an identifier value".to_string()),
        }
    }
    None
}

// A node's declarations in cascade order (type chain base first, classes,
// id rules, inline), every occurrence kept.
pub fn cascade_decls(sheet: &SheetModel, n: &crate::scene::Node) -> Vec<(String, Value)> {
    let mut out = Vec::new();
    for t in n.chain.iter().rev() {
        if let Some(df) = sheet.define(t) {
            out.extend(df.decls.iter().map(|d| (d.name.clone(), d.value.clone())));
        }
        for d in sheet.type_rule(t) {
            out.push((d.name.clone(), d.value.clone()));
        }
    }
    for c in &n.classes {
        if let Some(cr) = sheet.class(c) {
            out.extend(cr.decls.iter().map(|d| (d.name.clone(), d.value.clone())));
        }
    }
    if let Some(id) = &n.id {
        for (rid, ds) in &sheet.id_rules {
            if rid == id {
                out.extend(ds.iter().map(|d| (d.name.clone(), d.value.clone())));
            }
        }
    }
    out.extend(n.inline.iter().map(|d| (d.name.clone(), d.value.clone())));
    out
}

// Sequence-only properties reached through a rule or class; a path needs its
// data; a line or polygon needs enough well-formed points.
pub fn cascade_checks(ctx: &crate::compile::Ctx) -> Result<(), Diag> {
    use crate::types::Prim;
    for (i, n) in ctx.nodes.iter().enumerate().skip(1) {
        let parent_layout = n.parent.map(|p| ctx.comp[p].layout.as_str()).unwrap_or("flow");
        if parent_layout != "sequence" {
            for k in ["place", "activation"] {
                if n.props.contains_key(k) {
                    let _ = i;
                    return Err(node_err(&format!("'{}' is valid only in a 'layout: sequence'", k), n.span));
                }
            }
        }
        if parent_layout == "chart" || parent_layout == "pie" || n.props.contains_key("chrome") || n.is("plane") {
            continue;
        }
        if n.prim == Prim::Path && !n.props.contains_key("path") {
            return Err(Diag::error("missing-required-property", "'|path|' requires 'path'", n.span));
        }
        if matches!(n.prim, Prim::Line | Prim::Poly) {
            if let Some(v) = n.props.get("points") {
                let env = &ctx.sheet.env;
                let samples = n.props.get("samples").and_then(|s| crate::style::value_num(env, s)).unwrap_or(2.0).max(2.0) as usize;
                let mut count = 0usize;
                let bound = |n: &str| env.vars.get(n).and_then(|x| x.num()).is_some();
                for g in &v.groups {
                    let k = if g.len() == 1 {
                        match &g[0] {
                            Term::Num(..) => 1,
                            Term::Ident(n, _) if bound(n) => 1,
                            Term::Ident(..) => return Err(node_err("expected a number or tuple, got identifier", n.span)),
                            Term::Str(..) => return Err(node_err("expected a number or tuple, got string", n.span)),
                            Term::Var(x, _) => {
                                return Err(node_err(
                                    &format!("var(--lini-{}) is a visual variable; layout attrs require a number or tuple", x),
                                    n.span,
                                ))
                            }
                            t @ (Term::Group(..) | Term::Call(..)) => {
                                // only a lone parametric point samples the curve
                                if v.groups.len() == 1 && term_uses_u(env, t) {
                                    count += samples;
                                    continue;
                                }
                                let r = match t {
                                    Term::Group(e, _) => env.eval(e, &std::collections::HashMap::new()),
                                    _ => env.eval_term(t, &std::collections::HashMap::new()),
                                };
                                match r {
                                    Ok(crate::eval::EV::Tuple(xs)) => xs.len(),
                                    _ => 1,
                                }
                            }
                            _ => continue,
                        }
                    } else {
                        for t in g {
                            match t {
                                Term::Ident(x, _) if !bound(x) => return Err(node_err("expected a number, got identifier", n.span)),
                                Term::Str(..) => return Err(node_err("expected a number, got string", n.span)),
                                Term::Group(e, _) => {
                                    if let Ok(crate::eval::EV::Tuple(_)) = env.eval(e, &std::collections::HashMap::new()) {
                                        return Err(node_err("expected a number, got tuple", n.span));
                                    }
                                }
                                _ => {}
                            }
                        }
                        g.len()
                    };
                    if k != 2 {
                        return Err(node_err(&format!("expected a 2-tuple, got {} value(s)", k), n.span));
                    }
                    count += 1;
                }
                let need = if n.prim == Prim::Poly { 3 } else { 2 };
                if count < need {
                    return Err(Diag::error(
                        "missing-required-property",
                        &format!("'|{}|' requires at least {} points", n.prim.name(), need),
                        n.span,
                    ));
                }
            }
        }
    }
    Ok(())
}

// ------------------------------------------------------------------ ids

// How far `id` is from a bare endpoint `name` when it could be what was
// meant: within min(2, len − 1) edits, and a numbered sibling ('c2' for
// 'c', 'n1' for 'n2') is not a typo.
fn near_distance(name: &str, id: &str) -> Option<usize> {
    let limit = 2.min(name.chars().count().saturating_sub(1));
    // numbered siblings ('n1' / 'n2', 'c' / 'c2') share a stem
    if id == name || name.trim_end_matches(|c: char| c.is_ascii_digit()) == id.trim_end_matches(|c: char| c.is_ascii_digit()) {
        return None;
    }
    let d = crate::util::levenshtein(name, id);
    (d <= limit).then_some(d)
}

// ------------------------------------------------------------------ layout values

fn node_err(msg: &str, span: Span) -> Diag {
    Diag::error("layout", msg, span)
}

// A layout attribute's numbers: "expected a number or tuple, got …".
fn layout_nums(v: &Value, env: &crate::eval::Env) -> Result<Vec<f64>, String> {
    let mut out = Vec::new();
    let terms: Vec<&Term> = v.groups.iter().flat_map(|g| g.iter()).collect();
    let single = terms.len() == 1;
    for t in terms.iter() {
        let what = match t {
            Term::Num(x, _, _) => {
                out.push(*x);
                continue;
            }
            Term::Call(n, _, _) if builtin_arity(n).is_none() && !env.funcs.contains_key(n) => "function call",
            Term::Group(..) | Term::Call(..) => match crate::style::term_num(env, t) {
                Some(x) => {
                    out.push(x);
                    continue;
                }
                None => "tuple",
            },
            Term::Ident(n, _) => match env.vars.get(n).and_then(|v| v.num()) {
                Some(x) => {
                    out.push(x);
                    continue;
                }
                None => "identifier",
            },
            Term::Str(..) => "string",
            Term::Hash(..) => "hex color",
            Term::Var(n, _) => {
                return Err(format!("var(--lini-{}) is a visual variable; layout attrs require a number or tuple", n));
            }
            _ => "value",
        };
        if what == "tuple" {
            continue;
        }
        return Err(if single {
            format!("expected a number or tuple, got {}", what)
        } else {
            format!("expected a number, got {}", what)
        });
    }
    Ok(out)
}

// Layout attributes, read the way the layout pass meets them: children
// first; then, placing a container's children, their pins; the container's
// own layout, direction, padding and gap; its children's offsets
// (translate); last its own mirror and scale.
// `overflows`: the max-width overflows measuring found, if it ran (a box's
// overflow is met after its children, reading its padding first).
pub fn layout_values(ctx: &crate::compile::Ctx, overflows: &[(usize, Diag)]) -> Result<(), Diag> {
    fn pin(ctx: &crate::compile::Ctx, i: usize) -> Result<(), Diag> {
        let n = &ctx.nodes[i];
        if let Some(v) = n.props.get("pin") {
            let words: Vec<&str> = v
                .groups
                .iter()
                .flat_map(|g| g.iter())
                .map(|t| match t {
                    Term::Ident(s, _) => s.as_str(),
                    _ => "?",
                })
                .collect();
            let ok = match words.as_slice() {
                ["none"] | ["center"] | ["top"] | ["bottom"] | ["left"] | ["right"] => true,
                [a, b] => {
                    let v = |x: &str| x == "top" || x == "bottom";
                    let h = |x: &str| x == "left" || x == "right";
                    (v(a) && h(b)) || (h(a) && v(b))
                }
                _ => false,
            };
            if !ok {
                return Err(node_err(
                    "'pin' expects none, center, an edge (top/bottom/left/right), or a corner (e.g. 'top right')",
                    n.span,
                ));
            }
        }
        Ok(())
    }
    fn visit(ctx: &crate::compile::Ctx, i: usize, ov: &[(usize, Diag)]) -> Result<(), Diag> {
        for &c in &ctx.nodes[i].children {
            visit(ctx, c, ov)?;
        }
        let n = &ctx.nodes[i];
        let env = &ctx.sheet.env;
        let props: Vec<(String, Value)> = if i == 0 {
            n.inline.iter().map(|d| (d.name.clone(), d.value.clone())).collect()
        } else {
            n.props.iter().map(|(k, v)| (k.clone(), v.clone())).collect()
        };
        let get = |k: &str| props.iter().find(|(n, _)| n == k).map(|(_, v)| v);
        let padding = || -> Result<(), Diag> {
            if let Some(v) = get("padding") {
                let xs = layout_nums(v, env).map_err(|m| node_err(&m, n.span))?;
                if !matches!(xs.len(), 1 | 2 | 4) {
                    return Err(node_err(&format!("expected 1, 2, or 4 values, got {}", xs.len()), n.span));
                }
            }
            Ok(())
        };
        // a fixed width cannot pass the box's max-width
        if i != 0 {
            let num = |k: &str| get(k).and_then(|v| crate::style::value_num(env, v));
            if let (Some(w), Some(m)) = (num("width"), num("max-width")) {
                if w > m {
                    return Err(node_err(&format!("'width: {}' exceeds 'max-width: {}'", crate::util::f4(w), crate::util::f4(m)), n.span));
                }
            }
        }
        // a max-width box measures its children against the room its padding leaves
        if crate::layout::max_width_bounds(ctx, i) && !n.children.is_empty() {
            padding()?;
            if let Some((_, d)) = ov.iter().find(|(k, _)| *k == i) {
                return Err(d.clone());
            }
        }
        for &c in &n.children {
            pin(ctx, c)?;
        }
        // a container's own layout knobs are read when its children are placed
        let container = !n.children.is_empty() && n.prim != crate::types::Prim::Text;
        if container {
            const ENGINES: &str = "flow, grid, stack, tree, sequence, drawing, floorplan or schematic";
            if let Some(v) = get("layout") {
                match crate::style::single_term(v) {
                    Some(Term::Ident(s, _)) => {
                        if matches!(s.as_str(), "row" | "column") {
                            return Err(node_err(
                                &format!("'layout: {}' is not a layout — flow is the default; set 'direction: {}'", s, s),
                                n.span,
                            ));
                        }
                        if !matches!(
                            s.as_str(),
                            "flow" | "grid" | "stack" | "tree" | "sequence" | "drawing" | "floorplan" | "schematic" | "chart" | "pie"
                        ) {
                            return Err(node_err(&format!("unknown layout '{}' — expected {}", s, ENGINES), n.span));
                        }
                    }
                    _ => return Err(node_err(&format!("'layout' expects an engine name — {}", ENGINES), n.span)),
                }
            }
            if let Some(v) = get("direction") {
                match crate::style::single_term(v) {
                    Some(Term::Ident(s, _)) => {
                        if !matches!(s.as_str(), "row" | "column" | "radial") {
                            return Err(node_err(&format!("unknown direction '{}' — expected row or column", s), n.span));
                        }
                    }
                    _ => return Err(node_err("'direction' expects row or column", n.span)),
                }
            }
        }
        padding()?;
        if container {
            if let Some(v) = get("gap") {
                let xs = layout_nums(v, env).map_err(|m| node_err(&m, n.span))?;
                if !matches!(xs.len(), 1 | 2) {
                    return Err(node_err(&format!("'gap' expects 1 or 2 values, got {}", xs.len()), n.span));
                }
            }
        }
        // a grid places its children: columns, then each child's span / cell
        crate::table::grid_checks(ctx, i)?;
        for &c in &n.children {
            if let Some(v) = ctx.nodes[c].props.get("translate") {
                layout_nums(v, env).map_err(|m| node_err(&m, ctx.nodes[c].span))?;
            }
        }
        if i == 0 {
            return Ok(());
        }
        if let Some(v) = get("mirror") {
            let ok = match crate::style::single_term(v) {
                Some(Term::Ident(s, _)) => matches!(s.as_str(), "x-axis" | "y-axis" | "none"),
                Some(Term::Num(..)) | Some(Term::Group(..)) => true,
                Some(t @ Term::Call(..)) => crate::style::term_num(env, t).is_some(),
                Some(_) => false,
                None => true,
            };
            if !ok {
                return Err(node_err("'mirror' takes x-axis, y-axis, a bearing, or none", n.span));
            }
        }
        // (an axis's scale is log or linear)
        if let Some(v) = get("scale").filter(|_| !n.is("axis")) {
            match crate::style::value_num(env, v) {
                Some(x) if x > 0.0 => {}
                _ => return Err(node_err("'scale' must be > 0", n.span)),
            }
        }
        Ok(())
    }
    visit(ctx, 0, overflows)
}

// ------------------------------------------------------------------ types

// Every node's type must exist before values resolve (reported in order).
pub fn check_types(doc: &Doc, sheet: &SheetModel) -> Result<(), Diag> {
    // a scoped selector names only known types
    if let Some(sh) = &doc.sheet {
        for item in &sh.items {
            if let SheetItem::Rule(r) = item {
                if r.selector.len() < 2 {
                    continue;
                }
                for c in &r.selector {
                    if let Some(t) = &c.type_name {
                        if t != "-" && crate::scene::type_chain(sheet, t).is_none() {
                            return Err(Diag::error("unknown-type", &format!("unknown type '{}' in selector", t), r.span));
                        }
                    }
                }
            }
        }
    }
    fn walk(stmts: &[Stmt], sheet: &SheetModel) -> Result<(), Diag> {
        for s in stmts {
            match s {
                Stmt::Node(ns) => node(ns, sheet)?,
                Stmt::Link(l) => {
                    for g in &l.groups {
                        for ep in g {
                            if let Endpoint::Node(ns) = ep {
                                node(ns, sheet)?;
                            }
                        }
                    }
                }
                Stmt::Text(_) => {}
            }
        }
        Ok(())
    }
    fn node(ns: &NodeStmt, sheet: &SheetModel) -> Result<(), Diag> {
        let tname = ns.type_name.clone().unwrap_or_else(|| "box".to_string());
        if tname == "link" {
            return Err(Diag::error("resolve", "links are drawn by operators, not the '|link|' type", ns.head_span));
        }
        if crate::scene::type_chain(sheet, &tname).is_none() {
            return Err(crate::scene::unknown_type(&tname, ns.span));
        }
        if let Some(ch) = &ns.children {
            walk(ch, sheet)?;
        }
        Ok(())
    }
    walk(&doc.stmts, sheet)
}

// A define whose base chain never reaches a built-in names the missing type.
fn check_defines(doc: &Doc, sheet: &SheetModel) -> Option<Diag> {
    let sh = doc.sheet.as_ref()?;
    // a define takes a fresh name: neither a built-in nor one defined before
    let mut seen: Vec<&str> = Vec::new();
    for item in &sh.items {
        if let SheetItem::Define(df) = item {
            if crate::types::find(&df.name).is_some() {
                return Some(Diag::error("shadows-builtin", &format!("'{}' shadows a built-in type", df.name), df.span));
            }
            if seen.contains(&df.name.as_str()) {
                return Some(Diag::error("resolve", &format!("duplicate type '{}'", df.name), df.span));
            }
            seen.push(&df.name);
        }
    }
    for item in &sh.items {
        if let SheetItem::Define(df) = item {
            if crate::scene::type_chain(sheet, &df.name).is_none() {
                // the first name along the chain that is neither defined nor built in
                let mut cur = df.base.clone();
                let mut guard = 0;
                while guard < 50 {
                    guard += 1;
                    match sheet.define(&cur) {
                        Some(d) => cur = d.base.clone(),
                        None => break,
                    }
                }
                return Some(crate::scene::unknown_type(&cur, df.span));
            }
        }
    }
    None
}

// ------------------------------------------------------------------ R-phase

const QUOTED: &[&str] = &[
    "approved", "author", "date", "department", "document-type", "drawing-number", "reference", "revision",
    "sheet-number", "status", "title", "hint", "href", "path", "prefix", "src", "categories", "labels",
];

fn list_example(name: &str) -> Option<&'static str> {
    Some(match name {
        "align" => "align: start, center, end",
        "justify" => "justify: start, center, end",
        "columns" => "columns: 80, 140, auto",
        "rows" => "rows: 80, 140, auto",
        "categories" => "categories: \"a\", \"b\"",
        "labels" => "labels: \"a\", \"b\"",
        _ => return None,
    })
}

const COMPUTED_ARG: &str = "a computed argument must be a number, an expression, a bound name, or a compute call";
const TRAILING: &str = "trailing tokens after the expression";

struct R<'a> {
    sheet: &'a SheetModel,
}

type Locals = std::collections::HashMap<String, f64>;

fn builtin_arity(name: &str) -> Option<usize> {
    Some(match name {
        "sin" | "cos" | "tan" | "sqrt" | "abs" | "exp" | "ln" | "log" | "floor" | "round" => 1,
        "pow" => 2,
        "clamp" => 3,
        "min" | "max" => usize::MAX,
        _ => return None,
    })
}

impl<'a> R<'a> {
    fn lazy(&self, name: &str) -> Option<&Term> {
        if self.sheet.env.vars.contains_key(name) {
            return None;
        }
        match self.sheet.env.funcs.get(name) {
            Some(f) if f.params.is_empty() && self.sheet.lazy.iter().any(|n| n == name) => Some(&f.body),
            _ => None,
        }
    }

    fn term(&self, t: &Term, l: &Locals, depth: usize) -> Result<(), String> {
        match t {
            Term::Group(e, _) => self.eval(e, l, depth),
            Term::Call(..) => self.eval_term_call(t, l, depth),
            Term::Ident(n, _) => match self.lazy(n) {
                Some(b) => self.term(b, l, depth + 1),
                None => Ok(()),
            },
            Term::Num(..) => Ok(()),
            _ => Ok(()),
        }
    }

    fn eval_term_call(&self, t: &Term, l: &Locals, depth: usize) -> Result<(), String> {
        if let Term::Call(name, args, sp) = t {
            self.eval(&Expr::Call(name.clone(), args.clone(), *sp), l, depth)
        } else {
            Ok(())
        }
    }

    // Evaluate for its errors (the reference's messages, short-circuiting like it).
    fn eval(&self, e: &Expr, l: &Locals, depth: usize) -> Result<(), String> {
        self.value(e, l, depth).map(|_| ())
    }

    fn value(&self, e: &Expr, l: &Locals, depth: usize) -> Result<f64, String> {
        if depth > 64 {
            return Ok(0.0);
        }
        let env = &self.sheet.env;
        match e {
            Expr::Num(v, _) => Ok(*v),
            Expr::Percent(v, _) => Err(format!("unexpected '{}%' in an expression", crate::util::f4(*v))),
            Expr::Str(s, _) => Err(format!("unexpected '\"{}\"' in an expression", s)),
            Expr::Hash(h, _) => Err(format!("unexpected '#{}' in an expression", h)),
            Expr::Var(n, _) => Err(format!("unknown name '{}' in an expression", n)),
            Expr::Ident(n, _) => {
                if let Some(v) = l.get(n) {
                    return Ok(*v);
                }
                if let Some(v) = env.vars.get(n) {
                    return Ok(v.num().unwrap_or(0.0));
                }
                if let Some(b) = self.lazy(n) {
                    self.term(b, l, depth + 1)?;
                    return Ok(0.0);
                }
                if let Some(f) = env.funcs.get(n) {
                    if !f.params.is_empty() {
                        return Err(format!("'{}' takes {} argument(s), got 0", n, f.params.len()));
                    }
                }
                match n.as_str() {
                    "pi" => Ok(std::f64::consts::PI),
                    "e" => Ok(std::f64::consts::E),
                    _ => Err(format!("unknown name '{}' in an expression", n)),
                }
            }
            Expr::Call(name, _, _) if name == crate::parser::RUN => Err(TRAILING.into()),
            Expr::Call(name, args, _) => {
                if matches!(name.as_str(), "rgb" | "rgba" | "hsl" | "hsla" | "oklch" | "repeat")
                    || crate::paint::is_gradient(name)
                {
                    return Ok(0.0);
                }
                let mut xs = Vec::new();
                for a in args {
                    match a {
                        Expr::Str(..) | Expr::Var(..) | Expr::Hash(..) | Expr::Percent(..) => return Err(COMPUTED_ARG.into()),
                        Expr::Call(n, _, _) if n == crate::parser::RUN => return Err(COMPUTED_ARG.into()),
                        _ => xs.push(self.value(a, l, depth + 1)?),
                    }
                }
                if let Some(f) = env.funcs.get(name) {
                    if f.params.len() != args.len() && !self.sheet.lazy.iter().any(|x| x == name) {
                        return Err(format!("'{}' takes {} argument(s), got {}", name, f.params.len(), args.len()));
                    }
                    if self.sheet.lazy.iter().any(|x| x == name) {
                        return Err(format!("'{}' takes 0 argument(s), got {}", name, args.len()));
                    }
                    let mut l2 = l.clone();
                    for (p, x) in f.params.iter().zip(xs.iter()) {
                        l2.insert(p.clone(), *x);
                    }
                    self.term(&f.body, &l2, depth + 1)?;
                    return Ok(0.0);
                }
                if env.vars.contains_key(name) {
                    return Err(format!("'{}' takes 0 argument(s), got {}", name, args.len()));
                }
                match builtin_arity(name) {
                    None => Err(format!("unknown function '{}'", name)),
                    Some(usize::MAX) => {
                        if args.is_empty() {
                            Err(format!("'{}' needs at least one argument", name))
                        } else {
                            Ok(0.0)
                        }
                    }
                    Some(n) => {
                        if n != args.len() {
                            Err(format!("'{}' takes {} argument(s), got {}", name, n, args.len()))
                        } else {
                            Ok(0.0)
                        }
                    }
                }
            }
            Expr::Unary(_, a, _) => self.value(a, l, depth + 1),
            Expr::Bin(op, a, b, _) => {
                if op == "&&" || op == "||" {
                    return Err(TRAILING.into());
                }
                let x = self.value(a, l, depth + 1)?;
                let y = self.value(b, l, depth + 1)?;
                Ok(x + y)
            }
            Expr::Ternary(c, a, b, _) => {
                let cv = self.value(c, l, depth + 1)?;
                if cv != 0.0 {
                    self.value(a, l, depth + 1)
                } else {
                    self.value(b, l, depth + 1)
                }
            }
            Expr::Tuple(items, _) => {
                for it in items {
                    self.value(it, l, depth + 1)?;
                }
                Ok(0.0)
            }
            Expr::Block(binds, body, _) => {
                let mut l2 = l.clone();
                for (n, ex) in binds {
                    let v = self.value(ex, &l2, depth + 1)?;
                    l2.insert(n.clone(), v);
                }
                self.value(body, &l2, depth + 1)
            }
        }
    }

    fn color_fn(&self, name: &str, args: &[Expr], l: &Locals) -> Result<(), String> {
        color_range(name, args, &|e: &Expr| self.value(e, l, 0).ok())
    }
}

// rgb/hsl components in range: "rgb(300,0,0): component out of range".
pub fn color_range(name: &str, args: &[Expr], eval: &dyn Fn(&Expr) -> Option<f64>) -> Result<(), String> {
    {
        let hsl = name.starts_with("hsl");
        let mut parts = Vec::new();
        let mut bad = false;
        for (k, a) in args.iter().enumerate() {
            let (val, pct) = match a {
                Expr::Num(v, _) => (Some(*v), false),
                Expr::Percent(v, _) => (Some(*v), true),
                Expr::Unary(o, b, _) if o == "-" => match &**b {
                    Expr::Num(v, _) => (Some(-*v), false),
                    Expr::Percent(v, _) => (Some(-*v), true),
                    _ => (None, false),
                },
                Expr::Ident(..) | Expr::Var(..) | Expr::Str(..) | Expr::Hash(..) => (None, false),
                Expr::Call(n, _, _) if n == crate::parser::RUN => (None, false),
                other => (eval(other), false),
            };
            match val {
                None => parts.push("…".to_string()),
                Some(x) => {
                    parts.push(if pct { format!("{}%", crate::util::f4(x)) } else { crate::util::f4(x) });
                    let ok = match k {
                        0 if hsl => true,
                        0..=2 => {
                            if pct {
                                (0.0..=100.0).contains(&x)
                            } else if hsl {
                                (0.0..=100.0).contains(&x)
                            } else {
                                (0.0..=255.0).contains(&x)
                            }
                        }
                        3 => {
                            if pct {
                                (0.0..=100.0).contains(&x)
                            } else {
                                (0.0..=1.0).contains(&x)
                            }
                        }
                        _ => false,
                    };
                    if !ok {
                        bad = true;
                    }
                }
            }
        }
        if args.len() > 4 {
            bad = true;
        }
        if bad {
            return Err(format!("{}({}): component out of range", name, parts.join(",")));
        }
        Ok(())
    }
}

impl<'a> R<'a> {
    fn value_terms(&self, name: &str, v: &Value) -> Result<(), (String, &'static str)> {
        if name == "points" && v.groups.len() == 1 && v.groups[0].len() == 1 {
            let t = &v.groups[0][0];
            if term_parametric(&self.sheet.env, t) {
                let mut l = Locals::new();
                l.insert("u".into(), 0.0);
                self.term(t, &l, 0).map_err(|m| (m, "resolve"))?;
                let mut locals = std::collections::HashMap::new();
                locals.insert("u".to_string(), crate::eval::EV::Num(0.0));
                let r = match t {
                    Term::Group(e, _) => self.sheet.env.eval(e, &locals),
                    _ => self.sheet.env.eval_term(t, &locals),
                };
                if !matches!(r, Ok(crate::eval::EV::Tuple(ref xs)) if xs.len() == 2) {
                    return Err(("a parametric 'points:' expression must return a point '(x, y)'".into(), "resolve"));
                }
                return Ok(());
            }
        }
        let mut l = Locals::new();
        // only a lone parametric point reads the curve parameter
        if name == "points" && v.groups.len() == 1 && v.groups[0].len() == 1 {
            l.insert("u".into(), 0.0);
        }
        for t in v.groups.iter().flat_map(|g| g.iter()) {
            match t {
                Term::Call(n, args, _) if matches!(n.as_str(), "rgb" | "rgba" | "hsl" | "hsla") => {
                    self.color_fn(n, args, &l).map_err(|m| (m, "color-component-out-of-range"))?;
                }
                Term::Call(n, args, sp) if n == "oklch" => {
                    crate::style::oklch_call_hex(args, *sp).map_err(|d| (d.message, "resolve"))?;
                }
                Term::Call(n, args, sp) if crate::paint::is_gradient(n) => {
                    crate::paint::gradient_check(n, args, &self.sheet.env, *sp).map_err(|d| (d.message.clone(), d_family(&d)))?;
                }
                Term::Call(n, _, _) if n == "hatch" => {
                    if name != "fill" {
                        return Err(("'hatch' is a fill — 'stroke' takes a colour or gradient".into(), "resolve"));
                    }
                }
                Term::Call(n, _, _) if n == "repeat" => {}
                _ => self.term(t, &l, 0).map_err(|m| (m, "resolve"))?,
            }
        }
        Ok(())
    }

    fn decl(&self, d: &Decl, text: Option<&str>) -> Result<(), Diag> {
        let name = d.name.as_str();
        if !is_known(name) {
            return Ok(());
        }
        let sp = d.span;
        if let (Some(why), Some(p)) = (text, prop(name)) {
            if !p.text {
                return Err(Diag::error("resolve", &format!("'{}' needs a box — {}", name, why), sp));
            }
        }
        if name == "pattern" {
            return self.pattern(&d.value).map_err(|m| Diag::error("resolve", &m, sp));
        }
        if matches!(name, "draw" | "fn") {
            return Ok(());
        }
        if QUOTED.contains(&name) && d.value.groups.iter().flat_map(|g| g.iter()).any(|t| matches!(t, Term::Ident(..))) {
            return Err(Diag::error("resolve", &format!("'{}' takes a quoted string — write {}: \"…\"", name, name), sp));
        }
        if let Some(ex) = list_example(name) {
            if d.value.groups.iter().any(|g| g.len() > 1) {
                return Err(Diag::error(
                    "legacy-space-list",
                    &format!("'{}' takes comma-separated values — '{}'", name, ex),
                    sp,
                ));
            }
        }
        self.value_terms(name, &d.value).map_err(|(m, fam)| Diag::error(fam, &m, sp))
    }

    // `pattern: grid(cols, rows, dx, dy)` or `radial(count, radius)`.
    fn pattern(&self, v: &Value) -> Result<(), String> {
        const SHAPE: &str = "'pattern' takes grid(cols, rows, dx, dy) or radial(count, radius)";
        let (name, args) = match crate::style::single_term(v) {
            Some(Term::Call(n, a, _)) => (n.as_str(), a),
            _ => return Err(SHAPE.into()),
        };
        let want = match name {
            "grid" => 4,
            "radial" => 2,
            _ => return Err(SHAPE.into()),
        };
        if args.len() != want {
            return Err(SHAPE.into());
        }
        let l = Locals::new();
        let mut xs = Vec::new();
        for a in args {
            xs.push(self.value(a, &l, 0)?);
        }
        if name == "radial" {
            let count = match &args[0] {
                Expr::Num(x, _) => *x,
                _ => 2.0,
            };
            let radius = match &args[1] {
                Expr::Num(x, _) => *x,
                _ => 1.0,
            };
            if count < 2.0 || radius <= 0.0 {
                return Err("'radial' needs count ≥ 2 and radius > 0".into());
            }
        }
        let _ = xs;
        Ok(())
    }

    fn stmts(&self, stmts: &[Stmt], layout: &str) -> Result<(), Diag> {
        for s in stmts {
            match s {
                Stmt::Node(ns) => self.node(ns)?,
                Stmt::Text(t) => {
                    if let Some(st) = &t.style {
                        for d in st {
                            self.decl(d, Some("wrap the text in '|block|'"))?;
                        }
                    }
                }
                Stmt::Link(l) => {
                    for g in &l.groups {
                        for ep in g {
                            if let Endpoint::Node(ns) = ep {
                                self.node(ns)?;
                            }
                        }
                    }
                    let _ = layout;
                    if let Some(st) = &l.style {
                        for d in st {
                            self.decl(d, None)?;
                        }
                    }
                    if let Some(ls) = &l.labels {
                        for s in ls {
                            if let Stmt::Text(t) = s {
                                if let Some(st) = &t.style {
                                    for d in st {
                                        self.decl(d, Some(""))?;
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        Ok(())
    }

    fn node(&self, ns: &NodeStmt) -> Result<(), Diag> {
        if let Some(st) = &ns.style {
            for d in st {
                self.decl(d, None)?;
            }
        }
        if let Some(ch) = &ns.children {
            let tname = ns.type_name.clone().unwrap_or_else(|| "box".to_string());
            let chain = crate::scene::type_chain(self.sheet, &tname).map(|x| x.1).unwrap_or_default();
            let mut n = crate::scene::Node::new(crate::types::Prim::Block, chain, ns.span);
            n.classes = ns.classes.clone();
            n.id = ns.id.clone();
            if let Some(s) = &ns.style {
                n.inline = s.clone();
            }
            let (_, props) = crate::compile::cascade(self.sheet, &n);
            let lay = crate::compile::get(&props, "layout").and_then(crate::style::ident_of).unwrap_or("flow").to_string();
            self.stmts(ch, &lay)?;
        }
        Ok(())
    }
}

fn d_family(d: &Diag) -> &'static str {
    match d.family.as_str() {
        "invalid-color" => "invalid-color",
        "color-component-out-of-range" => "color-component-out-of-range",
        _ => "resolve",
    }
}

// Every type name some node's chain reaches.
fn used_types(doc: &Doc, sheet: &SheetModel) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    fn walk(stmts: &[Stmt], sheet: &SheetModel, out: &mut Vec<String>) {
        for s in stmts {
            match s {
                Stmt::Node(ns) => node(ns, sheet, out),
                Stmt::Link(l) => {
                    for g in &l.groups {
                        for ep in g {
                            if let Endpoint::Node(ns) = ep {
                                node(ns, sheet, out);
                            }
                        }
                    }
                }
                Stmt::Text(_) => {}
            }
        }
    }
    fn node(ns: &NodeStmt, sheet: &SheetModel, out: &mut Vec<String>) {
        let tname = ns.type_name.clone().unwrap_or_else(|| "box".to_string());
        if let Some((_, chain)) = crate::scene::type_chain(sheet, &tname) {
            for c in chain {
                if !out.contains(&c) {
                    out.push(c);
                }
            }
        }
        if let Some(ch) = &ns.children {
            walk(ch, sheet, out);
        }
    }
    walk(&doc.stmts, sheet, &mut out);
    for d in &sheet.defines {
        if out.contains(&d.name) {
            if let Some(b) = &d.body {
                walk(b, sheet, &mut out);
            }
        }
    }
    // a link end naming no declared node draws a box
    fn ids(stmts: &[Stmt], out: &mut Vec<String>) {
        for s in stmts {
            match s {
                Stmt::Node(ns) => {
                    if let Some(id) = &ns.id {
                        out.push(id.clone());
                    }
                    if let Some(ch) = &ns.children {
                        ids(ch, out);
                    }
                }
                Stmt::Link(l) => {
                    for ep in l.groups.iter().flatten() {
                        if let Endpoint::Node(ns) = ep {
                            ids(&[Stmt::Node((**ns).clone())], out);
                        }
                    }
                }
                Stmt::Text(_) => {}
            }
        }
    }
    fn auto(stmts: &[Stmt], declared: &[String]) -> bool {
        stmts.iter().any(|s| match s {
            Stmt::Node(ns) => ns.children.as_ref().is_some_and(|ch| auto(ch, declared)),
            Stmt::Link(l) => l.groups.iter().flatten().any(|ep| match ep {
                Endpoint::Path(p) => p.parts.last().is_some_and(|n| !declared.contains(n)),
                Endpoint::Text(..) => true,
                Endpoint::Node(_) => false,
            }),
            Stmt::Text(_) => false,
        })
    }
    let mut declared = Vec::new();
    ids(&doc.stmts, &mut declared);
    if auto(&doc.stmts, &declared) {
        for t in ["box", "block"] {
            if !out.iter().any(|x| x == t) {
                out.push(t.to_string());
            }
        }
    }
    out
}

// A rule merged over its defaults, as the stylesheet sees it: a property
// keeps the place it first takes (a default's, else where it is first
// written) and only its last value counts.
fn merged<'b>(defaults: &[&str], decls: impl Iterator<Item = &'b Decl>) -> Vec<&'b Decl> {
    let mut order: Vec<String> = defaults.iter().map(|s| s.to_string()).collect();
    let mut last: Vec<(String, &'b Decl)> = Vec::new();
    for d in decls {
        if !order.contains(&d.name) {
            order.push(d.name.clone());
        }
        last.retain(|(k, _)| k != &d.name);
        last.push((d.name.clone(), d));
    }
    order.iter().filter_map(|k| last.iter().find(|(n, _)| n == k).map(|(_, d)| *d)).collect()
}

// The R-phase; the first failure stops. Variables resolve first; then the
// drawn types' rules in stylesheet order (each merged over the type's
// defaults); then every other rule as written; the root block last (its
// padding, gap and font-size ahead of the rest).
pub fn resolve(doc: &Doc, sheet: &SheetModel) -> Result<(), Diag> {
    let r = R { sheet };
    let used = used_types(doc, sheet);
    let Some(sh) = &doc.sheet else { return Ok(()) };
    for item in &sh.items {
        if let SheetItem::Var(d) = item {
            r.value_terms("", &d.value).map_err(|(m, fam)| Diag::error(fam, &m, d.span))?;
        }
    }
    // a type's rule resolves only when that type is drawn
    let is_type_rule = |rl: &Rule| {
        let c = &rl.selector[0];
        rl.selector.len() == 1 && c.bars && c.id.is_none() && c.classes.is_empty() && c.type_name.as_deref().is_some_and(|t| t != "-")
    };
    let slot = |t: &str| {
        let k = if crate::types::find(t).is_some() {
            t.to_string()
        } else {
            format!("@define:{:04}", sheet.defines.iter().position(|d| d.name == t).unwrap_or(0))
        };
        crate::render::slot_rank(&k)
    };
    let mut types: Vec<&String> = used.iter().collect();
    types.sort_by_key(|t| slot(t));
    for t in types {
        let mut decls: Vec<&Decl> = Vec::new();
        for item in &sh.items {
            if let SheetItem::Define(df) = item {
                if &df.name == t {
                    decls.extend(df.decls.iter());
                }
            }
        }
        for item in &sh.items {
            if let SheetItem::Rule(rl) = item {
                if is_type_rule(rl) && rl.selector[0].type_name.as_ref() == Some(t) {
                    decls.extend(rl.decls.iter());
                }
            }
        }
        let defaults: Vec<&str> = if crate::types::find(t).is_some() { crate::style::type_defaults(t).iter().map(|d| d.name.as_str()).collect() } else { Vec::new() };
        for d in merged(&defaults, decls.into_iter()) {
            r.decl(d, None)?;
        }
    }
    for item in &sh.items {
        if let SheetItem::Rule(rl) = item {
            if !is_type_rule(rl) {
                for d in &rl.decls {
                    r.decl(d, None)?;
                }
            }
        }
    }
    let root = sh.items.iter().filter_map(|it| if let SheetItem::Decl(d) = it { Some(d) } else { None });
    for d in merged(&["padding", "gap", "font-size"], root) {
        r.decl(d, None)?;
    }
    Ok(())
}

// A statement's own declarations resolve as it is built (after its classes):
// `text` names why a box is needed when the statement is bare text.
pub fn stmt_decls(sheet: &SheetModel, decls: &[Decl], text: Option<&str>) -> Result<(), Diag> {
    let r = R { sheet };
    for d in decls {
        r.decl(d, text)?;
    }
    Ok(())
}
