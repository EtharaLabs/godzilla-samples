//! Dimensions in a 3D view: `dimension_3d`.
//!
//! A `dimension3d` keeps its `view` (a GUID), two `refs` ({at: [x, y, z]} a point of the model, or
//! {at, edge: [[x, y, z], [x, y, z]]} a point on an edge), the point its line passes through (`at`)
//! and its dimension `type` (a GUID). They hold places in space, not elements.

use super::common::*;
use super::view3d::{self, de};
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

/// A reference: a point, on an edge or not.
#[derive(Clone, Copy, Debug)]
pub struct Ref3 {
    pub at: [f64; 3],
    pub edge: Option<[[f64; 3]; 2]>,
}

impl Ref3 {
    pub fn to_value(&self) -> Value {
        match self.edge {
            None => jobj! {"at" => self.at},
            Some(e) => jobj! {"at" => self.at, "edge" => Value::Arr(vec![Value::from(e[0]), Value::from(e[1])])},
        }
    }
    pub fn of(v: &Value) -> Option<Ref3> {
        let at = view3d::p3(v.get("at")?)?;
        let edge = match v.get("edge") {
            Some(Value::Arr(a)) if a.len() == 2 => Some([view3d::p3(&a[0])?, view3d::p3(&a[1])?]),
            _ => None,
        };
        Some(Ref3 { at, edge })
    }
}

/// The foot of the perpendicular from `p` to the line through an edge.
pub fn foot(p: [f64; 3], e: [[f64; 3]; 2]) -> [f64; 3] {
    let d = view3d::sub3(e[1], e[0]);
    let l2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2];
    if l2 == 0.0 {
        return e[0];
    }
    let w = view3d::sub3(p, e[0]);
    let t = (w[0] * d[0] + w[1] * d[1] + w[2] * d[2]) / l2;
    [e[0][0] + d[0] * t, e[0][1] + d[1] * t, e[0][2] + d[2] * t]
}

/// The two ends of what a dimension measures: between two points straight across; to an edge,
/// square to its line.
pub fn ends(a: &Ref3, b: &Ref3) -> ([f64; 3], [f64; 3]) {
    if let Some(e) = b.edge {
        (a.at, foot(a.at, e))
    } else if let Some(e) = a.edge {
        (foot(b.at, e), b.at)
    } else {
        (a.at, b.at)
    }
}

pub fn length(a: &Ref3, b: &Ref3) -> f64 {
    let (p, q) = ends(a, b);
    view3d::dist3(p, q)
}

/// A length as the original reports it, to the hundredth.
pub fn r2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

/// The project's dimension types by name, sorted.
pub fn dimension_type_names(pr: &Project) -> Vec<String> {
    let mut names: Vec<String> = match pr.section("dimension_types") {
        Some(m) => m.keys().cloned().collect(),
        None => pr
            .library
            .values()
            .filter(|e| s_of(e, "kind") == Some("dimension-type"))
            .filter_map(|e| s_of(e, "name").map(|s| s.to_string()))
            .collect(),
    };
    names.sort();
    names.dedup();
    names
}

/// The type an aligned dimension starts in: `Diagonal - 2.5mm Arial`, else the first there is.
pub fn default_type(pr: &Project) -> Option<String> {
    let names = dimension_type_names(pr);
    if names.iter().any(|n| n == "Diagonal - 2.5mm Arial") {
        return Some("Diagonal - 2.5mm Arial".to_string());
    }
    names.into_iter().next()
}

fn no_type(pr: &Project, id: u64, name: &str) -> String {
    format!(
        "dimension3d {}: there's no dimension type `{}` (there are: {})",
        id,
        name,
        dimension_type_names(pr).join(", ")
    )
}

