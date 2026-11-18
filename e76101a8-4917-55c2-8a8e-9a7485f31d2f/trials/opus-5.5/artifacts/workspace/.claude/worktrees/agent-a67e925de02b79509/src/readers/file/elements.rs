//! The elements of a project file: the original's `Element`, an enum tagged by `category`, each
//! kind a struct of its own (written here in the schema language of `schema`).

/// The categories, in the order the original's enum lists them.
pub const CATEGORIES: &[&str] = &[
    "level",
    "grid",
    "wall",
    "floor",
    "ceiling",
    "shaft",
    "mass",
    "door",
    "window",
    "room",
    "roomseparator",
    "dimension",
    "dimension3d",
    "tag",
    "section",
    "elevation",
    "sheet",
    "viewport",
    "column",
    "structuralcolumn",
    "footing",
    "beam",
    "stripfooting",
    "pipe",
    "duct",
    "conduit",
    "cabletray",
    "wire",
    "downconductor",
    "groundconductor",
    "cable",
    "rebar",
    "component",
    "stair",
    "ramp",
    "railing",
    "roof",
    "text",
    "line",
    "region",
    "detailgroup",
    "repeatingdetail",
    "spot",
    "schedule",
    "view3d",
    "planview",
    "link",
    "pointcloud",
    "cadimport",
];

/// The struct a category's elements are read as.
pub fn struct_of(cat: &str) -> &'static str {
    match cat {
        "level" => "Level",
        "grid" => "Grid",
        "wall" => "Wall",
        "floor" => "Floor",
        "ceiling" => "Ceiling",
        "shaft" => "Shaft",
        "mass" => "Mass",
        "door" | "window" => "Opening",
        "room" => "Room",
        "roomseparator" => "RoomSeparator",
        "dimension" => "Dimension",
        "dimension3d" => "Dimension3D",
        "tag" => "Tag",
        "section" | "elevation" => "Section",
        "sheet" => "Sheet",
        "viewport" => "Viewport",
        "column" | "structuralcolumn" | "footing" => "Column",
        "beam" | "stripfooting" | "pipe" | "duct" | "conduit" | "cabletray" | "wire" | "downconductor"
        | "groundconductor" | "cable" => "RunEl",
        "rebar" => "Rebar",
        "component" => "Component",
        "stair" => "Stair",
        "ramp" => "Ramp",
        "railing" => "Railing",
        "roof" => "Roof",
        "text" => "Note",
        "line" => "RawDetailLine",
        "region" => "FilledRegion",
        "detailgroup" => "DetailGroup",
        "repeatingdetail" => "RepeatingDetail",
        "spot" => "Spot",
        "schedule" => "Schedule",
        "view3d" => "View3D",
        "planview" => "PlanView",
        "link" => "Link",
        "pointcloud" => "PointCloud",
        "cadimport" => "CadImport",
        _ => "",
    }
}

pub const SCHEMA: &str = r##"
tuple P2 (f64, f64)

struct ViewRange {
    top: Option<f64>
    cut: f64 = 1200.0
    bottom: f64 = 0.0
    depth: f64 = 0.0
}

struct Level {
    name: String
    elevation: f64
    view_range: ViewRange = {"top":null,"cut":1200.0,"bottom":0.0,"depth":0.0}
    crop: Option<[P2;2]> ?none
    extent: Option<[P2;2]> ?none
    graphics: Graphics = {} ?empty
    section_box: bool = false ?false
    computation_height: f64 = 1200.0 ?default
}

struct Grid {
    name: String
    start: P2
    end: P2
}

enum Location { center>centre centre core-center>core-centre core-centre exterior-finish interior-finish exterior-core interior-core }

struct Wall {
    type: String
    level: Ref
    start: P2
    end: P2
    top_level: Option<Ref>
    height: f64 = 0.0
    base_offset: f64 = 0.0
    top_offset: f64 = 0.0 ?default
    arc: f64 = 0.0 ?default
    location: Location = "centre" ?default
    attach_top: Option<Ref> ?none
    attach_base: Option<Ref> ?none
    room_bounding: bool = true ?default
    params: Map<Any> = {} ?empty
}

struct ShapePoint {
    id: u64 = 0
    guid: Ref = null
    at: P2
    z: f64
}

struct SplitLine {
    id: u64 = 0
    guid: Ref = null
    a: P2
    b: P2
}

struct Shape {
    points: Vec<ShapePoint> = [] ?empty
    lines: Vec<SplitLine> = [] ?empty
}

