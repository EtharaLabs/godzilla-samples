//! `material`: the project's materials library, its textures and the pictures they're made of.
//!
//! In the file a material is `{color, cut, surface, cut_pattern?, surface_pattern?, texture?,
//! transparency?}`, by name in `materials`, with a library entry of kind `material`; its patterns
//! name fill patterns by GUID, its texture `{kind, size, angle?, offset?, image?}` a picture by
//! the GUID of its library entry (kind `picture`, named by its id). Pictures are in `images`,
//! `{id: {name, png}}`, and go when no material's texture is made of them.

use super::picture;
use crate::commands::params::*;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;

pub const PATTERNS: [&str; 10] = ["none", "solid", "diagonal", "crosshatch", "horizontal", "vertical", "grid", "brick", "concrete", "insulation"];
pub const KINDS: [&str; 11] = ["brick", "block", "boards", "concrete", "plaster", "tile", "roof", "fabric", "metal", "insulation", "image"];

/// The size a texture drawn in code has, its tile's width and height in mm.
pub fn natural_size(kind: &str) -> [f64; 2] {
    match kind {
        "brick" => [900.0, 600.0],
        "block" => [800.0, 800.0],
        "boards" => [1200.0, 1120.0],
        "concrete" => [1000.0, 1000.0],
        "plaster" => [500.0, 500.0],
        "tile" => [1200.0, 1200.0],
        "roof" => [1320.0, 1000.0],
        "fabric" => [100.0, 100.0],
        "metal" => [800.0, 800.0],
        "insulation" => [600.0, 600.0],
        _ => [1000.0, 1000.0],
    }
}

/// The default tile of a picture's texture: 1000 mm across, as high as the picture is.
pub fn picture_size(w: u32, h: u32) -> [f64; 2] {
    [1000.0, 1000.0 * h as f64 / w as f64]
}

/// Numbers as Rust's Display shows them.
pub fn disp(x: f64) -> String {
    format!("{}", x)
}

// ---------------------------------------------------------------- lookups

pub fn materials(pr: &Project) -> Option<&Map> {
    pr.section("materials")
}

pub fn material<'a>(pr: &'a Project, name: &str) -> Option<&'a Value> {
    materials(pr).and_then(|m| m.get(name))
}

/// A material's GUID, from its library entry.
pub fn material_guid(pr: &Project, name: &str) -> Option<String> {
    pr.lib_guid("material", name)
}

/// The name of the material with this GUID.
pub fn material_name(pr: &Project, guid: &str) -> Option<String> {
    let id = pr.lib_find_guid(guid)?;
    let e = pr.library.get(&id)?;
    if e.get("kind").and_then(|k| k.as_str()) != Some("material") {
        return None;
    }
    e.get("name").and_then(|n| n.as_str()).map(|s| s.to_string())
}

/// A picture's id (`img-…`) from the GUID of its library entry.
pub fn picture_id(pr: &Project, guid: &str) -> Option<String> {
    let id = pr.lib_find_guid(guid)?;
    let e = pr.library.get(&id)?;
    if e.get("kind").and_then(|k| k.as_str()) != Some("picture") {
        return None;
    }
    e.get("name").and_then(|n| n.as_str()).map(|s| s.to_string())
}

pub fn picture_guid(pr: &Project, id: &str) -> Option<String> {
    pr.lib_guid("picture", id)
}

pub fn fill_pattern_name(pr: &Project, guid: &str) -> Option<String> {
    let id = pr.lib_find_guid(guid)?;
    let e = pr.library.get(&id)?;
    if e.get("kind").and_then(|k| k.as_str()) != Some("fill-pattern") {
        return None;
    }
    e.get("name").and_then(|n| n.as_str()).map(|s| s.to_string())
}

pub fn fill_pattern_guid(pr: &Project, name: &str) -> Option<String> {
    if !pr.section("fill_patterns").map(|m| m.contains(name)).unwrap_or(false) {
        return None;
    }
    pr.lib_guid("fill-pattern", name)
}

/// The pictures the project holds, by id.
pub fn picture_ids(pr: &Project) -> Vec<String> {
    pr.section("images").map(|m| m.keys().cloned().collect()).unwrap_or_default()
}

// ---------------------------------------------------------------- views

