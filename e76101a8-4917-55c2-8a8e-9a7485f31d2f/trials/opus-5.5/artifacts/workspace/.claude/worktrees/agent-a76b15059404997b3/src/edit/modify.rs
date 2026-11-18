//! Modify: an element's fields as `elements` shows them, of one element or several.
//!
//! As the original does it: for each element named (in the order named), `category` must be its
//! own, `level` and `top_level` given as text are read as a level (by name, id or GUID, or a plan
//! view's), and the fields given are merged over the element's (an object into an object, as a
//! JSON merge patch: a null takes a key away) and read back as the element of its category, the
//! fields in name order (`modify: element N: ` and serde's message for the first that isn't one
//! of its type). Then, element by element in id order, what the fields name has to be there: its
//! project parameters, its type, its levels, its host… (`wall N: type `X` doesn't exist`), and the
//! rest of the model's rules hold after the change, or nothing changes. One `id`: the reply is the
//! element as `elements` shows it; `ids`: `{modified: [ids]}`.

use super::common::*;
use super::modify_de::{self as de, T};
use super::modify_schema::{self as schema, Field, Role, Rule, Skip};
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;

const CMD: &str = "modify";

/// What a change gave each element, for the checks after it and the reply.
struct Changed {
    id: u64,
    cat: String,
    el: Value,
    /// The fields given (after merging), by name.
    given: Vec<(String, Value)>,
    /// The fields given as an element's id, which `elements` shows as that id until the file is
    /// read again.
    by_id: Vec<(String, Value)>,
}

pub fn run(s: &mut Session, p: &Value) -> R<Value> {
    let list_reply = p.get("ids").is_some();
    let ids = ids_param(&s.project, CMD, p)?;
    let mut patch: Vec<(String, Value)> = Vec::new();
    if let Some(m) = p.as_obj() {
        for (k, v) in &m.items {
            if k == "id" || k == "ids" {
                continue;
            }
            match patch.iter_mut().find(|(kk, _)| kk == k) {
                Some(slot) => slot.1 = v.clone(),
                None => patch.push((k.clone(), v.clone())),
            }
        }
    }
    let mut changed: Vec<Changed> = Vec::new();
    {
        let pr = &s.project;
        let mut resolved: Option<Vec<(String, Value)>> = None;
        for id in &ids {
            let e = pr.el(*id).cloned().unwrap_or(Value::Null);
            let cat = cat_of(&e).to_string();
            if let Some((_, c)) = patch.iter().find(|(k, _)| k == "category") {
                if c.as_str() != Some(cat.as_str()) {
                    return Err(format!("{}: `category` can't change; delete the element and create another", CMD));
                }
            }
            if resolved.is_none() {
                resolved = Some(resolve_levels(pr, &patch)?);
            }
            let fields: Vec<(String, Value)> =
                resolved.as_ref().unwrap().iter().filter(|(k, _)| k != "category").cloned().collect();
            let c = apply(pr, *id, &cat, &e, &fields).map_err(|m| format!("{}: element {}: {}", CMD, id, m))?;
            changed.push(c);
        }
    }
    // what the fields name, element by element in id order
    let mut order: Vec<usize> = (0..changed.len()).collect();
    order.sort_by_key(|i| changed[*i].id);
    for i in &order {
        let c = &changed[*i];
        check_names(&s.project, c, &changed).map_err(|m| format!("{} {}: {}", c.cat, c.id, m))?;
    }
    for i in &order {
        if changed[*i].cat == "room" {
            freeze(&s.project, &mut changed[*i])?;
        }
    }
    for c in &mut changed {
        finish(&s.project, c);
    }
    for c in &mut changed {
        if after(c, "sketch").is_some() {
            number_sketch(&mut s.project, &mut c.el);
        }
    }
    for c in &changed {
        s.project.elements.insert(c.id, c.el.clone());
    }
    if list_reply {
        return Ok(jobj! {"modified" => Value::Arr(ids.iter().map(|i| Value::u(*i)).collect())});
    }
    let Some(c) = changed.first() else {
        return Ok(jobj! {"modified" => Value::Arr(Vec::new())});
    };
    let by_id = c.by_id.clone();
    let id = c.id;
    let mut view = element_view(s, id);
    for (k, n) in by_id {
        view.set(&k, n);
    }
    Ok(view)
}

// ---------------------------------------------------------------- levels by name

/// `level` and `top_level` given as text, read as a level by name, id or GUID (or a plan view's
/// level): its GUID. Other values go on as they are, to be read as an element's id.
fn resolve_levels(pr: &Project, patch: &[(String, Value)]) -> R<Vec<(String, Value)>> {
    let mut out: Vec<(String, Value)> = patch.to_vec();
    for key in ["level", "top_level"] {
        let Some(slot) = out.iter_mut().find(|(k, _)| k == key) else { continue };
        if let Value::Str(s) = &slot.1 {
            let lv = level_by_text(pr, key, &slot.1, s)?;
            slot.1 = Value::Str(pr.guid_of(lv).unwrap_or_default());
        }
    }
    Ok(out)
}

fn level_by_text(pr: &Project, key: &str, v: &Value, s: &str) -> R<u64> {
    let not = || format!("{}: `{}`: {} is not a level or a plan view", CMD, key, v.to_compact());
    let t = s.trim();
    let by = |id: u64| crate::model::level_of_view(pr, id).ok_or_else(not);
    if let Ok(id) = t.parse::<u64>() {
        if !pr.elements.contains_key(&id) {
            return Err(not());
        }
        return by(id);
    }
    if let Some(g) = strict_guid(t) {
        return match pr.find_guid(&g) {
            Some(id) => by(id),
            None => Err(not()),
        };
    }
    let levels = crate::model::levels(pr);
    for id in &levels {
        if crate::model::name(pr, *id) == s {
            return Ok(*id);
        }
    }
    for id in pr.ids_of("planview") {
        if crate::model::name(pr, id) == s {
            if let Some(l) = crate::model::level_of_view(pr, id) {
                return Ok(l);
            }
        }
    }
    let names: Vec<String> = levels.iter().map(|l| crate::model::name(pr, *l)).collect();
    Err(format!("{}: no level or plan view named `{}` (the levels are: {})", CMD, s, names.join(", ")))
}

