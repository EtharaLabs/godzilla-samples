//! Fillet Arc: the corner of two straight detail lines or walls rounded by an arc.

use super::common::*;
use crate::json::Value;
use crate::session::Session;

pub fn run(s: &mut Session, p: &Value) -> R<Value> {
    let _ = (s, p);
    Err("fillet: not supported here".into())
}
