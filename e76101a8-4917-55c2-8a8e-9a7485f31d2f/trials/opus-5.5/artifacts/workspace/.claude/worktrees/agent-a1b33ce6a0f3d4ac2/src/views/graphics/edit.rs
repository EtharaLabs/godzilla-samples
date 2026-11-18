//! What `graphics` and `template` change of a graphics map, parameter by parameter, with the
//! original's messages, and the check of the result.

use super::ovr;
use super::vg::{self, gmap, gput, gput_map};
use crate::commands::params::{get, id_of};
use crate::json::{Map, Value};
use crate::project::Project;

pub type R<T> = Result<T, String>;

/// " (there are: a, b)", or nothing where there are none.
pub fn there_are(names: &[String]) -> String {
    if names.is_empty() {
        String::new()
    } else {
        format!(" (there are: {})", names.join(", "))
    }
}

// ---------------------------------------------------------------- categories

fn cat_list(cmd: &str, p: &Value, key: &str) -> R<Option<Vec<String>>> {
    match get(p, key) {
        None => Ok(None),
        Some(Value::Arr(a)) => {
            let mut out = Vec::new();
            for x in a {
                match x {
                    Value::Str(s) => out.push(vg::drawn_category(cmd, s)?),
                    _ => return Err(format!("{}: `{}`: {} is not a category", cmd, key, x.to_compact())),
                }
            }
            Ok(Some(out))
        }
        Some(v) => Err(format!("{}: `{}` is a list of categories, [\"walls\", \"rooms\"…], not {}", cmd, key, v.to_compact())),
    }
}

/// An override as the file holds it, changed by `f` (None where nothing is left).
fn edit_override(pr: &Project, cur: Option<&Value>, f: impl FnOnce(&mut ovr::Ovr)) -> Option<Value> {
    let mut o = cur.and_then(|v| ovr::de_override(v).ok()).unwrap_or_default();
    f(&mut o);
    let m = ovr::override_map(pr, &o, false);
    if m.is_empty() {
        None
    } else {
        Some(Value::Obj(m))
    }
}

fn put_sorted(m: &mut Map, k: &str, v: Option<Value>) {
    match v {
        Some(v) => m.insert_sorted(k, v),
        None => {
            m.remove(k);
        }
    }
}

/// `hide`: the categories hidden. Whether it was given.
pub fn hide(pr: &Project, cmd: &str, p: &Value, g: &mut Map) -> R<bool> {
    let Some(cats) = cat_list(cmd, p, "hide")? else { return Ok(false) };
    let mut m = gmap(g, "categories");
    for c in cats {
        let v = edit_override(pr, m.get(&c), |o| {
            o.hidden = true;
            o.shown = false;
        });
        put_sorted(&mut m, &c, v);
    }
    gput_map(g, "categories", m);
    Ok(true)
}

/// `show`: the categories shown again (and those hidden unless shown, shown).
pub fn show(pr: &Project, cmd: &str, p: &Value, g: &mut Map) -> R<bool> {
    let Some(cats) = cat_list(cmd, p, "show")? else { return Ok(false) };
    let mut m = gmap(g, "categories");
    for c in cats {
        let shown = vg::shown_kind(&c);
        let v = edit_override(pr, m.get(&c), |o| {
            o.hidden = false;
            if shown {
                o.shown = true;
            }
        });
        put_sorted(&mut m, &c, v);
    }
    gput_map(g, "categories", m);
    Ok(true)
}

/// `categories`: {category: override | null}, each merged into the last.
pub fn categories(pr: &Project, cmd: &str, p: &Value, g: &mut Map) -> R<bool> {
    let m = match get(p, "categories") {
        None => return Ok(false),
        Some(Value::Obj(m)) => m.clone(),
        Some(v) => return Err(format!("{}: `categories` is {{category: override}}, not {}", cmd, v.to_compact())),
    };
    let mut cats = gmap(g, "categories");
    for (k, v) in ovr::sorted_items(&m) {
        let c = vg::drawn_category(cmd, &k)?;
        if v.is_null() {
            cats.remove(&c);
            continue;
        }
        let nv = ovr::merged(pr, cats.get(&c), &v).map_err(|e| format!("{}: category `{}`: {}", cmd, c, e))?;
        put_sorted(&mut cats, &c, nv);
    }
    gput_map(g, "categories", cats);
    Ok(true)
}

// ---------------------------------------------------------------- elements

