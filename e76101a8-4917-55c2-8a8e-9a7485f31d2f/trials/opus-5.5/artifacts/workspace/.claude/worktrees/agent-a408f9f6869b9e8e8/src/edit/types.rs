//! Delete Type and Rename Type: a type of a category, or a family and its types.

use super::common::*;
use super::library_util::*;
use crate::commands::params::opt_text;
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

const GIVE: &str = "give `category` and `type`, or `family`, or `family` and `type`";

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let r = if cid == "delete_type" { delete(s, p) } else { rename(s, p) };
    r.map_err(clip_error)
}

// ---------------------------------------------------------------- delete_type

fn delete(s: &mut Session, p: &Value) -> R<Value> {
    const C: &str = "delete_type";
    let category = opt_text(p, C, "category")?;
    let family = opt_text(p, C, "family")?;
    let typ = opt_text(p, C, "type")?;
    let pr = &mut s.project;
    match (category, family, typ) {
        (Some(c), None, Some(t)) => delete_category_type(pr, &c, &t),
        (None, Some(f), None) => delete_family(pr, &f),
        (None, Some(f), Some(t)) => delete_family_type(pr, &f, &t),
        _ => Err(format!("{}: {}", C, GIVE)),
    }
}

fn deleted(kind: &str, name: &str) -> Value {
    jobj! {"deleted" => jobj! {"kind" => kind, "name" => name}}
}

fn delete_category_type(pr: &mut Project, c: &str, t: &str) -> R<Value> {
    const C: &str = "delete_type";
    let cat = norm_category(c);
    let Some(loc) = locate(pr, &cat, true) else {
        return Err(format!("{}: there is no {} type `{}`", C, cat, t));
    };
    let names = loc_names(pr, &loc);
    if !names.iter().any(|n| n == t) {
        return Err(format!("{}: there is no {} type `{}`{}", C, cat, t, there_are(&names)));
    }
    // text, dimension and filled region types are found where they are, and asked after as if
    // they were among `types`: none of their notes is counted, and nothing is taken away
    let drafting = matches!(loc, Loc::Styles(_));
    let kind = type_kind(&cat);
    if !drafting {
        let guid = pr.lib_guid(&kind, t);
        let n = uses_as_type(pr, guid.as_deref());
        if n > 0 {
            return Err(format!(
                "{}: {} type `{}` is used {}: change or delete what uses it first",
                C,
                cat,
                t,
                times(n)
            ));
        }
    }
    if names.len() == 1 {
        return Err(format!("{}: `{}` is the last {} type: a {} needs one; make another first", C, t, cat, cat));
    }
    if !drafting {
        if let Some(m) = loc_map_mut(pr, &loc) {
            m.remove(t);
        }
        lib_remove(pr, &kind, t);
    }
    Ok(deleted(&format!("{} type", cat), t))
}

fn delete_family(pr: &mut Project, f: &str) -> R<Value> {
    const C: &str = "delete_type";
    let names = family_names(pr);
    if !names.iter().any(|n| n == f) {
        return Err(format!("{}: there is no family `{}`{}", C, f, there_are(&names)));
    }
    let guid = pr.lib_guid("family", f);
    let n = uses_as_family(pr, guid.as_deref());
    if n > 0 {
        return Err(format!("{}: family `{}` is used {}: change or delete what uses it first", C, f, times(n)));
    }
    remove_family(pr, f);
    Ok(deleted("family", f))
}

fn delete_family_type(pr: &mut Project, f: &str, t: &str) -> R<Value> {
    const C: &str = "delete_type";
    let Some(fam) = families(pr).and_then(|m| m.get(f)).cloned() else {
        return Err(format!("{}: there is no family `{}`", C, f));
    };
    let types = family_type_names(&fam);
    if !types.iter().any(|n| n == t) {
        return Err(format!("{}: family `{}` has no type `{}`{}", C, f, t, there_are(&types)));
    }
    let q = qualified(f, t);
    let guid = pr.lib_guid("family-type", &q);
    let n = uses_as_type(pr, guid.as_deref());
    if n > 0 {
        return Err(format!("{}: family type `{}` is used {}: change or delete what uses it first", C, q, times(n)));
    }
    if types.len() == 1 {
        return Err(format!("{}: `{}` is its family's last type: delete the family", C, q));
    }
    remove_family_type(pr, f, t);
    Ok(deleted("family type", &q))
}

