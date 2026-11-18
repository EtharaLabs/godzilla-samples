//! Link Model and Reload Links: other projects shown in this one as references.

use super::common::*;
use crate::json::Value;
use crate::session::Session;

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let _ = (s, p);
    Err(format!("{}: not supported here", cid))
}