/// An element a list or a map names (its id, or its GUID).
fn element_ref(pr: &Project, cmd: &str, key: &str, v: &Value) -> R<u64> {
    let bad = || format!("{}: `{}`: {} is not an element id or GUID", cmd, key, v.to_compact());
    let id = match v {
        Value::Num(_) => id_of(v).ok_or_else(bad)?,
        Value::Str(s) => {
            if let Ok(id) = s.trim().parse::<u64>() {
                id
            } else if let Some(gd) = crate::model::normalize_guid(s) {
                match pr.find_guid(&gd) {
                    Some(id) => id,
                    None => return Err(bad()),
                }
            } else {
                return Err(bad());
            }
        }
        _ => return Err(bad()),
    };
    if !pr.elements.contains_key(&id) {
        return Err(format!("{}: no element {}", cmd, id));
    }
    Ok(id)
}

fn drawable(pr: &Project, cmd: &str, id: u64) -> R<()> {
    let c = pr.category(id).unwrap_or("").to_string();
    if vg::undrawn(&c) {
        return Err(format!("{}: element {} is a {}, and views don't draw those", cmd, id, c));
    }
    Ok(())
}

fn id_list(pr: &Project, cmd: &str, p: &Value, key: &str) -> R<Option<Vec<u64>>> {
    match get(p, key) {
        None => Ok(None),
        Some(Value::Arr(a)) => {
            let mut out = Vec::new();
            for x in a {
                let id = element_ref(pr, cmd, key, x)?;
                drawable(pr, cmd, id)?;
                out.push(id);
            }
            Ok(Some(out))
        }
        Some(v) => Err(format!("{}: `{}` is a list of element ids, not {}", cmd, key, v.to_compact())),
    }
}

/// `hide_elements` and `show_elements`.
pub fn hide_show_elements(pr: &Project, cmd: &str, p: &Value, g: &mut Map) -> R<bool> {
    let mut given = false;
    for (key, hidden) in [("hide_elements", true), ("show_elements", false)] {
        let Some(ids) = id_list(pr, cmd, p, key)? else { continue };
        given = true;
        let mut m = gmap(g, "elements");
        for id in ids {
            let gd = pr.guid_of(id).unwrap_or_default();
            let v = edit_override(pr, m.get(&gd), |o| o.hidden = hidden);
            put_sorted(&mut m, &gd, v);
        }
        gput_map(g, "elements", m);
    }
    Ok(given)
}

/// `elements`: {id: override | null}.
pub fn elements(pr: &Project, cmd: &str, p: &Value, g: &mut Map) -> R<bool> {
    let m = match get(p, "elements") {
        None => return Ok(false),
        Some(Value::Obj(m)) => m.clone(),
        Some(v) => return Err(format!("{}: `elements` is {{id: override}}, not {}", cmd, v.to_compact())),
    };
    let mut els = gmap(g, "elements");
    for (k, v) in ovr::sorted_items(&m) {
        let id = match k.trim().parse::<u64>() {
            Ok(id) => {
                if !pr.elements.contains_key(&id) {
                    return Err(format!("{}: no element {}", cmd, id));
                }
                id
            }
            Err(_) => match crate::model::normalize_guid(&k).and_then(|gd| pr.find_guid(&gd)) {
                Some(id) => id,
                None => return Err(format!("{}: `elements`: `{}` is not an element id or GUID", cmd, k)),
            },
        };
        drawable(pr, cmd, id)?;
        let gd = pr.guid_of(id).unwrap_or_default();
        if v.is_null() {
            els.remove(&gd);
            continue;
        }
        let nv = ovr::merged(pr, els.get(&gd), &v).map_err(|e| format!("{}: element {}: {}", cmd, id, e))?;
        put_sorted(&mut els, &gd, nv);
    }
    gput_map(g, "elements", els);
    Ok(true)
}

// ---------------------------------------------------------------- filters

/// The project's view filters (name: as the file holds it).
pub fn view_filters(pr: &Project) -> Map {
    pr.section("view_filters").cloned().unwrap_or_default()
}

/// What a command named that the check looks up after it has read everything: the filters it
/// applies (by name) and a template it names that the project hasn't.
#[derive(Default, Debug)]
pub struct Pending {
    pub filters: Option<Vec<String>>,
    pub template: Option<String>,
    /// Checking what the project holds: the filters applied and the template followed by GUID.
    pub stored: bool,
    /// A design option set or option the command named that isn't one (by its name).
    pub option_error: Option<String>,
}

/// The GUID of the view filter of this name, where the project has it.
pub fn filter_guid(pr: &Project, name: &str) -> Option<String> {
    if view_filters(pr).contains(name) {
        pr.lib_guid("view-filter", name)
    } else {
        None
    }
}

