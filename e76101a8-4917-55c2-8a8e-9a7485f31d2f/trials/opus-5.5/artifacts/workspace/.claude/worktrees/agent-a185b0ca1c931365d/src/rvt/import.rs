//! A Revit project read into a BIMCraft project: the levels, the elements by kind, and the
//! check-and-drop pass that leaves out what breaks a model rule and says why.

use super::build;
use super::cats;
use super::data::{self, DataIndex};
use super::doc::Doc;
use super::inventory;
use super::levels::Block;
use super::materials::{self, Materials};
use super::notes::{Kind, Notes};
use super::records::Record;
use crate::json::Value;
use crate::project::Project;
use std::collections::{BTreeMap, BTreeSet};

/// A level of the file as the import knows it.
#[derive(Clone, Debug)]
pub struct FileLevel {
    pub id: u64,
    pub name: String,
    /// Millimetres, rounded.
    pub elevation: f64,
    /// Feet, as the file has it.
    pub ft: f64,
    /// The project level it became, if it came in.
    pub guid: Option<String>,
}

pub struct Ctx<'a> {
    pub doc: &'a Doc,
    pub idx: DataIndex,
    pub mats: Materials,
    pub notes: Notes,
    pub pr: Project,
    pub levels: Vec<FileLevel>,
    /// Elements that came in, by the file's id and BIMCraft category: (project id, guid).
    pub made: BTreeMap<(u64, &'static str), (u64, String)>,
    /// The file's ids of elements left out (or never read), by kind.
    pub gone: BTreeSet<(u64, &'static str)>,
    /// The types of each category, by id.
    type_ids: BTreeMap<i64, BTreeSet<u64>>,
    /// The newest copy of each record, by id (a placed instance framed inside a record takes its id).
    newest: BTreeMap<u64, usize>,
    /// GUIDs given to library entries before the library is registered: (kind, name) → GUID.
    pub lib_guids: BTreeMap<(String, String), String>,
}

impl<'a> Ctx<'a> {
    pub fn new(doc: &'a Doc, name: &str) -> Ctx<'a> {
        let idx = data::index(doc);
        let mats = materials::read(doc, &idx);
        let mut type_ids: BTreeMap<i64, BTreeSet<u64>> = BTreeMap::new();
        let mut newest: BTreeMap<u64, usize> = BTreeMap::new();
        let order = doc.parts_newest_first();
        let rank = |p: usize| order.iter().position(|x| *x == p).unwrap_or(usize::MAX);
        for (i, r) in doc.records.iter().enumerate() {
            // a type: a record of the category that is not a placed instance (a type, a symbol)
            if !r.placed() && !r.inner && doc.declared(r.id) {
                type_ids.entry(r.category).or_default().insert(r.id);
            }
            if !r.boxed {
                continue;
            }
            if !r.inner && !doc.declared(r.id) {
                continue;
            }
            let key = r.id;
            match newest.get(&key) {
                Some(&j) => {
                    let (rj, ri) = (rank(doc.records[j].partition), rank(r.partition));
                    if ri < rj || (ri == rj && r.start >= doc.records[j].start) {
                        newest.insert(key, i);
                    }
                }
                None => {
                    newest.insert(key, i);
                }
            }
        }
        Ctx {
            doc,
            idx,
            mats,
            notes: Notes::default(),
            pr: build::new_project(name),
            levels: Vec::new(),
            made: BTreeMap::new(),
            gone: BTreeSet::new(),
            type_ids,
            newest,
            lib_guids: BTreeMap::new(),
        }
    }

    /// The GUID of a library entry: the one it has, or one it will have when the library is
    /// registered.
    pub fn lib_guid(&mut self, kind: &str, name: &str) -> String {
        if let Some(g) = self.pr.lib_guid(kind, name) {
            return g;
        }
        self.lib_guids
            .entry((kind.to_string(), name.to_string()))
            .or_insert_with(crate::rand::guid)
            .clone()
    }

    /// The placed instances of a category, by id.
    pub fn instances(&self, cat: i64) -> Vec<&'a Record> {
        let mut v: Vec<&Record> = Vec::new();
        for (_, &i) in &self.newest {
            let r = &self.doc.records[i];
            if r.category == cat && r.placed() {
                v.push(r);
            }
        }
        v.sort_by_key(|r| r.id);
        v
    }

    /// All the placed instances, of every category, by category then id.
    pub fn all_instances(&self) -> Vec<&'a Record> {
        let mut v: Vec<&Record> = Vec::new();
        for (_, &i) in &self.newest {
            let r = &self.doc.records[i];
            if r.placed() {
                v.push(r);
            }
        }
        v
    }

    /// Whether an id is a placed instance of a category (its current record).
    pub fn is_instance(&self, cat: i64, id: u64) -> bool {
        match self.newest.get(&id) {
            Some(&i) => {
                let r = &self.doc.records[i];
                r.category == cat && r.placed()
            }
            None => false,
        }
    }

    /// A record by id: its current boxed copy, else its copy in the newest partition.
    pub fn record(&self, id: u64) -> Option<&'a Record> {
        if let Some(&i) = self.newest.get(&id) {
            return Some(&self.doc.records[i]);
        }
        let doc = self.doc;
        for pi in doc.parts_newest_first() {
            if let Some(r) = doc.records.iter().rev().find(|r| r.id == id && r.partition == pi) {
                return Some(r);
            }
        }
        None
    }

    pub fn is_type(&self, cat: i64, id: u64) -> bool {
        self.type_ids.get(&cat).map(|s| s.contains(&id)).unwrap_or(false)
    }

    /// The one type of the category a record names, if it names exactly one.
    pub fn one_type(&self, r: &Record, cat: i64) -> Option<u64> {
        let mut found: Vec<u64> = Vec::new();
        for id in &r.refs {
            if self.is_type(cat, *id) && !found.contains(id) {
                found.push(*id);
            }
        }
        if found.len() == 1 {
            Some(found[0])
        } else {
            None
        }
    }

    /// An element's current data, if it has any.
    pub fn data(&self, id: u64) -> Option<&'a [u8]> {
        self.datas(id).into_iter().next()
    }

    /// All of an element's data blocks (their bodies), the newest partition's first.
    pub fn datas(&self, id: u64) -> Vec<&'a [u8]> {
        let doc = self.doc;
        self.idx.all_newest_first(doc, id).into_iter().map(|b| &doc.parts[b.part].data[b.body..b.end]).collect()
    }

    /// The first of an element's data blocks that has what `f` reads.
    pub fn first_data<T>(&self, id: u64, f: impl Fn(&'a [u8]) -> Option<T>) -> Option<T> {
        self.datas(id).into_iter().find_map(f)
    }

    pub fn type_name(&self, id: u64) -> Option<String> {
        let rel = self.doc.release;
        self.first_data(id, |d| data::type_name(d, rel))
    }

    /// A type's layers: from the first of its data blocks that has a compound structure.
    pub fn type_layers(&self, id: u64) -> super::types::Layers {
        let tag = self.doc.schema.tag("VerticalRegionsStructure");
        let mut mk = vec![0xffu8; 4];
        if let Some(t) = tag {
            mk.extend_from_slice(&t.to_le_bytes());
        }
        let mats = &self.mats;
        for d in self.datas(id) {
            if tag.is_some() && super::bytes::find(d, &mk, 0, d.len()).is_some() {
                return super::types::layers(self.doc, d, &|m| mats.is_material(m));
            }
        }
        super::types::Layers::None
    }

    /// The BIMCraft material of a material id (by its name), or "" when there is none.
    pub fn material_guid(&self, id: Option<u64>, category: i64) -> String {
        let id = match id {
            Some(i) => Some(i),
            None => materials::category_material(self.doc, &self.mats, category),
        };
        let name = match id.and_then(|i| self.mats.name(i)) {
            Some(n) => n.to_string(),
            None => return String::new(),
        };
        build::material_guid(&self.pr, &name).unwrap_or_default()
    }

    /// The file levels named in a list, then the level an element stands on: the highest of the
    /// candidates (the named ones, or all) at or below its bottom, else the lowest; none on a tie.
    pub fn base_level(&self, refs: &[u64], bottom_ft: f64) -> Option<usize> {
        let named: Vec<usize> = (0..self.levels.len()).filter(|i| refs.contains(&self.levels[*i].id)).collect();
        let cands: Vec<usize> = if named.is_empty() { (0..self.levels.len()).collect() } else { named };
        if cands.is_empty() {
            return None;
        }
        // at or below: within a thousandth of a foot
        let below: Vec<usize> = cands.iter().copied().filter(|i| self.levels[*i].ft <= bottom_ft + 0.001).collect();
        let pick_from = if below.is_empty() { cands.clone() } else { below.clone() };
        let target = if below.is_empty() {
            pick_from.iter().map(|i| self.levels[*i].ft).fold(f64::INFINITY, f64::min)
        } else {
            pick_from.iter().map(|i| self.levels[*i].ft).fold(f64::NEG_INFINITY, f64::max)
        };
        let at: Vec<usize> = pick_from.into_iter().filter(|i| self.levels[*i].ft == target).collect();
        if at.len() == 1 {
            Some(at[0])
        } else {
            None
        }
    }

    /// The level a run or a box stands on: the last of the levels (by elevation) at or below its
    /// base, else the lowest; the levels its record names do not count.
    pub fn level_at(&self, z_ft: f64) -> Option<usize> {
        if self.levels.is_empty() {
            return None;
        }
        // at or below: within a millimetre
        let below = (0..self.levels.len()).filter(|i| (self.levels[*i].ft - z_ft) * 304.8 <= 1.0).last();
        Some(below.unwrap_or(0))
    }

    /// A named level other than the base at the element's top (within a millimetre).
    pub fn top_level(&self, refs: &[u64], base: usize, top_ft: f64) -> Option<usize> {
        let at: Vec<usize> = (0..self.levels.len())
            .filter(|i| *i != base && refs.contains(&self.levels[*i].id))
            .filter(|i| ((self.levels[*i].ft - top_ft) * 304.8).abs() <= 1.0 && self.levels[*i].ft > self.levels[base].ft)
            .collect();
        if at.len() == 1 {
            Some(at[0])
        } else {
            None
        }
    }

    pub fn level_guid(&self, i: usize) -> Value {
        match &self.levels[i].guid {
            Some(g) => Value::s(g),
            None => Value::Null,
        }
    }

    /// Adds an element; returns its project id.
    pub fn add(&mut self, rid: u64, cat: &'static str, v: Value) -> u64 {
        let id = self.pr.alloc_id();
        let g = v.get("guid").and_then(|g| g.as_str()).unwrap_or("").to_string();
        self.pr.elements.insert(id, v);
        self.made.insert((rid, cat), (id, g));
        id
    }
}

