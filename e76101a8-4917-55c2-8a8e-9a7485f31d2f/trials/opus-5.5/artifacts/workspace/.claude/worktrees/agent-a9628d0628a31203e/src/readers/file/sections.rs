//! The sections of a project file other than its elements: the original's `Model`, its fields
//! (types, materials, families, the drafting styles, the electrical settings…) as serde reads them,
//! and what it writes back for a section the file leaves out.

use super::de::{self, Ctx, R};
use super::schema::Ty;
use crate::json::{Map, Value};

pub const SCHEMA: &str = r##"
struct LibEntry "Entry" {
    kind: LibKind
    name: String
    guid: Ref
}

# ---------------------------------------------------------------- types

enum LayerFunction { structure substrate thermal membrane finish }

struct Layer {
    id: u64 = 0
    guid: Ref = null
    function: LayerFunction = "structure"
    material: String = ""
    thickness: f64
    variable: bool = false ?false
}

struct WallType {
    thickness: f64
    layers: Vec<Layer> = [] ?empty
}

struct FloorType {
    thickness: f64
    layers: Vec<Layer> = [] ?empty
}

struct RoofType {
    thickness: f64
    layers: Vec<Layer> = [] ?empty
}

struct CeilingType {
    thickness: f64
    grid: f64 = 0.0
    layers: Vec<Layer> = [] ?empty
}

enum Operation { swing double-swing sliding double-sliding folding fixed }

struct OpeningType {
    width: f64
    height: f64
    sill: f64 = 0.0
    operation: Option<Operation> ?none
}

struct ColumnType {
    width: f64
    depth: f64
    round: bool = false
}

struct RailingType {
    height: f64
    spacing: f64 = 0.0
}

struct RunType {
    width: f64
    depth: f64
    round: bool = false
    material: String = "" ?empty
}

struct Types {
    wall: Map<WallType>
    floor: Map<FloorType>
    door: Map<OpeningType>
    window: Map<OpeningType>
    column: Map<ColumnType> = {}
    roof: Map<RoofType> = {}
    ceiling: Map<CeilingType> = {}
    railing: Map<RailingType> = {}
    structural_column: Map<ColumnType> = {} ?empty
    footing: Map<ColumnType> = {} ?empty
    runs: Map<Map<RunType>> = {} ?empty
}

# ---------------------------------------------------------------- materials and pictures

enum CutPattern { none solid diagonal crosshatch horizontal vertical grid brick concrete insulation }
enum TextureKind { brick block boards concrete plaster tile roof fabric metal insulation image }

struct Texture {
    kind: TextureKind
    size: [f64;2]
    angle: f64 = 0.0 ?default
    offset: [f64;2] = [0.0,0.0] ?default
    image: String = "" ?empty
}

struct Material {
    color: [u8;3]
    cut: CutPattern = "none"
    surface: CutPattern = "none"
    cut_pattern: Option<String> ?none
    surface_pattern: Option<String> ?none
    texture: Option<Texture> ?none
    transparency: u8 = 0 ?default
}

struct PictureFile @picture {
    name: String
    png: String
}

struct CadFile @cad {
    source: String
    path: Option<String> ?none
    dxf: String
}

# ---------------------------------------------------------------- families

enum FamilyCategory { furniture casework plumbing drain pipefitting pipeaccessory equipment outlet switch airterminal earthing inspectionbox lighting generic dataoutlet voiceoutlet patchpanel rack door window }
enum FamParamKind { length number angle yesno material }
enum Plane { xy xz yz }
enum Align { left center right }
enum ConnKind { power switch }
enum ConnSystem { power-balanced power-unbalanced switch }

untagged Expr = f64 | String
untagged Load = Expr | Vec<Expr>

struct FamParameter "Parameter" {
    name: String
    kind: FamParamKind = "length"
    instance: bool = false ?false
    value: Any = null
    formula: Option<String> ?none
}

struct Circle {
    centre: [Expr;2]
    radius: Expr
}

struct Form {
    id: u64 = 0
    guid: Ref = null
    plane: Plane = "xy"
    profile: Vec<[Expr;2]> = [] ?empty
    circle: Option<Circle> ?none
    from: Expr = 0.0
    to: Expr = 0.0
    axis: Option<[[Expr;2];2]> ?none
    void: bool = false ?false
    material: String = "" ?empty
    visible: Option<Expr> ?none
    mesh: Vec<[[f64;3];3]> = [] ?empty
}

struct Curve {
    centre: [Expr;2]
    radius: Expr
    from: Expr = 0.0
    to: Expr
}

