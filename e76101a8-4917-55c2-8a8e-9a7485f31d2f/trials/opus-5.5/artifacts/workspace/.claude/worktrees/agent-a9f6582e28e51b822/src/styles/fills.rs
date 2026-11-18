//! Fill patterns and filled region types: `fill_pattern`, `filled_region_type`, `import_fill_patterns`,
//! `export_fill_patterns`.
//!
//! The file keeps `fill_patterns` (by name: `target`, `lines`, `drawn`) and `region_types` (by name:
//! `foreground`, `foreground_color`, `background`, `background_color`, `masking`), both sorted by name;
//! a region type names its patterns, and a filled region its type, by the GUID of the library entry
//! (`fill-pattern`, `filled-region-type`), so a rename is the entry's and what names it follows.

use super::common::*;
use super::pat;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;

const FP: &str = "fill_pattern";
const RT: &str = "filled_region_type";
const KIND_FP: &str = "fill-pattern";
const KIND_RT: &str = "filled-region-type";

use super::check_error;

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "fill_pattern" => fill_pattern(s, p),
        "import_fill_patterns" => import(s, p),
        "export_fill_patterns" => export(s, p),
        "filled_region_type" => region_type(s, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

// ---------------------------------------------------------------- the pattern

/// A family of parallel lines: at `angle` degrees through `origin`, `spacing` apart, each `shift`
/// along from the last, dashed by `dashes` (a dash's length, a space's as a negative one, 0 a dot).
#[derive(Clone, Debug, PartialEq)]
pub struct Hatch {
    pub angle: f64,
    pub origin: [f64; 2],
    pub shift: f64,
    pub spacing: f64,
    pub dashes: Vec<f64>,
}

/// A fill pattern: drafting (mm on paper) or model (mm in the building), its families (none: solid),
/// and the scale of the view a made one was drawn in.
#[derive(Clone, Debug, PartialEq)]
pub struct Pattern {
    pub model: bool,
    pub lines: Vec<Hatch>,
    pub drawn: Option<f64>,
}

fn num_in(v: Option<&Value>) -> f64 {
    v.and_then(|x| x.as_f64()).unwrap_or(0.0)
}

impl Hatch {
    fn from_value(v: &Value) -> Hatch {
        let origin = match v.get("origin").and_then(|o| o.as_arr()) {
            Some(a) if a.len() == 2 => [a[0].as_f64().unwrap_or(0.0), a[1].as_f64().unwrap_or(0.0)],
            _ => [0.0, 0.0],
        };
        Hatch {
            angle: num_in(v.get("angle")),
            origin,
            shift: num_in(v.get("shift")),
            spacing: num_in(v.get("spacing")),
            dashes: v
                .get("dashes")
                .and_then(|d| d.as_arr())
                .map(|a| a.iter().filter_map(|x| x.as_f64()).collect())
                .unwrap_or_default(),
        }
    }

    /// As the file holds it: the origin, the shift and the dashes only where they aren't nothing.
    fn to_value(&self) -> Value {
        let mut m = Map::new();
        m.insert("angle", Value::f(self.angle));
        if !(self.origin[0] == 0.0 && self.origin[1] == 0.0) {
            m.insert("origin", Value::Arr(vec![Value::f(self.origin[0]), Value::f(self.origin[1])]));
        }
        if self.shift != 0.0 {
            m.insert("shift", Value::f(self.shift));
        }
        m.insert("spacing", Value::f(self.spacing));
        if !self.dashes.is_empty() {
            m.insert("dashes", Value::Arr(self.dashes.iter().map(|d| Value::f(*d)).collect()));
        }
        Value::Obj(m)
    }

    fn scale(&mut self, k: f64) {
        self.origin = [self.origin[0] * k, self.origin[1] * k];
        self.shift *= k;
        self.spacing *= k;
        for d in &mut self.dashes {
            *d *= k;
        }
    }
}

impl Pattern {
    pub fn from_value(v: &Value) -> Pattern {
        Pattern {
            model: v.get("target").and_then(|t| t.as_str()) == Some("model"),
            lines: v.get("lines").and_then(|l| l.as_arr()).map(|a| a.iter().map(Hatch::from_value).collect()).unwrap_or_default(),
            drawn: v.get("drawn").and_then(|d| d.as_f64()),
        }
    }

    /// As the file holds it (and replies give it): `target`, `lines` unless solid, `drawn` if any.
    pub fn to_value(&self) -> Value {
        let mut m = Map::new();
        m.insert("target", Value::s(if self.model { "model" } else { "drafting" }));
        if !self.lines.is_empty() {
            m.insert("lines", Value::Arr(self.lines.iter().map(|h| h.to_value()).collect()));
        }
        if let Some(d) = self.drawn {
            m.insert("drawn", Value::f(d));
        }
        Value::Obj(m)
    }

    /// The pattern's rules, as a pattern `name` breaks them.
    pub fn check(&self, name: &str) -> R<()> {
        if let Some(d) = self.drawn {
            if !(d > 0.0 && d <= 100000.0) {
                return Err(format!(
                    "fill pattern `{}`: the scale it was drawn at is a number above 0, at most 100000",
                    name
                ));
            }
        }
        if self.lines.len() > pat::MAX_FAMILIES {
            return Err(format!(
                "fill pattern `{}`: {} line families, more than {}",
                name,
                self.lines.len(),
                pat::MAX_FAMILIES
            ));
        }
        for (i, h) in self.lines.iter().enumerate() {
            let at = format!("fill pattern `{}` line {}", name, i + 1);
            let finite = h.angle.is_finite() && h.origin[0].is_finite() && h.origin[1].is_finite() && h.shift.is_finite();
            if !(finite && h.shift.abs() <= 100000.0) {
                return Err(format!("{}: its angle, origin and shift are numbers, the shift within 100000", at));
            }
            if h.origin[0].abs() > 100000.0 || h.origin[1].abs() > 100000.0 {
                return Err(format!("{}: its origin is within 100000 of the pattern's", at));
            }
            if !(h.spacing >= 0.05 && h.spacing <= 100000.0) {
                return Err(format!("{}: its lines are 0.05 to 100000 apart, not {}", at, disp(h.spacing)));
            }
            if h.dashes.len() > pat::MAX_DASHES {
                return Err(format!("{}: {} dashes and spaces, more than {}", at, h.dashes.len(), pat::MAX_DASHES));
            }
            if !h.dashes.is_empty() {
                if h.dashes.iter().any(|d| !(d.abs() <= 100000.0)) {
                    return Err(format!("{}: a dash or a space is a length within 100000", at));
                }
                let dash = h.dashes.iter().any(|d| *d >= 0.0);
                let space = h.dashes.iter().any(|d| *d < 0.0);
                let total: f64 = h.dashes.iter().map(|d| d.abs()).sum();
                if !(dash && space && total >= 0.05) {
                    return Err(format!(
                        "{}: dashes need a dash (0 is a dot) and a space (a negative length) among them, and 0.05 or more in all",
                        at
                    ));
                }
            }
        }
        Ok(())
    }
}

// ---------------------------------------------------------------- reading parameters as serde does

const LINES_FORM: &str = "`lines` is [{angle, spacing, origin?: [x, y], shift?, dashes?: [mm, -mm, …]}, …]";

/// A map's entries in the order serde visits a JSON object's (sorted by key).
fn sorted_items(m: &Map) -> Vec<(&String, &Value)> {
    let mut v: Vec<(&String, &Value)> = m.items.iter().map(|(k, v)| (k, v)).collect();
    v.sort_by(|a, b| a.0.cmp(b.0));
    v
}

fn de_f64(v: &Value) -> R<f64> {
    match v {
        Value::Num(n) => Ok(n.as_f64()),
        _ => Err(invalid_type(v, "f64")),
    }
}

fn de_p2(v: &Value) -> R<[f64; 2]> {
    let a = match v {
        Value::Arr(a) => a,
        _ => return Err(invalid_type(v, "tuple struct P2")),
    };
    let mut out = [0.0; 2];
    for (i, slot) in out.iter_mut().enumerate() {
        match a.get(i) {
            Some(x) => *slot = de_f64(x)?,
            None => return Err(format!("invalid length {}, expected tuple struct P2 with 2 elements", i)),
        }
    }
    if a.len() > 2 {
        return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
    }
    Ok(out)
}

fn de_seq_f64(v: &Value) -> R<Vec<f64>> {
    match v {
        Value::Arr(a) => a.iter().map(de_f64).collect(),
        _ => Err(invalid_type(v, "a sequence")),
    }
}

/// A hatch line from a sequence, as serde reads a struct from one: its fields in order, the
/// defaulted ones optional.
fn de_hatch_seq(a: &[Value]) -> R<Hatch> {
    let short = |i: usize| format!("invalid length {}, expected struct HatchLine with 5 elements", i);
    let angle = de_f64(a.first().ok_or_else(|| short(0))?)?;
    let origin = match a.get(1) {
        Some(x) => de_p2(x)?,
        None => [0.0, 0.0],
    };
    let shift = match a.get(2) {
        Some(x) => de_f64(x)?,
        None => 0.0,
    };
    let spacing = de_f64(a.get(3).ok_or_else(|| short(3))?)?;
    let dashes = match a.get(4) {
        Some(x) => de_seq_f64(x)?,
        None => Vec::new(),
    };
    if a.len() > 5 {
        return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
    }
    Ok(Hatch { angle, origin, shift, spacing, dashes })
}

fn de_hatch(v: &Value) -> R<Hatch> {
    let m = match v {
        Value::Obj(m) => m,
        Value::Arr(a) => return de_hatch_seq(a),
        _ => return Err(invalid_type(v, "struct HatchLine")),
    };
    let (mut angle, mut spacing) = (None, None);
    let mut h = Hatch { angle: 0.0, origin: [0.0, 0.0], shift: 0.0, spacing: 0.0, dashes: Vec::new() };
    for (k, x) in sorted_items(m) {
        match k.as_str() {
            "angle" => angle = Some(de_f64(x)?),
            "origin" => h.origin = de_p2(x)?,
            "shift" => h.shift = de_f64(x)?,
            "spacing" => spacing = Some(de_f64(x)?),
            "dashes" => h.dashes = de_seq_f64(x)?,
            _ => {
                return Err(format!(
                    "unknown field `{}`, expected one of `angle`, `origin`, `shift`, `spacing`, `dashes`",
                    k
                ))
            }
        }
    }
    h.angle = angle.ok_or_else(|| "missing field `angle`".to_string())?;
    h.spacing = spacing.ok_or_else(|| "missing field `spacing`".to_string())?;
    Ok(h)
}

/// `lines`, as serde reads a Vec of hatch lines (null or absent: None).
fn lines_param(p: &Value) -> R<Option<Vec<Hatch>>> {
    match p.get("lines") {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Arr(a)) => a
            .iter()
            .map(de_hatch)
            .collect::<R<Vec<Hatch>>>()
            .map(Some)
            .map_err(|e| format!("{}: {}: {}", FP, LINES_FORM, e)),
        Some(v) => Err(format!("{}: {}: {}", FP, LINES_FORM, invalid_type(v, "a sequence"))),
    }
}

