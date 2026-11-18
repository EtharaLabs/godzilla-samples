//! Columns (structural ones by their Pset LoadBearing), isolated footings, and the runs: beams,
//! strip footings, pipes, ducts, conduits, cable trays, wires, cables and conductors; the
//! reinforcing bars in them; grids.

use super::import::Ctx;
use super::import_build::{num_name, r3, r3z, r6};
use super::import_geom::{self as geom, Param, Solid, Tf, V2, V3};
use super::import_types;
use crate::json::{Map, Value};

/// What this module keeps for later passes.
#[derive(Default)]
pub struct State {
    /// The elements that got a mark (their entity, their category and the mark), for the
    /// `Mark` parameter the params pass makes.
    pub marks: Vec<(u64, String, String)>,
}

fn pv(p: V2) -> Value {
    Value::Arr(vec![Value::f(r3z(p[0])), Value::f(r3z(p[1]))])
}

/// The material of an element (or of its type) as a library material's GUID.
fn element_material(ctx: &mut Ctx, id: u64) -> Option<String> {
    let pick = |ctx: &Ctx, x: u64| -> Option<u64> {
        let mid = *ctx.m.material_of.get(&x)?;
        let e = ctx.m.get(mid)?;
        match e.name.as_str() {
            "IFCMATERIAL" => Some(mid),
            "IFCMATERIALPROFILESETUSAGE" => {
                let set = ctx.m.get(e.p(0).r()?)?;
                let prof = ctx.m.get(*set.p(0).refs().first()?)?;
                prof.p(2).r()
            }
            "IFCMATERIALPROFILESET" => {
                let prof = ctx.m.get(*e.p(2).refs().first()?)?;
                prof.p(2).r()
            }
            "IFCMATERIALCONSTITUENTSET" => {
                let c = ctx.m.get(*e.p(2).refs().first()?)?;
                c.p(2).r()
            }
            "IFCMATERIALLIST" => e.p(0).refs().first().copied(),
            "IFCMATERIALLAYERSETUSAGE" => {
                let set = ctx.m.get(e.p(0).r()?)?;
                let l = ctx.m.get(*set.p(0).refs().first()?)?;
                l.p(0).r()
            }
            "IFCMATERIALLAYERSET" => {
                let l = ctx.m.get(*e.p(0).refs().first()?)?;
                l.p(0).r()
            }
            _ => None,
        }
    };
    let mat = pick(ctx, id).or_else(|| ctx.m.type_of.get(&id).copied().and_then(|t| pick(ctx, t)))?;
    import_types::existing_material(ctx, mat)
}

/// A section's name for a type the file doesn't name: `Imported 200 x 500`, `Imported Round 50`.
fn section_name(w: f64, d: f64, round: bool) -> String {
    if round {
        format!("Imported Round {}", num_name(w))
    } else {
        format!("Imported {} x {}", num_name(w), num_name(d))
    }
}

// ---------------------------------------------------------------- columns and footings

/// A footprint in plan: its points, and whether it is round (and its diameter).
struct Foot {
    pts: Vec<V2>,
    round: Option<(f64, V2)>,
}

fn footprint(solids: &[Solid]) -> Option<Foot> {
    if solids.len() == 1 {
        if let Some(x) = &solids[0].ext {
            let d = x.tf.dir(x.dir);
            if d[2].abs() > 1.0 - 1e-9 {
                let pts: Vec<V2> = x
                    .outer
                    .iter()
                    .map(|p| {
                        let q = x.tf.apply([p[0], p[1], 0.0]);
                        [q[0], q[1]]
                    })
                    .collect();
                let round = match &x.param {
                    Param::Circle { r, centre } | Param::CircleHollow { r, centre, .. } => {
                        let c = x.tf.apply([centre[0], centre[1], 0.0]);
                        Some((2.0 * r, [c[0], c[1]]))
                    }
                    _ => None,
                };
                return Some(Foot { pts, round });
            }
        }
    }
    let t = super::import_slabs::top(solids)?;
    Some(Foot { pts: t.outer, round: None })
}

