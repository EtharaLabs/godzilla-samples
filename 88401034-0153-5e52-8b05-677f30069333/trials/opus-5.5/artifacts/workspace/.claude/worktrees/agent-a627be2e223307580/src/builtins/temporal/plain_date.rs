//! Temporal.PlainDate

use super::calendar::{self, Cal, FieldKind};
use super::dur::*;
use super::fields::*;
use super::iso::*;
use super::*;

pub fn setup(vm: &mut Vm, t: &Obj) {
    let (ctor, proto) = make_class(vm, K::PlainDate, "PlainDate", 3, construct);
    def_method(vm, &ctor, "from", 1, from);
    def_method(vm, &ctor, "compare", 2, compare);
    add_calendar_getters(vm, &proto, K::PlainDate);
    def_method(vm, &proto, "toString", 0, to_string);
    def_method(vm, &proto, "toJSON", 0, to_json);
    def_value_of(vm, &proto, K::PlainDate);
    def_method(vm, &proto, "equals", 1, equals);
    def_method(vm, &proto, "with", 1, with);
    def_method(vm, &proto, "add", 1, add);
    def_method(vm, &proto, "subtract", 1, subtract);
    def_method(vm, &proto, "until", 1, until);
    def_method(vm, &proto, "since", 1, since);
    def_method(vm, &proto, "toPlainDateTime", 0, to_plain_date_time);
    def_method(vm, &proto, "toPlainYearMonth", 0, to_plain_year_month);
    def_method(vm, &proto, "toPlainMonthDay", 0, to_plain_month_day);
    def_method(vm, &proto, "withCalendar", 1, with_calendar);
    def_method(vm, &proto, "toZonedDateTime", 1, to_zoned_date_time);
    finish_class(vm, K::PlainDate, &ctor, &proto);
    t.set_prop(PropKey::from_str("PlainDate"), Value::Obj(ctor), WC);
}

// ---------------------------------------------------------------------------
// Calendar getters shared by PlainDate / PlainDateTime / ZonedDateTime /
// PlainYearMonth / PlainMonthDay
// ---------------------------------------------------------------------------

/// (iso date, calendar) of any date-carrying receiver of kind `k`
pub fn date_of(vm: &mut Vm, this: &Value, k: K) -> JsResult<(IsoDate, Cal)> {
    match (k, slot_of(this)) {
        (K::PlainDate, Some(Slot::Date(d, c))) => Ok((d, c)),
        (K::PlainDateTime, Some(Slot::DateTime(dt, c))) => Ok((dt.date, c)),
        (K::PlainYearMonth, Some(Slot::YearMonth(d, c))) => Ok((d, c)),
        (K::PlainMonthDay, Some(Slot::MonthDay(d, c))) => Ok((d, c)),
        (K::ZonedDateTime, Some(Slot::Zoned(ns, tz, c))) => Ok((tz.datetime_for(ns).date, c)),
        _ => recv_err(vm, k),
    }
}

macro_rules! cal_getter {
    ($name:ident, $k:expr, |$d:ident, $c:ident| $body:expr) => {
        pub fn $name(vm: &mut Vm, a: &Args) -> JsResult<Value> {
            let ($d, $c) = date_of(vm, &a.this, $k)?;
            Ok($body)
        }
    };
}

