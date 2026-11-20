//! Temporal.PlainTime

use super::dur::*;
use super::fields::*;
use super::iso::*;
use super::plain_date::get_difference_settings;
use super::*;

pub fn setup(vm: &mut Vm, t: &Obj) {
    let (ctor, proto) = make_class(vm, K::PlainTime, "PlainTime", 0, construct);
    def_method(vm, &ctor, "from", 1, from);
    def_method(vm, &ctor, "compare", 2, compare);
    def_getter(vm, &proto, "hour", get_hour);
    def_getter(vm, &proto, "minute", get_minute);
    def_getter(vm, &proto, "second", get_second);
    def_getter(vm, &proto, "millisecond", get_millisecond);
    def_getter(vm, &proto, "microsecond", get_microsecond);
    def_getter(vm, &proto, "nanosecond", get_nanosecond);
    def_method(vm, &proto, "toString", 0, to_string);
    def_method(vm, &proto, "toJSON", 0, to_json);
    def_value_of(vm, &proto, K::PlainTime);
    def_method(vm, &proto, "equals", 1, equals);
    def_method(vm, &proto, "with", 1, with);
    def_method(vm, &proto, "add", 1, add);
    def_method(vm, &proto, "subtract", 1, subtract);
    def_method(vm, &proto, "until", 1, until);
    def_method(vm, &proto, "since", 1, since);
    def_method(vm, &proto, "round", 1, round);
    finish_class(vm, K::PlainTime, &ctor, &proto);
    t.set_prop(PropKey::from_str("PlainTime"), Value::Obj(ctor), WC);
}

/// ParseTemporalTimeString with the original's messages
pub fn parse_time_string(s: &str) -> TRes<Time> {
    if let Some(p) = parse::parse_date_time(s) {
        if p.z {
            return rerr("UTC designator not valid for PlainTime");
        }
        return match p.time {
            Some(t) => Ok(t),
            None => rerr("no time in PlainTime string"),
        };
    }
    if let Some(p) = parse::parse_time_only(s) {
        if p.z {
            return rerr("UTC designator not valid for PlainTime");
        }
        if parse::time_is_ambiguous(s, &p) {
            return rerr("ambiguous time string requires a T designator");
        }
        return Ok(p.time.unwrap_or_default());
    }
    rerr("invalid PlainTime string")
}

/// ToTemporalTime
pub fn to_temporal_time(vm: &mut Vm, item: &Value, options: &Value) -> JsResult<Time> {
    if let Value::Obj(o) = item {
        match slot_of(item) {
            Some(Slot::Time(t)) => {
                let opts = get_options_object_strict(vm, options)?;
                get_overflow(vm, &opts)?;
                return Ok(t);
            }
            Some(Slot::DateTime(dt, _)) => {
                let opts = get_options_object_strict(vm, options)?;
                get_overflow(vm, &opts)?;
                return Ok(dt.time);
            }
            Some(Slot::Zoned(ns, tz, _)) => {
                let dt = tz.datetime_for(ns);
                let opts = get_options_object_strict(vm, options)?;
                get_overflow(vm, &opts)?;
                return Ok(dt.time);
            }
            _ => {}
        }
        let r = match to_time_record(vm, o)? {
            Some(r) => r,
            None => return vm.throw_type("object has no time fields"),
        };
        let opts = get_options_object_strict(vm, options)?;
        let overflow = get_overflow(vm, &opts)?;
        let t = tr!(
            vm,
            regulate_time(
                r.hour.unwrap_or(0.0),
                r.minute.unwrap_or(0.0),
                r.second.unwrap_or(0.0),
                r.millisecond.unwrap_or(0.0),
                r.microsecond.unwrap_or(0.0),
                r.nanosecond.unwrap_or(0.0),
                overflow
            )
        );
        return Ok(t);
    }
    let s = match item {
        Value::Str(s) => s.to_rust_string(),
        _ => return vm.throw_type("cannot convert to Temporal.PlainTime"),
    };
    let t = tr!(vm, parse_time_string(&s));
    let opts = get_options_object_strict(vm, options)?;
    get_overflow(vm, &opts)?;
    Ok(t)
}

