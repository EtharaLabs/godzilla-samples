//! A dimension's constraints, text and value: `dimension_constraint`, `dimension_text`, `dimension_value`.

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

/// Run after every command that changes the model, before the check (`Session::execute`): each
/// constrained dimension is solved again and what it measures to moved to keep it; Err (the
/// command refused, nothing changed) where it can't be kept.
pub fn keep(pr: &mut Project) -> R<()> {
    let _ = pr;
    Ok(())
}
