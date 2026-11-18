//! Paper: the sheet sizes, the margins and title block a standard lays a sheet out with, where a
//! view goes on one by default, and how big each view is on paper (its viewport's size): a plan,
//! a section or an elevation drawn at its scale with its margins, the 3D view's picture, a
//! schedule's table lettered in our single-stroke capitals.

use super::super::common::*;
use super::super::plans::shows;
use crate::json::Value;
use crate::project::Project;

/// A sheet's drawing density: pixels to the paper millimetre.
pub const DENSITY: f64 = 5.0;

/// The sheet sizes, landscape: (name, width, height) in mm.
const SIZES: &[(&str, f64, f64)] = &[
    ("A0", 1189.0, 841.0),
    ("A1", 841.0, 594.0),
    ("A2", 594.0, 420.0),
    ("A3", 420.0, 297.0),
    ("A4", 297.0, 210.0),
    ("ARCH A", 304.8, 228.6),
    ("ARCH B", 457.2, 304.8),
    ("ARCH C", 609.6, 457.2),
    ("ARCH D", 914.4, 609.6),
    ("ARCH E", 1219.2, 914.4),
    ("ARCH E1", 1066.8, 762.0),
    ("ANSI A", 279.4, 215.9),
    ("ANSI B", 431.8, 279.4),
    ("ANSI C", 558.8, 431.8),
    ("ANSI D", 863.6, 558.8),
    ("ANSI E", 1117.6, 863.6),
    ("LETTER", 279.4, 215.9),
    ("TABLOID", 431.8, 279.4),
    ("LEDGER", 431.8, 279.4),
];

/// A size as a sheet keeps it: trimmed, in capitals.
pub fn normalize_size(s: &str) -> String {
    s.trim().to_uppercase()
}

/// The canonical name of a size as kept ("ARCHA" is ARCH A, "a3" A3), if it is one.
fn canonical(size: &str) -> Option<&'static str> {
    let size = &size.trim().to_uppercase();
    let size = size.as_str();
    if let Some(x) = SIZES.iter().find(|(n, _, _)| *n == size) {
        return Some(x.0);
    }
    for pre in ["ARCH", "ANSI"] {
        if let Some(rest) = size.strip_prefix(pre) {
            if rest.starts_with(' ') {
                continue;
            }
            let full = format!("{} {}", pre, rest);
            if let Some(x) = SIZES.iter().find(|(n, _, _)| *n == full) {
                return Some(x.0);
            }
        }
    }
    None
}

/// The paper a size names: width and height in mm, landscape.
pub fn paper_size(size: &str) -> Option<(f64, f64)> {
    let c = canonical(size)?;
    SIZES.iter().find(|(n, _, _)| *n == c).map(|x| (x.1, x.2))
}

/// The project's technical standard (iso unless it says).
pub fn standard(pr: &Project) -> String {
    pr.get("standard").and_then(|v| v.as_str()).unwrap_or("iso").to_string()
}

/// A standard's margins for a size: (left, the others) in mm.
fn margins(std: &str, size: &str) -> (f64, f64) {
    let c = canonical(size).unwrap_or("A3");
    match std {
        "nbr" => (25.0, if c == "A0" || c == "A1" { 10.0 } else { 7.0 }),
        "ansi" => (19.05, 12.7),
        "jis" => (20.0, if c == "A4" { 5.0 } else { 10.0 }),
        _ => (20.0, if c == "A4" { 7.0 } else { 10.0 }),
    }
}

/// The title block's height along the bottom of the frame.
const TITLE_BLOCK: f64 = 40.0;
/// How far inside the frame (and over the title block) views are laid out.
const INSET: f64 = 5.0;
/// The gap between a view and the next one placed right of it.
const GAP: f64 = 10.0;

