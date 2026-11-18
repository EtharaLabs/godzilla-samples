//! The model's rules as the original checks them when a project opens (and after every command),
//! where this checks them: the sections this reader knows (the drafting styles, the materials,
//! the detail groups, the view templates, the run types), then each element in turn, in id order,
//! by its category's rules in the order the original takes them (what it names of the library —
//! its type, its family, its styles —, what it points at among the elements — its level, its host,
//! its view —, its numbers, the ranges they keep to, its graphics), then the library's ids, and
//! last what the elements point at by their ids instead of their GUIDs, or that isn't there.

use crate::json::{Num, Value};
use crate::project::Project;
use std::collections::HashMap;

type R<T> = Result<T, String>;

/// The elements by GUID, for what points at them.
pub struct Index<'a> {
    pr: &'a Project,
    by_guid: HashMap<String, u64>,
}

impl<'a> Index<'a> {
    pub fn new(pr: &'a Project) -> Index<'a> {
        let mut by_guid = HashMap::new();
        for (id, e) in &pr.elements {
            if let Some(g) = e.get("guid").and_then(|x| x.as_str()) {
                by_guid.entry(g.to_string()).or_insert(*id);
            }
        }
        Index { pr, by_guid }
    }
    fn cat(&self, id: u64) -> &str {
        self.pr.elements.get(&id).and_then(|e| e.get("category")).and_then(|c| c.as_str()).unwrap_or("")
    }
}

/// What a reference names: the element (by GUID, or by its id), how it reads in a message, and
/// whether it names it by its id.
struct Target {
    id: Option<u64>,
    shown: String,
    by_id: bool,
}

fn target(ix: &Index, v: &Value) -> Option<Target> {
    match v {
        Value::Str(s) => match ix.by_guid.get(s) {
            Some(id) => Some(Target { id: Some(*id), shown: id.to_string(), by_id: false }),
            None => Some(Target { id: None, shown: s.clone(), by_id: false }),
        },
        Value::Num(Num::U(n)) => {
            let found = ix.pr.elements.contains_key(n);
            Some(Target { id: if found { Some(*n) } else { None }, shown: n.to_string(), by_id: found })
        }
        Value::Null => None,
        other => Some(Target { id: None, shown: other.to_compact(), by_id: false }),
    }
}

/// The names of a section's entries, as the original lists them.
fn names(pr: &Project, path: &[&str]) -> Vec<String> {
    let mut v = pr.get(path[0]);
    for p in &path[1..] {
        v = v.and_then(|x| x.get(p));
    }
    v.and_then(|x| x.as_obj()).map(|m| m.keys().cloned().collect()).unwrap_or_default()
}

/// The name a library reference holds: its library entry's (by GUID, of that kind), else as it is.
fn lib_name(pr: &Project, kind: &str, v: &Value) -> Option<String> {
    let s = v.as_str()?;
    for (_, e) in &pr.library {
        if e.get("kind").and_then(|k| k.as_str()) == Some(kind) && e.get("guid").and_then(|g| g.as_str()) == Some(s) {
            return e.get("name").and_then(|n| n.as_str()).map(|n| n.to_string());
        }
    }
    None
}

fn type_section(cat: &str) -> Option<Vec<&'static str>> {
    Some(match cat {
        "wall" => vec!["types", "wall"],
        "floor" => vec!["types", "floor"],
        "ceiling" => vec!["types", "ceiling"],
        "roof" => vec!["types", "roof"],
        "column" => vec!["types", "column"],
        "structuralcolumn" => vec!["types", "structural_column"],
        "footing" => vec!["types", "footing"],
        "railing" => vec!["types", "railing"],
        "door" => vec!["types", "door"],
        "window" => vec!["types", "window"],
        _ => return None,
    })
}

/// The categories a view's graphics may hide or override, in the order the original lists them.
const VIEW_CATEGORIES: &[&str] = &[
    "wall", "floor", "ceiling", "shaft", "mass", "door", "window", "room", "roomseparator", "column", "structuralcolumn",
    "footing", "beam", "stripfooting", "pipe", "duct", "conduit", "cabletray", "wire", "downconductor", "groundconductor",
    "cable", "rebar", "furniture", "casework", "plumbing", "drain", "pipefitting", "pipeaccessory", "equipment", "outlet",
    "switch", "airterminal", "earthing", "inspectionbox", "lighting", "generic", "dataoutlet", "voiceoutlet", "patchpanel",
    "rack", "stair", "ramp", "railing", "roof", "dimension", "tag", "text", "line", "region", "spot", "grid", "level",
    "section", "elevation", "pointcloud", "cadimport", "component",
];

/// What a tag may name.
const TAGGED: &[&str] = &[
    "wall", "floor", "ceiling", "door", "window", "room", "column", "structuralcolumn", "footing", "beam", "stripfooting",
    "pipe", "duct", "conduit", "cabletray", "wire", "downconductor", "groundconductor", "cable", "component", "stair",
    "ramp", "roof",
];

const RUNS: &[&str] = &[
    "beam", "stripfooting", "pipe", "duct", "conduit", "cabletray", "wire", "downconductor", "groundconductor", "cable",
];

fn there_are(list: &[String]) -> String {
    list.join(", ")
}

/// ` (there are: a, b)`, or nothing when there are none (as a view's graphics say it).
fn tail(list: &[String]) -> String {
    if list.is_empty() {
        String::new()
    } else {
        format!(" (there are: {})", list.join(", "))
    }
}

fn shown(v: &Value) -> String {
    match v {
        Value::Str(s) => s.clone(),
        other => other.to_compact(),
    }
}

fn is_view(cat: &str, with_sheet: bool) -> bool {
    matches!(cat, "level" | "planview" | "section" | "elevation") || (with_sheet && cat == "sheet")
}

/// The phases, in their order (an English project's where the file says none).
fn phases(pr: &Project) -> Vec<String> {
    crate::styles::phasing::phases(pr)
}

/// What a view's (or a template's) graphics hold, checked in the original's order: its background
/// grid; its categories' names and its overrides' transparency; its linework; the fill patterns its
/// overrides draw with; the filters it applies; its template, phase and phase filter; its scale;
/// its design options; and last, the elements it overrides.
fn graphics(ix: &Index, who: &str, g: &Value, template: bool) -> R<()> {
    let pr = ix.pr;
    let lib_missing = |kind: &str, v: &Value| lib_name(pr, kind, v).is_none();
    let set = |k: &str| g.get(k).filter(|v| !v.is_null());
    if template {
        let overrides = g.get("elements").and_then(|v| v.as_obj()).map(|m| !m.is_empty()).unwrap_or(false);
        if set("template").is_some() || overrides {
            return Err(format!(
                "{}: a template holds categories and filters; the elements and the template a view follows are its own",
                who
            ));
        }
    }
    if let Some(bg) = set("background_grid") {
        if !grid_ok(bg) {
            return Err(format!(
                "{}: background grid: spacing X/Y must be finite and between 0.001 and 1000000000 mm; divisions X/Y 1–1000, rotation -360–360 degrees, and pens 0–16",
                who
            ));
        }
    }
    let transparency = |o: &Value, what: &str| -> R<()> {
        match o.get("transparency").and_then(|t| t.as_u64()) {
            Some(t) if t > 100 => Err(format!("{}: {}: transparency is a percent, 0 to 100, not {}", who, what, t)),
            _ => Ok(()),
        }
    };
    if let Some(Value::Obj(cats)) = g.get("categories") {
        for (k, o) in cats.iter() {
            if !VIEW_CATEGORIES.contains(&k.as_str()) {
                return Err(format!("{}: `{}` isn't a category views draw; there are: {}", who, k, VIEW_CATEGORIES.join(", ")));
            }
            transparency(o, &format!("category `{}`", k))?;
        }
    }
    if let Some(Value::Obj(els)) = g.get("elements") {
        for (k, o) in els.iter() {
            transparency(o, &format!("element {}", k))?;
        }
    }
    if let Some(Value::Arr(ls)) = g.get("linework") {
        for (i, l) in ls.iter().enumerate() {
            let within = ["from", "to"].iter().all(|k| {
                l.get(k).and_then(|p| p.as_arr()).map(|a| a.iter().all(|x| x.as_f64().map(|f| f.abs() <= 1e9).unwrap_or(false))).unwrap_or(true)
            });
            if !within {
                return Err(format!("{}: Linework edge {}: its ends are numbers within 1000000000 mm", who, i));
            }
            if let Some(v) = l.get("style").filter(|v| !v.is_null()) {
                if lib_missing("line-style", v) {
                    return Err(format!(
                        "{}: Linework edge {}: there's no line style `{}`{}",
                        who,
                        i,
                        shown(v),
                        tail(&names(pr, &["line_styles"]))
                    ));
                }
            }
        }
    }
    let patterns = |o: &Value| -> R<()> {
        for side in ["projection", "cut"] {
            for layer in ["foreground", "background"] {
                if let Some(p) = o.get(side).and_then(|s| s.get(layer)).and_then(|l| l.get("pattern")).filter(|v| !v.is_null()) {
                    if lib_missing("fill-pattern", p) {
                        return Err(format!("{}: there's no fill pattern `{}`", who, shown(p)));
                    }
                }
            }
        }
        Ok(())
    };
    for key in ["categories", "elements"] {
        if let Some(Value::Obj(m)) = g.get(key) {
            for (_, o) in m.iter() {
                patterns(o)?;
            }
        }
    }
    let filters: &[Value] = match g.get("filters") {
        Some(Value::Arr(fs)) => fs,
        _ => &[],
    };
    for f in filters {
        patterns(f)?;
    }
    let mut applied: Vec<String> = Vec::new();
    for f in filters {
        let v = f.get("filter").cloned().unwrap_or(Value::Null);
        let name = match lib_name(pr, "view-filter", &v) {
            Some(n) => n,
            None => {
                return Err(format!("{}: there's no view filter `{}`{}", who, shown(&v), tail(&names(pr, &["view_filters"]))))
            }
        };
        if applied.contains(&name) {
            return Err(format!("{}: filter `{}` is applied twice", who, name));
        }
        transparency(f, &format!("filter `{}`", name))?;
        applied.push(name);
    }
    if let Some(t) = set("template") {
        if lib_missing("view-template", t) {
            return Err(format!("{}: there's no view template `{}` (there are: {})", who, shown(t), there_are(&names(pr, &["view_templates"]))));
        }
    }
    if let Some(p) = set("phase") {
        if lib_missing("phase", p) {
            return Err(format!("{}: there's no phase `{}` (there are: {})", who, shown(p), there_are(&phases(pr))));
        }
    }
    if let Some(f) = set("phase_filter") {
        if lib_missing("phase-filter", f) {
            let filters: Vec<String> = crate::styles::phasing::filters(pr).keys().cloned().collect();
            return Err(format!("{}: there's no phase filter `{}`{}", who, shown(f), tail(&filters)));
        }
    }
    if let Some(s) = set("scale").and_then(|s| s.as_f64()) {
        if !(1.0..=100_000.0).contains(&s) {
            return Err(format!("{}: its scale 1 : {} isn't between 1 : 1 and 1 : 100000", who, s));
        }
    }
    if let Some(Value::Obj(opts)) = g.get("options") {
        // by the names of their sets, as the original keeps them
        let mut by_name: Vec<(Option<String>, &String, &Value)> =
            opts.iter().map(|(set, opt)| (lib_name(pr, "option-set", &Value::s(set)), set, opt)).collect();
        by_name.sort_by(|a, b| a.0.as_ref().unwrap_or(a.1).cmp(b.0.as_ref().unwrap_or(b.1)));
        for (set_name, set, opt) in by_name {
            let set_name = match set_name {
                Some(n) => n,
                None => {
                    return Err(format!(
                        "{}: there's no design option set `{}`{}",
                        who,
                        set,
                        tail(&names(pr, &["option_sets"]))
                    ))
                }
            };
            if !opt.is_null() && lib_missing("design-option", opt) {
                let options: Vec<String> = pr
                    .section("option_sets")
                    .and_then(|m| m.get(&set_name))
                    .and_then(|s| s.get("options"))
                    .and_then(|o| o.as_arr())
                    .map(|a| a.iter().map(shown).collect())
                    .unwrap_or_default();
                return Err(format!(
                    "{}: design option set `{}` has no option `{}` (there are: {})",
                    who,
                    set_name,
                    shown(opt),
                    there_are(&options)
                ));
            }
        }
    }
    Ok(())
}

