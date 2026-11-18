//! A view's graphics: `graphics` (Visibility/Graphics), `scale`, `detail`, `visual_style`.
//!
//! A level, a plan view, a section, an elevation and a 3D view hold `graphics` (`vg::GKEYS`, in
//! that order): what they hide and override by category, by view filter and by element, their
//! phase, phase filter and design options, scale, detail level, visual style, background grid,
//! linework and the CAD layers they hide. A dependent plan view's are its parent's; a view that
//! follows a view template takes what the template controls from it.

#![allow(unused_imports)]

pub mod edit;
pub mod ovr;
pub mod vg;

use super::common::*;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;
use vg::{gput, gstr};

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "graphics" => cmd_graphics(s, p),
        "scale" => cmd_scale(s, p),
        "detail" => cmd_detail(s, p),
        "visual_style" => cmd_visual_style(s, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
    .map_err(clip)
}

/// The longest error the original gives whole; past it, the rest is counted.
const MAX_ERROR: usize = 2000;

/// A command's error past 2000 characters: its first 2000 and how many more there were.
pub fn clip(e: String) -> String {
    let n = e.chars().count();
    if n <= MAX_ERROR {
        return e;
    }
    let mut out: String = e.chars().take(MAX_ERROR).collect();
    out.push_str(&format!("… ({} more characters)", n - MAX_ERROR));
    out
}

// ---------------------------------------------------------------- views

/// A view a command names: an element, or the default 3D view before it comes to be.
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Target {
    Id(u64),
    Missing3d,
}

/// The categories a view is found by name in (sheets aren't, by name or number).
fn named_view(c: &str) -> bool {
    matches!(c, "level" | "planview" | "section" | "elevation" | "view3d" | "schedule")
}

/// A view by id, by name or by GUID; `{3D}` in any case is the default 3D view, which may not be
/// yet. "`view`: X is not a view" for an id the project hasn't, "no view named `X`" for a name.
pub fn lookup_view(pr: &Project, cmd: &str, v: &Value) -> R<Target> {
    let not = || format!("{}: `view`: {} is not a view", cmd, v.to_compact());
    match v {
        Value::Num(_) => {
            let id = id_of(v).ok_or_else(not)?;
            if pr.elements.contains_key(&id) {
                Ok(Target::Id(id))
            } else {
                Err(not())
            }
        }
        Value::Str(s) => {
            for (id, e) in &pr.elements {
                if named_view(cat(e)) && s_of(e, "name") == Some(s.as_str()) {
                    return Ok(Target::Id(*id));
                }
            }
            if is_default_3d_name(s) {
                return Ok(match default_3d(pr) {
                    Some(id) => Target::Id(id),
                    None => Target::Missing3d,
                });
            }
            if let Ok(id) = s.trim().parse::<u64>() {
                return if pr.elements.contains_key(&id) { Ok(Target::Id(id)) } else { Err(not()) };
            }
            if let Some(g) = crate::model::normalize_guid(s) {
                if let Some(id) = pr.find_guid(&g) {
                    return Ok(Target::Id(id));
                }
            }
            Err(format!("{}: no view named `{}`", cmd, s))
        }
        _ => Err(not()),
    }
}

/// How a message names a view (or another element): a view by its name, a sheet by its number.
pub fn label(pr: &Project, id: u64) -> String {
    match pr.el(id) {
        Some(e) if cat(e) == "sheet" => format!("sheet {}", s_of(e, "number").unwrap_or("")),
        Some(e) if named_view(cat(e)) => s_of(e, "name").unwrap_or("").to_string(),
        Some(e) => format!("{} {}", cat(e), id),
        None => id.to_string(),
    }
}

/// The view of `view` (the lowest level's plan unless given).
fn view_or_plan(pr: &Project, cmd: &str, p: &Value) -> R<Target> {
    match get(p, "view") {
        Some(v) => lookup_view(pr, cmd, v),
        None => default_plan(pr).map(Target::Id).ok_or_else(|| format!("{}: the project has no level", cmd)),
    }
}

/// Whether a view is a plan, a section or an elevation (they have a scale and a detail level).
fn is_drawing(c: &str) -> bool {
    matches!(c, "level" | "planview" | "section" | "elevation")
}

/// Whether a view takes graphics.
pub fn takes_graphics(c: &str) -> bool {
    is_drawing(c) || c == "view3d"
}

// ---------------------------------------------------------------- graphics

