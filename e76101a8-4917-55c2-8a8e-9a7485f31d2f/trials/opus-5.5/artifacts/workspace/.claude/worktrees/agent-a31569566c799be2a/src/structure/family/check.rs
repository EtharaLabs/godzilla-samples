//! What the original finds wrong with a family (`Family::problems`): every formula read at
//! once (each name it reads that the family lacks, syntax, functions), then the first thing its
//! rules refuse (`Family::check`, the model's rule too), and the warnings its geometry gives, each
//! said once for the types it holds in (`(in type `A`, `B`)`).

use super::eval::{disp, Eval, MAX_COORD, WALL_THICKNESS};
use super::geom::{self, Bbox, Solid};
use super::model::*;
use crate::json::Value;
use crate::structure::formula::{self, ParseError, MAX_LEN};

/// The most parameters, corners of a profile and points of a symbol's line.
pub const MAX_PARAMS: usize = 64;
pub const MAX_PROFILE: usize = 64;
pub const MAX_LINE: usize = 64;

/// The most characters a symbol's lettered text has.
pub const MAX_TEXT: usize = 256;

/// The longest name a parameter or a type has.
pub const MAX_NAME: usize = 256;

/// Whether a parameter's name is one: a letter (or `_`) first, then letters, digits, `_` and
/// spaces, up to 256 characters.
pub fn name_ok(name: &str) -> bool {
    if name.chars().count() > MAX_NAME {
        return false;
    }
    let mut cs = name.chars();
    match cs.next() {
        Some(c) if c.is_alphabetic() || c == '_' => {}
        _ => return false,
    }
    let ok = cs.all(|c| c.is_alphanumeric() || c == '_' || c == ' ');
    ok && !name.ends_with(' ')
}

// ---------------------------------------------------------------- reading every formula

fn text_of<'a>(out: &mut Vec<&'a str>, x: &'a Expr) {
    if let Expr::Text(s) = x {
        out.push(s.as_str());
    }
}

/// The formulas of a form, in the order the original reads them over its definition.
fn form_formulas(f: &Form) -> Vec<&str> {
    let mut out = Vec::new();
    for p in &f.profile {
        text_of(&mut out, &p[0]);
        text_of(&mut out, &p[1]);
    }
    text_of(&mut out, &f.from);
    text_of(&mut out, &f.to);
    if let Some(v) = &f.visible {
        text_of(&mut out, v);
    }
    if let Some(c) = &f.circle {
        text_of(&mut out, &c.centre[0]);
        text_of(&mut out, &c.centre[1]);
        text_of(&mut out, &c.radius);
    }
    if let Some(a) = &f.axis {
        for p in a {
            text_of(&mut out, &p[0]);
            text_of(&mut out, &p[1]);
        }
    }
    out
}

/// A symbol's formulas the original reads over its definition (its line, `visible`, its arc).
fn symbol_read_formulas(s: &Symbol) -> Vec<&str> {
    let mut out = Vec::new();
    for p in &s.line {
        text_of(&mut out, &p[0]);
        text_of(&mut out, &p[1]);
    }
    if let Some(v) = &s.visible {
        text_of(&mut out, v);
    }
    if let Some(a) = &s.arc {
        text_of(&mut out, &a.centre[0]);
        text_of(&mut out, &a.centre[1]);
        text_of(&mut out, &a.radius);
        text_of(&mut out, &a.from);
        text_of(&mut out, &a.to);
    }
    out
}

/// Every formula of a symbol.
fn symbol_formulas(s: &Symbol) -> Vec<&str> {
    let mut out = symbol_read_formulas(s);
    if let Some(t) = &s.text {
        text_of(&mut out, &t.at[0]);
        text_of(&mut out, &t.at[1]);
        text_of(&mut out, &t.height);
    }
    if let Some(d) = &s.dot {
        text_of(&mut out, &d.centre[0]);
        text_of(&mut out, &d.centre[1]);
        text_of(&mut out, &d.radius);
    }
    out
}

fn connector_formulas(c: &Connector) -> Vec<&str> {
    let mut out = Vec::new();
    text_of(&mut out, &c.voltage);
    match &c.load_va {
        Load::One(x) => text_of(&mut out, x),
        Load::PerPole(v) => v.iter().for_each(|x| text_of(&mut out, x)),
    }
    text_of(&mut out, &c.power_factor);
    out
}

fn too_long(s: &str) -> bool {
    s.chars().count() > MAX_LEN
}

