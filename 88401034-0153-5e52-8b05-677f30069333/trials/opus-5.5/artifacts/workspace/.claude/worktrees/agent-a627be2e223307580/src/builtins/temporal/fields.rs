//! Property-bag reading: PrepareCalendarFields, ToTemporalTimeRecord,
//! ToTemporalPartialDurationRecord and the calendar / time zone
//! identifier conversions.

use super::calendar::Cal;
use super::dur::Dur;
use super::iso::*;
use super::tz::Tz;
use super::*;

pub const F_DAY: u32 = 1 << 0;
pub const F_ERA: u32 = 1 << 1;
pub const F_ERA_YEAR: u32 = 1 << 2;
pub const F_HOUR: u32 = 1 << 3;
pub const F_MICROSECOND: u32 = 1 << 4;
pub const F_MILLISECOND: u32 = 1 << 5;
pub const F_MINUTE: u32 = 1 << 6;
pub const F_MONTH: u32 = 1 << 7;
pub const F_MONTH_CODE: u32 = 1 << 8;
pub const F_NANOSECOND: u32 = 1 << 9;
pub const F_OFFSET: u32 = 1 << 10;
pub const F_SECOND: u32 = 1 << 11;
pub const F_TIME_ZONE: u32 = 1 << 12;
pub const F_YEAR: u32 = 1 << 13;

pub const F_DATE: u32 = F_YEAR | F_MONTH | F_MONTH_CODE | F_DAY;
pub const F_TIME: u32 = F_HOUR | F_MINUTE | F_SECOND | F_MILLISECOND | F_MICROSECOND | F_NANOSECOND;

const ORDER: [(u32, &str); 14] = [
    (F_DAY, "day"),
    (F_ERA, "era"),
    (F_ERA_YEAR, "eraYear"),
    (F_HOUR, "hour"),
    (F_MICROSECOND, "microsecond"),
    (F_MILLISECOND, "millisecond"),
    (F_MINUTE, "minute"),
    (F_MONTH, "month"),
    (F_MONTH_CODE, "monthCode"),
    (F_NANOSECOND, "nanosecond"),
    (F_OFFSET, "offset"),
    (F_SECOND, "second"),
    (F_TIME_ZONE, "timeZone"),
    (F_YEAR, "year"),
];

/// Calendar Fields Record (unset = None)
#[derive(Clone, Default, Debug)]
pub struct Fields {
    pub era: Option<String>,
    pub era_year: Option<f64>,
    pub year: Option<f64>,
    pub month: Option<f64>,
    pub month_code: Option<String>,
    pub day: Option<f64>,
    pub hour: Option<f64>,
    pub minute: Option<f64>,
    pub second: Option<f64>,
    pub millisecond: Option<f64>,
    pub microsecond: Option<f64>,
    pub nanosecond: Option<f64>,
    pub offset: Option<String>,
    pub time_zone: Option<Tz>,
}

impl Fields {
    pub fn present(&self) -> u32 {
        let mut m = 0;
        if self.era.is_some() {
            m |= F_ERA;
        }
        if self.era_year.is_some() {
            m |= F_ERA_YEAR;
        }
        if self.year.is_some() {
            m |= F_YEAR;
        }
        if self.month.is_some() {
            m |= F_MONTH;
        }
        if self.month_code.is_some() {
            m |= F_MONTH_CODE;
        }
        if self.day.is_some() {
            m |= F_DAY;
        }
        if self.hour.is_some() {
            m |= F_HOUR;
        }
        if self.minute.is_some() {
            m |= F_MINUTE;
        }
        if self.second.is_some() {
            m |= F_SECOND;
        }
        if self.millisecond.is_some() {
            m |= F_MILLISECOND;
        }
        if self.microsecond.is_some() {
            m |= F_MICROSECOND;
        }
        if self.nanosecond.is_some() {
            m |= F_NANOSECOND;
        }
        if self.offset.is_some() {
            m |= F_OFFSET;
        }
        if self.time_zone.is_some() {
            m |= F_TIME_ZONE;
        }
        m
    }

