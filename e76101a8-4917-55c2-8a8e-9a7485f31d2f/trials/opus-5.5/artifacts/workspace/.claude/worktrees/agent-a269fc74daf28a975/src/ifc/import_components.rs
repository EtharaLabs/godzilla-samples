//! Components: furniture, sanitary and waste terminals, pipe fittings, valves, distribution
//! boards, outlets, switching devices, communications appliances, light fixtures and proxies, as
//! components of families made of their bodies: a family for each family the file names, of the
//! category its class says, a type for each type (and another for a body of a type that differs
//! from the first), and a type's mirror image as that type mirrored.

use super::import::Ctx;
use super::import_build::{r3z, r6};
use super::import_geom::{self as geom, sub, V3};
use super::import_mesh::{self as mesh, Tri};
use super::import_model::Model;
use crate::json::{Map, Value};
use std::collections::BTreeMap;

/// What this module keeps for later passes.
#[derive(Default)]
pub struct State {}

/// The categories in the order their components are made.
const ORDER: [&str; 17] = [
    "furniture",
    "plumbing",
    "drain",
    "pipefitting",
    "pipeaccessory",
    "equipment",
    "outlet",
    "switch",
    "airterminal",
    "earthing",
    "inspectionbox",
    "lighting",
    "generic",
    "dataoutlet",
    "voiceoutlet",
    "patchpanel",
    "rack",
];

const CLASSES: [&str; 13] = [
    "IFCFURNITURE",
    "IFCFURNISHINGELEMENT",
    "IFCSYSTEMFURNITUREELEMENT",
    "IFCSANITARYTERMINAL",
    "IFCWASTETERMINAL",
    "IFCPIPEFITTING",
    "IFCVALVE",
    "IFCELECTRICDISTRIBUTIONBOARD",
    "IFCOUTLET",
    "IFCSWITCHINGDEVICE",
    "IFCLIGHTFIXTURE",
    "IFCCOMMUNICATIONSAPPLIANCE",
    "IFCBUILDINGELEMENTPROXY",
];

const PLUMBING_KINDS: [&str; 8] = ["wc", "lav", "sink", "laundry", "shower", "bath", "bidet", "urinal"];
const DRAIN_KINDS: [&str; 3] = ["floor_drain", "floor_waste", "roof_drain"];
const FITTING_KINDS: [&str; 4] = ["bend", "tee", "coupling", "transition"];

/// What a proxy's object type says it is.
fn proxy_category(ot: &str) -> Option<&'static str> {
    match ot {
        "LightningTerminal" => Some("airterminal"),
        "EarthingRod" => Some("earthing"),
        "InspectionBox" => Some("inspectionbox"),
        "Rack" => Some("rack"),
        _ => None,
    }
}

