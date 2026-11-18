// Built-in type registry: every template lowers onto a primitive, with a
// chain of `.lini-*` classes whose defaults cascade base-first.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Prim {
    Block,
    Oval,
    Hex,
    Slant,
    Cyl,
    Diamond,
    Poly,
    Path,
    Sketch,
    Line,
    Icon,
    Image,
    Text,
}

impl Prim {
    pub fn name(self) -> &'static str {
        match self {
            Prim::Block => "block",
            Prim::Oval => "oval",
            Prim::Hex => "hex",
            Prim::Slant => "slant",
            Prim::Cyl => "cyl",
            Prim::Diamond => "diamond",
            Prim::Poly => "poly",
            Prim::Path => "path",
            Prim::Sketch => "sketch",
            Prim::Line => "line",
            Prim::Icon => "icon",
            Prim::Image => "image",
            Prim::Text => "text",
        }
    }
}

pub struct TypeDef {
    pub name: &'static str,
    pub prim: Prim,
    pub base: Option<&'static str>,
    pub defaults: &'static str,
}

macro_rules! t {
    ($n:expr, $p:ident, $b:expr, $d:expr) => {
        TypeDef { name: $n, prim: Prim::$p, base: $b, defaults: $d }
    };
}

// Registry order is the order type rules are emitted in the stylesheet.
pub static TYPES: &[TypeDef] = &[
    t!("block", Block, None, "fill: none; stroke: none; stroke-width: 2; padding: 0; gap: 36;"),
    t!("oval", Oval, None, "fill: --fill; stroke: --stroke; stroke-width: 2; padding: 20; direction: column; gap: 12;"),
    t!("hex", Hex, None, "fill: --fill; stroke: --stroke; stroke-width: 2; padding: 20; direction: column; gap: 12;"),
    t!("slant", Slant, None, "fill: --fill; stroke: --stroke; stroke-width: 2; padding: 20; direction: column; gap: 12; skew: 15;"),
    t!("cyl", Cyl, None, "fill: --fill; stroke: --stroke; stroke-width: 2; padding: 20; direction: column; gap: 12;"),
    t!("diamond", Diamond, None, "fill: --fill; stroke: --stroke; stroke-width: 2; padding: 20; direction: column; gap: 12;"),
    t!("poly", Poly, None, "fill: --fill; stroke: --stroke; stroke-width: 2;"),
    t!("path", Path, None, "fill: --fill; stroke: --stroke; stroke-width: 2;"),
    t!("sketch", Sketch, None, "fill: --fill; stroke: --stroke-dark; stroke-width: 2;"),
    t!("line", Line, None, "fill: none; stroke: --stroke; stroke-width: 2;"),
    t!("text", Text, None, ""),
    t!("icon", Icon, None, "fill: --icon-fill; stroke: --stroke; stroke-width: 2; width: 32; height: 32;"),
    t!("image", Image, None, ""),
    // templates
    t!("box", Block, Some("block"), "fill: --fill; stroke: --stroke; stroke-width: 2; padding: 20; radius: 8; direction: column; gap: 12;"),
    t!("rect", Block, Some("box"), "radius: 0;"),
    t!("group", Block, Some("block"), "stroke: --group-stroke; stroke-style: dashed; stroke-width: 1; fill: --group-fill; radius: 8; padding: 20;"),
    t!("row", Block, Some("block"), "direction: row;"),
    t!("column", Block, Some("block"), "direction: column;"),
    t!("grid", Block, Some("block"), "layout: grid;"),
    t!("caption", Block, Some("block"), "pin: top left; translate: 0 -20; color: --caption-color; font-scale: 12 15; font-weight: --caption-font-weight;"),
    t!("footnote", Block, Some("caption"), "pin: bottom; translate: 0 19; font-scale: 12 15; color: --footer-color;"),
    t!("badge", Block, Some("block"), "pin: top right; translate: 6 -6; radius: 8; padding: 2 6; shadow: 2 3 3; fill: --accent; color: --accent-text; font-size: 11; font-weight: normal;"),
    t!("table", Block, Some("group"), "layout: grid; align: stretch; justify: stretch; gap: 1; gap-fill: --stroke; padding: 0; fill: none; stroke: --stroke; stroke-width: 2; stroke-style: solid; font-size: 14; font-weight: normal; scale: 1;"),
    t!("cell", Block, Some("block"), "padding: 4 8;"),
    t!("header", Block, Some("cell"), "fill: --header-fill; font-weight: semibold;"),
    t!("entity", Block, Some("table"), "columns: auto, auto;"),
    t!("sign", Icon, Some("icon"), "width: 64; height: 64; padding: 4; stroke-width: 2; fit: contain;"),
    t!("note", Block, Some("block"), "fill: --fill; stroke: --stroke; padding: 20; scale: 1;"),
    t!("topic", Block, Some("block"), "fill: --fill; stroke: --stroke; stroke-width: 2; radius: 8; padding: 8 14; direction: column; gap: 12;"),
    t!("mindmap", Block, Some("topic"), "max-width: 160; font-size: 17; font-weight: semibold;"),
    t!("chart", Block, Some("block"), "layout: chart; gap: 15;"),
    t!("bars", Block, Some("block"), "radius: 2; stroke: auto;"),
    t!("area", Block, Some("block"), ""),
    t!("dots", Block, Some("block"), ""),
    t!("bubble", Block, Some("block"), ""),
    t!("band", Block, Some("block"), ""),
    t!("mark", Block, Some("block"), "marker: dot;"),
    t!("axis", Block, Some("block"), ""),
    t!("pie", Block, Some("block"), "layout: pie; gap: 15;"),
    t!("slice", Block, Some("block"), "stroke: auto;"),
    t!("sequence", Block, Some("block"), "layout: sequence; gap: 32 32;"),
    t!("loop", Block, Some("block"), "fill: none; stroke: --group-stroke; stroke-style: dashed; stroke-width: 1; radius: 4; padding: 24; font-size: 12;"),
    t!("alt", Block, Some("block"), "fill: none; stroke: --group-stroke; stroke-style: dashed; stroke-width: 1; radius: 4; padding: 24; font-size: 12;"),
    t!("opt", Block, Some("block"), "fill: none; stroke: --group-stroke; stroke-style: dashed; stroke-width: 1; radius: 4; padding: 24; font-size: 12;"),
    t!("else", Block, Some("block"), "fill: none; stroke: --group-stroke; stroke-style: dashed; stroke-width: 1; font-size: 12;"),
    t!("stack", Block, Some("block"), "layout: stack; padding: 0;"),
    t!("drawing", Block, Some("block"), "layout: drawing; padding: 0;"),
    t!("floorplan", Block, Some("drawing"), "layout: floorplan;"),
    t!("hole", Oval, Some("oval"), "fill: --bg; stroke: --stroke-dark;"),
    t!("hidden", Sketch, Some("sketch"), "stroke-style: dashed; stroke: --stroke-dark; stroke-width: 1; fill: none;"),
    t!("centerline", Line, Some("line"), "stroke-style: center; stroke: --stroke-light; stroke-width: 1; fill: none;"),
    t!("pitch-circle", Oval, Some("oval"), "stroke-style: center; stroke: --stroke-light; stroke-width: 1; fill: none;"),
    t!("plane", Line, Some("line"), "stroke-style: center; stroke: --stroke-light; stroke-width: 1; fill: none;"),
    t!("magnifier", Oval, Some("oval"), "stroke: --stroke-light; stroke-width: 1; fill: none;"),
    t!("breakline", Line, Some("line"), "stroke: --stroke-light; stroke-width: 1; fill: none;"),
    t!("shoulder", Line, Some("line"), "stroke: --stroke-dark;"),
    t!("threadline", Line, Some("line"), "stroke: --stroke-light; stroke-width: 1; fill: none;"),
    t!("feature-control", Block, Some("block"), "stroke: --stroke-dark; stroke-width: 1; fill: --bg; font-size: 12; scale: 1;"),
    t!("datum", Block, Some("block"), "stroke: --stroke-dark; stroke-width: 1; fill: --bg; font-size: 12; scale: 1;"),
    t!("surface-finish", Block, Some("block"), "symbol: basic; stroke: --stroke-dark; stroke-width: 1; fill: none; font-size: 12; scale: 1;"),
    t!("balloon", Oval, Some("oval"), "width: 16; fill: --fill; stroke: --stroke; font-size: 11; scale: 1;"),
    t!("page", Block, Some("block"), "fill: --bg; stroke-width: 0; width: 210; height: 297;"),
    t!("title-block", Block, Some("table"), "font-size: 14; font-weight: semibold; stroke-width: 1; radius: 0;"),
    t!("frame", Block, Some("rect"), "fill: none; stroke: --stroke; stroke-width: 2;"),
    t!("zone", Block, Some("block"), "font-size: 11; color: --stroke-light;"),
    t!("tick", Line, Some("line"), "stroke: --stroke; stroke-width: 1; fill: none;"),
    t!("field", Block, Some("block"), "font-size: 12; font-weight: normal; color: --footer-color;"),
    t!("wall", Sketch, Some("sketch"), "fill: --stroke-dark; stroke: none;"),
    t!("partition", Sketch, Some("wall"), ""),
    t!("door", Block, Some("block"), ""),
    t!("window", Block, Some("block"), ""),
    t!("stairs", Block, Some("block"), "stroke: --stroke-dark; stroke-width: 1; fill: --bg;"),
    t!("bed", Block, Some("block"), "stroke: --stroke-dark; stroke-width: 1; fill: --bg;"),
    t!("sofa", Block, Some("block"), "stroke: --stroke-dark; stroke-width: 1; fill: --bg;"),
    t!("dining", Block, Some("block"), "stroke: --stroke-dark; stroke-width: 1; fill: --bg;"),
    t!("appliance", Block, Some("block"), "stroke: --stroke-dark; stroke-width: 1; fill: --bg;"),
    t!("bath", Block, Some("block"), "stroke: --stroke-dark; stroke-width: 1; fill: --bg;"),
    t!("schematic", Block, Some("block"), "layout: schematic; gap: 100; clearance: 10; fill: --sheet;"),
    t!("component", Block, Some("block"), "fill: --component-fill; stroke: --component-stroke; stroke-width: 1.5; radius: 0; padding: 8; prefix: \"U\";"),
    t!("pin", Block, Some("block"), "height: 20; padding: 0; font-size: 11; gap: 0;"),
    t!("space", Block, Some("block"), "width: 20; height: 20;"),
    t!("label", Block, Some("block"), "shape: plain; font-size: 11; color: --label-ink; gap: 4;"),
    // further built-ins (defaults as `lini desugar` reveals them)
    t!("footer", Block, Some("cell"), "color: --footer-color;"),
    t!("control", Block, Some("block"), ""),
    t!("shoulder", Line, Some("line"), "stroke: --stroke-dark;"),
    t!("junction", Oval, Some("oval"), "fill: --wire; stroke: none; width: 8;"),
    t!("gnd", Block, Some("label"), "symbol: gnd;"),
    t!("nc", Block, Some("label"), "symbol: nc;"),
    t!("opamp", Block, Some("component"), "fill: none; stroke: none; prefix: \"U\";"),
    t!("J", Block, Some("component"), "prefix: \"J\";"),
    t!("R", Block, Some("block"), ""),
    t!("C", Block, Some("block"), ""),
    t!("L", Block, Some("block"), ""),
    t!("D", Block, Some("block"), ""),
    t!("LED", Block, Some("block"), ""),
    t!("Q", Block, Some("block"), ""),
    t!("Y", Block, Some("block"), ""),
    t!("F", Block, Some("block"), ""),
    t!("FB", Block, Some("block"), ""),
    t!("SW", Block, Some("block"), ""),
    t!("BT", Block, Some("block"), ""),
    t!("V", Block, Some("block"), ""),
    t!("I", Block, Some("block"), ""),
    t!("M", Block, Some("block"), ""),
    t!("BZ", Block, Some("block"), ""),
    t!("TP", Block, Some("block"), ""),
    // drawing / floorplan annotation lines and the sheet caption
    t!("window-sill", Line, Some("line"), "stroke: --stroke-light; stroke-width: 1; fill: none;"),
    t!("stair-tread", Line, Some("line"), "stroke: --stroke-light; stroke-width: 1; fill: none;"),
    t!("stair-arrow", Line, Some("line"), "stroke: --stroke-light; stroke-width: 1; fill: none;"),
    t!("projection", Line, Some("line"), "stroke: --stroke-light; stroke-width: 1; fill: none;"),
    t!("door-leaf", Line, Some("line"), "stroke: --stroke-light; stroke-width: 1; fill: none;"),
    t!("door-swing", Line, Some("line"), "stroke: --stroke-light; stroke-width: 1; fill: none;"),
    t!("halo", Line, Some("line"), ""),
    t!("sheet-caption", Block, Some("caption"), "translate: 10 10; font-scale: 16 15; font-weight: semibold;"),
];

pub fn find(name: &str) -> Option<&'static TypeDef> {
    TYPES.iter().find(|t| t.name == name)
}

pub fn order_of(name: &str) -> usize {
    TYPES.iter().position(|t| t.name == name).unwrap_or(usize::MAX)
}