/// The elements a view's graphics override: each one of the project's, named by its GUID (checked,
/// as the original checks it, once every element's other rules are).
fn graphics_keys(ix: &Index, who: &str, g: &Value) -> R<()> {
    if let Some(Value::Obj(els)) = g.get("elements") {
        for (k, _) in els.iter() {
            if !ix.by_guid.contains_key(k) {
                if let Ok(n) = k.parse::<u64>() {
                    if ix.pr.elements.contains_key(&n) {
                        return Err(format!("{} points at element {} by its id, not its GUID", who, n));
                    }
                }
                return Err(format!("{} points at {}, which no element of the project is", who, k));
            }
        }
    }
    Ok(())
}

/// A background grid the original draws: spacings of 0.001 mm to 1000000000 mm, 1 to 1000
/// divisions, a rotation within a turn either way, pens 0 to 16.
fn grid_ok(bg: &Value) -> bool {
    let nums = |k: &str| -> Vec<f64> {
        bg.get(k).and_then(|v| v.as_arr()).map(|a| a.iter().filter_map(|x| x.as_f64()).collect()).unwrap_or_default()
    };
    let spacing_ok = nums("spacing").iter().all(|s| s.is_finite() && (0.001..=1e9).contains(s));
    let divisions_ok = nums("divisions").iter().all(|d| (1.0..=1000.0).contains(d));
    let rotation_ok = bg.get("rotation").and_then(|r| r.as_f64()).map(|r| (-360.0..=360.0).contains(&r)).unwrap_or(true);
    let pens_ok = ["main", "sub"].iter().all(|k| bg.get(k).and_then(|s| s.get("pen")).and_then(|p| p.as_f64()).map(|p| (0.0..=16.0).contains(&p)).unwrap_or(true));
    spacing_ok && divisions_ok && rotation_ok && pens_ok
}

/// The view templates' graphics, checked (as the original checks them) after the materials.
pub fn templates(pr: &Project) -> R<()> {
    let ix = Index::new(pr);
    if let Some(ts) = pr.section("view_templates") {
        for (name, t) in ts.iter() {
            if let Some(g) = t.get("graphics") {
                graphics(&ix, &format!("view template `{}`", name), g, true)?;
            }
        }
    }
    Ok(())
}

/// The faces an element has painted, and with what.
fn paint(pr: &Project, id: u64, cat: &str, e: &Value) -> R<()> {
    let p = match e.get("params").and_then(|p| p.get("Paint")) {
        Some(p) => p,
        None => return Ok(()),
    };
    let m = match p {
        Value::Obj(m) => m,
        other => return Err(format!("{} {}: `Paint` is {{face: material}}, not {}", cat, id, other.to_compact())),
    };
    for (face, mat) in m.iter() {
        if let Some(fs) = crate::media::paint::faces(cat) {
            if !fs.contains(&face.as_str()) {
                return Err(format!("{} {}: a {} has no face `{}` to paint; its faces are {}", cat, id, cat, face, fs.join(", ")));
            }
        }
        if lib_name(pr, "material", mat).is_none() {
            return Err(format!(
                "{} {}: its `{}` is painted a material of the library, not {}; add one with `material`",
                cat,
                id,
                face,
                mat.to_compact()
            ));
        }
    }
    Ok(())
}

/// What the drafting styles name, checked (as the original checks them) before the text types: a
/// line style's pattern, a filled region type's patterns.
pub fn styles(pr: &Project) -> R<()> {
    let lib_missing = |kind: &str, v: &Value| lib_name(pr, kind, v).is_none();
    if let Some(ls) = pr.section("line_styles") {
        for (name, s) in ls.iter() {
            if let Some(p) = s.get("pattern").filter(|v| !v.is_null()) {
                if lib_missing("line-pattern", p) {
                    let all = names(pr, &["line_patterns"]);
                    return Err(format!("line style `{}`: there's no line pattern `{}` (there are: Solid, {})", name, shown(p), there_are(&all)));
                }
            }
        }
    }
    // the fill patterns' own rules, as the fill pattern commands keep them
    if let Some(fp) = pr.section("fill_patterns") {
        for (name, p) in fp.iter() {
            crate::styles::fills::Pattern::from_value(p).check(name)?;
        }
    }
    if let Some(rt) = pr.section("region_types") {
        for (name, t) in rt.iter() {
            for k in ["foreground", "background"] {
                if let Some(p) = t.get(k).filter(|v| !v.is_null()) {
                    if lib_missing("fill-pattern", p) {
                        return Err(format!(
                            "filled region type `{}`: there's no fill pattern `{}` (there are: {})",
                            name,
                            shown(p),
                            there_are(&names(pr, &["fill_patterns"]))
                        ));
                    }
                }
            }
        }
    }
    Ok(())
}

/// The run types' categories: each one a run's.
const RUN_CATEGORIES: &str = "beam, stripfooting, pipe, duct, conduit, cabletray, wire, downconductor, groundconductor, cable";

/// What the materials name, and the types' run categories, checked after the drafting styles.
pub fn materials(pr: &Project) -> R<()> {
    let lib_missing = |kind: &str, v: &Value| lib_name(pr, kind, v).is_none();
    if let Some(ms) = pr.section("materials") {
        for (name, m) in ms.iter() {
            for k in ["cut_pattern", "surface_pattern"] {
                if let Some(p) = m.get(k).filter(|v| !v.is_null()) {
                    if lib_missing("fill-pattern", p) {
                        return Err(format!("material `{}`: there's no fill pattern `{}`", name, shown(p)));
                    }
                }
            }
            if let Some(img) = m.get("texture").and_then(|t| t.get("image")).filter(|v| !v.is_null()) {
                if lib_missing("picture", img) {
                    return Err(format!(
                        "material `{}`: texture: it's of picture `{}`, which the project doesn't hold (it has: {})",
                        name,
                        shown(img),
                        names(pr, &["images"]).join(", ")
                    ));
                }
            }
        }
    }
    Ok(())
}

/// The run types' categories are runs'.
pub fn runs(pr: &Project) -> R<()> {
    if let Some(Value::Obj(r)) = pr.get("types").and_then(|t| t.get("runs")) {
        for (cat, _) in r.iter() {
            if !RUNS.contains(&cat.as_str()) {
                return Err(format!("`{}` has no run types; there are {}", cat, RUN_CATEGORIES));
            }
        }
    }
    Ok(())
}

/// Every element's rules, in id order, then the library's ids, then what the elements point at by
/// their ids.
pub fn check(pr: &Project) -> R<()> {
    let by_id = element_rules(pr)?;
    library_ids(pr)?;
    element_ids(pr, by_id)
}

