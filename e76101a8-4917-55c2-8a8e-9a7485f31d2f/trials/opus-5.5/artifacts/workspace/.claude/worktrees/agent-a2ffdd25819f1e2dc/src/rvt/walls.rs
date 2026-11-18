//! Walls: the location line or arc, the side of the exterior, levels and height from the
//! reference list and the box, the type and its layers.

use super::build::{self, mm, r3};
use super::bytes::*;
use super::cats;
use super::curves::{self, Curve};
use super::import::Ctx;
use super::notes::Kind;
use super::records::Record;
use super::types::{self, Layers};
use super::openings::WallFate;
use crate::json::Value;
use std::collections::BTreeMap;

pub const NOTE_NO_LINE: &str = "its record holds no location line (a family instance of the wall category): it comes in along the long side of its own box, as a column comes in as the rectangle of its box";
pub const NOTE_CURTAIN: &str = "its type has no layers (a curtain wall or a storefront): it comes in as the plane its own box gives, and the panels and mullions are not read";
pub const NOTE_SIDE: &str = "the data does not say which side is the exterior: kept as drawn";
pub const NO_LEVEL: &str = "it stands on no level";

/// Where a wall comes in: its line in plan (mm), arc sweep (degrees) if curved.
#[derive(Clone, Debug)]
pub struct Placed {
    pub rid: u64,
    pub start: [f64; 2],
    pub end: [f64; 2],
    pub arc: Option<f64>,
    pub level: usize,
    pub top: Option<usize>,
    pub height: f64,
    pub base_offset: f64,
    /// The type's key: its id in the file, or none.
    pub type_id: Option<u64>,
    pub layers: Option<Vec<types::Layer>>,
    /// The thickness a stand-in takes from the box (mm).
    pub box_thickness: f64,
}

/// The side of the exterior: Some(true) when the first layer is to the right of the line.
fn flip(ctx: &Ctx, d: &[u8], curve_end: usize) -> Option<bool> {
    let mk = [0xffu8, 0xff, 0xff, 0xff, 1, 0, 0, 0];
    if d.get(curve_end..curve_end + 8) != Some(&mk[..]) {
        return None;
    }
    let p = curve_end + 8 + 4 + if ctx.doc.release >= 2021 { 4 } else { 0 };
    match rd_u32(d, p)? {
        0 => Some(false),
        1 => Some(true),
        _ => None,
    }
}

/// The thickness the box gives a straight wall along its line (mm), from the extent across it.
fn box_thickness(b: &[f64; 6], dir: [f64; 2], len: f64) -> f64 {
    let ex = (b[3] - b[0]) * 304.8;
    let ey = (b[4] - b[1]) * 304.8;
    let (c, s) = (dir[0].abs(), dir[1].abs());
    if c >= s {
        if c == 0.0 {
            return 0.0;
        }
        (ey - len * s) / c
    } else {
        (ex - len * c) / s
    }
}

pub fn read(ctx: &mut Ctx) -> BTreeMap<u64, WallFate> {
    let kind = Kind::simple("wall");
    let mut placed: Vec<Placed> = Vec::new();
    let mut fates: BTreeMap<u64, WallFate> = BTreeMap::new();
    for r in ctx.instances(cats::OST_WALLS) {
        match read_one(ctx, r, &kind) {
            Ok(p) => placed.push(p),
            Err(curtain) => {
                ctx.gone.insert((r.id, "wall"));
                fates.insert(r.id, if curtain { WallFate::Curtain } else { WallFate::Out });
            }
        }
    }
    // the types: those with layers are the file's; stand-ins take the box's thickness
    let mut thick_by_type: std::collections::BTreeMap<Option<u64>, Vec<f64>> = std::collections::BTreeMap::new();
    for p in &placed {
        if p.layers.is_none() {
            let v = thick_by_type.entry(p.type_id).or_default();
            if !v.iter().any(|t| (*t - p.box_thickness).abs() < 1e-9) {
                v.push(p.box_thickness);
            }
        }
    }
    for p in placed {
        let tname = type_name(ctx, &p, &thick_by_type);
        let tv = match &p.layers {
            Some(ls) => layers_value(ctx, ls),
            None => {
                let t = r3(p.box_thickness);
                jobj! {"thickness" => t, "layers" => Value::Arr(vec![jobj!{"guid" => crate::rand::guid(), "function" => "structure", "material" => "", "thickness" => t}])}
            }
        };
        let name = build::add_type(&mut ctx.pr, "wall", &tname, tv);
        let tguid = ctx.lib_guid("type:wall", &name);
        let mut v = jobj! {
            "guid" => crate::rand::guid(),
            "category" => "wall",
            "type" => tguid,
            "level" => ctx.level_guid(p.level),
            "start" => Value::Arr(vec![Value::f(p.start[0]), Value::f(p.start[1])]),
            "end" => Value::Arr(vec![Value::f(p.end[0]), Value::f(p.end[1])]),
            "top_level" => match p.top { Some(t) => ctx.level_guid(t), None => Value::Null },
            "height" => p.height,
            "base_offset" => p.base_offset,
        };
        if let Some(a) = p.arc {
            v.set("arc", Value::f(a));
        }
        let g = v.get("guid").and_then(|g| g.as_str()).unwrap_or("").to_string();
        let base = ctx.levels[p.level].elevation + p.base_offset;
        fates.insert(
            p.rid,
            WallFate::In { guid: g, start: p.start, end: p.end, curved: p.arc.is_some(), base, top: base + p.height },
        );
        ctx.add(p.rid, "wall", v);
    }
    fates
}