/// An element's category and kind, if it comes in as a component, and whether its object type
/// is what says its category (a proxy's).
fn category(m: &Model, id: u64) -> Option<(&'static str, Option<&'static str>, bool)> {
    let e = m.get(id)?;
    let pre = e.p(8).enm().unwrap_or("");
    let c = match e.name.as_str() {
        "IFCFURNITURE" | "IFCFURNISHINGELEMENT" | "IFCSYSTEMFURNITUREELEMENT" => ("furniture", None, false),
        "IFCSANITARYTERMINAL" => {
            let k = match pre {
                "BATH" => Some("bath"),
                "BIDET" => Some("bidet"),
                "SHOWER" => Some("shower"),
                "SINK" => Some("sink"),
                "TOILETPAN" => Some("wc"),
                "URINAL" => Some("urinal"),
                "WASHHANDBASIN" => Some("lav"),
                _ => None,
            };
            ("plumbing", k, false)
        }
        "IFCWASTETERMINAL" => {
            let k = match pre {
                "FLOORTRAP" => Some("floor_drain"),
                "FLOORWASTE" => Some("floor_waste"),
                "ROOFDRAIN" => Some("roof_drain"),
                _ => None,
            };
            ("drain", k, false)
        }
        "IFCPIPEFITTING" => {
            let k = match pre {
                "BEND" => Some("bend"),
                "CONNECTOR" => Some("coupling"),
                "JUNCTION" => Some("tee"),
                "TRANSITION" => Some("transition"),
                _ => None,
            };
            ("pipefitting", k, false)
        }
        "IFCVALVE" => ("pipeaccessory", None, false),
        "IFCELECTRICDISTRIBUTIONBOARD" => ("equipment", None, false),
        "IFCOUTLET" => {
            let c = match pre {
                "DATAOUTLET" => "dataoutlet",
                "TELEPHONEOUTLET" => "voiceoutlet",
                _ => "outlet",
            };
            (c, None, false)
        }
        "IFCSWITCHINGDEVICE" => ("switch", None, false),
        "IFCLIGHTFIXTURE" => ("lighting", None, false),
        "IFCCOMMUNICATIONSAPPLIANCE" => ("patchpanel", None, false),
        "IFCBUILDINGELEMENTPROXY" => {
            let ot = m.object_type(id).map(|s| s.trim().to_string()).unwrap_or_default();
            if ot == "Mass" {
                return None;
            }
            match proxy_category(&ot) {
                Some(c) => (c, None, true),
                None => ("generic", None, false),
            }
        }
        _ => return None,
    };
    Some(c)
}

fn clean(s: Option<String>) -> Option<String> {
    s.map(|x| x.trim().to_string()).filter(|x| !x.is_empty())
}

fn cut(s: &str) -> String {
    s.chars().take(256).collect()
}

/// The family and type an element names: `Family:Type` (Revit's `Family:Type:Id` too) from its
/// type object, else its object type, else its name (a proxy whose object type says what it is,
/// by its name), else its class; one name alone is the family's and the type's.
fn names(ctx: &Ctx, id: u64, marker: bool) -> (String, String) {
    let label = if marker {
        clean(ctx.m.name(id))
    } else {
        super::import_types::file_type_name(ctx, id).or_else(|| clean(ctx.m.name(id)))
    }
    .unwrap_or_else(|| ctx.m.class(id).to_string());
    let mut parts = label.split(':');
    let fam = parts.next().unwrap_or("").trim();
    let typ = parts.next().map(|t| t.trim()).unwrap_or(fam);
    (cut(fam), cut(typ))
}

/// The first material of a material definition (a set's first, a layer's or profile's own).
fn first_material(m: &Model, id: u64, depth: usize) -> Option<u64> {
    if depth > 8 {
        return None;
    }
    let e = m.get(id)?;
    let next = |r: Option<u64>| r.and_then(|r| first_material(m, r, depth + 1));
    match e.name.as_str() {
        "IFCMATERIAL" => Some(id),
        "IFCMATERIALCONSTITUENTSET" | "IFCMATERIALPROFILESET" => next(e.p(2).refs().first().copied()),
        "IFCMATERIALCONSTITUENT" | "IFCMATERIALPROFILE" => next(e.p(2).r()),
        "IFCMATERIALLIST" | "IFCMATERIALLAYERSET" => next(e.p(0).refs().first().copied()),
        "IFCMATERIALLAYER" | "IFCMATERIALLAYERSETUSAGE" | "IFCMATERIALPROFILESETUSAGE" => next(e.p(0).r()),
        _ => None,
    }
}

/// The library material of the element's own material (or its type's), by name.
fn element_material(ctx: &mut Ctx, id: u64) -> Option<String> {
    let def = ctx.m.material_of.get(&id).copied().or_else(|| {
        let t = ctx.m.type_of.get(&id)?;
        ctx.m.material_of.get(t).copied()
    })?;
    let mat = first_material(&ctx.m, def, 0)?;
    super::import_types::material(ctx, mat)?;
    ctx.m.get(mat)?.p(0).str().map(|s| s.trim().to_string())
}

