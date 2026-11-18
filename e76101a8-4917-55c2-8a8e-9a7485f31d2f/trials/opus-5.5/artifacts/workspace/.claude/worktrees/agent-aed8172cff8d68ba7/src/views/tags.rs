//! Tags: `tag`.

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

/// What `elements` shows of this part's elements beyond their own fields.
pub fn element_view(pr: &Project, id: u64, x: &mut Value) {
    let _ = (pr, id, x);
}