/// `target`, as serde reads a unit enum (a string, or a map of one key to null).
fn target_param(p: &Value) -> R<Option<bool>> {
    let err = |e: String| format!("{}: `target` is drafting or model: {}", FP, e);
    let variant = |s: &str| match s {
        "drafting" => Ok(false),
        "model" => Ok(true),
        _ => Err(format!("unknown variant `{}`, expected `drafting` or `model`", s)),
    };
    match p.get("target") {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Str(s)) => variant(s).map(Some).map_err(err),
        Some(Value::Obj(m)) => {
            if m.len() != 1 {
                return Err(err("invalid value: map, expected map with a single key".into()));
            }
            let (k, v) = &m.items[0];
            let t = variant(k).map_err(err)?;
            if !v.is_null() {
                return Err(err(invalid_type(v, "unit")));
            }
            Ok(Some(t))
        }
        Some(v) => Err(err(invalid_type(v, "string or map"))),
    }
}

/// `drawn`: absent None, null Some(None) (forget it), a number Some(Some(n)).
fn drawn_param(p: &Value) -> R<Option<Option<f64>>> {
    match p.get("drawn") {
        None => Ok(None),
        Some(Value::Null) => Ok(Some(None)),
        Some(Value::Num(n)) => Ok(Some(Some(n.as_f64()))),
        Some(v) => Err(format!("{}: `drawn` is a view's scale, a number, not {}", FP, v.to_compact())),
    }
}