/// A styled item's surface style: its name, colour and transparency.
fn surface_style(m: &Model, si: u64) -> Option<(Option<String>, Option<[u64; 3]>, Option<f64>)> {
    let e = m.get(si)?;
    let mut styles: Vec<u64> = Vec::new();
    for s in e.p(1).refs() {
        match m.get(s).map(|x| x.name.as_str()) {
            Some("IFCPRESENTATIONSTYLEASSIGNMENT") => styles.extend(m.get(s).unwrap().p(0).refs()),
            _ => styles.push(s),
        }
    }
    for s in styles {
        let se = match m.get(s) {
            Some(x) if x.name == "IFCSURFACESTYLE" => x,
            _ => continue,
        };
        let name = clean(se.p(0).str().map(|x| x.to_string()));
        let mut rgb = None;
        let mut tr = None;
        for el in se.p(2).refs() {
            let ee = match m.get(el) {
                Some(x) => x,
                None => continue,
            };
            if ee.name == "IFCSURFACESTYLESHADING" || ee.name == "IFCSURFACESTYLERENDERING" {
                rgb = ee.p(0).r().and_then(|c| m.get(c)).and_then(|c| {
                    if c.name != "IFCCOLOURRGB" {
                        return None;
                    }
                    let f = |i: usize| -> Option<u64> { Some((c.p(i).num()?.clamp(0.0, 1.0) * 255.0).round() as u64) };
                    Some([f(1)?, f(2)?, f(3)?])
                });
                tr = ee.p(1).num();
                break;
            }
        }
        return Some((name, rgb, tr));
    }
    None
}

/// The library material a styled item paints with: the material of its surface style's name,
/// coloured (and made see-through) as the style says.
fn style_material(ctx: &mut Ctx, si: u64) -> Option<String> {
    let (name, rgb, tr) = surface_style(&ctx.m, si)?;
    let name = name?;
    let tr = tr.map(|t| (t.clamp(0.0, 1.0) * 100.0).round() as u64).filter(|t| *t > 0);
    let mats = ctx.pr.section_mut("materials");
    match mats.get_mut(&name) {
        Some(v) => {
            if let Some(c) = rgb {
                v.set("color", Value::Arr(c.iter().map(|x| Value::u(*x)).collect()));
            }
            match tr {
                Some(t) => v.set("transparency", Value::u(t)),
                None => {
                    v.remove("transparency");
                }
            }
        }
        None => {
            let c = rgb.unwrap_or([200, 200, 200]);
            let mut v = crate::jobj! {
                "color" => Value::Arr(c.iter().map(|x| Value::u(*x)).collect()),
                "cut" => "none",
                "surface" => "none",
            };
            if let Some(t) = tr {
                v.set("transparency", Value::u(t));
            }
            mats.insert_sorted(&name, v);
        }
    }
    Some(name)
}

/// A body's forms: its triangles by material (no material first), in the element's own frame.
type Forms = Vec<(String, Vec<Tri>)>;

fn flip(p: V3) -> V3 {
    [p[0], if p[1] == 0.0 { 0.0 } else { -p[1] }, p[2]]
}

/// The mirror image of forms across the element's own x axis.
fn mirror(forms: &Forms) -> Forms {
    forms.iter().map(|(m, ts)| (m.clone(), ts.iter().map(|t| mesh::canonical([flip(t[0]), flip(t[2]), flip(t[1])])).collect())).collect()
}

struct TypeB {
    name: String,
    base: String,
    forms: Forms,
}

struct FamB {
    name: String,
    cat: &'static str,
    kind: Option<&'static str>,
    types: Vec<TypeB>,
    members: Vec<usize>,
}

struct Cand {
    id: u64,
    fam: usize,
    typ: usize,
    mirrored: bool,
}

/// The element's frame: its origin and its angle in plan (radians).
fn frame(m: &Model, id: u64) -> (V3, f64) {
    let tf = geom::product_tf(m, id);
    (tf.t, tf.x[1].atan2(tf.x[0]))
}

