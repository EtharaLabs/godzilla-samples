//! Split: a wall, or a detail line of any shape, in two.

use super::common::*;
use crate::json::Value;
use crate::session::Session;

pub fn run(s: &mut Session, p: &Value) -> R<Value> {
    let _ = (s, p);
    Err("split: not supported here".into())
}