/// What reading a formula of the family's definition finds: its syntax, its functions, each
/// name it reads that the family lacks (none for one longer than the most, which its rules say).
fn read_one(fam: &Family, text: &str, at: &str, out: &mut Vec<String>) {
    if too_long(text) {
        return;
    }
    let f = match formula::parse(text) {
        Ok(f) => f,
        Err(ParseError::Empty) => {
            out.push(format!("{}: a formula is empty", at));
            return;
        }
        Err(ParseError::Syntax(m)) => {
            out.push(format!("{}: formula `{}`: {}", at, text, m));
            return;
        }
    };
    if let Err(m) = f.check_calls() {
        out.push(format!("{}: formula `{}`: {}", at, text, m));
        return;
    }
    for n in f.names() {
        let known = fam.param(&n).is_some() || (fam.hosted() && n == WALL_THICKNESS);
        if !known {
            out.push(format!("{}: formula `{}` reads `{}`, which isn't one of its parameters", at, text, n));
        }
    }
}

/// Every formula of the family read at once.
pub fn read_formulas(fam: &Family) -> Vec<String> {
    let mut out = Vec::new();
    for p in &fam.parameters {
        if let Some(f) = &p.formula {
            read_one(fam, f, &format!("parameter `{}`", p.name), &mut out);
        }
    }
    for (i, f) in fam.forms.iter().enumerate() {
        for t in form_formulas(f) {
            read_one(fam, t, &format!("form {}", i + 1), &mut out);
        }
    }
    for (i, s) in fam.symbols.iter().enumerate() {
        for t in symbol_read_formulas(s) {
            read_one(fam, t, &format!("symbol {}", i + 1), &mut out);
        }
    }
    out
}

// ---------------------------------------------------------------- the family's rules

fn holds(kind: Kind) -> &'static str {
    match kind {
        Kind::YesNo => "yes or no",
        Kind::Material => "a material's name",
        _ => "a number",
    }
}

/// Whether a value is one a parameter of this kind holds (null is none).
fn fits(kind: Kind, v: &Value) -> bool {
    match (kind, v) {
        (_, Value::Null) => true,
        (Kind::Material, Value::Str(_)) => true,
        (Kind::YesNo, Value::Bool(_)) | (Kind::YesNo, Value::Num(_)) => true,
        (Kind::Length | Kind::Number | Kind::Angle, Value::Num(_)) => true,
        _ => false,
    }
}

fn no_material(m: &str) -> String {
    format!("material `{}` isn't in the library; add it with `material`", m)
}

/// The `{Parameter}`s a symbol's text reads, in order; Err for a `{` left open.
pub fn text_refs(value: &str) -> Result<Vec<String>, ()> {
    let mut out = Vec::new();
    let mut rest = value;
    while let Some(i) = rest.find('{') {
        let after = &rest[i + 1..];
        match after.find('}') {
            Some(j) => {
                out.push(after[..j].to_string());
                rest = &after[j + 1..];
            }
            None => return Err(()),
        }
    }
    Ok(out)
}

/// A number as a symbol's text says it: to the thousandth, as plainly as it reads.
pub fn said_number(x: f64) -> String {
    let s = format!("{:.3}", x);
    let s = if s.contains('.') { s.trim_end_matches('0').trim_end_matches('.').to_string() } else { s };
    s
}

