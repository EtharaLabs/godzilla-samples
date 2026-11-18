//! `type`: Edit Type for every category, and the type each category uses by default.
//!
//! A category's types live in the file's `types` (`common::type_path`: `wall`, `floor`, `door`,
//! `window`, `column`, `roof`, `ceiling`, `railing`, `structural_column`, `footing`, `runs.<cat>`
//! in that order), each by name in name order, with a library entry `type:<category>` (its
//! GUID, which elements name it by). A wall type may have layers from its exterior side in, a
//! floor's, roof's or ceiling's from the top down: `{id, guid, function, material, thickness,
//! variable?}`, each a part with its own id (counting down with the library's) and GUID, its
//! material by GUID ("" for none); the type's `thickness` is theirs added up.

mod layers;
mod spec;

pub use layers::{Layer, FUNCTIONS};
pub use spec::{shape, word, Shape, Spec};

use crate::commands::params::{opt_bool, opt_num, opt_text};
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;
use crate::structure::common::{is_run, type_kind, type_path, types_of, R, RUN_CATS};
use crate::structure::members::read::parse_guid;
use spec::{has_material, layers_sum, validate, SUM_TOL};
use std::collections::{HashMap, HashSet};

const CMD: &str = "type";

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "type" => edit(s, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
    .map_err(clip)
}

/// The longest a command's refusal is.
const MAX_ERROR: usize = 2000;

/// A command's refusal cut to its first 2000 characters, saying how many more there were.
pub fn clip(e: String) -> String {
    let n = e.chars().count();
    if n <= MAX_ERROR {
        return e;
    }
    let mut out: String = e.chars().take(MAX_ERROR).collect();
    out.push_str(&format!("… ({} more characters)", n - MAX_ERROR));
    out
}

// ---------------------------------------------------------------- categories

/// The categories, as `type` and the rest of the original know them by key.
const KNOWN: &[&str] = &[
    "wall",
    "floor",
    "ceiling",
    "roof",
    "door",
    "window",
    "room",
    "column",
    "component",
    "stair",
    "ramp",
    "railing",
    "mass",
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
];

/// A category as typed (any case, spaces, `_`, `-` or anything but letters and digits left
/// out, plural): its key, known or not.
pub fn category_key(s: &str) -> String {
    let key: String = s.chars().filter(|c| c.is_ascii_alphanumeric()).collect::<String>().to_ascii_lowercase();
    if KNOWN.contains(&key.as_str()) {
        return key;
    }
    for c in KNOWN {
        if c.ends_with('s') && key == format!("{}es", c) {
            return c.to_string();
        }
    }
    key.trim_end_matches('s').to_string()
}

/// The categories that have types, in the order the model's rules visit them.
pub const TYPE_CATS: &[&str] = &[
    "door",
    "window",
    "wall",
    "floor",
    "roof",
    "ceiling",
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
    "railing",
];

/// The type a category's new elements take where the project has one of that name.
pub fn default_name(cat: &str) -> Option<&'static str> {
    Some(match cat {
        "wall" => "Generic - 200mm",
        "floor" => "Generic - 200mm",
        "roof" => "Generic - 300mm",
        "ceiling" => "Generic - 20mm",
        "door" => "Single 900 x 2100",
        "window" => "Fixed 1200 x 1500",
        "railing" => "Railing - 1000mm",
        "column" => "Rectangular 400 x 400",
        "structuralcolumn" => "Concrete 300 x 300",
        "footing" => "Footing 1200 x 1200",
        "beam" => "Beam 200 x 500",
        "stripfooting" => "Strip 600 x 300",
        "pipe" => "PVC 50",
        "duct" => "Rectangular 400 x 300",
        "conduit" => "PVC 25",
        "cabletray" => "Perforated 100 x 50",
        "wire" => "Wire 2.5",
        "downconductor" => "Steel 8",
        "groundconductor" => "Copper 9",
        "cable" => "Cat6",
        _ => return None,
    })
}

