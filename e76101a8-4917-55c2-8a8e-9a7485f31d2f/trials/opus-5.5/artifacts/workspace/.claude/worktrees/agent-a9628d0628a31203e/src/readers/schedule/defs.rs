//! What schedules are of: the categories, their fields and what each holds, the built-in
//! schedules (Room, Door, Window, Wall, Floor and Level Schedule) and their names in each
//! language, and the fields a new schedule of each category starts with.

use crate::project::Project;

/// The categories a schedule can be of, in the order the original lists them.
pub const CATS: &[&str] = &[
    "room",
    "door",
    "window",
    "wall",
    "floor",
    "ceiling",
    "roof",
    "column",
    "structuralcolumn",
    "footing",
    "beam",
    "rebar",
    "stripfooting",
    "pipe",
    "conduit",
    "cabletray",
    "duct",
    "cable",
    "downconductor",
    "groundconductor",
    "wire",
    "component",
    "stair",
    "ramp",
    "railing",
    "mass",
    "massfloor",
    "level",
    "multicategory",
];

/// The categories a multi-category schedule may list.
pub const MULTI_CATS: &[&str] = &[
    "room",
    "door",
    "window",
    "wall",
    "floor",
    "ceiling",
    "roof",
    "column",
    "structuralcolumn",
    "footing",
    "beam",
    "rebar",
    "stripfooting",
    "pipe",
    "conduit",
    "cabletray",
    "duct",
    "cable",
    "downconductor",
    "groundconductor",
    "wire",
    "component",
    "stair",
    "ramp",
    "railing",
    "mass",
    "level",
];

/// What a multi-category schedule lists when it says none: every built one but rooms, levels
/// and masses.
pub const MULTI_DEFAULT: &[&str] = &[
    "door",
    "window",
    "wall",
    "floor",
    "ceiling",
    "roof",
    "column",
    "structuralcolumn",
    "footing",
    "beam",
    "rebar",
    "stripfooting",
    "pipe",
    "conduit",
    "cabletray",
    "duct",
    "cable",
    "downconductor",
    "groundconductor",
    "wire",
    "component",
    "stair",
    "ramp",
    "railing",
];

/// What a field holds.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Text,
    Number,
    Length,
    Area,
    YesNo,
}

impl Kind {
    /// As the errors name it: "holds text", "holds a number"…
    pub fn holds(self) -> &'static str {
        match self {
            Kind::Text => "text",
            Kind::Number => "a number",
            Kind::Length => "a length",
            Kind::Area => "an area",
            Kind::YesNo => "yes or no",
        }
    }
    /// As a filter's error names what it compares.
    pub fn compares(self) -> &'static str {
        match self {
            Kind::Text => "text",
            Kind::Number => "a number",
            Kind::Length => "a length (mm)",
            Kind::Area => "an area (m²)",
            Kind::YesNo => "yes or no",
        }
    }
    pub fn numeric(self) -> bool {
        matches!(self, Kind::Number | Kind::Length | Kind::Area)
    }
    pub fn from_key(k: &str) -> Option<Kind> {
        Some(match k {
            "text" => Kind::Text,
            "number" => Kind::Number,
            "length" => Kind::Length,
            "area" => Kind::Area,
            "yesno" => Kind::YesNo,
            _ => return None,
        })
    }
    pub fn key(self) -> &'static str {
        match self {
            Kind::Text => "text",
            Kind::Number => "number",
            Kind::Length => "length",
            Kind::Area => "area",
            Kind::YesNo => "yesno",
        }
    }
}

use Kind::*;