/// `names`, as serde reads a Vec of strings (null or absent: None).
fn names_param(p: &Value, cmd: &str) -> R<Option<Vec<String>>> {
    let err = |e: String| format!("{}: `names` is [name, …]: {}", cmd, e);
    match p.get("names") {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Arr(a)) => a
            .iter()
            .map(|x| match x {
                Value::Str(s) => Ok(s.clone()),
                _ => Err(err(invalid_type(x, "a string"))),
            })
            .collect::<R<Vec<String>>>()
            .map(Some),
        Some(v) => Err(err(invalid_type(v, "a sequence"))),
    }
}

/// A text parameter as `opt_text` reads it, but untrimmed and kept when empty (a path).
fn raw_text(p: &Value, cmd: &str, key: &str) -> R<Option<String>> {
    match p.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Str(s)) if s.chars().count() <= 256 => Ok(Some(s.clone())),
        Some(v) => Err(format!("{}: `{}` must be text of at most 256 characters, got {}", cmd, key, v.to_compact())),
    }
}

// ---------------------------------------------------------------- the project's patterns

fn patterns(pr: &Project) -> Map {
    section(pr, "fill_patterns")
}

/// The project's patterns' names, in order (a file's section is sorted by name).
fn pattern_names(pr: &Project) -> Vec<String> {
    let mut v: Vec<String> = patterns(pr).keys().cloned().collect();
    v.sort();
    v
}

