//! Families for the export: their parameters' values for a type and an element (formulas
//! worked out), and their forms as triangle meshes in the family's own axes.

use super::geom::*;
use crate::json::Value;
use crate::project::Project;
use std::collections::HashMap;

/// A form as the export writes it: a closed face set, its points in the order the triangles
/// first meet them, and the name of the material it's made of.
#[derive(Clone, Debug, Default)]
pub struct Mesh {
    pub points: Vec<V3>,
    pub tris: Vec<[usize; 3]>,
    pub material: Option<String>,
}

/// What a door's or window's family reads from the wall it stands in, and how it is flipped.
#[derive(Clone, Copy, Debug)]
pub struct Hosted {
    pub wall_thickness: f64,
    pub flip_facing: bool,
    pub flip_hand: bool,
}

// ---------------------------------------------------------------- values

/// A parameter's value: a number (lengths, angles in degrees, yes/no as 1 or 0) or a text
/// (a material's GUID).
#[derive(Clone, Debug)]
pub enum Val {
    N(f64),
    S(String),
}

impl Val {
    pub fn num(&self) -> f64 {
        match self {
            Val::N(x) => *x,
            Val::S(_) => 0.0,
        }
    }
}

fn val_of(v: &Value) -> Option<Val> {
    match v {
        Value::Num(n) => Some(Val::N(n.as_f64())),
        Value::Bool(b) => Some(Val::N(if *b { 1.0 } else { 0.0 })),
        Value::Str(s) => Some(Val::S(s.clone())),
        _ => None,
    }
}

/// Every parameter's value for a type of a family and an element of it (its own `params`),
/// formulas worked out; a hosted family reads `Wall Thickness`.
pub fn all_values(pr: &Project, fam: &Value, type_name: &str, e: &Value, hosted: Option<Hosted>) -> HashMap<String, Val> {
    let _ = pr;
    let mut vals: HashMap<String, Val> = HashMap::new();
    let params = fam.get("parameters").and_then(|p| p.as_arr()).cloned().unwrap_or_default();
    let mut formulas: Vec<(String, String)> = Vec::new();
    for p in &params {
        let name = p.get("name").and_then(|n| n.as_str()).unwrap_or("").to_string();
        if let Some(v) = p.get("value").and_then(val_of) {
            vals.insert(name.clone(), v);
        }
    }
    if let Some(t) = fam.get("types").and_then(|t| t.get(type_name)).and_then(|t| t.as_obj()) {
        for (k, v) in &t.items {
            if let Some(v) = val_of(v) {
                vals.insert(k.clone(), v);
            }
        }
    }
    // an element's own values, keyed by the parameter's name or its library GUID (a family
    // parameter's entry named `Family: Parameter`)
    if let Some(ps) = e.get("params").and_then(|p| p.as_obj()) {
        for (k, v) in &ps.items {
            let key = match pr.lib_name(k) {
                Some(n) => n,
                None => k.clone(),
            };
            let name = params.iter().filter_map(|p| p.get("name").and_then(|n| n.as_str())).find(|pn| {
                *pn == key.as_str() || key.strip_suffix(pn).map_or(false, |pre| pre.ends_with(": "))
            });
            if let Some(name) = name {
                if let Some(v) = val_of(v) {
                    vals.insert(name.to_string(), v);
                }
            }
        }
    }
    if let Some(h) = hosted {
        vals.insert("Wall Thickness".into(), Val::N(h.wall_thickness));
    }
    for p in &params {
        if let Some(f) = p.get("formula").and_then(|f| f.as_str()) {
            let name = p.get("name").and_then(|n| n.as_str()).unwrap_or("").to_string();
            formulas.push((name, f.to_string()));
        }
    }
    // formulas may read one another: work them out until nothing changes
    for _ in 0..(formulas.len() + 1) {
        let mut changed = false;
        for (name, f) in &formulas {
            let names: Vec<String> = vals.keys().cloned().collect();
            if let Some(x) = eval(f, &vals, &names) {
                let old = vals.get(name).map(|v| v.num());
                if old != Some(x) {
                    vals.insert(name.clone(), Val::N(x));
                    changed = true;
                }
            }
        }
        if !changed {
            break;
        }
    }
    vals
}