// ---------------------------------------------------------------- merging and reading back

fn is_skipped(skip: Skip, v: &Value) -> bool {
    match skip {
        Skip::Never => false,
        Skip::Null => v.is_null(),
        Skip::Zero => v.as_f64() == Some(0.0),
        Skip::False => v.as_bool() == Some(false),
        Skip::True => v.as_bool() == Some(true),
        Skip::Empty => match v {
            Value::Arr(a) => a.is_empty(),
            Value::Obj(m) => m.is_empty(),
            Value::Str(s) => s.is_empty(),
            Value::Null => true,
            _ => false,
        },
        Skip::Eq(x) => v.as_f64() == Some(x),
        Skip::Str(x) => v.as_str() == Some(x),
        Skip::ZeroP2 => pt(Some(v)) == Some([0.0, 0.0]),
        Skip::Fn(f) => f(v),
    }
}

/// The fields given merged over the element and read back as its category's: the element as the
/// file will keep it, or serde's message for the first field (in name order) that isn't right.
fn apply(pr: &Project, id: u64, cat: &str, e: &Value, patch: &[(String, Value)]) -> R<Changed> {
    let fields = schema::fields(cat);
    let mut keys: Vec<&(String, Value)> = patch.iter().collect();
    keys.sort_by(|a, b| a.0.cmp(&b.0));
    let mut given: Vec<(String, Value)> = Vec::new();
    let mut by_id: Vec<(String, Value)> = Vec::new();
    for (k, v) in keys {
        let fd: Option<&Field> = fields.and_then(|fs| fs.iter().find(|f| f.name == k));
        let Some(fd) = fd else {
            if let Some(fs) = fields {
                let names: Vec<&str> = fs.iter().map(|f| f.name).collect();
                return Err(de::unknown_field(k, &names));
            }
            given.push((k.clone(), v.clone()));
            continue;
        };
        let merged = if let Value::Obj(_) = v {
            let mut cur = current(pr, e, fd);
            de::merge_patch(&mut cur, v);
            cur
        } else {
            v.clone()
        };
        de::de(pr, &merged, &fd.t)?;
        if de::has_ref(&fd.t) && de::ref_by_id(pr, &merged, &fd.t) {
            by_id.push((k.clone(), de::reply_form(pr, &merged, &fd.t)));
        }
        given.push((k.clone(), merged));
    }
    if cat == "line" {
        // a detail line is one kind of curve, with what goes with it
        let mut m = Map::new();
        for k in de::CURVE_FIELDS {
            let v = given.iter().find(|(kk, _)| kk == k).map(|(_, v)| v.clone()).or_else(|| e.get(k).cloned());
            if let Some(v) = v {
                m.insert(k, v);
            }
        }
        de::check_curve(&m)?;
    }
    // another family: the type and the values held are its own now (or not)
    if given.iter().any(|(k, _)| k == "family") {
        if !given.iter().any(|(k, _)| k == "type") {
            if let Some(g) = e.get("type").and_then(|t| t.as_str()) {
                let full = pr.lib_name(g).unwrap_or_else(|| g.to_string());
                let name = match family_of_element(pr, e) {
                    Some(f) => full.strip_prefix(&format!("{}: ", f)).map(|x| x.to_string()).unwrap_or(full),
                    None => full,
                };
                given.push(("type".to_string(), Value::Str(name)));
            }
        }
        if !given.iter().any(|(k, _)| k == "params") && e.get("params").is_some() {
            if let Some(fd) = fields.and_then(|fs| fs.iter().find(|f| f.role == Role::Params)) {
                given.push(("params".to_string(), current(pr, e, fd)));
            }
        }
    }
    let el = build(pr, cat, e, fields, &given);
    Ok(Changed { id, cat: cat.to_string(), el, given, by_id })
}

/// A field's value as the original holds it in memory, for a merge: `params` by the parameters'
/// names, the rest as the file has it.
fn current(pr: &Project, e: &Value, fd: &Field) -> Value {
    let v = e.get(fd.name).cloned().unwrap_or(Value::Null);
    if fd.role == Role::Params {
        let mut m = Map::new();
        if let Some(pm) = v.as_obj() {
            for (k, x) in &pm.items {
                m.insert(&param_name(pr, e, k), x.clone());
            }
        }
        return Value::Obj(m);
    }
    v
}

/// The element as the file keeps it: its fields in its category's order, those given in their
/// file form (left out where the file leaves them out), the others as they were.
fn build(pr: &Project, cat: &str, e: &Value, fields: Option<&'static [Field]>, given: &[(String, Value)]) -> Value {
    let mut out = Map::new();
    if let Some(g) = e.get("guid") {
        out.insert("guid", g.clone());
    }
    out.insert("category", Value::s(cat));
    let get = |k: &str| given.iter().find(|(kk, _)| kk == k).map(|(_, v)| v);
    match fields {
        Some(fs) => {
            for fd in fs {
                match get(fd.name) {
                    Some(v) => {
                        let sv = stored(pr, cat, e, given, fd, v);
                        if !is_skipped(fd.skip, &sv) {
                            out.insert(fd.name, sv);
                        }
                    }
                    None => {
                        if let Some(v) = e.get(fd.name) {
                            out.insert(fd.name, v.clone());
                        }
                    }
                }
            }
            if let Some(m) = e.as_obj() {
                for (k, v) in &m.items {
                    if !out.contains(k) && !fs.iter().any(|f| f.name == k) {
                        out.insert(k, v.clone());
                    }
                }
            }
        }
        None => {
            if let Some(m) = e.as_obj() {
                for (k, v) in &m.items {
                    out.insert(k, v.clone());
                }
            }
            for (k, v) in given {
                out.insert(k, v.clone());
            }
        }
    }
    Value::Obj(out)
}

/// A string naming something of the library: a GUID of the library is that entry's name.
fn lib_name_of(pr: &Project, s: &str) -> String {
    if let Some(g) = strict_guid(s) {
        if let Some(n) = pr.lib_name(&g) {
            return n;
        }
    }
    s.to_string()
}

