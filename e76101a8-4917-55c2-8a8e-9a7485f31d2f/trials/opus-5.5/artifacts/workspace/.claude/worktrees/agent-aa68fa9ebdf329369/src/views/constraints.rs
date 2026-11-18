//! A dimension's constraints, text and value: `dimension_constraint`, `dimension_text`, `dimension_value`.

pub mod moves;

use super::common::*;
use super::dims::{self, labels, measure};
use crate::json::{Map, Num, Value};
use crate::project::Project;
use crate::session::Session;
use std::cell::RefCell;

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let pr = &mut s.project;
    match cid {
        "dimension_text" => dimension_text(pr, p),
        "dimension_constraint" => dimension_constraint(pr, p),
        "dimension_value" => dimension_value(pr, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

// ---------------------------------------------------------------- reading the commands

/// The dimension a command's `id` names.
fn dim_param(pr: &Project, cmd: &str, p: &Value) -> R<u64> {
    let v = p.get("id").cloned().unwrap_or(Value::Null);
    let not = || format!("{}: {} is not an element id or GUID", cmd, v.clone().sorted().to_compact());
    let id = match &v {
        Value::Num(Num::U(u)) => *u,
        Value::Num(Num::F(f)) if *f >= 0.0 && f.fract() == 0.0 && *f < 1.8e19 => *f as u64,
        Value::Str(s) => {
            let t = s.trim();
            if let Ok(id) = t.parse::<u64>() {
                id
            } else if let Some(g) = crate::model::normalize_guid(t) {
                match pr.find_guid(&g) {
                    Some(id) => id,
                    None => return Err(format!("{}: no element {}", cmd, s)),
                }
            } else {
                return Err(not());
            }
        }
        _ => return Err(not()),
    };
    if !pr.elements.contains_key(&id) {
        return Err(format!("{}: no element {}", cmd, id));
    }
    if cat_of(pr, id) != "dimension" {
        return Err(format!("{}: {} isn't a dimension", cmd, cat_id(pr, id)));
    }
    Ok(id)
}

/// "dimension N has segments 0 to M, not X".
fn segments_err(cmd: &str, id: u64, n: usize, x: &str) -> String {
    format!("{}: dimension {} has segments 0 to {}, not {}", cmd, id, n.saturating_sub(1), x)
}

/// The order a dimension's fields are kept in.
const FIELD_ORDER: [&str; 19] = [
    "guid", "category", "level", "view", "kind", "orient", "refs", "at", "type", "prefix", "suffix", "above", "below", "replace", "equality",
    "texts", "equal", "locked", "alignment",
];

/// Puts a dimension's fields in the order the original keeps them.
pub fn order_fields(e: &mut Value) {
    let Value::Obj(m) = e else { return };
    let mut out = Map::new();
    for k in FIELD_ORDER {
        if let Some(v) = m.get(k) {
            out.items.push((k.to_string(), v.clone()));
        }
    }
    for (k, v) in &m.items {
        if !FIELD_ORDER.contains(&k.as_str()) {
            out.items.push((k.clone(), v.clone()));
        }
    }
    *m = out;
}

// ---------------------------------------------------------------- dimension_text

fn dimension_text(pr: &mut Project, p: &Value) -> R<Value> {
    const CMD: &str = "dimension_text";
    crate::styles::common::check_keys(p, CMD, &["id", "segment", "prefix", "suffix", "above", "below", "replace"])?;
    let id = dim_param(pr, CMD, p)?;
    let seg = crate::commands::params::opt_num(p, CMD, "segment")?;
    let n = dims::dimension_labels(pr, id).len();
    let seg = match seg {
        None => None,
        Some(s) => {
            if s < 0.0 || s.fract() != 0.0 || s >= n as f64 {
                return Err(segments_err(CMD, id, n, &disp(s)));
            }
            Some(s as usize)
        }
    };
    let mut given: Vec<(&str, String)> = Vec::new();
    for k in labels::TEXT_KEYS {
        if let Some(t) = crate::commands::params::opt_text(p, CMD, k)? {
            given.push((k, t));
        }
    }
    let e = pr.el_mut(id).unwrap();
    match seg {
        None => {
            for (k, t) in &given {
                if t.is_empty() {
                    e.remove(k);
                } else {
                    e.set(k, Value::s(t));
                }
            }
        }
        Some(s) => {
            let mut list: Vec<(usize, labels::Texts)> = labels::segment_texts(e);
            let i = match list.iter().position(|(x, _)| *x == s) {
                Some(i) => i,
                None => {
                    list.push((s, labels::Texts::default()));
                    list.len() - 1
                }
            };
            for (k, t) in &given {
                list[i].1.set(k, Some(t.clone()));
            }
            list.retain(|(_, t)| !t.is_empty());
            list.sort_by_key(|(s, _)| *s);
            if list.is_empty() {
                e.remove("texts");
            } else {
                let arr: Vec<Value> = list
                    .iter()
                    .map(|(s, t)| {
                        let mut m = Map::new();
                        m.insert("segment", Value::u(*s as u64));
                        for k in labels::TEXT_KEYS {
                            if let Some(x) = t.get(k) {
                                m.insert(k, Value::s(x));
                            }
                        }
                        Value::Obj(m)
                    })
                    .collect();
                e.set("texts", Value::Arr(arr));
            }
        }
    }
    order_fields(e);
    super::mark_step();
    let ls = dims::dimension_labels(pr, id);
    Ok(jobj! {"id" => id, "labels" => Value::Arr(ls.into_iter().map(Value::from).collect())})
}

// ---------------------------------------------------------------- dimension_constraint

/// A dimension's locked segments and their lengths.
pub fn locked_of(e: &Value) -> Vec<(usize, f64)> {
    let mut v: Vec<(usize, f64)> = e
        .get("locked")
        .and_then(|l| l.as_arr())
        .map(|a| {
            a.iter()
                .filter_map(|x| Some((x.get("segment")?.as_u64()? as usize, f_of(x, "length").unwrap_or(0.0))))
                .collect()
        })
        .unwrap_or_default();
    v.sort_by_key(|(s, _)| *s);
    v
}

pub fn is_equal(e: &Value) -> bool {
    e.get("equal").and_then(|x| x.as_bool()) == Some(true)
}

fn locked_value(list: &[(usize, f64)]) -> Value {
    Value::Arr(list.iter().map(|(s, l)| jobj! {"segment" => *s as u64, "length" => Value::f(*l)}).collect())
}

fn dimension_constraint(pr: &mut Project, p: &Value) -> R<Value> {
    const CMD: &str = "dimension_constraint";
    crate::styles::common::check_keys(p, CMD, &["id", "equal", "locked"])?;
    let id = dim_param(pr, CMD, p)?;
    let equal = crate::commands::params::opt_bool(p, CMD, "equal")?;
    let values = dims::values(pr, id);
    let n = values.len();
    let locked = match get(p, "locked") {
        None => None,
        Some(Value::Arr(a)) => {
            let mut segs: Vec<usize> = Vec::new();
            for x in a {
                match x {
                    Value::Num(Num::U(u)) if (*u as usize) < n => segs.push(*u as usize),
                    other => return Err(segments_err(CMD, id, n, &other.clone().sorted().to_compact())),
                }
            }
            segs.sort();
            segs.dedup();
            Some(segs)
        }
        Some(v) => return Err(format!("{}: `locked` is a list of segments, not {}", CMD, v.clone().sorted().to_compact())),
    };
    let before = pr.clone();
    let e = pr.el_mut(id).unwrap();
    match equal {
        Some(true) => {
            e.set("equality", Value::Bool(true));
            e.set("equal", Value::Bool(true));
        }
        Some(false) => {
            e.remove("equality");
            e.remove("equal");
        }
        None => {}
    }
    if let Some(segs) = locked {
        if segs.is_empty() {
            e.remove("locked");
        } else {
            let list: Vec<(usize, f64)> = segs.iter().map(|s| (*s, values[*s])).collect();
            e.set("locked", locked_value(&list));
        }
    }
    order_fields(e);
    super::mark_step();
    // the constraints hold now, nothing having moved
    keep_from(Some(&before), pr)?;
    let e = pr.el(id).unwrap();
    let segs: Vec<Value> = locked_of(e).iter().map(|(s, _)| Value::u(*s as u64)).collect();
    Ok(jobj! {"equal" => is_equal(e), "id" => id, "locked" => Value::Arr(segs)})
}

// ---------------------------------------------------------------- dimension_value

fn dimension_value(pr: &mut Project, p: &Value) -> R<Value> {
    const CMD: &str = "dimension_value";
    crate::styles::common::check_keys(p, CMD, &["id", "value", "segment"])?;
    let id = dim_param(pr, CMD, p)?;
    let d = measure::Dim::from_element(id, pr.el(id).unwrap());
    if !d.kind.along() {
        return Err(format!("{}: dimension {} isn't an aligned or a linear one: only their lengths are typed", CMD, id));
    }
    let value = match get(p, "value") {
        None => return Err(format!("{}: `value`, the length in mm, is required", CMD)),
        Some(v) => crate::commands::params::mm_of(v).ok_or_else(|| format!("{}: `value` must be a number in mm, got {}", CMD, v.clone().sorted().to_compact()))?,
    };
    if !(value > 0.0 && value <= 1e9) {
        return Err(format!("{}: `value` is a length above 0 and at most 1000000000 mm, not {}", CMD, disp(value)));
    }
    let laid = {
        let cx = measure::Ctx::new(pr);
        measure::lay(&cx, &d).map_err(|m| format!("dimension {}: {}", id, m))?
    };
    let n = laid.stations.len().saturating_sub(1);
    let seg = match get(p, "segment") {
        None => 0usize,
        Some(v) => {
            let x = crate::commands::params::num_of(v).filter(|x| x.fract() == 0.0 && x.is_finite());
            let Some(x) = x else {
                return Err(format!("{}: `segment` must be a whole number, got {}", CMD, v.clone().sorted().to_compact()));
            };
            if x < 0.0 || x >= n as f64 {
                return Err(segments_err(CMD, id, n, &disp(x)));
            }
            x as usize
        }
    };
    let (a, _) = laid.stations[seg];
    let (b, k) = laid.stations[seg + 1];
    let by = value - (b - a);
    let moved = d.refs[k].id(pr).ok_or_else(|| format!("dimension {}: element {} doesn't exist", id, d.refs[k].guid()))?;
    let before = pr.clone();
    if by != 0.0 {
        moves::move_by(pr, moved, [laid.dir[0] * by, laid.dir[1] * by]);
    }
    // a locked segment is locked at the length typed
    let e = pr.el(id).unwrap();
    let mut list = locked_of(e);
    if let Some(x) = list.iter_mut().find(|(s, _)| *s == seg) {
        x.1 = value;
        let lv = locked_value(&list);
        let e = pr.el_mut(id).unwrap();
        e.set("locked", lv);
    }
    // the other constraints hold, knowing what this moved
    keep_from(Some(&before), pr)?;
    Ok(jobj! {"by" => Value::f(measure::r2(by)), "id" => id, "moved" => moved})
}

// ---------------------------------------------------------------- the model's rules

/// The model rules of this part, checked after every command.
pub fn check(pr: &Project) -> R<()> {
    // each dimension's constraints are checked with the rest of its rules (`dims::check_one`)
    remember(pr);
    Ok(())
}

/// A dimension's constraints' rules: only an aligned or linear one of two segments or more is
/// kept equal, only an aligned or linear one's segments are locked.
pub fn rules(id: u64, e: &Value, d: &measure::Dim) -> R<()> {
    if is_equal(e) && (!d.kind.along() || d.refs.len() < 3) {
        return Err(format!("dimension {}: only an aligned or a linear dimension of two segments or more is kept equal", id));
    }
    if !locked_of(e).is_empty() && !d.kind.along() {
        return Err(format!("dimension {}: only an aligned or a linear dimension's segments are locked", id));
    }
    Ok(())
}

// ---------------------------------------------------------------- keeping the constraints

thread_local! {
    /// The project as the last commands left it, for what the next one moved (where keep isn't
    /// told what the project was before it): the state an undo or a redo goes back to is among
    /// them.
    static RECENT: RefCell<Vec<Project>> = const { RefCell::new(Vec::new()) };
}

/// How many of the states commands left are kept.
const KEPT_STATES: usize = 16;

fn has_constraints(pr: &Project) -> bool {
    pr.elements.values().any(|e| cat(e) == "dimension" && (is_equal(e) || !locked_of(e).is_empty()))
}

/// Remembers the project as a command left it (where it has dimensions).
fn remember(pr: &Project) {
    RECENT.with(|r| {
        let mut v = r.borrow_mut();
        if !pr.elements.values().any(|e| cat(e) == "dimension") {
            v.clear();
            return;
        }
        if v.last().map_or(false, |l| l.elements == pr.elements && l.get("uid") == pr.get("uid")) {
            return;
        }
        v.push(pr.clone());
        if v.len() > KEPT_STATES {
            v.remove(0);
        }
    });
}

/// The remembered state the project most likely was in before this command: of the same
/// project, the one it differs least from (the earlier where two are as near: an undo goes back).
fn likely_before(after: &Project) -> Option<Project> {
    RECENT.with(|r| {
        let v = r.borrow();
        let uid = after.get("uid");
        let mut best: Option<(usize, usize)> = None;
        for (i, s) in v.iter().enumerate() {
            if s.get("uid") != uid {
                continue;
            }
            let mut diff = 0;
            for (id, e) in &after.elements {
                if s.el(*id) != Some(e) {
                    diff += 1;
                }
            }
            diff += s.elements.keys().filter(|id| !after.elements.contains_key(id)).count();
            if best.map_or(true, |(d, _)| diff < d) {
                best = Some((diff, i));
            }
        }
        best.map(|(_, i)| v[i].clone())
    })
}

/// Run after every command that changes the model, before the check (`Session::execute`): each
/// constrained dimension is solved again and what it measures to moved to keep it; Err (the
/// command refused, nothing changed) where it can't be kept.
pub fn keep(pr: &mut Project) -> R<()> {
    if !has_constraints(pr) {
        return Ok(());
    }
    let before = likely_before(pr);
    keep_from(before.as_ref(), pr)
}

/// `keep`, told what the project was before the command.
pub fn keep_from(before: Option<&Project>, pr: &mut Project) -> R<()> {
    if !has_constraints(pr) {
        return Ok(());
    }
    let ids: Vec<u64> = pr
        .ids_of("dimension")
        .into_iter()
        .filter(|id| {
            let e = pr.el(*id).unwrap();
            is_equal(e) || !locked_of(e).is_empty()
        })
        .collect();
    // what keep itself has moved counts as moved for the passes after
    let mut kept: Vec<u64> = Vec::new();
    for _ in 0..PASSES {
        let mut any = false;
        for id in &ids {
            let mv = solve_one(before, &kept, pr, *id)?;
            for (el, v) in mv {
                moves::move_by(pr, el, v);
                if !kept.contains(&el) {
                    kept.push(el);
                }
                any = true;
            }
        }
        if !any {
            return Ok(());
        }
    }
    let id = ids.first().copied().unwrap_or(0);
    Err(format!("dimension {}'s constraints can't be kept: what the command moved pulls its locked segments apart", id))
}

/// Passes of solving before the constraints are said not to hold.
const PASSES: usize = 16;
/// How near a station is to where it goes.
const TOL: f64 = 0.01;

/// What has to move, and by how much, for one dimension's constraints to hold now.
fn solve_one(before: Option<&Project>, kept: &[u64], pr: &Project, id: u64) -> R<Vec<(u64, [f64; 2])>> {
    let e = pr.el(id).unwrap();
    let d = measure::Dim::from_element(id, e);
    if !d.kind.along() {
        return Ok(Vec::new());
    }
    let laid = {
        let cx = measure::Ctx::new(pr);
        match measure::lay(&cx, &d) {
            Ok(l) => l,
            Err(_) => return Ok(Vec::new()),
        }
    };
    let st = &laid.stations;
    let n = st.len();
    if n < 2 {
        return Ok(Vec::new());
    }
    let pos: Vec<f64> = st.iter().map(|s| s.0).collect();
    let el: Vec<Option<u64>> = st.iter().map(|s| d.refs[s.1].id(pr)).collect();
    // what the command moved: the elements it changed (a door whose wall was stretched is
    // changed where its offset from the wall's start is worked out again)
    let moved = |k: usize| -> bool {
        let Some(x) = el[k] else { return false };
        if kept.contains(&x) {
            return true;
        }
        let Some(b) = before else { return false };
        b.el(x) != pr.el(x)
    };
    let locked = locked_of(e);
    let lock_at = |s: usize| locked.iter().find(|(x, _)| *x == s).map(|(_, l)| *l);
    let apart = || format!("dimension {}'s constraints can't be kept: what the command moved pulls its locked segments apart", id);
    let mut target = pos.clone();
    // place a rigid run of stations a..=b, offsets from its first, by what moved, else its first
    let place = |a: usize, offs: &[f64], target: &mut Vec<f64>| -> R<()> {
        let mut base: Option<f64> = None;
        for (i, o) in offs.iter().enumerate() {
            let k = a + i;
            if moved(k) {
                let b = pos[k] - o;
                match base {
                    None => base = Some(b),
                    Some(x) if (x - b).abs() > TOL => return Err(apart()),
                    _ => {}
                }
            }
        }
        let base = base.unwrap_or(pos[a]);
        for (i, o) in offs.iter().enumerate() {
            target[a + i] = base + o;
        }
        Ok(())
    };
    if is_equal(e) && n >= 3 {
        if let Some((_, l0)) = locked.first() {
            if locked.iter().any(|(_, l)| (l - l0).abs() > TOL) {
                return Err(format!("dimension {}'s constraints can't be kept: its locked segments differ in length, so they can't be equal", id));
            }
            let offs: Vec<f64> = (0..n).map(|k| k as f64 * l0).collect();
            place(0, &offs, &mut target)?;
        } else {
            let len = (pos[n - 1] - pos[0]) / (n - 1) as f64;
            for (k, t) in target.iter_mut().enumerate() {
                *t = pos[0] + k as f64 * len;
            }
            target[n - 1] = pos[n - 1];
        }
    } else {
        let mut k = 0;
        while k + 1 < n {
            if lock_at(k).is_none() {
                k += 1;
                continue;
            }
            let a = k;
            let mut offs = vec![0.0];
            while k + 1 < n {
                match lock_at(k) {
                    Some(l) => {
                        let last = *offs.last().unwrap();
                        offs.push(last + l);
                        k += 1;
                    }
                    None => break,
                }
            }
            place(a, &offs, &mut target)?;
        }
    }
    // each element moved once, by what its stations need
    let mut out: Vec<(u64, f64)> = Vec::new();
    for k in 0..n {
        let delta = target[k] - pos[k];
        let Some(x) = el[k] else { continue };
        match out.iter().find(|(y, _)| *y == x) {
            Some((_, dd)) => {
                if (dd - delta).abs() > TOL {
                    return Err(apart());
                }
            }
            None => out.push((x, delta)),
        }
    }
    Ok(out
        .into_iter()
        .filter(|(_, dd)| dd.abs() > TOL)
        .map(|(x, dd)| (x, [laid.dir[0] * dd, laid.dir[1] * dd]))
        .collect())
}