/// `filters`: the list applied, replaced (each by its GUID, or its name where the project has
/// no such filter, which the check refuses).
pub fn filters(pr: &Project, cmd: &str, p: &Value, g: &mut Map, pend: &mut Pending) -> R<bool> {
    let a = match get(p, "filters") {
        None => return Ok(false),
        Some(Value::Arr(a)) if a.len() <= 32 => a.clone(),
        Some(v) => {
            return Err(format!(
                "{}: `filters` is [{{filter, hidden?, projection?, cut?, …}}, …] (up to 32), not {}",
                cmd,
                v.to_compact()
            ))
        }
    };
    let mut out: Vec<Value> = Vec::new();
    let mut names: Vec<String> = Vec::new();
    for x in &a {
        let (name, o) =
            ovr::de_applied(x).map_err(|e| format!("{}: filter {}: {}", cmd, x.clone().sorted().to_compact(), e))?;
        let name = vg::entry_name(pr, "view-filter", &name);
        let r = filter_guid(pr, &name).unwrap_or_else(|| name.clone());
        let mut m = Map::new();
        m.insert("filter", Value::s(&r));
        for (k, v) in ovr::override_map(pr, &o, false).items {
            m.insert(&k, v);
        }
        out.push(Value::Obj(m));
        names.push(name);
    }
    gput(g, "filters", if out.is_empty() { None } else { Some(Value::Arr(out)) });
    pend.filters = Some(names);
    Ok(true)
}

// ---------------------------------------------------------------- phase and design options

fn name_or_null(cmd: &str, key: &str, v: &Value) -> R<Option<String>> {
    match v {
        Value::Null => Ok(None),
        Value::Str(s) => Ok(Some(s.clone())),
        _ => Err(format!("{}: `{}` is a name, or null, not {}", cmd, key, v.to_compact())),
    }
}

/// `phase` and `phase_filter` (by name; null takes them away). Whether either was given.
pub fn phase(pr: &Project, cmd: &str, p: &Value, g: &mut Map) -> R<bool> {
    let mut given = false;
    for (key, kind) in [("phase", "phase"), ("phase_filter", "phase-filter")] {
        let Some(v) = p.get(key) else { continue };
        given = true;
        let n = name_or_null(cmd, key, v)?;
        let r = n.map(|n| pr.lib_guid(kind, &n).unwrap_or(n));
        gput(g, key, r.map(|s| Value::s(&s)));
    }
    Ok(given)
}

/// `options`: {set: option | null}.
pub fn options(pr: &Project, cmd: &str, p: &Value, g: &mut Map, pend: &mut Pending) -> R<bool> {
    let m = match p.get("options") {
        None | Some(Value::Null) => return Ok(false),
        Some(Value::Obj(m)) => m.clone(),
        Some(v) => return Err(format!("{}: `options` is {{set: option}}, not {}", cmd, v.to_compact())),
    };
    let sets = crate::styles::phasing::option_sets(pr);
    let mut set_names: Vec<String> = sets.keys().cloned().collect();
    set_names.sort();
    let mut opts = gmap(g, "options");
    for (k, v) in ovr::sorted_items(&m) {
        let set = pr.lib_guid("option-set", &k).unwrap_or_else(|| k.clone());
        // sets and options go by name: a GUID isn't taken for one
        if !sets.contains(&k) && !v.is_null() && pend.option_error.is_none() {
            pend.option_error = Some(format!("there's no design option set `{}`{}", k, there_are(&set_names)));
        }
        match &v {
            Value::Null => {
                opts.remove(&set);
            }
            Value::Str(o) => {
                let full = format!("{}: {}", k, o);
                let r = pr.lib_guid("design-option", &full).unwrap_or_else(|| o.clone());
                if sets.contains(&k) && pr.lib_guid("design-option", &full).is_none() && pend.option_error.is_none() {
                    let shown = vg::entry_name(pr, "design-option", o);
                    let have: Vec<String> = sets
                        .get(&k)
                        .and_then(|s| s.get("options"))
                        .and_then(|a| a.as_arr())
                        .map(|a| a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect())
                        .unwrap_or_default();
                    pend.option_error =
                        Some(format!("design option set `{}` has no option `{}` (there are: {})", k, shown, have.join(", ")));
                }
                opts.insert_sorted(&set, Value::s(&r));
            }
            _ => {
                return Err(format!(
                    "{}: `options`: set `{}`'s option is a name, or null, not {}",
                    cmd,
                    k,
                    v.to_compact()
                ))
            }
        }
    }
    gput_map(g, "options", opts);
    Ok(true)
}

