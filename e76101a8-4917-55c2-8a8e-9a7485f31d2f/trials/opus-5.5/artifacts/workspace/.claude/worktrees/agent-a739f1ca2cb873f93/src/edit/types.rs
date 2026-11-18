//! Delete Type and Rename Type: a type of a category, or a family and its types.

use super::common::*;
use crate::json::Value;
use crate::session::Session;

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let _ = (s, p);
    Err(format!("{}: not supported here", cid))
}
