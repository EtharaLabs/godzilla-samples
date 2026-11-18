//! Reading a project file as the original reads it: its `format` checked first, then each
//! element (`element N: …`), then the library, then the rest of the model, each value as serde
//! reads it into the original's types; what the file holds that the original doesn't know is left
//! out and listed (JSON pointers: the elements' first, then the file's own keys, then what the
//! other sections hold, in the order a JSON object's keys sort).

pub mod builtin;
pub mod de;
pub mod dxf;
pub mod elements;
pub mod hooks;
pub mod ids;
pub mod refcheck;
pub mod refs;
pub mod notes;
pub mod schema;
pub mod sections;
pub mod sync;

use crate::json::{Map, Num, Value};
use crate::project::Project;
use de::{Ctx, R};
use schema::Ty;
use std::collections::BTreeMap;

/// The newest file format this reads.
pub const FORMAT: u64 = 17;

/// The model's rules, as opening a project checks them: the whole model check, then what its
/// elements point at.
pub fn check_opened(pr: &Project) -> R<()> {
    // the sections first, in the original's order where this checks them (its drafting styles,
    // its text and dimension types, which only a file can break, its reinforcement presets and
    // electrical settings, its materials, its detail groups, its project parameters, its view
    // templates and its run types), then what the other parts check, then each element, the
    // library's ids, and last what elements point at by their ids
    refcheck::styles(pr)?;
    crate::styles::text::check(pr)?;
    crate::styles::presets::check(pr)?;
    crate::styles::electrical::check(pr)?;
    refcheck::materials(pr)?;
    refcheck::detail_groups(pr)?;
    crate::styles::parameters::check_project(pr)?;
    refcheck::templates(pr)?;
    refcheck::runs(pr)?;
    crate::check::check(pr)?;
    refcheck::check(pr)
}

/// The kinds a library entry may be (and any `type:…`).
pub const LIB_KINDS: &[&str] = &[
    "cad",
    "cloud",
    "design-option",
    "detail-group",
    "dimension-type",
    "distribution-system",
    "family",
    "family-parameter",
    "family-type",
    "fill-pattern",
    "filled-region-type",
    "line-pattern",
    "line-style",
    "material",
    "option-set",
    "parameter",
    "phase",
    "phase-filter",
    "picture",
    "reinforcement-preset",
    "text-type",
    "view-filter",
    "view-template",
    "voltage",
    "wire-type",
];

/// What reading a file gives: the project, and the pointers of what it left out.
pub struct Read {
    pub project: Project,
    pub left_out: Vec<String>,
}

/// The file's `format`: a whole number, no newer than this one reads.
fn check_format(v: &Value) -> R<()> {
    if let Some(f) = v.get("format") {
        match f {
            Value::Num(Num::U(n)) => {
                if *n > FORMAT {
                    return Err(format!(
                        "it was saved by a newer BIMCraft (file format {}; this one reads up to {}): update BIMCraft to open it",
                        n, FORMAT
                    ));
                }
            }
            _ => return Err("`format` must be a whole number".into()),
        }
    }
    Ok(())
}

/// One element, as the original's `Element` reads it: its own GUID first (made when it has
/// none), then its category, then what its kind holds.
pub fn read_element(v: &Value, cx: &mut Ctx) -> R<Value> {
    let mut guid = None;
    let (cat, rest) = match v {
        Value::Obj(m) => {
            if let Some(g) = m.get("guid") {
                guid = Some(de::own_guid(g)?);
            }
            let c = m.get("category").ok_or_else(|| de::missing("category"))?;
            let cat = tag_of(c)?;
            let mut rest = Map::new();
            for (k, x) in &m.items {
                if k != "guid" && k != "category" {
                    rest.items.push((k.clone(), x.clone()));
                }
            }
            (cat, Value::Obj(rest))
        }
        Value::Arr(a) => {
            let c = a.first().ok_or_else(|| de::missing("category"))?;
            let cat = tag_of(c)?;
            (cat, Value::Arr(a[1..].to_vec()))
        }
        _ => return Err(de::invalid_type(v, "internally tagged enum Element")),
    };
    let body = de::de(&rest, &Ty::Named(elements::struct_of(cat).to_string()), cx)?;
    let mut out = Map::new();
    out.insert("guid", Value::Str(guid.unwrap_or_else(crate::rand::guid)));
    out.insert("category", Value::s(cat));
    if let Value::Obj(b) = body {
        out.items.extend(b.items);
    }
    Ok(Value::Obj(out))
}

