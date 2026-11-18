//! Text and dimension types: `text_type`, `dimension_type`, and the fonts they letter in.
//!
//! The fonts listed are Arial (which letters on any system, a metric twin or IBM Plex Sans standing
//! in where it isn't installed), the ones BIMCraft carries, and the families of the font files under
//! `~/.fonts`, `$XDG_DATA_HOME/fonts` (`~/.local/share/fonts`), `/usr/local/share/fonts` and
//! `/usr/share/fonts`, each named as its `name` table names it (the typographic family, else the
//! family; American English first), the first of two names that differ only in case kept.

use super::common::*;
use crate::commands::params::opt_num;
use crate::json::{Map, Num, Value};
use crate::project::Project;
use crate::session::Session;
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "text_type" => text_type(s, p),
        "dimension_type" => dimension_type(s, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

// ================================================================ fonts

/// The fonts BIMCraft carries: always there.
const BUNDLED: [&str; 3] = ["IBM Plex Sans", "IBM Plex Mono", "BIMCraft Lettering"];

/// Families a file may name that stand in for one another (each tried in this order after the
/// one named), then the system's like of them.
const STAND_INS: &[(&[&str], &str)] = &[
    (&["Arial", "Liberation Sans", "Arimo", "Helvetica", "Helvetica Neue", "Nimbus Sans"], "DejaVu Sans"),
    (&["Times New Roman", "Liberation Serif", "Tinos", "Times"], "DejaVu Serif"),
    (&["Courier New", "Liberation Mono", "Cousine", "Courier"], "DejaVu Sans Mono"),
    (&["Calibri", "Carlito"], ""),
    (&["Cambria", "Caladea"], ""),
];

/// What letters a font no family stands in for.
const LAST_RESORT: &str = "IBM Plex Sans";

/// How many fonts a refusal names.
const SUCH_AS: usize = 12;

struct Fonts {
    /// The families BIMCraft carries and this system has, the first of a name (case aside) kept.
    real: Vec<String>,
    /// What the listings show: Arial and those, sorted case aside.
    listed: Vec<String>,
}

fn fonts() -> &'static Fonts {
    static F: OnceLock<Fonts> = OnceLock::new();
    F.get_or_init(load_fonts)
}

fn push_family(list: &mut Vec<String>, name: String) {
    let low = name.to_lowercase();
    if !list.iter().any(|x| x.to_lowercase() == low) {
        list.push(name);
    }
}

fn load_fonts() -> Fonts {
    let mut real = Vec::new();
    for b in BUNDLED {
        push_family(&mut real, b.to_string());
    }
    for dir in font_dirs() {
        let mut seen = HashSet::new();
        scan_dir(&dir, &mut real, &mut seen, 0);
    }
    let mut listed = vec!["Arial".to_string()];
    for r in &real {
        push_family(&mut listed, r.clone());
    }
    listed.sort_by_key(|a| a.to_lowercase());
    Fonts { real, listed }
}

/// Where the system keeps fonts, the user's first.
fn font_dirs() -> Vec<PathBuf> {
    let home = std::env::var_os("HOME").map(PathBuf::from);
    let mut v = Vec::new();
    if let Some(h) = &home {
        v.push(h.join(".fonts"));
    }
    match std::env::var("XDG_DATA_HOME") {
        Ok(x) => v.push(PathBuf::from(x).join("fonts")),
        Err(_) => {
            if let Some(h) = &home {
                v.push(h.join(".local/share/fonts"));
            }
        }
    }
    v.push(PathBuf::from("/usr/local/share/fonts"));
    v.push(PathBuf::from("/usr/share/fonts"));
    v
}

fn is_font_file(p: &Path) -> bool {
    match p.extension().and_then(|e| e.to_str()) {
        Some(e) => matches!(e.to_ascii_lowercase().as_str(), "ttf" | "ttc" | "otf" | "otc"),
        None => false,
    }
}

/// A directory's fonts, its subdirectories' in turn (a link to a directory isn't followed; a link
/// to a file named as a font is read).
fn scan_dir(dir: &Path, out: &mut Vec<String>, seen: &mut HashSet<PathBuf>, depth: usize) {
    if depth > 64 || !seen.insert(dir.to_path_buf()) {
        return;
    }
    let Ok(rd) = std::fs::read_dir(dir) else { return };
    for e in rd.flatten() {
        let path = e.path();
        let Ok(ft) = e.file_type() else { continue };
        if ft.is_dir() {
            scan_dir(&path, out, seen, depth + 1);
        } else if is_font_file(&path) {
            read_font_file(&path, out);
        }
    }
}

fn read_font_file(path: &Path, out: &mut Vec<String>) {
    let Ok(data) = std::fs::read(path) else { return };
    for f in families_in(&data) {
        push_family(out, f);
    }
}

fn be16(d: &[u8], at: usize) -> Option<usize> {
    let b = d.get(at..at + 2)?;
    Some(((b[0] as usize) << 8) | b[1] as usize)
}

fn be32(d: &[u8], at: usize) -> Option<usize> {
    let b = d.get(at..at + 4)?;
    Some(((b[0] as usize) << 24) | ((b[1] as usize) << 16) | ((b[2] as usize) << 8) | b[3] as usize)
}

