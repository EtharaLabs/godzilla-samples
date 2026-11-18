//! Pictures (PNG, JPEG) and the project's materials library: `material`, `favorite`, `library`,
//! `paint`.

pub mod favjson;
pub mod favorite;
pub mod jpeg;
pub mod library;
pub mod material;
pub mod paint;
pub mod picture;
pub mod png;
pub mod zlib;

use crate::json::Value;
use crate::session::Session;

/// Runs the commands this module owns; None for the others.
pub fn dispatch(s: &mut Session, cid: &str, p: &Value) -> Option<Result<Value, String>> {
    match cid {
        "material" => Some(material::cmd(s, p)),
        "favorite" => Some(favorite::cmd(s, p)),
        "library" => Some(library::cmd(s, p)),
        "paint" => Some(paint::cmd(s, p)),
        _ => None,
    }
}

/// The commands of this module that make an undo step even when nothing changed.
pub fn always_step(cid: &str) -> bool {
    matches!(cid, "material" | "paint")
}

/// The model rules this module owns, checked after every command.
pub fn check(pr: &crate::project::Project) -> Result<(), String> {
    let _ = pr;
    Ok(())
}
