//! Projects, history, levels and grids.

use super::params::*;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "new" => cmd_new(s, p),
        "open" => {
            let path = match opt_text(p, "open", "path")? {
                Some(x) => x,
                None => return Err("open: `path` is required".into()),
            };
            // the script's `open` reads a project file whatever its extension: a Revit file is
            // imported only by `run x.rvt`, `convert` and the MCP server's `open`
            open_project_file(s, &path).map_err(|e| format!("open: {}", e))
        }
        "save" => cmd_save(s, p),
        "undo" => cmd_undo(s, p, true),
        "redo" => cmd_undo(s, p, false),
        "level" => cmd_level(s, p),
        "grid" => cmd_grid(s, p),
        "delete" => cmd_delete(s, p),
        "inspect" => Ok(crate::inspect::inspect(s)),
        "elements" => crate::inspect::elements(s, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

// ---------------------------------------------------------------- projects

fn cmd_new(s: &mut Session, p: &Value) -> R<Value> {
    let name = opt_text(p, "new", "name")?;
    let lang = opt_text(p, "new", "language")?.unwrap_or_else(|| "en".into()).to_lowercase();
    if !crate::project::LANGS.contains(&lang.as_str()) {
        return Err(format!("new: `{}` is no language here; use en, pt, es or sv", lang));
    }
    let mut proj = Project::new(&lang);
    if let Some(n) = name {
        proj.doc.insert("name", Value::Str(n));
    }
    s.project = proj;
    s.path = None;
    s.undo.clear();
    s.redo.clear();
    Ok(jobj! {"language" => lang, "name" => s.project.name()})
}

/// Opens a project, or imports a file by its extension.
pub fn open_path(s: &mut Session, path: &str) -> Result<Value, String> {
    let low = path.to_lowercase();
    if crate::rvt::is_revit_path(path) {
        return crate::rvt::import(s, path);
    }
    let _ = low;
    open_project_file(s, path)
}

/// Opens a project file (or an IFC file), whatever the extension says otherwise.
pub fn open_project_file(s: &mut Session, path: &str) -> Result<Value, String> {
    let low = path.to_lowercase();
    if low.ends_with(".ifc") {
        return Err(format!("{}: IFC import is not available", path));
    }
    let text = std::fs::read_to_string(path).map_err(|e| format!("{}: {}", path, e))?;
    let v = crate::json::parse(&text).map_err(|e| format!("{} is not a BIMCraft project: {}", path, e))?;
    let proj = crate::load::load(v).map_err(|e| format!("{} is not a BIMCraft project: {}", path, e))?;
    s.project = proj;
    s.path = Some(path.to_string());
    s.undo.clear();
    s.redo.clear();
    Ok(jobj! {"name" => s.project.name(), "path" => path})
}

fn cmd_save(s: &mut Session, p: &Value) -> R<Value> {
    let path = match opt_text(p, "save", "path")? {
        Some(x) => x,
        None => match &s.path {
            Some(x) => x.clone(),
            None => return Err("save: `path` is required: this project hasn't been saved yet".into()),
        },
    };
    let low = path.to_lowercase();
    if low.ends_with(".ifc") {
        let text = crate::ifc::export::export(&s.project, &path);
        std::fs::write(&path, text).map_err(|e| format!("save: {}: {}", path, e))?;
        return Ok(jobj! {"format" => "IFC4", "path" => path});
    }
    let text = s.project.to_file_string();
    write_atomic(&path, text.as_bytes()).map_err(|e| format!("save: {}: {}", path, e))?;
    s.path = Some(path.clone());
    Ok(jobj! {"format" => "bimcraft", "path" => path})
}

/// Writes a file as tempfile and persist do: a hidden file beside it, renamed over it.
pub fn write_atomic(path: &str, bytes: &[u8]) -> Result<(), String> {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    let p = std::path::Path::new(path);
    let parent = match p.parent() {
        Some(d) if !d.as_os_str().is_empty() => d.to_path_buf(),
        _ => std::path::PathBuf::from(""),
    };
    let dir = if parent.is_absolute() {
        parent
    } else {
        std::env::current_dir().map_err(|e| e.to_string())?.join(parent)
    };
    let tmp = dir.join(format!(".tmp{}", crate::rand::alnum(6)));
    let mut f = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&tmp)
        .map_err(|e| format!("{} at path {:?}", e, tmp.to_string_lossy()))?;
    f.write_all(bytes).map_err(|e| format!("{} at path {:?}", e, tmp.to_string_lossy()))?;
    drop(f);
    std::fs::rename(&tmp, p).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        format!("{} at path {:?}", e, tmp.to_string_lossy())
    })?;
    Ok(())
}