/// Every element's references and numbers, in id order.
pub fn elements(pr: &Project) -> R<()> {
    let by_id = element_rules(pr)?;
    element_ids(pr, by_id)
}

/// Each element's rules, in id order; the first element each points at by its id.
fn element_rules(pr: &Project) -> R<Vec<Option<u64>>> {
    let ix = Index::new(pr);
    let mut by_id = Vec::new();
    for (id, e) in &pr.elements {
        if *id < 100_000 {
            return Err(format!("element {}: ids start at 100000", id));
        }
        by_id.push(element(&ix, *id, e)?);
    }
    Ok(by_id)
}

/// What each element points at by its id, or among elements the project doesn't have, in id
/// order (the original checks these last).
fn element_ids(pr: &Project, by_id: Vec<Option<u64>>) -> R<()> {
    let ix = Index::new(pr);
    for ((id, e), n) in pr.elements.iter().zip(by_id) {
        let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("");
        if let Some(n) = n {
            return Err(format!("{} {} points at element {} by its id, not its GUID", cat, id, n));
        }
        if let Some(g) = e.get("graphics") {
            graphics_keys(&ix, &format!("{} {}", cat, id), g)?;
        }
    }
    Ok(())
}

/// The most a length (or a coordinate) of the model may be, either way: a million km.
const MAX: f64 = 1e9;

/// One element, checked as the original checks it: what it names and what it holds, in the order
/// it takes them for its category; the first element it points at by its id kept (it reports that
/// last).
struct El<'a> {
    /// How its messages name it: `wall 100007`, `detail group `A` member 0`.
    name: String,
    ix: &'a Index<'a>,
    pr: &'a Project,
    cat: &'a str,
    e: &'a Value,
    by_id: Option<u64>,
}

impl<'a> El<'a> {
    fn who(&self) -> String {
        self.name.clone()
    }
    fn err<T>(&self, m: String) -> R<T> {
        Err(format!("{}: {}", self.who(), m))
    }
    fn note(&mut self, t: &Target) {
        if t.by_id && self.by_id.is_none() {
            self.by_id = t.id;
        }
    }
    fn get(&self, k: &str) -> Option<&'a Value> {
        self.e.get(k).filter(|v| !v.is_null())
    }
    fn f(&self, k: &str) -> Option<f64> {
        self.e.get(k).and_then(|v| v.as_f64())
    }
    fn no_top(&self) -> bool {
        self.e.get("top_level").map(|t| t.is_null()).unwrap_or(true)
    }

    // ------------------------------------------------ numbers the model can use

    fn bad(&self, label: &str, x: f64) -> R<()> {
        if x.is_finite() && x.abs() <= MAX {
            Ok(())
        } else {
            Err(format!("{} {}: {} is not a usable number", self.who(), label, x))
        }
    }
    fn num(&self, k: &str, label: &str) -> R<()> {
        match self.f(k) {
            Some(x) => self.bad(label, x),
            None => Ok(()),
        }
    }
    fn pt(&self, v: Option<&Value>, lx: &str, ly: &str) -> R<()> {
        if let Some(Value::Arr(a)) = v {
            if let Some(x) = a.first().and_then(|x| x.as_f64()) {
                self.bad(lx, x)?;
            }
            if let Some(y) = a.get(1).and_then(|y| y.as_f64()) {
                self.bad(ly, y)?;
            }
        }
        Ok(())
    }
    fn pts(&self, v: Option<&Value>, lx: &str, ly: &str) -> R<()> {
        if let Some(Value::Arr(a)) = v {
            for p in a {
                self.pt(Some(p), lx, ly)?;
            }
        }
        Ok(())
    }
    fn pt3(&self, v: Option<&Value>, l: &str) -> R<()> {
        if let Some(Value::Arr(a)) = v {
            for (i, x) in a.iter().enumerate() {
                if let Some(x) = x.as_f64() {
                    let axis = ["x", "y", "z"].get(i).copied().unwrap_or("z");
                    self.bad(&format!("{} {}", l, axis), x)?;
                }
            }
        }
        Ok(())
    }
    /// Its outline's openings (`opening 0 x`…).
    fn holes(&self, key: &str, label: &str, indexed: bool) -> R<()> {
        if let Some(Value::Arr(ops)) = self.e.get(key) {
            for (i, o) in ops.iter().enumerate() {
                let (lx, ly) = if indexed {
                    (format!("{} {} x", label, i), format!("{} {} y", label, i))
                } else {
                    (format!("{} x", label), format!("{} y", label))
                };
                self.pts(Some(o), &lx, &ly)?;
            }
        }
        Ok(())
    }

    // ------------------------------------------------ what it points at

    fn level_ref(&mut self, key: &str) -> R<()> {
        if let Some(t) = self.e.get(key).and_then(|v| target(self.ix, v)) {
            match t.id {
                Some(n) if self.ix.cat(n) == "level" => self.note(&t),
                _ => return self.err(format!("level {} doesn't exist", t.shown)),
            }
        }
        Ok(())
    }
    fn level(&mut self) -> R<()> {
        self.level_ref("level")
    }
    /// Its top: its top level, or its height when it has none.
    fn top(&mut self, height: &str) -> R<()> {
        if self.no_top() {
            self.num("height", height)
        } else {
            self.level_ref("top_level")
        }
    }
    /// Its type, where its category's are the project's types.
    fn ty(&self) -> R<()> {
        let cat = self.cat;
        let t = match self.e.get("type") {
            Some(t) => t,
            None => return Ok(()),
        };
        let (kind, path) = if RUNS.contains(&cat) {
            (format!("type:{}", cat), vec!["types".to_string(), "runs".to_string(), cat.to_string()])
        } else if let Some(p) = type_section(cat) {
            (format!("type:{}", cat), p.iter().map(|s| s.to_string()).collect())
        } else {
            return Ok(());
        };
        if lib_name(self.pr, &kind, t).is_none() {
            let p: Vec<&str> = path.iter().map(|s| s.as_str()).collect();
            return self.err(format!("type `{}` doesn't exist (there are: {})", shown(t), there_are(&names(self.pr, &p))));
        }
        Ok(())
    }
    /// Its family (a component's, or a door's or a window's of a family).
    fn family(&self) -> R<Option<String>> {
        let f = match self.get("family") {
            Some(f) => f,
            None => return Ok(None),
        };
        match lib_name(self.pr, "family", f) {
            Some(n) => Ok(Some(n)),
            None => {
                let all: Vec<String> = match self.cat {
                    "door" | "window" => self
                        .pr
                        .section("families")
                        .map(|m| {
                            m.iter()
                                .filter(|(_, v)| v.get("category").and_then(|c| c.as_str()) == Some(self.cat))
                                .map(|(k, _)| k.clone())
                                .collect()
                        })
                        .unwrap_or_default(),
                    _ => names(self.pr, &["families"]),
                };
                Err(format!("{}: family `{}` doesn't exist (there are: {})", self.who(), shown(f), there_are(&all)))
            }
        }
    }
    /// Its type in its family.
    fn family_type(&self, family: &str) -> R<()> {
        if let Some(t) = self.e.get("type") {
            if lib_name(self.pr, "family-type", t).is_none() {
                let types = names(self.pr, &["families", family, "types"]);
                return self.err(format!("type `{}` doesn't exist (there are: {})", shown(t), there_are(&types)));
            }
        }
        Ok(())
    }
    fn named(&self, key: &str, kind: &str, what: &str, section: &str, list: bool) -> R<()> {
        let v = match self.e.get(key) {
            Some(v) if !v.is_null() => v,
            _ => return Ok(()),
        };
        if lib_name(self.pr, kind, v).is_none() {
            let tail = if list { format!(" (there are: {})", there_are(&names(self.pr, &[section]))) } else { String::new() };
            return self.err(format!("there's no {} `{}`{}", what, shown(v), tail));
        }
        Ok(())
    }
    /// The view an annotation is drawn in: a plan, a section, an elevation (or a sheet).
    fn drawn_in(&mut self, sheet_ok: bool) -> R<()> {
        if let Some(t) = self.e.get("view").and_then(|v| target(self.ix, v)) {
            match t.id {
                None => return self.err(format!("view {} doesn't exist", t.shown)),
                Some(n) if !is_view(self.ix.cat(n), sheet_ok) => {
                    let tail = if sheet_ok { "a plan, a section, an elevation or a sheet" } else { "a plan, a section, an elevation" };
                    return self.err(format!("{} {} isn't {}", self.ix.cat(n), n, tail));
                }
                Some(_) => self.note(&t),
            }
        }
        Ok(())
    }
    /// A view that must be a plan view of this level (by GUID).
    fn plan_of(&mut self, level: Option<&Value>, what: &str) -> R<()> {
        if let Some(t) = self.e.get("view").and_then(|v| target(self.ix, v)) {
            let ok = t.id.map(|n| {
                let v = &self.pr.elements[&n];
                v.get("category").and_then(|c| c.as_str()) == Some("planview")
                    && level.is_some()
                    && v.get("level") == level
            });
            match ok {
                Some(true) => self.note(&t),
                _ => return self.err(format!("view {} isn't a plan view of {}", t.shown, what)),
            }
        }
        Ok(())
    }
    fn element_ref(&mut self, key: &str) -> R<()> {
        if let Some(t) = self.e.get(key).and_then(|v| target(self.ix, v)) {
            match t.id {
                None => return self.err(format!("element {} doesn't exist", t.shown)),
                Some(_) => self.note(&t),
            }
        }
        Ok(())
    }

    // ------------------------------------------------ what it draws with and in

    fn graphics(&self) -> R<()> {
        match self.e.get("graphics") {
            Some(g) => graphics(self.ix, &self.who(), g, false),
            None => Ok(()),
        }
    }
    /// Its sketch's lines: each point a number within the model.
    fn sketch(&self) -> R<()> {
        if let Some(Value::Arr(ls)) = self.e.get("sketch") {
            for (i, l) in ls.iter().enumerate() {
                if !curve_within(l) {
                    return self.err(format!(
                        "sketch line {} has a point that isn't a number within 1000000000 mm, or a curve reaching further",
                        i
                    ));
                }
            }
        }
        Ok(())
    }
}

