//! Link Model and Reload Links: other projects shown in this one as references.
//!
//! A link is an element, `{guid, category: "link", name, path, at, angle?}` (`angle` only when it
//! isn't 0), its `path` kept as given: a relative one is read relative to the project's file (to
//! where the program runs while the project has none). What was read of a file is held beside
//! the project, not in its file, by the path as the links give it (two links of one path show
//! one reading): `link` reads it, `reload` reads it again (what was read stays where the file
//! can't be read), and opening a project reads every link's anew, saying which it couldn't
//! (`links_not_loaded`). `elements` shows the count of a link's file's elements as last read
//! (`null` and `loaded: false` until it is).

use super::common::*;
use crate::commands::params::{opt_num, opt_point, opt_text};
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;
use std::cell::RefCell;
use std::collections::HashMap;

thread_local! {
    /// What was read of each linked file: its elements' count, by the project (its uid) and the
    /// path as the links give it.
    static LOADED: RefCell<HashMap<(String, String), usize>> = RefCell::new(HashMap::new());
}

/// Which project the readings are of: its uid (a new project has a new one).
fn key(pr: &Project) -> String {
    pr.doc.get("uid").map(|u| u.to_compact()).unwrap_or_default()
}

fn set_loaded(pr: &Project, path: &str, n: usize) {
    LOADED.with(|m| {
        m.borrow_mut().insert((key(pr), path.to_string()), n);
    });
}

fn get_loaded(pr: &Project, path: &str) -> Option<usize> {
    LOADED.with(|m| m.borrow().get(&(key(pr), path.to_string())).cloned())
}

fn forget_all(pr: &Project) {
    let k = key(pr);
    LOADED.with(|m| m.borrow_mut().retain(|(u, _), _| *u != k));
}

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "link" => link(s, p),
        _ => reload(s, p),
    }
}

// ---------------------------------------------------------------- reading a project file

/// Reads a project file (or an IFC file) as Open reads it, into a project of its own; the error
/// is what Open says after `open: ` (`x: No such file or directory (os error 2)`, `x is not a
/// BIMCraft project: …`), the path as given.
pub fn read_project(path: &str) -> Result<Project, String> {
    let low = path.to_lowercase();
    if low.ends_with(".ifc") {
        let mut tmp = Session::new();
        crate::ifc::import::import(&mut tmp, path)?;
        return Ok(tmp.project);
    }
    let text = std::fs::read_to_string(path).map_err(|e| format!("{}: {}", path, e))?;
    let v = crate::json::parse(&text).map_err(|e| format!("{} is not a BIMCraft project: {}", path, e))?;
    let proj = crate::load::load(v).map_err(|e| format!("{} is not a BIMCraft project: {}", path, e))?;
    crate::cloud::check(&proj).map_err(|e| format!("{}: {}", path, e))?;
    Ok(proj)
}

/// Where a link's file is: its path as given when absolute or when the project has no file,
/// else beside the project's file (`sub/p.bimcraft` and `x.bimcraft` read `sub/x.bimcraft`).
pub fn resolve_path(project_path: Option<&str>, path: &str) -> String {
    let p = std::path::Path::new(path);
    if p.is_absolute() {
        return path.to_string();
    }
    match project_path {
        Some(pp) => match std::path::Path::new(pp).parent() {
            Some(dir) => dir.join(p).to_string_lossy().to_string(),
            None => path.to_string(),
        },
        None => path.to_string(),
    }
}

/// Reads a link's file: its elements' count, or why it couldn't be read.
fn read_link(project_path: Option<&str>, path: &str) -> Result<usize, String> {
    read_project(&resolve_path(project_path, path)).map(|pr| pr.elements.len())
}

/// The links of the project, in id order: (id, name, path).
fn links(pr: &Project) -> Vec<(u64, String, String)> {
    pr.elements
        .iter()
        .filter(|(_, e)| cat_of(e) == "link")
        .map(|(id, e)| {
            let n = e.get("name").and_then(|x| x.as_str()).unwrap_or("").to_string();
            let p = e.get("path").and_then(|x| x.as_str()).unwrap_or("").to_string();
            (*id, n, p)
        })
        .collect()
}

/// Reads every link's file anew, as opening a project does; the ones it couldn't, `{error,
/// name}`, in id order.
pub fn load_all(s: &Session) -> Vec<Value> {
    forget_all(&s.project);
    let mut failed = Vec::new();
    for (_, name, path) in links(&s.project) {
        match read_link(s.path.as_deref(), &path) {
            Ok(n) => set_loaded(&s.project, &path, n),
            Err(e) => failed.push(crate::jobj! {"error" => e, "name" => name}),
        }
    }
    failed
}