/// A material as replies and `inspect` show it: keys sorted, patterns and pictures by name.
pub fn view(pr: &Project, m: &Value) -> Value {
    let mut v = m.clone();
    for key in ["cut_pattern", "surface_pattern"] {
        if let Some(g) = v.get(key).and_then(|x| x.as_str()).map(|s| s.to_string()) {
            if let Some(n) = fill_pattern_name(pr, &g) {
                v.set(key, Value::Str(n));
            }
        }
    }
    if let Some(t) = v.get_mut("texture") {
        if let Some(g) = t.get("image").and_then(|x| x.as_str()).map(|s| s.to_string()) {
            if let Some(id) = picture_id(pr, &g) {
                t.set("image", Value::Str(id));
            }
        }
    }
    v.sorted()
}

/// Every material as `inspect` shows them.
pub fn inspect_materials(pr: &Project) -> Value {
    let mut out = Map::new();
    if let Some(ms) = materials(pr) {
        for (k, m) in ms.iter() {
            out.insert(k, view(pr, m));
        }
    }
    Value::Obj(out).sorted()
}

/// The pictures as `inspect` shows them: `{id: {name, size: [w, h]}}`.
pub fn inspect_images(pr: &Project) -> Value {
    let mut out = Map::new();
    if let Some(imgs) = pr.section("images") {
        for (id, im) in imgs.iter() {
            let name = im.get("name").cloned().unwrap_or(Value::Null);
            let (w, h) = im
                .get("png")
                .and_then(|p| p.as_str())
                .and_then(crate::util::base64_decode)
                .map(|b| png_size(&b))
                .unwrap_or((0, 0));
            out.insert(id, jobj! {"name" => name, "size" => Value::Arr(vec![Value::u(w as u64), Value::u(h as u64)])});
        }
    }
    Value::Obj(out).sorted()
}

/// A PNG's size from its header.
pub fn png_size(b: &[u8]) -> (u32, u32) {
    if b.len() >= 24 {
        (u32::from_be_bytes(b[16..20].try_into().unwrap()), u32::from_be_bytes(b[20..24].try_into().unwrap()))
    } else {
        (0, 0)
    }
}

// ---------------------------------------------------------------- pictures

/// Adds a picture (if the project hasn't it already), as the 24th at most.
pub fn add_picture(pr: &mut Project, pic: &picture::Picture) -> Result<(), String> {
    let have = picture_ids(pr);
    if have.contains(&pic.id) {
        return Ok(());
    }
    if have.len() >= picture::MAX_PICTURES {
        return Err(format!(
            "the project holds {} pictures already; take a texture of one away first",
            picture::MAX_PICTURES
        ));
    }
    let entry = jobj! {"name" => pic.name.clone(), "png" => crate::util::base64_encode(&pic.png)};
    pr.section_mut("images").insert_sorted(&pic.id, entry);
    pr.lib_add("picture", &pic.id);
    Ok(())
}

/// Takes away the pictures no material's texture is made of (and `images` with the last).
pub fn drop_unused_pictures(pr: &mut Project) {
    let ids = picture_ids(pr);
    if ids.is_empty() {
        if pr.doc.contains("images") {
            pr.remove_top("images");
        }
        return;
    }
    let mut used: Vec<String> = Vec::new();
    if let Some(ms) = materials(pr) {
        for (_, m) in ms.iter() {
            if let Some(g) = m.get("texture").and_then(|t| t.get("image")).and_then(|x| x.as_str()) {
                used.push(g.to_string());
            }
        }
    }
    for id in ids {
        let g = picture_guid(pr, &id);
        let keep = g.as_ref().map(|g| used.contains(g)).unwrap_or(false);
        if !keep {
            if let Some(m) = pr.get_mut("images").and_then(|v| v.as_obj_mut()) {
                m.remove(&id);
            }
            if let Some(lid) = pr.lib_find("picture", &id) {
                pr.library.remove(&lid);
            }
        }
    }
    if picture_ids(pr).is_empty() {
        pr.remove_top("images");
    }
}

// ---------------------------------------------------------------- parameters