macro_rules! cal_getters_for {
    ($modname:ident, $k:expr) => {
        pub mod $modname {
            use super::*;
            cal_getter!(year, $k, |d, c| num(calendar::iso_to_date(c, &d).year as f64));
            cal_getter!(era, $k, |d, c| match calendar::era_of(c, &d) {
                Some((e, _)) => Value::str(&e),
                None => Value::Undefined,
            });
            cal_getter!(era_year, $k, |d, c| match calendar::era_of(c, &d) {
                Some((_, y)) => num(y as f64),
                None => Value::Undefined,
            });
            cal_getter!(month, $k, |d, c| num(calendar::iso_to_date(c, &d).month as f64));
            cal_getter!(day, $k, |d, c| num(calendar::iso_to_date(c, &d).day as f64));
            cal_getter!(month_code, $k, |d, c| Value::str(&calendar::iso_to_date(c, &d).month_code.to_string()));
            cal_getter!(calendar_id, $k, |_d, c| Value::str(c.id()));
            cal_getter!(day_of_week, $k, |d, c| num(calendar::day_of_week(c, &d) as f64));
            cal_getter!(day_of_year, $k, |d, c| num(calendar::day_of_year(c, &d) as f64));
            cal_getter!(week_of_year, $k, |d, c| match calendar::week_of_year(c, &d) {
                Some((w, _)) => num(w as f64),
                None => Value::Undefined,
            });
            cal_getter!(year_of_week, $k, |d, c| match calendar::week_of_year(c, &d) {
                Some((_, y)) => num(y as f64),
                None => Value::Undefined,
            });
            cal_getter!(days_in_week, $k, |_d, _c| num(7.0));
            cal_getter!(days_in_month, $k, |d, c| {
                let cd = calendar::iso_to_date(c, &d);
                num(calendar::days_in_month_cal(c, cd.year, cd.month) as f64)
            });
            cal_getter!(days_in_year, $k, |d, c| {
                let cd = calendar::iso_to_date(c, &d);
                num(calendar::days_in_year_cal(c, cd.year) as f64)
            });
            cal_getter!(months_in_year, $k, |d, c| {
                let cd = calendar::iso_to_date(c, &d);
                num(calendar::months_in_year(c, cd.year) as f64)
            });
            cal_getter!(in_leap_year, $k, |d, c| {
                let cd = calendar::iso_to_date(c, &d);
                Value::Bool(calendar::in_leap_year(c, cd.year))
            });
        }
    };
}

cal_getters_for!(g_date, K::PlainDate);
cal_getters_for!(g_datetime, K::PlainDateTime);
cal_getters_for!(g_zoned, K::ZonedDateTime);
cal_getters_for!(g_ym, K::PlainYearMonth);
cal_getters_for!(g_md, K::PlainMonthDay);

pub struct CalGetters {
    pub year: NativeFn,
    pub era: NativeFn,
    pub era_year: NativeFn,
    pub month: NativeFn,
    pub day: NativeFn,
    pub month_code: NativeFn,
    pub calendar_id: NativeFn,
    pub day_of_week: NativeFn,
    pub day_of_year: NativeFn,
    pub week_of_year: NativeFn,
    pub year_of_week: NativeFn,
    pub days_in_week: NativeFn,
    pub days_in_month: NativeFn,
    pub days_in_year: NativeFn,
    pub months_in_year: NativeFn,
    pub in_leap_year: NativeFn,
}

macro_rules! getters_of {
    ($m:ident) => {
        CalGetters {
            year: $m::year,
            era: $m::era,
            era_year: $m::era_year,
            month: $m::month,
            day: $m::day,
            month_code: $m::month_code,
            calendar_id: $m::calendar_id,
            day_of_week: $m::day_of_week,
            day_of_year: $m::day_of_year,
            week_of_year: $m::week_of_year,
            year_of_week: $m::year_of_week,
            days_in_week: $m::days_in_week,
            days_in_month: $m::days_in_month,
            days_in_year: $m::days_in_year,
            months_in_year: $m::months_in_year,
            in_leap_year: $m::in_leap_year,
        }
    };
}

pub fn getters(k: K) -> CalGetters {
    match k {
        K::PlainDate => getters_of!(g_date),
        K::PlainDateTime => getters_of!(g_datetime),
        K::ZonedDateTime => getters_of!(g_zoned),
        K::PlainYearMonth => getters_of!(g_ym),
        _ => getters_of!(g_md),
    }
}

fn add_calendar_getters(vm: &mut Vm, proto: &Obj, k: K) {
    let g = getters(k);
    def_getter(vm, proto, "year", g.year);
    def_getter(vm, proto, "era", g.era);
    def_getter(vm, proto, "eraYear", g.era_year);
    def_getter(vm, proto, "month", g.month);
    def_getter(vm, proto, "day", g.day);
    def_getter(vm, proto, "monthCode", g.month_code);
    def_getter(vm, proto, "calendarId", g.calendar_id);
    def_getter(vm, proto, "dayOfWeek", g.day_of_week);
    def_getter(vm, proto, "dayOfYear", g.day_of_year);
    def_getter(vm, proto, "weekOfYear", g.week_of_year);
    def_getter(vm, proto, "yearOfWeek", g.year_of_week);
    def_getter(vm, proto, "daysInWeek", g.days_in_week);
    def_getter(vm, proto, "daysInMonth", g.days_in_month);
    def_getter(vm, proto, "daysInYear", g.days_in_year);
    def_getter(vm, proto, "monthsInYear", g.months_in_year);
    def_getter(vm, proto, "inLeapYear", g.in_leap_year);
}