fn pattern_guid(pr: &Project, name: &str) -> Option<String> {
    guid_of(pr, KIND_FP, name)
}

fn pattern_of_guid(pr: &Project, g: &str) -> Option<String> {
    name_of_guid(pr, KIND_FP, g)
}

/// Whether a value holds this GUID anywhere within it.
fn holds(v: &Value, g: &str) -> bool {
    match v {
        Value::Str(s) => s == g,
        Value::Arr(a) => a.iter().any(|x| holds(x, g)),
        Value::Obj(m) => m.items.iter().any(|(_, x)| holds(x, g)),
        _ => false,
    }
}

// ---------------------------------------------------------------- fill_pattern

fn fill_pattern(s: &mut Session, p: &Value) -> R<Value> {
    check_keys(p, FP, &["name", "target", "lines", "drawn", "rename", "delete"])?;
    let pr = &mut s.project;
    let Some(name) = opt_name(p, FP, "name")? else {
        let mut all = Map::new();
        for (k, v) in patterns(pr).iter() {
            all.insert(k, Pattern::from_value(v).to_value());
        }
        return Ok(jobj! {"patterns" => Value::Obj(all)});
    };
    if opt_bool(p, FP, "delete")? == Some(true) {
        return delete_pattern(pr, &name);
    }
    let all = patterns(pr);
    let existing = all.get(&name).map(Pattern::from_value);
    let given = |k: &str| p.get(k).map(|v| !v.is_null()).unwrap_or(false);
    if existing.is_none() && !given("lines") && !given("target") {
        let names = pattern_names(pr);
        return Err(if names.is_empty() {
            format!("{}: there's no fill pattern `{}`; make one with `lines`", FP, name)
        } else {
            format!("{}: there's no fill pattern `{}`; make one with `lines` (there are: {})", FP, name, names.join(", "))
        });
    }
    let drawn = drawn_param(p)?;
    let lines = lines_param(p)?;
    let target = target_param(p)?;
    let rename = opt_name(p, FP, "rename")?;
    if let Some(r) = &rename {
        if *r != name && all.contains(r) {
            return Err(format!("{}: there's already a fill pattern `{}`", FP, r));
        }
    }
    let is_new = existing.is_none();
    let mut pat = existing.unwrap_or(Pattern { model: false, lines: Vec::new(), drawn: None });
    if let Some(d) = drawn {
        pat.drawn = d;
    }
    let lines_given = lines.is_some();
    if let Some(l) = lines {
        pat.lines = l;
    }
    if let Some(model) = target {
        // a made pattern given another target and no lines is the same drawing, rescaled
        if !is_new && !lines_given && model != pat.model {
            if let Some(n) = pat.drawn {
                let k = if model { n } else { 1.0 / n };
                for h in &mut pat.lines {
                    h.scale(k);
                }
            }
        }
        pat.model = model;
    }
    let final_name = rename.clone().unwrap_or_else(|| name.clone());
    pat.check(&final_name).map_err(|e| format!("{}: {}", FP, e))?;
    let sec = pr.section_mut("fill_patterns");
    if final_name != name {
        sec.remove(&name);
    }
    sec.insert_sorted(&final_name, pat.to_value());
    if final_name != name {
        lib_rename(pr, KIND_FP, &name, &final_name);
    }
    lib_ensure(pr, KIND_FP, &final_name);
    super::mark_step();
    Ok(jobj! {"name" => final_name, "pattern" => pat.to_value()})
}