/// Where views go on a sheet: (W, H, left, right, bottom, top) — the paper and its margins,
/// the bottom one over the title block.
fn layout(pr: &Project, sheet: &Value) -> (f64, f64, f64, f64, f64, f64) {
    let size = s_of(sheet, "size").unwrap_or("A3");
    let (w, h) = paper_size(size).unwrap_or((420.0, 297.0));
    let (l, o) = margins(&standard(pr), size);
    (w, h, l, o, o + TITLE_BLOCK, o)
}

/// The middle of the sheet's drawing area, where the first view goes.
pub fn middle(pr: &Project, sheet: &Value) -> [f64; 2] {
    let (w, h, l, r, b, t) = layout(pr, sheet);
    [(w + l - r) / 2.0, (h + b - t) / 2.0]
}

/// Where a view `size` wide and tall goes on a sheet by default: right of the views there, at
/// the middle's height, where it fits; else in the top right corner; on an empty sheet, in the
/// middle.
pub fn default_place(pr: &Project, sheet_id: u64, size: [f64; 2]) -> [f64; 2] {
    let sheet = pr.el(sheet_id).unwrap();
    let mid = middle(pr, sheet);
    let g = guid(pr, sheet_id);
    let mut right: Option<f64> = None;
    for (id, e) in &pr.elements {
        if cat(e) == "viewport" && s_of(e, "sheet") == Some(g.as_str()) {
            let at = pt_of(e, "at").unwrap_or([0.0, 0.0]);
            let sz = viewport_size(pr, *id);
            let r = at[0] + sz[0] / 2.0;
            right = Some(right.map_or(r, |x: f64| x.max(r)));
        }
    }
    let Some(right) = right else { return mid };
    let (w, h, _, r, _, t) = layout(pr, sheet);
    let x1 = w - (r + INSET);
    let y1 = h - (t + INSET);
    let x = right + GAP + size[0] / 2.0;
    if x + size[0] / 2.0 <= x1 + 1e-9 {
        [x, mid[1]]
    } else {
        [x1 - size[0] / 2.0, y1 - size[1] / 2.0]
    }
}

// ---------------------------------------------------------------- lettering

/// How wide a line of `n` letters of our single-stroke capitals is, `size` mm tall, in mm: the
/// font is 12 units to its height, each letter 8 wide and the next 11 on.
pub fn text_mm(n: usize, size: f64) -> f64 {
    if n == 0 {
        return 0.0;
    }
    size / 12.0 * (11 * (n - 1) + 8) as f64
}

/// The same in pixels of a sheet.
pub fn text_px(n: usize, size: f64) -> f64 {
    text_mm(n, size) * DENSITY
}

fn chars(s: &str) -> usize {
    s.chars().count()
}

/// Whole pixels up from a measure.
fn ceil_px(x: f64) -> f64 {
    x.ceil()
}

// ---------------------------------------------------------------- sizes of views on paper

/// How big a viewport's view is on its sheet, mm.
pub fn viewport_size(pr: &Project, vp: u64) -> [f64; 2] {
    let Some(e) = pr.el(vp) else { return [0.0, 0.0] };
    let scale = f_of(e, "scale").unwrap_or(100.0);
    match ref_id(pr, e, "view") {
        Some(v) => view_size(pr, v, scale),
        None => [0.0, 0.0],
    }
}

