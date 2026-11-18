//! Names of what the project holds by GUID, as `inspect` shows them.

use crate::project::Project;

/// The name of the library entry of this kind a GUID names.
pub fn lib(pr: &Project, kind: &str, g: &str) -> Option<String> {
    let id = pr.lib_find_guid(g)?;
    let e = pr.library.get(&id)?;
    if e.get("kind").and_then(|k| k.as_str()) != Some(kind) {
        return None;
    }
    e.get("name").and_then(|n| n.as_str()).map(|s| s.to_string())
}

/// A design option's own name (its entry is named `set: option`).
pub fn option(pr: &Project, g: &str) -> Option<String> {
    let full = lib(pr, "design-option", g)?;
    Some(match full.split_once(": ") {
        Some((_, o)) => o.to_string(),
        None => full,
    })
}
