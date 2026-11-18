//! View templates: `template`.
//!
//! The file keeps `view_templates` (name: {kind?, controls, graphics?, view_range?}, sorted by
//! name, the section gone with its last template) and a `view-template` library entry for each.
//! A view follows one by GUID (`graphics.template`); what the template controls (`vg::GROUPS`)
//! the view takes from it and can't change for itself.

#![allow(unused_imports)]

use super::common::*;
use super::filters::name_param;
use super::graphics::edit;
use super::graphics::ovr::sorted_items;
use super::graphics::vg::{self, gmap, gput, gstr};
use super::graphics::{self as gr, Target};
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "template" => cmd_template(s, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
    .map_err(gr::clip)
}

/// The view kinds a template is for.
const KINDS: &[&str] = &["plan", "section", "3d"];

fn kind_of_view(c: &str) -> Option<&'static str> {
    match c {
        "level" | "planview" => Some("plan"),
        "section" | "elevation" => Some("section"),
        "view3d" => Some("3d"),
        _ => None,
    }
}

fn template_names(pr: &Project) -> Vec<String> {
    let mut v: Vec<String> = vg::templates(pr).keys().cloned().collect();
    v.sort();
    v
}

fn set_templates(pr: &mut Project, m: Map) {
    if m.is_empty() {
        pr.remove_top("view_templates");
    } else {
        pr.insert_top("view_templates", Value::Obj(m));
    }
}

/// A template object put together in the file's order.
fn assemble(kind: &Option<String>, controls: &[String], g: &Map, range: &Option<Value>) -> Value {
    let mut m = Map::new();
    if let Some(k) = kind {
        m.insert("kind", Value::s(k));
    }
    m.insert("controls", Value::from(controls.to_vec()));
    if !g.is_empty() {
        m.insert("graphics", Value::Obj(g.clone()));
    }
    if let Some(r) = range {
        m.insert("view_range", r.clone());
    }
    Value::Obj(m)
}

// ---------------------------------------------------------------- view ranges

/// A plan's view range as a file holds it (its defaults where it says nothing).
fn range_parts(v: Option<&Value>) -> (Option<f64>, f64, f64, f64) {
    let g = |k: &str, d: f64| v.and_then(|r| r.get(k)).and_then(|x| x.as_f64()).unwrap_or(d);
    let top = v.and_then(|r| r.get("top")).and_then(|x| x.as_f64());
    (top, g("cut", 1200.0), g("bottom", 0.0), g("depth", 0.0))
}

fn range_value(top: Option<f64>, cut: f64, bottom: f64, depth: f64) -> Value {
    jobj! {"top" => top.map(Value::f).unwrap_or(Value::Null), "cut" => Value::f(cut), "bottom" => Value::f(bottom), "depth" => Value::f(depth)}
}

/// `view_range` merged into a template's range.
fn range_patch(cmd: &str, cur: Option<&Value>, v: &Value) -> R<Value> {
    let m = match v {
        Value::Obj(m) => m,
        _ => return Err(format!("{}: `view_range` is {{top?, cut?, bottom?, depth?}} in mm, not {}", cmd, v.to_compact())),
    };
    let (mut top, mut cut, mut bottom, mut depth) = range_parts(cur);
    for (k, x) in sorted_items(m) {
        let num = |x: &Value| crate::styles::common::f64_of(x).map_err(|e| format!("{}: `view_range`: {}", cmd, e));
        match k.as_str() {
            "top" => {
                top = if x.is_null() { None } else { Some(num(&x)?) };
            }
            "cut" | "bottom" | "depth" => {
                if x.is_null() {
                    continue;
                }
                let n = num(&x)?;
                match k.as_str() {
                    "cut" => cut = n,
                    "bottom" => bottom = n,
                    _ => depth = n,
                }
            }
            _ => {
                return Err(format!(
                    "{}: `view_range`: unknown field `{}`, expected one of `top`, `cut`, `bottom`, `depth`",
                    cmd, k
                ))
            }
        }
    }
    Ok(range_value(top, cut, bottom, depth))
}

