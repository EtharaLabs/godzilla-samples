//! `type`: Edit Type for every category, and the type each category uses by default.

use crate::json::Value;
use crate::project::Project;
use crate::session::Session;
use super::common::R;

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

/// The type a new element of a category takes when it names none: the category's own default
/// where the project has a type of that name, else the first by name.
pub fn default_type(pr: &Project, cat: &str) -> Option<String> {
    let types = super::common::types_of(pr, cat)?;
    let named = match cat {
        "column" => "Rectangular 400 x 400",
        "structuralcolumn" => "Concrete 300 x 300",
        "footing" => "Footing 1200 x 1200",
        "beam" => "Beam 200 x 500",
        "stripfooting" => "Strip 600 x 300",
        "pipe" => "PVC 50",
        "duct" => "Rectangular 400 x 300",
        "conduit" => "PVC 25",
        "cabletray" => "Perforated 100 x 50",
        "wire" => "Wire 2.5",
        "downconductor" => "Steel 8",
        "groundconductor" => "Copper 9",
        "cable" => "Cat6",
        _ => "",
    };
    if !named.is_empty() && types.contains(named) {
        return Some(named.to_string());
    }
    let mut names: Vec<&String> = types.keys().collect();
    names.sort();
    names.first().map(|n| n.to_string())
}