pub fn columns(ctx: &mut Ctx) {
    // the columns, then the pad footings
    let mut ids: Vec<u64> = Vec::new();
    for c in ["IFCCOLUMN", "IFCCOLUMNSTANDARDCASE"] {
        ids.extend_from_slice(ctx.m.of(c));
    }
    ids.sort();
    let mut feet: Vec<u64> = ctx.m.of("IFCFOOTING").to_vec();
    feet.sort();
    for id in ids.into_iter().chain(feet) {
        if ctx.m.class(id) == "IFCFOOTING" && footing_kind(ctx, id) == "STRIP_FOOTING" {
            continue;
        }
        column(ctx, id);
    }
}

fn footing_kind(ctx: &Ctx, id: u64) -> String {
    let e = ctx.m.get(id).unwrap();
    let mut k = e.p(8).enm().unwrap_or("").to_string();
    if k.is_empty() || k == "NOTDEFINED" || k == "USERDEFINED" {
        if let Some(t) = ctx.m.type_of.get(&id).and_then(|t| ctx.m.get(*t)) {
            if let Some(x) = t.p(9).enm() {
                k = x.to_string();
            }
        }
    }
    k
}

fn column(ctx: &mut Ctx, id: u64) {
    let class = ctx.m.class(id).to_string();
    let solids = geom::body(&ctx.m, id);
    let f = match footprint(&solids) {
        Some(f) => f,
        None => {
            ctx.skip(id, "it has no body BIMCraft can read");
            return;
        }
    };
    let pts: Vec<V3> = solids.iter().flat_map(|s| s.points().copied().collect::<Vec<_>>()).collect();
    let (z0, z1) = pts.iter().fold((f64::INFINITY, f64::NEG_INFINITY), |(a, b), p| (a.min(p[2]), b.max(p[2])));
    let (at, angle, w, d, round) = match f.round {
        Some((dia, c)) => (c, 0.0, dia, dia, true),
        None => {
            // the first of the longest sides gives the width and its direction
            let p = super::import_slabs::simplify(&f.pts);
            let n = p.len();
            let mut best = 0;
            let mut bl = -1.0;
            for i in 0..n {
                let (a, b) = (p[i], p[(i + 1) % n]);
                let l = ((b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2)).sqrt();
                if l > bl + 1e-6 {
                    bl = l;
                    best = i;
                }
            }
            let (a, b) = (p[best], p[(best + 1) % n]);
            let u = [(b[0] - a[0]) / bl, (b[1] - a[1]) / bl];
            let v = [-u[1], u[0]];
            let (mut s0, mut s1, mut t0, mut t1) = (f64::INFINITY, f64::NEG_INFINITY, f64::INFINITY, f64::NEG_INFINITY);
            for q in &p {
                let s = q[0] * u[0] + q[1] * u[1];
                let t = q[0] * v[0] + q[1] * v[1];
                s0 = s0.min(s);
                s1 = s1.max(s);
                t0 = t0.min(t);
                t1 = t1.max(t);
            }
            let (sm, tm) = ((s0 + s1) / 2.0, (t0 + t1) / 2.0);
            let c = [u[0] * sm + v[0] * tm, u[1] * sm + v[1] * tm];
            let mut ang = u[1].atan2(u[0]).to_degrees();
            if ang < -1e-9 {
                ang += 360.0;
            }
            (c, ang, s1 - s0, t1 - t0, false)
        }
    };
    let (cat, tcat, pset) = if class == "IFCFOOTING" {
        ("footing", "footing", "Pset_FootingCommon")
    } else if super::import_slabs::load_bearing(ctx, id, "Pset_ColumnCommon") {
        ("structuralcolumn", "structural_column", "Pset_ColumnCommon")
    } else {
        ("column", "column", "Pset_ColumnCommon")
    };
    let _ = pset;
    let (w, d) = (super::import_build::r2(w), super::import_build::r2(d));
    let base_name = import_types::file_type_name(ctx, id).unwrap_or_else(|| section_name(w, d, round));
    let tv = crate::jobj! {"width" => w, "depth" => d, "round" => round};
    let tname = import_types::register(ctx, tcat, &base_name, tv);
    let tguid = ctx.type_guid(tcat, &tname);
    let level = ctx.level_of(id, z0);
    let lev = ctx.levels[level].elevation;
    let top_level = ctx.level_at_top(level, z1);
    let mk = import_types::mark_of(ctx, id, &base_name);
    let g = ctx.guid_for(id);
    let mut m = Map::new();
    m.insert("guid", Value::s(&g));
    m.insert("category", Value::s(cat));
    m.insert("type", Value::s(&tguid));
    m.insert("level", ctx.level_guid(level));
    m.insert("at", pv(at));
    m.insert("angle", Value::f(r6(angle)));
    m.insert("top_level", match top_level {
        Some(t) if cat != "footing" => ctx.level_guid(t),
        _ => Value::Null,
    });
    m.insert("height", Value::f(r3(z1 - z0)));
    m.insert("base_offset", Value::f(r3(z0 - lev)));
    ctx.add(id, Value::Obj(m));
    if let Some(mk) = mk {
        ctx.structure.marks.push((id, cat.to_string(), mk));
    }
}

