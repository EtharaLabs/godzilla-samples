//! The model's rules, checked after every command that changes it.

use crate::project::Project;

pub fn check(pr: &Project) -> Result<(), String> {
    core_check(pr)?;
    crate::edit::delete::check_levels(pr)?;
    crate::cloud::check(pr)?;
    crate::media::check(pr)?;
    crate::styles::check(pr)?;
    crate::arch::check(pr)?;
    crate::structure::check(pr)?;
    crate::views::check(pr)?;
    crate::edit::check(pr)?;
    crate::readers::check(pr)?;
    Ok(())
}

fn core_check(pr: &Project) -> Result<(), String> {
    let mut level_names: Vec<String> = Vec::new();
    let mut grid_names: Vec<String> = Vec::new();
    for (id, e) in &pr.elements {
        let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("");
        match cat {
            "level" => {
                let name = e.get("name").and_then(|n| n.as_str()).unwrap_or("").to_string();
                if level_names.contains(&name) {
                    return Err(format!("level {}: another level is already named `{}`", id, name));
                }
                level_names.push(name);
                if let Some(ext) = e.get("extent").and_then(|x| x.as_arr()) {
                    let a = ext.first().and_then(crate::commands::params::point_of);
                    let b = ext.get(1).and_then(crate::commands::params::point_of);
                    if let (Some(a), Some(b)) = (a, b) {
                        if !(b[0] - a[0] > 1.0 && b[1] - a[1] > 1.0) {
                            return Err(format!(
                                "level {}: its extent runs from its south-west corner to its north-east one",
                                id
                            ));
                        }
                    }
                }
            }
            "grid" => {
                let name = e.get("name").and_then(|n| n.as_str()).unwrap_or("").to_string();
                if grid_names.contains(&name) {
                    return Err(format!("grid {}: another grid is already named `{}`", id, name));
                }
                grid_names.push(name);
                let a = e.get("start").and_then(crate::commands::params::point_of).unwrap_or([0.0, 0.0]);
                let b = e.get("end").and_then(crate::commands::params::point_of).unwrap_or([0.0, 0.0]);
                let len = ((b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2)).sqrt();
                if len <= 1.0 {
                    return Err(format!("grid {}: too short ({} mm)", id, len));
                }
            }
            _ => {}
        }
    }
    Ok(())
}