/// The type a new element of a category takes when it names none: the category's own default
/// where the project has a type of that name (whatever the project's language: the types are
/// named alike in all of them), else the first by name (byte order); None when it has none.
/// A renamed or deleted default is no longer the default: the first by name is.
pub fn default_type(pr: &Project, cat: &str) -> Option<String> {
    let types = types_of(pr, cat)?;
    if let Some(named) = default_name(cat) {
        if types.contains(named) {
            return Some(named.to_string());
        }
    }
    types.keys().min().map(|n| n.to_string())
}

/// A type of a category by name, as the original holds it (materials by name).
pub fn spec_of(pr: &Project, cat: &str, name: &str) -> Option<Spec> {
    let v = types_of(pr, cat)?.get(name)?;
    Spec::from_file(pr, cat, v)
}

/// One type as `type` replies and `inspect` shows it: keys sorted, materials by name, layers
/// with their ids and GUIDs.
pub fn type_view(pr: &Project, cat: &str, name: &str) -> Option<Value> {
    Some(spec_of(pr, cat, name)?.view(&[]))
}

/// The project's types as `inspect` shows them (`types`): every category's by name as
/// `type_view` shows them, under the file's keys (`structural_column`, `runs` by category…);
/// structural columns, footings and runs only where the project has some.
pub fn types_view(pr: &Project) -> Value {
    let mut out = Map::new();
    let types = match pr.section("types") {
        Some(t) => t,
        None => return Value::Obj(out),
    };
    let one = |cat: &str, ts: &Map| -> Value {
        let mut m = Map::new();
        for (n, v) in ts.iter() {
            if let Some(sp) = Spec::from_file(pr, cat, v) {
                m.insert_sorted(n, sp.view(&[]));
            }
        }
        Value::Obj(m)
    };
    for (key, cat, always) in [
        ("wall", "wall", true),
        ("floor", "floor", true),
        ("door", "door", true),
        ("window", "window", true),
        ("column", "column", true),
        ("roof", "roof", true),
        ("ceiling", "ceiling", true),
        ("railing", "railing", true),
        ("structural_column", "structuralcolumn", false),
        ("footing", "footing", false),
    ] {
        match types.get(key) {
            Some(Value::Obj(ts)) if always || !ts.is_empty() => out.insert(key, one(cat, ts)),
            _ if always => out.insert(key, Value::obj()),
            _ => {}
        }
    }
    if let Some(Value::Obj(runs)) = types.get("runs") {
        if !runs.is_empty() {
            let mut r = Map::new();
            for (c, ts) in runs.iter() {
                if let Value::Obj(ts) = ts {
                    r.insert_sorted(c, one(c, ts));
                }
            }
            out.insert("runs", Value::Obj(r));
        }
    }
    Value::Obj(out)
}

/// A wall's, floor's, roof's or ceiling's type: its thickness and its layers (from the
/// exterior in for a wall, from the top down for the others; none for a type of one material),
/// their materials by name.
pub fn layered(pr: &Project, cat: &str, name: &str) -> Option<(f64, Vec<Layer>)> {
    match spec_of(pr, cat, name)? {
        Spec::Layered { thickness, layers, .. } => Some((thickness, layers)),
        _ => None,
    }
}

/// A layered type's core: from the exterior (top) face to its first structure layer's outer
/// face and to its last one's inner face, mm; None when no layer is structure.
pub fn core(layers: &[Layer]) -> Option<(f64, f64)> {
    let first = layers.iter().position(|l| l.function == "structure")?;
    let last = layers.iter().rposition(|l| l.function == "structure")?;
    let mut at = 0.0;
    let (mut a, mut b) = (0.0, 0.0);
    for (i, l) in layers.iter().enumerate() {
        if i == first {
            a = at;
        }
        at += l.thickness;
        if i == last {
            b = at;
        }
    }
    Some((a, b))
}

// ---------------------------------------------------------------- the command's parameters

/// What the original does to a command's parameters first: a string that is a library entry's
/// GUID (a type's, a material's, a family's…) stands for that entry's name.
pub fn names_for_guids(pr: &Project, p: &Value) -> Value {
    let mut by: HashMap<&str, &str> = HashMap::with_capacity(pr.library.len());
    for e in pr.library.values() {
        if let (Some(g), Some(n)) = (e.get("guid").and_then(|g| g.as_str()), e.get("name").and_then(|n| n.as_str())) {
            by.entry(g).or_insert(n);
        }
    }
    fn walk(v: &mut Value, by: &HashMap<&str, &str>) {
        match v {
            Value::Str(s) => {
                if let Some(g) = parse_guid(s) {
                    if let Some(n) = by.get(g.as_str()) {
                        *s = n.to_string();
                    }
                }
            }
            Value::Arr(a) => a.iter_mut().for_each(|x| walk(x, by)),
            Value::Obj(m) => m.items.iter_mut().for_each(|(_, x)| walk(x, by)),
            _ => {}
        }
    }
    let mut out = p.clone();
    walk(&mut out, &by);
    out
}

