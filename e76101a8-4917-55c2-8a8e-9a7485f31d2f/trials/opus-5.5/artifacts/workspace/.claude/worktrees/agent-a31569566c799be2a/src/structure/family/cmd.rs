//! The `family` command: list, read, create, change (parts patched, deleted, replaced by
//! place), dry run, rename, delete, load from a file and save to one.
//!
//! The original reads its keys in this order, each done as it's read: `path` (the family file,
//! whose definition keys stand for the command's), `name`, `save` (the family written to a file,
//! and nothing else), `delete` without a name, `dry_run`, `delete`, then the definition:
//! `category`, `parameters`, `forms`, `symbols`, `form`, `symbol`, `delete_form`, `delete_symbol`,
//! `connectors`, `operation`, `kind`, `types`, `rename`. The family it makes is then held to its
//! rules (every error and warning said at once), and its components to it.

use super::check::{problems, refusal};
use super::de::{self, DeR};
use super::eval::{values_view, Eval};
use super::ids;
use super::model::*;
use super::{exists, family_of, has_material, put_family, view_of};
use crate::commands::params::{opt_bool, opt_text};
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;
use crate::structure::common::R;

const CMD: &str = "family";

/// The keys that change a family.
const CHANGE_KEYS: &[&str] = &[
    "category",
    "parameters",
    "types",
    "forms",
    "symbols",
    "connectors",
    "form",
    "symbol",
    "delete_form",
    "delete_symbol",
    "operation",
    "kind",
    "rename",
];

/// The keys a family file gives.
const FILE_KEYS: &[&str] = &["category", "parameters", "types", "forms", "symbols", "connectors", "operation", "kind"];

fn given(p: &Value, k: &str) -> Option<Value> {
    match p.get(k) {
        None | Some(Value::Null) => None,
        Some(v) => Some(v.clone()),
    }
}

fn serde<T>(key: &str, r: DeR<T>) -> R<T> {
    r.map_err(|e| format!("{}: `{}`: {}", CMD, key, e))
}

fn patch_of(src: &Value, key: &str, what: &str) -> R<Option<Map>> {
    match given(src, key) {
        None => Ok(None),
        Some(Value::Obj(m)) => Ok(Some(m)),
        Some(v) => Err(format!("{}: `{}` must be {{id | guid, …the {}'s fields}}, not {}", CMD, key, what, v.to_compact())),
    }
}

/// What a dry run reports.
#[derive(Default)]
struct Report {
    forms_deleted: Vec<u64>,
    forms_patched: Vec<u64>,
    forms_replaced: usize,
    symbols_deleted: Vec<u64>,
    symbols_patched: Vec<u64>,
    symbols_replaced: usize,
}

/// A part chosen by `id` (a number, or one in a string) or `guid`.
enum Pick {
    Id(u64),
    Guid(String),
}

impl Pick {
    fn shown(&self) -> String {
        match self {
            Pick::Id(n) => n.to_string(),
            Pick::Guid(g) => g.clone(),
        }
    }
}

fn pick_of(v: &Value) -> Option<Pick> {
    match v {
        Value::Num(n) => {
            let x = n.as_f64();
            if x >= 0.0 && x.fract() == 0.0 {
                Some(Pick::Id(x as u64))
            } else {
                None
            }
        }
        Value::Str(s) => {
            let t = s.trim();
            if !t.is_empty() && t.bytes().all(|b| b.is_ascii_digit()) {
                return t.parse::<u64>().ok().map(Pick::Id);
            }
            de::real_guid(s).map(Pick::Guid)
        }
        _ => None,
    }
}

fn matches(pick: &Pick, id: Option<u64>, guid: &Option<GRef>) -> bool {
    match pick {
        Pick::Id(n) => id == Some(*n),
        Pick::Guid(g) => guid.as_ref().and_then(|x| x.guid()) == Some(g.as_str()),
    }
}

/// Binds new parts to the old ones by place: one given without an id or a GUID takes those of
/// the part in its place before.
fn keep_by_place<T>(new: &mut [T], old: &[T], get: impl Fn(&T) -> (Option<u64>, Option<GRef>), set: impl Fn(&mut T, Option<u64>, Option<GRef>)) {
    for (i, n) in new.iter_mut().enumerate() {
        let (id, g) = get(n);
        if id.is_none() && g.is_none() {
            if let Some(o) = old.get(i) {
                let (oid, og) = get(o);
                set(n, oid, og);
            }
        }
    }
}