/// What `graphics` replies for a view: its graphics in force (`vid` none for the default 3D view
/// before it comes to be).
pub fn view_reply(pr: &Project, vid: Option<u64>, name: &str) -> Value {
    let own = vid.map(|id| vg::own(pr, vg::source_of(pr, id))).unwrap_or_default();
    let eff = vg::effective(pr, &own);
    let tpl = vg::template_of(pr, &own);
    let controlled: Vec<String> = tpl.as_ref().map(|(_, t)| vg::controls_of(t)).unwrap_or_default();
    let mut elements = Map::new();
    let mut hidden_elements = Vec::new();
    for (gd, o) in &vg::gmap(&own, "elements").items {
        let Some(id) = pr.find_guid(gd) else { continue };
        elements.insert(&id.to_string(), ovr::named_override(pr, o));
        if o.get("hidden").and_then(|h| h.as_bool()).unwrap_or(false) {
            hidden_elements.push(Value::u(id));
        }
    }
    jobj! {
        "background_grid" => vg::grid_reply(&eff),
        "categories" => Value::Obj(vg::named_categories(pr, &eff)),
        "controlled" => controlled,
        "detail" => gstr(&eff, "detail").unwrap_or_else(|| "fine".into()),
        "elements" => Value::Obj(elements),
        "filters" => vg::named_filters(pr, &eff),
        "hidden" => vg::hidden_categories(&eff),
        "hidden_elements" => Value::Arr(hidden_elements),
        "layers" => Value::Obj(vg::named_layers(pr, &own)),
        "name" => name,
        "options" => Value::Obj(vg::named_options(pr, &eff)),
        "phase" => vg::phase_name(pr, &eff),
        "phase_filter" => vg::phase_filter_name(pr, &eff),
        "scale" => eff.get("scale").cloned().unwrap_or(Value::Null),
        "template" => tpl.map(|(n, _)| Value::s(&n)).unwrap_or(Value::Null),
        "view" => vid.map(Value::u).unwrap_or(Value::Null),
        "visual_style" => gstr(&eff, "style").unwrap_or_else(|| "shaded".into()),
    }
}

/// The refusal of a change to a dependent view.
fn dependent_error(pr: &Project, cmd: &str, id: u64, parent: u64, what: &str) -> String {
    format!(
        "{}: {} is a dependent view: it follows its parent, `{}`, in its {}; change them there",
        cmd,
        name_of(pr, id),
        name_of(pr, parent),
        what
    )
}

fn cmd_graphics(s: &mut Session, p: &Value) -> R<Value> {
    let (vid, name) = apply(&mut s.project, "graphics", p)?;
    Ok(view_reply(&s.project, vid, &name))
}

/// What `graphics` does to a view (as its parameters say; `cmd` names the command in messages):
/// the view's id (none for the default 3D view while it isn't yet) and its name. A command that
/// changes a view's graphics in its own way (`show_mass`: `{view, hide: ["mass"]}` or `show`)
/// goes through here, and its refusals are graphics' (a dependent view's, a template's).
pub fn apply(pr: &mut Project, cmd: &str, p: &Value) -> R<(Option<u64>, String)> {
    let target = view_or_plan(pr, cmd, p)?;
    let vid = match target {
        Target::Id(id) => {
            if !takes_graphics(&cat_of(pr, id)) {
                return Err(format!("{}: {} isn't a plan, a section, an elevation or a 3D view", cmd, label(pr, id)));
            }
            Some(id)
        }
        Target::Missing3d => None,
    };
    let name = match vid {
        Some(id) => name_of(pr, id),
        None => DEFAULT_3D.to_string(),
    };
    let reset = crate::commands::params::opt_bool(p, cmd, "reset")?.unwrap_or(false);
    let src = vid.map(|id| vg::source_of(pr, id));
    let old = src.map(|id| vg::own(pr, id)).unwrap_or_default();
    // what the template the view is to follow controls isn't the view's to change: refused before
    // anything else is read (a template the project hasn't is none, refused later); a reset
    // starts the view over, and nothing is refused
    let follows: Option<(String, Value)> = match p.get("template") {
        _ if reset => None,
        Some(Value::Null) => None,
        Some(Value::Str(n)) => {
            let n = vg::entry_name(pr, "view-template", n);
            vg::templates(pr).get(&n).cloned().map(|t| (n, t))
        }
        _ => vg::template_of(pr, &old),
    };
    if let Some((tname, t)) = &follows {
        let c = vg::controls_of(t);
        let given = [
            ("categories", get(p, "hide").is_some() || get(p, "show").is_some() || get(p, "categories").is_some()),
            ("filters", get(p, "filters").is_some()),
            ("phase", p.get("phase").is_some() || p.get("phase_filter").is_some()),
            ("options", get(p, "options").is_some()),
            ("background_grid", p.get("background_grid").is_some()),
        ];
        for (group, given) in given {
            if given && c.iter().any(|x| x == group) {
                return Err(vg::followed_error(cmd, group, tname));
            }
        }
    }
    let mut g = if reset { Map::new() } else { old.clone() };
    edit::hide(pr, cmd, p, &mut g)?;
    edit::show(pr, cmd, p, &mut g)?;
    edit::hide_show_elements(pr, cmd, p, &mut g)?;
    edit::categories(pr, cmd, p, &mut g)?;
    edit::elements(pr, cmd, p, &mut g)?;
    let mut pend = edit::Pending::default();
    edit::filters(pr, cmd, p, &mut g, &mut pend)?;
    edit::grid(cmd, p, &mut g)?;
    edit::layers(pr, cmd, p, &mut g)?;
    edit::phase(pr, cmd, p, &mut g)?;
    edit::options(pr, cmd, p, &mut g, &mut pend)?;
    template_param(pr, cmd, p, &mut g, &mut pend)?;
    if g != old {
        if let Some(id) = vid {
            if let Some(parent) = vg::parent_of(pr, id) {
                return Err(dependent_error(pr, cmd, id, parent, "graphics"));
            }
        }
    }
    edit::check_with(pr, &g, &pend).map_err(|e| format!("{}: {}", cmd, e))?;
    let mut vid = vid;
    if g != old {
        let id = match src {
            Some(id) => id,
            None => {
                let id = ensure_default_3d(pr);
                vid = Some(id);
                id
            }
        };
        vg::store_in(pr, id, g);
    }
    Ok((vid, name))
}

