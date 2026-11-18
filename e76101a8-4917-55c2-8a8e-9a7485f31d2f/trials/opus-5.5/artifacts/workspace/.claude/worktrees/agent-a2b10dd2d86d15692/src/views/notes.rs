//! Text notes: `text`, and what the notes, tags and linework commands share (views and elements
//! by reference, serde's words for a value that isn't what was wanted, the model's usable numbers).

use super::common::*;
use crate::json::{Map, Num, Value};
use crate::project::Project;
use crate::session::Session;

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        // the parameters as the original holds them: every object's keys in order
        "text" => text(&mut s.project, &p.clone().sorted()).map_err(clip_error),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

// ================================================================ shared

/// The longest error a command gives whole; past it, the rest is counted.
const MAX_ERROR: usize = 2000;

/// A command's error past 2000 characters: its first 2000 and how many more there were (what the
/// model's check finds after the command is said whole).
pub fn clip_error(e: String) -> String {
    let n = e.chars().count();
    if n <= MAX_ERROR {
        return e;
    }
    let mut out: String = e.chars().take(MAX_ERROR).collect();
    out.push_str(&format!("\u{2026} ({} more characters)", n - MAX_ERROR));
    out
}

/// The largest coordinate the model holds, mm.
pub const MAX_COORD: f64 = 1e9;

/// A number the model can hold: finite, and no further than `MAX_COORD` from 0.
pub fn usable(x: f64) -> bool {
    x.is_finite() && x.abs() <= MAX_COORD
}

/// "text 100002 x: 10000000000 is not a usable number", the model's words for a number it can't
/// hold; `what` names the number (`x`, `leader y`, `angle`).
pub fn unusable(pr: &Project, id: u64, what: &str, x: f64) -> String {
    format!("{} {} {}: {} is not a usable number", cat_of(pr, id), id, what, disp(x))
}

/// A GUID as a command takes one: 8-4-4-4-12 hexadecimal digits in any case, in braces or not,
/// space round it; lowercase.
pub fn parse_guid(s: &str) -> Option<String> {
    let t = s.trim();
    let t = match t.strip_prefix('{') {
        Some(r) => r.strip_suffix('}')?,
        None => t,
    };
    let b = t.as_bytes();
    if b.len() != 36 {
        return None;
    }
    for (i, c) in b.iter().enumerate() {
        let dash = matches!(i, 8 | 13 | 18 | 23);
        if dash != (*c == b'-') {
            return None;
        }
        if !dash && !c.is_ascii_hexdigit() {
            return None;
        }
    }
    Some(t.to_lowercase())
}

/// Whether a text is an id: digits only, space round them.
fn digits(s: &str) -> Option<u64> {
    let t = s.trim();
    if t.is_empty() || !t.bytes().all(|c| c.is_ascii_digit()) {
        return None;
    }
    t.parse::<u64>().ok()
}

/// A view by id (any element: what it isn't is for the command or the model to say), or by its
/// name (a level's, a plan view's, a section's, an elevation's, a 3D view's or a schedule's; then
/// a sheet's number). A text of digits is an id and a GUID is one, never a name: "`view`: "99" is
/// not a view" for one the project hasn't, "no view named `X`" for a name no view has.
pub fn view_ref(pr: &Project, cmd: &str, key: &str, v: &Value) -> R<u64> {
    view_ref_of(pr, cmd, key, v, true)
}

/// `view_ref`, sheets by number or not.
pub fn view_ref_of(pr: &Project, cmd: &str, key: &str, v: &Value, sheets: bool) -> R<u64> {
    let not = || format!("{}: `{}`: {} is not a view", cmd, key, v.to_compact());
    match v {
        Value::Num(_) => match id_of(v) {
            Some(id) if pr.elements.contains_key(&id) => Ok(id),
            _ => Err(not()),
        },
        Value::Str(s) => {
            if let Some(id) = digits(s) {
                return if pr.elements.contains_key(&id) { Ok(id) } else { Err(not()) };
            }
            if let Some(g) = parse_guid(s) {
                return pr.find_guid(&g).ok_or_else(not);
            }
            for (id, e) in &pr.elements {
                let c = cat(e);
                if c != "sheet" && is_view_category(c) && s_of(e, "name") == Some(s.as_str()) {
                    return Ok(*id);
                }
            }
            for (id, e) in &pr.elements {
                if sheets && cat(e) == "sheet" && s_of(e, "number") == Some(s.as_str()) {
                    return Ok(*id);
                }
            }
            Err(format!("{}: no view named `{}`", cmd, s))
        }
        _ => Err(not()),
    }
}