/// A template's range is one a plan can have: usable numbers, top ≥ cut ≥ bottom ≥ depth.
fn check_range(r: &Value) -> R<()> {
    let (top, cut, bottom, depth) = range_parts(Some(r));
    let usable = |x: f64| x.is_finite() && x.abs() <= 1e9;
    for (k, x) in [("top", top), ("cut", Some(cut)), ("bottom", Some(bottom)), ("depth", Some(depth))] {
        if let Some(x) = x {
            if !usable(x) {
                return Err(format!("its view range {}: {} is not a usable number", k, x));
            }
        }
    }
    let ok = top.map(|t| t >= cut).unwrap_or(true) && cut >= bottom && bottom >= depth;
    if !ok {
        let t = match top {
            Some(t) => format!("top {}", t),
            None => "top at the level above".to_string(),
        };
        return Err(format!(
            "its: its plan's view range runs top ≥ cut plane ≥ bottom ≥ view depth, not {}, cut {}, bottom {}, depth {}",
            t, cut, bottom, depth
        ));
    }
    Ok(())
}

/// The view range in force of a plan (a level or a plan view): its own (a dependent's, its
/// parent's), or its template's where that controls the range.
pub fn view_range_of(pr: &Project, id: u64) -> Option<Value> {
    let src = vg::source_of(pr, id);
    let own = vg::own(pr, src);
    if let Some((_, t)) = vg::template_of(pr, &own) {
        if vg::controls_of(&t).iter().any(|c| c == "range") {
            if let Some(r) = t.get("view_range") {
                return Some(r.clone());
            }
        }
    }
    pr.el(src).and_then(|e| e.get("view_range")).cloned()
}

/// The groups a view's template controls (none where it follows none), and the template's name.
pub fn controlled(pr: &Project, id: u64) -> Option<(String, Vec<String>)> {
    let own = vg::own(pr, vg::source_of(pr, id));
    let (n, t) = vg::template_of(pr, &own)?;
    Some((n, vg::controls_of(&t)))
}

// ---------------------------------------------------------------- the command

fn parse_controls(cmd: &str, v: &Value) -> R<Vec<String>> {
    let pre = format!(
        "{}: `controls` is a list of what it controls: {}: ",
        cmd,
        vg::GROUPS.iter().map(|g| format!("\"{}\"", g)).collect::<Vec<_>>().join(", ")
    );
    let a = match v {
        Value::Arr(a) => a,
        _ => return Err(format!("{}invalid type: {}, expected a sequence", pre, v.kind_name())),
    };
    let mut given: Vec<String> = Vec::new();
    for x in a {
        match x {
            Value::Str(s) if vg::GROUPS.contains(&s.as_str()) => given.push(s.clone()),
            Value::Str(s) => {
                let list: Vec<String> = vg::GROUPS.iter().map(|g| format!("`{}`", g)).collect();
                return Err(format!("{}unknown variant `{}`, expected one of {}", pre, s, list.join(", ")));
            }
            _ => return Err(format!("{}invalid type: {}, expected string or map", pre, x.kind_name())),
        }
    }
    Ok(vg::GROUPS.iter().filter(|g| given.iter().any(|x| x == *g)).map(|g| g.to_string()).collect())
}

/// What a template takes from a view (`from`): its graphics in force but what is the view's own,
/// a plan's view range, and its kind.
fn from_view(pr: &Project, id: u64) -> (Map, Option<Value>, Option<String>) {
    let eff = vg::effective_of(pr, id);
    let mut g = Map::new();
    for k in ["categories", "filters", "phase", "phase_filter", "options", "scale", "detail", "style", "background_grid"] {
        gput(&mut g, k, eff.get(k).cloned());
    }
    let c = cat_of(pr, id);
    let range = if matches!(c.as_str(), "level" | "planview") { view_range_of(pr, id) } else { None };
    (g, range, kind_of_view(&c).map(|k| k.to_string()))
}