fn layers_value(ctx: &Ctx, ls: &[types::Layer]) -> Value {
    let mut arr = Vec::new();
    let mut total = 0.0;
    for l in ls {
        let t = mm(l.width);
        total += l.width;
        arr.push(jobj! {
            "guid" => crate::rand::guid(),
            "function" => types::function_name(l.function).unwrap_or("structure"),
            "material" => ctx.material_guid(l.material, cats::OST_WALLS),
            "thickness" => t,
        });
    }
    jobj! {"thickness" => mm(total), "layers" => Value::Arr(arr)}
}

fn type_name(ctx: &Ctx, p: &Placed, thick: &std::collections::BTreeMap<Option<u64>, Vec<f64>>) -> String {
    let fmt = |t: f64| format!("{}", r3(t));
    match p.type_id {
        None => format!("Imported - {}mm", fmt(p.box_thickness)),
        Some(tid) => {
            let has_data = ctx.data(tid).is_some();
            let name = ctx.type_name(tid);
            match &p.layers {
                Some(ls) => match name {
                    Some(n) => n,
                    None => {
                        let total: f64 = ls.iter().map(|l| l.width).sum();
                        format!("Imported - {}mm", fmt(total * 304.8))
                    }
                },
                None => {
                    let base = match name {
                        Some(n) => n,
                        None => {
                            let _ = has_data;
                            "Imported".to_string()
                        }
                    };
                    let several = thick.get(&p.type_id).map(|v| v.len() > 1).unwrap_or(false);
                    if several {
                        format!("{} - {}mm", base, fmt(p.box_thickness))
                    } else {
                        base
                    }
                }
            }
        }
    }
}

/// The wall as it comes in, or (when it does not) whether it was left out for its type.
fn read_one(ctx: &mut Ctx, r: &Record, kind: &Kind) -> Result<Placed, bool> {
    let mut notes: Vec<&'static str> = Vec::new();
    match read_wall(ctx, r, &mut notes) {
        Ok(Some(p)) => {
            for n in notes {
                ctx.notes.note(kind, n, r.id);
            }
            Ok(p)
        }
        Ok(None) => Err(false),
        Err(reason) => {
            ctx.notes.leave(kind, &reason, r.id);
            Err(reason.starts_with("its type"))
        }
    }
}