// ---------------------------------------------------------------- runs

const RUN_CLASSES: &[&str] = &[
    "IFCBEAM",
    "IFCBEAMSTANDARDCASE",
    "IFCFOOTING",
    "IFCPIPESEGMENT",
    "IFCDUCTSEGMENT",
    "IFCCABLECARRIERSEGMENT",
    "IFCCABLESEGMENT",
];

fn predefined(ctx: &Ctx, id: u64) -> String {
    let e = ctx.m.get(id).unwrap();
    let mut k = e.p(8).enm().unwrap_or("").to_string();
    if k.is_empty() || k == "NOTDEFINED" || k == "USERDEFINED" {
        if let Some(t) = ctx.m.type_of.get(&id).and_then(|t| ctx.m.get(*t)) {
            if let Some(x) = t.p(9).enm() {
                k = x.to_string();
            }
        }
    }
    k
}

/// The run kind an element is: what BIMCraft wrote in its `BIMCraft_Run`, else its class's.
fn run_kind(ctx: &Ctx, id: u64) -> Option<String> {
    if let Some(c) = ctx.m.prop(id, "BIMCraft_Run", "Category").and_then(|p| p.str().map(|s| s.to_string())) {
        if super::import_build::is_run(&c) {
            return Some(c);
        }
    }
    let class = ctx.m.class(id);
    let pt = predefined(ctx, id);
    Some(
        match class {
            "IFCBEAM" | "IFCBEAMSTANDARDCASE" => "beam",
            "IFCFOOTING" => {
                if pt == "STRIP_FOOTING" {
                    "stripfooting"
                } else {
                    return None;
                }
            }
            "IFCPIPESEGMENT" => "pipe",
            "IFCDUCTSEGMENT" => "duct",
            "IFCCABLECARRIERSEGMENT" => {
                if pt == "CONDUITSEGMENT" {
                    "conduit"
                } else {
                    "cabletray"
                }
            }
            "IFCCABLESEGMENT" => {
                if pt == "CONDUCTORSEGMENT" {
                    "downconductor"
                } else {
                    "wire"
                }
            }
            _ => return None,
        }
        .to_string(),
    )
}

/// A run's axis and section: from an extrusion along anything but up, else the longest way the
/// body spreads. Returns the start and end of its centre line in space, the width (level,
/// across) and depth (square to that), and whether it is round.
fn run_axis(solids: &[Solid]) -> Option<(V3, V3, f64, f64, bool)> {
    // one profile extruded along anything but up runs that way; one extruded up does if the way
    // it spreads most is up too (a riser)
    let main = main_axis(solids);
    if solids.len() == 1 {
        if let Some(x) = &solids[0].ext {
            let d = geom::unit(x.tf.dir(x.dir));
            let up = d[2].abs() > 1.0 - 1e-9;
            if up && !main.map(|m| m.0[2].abs() > 1.0 - 1e-9).unwrap_or(false) {
                return main.map(|m| m.1);
            }
            let (c, w, h, round) = match &x.param {
                Param::Rect { x: px, y: py, centre, .. } => (*centre, *px, *py, false),
                Param::Circle { r, centre } | Param::CircleHollow { r, centre, .. } => (*centre, 2.0 * r, 2.0 * r, true),
                Param::None => {
                    let (mut x0, mut x1, mut y0, mut y1) = (f64::INFINITY, f64::NEG_INFINITY, f64::INFINITY, f64::NEG_INFINITY);
                    for p in &x.outer {
                        x0 = x0.min(p[0]);
                        x1 = x1.max(p[0]);
                        y0 = y0.min(p[1]);
                        y1 = y1.max(p[1]);
                    }
                    ([(x0 + x1) / 2.0, (y0 + y1) / 2.0], x1 - x0, y1 - y0, false)
                }
            };
            let start = x.tf.apply([c[0], c[1], 0.0]);
            let end = geom::add(start, geom::mul(d, x.depth));
            // which of the profile's sides lies level: the width; the other, the depth
            let ax = x.tf.dir([1.0, 0.0, 0.0]);
            let ay = x.tf.dir([0.0, 1.0, 0.0]);
            let (w, h) = if ax[2].abs() <= ay[2].abs() { (w, h) } else { (h, w) };
            return Some((start, end, w, h, round));
        }
    }
    main.map(|m| m.1)
}

