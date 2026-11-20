//! Temporal.PlainDateTime

use super::calendar::{self, Cal, FieldKind};
use super::dur::*;
use super::fields::*;
use super::iso::*;
use super::plain_date::{ctor_calendar, get_difference_settings, getters, valid_iso_date_f};
use super::plain_time::{read_to_string_rounding, round_options, round_time, time_from_f, valid_time_f};
use super::*;

pub fn setup(vm: &mut Vm, t: &Obj) {
    let (ctor, proto) = make_class(vm, K::PlainDateTime, "PlainDateTime", 3, construct);
    def_method(vm, &ctor, "from", 1, from);
    def_method(vm, &ctor, "compare", 2, compare);
    let g = getters(K::PlainDateTime);
    def_getter(vm, &proto, "year", g.year);
    def_getter(vm, &proto, "era", g.era);
    def_getter(vm, &proto, "eraYear", g.era_year);
    def_getter(vm, &proto, "month", g.month);
    def_getter(vm, &proto, "day", g.day);
    def_getter(vm, &proto, "monthCode", g.month_code);
    def_getter(vm, &proto, "calendarId", g.calendar_id);
    def_getter(vm, &proto, "hour", get_hour);
    def_getter(vm, &proto, "minute", get_minute);
    def_getter(vm, &proto, "second", get_second);
    def_getter(vm, &proto, "millisecond", get_millisecond);
    def_getter(vm, &proto, "microsecond", get_microsecond);
    def_getter(vm, &proto, "nanosecond", get_nanosecond);
    def_getter(vm, &proto, "dayOfWeek", g.day_of_week);
    def_getter(vm, &proto, "dayOfYear", g.day_of_year);
    def_getter(vm, &proto, "daysInMonth", g.days_in_month);
    def_getter(vm, &proto, "daysInYear", g.days_in_year);
    def_getter(vm, &proto, "monthsInYear", g.months_in_year);
    def_getter(vm, &proto, "inLeapYear", g.in_leap_year);
    def_getter(vm, &proto, "weekOfYear", g.week_of_year);
    def_getter(vm, &proto, "yearOfWeek", g.year_of_week);
    def_getter(vm, &proto, "daysInWeek", g.days_in_week);
    def_method(vm, &proto, "toString", 0, to_string);
    def_method(vm, &proto, "toJSON", 0, to_json);
    def_value_of(vm, &proto, K::PlainDateTime);
    def_method(vm, &proto, "toPlainDate", 0, to_plain_date);
    def_method(vm, &proto, "toPlainTime", 0, to_plain_time);
    def_method(vm, &proto, "withPlainTime", 0, with_plain_time);
    def_method(vm, &proto, "withCalendar", 1, with_calendar);
    def_method(vm, &proto, "toZonedDateTime", 1, to_zoned_date_time);
    def_method(vm, &proto, "equals", 1, equals);
    def_method(vm, &proto, "add", 1, add);
    def_method(vm, &proto, "subtract", 1, subtract);
    def_method(vm, &proto, "with", 1, with);
    def_method(vm, &proto, "round", 1, round);
    def_method(vm, &proto, "until", 1, until);
    def_method(vm, &proto, "since", 1, since);
    finish_class(vm, K::PlainDateTime, &ctor, &proto);
    t.set_prop(PropKey::from_str("PlainDateTime"), Value::Obj(ctor), WC);
}

pub const MSG_DATETIME_RANGE_STR: &str = "date-time outside representable range";

/// Parse a PlainDateTime string
pub fn parse_datetime_string(s: &str) -> TRes<(IsoDateTime, Cal)> {
    if let Some(p) = parse::parse_date_time(s) {
        if p.z {
            return rerr("UTC designator not valid for PlainDateTime");
        }
        let cal = match &p.calendar {
            None => Cal::Iso8601,
            Some(c) => match Cal::from_id(c) {
                Some(c) => c,
                None => return rerr("unsupported calendar"),
            },
        };
        let d = IsoDate::new(p.year.unwrap_or(0), p.month, p.day.unwrap_or(1));
        let t = p.time.unwrap_or(Time::MIDNIGHT);
        if !datetime_within_limits(&d, &t) {
            return rerr(MSG_DATETIME_RANGE_STR);
        }
        return Ok((IsoDateTime { date: d, time: t }, cal));
    }
    if let Some(p) = parse::parse_time_only(s) {
        if p.z {
            return rerr("UTC designator not valid for PlainDateTime");
        }
        return rerr("no date in PlainDateTime string");
    }
    rerr("invalid datetime")
}

