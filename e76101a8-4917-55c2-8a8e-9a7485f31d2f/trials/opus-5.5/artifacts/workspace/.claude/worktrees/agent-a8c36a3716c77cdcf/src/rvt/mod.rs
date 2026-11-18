//! Revit files (.rvt, .rfa, .rte, .rft), read only: `info`, and import as a project.

pub mod atom;
pub mod basic;
pub mod build;
pub mod bytes;
pub mod cats;
pub mod cfb;
pub mod columns;
pub mod components;
pub mod container;
pub mod curves;
pub mod data;
pub mod deflate;
pub mod doc;
pub mod drop;
pub mod elemtable;
pub mod floors;
pub mod gzip;
pub mod import;
pub mod info;
pub mod inventory;
pub mod levels;
pub mod materials;
pub mod mep;
pub mod notes;
pub mod openings;
pub mod plan;
pub mod records;
pub mod roofs;
pub mod rooms;
pub mod schema;
pub mod sketch;
pub mod types;
pub mod walls;

use crate::json::Value;
use crate::session::Session;

/// Whether a path names a Revit file, by its extension (any case).
pub fn is_revit_path(path: &str) -> bool {
    let low = path.to_lowercase();
    low.ends_with(".rvt") || low.ends_with(".rfa") || low.ends_with(".rte") || low.ends_with(".rft")
}

/// The file opened, its `BasicFileInfo` read and its Atom entry: what both `info` and the import
/// need first. Errors are whole messages, the path first.
pub struct Opened {
    pub container: container::Container,
    pub basic: basic::BasicInfo,
    pub atom: atom::Atom,
}

pub fn open(path: &str) -> Result<Opened, String> {
    let c = container::open(path)?;
    if !c.has("BasicFileInfo") {
        return Err(format!(
            "{}: this is a Compound File but not a Revit one: it has no BasicFileInfo stream (its streams: {})",
            path,
            c.names().join(", ")
        ));
    }
    let bfi = c.read("BasicFileInfo").map_err(|e| format!("{}: {}", path, e))?.unwrap_or_default();
    let basic = basic::parse(&bfi).map_err(|e| format!("{}: {}", path, e))?;
    let part_atom = c.read("PartAtom").ok().flatten();
    let project_info = c.read("ProjectInformation").ok().flatten();
    let atom = atom::read(part_atom.as_deref(), project_info.as_deref());
    Ok(Opened { container: c, basic, atom })
}

/// What `bimcraft-cli info x.rvt` prints (before its keys are sorted), or the error line it prints.
pub fn info(path: &str) -> Result<Value, String> {
    let o = open(path)?;
    let elements = match doc::read(&o.container, o.basic.release) {
        Ok(d) => info::elements(&d),
        Err(e) => jobj! {"error" => e},
    };
    Ok(info::build(&o.basic, &o.atom, elements))
}

/// The name a project imported from a file takes: the file's title, else the file's stem.
fn project_name(path: &str, atom: &atom::Atom) -> String {
    if let Some(t) = &atom.title {
        return t.clone();
    }
    let p = std::path::Path::new(path);
    p.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default()
}

/// Imports a Revit file as a new project into the session (what `run x.rvt`, `convert x.rvt`
/// and the MCP server's `open` do); returns the reply `run` prints. An error is the whole message
/// to print (the path first; no `open: ` before it).
pub fn import(s: &mut Session, path: &str) -> Result<Value, String> {
    let o = open(path)?;
    let d = doc::read(&o.container, o.basic.release).map_err(|e| format!("{}: {}", path, e))?;
    let name = project_name(path, &o.atom);
    let (pr, notes) = import::run(&d, &name);
    import::check_types(&pr).map_err(|e| format!("{}: {}", path, e))?;
    let reply = import::reply(&pr, &notes, o.basic.release, &name, path);
    s.project = pr;
    s.path = None;
    s.undo.clear();
    s.redo.clear();
    Ok(reply)
}
