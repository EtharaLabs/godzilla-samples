//! View filters: `filter`.
//!
//! The file keeps `view_filters` (name: {categories, rules?}, sorted by name, the section gone
//! with its last filter) and a `view-filter` library entry for each. A rule is a schedule
//! filter's: {field, op, value?}, a project parameter's field by its GUID and a value naming a
//! phase (or a design option) by its GUID. Views apply filters by GUID (`graphics.filters`).

#![allow(unused_imports)]

pub mod fields;
pub mod rooms;

use super::common::*;
use super::graphics::ovr::{self, sorted_items};
use super::graphics::vg;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;
use fields::Kind;

/// The categories a filter picks from, as the original lists them.
pub const CATEGORIES: &[&str] = &[
    "room",
    "door",
    "window",
    "wall",
    "floor",
    "ceiling",
    "roof",
    "column",
    "structuralcolumn",
    "footing",
    "beam",
    "rebar",
    "stripfooting",
    "pipe",
    "conduit",
    "cabletray",
    "duct",
    "cable",
    "downconductor",
    "groundconductor",
    "wire",
    "component",
    "stair",
    "ramp",
    "railing",
    "mass",
    "massfloor",
    "level",
];

pub const OPS: &[&str] = &[
    "equals",
    "not-equals",
    "greater",
    "greater-or-equal",
    "less",
    "less-or-equal",
    "contains",
    "not-contains",
    "begins-with",
    "not-begins-with",
    "ends-with",
    "not-ends-with",
    "has-value",
    "has-no-value",
];

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "filter" => cmd_filter(s, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
    .map_err(super::graphics::clip)
}

/// The project's view filters (name: as the file holds it).
pub fn view_filters(pr: &Project) -> Map {
    pr.section("view_filters").cloned().unwrap_or_default()
}

fn set_view_filters(pr: &mut Project, m: Map) {
    if m.is_empty() {
        pr.remove_top("view_filters");
    } else {
        pr.insert_top("view_filters", Value::Obj(m));
    }
}

/// A name a command is given: text, trimmed, of 1 to 256 characters.
pub fn name_param(p: &Value, cmd: &str, key: &str) -> R<Option<String>> {
    match p.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Str(s)) if s.chars().count() <= 256 => {
            let t = s.trim();
            Ok(if t.is_empty() { None } else { Some(t.to_string()) })
        }
        Some(v) => Err(format!("{}: `{}` must be text of at most 256 characters, got {}", cmd, key, v.to_compact())),
    }
}

/// A category filters pick from, else the original's message.
fn filter_category(cmd: &str, s: &str) -> R<String> {
    vg::singular_in(s, CATEGORIES).ok_or_else(|| {
        format!("{}: `{}` isn't a category filters pick from; there are: {}", cmd, s, CATEGORIES.join(", "))
    })
}

/// A rule as a command gives it.
#[derive(Clone, Debug)]
pub struct Rule {
    pub field: String,
    pub op: String,
    pub value: Option<Value>,
}

impl Rule {
    /// The rule as a reply shows it (and as the command gave it).
    pub fn value(&self) -> Value {
        let mut m = Map::new();
        m.insert("field", Value::s(&self.field));
        m.insert("op", Value::s(&self.op));
        if let Some(v) = &self.value {
            m.insert("value", v.clone());
        }
        Value::Obj(m)
    }
}

/// A rule as serde reads it: {field, op, value?}.
fn de_rule(v: &Value) -> R<Rule> {
    let m = match v {
        Value::Obj(m) => m,
        _ => return Err(format!("invalid type: {}, expected struct Filter", v.kind_name())),
    };
    let mut field = None;
    let mut op = None;
    let mut value = None;
    for (k, x) in sorted_items(m) {
        match k.as_str() {
            "field" => field = Some(ovr::de_string(&x)?),
            "op" => match &x {
                Value::Str(s) if OPS.contains(&s.as_str()) => op = Some(s.clone()),
                Value::Str(s) => {
                    let list: Vec<String> = OPS.iter().map(|o| format!("`{}`", o)).collect();
                    return Err(format!("unknown variant `{}`, expected one of {}", s, list.join(", ")));
                }
                _ => return Err(format!("invalid type: {}, expected string or map", x.kind_name())),
            },
            "value" => {
                value = if x.is_null() { None } else { Some(x.clone()) };
            }
            _ => return Err(format!("unknown field `{}`, expected one of `field`, `op`, `value`", k)),
        }
    }
    let field = field.ok_or_else(|| "missing field `field`".to_string())?;
    let op = op.ok_or_else(|| "missing field `op`".to_string())?;
    Ok(Rule { field, op, value })
}