/// The rules the family itself is held to, worked out for every type: the first refusal, as
/// the original says it (after `family `name`: `).
pub fn rules(fam: &Family, has_material: &dyn Fn(&str) -> bool) -> Result<(), String> {
    if fam.parameters.len() > MAX_PARAMS {
        return Err(format!("it has more than {} parameters", MAX_PARAMS));
    }
    if fam.types.is_empty() {
        return Err("it needs a type: add one to `types`".into());
    }
    if let Some(k) = &fam.kind {
        let kinds = kinds_of(&fam.category);
        if kinds.is_empty() {
            return Err(format!("`kind` `{}`: a family of this category has no kinds; leave `kind` out", k));
        }
        if !kinds.contains(&k.as_str()) {
            return Err(format!("`kind` is one of {}, not `{}`", kinds.join(", "), k));
        }
    }
    if fam.hosted() {
        for n in ["Width", "Height"] {
            if !fam.parameters.iter().any(|p| p.name == n && p.kind == Kind::Length) {
                return Err(format!(
                    "a door or window family needs a length parameter `{}`: the size of the opening it makes",
                    n
                ));
            }
        }
        if fam.param(WALL_THICKNESS).is_some() {
            return Err(format!(
                "`{}` is the wall's, which a door or a window reads; name the parameter otherwise",
                WALL_THICKNESS
            ));
        }
    }
    let mut seen: Vec<&str> = Vec::new();
    for p in &fam.parameters {
        if !name_ok(&p.name) {
            return Err(format!(
                "parameter `{}`: a name starts with a letter and holds letters, digits, `_` and spaces, up to {}",
                p.name, MAX_NAME
            ));
        }
        if seen.contains(&p.name.as_str()) {
            return Err(format!("parameter `{}` is named twice", p.name));
        }
        seen.push(&p.name);
        if p.kind == Kind::Material && p.formula.is_some() {
            return Err(format!("parameter `{}`: a material takes no formula", p.name));
        }
        if p.formula.as_deref().map(too_long).unwrap_or(false) {
            return Err(format!("parameter `{}`: its formula is longer than {} characters", p.name, MAX_LEN));
        }
        if !fits(p.kind, &p.value) {
            return Err(format!("parameter `{}` holds {}, not {}", p.name, holds(p.kind), p.value.to_compact()));
        }
        if p.kind == Kind::Material {
            if let Value::Str(m) = &p.value {
                if !m.is_empty() && !has_material(m) {
                    return Err(format!("parameter `{}`: {}", p.name, no_material(m)));
                }
            }
        }
    }
    for (t, vals) in &fam.types {
        if t.trim().is_empty() || t.chars().count() > MAX_NAME {
            return Err(format!("type `{}`: a type needs a name, up to {} characters", t, MAX_NAME));
        }
        for (k, v) in vals.iter() {
            let p = match fam.param(k) {
                Some(p) => p,
                None => return Err(format!("type `{}`: `{}` isn't one of its parameters", t, k)),
            };
            if p.instance {
                return Err(format!("type `{}`: `{}` is an instance parameter; each component sets its own", t, k));
            }
            if p.formula.is_some() {
                return Err(format!("type `{}`: `{}` is worked out by its formula", t, k));
            }
            if !fits(p.kind, v) {
                return Err(format!("parameter `{}` holds {}, not {}", k, holds(p.kind), v.to_compact()));
            }
            if p.kind == Kind::Material {
                if let Value::Str(m) = v {
                    if !m.is_empty() && !has_material(m) {
                        return Err(format!("type `{}`: {}", t, no_material(m)));
                    }
                }
            }
        }
    }
    let mats = fam.material_params();
    for (i, f) in fam.forms.iter().enumerate() {
        let n = i + 1;
        let shapes = (!f.profile.is_empty()) as u8 + f.circle.is_some() as u8 + (!f.mesh.is_empty()) as u8;
        if shapes != 1 {
            return Err(format!("form {}: it takes a `profile`, a `circle` or a `mesh`, one of them", n));
        }
        if !f.mesh.is_empty() && f.axis.is_some() {
            return Err(format!("form {}: a `mesh` is as it is; an `axis` turns a `profile` or a `circle`", n));
        }
        if !f.material.is_empty() && !mats.contains(&f.material) && !has_material(&f.material) {
            return Err(format!("form {}: {}", n, no_material(&f.material)));
        }
        if form_formulas(f).into_iter().any(too_long) {
            return Err(format!("form {}: a formula of it is longer than {} characters", n, MAX_LEN));
        }
    }
    for (i, s) in fam.symbols.iter().enumerate() {
        if let Some(t) = &s.text {
            match text_refs(&t.value) {
                Err(()) => return Err(format!("symbol {}: its text has a `{{` with no `}}` to close it", i + 1)),
                Ok(refs) => {
                    for r in refs {
                        if fam.param(r.trim()).is_none() {
                            return Err(format!(
                                "symbol {}: its text reads `{{{}}}`, which isn't one of the family's parameters",
                                i + 1,
                                r
                            ));
                        }
                    }
                }
            }
        }
    }
    if fam.symbols.iter().any(|s| symbol_formulas(s).into_iter().any(too_long)) {
        return Err(format!("a formula of a symbol is longer than {} characters", MAX_LEN));
    }
    if fam.connectors.iter().filter(|c| c.kind == ConnKind::Power).count() > 1 {
        return Err("it has two power connectors: keep one, a device draws its load through one".into());
    }
    for (i, c) in fam.connectors.iter().enumerate() {
        let n = i + 1;
        if connector_formulas(c).into_iter().any(too_long) {
            return Err(format!("connector {}: a formula of it is longer than {} characters", n, MAX_LEN));
        }
        match (c.kind, c.system) {
            (ConnKind::Power, System::Switch) => {
                return Err(format!(
                    "connector {}: a power connector's system is `power-balanced` or `power-unbalanced`, not `switch`",
                    n
                ))
            }
            (ConnKind::Switch, System::Balanced | System::Unbalanced) => {
                return Err(format!("connector {}: a switch connector's system is `switch`", n))
            }
            _ => {}
        }
        if !(1..=3).contains(&c.poles) {
            return Err(format!("connector {}: poles are 1, 2 or 3, not {}", n, c.poles));
        }
        if let Load::PerPole(v) = &c.load_va {
            if c.system != System::Unbalanced || v.len() != c.poles as usize {
                return Err(format!(
                    "connector {}: a load per phase is a list of one for each pole ({}) on a `power-unbalanced` connector; a balanced one takes a single load",
                    n, c.poles
                ));
            }
        }
    }
    // the connectors of every type first (each type's values worked out for them), then each
    // type's formulas, symbols and forms
    if !fam.connectors.is_empty() {
        for (t, _) in &fam.types {
            let ev = Eval::new(fam, Some(t), None, None);
            connectors_worked_out(fam, &ev).map_err(|e| format!("type `{}`: {}", t, e))?;
        }
    }
    for (t, _) in &fam.types {
        let ev = Eval::new(fam, Some(t), None, None);
        parts_worked_out(fam, &ev).map_err(|e| format!("type `{}`: {}", t, e))?;
    }
    Ok(())
}