/// An element of a detail group: the model's `Element` (its category, then what its kind holds;
/// a member's GUID is the member's own).
pub fn read_member_element(v: &Value, cx: &mut Ctx) -> R<Value> {
    let (cat, rest) = match v {
        Value::Obj(m) => {
            let c = m.get("category").ok_or_else(|| de::missing("category"))?;
            let cat = tag_of(c)?;
            let mut rest = Map::new();
            for (k, x) in &m.items {
                if k != "category" {
                    rest.items.push((k.clone(), x.clone()));
                }
            }
            (cat, Value::Obj(rest))
        }
        Value::Arr(a) => {
            let c = a.first().ok_or_else(|| de::missing("category"))?;
            let cat = tag_of(c)?;
            (cat, Value::Arr(a[1..].to_vec()))
        }
        _ => return Err(de::invalid_type(v, "internally tagged enum Element")),
    };
    let body = de::de(&rest, &Ty::Named(elements::struct_of(cat).to_string()), cx)?;
    let mut out = Map::new();
    out.insert("category", Value::s(cat));
    if let Value::Obj(b) = body {
        out.items.extend(b.items);
    }
    Ok(Value::Obj(out))
}

fn tag_of(c: &Value) -> R<&'static str> {
    match c {
        Value::Str(s) => match elements::CATEGORIES.iter().find(|x| **x == s.as_str()) {
            Some(x) => Ok(x),
            None => Err(de::unknown_variant(s, elements::CATEGORIES)),
        },
        _ => Err(de::invalid_type(c, "variant identifier")),
    }
}

/// Reads a project file's JSON as the original does.
pub fn read(v: Value) -> R<Read> {
    check_format(&v)?;
    // a file without its format is of the oldest (and read as one)
    let format = match v.get("format") {
        Some(Value::Num(Num::U(n))) => *n,
        _ => 0,
    };
    de::set_file_format(format);
    let r = read_at(v);
    de::set_file_format(FORMAT);
    r
}

