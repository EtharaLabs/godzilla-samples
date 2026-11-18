//! What opening a project reads besides its own file: each link's project (`links_not_loaded`
//! says which it couldn't read, and why) and each linked CAD drawing's file (`cads_not_reloaded`).

use crate::json::Value;
use crate::project::Project;
use std::path::Path;

/// A file named in the project, as it is found from the project's own file.
fn beside(project_path: &str, p: &str) -> String {
    let dir = Path::new(project_path).parent().map(|d| d.to_path_buf()).unwrap_or_default();
    dir.join(p).to_string_lossy().to_string()
}

/// Why a linked project can't be read, as `open` would say it (without `open: `).
pub fn link_error(path: &str) -> Option<String> {
    let bytes = match std::fs::read(path) {
        Ok(b) => b,
        Err(e) => return Some(format!("{}: {}", path, e)),
    };
    if path.to_lowercase().ends_with(".ifc") {
        return None;
    }
    let text = match String::from_utf8(bytes) {
        Ok(t) => t,
        Err(_) => return Some(format!("{}: stream did not contain valid UTF-8", path)),
    };
    let v = match crate::json::parse(&text) {
        Ok(v) => v,
        Err(e) => return Some(format!("{} is not a BIMCraft project: {}", path, e)),
    };
    let (p, _) = match crate::load::load_report(v) {
        Ok(r) => r,
        Err(e) => return Some(format!("{} is not a BIMCraft project: {}", path, e)),
    };
    if let Err(e) = super::check_opened(&p) {
        return Some(format!("{}: {}", path, e));
    }
    None
}

/// The links of a project just read whose projects couldn't be read.
pub fn reload_links(project_path: &str, pr: &Project) -> Vec<Value> {
    let mut links = Vec::new();
    for (_, e) in &pr.elements {
        if e.get("category").and_then(|c| c.as_str()) != Some("link") {
            continue;
        }
        let p = e.get("path").and_then(|x| x.as_str()).unwrap_or("");
        let name = e.get("name").and_then(|x| x.as_str()).unwrap_or("");
        if let Some(err) = link_error(&beside(project_path, p)) {
            links.push(jobj! {"error" => err, "name" => name});
        }
    }
    links
}

/// The linked drawings of a project just read, read again from their files (before the model's
/// check, as the original reads them): each one read takes the place of what the project held;
/// those that couldn't be read, and why.
pub fn reload_cads(project_path: &str, pr: &mut Project) -> Vec<Value> {
    let mut cads = Vec::new();
    let mut fresh: Vec<(String, Vec<u8>)> = Vec::new();
    if let Some(Value::Obj(m)) = pr.get("cads") {
        for (name, c) in &m.items {
            let p = match c.get("path").and_then(|x| x.as_str()) {
                Some(p) => p,
                None => continue,
            };
            match read_cad(&beside(project_path, p)) {
                Ok(Some(bytes)) => fresh.push((name.clone(), bytes)),
                Ok(None) => {}
                Err(e) => cads.push(jobj! {"cad" => name.as_str(), "error" => e}),
            }
        }
    }
    if !fresh.is_empty() {
        if let Some(Value::Obj(m)) = pr.doc.get_mut("cads") {
            for (name, bytes) in fresh {
                if let Some(c) = m.get_mut(&name) {
                    c.set("dxf", Value::Str(crate::util::base64_encode(&crate::deflate::zlib_compress(&bytes))));
                }
            }
        }
    }
    cads
}

/// A linked drawing's file read again: its DXF (None: a DWG, kept as the project holds it), or why
/// it can't be.
fn read_cad(full: &str) -> Result<Option<Vec<u8>>, String> {
    let ext = Path::new(full).extension().map(|e| e.to_string_lossy().to_lowercase()).unwrap_or_default();
    if ext != "dxf" && ext != "dwg" {
        return Err(format!("{}: a .{} file isn't a CAD drawing BIMCraft reads; it reads DXF", full, ext));
    }
    let bytes = std::fs::read(full).map_err(|e| format!("{}: {}", full, e))?;
    if ext == "dwg" {
        let version = bytes
            .get(..6)
            .and_then(|v| std::str::from_utf8(v).ok())
            .and_then(|v| v.strip_prefix("AC"))
            .and_then(|n| n.parse::<u32>().ok());
        return match version {
            Some(n) if (1015..=1032).contains(&n) => Ok(None),
            _ => Err(format!("{}: it isn't a DWG file (a DWG begins with its version, AC1015 to AC1032)", full)),
        };
    }
    super::dxf::check(&bytes)?;
    Ok(Some(bytes))
}