/// A curve's points (and its circle, for one of a centre and a radius) are within the model.
fn curve_within(l: &Value) -> bool {
    let ok = |x: &Value| x.as_f64().map(|f| f.is_finite() && f.abs() <= MAX).unwrap_or(true);
    let point_ok = |p: Option<&Value>| p.and_then(|p| p.as_arr()).map(|a| a.iter().all(ok)).unwrap_or(true);
    for k in ["start", "end", "through", "centre", "start_tangent", "end_tangent"] {
        if !point_ok(l.get(k)) {
            return false;
        }
    }
    for k in ["points", "control", "fit"] {
        if let Some(Value::Arr(ps)) = l.get(k) {
            if !ps.iter().all(|p| point_ok(Some(p))) {
                return false;
            }
        }
    }
    if let (Some(c), Some(r)) = (point2(l.get("centre")), l.get("radius").and_then(|r| r.as_f64())) {
        if c.0.hypot(c.1) + r.abs() > MAX {
            return false;
        }
    }
    for (a, b, t) in arcs_of(l) {
        if arc_reach(a, b, t).map(|r| r > MAX).unwrap_or(false) {
            return false;
        }
    }
    true
}

fn point2(v: Option<&Value>) -> Option<(f64, f64)> {
    let a = v?.as_arr()?;
    Some((a.first()?.as_f64()?, a.get(1)?.as_f64()?))
}

/// How far from the origin the circle of an arc from `a` to `b` turning `turn` degrees reaches
/// (None: it turns too little to be other than straight, or has no length).
fn arc_reach(a: (f64, f64), b: (f64, f64), turn: f64) -> Option<f64> {
    let t = turn.to_radians();
    if t.abs() < 1e-9 {
        return None;
    }
    let (dx, dy) = (b.0 - a.0, b.1 - a.1);
    let c = dx.hypot(dy);
    if c == 0.0 {
        return None;
    }
    let half = t / 2.0;
    let r = c / (2.0 * half.sin().abs());
    let off = (c / 2.0) / half.tan();
    let (nx, ny) = (-dy / c, dx / c);
    let (cx, cy) = ((a.0 + b.0) / 2.0 + nx * off, (a.1 + b.1) / 2.0 + ny * off);
    Some(cx.hypot(cy) + r)
}

/// The arcs of a curve: its start and end with its turn, or each of its points' segments with
/// theirs.
fn arcs_of(l: &Value) -> Vec<((f64, f64), (f64, f64), f64)> {
    let mut out = Vec::new();
    if let (Some(a), Some(b), Some(t)) = (point2(l.get("start")), point2(l.get("end")), l.get("arc").and_then(|x| x.as_f64())) {
        out.push((a, b, t));
    }
    if let (Some(Value::Arr(ps)), Some(Value::Arr(ts))) = (l.get("points"), l.get("arcs")) {
        let pts: Vec<(f64, f64)> = ps.iter().filter_map(|p| point2(Some(p))).collect();
        let closed = l.get("closed").and_then(|c| c.as_bool()).unwrap_or(false);
        for (i, t) in ts.iter().enumerate() {
            let t = match t.as_f64() {
                Some(t) => t,
                None => continue,
            };
            let a = match pts.get(i) {
                Some(a) => *a,
                None => continue,
            };
            let b = match pts.get(i + 1) {
                Some(b) => *b,
                None if closed && !pts.is_empty() => pts[0],
                None => continue,
            };
            out.push((a, b, t));
        }
    }
    out
}

/// A detail line's geometry, as the original checks it.
fn line_geometry(c: &El) -> R<()> {
    let e = c.e;
    let within = |x: &Value| x.as_f64().map(|f| f.is_finite() && f.abs() <= MAX).unwrap_or(true);
    let point_ok = |p: Option<&Value>| p.and_then(|p| p.as_arr()).map(|a| a.iter().all(within)).unwrap_or(true);
    for k in ["start", "end"] {
        if !point_ok(e.get(k)) {
            return c.err("a point isn't a number within 1000000000 mm".into());
        }
    }
    for k in ["points", "fit"] {
        if let Some(Value::Arr(ps)) = e.get(k) {
            if !ps.iter().all(|p| point_ok(Some(p))) {
                return c.err("a point isn't a number within 1000000000 mm".into());
            }
        }
    }
    if let Some(Value::Arr(ps)) = e.get("control") {
        if !ps.iter().all(|p| point_ok(Some(p))) {
            return c.err("a control point isn't a number within 1000000000 mm".into());
        }
    }
    // its points, one after another, apart
    let same = |a: Option<(f64, f64)>, b: Option<(f64, f64)>| matches!((a, b), (Some(a), Some(b)) if a == b);
    let mut repeated = same(point2(e.get("start")), point2(e.get("end")));
    if let Some(Value::Arr(ps)) = e.get("points") {
        let pts: Vec<Option<(f64, f64)>> = ps.iter().map(|p| point2(Some(p))).collect();
        repeated |= pts.windows(2).any(|w| same(w[0], w[1]));
    }
    if repeated {
        return c.err("two points one after another are the same; a line runs between points apart".into());
    }
    if let Some(Value::Arr(ps)) = e.get("points") {
        let closed = e.get("closed").and_then(|c| c.as_bool()).unwrap_or(false);
        match e.get("arcs") {
            Some(Value::Arr(ts)) => {
                let segments = if closed { ps.len() } else { ps.len().saturating_sub(1) };
                if ts.len() != segments {
                    return c.err(format!("`arcs` gives one turn for each of its {} segments, not {}", segments, ts.len()));
                }
            }
            _ => {
                if closed && ps.len() < 3 {
                    return c.err("a closed line needs three points or more, or arcs".into());
                }
            }
        }
    }
    if let Some(Value::Arr(ks)) = e.get("knots") {
        let ks: Vec<f64> = ks.iter().filter_map(|k| k.as_f64()).collect();
        let ok = ks.iter().all(|k| k.is_finite() && k.abs() <= MAX) && ks.windows(2).all(|w| w[1] >= w[0]);
        if !ok {
            return c.err("its knots are numbers, each no less than the one before".into());
        }
    }
    if !point_ok(e.get("centre")) {
        return c.err("its centre isn't a point within 1000000000 mm".into());
    }
    let mut turns: Vec<f64> = e.get("arc").and_then(|a| a.as_f64()).into_iter().collect();
    if let Some(Value::Arr(a)) = e.get("arcs") {
        turns.extend(a.iter().filter_map(|x| x.as_f64()));
    }
    for t in turns {
        if !(t.abs() < 360.0) {
            return c.err(format!("an arc turns {}°; it turns less than a whole circle, either way", t));
        }
    }
    for (a, b, t) in arcs_of(e) {
        if arc_reach(a, b, t).map(|r| r > MAX).unwrap_or(false) {
            return c.err(
                "an arc of it is part of a circle that reaches further than 1000000000 mm from the origin: it turns almost nothing, or almost a whole circle, so its circle is huge"
                    .into(),
            );
        }
    }
    let length_ok = |r: f64| r > 1.0 && r <= MAX;
    if let Some(r) = e.get("radius").and_then(|r| r.as_f64()) {
        if !length_ok(r) {
            return c.err(format!("its radius is {} mm; it's more than 1 mm and at most 1000000000", r));
        }
        if let Some(ct) = point2(e.get("centre")) {
            if ct.0.hypot(ct.1) + r > MAX {
                return c.err("the circle reaches further than 1000000000 mm from the origin; move it in or make it smaller".into());
            }
        }
    }
    if let Some(Value::Arr(rr)) = e.get("radii") {
        // an ellipse's radii by their size (the file keeps their signs)
        let rs: Vec<f64> = rr.iter().filter_map(|x| x.as_f64()).map(f64::abs).collect();
        for (i, r) in rs.iter().enumerate() {
            if !length_ok(*r) {
                let which = if i == 0 { "first" } else { "second" };
                return c.err(format!("its {} radius is {} mm; it's more than 1 mm and at most 1000000000", which, r));
            }
        }
        if let Some(ct) = point2(e.get("centre")) {
            let big = rs.iter().cloned().fold(0.0, f64::max);
            if ct.0.hypot(ct.1) + big > MAX {
                return c.err("the ellipse reaches further than 1000000000 mm from the origin; move it in or make it smaller".into());
            }
        }
    }
    if let Some(a) = e.get("angle").and_then(|a| a.as_f64()) {
        if !(a.abs() <= 1e6) {
            return c.err(format!("its angle {}° isn't a number of degrees", a));
        }
    }
    if let Some(Value::Arr(sp)) = e.get("span") {
        let s: Vec<f64> = sp.iter().filter_map(|x| x.as_f64()).collect();
        if !s.iter().all(|x| x.abs() <= 1e6) {
            return c.err("its span isn't two angles in degrees".into());
        }
        if let [a, b] = s[..] {
            if (b - a).abs() < 1e-6 {
                return c.err(format!("its span from {}° to {}° is nothing; give two angles apart", a, b));
            }
        }
    }
    for k in ["start_tangent", "end_tangent"] {
        if let Some(t) = point2(e.get(k)) {
            let nothing = !(t.0.abs() <= MAX && t.1.abs() <= MAX) || t.0.hypot(t.1) < 1e-9;
            if nothing {
                return c.err("a tangent is a direction [x, y], not nothing".into());
            }
        }
    }
    if let (Some(Value::Arr(cp)), Some(Value::Arr(ks))) = (e.get("control"), e.get("knots")) {
        knots(c, cp.len(), &ks.iter().filter_map(|k| k.as_f64()).collect::<Vec<f64>>())?;
    }
    if let Some(len) = curve_length(e) {
        if len <= 1.0 {
            return c.err("it is 1 mm long or less".into());
        }
    }
    if e.get("insulation").map(|v| !v.is_null()).unwrap_or(false) && e.get("cloud").map(|v| !v.is_null()).unwrap_or(false) {
        return c.err("it is insulation or a revision cloud, not both".into());
    }
    if let Some(w) = e.get("insulation").and_then(|x| x.as_f64()) {
        if !(w > 1.0 && w <= 10_000.0) {
            return c.err(format!("its insulation is {} mm wide; it's more than 1 mm and at most 10000", w));
        }
    }
    if let Some(w) = e.get("cloud").and_then(|x| x.as_f64()) {
        if !(w > 1.0 && w <= 10_000.0) {
            return c.err(format!("its cloud's arcs are {} mm long; they're more than 1 mm and at most 10000", w));
        }
    }
    Ok(())
}