fn color_of(v: &Value) -> Option<[u8; 3]> {
    match v {
        Value::Str(s) => {
            let b = s.as_bytes();
            if b.len() != 7 || b[0] != b'#' || !s[1..].chars().all(|c| c.is_ascii_hexdigit()) {
                return None;
            }
            let h = |i: usize| u8::from_str_radix(&s[i..i + 2], 16).ok();
            Some([h(1)?, h(3)?, h(5)?])
        }
        Value::Arr(a) if a.len() == 3 => {
            let mut c = [0u8; 3];
            for (i, x) in a.iter().enumerate() {
                match x {
                    Value::Num(crate::json::Num::U(u)) if *u <= 255 => c[i] = *u as u8,
                    _ => return None,
                }
            }
            Some(c)
        }
        _ => None,
    }
}

pub fn color_value(c: [u8; 3]) -> Value {
    Value::Arr(vec![Value::u(c[0] as u64), Value::u(c[1] as u64), Value::u(c[2] as u64)])
}

/// `[a, b]` numbers, or one for both.
fn pair_of(v: &Value) -> Option<[f64; 2]> {
    match v {
        Value::Num(n) => {
            let x = n.as_f64();
            Some([x, x])
        }
        Value::Arr(a) if a.len() == 2 => Some([num_of(&a[0])?, num_of(&a[1])?]),
        _ => None,
    }
}

fn pair_value(p: [f64; 2]) -> Value {
    Value::Arr(vec![Value::f(p[0]), Value::f(p[1])])
}

/// A pattern by name: one drawn in code, or a fill pattern of the project's (by its GUID).
enum Pattern {
    Builtin(String),
    Fill(String),
}

fn pattern_of(pr: &Project, key: &str, v: &Value) -> Result<Pattern, String> {
    if let Value::Str(s) = v {
        if PATTERNS.contains(&s.as_str()) {
            return Ok(Pattern::Builtin(s.clone()));
        }
        if let Some(g) = fill_pattern_guid(pr, s) {
            return Ok(Pattern::Fill(g));
        }
    }
    Err(format!(
        "material: `{}`: {} isn't a pattern: one of none, solid, diagonal, crosshatch, horizontal, vertical, grid, brick, concrete, insulation, or a fill pattern of the project's",
        key,
        v.to_compact()
    ))
}

/// What the `texture` parameter says, read before anything is taken.
struct TextureParam {
    kind: String,
    size: Option<[f64; 2]>,
    offset: Option<[f64; 2]>,
    angle: Option<f64>,
    path: Option<String>,
    image: Option<String>,
}

const KINDS_TEXT: &str = "brick, block, boards, concrete, plaster, tile, roof, fabric, metal, insulation, image";

/// Reads the texture parameter, with the material's current texture kind to inherit when the
/// parameter gives none. The order of its errors is the original's: unknown field, kind (value,
/// then inherit or "needs a kind"), size/offset/angle format, `only image takes a path`, the
/// path's and image's types.
fn texture_param(v: &Value, old_kind: Option<&str>) -> Result<Option<TextureParam>, String> {
    let m = match v {
        Value::Null => return Ok(None),
        Value::Obj(m) => m,
        _ => return Err(format!("material: `texture` is {{kind, size?, angle?, offset?, path?}} or null, not {}", v.to_compact())),
    };
    for (k, _) in m.iter() {
        if !["kind", "size", "angle", "offset", "path", "image"].contains(&k.as_str()) {
            return Err(format!("material: texture: `{}` isn't one of kind, size, angle, offset, path, image", k));
        }
    }
    let kind = match m.get("kind") {
        None | Some(Value::Null) => match old_kind {
            Some(k) => k.to_string(),
            None => return Err(format!("material: a texture needs a `kind`: one of {}", KINDS_TEXT)),
        },
        Some(Value::Str(s)) if KINDS.contains(&s.as_str()) => s.clone(),
        Some(x) => return Err(format!("material: texture `kind`: {} isn't one of {}", x.to_compact(), KINDS_TEXT)),
    };
    let size = match m.get("size") {
        None | Some(Value::Null) => None,
        Some(x) => Some(pair_of(x).ok_or_else(|| format!("material: texture `size` is [a, b] numbers, or one, not {}", x.to_compact()))?),
    };
    let offset = match m.get("offset") {
        None | Some(Value::Null) => None,
        Some(x) => Some(pair_of(x).ok_or_else(|| format!("material: texture `offset` is [a, b] numbers, or one, not {}", x.to_compact()))?),
    };
    let angle = match m.get("angle") {
        None | Some(Value::Null) => None,
        Some(x) => Some(num_of(x).ok_or_else(|| format!("material: texture `angle` is a number of degrees, not {}", x.to_compact()))?),
    };
    let has_path = !matches!(m.get("path"), None | Some(Value::Null));
    let has_image = !matches!(m.get("image"), None | Some(Value::Null));
    if kind != "image" && (has_path || has_image) {
        return Err("material: only a texture of kind `image` takes a `path` or an `image`".into());
    }
    let path = match m.get("path") {
        None | Some(Value::Null) => None,
        Some(Value::Str(s)) => Some(s.clone()),
        Some(x) => return Err(format!("material: texture `path` is a file's path, not {}", x.to_compact())),
    };
    let image = match m.get("image") {
        None | Some(Value::Null) => None,
        Some(Value::Str(s)) => Some(s.clone()),
        Some(x) => return Err(format!("material: texture `image` is a picture's id, not {}", x.to_compact())),
    };
    Ok(Some(TextureParam { kind, size, offset, angle, path, image }))
}

