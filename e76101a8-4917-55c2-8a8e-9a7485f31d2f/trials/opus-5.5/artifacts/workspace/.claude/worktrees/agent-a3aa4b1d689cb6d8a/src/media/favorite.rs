//! `favorite`: the user's favorites, materials (with their pictures) and families (with the
//! materials they're made of), kept in a file of their own for every project:
//! `{"version": 1, "materials": {name: {material, images?}}, "families": {name: {family, materials?}}}`.

use super::favjson::{self, FamilyEntry, Favorites, MaterialEntry, PictureFile};
use super::material as mat;
use crate::commands::params::*;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;

/// Where the favorites are: `BIMCRAFT_FAVORITES`, else `favorites.json` in the configuration
/// folder (`$XDG_CONFIG_HOME/bimcraft`, else `~/.config/bimcraft`).
pub fn default_path() -> String {
    if let Ok(p) = std::env::var("BIMCRAFT_FAVORITES") {
        if !p.is_empty() {
            return p;
        }
    }
    let dir = match std::env::var("XDG_CONFIG_HOME") {
        Ok(x) if !x.is_empty() && std::path::Path::new(&x).is_absolute() => std::path::PathBuf::from(x),
        _ => {
            let home = std::env::var("HOME").unwrap_or_default();
            std::path::Path::new(&home).join(".config")
        }
    };
    dir.join("bimcraft").join("favorites.json").to_string_lossy().to_string()
}

fn io(path: &str, e: &std::io::Error) -> String {
    format!("favorite: {}: {}", path, crate::commands::io_err(e))
}

/// Reads the favorites (none if there's no file yet).
pub fn read(path: &str) -> Result<Favorites, String> {
    let bytes = match std::fs::read(path) {
        Ok(b) => b,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Favorites::default()),
        Err(e) => return Err(io(path, &e)),
    };
    let bad = |e: String| format!("favorite: {} isn't a favorites file: {}", path, e);
    if let Err(e) = crate::json::parse_bytes(&bytes) {
        return Err(bad(e.to_string()));
    }
    let favs = favjson::favorites(&bytes).map_err(bad)?;
    // each favorite as it would come into a project
    for (name, e) in &favs.materials {
        if let Err(m) = check_entry(e) {
            return Err(format!("favorite: {}: material `{}`: {}", path, name, m));
        }
    }
    for (name, e) in &favs.families {
        let has_types = e.family.get("types").and_then(|t| t.as_obj()).map(|t| !t.is_empty()).unwrap_or(false);
        if !has_types {
            return Err(format!("favorite: {}: family `{}`: it needs a type: add one to `types`", path, name));
        }
        for (mname, me) in &e.materials {
            if let Err(m) = check_entry(me) {
                return Err(format!("favorite: {}: material `{}`: {}", path, mname, m));
            }
        }
    }
    Ok(favs)
}

/// What a favorite material must be: its texture's tile and its picture.
fn check_entry(e: &MaterialEntry) -> Result<(), String> {
    let Some(t) = e.material.get("texture") else { return Ok(()) };
    let kind = t.get("kind").and_then(|k| k.as_str()).unwrap_or("");
    let size = t.get("size").and_then(|s| s.as_arr()).map(|a| [a[0].as_f64().unwrap_or(0.0), a[1].as_f64().unwrap_or(0.0)]).unwrap_or([0.0, 0.0]);
    let ok = |x: f64| x.is_finite() && (1.0..=1_000_000.0).contains(&x);
    if !ok(size[0]) || !ok(size[1]) {
        return Err(format!(
            "texture: a tile of it is {} by {} mm; each side is 1 to 1000000 mm",
            mat::disp(size[0]),
            mat::disp(size[1])
        ));
    }
    let angle = t.get("angle").and_then(|a| a.as_f64()).unwrap_or(0.0);
    let offset: Vec<f64> = t.get("offset").and_then(|o| o.as_arr()).map(|a| a.iter().filter_map(|x| x.as_f64()).collect()).unwrap_or_default();
    if angle.abs() > 1_000_000.0 || offset.iter().any(|x| (x / 1000.0).abs() > 1_000_000.0) {
        return Err("texture: its angle and its offset need to be numbers".into());
    }
    let image = t.get("image").and_then(|i| i.as_str());
    if kind == "image" {
        match image {
            None => return Err("a texture of a picture needs its file, `path`, or one of the project's, `image`".into()),
            Some(id) => {
                if !e.images.iter().any(|(k, _)| k == id) {
                    let have: Vec<&str> = e.images.iter().map(|(k, _)| k.as_str()).collect();
                    return Err(format!(
                        "texture: it's of picture `{}`, which the project doesn't hold (it has: {})",
                        id,
                        have.join(", ")
                    ));
                }
            }
        }
    } else if image.is_some() {
        return Err("only a texture of kind `image` takes a `path` or an `image`".into());
    }
    Ok(())
}

