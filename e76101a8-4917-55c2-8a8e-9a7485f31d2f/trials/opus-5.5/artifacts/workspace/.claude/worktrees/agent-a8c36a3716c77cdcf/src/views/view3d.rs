//! 3D views: `section_box`, `perspective`, `graphic_display_options`, `camera`, `work_plane`.
//!
//! A 3D view (`view3d`) keeps, in this order: `guid`, `category`, `name`, `azimuth`, `elevation`, `graphics`,
//! `section_box` {min, max, on}, `perspective` {lens, on}, `camera` {eye, target}, `display` {edges, silhouette?,
//! ambient_shadows?} (left out while it is the default) and `work_plane` {level?, offset?, points?, surface?}.

use super::common::*;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;
use crate::commands::params::{opt_bool, opt_num};

pub mod de;
pub mod scene;

/// The fields of a 3D view in the order the original writes them.
pub const FIELDS: &[&str] = &[
    "guid",
    "category",
    "name",
    "azimuth",
    "elevation",
    "graphics",
    "section_box",
    "perspective",
    "camera",
    "display",
    "work_plane",
];

/// How far a fitted section box stands clear of the model, mm.
pub const SECTION_BOX_ROOM: f64 = 300.0;
/// The least a section box spans on each axis, mm.
pub const MIN_SECTION_BOX: f64 = 10.0;
/// The widest silhouette, px.
pub const MAX_SILHOUETTE: u64 = 10;
/// The lens a view is seen through until told, mm.
pub const DEFAULT_LENS: f64 = 35.0;
/// The largest coordinate the model takes, mm.
pub const REACH: f64 = 1e9;

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "section_box" => section_box(s, p),
        "perspective" => perspective(s, p),
        "graphic_display_options" => display(s, p),
        "camera" => camera(s, p),
        "work_plane" => work_plane(s, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

// ---------------------------------------------------------------- views by name, id or GUID

/// The categories a view of the model (or a schedule) is, which a view is found by name among.
pub const NAMED_VIEWS: &[&str] = &["level", "planview", "section", "elevation", "view3d", "schedule"];

/// A GUID as the original reads one: 36 characters, hyphenated, in any case (spaces round it aside).
pub fn strict_guid(s: &str) -> Option<String> {
    let t = s.trim();
    let b = t.as_bytes();
    if b.len() != 36 {
        return None;
    }
    for (i, c) in b.iter().enumerate() {
        let dash = matches!(i, 8 | 13 | 18 | 23);
        if dash {
            if *c != b'-' {
                return None;
            }
        } else if !c.is_ascii_hexdigit() {
            return None;
        }
    }
    Some(t.to_ascii_lowercase())
}

/// The view of a model (or the schedule) of this name, the first by id.
pub fn view_named(pr: &Project, name: &str) -> Option<u64> {
    pr.elements
        .iter()
        .find(|(_, e)| NAMED_VIEWS.contains(&cat(e)) && s_of(e, "name") == Some(name))
        .map(|(id, _)| *id)
}

/// A view given by name (not a sheet's number), by id (any element: what it isn't is the command's
/// to say) or by GUID: "`view`: X is not a view" for what is neither, "no view named `X`" for a name none has.
pub fn lookup_view(pr: &Project, cmd: &str, key: &str, v: &Value) -> R<u64> {
    let not = || format!("{}: `{}`: {} is not a view", cmd, key, v.clone().sorted().to_compact());
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
            if let Some(id) = view_named(pr, s) {
                return Ok(id);
            }
            if let Ok(id) = s.trim().parse::<u64>() {
                if pr.elements.contains_key(&id) {
                    return Ok(id);
                }
            }
            if let Some(g) = strict_guid(s) {
                if let Some(id) = pr.find_guid(&g) {
                    return Ok(id);
                }
            }
            Err(format!("{}: no view named `{}`", cmd, s))
        }
        _ => Err(not()),
    }
}

/// How the original names an element it was given as a view: a view by its name, a sheet as
/// "sheet A101", anything else as "wall 100002".
pub fn describe(pr: &Project, id: u64) -> String {
    match pr.el(id) {
        Some(e) if NAMED_VIEWS.contains(&cat(e)) => s_of(e, "name").unwrap_or("").to_string(),
        Some(e) if cat(e) == "sheet" => format!("sheet {}", s_of(e, "number").unwrap_or("")),
        _ => cat_id(pr, id),
    }
}

