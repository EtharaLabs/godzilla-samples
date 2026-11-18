//! A project file's scans (`clouds`), read back: each entry as the original's `CloudFile`
//! (its fields as serde would take them, in the order a JSON map visits them), then every check
//! a scan's making makes, the file held to `MAX_CLOUDS` scans and `MAX_CLOUD_POINTS` points while
//! it is read; and the rules the model keeps for point clouds after every command.

use super::read::{MAX_CLOUDS, MAX_CLOUD_POINTS, MAX_FAR, MAX_SPAN};
use crate::json::{fmt_f64, Map, Num, Value};
use crate::project::Project;

/// The most bytes a scan's points unpack to, and its colours.
const POINTS_CAP: usize = MAX_CLOUD_POINTS as usize * 12;
const COLOURS_CAP: usize = MAX_CLOUD_POINTS as usize * 3;

/// How serde names a value in "invalid type" errors.
fn unexpected(v: &Value) -> String {
    match v {
        Value::Num(Num::F(f)) => format!("floating point `{}`", fmt_f64(*f)),
        Value::Obj(_) => "map".into(),
        _ => v.kind_name(),
    }
}

fn invalid_type(v: &Value, expected: &str) -> String {
    format!("invalid type: {}, expected {}", unexpected(v), expected)
}

fn as_string(v: &Value) -> Result<String, String> {
    match v {
        Value::Str(s) => Ok(s.clone()),
        _ => Err(invalid_type(v, "a string")),
    }
}

fn as_usize(v: &Value) -> Result<u64, String> {
    match v {
        Value::Num(Num::U(u)) => Ok(*u),
        Value::Num(Num::I(i)) => Err(format!("invalid value: integer `{}`, expected usize", i)),
        _ => Err(invalid_type(v, "usize")),
    }
}

fn as_f64(v: &Value) -> Result<f64, String> {
    match v {
        Value::Num(n) => Ok(n.as_f64()),
        _ => Err(invalid_type(v, "f64")),
    }
}

fn sorted(m: &Map) -> Vec<(&String, &Value)> {
    let mut v: Vec<(&String, &Value)> = m.iter().collect();
    v.sort_by(|a, b| a.0.cmp(b.0));
    v
}

struct Station {
    source: String,
    points: u64,
}

struct CloudFile {
    source: String,
    stations: Vec<Station>,
    origin: [f64; 3],
    read: u64,
    points: String,
    colours: Option<String>,
}

fn station_of(v: &Value) -> Result<Station, String> {
    let m = match v {
        Value::Obj(m) => m,
        // serde takes a struct from a sequence too: its fields in order
        Value::Arr(a) => {
            let what = "struct Station with 2 elements";
            let source = as_string(a.first().ok_or_else(|| format!("invalid length 0, expected {}", what))?)?;
            let points = as_usize(a.get(1).ok_or_else(|| format!("invalid length 1, expected {}", what))?)?;
            if a.len() > 2 {
                return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
            }
            return Ok(Station { source, points });
        }
        _ => return Err(invalid_type(v, "struct Station")),
    };
    let (mut source, mut points) = (None, None);
    for (k, x) in sorted(m) {
        match k.as_str() {
            "source" => source = Some(as_string(x)?),
            "points" => points = Some(as_usize(x)?),
            _ => {}
        }
    }
    Ok(Station {
        source: source.ok_or_else(|| "missing field `source`".to_string())?,
        points: points.ok_or_else(|| "missing field `points`".to_string())?,
    })
}

fn origin_of(v: &Value) -> Result<[f64; 3], String> {
    let a = match v {
        Value::Arr(a) => a,
        _ => return Err(invalid_type(v, "an array of length 3")),
    };
    let mut o = [0.0; 3];
    for (k, x) in a.iter().enumerate() {
        if k >= 3 {
            return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
        }
        o[k] = as_f64(x)?;
    }
    if a.len() < 3 {
        return Err(format!("invalid length {}, expected an array of length 3", a.len()));
    }
    Ok(o)
}

fn stations_of(x: &Value) -> Result<Vec<Station>, String> {
    let a = match x {
        Value::Arr(a) => a,
        _ => return Err(invalid_type(x, "a sequence")),
    };
    a.iter().map(station_of).collect()
}