/// A wall as it comes in, none for a record with no wall to read, or why it is left out.
fn read_wall(ctx: &mut Ctx, r: &Record, notes: &mut Vec<&'static str>) -> Result<Option<Placed>, String> {
    let b = match r.bbox {
        Some(b) => b,
        None => return Ok(None),
    };
    if !b.iter().all(|x| x.is_finite()) {
        return Ok(None);
    }
    // a box with no volume has no wall to read
    if !(b[3] > b[0] && b[4] > b[1] && b[5] > b[2]) {
        return Ok(None);
    }
    let bottom = mm(b[2]);
    let topz = mm(b[5]);
    let level = match ctx.base_level(&r.refs, b[2]) {
        Some(l) => l,
        None => return Err(NO_LEVEL.into()),
    };
    let found = ctx.first_data(r.id, |d| curves::first(d).map(|c| (d, c)));
    let data = found.map(|(d, _)| d);
    let curve = found.map(|(_, c)| c);
    let mut start;
    let mut end;
    let mut arc = None;
    let mut straight_dir = [1.0, 0.0];
    let len_mm;
    let mut from_box = false;
    let mut side_unknown = false;
    match curve {
        Some((Curve::Line(l), ce)) => {
            if (l.start[2] - l.end[2]).abs() > 1e-9 || l.dir[2].abs() > 1e-9 {
                return Err("its location line is not level".into());
            }
            start = [mm(l.start[0]), mm(l.start[1])];
            end = [mm(l.end[0]), mm(l.end[1])];
            let dx = l.end[0] - l.start[0];
            let dy = l.end[1] - l.start[1];
            let n = (dx * dx + dy * dy).sqrt();
            len_mm = n * 304.8;
            if n > 0.0 {
                straight_dir = [dx / n, dy / n];
            }
            match flip(ctx, data.unwrap(), ce) {
                Some(true) => std::mem::swap(&mut start, &mut end),
                Some(false) => {}
                None => side_unknown = true,
            }
        }
        Some((Curve::Arc(a), ce)) => {
            let n = a.normal();
            if n[0].abs() > 1e-9 || n[1].abs() > 1e-9 {
                return Err("its location arc is not in plan".into());
            }
            let s = a.start();
            let e = a.end();
            start = [mm(s[0]), mm(s[1])];
            end = [mm(e[0]), mm(e[1])];
            let mut sweep = (a.a1 - a.a0).to_degrees();
            if n[2] < 0.0 {
                sweep = -sweep;
            }
            len_mm = 0.0;
            match flip(ctx, data.unwrap(), ce) {
                Some(true) => {
                    std::mem::swap(&mut start, &mut end);
                    sweep = -sweep;
                }
                Some(false) => {}
                None => side_unknown = true,
            }
            arc = Some(build::r6(sweep));
        }
        None => {
            // along the long side of the box, through its middle
            let (x0, y0, x1, y1) = (mm(b[0]), mm(b[1]), mm(b[3]), mm(b[4]));
            if x1 - x0 >= y1 - y0 {
                let y = r3((b[1] + b[4]) / 2.0 * 304.8);
                start = [x0, y];
                end = [x1, y];
                len_mm = x1 - x0;
            } else {
                let x = r3((b[0] + b[3]) / 2.0 * 304.8);
                start = [x, y0];
                end = [x, y1];
                len_mm = y1 - y0;
                straight_dir = [0.0, 1.0];
            }
            from_box = true;
        }
    }
    let base_elev = ctx.levels[level].elevation;
    let top = ctx.top_level(&r.refs, level, b[5]);
    let height = r3(topz - bottom);
    let base_offset = r3(bottom - base_elev);
    // the type
    let type_id = ctx.one_type(r, cats::OST_WALLS);
    let layers = match type_id {
        Some(t) => ctx.type_layers(t),
        None => Layers::None,
    };
    let tname_for_msg = type_id.and_then(|t| ctx.type_name(t));
    let no_layers_msg = || match &tname_for_msg {
        Some(n) => format!("its type '{}' has no layers the reader can read", n),
        None => "its type has no layers the reader can read".to_string(),
    };
    let mut box_t = 0.0;
    let layers = match layers {
        Layers::Read(ls) => {
            // a stand-in's one layer has no side, and its line is its box's anyway
            if from_box {
                notes.push(NOTE_NO_LINE);
            }
            if side_unknown {
                notes.push(NOTE_SIDE);
            }
            Some(ls)
        }
        Layers::Thin => return Err(no_layers_msg()),
        Layers::None => {
            if arc.is_some() {
                return Err(no_layers_msg());
            }
            box_t = box_thickness(&b, straight_dir, len_mm);
            if !(box_t >= 25.0) {
                return Err(no_layers_msg());
            }
            notes.push(NOTE_CURTAIN);
            None
        }
    };
    Ok(Some(Placed {
        rid: r.id,
        start,
        end,
        arc,
        level,
        top,
        height,
        base_offset,
        type_id,
        layers,
        box_thickness: box_t,
    }))
}