/// The default 3D view: the 3D view named `{3D}`.
pub fn default_view(pr: &Project) -> Option<u64> {
    pr.elements
        .iter()
        .find(|(_, e)| cat(e) == "view3d" && s_of(e, "name") == Some(DEFAULT_3D))
        .map(|(id, _)| *id)
}

/// The default 3D view, made as the original makes it.
pub fn make_default_view(pr: &mut Project) -> u64 {
    if let Some(id) = default_view(pr) {
        return id;
    }
    let id = pr.alloc_id();
    pr.elements.insert(
        id,
        jobj! {
            "guid" => crate::rand::guid(),
            "category" => "view3d",
            "name" => DEFAULT_3D,
            "azimuth" => -45.0,
            "elevation" => 30.0,
        },
    );
    id
}

/// The 3D view a command works on: `view` (a 3D view's name or id; `{3D}` in any case is the default
/// one), else the default one. `None`: the default 3D view, not made yet.
pub fn target(pr: &Project, cmd: &str, p: &Value, why: &str) -> R<Option<u64>> {
    let id = match get(p, "view") {
        None => return Ok(default_view(pr)),
        Some(Value::Str(s)) if is_default_3d_name(s) => return Ok(default_view(pr)),
        Some(v) => lookup_view(pr, cmd, "view", v)?,
    };
    if cat_of(pr, id) != "view3d" {
        return Err(format!("{}: {} isn't a 3D view; {}", cmd, describe(pr, id), why));
    }
    Ok(Some(id))
}

/// The view a command changes: the one it named, or the default one, made now.
fn made(pr: &mut Project, t: Option<u64>) -> u64 {
    match t {
        Some(id) => id,
        None => make_default_view(pr),
    }
}

/// Sets a field of a 3D view where the original writes it.
pub fn put(e: &mut Value, k: &str, v: Value) {
    let Value::Obj(m) = e else { return };
    if let Some(slot) = m.get_mut(k) {
        *slot = v;
        return;
    }
    let rank = |key: &str| FIELDS.iter().position(|f| *f == key);
    let Some(r) = rank(k) else {
        m.items.push((k.to_string(), v));
        return;
    };
    let pos = m
        .items
        .iter()
        .position(|(kk, _)| match rank(kk) {
            Some(rr) => rr > r,
            None => true,
        })
        .unwrap_or(m.items.len());
    m.items.insert(pos, (k.to_string(), v));
}

fn put_field(pr: &mut Project, id: u64, k: &str, v: Value) {
    if let Some(e) = pr.el_mut(id) {
        put(e, k, v);
    }
}

// ---------------------------------------------------------------- reading a view's settings

/// A point [x, y, z] of numbers.
pub fn p3(v: &Value) -> Option<[f64; 3]> {
    let a = v.as_arr()?;
    if a.len() != 3 {
        return None;
    }
    Some([a[0].as_f64()?, a[1].as_f64()?, a[2].as_f64()?])
}

/// A view's section box: min, max, on.
pub fn section_box_of(e: &Value) -> Option<([f64; 3], [f64; 3], bool)> {
    let b = e.get("section_box")?;
    let min = p3(b.get("min")?)?;
    let max = p3(b.get("max")?)?;
    let on = b.get("on").and_then(|x| x.as_bool()).unwrap_or(true);
    Some((min, max, on))
}

/// A view's perspective: lens, on.
pub fn perspective_of(e: &Value) -> Option<(f64, bool)> {
    let p = e.get("perspective")?;
    let lens = p.get("lens").and_then(|x| x.as_f64()).unwrap_or(DEFAULT_LENS);
    let on = p.get("on").and_then(|x| x.as_bool()).unwrap_or(true);
    Some((lens, on))
}

/// A view's camera: eye, target.
pub fn camera_of(e: &Value) -> Option<([f64; 3], [f64; 3])> {
    let c = e.get("camera")?;
    Some((p3(c.get("eye")?)?, p3(c.get("target")?)?))
}

/// A 3D view's graphic display options.
#[derive(Clone, Copy, PartialEq, Debug)]
pub struct Display {
    pub edges: bool,
    pub silhouette: u64,
    pub ambient_shadows: bool,
}

impl Default for Display {
    fn default() -> Display {
        Display { edges: true, silhouette: 0, ambient_shadows: false }
    }
}

