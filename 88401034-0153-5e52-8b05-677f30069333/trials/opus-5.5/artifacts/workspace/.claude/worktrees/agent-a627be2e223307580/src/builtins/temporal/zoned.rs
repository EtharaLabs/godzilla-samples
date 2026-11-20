//! Temporal.ZonedDateTime

use super::calendar::{self, Cal, FieldKind};
use super::dur::*;
use super::fields::*;
use super::iso::*;
use super::plain_date::{get_difference_settings, getters};
use super::plain_date_time::{interpret_datetime_fields, round_iso_datetime};
use super::plain_time::round_options;
use super::tz::Tz;
use super::*;

pub fn setup(vm: &mut Vm, t: &Obj) {
    let (ctor, proto) = make_class(vm, K::ZonedDateTime, "ZonedDateTime", 2, construct);
    def_method(vm, &ctor, "from", 1, from);
    def_method(vm, &ctor, "compare", 2, compare);
    let g = getters(K::ZonedDateTime);
    def_getter(vm, &proto, "year", g.year);
    def_getter(vm, &proto, "era", g.era);
    def_getter(vm, &proto, "eraYear", g.era_year);
    def_getter(vm, &proto, "month", g.month);
    def_getter(vm, &proto, "day", g.day);
    def_getter(vm, &proto, "monthCode", g.month_code);
    def_getter(vm, &proto, "dayOfWeek", g.day_of_week);
    def_getter(vm, &proto, "dayOfYear", g.day_of_year);
    def_getter(vm, &proto, "daysInMonth", g.days_in_month);
    def_getter(vm, &proto, "daysInYear", g.days_in_year);
    def_getter(vm, &proto, "inLeapYear", g.in_leap_year);
    def_getter(vm, &proto, "weekOfYear", g.week_of_year);
    def_getter(vm, &proto, "yearOfWeek", g.year_of_week);
    def_getter(vm, &proto, "daysInWeek", g.days_in_week);
    def_getter(vm, &proto, "monthsInYear", g.months_in_year);
    def_getter(vm, &proto, "hoursInDay", get_hours_in_day);
    def_getter(vm, &proto, "hour", get_hour);
    def_getter(vm, &proto, "minute", get_minute);
    def_getter(vm, &proto, "second", get_second);
    def_getter(vm, &proto, "millisecond", get_millisecond);
    def_getter(vm, &proto, "microsecond", get_microsecond);
    def_getter(vm, &proto, "nanosecond", get_nanosecond);
    def_getter(vm, &proto, "calendarId", g.calendar_id);
    def_getter(vm, &proto, "epochMilliseconds", get_epoch_milliseconds);
    def_getter(vm, &proto, "epochNanoseconds", get_epoch_nanoseconds);
    def_getter(vm, &proto, "offsetNanoseconds", get_offset_nanoseconds);
    def_getter(vm, &proto, "offset", get_offset);
    def_getter(vm, &proto, "timeZoneId", get_time_zone_id);
    def_method(vm, &proto, "toInstant", 0, to_instant);
    def_method(vm, &proto, "toPlainDate", 0, to_plain_date);
    def_method(vm, &proto, "toPlainTime", 0, to_plain_time);
    def_method(vm, &proto, "toPlainDateTime", 0, to_plain_date_time);
    def_method(vm, &proto, "startOfDay", 0, start_of_day);
    def_method(vm, &proto, "equals", 1, equals);
    def_value_of(vm, &proto, K::ZonedDateTime);
    def_method(vm, &proto, "toJSON", 0, to_json);
    def_method(vm, &proto, "toString", 0, to_string);
    def_method(vm, &proto, "add", 1, add);
    def_method(vm, &proto, "subtract", 1, subtract);
    def_method(vm, &proto, "with", 1, with);
    def_method(vm, &proto, "withTimeZone", 1, with_time_zone);
    def_method(vm, &proto, "withCalendar", 1, with_calendar);
    def_method(vm, &proto, "getTimeZoneTransition", 1, get_time_zone_transition);
    def_method(vm, &proto, "withPlainTime", 0, with_plain_time);
    def_method(vm, &proto, "until", 1, until);
    def_method(vm, &proto, "since", 1, since);
    def_method(vm, &proto, "round", 1, round);
    finish_class(vm, K::ZonedDateTime, &ctor, &proto);
    t.set_prop(PropKey::from_str("ZonedDateTime"), Value::Obj(ctor), WC);
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum OffsetBehaviour {
    Option,
    Exact,
    Wall,
}

pub const MSG_OFFSET_MISMATCH: &str = "offset does not match the time zone";

/// InterpretISODateTimeOffset (time None = start of day)
#[allow(clippy::too_many_arguments)]
pub fn interpret_offset(
    date: &IsoDate,
    time: Option<Time>,
    ob: OffsetBehaviour,
    offset_ns: i128,
    tz: &Tz,
    dis: Disambiguation,
    oo: OffsetOption,
    match_minutes: bool,
) -> TRes<i128> {
    let time = match time {
        None => return tz.start_of_day(date),
        Some(t) => t,
    };
    let dt = IsoDateTime { date: *date, time };
    if ob == OffsetBehaviour::Wall || (ob == OffsetBehaviour::Option && oo == OffsetOption::Ignore) {
        return tz.epoch_ns_for(&dt, dis);
    }
    if ob == OffsetBehaviour::Exact || (ob == OffsetBehaviour::Option && oo == OffsetOption::Use) {
        let b = balance_datetime(date, &time, -offset_ns);
        if !days_in_range(&b.date) {
            return rerr(MSG_INSTANT_RANGE);
        }
        let ns = utc_epoch_ns_dt(&b);
        if !epoch_ns_valid(ns) {
            return rerr(MSG_INSTANT_RANGE);
        }
        return Ok(ns);
    }
    if !days_in_range(date) {
        return rerr(MSG_INSTANT_RANGE);
    }
    let utc = utc_epoch_ns_dt(&dt);
    let possible = tz.possible_epoch_ns(&dt)?;
    for &c in &possible {
        let co = utc - c;
        if co == offset_ns {
            return Ok(c);
        }
        if match_minutes && round_to_increment(co, NS_PER_MINUTE, RoundingMode::HalfExpand) == offset_ns {
            return Ok(c);
        }
    }
    if oo == OffsetOption::Reject {
        return rerr(MSG_OFFSET_MISMATCH);
    }
    tz.disambiguate(possible, &dt, dis)
}

/// Parsed ZonedDateTime string
pub struct ZParse {
    pub date: IsoDate,
    pub time: Option<Time>,
    pub tz: Tz,
    pub cal: Cal,
    pub ob: OffsetBehaviour,
    pub offset_ns: i128,
    pub match_minutes: bool,
}

pub fn parse_zoned_string(s: &str) -> TRes<ZParse> {
    let p = match parse::parse_date_time(s).or_else(|| parse::parse_time_only(s)) {
        Some(p) => p,
        None => return rerr("invalid ZonedDateTime"),
    };
    let cal = match &p.calendar {
        None => Cal::Iso8601,
        Some(c) => match Cal::from_id(c) {
            Some(c) => c,
            None => return rerr("unsupported calendar"),
        },
    };
    if p.form != parse::Form::DateTime {
        return rerr("invalid ZonedDateTime");
    }
    let ann = match &p.tz {
        Some(a) => a.text.clone(),
        None => return rerr("missing time zone"),
    };
    let tz = match Tz::from_identifier(&ann) {
        Some(tz) => tz,
        None => return rerr(format!("unknown time zone: {}", ann)),
    };
    let (ob, offset_ns, match_minutes) = if p.z {
        (OffsetBehaviour::Exact, 0, true)
    } else if let Some(o) = &p.offset {
        (OffsetBehaviour::Option, o.ns, !o.has_seconds)
    } else {
        (OffsetBehaviour::Wall, 0, true)
    };
    let date = IsoDate::new(p.year.unwrap_or(0), p.month, p.day.unwrap_or(1));
    if !datetime_within_limits(&date, &p.time.unwrap_or(Time::MIDNIGHT)) {
        return rerr(MSG_DATETIME_RANGE);
    }
    Ok(ZParse { date, time: p.time, tz, cal, ob, offset_ns, match_minutes })
}

/// ToTemporalZonedDateTime
pub fn to_temporal_zoned(vm: &mut Vm, item: &Value, options: &Value) -> JsResult<(i128, Tz, Cal)> {
    if let Value::Obj(o) = item {
        if let Some(Slot::Zoned(ns, tz, c)) = slot_of(item) {
            let opts = get_options_object(vm, options)?;
            get_disambiguation(vm, &opts)?;
            get_offset_option(vm, &opts, OffsetOption::Reject)?;
            get_overflow(vm, &opts)?;
            return Ok((ns, tz, c));
        }
        let cal = get_calendar_with_iso_default(vm, o)?;
        let mut f = prepare_fields(vm, cal, o, F_DATE | F_TIME | F_OFFSET | F_TIME_ZONE, Required::List(F_TIME_ZONE))?;
        let tz = f.time_zone.clone().unwrap_or_else(Tz::utc);
        let ob = if f.offset.is_some() { OffsetBehaviour::Option } else { OffsetBehaviour::Wall };
        let opts = get_options_object(vm, options)?;
        let dis = get_disambiguation(vm, &opts)?;
        let oo = get_offset_option(vm, &opts, OffsetOption::Reject)?;
        let overflow = get_overflow(vm, &opts)?;
        let dt = tr!(vm, interpret_datetime_fields(cal, &mut f, overflow));
        let offset_ns = match &f.offset {
            Some(s) => parse::parse_offset_string(s, true).map(|o| o.ns).unwrap_or(0),
            None => 0,
        };
        let ns = tr!(vm, interpret_offset(&dt.date, Some(dt.time), ob, offset_ns, &tz, dis, oo, false));
        return Ok((ns, tz, cal));
    }
    let s = match item {
        Value::Str(s) => s.to_rust_string(),
        _ => return vm.throw_type("cannot convert to Temporal.ZonedDateTime"),
    };
    let zp = tr!(vm, parse_zoned_string(&s));
    let opts = get_options_object(vm, options)?;
    let dis = get_disambiguation(vm, &opts)?;
    let oo = get_offset_option(vm, &opts, OffsetOption::Reject)?;
    get_overflow(vm, &opts)?;
    let ns = tr!(
        vm,
        interpret_offset(&zp.date, zp.time, zp.ob, zp.offset_ns, &zp.tz, dis, oo, zp.match_minutes)
    );
    Ok((ns, zp.tz, zp.cal))
}

fn construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = match &a.new_target {
        Some(nt) => nt.clone(),
        None => return vm.throw_type("constructor requires 'new'"),
    };
    let prim = match a.arg(0) {
        Value::Obj(_) => vm.to_primitive(&a.arg(0), crate::ops::Hint::Number)?,
        v => v,
    };
    let b = match prim {
        Value::BigInt(b) => (*b).clone(),
        Value::Bool(b) => crate::bigint::BigInt::from_i64(b as i64),
        Value::Str(s) => match crate::bigint::BigInt::parse(s.units()) {
            Some(b) => b,
            None => return vm.throw_syntax("Cannot convert string to a BigInt"),
        },
        Value::Num(_) => return vm.throw_type("Cannot convert a Number to a BigInt"),
        _ => return vm.throw_type("Cannot convert value to a BigInt"),
    };
    let ns = match bigint_to_i128(&b) {
        Some(ns) if epoch_ns_valid(ns) => ns,
        _ => return vm.throw_range(MSG_INSTANT_RANGE),
    };
    let tz = match a.arg(1) {
        Value::Str(s) => match Tz::from_identifier(&s.to_rust_string()) {
            Some(tz) => tz,
            None => return vm.throw_range("invalid time zone identifier"),
        },
        Value::Undefined => return vm.throw_type("missing timeZone"),
        _ => return vm.throw_type("time zone must be a string"),
    };
    let cal = super::plain_date::ctor_calendar(vm, &a.arg(2))?;
    create_zoned(vm, ns, tz, cal, Some(&nt))
}

