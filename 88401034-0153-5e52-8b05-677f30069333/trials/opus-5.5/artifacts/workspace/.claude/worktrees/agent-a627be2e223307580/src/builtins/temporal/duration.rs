//! Temporal.Duration

use super::calendar::{self, Cal};
use super::dur::*;
use super::fields::*;
use super::iso::*;
use super::plain_time::round_options;
use super::tz::Tz;
use super::zoned::{interpret_offset, OffsetBehaviour};
use super::*;

pub fn setup(vm: &mut Vm, t: &Obj) {
    let (ctor, proto) = make_class(vm, K::Duration, "Duration", 0, construct);
    def_method(vm, &ctor, "from", 1, from);
    def_method(vm, &ctor, "compare", 2, compare);
    def_getter(vm, &proto, "years", get_years);
    def_getter(vm, &proto, "months", get_months);
    def_getter(vm, &proto, "weeks", get_weeks);
    def_getter(vm, &proto, "days", get_days);
    def_getter(vm, &proto, "hours", get_hours);
    def_getter(vm, &proto, "minutes", get_minutes);
    def_getter(vm, &proto, "seconds", get_seconds);
    def_getter(vm, &proto, "milliseconds", get_milliseconds);
    def_getter(vm, &proto, "microseconds", get_microseconds);
    def_getter(vm, &proto, "nanoseconds", get_nanoseconds);
    def_getter(vm, &proto, "sign", get_sign);
    def_getter(vm, &proto, "blank", get_blank);
    def_method(vm, &proto, "toString", 0, to_string);
    def_method(vm, &proto, "toJSON", 0, to_json);
    def_value_of(vm, &proto, K::Duration);
    def_method(vm, &proto, "negated", 0, negated);
    def_method(vm, &proto, "abs", 0, abs);
    def_method(vm, &proto, "with", 1, with);
    def_method(vm, &proto, "add", 1, add);
    def_method(vm, &proto, "subtract", 1, subtract);
    def_method(vm, &proto, "round", 1, round);
    def_method(vm, &proto, "total", 1, total);
    finish_class(vm, K::Duration, &ctor, &proto);
    t.set_prop(PropKey::from_str("Duration"), Value::Obj(ctor), WC);
}

fn construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = match &a.new_target {
        Some(nt) => nt.clone(),
        None => return vm.throw_type("constructor requires 'new'"),
    };
    let mut f = [0.0f64; 10];
    for (i, v) in f.iter_mut().enumerate() {
        let x = a.arg(i);
        if !x.is_undefined() {
            *v = to_integer_if_integral(vm, &x)?;
        }
    }
    create_duration(vm, Dur::from_fields(f), Some(&nt))
}

fn from(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let d = to_duration(vm, &a.arg(0))?;
    create_duration(vm, d, None)
}

macro_rules! dur_getter {
    ($name:ident, $field:ident) => {
        fn $name(vm: &mut Vm, a: &Args) -> JsResult<Value> {
            Ok(num(this_duration(vm, a)?.$field))
        }
    };
}

dur_getter!(get_years, years);
dur_getter!(get_months, months);
dur_getter!(get_weeks, weeks);
dur_getter!(get_days, days);
dur_getter!(get_hours, hours);
dur_getter!(get_minutes, minutes);
dur_getter!(get_seconds, seconds);
dur_getter!(get_milliseconds, milliseconds);
dur_getter!(get_microseconds, microseconds);
dur_getter!(get_nanoseconds, nanoseconds);

fn get_sign(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_duration(vm, a)?.sign() as f64))
}

fn get_blank(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(this_duration(vm, a)?.sign() == 0))
}

fn to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let d = this_duration(vm, a)?;
    let opts = get_options_object(vm, &a.arg(0))?;
    let digits = get_fractional_digits(vm, &opts)?;
    let mode = get_rounding_mode(vm, &opts, RoundingMode::Trunc)?;
    let smallest = match opt_unit_string(vm, &opts, "smallestUnit")? {
        None => None,
        Some(s) => match Unit::from_str(&s) {
            Some(u) if u >= Unit::Second => Some(u),
            _ => return vm.throw_range("smallestUnit must be second or smaller"),
        },
    };
    let (p, unit, inc) = seconds_precision(smallest, digits);
    if unit == Unit::Nanosecond && inc == 1 {
        return Ok(Value::str(&d.to_string_with(p)));
    }
    let largest = d.default_largest_unit();
    let i = to_internal(&d);
    let t = tr!(vm, round_time_duration(i.time, inc, unit, mode));
    let r = tr!(vm, from_internal(&IDur { date: i.date, time: t }, Unit::larger(largest, Unit::Second)));
    Ok(Value::str(&r.to_string_with(p)))
}