    /// Copy the field `flag` from `o`.
    pub fn copy_from(&mut self, o: &Fields, flag: u32) {
        match flag {
            F_ERA => self.era = o.era.clone(),
            F_ERA_YEAR => self.era_year = o.era_year,
            F_YEAR => self.year = o.year,
            F_MONTH => self.month = o.month,
            F_MONTH_CODE => self.month_code = o.month_code.clone(),
            F_DAY => self.day = o.day,
            F_HOUR => self.hour = o.hour,
            F_MINUTE => self.minute = o.minute,
            F_SECOND => self.second = o.second,
            F_MILLISECOND => self.millisecond = o.millisecond,
            F_MICROSECOND => self.microsecond = o.microsecond,
            F_NANOSECOND => self.nanosecond = o.nanosecond,
            F_OFFSET => self.offset = o.offset.clone(),
            F_TIME_ZONE => self.time_zone = o.time_zone.clone(),
            _ => {}
        }
    }

    pub fn set_time(&mut self, t: &Time) {
        self.hour = Some(t.hour as f64);
        self.minute = Some(t.minute as f64);
        self.second = Some(t.second as f64);
        self.millisecond = Some(t.millisecond as f64);
        self.microsecond = Some(t.microsecond as f64);
        self.nanosecond = Some(t.nanosecond as f64);
    }
}

pub const ALL_FLAGS: [u32; 14] = [
    F_DAY,
    F_ERA,
    F_ERA_YEAR,
    F_HOUR,
    F_MICROSECOND,
    F_MILLISECOND,
    F_MINUTE,
    F_MONTH,
    F_MONTH_CODE,
    F_NANOSECOND,
    F_OFFSET,
    F_SECOND,
    F_TIME_ZONE,
    F_YEAR,
];

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Required {
    /// at least one field must be present (with()); the message names the method
    Partial,
    /// listed fields are required; time fields default to 0
    List(u32),
}

/// Syntactic monthCode check: "M" + 2 digits + optional "L".
pub fn month_code_syntax_ok(s: &str) -> bool {
    let b = s.as_bytes();
    (b.len() == 3 || (b.len() == 4 && b[3] == b'L')) && b[0] == b'M' && b[1].is_ascii_digit() && b[2].is_ascii_digit()
}

/// ToPrimitive(value, string) and require a String
fn to_primitive_string(vm: &mut Vm, v: &Value, what: &str) -> JsResult<String> {
    let p = vm.to_primitive(v, crate::ops::Hint::String)?;
    match p {
        Value::Str(s) => Ok(s.to_rust_string()),
        _ => vm.throw_type(format!("{} must be a string", what)),
    }
}

/// PrepareCalendarFields
pub fn prepare_fields(vm: &mut Vm, cal: Cal, obj: &Obj, names: u32, required: Required) -> JsResult<Fields> {
    let mut names = names;
    if cal.has_eras() && names & F_YEAR != 0 {
        names |= F_ERA | F_ERA_YEAR;
    }
    let mut f = Fields::default();
    let mut any = false;
    for (flag, key) in ORDER {
        if names & flag == 0 {
            continue;
        }
        let v = vm.get_str(obj, key)?;
        if v.is_undefined() {
            if let Required::List(req) = required {
                if req & flag != 0 {
                    if flag == F_TIME_ZONE {
                        return vm.throw_type("missing timeZone");
                    }
                    return vm.throw_type(format!("missing field '{}'", key));
                }
                if F_TIME & flag != 0 {
                    let mut z = Fields::default();
                    z.set_time(&Time::MIDNIGHT);
                    f.copy_from(&z, flag);
                }
            }
            continue;
        }
        any = true;
        match flag {
            F_MONTH | F_DAY => {
                let n = to_integer_with_truncation(vm, &v)?;
                if n <= 0.0 {
                    return vm.throw_range(format!("{} must be positive", key));
                }
                if flag == F_MONTH {
                    f.month = Some(n);
                } else {
                    f.day = Some(n);
                }
            }
            F_MONTH_CODE => {
                let s = to_primitive_string(vm, &v, "monthCode")?;
                if !month_code_syntax_ok(&s) {
                    return vm.throw_range(format!("invalid monthCode: {}", s));
                }
                f.month_code = Some(s);
            }
            F_OFFSET => {
                let s = to_primitive_string(vm, &v, "offset")?;
                if parse::parse_offset_string(&s, true).is_none() {
                    return vm.throw_range(format!("invalid UTC offset: {}", s));
                }
                f.offset = Some(s);
            }
            F_ERA => {
                let s = vm.to_string(&v)?.to_rust_string();
                f.era = Some(s);
            }
            F_TIME_ZONE => {
                let tz = to_time_zone_identifier(vm, &v)?;
                f.time_zone = Some(tz);
            }
            _ => {
                let n = to_integer_with_truncation(vm, &v)?;
                match flag {
                    F_ERA_YEAR => f.era_year = Some(n),
                    F_YEAR => f.year = Some(n),
                    F_HOUR => f.hour = Some(n),
                    F_MINUTE => f.minute = Some(n),
                    F_SECOND => f.second = Some(n),
                    F_MILLISECOND => f.millisecond = Some(n),
                    F_MICROSECOND => f.microsecond = Some(n),
                    F_NANOSECOND => f.nanosecond = Some(n),
                    _ => {}
                }
            }
        }
    }
    if required == Required::Partial && !any {
        return vm.throw_type("with() requires at least one field");
    }
    Ok(f)
}

