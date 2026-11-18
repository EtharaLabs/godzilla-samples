//! `symbol_set`: sets of families that are plan symbols and nothing else (AREI).

use crate::json::Value;
use crate::session::Session;
use crate::structure::common::R;

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let _ = (s, p);
    Err(format!("{}: not supported here", cid))
}