fn to_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let d = this_duration(vm, a)?;
    Ok(Value::str(&d.to_string_with(Precision::Auto)))
}

fn negated(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let d = this_duration(vm, a)?;
    create_duration(vm, d.negated(), None)
}

fn abs(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let d = this_duration(vm, a)?;
    create_duration(vm, d.abs(), None)
}

fn with(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let d = this_duration(vm, a)?;
    let o = match a.arg(0) {
        Value::Obj(o) => o,
        _ => return vm.throw_type("with() argument must be an object"),
    };
    let p = match to_partial_duration(vm, &o)? {
        Some(p) => p,
        None => return vm.throw_type("with() requires at least one duration field"),
    };
    let mut f = d.fields();
    for i in 0..10 {
        if let Some(v) = p[i] {
            f[i] = v;
        }
    }
    create_duration(vm, Dur::from_fields(f), None)
}

fn add_sub(vm: &mut Vm, a: &Args, negate: bool) -> JsResult<Value> {
    let d = this_duration(vm, a)?;
    let mut o = to_duration(vm, &a.arg(0))?;
    if negate {
        o = o.negated();
    }
    let largest = Unit::larger(d.default_largest_unit(), o.default_largest_unit());
    if largest.is_calendar() {
        return vm.throw_range("Duration arithmetic with years, months, or weeks requires a relativeTo");
    }
    let d1 = tr!(vm, to_internal_24h(&d));
    let d2 = tr!(vm, to_internal_24h(&o));
    let t = tr!(vm, add_time(d1.time, d2.time));
    let r = tr!(vm, from_internal(&IDur { date: DateDur::default(), time: t }, largest));
    create_duration(vm, r, None)
}

fn add(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    add_sub(vm, a, false)
}

fn subtract(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    add_sub(vm, a, true)
}

// ---------------------------------------------------------------------------
// relativeTo
// ---------------------------------------------------------------------------

pub enum RelativeTo {
    None,
    Plain(IsoDate, Cal),
    Zoned(i128, Tz, Cal),
}

const MSG_REL_RANGE: &str = "relativeTo is outside the supported range";

fn parse_relative_to_string(s: &str) -> TRes<RelativeTo> {
    let p = match parse::parse_date_time(s) {
        Some(p) => p,
        None => {
            if parse::parse_time_only(s).is_some() {
                return rerr("relativeTo needs a date");
            }
            return rerr("invalid relativeTo string");
        }
    };
    let cal = match &p.calendar {
        None => Cal::Iso8601,
        Some(c) => match Cal::from_id(c) {
            Some(c) => c,
            None => return rerr("unsupported calendar"),
        },
    };
    if p.z && p.tz.is_none() {
        return rerr("Z designator requires a bracketed time zone in relativeTo");
    }
    let date = IsoDate::new(p.year.unwrap_or(0), p.month, p.day.unwrap_or(1));
    let tz = match &p.tz {
        None => {
            if !date_within_limits(&date) {
                return rerr(MSG_REL_RANGE);
            }
            return Ok(RelativeTo::Plain(date, cal));
        }
        Some(a) => match Tz::from_identifier(&a.text) {
            Some(tz) => tz,
            None => return rerr("invalid time zone in relativeTo string"),
        },
    };
    if !datetime_within_limits(&date, &p.time.unwrap_or(Time::MIDNIGHT)) {
        return rerr(MSG_REL_RANGE);
    }
    let (ob, off, mm) = if p.z {
        (OffsetBehaviour::Exact, 0, true)
    } else if let Some(o) = &p.offset {
        (OffsetBehaviour::Option, o.ns, !o.has_seconds)
    } else {
        (OffsetBehaviour::Wall, 0, true)
    };
    let ns = interpret_offset(&date, p.time, ob, off, &tz, Disambiguation::Compatible, OffsetOption::Reject, mm)?;
    Ok(RelativeTo::Zoned(ns, tz, cal))
}