fn read_at(v: Value) -> R<Read> {
    hooks::take_sizes();
    let root = match &v {
        Value::Obj(m) => m.clone(),
        _ => return Err(read_seq_root(&v)),
    };
    // the elements
    let mut cx = Ctx::new(true);
    let els_v = root.get("elements").cloned().unwrap_or(Value::Null);
    let els = match &els_v {
        Value::Obj(m) => m,
        _ => return Err(de::invalid_type(&els_v, "a map")),
    };
    let mut elements: BTreeMap<u64, Value> = BTreeMap::new();
    let mut guids: std::collections::HashMap<String, u64> = std::collections::HashMap::new();
    for (k, e) in de::sorted(els) {
        let id: u64 = k.parse().map_err(|_| format!("`{}` isn't an element id", k))?;
        cx.path = vec!["elements".to_string(), k.clone()];
        let el = read_element(e, &mut cx).map_err(|m| format!("element {}: {}", id, m))?;
        // two elements of one GUID, as the elements are visited
        if let Some(g) = el.get("guid").and_then(|g| g.as_str()) {
            if let Some(first) = guids.get(g) {
                return Err(format!("elements {} and {} have the same GUID {}", first, id, g));
            }
            guids.insert(g.to_string(), id);
        }
        elements.insert(id, el);
    }
    let el_left = std::mem::take(&mut cx.left);
    // the library
    let mut sec_left: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut library: BTreeMap<u64, Value> = BTreeMap::new();
    if let Some(lv) = root.get("library") {
        let lm = match lv {
            Value::Obj(m) => m,
            _ => return Err(de::invalid_type(lv, "a map")),
        };
        // the entries first, then their ids, then the library's own rules, entry by entry
        let mut cx = Ctx::new(false);
        let mut read: Vec<(String, Value)> = Vec::new();
        for (k, e) in de::sorted(lm) {
            cx.path = vec!["library".to_string(), k.clone()];
            let entry = de::de(e, &Ty::Named("LibEntry".into()), &mut cx)?;
            read.push((k.clone(), entry));
        }
        for (k, entry) in read {
            let id: u64 = k.parse().map_err(|_| format!("`{}` isn't a library id", k))?;
            library.insert(id, entry);
        }
        sync::check(&library)?;
        sec_left.insert("library".into(), cx.left);
    }
    // the model
    let (mut doc, top_left) = read_model(&root, &mut sec_left)?;
    let mut left_out = el_left;
    left_out.extend(top_left);
    for (_, l) in sec_left {
        left_out.extend(l);
    }
    // the text types notes of a size of their own take, made where the file hasn't them
    let sizes = hooks::take_sizes();
    if !sizes.is_empty() {
        if let Some(Value::Obj(tt)) = doc.get_mut("text_types") {
            for (name, size) in sizes {
                if !tt.contains(&name) {
                    tt.insert_sorted(
                        &name,
                        jobj! {"font" => "Arial", "size" => Value::f(size), "color" => Value::Arr(vec![Value::u(0), Value::u(0), Value::u(0)]), "border_offset" => 1.0, "border_pen" => 1u64},
                    );
                }
            }
        }
    }
    // what names the library's things, by name as the original holds it
    let lib = refs::Lib::new(&library);
    refs::walk(&mut refs::ToNames(&lib), &mut doc, &mut elements);
    // the library made to name what the model holds (the materials the types and families name
    // made where the file hasn't them), and the parts given ids
    let mut alloc = ids::Alloc::new(&library, &doc, &elements);
    sync::drop_stale(&mut library, &doc);
    make_materials(&mut doc);
    sync::add_missing(&mut library, &doc, &mut alloc);
    ids::repair(&mut doc, &mut elements, &library, &mut alloc);
    if let Some(n) = alloc.next_id {
        // an entry took an element id: elements count on from past it
        doc.insert("next_id", Value::u(n));
    }
    // and back to GUIDs, as the file holds them
    let lib = refs::Lib::new(&library);
    refs::walk(&mut refs::ToGuids(&lib), &mut doc, &mut elements);
    let mut project = Project::from_value(Value::Obj(doc));
    project.elements = elements;
    project.library = library;
    Ok(Read { project, left_out })
}