/// The numeric parameters' values.
pub fn values(pr: &Project, fam: &Value, type_name: &str, e: &Value, hosted: Option<Hosted>) -> HashMap<String, f64> {
    all_values(pr, fam, type_name, e, hosted)
        .into_iter()
        .filter_map(|(k, v)| match v {
            Val::N(x) => Some((k, x)),
            _ => None,
        })
        .collect()
}

/// A number or a formula of a form.
pub fn size(v: Option<&Value>, vals: &HashMap<String, Val>, names: &[String]) -> f64 {
    match v {
        Some(Value::Num(n)) => n.as_f64(),
        Some(Value::Str(s)) => eval(s, vals, names).unwrap_or(0.0),
        Some(Value::Bool(b)) => {
            if *b {
                1.0
            } else {
                0.0
            }
        }
        _ => 0.0,
    }
}

// ---------------------------------------------------------------- formulas

#[derive(Clone, Debug, PartialEq)]
enum Tok {
    Num(f64),
    Name(String),
    Op(String),
    LP,
    RP,
    Comma,
}

fn lex(s: &str, names: &[String]) -> Option<Vec<Tok>> {
    let cs: Vec<char> = s.chars().collect();
    let mut i = 0;
    let mut out = Vec::new();
    // longest parameter names first
    let mut sorted: Vec<&String> = names.iter().collect();
    sorted.sort_by(|a, b| b.chars().count().cmp(&a.chars().count()));
    while i < cs.len() {
        let c = cs[i];
        if c.is_whitespace() {
            i += 1;
            continue;
        }
        if c.is_ascii_digit() || (c == '.' && i + 1 < cs.len() && cs[i + 1].is_ascii_digit()) {
            let st = i;
            while i < cs.len() && (cs[i].is_ascii_digit() || cs[i] == '.') {
                i += 1;
            }
            if i < cs.len() && (cs[i] == 'e' || cs[i] == 'E') {
                let mut j = i + 1;
                if j < cs.len() && (cs[j] == '+' || cs[j] == '-') {
                    j += 1;
                }
                if j < cs.len() && cs[j].is_ascii_digit() {
                    i = j;
                    while i < cs.len() && cs[i].is_ascii_digit() {
                        i += 1;
                    }
                }
            }
            let t: String = cs[st..i].iter().collect();
            out.push(Tok::Num(t.parse().ok()?));
            continue;
        }
        match c {
            '(' => {
                out.push(Tok::LP);
                i += 1;
                continue;
            }
            ')' => {
                out.push(Tok::RP);
                i += 1;
                continue;
            }
            ',' | ';' => {
                out.push(Tok::Comma);
                i += 1;
                continue;
            }
            _ => {}
        }
        let two: String = cs[i..(i + 2).min(cs.len())].iter().collect();
        if ["<=", ">=", "==", "!=", "<>", "&&", "||"].contains(&two.as_str()) {
            out.push(Tok::Op(two));
            i += 2;
            continue;
        }
        if "+-*/^<>=!%".contains(c) {
            out.push(Tok::Op(c.to_string()));
            i += 1;
            continue;
        }
        // a parameter's name (which may hold spaces), else a word
        let rest: String = cs[i..].iter().collect();
        let mut matched = None;
        for n in &sorted {
            if rest.starts_with(n.as_str()) {
                let after = rest[n.len()..].chars().next();
                if after.map(|a| !(a.is_alphanumeric() || a == '_')).unwrap_or(true) {
                    matched = Some((*n).clone());
                    break;
                }
            }
        }
        if let Some(n) = matched {
            i += n.chars().count();
            out.push(Tok::Name(n));
            continue;
        }
        if c.is_alphabetic() || c == '_' {
            let st = i;
            while i < cs.len() && (cs[i].is_alphanumeric() || cs[i] == '_') {
                i += 1;
            }
            out.push(Tok::Name(cs[st..i].iter().collect()));
            continue;
        }
        return None;
    }
    Some(out)
}

struct Parser<'a> {
    t: Vec<Tok>,
    i: usize,
    vals: &'a HashMap<String, Val>,
}