struct Label {
    at: [Expr;2]
    height: Expr
    value: String
    align: Align = "left" ?default
}

struct Symbol {
    id: u64 = 0
    guid: Ref = null
    line: Vec<[Expr;2]> = [] ?empty
    arc: Option<Curve> ?none
    text: Option<Label> ?none
    dot: Option<Circle> ?none
    visible: Option<Expr> ?none
}

struct Connector {
    id: u64 = 0
    guid: Ref = null
    kind: ConnKind
    system: ConnSystem
    poles: u8 = 1
    voltage: Expr = 0.0
    load_va: Load = 0.0
    power_factor: Expr = 1.0
    classification: String = "" ?empty
}

struct Family {
    category: FamilyCategory = "furniture"
    kind: Option<String> ?none
    parameters: Vec<FamParameter> = []
    types: Map<Map<Any>> = {}
    forms: Vec<Form> = []
    symbols: Vec<Symbol> = [] ?empty
    operation: Option<Operation> ?none
    connectors: Vec<Connector> = [] ?empty
}

# ---------------------------------------------------------------- parameters, filters, templates

enum ParamKind { text number length yesno }

struct ProjectParameter {
    kind: ParamKind = "text"
    categories: Vec<String>
}

struct ViewFilter {
    categories: Vec<String>
    rules: Vec<Filter> = [] ?empty
}

enum TemplateKind { plan section 3d }
enum Control { categories filters range phase options scale detail style background_grid }

struct ViewTemplate {
    kind: Option<TemplateKind> ?none
    controls: Set<Control>
    graphics: Graphics = {} ?empty
    view_range: Option<ViewRange> ?none
}

# ---------------------------------------------------------------- phasing

enum Show { by-category overridden not-displayed }
enum Status { new existing demolished temporary }

struct PhaseFilter {
    new: Show = "by-category"
    existing: Show = "by-category"
    demolished: Show = "by-category"
    temporary: Show = "by-category"
}

struct OptionSet {
    options: Vec<String>
    primary: String
}

# ---------------------------------------------------------------- drafting styles

struct ScalePens {
    scale: f64
    widths: [f64;16]
}

struct LineWeights {
    model: Vec<ScalePens>
    annotation: [f64;16]
}

enum Standard { nbr iso ansi eu jis }

struct ObjectStyle {
    projection: Pen
    cut: Pen
}

struct OffsetSeg { length: f64  count: u32  distance: f64 }
struct WaveSeg { length: f64  frequency: f64  amplitude: f64 }
struct TextSeg { length: f64  size: f64  text: String }

enum Segment { dash(f64) space(f64) dot dot_length(f64) offset(OffsetSeg) wave(WaveSeg) zigzag(WaveSeg) text(TextSeg) }

struct LineStyle {
    pen: Pen
    color: [u8;3] = [0,0,0]
    pattern: Option<String> ?none
}

enum Target { drafting model }

struct HatchLine {
    angle: f64
    origin: P2 = [0.0,0.0] ?default
    shift: f64 = 0.0 ?default
    spacing: f64
    dashes: Vec<f64> = [] ?empty
}

struct FillPattern {
    target: Target = "drafting"
    lines: Vec<HatchLine> = [] ?empty
    drawn: Option<f64> ?none
}

struct RegionType "FilledRegionType" {
    foreground: Option<String> ?none
    foreground_color: [u8;3] = [0,0,0]
    background: Option<String> ?none
    background_color: [u8;3] = [0,0,0]
    masking: bool = false ?false
}

struct TextType {
    font: String = "Arial"
    size: f64 = 2.5
    bold: bool = false ?false
    italic: bool = false ?false
    underline: bool = false ?false
    width_factor: f64 = 1.0 ?default
    color: [u8;3] = [0,0,0]
    border: bool = false ?false
    border_offset: f64 = 1.0
    border_pen: Pen = 1
}

enum DimString { continuous baseline ordinate }
enum Tick { diagonal arrow open_arrow dot none }
enum Witness { gap_to_element fixed }
enum Background { opaque transparent }
enum Read { up_then_left up_then_right }
enum DimUnits { mm cm m in ft ft-in }

