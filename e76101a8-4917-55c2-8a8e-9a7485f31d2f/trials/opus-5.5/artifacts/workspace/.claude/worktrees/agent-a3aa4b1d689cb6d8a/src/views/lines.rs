//! Detail lines: `detail_line` (lines, polylines with arcs, circles, ellipses, splines, insulation,
//! clouds), the model's rules for them, and what `elements` shows of one.
//!
//! A line is saved as `{guid, category: "line", view, style, insulation?, centre_mark?, cloud?,
//! revision?, …its curve's fields}`: `view` the GUID of the view it is drawn in (a level's own
//! plan, a plan view, a section, an elevation or a sheet), `style` the GUID of its line style's
//! library entry.

use super::common::*;
use super::curves::{self, Curve};
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;

const CMD: &str = "detail_line";

/// The parameters `detail_line` takes, in the order its error lists them.
pub const PARAMS: &[&str] = &[
    "view", "level", "style", "insulation", "centre_mark", "cloud", "revision", "start", "end", "through", "arc",
    "points", "arcs", "closed", "centre", "radius", "radii", "angle", "span", "control", "knots", "fit", "start_tangent",
    "end_tangent",
];

/// The categories a detail line may be drawn in.
pub const LINE_VIEWS: &[&str] = &["level", "planview", "section", "elevation", "sheet"];

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "detail_line" => detail_line(&mut s.project, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

// ---------------------------------------------------------------- the line's own fields

/// What a detail line is beside its curve.
#[derive(Clone, Debug, Default)]
pub struct Props {
    /// The view's GUID.
    pub view: String,
    /// The line style's GUID (or a name the project hasn't, which the model's check refuses).
    pub style: String,
    pub insulation: Option<f64>,
    pub centre_mark: bool,
    pub cloud: Option<f64>,
    pub revision: Option<String>,
}

impl Props {
    /// The fields of an existing line.
    pub fn of(e: &Value) -> Props {
        Props {
            view: s_of(e, "view").unwrap_or("").to_string(),
            style: s_of(e, "style").unwrap_or("").to_string(),
            insulation: f_of(e, "insulation"),
            centre_mark: e.get("centre_mark").and_then(|x| x.as_bool()).unwrap_or(false),
            cloud: f_of(e, "cloud"),
            revision: s_of(e, "revision").map(|s| s.to_string()),
        }
    }
}

/// A detail line element as the original saves one.
pub fn line_element(guid: &str, props: &Props, curve: &Curve) -> Value {
    let mut m = Map::new();
    m.insert("guid", Value::s(guid));
    m.insert("category", Value::s("line"));
    m.insert("view", Value::s(&props.view));
    m.insert("style", Value::s(&props.style));
    if let Some(x) = props.insulation {
        m.insert("insulation", Value::f(x));
    }
    if props.centre_mark {
        m.insert("centre_mark", Value::Bool(true));
    }
    if let Some(x) = props.cloud {
        m.insert("cloud", Value::f(x));
    }
    if let Some(r) = &props.revision {
        m.insert("revision", Value::s(r));
    }
    curve.put_fields(&mut m);
    Value::Obj(m)
}

/// Adds a detail line to the project: its new id.
pub fn add_line(pr: &mut Project, props: &Props, curve: &Curve) -> u64 {
    let id = pr.alloc_id();
    let g = crate::rand::guid();
    pr.elements.insert(id, line_element(&g, props, curve));
    id
}

/// The curve of a detail line (None if it isn't one or holds none).
pub fn curve_of(pr: &Project, id: u64) -> Option<Curve> {
    let e = pr.el(id)?;
    if cat(e) != "line" {
        return None;
    }
    curves::parse(e).ok()
}

/// Puts a new curve in a detail line, its other fields as they were.
pub fn set_curve(pr: &mut Project, id: u64, curve: &Curve) {
    if let Some(e) = pr.el_mut(id) {
        curve.set_in(e);
    }
}

// ---------------------------------------------------------------- styles

const THIN: [&str; 9] = [
    "Thin Lines",
    "Linhas finas",
    "Líneas finas",
    "Tunna linjer",
    "Tenké čáry",
    "Lignes fines",
    "Dunne lijnen",
    "Dünne Linien",
    "Linee sottili",
];

/// The project's line styles by name, sorted.
pub fn style_names(pr: &Project) -> Vec<String> {
    let mut v: Vec<String> = pr.section("line_styles").map(|m| m.keys().cloned().collect()).unwrap_or_default();
    v.sort();
    v
}

/// The style a line is drawn in unless told: Thin Lines in the project's language (or in
/// English), else the first thin solid black one, else the first.
pub fn default_style(pr: &Project) -> Option<String> {
    let names = style_names(pr);
    if names.is_empty() {
        return None;
    }
    let own = word(pr, THIN);
    for n in [own, "Thin Lines"] {
        if names.iter().any(|x| x == n) {
            return Some(n.to_string());
        }
    }
    let sec = pr.section("line_styles");
    for n in &names {
        if let Some(st) = sec.and_then(|s| s.get(n)) {
            let pen = st.get("pen").and_then(|x| x.as_u64()).unwrap_or(1);
            let black = crate::styles::common::color_in(st.get("color")) == [0, 0, 0];
            if pen == 1 && black && st.get("pattern").map(|p| p.is_null()).unwrap_or(true) {
                return Some(n.clone());
            }
        }
    }
    Some(names[0].clone())
}

/// The name of the style a line names (its GUID's entry, or the name itself).
pub fn style_name(pr: &Project, s: &str) -> String {
    if let Some(n) = pr
        .library
        .values()
        .find(|e| e.get("kind").and_then(|k| k.as_str()) == Some("line-style") && e.get("guid").and_then(|g| g.as_str()) == Some(s))
        .and_then(|e| e.get("name"))
        .and_then(|n| n.as_str())
    {
        return n.to_string();
    }
    s.to_string()
}

/// What a line's `style` holds for a style named so: its entry's GUID, or the name (refused by
/// the check) where the project has no such style.
pub fn style_ref(pr: &Project, name: &str) -> String {
    let n = crate::styles::electrical::resolve(pr, "line-style", name);
    if style_names(pr).iter().any(|x| *x == n) {
        if let Some(g) = pr.lib_guid("line-style", &n) {
            return g;
        }
    }
    n
}

// ---------------------------------------------------------------- parameters

/// The parameters as the original reads them: a string that is the GUID of a library entry (a line
/// style, a material…) stands for the entry's name, at any depth.
pub fn with_names(pr: &Project, p: &Value) -> Value {
    match p {
        Value::Str(s) => {
            if let Some(g) = crate::styles::electrical::as_guid(s) {
                if let Some(e) = pr.library.values().find(|e| e.get("guid").and_then(|x| x.as_str()) == Some(g.as_str())) {
                    if let Some(n) = e.get("name").and_then(|n| n.as_str()) {
                        return Value::s(n);
                    }
                }
            }
            p.clone()
        }
        Value::Arr(a) => Value::Arr(a.iter().map(|x| with_names(pr, x)).collect()),
        Value::Obj(m) => {
            let mut o = Map::new();
            for (k, v) in &m.items {
                o.items.push((k.clone(), with_names(pr, v)));
            }
            Value::Obj(o)
        }
        _ => p.clone(),
    }
}

/// Whether a GUID is a part's that an element or a section of the file holds (a wall type's
/// layer, a region's sketch line…): something with an id, not an element.
pub fn part_guid(pr: &Project, g: &str) -> bool {
    fn scan(v: &Value, g: &str) -> bool {
        match v {
            Value::Obj(m) => {
                if m.get("guid").and_then(|x| x.as_str()) == Some(g) && m.get("id").is_some() {
                    return true;
                }
                m.items.iter().any(|(_, x)| scan(x, g))
            }
            Value::Arr(a) => a.iter().any(|x| scan(x, g)),
            _ => false,
        }
    }
    pr.doc.items.iter().any(|(k, v)| k != "elements" && k != "library" && scan(v, g)) || pr.elements.values().any(|e| scan(e, g))
}

// ---------------------------------------------------------------- views

/// A view by id, number, name or GUID, as `detail_line` reads one: any element given by id (what
/// it isn't is the model check's to say), else "`view`: X is not a view" or "no view named `X`".
pub fn view_arg(pr: &Project, cmd: &str, key: &str, v: &Value) -> R<u64> {
    let not = || format!("{}: `{}`: {} is not a view", cmd, key, v.to_compact());
    match v {
        Value::Num(_) => {
            let id = id_of(v).ok_or_else(not)?;
            if pr.elements.contains_key(&id) {
                Ok(id)
            } else {
                Err(not())
            }
        }
        Value::Str(s) => {
            if let Some(id) = find_view_named(pr, s) {
                return Ok(id);
            }
            if let Ok(id) = s.trim().parse::<u64>() {
                if pr.elements.contains_key(&id) {
                    return Ok(id);
                }
                return Err(not());
            }
            if let Some(g) = crate::model::normalize_guid(s) {
                if let Some(id) = pr.find_guid(&g) {
                    return Ok(id);
                }
                if part_guid(pr, &g) {
                    return Err(not());
                }
            }
            Err(format!("{}: no view named `{}`", cmd, s))
        }
        _ => Err(not()),
    }
}

/// A level or a plan view (itself, not its level), as `level` gives one.
pub fn plan_arg(pr: &Project, cmd: &str, key: &str, v: &Value) -> R<u64> {
    let not = || format!("{}: `{}`: {} is not a level or a plan view", cmd, key, v.to_compact());
    let is_plan = |id: u64| matches!(pr.category(id), Some("level") | Some("planview"));
    match v {
        Value::Num(_) => {
            let id = crate::model::find(pr, v).ok_or_else(not)?;
            if is_plan(id) {
                Ok(id)
            } else {
                Err(not())
            }
        }
        Value::Str(s) => {
            if let Some(id) = crate::model::find(pr, v) {
                return if is_plan(id) { Ok(id) } else { Err(not()) };
            }
            if s.trim().parse::<u64>().is_ok() {
                return Err(not());
            }
            if let Some(g) = crate::model::normalize_guid(s) {
                if part_guid(pr, &g) {
                    return Err(not());
                }
            }
            for id in crate::model::levels(pr) {
                if crate::model::name(pr, id) == *s {
                    return Ok(id);
                }
            }
            for id in pr.ids_of("planview") {
                if crate::model::name(pr, id) == *s {
                    return Ok(id);
                }
            }
            let names: Vec<String> = crate::model::levels(pr).iter().map(|l| crate::model::name(pr, *l)).collect();
            Err(format!("{}: no level or plan view named `{}` (the levels are: {})", cmd, s, names.join(", ")))
        }
        _ => Err(not()),
    }
}

/// The view a command draws in: `view`, else `level` (a level or a plan view), else the lowest
/// level's plan.
pub fn drawing_view(pr: &Project, cmd: &str, p: &Value) -> R<u64> {
    if let Some(v) = get(p, "view") {
        return view_arg(pr, cmd, "view", v);
    }
    if let Some(v) = get(p, "level") {
        return plan_arg(pr, cmd, "level", v);
    }
    default_plan(pr).ok_or_else(|| format!("{}: the project has no level", cmd))
}

/// The level a line's view shows (a plan's), if any.
pub fn line_level(pr: &Project, e: &Value) -> Option<u64> {
    let v = ref_id(pr, e, "view")?;
    match pr.category(v)? {
        "level" => Some(v),
        "planview" => crate::model::level_of_view(pr, v),
        _ => None,
    }
}

// ---------------------------------------------------------------- detail_line

fn detail_line(pr: &mut Project, p: &Value) -> R<Value> {
    let p = &with_names(pr, p);
    crate::styles::common::check_keys(p, CMD, PARAMS)?;
    let curve = curves::parse(p).map_err(|e| format!("{}: {}", CMD, e))?.rounded();
    curve.check().map_err(|e| format!("{}: the line: {}", CMD, e))?;
    let curve = curve.arcs_rounded();
    let insulation = crate::commands::params::opt_num(p, CMD, "insulation")?;
    let centre_mark = crate::commands::params::opt_bool(p, CMD, "centre_mark")?.unwrap_or(false);
    let cloud = crate::commands::params::opt_num(p, CMD, "cloud")?;
    let revision = crate::commands::params::opt_text(p, CMD, "revision")?;
    let view = drawing_view(pr, CMD, p)?;
    let style = match crate::styles::common::opt_name(p, CMD, "style")? {
        Some(n) => style_ref(pr, &n),
        None => {
            let n = default_style(pr).ok_or_else(|| format!("{}: the project has no line style; make one first", CMD))?;
            style_ref(pr, &n)
        }
    };
    let props = Props { view: guid(pr, view), style, insulation, centre_mark, cloud, revision };
    let id = add_line(pr, &props, &curve);
    Ok(jobj! {"id" => id})
}

// ---------------------------------------------------------------- the model's rules

/// The rules every detail line keeps: drawn in a plan, a section, an elevation or a sheet; its
/// curve sound; insulation or a cloud of a sensible size, not both; a line style the project has.
pub fn check(pr: &Project) -> R<()> {
    for (id, e) in &pr.elements {
        if cat(e) != "line" {
            continue;
        }
        check_line(pr, *id, e).map_err(|m| format!("line {}: {}", id, m))?;
    }
    Ok(())
}

/// What's wrong with a detail line, the first thing in the original's order.
pub fn check_line(pr: &Project, _id: u64, e: &Value) -> R<()> {
    if let Some(v) = ref_id(pr, e, "view") {
        let c = cat_of(pr, v);
        if !LINE_VIEWS.contains(&c.as_str()) {
            return Err(format!("{} {} isn't a plan, a section, an elevation or a sheet", c, v));
        }
    }
    if let Ok(c) = curves::parse(e) {
        c.check()?;
    }
    if let Some(w) = f_of(e, "insulation") {
        if !(w > 1.0 && w <= 10000.0) {
            return Err(format!("its insulation is {} mm wide; it's more than 1 mm and at most 10000", disp(w)));
        }
    }
    if let Some(a) = f_of(e, "cloud") {
        if !(a > 1.0 && a <= 10000.0) {
            return Err(format!("its cloud's arcs are {} mm long; they're more than 1 mm and at most 10000", disp(a)));
        }
    }
    if e.get("insulation").map(|x| !x.is_null()).unwrap_or(false) && e.get("cloud").map(|x| !x.is_null()).unwrap_or(false) {
        return Err("it is insulation or a revision cloud, not both".into());
    }
    if let Some(s) = s_of(e, "style") {
        let name = style_name(pr, s);
        if !style_names(pr).contains(&name) {
            return Err(format!("there's no line style `{}` (there are: {})", name, style_names(pr).join(", ")));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------- elements

/// What `elements` shows of a detail line beyond its fields: its length (to the hundredth), the
/// level of the plan it is in (null elsewhere), its shape and its style by name.
pub fn element_view(pr: &Project, id: u64, x: &mut Value) {
    let Some(e) = pr.el(id) else { return };
    if let Ok(c) = curves::parse(e) {
        x.set("length", Value::f(curves::r2(c.length())));
        x.set("shape", Value::s(c.shape()));
    }
    let lv = line_level(pr, e).map(|l| Value::s(&guid(pr, l))).unwrap_or(Value::Null);
    x.set("level", lv);
    if let Some(s) = s_of(e, "style") {
        x.set("style", Value::s(&style_name(pr, s)));
    }
}

// ---------------------------------------------------------------- reading a file

/// A detail line as the original keeps one it has read: its curve in its own terms (a polyline of
/// two points as `start` and `end`, `through` worked into an `arc`…), a style named by name
/// given its entry's GUID, the fields it doesn't know left out. None if it isn't a line it can read.
pub fn normalized(pr: &Project, e: &Value) -> Option<Value> {
    if cat(e) != "line" {
        return None;
    }
    let curve = curves::parse(e).ok()?;
    let mut props = Props::of(e);
    props.style = style_ref(pr, &style_name(pr, &props.style));
    Some(line_element(s_of(e, "guid").unwrap_or(""), &props, &curve))
}

/// Every detail line of a project read from a file put in the original's terms (for the reader to
/// call after loading).
pub fn normalize(pr: &mut Project) {
    let ids: Vec<u64> = pr.ids_of("line");
    for id in ids {
        if let Some(n) = pr.el(id).and_then(|e| normalized(pr, e)) {
            pr.elements.insert(id, n);
        }
    }
}
