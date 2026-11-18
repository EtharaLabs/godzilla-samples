//! A view's graphics as the file holds them (`graphics` of a level, a plan view, a section, an
//! elevation or a 3D view, and of a view template): its keys in their order, the categories views
//! draw, the background grid, what a template controls, and the graphics in force.

use super::ovr::{self, de_bool, de_pen, de_rgb_array, de_u16, sorted_items};
use crate::json::{Map, Num, Value};
use crate::project::Project;
use crate::styles::common::{color_value, f64_of};

pub type R<T> = Result<T, String>;

// ---------------------------------------------------------------- categories

/// The model categories Visibility/Graphics has, in its order.
pub const MODEL: &[&str] = &[
    "wall",
    "floor",
    "ceiling",
    "shaft",
    "mass",
    "door",
    "window",
    "room",
    "roomseparator",
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
    "rebar",
    "furniture",
    "casework",
    "plumbing",
    "drain",
    "pipefitting",
    "pipeaccessory",
    "equipment",
    "outlet",
    "switch",
    "airterminal",
    "earthing",
    "inspectionbox",
    "lighting",
    "generic",
    "dataoutlet",
    "voiceoutlet",
    "patchpanel",
    "rack",
    "stair",
    "ramp",
    "railing",
    "roof",
];

/// The annotation (and imported) categories, after the model's.
pub const ANNOTATION: &[&str] =
    &["dimension", "tag", "text", "line", "region", "spot", "grid", "level", "section", "elevation", "pointcloud", "cadimport"];

/// Every name `hide`, `show` and `categories` take, as the original lists them.
pub fn drawn_names() -> Vec<&'static str> {
    let mut v: Vec<&'static str> = MODEL.to_vec();
    v.extend_from_slice(ANNOTATION);
    v.push("component");
    v.push("roomreference");
    v.push("roomseparator");
    v
}

/// The categories a view hides unless it shows them (`shown`): rooms in a 3D view, a room's
/// reference cross everywhere.
pub fn shown_kind(c: &str) -> bool {
    matches!(c, "room" | "roomreference")
}

/// The categories of elements views don't draw (so none can be hidden in one).
pub fn undrawn(c: &str) -> bool {
    matches!(c, "sheet" | "schedule" | "viewport" | "view3d" | "dimension3d" | "planview")
}

/// A name as the original keys it: its letters and digits, lowercase.
pub fn squash(s: &str) -> String {
    s.chars().filter(|c| c.is_alphanumeric()).flat_map(|c| c.to_lowercase()).collect()
}

/// A category from a name in any case, singular or plural, among `list`.
pub fn singular_in(s: &str, list: &[&str]) -> Option<String> {
    let k = squash(s);
    if list.contains(&k.as_str()) {
        return Some(k);
    }
    let mut cands: Vec<String> = Vec::new();
    if let Some(x) = k.strip_suffix("ies") {
        cands.push(format!("{}y", x));
    }
    if k.ends_with("sses") || k.ends_with("ches") || k.ends_with("shes") {
        cands.push(k[..k.len() - 2].to_string());
    }
    cands.push(k.trim_end_matches('s').to_string());
    cands.into_iter().find(|c| !c.is_empty() && list.contains(&c.as_str()))
}

/// A category views draw, else the original's message.
pub fn drawn_category(cmd: &str, s: &str) -> R<String> {
    let names = drawn_names();
    singular_in(s, &names)
        .ok_or_else(|| format!("{}: `{}` isn't a category views draw; there are: {}", cmd, s, names.join(", ")))
}

// ---------------------------------------------------------------- the keys

/// A view's graphics' keys, in the order the file holds them.
pub const GKEYS: &[&str] = &[
    "template",
    "categories",
    "filters",
    "elements",
    "phase",
    "phase_filter",
    "options",
    "scale",
    "detail",
    "style",
    "background_grid",
    "linework",
    "layers",
];

fn rank(k: &str) -> usize {
    GKEYS.iter().position(|x| *x == k).unwrap_or(usize::MAX)
}

