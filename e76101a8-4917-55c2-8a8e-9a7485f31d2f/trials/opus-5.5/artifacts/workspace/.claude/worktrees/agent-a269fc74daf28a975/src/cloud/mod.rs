//! Point clouds: PTS, XYZ, PLY, LAS and E57 scans, and the `point_cloud` command.
//!
//! A project holds each scan once, by name, in its file's `clouds` (a library entry of kind
//! `cloud` gives it an id and a GUID): the file it came from (and its stations'), where its
//! middle was there, how many points the file held, and the points kept, as little-endian
//! `f32` about that middle, and their colours, each deflated and in base64. A `pointcloud`
//! element places a scan: its `cloud` (the library entry's GUID), its `level`, its middle at
//! `at` and `offset` over the level, turned `angle` degrees.

pub mod e57;
pub mod file;
pub mod las;
pub mod ply;
pub mod read;
pub mod text;
pub mod xml;

use crate::commands::params::*;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;
use read::{Format, Options, Scan, MAX_CLOUDS, MAX_CLOUD_POINTS, MAX_STATIONS};

const CMD: &str = "point_cloud";

/// Runs the commands this module owns; None for the others.
pub fn dispatch(s: &mut Session, cid: &str, p: &Value) -> Option<Result<Value, String>> {
    match cid {
        "point_cloud" => Some(cmd_point_cloud(s, p)),
        _ => None,
    }
}

fn err<T>(msg: String) -> Result<T, String> {
    Err(format!("{}: {}", CMD, msg))
}

/// A file's name, as a scan keeps where it came from.
fn file_name(path: &str) -> String {
    std::path::Path::new(path).file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default()
}

fn file_stem(path: &str) -> String {
    std::path::Path::new(path).file_stem().map(|n| n.to_string_lossy().to_string()).unwrap_or_default()
}

/// The `path` parameter: one file or a list of a scan's stations.
fn paths_param(p: &Value) -> Result<Option<Vec<String>>, String> {
    match p.get("path") {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Str(s)) => Ok(Some(vec![s.clone()])),
        Some(Value::Arr(a)) => {
            if a.is_empty() {
                return err("`path` is a scan file, or a list of the files of one scan's stations, not an empty list".into());
            }
            if a.len() > MAX_STATIONS {
                return err(format!("a scan comes from up to {} files, not {}", MAX_STATIONS, a.len()));
            }
            let mut out = Vec::new();
            for v in a {
                match v {
                    Value::Str(s) => out.push(s.clone()),
                    _ => return err(format!("`path` lists files by their paths, not {}", v.to_compact())),
                }
            }
            Ok(Some(out))
        }
        Some(v) => err(format!(
            "`path` is a scan file, or a list of the files of one scan's stations, not {}",
            v.to_compact()
        )),
    }
}

/// mm in each of a file's units.
fn units_scale(u: &str) -> Option<f64> {
    Some(match u.trim().to_lowercase().as_str() {
        "mm" => 1.0,
        "cm" => 10.0,
        "m" => 1000.0,
        "in" => 25.4,
        "ft" => 304.8,
        _ => return None,
    })
}

#[derive(PartialEq)]
enum Origin {
    Centre,
    File,
}

