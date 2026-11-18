//! Modify: an element's fields as `elements` shows them, of one element or several.

use super::common::*;
use crate::json::Value;
use crate::session::Session;

pub fn run(s: &mut Session, p: &Value) -> R<Value> {
    let _ = (s, p);
    Err("modify: not supported here".into())
}
