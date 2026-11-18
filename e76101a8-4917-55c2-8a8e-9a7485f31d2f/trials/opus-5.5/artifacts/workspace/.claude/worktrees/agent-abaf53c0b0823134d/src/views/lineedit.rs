//! Editing detail lines: `join_polyline`, `explode`, `vertex`, `convert_spline`, `offset`, `trim_extend`.

#![allow(unused_imports)]

use super::common::*;
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let _ = (s, p);
    Err(format!("{}: not supported here", cid))
}

/// The model rules of this part, checked after every command.
pub fn check(pr: &Project) -> R<()> {
    let _ = pr;
    Ok(())
}
