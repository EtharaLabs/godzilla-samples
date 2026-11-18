//! Reading IFC2x3 and IFC4 files into a project.

use crate::json::Value;
use crate::session::Session;

/// Imports an IFC file as a new project into the session (what `run x.ifc`, `convert` and
/// `open` do); returns the reply `run` prints. An error is what follows `open: `.
pub fn import(s: &mut Session, path: &str) -> Result<Value, String> {
    let _ = s;
    Err(format!("{}: IFC import is not available", path))
}
