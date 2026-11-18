//! Reading IFC2x3 and IFC4 files into a project.

use super::import_build::{self as build, LibGuids};
use super::import_geom as geom;
use super::import_model::{guid_of_global_id, Model};
use super::step;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;
use std::collections::{BTreeMap, BTreeSet};

/// A level of the project as the import knows it.
#[derive(Clone, Debug)]
pub struct Lvl {
    /// The storey's entity, if it came from one.
    pub ent: Option<u64>,
    pub name: String,
    pub elevation: f64,
    pub guid: String,
}

/// An element that came in.
#[derive(Clone, Debug)]
pub struct Made {
    pub id: u64,
    pub guid: String,
    pub cat: String,
}

pub struct Ctx {
    pub m: Model,
    pub pr: Project,
    pub path: String,
    pub levels: Vec<Lvl>,
    pub skipped: Vec<String>,
    /// The file's entities a pass has taken (made into an element, left out with why, or read
    /// as a part of another).
    pub handled: BTreeSet<u64>,
    /// Values a moved model leaves where they are (an element's id and key): what came from no
    /// geometry of the file (a room's point when it has no body, a loft's outlines), a bar's path.
    pub fixed: BTreeSet<(u64, &'static str)>,
    /// The file's entities that came in, and what they became.
    pub made: BTreeMap<u64, Made>,
    pub used_guids: BTreeSet<String>,
    pub lib: LibGuids,
    /// What later passes need of the walls: entity → its measured line.
    pub walls: BTreeMap<u64, super::import_walls::WallLine>,
    /// The types made so far: (category, name, values) → the name it has.
    pub type_names: super::import_types::TypeNames,
    /// What each kind's pass keeps for the later ones (each module owns its own).
    pub slabs: super::import_slabs::State,
    pub roofs: super::import_roofs::State,
    pub structure: super::import_structure::State,
    pub circulation: super::import_circulation::State,
    pub components: super::import_components::State,
    pub params: super::import_params::State,
}

impl Ctx {
    /// The GUID an entity comes in with: its GlobalId's, unless it is no GUID or one already
    /// taken; then a new one.
    pub fn guid_for(&mut self, ent: u64) -> String {
        let g = self.m.get(ent).and_then(|e| e.p(0).str()).and_then(guid_of_global_id);
        let g = match g {
            Some(g) if !self.used_guids.contains(&g) => g,
            _ => crate::rand::guid(),
        };
        self.used_guids.insert(g.clone());
        g
    }

    /// Adds an element; returns its project id.
    pub fn add(&mut self, ent: u64, v: Value) -> u64 {
        let id = self.pr.alloc_id();
        let g = v.get("guid").and_then(|g| g.as_str()).unwrap_or("").to_string();
        let cat = v.get("category").and_then(|c| c.as_str()).unwrap_or("").to_string();
        self.pr.elements.insert(id, v);
        self.made.insert(ent, Made { id, guid: g, cat });
        self.handled.insert(ent);
        id
    }

    /// Says an element was left out, and why.
    pub fn skip(&mut self, ent: u64, why: &str) {
        let line = self.describe(ent);
        self.skipped.push(format!("{}: {}", line, why));
        self.handled.insert(ent);
    }

    /// `IFCWALL #39 'W'`: an element as the reply names it.
    pub fn describe(&self, ent: u64) -> String {
        let class = self.m.class(ent).to_string();
        match self.m.name(ent) {
            Some(n) => format!("{} #{} '{}'", class, ent, n),
            None => format!("{} #{}", class, ent),
        }
    }

    pub fn type_guid(&mut self, cat: &str, name: &str) -> String {
        let kind = build::type_kind(cat);
        self.lib.get(&self.pr, &kind, name)
    }

    pub fn level_guid(&self, i: usize) -> Value {
        Value::s(&self.levels[i].guid)
    }