fn needs(cat: &str, key: &str) -> String {
    format!("{}: a new {} type needs `{}`", CMD, cat, key)
}

fn d(x: f64) -> String {
    format!("{}", x)
}

const OPERATIONS: &[&str] = &["swing", "double-swing", "sliding", "double-sliding", "folding", "fixed"];

// ---------------------------------------------------------------- the command

fn edit(s: &mut Session, p0: &Value) -> R<Value> {
    let p = &names_for_guids(&s.project, p0);
    let cat_raw = match opt_text(p, CMD, "category")? {
        Some(c) => c,
        None => return Err(format!("{}: `category` is required: wall, floor, ceiling, door or window", CMD)),
    };
    let name = match opt_text(p, CMD, "name")? {
        Some(n) if !n.trim().is_empty() => n,
        _ => return Err(format!("{}: `name` is required", CMD)),
    };
    let thickness = opt_num(p, CMD, "thickness")?;
    let width = opt_num(p, CMD, "width")?;
    let height = opt_num(p, CMD, "height")?;
    let sill = opt_num(p, CMD, "sill")?;
    let cat = category_key(&cat_raw);
    let sh = match shape(&cat) {
        Some(x) => x,
        None => {
            return Err(format!(
                "{}: `{}` has no types; use wall, floor, ceiling, door, window, column, structural column, footing, \
                 beam, strip footing, pipe, conduit, cable tray, wire, down conductor, earthing conductor, cable, roof or railing",
                CMD, cat
            ))
        }
    };
    let pr = &s.project;
    let old = spec_of(pr, &cat, &name);
    let spec = match sh {
        Shape::Layered => layered_spec(p, &cat, old.as_ref(), thickness)?,
        Shape::Opening => {
            let (ow, oh, os, oo) = match &old {
                Some(Spec::Opening { width, height, sill, operation }) => {
                    (Some(*width), Some(*height), Some(*sill), operation.clone())
                }
                _ => (None, None, None, None),
            };
            let operation = match opt_text(p, CMD, "operation")? {
                None => oo,
                Some(o) => {
                    let t = o.trim().to_lowercase();
                    if t.is_empty() {
                        None
                    } else if OPERATIONS.contains(&t.as_str()) {
                        Some(t)
                    } else {
                        return Err(format!("{}: `operation` is one of {}, not `{}`", CMD, OPERATIONS.join(", "), o));
                    }
                }
            };
            let width = width.or(ow).ok_or_else(|| needs(&cat, "width"))?;
            let height = height.or(oh).ok_or_else(|| needs(&cat, "height"))?;
            let sill = sill.or(os).unwrap_or(if cat == "window" { 900.0 } else { 0.0 });
            Spec::Opening { width, height, sill, operation }
        }
        Shape::Column => {
            let (ow, od, or) = match &old {
                Some(Spec::Column { width, depth, round }) => (Some(*width), Some(*depth), Some(*round)),
                _ => (None, None, None),
            };
            let width = width.or(ow).ok_or_else(|| needs(&cat, "width"))?;
            let round = opt_bool(p, CMD, "round")?.or(or).unwrap_or(false);
            let depth = if round { width } else { opt_num(p, CMD, "depth")?.or(od).unwrap_or(width) };
            Spec::Column { width, depth, round }
        }
        Shape::Run => {
            let (ow, od, or, om) = match &old {
                Some(Spec::Run { width, depth, round, material }) => {
                    (Some(*width), Some(*depth), Some(*round), material.clone())
                }
                _ => (None, None, None, None),
            };
            let width = width.or(ow).ok_or_else(|| needs(&cat, "width"))?;
            let round = opt_bool(p, CMD, "round")?.or(or).unwrap_or(false);
            let depth = if round {
                width
            } else {
                opt_num(p, CMD, "depth")?.or(od).ok_or_else(|| needs(&cat, "depth"))?
            };
            let material = match opt_text(p, CMD, "material")? {
                None => om,
                Some(m) if m.is_empty() => None,
                Some(m) => Some(m),
            };
            Spec::Run { width, depth, round, material }
        }
        Shape::Railing => {
            let (oh, os) = match &old {
                Some(Spec::Railing { height, spacing }) => (Some(*height), Some(*spacing)),
                _ => (None, None),
            };
            let height = height.or(oh).ok_or_else(|| needs(&cat, "height"))?;
            let spacing = opt_num(p, CMD, "spacing")?.or(os).unwrap_or(0.0);
            Spec::Railing { height, spacing }
        }
    };
    validate(&cat, &name, &spec, &|m: &str| has_material(pr, m))?;
    // the reply shows the type as the command leaves it, before its new layers have their
    // ids and GUIDs (the original gives them after the command)
    let view = spec.view(&[]);
    store(&mut s.project, &cat, &name, spec, old.as_ref());
    crate::structure::common::mark_step();
    Ok(crate::jobj! {"category" => cat.as_str(), "name" => name.as_str(), "type" => view})
}

