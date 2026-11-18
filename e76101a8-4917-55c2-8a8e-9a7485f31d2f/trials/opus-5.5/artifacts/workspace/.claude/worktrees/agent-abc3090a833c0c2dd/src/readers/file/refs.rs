//! Where a project file names a thing of its library (a type, a material, a style, a phase…): by
//! its GUID, which the original reads as the thing's name (the file's library saying whose), and
//! writes back as the GUID its library gives that name once read; a name the library hasn't is
//! kept as it is, for the model's check to say so.
//!
//! `walk` visits every such place with the kind of library entry it names (and, for a family's
//! type or a set's option, whose: `Family: Type`, `Set: Option`).

use crate::json::{Map, Value};
use std::collections::BTreeMap;

/// What becomes of a name or a GUID found at a place of this kind.
pub trait Resolve {
    /// `whose`: the family or option set a type or an option is of (its name).
    fn map(&mut self, kind: &str, whose: Option<&str>, s: &str) -> String;
}

fn one(r: &mut dyn Resolve, kind: &str, whose: Option<&str>, v: &mut Value) {
    if let Value::Str(s) = v {
        let n = r.map(kind, whose, s);
        *s = n;
    }
}

fn field(r: &mut dyn Resolve, kind: &str, whose: Option<&str>, m: &mut Value, k: &str) {
    if let Some(v) = m.get_mut(k) {
        one(r, kind, whose, v);
    }
}

/// A map whose keys name things: renamed, and sorted as the original's map holds them.
fn keys(r: &mut dyn Resolve, kind: &str, m: &mut Value) {
    if let Value::Obj(mm) = m {
        let mut out = Map::new();
        for (k, v) in std::mem::take(&mut mm.items) {
            let nk = r.map(kind, None, &k);
            out.items.push((nk, v));
        }
        out.sort();
        // a key twice keeps the last
        let mut dedup = Map::new();
        for (k, v) in out.items {
            dedup.insert(&k, v);
        }
        *mm = dedup;
    }
}

fn str_of(v: Option<&Value>) -> Option<String> {
    v.and_then(|x| x.as_str()).map(|s| s.to_string())
}

// ---------------------------------------------------------------- views' graphics

fn style(r: &mut dyn Resolve, st: &mut Value) {
    for k in ["foreground", "background"] {
        if let Some(f) = st.get_mut(k) {
            field(r, "fill-pattern", None, f, "pattern");
        }
    }
}

fn overrides(r: &mut dyn Resolve, o: &mut Value) {
    for k in ["projection", "cut"] {
        if let Some(st) = o.get_mut(k) {
            style(r, st);
        }
    }
}

pub fn graphics(r: &mut dyn Resolve, g: &mut Value) {
    field(r, "view-template", None, g, "template");
    for k in ["categories", "elements"] {
        if let Some(Value::Obj(m)) = g.get_mut(k) {
            for (_, o) in m.items.iter_mut() {
                overrides(r, o);
            }
        }
    }
    if let Some(Value::Arr(a)) = g.get_mut("filters") {
        for f in a.iter_mut() {
            field(r, "view-filter", None, f, "filter");
            overrides(r, f);
        }
    }
    field(r, "phase", None, g, "phase");
    field(r, "phase-filter", None, g, "phase_filter");
    if let Some(opts) = g.get_mut("options") {
        // each set's option is of that set
        if let Value::Obj(m) = opts {
            let mut out = Map::new();
            for (k, mut v) in std::mem::take(&mut m.items) {
                let set_in = k.clone();
                let set_name = r.map("option-set", None, &k);
                // the option is named as of its set, by the set's name before it is renamed
                let whose = set_internal(&set_in, &set_name);
                one(r, "design-option", Some(&whose), &mut v);
                out.items.push((set_name, v));
            }
            out.sort();
            *m = out;
        }
    }
    if let Some(Value::Arr(a)) = g.get_mut("linework") {
        for l in a.iter_mut() {
            field(r, "line-style", None, l, "style");
        }
    }
    if let Some(l) = g.get_mut("layers") {
        keys(r, "cad", l);
    }
}

