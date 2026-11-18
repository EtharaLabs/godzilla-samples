//! Electrical settings: `voltage`, `distribution_system`, `wire_type`.
//!
//! The file keeps them in `voltages`, `distribution_systems` and `wire_types`, each by name in
//! name order, and the library names each (`voltage`, `distribution-system`, `wire-type`) with its
//! GUID; a distribution system names its voltages by their GUIDs. A command takes an entry by its
//! name or its GUID.

use super::common::*;
use crate::json::{Map, Num, Value};
use crate::project::Project;
use crate::session::Session;

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "voltage" => voltage(s, p),
        "distribution_system" => distribution_system(s, p),
        "wire_type" => wire_type(s, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

/// What `inspect` says of the electrical settings.
pub fn inspect_entries(s: &Session, out: &mut Vec<(String, Value)>) {
    let pr = &s.project;
    out.push(("voltages".into(), Value::Obj(section(pr, "voltages"))));
    out.push(("distribution_systems".into(), systems_shown(pr)));
    out.push(("wire_types".into(), Value::Obj(section(pr, "wire_types"))));
}

// ---------------------------------------------------------------- shared

/// A GUID as a command takes one for a library entry: hyphenated, in any case, braced or not;
/// lowercase.
pub fn as_guid(s: &str) -> Option<String> {
    let t = s.trim();
    let t = match t.strip_prefix('{') {
        Some(x) => x.strip_suffix('}')?,
        None => t,
    };
    let b = t.as_bytes();
    if b.len() != 36 {
        return None;
    }
    for (i, c) in b.iter().enumerate() {
        let dash = matches!(i, 8 | 13 | 18 | 23);
        if dash != (*c == b'-') || (!dash && !c.is_ascii_hexdigit()) {
            return None;
        }
    }
    Some(t.to_ascii_lowercase())
}

/// An entry's name from its name or its GUID: a GUID names whatever library entry has it (a
/// voltage's command given a wire type's GUID reads that wire type's name, and finds no voltage).
pub fn resolve(pr: &Project, kind: &str, name: &str) -> String {
    let _ = kind;
    if let Some(g) = as_guid(name) {
        if let Some(e) = pr.library.values().find(|e| e.get("guid").and_then(|x| x.as_str()) == Some(g.as_str())) {
            if let Some(n) = e.get("name").and_then(|n| n.as_str()) {
                return n.to_string();
            }
        }
    }
    name.to_string()
}

/// The model rule that no library entry of these kinds is named like a GUID (a command takes a
/// name or a GUID, so one can't be the other): "voltage `…`: a name isn't a GUID; name it otherwise".
pub fn check_guid_names(pr: &Project, kinds: &[&str]) -> R<()> {
    for e in pr.library.values() {
        let kind = e.get("kind").and_then(|k| k.as_str()).unwrap_or("");
        if !kinds.contains(&kind) {
            continue;
        }
        let name = e.get("name").and_then(|n| n.as_str()).unwrap_or("");
        if as_guid(name).is_some() {
            return Err(format!("{} `{}`: a name isn't a GUID; name it otherwise", kind.replace('-', " "), name));
        }
    }
    // an entry of a section the library doesn't name (a file's) is held to it too
    for (kind, sec) in [
        ("voltage", "voltages"),
        ("distribution-system", "distribution_systems"),
        ("wire-type", "wire_types"),
        ("reinforcement-preset", super::presets::SECTION),
    ] {
        if !kinds.contains(&kind) {
            continue;
        }
        if let Some(m) = pr.section(sec) {
            if let Some(name) = m.keys().find(|n| as_guid(n).is_some()) {
                return Err(format!("{} `{}`: a name isn't a GUID; name it otherwise", kind.replace('-', " "), name));
            }
        }
    }
    Ok(())
}

/// A text parameter as given (not trimmed); None when absent or null.
fn opt_raw_text(p: &Value, cmd: &str, key: &str) -> R<Option<String>> {
    crate::commands::params::opt_text(p, cmd, key)
}

/// A number of some unit: "`key` must be a number of volts, got …".
fn opt_number(p: &Value, cmd: &str, key: &str, unit: &str) -> R<Option<f64>> {
    match p.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Num(n)) => Ok(Some(n.as_f64())),
        Some(v) => Err(format!("{}: `{}` must be a number of {}, got {}", cmd, key, unit, v.to_compact())),
    }
}

