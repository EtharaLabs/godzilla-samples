// Date constructor and prototype.

use crate::datetime as dt;
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let proto = vm.intr.date_proto.clone();
    let ctor = vm.native_ctor("Date", 7, date_ctor, &proto);
    vm.def_method(&ctor, "now", 0, date_now);
    vm.def_method(&ctor, "parse", 1, date_parse);
    vm.def_method(&ctor, "UTC", 7, date_utc);
    let getters: &[(&str, NativeFn)] = &[
        ("getDate", |vm, a| getter(vm, a, |t| dt::date_from_time(dt::local_time(t)))),
        ("getDay", |vm, a| getter(vm, a, |t| dt::week_day(dt::local_time(t)))),
        ("getFullYear", |vm, a| getter(vm, a, |t| dt::year_from_time(dt::local_time(t)))),
        ("getHours", |vm, a| getter(vm, a, |t| dt::hour_from_time(dt::local_time(t)))),
        ("getMilliseconds", |vm, a| getter(vm, a, |t| dt::ms_from_time(dt::local_time(t)))),
        ("getMinutes", |vm, a| getter(vm, a, |t| dt::min_from_time(dt::local_time(t)))),
        ("getMonth", |vm, a| getter(vm, a, |t| dt::month_from_time(dt::local_time(t)))),
        ("getSeconds", |vm, a| getter(vm, a, |t| dt::sec_from_time(dt::local_time(t)))),
        ("getTime", |vm, a| getter(vm, a, |t| t)),
        ("getTimezoneOffset", |vm, a| getter(vm, a, |t| (t - dt::local_time(t)) / 60000.0)),
        ("getUTCDate", |vm, a| getter(vm, a, dt::date_from_time)),
        ("getUTCDay", |vm, a| getter(vm, a, dt::week_day)),
        ("getUTCFullYear", |vm, a| getter(vm, a, dt::year_from_time)),
        ("getUTCHours", |vm, a| getter(vm, a, dt::hour_from_time)),
        ("getUTCMilliseconds", |vm, a| getter(vm, a, dt::ms_from_time)),
        ("getUTCMinutes", |vm, a| getter(vm, a, dt::min_from_time)),
        ("getUTCMonth", |vm, a| getter(vm, a, dt::month_from_time)),
        ("getUTCSeconds", |vm, a| getter(vm, a, dt::sec_from_time)),
        ("getYear", |vm, a| getter(vm, a, |t| dt::year_from_time(dt::local_time(t)) - 1900.0)),
        ("valueOf", |vm, a| getter(vm, a, |t| t)),
    ];
    for (n, f) in getters {
        vm.def_method(&proto, n, 0, *f);
    }
    let setters: &[(&str, u32, NativeFn)] = &[
        ("setDate", 1, |vm, a| set_date_part(vm, a, 2, true)),
        ("setFullYear", 3, |vm, a| set_date_part(vm, a, 0, true)),
        ("setHours", 4, |vm, a| set_time_part(vm, a, 0, true)),
        ("setMilliseconds", 1, |vm, a| set_time_part(vm, a, 3, true)),
        ("setMinutes", 3, |vm, a| set_time_part(vm, a, 1, true)),
        ("setMonth", 2, |vm, a| set_date_part(vm, a, 1, true)),
        ("setSeconds", 2, |vm, a| set_time_part(vm, a, 2, true)),
        ("setTime", 1, set_time),
        ("setUTCDate", 1, |vm, a| set_date_part(vm, a, 2, false)),
        ("setUTCFullYear", 3, |vm, a| set_date_part(vm, a, 0, false)),
        ("setUTCHours", 4, |vm, a| set_time_part(vm, a, 0, false)),
        ("setUTCMilliseconds", 1, |vm, a| set_time_part(vm, a, 3, false)),
        ("setUTCMinutes", 3, |vm, a| set_time_part(vm, a, 1, false)),
        ("setUTCMonth", 2, |vm, a| set_date_part(vm, a, 1, false)),
        ("setUTCSeconds", 2, |vm, a| set_time_part(vm, a, 2, false)),
        ("setYear", 1, set_year),
    ];
    for (n, l, f) in setters {
        vm.def_method(&proto, n, *l, *f);
    }
    vm.def_method(&proto, "toDateString", 0, |vm, a| string_method(vm, a, dt::to_date_only_string));
    vm.def_method(&proto, "toISOString", 0, to_iso_string);
    vm.def_method(&proto, "toJSON", 1, to_json);
    vm.def_method(&proto, "toLocaleDateString", 0, |vm, a| locale_method(vm, a, 1));
    vm.def_method(&proto, "toLocaleString", 0, |vm, a| locale_method(vm, a, 0));
    vm.def_method(&proto, "toLocaleTimeString", 0, |vm, a| locale_method(vm, a, 2));
    vm.def_method(&proto, "toString", 0, |vm, a| string_method(vm, a, dt::to_date_string));
    vm.def_method(&proto, "toTimeString", 0, |vm, a| string_method(vm, a, dt::to_time_only_string));
    let utc = vm.def_method(&proto, "toUTCString", 0, |vm, a| string_method(vm, a, dt::to_utc_string));
    proto.set_prop(PropKey::from_str("toGMTString"), Value::Obj(utc), WC);
    vm.def_method(&proto, "toTemporalInstant", 0, to_temporal_instant);
    let tp = vm.native_fn("[Symbol.toPrimitive]", 1, to_primitive);
    proto.set_prop(PropKey::Sym(vm.intr.sym_to_primitive.clone()), Value::Obj(tp), CONFIGURABLE);
    vm.def_global("Date", Value::Obj(ctor));
}

