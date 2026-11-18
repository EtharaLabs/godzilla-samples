// The wires of every schematic scope, routed after layout between fixed
// ports: a pin's stub tip (left along the pin's facing), a part's station, a
// label's connection point (a run's far end: the wire travels its length).
// Routes run on the scope's lattice lines clear of every body's lattice
// cells; a wire of a net already drawn joins it where it can, and the points
// where three ways of one net meet get a junction dot.

use super::net::{origin_in, Dir, Kind, Term};
use crate::compile::Ctx;
use std::cell::RefCell;

#[derive(Clone, Debug)]
pub struct Routed {
    pub li: usize,
    pub pts: Vec<(f64, f64)>,
    // the net name along the trace: (text, x, y, rotation)
    pub labels: Vec<(String, f64, f64, f64)>,
    pub scope: usize,
}

#[derive(Default)]
pub struct Wiring {
    pub wires: Vec<Routed>,
    // the wires no route can be drawn for: (link, its ends' boxes)
    pub strays: Vec<(usize, crate::route::Rect, crate::route::Rect)>,
    pub junctions: Vec<(f64, f64)>,
    // a scope a wire is drawn in is not the root: wires wear the class
    pub nested: bool,
}

thread_local! {
    pub static WIRING: RefCell<Wiring> = RefCell::new(Wiring::default());
    // the box of the nested sheet being routed (none for the root)
    static BOUNDS: RefCell<Option<super::router::Rect>> = RefCell::new(None);
}

pub fn reset() {
    WIRING.with(|w| *w.borrow_mut() = Wiring::default());
}

pub const CLEAR: f64 = 10.0;
// a wire's width
pub const WIRE: f64 = 1.5;

fn abs_point(ctx: &Ctx, t: &Term) -> (f64, f64) {
    let o = origin_in(ctx, t.dev, 0);
    (o.0 + t.off.0, o.1 + t.off.1)
}

fn same(a: f64, b: f64) -> bool {
    (a - b).abs() < 1e-9
}

// a direct route: straight, or one corner
fn direct(a: (f64, f64), da: Dir, b: (f64, f64), db: Dir) -> Option<Vec<(f64, f64)>> {
    let ahead = |p: (f64, f64), d: Dir, q: (f64, f64)| -> bool {
        match d {
            Dir::R => q.0 > p.0 - 1e-9,
            Dir::L => q.0 < p.0 + 1e-9,
            Dir::D => q.1 > p.1 - 1e-9,
            Dir::U => q.1 < p.1 + 1e-9,
        }
    };
    if da == db.opposite() {
        let aligned = if da.horizontal() { same(a.1, b.1) } else { same(a.0, b.0) };
        if aligned && ahead(a, da, b) {
            return Some(vec![a, b]);
        }
        if ahead(a, da, b) {
            // a staircase: the jog halfway
            if da.horizontal() {
                let m = (a.0 + b.0) / 2.0;
                return Some(vec![a, (m, a.1), (m, b.1), b]);
            } else {
                let m = (a.1 + b.1) / 2.0;
                return Some(vec![a, (a.0, m), (b.0, m), b]);
            }
        }
        return None;
    }
    if da.horizontal() != db.horizontal() {
        let c = if da.horizontal() { (b.0, a.1) } else { (a.0, b.1) };
        if ahead(a, da, c) && ahead(b, db, c) {
            return Some(vec![a, c, b]);
        }
    }
    None
}

// one wire: from port to port, a run travelled to its far end
fn route_one(ctx: &Ctx, raw_all: &[(super::router::Rect, f64)], owner_all: &[usize], w: &super::net::Wire, lattice: (f64, f64), pass: &[usize]) -> Vec<(f64, f64)> {
    route_checked(ctx, raw_all, owner_all, w, lattice, pass).0
}