fn cmd_undo(s: &mut Session, p: &Value, undo: bool) -> R<Value> {
    let cmd = if undo { "undo" } else { "redo" };
    let avail = if undo { s.undo.len() } else { s.redo.len() };
    if avail == 0 {
        return Err(if undo { "nothing to undo".into() } else { "nothing to redo".into() });
    }
    let count = match get(p, "count") {
        None => 1,
        Some(v) => match v.as_f64() {
            Some(c) if c >= 1.0 && c <= avail as f64 && c.fract() == 0.0 => c as usize,
            _ => {
                return Err(format!(
                    "`count` must be from 1 to {}, the steps there are to {}",
                    avail, cmd
                ))
            }
        },
    };
    let mut label = String::new();
    for _ in 0..count {
        if undo {
            let step = s.undo.pop().unwrap();
            s.project = step.before.clone();
            label = step.label.clone();
            s.redo.push(step);
        } else {
            let step = s.redo.pop().unwrap();
            s.project = step.after.clone();
            label = step.label.clone();
            s.undo.push(step);
        }
    }
    let mut m = Map::new();
    m.insert("count", Value::u(count as u64));
    m.insert(if undo { "undone" } else { "redone" }, Value::Str(label));
    Ok(Value::Obj(m))
}

// ---------------------------------------------------------------- levels and grids

pub fn level_ids_sorted(pr: &Project) -> Vec<u64> {
    let mut ids = pr.ids_of("level");
    ids.sort_by(|a, b| {
        let ea = pr.el(*a).and_then(|e| e.get("elevation")).and_then(|x| x.as_f64()).unwrap_or(0.0);
        let eb = pr.el(*b).and_then(|e| e.get("elevation")).and_then(|x| x.as_f64()).unwrap_or(0.0);
        ea.partial_cmp(&eb).unwrap_or(std::cmp::Ordering::Equal).then(a.cmp(b))
    });
    ids
}

pub fn level_word(lang: &str) -> &'static str {
    match lang {
        "pt" => "Nível",
        "es" => "Nivel",
        "sv" => "Nivå",
        "cs" => "Podlaží",
        "fr" => "Niveau",
        "nl" => "Niveau",
        "de" => "Ebene",
        "it" => "Livello",
        _ => "Level",
    }
}

fn cmd_level(s: &mut Session, p: &Value) -> R<Value> {
    let elevation = req_num(p, "level", "elevation")?;
    let name = opt_text(p, "level", "name")?;
    let extent = match get(p, "extent") {
        None => None,
        Some(v) => {
            let pts = points_of(v).ok_or_else(|| "level: `extent` [[x, y], …] is required".to_string())?;
            if pts.len() != 2 {
                return Err("level: `extent` is two corners, [[x, y], [x, y]]: south-west, then north-east".into());
            }
            Some(pts)
        }
    };
    let pr = &mut s.project;
    let name = match name {
        Some(n) => n,
        None => {
            let word = level_word(&pr.language());
            let names: Vec<String> = pr
                .ids_of("level")
                .iter()
                .filter_map(|id| pr.el(*id).and_then(|e| e.get("name")).and_then(|n| n.as_str()).map(|s| s.to_string()))
                .collect();
            let mut n = names.len() + 1;
            loop {
                let cand = format!("{} {}", word, n);
                if !names.contains(&cand) {
                    break cand;
                }
                n += 1;
            }
        }
    };
    let id = pr.alloc_id();
    let mut e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => "level",
        "name" => name.clone(),
        "elevation" => elevation,
        "view_range" => jobj!{"top" => Value::Null, "cut" => 1200.0, "bottom" => 0.0, "depth" => 0.0},
    };
    if let Some(x) = extent {
        e.set("extent", Value::Arr(vec![x[0].into(), x[1].into()]));
    }
    pr.elements.insert(id, e);
    Ok(jobj! {"id" => id, "name" => name})
}