const REFS: &str = "`refs` is two references [{at: [x, y, z], edge?: [[x, y, z], [x, y, z]]}, …]";

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    if cid != "dimension_3d" {
        return Err(format!("{}: not supported here", cid));
    }
    let cmd = "dimension_3d";
    let t = view3d::target(&s.project, cmd, p, "a dimension of points and edges in space goes in a 3D view")?;
    let refs = match get(p, "refs") {
        Some(Value::Arr(a)) if a.len() == 2 => a.clone(),
        _ => return Err(format!("{}: {}", cmd, REFS)),
    };
    let mut rs = Vec::new();
    for v in &refs {
        let (at, edge) = de::ref3(v).map_err(|e| format!("{}: a ref is {{at: [x, y, z], edge?}}: {}", cmd, e))?;
        let r = Ref3 { at, edge };
        let mut pts = vec![r.at];
        if let Some(e) = r.edge {
            pts.push(e[0]);
            pts.push(e[1]);
        }
        if pts.iter().any(|q| q.iter().any(|x| !(x.abs() <= view3d::REACH))) {
            return Err(format!(
                "{}: a ref's points must be [x, y, z] in mm within ±1000000000, got {}",
                cmd,
                v.clone().sorted().to_compact()
            ));
        }
        rs.push(r);
    }
    let at = match get(p, "at") {
        None => return Err(format!("{}: `at` [x, y, z] is required", cmd)),
        Some(v) => point3_of(v)
            .ok_or_else(|| format!("{}: `at` must be a point [x, y, z] in mm, got {}", cmd, v.clone().sorted().to_compact()))?,
    };
    let ty = crate::commands::params::opt_text(p, cmd, "type")?;
    let pr = &mut s.project;
    let (a, b) = (rs[0], rs[1]);
    // what the check would refuse, said for the element it would be
    let id_next = {
        let mut probe = pr.next_id();
        while pr.elements.contains_key(&probe) {
            probe += 1;
        }
        // the default 3D view comes first when it is made now
        if t.is_none() {
            probe += 1;
            while pr.elements.contains_key(&probe) {
                probe += 1;
            }
        }
        probe
    };
    check_refs(id_next, &a, &b)?;
    let ty = match ty {
        Some(n) => n,
        None => default_type(pr).unwrap_or_default(),
    };
    let Some(ty_guid) = pr.lib_guid("dimension-type", &ty) else {
        return Err(no_type(pr, id_next, &ty));
    };
    let view = match t {
        Some(v) => v,
        None => view3d::make_default_view(pr),
    };
    let id = pr.alloc_id();
    let e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => "dimension3d",
        "view" => guid(pr, view),
        "refs" => Value::Arr(vec![a.to_value(), b.to_value()]),
        "at" => at,
        "type" => ty_guid,
    };
    pr.elements.insert(id, e);
    Ok(jobj! {"id" => id, "length" => r2(length(&a, &b)), "view" => view})
}

/// The edges it measures to have length, and it measures something.
fn check_refs(id: u64, a: &Ref3, b: &Ref3) -> R<()> {
    for r in [a, b] {
        if let Some(e) = r.edge {
            if view3d::dist3(e[0], e[1]) <= 1.0 {
                return Err(format!("dimension3d {}: an edge it measures to has its two ends in one place", id));
            }
        }
    }
    if length(a, b) <= 1.0 {
        return Err(format!(
            "dimension3d {}: it measures nothing: its references are in one place, or one lies on the other's edge",
            id
        ));
    }
    Ok(())
}

fn refs_of(e: &Value) -> Option<(Ref3, Ref3)> {
    let a = e.get("refs")?.as_arr()?;
    if a.len() != 2 {
        return None;
    }
    Some((Ref3::of(&a[0])?, Ref3::of(&a[1])?))
}

/// The model rules of this part, checked after every command.
pub fn check(pr: &Project) -> R<()> {
    for (id, e) in &pr.elements {
        if cat(e) != "dimension3d" {
            continue;
        }
        if let Some((a, b)) = refs_of(e) {
            check_refs(*id, &a, &b)?;
        }
        if let Some(g) = s_of(e, "type") {
            if pr.lib_name(g).is_none() {
                return Err(no_type(pr, *id, g));
            }
        }
    }
    Ok(())
}

/// What `elements` shows of this part's elements beyond their own fields: its type by name and
/// its length.
pub fn element_view(pr: &Project, id: u64, x: &mut Value) {
    let Some(e) = pr.el(id) else { return };
    if let Some(n) = lib_ref_name(pr, e, "type") {
        x.set("type", Value::s(&n));
    }
    if let Some((a, b)) = refs_of(e) {
        x.set("length", Value::f(r2(length(&a, &b))));
    }
}