fn from(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, tz, c) = to_temporal_zoned(vm, &a.arg(0), &a.arg(1))?;
    create_zoned(vm, ns, tz, c, None)
}

fn compare(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (one, _, _) = to_temporal_zoned(vm, &a.arg(0), &Value::Undefined)?;
    let (two, _, _) = to_temporal_zoned(vm, &a.arg(1), &Value::Undefined)?;
    Ok(num(one.cmp(&two) as i32 as f64))
}

fn this_dt(vm: &mut Vm, a: &Args) -> JsResult<IsoDateTime> {
    let (ns, tz, _) = this_zoned(vm, a)?;
    Ok(tz.datetime_for(ns))
}

fn get_hour(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_dt(vm, a)?.time.hour as f64))
}
fn get_minute(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_dt(vm, a)?.time.minute as f64))
}
fn get_second(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_dt(vm, a)?.time.second as f64))
}
fn get_millisecond(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_dt(vm, a)?.time.millisecond as f64))
}
fn get_microsecond(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_dt(vm, a)?.time.microsecond as f64))
}
fn get_nanosecond(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(num(this_dt(vm, a)?.time.nanosecond as f64))
}

fn get_hours_in_day(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, tz, _) = this_zoned(vm, a)?;
    let today = tz.datetime_for(ns).date;
    let tomorrow = add_days(today, 1);
    let t0 = tr!(vm, tz.start_of_day(&today));
    let t1 = tr!(vm, tz.start_of_day(&tomorrow));
    Ok(num(total_time(t1 - t0, Unit::Hour)))
}

