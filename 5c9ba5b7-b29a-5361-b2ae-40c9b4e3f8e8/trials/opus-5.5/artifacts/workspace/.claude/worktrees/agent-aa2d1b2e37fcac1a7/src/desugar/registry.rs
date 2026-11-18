// The order `lini desugar` writes the `.lini-*` rules in, and the default
// rule text of the internal classes the lowering introduces. Types read their
// defaults (and chains) from `types.rs`.

// built-in types and chrome classes, before the user's defines
pub static BUILTIN_ORDER: &[&str] = &[
    "block", "oval", "hex", "slant", "cyl", "diamond", "poly", "path", "line", "icon", "image", "sketch", "box", "rect",
    "group", "caption", "sheet-caption", "footnote", "badge", "row", "column", "grid", "table", "cell", "header", "footer", "entity",
    "sign", "chart", "pie", "area", "bars", "dots", "bubble", "slice", "axis", "band", "mark", "sequence", "loop", "opt",
    "alt", "else", "note", "balloon", "topic", "mindmap", "drawing", "hole", "centerline", "pitch-circle", "breakline",
    "hidden", "shoulder", "threadline", "surface-finish", "feature-control", "control", "datum", "plane",
    "magnifier", "page", "title-block", "field", "frame", "zone", "tick", "stack", "floorplan", "wall", "partition",
    "door", "door-leaf", "door-swing", "window", "window-sill", "stair-tread", "stair-arrow", "bed", "sofa", "dining",
    "bath", "appliance", "stairs", "schematic", "component", "pin", "space",
    "label", "junction", "J", "opamp", "gnd", "nc", "R", "C", "L", "D", "LED", "Q", "Y", "F", "FB", "SW", "BT", "V", "I",
    "M", "BZ", "TP",
];

// utility classes the lowering adds, after the user's defines
pub static UTILITY_ORDER: &[&str] = &[
    "align-start",
    "align-end",
    "justify-start",
    "justify-end",
    "sch-line",
    "sch-solid",
    "sch-tag-line",
    "pin-stub",
    "pin-number",
    "ref",
    "part-value",
    "tag-outline",
    "tag-round",
    "tag-flag-left",
    "tag-flag-right",
    "tag-flag-both",
    "net-run",
    "net-run-turned",
];

// default rule text of classes that are not types
pub fn class_defaults(name: &str) -> Option<&'static str> {
    Some(match name {
        "breakline" => "stroke: --stroke-light; stroke-width: 1; fill: none;",
        "threadline" => "stroke: --stroke-light; stroke-width: 1; fill: none;",
        "door-leaf" => "stroke: --stroke-light; stroke-width: 1; fill: none;",
        "door-swing" => "stroke: --stroke-light; stroke-width: 1; fill: none;",
        "window-sill" => "stroke: --stroke-light; stroke-width: 1; fill: none;",
        "stair-tread" => "stroke: --stroke-light; stroke-width: 1; fill: none;",
        "stair-arrow" => "stroke: --stroke-light; stroke-width: 1; fill: none;",
        "align-start" => "align: start;",
        "align-end" => "align: end;",
        "justify-start" => "justify: start;",
        "justify-end" => "justify: end;",
        "sch-line" => "fill: none; stroke: --component-stroke; stroke-width: 1.5;",
        "sch-solid" => "fill: --component-stroke; stroke: none;",
        "sch-tag-line" => "fill: none; stroke: --label-ink; stroke-width: 1.5;",
        "pin-stub" => "fill: none; stroke: --component-stroke; stroke-width: 1.5;",
        "pin-number" => "color: --pin-number; font-size: 10;",
        "ref" => "font-size: 12; font-weight: semibold;",
        "part-value" => "font-size: 12;",
        "net-run" => "width: 40; padding: 0 4;",
        "net-run-turned" => "height: 40; padding: 4 0;",
        "tag-outline" => "stroke: --label-ink; stroke-width: 1.5; padding: 2 6;",
        "tag-round" => "radius: 99;",
        "tag-flag-left" => "padding: 2 6 2 14;",
        "tag-flag-right" => "padding: 2 14 2 6;",
        "tag-flag-both" => "padding: 2 14;",
        "sheet-caption" => "translate: 10 10; font-scale: 16 15; font-weight: semibold;",
        _ => return None,
    })
}

// the type a chrome class lowers onto
pub fn class_base(name: &str) -> Option<&'static str> {
    Some(match name {
        "breakline" | "threadline" | "door-leaf" | "door-swing" | "window-sill" | "stair-tread" | "stair-arrow"
        | "pin-stub" => "line",
        "pin-number" | "ref" | "part-value" => "block",
        "sch-line" | "sch-solid" | "sch-tag-line" => "path",
        "sheet-caption" => "caption",
        _ => return None,
    })
}