/// The text a field given names (its library name), where it is text.
fn named(pr: &Project, v: &Value) -> Option<String> {
    v.as_str().map(|s| lib_name_of(pr, s))
}

/// The family an element is of after the change (a component's, a door's or a window's): its name.
fn family_after(pr: &Project, e: &Value, given: &[(String, Value)]) -> Option<String> {
    match given.iter().find(|(k, _)| k == "family") {
        Some((_, v)) => named(pr, v),
        None => e.get("family").and_then(|f| f.as_str()).map(|g| pr.lib_name(g).unwrap_or_else(|| g.to_string())),
    }
}

/// A given value in its file form.
fn stored(pr: &Project, cat: &str, e: &Value, given: &[(String, Value)], fd: &Field, v: &Value) -> Value {
    let lib = |kind: &str, v: &Value| -> Value {
        match named(pr, v) {
            Some(n) => match pr.lib_guid(kind, &n) {
                Some(g) => Value::Str(g),
                None => Value::Str(n),
            },
            None => v.clone(),
        }
    };
    match fd.role {
        Role::Type => {
            let fam = if matches!(cat, "component" | "door" | "window") { family_after(pr, e, given) } else { None };
            match fam {
                Some(f) => match named(pr, v) {
                    Some(n) => match pr.lib_guid("family-type", &format!("{}: {}", f, n)) {
                        Some(g) => Value::Str(g),
                        None => Value::Str(n),
                    },
                    None => v.clone(),
                },
                None => lib(&format!("type:{}", cat), v),
            }
        }
        Role::Family => lib("family", v),
        Role::LineStyle | Role::RegionStyle => lib("line-style", v),
        Role::TextType => lib("text-type", v),
        Role::DimType => lib("dimension-type", v),
        Role::RegionType => lib("filled-region-type", v),
        Role::Group => lib("detail-group", v),
        Role::Cloud => lib("cloud", v),
        Role::Cad => lib("cad", v),
        Role::Params => stored_params(pr, e, given, v),
        Role::Graphics => stored_graphics(pr, v),
        _ => de::store(pr, v, &fd.t),
    }
}

/// A view's graphics as the file keeps them: in their fields' order, what's as a view has it by
/// default left out (fine detail, shaded, nothing overridden), its template, phase and phase
/// filter by GUID.
fn stored_graphics(pr: &Project, v: &Value) -> Value {
    let Some(m) = v.as_obj() else { return v.clone() };
    let mut out = Map::new();
    for f in schema::GRAPHICS.fields {
        let Some(x) = m.get(f.name) else { continue };
        let x = match (f.name, x) {
            (_, Value::Null) => continue,
            ("detail", Value::Str(s)) if s == "fine" => continue,
            ("style", Value::Str(s)) if s == "shaded" => continue,
            (_, Value::Obj(o)) if o.is_empty() => continue,
            (_, Value::Arr(a)) if a.is_empty() => continue,
            ("template", Value::Str(s)) => lib_ref(pr, "view-template", s),
            ("phase", Value::Str(s)) => lib_ref(pr, "phase", s),
            ("phase_filter", Value::Str(s)) => lib_ref(pr, "phase-filter", s),
            ("scale", Value::Num(n)) => Value::f(n.as_f64()),
            ("detail" | "style", _) => de::store(pr, x, &f.t),
            _ => x.clone(),
        };
        out.insert(f.name, x);
    }
    Value::Obj(out)
}

/// A library entry named (or given by GUID): its GUID; the name where there's none.
fn lib_ref(pr: &Project, kind: &str, s: &str) -> Value {
    let n = lib_name_of(pr, s);
    match pr.lib_guid(kind, &n) {
        Some(g) => Value::Str(g),
        None => Value::Str(n),
    }
}

// ---------------------------------------------------------------- params

const CREATED: &str = "Phase Created";
const DEMOLISHED: &str = "Phase Demolished";
const OPTION: &str = "Design Option";

/// The name a key of an element's `params` stands for: a project parameter's or a family
/// parameter's (by its GUID), or the key itself.
fn param_name(pr: &Project, e: &Value, k: &str) -> String {
    if let Some(g) = strict_guid(k) {
        if let Some(le) = pr.library.values().find(|x| x.get("guid").and_then(|y| y.as_str()) == Some(g.as_str())) {
            let name = le.get("name").and_then(|n| n.as_str()).unwrap_or("").to_string();
            return match le.get("kind").and_then(|x| x.as_str()) {
                Some("family-parameter") => match family_of_element(pr, e) {
                    Some(f) => name.strip_prefix(&format!("{}: ", f)).map(|x| x.to_string()).unwrap_or(name),
                    None => name.split_once(": ").map(|(_, b)| b.to_string()).unwrap_or(name),
                },
                _ => name,
            };
        }
    }
    k.to_string()
}

fn family_of_element(pr: &Project, e: &Value) -> Option<String> {
    let f = e.get("family")?.as_str()?;
    Some(pr.lib_name(f).unwrap_or_else(|| f.to_string()))
}

/// A family's parameters: (name, kind, instance).
fn family_params(pr: &Project, fam: &str) -> Vec<(String, String, bool)> {
    pr.section("families")
        .and_then(|m| m.get(fam))
        .and_then(|f| f.get("parameters"))
        .and_then(|a| a.as_arr())
        .map(|a| {
            a.iter()
                .filter_map(|x| {
                    let n = x.get("name")?.as_str()?.to_string();
                    let k = x.get("kind").and_then(|k| k.as_str()).unwrap_or("length").to_string();
                    let i = x.get("instance").and_then(|i| i.as_bool()).unwrap_or(false);
                    Some((n, k, i))
                })
                .collect()
        })
        .unwrap_or_default()
}

