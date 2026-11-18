//! `hydrant_size`: IT 22/2025 of the CBPMESP: hydrants and hose reels.

use crate::json::Value;
use crate::session::Session;
use crate::structure::common::R;

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let _ = (s, p);
    Err(format!("{}: not supported here", cid))
}