/// An element by its id (a number, or digits in a text) or its GUID: "no element 99", "\"x\" is
/// not an element id or GUID".
pub fn element_ref(pr: &Project, cmd: &str, v: &Value) -> R<u64> {
    let not = || format!("{}: {} is not an element id or GUID", cmd, v.to_compact());
    match v {
        Value::Num(_) => {
            let id = id_of(v).ok_or_else(not)?;
            if pr.elements.contains_key(&id) {
                Ok(id)
            } else {
                Err(format!("{}: no element {}", cmd, id))
            }
        }
        Value::Str(s) => {
            if let Some(id) = digits(s) {
                return if pr.elements.contains_key(&id) { Ok(id) } else { Err(format!("{}: no element {}", cmd, id)) };
            }
            match parse_guid(s) {
                Some(g) => pr.find_guid(&g).ok_or_else(|| format!("{}: no element {}", cmd, g)),
                None => Err(not()),
            }
        }
        _ => Err(not()),
    }
}

/// What serde calls a value it didn't expect ("integer `-1`", "floating point `0.5`", "string
/// \"x\"", "map"…).
pub fn unexpected(v: &Value) -> String {
    match v {
        Value::Num(Num::F(f)) => format!("floating point `{}`", crate::json::fmt_f64(*f)),
        _ => v.kind_name(),
    }
}

pub fn invalid_type(v: &Value, expected: &str) -> String {
    format!("invalid type: {}, expected {}", unexpected(v), expected)
}

/// A whole number as serde reads a usize.
pub fn de_usize(v: &Value) -> R<u64> {
    match v {
        Value::Num(Num::U(u)) => Ok(*u),
        Value::Num(Num::I(i)) => Err(format!("invalid value: integer `{}`, expected usize", i)),
        _ => Err(invalid_type(v, "usize")),
    }
}

/// A yes or no as serde reads an Option<bool> (null: None).
pub fn de_opt_bool(v: &Value) -> R<Option<bool>> {
    match v {
        Value::Null => Ok(None),
        Value::Bool(b) => Ok(Some(*b)),
        _ => Err(invalid_type(v, "a boolean")),
    }
}

/// An object's entries in key order, a key given twice keeping its last value (as a BTreeMap).
pub fn sorted_items(m: &Map) -> Vec<(&String, &Value)> {
    let mut v: Vec<(&String, &Value)> = m.items.iter().map(|(k, v)| (k, v)).collect();
    v.sort_by(|a, b| a.0.cmp(b.0));
    let mut out: Vec<(&String, &Value)> = Vec::with_capacity(v.len());
    for (k, x) in v {
        if let Some(last) = out.last_mut() {
            if last.0 == k {
                last.1 = x;
                continue;
            }
        }
        out.push((k, x));
    }
    out
}

/// A text parameter as `styles` reads names: trimmed, None when absent, null or blank.
pub fn opt_name(p: &Value, cmd: &str, key: &str) -> R<Option<String>> {
    crate::styles::common::opt_name(p, cmd, key)
}

// ================================================================ text types

/// The project's text types, name to definition.
fn text_types(pr: &Project) -> Map {
    pr.section("text_types").cloned().unwrap_or_default()
}

/// The text types' names in order (as a sorted map holds them).
fn text_type_names(pr: &Project) -> Vec<String> {
    let mut v: Vec<String> = text_types(pr).keys().cloned().collect();
    v.sort();
    v
}

/// The text type a note names (by GUID, or by name), its name.
pub fn note_type_name(pr: &Project, r: &str) -> Option<String> {
    let names = text_type_names(pr);
    if let Some(n) = crate::styles::common::name_of_guid(pr, "text-type", r) {
        if names.contains(&n) {
            return Some(n);
        }
    }
    if names.iter().any(|n| n == r) {
        return Some(r.to_string());
    }
    None
}

