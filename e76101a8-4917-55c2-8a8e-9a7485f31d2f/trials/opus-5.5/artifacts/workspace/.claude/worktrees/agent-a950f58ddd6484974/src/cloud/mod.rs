//! Point clouds: PTS, XYZ, PLY, LAS and E57 scans, and the `point_cloud` command.

use crate::json::Value;
use crate::session::Session;

/// The `point_cloud` command.
pub fn cmd_point_cloud(s: &mut Session, p: &Value) -> Result<Value, String> {
    let _ = (s, p);
    Err("point_cloud: not available".into())
}

/// Runs the commands this module owns; None for the others.
pub fn dispatch(s: &mut Session, cid: &str, p: &Value) -> Option<Result<Value, String>> {
    match cid {
        "point_cloud" => Some(cmd_point_cloud(s, p)),
        _ => None,
    }
}

/// The model rules this module owns, checked after every command.
pub fn check(pr: &crate::project::Project) -> Result<(), String> {
    let _ = pr;
    Ok(())
}