fn not_of(what: &str, pick: &Pick, family: &str) -> String {
    format!("{}: {} {} is not of family {:?}", CMD, what, pick.shown(), family)
}

/// The `id` or `guid` a patch picks its part by.
fn patch_pick(m: &Map, what: &str) -> R<Pick> {
    let sel = m.get("id").filter(|v| !v.is_null()).or_else(|| m.get("guid").filter(|v| !v.is_null()));
    match sel {
        None => Err(format!("{}: `{}` needs the {}'s `id` or `guid`", CMD, what, what)),
        Some(v) => pick_of(v).ok_or_else(|| format!("{}: `{}` needs the {}'s `id` or `guid`, not {}", CMD, what, what, v.to_compact())),
    }
}

/// Merges a patch's fields over a part's (a null taking one away).
fn merged(part: Value, patch: &Map) -> Value {
    let mut m = match part {
        Value::Obj(m) => m,
        _ => Map::new(),
    };
    for (k, v) in patch.iter() {
        if k == "id" || k == "guid" {
            continue;
        }
        if v.is_null() {
            m.remove(k);
        } else {
            m.insert(k, v.clone());
        }
    }
    Value::Obj(m)
}

fn form_view(f: &Form, fam: &Family) -> Value {
    let mut one = fam.clone();
    one.forms = vec![f.clone()];
    one.view().get("forms").and_then(|a| a.as_arr()).and_then(|a| a.first()).cloned().unwrap_or(Value::Null)
}

/// Builds the family a change makes of `old` (none: a new one), each key read and done in the
/// original's order: `src` is the command's parameters, or a family file's object.
fn apply(old: Option<&Family>, name: &str, src: &Value, from_file: bool, rep: &mut Report) -> R<(Family, String)> {
    let mut f = old.cloned().unwrap_or_default();
    if let Some(v) = given(src, "category") {
        f.category = serde("category", de::de_category(&v))?;
    }
    if let Some(v) = given(src, "parameters") {
        f.parameters = serde("parameters", de::de_seq(&v, &de::de_param))?;
    }
    if let Some(v) = given(src, "forms") {
        let mut fs = serde("forms", de::de_seq(&v, &de::de_form))?;
        keep_by_place(&mut fs, &f.forms, |x| (x.id, x.guid.clone()), |x, id, g| {
            x.id = id;
            x.guid = g;
        });
        rep.forms_replaced = fs.len();
        f.forms = fs;
    }
    if let Some(v) = given(src, "symbols") {
        let mut ss = serde("symbols", de::de_seq(&v, &de::de_symbol))?;
        keep_by_place(&mut ss, &f.symbols, |x| (x.id, x.guid.clone()), |x, id, g| {
            x.id = id;
            x.guid = g;
        });
        rep.symbols_replaced = ss.len();
        f.symbols = ss;
    }
    if !from_file {
        if let Some(patch) = patch_of(src, "form", "form")? {
            let pick = patch_pick(&patch, "form")?;
            let i = f.forms.iter().position(|x| matches(&pick, x.id, &x.guid)).ok_or_else(|| not_of("form", &pick, name))?;
            let v = merged(form_view(&f.forms[i], &f), &patch);
            let mut nf = de::de_form(&v).map_err(|e| format!("{}: form {} of family {:?}: {}", CMD, pick.shown(), name, e))?;
            nf.id = f.forms[i].id;
            nf.guid = f.forms[i].guid.clone();
            if let Some(id) = nf.id {
                rep.forms_patched.push(id);
            }
            f.forms[i] = nf;
        }
        if let Some(patch) = patch_of(src, "symbol", "symbol")? {
            let pick = patch_pick(&patch, "symbol")?;
            let i = f.symbols.iter().position(|x| matches(&pick, x.id, &x.guid)).ok_or_else(|| not_of("symbol", &pick, name))?;
            let v = merged(symbol_value(&f.symbols[i]), &patch);
            let mut ns = de::de_symbol(&v).map_err(|e| format!("{}: symbol {} of family {:?}: {}", CMD, pick.shown(), name, e))?;
            ns.id = f.symbols[i].id;
            ns.guid = f.symbols[i].guid.clone();
            if let Some(id) = ns.id {
                rep.symbols_patched.push(id);
            }
            f.symbols[i] = ns;
        }
        for (key, what) in [("delete_form", "form"), ("delete_symbol", "symbol")] {
            let Some(Value::Arr(a)) = given(src, key) else { continue };
            for x in &a {
                let pick = pick_of(x)
                    .ok_or_else(|| format!("{}: `{}` needs the {}'s `id` or `guid`, not {}", CMD, what, what, x.to_compact()))?;
                if what == "form" {
                    let i = f.forms.iter().position(|y| matches(&pick, y.id, &y.guid)).ok_or_else(|| not_of(what, &pick, name))?;
                    if let Some(id) = f.forms[i].id {
                        rep.forms_deleted.push(id);
                    }
                    f.forms.remove(i);
                } else {
                    let i = f.symbols.iter().position(|y| matches(&pick, y.id, &y.guid)).ok_or_else(|| not_of(what, &pick, name))?;
                    if let Some(id) = f.symbols[i].id {
                        rep.symbols_deleted.push(id);
                    }
                    f.symbols.remove(i);
                }
            }
        }
    }
    if let Some(v) = given(src, "connectors") {
        let mut cs = serde("connectors", de::de_seq(&v, &de::de_connector))?;
        keep_by_place(&mut cs, &f.connectors, |x| (x.id, x.guid.clone()), |x, id, g| {
            x.id = id;
            x.guid = g;
        });
        f.connectors = cs;
    }
    if let Some(o) = opt_text(src, CMD, "operation")? {
        let t = o.trim().to_lowercase();
        if t.is_empty() {
            f.operation = None;
        } else if OPERATIONS.contains(&t.as_str()) {
            f.operation = Some(t);
        } else {
            return Err(format!("{}: `operation` is one of {}, not `{}`", CMD, OPERATIONS.join(", "), o));
        }
    }
    if let Some(k) = opt_text(src, CMD, "kind")? {
        let t = k.trim();
        f.kind = if t.is_empty() { None } else { Some(t.to_string()) };
    }
    if let Some(v) = given(src, "types") {
        for (t, vals) in serde("types", de::de_types(&v))? {
            match vals {
                None => f.remove_type(&t),
                Some(vals) => {
                    let mut cur = f.type_values(&t).cloned().unwrap_or_default();
                    for (k, v) in vals.iter() {
                        if v.is_null() {
                            cur.remove(k);
                        } else {
                            cur.insert_sorted(k, v.clone());
                        }
                    }
                    f.set_type(&t, cur);
                }
            }
        }
    }
    let mut name = name.to_string();
    if !from_file {
        if let Some(r) = opt_text(src, CMD, "rename")? {
            let t = r.trim();
            if t.is_empty() {
                return Err(format!("{}: `rename` needs a name", CMD));
            }
            name = t.to_string();
        }
    }
    Ok((f, name))
}