fn forms_of(ctx: &mut Ctx, id: u64) -> Forms {
    let parts = mesh::body_parts(&ctx.m, id);
    let (o, ang) = frame(&ctx.m, id);
    let (c, s) = (ang.cos(), ang.sin());
    let local = |p: V3| -> V3 {
        let d = sub(p, o);
        [r3z(c * d[0] + s * d[1]), r3z(-s * d[0] + c * d[1]), r3z(d[2])]
    };
    let mut by: BTreeMap<String, Vec<Tri>> = BTreeMap::new();
    let mut own: Option<Option<String>> = None;
    for part in parts {
        let mut mat = part.style.and_then(|si| style_material(ctx, si));
        if mat.is_none() {
            if own.is_none() {
                own = Some(element_material(ctx, id));
            }
            mat = own.clone().unwrap();
        }
        let list = by.entry(mat.unwrap_or_default()).or_default();
        for t in part.tris {
            list.push(mesh::canonical([local(t[0]), local(t[1]), local(t[2])]));
        }
    }
    by.into_iter().filter(|(_, ts)| !ts.is_empty()).collect()
}

/// A family's faults, as the project would refuse it.
fn check(f: &FamB) -> Result<(), String> {
    if let Some(k) = f.kind {
        let kinds: &[&str] = match f.cat {
            "plumbing" => &PLUMBING_KINDS,
            "drain" => &DRAIN_KINDS,
            "pipefitting" => &FITTING_KINDS,
            _ => &[],
        };
        if kinds.is_empty() {
            return Err(format!("`kind` `{}`: a family of this category has no kinds; leave `kind` out", k));
        }
        if !kinds.contains(&k) {
            return Err(format!("`kind` is one of {}, not `{}`", kinds.join(", "), k));
        }
    }
    for t in &f.types {
        if t.name.is_empty() || t.name.chars().count() > 256 {
            return Err(format!("type `{}`: a type needs a name, up to 256 characters", t.name));
        }
    }
    Ok(())
}

fn tri_value(t: &Tri) -> Value {
    Value::Arr(t.iter().map(|p| Value::Arr(p.iter().map(|x| Value::f(*x)).collect())).collect())
}

fn family_value(ctx: &mut Ctx, f: &FamB) -> Value {
    let single = f.types.len() == 1;
    let mut types = Map::new();
    for (i, t) in f.types.iter().enumerate() {
        let v = if single { Value::obj() } else { crate::jobj! {"Variant" => Value::u(i as u64 + 1)} };
        types.insert_sorted(&t.name, v);
    }
    let params = if single {
        Vec::new()
    } else {
        vec![crate::jobj! {"name" => "Variant", "kind" => "number", "value" => Value::Null}]
    };
    let mut forms = Vec::new();
    for (i, t) in f.types.iter().enumerate() {
        for (mat, tris) in &t.forms {
            let mut o = Map::new();
            o.insert("id", Value::u(0));
            o.insert("guid", Value::s(&crate::rand::guid()));
            o.insert("plane", Value::s("xy"));
            o.insert("from", Value::f(0.0));
            o.insert("to", Value::f(0.0));
            if !mat.is_empty() {
                let g = ctx.lib.get(&ctx.pr, "material", mat);
                o.insert("material", Value::s(&g));
            }
            if !single {
                o.insert("visible", Value::s(&format!("Variant = {}", i + 1)));
            }
            o.insert("mesh", Value::Arr(tris.iter().map(tri_value).collect()));
            forms.push(Value::Obj(o));
        }
    }
    let mut v = crate::jobj! {"category" => f.cat};
    if let Some(k) = f.kind {
        v.set("kind", Value::s(k));
    }
    v.set("parameters", Value::Arr(params));
    v.set("types", Value::Obj(types));
    v.set("forms", Value::Arr(forms));
    v
}