/// How big a view is on paper at 1 : `scale`, mm: what it shows at the scale with 12 mm round
/// it (a section's and an elevation's levels' heads on their right), the 3D view's picture, a
/// schedule's table.
pub fn view_size(pr: &Project, view: u64, scale: f64) -> [f64; 2] {
    let Some(e) = pr.el(view) else { return [0.0, 0.0] };
    let k = DENSITY / scale;
    const MARGIN: f64 = 2.0 * 12.0 * DENSITY;
    match cat(e) {
        "level" | "planview" => {
            let (lo, hi) = shows::plan_crop(e)
                .or_else(|| shows::plan_shows(pr, view))
                .unwrap_or(([0.0, 0.0], [10000.0, 10000.0]));
            [ceil_px((hi[0] - lo[0]) * k + MARGIN) / DENSITY, ceil_px((hi[1] - lo[1]) * k + MARGIN) / DENSITY]
        }
        "section" | "elevation" => {
            let (u0, u1, v0, v1) = shows::section_frame(pr, view);
            let heads = level_heads_px(pr);
            [ceil_px((u1 - u0) * k + MARGIN + heads) / DENSITY, ceil_px((v1 - v0) * k + MARGIN) / DENSITY]
        }
        "view3d" => {
            let az = f_of(e, "azimuth").unwrap_or(-45.0);
            let el = f_of(e, "elevation").unwrap_or(30.0);
            match shows::view3d_extent(pr, Some(view), az, el) {
                None => [1.0 / DENSITY, 1.0 / DENSITY],
                Some((w, h)) => {
                    let cap = |x: f64| ceil_px(x * k + MARGIN).min(4096.0).max(1.0) / DENSITY;
                    [cap(w), cap(h)]
                }
            }
        }
        "schedule" => schedule_size(pr, view),
        _ => [0.0, 0.0],
    }
}

/// The room a section's level heads take right of its levels' lines: a gap, the widest name or
/// height lettered 2 mm tall, and a little more.
fn level_heads_px(pr: &Project) -> f64 {
    let mut n = 0usize;
    for id in crate::model::levels(pr) {
        let e = pr.el(id).unwrap();
        n = n.max(chars(s_of(e, "name").unwrap_or("")));
        n = n.max(chars(&length_text(pr, f_of(e, "elevation").unwrap_or(0.0))));
    }
    12.0 + text_px(n, 2.0)
}

/// A length as the project's units letter it on paper: whole millimetres; centimetres to the
/// millimetre (no `.0`); metres and decimal feet to two places; inches and feet and inches to
/// the sixteenth.
pub fn length_text(pr: &Project, mm: f64) -> String {
    let units = pr.get("units").and_then(|v| v.as_str()).unwrap_or("mm").to_string();
    match units.as_str() {
        "cm" => {
            let t = format!("{:.1}", mm / 10.0);
            let t = t.strip_suffix(".0").map(|x| x.to_string()).unwrap_or(t);
            if t == "-0" { "0".to_string() } else { t }
        }
        "m" => {
            let t = format!("{:.2}", mm / 1000.0);
            if t == "-0.00" { "0.00".to_string() } else { t }
        }
        "ft" => {
            let t = format!("{:.2}", mm / 304.8);
            let t = if t == "-0.00" { "0.00".to_string() } else { t };
            format!("{}'", t)
        }
        "in" | "ft-in" => {
            let neg = mm < 0.0;
            let s = (mm.abs() / 25.4 * 16.0).round() as u64;
            let sign = if neg && s > 0 { "-" } else { "" };
            let frac = |x: u64| -> String {
                if x == 0 {
                    return String::new();
                }
                let (mut a, mut b) = (x, 16u64);
                while a % 2 == 0 {
                    a /= 2;
                    b /= 2;
                }
                format!("{}/{}", a, b)
            };
            if units == "in" {
                let (w, f) = (s / 16, s % 16);
                let body = match (w, f) {
                    (0, 0) => "0".to_string(),
                    (0, f) => frac(f),
                    (w, 0) => w.to_string(),
                    (w, f) => format!("{} {}", w, frac(f)),
                };
                format!("{}{}\"", sign, body)
            } else {
                let feet = s / 192;
                let rem = s % 192;
                let (w, f) = (rem / 16, rem % 16);
                let inches = if f == 0 { w.to_string() } else { format!("{} {}", w, frac(f)) };
                format!("{}{}'-{}\"", sign, feet, inches)
            }
        }
        _ => {
            let r = mm.round();
            if r == 0.0 {
                "0".to_string()
            } else {
                format!("{}", r as i64)
            }
        }
    }
}

// ---------------------------------------------------------------- schedules