/// Sets (or, with None, takes away) a key of a graphics map in its place.
pub fn gput(g: &mut Map, k: &str, v: Option<Value>) {
    if let Some(v) = v {
        if let Some(slot) = g.get_mut(k) {
            *slot = v;
            return;
        }
        let r = rank(k);
        let pos = g.items.iter().position(|(kk, _)| rank(kk) > r).unwrap_or(g.items.len());
        g.items.insert(pos, (k.to_string(), v));
    } else {
        g.remove(k);
    }
}

/// A map-valued key of a graphics map (empty where it has none).
pub fn gmap(g: &Map, k: &str) -> Map {
    g.get(k).and_then(|v| v.as_obj()).cloned().unwrap_or_default()
}

/// Puts a map-valued key back, taking it away where it is empty.
pub fn gput_map(g: &mut Map, k: &str, m: Map) {
    if m.is_empty() {
        gput(g, k, None);
    } else {
        gput(g, k, Some(Value::Obj(m)));
    }
}

pub fn gstr(g: &Map, k: &str) -> Option<String> {
    g.get(k).and_then(|v| v.as_str()).map(|s| s.to_string())
}

// ---------------------------------------------------------------- where an element holds them

/// The keys that come before `graphics` in each view's element.
fn before_graphics(category: &str) -> &'static [&'static str] {
    match category {
        "level" => &["guid", "category", "name", "elevation", "extent", "view_range", "crop"],
        "planview" => &["guid", "category", "level", "name", "view_range", "crop"],
        "section" | "elevation" => &["guid", "category", "name", "start", "end", "depth", "crop"],
        "view3d" => &["guid", "category", "name", "azimuth", "elevation"],
        _ => &["guid", "category", "name"],
    }
}

/// A view's own graphics (empty where it has none).
pub fn own(pr: &Project, id: u64) -> Map {
    pr.el(id).and_then(|e| e.get("graphics")).and_then(|g| g.as_obj()).cloned().unwrap_or_default()
}

/// Puts a view's graphics back in its element, in their place (taken away when empty).
pub fn store(e: &mut Value, g: Map) {
    let category = e.get("category").and_then(|c| c.as_str()).unwrap_or("").to_string();
    let Value::Obj(m) = e else { return };
    if g.is_empty() {
        m.remove("graphics");
        return;
    }
    if let Some(slot) = m.get_mut("graphics") {
        *slot = Value::Obj(g);
        return;
    }
    let before = before_graphics(&category);
    let pos = m.items.iter().rposition(|(k, _)| before.contains(&k.as_str())).map(|i| i + 1).unwrap_or(m.items.len());
    m.items.insert(pos, ("graphics".to_string(), Value::Obj(g)));
}

pub fn store_in(pr: &mut Project, id: u64, g: Map) {
    if let Some(e) = pr.el_mut(id) {
        store(e, g);
    }
}

/// What views hold of elements and CAD drawings that are gone (by GUID): their overrides and the
/// layers hidden of them, taken away (`delete` and the CAD drawings' owner call this).
pub fn forget(pr: &mut Project, guids: &[String]) {
    let ids: Vec<u64> = pr.elements.iter().filter(|(_, e)| e.get("graphics").is_some()).map(|(id, _)| *id).collect();
    for id in ids {
        let mut g = own(pr, id);
        let before = g.clone();
        for k in ["elements", "layers"] {
            let mut m = gmap(&g, k);
            for gd in guids {
                m.remove(gd);
            }
            gput_map(&mut g, k, m);
        }
        if g != before {
            store_in(pr, id, g);
        }
    }
}

// ---------------------------------------------------------------- the background grid

#[derive(Clone, PartialEq, Debug)]
pub struct GridStyle {
    pub enabled: bool,
    pub color: [u8; 3],
    pub pen: u64,
}

#[derive(Clone, PartialEq, Debug)]
pub struct Grid {
    pub visible: bool,
    pub main: GridStyle,
    pub sub: GridStyle,
    pub spacing: [f64; 2],
    pub divisions: [u64; 2],
    pub rotation: f64,
}