/// Names as a dry run lists them: in name order.
fn names(mut v: Vec<String>) -> Value {
    v.sort();
    v.dedup();
    Value::Arr(v.into_iter().map(Value::Str).collect())
}

fn ids_value(v: &[u64]) -> Value {
    Value::Arr(v.iter().map(|x| Value::u(*x)).collect())
}

/// What a dry run says it would do.
fn changes(old: Option<&Family>, new: &Family, rep: &Report, rename: Option<&str>, deleted: bool) -> Value {
    let empty = Family::default();
    let o = old.unwrap_or(&empty);
    let (mut padd, mut pchg, mut prem) = (Vec::new(), Vec::new(), Vec::new());
    for p in &new.parameters {
        match o.param(&p.name) {
            None => padd.push(p.name.clone()),
            Some(op) => {
                if op != p {
                    pchg.push(p.name.clone())
                }
            }
        }
    }
    for p in &o.parameters {
        if new.param(&p.name).is_none() {
            prem.push(p.name.clone());
        }
    }
    let (mut tadd, mut tchg, mut trem) = (Vec::new(), Vec::new(), Vec::new());
    for (t, vals) in &new.types {
        match o.type_values(t) {
            None => tadd.push(t.clone()),
            Some(ov) => {
                if ov != vals {
                    tchg.push(t.clone())
                }
            }
        }
    }
    for (t, _) in &o.types {
        if new.type_values(t).is_none() {
            trem.push(t.clone());
        }
    }
    let part = |del: &[u64], pat: &[u64], rep: usize| crate::jobj! {"deleted" => ids_value(del), "patched" => ids_value(pat), "replaced" => rep};
    crate::jobj! {
        "deleted" => deleted,
        "forms" => part(&rep.forms_deleted, &rep.forms_patched, rep.forms_replaced),
        "parameters" => crate::jobj! {"added" => names(padd), "changed" => names(pchg), "removed" => names(prem)},
        "rename" => rename.map(Value::s).unwrap_or(Value::Null),
        "symbols" => part(&rep.symbols_deleted, &rep.symbols_patched, rep.symbols_replaced),
        "types" => crate::jobj! {"added" => names(tadd), "changed" => names(tchg), "removed" => names(trem)},
    }
}