/// The family worked out for one type (or one component): its connectors (with every
/// parameter's value), then its parameters' formulas, its symbols and its forms; the first refusal.
pub fn worked_out(fam: &Family, ev: &Eval) -> Result<(), String> {
    if !fam.connectors.is_empty() {
        connectors_worked_out(fam, ev)?;
    }
    parts_worked_out(fam, ev)
}

fn connectors_worked_out(fam: &Family, ev: &Eval) -> Result<(), String> {
    ev.values()?;
    for (i, c) in fam.connectors.iter().enumerate() {
        connector_values(c, ev).map_err(|e| format!("connector {}: {}", i + 1, e))?;
    }
    Ok(())
}

/// A type or a component worked out but for its connectors: its parameters' formulas, its symbols,
/// its forms (what a component is held to: its connectors aren't checked against its own values).
pub fn parts_worked_out(fam: &Family, ev: &Eval) -> Result<(), String> {
    for p in &fam.parameters {
        if p.formula.is_some() && p.kind != Kind::Material {
            ev.param(p)?;
        }
    }
    for (i, s) in fam.symbols.iter().enumerate() {
        check_symbol(fam, s, ev).map_err(|e| format!("symbol {}: {}", i + 1, e))?;
    }
    let mut built = Vec::new();
    for (i, f) in fam.forms.iter().enumerate() {
        if let Some(solid) = build_form(f, ev).map_err(|e| format!("form {}: {}", i + 1, e))? {
            let bbox = solid.bbox();
            built.push(Piece { index: i, void: f.void, material: String::new(), solid, bbox });
        }
    }
    cuts_checked(built)
}

/// The most triangles a solid form may have where a void comes to cut it.
pub const MAX_CUT_TRIANGLES: usize = 20_000;

/// The voids cut as `cut` cuts them, each refused where a solid form listed before it (as the
/// voids before have left it, whether it reaches it or not) has more triangles than a cut may
/// take. Only the cuts a later void comes to are made.
fn cuts_checked(pieces: Vec<Piece>) -> Result<(), String> {
    let Some(last) = pieces.iter().rposition(|p| p.void) else { return Ok(()) };
    let mut out: Vec<Piece> = Vec::new();
    for (k, p) in pieces.into_iter().enumerate() {
        if !p.void {
            out.push(p);
            continue;
        }
        for q in &out {
            let n = q.solid.triangle_count();
            if n > MAX_CUT_TRIANGLES {
                return Err(format!(
                    "form {}: the form cut has {} triangles; it can't have more than {} to cut",
                    p.index + 1,
                    n,
                    MAX_CUT_TRIANGLES
                ));
            }
        }
        if k == last {
            break;
        }
        cut_by(&mut out, &p);
    }
    Ok(())
}