/// `template`: the view template a view follows (by name), or null. A name the project hasn't
/// is held as it is, for the check to refuse.
fn template_param(pr: &Project, cmd: &str, p: &Value, g: &mut Map, pend: &mut edit::Pending) -> R<()> {
    match p.get("template") {
        None => Ok(()),
        Some(Value::Null) => {
            gput(g, "template", None);
            Ok(())
        }
        Some(Value::Str(n)) => {
            let ts = vg::templates(pr);
            let n = &vg::entry_name(pr, "view-template", n);
            match pr.lib_guid("view-template", n) {
                Some(gd) if ts.contains(n) => gput(g, "template", Some(Value::s(&gd))),
                _ => {
                    gput(g, "template", Some(Value::s(n)));
                    pend.template = Some(n.clone());
                }
            }
            Ok(())
        }
        Some(v) => Err(format!("{}: `template` is a view template's name, or null, not {}", cmd, v.to_compact())),
    }
}

// ---------------------------------------------------------------- scale, detail and visual style

/// The template a view (by its graphics' source) follows, where it controls `group`.
fn controlling(pr: &Project, src: u64, group: &str) -> Option<String> {
    let (n, t) = vg::template_of(pr, &vg::own(pr, src))?;
    if vg::controls_of(&t).iter().any(|x| x == group) {
        Some(n)
    } else {
        None
    }
}

/// A plan, a section or an elevation a command names.
fn drawing_view(pr: &Project, cmd: &str, p: &Value) -> R<u64> {
    let id = match view_or_plan(pr, cmd, p)? {
        Target::Id(id) => id,
        Target::Missing3d => {
            let n = get(p, "view").and_then(|v| v.as_str()).unwrap_or(DEFAULT_3D).to_string();
            return Err(format!("{}: no view named `{}`", cmd, n));
        }
    };
    if !is_drawing(&cat_of(pr, id)) {
        return Err(format!("{}: {} isn't a plan, a section or an elevation; only those have one", cmd, label(pr, id)));
    }
    Ok(id)
}

/// The n of 1 : n a scale is, from 1 to 100000.
pub fn scale_of(cmd: &str, v: &Value) -> R<f64> {
    let bad = || format!("{}: `scale` is the n of 1 : n, from 1 to 100000, not {}", cmd, v.to_compact());
    match v {
        Value::Null => Err(format!(
            "{}: `scale` is the n of 1 : n, from 1 to 100000, not null: a view always has a scale (1 : 100, or 1/8\" = 1'-0\" in feet and inches, until it is given one)",
            cmd
        )),
        Value::Num(n) => {
            let x = n.as_f64();
            if x.is_finite() && (1.0..=100000.0).contains(&x) {
                Ok(x)
            } else {
                Err(bad())
            }
        }
        _ => Err(bad()),
    }
}

/// A detail level: coarse, medium or fine (any case).
pub fn detail_of(cmd: &str, v: &Value) -> R<String> {
    if let Value::Str(s) = v {
        let k = vg::squash(s);
        if ["coarse", "medium", "fine"].contains(&k.as_str()) {
            return Ok(k);
        }
    }
    Err(format!("{}: `detail` is coarse, medium or fine, not {}", cmd, v.to_compact()))
}

/// A visual style: shaded, hidden_line or wireframe (any case, with or without the underscore).
pub fn style_of(cmd: &str, key: &str, v: &Value) -> R<String> {
    if let Value::Str(s) = v {
        match vg::squash(s).as_str() {
            "shaded" => return Ok("shaded".into()),
            "hiddenline" => return Ok("hidden_line".into()),
            "wireframe" => return Ok("wireframe".into()),
            _ => {}
        }
    }
    Err(format!("{}: `{}` is shaded, hidden_line or wireframe, not {}", cmd, key, v.to_compact()))
}