/// The name of a set, as it is (whichever way the walk is going: the name, not the GUID).
fn set_internal(before: &str, after: &str) -> String {
    if super::de::parse_guid(after).is_some() && super::de::parse_guid(before).is_none() {
        before.to_string()
    } else {
        after.to_string()
    }
}

// ---------------------------------------------------------------- elements

/// The parameters an element holds: project parameters by GUID, its phases, option, paint.
fn params(r: &mut dyn Resolve, p: &mut Value) {
    let m = match p {
        Value::Obj(m) => m,
        _ => return,
    };
    let mut out = Map::new();
    for (k, mut v) in std::mem::take(&mut m.items) {
        match k.as_str() {
            "Phase Created" | "Phase Demolished" => one(r, "phase", None, &mut v),
            "Design Option" => one(r, "design-option", None, &mut v),
            "Paint" => {
                if let Value::Obj(pm) = &mut v {
                    for (_, x) in pm.items.iter_mut() {
                        one(r, "material", None, x);
                    }
                }
            }
            "Mass Face" | "Mass Floor" => {}
            _ => {}
        }
        let nk = match k.as_str() {
            "Phase Created" | "Phase Demolished" | "Design Option" | "Paint" | "Mass Face" | "Mass Floor" => k,
            _ => r.map("parameter", None, &k),
        };
        out.items.push((nk, v));
    }
    out.sort();
    let mut dedup = Map::new();
    for (k, v) in out.items {
        dedup.insert(&k, v);
    }
    *m = dedup;
}

fn type_kind(cat: &str) -> Option<String> {
    Some(match cat {
        "wall" | "floor" | "ceiling" | "roof" | "column" | "structuralcolumn" | "footing" | "railing" | "beam"
        | "stripfooting" | "pipe" | "duct" | "conduit" | "cabletray" | "wire" | "downconductor" | "groundconductor"
        | "cable" => format!("type:{}", cat),
        _ => return None,
    })
}

/// The schedule's and view filters' fields that are project parameters.
fn param_field(r: &mut dyn Resolve, v: &mut Value, k: &str) {
    field(r, "parameter", None, v, k);
}

/// One element's names of the library.
pub fn element(r: &mut dyn Resolve, e: &mut Value) {
    let cat = str_of(e.get("category")).unwrap_or_default();
    if let Some(k) = type_kind(&cat) {
        field(r, &k, None, e, "type");
    }
    match cat.as_str() {
        "door" | "window" | "component" => {
            let fam_in = str_of(e.get("family"));
            field(r, "family", None, e, "family");
            let fam_now = str_of(e.get("family"));
            match (fam_in, fam_now) {
                (Some(a), Some(b)) => {
                    let whose = set_internal(&a, &b);
                    field(r, "family-type", Some(&whose), e, "type");
                }
                _ => {
                    let k = if cat == "door" { "type:door" } else { "type:window" };
                    if cat != "component" {
                        field(r, k, None, e, "type");
                    }
                }
            }
        }
        "text" => field(r, "text-type", None, e, "type"),
        "dimension" | "dimension3d" => field(r, "dimension-type", None, e, "type"),
        "line" => field(r, "line-style", None, e, "style"),
        "region" => {
            field(r, "filled-region-type", None, e, "type");
            field(r, "line-style", None, e, "line_style");
            // a region's boundary lines may each have a style of their own
            if let Some(Value::Arr(a)) = e.get_mut("sketch") {
                for l in a.iter_mut() {
                    field(r, "line-style", None, l, "style");
                }
            }
        }
        "detailgroup" | "repeatingdetail" => field(r, "detail-group", None, e, "type"),
        "cadimport" => field(r, "cad", None, e, "cad"),
        "pointcloud" => field(r, "cloud", None, e, "cloud"),
        "schedule" => {
            for (k, f) in [("fields", "name"), ("filters", "field"), ("sort", "field")] {
                if let Some(Value::Arr(a)) = e.get_mut(k) {
                    for x in a.iter_mut() {
                        param_field(r, x, f);
                    }
                }
            }
        }
        _ => {}
    }
    if let Some(g) = e.get_mut("graphics") {
        graphics(r, g);
    }
    if let Some(p) = e.get_mut("params") {
        params(r, p);
    }
}

