//! Intl.ListFormat.
//!
//! Slots: `__lf: true`, `__lf_locale`, `__lf_type`, `__lf_style`.
//!
//! The original only has list data for Spanish (a slot locale equal to "es"
//! or starting with "es-"); every other locale uses its English patterns:
//!
//! | type        | style        | 2 items      | joiner     | last joiner |
//! |-------------|--------------|--------------|------------|-------------|
//! | conjunction | long         | `A and B`    | `, `       | `, and `    |
//! | conjunction | short        | `A & B`      | `, `       | `, & `      |
//! | conjunction | narrow       | `A B`        | ` `        | ` `         |
//! | disjunction | long/short/narrow | `A or B` | `, `     | `, or `     |
//! | unit        | narrow       | `A B`        | ` `        | ` `         |
//! | otherwise   |              | `A, B`       | `, `       | `, `        |
//!
//! Spanish: conjunction (any style) `A y B` / `A, B y C`; disjunction (any
//! style) `A o B` / `A, B o C`; unit long like conjunction, unit short
//! `A y B` / `A, B, C`, unit narrow space-separated, anything else `, `.
//! There is no "y" -> "e" / "o" -> "u" adjustment.

use super::*;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    define_class(
        vm,
        intl,
        "ListFormat",
        0,
        lf_ctor,
        &[
            Member::Method("format", 1, lf_format),
            Member::Method("formatToParts", 1, lf_format_to_parts),
            Member::Method("resolvedOptions", 0, lf_resolved_options),
        ],
        true,
    );
}

fn lf_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_new(vm, a, "ListFormat")?;
    let requested = locale_list(vm, &a.arg(0))?;
    let opts = get_options(vm, &a.arg(1), OptionsMode::Strict)?;
    read_locale_matcher(vm, &opts)?;
    let ty = get_opt_str(vm, &opts, "type", &["conjunction", "disjunction", "unit"])?
        .unwrap_or_else(|| "conjunction".to_string());
    let style = get_opt_str(vm, &opts, "style", &["long", "short", "narrow"])?.unwrap_or_else(|| "long".to_string());
    let r = resolve_locale(&requested);
    let o = alloc_instance(vm, a)?;
    set_slot(&o, "__lf", Value::Bool(true));
    set_slot(&o, "__lf_locale", Value::str(&r.base));
    set_slot(&o, "__lf_type", Value::str(&ty));
    set_slot(&o, "__lf_style", Value::str(&style));
    Ok(Value::Obj(o))
}

/// (two-item joiner, middle joiner, last joiner)
type Joiners = (&'static str, &'static str, &'static str);

const COMMAS: Joiners = (", ", ", ", ", ");
const SPACES: Joiners = (" ", " ", " ");

fn joiners(locale: Option<&str>, ty: Option<&str>, style: Option<&str>) -> Joiners {
    let es = matches!(locale, Some(l) if l == "es" || l.starts_with("es-"));
    if es {
        return match ty {
            Some("conjunction") => (" y ", ", ", " y "),
            Some("disjunction") => (" o ", ", ", " o "),
            Some("unit") => match style {
                Some("long") => (" y ", ", ", " y "),
                Some("short") => (" y ", ", ", ", "),
                Some("narrow") => SPACES,
                _ => COMMAS,
            },
            _ => COMMAS,
        };
    }
    match (ty, style) {
        (Some("conjunction"), Some("long")) => (" and ", ", ", ", and "),
        (Some("conjunction"), Some("short")) => (" & ", ", ", ", & "),
        (Some("conjunction"), Some("narrow")) => SPACES,
        (Some("disjunction"), Some("long" | "short" | "narrow")) => (" or ", ", ", ", or "),
        (Some("unit"), Some("narrow")) => SPACES,
        _ => COMMAS,
    }
}

/// StringListFromIterable (undefined -> empty list).  Elements are kept as
/// UTF-16 strings (lone surrogates survive).
fn string_list(vm: &mut Vm, v: &Value) -> JsResult<Vec<JsStr>> {
    match v {
        Value::Undefined => return Ok(Vec::new()),
        // the original reports the failed Symbol.iterator lookup this way
        Value::Null => return vm.throw_type("cannot read property ' 1' of null"),
        _ => {}
    }
    let (it, next) = vm.get_iterator(v)?;
    let itv = Value::Obj(it);
    let mut out = Vec::new();
    while let Some(x) = vm.iter_step(&itv, &next)? {
        match x {
            Value::Str(s) => out.push(s),
            _ => {
                let _ = vm.iterator_close(&itv);
                return vm.throw_type("Intl.ListFormat list elements must be strings");
            }
        }
    }
    Ok(out)
}

fn format_parts(o: &Obj, items: Vec<JsStr>) -> Vec<(&'static str, JsStr)> {
    let locale = slot_str(o, "__lf_locale");
    let ty = slot_str(o, "__lf_type");
    let style = slot_str(o, "__lf_style");
    let (two, middle, last) = joiners(locale.as_deref(), ty.as_deref(), style.as_deref());
    let n = items.len();
    let mut parts = Vec::with_capacity(n * 2);
    for (i, s) in items.into_iter().enumerate() {
        if i > 0 {
            let sep = if n == 2 {
                two
            } else if i == n - 1 {
                last
            } else {
                middle
            };
            parts.push(("literal", JsStr::from_str(sep)));
        }
        parts.push(("element", s));
    }
    parts
}

fn lf_format(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.this, "__lf")?;
    let items = string_list(vm, &a.arg(0))?;
    let parts = format_parts(&o, items);
    let mut units: Vec<u16> = Vec::new();
    for (_, s) in &parts {
        units.extend_from_slice(s.units());
    }
    Ok(Value::Str(JsStr::from_units(units)))
}

fn lf_format_to_parts(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.this, "__lf")?;
    let items = string_list(vm, &a.arg(0))?;
    let parts = format_parts(&o, items);
    let mut out = Vec::with_capacity(parts.len());
    for (kind, s) in parts {
        let p = vm.new_object();
        p.set_str("type", Value::str(kind), WEC);
        p.set_str("value", Value::Str(s), WEC);
        out.push(Value::Obj(p));
    }
    Ok(Value::Obj(vm.new_array(out)))
}

fn lf_resolved_options(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.this, "__lf")?;
    let r = vm.new_object();
    for (key, slot_name) in [("locale", "__lf_locale"), ("type", "__lf_type"), ("style", "__lf_style")] {
        if let Some(v) = slot(&o, slot_name) {
            if !v.is_undefined() {
                r.set_str(key, v, WEC);
            }
        }
    }
    Ok(Value::Obj(r))
}
