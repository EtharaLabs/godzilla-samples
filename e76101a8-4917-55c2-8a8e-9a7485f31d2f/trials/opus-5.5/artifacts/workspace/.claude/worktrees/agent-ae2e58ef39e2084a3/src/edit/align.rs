//! Align: an element's picked line onto a reference, and the padlock that keeps it there.

use super::common::*;
use crate::json::Value;
use crate::session::Session;

pub fn run(s: &mut Session, p: &Value) -> R<Value> {
    let _ = (s, p);
    Err("align: not supported here".into())
}
