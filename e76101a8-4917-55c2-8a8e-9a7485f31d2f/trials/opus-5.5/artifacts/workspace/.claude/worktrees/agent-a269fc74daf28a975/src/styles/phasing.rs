//! Phases, phase filters and design options: `phase`, `phase_filter`, `option`.
//!
//! The file keeps `phases` (names, in order), `phase_filters` (name: how each status shows),
//! `phase_overrides` (status: override, fill patterns by GUID) and `option_sets` (name: its
//! options and its primary's GUID), each written only where it differs from what an English
//! project starts with. The library names every phase (`phase`), filter (`phase-filter`), set
//! (`option-set`) and option (`design-option`, `Set: Option`); what refers to one holds its GUID:
//! an element's `Phase Created`, `Phase Demolished` and `Design Option` (in `params`), a view's or
//! a template's `graphics` (`phase`, `phase_filter`, `options` {set: option}), and the rules of
//! view filters and schedules that name one. What this session makes things in (`now`) is the
//! session's, kept by name.

use super::common::*;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;
use std::collections::BTreeSet;

pub const DEFAULT_PHASES: [&str; 2] = ["Existing", "New Construction"];
pub const STATUSES: [&str; 4] = ["new", "existing", "demolished", "temporary"];
const SHOWS: [&str; 3] = ["by-category", "overridden", "not-displayed"];
const CREATED: &str = "Phase Created";
const DEMOLISHED: &str = "Phase Demolished";
const OPTION: &str = "Design Option";

const NAME_RULE: &str = "a name is 1 to 256 characters, with nothing before or after it but letters, digits and the like";

/// The categories whose elements hold a phase of their own (doors and windows follow their wall).
const PHASED: &[&str] = &[
    "wall",
    "floor",
    "ceiling",
    "room",
    "column",
    "structuralcolumn",
    "footing",
    "beam",
    "stripfooting",
    "pipe",
    "duct",
    "conduit",
    "cabletray",
    "wire",
    "downconductor",
    "groundconductor",
    "cable",
    "stair",
    "ramp",
    "railing",
    "roof",
    "mass",
    "component",
];

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "phase" => cmd_phase(s, p),
        "phase_filter" => cmd_phase_filter(s, p),
        "option" => cmd_option(s, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

// ---------------------------------------------------------------- defaults

fn default_filters() -> Map {
    let f = |n: &str, e: &str, d: &str, t: &str| jobj! {"new" => n, "existing" => e, "demolished" => d, "temporary" => t};
    let mut m = Map::new();
    m.insert("Show All", f("by-category", "by-category", "by-category", "by-category"));
    m.insert("Show Complete", f("by-category", "by-category", "not-displayed", "by-category"));
    m.insert("Show New", f("by-category", "not-displayed", "not-displayed", "not-displayed"));
    m.insert("Show Previous + Demolished", f("not-displayed", "by-category", "overridden", "not-displayed"));
    m.insert("Show Previous + New", f("by-category", "overridden", "not-displayed", "by-category"));
    m
}

fn default_overrides() -> Map {
    let red = || jobj! {"color" => Value::Arr(vec![Value::u(200), Value::u(40), Value::u(30)]), "dash" => "dashed"};
    let mut m = Map::new();
    m.insert("existing", jobj! {"halftone" => true});
    m.insert("demolished", jobj! {"projection" => red(), "cut" => red()});
    m
}

// ---------------------------------------------------------------- the sections

pub fn phases(pr: &Project) -> Vec<String> {
    match pr.get("phases").and_then(|v| v.as_arr()) {
        Some(a) => a.iter().map(|x| x.as_str().map(|s| s.to_string()).unwrap_or_else(|| x.to_compact())).collect(),
        None => DEFAULT_PHASES.iter().map(|s| s.to_string()).collect(),
    }
}

fn set_phases(pr: &mut Project, ph: &[String]) {
    if ph.len() == 2 && ph[0] == DEFAULT_PHASES[0] && ph[1] == DEFAULT_PHASES[1] {
        pr.remove_top("phases");
    } else {
        pr.insert_top("phases", Value::Arr(ph.iter().map(|x| Value::s(x)).collect()));
    }
}

/// The phase filters, each with its four statuses (by category where the file says none).
pub fn filters(pr: &Project) -> Map {
    match pr.get("phase_filters").and_then(|v| v.as_obj()) {
        Some(m) => {
            let mut out = Map::new();
            for (k, v) in &m.items {
                let mut f = Map::new();
                for st in STATUSES {
                    f.insert(st, v.get(st).cloned().unwrap_or_else(|| Value::s("by-category")));
                }
                out.insert(k, Value::Obj(f));
            }
            out
        }
        None => default_filters(),
    }
}

fn set_filters(pr: &mut Project, mut f: Map) {
    f.sort();
    if f == default_filters() {
        pr.remove_top("phase_filters");
    } else {
        pr.insert_top("phase_filters", Value::Obj(f));
    }
}

/// The overrides as the file holds them (fill patterns by GUID).
fn overrides(pr: &Project) -> Map {
    match pr.get("phase_overrides").and_then(|v| v.as_obj()) {
        Some(m) => m.clone(),
        None => default_overrides(),
    }
}

fn set_overrides(pr: &mut Project, o: Map) {
    // statuses in their order
    let mut m = Map::new();
    for st in STATUSES {
        if let Some(v) = o.get(st) {
            m.insert(st, v.clone());
        }
    }
    if m == default_overrides() {
        pr.remove_top("phase_overrides");
    } else {
        pr.insert_top("phase_overrides", Value::Obj(m));
    }
}

pub fn option_sets(pr: &Project) -> Map {
    pr.get("option_sets").and_then(|v| v.as_obj()).cloned().unwrap_or_default()
}

fn set_option_sets(pr: &mut Project, mut m: Map) {
    m.sort();
    if m.is_empty() {
        pr.remove_top("option_sets");
    } else {
        pr.insert_top("option_sets", Value::Obj(m));
    }
}

fn set_options_of(set: &Value) -> Vec<String> {
    set.get("options")
        .and_then(|v| v.as_arr())
        .map(|a| a.iter().map(|x| x.as_str().map(|s| s.to_string()).unwrap_or_else(|| x.to_compact())).collect())
        .unwrap_or_default()
}

/// How the file holds a set's primary: its option's GUID, or an option named like a GUID as it
/// is named (which the original takes for a GUID already).
fn primary_ref(pr: &Project, set: &str, option: &str) -> String {
    if super::electrical::as_guid(option).is_some() {
        return option.to_string();
    }
    pr.lib_guid("design-option", &format!("{}: {}", set, option)).unwrap_or_else(|| option.to_string())
}

/// A set's primary as an option's name (the file holds its GUID).
fn primary_name(pr: &Project, set_name: &str, set: &Value) -> String {
    let raw = match set.get("primary") {
        Some(Value::Str(s)) => s.clone(),
        Some(v) => return v.to_compact(),
        None => return String::new(),
    };
    option_value_name(pr, set_name, &raw)
}

/// An option as a set names it, from its GUID, `Set: Option` or its own name.
fn option_value_name(pr: &Project, set_name: &str, raw: &str) -> String {
    let full = name_of_guid(pr, "design-option", raw).unwrap_or_else(|| raw.to_string());
    if let Some(rest) = full.strip_prefix(&format!("{}: ", set_name)) {
        return rest.to_string();
    }
    if name_of_guid(pr, "design-option", raw).is_some() {
        // an option of another set: its own part
        if let Some((_, o)) = full.split_once(": ") {
            return o.to_string();
        }
    }
    full
}

// ---------------------------------------------------------------- names

/// A name a command is given: text, trimmed, 1 to 256 characters.
fn name_of(v: &Value, cmd: &str, key: &str) -> R<String> {
    if let Value::Str(s) = v {
        let t = s.trim();
        let n = t.chars().count();
        if n >= 1 && n <= 256 {
            return Ok(t.to_string());
        }
    }
    Err(format!("{}: `{}` is a name of 1 to 256 characters, not {}", cmd, key, v.to_compact()))
}

/// A name parameter: None absent or null.
fn opt_name_of(p: &Value, cmd: &str, key: &str) -> R<Option<String>> {
    match p.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(v) => name_of(v, cmd, key).map(Some),
    }
}

