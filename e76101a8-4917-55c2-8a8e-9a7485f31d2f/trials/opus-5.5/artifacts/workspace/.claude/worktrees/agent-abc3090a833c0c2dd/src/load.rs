//! Reading a project file into a project.

use crate::json::Value;
use crate::project::Project;

/// A project file's JSON read as the original reads it (serde's message when it isn't one).
pub fn load(v: Value) -> Result<Project, String> {
    load_report(v).map(|(p, _)| p)
}

/// A project file read, and the JSON pointers of what in it the original doesn't know (and so
/// leaves out).
pub fn load_report(v: Value) -> Result<(Project, Vec<String>), String> {
    let r = crate::readers::file::read(v)?;
    let mut p = r.project;
    crate::cloud::load(&mut p)?;
    // the text and dimension types as the styles hold them (already as read; their library too)
    crate::styles::text::normalize(&mut p);
    crate::styles::text::sync_library(&mut p);
    Ok((p, r.left_out))
}