/// ToTimeRecordOrMidnight
pub fn to_time_or_midnight(vm: &mut Vm, v: &Value) -> JsResult<Time> {
    if v.is_undefined() {
        return Ok(Time::MIDNIGHT);
    }
    to_temporal_time(vm, v, &Value::Undefined)
}

/// IsValidTime on float64 integers
pub fn valid_time_f(f: &[f64; 6]) -> bool {
    let max = [23.0, 59.0, 59.0, 999.0, 999.0, 999.0];
    f.iter().zip(max.iter()).all(|(v, m)| *v >= 0.0 && v <= m)
}

pub fn time_from_f(f: &[f64; 6]) -> Time {
    Time {
        hour: f[0] as u8,
        minute: f[1] as u8,
        second: f[2] as u8,
        millisecond: f[3] as u16,
        microsecond: f[4] as u16,
        nanosecond: f[5] as u16,
    }
}

fn construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = match &a.new_target {
        Some(nt) => nt.clone(),
        None => return vm.throw_type("constructor requires 'new'"),
    };
    let mut f = [0.0f64; 6];
    for (i, v) in f.iter_mut().enumerate() {
        let x = a.arg(i);
        if !x.is_undefined() {
            *v = to_integer_with_truncation(vm, &x)?;
        }
    }
    if !valid_time_f(&f) {
        return vm.throw_range("ISO time field is out of range");
    }
    create_time(vm, time_from_f(&f), Some(&nt))
}

fn from(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t = to_temporal_time(vm, &a.arg(0), &a.arg(1))?;
    create_time(vm, t, None)
}

fn compare(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let one = to_temporal_time(vm, &a.arg(0), &Value::Undefined)?;
    let two = to_temporal_time(vm, &a.arg(1), &Value::Undefined)?;
    Ok(num(one.cmp(&two) as i32 as f64))
}

fn get_hour(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_time(vm, a)?.hour as f64))
}
fn get_minute(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_time(vm, a)?.minute as f64))
}
fn get_second(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_time(vm, a)?.second as f64))
}
fn get_millisecond(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_time(vm, a)?.millisecond as f64))
}
fn get_microsecond(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_time(vm, a)?.microsecond as f64))
}
fn get_nanosecond(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_time(vm, a)?.nanosecond as f64))
}

/// RoundTime: returns (day carry, time)
pub fn round_time(t: &Time, increment: i128, unit: Unit, mode: RoundingMode) -> (i64, Time) {
    let q: i128 = match unit {
        Unit::Day | Unit::Hour => t.to_ns(),
        Unit::Minute => t.to_ns() - t.hour as i128 * NS_PER_HOUR,
        Unit::Second => t.to_ns() - t.hour as i128 * NS_PER_HOUR - t.minute as i128 * NS_PER_MINUTE,
        Unit::Millisecond => t.sub_second_ns() as i128,
        Unit::Microsecond => t.microsecond as i128 * 1000 + t.nanosecond as i128,
        _ => t.nanosecond as i128,
    };
    let unit_len = unit.ns();
    let result = round_to_increment(q, increment * unit_len, mode) / unit_len;
    let base: i128 = match unit {
        Unit::Day => return (result as i64, Time::MIDNIGHT),
        Unit::Hour => 0,
        Unit::Minute => t.hour as i128 * NS_PER_HOUR,
        Unit::Second => t.hour as i128 * NS_PER_HOUR + t.minute as i128 * NS_PER_MINUTE,
        Unit::Millisecond => t.to_ns() - t.sub_second_ns() as i128,
        Unit::Microsecond => t.to_ns() - (t.microsecond as i128 * 1000 + t.nanosecond as i128),
        _ => t.to_ns() - t.nanosecond as i128,
    };
    Time::balance(base + result * unit_len)
}

