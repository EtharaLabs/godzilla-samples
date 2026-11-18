//! A reference picked by a point: the nearest line of what the plan cuts (a wall's centre line,
//! faces and ends, a door's or window's centre and jambs, a grid), the nearest end (`{endpoint}`),
//! or the nearest round edge or arc, within 100 mm.

use super::geom::{self, *};
use super::measure::{Ctx, Kind};
use super::refs::{End, Face, Ref, Target};
use super::super::common::*;
use crate::json::Value;
use crate::project::Project;

/// The plan a dimension is in: its level, and the plan view where it is in one.
#[derive(Clone, Copy, Debug)]
pub struct Plan {
    pub level: u64,
    pub view: Option<u64>,
}

impl Plan {
    /// The height the plan cuts at.
    pub fn cut(&self, pr: &Project) -> f64 {
        let lv = pr.el(self.level).and_then(|e| f_of(e, "elevation")).unwrap_or(0.0);
        let key = self.view.unwrap_or(self.level);
        let mut src = key;
        // a dependent view follows its parent's view range
        if let Some(e) = pr.el(key) {
            if let Some(p) = ref_id(pr, e, "parent") {
                src = p;
            }
        }
        let cut = pr
            .el(src)
            .and_then(|e| e.get("view_range"))
            .and_then(|v| f_of(v, "cut"))
            .unwrap_or(1200.0);
        lv + cut
    }
    /// The plan's name in messages: its level's.
    pub fn name(&self, pr: &Project) -> String {
        name_of(pr, self.level)
    }
    /// The views whose detail lines it shows: its own (and a dependent view's parent's).
    fn line_views(&self, pr: &Project) -> Vec<String> {
        let key = self.view.unwrap_or(self.level);
        let mut v = vec![guid(pr, key)];
        if let Some(e) = pr.el(key) {
            if let Some(p) = s_of(e, "parent") {
                v.push(p.to_string());
            }
        }
        v
    }
}

/// Whether the plan cuts a wall (or a column): it spans the plan's cut height.
fn cut_by(pr: &Project, plan: &Plan, base: f64, top: f64) -> bool {
    let h = plan.cut(pr);
    base <= h && h < top
}

fn fmt_pt(p: P) -> String {
    format!("[{}, {}]", disp(p[0]), disp(p[1]))
}

/// The walls the plan cuts, joined.
fn cut_walls<'a>(cx: &'a Ctx, plan: &Plan) -> Vec<&'a Wall> {
    cx.walls().iter().filter(|w| cut_by(cx.pr, plan, w.b.base, w.b.top)).collect()
}

/// The doors and windows in those walls, by id.
fn openings(pr: &Project, walls: &[&Wall], c: &str) -> Vec<u64> {
    let hosts: Vec<&str> = walls.iter().map(|w| w.b.guid.as_str()).collect();
    pr.ids_of(c).into_iter().filter(|id| pr.el(*id).and_then(|e| s_of(e, "host")).map_or(false, |h| hosts.contains(&h))).collect()
}

/// The detail lines in the plan, by id.
fn plan_lines(pr: &Project, plan: &Plan) -> Vec<u64> {
    let views = plan.line_views(pr);
    pr.ids_of("line").into_iter().filter(|id| pr.el(*id).and_then(|e| s_of(e, "view")).map_or(false, |v| views.iter().any(|x| x == v))).collect()
}

/// What a point may pick, gathered element by element, the nearest within reach winning, the
/// first by id where two are as near.
struct Best {
    c: Vec<(u64, usize, f64, Face, Option<End>)>,
}

impl Best {
    fn new() -> Best {
        Best { c: Vec::new() }
    }
    fn offer(&mut self, d: f64, _pr: &Project, id: u64, face: Face, point: Option<End>) {
        let n = self.c.len();
        self.c.push((id, n, d, face, point));
    }
    fn pick(mut self, pr: &Project) -> Option<Ref> {
        self.c.sort_by_key(|x| (x.0, x.1));
        let mut best: Option<&(u64, usize, f64, Face, Option<End>)> = None;
        for x in &self.c {
            if x.2 <= PICK && best.map_or(true, |b| x.2 < b.2) {
                best = Some(x);
            }
        }
        best.map(|b| Ref { target: Target::Guid(guid(pr, b.0)), face: b.3, point: b.4 })
    }
}

/// Which lines a point may pick: those running along (or across) a way, as the dimension's first
/// reference does (an aligned one takes lines along it; a linear or angular one, lines across it).
#[derive(Clone, Copy, Debug)]
pub struct Along {
    pub dir: P,
    pub parallel: bool,
}