// (the route, and whether a fixed port's landing lies under another body)
fn route_checked(
    ctx: &Ctx,
    raw_all: &[(super::router::Rect, f64)],
    owner_all: &[usize],
    w: &super::net::Wire,
    lattice: (f64, f64),
    pass: &[usize],
) -> (Vec<(f64, f64)>, bool) {
    // the runs of the wire's own net never block it
    let keep: Vec<usize> = (0..owner_all.len()).filter(|&k| !pass.contains(&owner_all[k]) || owner_all[k] == w.a.dev || owner_all[k] == w.b.dev).collect();
    let raw: Vec<(super::router::Rect, f64)> = keep.iter().map(|&k| raw_all[k]).collect();
    let owner: Vec<usize> = keep.iter().map(|&k| owner_all[k]).collect();
    let (raw, owner) = (&raw[..], &owner[..]);
    use super::router::Port;
    // two pins of one side tied: the U hugging the part, a clearance out
    if w.a.kind == Kind::Pin && w.b.kind == Kind::Pin && w.a.dev == w.b.dev && w.a.dir == w.b.dir {
        let (pa, pb) = (abs_point(ctx, &w.a), abs_point(ctx, &w.b));
        let (vx, vy) = w.a.dir.vec();
        let reach = |p: (f64, f64)| p.0 * vx + p.1 * vy;
        let out = reach(pa).max(reach(pb)) + CLEAR;
        let at = |p: (f64, f64)| -> (f64, f64) {
            if w.a.dir.horizontal() {
                (out * vx, p.1)
            } else {
                (p.0, out * vy)
            }
        };
        return (vec![pa, at(pa), at(pb), pb], false);
    }
    // every box keeps the clearance past its own stroke; a part's own
    // drawing keeps the bare clearance from the wires of its stations
    let stations: Vec<usize> = [&w.a, &w.b].iter().filter(|t| t.kind == Kind::Station && t.dir.horizontal()).map(|t| t.dev).collect();
    let obs: Vec<super::router::Rect> = raw
        .iter()
        .zip(owner)
        .map(|((r, sw), d)| if stations.contains(d) { r.grow(CLEAR) } else { r.grow(CLEAR + sw) })
        .collect();
    let place_obs: Vec<super::router::Rect> = raw.iter().map(|(r, sw)| r.grow(CLEAR + sw)).collect();
    let obs = &obs[..];
    let port = |t: &Term| -> (Port, Option<(f64, f64)>) {
        let own = owner.iter().position(|&d| d == t.dev);
        if t.kind == Kind::Run {
            let o = origin_in(ctx, t.dev, 0);
            let far = (o.0 + t.off.0, o.1 + t.off.1);
            let near = t.through.map(|n| (o.0 + n.0, o.1 + n.1)).unwrap_or(far);
            // the wire joins the run at its first lattice line in from the
            // near end
            let join = |n: f64, f: f64, o: f64| -> f64 {
                let k = (n - o) / 20.0;
                let j = if f < n { (k + 1e-9).floor() } else { (k - 1e-9).ceil() } * 20.0 + o;
                if (j - n).abs() <= (f - n).abs() + 1e-9 {
                    j
                } else {
                    n
                }
            };
            let p = if (near.0 - far.0).abs() < 1e-9 {
                (near.0, join(near.1, far.1, lattice.1))
            } else {
                (join(near.0, far.0, lattice.0), near.1)
            };
            return (Port { p, d: t.dir, own, free: true, station: false }, Some(far));
        }
        (Port { p: abs_point(ctx, t), d: t.dir, own, free: false, station: t.kind == Kind::Station && t.dir.horizontal() }, None)
    };
    let (mut pa, fa) = port(&w.a);
    let (mut pb, fb) = port(&w.b);
    let drop: Vec<usize> = Vec::new();
    let mut obs2: Vec<super::router::Rect> = Vec::new();
    let mut own2: Vec<usize> = Vec::new();
    let mut remap: Vec<Option<usize>> = Vec::new();
    for (k, r) in obs.iter().enumerate() {
        if drop.contains(&owner[k]) {
            remap.push(None);
        } else {
            remap.push(Some(obs2.len()));
            obs2.push(*r);
            own2.push(owner[k]);
        }
    }
    for p in [&mut pa, &mut pb] {
        p.own = p.own.and_then(|k| remap[k]);
    }
    if std::env::var("LINI_SCH_DBG").is_ok() {
        eprintln!("route {:?} -> {:?}", pa, pb);
        for (k, r) in obs2.iter().enumerate() {
            eprintln!("  ob {} {:?}", k, r);
        }
    }
    let raw_obs: Vec<super::router::Rect> = raw.iter().map(|(r, _)| *r).collect();
    let bounds = BOUNDS.with(|b| *b.borrow());
    let world = super::router::World { obs: obs2, place_obs, raw_obs, bounds, owner: own2, lattice };
    let (la, lb) = (world.landing(&pa), world.landing(&pb));
    if std::env::var("LINI_SCH_DBG").is_ok() {
        eprintln!("  landings {:?} {:?}", la, lb);
    }
    // a fixed port whose landing (a clearance out of it) lies within a
    // clearance of another device's drawing: no route
    let covered = |p: &super::router::Port, dev: usize| -> bool {
        if p.free {
            return false;
        }
        let v = p.d.vec();
        let l = (p.p.0 + CLEAR * v.0, p.p.1 + CLEAR * v.1);
        raw.iter().zip(owner).any(|((r, _), &d)| {
            let e = CLEAR;
            d != dev && l.0 > r.x0 - e + 1e-6 && l.0 < r.x1 + e - 1e-6 && l.1 > r.y0 - e + 1e-6 && l.1 < r.y1 + e - 1e-6
        })
    };
    if covered(&pa, w.a.dev) || covered(&pb, w.b.dev) {
        return (Vec::new(), true);
    }
    let mut pts = match world.search(&pa, &pb, 2.0 * CLEAR) {
        Some(p) => p,
        None => direct(pa.p, pa.d, pb.p, pb.d).unwrap_or_else(|| vec![pa.p, pb.p]),
    };
    // two ports a hair out of line: the step between them is drawn, halfway
    // between their landings
    if pts.len() == 2 && fa.is_none() && fb.is_none() {
        let (a, b) = (pts[0], pts[1]);
        if a.0 != b.0 && (a.0 - b.0).abs() < 1e-6 && (a.1 - b.1).abs() > 1e-6 {
            let m = (la.1 + lb.1) / 2.0;
            pts = vec![a, (a.0, m), (b.0, m), b];
        } else if a.1 != b.1 && (a.1 - b.1).abs() < 1e-6 && (a.0 - b.0).abs() > 1e-6 {
            let m = (la.0 + lb.0) / 2.0;
            pts = vec![a, (m, a.1), (m, b.1), b];
        }
        return (pts, false);
    }
    if let Some(f) = fa {
        pts.insert(0, f);
    }
    if let Some(f) = fb {
        pts.push(f);
    }
    (super::router::simplify(&pts), false)
}