/// A whole number 0 to 255 (serde's u8).
fn opt_u8(p: &Value, cmd: &str, key: &str) -> R<Option<u64>> {
    match p.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Num(Num::U(u))) if *u <= 255 => Ok(Some(*u)),
        Some(v) => Err(format!("{}: `{}` must be a whole number from 0 to 255, got {}", cmd, key, v.to_compact())),
    }
}

/// Puts an entry into a section in name order, under its new name when renamed.
fn put(pr: &mut Project, key: &str, old: &str, new: &str, v: Value) {
    let sec = pr.section_mut(key);
    if old != new {
        sec.remove(old);
    }
    sec.insert_sorted(new, v);
}

/// The library entry follows: renamed, or made for a new entry.
fn lib_follow(pr: &mut Project, kind: &str, old: &str, new: &str, existed: bool) {
    if existed {
        if old != new {
            lib_rename(pr, kind, old, new);
        }
    } else {
        lib_ensure(pr, kind, new);
    }
}

fn round1(x: f64) -> f64 {
    (x * 10.0).round() / 10.0
}

// ---------------------------------------------------------------- voltages

/// A voltage as the model holds it: its nominal above 0 and up to 100000 V, and its band round it.
fn check_voltage(name: &str, nominal: f64, min: f64, max: f64) -> R<()> {
    let what = format!("voltage `{}`", name);
    if !(nominal > 0.0 && nominal <= 100000.0) {
        return Err(format!("{}: `nominal` is volts above 0 and up to 100000, not {}", what, disp(nominal)));
    }
    if !(min > 0.0 && min <= nominal) {
        return Err(format!(
            "{}: `min` is volts above 0 and not above the nominal {} V, not {}",
            what,
            disp(nominal),
            disp(min)
        ));
    }
    if !(max >= nominal && max <= 100000.0) {
        return Err(format!(
            "{}: `max` is volts up to 100000 and not under the nominal {} V, not {}",
            what,
            disp(nominal),
            disp(max)
        ));
    }
    Ok(())
}

/// The model rules of the electrical settings: each voltage, distribution system and wire type
/// as its command would take it, in that order and each section in name order.
pub fn check(pr: &Project) -> R<()> {
    let mut voltages: Vec<(String, Value)> = section(pr, "voltages").items;
    voltages.sort_by(|a, b| a.0.cmp(&b.0));
    for (n, v) in &voltages {
        let f = |k: &str| v.get(k).and_then(|x| x.as_f64()).unwrap_or(0.0);
        check_voltage(n, f("nominal"), f("min"), f("max"))?;
    }
    let mut systems: Vec<(String, Value)> = section(pr, "distribution_systems").items;
    systems.sort_by(|a, b| a.0.cmp(&b.0));
    for (n, ds) in &systems {
        let named: Vec<(&str, Option<String>)> = ["l_l", "l_n", "l_g"]
            .iter()
            .map(|k| {
                let n = ds
                    .get(k)
                    .and_then(|g| g.as_str())
                    .map(|g| name_of_guid(pr, "voltage", g).unwrap_or_else(|| g.to_string()));
                (*k, n)
            })
            .collect();
        let u = |k: &str| ds.get(k).and_then(|x| x.as_u64()).unwrap_or(0);
        check_system(pr, n, u("phases"), u("wires"), &named, ds.get("ground").and_then(|g| g.as_str()))?;
    }
    let mut wires: Vec<(String, Value)> = section(pr, "wire_types").items;
    wires.sort_by(|a, b| a.0.cmp(&b.0));
    for (n, wt) in &wires {
        let t = |k: &str| wt.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string();
        let sizes: Vec<Size> = wt
            .get("sizes")
            .and_then(|x| x.as_arr())
            .map(|a| a.iter().filter_map(|r| size_of(r).ok()).collect())
            .unwrap_or_default();
        let temp = wt.get("temperature").and_then(|x| x.as_f64()).unwrap_or(0.0);
        check_wire_type(n, &t("material"), temp, &t("insulation"), &sizes)?;
    }
    Ok(())
}

