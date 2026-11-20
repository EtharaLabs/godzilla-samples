//! Temporal.PlainYearMonth

use super::calendar::{self, Cal, FieldKind};
use super::dur::*;
use super::fields::*;
use super::iso::*;
use super::plain_date::{ctor_calendar, getters, valid_iso_date_f};
use super::*;

pub fn setup(vm: &mut Vm, t: &Obj) {
    let (ctor, proto) = make_class(vm, K::PlainYearMonth, "PlainYearMonth", 2, construct);
    def_method(vm, &ctor, "from", 1, from);
    def_method(vm, &ctor, "compare", 2, compare);
    let g = getters(K::PlainYearMonth);
    def_getter(vm, &proto, "year", g.year);
    def_getter(vm, &proto, "era", g.era);
    def_getter(vm, &proto, "eraYear", g.era_year);
    def_getter(vm, &proto, "month", g.month);
    def_getter(vm, &proto, "monthCode", g.month_code);
    def_getter(vm, &proto, "calendarId", g.calendar_id);
    def_method(vm, &proto, "toPlainDate", 1, to_plain_date);
    def_getter(vm, &proto, "daysInMonth", g.days_in_month);
    def_getter(vm, &proto, "daysInYear", g.days_in_year);
    def_getter(vm, &proto, "monthsInYear", g.months_in_year);
    def_getter(vm, &proto, "inLeapYear", g.in_leap_year);
    def_method(vm, &proto, "toString", 0, to_string);
    def_method(vm, &proto, "toJSON", 0, to_json);
    def_value_of(vm, &proto, K::PlainYearMonth);
    def_method(vm, &proto, "equals", 1, equals);
    def_method(vm, &proto, "with", 1, with);
    def_method(vm, &proto, "add", 1, add);
    def_method(vm, &proto, "subtract", 1, subtract);
    def_method(vm, &proto, "until", 1, until);
    def_method(vm, &proto, "since", 1, since);
    finish_class(vm, K::PlainYearMonth, &ctor, &proto);
    t.set_prop(PropKey::from_str("PlainYearMonth"), Value::Obj(ctor), WC);
}

const MSG_INVALID: &str = "invalid year-month";

/// Parse a PlainYearMonth string: (iso date, calendar) before calendar
/// canonicalisation of the reference day.
pub fn parse_year_month_string(s: &str) -> TRes<(IsoDate, Cal)> {
    let (d, cal) = if let Some(p) = parse::parse_date_time(s) {
        if p.z {
            return rerr(MSG_INVALID);
        }
        let cal = match &p.calendar {
            None => Cal::Iso8601,
            Some(c) => match Cal::from_id(c) {
                Some(c) => c,
                None => return rerr(MSG_INVALID),
            },
        };
        (IsoDate::new(p.year.unwrap_or(0), p.month, p.day.unwrap_or(1)), cal)
    } else if let Some(p) = parse::parse_year_month(s) {
        if let Some(c) = &p.calendar {
            if Cal::from_id(c) != Some(Cal::Iso8601) {
                return rerr(MSG_INVALID);
            }
        }
        (IsoDate::new(p.year.unwrap_or(0), p.month, 1), Cal::Iso8601)
    } else {
        return rerr(MSG_INVALID);
    };
    if !year_month_within_limits(&d) {
        return rerr(MSG_INVALID);
    }
    Ok((d, cal))
}

/// ToTemporalYearMonth
pub fn to_temporal_year_month(vm: &mut Vm, item: &Value, options: &Value) -> JsResult<(IsoDate, Cal)> {
    if let Value::Obj(o) = item {
        if let Some(Slot::YearMonth(d, c)) = slot_of(item) {
            let opts = get_options_object_strict(vm, options)?;
            get_overflow(vm, &opts)?;
            return Ok((d, c));
        }
        let cal = get_calendar_with_iso_default(vm, o)?;
        let mut f = prepare_fields(vm, cal, o, F_YEAR | F_MONTH | F_MONTH_CODE, Required::List(0))?;
        let opts = get_options_object_strict(vm, options)?;
        let overflow = get_overflow(vm, &opts)?;
        let d = tr!(vm, calendar::year_month_from_fields(cal, &mut f, overflow));
        return Ok((d, cal));
    }
    let s = match item {
        Value::Str(s) => s.to_rust_string(),
        _ => return vm.throw_type("cannot convert to Temporal.PlainYearMonth"),
    };
    let (d, cal) = tr!(vm, parse_year_month_string(&s));
    let opts = get_options_object_strict(vm, options)?;
    get_overflow(vm, &opts)?;
    let mut f = calendar::iso_to_fields(cal, &d, FieldKind::YearMonth);
    let r = tr!(vm, calendar::year_month_from_fields(cal, &mut f, Overflow::Constrain));
    Ok((r, cal))
}