fn delete_pattern(pr: &mut Project, name: &str) -> R<Value> {
    if !patterns(pr).contains(name) {
        return Err(format!("{}: there's no fill pattern `{}`", FP, name));
    }
    let g = pattern_guid(pr, name).unwrap_or_default();
    if !g.is_empty() {
        let mut types: Vec<(String, Value)> = section(pr, "region_types").items;
        types.sort_by(|a, b| a.0.cmp(&b.0));
        for (t, v) in &types {
            let fg = v.get("foreground").and_then(|x| x.as_str()) == Some(g.as_str());
            let bg = v.get("background").and_then(|x| x.as_str()) == Some(g.as_str());
            if fg || bg {
                return Err(format!("{}: filled region type `{}` fills with `{}`; give it another first", FP, t, name));
            }
        }
        let mut mats: Vec<(String, Value)> = section(pr, "materials").items;
        mats.sort_by(|a, b| a.0.cmp(&b.0));
        for (m, v) in &mats {
            let cut = v.get("cut_pattern").and_then(|x| x.as_str()) == Some(g.as_str());
            let surface = v.get("surface_pattern").and_then(|x| x.as_str()) == Some(g.as_str());
            if cut || surface {
                return Err(format!("{}: material `{}` shows `{}`; give it another first", FP, m, name));
            }
        }
        // what the model's check then finds: views and templates overriding with it
        let mut templates: Vec<(String, Value)> = section(pr, "view_templates").items;
        templates.sort_by(|a, b| a.0.cmp(&b.0));
        for (t, v) in &templates {
            if v.get("graphics").map(|gr| holds(gr, &g)).unwrap_or(false) {
                return Err(check_error(format!("view template `{}`: there's no fill pattern `{}`", t, name)));
            }
        }
        for (id, e) in &pr.elements {
            if e.get("graphics").map(|gr| holds(gr, &g)).unwrap_or(false) {
                let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("element");
                return Err(check_error(format!("{} {}: there's no fill pattern `{}`", cat, id, name)));
            }
        }
    }
    pr.section_mut("fill_patterns").remove(name);
    lib_remove(pr, KIND_FP, name);
    super::mark_step();
    Ok(jobj! {"deleted" => name})
}

// ---------------------------------------------------------------- PAT files