impl Default for Grid {
    fn default() -> Grid {
        Grid {
            visible: true,
            main: GridStyle { enabled: false, color: [230, 230, 230], pen: 0 },
            sub: GridStyle { enabled: false, color: [245, 245, 245], pen: 0 },
            spacing: [1000.0, 1000.0],
            divisions: [5, 5],
            rotation: 0.0,
        }
    }
}

const GRID_RULE: &str = "spacing X/Y must be finite and between 0.001 and 1000000000 mm; divisions X/Y 1–1000, rotation -360–360 degrees, and pens 0–16";

impl Grid {
    /// The grid a file holds (its defaults where it says nothing).
    pub fn from_value(v: Option<&Value>) -> Grid {
        let mut g = Grid::default();
        let Some(v) = v else { return g };
        if let Some(b) = v.get("visible").and_then(|x| x.as_bool()) {
            g.visible = b;
        }
        for (k, st) in [("main", &mut g.main), ("sub", &mut g.sub)] {
            if let Some(s) = v.get(k) {
                if let Some(b) = s.get("enabled").and_then(|x| x.as_bool()) {
                    st.enabled = b;
                }
                if let Some(c) = s.get("color").and_then(crate::styles::common::color_of) {
                    st.color = c;
                }
                if let Some(p) = s.get("pen").and_then(|x| x.as_f64()) {
                    st.pen = p as u64;
                }
            }
        }
        if let Some(a) = v.get("spacing").and_then(|x| x.as_arr()) {
            for i in 0..2 {
                if let Some(x) = a.get(i).and_then(|x| x.as_f64()) {
                    g.spacing[i] = x;
                }
            }
        }
        if let Some(a) = v.get("divisions").and_then(|x| x.as_arr()) {
            for i in 0..2 {
                if let Some(x) = a.get(i).and_then(|x| x.as_f64()) {
                    g.divisions[i] = x as u64;
                }
            }
        }
        if let Some(r) = v.get("rotation").and_then(|x| x.as_f64()) {
            g.rotation = r;
        }
        g
    }

    pub fn to_value(&self) -> Value {
        let st = |s: &GridStyle| jobj! {"enabled" => s.enabled, "color" => color_value(s.color), "pen" => s.pen};
        jobj! {
            "visible" => self.visible,
            "main" => st(&self.main),
            "sub" => st(&self.sub),
            "spacing" => Value::Arr(vec![Value::f(self.spacing[0]), Value::f(self.spacing[1])]),
            "divisions" => Value::Arr(vec![Value::u(self.divisions[0]), Value::u(self.divisions[1])]),
            "rotation" => Value::f(self.rotation),
        }
    }

    /// Whether its numbers are ones the model takes.
    pub fn ok(&self) -> bool {
        let sp = |x: f64| x.is_finite() && (0.001..=1e9).contains(&x);
        let dv = |x: u64| (1..=1000).contains(&x);
        sp(self.spacing[0])
            && sp(self.spacing[1])
            && dv(self.divisions[0])
            && dv(self.divisions[1])
            && self.rotation.is_finite()
            && (-360.0..=360.0).contains(&self.rotation)
            && self.main.pen <= 16
            && self.sub.pen <= 16
    }

