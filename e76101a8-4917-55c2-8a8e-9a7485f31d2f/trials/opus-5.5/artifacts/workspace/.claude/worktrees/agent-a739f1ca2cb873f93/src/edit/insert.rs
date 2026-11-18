//! Insert from File: elements of another project brought into this one.

use super::common::*;
use crate::json::Value;
use crate::session::Session;

pub fn run(s: &mut Session, p: &Value) -> R<Value> {
    let _ = (s, p);
    Err("insert: not supported here".into())
}