fn import(s: &mut Session, p: &Value) -> R<Value> {
    const C: &str = "import_fill_patterns";
    check_keys(p, C, &["path", "text", "replace"])?;
    let replace = opt_bool(p, C, "replace")?.unwrap_or(false);
    let text = match p.get("text") {
        None | Some(Value::Null) => None,
        Some(Value::Str(t)) => Some(t.clone()),
        Some(_) => return Err(format!("{}: `text` must be the text of a PAT file", C)),
    };
    let path = raw_text(p, C, "path")?;
    let text = match (path, text) {
        (Some(path), None) => {
            let meta = std::fs::metadata(&path).map_err(|e| format!("{}: {}: {}", C, path, e))?;
            if meta.is_file() && meta.len() > pat::MAX_FILE {
                return Err(format!("{}: {} is too large ({} bytes)", C, path, meta.len()));
            }
            let bytes = std::fs::read(&path).map_err(|e| format!("{}: {}: {}", C, path, e))?;
            if bytes.len() as u64 > pat::MAX_FILE {
                return Err(format!("{}: {} is too large ({} bytes)", C, path, bytes.len()));
            }
            pat::decode(&bytes)
        }
        (None, Some(t)) => {
            if t.len() as u64 > pat::MAX_FILE {
                return Err(format!("{}: the file is {} bytes, more than {}", C, t.len(), pat::MAX_FILE));
            }
            t
        }
        _ => return Err(format!("{}: give `path`, a PAT file, or its `text`", C)),
    };
    let file = pat::parse(&text);
    let pr = &mut s.project;
    let had: Vec<String> = pattern_names(pr);
    // what the file itself can't give comes after what the project already has
    let mut seen: Vec<String> = Vec::new();
    let mut valid: Vec<(String, Pattern)> = Vec::new();
    let mut unfit: Vec<Value> = Vec::new();
    for r in file.patterns {
        let why = match r.pattern {
            Err(e) => Some(e),
            Ok(pt) => match pt.check(&r.name) {
                Err(e) => Some(e),
                Ok(()) if seen.contains(&r.name) => Some("the file has it twice".to_string()),
                Ok(()) => {
                    seen.push(r.name.clone());
                    valid.push((r.name.clone(), pt));
                    None
                }
            },
        };
        if let Some(w) = why {
            unfit.push(jobj! {"name" => r.name.clone(), "why" => w});
        }
    }
    let mut imported: Vec<(String, Pattern)> = Vec::new();
    let mut left: Vec<Value> = Vec::new();
    for (n, pt) in valid {
        if had.contains(&n) && !replace {
            left.push(jobj! {"name" => n, "why" => "the project has a pattern of that name"});
        } else {
            imported.push((n, pt));
        }
    }
    left.extend(unfit);
    let count = left.len() + file.unread;
    if file.unread > 0 {
        left.push(jobj! {
            "name" => format!("{} more", file.unread),
            "why" => format!("the file holds more than {} patterns; the rest weren't read", pat::MAX_PATTERNS),
        });
    }
    left.truncate(100);
    let mut new_names: Vec<String> = Vec::new();
    for (n, pt) in &imported {
        pr.section_mut("fill_patterns").insert_sorted(n, pt.to_value());
        if pattern_guid(pr, n).is_none() && !new_names.contains(n) {
            new_names.push(n.clone());
        }
    }
    new_names.sort();
    for n in &new_names {
        lib_ensure(pr, KIND_FP, n);
    }
    super::mark_step();
    let names: Vec<Value> = imported.iter().map(|(n, _)| Value::s(n)).collect();
    Ok(jobj! {"imported" => Value::Arr(names), "left_out" => Value::Arr(left), "left_out_count" => count})
}

fn export(s: &mut Session, p: &Value) -> R<Value> {
    const C: &str = "export_fill_patterns";
    check_keys(p, C, &["path", "names"])?;
    let pr = &s.project;
    let names = names_param(p, C)?;
    let all = patterns(pr);
    if let Some(ns) = &names {
        for n in ns {
            if !all.contains(n) {
                return Err(format!("{}: there's no fill pattern `{}`", C, n));
            }
        }
    }
    let path = raw_text(p, C, "path")?;
    let mut chosen: Vec<(String, Pattern)> = all
        .iter()
        .filter(|(k, _)| names.as_ref().map(|ns| ns.contains(k)).unwrap_or(true))
        .map(|(k, v)| (k.clone(), Pattern::from_value(v)))
        .collect();
    chosen.sort_by(|a, b| a.0.cmp(&b.0));
    let text = pat::write(chosen.iter().map(|(k, v)| (k.as_str(), v)));
    match path {
        None => Ok(jobj! {"text" => text}),
        Some(path) => {
            write_persist(&path, text.as_bytes()).map_err(|e| format!("{}: {}: {}", C, path, e))?;
            Ok(jobj! {"path" => path})
        }
    }
}