impl<'a> Parser<'a> {
    fn peek(&self) -> Option<&Tok> {
        self.t.get(self.i)
    }
    fn op(&self) -> Option<String> {
        match self.peek() {
            Some(Tok::Op(o)) => Some(o.clone()),
            _ => None,
        }
    }
    fn expr(&mut self) -> Option<f64> {
        self.or()
    }
    fn or(&mut self) -> Option<f64> {
        let mut a = self.and()?;
        while self.op().as_deref() == Some("||") {
            self.i += 1;
            let b = self.and()?;
            a = if a != 0.0 || b != 0.0 { 1.0 } else { 0.0 };
        }
        Some(a)
    }
    fn and(&mut self) -> Option<f64> {
        let mut a = self.cmp()?;
        while self.op().as_deref() == Some("&&") {
            self.i += 1;
            let b = self.cmp()?;
            a = if a != 0.0 && b != 0.0 { 1.0 } else { 0.0 };
        }
        Some(a)
    }
    fn cmp(&mut self) -> Option<f64> {
        let a = self.add()?;
        if let Some(o) = self.op() {
            let r = match o.as_str() {
                "<" | ">" | "<=" | ">=" | "=" | "==" | "!=" | "<>" => o,
                _ => return Some(a),
            };
            self.i += 1;
            let b = self.add()?;
            let t = match r.as_str() {
                "<" => a < b,
                ">" => a > b,
                "<=" => a <= b,
                ">=" => a >= b,
                "=" | "==" => a == b,
                _ => a != b,
            };
            return Some(if t { 1.0 } else { 0.0 });
        }
        Some(a)
    }
    fn add(&mut self) -> Option<f64> {
        let mut a = self.mul()?;
        loop {
            match self.op().as_deref() {
                Some("+") => {
                    self.i += 1;
                    a += self.mul()?;
                }
                Some("-") => {
                    self.i += 1;
                    a -= self.mul()?;
                }
                _ => return Some(a),
            }
        }
    }
    fn mul(&mut self) -> Option<f64> {
        let mut a = self.unary()?;
        loop {
            match self.op().as_deref() {
                Some("*") => {
                    self.i += 1;
                    a *= self.unary()?;
                }
                Some("/") => {
                    self.i += 1;
                    a /= self.unary()?;
                }
                Some("%") => {
                    self.i += 1;
                    a %= self.unary()?;
                }
                _ => return Some(a),
            }
        }
    }
    fn unary(&mut self) -> Option<f64> {
        match self.op().as_deref() {
            Some("-") => {
                self.i += 1;
                Some(-self.unary()?)
            }
            Some("+") => {
                self.i += 1;
                self.unary()
            }
            Some("!") => {
                self.i += 1;
                let v = self.unary()?;
                Some(if v == 0.0 { 1.0 } else { 0.0 })
            }
            _ => self.pow(),
        }
    }
    fn pow(&mut self) -> Option<f64> {
        let a = self.atom()?;
        if self.op().as_deref() == Some("^") {
            self.i += 1;
            let b = self.unary()?;
            return Some(a.powf(b));
        }
        Some(a)
    }
    fn args(&mut self) -> Option<Vec<f64>> {
        // after the name: ( a, b, … )
        if self.peek() != Some(&Tok::LP) {
            return None;
        }
        self.i += 1;
        let mut out = Vec::new();
        if self.peek() == Some(&Tok::RP) {
            self.i += 1;
            return Some(out);
        }
        loop {
            out.push(self.expr()?);
            match self.peek() {
                Some(Tok::Comma) => self.i += 1,
                Some(Tok::RP) => {
                    self.i += 1;
                    return Some(out);
                }
                _ => return None,
            }
        }
    }
    fn atom(&mut self) -> Option<f64> {
        match self.peek()?.clone() {
            Tok::Num(x) => {
                self.i += 1;
                Some(x)
            }
            Tok::LP => {
                self.i += 1;
                let v = self.expr()?;
                if self.peek() != Some(&Tok::RP) {
                    return None;
                }
                self.i += 1;
                Some(v)
            }
            Tok::Name(n) => {
                self.i += 1;
                if self.peek() == Some(&Tok::LP) && !self.vals.contains_key(&n) {
                    let a = self.args()?;
                    let f = n.to_lowercase();
                    let one = |a: &Vec<f64>| a.first().copied();
                    return match f.as_str() {
                        "min" => a.iter().cloned().reduce(f64::min),
                        "max" => a.iter().cloned().reduce(f64::max),
                        "abs" => one(&a).map(f64::abs),
                        "sqrt" => one(&a).map(f64::sqrt),
                        "round" => one(&a).map(f64::round),
                        "floor" | "rounddown" => one(&a).map(f64::floor),
                        "ceil" | "roundup" => one(&a).map(f64::ceil),
                        "sin" => one(&a).map(|x| x.to_radians().sin()),
                        "cos" => one(&a).map(|x| x.to_radians().cos()),
                        "tan" => one(&a).map(|x| x.to_radians().tan()),
                        "asin" => one(&a).map(|x| x.asin().to_degrees()),
                        "acos" => one(&a).map(|x| x.acos().to_degrees()),
                        "atan" => one(&a).map(|x| x.atan().to_degrees()),
                        "exp" => one(&a).map(f64::exp),
                        "ln" => one(&a).map(f64::ln),
                        "log" => one(&a).map(f64::log10),
                        "if" => {
                            if a.len() == 3 {
                                Some(if a[0] != 0.0 { a[1] } else { a[2] })
                            } else {
                                None
                            }
                        }
                        "and" => Some(if a.iter().all(|x| *x != 0.0) { 1.0 } else { 0.0 }),
                        "or" => Some(if a.iter().any(|x| *x != 0.0) { 1.0 } else { 0.0 }),
                        "not" => one(&a).map(|x| if x == 0.0 { 1.0 } else { 0.0 }),
                        _ => None,
                    };
                }
                if let Some(v) = self.vals.get(&n) {
                    return Some(v.num());
                }
                match n.to_lowercase().as_str() {
                    "pi" => Some(std::f64::consts::PI),
                    "true" | "yes" => Some(1.0),
                    "false" | "no" => Some(0.0),
                    _ => None,
                }
            }
            _ => None,
        }
    }
}