/// A wall's, floor's, roof's or ceiling's type as `type` leaves it.
fn layered_spec(p: &Value, cat: &str, old: Option<&Spec>, thickness: Option<f64>) -> R<Spec> {
    let given = layers::param(p, CMD)?;
    let (old_t, old_grid, old_layers): (Option<f64>, Option<f64>, Vec<Layer>) = match old {
        Some(Spec::Layered { thickness, grid, layers }) => (Some(*thickness), *grid, layers.clone()),
        _ => (None, None, Vec::new()),
    };
    // a new thickness for layers kept goes to their structure
    let mut to_structure = false;
    let (t, mut ls) = match given {
        Some(ls) if !ls.is_empty() => {
            let sum = layers_sum(&ls);
            if let Some(t) = thickness {
                if (sum - t).abs() > SUM_TOL {
                    return Err(format!("{}: its layers add up to {} mm, not the {} mm given", CMD, d(sum), d(t)));
                }
            }
            // a layer given without its id and GUID is the one it replaces, by place
            let mut out = Vec::with_capacity(ls.len());
            for (i, mut l) in ls.into_iter().enumerate() {
                if !l.has_ref() {
                    if let Some(o) = old_layers.get(i) {
                        l.id = o.id;
                        l.guid = o.guid.clone();
                    }
                }
                out.push(l);
            }
            (sum, out)
        }
        Some(_) => match thickness {
            Some(t) => (t, Vec::new()),
            None => return Err(needs(cat, "thickness")),
        },
        None => match (thickness, old_t) {
            (Some(t), Some(_)) => {
                to_structure = !old_layers.is_empty();
                (t, old_layers)
            }
            (Some(t), None) => (t, Vec::new()),
            (None, Some(ot)) => (ot, old_layers),
            (None, None) => return Err(needs(cat, "thickness")),
        },
    };
    let grid = if cat == "ceiling" { Some(opt_num(p, CMD, "grid")?.or(old_grid).unwrap_or(0.0)) } else { None };
    if to_structure {
        // its first structure layer, else its thickest (the last of the thickest)
        let idx = match ls.iter().position(|l| l.function == "structure") {
            Some(i) => i,
            None => {
                let mut best = 0;
                for (i, l) in ls.iter().enumerate() {
                    if l.thickness >= ls[best].thickness {
                        best = i;
                    }
                }
                best
            }
        };
        let now = ls[idx].thickness + (t - old_t.unwrap_or(0.0));
        if now <= 0.0 {
            return Err(format!(
                "{}: at {} mm its structure would be {} mm thick; change its layers",
                CMD,
                d(t),
                d(now)
            ));
        }
        ls[idx].thickness = now;
    }
    Ok(Spec::Layered { thickness: t, grid, layers: ls })
}

// ---------------------------------------------------------------- storing a type