/// A texture as the file holds it, read back.
struct Texture {
    kind: String,
    size: [f64; 2],
    angle: f64,
    offset: [f64; 2],
    /// the picture's GUID
    image: Option<String>,
}

fn texture_of(v: &Value) -> Option<Texture> {
    let kind = v.get("kind")?.as_str()?.to_string();
    let size = v.get("size").and_then(pair_of).unwrap_or_else(|| natural_size(&kind));
    let angle = v.get("angle").and_then(|x| x.as_f64()).unwrap_or(0.0);
    let offset = v.get("offset").and_then(pair_of).unwrap_or([0.0, 0.0]);
    let image = v.get("image").and_then(|x| x.as_str()).map(|s| s.to_string());
    Some(Texture { kind, size, angle, offset, image })
}

fn texture_value(t: &Texture) -> Value {
    let mut m = Map::new();
    m.insert("kind", Value::s(&t.kind));
    m.insert("size", pair_value(t.size));
    if t.angle != 0.0 {
        m.insert("angle", Value::f(t.angle));
    }
    if t.offset != [0.0, 0.0] {
        m.insert("offset", pair_value(t.offset));
    }
    if let Some(g) = &t.image {
        m.insert("image", Value::s(g));
    }
    Value::Obj(m)
}

/// A new material's fields.
pub fn new_material() -> Value {
    jobj! {"color" => color_value([200, 200, 200]), "cut" => "none", "surface" => "none"}
}

/// Puts a material's fields in the order the file has them.
pub fn ordered(m: &Value) -> Value {
    let mut out = Map::new();
    for k in ["color", "cut", "surface", "cut_pattern", "surface_pattern", "texture", "transparency"] {
        if let Some(v) = m.get(k) {
            out.insert(k, v.clone());
        }
    }
    if let Some(mm) = m.as_obj() {
        for (k, v) in mm.iter() {
            if !out.contains(k) {
                out.insert(k, v.clone());
            }
        }
    }
    Value::Obj(out)
}

// ---------------------------------------------------------------- what uses a material

/// What keeps a material from being taken away, as the command says it; None if nothing.
fn in_use(pr: &Project, name: &str, guid: &str) -> Option<String> {
    // the layers of types
    if let Some(types) = pr.section("types") {
        for (cat, ts) in types.iter() {
            if cat == "runs" {
                continue;
            }
            if let Some(ts) = ts.as_obj() {
                for (tn, t) in ts.iter() {
                    if let Some(layers) = t.get("layers").and_then(|l| l.as_arr()) {
                        if layers.iter().any(|l| l.get("material").and_then(|m| m.as_str()) == Some(guid)) {
                            return Some(format!(
                                "material: `{}` is in {} type `{}`'s layers; take it out of them first",
                                name,
                                type_word(cat),
                                tn
                            ));
                        }
                    }
                }
            }
        }
    }
    // families
    if let Some(fams) = pr.section("families") {
        let mut names: Vec<&String> = fams.keys().collect();
        names.sort();
        for fname in names {
            if mentions(fams.get(fname).unwrap(), guid) {
                return Some(format!("material: `{}` is in family `{}`; take it out of it first", name, fname));
            }
        }
    }
    // paint
    for (id, e) in &pr.elements {
        if let Some(p) = e.get("params").and_then(|p| p.get("Paint")).and_then(|p| p.as_obj()) {
            if p.iter().any(|(_, g)| g.as_str() == Some(guid)) {
                let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("element");
                return Some(format!("material: `{}` is in the paint of {} {}; take it out of it first", name, cat, id));
            }
        }
    }
    None
}