/// Options shared by PlainTime/PlainDateTime/Instant/ZonedDateTime toString:
/// fractionalSecondDigits, roundingMode, smallestUnit.
pub fn read_to_string_rounding(vm: &mut Vm, opts: &Opts) -> JsResult<(Precision, Unit, i128, RoundingMode)> {
    let digits = get_fractional_digits(vm, opts)?;
    let mode = get_rounding_mode(vm, opts, RoundingMode::Trunc)?;
    let su = get_unit_option(vm, opts, "smallestUnit")?;
    let smallest = match su {
        None => None,
        Some(UnitOpt::U(u)) if !u.is_date() && u != Unit::Hour => Some(u),
        Some(UnitOpt::U(_)) => return vm.throw_range("smallestUnit must be a time unit"),
        Some(UnitOpt::Auto) => return vm.throw_range("invalid smallestUnit"),
    };
    let (p, u, inc) = seconds_precision(smallest, digits);
    Ok((p, u, inc, mode))
}

fn to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t = this_time(vm, a)?;
    let opts = get_options_object(vm, &a.arg(0))?;
    let (p, u, inc, mode) = read_to_string_rounding(vm, &opts)?;
    let (_, r) = round_time(&t, inc, u, mode);
    Ok(Value::str(&fmt_time(&r, p)))
}

fn to_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t = this_time(vm, a)?;
    Ok(Value::str(&fmt_time(&t, Precision::Auto)))
}

fn equals(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t = this_time(vm, a)?;
    let o = to_temporal_time(vm, &a.arg(0), &Value::Undefined)?;
    Ok(Value::Bool(t == o))
}

fn with(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t = this_time(vm, a)?;
    let obj = check_partial(vm, &a.arg(0))?;
    let p = match to_time_record(vm, &obj)? {
        Some(p) => p,
        None => return vm.throw_type("with() requires at least one time field"),
    };
    let opts = get_options_object(vm, &a.arg(1))?;
    let overflow = get_overflow(vm, &opts)?;
    let r = tr!(
        vm,
        regulate_time(
            p.hour.unwrap_or(t.hour as f64),
            p.minute.unwrap_or(t.minute as f64),
            p.second.unwrap_or(t.second as f64),
            p.millisecond.unwrap_or(t.millisecond as f64),
            p.microsecond.unwrap_or(t.microsecond as f64),
            p.nanosecond.unwrap_or(t.nanosecond as f64),
            overflow
        )
    );
    create_time(vm, r, None)
}

fn add_sub(vm: &mut Vm, a: &Args, negate: bool) -> JsResult<Value> {
    let t = this_time(vm, a)?;
    let mut d = to_duration(vm, &a.arg(0))?;
    if negate {
        d = d.negated();
    }
    let i = to_internal(&d);
    let (_, r) = Time::balance(t.to_ns() + i.time);
    create_time(vm, r, None)
}

fn add(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    add_sub(vm, a, false)
}

fn subtract(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    add_sub(vm, a, true)
}

fn difference(vm: &mut Vm, a: &Args, since: bool) -> JsResult<Value> {
    let t = this_time(vm, a)?;
    let other = to_temporal_time(vm, &a.arg(0), &Value::Undefined)?;
    let opts = get_options_object(vm, &a.arg(1))?;
    let s = get_difference_settings(vm, since, &opts, UnitGroup::Time, &[], Unit::Nanosecond, Unit::Hour)?;
    let td = difference_time(&t, &other);
    let td = tr!(vm, round_time_duration(td, s.increment as i128, s.smallest, s.mode));
    let mut r = tr!(vm, from_internal(&IDur { date: DateDur::default(), time: td }, s.largest));
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

/// Shared argument handling of round(): string shorthand or options object.
/// `undefined_msg` = message for a missing argument (None: the generic one).
pub fn round_options(vm: &mut Vm, v: &Value, undefined_msg: Option<&str>) -> JsResult<Opts> {
    match v {
        Value::Str(_) => Ok(string_shorthand(vm, "smallestUnit", v.clone())),
        Value::Obj(o) => Ok(Some(o.clone())),
        Value::Undefined if undefined_msg.is_some() => vm.throw_type(undefined_msg.unwrap_or_default()),
        _ => vm.throw_type("options must be an object or a string"),
    }
}

fn round(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t = this_time(vm, a)?;
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
    let max = unit.max_increment().unwrap_or(1);
    tr!(vm, validate_increment(increment, max, false));
    let (_, r) = round_time(&t, increment, unit, mode);
    create_time(vm, r, None)
}
