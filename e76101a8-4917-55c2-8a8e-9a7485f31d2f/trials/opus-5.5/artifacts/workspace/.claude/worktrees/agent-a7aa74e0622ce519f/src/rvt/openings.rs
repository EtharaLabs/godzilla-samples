//! Doors and windows: the host wall, the hole as the instance's box along the wall, the type by
//! its name entry, neighbours that overlap a little narrowed to fit.

use super::build::{self, mm, r3};
use super::bytes::*;
use super::cats;
use super::import::Ctx;
use super::notes::Kind;
use super::records::Record;
use std::collections::BTreeMap;

/// What became of a wall of the file, for the openings it hosts.
#[derive(Clone, Debug)]
pub enum WallFate {
    In { guid: String, start: [f64; 2], end: [f64; 2], curved: bool, base: f64, top: f64 },
    /// Left out because its type has no layers it could stand in for (a curtain wall).
    Curtain,
    Out,
}

pub const NOTE_NARROWED: &str =
    "it overlaps a neighbour in its wall by up to a tenth of its width, which BIMCraft does not allow: narrowed to fit";
pub const NOTE_OVERRUN: &str = "its box overruns its wall, and it comes in as far as the wall goes";

struct Hole {
    rid: u64,
    cat: &'static str,
    type_id: Option<u64>,
    wall: u64,
    guid: String,
    length: f64,
    offset: f64,
    width: f64,
    height: f64,
    sill: f64,
    notes: Vec<&'static str>,
}

/// A family type's name: its name entry (the type's id, a counted name, and from 2024 the category).
pub fn symbol_name(ctx: &Ctx, id: u64, cat: i64) -> Option<String> {
    let doc = ctx.doc;
    let wide = doc.wide();
    for pi in doc.parts_newest_first() {
        let d = &doc.parts[pi].data;
        let key: Vec<u8> = if wide {
            id.to_le_bytes().to_vec()
        } else {
            let mut k = vec![1u8, 0, 0, 0];
            k.extend_from_slice(&(id as u32).to_le_bytes());
            k
        };
        let mut q = 0;
        let mut found: Vec<String> = Vec::new();
        while let Some(p) = find(d, &key, q, d.len()) {
            q = p + 1;
            let s = p + key.len();
            if let Some((name, e)) = super::data::counted(d, s, 256) {
                if wide && rd_i64(d, e) != Some(cat) {
                    continue;
                }
                if let Some(n) = super::data::usable_name(&name, doc.release) {
                    if !found.contains(&n) {
                        found.push(n);
                    }
                }
            }
        }
        // a symbol with two names has none the reader can trust
        if found.len() == 1 {
            return found.pop();
        }
        if !found.is_empty() {
            return None;
        }
    }
    None
}

/// The one family symbol of the category its list names that has a name entry.
pub fn symbol(ctx: &Ctx, r: &Record, cat: i64) -> (Option<u64>, Option<String>) {
    let mut named: Vec<(u64, String)> = Vec::new();
    let mut syms: Vec<u64> = Vec::new();
    for id in &r.refs {
        if ctx.is_type(cat, *id) {
            if !syms.contains(id) {
                syms.push(*id);
            }
            if let Some(n) = symbol_name(ctx, *id, cat) {
                if !named.iter().any(|(i, _)| i == id) {
                    named.push((*id, n));
                }
            }
        }
    }
    if named.len() == 1 {
        return (Some(named[0].0), Some(named[0].1.clone()));
    }
    if syms.len() == 1 {
        return (Some(syms[0]), None);
    }
    (None, None)
}

pub fn read(ctx: &mut Ctx, fates: &BTreeMap<u64, WallFate>) {
    let mut holes: Vec<Hole> = Vec::new();
    for (cat, word) in [(cats::OST_DOORS, "door"), (cats::OST_WINDOWS, "window")] {
        let kind = Kind::simple(word);
        for r in ctx.instances(cat) {
            match read_one(ctx, r, cat, word, fates) {
                Ok(Some(h)) => holes.push(h),
                Ok(None) => {}
                Err(reason) => ctx.notes.leave(&kind, &reason, r.id),
            }
        }
    }
    // neighbours in a wall that overlap by up to a tenth of each one's width are narrowed
    let n = holes.len();
    for i in 0..n {
        for j in 0..n {
            if i == j || holes[i].guid != holes[j].guid {
                continue;
            }
            let (a0, a1) = (holes[i].offset - holes[i].width / 2.0, holes[i].offset + holes[i].width / 2.0);
            let (b0, b1) = (holes[j].offset - holes[j].width / 2.0, holes[j].offset + holes[j].width / 2.0);
            if !(holes[i].offset <= holes[j].offset && a1 > b0 + 1e-9) {
                continue;
            }
            let ov = a1.min(b1) - a0.max(b0);
            if ov <= 1e-9 || ov > holes[i].width / 10.0 + 1e-9 || ov > holes[j].width / 10.0 + 1e-9 {
                continue;
            }
            let h = ov / 2.0;
            holes[i].width -= h;
            holes[i].offset -= h / 2.0;
            holes[j].width -= h;
            holes[j].offset += h / 2.0;
            if !holes[i].notes.contains(&NOTE_NARROWED) {
                holes[i].notes.push(NOTE_NARROWED);
            }
            if !holes[j].notes.contains(&NOTE_NARROWED) {
                holes[j].notes.push(NOTE_NARROWED);
            }
        }
    }
    let opening = Kind::simple("opening");
    for h in holes {
        for n in &h.notes {
            ctx.notes.note(&opening, n, h.rid);
        }
        let catname = if h.cat == "door" { "door" } else { "window" };
        let tname = match h.type_id.and_then(|t| symbol_name(ctx, t, if h.cat == "door" { cats::OST_DOORS } else { cats::OST_WINDOWS })) {
            Some(n) => n,
            None => format!("Imported {}", catname),
        };
        let tv = jobj! {"width" => r3(h.width), "height" => h.height, "sill" => r3(h.sill)};
        let name = build::add_type(&mut ctx.pr, catname, &tname, tv);
        let tg = ctx.lib_guid(&format!("type:{}", catname), &name);
        let v = jobj! {
            "guid" => crate::rand::guid(),
            "category" => catname,
            "type" => tg,
            "host" => h.guid.as_str(),
            "offset" => r3(h.offset),
            "sill" => r3(h.sill),
            "mark" => "",
            "flip_facing" => false,
            "flip_hand" => false,
        };
        let _ = (h.wall, h.length);
        ctx.add(h.rid, h.cat, v);
    }
}

