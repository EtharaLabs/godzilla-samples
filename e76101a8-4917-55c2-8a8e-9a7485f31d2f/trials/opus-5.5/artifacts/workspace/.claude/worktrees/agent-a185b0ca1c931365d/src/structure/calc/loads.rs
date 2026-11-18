//! `load_points`: NBR 5410:2004 item 9.5.2: a dwelling's lighting and general-use outlets.

use crate::json::Value;
use crate::session::Session;
use crate::structure::common::R;

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let _ = (s, p);
    Err(format!("{}: not supported here", cid))
}
