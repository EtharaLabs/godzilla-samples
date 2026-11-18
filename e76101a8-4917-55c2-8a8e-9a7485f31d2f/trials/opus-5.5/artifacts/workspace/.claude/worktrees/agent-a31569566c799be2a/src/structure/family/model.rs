//! A family as the original holds it in memory (its materials by name), read from the project
//! file's JSON (materials by GUID) and written back to it, and shown as `family` and `inspect`
//! show it.

use crate::json::{Map, Num, Value};

/// A size: a number of mm (or degrees), or a formula over the family's parameters.
#[derive(Clone, Debug, PartialEq)]
pub enum Expr {
    Num(f64),
    Text(String),
}

impl Expr {
    pub fn value(&self) -> Value {
        match self {
            Expr::Num(x) => Value::f(*x),
            Expr::Text(s) => Value::s(s),
        }
    }
    /// From a file: a number or a formula's text (anything else, none).
    pub fn from_value(v: &Value) -> Option<Expr> {
        match v {
            Value::Num(n) => Some(Expr::Num(n.as_f64())),
            Value::Str(s) => Some(Expr::Text(s.clone())),
            _ => None,
        }
    }
    pub fn zero() -> Expr {
        Expr::Num(0.0)
    }
}

/// What a part's `guid` names: a GUID, or (as a command may give it) an element's id.
#[derive(Clone, Debug, PartialEq)]
pub enum GRef {
    Guid(String),
    Id(u64),
}

impl GRef {
    pub fn value(&self) -> Value {
        match self {
            GRef::Guid(g) => Value::s(g),
            GRef::Id(n) => Value::u(*n),
        }
    }
    pub fn guid(&self) -> Option<&str> {
        match self {
            GRef::Guid(g) => Some(g),
            GRef::Id(_) => None,
        }
    }
}

/// A parameter's kind.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Length,
    Number,
    Angle,
    YesNo,
    Material,
}

pub const KINDS: &[&str] = &["length", "number", "angle", "yesno", "material"];

impl Kind {
    pub fn name(self) -> &'static str {
        match self {
            Kind::Length => "length",
            Kind::Number => "number",
            Kind::Angle => "angle",
            Kind::YesNo => "yesno",
            Kind::Material => "material",
        }
    }
    pub fn parse(s: &str) -> Option<Kind> {
        Some(match s {
            "length" => Kind::Length,
            "number" => Kind::Number,
            "angle" => Kind::Angle,
            "yesno" => Kind::YesNo,
            "material" => Kind::Material,
            _ => return None,
        })
    }
}

/// A family parameter: each type's, or with `instance` each component's. Its `value` is the
/// JSON it was given (a number as written, a yes/no, a material's name), null for none.
#[derive(Clone, Debug, PartialEq)]
pub struct Param {
    pub name: String,
    pub kind: Kind,
    pub instance: bool,
    pub value: Value,
    pub formula: Option<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Plane {
    XY,
    XZ,
    YZ,
}

pub const PLANES: &[&str] = &["xy", "xz", "yz"];

impl Plane {
    pub fn name(self) -> &'static str {
        match self {
            Plane::XY => "xy",
            Plane::XZ => "xz",
            Plane::YZ => "yz",
        }
    }
    pub fn parse(s: &str) -> Option<Plane> {
        Some(match s {
            "xy" => Plane::XY,
            "xz" => Plane::XZ,
            "yz" => Plane::YZ,
            _ => return None,
        })
    }
}

pub type Pt = [Expr; 2];

#[derive(Clone, Debug, PartialEq)]
pub struct Circle {
    pub centre: Pt,
    pub radius: Expr,
}

/// A form: a profile (or a circle) in a sketch plane swept from `from` to `to`, or turned about
/// an `axis` from `from` to `to` degrees, or triangles as a file brings them (`mesh`).
#[derive(Clone, Debug, PartialEq)]
pub struct Form {
    pub id: Option<u64>,
    pub guid: Option<GRef>,
    pub plane: Plane,
    pub profile: Vec<Pt>,
    pub circle: Option<Circle>,
    pub from: Expr,
    pub to: Expr,
    pub axis: Option<[Pt; 2]>,
    pub void: bool,
    /// A material's name or a material parameter's; "" for none.
    pub material: String,
    pub visible: Option<Expr>,
    pub mesh: Vec<[[f64; 3]; 3]>,
}