fn levels_in(ctx: &mut Ctx) {
    let doc = ctx.doc;
    let mut read: Vec<(f64, u64, String, f64)> = Vec::new();
    let mut unread = 0usize;
    let mut owned: Vec<u64> = Vec::new();
    for id in inventory::level_ids(doc) {
        match inventory::level_block(doc, id) {
            Some(Block::Read { name, elevation, .. }) => read.push((build::mm(elevation), id, name, elevation)),
            Some(Block::Owned) => owned.push(id),
            None => unread += 1,
        }
    }
    read.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal).then(a.1.cmp(&b.1)));
    let mut used: Vec<String> = Vec::new();
    let mut late: Vec<String> = Vec::new();
    let lvl = Kind::simple("level");
    for (elev, id, name, ft) in read {
        let mut n = name.clone();
        let mut k = 2;
        while used.contains(&n) {
            n = format!("{} ({})", name, k);
            k += 1;
        }
        used.push(n.clone());
        let g = crate::rand::guid();
        let v = jobj! {
            "guid" => g.as_str(),
            "category" => "level",
            "name" => n.as_str(),
            "elevation" => elev,
            "view_range" => jobj!{"top" => Value::Null, "cut" => 1200.0, "bottom" => 0.0, "depth" => 0.0},
        };
        let pid = ctx.pr.alloc_id();
        if elev.abs() > 1e9 {
            late.push(format!("1 level left out, {} is not a usable number ('{}')", elev, n));
            ctx.levels.push(FileLevel { id, name: n, elevation: elev, ft, guid: None });
            continue;
        }
        ctx.pr.elements.insert(pid, v);
        ctx.levels.push(FileLevel { id, name: n, elevation: elev, ft, guid: Some(g) });
    }
    if ctx.levels.iter().all(|l| l.guid.is_none()) {
        ctx.notes.first.push("the file has no levels the reader can find: the project has one, Level 1, at zero".into());
        let g = crate::rand::guid();
        let v = jobj! {
            "guid" => g.as_str(),
            "category" => "level",
            "name" => "Level 1",
            "elevation" => 0.0,
            "view_range" => jobj!{"top" => Value::Null, "cut" => 1200.0, "bottom" => 0.0, "depth" => 0.0},
        };
        let pid = ctx.pr.alloc_id();
        ctx.pr.elements.insert(pid, v);
    }
    if unread > 0 {
        ctx.notes.first.push(format!(
            "{} {} left out, no name or elevation the reader can find (its block is missing or damaged)",
            unread,
            if unread == 1 { "level" } else { "levels" }
        ));
    }
    ctx.notes.first.extend(late);
    for id in owned {
        ctx.notes.leave(&lvl, "it sits inside other elements, so it is not a project level", id);
    }
    // levels that did not come in are no level to stand on
    ctx.levels.retain(|l| l.guid.is_some());
}