/// The materials the types and the families name that the file hasn't: grey, of no pattern.
fn make_materials(doc: &mut Map) {
    let mut names: Vec<String> = Vec::new();
    let add = |s: Option<&str>, names: &mut Vec<String>| {
        if let Some(s) = s {
            if !s.is_empty() && !names.iter().any(|n| n == s) {
                names.push(s.to_string());
            }
        }
    };
    if let Some(Value::Obj(types)) = doc.get("types") {
        for (k, sec) in &types.items {
            if let Value::Obj(ts) = sec {
                for (_, t) in &ts.items {
                    if k == "runs" {
                        if let Value::Obj(rs) = t {
                            for (_, r) in &rs.items {
                                add(r.get("material").and_then(|x| x.as_str()), &mut names);
                            }
                        }
                    } else if let Some(Value::Arr(ls)) = t.get("layers") {
                        for l in ls {
                            add(l.get("material").and_then(|x| x.as_str()), &mut names);
                        }
                    }
                }
            }
        }
    }
    if let Some(Value::Obj(fams)) = doc.get("families") {
        for (_, f) in &fams.items {
            let mut mparams: Vec<String> = Vec::new();
            if let Some(Value::Arr(ps)) = f.get("parameters") {
                for p in ps {
                    if p.get("kind").and_then(|k| k.as_str()) == Some("material") {
                        if let Some(n) = p.get("name").and_then(|x| x.as_str()) {
                            mparams.push(n.to_string());
                        }
                        add(p.get("value").and_then(|x| x.as_str()), &mut names);
                    }
                }
            }
            if let Some(Value::Obj(ts)) = f.get("types") {
                for (_, t) in &ts.items {
                    if let Value::Obj(tm) = t {
                        for (k, v) in &tm.items {
                            if mparams.contains(k) {
                                add(v.as_str(), &mut names);
                            }
                        }
                    }
                }
            }
            if let Some(Value::Arr(fs)) = f.get("forms") {
                for form in fs {
                    if let Some(m) = form.get("material").and_then(|x| x.as_str()) {
                        if !mparams.iter().any(|p| p == m) {
                            add(Some(m), &mut names);
                        }
                    }
                }
            }
        }
    }
    let mats = match doc.get_mut("materials") {
        Some(Value::Obj(m)) => m,
        _ => return,
    };
    for n in names {
        if !mats.contains(&n) {
            mats.insert_sorted(&n, jobj! {"color" => Value::Arr(vec![Value::u(200), Value::u(200), Value::u(200)]), "cut" => "none", "surface" => "none"});
        }
    }
}

/// The file's own keys, in the order the original writes them.
pub const MODEL_FIELDS: &[&str] = &[
    "format",
    "name",
    "uid",
    "units",
    "language",
    "room_area",
    "next_id",
    "types",
    "materials",
    "images",
    "clouds",
    "cads",
    "families",
    "parameters",
    "view_filters",
    "view_templates",
    "phases",
    "phase_filters",
    "phase_overrides",
    "option_sets",
    "line_weights",
    "standard",
    "object_styles",
    "line_patterns",
    "line_styles",
    "fill_patterns",
    "region_types",
    "text_types",
    "dimension_types",
    "detail_groups",
    "reinforcement",
    "voltages",
    "distribution_systems",
    "wire_types",
    "elements",
    "library",
];

/// The model's own sections (all but its elements and library), as serde reads `Model`.
fn read_model(root: &Map, sec_left: &mut BTreeMap<String, Vec<String>>) -> R<(Map, Vec<String>)> {
    let mut top_left = Vec::new();
    let mut got: BTreeMap<&str, Value> = BTreeMap::new();
    for (k, x) in de::sorted(root) {
        let f = match MODEL_FIELDS.iter().find(|f| **f == k.as_str()) {
            Some(f) => *f,
            None => {
                top_left.push(format!("/{}", k.replace('~', "~0").replace('/', "~1")));
                continue;
            }
        };
        if f == "elements" || f == "library" {
            continue;
        }
        let mut cx = Ctx::new(false);
        cx.path = vec![f.to_string()];
        let v = sections::read_section(f, x, &mut cx)?;
        if !cx.left.is_empty() {
            sec_left.entry(f.to_string()).or_default().extend(cx.left);
        }
        got.insert(f, v);
    }
    let mut doc = Map::new();
    for f in MODEL_FIELDS {
        if *f == "elements" || *f == "library" {
            doc.insert(f, Value::Null);
            continue;
        }
        match got.remove(f) {
            Some(v) => doc.insert(f, v),
            None => match sections::default_of(f) {
                Some(Some(v)) => doc.insert(f, v),
                Some(None) => {}
                None => return Err(de::missing(f)),
            },
        }
    }
    let doc = sections::finish(doc);
    Ok((doc, top_left))
}

/// A file whose top is a sequence: serde reads `Model` from it, its fields in order.
fn read_seq_root(v: &Value) -> String {
    match v {
        Value::Arr(a) => sections::read_seq_model(a).err().unwrap_or_default(),
        _ => de::invalid_type(v, "struct Model"),
    }
}