pub fn this_time(vm: &mut Vm, v: &Value) -> JsResult<f64> {
    match v {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Date(t) => Ok(*t),
            _ => Err(vm.make_error("TypeError", "this is not a Date object")),
        },
        _ => vm.throw_type("this is not a Date object"),
    }
}

fn set_this_time(v: &Value, t: f64) {
    if let Value::Obj(o) = v {
        if let ObjKind::Date(x) = &mut o.borrow_mut().kind {
            *x = t;
        }
    }
}

fn getter(vm: &mut Vm, a: &Args, f: fn(f64) -> f64) -> JsResult<Value> {
    let t = this_time(vm, &a.this)?;
    if t.is_nan() {
        return Ok(Value::Num(f64::NAN));
    }
    Ok(Value::Num(f(t)))
}

fn make_date_from_args(vm: &mut Vm, args: &[Value]) -> JsResult<f64> {
    let mut nums = Vec::new();
    for v in args.iter().take(7) {
        nums.push(vm.to_number(v)?);
    }
    let y = nums[0];
    let m = nums.get(1).copied().unwrap_or(0.0);
    let d = nums.get(2).copied().unwrap_or(1.0);
    let h = nums.get(3).copied().unwrap_or(0.0);
    let mi = nums.get(4).copied().unwrap_or(0.0);
    let s = nums.get(5).copied().unwrap_or(0.0);
    let ms = nums.get(6).copied().unwrap_or(0.0);
    let yr = if y.is_nan() {
        y
    } else {
        let yi = crate::ops::integer_or_infinity(y);
        if (0.0..=99.0).contains(&yi) {
            1900.0 + yi
        } else {
            y
        }
    };
    Ok(dt::make_date(dt::make_day(yr, m, d), dt::make_time(h, mi, s, ms)))
}

fn date_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return Ok(Value::str(&dt::to_date_string(dt::now_ms())));
    }
    let t = match a.args.len() {
        0 => dt::now_ms(),
        1 => {
            let v = &a.args[0];
            let tv = match v {
                Value::Obj(o) if matches!(o.borrow().kind, ObjKind::Date(_)) => match &o.borrow().kind {
                    ObjKind::Date(t) => *t,
                    _ => unreachable!(),
                },
                _ => {
                    let p = vm.to_primitive(v, crate::ops::Hint::Default)?;
                    match &p {
                        Value::Str(s) => dt::parse_for_constructor(&s.to_rust_string()),
                        _ => vm.to_number(&p)?,
                    }
                }
            };
            dt::time_clip(tv)
        }
        _ => {
            let t = make_date_from_args(vm, a.args)?;
            dt::time_clip(dt::utc(t))
        }
    };
    let proto = vm.proto_from_nt(&a.new_target, &vm.intr.date_proto.clone())?;
    Ok(Value::Obj(Obj::with_class(Some(proto), ObjKind::Date(t), "Date")))
}

fn date_now(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Num(dt::now_ms()))
}

fn date_parse(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    Ok(Value::Num(dt::parse(&s.to_rust_string())))
}

fn date_utc(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.args.is_empty() {
        return Ok(Value::Num(f64::NAN));
    }
    let t = make_date_from_args(vm, a.args)?;
    Ok(Value::Num(dt::time_clip(t)))
}

fn set_time(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    this_time(vm, &a.this)?;
    let t = vm.to_number(&a.arg(0))?;
    let v = dt::time_clip(t);
    set_this_time(&a.this, v);
    Ok(Value::Num(v))
}

/// which: 0 hours, 1 minutes, 2 seconds, 3 ms
fn set_time_part(vm: &mut Vm, a: &Args, which: usize, local: bool) -> JsResult<Value> {
    let t0 = this_time(vm, &a.this)?;
    let t = if local { dt::local_time(t0) } else { t0 };
    let mut nums = Vec::new();
    let maxn = 4 - which;
    for i in 0..maxn.min(a.args.len().max(1)) {
        nums.push(vm.to_number(&a.arg(i))?);
    }
    if t0.is_nan() {
        return Ok(Value::Num(f64::NAN));
    }
    let mut h = dt::hour_from_time(t);
    let mut m = dt::min_from_time(t);
    let mut s = dt::sec_from_time(t);
    let mut ms = dt::ms_from_time(t);
    for (i, n) in nums.into_iter().enumerate() {
        match which + i {
            0 => h = n,
            1 => m = n,
            2 => s = n,
            _ => ms = n,
        }
    }
    let date = dt::make_date(dt::day(t), dt::make_time(h, m, s, ms));
    let u = dt::time_clip(if local { dt::utc(date) } else { date });
    set_this_time(&a.this, u);
    Ok(Value::Num(u))
}