/// IsPartialTemporalObject (throws the original's with() messages)
pub fn check_partial(vm: &mut Vm, v: &Value) -> JsResult<Obj> {
    let o = match v {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("with() argument must be a plain object"),
    };
    if slot_of(v).is_some() {
        return vm.throw_type("with() argument must be a plain object");
    }
    let c = vm.get_str(&o, "calendar")?;
    if !c.is_undefined() {
        return vm.throw_type("with() argument must not have 'calendar'");
    }
    let t = vm.get_str(&o, "timeZone")?;
    if !t.is_undefined() {
        return vm.throw_type("with() argument must not have 'timeZone'");
    }
    Ok(o)
}

/// Partial time record (ToTemporalTimeRecord with completeness = partial)
#[derive(Clone, Copy, Default, Debug)]
pub struct TimeLike {
    pub hour: Option<f64>,
    pub minute: Option<f64>,
    pub second: Option<f64>,
    pub millisecond: Option<f64>,
    pub microsecond: Option<f64>,
    pub nanosecond: Option<f64>,
}

/// ToTemporalTimeRecord: reads hour, microsecond, millisecond, minute,
/// nanosecond, second (alphabetical).  Returns None when no field is present.
pub fn to_time_record(vm: &mut Vm, o: &Obj) -> JsResult<Option<TimeLike>> {
    let mut r = TimeLike::default();
    let mut any = false;
    for key in ["hour", "microsecond", "millisecond", "minute", "nanosecond", "second"] {
        let v = vm.get_str(o, key)?;
        if v.is_undefined() {
            continue;
        }
        any = true;
        let n = to_integer_with_truncation(vm, &v)?;
        match key {
            "hour" => r.hour = Some(n),
            "microsecond" => r.microsecond = Some(n),
            "millisecond" => r.millisecond = Some(n),
            "minute" => r.minute = Some(n),
            "nanosecond" => r.nanosecond = Some(n),
            _ => r.second = Some(n),
        }
    }
    Ok(if any { Some(r) } else { None })
}

/// RegulateTime
pub fn regulate_time(h: f64, mi: f64, s: f64, ms: f64, us: f64, ns: f64, overflow: Overflow) -> TRes<Time> {
    match overflow {
        Overflow::Constrain => Ok(Time {
            hour: h.clamp(0.0, 23.0) as u8,
            minute: mi.clamp(0.0, 59.0) as u8,
            second: s.clamp(0.0, 59.0) as u8,
            millisecond: ms.clamp(0.0, 999.0) as u16,
            microsecond: us.clamp(0.0, 999.0) as u16,
            nanosecond: ns.clamp(0.0, 999.0) as u16,
        }),
        Overflow::Reject => {
            let checks = [
                (h, 23.0, "hour"),
                (mi, 59.0, "minute"),
                (s, 59.0, "second"),
                (ms, 999.0, "millisecond"),
                (us, 999.0, "microsecond"),
                (ns, 999.0, "nanosecond"),
            ];
            for (v, max, name) in checks {
                if v < 0.0 || v > max {
                    return rerr(format!("{} out of range", name));
                }
            }
            Ok(Time {
                hour: h as u8,
                minute: mi as u8,
                second: s as u8,
                millisecond: ms as u16,
                microsecond: us as u16,
                nanosecond: ns as u16,
            })
        }
    }
}