/// The longest way a body spreads (its points' main axis, by power iteration from a fixed
/// start), and the run along it: from its west (or south, or bottom) end, with the extents
/// across and square to it.
fn main_axis(solids: &[Solid]) -> Option<(V3, (V3, V3, f64, f64, bool))> {
    let pts: Vec<V3> = solids.iter().flat_map(|s| s.points().copied().collect::<Vec<_>>()).collect();
    if pts.is_empty() {
        return None;
    }
    let n = pts.len() as f64;
    let mut c = [0.0; 3];
    for p in &pts {
        c = geom::add(c, *p);
    }
    c = geom::mul(c, 1.0 / n);
    let mut cov = [[0.0; 3]; 3];
    for p in &pts {
        let d = geom::sub(*p, c);
        for i in 0..3 {
            for j in 0..3 {
                cov[i][j] += d[i] * d[j];
            }
        }
    }
    let mut v = [1.0, 0.7, 0.3];
    for _ in 0..64 {
        let w = [
            cov[0][0] * v[0] + cov[0][1] * v[1] + cov[0][2] * v[2],
            cov[1][0] * v[0] + cov[1][1] * v[1] + cov[1][2] * v[2],
            cov[2][0] * v[0] + cov[2][1] * v[1] + cov[2][2] * v[2],
        ];
        let l = geom::norm(w);
        if l == 0.0 {
            break;
        }
        v = geom::mul(w, 1.0 / l);
    }
    let mut u = geom::unit(v);
    // run along it from its west (or south, or bottom) end
    if u[0] < -1e-9 || (u[0].abs() <= 1e-9 && (u[1] < -1e-9 || (u[1].abs() <= 1e-9 && u[2] < 0.0))) {
        u = geom::mul(u, -1.0);
    }
    let across = if u[2].abs() > 1.0 - 1e-9 { [1.0, 0.0, 0.0] } else { geom::unit([-u[1], u[0], 0.0]) };
    let up = geom::cross(u, across);
    let (mut s0, mut s1, mut a0, mut a1, mut b0, mut b1) = (f64::INFINITY, f64::NEG_INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::INFINITY, f64::NEG_INFINITY);
    for p in &pts {
        let d = geom::sub(*p, c);
        let (s, a, b) = (geom::dot(d, u), geom::dot(d, across), geom::dot(d, up));
        s0 = s0.min(s);
        s1 = s1.max(s);
        a0 = a0.min(a);
        a1 = a1.max(a);
        b0 = b0.min(b);
        b1 = b1.max(b);
    }
    let mid = geom::add(c, geom::add(geom::mul(across, (a0 + a1) / 2.0), geom::mul(up, (b0 + b1) / 2.0)));
    let start = geom::add(mid, geom::mul(u, s0));
    let end = geom::add(mid, geom::mul(u, s1));
    Some((u, (start, end, a1 - a0, b1 - b0, false)))
}

pub fn runs(ctx: &mut Ctx) {
    let mut ids: Vec<u64> = Vec::new();
    for c in RUN_CLASSES {
        ids.extend_from_slice(ctx.m.of(c));
    }
    ids.sort();
    for id in ids {
        if let Some(k) = run_kind(ctx, id) {
            run(ctx, id, &k);
        }
    }
}

