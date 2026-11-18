//! `conduit_fill`: NBR 5410: a conduit's fill.
//!
//! The conductors of a circuit of `section` mm² (its phases, the neutral, the protective
//! conductor of Tabela 58), `circuits` of them, each by its outside diameter, over the conduit's
//! inside: π d²/4 summed conductor by conductor, circuit by circuit, over π D²/4. A cable the
//! catalogue lacks leaves the fill pending.

mod tables;

use super::circuit::args::{clip, disp, known, num, object, word};
use super::circuit::{protective, reduced_neutral};
use crate::json::{Map, Value};
use crate::session::Session;
use crate::structure::common::R;
use tables::{CABLES, FAMILIES};

const KEYS: &[&str] = &["circuits", "family", "phases", "reduced_neutral", "section", "size"];
const PHASES: &[&str] = &["FN", "FF", "3F", "3FN"];

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let _ = s;
    fill(cid, p).map_err(clip)
}

/// The outside diameter of the cable of a section (within 1e-9), mm.
fn diameter(s: f64) -> Option<f64> {
    CABLES.iter().find(|(c, _)| (s - c).abs() <= 1e-9).map(|(_, d)| *d)
}

fn area(d: f64) -> f64 {
    std::f64::consts::PI * d * d / 4.0
}

fn fill(cmd: &str, p: &Value) -> R<Value> {
    let m = object(cmd, p)?;
    known(cmd, m, KEYS)?;
    let section = num(cmd, m, "section", 0.0, 1000.0)?.unwrap_or(0.0);
    if section == 0.0 {
        return Err(format!("{}: `section` (mm²) is required", cmd));
    }
    let phases = word(cmd, m, "phases", PHASES)?.unwrap_or(0);
    let circuits = num(cmd, m, "circuits", 1.0, 1000.0)?.unwrap_or(1.0).round() as u64;
    let keys: Vec<&str> = FAMILIES.iter().map(|f| f.key).collect();
    let family = &FAMILIES[word(cmd, m, "family", &keys)?.unwrap_or(0)];
    let reduced = super::circuit::args::flag(cmd, m, "reduced_neutral")?.unwrap_or(false);

    let pe = protective(section);
    let sections: Vec<f64> = match phases {
        0 | 1 => vec![section, section, pe],
        2 => vec![section, section, section, pe],
        _ => {
            let n = if reduced { reduced_neutral(section) } else { section };
            vec![section, section, section, n, pe]
        }
    };
    let count = sections.len() as u64 * circuits;
    let mut source = Map::new();
    source.insert("document", Value::s(family.document));
    source.insert("inside", Value::s("outside less twice the wall"));
    source.insert("maker", Value::s(family.maker));
    source.insert("page", Value::s(family.page));
    source.insert("url", Value::s(family.url));
    let source = Value::Obj(source);

    let mut diameters = Vec::with_capacity(sections.len());
    for s in &sections {
        match diameter(*s) {
            Some(d) => diameters.push(d),
            None => {
                let mut out = Map::new();
                out.insert("conductors", Value::u(count));
                out.insert(
                    "pending",
                    Value::s(&format!("the catalogue has no outside diameter for a cable of {} mm²", disp(*s))),
                );
                out.insert("source", source);
                return Ok(Value::Obj(out));
            }
        }
    }
    let size = match m.get("size") {
        None | Some(Value::Null) => None,
        Some(Value::Str(t)) if t.chars().count() <= 256 => Some(t.clone()),
        Some(v) => {
            return Err(format!("{}: `size` must be text of at most 256 characters, got {}", cmd, v.to_compact()))
        }
    };
    let chosen = match &size {
        None => None,
        Some(t) => match family.sizes.iter().position(|(mark, _)| mark == t) {
            Some(i) => Some(i),
            None => {
                let marks: Vec<&str> = family.sizes.iter().map(|(mark, _)| *mark).collect();
                return Err(format!("{}: `size` must be one of {}", cmd, marks.join(", ")));
            }
        },
    };

    let limit = match count {
        1 => 53.0,
        2 => 31.0,
        _ => 40.0,
    };
    let mut cables = 0.0;
    for _ in 0..circuits {
        for d in &diameters {
            cables += area(*d);
        }
    }
    let percent = |inside: f64| cables / area(inside) * 100.0;
    let smallest = family.sizes.iter().find(|(_, inside)| percent(*inside) <= limit + 1e-9).map(|(mark, _)| *mark);

    let mut out = Map::new();
    out.insert("circuits", Value::u(circuits));
    out.insert("conductors", Value::u(count));
    match chosen {
        None => {
            out.insert("fill_percent", Value::Null);
            out.insert("inside_mm", Value::Null);
            out.insert("limit_percent", Value::Null);
            out.insert("ok", Value::Null);
        }
        Some(i) => {
            let inside = family.sizes[i].1;
            let f = percent(inside);
            out.insert("fill_percent", Value::f((f * 10.0).round() / 10.0));
            out.insert("inside_mm", Value::f((inside * 100.0).round() / 100.0));
            out.insert("limit_percent", Value::f(limit));
            out.insert("ok", Value::Bool(f <= limit + 1e-9));
        }
    }
    out.insert("sections_mm2", Value::Arr(sections.iter().map(|s| Value::f(*s)).collect()));
    out.insert("size", size.map(|t| Value::s(&t)).unwrap_or(Value::Null));
    out.insert("smallest", smallest.map(Value::s).unwrap_or(Value::Null));
    out.insert("source", source);
    Ok(Value::Obj(out))
}