// a device's box for a stray's line: its drawing (a component's outline with
// its line) out to its pin stubs, cut back to its ports where they lie inside
fn stray_box(ctx: &Ctx, scope: usize, dev: usize, ports: &[&Term]) -> crate::route::Rect {
    let n = &ctx.nodes[dev];
    let c = &ctx.comp[dev];
    let g = origin_in(ctx, dev, 0);
    let cen = (g.0 - n.geo_off.0, g.1 - n.geo_off.1);
    let hs = if c.has_stroke { c.stroke_width / 2.0 } else { 0.0 };
    let mut b = [cen.0 - n.w / 2.0 - hs, cen.1 - n.h / 2.0 - hs, cen.0 + n.w / 2.0 + hs, cen.1 + n.h / 2.0 + hs];
    let mut stack: Vec<usize> = n.children.clone();
    let mut stations: Vec<Term> = Vec::new();
    while let Some(k) = stack.pop() {
        if super::place::has(ctx, k, "pin-stub") {
            let o = origin_in(ctx, k, dev);
            if let Some(crate::scene::Geo::Points(pts)) = &ctx.nodes[k].geo {
                for p in pts {
                    let q = (g.0 + o.0 + p.0, g.1 + o.1 + p.1);
                    b[0] = b[0].min(q.0);
                    b[1] = b[1].min(q.1);
                    b[2] = b[2].max(q.0);
                    b[3] = b[3].max(q.1);
                }
            }
        }
        if ctx.nodes[k].parent == Some(dev) && ctx.nodes[k].id.is_some() {
            if let Some(t) = super::net::term(ctx, scope, k) {
                if t.kind == Kind::Station {
                    stations.push(t);
                }
            }
        }
        stack.extend(ctx.nodes[k].children.iter().cloned());
    }
    for t in ports.iter().cloned().chain(stations.iter()) {
        let p = (g.0 + t.off.0, g.1 + t.off.1);
        if p.0 > b[0] && p.0 < b[2] && p.1 > b[1] && p.1 < b[3] {
            match t.dir {
                Dir::R => b[2] = p.0,
                Dir::L => b[0] = p.0,
                Dir::D => b[3] = p.1,
                Dir::U => b[1] = p.1,
            }
        }
    }
    crate::route::Rect::new(b[0], b[1], b[2], b[3])
}