/// A name as the model holds one: 1 to 256 characters, nothing round it.
fn name_ok(s: &str) -> bool {
    let n = s.chars().count();
    n >= 1 && n <= 256 && s.trim() == s
}

fn list(names: &[String]) -> String {
    names.join(", ")
}

/// " (there are: a, b)", or nothing where there are none.
fn there_are(names: &[String]) -> String {
    if names.is_empty() {
        String::new()
    } else {
        format!(" (there are: {})", names.join(", "))
    }
}

// ---------------------------------------------------------------- the library

fn phase_guid(pr: &mut Project, name: &str) -> String {
    lib_ensure(pr, "phase", name)
}

/// The name of the phase a value names (its GUID, or its name).
pub fn phase_name_of(pr: &Project, v: &str) -> String {
    name_of_guid(pr, "phase", v).unwrap_or_else(|| v.to_string())
}

pub fn filter_name_of(pr: &Project, v: &str) -> String {
    name_of_guid(pr, "phase-filter", v).unwrap_or_else(|| v.to_string())
}

pub fn set_name_of(pr: &Project, v: &str) -> String {
    name_of_guid(pr, "option-set", v).unwrap_or_else(|| v.to_string())
}

fn pattern_name_of(pr: &Project, v: &str) -> String {
    name_of_guid(pr, "fill-pattern", v).unwrap_or_else(|| v.to_string())
}

// ---------------------------------------------------------------- overrides

#[derive(Clone, Default, PartialEq)]
struct PFill {
    pattern: Option<String>,
    color: [u8; 3],
}

#[derive(Clone, Default, PartialEq)]
struct Style {
    color: Option<[u8; 3]>,
    weight: Option<u64>,
    dash: Option<String>,
    fill: Option<[u8; 3]>,
    foreground: Option<PFill>,
    background: Option<PFill>,
}

impl Style {
    fn is_empty(&self) -> bool {
        *self == Style::default()
    }
}

#[derive(Clone, Default, PartialEq)]
struct Ovr {
    hidden: bool,
    projection: Option<Style>,
    cut: Option<Style>,
    halftone: bool,
    transparency: u64,
    shown: bool,
}

fn sorted_items(m: &Map) -> Vec<(String, Value)> {
    Value::Obj(m.clone()).sorted().as_obj().map(|m| m.items.clone()).unwrap_or_default()
}

fn de_bool(v: &Value) -> R<bool> {
    match v {
        Value::Bool(b) => Ok(*b),
        _ => Err(format!("invalid type: {}, expected a boolean", v.kind_name())),
    }
}

fn de_u8(v: &Value) -> R<u64> {
    use crate::json::Num;
    match v {
        Value::Num(Num::U(u)) if *u <= 255 => Ok(*u),
        Value::Num(Num::U(u)) => Err(format!("invalid value: integer `{}`, expected u8", u)),
        Value::Num(Num::I(i)) => Err(format!("invalid value: integer `{}`, expected u8", i)),
        _ => Err(format!("invalid type: {}, expected u8", v.kind_name())),
    }
}

fn de_colour(v: &Value) -> R<[u8; 3]> {
    color_of(v).ok_or_else(|| format!("{} isn't a colour: [r, g, b], each 0 to 255, or \"#rrggbb\"", v.to_compact()))
}

fn de_rgb_array(v: &Value) -> R<[u8; 3]> {
    let a = match v {
        Value::Arr(a) => a,
        _ => return Err(format!("invalid type: {}, expected an array of length 3", v.kind_name())),
    };
    let mut out = [0u8; 3];
    for i in 0..3 {
        match a.get(i) {
            Some(x) => out[i] = de_u8(x)? as u8,
            None => return Err(format!("invalid length {}, expected an array of length 3", i)),
        }
    }
    if a.len() > 3 {
        return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
    }
    Ok(out)
}

/// A key in a JSON pointer.
fn ptr(k: &str) -> String {
    k.replace('~', "~0").replace('/', "~1")
}

/// A field a struct doesn't know: refused, or (reading a file) left out and listed.
fn unknown(left: &mut Option<&mut Vec<String>>, path: &str, k: &str, msg: String) -> R<()> {
    match left {
        Some(l) => {
            l.push(format!("{}/{}", path, ptr(k)));
            Ok(())
        }
        None => Err(msg),
    }
}

fn de_fill(v: &Value, mut left: Option<&mut Vec<String>>, path: &str) -> R<PFill> {
    let m = match v {
        Value::Obj(m) => m,
        _ => return Err(format!("invalid type: {}, expected struct PatternFill", v.kind_name())),
    };
    let mut f = PFill::default();
    for (k, x) in sorted_items(m) {
        match k.as_str() {
            "pattern" => {
                f.pattern = match &x {
                    Value::Null => None,
                    Value::Str(s) => Some(s.clone()),
                    _ => return Err(format!("invalid type: {}, expected a string", x.kind_name())),
                }
            }
            "color" => f.color = de_rgb_array(&x)?,
            _ => unknown(&mut left, path, &k, format!("unknown field `{}`, expected `pattern` or `color`", k))?,
        }
    }
    Ok(f)
}

fn de_style(v: &Value, mut left: Option<&mut Vec<String>>, path: &str) -> R<Style> {
    let m = match v {
        Value::Obj(m) => m,
        _ => return Err(format!("invalid type: {}, expected struct Style", v.kind_name())),
    };
    let mut st = Style::default();
    for (k, x) in sorted_items(m) {
        let sub = format!("{}/{}", path, ptr(&k));
        match k.as_str() {
            "color" => st.color = Some(de_colour(&x)?),
            "weight" => {
                let w = f64_of(&x)?;
                st.weight = Some(pen_of(w).ok_or_else(|| {
                    format!("a line weight is a pen, a whole number from 0 (a hairline) to 16, not {}", disp(w))
                })?);
            }
            "dash" => {
                st.dash = Some(match &x {
                    Value::Str(s) if ["solid", "dashed", "dotted"].contains(&s.as_str()) => s.clone(),
                    Value::Str(s) => {
                        return Err(format!("unknown variant `{}`, expected one of `solid`, `dashed`, `dotted`", s))
                    }
                    _ => return Err(format!("invalid type: {}, expected string or map", x.kind_name())),
                })
            }
            "fill" => st.fill = Some(de_colour(&x)?),
            "foreground" => st.foreground = Some(de_fill(&x, left.as_deref_mut(), &sub)?),
            "background" => st.background = Some(de_fill(&x, left.as_deref_mut(), &sub)?),
            _ => unknown(
                &mut left,
                path,
                &k,
                format!(
                    "unknown field `{}`, expected one of `color`, `weight`, `dash`, `fill`, `foreground`, `background`",
                    k
                ),
            )?,
        }
    }
    Ok(st)
}

fn de_override(v: &Value, mut left: Option<&mut Vec<String>>, path: &str) -> R<Ovr> {
    let m = match v {
        Value::Obj(m) => m,
        _ => return Err(format!("invalid type: {}, expected struct Override", v.kind_name())),
    };
    let mut o = Ovr::default();
    for (k, x) in sorted_items(m) {
        let sub = format!("{}/{}", path, ptr(&k));
        match k.as_str() {
            "hidden" => o.hidden = de_bool(&x)?,
            "projection" => o.projection = Some(de_style(&x, left.as_deref_mut(), &sub)?),
            "cut" => o.cut = Some(de_style(&x, left.as_deref_mut(), &sub)?),
            "halftone" => o.halftone = de_bool(&x)?,
            "transparency" => o.transparency = de_u8(&x)?,
            "shown" => o.shown = de_bool(&x)?,
            _ => unknown(
                &mut left,
                path,
                &k,
                format!(
                    "unknown field `{}`, expected one of `hidden`, `projection`, `cut`, `halftone`, `transparency`, `shown`",
                    k
                ),
            )?,
        }
    }
    Ok(o)
}

/// A pattern layer as the file holds it (`names`: the pattern by name, else by GUID).
fn fill_value(pr: &Project, f: &PFill, names: bool) -> Value {
    let pat = match &f.pattern {
        None => Value::Null,
        Some(n) => {
            if names {
                Value::s(n)
            } else {
                Value::s(&pr.lib_guid("fill-pattern", n).unwrap_or_else(|| n.clone()))
            }
        }
    };
    jobj! {"pattern" => pat, "color" => color_value(f.color)}
}