fn voltage(s: &mut Session, p: &Value) -> R<Value> {
    const CMD: &str = "voltage";
    check_keys(p, CMD, &["name", "nominal", "min", "max", "rename", "delete"])?;
    let pr = &mut s.project;
    let Some(name) = opt_name(p, CMD, "name")? else {
        return Ok(jobj! {"voltages" => Value::Obj(section(pr, "voltages"))});
    };
    let name = resolve(pr, "voltage", &name);
    let existing = pr.section("voltages").and_then(|m| m.get(&name)).cloned();
    if opt_bool(p, CMD, "delete")? == Some(true) {
        if existing.is_none() {
            return Err(format!("{}: there's no voltage `{}`", CMD, name));
        }
        if let Some(g) = pr.lib_guid("voltage", &name) {
            let systems = section(pr, "distribution_systems");
            let mut names: Vec<&String> = systems.keys().collect();
            names.sort();
            for dn in names {
                let ds = systems.get(dn).unwrap();
                if ["l_l", "l_n", "l_g"].iter().any(|k| ds.get(k).and_then(|x| x.as_str()) == Some(g.as_str())) {
                    return Err(format!(
                        "{}: voltage `{}` is one distribution system `{}` supplies: change or delete that first",
                        CMD, name, dn
                    ));
                }
            }
        }
        pr.section_mut("voltages").remove(&name);
        lib_remove(pr, "voltage", &name);
        super::mark_step();
        return Ok(jobj! {"deleted" => name});
    }
    let rename = opt_name(p, CMD, "rename")?;
    if rename.is_some() && existing.is_none() {
        return Err(format!("{}: there's no voltage `{}` to rename", CMD, name));
    }
    let nominal = opt_number(p, CMD, "nominal", "volts")?;
    if nominal.is_none() && existing.is_none() {
        return Err(format!("{}: `nominal` (volts) is required for a new voltage", CMD));
    }
    let min = opt_number(p, CMD, "min", "volts")?;
    let max = opt_number(p, CMD, "max", "volts")?;
    let target = rename.unwrap_or_else(|| name.clone());
    if target != name && pr.section("voltages").map(|m| m.contains(&target)).unwrap_or(false) {
        return Err(format!("{}: there's already a voltage `{}`", CMD, target));
    }
    let old = |k: &str| existing.as_ref().and_then(|e| e.get(k)).and_then(|x| x.as_f64());
    let nominal = nominal.or_else(|| old("nominal")).unwrap_or(0.0);
    let min = min.or_else(|| old("min")).unwrap_or_else(|| round1(nominal * 0.9));
    let max = max.or_else(|| old("max")).unwrap_or_else(|| round1(nominal * 1.1));
    check_voltage(&target, nominal, min, max).map_err(|e| format!("{}: {}", CMD, e))?;
    let v = jobj! {"nominal" => nominal, "min" => min, "max" => max};
    put(pr, "voltages", &name, &target, v.clone());
    lib_follow(pr, "voltage", &name, &target, existing.is_some());
    super::mark_step();
    Ok(jobj! {"name" => target, "voltage" => v})
}

// ---------------------------------------------------------------- distribution systems

const GROUNDS: &[&str] = &["TN-S", "TN-C", "TN-C-S", "TT", "IT"];

/// A distribution system as a reply shows it: its voltages by name.
fn system_shown(pr: &Project, ds: &Value) -> Value {
    let mut out = Map::new();
    if let Some(m) = ds.as_obj() {
        for (k, v) in &m.items {
            if matches!(k.as_str(), "l_l" | "l_n" | "l_g") {
                let g = v.as_str().unwrap_or("");
                let n = name_of_guid(pr, "voltage", g).unwrap_or_else(|| g.to_string());
                out.insert(k, Value::Str(n));
            } else {
                out.insert(k, v.clone());
            }
        }
    }
    Value::Obj(out)
}

