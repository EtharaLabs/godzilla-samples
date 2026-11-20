//! The `Temporal` global (Temporal proposal, 2025 shape: no Calendar /
//! TimeZone objects; string identifiers only).
//!
//! Layout:
//! * `iso`      – pure ISO calendar / clock arithmetic
//! * `parse`    – ISO 8601 / RFC 9557 string grammar
//! * `calendar` – calendar systems (iso8601 + the Intl calendars)
//! * `tz`       – time zones (UTC, offsets, IANA via `crate::datetime`)
//! * `dur`      – duration records, rounding and difference algorithms
//! * `fields`   – property-bag reading (PrepareCalendarFields & co.)
//! * one file per Temporal type + `now`.

macro_rules! tr {
    ($vm:expr, $e:expr) => {
        match $e {
            Ok(v) => v,
            Err(e) => return $crate::builtins::temporal::throw($vm, e),
        }
    };
}

pub mod calendar;
pub mod cals;
pub mod cn_tables;
pub mod dur;
pub mod fields;
pub mod iso;
pub mod parse;
pub mod tz;

mod duration;
mod instant;
mod dur_locale_data;
mod locale;
mod month_day;
mod now;
mod plain_date;
mod plain_date_time;
mod plain_time;
mod year_month;
mod zoned;

use std::cell::RefCell;

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

use calendar::Cal;
use dur::Dur;
use iso::*;
use tz::Tz;

// ---------------------------------------------------------------------------
// Internal slots
// ---------------------------------------------------------------------------

#[derive(Clone)]
pub enum Slot {
    Date(IsoDate, Cal),
    Time(Time),
    DateTime(IsoDateTime, Cal),
    YearMonth(IsoDate, Cal),
    MonthDay(IsoDate, Cal),
    Instant(i128),
    Zoned(i128, Tz, Cal),
    Duration(Dur),
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum K {
    PlainDate = 0,
    PlainTime,
    PlainDateTime,
    PlainYearMonth,
    PlainMonthDay,
    Duration,
    Instant,
    ZonedDateTime,
}

impl K {
    pub fn name(self) -> &'static str {
        match self {
            K::PlainDate => "Temporal.PlainDate",
            K::PlainTime => "Temporal.PlainTime",
            K::PlainDateTime => "Temporal.PlainDateTime",
            K::PlainYearMonth => "Temporal.PlainYearMonth",
            K::PlainMonthDay => "Temporal.PlainMonthDay",
            K::Duration => "Temporal.Duration",
            K::Instant => "Temporal.Instant",
            K::ZonedDateTime => "Temporal.ZonedDateTime",
        }
    }
}

thread_local! {
    static PROTOS: RefCell<Vec<Option<Obj>>> = RefCell::new(vec![None; 8]);
}

pub fn proto(k: K) -> Obj {
    PROTOS.with(|p| p.borrow()[k as usize].clone().expect("Temporal prototype"))
}

fn set_proto(k: K, o: &Obj) {
    PROTOS.with(|p| p.borrow_mut()[k as usize] = Some(o.clone()));
}

pub fn slot_of(v: &Value) -> Option<Slot> {
    if let Value::Obj(o) = v {
        if let ObjKind::Host(h) = &o.borrow().kind {
            if let Some(s) = h.downcast_ref::<Slot>() {
                return Some(s.clone());
            }
        }
    }
    None
}

