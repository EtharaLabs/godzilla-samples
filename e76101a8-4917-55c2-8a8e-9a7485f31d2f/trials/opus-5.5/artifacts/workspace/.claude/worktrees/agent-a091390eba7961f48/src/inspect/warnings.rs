//! What `inspect` warns of, in the order the original gives it: the rooms that aren't enclosed or
//! share another's space (by id), then the lighting, outlet and switch families in use without a
//! connector (by name).

use crate::json::Value;
use crate::project::Project;
use crate::readers::common::Ctx;

pub fn warnings(pr: &Project) -> Vec<String> {
    let mut out = Vec::new();
    let cx = Ctx::new(pr);
    rooms(&cx, &mut out);
    zero_load(pr, &mut out);
    out
}

/// A room as the warnings name it: its id, number and name.
fn room_label(id: u64, v: &Value) -> String {
    let text = |k: &str| v.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string();
    format!("room {} ({} {})", id, text("number"), text("name"))
}

/// Rooms in a space another room has (redundant), and rooms nothing encloses, as their views say.
fn rooms(cx: &Ctx, out: &mut Vec<String>) {
    for id in cx.pr.ids_of("room") {
        let Some(v) = crate::readers::view::element_view(cx, id) else {
            continue;
        };
        if let Some(other) = v.get("shares_space_with").and_then(|x| x.as_u64()) {
            out.push(format!(
                "{} is in the space room {} has; two rooms can't share one, so it is unbounded: delete one, or part them with a room separation line",
                room_label(id, &v),
                other
            ));
        } else if v.get("enclosed").and_then(|x| x.as_bool()) == Some(false) {
            out.push(format!("{} is not enclosed: the walls around it no longer close", room_label(id, &v)));
        }
    }
}

/// A lighting, outlet or switch family without a connector: its placed devices count as no load.
/// A family of plan symbols only (a symbol set's: no forms) is no device and isn't warned of.
fn zero_load(pr: &Project, out: &mut Vec<String>) {
    let Some(fs) = pr.section("families") else {
        return;
    };
    let mut names: Vec<&String> = fs.keys().collect();
    names.sort();
    for name in names {
        let f = fs.get(name).unwrap();
        let cat = f.get("category").and_then(|c| c.as_str()).unwrap_or("");
        if !matches!(cat, "lighting" | "outlet" | "switch") {
            continue;
        }
        let none = |k: &str| f.get(k).and_then(|x| x.as_arr()).map(|a| a.is_empty()).unwrap_or(true);
        if !none("connectors") || (none("forms") && !none("symbols")) {
            continue;
        }
        let Some(g) = pr.lib_guid("family", name) else {
            continue;
        };
        let n = pr
            .elements
            .values()
            .filter(|e| {
                e.get("category").and_then(|c| c.as_str()) == Some("component")
                    && e.get("family").and_then(|x| x.as_str()) == Some(g.as_str())
            })
            .count();
        if n == 0 {
            continue;
        }
        let (placed, count) = if n == 1 { ("device", "counts") } else { ("devices", "count") };
        out.push(format!(
            "family `{}` has no connector, so its {} placed {} {} as a load of zero: give it one with `family` `connectors`",
            name, n, placed, count
        ));
    }
}