fn systems_shown(pr: &Project) -> Value {
    let mut out = Map::new();
    for (k, v) in section(pr, "distribution_systems").items {
        out.insert(&k, system_shown(pr, &v));
    }
    Value::Obj(out)
}

/// A distribution system as the model holds it (its voltages by name: `l_l`, `l_n`, `l_g`).
fn check_system(
    pr: &Project,
    name: &str,
    phases: u64,
    wires: u64,
    named: &[(&str, Option<String>)],
    ground: Option<&str>,
) -> R<()> {
    let what = format!("distribution system `{}`", name);
    if !(1..=3).contains(&phases) {
        return Err(format!("{}: `phases` is 1, 2 or 3, not {}", what, phases));
    }
    let lo = phases.max(2);
    let hi = phases + 1;
    if wires < lo || wires > hi {
        return Err(format!(
            "{}: `wires` counts the line conductors and the neutral, not the protective one: {} to {} for {} {}, not {}",
            what,
            lo,
            hi,
            phases,
            if phases == 1 { "phase" } else { "phases" },
            wires
        ));
    }
    if named.iter().all(|(_, n)| n.is_none()) {
        return Err(format!("{}: it supplies no voltage; give `l_l`, `l_n` or `l_g`", what));
    }
    if phases >= 2 && named[0].1.is_none() {
        return Err(format!("{}: `l_l`, the voltage between lines, is required for {} phases", what, phases));
    }
    let voltages = section(pr, "voltages");
    for (k, n) in named {
        if let Some(n) = n {
            if !voltages.contains(n) {
                let mut have: Vec<&String> = voltages.keys().collect();
                have.sort();
                let have: Vec<&str> = have.iter().map(|s| s.as_str()).collect();
                return Err(format!(
                    "{}: `{}` names voltage `{}`, which the project doesn't have (there are: {})",
                    what,
                    k,
                    n,
                    have.join(", ")
                ));
            }
        }
    }
    if phases == 3 {
        if let (Some(ll), Some(ln)) = (&named[0].1, &named[1].1) {
            let vl = voltages.get(ll).and_then(|v| v.get("nominal")).and_then(|x| x.as_f64()).unwrap_or(0.0);
            let vn = voltages.get(ln).and_then(|v| v.get("nominal")).and_then(|x| x.as_f64()).unwrap_or(0.0);
            let s3 = 3f64.sqrt();
            if ((vl / vn) / s3 - 1.0).abs() > 0.03 {
                return Err(format!(
                    "{}: with 3 phases `l_l` `{}` ({} V) should be about 1.73 times `l_n` `{}` ({} V)",
                    what,
                    ll,
                    disp(vl),
                    ln,
                    disp(vn)
                ));
            }
        }
    }
    if let Some(g) = ground {
        if !GROUNDS.contains(&g) {
            return Err(format!("{}: `ground` is the earthing, one of {}, not `{}`", what, GROUNDS.join(", "), g));
        }
    }
    Ok(())
}