/// A category's own fields, in order, with what each holds (Count among them).
pub fn own_fields(cat: &str) -> &'static [(&'static str, Kind)] {
    match cat {
        "wall" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("Length", Length),
            ("Height", Length),
            ("Thickness", Length),
            ("Count", Number),
        ],
        "floor" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("Area", Area),
            ("Thickness", Length),
            ("Offset", Length),
            ("Count", Number),
            ("Structural", YesNo),
        ],
        "ceiling" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("Offset", Length),
            ("Area", Area),
            ("Thickness", Length),
            ("Count", Number),
        ],
        "roof" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("Slope", Number),
            ("Plan Area", Area),
            ("Offset", Length),
            ("Count", Number),
        ],
        "door" => &[
            ("Mark", Text),
            ("Type", Text),
            ("Width", Length),
            ("Height", Length),
            ("Level", Text),
            ("Wall", Number),
            ("Family", Text),
            ("Operation", Text),
            ("Count", Number),
        ],
        "window" => &[
            ("Mark", Text),
            ("Type", Text),
            ("Width", Length),
            ("Height", Length),
            ("Sill", Length),
            ("Level", Text),
            ("Wall", Number),
            ("Family", Text),
            ("Operation", Text),
            ("Count", Number),
        ],
        "room" => &[
            ("Number", Text),
            ("Name", Text),
            ("Level", Text),
            ("Area", Area),
            ("Perimeter", Length),
            ("Count", Number),
            ("Unbounded Height", Length),
            ("Volume", Number),
        ],
        "column" | "structuralcolumn" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("Width", Length),
            ("Depth", Length),
            ("Height", Length),
            ("Count", Number),
        ],
        "component" => &[("Family", Text), ("Type", Text), ("Level", Text), ("Count", Number)],
        "stair" => &[
            ("Id", Number),
            ("Level", Text),
            ("Width", Length),
            ("Height", Length),
            ("Risers", Number),
            ("Riser Height", Length),
            ("Tread", Length),
            ("Length", Length),
            ("Count", Number),
        ],
        "ramp" => &[
            ("Id", Number),
            ("Level", Text),
            ("Width", Length),
            ("Height", Length),
            ("Length", Length),
            ("Slope", Number),
            ("Count", Number),
        ],
        "railing" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("Length", Length),
            ("Height", Length),
            ("Count", Number),
        ],
        "mass" => &[
            ("Name", Text),
            ("Level", Text),
            ("Height", Length),
            ("Area", Area),
            ("Volume", Number),
            ("Gross Floor Area", Area),
            ("Count", Number),
        ],
        "footing" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("Width", Length),
            ("Depth", Length),
            ("Thickness", Length),
            ("Count", Number),
        ],
        "beam" | "stripfooting" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("Length", Length),
            ("Width", Length),
            ("Depth", Length),
            ("System", Text),
            ("Count", Number),
        ],
        "pipe" | "conduit" | "wire" | "cable" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("System", Text),
            ("Length", Length),
            ("Diameter", Length),
            ("Count", Number),
        ],
        "duct" | "cabletray" | "downconductor" | "groundconductor" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("System", Text),
            ("Length", Length),
            ("Width", Length),
            ("Depth", Length),
            ("Count", Number),
        ],
        "rebar" => &[
            ("Id", Number),
            ("Level", Text),
            ("Grade", Text),
            ("Diameter", Length),
            ("Length", Length),
            ("Count", Number),
            ("Weight", Number),
            ("Host", Number),
            ("Layer", Text),
        ],
        "massfloor" => &[
            ("Mass", Text),
            ("Level", Text),
            ("Area", Area),
            ("Perimeter", Length),
            ("Volume", Number),
            ("Count", Number),
        ],
        "level" => &[("Elevation", Length), ("Name", Text), ("Count", Number)],
        "multicategory" => &[
            ("Category", Text),
            ("Family", Text),
            ("Type", Text),
            ("Level", Text),
            ("Count", Number),
            ("Width", Length),
            ("Height", Length),
            ("Length", Length),
            ("Thickness", Length),
            ("Area", Area),
            ("Material", Text),
            ("Id", Number),
            ("Mark", Text),
            ("Name", Text),
        ],
        _ => &[],
    }
}

/// The fields a schedule of a category shows until it's told otherwise.
pub fn default_fields(cat: &str) -> &'static [&'static str] {
    match cat {
        "room" => &["Number", "Name", "Level", "Area", "Perimeter"],
        "door" => &["Mark", "Type", "Width", "Height", "Level", "Wall"],
        "window" => &["Mark", "Type", "Width", "Height", "Sill", "Level", "Wall"],
        "wall" => &["Id", "Type", "Level", "Length", "Height", "Thickness"],
        "floor" => &["Id", "Type", "Level", "Area", "Thickness"],
        "ceiling" => &["Id", "Type", "Level", "Offset", "Area"],
        "roof" => &["Id", "Type", "Level", "Slope"],
        "column" | "structuralcolumn" => &["Id", "Type", "Level", "Width", "Depth", "Height"],
        "footing" => &["Id", "Type", "Level", "Width", "Depth", "Thickness"],
        "beam" | "stripfooting" => &["Id", "Type", "Level", "Length", "Width", "Depth"],
        "pipe" | "conduit" | "wire" | "cable" => &["Id", "Type", "Level", "System", "Length", "Diameter"],
        "duct" | "cabletray" | "downconductor" | "groundconductor" => {
            &["Id", "Type", "Level", "System", "Length", "Width", "Depth"]
        }
        "component" => &["Family", "Type", "Level", "Count"],
        "stair" => &["Id", "Level", "Width", "Height", "Risers", "Riser Height", "Tread"],
        "ramp" => &["Id", "Level", "Width", "Height", "Length", "Slope"],
        "railing" => &["Id", "Type", "Level", "Length", "Height"],
        "rebar" => &["Id", "Level", "Grade", "Diameter", "Length", "Count", "Weight"],
        "mass" => &["Name", "Level", "Height", "Area", "Volume"],
        "massfloor" => &["Mass", "Level", "Area", "Perimeter", "Volume"],
        "level" => &["Elevation", "Name"],
        "multicategory" => &[
            "Category", "Family", "Type", "Level", "Count", "Width", "Height", "Length", "Thickness", "Area", "Material",
        ],
        _ => &[],
    }
}