pub fn route(ctx: &mut Ctx) {
    reset();
    if !super::active() {
        return;
    }
    let mut all = Wiring::default();
    let mut raws: Vec<(usize, Vec<(usize, [f64; 4])>)> = Vec::new();
    // the devices' drawn boxes (labels aside), each device's together
    let mut bodies: Vec<(usize, Vec<(usize, [f64; 4])>)> = Vec::new();
    let root_sch = ctx.comp[0].layout == "schematic";
    for s in 0..ctx.nodes.len() {
        if ctx.comp[s].layout != "schematic" {
            continue;
        }
        if s != 0 || !root_sch {
            // nested scopes draw wires with the schematic class
        }
        let wires = super::net::wires(ctx, s);
        if !wires.is_empty() && s != 0 {
            all.nested = true;
        }
        // the bodies wires go around, grown by the clearance
        let so = origin_in(ctx, s, 0);
        let nested_box = if s != 0 {
            let (w, h) = (ctx.nodes[s].w, ctx.nodes[s].h);
            let c = (so.0 - ctx.nodes[s].geo_off.0, so.1 - ctx.nodes[s].geo_off.1);
            Some(super::router::Rect::new(c.0 - w / 2.0, c.1 - h / 2.0, c.0 + w / 2.0, c.1 + h / 2.0))
        } else {
            None
        };
        BOUNDS.with(|b| *b.borrow_mut() = nested_box);
        let mut obs: Vec<(super::router::Rect, f64)> = Vec::new();
        let mut owner: Vec<usize> = Vec::new();
        let mut raw_boxes: Vec<(usize, [f64; 4])> = Vec::new();
        let mut devs: Vec<usize> = Vec::new();
        super::place::BODIES.with(|b| {
            for (sc, list) in b.borrow().iter() {
                if *sc != s {
                    continue;
                }
                for (dev, r, sw) in list {
                    obs.push((super::router::Rect::new(so.0 + r[0], so.1 + r[1], so.0 + r[2], so.1 + r[3]), *sw));
                    // a net name keeps off the labels drawn on the sheet
                    if super::place::is_label(ctx, *dev) {
                        raw_boxes.push((*dev, [so.0 + r[0], so.1 + r[1], so.0 + r[2], so.1 + r[3]]));
                    } else if !devs.contains(dev) {
                        devs.push(*dev);
                    }
                    owner.push(*dev);
                }
            }
        });
        raws.push((s, raw_boxes));
        // and off every device's outline out to its stubs (its texts aside)
        let body_boxes: Vec<(usize, [f64; 4])> = devs
            .into_iter()
            .map(|d| {
                let r = stray_box(ctx, s, d, &[]);
                (d, [r.x0, r.y0, r.x1, r.y1])
            })
            .collect();
        bodies.push((s, body_boxes));
        let mut runs_met: Vec<usize> = Vec::new();
        for w in &wires {
            let mut w = w.clone();
            // a run's first wire travels its length; the traffic after it
            // travels it back or continues straight on from its far end,
            // whichever is the shorter way
            let mut onward: Option<super::net::Wire> = None;
            for side in 0..2 {
                let t = if side == 0 { &w.a } else { &w.b };
                if t.kind != Kind::Run {
                    continue;
                }
                if runs_met.contains(&t.dev) {
                    if let Some(near) = t.through {
                        let mut w2 = w.clone();
                        let t2 = if side == 0 { &mut w2.a } else { &mut w2.b };
                        t2.dir = Dir::of_vec(t2.off.0 - near.0, t2.off.1 - near.1);
                        t2.kind = Kind::Other;
                        t2.through = None;
                        onward = Some(w2);
                    }
                } else {
                    runs_met.push(t.dev);
                }
            }
            if let Some(w2) = onward {
                let pass = net_runs(ctx, &wires, w.li);
                let back = route_one(ctx, &obs, &owner, &w, so, &pass);
                let on = route_one(ctx, &obs, &owner, &w2, so, &pass);
                let pts = if path_cost(&on) < path_cost(&back) - 1e-9 { on } else { back };
                all.wires.push(Routed { li: w.li, pts, labels: Vec::new(), scope: s });
                continue;
            }
            // a tag attaches by the end facing the other end of its wire (by
            // its edge above or below off an upright pin)
            let facing = |tag: &Term, other: &Term| -> Dir {
                let o = origin_in(ctx, tag.dev, 0);
                let p = abs_point(ctx, other);
                if other.kind == Kind::Pin && !other.dir.horizontal() {
                    if p.1 > o.1 {
                        Dir::D
                    } else {
                        Dir::U
                    }
                } else if p.0 > o.0 {
                    Dir::R
                } else {
                    Dir::L
                }
            };
            if w.a.kind == Kind::Flag {
                let d = facing(&w.a, &w.b);
                w.a = super::net::flag_end(ctx, &w.a, d);
            }
            if w.b.kind == Kind::Flag {
                let d = facing(&w.b, &w.a);
                w.b = super::net::flag_end(ctx, &w.b, d);
            }
            let pass = net_runs(ctx, &wires, w.li);
            let (pts, blocked) = route_checked(ctx, &obs, &owner, &w, so, &pass);
            if blocked {
                let l = &ctx.links[w.li];
                let msg = format!(
                    "impossible ({} -> {}): fixed port blocked: a body covers the port's landing",
                    crate::links::path_of(ctx, l.from),
                    crate::links::path_of(ctx, l.to)
                );
                ctx.warnings.push(crate::diag::Diag::warning("impossible-link", &msg, l.span));
                let (ba, bb) = (stray_box(ctx, s, w.a.dev, &[&w.a]), stray_box(ctx, s, w.b.dev, &[&w.b]));
                all.strays.push((w.li, ba, bb));
                continue;
            }
            all.wires.push(Routed { li: w.li, pts, labels: Vec::new(), scope: s });
        }
    }
    // wires of different nets sharing a line spread apart
    nudge(ctx, &mut all.wires);
    // net names along the trace
    let routes: Vec<Vec<(f64, f64)>> = all.wires.iter().map(|r| r.pts.clone()).collect();
    let mut placed: Vec<[f64; 4]> = Vec::new();
    for (wi, r) in all.wires.iter_mut().enumerate() {
        let others: Vec<Vec<(f64, f64)>> = routes.iter().enumerate().filter(|(j, _)| *j != wi).map(|(_, p)| p.clone()).collect();
        let mut blocks: Vec<[f64; 4]> = placed.clone();
        if let Some(list) = raws.iter().find(|(sc, _)| *sc == r.scope) {
            // (the wire's own ends aside)
            let l = &ctx.links[r.li];
            let ends = [super::net::device_of(ctx, r.scope, l.from), super::net::device_of(ctx, r.scope, l.to)];
            // (a touch is no meeting)
            let sh = 1.0;
            blocks.extend(list.1.iter().filter(|(d, _)| !ends.contains(&Some(*d))).map(|(_, b)| [b[0] + sh, b[1] + sh, b[2] - sh, b[3] - sh]));
        }
        // a device's outline, its own ends' too, keeps a little margin
        if let Some(list) = bodies.iter().find(|(sc, _)| *sc == r.scope) {
            let g = 2.0;
            blocks.extend(list.1.iter().map(|(_, b)| [b[0] - g, b[1] - g, b[2] + g, b[3] + g]));
        }
        // each name at its own `along` (the last one standing for the rest)
        let alongs: Vec<f64> = ctx.links[r.li]
            .style
            .iter()
            .rev()
            .find(|d| d.name == "along")
            .map(|d| crate::style::value_nums(&ctx.sheet.env, &d.value))
            .unwrap_or_default();
        for (k, t) in link_texts(ctx, r.li).into_iter().enumerate() {
            let along = alongs.get(k).or(alongs.last()).cloned().unwrap_or(0.5);
            let lb = place_label(ctx, &r.pts, along, t, &others, &blocks);
            let tw = {
                let w = if ctx.comp[0].layout == "schematic" { ctx.comp[0].font_weight } else { 400 };
                crate::font::text_width(crate::font::Family::Sans, w, 11.0, &lb.0)
            };
            let b = label_box(lb.1, lb.2, lb.3, tw);
            placed.push(b);

            r.labels.push(lb);
        }
    }
    all.junctions = junctions(ctx, &all.wires);
    WIRING.with(|w| *w.borrow_mut() = all);
}