/// What `elements` shows of a link beyond its fields: `elements`, the count of its file's
/// elements as last read (null when it hasn't been), and `loaded`.
pub fn element_view(pr: &Project, e: &mut Value) {
    let path = e.get("path").and_then(|x| x.as_str()).unwrap_or("").to_string();
    let n = get_loaded(pr, &path);
    e.set("elements", n.map(|n| Value::u(n as u64)).unwrap_or(Value::Null));
    e.set("loaded", Value::Bool(n.is_some()));
}

// ---------------------------------------------------------------- link

fn file_stem(path: &str) -> String {
    std::path::Path::new(path)
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_default()
}

fn link(s: &mut Session, p: &Value) -> R<Value> {
    let path = match opt_text(p, "link", "path")? {
        Some(x) => x,
        None => return Err("link: `path` is required".into()),
    };
    // the file is read before the rest is looked at
    let n = read_link(s.path.as_deref(), &path).map_err(|e| format!("link: {}", e))?;
    let name = opt_text(p, "link", "name")?;
    let at = opt_point(p, "link", "at")?.unwrap_or([0.0, 0.0]);
    let angle = opt_num(p, "link", "angle")?.unwrap_or(0.0);
    let name = name.unwrap_or_else(|| file_stem(&path));
    let pr = &mut s.project;
    let id = pr.alloc_id();
    let mut e = crate::jobj! {
        "guid" => crate::rand::guid(),
        "category" => "link",
        "name" => name.clone(),
        "path" => path.clone(),
        "at" => Value::Arr(vec![Value::f(at[0]), Value::f(at[1])]),
    };
    if angle != 0.0 {
        e.set("angle", Value::f(angle));
    }
    pr.elements.insert(id, e);
    set_loaded(pr, &path, n);
    Ok(crate::jobj! {"elements" => n, "id" => id, "name" => name})
}

// ---------------------------------------------------------------- reload

fn reload(s: &mut Session, p: &Value) -> R<Value> {
    let only: Option<u64> = match p.get("id") {
        None | Some(Value::Null) => None,
        Some(v) => {
            let bad = || format!("reload: `id` must be an element id or GUID, got {}", v.to_compact());
            let id = match v {
                Value::Num(n) => num_id(n).ok_or_else(bad)?,
                Value::Str(t) => {
                    let t = t.trim();
                    if let Ok(id) = t.parse::<u64>() {
                        id
                    } else if let Some(g) = strict_guid(t) {
                        match s.project.find_guid(&g) {
                            Some(id) => id,
                            None => return Err(format!("reload: element {} is not a link", t)),
                        }
                    } else {
                        return Err(bad());
                    }
                }
                _ => return Err(bad()),
            };
            if s.project.category(id) != Some("link") {
                return Err(format!("reload: element {} is not a link", id));
            }
            Some(id)
        }
    };
    let mut reloaded = Vec::new();
    let mut failed = Vec::new();
    for (id, name, path) in links(&s.project) {
        if only.map(|o| o != id).unwrap_or(false) {
            continue;
        }
        match read_link(s.path.as_deref(), &path) {
            Ok(n) => {
                set_loaded(&s.project, &path, n);
                reloaded.push(Value::s(&name));
            }
            // what was read before stays
            Err(e) => failed.push(crate::jobj! {"error" => e, "name" => name}),
        }
    }
    Ok(crate::jobj! {"failed" => Value::Arr(failed), "reloaded" => Value::Arr(reloaded)})
}

// ---------------------------------------------------------------- the model's rules

/// Each link has a name and a path of a file, up to 256 characters, an angle within a turn either
/// way, and a name of its own among the links.
pub fn check(pr: &Project) -> R<()> {
    let mut names: Vec<String> = Vec::new();
    for (id, e) in &pr.elements {
        if cat_of(e) != "link" {
            continue;
        }
        let name = e.get("name").and_then(|x| x.as_str()).unwrap_or("");
        let path = e.get("path").and_then(|x| x.as_str()).unwrap_or("");
        if name.trim().is_empty() || name.chars().count() > 256 || path.is_empty() || path.chars().count() > 256 {
            return Err(format!("link {}: a link needs a name and the path of a file, up to 256 characters", id));
        }
        if let Some(a) = e.get("angle").and_then(|x| x.as_f64()) {
            if !(-360.0..=360.0).contains(&a) {
                return Err(format!("link {}: its angle {}° isn't between -360° and 360°", id, a));
            }
        }
        if names.iter().any(|n| n == name) {
            return Err(format!("link {}: another link is already named `{}`", id, name));
        }
        names.push(name.to_string());
    }
    Ok(())
}