fn entry_value(e: &MaterialEntry) -> Value {
    let mut m = Map::new();
    m.insert("material", e.material.clone());
    if !e.images.is_empty() {
        let mut im = Map::new();
        for (id, p) in &e.images {
            im.insert(id, jobj! {"name" => p.name.clone(), "png" => p.png.clone()});
        }
        m.insert("images", Value::Obj(im));
    }
    Value::Obj(m)
}

/// Writes the favorites (pretty, as serde_json writes them), making its folder if need be.
pub fn write(path: &str, favs: &Favorites) -> Result<(), String> {
    let mut mats = Map::new();
    for (n, e) in &favs.materials {
        mats.insert(n, entry_value(e));
    }
    let mut fams = Map::new();
    for (n, e) in &favs.families {
        let mut m = Map::new();
        m.insert("family", e.family.clone());
        if !e.materials.is_empty() {
            let mut mm = Map::new();
            for (mn, me) in &e.materials {
                mm.insert(mn, entry_value(me));
            }
            m.insert("materials", Value::Obj(mm));
        }
        fams.insert(n, Value::Obj(m));
    }
    let doc = jobj! {"version" => 1u64, "materials" => Value::Obj(mats), "families" => Value::Obj(fams)};
    if let Some(dir) = std::path::Path::new(path).parent() {
        if !dir.as_os_str().is_empty() {
            std::fs::create_dir_all(dir).map_err(|e| io(path, &e))?;
        }
    }
    std::fs::write(path, doc.to_pretty()).map_err(|e| io(path, &e))
}

fn put<T: Clone>(list: &mut Vec<(String, T)>, name: &str, v: T) {
    match list.binary_search_by(|(k, _)| k.as_str().cmp(name)) {
        Ok(i) => list[i].1 = v,
        Err(i) => list.insert(i, (name.to_string(), v)),
    }
}

// ---------------------------------------------------------------- materials in and out

/// A project's material as a favorite: patterns and its picture by name, with the picture.
pub fn material_entry(pr: &Project, name: &str) -> Option<MaterialEntry> {
    let m = mat::material(pr, name)?;
    let mut v = mat::ordered(m);
    let mut images = Vec::new();
    for key in ["cut_pattern", "surface_pattern"] {
        if let Some(g) = v.get(key).and_then(|x| x.as_str()).map(|s| s.to_string()) {
            if let Some(n) = mat::fill_pattern_name(pr, &g) {
                v.set(key, Value::Str(n));
            }
        }
    }
    if let Some(t) = v.get_mut("texture") {
        if let Some(g) = t.get("image").and_then(|x| x.as_str()).map(|s| s.to_string()) {
            if let Some(id) = mat::picture_id(pr, &g) {
                t.set("image", Value::s(&id));
                if let Some(im) = pr.section("images").and_then(|m| m.get(&id)) {
                    images.push((
                        id.clone(),
                        PictureFile {
                            name: im.get("name").and_then(|x| x.as_str()).unwrap_or("").to_string(),
                            png: im.get("png").and_then(|x| x.as_str()).unwrap_or("").to_string(),
                        },
                    ));
                }
            }
        }
    }
    Some(MaterialEntry { material: v, images })
}

/// Brings a favorite material into the project as `target` (over the one it has, if any).
pub fn load_material(pr: &mut Project, target: &str, e: &MaterialEntry) -> Result<(), String> {
    if mat::material(pr, target).is_none() {
        pr.section_mut("materials").insert_sorted(target, mat::new_material());
        if pr.lib_find("material", target).is_none() {
            pr.lib_add("material", target);
        }
    }
    let mut m = e.material.clone();
    for key in ["cut_pattern", "surface_pattern"] {
        if let Some(n) = m.get(key).and_then(|x| x.as_str()).map(|s| s.to_string()) {
            match mat::fill_pattern_guid(pr, &n) {
                Some(g) => m.set(key, Value::Str(g)),
                None => return Err(format!("material `{}`: there's no fill pattern `{}`", target, n)),
            }
        }
    }
    if let Some(id) = m.get("texture").and_then(|t| t.get("image")).and_then(|x| x.as_str()).map(|s| s.to_string()) {
        if let Some((_, pf)) = e.images.iter().find(|(k, _)| *k == id) {
            if !mat::picture_ids(pr).contains(&id) {
                if mat::picture_ids(pr).len() >= super::picture::MAX_PICTURES {
                    return Err(format!(
                        "favorite: the project holds {} pictures already; take a texture of one away first",
                        super::picture::MAX_PICTURES
                    ));
                }
                pr.section_mut("images").insert_sorted(&id, jobj! {"name" => pf.name.clone(), "png" => pf.png.clone()});
                pr.lib_add("picture", &id);
            }
        }
        let g = mat::picture_guid(pr, &id).unwrap_or_default();
        if let Some(t) = m.get_mut("texture") {
            t.set("image", Value::Str(g));
        }
    }
    pr.section_mut("materials").insert_sorted(target, mat::ordered(&m));
    mat::drop_unused_pictures(pr);
    Ok(())
}