/// Writes a file as the tempfile crate's persist does: a hidden file beside it, renamed over it,
/// with that crate's errors.
fn write_persist(path: &str, bytes: &[u8]) -> Result<(), String> {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    let p = std::path::Path::new(path);
    let parent = match p.parent() {
        Some(d) if !d.as_os_str().is_empty() => d.to_path_buf(),
        _ => std::path::PathBuf::from(""),
    };
    let dir = if parent.is_absolute() {
        parent
    } else {
        std::env::current_dir().map_err(|e| e.to_string())?.join(parent)
    };
    let tmp = dir.join(format!(".tmp{}", crate::rand::alnum(6)));
    let at = |e: std::io::Error| format!("{} at path {:?}", e, tmp.to_string_lossy());
    let mut f = std::fs::OpenOptions::new().write(true).create_new(true).mode(0o600).open(&tmp).map_err(at)?;
    if let Err(e) = f.write_all(bytes) {
        drop(f);
        let _ = std::fs::remove_file(&tmp);
        return Err(at(e));
    }
    drop(f);
    std::fs::rename(&tmp, p).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        format!("failed to persist temporary file: {}", e)
    })
}

// ---------------------------------------------------------------- filled_region_type

/// `foreground` or `background`: absent None, null or blank Some(None), a name Some(Some(name)).
fn pattern_param(p: &Value, key: &str) -> R<Option<Option<String>>> {
    match p.get(key) {
        None => Ok(None),
        Some(Value::Null) => Ok(Some(None)),
        Some(Value::Str(s)) => {
            let t = s.trim();
            Ok(Some(if t.is_empty() { None } else { Some(t.to_string()) }))
        }
        Some(v) => Err(format!("{}: `{}` is a fill pattern's name, or null for none, not {}", RT, key, v.to_compact())),
    }
}

/// A region type as replies give it: its patterns by name.
fn type_reply(pr: &Project, v: &Value) -> Value {
    let mut m = Map::new();
    for key in ["foreground", "background"] {
        if let Some(g) = v.get(key).and_then(|x| x.as_str()) {
            if let Some(n) = pattern_of_guid(pr, g) {
                m.insert(key, Value::s(&n));
            }
        }
        let ck = format!("{}_color", key);
        m.insert(&ck, color_value(color_in(v.get(&ck))));
    }
    if v.get("masking").and_then(|x| x.as_bool()) == Some(true) {
        m.insert("masking", Value::Bool(true));
    }
    Value::Obj(m)
}

/// A region type's pattern by name, as its library GUID (None: not given; Some(None): none).
fn resolve_pattern(pr: &mut Project, want: &Option<Option<String>>, type_name: &str) -> R<Option<Option<String>>> {
    match want {
        Some(Some(n)) => {
            if patterns(pr).contains(n) {
                Ok(Some(Some(lib_ensure(pr, KIND_FP, n))))
            } else {
                Err(format!(
                    "{}: filled region type `{}`: there's no fill pattern `{}` (there are: {})",
                    RT,
                    type_name,
                    n,
                    pattern_names(pr).join(", ")
                ))
            }
        }
        Some(None) => Ok(Some(None)),
        None => Ok(None),
    }
}