struct Floor {
    type: String
    level: Ref
    boundary: Vec<P2>
    openings: Vec<Vec<P2>> = [] ?empty
    offset: f64 = 0.0 ?default
    slope: f64 = 0.0 ?default
    arrow: Option<[P2;2]> ?none
    structural: bool = false ?false
    pattern_origin: P2 = [0.0,0.0] ?default
    pattern_angle: f64 = 0.0 ?default
    sketch: Vec<RawSketchLine> = [] ?empty
    shape: Shape = {} ?empty
    params: Map<Any> = {} ?empty
}

struct Ceiling {
    type: String
    level: Ref
    boundary: Vec<P2>
    openings: Vec<Vec<P2>> = [] ?empty
    offset: f64
    sketch: Vec<RawSketchLine> = [] ?empty
    params: Map<Any> = {} ?empty
}

struct Shaft {
    level: Ref
    boundary: Vec<P2>
    top_level: Option<Ref>
    height: f64 = 0.0
    base_offset: f64 = 0.0
    sketch: Vec<RawSketchLine> = [] ?empty
}

struct Mass {
    name: String = ""
    level: Ref
    boundary: Vec<P2>
    top_level: Option<Ref>
    height: f64 = 0.0
    base_offset: f64 = 0.0
    top: Option<Vec<P2>> ?none
    params: Map<Any> = {} ?empty
}

struct Opening {
    type: String
    family: Option<String> ?none
    host: Ref
    offset: f64
    sill: f64 = 0.0
    mark: String = ""
    flip_facing: bool = false
    flip_hand: bool = false
    params: Map<Any> = {} ?empty
}

struct Region {
    outer: Vec<P2>
    holes: Vec<Vec<P2>>
}

struct Kept {
    centre: Option<Region> ?none
    finish: Option<Region> ?none
}

struct Room @room {
    level: Ref
    point: P2
    name: String
    number: String
    colour: Option<[u8;3]> ?none
    params: Map<Any> = {} ?empty
    base_offset: f64 = 0.0 ?default
    top_level: Option<Ref>
    limit_offset: Some<f64> ?none
    frozen: bool = false ?false
    kept: Option<Kept> ?none
}

struct RoomSeparator {
    level: Ref
    start: P2
    end: P2
}

enum DimKind { aligned linear angular radial diameter arc_length }
enum Orient { horizontal vertical }
enum Face { center>centre centre left right start end }
enum EndPoint { start end }

struct Reference {
    id: Ref
    face: Face = "centre"
    point: Option<EndPoint> ?none
}

struct SegmentText {
    segment: usize
    prefix: String = "" ?empty
    suffix: String = "" ?empty
    above: String = "" ?empty
    below: String = "" ?empty
    replace: String = "" ?empty
}

struct Lock {
    segment: usize
    length: f64
}

struct Dimension @dimension {
    level: Ref
    view: Option<Ref> ?none
    kind: DimKind = "aligned"
    orient: Option<Orient> ?none
    refs: Vec<Reference>
    at: P2
    type: String = ""
    prefix: String = "" ?empty
    suffix: String = "" ?empty
    above: String = "" ?empty
    below: String = "" ?empty
    replace: String = "" ?empty
    equality: bool = false ?false
    texts: Vec<SegmentText> = [] ?empty
    equal: bool = false ?false
    locked: Vec<Lock> = [] ?empty
    alignment: bool = false ?false
}

struct Ref3 {
    at: [f64;3]
    edge: Option<[[f64;3];2]> ?none
}

struct Dimension3D {
    view: Ref
    refs: [Ref3;2]
    at: [f64;3]
    type: String = ""
}

struct Tag {
    host: Ref
    view: Option<Ref> ?none
    offset: P2
    leader: bool = false
    label: Option<String> ?none
}

struct Section {
    name: String
    start: P2
    end: P2
    depth: Option<f64>
    crop: Option<[f64;2]> ?none
    graphics: Graphics = {} ?empty
}

struct Sheet {
    number: String
    name: String
    size: String
}

struct Viewport {
    sheet: Ref
    view: Ref
    at: P2
    scale: f64
}

struct Column {
    type: String
    level: Ref
    at: P2
    angle: f64 = 0.0
    top_level: Option<Ref>
    height: f64 = 0.0
    base_offset: f64 = 0.0
    params: Map<Any> = {} ?empty
    room_bounding: bool = true ?default
}

enum Justify { top center>centre centre bottom }

struct RunEl "Run" {
    type: String
    level: Ref
    start: P2
    end: P2
    offset: f64 = 0.0
    end_offset: Option<f64> ?none
    justify: Justify = "centre"
    system: String = "" ?empty
    params: Map<Any> = {} ?empty
}

struct Rebar {
    level: Ref
    host: Option<Ref> ?none
    path: Vec<[f64;3]>
    diameter: f64
    grade: String = "CA-50"
    layer: String = "" ?empty
}

struct Component {
    family: String
    type: String
    level: Ref
    at: P2
    angle: f64 = 0.0
    offset: f64 = 0.0
    mirrored: bool = false ?false
    params: Map<Any> = {} ?empty
}