fn colours_of(x: &Value) -> Result<Option<String>, String> {
    match x {
        Value::Null => Ok(None),
        _ => Ok(Some(as_string(x)?)),
    }
}

/// A `CloudFile` written as a sequence: its fields in their order, those with defaults optional.
fn cloud_file_of_seq(a: &[Value]) -> Result<CloudFile, String> {
    let short = |i: usize| format!("invalid length {}, expected struct CloudFile with 6 elements", i);
    let source = as_string(a.first().ok_or_else(|| short(0))?)?;
    let stations = match a.get(1) {
        Some(x) => stations_of(x)?,
        None => Vec::new(),
    };
    let origin = origin_of(a.get(2).ok_or_else(|| short(2))?)?;
    let read = as_usize(a.get(3).ok_or_else(|| short(3))?)?;
    let points = as_string(a.get(4).ok_or_else(|| short(4))?)?;
    let colours = match a.get(5) {
        Some(x) => colours_of(x)?,
        None => None,
    };
    if a.len() > 6 {
        return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
    }
    Ok(CloudFile { source, stations, origin, read, points, colours })
}

fn cloud_file_of(v: &Value) -> Result<CloudFile, String> {
    let m = match v {
        Value::Obj(m) => m,
        Value::Arr(a) => return cloud_file_of_seq(a),
        _ => return Err(invalid_type(v, "struct CloudFile")),
    };
    let (mut source, mut stations, mut origin, mut read, mut points, mut colours) = (None, None, None, None, None, None);
    for (k, x) in sorted(m) {
        match k.as_str() {
            "source" => source = Some(as_string(x)?),
            "stations" => stations = Some(stations_of(x)?),
            "origin" => origin = Some(origin_of(x)?),
            "read" => read = Some(as_usize(x)?),
            "points" => points = Some(as_string(x)?),
            "colours" => colours = Some(colours_of(x)?),
            _ => {}
        }
    }
    let missing = |f: &str| format!("missing field `{}`", f);
    Ok(CloudFile {
        source: source.ok_or_else(|| missing("source"))?,
        stations: stations.unwrap_or_default(),
        origin: origin.ok_or_else(|| missing("origin"))?,
        read: read.ok_or_else(|| missing("read"))?,
        points: points.ok_or_else(|| missing("points"))?,
        colours: colours.unwrap_or(None),
    })
}

/// Base64 as the original reads it: spaces, line breaks and `=` passed over wherever they are,
/// and what is left of a last group less than a byte let go.
pub fn base64_lenient(s: &str) -> Option<Vec<u8>> {
    let mut out = Vec::with_capacity(s.len() / 4 * 3);
    let mut acc: u32 = 0;
    let mut bits = 0;
    for ch in s.bytes() {
        let v = match ch {
            b'A'..=b'Z' => ch - b'A',
            b'a'..=b'z' => ch - b'a' + 26,
            b'0'..=b'9' => ch - b'0' + 52,
            b'+' => 62,
            b'/' => 63,
            b'=' | b' ' | b'\n' | b'\r' => continue,
            _ => return None,
        };
        acc = (acc << 6 | v as u32) & 0xFFFFFF;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push((acc >> bits) as u8);
        }
    }
    Some(out)
}

/// A scan's packed data, unpacked: base64, then zlib, up to `cap` bytes.
fn unpack(s: &str, cap: usize) -> Result<Vec<u8>, String> {
    let z = base64_lenient(s).ok_or_else(|| "a cloud's data isn't base64".to_string())?;
    crate::inflate::zlib_decode(&z, cap).map_err(|e| match e {
        crate::inflate::InflateError::Corrupt => "a cloud's data isn't zlib: corrupt deflate stream".to_string(),
        crate::inflate::InflateError::Truncated => "a cloud's data isn't zlib: incomplete deflate stream".to_string(),
        crate::inflate::InflateError::TooBig => format!("a cloud's data holds more than {} bytes", cap),
    })
}

