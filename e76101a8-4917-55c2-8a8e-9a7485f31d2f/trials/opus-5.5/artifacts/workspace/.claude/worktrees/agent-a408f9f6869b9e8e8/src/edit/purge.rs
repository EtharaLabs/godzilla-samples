//! Purge Unused: what nothing uses, taken out.
//!
//! Each round finds, in the project as the round finds it, what nothing uses of each kind asked
//! for (types of categories, families, families' types, materials, pictures, view filters, view
//! templates, in that order, each sorted by name), and takes it all out; then again, for what
//! that left unused (a material only a purged type was made of, the picture of a purged
//! material, a filter only a purged template applied), until a round finds nothing.

use super::common::*;
use super::library_util::*;
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;
use std::collections::HashSet;

const KINDS: &[&str] = &["type", "family", "material", "picture", "filter", "template"];

/// Something purge takes out.
enum Item {
    CategoryType { cat: String, loc: Loc, name: String },
    Family(String),
    FamilyType { family: String, name: String },
    Material(String),
    Picture(String),
    Filter(String),
    Template(String),
}

impl Item {
    /// (kind, name) as the reply lists it.
    fn label(&self) -> (String, String) {
        match self {
            Item::CategoryType { cat, name, .. } => (format!("{} type", cat), name.clone()),
            Item::Family(n) => ("family".into(), n.clone()),
            Item::FamilyType { family, name } => ("family type".into(), qualified(family, name)),
            Item::Material(n) => ("material".into(), n.clone()),
            Item::Picture(n) => ("picture".into(), n.clone()),
            Item::Filter(n) => ("view filter".into(), n.clone()),
            Item::Template(n) => ("view template".into(), n.clone()),
        }
    }
}

fn kinds_param(p: &Value) -> R<Vec<String>> {
    match p.get("kinds") {
        None | Some(Value::Null) => Ok(vec!["type".to_string(), "family".to_string()]),
        Some(Value::Arr(a)) => {
            let mut out: Vec<String> = Vec::new();
            for v in a {
                match v.as_str() {
                    Some(k) if KINDS.contains(&k) => {
                        if !out.iter().any(|x| x == k) {
                            out.push(k.to_string());
                        }
                    }
                    _ => {
                        return Err(format!(
                            "purge: `kinds` holds {}, not {}",
                            KINDS.join(", "),
                            v.to_compact()
                        ))
                    }
                }
            }
            Ok(out)
        }
        Some(v) => Err(format!("purge: `kinds` is a list of what to purge, not {}", v.to_compact())),
    }
}

pub fn run(s: &mut Session, p: &Value) -> R<Value> {
    purge(s, p).map_err(clip_error)
}

fn purge(s: &mut Session, p: &Value) -> R<Value> {
    let kinds = kinds_param(p)?;
    let dry_run = crate::commands::params::opt_bool(p, "purge", "dry_run")?.unwrap_or(false);
    let mut pr = s.project.clone();
    let mut removed: Vec<Value> = Vec::new();
    let mut seen: HashSet<(String, String)> = HashSet::new();
    // the materials taken out, by GUID: an element's own value may still name one
    let mut materials_out: Vec<(String, String)> = Vec::new();
    loop {
        let items = unused(&pr, &kinds);
        let mut any = false;
        for it in &items {
            let label = it.label();
            if !seen.insert(label.clone()) {
                continue;
            }
            any = true;
            if let Item::Material(m) = it {
                if let Some(g) = pr.lib_guid("material", m) {
                    materials_out.push((g, m.clone()));
                }
            }
            take_out(&mut pr, it);
            removed.push(jobj! {"kind" => label.0, "name" => label.1});
        }
        if !any {
            break;
        }
    }
    if !dry_run {
        own_values_hold(&pr, &materials_out)?;
        s.project = pr;
    }
    Ok(jobj! {"count" => removed.len(), "dry_run" => dry_run, "removed" => Value::Arr(removed)})
}