// ---------------------------------------------------------------- families in and out

/// A project's family as a favorite: the materials it names by name, and those materials.
pub fn family_entry(pr: &Project, name: &str) -> Option<FamilyEntry> {
    let f = pr.section("families")?.get(name)?;
    let mut used: Vec<String> = Vec::new();
    let fam = rename_materials(pr, f, &mut used);
    used.sort();
    used.dedup();
    let mut materials = Vec::new();
    for m in used {
        if let Some(e) = material_entry(pr, &m) {
            materials.push((m, e));
        }
    }
    Some(FamilyEntry { family: fam, materials })
}

/// A copy with every material GUID made the material's name.
fn rename_materials(pr: &Project, v: &Value, used: &mut Vec<String>) -> Value {
    match v {
        Value::Str(s) => {
            if crate::model::normalize_guid(s).as_deref() == Some(s.as_str()) {
                if let Some(n) = mat::material_name(pr, s) {
                    used.push(n.clone());
                    return Value::Str(n);
                }
            }
            v.clone()
        }
        Value::Arr(a) => Value::Arr(a.iter().map(|x| rename_materials(pr, x, used)).collect()),
        Value::Obj(m) => {
            let mut out = Map::new();
            for (k, x) in m.iter() {
                out.insert(k, rename_materials(pr, x, used));
            }
            Value::Obj(out)
        }
        _ => v.clone(),
    }
}

// ---------------------------------------------------------------- the command

pub fn cmd(s: &mut Session, p: &Value) -> Result<Value, String> {
    let action = opt_text(p, "favorite", "action")?;
    let kind = opt_text(p, "favorite", "kind")?.unwrap_or_else(|| "material".into());
    if kind != "material" && kind != "family" {
        return Err(format!("favorite: `kind` is material or family, not `{}`", kind));
    }
    let action = action.unwrap_or_else(|| "list".into());
    if !matches!(action.as_str(), "list" | "save" | "load" | "delete") {
        return Err(format!("favorite: `action` is list, save, load or delete, not `{}`", action));
    }
    let path = match opt_text(p, "favorite", "path")? {
        Some(x) => x,
        None => default_path(),
    };
    let whose = if kind == "family" { "the family's" } else { "the material's" };
    let need_name = || -> Result<String, String> {
        match opt_text(p, "favorite", "name")? {
            Some(n) if !n.trim().is_empty() => Ok(n.trim().to_string()),
            _ => Err(format!("favorite: `name` is required: {}", whose)),
        }
    };
    let as_name = || -> Result<Option<String>, String> {
        Ok(opt_text(p, "favorite", "as")?.map(|a| a.trim().to_string()).filter(|a| !a.is_empty()))
    };
    match action.as_str() {
        "list" => {
            let favs = read(&path)?;
            let mats: Vec<Value> = favs
                .materials
                .iter()
                .map(|(n, e)| {
                    let tex = e.material.get("texture").and_then(|t| t.get("kind")).cloned().unwrap_or(Value::Null);
                    jobj! {"color" => e.material.get("color").cloned().unwrap_or(Value::Null), "name" => n.clone(), "texture" => tex}
                })
                .collect();
            let fams: Vec<Value> = favs
                .families
                .iter()
                .map(|(n, e)| {
                    let types: Vec<Value> = e
                        .family
                        .get("types")
                        .and_then(|t| t.as_obj())
                        .map(|t| {
                            let mut k: Vec<String> = t.keys().cloned().collect();
                            k.sort();
                            k.into_iter().map(Value::Str).collect()
                        })
                        .unwrap_or_default();
                    jobj! {"category" => e.family.get("category").cloned().unwrap_or(Value::Null), "name" => n.clone(), "types" => Value::Arr(types)}
                })
                .collect();
            Ok(jobj! {"families" => Value::Arr(fams), "materials" => Value::Arr(mats), "path" => path})
        }
        "save" => {
            let name = need_name()?;
            let target = as_name()?.unwrap_or_else(|| name.clone());
            let pr = &s.project;
            let mut favs = read(&path)?;
            if kind == "material" {
                let e = material_entry(pr, &name).ok_or_else(|| format!("favorite: the library has no `{}`", name))?;
                put(&mut favs.materials, &target, e);
            } else {
                let e = family_entry(pr, &name).ok_or_else(|| format!("favorite: the project has no family `{}`", name))?;
                put(&mut favs.families, &target, e);
            }
            write(&path, &favs)?;
            Ok(jobj! {"kind" => kind, "path" => path, "saved" => target})
        }
        "load" => {
            let name = need_name()?;
            let target = as_name()?.unwrap_or_else(|| name.clone());
            let replace = opt_bool(p, "favorite", "replace")?.unwrap_or(false);
            let favs = read(&path)?;
            let pr = &mut s.project;
            if kind == "material" {
                let e = favs
                    .materials
                    .iter()
                    .find(|(n, _)| *n == name)
                    .map(|(_, e)| e.clone())
                    .ok_or_else(|| format!("favorite: there's no favorite material `{}`", name))?;
                if mat::material(pr, &target).is_some() && !replace {
                    return Err(format!(
                        "favorite: the library has `{}` already: load it `as` another name, or `replace` it",
                        target
                    ));
                }
                load_material(pr, &target, &e)?;
            } else {
                let e = favs
                    .families
                    .iter()
                    .find(|(n, _)| *n == name)
                    .map(|(_, e)| e.clone())
                    .ok_or_else(|| format!("favorite: there's no favorite family `{}`", name))?;
                load_family(pr, &target, &e, replace)?;
            }
            Ok(jobj! {"kind" => kind, "loaded" => target})
        }
        _ => {
            let name = need_name()?;
            let mut favs = read(&path)?;
            let list_len;
            if kind == "material" {
                list_len = favs.materials.len();
                favs.materials.retain(|(n, _)| *n != name);
                if favs.materials.len() == list_len {
                    return Err(format!("favorite: there's no favorite material `{}`", name));
                }
            } else {
                list_len = favs.families.len();
                favs.families.retain(|(n, _)| *n != name);
                if favs.families.len() == list_len {
                    return Err(format!("favorite: there's no favorite family `{}`", name));
                }
            }
            write(&path, &favs)?;
            Ok(jobj! {"deleted" => name, "kind" => kind})
        }
    }
}