/// The keys of the file's `types`, in its order.
const SECTION_ORDER: &[&str] = &[
    "wall",
    "floor",
    "door",
    "window",
    "column",
    "roof",
    "ceiling",
    "railing",
    "structural_column",
    "footing",
    "runs",
];

/// Inserts a key into a map at its place in an order (after those before it).
fn insert_ordered(m: &mut Map, key: &str, v: Value, order: &[&str]) {
    if m.contains(key) {
        m.insert(key, v);
        return;
    }
    let rank = |k: &str| order.iter().position(|o| *o == k).unwrap_or(usize::MAX);
    let r = rank(key);
    let pos = m.items.iter().position(|(k, _)| rank(k) > r).unwrap_or(m.items.len());
    m.items.insert(pos, (key.to_string(), v));
}

/// A category's types in the file, made where they go when the file has none of them.
fn types_map<'a>(pr: &'a mut Project, cat: &str) -> &'a mut Map {
    let (sec, sub) = type_path(cat);
    let types = pr.section_mut("types");
    if !matches!(types.get(sec), Some(Value::Obj(_))) {
        insert_ordered(types, sec, Value::obj(), SECTION_ORDER);
    }
    let mut m = types.get_mut(sec).unwrap().as_obj_mut().unwrap();
    if let Some(k) = sub {
        if !matches!(m.get(k), Some(Value::Obj(_))) {
            put_sorted(m, k, Value::obj());
        }
        m = m.get_mut(k).unwrap().as_obj_mut().unwrap();
    }
    m
}

/// Sets a key of a map the original keeps in name order (a BTreeMap: its types of a category,
/// its run categories, its families), which a hand-made file may not have kept.
pub fn put_sorted(m: &mut Map, k: &str, v: Value) {
    if !m.items.windows(2).all(|w| w[0].0 < w[1].0) {
        m.sort();
    }
    if m.contains(k) {
        m.insert(k, v);
    } else {
        m.insert_sorted(k, v);
    }
}

/// A material's GUID by name, its library entry made if it has none.
fn material_guid(pr: &mut Project, name: &str) -> String {
    match pr.lib_guid("material", name) {
        Some(g) => g,
        None => pr.lib_add("material", name).1,
    }
}

/// Every id and GUID the project uses (elements, library entries and the parts of its types,
/// families and the rest), but those of one type's layers.
fn used_refs(pr: &Project, cat: &str, name: &str) -> (HashSet<u64>, HashSet<String>) {
    let mut ids: HashSet<u64> = pr.elements.keys().copied().collect();
    let mut guids: HashSet<String> = HashSet::new();
    for e in pr.elements.values() {
        if let Some(g) = e.get("guid").and_then(|g| g.as_str()) {
            guids.insert(g.to_string());
        }
    }
    for (id, e) in &pr.library {
        ids.insert(*id);
        if let Some(g) = e.get("guid").and_then(|g| g.as_str()) {
            guids.insert(g.to_string());
        }
    }
    fn scan(v: &Value, ids: &mut HashSet<u64>, guids: &mut HashSet<String>) {
        match v {
            Value::Obj(m) => {
                if let Some(id) = m.get("id").and_then(|x| x.as_u64()) {
                    ids.insert(id);
                    if let Some(g) = m.get("guid").and_then(|g| g.as_str()) {
                        guids.insert(g.to_string());
                    }
                }
                m.items.iter().for_each(|(_, x)| scan(x, ids, guids));
            }
            Value::Arr(a) => a.iter().for_each(|x| scan(x, ids, guids)),
            _ => {}
        }
    }
    let (sec, sub) = type_path(cat);
    for (k, v) in &pr.doc.items {
        if k == "elements" || k == "library" {
            continue;
        }
        if k == "types" {
            if let Value::Obj(types) = v {
                for (tk, tv) in &types.items {
                    if tk != sec {
                        scan(tv, &mut ids, &mut guids);
                        continue;
                    }
                    let inner = match sub {
                        None => Some(tv),
                        Some(sk) => {
                            if let Value::Obj(runs) = tv {
                                for (rk, rv) in &runs.items {
                                    if rk != sk {
                                        scan(rv, &mut ids, &mut guids);
                                    }
                                }
                            }
                            tv.get(sk)
                        }
                    };
                    if let Some(Value::Obj(ts)) = inner {
                        for (n, t) in &ts.items {
                            if n != name {
                                scan(t, &mut ids, &mut guids);
                            }
                        }
                    }
                }
            }
            continue;
        }
        scan(v, &mut ids, &mut guids);
    }
    (ids, guids)
}