/// GetTemporalRelativeToOption
pub fn get_relative_to(vm: &mut Vm, o: &Opts) -> JsResult<RelativeTo> {
    let v = opt_get(vm, o, "relativeTo")?;
    match &v {
        Value::Undefined => Ok(RelativeTo::None),
        Value::Obj(obj) => {
            match slot_of(&v) {
                Some(Slot::Zoned(ns, tz, c)) => return Ok(RelativeTo::Zoned(ns, tz, c)),
                Some(Slot::Date(d, c)) => return Ok(RelativeTo::Plain(d, c)),
                Some(Slot::DateTime(dt, c)) => return Ok(RelativeTo::Plain(dt.date, c)),
                _ => {}
            }
            let cal = get_calendar_with_iso_default(vm, obj)?;
            let mut f = prepare_fields(vm, cal, obj, F_DATE | F_TIME | F_OFFSET | F_TIME_ZONE, Required::List(0))?;
            if f.day.is_none() {
                return vm.throw_type("day is required");
            }
            if f.year.is_none() && !(f.era.is_some() && f.era_year.is_some()) {
                return vm.throw_type("year is required");
            }
            if f.month.is_none() && f.month_code.is_none() {
                return vm.throw_type("month or monthCode is required");
            }
            let date = tr!(vm, calendar::date_from_fields(cal, &mut f, Overflow::Constrain));
            let time = tr!(
                vm,
                regulate_time(
                    f.hour.unwrap_or(0.0),
                    f.minute.unwrap_or(0.0),
                    f.second.unwrap_or(0.0),
                    f.millisecond.unwrap_or(0.0),
                    f.microsecond.unwrap_or(0.0),
                    f.nanosecond.unwrap_or(0.0),
                    Overflow::Constrain
                )
            );
            let dt = IsoDateTime { date, time };
            let tz = match f.time_zone.clone() {
                None => return Ok(RelativeTo::Plain(dt.date, cal)),
                Some(tz) => tz,
            };
            let (ob, off) = match &f.offset {
                Some(s) => (OffsetBehaviour::Option, parse::parse_offset_string(s, true).map(|o| o.ns).unwrap_or(0)),
                None => (OffsetBehaviour::Wall, 0),
            };
            let ns = tr!(
                vm,
                interpret_offset(&dt.date, Some(dt.time), ob, off, &tz, Disambiguation::Compatible, OffsetOption::Reject, false)
            );
            Ok(RelativeTo::Zoned(ns, tz, cal))
        }
        Value::Str(s) => {
            let s = s.to_rust_string();
            Ok(tr!(vm, parse_relative_to_string(&s)))
        }
        _ => vm.throw_type("relativeTo must be an object, a string, or undefined"),
    }
}

/// DateDurationDays
fn date_duration_days(dd: &DateDur, d: &IsoDate, cal: Cal) -> TRes<i64> {
    let ymw = dd.adjust(0, None, None)?;
    if ymw.sign() == 0 {
        return Ok(dd.days);
    }
    let later = calendar::date_add(cal, d, &ymw, Overflow::Constrain)?;
    Ok(dd.days + epoch_days(later) - epoch_days(*d))
}

fn compare(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let one = to_duration(vm, &a.arg(0))?;
    let two = to_duration(vm, &a.arg(1))?;
    let opts = get_options_object(vm, &a.arg(2))?;
    let rel = get_relative_to(vm, &opts)?;
    if one == two {
        return Ok(num(0.0));
    }
    let lu1 = one.default_largest_unit();
    let lu2 = two.default_largest_unit();
    let d1 = to_internal(&one);
    let d2 = to_internal(&two);
    if let RelativeTo::Zoned(ns, tz, cal) = &rel {
        if lu1.is_date() || lu2.is_date() {
            let a1 = tr!(vm, add_zoned(*ns, tz, *cal, &d1, Overflow::Constrain));
            let a2 = tr!(vm, add_zoned(*ns, tz, *cal, &d2, Overflow::Constrain));
            return Ok(num(a1.cmp(&a2) as i32 as f64));
        }
    }
    let (days1, days2) = if lu1.is_calendar() || lu2.is_calendar() {
        let (d, cal) = match &rel {
            RelativeTo::Plain(d, c) => (*d, *c),
            _ => return vm.throw_range("comparing calendar durations requires relativeTo"),
        };
        (tr!(vm, date_duration_days(&d1.date, &d, cal)), tr!(vm, date_duration_days(&d2.date, &d, cal)))
    } else {
        (one.days as i64, two.days as i64)
    };
    let t1 = tr!(vm, add_24h_days(d1.time, days1));
    let t2 = tr!(vm, add_24h_days(d2.time, days2));
    Ok(num(t1.cmp(&t2) as i32 as f64))
}

/// Shared tail of round() / total() with a plain relativeTo:
/// (start date-time, target date-time)
fn plain_target(d: &Dur, date: &IsoDate, cal: Cal) -> TRes<(IsoDateTime, IsoDateTime)> {
    let i = to_internal_24h(d)?;
    let (days, time) = Time::balance(i.time);
    let dd = i.date.adjust(days, None, None)?;
    let target = calendar::date_add(cal, date, &dd, Overflow::Constrain)?;
    Ok((IsoDateTime { date: *date, time: Time::MIDNIGHT }, IsoDateTime { date: target, time }))
}