/// The `point_cloud` command.
pub fn cmd_point_cloud(s: &mut Session, p: &Value) -> Result<Value, String> {
    let level = crate::model::level_param(&s.project, CMD, p, "level")?;
    let paths = paths_param(p)?;
    let cloud = opt_text(p, CMD, "cloud")?;
    match (&paths, &cloud) {
        (Some(_), Some(_)) => {
            return err("give `path`, a scan file to bring in, or `cloud`, a scan the project holds; not both".into())
        }
        (None, None) => {
            return err("give `path`, a scan file (PTS, XYZ, PLY, LAS or E57) to bring in, or `cloud`, the name of a scan the project holds".into())
        }
        _ => {}
    }
    if let Some(name) = cloud {
        return place_held(s, p, level, &name);
    }
    let paths = paths.unwrap();
    let mut formats = Vec::new();
    for path in &paths {
        match Format::from_path(path) {
            Ok(f) => formats.push(f),
            Err(e) => return err(format!("{}: {}", path, e)),
        }
    }
    let name = match opt_text(p, CMD, "name")? {
        Some(n) => n,
        None => file_stem(&paths[0]),
    };
    if name.trim().is_empty() {
        return err("a scan needs a `name`".into());
    }
    if clouds(&s.project).map(|m| m.contains(&name)).unwrap_or(false) {
        return err(format!(
            "the project already holds a scan named `{}`: place it again with `cloud`, or bring this file in under another `name`",
            name
        ));
    }
    let held = clouds(&s.project).map(|m| m.len()).unwrap_or(0);
    if held >= MAX_CLOUDS {
        return err(format!("the project holds {} scans already; delete the point clouds of one first", held));
    }
    let scale = match opt_text(p, CMD, "units")? {
        None => 1000.0,
        Some(u) => match units_scale(&u) {
            Some(x) => x,
            None => return err(format!("`units` is one of mm, cm, m, in, ft, not {}", u)),
        },
    };
    let spacing = opt_num(p, CMD, "spacing")?.unwrap_or(0.0);
    let total = total_points(&s.project);
    if total >= MAX_CLOUD_POINTS {
        return err(format!(
            "the project's scans hold {} points, all it may; delete the point clouds of one first",
            total
        ));
    }
    let left = MAX_CLOUD_POINTS - total;
    let mut stations: Vec<(String, Scan)> = Vec::new();
    let share = left / paths.len() as u64;
    for (path, fmt) in paths.iter().zip(formats.iter()) {
        let opts = Options { scale, cap: if paths.len() == 1 { left } else { share }, spacing };
        match read::read(path, *fmt, &opts) {
            Ok(sc) => stations.push((file_name(path), sc)),
            Err(e) => return err(format!("{}: {}", path, e)),
        }
    }
    // a list of one is that file alone; more are a survey's stations, brought together
    let (scan, station_list) = if stations.len() == 1 {
        (stations.pop().unwrap().1, None)
    } else {
        let (sc, counts) = match merge(&stations, spacing) {
            Ok(x) => x,
            Err(e) => return err(e),
        };
        let list: Vec<(String, usize)> = stations.iter().zip(counts).map(|((n, _), c)| (n.clone(), c)).collect();
        (sc, Some(list))
    };
    let origin_mode = origin_param(p)?;
    let (at, offset, angle) = placement(&s.project, p, level, &origin_mode, &scan.origin, lowest(&scan.points))?;

    let entry = cloud_entry(&file_name(&paths[0]), station_list.as_deref(), &scan);
    let pr = &mut s.project;
    let (_, lguid) = pr.lib_add("cloud", &name);
    {
        let sec = pr.section_mut("clouds");
        sec.insert_sorted(&name, entry);
    }
    remember(&name_key(pr, &name), &scan);
    let id = place_element(pr, &lguid, level, at, offset, angle);
    Ok(reply(&name, id, &scan.origin, scan.points.len() as u64, scan.read))
}

fn reply(name: &str, id: u64, origin: &[f64; 3], points: u64, read: u64) -> Value {
    jobj! {
        "cloud" => name,
        "id" => id,
        "origin" => Value::Arr(origin.iter().map(|x| Value::f(*x)).collect()),
        "points" => points,
        "read" => read,
    }
}

fn origin_param(p: &Value) -> Result<Origin, String> {
    match opt_text(p, CMD, "origin")? {
        None => Ok(Origin::Centre),
        Some(o) => match o.as_str() {
            "centre" | "center" => Ok(Origin::Centre),
            "file" => Ok(Origin::File),
            _ => err(format!(
                "`origin` is centre (its middle on `at`, its foot on the level) or file (where its file puts it), not {}",
                o
            )),
        },
    }
}

/// Where the element goes: `at`, `offset` and `angle`, from the parameters or the scan.
fn placement(
    pr: &Project,
    p: &Value,
    level: u64,
    mode: &Origin,
    origin: &[f64; 3],
    min_z: f32,
) -> Result<([f64; 2], f64, f64), String> {
    if *mode == Origin::File && origin.iter().any(|v| !(v.abs() <= MAX_MM)) {
        return err(format!(
            "the scan's middle lies at {:?} mm in its file, past the {} mm a model reaches: place it by its `centre`",
            origin, MAX_MM as u64
        ));
    }
    let at = opt_point(p, CMD, "at")?;
    let offset = opt_num(p, CMD, "offset")?;
    let angle = opt_num(p, CMD, "angle")?;
    let elev = crate::model::elev(pr, level);
    let at = at.unwrap_or(match mode {
        Origin::File => [origin[0], origin[1]],
        Origin::Centre => [0.0, 0.0],
    });
    let offset = offset.unwrap_or(match mode {
        Origin::File => origin[2] - elev,
        Origin::Centre => -(min_z as f64),
    });
    Ok((at, offset, angle.unwrap_or(0.0)))
}