/// `params` as the file keeps them: by the parameters' GUIDs (phasing's by name), in key order,
/// a phase or a design option by its GUID.
fn stored_params(pr: &Project, e: &Value, given: &[(String, Value)], v: &Value) -> Value {
    let fam = family_after(pr, e, given);
    let mut out = Map::new();
    let Some(m) = v.as_obj() else { return Value::Obj(out) };
    for (k, x) in &m.items {
        let (key, val) = match k.as_str() {
            CREATED | DEMOLISHED => {
                let val = match x.as_str().and_then(|s| pr.lib_guid("phase", &lib_name_of(pr, s))) {
                    Some(g) => Value::Str(g),
                    None => x.clone(),
                };
                (k.clone(), val)
            }
            OPTION => {
                let val = match x.as_str().and_then(|s| pr.lib_guid("design-option", &lib_name_of(pr, s))) {
                    Some(g) => Value::Str(g),
                    None => x.clone(),
                };
                (k.clone(), val)
            }
            "Paint" => {
                let val = match x {
                    Value::Obj(pm) => {
                        let mut faces = Map::new();
                        for (face, mat) in &pm.items {
                            let mv = match mat.as_str() {
                                Some(s) => lib_ref(pr, "material", s),
                                None => mat.clone(),
                            };
                            faces.insert_sorted(face, mv);
                        }
                        Value::Obj(faces)
                    }
                    _ => x.clone(),
                };
                (k.clone(), val)
            }
            "Mass Floor" => {
                let val = match x {
                    Value::Obj(mm) => {
                        let mut o = Map::new();
                        for (kk, vv) in &mm.items {
                            o.insert_sorted(kk, de::store(pr, vv, &T::Ref));
                        }
                        Value::Obj(o)
                    }
                    _ => x.clone(),
                };
                (k.clone(), val)
            }
            _ => {
                let fam_param = fam.as_ref().and_then(|f| {
                    let g = pr.lib_guid("family-parameter", &format!("{}: {}", f, k))?;
                    let kind = family_params(pr, f).into_iter().find(|(n, _, _)| n == k).map(|(_, kd, _)| kd);
                    Some((g, kind))
                });
                if let Some(g) = crate::styles::parameters::key_of(pr, k) {
                    (g, x.clone())
                } else if let Some((g, kind)) = fam_param {
                    let val = match (kind.as_deref(), x) {
                        (Some("material"), Value::Str(s)) => lib_ref(pr, "material", s),
                        _ => x.clone(),
                    };
                    (g, val)
                } else {
                    (k.clone(), x.clone())
                }
            }
        };
        out.insert_sorted(&key, val);
    }
    Value::Obj(out)
}

/// The phases, in order.
fn phase_names(pr: &Project) -> Vec<String> {
    crate::styles::phasing::phases(pr)
}

fn has_material(pr: &Project, s: &str) -> bool {
    let n = lib_name_of(pr, s);
    pr.section("materials").map(|m| m.contains(&n)).unwrap_or(false)
}

/// A family parameter's value is of its kind.
fn check_family_value(pr: &Project, k: &str, kind: &str, v: &Value) -> R<()> {
    match kind {
        "length" | "number" | "angle" => {
            if !matches!(v, Value::Num(_)) {
                return Err(format!("parameter `{}` holds a number, not {}", k, v.to_compact()));
            }
        }
        "yesno" => {
            if !matches!(v, Value::Bool(_) | Value::Num(_)) {
                return Err(format!("parameter `{}` holds yes or no, not {}", k, v.to_compact()));
            }
        }
        "material" => match v {
            Value::Str(s) => {
                if !has_material(pr, s) {
                    return Err(format!("material `{}` isn't in the library; add it with `material`", lib_name_of(pr, s)));
                }
            }
            _ => return Err(format!("parameter `{}` holds a material's name, not {}", k, v.to_compact())),
        },
        _ => {}
    }
    Ok(())
}

/// `Mass Floor` is {mass, level}, a floor's: the mass it was made from and the level it's on.
fn check_mass_floor(pr: &Project, cat: &str, v: &Value) -> R<()> {
    let not = |shown: &Value| format!("`Mass Floor` is {{mass, level}}, not {}", shown.to_compact());
    let Some(m) = v.as_obj() else { return Err(not(v)) };
    let mut shown = Map::new();
    for (k, x) in &m.items {
        shown.insert_sorted(k, de::store(pr, x, &T::Ref));
    }
    let shown = Value::Obj(shown);
    let target = |k: &str| -> Option<u64> {
        let r = de::de_ref(pr, m.get(k)?).ok()?.id();
        pr.elements.contains_key(&r).then_some(r)
    };
    let (Some(mass), Some(level)) = (target("mass"), target("level")) else { return Err(not(&shown)) };
    if m.len() != 2 {
        return Err(not(&shown));
    }
    if cat != "floor" {
        return Err("only a floor holds `Mass Floor`".into());
    }
    for (t, want) in [(mass, "mass"), (level, "level")] {
        if pr.category(t) != Some(want) {
            return Err(format!("`Mass Floor` names {}, which isn't a {}", pr.guid_of(t).unwrap_or_default(), want));
        }
    }
    Ok(())
}

/// The faces a category's elements can be painted on.
fn paint_faces(cat: &str) -> &'static [&'static str] {
    match cat {
        "wall" => &["exterior", "interior"],
        "floor" | "roof" | "ceiling" => &["top", "bottom"],
        "room" | "mass" => &[],
        _ => &["all"],
    }
}

/// `Paint` is {face: material}, of the element's faces and the library's materials.
fn check_paint(pr: &Project, cat: &str, v: &Value) -> R<()> {
    let Some(m) = v.as_obj() else {
        return Err(format!("`Paint` is {{face: material}}, not {}", v.to_compact()));
    };
    let faces = paint_faces(cat);
    let mut items: Vec<&(String, Value)> = m.items.iter().collect();
    items.sort_by(|a, b| a.0.cmp(&b.0));
    for (face, mat) in items {
        if !faces.contains(&face.as_str()) {
            return Err(format!(
                "a {} has no face `{}` to paint; its faces are {}",
                cat,
                face,
                if faces.is_empty() { "none".to_string() } else { faces.join(", ") }
            ));
        }
        let ok = mat.as_str().map(|s| has_material(pr, s)).unwrap_or(false);
        if !ok {
            return Err(format!(
                "its `{}` is painted a material of the library, not {}; add one with `material`",
                face,
                mat.to_compact()
            ));
        }
    }
    Ok(())
}