fn get_epoch_milliseconds(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, _, _) = this_zoned(vm, a)?;
    Ok(num(ns.div_euclid(1_000_000) as f64))
}

fn get_epoch_nanoseconds(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, _, _) = this_zoned(vm, a)?;
    Ok(ns_to_bigint(ns))
}

fn get_offset_nanoseconds(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, tz, _) = this_zoned(vm, a)?;
    Ok(num(tz.offset_ns(ns) as f64))
}

fn get_offset(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, tz, _) = this_zoned(vm, a)?;
    Ok(Value::str(&fmt_offset_ns(tz.offset_ns(ns))))
}

fn get_time_zone_id(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (_, tz, _) = this_zoned(vm, a)?;
    Ok(Value::str(&tz.id()))
}

fn to_instant(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, _, _) = this_zoned(vm, a)?;
    create_instant(vm, ns, None)
}

fn to_plain_date(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, tz, cal) = this_zoned(vm, a)?;
    create_date(vm, tz.datetime_for(ns).date, cal, None)
}

fn to_plain_time(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, tz, _) = this_zoned(vm, a)?;
    create_time(vm, tz.datetime_for(ns).time, None)
}

fn to_plain_date_time(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, tz, cal) = this_zoned(vm, a)?;
    create_datetime(vm, tz.datetime_for(ns), cal, None)
}

