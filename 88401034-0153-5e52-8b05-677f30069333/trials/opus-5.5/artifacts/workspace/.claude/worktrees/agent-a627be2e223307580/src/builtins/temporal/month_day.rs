//! Temporal.PlainMonthDay

use super::calendar::{self, Cal, FieldKind};
use super::fields::*;
use super::iso::*;
use super::plain_date::{ctor_calendar, getters, valid_iso_date_f};
use super::*;

pub fn setup(vm: &mut Vm, t: &Obj) {
    let (ctor, proto) = make_class(vm, K::PlainMonthDay, "PlainMonthDay", 2, construct);
    def_method(vm, &ctor, "from", 1, from);
    let g = getters(K::PlainMonthDay);
    def_getter(vm, &proto, "monthCode", g.month_code);
    def_getter(vm, &proto, "day", g.day);
    def_getter(vm, &proto, "calendarId", g.calendar_id);
    def_method(vm, &proto, "toString", 0, to_string);
    def_method(vm, &proto, "toJSON", 0, to_json);
    def_value_of(vm, &proto, K::PlainMonthDay);
    def_method(vm, &proto, "equals", 1, equals);
    def_method(vm, &proto, "with", 1, with);
    def_method(vm, &proto, "toPlainDate", 1, to_plain_date);
    finish_class(vm, K::PlainMonthDay, &ctor, &proto);
    t.set_prop(PropKey::from_str("PlainMonthDay"), Value::Obj(ctor), WC);
}

const MSG_INVALID: &str = "invalid month-day";

/// Parse a PlainMonthDay string into its ISO reference date
pub fn parse_month_day_string(s: &str) -> TRes<(IsoDate, Cal)> {
    if let Some(p) = parse::parse_date_time(s) {
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
        let d = IsoDate::new(p.year.unwrap_or(0), p.month, p.day.unwrap_or(1));
        if cal == Cal::Iso8601 {
            return Ok((IsoDate::new(1972, d.month, d.day), cal));
        }
        if !date_within_limits(&d) {
            return rerr(MSG_INVALID);
        }
        let mut f = calendar::iso_to_fields(cal, &d, FieldKind::MonthDay);
        let r = calendar::month_day_from_fields(cal, &mut f, Overflow::Constrain)?;
        return Ok((r, cal));
    }
    if let Some(p) = parse::parse_month_day(s) {
        if let Some(c) = &p.calendar {
            if Cal::from_id(c) != Some(Cal::Iso8601) {
                return rerr(MSG_INVALID);
            }
        }
        return Ok((IsoDate::new(1972, p.month, p.day.unwrap_or(1)), Cal::Iso8601));
    }
    rerr(MSG_INVALID)
}

/// ToTemporalMonthDay
pub fn to_temporal_month_day(vm: &mut Vm, item: &Value, options: &Value) -> JsResult<(IsoDate, Cal)> {
    if let Value::Obj(o) = item {
        if let Some(Slot::MonthDay(d, c)) = slot_of(item) {
            let opts = get_options_object_strict(vm, options)?;
            get_overflow(vm, &opts)?;
            return Ok((d, c));
        }
        let cal = get_calendar_with_iso_default(vm, o)?;
        let mut f = prepare_fields(vm, cal, o, F_DATE, Required::List(0))?;
        let opts = get_options_object_strict(vm, options)?;
        let overflow = get_overflow(vm, &opts)?;
        let d = tr!(vm, calendar::month_day_from_fields(cal, &mut f, overflow));
        return Ok((d, cal));
    }
    let s = match item {
        Value::Str(s) => s.to_rust_string(),
        _ => return vm.throw_type("cannot convert to Temporal.PlainMonthDay"),
    };
    let r = tr!(vm, parse_month_day_string(&s));
    let opts = get_options_object_strict(vm, options)?;
    get_overflow(vm, &opts)?;
    Ok(r)
}

fn construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = match &a.new_target {
        Some(nt) => nt.clone(),
        None => return vm.throw_type("constructor requires 'new'"),
    };
    let m = to_integer_with_truncation(vm, &a.arg(0))?;
    let d = to_integer_with_truncation(vm, &a.arg(1))?;
    let cal = ctor_calendar(vm, &a.arg(2))?;
    let ry = a.arg(3);
    let y = if ry.is_undefined() { 1972.0 } else { to_integer_with_truncation(vm, &ry)? };
    if !valid_iso_date_f(y, m, d) {
        return vm.throw_range("ISO date field is out of range");
    }
    create_month_day(vm, IsoDate::new(y as i64, m as u8, d as u8), cal, Some(&nt))
}

fn from(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, c) = to_temporal_month_day(vm, &a.arg(0), &a.arg(1))?;
    create_month_day(vm, d, c, None)
}

pub fn month_day_to_string(d: &IsoDate, cal: Cal, show: ShowCalendar) -> String {
    let mut r = format!("{:02}-{:02}", d.month, d.day);
    if matches!(show, ShowCalendar::Always | ShowCalendar::Critical) || cal != Cal::Iso8601 {
        r = format!("{}-{}", pad_year(d.year), r);
    }
    r + &fmt_calendar_annotation(cal, show)
}

fn to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, c) = this_month_day(vm, a)?;
    let opts = get_options_object(vm, &a.arg(0))?;
    let show = get_show_calendar(vm, &opts)?;
    Ok(Value::str(&month_day_to_string(&d, c, show)))
}

fn to_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, c) = this_month_day(vm, a)?;
    Ok(Value::str(&month_day_to_string(&d, c, ShowCalendar::Auto)))
}

fn equals(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, c) = this_month_day(vm, a)?;
    let (o, oc) = to_temporal_month_day(vm, &a.arg(0), &Value::Undefined)?;
    Ok(Value::Bool(d == o && c == oc))
}

fn with(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, cal) = this_month_day(vm, a)?;
    let obj = check_partial(vm, &a.arg(0))?;
    let base = calendar::iso_to_fields(cal, &d, FieldKind::MonthDay);
    let partial = prepare_fields(vm, cal, &obj, F_DATE, Required::Partial)?;
    tr!(vm, calendar::check_with_era(cal, &partial));
    let mut merged = calendar::merge_fields(cal, &base, &partial);
    let opts = get_options_object(vm, &a.arg(1))?;
    let overflow = get_overflow(vm, &opts)?;
    let r = tr!(vm, calendar::month_day_from_fields(cal, &mut merged, overflow));
    create_month_day(vm, r, cal, None)
}

fn to_plain_date(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (d, cal) = this_month_day(vm, a)?;
    let item = match a.arg(0) {
        Value::Obj(o) => o,
        _ => return vm.throw_type("toPlainDate() argument must be an object"),
    };
    let mut base = calendar::iso_to_fields(cal, &d, FieldKind::MonthDay);
    // the original merges the ISO reference day, not the calendar day
    base.day = Some(d.day as f64);
    let input = prepare_fields(vm, cal, &item, F_YEAR, Required::List(0))?;
    if input.year.is_none() && !(input.era.is_some() && input.era_year.is_some()) {
        return vm.throw_type("toPlainDate() requires a year");
    }
    let mut merged = calendar::merge_fields(cal, &base, &input);
    let r = tr!(vm, calendar::date_from_fields(cal, &mut merged, Overflow::Constrain));
    create_date(vm, r, cal, None)
}