/// The schedules a sheet takes by name: what each is of, and its name in each language.
pub const SCHEDULES: &[(&str, [&str; 9])] = &[
    (
        "room",
        [
            "Room Schedule",
            "Tabela de ambientes",
            "Tabla de habitaciones",
            "Rumsförteckning",
            "Výkaz místností",
            "Nomenclature des pièces",
            "Ruimtelijst",
            "Raumtabelle",
            "Abaco zone",
        ],
    ),
    (
        "door",
        [
            "Door Schedule",
            "Tabela de portas",
            "Tabla de puertas",
            "Dörrförteckning",
            "Výkaz dveří",
            "Nomenclature des portes",
            "Deurenlijst",
            "Türtabelle",
            "Abaco porte",
        ],
    ),
    (
        "window",
        [
            "Window Schedule",
            "Tabela de janelas",
            "Tabla de ventanas",
            "Fönsterförteckning",
            "Výkaz oken",
            "Nomenclature des fenêtres",
            "Ramenlijst",
            "Fenstertabelle",
            "Abaco finestre",
        ],
    ),
    (
        "wall",
        [
            "Wall Schedule",
            "Tabela de paredes",
            "Tabla de muros",
            "Väggförteckning",
            "Výkaz stěn",
            "Nomenclature des murs",
            "Murenlijst",
            "Wandtabelle",
            "Abaco muri",
        ],
    ),
    (
        "floor",
        [
            "Floor Schedule",
            "Tabela de pisos",
            "Tabla de pisos",
            "Bjälklagsförteckning",
            "Výkaz podlah",
            "Nomenclature des sols",
            "Vloerenlijst",
            "Bodentabelle",
            "Abaco solai",
        ],
    ),
    (
        "level",
        [
            "Level Schedule",
            "Tabela de níveis",
            "Tabla de niveles",
            "Nivåförteckning",
            "Výkaz podlaží",
            "Nomenclature des niveaux",
            "Niveaulijst",
            "Geschosstabelle",
            "Abaco piani",
        ],
    ),
];

/// What a schedule's name in any language is of (in any case, trimmed).
pub fn schedule_of(name: &str) -> Option<&'static str> {
    let t = name.trim().to_lowercase();
    SCHEDULES
        .iter()
        .find(|(_, names)| names.iter().any(|n| n.to_lowercase() == t))
        .map(|(of, _)| *of)
}

/// A category's schedule name in the project's language.
pub fn schedule_name(pr: &Project, of: &str) -> String {
    SCHEDULES
        .iter()
        .find(|(o, _)| *o == of)
        .map(|(_, names)| word(pr, *names).to_string())
        .unwrap_or_default()
}

/// A category's own columns: (field, heading).
fn default_fields(of: &str) -> Vec<&'static str> {
    match of {
        "room" => vec!["Number", "Name", "Level", "Area", "Perimeter"],
        "door" => vec!["Mark", "Type", "Width", "Height", "Level", "Wall"],
        "window" => vec!["Mark", "Type", "Width", "Height", "Sill", "Level", "Wall"],
        "wall" => vec!["Id", "Type", "Level", "Length", "Height", "Thickness"],
        "floor" => vec!["Id", "Type", "Level", "Area", "Thickness"],
        "level" => vec!["Elevation", "Name"],
        _ => vec![],
    }
}