struct Landing {
    at: f64
    turn: f64 = 0.0
}

struct Stair {
    level: Ref
    top_level: Option<Ref>
    height: f64 = 0.0
    start: P2
    angle: f64
    width: f64
    riser: f64
    tread: f64
    landings: Vec<Landing> = [] ?empty
    params: Map<Any> = {} ?empty
}

struct Ramp {
    level: Ref
    top_level: Option<Ref>
    height: f64 = 0.0
    start: P2
    angle: f64
    width: f64
    slope: f64
    landings: Vec<Landing> = [] ?empty
    params: Map<Any> = {} ?empty
}

enum Side { left right }

struct Railing {
    type: String
    level: Ref
    path: Vec<P2> = [] ?empty
    base_offset: f64 = 0.0 ?default
    host: Option<Ref> ?none
    side: Option<Side> ?none
    params: Map<Any> = {} ?empty
}

struct Extrusion {
    line: [P2;2]
    profile: Vec<P2>
    from: f64 = 0.0
    to: f64
}

struct Roof {
    type: String
    level: Ref
    boundary: Vec<P2> = [] ?empty
    courtyards: Vec<Vec<P2>> = [] ?empty
    slope: f64 = 0.0
    slopes: Vec<f64> = [] ?empty
    overhang: f64 = 0.0
    gable: bool = false ?false
    gables: Vec<usize> = [] ?empty
    offset: f64 = 0.0
    openings: Vec<Vec<P2>> = [] ?empty
    join: Option<Ref> ?none
    extrusion: Option<Extrusion> ?none
    sketch: Vec<RawSketchLine> = [] ?empty
    shape: Shape = {} ?empty
    params: Map<Any> = {} ?empty
}

struct TextRun "Run" {
    from: usize
    to: usize
    bold: Option<bool> ?none
    italic: Option<bool> ?none
    underline: Option<bool> ?none
}

struct Note @note {
    view: Ref
    at: P2
    text: String
    type: String = ""
    size: Option<f64> ?never
    angle: f64 = 0.0
    leader: Option<P2> ?none
    override_format: bool = false ?false
    runs: Vec<TextRun> = [] ?empty
}

struct RawDetailLine @detail_line {
    view: Ref
    style: String
    points: Option<Vec<P2>>
    arcs: Option<Vec<f64>>
    closed: bool = false
    start: Option<P2>
    end: Option<P2>
    arc: Option<f64>
    through: Option<P2>
    centre: Option<P2>
    radius: Option<f64>
    radii: Option<[f64;2]>
    angle: Option<f64>
    span: Option<[f64;2]>
    control: Option<Vec<P2>>
    knots: Option<Vec<f64>>
    fit: Option<Vec<P2>>
    start_tangent: Option<P2>
    end_tangent: Option<P2>
    insulation: Option<f64>
    centre_mark: bool = false
    cloud: Option<f64>
    revision: Option<String>
}

struct RawSketchLine @sketch_line {
    id: u64 = 0
    guid: Ref = null
    style: Option<String>
    points: Option<Vec<P2>>
    arcs: Option<Vec<f64>>
    closed: bool = false
    start: Option<P2>
    end: Option<P2>
    arc: Option<f64>
    through: Option<P2>
    centre: Option<P2>
    radius: Option<f64>
    radii: Option<[f64;2]>
    angle: Option<f64>
    span: Option<[f64;2]>
    control: Option<Vec<P2>>
    knots: Option<Vec<f64>>
    fit: Option<Vec<P2>>
    start_tangent: Option<P2>
    end_tangent: Option<P2>
    slope: Option<f64>
    invisible: bool = false
}

struct FilledRegion {
    view: Ref
    type: String
    line_style: Option<String> ?none
    sketch: Vec<RawSketchLine>
    pattern_origin: P2 = [0.0,0.0] ?default
    pattern_angle: f64 = 0.0 ?default
}

struct DetailGroup {
    view: Ref
    type: String
    at: P2
    angle: f64 = 0.0 ?default
    mirrored: bool = false ?false
}

struct RepeatingDetail {
    view: Ref
    type: String
    start: P2
    end: P2
    spacing: f64
    mirrored: bool = false ?false
}

struct Spot {
    view: Ref
    at: P2
    host: Option<Ref> ?none
    slope: bool = false ?false
}

enum FieldKind { text number length area yesno }

struct Field {
    name: String
    formula: Option<String> ?none
    kind: Option<FieldKind> ?none
    heading: Option<String> ?none
    total: bool = false ?false
}

enum Op { equals not-equals greater greater-or-equal less less-or-equal contains not-contains begins-with not-begins-with ends-with not-ends-with has-value has-no-value }