/// A text type's size, mm on paper.
pub fn text_type_size(pr: &Project, name: &str) -> f64 {
    text_types(pr).get(name).and_then(|t| f_of(t, "size")).unwrap_or(2.5)
}

/// The type a new note takes: 2.5mm, else the first by name.
fn default_text_type(pr: &Project) -> Option<String> {
    let names = text_type_names(pr);
    if names.iter().any(|n| n == "2.5mm") {
        return Some("2.5mm".into());
    }
    names.first().cloned()
}

// ================================================================ text

pub const TEXT_PARAMS: &[&str] = &["text", "at", "view", "type", "angle", "leader", "override_format", "runs"];

/// The most characters a note holds, and the most formatting runs.
pub const MAX_NOTE: usize = 4000;
pub const MAX_RUNS: usize = 1000;

/// A run of characters a note formats on its own.
#[derive(Clone, Debug, PartialEq)]
pub struct Run {
    pub from: u64,
    pub to: u64,
    pub bold: Option<bool>,
    pub italic: Option<bool>,
    pub underline: Option<bool>,
}

impl Run {
    pub fn to_value(&self) -> Value {
        let mut m = Map::new();
        m.insert("from", Value::u(self.from));
        m.insert("to", Value::u(self.to));
        if let Some(b) = self.bold {
            m.insert("bold", Value::Bool(b));
        }
        if let Some(b) = self.italic {
            m.insert("italic", Value::Bool(b));
        }
        if let Some(b) = self.underline {
            m.insert("underline", Value::Bool(b));
        }
        Value::Obj(m)
    }
}

/// A run as serde reads the struct (its fields in key order; unknown ones refused).
pub fn de_run(v: &Value) -> R<Run> {
    let m = match v {
        Value::Obj(m) => m,
        _ => return Err(invalid_type(v, "struct Run")),
    };
    let (mut from, mut to) = (None, None);
    let mut r = Run { from: 0, to: 0, bold: None, italic: None, underline: None };
    for (k, x) in sorted_items(m) {
        match k.as_str() {
            "from" => from = Some(de_usize(x)?),
            "to" => to = Some(de_usize(x)?),
            "bold" => r.bold = de_opt_bool(x)?,
            "italic" => r.italic = de_opt_bool(x)?,
            "underline" => r.underline = de_opt_bool(x)?,
            _ => {
                return Err(format!(
                    "unknown field `{}`, expected one of `from`, `to`, `bold`, `italic`, `underline`",
                    k
                ))
            }
        }
    }
    r.from = from.ok_or("missing field `from`")?;
    r.to = to.ok_or("missing field `to`")?;
    Ok(r)
}

/// A note's runs as a file holds them (anything unreadable left out).
pub fn runs_of(e: &Value) -> Vec<Run> {
    match e.get("runs").and_then(|r| r.as_arr()) {
        Some(a) => a.iter().filter_map(|x| de_run(x).ok()).collect(),
        None => Vec::new(),
    }
}