fn place_element(pr: &mut Project, cloud_guid: &str, level: u64, at: [f64; 2], offset: f64, angle: f64) -> u64 {
    let id = pr.alloc_id();
    let lg = pr.guid_of(level).unwrap_or_default();
    pr.elements.insert(
        id,
        jobj! {
            "guid" => crate::rand::guid(),
            "category" => "pointcloud",
            "cloud" => cloud_guid,
            "level" => lg,
            "at" => Value::Arr(vec![Value::f(at[0]), Value::f(at[1])]),
            "offset" => Value::f(offset),
            "angle" => Value::f(angle),
        },
    );
    id
}

/// Places a scan the project holds again.
fn place_held(s: &mut Session, p: &Value, level: u64, name: &str) -> Result<Value, String> {
    let entry = match clouds(&s.project).and_then(|m| m.get(name)) {
        Some(e) => e.clone(),
        None => {
            let names: Vec<String> = clouds(&s.project).map(|m| m.keys().cloned().collect()).unwrap_or_default();
            return err(format!(
                "the project holds no scan named `{}` (it holds: {})",
                name,
                if names.is_empty() { "none".to_string() } else { names.join(", ") }
            ));
        }
    };
    let info = info_of(&entry);
    let origin = entry_origin(&entry);
    let mode = origin_param(p)?;
    let (at, offset, angle) = placement(&s.project, p, level, &mode, &origin, info.min_z)?;
    let pr = &mut s.project;
    let lguid = match pr.lib_guid("cloud", name) {
        Some(g) => g,
        None => pr.lib_add("cloud", name).1,
    };
    let id = place_element(pr, &lguid, level, at, offset, angle);
    let read = entry.get("read").and_then(|v| v.as_u64()).unwrap_or(0);
    Ok(reply(name, id, &origin, info.count, read))
}

fn entry_origin(e: &Value) -> [f64; 3] {
    let mut o = [0.0; 3];
    if let Some(a) = e.get("origin").and_then(|v| v.as_arr()) {
        for k in 0..3 {
            o[k] = a.get(k).and_then(|v| v.as_f64()).unwrap_or(0.0);
        }
    }
    o
}

/// The project file's entry for a scan.
fn cloud_entry(source: &str, stations: Option<&[(String, usize)]>, scan: &Scan) -> Value {
    let mut m = Map::new();
    m.insert("source", Value::s(source));
    if let Some(st) = stations {
        m.insert(
            "stations",
            Value::Arr(st.iter().map(|(n, c)| jobj! {"source" => n.as_str(), "points" => *c as u64}).collect()),
        );
    }
    m.insert("origin", Value::Arr(scan.origin.iter().map(|x| Value::f(*x)).collect()));
    m.insert("read", Value::u(scan.read));
    let mut pts = Vec::with_capacity(scan.points.len() * 12);
    for q in &scan.points {
        for v in q {
            pts.extend_from_slice(&v.to_le_bytes());
        }
    }
    m.insert("points", Value::Str(crate::util::base64_encode(&crate::deflate::zlib_compress(&pts))));
    if let Some(c) = &scan.colours {
        let mut b = Vec::with_capacity(c.len() * 3);
        for x in c {
            b.extend_from_slice(x);
        }
        m.insert("colours", Value::Str(crate::util::base64_encode(&crate::deflate::zlib_compress(&b))));
    }
    Value::Obj(m)
}

