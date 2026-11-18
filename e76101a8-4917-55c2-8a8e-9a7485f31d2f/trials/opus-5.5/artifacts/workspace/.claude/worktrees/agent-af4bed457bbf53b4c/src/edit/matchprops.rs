//! Match Properties: the type (and a component's family) of one element given to others.

use super::common::*;
use crate::json::Value;
use crate::session::Session;

pub fn run(s: &mut Session, p: &Value) -> R<Value> {
    let _ = (s, p);
    Err("match_properties: not supported here".into())
}