fn text(pr: &mut Project, p: &Value) -> R<Value> {
    const CMD: &str = "text";
    if given(p, "size") {
        return Err("text: a note's size is its text type's: give `type` (`text_type` lists them, and makes one of a size)".into());
    }
    crate::styles::common::check_keys(p, CMD, TEXT_PARAMS)?;
    let body = match get(p, "text") {
        None => return Err("text: `text` is required".into()),
        Some(Value::Str(s)) if s.chars().count() <= MAX_NOTE => s.clone(),
        Some(v) => {
            return Err(format!("text: `text` must be text of at most {} characters, got {}", MAX_NOTE, v.to_compact()))
        }
    };
    let at = crate::commands::params::req_point(p, CMD, "at")?;
    let view = match get(p, "view") {
        Some(v) => view_ref(pr, CMD, "view", v)?,
        None => default_plan(pr).ok_or("text: the model has no levels")?,
    };
    let ty = match opt_name(p, CMD, "type")? {
        Some(n) => n,
        None => default_text_type(pr).ok_or("text: the project has no text type; make one first")?,
    };
    let runs = match get(p, "runs") {
        None => Vec::new(),
        Some(Value::Arr(a)) => a
            .iter()
            .map(de_run)
            .collect::<R<Vec<Run>>>()
            .map_err(|e| format!("text: `runs`: {}", e))?,
        Some(v) => return Err(format!("text: `runs`: {}", invalid_type(v, "a sequence"))),
    };
    let angle = crate::commands::params::opt_num(p, CMD, "angle")?.unwrap_or(0.0);
    let leader = crate::commands::params::opt_point(p, CMD, "leader")?;
    let override_format = crate::commands::params::opt_bool(p, CMD, "override_format")?.unwrap_or(false);
    // the type by GUID where the project has it; a name it hasn't stays for the model to refuse
    let type_ref = pr.lib_guid("text-type", &ty).filter(|_| text_types(pr).contains(&ty)).unwrap_or(ty);
    let id = pr.alloc_id();
    let mut m = Map::new();
    m.insert("guid", Value::s(&crate::rand::guid()));
    m.insert("category", Value::s("text"));
    m.insert("view", Value::s(&guid(pr, view)));
    m.insert("at", pt_value(at));
    m.insert("text", Value::s(&body));
    m.insert("type", Value::s(&type_ref));
    m.insert("angle", Value::f(angle));
    if let Some(l) = leader {
        m.insert("leader", pt_value(l));
    }
    if override_format {
        m.insert("override_format", Value::Bool(true));
    }
    if !runs.is_empty() {
        m.insert("runs", Value::Arr(runs.iter().map(|r| r.to_value()).collect()));
    }
    pr.elements.insert(id, Value::Obj(m));
    Ok(jobj! {"id" => id})
}

// ================================================================ the model's rules

/// Whether a note may be drawn in a view of this category: a plan (a level's own, or a plan
/// view), a section, an elevation or a sheet.
pub fn note_view_ok(c: &str) -> bool {
    matches!(c, "level" | "planview" | "section" | "elevation" | "sheet")
}

/// The model rules for one text note (of a view, a group's member…), its messages prefixed
/// `text N`.
pub fn check_note(pr: &Project, id: u64, e: &Value) -> R<()> {
    let name = format!("{} {}", cat(e), id);
    if let Some(v) = ref_id(pr, e, "view") {
        let c = cat_of(pr, v);
        if !note_view_ok(&c) {
            return Err(format!("{}: {} {} isn't a plan, a section, an elevation or a sheet", name, c, v));
        }
    }
    let num = |what: &str, x: f64| -> R<()> {
        if usable(x) {
            Ok(())
        } else {
            Err(format!("{} {}: {} is not a usable number", name, what, disp(x)))
        }
    };
    if let Some(a) = pt_of(e, "at") {
        num("x", a[0])?;
        num("y", a[1])?;
    }
    if let Some(a) = f_of(e, "angle") {
        num("angle", a)?;
    }
    if let Some(l) = pt_of(e, "leader") {
        num("leader x", l[0])?;
        num("leader y", l[1])?;
    }
    let body = s_of(e, "text").unwrap_or("");
    let n = body.chars().count();
    if n > MAX_NOTE {
        return Err(format!("{}: its text is {} characters long; a note holds up to {}", name, n, MAX_NOTE));
    }
    if body.trim().is_empty() {
        return Err(format!("{}: a text note needs text", name));
    }
    if let Some(t) = s_of(e, "type") {
        if note_type_name(pr, t).is_none() {
            return Err(format!(
                "{}: there's no text type `{}` (there are: {})",
                name,
                t,
                text_type_names(pr).join(", ")
            ));
        }
    }
    let runs = runs_of(e);
    if runs.len() > MAX_RUNS {
        return Err(format!("{}: it has {} formatting runs; a note holds up to {}", name, runs.len(), MAX_RUNS));
    }
    let mut prev_to: Option<u64> = None;
    for (i, r) in runs.iter().enumerate() {
        if !(r.from < r.to && r.to as usize <= n) {
            return Err(format!(
                "{}: run {} is of characters {} to {}; it needs some of the text's {}",
                name, i, r.from, r.to, n
            ));
        }
        if let Some(t) = prev_to {
            if r.from < t {
                return Err(format!(
                    "{}: run {} starts at {}, inside the run before it; give them in order, apart",
                    name, i, r.from
                ));
            }
        }
        if r.bold.is_none() && r.italic.is_none() && r.underline.is_none() {
            return Err(format!("{}: run {} overrides nothing; give it `bold`, `italic` or `underline`", name, i));
        }
        prev_to = Some(r.to);
    }
    Ok(())
}