/// Stations brought together about the middle of them all, one point kept in each cube of
/// `spacing` across them, a station with no colours grey among ones with.
fn merge(stations: &[(String, Scan)], spacing: f64) -> Result<(Scan, Vec<usize>), String> {
    let mut lo = [f64::INFINITY; 3];
    let mut hi = [f64::NEG_INFINITY; 3];
    for (_, sc) in stations {
        for q in &sc.points {
            for k in 0..3 {
                let v = sc.origin[k] + q[k] as f64;
                if v < lo[k] {
                    lo[k] = v;
                }
                if v > hi[k] {
                    hi[k] = v;
                }
            }
        }
    }
    for k in 0..3 {
        let w = hi[k] - lo[k];
        if w > read::MAX_SPAN {
            return Err(format!(
                "together they're {:.0} mm wide along {}; up to {:.0} mm",
                w,
                ["x", "y", "z"][k],
                read::MAX_SPAN
            ));
        }
    }
    let any_points = lo[0].is_finite();
    let origin = if any_points {
        [(lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0, (lo[2] + hi[2]) / 2.0]
    } else {
        [0.0; 3]
    };
    let with_colour = stations.iter().any(|(_, s)| s.colours.is_some());
    let mut seen: std::collections::HashSet<[i64; 3]> = std::collections::HashSet::new();
    let mut points = Vec::new();
    let mut colours = Vec::new();
    let mut counts = Vec::new();
    let mut read = 0;
    for (_, sc) in stations {
        read += sc.read;
        let mut n = 0;
        for (i, q) in sc.points.iter().enumerate() {
            let a = [sc.origin[0] + q[0] as f64, sc.origin[1] + q[1] as f64, sc.origin[2] + q[2] as f64];
            if spacing > 0.0 {
                let key = read::cube(&a, &lo, spacing);
                if !seen.insert(key) {
                    continue;
                }
            }
            points.push([(a[0] - origin[0]) as f32, (a[1] - origin[1]) as f32, (a[2] - origin[2]) as f32]);
            if with_colour {
                colours.push(match &sc.colours {
                    Some(c) => c[i],
                    None => [read::GREY; 3],
                });
            }
            n += 1;
        }
        counts.push(n);
    }
    Ok((Scan { origin, points, colours: if with_colour { Some(colours) } else { None }, read }, counts))
}

// ---------------------------------------------------------------- the project's scans

/// The project's scans, by name.
pub fn clouds(pr: &Project) -> Option<&Map> {
    pr.section("clouds")
}

/// What a scan's points come to: how many, and the lowest.
#[derive(Clone, Copy)]
pub struct Info {
    pub count: u64,
    pub min_z: f32,
}

fn cache() -> &'static std::sync::Mutex<std::collections::HashMap<u64, Info>> {
    static C: std::sync::OnceLock<std::sync::Mutex<std::collections::HashMap<u64, Info>>> = std::sync::OnceLock::new();
    C.get_or_init(|| std::sync::Mutex::new(std::collections::HashMap::new()))
}

/// A cheap key for a scan's packed points: its length and its ends (where zlib's checksum is).
fn key_of(points: &str) -> u64 {
    let b = points.as_bytes();
    let n = b.len();
    let mut k = Vec::with_capacity(200);
    k.extend_from_slice(&(n as u64).to_le_bytes());
    k.extend_from_slice(&b[..n.min(32)]);
    k.extend_from_slice(&b[n.saturating_sub(32)..]);
    // and a byte from each of 128 stretches along it
    if n > 0 {
        for i in 0..128 {
            k.push(b[i * n / 128]);
        }
    }
    crate::util::fnv1a64(&k)
}