struct DimensionType {
    string: DimString = "continuous"
    tick: Tick = "diagonal"
    tick_size: f64 = 2.0
    line_pen: Pen = 4
    tick_pen: Pen = 7
    color: [u8;3] = [0,0,0]
    line_extension: f64 = 0.8
    witness: Witness = "gap_to_element"
    witness_length: f64 = 5.0
    witness_gap: f64 = 0.6
    witness_extension: f64 = 0.8
    baseline_spacing: f64 = 7.0
    centre_mark: bool = true
    font: String = "Arial"
    text_size: f64 = 2.5
    width_factor: f64 = 1.0
    bold: bool = false ?false
    italic: bool = false ?false
    underline: bool = false ?false
    text_offset: f64 = 1.0
    background: Background = "opaque"
    read: Read = "up_then_left"
    units: Option<DimUnits> ?none
    decimals: Option<u8> ?none
    radius_symbol: String = "R"
    diameter_symbol: String = "Ø"
    equality_text: String = "EQ"
}

struct Member {
    id: u64 = 0
    guid: Ref = null
    element: MemberElement
}

struct DetailGroupType "GroupType" {
    members: Vec<Member>
}

struct Preset {
    kind: String
    params: Map<Any>
}

# ---------------------------------------------------------------- electrical

struct Voltage {
    nominal: f64
    min: f64
    max: f64
}

struct DistributionSystem {
    phases: u8
    wires: u8
    l_l: Option<String> ?none
    l_n: Option<String> ?none
    l_g: Option<String> ?none
    ground: Option<String> ?none
}

struct WireSize {
    section: f64
    ampacity: f64
    label: Option<String> ?none
}

struct WireType {
    material: String
    temperature: f64
    insulation: String
    note: String = "" ?empty
    sizes: Vec<WireSize>
}

enum Units { mm cm m in ft ft-in }
enum Language { en pt es sv cs fr de nl it }
enum RoomArea { centre finish }
"##;

/// What an English project starts with, and is written only where a file differs from it.
const DEFAULT_PHASES: &str = r#"["Existing","New Construction"]"#;
const DEFAULT_PHASE_FILTERS: &str = r#"{"Show All":{"new":"by-category","existing":"by-category","demolished":"by-category","temporary":"by-category"},"Show Complete":{"new":"by-category","existing":"by-category","demolished":"not-displayed","temporary":"by-category"},"Show New":{"new":"by-category","existing":"not-displayed","demolished":"not-displayed","temporary":"not-displayed"},"Show Previous + Demolished":{"new":"not-displayed","existing":"by-category","demolished":"overridden","temporary":"not-displayed"},"Show Previous + New":{"new":"by-category","existing":"overridden","demolished":"not-displayed","temporary":"by-category"}}"#;
const DEFAULT_PHASE_OVERRIDES: &str = r#"{"existing":{"halftone":true},"demolished":{"projection":{"color":[200,40,30],"dash":"dashed"},"cut":{"color":[200,40,30],"dash":"dashed"}}}"#;

