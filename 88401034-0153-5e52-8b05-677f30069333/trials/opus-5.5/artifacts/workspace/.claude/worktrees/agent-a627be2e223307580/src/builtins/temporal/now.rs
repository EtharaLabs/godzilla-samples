//! Temporal.Now

use super::calendar::Cal;
use super::fields::to_time_zone_identifier;
use super::tz::Tz;
use super::*;

pub fn setup(vm: &mut Vm, t: &Obj) {
    let now = vm.new_object();
    def_method(vm, &now, "instant", 0, instant);
    def_method(vm, &now, "timeZoneId", 0, time_zone_id);
    def_method(vm, &now, "zonedDateTimeISO", 0, zoned_date_time_iso);
    def_method(vm, &now, "plainDateISO", 0, plain_date_iso);
    def_method(vm, &now, "plainTimeISO", 0, plain_time_iso);
    def_method(vm, &now, "plainDateTimeISO", 0, plain_date_time_iso);
    vm.set_tag(&now, "Temporal.Now");
    t.set_prop(PropKey::from_str("Now"), Value::Obj(now), WC);
}

/// SystemUTCEpochNanoseconds (millisecond resolution, like the original)
fn now_ns() -> i128 {
    crate::datetime::now_ms() as i128 * 1_000_000
}

fn tz_arg(vm: &mut Vm, v: &Value) -> JsResult<Tz> {
    if v.is_undefined() {
        return Ok(Tz::utc());
    }
    to_time_zone_identifier(vm, v)
}

fn instant(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    create_instant(vm, now_ns(), None)
}

fn time_zone_id(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::str("UTC"))
}

fn zoned_date_time_iso(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let tz = tz_arg(vm, &a.arg(0))?;
    create_zoned(vm, now_ns(), tz, Cal::Iso8601, None)
}

fn plain_date_iso(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let tz = tz_arg(vm, &a.arg(0))?;
    let dt = tz.datetime_for(now_ns());
    create_date(vm, dt.date, Cal::Iso8601, None)
}

fn plain_time_iso(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let tz = tz_arg(vm, &a.arg(0))?;
    let dt = tz.datetime_for(now_ns());
    create_time(vm, dt.time, None)
}

fn plain_date_time_iso(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let tz = tz_arg(vm, &a.arg(0))?;
    let dt = tz.datetime_for(now_ns());
    create_datetime(vm, dt, Cal::Iso8601, None)
}