fn style_value(pr: &Project, s: &Style, names: bool) -> Value {
    let mut m = Map::new();
    if let Some(c) = s.color {
        m.insert("color", color_value(c));
    }
    if let Some(w) = s.weight {
        m.insert("weight", Value::u(w));
    }
    if let Some(d) = &s.dash {
        m.insert("dash", Value::s(d));
    }
    if let Some(c) = s.fill {
        m.insert("fill", color_value(c));
    }
    if let Some(f) = &s.foreground {
        m.insert("foreground", fill_value(pr, f, names));
    }
    if let Some(f) = &s.background {
        m.insert("background", fill_value(pr, f, names));
    }
    Value::Obj(m)
}

fn override_value(pr: &Project, o: &Ovr, names: bool) -> Value {
    let mut m = Map::new();
    if o.hidden {
        m.insert("hidden", Value::Bool(true));
    }
    if let Some(s) = &o.projection {
        if !s.is_empty() {
            m.insert("projection", style_value(pr, s, names));
        }
    }
    if let Some(s) = &o.cut {
        if !s.is_empty() {
            m.insert("cut", style_value(pr, s, names));
        }
    }
    if o.halftone {
        m.insert("halftone", Value::Bool(true));
    }
    if o.transparency != 0 {
        m.insert("transparency", Value::u(o.transparency));
    }
    if o.shown {
        m.insert("shown", Value::Bool(true));
    }
    Value::Obj(m)
}

/// An override from the file with its fill patterns named.
fn named_override(pr: &Project, v: &Value) -> Value {
    let mut v = v.clone();
    for side in ["projection", "cut"] {
        for layer in ["foreground", "background"] {
            if let Some(Value::Obj(f)) = v.get_mut(side).and_then(|s| s.get_mut(layer)) {
                if let Some(Value::Str(g)) = f.get("pattern") {
                    let n = pattern_name_of(pr, g);
                    f.insert("pattern", Value::s(&n));
                }
            }
        }
    }
    v
}

/// The overrides as `phase` and `inspect` show them: fill patterns by name.
pub fn overrides_shown(pr: &Project) -> Value {
    let mut m = Map::new();
    for (k, v) in &overrides(pr).items {
        m.insert(k, named_override(pr, v));
    }
    Value::Obj(m)
}

/// JSON merge patch: null takes a key away, objects merge, the rest replaces.
fn merge_patch(target: &mut Value, patch: &Value) {
    if let Value::Obj(pm) = patch {
        if !matches!(target, Value::Obj(_)) {
            *target = Value::obj();
        }
        let tm = target.as_obj_mut().unwrap();
        for (k, v) in &pm.items {
            if v.is_null() {
                tm.remove(k);
            } else {
                let mut cur = tm.get(k).cloned().unwrap_or(Value::Null);
                merge_patch(&mut cur, v);
                tm.insert(k, cur);
            }
        }
    } else {
        *target = patch.clone();
    }
}

fn apply_overrides(pr: &mut Project, v: &Value) -> R<bool> {
    let m = match v {
        Value::Obj(m) => m.clone(),
        _ => return Err(format!("phase: `overrides` is {{status: override}}, not {}", v.to_compact())),
    };
    let items = sorted_items(&m);
    for (k, _) in &items {
        if !STATUSES.contains(&k.as_str()) {
            return Err(format!(
                "phase: `overrides`: `{}` isn't a status: new, existing, demolished or temporary",
                k
            ));
        }
    }
    let mut cur = overrides(pr);
    for (k, x) in &items {
        if x.is_null() {
            cur.remove(k);
            continue;
        }
        let mut target = cur.get(k).map(|v| named_override(pr, v)).unwrap_or_else(Value::obj);
        merge_patch(&mut target, x);
        let o = de_override(&target.sorted(), None, "").map_err(|e| format!("phase: the {} phase: {}", k, e))?;
        let fv = override_value(pr, &o, false);
        if fv.as_obj().map(|m| m.is_empty()).unwrap_or(true) {
            cur.remove(k);
        } else {
            cur.insert(k, fv);
        }
    }
    set_overrides(pr, cur);
    Ok(!items.is_empty())
}

// ---------------------------------------------------------------- elements

fn cat(e: &Value) -> &str {
    e.get("category").and_then(|c| c.as_str()).unwrap_or("")
}

fn is_opening(e: &Value) -> bool {
    matches!(cat(e), "door" | "window")
}

fn param<'a>(e: &'a Value, k: &str) -> Option<&'a Value> {
    e.get("params").and_then(|p| p.get(k))
}

/// The fields an element's struct holds after `params`, where it puts them before.
fn after_params(category: &str) -> &'static [&'static str] {
    match category {
        "room" => &["base_offset", "top_level", "limit_offset", "frozen", "kept"],
        "column" | "structuralcolumn" | "footing" => &["room_bounding"],
        _ => &[],
    }
}

/// Sets a value among an element's params (kept in sorted order), making `params` in its place.
pub fn set_param(e: &mut Value, k: &str, v: Value) {
    let category = cat(e).to_string();
    let Value::Obj(m) = e else { return };
    if !m.contains("params") {
        let after = after_params(&category);
        let pos = m.items.iter().position(|(kk, _)| after.contains(&kk.as_str())).unwrap_or(m.items.len());
        m.items.insert(pos, ("params".to_string(), Value::obj()));
    }
    if let Some(Value::Obj(pm)) = m.get_mut("params") {
        pm.insert_sorted(k, v);
    }
}

/// Takes a value away from an element's params, and `params` with its last one.
pub fn remove_param(e: &mut Value, k: &str) {
    let Value::Obj(m) = e else { return };
    let mut empty = false;
    if let Some(Value::Obj(pm)) = m.get_mut("params") {
        pm.remove(k);
        empty = pm.is_empty();
    }
    if empty {
        m.remove("params");
    }
}

fn find_by_guid(pr: &Project, g: &str) -> Option<u64> {
    pr.find_guid(g)
}

/// The phase index an element is made in and taken down in (doors and windows follow their wall);
/// Err with the param and its value where it names no phase.
fn phase_span(pr: &Project, ph: &[String], e: &Value, depth: usize) -> (Option<usize>, Option<usize>) {
    let idx = |v: &Value| -> Option<usize> {
        let s = v.as_str()?;
        let n = phase_name_of(pr, s);
        ph.iter().position(|x| *x == n)
    };
    let own_c = param(e, CREATED).map(|v| idx(v));
    let own_d = param(e, DEMOLISHED).map(|v| idx(v));
    if is_opening(e) && depth < 4 {
        let host = e
            .get("host")
            .and_then(|h| h.as_str())
            .and_then(|g| find_by_guid(pr, g))
            .and_then(|id| pr.el(id));
        let (hc, hd) = match host {
            Some(h) => phase_span(pr, ph, h, depth + 1),
            None => (Some(0), None),
        };
        return (own_c.unwrap_or(hc), own_d.unwrap_or(hd));
    }
    (own_c.unwrap_or(Some(0)), own_d.flatten())
}

/// Elements of the phased categories that hold no `Phase Created` get the first phase's.
fn pin_first(pr: &mut Project) {
    let ph = phases(pr);
    let Some(first) = ph.first().cloned() else { return };
    let ids: Vec<u64> = pr
        .elements
        .iter()
        .filter(|(_, e)| PHASED.contains(&cat(e)) && param(e, CREATED).is_none())
        .map(|(id, _)| *id)
        .collect();
    if ids.is_empty() {
        return;
    }
    let g = phase_guid(pr, &first);
    for id in ids {
        if let Some(e) = pr.elements.get_mut(&id) {
            set_param(e, CREATED, Value::s(&g));
        }
    }
}

/// Every string equal to `from` in the model (but the library) becomes `to`.
fn replace_strings(pr: &mut Project, from: &str, to: &Value) {
    fn walk(v: &mut Value, from: &str, to: &Value) {
        match v {
            Value::Str(s) if s == from => *v = to.clone(),
            Value::Arr(a) => a.iter_mut().for_each(|x| walk(x, from, to)),
            Value::Obj(m) => m.items.iter_mut().for_each(|(_, x)| walk(x, from, to)),
            _ => {}
        }
    }
    for (k, v) in pr.doc.items.iter_mut() {
        if k != "library" && k != "elements" {
            walk(v, from, to);
        }
    }
    for e in pr.elements.values_mut() {
        walk(e, from, to);
    }
}