/// How the model takes one of its fields: its type, and what it is when the file leaves it out.
enum Def {
    /// The file must have it.
    Required,
    /// This, written back.
    Value(&'static str),
    /// Left out, and not written.
    Absent,
    /// What an English project starts with.
    Builtin,
}

fn field(name: &str) -> (Ty, Def) {
    let n = |s: &str| Ty::Named(s.to_string());
    let map = |s: &str| Ty::Map(Box::new(Ty::Named(s.to_string())));
    match name {
        "format" => (Ty::U(32), Def::Value("17")),
        "name" => (Ty::Str, Def::Required),
        "uid" => (Ty::U(64), Def::Required),
        "units" => (n("Units"), Def::Value("\"mm\"")),
        "language" => (n("Language"), Def::Value("\"en\"")),
        "room_area" => (n("RoomArea"), Def::Absent),
        "next_id" => (Ty::U(64), Def::Required),
        "types" => (n("Types"), Def::Required),
        "materials" => (map("Material"), Def::Value("{}")),
        "images" => (map("PictureFile"), Def::Absent),
        "cads" => (map("CadFile"), Def::Absent),
        "families" => (map("Family"), Def::Value("{}")),
        "parameters" => (map("ProjectParameter"), Def::Value("{}")),
        "view_filters" => (map("ViewFilter"), Def::Absent),
        "view_templates" => (map("ViewTemplate"), Def::Absent),
        "phases" => (Ty::Vec(Box::new(Ty::Str)), Def::Value(DEFAULT_PHASES)),
        "phase_filters" => (map("PhaseFilter"), Def::Value(DEFAULT_PHASE_FILTERS)),
        "phase_overrides" => (Ty::EnumMap("Status".into(), Box::new(n("Override"))), Def::Value(DEFAULT_PHASE_OVERRIDES)),
        "option_sets" => (map("OptionSet"), Def::Absent),
        "line_weights" => (Ty::Opt(Box::new(n("LineWeights"))), Def::Absent),
        "standard" => (Ty::Opt(Box::new(n("Standard"))), Def::Absent),
        "object_styles" => (map("ObjectStyle"), Def::Absent),
        "line_patterns" => (Ty::Map(Box::new(Ty::Vec(Box::new(n("Segment"))))), Def::Builtin),
        "line_styles" => (map("LineStyle"), Def::Builtin),
        "fill_patterns" => (map("FillPattern"), Def::Builtin),
        "region_types" => (map("RegionType"), Def::Builtin),
        "text_types" => (map("TextType"), Def::Builtin),
        "dimension_types" => (map("DimensionType"), Def::Builtin),
        "detail_groups" => (map("DetailGroupType"), Def::Absent),
        "reinforcement" => (map("Preset"), Def::Absent),
        "voltages" => (map("Voltage"), Def::Builtin),
        "distribution_systems" => (map("DistributionSystem"), Def::Builtin),
        "wire_types" => (map("WireType"), Def::Builtin),
        _ => (Ty::Any, Def::Absent),
    }
}

/// Reads one of the model's sections.
pub fn read_section(name: &str, v: &Value, cx: &mut Ctx) -> R<Value> {
    match name {
        "clouds" => read_clouds(v),
        // a map of whatever expected message the original gives
        "cads" if !matches!(v, Value::Obj(_)) => Err(de::invalid_type(v, "a map of CAD drawings")),
        _ => {
            let (t, _) = field(name);
            de::de(v, &t, cx)
        }
    }
}

/// The scans, read as the point cloud reader reads them.
fn read_clouds(v: &Value) -> R<Value> {
    let mut tmp = crate::project::Project::from_value(Value::obj());
    tmp.doc.insert("clouds", v.clone());
    crate::cloud::file::load(&mut tmp)?;
    Ok(tmp.doc.get("clouds").cloned().unwrap_or_else(Value::obj))
}

/// A section the file leaves out: None when the file must have it; Some(None) when it stays out;
/// Some(Some(v)) when the original has its default.
pub fn default_of(name: &str) -> Option<Option<Value>> {
    if name == "clouds" {
        return Some(None);
    }
    match field(name).1 {
        Def::Required => None,
        Def::Value(s) => Some(Some(crate::json::parse(s).unwrap())),
        Def::Absent => Some(None),
        Def::Builtin => Some(Some(super::builtin::section(name))),
    }
}

/// What the original leaves out of a section once read (the ones written only where they say
/// something).
pub fn finish(mut doc: Map) -> Map {
    let empty_out = ["images", "cads", "view_filters", "view_templates", "option_sets", "object_styles", "detail_groups", "reinforcement"];
    for k in empty_out {
        if let Some(Value::Obj(m)) = doc.get(k) {
            if m.is_empty() {
                doc.remove(k);
            }
        }
    }
    for k in ["line_weights", "standard"] {
        if let Some(Value::Null) = doc.get(k) {
            doc.remove(k);
        }
    }
    if let Some(Value::Str(s)) = doc.get("room_area") {
        if s == "centre" {
            doc.remove("room_area");
        }
    }
    for (k, d) in [("phases", DEFAULT_PHASES), ("phase_filters", DEFAULT_PHASE_FILTERS), ("phase_overrides", DEFAULT_PHASE_OVERRIDES)] {
        if doc.get(k) == Some(&crate::json::parse(d).unwrap()) {
            doc.remove(k);
        }
    }
    // the file is written in this one's format, and ids of elements start at 100000
    doc.insert("format", Value::u(super::FORMAT));
    if let Some(Value::Num(crate::json::Num::U(n))) = doc.get("next_id") {
        if *n < 100_000 {
            doc.insert("next_id", Value::u(100_000));
        }
    }
    doc
}

/// `Model` read from a sequence: its fields in order (an element map and a library last).
pub fn read_seq_model(a: &[Value]) -> R<()> {
    let fields = super::MODEL_FIELDS;
    let n = fields.len();
    for (i, f) in fields.iter().enumerate() {
        match a.get(i) {
            Some(x) => {
                let mut cx = Ctx::new(false);
                match *f {
                    "elements" | "library" => {
                        if !matches!(x, Value::Obj(_)) {
                            return Err(de::invalid_type(x, "a map"));
                        }
                    }
                    _ => {
                        read_section(f, x, &mut cx)?;
                    }
                }
            }
            None => {
                let required = *f == "elements" || matches!(field(f).1, Def::Required);
                if required {
                    return Err(format!("invalid length {}, expected struct Model with {} elements", i, n));
                }
            }
        }
    }
    if a.len() > n {
        return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
    }
    Err("a project file's top is a map".into())
}