    /// The level an element stands on: its storey's, else the highest at or below `z`, else the
    /// lowest.
    pub fn level_of(&self, ent: u64, z: f64) -> usize {
        if let Some(s) = self.m.container(ent) {
            if let Some(i) = self.levels.iter().position(|l| l.ent == Some(s)) {
                return i;
            }
        }
        self.level_at(z)
    }

    /// The highest level at or below `z` (within a millimetre), else the lowest.
    pub fn level_at(&self, z: f64) -> usize {
        let mut best: Option<usize> = None;
        for (i, l) in self.levels.iter().enumerate() {
            if l.elevation <= z + 1.0 {
                best = Some(i);
            }
        }
        best.unwrap_or(0)
    }

    /// A level whose elevation is at `z` (within a millimetre), above level `base`.
    pub fn level_at_top(&self, base: usize, z: f64) -> Option<usize> {
        for (i, l) in self.levels.iter().enumerate() {
            if i != base && (l.elevation - z).abs() <= 1.0 && l.elevation > self.levels[base].elevation {
                return Some(i);
            }
        }
        None
    }
}

fn file_stem(path: &str) -> String {
    std::path::Path::new(path).file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default()
}

/// Imports an IFC file as a new project into the session (what `run x.ifc`, `convert` and
/// `open` do); returns the reply `run` prints. An error is what follows `open: `.
pub fn import(s: &mut Session, path: &str) -> Result<Value, String> {
    let bytes = std::fs::read(path).map_err(|e| format!("{}: {}", path, crate::commands::io_err(&e)))?;
    let (pr, reply) = read(&bytes, path)?;
    s.project = pr;
    s.now_phase = None;
    s.now_option = None;
    s.path = None;
    s.undo.clear();
    s.redo.clear();
    Ok(reply)
}

/// Reads an IFC file's bytes into a project, and the reply an import makes.
pub fn read(bytes: &[u8], path: &str) -> Result<(Project, Value), String> {
    let f = step::parse(bytes).map_err(|e| format!("{}: {}", path, e))?;
    let schema = f.schema();
    if schema.is_empty() {
        return Err(format!("{}: this STEP file is in no schema, not IFC", path));
    }
    if !schema.starts_with("IFC") {
        return Err(format!("{}: this STEP file is in {}, not IFC", path, schema));
    }
    let project = f.entities.iter().find(|(_, e)| e.name == "IFCPROJECT").map(|(id, _)| *id);
    let project = match project {
        Some(p) => p,
        None => return Err(format!("{}: it has no IfcProject", path)),
    };
    let mut m = Model::new(f, schema.clone());
    m.read_units(project);
    let name = match m.name(project).map(|n| n.trim().to_string()) {
        Some(n) if !n.is_empty() => n,
        _ => file_stem(path),
    };
    let pr = build::new_project(&name);
    let mut ctx = Ctx {
        m,
        pr,
        path: path.to_string(),
        levels: Vec::new(),
        skipped: Vec::new(),
        handled: BTreeSet::new(),
        fixed: BTreeSet::new(),
        made: BTreeMap::new(),
        used_guids: BTreeSet::new(),
        lib: LibGuids::default(),
        walls: BTreeMap::new(),
        type_names: BTreeMap::new(),
        slabs: Default::default(),
        roofs: Default::default(),
        structure: Default::default(),
        circulation: Default::default(),
        components: Default::default(),
        params: Default::default(),
    };
    levels(&mut ctx);
    elements(&mut ctx)?;
    let moved = move_near_origin(&mut ctx);
    build::renumber(&mut ctx.pr, &ctx.lib);
    let reply = reply(&ctx, &schema, &name, path, moved);
    Ok((ctx.pr, reply))
}

/// The storeys as levels, from the lowest up (ties in the file's order), named apart.
fn levels(ctx: &mut Ctx) {
    let mut found: Vec<(f64, u64, String)> = Vec::new();
    for id in ctx.m.of("IFCBUILDINGSTOREY").to_vec() {
        let e = ctx.m.get(id).unwrap();
        let elev = match e.p(5).r() {
            Some(lp) if ctx.m.get(lp).map(|x| x.name == "IFCLOCALPLACEMENT").unwrap_or(false) => geom::placement(&ctx.m, lp).t[2],
            _ => e.p(9).num().map(|x| x * ctx.m.scale).filter(|x| x.is_finite()).unwrap_or(0.0),
        };
        let name = e.p(2).str().map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).unwrap_or_else(|| "Level".to_string());
        found.push((build::r3(elev), id, name));
    }
    found.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal).then(a.1.cmp(&b.1)));
    let mut used: Vec<String> = Vec::new();
    for (elev, id, name) in found {
        let mut n = name.clone();
        let mut k = 2;
        while used.contains(&n) {
            n = format!("{} ({})", name, k);
            k += 1;
        }
        used.push(n.clone());
        let g = ctx.guid_for(id);
        let v = crate::jobj! {
            "guid" => g.as_str(),
            "category" => "level",
            "name" => n.as_str(),
            "elevation" => elev,
            "view_range" => crate::jobj!{"top" => Value::Null, "cut" => 1200.0, "bottom" => 0.0, "depth" => 0.0},
        };
        ctx.add(id, v);
        ctx.levels.push(Lvl { ent: Some(id), name: n, elevation: elev, guid: g });
    }
    if ctx.levels.is_empty() {
        let g = crate::rand::guid();
        let v = crate::jobj! {
            "guid" => g.as_str(),
            "category" => "level",
            "name" => "Level 1",
            "elevation" => 0.0,
            "view_range" => crate::jobj!{"top" => Value::Null, "cut" => 1200.0, "bottom" => 0.0, "depth" => 0.0},
        };
        let id = ctx.pr.alloc_id();
        ctx.pr.elements.insert(id, v);
        ctx.levels.push(Lvl { ent: None, name: "Level 1".into(), elevation: 0.0, guid: g });
    }
}