fn cmd_scale(s: &mut Session, p: &Value) -> R<Value> {
    let cmd = "scale";
    let pr = &mut s.project;
    let id = drawing_view(pr, cmd, p)?;
    let src = vg::source_of(pr, id);
    if let Some(v) = p.get("scale") {
        let x = scale_of(cmd, v)?;
        if let Some(parent) = vg::parent_of(pr, id) {
            return Err(dependent_error(pr, cmd, id, parent, "scale"));
        }
        if let Some(t) = controlling(pr, src, "scale") {
            return Err(vg::followed_error(cmd, "scale", &t));
        }
        let mut g = vg::own(pr, src);
        gput(&mut g, "scale", Some(Value::f(x)));
        vg::store_in(pr, src, g);
    }
    let eff = vg::effective_of(pr, id);
    let sc = eff.get("scale").and_then(|x| x.as_f64()).unwrap_or_else(|| vg::default_scale(pr));
    Ok(jobj! {"name" => name_of(pr, id), "scale" => Value::f(sc), "view" => id})
}

fn cmd_detail(s: &mut Session, p: &Value) -> R<Value> {
    let cmd = "detail";
    let pr = &mut s.project;
    let id = drawing_view(pr, cmd, p)?;
    let src = vg::source_of(pr, id);
    if let Some(v) = get(p, "detail") {
        let d = detail_of(cmd, v)?;
        if let Some(parent) = vg::parent_of(pr, id) {
            return Err(dependent_error(pr, cmd, id, parent, "detail level"));
        }
        if let Some(t) = controlling(pr, src, "detail") {
            return Err(vg::followed_error(cmd, "detail", &t));
        }
        let mut g = vg::own(pr, src);
        gput(&mut g, "detail", if d == "fine" { None } else { Some(Value::s(&d)) });
        vg::store_in(pr, src, g);
    }
    let eff = vg::effective_of(pr, id);
    let d = gstr(&eff, "detail").unwrap_or_else(|| "fine".into());
    Ok(jobj! {"detail" => d, "name" => name_of(pr, id), "view" => id})
}

fn cmd_visual_style(s: &mut Session, p: &Value) -> R<Value> {
    let cmd = "visual_style";
    let pr = &mut s.project;
    let target = match get(p, "view") {
        Some(v) => lookup_view(pr, cmd, v)?,
        None => match default_3d(pr) {
            Some(id) => Target::Id(id),
            None => Target::Missing3d,
        },
    };
    let mut vid = match target {
        Target::Id(id) => {
            if cat_of(pr, id) != "view3d" {
                return Err(format!("{}: {} isn't a 3D view; only those have a visual style", cmd, label(pr, id)));
            }
            Some(id)
        }
        Target::Missing3d => None,
    };
    if let Some(v) = get(p, "style") {
        let st = style_of(cmd, "style", v)?;
        if let Some(id) = vid {
            if let Some(t) = controlling(pr, id, "style") {
                return Err(vg::followed_error(cmd, "style", &t));
            }
        }
        let old = vid.map(|id| vg::own(pr, id)).unwrap_or_default();
        let mut g = old.clone();
        gput(&mut g, "style", if st == "shaded" { None } else { Some(Value::s(&st)) });
        if g != old {
            let id = match vid {
                Some(id) => id,
                None => ensure_default_3d(pr),
            };
            vid = Some(id);
            vg::store_in(pr, id, g);
        }
    }
    let eff = vid.map(|id| vg::effective_of(pr, id)).unwrap_or_default();
    let st = gstr(&eff, "style").unwrap_or_else(|| "shaded".into());
    Ok(jobj! {"style" => st, "view" => vid.map(Value::u).unwrap_or(Value::Null)})
}

// ---------------------------------------------------------------- the model's rules

/// The model rules of this part, checked after every command, in the model's order: the view
/// filters, the view templates, then what each view's graphics hold.
pub fn check(pr: &Project) -> R<()> {
    super::filters::check_all(pr)?;
    super::templates::check_all(pr)?;
    for (id, e) in &pr.elements {
        let Some(Value::Obj(g)) = e.get("graphics") else { continue };
        if !takes_graphics(cat(e)) {
            continue;
        }
        edit::check(pr, g).map_err(|m| format!("{} {}: {}", cat(e), id, m))?;
    }
    Ok(())
}

/// What `elements` shows of a view's graphics: what they name by GUID, named.
pub fn element_view(pr: &Project, _id: u64, x: &mut Value) {
    if let Some(Value::Obj(g)) = x.get("graphics").cloned() {
        x.set("graphics", vg::named(pr, &g));
    }
}