/// A rule as the file holds it, read back by name.
fn named_rule(pr: &Project, cats: &[String], r: &Value) -> Rule {
    let mut field = r.get("field").and_then(|x| x.as_str()).unwrap_or("").to_string();
    if let Some(n) = crate::styles::common::name_of_guid(pr, "parameter", &field) {
        field = n;
    }
    let _ = cats;
    let op = r.get("op").and_then(|x| x.as_str()).unwrap_or("").to_string();
    let mut value = r.get("value").cloned();
    if let Some(Value::Str(v)) = &value {
        let named = match field.as_str() {
            "Phase Created" | "Phase Demolished" => crate::styles::common::name_of_guid(pr, "phase", v),
            "Design Option" => crate::styles::common::name_of_guid(pr, "design-option", v),
            _ => None,
        };
        if let Some(n) = named {
            value = Some(Value::s(&n));
        }
    }
    Rule { field, op, value }
}

/// A filter's categories as the file holds them.
fn cats_of(f: &Value) -> Vec<String> {
    f.get("categories")
        .and_then(|c| c.as_arr())
        .map(|a| a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect())
        .unwrap_or_default()
}

/// A filter's rules, by name.
fn rules_of(pr: &Project, f: &Value) -> Vec<Rule> {
    let cats = cats_of(f);
    f.get("rules").and_then(|r| r.as_arr()).map(|a| a.iter().map(|r| named_rule(pr, &cats, r)).collect()).unwrap_or_default()
}

/// A rule's value against what its field holds: "filter on `F`: …", or None where it holds.
fn rule_error(r: &Rule, kind: Kind) -> Option<String> {
    if matches!(r.op.as_str(), "has-value" | "has-no-value") {
        return None;
    }
    let text_op = matches!(
        r.op.as_str(),
        "contains" | "not-contains" | "begins-with" | "not-begins-with" | "ends-with" | "not-ends-with"
    );
    let shown = r.value.as_ref().map(|v| v.to_compact()).unwrap_or_else(|| "null".into());
    let pre = format!("filter on `{}`: ", r.field);
    match kind {
        Kind::Text => match &r.value {
            Some(Value::Str(_)) => None,
            _ => Some(format!("{}it compares text, not {}", pre, shown)),
        },
        Kind::YesNo => {
            if text_op {
                return Some(format!("{}it holds {}, and only text contains, begins or ends", pre, kind.holds()));
            }
            if !matches!(r.op.as_str(), "equals" | "not-equals") {
                return Some(format!("{}yes or no only equals or doesn't", pre));
            }
            match &r.value {
                Some(Value::Bool(_)) => None,
                _ => Some(format!("{}it compares yes or no, not {}", pre, shown)),
            }
        }
        _ => {
            if text_op {
                return Some(format!("{}it holds {}, and only text contains, begins or ends", pre, kind.holds()));
            }
            match &r.value {
                Some(Value::Num(_)) => None,
                _ => Some(format!("{}it compares {}, not {}", pre, kind.compares(), shown)),
            }
        }
    }
}

/// Checks rules against categories (each field one of every category's, its value of its kind),
/// as a schedule's filters are checked; the message after `filter: `.
fn check_rules(pr: &Project, cats: &[String], rules: &[Rule]) -> R<Vec<(Rule, Vec<fields::Field>)>> {
    let mut out = Vec::new();
    for r in rules {
        // category by category: the field one of its, the value one the field compares
        let mut fs = Vec::new();
        for c in cats {
            match fields::field(pr, c, &r.field) {
                Some(f) => {
                    if let Some(e) = rule_error(r, f.kind) {
                        return Err(e);
                    }
                    fs.push(f)
                }
                None => {
                    let names: Vec<String> = fields::fields_of(pr, c).into_iter().map(|f| f.name).collect();
                    return Err(format!(
                        "filter: `{}` isn't a field of {}s; there are: {}",
                        r.field,
                        c,
                        names.join(", ")
                    ));
                }
            }
        }
        out.push((r.clone(), fs));
    }
    Ok(out)
}

/// The elements a filter picks out, by id.
pub fn matches(pr: &Project, cats: &[String], rules: &[Rule]) -> Vec<u64> {
    let mut ids = Vec::new();
    for c in cats {
        let fs: Vec<Option<fields::Field>> = rules.iter().map(|r| fields::field(pr, c, &r.field)).collect();
        for id in fields::elements_of(pr, c) {
            let ok = rules.iter().zip(fs.iter()).all(|(r, f)| match f {
                Some(f) => {
                    let v = fields::value_of(pr, c, id, f);
                    fields::holds(v.as_ref(), f.kind, &r.op, r.value.as_ref())
                }
                None => false,
            });
            if ok {
                ids.push(id);
            }
        }
    }
    ids.sort();
    ids.dedup();
    ids
}