/// An element's params after the change are those of its category and kind (in name order).
fn check_params(pr: &Project, c: &Changed, m: &Map, changed: &[Changed]) -> R<()> {
    let mut items: Vec<&(String, Value)> = m.items.iter().collect();
    items.sort_by(|a, b| a.0.cmp(&b.0));
    let fam = family_after(pr, pr.el(c.id).unwrap_or(&Value::Null), &c.given);
    let defs = pr.section("parameters").cloned().unwrap_or_default();
    let ph = phase_names(pr);
    for (k, v) in items {
        match k.as_str() {
            CREATED | DEMOLISHED => {
                let ok = v.as_str().map(|s| ph.contains(&lib_name_of(pr, s))).unwrap_or(false);
                if !ok {
                    return Err(format!(
                        "`{}` is one of the project's phases ({}), not {}",
                        k,
                        ph.join(", "),
                        v.to_compact()
                    ));
                }
            }
            OPTION => {
                let full = v.as_str().map(|s| lib_name_of(pr, s));
                let sets = crate::styles::phasing::option_sets(pr);
                let ok = full
                    .as_deref()
                    .and_then(|f| f.split_once(": "))
                    .map(|(sn, o)| {
                        sets.get(sn)
                            .and_then(|sv| sv.get("options"))
                            .and_then(|a| a.as_arr())
                            .map(|a| a.iter().any(|x| x.as_str() == Some(o)))
                            .unwrap_or(false)
                    })
                    .unwrap_or(false);
                if !ok {
                    return Err(format!("`{}` is `set: option`, one the project has, not {}", OPTION, v.to_compact()));
                }
            }
            "Paint" => check_paint(pr, &c.cat, v)?,
            "Mass Floor" => check_mass_floor(pr, &c.cat, v)?,
            _ => {
                if let Some(def) = defs.get(k) {
                    let cats_ok = def
                        .get("categories")
                        .and_then(|a| a.as_arr())
                        .map(|a| a.iter().any(|x| x.as_str() == Some(c.cat.as_str())))
                        .unwrap_or(false);
                    if cats_ok {
                        let kind = def.get("kind").and_then(|x| x.as_str()).unwrap_or("text");
                        if let Err(holds) = crate::styles::parameters::value_fits(kind, v) {
                            return Err(format!("`{}` holds {}, not {}", k, holds, v.to_compact()));
                        }
                        continue;
                    }
                }
                if let Some(f) = &fam {
                    if let Some((_, kind, inst)) = family_params(pr, f).into_iter().find(|(n, _, _)| n == k) {
                        if !inst {
                            return Err(format!("`{}` is a type parameter of `{}`; change it in its type, with `family`", k, f));
                        }
                        check_family_value(pr, k, &kind, v)?;
                        continue;
                    }
                }
                return Err(format!("`{}` isn't a parameter of {}s; add it with `parameter`", k, c.cat));
            }
        }
    }
    // made before it is taken down (a door or a window with none of its own follows its wall)
    let idx = |v: Option<&Value>| -> Option<usize> {
        let s = v?.as_str()?;
        let n = lib_name_of(pr, s);
        ph.iter().position(|x| *x == n)
    };
    let mut made = idx(m.get(CREATED));
    let mut down = idx(m.get(DEMOLISHED));
    if matches!(c.cat.as_str(), "door" | "window") && (m.get(CREATED).is_none() || m.get(DEMOLISHED).is_none()) {
        let host = c
            .given
            .iter()
            .find(|(k, _)| k == "host")
            .and_then(|(_, v)| de::de_ref(pr, v).ok())
            .map(|r| r.id())
            .or_else(|| pr.el(c.id).and_then(|e| e.get("host")).and_then(|h| h.as_str()).and_then(|g| pr.find_guid(g)));
        if let Some(h) = host {
            let he = changed.iter().find(|x| x.id == h).map(|x| &x.el).or_else(|| pr.el(h));
            if let Some(he) = he {
                let hp = he.get("params");
                if made.is_none() && m.get(CREATED).is_none() {
                    made = idx(hp.and_then(|p| p.get(CREATED)).map(|g| g));
                }
                if down.is_none() && m.get(DEMOLISHED).is_none() {
                    down = idx(hp.and_then(|p| p.get(DEMOLISHED)));
                }
            }
        }
    }
    let made = made.unwrap_or(0);
    if let Some(d) = down {
        if d < made {
            return Err("it can't be demolished in a phase before the one it was made in".into());
        }
    }
    Ok(())
}

// ---------------------------------------------------------------- what the fields name

fn sorted_keys(m: Option<&Map>) -> Vec<String> {
    let mut v: Vec<String> = m.map(|m| m.keys().cloned().collect()).unwrap_or_default();
    v.sort();
    v
}

/// A category's types, by name in name order.
fn type_names(pr: &Project, cat: &str) -> Vec<String> {
    let Some((sec, sub)) = schema::type_section(cat) else { return Vec::new() };
    let t = pr.section("types").and_then(|m| m.get(sec));
    let t = match sub {
        Some(s) => t.and_then(|x| x.get(s)),
        None => t,
    };
    sorted_keys(t.and_then(|x| x.as_obj()))
}

fn family_types(pr: &Project, fam: &str) -> Vec<String> {
    sorted_keys(pr.section("families").and_then(|m| m.get(fam)).and_then(|f| f.get("types")).and_then(|t| t.as_obj()))
}

fn family_category(pr: &Project, fam: &str) -> Option<String> {
    pr.section("families")?.get(fam)?.get("category")?.as_str().map(|s| s.to_string())
}

/// The value a field has after the change (given, else the element's).
fn after<'a>(c: &'a Changed, k: &str) -> Option<&'a Value> {
    c.given.iter().find(|(kk, _)| kk == k).map(|(_, v)| v)
}

fn el_cat(pr: &Project, id: u64) -> Option<String> {
    pr.category(id).map(|c| c.to_string())
}