/// A spline's knots: as many as its control points and its degree (1 to 5, below their count) and
/// one more, its ends each its degree's and one more times, none inside more than its degree.
fn knots(c: &El, n: usize, ks: &[f64]) -> R<()> {
    let k = ks.len();
    let d = k as i64 - n as i64 - 1;
    if d < 1 || d > 5.min(n as i64 - 1) {
        return c.err(format!(
            "a spline of {} control points has {} plus its degree plus one knots (degree 1 to 5, below {}), not {}",
            n, n, n, k
        ));
    }
    let d = d as usize;
    let (first, last) = (ks[0], ks[k - 1]);
    if first == last || !ks[..=d].iter().all(|x| *x == first) || !ks[k - 1 - d..].iter().all(|x| *x == last) {
        return c.err(format!(
            "its first {} knots are the same, and its last {}, so it runs from its first control point to its last",
            d + 1,
            d + 1
        ));
    }
    for v in ks {
        let count = ks.iter().filter(|x| *x == v).count();
        let allowed = if *v == first || *v == last { d + 1 } else { d };
        if count > allowed {
            return c.err(format!("no knot inside it comes more than {} times", d));
        }
    }
    Ok(())
}

/// How long a detail line's curve is, where that can be told for sure: a line or an arc, a
/// polyline, a circle or an ellipse (or part of one), a spline no longer than its control points'
/// polygon (None for a spline through points).
fn curve_length(e: &Value) -> Option<f64> {
    let seg = |a: (f64, f64), b: (f64, f64), turn: f64| -> f64 {
        let c = (b.0 - a.0).hypot(b.1 - a.1);
        let t = turn.to_radians().abs();
        if t < 1e-9 || c == 0.0 {
            c
        } else {
            c / (2.0 * (t / 2.0).sin()) * t
        }
    };
    if let (Some(a), Some(b)) = (point2(e.get("start")), point2(e.get("end"))) {
        return Some(seg(a, b, e.get("arc").and_then(|x| x.as_f64()).unwrap_or(0.0)));
    }
    if let Some(Value::Arr(ps)) = e.get("points") {
        let pts: Vec<(f64, f64)> = ps.iter().filter_map(|p| point2(Some(p))).collect();
        let turns: Vec<f64> = match e.get("arcs") {
            Some(Value::Arr(a)) => a.iter().map(|x| x.as_f64().unwrap_or(0.0)).collect(),
            _ => Vec::new(),
        };
        let closed = e.get("closed").and_then(|c| c.as_bool()).unwrap_or(false);
        let n = if closed { pts.len() } else { pts.len().saturating_sub(1) };
        let mut len = 0.0;
        for i in 0..n {
            len += seg(pts[i], pts[(i + 1) % pts.len()], turns.get(i).cloned().unwrap_or(0.0));
        }
        return Some(len);
    }
    if let Some(r) = e.get("radius").and_then(|x| x.as_f64()) {
        return Some(2.0 * std::f64::consts::PI * r.abs());
    }
    if let Some(Value::Arr(rr)) = e.get("radii") {
        let rs: Vec<f64> = rr.iter().filter_map(|x| x.as_f64()).map(f64::abs).collect();
        if rs.len() != 2 {
            return None;
        }
        let (from, to) = match e.get("span") {
            Some(Value::Arr(s)) if s.len() == 2 => (s[0].as_f64()?.to_radians(), s[1].as_f64()?.to_radians()),
            _ => (0.0, 2.0 * std::f64::consts::PI),
        };
        // along it, in many short steps
        let steps = 4096;
        let mut len = 0.0;
        let at = |t: f64| (rs[0] * t.cos(), rs[1] * t.sin());
        let mut prev = at(from);
        for i in 1..=steps {
            let p = at(from + (to - from) * i as f64 / steps as f64);
            len += (p.0 - prev.0).hypot(p.1 - prev.1);
            prev = p;
        }
        return Some(len);
    }
    if let Some(Value::Arr(ps)) = e.get("control") {
        let pts: Vec<(f64, f64)> = ps.iter().filter_map(|p| point2(Some(p))).collect();
        let poly: f64 = pts.windows(2).map(|w| (w[1].0 - w[0].0).hypot(w[1].1 - w[0].1)).sum();
        // the curve is no longer than its polygon: short for sure only when that is
        return if poly <= 1.0 { Some(poly) } else { None };
    }
    None
}

/// A landing's turn: straight on, left or right, or back.
fn landings(c: &El) -> R<()> {
    if let Some(Value::Arr(ls)) = c.e.get("landings") {
        for l in ls {
            if let Some(x) = l.get("at").and_then(|v| v.as_f64()) {
                c.bad("landing", x)?;
            }
            if let Some(t) = l.get("turn").and_then(|v| v.as_f64()) {
                if ![0.0, 90.0, -90.0, 180.0, -180.0].contains(&t) {
                    return c.err(format!(
                        "a landing turns 0 (straight on), 90 or -90 (left or right), or 180 or -180 (back beside the run, to its left or its right), not {}",
                        t
                    ));
                }
            }
        }
    }
    Ok(())
}