/// The keys that make a template where there is none (`layers` doesn't).
const MAKES: &[&str] = &[
    "like",
    "kind",
    "from",
    "controls",
    "view_range",
    "reset",
    "scale",
    "detail",
    "visual_style",
    "background_grid",
    "hide",
    "show",
    "categories",
    "filters",
    "phase",
    "phase_filter",
    "options",
    "elements",
    "hide_elements",
    "show_elements",
    "template",
];

fn cmd_template(s: &mut Session, p: &Value) -> R<Value> {
    let cmd = "template";
    let name = name_param(p, cmd, "name")?.ok_or_else(|| format!("{}: `name` is required", cmd))?;
    let delete = crate::commands::params::opt_bool(p, cmd, "delete")?.unwrap_or(false);
    let pr = &mut s.project;
    let name = vg::entry_name(pr, "view-template", &name);
    let all = vg::templates(pr);
    if delete {
        if !all.contains(&name) {
            return Err(format!("{}: there's no view template `{}`", cmd, name));
        }
        delete_template(pr, &name);
        return Ok(jobj! {"deleted" => true, "name" => name});
    }
    // `like` starts a new template; one that is there already keeps its own
    let like = match name_param(p, cmd, "like")? {
        None => None,
        Some(_) if all.contains(&name) => None,
        Some(l) => match all.get(&vg::entry_name(pr, "view-template", &l)) {
            Some(t) => Some(t.clone()),
            None => {
                return Err(format!(
                    "{}: there's no view template `{}` to start from{}",
                    cmd,
                    l,
                    edit::there_are(&template_names(pr))
                ))
            }
        },
    };
    let kind_given: Option<Option<String>> = match p.get("kind") {
        None => None,
        Some(Value::Null) => Some(None),
        Some(Value::Str(k)) if KINDS.contains(&k.as_str()) => Some(Some(k.clone())),
        Some(v) => return Err(format!("{}: `kind` is plan, section or 3d, or null for any, not {}", cmd, v.to_compact())),
    };
    let from = match get(p, "from") {
        None => None,
        Some(v) => match gr::lookup_view(pr, cmd, v)? {
            Target::Id(id) => {
                if !gr::takes_graphics(&cat_of(pr, id)) {
                    return Err(format!(
                        "{}: {} isn't a plan, a section, an elevation or a 3D view; templates are made from those",
                        cmd,
                        gr::label(pr, id)
                    ));
                }
                Some(id)
            }
            Target::Missing3d => {
                return Err(format!("{}: no view named `{}`", cmd, v.as_str().unwrap_or(DEFAULT_3D)));
            }
        },
    };
    let controls_given = match get(p, "controls") {
        None => None,
        Some(v) => Some(parse_controls(cmd, v)?),
    };
    let existing = all.get(&name).cloned();
    let range_given = match get(p, "view_range") {
        None => None,
        Some(v) => Some(v.clone()),
    };
    if let Some(v) = &range_given {
        if !matches!(v, Value::Obj(_)) {
            return Err(format!("{}: `view_range` is {{top?, cut?, bottom?, depth?}} in mm, not {}", cmd, v.to_compact()));
        }
        // field types are read now; the range is merged once the template is known
        range_patch(cmd, None, v)?;
    }
    if existing.is_none() {
        let makes = MAKES.iter().any(|k| match *k {
            "template" => p.get(k).map(|v| !v.is_null()).unwrap_or(false),
            _ => get(p, k).is_some(),
        });
        if !makes {
            return Err(format!(
                "{}: there's no view template `{}`; make one with `from` (a view), or `controls`{}",
                cmd,
                name,
                edit::there_are(&template_names(pr))
            ));
        }
    }
    for k in ["elements", "hide_elements", "show_elements", "layers", "template"] {
        let given = if k == "template" { p.get(k).is_some() } else { get(p, k).is_some() };
        if given {
            return Err(format!(
                "{}: `{}` is a view's own; a template holds categories, filters, a phase and design options",
                cmd, k
            ));
        }
    }
    let reset = crate::commands::params::opt_bool(p, cmd, "reset")?.unwrap_or(false);

    // the template as it stands, or as it starts
    let base = existing.clone().or_else(|| like.clone());
    let mut kind: Option<String> = base.as_ref().and_then(|t| gstr(t.as_obj().unwrap_or(&Map::new()), "kind"));
    let mut controls: Vec<String> = match &base {
        Some(t) => vg::controls_of(t),
        None => vg::GROUPS.iter().map(|g| g.to_string()).collect(),
    };
    let mut g: Map = base.as_ref().map(vg::template_graphics).unwrap_or_default();
    let mut range: Option<Value> = base.as_ref().and_then(|t| t.get("view_range").cloned());
    let old = existing.clone();
    if let Some(k) = kind_given {
        kind = k;
    }
    if let Some(id) = from {
        let (fg, fr, fk) = from_view(pr, id);
        g = fg;
        range = fr;
        kind = fk;
    }
    if let Some(c) = controls_given {
        controls = c;
    }
    if let Some(v) = &range_given {
        range = Some(range_patch(cmd, range.as_ref(), v)?);
    }
    if reset {
        g = Map::new();
    }
    edit::grid(cmd, p, &mut g)?;
    edit::hide(pr, cmd, p, &mut g)?;
    edit::show(pr, cmd, p, &mut g)?;
    edit::categories(pr, cmd, p, &mut g)?;
    let mut pend = edit::Pending::default();
    edit::filters(pr, cmd, p, &mut g, &mut pend)?;
    edit::phase(pr, cmd, p, &mut g)?;
    edit::options(pr, cmd, p, &mut g, &mut pend)?;
    if let Some(v) = p.get("scale") {
        let x = gr::scale_of(cmd, v)?;
        gput(&mut g, "scale", Some(Value::f(x)));
    }
    if let Some(v) = get(p, "detail") {
        let d = gr::detail_of(cmd, v)?;
        gput(&mut g, "detail", if d == "fine" { None } else { Some(Value::s(&d)) });
    }
    if let Some(v) = get(p, "visual_style") {
        let st = gr::style_of(cmd, "visual_style", v)?;
        gput(&mut g, "style", if st == "shaded" { None } else { Some(Value::s(&st)) });
    }
    edit::check_with(pr, &g, &pend).map_err(|e| format!("{}: {}", cmd, e))?;
    if let Some(r) = &range {
        if range_given.is_some() {
            check_range(r).map_err(|e| format!("{}: {}", cmd, e))?;
        }
    }
    let mut final_name = name.clone();
    if let Some(n) = name_param(p, cmd, "rename")? {
        if n != name {
            if all.contains(&n) {
                return Err(format!("{}: there's already a view template `{}`", cmd, n));
            }
            final_name = n;
        }
    }
    let t = assemble(&kind, &controls, &g, &range);
    let mut all = vg::templates(pr);
    if old.as_ref() != Some(&t) || final_name != name {
        if final_name != name {
            all.remove(&name);
        }
        all.insert_sorted(&final_name, t);
        set_templates(pr, all);
        if existing.is_some() && final_name != name {
            crate::styles::common::lib_rename(pr, "view-template", &name, &final_name);
        }
        crate::styles::common::lib_ensure(pr, "view-template", &final_name);
    }
    Ok(reply(pr, &final_name))
}