/// Every check the making of a scan makes; how many points it holds.
fn check_cloud(cf: &CloudFile) -> Result<u64, String> {
    let pts = unpack(&cf.points, POINTS_CAP)?;
    if pts.len() % 12 != 0 {
        return Err("a cloud's points are cut short".into());
    }
    let cols = match &cf.colours {
        Some(c) => Some(unpack(c, COLOURS_CAP)?),
        None => None,
    };
    let n = (pts.len() / 12) as u64;
    if n == 0 || n > MAX_CLOUD_POINTS {
        return Err(format!("a cloud holds 1 to {} points, not {}", MAX_CLOUD_POINTS, n));
    }
    if cf.read < n {
        return Err(format!("a cloud read from {} points can't keep {}", cf.read, n));
    }
    if cf.origin.iter().any(|v| !(v.abs() <= MAX_FAR)) {
        return Err(format!("a cloud's origin {:?} isn't one", cf.origin));
    }
    if let Some(c) = &cols {
        if c.len() as u64 / 3 != n {
            return Err("a cloud has a colour for each point or none".into());
        }
    }
    if cf.stations.len() > 1 && cf.stations.iter().map(|s| s.points).sum::<u64>() != n {
        return Err("a cloud's stations hold all its points between them".into());
    }
    for c in pts.chunks_exact(4) {
        let v = f32::from_le_bytes([c[0], c[1], c[2], c[3]]);
        if !((v as f64).abs() <= MAX_SPAN) {
            return Err(format!("a cloud's point lies {} mm from its middle, past {}", v, MAX_SPAN as u64));
        }
    }
    Ok(n)
}

/// The entry as the original writes it back.
fn entry_of(cf: &CloudFile) -> Value {
    let mut m = Map::new();
    m.insert("source", Value::s(&cf.source));
    if !cf.stations.is_empty() {
        m.insert(
            "stations",
            Value::Arr(cf.stations.iter().map(|s| jobj! {"source" => s.source.as_str(), "points" => s.points}).collect()),
        );
    }
    m.insert("origin", Value::Arr(cf.origin.iter().map(|x| Value::f(*x)).collect()));
    m.insert("read", Value::u(cf.read));
    m.insert("points", Value::s(&cf.points));
    if let Some(c) = &cf.colours {
        m.insert("colours", Value::s(c));
    }
    Value::Obj(m)
}

/// Reads a project file's `clouds` back as the original does, writing them as it would.
pub fn load(pr: &mut Project) -> Result<(), String> {
    let v = match pr.doc.get("clouds") {
        None => return Ok(()),
        Some(v) => v.clone(),
    };
    let m = match &v {
        Value::Obj(m) => m,
        _ => return Err(invalid_type(&v, "a map of scans")),
    };
    let mut out = Map::new();
    let mut total: u64 = 0;
    for (i, (name, e)) in sorted(m).into_iter().enumerate() {
        if i >= MAX_CLOUDS {
            return Err(format!("the file holds more than {} scans, all a project may hold", MAX_CLOUDS));
        }
        let cf = cloud_file_of(e)?;
        let n = check_cloud(&cf)?;
        total += n;
        if total > MAX_CLOUD_POINTS {
            return Err(format!(
                "the file's scans hold more than {} points, all a project may hold",
                MAX_CLOUD_POINTS
            ));
        }
        out.insert(name, entry_of(&cf));
    }
    // where the original's file puts its scans, wherever this file had them
    pr.remove_top("clouds");
    if !out.is_empty() {
        pr.insert_top("clouds", Value::Obj(out));
    }
    Ok(())
}

