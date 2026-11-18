//! The `BuiltInCategory` ids the reader knows by name.

pub const OST_WALLS: i64 = -2000011;
pub const OST_WINDOWS: i64 = -2000014;
pub const OST_DOORS: i64 = -2000023;
pub const OST_FLOORS: i64 = -2000032;
pub const OST_ROOFS: i64 = -2000035;
pub const OST_CEILINGS: i64 = -2000038;
pub const OST_SKETCH_LINES: i64 = -2000045;
pub const OST_COLUMNS: i64 = -2000100;
pub const OST_GENERIC: i64 = -2000151;
pub const OST_ROOMS: i64 = -2000160;
pub const OST_LEVELS: i64 = -2000240;
pub const OST_MATERIALS: i64 = -2000700;
pub const OST_STRUCTURAL_COLUMNS: i64 = -2001330;
pub const OST_DUCTS: i64 = -2008000;
pub const OST_PIPES: i64 = -2008044;
pub const OST_CABLE_TRAYS: i64 = -2008130;

const NAMES: &[(i64, &str)] = &[
    (-2000011, "Walls"),
    (-2000014, "Windows"),
    (-2000023, "Doors"),
    (-2000032, "Floors"),
    (-2000035, "Roofs"),
    (-2000038, "Ceilings"),
    (-2000045, "Lines: <Sketch>"),
    (-2000051, "Lines"),
    (-2000080, "Furniture"),
    (-2000100, "Columns"),
    (-2000112, "Phases"),
    (-2000120, "Stairs"),
    (-2000123, "Stairs: Supports"),
    (-2000126, "Railings"),
    (-2000151, "Generic Models"),
    (-2000160, "Rooms"),
    (-2000170, "Curtain Panels"),
    (-2000171, "Curtain Wall Mullions"),
    (-2000181, "Walls: Wall Sweeps"),
    (-2000182, "Walls: Reveals"),
    (-2000240, "Levels"),
    (-2000267, "Assemblies"),
    (-2000919, "Stairs: Runs"),
    (-2000920, "Stairs: Landings"),
    (-2000996, "Shaft Openings"),
    (-2000997, "Walls: Rectangular Straight Wall Opening"),
    (-2001000, "Casework"),
    (-2001040, "Electrical Equipment"),
    (-2001060, "Electrical Fixtures"),
    (-2001100, "Furniture Systems"),
    (-2001120, "Lighting Fixtures"),
    (-2001140, "Mechanical Equipment"),
    (-2001160, "Plumbing Fixtures"),
    (-2001180, "Parking"),
    (-2001263, "Site: Pads"),
    (-2001300, "Structural Foundations"),
    (-2001320, "Structural Framing"),
    (-2001327, "Structural Beam Systems"),
    (-2001330, "Structural Columns"),
    (-2001336, "Structural Trusses"),
    (-2001350, "Specialty Equipment"),
    (-2001354, "Structural Stiffeners"),
    (-2001360, "Planting"),
    (-2001370, "Entourage"),
    (-2001392, "Floors: Slab Edges"),
    (-2003200, "Areas"),
    (-2003400, "Mass"),
    (-2006112, "Design Option Sets"),
    (-2006114, "Design Options"),
    (-2008000, "Ducts"),
    (-2008010, "Duct Fittings"),
    (-2008013, "Air Terminals"),
    (-2008020, "Flex Ducts"),
    (-2008044, "Pipes"),
    (-2008049, "Pipe Fittings"),
    (-2008087, "Lighting Devices"),
    (-2008099, "Sprinklers"),
    (-2008126, "Cable Tray Fittings"),
    (-2008128, "Conduit Fittings"),
    (-2008130, "Cable Trays"),
    (-2008132, "Conduits"),
    (-2009000, "Structural Rebar"),
    (-2009030, "Structural Connections"),
];

pub fn name(cat: i64) -> Option<&'static str> {
    NAMES.iter().find(|(c, _)| *c == cat).map(|(_, n)| *n)
}

/// Whether the number is in the range of `BuiltInCategory` ids the reader takes.
pub fn plausible(cat: i64) -> bool {
    (-2_100_000..=-1_990_000).contains(&cat)
}