pub fn new_temporal(vm: &mut Vm, k: K, s: Slot, nt: Option<&Obj>) -> JsResult<Value> {
    let fallback = proto(k);
    let p = match nt {
        Some(nt) => vm.proto_from_nt(&Some(nt.clone()), &fallback)?,
        None => fallback,
    };
    Ok(Value::Obj(Obj::new(Some(p), ObjKind::Host(Box::new(s)))))
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub enum TErr {
    Range(String),
    Type(String),
}

pub type TRes<T> = Result<T, TErr>;

pub fn rerr<T>(m: impl Into<String>) -> TRes<T> {
    Err(TErr::Range(m.into()))
}

pub fn terr<T>(m: impl Into<String>) -> TRes<T> {
    Err(TErr::Type(m.into()))
}

pub fn throw<T>(vm: &mut Vm, e: TErr) -> JsResult<T> {
    match e {
        TErr::Range(m) => vm.throw_range(m),
        TErr::Type(m) => vm.throw_type(m),
    }
}

// ---------------------------------------------------------------------------
// Object creation (with the original's range messages)
// ---------------------------------------------------------------------------

pub const MSG_DATE_RANGE: &str = "date is outside the supported range";
pub const MSG_DATETIME_RANGE: &str = "date-time is outside the representable range";
pub const MSG_YM_RANGE: &str = "year-month is outside the supported range";
pub const MSG_INSTANT_RANGE: &str = "instant is outside the representable range";

pub fn create_date(vm: &mut Vm, d: IsoDate, cal: Cal, nt: Option<&Obj>) -> JsResult<Value> {
    if !date_within_limits(&d) {
        return vm.throw_range(MSG_DATE_RANGE);
    }
    new_temporal(vm, K::PlainDate, Slot::Date(d, cal), nt)
}

pub fn create_time(vm: &mut Vm, t: Time, nt: Option<&Obj>) -> JsResult<Value> {
    new_temporal(vm, K::PlainTime, Slot::Time(t), nt)
}

pub fn create_datetime(vm: &mut Vm, dt: IsoDateTime, cal: Cal, nt: Option<&Obj>) -> JsResult<Value> {
    if !date_within_limits(&dt.date) {
        return vm.throw_range(MSG_DATE_RANGE);
    }
    if !datetime_within_limits(&dt.date, &dt.time) {
        return vm.throw_range(MSG_DATETIME_RANGE);
    }
    new_temporal(vm, K::PlainDateTime, Slot::DateTime(dt, cal), nt)
}

pub fn create_year_month(vm: &mut Vm, d: IsoDate, cal: Cal, nt: Option<&Obj>) -> JsResult<Value> {
    if !year_month_within_limits(&d) {
        return vm.throw_range(MSG_YM_RANGE);
    }
    new_temporal(vm, K::PlainYearMonth, Slot::YearMonth(d, cal), nt)
}

pub fn create_month_day(vm: &mut Vm, d: IsoDate, cal: Cal, nt: Option<&Obj>) -> JsResult<Value> {
    if !date_within_limits(&d) {
        return vm.throw_range(MSG_DATE_RANGE);
    }
    new_temporal(vm, K::PlainMonthDay, Slot::MonthDay(d, cal), nt)
}

pub fn create_instant(vm: &mut Vm, ns: i128, nt: Option<&Obj>) -> JsResult<Value> {
    if !epoch_ns_valid(ns) {
        return vm.throw_range(MSG_INSTANT_RANGE);
    }
    new_temporal(vm, K::Instant, Slot::Instant(ns), nt)
}

pub fn create_zoned(vm: &mut Vm, ns: i128, tz: Tz, cal: Cal, nt: Option<&Obj>) -> JsResult<Value> {
    if !epoch_ns_valid(ns) {
        return vm.throw_range(MSG_INSTANT_RANGE);
    }
    new_temporal(vm, K::ZonedDateTime, Slot::Zoned(ns, tz, cal), nt)
}

pub fn create_duration(vm: &mut Vm, d: Dur, nt: Option<&Obj>) -> JsResult<Value> {
    tr!(vm, d.validate());
    new_temporal(vm, K::Duration, Slot::Duration(d), nt)
}

// ---------------------------------------------------------------------------
// Receivers
// ---------------------------------------------------------------------------

pub fn recv_err<T>(vm: &mut Vm, k: K) -> JsResult<T> {
    vm.throw_type(format!("receiver is not a {}", k.name()))
}

pub fn this_date(vm: &mut Vm, a: &Args) -> JsResult<(IsoDate, Cal)> {
    match slot_of(&a.this) {
        Some(Slot::Date(d, c)) => Ok((d, c)),
        _ => recv_err(vm, K::PlainDate),
    }
}

pub fn this_time(vm: &mut Vm, a: &Args) -> JsResult<Time> {
    match slot_of(&a.this) {
        Some(Slot::Time(t)) => Ok(t),
        _ => recv_err(vm, K::PlainTime),
    }
}

pub fn this_datetime(vm: &mut Vm, a: &Args) -> JsResult<(IsoDateTime, Cal)> {
    match slot_of(&a.this) {
        Some(Slot::DateTime(d, c)) => Ok((d, c)),
        _ => recv_err(vm, K::PlainDateTime),
    }
}

pub fn this_year_month(vm: &mut Vm, a: &Args) -> JsResult<(IsoDate, Cal)> {
    match slot_of(&a.this) {
        Some(Slot::YearMonth(d, c)) => Ok((d, c)),
        _ => recv_err(vm, K::PlainYearMonth),
    }
}

pub fn this_month_day(vm: &mut Vm, a: &Args) -> JsResult<(IsoDate, Cal)> {
    match slot_of(&a.this) {
        Some(Slot::MonthDay(d, c)) => Ok((d, c)),
        _ => recv_err(vm, K::PlainMonthDay),
    }
}

pub fn this_instant(vm: &mut Vm, a: &Args) -> JsResult<i128> {
    match slot_of(&a.this) {
        Some(Slot::Instant(ns)) => Ok(ns),
        _ => recv_err(vm, K::Instant),
    }
}

pub fn this_zoned(vm: &mut Vm, a: &Args) -> JsResult<(i128, Tz, Cal)> {
    match slot_of(&a.this) {
        Some(Slot::Zoned(ns, tz, c)) => Ok((ns, tz, c)),
        _ => recv_err(vm, K::ZonedDateTime),
    }
}

pub fn this_duration(vm: &mut Vm, a: &Args) -> JsResult<Dur> {
    match slot_of(&a.this) {
        Some(Slot::Duration(d)) => Ok(d),
        _ => recv_err(vm, K::Duration),
    }
}

// ---------------------------------------------------------------------------
// Number conversions
// ---------------------------------------------------------------------------

/// ToIntegerWithTruncation
pub fn to_integer_with_truncation(vm: &mut Vm, v: &Value) -> JsResult<f64> {
    let n = vm.to_number(v)?;
    if !n.is_finite() {
        return vm.throw_range("value must be finite");
    }
    Ok(n.trunc() + 0.0)
}

/// ToIntegerIfIntegral
pub fn to_integer_if_integral(vm: &mut Vm, v: &Value) -> JsResult<f64> {
    let n = vm.to_number(v)?;
    if !n.is_finite() || n.trunc() != n {
        return vm.throw_range("value must be an integer");
    }
    Ok(n + 0.0)
}

// ---------------------------------------------------------------------------
// Options
// ---------------------------------------------------------------------------

pub type Opts = Option<Obj>;

/// GetOptionsObject
pub fn get_options_object(vm: &mut Vm, v: &Value) -> JsResult<Opts> {
    match v {
        Value::Undefined => Ok(None),
        Value::Obj(o) => Ok(Some(o.clone())),
        _ => vm.throw_type("options must be an object or undefined"),
    }
}

/// GetOptionsObject as used by from() of the plain types and the
/// PlainDate / PlainYearMonth toString (shorter message)
pub fn get_options_object_strict(vm: &mut Vm, v: &Value) -> JsResult<Opts> {
    match v {
        Value::Undefined => Ok(None),
        Value::Obj(o) => Ok(Some(o.clone())),
        _ => vm.throw_type("options must be an object"),
    }
}

pub fn opt_get(vm: &mut Vm, o: &Opts, name: &str) -> JsResult<Value> {
    match o {
        Some(o) => vm.get_str(o, name),
        None => Ok(Value::Undefined),
    }
}

pub fn opt_string(vm: &mut Vm, o: &Opts, name: &str) -> JsResult<Option<String>> {
    let v = opt_get(vm, o, name)?;
    if v.is_undefined() {
        return Ok(None);
    }
    Ok(Some(vm.to_string(&v)?.to_rust_string()))
}

/// Options object created from a string shorthand: { [key]: string }.
pub fn string_shorthand(vm: &mut Vm, key: &str, s: Value) -> Opts {
    let o = Obj::new(None, ObjKind::Ordinary);
    o.set_prop(PropKey::from_str(key), s, WEC);
    let _ = vm;
    Some(o)
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Overflow {
    Constrain,
    Reject,
}

pub fn get_overflow(vm: &mut Vm, o: &Opts) -> JsResult<Overflow> {
    match opt_string(vm, o, "overflow")? {
        None => Ok(Overflow::Constrain),
        Some(s) => match s.as_str() {
            "constrain" => Ok(Overflow::Constrain),
            "reject" => Ok(Overflow::Reject),
            _ => vm.throw_range(format!("invalid overflow ({})", s)),
        },
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Disambiguation {
    Compatible,
    Earlier,
    Later,
    Reject,
}

pub fn get_disambiguation(vm: &mut Vm, o: &Opts) -> JsResult<Disambiguation> {
    match opt_string(vm, o, "disambiguation")? {
        None => Ok(Disambiguation::Compatible),
        Some(s) => match s.as_str() {
            "compatible" => Ok(Disambiguation::Compatible),
            "earlier" => Ok(Disambiguation::Earlier),
            "later" => Ok(Disambiguation::Later),
            "reject" => Ok(Disambiguation::Reject),
            _ => vm.throw_range(format!("invalid disambiguation: {}", s)),
        },
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum OffsetOption {
    Prefer,
    Use,
    Ignore,
    Reject,
}

pub fn get_offset_option(vm: &mut Vm, o: &Opts, fallback: OffsetOption) -> JsResult<OffsetOption> {
    match opt_string(vm, o, "offset")? {
        None => Ok(fallback),
        Some(s) => match s.as_str() {
            "prefer" => Ok(OffsetOption::Prefer),
            "use" => Ok(OffsetOption::Use),
            "ignore" => Ok(OffsetOption::Ignore),
            "reject" => Ok(OffsetOption::Reject),
            _ => vm.throw_range(format!("invalid offset: {}", s)),
        },
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ShowCalendar {
    Auto,
    Always,
    Never,
    Critical,
}

pub fn get_show_calendar(vm: &mut Vm, o: &Opts) -> JsResult<ShowCalendar> {
    match opt_string(vm, o, "calendarName")? {
        None => Ok(ShowCalendar::Auto),
        Some(s) => match s.as_str() {
            "auto" => Ok(ShowCalendar::Auto),
            "always" => Ok(ShowCalendar::Always),
            "never" => Ok(ShowCalendar::Never),
            "critical" => Ok(ShowCalendar::Critical),
            _ => vm.throw_range(format!("invalid calendarName: {}", s)),
        },
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ShowTimeZone {
    Auto,
    Never,
    Critical,
}

pub fn get_show_time_zone(vm: &mut Vm, o: &Opts) -> JsResult<ShowTimeZone> {
    match opt_string(vm, o, "timeZoneName")? {
        None => Ok(ShowTimeZone::Auto),
        Some(s) => match s.as_str() {
            "auto" => Ok(ShowTimeZone::Auto),
            "never" => Ok(ShowTimeZone::Never),
            "critical" => Ok(ShowTimeZone::Critical),
            _ => vm.throw_range(format!("invalid timeZoneName: {}", s)),
        },
    }
}

/// GetTemporalShowOffsetOption: true = auto, false = never
pub fn get_show_offset(vm: &mut Vm, o: &Opts) -> JsResult<bool> {
    match opt_string(vm, o, "offset")? {
        None => Ok(true),
        Some(s) => match s.as_str() {
            "auto" => Ok(true),
            "never" => Ok(false),
            _ => vm.throw_range(format!("invalid offset: {}", s)),
        },
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum RoundingMode {
    Ceil,
    Floor,
    Expand,
    Trunc,
    HalfCeil,
    HalfFloor,
    HalfExpand,
    HalfTrunc,
    HalfEven,
}

impl RoundingMode {
    pub fn negate(self) -> RoundingMode {
        match self {
            RoundingMode::Ceil => RoundingMode::Floor,
            RoundingMode::Floor => RoundingMode::Ceil,
            RoundingMode::HalfCeil => RoundingMode::HalfFloor,
            RoundingMode::HalfFloor => RoundingMode::HalfCeil,
            m => m,
        }
    }
}

pub fn get_rounding_mode(vm: &mut Vm, o: &Opts, fallback: RoundingMode) -> JsResult<RoundingMode> {
    match opt_string(vm, o, "roundingMode")? {
        None => Ok(fallback),
        Some(s) => match s.as_str() {
            "ceil" => Ok(RoundingMode::Ceil),
            "floor" => Ok(RoundingMode::Floor),
            "expand" => Ok(RoundingMode::Expand),
            "trunc" => Ok(RoundingMode::Trunc),
            "halfCeil" => Ok(RoundingMode::HalfCeil),
            "halfFloor" => Ok(RoundingMode::HalfFloor),
            "halfExpand" => Ok(RoundingMode::HalfExpand),
            "halfTrunc" => Ok(RoundingMode::HalfTrunc),
            "halfEven" => Ok(RoundingMode::HalfEven),
            _ => vm.throw_range("invalid roundingMode"),
        },
    }
}

pub const MSG_INCREMENT: &str = "roundingIncrement out of range";

/// GetRoundingIncrementOption
pub fn get_rounding_increment(vm: &mut Vm, o: &Opts) -> JsResult<i128> {
    let v = opt_get(vm, o, "roundingIncrement")?;
    if v.is_undefined() {
        return Ok(1);
    }
    let n = vm.to_number(&v)?;
    if !n.is_finite() {
        return vm.throw_range(MSG_INCREMENT);
    }
    let n = n.trunc();
    if !(1.0..=1e9).contains(&n) {
        return vm.throw_range(MSG_INCREMENT);
    }
    Ok(n as i128)
}

/// ValidateTemporalRoundingIncrement
pub fn validate_increment(increment: i128, dividend: i128, inclusive: bool) -> TRes<()> {
    let max = if inclusive { dividend } else { dividend - 1 };
    if increment > max || dividend % increment != 0 {
        return rerr(MSG_INCREMENT);
    }
    Ok(())
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Digits {
    Auto,
    N(u8),
}

/// GetTemporalFractionalSecondDigitsOption
pub fn get_fractional_digits(vm: &mut Vm, o: &Opts) -> JsResult<Digits> {
    let v = opt_get(vm, o, "fractionalSecondDigits")?;
    if v.is_undefined() {
        return Ok(Digits::Auto);
    }
    let n = match v {
        Value::Num(n) => n,
        _ => {
            let s = vm.to_string(&v)?;
            if s.eq_str("auto") {
                return Ok(Digits::Auto);
            }
            return vm.throw_range("fractionalSecondDigits must be 'auto' or a number");
        }
    };
    if !n.is_finite() {
        return vm.throw_range("fractionalSecondDigits out of range");
    }
    let n = n.floor();
    if !(0.0..=9.0).contains(&n) {
        return vm.throw_range("fractionalSecondDigits out of range");
    }
    Ok(Digits::N(n as u8))
}

// ---------------------------------------------------------------------------
// Units
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
pub enum Unit {
    Year,
    Month,
    Week,
    Day,
    Hour,
    Minute,
    Second,
    Millisecond,
    Microsecond,
    Nanosecond,
}

impl Unit {
    pub const ALL: [Unit; 10] = [
        Unit::Year,
        Unit::Month,
        Unit::Week,
        Unit::Day,
        Unit::Hour,
        Unit::Minute,
        Unit::Second,
        Unit::Millisecond,
        Unit::Microsecond,
        Unit::Nanosecond,
    ];

    /// Length in nanoseconds (days are 24 hours).
    pub fn ns(self) -> i128 {
        match self {
            Unit::Day => NS_PER_DAY,
            Unit::Hour => NS_PER_HOUR,
            Unit::Minute => NS_PER_MINUTE,
            Unit::Second => NS_PER_SECOND,
            Unit::Millisecond => 1_000_000,
            Unit::Microsecond => 1000,
            Unit::Nanosecond => 1,
            _ => 0,
        }
    }

    pub fn is_calendar(self) -> bool {
        matches!(self, Unit::Year | Unit::Month | Unit::Week)
    }

    pub fn is_date(self) -> bool {
        self <= Unit::Day
    }

    pub fn larger(a: Unit, b: Unit) -> Unit {
        if a <= b {
            a
        } else {
            b
        }
    }

    pub fn from_str(s: &str) -> Option<Unit> {
        Some(match s {
            "year" | "years" => Unit::Year,
            "month" | "months" => Unit::Month,
            "week" | "weeks" => Unit::Week,
            "day" | "days" => Unit::Day,
            "hour" | "hours" => Unit::Hour,
            "minute" | "minutes" => Unit::Minute,
            "second" | "seconds" => Unit::Second,
            "millisecond" | "milliseconds" => Unit::Millisecond,
            "microsecond" | "microseconds" => Unit::Microsecond,
            "nanosecond" | "nanoseconds" => Unit::Nanosecond,
            _ => return None,
        })
    }

    /// MaximumTemporalDurationRoundingIncrement
    pub fn max_increment(self) -> Option<i128> {
        match self {
            Unit::Year | Unit::Month | Unit::Week | Unit::Day => None,
            Unit::Hour => Some(24),
            Unit::Minute | Unit::Second => Some(60),
            _ => Some(1000),
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum UnitOpt {
    Auto,
    U(Unit),
}

/// GetTemporalUnitValuedOption (None = unset)
/// Unit-valued option as a string; the original treats "" like undefined.
pub fn opt_unit_string(vm: &mut Vm, o: &Opts, key: &str) -> JsResult<Option<String>> {
    Ok(opt_string(vm, o, key)?.filter(|s| !s.is_empty()))
}

pub fn get_unit_option(vm: &mut Vm, o: &Opts, key: &str) -> JsResult<Option<UnitOpt>> {
    match opt_unit_string(vm, o, key)? {
        None => Ok(None),
        Some(s) => {
            if s == "auto" {
                return Ok(Some(UnitOpt::Auto));
            }
            match Unit::from_str(&s) {
                Some(u) => Ok(Some(UnitOpt::U(u))),
                None => vm.throw_range(format!("invalid {}", key)),
            }
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum UnitGroup {
    Date,
    Time,
    DateTime,
}

/// ValidateTemporalUnitValue
pub fn validate_unit(key: &str, v: Option<UnitOpt>, group: UnitGroup, extra: &[Unit], allow_auto: bool) -> TRes<()> {
    let u = match v {
        None => return Ok(()),
        Some(UnitOpt::Auto) => {
            if allow_auto {
                return Ok(());
            }
            return rerr(format!("invalid {}", key));
        }
        Some(UnitOpt::U(u)) => u,
    };
    if extra.contains(&u) {
        return Ok(());
    }
    match group {
        UnitGroup::DateTime => Ok(()),
        UnitGroup::Date => {
            if u.is_date() {
                Ok(())
            } else {
                rerr(format!("{} must be a date unit", key))
            }
        }
        UnitGroup::Time => {
            if !u.is_date() {
                Ok(())
            } else {
                rerr(format!("{} must be a time unit", key))
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Rounding
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Unsigned {
    Zero,
    Infinity,
    HalfZero,
    HalfInfinity,
    HalfEven,
}

pub fn unsigned_mode(mode: RoundingMode, negative: bool) -> Unsigned {
    use RoundingMode::*;
    match (mode, negative) {
        (Ceil, false) => Unsigned::Infinity,
        (Ceil, true) => Unsigned::Zero,
        (Floor, false) => Unsigned::Zero,
        (Floor, true) => Unsigned::Infinity,
        (Expand, _) => Unsigned::Infinity,
        (Trunc, _) => Unsigned::Zero,
        (HalfCeil, false) => Unsigned::HalfInfinity,
        (HalfCeil, true) => Unsigned::HalfZero,
        (HalfFloor, false) => Unsigned::HalfZero,
        (HalfFloor, true) => Unsigned::HalfInfinity,
        (HalfExpand, _) => Unsigned::HalfInfinity,
        (HalfTrunc, _) => Unsigned::HalfZero,
        (HalfEven, _) => Unsigned::HalfEven,
    }
}

/// ApplyUnsignedRoundingMode for x = r1 + num/den (0 <= num < den, r2 = r1 + 1 step)
/// returning true when r2 is chosen.  `r1_even` is used for half-even.
pub fn choose_upper(num: i128, den: i128, mode: Unsigned, r1_even: bool) -> bool {
    if num == 0 {
        return false;
    }
    match mode {
        Unsigned::Zero => false,
        Unsigned::Infinity => true,
        _ => {
            let twice = num * 2;
            if twice < den {
                false
            } else if twice > den {
                true
            } else {
                match mode {
                    Unsigned::HalfZero => false,
                    Unsigned::HalfInfinity => true,
                    _ => !r1_even,
                }
            }
        }
    }
}

/// RoundNumberToIncrement on an exact integer.
pub fn round_to_increment(x: i128, increment: i128, mode: RoundingMode) -> i128 {
    let negative = x < 0;
    let ax = x.abs();
    let r1 = ax / increment;
    let rem = ax % increment;
    let um = unsigned_mode(mode, negative);
    let q = if choose_upper(rem, increment, um, r1 % 2 == 0) { r1 + 1 } else { r1 };
    let r = q * increment;
    if negative {
        -r
    } else {
        r
    }
}

/// RoundNumberToIncrementAsIfPositive
pub fn round_as_if_positive(x: i128, increment: i128, mode: RoundingMode) -> i128 {
    let r1 = x.div_euclid(increment);
    let rem = x.rem_euclid(increment);
    let um = unsigned_mode(mode, false);
    let q = if choose_upper(rem, increment, um, r1.rem_euclid(2) == 0) { r1 + 1 } else { r1 };
    q * increment
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Precision {
    Minute,
    Auto,
    Digits(u8),
}

pub fn pad_year(y: i64) -> String {
    if (0..=9999).contains(&y) {
        format!("{:04}", y)
    } else {
        format!("{}{:06}", if y < 0 { '-' } else { '+' }, y.abs())
    }
}

pub fn fmt_date(d: &IsoDate) -> String {
    format!("{}-{:02}-{:02}", pad_year(d.year), d.month, d.day)
}

pub fn fmt_fraction(sub_ns: u32, p: Precision) -> String {
    match p {
        Precision::Minute => String::new(),
        Precision::Auto => {
            if sub_ns == 0 {
                return String::new();
            }
            let s = format!("{:09}", sub_ns);
            format!(".{}", s.trim_end_matches('0'))
        }
        Precision::Digits(0) => String::new(),
        Precision::Digits(n) => {
            let s = format!("{:09}", sub_ns);
            format!(".{}", &s[..n as usize])
        }
    }
}

/// FormatTimeString
pub fn fmt_time_parts(h: u64, m: u64, s: u64, sub_ns: u32, p: Precision) -> String {
    if p == Precision::Minute {
        return format!("{:02}:{:02}", h, m);
    }
    format!("{:02}:{:02}:{:02}{}", h, m, s, fmt_fraction(sub_ns, p))
}

pub fn fmt_time(t: &Time, p: Precision) -> String {
    fmt_time_parts(t.hour as u64, t.minute as u64, t.second as u64, t.sub_second_ns(), p)
}

/// FormatOffsetTimeZoneIdentifier
pub fn fmt_offset_minutes(minutes: i64) -> String {
    let sign = if minutes >= 0 { '+' } else { '-' };
    let a = minutes.abs();
    format!("{}{:02}:{:02}", sign, a / 60, a % 60)
}

/// FormatDateTimeUTCOffsetRounded
pub fn fmt_offset_rounded(offset_ns: i128) -> String {
    let r = round_to_increment(offset_ns, NS_PER_MINUTE, RoundingMode::HalfExpand);
    fmt_offset_minutes((r / NS_PER_MINUTE) as i64)
}

/// FormatUTCOffsetNanoseconds
pub fn fmt_offset_ns(offset_ns: i128) -> String {
    let sign = if offset_ns >= 0 { '+' } else { '-' };
    let a = offset_ns.abs();
    let h = (a / NS_PER_HOUR) as u64;
    let m = (a / NS_PER_MINUTE % 60) as u64;
    let s = (a / NS_PER_SECOND % 60) as u64;
    let sub = (a % NS_PER_SECOND) as u32;
    let p = if s == 0 && sub == 0 { Precision::Minute } else { Precision::Auto };
    format!("{}{}", sign, fmt_time_parts(h, m, s, sub, p))
}

pub fn fmt_calendar_annotation(cal: Cal, show: ShowCalendar) -> String {
    match show {
        ShowCalendar::Never => String::new(),
        ShowCalendar::Auto if cal == Cal::Iso8601 => String::new(),
        ShowCalendar::Critical => format!("[!u-ca={}]", cal.id()),
        _ => format!("[u-ca={}]", cal.id()),
    }
}

/// ISODateTimeToString
pub fn fmt_datetime(dt: &IsoDateTime, cal: Cal, p: Precision, show: ShowCalendar) -> String {
    format!("{}T{}{}", fmt_date(&dt.date), fmt_time(&dt.time, p), fmt_calendar_annotation(cal, show))
}

/// ToSecondsStringPrecisionRecord: (precision, unit, increment)
pub fn seconds_precision(smallest: Option<Unit>, digits: Digits) -> (Precision, Unit, i128) {
    match smallest {
        Some(Unit::Minute) => (Precision::Minute, Unit::Minute, 1),
        Some(Unit::Second) => (Precision::Digits(0), Unit::Second, 1),
        Some(Unit::Millisecond) => (Precision::Digits(3), Unit::Millisecond, 1),
        Some(Unit::Microsecond) => (Precision::Digits(6), Unit::Microsecond, 1),
        Some(Unit::Nanosecond) => (Precision::Digits(9), Unit::Nanosecond, 1),
        _ => match digits {
            Digits::Auto => (Precision::Auto, Unit::Nanosecond, 1),
            Digits::N(0) => (Precision::Digits(0), Unit::Second, 1),
            Digits::N(n) if n <= 3 => (Precision::Digits(n), Unit::Millisecond, 10i128.pow(3 - n as u32)),
            Digits::N(n) if n <= 6 => (Precision::Digits(n), Unit::Microsecond, 10i128.pow(6 - n as u32)),
            Digits::N(n) => (Precision::Digits(n), Unit::Nanosecond, 10i128.pow(9 - n as u32)),
        },
    }
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

/// Define a getter named `name` (the original names getters without "get ").
pub fn def_getter(vm: &mut Vm, target: &Obj, name: &str, f: NativeFn) {
    let g = vm.native_fn(name, 0, f);
    target.set_accessor(PropKey::from_str(name), Some(g), None, CONFIGURABLE);
}

pub fn def_method(vm: &mut Vm, target: &Obj, name: &str, len: u32, f: NativeFn) {
    vm.def_method(target, name, len, f);
}

/// Build constructor + prototype; returns (ctor, proto).  The `constructor`
/// property is (re)inserted by the caller at the right position.
pub fn make_class(vm: &mut Vm, k: K, name: &str, len: u32, f: NativeFn) -> (Obj, Obj) {
    let proto = vm.new_object();
    let ctor = vm.native_ctor(name, len, f, &proto);
    // native_ctor inserts `constructor` first; remove it so the caller can
    // add it at the original's position.
    proto.borrow_mut().props.remove(&PropKey::from_str("constructor"));
    set_proto(k, &proto);
    (ctor, proto)
}

pub fn finish_class(vm: &mut Vm, k: K, ctor: &Obj, proto: &Obj) {
    proto.set_prop(PropKey::from_str("constructor"), Value::Obj(ctor.clone()), WC);
    // which prototype's function was called matters for foreign receivers
    let which = match k {
        K::Duration => 1.0,
        K::ZonedDateTime => 2.0,
        _ => 0.0,
    };
    let f = vm.native_closure("toLocaleString", 0, locale::to_locale_string, vec![Value::Num(which)]);
    proto.set_prop(PropKey::from_str("toLocaleString"), Value::Obj(f), WC);
    vm.set_tag(proto, k.name());
}

pub fn setup(vm: &mut Vm) {
    let t = vm.new_object();
    plain_date::setup(vm, &t);
    plain_time::setup(vm, &t);
    plain_date_time::setup(vm, &t);
    year_month::setup(vm, &t);
    month_day::setup(vm, &t);
    duration::setup(vm, &t);
    instant::setup(vm, &t);
    zoned::setup(vm, &t);
    now::setup(vm, &t);
    vm.set_tag(&t, "Temporal");
    vm.def_global("Temporal", Value::Obj(t));
}

/// Date.prototype.toTemporalInstant
pub fn instant_from_ms(vm: &mut Vm, t: f64) -> JsResult<Value> {
    if t.is_nan() {
        return vm.throw_range("invalid Date has no Temporal.Instant");
    }
    create_instant(vm, t as i128 * 1_000_000, None)
}

/// valueOf for every Temporal type (always throws)
pub fn value_of_thrower(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let name = match a.slot(0) {
        Value::Str(s) => s.to_rust_string(),
        _ => String::new(),
    };
    let alt = if a.slot(1).truthy() { "equals" } else { "compare" };
    vm.throw_type(format!("{} has no valueOf; use {}", name, alt))
}

pub fn def_value_of(vm: &mut Vm, proto: &Obj, k: K) {
    let f = vm.native_closure("valueOf", 0, value_of_thrower, vec![Value::str(k.name()), Value::Bool(k == K::PlainMonthDay)]);
    proto.set_prop(PropKey::from_str("valueOf"), Value::Obj(f), WC);
}

/// BigInt value of epoch nanoseconds
pub fn ns_to_bigint(ns: i128) -> Value {
    Value::BigInt(std::rc::Rc::new(crate::bigint::BigInt::from_i128(ns)))
}

pub fn bigint_to_i128(b: &crate::bigint::BigInt) -> Option<i128> {
    if b.bit_length() > 120 {
        return None;
    }
    b.to_string_radix(10).parse::<i128>().ok()
}

pub fn num(v: f64) -> Value {
    Value::Num(v)
}