impl Display {
    pub fn of(e: &Value) -> Display {
        let d = Display::default();
        let Some(x) = e.get("display") else { return d };
        Display {
            edges: x.get("edges").and_then(|v| v.as_bool()).unwrap_or(d.edges),
            silhouette: x.get("silhouette").and_then(|v| v.as_f64()).map(|v| v as u64).unwrap_or(d.silhouette),
            ambient_shadows: x.get("ambient_shadows").and_then(|v| v.as_bool()).unwrap_or(d.ambient_shadows),
        }
    }
    /// As the original saves it (none while it is the default).
    pub fn to_value(&self) -> Option<Value> {
        if *self == Display::default() {
            return None;
        }
        let mut m = Map::new();
        m.insert("edges", Value::Bool(self.edges));
        if self.silhouette != 0 {
            m.insert("silhouette", Value::u(self.silhouette));
        }
        if self.ambient_shadows {
            m.insert("ambient_shadows", Value::Bool(true));
        }
        Some(Value::Obj(m))
    }
}

// ---------------------------------------------------------------- section_box

/// A corner of the section box: [x, y, z] of numbers, any size (the check says what isn't usable).
fn corner(p: &Value, cmd: &str, key: &str) -> R<Option<[f64; 3]>> {
    match get(p, key) {
        None => Ok(None),
        Some(v) => p3(v).map(Some).ok_or_else(|| {
            format!("{}: `{}`, a corner of the section box, is [x, y, z] in mm, not {}", cmd, key, v.clone().sorted().to_compact())
        }),
    }
}

fn section_box(s: &mut Session, p: &Value) -> R<Value> {
    let cmd = "section_box";
    let t = target(&s.project, cmd, p, "only a 3D view has a section box")?;
    let min = corner(p, cmd, "min")?;
    let max = corner(p, cmd, "max")?;
    let on = opt_bool(p, cmd, "on")?.unwrap_or(true);
    let pr = &mut s.project;
    let cur = t.and_then(|id| pr.el(id)).and_then(section_box_of);
    let (min, max) = match (min, max, cur) {
        (Some(a), Some(b), _) => (a, b),
        (a, b, Some((cmin, cmax, _))) => (a.unwrap_or(cmin), b.unwrap_or(cmax)),
        (a, b, None) => {
            let Some((lo, hi)) = scene::model_box(pr) else {
                return Err(format!(
                    "{}: there's nothing in the project to fit a section box round: give its `min` and `max`",
                    cmd
                ));
            };
            let r = SECTION_BOX_ROOM;
            let flo = [lo[0] - r, lo[1] - r, lo[2] - r];
            let fhi = [hi[0] + r, hi[1] + r, hi[2] + r];
            (a.unwrap_or(flo), b.unwrap_or(fhi))
        }
    };
    let id = made(pr, t);
    put_field(pr, id, "section_box", jobj! {"min" => min, "max" => max, "on" => on});
    super::mark_step();
    Ok(jobj! {"max" => max, "min" => min, "on" => on, "view" => id})
}

// ---------------------------------------------------------------- perspective

fn perspective(s: &mut Session, p: &Value) -> R<Value> {
    let cmd = "perspective";
    let t = target(&s.project, cmd, p, "only a 3D view is seen in perspective")?;
    let on = opt_bool(p, cmd, "on")?.unwrap_or(true);
    let lens = opt_num(p, cmd, "lens")?;
    let pr = &mut s.project;
    let cur = t.and_then(|id| pr.el(id)).and_then(perspective_of).map(|(l, _)| l).unwrap_or(DEFAULT_LENS);
    let lens = lens.unwrap_or(cur);
    let id = made(pr, t);
    put_field(pr, id, "perspective", jobj! {"lens" => lens, "on" => on});
    super::mark_step();
    Ok(jobj! {"lens" => lens, "on" => on, "view" => id})
}

// ---------------------------------------------------------------- graphic_display_options