/// A GUID as a file writes it, `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` (in braces or not, in any
/// case), as the model keeps it.
fn parse_guid(s: &str) -> Option<String> {
    let t = s.strip_prefix('{').and_then(|t| t.strip_suffix('}')).unwrap_or(s);
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

/// What an element points at: another's GUID, or its id.
enum Ref {
    Guid(String),
    Id(u64),
}

fn ref_of(v: &Value) -> Result<Ref, String> {
    match v {
        Value::Str(s) => match parse_guid(s) {
            Some(g) => Ok(Ref::Guid(g)),
            None => match s.parse::<u64>() {
                Ok(n) => Ok(Ref::Id(n)),
                Err(_) => Err(format!("`{}` is not a GUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx) or an id", s)),
            },
        },
        Value::Num(Num::U(n)) => Ok(Ref::Id(*n)),
        Value::Num(Num::I(n)) => Err(format!("{} is not an element id", n)),
        Value::Num(Num::F(f)) => {
            if *f >= 0.0 && f.fract() == 0.0 && *f < 18446744073709551616.0 {
                Ok(Ref::Id(*f as u64))
            } else {
                Err(format!("{} is not an element id", f))
            }
        }
        _ => Err(invalid_type(v, "an element's GUID, or its id")),
    }
}

/// A file's `pointcloud` elements read back as the original reads them: their fields as serde
/// takes them (in the order a JSON map visits them), a scan named rather than pointed at by its
/// GUID, written back as it writes them.
pub fn load_elements(pr: &mut Project) -> Result<(), String> {
    let ids: Vec<u64> = pr.ids_of("pointcloud");
    for id in ids {
        let e = pr.elements.get(&id).cloned().unwrap_or(Value::Null);
        let m = match &e {
            Value::Obj(m) => m,
            _ => continue,
        };
        let el = |msg: String| format!("element {}: {}", id, msg);
        // an element's own GUID is read first, what its kind holds after (serde's flattening)
        let guid = match m.get("guid") {
            Some(x) => Some(ref_of(x).map_err(el)?),
            None => None,
        };
        let (mut cloud, mut level, mut at, mut offset, mut angle) = (None, None, None, None, None);
        for (k, x) in sorted(m) {
            match k.as_str() {
                "cloud" => cloud = Some(as_string(x).map_err(el)?),
                "level" => {
                    level = Some(match ref_of(x).map_err(el)? {
                        Ref::Guid(g) => Value::Str(g),
                        Ref::Id(n) => Value::u(n),
                    })
                }
                "at" => {
                    let a = match x {
                        Value::Arr(a) => a,
                        _ => return Err(el(invalid_type(x, "tuple struct P2"))),
                    };
                    let mut p = [0.0; 2];
                    for (i, v) in a.iter().enumerate() {
                        if i >= 2 {
                            break;
                        }
                        p[i] = as_f64(v).map_err(el)?;
                    }
                    if a.len() < 2 {
                        return Err(el(format!("invalid length {}, expected tuple struct P2 with 2 elements", a.len())));
                    }
                    if a.len() > 2 {
                        return Err(el(format!("invalid length {}, expected 2 elements in sequence", a.len())));
                    }
                    at = Some(p);
                }
                "offset" => offset = Some(as_f64(x).map_err(el)?),
                "angle" => angle = Some(as_f64(x).map_err(el)?),
                _ => {}
            }
        }
        let missing = |f: &str| el(format!("missing field `{}`", f));
        let cloud = cloud.ok_or_else(|| missing("cloud"))?;
        let level = level.ok_or_else(|| missing("level"))?;
        let at = at.ok_or_else(|| missing("at"))?;
        let guid = match guid {
            Some(Ref::Guid(g)) => g,
            Some(Ref::Id(n)) => return Err(el(format!("{} is an id, not a GUID", n))),
            None => crate::rand::guid(),
        };
        // a scan may be named: it's pointed at by its library entry's GUID
        let cloud = if pr.lib_find_guid(&cloud).is_some() {
            cloud
        } else {
            pr.lib_guid("cloud", &cloud).unwrap_or(cloud)
        };
        let out = jobj! {
            "guid" => guid,
            "category" => "pointcloud",
            "cloud" => cloud,
            "level" => level,
            "at" => Value::Arr(vec![Value::f(at[0]), Value::f(at[1])]),
            "offset" => Value::f(offset.unwrap_or(0.0)),
            "angle" => Value::f(angle.unwrap_or(0.0)),
        };
        pr.elements.insert(id, out);
    }
    Ok(())
}

/// The fields of a file's `clouds` the original doesn't know, as JSON pointers.
pub fn left_out(doc: &Value) -> Vec<String> {
    let mut out = Vec::new();
    let m = match doc.get("clouds") {
        Some(Value::Obj(m)) => m,
        _ => return out,
    };
    for (name, e) in sorted(m) {
        if let Value::Obj(em) = e {
            for (k, x) in sorted(em) {
                match k.as_str() {
                    "source" | "origin" | "read" | "points" | "colours" => {}
                    "stations" => {
                        if let Value::Arr(a) = x {
                            for (i, s) in a.iter().enumerate() {
                                if let Value::Obj(sm) = s {
                                    for (sk, _) in sorted(sm) {
                                        if sk != "source" && sk != "points" {
                                            out.push(format!("/clouds/{}/stations/{}/{}", name, i, sk));
                                        }
                                    }
                                }
                            }
                        }
                    }
                    _ => out.push(format!("/clouds/{}/{}", name, k)),
                }
            }
        }
    }
    out
}

/// The model rules for point clouds: no more scans or points than a project holds, and what an
/// element places is a scan the project holds.
pub fn check(pr: &Project) -> Result<(), String> {
    if let Some(m) = super::clouds(pr) {
        if m.len() > MAX_CLOUDS {
            return Err(format!("the project has {} scans; it holds up to {}", m.len(), MAX_CLOUDS));
        }
        let total: u64 = m.iter().map(|(_, e)| super::info_of(e).count).sum();
        if total > MAX_CLOUD_POINTS {
            return Err(format!("the project's scans hold {} points; it holds up to {}", total, MAX_CLOUD_POINTS));
        }
    }
    for (id, e) in &pr.elements {
        if e.get("category").and_then(|c| c.as_str()) != Some("pointcloud") {
            continue;
        }
        let g = e.get("cloud").and_then(|c| c.as_str()).unwrap_or("");
        let name = match pr.lib_find_guid(g).and_then(|lid| pr.library.get(&lid)) {
            Some(l) if l.get("kind").and_then(|k| k.as_str()) == Some("cloud") => {
                l.get("name").and_then(|n| n.as_str()).unwrap_or("").to_string()
            }
            _ => return Err(format!("pointcloud {}: the project holds no scan named `{}`", id, g)),
        };
        if !super::clouds(pr).map(|m| m.contains(&name)).unwrap_or(false) {
            return Err(format!("pointcloud {}: the project holds no scan named `{}`", id, name));
        }
        let lv = e.get("level").cloned().unwrap_or(Value::Null);
        let by_id = crate::commands::params::id_of(&lv).filter(|n| pr.elements.contains_key(n));
        if by_id.is_none() {
            let lg = match &lv {
                Value::Str(s) => s.clone(),
                other => other.to_compact(),
            };
            let is_level = pr.find_guid(&lg).map(|lid| pr.category(lid) == Some("level")).unwrap_or(false);
            if !is_level {
                return Err(format!("pointcloud {}: level {} doesn't exist", id, lg));
            }
        }
        let num = |k: &str| e.get(k).and_then(|v| v.as_f64()).unwrap_or(0.0);
        let at = e.get("at").and_then(|v| v.as_arr()).cloned().unwrap_or_default();
        let ax = at.first().and_then(|v| v.as_f64()).unwrap_or(0.0);
        let ay = at.get(1).and_then(|v| v.as_f64()).unwrap_or(0.0);
        for (what, v) in [("at x", ax), ("at y", ay), ("offset", num("offset")), ("angle", num("angle"))] {
            if !(v.abs() <= crate::commands::params::MAX_MM) {
                return Err(format!("pointcloud {} {}: {} is not a usable number", id, what, v));
            }
        }
        if let Some(n) = by_id {
            return Err(format!("pointcloud {} points at element {} by its id, not its GUID", id, n));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base64_as_the_original_reads_it() {
        assert_eq!(base64_lenient("aGVsbG8=").unwrap(), b"hello");
        assert_eq!(base64_lenient("aGVsbG8").unwrap(), b"hello");
        assert_eq!(base64_lenient(" aGVs\nbG8= ").unwrap(), b"hello");
        assert_eq!(base64_lenient("aG=VsbG8").unwrap(), b"hello");
        assert!(base64_lenient("aGVsbG8-").is_none());
        assert!(base64_lenient("\taGVsbG8").is_none());
        assert_eq!(base64_lenient("a").unwrap(), b"");
    }
}
