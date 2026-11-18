//! Point clouds: PTS, XYZ, PLY, LAS and E57 scans, and the `point_cloud` command.

use crate::json::Value;
use crate::session::Session;

/// The `point_cloud` command.
pub fn cmd_point_cloud(s: &mut Session, p: &Value) -> Result<Value, String> {
    let _ = (s, p);
    Err("point_cloud: not available".into())
}