/// The rules (view filters', schedules') whose value is this GUID name it by text instead.
fn rules_to_text(pr: &mut Project, g: &str, name: &str) {
    fn walk(v: &mut Value, g: &str, name: &str) {
        match v {
            Value::Arr(a) => a.iter_mut().for_each(|x| walk(x, g, name)),
            Value::Obj(m) => {
                if m.contains("field") && m.get("value").and_then(|x| x.as_str()) == Some(g) {
                    m.insert("value", Value::s(name));
                }
                m.items.iter_mut().for_each(|(_, x)| walk(x, g, name));
            }
            _ => {}
        }
    }
    for (k, v) in pr.doc.items.iter_mut() {
        if k != "library" && k != "elements" {
            walk(v, g, name);
        }
    }
    for e in pr.elements.values_mut() {
        walk(e, g, name);
    }
}

/// Deletes elements and what goes with them: the doors and windows of walls, what is hosted by
/// what goes (tags, railings, spot elevations, bars), dimensions left with fewer than two
/// references. The ids that went, in order.
pub fn delete_with_dependants(pr: &mut Project, ids: &BTreeSet<u64>) -> Vec<u64> {
    let mut gone: BTreeSet<u64> = ids.iter().copied().filter(|id| pr.elements.contains_key(id)).collect();
    loop {
        let guids: BTreeSet<String> = gone.iter().filter_map(|id| pr.guid_of(*id)).collect();
        let mut more = Vec::new();
        for (id, e) in &pr.elements {
            if gone.contains(id) {
                continue;
            }
            let hosted = ["host", "wall"].iter().any(|k| e.get(k).and_then(|h| h.as_str()).map(|h| guids.contains(h)).unwrap_or(false));
            let dim_left = match e.get("refs").and_then(|r| r.as_arr()) {
                Some(refs) if cat(e) == "dimension" => {
                    let n = refs.len();
                    let lost = refs
                        .iter()
                        .filter(|r| r.get("id").and_then(|x| x.as_str()).map(|g| guids.contains(g)).unwrap_or(false))
                        .count();
                    lost > 0 && n - lost < 2
                }
                _ => false,
            };
            if hosted || dim_left {
                more.push(*id);
            }
        }
        if more.is_empty() {
            break;
        }
        gone.extend(more);
    }
    let guids: BTreeSet<String> = gone.iter().filter_map(|id| pr.guid_of(*id)).collect();
    for id in &gone {
        pr.elements.remove(id);
    }
    // dimensions lose what went
    for e in pr.elements.values_mut() {
        if cat(e) != "dimension" {
            continue;
        }
        if let Some(Value::Arr(refs)) = e.get_mut("refs") {
            refs.retain(|r| !r.get("id").and_then(|x| x.as_str()).map(|g| guids.contains(g)).unwrap_or(false));
        }
    }
    gone.into_iter().collect()
}

// ---------------------------------------------------------------- phase

fn phase_reply(s: &Session) -> Value {
    let pr = &s.project;
    jobj! {
        "now" => s.now_phase.clone(),
        "overrides" => overrides_shown(pr),
        "phases" => phases(pr),
    }
}

fn no_phase(name: &str, ph: &[String]) -> String {
    format!("phase: no phase `{}` (there are: {})", name, list(ph))
}

/// Whether anything holds a phase: an element made or taken down in it, a view or a template
/// showing it, this session making things in it.
fn phase_in_use(s: &Session, name: &str) -> bool {
    let pr = &s.project;
    let ph = phases(pr);
    let first = ph.first().map(|f| f == name).unwrap_or(false);
    let holds = |v: Option<&Value>| v.and_then(|x| x.as_str()).map(|x| phase_name_of(pr, x) == name).unwrap_or(false);
    for e in pr.elements.values() {
        if holds(param(e, CREATED)) || holds(param(e, DEMOLISHED)) {
            return true;
        }
        if first && PHASED.contains(&cat(e)) && param(e, CREATED).is_none() {
            return true;
        }
        if holds(e.get("graphics").and_then(|g| g.get("phase"))) {
            return true;
        }
    }
    if let Some(t) = pr.section("view_templates") {
        for (_, v) in &t.items {
            if holds(v.get("graphics").and_then(|g| g.get("phase"))) {
                return true;
            }
        }
    }
    s.now_phase.as_deref() == Some(name)
}

/// After a phase's elements moved into another: none taken down before it was made.
fn clamp_demolitions(pr: &mut Project) {
    let ph = phases(pr);
    let ids: Vec<u64> = pr.elements.keys().copied().collect();
    for id in ids {
        let e = &pr.elements[&id];
        if param(e, DEMOLISHED).is_none() {
            continue;
        }
        // made where it (or, a door or window of none, its wall) says
        let (c, d) = phase_span(pr, &ph, e, 0);
        if let (Some(ci), Some(di)) = (c, d) {
            if di < ci {
                let g = phase_guid(pr, &ph[ci]);
                if let Some(e) = pr.elements.get_mut(&id) {
                    set_param(e, DEMOLISHED, Value::s(&g));
                }
            }
        }
    }
}

fn cmd_phase(s: &mut Session, p: &Value) -> R<Value> {
    let cmd = "phase";
    let name = opt_name_of(p, cmd, "name")?;
    let before = opt_name_of(p, cmd, "before")?;
    let after = opt_name_of(p, cmd, "after")?;
    let rename = match p.get("rename") {
        None => None,
        Some(v) => Some(name_of(v, cmd, "rename")?),
    };
    let into = opt_name_of(p, cmd, "into")?;
    let delete = opt_bool(p, cmd, "delete")?.unwrap_or(false);
    let now: Option<Option<String>> = match p.get("now") {
        None => None,
        Some(Value::Null) => Some(None),
        Some(Value::Str(x)) => Some(Some(x.clone())),
        Some(v) => return Err(format!("phase: `now` is a phase's name, or null, not {}", v.to_compact())),
    };
    if name.is_none() && (before.is_some() || after.is_some() || rename.is_some() || into.is_some() || delete) {
        return Err("phase: `name` is required: the phase to rename, delete, or add".into());
    }
    if let Some(name) = name {
        super::mark_step();
        if delete {
            delete_phase(s, &name, into.as_deref())?;
        } else if let Some(r) = rename {
            rename_phase(s, &name, &r)?;
        } else {
            add_phase(s, &name, before.as_deref(), after.as_deref())?;
        }
    }
    if let Some(ov) = p.get("overrides") {
        if !ov.is_null() && apply_overrides(&mut s.project, ov)? {
            super::mark_step();
        }
    }
    if let Some(now) = now {
        if let Some(n) = &now {
            let ph = phases(&s.project);
            if !ph.contains(n) {
                return Err(no_phase(n, &ph));
            }
        }
        s.now_phase = now;
    }
    Ok(phase_reply(s))
}

fn add_phase(s: &mut Session, name: &str, before: Option<&str>, after: Option<&str>) -> R<()> {
    let pr = &mut s.project;
    let mut ph = phases(pr);
    if ph.iter().any(|x| x == name) {
        return Err(format!("phase: there's a phase `{}` already; rename or delete it", name));
    }
    if before.is_some() && after.is_some() {
        return Err("phase: `before` and `after` are two ways to say where; give one".into());
    }
    let pos = if let Some(b) = before {
        ph.iter().position(|x| x == b).ok_or_else(|| no_phase(b, &ph))?
    } else if let Some(a) = after {
        ph.iter().position(|x| x == a).ok_or_else(|| no_phase(a, &ph))? + 1
    } else {
        ph.len()
    };
    if pos == 0 {
        pin_first(pr);
    }
    lib_ensure(pr, "phase", name);
    ph.insert(pos, name.to_string());
    set_phases(pr, &ph);
    Ok(())
}

fn rename_phase(s: &mut Session, name: &str, to: &str) -> R<()> {
    let pr = &mut s.project;
    let mut ph = phases(pr);
    let i = ph.iter().position(|x| x == name).ok_or_else(|| no_phase(name, &ph))?;
    if name == to {
        return Ok(());
    }
    if ph.iter().any(|x| x == to) {
        return Err(format!("phase: there's a phase `{}` already", to));
    }
    ph[i] = to.to_string();
    lib_rename(pr, "phase", name, to);
    set_phases(pr, &ph);
    if s.now_phase.as_deref() == Some(name) {
        s.now_phase = Some(to.to_string());
    }
    Ok(())
}