fn display(s: &mut Session, p: &Value) -> R<Value> {
    let cmd = "graphic_display_options";
    let t = target(&s.project, cmd, p, "only a 3D view has graphic display options")?;
    let silhouette = match get(p, "silhouette") {
        None => None,
        Some(v) => {
            let ok = num_of(v).filter(|x| x.fract() == 0.0 && *x >= 0.0 && *x <= MAX_SILHOUETTE as f64);
            match ok {
                Some(x) => Some(x as u64),
                None => {
                    return Err(format!(
                        "{}: `silhouette` is how many px wide the outline is, a whole number 0 to 10, got {}",
                        cmd,
                        v.clone().sorted().to_compact()
                    ))
                }
            }
        }
    };
    let edges = opt_bool(p, cmd, "edges")?;
    let ambient = opt_bool(p, cmd, "ambient_shadows")?;
    let pr = &mut s.project;
    let cur = t.and_then(|id| pr.el(id)).map(Display::of).unwrap_or_default();
    let new = Display {
        edges: edges.unwrap_or(cur.edges),
        silhouette: silhouette.unwrap_or(cur.silhouette),
        ambient_shadows: ambient.unwrap_or(cur.ambient_shadows),
    };
    let reply = |view: Value| {
        jobj! {"ambient_shadows" => new.ambient_shadows, "edges" => new.edges, "silhouette" => new.silhouette, "view" => view}
    };
    if t.is_none() && new == Display::default() {
        // nothing to change on a view that hasn't come to be: it stays as it is, unmade
        return Ok(reply(Value::Null));
    }
    let changing = edges.is_some() || silhouette.is_some() || ambient.is_some();
    let id = match t {
        Some(id) => id,
        None => make_default_view(pr),
    };
    if changing {
        if let Some(e) = pr.el_mut(id) {
            match new.to_value() {
                Some(v) => put(e, "display", v),
                None => {
                    e.remove("display");
                }
            }
        }
    }
    Ok(reply(Value::u(id)))
}

// ---------------------------------------------------------------- camera

fn point3(p: &Value, cmd: &str, key: &str) -> R<Option<[f64; 3]>> {
    match get(p, key) {
        None => Ok(None),
        Some(v) => point3_of(v)
            .map(Some)
            .ok_or_else(|| format!("{}: `{}` must be a point [x, y, z] in mm, got {}", cmd, key, v.clone().sorted().to_compact())),
    }
}

pub fn dist3(a: [f64; 3], b: [f64; 3]) -> f64 {
    ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt()
}

/// The eye this close to the target (mm) or closer has nothing to look at.
pub const EYE_GAP: f64 = 1.0;

/// The names every view goes by (levels too), which a new camera's number steps past.
fn view_names(pr: &Project) -> Vec<String> {
    pr.elements
        .values()
        .filter(|e| NAMED_VIEWS.contains(&cat(e)))
        .filter_map(|e| s_of(e, "name").map(|s| s.to_string()))
        .collect()
}

fn camera(s: &mut Session, p: &Value) -> R<Value> {
    let cmd = "camera";
    let view_given = has(p, "view");
    let t = if view_given { target(&s.project, cmd, p, "a camera goes on a 3D view")? } else { None };
    let eye = point3(p, cmd, "eye")?;
    let tgt = point3(p, cmd, "target")?;
    let lens = opt_num(p, cmd, "lens")?;
    let pr = &mut s.project;
    let el = t.and_then(|id| pr.el(id));
    let cur_cam = el.and_then(camera_of);
    let cur_persp = el.and_then(perspective_of);
    if view_given && eye.is_none() && tgt.is_none() && lens.is_none() {
        // reading it back makes nothing
        let name = match t {
            Some(id) => name_of(pr, id),
            None => DEFAULT_3D.to_string(),
        };
        let (l, on) = cur_persp.unwrap_or((DEFAULT_LENS, false));
        return Ok(jobj! {
            "eye" => cur_cam.map(|c| Value::from(c.0)),
            "lens" => l,
            "name" => name,
            "perspective" => on,
            "target" => cur_cam.map(|c| Value::from(c.1)),
            "view" => t,
        });
    }
    let (eye, tgt) = match (eye.or(cur_cam.map(|c| c.0)), tgt.or(cur_cam.map(|c| c.1))) {
        (Some(e), Some(t)) => (e, t),
        _ => return Err(format!("{}: `eye` and `target` [x, y, z] are both required to set a camera", cmd)),
    };
    if dist3(eye, tgt) <= EYE_GAP {
        return Err(format!("{}: the eye is on the target; give the camera two points a little apart", cmd));
    }
    let lens = match lens {
        Some(l) => l,
        None => match cur_persp {
            Some((l, true)) => l,
            _ => DEFAULT_LENS,
        },
    };
    if !(10.0..=600.0).contains(&lens) {
        return Err(format!("{}: a {} mm lens is no camera's; a camera's lens is 10 to 600 mm", cmd, disp(lens)));
    }
    let id = if view_given {
        made(pr, t)
    } else {
        let name = match opt_text(p, cmd, "name")? {
            Some(n) => n,
            None => {
                let base = word(pr, ["Camera", "Câmera", "Cámara", "Kamera", "Kamera", "Caméra", "Camera", "Kamera", "Camera"]);
                let names = view_names(pr);
                let mut n = 1u64;
                loop {
                    let c = format!("{} {}", base, n);
                    if !names.contains(&c) {
                        break c;
                    }
                    n += 1;
                }
            }
        };
        let id = pr.alloc_id();
        pr.elements.insert(
            id,
            jobj! {
                "guid" => crate::rand::guid(),
                "category" => "view3d",
                "name" => name,
                "azimuth" => -45.0,
                "elevation" => 30.0,
            },
        );
        id
    };
    put_field(pr, id, "perspective", jobj! {"lens" => lens, "on" => true});
    put_field(pr, id, "camera", jobj! {"eye" => eye, "target" => tgt});
    super::mark_step();
    Ok(jobj! {
        "eye" => eye,
        "id" => id,
        "lens" => lens,
        "name" => name_of(pr, id),
        "perspective" => true,
        "target" => tgt,
        "view" => id,
    })
}