fn region_type(s: &mut Session, p: &Value) -> R<Value> {
    check_keys(
        p,
        RT,
        &["name", "foreground", "foreground_color", "background", "background_color", "masking", "rename", "delete"],
    )?;
    let pr = &mut s.project;
    let types = section(pr, "region_types");
    let Some(name) = opt_name(p, RT, "name")? else {
        let mut all = Map::new();
        for (k, v) in types.iter() {
            all.insert(k, type_reply(pr, v));
        }
        return Ok(jobj! {"types" => Value::Obj(all)});
    };
    if opt_bool(p, RT, "delete")? == Some(true) {
        return delete_type(pr, &name);
    }
    let fg = pattern_param(p, "foreground")?;
    let bg = pattern_param(p, "background")?;
    let fgc = opt_color(p, RT, "foreground_color")?;
    let bgc = opt_color(p, RT, "background_color")?;
    let masking = opt_bool(p, RT, "masking")?;
    let rename = opt_name(p, RT, "rename")?;
    if let Some(r) = &rename {
        if *r != name && types.contains(r) {
            return Err(format!("{}: there's already a filled region type `{}`", RT, r));
        }
    }
    let final_name = rename.clone().unwrap_or_else(|| name.clone());
    let fg_g = resolve_pattern(pr, &fg, &final_name)?;
    let bg_g = resolve_pattern(pr, &bg, &final_name)?;
    let old = types.get(&name).cloned().unwrap_or_else(Value::obj);
    let pick = |key: &str, given: &Option<Option<String>>| -> Option<String> {
        match given {
            Some(x) => x.clone(),
            None => old.get(key).and_then(|x| x.as_str()).map(|x| x.to_string()),
        }
    };
    let fore = pick("foreground", &fg_g);
    let back = pick("background", &bg_g);
    let fore_c = fgc.unwrap_or_else(|| color_in(old.get("foreground_color")));
    let back_c = bgc.unwrap_or_else(|| color_in(old.get("background_color")));
    let mask = masking.unwrap_or(old.get("masking").and_then(|x| x.as_bool()) == Some(true));
    let mut m = Map::new();
    if let Some(g) = &fore {
        m.insert("foreground", Value::s(g));
    }
    m.insert("foreground_color", color_value(fore_c));
    if let Some(g) = &back {
        m.insert("background", Value::s(g));
    }
    m.insert("background_color", color_value(back_c));
    if mask {
        m.insert("masking", Value::Bool(true));
    }
    let v = Value::Obj(m);
    let sec = pr.section_mut("region_types");
    if final_name != name {
        sec.remove(&name);
    }
    sec.insert_sorted(&final_name, v.clone());
    if final_name != name {
        lib_rename(pr, KIND_RT, &name, &final_name);
    }
    lib_ensure(pr, KIND_RT, &final_name);
    super::mark_step();
    Ok(jobj! {"name" => final_name, "type" => type_reply(pr, &v)})
}

fn delete_type(pr: &mut Project, name: &str) -> R<Value> {
    if !section(pr, "region_types").contains(name) {
        return Err(format!("{}: there's no filled region type `{}`", RT, name));
    }
    let g = guid_of(pr, KIND_RT, name).unwrap_or_default();
    if !g.is_empty() {
        for (id, e) in &pr.elements {
            if e.get("category").and_then(|c| c.as_str()) == Some("region")
                && e.get("type").and_then(|t| t.as_str()) == Some(g.as_str())
            {
                return Err(format!("{}: filled region {} is of `{}`; give it another type first", RT, id, name));
            }
        }
    }
    pr.section_mut("region_types").remove(name);
    lib_remove(pr, KIND_RT, name);
    if !g.is_empty() {
        // what the model's check then finds: detail groups whose members are of it
        let mut groups: Vec<(String, Value)> = section(pr, "detail_groups").items;
        groups.sort_by(|a, b| a.0.cmp(&b.0));
        for (gname, gv) in &groups {
            let members = gv.get("members").and_then(|m| m.as_arr()).cloned().unwrap_or_default();
            for (i, mem) in members.iter().enumerate() {
                let el = mem.get("element");
                let is_region = el.and_then(|e| e.get("category")).and_then(|c| c.as_str()) == Some("region");
                let of_it = el.and_then(|e| e.get("type")).and_then(|t| t.as_str()) == Some(g.as_str());
                if is_region && of_it {
                    let mut rest: Vec<String> = section(pr, "region_types").keys().cloned().collect();
                    rest.sort();
                    return Err(check_error(format!(
                        "detail group `{}` member {}: there's no filled region type `{}` (there are: {})",
                        gname,
                        i,
                        name,
                        rest.join(", ")
                    )));
                }
            }
        }
    }
    super::mark_step();
    Ok(jobj! {"deleted" => name})
}
