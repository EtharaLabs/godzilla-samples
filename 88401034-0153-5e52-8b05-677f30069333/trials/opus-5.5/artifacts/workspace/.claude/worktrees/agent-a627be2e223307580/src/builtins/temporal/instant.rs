//! Temporal.Instant

use super::calendar::Cal;
use super::dur::*;
use super::fields::*;
use super::iso::*;
use super::plain_date::get_difference_settings;
use super::plain_time::round_options;
use super::*;

pub fn setup(vm: &mut Vm, t: &Obj) {
    let (ctor, proto) = make_class(vm, K::Instant, "Instant", 1, construct);
    def_method(vm, &ctor, "from", 1, from);
    def_method(vm, &ctor, "fromEpochMilliseconds", 1, from_epoch_milliseconds);
    def_method(vm, &ctor, "fromEpochNanoseconds", 1, from_epoch_nanoseconds);
    def_method(vm, &ctor, "compare", 2, compare);
    def_getter(vm, &proto, "epochMilliseconds", get_epoch_milliseconds);
    def_getter(vm, &proto, "epochNanoseconds", get_epoch_nanoseconds);
    def_method(vm, &proto, "toString", 0, to_string);
    def_value_of(vm, &proto, K::Instant);
    def_method(vm, &proto, "toJSON", 0, to_json);
    def_method(vm, &proto, "equals", 1, equals);
    def_method(vm, &proto, "toZonedDateTimeISO", 1, to_zoned_date_time_iso);
    def_method(vm, &proto, "add", 1, add);
    def_method(vm, &proto, "subtract", 1, subtract);
    def_method(vm, &proto, "round", 1, round);
    def_method(vm, &proto, "until", 1, until);
    def_method(vm, &proto, "since", 1, since);
    finish_class(vm, K::Instant, &ctor, &proto);
    t.set_prop(PropKey::from_str("Instant"), Value::Obj(ctor), WC);
}

const MSG_INVALID: &str = "invalid Instant string";

/// Parse an Instant string
pub fn parse_instant_string(s: &str) -> TRes<i128> {
    let p = match parse::parse_date_time(s) {
        Some(p) => p,
        None => return rerr(MSG_INVALID),
    };
    let t = match p.time {
        Some(t) => t,
        None => return rerr(MSG_INVALID),
    };
    let offset = if p.z {
        0
    } else {
        match &p.offset {
            Some(o) => o.ns,
            None => return rerr(MSG_INVALID),
        }
    };
    let d = IsoDate::new(p.year.unwrap_or(0), p.month, p.day.unwrap_or(1));
    let b = balance_datetime(&d, &t, -offset);
    if !days_in_range(&b.date) {
        return rerr(MSG_INVALID);
    }
    let ns = utc_epoch_ns_dt(&b);
    if !epoch_ns_valid(ns) {
        return rerr(MSG_INVALID);
    }
    Ok(ns)
}

/// ToTemporalInstant
pub fn to_temporal_instant(vm: &mut Vm, item: &Value) -> JsResult<i128> {
    let mut v = item.clone();
    if let Value::Obj(_) = item {
        match slot_of(item) {
            Some(Slot::Instant(ns)) | Some(Slot::Zoned(ns, _, _)) => return Ok(ns),
            _ => {}
        }
        v = vm.to_primitive(item, crate::ops::Hint::String)?;
    }
    let s = match &v {
        Value::Str(s) => s.to_rust_string(),
        _ => return vm.throw_type("cannot convert to Temporal.Instant"),
    };
    Ok(tr!(vm, parse_instant_string(&s)))
}

/// ToBigInt for epochNanoseconds arguments (the original's messages)
fn to_epoch_ns_bigint(vm: &mut Vm, v: &Value) -> JsResult<i128> {
    let b = match v {
        Value::BigInt(b) => (**b).clone(),
        Value::Bool(b) => crate::bigint::BigInt::from_i64(*b as i64),
        Value::Str(s) => match crate::bigint::BigInt::parse(s.units()) {
            Some(b) if !s.to_rust_string().trim().is_empty() => b,
            _ => return vm.throw_syntax("cannot convert string to a BigInt"),
        },
        _ => return vm.throw_type("epochNanoseconds must be a BigInt"),
    };
    match bigint_to_i128(&b) {
        Some(ns) if epoch_ns_valid(ns) => Ok(ns),
        _ => vm.throw_range(MSG_INSTANT_RANGE),
    }
}

fn construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = match &a.new_target {
        Some(nt) => nt.clone(),
        None => return vm.throw_type("constructor requires 'new'"),
    };
    let ns = to_epoch_ns_bigint(vm, &a.arg(0))?;
    create_instant(vm, ns, Some(&nt))
}

fn from(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ns = to_temporal_instant(vm, &a.arg(0))?;
    create_instant(vm, ns, None)
}

fn from_epoch_milliseconds(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let n = vm.to_number(&a.arg(0))?;
    if !n.is_finite() || n.trunc() != n {
        return vm.throw_range("epochMilliseconds must be an integer");
    }
    if n.abs() > 1e20 {
        return vm.throw_range(MSG_INSTANT_RANGE);
    }
    create_instant(vm, n as i128 * 1_000_000, None)
}

