//! Doors and windows: the opening each cuts in its wall, and what fills it, a panel of the
//! project's own type or a family's forms.

use super::geom::*;
use super::step::{gid, real, refs, st};
use super::Ex;
use crate::json::Value;
use crate::project::Project;

fn num(v: Option<&Value>) -> Option<f64> {
    v.and_then(|x| x.as_f64())
}

/// A door's or window's family, if it is of one.
pub fn family_of<'a>(pr: &'a Project, e: &Value) -> Option<(String, &'a Value)> {
    let fg = e.get("family")?.as_str()?;
    let name = pr.lib_name(fg)?;
    let f = pr.get("families")?.get(&name)?;
    Some((name, f))
}

/// The name of a door's or window's type: its family's type, or the project's own.
pub fn type_name(pr: &Project, e: &Value) -> String {
    let tg = e.get("type").and_then(|t| t.as_str()).unwrap_or("");
    let full = pr.lib_name(tg).unwrap_or_default();
    match family_of(pr, e) {
        Some((fname, _)) => short_type(&fname, &full),
        None => full,
    }
}

/// A family type's own name: its library entry is named `Family: Type`.
pub fn short_type(family: &str, full: &str) -> String {
    full.strip_prefix(&format!("{}: ", family)).map(|s| s.to_string()).unwrap_or_else(|| full.to_string())
}

/// Width and height of the hole a door or window makes.
pub fn opening_size(pr: &Project, e: &Value) -> (f64, f64) {
    let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("door");
    let tn = type_name(pr, e);
    if let Some((_, fam)) = family_of(pr, e) {
        let vals = super::family::values(pr, fam, &tn, e, None);
        let w = vals.get("Width").copied().unwrap_or(900.0);
        let h = vals.get("Height").copied().unwrap_or(2100.0);
        return (w, h);
    }
    let td = pr.get("types").and_then(|t| t.get(cat)).and_then(|t| t.get(&tn));
    let w = num(td.and_then(|t| t.get("width"))).unwrap_or(900.0);
    let h = num(td.and_then(|t| t.get("height"))).unwrap_or(2100.0);
    (w, h)
}

/// How a door opens, in IFC's words, and how a window is partitioned.
fn operation(pr: &Project, e: &Value, cat: &str, flip_hand: bool) -> (String, String) {
    let op = match family_of(pr, e) {
        Some((_, f)) => f.get("operation").and_then(|o| o.as_str()).unwrap_or("").to_string(),
        None => {
            let tn = type_name(pr, e);
            pr.get("types")
                .and_then(|t| t.get(cat))
                .and_then(|t| t.get(&tn))
                .and_then(|t| t.get("operation"))
                .and_then(|o| o.as_str())
                .unwrap_or("")
                .to_string()
        }
    };
    if cat == "window" {
        let p = match op.as_str() {
            "double-swing" | "sliding" | "double-sliding" => "DOUBLE_PANEL_VERTICAL",
            _ => "SINGLE_PANEL",
        };
        return (p.to_string(), p.to_string());
    }
    let side = |l: &str, r: &str| if flip_hand { r.to_string() } else { l.to_string() };
    let (inst, ty) = match op.as_str() {
        "double-swing" => ("DOUBLE_DOOR_SINGLE_SWING".to_string(), "DOUBLE_DOOR_SINGLE_SWING".to_string()),
        "sliding" => (side("SLIDING_TO_LEFT", "SLIDING_TO_RIGHT"), "SLIDING_TO_LEFT".to_string()),
        "double-sliding" => ("DOUBLE_DOOR_SLIDING".to_string(), "DOUBLE_DOOR_SLIDING".to_string()),
        "folding" => (side("FOLDING_TO_LEFT", "FOLDING_TO_RIGHT"), "FOLDING_TO_LEFT".to_string()),
        "fixed" => ("NOTDEFINED".to_string(), "NOTDEFINED".to_string()),
        _ => (side("SINGLE_SWING_LEFT", "SINGLE_SWING_RIGHT"), "SINGLE_SWING_LEFT".to_string()),
    };
    (inst, ty)
}