fn delete_phase(s: &mut Session, name: &str, into: Option<&str>) -> R<()> {
    let ph = phases(&s.project);
    let i = ph.iter().position(|x| x == name).ok_or_else(|| no_phase(name, &ph))?;
    if ph.len() == 1 {
        return Err(format!("phase: `{}` is the project's only phase; a project has one at least", name));
    }
    if let Some(t) = into {
        if !ph.iter().any(|x| x == t) {
            return Err(no_phase(t, &ph));
        }
        if t == name {
            return Err("phase: `into` is another phase than the one that goes".into());
        }
    }
    if into.is_none() && phase_in_use(s, name) {
        return Err(format!("phase: `{}` is in use: say `into` which phase takes its elements and views", name));
    }
    let pr = &mut s.project;
    if i == 0 {
        pin_first(pr);
    }
    let g = pr.lib_guid("phase", name);
    match into {
        Some(t) => {
            let tg = phase_guid(pr, t);
            if let Some(g) = &g {
                replace_strings(pr, g, &Value::s(&tg));
            }
            replace_named(pr, name, &tg);
            if s.now_phase.as_deref() == Some(name) {
                s.now_phase = Some(t.to_string());
            }
        }
        None => {
            if let Some(g) = &g {
                rules_to_text(pr, g, name);
            }
        }
    }
    let pr = &mut s.project;
    let mut ph = ph;
    ph.remove(i);
    set_phases(pr, &ph);
    lib_remove(pr, "phase", name);
    clamp_demolitions(pr);
    Ok(())
}

/// Params and graphics that name a phase by its name (as an older file may) take a GUID instead.
fn replace_named(pr: &mut Project, name: &str, to: &str) {
    for e in pr.elements.values_mut() {
        for k in [CREATED, DEMOLISHED] {
            if param(e, k).and_then(|v| v.as_str()) == Some(name) {
                set_param(e, k, Value::s(to));
            }
        }
        if let Some(Value::Obj(g)) = e.get_mut("graphics") {
            if g.get("phase").and_then(|v| v.as_str()) == Some(name) {
                g.insert("phase", Value::s(to));
            }
        }
    }
}

// ---------------------------------------------------------------- phase filters

fn views_with(pr: &Project, key: &str, g: &str) -> Option<String> {
    for e in pr.elements.values() {
        if e.get("graphics").and_then(|x| x.get(key)).and_then(|x| x.as_str()) == Some(g) {
            return Some(e.get("name").and_then(|n| n.as_str()).unwrap_or("").to_string());
        }
    }
    None
}

fn templates_with(pr: &Project, key: &str, g: &str) -> Option<String> {
    let t = pr.section("view_templates")?;
    for (k, v) in &t.items {
        if v.get("graphics").and_then(|x| x.get(key)).and_then(|x| x.as_str()) == Some(g) {
            return Some(k.clone());
        }
    }
    None
}

fn cmd_phase_filter(s: &mut Session, p: &Value) -> R<Value> {
    let cmd = "phase_filter";
    let name = match p.get("name") {
        None | Some(Value::Null) => return Err("phase_filter: `name` is required".into()),
        Some(v) => name_of(v, cmd, "name")?,
    };
    let delete = opt_bool(p, cmd, "delete")?.unwrap_or(false);
    let pr = &mut s.project;
    let mut f = filters(pr);
    if delete {
        if !f.contains(&name) {
            return Err(format!("phase_filter: there's no phase filter `{}`", name));
        }
        if let Some(g) = pr.lib_guid("phase-filter", &name) {
            if let Some(v) = views_with(pr, "phase_filter", &g) {
                return Err(format!("phase_filter: `{}` is the phase filter of {}; give it another first", name, v));
            }
            if let Some(t) = templates_with(pr, "phase_filter", &g) {
                return Err(format!(
                    "phase_filter: `{}` is the phase filter of view template `{}`; give it another first",
                    name, t
                ));
            }
        }
        f.remove(&name);
        set_filters(pr, f);
        lib_remove(pr, "phase-filter", &name);
        return Ok(jobj! {"deleted" => true, "name" => name});
    }
    let mut given = Vec::new();
    for st in STATUSES {
        match p.get(st) {
            None | Some(Value::Null) => {}
            Some(Value::Str(x)) if SHOWS.contains(&x.as_str()) => given.push((st, x.clone())),
            Some(v) => {
                return Err(format!(
                    "phase_filter: `{}` is by-category, overridden or not-displayed, not {}",
                    st,
                    v.to_compact()
                ))
            }
        }
    }
    if !f.contains(&name) {
        lib_ensure(pr, "phase-filter", &name);
        let mut nf = Map::new();
        for st in STATUSES {
            nf.insert(st, Value::s("by-category"));
        }
        f.insert(&name, Value::Obj(nf));
    }
    if let Some(Value::Obj(fm)) = f.get_mut(&name) {
        for (st, x) in &given {
            fm.insert(st, Value::s(x));
        }
    }
    let shown = f.get(&name).cloned().unwrap_or(Value::Null);
    set_filters(pr, f);
    Ok(jobj! {"filter" => shown, "name" => name})
}

// ---------------------------------------------------------------- design options

fn no_set(name: &str, pr: &Project, with_list: bool) -> String {
    if with_list {
        let names: Vec<String> = option_sets(pr).keys().cloned().collect();
        format!("option: no design option set `{}`{}", name, there_are(&names))
    } else {
        format!("option: no design option set `{}`", name)
    }
}

fn set_reply(s: &Session, name: &str, with_now: bool) -> Value {
    let pr = &s.project;
    let sets = option_sets(pr);
    let set = sets.get(name).cloned().unwrap_or(Value::Null);
    let mut m = Map::new();
    if with_now {
        m.insert("now", Value::from(s.now_option.clone()));
    }
    m.insert("options", Value::from(set_options_of(&set)));
    m.insert("primary", Value::s(&primary_name(pr, name, &set)));
    m.insert("set", Value::s(name));
    Value::Obj(m)
}

/// Whether `Set: Option` names one the project has.
fn option_exists(pr: &Project, full: &str) -> bool {
    let Some((set, opt)) = full.split_once(": ") else { return false };
    option_sets(pr).get(set).map(|v| set_options_of(v).iter().any(|o| o == opt)).unwrap_or(false)
}

/// The elements in an option (its GUID or `Set: Option` in their `Design Option`).
fn elements_in(pr: &Project, set: &str, opt: &str) -> Vec<u64> {
    let full = format!("{}: {}", set, opt);
    let g = pr.lib_guid("design-option", &full);
    pr.elements
        .iter()
        .filter(|(_, e)| {
            param(e, OPTION)
                .and_then(|v| v.as_str())
                .map(|v| v == full || Some(v.to_string()) == g)
                .unwrap_or(false)
        })
        .map(|(id, _)| *id)
        .collect()
}

/// Takes what views and templates show of a set (or of one option of it) away.
fn forget_shown(pr: &mut Project, set_guid: &str, option_guid: Option<&str>) {
    fn strip(g: &mut Value, set_guid: &str, option_guid: Option<&str>) -> bool {
        let Some(Value::Obj(opts)) = g.get_mut("options") else { return false };
        let hit = match opts.get(set_guid).and_then(|v| v.as_str()) {
            Some(v) => option_guid.map(|o| o == v).unwrap_or(true),
            None => false,
        };
        if hit {
            opts.remove(set_guid);
        }
        let empty = opts.is_empty();
        if empty {
            g.remove("options");
        }
        g.as_obj().map(|m| m.is_empty()).unwrap_or(false)
    }
    for e in pr.elements.values_mut() {
        if let Some(g) = e.get_mut("graphics") {
            if strip(g, set_guid, option_guid) {
                e.remove("graphics");
            }
        }
    }
    if let Some(Value::Obj(t)) = pr.doc.get_mut("view_templates") {
        for (_, v) in t.items.iter_mut() {
            if let Some(g) = v.get_mut("graphics") {
                if strip(g, set_guid, option_guid) {
                    v.remove("graphics");
                }
            }
        }
    }
}