/// The elements the project's filter of this name picks out.
pub fn matches_of(pr: &Project, name: &str) -> Vec<u64> {
    let Some(f) = view_filters(pr).get(name).cloned() else { return Vec::new() };
    let cats = cats_of(&f);
    let rules = rules_of(pr, &f);
    matches(pr, &cats, &rules)
}

/// A rule as the file holds it: a project parameter by its GUID, a phase or a design option it
/// names exactly by its GUID.
fn file_rule(pr: &Project, r: &Rule, fs: &[fields::Field]) -> Value {
    let field = fs.first().and_then(|f| f.param.clone()).unwrap_or_else(|| r.field.clone());
    let mut m = Map::new();
    m.insert("field", Value::s(&field));
    m.insert("op", Value::s(&r.op));
    if let Some(v) = &r.value {
        let mut v = v.clone();
        if let Value::Str(t) = &v {
            let g = match r.field.as_str() {
                "Phase Created" | "Phase Demolished" => {
                    if crate::styles::phasing::phases(pr).iter().any(|x| x == t) {
                        pr.lib_guid("phase", t)
                    } else {
                        None
                    }
                }
                "Design Option" => pr.lib_guid("design-option", t),
                _ => None,
            };
            if let Some(g) = g {
                v = Value::s(&g);
            }
        }
        m.insert("value", v);
    }
    Value::Obj(m)
}

fn reply(pr: &Project, name: &str, cats: &[String], rules: &[Rule]) -> Value {
    jobj! {
        "categories" => cats.to_vec(),
        "matches" => matches(pr, cats, rules),
        "name" => name,
        "rules" => Value::Arr(rules.iter().map(|r| r.value()).collect()),
    }
}

fn cmd_filter(s: &mut Session, p: &Value) -> R<Value> {
    let cmd = "filter";
    let name = name_param(p, cmd, "name")?.ok_or_else(|| format!("{}: `name` is required", cmd))?;
    let delete = crate::commands::params::opt_bool(p, cmd, "delete")?.unwrap_or(false);
    let pr = &mut s.project;
    let name = vg::entry_name(pr, "view-filter", &name);
    let mut all = view_filters(pr);
    if delete {
        if !all.contains(&name) {
            return Err(format!("{}: there's no view filter `{}`", cmd, name));
        }
        delete_filter(pr, &name);
        return Ok(jobj! {"deleted" => true, "name" => name});
    }
    let cats_given = match get(p, "categories") {
        None => None,
        Some(Value::Arr(a)) => {
            let mut out: Vec<String> = Vec::new();
            for x in a {
                match x {
                    Value::Str(c) => {
                        let c = filter_category(cmd, c)?;
                        if !out.contains(&c) {
                            out.push(c);
                        }
                    }
                    _ => return Err(format!("{}: `categories`: {} is not a category", cmd, x.to_compact())),
                }
            }
            out.sort();
            Some(out)
        }
        Some(v) => {
            return Err(format!(
                "{}: `categories` is a list of categories, [\"walls\", \"doors\"…], not {}",
                cmd,
                v.to_compact()
            ))
        }
    };
    let existing = all.get(&name).cloned();
    if existing.is_none() && cats_given.is_none() {
        return Err(format!("{}: a new filter needs `categories`, [\"walls\", \"doors\"…]", cmd));
    }
    let rules_given = match get(p, "rules") {
        None => None,
        Some(Value::Arr(a)) if a.len() <= 64 => {
            let mut out = Vec::new();
            for x in a {
                out.push(de_rule(x).map_err(|e| format!("{}: rule {}: {}", cmd, x.clone().sorted().to_compact(), e))?);
            }
            Some(out)
        }
        Some(v) => return Err(format!("{}: `rules` is [{{field, op, value}}, …] (up to 64), not {}", cmd, v.to_compact())),
    };
    if cats_given.as_ref().map(|c| c.is_empty()).unwrap_or(false) {
        return Err(format!("{}: it needs categories, one or more of: {}", cmd, CATEGORIES.join(", ")));
    }
    let cats = match cats_given {
        Some(c) => c,
        None => cats_of(existing.as_ref().unwrap()),
    };
    let rules = match rules_given {
        Some(r) => r,
        None => existing.as_ref().map(|f| rules_of(pr, f)).unwrap_or_default(),
    };
    let checked = check_rules(pr, &cats, &rules).map_err(|e| format!("{}: {}", cmd, e))?;
    let mut f = Map::new();
    f.insert("categories", Value::from(cats.clone()));
    if !checked.is_empty() {
        f.insert("rules", Value::Arr(checked.iter().map(|(r, fs)| file_rule(pr, r, fs)).collect()));
    }
    all.insert_sorted(&name, Value::Obj(f));
    set_view_filters(pr, all);
    crate::styles::common::lib_ensure(pr, "view-filter", &name);
    Ok(reply(pr, &name, &cats, &rules))
}