    /// The grid's own error, as the check gives it.
    pub fn rule() -> &'static str {
        GRID_RULE
    }

    /// A patch from a command over this grid (null fields leave theirs as they are).
    pub fn patched(&self, v: &Value) -> R<Grid> {
        let m = match v {
            Value::Obj(m) => m,
            _ => return Err(format!("invalid type: {}, expected struct GridPatch", v.kind_name())),
        };
        let mut g = self.clone();
        for (k, x) in sorted_items(m) {
            if x.is_null() {
                if !["visible", "main", "sub", "spacing", "divisions", "rotation"].contains(&k.as_str()) {
                    return Err(format!(
                        "unknown field `{}`, expected one of `visible`, `main`, `sub`, `spacing`, `divisions`, `rotation`",
                        k
                    ));
                }
                continue;
            }
            match k.as_str() {
                "visible" => g.visible = de_bool(&x)?,
                "main" => g.main = patch_style(&g.main, &x)?,
                "sub" => g.sub = patch_style(&g.sub, &x)?,
                "spacing" => {
                    let a = de_pair(&x, |v| f64_of(v))?;
                    g.spacing = a;
                }
                "divisions" => {
                    let a = de_pair(&x, de_u16)?;
                    g.divisions = a;
                }
                "rotation" => g.rotation = f64_of(&x)?,
                _ => {
                    return Err(format!(
                        "unknown field `{}`, expected one of `visible`, `main`, `sub`, `spacing`, `divisions`, `rotation`",
                        k
                    ))
                }
            }
        }
        Ok(g)
    }
}

fn patch_style(cur: &GridStyle, v: &Value) -> R<GridStyle> {
    let m = match v {
        Value::Obj(m) => m,
        _ => return Err(format!("invalid type: {}, expected struct GridStyle", v.kind_name())),
    };
    let mut s = cur.clone();
    for (k, x) in sorted_items(m) {
        if x.is_null() {
            if !["enabled", "color", "pen"].contains(&k.as_str()) {
                return Err(format!("unknown field `{}`, expected one of `enabled`, `color`, `pen`", k));
            }
            continue;
        }
        match k.as_str() {
            "enabled" => s.enabled = de_bool(&x)?,
            "color" => s.color = de_rgb_array(&x)?,
            "pen" => s.pen = de_pen(&x)?,
            _ => return Err(format!("unknown field `{}`, expected one of `enabled`, `color`, `pen`", k)),
        }
    }
    Ok(s)
}

fn de_pair<T: Copy + Default>(v: &Value, f: impl Fn(&Value) -> R<T>) -> R<[T; 2]> {
    let a = match v {
        Value::Arr(a) => a,
        _ => return Err(format!("invalid type: {}, expected an array of length 2", v.kind_name())),
    };
    let mut out = [T::default(); 2];
    for i in 0..2 {
        match a.get(i) {
            Some(x) => out[i] = f(x)?,
            None => return Err(format!("invalid length {}, expected an array of length 2", i)),
        }
    }
    if a.len() > 2 {
        return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
    }
    Ok(out)
}

/// A command's `background_grid` (an object, or null for the defaults) over the graphics' own:
/// the grid as the file then holds it (None where it is the default).
pub fn grid_param(cmd: &str, g: &Map, v: &Value) -> R<Option<Value>> {
    if v.is_null() {
        return Ok(None);
    }
    if !matches!(v, Value::Obj(_)) {
        return Err(format!("{}: `background_grid` is an object, or null to restore defaults", cmd));
    }
    let cur = Grid::from_value(g.get("background_grid"));
    let new = cur.patched(v).map_err(|e| format!("{}: background grid: {}", cmd, e))?;
    // its numbers are the check's to refuse
    Ok(if new == Grid::default() { None } else { Some(new.to_value()) })
}

// ---------------------------------------------------------------- templates and what they control

/// What a template can control, in its order.
pub const GROUPS: &[&str] = &["categories", "filters", "range", "phase", "options", "scale", "detail", "style", "background_grid"];

/// A group's keys in a graphics map.
pub fn group_keys(group: &str) -> &'static [&'static str] {
    match group {
        "categories" => &["categories"],
        "filters" => &["filters"],
        "phase" => &["phase", "phase_filter"],
        "options" => &["options"],
        "scale" => &["scale"],
        "detail" => &["detail"],
        "style" => &["style"],
        "background_grid" => &["background_grid"],
        _ => &[],
    }
}

/// How a refusal names a group a template controls.
pub fn group_words(group: &str) -> &'static str {
    match group {
        "categories" => "categories",
        "filters" => "filters",
        "range" => "view range",
        "phase" => "phase and phase filter",
        "options" => "design options",
        "scale" => "scale",
        "detail" => "detail level",
        "style" => "visual style",
        "background_grid" => "background grids",
        _ => "settings",
    }
}

