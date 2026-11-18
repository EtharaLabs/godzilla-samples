//! Autosave and Recover Autosave: recovery snapshots.
//!
//! `autosave {path}` writes the project as Save writes it (the same bytes), atomically (a hidden
//! temporary file beside it, renamed over it), and changes nothing else: the project keeps its
//! path, its undo history and its unsaved state. `recover {path, project?}` opens a snapshot as
//! Open does (the same reading, the same errors, after `open: `) and starts a new history; Save
//! then goes to `project`, or needs a path without it. The snapshot's links are read relative to
//! `project` (or as given without one).

use super::common::*;
use crate::commands::params::opt_text;
use crate::json::Value;
use crate::session::Session;

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "autosave" => autosave(s, p),
        _ => recover(s, p),
    }
}

fn autosave(s: &mut Session, p: &Value) -> R<Value> {
    let path = match opt_text(p, "autosave", "path")? {
        Some(x) => x,
        None => return Err("autosave: `path` is required".into()),
    };
    let text = s.project.to_file_string();
    write_atomic(&path, text.as_bytes()).map_err(|e| format!("autosave: {}", e))?;
    Ok(crate::jobj! {"format" => "bimcraft", "path" => path})
}

fn recover(s: &mut Session, p: &Value) -> R<Value> {
    // the project to save to is read first, then the snapshot as Open reads a path
    let project = opt_text(p, "recover", "project")?;
    let path = match opt_text(p, "open", "path")? {
        Some(x) => x,
        None => return Err("open: `path` is required".into()),
    };
    let mut reply = crate::commands::basic::open_project_file(s, &path).map_err(|e| format!("open: {}", e))?;
    s.path = project;
    // its links stand relative to the project it is recovered for
    if let Value::Obj(m) = &mut reply {
        m.remove("links_not_loaded");
    }
    let failed = super::link::load_all(s);
    if !failed.is_empty() {
        reply.set("links_not_loaded", Value::Arr(failed));
    }
    Ok(reply)
}

/// Writes a file as tempfile's NamedTempFile and persist do, with their errors after the path:
/// `x: <error> at path "<the temporary file>"` when the temporary file can't be made or written,
/// `x: failed to persist temporary file: <error>` when it can't be renamed over the file.
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
        std::env::current_dir().map_err(|e| format!("{}: {}", path, e))?.join(parent)
    };
    let tmp = dir.join(format!(".tmp{}", crate::rand::alnum(6)));
    let at = |e: std::io::Error| format!("{}: {} at path {:?}", path, e, tmp.to_string_lossy());
    let mut f = std::fs::OpenOptions::new().write(true).create_new(true).mode(0o600).open(&tmp).map_err(at)?;
    if let Err(e) = f.write_all(bytes) {
        drop(f);
        let _ = std::fs::remove_file(&tmp);
        return Err(at(e));
    }
    drop(f);
    if let Err(e) = std::fs::rename(&tmp, p) {
        let _ = std::fs::remove_file(&tmp);
        return Err(format!("{}: failed to persist temporary file: {}", path, e));
    }
    Ok(())
}