impl Along {
    fn takes(&self, a: P, b: P) -> bool {
        let c = cross(unit(sub(b, a)), self.dir).abs();
        if self.parallel {
            c <= PARALLEL
        } else {
            c > PARALLEL
        }
    }
}

/// The line nearest a point, of what an aligned, linear or angular dimension measures to (of
/// those `along` lets it take).
pub fn line_at(cx: &Ctx, plan: &Plan, p: P, along: Option<Along>) -> Result<Ref, String> {
    let pr = cx.pr;
    let mut best = Best::new();
    let walls = cut_walls(cx, plan);
    let takes = |a: P, b: P| along.map_or(true, |f| f.takes(a, b));
    for w in &walls {
        let id = w.id();
        if w.b.straight() {
            // its centre line and faces as lines, from its start's line to its end's
            for (off, f) in [(0.0, Face::Centre), (w.b.t / 2.0, Face::Left), (-w.b.t / 2.0, Face::Right)] {
                let (a, b) = w.full(off);
                if takes(a, b) {
                    best.offer(seg_dist(p, a, b), pr, id, f, None);
                }
            }
        } else if along.is_none() {
            for (off, f) in [(0.0, Face::Centre), (w.b.t / 2.0, Face::Left), (-w.b.t / 2.0, Face::Right)] {
                best.offer(arc_dist(&w.b, off, p), pr, id, f, None);
            }
        }
        if takes(w.sface.0, w.sface.1) {
            best.offer(seg_dist(p, w.sface.0, w.sface.1), pr, id, Face::Start, None);
        }
        if takes(w.eface.0, w.eface.1) {
            best.offer(seg_dist(p, w.eface.0, w.eface.1), pr, id, Face::End, None);
        }
    }
    for c in ["door", "window"] {
        for id in openings(pr, &walls, c) {
            if let Some((_, ls)) = geom::opening_lines(pr, id) {
                for (l, f) in ls.iter().zip([Face::Centre, Face::Start, Face::End]) {
                    if takes(l.0, l.1) {
                        best.offer(seg_dist(p, l.0, l.1), pr, id, f, None);
                    }
                }
            }
        }
    }
    for id in pr.ids_of("grid") {
        let e = pr.el(id).unwrap();
        let a = pt_of(e, "start").unwrap_or([0.0, 0.0]);
        let b = pt_of(e, "end").unwrap_or([0.0, 0.0]);
        if takes(a, b) {
            best.offer(seg_dist(p, a, b), pr, id, Face::Centre, None);
        }
    }
    best.pick(pr).ok_or_else(|| {
        format!(
            "no wall face, wall centre line, wall end, door, window or grid line at {} on {}",
            fmt_pt(p),
            plan.name(pr)
        )
    })
}

/// How far a point is from a curved wall's arc `off` left of its centre line.
fn arc_dist(w: &WallBase, off: f64, p: P) -> f64 {
    let Some((c, _, a0, sweep)) = w.circle() else { return f64::INFINITY };
    let Carrier::Circle { r, .. } = w.carrier(off) else { return f64::INFINITY };
    arc_point_dist(c, r, a0, sweep, p)
}

/// How far a point is from an arc (its nearest point on it, or an end).
pub fn arc_point_dist(c: P, r: f64, a0: f64, sweep: f64, p: P) -> f64 {
    let a = (p[1] - c[1]).atan2(p[0] - c[0]);
    let f = if sweep > 0.0 { wrap(a - a0) / sweep } else { wrap(a0 - a) / -sweep };
    if f <= 1.0 {
        return (dist(p, c) - r).abs();
    }
    let s = [c[0] + r * a0.cos(), c[1] + r * a0.sin()];
    let e = [c[0] + r * (a0 + sweep).cos(), c[1] + r * (a0 + sweep).sin()];
    dist(p, s).min(dist(p, e))
}