fn parse_options(v: &Value) -> R<Vec<String>> {
    let a = match v {
        Value::Arr(a) if a.len() <= 16 => a,
        _ => return Err(format!("option: `options` is a list of up to 16 names, not {}", v.to_compact())),
    };
    let mut out = Vec::new();
    for x in a {
        match x {
            Value::Str(t) if (1..=256).contains(&t.trim().chars().count()) => out.push(t.trim().to_string()),
            _ => return Err(format!("option: an option is a name of 1 to 256 characters, not {}", x.to_compact())),
        }
    }
    Ok(out)
}

fn check_new_options(set: &str, opts: &[String]) -> R<()> {
    if opts.is_empty() {
        return Err(format!("option: set `{}`: `options` names at least one option, not none", set));
    }
    for (i, o) in opts.iter().enumerate() {
        if o.contains(':') {
            return Err(format!("option: set `{}`: option `{}`: a name has no colon in it", set, o));
        }
        if opts[..i].contains(o) {
            return Err(format!("option: set `{}` has option `{}` twice", set, o));
        }
    }
    Ok(())
}

fn cmd_option(s: &mut Session, p: &Value) -> R<Value> {
    let cmd = "option";
    let set = opt_name_of(p, cmd, "set")?;
    let now: Option<Option<String>> = match p.get("now") {
        None => None,
        Some(Value::Null) => Some(None),
        Some(Value::Str(x)) => Some(Some(x.clone())),
        Some(v) => return Err(format!("option: `now` is `set: option`, or null, not {}", v.to_compact())),
    };
    let Some(set) = set else {
        if let Some(now) = now {
            set_now_option(s, now)?;
            return Ok(jobj! {"now" => s.now_option.clone()});
        }
        return Err("option: `set` is required: the design option set to make, change, rename or delete".into());
    };
    let option = opt_name_of(p, cmd, "option")?;
    let rename = opt_name_of(p, cmd, "rename")?;
    let primary = opt_name_of(p, cmd, "primary")?;
    let delete = opt_bool(p, cmd, "delete")?.unwrap_or(false);
    let accept = opt_bool(p, cmd, "accept")?.unwrap_or(false);
    let options = match p.get("options") {
        None | Some(Value::Null) => None,
        Some(v) => Some(parse_options(v)?),
    };
    if set.contains(':') {
        return Err(format!("option: set `{}`: a name has no colon in it", set));
    }
    if let Some(opts) = &options {
        check_new_options(&set, opts)?;
    }
    if delete || accept {
        super::mark_step();
        let deleted = remove_set(s, &set, accept)?;
        return Ok(jobj! {"deleted" => deleted, "set" => set});
    }
    if let Some(to) = rename {
        super::mark_step();
        if !option_sets(&s.project).contains(&set) {
            return Err(no_set(&set, &s.project, false));
        }
        match option {
            Some(o) => {
                rename_option(s, &set, &o, &to)?;
                if let Some(now) = now {
                    set_now_option(s, now)?;
                }
                return Ok(set_reply(s, &set, true));
            }
            None => {
                rename_set(s, &set, &to)?;
                if let Some(now) = now {
                    set_now_option(s, now)?;
                }
                return Ok(set_reply(s, &to, false));
            }
        }
    }
    let exists = option_sets(&s.project).contains(&set);
    if !exists && options.is_none() {
        return Err(format!(
            "option: design option set `{}` doesn't exist: make it with `options`, [\"Option 1\", \"Option 2\"]",
            set
        ));
    }
    if options.is_some() || primary.is_some() {
        super::mark_step();
    }
    if let Some(opts) = options {
        set_options(s, &set, &opts, exists)?;
    }
    let mut bad_primary = None;
    if let Some(pn) = primary {
        let pr = &mut s.project;
        let opts = option_sets(pr).get(&set).map(set_options_of).unwrap_or_default();
        if opts.contains(&pn) {
            let g = primary_ref(pr, &set, &pn);
            let mut sets = option_sets(pr);
            if let Some(Value::Obj(m)) = sets.get_mut(&set) {
                m.insert("primary", Value::s(&g));
            }
            set_option_sets(pr, sets);
        } else {
            bad_primary = Some(pn);
        }
    }
    if let Some(now) = now {
        set_now_option(s, now)?;
    }
    if let Some(pn) = bad_primary {
        // the model's rule, as the check after the command says it
        return Err(format!("design option set `{}`: its primary `{}` isn't one of its options", set, pn));
    }
    Ok(set_reply(s, &set, true))
}

fn set_now_option(s: &mut Session, now: Option<String>) -> R<()> {
    if let Some(n) = &now {
        if !option_exists(&s.project, n) {
            return Err(format!("option: `now` is `set: option`, one the project has; `{}` isn't", n));
        }
    }
    s.now_option = now;
    Ok(())
}

/// Makes a set, or gives it these options (keeping the primary where it stays, else the first).
fn set_options(s: &mut Session, set: &str, opts: &[String], exists: bool) -> R<()> {
    let pr = &mut s.project;
    let mut sets = option_sets(pr);
    if !exists {
        lib_ensure(pr, "option-set", set);
        for o in opts {
            lib_ensure(pr, "design-option", &format!("{}: {}", set, o));
        }
        let primary = primary_ref(pr, set, &opts[0]);
        sets.insert(set, jobj! {"options" => opts.to_vec(), "primary" => primary});
        set_option_sets(pr, sets);
        return Ok(());
    }
    let cur = sets.get(set).cloned().unwrap_or(Value::Null);
    let old = set_options_of(&cur);
    for o in &old {
        if !opts.contains(o) && !elements_in(pr, set, o).is_empty() {
            return Err(format!(
                "option: option `{}` has elements in it; move them (modify {{params}}) or `accept`/`delete` the set first",
                o
            ));
        }
    }
    let primary_was = primary_name(pr, set, &cur);
    for o in opts {
        if !old.contains(o) {
            lib_ensure(pr, "design-option", &format!("{}: {}", set, o));
        }
    }
    let set_guid = pr.lib_guid("option-set", set);
    for o in &old {
        if !opts.contains(o) {
            let full = format!("{}: {}", set, o);
            if let Some(g) = pr.lib_guid("design-option", &full) {
                if let Some(sg) = &set_guid {
                    forget_shown(pr, sg, Some(&g));
                }
                rules_to_text(pr, &g, &full);
            }
            lib_remove(pr, "design-option", &full);
        }
    }
    let primary = if opts.contains(&primary_was) { primary_was } else { opts[0].clone() };
    let pg = primary_ref(pr, set, &primary);
    sets.insert(set, jobj! {"options" => opts.to_vec(), "primary" => pg});
    set_option_sets(pr, sets);
    Ok(())
}

fn rename_set(s: &mut Session, set: &str, to: &str) -> R<()> {
    let pr = &mut s.project;
    let mut sets = option_sets(pr);
    if to == set {
        return Ok(());
    }
    if to.contains(':') {
        return Err(format!("option: `{}`: a name has no colon in it", to));
    }
    if sets.contains(to) {
        return Err(format!("option: there's a design option set `{}` already", to));
    }
    let v = sets.remove(set).unwrap_or(Value::Null);
    for o in set_options_of(&v) {
        lib_rename(pr, "design-option", &format!("{}: {}", set, o), &format!("{}: {}", to, o));
    }
    lib_rename(pr, "option-set", set, to);
    sets.insert(to, v);
    set_option_sets(pr, sets);
    if let Some(n) = &s.now_option {
        if let Some(o) = n.strip_prefix(&format!("{}: ", set)) {
            s.now_option = Some(format!("{}: {}", to, o));
        }
    }
    Ok(())
}

fn rename_option(s: &mut Session, set: &str, opt: &str, to: &str) -> R<()> {
    let pr = &mut s.project;
    let mut sets = option_sets(pr);
    let cur = sets.get(set).cloned().unwrap_or(Value::Null);
    let mut opts = set_options_of(&cur);
    let Some(i) = opts.iter().position(|o| o == opt) else {
        return Err(format!("option: set `{}` has no option `{}` (there are: {})", set, opt, list(&opts)));
    };
    if to == opt {
        return Ok(());
    }
    if to.contains(':') {
        return Err(format!("option: `{}`: a name has no colon in it", to));
    }
    if opts.iter().any(|o| o == to) {
        return Err(format!("option: set `{}` has an option `{}` already", set, to));
    }
    opts[i] = to.to_string();
    lib_rename(pr, "design-option", &format!("{}: {}", set, opt), &format!("{}: {}", set, to));
    if let Some(Value::Obj(m)) = sets.get_mut(set) {
        m.insert("options", Value::from(opts));
    }
    set_option_sets(pr, sets);
    if s.now_option.as_deref() == Some(&format!("{}: {}", set, opt)) {
        s.now_option = Some(format!("{}: {}", set, to));
    }
    Ok(())
}