/// Works out a formula over the values.
pub fn eval(f: &str, vals: &HashMap<String, Val>, names: &[String]) -> Option<f64> {
    let t = lex(f, names)?;
    let mut p = Parser { t, i: 0, vals };
    let v = p.expr()?;
    if p.i != p.t.len() {
        return None;
    }
    Some(v)
}

// ---------------------------------------------------------------- forms

/// The forms of a family's type for an element, each a mesh in the family's axes (a hosted
/// family's flipped as its element is).
pub fn meshes(pr: &Project, fam: &Value, type_name: &str, e: &Value, hosted: Option<Hosted>) -> Vec<Mesh> {
    let vals = all_values(pr, fam, type_name, e, hosted);
    // a component mirrored across its x axis; a door or a window flipped to face the other
    // way (across its wall) or to open the other hand (along it)
    let (mx, my) = match hosted {
        Some(h) => (h.flip_hand, h.flip_facing),
        None => (false, e.get("mirrored").and_then(|m| m.as_bool()).unwrap_or(false)),
    };
    let names: Vec<String> = vals.keys().cloned().collect();
    let forms = fam.get("forms").and_then(|f| f.as_arr()).cloned().unwrap_or_default();
    // the solids so far: their triangles as written, what voids left of them, their material
    let mut solids: Vec<(Vec<[V3; 3]>, Option<Vec<super::csg::Poly>>, Option<String>)> = Vec::new();
    for fo in &forms {
        if let Some(vis) = fo.get("visible") {
            let shown = match vis {
                Value::Bool(b) => *b,
                Value::Str(s) => match vals.get(s) {
                    Some(v) => v.num() != 0.0,
                    None => eval(s, &vals, &names).map(|x| x != 0.0).unwrap_or(true),
                },
                Value::Num(n) => n.as_f64() != 0.0,
                _ => true,
            };
            if !shown {
                continue;
            }
        }
        let Some(tris) = prism(fo, &vals, &names) else { continue };
        if fo.get("void").and_then(|v| v.as_bool()).unwrap_or(false) {
            // a void cuts each solid before it that it reaches into
            let vb = bounds(&tris);
            let vp: Vec<super::csg::Poly> = tris.iter().map(|t| super::csg::Poly::new(t.to_vec())).collect();
            for s in solids.iter_mut() {
                if !overlap(bounds(&s.0), vb) {
                    continue;
                }
                let cur = s.1.take().unwrap_or_else(|| s.0.iter().map(|t| super::csg::Poly::new(t.to_vec())).collect());
                s.1 = Some(super::csg::as_triangles(&super::csg::subtract(&cur, &vp)));
            }
            continue;
        }
        solids.push((tris, None, form_material(pr, fo, &vals)));
    }
    let mut out = Vec::new();
    for (mut tris, cut, material) in solids {
        let mut m = match cut {
            None => {
                if mx || my {
                    for t in tris.iter_mut() {
                        for p in t.iter_mut() {
                            if mx {
                                p.x = -p.x;
                            }
                            if my {
                                p.y = -p.y;
                            }
                        }
                        if mx != my {
                            t.swap(1, 2);
                        }
                    }
                }
                mesh_of(&tris)
            }
            Some(polys) => {
                let (points, tris) = super::csg::triangles(&polys, mx, my);
                Mesh { points, tris, material: None }
            }
        };
        m.material = material;
        out.push(m);
    }
    out
}