/// The elements, kind by kind (an error is one that stops the import).
fn elements(ctx: &mut Ctx) -> Result<(), String> {
    // the library's materials coloured as the file colours them, then the passes in the order
    // the original makes the elements (and so numbers them)
    super::import_types::library_colours(ctx);
    super::import_walls::walls(ctx);
    super::import_slabs::floors(ctx);
    super::import_slabs::ceilings(ctx);
    super::import_roofs::roofs(ctx)?;
    super::import_slabs::shafts(ctx);
    super::import_circulation::masses(ctx);
    super::import_structure::columns(ctx);
    super::import_structure::runs(ctx);
    super::import_components::components(ctx)?;
    super::import_circulation::stairs(ctx);
    super::import_circulation::railings(ctx);
    super::import_circulation::separators(ctx);
    super::import_structure::rebar(ctx);
    super::import_walls::openings(ctx)?;
    super::import_rooms::rooms(ctx);
    super::import_structure::grids(ctx);
    // what comes after every element is in: walls attached to roofs, parameters and phases
    super::import_roofs::attach(ctx);
    super::import_params::params(ctx);
    unhandled(ctx);
    Ok(())
}

/// What the storeys hold that no pass took: so many of each class, with why.
fn unhandled(ctx: &mut Ctx) {
    let mut counts: BTreeMap<String, usize> = BTreeMap::new();
    for el in ctx.m.contained_in.keys() {
        if ctx.handled.contains(el) {
            continue;
        }
        let c = ctx.m.class(*el);
        if c.is_empty() {
            continue;
        }
        *counts.entry(c.to_string()).or_insert(0) += 1;
    }
    for (c, n) in counts {
        ctx.skipped.push(format!("{} {}: BIMCraft has no element for {}", n, c, if n == 1 { "it" } else { "them" }));
    }
}