fn distribution_system(s: &mut Session, p: &Value) -> R<Value> {
    const CMD: &str = "distribution_system";
    check_keys(p, CMD, &["name", "phases", "wires", "l_l", "l_n", "l_g", "ground", "rename", "delete"])?;
    let pr = &mut s.project;
    let Some(name) = opt_name(p, CMD, "name")? else {
        return Ok(jobj! {"distribution_systems" => systems_shown(pr)});
    };
    let name = resolve(pr, "distribution-system", &name);
    let existing = pr.section("distribution_systems").and_then(|m| m.get(&name)).cloned();
    if opt_bool(p, CMD, "delete")? == Some(true) {
        if existing.is_none() {
            return Err(format!("{}: there's no distribution system `{}`", CMD, name));
        }
        pr.section_mut("distribution_systems").remove(&name);
        lib_remove(pr, "distribution-system", &name);
        super::mark_step();
        return Ok(jobj! {"deleted" => name});
    }
    let rename = opt_name(p, CMD, "rename")?;
    if rename.is_some() && existing.is_none() {
        return Err(format!("{}: there's no distribution system `{}` to rename", CMD, name));
    }
    let phases = opt_u8(p, CMD, "phases")?;
    if phases.is_none() && existing.is_none() {
        return Err(format!("{}: `phases` (1, 2 or 3) is required for a new distribution system", CMD));
    }
    let wires = opt_u8(p, CMD, "wires")?;
    if wires.is_none() && existing.is_none() {
        return Err(format!(
            "{}: `wires` (the line conductors and the neutral) is required for a new distribution system",
            CMD
        ));
    }
    // each voltage: None, not given; Some(None), taken away; Some(Some(name))
    let mut volts: Vec<(&str, Option<Option<String>>)> = Vec::new();
    for k in ["l_l", "l_n", "l_g"] {
        let v = opt_raw_text(p, CMD, k)?.map(|t| {
            let t = t.trim().to_string();
            if t.is_empty() {
                None
            } else {
                Some(t)
            }
        });
        volts.push((k, v));
    }
    let ground = opt_raw_text(p, CMD, "ground")?.map(|t| {
        let t = t.trim().to_string();
        if t.is_empty() {
            None
        } else {
            Some(t)
        }
    });
    let target = rename.unwrap_or_else(|| name.clone());
    if target != name && pr.section("distribution_systems").map(|m| m.contains(&target)).unwrap_or(false) {
        return Err(format!("{}: there's already a distribution system `{}`", CMD, target));
    }
    let old = existing.clone().unwrap_or_else(Value::obj);
    let phases = phases.or_else(|| old.get("phases").and_then(|x| x.as_u64())).unwrap_or(0);
    let wires = wires.or_else(|| old.get("wires").and_then(|x| x.as_u64())).unwrap_or(0);
    // the voltages by name (a GUID given resolved), as they will be
    let mut named: Vec<(&str, Option<String>)> = Vec::new();
    for (k, v) in &volts {
        let n = match v {
            Some(x) => x.clone().map(|n| resolve(pr, "voltage", &n)),
            None => old
                .get(k)
                .and_then(|g| g.as_str())
                .map(|g| name_of_guid(pr, "voltage", g).unwrap_or_else(|| g.to_string())),
        };
        named.push((k, n));
    }
    let ground = match ground {
        Some(g) => g,
        None => old.get("ground").and_then(|g| g.as_str()).map(|g| g.to_string()),
    };
    check_system(pr, &target, phases, wires, &named, ground.as_deref()).map_err(|e| format!("{}: {}", CMD, e))?;
    let mut m = Map::new();
    m.insert("phases", Value::u(phases));
    m.insert("wires", Value::u(wires));
    for (k, n) in &named {
        if let Some(n) = n {
            let g = pr.lib_guid("voltage", n).unwrap_or_else(|| lib_ensure(pr, "voltage", n));
            m.insert(k, Value::Str(g));
        }
    }
    if let Some(g) = ground {
        m.insert("ground", Value::Str(g));
    }
    let v = Value::Obj(m);
    put(pr, "distribution_systems", &name, &target, v.clone());
    lib_follow(pr, "distribution-system", &name, &target, existing.is_some());
    super::mark_step();
    let shown = system_shown(pr, &v);
    Ok(jobj! {"distribution_system" => shown, "name" => target})
}

// ---------------------------------------------------------------- wire types

const MATERIALS: &[&str] = &["copper", "aluminium"];

struct Size {
    section: f64,
    ampacity: f64,
    label: Option<String>,
}