// ---------------------------------------------------------------- CAD drawings' layers

/// The layers a CAD drawing the project holds has (its table's and its entities').
pub fn cad_layers(pr: &Project, name: &str) -> Vec<String> {
    let Some(c) = pr.section("cads").and_then(|m| m.get(name).cloned()) else { return Vec::new() };
    let Some(b64) = c.get("dxf").and_then(|d| d.as_str()) else { return Vec::new() };
    let Some(z) = crate::util::base64_decode(b64) else { return Vec::new() };
    let Ok(raw) = crate::inflate::zlib_decode(&z, 1 << 30) else { return Vec::new() };
    let text = String::from_utf8_lossy(&raw).to_string();
    let lines: Vec<&str> = text.lines().map(|l| l.trim()).collect();
    let mut out: Vec<String> = Vec::new();
    let mut in_layer_table = false;
    let mut i = 0;
    let mut current = String::new();
    while i + 1 < lines.len() {
        let code = lines[i];
        let val = lines[i + 1];
        if code == "0" {
            current = val.to_string();
            if val == "TABLE" {
                in_layer_table = false;
            }
            if val == "ENDTAB" {
                in_layer_table = false;
            }
        }
        if code == "2" && current == "TABLE" && val == "LAYER" {
            in_layer_table = true;
        } else if code == "2" && current == "LAYER" && in_layer_table {
            if !out.iter().any(|x| x == val) {
                out.push(val.to_string());
            }
        } else if code == "8" && current != "LAYER" {
            if !out.iter().any(|x| x == val) {
                out.push(val.to_string());
            }
        }
        i += 2;
    }
    out
}

/// `layers`: {drawing: [layer, …] | null}, the layers of each CAD drawing hidden.
pub fn layers(pr: &Project, cmd: &str, p: &Value, g: &mut Map) -> R<bool> {
    let m = match get(p, "layers") {
        None => return Ok(false),
        Some(Value::Obj(m)) => m.clone(),
        Some(v) => return Err(format!("{}: `layers` is {{drawing: [layer, …] | null}}, not {}", cmd, v.to_compact())),
    };
    let mut ls = gmap(g, "layers");
    for (k, v) in ovr::sorted_items(&m) {
        let known = pr.section("cads").map(|c| c.contains(&k)).unwrap_or(false);
        let gd = match pr.lib_guid("cad", &k) {
            Some(gd) if known => gd,
            _ => {
                return Err(format!(
                    "{}: `layers`: the project has no CAD drawing `{}` (see `elements` of category cadimport)",
                    cmd, k
                ))
            }
        };
        match &v {
            Value::Null => {
                ls.remove(&gd);
            }
            Value::Arr(a) => {
                let have = cad_layers(pr, &k);
                let mut names: Vec<String> = Vec::new();
                for x in a {
                    let Value::Str(n) = x else {
                        return Err(format!("{}: `layers`: `{}` lists layers by name, not {}", cmd, k, x.to_compact()));
                    };
                    if !have.iter().any(|h| h == n) {
                        return Err(format!("{}: `layers`: `{}` has no layer `{}` (see `cad_layers`)", cmd, k, n));
                    }
                    if !names.contains(n) {
                        names.push(n.clone());
                    }
                }
                names.sort();
                if names.is_empty() {
                    ls.remove(&gd);
                } else {
                    ls.insert_sorted(&gd, Value::from(names));
                }
            }
            _ => {
                return Err(format!(
                    "{}: `layers`: `{}` is a list of the layers to hide, or null, not {}",
                    cmd,
                    k,
                    v.to_compact()
                ))
            }
        }
    }
    gput_map(g, "layers", ls);
    Ok(true)
}

// ---------------------------------------------------------------- the background grid

/// `background_grid`: a patch over the grid, or null for the defaults.
pub fn grid(cmd: &str, p: &Value, g: &mut Map) -> R<bool> {
    let Some(v) = p.get("background_grid") else { return Ok(false) };
    let new = vg::grid_param(cmd, g, v)?;
    gput(g, "background_grid", new);
    Ok(true)
}

// ---------------------------------------------------------------- the check

fn transparency(v: &Value) -> u64 {
    v.get("transparency").and_then(|t| t.as_u64()).unwrap_or(0)
}