// a drawn route's length plus two clearances a bend
fn path_cost(pts: &[(f64, f64)]) -> f64 {
    let mut c = 0.0;
    for k in 1..pts.len() {
        c += (pts[k].0 - pts[k - 1].0).abs() + (pts[k].1 - pts[k - 1].1).abs();
        if k >= 2 {
            c += 2.0 * CLEAR;
        }
    }
    c
}

fn link_texts(ctx: &Ctx, li: usize) -> Vec<String> {
    let l = &ctx.links[li];
    let mut out = Vec::new();
    if let Some(t) = &l.label {
        out.push(t.clone());
    }
    for s in &l.labels {
        if let crate::ast::Stmt::Text(t) = s {
            out.push(t.text.clone());
        }
    }
    out
}

// a net name rides beside the trace at `along` of its length: above a level
// run, to the left of an upright one (turned to read up it)
// a net name's place at distance `s` along the trace: (x, y, rotation)
fn label_at(pts: &[(f64, f64)], s: f64, tw: f64, others: &[Vec<(f64, f64)>]) -> (f64, f64, f64) {
    let mut s = s;
    for k in 1..pts.len() {
        let (p, q) = (pts[k - 1], pts[k]);
        let len = (q.0 - p.0).abs() + (q.1 - p.1).abs();
        if s <= len + 1e-9 || k == pts.len() - 1 {
            let f = if len > 0.0 { s / len } else { 0.0 };
            let x = p.0 + (q.0 - p.0) * f;
            let y = p.1 + (q.1 - p.1) * f;
            if same(p.1, q.1) {
                return (x, y - 9.5, 0.0);
            }
            // upright: beside the trace, the side a wire crowds avoided
            let crowded = |lx: f64| -> bool {
                let m = 6.0;
                // the name's side of the trace only
                let b = if lx > x {
                    [x, y - tw / 2.0 - m, lx + 5.5 + m, y + tw / 2.0 + m]
                } else {
                    [lx - 5.5 - m, y - tw / 2.0 - m, x, y + tw / 2.0 + m]
                };
                let hit = |a: (f64, f64), c: (f64, f64)| -> bool {
                    let (x0, x1) = (a.0.min(c.0), a.0.max(c.0));
                    let (y0, y1) = (a.1.min(c.1), a.1.max(c.1));
                    x0 < b[2] - 1e-9 && x1 > b[0] + 1e-9 && y0 < b[3] - 1e-9 && y1 > b[1] + 1e-9
                        || (same(x0, x1) && x0 > b[0] + 1e-9 && x0 < b[2] - 1e-9 && y0 < b[3] - 1e-9 && y1 > b[1] + 1e-9)
                        || (same(y0, y1) && y0 > b[1] + 1e-9 && y0 < b[3] - 1e-9 && x0 < b[2] - 1e-9 && x1 > b[0] + 1e-9)
                };
                let own = (1..pts.len()).any(|j| j != k && hit(pts[j - 1], pts[j]));
                own || others.iter().any(|o| (1..o.len()).any(|j| hit(o[j - 1], o[j])))
            };
            // the side the trace came from (the bend's outside), unless a
            // wire crowds it there and the other side is clear
            // (crowded both sides, the right)
            let pref = if k >= 2 && pts[k - 1].0 < pts[k - 2].0 - 1e-9 { -9.5 } else { 9.5 };
            let side = if !crowded(x + pref) {
                pref
            } else if !crowded(x - pref) {
                -pref
            } else {
                9.5
            };
            return (x + side, y, 270.0);
        }
        s -= len;
    }
    (pts[0].0, pts[0].1 - 9.5, 0.0)
}