struct Filter {
    field: String
    op: Op
    value: Any = null
}

struct Sort {
    field: String
    descending: bool = false ?false
}

struct Schedule {
    name: String
    of: String
    categories: Vec<String> = [] ?empty
    fields: Vec<Field> = [] ?empty
    filters: Vec<Filter> = [] ?empty
    sort: Vec<Sort> = [] ?empty
    grouped: bool = false ?false
}

struct SectionBox {
    min: [f64;3]
    max: [f64;3]
    on: bool = true
}

struct Perspective {
    lens: f64
    on: bool = true
}

struct ViewCamera {
    eye: [f64;3]
    target: [f64;3]
}

struct DisplayOptions {
    edges: bool = true
    silhouette: u32 = 0 ?default
    ambient_shadows: bool = false ?false
}

struct Surface {
    point: [f64;3]
    normal: [f64;3]
}

struct WorkPlane {
    level: Option<Ref> ?none
    offset: f64 = 0.0 ?default
    points: Option<[[f64;3];3]> ?none
    surface: Option<Surface> ?none
}

struct View3D {
    name: String
    azimuth: f64
    elevation: f64
    graphics: Graphics = {} ?empty
    section_box: Option<SectionBox> ?none
    perspective: Option<Perspective> ?none
    camera: Option<ViewCamera> ?none
    display: DisplayOptions = {"edges":true} ?default
    work_plane: Option<WorkPlane> ?none
}

struct PlanView {
    level: Ref
    name: String
    view_range: ViewRange = {"top":null,"cut":1200.0,"bottom":0.0,"depth":0.0}
    crop: Option<[P2;2]> ?none
    graphics: Graphics = {} ?empty
    parent: Option<Ref> ?none
    section_box: bool = false ?false
}

struct Link {
    name: String
    path: String
    at: P2
    angle: f64 = 0.0 ?default
}

struct PointCloud {
    cloud: String
    level: Ref
    at: P2
    offset: f64 = 0.0
    angle: f64 = 0.0
}

enum Colors { preserve invert black }

struct CadImport {
    cad: String
    level: Ref
    at: P2
    origin: P2 = [0.0,0.0] ?default
    scale: f64
    angle: f64 = 0.0 ?default
    view: Option<Ref> ?none
    hidden: Set<String> = [] ?empty
    colors: Colors = "preserve" ?default
}

# ---------------------------------------------------------------- what views draw

enum Dash { solid dashed dotted }

struct PatternFill {
    pattern: Option<String>
    color: [u8;3] = [0,0,0]
}

struct Style {
    color: Option<Colour> ?none
    weight: Option<Weight> ?none
    dash: Option<Dash> ?none
    fill: Option<Colour> ?none
    foreground: Option<PatternFill> ?none
    background: Option<PatternFill> ?none
}

struct Override {
    hidden: bool = false ?false
    projection: Style = {} ?empty
    cut: Style = {} ?empty
    halftone: bool = false ?false
    transparency: u8 = 0 ?default
    shown: bool = false ?false
}

struct AppliedJson {
    filter: String
    hidden: bool = false ?false
    projection: Style = {} ?empty
    cut: Style = {} ?empty
    halftone: bool = false ?false
    transparency: u8 = 0 ?default
}

struct GridStyle {
    enabled: bool = false
    color: [u8;3] = [230,230,230]
    pen: Pen = 0
}

struct BackgroundGrid {
    visible: bool = true
    main: GridStyle = {"enabled":false,"color":[230,230,230],"pen":0}
    sub: GridStyle = {"enabled":false,"color":[245,245,245],"pen":0}
    spacing: [f64;2] = [1000.0,1000.0]
    divisions: [u16;2] = [5,5]
    rotation: f64 = 0.0
}

struct Linework {
    element: Ref
    from: P2
    to: P2
    style: Option<String> ?none
}

enum Detail { coarse medium fine }
enum VisualStyle { shaded hidden_line wireframe }

struct Graphics {
    template: Option<String> ?none
    categories: Map<Override> = {} ?empty
    filters: Vec<AppliedJson> = [] ?empty
    elements: RefMap<Override> = {} ?empty
    phase: Option<String> ?none
    phase_filter: Option<String> ?none
    options: Map<String> = {} ?empty
    scale: Option<f64> ?none
    detail: Detail = "fine" ?default
    style: VisualStyle = "shaded" ?default
    background_grid: BackgroundGrid = {"visible":true,"main":{"enabled":false,"color":[230,230,230],"pen":0},"sub":{"enabled":false,"color":[245,245,245],"pen":0},"spacing":[1000.0,1000.0],"divisions":[5,5],"rotation":0.0} ?default
    linework: Vec<Linework> = [] ?empty
    layers: Map<Set<String>> = {} ?empty
}
"##;