/// A 3D view: its angles, its graphics, its section box, its lens, its camera, its edges and its
/// work plane.
fn view3d(c: &El) -> R<()> {
    let e = c.e;
    c.num("azimuth", "azimuth")?;
    if let Some(el) = c.f("elevation") {
        if !(-89.0..=89.0).contains(&el) {
            return c.err(format!("elevation {}° isn't between -89° and 89°", el));
        }
    }
    c.graphics()?;
    if let Some(b) = c.get("section_box") {
        c.pt3(b.get("min"), "section box")?;
        c.pt3(b.get("max"), "section box")?;
        let v3 = |k: &str| -> Vec<f64> { b.get(k).and_then(|a| a.as_arr()).map(|a| a.iter().filter_map(|x| x.as_f64()).collect()).unwrap_or_default() };
        let (lo, hi) = (v3("min"), v3("max"));
        for (i, axis) in ["x", "y", "z"].iter().enumerate() {
            if let (Some(a), Some(b)) = (lo.get(i), hi.get(i)) {
                if b - a < 10.0 {
                    return c.err(format!(
                        "its section box runs from {} to {} mm in {}; its max is at least 10 mm past its min on each axis",
                        a, b, axis
                    ));
                }
            }
        }
    }
    if let Some(l) = c.get("perspective").and_then(|p| p.get("lens")).and_then(|l| l.as_f64()) {
        if !(10.0..=600.0).contains(&l) {
            return c.err(format!("a {} mm lens is no camera's; a perspective's lens is 10 to 600 mm", l));
        }
    }
    if let Some(cam) = c.get("camera") {
        c.pt3(cam.get("eye"), "camera eye")?;
        c.pt3(cam.get("target"), "camera target")?;
        let v3 = |k: &str| -> Vec<f64> { cam.get(k).and_then(|a| a.as_arr()).map(|a| a.iter().filter_map(|x| x.as_f64()).collect()).unwrap_or_default() };
        let (a, b) = (v3("eye"), v3("target"));
        if a.len() == 3 && b.len() == 3 {
            let d = ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt();
            if d <= 1.0 {
                return c.err("its camera's eye is on its target, so it has nothing to look at; give them two points a little apart".into());
            }
        }
    }
    if let Some(s) = e.get("display").and_then(|d| d.get("silhouette")).and_then(|s| s.as_u64()) {
        if s > 10 {
            return c.err(format!("a silhouette {} px wide is wider than the 10 px one may be", s));
        }
    }
    if let Some(wp) = c.get("work_plane") {
        let given = ["level", "points", "surface"].iter().filter(|k| wp.get(k).map(|v| !v.is_null()).unwrap_or(false)).count();
        if given > 1 {
            return c.err("a work plane is on a `level`, through three `points` or on a `surface`: only one of them".into());
        }
        let place = |p: &Value| p.as_arr().map(|a| a.iter().all(|x| x.as_f64().map(|f| f.abs() <= MAX).unwrap_or(true))).unwrap_or(true);
        if let Some(Value::Arr(ps)) = wp.get("points") {
            if !ps.iter().all(place) {
                return c.err("a point of the work plane isn't a place in the project".into());
            }
            // a triangle, its least height more than 1 mm
            let p: Vec<Vec<f64>> = ps.iter().map(|p| p.as_arr().map(|a| a.iter().filter_map(|x| x.as_f64()).collect()).unwrap_or_default()).collect();
            if p.len() == 3 && p.iter().all(|q| q.len() == 3) {
                let sub = |a: &[f64], b: &[f64]| [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
                let len = |v: [f64; 3]| (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt();
                let (u, v) = (sub(&p[1], &p[0]), sub(&p[2], &p[0]));
                let n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
                let longest = len(u).max(len(v)).max(len(sub(&p[2], &p[1])));
                if len(n) <= longest {
                    return c.err("the work plane's three points lie along a line: pick three that make a triangle".into());
                }
            }
        }
        if let Some(o) = wp.get("offset").and_then(|o| o.as_f64()) {
            if !(o.abs() <= MAX) {
                return c.err(format!("its work plane's offset {} isn't a length", o));
            }
        }
        if let Some(s) = wp.get("surface").filter(|s| !s.is_null()) {
            if let Some(p) = s.get("point") {
                if !place(p) {
                    return c.err("the work plane's surface point isn't a place in the project".into());
                }
            }
            let n: Vec<f64> = s.get("normal").and_then(|a| a.as_arr()).map(|a| a.iter().filter_map(|x| x.as_f64()).collect()).unwrap_or_default();
            if !n.is_empty() && n.iter().all(|x| *x == 0.0) {
                return c.err("the work plane's surface `normal` is the way it faces, [x, y, z], and can't be [0, 0, 0]".into());
            }
        }
    }
    Ok(())
}

/// A link: its name and file, where it is, how it turns.
fn link(c: &El) -> R<()> {
    let s = |k: &str| c.e.get(k).and_then(|v| v.as_str()).unwrap_or("");
    let (name, path) = (s("name"), s("path"));
    if name.chars().count() > 256 {
        return c.err("name is longer than 256 characters".into());
    }
    if name.trim().is_empty() || path.trim().is_empty() || path.chars().count() > 256 {
        return c.err("a link needs a name and the path of a file, up to 256 characters".into());
    }
    c.pt(c.e.get("at"), "at x", "at y")?;
    if let Some(a) = c.f("angle") {
        if !(-360.0..=360.0).contains(&a) {
            return c.err(format!("its angle {}° isn't between -360° and 360°", a));
        }
    }
    Ok(())
}

/// One element's checks, in the order the original takes them for its category; the first element
/// it points at by its id.
fn element(ix: &Index, id: u64, e: &Value) -> R<Option<u64>> {
    let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("");
    let mut c = El { name: format!("{} {}", cat, id), ix, pr: ix.pr, cat, e, by_id: None };
    // what it's painted with comes first
    paint(c.pr, id, cat, e)?;
    match cat {
        "level" => {
            c.num("elevation", "elevation")?;
            c.num("computation_height", "computation height")?;
            view_range(&c)?;
            c.pts(e.get("crop"), "crop x", "crop y")?;
            c.pts(e.get("extent"), "extent x", "extent y")?;
            c.graphics()?;
        }
        "grid" | "roomseparator" => {
            c.level()?;
            c.pt(e.get("start"), "x", "y")?;
            c.pt(e.get("end"), "x", "y")?;
        }
        "wall" => {
            c.ty()?;
            c.level()?;
            c.pt(e.get("start"), "x", "y")?;
            c.pt(e.get("end"), "x", "y")?;
            c.num("base_offset", "base_offset")?;
            if c.no_top() {
                c.num("height", "height")?;
            }
            if let Some(a) = c.f("arc") {
                if !(-360.0..=360.0).contains(&a) {
                    return c.err(format!("arc {}° isn't between -360° and 360°, reaching no farther than 1000 km", a));
                }
            }
            attach(&mut c)?;
            if !c.no_top() {
                c.level_ref("top_level")?;
            }
            c.num("top_offset", "top offset")?;
        }
        "floor" => {
            c.pt(e.get("pattern_origin"), "pattern origin x", "pattern origin y")?;
            c.num("pattern_angle", "pattern angle")?;
            c.ty()?;
            c.level()?;
            c.pts(e.get("boundary"), "x", "y")?;
            c.holes("openings", "opening", true)?;
            c.sketch()?;
            c.num("offset", "offset")?;
            let slope = c.f("slope").unwrap_or(0.0);
            if !(-75.0..=75.0).contains(&slope) {
                return c.err(format!("slope {}° isn't between -75° and 75°", slope));
            }
            if slope != 0.0 && c.get("arrow").is_none() {
                return c.err("a sloped floor needs a slope arrow, from where its top is at its offset toward where it rises".into());
            }
            c.pts(e.get("arrow"), "arrow x", "arrow y")?;
            let shaped = e.get("shape").map(|sh| {
                ["points", "lines"].iter().any(|k| sh.get(k).and_then(|v| v.as_arr()).map(|a| !a.is_empty()).unwrap_or(false))
            });
            if slope != 0.0 && shaped == Some(true) {
                return c.err(
                    "a shaped floor takes its falls from its points, not a slope arrow too: `modify` its `slope` to 0, or `reset_shape`".into(),
                );
            }
            shape(&c)?;
        }
        "ceiling" => {
            c.ty()?;
            c.level()?;
            c.pts(e.get("boundary"), "x", "y")?;
            c.holes("openings", "opening", true)?;
            c.sketch()?;
            c.num("offset", "offset")?;
        }
        "shaft" => {
            c.level()?;
            c.pts(e.get("boundary"), "x", "y")?;
            c.num("base_offset", "base_offset")?;
            c.sketch()?;
            c.top("height")?;
        }
        "mass" => {
            c.level()?;
            c.pts(e.get("boundary"), "x", "y")?;
            c.num("base_offset", "base_offset")?;
            c.top("height")?;
            c.pts(e.get("top"), "top x", "top y")?;
        }
        "door" | "window" => {
            if let Some(t) = e.get("host").and_then(|v| target(ix, v)) {
                match t.id {
                    Some(n) if ix.cat(n) == "wall" => c.note(&t),
                    _ => return c.err(format!("host wall {} doesn't exist", t.shown)),
                }
            }
            match c.family()? {
                Some(f) => c.family_type(&f)?,
                None => c.ty()?,
            }
            c.num("offset", "offset")?;
            c.num("sill", "sill")?;
        }
        "room" => {
            c.level()?;
            c.pt(e.get("point"), "x", "y")?;
            if !c.no_top() {
                c.level_ref("top_level")?;
            }
            c.num("base_offset", "base offset")?;
            if let Some(k) = e.get("kept") {
                for side in ["centre", "finish"] {
                    if let Some(r) = k.get(side) {
                        let lx = format!("(room) kept {} boundary x", side);
                        let ly = format!("(room) kept {} boundary y", side);
                        c.pts(r.get("outer"), &lx, &ly)?;
                        if let Some(Value::Arr(hs)) = r.get("holes") {
                            for h in hs {
                                c.pts(Some(h), &lx, &ly)?;
                            }
                        }
                    }
                }
            }
            c.num("limit_offset", "limit offset")?;
        }
        "dimension" => {
            c.level()?;
            let level = e.get("level").cloned();
            c.plan_of(level.as_ref(), "its level")?;
            c.pt(e.get("at"), "x", "y")?;
            c.named("type", "dimension-type", "dimension type", "dimension_types", true)?;
            segments(&c)?;
            if let Some(Value::Arr(refs)) = e.get("refs") {
                for r in refs {
                    if let Some(t) = r.get("id").and_then(|v| target(ix, v)) {
                        match t.id {
                            None => return c.err(format!("element {} doesn't exist", t.shown)),
                            Some(_) => c.note(&t),
                        }
                    }
                }
            }
        }
        "dimension3d" => {
            if let Some(t) = e.get("view").and_then(|v| target(ix, v)) {
                match t.id {
                    Some(n) if ix.cat(n) == "view3d" => c.note(&t),
                    _ => return c.err(format!("view {} isn't a 3D view", t.shown)),
                }
            }
            let point = |v: Option<&Value>| -> R<()> {
                if let Some(Value::Arr(a)) = v {
                    for x in a.iter().filter_map(|x| x.as_f64()) {
                        c.bad("point", x)?;
                    }
                }
                Ok(())
            };
            if let Some(Value::Arr(rs)) = e.get("refs") {
                for r in rs {
                    point(r.get("at"))?;
                    if let Some(Value::Arr(ed)) = r.get("edge") {
                        for p in ed {
                            point(Some(p))?;
                        }
                    }
                }
            }
            point(e.get("at"))?;
            c.named("type", "dimension-type", "dimension type", "dimension_types", true)?;
        }
        "tag" => {
            let hv = e.get("host");
            let mut host_level: Option<Value> = None;
            if let Some(t) = hv.and_then(|v| target(ix, v)) {
                match t.id {
                    None => return c.err(format!("element {} doesn't exist", t.shown)),
                    Some(n) if !TAGGED.contains(&ix.cat(n)) => {
                        return c.err(format!(
                            "tags name what has a place in a plan (doors, windows, walls, columns, floors, rooms and the like), not {} {}",
                            ix.cat(n),
                            shown(hv.unwrap())
                        ))
                    }
                    Some(n) => {
                        c.note(&t);
                        host_level = level_of(c.pr, n);
                    }
                }
            }
            c.plan_of(host_level.as_ref(), "its host's level")?;
            c.pt(e.get("offset"), "offset x", "offset y")?;
        }
        "section" | "elevation" => {
            c.pt(e.get("start"), "x", "y")?;
            c.pt(e.get("end"), "x", "y")?;
            c.num("depth", "depth")?;
            if let Some(Value::Arr(cr)) = e.get("crop") {
                for x in cr.iter().filter_map(|x| x.as_f64()) {
                    c.bad("crop", x)?;
                }
            }
            c.graphics()?;
        }
        "viewport" => {
            if let Some(t) = e.get("sheet").and_then(|v| target(ix, v)) {
                match t.id {
                    Some(n) if ix.cat(n) == "sheet" => c.note(&t),
                    Some(n) => return c.err(format!("{} {} isn't a sheet", ix.cat(n), n)),
                    None => return c.err(format!("element {} isn't a sheet", t.shown)),
                }
            }
            if let Some(t) = e.get("view").and_then(|v| target(ix, v)) {
                let ok = |cc: &str| matches!(cc, "level" | "planview" | "section" | "elevation" | "schedule" | "view3d");
                match t.id {
                    Some(n) if ok(ix.cat(n)) => c.note(&t),
                    Some(n) => {
                        return c.err(format!("{} {} isn't a plan, a section, an elevation, a schedule or a 3D view", ix.cat(n), n))
                    }
                    None => {
                        return c.err(format!("element {} isn't a plan, a section, an elevation, a schedule or a 3D view", t.shown))
                    }
                }
            }
            c.pt(e.get("at"), "x", "y")?;
            if let Some(s) = c.f("scale") {
                if !(1.0..=100_000.0).contains(&s) {
                    return c.err(format!("scale 1 : {} isn't between 1 : 1 and 1 : 100000", s));
                }
            }
        }
        "column" | "structuralcolumn" | "footing" => {
            c.ty()?;
            c.level()?;
            c.pt(e.get("at"), "x", "y")?;
            c.num("angle", "angle")?;
            c.num("base_offset", "base_offset")?;
            c.top("height")?;
        }
        "beam" | "stripfooting" | "pipe" | "duct" | "conduit" | "cabletray" | "wire" | "downconductor" | "groundconductor"
        | "cable" => {
            c.ty()?;
            c.level()?;
            c.pt(e.get("start"), "start x", "start y")?;
            c.pt(e.get("end"), "end x", "end y")?;
            c.num("offset", "offset")?;
            c.num("end_offset", "end_offset")?;
        }
        "rebar" => {
            c.level()?;
            if let Some(dm) = c.f("diameter") {
                if !(3.0..=100.0).contains(&dm) {
                    return c.err(format!("diameter {} mm isn't between 3 and 100 mm", dm));
                }
            }
            if let Some(Value::Arr(ps)) = e.get("path") {
                if ps.len() < 2 || ps.len() > 10_000 {
                    return c.err("a path needs 2 to 10000 points".into());
                }
                let ok = ps.iter().all(|p| {
                    p.as_arr().map(|a| a.iter().all(|x| x.as_f64().map(|f| f.is_finite() && f.abs() <= MAX).unwrap_or(true))).unwrap_or(true)
                });
                if !ok {
                    return c.err("a point of its path is not finite or reaches past 1000000000 mm".into());
                }
            }
            if let Some(t) = e.get("host").and_then(|v| target(ix, v)) {
                match t.id {
                    None => return c.err(format!("host {} doesn't exist", t.shown)),
                    Some(n) if !matches!(ix.cat(n), "beam" | "column" | "structuralcolumn" | "footing" | "floor") => {
                        return c.err(format!("{} {} is no host for bars; a beam, a column, a footing or a floor is", ix.cat(n), n))
                    }
                    Some(_) => c.note(&t),
                }
            }
        }
        "component" => {
            let fam = c.family()?;
            c.level()?;
            c.pt(e.get("at"), "x", "y")?;
            c.num("angle", "angle")?;
            c.num("offset", "offset")?;
            if let Some(f) = fam {
                c.family_type(&f)?;
            }
        }
        "stair" | "ramp" => {
            c.level()?;
            c.pt(e.get("start"), "x", "y")?;
            c.num("angle", "angle")?;
            c.top("height")?;
            c.num("width", "width")?;
            if cat == "stair" {
                c.num("riser", "riser")?;
                c.num("tread", "tread")?;
            } else if let Some(s) = c.f("slope") {
                if !(1.0..=50.0).contains(&s) {
                    return c.err(format!("slope {}% isn't from 1% to 50%", s));
                }
            }
            landings(&c)?;
        }
        "railing" => {
            c.ty()?;
            c.level()?;
            c.num("base_offset", "base_offset")?;
            if let Some(t) = e.get("host").and_then(|v| target(ix, v)) {
                match t.id {
                    Some(n) if matches!(ix.cat(n), "stair" | "ramp") => c.note(&t),
                    _ => return c.err(format!("host {} isn't a stair or a ramp", t.shown)),
                }
            }
            c.pts(e.get("path"), "x", "y")?;
        }
        "roof" => {
            c.ty()?;
            c.level()?;
            c.num("overhang", "overhang")?;
            c.num("offset", "offset")?;
            c.pts(e.get("boundary"), "x", "y")?;
            c.holes("openings", "opening", false)?;
            if let Some(x) = e.get("extrusion") {
                if let Some(Value::Arr(l)) = x.get("line") {
                    for p in l {
                        c.pt(Some(p), "x", "y")?;
                    }
                }
                c.pts(x.get("profile"), "x", "y")?;
                for k in ["from", "to"] {
                    if let Some(v) = x.get(k).and_then(|v| v.as_f64()) {
                        c.bad(k, v)?;
                    }
                }
            }
            if let Some(s) = c.f("slope") {
                if !(0.0..=75.0).contains(&s) {
                    return c.err(format!("slope {}° isn't from 0° (flat) to 75°", s));
                }
            }
            if let Some(Value::Arr(ss)) = e.get("slopes") {
                for (i, s) in ss.iter().filter_map(|x| x.as_f64()).enumerate() {
                    if !(0.0..=75.0).contains(&s) {
                        return c.err(format!("edge {}'s slope {}° isn't from 0° (the roof's slope) to 75°", i, s));
                    }
                }
            }
            c.holes("courtyards", "courtyard", true)?;
            c.sketch()?;
            shape(&c)?;
            if let Some(t) = e.get("join").and_then(|v| target(ix, v)) {
                match t.id {
                    Some(n) if ix.cat(n) == "roof" => c.note(&t),
                    _ => return c.err(format!("it joins element {}, which isn't a roof that joins none", t.shown)),
                }
            }
        }
        "text" | "line" | "region" => {
            c.drawn_in(true)?;
            drafting(&c)?;
        }
        "detailgroup" => {
            c.drawn_in(true)?;
            c.pt(e.get("at"), "x", "y")?;
            c.num("angle", "angle")?;
            c.named("type", "detail-group", "detail group", "detail_groups", true)?;
        }
        "repeatingdetail" => {
            c.drawn_in(true)?;
            c.pt(e.get("start"), "x", "y")?;
            c.pt(e.get("end"), "x", "y")?;
            if let Some(sp) = c.f("spacing") {
                if !(1.0..=MAX).contains(&sp) {
                    return c.err(format!("spacing {} mm isn't from 1 mm to 1000000000", sp));
                }
                if let (Some(a), Some(b)) = (point2(e.get("start")), point2(e.get("end"))) {
                    let len = (b.0 - a.0).hypot(b.1 - a.1);
                    if (len / sp).floor() + 1.0 > 2000.0 {
                        return c.err("it would repeat more than 2000 times; space it wider or draw it shorter".into());
                    }
                }
            }
            c.named("type", "detail-group", "detail group", "detail_groups", true)?;
        }
        "spot" => {
            c.drawn_in(false)?;
            c.pt(e.get("at"), "x", "y")?;
            c.element_ref("host")?;
        }
        "view3d" => view3d(&c)?,
        "planview" => {
            c.level()?;
            view_range(&c)?;
            c.pts(e.get("crop"), "crop x", "crop y")?;
            c.graphics()?;
            if let Some(t) = e.get("parent").and_then(|v| target(ix, v)) {
                match t.id {
                    Some(n) if matches!(ix.cat(n), "level" | "planview") => c.note(&t),
                    _ => {
                        return c.err(format!(
                            "a dependent view hangs from a plan of its own level that is no dependent itself, not {}",
                            t.shown
                        ))
                    }
                }
            }
        }
        "link" => link(&c)?,
        "pointcloud" => {
            c.level()?;
            c.pt(e.get("at"), "at x", "at y")?;
            c.num("offset", "offset")?;
            c.num("angle", "angle")?;
        }
        "cadimport" => {
            if let Some(v) = e.get("cad") {
                if lib_name(c.pr, "cad", v).is_none() {
                    return c.err(format!("the project holds no CAD drawing named `{}`", shown(v)));
                }
            }
            c.level()?;
            c.pt(e.get("at"), "at x", "at y")?;
            c.num("angle", "angle")?;
            if let Some(o) = point2(e.get("origin")) {
                if !(o.0.abs() <= 1e12 && o.1.abs() <= 1e12) {
                    return c.err(format!("origin P2({:?}, {:?}) is past what a drawing holds", o.0, o.1));
                }
            }
            if let Some(s) = c.f("scale") {
                if !(0.000001..=10_000_000.0).contains(&s) {
                    return c.err(format!(
                        "a scale of {} mm to the drawing's unit isn't one; give one from 0.000001 to 10000000",
                        s
                    ));
                }
            }
            if let Some(t) = e.get("view").and_then(|v| target(ix, v)) {
                match t.id {
                    Some(n) if matches!(ix.cat(n), "level" | "planview") => c.note(&t),
                    _ => {
                        return c.err(format!(
                            "view {} isn't a plan of its level; an import shows in one of its level's plans",
                            t.shown
                        ))
                    }
                }
            }
        }
        _ => {}
    }
    Ok(c.by_id)
}

/// A note's, a detail line's or a filled region's own rules (an element's, or a detail group's
/// member's): what it holds, then what it's drawn with.
fn drafting(c: &El) -> R<()> {
    let e = c.e;
    match c.cat {
        "text" => {
            c.pt(e.get("at"), "x", "y")?;
            let text = e.get("text").and_then(|t| t.as_str()).unwrap_or("");
            if text.trim().is_empty() {
                return c.err("a text note needs text".into());
            }
            let chars = text.chars().count();
            if chars > 4000 {
                return c.err(format!("its text is {} characters long; a note holds up to 4000", chars));
            }
            c.named("type", "text-type", "text type", "text_types", true)?;
            if let Some(Value::Arr(runs)) = e.get("runs") {
                let mut before: Option<u64> = None;
                for (i, run) in runs.iter().enumerate() {
                    let at = |k: &str| run.get(k).and_then(|x| x.as_u64()).unwrap_or(0);
                    let (from, to) = (at("from"), at("to"));
                    if from >= to || to > chars as u64 {
                        return c.err(format!("run {} is of characters {} to {}; it needs some of the text's {}", i, from, to, chars));
                    }
                    if let Some(b) = before {
                        if from < b {
                            return c.err(format!("run {} starts at {}, inside the run before it; give them in order, apart", i, from));
                        }
                    }
                    let set = ["bold", "italic", "underline"].iter().any(|k| run.get(k).map(|v| !v.is_null()).unwrap_or(false));
                    if !set {
                        return c.err(format!("run {} overrides nothing; give it `bold`, `italic` or `underline`", i));
                    }
                    before = Some(to);
                }
            }
            c.num("angle", "angle")?;
            c.pt(e.get("leader"), "leader x", "leader y")?;
        }
        "line" => {
            line_geometry(c)?;
            c.named("style", "line-style", "line style", "line_styles", true)?;
        }
        "region" => {
            c.pt(e.get("pattern_origin"), "pattern origin x", "pattern origin y")?;
            c.num("pattern_angle", "pattern angle")?;
            c.sketch()?;
            c.named("type", "filled-region-type", "filled region type", "region_types", true)?;
            c.named("line_style", "line-style", "line style", "line_styles", false)?;
            if let Some(Value::Arr(ls)) = e.get("sketch") {
                for (i, l) in ls.iter().enumerate() {
                    if let Some(s) = l.get("style").filter(|v| !v.is_null()) {
                        if lib_name(c.pr, "line-style", s).is_none() {
                            return c.err(format!("boundary line {} is drawn in `{}`, and there's no such line style", i, shown(s)));
                        }
                    }
                }
            }
        }
        _ => {}
    }
    Ok(())
}

/// The detail groups, checked (as the original checks them) after the materials: each holds 1 to
/// 10000 members, each a detail line, a filled region or a note, each by its own rules.
pub fn detail_groups(pr: &Project) -> R<()> {
    let ix = Index::new(pr);
    let groups = match pr.section("detail_groups") {
        Some(g) => g,
        None => return Ok(()),
    };
    for (name, g) in groups.iter() {
        let members: &[Value] = match g.get("members") {
            Some(Value::Arr(m)) => m,
            _ => &[],
        };
        if members.is_empty() || members.len() > 10_000 {
            return Err(format!("detail group `{}`: it holds {} members; it holds 1 to 10000", name, members.len()));
        }
        for (i, m) in members.iter().enumerate() {
            let e = match m.get("element") {
                Some(e) => e,
                None => continue,
            };
            let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("");
            let who = format!("detail group `{}` member {}", name, i);
            if !matches!(cat, "line" | "region" | "text") {
                return Err(format!("{}: a {} can't be in a detail group; it holds detail lines, filled regions and text", who, cat));
            }
            let c = El { name: who, ix: &ix, pr, cat, e, by_id: None };
            drafting(&c)?;
        }
    }
    Ok(())
}

/// A floor's or a roof's shape: its points (where, and how high) and its split lines.
fn shape(c: &El) -> R<()> {
    let sh = match c.e.get("shape") {
        Some(sh) => sh,
        None => return Ok(()),
    };
    if let Some(Value::Arr(ps)) = sh.get("points") {
        for p in ps {
            c.pt(p.get("at"), "shape point x", "shape point y")?;
            if let Some(z) = p.get("z").and_then(|z| z.as_f64()) {
                if !(z.is_finite() && z.abs() <= MAX) {
                    let (x, y) = point2(p.get("at")).unwrap_or((0.0, 0.0));
                    return c.err(format!("the shape point at ({}, {}) has a height `z` of {}: it must be a number in mm", x, y, z));
                }
            }
        }
    }
    if let Some(Value::Arr(ls)) = sh.get("lines") {
        for l in ls {
            c.pt(l.get("a"), "split line x", "split line y")?;
            c.pt(l.get("b"), "split line x", "split line y")?;
        }
    }
    Ok(())
}

/// A level's or a plan's view range: each of its heights a usable number.
fn view_range(c: &El) -> R<()> {
    if let Some(vr) = c.e.get("view_range") {
        for k in ["top", "cut", "bottom", "depth"] {
            if let Some(x) = vr.get(k).and_then(|v| v.as_f64()) {
                c.bad(&format!("view range {}", k), x)?;
            }
        }
    }
    Ok(())
}

/// A wall's attachments: each to a roof or a floor.
fn attach(c: &mut El) -> R<()> {
    for key in ["attach_top", "attach_base"] {
        if let Some(t) = c.e.get(key).and_then(|v| target(c.ix, v)) {
            match t.id {
                Some(n) if matches!(c.ix.cat(n), "roof" | "floor") => c.note(&t),
                _ => return c.err(format!("{} {} isn't a roof or a floor", key, t.shown)),
            }
        }
    }
    Ok(())
}

/// A dimension's segments: their texts and their locks, each once, each a segment, at a length.
fn segments(c: &El) -> R<()> {
    let seg = |v: &Value| v.get("segment").and_then(|s| s.as_u64()).unwrap_or(0);
    if let Some(Value::Arr(ts)) = c.e.get("texts") {
        let mut seen = Vec::new();
        for t in ts {
            let s = seg(t);
            if s >= 10_000 || seen.contains(&s) {
                return c.err(format!("segment {}'s text is given twice, or there's no such segment", s));
            }
            seen.push(s);
        }
    }
    if let Some(Value::Arr(ls)) = c.e.get("locked") {
        let mut seen = Vec::new();
        for l in ls {
            let s = seg(l);
            let len = l.get("length").and_then(|x| x.as_f64()).unwrap_or(0.0);
            if s >= 10_000 || seen.contains(&s) || !(len.is_finite() && len.abs() <= MAX) {
                return c.err(format!("segment {} is locked twice, at no length, or isn't a segment", s));
            }
            seen.push(s);
        }
    }
    Ok(())
}

/// The level an element stands on: its own, or its host's (a door's, a window's).
fn level_of(pr: &Project, id: u64) -> Option<Value> {
    let e = pr.elements.get(&id)?;
    if let Some(l) = e.get("level").filter(|v| !v.is_null()) {
        return Some(l.clone());
    }
    let host = e.get("host").and_then(|h| h.as_str())?;
    let (_, h) = pr.elements.iter().find(|(_, x)| x.get("guid").and_then(|g| g.as_str()) == Some(host))?;
    h.get("level").filter(|v| !v.is_null()).cloned()
}

/// How the original names a library entry of a kind: `wall type`, `material`, `scan`…
pub fn kind_name(kind: &str) -> String {
    if let Some(c) = kind.strip_prefix("type:") {
        return format!("{} type", c);
    }
    match kind {
        "cloud" => "scan".into(),
        "cad" => "CAD drawing".into(),
        "option-set" => "design option set".into(),
        _ => kind.replace('-', " "),
    }
}

/// The library's ids: from 100000 up, and none an element's.
pub fn library_ids(pr: &Project) -> R<()> {
    let ix = Index::new(pr);
    for (id, e) in &pr.library {
        let kind = e.get("kind").and_then(|k| k.as_str()).unwrap_or("");
        let name = e.get("name").and_then(|k| k.as_str()).unwrap_or("");
        if *id < 100_000 {
            return Err(format!("{} `{}`: ids start at 100000", kind_name(kind), name));
        }
        if pr.elements.contains_key(id) {
            return Err(format!("{} `{}` and element {} have the same id", kind_name(kind), name, id));
        }
        if let Some(n) = e.get("guid").and_then(|g| g.as_str()).and_then(|g| ix.by_guid.get(g)) {
            return Err(format!("{} `{}` has the GUID of element {}", kind_name(kind), name, n));
        }
    }
    Ok(())
}