/// Deletes a set with every element of its options, or (`accept`) keeps its primary's.
fn remove_set(s: &mut Session, set: &str, accept: bool) -> R<Vec<u64>> {
    let pr = &mut s.project;
    let mut sets = option_sets(pr);
    let Some(v) = sets.get(set).cloned() else {
        return Err(no_set(set, pr, true));
    };
    let opts = set_options_of(&v);
    let primary = primary_name(pr, set, &v);
    let mut gone = BTreeSet::new();
    let mut kept = Vec::new();
    for o in &opts {
        let ids = elements_in(pr, set, o);
        if accept && *o == primary {
            kept.extend(ids);
        } else {
            gone.extend(ids);
        }
    }
    for id in &kept {
        if let Some(e) = pr.elements.get_mut(id) {
            remove_param(e, OPTION);
        }
    }
    let deleted = delete_with_dependants(pr, &gone);
    if let Some(sg) = pr.lib_guid("option-set", set) {
        forget_shown(pr, &sg, None);
    }
    for o in &opts {
        let full = format!("{}: {}", set, o);
        if let Some(g) = pr.lib_guid("design-option", &full) {
            rules_to_text(pr, &g, &full);
        }
        lib_remove(pr, "design-option", &full);
    }
    lib_remove(pr, "option-set", set);
    sets.remove(set);
    set_option_sets(pr, sets);
    if let Some(n) = &s.now_option {
        if n.starts_with(&format!("{}: ", set)) {
            s.now_option = None;
        }
    }
    Ok(deleted)
}

// ---------------------------------------------------------------- the rules

/// The model rules of this part, checked after every command.
pub fn check(pr: &crate::project::Project) -> R<()> {
    check_with(pr, &|_, _, _, _| Ok(()))
}

/// What checks an element's other params (a project parameter's value): `(id, element, name,
/// value)`, Err with the message after the element's `category id: `.
pub type ParamRule<'a> = &'a dyn Fn(u64, &Value, &str, &Value) -> R<()>;

/// The rules, with `other` checking the params that aren't phasing's in the same pass: the
/// original goes through an element's params in order (sorted, as it keeps them), phasing's and
/// the project parameters' alike, then sees that it isn't taken down before it is made.
pub fn check_with(pr: &crate::project::Project, other: ParamRule) -> R<()> {
    let ph = phases(pr);
    if ph.is_empty() || ph.len() > 64 {
        return Err(format!("a project has 1 to 64 phases, not {}", ph.len()));
    }
    for (i, n) in ph.iter().enumerate() {
        if !name_ok(n) {
            return Err(format!("phase `{}`: {}", n, NAME_RULE));
        }
        if ph[..i].contains(n) {
            return Err(format!("phase `{}` is in the project twice", n));
        }
    }
    let filters = filters(pr);
    if filters.len() > 64 {
        return Err(format!("the project has {} phase filters; it holds up to 64", filters.len()));
    }
    for (n, _) in &filters.items {
        if !name_ok(n) {
            return Err(format!("phase filter `{}`: {}", n, NAME_RULE));
        }
    }
    let ov = overrides(pr);
    for st in STATUSES {
        let Some(o) = ov.get(st) else { continue };
        let t = o.get("transparency").and_then(|x| x.as_u64()).unwrap_or(0);
        if t > 100 {
            return Err(format!("the {} phase's overrides: transparency is a percent, 0 to 100, not {}", st, t));
        }
        for side in ["projection", "cut"] {
            for layer in ["foreground", "background"] {
                if let Some(Value::Str(g)) = o.get(side).and_then(|x| x.get(layer)).and_then(|x| x.get("pattern")) {
                    let n = pattern_name_of(pr, g);
                    let known = pr.section("fill_patterns").map(|m| m.contains(&n)).unwrap_or(false);
                    if !known {
                        return Err(format!("there's no fill pattern `{}`", n));
                    }
                }
            }
        }
        if o.get("hidden").and_then(|x| x.as_bool()).unwrap_or(false) || t > 0 {
            return Err(format!(
                "the {} phase's overrides: a phase filter hides what it doesn't display; overrides draw",
                st
            ));
        }
    }
    let sets = option_sets(pr);
    if sets.len() > 32 {
        return Err(format!("the project has {} option sets; it holds up to 32", sets.len()));
    }
    for (sn, v) in &sets.items {
        if !name_ok(sn) {
            return Err(format!("design option set `{}`: {}", sn, NAME_RULE));
        }
        if sn.contains(':') {
            return Err(format!("design option set `{}`: a name has no colon in it", sn));
        }
        let opts = set_options_of(v);
        if opts.is_empty() || opts.len() > 16 {
            return Err(format!("design option set `{}` has 1 to 16 options, not {}", sn, opts.len()));
        }
        for (i, o) in opts.iter().enumerate() {
            if !name_ok(o) {
                return Err(format!("design option set `{}`: option `{}`: {}", sn, o, NAME_RULE));
            }
            if o.contains(':') {
                return Err(format!("design option set `{}`: option `{}`: a name has no colon in it", sn, o));
            }
            if opts[..i].contains(o) {
                return Err(format!("design option set `{}` has option `{}` twice", sn, o));
            }
        }
        let prim = primary_name(pr, sn, v);
        if !opts.contains(&prim) {
            return Err(format!("design option set `{}`: its primary `{}` isn't one of its options", sn, prim));
        }
    }
    if let Some(t) = pr.section("view_templates") {
        for (k, v) in &t.items {
            if let Some(g) = v.get("graphics") {
                check_graphics(pr, &ph, &filters, &sets, g).map_err(|e| format!("view template `{}`: {}", k, e))?;
            }
        }
    }
    for (id, e) in &pr.elements {
        if e.get("params").is_some() {
            check_params(pr, &ph, &sets, *id, e, other).map_err(|m| format!("{} {}: {}", cat(e), id, m))?;
        }
        if let Some(g) = e.get("graphics") {
            check_graphics(pr, &ph, &filters, &sets, g).map_err(|m| format!("{} {}: {}", cat(e), id, m))?;
        }
    }
    Ok(())
}

fn check_params(pr: &Project, ph: &[String], sets: &Map, id: u64, e: &Value, other: ParamRule) -> R<()> {
    let items = match e.get("params") {
        Some(Value::Obj(m)) => sorted_items(m),
        _ => Vec::new(),
    };
    for (k, v) in &items {
        if k == OPTION {
            let full = v.as_str().map(|s| name_of_guid(pr, "design-option", s).unwrap_or_else(|| s.to_string()));
            let ok = full
                .as_deref()
                .and_then(|f| f.split_once(": "))
                .map(|(sn, o)| sets.get(sn).map(|sv| set_options_of(sv).iter().any(|x| x == o)).unwrap_or(false))
                .unwrap_or(false);
            if !ok {
                return Err(format!("`{}` is `set: option`, one the project has, not {}", OPTION, v.to_compact()));
            }
        } else if k == CREATED || k == DEMOLISHED {
            let ok = v.as_str().map(|s| ph.contains(&phase_name_of(pr, s))).unwrap_or(false);
            if !ok {
                return Err(format!(
                    "`{}` is one of the project's phases ({}), not {}",
                    k,
                    list(ph),
                    v.to_compact()
                ));
            }
        } else {
            other(id, e, k, v)?;
        }
    }
    let (c, d) = phase_span(pr, ph, e, 0);
    if let (Some(c), Some(d)) = (c, d) {
        if d < c {
            return Err("it can't be demolished in a phase before the one it was made in".into());
        }
    }
    Ok(())
}

/// What a view's or a template's `graphics` names (its phase, phase filter and options) is the
/// project's; else the message `graphics` and `template` give after their own name, and the
/// check after the view's (`there's no phase `X` (there are: …)` and the like).
pub fn check_view_graphics(pr: &Project, g: &Value) -> R<()> {
    check_graphics(pr, &phases(pr), &filters(pr), &option_sets(pr), g)
}