fn name_key(pr: &Project, name: &str) -> String {
    clouds(pr)
        .and_then(|m| m.get(name))
        .and_then(|e| e.get("points"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .unwrap_or_default()
}

/// The lowest of a scan's points, about its middle (its foot); nought for none.
fn lowest(points: &[[f32; 3]]) -> f32 {
    if points.is_empty() {
        return 0.0;
    }
    points.iter().map(|q| q[2]).fold(f32::INFINITY, f32::min)
}

fn remember(points_b64: &str, scan: &Scan) {
    let min_z = lowest(&scan.points);
    cache().lock().unwrap().insert(key_of(points_b64), Info { count: scan.points.len() as u64, min_z });
}

/// A scan's points, unpacked.
pub fn unpack_points(e: &Value, cap: usize) -> Option<Vec<[f32; 3]>> {
    let s = e.get("points")?.as_str()?;
    let z = crate::util::base64_decode(s)?;
    let raw = crate::inflate::zlib_decode(&z, cap).ok()?;
    Some(raw.chunks_exact(12).map(|c| {
        [
            f32::from_le_bytes([c[0], c[1], c[2], c[3]]),
            f32::from_le_bytes([c[4], c[5], c[6], c[7]]),
            f32::from_le_bytes([c[8], c[9], c[10], c[11]]),
        ]
    }).collect())
}

/// How many points a scan holds, and its lowest.
pub fn info_of(e: &Value) -> Info {
    let s = e.get("points").and_then(|v| v.as_str()).unwrap_or("");
    let k = key_of(s);
    if let Some(i) = cache().lock().unwrap().get(&k) {
        return *i;
    }
    let pts = unpack_points(e, (MAX_CLOUD_POINTS as usize + 1) * 12).unwrap_or_default();
    let min_z = lowest(&pts);
    let i = Info { count: pts.len() as u64, min_z };
    cache().lock().unwrap().insert(k, i);
    i
}

/// The points the project's scans hold among them.
pub fn total_points(pr: &Project) -> u64 {
    clouds(pr).map(|m| m.iter().map(|(_, e)| info_of(e).count).sum()).unwrap_or(0)
}

/// After a command: a scan that nothing places any more goes, with its library entry.
pub fn drop_unplaced(pr: &mut Project) {
    let names: Vec<String> = match clouds(pr) {
        Some(m) => m.keys().cloned().collect(),
        None => return,
    };
    let placed: std::collections::HashSet<String> = pr
        .elements
        .values()
        .filter(|e| e.get("category").and_then(|c| c.as_str()) == Some("pointcloud"))
        .filter_map(|e| e.get("cloud").and_then(|c| c.as_str()).map(|s| s.to_string()))
        .collect();
    let mut gone = Vec::new();
    for n in names {
        let g = pr.lib_guid("cloud", &n);
        let used = g.as_ref().map(|g| placed.contains(g)).unwrap_or(false);
        if !used {
            let lid = pr.lib_find("cloud", &n);
            gone.push((n, lid));
        }
    }
    if gone.is_empty() {
        return;
    }
    for (n, lid) in gone {
        if let Some(Value::Obj(m)) = pr.doc.get_mut("clouds") {
            m.remove(&n);
        }
        if let Some(id) = lid {
            pr.library.remove(&id);
        }
    }
    if clouds(pr).map(|m| m.is_empty()).unwrap_or(false) {
        pr.remove_top("clouds");
    }
}

/// A point cloud as `elements` shows it: its scan by name, the scan's file (and stations) and
/// how many points it holds.
pub fn element_view(pr: &Project, x: &mut Value) {
    let g = x.get("cloud").and_then(|c| c.as_str()).unwrap_or("").to_string();
    let name = match pr.lib_name(&g) {
        Some(n) => n,
        None => return,
    };
    x.set("cloud", Value::Str(name.clone()));
    if let Some(e) = clouds(pr).and_then(|m| m.get(&name)) {
        x.set("points", Value::u(info_of(e).count));
        if let Some(src) = e.get("source") {
            x.set("source", src.clone());
        }
        if let Some(st) = e.get("stations") {
            x.set("stations", st.clone());
        }
    }
}

/// Why `mirror` leaves a point cloud as it is.
pub fn mirror_refusal(id: u64) -> String {
    format!("point cloud {} can't be mirrored: a scan is what was measured; move it or turn it", id)
}

/// The fields of a project file's scans and point clouds the original doesn't read (JSON
/// pointers, for what opening a file reports it left out).
pub fn left_out(doc: &Value) -> Vec<String> {
    let mut out = file::left_out(doc);
    if let Some(Value::Obj(els)) = doc.get("elements") {
        for (id, e) in els.iter() {
            if e.get("category").and_then(|c| c.as_str()) != Some("pointcloud") {
                continue;
            }
            if let Value::Obj(m) = e {
                let mut keys: Vec<&String> = m.keys().collect();
                keys.sort();
                for k in keys {
                    if !matches!(k.as_str(), "guid" | "category" | "cloud" | "level" | "at" | "offset" | "angle") {
                        out.push(format!("/elements/{}/{}", id, k));
                    }
                }
            }
        }
    }
    out
}

/// The model rules this module owns, checked after every command.
pub fn check(pr: &crate::project::Project) -> Result<(), String> {
    file::check(pr)
}

/// Reading a project file: its scans read back as the original reads them, and those nothing
/// places dropped.
pub fn load(pr: &mut Project) -> Result<(), String> {
    file::load(pr)?;
    file::load_elements(pr)?;
    drop_unplaced(pr);
    Ok(())
}