/// The box round triangles.
fn bounds(tris: &[[V3; 3]]) -> (V3, V3) {
    let mut lo = v3(f64::INFINITY, f64::INFINITY, f64::INFINITY);
    let mut hi = v3(f64::NEG_INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY);
    for t in tris {
        for p in t {
            lo = v3(lo.x.min(p.x), lo.y.min(p.y), lo.z.min(p.z));
            hi = v3(hi.x.max(p.x), hi.y.max(p.y), hi.z.max(p.z));
        }
    }
    (lo, hi)
}

fn overlap(a: (V3, V3), b: (V3, V3)) -> bool {
    a.0.x < b.1.x && b.0.x < a.1.x && a.0.y < b.1.y && b.0.y < a.1.y && a.0.z < b.1.z && b.0.z < a.1.z
}

/// The name of the material a form is made of: a material parameter's value, or a material
/// named by GUID.
fn form_material(pr: &Project, fo: &Value, vals: &HashMap<String, Val>) -> Option<String> {
    let m = fo.get("material")?.as_str()?;
    let g = match vals.get(m) {
        Some(Val::S(s)) => s.clone(),
        _ => m.to_string(),
    };
    pr.lib_name(&g).or_else(|| {
        if pr.get("materials").and_then(|x| x.get(&g)).is_some() {
            Some(g.clone())
        } else {
            None
        }
    })
}

/// Triangulates a simple ring, its corners counter-clockwise: ears clipped from the first
/// corner on.
pub fn ear_clip(ring: &[V2]) -> Vec<[usize; 3]> {
    let n = ring.len();
    let mut idx: Vec<usize> = (0..n).collect();
    let mut out = Vec::new();
    let mut k = 0usize;
    let mut guard = 0;
    while idx.len() >= 3 && guard < 10 * n * n + 10 {
        guard += 1;
        let m = idx.len();
        let i0 = idx[(k + m - 1) % m];
        let i1 = idx[k % m];
        let i2 = idx[(k + 1) % m];
        let (a, b, c) = (ring[i0], ring[i1], ring[i2]);
        let convex = (b - a).cross(c - b) > 0.0;
        let mut ok = convex || m == 3;
        if ok && m > 3 {
            for &j in &idx {
                if j == i0 || j == i1 || j == i2 {
                    continue;
                }
                if in_tri(ring[j], a, b, c) {
                    ok = false;
                    break;
                }
            }
        }
        if ok {
            out.push([i0, i1, i2]);
            idx.remove(k % m);
            if k >= idx.len() {
                k = 0;
            }
        } else {
            k = (k + 1) % m;
        }
    }
    out
}

fn in_tri(p: V2, a: V2, b: V2, c: V2) -> bool {
    let d1 = (b - a).cross(p - a);
    let d2 = (c - b).cross(p - b);
    let d3 = (a - c).cross(p - c);
    d1 >= 0.0 && d2 >= 0.0 && d3 >= 0.0
}

/// A form: swept straight, or turned about an axis in its plane.
fn prism(fo: &Value, vals: &HashMap<String, Val>, names: &[String]) -> Option<Vec<[V3; 3]>> {
    if let Some(m) = fo.get("mesh").and_then(|m| m.as_arr()) {
        // triangles as they came (an imported form)
        let mut out = Vec::with_capacity(m.len());
        for t in m {
            let t = t.as_arr()?;
            if t.len() < 3 {
                continue;
            }
            let mut tri = [v3(0.0, 0.0, 0.0); 3];
            for k in 0..3 {
                let p = t[k].as_arr()?;
                tri[k] = v3(size(p.first(), vals, names), size(p.get(1), vals, names), size(p.get(2), vals, names));
            }
            out.push(tri);
        }
        return if out.is_empty() { None } else { Some(out) };
    }
    if fo.get("axis").and_then(|a| a.as_arr()).map(|a| a.len() >= 2).unwrap_or(false) {
        return revolve(fo, vals, names);
    }
    straight(fo, vals, names)
}