/// A model at map coordinates moved near the origin: by the lowest corner of where the storeys'
/// elements are placed, in whole metres down, when that is further than 100 km away.
fn move_near_origin(ctx: &mut Ctx) -> Value {
    let mut lo = [f64::INFINITY, f64::INFINITY];
    for el in ctx.m.contained_in.keys() {
        let lp = match ctx.m.get(*el).and_then(|e| e.p(5).r()) {
            Some(r) if ctx.m.class(r) == "IFCLOCALPLACEMENT" => r,
            _ => continue,
        };
        let t = geom::placement(&ctx.m, lp).t;
        lo[0] = lo[0].min(t[0]);
        lo[1] = lo[1].min(t[1]);
    }
    if !lo[0].is_finite() || !(lo[0].abs() > 1e8 || lo[1].abs() > 1e8) {
        return Value::Null;
    }
    let (dx, dy) = (-(lo[0] / 1000.0).floor() * 1000.0, -(lo[1] / 1000.0).floor() * 1000.0);
    let shift = |p: &mut Value| {
        if let Some(a) = p.as_arr_mut() {
            if a.len() >= 2 {
                if let (Some(x), Some(y)) = (a[0].as_f64(), a[1].as_f64()) {
                    a[0] = Value::f(build::r3(x + dx));
                    a[1] = Value::f(build::r3(y + dy));
                }
            }
        }
    };
    let shift_all = |v: &mut Value| {
        if let Value::Arr(a) = v {
            for p in a.iter_mut() {
                shift(p);
            }
        }
    };
    let fixed = ctx.fixed.clone();
    for (id, e) in ctx.pr.elements.iter_mut() {
        let keep = |k: &str| fixed.contains(&(*id, k)) || fixed.iter().any(|(i, kk)| i == id && *kk == k);
        for k in ["start", "end", "at", "point"] {
            if keep(k) {
                continue;
            }
            if let Some(p) = e.get_mut(k) {
                shift(p);
            }
        }
        for k in ["boundary", "path", "arrow", "top"] {
            if keep(k) {
                continue;
            }
            if let Some(v) = e.get_mut(k) {
                shift_all(v);
            }
        }
        for k in ["openings", "courtyards"] {
            if let Some(Value::Arr(ls)) = e.get_mut(k) {
                for l in ls.iter_mut() {
                    shift_all(l);
                }
            }
        }
        if let Some(sh) = e.get_mut("shape") {
            if let Some(Value::Arr(ps)) = sh.get_mut("points") {
                for pt in ps.iter_mut() {
                    if let Some(a) = pt.get_mut("at") {
                        shift(a);
                    }
                }
            }
            if let Some(Value::Arr(ls)) = sh.get_mut("lines") {
                for l in ls.iter_mut() {
                    for k in ["a", "b"] {
                        if let Some(a) = l.get_mut(k) {
                            shift(a);
                        }
                    }
                }
            }
        }
        if let Some(x) = e.get_mut("extrusion") {
            if let Some(l) = x.get_mut("line") {
                shift_all(l);
            }
        }
    }
    Value::Arr(vec![Value::f(dx), Value::f(dy)])
}

fn reply(ctx: &Ctx, schema: &str, name: &str, path: &str, moved: Value) -> Value {
    let mut counts: BTreeMap<String, u64> = BTreeMap::new();
    for e in ctx.pr.elements.values() {
        let c = e.get("category").and_then(|c| c.as_str()).unwrap_or("").to_string();
        *counts.entry(c).or_insert(0) += 1;
    }
    let mut m = Map::new();
    for (k, v) in counts {
        m.insert(&k, Value::u(v));
    }
    crate::jobj! {
        "elements" => Value::Obj(m),
        "format" => schema,
        "moved" => moved,
        "name" => name,
        "path" => path,
        "skipped" => Value::Arr(ctx.skipped.iter().map(|s| Value::s(s)).collect()),
    }
}
