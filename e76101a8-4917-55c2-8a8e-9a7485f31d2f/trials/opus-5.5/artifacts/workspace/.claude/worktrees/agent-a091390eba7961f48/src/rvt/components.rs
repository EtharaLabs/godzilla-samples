//! Family instances of the other categories: a box of the record's box in a family of the
//! category (named by its id when the reader has no name for it), and the categories the
//! importer has no reader for, counted.

use super::build::{mm, r3};
use super::cats;
use super::import::Ctx;
use super::notes::Kind;
use super::records::Record;
use crate::json::Value;
use std::collections::{BTreeMap, BTreeSet};

pub const NOTE_NAMED: &str = "comes in as a box of its record's box: its shape, its type and its connectors are not read";
pub const NOTE_UNNAMED: &str = "comes in as a box of its record's box, in a family named by its category's id: its category has no name here, and its shape, its type and its connectors are not read";
pub const FLAT_NAMED: &str = "it has no volume: a flat symbol has no body to import";
pub const FLAT_UNNAMED: &str = "it has no volume, so it has no body to import";
pub const COMPANION: &str =
    "its box is that of an element of a category the reader knows: it is taken as that element's companion, not a second body";

/// The categories that come in as boxes, in the order they come in: (category, the element as
/// the notes name it, the BIMCraft family category).
const BOXES: &[(i64, &str, &str)] = &[
    (-2008049, "pipe fitting", "pipefitting"),
    (-2008010, "duct fitting", "generic"),
    (-2008020, "flex duct", "generic"),
    (-2008013, "air terminal", "generic"),
    (-2008099, "sprinkler", "generic"),
    (-2001160, "plumbing fixture", "plumbing"),
    (-2001140, "mechanical equipment item", "generic"),
    (-2001040, "electrical equipment item", "equipment"),
    (-2001060, "electrical fixture", "generic"),
    (-2001120, "lighting fixture", "lighting"),
    (-2008087, "lighting device", "generic"),
    (-2000151, "generic model", "generic"),
    (-2000080, "furniture item", "furniture"),
    (-2001000, "casework item", "casework"),
    (-2001350, "specialty equipment item", "generic"),
    (-2008126, "cable tray fitting", "generic"),
    (-2008128, "conduit fitting", "generic"),
    (-2001360, "plant", "generic"),
    (-2001370, "entourage item", "generic"),
    (-2001180, "parking item", "generic"),
];

/// The categories other readers take.
const READ: &[i64] = &[
    cats::OST_WALLS,
    cats::OST_WINDOWS,
    cats::OST_DOORS,
    cats::OST_FLOORS,
    cats::OST_ROOFS,
    cats::OST_CEILINGS,
    cats::OST_COLUMNS,
    cats::OST_STRUCTURAL_COLUMNS,
    cats::OST_ROOMS,
    cats::OST_PIPES,
    cats::OST_DUCTS,
    cats::OST_CABLE_TRAYS,
];

/// Placed elements of these are not elements to import (levels are read as levels; sketch lines
/// as the boundaries of what they sketch).
const QUIET: &[i64] = &[cats::OST_LEVELS, cats::OST_SKETCH_LINES];

fn boxed(cat: i64) -> Option<(&'static str, &'static str)> {
    BOXES.iter().find(|(c, _, _)| *c == cat).map(|(_, k, f)| (*k, *f))
}

/// A box as the import writes it (millimetres, rounded): boxes the same so are the same.
fn box_key(b: &[f64; 6]) -> [u64; 6] {
    let mut k = [0u64; 6];
    for i in 0..6 {
        k[i] = mm(b[i]).to_bits();
    }
    k
}

pub fn read(ctx: &mut Ctx) {
    let all = ctx.all_instances();
    let mut cats_seen: BTreeSet<i64> = BTreeSet::new();
    let mut known_boxes: BTreeSet<[u64; 6]> = BTreeSet::new();
    for r in &all {
        if !cats::plausible(r.category) || QUIET.contains(&r.category) {
            continue;
        }
        cats_seen.insert(r.category);
        if READ.contains(&r.category) || boxed(r.category).is_some() {
            if let Some(b) = &r.bbox {
                known_boxes.insert(box_key(b));
            }
        }
    }
    // the categories in the order their elements come in: those of the table in its order, then
    // the others by id
    let named: Vec<i64> = BOXES.iter().map(|(c, _, _)| *c).filter(|c| cats_seen.contains(c)).collect();
    let mut unnamed: Vec<i64> = Vec::new();
    for c in &cats_seen {
        if READ.contains(c) || boxed(*c).is_some() {
            continue;
        }
        if let Some(n) = cats::name(*c) {
            for r in ctx.instances(*c) {
                ctx.notes.no_reader(*c, n, r.id);
            }
        } else {
            unnamed.push(*c);
        }
    }
    let mut fams: BTreeMap<i64, (String, String)> = BTreeMap::new();
    for c in named.into_iter().chain(unnamed) {
        let (kind, fam_name, fam_cat, note, flat) = match boxed(c) {
            Some((k, f)) => (Kind::simple(k), cats::name(c).unwrap_or("").to_string(), f, NOTE_NAMED, FLAT_NAMED),
            None => (
                Kind::new(&format!("category {} element", c), &format!("category {} elements", c)),
                format!("Category {}", c),
                "generic",
                NOTE_UNNAMED,
                FLAT_UNNAMED,
            ),
        };
        let unnamed = boxed(c).is_none();
        for r in ctx.instances(c) {
            match read_one(ctx, r, unnamed, &known_boxes, &fam_name, fam_cat, &mut fams) {
                Ok(true) => ctx.notes.note(&kind, note, r.id),
                Ok(false) => {}
                Err(Some(reason)) => ctx.notes.leave(&kind, reason, r.id),
                Err(None) => ctx.notes.leave(&kind, flat, r.id),
            }
        }
    }
}