fn check_graphics(pr: &Project, ph: &[String], filters: &Map, sets: &Map, g: &Value) -> R<()> {
    if let Some(Value::Str(x)) = g.get("phase") {
        let n = phase_name_of(pr, x);
        if !ph.contains(&n) {
            return Err(format!("there's no phase `{}` (there are: {})", n, list(ph)));
        }
    }
    if let Some(Value::Str(x)) = g.get("phase_filter") {
        let n = filter_name_of(pr, x);
        if !filters.contains(&n) {
            let names: Vec<String> = filters.keys().cloned().collect();
            return Err(format!("there's no phase filter `{}`{}", n, there_are(&names)));
        }
    }
    if let Some(Value::Obj(opts)) = g.get("options") {
        for (k, v) in &opts.items {
            let sn = set_name_of(pr, k);
            let Some(sv) = sets.get(&sn) else {
                let names: Vec<String> = sets.keys().cloned().collect();
                return Err(format!("there's no design option set `{}`{}", sn, there_are(&names)));
            };
            let raw = v.as_str().map(|s| s.to_string()).unwrap_or_else(|| v.to_compact());
            let o = option_value_name(pr, &sn, &raw);
            let opts = set_options_of(sv);
            if !opts.contains(&o) {
                return Err(format!("design option set `{}` has no option `{}` (there are: {})", sn, o, list(&opts)));
            }
        }
    }
    Ok(())
}

// ---------------------------------------------------------------- what a session makes

/// Whether elements of this category hold a phase and an option (doors and windows included).
pub fn holds_phase(category: &str) -> bool {
    PHASED.contains(&category) || matches!(category, "door" | "window")
}

/// What a new element gets from the session (`now`): its `Phase Created` (none for the first
/// phase, but a door or a window is named, else it would follow its wall) and its `Design Option`,
/// where it holds none of its own. Nothing for what holds no phase (annotation, levels, grids).
pub fn stamp_new(pr: &Project, now_phase: Option<&str>, now_option: Option<&str>, e: &mut Value) {
    let category = cat(e).to_string();
    if !holds_phase(&category) {
        return;
    }
    if let Some(p) = now_phase {
        let first = phases(pr).first().map(|f| f == p).unwrap_or(false);
        if param(e, CREATED).is_none() && (!first || is_opening(e)) {
            if let Some(g) = pr.lib_guid("phase", p) {
                set_param(e, CREATED, Value::s(&g));
            }
        }
    }
    if let Some(o) = now_option {
        if param(e, OPTION).is_none() {
            if let Some(g) = pr.lib_guid("design-option", o) {
                set_param(e, OPTION, Value::s(&g));
            }
        }
    }
}

/// A copy is made in the session's phase (its own `Phase Created` replaced, none for the first
/// phase but on a door or a window, and its `Phase Demolished` dropped) and option, where the
/// session has them; else it keeps its own.
pub fn stamp_copy(pr: &Project, now_phase: Option<&str>, now_option: Option<&str>, e: &mut Value) {
    let category = cat(e).to_string();
    if !holds_phase(&category) {
        return;
    }
    if let Some(p) = now_phase {
        let first = phases(pr).first().map(|f| f == p).unwrap_or(false);
        remove_param(e, DEMOLISHED);
        if first && !is_opening(e) {
            remove_param(e, CREATED);
        } else if let Some(g) = pr.lib_guid("phase", p) {
            set_param(e, CREATED, Value::s(&g));
        }
    }
    if let Some(o) = now_option {
        if let Some(g) = pr.lib_guid("design-option", o) {
            set_param(e, OPTION, Value::s(&g));
        }
    }
}

// ---------------------------------------------------------------- reading a file

/// Reads this part's sections of a project file as the original does: serde's message where a
/// value is of the wrong type (the caller says which file), the fields it doesn't know left out
/// (their JSON pointers returned, for `open`'s `left_out`), and what it keeps written back in
/// full (a filter's four statuses, a pattern layer's colour, overrides in status order).
pub fn load(pr: &mut Project) -> Result<Vec<String>, String> {
    let mut left = Vec::new();
    if let Some(v) = pr.get("phases") {
        let a = v.as_arr().ok_or_else(|| invalid_type(v, "a sequence"))?;
        for x in a {
            if !matches!(x, Value::Str(_)) {
                return Err(invalid_type(x, "a string"));
            }
        }
        let ph = phases(pr);
        set_phases(pr, &ph);
    }
    if let Some(v) = pr.get("phase_filters").cloned() {
        let m = v.as_obj().ok_or_else(|| invalid_type(&v, "a map"))?;
        let mut out = Map::new();
        for (name, f) in &m.items {
            let fm = f.as_obj().ok_or_else(|| invalid_type(f, "struct PhaseFilter"))?;
            let mut nf = Map::new();
            for st in STATUSES {
                nf.insert(st, Value::s("by-category"));
            }
            for (k, x) in &fm.items {
                if STATUSES.contains(&k.as_str()) {
                    match x {
                        Value::Str(s) if SHOWS.contains(&s.as_str()) => nf.insert(k, x.clone()),
                        Value::Str(s) => {
                            return Err(format!(
                                "unknown variant `{}`, expected one of `by-category`, `overridden`, `not-displayed`",
                                s
                            ))
                        }
                        _ => return Err(invalid_type(x, "string or map")),
                    }
                } else {
                    left.push(format!("/phase_filters/{}/{}", ptr(name), ptr(k)));
                }
            }
            out.insert(name, Value::Obj(nf));
        }
        set_filters(pr, out);
    }
    if let Some(v) = pr.get("phase_overrides").cloned() {
        let m = v.as_obj().ok_or_else(|| invalid_type(&v, "a map"))?;
        for (k, _) in &m.items {
            if !STATUSES.contains(&k.as_str()) {
                return Err(format!(
                    "unknown variant `{}`, expected one of `new`, `existing`, `demolished`, `temporary`",
                    k
                ));
            }
        }
        let mut out = Map::new();
        for st in STATUSES {
            if let Some(x) = m.get(st) {
                let o = de_override(x, Some(&mut left), &format!("/phase_overrides/{}", st))?;
                out.insert(st, override_value(pr, &o, true));
            }
        }
        if out == default_overrides() {
            pr.remove_top("phase_overrides");
        } else {
            pr.insert_top("phase_overrides", Value::Obj(out));
        }
    }
    if let Some(v) = pr.get("option_sets").cloned() {
        let m = v.as_obj().ok_or_else(|| invalid_type(&v, "a map"))?;
        let mut out = Map::new();
        for (name, sv) in &m.items {
            let sm = sv.as_obj().ok_or_else(|| invalid_type(sv, "struct OptionSet"))?;
            let mut options = None;
            let mut primary = None;
            for (k, x) in &sm.items {
                match k.as_str() {
                    "options" => {
                        let a = x.as_arr().ok_or_else(|| invalid_type(x, "a sequence"))?;
                        for o in a {
                            if !matches!(o, Value::Str(_)) {
                                return Err(invalid_type(o, "a string"));
                            }
                        }
                        options = Some(x.clone());
                    }
                    "primary" => match x {
                        Value::Str(_) => primary = Some(x.clone()),
                        _ => return Err(invalid_type(x, "a string")),
                    },
                    _ => left.push(format!("/option_sets/{}/{}", ptr(name), ptr(k))),
                }
            }
            let options = options.ok_or_else(|| "missing field `options`".to_string())?;
            let primary = primary.ok_or_else(|| "missing field `primary`".to_string())?;
            out.insert(name, jobj! {"options" => options, "primary" => primary});
        }
        set_option_sets(pr, out);
    }
    Ok(left)
}

// ---------------------------------------------------------------- inspect

/// What `inspect` says of this part's sections.
pub fn inspect_entries(s: &Session, out: &mut Vec<(String, Value)>) {
    let pr = &s.project;
    let mut sets = Map::new();
    for (k, v) in &option_sets(pr).items {
        sets.insert(
            k,
            jobj! {"options" => set_options_of(v), "primary" => primary_name(pr, k, v)},
        );
    }
    out.push(("option_sets".into(), Value::Obj(sets)));
    out.push(("phase_filters".into(), Value::Obj(filters(pr))));
    out.push(("phase_overrides".into(), overrides_shown(pr)));
    out.push(("phases".into(), Value::from(phases(pr))));
}