/// The family of each face of a font file (a collection has several).
fn families_in(data: &[u8]) -> Vec<String> {
    let mut out = Vec::new();
    let Some(tag) = be32(data, 0) else { return out };
    if tag == 0x7474_6366 {
        // ttcf
        let n = be32(data, 8).unwrap_or(0);
        for i in 0..n.min(4096) {
            if let Some(off) = be32(data, 12 + 4 * i) {
                if let Some(f) = face_family(data, off) {
                    out.push(f);
                }
            }
        }
    } else if let Some(f) = face_family(data, 0) {
        out.push(f);
    }
    out
}

fn face_family(data: &[u8], off: usize) -> Option<String> {
    let magic = be32(data, off)?;
    if !matches!(magic, 0x0001_0000 | 0x4F54_544F | 0x7472_7565) {
        return None;
    }
    let n = be16(data, off + 4)?;
    for i in 0..n {
        let rec = off + 12 + 16 * i;
        if data.get(rec..rec + 4)? == b"name" {
            let o = be32(data, rec + 8)?;
            let l = be32(data, rec + 12)?;
            return name_family(data.get(o..o.checked_add(l)?)?);
        }
    }
    None
}

struct NameRec<'a> {
    platform: usize,
    encoding: usize,
    language: usize,
    id: usize,
    bytes: &'a [u8],
}

impl NameRec<'_> {
    fn is_unicode(&self) -> bool {
        self.platform == 0 || (self.platform == 3 && matches!(self.encoding, 1 | 10))
    }
    fn is_mac_roman(&self) -> bool {
        self.platform == 1 && self.encoding == 0
    }
    fn english_us(&self) -> bool {
        (self.platform == 3 && self.language == 0x0409) || (self.platform == 1 && self.encoding == 0 && self.language == 0)
    }
    fn text(&self) -> Option<String> {
        if self.is_unicode() {
            let units: Vec<u16> = self.bytes.chunks_exact(2).map(|c| ((c[0] as u16) << 8) | c[1] as u16).collect();
            String::from_utf16(&units).ok()
        } else if self.is_mac_roman() {
            Some(self.bytes.iter().map(|b| mac_roman(*b)).collect())
        } else {
            None
        }
    }
}

const MAC_ROMAN_HIGH: [u16; 128] = [
    0x00C4, 0x00C5, 0x00C7, 0x00C9, 0x00D1, 0x00D6, 0x00DC, 0x00E1, 0x00E0, 0x00E2, 0x00E4, 0x00E3, 0x00E5, 0x00E7,
    0x00E9, 0x00E8, 0x00EA, 0x00EB, 0x00ED, 0x00EC, 0x00EE, 0x00EF, 0x00F1, 0x00F3, 0x00F2, 0x00F4, 0x00F6, 0x00F5,
    0x00FA, 0x00F9, 0x00FB, 0x00FC, 0x2020, 0x00B0, 0x00A2, 0x00A3, 0x00A7, 0x2022, 0x00B6, 0x00DF, 0x00AE, 0x00A9,
    0x2122, 0x00B4, 0x00A8, 0x2260, 0x00C6, 0x00D8, 0x221E, 0x00B1, 0x2264, 0x2265, 0x00A5, 0x00B5, 0x2202, 0x2211,
    0x220F, 0x03C0, 0x222B, 0x00AA, 0x00BA, 0x03A9, 0x00E6, 0x00F8, 0x00BF, 0x00A1, 0x00AC, 0x221A, 0x0192, 0x2248,
    0x2206, 0x00AB, 0x00BB, 0x2026, 0x00A0, 0x00C0, 0x00C3, 0x00D5, 0x0152, 0x0153, 0x2013, 0x2014, 0x201C, 0x201D,
    0x2018, 0x2019, 0x00F7, 0x25CA, 0x00FF, 0x0178, 0x2044, 0x20AC, 0x2039, 0x203A, 0xFB01, 0xFB02, 0x2021, 0x00B7,
    0x201A, 0x201E, 0x2030, 0x00C2, 0x00CA, 0x00C1, 0x00CB, 0x00C8, 0x00CD, 0x00CE, 0x00CF, 0x00CC, 0x00D3, 0x00D4,
    0xF8FF, 0x00D2, 0x00DA, 0x00DB, 0x00D9, 0x0131, 0x02C6, 0x02DC, 0x00AF, 0x02D8, 0x02D9, 0x02DA, 0x00B8, 0x02DD,
    0x02DB, 0x02C7,
];

fn mac_roman(b: u8) -> char {
    if b < 0x80 {
        b as char
    } else {
        char::from_u32(MAC_ROMAN_HIGH[(b - 0x80) as usize] as u32).unwrap_or('\u{fffd}')
    }
}