/// The family a category's boxes come in as (made the first time), and its type's GUID.
fn family(ctx: &mut Ctx, c: i64, name: &str, fam_cat: &str, fams: &mut BTreeMap<i64, (String, String)>) -> (String, String) {
    if let Some(f) = fams.get(&c) {
        return f.clone();
    }
    let param = |n: &str| jobj! {"name" => n, "kind" => "length", "instance" => true, "value" => 100.0};
    let pt = |x: &str, y: &str| Value::Arr(vec![Value::s(x), Value::s(y)]);
    let form = jobj! {
        "guid" => crate::rand::guid(),
        "plane" => "xy",
        "profile" => Value::Arr(vec![
            pt("-(Width) / 2", "-(Depth) / 2"),
            pt("Width / 2", "-(Depth) / 2"),
            pt("Width / 2", "Depth / 2"),
            pt("-(Width) / 2", "Depth / 2"),
        ]),
        "from" => 0.0,
        "to" => "Height",
    };
    let fv = jobj! {
        "category" => fam_cat,
        "parameters" => Value::Arr(vec![param("Width"), param("Depth"), param("Height")]),
        "types" => jobj! {"Imported" => Value::obj()},
        "forms" => Value::Arr(vec![form]),
    };
    ctx.pr.section_mut("families").insert_sorted(name, fv);
    let fg = ctx.lib_guid("family", name);
    let tg = ctx.lib_guid("family-type", &format!("{}: Imported", name));
    fams.insert(c, (fg.clone(), tg.clone()));
    (fg, tg)
}

/// Ok(true) when it came in; Err(None) when its box has no volume.
fn read_one(
    ctx: &mut Ctx,
    r: &Record,
    unnamed: bool,
    known: &BTreeSet<[u64; 6]>,
    fam_name: &str,
    fam_cat: &str,
    fams: &mut BTreeMap<i64, (String, String)>,
) -> Result<bool, Option<&'static str>> {
    let b = match r.bbox {
        Some(b) => b,
        None => return Ok(false),
    };
    if !(b[3] > b[0] && b[4] > b[1] && b[5] > b[2]) {
        return Err(None);
    }
    if unnamed && known.contains(&box_key(&b)) {
        return Err(Some(COMPANION));
    }
    let bottom = mm(b[2]);
    let level = ctx.level_at(b[2]).ok_or(Some(super::walls::NO_LEVEL))?;
    let (fg, tg) = family(ctx, r.category, fam_name, fam_cat, fams);
    let w = r3(mm(b[3]) - mm(b[0]));
    let d = r3(mm(b[4]) - mm(b[1]));
    let h = r3(mm(b[5]) - mm(b[2]));
    let mut params: Vec<(String, f64)> = Vec::new();
    for (n, x) in [("Width", w), ("Depth", d), ("Height", h)] {
        params.push((ctx.lib_guid("family-parameter", &format!("{}: {}", fam_name, n)), x));
    }
    params.sort_by(|a, c| a.0.cmp(&c.0));
    let mut pm = crate::json::Map::new();
    for (g, x) in params {
        pm.insert(&g, Value::f(x));
    }
    let lev = ctx.levels[level].elevation;
    let v = jobj! {
        "guid" => crate::rand::guid(),
        "category" => "component",
        "family" => fg,
        "type" => tg,
        "level" => ctx.level_guid(level),
        "at" => Value::Arr(vec![Value::f(r3((b[0] + b[3]) / 2.0 * 304.8)), Value::f(r3((b[1] + b[4]) / 2.0 * 304.8))]),
        "angle" => 0.0,
        "offset" => r3(bottom - lev),
        "params" => Value::Obj(pm),
    };
    ctx.add(r.id, "component", v);
    Ok(true)
}