fn construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = match &a.new_target {
        Some(nt) => nt.clone(),
        None => return vm.throw_type("constructor requires 'new'"),
    };
    let y = to_integer_with_truncation(vm, &a.arg(0))?;
    let m = to_integer_with_truncation(vm, &a.arg(1))?;
    let cal = ctor_calendar(vm, &a.arg(2))?;
    let rd = a.arg(3);
    let r = if rd.is_undefined() { 1.0 } else { to_integer_with_truncation(vm, &rd)? };
    if !valid_iso_date_f(y, m, r) {
        return vm.throw_range(MSG_INVALID);
    }
    create_year_month(vm, IsoDate::new(y as i64, m as u8, r as u8), cal, Some(&nt))
}

fn from(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, c) = to_temporal_year_month(vm, &a.arg(0), &a.arg(1))?;
    create_year_month(vm, d, c, None)
}

fn compare(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (one, _) = to_temporal_year_month(vm, &a.arg(0), &Value::Undefined)?;
    let (two, _) = to_temporal_year_month(vm, &a.arg(1), &Value::Undefined)?;
    Ok(num(compare_date(&one, &two) as i32 as f64))
}

pub fn year_month_to_string(d: &IsoDate, cal: Cal, show: ShowCalendar) -> String {
    let mut r = format!("{}-{:02}", pad_year(d.year), d.month);
    if matches!(show, ShowCalendar::Always | ShowCalendar::Critical) || cal != Cal::Iso8601 {
        r += &format!("-{:02}", d.day);
    }
    r + &fmt_calendar_annotation(cal, show)
}

fn to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, c) = this_year_month(vm, a)?;
    let opts = get_options_object_strict(vm, &a.arg(0))?;
    let show = get_show_calendar(vm, &opts)?;
    Ok(Value::str(&year_month_to_string(&d, c, show)))
}

fn to_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, c) = this_year_month(vm, a)?;
    Ok(Value::str(&year_month_to_string(&d, c, ShowCalendar::Auto)))
}

fn equals(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, c) = this_year_month(vm, a)?;
    let (o, oc) = to_temporal_year_month(vm, &a.arg(0), &Value::Undefined)?;
    Ok(Value::Bool(d == o && c == oc))
}

fn with(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, cal) = this_year_month(vm, a)?;
    let obj = check_partial(vm, &a.arg(0))?;
    let base = calendar::iso_to_fields(cal, &d, FieldKind::YearMonth);
    let partial = prepare_fields(vm, cal, &obj, F_YEAR | F_MONTH | F_MONTH_CODE, Required::Partial)?;
    tr!(vm, calendar::check_with_era(cal, &partial));
    let mut merged = calendar::merge_fields(cal, &base, &partial);
    let opts = get_options_object(vm, &a.arg(1))?;
    let overflow = get_overflow(vm, &opts)?;
    let r = tr!(vm, calendar::year_month_from_fields(cal, &mut merged, overflow));
    create_year_month(vm, r, cal, None)
}

