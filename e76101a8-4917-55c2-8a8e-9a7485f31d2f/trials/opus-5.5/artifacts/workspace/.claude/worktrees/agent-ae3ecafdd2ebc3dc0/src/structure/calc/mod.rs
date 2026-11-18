//! The sizing calculators: pure functions of their parameters that change nothing.

pub mod circuit;
pub mod conduit_fill;
pub mod drainage;
pub mod hydrant;
pub mod loads;
pub mod storm;
pub mod water;

use crate::json::Value;
use crate::session::Session;
use super::common::R;

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "circuit" => circuit::run(s, cid, p),
        "conduit_fill" => conduit_fill::run(s, cid, p),
        "load_points" => loads::run(s, cid, p),
        "drain_size" | "vent_size" => drainage::run(s, cid, p),
        "water_size" => water::run(s, cid, p),
        "storm_size" => storm::run(s, cid, p),
        "hydrant_size" => hydrant::run(s, cid, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}