impl<'a> Ex<'a> {
    pub fn write_opening(&mut self, id: u64, e: &Value) {
        let pr = self.pr;
        let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("door").to_string();
        let host = e.get("host").and_then(|h| h.as_str()).unwrap_or("").to_string();
        let Some(w) = self.walls.iter().find(|w| w.guid == host).cloned() else { return };
        let Some(&wall_place) = self.placements.get(&w.id) else { return };
        let Some(&wall_prod) = self.products.get(&w.id) else { return };
        let (ow, oh) = opening_size(pr, e);
        let offset = num(e.get("offset")).unwrap_or(0.0);
        let sill = num(e.get("sill")).unwrap_or(0.0);
        let flip_hand = e.get("flip_hand").and_then(|b| b.as_bool()).unwrap_or(false);
        // where the opening starts, in the wall's own axes, and which way it runs
        let mid_off = (w.left - w.right) / 2.0;
        let (at, xdir, depth) = match w.arc_geom() {
            None => {
                // its middle along the wall, back half its width, taken into the wall's axes
                let o = w.start;
                let d = w.start_dir();
                let n = d.perp();
                let c = o + d * offset + n * mid_off;
                let v = (c - d * (ow / 2.0)) - o;
                (v2(v.dot(d), v.dot(n)), v2(1.0, 0.0), w.thickness + 20.0)
            }
            Some(a) => {
                let origin = w.start;
                let d = w.start_dir();
                let n = d.perp();
                let local = |p: V2| {
                    let v = p - origin;
                    v2(v.dot(d), v.dot(n))
                };
                let sgn = if a.sweep > 0.0 { 1.0 } else { -1.0 };
                let ang = a.a0 + sgn * offset / a.radius;
                // the middle of the opening on the wall's centre line, the tangent there
                let rc = a.radius - sgn * mid_off;
                let m = a.centre + v2(ang.cos(), ang.sin()) * rc;
                let tg = v2(-ang.sin(), ang.cos()) * sgn;
                let ml = local(m);
                let tl = v2(tg.dot(d), tg.dot(n));
                let p = ml - tl * (ow / 2.0);
                let r_in = (a.radius - w.left).min(a.radius - w.right).abs();
                let half = ow / 2.0;
                let sag = if r_in > half { r_in - (r_in * r_in - half * half).sqrt() } else { r_in };
                (p, tl, w.thickness + 2.0 * sag + 20.0)
            }
        };
        let oplace = self.placement(wall_place, v3(at.x, at.y, sill), Some(xdir));
        let c = self.st.point2(ow / 2.0, 0.0);
        let a2 = self.add(format!("IFCAXIS2PLACEMENT2D(#{},$)", c));
        let rect = self.add(format!("IFCRECTANGLEPROFILEDEF(.AREA.,$,#{},{},{})", a2, real(ow), real(depth)));
        let solid = self.add(format!("IFCEXTRUDEDAREASOLID(#{},#{},#{},{})", rect, self.origin, self.up, real(oh)));
        let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','SweptSolid',(#{}))", self.body, solid));
        let shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
        let g = self.fresh();
        let opening = self.add(format!("IFCOPENINGELEMENT('{}',$,'Opening',$,$,#{},#{},$,.OPENING.)", g, oplace, shape));
        let g = self.fresh();
        self.add(format!("IFCRELVOIDSELEMENT('{}',$,$,$,#{},#{})", g, wall_prod, opening));
        // what fills it
        let tn = type_name(pr, e);
        let fam = family_of(pr, e);
        let name = match &fam {
            Some((fname, _)) => format!("{}:{}", fname, tn),
            None => tn.clone(),
        };
        let mut mats: Vec<usize> = Vec::new();
        let (place, fshape) = match &fam {
            None => {
                let c = self.st.point2(ow / 2.0, 0.0);
                let a2 = self.add(format!("IFCAXIS2PLACEMENT2D(#{},$)", c));
                let rect = self.add(format!("IFCRECTANGLEPROFILEDEF(.AREA.,$,#{},{},50.)", a2, real(ow)));
                let place = self.placement(oplace, v3(0.0, 0.0, 0.0), None);
                let solid =
                    self.add(format!("IFCEXTRUDEDAREASOLID(#{},#{},#{},{})", rect, self.origin, self.up, real(oh)));
                let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','SweptSolid',(#{}))", self.body, solid));
                let shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
                (place, shape)
            }
            Some((_, f)) => {
                let flip_facing = e.get("flip_facing").and_then(|b| b.as_bool()).unwrap_or(false);
                let ctx = super::family::Hosted { wall_thickness: w.thickness, flip_facing, flip_hand };
                let meshes = super::family::meshes(pr, f, &tn, e, Some(ctx));
                let items = self.face_sets(&meshes, &mut mats);
                let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','Tessellation',({}))", self.body, refs(&items)));
                let place = self.placement(oplace, v3(ow / 2.0, 0.0, 0.0), None);
                let shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
                (place, shape)
            }
        };
        let (op, op_type) = operation(pr, e, &cat, flip_hand);
        let mark = e.get("mark").and_then(|m| m.as_str()).unwrap_or("");
        let ifc_name = st(&name);
        let product = if cat == "door" {
            self.add(format!(
                "IFCDOOR('{}',$,{},$,{},#{},#{},{},{},{},.DOOR.,.{}.,$)",
                gid(e.get("guid").and_then(|g| g.as_str()).unwrap_or("")),
                ifc_name,
                ifc_name,
                place,
                fshape,
                st(mark),
                real(oh),
                real(ow),
                op
            ))
        } else {
            self.add(format!(
                "IFCWINDOW('{}',$,{},$,{},#{},#{},{},{},{},.WINDOW.,.{}.,$)",
                gid(e.get("guid").and_then(|g| g.as_str()).unwrap_or("")),
                ifc_name,
                ifc_name,
                place,
                fshape,
                st(mark),
                real(oh),
                real(ow),
                op
            ))
        };
        self.products.insert(id, product);
        let common = if cat == "door" { "Pset_DoorCommon" } else { "Pset_WindowCommon" };
        self.finish(id, e, product, Some(common), false);
        let g = self.fresh();
        self.add(format!("IFCRELFILLSELEMENT('{}',$,$,$,#{},#{})", g, opening, product));
        let qn = if cat == "door" { "Qto_DoorBaseQuantities" } else { "Qto_WindowBaseQuantities" };
        self.quantities(
            qn,
            product,
            &[
                ("L", "Width", ow),
                ("L", "Height", oh),
                ("L", "Perimeter", 2.0 * (ow + oh)),
                ("A", "Area", ow * oh / 1e6),
            ],
        );
        if mats.len() == 1 {
            let g = self.fresh();
            self.add(format!("IFCRELASSOCIATESMATERIAL('{}',$,$,$,(#{}),#{})", g, product, mats[0]));
        } else if mats.len() > 1 {
            let cons: Vec<usize> =
                mats.iter().map(|m| self.add(format!("IFCMATERIALCONSTITUENT($,$,#{},$,$)", m))).collect();
            let set = self.add(format!("IFCMATERIALCONSTITUENTSET({},$,({}))", st(&tn), refs(&cons)));
            let g = self.fresh();
            self.add(format!("IFCRELASSOCIATESMATERIAL('{}',$,$,$,(#{}),#{})", g, product, set));
        }
        let level = w.level.clone();
        self.contain(&level, product);
        let (class, kind) = if cat == "door" { ("IFCDOORTYPE", ".DOOR.") } else { ("IFCWINDOWTYPE", ".WINDOW.") };
        self.typed(class, &name, &format!("$,$,$,$,$,$,{},.{}.,.T.,$", kind, op_type), product);
    }