fn add_sub(vm: &mut Vm, a: &Args, negate: bool) -> JsResult<Value> {
    let (d, cal) = this_year_month(vm, a)?;
    let mut dur = to_duration(vm, &a.arg(0))?;
    if negate {
        dur = dur.negated();
    }
    let opts = get_options_object(vm, &a.arg(1))?;
    let overflow = get_overflow(vm, &opts)?;
    if dur.fields()[2..].iter().any(|v| *v != 0.0) {
        return vm.throw_range("cannot add units smaller than months to a PlainYearMonth");
    }
    let mut f = calendar::iso_to_fields(cal, &d, FieldKind::YearMonth);
    f.day = Some(1.0);
    let start = tr!(vm, calendar::date_from_fields(cal, &mut f, Overflow::Constrain));
    let dd = tr!(vm, to_date_duration_without_time(&dur));
    let added = tr!(vm, calendar::date_add(cal, &start, &dd, overflow));
    let mut af = calendar::iso_to_fields(cal, &added, FieldKind::YearMonth);
    let r = tr!(vm, calendar::year_month_from_fields(cal, &mut af, overflow));
    create_year_month(vm, r, cal, None)
}

fn add(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    add_sub(vm, a, false)
}

fn subtract(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    add_sub(vm, a, true)
}

fn difference(vm: &mut Vm, a: &Args, since: bool) -> JsResult<Value> {
    let (d, cal) = this_year_month(vm, a)?;
    let (other, ocal) = to_temporal_year_month(vm, &a.arg(0), &Value::Undefined)?;
    if cal != ocal {
        return vm.throw_range("cannot compare dates in different calendars");
    }
    let opts = get_options_object(vm, &a.arg(1))?;
    // GetDifferenceSettings(date, « week, day », month, year)
    let largest = get_unit_option(vm, &opts, "largestUnit")?;
    let increment = get_rounding_increment(vm, &opts)?;
    let mut mode = get_rounding_mode(vm, &opts, RoundingMode::Trunc)?;
    let smallest = get_unit_option(vm, &opts, "smallestUnit")?;
    if since {
        mode = mode.negate();
    }
    let smallest = match smallest {
        None => Unit::Month,
        Some(UnitOpt::U(u)) if u == Unit::Year || u == Unit::Month => u,
        Some(UnitOpt::Auto) => return vm.throw_range("invalid smallestUnit"),
        Some(_) => return vm.throw_range("smallestUnit must be year or month"),
    };
    let largest = match largest {
        None | Some(UnitOpt::Auto) => None,
        Some(UnitOpt::U(u)) if u == Unit::Year || u == Unit::Month => Some(u),
        Some(_) => return vm.throw_range("largestUnit must be year or month"),
    };
    let largest = largest.unwrap_or(Unit::larger(Unit::Year, smallest));
    if Unit::larger(largest, smallest) != largest {
        return vm.throw_range("smallestUnit is larger than largestUnit");
    }
    if d == other {
        return create_duration(vm, Dur::default(), None);
    }
    let mut tf = calendar::iso_to_fields(cal, &d, FieldKind::YearMonth);
    tf.day = Some(1.0);
    let this_date = tr!(vm, calendar::date_from_fields(cal, &mut tf, Overflow::Constrain));
    let mut of = calendar::iso_to_fields(cal, &other, FieldKind::YearMonth);
    of.day = Some(1.0);
    let other_date = tr!(vm, calendar::date_from_fields(cal, &mut of, Overflow::Constrain));
    let dd = calendar::date_until(cal, &this_date, &other_date, largest);
    let ym = tr!(vm, dd.adjust(0, Some(0), None));
    let mut idur = IDur { date: ym, time: 0 };
    if smallest != Unit::Month || increment != 1 {
        let start = IsoDateTime { date: this_date, time: Time::MIDNIGHT };
        let dest = utc_epoch_ns(&other_date, &Time::MIDNIGHT);
        idur = tr!(vm, round_relative(idur, dest, &start, None, cal, largest, increment as i64, smallest, mode));
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

fn to_plain_date(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, cal) = this_year_month(vm, a)?;
    let item = match a.arg(0) {
        Value::Obj(o) => o,
        _ => return vm.throw_type("toPlainDate() argument must be an object"),
    };
    let base = calendar::iso_to_fields(cal, &d, FieldKind::YearMonth);
    let input = prepare_fields(vm, cal, &item, F_DAY, Required::List(0))?;
    if input.day.is_none() {
        return vm.throw_type("toPlainDate() requires a day");
    }
    let mut merged = calendar::merge_fields(cal, &base, &input);
    let r = tr!(vm, calendar::date_from_fields(cal, &mut merged, Overflow::Constrain));
    create_date(vm, r, cal, None)
}