fn read_one(ctx: &mut Ctx, r: &Record, cat: i64, word: &'static str, fates: &BTreeMap<u64, WallFate>) -> Result<Option<Hole>, String> {
    let b = match r.bbox {
        Some(b) => b,
        None => return Ok(None),
    };
    // a skylight: set in a roof or a floor
    let in_slab = r.refs.iter().any(|id| ctx.is_instance(cats::OST_ROOFS, *id) || ctx.is_instance(cats::OST_FLOORS, *id));
    if in_slab {
        return Err(format!(
            "it is set in a roof or a floor (a skylight), and BIMCraft's {}s stand in walls",
            word
        ));
    }
    let walls: Vec<u64> = r.refs.iter().copied().filter(|id| ctx.is_instance(cats::OST_WALLS, *id)).collect();
    if walls.is_empty() {
        return Err("its record names no wall".into());
    }
    // the host: the nearest below the opening's own id that it fits in, else the nearest named,
    // skipping curtain walls
    let usable: Vec<u64> = walls.iter().copied().filter(|w| !matches!(fates.get(w), Some(WallFate::Curtain))).collect();
    if usable.is_empty() {
        return Err("its host is a curtain wall, which BIMCraft has no element for".into());
    }
    let (cx, cy) = (mm((b[0] + b[3]) / 2.0), mm((b[1] + b[4]) / 2.0));
    let fits = |w: u64| -> bool {
        match fates.get(&w) {
            Some(WallFate::In { start, end, curved: false, .. }) => {
                let (dx, dy) = (end[0] - start[0], end[1] - start[1]);
                let l = (dx * dx + dy * dy).sqrt();
                if l == 0.0 {
                    return false;
                }
                let t = ((cx - start[0]) * dx + (cy - start[1]) * dy) / l;
                t >= 0.0 && t <= l
            }
            _ => false,
        }
    };
    let mut below: Vec<u64> = usable.iter().copied().filter(|w| *w < r.id).collect();
    below.sort();
    let host = match below.iter().rev().find(|w| fits(**w)) {
        Some(w) => *w,
        None => *usable.iter().min_by_key(|w| (**w as i128 - r.id as i128).abs()).unwrap(),
    };
    let (guid, start, end, curved, base, top) = match fates.get(&host) {
        Some(WallFate::In { guid, start, end, curved, base, top }) => (guid.clone(), *start, *end, *curved, *base, *top),
        _ => return Err(format!("its host wall {} was left out", host)),
    };
    if curved {
        return Err(format!("its host wall {} is curved, and a curved wall's box gives no width", host));
    }
    let (dx, dy) = (end[0] - start[0], end[1] - start[1]);
    let len = (dx * dx + dy * dy).sqrt();
    let (ux, uy) = (dx / len, dy / len);
    let ex = mm(b[3]) - mm(b[0]);
    let ey = mm(b[4]) - mm(b[1]);
    let (c, s) = (ux.abs(), uy.abs());
    let width = if s < 1e-9 {
        ex
    } else if c < 1e-9 {
        ey
    } else {
        let det = c * c - s * s;
        if det.abs() < 0.1 {
            return Err(format!(
                "its host wall {} runs at an angle, and the box of a door or window in it gives no width",
                host
            ));
        }
        let w = (ex * c - ey * s) / det;
        let d = (ey * c - ex * s) / det;
        if w <= 0.0 || d < 0.0 {
            return Err(format!(
                "its host wall {} runs at an angle, and the box of a door or window in it gives no width",
                host
            ));
        }
        w
    };
    let mut notes: Vec<&'static str> = Vec::new();
    let mut offset = (cx - start[0]) * ux + (cy - start[1]) * uy;
    let bottom = mm(b[2]);
    let topz = mm(b[5]);
    if bottom >= top {
        return Err(format!("its host wall {} leaves no room for it", host));
    }
    let mut height = mm(b[5] - b[2]);
    let mut overrun = false;
    if topz > top + 1e-9 {
        height = top - bottom;
        overrun = true;
    }
    if offset - width / 2.0 < -1e-9 {
        offset = width / 2.0;
        overrun = true;
    } else if offset + width / 2.0 > len + 1e-9 {
        offset = len - width / 2.0;
        overrun = true;
    }
    if overrun {
        notes.push(NOTE_OVERRUN);
    }
    let mut sill = bottom - base;
    if sill < 0.0 && sill > -2.0 {
        sill = 0.0;
    }
    let (type_id, _) = symbol(ctx, r, cat);
    Ok(Some(Hole {
        rid: r.id,
        cat: word,
        type_id,
        wall: host,
        guid,
        length: len,
        offset,
        width,
        height,
        sill,
        notes,
    }))
}
