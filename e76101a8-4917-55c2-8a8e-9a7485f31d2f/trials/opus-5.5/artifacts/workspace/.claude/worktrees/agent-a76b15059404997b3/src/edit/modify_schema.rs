//! The fields `modify` takes of each category, in the order the original's element structs hold
//! them (the order a project file keeps them in, and its `unknown field` errors list them in):
//! each field's type, when the file leaves it out, and what it names.

use super::modify_de::*;

/// When the file leaves a field out.
#[derive(Clone, Copy, Debug)]
pub enum Skip {
    Never,
    /// None.
    Null,
    /// 0 (or -0).
    Zero,
    False,
    True,
    /// An empty list, map or text.
    Empty,
    /// This number.
    Eq(f64),
    /// This variant.
    Str(&'static str),
    /// [0, 0].
    ZeroP2,
    /// When this says so.
    Fn(fn(&crate::json::Value) -> bool),
}

/// What an element reference must be, and what the original says when it isn't.
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Rule {
    /// Anything (its own rules are other parts' business).
    Any,
    Level,
    HostWall,
    /// A plan, a section, an elevation or a sheet (detail lines, notes, regions, groups).
    View,
    /// A roof or a floor.
    Attach,
    TagHost,
    /// Any element (a spot elevation's host).
    Element,
    /// A rebar's host.
    Host,
    /// A plan of the element's level.
    DimView,
    TagView,
    Sheet,
    ViewportView,
    View3d,
    CadView,
    Parent,
    Join,
}

/// What a field names, for the checks after the change and the way the file keeps it.
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Role {
    Plain,
    /// The element's type, by name (or GUID).
    Type,
    /// A family, by name.
    Family,
    LineStyle,
    /// A filled region's boundary style: a line style, or none.
    RegionStyle,
    TextType,
    DimType,
    RegionType,
    Group,
    Cloud,
    Cad,
    /// `level`: by name, id or GUID.
    Level,
    TopLevel,
    Ref(Rule),
    Params,
    /// A view's graphics: its template, phase and phase filter by name.
    Graphics,
}

pub struct Field {
    pub name: &'static str,
    pub t: T,
    pub skip: Skip,
    pub role: Role,
}

const fn f(name: &'static str, t: T, skip: Skip, role: Role) -> Field {
    Field { name, t, skip, role }
}
const fn p(name: &'static str, t: T, skip: Skip) -> Field {
    Field { name, t, skip, role: Role::Plain }
}

const fn fd(name: &'static str, t: T, required: bool) -> Fd {
    Fd { name, t, required, default: None, keep_null: false, skip_if: None }
}
/// A field the file always holds: this when it's missing.
const fn fdd(name: &'static str, t: T, default: fn() -> Value) -> Fd {
    Fd { name, t, required: false, default: Some(default), keep_null: false, skip_if: None }
}
/// An optional field the file always holds, null when it's none.
const fn fdn(name: &'static str, t: T) -> Fd {
    Fd { name, t, required: false, default: Some(null), keep_null: true, skip_if: None }
}
fn null() -> Value {
    Value::Null
}
fn zero() -> Value {
    Value::f(0.0)
}
fn cut_default() -> Value {
    Value::f(1200.0)
}
fn empty_list() -> Value {
    Value::Arr(Vec::new())
}
fn yes() -> Value {
    Value::Bool(true)
}
/// A field left out when this says so of its value.
const fn fds(name: &'static str, t: T, skip_if: fn(&Value) -> bool) -> Fd {
    Fd { name, t, required: false, default: None, keep_null: false, skip_if: Some(skip_if) }
}
fn is_false(v: &Value) -> bool {
    v.as_bool() == Some(false)
}
fn is_zero(v: &Value) -> bool {
    v.as_f64() == Some(0.0)
}

/// A 3D view's display options left out where they're as a view has them by default.
pub fn default_display(v: &Value) -> bool {
    match v {
        Value::Obj(m) => {
            m.get("edges").and_then(|x| x.as_bool()).unwrap_or(true)
                && m.get("silhouette").and_then(|x| x.as_f64()).unwrap_or(0.0) == 0.0
                && !m.get("ambient_shadows").and_then(|x| x.as_bool()).unwrap_or(false)
        }
        Value::Null => true,
        _ => false,
    }
}

use crate::json::Value;

pub static VIEW_RANGE: Sd = Sd {
    name: "ViewRange",
    fields: &[fdn("top", OPT_F), fdd("cut", F, cut_default), fdd("bottom", F, zero), fdd("depth", F, zero)],
    deny: true,
};
pub static BACKGROUND_GRID: Sd = Sd { name: "BackgroundGrid", fields: &[], deny: false };
pub static APPLIED: Sd = Sd { name: "AppliedJson", fields: &[], deny: false };
pub static LINEWORK: Sd = Sd { name: "Linework", fields: &[], deny: false };
pub const DETAIL: &[&str] = &["coarse", "medium", "fine"];
pub const STYLE: &[&str] = &["shaded", "hidden_line", "wireframe"];
pub static GRAPHICS: Sd = Sd {
    name: "Graphics",
    fields: &[
        fd("template", OPT_STR, false),
        fd("categories", T::Opt(&T::Map), false),
        fd("filters", T::Opt(&T::Vec(&T::Struct(&APPLIED))), false),
        fd("elements", T::Opt(&T::Map), false),
        fd("phase", OPT_STR, false),
        fd("phase_filter", OPT_STR, false),
        fd("options", T::Opt(&T::Map), false),
        fd("scale", OPT_F, false),
        fd("detail", T::Opt(&T::Enum(DETAIL)), false),
        fd("style", T::Opt(&T::Enum(STYLE)), false),
        fd("background_grid", T::Opt(&T::Struct(&BACKGROUND_GRID)), false),
        fd("linework", T::Opt(&T::Vec(&T::Struct(&LINEWORK))), false),
        fd("layers", T::Opt(&T::Map), false),
    ],
    deny: true,
};
pub static REGION: Sd = Sd {
    name: "Region",
    fields: &[fd("outer", PTS, true), fdd("holes", LOOPS, empty_list)],
    deny: true,
};
pub static KEPT: Sd = Sd {
    name: "Kept",
    fields: &[fd("centre", T::Opt(&T::Struct(&REGION)), false), fd("finish", T::Opt(&T::Struct(&REGION)), false)],
    deny: true,
};
pub static SKETCH_LINE: Sd = Sd {
    name: "RawSketchLine",
    fields: &[
        fd("id", T::Opt(&T::U64), false),
        fd("guid", T::Opt(&T::Any), false),
        fd("style", OPT_STR, false),
        fd("invisible", T::Opt(&T::Bool), false),
        fd("slope", OPT_F, false),
        fd("start", OPT_P2, false),
        fd("end", OPT_P2, false),
        fd("through", OPT_P2, false),
        fd("arc", OPT_F, false),
        fd("points", OPT_PTS, false),
        fd("arcs", OPT_VEC_F, false),
        fd("closed", T::Opt(&T::Bool), false),
        fd("centre", OPT_P2, false),
        fd("radius", OPT_F, false),
        fd("radii", OPT_F2, false),
        fd("angle", OPT_F, false),
        fd("span", OPT_F2, false),
        fd("control", OPT_PTS, false),
        fd("knots", OPT_VEC_F, false),
        fd("fit", OPT_PTS, false),
        fd("start_tangent", OPT_P2, false),
        fd("end_tangent", OPT_P2, false),
    ],
    deny: true,
};
pub static SHAPE_POINT: Sd = Sd { name: "ShapePoint", fields: &[], deny: false };
pub static SPLIT_LINE: Sd = Sd { name: "SplitLine", fields: &[], deny: false };
pub static SHAPE: Sd = Sd {
    name: "Shape",
    fields: &[
        fd("points", T::Opt(&T::Vec(&T::Struct(&SHAPE_POINT))), false),
        fd("lines", T::Opt(&T::Vec(&T::Struct(&SPLIT_LINE))), false),
    ],
    deny: true,
};
pub static EXTRUSION: Sd = Sd {
    name: "Extrusion",
    fields: &[fd("line", SEG, true), fd("profile", PTS, false), fd("from", F, false), fd("to", F, false)],
    deny: true,
};
pub static LANDING: Sd = Sd { name: "Landing", fields: &[fd("at", F, true), fdd("turn", F, zero)], deny: true };
pub const FACES: &[&str] = &["center", "centre", "left", "right", "start", "end"];
pub static REFERENCE: Sd = Sd {
    name: "Reference",
    fields: &[fd("id", T::Ref, true), fd("face", T::Opt(&T::Enum(FACES)), false), fd("point", OPT_P2, false)],
    deny: true,
};
pub static RUN: Sd = Sd {
    name: "Run",
    fields: &[
        fd("from", T::Usize, true),
        fd("to", T::Usize, true),
        fd("bold", T::Opt(&T::Bool), false),
        fd("italic", T::Opt(&T::Bool), false),
        fd("underline", T::Opt(&T::Bool), false),
    ],
    deny: true,
};
pub static SEGMENT_TEXT: Sd = Sd {
    name: "SegmentText",
    fields: &[
        fd("segment", T::Usize, true),
        fd("prefix", OPT_STR, false),
        fd("suffix", OPT_STR, false),
        fd("above", OPT_STR, false),
        fd("below", OPT_STR, false),
        fd("replace", OPT_STR, false),
    ],
    deny: true,
};
pub static LOCK: Sd = Sd { name: "Lock", fields: &[fd("segment", T::Usize, true), fd("length", F, true)], deny: true };
pub static SECTION_BOX: Sd = Sd {
    name: "SectionBox",
    fields: &[fd("min", P3, true), fd("max", P3, true), fdd("on", T::Bool, yes)],
    deny: true,
};
pub static PERSPECTIVE: Sd = Sd { name: "Perspective", fields: &[fd("lens", F, true), fdd("on", T::Bool, yes)], deny: true };
pub static CAMERA: Sd = Sd { name: "ViewCamera", fields: &[fd("eye", P3, true), fd("target", P3, true)], deny: true };
pub static DISPLAY: Sd = Sd {
    name: "DisplayOptions",
    fields: &[fdd("edges", T::Bool, yes), fds("silhouette", T::U32, is_zero), fds("ambient_shadows", T::Bool, is_false)],
    deny: true,
};
pub static WORK_PLANE: Sd = Sd {
    name: "WorkPlane",
    fields: &[
        fd("level", OPT_REF, false),
        fd("offset", F, false),
        fd("points", T::Opt(&T::Arr(3, &P3)), false),
        fd("surface", T::Any, false),
    ],
    deny: true,
};
pub static REF3: Sd = Sd { name: "Ref3", fields: &[fd("at", P3, true)], deny: false };
pub static SCHED_FIELD: Sd = Sd { name: "Field", fields: &[fd("name", T::Str, true)], deny: false };
pub static SCHED_FILTER: Sd = Sd { name: "Filter", fields: &[fd("field", T::Str, true)], deny: false };
pub static SCHED_SORT: Sd = Sd { name: "Sort", fields: &[fd("field", T::Str, true)], deny: false };

pub const LOCATIONS: &[&str] = &[
    "center",
    "centre",
    "core-center",
    "core-centre",
    "exterior-finish",
    "interior-finish",
    "exterior-core",
    "interior-core",
];
pub const JUSTIFY: &[&str] = &["top", "center", "centre", "bottom"];
pub const DIM_KINDS: &[&str] = &["aligned", "linear", "angular", "radial", "diameter", "arc_length"];
pub const ORIENT: &[&str] = &["horizontal", "vertical"];
pub const SIDES: &[&str] = &["left", "right"];
pub const COLORS: &[&str] = &["preserve", "invert", "black"];

use Role as R;
use Skip as S;

static LEVEL: &[Field] = &[
    p("name", T::Str, S::Never),
    p("elevation", F, S::Never),
    p("view_range", T::Struct(&VIEW_RANGE), S::Never),
    p("crop", OPT_SEG, S::Null),
    p("extent", OPT_SEG, S::Null),
    f("graphics", T::Struct(&GRAPHICS), S::Empty, R::Graphics),
    p("section_box", T::Bool, S::False),
    p("computation_height", F, S::Eq(1200.0)),
];

static PLANVIEW: &[Field] = &[
    f("level", T::Ref, S::Never, R::Level),
    p("name", T::Str, S::Never),
    p("view_range", T::Struct(&VIEW_RANGE), S::Never),
    p("crop", OPT_SEG, S::Null),
    f("graphics", T::Struct(&GRAPHICS), S::Empty, R::Graphics),
    f("parent", OPT_REF, S::Null, R::Ref(Rule::Parent)),
    p("section_box", T::Bool, S::False),
];

static WALL: &[Field] = &[
    f("type", T::Str, S::Never, R::Type),
    f("level", T::Ref, S::Never, R::Level),
    p("start", P2, S::Never),
    p("end", P2, S::Never),
    f("top_level", OPT_REF, S::Never, R::TopLevel),
    p("height", F, S::Never),
    p("base_offset", F, S::Never),
    p("top_offset", F, S::Zero),
    p("arc", F, S::Zero),
    p("location", T::Enum(LOCATIONS), S::Str("centre")),
    f("attach_top", OPT_REF, S::Null, R::Ref(Rule::Attach)),
    f("attach_base", OPT_REF, S::Null, R::Ref(Rule::Attach)),
    p("room_bounding", T::Bool, S::True),
    f("params", T::Map, S::Empty, R::Params),
];

static OPENING: &[Field] = &[
    f("type", T::Str, S::Never, R::Type),
    f("family", OPT_STR, S::Null, R::Family),
    f("host", T::Ref, S::Never, R::Ref(Rule::HostWall)),
    p("offset", F, S::Never),
    p("sill", F, S::Never),
    p("mark", T::Str, S::Never),
    p("flip_facing", T::Bool, S::Never),
    p("flip_hand", T::Bool, S::Never),
    f("params", T::Map, S::Empty, R::Params),
];

static ROOM: &[Field] = &[
    f("level", T::Ref, S::Never, R::Level),
    p("point", P2, S::Never),
    p("name", T::Str, S::Never),
    p("number", T::Str, S::Never),
    p("colour", OPT_U8X3, S::Null),
    f("params", T::Map, S::Empty, R::Params),
    p("base_offset", F, S::Zero),
    f("top_level", OPT_REF, S::Null, R::TopLevel),
    p("limit_offset", F, S::Eq(2500.0)),
    p("frozen", T::Bool, S::False),
    p("kept", T::Opt(&T::Struct(&KEPT)), S::Null),
];

static FLOOR: &[Field] = &[
    f("type", T::Str, S::Never, R::Type),
    f("level", T::Ref, S::Never, R::Level),
    p("boundary", PTS, S::Never),
    p("openings", LOOPS, S::Empty),
    p("offset", F, S::Zero),
    p("slope", F, S::Zero),
    p("arrow", OPT_SEG, S::Null),
    p("structural", T::Bool, S::False),
    p("pattern_origin", P2, S::ZeroP2),
    p("pattern_angle", F, S::Zero),
    p("sketch", T::Vec(&T::Struct(&SKETCH_LINE)), S::Empty),
    p("shape", T::Struct(&SHAPE), S::Empty),
    f("params", T::Map, S::Empty, R::Params),
];

static CEILING: &[Field] = &[
    f("type", T::Str, S::Never, R::Type),
    f("level", T::Ref, S::Never, R::Level),
    p("boundary", PTS, S::Never),
    p("openings", LOOPS, S::Empty),
    p("offset", F, S::Never),
    p("sketch", T::Vec(&T::Struct(&SKETCH_LINE)), S::Empty),
    f("params", T::Map, S::Empty, R::Params),
];

static ROOF: &[Field] = &[
    f("type", T::Str, S::Never, R::Type),
    f("level", T::Ref, S::Never, R::Level),
    p("boundary", PTS, S::Never),
    p("courtyards", LOOPS, S::Empty),
    p("slope", F, S::Never),
    p("slopes", VEC_F, S::Empty),
    p("overhang", F, S::Never),
    p("gable", T::Bool, S::False),
    p("gables", VEC_USIZE, S::Empty),
    p("offset", F, S::Never),
    p("openings", LOOPS, S::Empty),
    f("join", OPT_REF, S::Null, R::Ref(Rule::Join)),
    p("extrusion", T::Opt(&T::Struct(&EXTRUSION)), S::Null),
    p("sketch", T::Vec(&T::Struct(&SKETCH_LINE)), S::Empty),
    p("shape", T::Struct(&SHAPE), S::Empty),
    f("params", T::Map, S::Empty, R::Params),
];

static COLUMN: &[Field] = &[
    f("type", T::Str, S::Never, R::Type),
    f("level", T::Ref, S::Never, R::Level),
    p("at", P2, S::Never),
    p("angle", F, S::Never),
    f("top_level", OPT_REF, S::Never, R::TopLevel),
    p("height", F, S::Never),
    p("base_offset", F, S::Never),
    f("params", T::Map, S::Empty, R::Params),
    p("room_bounding", T::Bool, S::True),
];

static RUN_FIELDS: &[Field] = &[
    f("type", T::Str, S::Never, R::Type),
    f("level", T::Ref, S::Never, R::Level),
    p("start", P2, S::Never),
    p("end", P2, S::Never),
    p("offset", F, S::Never),
    p("end_offset", OPT_F, S::Null),
    p("justify", T::Enum(JUSTIFY), S::Never),
    p("system", T::Str, S::Empty),
    f("params", T::Map, S::Empty, R::Params),
];

static STAIR: &[Field] = &[
    f("level", T::Ref, S::Never, R::Level),
    f("top_level", OPT_REF, S::Never, R::TopLevel),
    p("height", F, S::Never),
    p("start", P2, S::Never),
    p("angle", F, S::Never),
    p("width", F, S::Never),
    p("riser", F, S::Never),
    p("tread", F, S::Never),
    p("landings", T::Vec(&T::Struct(&LANDING)), S::Empty),
    f("params", T::Map, S::Empty, R::Params),
];

static RAMP: &[Field] = &[
    f("level", T::Ref, S::Never, R::Level),
    f("top_level", OPT_REF, S::Never, R::TopLevel),
    p("height", F, S::Never),
    p("start", P2, S::Never),
    p("angle", F, S::Never),
    p("width", F, S::Never),
    p("slope", F, S::Never),
    p("landings", T::Vec(&T::Struct(&LANDING)), S::Empty),
    f("params", T::Map, S::Empty, R::Params),
];

static RAILING: &[Field] = &[
    f("type", T::Str, S::Never, R::Type),
    f("level", T::Ref, S::Never, R::Level),
    p("path", PTS, S::Never),
    p("base_offset", F, S::Zero),
    f("host", OPT_REF, S::Null, R::Ref(Rule::Any)),
    p("side", T::Opt(&T::Enum(SIDES)), S::Null),
    f("params", T::Map, S::Empty, R::Params),
];

static SHAFT: &[Field] = &[
    f("level", T::Ref, S::Never, R::Level),
    p("boundary", PTS, S::Never),
    f("top_level", OPT_REF, S::Never, R::TopLevel),
    p("height", F, S::Never),
    p("base_offset", F, S::Never),
    p("sketch", T::Vec(&T::Struct(&SKETCH_LINE)), S::Empty),
];

static MASS: &[Field] = &[
    p("name", T::Str, S::Never),
    f("level", T::Ref, S::Never, R::Level),
    p("boundary", PTS, S::Never),
    f("top_level", OPT_REF, S::Never, R::TopLevel),
    p("height", F, S::Never),
    p("base_offset", F, S::Never),
    p("top", OPT_PTS, S::Null),
    f("params", T::Map, S::Empty, R::Params),
];

static ROOM_SEPARATOR: &[Field] = &[
    f("level", T::Ref, S::Never, R::Level),
    p("start", P2, S::Never),
    p("end", P2, S::Never),
];

static GRID: &[Field] = &[p("name", T::Str, S::Never), p("start", P2, S::Never), p("end", P2, S::Never)];

static COMPONENT: &[Field] = &[
    f("family", T::Str, S::Never, R::Family),
    f("type", T::Str, S::Never, R::Type),
    f("level", T::Ref, S::Never, R::Level),
    p("at", P2, S::Never),
    p("angle", F, S::Never),
    p("offset", F, S::Never),
    p("mirrored", T::Bool, S::False),
    f("params", T::Map, S::Empty, R::Params),
];

static LINE: &[Field] = &[
    f("view", T::Ref, S::Never, R::Ref(Rule::View)),
    f("style", T::Str, S::Never, R::LineStyle),
    p("insulation", OPT_F, S::Null),
    p("centre_mark", T::Bool, S::False),
    p("cloud", OPT_F, S::Null),
    p("revision", OPT_STR, S::Null),
    p("start", OPT_P2, S::Null),
    p("end", OPT_P2, S::Null),
    p("through", OPT_P2, S::Null),
    p("arc", OPT_F, S::Null),
    p("points", OPT_PTS, S::Null),
    p("arcs", OPT_VEC_F, S::Null),
    p("closed", T::Bool, S::False),
    p("centre", OPT_P2, S::Null),
    p("radius", OPT_F, S::Null),
    p("radii", OPT_F2, S::Null),
    p("angle", OPT_F, S::Null),
    p("span", OPT_F2, S::Null),
    p("control", OPT_PTS, S::Null),
    p("knots", OPT_VEC_F, S::Null),
    p("fit", OPT_PTS, S::Null),
    p("start_tangent", OPT_P2, S::Null),
    p("end_tangent", OPT_P2, S::Null),
];

static TEXT: &[Field] = &[
    f("view", T::Ref, S::Never, R::Ref(Rule::View)),
    p("at", P2, S::Never),
    p("text", T::Str, S::Never),
    f("type", T::Str, S::Never, R::TextType),
    p("size", OPT_F, S::Null),
    p("angle", F, S::Never),
    p("leader", OPT_P2, S::Null),
    p("override_format", T::Bool, S::False),
    p("runs", T::Vec(&T::Struct(&RUN)), S::Empty),
];

static DIMENSION: &[Field] = &[
    f("level", T::Ref, S::Never, R::Level),
    f("view", OPT_REF, S::Null, R::Ref(Rule::DimView)),
    p("kind", T::Enum(DIM_KINDS), S::Never),
    p("orient", T::Opt(&T::Enum(ORIENT)), S::Null),
    p("refs", T::Vec(&T::Struct(&REFERENCE)), S::Never),
    p("at", P2, S::Never),
    f("type", T::Str, S::Never, R::DimType),
    p("prefix", T::Str, S::Empty),
    p("suffix", T::Str, S::Empty),
    p("above", T::Str, S::Empty),
    p("below", T::Str, S::Empty),
    p("replace", T::Str, S::Empty),
    p("equality", T::Bool, S::False),
    p("texts", T::Vec(&T::Struct(&SEGMENT_TEXT)), S::Empty),
    p("equal", T::Bool, S::False),
    p("locked", T::Vec(&T::Struct(&LOCK)), S::Empty),
    p("alignment", T::Bool, S::False),
];

static TAG: &[Field] = &[
    f("host", T::Ref, S::Never, R::Ref(Rule::TagHost)),
    f("view", OPT_REF, S::Null, R::Ref(Rule::TagView)),
    p("offset", P2, S::Never),
    p("leader", T::Bool, S::Never),
    p("label", OPT_STR, S::Null),
];

static SPOT: &[Field] = &[
    f("view", T::Ref, S::Never, R::Ref(Rule::View)),
    p("at", P2, S::Never),
    f("host", OPT_REF, S::Null, R::Ref(Rule::Element)),
    p("slope", T::Bool, S::False),
];

static SECTION: &[Field] = &[
    p("name", T::Str, S::Never),
    p("start", P2, S::Never),
    p("end", P2, S::Never),
    p("depth", OPT_F, S::Never),
    p("crop", OPT_F2, S::Null),
    f("graphics", T::Struct(&GRAPHICS), S::Empty, R::Graphics),
];

static SHEET: &[Field] = &[p("number", T::Str, S::Never), p("name", T::Str, S::Never), p("size", T::Str, S::Never)];

static VIEW3D: &[Field] = &[
    p("name", T::Str, S::Never),
    p("azimuth", F, S::Never),
    p("elevation", F, S::Never),
    f("graphics", T::Struct(&GRAPHICS), S::Empty, R::Graphics),
    p("section_box", T::Opt(&T::Struct(&SECTION_BOX)), S::Null),
    p("perspective", T::Opt(&T::Struct(&PERSPECTIVE)), S::Null),
    p("camera", T::Opt(&T::Struct(&CAMERA)), S::Null),
    p("display", T::Struct(&DISPLAY), S::Fn(default_display)),
    p("work_plane", T::Opt(&T::Struct(&WORK_PLANE)), S::Null),
];

static DETAIL_GROUP: &[Field] = &[
    f("view", T::Ref, S::Never, R::Ref(Rule::View)),
    f("type", T::Str, S::Never, R::Group),
    p("at", P2, S::Never),
    p("angle", F, S::Zero),
    p("mirrored", T::Bool, S::False),
];

static REPEATING_DETAIL: &[Field] = &[
    f("view", T::Ref, S::Never, R::Ref(Rule::View)),
    f("type", T::Str, S::Never, R::Group),
    p("start", P2, S::Never),
    p("end", P2, S::Never),
    p("spacing", F, S::Never),
    p("mirrored", T::Bool, S::False),
];

static VIEWPORT: &[Field] = &[
    f("sheet", T::Ref, S::Never, R::Ref(Rule::Sheet)),
    f("view", T::Ref, S::Never, R::Ref(Rule::ViewportView)),
    p("at", P2, S::Never),
    p("scale", F, S::Never),
];

static REGION_FIELDS: &[Field] = &[
    f("view", T::Ref, S::Never, R::Ref(Rule::View)),
    f("type", T::Str, S::Never, R::RegionType),
    f("line_style", OPT_STR, S::Null, R::RegionStyle),
    p("sketch", T::Vec(&T::Struct(&SKETCH_LINE)), S::Never),
    p("pattern_origin", P2, S::ZeroP2),
    p("pattern_angle", F, S::Zero),
];

static DIMENSION3D: &[Field] = &[
    f("view", T::Ref, S::Never, R::Ref(Rule::View3d)),
    p("refs", T::Arr(2, &T::Struct(&REF3)), S::Never),
    p("at", P3, S::Never),
    f("type", T::Str, S::Never, R::DimType),
];

static REBAR: &[Field] = &[
    f("level", T::Ref, S::Never, R::Level),
    f("host", OPT_REF, S::Null, R::Ref(Rule::Host)),
    p("path", PTS3, S::Never),
    p("diameter", F, S::Never),
    p("grade", T::Str, S::Never),
    p("layer", T::Str, S::Empty),
];

static POINT_CLOUD: &[Field] = &[
    f("cloud", T::Str, S::Never, R::Cloud),
    f("level", T::Ref, S::Never, R::Level),
    p("at", P2, S::Never),
    p("offset", F, S::Never),
    p("angle", F, S::Never),
];

static CAD_IMPORT: &[Field] = &[
    f("cad", T::Str, S::Never, R::Cad),
    f("level", T::Ref, S::Never, R::Level),
    p("at", P2, S::Never),
    p("origin", P2, S::Never),
    p("scale", F, S::Never),
    p("angle", F, S::Zero),
    f("view", OPT_REF, S::Null, R::Ref(Rule::CadView)),
    p("hidden", VEC_STR, S::Empty),
    p("colors", T::Enum(COLORS), S::Str("preserve")),
];

static SCHEDULE: &[Field] = &[
    p("name", T::Str, S::Never),
    p("of", T::Str, S::Never),
    p("categories", VEC_STR, S::Empty),
    p("fields", T::Vec(&T::Struct(&SCHED_FIELD)), S::Never),
    p("filters", T::Vec(&T::Struct(&SCHED_FILTER)), S::Empty),
    p("sort", T::Vec(&T::Struct(&SCHED_SORT)), S::Empty),
    p("grouped", T::Bool, S::False),
];

static LINK: &[Field] = &[
    p("name", T::Str, S::Never),
    p("path", T::Str, S::Never),
    p("at", P2, S::Never),
    p("angle", F, S::Zero),
];

/// The fields of a category's elements, in their order; None for a category `modify` doesn't know.
pub fn fields(cat: &str) -> Option<&'static [Field]> {
    Some(match cat {
        "level" => LEVEL,
        "planview" => PLANVIEW,
        "wall" => WALL,
        "door" | "window" => OPENING,
        "room" => ROOM,
        "floor" => FLOOR,
        "ceiling" => CEILING,
        "roof" => ROOF,
        "column" | "structuralcolumn" | "footing" => COLUMN,
        "beam" | "stripfooting" | "pipe" | "duct" | "conduit" | "cabletray" | "wire" | "downconductor"
        | "groundconductor" | "cable" => RUN_FIELDS,
        "stair" => STAIR,
        "ramp" => RAMP,
        "railing" => RAILING,
        "shaft" => SHAFT,
        "mass" => MASS,
        "roomseparator" => ROOM_SEPARATOR,
        "grid" => GRID,
        "component" => COMPONENT,
        "line" => LINE,
        "text" => TEXT,
        "dimension" => DIMENSION,
        "tag" => TAG,
        "spot" => SPOT,
        "section" | "elevation" => SECTION,
        "sheet" => SHEET,
        "view3d" => VIEW3D,
        "detailgroup" => DETAIL_GROUP,
        "repeatingdetail" => REPEATING_DETAIL,
        "viewport" => VIEWPORT,
        "region" => REGION_FIELDS,
        "dimension3d" => DIMENSION3D,
        "rebar" => REBAR,
        "pointcloud" => POINT_CLOUD,
        "cadimport" => CAD_IMPORT,
        "schedule" => SCHEDULE,
        "link" => LINK,
        _ => return None,
    })
}

/// The file's key for a category's types (`types.wall`, `types.runs.beam`…) and the library's kind.
pub fn type_section(cat: &str) -> Option<(&'static str, Option<&'static str>)> {
    Some(match cat {
        "wall" => ("wall", None),
        "floor" => ("floor", None),
        "door" => ("door", None),
        "window" => ("window", None),
        "column" => ("column", None),
        "roof" => ("roof", None),
        "ceiling" => ("ceiling", None),
        "railing" => ("railing", None),
        "structuralcolumn" => ("structural_column", None),
        "footing" => ("footing", None),
        "beam" => ("runs", Some("beam")),
        "stripfooting" => ("runs", Some("stripfooting")),
        "pipe" => ("runs", Some("pipe")),
        "duct" => ("runs", Some("duct")),
        "conduit" => ("runs", Some("conduit")),
        "cabletray" => ("runs", Some("cabletray")),
        "wire" => ("runs", Some("wire")),
        "downconductor" => ("runs", Some("downconductor")),
        "groundconductor" => ("runs", Some("groundconductor")),
        "cable" => ("runs", Some("cable")),
        _ => return None,
    })
}