// ---------------------------------------------------------------------------
// Conversion
// ---------------------------------------------------------------------------

pub const MSG_DATE_RANGE_STR: &str = "date outside representable range";

/// Parse a PlainDate string (the original's messages)
pub fn parse_date_string(s: &str) -> TRes<(IsoDate, Cal)> {
    if let Some(p) = parse::parse_date_time(s) {
        if p.z {
            return rerr("UTC designator not valid for PlainDate");
        }
        let cal = match &p.calendar {
            None => Cal::Iso8601,
            Some(c) => match Cal::from_id(c) {
                Some(c) => c,
                None => return rerr("unsupported calendar"),
            },
        };
        let d = IsoDate::new(p.year.unwrap_or(0), p.month, p.day.unwrap_or(1));
        if !date_within_limits(&d) {
            return rerr(MSG_DATE_RANGE_STR);
        }
        return Ok((d, cal));
    }
    if let Some(p) = parse::parse_time_only(s) {
        if p.z {
            return rerr("UTC designator not valid for PlainDate");
        }
        return rerr("no date in PlainDate string");
    }
    rerr("invalid date string")
}

/// ToTemporalDate
pub fn to_temporal_date(vm: &mut Vm, item: &Value, options: &Value) -> JsResult<(IsoDate, Cal)> {
    if let Value::Obj(o) = item {
        match slot_of(item) {
            Some(Slot::Date(d, c)) => {
                let opts = get_options_object_strict(vm, options)?;
                get_overflow(vm, &opts)?;
                return Ok((d, c));
            }
            Some(Slot::Zoned(ns, tz, c)) => {
                let dt = tz.datetime_for(ns);
                let opts = get_options_object_strict(vm, options)?;
                get_overflow(vm, &opts)?;
                return Ok((dt.date, c));
            }
            Some(Slot::DateTime(dt, c)) => {
                let opts = get_options_object_strict(vm, options)?;
                get_overflow(vm, &opts)?;
                return Ok((dt.date, c));
            }
            _ => {}
        }
        let cal = get_calendar_with_iso_default(vm, o)?;
        let mut f = prepare_fields(vm, cal, o, F_DATE, Required::List(0))?;
        let opts = get_options_object_strict(vm, options)?;
        let overflow = get_overflow(vm, &opts)?;
        let d = tr!(vm, calendar::date_from_fields(cal, &mut f, overflow));
        return Ok((d, cal));
    }
    let s = match item {
        Value::Str(s) => s.to_rust_string(),
        _ => return vm.throw_type("cannot convert to Temporal.PlainDate"),
    };
    let (d, cal) = tr!(vm, parse_date_string(&s));
    let opts = get_options_object_strict(vm, options)?;
    get_overflow(vm, &opts)?;
    Ok((d, cal))
}

/// GetDifferenceSettings
pub struct DiffSettings {
    pub smallest: Unit,
    pub largest: Unit,
    pub mode: RoundingMode,
    pub increment: i64,
}

#[allow(clippy::too_many_arguments)]
pub fn get_difference_settings(
    vm: &mut Vm,
    since: bool,
    o: &Opts,
    group: UnitGroup,
    disallowed: &[Unit],
    fallback_smallest: Unit,
    smallest_largest_default: Unit,
) -> JsResult<DiffSettings> {
    let largest = get_unit_option(vm, o, "largestUnit")?;
    let increment = get_rounding_increment(vm, o)?;
    let mut mode = get_rounding_mode(vm, o, RoundingMode::Trunc)?;
    let smallest = get_unit_option(vm, o, "smallestUnit")?;
    if since {
        mode = mode.negate();
    }
    // the original validates smallestUnit before largestUnit
    tr!(vm, validate_unit("smallestUnit", smallest, group, &[], false));
    tr!(vm, validate_unit("largestUnit", largest, group, &[], true));
    if let Some(UnitOpt::U(u)) = largest {
        if disallowed.contains(&u) {
            return vm.throw_range("invalid largestUnit");
        }
    }
    let smallest = match smallest {
        Some(UnitOpt::U(u)) => u,
        _ => fallback_smallest,
    };
    if disallowed.contains(&smallest) {
        return vm.throw_range("invalid smallestUnit");
    }
    let default_largest = Unit::larger(smallest_largest_default, smallest);
    let largest = match largest {
        Some(UnitOpt::U(u)) => u,
        _ => default_largest,
    };
    if Unit::larger(largest, smallest) != largest {
        if group == UnitGroup::Time {
            return vm.throw_range("largestUnit cannot be smaller than smallestUnit");
        }
        return vm.throw_range("smallestUnit is larger than largestUnit");
    }
    if let Some(max) = smallest.max_increment() {
        tr!(vm, validate_increment(increment, max, false));
    }
    Ok(DiffSettings { smallest, largest, mode, increment: increment as i64 })
}