/// What `template` replies of a template: its settings, what it controls, the views following it.
pub fn reply(pr: &Project, name: &str) -> Value {
    let t = vg::templates(pr).get(name).cloned().unwrap_or_else(Value::obj);
    let g = vg::template_graphics(&t);
    let gd = pr.lib_guid("view-template", name);
    let views: Vec<u64> = pr
        .elements
        .iter()
        .filter(|(_, e)| {
            e.get("graphics").and_then(|g| g.get("template")).and_then(|x| x.as_str()) == gd.as_deref() && gd.is_some()
        })
        .map(|(id, _)| *id)
        .collect();
    let range = match t.get("view_range") {
        Some(r) => {
            let (top, cut, bottom, depth) = range_parts(Some(r));
            jobj! {"bottom" => Value::f(bottom), "cut" => Value::f(cut), "depth" => Value::f(depth), "top" => top.map(Value::f).unwrap_or(Value::Null)}
        }
        None => Value::Null,
    };
    jobj! {
        "background_grid" => vg::grid_reply(&g),
        "categories" => Value::Obj(vg::named_categories(pr, &g)),
        "controls" => vg::controls_of(&t),
        "detail" => gstr(&g, "detail").unwrap_or_else(|| "fine".into()),
        "filters" => vg::named_filters(pr, &g),
        "hidden" => vg::hidden_categories(&g),
        "kind" => t.get("kind").cloned().unwrap_or(Value::Null),
        "layers" => Value::obj(),
        "name" => name,
        "options" => Value::Obj(vg::named_options(pr, &g)),
        "phase" => vg::phase_name(pr, &g),
        "phase_filter" => vg::phase_filter_name(pr, &g),
        "scale" => g.get("scale").cloned().unwrap_or(Value::Null),
        "view_range" => range,
        "views" => views,
        "visual_style" => gstr(&g, "style").unwrap_or_else(|| "shaded".into()),
    }
}