// ---------------------------------------------------------------- the sections

fn layers(r: &mut dyn Resolve, t: &mut Value) {
    if let Some(Value::Arr(a)) = t.get_mut("layers") {
        for l in a.iter_mut() {
            field(r, "material", None, l, "material");
        }
    }
}

/// A family: its material parameters' values and its forms' materials name materials.
fn family(r: &mut dyn Resolve, f: &mut Value) {
    let mut material_params: Vec<String> = Vec::new();
    if let Some(Value::Arr(ps)) = f.get_mut("parameters") {
        for p in ps.iter_mut() {
            if p.get("kind").and_then(|k| k.as_str()) == Some("material") {
                if let Some(n) = str_of(p.get("name")) {
                    material_params.push(n);
                }
                field(r, "material", None, p, "value");
            }
        }
    }
    if let Some(Value::Obj(ts)) = f.get_mut("types") {
        for (_, t) in ts.items.iter_mut() {
            if let Value::Obj(tm) = t {
                for (k, v) in tm.items.iter_mut() {
                    if material_params.contains(k) {
                        one(r, "material", None, v);
                    }
                }
            }
        }
    }
    if let Some(Value::Arr(fs)) = f.get_mut("forms") {
        for form in fs.iter_mut() {
            let m = str_of(form.get("material"));
            if let Some(m) = m {
                // a form's material is a material parameter's name, or a material's
                if !m.is_empty() && !material_params.contains(&m) {
                    field(r, "material", None, form, "material");
                }
            }
        }
    }
}

/// Every place in the model's sections and its elements that names a thing of the library.
pub fn walk(r: &mut dyn Resolve, doc: &mut Map, elements: &mut BTreeMap<u64, Value>) {
    if let Some(Value::Obj(types)) = doc.get_mut("types") {
        for (k, sec) in types.items.iter_mut() {
            if k == "runs" {
                if let Value::Obj(cats) = sec {
                    for (_, m) in cats.items.iter_mut() {
                        if let Value::Obj(ts) = m {
                            for (_, t) in ts.items.iter_mut() {
                                field(r, "material", None, t, "material");
                            }
                        }
                    }
                }
            } else if let Value::Obj(ts) = sec {
                for (_, t) in ts.items.iter_mut() {
                    layers(r, t);
                }
            }
        }
    }
    if let Some(Value::Obj(ms)) = doc.get_mut("materials") {
        for (_, m) in ms.items.iter_mut() {
            field(r, "fill-pattern", None, m, "cut_pattern");
            field(r, "fill-pattern", None, m, "surface_pattern");
            if let Some(t) = m.get_mut("texture") {
                field(r, "picture", None, t, "image");
            }
        }
    }
    if let Some(Value::Obj(fs)) = doc.get_mut("families") {
        for (_, f) in fs.items.iter_mut() {
            family(r, f);
        }
    }
    if let Some(Value::Obj(vf)) = doc.get_mut("view_filters") {
        for (_, f) in vf.items.iter_mut() {
            if let Some(Value::Arr(a)) = f.get_mut("rules") {
                for x in a.iter_mut() {
                    param_field(r, x, "field");
                }
            }
        }
    }
    if let Some(Value::Obj(vt)) = doc.get_mut("view_templates") {
        for (_, t) in vt.items.iter_mut() {
            if let Some(g) = t.get_mut("graphics") {
                graphics(r, g);
            }
        }
    }
    if let Some(Value::Obj(po)) = doc.get_mut("phase_overrides") {
        for (_, o) in po.items.iter_mut() {
            overrides(r, o);
        }
    }
    if let Some(Value::Obj(os)) = doc.get_mut("option_sets") {
        for (k, s) in os.items.iter_mut() {
            let set = k.clone();
            field(r, "design-option", Some(&set), s, "primary");
        }
    }
    if let Some(Value::Obj(ls)) = doc.get_mut("line_styles") {
        for (_, s) in ls.items.iter_mut() {
            field(r, "line-pattern", None, s, "pattern");
        }
    }
    if let Some(Value::Obj(rt)) = doc.get_mut("region_types") {
        for (_, t) in rt.items.iter_mut() {
            field(r, "fill-pattern", None, t, "foreground");
            field(r, "fill-pattern", None, t, "background");
        }
    }
    if let Some(Value::Obj(dg)) = doc.get_mut("detail_groups") {
        for (_, g) in dg.items.iter_mut() {
            if let Some(Value::Arr(ms)) = g.get_mut("members") {
                for m in ms.iter_mut() {
                    if let Some(e) = m.get_mut("element") {
                        element(r, e);
                    }
                }
            }
        }
    }
    if let Some(Value::Obj(ds)) = doc.get_mut("distribution_systems") {
        for (_, s) in ds.items.iter_mut() {
            for k in ["l_l", "l_n", "l_g"] {
                field(r, "voltage", None, s, k);
            }
        }
    }
    for (_, e) in elements.iter_mut() {
        element(r, e);
    }
}