/// One row of `sizes`, as serde reads a `WireSize` {section, ampacity, label?}: from a map
/// (its keys in order, unknown ones refused) or from a sequence.
fn size_of(v: &Value) -> Result<Size, String> {
    let label_of = |x: &Value| -> Result<Option<String>, String> {
        match x {
            Value::Null => Ok(None),
            Value::Str(s) => Ok(Some(s.clone())),
            other => Err(invalid_type(other, "a string")),
        }
    };
    match v {
        Value::Obj(_) => {
            let sorted = v.clone().sorted();
            let m = sorted.as_obj().unwrap();
            let (mut section, mut ampacity, mut label) = (None, None, None);
            for (k, x) in &m.items {
                match k.as_str() {
                    "section" => section = Some(f64_of(x)?),
                    "ampacity" => ampacity = Some(f64_of(x)?),
                    "label" => label = Some(label_of(x)?),
                    other => {
                        return Err(format!(
                            "unknown field `{}`, expected one of `section`, `ampacity`, `label`",
                            other
                        ))
                    }
                }
            }
            let section = section.ok_or("missing field `section`")?;
            let ampacity = ampacity.ok_or("missing field `ampacity`")?;
            Ok(Size { section, ampacity, label: label.flatten() })
        }
        Value::Arr(a) => {
            let short = |n: usize| format!("invalid length {}, expected struct WireSize with 3 elements", n);
            let section = f64_of(a.first().ok_or_else(|| short(0))?)?;
            let ampacity = f64_of(a.get(1).ok_or_else(|| short(1))?)?;
            let label = match a.get(2) {
                Some(x) => label_of(x)?,
                None => None,
            };
            if a.len() > 3 {
                return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
            }
            Ok(Size { section, ampacity, label })
        }
        other => Err(invalid_type(other, "struct WireSize")),
    }
}

fn sizes_of(v: &Value) -> Result<Vec<Size>, String> {
    match v {
        Value::Arr(a) => a.iter().map(size_of).collect(),
        other => Err(invalid_type(other, "a sequence")),
    }
}

fn size_value(s: &Size) -> Value {
    let mut m = Map::new();
    m.insert("section", Value::f(s.section));
    m.insert("ampacity", Value::f(s.ampacity));
    if let Some(l) = &s.label {
        m.insert("label", Value::Str(l.clone()));
    }
    Value::Obj(m)
}

fn wire_type(s: &mut Session, p: &Value) -> R<Value> {
    const CMD: &str = "wire_type";
    check_keys(p, CMD, &["name", "material", "temperature", "insulation", "note", "sizes", "rename", "delete"])?;
    let pr = &mut s.project;
    let Some(name) = opt_name(p, CMD, "name")? else {
        return Ok(jobj! {"wire_types" => Value::Obj(section(pr, "wire_types"))});
    };
    let name = resolve(pr, "wire-type", &name);
    let existing = pr.section("wire_types").and_then(|m| m.get(&name)).cloned();
    if opt_bool(p, CMD, "delete")? == Some(true) {
        if existing.is_none() {
            return Err(format!("{}: there's no wire type `{}`", CMD, name));
        }
        pr.section_mut("wire_types").remove(&name);
        lib_remove(pr, "wire-type", &name);
        super::mark_step();
        return Ok(jobj! {"deleted" => name});
    }
    let rename = opt_name(p, CMD, "rename")?;
    if rename.is_some() && existing.is_none() {
        return Err(format!("{}: there's no wire type `{}` to rename", CMD, name));
    }
    let new = existing.is_none();
    let material = opt_raw_text(p, CMD, "material")?;
    if material.is_none() && new {
        return Err(format!("{}: `material` (copper, aluminium) is required for a new wire type", CMD));
    }
    let temperature = opt_number(p, CMD, "temperature", "°C")?;
    if temperature.is_none() && new {
        return Err(format!("{}: `temperature` (°C) is required for a new wire type", CMD));
    }
    let insulation = opt_raw_text(p, CMD, "insulation")?;
    if insulation.is_none() && new {
        return Err(format!("{}: `insulation` is required for a new wire type", CMD));
    }
    let note = opt_raw_text(p, CMD, "note")?;
    let sizes = match p.get("sizes") {
        None | Some(Value::Null) => None,
        Some(v) => {
            let rows = sizes_of(v)
                .map_err(|e| format!("{}: `sizes` must be a list of {{section, ampacity, label?}}: {}", CMD, e))?;
            if rows.len() > 64 {
                return Err(format!("{}: `sizes` holds up to 64 rows", CMD));
            }
            Some(rows)
        }
    };
    if sizes.is_none() && new {
        return Err(format!("{}: `sizes` [{{section, ampacity}}, …] is required for a new wire type", CMD));
    }
    let target = rename.unwrap_or_else(|| name.clone());
    if target != name && pr.section("wire_types").map(|m| m.contains(&target)).unwrap_or(false) {
        return Err(format!("{}: there's already a wire type `{}`", CMD, target));
    }
    let old = existing.clone().unwrap_or_else(Value::obj);
    let text = |k: &str| old.get(k).and_then(|x| x.as_str()).map(|x| x.to_string());
    let material = material.or_else(|| text("material")).unwrap_or_default();
    let temperature = temperature.or_else(|| old.get("temperature").and_then(|x| x.as_f64())).unwrap_or(0.0);
    let insulation = insulation.or_else(|| text("insulation")).unwrap_or_default();
    let note = match note {
        Some(n) if n.is_empty() => None,
        Some(n) => Some(n),
        None => text("note"),
    };
    let sizes = match sizes {
        Some(s) => s,
        None => old
            .get("sizes")
            .and_then(|x| x.as_arr())
            .map(|a| a.iter().filter_map(|r| size_of(r).ok()).collect())
            .unwrap_or_default(),
    };
    check_wire_type(&target, &material, temperature, &insulation, &sizes).map_err(|e| format!("{}: {}", CMD, e))?;
    let mut m = Map::new();
    m.insert("material", Value::Str(material));
    m.insert("temperature", Value::f(temperature));
    m.insert("insulation", Value::Str(insulation));
    if let Some(n) = note {
        m.insert("note", Value::Str(n));
    }
    m.insert("sizes", Value::Arr(sizes.iter().map(size_value).collect()));
    let v = Value::Obj(m);
    put(pr, "wire_types", &name, &target, v.clone());
    lib_follow(pr, "wire-type", &name, &target, existing.is_some());
    super::mark_step();
    Ok(jobj! {"name" => target, "wire_type" => v})
}