/// Takes a template away: its entry, and the views following it keep their own settings.
pub fn delete_template(pr: &mut Project, name: &str) {
    let gd = pr.lib_guid("view-template", name);
    let mut all = vg::templates(pr);
    all.remove(name);
    set_templates(pr, all);
    crate::styles::common::lib_remove(pr, "view-template", name);
    let Some(gd) = gd else { return };
    let ids: Vec<u64> = pr.elements.keys().copied().collect();
    for id in ids {
        let mut g = vg::own(pr, id);
        if gstr(&g, "template").as_deref() == Some(gd.as_str()) {
            gput(&mut g, "template", None);
            vg::store_in(pr, id, g);
        }
    }
}

/// Whether a view follows the template of this name (`purge` keeps those).
pub fn used(pr: &Project, name: &str) -> bool {
    let Some(gd) = pr.lib_guid("view-template", name) else { return false };
    pr.elements
        .values()
        .any(|e| e.get("graphics").and_then(|g| g.get("template")).and_then(|x| x.as_str()) == Some(gd.as_str()))
}

/// The model rules of this part (checked with the graphics', in the model's order).
pub fn check(pr: &Project) -> R<()> {
    let _ = pr;
    Ok(())
}

/// What each template's graphics hold is the model's, and its range is a plan's.
pub fn check_all(pr: &Project) -> R<()> {
    for (k, t) in &vg::templates(pr).items {
        let g = vg::template_graphics(t);
        let pre = |e: String| format!("view template `{}`: {}", k, e);
        edit::check(pr, &g).map_err(pre)?;
        if let Some(r) = t.get("view_range") {
            check_range(r).map_err(pre)?;
        }
    }
    Ok(())
}

/// What `inspect` says of the sections this part keeps: the view templates, what they name by
/// GUID named.
pub fn inspect_entries(s: &Session, out: &mut Vec<(String, Value)>) {
    let pr = &s.project;
    let mut m = Map::new();
    for (k, t) in &vg::templates(pr).items {
        let mut e = Map::new();
        if let Some(kind) = t.get("kind") {
            e.insert("kind", kind.clone());
        }
        e.insert("controls", t.get("controls").cloned().unwrap_or_else(|| Value::Arr(vec![])));
        let g = vg::template_graphics(t);
        if !g.is_empty() {
            e.insert("graphics", vg::named(pr, &g));
        }
        if let Some(r) = t.get("view_range") {
            e.insert("view_range", r.clone());
        }
        m.insert(k, Value::Obj(e));
    }
    out.push(("view_templates".into(), Value::Obj(m)));
}