fn label_box(x: f64, y: f64, rot: f64, tw: f64) -> [f64; 4] {
    if rot != 0.0 {
        [x - 5.5, y - tw / 2.0, x + 5.5, y + tw / 2.0]
    } else {
        [x - tw / 2.0, y - 5.5, x + tw / 2.0, y + 5.5]
    }
}

// a net name rides beside the trace at `along` of its length: above a level
// run, beside an upright one (turned to read up it); where it would meet a
// name set before or a drawn box it slides along the trace, four at a time,
// back first
fn place_label(ctx: &Ctx, pts: &[(f64, f64)], along: f64, text: String, others: &[Vec<(f64, f64)>], blocks: &[[f64; 4]]) -> (String, f64, f64, f64) {
    let mut total = 0.0;
    for k in 1..pts.len() {
        total += (pts[k].0 - pts[k - 1].0).abs() + (pts[k].1 - pts[k - 1].1).abs();
    }
    let tw = {
        let w = if ctx.comp[0].layout == "schematic" { ctx.comp[0].font_weight } else { 400 };
        crate::font::text_width(crate::font::Family::Sans, w, 11.0, &text)
    };
    let s0 = total * along;
    let clear = |b: &[f64; 4]| !blocks.iter().any(|o| b[0] < o[2] - 1e-9 && o[0] < b[2] - 1e-9 && b[1] < o[3] - 1e-9 && o[1] < b[3] - 1e-9);
    let first = label_at(pts, s0, tw, others);
    if clear(&label_box(first.0, first.1, first.2, tw)) {
        return (text, first.0, first.1, first.2);
    }
    if std::env::var("LINI_SCH_DBG").is_ok() {
        let b = label_box(first.0, first.1, first.2, tw);
        for o in blocks {
            if b[0] < o[2] - 1e-9 && o[0] < b[2] - 1e-9 && b[1] < o[3] - 1e-9 && o[1] < b[3] - 1e-9 {
                eprintln!("name {} at {:?} box {:?} blocked by {:?}", text, (first.0, first.1), b, o);
            }
        }
    }
    for k in 1..400 {
        for sg in [-1.0, 1.0] {
            let s = s0 + sg * 4.0 * k as f64;
            if s < -1e-9 || s > total + 1e-9 {
                continue;
            }
            let (x, y, r) = label_at(pts, s, tw, others);
            if clear(&label_box(x, y, r, tw)) {
                return (text, x, y, r);
            }
        }
    }
    (text, first.0, first.1, first.2)
}

// the run labels on the net of the wire `li` (wires sharing a terminal
// join; a run passes its net's traffic)
fn net_runs(ctx: &Ctx, wires: &[super::net::Wire], li: usize) -> Vec<usize> {
    let ends: Vec<(usize, usize)> = wires.iter().map(|w| (ctx.links[w.li].from, ctx.links[w.li].to)).collect();
    let start = match wires.iter().position(|w| w.li == li) {
        Some(k) => k,
        None => return Vec::new(),
    };
    let mut inn = vec![false; wires.len()];
    inn[start] = true;
    let mut changed = true;
    while changed {
        changed = false;
        for i in 0..wires.len() {
            if inn[i] {
                continue;
            }
            let (a, b) = ends[i];
            if (0..wires.len()).any(|j| inn[j] && (ends[j].0 == a || ends[j].0 == b || ends[j].1 == a || ends[j].1 == b)) {
                inn[i] = true;
                changed = true;
            }
        }
    }
    let mut out = Vec::new();
    for (i, w) in wires.iter().enumerate() {
        if !inn[i] {
            continue;
        }
        for t in [&w.a, &w.b] {
            if t.kind == Kind::Run && !out.contains(&t.dev) {
                out.push(t.dev);
            }
        }
    }
    out
}

// the nets of routed wires: wires sharing a terminal join
fn nets_of(ctx: &Ctx, wires: &[Routed]) -> Vec<usize> {
    let n = wires.len();
    let mut parent: Vec<usize> = (0..n).collect();
    fn find(p: &mut Vec<usize>, i: usize) -> usize {
        let mut i = i;
        while p[i] != i {
            p[i] = p[p[i]];
            i = p[i];
        }
        i
    }
    let ends: Vec<(usize, usize)> = wires.iter().map(|r| (ctx.links[r.li].from, ctx.links[r.li].to)).collect();
    for i in 0..n {
        for j in 0..i {
            let (a, b) = ends[i];
            let (c, d) = ends[j];
            if a == c || a == d || b == c || b == d {
                let (x, y) = (find(&mut parent, i), find(&mut parent, j));
                parent[x] = y;
            }
        }
    }
    (0..n).map(|i| find(&mut parent, i)).collect()
}