/// The model's rule that an element's own value of a material parameter (a component's, a
/// door's…) is a material of the library: purge doesn't count those values as uses, so taking a
/// material only they name out is refused by it, as the original's check refuses it.
fn own_values_hold(pr: &Project, materials_out: &[(String, String)]) -> R<()> {
    if materials_out.is_empty() {
        return Ok(());
    }
    for (id, e) in &pr.elements {
        let Some(params) = e.get("params").and_then(|p| p.as_obj()) else { continue };
        let mut keys: Vec<&(String, Value)> = params.items.iter().collect();
        keys.sort_by(|a, b| a.0.cmp(&b.0));
        for (k, v) in keys {
            if k == "Paint" {
                continue;
            }
            let Some(g) = v.as_str() else { continue };
            if let Some((_, name)) = materials_out.iter().find(|(mg, _)| mg == g) {
                return Err(check_error(format!(
                    "{} {}: material `{}` isn't in the library; add it with `material`",
                    cat_of(e),
                    id,
                    name
                )));
            }
        }
    }
    Ok(())
}

/// Every string a value holds, anywhere in it.
fn strings<'a>(v: &'a Value, out: &mut HashSet<&'a str>) {
    match v {
        Value::Str(s) => {
            out.insert(s.as_str());
        }
        Value::Arr(a) => a.iter().for_each(|x| strings(x, out)),
        Value::Obj(m) => m.items.iter().for_each(|(_, x)| strings(x, out)),
        _ => {}
    }
}

fn sorted_keys(pr: &Project, section: &str) -> Vec<String> {
    let mut v: Vec<String> = pr.section(section).map(|m| m.keys().cloned().collect()).unwrap_or_default();
    v.sort();
    v
}

fn used_guid(pr: &Project, kind: &str, name: &str, used: &HashSet<&str>) -> bool {
    pr.lib_guid(kind, name).map(|g| used.contains(g.as_str())).unwrap_or(false)
}