/// A face's family from its `name` table: the typographic family's names, else the family's
/// (Unicode ones, and a Mac Roman one where none is American English), American English first.
fn name_family(t: &[u8]) -> Option<String> {
    let count = be16(t, 2)?;
    let storage = be16(t, 4)?;
    let mut recs = Vec::new();
    for i in 0..count {
        let r = 6 + 12 * i;
        let (Some(platform), Some(encoding), Some(language), Some(id), Some(len), Some(off)) =
            (be16(t, r), be16(t, r + 2), be16(t, r + 4), be16(t, r + 6), be16(t, r + 8), be16(t, r + 10))
        else {
            break;
        };
        let Some(bytes) = t.get(storage + off..storage + off + len) else { break };
        recs.push(NameRec { platform, encoding, language, id, bytes });
    }
    let collect = |id: usize| -> Vec<(String, bool)> {
        let mut v = Vec::new();
        for r in recs.iter().filter(|r| r.id == id && r.is_unicode()) {
            if let Some(s) = r.text() {
                v.push((s, r.english_us()));
            }
        }
        if !v.iter().any(|x| x.1) {
            for r in recs.iter().filter(|r| r.id == id && r.is_mac_roman()) {
                if let Some(s) = r.text() {
                    v.push((s, r.english_us()));
                    break;
                }
            }
        }
        v
    };
    let mut fams = collect(16);
    if fams.is_empty() {
        fams = collect(1);
    }
    if fams.len() > 1 {
        if let Some(i) = fams.iter().position(|f| f.1) {
            fams.swap(0, i);
        }
    }
    fams.into_iter().next().map(|f| f.0)
}

/// The family a font is drawn with here: its own, else the first of its stand-ins the system has,
/// else IBM Plex Sans.
fn drawn_with(font: &str) -> String {
    let f = fonts();
    let find = |name: &str| {
        let low = name.to_lowercase();
        f.real.iter().find(|r| r.to_lowercase() == low).cloned()
    };
    if let Some(x) = find(font) {
        return x;
    }
    let low = font.to_lowercase();
    for (group, like) in STAND_INS {
        if group.iter().any(|g| g.to_lowercase() == low) {
            for g in group.iter() {
                if let Some(x) = find(g) {
                    return x;
                }
            }
            if !like.is_empty() {
                if let Some(x) = find(like) {
                    return x;
                }
            }
        }
    }
    LAST_RESORT.to_string()
}

/// A font a command names, as the listing names it (or as its stand-in table does).
fn known_font(q: &str) -> Option<String> {
    let low = q.to_lowercase();
    if let Some(x) = fonts().listed.iter().find(|x| x.to_lowercase() == low) {
        return Some(x.clone());
    }
    for (group, _) in STAND_INS {
        if let Some(g) = group.iter().find(|g| g.to_lowercase() == low) {
            return Some(g.to_string());
        }
    }
    None
}

/// The fonts a refusal offers: those its first word is part of, else all, at most 12.
fn such_as(q: &str) -> Vec<String> {
    let listed = &fonts().listed;
    let word = q.split_whitespace().next().unwrap_or("").to_lowercase();
    let mut v: Vec<String> = listed.iter().filter(|x| x.to_lowercase().contains(&word)).cloned().collect();
    if v.is_empty() {
        v = listed.clone();
    }
    v.truncate(SUCH_AS);
    v
}

fn fonts_value() -> Value {
    Value::Arr(fonts().listed.iter().map(|s| Value::s(s)).collect())
}

// ================================================================ the elements of a type

/// The first element of a category whose `type` is this GUID.
fn first_of_type(pr: &Project, cat: &str, guid: &Option<String>) -> Option<u64> {
    let g = guid.as_ref()?;
    pr.elements
        .iter()
        .find(|(_, e)| {
            e.get("category").and_then(|c| c.as_str()) == Some(cat) && e.get("type").and_then(|t| t.as_str()) == Some(g.as_str())
        })
        .map(|(id, _)| *id)
}

// ================================================================ text types

const TEXT_KIND: &str = "text-type";
const TEXT_PARAMS: &[&str] = &[
    "name",
    "like",
    "rename",
    "delete",
    "font",
    "size",
    "bold",
    "italic",
    "underline",
    "width_factor",
    "color",
    "border",
    "border_offset",
    "border_pen",
];

#[derive(Clone)]
struct TextType {
    font: String,
    size: f64,
    bold: bool,
    italic: bool,
    underline: bool,
    width_factor: f64,
    color: [u8; 3],
    border: bool,
    border_offset: f64,
    border_pen: u64,
}

fn num_in(v: &Value, k: &str, d: f64) -> f64 {
    v.get(k).and_then(|x| x.as_f64()).unwrap_or(d)
}

fn bool_in(v: &Value, k: &str, d: bool) -> bool {
    v.get(k).and_then(|x| x.as_bool()).unwrap_or(d)
}

fn str_in(v: &Value, k: &str, d: &str) -> String {
    v.get(k).and_then(|x| x.as_str()).unwrap_or(d).to_string()
}

fn pen_in(v: &Value, k: &str, d: u64) -> u64 {
    v.get(k).and_then(|x| x.as_f64()).and_then(pen_of).unwrap_or(d)
}

impl TextType {
    fn default() -> TextType {
        TextType {
            font: "Arial".into(),
            size: 2.5,
            bold: false,
            italic: false,
            underline: false,
            width_factor: 1.0,
            color: [0, 0, 0],
            border: false,
            border_offset: 1.0,
            border_pen: 1,
        }
    }

    fn from_json(v: &Value) -> TextType {
        let d = TextType::default();
        TextType {
            font: str_in(v, "font", &d.font),
            size: num_in(v, "size", d.size),
            bold: bool_in(v, "bold", false),
            italic: bool_in(v, "italic", false),
            underline: bool_in(v, "underline", false),
            width_factor: num_in(v, "width_factor", 1.0),
            color: v.get("color").and_then(color_of).unwrap_or([0, 0, 0]),
            border: bool_in(v, "border", false),
            border_offset: num_in(v, "border_offset", 1.0),
            border_pen: pen_in(v, "border_pen", 1),
        }
    }