impl Default for Form {
    fn default() -> Form {
        Form {
            id: None,
            guid: None,
            plane: Plane::XY,
            profile: Vec::new(),
            circle: None,
            from: Expr::zero(),
            to: Expr::zero(),
            axis: None,
            void: false,
            material: String::new(),
            visible: None,
            mesh: Vec::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Arc {
    pub centre: Pt,
    pub radius: Expr,
    pub from: Expr,
    pub to: Expr,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Align {
    Left,
    Center,
    Right,
}

pub const ALIGNS: &[&str] = &["left", "center", "right"];

impl Align {
    pub fn name(self) -> &'static str {
        match self {
            Align::Left => "left",
            Align::Center => "center",
            Align::Right => "right",
        }
    }
    pub fn parse(s: &str) -> Option<Align> {
        Some(match s {
            "left" => Align::Left,
            "center" => Align::Center,
            "right" => Align::Right,
            _ => return None,
        })
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Text {
    pub at: Pt,
    pub height: Expr,
    pub value: String,
    pub align: Align,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Dot {
    pub centre: Pt,
    pub radius: Expr,
}

/// A plan symbol: one of a line, an arc, a text or a dot.
#[derive(Clone, Debug, PartialEq, Default)]
pub struct Symbol {
    pub id: Option<u64>,
    pub guid: Option<GRef>,
    pub line: Vec<Pt>,
    pub arc: Option<Arc>,
    pub text: Option<Text>,
    pub dot: Option<Dot>,
    pub visible: Option<Expr>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ConnKind {
    Power,
    Switch,
}

pub const CONN_KINDS: &[&str] = &["power", "switch"];

impl ConnKind {
    pub fn name(self) -> &'static str {
        match self {
            ConnKind::Power => "power",
            ConnKind::Switch => "switch",
        }
    }
    pub fn parse(s: &str) -> Option<ConnKind> {
        Some(match s {
            "power" => ConnKind::Power,
            "switch" => ConnKind::Switch,
            _ => return None,
        })
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum System {
    Balanced,
    Unbalanced,
    Switch,
}

pub const SYSTEMS: &[&str] = &["power-balanced", "power-unbalanced", "switch"];

impl System {
    pub fn name(self) -> &'static str {
        match self {
            System::Balanced => "power-balanced",
            System::Unbalanced => "power-unbalanced",
            System::Switch => "switch",
        }
    }
    pub fn parse(s: &str) -> Option<System> {
        Some(match s {
            "power-balanced" => System::Balanced,
            "power-unbalanced" => System::Unbalanced,
            "switch" => System::Switch,
            _ => return None,
        })
    }
}

/// A connector's load: one for the device, or one for each pole.
#[derive(Clone, Debug, PartialEq)]
pub enum Load {
    One(Expr),
    PerPole(Vec<Expr>),
}

impl Load {
    pub fn value(&self) -> Value {
        match self {
            Load::One(e) => e.value(),
            Load::PerPole(v) => Value::Arr(v.iter().map(|e| e.value()).collect()),
        }
    }
}

/// What an electrical device draws (or a switch switches).
#[derive(Clone, Debug, PartialEq)]
pub struct Connector {
    pub id: Option<u64>,
    pub guid: Option<GRef>,
    pub kind: ConnKind,
    pub system: System,
    pub poles: u8,
    pub voltage: Expr,
    pub load_va: Load,
    pub power_factor: Expr,
    pub classification: String,
}

/// The categories a family may be of, in the original's order.
pub const CATEGORIES: &[&str] = &[
    "furniture",
    "casework",
    "plumbing",
    "drain",
    "pipefitting",
    "pipeaccessory",
    "equipment",
    "outlet",
    "switch",
    "airterminal",
    "earthing",
    "inspectionbox",
    "lighting",
    "generic",
    "dataoutlet",
    "voiceoutlet",
    "patchpanel",
    "rack",
    "door",
    "window",
];

/// The kinds a category's fixtures and fittings may be (none for the others).
pub fn kinds_of(category: &str) -> &'static [&'static str] {
    match category {
        "plumbing" => &["wc", "lav", "sink", "laundry", "shower", "bath", "bidet", "urinal"],
        "drain" => &["floor_drain", "floor_waste", "roof_drain"],
        "pipefitting" => &["bend", "tee", "cross", "transition", "coupling"],
        _ => &[],
    }
}

/// How a door or a window opens.
pub const OPERATIONS: &[&str] = &["swing", "double-swing", "sliding", "double-sliding", "folding", "fixed"];

/// A family.
#[derive(Clone, Debug, PartialEq)]
pub struct Family {
    pub category: String,
    pub kind: Option<String>,
    pub parameters: Vec<Param>,
    /// Its types by name (in name order), each its parameters' values by name.
    pub types: Vec<(String, Map)>,
    pub forms: Vec<Form>,
    pub symbols: Vec<Symbol>,
    pub operation: Option<String>,
    pub connectors: Vec<Connector>,
}

impl Default for Family {
    fn default() -> Family {
        Family {
            category: "furniture".into(),
            kind: None,
            parameters: Vec::new(),
            types: Vec::new(),
            forms: Vec::new(),
            symbols: Vec::new(),
            operation: None,
            connectors: Vec::new(),
        }
    }
}

impl Family {
    /// Whether it stands in a wall (a door's or a window's).
    pub fn hosted(&self) -> bool {
        self.category == "door" || self.category == "window"
    }
    pub fn param(&self, name: &str) -> Option<&Param> {
        self.parameters.iter().find(|p| p.name == name)
    }
    pub fn type_values(&self, name: &str) -> Option<&Map> {
        self.types.iter().find(|(n, _)| n == name).map(|(_, m)| m)
    }
    pub fn type_names(&self) -> Vec<String> {
        self.types.iter().map(|(n, _)| n.clone()).collect()
    }
    /// Sets a type's values, keeping the types in name order.
    pub fn set_type(&mut self, name: &str, values: Map) {
        match self.types.binary_search_by(|(n, _)| n.as_str().cmp(name)) {
            Ok(i) => self.types[i].1 = values,
            Err(i) => self.types.insert(i, (name.to_string(), values)),
        }
    }
    pub fn remove_type(&mut self, name: &str) {
        self.types.retain(|(n, _)| n != name);
    }
    /// The material parameters' names.
    pub fn material_params(&self) -> Vec<String> {
        self.parameters.iter().filter(|p| p.kind == Kind::Material).map(|p| p.name.clone()).collect()
    }
}

// ---------------------------------------------------------------- the project file's form

fn pt_from(v: &Value) -> Pt {
    let a = v.as_arr();
    let at = |i: usize| a.and_then(|a| a.get(i)).and_then(Expr::from_value).unwrap_or_else(Expr::zero);
    [at(0), at(1)]
}

fn pts_from(v: Option<&Value>) -> Vec<Pt> {
    v.and_then(|x| x.as_arr()).map(|a| a.iter().map(pt_from).collect()).unwrap_or_default()
}

fn expr_of(v: Option<&Value>, d: Expr) -> Expr {
    v.and_then(Expr::from_value).unwrap_or(d)
}

fn id_from(v: &Value) -> Option<u64> {
    v.get("id").and_then(|x| x.as_u64()).filter(|n| *n != 0)
}

fn guid_from(v: &Value) -> Option<GRef> {
    match v.get("guid") {
        Some(Value::Str(s)) if !s.is_empty() => Some(GRef::Guid(s.clone())),
        Some(Value::Num(Num::U(n))) if *n != 0 => Some(GRef::Id(*n)),
        _ => None,
    }
}

fn str_of(v: Option<&Value>) -> String {
    v.and_then(|x| x.as_str()).unwrap_or("").to_string()
}

fn form_from(v: &Value, mat: &dyn Fn(&str) -> String) -> Form {
    let circle = v.get("circle").filter(|c| !c.is_null()).map(|c| Circle {
        centre: c.get("centre").map(pt_from).unwrap_or([Expr::zero(), Expr::zero()]),
        radius: expr_of(c.get("radius"), Expr::zero()),
    });
    let axis = v.get("axis").and_then(|a| a.as_arr()).map(|a| {
        [a.first().map(pt_from).unwrap_or([Expr::zero(), Expr::zero()]), a.get(1).map(pt_from).unwrap_or([Expr::zero(), Expr::zero()])]
    });
    let mesh = v
        .get("mesh")
        .and_then(|m| m.as_arr())
        .map(|tris| {
            tris.iter()
                .map(|t| {
                    let mut out = [[0.0; 3]; 3];
                    for (i, p) in t.as_arr().map(|x| x.as_slice()).unwrap_or(&[]).iter().take(3).enumerate() {
                        for (j, c) in p.as_arr().map(|x| x.as_slice()).unwrap_or(&[]).iter().take(3).enumerate() {
                            out[i][j] = c.as_f64().unwrap_or(0.0);
                        }
                    }
                    out
                })
                .collect()
        })
        .unwrap_or_default();
    let material = str_of(v.get("material"));
    Form {
        id: id_from(v),
        guid: guid_from(v),
        plane: v.get("plane").and_then(|p| p.as_str()).and_then(Plane::parse).unwrap_or(Plane::XY),
        profile: pts_from(v.get("profile")),
        circle,
        from: expr_of(v.get("from"), Expr::zero()),
        to: expr_of(v.get("to"), Expr::zero()),
        axis,
        void: v.get("void").and_then(|x| x.as_bool()).unwrap_or(false),
        material: if material.is_empty() { material } else { mat(&material) },
        visible: v.get("visible").and_then(Expr::from_value),
        mesh,
    }
}

fn symbol_from(v: &Value) -> Symbol {
    let arc = v.get("arc").filter(|c| !c.is_null()).map(|c| Arc {
        centre: c.get("centre").map(pt_from).unwrap_or([Expr::zero(), Expr::zero()]),
        radius: expr_of(c.get("radius"), Expr::zero()),
        from: expr_of(c.get("from"), Expr::zero()),
        to: expr_of(c.get("to"), Expr::zero()),
    });
    let text = v.get("text").filter(|c| !c.is_null()).map(|c| Text {
        at: c.get("at").map(pt_from).unwrap_or([Expr::zero(), Expr::zero()]),
        height: expr_of(c.get("height"), Expr::zero()),
        value: str_of(c.get("value")),
        align: c.get("align").and_then(|a| a.as_str()).and_then(Align::parse).unwrap_or(Align::Left),
    });
    let dot = v.get("dot").filter(|c| !c.is_null()).map(|c| Dot {
        centre: c.get("centre").map(pt_from).unwrap_or([Expr::zero(), Expr::zero()]),
        radius: expr_of(c.get("radius"), Expr::zero()),
    });
    Symbol {
        id: id_from(v),
        guid: guid_from(v),
        line: pts_from(v.get("line")),
        arc,
        text,
        dot,
        visible: v.get("visible").and_then(Expr::from_value),
    }
}

fn connector_from(v: &Value) -> Connector {
    let load_va = match v.get("load_va") {
        Some(Value::Arr(a)) => Load::PerPole(a.iter().map(|x| Expr::from_value(x).unwrap_or_else(Expr::zero)).collect()),
        Some(x) => Load::One(Expr::from_value(x).unwrap_or_else(Expr::zero)),
        None => Load::One(Expr::zero()),
    };
    Connector {
        id: id_from(v),
        guid: guid_from(v),
        kind: v.get("kind").and_then(|k| k.as_str()).and_then(ConnKind::parse).unwrap_or(ConnKind::Power),
        system: v.get("system").and_then(|k| k.as_str()).and_then(System::parse).unwrap_or(System::Balanced),
        poles: v.get("poles").and_then(|x| x.as_u64()).map(|n| n.min(255) as u8).unwrap_or(1),
        voltage: expr_of(v.get("voltage"), Expr::zero()),
        load_va,
        power_factor: expr_of(v.get("power_factor"), Expr::Num(1.0)),
        classification: str_of(v.get("classification")),
    }
}

/// A family as the project file holds it, read: `mat` turns a material's GUID into its name
/// (anything else stays as it is).
pub fn from_file(v: &Value, mat: &dyn Fn(&str) -> String) -> Family {
    let parameters: Vec<Param> = v
        .get("parameters")
        .and_then(|p| p.as_arr())
        .map(|a| {
            a.iter()
                .map(|p| {
                    let kind = p.get("kind").and_then(|k| k.as_str()).and_then(Kind::parse).unwrap_or(Kind::Length);
                    let mut value = p.get("value").cloned().unwrap_or(Value::Null);
                    if kind == Kind::Material {
                        if let Value::Str(s) = &value {
                            if !s.is_empty() {
                                value = Value::Str(mat(s));
                            }
                        }
                    }
                    Param {
                        name: str_of(p.get("name")),
                        kind,
                        instance: p.get("instance").and_then(|x| x.as_bool()).unwrap_or(false),
                        value,
                        formula: p.get("formula").and_then(|f| f.as_str()).map(|s| s.to_string()),
                    }
                })
                .collect()
        })
        .unwrap_or_default();
    let mats: Vec<String> = parameters.iter().filter(|p| p.kind == Kind::Material).map(|p| p.name.clone()).collect();
    let mut types: Vec<(String, Map)> = Vec::new();
    if let Some(Value::Obj(ts)) = v.get("types") {
        for (n, t) in ts.iter() {
            let mut m = Map::new();
            if let Value::Obj(vals) = t {
                for (k, x) in vals.iter() {
                    let x = match x {
                        Value::Str(s) if mats.contains(k) && !s.is_empty() => Value::Str(mat(s)),
                        _ => x.clone(),
                    };
                    m.insert_sorted(k, x);
                }
            }
            types.push((n.clone(), m));
        }
        types.sort_by(|a, b| a.0.cmp(&b.0));
        types.dedup_by(|a, b| a.0 == b.0);
    }
    let forms = v
        .get("forms")
        .and_then(|f| f.as_arr())
        .map(|a| {
            a.iter()
                .map(|f| {
                    let mut fo = form_from(f, mat);
                    // a material parameter's name is the parameter's, whatever a material is named
                    if !fo.material.is_empty() {
                        let raw = str_of(f.get("material"));
                        if mats.contains(&raw) {
                            fo.material = raw;
                        }
                    }
                    fo
                })
                .collect()
        })
        .unwrap_or_default();
    Family {
        category: v.get("category").and_then(|c| c.as_str()).unwrap_or("furniture").to_string(),
        kind: v.get("kind").and_then(|k| k.as_str()).map(|s| s.to_string()),
        parameters,
        types,
        forms,
        symbols: v.get("symbols").and_then(|s| s.as_arr()).map(|a| a.iter().map(symbol_from).collect()).unwrap_or_default(),
        operation: v.get("operation").and_then(|o| o.as_str()).map(|s| s.to_string()),
        connectors: v.get("connectors").and_then(|s| s.as_arr()).map(|a| a.iter().map(connector_from).collect()).unwrap_or_default(),
    }
}

fn pt_value(p: &Pt) -> Value {
    Value::Arr(vec![p[0].value(), p[1].value()])
}

fn pts_value(v: &[Pt]) -> Value {
    Value::Arr(v.iter().map(pt_value).collect())
}

fn form_value(f: &Form, material: &str) -> Value {
    let mut m = Map::new();
    if let Some(id) = f.id {
        m.insert("id", Value::u(id));
    }
    if let Some(g) = &f.guid {
        m.insert("guid", g.value());
    }
    m.insert("plane", Value::s(f.plane.name()));
    if !f.profile.is_empty() {
        m.insert("profile", pts_value(&f.profile));
    }
    if let Some(c) = &f.circle {
        m.insert("circle", crate::jobj! {"centre" => pt_value(&c.centre), "radius" => c.radius.value()});
    }
    m.insert("from", f.from.value());
    m.insert("to", f.to.value());
    if let Some(a) = &f.axis {
        m.insert("axis", Value::Arr(vec![pt_value(&a[0]), pt_value(&a[1])]));
    }
    if f.void {
        m.insert("void", Value::Bool(true));
    }
    if !material.is_empty() {
        m.insert("material", Value::s(material));
    }
    if let Some(v) = &f.visible {
        m.insert("visible", v.value());
    }
    if !f.mesh.is_empty() {
        let tris: Vec<Value> = f
            .mesh
            .iter()
            .map(|t| Value::Arr(t.iter().map(|p| Value::Arr(p.iter().map(|c| Value::f(*c)).collect())).collect()))
            .collect();
        m.insert("mesh", Value::Arr(tris));
    }
    Value::Obj(m)
}

pub fn symbol_value(s: &Symbol) -> Value {
    let mut m = Map::new();
    if let Some(id) = s.id {
        m.insert("id", Value::u(id));
    }
    if let Some(g) = &s.guid {
        m.insert("guid", g.value());
    }
    if !s.line.is_empty() {
        m.insert("line", pts_value(&s.line));
    }
    if let Some(a) = &s.arc {
        m.insert(
            "arc",
            crate::jobj! {"centre" => pt_value(&a.centre), "radius" => a.radius.value(), "from" => a.from.value(), "to" => a.to.value()},
        );
    }
    if let Some(t) = &s.text {
        let mut tm = Map::new();
        tm.insert("at", pt_value(&t.at));
        tm.insert("height", t.height.value());
        tm.insert("value", Value::s(&t.value));
        if t.align != Align::Left {
            tm.insert("align", Value::s(t.align.name()));
        }
        m.insert("text", Value::Obj(tm));
    }
    if let Some(d) = &s.dot {
        m.insert("dot", crate::jobj! {"centre" => pt_value(&d.centre), "radius" => d.radius.value()});
    }
    if let Some(v) = &s.visible {
        m.insert("visible", v.value());
    }
    Value::Obj(m)
}

pub fn connector_value(c: &Connector) -> Value {
    let mut m = Map::new();
    if let Some(id) = c.id {
        m.insert("id", Value::u(id));
    }
    if let Some(g) = &c.guid {
        m.insert("guid", g.value());
    }
    m.insert("kind", Value::s(c.kind.name()));
    m.insert("system", Value::s(c.system.name()));
    m.insert("poles", Value::u(c.poles as u64));
    m.insert("voltage", c.voltage.value());
    m.insert("load_va", c.load_va.value());
    m.insert("power_factor", c.power_factor.value());
    if !c.classification.is_empty() {
        m.insert("classification", Value::s(&c.classification));
    }
    Value::Obj(m)
}

fn param_value(p: &Param, value: Value) -> Value {
    let mut m = Map::new();
    m.insert("name", Value::s(&p.name));
    m.insert("kind", Value::s(p.kind.name()));
    if p.instance {
        m.insert("instance", Value::Bool(true));
    }
    m.insert("value", value);
    if let Some(f) = &p.formula {
        m.insert("formula", Value::s(f));
    }
    Value::Obj(m)
}

impl Family {
    /// As the file holds it (the original's field order), `mat` giving a material's GUID by
    /// name (None leaves the name).
    pub fn to_file(&self, mat: &dyn Fn(&str) -> Option<String>) -> Value {
        self.write(&|s: &str| mat(s).unwrap_or_else(|| s.to_string()))
    }

    /// As `family` and `inspect` show it: materials by name.
    pub fn view(&self) -> Value {
        self.write(&|s: &str| s.to_string())
    }

    fn write(&self, mat: &dyn Fn(&str) -> String) -> Value {
        let mats = self.material_params();
        let mut m = Map::new();
        m.insert("category", Value::s(&self.category));
        if let Some(k) = &self.kind {
            m.insert("kind", Value::s(k));
        }
        let params: Vec<Value> = self
            .parameters
            .iter()
            .map(|p| {
                let v = match (&p.value, p.kind) {
                    (Value::Str(s), Kind::Material) if !s.is_empty() => Value::Str(mat(s)),
                    (v, _) => v.clone(),
                };
                param_value(p, v)
            })
            .collect();
        m.insert("parameters", Value::Arr(params));
        let mut types = Map::new();
        for (n, vals) in &self.types {
            let mut t = Map::new();
            for (k, x) in vals.iter() {
                let x = match x {
                    Value::Str(s) if mats.contains(k) && !s.is_empty() => Value::Str(mat(s)),
                    _ => x.clone(),
                };
                t.insert_sorted(k, x);
            }
            types.insert_sorted(n, Value::Obj(t));
        }
        m.insert("types", Value::Obj(types));
        let forms: Vec<Value> = self
            .forms
            .iter()
            .map(|f| {
                let material = if f.material.is_empty() || mats.contains(&f.material) {
                    f.material.clone()
                } else {
                    mat(&f.material)
                };
                form_value(f, &material)
            })
            .collect();
        m.insert("forms", Value::Arr(forms));
        if !self.symbols.is_empty() {
            m.insert("symbols", Value::Arr(self.symbols.iter().map(symbol_value).collect()));
        }
        if let Some(o) = &self.operation {
            m.insert("operation", Value::s(o));
        }
        if !self.connectors.is_empty() {
            m.insert("connectors", Value::Arr(self.connectors.iter().map(connector_value).collect()));
        }
        Value::Obj(m)
    }
}