/// The categories BIMCraft has a reader for, and their kinds.
pub fn kind_of(cat: i64) -> Option<Kind> {
    Some(match cat {
        cats::OST_WALLS => Kind::simple("wall"),
        _ => return None,
    })
}

pub fn run(doc: &Doc, name: &str) -> (Project, Notes) {
    let mut ctx = Ctx::new(doc, name);
    levels_in(&mut ctx);
    let fates = super::walls::read(&mut ctx);
    let sketches = super::sketch::owners(&ctx);
    super::floors::read(&mut ctx, &sketches);
    let under = super::roofs::read(&mut ctx, &sketches);
    super::roofs::attach(&mut ctx, &fates, &under);
    super::openings::read(&mut ctx, &fates);
    super::columns::read(&mut ctx);
    super::rooms::read(&mut ctx);
    super::mep::read(&mut ctx);
    super::components::read(&mut ctx);
    super::drop::run(&mut ctx);
    build::sync_library(&mut ctx.pr, &ctx.lib_guids);
    (ctx.pr, ctx.notes)
}

/// The project rules on the types an import makes that it can break (a column's size comes from
/// a box the file gives): what the original says when a project breaks them.
pub fn check_types(pr: &Project) -> Result<(), String> {
    let types = match pr.doc.get("types") {
        Some(Value::Obj(m)) => m,
        _ => return Ok(()),
    };
    for (sect, tv) in &types.items {
        let what = match sect.as_str() {
            "column" => "column",
            "structural_column" => "structural column",
            _ => continue,
        };
        let m = match tv {
            Value::Obj(m) => m,
            _ => continue,
        };
        for (name, t) in &m.items {
            for key in ["width", "depth"] {
                if let Some(x) = t.get(key).and_then(|x| x.as_f64()) {
                    if !(x > 0.0) {
                        return Err(format!("{} type `{}` {} must be above zero, got {}", what, name, key, x));
                    }
                }
            }
        }
    }
    Ok(())
}

/// The reply `run` prints for an import.
pub fn reply(pr: &Project, notes: &Notes, release: u32, name: &str, path: &str) -> Value {
    let mut counts: BTreeMap<String, u64> = BTreeMap::new();
    for e in pr.elements.values() {
        let c = e.get("category").and_then(|c| c.as_str()).unwrap_or("").to_string();
        *counts.entry(c).or_insert(0) += 1;
    }
    let mut m = crate::json::Map::new();
    for (k, v) in counts {
        m.insert(&k, Value::u(v));
    }
    jobj! {
        "elements" => Value::Obj(m),
        "format" => format!("Revit {}", release),
        "moved" => Value::Null,
        "name" => name,
        "path" => path,
        "skipped" => Value::Arr(notes.lines().into_iter().map(Value::Str).collect()),
    }
}