// ---------------------------------------------------------------- the two ways

/// The library as a lookup: by kind and GUID, by kind and name.
pub struct Lib {
    by_guid: std::collections::HashMap<(String, String), String>,
    by_name: std::collections::HashMap<(String, String), String>,
}

impl Lib {
    pub fn new(library: &BTreeMap<u64, Value>) -> Lib {
        let mut by_guid = std::collections::HashMap::new();
        let mut by_name = std::collections::HashMap::new();
        for (_, e) in library {
            let kind = str_of(e.get("kind")).unwrap_or_default();
            let name = str_of(e.get("name")).unwrap_or_default();
            let guid = str_of(e.get("guid")).unwrap_or_default();
            by_guid.entry((kind.clone(), guid.clone())).or_insert(name.clone());
            by_name.entry((kind, name)).or_insert(guid);
        }
        Lib { by_guid, by_name }
    }
}

fn full(whose: Option<&str>, s: &str) -> String {
    match whose {
        Some(w) => format!("{}: {}", w, s),
        None => s.to_string(),
    }
}

/// A GUID read as the name its library gives it (of a family's type, or a set's option, the part
/// after `Whose: `); anything else as it is.
pub struct ToNames<'a>(pub &'a Lib);

impl Resolve for ToNames<'_> {
    fn map(&mut self, kind: &str, whose: Option<&str>, s: &str) -> String {
        if let Some(g) = super::de::parse_guid(s) {
            if let Some(n) = self.0.by_guid.get(&(kind.to_string(), g)) {
                if let Some(w) = whose {
                    if let Some(rest) = n.strip_prefix(&format!("{}: ", w)) {
                        return rest.to_string();
                    }
                }
                return n.clone();
            }
        }
        s.to_string()
    }
}

/// A name written as its GUID in the library; anything else as it is.
pub struct ToGuids<'a>(pub &'a Lib);

impl Resolve for ToGuids<'_> {
    fn map(&mut self, kind: &str, whose: Option<&str>, s: &str) -> String {
        if let Some(g) = self.0.by_name.get(&(kind.to_string(), full(whose, s))) {
            return g.clone();
        }
        s.to_string()
    }
}