/// Brings a favorite family in: the materials it's made of that the project hasn't come by
/// name, then the family with its materials named by GUID.
fn load_family(pr: &mut Project, target: &str, e: &FamilyEntry, replace: bool) -> Result<(), String> {
    let exists = pr.section("families").map(|f| f.contains(target)).unwrap_or(false);
    if exists && !replace {
        return Err(format!(
            "favorite: the project has family `{}` already: load it `as` another name, or `replace` it",
            target
        ));
    }
    for (mname, me) in &e.materials {
        if mat::material(pr, mname).is_none() {
            load_material(pr, mname, me)?;
        }
    }
    let fam = guid_materials(pr, &e.family);
    if !exists {
        pr.lib_add("family", target);
    }
    pr.section_mut("families").insert_sorted(target, fam);
    Ok(())
}

/// A copy with every material name in `material` and material values made its GUID.
fn guid_materials(pr: &Project, v: &Value) -> Value {
    let mut out = v.clone();
    if let Some(forms) = out.get_mut("forms").and_then(|f| f.as_arr_mut()) {
        for fo in forms.iter_mut() {
            if let Some(n) = fo.get("material").and_then(|m| m.as_str()).map(|s| s.to_string()) {
                if let Some(g) = mat::material_guid(pr, &n) {
                    fo.set("material", Value::Str(g));
                }
            }
        }
    }
    let mut mparams: Vec<String> = Vec::new();
    if let Some(params) = out.get_mut("parameters").and_then(|f| f.as_arr_mut()) {
        for pa in params.iter_mut() {
            if pa.get("kind").and_then(|k| k.as_str()) == Some("material") {
                if let Some(n) = pa.get("name").and_then(|m| m.as_str()) {
                    mparams.push(n.to_string());
                }
                if let Some(n) = pa.get("value").and_then(|m| m.as_str()).map(|s| s.to_string()) {
                    if let Some(g) = mat::material_guid(pr, &n) {
                        pa.set("value", Value::Str(g));
                    }
                }
            }
        }
    }
    if let Some(types) = out.get_mut("types").and_then(|t| t.as_obj_mut()) {
        for (_, t) in types.items.iter_mut() {
            for pn in &mparams {
                if let Some(n) = t.get(pn).and_then(|m| m.as_str()).map(|s| s.to_string()) {
                    if let Some(g) = mat::material_guid(pr, &n) {
                        t.set(pn, Value::Str(g));
                    }
                }
            }
        }
    }
    out
}