// Segments of different nets laid on one line spread apart a clearance at
// a time, centred on it, each toward the way it turns off the shared stretch
// (the one leaving it first stands on the side it leaves by); a segment at a
// port stays.
fn nudge(ctx: &Ctx, wires: &mut [Routed]) {
    let nets = nets_of(ctx, wires);
    for horiz in [true, false] {
        // (wire, segment index k: pts[k-1]..pts[k], line coordinate, lo, hi)
        let mut segs: Vec<(usize, usize, f64, f64, f64)> = Vec::new();
        for (wi, r) in wires.iter().enumerate() {
            let p = &r.pts;
            for k in 1..p.len() {
                let (a, b) = (p[k - 1], p[k]);
                let (along_a, along_b, c0, c1) = if horiz { (a.0, b.0, a.1, b.1) } else { (a.1, b.1, a.0, b.0) };
                if (c0 - c1).abs() < 1e-9 && (along_a - along_b).abs() > 1e-9 {
                    segs.push((wi, k, c0, along_a.min(along_b), along_a.max(along_b)));
                }
            }
        }
        // groups: overlapping segments on one line, of at least two nets
        let n = segs.len();
        let mut done = vec![false; n];
        let mut moves: Vec<(usize, usize, f64)> = Vec::new();
        for i in 0..n {
            if done[i] {
                continue;
            }
            let mut group = vec![i];
            done[i] = true;
            let mut g = 0;
            while g < group.len() {
                let a = segs[group[g]];
                for j in 0..n {
                    if done[j] {
                        continue;
                    }
                    let b = segs[j];
                    if (a.2 - b.2).abs() < 1e-9 && a.3 < b.4 + 1e-9 && b.3 < a.4 + 1e-9 && nets[a.0] != nets[b.0] {
                        done[j] = true;
                        group.push(j);
                    }
                }
                g += 1;
            }
            if group.len() < 2 {
                continue;
            }
            // one entry per net in the group (a net's own segments ride together)
            let mut members: Vec<usize> = Vec::new();
            for &k in &group {
                if !members.iter().any(|&m| nets[segs[m].0] == nets[segs[k].0]) {
                    members.push(k);
                }
            }
            if members.len() < 2 {
                continue;
            }
            // which way a segment turns at its low and high ends (-1 toward
            // the lower coordinate, +1 the higher, 0 a port)
            let turn = |m: usize, high: bool| -> f64 {
                let (wi, k, c, _, _) = segs[m];
                let p = &wires[wi].pts;
                let (a, b) = (p[k - 1], p[k]);
                let a_low = if horiz { a.0 < b.0 } else { a.1 < b.1 };
                // the end at the high (or low) side and its neighbour beyond
                let at_a = a_low != high;
                let nb = if at_a {
                    if k >= 2 { Some(p[k - 2]) } else { None }
                } else if k + 1 < p.len() {
                    Some(p[k + 1])
                } else {
                    None
                };
                match nb {
                    Some(q) => {
                        let v = if horiz { q.1 } else { q.0 };
                        if v < c - 1e-9 {
                            -1.0
                        } else if v > c + 1e-9 {
                            1.0
                        } else {
                            0.0
                        }
                    }
                    None => 0.0,
                }
            };
            let fixed = |m: usize| -> bool {
                let (wi, k, _, _, _) = segs[m];
                k == 1 || k + 1 == wires[wi].pts.len()
            };
            // pairwise: -1 when a stands on the low side of b
            let order = |a: usize, b: usize| -> f64 {
                let (sa, sb) = (segs[a], segs[b]);
                // the stretch they share starts where the later one starts
                if sa.3 > sb.3 + 1e-9 {
                    let t = turn(a, false);
                    if t != 0.0 {
                        return t;
                    }
                } else if sb.3 > sa.3 + 1e-9 {
                    let t = turn(b, false);
                    if t != 0.0 {
                        return -t;
                    }
                }
                if sa.4 < sb.4 - 1e-9 {
                    let t = turn(a, true);
                    if t != 0.0 {
                        return t;
                    }
                } else if sb.4 < sa.4 - 1e-9 {
                    let t = turn(b, true);
                    if t != 0.0 {
                        return -t;
                    }
                }
                0.0
            };
            let mut ord = members.clone();
            // insertion by the pairwise order (ties keep the routing order)
            for x in 1..ord.len() {
                let mut y = x;
                while y > 0 && order(ord[y], ord[y - 1]) < 0.0 {
                    ord.swap(y, y - 1);
                    y -= 1;
                }
            }
            if ord.iter().any(|&m| fixed(m)) {
                continue;
            }
            let cnt = ord.len() as f64;
            for (idx, &m) in ord.iter().enumerate() {
                let off = (idx as f64 - (cnt - 1.0) / 2.0) * CLEAR;
                // the net's segments in this group move together
                for &k in &group {
                    if nets[segs[k].0] == nets[segs[m].0] {
                        moves.push((segs[k].0, segs[k].1, segs[k].2 + off));
                    }
                }
            }
        }
        for (wi, k, v) in moves {
            let p = &mut wires[wi].pts;
            if horiz {
                p[k - 1].1 = v;
                p[k].1 = v;
            } else {
                p[k - 1].0 = v;
                p[k].0 = v;
            }
        }
    }
}