fn all_values(fam: &Family) -> Value {
    let mut m = Map::new();
    for (t, _) in &fam.types {
        let ev = Eval::new(fam, Some(t), None, None);
        let v = ev.values().map(|vals| values_view(&vals)).unwrap_or_else(|_| Value::obj());
        m.insert_sorted(t, v);
    }
    Value::Obj(m)
}

fn warnings_value(w: &[String]) -> Value {
    Value::Arr(w.iter().map(|s| Value::s(s)).collect())
}

/// The family file at `path`: its object.
fn read_file(path: &str) -> R<Value> {
    let text = std::fs::read(path).map_err(|e| format!("{}: {}: {}", CMD, path, crate::commands::io_err(&e)))?;
    let v = crate::json::parse_bytes(&text).map_err(|e| format!("{}: {} is not a family: {}", CMD, path, e))?;
    if !matches!(v, Value::Obj(_)) {
        return Err(format!("{}: {} is not a family: it isn't an object", CMD, path));
    }
    Ok(v)
}

fn list(pr: &Project) -> Value {
    let mut out = Vec::new();
    if let Some(fams) = pr.section("families") {
        let mut names: Vec<&String> = fams.keys().collect();
        names.sort();
        for n in names {
            let f = fams.get(n).unwrap();
            let count = |k: &str| f.get(k).and_then(|x| x.as_arr()).map(|a| a.len()).unwrap_or(0);
            out.push(crate::jobj! {
                "category" => f.get("category").cloned().unwrap_or(Value::Null),
                "forms" => count("forms"),
                "name" => n.as_str(),
                "symbols" => count("symbols"),
                "types" => f.get("types").and_then(|t| t.as_obj()).map(|t| t.len()).unwrap_or(0),
            });
        }
    }
    crate::jobj! {"families" => Value::Arr(out)}
}

/// The elements (components, doors, windows) of a family, by id.
fn users(pr: &Project, name: &str) -> Vec<u64> {
    let Some(g) = pr.lib_guid(ids::FAMILY, name) else { return Vec::new() };
    pr.elements.iter().filter(|(_, e)| e.get("family").and_then(|f| f.as_str()) == Some(g.as_str())).map(|(id, _)| *id).collect()
}

/// Runs `family`: its own refusals cut at 2000 characters, what the family's rules (and its
/// elements') say whole.
pub fn run(s: &mut Session, p0: &Value) -> R<Value> {
    WHOLE.with(|w| w.set(false));
    match run_inner(s, p0) {
        Ok(v) => Ok(v),
        Err(e) if WHOLE.with(|w| w.get()) => Err(e),
        Err(e) => Err(crate::structure::types::clip(e)),
    }
}