/// Puts a type in the file as `type` leaves it: a new one gets its library entry, then its new
/// layers their ids (counting down with the library's) and GUIDs, as the original gives them
/// after the command: a layer that is one the type had (its id and GUID) keeps them; another
/// keeps an id or a GUID given it that nothing else has, and gets a new one else.
fn store(pr: &mut Project, cat: &str, name: &str, mut spec: Spec, old: Option<&Spec>) {
    let is_new = old.is_none();
    let old_pairs: Vec<(Option<u64>, Option<layers::GRef>)> = match old {
        Some(Spec::Layered { layers, .. }) => layers.iter().map(|l| (l.id, l.guid.clone())).collect(),
        _ => Vec::new(),
    };
    let mut mats: HashMap<String, String> = HashMap::new();
    let names: Vec<String> = match &spec {
        Spec::Layered { layers, .. } => layers.iter().map(|l| l.material.clone()).filter(|m| !m.is_empty()).collect(),
        Spec::Run { material: Some(m), .. } => vec![m.clone()],
        _ => Vec::new(),
    };
    for n in names {
        if !mats.contains_key(&n) {
            let g = material_guid(pr, &n);
            mats.insert(n, g);
        }
    }
    let file = |sp: &Spec, mats: &HashMap<String, String>| sp.to_file(&|n: &str| mats.get(n).cloned().unwrap_or_default());
    let v = file(&spec, &mats);
    put_sorted(types_map(pr, cat), name, v);
    // the ids its layers have now, which the original's allocator counts down from too
    let given: Vec<u64> = match &spec {
        Spec::Layered { layers, .. } => layers.iter().filter_map(|l| l.id).collect(),
        _ => Vec::new(),
    };
    if is_new && pr.lib_find(&type_kind(cat), name).is_none() {
        let id = alloc_entry(pr, &given);
        let g = crate::structure::common::new_guid();
        pr.library.insert(id, crate::jobj! {"kind" => type_kind(cat), "name" => name, "guid" => g});
    }
    if let Spec::Layered { layers, .. } = &mut spec {
        if layers.is_empty() {
            return;
        }
        let (mut ids, mut guids) = used_refs(pr, cat, name);
        // the layers that are the type's own where they were (the id and GUID its layer in
        // that place had) are claimed first
        let mut claimed = vec![false; layers.len()];
        for (i, l) in layers.iter().enumerate() {
            if l.id.is_none() || !matches!(l.guid, Some(layers::GRef::Guid(_))) {
                continue;
            }
            if old_pairs.get(i) == Some(&(l.id, l.guid.clone())) {
                claimed[i] = true;
                ids.insert(l.id.unwrap());
                if let Some(layers::GRef::Guid(g)) = &l.guid {
                    guids.insert(g.clone());
                }
            }
        }
        let mut need: Vec<usize> = Vec::new();
        for (i, l) in layers.iter_mut().enumerate() {
            if claimed[i] {
                continue;
            }
            match l.id {
                Some(id) if !ids.contains(&id) => {
                    ids.insert(id);
                }
                _ => need.push(i),
            }
            match &l.guid {
                Some(layers::GRef::Guid(g)) if !guids.contains(g) => {
                    guids.insert(g.clone());
                }
                _ => {
                    let g = crate::structure::common::new_guid();
                    guids.insert(g.clone());
                    l.guid = Some(layers::GRef::Guid(g));
                }
            }
        }
        let fresh = alloc_parts(pr, &given, need.len());
        for (i, id) in need.into_iter().zip(fresh) {
            layers[i].id = Some(id);
        }
        let v = file(&spec, &mats);
        put_sorted(types_map(pr, cat), name, v);
    }
}

/// The lowest id the library and the parts use, as the original's allocator sees it: with the
/// ids a command's layers were given (the project's own count keeps to the library's range).
fn lowest(pr: &Project, given: &[u64]) -> u64 {
    let mut low = pr.lowest_lib_id().min(pr.lib_low);
    for g in given {
        low = low.min(*g);
    }
    low
}