/// How many letters a field's heading has on a sheet in each language (en, pt, es, sv, cs, fr,
/// nl, de, it), an area's with its unit: the headings are lettered in the project's language.
const HEADINGS: &[(&str, [usize; 9])] = &[
    ("Number", [6, 6, 6, 6, 5, 6, 6, 6, 6]),
    ("Name", [4, 4, 6, 4, 5, 3, 4, 4, 4]),
    ("Level", [5, 5, 5, 4, 7, 6, 6, 8, 5]),
    ("Area", [9, 9, 9, 9, 11, 12, 16, 11, 15]),
    ("Perimeter", [9, 9, 9, 7, 5, 9, 6, 6, 9]),
    ("Count", [5, 8, 8, 5, 5, 6, 6, 6, 6]),
    ("Unbounded Height", [16, 21, 20, 15, 18, 21, 18, 16, 16]),
    ("Volume", [6, 6, 7, 5, 5, 6, 6, 7, 6]),
    ("Mark", [4, 5, 5, 10, 8, 6, 9, 5, 2]),
    ("Type", [4, 4, 4, 3, 3, 4, 4, 3, 4]),
    ("Width", [5, 7, 5, 5, 5, 7, 7, 6, 9]),
    ("Height", [6, 6, 6, 4, 5, 7, 6, 4, 7]),
    ("Wall", [4, 6, 4, 4, 5, 3, 4, 4, 4]),
    ("Family", [6, 7, 7, 6, 6, 7, 7, 7, 7]),
    ("Operation", [9, 8, 9, 16, 16, 9, 9, 9, 8]),
    ("Sill", [4, 8, 9, 14, 7, 6, 11, 8, 9]),
    ("Id", [2, 2, 2, 2, 2, 2, 2, 2, 2]),
    ("Length", [6, 11, 8, 5, 5, 8, 6, 5, 9]),
    ("Thickness", [9, 9, 7, 8, 8, 9, 5, 5, 8]),
    ("Offset", [6, 12, 7, 12, 8, 8, 12, 7, 11]),
    ("Elevation", [9, 8, 9, 5, 6, 9, 5, 7, 9]),
];

/// How many letters a column's heading has: its own (an area's with its unit), else its field's
/// name in the project's language.
fn heading_letters(pr: &Project, field: &str, heading: Option<&str>) -> usize {
    if let Some(h) = heading {
        return chars(h) + if field == "Area" { 5 } else { 0 };
    }
    let i = crate::project::LANGS.iter().position(|l| *l == pr.language()).unwrap_or(0);
    match HEADINGS.iter().find(|(f, _)| *f == field) {
        Some((_, n)) => n[i],
        None => chars(field),
    }
}

/// The elements a schedule lists, by id.
fn schedule_rows(pr: &Project, of: &str) -> Vec<u64> {
    if of == "level" {
        return crate::model::levels(pr);
    }
    pr.ids_of(of)
}


/// The level an element stands on (a door's or a window's, its wall's).
fn level_name_of(pr: &Project, e: &Value) -> String {
    ref_id(pr, e, "level")
        .or_else(|| ref_id(pr, e, "host").and_then(|h| pr.el(h)).and_then(|h| ref_id(pr, h, "level")))
        .map(|l| name_of(pr, l))
        .unwrap_or_default()
}

/// A door's or a window's type entry, for its width, height and sill.
fn opening_type<'a>(pr: &'a Project, e: &Value) -> Option<&'a Value> {
    super::super::model::type_entry(pr, cat(e), e)
}

/// A door's or a window's size: its family's parameter, else its type's field.
fn opening_size(pr: &Project, e: &Value, param: &str, field: &str) -> Option<f64> {
    if e.get("family").is_some() {
        if let Some(v) = shows::family_param(pr, e, param) {
            return Some(v);
        }
    }
    opening_type(pr, e).and_then(|t| f_of(t, field))
}

/// A polygon's area, m².
fn area_m2(pts: &[[f64; 2]]) -> f64 {
    let mut a = 0.0;
    for i in 0..pts.len() {
        let p = pts[i];
        let q = pts[(i + 1) % pts.len()];
        a += p[0] * q[1] - q[0] * p[1];
    }
    (a / 2.0).abs() / 1e6
}