    fn to_json(&self) -> Value {
        let mut m = Map::new();
        m.insert("font", Value::s(&self.font));
        m.insert("size", Value::f(self.size));
        if self.bold {
            m.insert("bold", Value::Bool(true));
        }
        if self.italic {
            m.insert("italic", Value::Bool(true));
        }
        if self.underline {
            m.insert("underline", Value::Bool(true));
        }
        if self.width_factor != 1.0 {
            m.insert("width_factor", Value::f(self.width_factor));
        }
        m.insert("color", color_value(self.color));
        if self.border {
            m.insert("border", Value::Bool(true));
        }
        m.insert("border_offset", Value::f(self.border_offset));
        m.insert("border_pen", Value::u(self.border_pen));
        Value::Obj(m)
    }
}

fn default_text_types() -> Map {
    let mut m = Map::new();
    for (n, size) in [("2.5mm", 2.5), ("3.5mm", 3.5), ("5mm", 5.0)] {
        let mut t = TextType::default();
        t.size = size;
        m.insert(n, t.to_json());
    }
    m
}

/// The project's text types, as its file holds them (a project without any starts with three).
fn text_types(pr: &Project) -> Map {
    match pr.section("text_types") {
        Some(m) => m.clone(),
        None => default_text_types(),
    }
}

fn text_types_mut(pr: &mut Project) -> &mut Map {
    if pr.section("text_types").is_none() {
        pr.insert_top("text_types", Value::Obj(default_text_types()));
    }
    pr.section_mut("text_types")
}

fn text_type(s: &mut Session, p: &Value) -> R<Value> {
    const CMD: &str = "text_type";
    check_keys(p, CMD, TEXT_PARAMS)?;
    let Some(name) = opt_name(p, CMD, "name")? else {
        return Ok(text_listing(&s.project));
    };
    let pr = &mut s.project;
    let types = text_types(pr);
    let delete = opt_bool(p, CMD, "delete")?;
    if delete == Some(true) {
        if !types.contains(&name) {
            return Err(format!("{}: there's no text type `{}`", CMD, name));
        }
        let guid = pr.lib_guid(TEXT_KIND, &name);
        if let Some(id) = first_of_type(pr, "text", &guid) {
            return Err(format!("{}: note {} is of `{}`; give it another type first", CMD, id, name));
        }
        text_types_mut(pr).remove(&name);
        lib_remove(pr, TEXT_KIND, &name);
        super::mark_step();
        return Ok(jobj! {"deleted" => name});
    }
    let like = opt_name(p, CMD, "like")?;
    let exists = types.contains(&name);
    let mut t = if exists {
        TextType::from_json(types.get(&name).unwrap())
    } else if let Some(l) = &like {
        match types.get(l) {
            Some(v) => TextType::from_json(v),
            None => return Err(format!("{}: there's no text type `{}` to start from", CMD, l)),
        }
    } else {
        TextType::default()
    };
    if let Some(q) = opt_name(p, CMD, "font")? {
        match known_font(&q) {
            Some(f) => t.font = f,
            None => {
                return Err(format!(
                    "{}: this system has no font `{}` (it has {}, such as: {}); `text_type` without `name` lists them",
                    CMD,
                    q,
                    fonts().listed.len(),
                    such_as(&q).join(", ")
                ))
            }
        }
    }
    if let Some(x) = opt_num(p, CMD, "size")? {
        t.size = x;
    }
    if let Some(x) = opt_num(p, CMD, "width_factor")? {
        t.width_factor = x;
    }
    if let Some(x) = opt_num(p, CMD, "border_offset")? {
        t.border_offset = x;
    }
    if let Some(x) = opt_bool(p, CMD, "bold")? {
        t.bold = x;
    }
    if let Some(x) = opt_bool(p, CMD, "italic")? {
        t.italic = x;
    }
    if let Some(x) = opt_bool(p, CMD, "underline")? {
        t.underline = x;
    }
    if let Some(x) = opt_bool(p, CMD, "border")? {
        t.border = x;
    }
    if let Some(x) = opt_color(p, CMD, "color")? {
        t.color = x;
    }
    if let Some(x) = opt_pen(p, CMD, "border_pen")? {
        t.border_pen = x;
    }
    let mut final_name = name.clone();
    if let Some(r) = opt_name(p, CMD, "rename")? {
        if r != name {
            if types.contains(&r) {
                return Err(format!("{}: there's already a text type `{}`", CMD, r));
            }
            final_name = r;
        }
    }
    validate_text(&t, &final_name).map_err(|e| format!("{}: {}", CMD, e))?;
    let sec = text_types_mut(pr);
    if final_name != name {
        sec.remove(&name);
    }
    sec.insert_sorted(&final_name, t.to_json());
    if exists {
        if final_name != name {
            lib_rename(pr, TEXT_KIND, &name, &final_name);
        }
        if pr.lib_find(TEXT_KIND, &final_name).is_none() {
            pr.lib_add(TEXT_KIND, &final_name);
        }
    } else {
        lib_ensure(pr, TEXT_KIND, &final_name);
    }
    super::mark_step();
    Ok(jobj! {"name" => final_name, "type" => t.to_json()})
}

/// A font's name is up to 256 characters.
fn font_ok(f: &str) -> bool {
    !f.is_empty() && f.chars().count() <= 256
}