/// Takes a filter away: its entry, and every view and template stops applying it.
pub fn delete_filter(pr: &mut Project, name: &str) {
    let gd = pr.lib_guid("view-filter", name);
    let mut all = view_filters(pr);
    all.remove(name);
    set_view_filters(pr, all);
    crate::styles::common::lib_remove(pr, "view-filter", name);
    let Some(gd) = gd else { return };
    fn strip(g: &mut Map, gd: &str) {
        if let Some(Value::Arr(a)) = g.get("filters").cloned() {
            let kept: Vec<Value> = a.into_iter().filter(|f| f.get("filter").and_then(|x| x.as_str()) != Some(gd)).collect();
            vg::gput(g, "filters", if kept.is_empty() { None } else { Some(Value::Arr(kept)) });
        }
    }
    let ids: Vec<u64> = pr.elements.keys().copied().collect();
    for id in ids {
        let mut g = vg::own(pr, id);
        if g.contains("filters") {
            let before = g.clone();
            strip(&mut g, &gd);
            if g != before {
                vg::store_in(pr, id, g);
            }
        }
    }
    if let Some(Value::Obj(ts)) = pr.doc.get_mut("view_templates") {
        for (_, t) in ts.items.iter_mut() {
            if let Some(Value::Obj(g)) = t.get_mut("graphics") {
                strip(g, &gd);
                if g.is_empty() {
                    t.remove("graphics");
                }
            }
        }
    }
}

/// Whether a view or a template applies the filter of this name (`purge` keeps those).
pub fn used(pr: &Project, name: &str) -> bool {
    let Some(gd) = pr.lib_guid("view-filter", name) else { return false };
    let applies = |g: &Value| {
        g.get("filters")
            .and_then(|f| f.as_arr())
            .map(|a| a.iter().any(|f| f.get("filter").and_then(|x| x.as_str()) == Some(gd.as_str())))
            .unwrap_or(false)
    };
    pr.elements.values().any(|e| e.get("graphics").map(applies).unwrap_or(false))
        || vg::templates(pr).items.iter().any(|(_, t)| t.get("graphics").map(applies).unwrap_or(false))
}

/// The model rules of this part (checked with the graphics', in the model's order).
pub fn check(pr: &Project) -> R<()> {
    let _ = pr;
    Ok(())
}

/// Each view filter's categories are ones filters pick from, and its rules a schedule filter's of
/// all of them.
pub fn check_all(pr: &Project) -> R<()> {
    for (k, f) in &view_filters(pr).items {
        let pre = |e: String| format!("view filter `{}`: {}", k, e);
        let cats = cats_of(f);
        for c in &cats {
            if !CATEGORIES.contains(&c.as_str()) {
                return Err(pre(format!(
                    "`{}` isn't a category filters pick from; there are: {}",
                    c,
                    CATEGORIES.join(", ")
                )));
            }
        }
        if cats.is_empty() {
            return Err(pre(format!("it needs categories, one or more of: {}", CATEGORIES.join(", "))));
        }
        let rules = rules_of(pr, f);
        check_rules(pr, &cats, &rules).map_err(pre)?;
    }
    Ok(())
}

/// What `inspect` says of the sections this part keeps: the view filters, by name, their rules'
/// fields and values named.
pub fn inspect_entries(s: &Session, out: &mut Vec<(String, Value)>) {
    let pr = &s.project;
    let mut m = Map::new();
    for (k, f) in &view_filters(pr).items {
        let mut e = Map::new();
        e.insert("categories", Value::from(cats_of(f)));
        if f.get("rules").and_then(|r| r.as_arr()).map(|a| !a.is_empty()).unwrap_or(false) {
            e.insert("rules", Value::Arr(rules_of(pr, f).iter().map(|r| r.value()).collect()));
        }
        m.insert(k, Value::Obj(e));
    }
    out.push(("view_filters".into(), Value::Obj(m)));
}