/// which: 0 year, 1 month, 2 date
fn set_date_part(vm: &mut Vm, a: &Args, which: usize, local: bool) -> JsResult<Value> {
    let t0 = this_time(vm, &a.this)?;
    let mut t = if local { dt::local_time(t0) } else { t0 };
    let maxn = 3 - which;
    let mut nums = Vec::new();
    for i in 0..maxn.min(a.args.len().max(1)) {
        nums.push(vm.to_number(&a.arg(i))?);
    }
    if t0.is_nan() {
        if which == 0 {
            t = 0.0;
        } else {
            return Ok(Value::Num(f64::NAN));
        }
    }
    let mut y = dt::year_from_time(t);
    let mut mo = dt::month_from_time(t);
    let mut d = dt::date_from_time(t);
    for (i, n) in nums.into_iter().enumerate() {
        match which + i {
            0 => y = n,
            1 => mo = n,
            _ => d = n,
        }
    }
    let date = dt::make_date(dt::make_day(y, mo, d), dt::time_within_day(t));
    let u = dt::time_clip(if local { dt::utc(date) } else { date });
    set_this_time(&a.this, u);
    Ok(Value::Num(u))
}

fn set_year(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t0 = this_time(vm, &a.this)?;
    let t = if t0.is_nan() { 0.0 } else { dt::local_time(t0) };
    let y = vm.to_number(&a.arg(0))?;
    if y.is_nan() {
        set_this_time(&a.this, f64::NAN);
        return Ok(Value::Num(f64::NAN));
    }
    let yi = crate::ops::integer_or_infinity(y);
    let yyyy = if (0.0..=99.0).contains(&yi) { 1900.0 + yi } else { y };
    let d = dt::make_day(yyyy, dt::month_from_time(t), dt::date_from_time(t));
    let u = dt::time_clip(dt::utc(dt::make_date(d, dt::time_within_day(t))));
    set_this_time(&a.this, u);
    Ok(Value::Num(u))
}

fn string_method(vm: &mut Vm, a: &Args, f: fn(f64) -> String) -> JsResult<Value> {
    let t = this_time(vm, &a.this)?;
    Ok(Value::str(&f(t)))
}

fn to_iso_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t = this_time(vm, &a.this)?;
    match dt::to_iso_string(t) {
        Some(s) => Ok(Value::str(&s)),
        None => vm.throw_range("Invalid time value"),
    }
}

fn to_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = vm.to_object(&a.this)?;
    let ov = Value::Obj(o.clone());
    let tv = vm.to_primitive(&ov, crate::ops::Hint::Number)?;
    if let Value::Num(n) = tv {
        if !n.is_finite() {
            return Ok(Value::Null);
        }
    }
    let f = vm.get_str(&o, "toISOString")?;
    if !f.is_callable() {
        return vm.throw_type("toISOString is not a function");
    }
    vm.call(&f, ov, &[])
}

fn locale_method(vm: &mut Vm, a: &Args, kind: u8) -> JsResult<Value> {
    let t = this_time(vm, &a.this)?;
    if t.is_nan() {
        return Ok(Value::str("Invalid Date"));
    }
    let locales = crate::builtins::intl::locale_list(vm, &a.arg(0))?;
    let opts = crate::builtins::intl::read_dtf_options(vm, &a.arg(1))?;
    let r = match kind {
        0 => dt::to_locale_string(t, &locales, &opts),
        1 => dt::to_locale_date_string(t, &locales, &opts),
        _ => dt::to_locale_time_string(t, &locales, &opts),
    };
    match r {
        Ok(s) => Ok(Value::str(&s)),
        Err(e) => crate::builtins::intl::throw_dt_error(vm, e),
    }
}

fn to_primitive(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("Date.prototype[Symbol.toPrimitive] on non-object"),
    };
    let hint = match a.arg(0) {
        Value::Str(s) => s.to_rust_string(),
        _ => return vm.throw_type("invalid Symbol.toPrimitive hint"),
    };
    let order: [&str; 2] = match hint.as_str() {
        "string" | "default" => ["toString", "valueOf"],
        "number" => ["valueOf", "toString"],
        _ => return vm.throw_type("invalid Symbol.toPrimitive hint"),
    };
    let ov = Value::Obj(o.clone());
    for n in order {
        let f = vm.get_str(&o, n)?;
        if f.is_callable() {
            let r = vm.call(&f, ov.clone(), &[])?;
            if !r.is_object() {
                return Ok(r);
            }
        }
    }
    vm.throw_type("cannot convert object to primitive value")
}

fn to_temporal_instant(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t = this_time(vm, &a.this)?;
    crate::builtins::temporal::instant_from_ms(vm, t)
}