/// A void cut out of the solid forms before it whose box (of what is left of them) meets its
/// own, touching counting.
fn cut_by(solids: &mut [Piece], void: &Piece) {
    let Some(vb) = void.bbox else { return };
    for q in solids.iter_mut() {
        let Some(qb) = q.solid.bbox() else { continue };
        if !qb.meets(&vb) {
            continue;
        }
        if let Some(s) = geom::subtract(&q.solid, &void.solid) {
            q.solid = s;
        }
    }
}

// ---------------------------------------------------------------- connectors worked out

/// A connector worked out: its voltage, power factor and load on each pole (none on a switch).
#[derive(Clone, Debug, PartialEq)]
pub struct ConnectorValues {
    pub voltage: f64,
    pub power_factor: f64,
    pub load_by_phase: Vec<f64>,
}

impl ConnectorValues {
    /// Its load in all (the sum of its phases').
    pub fn load(&self) -> f64 {
        self.load_by_phase.iter().copied().sum::<f64>()
    }
}

fn part_usable(ev: &Eval, e: &Expr, what: &str) -> Result<f64, String> {
    ev.usable(e).map_err(|m| format!("its {}: {}", what, m))
}

/// A connector worked out, refused where its values are out of their range.
pub fn connector_values(c: &Connector, ev: &Eval) -> Result<ConnectorValues, String> {
    let voltage = part_usable(ev, &c.voltage, "voltage")?;
    let power_factor = part_usable(ev, &c.power_factor, "power factor")?;
    let loads: Vec<f64> = match &c.load_va {
        Load::One(e) => vec![part_usable(ev, e, "load")?],
        Load::PerPole(v) => {
            let mut out = Vec::with_capacity(v.len());
            for e in v {
                out.push(part_usable(ev, e, "load")?);
            }
            out
        }
    };
    if c.kind == ConnKind::Switch {
        if loads.iter().any(|l| *l != 0.0) {
            return Err("a switch carries no load; leave `load_va` out".into());
        }
        return Ok(ConnectorValues { voltage, power_factor, load_by_phase: Vec::new() });
    }
    if !(voltage > 0.0 && voltage <= 100_000.0) {
        return Err(format!("its voltage is {} V; it takes more than 0 and up to 100000", disp(voltage)));
    }
    if !(power_factor > 0.0 && power_factor <= 1.0) {
        return Err(format!("its power factor is {}; it takes more than 0 and up to 1", disp(power_factor)));
    }
    let poles = c.poles.max(1) as usize;
    let load_by_phase = match &c.load_va {
        Load::PerPole(_) => loads,
        Load::One(_) => vec![loads[0] / poles as f64; poles],
    };
    for l in &load_by_phase {
        if !(*l >= 0.0 && *l <= MAX_COORD) {
            return Err(format!("its load is {} VA; it takes 0 up to 1000000000", disp(*l)));
        }
    }
    Ok(ConnectorValues { voltage, power_factor, load_by_phase })
}

// ---------------------------------------------------------------- symbols worked out

/// A symbol's text with its `{Parameter}`s said.
pub fn said_text(fam: &Family, value: &str, ev: &Eval) -> Result<String, String> {
    let mut out = String::new();
    let mut rest = value;
    while let Some(i) = rest.find('{') {
        out.push_str(&rest[..i]);
        let after = &rest[i + 1..];
        let j = after.find('}').unwrap_or(after.len());
        let name = after[..j].trim();
        if let Some(p) = fam.param(name) {
            match ev.param(p)? {
                super::eval::PVal::Num(x) => out.push_str(&said_number(x)),
                super::eval::PVal::Mat(m) => out.push_str(&m),
            }
        }
        rest = if j < after.len() { &after[j + 1..] } else { "" };
    }
    out.push_str(rest);
    Ok(out)
}

/// A plan symbol worked out, in the family's own axes (mm; arcs in degrees from +x,
/// counter-clockwise).
#[derive(Clone, Debug, PartialEq)]
pub enum Mark {
    Line(Vec<[f64; 2]>),
    Arc { centre: [f64; 2], radius: f64, from: f64, to: f64 },
    /// Capitals `height` mm tall, `at` the middle of the line of text vertically, started,
    /// centred or ended there.
    Text { at: [f64; 2], height: f64, text: String, align: Align },
    Dot { centre: [f64; 2], radius: f64 },
}