// points where three ways of one net meet
// the boxes of every run label (absolute)
fn run_boxes(ctx: &Ctx) -> Vec<[f64; 4]> {
    let mut out = Vec::new();
    for i in 0..ctx.nodes.len() {
        if super::place::has(ctx, i, "net-run") || super::place::has(ctx, i, "net-run-turned") {
            let o = origin_in(ctx, i, 0);
            let n = &ctx.nodes[i];
            out.push([o.0 - n.w / 2.0, o.1 - n.h / 2.0, o.0 + n.w / 2.0, o.1 + n.h / 2.0]);
        }
    }
    out
}

fn junctions(ctx: &Ctx, wires: &[Routed]) -> Vec<(f64, f64)> {
    let runs = run_boxes(ctx);
    // the way along a run one wire alone travels is the name, not a branch
    let along_run = |p: (f64, f64), d: Dir| -> bool {
        let (vx, vy) = d.vec();
        let q = (p.0 + vx, p.1 + vy);
        let inside = |b: &[f64; 4], q: (f64, f64)| q.0 > b[0] + 1e-9 && q.0 < b[2] - 1e-9 && q.1 > b[1] + 1e-9 && q.1 < b[3] - 1e-9;
        let within = |b: &[f64; 4], q: (f64, f64)| q.0 > b[0] - 1e-9 && q.0 < b[2] + 1e-9 && q.1 > b[1] - 1e-9 && q.1 < b[3] + 1e-9;
        runs.iter().any(|b| within(b, p) && inside(b, q))
    };
    // nets: wires sharing a terminal node (pins, labels) join
    let n = wires.len();
    let mut parent: Vec<usize> = (0..n).collect();
    fn find(p: &mut Vec<usize>, i: usize) -> usize {
        let mut i = i;
        while p[i] != i {
            p[i] = p[p[i]];
            i = p[i];
        }
        i
    }
    let ends: Vec<(usize, usize)> = wires.iter().map(|r| (ctx.links[r.li].from, ctx.links[r.li].to)).collect();
    for i in 0..n {
        for j in 0..i {
            let (a, b) = ends[i];
            let (c, d) = ends[j];
            if a == c || a == d || b == c || b == d {
                let (x, y) = (find(&mut parent, i), find(&mut parent, j));
                parent[x] = y;
            }
        }
    }
    let mut out: Vec<(f64, f64)> = Vec::new();
    let roots: Vec<usize> = (0..n).map(|i| find(&mut parent, i)).collect();
    for i in 0..n {
        let root = roots[i];
        // candidate points: this wire's vertices, then its net's other
        // wires' vertices lying along it (wire by wire)
        let pi = &wires[i].pts;
        let mut cands: Vec<(f64, f64)> = pi.clone();
        for j in 0..n {
            if j == i || roots[j] != root {
                continue;
            }
            for &q in &wires[j].pts {
                let inside = (1..pi.len()).any(|k| on_seg(q, pi[k - 1], pi[k]) && !(same(q.0, pi[k - 1].0) && same(q.1, pi[k - 1].1)));
                if inside {
                    cands.push(q);
                }
            }
        }
        for p in cands {
            if out.iter().any(|q| same(q.0, p.0) && same(q.1, p.1)) {
                continue;
            }
            // the ways leaving p, each with the wires taking it
            let mut dirs: Vec<(Dir, Vec<usize>)> = Vec::new();
            for j in 0..n {
                if find(&mut parent, j) != root {
                    continue;
                }
                let pts = &wires[j].pts;
                for k in 1..pts.len() {
                    let (s, e) = (pts[k - 1], pts[k]);
                    for (from, to) in [(s, e), (e, s)] {
                        // a segment leaving p
                        if on_seg(p, from, to) && !(same(p.0, to.0) && same(p.1, to.1)) {
                            let d = Dir::of_vec(to.0 - p.0, to.1 - p.1);
                            match dirs.iter_mut().find(|x| x.0 == d) {
                                Some(x) => {
                                    if !x.1.contains(&j) {
                                        x.1.push(j);
                                    }
                                }
                                None => dirs.push((d, vec![j])),
                            }
                        }
                    }
                }
            }
            let ways = dirs.iter().filter(|(d, ws)| ws.len() > 1 || !along_run(p, *d)).count();
            if ways >= 3 {
                out.push(p);
            }
        }
    }
    out
}

// p on the segment [a, b] (a included, b excluded unless a == b)
fn on_seg(p: (f64, f64), a: (f64, f64), b: (f64, f64)) -> bool {
    if same(a.1, b.1) && same(p.1, a.1) {
        let (lo, hi) = (a.0.min(b.0), a.0.max(b.0));
        return p.0 > lo - 1e-9 && p.0 < hi + 1e-9;
    }
    if same(a.0, b.0) && same(p.0, a.0) {
        let (lo, hi) = (a.1.min(b.1), a.1.max(b.1));
        return p.1 > lo - 1e-9 && p.1 < hi + 1e-9;
    }
    false
}