/// The refusal of a change a view's template controls.
pub fn followed_error(cmd: &str, group: &str, template: &str) -> String {
    format!(
        "{}: its {} follow view template `{}`; change the template, or `template: null` to stop following it",
        cmd,
        group_words(group),
        template
    )
}

/// The name of a library entry a command names by name or by GUID (any case, braces or not).
pub fn entry_name(pr: &Project, kind: &str, s: &str) -> String {
    if let Some(g) = crate::model::normalize_guid(s) {
        if let Some(n) = crate::styles::common::name_of_guid(pr, kind, &g) {
            return n;
        }
    }
    s.to_string()
}

/// The project's view templates (name: as the file holds it).
pub fn templates(pr: &Project) -> Map {
    pr.section("view_templates").cloned().unwrap_or_default()
}

/// The template a graphics map follows: its name and its object, where the project has it.
pub fn template_of(pr: &Project, g: &Map) -> Option<(String, Value)> {
    let r = gstr(g, "template")?;
    let name = crate::styles::common::name_of_guid(pr, "view-template", &r).unwrap_or(r);
    let t = templates(pr).get(&name).cloned()?;
    Some((name, t))
}

/// What a template controls (as its file says, in their order).
pub fn controls_of(t: &Value) -> Vec<String> {
    let given: Vec<String> = t
        .get("controls")
        .and_then(|c| c.as_arr())
        .map(|a| a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect())
        .unwrap_or_default();
    GROUPS.iter().filter(|g| given.iter().any(|x| x == *g)).map(|g| g.to_string()).collect()
}

/// A template's own graphics.
pub fn template_graphics(t: &Value) -> Map {
    t.get("graphics").and_then(|g| g.as_obj()).cloned().unwrap_or_default()
}

/// The graphics in force of a view whose own are `g`: what its template controls taken from it.
pub fn effective(pr: &Project, g: &Map) -> Map {
    let mut out = g.clone();
    if let Some((_, t)) = template_of(pr, g) {
        let tg = template_graphics(&t);
        for group in controls_of(&t) {
            for k in group_keys(&group) {
                gput(&mut out, k, tg.get(k).cloned());
            }
        }
    }
    out
}

/// The views whose graphics are the source of their own: a dependent plan view's are its
/// parent's.
pub fn source_of(pr: &Project, id: u64) -> u64 {
    if let Some(e) = pr.el(id) {
        if e.get("category").and_then(|c| c.as_str()) == Some("planview") {
            if let Some(p) = e.get("parent").and_then(|p| p.as_str()).and_then(|g| pr.find_guid(g)) {
                if p != id {
                    return p;
                }
            }
        }
    }
    id
}

/// The parent of a dependent plan view.
pub fn parent_of(pr: &Project, id: u64) -> Option<u64> {
    let e = pr.el(id)?;
    if e.get("category").and_then(|c| c.as_str()) != Some("planview") {
        return None;
    }
    e.get("parent").and_then(|p| p.as_str()).and_then(|g| pr.find_guid(g))
}

/// The graphics in force of a view (by id): its source's own, with its template's.
pub fn effective_of(pr: &Project, id: u64) -> Map {
    effective(pr, &own(pr, source_of(pr, id)))
}

// ---------------------------------------------------------------- names for replies

/// The categories of a graphics map with their overrides' patterns named.
pub fn named_categories(pr: &Project, g: &Map) -> Map {
    let mut out = Map::new();
    for (k, v) in &gmap(g, "categories").items {
        out.insert(k, ovr::named_override(pr, v));
    }
    out
}

/// The categories hidden (by name, sorted).
pub fn hidden_categories(g: &Map) -> Vec<String> {
    let mut v: Vec<String> = gmap(g, "categories")
        .items
        .iter()
        .filter(|(_, o)| o.get("hidden").and_then(|h| h.as_bool()).unwrap_or(false))
        .map(|(k, _)| k.clone())
        .collect();
    v.sort();
    v
}