/// How a category's types are named in messages.
pub fn type_word(cat: &str) -> String {
    match cat {
        "structural_column" => "structural column".into(),
        c => c.to_string(),
    }
}

/// Whether a value holds this string anywhere.
fn mentions(v: &Value, s: &str) -> bool {
    match v {
        Value::Str(x) => x == s,
        Value::Arr(a) => a.iter().any(|x| mentions(x, s)),
        Value::Obj(m) => m.iter().any(|(_, x)| mentions(x, s)),
        _ => false,
    }
}

/// The run types (beams, pipes…) made of a material: they name it by name, and don't follow
/// it when it's renamed or taken away; the model check then refuses that.
fn run_type_error(pr: &Project, guid: &str, name: &str) -> Option<String> {
    let runs = pr.section("types")?.get("runs")?.as_obj()?;
    let mut cats: Vec<&String> = runs.keys().collect();
    cats.sort();
    for cat in cats {
        if let Some(ts) = runs.get(cat).and_then(|t| t.as_obj()) {
            let mut names: Vec<&String> = ts.keys().collect();
            names.sort();
            for tn in names {
                if ts.get(tn).and_then(|t| t.get("material")).and_then(|m| m.as_str()) == Some(guid) {
                    return Some(format!(
                        "{} type `{}`: material `{}` isn't in the library; add it with `material`",
                        cat, tn, name
                    ));
                }
            }
        }
    }
    None
}

// ---------------------------------------------------------------- the command

pub fn cmd(s: &mut Session, p: &Value) -> Result<Value, String> {
    let name = match opt_text(p, "material", "name")? {
        Some(n) if !n.trim().is_empty() => n.trim().to_string(),
        _ => return Err("material: `name` is required".into()),
    };
    let delete = opt_bool(p, "material", "delete")?.unwrap_or(false);
    let pr = &mut s.project;
    if delete {
        return delete_material(pr, &name);
    }
    // a new one is made first, its picture (if any) after it
    if material(pr, &name).is_none() {
        pr.section_mut("materials").insert_sorted(&name, new_material());
        if pr.lib_find("material", &name).is_none() {
            pr.lib_add("material", &name);
        }
    }
    let mut m = material(pr, &name).cloned().unwrap();
    // texture
    if given(p, "texture") {
        let tv = p.get("texture").unwrap();
        let old = m.get("texture").and_then(texture_of);
        match texture_param(tv, old.as_ref().map(|t| t.kind.as_str()))? {
            None => {
                m.remove("texture");
            }
            Some(tp) => {
                let t = make_texture(pr, old, &tp)?;
                m.set("texture", texture_value(&t));
            }
        }
    }
    // colour
    if let Some(v) = get(p, "color") {
        match color_of(v) {
            Some(c) => m.set("color", color_value(c)),
            None => {
                return Err(format!(
                    "material: `color` is \"#rrggbb\" or [r, g, b], each 0 to 255, not {}",
                    v.to_compact()
                ))
            }
        }
    }
    // transparency
    if let Some(v) = get(p, "transparency") {
        match v {
            Value::Num(crate::json::Num::U(u)) if *u <= 100 => {
                if *u == 0 {
                    m.remove("transparency");
                } else {
                    m.set("transparency", Value::u(*u));
                }
            }
            _ => return Err(format!("material: `transparency` is a whole percent, 0 to 100, not {}", v.to_compact())),
        }
    }
    // patterns
    for (key, extra) in [("cut", "cut_pattern"), ("surface", "surface_pattern")] {
        if let Some(v) = get(p, key) {
            match pattern_of(pr, key, v)? {
                Pattern::Builtin(b) => {
                    m.set(key, Value::Str(b));
                    m.remove(extra);
                }
                Pattern::Fill(g) => {
                    m.set(key, Value::s("none"));
                    m.set(extra, Value::Str(g));
                }
            }
        }
    }
    // rename
    let mut final_name = name.clone();
    if given(p, "rename") {
        if let Some(r) = opt_text(p, "material", "rename")? {
            let r = r.trim().to_string();
            if r.is_empty() {
                return Err("material: `rename` needs a name".into());
            }
            if r != name {
                if material(pr, &r).is_some() {
                    return Err(format!("material: the library already has `{}`", r));
                }
                final_name = r;
            }
        }
    }
    let m = ordered(&m);
    if final_name != name {
        let guid = material_guid(pr, &name).unwrap_or_default();
        if let Some(e) = run_type_error(pr, &guid, &name) {
            return Err(e);
        }
        pr.section_mut("materials").remove(&name);
        pr.section_mut("materials").insert_sorted(&final_name, m.clone());
        if let Some(lid) = pr.lib_find("material", &name) {
            if let Some(e) = pr.library.get_mut(&lid) {
                e.set("name", Value::s(&final_name));
            }
        }
    } else {
        pr.section_mut("materials").insert_sorted(&name, m.clone());
    }
    drop_unused_pictures(pr);
    let view = view(pr, &m);
    Ok(jobj! {"material" => view, "name" => final_name})
}