/// Whether a category's schedules have the phase and design option fields.
pub fn phased(cat: &str) -> bool {
    !matches!(cat, "rebar" | "level" | "massfloor")
}

pub const PHASE_CREATED: &str = "Phase Created";
pub const PHASE_DEMOLISHED: &str = "Phase Demolished";
pub const DESIGN_OPTION: &str = "Design Option";

/// The categories with a built-in schedule, in the order of the names below.
pub const BUILTIN_CATS: &[&str] = &["room", "door", "window", "wall", "floor", "level"];

/// The built-in schedules' names, by language (rooms, doors, windows, walls, floors, levels).
const BUILTIN_NAMES: &[(&str, [&str; 6])] = &[
    ("en", ["Room Schedule", "Door Schedule", "Window Schedule", "Wall Schedule", "Floor Schedule", "Level Schedule"]),
    (
        "pt",
        [
            "Tabela de ambientes",
            "Tabela de portas",
            "Tabela de janelas",
            "Tabela de paredes",
            "Tabela de pisos",
            "Tabela de níveis",
        ],
    ),
    (
        "es",
        [
            "Tabla de habitaciones",
            "Tabla de puertas",
            "Tabla de ventanas",
            "Tabla de muros",
            "Tabla de pisos",
            "Tabla de niveles",
        ],
    ),
    (
        "sv",
        [
            "Rumsförteckning",
            "Dörrförteckning",
            "Fönsterförteckning",
            "Väggförteckning",
            "Bjälklagsförteckning",
            "Nivåförteckning",
        ],
    ),
    ("cs", ["Výkaz místností", "Výkaz dveří", "Výkaz oken", "Výkaz stěn", "Výkaz podlah", "Výkaz podlaží"]),
    (
        "fr",
        [
            "Nomenclature des pièces",
            "Nomenclature des portes",
            "Nomenclature des fenêtres",
            "Nomenclature des murs",
            "Nomenclature des sols",
            "Nomenclature des niveaux",
        ],
    ),
    ("nl", ["Ruimtelijst", "Deurenlijst", "Ramenlijst", "Murenlijst", "Vloerenlijst", "Niveaulijst"]),
    ("de", ["Raumtabelle", "Türtabelle", "Fenstertabelle", "Wandtabelle", "Bodentabelle", "Geschosstabelle"]),
    ("it", ["Abaco zone", "Abaco porte", "Abaco finestre", "Abaco muri", "Abaco solai", "Abaco piani"]),
];

/// A category's built-in schedule's name in a language (English for one it hasn't).
pub fn builtin_name(cat: &str, lang: &str) -> Option<&'static str> {
    let i = BUILTIN_CATS.iter().position(|c| *c == cat)?;
    let names = BUILTIN_NAMES.iter().find(|(l, _)| *l == lang).unwrap_or(&BUILTIN_NAMES[0]);
    Some(names.1[i])
}

/// The category whose built-in schedule a name is, in any language and any case.
pub fn builtin_of_name(name: &str) -> Option<&'static str> {
    let low = name.trim().to_lowercase();
    for (_, names) in BUILTIN_NAMES {
        for (i, n) in names.iter().enumerate() {
            if n.to_lowercase() == low {
                return Some(BUILTIN_CATS[i]);
            }
        }
    }
    None
}

/// A category as typed: in any case, words together or apart, plural or not.
pub fn parse_category(s: &str, among: &[&'static str]) -> Option<&'static str> {
    among.iter().copied().find(|c| crate::readers::view::category_matches(s, c))
}

/// A category as the errors name its elements: "doors", "multicategorys".
pub fn plural(cat: &str) -> String {
    format!("{}s", cat)
}

/// The project's language.
pub fn language(pr: &Project) -> String {
    pr.language()
}