thread_local! {
    /// The refusal being made is the family's rules', said whole.
    static WHOLE: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

fn whole(e: String) -> String {
    WHOLE.with(|w| w.set(true));
    e
}

fn run_inner(s: &mut Session, p0: &Value) -> R<Value> {
    let p = crate::structure::types::names_for_guids(&s.project, p0);
    let path = opt_text(&p, CMD, "path")?;
    let file = match &path {
        Some(path) => Some(read_file(path)?),
        None => None,
    };
    let name = match (p.get("name").filter(|v| !v.is_null()), &file) {
        (Some(_), _) | (None, None) => opt_text(&p, CMD, "name")?,
        (None, Some(f)) => match f.get("name").filter(|v| !v.is_null()) {
            Some(_) => opt_text(f, CMD, "name")?,
            None => Some(
                std::path::Path::new(path.as_deref().unwrap_or(""))
                    .file_stem()
                    .map(|s| s.to_string_lossy().to_string())
                    .unwrap_or_default(),
            ),
        },
    };
    let name = name.map(|n| n.trim().to_string()).unwrap_or_default();
    let pr = &s.project;
    let save = if file.is_none() { opt_text(&p, CMD, "save")? } else { None };
    if let Some(sp) = save {
        if name.is_empty() {
            return Err(format!("{}: `name` is required: the family to save", CMD));
        }
        if !exists(pr, &name) {
            return Err(format!("{}: there's no family `{}` to save", CMD, name));
        }
        if opt_bool(&p, CMD, "dry_run")?.unwrap_or(false) {
            return Ok(crate::jobj! {"dry_run" => true, "name" => name.as_str(), "ok" => true, "path" => sp.as_str(), "saved" => false});
        }
        let mut v = view_of(pr, &name).unwrap_or_else(Value::obj);
        v.set("name", Value::s(&name));
        std::fs::write(&sp, v.sorted().to_pretty()).map_err(|e| format!("{}: {}: {}", CMD, sp, crate::commands::io_err(&e)))?;
        return Ok(crate::jobj! {"path" => sp.as_str(), "saved" => name.as_str()});
    }
    if name.is_empty() {
        let delete = if file.is_none() { opt_bool(&p, CMD, "delete")?.unwrap_or(false) } else { false };
        if delete || (file.is_none() && given(&p, "rename").is_some()) {
            return Err(format!("{}: `name` is required: the family's", CMD));
        }
        return Ok(list(pr));
    }
    let dry = opt_bool(&p, CMD, "dry_run")?.unwrap_or(false);
    let delete = if file.is_none() { opt_bool(&p, CMD, "delete")?.unwrap_or(false) } else { false };
    if delete {
        if !exists(pr, &name) {
            return Err(format!("{}: there's no family `{}`", CMD, name));
        }
        let us = users(pr, &name);
        if !us.is_empty() {
            let list: Vec<String> = us.iter().map(|x| x.to_string()).collect();
            return Err(format!("{}: elements {} are of `{}`; delete them first", CMD, list.join(", "), name));
        }
        if dry {
            let f = family_of(pr, &name).unwrap_or_default();
            let ch = changes(Some(&f), &f, &Report::default(), None, true);
            return Ok(crate::jobj! {"changes" => ch, "dry_run" => true, "name" => name.as_str(), "ok" => true, "warnings" => Value::Arr(Vec::new())});
        }
        super::remove_family(&mut s.project, &name);
        crate::structure::common::mark_step();
        return Ok(crate::jobj! {"deleted" => name.as_str(), "warnings" => Value::Arr(Vec::new())});
    }
    let src = file.as_ref().unwrap_or(&p);
    let keys: &[&str] = if file.is_some() { FILE_KEYS } else { CHANGE_KEYS };
    let is_change = keys.iter().any(|k| given(src, k).is_some());
    let old = family_of(pr, &name);
    if !is_change && old.is_none() {
        return Err(format!("{}: there's no family `{}`", CMD, name));
    }
    if !is_change && !dry {
        let f = old.unwrap();
        let w = super::check::warnings(&f);
        return Ok(crate::jobj! {"family" => f.view(), "name" => name.as_str(), "values" => all_values(&f), "warnings" => warnings_value(&w)});
    }
    let mut rep = Report::default();
    let (new, new_name) = apply(old.as_ref(), &name, src, file.is_some(), &mut rep)?;
    if new_name != name && exists(pr, &new_name) {
        return Err(format!("{}: there's a family `{}` already", CMD, new_name));
    }
    let (errors, warnings) = problems(&new, &new_name, &|m: &str| has_material(pr, m));
    if !errors.is_empty() {
        return Err(whole(refusal(&new_name, &errors, &warnings)));
    }
    if dry {
        let renamed = if file.is_none() && given(src, "rename").is_some() { Some(new_name.as_str()) } else { None };
        let ch = changes(old.as_ref(), &new, &rep, renamed, false);
        return Ok(crate::jobj! {
            "changes" => ch,
            "dry_run" => true,
            "family" => new.view(),
            "name" => new_name.as_str(),
            "ok" => true,
            "values" => all_values(&new),
            "warnings" => warnings_value(&warnings),
        });
    }
    // what the model's rules say of the family's components once it's changed
    crate::structure::component::check_family_users(pr, &name, &new).map_err(whole)?;
    let reply = crate::jobj! {"family" => new.view(), "name" => new_name.as_str(), "warnings" => warnings_value(&warnings)};
    let pr = &mut s.project;
    if new_name != name {
        super::rename_family(pr, &name, &new_name);
    }
    put_family(pr, &new_name, &new);
    crate::structure::common::mark_step();
    Ok(reply)
}
