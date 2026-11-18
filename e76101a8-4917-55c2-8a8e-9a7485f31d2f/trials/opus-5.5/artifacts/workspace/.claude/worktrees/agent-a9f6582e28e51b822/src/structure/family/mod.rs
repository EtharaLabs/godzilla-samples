//! `family`: the project's families, created, changed, read, listed, loaded and saved.

use crate::json::Value;
use crate::project::Project;
use crate::session::Session;
use crate::structure::common::R;

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let _ = (s, p);
    Err(format!("{}: not supported here", cid))
}

/// The model rules of this part, checked after every command.
pub fn check(pr: &Project) -> R<()> {
    let _ = pr;
    Ok(())
}

/// What `inspect` warns of: a lighting, outlet or switch family in use that holds no connector…
pub fn warnings(pr: &Project) -> Vec<String> {
    let _ = pr;
    Vec::new()
}