/// What nothing uses, of the kinds asked for, in the order the reply lists it.
fn unused(pr: &Project, kinds: &[String]) -> Vec<Item> {
    let has = |k: &str| kinds.iter().any(|x| x == k);
    let mut out: Vec<Item> = Vec::new();
    // what elements are of: their types and families
    let mut el_types: HashSet<&str> = HashSet::new();
    let mut el_families: HashSet<&str> = HashSet::new();
    for e in pr.elements.values() {
        if let Some(t) = e.get("type").and_then(|t| t.as_str()) {
            el_types.insert(t);
        }
        if let Some(f) = e.get("family").and_then(|t| t.as_str()) {
            el_families.insert(f);
        }
    }
    // types of categories: a category none of whose types is used keeps the one a new element of
    // it would take (the starter's, else its first)
    if has("type") {
        let mut cats = type_categories(pr);
        cats.sort_by(|a, b| a.0.cmp(&b.0));
        for (cat, loc) in cats {
            let names = loc_names(pr, &loc);
            let kind = type_kind(&cat);
            let used: Vec<bool> = names.iter().map(|n| used_guid(pr, &kind, n, &el_types)).collect();
            let keep: Option<String> = if used.iter().any(|u| *u) {
                None
            } else {
                preferred_type(&cat)
                    .filter(|p| names.iter().any(|n| n == p))
                    .map(|p| p.to_string())
                    .or_else(|| names.first().cloned())
            };
            for (n, u) in names.iter().zip(used.iter()) {
                if !*u && keep.as_deref() != Some(n.as_str()) {
                    out.push(Item::CategoryType { cat: cat.clone(), loc: loc.clone(), name: n.clone() });
                }
            }
        }
    }
    // families
    let mut families_out: HashSet<String> = HashSet::new();
    if has("family") {
        for f in family_names(pr) {
            if !used_guid(pr, "family", &f, &el_families) {
                families_out.insert(f.clone());
                out.push(Item::Family(f));
            }
        }
    }
    // the types of the families that stay: a family none of whose types is used keeps its last
    if has("type") {
        for f in family_names(pr) {
            if families_out.contains(&f) {
                continue;
            }
            let Some(fam) = families(pr).and_then(|m| m.get(&f)) else { continue };
            let names = family_type_names(fam);
            let used: Vec<bool> = names.iter().map(|t| used_guid(pr, "family-type", &qualified(&f, t), &el_types)).collect();
            let keep: Option<String> = if used.iter().any(|u| *u) { None } else { names.last().cloned() };
            for (t, u) in names.iter().zip(used.iter()) {
                if !*u && keep.as_deref() != Some(t.as_str()) {
                    out.push(Item::FamilyType { family: f.clone(), name: t.clone() });
                }
            }
        }
    }
    // materials: in a type (its layers, a run's), in a family, or painted on an element
    if has("material") {
        let mut used: HashSet<&str> = HashSet::new();
        if let Some(v) = pr.get("types") {
            strings(v, &mut used);
        }
        if let Some(v) = pr.get("families") {
            strings(v, &mut used);
        }
        for e in pr.elements.values() {
            if let Some(paint) = e.get("params").and_then(|p| p.get("Paint")) {
                strings(paint, &mut used);
            }
        }
        for m in sorted_keys(pr, "materials") {
            if !used_guid(pr, "material", &m, &used) {
                out.push(Item::Material(m));
            }
        }
    }
    // pictures: what a material's texture is made of
    if has("picture") {
        let mut used: HashSet<&str> = HashSet::new();
        if let Some(v) = pr.get("materials") {
            strings(v, &mut used);
        }
        for id in sorted_keys(pr, "images") {
            if !used_guid(pr, "picture", &id, &used) {
                out.push(Item::Picture(id));
            }
        }
    }
    // what views' graphics name: filters and templates (and the filters templates apply)
    let mut graphics: HashSet<&str> = HashSet::new();
    if has("filter") || has("template") {
        for e in pr.elements.values() {
            if let Some(g) = e.get("graphics") {
                strings(g, &mut graphics);
            }
        }
    }
    if has("filter") {
        let mut used = graphics.clone();
        if let Some(v) = pr.get("view_templates") {
            strings(v, &mut used);
        }
        for f in sorted_keys(pr, "view_filters") {
            if !used_guid(pr, "view-filter", &f, &used) {
                out.push(Item::Filter(f));
            }
        }
    }
    if has("template") {
        for t in sorted_keys(pr, "view_templates") {
            if !used_guid(pr, "view-template", &t, &graphics) {
                out.push(Item::Template(t));
            }
        }
    }
    out
}

/// Takes an entry of a section away, and the section with its last entry.
fn remove_entry(pr: &mut Project, section: &str, name: &str, drop_empty: bool) {
    let empty = match pr.get_mut(section).and_then(|v| v.as_obj_mut()) {
        Some(m) => {
            m.remove(name);
            m.is_empty()
        }
        None => false,
    };
    if empty && drop_empty {
        pr.remove_top(section);
    }
}

fn take_out(pr: &mut Project, it: &Item) {
    match it {
        Item::CategoryType { cat, loc, name } => {
            if let Some(m) = loc_map_mut(pr, loc) {
                m.remove(name);
            }
            lib_remove(pr, &type_kind(cat), name);
        }
        Item::Family(f) => remove_family(pr, f),
        Item::FamilyType { family, name } => remove_family_type(pr, family, name),
        Item::Material(m) => {
            remove_entry(pr, "materials", m, false);
            lib_remove(pr, "material", m);
        }
        Item::Picture(id) => {
            remove_entry(pr, "images", id, true);
            lib_remove(pr, "picture", id);
        }
        Item::Filter(f) => {
            remove_entry(pr, "view_filters", f, true);
            lib_remove(pr, "view-filter", f);
        }
        Item::Template(t) => {
            remove_entry(pr, "view_templates", t, true);
            lib_remove(pr, "view-template", t);
        }
    }
}