/// ToTemporalDateTime
pub fn to_temporal_datetime(vm: &mut Vm, item: &Value, options: &Value) -> JsResult<(IsoDateTime, Cal)> {
    if let Value::Obj(o) = item {
        match slot_of(item) {
            Some(Slot::DateTime(dt, c)) => {
                let opts = get_options_object_strict(vm, options)?;
                get_overflow(vm, &opts)?;
                return Ok((dt, c));
            }
            Some(Slot::Date(d, c)) => {
                let opts = get_options_object_strict(vm, options)?;
                get_overflow(vm, &opts)?;
                return Ok((IsoDateTime { date: d, time: Time::MIDNIGHT }, c));
            }
            _ => {}
        }
        let cal = get_calendar_with_iso_default(vm, o)?;
        let mut f = prepare_fields(vm, cal, o, F_DATE | F_TIME, Required::List(0))?;
        let opts = get_options_object_strict(vm, options)?;
        let overflow = get_overflow(vm, &opts)?;
        let dt = match interpret_datetime_fields(cal, &mut f, overflow) {
            Ok(dt) => dt,
            Err(TErr::Range(m)) if m == MSG_DATETIME_RANGE => return vm.throw_range(MSG_DATETIME_RANGE_STR),
            Err(e) => return throw(vm, e),
        };
        return Ok((dt, cal));
    }
    let s = match item {
        Value::Str(s) => s.to_rust_string(),
        _ => return vm.throw_type("cannot convert to Temporal.PlainDateTime"),
    };
    let r = tr!(vm, parse_datetime_string(&s));
    let opts = get_options_object_strict(vm, options)?;
    get_overflow(vm, &opts)?;
    Ok(r)
}

/// InterpretTemporalDateTimeFields
pub fn interpret_datetime_fields(cal: Cal, f: &mut Fields, overflow: Overflow) -> TRes<IsoDateTime> {
    calendar::resolve_fields(cal, f, FieldKind::Date)?;
    let d = calendar::date_to_iso(cal, f, overflow)?;
    let t = regulate_time(
        f.hour.unwrap_or(0.0),
        f.minute.unwrap_or(0.0),
        f.second.unwrap_or(0.0),
        f.millisecond.unwrap_or(0.0),
        f.microsecond.unwrap_or(0.0),
        f.nanosecond.unwrap_or(0.0),
        overflow,
    )?;
    if !datetime_within_limits(&d, &t) {
        return rerr(MSG_DATETIME_RANGE);
    }
    Ok(IsoDateTime { date: d, time: t })
}

fn construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = match &a.new_target {
        Some(nt) => nt.clone(),
        None => return vm.throw_type("constructor requires 'new'"),
    };
    let y = to_integer_with_truncation(vm, &a.arg(0))?;
    let m = to_integer_with_truncation(vm, &a.arg(1))?;
    let d = to_integer_with_truncation(vm, &a.arg(2))?;
    let mut f = [0.0f64; 6];
    for (i, v) in f.iter_mut().enumerate() {
        let x = a.arg(3 + i);
        if !x.is_undefined() {
            *v = to_integer_with_truncation(vm, &x)?;
        }
    }
    let cal = ctor_calendar(vm, &a.arg(9))?;
    if !valid_iso_date_f(y, m, d) {
        return vm.throw_range("ISO date field is out of range");
    }
    if !valid_time_f(&f) {
        return vm.throw_range("ISO time field is out of range");
    }
    let dt = IsoDateTime { date: IsoDate::new(y as i64, m as u8, d as u8), time: time_from_f(&f) };
    create_datetime(vm, dt, cal, Some(&nt))
}

fn from(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (dt, c) = to_temporal_datetime(vm, &a.arg(0), &a.arg(1))?;
    create_datetime(vm, dt, c, None)
}

fn compare(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (one, _) = to_temporal_datetime(vm, &a.arg(0), &Value::Undefined)?;
    let (two, _) = to_temporal_datetime(vm, &a.arg(1), &Value::Undefined)?;
    Ok(num(compare_datetime(&one, &two) as i32 as f64))
}

fn get_hour(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_datetime(vm, a)?.0.time.hour as f64))
}
fn get_minute(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_datetime(vm, a)?.0.time.minute as f64))
}
fn get_second(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_datetime(vm, a)?.0.time.second as f64))
}
fn get_millisecond(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_datetime(vm, a)?.0.time.millisecond as f64))
}
fn get_microsecond(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_datetime(vm, a)?.0.time.microsecond as f64))
}
fn get_nanosecond(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_datetime(vm, a)?.0.time.nanosecond as f64))
}

/// RoundISODateTime
pub fn round_iso_datetime(dt: &IsoDateTime, increment: i128, unit: Unit, mode: RoundingMode) -> IsoDateTime {
    let (days, t) = round_time(&dt.time, increment, unit, mode);
    IsoDateTime { date: add_days(dt.date, days), time: t }
}

fn to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (dt, cal) = this_datetime(vm, a)?;
    let opts = get_options_object(vm, &a.arg(0))?;
    let show = get_show_calendar(vm, &opts)?;
    let (p, u, inc, mode) = read_to_string_rounding(vm, &opts)?;
    let r = round_iso_datetime(&dt, inc, u, mode);
    if !datetime_within_limits(&r.date, &r.time) {
        return vm.throw_range(MSG_DATETIME_RANGE);
    }
    Ok(Value::str(&fmt_datetime(&r, cal, p, show)))
}