fn from_epoch_nanoseconds(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ns = to_epoch_ns_bigint(vm, &a.arg(0))?;
    create_instant(vm, ns, None)
}

fn compare(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let one = to_temporal_instant(vm, &a.arg(0))?;
    let two = to_temporal_instant(vm, &a.arg(1))?;
    Ok(num(one.cmp(&two) as i32 as f64))
}

fn get_epoch_milliseconds(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ns = this_instant(vm, a)?;
    Ok(num(ns.div_euclid(1_000_000) as f64))
}

fn get_epoch_nanoseconds(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ns = this_instant(vm, a)?;
    Ok(ns_to_bigint(ns))
}

/// TemporalInstantToString
pub fn instant_to_string(ns: i128, tz: Option<&tz::Tz>, p: Precision) -> String {
    let utc = tz::Tz::utc();
    let out_tz = tz.unwrap_or(&utc);
    let dt = out_tz.datetime_for(ns);
    let s = fmt_datetime(&dt, Cal::Iso8601, p, ShowCalendar::Never);
    match tz {
        None => s + "Z",
        Some(tz) => s + &fmt_offset_rounded(tz.offset_ns(ns)),
    }
}

fn to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ns = this_instant(vm, a)?;
    let opts = match a.arg(0) {
        Value::Undefined => None,
        Value::Obj(o) => Some(o),
        _ => return vm.throw_type("options must be an object or undefined"),
    };
    let digits = get_fractional_digits(vm, &opts)?;
    let mode = get_rounding_mode(vm, &opts, RoundingMode::Trunc)?;
    let su = get_unit_option(vm, &opts, "smallestUnit")?;
    let tzv = opt_get(vm, &opts, "timeZone")?;
    let smallest = match su {
        None => None,
        Some(UnitOpt::U(u)) if !u.is_date() && u != Unit::Hour => Some(u),
        Some(UnitOpt::U(_)) => return vm.throw_range("invalid smallestUnit for toString"),
        Some(UnitOpt::Auto) => return vm.throw_range("invalid smallestUnit"),
    };
    let tz = if tzv.is_undefined() { None } else { Some(to_time_zone_identifier(vm, &tzv)?) };
    let (p, u, inc) = seconds_precision(smallest, digits);
    let r = round_as_if_positive(ns, u.ns() * inc, mode);
    if !epoch_ns_valid(r) {
        return vm.throw_range(MSG_INSTANT_RANGE);
    }
    Ok(Value::str(&instant_to_string(r, tz.as_ref(), p)))
}

fn to_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ns = this_instant(vm, a)?;
    Ok(Value::str(&instant_to_string(ns, None, Precision::Auto)))
}

fn equals(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ns = this_instant(vm, a)?;
    let o = to_temporal_instant(vm, &a.arg(0))?;
    Ok(Value::Bool(ns == o))
}

fn to_zoned_date_time_iso(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ns = this_instant(vm, a)?;
    let tz = to_time_zone_identifier(vm, &a.arg(0))?;
    create_zoned(vm, ns, tz, Cal::Iso8601, None)
}

fn add_sub(vm: &mut Vm, a: &Args, negate: bool) -> JsResult<Value> {
    let ns = this_instant(vm, a)?;
    let mut d = to_duration(vm, &a.arg(0))?;
    if negate {
        d = d.negated();
    }
    if d.default_largest_unit().is_date() {
        let m = if negate { "subtract" } else { "add" };
        return vm.throw_range(format!("Instant.{} does not accept calendar units", m));
    }
    let i = to_internal(&d);
    let r = tr!(vm, add_instant(ns, i.time));
    create_instant(vm, r, None)
}

fn add(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    add_sub(vm, a, false)
}

fn subtract(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    add_sub(vm, a, true)
}

fn difference(vm: &mut Vm, a: &Args, since: bool) -> JsResult<Value> {
    let ns = this_instant(vm, a)?;
    let other = to_temporal_instant(vm, &a.arg(0))?;
    let opts = get_options_object(vm, &a.arg(1))?;
    let s = get_difference_settings(vm, since, &opts, UnitGroup::Time, &[], Unit::Nanosecond, Unit::Second)?;
    let i = tr!(vm, difference_instant(ns, other, s.increment, s.smallest, s.mode));
    let mut r = tr!(vm, from_internal(&i, s.largest));
    if since {
        r = r.negated();
    }
    create_duration(vm, r, None)
}

fn until(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    difference(vm, a, false)
}

fn since(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    difference(vm, a, true)
}

fn round(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ns = this_instant(vm, a)?;
    let opts = round_options(vm, &a.arg(0), None)?;
    let increment = get_rounding_increment(vm, &opts)?;
    let mode = get_rounding_mode(vm, &opts, RoundingMode::HalfExpand)?;
    let su = match opt_unit_string(vm, &opts, "smallestUnit")? {
        Some(s) => Unit::from_str(&s),
        None => None,
    };
    let unit = match su {
        Some(u) if !u.is_date() => u,
        _ => return vm.throw_range("smallestUnit is required"),
    };
    let max = NS_PER_DAY / unit.ns();
    tr!(vm, validate_increment(increment, max, true));
    let r = round_as_if_positive(ns, unit.ns() * increment, mode);
    create_instant(vm, r, None)
}