fn patterns_known(pr: &Project, v: &Value) -> R<()> {
    let known = pr.section("fill_patterns").cloned().unwrap_or_default();
    for pat in ovr::patterns_in(v) {
        let n = ovr::pattern_name(pr, &pat);
        if !known.contains(&n) {
            return Err(format!("there's no fill pattern `{}`", n));
        }
    }
    Ok(())
}

/// What the graphics map holds is the model's: transparency a percent, fill patterns the
/// project's, the filters it applies (once each) and the template it follows the project's, its
/// phase, phase filter and design options; else the message (after the command's or the view's
/// name). `pend` says what a command named by name and is looked up here.
pub fn check_with(pr: &Project, g: &Map, pend: &Pending) -> R<()> {
    if let Some(bg) = g.get("background_grid") {
        if !vg::Grid::from_value(Some(bg)).ok() {
            return Err(format!("background grid: {}", vg::Grid::rule()));
        }
    }
    let cats = gmap(g, "categories");
    let els = gmap(g, "elements");
    for (k, v) in &cats.items {
        let t = transparency(v);
        if t > 100 {
            return Err(format!("category `{}`: transparency is a percent, 0 to 100, not {}", k, t));
        }
    }
    for (k, v) in &els.items {
        let t = transparency(v);
        if t > 100 {
            return Err(format!("element {}: transparency is a percent, 0 to 100, not {}", k, t));
        }
    }
    for (_, v) in cats.items.iter().chain(els.items.iter()) {
        patterns_known(pr, v)?;
    }
    let fl = g.get("filters").and_then(|f| f.as_arr()).cloned().unwrap_or_default();
    let mut seen: Vec<String> = Vec::new();
    for (i, f) in fl.iter().enumerate() {
        let r = f.get("filter").and_then(|x| x.as_str()).unwrap_or("").to_string();
        let name = match &pend.filters {
            Some(names) => names.get(i).cloned().unwrap_or(r.clone()),
            None => crate::styles::common::name_of_guid(pr, "view-filter", &r).unwrap_or(r.clone()),
        };
        if (pend.filters.is_some() || pend.stored) && filter_guid(pr, &name).is_none() {
            let mut names: Vec<String> = view_filters(pr).keys().cloned().collect();
            names.sort();
            return Err(format!("there's no view filter `{}`{}", name, there_are(&names)));
        }
        if seen.contains(&name) {
            return Err(format!("filter `{}` is applied twice", name));
        }
        seen.push(name.clone());
        let t = transparency(f);
        if t > 100 {
            return Err(format!("filter `{}`: transparency is a percent, 0 to 100, not {}", name, t));
        }
        patterns_known(pr, f)?;
    }
    let missing_template = match &pend.template {
        Some(n) => Some(n.clone()),
        None if pend.stored => match vg::gstr(g, "template") {
            Some(r) if vg::template_of(pr, g).is_none() => Some(r),
            _ => None,
        },
        None => None,
    };
    if let Some(n) = missing_template {
        let mut names: Vec<String> = vg::templates(pr).keys().cloned().collect();
        names.sort();
        return Err(format!("there's no view template `{}`{}", n, there_are(&names)));
    }
    if let Some(e) = &pend.option_error {
        // the phase and its filter are looked at before the design options
        let mut np = g.clone();
        np.remove("options");
        crate::styles::phasing::check_view_graphics(pr, &Value::Obj(np))?;
        return Err(e.clone());
    }
    crate::styles::phasing::check_view_graphics(pr, &Value::Obj(g.clone()))
}

/// The check of graphics as the project holds them (a view's or a template's), in the order
/// the model's check goes: the background grid, the categories' names, then what the command's
/// check sees, then the scale.
pub fn check(pr: &Project, g: &Map) -> R<()> {
    if let Some(bg) = g.get("background_grid") {
        if !vg::Grid::from_value(Some(bg)).ok() {
            return Err(format!("background grid: {}", vg::Grid::rule()));
        }
    }
    let names = vg::drawn_names();
    for (k, _) in &gmap(g, "categories").items {
        if !names.contains(&k.as_str()) {
            // the model's list leaves the subcategories out
            let listed: Vec<&str> = names[..names.len() - 2].to_vec();
            return Err(format!("`{}` isn't a category views draw; there are: {}", k, listed.join(", ")));
        }
    }
    check_with(pr, g, &Pending { stored: true, ..Pending::default() })?;
    if let Some(sc) = g.get("scale").and_then(|x| x.as_f64()) {
        if !(sc.is_finite() && (1.0..=100000.0).contains(&sc)) {
            return Err(format!("its scale 1 : {} isn't between 1 : 1 and 1 : 100000", sc));
        }
    }
    Ok(())
}