fn to_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (dt, cal) = this_datetime(vm, a)?;
    Ok(Value::str(&fmt_datetime(&dt, cal, Precision::Auto, ShowCalendar::Auto)))
}

fn to_plain_date(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (dt, cal) = this_datetime(vm, a)?;
    create_date(vm, dt.date, cal, None)
}

fn to_plain_time(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (dt, _) = this_datetime(vm, a)?;
    create_time(vm, dt.time, None)
}

fn with_plain_time(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (dt, cal) = this_datetime(vm, a)?;
    let t = super::plain_time::to_time_or_midnight(vm, &a.arg(0))?;
    create_datetime(vm, IsoDateTime { date: dt.date, time: t }, cal, None)
}

fn with_calendar(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (dt, _) = this_datetime(vm, a)?;
    let cal = with_calendar_arg(vm, &a.arg(0))?;
    create_datetime(vm, dt, cal, None)
}

fn to_zoned_date_time(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (dt, cal) = this_datetime(vm, a)?;
    let tz = to_time_zone_identifier(vm, &a.arg(0))?;
    let opts = get_options_object(vm, &a.arg(1))?;
    let dis = get_disambiguation(vm, &opts)?;
    let ns = tr!(vm, tz.epoch_ns_for(&dt, dis));
    create_zoned(vm, ns, tz, cal, None)
}

fn equals(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (dt, cal) = this_datetime(vm, a)?;
    let (o, oc) = to_temporal_datetime(vm, &a.arg(0), &Value::Undefined)?;
    Ok(Value::Bool(dt == o && cal == oc))
}

fn add_sub(vm: &mut Vm, a: &Args, negate: bool) -> JsResult<Value> {
    let (dt, cal) = this_datetime(vm, a)?;
    let mut d = to_duration(vm, &a.arg(0))?;
    if negate {
        d = d.negated();
    }
    let opts = get_options_object(vm, &a.arg(1))?;
    let overflow = get_overflow(vm, &opts)?;
    let i = tr!(vm, to_internal_24h(&d));
    let (days, t) = Time::balance(dt.time.to_ns() + i.time);
    let dd = tr!(vm, i.date.adjust(days, None, None));
    let date = tr!(vm, calendar::date_add(cal, &dt.date, &dd, overflow));
    create_datetime(vm, IsoDateTime { date, time: t }, cal, None)
}

fn add(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    add_sub(vm, a, false)
}

fn subtract(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    add_sub(vm, a, true)
}

fn with(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (dt, cal) = this_datetime(vm, a)?;
    let obj = check_partial(vm, &a.arg(0))?;
    let mut base = calendar::iso_to_fields(cal, &dt.date, FieldKind::Date);
    base.set_time(&dt.time);
    let partial = prepare_fields(vm, cal, &obj, F_DATE | F_TIME, Required::Partial)?;
    tr!(vm, calendar::check_with_era(cal, &partial));
    let mut merged = calendar::merge_fields(cal, &base, &partial);
    let opts = get_options_object(vm, &a.arg(1))?;
    let overflow = get_overflow(vm, &opts)?;
    let r = tr!(vm, interpret_datetime_fields(cal, &mut merged, overflow));
    create_datetime(vm, r, cal, None)
}

fn round(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (dt, cal) = this_datetime(vm, a)?;
    let opts = round_options(vm, &a.arg(0), None)?;
    let increment = get_rounding_increment(vm, &opts)?;
    let mode = get_rounding_mode(vm, &opts, RoundingMode::HalfExpand)?;
    let su = match opt_unit_string(vm, &opts, "smallestUnit")? {
        Some(s) => Unit::from_str(&s),
        None => None,
    };
    let unit = match su {
        Some(u) if u >= Unit::Day => u,
        _ => return vm.throw_range("invalid smallestUnit"),
    };
    let (max, inclusive) = if unit == Unit::Day { (1, true) } else { (unit.max_increment().unwrap_or(1), false) };
    tr!(vm, validate_increment(increment, max, inclusive));
    if unit == Unit::Nanosecond && increment == 1 {
        return create_datetime(vm, dt, cal, None);
    }
    let r = round_iso_datetime(&dt, increment, unit, mode);
    create_datetime(vm, r, cal, None)
}

fn difference(vm: &mut Vm, a: &Args, since: bool) -> JsResult<Value> {
    let (dt, cal) = this_datetime(vm, a)?;
    let (other, ocal) = to_temporal_datetime(vm, &a.arg(0), &Value::Undefined)?;
    if cal != ocal {
        return vm.throw_range("cannot compare dates in different calendars");
    }
    let opts = get_options_object(vm, &a.arg(1))?;
    let s = get_difference_settings(vm, since, &opts, UnitGroup::DateTime, &[], Unit::Nanosecond, Unit::Day)?;
    if dt == other {
        return create_duration(vm, Dur::default(), None);
    }
    let i = tr!(
        vm,
        difference_plain_datetime_with_rounding(&dt, &other, cal, s.largest, s.increment, s.smallest, s.mode)
    );
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