/// A text type's rules: "text type `X`: …".
fn validate_text(t: &TextType, name: &str) -> R<()> {
    let label = format!("text type `{}`", name);
    if !font_ok(&t.font) {
        return Err(format!("{}: a font is named by up to 256 characters", label));
    }
    if !(t.size > 0.0 && t.size <= 100.0) {
        return Err(format!("{}: its size, {} mm, isn't above 0 and at most 100", label, disp(t.size)));
    }
    if !(t.width_factor >= 0.1 && t.width_factor <= 10.0) {
        return Err(format!("{}: its width factor, {}, isn't from 0.1 to 10", label, disp(t.width_factor)));
    }
    if !(t.border_offset >= 0.0 && t.border_offset <= 50.0) {
        return Err(format!("{}: its border offset, {} mm, isn't from 0 to 50", label, disp(t.border_offset)));
    }
    Ok(())
}

fn text_listing(pr: &Project) -> Value {
    let types = text_types(pr);
    let mut drawn = Map::new();
    let mut out = Map::new();
    for (n, v) in &types.items {
        let t = TextType::from_json(v);
        drawn.insert(n, Value::s(&drawn_with(&t.font)));
        out.insert(n, t.to_json());
    }
    jobj! {"drawn_with" => Value::Obj(drawn), "fonts" => fonts_value(), "types" => Value::Obj(out)}
}

// ================================================================ dimension types

const DIM_KIND: &str = "dimension-type";

const DIM_FIELDS: [&str; 27] = [
    "string",
    "tick",
    "tick_size",
    "line_pen",
    "tick_pen",
    "color",
    "line_extension",
    "witness",
    "witness_length",
    "witness_gap",
    "witness_extension",
    "baseline_spacing",
    "centre_mark",
    "font",
    "text_size",
    "bold",
    "italic",
    "underline",
    "width_factor",
    "text_offset",
    "background",
    "read",
    "units",
    "decimals",
    "radius_symbol",
    "diameter_symbol",
    "equality_text",
];

const STRINGS: [&str; 3] = ["continuous", "baseline", "ordinate"];
const TICKS: [&str; 5] = ["diagonal", "arrow", "open_arrow", "dot", "none"];
const WITNESS: [&str; 2] = ["gap_to_element", "fixed"];
const BACKGROUNDS: [&str; 2] = ["opaque", "transparent"];
const READS: [&str; 2] = ["up_then_left", "up_then_right"];
const UNITS: [&str; 6] = ["mm", "cm", "m", "in", "ft", "ft-in"];

#[derive(Clone)]
struct DimType {
    string: String,
    tick: String,
    tick_size: f64,
    line_pen: u64,
    tick_pen: u64,
    color: [u8; 3],
    line_extension: f64,
    witness: String,
    witness_length: f64,
    witness_gap: f64,
    witness_extension: f64,
    baseline_spacing: f64,
    centre_mark: bool,
    font: String,
    text_size: f64,
    bold: bool,
    italic: bool,
    underline: bool,
    width_factor: f64,
    text_offset: f64,
    background: String,
    read: String,
    units: Option<String>,
    decimals: Option<u64>,
    radius_symbol: String,
    diameter_symbol: String,
    equality_text: String,
}

impl DimType {
    /// A new dimension type's values (`Diagonal - 2.5mm Arial`'s as a project starts).
    fn default() -> DimType {
        DimType {
            string: "continuous".into(),
            tick: "diagonal".into(),
            tick_size: 2.0,
            line_pen: 4,
            tick_pen: 7,
            color: [0, 0, 0],
            line_extension: 0.8,
            witness: "gap_to_element".into(),
            witness_length: 5.0,
            witness_gap: 0.6,
            witness_extension: 0.8,
            baseline_spacing: 7.0,
            centre_mark: true,
            font: "Arial".into(),
            text_size: 2.5,
            bold: false,
            italic: false,
            underline: false,
            width_factor: 1.0,
            text_offset: 1.0,
            background: "opaque".into(),
            read: "up_then_left".into(),
            units: None,
            decimals: None,
            radius_symbol: "R".into(),
            diameter_symbol: "Ø".into(),
            equality_text: "EQ".into(),
        }
    }

    fn arrow() -> DimType {
        let mut d = DimType::default();
        d.tick = "arrow".into();
        d.tick_size = 2.5;
        d
    }

    fn from_json(v: &Value) -> DimType {
        let d = DimType::default();
        DimType {
            string: str_in(v, "string", &d.string),
            tick: str_in(v, "tick", &d.tick),
            tick_size: num_in(v, "tick_size", d.tick_size),
            line_pen: pen_in(v, "line_pen", d.line_pen),
            tick_pen: pen_in(v, "tick_pen", d.tick_pen),
            color: v.get("color").and_then(color_of).unwrap_or(d.color),
            line_extension: num_in(v, "line_extension", d.line_extension),
            witness: str_in(v, "witness", &d.witness),
            witness_length: num_in(v, "witness_length", d.witness_length),
            witness_gap: num_in(v, "witness_gap", d.witness_gap),
            witness_extension: num_in(v, "witness_extension", d.witness_extension),
            baseline_spacing: num_in(v, "baseline_spacing", d.baseline_spacing),
            centre_mark: bool_in(v, "centre_mark", d.centre_mark),
            font: str_in(v, "font", &d.font),
            text_size: num_in(v, "text_size", d.text_size),
            bold: bool_in(v, "bold", false),
            italic: bool_in(v, "italic", false),
            underline: bool_in(v, "underline", false),
            width_factor: num_in(v, "width_factor", d.width_factor),
            text_offset: num_in(v, "text_offset", d.text_offset),
            background: str_in(v, "background", &d.background),
            read: str_in(v, "read", &d.read),
            units: v.get("units").and_then(|x| x.as_str()).map(|s| s.to_string()),
            decimals: v.get("decimals").and_then(|x| x.as_u64()),
            radius_symbol: str_in(v, "radius_symbol", &d.radius_symbol),
            diameter_symbol: str_in(v, "diameter_symbol", &d.diameter_symbol),
            equality_text: str_in(v, "equality_text", &d.equality_text),
        }
    }