// ---------------------------------------------------------------- rename_type

fn rename(s: &mut Session, p: &Value) -> R<Value> {
    const C: &str = "rename_type";
    crate::styles::common::check_keys(p, C, &["category", "family", "type", "name"])?;
    let name = match opt_text(p, C, "name")? {
        Some(n) if !n.trim().is_empty() => n.trim().to_string(),
        _ => return Err(format!("{}: `name` is required: the type's new name", C)),
    };
    let category = opt_text(p, C, "category")?;
    let family = opt_text(p, C, "family")?;
    let typ = opt_text(p, C, "type")?;
    let pr = &mut s.project;
    match (category, family, typ) {
        (Some(c), None, Some(t)) => rename_category_type(pr, &c, &t, &name),
        (None, Some(f), None) => rename_family(pr, &f, &name),
        (None, Some(f), Some(t)) => rename_family_type(pr, &f, &t, &name),
        _ => Err(format!("{}: {}", C, GIVE)),
    }
}

fn renamed(from: &str, kind: &str, to: &str) -> Value {
    jobj! {"renamed" => jobj! {"from" => from, "kind" => kind, "to" => to}}
}

fn rename_category_type(pr: &mut Project, c: &str, t: &str, name: &str) -> R<Value> {
    const C: &str = "rename_type";
    let cat = norm_category(c);
    let Some(loc) = locate(pr, &cat, false) else {
        return Err(format!("{}: there is no {} type `{}`", C, cat, t));
    };
    let names = loc_names(pr, &loc);
    if !names.iter().any(|n| n == t) {
        return Err(format!("{}: there is no {} type `{}`{}", C, cat, t, there_are(&names)));
    }
    let kind_word = format!("{} type", cat);
    if name == t {
        return Ok(renamed(t, &kind_word, t));
    }
    if names.iter().any(|n| n == name) {
        return Err(format!("{}: there's already a {} `{}`", C, kind_word, name));
    }
    if let Some(m) = loc_map_mut(pr, &loc) {
        rename_key_sorted(m, t, name);
    }
    lib_rename(pr, &type_kind(&cat), t, name);
    // the model's rule that a library name isn't a GUID, which the original checks after it
    if is_guid_name(name) {
        return Err(check_error(format!("{} `{}`: a name isn't a GUID; name it otherwise", kind_word, name)));
    }
    Ok(renamed(t, &kind_word, name))
}

fn rename_family_type(pr: &mut Project, f: &str, t: &str, name: &str) -> R<Value> {
    const C: &str = "rename_type";
    let Some(fam) = families(pr).and_then(|m| m.get(f)).cloned() else {
        return Err(format!("{}: there is no family `{}`", C, f));
    };
    let types = family_type_names(&fam);
    if !types.iter().any(|n| n == t) {
        return Err(format!("{}: family `{}` has no type `{}`{}", C, f, t, there_are(&types)));
    }
    if name == t {
        return Ok(renamed(&qualified(f, t), "family type", t));
    }
    if types.iter().any(|n| n == name) {
        return Err(format!("{}: there's already a family type `{}`", C, name));
    }
    if let Some(m) = pr
        .get_mut("families")
        .and_then(|v| v.get_mut(f))
        .and_then(|x| x.get_mut("types"))
        .and_then(|x| x.as_obj_mut())
    {
        rename_key_sorted(m, t, name);
    }
    lib_rename(pr, "family-type", &qualified(f, t), &qualified(f, name));
    Ok(renamed(t, "family type", name))
}

/// A family on its own isn't renamed here: only its own name back, or a name another family
/// has, is answered; anything else isn't found.
fn rename_family(pr: &mut Project, f: &str, name: &str) -> R<Value> {
    const C: &str = "rename_type";
    let names = family_names(pr);
    if !names.iter().any(|n| n == f) {
        return Err(format!("{}: there is no family `{}`{}", C, f, there_are(&names)));
    }
    if name == f {
        return Ok(renamed(f, "family", f));
    }
    if names.iter().any(|n| n == name) {
        return Err(format!("{}: there's already a family `{}`", C, name));
    }
    Err(format!("{}: there is no family `{}`", C, f))
}