/// The level of a plan (a level, or a plan view's).
fn plan_level(pr: &Project, id: u64) -> Option<u64> {
    crate::model::level_of_view(pr, id)
}

/// Each field given names what's there: the element's project parameters, its type, its levels,
/// its host… (in the order of its fields, its parameters first).
fn check_names(pr: &Project, c: &Changed, all: &[Changed]) -> R<()> {
    let Some(fields) = schema::fields(&c.cat) else { return Ok(()) };
    if let Some(Value::Obj(m)) = after(c, "params") {
        check_params(pr, c, m, all)?;
    }
    let e = pr.el(c.id).cloned().unwrap_or(Value::Null);
    // a family before the type it's of
    let ordered: Vec<&Field> = fields
        .iter()
        .filter(|f| f.role == Role::Family)
        .chain(fields.iter().filter(|f| f.role != Role::Family))
        .collect();
    for fd in ordered {
        let Some(v) = after(c, fd.name) else { continue };
        match fd.role {
            Role::Type => {
                let Some(n) = named(pr, v) else { continue };
                let fam = if matches!(c.cat.as_str(), "component" | "door" | "window") {
                    family_after(pr, &e, &c.given)
                } else {
                    None
                };
                let names = match &fam {
                    Some(f) => {
                        if pr.section("families").map(|m| m.contains(f)).unwrap_or(false) {
                            family_types(pr, f)
                        } else {
                            continue;
                        }
                    }
                    None => type_names(pr, &c.cat),
                };
                if !names.contains(&n) {
                    return Err(format!("type `{}` doesn't exist (there are: {})", n, names.join(", ")));
                }
            }
            Role::Family => {
                let Some(n) = named(pr, v) else { continue };
                let fams = pr.section("families").cloned().unwrap_or_default();
                let want = match c.cat.as_str() {
                    "door" => Some("door"),
                    "window" => Some("window"),
                    _ => None,
                };
                if !fams.contains(&n) {
                    let mut names: Vec<String> = fams
                        .items
                        .iter()
                        .filter(|(_, f)| want.map(|w| f.get("category").and_then(|x| x.as_str()) == Some(w)).unwrap_or(true))
                        .map(|(k, _)| k.clone())
                        .collect();
                    names.sort();
                    return Err(format!("family `{}` doesn't exist (there are: {})", n, names.join(", ")));
                }
                if let Some(w) = want {
                    if family_category(pr, &n).as_deref() != Some(w) {
                        return Err(format!("family `{}` isn't a {} family", n, w));
                    }
                }
            }
            Role::LineStyle => {
                let Some(n) = named(pr, v) else { continue };
                let names = sorted_keys(pr.section("line_styles"));
                if !names.contains(&n) {
                    return Err(format!("there's no line style `{}` (there are: {})", n, names.join(", ")));
                }
            }
            Role::RegionStyle => {
                let Some(n) = named(pr, v) else { continue };
                if !pr.section("line_styles").map(|m| m.contains(&n)).unwrap_or(false) {
                    return Err(format!("there's no line style `{}`", n));
                }
            }
            Role::TextType => {
                let Some(n) = named(pr, v) else { continue };
                let names = sorted_keys(pr.section("text_types"));
                if !names.contains(&n) {
                    return Err(format!("there's no text type `{}` (there are: {})", n, names.join(", ")));
                }
            }
            Role::DimType => {
                let Some(n) = named(pr, v) else { continue };
                let names = sorted_keys(pr.section("dimension_types"));
                if !names.contains(&n) {
                    return Err(format!("there's no dimension type `{}` (there are: {})", n, names.join(", ")));
                }
            }
            Role::RegionType => {
                let Some(n) = named(pr, v) else { continue };
                let names = sorted_keys(pr.section("region_types"));
                if !names.contains(&n) {
                    return Err(format!("there's no filled region type `{}` (there are: {})", n, names.join(", ")));
                }
            }
            Role::Group => {
                let Some(n) = named(pr, v) else { continue };
                let names = sorted_keys(pr.section("detail_groups"));
                if !names.contains(&n) {
                    return Err(format!("there's no detail group `{}` (there are: {})", n, names.join(", ")));
                }
            }
            Role::Cloud => {
                let Some(n) = named(pr, v) else { continue };
                if !pr.section("clouds").map(|m| m.contains(&n)).unwrap_or(false) {
                    return Err(format!("the project holds no scan named `{}`", n));
                }
            }
            Role::Cad => {
                let Some(n) = named(pr, v) else { continue };
                if !pr.section("cads").map(|m| m.contains(&n)).unwrap_or(false) {
                    return Err(format!("the project holds no CAD drawing named `{}`", n));
                }
            }
            Role::Level | Role::TopLevel => {
                let Ok(r) = de::de_ref(pr, v) else { continue };
                let t = r.id();
                if el_cat(pr, t).as_deref() != Some("level") {
                    return Err(format!("level {} doesn't exist", t));
                }
            }
            Role::Ref(rule) => {
                if v.is_null() {
                    continue;
                }
                let Ok(r) = de::de_ref(pr, v) else { continue };
                check_ref(pr, c, fd.name, rule, r.id())?;
            }
            Role::Params | Role::Plain | Role::Graphics => {}
        }
    }
    Ok(())
}