/// A form's profile in its plane, counter-clockwise: its points, or a circle in 32 chords.
fn profile_of(fo: &Value, vals: &HashMap<String, Val>, names: &[String]) -> Option<Vec<V2>> {
    let mut ring: Vec<V2> = Vec::new();
    if let Some(pts) = fo.get("profile").and_then(|p| p.as_arr()) {
        for p in pts {
            let a = p.as_arr()?;
            ring.push(v2(size(a.first(), vals, names), size(a.get(1), vals, names)));
        }
    } else if let Some(c) = fo.get("circle") {
        let cc = c.get("centre").and_then(|x| x.as_arr()).cloned().unwrap_or_default();
        let cx = size(cc.first(), vals, names);
        let cy = size(cc.get(1), vals, names);
        let r = size(c.get("radius"), vals, names);
        let k = 32;
        for i in 0..k {
            let a = std::f64::consts::TAU * i as f64 / k as f64;
            ring.push(v2(cx + r * a.cos(), cy + r * a.sin()));
        }
    }
    if ring.len() < 3 {
        return None;
    }
    if signed_area(&ring) < 0.0 {
        ring.reverse();
    }
    Some(ring)
}

/// A point of a form's plane in the family's axes.
fn plane_point(plane: &str, p: V2, h: f64) -> V3 {
    match plane {
        "xz" => v3(p.x, h, p.y),
        "yz" => v3(h, p.x, p.y),
        _ => v3(p.x, p.y, h),
    }
}

/// A form turned about an axis in its plane from `from` to `to` degrees: its profile at the
/// end and at the start (when it doesn't turn all the way round), then a band for each edge,
/// a step of a 32nd of a turn at a time; every triangle facing out, the end facing the way
/// it turns.
fn revolve(fo: &Value, vals: &HashMap<String, Val>, names: &[String]) -> Option<Vec<[V3; 3]>> {
    let plane = fo.get("plane").and_then(|p| p.as_str()).unwrap_or("xy");
    let from = size(fo.get("from"), vals, names);
    let to = size(fo.get("to"), vals, names);
    let ring = profile_of(fo, vals, names)?;
    let ax = fo.get("axis").and_then(|a| a.as_arr())?;
    let pa = ax[0].as_arr()?;
    let pb = ax[1].as_arr()?;
    let a2 = v2(size(pa.first(), vals, names), size(pa.get(1), vals, names));
    let b2 = v2(size(pb.first(), vals, names), size(pb.get(1), vals, names));
    let a = plane_point(plane, a2, 0.0);
    let k = (plane_point(plane, b2, 0.0) - a).normalize();
    let sweep = to - from;
    let full = sweep.abs() >= 360.0 - 1e-9;
    let steps = ((32.0 * sweep.abs() / 360.0) - 1e-9).ceil().max(1.0) as usize;
    let at = |p: V2, j: usize| -> V3 {
        let th = (from + sweep * j as f64 / steps as f64).to_radians();
        let (mut sn, mut cs) = th.sin_cos();
        // a quarter turn's sine and cosine as they are, not a hair off
        if sn.abs() < 1e-12 {
            sn = 0.0;
        }
        if cs.abs() < 1e-12 {
            cs = 0.0;
        }
        // the part along the axis stays; the part across it turns
        let v = plane_point(plane, p, 0.0) - a;
        let par = k * k.dot(v);
        let perp = v - par;
        a + (par + perp * cs + k.cross(perp) * sn)
    };
    let tris = ear_clip(&ring);
    // which way the end faces: its first triangle as drawn against the way it turns there
    let flip = {
        let t = tris.first()?;
        let (p0, p1, p2) = (at(ring[t[0]], steps), at(ring[t[1]], steps), at(ring[t[2]], steps));
        let n = (p1 - p0).cross(p2 - p0);
        let c = (p0 + p1 + p2) * (1.0 / 3.0);
        let tangent = k.cross(c - a) * sweep.signum();
        n.dot(tangent) < 0.0
    };
    let mut written: Vec<[V3; 3]> = Vec::new();
    let tri = |w: &mut Vec<[V3; 3]>, a: V3, b: V3, c: V3| {
        // none where corners on the axis come together
        if a == b || b == c || a == c {
            return;
        }
        if flip {
            w.push([a, c, b]);
        } else {
            w.push([a, b, c]);
        }
    };
    if !full {
        for t in &tris {
            tri(&mut written, at(ring[t[0]], steps), at(ring[t[1]], steps), at(ring[t[2]], steps));
            tri(&mut written, at(ring[t[0]], 0), at(ring[t[2]], 0), at(ring[t[1]], 0));
        }
    }
    let n = ring.len();
    for i in 0..n {
        let jn = (i + 1) % n;
        for s in 0..steps {
            let (bi, bj, tj, ti) = (at(ring[i], s), at(ring[jn], s), at(ring[jn], s + 1), at(ring[i], s + 1));
            tri(&mut written, bi, bj, tj);
            tri(&mut written, bi, tj, ti);
        }
    }
    Some(written)
}