fn start_of_day(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, tz, cal) = this_zoned(vm, a)?;
    let d = tz.datetime_for(ns).date;
    let r = tr!(vm, tz.start_of_day(&d));
    create_zoned(vm, r, tz, cal, None)
}

fn equals(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, tz, cal) = this_zoned(vm, a)?;
    let (ons, otz, ocal) = to_temporal_zoned(vm, &a.arg(0), &Value::Undefined)?;
    Ok(Value::Bool(ns == ons && tz.equals(&otz) && cal == ocal))
}

/// TemporalZonedDateTimeToString
#[allow(clippy::too_many_arguments)]
pub fn zoned_to_string(
    ns: i128,
    tz: &Tz,
    cal: Cal,
    p: Precision,
    show_cal: ShowCalendar,
    show_tz: ShowTimeZone,
    show_offset: bool,
    increment: i128,
    unit: Unit,
    mode: RoundingMode,
) -> String {
    let ns = round_as_if_positive(ns, increment * unit.ns(), mode);
    let offset = tz.offset_ns(ns);
    let dt = datetime_from_epoch_ns(ns + offset);
    let mut s = format!("{}T{}", fmt_date(&dt.date), fmt_time(&dt.time, p));
    if show_offset {
        s += &fmt_offset_rounded(offset);
    }
    match show_tz {
        ShowTimeZone::Never => {}
        ShowTimeZone::Critical => s += &format!("[!{}]", tz.id()),
        ShowTimeZone::Auto => s += &format!("[{}]", tz.id()),
    }
    s + &fmt_calendar_annotation(cal, show_cal)
}