/// A cell's text, where it can be told: the element's own field as a schedule shows it.
fn cell_text(pr: &Project, id: u64, field: &str) -> String {
    use super::super::model as m;
    let Some(e) = pr.el(id) else { return String::new() };
    match field {
        "Name" => s_of(e, "name").unwrap_or("").to_string(),
        "Number" => s_of(e, "number").unwrap_or("").to_string(),
        "Mark" => s_of(e, "mark").unwrap_or("").to_string(),
        "Elevation" => length_text(pr, f_of(e, "elevation").unwrap_or(0.0)),
        "Id" => id.to_string(),
        "Level" => level_name_of(pr, e),
        "Type" => {
            let t = lib_ref_name(pr, e, "type").unwrap_or_default();
            // a family's type goes by "Family: Type" in the library and by its own name here
            match lib_ref_name(pr, e, "family") {
                Some(f) => t.strip_prefix(&format!("{}: ", f)).map(|x| x.to_string()).unwrap_or(t),
                None => t,
            }
        }
        "Family" => lib_ref_name(pr, e, "family").unwrap_or_default(),
        "Operation" => {
            let op = lib_ref_name(pr, e, "family")
                .and_then(|f| pr.section("families").and_then(|fs| fs.get(&f)).and_then(|f| s_of(f, "operation")).map(|o| o.to_string()))
                .unwrap_or_default();
            op.split('-')
                .filter(|w| !w.is_empty())
                .map(|w| {
                    let mut c = w.chars();
                    match c.next() {
                        Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
                        None => String::new(),
                    }
                })
                .collect::<Vec<_>>()
                .join(" ")
        }
        "Wall" => ref_id(pr, e, "host").map(|h| h.to_string()).unwrap_or_default(),
        "Count" => "1".to_string(),
        "Thickness" => match cat(e) {
            "wall" => length_text(pr, m::wall_thickness(pr, e)),
            c => length_text(pr, m::type_entry(pr, c, e).and_then(|t| f_of(t, "thickness")).unwrap_or(0.0)),
        },
        "Length" => length_text(pr, m::location_line(e).length()),
        "Height" => match cat(e) {
            "wall" => {
                let (b, t) = m::base_top(pr, e);
                length_text(pr, t - b)
            }
            _ => length_text(pr, f_of(e, "height").or_else(|| opening_size(pr, e, "Height", "height")).unwrap_or(0.0)),
        },
        "Width" => length_text(pr, f_of(e, "width").or_else(|| opening_size(pr, e, "Width", "width")).unwrap_or(0.0)),
        "Sill" => length_text(pr, f_of(e, "sill").or_else(|| opening_type(pr, e).and_then(|t| f_of(t, "sill"))).unwrap_or(0.0)),
        "Offset" => length_text(pr, f_of(e, "offset").unwrap_or(0.0)),
        "Area" => match pts_of(e, "boundary") {
            Some(b) => format!("{:.2}", area_m2(&b)),
            None => String::new(),
        },
        _ => String::new(),
    }
}

/// How big a schedule's table is on paper, mm: its title, 3.5 mm capitals, over its headings and
/// rows, 2.5 mm capitals, each column as wide as its widest text and 2 mm either side.
pub fn schedule_size(pr: &Project, id: u64) -> [f64; 2] {
    let Some(e) = pr.el(id) else { return [0.0, 0.0] };
    let of = s_of(e, "of").unwrap_or("room").to_string();
    let title = s_of(e, "name").unwrap_or("");
    let fields: Vec<(String, Option<String>)> = match e.get("fields").and_then(|f| f.as_arr()) {
        Some(a) if !a.is_empty() => a
            .iter()
            .map(|f| match f {
                Value::Str(s) => (s.clone(), None),
                _ => (
                    s_of(f, "name").unwrap_or("").to_string(),
                    s_of(f, "heading").map(|h| h.to_string()),
                ),
            })
            .collect(),
        _ => default_fields(&of).into_iter().map(|f| (f.to_string(), None)).collect(),
    };
    let rows = schedule_rows(pr, &of);
    let mut table = 0.0;
    for (f, h) in &fields {
        let mut n = heading_letters(pr, f, h.as_deref());
        for r in &rows {
            n = n.max(chars(&cell_text(pr, *r, f)));
        }
        table += DENSITY * (text_mm(n, 2.5) + 4.0);
    }
    let title_w = DENSITY * (text_mm(chars(title), 3.5) + 4.0);
    let w = ceil_px(if title_w > table { title_w } else { table });
    let h = 45.0 + 30.0 + 30.0 * rows.len() as f64;
    [w / DENSITY, h / DENSITY]
}