fn round(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let d = this_duration(vm, a)?;
    let opts = match a.arg(0) {
        Value::Str(s) if s.is_empty() => Some(Obj::new(None, ObjKind::Ordinary)),
        v => round_options(vm, &v, Some("round() requires an options argument"))?,
    };
    let lu = get_unit_option(vm, &opts, "largestUnit")?;
    let rel = get_relative_to(vm, &opts)?;
    let increment = get_rounding_increment(vm, &opts)?;
    let mode = get_rounding_mode(vm, &opts, RoundingMode::HalfExpand)?;
    let su = get_unit_option(vm, &opts, "smallestUnit")?;
    let mut smallest_present = true;
    let smallest = match su {
        None => {
            smallest_present = false;
            Unit::Nanosecond
        }
        Some(UnitOpt::U(u)) => u,
        Some(UnitOpt::Auto) => return vm.throw_range("invalid smallestUnit"),
    };
    let existing_largest = d.default_largest_unit();
    let default_largest = Unit::larger(existing_largest, smallest);
    let mut largest_present = true;
    let largest = match lu {
        None => {
            largest_present = false;
            default_largest
        }
        Some(UnitOpt::Auto) => default_largest,
        Some(UnitOpt::U(u)) => u,
    };
    if !smallest_present && !largest_present {
        return vm.throw_range("round() requires smallestUnit or largestUnit");
    }
    if Unit::larger(largest, smallest) != largest {
        return vm.throw_range("smallestUnit is larger than largestUnit");
    }
    if let Some(max) = smallest.max_increment() {
        tr!(vm, validate_increment(increment, max, false));
    }
    if increment > 1 && largest != smallest && smallest.is_date() {
        return vm.throw_range(MSG_INCREMENT);
    }
    let inc = increment as i64;
    match rel {
        RelativeTo::Zoned(ns, tz, cal) => {
            let i = to_internal(&d);
            let target = tr!(vm, add_zoned(ns, &tz, cal, &i, Overflow::Constrain));
            let r = tr!(vm, difference_zoned_with_rounding(ns, target, &tz, cal, largest, inc, smallest, mode));
            let lu2 = if largest.is_date() { Unit::Hour } else { largest };
            let out = tr!(vm, from_internal(&r, lu2));
            return create_duration(vm, out, None);
        }
        RelativeTo::Plain(date, cal) => {
            let (start, target) = tr!(vm, plain_target(&d, &date, cal));
            let r = tr!(vm, difference_plain_datetime_with_rounding(&start, &target, cal, largest, inc, smallest, mode));
            let out = tr!(vm, from_internal(&r, largest));
            return create_duration(vm, out, None);
        }
        RelativeTo::None => {}
    }
    if existing_largest.is_calendar() || largest.is_calendar() || smallest.is_calendar() {
        return vm.throw_range("rounding calendar units requires relativeTo");
    }
    let i = tr!(vm, to_internal_24h(&d));
    let r = if smallest == Unit::Day {
        let days = round_to_increment(i.time, NS_PER_DAY * increment, mode) / NS_PER_DAY;
        let dd = tr!(vm, DateDur::new(0, 0, 0, days as i64).validate());
        IDur { date: dd, time: 0 }
    } else {
        let t = tr!(vm, round_time_duration(i.time, increment, smallest, mode));
        IDur { date: DateDur::default(), time: t }
    };
    let out = tr!(vm, from_internal(&r, largest));
    create_duration(vm, out, None)
}

fn total(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let d = this_duration(vm, a)?;
    let opts = match a.arg(0) {
        Value::Undefined => return vm.throw_type("total() requires an options argument"),
        Value::Str(s) if s.is_empty() => Some(Obj::new(None, ObjKind::Ordinary)),
        Value::Str(s) => string_shorthand(vm, "unit", Value::Str(s)),
        Value::Obj(o) => Some(o),
        _ => return vm.throw_type("options must be an object or a string"),
    };
    let rel = get_relative_to(vm, &opts)?;
    let unit = match get_unit_option(vm, &opts, "unit")? {
        None => return vm.throw_range("unit is required"),
        Some(UnitOpt::Auto) => return vm.throw_range("invalid unit"),
        Some(UnitOpt::U(u)) => u,
    };
    let t = match rel {
        RelativeTo::Zoned(ns, tz, cal) => {
            let i = to_internal(&d);
            let target = tr!(vm, add_zoned(ns, &tz, cal, &i, Overflow::Constrain));
            tr!(vm, difference_zoned_with_total(ns, target, &tz, cal, unit))
        }
        RelativeTo::Plain(date, cal) => {
            let (start, target) = tr!(vm, plain_target(&d, &date, cal));
            tr!(vm, difference_plain_datetime_with_total(&start, &target, cal, unit))
        }
        RelativeTo::None => {
            let largest = d.default_largest_unit();
            if largest.is_calendar() || unit.is_calendar() {
                return vm.throw_range("total of a calendar duration requires relativeTo");
            }
            let i = tr!(vm, to_internal_24h(&d));
            total_time(i.time, unit)
        }
    };
    Ok(num(t))
}