// ---------------------------------------------------------------------------
// Constructor & statics
// ---------------------------------------------------------------------------

/// IsValidISODate on float64 integers
pub fn valid_iso_date_f(y: f64, m: f64, d: f64) -> bool {
    (1.0..=12.0).contains(&m) && d >= 1.0 && d <= days_in_month(y as i64, m as u8) as f64
}

/// calendar argument of the constructors
pub fn ctor_calendar(vm: &mut Vm, v: &Value) -> JsResult<Cal> {
    match v {
        Value::Undefined => Ok(Cal::Iso8601),
        Value::Str(s) => match Cal::from_id(&s.to_rust_string()) {
            Some(c) => Ok(c),
            None => vm.throw_range("invalid calendar identifier"),
        },
        _ => vm.throw_type("calendar must be a string"),
    }
}

fn construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = match &a.new_target {
        Some(nt) => nt.clone(),
        None => return vm.throw_type("constructor requires 'new'"),
    };
    let y = to_integer_with_truncation(vm, &a.arg(0))?;
    let m = to_integer_with_truncation(vm, &a.arg(1))?;
    let d = to_integer_with_truncation(vm, &a.arg(2))?;
    let cal = ctor_calendar(vm, &a.arg(3))?;
    if !valid_iso_date_f(y, m, d) {
        return vm.throw_range("ISO date field is out of range");
    }
    create_date(vm, IsoDate::new(y as i64, m as u8, d as u8), cal, Some(&nt))
}

fn from(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, c) = to_temporal_date(vm, &a.arg(0), &a.arg(1))?;
    create_date(vm, d, c, None)
}

fn compare(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (one, _) = to_temporal_date(vm, &a.arg(0), &Value::Undefined)?;
    let (two, _) = to_temporal_date(vm, &a.arg(1), &Value::Undefined)?;
    Ok(num(compare_date(&one, &two) as i32 as f64))
}

// ---------------------------------------------------------------------------
// Methods
// ---------------------------------------------------------------------------

pub fn date_to_string(d: &IsoDate, cal: Cal, show: ShowCalendar) -> String {
    format!("{}{}", fmt_date(d), fmt_calendar_annotation(cal, show))
}

fn to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, c) = this_date(vm, a)?;
    let opts = get_options_object_strict(vm, &a.arg(0))?;
    let show = get_show_calendar(vm, &opts)?;
    Ok(Value::str(&date_to_string(&d, c, show)))
}

fn to_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, c) = this_date(vm, a)?;
    Ok(Value::str(&date_to_string(&d, c, ShowCalendar::Auto)))
}

fn equals(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, c) = this_date(vm, a)?;
    let (o, oc) = to_temporal_date(vm, &a.arg(0), &Value::Undefined)?;
    Ok(Value::Bool(d == o && c == oc))
}

fn with(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, cal) = this_date(vm, a)?;
    let obj = check_partial(vm, &a.arg(0))?;
    let base = calendar::iso_to_fields(cal, &d, FieldKind::Date);
    let partial = prepare_fields(vm, cal, &obj, F_DATE, Required::Partial)?;
    tr!(vm, calendar::check_with_era(cal, &partial));
    let mut merged = calendar::merge_fields(cal, &base, &partial);
    let opts = get_options_object(vm, &a.arg(1))?;
    let overflow = get_overflow(vm, &opts)?;
    let r = tr!(vm, calendar::date_from_fields(cal, &mut merged, overflow));
    create_date(vm, r, cal, None)
}