    /// Each mesh as a closed `IfcTriangulatedFaceSet` styled in its material's colour; the
    /// materials met are added to `mats` in the order they are first met.
    pub fn face_sets(&mut self, meshes: &[super::family::Mesh], mats: &mut Vec<usize>) -> Vec<usize> {
        let mut items = Vec::new();
        for m in meshes {
            let mut pts = String::new();
            for (i, p) in m.points.iter().enumerate() {
                if i > 0 {
                    pts.push(',');
                }
                pts.push_str(&format!("({},{},{})", real(p.x), real(p.y), real(p.z)));
            }
            let list = self.add(format!("IFCCARTESIANPOINTLIST3D(({}))", pts));
            let mut tris = String::new();
            for (i, t) in m.tris.iter().enumerate() {
                if i > 0 {
                    tris.push(',');
                }
                tris.push_str(&format!("({},{},{})", t[0] + 1, t[1] + 1, t[2] + 1));
            }
            let fs = self.add(format!("IFCTRIANGULATEDFACESET(#{},$,.T.,({}),$)", list, tris));
            if let Some(mn) = &m.material {
                let (mat, style) = self.material(mn);
                if !mats.contains(&mat) {
                    mats.push(mat);
                }
                self.add(format!("IFCSTYLEDITEM(#{},(#{}),$)", fs, style));
            }
            items.push(fs);
        }
        items
    }
}