fn is_number_name(s: &str) -> Option<u64> {
    if !s.is_empty() && s.chars().all(|c| c.is_ascii_digit()) {
        s.parse().ok()
    } else {
        None
    }
}

fn cmd_grid(s: &mut Session, p: &Value) -> R<Value> {
    let start = req_point(p, "grid", "start")?;
    let end = req_point(p, "grid", "end")?;
    let name = opt_text(p, "grid", "name")?;
    let pr = &mut s.project;
    let grids = pr.ids_of("grid");
    let names: Vec<String> = grids
        .iter()
        .filter_map(|id| pr.el(*id).and_then(|e| e.get("name")).and_then(|n| n.as_str()).map(|s| s.to_string()))
        .collect();
    let name = match name {
        Some(n) => n,
        None => {
            let last = names.last().cloned().unwrap_or_default();
            let letter = {
                let mut c = last.chars();
                match (c.next(), c.next()) {
                    (Some(ch), None) if ch.is_ascii_uppercase() && ch != 'Z' => Some(ch),
                    _ => None,
                }
            };
            if let Some(ch) = letter {
                let mut ch = (ch as u8 + 1) as char;
                loop {
                    let cand = ch.to_string();
                    if !names.contains(&cand) || ch == 'Z' {
                        break cand;
                    }
                    ch = (ch as u8 + 1) as char;
                }
            } else {
                let mut n = names.iter().filter_map(|n| is_number_name(n)).max().unwrap_or(0) + 1;
                loop {
                    let cand = n.to_string();
                    if !names.contains(&cand) {
                        break cand;
                    }
                    n += 1;
                }
            }
        }
    };
    let id = pr.alloc_id();
    pr.elements.insert(
        id,
        jobj! {
            "guid" => crate::rand::guid(),
            "category" => "grid",
            "name" => name.clone(),
            "start" => start,
            "end" => end,
        },
    );
    Ok(jobj! {"id" => id, "name" => name})
}

// ---------------------------------------------------------------- delete

fn cmd_delete(s: &mut Session, p: &Value) -> R<Value> {
    let ids: Vec<u64> = match get(p, "ids").and_then(|v| v.as_arr()) {
        Some(a) => a.iter().filter_map(id_of).collect(),
        None => return Err("delete: `ids` [id, …] is required".into()),
    };
    let pr = &mut s.project;
    let mut deleted = Vec::new();
    for id in ids {
        if pr.elements.remove(&id).is_some() {
            deleted.push(id);
        }
    }
    Ok(jobj! {"deleted" => deleted})
}

// ---------------------------------------------------------------- reading files

pub fn info(path: &str) -> Result<Value, String> {
    if crate::rvt::is_revit_path(path) {
        return crate::rvt::info(path);
    }
    let mut s = Session::new();
    open_path(&mut s, path).map_err(|e| format!("open: {}", e))?;
    let mut v = crate::inspect::inspect(&s);
    v.set("path", Value::s(path));
    Ok(v)
}

pub fn build_sample(_s: &mut Session) -> Result<(), String> {
    Err("the sample house is not available".into())
}

pub fn build_highrise(_s: &mut Session, _storeys: u64) -> Result<Value, String> {
    Err("the highrise sample is not available".into())
}