fn run(ctx: &mut Ctx, id: u64, kind: &str) {
    let solids = geom::body(&ctx.m, id);
    let (mut a, mut b, w, d, round) = match run_axis(&solids) {
        Some(x) => x,
        None => {
            ctx.skip(id, "it has no body BIMCraft can read, or it stands (a column) or lies flat");
            return;
        }
    };
    // a beam or a wall footing runs along: one that stands is a column
    if matches!(kind, "beam" | "stripfooting") && (a[0] - b[0]).hypot(a[1] - b[1]) < 1e-6 {
        ctx.skip(id, &format!("its ends are one over the other; a {} runs along, and what stands is a column", kind));
        return;
    }
    // a run goes east (or north, or up)
    let dv = geom::sub(b, a);
    if dv[0] < -1e-6 || (dv[0].abs() <= 1e-6 && (dv[1] < -1e-6 || (dv[1].abs() <= 1e-6 && dv[2] < 0.0))) {
        std::mem::swap(&mut a, &mut b);
    }
    let justify = ctx
        .m
        .prop(id, "BIMCraft_Run", "Justification")
        .and_then(|p| p.str().map(|s| s.to_string()))
        .filter(|s| s == "top" || s == "centre" || s == "bottom")
        .unwrap_or_else(|| "centre".to_string());
    // the justification line's height at each end: over or under the centre line by half the
    // depth, measured square to the run
    let dir = geom::unit(geom::sub(b, a));
    let h = (dir[0] * dir[0] + dir[1] * dir[1]).sqrt();
    let upright = h < 1e-9;
    let half = if upright { 0.0 } else { d / 2.0 / h };
    let lift = match justify.as_str() {
        "top" => half,
        "bottom" => -half,
        _ => 0.0,
    };
    let level = ctx.level_of(id, a[2].min(b[2]));
    let lev = ctx.levels[level].elevation;
    let (w, d) = (super::import_build::r2(w), super::import_build::r2(d));
    let base_name = import_types::file_type_name(ctx, id).unwrap_or_else(|| section_name(w, d, round));
    let mut tv = crate::jobj! {"width" => w, "depth" => d, "round" => round};
    if let Some(mg) = element_material(ctx, id) {
        tv.set("material", Value::s(&mg));
    }
    let tname = import_types::register(ctx, kind, &base_name, tv);
    let tguid = ctx.type_guid(kind, &tname);
    let off = r3(a[2] + lift - lev);
    let end_off = r3(b[2] + lift - lev);
    let structural = matches!(kind, "beam" | "stripfooting");
    let mk = if structural { import_types::mark_of(ctx, id, &base_name) } else { None };
    let system = ctx.m.groups.get(&id).and_then(|gs| {
        gs.iter().find_map(|g| {
            let c = ctx.m.class(*g);
            if c == "IFCSYSTEM" || c == "IFCDISTRIBUTIONSYSTEM" || c == "IFCDISTRIBUTIONCIRCUIT" || c == "IFCBUILDINGSYSTEM" {
                ctx.m.name(*g).map(|n| n.trim().to_string()).filter(|n| !n.is_empty())
            } else {
                None
            }
        })
    });
    let g = ctx.guid_for(id);
    let mut m = Map::new();
    m.insert("guid", Value::s(&g));
    m.insert("category", Value::s(kind));
    m.insert("type", Value::s(&tguid));
    m.insert("level", ctx.level_guid(level));
    m.insert("start", pv([a[0], a[1]]));
    m.insert("end", pv([b[0], b[1]]));
    m.insert("offset", Value::f(off));
    if end_off != off {
        m.insert("end_offset", Value::f(end_off));
    }
    m.insert("justify", Value::s(&justify));
    if let Some(s) = system {
        m.insert("system", Value::s(&s));
    }
    ctx.add(id, Value::Obj(m));
    if let Some(mk) = mk {
        ctx.structure.marks.push((id, kind.to_string(), mk));
    }
}

// ---------------------------------------------------------------- rebar

pub fn rebar(ctx: &mut Ctx) {
    let ids: Vec<u64> = ctx.m.of("IFCREINFORCINGBAR").to_vec();
    for id in ids {
        bar(ctx, id);
    }
}

