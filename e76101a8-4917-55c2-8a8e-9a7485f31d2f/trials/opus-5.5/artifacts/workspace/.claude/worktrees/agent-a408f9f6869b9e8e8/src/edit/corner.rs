//! Trim/Extend to Corner: two walls, or two detail lines, to where they meet.

use super::common::*;
use crate::json::Value;
use crate::session::Session;

pub fn run(s: &mut Session, p: &Value) -> R<Value> {
    let _ = (s, p);
    Err("corner: not supported here".into())
}