pub fn components(ctx: &mut Ctx) -> Result<(), String> {
    // the candidates: category by category, each in the file's order
    let mut found: Vec<(usize, u64, &'static str, Option<&'static str>, bool)> = Vec::new();
    for cls in CLASSES {
        for &id in ctx.m.of(cls) {
            if let Some((cat, kind, marker)) = category(&ctx.m, id) {
                let k = ORDER.iter().position(|c| *c == cat).unwrap_or(ORDER.len());
                found.push((k, id, cat, kind, marker));
            }
        }
    }
    found.sort_by(|a, b| a.0.cmp(&b.0).then(a.1.cmp(&b.1)));
    let mut fams: Vec<FamB> = Vec::new();
    let mut cands: Vec<Cand> = Vec::new();
    for (_, id, cat, kind, marker) in found {
        let (fname, tname) = names(ctx, id, marker);
        let forms = forms_of(ctx, id);
        if forms.is_empty() {
            ctx.skip(id, "it has no body BIMCraft can read");
            continue;
        }
        let fi = match fams.iter().position(|f| f.name == fname) {
            Some(i) => i,
            None => {
                fams.push(FamB { name: fname.clone(), cat, kind: None, types: Vec::new(), members: Vec::new() });
                fams.len() - 1
            }
        };
        let f = &mut fams[fi];
        if f.kind.is_none() {
            f.kind = kind;
        }
        let mut hit: Option<(usize, bool)> = None;
        let mirrored = mirror(&forms);
        for (ti, t) in f.types.iter().enumerate() {
            if t.base != tname {
                continue;
            }
            if t.forms == forms {
                hit = Some((ti, false));
                break;
            }
            if t.forms == mirrored {
                hit = Some((ti, true));
                break;
            }
        }
        let (ti, mir) = match hit {
            Some(h) => h,
            None => {
                let n = f.types.iter().filter(|t| t.base == tname).count();
                let name = if n == 0 { tname.clone() } else { format!("{} ({})", tname, n + 1) };
                f.types.push(TypeB { name, base: tname.clone(), forms });
                (f.types.len() - 1, false)
            }
        };
        f.members.push(cands.len());
        cands.push(Cand { id, fam: fi, typ: ti, mirrored: mir });
    }
    // each family as the project takes it, or its components left out with why
    let mut ok = vec![false; fams.len()];
    for fi in 0..fams.len() {
        match check(&fams[fi]) {
            Err(why) => {
                for &ci in &fams[fi].members {
                    let id = cands[ci].id;
                    ctx.skip(id, &why);
                }
            }
            Ok(()) => {
                if fams[fi].name.is_empty() {
                    return Err(format!("{}: a family needs a name", ctx.path));
                }
                let v = family_value(ctx, &fams[fi]);
                ctx.pr.section_mut("families").insert_sorted(&fams[fi].name, v);
                ok[fi] = true;
            }
        }
    }
    for c in &cands {
        if !ok[c.fam] {
            continue;
        }
        let f = &fams[c.fam];
        let t = &f.types[c.typ];
        let (o, ang) = frame(&ctx.m, c.id);
        let lvl = ctx.level_of(c.id, o[2]);
        let fam_guid = ctx.lib.get(&ctx.pr, "family", &f.name);
        let type_guid = ctx.lib.get(&ctx.pr, "family-type", &format!("{}: {}", f.name, t.name));
        let g = ctx.guid_for(c.id);
        let mut v = crate::jobj! {
            "guid" => g.as_str(),
            "category" => "component",
            "family" => fam_guid,
            "type" => type_guid,
            "level" => ctx.level_guid(lvl),
            "at" => Value::Arr(vec![Value::f(r3z(o[0])), Value::f(r3z(o[1]))]),
            "angle" => r6(ang.to_degrees()),
            "offset" => r3z(o[2] - ctx.levels[lvl].elevation),
        };
        if c.mirrored {
            v.set("mirrored", Value::Bool(true));
        }
        ctx.add(c.id, v);
    }
    Ok(())
}