/// ToTemporalPartialDurationRecord (None = no recognized field)
pub fn to_partial_duration(vm: &mut Vm, o: &Obj) -> JsResult<Option<[Option<f64>; 10]>> {
    // alphabetical read order, stored in field order
    const KEYS: [(&str, usize); 10] = [
        ("days", 3),
        ("hours", 4),
        ("microseconds", 8),
        ("milliseconds", 7),
        ("minutes", 5),
        ("months", 1),
        ("nanoseconds", 9),
        ("seconds", 6),
        ("weeks", 2),
        ("years", 0),
    ];
    let mut r: [Option<f64>; 10] = [None; 10];
    let mut any = false;
    for (key, idx) in KEYS {
        let v = vm.get_str(o, key)?;
        if v.is_undefined() {
            continue;
        }
        any = true;
        r[idx] = Some(to_integer_if_integral(vm, &v)?);
    }
    Ok(if any { Some(r) } else { None })
}

/// ToTemporalDuration
pub fn to_duration(vm: &mut Vm, v: &Value) -> JsResult<Dur> {
    if let Some(Slot::Duration(d)) = slot_of(v) {
        return Ok(d);
    }
    match v {
        Value::Obj(o) => {
            let p = match to_partial_duration(vm, o)? {
                Some(p) => p,
                None => return vm.throw_type("invalid Temporal.Duration-like: no recognized fields"),
            };
            let mut f = [0.0f64; 10];
            for i in 0..10 {
                if let Some(x) = p[i] {
                    f[i] = x;
                }
            }
            let d = Dur::from_fields(f);
            tr!(vm, d.validate());
            Ok(d)
        }
        Value::Str(s) => {
            let s = s.to_rust_string();
            Ok(tr!(vm, Dur::parse(&s)))
        }
        _ => vm.throw_type("cannot convert to Temporal.Duration"),
    }
}

/// ToTemporalTimeZoneIdentifier
pub fn to_time_zone_identifier(vm: &mut Vm, v: &Value) -> JsResult<Tz> {
    if let Some(Slot::Zoned(_, tz, _)) = slot_of(v) {
        return Ok(tz);
    }
    match v {
        Value::Str(s) => {
            let s = s.to_rust_string();
            match Tz::from_time_zone_string(&s) {
                Some(tz) => Ok(tz),
                None => vm.throw_range("invalid time zone identifier"),
            }
        }
        _ => vm.throw_type("timeZone must be a string or ZonedDateTime"),
    }
}

/// ToTemporalCalendarIdentifier
pub fn to_calendar_identifier(vm: &mut Vm, v: &Value) -> JsResult<Cal> {
    match slot_of(v) {
        Some(Slot::Date(_, c))
        | Some(Slot::DateTime(_, c))
        | Some(Slot::YearMonth(_, c))
        | Some(Slot::MonthDay(_, c))
        | Some(Slot::Zoned(_, _, c)) => return Ok(c),
        _ => {}
    }
    match v {
        Value::Str(s) => {
            let s = s.to_rust_string();
            match Cal::from_calendar_string(&s) {
                Some(c) => Ok(c),
                None => vm.throw_range("invalid calendar identifier"),
            }
        }
        _ => vm.throw_type("calendar is not a string"),
    }
}

/// Argument of withCalendar()
pub fn with_calendar_arg(vm: &mut Vm, v: &Value) -> JsResult<Cal> {
    match slot_of(v) {
        Some(Slot::Date(_, c))
        | Some(Slot::DateTime(_, c))
        | Some(Slot::YearMonth(_, c))
        | Some(Slot::MonthDay(_, c))
        | Some(Slot::Zoned(_, _, c)) => return Ok(c),
        _ => {}
    }
    match v {
        Value::Undefined => vm.throw_type("calendar argument is required"),
        Value::Str(_) => to_calendar_identifier(vm, v),
        _ => vm.throw_type("calendar must be a string"),
    }
}

/// GetTemporalCalendarIdentifierWithISODefault
pub fn get_calendar_with_iso_default(vm: &mut Vm, o: &Obj) -> JsResult<Cal> {
    // the original reads the `calendar` property even for Temporal objects
    // (which have `calendarId`), so they default to iso8601
    let c = vm.get_str(o, "calendar")?;
    if c.is_undefined() {
        return Ok(Cal::Iso8601);
    }
    to_calendar_identifier(vm, &c)
}