fn bar(ctx: &mut Ctx, id: u64) {
    let e = ctx.m.get(id).unwrap().clone();
    let tf = geom::product_tf(&ctx.m, id);
    let mut path: Vec<V3> = Vec::new();
    let mut radius: Option<f64> = None;
    for rep in geom::rep_items(&ctx.m, &e, "Body") {
        let re = match ctx.m.get(rep) {
            Some(r) => r.clone(),
            None => continue,
        };
        for it in re.p(3).refs() {
            let ie = match ctx.m.get(it) {
                Some(x) => x.clone(),
                None => continue,
            };
            if ie.name != "IFCSWEPTDISKSOLID" && ie.name != "IFCSWEPTDISKSOLIDPOLYGONAL" {
                continue;
            }
            if radius.is_none() {
                radius = ie.p(1).num().map(|r| r * ctx.m.scale);
            }
            let pts = match ie.p(0).r().and_then(|c| geom::curve(&ctx.m, c)) {
                Some(p) => p,
                None => continue,
            };
            for p in pts {
                let q = tf.apply(p);
                if let Some(l) = path.last() {
                    if geom::norm(geom::sub(*l, q)) < 1e-6 {
                        continue;
                    }
                }
                path.push(q);
            }
        }
    }
    if path.len() < 2 {
        ctx.skip(id, "its body is no disk swept along a line");
        return;
    }
    let z = path.iter().map(|p| p[2]).fold(f64::INFINITY, f64::min);
    let level = ctx.level_of(id, z);
    let lev = ctx.levels[level].elevation;
    let s = ctx.m.scale;
    let diameter = e.p(9).num().map(|x| x * s).or(radius.map(|r| 2.0 * r)).unwrap_or(0.0);
    let grade = e.p(8).str().map(|x| x.to_string()).unwrap_or_default();
    let host = ctx.m.parent.get(&id).and_then(|p| ctx.made.get(p)).map(|m| m.guid.clone());
    let g = ctx.guid_for(id);
    let mut m = Map::new();
    m.insert("guid", Value::s(&g));
    m.insert("category", Value::s("rebar"));
    m.insert("level", ctx.level_guid(level));
    if let Some(h) = host {
        m.insert("host", Value::s(&h));
    }
    m.insert(
        "path",
        Value::Arr(path.iter().map(|p| Value::Arr(vec![Value::f(r3z(p[0])), Value::f(r3z(p[1])), Value::f(r3z(p[2] - lev))])).collect()),
    );
    m.insert("diameter", Value::f(r3(diameter)));
    m.insert("grade", Value::s(&grade));
    let pid = ctx.add(id, Value::Obj(m));
    ctx.fixed.insert((pid, "path"));
    let _ = Tf::ID;
}

// ---------------------------------------------------------------- grids

/// IfcGrid: a grid for each of its axes, named for its tag.
pub fn grids(ctx: &mut Ctx) {
    let ids: Vec<u64> = ctx.m.of("IFCGRID").to_vec();
    for id in ids {
        ctx.handled.insert(id);
        let e = ctx.m.get(id).unwrap().clone();
        let tf = geom::product_tf(&ctx.m, id);
        // (…, UAxes 7, VAxes 8, WAxes 9)
        let mut axes: Vec<u64> = Vec::new();
        for i in [7usize, 8, 9] {
            axes.extend(e.p(i).refs());
        }
        for ax in axes {
            let ae = match ctx.m.get(ax) {
                Some(a) => a.clone(),
                None => continue,
            };
            // IfcGridAxis(AxisTag, AxisCurve, SameSense)
            let name = ae.p(0).str().map(|s| s.to_string()).unwrap_or_default();
            let pts = match ae.p(1).r().and_then(|c| geom::curve(&ctx.m, c)) {
                Some(p) if p.len() >= 2 => p,
                _ => continue,
            };
            let mut a = tf.apply(pts[0]);
            let mut b = tf.apply(pts[pts.len() - 1]);
            if ae.p(2).boolean() == Some(false) {
                std::mem::swap(&mut a, &mut b);
            }
            let g = crate::rand::guid();
            let v = crate::jobj! {
                "guid" => g.as_str(),
                "category" => "grid",
                "name" => name.as_str(),
                "start" => pv([a[0], a[1]]),
                "end" => pv([b[0], b[1]]),
            };
            let pid = ctx.pr.alloc_id();
            ctx.pr.elements.insert(pid, v);
        }
    }
}