/// A form swept straight: its profile's caps (the far one first) and its sides.
fn straight(fo: &Value, vals: &HashMap<String, Val>, names: &[String]) -> Option<Vec<[V3; 3]>> {
    let plane = fo.get("plane").and_then(|p| p.as_str()).unwrap_or("xy");
    let from = size(fo.get("from"), vals, names);
    let to = size(fo.get("to"), vals, names);
    let mut ring: Vec<V2> = Vec::new();
    if let Some(pts) = fo.get("profile").and_then(|p| p.as_arr()) {
        for p in pts {
            let a = p.as_arr()?;
            ring.push(v2(size(a.first(), vals, names), size(a.get(1), vals, names)));
        }
    } else if let Some(c) = fo.get("circle") {
        let cc = c.get("centre").and_then(|x| x.as_arr()).cloned().unwrap_or_default();
        let cx = size(cc.first(), vals, names);
        let cy = size(cc.get(1), vals, names);
        let r = size(c.get("radius"), vals, names);
        let k = 32;
        for i in 0..k {
            let a = std::f64::consts::TAU * i as f64 / k as f64;
            ring.push(v2(cx + r * a.cos(), cy + r * a.sin()));
        }
    }
    if ring.len() < 3 {
        return None;
    }
    if signed_area(&ring) < 0.0 {
        ring.reverse();
    }
    let tris = ear_clip(&ring);
    let to3 = |p: V2, h: f64| -> V3 {
        match plane {
            "xz" => v3(p.x, h, p.y),
            "yz" => v3(h, p.x, p.y),
            _ => v3(p.x, p.y, h),
        }
    };
    // the triangles as written: the far cap's and the near cap's in turn, then the sides; a
    // profile in the xz plane faces the other way round its sweep, so all of them turn over
    let flip = plane == "xz";
    let mut written: Vec<[V3; 3]> = Vec::new();
    let tri = |w: &mut Vec<[V3; 3]>, a: V3, b: V3, c: V3| {
        if flip {
            w.push([a, c, b]);
        } else {
            w.push([a, b, c]);
        }
    };
    let n = ring.len();
    for t in &tris {
        tri(&mut written, to3(ring[t[0]], to), to3(ring[t[1]], to), to3(ring[t[2]], to));
        tri(&mut written, to3(ring[t[0]], from), to3(ring[t[2]], from), to3(ring[t[1]], from));
    }
    for i in 0..n {
        let j = (i + 1) % n;
        let (bi, bj, tj, ti) = (to3(ring[i], from), to3(ring[j], from), to3(ring[j], to), to3(ring[i], to));
        tri(&mut written, bi, bj, tj);
        tri(&mut written, bi, tj, ti);
    }
    Some(written)
}

/// A mesh of triangles as written: their corners listed once, in the order first met.
pub fn mesh_of(written: &[[V3; 3]]) -> Mesh {
    let mut m = Mesh::default();
    for t in written {
        let mut idx = [0usize; 3];
        for k in 0..3 {
            let p = t[k];
            idx[k] = match m.points.iter().position(|q| *q == p) {
                Some(i) => i,
                None => {
                    m.points.push(p);
                    m.points.len() - 1
                }
            };
        }
        m.tris.push(idx);
    }
    m
}

/// Mirrors a mesh across its x axis (y to -y), its triangles turned to stay facing out.
pub fn mirror_y(m: &mut Mesh) {
    for p in m.points.iter_mut() {
        p.y = -p.y;
    }
    for t in m.tris.iter_mut() {
        t.swap(1, 2);
    }
}
