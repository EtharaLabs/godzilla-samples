//! The serde types `reinforce` reads its parameters into, field by field as the original
//! declares them (the order serde lists them in and reads an array by).

use super::de::{opt, req, Field, Shape, Ty};

pub static BENT: Shape = Shape {
    name: "Bent",
    fields: &[req("count", Ty::Usize), opt("angle", Ty::F64), opt("top", Ty::F64)],
};

/// A beam's row of bars, `bottom` or `top`.
pub static ROW: Shape = Shape {
    name: "Row",
    fields: &[req("count", Ty::Usize), req("diameter", Ty::F64), opt("hook", Ty::Any), opt("bent", Ty::Struct(&BENT))],
};

pub static ENDS: Shape = Shape {
    name: "Ends",
    fields: &[req("length", Ty::F64), req("spacing", Ty::F64)],
};

pub static STIRRUP: Shape = Shape {
    name: "Stirrup",
    fields: &[
        req("diameter", Ty::F64),
        req("spacing", Ty::F64),
        opt("ends", Ty::Struct(&ENDS)),
        opt("hook", Ty::F64),
    ],
};

/// Bars of a diameter at most a spacing apart: a beam's skin, a mesh's layer.
pub static PITCH: Shape = Shape {
    name: "Pitch",
    fields: &[req("diameter", Ty::F64), req("spacing", Ty::F64)],
};

pub static BEAM_ANCHOR: Shape = Shape {
    name: "BeamAnchor",
    fields: &[opt("start", Ty::F64), opt("end", Ty::F64)],
};

pub static JOG: Shape = Shape {
    name: "Jog",
    fields: &[req("by", Ty::F64), req("from_top", Ty::F64), opt("slope", Ty::F64)],
};

pub static COLUMN_BARS: Shape = Shape {
    name: "ColumnBars",
    fields: &[
        req("diameter", Ty::F64),
        opt("x", Ty::Usize),
        opt("y", Ty::Usize),
        opt("count", Ty::Usize),
        opt("hook", Ty::Any),
        opt("jog", Ty::Struct(&JOG)),
    ],
};

pub static TIES: Shape = Shape {
    name: "Ties",
    fields: &[req("diameter", Ty::F64), opt("hook", Ty::F64)],
};

pub static COLUMN_ANCHOR: Shape = Shape {
    name: "ColumnAnchor",
    fields: &[opt("below", Ty::F64), opt("above", Ty::F64)],
};

/// A footing's mesh.
pub static MESH: Shape = Shape {
    name: "Mesh",
    fields: &[opt("x", Ty::Struct(&PITCH)), opt("y", Ty::Struct(&PITCH)), opt("hook", Ty::F64)],
};

/// A floor's mesh, `bottom` or `top`.
pub static GRID: Shape = Shape {
    name: "Grid",
    fields: &[opt("x", Ty::Struct(&PITCH)), opt("y", Ty::Struct(&PITCH)), opt("hook", Ty::F64)],
};

/// The faces of `cover` given one by one.
pub static FACES: Shape = Shape {
    name: "Faces",
    fields: &[opt("top", Ty::F64), opt("bottom", Ty::F64), opt("sides", Ty::F64)],
};

#[allow(dead_code)]
pub const NO_FIELDS: &[Field] = &[];