/// The end nearest a point: of a wall's centre line or faces, a door's or window's lines, a grid,
/// a detail line.
pub fn end_at(cx: &Ctx, plan: &Plan, p: P) -> Result<Ref, String> {
    let pr = cx.pr;
    let mut best = Best::new();
    let walls = cut_walls(cx, plan);
    for w in &walls {
        let id = w.id();
        for (l, f) in [((w.b.cl.start, w.b.cl.end), Face::Centre), (w.left, Face::Left), (w.right, Face::Right)] {
            best.offer(dist(p, l.0), pr, id, f, Some(End::Start));
            best.offer(dist(p, l.1), pr, id, f, Some(End::End));
        }
    }
    for c in ["door", "window"] {
        for id in openings(pr, &walls, c) {
            if let Some((_, ls)) = geom::opening_lines(pr, id) {
                for (l, f) in ls.iter().zip([Face::Centre, Face::Start, Face::End]) {
                    best.offer(dist(p, l.0), pr, id, f, Some(End::Start));
                    best.offer(dist(p, l.1), pr, id, f, Some(End::End));
                }
            }
        }
    }
    for id in pr.ids_of("grid") {
        let e = pr.el(id).unwrap();
        let a = pt_of(e, "start").unwrap_or([0.0, 0.0]);
        let b = pt_of(e, "end").unwrap_or([0.0, 0.0]);
        best.offer(dist(p, a), pr, id, Face::Centre, Some(End::Start));
        best.offer(dist(p, b), pr, id, Face::Centre, Some(End::End));
    }
    for id in plan_lines(pr, plan) {
        if let Some(s) = geom::line_shape(pr.el(id).unwrap()) {
            let (a, b) = s.ends();
            best.offer(dist(p, a), pr, id, Face::Centre, Some(End::Start));
            best.offer(dist(p, b), pr, id, Face::Centre, Some(End::End));
        }
    }
    best.pick(pr).ok_or_else(|| {
        format!(
            "no end of a wall, a wall face, a door, a window, a grid or a detail line at {} on {}",
            fmt_pt(p),
            plan.name(pr)
        )
    })
}

/// The round edge nearest a point (radial and diameter: a round column, a curved wall's centre
/// line or face, a circle or an arc), or the arc (arc length: a curved wall's, a detail line's).
pub fn round_at(cx: &Ctx, plan: &Plan, p: P, kind: Kind) -> Result<Ref, String> {
    let pr = cx.pr;
    let mut best = Best::new();
    let arcs_only = kind == Kind::ArcLength;
    if !arcs_only {
        for c in ["column", "structuralcolumn", "footing"] {
            for id in pr.ids_of(c) {
                let e = pr.el(id).unwrap();
                if let Some((ctr, r)) = geom::round_column(pr, e) {
                    let (base, top) = super::super::model::base_top(pr, e);
                    if cut_by(pr, plan, base, top) {
                        best.offer((dist(p, ctr) - r).abs(), pr, id, Face::Centre, None);
                    }
                }
            }
        }
    }
    for w in cut_walls(cx, plan) {
        if w.b.straight() {
            continue;
        }
        for (off, f) in [(0.0, Face::Centre), (w.b.t / 2.0, Face::Left), (-w.b.t / 2.0, Face::Right)] {
            best.offer(arc_dist(&w.b, off, p), pr, w.id(), f, None);
        }
    }
    for id in plan_lines(pr, plan) {
        match geom::line_shape(pr.el(id).unwrap()) {
            Some(LineShape::Arc { c, r, a0, sweep, .. }) => best.offer(arc_point_dist(c, r, a0, sweep, p), pr, id, Face::Centre, None),
            Some(LineShape::Circle { c, r }) if !arcs_only => best.offer((dist(p, c) - r).abs(), pr, id, Face::Centre, None),
            _ => {}
        }
    }
    best.pick(pr).ok_or_else(|| {
        if arcs_only {
            format!("no curved wall or arc at {} on {}", fmt_pt(p), plan.name(pr))
        } else {
            format!("no round column's, curved wall's, circle's or arc's edge at {} on {}", fmt_pt(p), plan.name(pr))
        }
    })
}

/// Everything a reference's element spans in plan, for where `at` lies (a linear dimension's way).
pub fn extent(cx: &Ctx, r: &Ref) -> Vec<P> {
    let pr = cx.pr;
    let Some(id) = r.id(pr) else { return Vec::new() };
    let e: &Value = pr.el(id).unwrap();
    match cat(e) {
        "wall" => {
            let Some(w) = cx.wall(id) else { return Vec::new() };
            if let Some(end) = r.point {
                // a point: where it is
                return super::measure::ref_geo(cx, r).ok().map(|g| match g {
                    super::measure::Geo::Point(p) => vec![p],
                    super::measure::Geo::Line(a, b) => vec![if end == End::Start { a } else { b }],
                }).unwrap_or_default();
            }
            if !w.b.straight() {
                return w.outline();
            }
            match r.face {
                Face::Centre => {
                    let (a, b) = w.full(0.0);
                    vec![a, b]
                }
                Face::Left => {
                    let (a, b) = w.full(w.b.t / 2.0);
                    vec![a, b]
                }
                Face::Right => {
                    let (a, b) = w.full(-w.b.t / 2.0);
                    vec![a, b]
                }
                Face::Start => vec![w.sface.0, w.sface.1],
                Face::End => vec![w.eface.0, w.eface.1],
            }
        }
        _ => match super::measure::ref_geo(cx, r) {
            Ok(super::measure::Geo::Point(p)) => vec![p],
            Ok(super::measure::Geo::Line(a, b)) => vec![a, b],
            Err(_) => Vec::new(),
        },
    }
}