fn check_ref(pr: &Project, c: &Changed, field: &str, rule: Rule, t: u64) -> R<()> {
    let tc = el_cat(pr, t);
    let tcs = tc.as_deref().unwrap_or("");
    let plan = |id: u64| plan_level(pr, id).is_some();
    match rule {
        Rule::Any => {}
        Rule::Level => {
            if tcs != "level" {
                return Err(format!("level {} doesn't exist", t));
            }
        }
        Rule::HostWall => {
            if tcs != "wall" {
                return Err(format!("host wall {} doesn't exist", t));
            }
        }
        Rule::View => {
            if tc.is_none() {
                return Err(format!("view {} doesn't exist", t));
            }
            if !matches!(tcs, "level" | "planview" | "section" | "elevation" | "sheet") {
                return Err(format!("{} {} isn't a plan, a section, an elevation or a sheet", tcs, t));
            }
        }
        Rule::Attach => {
            if !matches!(tcs, "roof" | "floor") {
                return Err(format!("{} {} isn't a roof or a floor", field, t));
            }
        }
        Rule::TagHost => {
            if tc.is_none() {
                return Err(format!("element {} doesn't exist", t));
            }
            let untaggable = matches!(
                tcs,
                "level"
                    | "grid"
                    | "line"
                    | "text"
                    | "dimension"
                    | "dimension3d"
                    | "tag"
                    | "spot"
                    | "section"
                    | "elevation"
                    | "sheet"
                    | "view3d"
                    | "planview"
                    | "viewport"
                    | "region"
                    | "detailgroup"
                    | "repeatingdetail"
                    | "schedule"
                    | "link"
                    | "roomseparator"
                    | "pointcloud"
                    | "cadimport"
            );
            if untaggable {
                return Err(format!(
                    "tags name what has a place in a plan (doors, windows, walls, columns, floors, rooms and the like), not {} {}",
                    tcs,
                    pr.guid_of(t).unwrap_or_default()
                ));
            }
        }
        Rule::Element => {
            if tc.is_none() {
                return Err(format!("element {} doesn't exist", t));
            }
        }
        Rule::Host => {
            if tc.is_none() {
                return Err(format!("host {} doesn't exist", t));
            }
        }
        Rule::DimView => {
            let lv = after(c, "level")
                .and_then(|v| de::de_ref(pr, v).ok())
                .map(|r| r.id())
                .or_else(|| pr.el(c.id).and_then(|e| e.get("level")).and_then(|g| g.as_str()).and_then(|g| pr.find_guid(g)));
            if plan_level(pr, t).is_none() || plan_level(pr, t) != lv {
                return Err(format!("view {} isn't a plan view of its level", t));
            }
        }
        Rule::TagView => {
            if !plan(t) {
                return Err(format!("view {} isn't a plan view of its host's level", t));
            }
        }
        Rule::Sheet => {
            if tcs != "sheet" {
                return Err(format!("{} {} isn't a sheet", tc.as_deref().unwrap_or("element"), t));
            }
        }
        Rule::ViewportView => {
            if !matches!(tcs, "level" | "planview" | "section" | "elevation" | "schedule" | "view3d") {
                return Err(format!(
                    "{} {} isn't a plan, a section, an elevation, a schedule or a 3D view",
                    tc.as_deref().unwrap_or("element"),
                    t
                ));
            }
        }
        Rule::View3d => {
            if tcs != "view3d" {
                return Err(format!("view {} isn't a 3D view", t));
            }
        }
        Rule::CadView => {
            if !plan(t) {
                return Err(format!("view {} isn't a plan of its level; an import shows in one of its level's plans", t));
            }
        }
        Rule::Parent => {
            if tcs != "level" && tcs != "planview" {
                return Err(format!(
                    "a dependent view hangs from a plan of its own level that is no dependent itself, not {}",
                    t
                ));
            }
        }
        Rule::Join => {
            // the roof it joins joins none itself (as it is after the change)
            let joins = if t == c.id { true } else { pr.el(t).and_then(|e| e.get("join")).map(|j| !j.is_null()).unwrap_or(false) };
            if tcs != "roof" || joins {
                let named = pr.guid_of(t).unwrap_or_else(|| t.to_string());
                return Err(format!("it joins element {}, which isn't a roof that joins none", named));
            }
        }
    }
    Ok(())
}

// ---------------------------------------------------------------- what follows from a change

fn finish(pr: &Project, c: &mut Changed) {
    let old = pr.el(c.id).cloned().unwrap_or(Value::Null);
    match c.cat.as_str() {
        "wall" => {
            if after(c, "location").is_some() && after(c, "start").is_none() && after(c, "end").is_none() {
                keep_wall_in_place(pr, &old, &mut c.el);
            }
        }
        "text" => {
            if after(c, "text").is_some() && after(c, "runs").is_none() {
                remap_runs(&old, &mut c.el);
            }
        }
        "line" => {
            if let Some(m) = c.el.as_obj_mut() {
                de::normalize_curve(m);
            }
        }
        _ => {}
    }
}

/// A room is frozen with the boundary it has now (unless it's given one), and unfrozen it keeps
/// none; one that has none to keep can't be frozen.
fn freeze(pr: &Project, c: &mut Changed) -> R<()> {
    let frozen = c.el.get("frozen").and_then(|f| f.as_bool()).unwrap_or(false);
    if !frozen {
        c.el.remove("kept");
        return Ok(());
    }
    if !c.el.get("kept").map(|k| k.is_null()).unwrap_or(true) {
        return Ok(());
    }
    match super::modify_room::kept(pr, c.id, &c.el) {
        super::modify_room::Kept::Found(kept) => {
            c.el.remove("kept");
            c.el.set("kept", kept);
            Ok(())
        }
        super::modify_room::Kept::Unbounded => Err(format!(
            "room {}: the room is frozen but unbounded (not enclosed, or in a space another room has); a room is frozen with the boundary it has, so give it one first (walls or room separation lines round it, the other room deleted or parted from it), or leave it unfrozen",
            c.id
        )),
        super::modify_room::Kept::Unknown => Ok(()),
    }
}

/// Sketch lines given: each a curve as the file keeps it, with an id and a GUID of its own.
fn number_sketch(pr: &mut Project, el: &mut Value) {
    let Some(Value::Arr(lines)) = el.get_mut("sketch") else { return };
    for l in lines.iter_mut() {
        let Value::Obj(m) = l else { continue };
        de::normalize_curve(m);
        let id = match m.get("id") {
            Some(Value::Num(n)) => Value::Num(*n),
            _ => Value::u(pr.alloc_lib_id()),
        };
        let guid = match m.get("guid") {
            Some(Value::Str(g)) => Value::Str(strict_guid(g).unwrap_or_else(|| g.clone())),
            _ => Value::Str(crate::rand::guid()),
        };
        let mut out = Map::new();
        out.insert("id", id);
        out.insert("guid", guid);
        for (k, v) in &m.items {
            if k != "id" && k != "guid" && !v.is_null() {
                out.insert(k, v.clone());
            }
        }
        *m = out;
    }
}

