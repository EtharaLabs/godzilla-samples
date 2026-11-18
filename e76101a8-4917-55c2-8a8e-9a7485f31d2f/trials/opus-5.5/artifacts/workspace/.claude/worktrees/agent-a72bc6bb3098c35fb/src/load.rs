//! Reading a project file into a project.

use crate::json::Value;
use crate::project::Project;

pub fn load(v: Value) -> Result<Project, String> {
    if !matches!(v, Value::Obj(_)) {
        return Err(format!("invalid type: {}, expected struct ProjectFile", v.kind_name()));
    }
    Ok(Project::from_value(v))
}