fn add_sub(vm: &mut Vm, a: &Args, negate: bool) -> JsResult<Value> {
    let (d, cal) = this_date(vm, a)?;
    let mut dur = to_duration(vm, &a.arg(0))?;
    if negate {
        dur = dur.negated();
    }
    let dd = tr!(vm, to_date_duration_without_time(&dur));
    let opts = get_options_object(vm, &a.arg(1))?;
    let overflow = get_overflow(vm, &opts)?;
    let r = tr!(vm, calendar::date_add(cal, &d, &dd, overflow));
    create_date(vm, r, cal, None)
}

fn add(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    add_sub(vm, a, false)
}

fn subtract(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    add_sub(vm, a, true)
}

fn difference(vm: &mut Vm, a: &Args, since: bool) -> JsResult<Value> {
    let (d, cal) = this_date(vm, a)?;
    let (other, ocal) = to_temporal_date(vm, &a.arg(0), &Value::Undefined)?;
    if cal != ocal {
        return vm.throw_range("cannot compare dates in different calendars");
    }
    let opts = get_options_object(vm, &a.arg(1))?;
    let s = get_difference_settings(vm, since, &opts, UnitGroup::Date, &[], Unit::Day, Unit::Day)?;
    if d == other {
        return create_duration(vm, Dur::default(), None);
    }
    let dd = calendar::date_until(cal, &d, &other, s.largest);
    let mut idur = IDur { date: dd, time: 0 };
    if s.smallest != Unit::Day || s.increment != 1 {
        let start = IsoDateTime { date: d, time: Time::MIDNIGHT };
        let dest = utc_epoch_ns(&other, &Time::MIDNIGHT);
        idur = tr!(vm, round_relative(idur, dest, &start, None, cal, s.largest, s.increment, s.smallest, s.mode));
    }
    let mut r = tr!(vm, from_internal(&idur, Unit::Day));
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

fn to_plain_date_time(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, cal) = this_date(vm, a)?;
    let t = super::plain_time::to_time_or_midnight(vm, &a.arg(0))?;
    create_datetime(vm, IsoDateTime { date: d, time: t }, cal, None)
}

fn to_plain_year_month(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, cal) = this_date(vm, a)?;
    let mut f = calendar::iso_to_fields(cal, &d, FieldKind::Date);
    let r = tr!(vm, calendar::year_month_from_fields(cal, &mut f, Overflow::Constrain));
    create_year_month(vm, r, cal, None)
}

fn to_plain_month_day(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, cal) = this_date(vm, a)?;
    let mut f = calendar::iso_to_fields(cal, &d, FieldKind::Date);
    let r = tr!(vm, calendar::month_day_from_fields(cal, &mut f, Overflow::Constrain));
    create_month_day(vm, r, cal, None)
}

fn with_calendar(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, _) = this_date(vm, a)?;
    let cal = with_calendar_arg(vm, &a.arg(0))?;
    create_date(vm, d, cal, None)
}

fn to_zoned_date_time(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, cal) = this_date(vm, a)?;
    let item = a.arg(0);
    let (tz, time_v) = match &item {
        Value::Obj(o) => {
            let tzl = vm.get_str(o, "timeZone")?;
            if tzl.is_undefined() {
                return vm.throw_type("timeZone must be a string or ZonedDateTime");
            } else {
                let tz = to_time_zone_identifier(vm, &tzl)?;
                let pt = vm.get_str(o, "plainTime")?;
                (tz, pt)
            }
        }
        _ => (to_time_zone_identifier(vm, &item)?, Value::Undefined),
    };
    let ns = if time_v.is_undefined() {
        tr!(vm, tz.start_of_day(&d))
    } else {
        let t = super::plain_time::to_temporal_time(vm, &time_v, &Value::Undefined)?;
        let dt = IsoDateTime { date: d, time: t };
        if !datetime_within_limits(&dt.date, &dt.time) {
            return vm.throw_range(MSG_DATETIME_RANGE);
        }
        tr!(vm, tz.epoch_ns_for(&dt, Disambiguation::Compatible))
    };
    create_zoned(vm, ns, tz, cal, None)
}