/// The model rules of this part, checked after every command.
pub fn check(pr: &Project) -> R<()> {
    for (id, e) in &pr.elements {
        if cat(e) == "text" {
            check_note(pr, *id, e)?;
        }
    }
    Ok(())
}

/// What `elements` shows of a note beyond its own fields: its view's level (null in a section, an
/// elevation or on a sheet), its type's size and its type by name.
pub fn element_view(pr: &Project, id: u64, x: &mut Value) {
    let Some(e) = pr.el(id) else { return };
    let level = ref_id(pr, e, "view").and_then(|v| plan_level(pr, v)).map(|l| guid(pr, l));
    x.set("level", level.map(Value::from).unwrap_or(Value::Null));
    if let Some(t) = s_of(e, "type").and_then(|t| note_type_name(pr, t)) {
        x.set("size", Value::f(text_type_size(pr, &t)));
        x.set("type", Value::s(&t));
    }
}

/// A file's notes as the original reads them: a `size` left on one gives it a type of that size
/// (an existing one of it, else one made, `<size>mm`), a type named rather than referred to by
/// GUID is referred to, and a note of no type takes the default. For the loader to call.
pub fn normalize(pr: &mut Project) {
    let ids: Vec<u64> = pr.ids_of("text");
    for id in ids {
        let Some(e) = pr.el(id).cloned() else { continue };
        let mut e = e;
        let size = e.get("size").and_then(|s| s.as_f64());
        let had_size = e.get("size").is_some();
        let mut t = s_of(&e, "type").map(|s| s.to_string());
        if t.is_none() {
            if let Some(sz) = size {
                t = type_of_size(pr, sz);
            }
        }
        let t = t.or_else(|| default_text_type(pr));
        if let Some(t) = t {
            if let Some(n) = note_type_name(pr, &t) {
                if let Some(g) = pr.lib_guid("text-type", &n) {
                    e.set("type", Value::s(&g));
                }
            }
        }
        if had_size {
            e.remove("size");
        }
        // the fields in the file's order
        let mut m = Map::new();
        for k in ["guid", "category", "view", "at", "text", "type", "angle", "leader", "override_format", "runs"] {
            match (k, e.get(k)) {
                ("angle", None) => m.insert("angle", Value::f(0.0)),
                ("leader", Some(Value::Null)) | ("override_format", Some(Value::Bool(false))) => {}
                ("runs", Some(Value::Arr(a))) if a.is_empty() => {}
                (_, Some(v)) => m.insert(k, v.clone()),
                _ => {}
            }
        }
        pr.elements.insert(id, Value::Obj(m));
    }
}

/// The text type of a size, made `<size>mm` like 2.5mm where the project has none of it.
fn type_of_size(pr: &mut Project, size: f64) -> Option<String> {
    let types = text_types(pr);
    let mut names: Vec<&String> = types.keys().collect();
    names.sort();
    for n in names {
        if types.get(n).and_then(|t| f_of(t, "size")) == Some(size) {
            return Some(n.clone());
        }
    }
    let name = format!("{}mm", disp(size));
    let def = types.get("2.5mm").cloned().unwrap_or_else(|| {
        jobj! {"font" => "Arial", "size" => 2.5, "color" => Value::Arr(vec![Value::u(0), Value::u(0), Value::u(0)]), "border_offset" => 1.0, "border_pen" => 1u64}
    });
    let mut def = def;
    def.set("size", Value::f(size));
    pr.section_mut("text_types").insert_sorted(&name, def);
    if pr.lib_find("text-type", &name).is_none() {
        pr.lib_add("text-type", &name);
    }
    Some(name)
}