/// A wire type as the model holds it: its material, working temperature, insulation, and 1 to 64
/// rows of sections growing, each carrying at least what the one before does.
fn check_wire_type(name: &str, material: &str, temperature: f64, insulation: &str, sizes: &[Size]) -> R<()> {
    let what = format!("wire type `{}`", name);
    if !MATERIALS.contains(&material) {
        return Err(format!("{}: `material` is one of {}, not `{}`", what, MATERIALS.join(", "), material));
    }
    if !(temperature > 0.0 && temperature <= 250.0) {
        return Err(format!("{}: `temperature` is °C above 0 and up to 250, not {}", what, disp(temperature)));
    }
    if insulation.trim().is_empty() || insulation.chars().count() > 256 {
        return Err(format!("{}: `insulation` is 1 to 256 characters", what));
    }
    if sizes.is_empty() || sizes.len() > 64 {
        return Err(format!("{}: `sizes` holds 1 to 64 rows, not {}", what, sizes.len()));
    }
    for (i, r) in sizes.iter().enumerate() {
        let row = i + 1;
        if !(r.section > 0.0 && r.section <= 10000.0) {
            return Err(format!(
                "{}: row {}: `section` is mm² above 0 and up to 10000, not {}",
                what,
                row,
                disp(r.section)
            ));
        }
        if !(r.ampacity > 0.0 && r.ampacity <= 100000.0) {
            return Err(format!(
                "{}: row {}: `ampacity` is amperes above 0 and up to 100000, not {}",
                what,
                row,
                disp(r.ampacity)
            ));
        }
        if i > 0 {
            let prev = &sizes[i - 1];
            if !(r.section > prev.section) {
                return Err(format!(
                    "{}: row {}: `section` {} mm² must be larger than the row before's {} mm²",
                    what,
                    row,
                    disp(r.section),
                    disp(prev.section)
                ));
            }
            if r.ampacity < prev.ampacity {
                return Err(format!(
                    "{}: row {}: `ampacity` {} A is less than the row before's {} A: a larger section carries at least as much",
                    what,
                    row,
                    disp(r.ampacity),
                    disp(prev.ampacity)
                ));
            }
        }
    }
    Ok(())
}