fn to_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    // the original's toJSON keeps the full-precision offset (-04:56:02)
    let (ns, tz, cal) = this_zoned(vm, a)?;
    let offset = tz.offset_ns(ns);
    let dt = datetime_from_epoch_ns(ns + offset);
    let s = format!(
        "{}T{}{}[{}]{}",
        fmt_date(&dt.date),
        fmt_time(&dt.time, Precision::Auto),
        fmt_offset_ns(offset),
        tz.id(),
        fmt_calendar_annotation(cal, ShowCalendar::Auto)
    );
    Ok(Value::str(&s))
}

fn to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, tz, cal) = this_zoned(vm, a)?;
    let opts = get_options_object(vm, &a.arg(0))?;
    let show_cal = get_show_calendar(vm, &opts)?;
    let digits = get_fractional_digits(vm, &opts)?;
    let show_offset = get_show_offset(vm, &opts)?;
    let mode = get_rounding_mode(vm, &opts, RoundingMode::Trunc)?;
    let su = get_unit_option(vm, &opts, "smallestUnit")?;
    let show_tz = get_show_time_zone(vm, &opts)?;
    let smallest = match su {
        None => None,
        Some(UnitOpt::U(u)) if !u.is_date() && u != Unit::Hour => Some(u),
        Some(UnitOpt::U(_)) => return vm.throw_range("invalid smallestUnit for toString"),
        Some(UnitOpt::Auto) => return vm.throw_range("invalid smallestUnit"),
    };
    let (p, u, inc) = seconds_precision(smallest, digits);
    // The original rounds the wall-clock time (like round()) and maps it
    // back to an instant, preferring the current offset.
    let r = if u == Unit::Nanosecond && inc == 1 {
        ns
    } else {
        let dt = tz.datetime_for(ns);
        let rd = round_iso_datetime(&dt, inc, u, mode);
        let offset = tz.offset_ns(ns);
        tr!(
            vm,
            interpret_offset(
                &rd.date,
                Some(rd.time),
                OffsetBehaviour::Option,
                offset,
                &tz,
                Disambiguation::Compatible,
                OffsetOption::Prefer,
                false
            )
        )
    };
    Ok(Value::str(&zoned_to_string(r, &tz, cal, p, show_cal, show_tz, show_offset, 1, Unit::Nanosecond, mode)))
}

fn add_sub(vm: &mut Vm, a: &Args, negate: bool) -> JsResult<Value> {
    let (ns, tz, cal) = this_zoned(vm, a)?;
    let mut d = to_duration(vm, &a.arg(0))?;
    if negate {
        d = d.negated();
    }
    let opts = get_options_object(vm, &a.arg(1))?;
    let overflow = get_overflow(vm, &opts)?;
    let i = to_internal(&d);
    let r = tr!(vm, add_zoned(ns, &tz, cal, &i, overflow));
    create_zoned(vm, r, tz, cal, None)
}

fn add(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    add_sub(vm, a, false)
}

fn subtract(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    add_sub(vm, a, true)
}

fn with(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, tz, cal) = this_zoned(vm, a)?;
    if !a.arg(0).is_object() {
        return vm.throw_type("with() argument must be an object");
    }
    let obj = check_partial(vm, &a.arg(0))?;
    let offset = tz.offset_ns(ns);
    let dt = tz.datetime_for(ns);
    let mut base = calendar::iso_to_fields(cal, &dt.date, FieldKind::Date);
    base.set_time(&dt.time);
    base.offset = Some(fmt_offset_ns(offset));
    let partial = prepare_fields(vm, cal, &obj, F_DATE | F_TIME | F_OFFSET, Required::Partial)?;
    tr!(vm, calendar::check_with_era(cal, &partial));
    let mut merged = calendar::merge_fields(cal, &base, &partial);
    let opts = get_options_object(vm, &a.arg(1))?;
    let dis = get_disambiguation(vm, &opts)?;
    let oo = get_offset_option(vm, &opts, OffsetOption::Prefer)?;
    let overflow = get_overflow(vm, &opts)?;
    let r = tr!(vm, interpret_datetime_fields(cal, &mut merged, overflow));
    let new_offset = match &merged.offset {
        Some(s) => parse::parse_offset_string(s, true).map(|o| o.ns).unwrap_or(0),
        None => 0,
    };
    let ns2 = tr!(
        vm,
        interpret_offset(&r.date, Some(r.time), OffsetBehaviour::Option, new_offset, &tz, dis, oo, false)
    );
    create_zoned(vm, ns2, tz, cal, None)
}