    fn to_json(&self) -> Value {
        let mut m = Map::new();
        m.insert("string", Value::s(&self.string));
        m.insert("tick", Value::s(&self.tick));
        m.insert("tick_size", Value::f(self.tick_size));
        m.insert("line_pen", Value::u(self.line_pen));
        m.insert("tick_pen", Value::u(self.tick_pen));
        m.insert("color", color_value(self.color));
        m.insert("line_extension", Value::f(self.line_extension));
        m.insert("witness", Value::s(&self.witness));
        m.insert("witness_length", Value::f(self.witness_length));
        m.insert("witness_gap", Value::f(self.witness_gap));
        m.insert("witness_extension", Value::f(self.witness_extension));
        m.insert("baseline_spacing", Value::f(self.baseline_spacing));
        m.insert("centre_mark", Value::Bool(self.centre_mark));
        m.insert("font", Value::s(&self.font));
        m.insert("text_size", Value::f(self.text_size));
        if self.bold {
            m.insert("bold", Value::Bool(true));
        }
        if self.italic {
            m.insert("italic", Value::Bool(true));
        }
        if self.underline {
            m.insert("underline", Value::Bool(true));
        }
        m.insert("width_factor", Value::f(self.width_factor));
        m.insert("text_offset", Value::f(self.text_offset));
        m.insert("background", Value::s(&self.background));
        m.insert("read", Value::s(&self.read));
        if let Some(u) = &self.units {
            m.insert("units", Value::s(u));
        }
        if let Some(d) = self.decimals {
            m.insert("decimals", Value::u(d));
        }
        m.insert("radius_symbol", Value::s(&self.radius_symbol));
        m.insert("diameter_symbol", Value::s(&self.diameter_symbol));
        m.insert("equality_text", Value::s(&self.equality_text));
        Value::Obj(m)
    }
}

fn default_dimension_types() -> Map {
    let mut m = Map::new();
    m.insert("Arrow - 2.5mm Arial", DimType::arrow().to_json());
    m.insert("Diagonal - 2.5mm Arial", DimType::default().to_json());
    m
}

fn dimension_types(pr: &Project) -> Map {
    match pr.section("dimension_types") {
        Some(m) => m.clone(),
        None => default_dimension_types(),
    }
}

fn dimension_types_mut(pr: &mut Project) -> &mut Map {
    if pr.section("dimension_types").is_none() {
        pr.insert_top("dimension_types", Value::Obj(default_dimension_types()));
    }
    pr.section_mut("dimension_types")
}

/// serde's words for a list of what it expected: `a`, `a` or `b`, one of `a`, `b`, `c`.
fn one_of(names: &[&str]) -> String {
    match names.len() {
        0 => "there are no variants".into(),
        1 => format!("`{}`", names[0]),
        2 => format!("`{}` or `{}`", names[0], names[1]),
        _ => format!("one of {}", names.iter().map(|n| format!("`{}`", n)).collect::<Vec<_>>().join(", ")),
    }
}

/// A unit variant of an enum, as serde reads one from JSON: its name, or a map of it to null.
fn variant_of(v: &Value, variants: &[&str]) -> Result<String, String> {
    let unknown = |s: &str| format!("unknown variant `{}`, expected {}", s, one_of(variants));
    match v {
        Value::Str(s) => {
            if variants.contains(&s.as_str()) {
                Ok(s.clone())
            } else {
                Err(unknown(s))
            }
        }
        Value::Obj(m) => {
            if m.items.len() != 1 {
                return Err("invalid value: map, expected map with a single key".into());
            }
            let (k, x) = &m.items[0];
            if !variants.contains(&k.as_str()) {
                return Err(unknown(k));
            }
            match x {
                Value::Null => Ok(k.clone()),
                other => Err(invalid_type(other, "unit")),
            }
        }
        other => Err(invalid_type(other, "string or map")),
    }
}

fn bool_of(v: &Value) -> Result<bool, String> {
    match v {
        Value::Bool(b) => Ok(*b),
        other => Err(invalid_type(other, "a boolean")),
    }
}

fn string_of(v: &Value) -> Result<String, String> {
    match v {
        Value::Str(s) => Ok(s.clone()),
        other => Err(invalid_type(other, "a string")),
    }
}

fn u8_of(v: &Value) -> Result<u64, String> {
    match v {
        Value::Num(Num::U(u)) if *u <= 255 => Ok(*u),
        Value::Num(Num::U(u)) => Err(format!("invalid value: integer `{}`, expected u8", u)),
        Value::Num(Num::I(i)) => Err(format!("invalid value: integer `{}`, expected u8", i)),
        other => Err(invalid_type(other, "u8")),
    }
}