/// The filters applied, each by name, their patterns named.
pub fn named_filters(pr: &Project, g: &Map) -> Value {
    let a = g.get("filters").and_then(|f| f.as_arr()).cloned().unwrap_or_default();
    Value::Arr(
        a.iter()
            .map(|f| {
                let mut f = ovr::named_override(pr, f);
                if let Some(Value::Str(r)) = f.get("filter") {
                    let n = crate::styles::common::name_of_guid(pr, "view-filter", r).unwrap_or_else(|| r.clone());
                    f.set("filter", Value::s(&n));
                }
                f
            })
            .collect(),
    )
}

/// The design options shown, {set: option} by name.
pub fn named_options(pr: &Project, g: &Map) -> Map {
    let mut out = Map::new();
    for (k, v) in &gmap(g, "options").items {
        let set = crate::styles::phasing::set_name_of(pr, k);
        let raw = v.as_str().map(|s| s.to_string()).unwrap_or_else(|| v.to_compact());
        let full = crate::styles::common::name_of_guid(pr, "design-option", &raw).unwrap_or(raw.clone());
        let opt = match full.strip_prefix(&format!("{}: ", set)) {
            Some(o) => o.to_string(),
            None => {
                if full != raw {
                    full.split_once(": ").map(|(_, o)| o.to_string()).unwrap_or(full.clone())
                } else {
                    full.clone()
                }
            }
        };
        out.insert(&set, Value::s(&opt));
    }
    out
}

/// The CAD drawings' layers hidden, {drawing: [layer, …]} by the drawing's name.
pub fn named_layers(pr: &Project, g: &Map) -> Map {
    let mut out = Map::new();
    for (k, v) in &gmap(g, "layers").items {
        let n = crate::styles::common::name_of_guid(pr, "cad", k).unwrap_or_else(|| k.clone());
        out.insert(&n, v.clone());
    }
    out
}

pub fn phase_name(pr: &Project, g: &Map) -> Value {
    match gstr(g, "phase") {
        Some(p) => Value::s(&crate::styles::phasing::phase_name_of(pr, &p)),
        None => Value::Null,
    }
}

pub fn phase_filter_name(pr: &Project, g: &Map) -> Value {
    match gstr(g, "phase_filter") {
        Some(p) => Value::s(&crate::styles::phasing::filter_name_of(pr, &p)),
        None => Value::Null,
    }
}

/// A graphics map with what it names by GUID named (as `elements` and `inspect` show it).
pub fn named(pr: &Project, g: &Map) -> Value {
    let mut out = Map::new();
    for (k, v) in &g.items {
        let nv = match k.as_str() {
            "template" => {
                let r = v.as_str().unwrap_or("").to_string();
                Value::s(&crate::styles::common::name_of_guid(pr, "view-template", &r).unwrap_or(r))
            }
            "categories" => Value::Obj(named_categories(pr, g)),
            "filters" => named_filters(pr, g),
            "elements" => {
                let mut m = Map::new();
                for (ek, ev) in &gmap(g, "elements").items {
                    m.insert(ek, ovr::named_override(pr, ev));
                }
                Value::Obj(m)
            }
            "phase" => phase_name(pr, g),
            "phase_filter" => phase_filter_name(pr, g),
            "options" => Value::Obj(named_options(pr, g)),
            "layers" => Value::Obj(named_layers(pr, g)),
            _ => v.clone(),
        };
        out.insert(k, nv);
    }
    Value::Obj(out)
}

/// The scale of the units' default: 1 : 100, or 1 : 96 in feet and inches.
pub fn default_scale(pr: &Project) -> f64 {
    let units = pr.get("units").and_then(|u| u.as_str()).unwrap_or("mm");
    if matches!(units, "in" | "ft" | "ft-in") {
        96.0
    } else {
        100.0
    }
}

/// What the background grid in force is, as a reply shows it.
pub fn grid_reply(g: &Map) -> Value {
    Grid::from_value(g.get("background_grid")).to_value()
}