fn make_texture(pr: &mut Project, old: Option<Texture>, tp: &TextureParam) -> Result<Texture, String> {
    let same = old.as_ref().map(|t| t.kind == tp.kind).unwrap_or(false);
    let mut t = if same {
        old.unwrap()
    } else {
        Texture { kind: tp.kind.clone(), size: natural_size(&tp.kind), angle: 0.0, offset: [0.0, 0.0], image: None }
    };
    let mut wanted_image: Option<String> = None;
    if tp.kind == "image" {
        if let Some(path) = &tp.path {
            let pic = match picture::load(path) {
                Ok(p) => p,
                Err(picture::Fail::Msg(m)) => return Err(format!("material: {}", m)),
                Err(picture::Fail::Panic { at, msg }) => return Err(picture::panic_error("material", at, &msg)),
            };
            add_picture(pr, &pic).map_err(|e| format!("material: {}", e))?;
            t.image = picture_guid(pr, &pic.id);
            t.size = picture_size(pic.w, pic.h);
        } else if let Some(img) = &tp.image {
            wanted_image = Some(img.clone());
        } else if t.image.is_none() {
            return Err("material: a texture of a picture needs its file, `path`, or one of the project's, `image`".into());
        }
    }
    if let Some(sz) = tp.size {
        t.size = sz;
    }
    if let Some(a) = tp.angle {
        t.angle = a;
    }
    if let Some(o) = tp.offset {
        t.offset = o;
    }
    let ok = |x: f64| x.is_finite() && (1.0..=1_000_000.0).contains(&x);
    if !ok(t.size[0]) || !ok(t.size[1]) {
        return Err(format!(
            "material: texture: a tile of it is {} by {} mm; each side is 1 to 1000000 mm",
            disp(t.size[0]),
            disp(t.size[1])
        ));
    }
    // the offset is held in metres there
    let fine = t.angle.is_finite()
        && t.angle.abs() <= 1_000_000.0
        && t.offset.iter().all(|x| x.is_finite() && (x / 1000.0).abs() <= 1_000_000.0);
    if !fine {
        return Err("material: texture: its angle and its offset need to be numbers".into());
    }
    if let Some(img) = wanted_image {
        match picture_guid(pr, &img) {
            Some(g) if pr.section("images").map(|m| m.contains(&img)).unwrap_or(false) => t.image = Some(g),
            _ => {
                return Err(format!(
                    "material: texture: it's of picture `{}`, which the project doesn't hold (it has: {})",
                    img,
                    picture_ids(pr).join(", ")
                ))
            }
        }
    }
    Ok(t)
}

fn delete_material(pr: &mut Project, name: &str) -> Result<Value, String> {
    if material(pr, name).is_none() {
        return Err(format!("material: the library has no `{}`", name));
    }
    let guid = material_guid(pr, name).unwrap_or_default();
    if let Some(e) = in_use(pr, name, &guid) {
        return Err(e);
    }
    if let Some(e) = run_type_error(pr, &guid, name) {
        return Err(e);
    }
    pr.section_mut("materials").remove(name);
    if let Some(lid) = pr.lib_find("material", name) {
        pr.library.remove(&lid);
    }
    drop_unused_pictures(pr);
    Ok(jobj! {"deleted" => name})
}
