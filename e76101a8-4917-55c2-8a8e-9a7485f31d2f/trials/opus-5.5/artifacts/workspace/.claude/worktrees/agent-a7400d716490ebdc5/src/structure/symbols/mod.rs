//! `symbol_set`: sets of families that are plan symbols and nothing else (AREI).
//!
//! A set's families each have one type, `Standard`, no parameters and no forms, and the symbols
//! of the set's data (the family `symbols` schema). A family the project has by that name stays
//! as it is. The new ones get their library entries as the original gives them after a command:
//! the families' (in name order), then their types' (`<family>: Standard`), then each one's
//! symbols, family by family in name order, each a part with its own id and GUID.

mod data;

use crate::commands::params::opt_text;
use crate::json::{Map, Value};
use crate::session::Session;
use crate::structure::common::{new_guid, R};
use std::sync::OnceLock;

const CMD: &str = "symbol_set";

/// The sets there are.
pub const SETS: &[&str] = &["arei"];

/// The languages a set's family names come in.
pub const NAMES: &[&str] = &["en", "nl", "fr"];

/// One family of a set: its names (English, Dutch, French), category and symbols.
pub struct Symbol {
    pub names: [String; 3],
    pub category: String,
    pub symbols: Vec<Value>,
}

/// The AREI set, in its own order (its English names').
pub fn arei() -> &'static [Symbol] {
    static SET: OnceLock<Vec<Symbol>> = OnceLock::new();
    SET.get_or_init(|| {
        let v = crate::json::parse(data::AREI).expect("arei symbols");
        v.as_arr()
            .unwrap()
            .iter()
            .map(|row| {
                let r = row.as_arr().unwrap();
                let s = |i: usize| r[i].as_str().unwrap_or("").to_string();
                Symbol {
                    names: [s(0), s(1), s(2)],
                    category: s(3),
                    symbols: r[4].as_arr().cloned().unwrap_or_default(),
                }
            })
            .collect()
    })
}

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "symbol_set" => load(s, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
    .map_err(crate::structure::types::clip)
}

fn load(s: &mut Session, p0: &Value) -> R<Value> {
    let p = &crate::structure::types::names_for_guids(&s.project, p0);
    let set = match opt_text(p, CMD, "set")? {
        Some(x) => x,
        None => return Err(format!("{}: `set` is required: {}", CMD, SETS.join(", "))),
    };
    if !SETS.contains(&set.as_str()) {
        return Err(format!("{}: no symbol set `{}`: there is {}", CMD, set, SETS.join(", ")));
    }
    let lang = match opt_text(p, CMD, "names")? {
        Some(n) => {
            let t = n.trim().to_lowercase();
            match NAMES.iter().position(|x| *x == t) {
                Some(i) => i,
                None => return Err(format!("{}: `names` is en, nl or fr, not `{}`", CMD, n)),
            }
        }
        // as given none: a French project's French, a Dutch project's Dutch, else English
        None => match s.project.language().as_str() {
            "nl" => 1,
            "fr" => 2,
            _ => 0,
        },
    };
    let pr = &mut s.project;
    let mut loaded: Vec<String> = Vec::new();
    let mut kept: Vec<String> = Vec::new();
    let mut fresh: Vec<&Symbol> = Vec::new();
    for sym in arei() {
        let name = &sym.names[lang];
        let has = pr.section("families").map(|f| f.contains(name)).unwrap_or(false);
        if has || loaded.contains(name) {
            kept.push(name.clone());
        } else {
            loaded.push(name.clone());
            fresh.push(sym);
        }
    }
    // the families, as the file holds them
    for sym in &fresh {
        let mut f = Map::new();
        f.insert("category", Value::s(&sym.category));
        f.insert("parameters", Value::Arr(Vec::new()));
        f.insert("types", crate::jobj! {"Standard" => Value::obj()});
        f.insert("forms", Value::Arr(Vec::new()));
        f.insert("symbols", Value::Arr(Vec::new()));
        crate::structure::types::put_sorted(pr.section_mut("families"), &sym.names[lang], Value::Obj(f));
    }
    // their library entries and parts, in name order
    let mut order: Vec<&Symbol> = fresh.clone();
    order.sort_by(|a, b| a.names[lang].cmp(&b.names[lang]));
    for sym in &order {
        pr.lib_add("family", &sym.names[lang]);
    }
    for sym in &order {
        pr.lib_add("family-type", &format!("{}: Standard", sym.names[lang]));
    }
    for sym in &order {
        let mut parts = Vec::with_capacity(sym.symbols.len());
        for x in &sym.symbols {
            let mut m = Map::new();
            m.insert("id", Value::u(pr.alloc_lib_id()));
            m.insert("guid", Value::s(&new_guid()));
            if let Value::Obj(o) = x {
                for (k, v) in &o.items {
                    m.insert(k, v.clone());
                }
            }
            parts.push(Value::Obj(m));
        }
        if let Some(Value::Obj(f)) = pr.section_mut("families").get_mut(&sym.names[lang]) {
            f.insert("symbols", Value::Arr(parts));
        }
    }
    crate::structure::common::mark_step();
    let list = |v: Vec<String>| Value::Arr(v.into_iter().map(Value::Str).collect());
    Ok(crate::jobj! {"kept" => list(kept), "loaded" => list(loaded), "set" => set.as_str()})
}