fn dim_pen(v: &Value) -> Result<u64, String> {
    let x = f64_of(v)?;
    pen_of(x).ok_or_else(|| format!("a line weight is a pen, a whole number from 0 (a hairline) to 16, not {}", disp(x)))
}

/// Reads one of a dimension type's values onto it, as serde reads the type's fields.
fn dim_field(t: &mut DimType, k: &str, v: &Value) -> Result<(), String> {
    match k {
        "string" => t.string = variant_of(v, &STRINGS)?,
        "tick" => t.tick = variant_of(v, &TICKS)?,
        "witness" => t.witness = variant_of(v, &WITNESS)?,
        "background" => t.background = variant_of(v, &BACKGROUNDS)?,
        "read" => t.read = variant_of(v, &READS)?,
        "units" => {
            t.units = match v {
                Value::Null => None,
                _ => Some(variant_of(v, &UNITS)?),
            }
        }
        "decimals" => {
            t.decimals = match v {
                Value::Null => None,
                _ => Some(u8_of(v)?),
            }
        }
        "tick_size" => t.tick_size = f64_of(v)?,
        "line_extension" => t.line_extension = f64_of(v)?,
        "witness_length" => t.witness_length = f64_of(v)?,
        "witness_gap" => t.witness_gap = f64_of(v)?,
        "witness_extension" => t.witness_extension = f64_of(v)?,
        "baseline_spacing" => t.baseline_spacing = f64_of(v)?,
        "text_size" => t.text_size = f64_of(v)?,
        "width_factor" => t.width_factor = f64_of(v)?,
        "text_offset" => t.text_offset = f64_of(v)?,
        "line_pen" => t.line_pen = dim_pen(v)?,
        "tick_pen" => t.tick_pen = dim_pen(v)?,
        "centre_mark" => t.centre_mark = bool_of(v)?,
        "bold" => t.bold = bool_of(v)?,
        "italic" => t.italic = bool_of(v)?,
        "underline" => t.underline = bool_of(v)?,
        "radius_symbol" => t.radius_symbol = string_of(v)?,
        "diameter_symbol" => t.diameter_symbol = string_of(v)?,
        "equality_text" => t.equality_text = string_of(v)?,
        "color" => {
            // a colour given was read before; null is no colour
            if v.is_null() {
                return Err(invalid_type(v, "an array of length 3"));
            }
        }
        "font" => {}
        _ => return Err(format!("unknown field `{}`, expected {}", k, one_of(&DIM_FIELDS))),
    }
    Ok(())
}

fn symbol_ok(s: &str) -> bool {
    s.chars().count() <= 200 && !s.chars().any(|c| c.is_control())
}

/// A dimension type's rules: "dimension type `X`: …".
fn validate_dim(t: &DimType, name: &str) -> R<()> {
    let label = format!("dimension type `{}`", name);
    if !font_ok(&t.font) {
        return Err(format!("{}: a font is named by up to 256 characters", label));
    }
    if !(t.text_size > 0.0 && t.text_size <= 100.0) {
        return Err(format!("{}: its text size, {} mm, isn't above 0 and at most 100", label, disp(t.text_size)));
    }
    if !(t.width_factor >= 0.1 && t.width_factor <= 10.0) {
        return Err(format!("{}: its width factor, {}, isn't from 0.1 to 10", label, disp(t.width_factor)));
    }
    for (x, what) in [
        (t.tick_size, "tick size"),
        (t.line_extension, "dimension line extension"),
        (t.witness_length, "witness line length"),
        (t.witness_gap, "witness line gap"),
        (t.witness_extension, "witness line extension"),
        (t.baseline_spacing, "baseline spacing"),
        (t.text_offset, "text offset"),
    ] {
        if !(x >= 0.0 && x <= 50.0) {
            return Err(format!("{}: its {}, {} mm on paper, isn't from 0 to 50", label, what, disp(x)));
        }
    }
    if let Some(d) = t.decimals {
        if d > 6 {
            return Err(format!("{}: it rounds to at most 6 places, not {}", label, d));
        }
    }
    for (s, what) in [
        (&t.radius_symbol, "radius symbol"),
        (&t.diameter_symbol, "diameter symbol"),
        (&t.equality_text, "equality text"),
    ] {
        if !symbol_ok(s) {
            return Err(format!("{}: its {} is up to 200 characters on one line", label, what));
        }
    }
    Ok(())
}