fn opt_text(p: &Value, cmd: &str, key: &str) -> R<Option<String>> {
    crate::commands::params::opt_text(p, cmd, key)
}

// ---------------------------------------------------------------- work_plane

/// A work plane as a view keeps it.
#[derive(Clone, Debug, PartialEq)]
pub enum On {
    Level(String),
    Points([[f64; 3]; 3]),
    Surface { point: [f64; 3], normal: [f64; 3] },
}

#[derive(Clone, Debug, PartialEq)]
pub struct WorkPlane {
    pub on: On,
    pub offset: f64,
}

impl WorkPlane {
    pub fn to_value(&self) -> Value {
        let mut m = Map::new();
        if let On::Level(g) = &self.on {
            m.insert("level", Value::s(g));
        }
        if self.offset != 0.0 {
            m.insert("offset", Value::f(self.offset));
        }
        match &self.on {
            On::Points(ps) => {
                m.insert("points", Value::Arr(ps.iter().map(|q| Value::from(*q)).collect()));
            }
            On::Surface { point, normal } => {
                m.insert("surface", jobj! {"point" => *point, "normal" => *normal});
            }
            On::Level(_) => {}
        }
        Value::Obj(m)
    }
}

/// A view's work plane as it keeps it (none read from what isn't one).
pub fn work_plane_of(e: &Value) -> Option<WorkPlane> {
    let w = e.get("work_plane")?;
    let offset = w.get("offset").and_then(|x| x.as_f64()).unwrap_or(0.0);
    if let Some(g) = w.get("level").and_then(|x| x.as_str()) {
        return Some(WorkPlane { on: On::Level(g.to_string()), offset });
    }
    if let Some(a) = w.get("points").and_then(|x| x.as_arr()) {
        if a.len() == 3 {
            let q: Vec<[f64; 3]> = a.iter().filter_map(p3).collect();
            if q.len() == 3 {
                return Some(WorkPlane { on: On::Points([q[0], q[1], q[2]]), offset });
            }
        }
    }
    if let Some(sf) = w.get("surface") {
        if let (Some(point), Some(normal)) = (sf.get("point").and_then(p3), sf.get("normal").and_then(p3)) {
            return Some(WorkPlane { on: On::Surface { point, normal }, offset });
        }
    }
    None
}

/// A plane: a point of it and its unit normal.
#[derive(Clone, Copy, Debug)]
pub struct Frame {
    pub origin: [f64; 3],
    pub normal: [f64; 3],
}

/// A vector made a unit one as the original does (times one over its length).
pub fn unit3(v: [f64; 3]) -> [f64; 3] {
    let l = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt();
    let k = 1.0 / l;
    [v[0] * k, v[1] * k, v[2] * k]
}

pub fn sub3(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}

pub fn cross3(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}

