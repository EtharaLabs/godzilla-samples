//! Move, Copy, Rotate and Mirror: elements of every category, and the walls joined to them.

use super::common::*;
use crate::json::Value;
use crate::session::Session;

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let _ = (s, p);
    Err(format!("{}: not supported here", cid))
}