/// The highest id the library and the parts use.
fn highest(pr: &Project, given: &[u64]) -> u64 {
    fn scan(v: &Value, high: &mut u64) {
        match v {
            Value::Obj(m) => {
                if let Some(id) = m.get("id").and_then(|x| x.as_u64()) {
                    if id >= 900_000 {
                        *high = (*high).max(id);
                    }
                }
                m.items.iter().for_each(|(_, x)| scan(x, high));
            }
            Value::Arr(a) => a.iter().for_each(|x| scan(x, high)),
            _ => {}
        }
    }
    let mut high = pr.library.keys().next_back().copied().unwrap_or(0);
    for (k, v) in &pr.doc.items {
        if k != "elements" && k != "library" {
            scan(v, &mut high);
        }
    }
    for g in given {
        high = high.max(*g);
    }
    high
}

/// A new library entry's id: the next one down, or (where that would run into the elements')
/// the next element id.
fn alloc_entry(pr: &mut Project, given: &[u64]) -> u64 {
    let low = lowest(pr, given);
    let next = pr.next_id();
    if low > next {
        pr.lib_low = low - 1;
        low - 1
    } else {
        pr.doc.insert("next_id", Value::u(next + 1));
        next
    }
}

/// Ids for new parts: counting down from the lowest, or (where that would run into the
/// elements' ids) up from the highest.
fn alloc_parts(pr: &mut Project, given: &[u64], n: usize) -> Vec<u64> {
    if n == 0 {
        return Vec::new();
    }
    let low = lowest(pr, given);
    if low > pr.next_id() {
        let ids: Vec<u64> = (1..=n as u64).map(|k| low.saturating_sub(k)).collect();
        pr.lib_low = pr.lib_low.min(*ids.last().unwrap());
        ids
    } else {
        let high = highest(pr, given);
        (1..=n as u64).map(|k| high + k).collect()
    }
}

// ---------------------------------------------------------------- the model's rules

/// The model rules of this part, checked after every command (and by the original on opening
/// a file): every type of every category, doors' first, in name order, each by its rules in
/// turn; a run category the original doesn't know is refused where it comes.
///
/// Materials are not checked here: the original's reader makes a material of a name a file's
/// types give and the library hasn't, and the commands refuse what would leave one out (`type`
/// here; deleting or renaming a material, in `material`).
pub fn check(pr: &Project) -> R<()> {
    let has = |_: &str| true;
    let types = match pr.section("types") {
        Some(t) => t,
        None => return Ok(()),
    };
    let one = |cat: &str, ts: &Map| -> R<()> {
        let mut names: Vec<&String> = ts.keys().collect();
        names.sort();
        for n in names {
            if let Some(t) = Spec::from_file(pr, cat, ts.get(n).unwrap()) {
                validate(cat, n, &t, &has)?;
            }
        }
        Ok(())
    };
    for cat in ["door", "window", "wall", "floor", "roof", "ceiling", "column", "structuralcolumn", "footing"] {
        if let Some(Value::Obj(ts)) = types.get(type_path(cat).0) {
            one(cat, ts)?;
        }
    }
    if let Some(Value::Obj(runs)) = types.get("runs") {
        let mut cats: Vec<&String> = runs.keys().collect();
        cats.sort();
        for c in cats {
            if !is_run(c) {
                return Err(format!("`{}` has no run types; there are {}", c, RUN_CATS.join(", ")));
            }
            if let Some(Value::Obj(ts)) = runs.get(c) {
                one(c, ts)?;
            }
        }
    }
    if let Some(Value::Obj(ts)) = types.get("railing") {
        one("railing", ts)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    /// Writes `types_view` of the project at $TYPES_IN to $TYPES_OUT, to compare with the
    /// original's `inspect`.
    #[test]
    #[ignore]
    fn types_view_dump() {
        let inp = std::env::var("TYPES_IN").unwrap();
        let out = std::env::var("TYPES_OUT").unwrap();
        let v = crate::json::parse(&std::fs::read_to_string(inp).unwrap()).unwrap();
        let pr = crate::load::load(v).unwrap();
        std::fs::write(out, super::types_view(&pr).sorted().to_compact()).unwrap();
    }
}