pub fn len3(v: [f64; 3]) -> f64 {
    (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt()
}

/// Upright: its normal this little off level (or less).
pub const UPRIGHT: f64 = 1e-9;

/// The three points lie along a line: the triangle's least height (over its longest side) is
/// a millimetre or less.
pub fn along_a_line(ps: &[[f64; 3]; 3]) -> bool {
    let a = sub3(ps[1], ps[0]);
    let b = sub3(ps[2], ps[0]);
    let c = sub3(ps[2], ps[1]);
    let longest = len3(a).max(len3(b)).max(len3(c));
    if longest <= 0.0 {
        return true;
    }
    len3(cross3(a, b)) / longest <= 1.0
}

fn out_of_reach(q: [f64; 3]) -> bool {
    q.iter().any(|x| !(x.abs() <= REACH))
}

/// The plane a work plane resolves to (`None` where its level isn't in the project).
pub fn frame(pr: &Project, w: &WorkPlane) -> Option<Frame> {
    match &w.on {
        On::Level(g) => {
            let id = pr.find_guid(g)?;
            let z = f_of(pr.el(id)?, "elevation").unwrap_or(0.0);
            Some(Frame { origin: [0.0, 0.0, z + w.offset], normal: [0.0, 0.0, 1.0] })
        }
        On::Points(ps) => {
            let mut n = unit3(cross3(sub3(ps[1], ps[0]), sub3(ps[2], ps[0])));
            if !(n[2].abs() <= UPRIGHT) && n[2] < 0.0 {
                n = [-n[0], -n[1], -n[2]];
            }
            let o = ps[0];
            Some(Frame { origin: [o[0] + n[0] * w.offset, o[1] + n[1] * w.offset, o[2] + n[2] * w.offset], normal: n })
        }
        On::Surface { point, normal } => {
            let n = unit3(*normal);
            let o = *point;
            Some(Frame { origin: [o[0] + n[0] * w.offset, o[1] + n[1] * w.offset, o[2] + n[2] * w.offset], normal: n })
        }
    }
}

/// The plane a view sketches on: its work plane, else the lowest level's.
pub fn view_frame(pr: &Project, view: Option<u64>) -> Frame {
    let w = view.and_then(|id| pr.el(id)).and_then(work_plane_of);
    if let Some(w) = w {
        if let Some(f) = frame(pr, &w) {
            return f;
        }
    }
    let z = default_plan(pr).and_then(|l| pr.el(l)).and_then(|e| f_of(e, "elevation")).unwrap_or(0.0);
    Frame { origin: [0.0, 0.0, z], normal: [0.0, 0.0, 1.0] }
}

/// What `work_plane` says of a plane.
fn plane_reply(pr: &Project, view: u64, w: Option<&WorkPlane>, f: &Frame) -> Value {
    let level = match w {
        None => default_plan(pr),
        Some(WorkPlane { on: On::Level(g), .. }) => pr.find_guid(g),
        Some(_) => None,
    };
    let offset = w.map(|w| w.offset).unwrap_or(0.0);
    let points = match w {
        Some(WorkPlane { on: On::Points(ps), .. }) => Value::Arr(ps.iter().map(|q| Value::from(*q)).collect()),
        _ => Value::Null,
    };
    let surface = match w {
        Some(WorkPlane { on: On::Surface { point, normal }, .. }) => jobj! {"normal" => *normal, "point" => *point},
        _ => Value::Null,
    };
    let n = f.normal;
    let o = f.origin;
    let slope = n[2].abs().min(1.0).acos().to_degrees();
    let z = if n[2].abs() <= UPRIGHT { Value::Null } else { Value::f(o[2] + (n[0] / n[2]) * o[0] + (n[1] / n[2]) * o[1]) };
    jobj! {
        "level" => level,
        "normal" => n,
        "offset" => offset,
        "origin" => o,
        "points" => points,
        "slope" => slope,
        "surface" => surface,
        "view" => view,
        "z" => z,
    }
}

fn work_plane(s: &mut Session, p: &Value) -> R<Value> {
    let cmd = "work_plane";
    let t = target(&s.project, cmd, p, "only a 3D view has a work plane to set")?;
    let offset = opt_num(p, cmd, "offset")?;
    let points = match get(p, "points") {
        None => None,
        Some(v) => {
            let bad = || {
                format!(
                    "{}: `points` are three points [[x, y, z], [x, y, z], [x, y, z]] in mm, not {}",
                    cmd,
                    v.clone().sorted().to_compact()
                )
            };
            let a = v.as_arr().ok_or_else(bad)?;
            if a.len() != 3 {
                return Err(bad());
            }
            let q: Vec<[f64; 3]> = a.iter().filter_map(p3).collect();
            if q.len() != 3 {
                return Err(bad());
            }
            Some([q[0], q[1], q[2]])
        }
    };
    let surface = match get(p, "surface") {
        None => None,
        Some(v) => Some(de::surface(v).map_err(|e| {
            format!("{}: `surface` is {{point: [x, y, z], normal: [x, y, z]}}, a point of it in mm and the way it faces: {}", cmd, e)
        })?),
    };
    let level = match get(p, "level") {
        None => None,
        Some(v) => Some(crate::model::resolve_level(&s.project, cmd, "level", v)?),
    };
    let kinds = level.is_some() as u8 + points.is_some() as u8 + surface.is_some() as u8;
    if kinds > 1 {
        return Err(format!(
            "{}: a work plane is on a `level`, through three `points` or on a `surface`: only one of them",
            cmd
        ));
    }
    if let Some(ps) = &points {
        if ps.iter().any(|q| out_of_reach(*q)) {
            return Err(format!("{}: a point of the work plane isn't a place in the project", cmd));
        }
        if along_a_line(ps) {
            return Err(format!("{}: the work plane's three points lie along a line: pick three that make a triangle", cmd));
        }
    }
    if let Some((point, normal)) = &surface {
        if out_of_reach(*point) {
            return Err(format!("{}: the work plane's surface point isn't a place in the project", cmd));
        }
        if len3(*normal) <= UPRIGHT {
            return Err(format!(
                "{}: the work plane's surface `normal` is the way it faces, [x, y, z], and can't be [0, 0, 0]",
                cmd
            ));
        }
    }
    let pr = &mut s.project;
    let before = t.and_then(|id| pr.el(id)).and_then(work_plane_of);
    let old_frame = view_frame(pr, t);
    let new: Option<WorkPlane> = if let Some(l) = level {
        Some(WorkPlane { on: On::Level(guid(pr, l)), offset: offset.unwrap_or(0.0) })
    } else if let Some(ps) = points {
        Some(WorkPlane { on: On::Points(ps), offset: offset.unwrap_or(0.0) })
    } else if let Some((point, normal)) = surface {
        Some(WorkPlane { on: On::Surface { point, normal }, offset: offset.unwrap_or(0.0) })
    } else if let Some(o) = offset {
        // only an offset: the plane as it is, moved by that instead
        let on = match &before {
            Some(w) => w.on.clone(),
            None => On::Level(default_plan(pr).map(|l| guid(pr, l)).unwrap_or_default()),
        };
        Some(WorkPlane { on, offset: o })
    } else {
        None
    };
    let id = made(pr, t);
    if let Some(e) = pr.el_mut(id) {
        match &new {
            Some(w) => put(e, "work_plane", w.to_value()),
            None => {
                e.remove("work_plane");
            }
        }
    }
    super::mark_step();
    let f = match &new {
        // given nothing, the original says the plane it had
        None => old_frame,
        Some(w) => frame(pr, w).unwrap_or(old_frame),
    };
    Ok(plane_reply(pr, id, new.as_ref(), &f))
}

/// A level deleted takes the work planes on it with it (for `delete`).
pub fn forget_level(pr: &mut Project, level_guid: &str) {
    for e in pr.elements.values_mut() {
        if cat(e) != "view3d" {
            continue;
        }
        let on_it = e.get("work_plane").and_then(|w| w.get("level")).and_then(|g| g.as_str()) == Some(level_guid);
        if on_it {
            e.remove("work_plane");
        }
    }
}

// ---------------------------------------------------------------- the model rules

fn usable(x: f64) -> bool {
    x.is_finite() && x.abs() <= REACH
}

const AXES: [&str; 3] = ["x", "y", "z"];

fn check_view(pr: &Project, id: u64, e: &Value) -> R<()> {
    let name = s_of(e, "name").unwrap_or("");
    if name.trim().is_empty() {
        return Err(format!("view3d {}: a view needs a name", id));
    }
    if let Some((min, max, _)) = section_box_of(e) {
        for i in 0..3 {
            for v in [min[i], max[i]] {
                if !usable(v) {
                    return Err(format!("view3d {} section box {}: {} is not a usable number", id, AXES[i], disp(v)));
                }
            }
            if max[i] - min[i] < MIN_SECTION_BOX {
                return Err(format!(
                    "view3d {}: its section box runs from {} to {} mm in {}; its max is at least 10 mm past its min on each axis",
                    id,
                    disp(min[i]),
                    disp(max[i]),
                    AXES[i]
                ));
            }
        }
    }
    if let Some((lens, _)) = perspective_of(e) {
        if !(10.0..=600.0).contains(&lens) {
            return Err(format!(
                "view3d {}: a {} mm lens is no camera's; a perspective's lens is 10 to 600 mm",
                id,
                disp(lens)
            ));
        }
    }
    if let Some((eye, tgt)) = camera_of(e) {
        for (k, q) in [("eye", eye), ("target", tgt)] {
            for i in 0..3 {
                if !usable(q[i]) {
                    return Err(format!("view3d {} camera {} {}: {} is not a usable number", id, k, AXES[i], disp(q[i])));
                }
            }
        }
        if dist3(eye, tgt) <= EYE_GAP {
            return Err(format!(
                "view3d {}: its camera's eye is on its target, so it has nothing to look at; give them two points a little apart",
                id
            ));
        }
    }
    let d = Display::of(e);
    if d.silhouette > MAX_SILHOUETTE {
        return Err(format!("view3d {}: a silhouette {} px wide is wider than the 10 px one may be", id, d.silhouette));
    }
    if let Some(w) = e.get("work_plane") {
        check_work_plane(pr, id, w)?;
    }
    Ok(())
}

fn check_work_plane(pr: &Project, id: u64, w: &Value) -> R<()> {
    if let Some(o) = w.get("offset").and_then(|x| x.as_f64()) {
        if !usable(o) {
            return Err(format!("view3d {}: its work plane's offset {} isn't a length", id, disp(o)));
        }
    }
    let level = w.get("level").filter(|x| !x.is_null());
    let points = w.get("points").filter(|x| !x.is_null());
    let surface = w.get("surface").filter(|x| !x.is_null());
    let kinds = level.is_some() as u8 + points.is_some() as u8 + surface.is_some() as u8;
    if kinds == 0 {
        return Err(format!("view3d {}: a work plane needs a `level`, three `points` or a `surface`", id));
    }
    if kinds > 1 {
        return Err(format!(
            "view3d {}: a work plane is on a `level`, through three `points` or on a `surface`: only one of them",
            id
        ));
    }
    if let Some(g) = level {
        let found = g.as_str().and_then(|g| pr.find_guid(g)).filter(|l| cat_of(pr, *l) == "level");
        if found.is_none() {
            return Err(format!("view3d {}: its level isn't in the project", id));
        }
    }
    if let Some(a) = points.and_then(|x| x.as_arr()) {
        let q: Vec<[f64; 3]> = a.iter().filter_map(p3).collect();
        if q.len() == 3 {
            let ps = [q[0], q[1], q[2]];
            if ps.iter().any(|q| out_of_reach(*q)) {
                return Err(format!("view3d {}: a point of the work plane isn't a place in the project", id));
            }
            if along_a_line(&ps) {
                return Err(format!(
                    "view3d {}: the work plane's three points lie along a line: pick three that make a triangle",
                    id
                ));
            }
        }
    }
    if let Some(sf) = surface {
        if let (Some(point), Some(normal)) = (sf.get("point").and_then(p3), sf.get("normal").and_then(p3)) {
            if out_of_reach(point) {
                return Err(format!("view3d {}: the work plane's surface point isn't a place in the project", id));
            }
            if len3(normal) <= UPRIGHT {
                return Err(format!(
                    "view3d {}: the work plane's surface `normal` is the way it faces, [x, y, z], and can't be [0, 0, 0]",
                    id
                ));
            }
        }
    }
    Ok(())
}

/// The model rules of this part, checked after every command.
pub fn check(pr: &Project) -> R<()> {
    for (id, e) in &pr.elements {
        if cat(e) == "view3d" {
            check_view(pr, *id, e)?;
        }
    }
    // names: a 3D view's is a level's no more than another view's
    let levels: Vec<&str> = pr.elements.values().filter(|e| cat(e) == "level").filter_map(|e| s_of(e, "name")).collect();
    let mut seen: Vec<(&str, &str)> = Vec::new();
    for (id, e) in &pr.elements {
        let c = cat(e);
        if !NAMED_VIEWS.contains(&c) || c == "level" {
            continue;
        }
        let Some(name) = s_of(e, "name") else { continue };
        if c == "view3d" && levels.contains(&name) {
            return Err(format!("a view is named `{}`, as a level is; name it otherwise", name));
        }
        if let Some((_, other)) = seen.iter().find(|(n, _)| *n == name) {
            if c == "view3d" || *other == "view3d" {
                return Err(format!("{} {}: another view is already named `{}`", c, id, name));
            }
        }
        seen.push((name, c));
    }
    Ok(())
}

/// What `elements` shows of this part's elements beyond their own fields: a 3D view shows its own.
pub fn element_view(pr: &Project, id: u64, x: &mut Value) {
    let _ = (pr, id, x);
}