/// The symbols a family's plan draws for the values `ev` gives (those there, and that work out).
pub fn marks(fam: &Family, ev: &Eval) -> Vec<Mark> {
    let mut out = Vec::new();
    for s in &fam.symbols {
        if check_symbol(fam, s, ev).is_err() || !ev.visible(&s.visible).unwrap_or(false) {
            continue;
        }
        let m = if !s.line.is_empty() {
            s.line.iter().map(|p| ev.point(p)).collect::<Result<Vec<_>, _>>().ok().map(Mark::Line)
        } else if let Some(a) = &s.arc {
            (|| -> Result<Mark, String> {
                Ok(Mark::Arc { centre: ev.point(&a.centre)?, radius: ev.usable(&a.radius)?, from: ev.usable(&a.from)?, to: ev.usable(&a.to)? })
            })()
            .ok()
        } else if let Some(t) = &s.text {
            (|| -> Result<Mark, String> {
                Ok(Mark::Text { at: ev.point(&t.at)?, height: ev.usable(&t.height)?, text: said_text(fam, &t.value, ev)?, align: t.align })
            })()
            .ok()
        } else if let Some(d) = &s.dot {
            (|| -> Result<Mark, String> { Ok(Mark::Dot { centre: ev.point(&d.centre)?, radius: ev.usable(&d.radius)? }) })().ok()
        } else {
            None
        };
        if let Some(m) = m {
            out.push(m);
        }
    }
    out
}