fn with_time_zone(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, _, cal) = this_zoned(vm, a)?;
    let tz = to_time_zone_identifier(vm, &a.arg(0))?;
    create_zoned(vm, ns, tz, cal, None)
}

fn with_calendar(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, tz, _) = this_zoned(vm, a)?;
    let cal = with_calendar_arg(vm, &a.arg(0))?;
    create_zoned(vm, ns, tz, cal, None)
}

fn get_time_zone_transition(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, tz, cal) = this_zoned(vm, a)?;
    let arg = a.arg(0);
    let opts = match &arg {
        Value::Undefined => return vm.throw_type("direction is required"),
        Value::Str(_) => string_shorthand(vm, "direction", arg.clone()),
        Value::Obj(o) => Some(o.clone()),
        _ => return vm.throw_type("direction must be a string or an options object"),
    };
    let next = match opt_string(vm, &opts, "direction")? {
        None => return vm.throw_range("direction is required"),
        Some(s) => match s.as_str() {
            "next" => true,
            "previous" => false,
            _ => return vm.throw_range("direction must be 'next' or 'previous'"),
        },
    };
    let t = if next { tz.next_transition(ns) } else { tz.prev_transition(ns) };
    match t {
        Some(t) => create_zoned(vm, t, tz, cal, None),
        None => Ok(Value::Null),
    }
}

fn with_plain_time(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (ns, tz, cal) = this_zoned(vm, a)?;
    let dt = tz.datetime_for(ns);
    let arg = a.arg(0);
    let r = if arg.is_undefined() {
        tr!(vm, tz.start_of_day(&dt.date))
    } else {
        let t = super::plain_time::to_temporal_time(vm, &arg, &Value::Undefined)?;
        tr!(vm, tz.epoch_ns_for(&IsoDateTime { date: dt.date, time: t }, Disambiguation::Compatible))
    };
    create_zoned(vm, r, tz, cal, None)
}

fn difference(vm: &mut Vm, a: &Args, since: bool) -> JsResult<Value> {
    let (ns, tz, cal) = this_zoned(vm, a)?;
    let (ons, otz, ocal) = to_temporal_zoned(vm, &a.arg(0), &Value::Undefined)?;
    if cal != ocal {
        return vm.throw_range("cannot compare dates in different calendars");
    }
    let opts = get_options_object(vm, &a.arg(1))?;
    let s = get_difference_settings(vm, since, &opts, UnitGroup::DateTime, &[], Unit::Nanosecond, Unit::Hour)?;
    let mut r = if !s.largest.is_date() {
        let i = tr!(vm, difference_instant(ns, ons, s.increment, s.smallest, s.mode));
        tr!(vm, from_internal(&i, s.largest))
    } else {
        if !tz.equals(&otz) {
            return vm.throw_range("cannot compute a calendar-unit difference between time zones");
        }
        if ns == ons {
            return create_duration(vm, Dur::default(), None);
        }
        let i = tr!(
            vm,
            difference_zoned_with_rounding(ns, ons, &tz, cal, s.largest, s.increment, s.smallest, s.mode)
        );
        tr!(vm, from_internal(&i, Unit::Hour))
    };
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
    let (ns, tz, cal) = this_zoned(vm, a)?;
    let opts = round_options(vm, &a.arg(0), Some("round() requires an options argument"))?;
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
        return create_zoned(vm, ns, tz, cal, None);
    }
    let dt = tz.datetime_for(ns);
    let r = if unit == Unit::Day {
        let start = tr!(vm, tz.start_of_day(&dt.date));
        let end = tr!(vm, tz.start_of_day(&add_days(dt.date, 1)));
        let rounded = tr!(vm, round_time_to_increment(ns - start, end - start, mode));
        start + rounded
    } else {
        let rd = round_iso_datetime(&dt, increment, unit, mode);
        let offset = tz.offset_ns(ns);
        tr!(
            vm,
            interpret_offset(
                &rd.date,
                Some(rd.time),
                OffsetBehaviour::Option,
                offset,
                &tz,
                Disambiguation::Compatible,
                OffsetOption::Prefer,
                false
            )
        )
    };
    create_zoned(vm, r, tz, cal, None)
}