/// How far a location line is from a wall's centre line, toward its exterior.
pub fn location_offset(loc: &str, thickness: f64, layers: &[(String, f64)]) -> f64 {
    let half = thickness / 2.0;
    let mut a = 0.0;
    let mut b = thickness;
    let first = layers.iter().position(|(f, _)| f == "structure");
    let last = layers.iter().rposition(|(f, _)| f == "structure");
    if let (Some(i), Some(j)) = (first, last) {
        a = layers[..i].iter().map(|(_, t)| *t).sum();
        b = layers[..=j].iter().map(|(_, t)| *t).sum();
    }
    match loc {
        "exterior-finish" => half,
        "interior-finish" => -half,
        "exterior-core" => half - a,
        "interior-core" => half - b,
        "core-centre" | "core-center" => half - (a + b) / 2.0,
        _ => 0.0,
    }
}

/// A wall put on another location line stays where it is: its line moves by the distance between
/// the two lines (its type's, as it is now).
fn keep_wall_in_place(pr: &Project, old: &Value, w: &mut Value) {
    let old_loc = old.get("location").and_then(|l| l.as_str()).unwrap_or("centre").to_string();
    let new_loc = w.get("location").and_then(|l| l.as_str()).unwrap_or("centre").to_string();
    let tname = w.get("type").and_then(|t| t.as_str()).and_then(|g| pr.lib_name(g)).unwrap_or_default();
    let Some(ty) = pr.section("types").and_then(|m| m.get("wall")).and_then(|m| m.get(&tname)) else { return };
    let mut layers: Vec<(String, f64)> = Vec::new();
    if let Some(a) = ty.get("layers").and_then(|l| l.as_arr()) {
        for l in a {
            let f = l.get("function").and_then(|x| x.as_str()).unwrap_or("structure").to_string();
            let t = l.get("thickness").and_then(|x| x.as_f64()).unwrap_or(0.0);
            layers.push((f, t));
        }
    }
    let thickness = ty
        .get("thickness")
        .and_then(|x| x.as_f64())
        .unwrap_or_else(|| layers.iter().map(|(_, t)| *t).sum());
    let delta = location_offset(&new_loc, thickness, &layers) - location_offset(&old_loc, thickness, &layers);
    if delta == 0.0 {
        return;
    }
    let (Some(s), Some(e)) = (pt(w.get("start")), pt(w.get("end"))) else { return };
    let arc = w.get("arc").and_then(|a| a.as_f64()).unwrap_or(0.0);
    let (ns, ne) = offset_line(s, e, arc, delta);
    w.set("start", ptv([r3(ns[0]), r3(ns[1])]));
    w.set("end", ptv([r3(ne[0]), r3(ne[1])]));
}

/// A wall's line (straight, or an arc turning `arc` degrees) moved `d` to its left.
fn offset_line(s: [f64; 2], e: [f64; 2], arc: f64, d: f64) -> ([f64; 2], [f64; 2]) {
    let dx = e[0] - s[0];
    let dy = e[1] - s[1];
    let len = (dx * dx + dy * dy).sqrt();
    if len == 0.0 {
        return (s, e);
    }
    let n = [-dy / len, dx / len];
    if arc == 0.0 {
        return ([s[0] + n[0] * d, s[1] + n[1] * d], [e[0] + n[0] * d, e[1] + n[1] * d]);
    }
    let a = arc.to_radians();
    let m = [(s[0] + e[0]) / 2.0, (s[1] + e[1]) / 2.0];
    let h = len / (2.0 * (a / 2.0).tan());
    let c = [m[0] + n[0] * h, m[1] + n[1] * h];
    let r = ((s[0] - c[0]).powi(2) + (s[1] - c[1]).powi(2)).sqrt();
    if r == 0.0 {
        return (s, e);
    }
    let r2 = if arc > 0.0 { r - d } else { r + d };
    let k = r2 / r;
    (
        [c[0] + (s[0] - c[0]) * k, c[1] + (s[1] - c[1]) * k],
        [c[0] + (e[0] - c[0]) * k, c[1] + (e[1] - c[1]) * k],
    )
}

/// A note's new text keeps its runs on what didn't change: positions before the change stay,
/// those in it go to its end, those after it move with it; a run left empty goes.
fn remap_runs(old: &Value, t: &mut Value) {
    let a: Vec<char> = old.get("text").and_then(|x| x.as_str()).unwrap_or("").chars().collect();
    let b: Vec<char> = t.get("text").and_then(|x| x.as_str()).unwrap_or("").chars().collect();
    if a == b {
        return;
    }
    let Some(runs) = t.get("runs").and_then(|r| r.as_arr()).cloned() else { return };
    let mut pre = 0;
    while pre < a.len() && pre < b.len() && a[pre] == b[pre] {
        pre += 1;
    }
    let mut suf = 0;
    while suf < a.len() - pre && suf < b.len() - pre && a[a.len() - 1 - suf] == b[b.len() - 1 - suf] {
        suf += 1;
    }
    let old_end = a.len() - suf;
    let new_end = b.len() - suf;
    let map = |p: u64| -> u64 {
        let p = p as usize;
        if p < pre {
            p as u64
        } else if p <= old_end {
            new_end as u64
        } else {
            (p as i64 + new_end as i64 - old_end as i64).max(0) as u64
        }
    };
    let mut out = Vec::new();
    for r in runs {
        let (Some(f), Some(to)) = (r.get("from").and_then(|x| x.as_u64()), r.get("to").and_then(|x| x.as_u64())) else {
            out.push(r);
            continue;
        };
        let (nf, nt) = (map(f), map(to));
        if nt <= nf {
            continue;
        }
        let mut r2 = r.clone();
        r2.set("from", Value::u(nf));
        r2.set("to", Value::u(nt));
        out.push(r2);
    }
    if out.is_empty() {
        t.remove("runs");
    } else {
        t.set("runs", Value::Arr(out));
    }
}