fn check_symbol(fam: &Family, s: &Symbol, ev: &Eval) -> Result<(), String> {
    let shapes = (!s.line.is_empty()) as u8 + s.arc.is_some() as u8 + s.text.is_some() as u8 + s.dot.is_some() as u8;
    if shapes != 1 || s.line.len() > MAX_LINE {
        return Err(format!(
            "it takes a `line` of up to {} points, an `arc`, a `text` or a `dot`, one of them",
            MAX_LINE
        ));
    }
    if !ev.visible(&s.visible)? {
        return Ok(());
    }
    for p in &s.line {
        ev.point(p)?;
    }
    if let Some(a) = &s.arc {
        ev.point(&a.centre)?;
        let r = ev.usable(&a.radius)?;
        let from = ev.usable(&a.from)?;
        let to = ev.usable(&a.to)?;
        let span = (to - from).abs();
        if !(r > 0.0 && span > 0.0 && span <= 360.0) {
            return Err(format!(
                "its arc has radius {} and runs from {} to {} degrees; it needs a radius above zero and up to a full turn",
                disp(r),
                disp(from),
                disp(to)
            ));
        }
    }
    if let Some(t) = &s.text {
        ev.point(&t.at)?;
        let h = ev.usable(&t.height)?;
        if !(h > 0.0) {
            return Err(format!("its text has height {}; it needs a height above zero", disp(h)));
        }
        let said = said_text(fam, &t.value, ev)?;
        if said.trim().is_empty() {
            return Err("its text is empty; give it a `value` with something to letter".into());
        }
        if said.chars().count() > MAX_TEXT {
            return Err(format!("its text is longer than {} characters", MAX_TEXT));
        }
    }
    if let Some(d) = &s.dot {
        ev.point(&d.centre)?;
        let r = ev.usable(&d.radius)?;
        if !(r > 0.0) {
            return Err(format!("its dot has radius {}; it needs a radius above zero", disp(r)));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------- forms worked out

/// A form worked out: where it is (none when it isn't there), a solid or a void, of what.
#[derive(Clone, Debug)]
pub struct Piece {
    /// Its place among the family's forms, from 0.
    pub index: usize,
    pub void: bool,
    /// Its material's name ("" for none): a material parameter's value where it names one.
    pub material: String,
    pub solid: Solid,
    pub bbox: Option<Bbox>,
}

/// Which side of an axis a point is on: +1, -1, or 0 on it (within a millionth).
fn side(d: f64) -> i8 {
    if d >= 1e-6 {
        1
    } else if d <= -1e-6 {
        -1
    } else {
        0
    }
}

/// A form worked out for the values `ev` gives: None where it isn't visible.
pub fn build_form(f: &Form, ev: &Eval) -> Result<Option<Solid>, String> {
    if !ev.visible(&f.visible)? {
        return Ok(None);
    }
    if f.profile.len() > MAX_PROFILE {
        return Err(format!("its profile has more than {} corners", MAX_PROFILE));
    }
    if !f.mesh.is_empty() {
        for t in &f.mesh {
            for p in t {
                for c in p {
                    if !(c.is_finite() && c.abs() <= MAX_COORD) {
                        return Err("a corner of it isn't a usable number".into());
                    }
                }
            }
        }
        return Ok(Some(geom::mesh(&f.mesh)));
    }
    let mut circle: Option<([f64; 2], f64)> = None;
    let pts: Vec<[f64; 2]> = if let Some(c) = &f.circle {
        let centre = ev.point(&c.centre)?;
        let r = ev.usable(&c.radius)?;
        if !(r > 0.0) {
            return Err(format!("its circle's radius is {}; it needs one above zero", disp(r)));
        }
        circle = Some((centre, r));
        geom::circle(centre, r)
    } else {
        let mut v = Vec::with_capacity(f.profile.len());
        for p in &f.profile {
            v.push(ev.point(p)?);
        }
        v
    };
    let from = ev.usable(&f.from)?;
    let to = ev.usable(&f.to)?;
    let axis = match &f.axis {
        Some(a) => Some([ev.point(&a[0])?, ev.point(&a[1])?]),
        None => None,
    };
    if geom::area(&pts).abs() < 1.0 {
        return Err("its profile has no area: it needs three corners or more, or a circle".into());
    }
    match axis {
        Some(ax) => {
            if from >= to {
                return Err(format!("sweeps nothing: from {} to {} degrees", disp(from), disp(to)));
            }
            if to - from > 360.0 {
                return Err(format!(
                    "turns more than all the way round: from {} to {} degrees, 360 at most",
                    disp(from),
                    disp(to)
                ));
            }
            let d = [ax[1][0] - ax[0][0], ax[1][1] - ax[0][1]];
            let l = (d[0] * d[0] + d[1] * d[1]).sqrt();
            if l < 1e-6 {
                return Err("its axis starts and ends at one point: it needs a direction".into());
            }
            let u = [d[0] / l, d[1] / l];
            let dist = |p: [f64; 2]| u[0] * (p[1] - ax[0][1]) - u[1] * (p[0] - ax[0][0]);
            let crosses = match circle {
                Some((c, r)) => r - dist(c).abs() >= 1e-6,
                None => {
                    let sides: Vec<i8> = pts.iter().map(|p| side(dist(*p))).collect();
                    sides.contains(&1) && sides.contains(&-1)
                }
            };
            if crosses {
                return Err("its profile crosses its axis: draw it to one side of it".into());
            }
            Ok(Some(geom::revolve(f.plane, &pts, ax, from, to)))
        }
        None => {
            if from >= to {
                return Err(format!("sweeps nothing: from {} to {}", disp(from), disp(to)));
            }
            Ok(Some(geom::extrude(f.plane, &pts, from, to)))
        }
    }
}

/// The material a form is of for these values: a material parameter's value where it names one.
pub fn form_material(fam: &Family, f: &Form, ev: &Eval) -> String {
    if f.material.is_empty() {
        return String::new();
    }
    match fam.param(&f.material) {
        Some(p) if p.kind == Kind::Material => match ev.param(p) {
            Ok(super::eval::PVal::Mat(m)) => m,
            _ => String::new(),
        },
        _ => f.material.clone(),
    }
}

/// Each form worked out that builds (and is there), before any void cuts it.
pub fn pieces(fam: &Family, ev: &Eval) -> Vec<Piece> {
    let mut out = Vec::new();
    for (i, f) in fam.forms.iter().enumerate() {
        if let Ok(Some(solid)) = build_form(f, ev) {
            let bbox = solid.bbox();
            out.push(Piece { index: i, void: f.void, material: form_material(fam, f, ev), solid, bbox });
        }
    }
    out
}

/// The solid forms with the voids cut out of those listed before them: each void out of each
/// solid before it whose box (of what is left of it) meets the void's, touching counting.
pub fn cut(pieces: &[Piece]) -> Vec<Piece> {
    let mut out: Vec<Piece> = Vec::new();
    for p in pieces {
        if p.void {
            cut_by(&mut out, p);
        } else {
            out.push(p.clone());
        }
    }
    out
}

/// How high the forms reach over the base, after voids cut them (0 at least).
pub fn height(pieces: &[Piece]) -> f64 {
    let mut h: f64 = 0.0;
    for p in cut(pieces) {
        for poly in &p.solid.polys {
            for v in poly {
                h = h.max(v[2]);
            }
        }
    }
    h
}

/// A length as the warnings say it: to a tenth of a millimetre.
fn tenth(x: f64) -> String {
    disp((x * 10.0).round() / 10.0)
}

/// The warnings the family gives, each said once with the types it holds in.
pub fn warnings(fam: &Family) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    if fam.hosted() && fam.symbols.is_empty() {
        out.push(
            "its plan draws no symbols: a door's or a window's plan shows its swing or its sill, and this one shows nothing"
                .into(),
        );
    }
    // each type's warnings, form by form; said form by form, then type by type
    let mut by_type: Vec<(String, Vec<(usize, String)>)> = Vec::new();
    for (t, _) in &fam.types {
        let ev = Eval::new(fam, Some(t), None, None);
        // a type whose values can't be worked out gives no shapes to warn of
        if ev.values().is_err() {
            continue;
        }
        let ps = pieces(fam, &ev);
        let size = |n: &str| match fam.param(n) {
            Some(p) if p.kind == Kind::Length => ev.param(p).ok().map(|v| v.num()),
            _ => None,
        };
        let wall = if fam.hosted() { Some(ev.wall.unwrap_or(super::eval::DEFAULT_WALL)) } else { None };
        // an opening of no size has no outside to lie in
        let opening = match (fam.hosted(), size("Width"), size("Height")) {
            (true, Some(w), Some(h)) if w > 0.0 && h > 0.0 => Some((w, h)),
            _ => None,
        };
        let mut mine: Vec<(usize, String)> = Vec::new();
        for (k, p) in ps.iter().enumerate() {
            let n = p.index + 1;
            let Some(b) = p.bbox else { continue };
            let mut ws: Vec<String> = Vec::new();
            if p.void {
                let hits = ps[..k].iter().any(|q| !q.void && q.bbox.map(|qb| qb.overlaps(&b)).unwrap_or(false));
                if !hits {
                    ws.push(format!("form {}: its void passes through no solid form listed before it; it cuts nothing", n));
                }
            } else if let Some(wall) = wall {
                let thick = b.max[1] - b.min[1];
                if thick > wall {
                    ws.push(format!(
                        "form {}: it is {} mm thick across the wall where the wall is {} mm",
                        n,
                        tenth(thick),
                        tenth(wall)
                    ));
                }
                let outside = match opening {
                    Some((w, h)) => b.max[0] < -w / 2.0 || b.min[0] > w / 2.0 || b.max[2] < 0.0 || b.min[2] > h,
                    None => false,
                };
                if outside {
                    ws.push(format!(
                        "form {}: it lies wholly outside the opening (x {}…{} mm, z {}…{} mm)",
                        n,
                        tenth(b.min[0]),
                        tenth(b.max[0]),
                        tenth(b.min[2]),
                        tenth(b.max[2])
                    ));
                }
            }
            for w in ws {
                mine.push((p.index, w));
            }
        }
        by_type.push((t.clone(), mine));
    }
    // said once each, in the order of their words, with the types they hold in
    let mut per: std::collections::BTreeMap<String, Vec<String>> = std::collections::BTreeMap::new();
    for (t, ws) in &by_type {
        for (_, w) in ws {
            let ts = per.entry(w.clone()).or_default();
            if !ts.contains(t) {
                ts.push(t.clone());
            }
        }
    }
    for (w, ts) in per {
        let list: Vec<String> = ts.iter().map(|t| format!("`{}`", t)).collect();
        out.push(format!("{} (in type {})", w, list.join(", ")));
    }
    out
}

/// What the original finds wrong with a family: (errors, warnings). The errors are each formula
/// that doesn't read, then the first refusal of its rules, each after `family `name`: `.
pub fn problems(fam: &Family, name: &str, has_material: &dyn Fn(&str) -> bool) -> (Vec<String>, Vec<String>) {
    let mut errors: Vec<String> = read_formulas(fam).into_iter().map(|e| format!("family `{}`: {}", name, e)).collect();
    if let Err(e) = rules(fam, has_material) {
        errors.push(format!("family `{}`: {}", name, e));
    }
    (errors, warnings(fam))
}

/// A refusal carrying every error and warning found.
pub fn refusal(name: &str, errors: &[String], warnings: &[String]) -> String {
    let mut lines: Vec<String> = errors.to_vec();
    for w in warnings {
        lines.push(format!("family `{}`: warning: {}", name, w));
    }
    lines.join("\n")
}