fn dimension_type(s: &mut Session, p: &Value) -> R<Value> {
    const CMD: &str = "dimension_type";
    let Some(name) = opt_name(p, CMD, "name")? else {
        return Ok(dimension_listing(&s.project));
    };
    let pr = &mut s.project;
    let types = dimension_types(pr);
    let delete = opt_bool(p, CMD, "delete")?;
    if delete == Some(true) {
        if !types.contains(&name) {
            return Err(format!("{}: there's no dimension type `{}`", CMD, name));
        }
        let guid = pr.lib_guid(DIM_KIND, &name);
        if let Some(id) = first_of_type(pr, "dimension", &guid) {
            return Err(format!("{}: dimension {} is of `{}`; give it another type first", CMD, id, name));
        }
        dimension_types_mut(pr).remove(&name);
        lib_remove(pr, DIM_KIND, &name);
        // a dimension in a 3D view isn't asked after; the model's check then finds it without one
        if let Some(id) = first_of_type(pr, "dimension3d", &guid) {
            let left: Vec<String> = dimension_types(pr).keys().cloned().collect();
            return Err(super::check_error(format!(
                "dimension3d {}: there's no dimension type `{}` (there are: {})",
                id,
                name,
                left.join(", ")
            )));
        }
        super::mark_step();
        return Ok(jobj! {"deleted" => name});
    }
    let like = opt_name(p, CMD, "like")?;
    let exists = types.contains(&name);
    let mut t = if exists {
        DimType::from_json(types.get(&name).unwrap())
    } else if let Some(l) = &like {
        match types.get(l) {
            Some(v) => DimType::from_json(v),
            None => return Err(format!("{}: there's no dimension type `{}` to start from", CMD, l)),
        }
    } else {
        DimType::default()
    };
    if let Some(v) = p.get("color") {
        if !v.is_null() {
            if let Some(c) = opt_color(p, CMD, "color")? {
                t.color = c;
            }
        }
    }
    let font = opt_name(p, CMD, "font")?;
    // the rest as serde reads a struct: its keys in order
    if let Value::Obj(m) = p {
        let mut keys: Vec<&String> = m.items.iter().map(|(k, _)| k).filter(|k| !matches!(k.as_str(), "name" | "like" | "rename" | "delete")).collect();
        keys.sort();
        keys.dedup();
        for k in keys {
            let v = m.items.iter().rev().find(|(kk, _)| kk == k).map(|(_, v)| v).unwrap();
            dim_field(&mut t, k, v).map_err(|e| format!("{}: {}", CMD, e))?;
        }
    }
    if let Some(q) = font {
        match known_font(&q) {
            Some(f) => t.font = f,
            None => {
                return Err(format!(
                    "{}: this system has no font `{}`; `dimension_type` without `name` lists them",
                    CMD, q
                ))
            }
        }
    }
    let mut final_name = name.clone();
    if let Some(r) = opt_name(p, CMD, "rename")? {
        if r != name {
            if types.contains(&r) {
                return Err(format!("{}: there's already a dimension type `{}`", CMD, r));
            }
            final_name = r;
        }
    }
    validate_dim(&t, &final_name).map_err(|e| format!("{}: {}", CMD, e))?;
    let sec = dimension_types_mut(pr);
    if final_name != name {
        sec.remove(&name);
    }
    sec.insert_sorted(&final_name, t.to_json());
    if exists {
        if final_name != name {
            lib_rename(pr, DIM_KIND, &name, &final_name);
        }
        if pr.lib_find(DIM_KIND, &final_name).is_none() {
            pr.lib_add(DIM_KIND, &final_name);
        }
    } else {
        lib_ensure(pr, DIM_KIND, &final_name);
    }
    super::mark_step();
    Ok(jobj! {"name" => final_name, "type" => t.to_json()})
}

fn dimension_listing(pr: &Project) -> Value {
    let types = dimension_types(pr);
    let mut out = Map::new();
    for (n, v) in &types.items {
        out.insert(n, DimType::from_json(v).to_json());
    }
    jobj! {"fonts" => fonts_value(), "types" => Value::Obj(out)}
}

// ================================================================ loading

/// The model's rules for its text and dimension types, as opening a file checks them
/// ("text type `A`: its size, 0 mm, isn't above 0 and at most 100"; the text types first, each
/// in its order, then the dimension types). The commands keep them, so only a file breaks them.
pub fn check(pr: &Project) -> R<()> {
    for (n, v) in &text_types(pr).items {
        validate_text(&TextType::from_json(v), n)?;
    }
    for (n, v) in &dimension_types(pr).items {
        validate_dim(&DimType::from_json(v), n)?;
    }
    Ok(())
}

/// The library entries of the text and dimension types as opening a file leaves them: one for
/// each type (those it lacks made, the text types' first, each kind in name order) and none for a
/// type the file hasn't.
pub fn sync_library(pr: &mut Project) {
    for (kind, names) in [
        (TEXT_KIND, text_types(pr).keys().cloned().collect::<Vec<String>>()),
        (DIM_KIND, dimension_types(pr).keys().cloned().collect::<Vec<String>>()),
    ] {
        let stale: Vec<u64> = pr
            .library
            .iter()
            .filter(|(_, e)| {
                e.get("kind").and_then(|k| k.as_str()) == Some(kind)
                    && !names.iter().any(|n| Some(n.as_str()) == e.get("name").and_then(|x| x.as_str()))
            })
            .map(|(id, _)| *id)
            .collect();
        for id in stale {
            pr.library.remove(&id);
        }
        for n in &names {
            if pr.lib_find(kind, n).is_none() {
                pr.lib_add(kind, n);
            }
        }
    }
}

/// A project file's text and dimension types as the original holds them once read: every value
/// there, its defaults where the file leaves one out, in the order it writes them (for the core's
/// `open` to call; a file without the sections gets the ones a project starts with).
pub fn normalize(pr: &mut Project) {
    let t = text_types(pr);
    let mut m = Map::new();
    for (n, v) in &t.items {
        m.insert_sorted(n, TextType::from_json(v).to_json());
    }
    pr.insert_top("text_types", Value::Obj(m));
    let d = dimension_types(pr);
    let mut m = Map::new();
    for (n, v) in &d.items {
        m.insert_sorted(n, DimType::from_json(v).to_json());
    }
    pr.insert_top("dimension_types", Value::Obj(m));
}
