//! `Date` support for the lumen runtime: ECMA-262 time-value algorithms,
//! the fixed string formats, `Date.parse` / `new Date(string)` parsing and
//! the locale-sensitive formatting behind `toLocaleString` & co. (an
//! `Intl.DateTimeFormat` subset).  Pure std, no unsafe.
//!
//! Everything below was established by black-box observation of the original
//! `lumen` binary (differential tests over ~11k timestamps/argument tuples,
//! ~65k parse strings and ~80k locale/option/time-zone cases all agree).
//!
//! # Local time zone
//! The original ALWAYS uses UTC as its local time zone: `TZ` is ignored,
//! `getTimezoneOffset()` is 0 and `toString()` ends in
//! `GMT+0000 (Coordinated Universal Time)`.  [`local_tza`] is therefore 0 and
//! [`local_time`] / [`utc`] are identities.
//!
//! # String formats
//! * `toString`: `"Thu Jan 01 1970 00:00:00 GMT+0000 (Coordinated Universal Time)"`
//! * `toDateString`: `"Thu Jan 01 1970"`, `toTimeString`: `"00:00:00 GMT+0000 (Coordinated Universal Time)"`
//! * `toUTCString` (== `toGMTString`): `"Thu, 01 Jan 1970 00:00:00 GMT"`
//! * Years in these three: at least 4 digits, sign for negatives:
//!   `-0001`, `0000`, `0999`, `12345`, `-271821`, `275760`.
//! * `toISOString`: `YYYY-MM-DDTHH:mm:ss.sssZ`, years outside 0..=9999 as
//!   `+275760` / `-000001` (6 digits + sign).  NaN: the caller throws
//!   `RangeError: Invalid time value` (same message for `Intl` formatting of
//!   an invalid time).  `toJSON` of an invalid date gives `null`.
//! * All of them give `"Invalid Date"` for NaN (`String(new Date(NaN))`,
//!   `new Date(8.64e15 + 1)`); the toLocale* family too.
//! * Calling a Date method on a non-Date: `TypeError: this is not a Date object`.
//!
//! # Constructor / setters (caller side)
//! * `new Date(y, m, ...)`, `Date.UTC` and `setYear` map years 0..=99 (after
//!   ToIntegerOrInfinity) to 1900+y; that is the caller's job.  `Date.UTC()`
//!   with no argument is NaN; `Date.UTC(2020)` = month 0.
//! * [`make_day`] returns NaN when `year + floor(month / 12)` is outside
//!   ±300000 (the original's limit; V8 uses ±1e6), otherwise exact f64 math.
//! * Setters on an invalid date: per spec (`setFullYear`, `setUTCFullYear`
//!   and Annex B `setYear` start from +0, the others stay NaN).
//!   [`time_clip`] turns -0 into +0.
//!
//! # Parsing
//! `Date.parse(s)` ([`parse`]) tries, in order:
//! 1. **Strict ISO** ([`parse_iso`]), after Rust `str::trim` (Unicode
//!    White_Space, so U+FEFF is *not* trimmed):
//!    `YYYY | ±YYYYYY` (`-000000` rejected) `[-MM[-DD]]`
//!    `[T HH[:mm[:ss]][.f+][Z | ±HH:mm]]`.  Fields are not range-checked
//!    (`2020-13-01` = 2021-01-01, `2020-02-30` = 2020-03-01, `T24:00:01`,
//!    `T25:00`, offsets `+99:99` all accepted); hour-only `T10` and
//!    fractions after hour/minute (`T10.5`) are fine; 1+ fraction digits,
//!    truncated to ms.  Lowercase `t`/`z`, `+0100`, `+01` are rejected.
//!    Date-only = UTC, date-time without offset = local (= UTC).
//! 2. **Space-separated variant** (only when the string contains a U+0020):
//!    split at the first space; date `[+|-]Y+[-M{1,2}[-D{1,2}]]` (any number
//!    of year digits), time `H{1,2}[:m{1,2}[:s{1,2}]][.f+]` followed by `Z` or
//!    an offset introduced by the LAST `+`/`-`: `±HH`, `±HHMM` or `±HH:MM`.
//!    So `"2020-1-2 3:4"`, `"202 03:04"`, `"2020-01-02 03:04:05+0100"` parse
//!    although the ISO path rejects them.
//! 3. **Legacy tokens** ([`parse_legacy`], see its docs): month names by
//!    their first three letters, numbers assigned to day/year by magnitude,
//!    first `h:m:s` token = time, `GMT±hhmm` / signed tokens = offsets;
//!    AM/PM and zone abbreviations are IGNORED; parentheses are separators,
//!    not comments; no two-digit-year mapping; computed with wrapping i64
//!    arithmetic and **not TimeClip'ed** (`Date.parse("Sep 14 275760")` is
//!    8640000086400000).
//!
//! `new Date(string)` ([`parse_for_constructor`]) only uses 1. and 2.:
//! legacy strings — even the original's own `toString()` output — give an
//! Invalid Date there, while `Date.parse` accepts them.
//!
//! Where the original *panics* (aborting the process: a non-ASCII character
//! inside a 4-byte `±HHMM` offset of the space-separated form, e.g.
//! `"2376 x-5é("`) this module returns NaN.
//!
//! # Locale formatting (`toLocaleString`, `Intl.DateTimeFormat`)
//! The original has a small built-in `Intl` with its own patterns, not CLDR:
//! * Default: `"1/1/1970, 12:00:00 AM"` (toLocaleString), `"1/1/1970"`,
//!   `"12:00:00 AM"`; the default locale is `en`, time zone `UTC`.
//! * Locale data exists for ar de en es fr gv hi it ja ko ln nl pl pt ru si
//!   sl sr sv th zh (zh-TW/HK/MO use Traditional names; ar-MA/DZ/TN/LY/EH/MR
//!   use latn digits); any other language falls back to `en`.  Only the
//!   numeric date order/separator (`3/7/2020`, `7.3.2020`, `7/3/2020`,
//!   `2020/3/7`, `7-3-2020`, `2020-3-7`), month and era names, default hour
//!   cycle (h12 for en, h23 otherwise; hour12 => h11 for ja) and digits
//!   (ar => arab) are localised.  Weekday names, AM/PM, day periods and
//!   time-zone names are always English; textual dates always use the
//!   English layout (`"Saturday, März 7, 2020"` for de).
//! * Pattern: `[weekday ", "] date-body [" " era] [", " time] [" " tzName]`
//!   where the body is `month[" " day][", " year]` for textual months
//!   (`"Mar, 2020"`, `"March 7"`) or the locale's numeric order joined by its
//!   separator; time = `h:mm:ss` of the present fields (minutes and seconds
//!   always 2-digit, hour 2-digit in h23/h24 unless a dayPeriod is shown),
//!   `.fff` fractional seconds (appended directly when no seconds), then
//!   ` AM`/` PM` for h11/h12 or the English day period
//!   (`in the morning`, `noon`/`n`, `in the afternoon`, `in the evening`,
//!   `at night`).  `{weekday:"long"}` alone gives `"Saturday, "`.
//! * Styles: dateStyle full/long/medium/short = weekday+long month / long
//!   month / short month / numeric with 2-digit year; timeStyle full/long add
//!   the long/short zone name.  Mixing styles with explicit components:
//!   `TypeError: dateStyle/timeStyle cannot be combined with explicit date-time components`.
//! * Errors: `RangeError: invalid <option>: <value>`,
//!   `RangeError: fractionalSecondDigits out of range`,
//!   `RangeError: invalid time zone: <name>`,
//!   `RangeError: Incorrect locale information provided: <tag>`,
//!   `TypeError: options must be an object` (non-object, non-undefined
//!   options), `TypeError: locale must be a string or object` (bad list
//!   element), `TypeError: Cannot convert null to object` (locales = null).
//! * Option read order (spec order): localeMatcher, calendar,
//!   numberingSystem, hour12, hourCycle, timeZone, weekday, era, year,
//!   month, day, dayPeriod, hour, minute, second, fractionalSecondDigits,
//!   timeZoneName, formatMatcher, dateStyle, timeStyle.  String options use
//!   ToString, hour12 ToBoolean, fractionalSecondDigits ToNumber.  An invalid
//!   date returns "Invalid Date" before locales/options are even read.
//! * Calendars: gregory/iso8601, buddhist, roc and japanese are implemented;
//!   the other calendars the original supports (islamic*, chinese, dangi,
//!   hebrew, persian, indian, coptic, ethiopic, ethioaa) are reported in
//!   resolvedOptions but formatted as Gregorian (known gap).
//! * Numbering systems: all decimal systems (`-u-nu-` or the option).
//!
//! # Time zones
//! `UTC` (any case), offsets `±HH`, `±HHMM`, `±HH:MM` (resolved as `±HH:MM`)
//! and every IANA name of the system tz database (case-insensitive,
//! canonical case returned, links keep their own name) read at runtime from
//! `/usr/share/zoneinfo` (TZif + `tzdata.zi`).  Quirks reproduced:
//! * no DST after 2037 (the original's data ends there);
//! * `timeZoneName` short/shortOffset/shortGeneric = `GMT±h[:mm]` of the
//!   offset in effect at the EPOCH, not at the formatted date
//!   (`America/New_York` in July is still `GMT-5`); `UTC` => `UTC`;
//! * long names: a few CLDR names (Eastern/Central/Mountain/Pacific
//!   Standard Time, India/Japan/China Standard Time, Central European
//!   Standard Time, Coordinated Universal Time) else a representative zone
//!   id (`Europe/London` => `Europe/Guernsey`) — embedded table;
//! * zones that are links in the original's (non-backzone) data use the
//!   link target's history; the 2026 rule changes for Morocco and
//!   Alberta/Manitoba that the original lacks are undone.

//!
//! # API overview (for the JS bindings)
//! * time math: [`day`], [`time_within_day`], [`days_in_year`],
//!   [`day_from_year`], [`time_from_year`], [`year_from_time`],
//!   [`in_leap_year`], [`month_from_time`], [`date_from_time`], [`week_day`],
//!   [`hour_from_time`], [`min_from_time`], [`sec_from_time`],
//!   [`ms_from_time`], [`make_time`], [`make_day`], [`make_date`],
//!   [`time_clip`], [`local_tza`], [`local_time`], [`utc`], [`now_ms`],
//!   [`fields`] (all UTC fields at once).
//! * strings: [`to_date_string`], [`to_date_only_string`],
//!   [`to_time_only_string`], [`to_iso_string`], [`to_utc_string`].
//! * parsing: [`parse`] (`Date.parse`, result NOT clipped),
//!   [`parse_for_constructor`] (`new Date(str)`, already clipped).
//! * locale: build a [`DateTimeFormatOptions`] (`set`, `set_hour12`,
//!   `set_fractional_second_digits`), call [`canonicalize_locale_list`]
//!   first (its error must win over option errors), then
//!   [`to_locale_string`] / [`to_locale_date_string`] /
//!   [`to_locale_time_string`] or [`DateTimeFormat`] (`new`, `format`,
//!   `format_to_parts`, `resolved_options`) and [`supported_locales_of`].
//!   Errors are [`DateTimeError`] { kind: Range | Type, message }.

#![allow(dead_code)]

// ============================================================================
// Constants
// ============================================================================

pub const MS_PER_DAY: f64 = 86_400_000.0;
pub const MS_PER_HOUR: f64 = 3_600_000.0;
pub const MS_PER_MINUTE: f64 = 60_000.0;
pub const MS_PER_SECOND: f64 = 1_000.0;
/// Largest magnitude of a valid time value (±100,000,000 days).
pub const MAX_TIME: f64 = 8.64e15;

const WEEKDAY_SHORT: [&str; 7] = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_SHORT: [&str; 12] = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

// ============================================================================
// ECMA-262 §21.4.1 time-value algorithms
// ============================================================================

/// Day(t) = floor(t / msPerDay)
pub fn day(t: f64) -> f64 {
    (t / MS_PER_DAY).floor()
}

/// TimeWithinDay(t) = t modulo msPerDay (result in [0, msPerDay))
pub fn time_within_day(t: f64) -> f64 {
    let r = t % MS_PER_DAY;
    if r < 0.0 {
        r + MS_PER_DAY
    } else {
        r + 0.0
    }
}

/// DaysInYear(y): 365 or 366 (NaN for non-finite input).
pub fn days_in_year(y: f64) -> f64 {
    if !y.is_finite() {
        return f64::NAN;
    }
    if is_leap_year_f(y) {
        366.0
    } else {
        365.0
    }
}

fn is_leap_year_f(y: f64) -> bool {
    (y % 4.0 == 0.0 && y % 100.0 != 0.0) || y % 400.0 == 0.0
}

fn is_leap_year_i(y: i64) -> bool {
    (y % 4 == 0 && y % 100 != 0) || y % 400 == 0
}

/// DayFromYear(y) = 365 × (y − 1970) + floor((y − 1969) / 4) − floor((y − 1901) / 100) + floor((y − 1601) / 400)
pub fn day_from_year(y: f64) -> f64 {
    365.0 * (y - 1970.0) + ((y - 1969.0) / 4.0).floor() - ((y - 1901.0) / 100.0).floor()
        + ((y - 1601.0) / 400.0).floor()
}

/// TimeFromYear(y) = msPerDay × DayFromYear(y)
pub fn time_from_year(y: f64) -> f64 {
    MS_PER_DAY * day_from_year(y)
}

/// Proleptic-Gregorian (year, month 1..=12, day 1..=31) of a day number
/// (days since 1970-01-01).  Exact for any |days| < 2^60 (Howard Hinnant's
/// `civil_from_days`).
pub fn civil_from_days(days: i64) -> (i64, u32, u32) {
    // valid time values need |days| <= 1e8; clamp absurd input (no overflow)
    let z = days.clamp(-(1 << 40), 1 << 40) + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097); // [0, 146096]
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365; // [0, 399]
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32; // [1, 31]
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32; // [1, 12]
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// Day number (days since 1970-01-01) of a proleptic-Gregorian date with
/// `month` in 1..=12 (`day` may be out of range; it is simply added).
pub fn days_from_civil(year: i64, month: u32, day: i64) -> i64 {
    let y = if month <= 2 { year - 1 } else { year };
    let era = y.div_euclid(400);
    let yoe = y.rem_euclid(400);
    let m = month as i64;
    let mp = if m > 2 { m - 3 } else { m + 9 };
    let doy = (153 * mp + 2) / 5;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468 + (day - 1)
}

/// Split a finite time value into (year, month0 0..=11, date 1..=31).
fn ymd_from_time(t: f64) -> (i64, u32, u32) {
    let (y, m, d) = civil_from_days(day(t) as i64);
    (y, m - 1, d)
}

/// YearFromTime(t)
pub fn year_from_time(t: f64) -> f64 {
    if !t.is_finite() {
        return f64::NAN;
    }
    ymd_from_time(t).0 as f64
}

/// InLeapYear(t)
pub fn in_leap_year(t: f64) -> bool {
    t.is_finite() && is_leap_year_i(ymd_from_time(t).0)
}

/// MonthFromTime(t): 0..=11
pub fn month_from_time(t: f64) -> f64 {
    if !t.is_finite() {
        return f64::NAN;
    }
    ymd_from_time(t).1 as f64
}

/// DateFromTime(t): 1..=31
pub fn date_from_time(t: f64) -> f64 {
    if !t.is_finite() {
        return f64::NAN;
    }
    ymd_from_time(t).2 as f64
}

/// WeekDay(t): 0 (Sunday) ..= 6 (Saturday)
pub fn week_day(t: f64) -> f64 {
    if !t.is_finite() {
        return f64::NAN;
    }
    let r = (day(t) + 4.0) % 7.0;
    if r < 0.0 {
        r + 7.0
    } else {
        r + 0.0
    }
}

fn pos_mod(a: f64, b: f64) -> f64 {
    let r = a % b;
    if r < 0.0 {
        r + b
    } else {
        r + 0.0
    }
}

/// HourFromTime(t): 0..=23
pub fn hour_from_time(t: f64) -> f64 {
    if !t.is_finite() {
        return f64::NAN;
    }
    pos_mod((t / MS_PER_HOUR).floor(), 24.0)
}

/// MinFromTime(t): 0..=59
pub fn min_from_time(t: f64) -> f64 {
    if !t.is_finite() {
        return f64::NAN;
    }
    pos_mod((t / MS_PER_MINUTE).floor(), 60.0)
}

/// SecFromTime(t): 0..=59
pub fn sec_from_time(t: f64) -> f64 {
    if !t.is_finite() {
        return f64::NAN;
    }
    pos_mod((t / MS_PER_SECOND).floor(), 60.0)
}

/// msFromTime(t): 0..=999
pub fn ms_from_time(t: f64) -> f64 {
    if !t.is_finite() {
        return f64::NAN;
    }
    pos_mod(t, MS_PER_SECOND)
}

/// ToIntegerOrInfinity for already-numeric input (NaN -> 0 is NOT applied
/// here; callers check finiteness first).
fn to_integer(x: f64) -> f64 {
    x.trunc() + 0.0
}

/// MakeTime(hour, min, sec, ms): NaN if any argument is non-finite.
pub fn make_time(hour: f64, min: f64, sec: f64, ms: f64) -> f64 {
    if !hour.is_finite() || !min.is_finite() || !sec.is_finite() || !ms.is_finite() {
        return f64::NAN;
    }
    let h = to_integer(hour);
    let m = to_integer(min);
    let s = to_integer(sec);
    let milli = to_integer(ms);
    ((h * MS_PER_HOUR + m * MS_PER_MINUTE) + s * MS_PER_SECOND) + milli
}

/// Cumulative days before month `m0` (0..=11).
fn days_before_month(m0: usize, leap: bool) -> f64 {
    const CUM: [u16; 12] = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
    let extra = if leap && m0 >= 2 { 1.0 } else { 0.0 };
    CUM[m0] as f64 + extra
}

/// MakeDay(year, month, date).
///
/// Like the original runtime, the combined year `year + floor(month / 12)` is
/// range-checked against ±300000 (beyond that the result is NaN even if a
/// huge negative `date` would bring the final value back into range).
pub fn make_day(year: f64, month: f64, date: f64) -> f64 {
    if !year.is_finite() || !month.is_finite() || !date.is_finite() {
        return f64::NAN;
    }
    let y = to_integer(year);
    let m = to_integer(month);
    let dt = to_integer(date);
    let ym = y + (m / 12.0).floor();
    if !ym.is_finite() || ym.abs() > 300_000.0 {
        return f64::NAN;
    }
    let mn = pos_mod(m, 12.0) as usize;
    let leap = is_leap_year_f(ym);
    day_from_year(ym) + days_before_month(mn.min(11), leap) + dt - 1.0
}

/// MakeDate(day, time)
pub fn make_date(day: f64, time: f64) -> f64 {
    if !day.is_finite() || !time.is_finite() {
        return f64::NAN;
    }
    let tv = day * MS_PER_DAY + time;
    if !tv.is_finite() {
        return f64::NAN;
    }
    tv
}

/// TimeClip(time): NaN outside ±8.64e15, otherwise ToIntegerOrInfinity (with
/// -0 normalised to +0).
pub fn time_clip(time: f64) -> f64 {
    if !time.is_finite() || time.abs() > MAX_TIME {
        return f64::NAN;
    }
    to_integer(time)
}

/// LocalTZA(t, isUTC) in milliseconds.  The original runtime always uses UTC
/// as its local time zone (the TZ environment variable is ignored), so this
/// is always 0.
pub fn local_tza(_t: f64, _is_utc: bool) -> f64 {
    0.0
}

/// LocalTime(t) = t + LocalTZA(t, true)
pub fn local_time(t: f64) -> f64 {
    t + local_tza(t, true)
}

/// UTC(t) = t − LocalTZA(t, false)
pub fn utc(t: f64) -> f64 {
    t - local_tza(t, false)
}

/// Current time in whole milliseconds since the epoch (Date.now()).
pub fn now_ms() -> f64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(d) => d.as_millis() as f64,
        Err(e) => -(e.duration().as_millis() as f64),
    }
}

// ============================================================================
// Fixed-format string conversions
// ============================================================================

/// Broken-down UTC fields of a finite time value.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Fields {
    pub year: i64,
    /// 0..=11
    pub month: u32,
    /// 1..=31
    pub day: u32,
    /// 0 = Sunday
    pub weekday: u32,
    pub hour: u32,
    pub minute: u32,
    pub second: u32,
    pub millisecond: u32,
}

/// Break a finite time value into calendar fields (no time-zone shift).
pub fn fields(t: f64) -> Fields {
    let days = day(t);
    let (year, month, d) = ymd_from_time(t);
    let ms_in_day = time_within_day(t) as i64;
    Fields {
        year,
        month,
        day: d,
        weekday: pos_mod(days + 4.0, 7.0) as u32,
        hour: (ms_in_day / 3_600_000) as u32,
        minute: (ms_in_day / 60_000 % 60) as u32,
        second: (ms_in_day / 1000 % 60) as u32,
        millisecond: (ms_in_day % 1000) as u32,
    }
}

/// Year as printed by toString/toDateString/toUTCString: at least 4 digits,
/// with a leading '-' for negative years ("-0001", "0000", "12345").
fn format_year_legacy(y: i64) -> String {
    if y < 0 {
        format!("-{:04}", -y)
    } else {
        format!("{:04}", y)
    }
}

const LOCAL_TZ_SUFFIX: &str = "GMT+0000 (Coordinated Universal Time)";

/// Date.prototype.toString: "Thu Jan 01 1970 00:00:00 GMT+0000 (Coordinated Universal Time)"
/// ("Invalid Date" for NaN).
pub fn to_date_string(t: f64) -> String {
    if time_clip(t).is_nan() {
        return "Invalid Date".to_string();
    }
    let f = fields(local_time(t));
    format!(
        "{} {} {:02} {} {:02}:{:02}:{:02} {}",
        WEEKDAY_SHORT[f.weekday as usize],
        MONTH_SHORT[f.month as usize],
        f.day,
        format_year_legacy(f.year),
        f.hour,
        f.minute,
        f.second,
        LOCAL_TZ_SUFFIX
    )
}

/// Date.prototype.toDateString: "Thu Jan 01 1970"
pub fn to_date_only_string(t: f64) -> String {
    if time_clip(t).is_nan() {
        return "Invalid Date".to_string();
    }
    let f = fields(local_time(t));
    format!(
        "{} {} {:02} {}",
        WEEKDAY_SHORT[f.weekday as usize],
        MONTH_SHORT[f.month as usize],
        f.day,
        format_year_legacy(f.year)
    )
}

/// Date.prototype.toTimeString: "00:00:00 GMT+0000 (Coordinated Universal Time)"
pub fn to_time_only_string(t: f64) -> String {
    if time_clip(t).is_nan() {
        return "Invalid Date".to_string();
    }
    let f = fields(local_time(t));
    format!(
        "{:02}:{:02}:{:02} {}",
        f.hour, f.minute, f.second, LOCAL_TZ_SUFFIX
    )
}

/// Date.prototype.toISOString: "1970-01-01T00:00:00.000Z"; years outside
/// 0..=9999 use the expanded form "+275760-09-13T00:00:00.000Z" /
/// "-000001-01-01T00:00:00.000Z".  `None` for NaN: the caller must throw
/// `RangeError: Invalid time value`.
pub fn to_iso_string(t: f64) -> Option<String> {
    if time_clip(t).is_nan() {
        return None;
    }
    let f = fields(t);
    let year = if (0..=9999).contains(&f.year) {
        format!("{:04}", f.year)
    } else if f.year < 0 {
        format!("-{:06}", -f.year)
    } else {
        format!("+{:06}", f.year)
    };
    Some(format!(
        "{}-{:02}-{:02}T{:02}:{:02}:{:02}.{:03}Z",
        year,
        f.month + 1,
        f.day,
        f.hour,
        f.minute,
        f.second,
        f.millisecond
    ))
}

/// Date.prototype.toUTCString / toGMTString: "Thu, 01 Jan 1970 00:00:00 GMT"
pub fn to_utc_string(t: f64) -> String {
    if time_clip(t).is_nan() {
        return "Invalid Date".to_string();
    }
    let f = fields(t);
    format!(
        "{}, {:02} {} {} {:02}:{:02}:{:02} GMT",
        WEEKDAY_SHORT[f.weekday as usize],
        f.day,
        MONTH_SHORT[f.month as usize],
        format_year_legacy(f.year),
        f.hour,
        f.minute,
        f.second
    )
}

// ============================================================================
// Parsing
// ============================================================================

/// `Date.parse(s)`: strict ISO ([`parse_iso`]), then the space-separated
/// ISO-like form, then the legacy free-form parser ([`parse_legacy`]).
/// Returns NaN when unrecognised.  NOTE: values produced by the legacy parser
/// are *not* TimeClip'ed (the original returns e.g. 8640000086400000 for
/// "Sep 14 275760"), and its arithmetic wraps like i64.
pub fn parse(s: &str) -> f64 {
    let iso = parse_for_constructor(s);
    if !iso.is_nan() {
        return iso;
    }
    parse_legacy(s).unwrap_or(f64::NAN)
}

/// String parsing used by `new Date(string)`: the original only accepts the
/// two ISO-like formats there (legacy strings such as "Mar 7 2020" or even
/// its own toString() output give an Invalid Date).  The result is already
/// TimeClip'ed.
pub fn parse_for_constructor(s: &str) -> f64 {
    let s = s.trim();
    if let Some(t) = parse_iso_inner(s) {
        return t;
    }
    parse_space_separated(s).unwrap_or(f64::NAN)
}

struct IsoCursor<'a> {
    b: &'a [u8],
    i: usize,
}

impl<'a> IsoCursor<'a> {
    fn peek(&self) -> Option<u8> {
        self.b.get(self.i).copied()
    }
    fn eat(&mut self, c: u8) -> bool {
        if self.peek() == Some(c) {
            self.i += 1;
            true
        } else {
            false
        }
    }
    /// Exactly `n` ASCII digits.
    fn digits(&mut self, n: usize) -> Option<i64> {
        let mut v: i64 = 0;
        for k in 0..n {
            let c = *self.b.get(self.i + k)?;
            if !c.is_ascii_digit() {
                return None;
            }
            v = v * 10 + (c - b'0') as i64;
        }
        self.i += n;
        Some(v)
    }
}

/// The ISO-8601 subset accepted by the original (after Rust-style `trim()`,
/// i.e. Unicode White_Space, which does NOT include U+FEFF):
///
/// ```text
///   YYYY | (+|-)YYYYYY        ("-000000" rejected)
///   [ -MM [ -DD ] ]
///   [ (T|' ') HH [ :mm [ :ss ] ] [ .f+ ] [ Z | (+|-)HH:mm ] ]
/// ```
///
/// Field values are NOT range-checked: "2020-13-01" is 2021-01-01,
/// "2020-02-30" is 2020-03-01, "T24:00:01" / "T25:00" / "T12:60" overflow
/// into the next unit, offsets "+99:99" are accepted.  Date-only forms are
/// UTC, date-time forms without offset are local time (= UTC here).  The
/// final value is TimeClip'ed.
pub fn parse_iso(s: &str) -> f64 {
    parse_iso_inner(s.trim()).unwrap_or(f64::NAN)
}

fn parse_iso_inner(s: &str) -> Option<f64> {
    let mut c = IsoCursor { b: s.as_bytes(), i: 0 };
    let year = match c.peek()? {
        b'+' | b'-' => {
            let neg = c.peek() == Some(b'-');
            c.i += 1;
            let v = c.digits(6)?;
            if neg && v == 0 {
                return None;
            }
            if neg {
                -v
            } else {
                v
            }
        }
        _ => c.digits(4)?,
    };
    let mut month = 1i64;
    let mut dayv = 1i64;
    if c.eat(b'-') {
        month = c.digits(2)?;
        if c.eat(b'-') {
            dayv = c.digits(2)?;
        }
    }
    let (mut h, mut mi, mut sec, mut ms) = (0i64, 0i64, 0i64, 0i64);
    let mut offset_min = 0i64;
    if c.eat(b'T') || c.eat(b' ') {
        h = c.digits(2)?;
        if c.eat(b':') {
            mi = c.digits(2)?;
            if c.eat(b':') {
                sec = c.digits(2)?;
            }
        }
        if c.eat(b'.') {
            let start = c.i;
            let mut frac = 0i64;
            while let Some(d) = c.peek() {
                if !d.is_ascii_digit() {
                    break;
                }
                if c.i - start < 3 {
                    frac = frac * 10 + (d - b'0') as i64;
                }
                c.i += 1;
            }
            let n = c.i - start;
            if n == 0 {
                return None;
            }
            for _ in n..3 {
                frac *= 10;
            }
            ms = frac;
        }
        if c.eat(b'Z') {
            // UTC
        } else if let Some(sign @ (b'+' | b'-')) = c.peek() {
            c.i += 1;
            let oh = c.digits(2)?;
            if !c.eat(b':') {
                return None;
            }
            let om = c.digits(2)?;
            offset_min = oh * 60 + om;
            if sign == b'-' {
                offset_min = -offset_min;
            }
        }
        // (no offset: local time, which is UTC in this runtime)
    }
    if c.i != c.b.len() {
        return None;
    }
    let dayn = make_day(year as f64, (month - 1) as f64, dayv as f64);
    let time = make_time(h as f64, mi as f64, sec as f64, ms as f64);
    let t = make_date(dayn, time) - offset_min as f64 * MS_PER_MINUTE;
    let t = time_clip(t);
    if t.is_nan() {
        None
    } else {
        Some(t)
    }
}

/// Howard Hinnant's days_from_civil with *wrapping* i64 arithmetic, exactly as
/// the original's legacy parser computes it (observable for absurd years).
fn days_from_civil_wrapping(year: i64, month: i64, day: i64) -> i64 {
    let y = if month <= 2 { year.wrapping_sub(1) } else { year };
    let era = (if y >= 0 { y } else { y.wrapping_sub(399) }) / 400;
    let yoe = y.wrapping_sub(era.wrapping_mul(400));
    let mp = if month > 2 { month - 3 } else { month + 9 };
    let doy = (153 * mp + 2) / 5 + day - 1;
    let doe = yoe
        .wrapping_mul(365)
        .wrapping_add(yoe / 4)
        .wrapping_sub(yoe / 100)
        .wrapping_add(doy);
    era.wrapping_mul(146_097).wrapping_add(doe).wrapping_sub(719_468)
}

fn month_from_word(tok: &str) -> Option<i64> {
    const NAMES: [&str; 12] = [
        "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    ];
    let b = tok.as_bytes();
    if b.len() < 3 {
        return None;
    }
    let p = [
        b[0].to_ascii_lowercase(),
        b[1].to_ascii_lowercase(),
        b[2].to_ascii_lowercase(),
    ];
    NAMES
        .iter()
        .position(|n| n.as_bytes() == p)
        .map(|i| i as i64 + 1)
}

/// Offset in minutes from the ASCII digits of `s`: needs at least four
/// digits, the first four are read as HHMM (no range check).
fn offset_from_digits(s: &str, negative: bool) -> Option<i64> {
    let d: Vec<i64> = s
        .bytes()
        .filter(|c| c.is_ascii_digit())
        .take(4)
        .map(|c| (c - b'0') as i64)
        .collect();
    if d.len() < 4 {
        return None;
    }
    let v = (d[0] * 10 + d[1]) * 60 + d[2] * 10 + d[3];
    Some(if negative { -v } else { v })
}

/// "GMT..." token: optional sign right after "GMT", then >= 4 digits anywhere.
fn gmt_offset(tok: &str) -> Option<i64> {
    let rest = &tok[3..];
    let negative = rest.starts_with('-');
    offset_from_digits(rest, negative)
}

fn starts_with_gmt(tok: &str) -> bool {
    tok.len() >= 3 && tok.as_bytes()[..3].eq_ignore_ascii_case(b"gmt")
}

/// The original's legacy (non-ISO) parser, reverse-engineered:
///
/// * Tokens are separated by Unicode whitespace, ',', '(' and ')' (parens are
///   *not* comments).
/// * A token whose first three letters (ASCII, case-insensitive) are a month
///   abbreviation sets the month ("Septembre", "Marathon", "Mar7" all count);
///   the last one wins.
/// * Otherwise a token containing ':' is the time if no time was seen yet:
///   split on ':' and each of the first three parts is parsed as an i64
///   (Rust syntax, optional sign) with failure -> 0 ("10:20:30.5" is
///   10:20:00, "T10:00" is 00:00).  Later ':' tokens go through the rules
///   below (so "+05:45" after a time is an offset, "11:00" is ignored).
/// * A token starting with "GMT" (case-insensitive) is an offset: optional
///   sign immediately after "GMT", then the first four ASCII digits found
///   (colons/garbage skipped) are HHMM; fewer than four digits -> ignored.
///   "UTC", "UT", "Z", "EST", "PDT", "AM", "PM", weekday names and any other
///   words are ignored (AM/PM have no effect!).
/// * A token that parses as an i64 is a number: if it has >= 4 characters or
///   its value is > 31 it is the year (overwriting any earlier year, so
///   "Mar 7 2020 +0200" is year 200); else it fills the day if unset, else
///   the year if unset, else it is ignored.  No two-digit-year mapping.
/// * Any other token starting with '+' or '-' (e.g. "-+0530", "+0100x",
///   or "+05:45" once a time was seen) is an offset from its first four
///   digits (needs >= 4 digits; the sign is the first character).
/// * Month, day and year are all required.  The result is computed with
///   wrapping i64 arithmetic and NOT TimeClip'ed.
pub fn parse_legacy(s: &str) -> Option<f64> {
    let mut month: Option<i64> = None;
    let mut dayv: Option<i64> = None;
    let mut year: Option<i64> = None;
    let mut time: Option<i64> = None;
    let mut offset: Option<i64> = None;
    let tokens = s
        .split(|c: char| c.is_whitespace() || c == ',' || c == '(' || c == ')')
        .filter(|t| !t.is_empty());
    for tok in tokens {
        if let Some(m) = month_from_word(tok) {
            month = Some(m);
            continue;
        }
        if tok.contains(':') && time.is_none() {
            {
                let mut parts = tok.split(':');
                let mut next = || {
                    parts
                        .next()
                        .and_then(|p| p.parse::<i64>().ok())
                        .unwrap_or(0)
                };
                let h = next();
                let m = next();
                let sec = next();
                time = Some(
                    h.wrapping_mul(3_600_000)
                        .wrapping_add(m.wrapping_mul(60_000))
                        .wrapping_add(sec.wrapping_mul(1000)),
                );
            }
            continue;
        }
        if starts_with_gmt(tok) {
            if let Some(o) = gmt_offset(tok) {
                offset = Some(o);
            }
            continue;
        }
        if let Ok(n) = tok.parse::<i64>() {
            if tok.len() >= 4 || n > 31 {
                year = Some(n);
            } else if dayv.is_none() {
                dayv = Some(n);
            } else if year.is_none() {
                year = Some(n);
            }
            continue;
        }
        if tok.starts_with('+') || tok.starts_with('-') {
            if let Some(o) = offset_from_digits(tok, tok.starts_with('-')) {
                offset = Some(o);
            }
        }
    }
    let (m, d, y) = (month?, dayv?, year?);
    let days = days_from_civil_wrapping(y, m, d);
    // date + time in wrapping i64, the offset is then subtracted in f64
    let local = days
        .wrapping_mul(86_400_000)
        .wrapping_add(time.unwrap_or(0));
    Some(local as f64 - (offset.unwrap_or(0) * 60_000) as f64)
}

/// Optional sign followed by 1+ ASCII digits parsed as i64 ("-0..." is
/// rejected, like "-000000" in ISO).
fn relaxed_year(s: &str) -> Option<i64> {
    let (neg, digits) = match s.as_bytes().first()? {
        b'+' => (false, &s[1..]),
        b'-' => (true, &s[1..]),
        _ => (false, s),
    };
    if digits.is_empty() || !digits.bytes().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let v: i64 = digits.parse().ok()?;
    if neg {
        if v == 0 {
            return None;
        }
        Some(-v)
    } else {
        Some(v)
    }
}

/// 1 or 2 ASCII digits.
fn one_or_two_digits(s: &str) -> Option<i64> {
    if s.is_empty() || s.len() > 2 || !s.bytes().all(|c| c.is_ascii_digit()) {
        return None;
    }
    s.parse().ok()
}

/// The second ISO-like format of the original: "<date> <time>" split at the
/// first U+0020, with relaxed field widths:
///
/// ```text
///   date: [+|-]Y+ [ -M{1,2} [ -D{1,2} ] ]
///   time: H{1,2} [ :m{1,2} [ :s{1,2} ] ] [ .f+ ] [ Z | (+|-)HH | (+|-)HHMM | (+|-)HH:MM ]
/// ```
///
/// The offset is introduced by the LAST '+'/'-' of the time part (`±HH:`
/// is accepted too).  Computed
/// with wrapping i64 arithmetic (month normalised into the year first), then
/// range-checked like TimeClip.  (Where the original panics on a non-ASCII
/// 4-byte offset, NaN is returned.)
fn parse_space_separated(s: &str) -> Option<f64> {
    let (date, time) = s.split_once(' ')?;
    // --- date (a leading sign belongs to the year) ---
    let sign_len = usize::from(date.starts_with('-') || date.starts_with('+'));
    let mut it = date[sign_len..].splitn(3, '-');
    let ytxt = it.next()?;
    let year = relaxed_year(&date[..sign_len + ytxt.len()])?;
    let month = match it.next() {
        Some(m) => one_or_two_digits(m)?,
        None => 1,
    };
    let dayv = match it.next() {
        Some(d) => one_or_two_digits(d)?,
        None => 1,
    };
    // --- offset ---
    let mut offset_min: i64 = 0;
    let mut rest = time;
    if let Some(p) = time.rfind(|c| c == '+' || c == '-') {
        let neg = time.as_bytes()[p] == b'-';
        let off = &time[p + 1..];
        let (hh, mm) = match off.len() {
            2 => (off, "0"),
            3 if off.ends_with(':') => (&off[..2], "0"),
            4 => {
                if !off.is_char_boundary(2) {
                    return None; // the original panics here
                }
                (&off[..2], &off[2..])
            }
            5 => {
                if off.as_bytes()[2] != b':' || !off.is_char_boundary(2) || !off.is_char_boundary(3) {
                    return None;
                }
                (&off[..2], &off[3..])
            }
            _ => return None,
        };
        let hh: i64 = hh.parse().ok()?;
        let mm: i64 = mm.parse().ok()?;
        offset_min = hh * 60 + mm;
        if neg {
            offset_min = -offset_min;
        }
        rest = &time[..p];
    } else if let Some(r) = time.strip_suffix('Z') {
        rest = r;
    }
    // --- time ---
    let (hms, frac) = match rest.split_once('.') {
        Some((a, f)) => (a, Some(f)),
        None => (rest, None),
    };
    let mut tp = hms.split(':');
    let h = one_or_two_digits(tp.next()?)?;
    let mi = match tp.next() {
        Some(x) => one_or_two_digits(x)?,
        None => 0,
    };
    let sec = match tp.next() {
        Some(x) => one_or_two_digits(x)?,
        None => 0,
    };
    if tp.next().is_some() {
        return None;
    }
    let ms = match frac {
        Some(f) => {
            if f.is_empty() || !f.bytes().all(|c| c.is_ascii_digit()) {
                return None;
            }
            let mut v = 0i64;
            for (k, c) in f.bytes().take(3).enumerate() {
                v += (c - b'0') as i64 * [100, 10, 1][k];
            }
            v
        }
        None => 0,
    };
    // --- combine (wrapping i64, month normalised first) ---
    let y = year.wrapping_add((month - 1).div_euclid(12));
    let m = (month - 1).rem_euclid(12) + 1;
    let days = days_from_civil_wrapping(y, m, dayv);
    let t = days
        .wrapping_mul(86_400_000)
        .wrapping_add(h * 3_600_000 + mi * 60_000 + sec * 1000 + ms)
        .wrapping_sub(offset_min * 60_000);
    let t = t as f64;
    if t.abs() > MAX_TIME {
        return None;
    }
    Some(t + 0.0)
}

// ============================================================================
// Locale-sensitive formatting (the subset of Intl.DateTimeFormat used by
// Date.prototype.toLocaleString / toLocaleDateString / toLocaleTimeString)
// ============================================================================

/// Error kind of a [`DateTimeError`] (which JS error the caller should throw).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ErrorKind {
    Range,
    Type,
}

/// An error with the exact message the original runtime uses.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DateTimeError {
    pub kind: ErrorKind,
    pub message: String,
}

impl DateTimeError {
    fn range(message: String) -> Self {
        DateTimeError { kind: ErrorKind::Range, message }
    }
    fn type_error(message: &str) -> Self {
        DateTimeError { kind: ErrorKind::Type, message: message.to_string() }
    }
}

impl std::fmt::Display for DateTimeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let k = match self.kind {
            ErrorKind::Range => "RangeError",
            ErrorKind::Type => "TypeError",
        };
        write!(f, "{}: {}", k, self.message)
    }
}

// ---------------------------------------------------------------------------
// BCP 47 / UTS 35 language tags
// ---------------------------------------------------------------------------

/// A structurally valid, canonicalised Unicode locale identifier.
#[derive(Clone, Debug, PartialEq, Eq)]
struct LanguageTag {
    language: String,
    script: Option<String>,
    region: Option<String>,
    variants: Vec<String>,
    /// -u- attributes (kept only for supportedLocalesOf output)
    u_attributes: Vec<String>,
    /// -u- keywords in canonical (sorted, de-duplicated) order; value "" = true
    u_keywords: Vec<(String, String)>,
    /// other extensions (singleton, rest) in canonical order, already lowercase
    other_ext: Vec<(char, String)>,
    /// private use subtags (after "x-")
    private_use: Option<String>,
}

fn is_alpha(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_alphabetic())
}
fn is_digit(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit())
}
fn is_alnum(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_alphanumeric())
}

fn parse_language_tag(tag: &str) -> Option<LanguageTag> {
    if tag.is_empty() || !tag.is_ascii() {
        return None;
    }
    let lower = tag.to_ascii_lowercase();
    let subtags: Vec<&str> = lower.split('-').collect();
    if subtags.iter().any(|s| s.is_empty() || s.len() > 8) {
        return None;
    }
    let mut i = 0;
    let lang = subtags[0];
    if !(is_alpha(lang) && (lang.len() == 2 || lang.len() == 3 || (5..=8).contains(&lang.len()))) {
        return None;
    }
    i += 1;
    let mut script = None;
    if i < subtags.len() && subtags[i].len() == 4 && is_alpha(subtags[i]) {
        let s = subtags[i];
        script = Some(s[..1].to_ascii_uppercase() + &s[1..]);
        i += 1;
    }
    let mut region = None;
    if i < subtags.len() {
        let s = subtags[i];
        if (s.len() == 2 && is_alpha(s)) || (s.len() == 3 && is_digit(s)) {
            region = Some(s.to_ascii_uppercase());
            i += 1;
        }
    }
    let mut variants: Vec<String> = Vec::new();
    while i < subtags.len() {
        let s = subtags[i];
        let ok = is_alnum(s)
            && ((5..=8).contains(&s.len())
                || (s.len() == 4 && s.as_bytes()[0].is_ascii_digit()));
        if !ok {
            break;
        }
        if variants.iter().any(|v| v == s) {
            return None;
        }
        variants.push(s.to_string());
        i += 1;
    }
    variants.sort();
    let mut u_attributes = Vec::new();
    let mut u_keywords: Vec<(String, String)> = Vec::new();
    let mut other_ext: Vec<(char, String)> = Vec::new();
    let mut seen_singletons: Vec<char> = Vec::new();
    let mut private_use = None;
    while i < subtags.len() {
        let s = subtags[i];
        if s.len() != 1 {
            return None;
        }
        let singleton = s.as_bytes()[0] as char;
        i += 1;
        if singleton == 'x' {
            let rest = &subtags[i..];
            if rest.is_empty() || !rest.iter().all(|p| is_alnum(p)) {
                return None;
            }
            private_use = Some(rest.join("-"));
            i = subtags.len();
            break;
        }
        if !singleton.is_ascii_alphanumeric() || seen_singletons.contains(&singleton) {
            return None;
        }
        seen_singletons.push(singleton);
        let start = i;
        while i < subtags.len() && subtags[i].len() > 1 {
            i += 1;
        }
        let body = &subtags[start..i];
        if body.is_empty() {
            return None;
        }
        match singleton {
            'u' => {
                let mut k = 0;
                while k < body.len() && body[k].len() >= 3 {
                    if !is_alnum(body[k]) {
                        return None;
                    }
                    u_attributes.push(body[k].to_string());
                    k += 1;
                }
                while k < body.len() {
                    let key = body[k];
                    let kb = key.as_bytes();
                    if key.len() != 2 || !kb[0].is_ascii_alphanumeric() || !kb[1].is_ascii_alphabetic() {
                        return None;
                    }
                    k += 1;
                    let vs = k;
                    while k < body.len() && body[k].len() >= 3 {
                        if !is_alnum(body[k]) {
                            return None;
                        }
                        k += 1;
                    }
                    let mut value = body[vs..k].join("-");
                    if value == "true" {
                        value.clear();
                    }
                    if key == "ca" {
                        match value.as_str() {
                            "islamicc" => value = "islamic-civil".to_string(),
                            "ethiopic-amete-alem" => value = "ethioaa".to_string(),
                            _ => {}
                        }
                    }
                    if !u_keywords.iter().any(|(kk, _)| kk == key) {
                        u_keywords.push((key.to_string(), value));
                    }
                }
            }
            't' => {
                if !valid_transformed_extension(body) {
                    return None;
                }
                other_ext.push(('t', body.join("-")));
            }
            _ => {
                if !body.iter().all(|p| is_alnum(p) && p.len() >= 2) {
                    return None;
                }
                other_ext.push((singleton, body.join("-")));
            }
        }
    }
    if i != subtags.len() {
        return None;
    }
    u_keywords.sort_by(|a, b| a.0.cmp(&b.0));
    other_ext.sort_by(|a, b| a.0.cmp(&b.0));
    let mut t = LanguageTag {
        language: lang.to_string(),
        script,
        region,
        variants,
        u_attributes,
        u_keywords,
        other_ext,
        private_use,
    };
    apply_language_alias(&mut t);
    Some(t)
}

/// `-t-` extension body: `tlang? tfield*` (at least one), where tlang is a
/// unicode_language_id and tfield = (alpha digit) (3*8alphanum)+.
fn valid_transformed_extension(body: &[&str]) -> bool {
    let mut i = 0;
    let n = body.len();
    let is_lang = |s: &str| is_alpha(s) && (s.len() == 2 || s.len() == 3 || (5..=8).contains(&s.len()));
    if i < n && is_lang(body[i]) {
        i += 1;
        if i < n && body[i].len() == 4 && is_alpha(body[i]) {
            i += 1;
        }
        if i < n
            && ((body[i].len() == 2 && is_alpha(body[i])) || (body[i].len() == 3 && is_digit(body[i])))
        {
            i += 1;
        }
        while i < n
            && is_alnum(body[i])
            && ((5..=8).contains(&body[i].len())
                || (body[i].len() == 4 && body[i].as_bytes()[0].is_ascii_digit()))
        {
            i += 1;
        }
    }
    let had_lang = i > 0;
    let mut had_field = false;
    while i < n {
        let k = body[i].as_bytes();
        if !(k.len() == 2 && k[0].is_ascii_alphabetic() && k[1].is_ascii_digit()) {
            return false;
        }
        i += 1;
        let st = i;
        while i < n && (3..=8).contains(&body[i].len()) && is_alnum(body[i]) {
            i += 1;
        }
        if i == st {
            return false;
        }
        had_field = true;
    }
    had_lang || had_field
}

/// UN M.49 numeric region codes with an alpha-2 equivalent (common ones).
const REGION_ALIASES: &[(&str, &str)] = &[
    ("012", "DZ"), ("036", "AU"), ("040", "AT"), ("056", "BE"), ("076", "BR"), ("124", "CA"),
    ("156", "CN"), ("158", "TW"), ("250", "FR"), ("276", "DE"), ("344", "HK"), ("356", "IN"),
    ("380", "IT"), ("392", "JP"), ("410", "KR"), ("446", "MO"), ("484", "MX"), ("504", "MA"),
    ("528", "NL"), ("616", "PL"), ("620", "PT"), ("643", "RU"), ("682", "SA"), ("724", "ES"),
    ("752", "SE"), ("756", "CH"), ("764", "TH"), ("788", "TN"), ("818", "EG"), ("826", "GB"),
    ("840", "US"),
];

/// A few CLDR language aliases (enough for the supported locales).
fn apply_language_alias(t: &mut LanguageTag) {
    if let Some(r) = t.region.as_deref() {
        if let Some((_, a)) = REGION_ALIASES.iter().find(|(n, _)| *n == r) {
            t.region = Some(a.to_string());
        }
    }
    let (lang, script): (&str, Option<&str>) = match t.language.as_str() {
        "sh" => ("sr", Some("Latn")),
        "cmn" => ("zh", None),
        "iw" => ("he", None),
        "in" => ("id", None),
        "ji" => ("yi", None),
        "jw" => ("jv", None),
        "mo" => ("ro", None),
        "tl" => ("fil", None),
        _ => return,
    };
    t.language = lang.to_string();
    if t.script.is_none() {
        t.script = script.map(|s| s.to_string());
    }
}

impl LanguageTag {
    fn base_name(&self) -> String {
        let mut s = self.language.clone();
        if let Some(sc) = &self.script {
            s.push('-');
            s.push_str(sc);
        }
        if let Some(r) = &self.region {
            s.push('-');
            s.push_str(r);
        }
        for v in &self.variants {
            s.push('-');
            s.push_str(v);
        }
        s
    }

    fn keyword(&self, key: &str) -> Option<&str> {
        self.u_keywords
            .iter()
            .find(|(k, _)| k == key)
            .map(|(_, v)| v.as_str())
    }

    /// Full canonical form (as returned by Intl.getCanonicalLocales).
    fn to_canonical_string(&self) -> String {
        let mut s = self.base_name();
        let mut exts: Vec<(char, String)> = self.other_ext.clone();
        if !self.u_attributes.is_empty() || !self.u_keywords.is_empty() {
            let mut u = self.u_attributes.join("-");
            for (k, v) in &self.u_keywords {
                if !u.is_empty() {
                    u.push('-');
                }
                u.push_str(k);
                if !v.is_empty() {
                    u.push('-');
                    u.push_str(v);
                }
            }
            exts.push(('u', u));
        }
        exts.sort_by(|a, b| a.0.cmp(&b.0));
        for (c, body) in exts {
            s.push('-');
            s.push(c);
            s.push('-');
            s.push_str(&body);
        }
        if let Some(p) = &self.private_use {
            s.push_str("-x-");
            s.push_str(p);
        }
        s
    }
}

/// CanonicalizeLocaleList for a list of tag strings.  Error message matches
/// the original: `RangeError: Incorrect locale information provided: <tag>`.
pub fn canonicalize_locale_list(locales: &[String]) -> Result<Vec<String>, DateTimeError> {
    let mut out: Vec<String> = Vec::new();
    for l in locales {
        let t = parse_language_tag(l).ok_or_else(|| {
            DateTimeError::range(format!("Incorrect locale information provided: {}", l))
        })?;
        let c = t.to_canonical_string();
        if !out.contains(&c) {
            out.push(c);
        }
    }
    Ok(out)
}

/// Intl.DateTimeFormat.supportedLocalesOf (canonicalised tags whose language
/// has locale data).
pub fn supported_locales_of(locales: &[String]) -> Result<Vec<String>, DateTimeError> {
    let mut out = Vec::new();
    for l in locales {
        let t = parse_language_tag(l).ok_or_else(|| {
            DateTimeError::range(format!("Incorrect locale information provided: {}", l))
        })?;
        if t.private_use.is_some() && t.language.is_empty() {
            continue;
        }
        if locale_info(&t.language).is_some() {
            let c = t.to_canonical_string();
            if !out.contains(&c) {
                out.push(c);
            }
        }
    }
    Ok(out)
}

// ---------------------------------------------------------------------------
// Locale data
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum DateOrder {
    Mdy,
    Dmy,
    Ymd,
}

struct LocaleInfo {
    lang: &'static str,
    order: DateOrder,
    sep: &'static str,
    /// [long, short, narrow] month names; None = the locale has no month
    /// names and textual months fall back to the numeric pattern.
    months: Option<&'static [[&'static str; 12]; 3]>,
    /// [long, short, narrow] x [BC, AD]
    eras: [[&'static str; 2]; 3],
    /// hour cycle used when hour12 is true
    h12: HourCycle,
    default_hc: HourCycle,
    default_nu: &'static str,
}

// Locale data observed in the original runtime (weekday, AM/PM and day-period
// names are always English there).
const MONTHS_EN: [[&str; 12]; 3] = [
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"],
];
const MONTHS_AR: [[&str; 12]; 3] = [
    ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"],
    ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"],
    ["ي", "ف", "م", "أ", "و", "ن", "ل", "غ", "س", "ك", "ب", "د"],
];
const MONTHS_DE: [[&str; 12]; 3] = [
    ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"],
    ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sept.", "Okt.", "Nov.", "Dez."],
    ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"],
];
const MONTHS_ES: [[&str; 12]; 3] = [
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
    ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic"],
    ["E", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"],
];
const MONTHS_FR: [[&str; 12]; 3] = [
    ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
    ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."],
    ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"],
];
const MONTHS_IT: [[&str; 12]; 3] = [
    ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"],
    ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"],
    ["G", "F", "M", "A", "M", "G", "L", "A", "S", "O", "N", "D"],
];
const MONTHS_JA: [[&str; 12]; 3] = [
    ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"],
    ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"],
    ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"],
];
const MONTHS_KO: [[&str; 12]; 3] = [
    ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"],
    ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"],
    ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"],
];
const MONTHS_NL: [[&str; 12]; 3] = [
    ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december"],
    ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"],
    ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"],
];
const MONTHS_PT: [[&str; 12]; 3] = [
    ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"],
    ["jan.", "fev.", "mar.", "abr.", "mai.", "jun.", "jul.", "ago.", "set.", "out.", "nov.", "dez."],
    ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"],
];
const MONTHS_RU: [[&str; 12]; 3] = [
    ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"],
    ["янв.", "февр.", "мар.", "апр.", "мая", "июн.", "июл.", "авг.", "сент.", "окт.", "нояб.", "дек."],
    ["Я", "Ф", "М", "А", "М", "И", "И", "А", "С", "О", "Н", "Д"],
];
const MONTHS_ZH: [[&str; 12]; 3] = [
    ["一月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "十一月", "十二月"],
    ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"],
    ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"],
];
const LOCALES: &[LocaleInfo] = &[
    LocaleInfo { lang: "en", order: DateOrder::Mdy, sep: "/", months: Some(&MONTHS_EN), eras: [["Before Christ", "Anno Domini"], ["BC", "AD"], ["B", "A"]], h12: HourCycle::H12, default_hc: HourCycle::H12, default_nu: "latn" },
    LocaleInfo { lang: "ar", order: DateOrder::Dmy, sep: "/", months: Some(&MONTHS_AR), eras: [["قبل الميلاد", "ميلادي"], ["ق.م", "م"], ["ق.م", "م"]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "arab" },
    LocaleInfo { lang: "de", order: DateOrder::Dmy, sep: ".", months: Some(&MONTHS_DE), eras: [["v. Chr.", "n. Chr."], ["v. Chr.", "n. Chr."], ["v. Chr.", "n. Chr."]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "es", order: DateOrder::Dmy, sep: "/", months: Some(&MONTHS_ES), eras: [["antes de Cristo", "después de Cristo"], ["a. C.", "d. C."], ["a. C.", "d. C."]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "fr", order: DateOrder::Dmy, sep: "/", months: Some(&MONTHS_FR), eras: [["avant Jésus-Christ", "après Jésus-Christ"], ["av. J.-C.", "ap. J.-C."], ["av. J.-C.", "ap. J.-C."]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "gv", order: DateOrder::Mdy, sep: "/", months: None, eras: [["BCE", "CE"], ["BCE", "CE"], ["BCE", "CE"]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "hi", order: DateOrder::Mdy, sep: "/", months: None, eras: [["BCE", "CE"], ["BCE", "CE"], ["BCE", "CE"]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "it", order: DateOrder::Dmy, sep: "/", months: Some(&MONTHS_IT), eras: [["avanti Cristo", "dopo Cristo"], ["a.C.", "d.C."], ["aC", "dC"]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "ja", order: DateOrder::Ymd, sep: "/", months: Some(&MONTHS_JA), eras: [["紀元前", "西暦"], ["紀元前", "西暦"], ["BC", "AD"]], h12: HourCycle::H11, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "ko", order: DateOrder::Ymd, sep: "/", months: Some(&MONTHS_KO), eras: [["기원전", "서기"], ["BC", "AD"], ["BC", "AD"]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "ln", order: DateOrder::Mdy, sep: "/", months: None, eras: [["BCE", "CE"], ["BCE", "CE"], ["BCE", "CE"]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "nl", order: DateOrder::Dmy, sep: "-", months: Some(&MONTHS_NL), eras: [["voor Christus", "na Christus"], ["v.Chr.", "n.Chr."], ["v.C.", "n.C."]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "pl", order: DateOrder::Dmy, sep: ".", months: None, eras: [["BCE", "CE"], ["BCE", "CE"], ["BCE", "CE"]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "pt", order: DateOrder::Dmy, sep: "/", months: Some(&MONTHS_PT), eras: [["antes de Cristo", "depois de Cristo"], ["a.C.", "d.C."], ["a.C.", "d.C."]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "ru", order: DateOrder::Dmy, sep: ".", months: Some(&MONTHS_RU), eras: [["до Рождества Христова", "от Рождества Христова"], ["до н. э.", "н. э."], ["до н.э.", "н.э."]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "si", order: DateOrder::Mdy, sep: "/", months: None, eras: [["BCE", "CE"], ["BCE", "CE"], ["BCE", "CE"]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "sl", order: DateOrder::Dmy, sep: ".", months: None, eras: [["BCE", "CE"], ["BCE", "CE"], ["BCE", "CE"]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "sr", order: DateOrder::Dmy, sep: ".", months: None, eras: [["BCE", "CE"], ["BCE", "CE"], ["BCE", "CE"]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "sv", order: DateOrder::Ymd, sep: "-", months: None, eras: [["BCE", "CE"], ["BCE", "CE"], ["BCE", "CE"]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "th", order: DateOrder::Dmy, sep: "/", months: None, eras: [["BCE", "CE"], ["BCE", "CE"], ["BCE", "CE"]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
    LocaleInfo { lang: "zh", order: DateOrder::Ymd, sep: "/", months: Some(&MONTHS_ZH), eras: [["公元前", "公元"], ["公元前", "公元"], ["公元前", "公元"]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" },
];

const MONTHS_ZH_HANT: [[&str; 12]; 3] = [
    ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"],
    ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"],
    ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"],
];
/// zh with region TW / HK / MO
const LOCALE_ZH_HANT: LocaleInfo = LocaleInfo { lang: "zh", order: DateOrder::Ymd, sep: "/", months: Some(&MONTHS_ZH_HANT), eras: [["西元前", "西元"], ["西元前", "西元"], ["西元前", "西元"]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" };
/// ar with a Maghreb region (latn digits)
const LOCALE_AR_LATN: LocaleInfo = LocaleInfo { lang: "ar", order: DateOrder::Dmy, sep: "/", months: Some(&MONTHS_AR), eras: [["قبل الميلاد", "ميلادي"], ["ق.م", "م"], ["ق.م", "م"]], h12: HourCycle::H12, default_hc: HourCycle::H23, default_nu: "latn" };

fn locale_info(lang: &str) -> Option<&'static LocaleInfo> {
    LOCALES.iter().find(|l| l.lang == lang)
}

/// Locale data for a language + optional region.
fn locale_info_for(lang: &str, region: Option<&str>) -> Option<&'static LocaleInfo> {
    match (lang, region) {
        ("zh", Some("TW" | "HK" | "MO")) => Some(&LOCALE_ZH_HANT),
        ("ar", Some("MA" | "DZ" | "TN" | "LY" | "EH" | "MR")) => Some(&LOCALE_AR_LATN),
        _ => locale_info(lang),
    }
}

/// Era names of the buddhist ([long, short, narrow]) and roc ([long, short,
/// narrow] x [Minguo, before]) calendars per locale.
const CALENDAR_ERAS: &[(&str, [&str; 3], [[&str; 2]; 3])] = &[
    ("en", ["BE", "BE", "BE"], [["Minguo", "B.R.O.C."], ["Minguo", "B.R.O.C."], ["Minguo", "B.R.O.C."]]),
    ("ar", ["التقويم البوذي", "BE", "BE"], [["جمهورية الصي", "BROC"], ["جمهورية الصي", "BROC"], ["جمهورية الصي", "BROC"]]),
    ("de", ["B.E.", "BE", "BE"], [["Minguo", "vor Volksrepublik China"], ["Minguo", "BROC"], ["Minguo", "v. VR China"]]),
    ("es", ["BE", "BE", "BE"], [["minguo", "antes de RDC"], ["minguo", "antes de RDC"], ["minguo", "antes de RDC"]]),
    ("fr", ["ère bouddhique", "E. B.", "EB"], [["RdC", "avant RdC"], ["RdC", "av. RdC"], ["RdC", "av. RdC"]]),
    ("gv", ["BE", "BE", "BE"], [["ROC", "BROC"], ["ROC", "BROC"], ["ROC", "BROC"]]),
    ("hi", ["BE", "BE", "BE"], [["ROC", "BROC"], ["ROC", "BROC"], ["ROC", "BROC"]]),
    ("it", ["EB", "EB", "EB"], [["Minguo", "Prima di R.O.C."], ["Minguo", "Prima di R.O.C."], ["Minguo", "Prima di R.O.C."]]),
    ("ja", ["仏暦", "BE", "BE"], [["民国", "民国前"], ["民国", "民国前"], ["民国", "民国前"]]),
    ("ko", ["불기", "불기", "불기"], [["중화민국", "중화민국전"], ["중화민국", "중화민국전"], ["중화민국", "중화민국전"]]),
    ("ln", ["BE", "BE", "BE"], [["ROC", "BROC"], ["ROC", "BROC"], ["ROC", "BROC"]]),
    ("nl", ["BE", "BE", "BE"], [["Minguo", "voor R.O.C."], ["Minguo", "voor R.O.C."], ["Minguo", "voor R.O.C."]]),
    ("pl", ["BE", "BE", "BE"], [["ROC", "BROC"], ["ROC", "BROC"], ["ROC", "BROC"]]),
    ("pt", ["EB", "BE", "EB"], [["Minguo", "Antes da R.C."], ["Minguo", "Antes da R.C."], ["Minguo", "Antes da R.C."]]),
    ("ru", ["буддийская эра", "BE", "бэ"], [["Миньго", "до основания Китайской республики"], ["Minguo", "BROC"], ["Миньго", "до респ."]]),
    ("si", ["BE", "BE", "BE"], [["ROC", "BROC"], ["ROC", "BROC"], ["ROC", "BROC"]]),
    ("sl", ["BE", "BE", "BE"], [["ROC", "BROC"], ["ROC", "BROC"], ["ROC", "BROC"]]),
    ("sr", ["BE", "BE", "BE"], [["ROC", "BROC"], ["ROC", "BROC"], ["ROC", "BROC"]]),
    ("sv", ["BE", "BE", "BE"], [["ROC", "BROC"], ["ROC", "BROC"], ["ROC", "BROC"]]),
    ("th", ["BE", "BE", "BE"], [["ROC", "BROC"], ["ROC", "BROC"], ["ROC", "BROC"]]),
    ("zh", ["佛历", "佛历", "佛历"], [["民国", "民国前"], ["民国", "民国前"], ["民国", "民国前"]]),
    ("zh-TW", ["佛曆", "佛曆", "佛曆"], [["民國", "民國前"], ["民國", "民國前"], ["民國", "民國前"]]),
];

/// Calendars whose formatting is implemented (others are formatted with the
/// Gregorian calendar).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum CalendarKind {
    Gregory,
    Buddhist,
    Roc,
    Japanese,
}

/// Japanese eras: (first day as days since epoch, first gregorian year, name).
/// Before 1873-01-01 the original uses the Gregorian AD/BC eras.
const JAPANESE_ERAS: [(i64, i64, &str); 5] = [
    (-35428, 1868, "Meiji"), // 1873-01-01 (shown as Meiji 6)
    (-20974, 1912, "Taish\u{14d}"), // 1912-07-30
    (-15713, 1926, "Sh\u{14d}wa"), // 1926-12-25
    (6947, 1989, "Heisei"),  // 1989-01-08
    (18017, 2019, "Reiwa"),  // 2019-05-01
];

fn calendar_kind(cal: &str) -> CalendarKind {
    match cal {
        "buddhist" => CalendarKind::Buddhist,
        "roc" => CalendarKind::Roc,
        "japanese" => CalendarKind::Japanese,
        _ => CalendarKind::Gregory,
    }
}

fn calendar_eras(info: &LocaleInfo) -> (&'static [&'static str; 3], &'static [[&'static str; 2]; 3]) {
    let key = if std::ptr::eq(info, &LOCALE_ZH_HANT) { "zh-TW" } else { info.lang };
    let row = CALENDAR_ERAS
        .iter()
        .find(|(l, _, _)| *l == key)
        .unwrap_or(&CALENDAR_ERAS[0]);
    (&row.1, &row.2)
}

const WEEKDAY_LONG: [&str; 7] = [
    "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
];

/// Decimal numbering systems supported by the original: (name, digits).
const NUMBERING_SYSTEMS: &[(&str, u32)] = &[
    ("adlm", 0x1E950), ("ahom", 0x11730), ("arab", 0x0660), ("arabext", 0x06F0),
    ("bali", 0x1B50), ("beng", 0x09E6), ("bhks", 0x11C50), ("brah", 0x11066),
    ("cakm", 0x11136), ("cham", 0xAA50), ("deva", 0x0966), ("diak", 0x11950),
    ("fullwide", 0xFF10), ("gara", 0x10D40), ("gong", 0x11DA0), ("gonm", 0x11D50),
    ("gujr", 0x0AE6), ("gukh", 0x16130), ("guru", 0x0A66), ("hanidec", 0),
    ("hmng", 0x16B50), ("hmnp", 0x1E140), ("java", 0xA9D0), ("kali", 0xA900),
    ("kawi", 0x11F50), ("khmr", 0x17E0), ("knda", 0x0CE6), ("krai", 0x16D70),
    ("lana", 0x1A80), ("lanatham", 0x1A90), ("laoo", 0x0ED0), ("latn", 0x30),
    ("lepc", 0x1C40), ("limb", 0x1946), ("mathbold", 0x1D7CE), ("mathdbl", 0x1D7D8),
    ("mathmono", 0x1D7F6), ("mathsanb", 0x1D7EC), ("mathsans", 0x1D7E2), ("mlym", 0x0D66),
    ("modi", 0x11650), ("mong", 0x1810), ("mroo", 0x16A60), ("mtei", 0xABF0),
    ("mymr", 0x1040), ("mymrepka", 0x116DA), ("mymrpao", 0x116D0), ("mymrshan", 0x1090),
    ("mymrtlng", 0xA9F0), ("nagm", 0x1E4F0), ("newa", 0x11450), ("nkoo", 0x07C0),
    ("olck", 0x1C50), ("onao", 0x1E5F1), ("orya", 0x0B66), ("osma", 0x104A0),
    ("outlined", 0x1CCF0), ("rohg", 0x10D30), ("saur", 0xA8D0), ("segment", 0x1FBF0),
    ("shrd", 0x111D0), ("sind", 0x112F0), ("sinh", 0x0DE6), ("sora", 0x110F0),
    ("sund", 0x1BB0), ("sunu", 0x11BF0), ("takr", 0x116C0), ("talu", 0x19D0),
    ("tamldec", 0x0BE6), ("telu", 0x0C66), ("thai", 0x0E50), ("tibt", 0x0F20),
    ("tirh", 0x114D0), ("tnsa", 0x16AC0), ("vaii", 0xA620), ("wara", 0x118E0),
    ("wcho", 0x1E2F0),
];

const HANIDEC_DIGITS: [char; 10] = ['〇', '一', '二', '三', '四', '五', '六', '七', '八', '九'];

fn numbering_system_supported(name: &str) -> bool {
    NUMBERING_SYSTEMS.iter().any(|(n, _)| *n == name)
}

/// Replace ASCII digits by the digits of numbering system `nu`.
fn transliterate_digits(s: &str, nu: &str) -> String {
    if nu == "latn" {
        return s.to_string();
    }
    let zero = match NUMBERING_SYSTEMS.iter().find(|(n, _)| *n == nu) {
        Some((_, z)) => *z,
        None => return s.to_string(),
    };
    s.chars()
        .map(|c| {
            if let Some(d) = c.to_digit(10).filter(|_| c.is_ascii_digit()) {
                if nu == "hanidec" {
                    HANIDEC_DIGITS[d as usize]
                } else {
                    char::from_u32(zero + d).unwrap_or(c)
                }
            } else {
                c
            }
        })
        .collect()
}

fn decimal_separator(nu: &str) -> &'static str {
    match nu {
        "arab" | "arabext" => "\u{066B}",
        _ => ".",
    }
}

/// English day periods as used by the original for every locale.
fn day_period_name(hour: u32, style: TextStyle) -> &'static str {
    match hour {
        0..=11 => "in the morning",
        12 => {
            if style == TextStyle::Narrow {
                "n"
            } else {
                "noon"
            }
        }
        13..=17 => "in the afternoon",
        18..=20 => "in the evening",
        _ => "at night",
    }
}

// ---------------------------------------------------------------------------
// Options
// ---------------------------------------------------------------------------

/// weekday / era / dayPeriod widths.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TextStyle {
    Narrow,
    Short,
    Long,
}

/// "numeric" / "2-digit"
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NumericStyle {
    Numeric,
    TwoDigit,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MonthStyle {
    Numeric,
    TwoDigit,
    Narrow,
    Short,
    Long,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HourCycle {
    H11,
    H12,
    H23,
    H24,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TimeZoneNameStyle {
    Short,
    Long,
    ShortOffset,
    LongOffset,
    ShortGeneric,
    LongGeneric,
}

/// dateStyle / timeStyle values.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FormatStyle {
    Full,
    Long,
    Medium,
    Short,
}

impl TextStyle {
    pub fn as_str(self) -> &'static str {
        match self {
            TextStyle::Narrow => "narrow",
            TextStyle::Short => "short",
            TextStyle::Long => "long",
        }
    }
    fn parse(v: &str) -> Option<Self> {
        Some(match v {
            "narrow" => TextStyle::Narrow,
            "short" => TextStyle::Short,
            "long" => TextStyle::Long,
            _ => return None,
        })
    }
    fn index(self) -> usize {
        match self {
            TextStyle::Long => 0,
            TextStyle::Short => 1,
            TextStyle::Narrow => 2,
        }
    }
}

impl NumericStyle {
    pub fn as_str(self) -> &'static str {
        match self {
            NumericStyle::Numeric => "numeric",
            NumericStyle::TwoDigit => "2-digit",
        }
    }
    fn parse(v: &str) -> Option<Self> {
        Some(match v {
            "numeric" => NumericStyle::Numeric,
            "2-digit" => NumericStyle::TwoDigit,
            _ => return None,
        })
    }
}

impl MonthStyle {
    pub fn as_str(self) -> &'static str {
        match self {
            MonthStyle::Numeric => "numeric",
            MonthStyle::TwoDigit => "2-digit",
            MonthStyle::Narrow => "narrow",
            MonthStyle::Short => "short",
            MonthStyle::Long => "long",
        }
    }
    fn parse(v: &str) -> Option<Self> {
        Some(match v {
            "numeric" => MonthStyle::Numeric,
            "2-digit" => MonthStyle::TwoDigit,
            "narrow" => MonthStyle::Narrow,
            "short" => MonthStyle::Short,
            "long" => MonthStyle::Long,
            _ => return None,
        })
    }
}

impl HourCycle {
    pub fn as_str(self) -> &'static str {
        match self {
            HourCycle::H11 => "h11",
            HourCycle::H12 => "h12",
            HourCycle::H23 => "h23",
            HourCycle::H24 => "h24",
        }
    }
    fn parse(v: &str) -> Option<Self> {
        Some(match v {
            "h11" => HourCycle::H11,
            "h12" => HourCycle::H12,
            "h23" => HourCycle::H23,
            "h24" => HourCycle::H24,
            _ => return None,
        })
    }
    fn is_12(self) -> bool {
        matches!(self, HourCycle::H11 | HourCycle::H12)
    }
}

impl TimeZoneNameStyle {
    pub fn as_str(self) -> &'static str {
        match self {
            TimeZoneNameStyle::Short => "short",
            TimeZoneNameStyle::Long => "long",
            TimeZoneNameStyle::ShortOffset => "shortOffset",
            TimeZoneNameStyle::LongOffset => "longOffset",
            TimeZoneNameStyle::ShortGeneric => "shortGeneric",
            TimeZoneNameStyle::LongGeneric => "longGeneric",
        }
    }
    fn parse(v: &str) -> Option<Self> {
        Some(match v {
            "short" => TimeZoneNameStyle::Short,
            "long" => TimeZoneNameStyle::Long,
            "shortOffset" => TimeZoneNameStyle::ShortOffset,
            "longOffset" => TimeZoneNameStyle::LongOffset,
            "shortGeneric" => TimeZoneNameStyle::ShortGeneric,
            "longGeneric" => TimeZoneNameStyle::LongGeneric,
            _ => return None,
        })
    }
    fn is_long(self) -> bool {
        matches!(
            self,
            TimeZoneNameStyle::Long | TimeZoneNameStyle::LongOffset | TimeZoneNameStyle::LongGeneric
        )
    }
}

impl FormatStyle {
    pub fn as_str(self) -> &'static str {
        match self {
            FormatStyle::Full => "full",
            FormatStyle::Long => "long",
            FormatStyle::Medium => "medium",
            FormatStyle::Short => "short",
        }
    }
    fn parse(v: &str) -> Option<Self> {
        Some(match v {
            "full" => FormatStyle::Full,
            "long" => FormatStyle::Long,
            "medium" => FormatStyle::Medium,
            "short" => FormatStyle::Short,
            _ => return None,
        })
    }
}

/// Options bag of Intl.DateTimeFormat / Date.prototype.toLocale*String.
///
/// The JS layer should read the properties of the options object (in the
/// order listed in the module docs), convert string-valued ones with
/// ToString and feed them to [`DateTimeFormatOptions::set`] (which validates
/// them with the original's error messages), use
/// [`DateTimeFormatOptions::set_fractional_second_digits`] for the numeric
/// option and ToBoolean for `hour12`.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct DateTimeFormatOptions {
    pub locale_matcher: Option<String>,
    /// already lower-cased
    pub calendar: Option<String>,
    pub numbering_system: Option<String>,
    pub hour12: Option<bool>,
    pub hour_cycle: Option<HourCycle>,
    /// canonical time-zone identifier (validated by `set`)
    pub time_zone: Option<String>,
    pub weekday: Option<TextStyle>,
    pub era: Option<TextStyle>,
    pub year: Option<NumericStyle>,
    pub month: Option<MonthStyle>,
    pub day: Option<NumericStyle>,
    pub day_period: Option<TextStyle>,
    pub hour: Option<NumericStyle>,
    pub minute: Option<NumericStyle>,
    pub second: Option<NumericStyle>,
    pub fractional_second_digits: Option<u8>,
    pub time_zone_name: Option<TimeZoneNameStyle>,
    pub format_matcher: Option<String>,
    pub date_style: Option<FormatStyle>,
    pub time_style: Option<FormatStyle>,
}

/// `type` production of UTS 35: (3*8alphanum) *("-" (3*8alphanum))
fn is_unicode_type(v: &str) -> bool {
    !v.is_empty()
        && v
            .split('-')
            .all(|p| (3..=8).contains(&p.len()) && p.bytes().all(|b| b.is_ascii_alphanumeric()))
}

impl DateTimeFormatOptions {
    pub fn new() -> Self {
        Self::default()
    }

    /// Set a string-valued option from its JS property name and its
    /// ToString'ed value.  Returns the original's RangeError for invalid
    /// values (e.g. "invalid month: foo", "invalid time zone: Bad/Zone").
    /// `hour12` must go through [`Self::set_hour12`] (ToBoolean); unknown
    /// property names are ignored.
    pub fn set(&mut self, name: &str, value: &str) -> Result<(), DateTimeError> {
        let bad = || DateTimeError::range(format!("invalid {}: {}", name, value));
        match name {
            "localeMatcher" => {
                if value != "lookup" && value != "best fit" {
                    return Err(bad());
                }
                self.locale_matcher = Some(value.to_string());
            }
            "formatMatcher" => {
                if value != "basic" && value != "best fit" {
                    return Err(bad());
                }
                self.format_matcher = Some(value.to_string());
            }
            "calendar" => {
                if !is_unicode_type(value) {
                    return Err(bad());
                }
                self.calendar = Some(value.to_ascii_lowercase());
            }
            "numberingSystem" => {
                if !is_unicode_type(value) {
                    return Err(bad());
                }
                self.numbering_system = Some(value.to_string());
            }
            "hourCycle" => self.hour_cycle = Some(HourCycle::parse(value).ok_or_else(bad)?),
            "fractionalSecondDigits" => {
                let n = value.trim().parse::<f64>().unwrap_or(f64::NAN);
                self.set_fractional_second_digits(n)?;
            }
            "timeZone" => {
                let tz = TimeZone::from_name(value).ok_or_else(|| {
                    DateTimeError::range(format!("invalid time zone: {}", value))
                })?;
                self.time_zone = Some(tz.id());
            }
            "weekday" => self.weekday = Some(TextStyle::parse(value).ok_or_else(bad)?),
            "era" => self.era = Some(TextStyle::parse(value).ok_or_else(bad)?),
            "year" => self.year = Some(NumericStyle::parse(value).ok_or_else(bad)?),
            "month" => self.month = Some(MonthStyle::parse(value).ok_or_else(bad)?),
            "day" => self.day = Some(NumericStyle::parse(value).ok_or_else(bad)?),
            "dayPeriod" => self.day_period = Some(TextStyle::parse(value).ok_or_else(bad)?),
            "hour" => self.hour = Some(NumericStyle::parse(value).ok_or_else(bad)?),
            "minute" => self.minute = Some(NumericStyle::parse(value).ok_or_else(bad)?),
            "second" => self.second = Some(NumericStyle::parse(value).ok_or_else(bad)?),
            "timeZoneName" => {
                self.time_zone_name = Some(TimeZoneNameStyle::parse(value).ok_or_else(bad)?)
            }
            "dateStyle" => self.date_style = Some(FormatStyle::parse(value).ok_or_else(bad)?),
            "timeStyle" => self.time_style = Some(FormatStyle::parse(value).ok_or_else(bad)?),
            _ => {}
        }
        Ok(())
    }

    /// `hour12` (the caller applies ToBoolean).
    pub fn set_hour12(&mut self, value: bool) {
        self.hour12 = Some(value);
    }

    /// `fractionalSecondDigits` after ToNumber: must be in 1..=3 (floored),
    /// else `RangeError: fractionalSecondDigits out of range`.
    pub fn set_fractional_second_digits(&mut self, value: f64) -> Result<(), DateTimeError> {
        if !(value >= 1.0 && value < 4.0) {
            return Err(DateTimeError::range(
                "fractionalSecondDigits out of range".to_string(),
            ));
        }
        self.fractional_second_digits = Some(value.floor() as u8);
        Ok(())
    }

    fn has_explicit_components(&self) -> bool {
        self.weekday.is_some()
            || self.era.is_some()
            || self.year.is_some()
            || self.month.is_some()
            || self.day.is_some()
            || self.day_period.is_some()
            || self.hour.is_some()
            || self.minute.is_some()
            || self.second.is_some()
            || self.fractional_second_digits.is_some()
            || self.time_zone_name.is_some()
    }
}

/// Which components ToDateTimeOptions checks ("required").
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RequiredComponents {
    Any,
    Date,
    Time,
}

/// Which components ToDateTimeOptions adds when none is present ("defaults").
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DefaultComponents {
    Date,
    Time,
    All,
}

/// One element of formatToParts().
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DateTimePart {
    /// "weekday", "era", "year", "month", "day", "dayPeriod", "hour",
    /// "minute", "second", "fractionalSecond", "timeZoneName" or "literal"
    pub kind: &'static str,
    pub value: String,
}

/// A resolved date-time formatter (Intl.DateTimeFormat instance state).
#[derive(Clone, Debug)]
pub struct DateTimeFormat {
    locale: String,
    info: &'static LocaleInfo,
    calendar: String,
    numbering_system: String,
    time_zone: TimeZone,
    hour_cycle: Option<HourCycle>,
    hour_cycle_label: Option<String>,
    weekday: Option<TextStyle>,
    era: Option<TextStyle>,
    year: Option<NumericStyle>,
    month: Option<MonthStyle>,
    day: Option<NumericStyle>,
    day_period: Option<TextStyle>,
    hour: Option<NumericStyle>,
    minute: Option<NumericStyle>,
    second: Option<NumericStyle>,
    fractional_second_digits: Option<u8>,
    time_zone_name: Option<TimeZoneNameStyle>,
    date_style: Option<FormatStyle>,
    time_style: Option<FormatStyle>,
}

impl std::fmt::Debug for LocaleInfo {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "LocaleInfo({})", self.lang)
    }
}

/// A value of resolvedOptions().
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ResolvedValue {
    Str(String),
    Bool(bool),
    Number(u8),
}

const CALENDARS: &[&str] = &[
    "buddhist", "chinese", "coptic", "dangi", "ethioaa", "ethiopic", "gregory", "hebrew",
    "indian", "islamic-civil", "islamic-tbla", "islamic-umalqura", "iso8601", "japanese",
    "persian", "roc",
];

fn canonical_calendar(c: &str) -> Option<&'static str> {
    let c = match c {
        "islamicc" | "islamic" | "islamic-rgsa" => "islamic-civil",
        "ethiopic-amete-alem" => "ethioaa",
        "gregorian" => "gregory",
        other => other,
    };
    CALENDARS.iter().copied().find(|x| *x == c)
}

impl DateTimeFormat {
    /// `new Intl.DateTimeFormat(locales, options)` (required "any",
    /// defaults "date").
    pub fn new(locales: &[String], options: &DateTimeFormatOptions) -> Result<Self, DateTimeError> {
        Self::with_defaults(locales, options, RequiredComponents::Any, DefaultComponents::Date)
    }

    /// Construct with explicit ToDateTimeOptions behaviour
    /// (toLocaleString: Any/All, toLocaleDateString: Date/Date,
    /// toLocaleTimeString: Time/Time).
    pub fn with_defaults(
        locales: &[String],
        options: &DateTimeFormatOptions,
        required: RequiredComponents,
        defaults: DefaultComponents,
    ) -> Result<Self, DateTimeError> {
        let mut tags = Vec::new();
        for l in locales {
            tags.push(parse_language_tag(l).ok_or_else(|| {
                DateTimeError::range(format!("Incorrect locale information provided: {}", l))
            })?);
        }
        // Locale negotiation: first tag whose language has data, else "en".
        let chosen = tags.into_iter().find(|t| locale_info(&t.language).is_some());
        let (base, tag) = match &chosen {
            Some(t) => (t.base_name(), Some(t)),
            None => ("en".to_string(), None),
        };
        let info = match tag {
            Some(t) => locale_info_for(&t.language, t.region.as_deref()),
            None => None,
        }
        .unwrap_or(&LOCALES[0]);

        // -u- keywords that are supported
        let ext_ca = tag
            .and_then(|t| t.keyword("ca"))
            .and_then(canonical_calendar);
        let ext_nu = tag
            .and_then(|t| t.keyword("nu"))
            .filter(|n| numbering_system_supported(n))
            .map(|s| s.to_string());
        let ext_hc_raw = tag.and_then(|t| t.keyword("hc"));
        let ext_hc = ext_hc_raw.and_then(HourCycle::parse);
        // the original keeps an unknown -u-hc- value verbatim (reported by
        // resolvedOptions, formatted like h23)
        let mut hc_label: Option<String> = None;

        let mut keep_ca = ext_ca;
        let mut calendar = ext_ca.unwrap_or("gregory").to_string();
        if let Some(c) = options.calendar.as_deref().and_then(canonical_calendar) {
            if Some(c) != ext_ca {
                keep_ca = None;
            }
            calendar = c.to_string();
        }
        let mut keep_nu = ext_nu.clone();
        let mut numbering_system = ext_nu.clone().unwrap_or_else(|| info.default_nu.to_string());
        if let Some(n) = options
            .numbering_system
            .as_deref()
            .filter(|n| numbering_system_supported(n))
        {
            if Some(n) != ext_nu.as_deref() {
                keep_nu = None;
            }
            numbering_system = n.to_string();
        }
        // hour cycle
        let mut keep_hc = ext_hc;
        let hc = if let Some(h12) = options.hour12 {
            keep_hc = None;
            if h12 {
                info.h12
            } else {
                HourCycle::H23
            }
        } else if let Some(h) = options.hour_cycle {
            if Some(h) != ext_hc {
                keep_hc = None;
            }
            h
        } else if let (Some(raw), None) = (ext_hc_raw, ext_hc) {
            hc_label = Some(raw.to_string());
            HourCycle::H23
        } else {
            ext_hc.unwrap_or(info.default_hc)
        };

        let mut locale = base;
        if keep_ca.is_some() || keep_hc.is_some() || keep_nu.is_some() {
            locale.push_str("-u");
            if let Some(c) = keep_ca {
                locale.push_str("-ca-");
                locale.push_str(c);
            }
            if let Some(h) = keep_hc {
                locale.push_str("-hc-");
                locale.push_str(h.as_str());
            }
            if let Some(n) = &keep_nu {
                locale.push_str("-nu-");
                locale.push_str(n);
            }
        }

        let time_zone = match &options.time_zone {
            Some(z) => TimeZone::from_name(z)
                .ok_or_else(|| DateTimeError::range(format!("invalid time zone: {}", z)))?,
            None => TimeZone::Utc,
        };

        let mut f = DateTimeFormat {
            locale,
            info,
            calendar,
            numbering_system,
            time_zone,
            hour_cycle: None,
            hour_cycle_label: hc_label,
            weekday: options.weekday,
            era: options.era,
            year: options.year,
            month: options.month,
            day: options.day,
            day_period: options.day_period,
            hour: options.hour,
            minute: options.minute,
            second: options.second,
            fractional_second_digits: options.fractional_second_digits,
            time_zone_name: options.time_zone_name,
            date_style: options.date_style,
            time_style: options.time_style,
        };

        if f.date_style.is_some() || f.time_style.is_some() {
            if options.has_explicit_components() {
                return Err(DateTimeError::type_error(
                    "dateStyle/timeStyle cannot be combined with explicit date-time components",
                ));
            }
        } else {
            let mut need_defaults = true;
            if matches!(required, RequiredComponents::Date | RequiredComponents::Any)
                && (f.weekday.is_some() || f.year.is_some() || f.month.is_some() || f.day.is_some())
            {
                need_defaults = false;
            }
            if matches!(required, RequiredComponents::Time | RequiredComponents::Any)
                && (f.day_period.is_some()
                    || f.hour.is_some()
                    || f.minute.is_some()
                    || f.second.is_some()
                    || f.fractional_second_digits.is_some())
            {
                need_defaults = false;
            }
            if need_defaults && matches!(defaults, DefaultComponents::Date | DefaultComponents::All) {
                f.year = Some(NumericStyle::Numeric);
                f.month = Some(MonthStyle::Numeric);
                f.day = Some(NumericStyle::Numeric);
            }
            if need_defaults && matches!(defaults, DefaultComponents::Time | DefaultComponents::All) {
                f.hour = Some(NumericStyle::Numeric);
                f.minute = Some(NumericStyle::Numeric);
                f.second = Some(NumericStyle::Numeric);
            }
        }
        if f.hour.is_some() || f.time_style.is_some() {
            f.hour_cycle = Some(hc);
        }
        Ok(f)
    }

    /// The resolved locale (resolvedOptions().locale).
    pub fn locale(&self) -> &str {
        &self.locale
    }

    /// resolvedOptions() as an ordered list of (property, value).
    pub fn resolved_options(&self) -> Vec<(&'static str, ResolvedValue)> {
        use ResolvedValue::*;
        let mut v = vec![
            ("locale", Str(self.locale.clone())),
            ("calendar", Str(self.calendar.clone())),
            ("numberingSystem", Str(self.numbering_system.clone())),
            ("timeZone", Str(self.time_zone.id())),
        ];
        if let Some(hc) = self.hour_cycle {
            let label = self.hour_cycle_label.clone().unwrap_or_else(|| hc.as_str().to_string());
            v.push(("hourCycle", Str(label)));
            v.push(("hour12", Bool(hc.is_12())));
        }
        let s = |x: &'static str| Str(x.to_string());
        if let Some(x) = self.weekday {
            v.push(("weekday", s(x.as_str())));
        }
        if let Some(x) = self.era {
            v.push(("era", s(x.as_str())));
        }
        if let Some(x) = self.year {
            v.push(("year", s(x.as_str())));
        }
        if let Some(x) = self.month {
            v.push(("month", s(x.as_str())));
        }
        if let Some(x) = self.day {
            v.push(("day", s(x.as_str())));
        }
        if let Some(x) = self.day_period {
            v.push(("dayPeriod", s(x.as_str())));
        }
        if let Some(x) = self.hour {
            v.push(("hour", s(x.as_str())));
        }
        if let Some(x) = self.minute {
            v.push(("minute", s(x.as_str())));
        }
        if let Some(x) = self.second {
            v.push(("second", s(x.as_str())));
        }
        if let Some(x) = self.fractional_second_digits {
            v.push(("fractionalSecondDigits", Number(x)));
        }
        if let Some(x) = self.time_zone_name {
            v.push(("timeZoneName", s(x.as_str())));
        }
        if let Some(x) = self.date_style {
            v.push(("dateStyle", s(x.as_str())));
        }
        if let Some(x) = self.time_style {
            v.push(("timeStyle", s(x.as_str())));
        }
        v
    }

    /// Intl.DateTimeFormat.prototype.format: `RangeError: Invalid time
    /// value` for non-finite / out-of-range time values.
    pub fn format(&self, t: f64) -> Result<String, DateTimeError> {
        Ok(self
            .format_to_parts(t)?
            .into_iter()
            .map(|p| p.value)
            .collect())
    }

    /// Intl.DateTimeFormat.prototype.formatToParts.
    pub fn format_to_parts(&self, t: f64) -> Result<Vec<DateTimePart>, DateTimeError> {
        let t = time_clip(t);
        if t.is_nan() {
            return Err(DateTimeError::range("Invalid time value".to_string()));
        }
        Ok(self.parts(t))
    }

    fn effective_components(&self) -> Components {
        let mut c = Components {
            weekday: self.weekday,
            era: self.era,
            year: self.year,
            month: self.month,
            day: self.day,
            day_period: self.day_period,
            hour: self.hour,
            minute: self.minute,
            second: self.second,
            fsd: self.fractional_second_digits,
            tz_name: self.time_zone_name,
        };
        if let Some(ds) = self.date_style {
            match ds {
                FormatStyle::Full => {
                    c.weekday = Some(TextStyle::Long);
                    c.month = Some(MonthStyle::Long);
                    c.day = Some(NumericStyle::Numeric);
                    c.year = Some(NumericStyle::Numeric);
                }
                FormatStyle::Long => {
                    c.month = Some(MonthStyle::Long);
                    c.day = Some(NumericStyle::Numeric);
                    c.year = Some(NumericStyle::Numeric);
                }
                FormatStyle::Medium => {
                    c.month = Some(MonthStyle::Short);
                    c.day = Some(NumericStyle::Numeric);
                    c.year = Some(NumericStyle::Numeric);
                }
                FormatStyle::Short => {
                    c.month = Some(MonthStyle::Numeric);
                    c.day = Some(NumericStyle::Numeric);
                    c.year = Some(NumericStyle::TwoDigit);
                }
            }
        }
        if let Some(ts) = self.time_style {
            c.hour = Some(NumericStyle::Numeric);
            c.minute = Some(NumericStyle::TwoDigit);
            match ts {
                FormatStyle::Full => {
                    c.second = Some(NumericStyle::TwoDigit);
                    c.tz_name = Some(TimeZoneNameStyle::Long);
                }
                FormatStyle::Long => {
                    c.second = Some(NumericStyle::TwoDigit);
                    c.tz_name = Some(TimeZoneNameStyle::Short);
                }
                FormatStyle::Medium => c.second = Some(NumericStyle::TwoDigit),
                FormatStyle::Short => {}
            }
        }
        c
    }

    /// Displayed year and (if requested) era name for the calendar.
    fn year_and_era(&self, f: &Fields, era: Option<TextStyle>) -> (i64, Option<&'static str>) {
        let info = self.info;
        let gregorian = |convert: bool| {
            let ad = f.year > 0;
            let y = if convert && !ad { 1 - f.year } else { f.year };
            (y, era.map(|e| info.eras[e.index()][ad as usize]))
        };
        match calendar_kind(&self.calendar) {
            CalendarKind::Gregory => gregorian(era.is_some()),
            CalendarKind::Buddhist => {
                let (b, _) = calendar_eras(info);
                (f.year + 543, era.map(|e| b[e.index()]))
            }
            CalendarKind::Roc => {
                let (_, r) = calendar_eras(info);
                let y = f.year - 1911;
                (y, era.map(|e| r[e.index()][if y >= 1 { 0 } else { 1 }]))
            }
            CalendarKind::Japanese => {
                let days = days_from_civil(f.year, f.month + 1, f.day as i64);
                match JAPANESE_ERAS.iter().rev().find(|(start, _, _)| days >= *start) {
                    Some((_, first, name)) => (f.year - first + 1, era.map(|_| *name)),
                    None => gregorian(true),
                }
            }
        }
    }

    fn parts(&self, t: f64) -> Vec<DateTimePart> {
        let c = self.effective_components();
        let info = self.info;
        let offset_ms = self.time_zone.offset_ms(t);
        let f = fields(t + offset_ms);
        let mut out: Vec<DateTimePart> = Vec::new();
        let push = |out: &mut Vec<DateTimePart>, kind: &'static str, value: String| {
            out.push(DateTimePart { kind, value });
        };
        let lit = |out: &mut Vec<DateTimePart>, s: &str| {
            out.push(DateTimePart { kind: "literal", value: s.to_string() });
        };

        // ---- date ----
        if let Some(w) = c.weekday {
            let name = match w {
                TextStyle::Long => WEEKDAY_LONG[f.weekday as usize],
                _ => WEEKDAY_SHORT[f.weekday as usize],
            };
            push(&mut out, "weekday", name.to_string());
            lit(&mut out, ", ");
        }
        let (year_value, era_name) = self.year_and_era(&f, c.era);
        let year_str = |style: NumericStyle| match style {
            NumericStyle::Numeric => year_value.to_string(),
            NumericStyle::TwoDigit => format!("{:02}", year_value.rem_euclid(100)),
        };
        let day_str = |style: NumericStyle| match style {
            NumericStyle::Numeric => f.day.to_string(),
            NumericStyle::TwoDigit => format!("{:02}", f.day),
        };
        let textual = matches!(
            c.month,
            Some(MonthStyle::Narrow | MonthStyle::Short | MonthStyle::Long)
        ) && info.months.is_some();
        let body_start = out.len();
        if textual {
            let months = info.months.unwrap();
            let idx = match c.month.unwrap() {
                MonthStyle::Long => 0,
                MonthStyle::Short => 1,
                _ => 2,
            };
            push(&mut out, "month", months[idx][f.month as usize].to_string());
            if let Some(d) = c.day {
                lit(&mut out, " ");
                push(&mut out, "day", day_str(d));
            }
            if let Some(y) = c.year {
                lit(&mut out, ", ");
                push(&mut out, "year", year_str(y));
            }
        } else {
            let order: [char; 3] = match info.order {
                DateOrder::Mdy => ['m', 'd', 'y'],
                DateOrder::Dmy => ['d', 'm', 'y'],
                DateOrder::Ymd => ['y', 'm', 'd'],
            };
            let mut first = true;
            for k in order {
                let item = match k {
                    'y' => c.year.map(|y| ("year", year_str(y))),
                    'm' => c.month.map(|m| {
                        (
                            "month",
                            if m == MonthStyle::TwoDigit {
                                format!("{:02}", f.month + 1)
                            } else {
                                (f.month + 1).to_string()
                            },
                        )
                    }),
                    _ => c.day.map(|d| ("day", day_str(d))),
                };
                if let Some((kind, v)) = item {
                    if !first {
                        lit(&mut out, info.sep);
                    }
                    first = false;
                    push(&mut out, kind, v);
                }
            }
        }
        let has_body = out.len() > body_start;
        if let (Some(e), true) = (era_name, has_body) {
            lit(&mut out, " ");
            push(&mut out, "era", e.to_string());
        }

        // ---- time ----
        let mut time: Vec<DateTimePart> = Vec::new();
        let hc = self.hour_cycle.unwrap_or(info.default_hc);
        if let Some(hs) = c.hour {
            let h = f.hour;
            let hv = match hc {
                HourCycle::H11 => h % 12,
                HourCycle::H12 => {
                    if h % 12 == 0 {
                        12
                    } else {
                        h % 12
                    }
                }
                HourCycle::H23 => h,
                HourCycle::H24 => {
                    if h == 0 {
                        24
                    } else {
                        h
                    }
                }
            };
            let pad = hs == NumericStyle::TwoDigit || (!hc.is_12() && c.day_period.is_none());
            push(&mut time, "hour", if pad { format!("{:02}", hv) } else { hv.to_string() });
        }
        if c.minute.is_some() {
            if !time.is_empty() {
                lit(&mut time, ":");
            }
            push(&mut time, "minute", format!("{:02}", f.minute));
        }
        if c.second.is_some() {
            if !time.is_empty() {
                lit(&mut time, ":");
            }
            push(&mut time, "second", format!("{:02}", f.second));
        }
        let has_hms = !time.is_empty();
        if let Some(n) = c.fsd {
            if c.second.is_some() {
                lit(&mut time, decimal_separator(&self.numbering_system));
            }
            let ms = format!("{:03}", f.millisecond);
            push(&mut time, "fractionalSecond", ms[..n.clamp(1, 3) as usize].to_string());
        }
        if c.hour.is_some() && hc.is_12() {
            lit(&mut time, " ");
            let v = match c.day_period {
                Some(dp) => day_period_name(f.hour, dp).to_string(),
                None => (if f.hour < 12 { "AM" } else { "PM" }).to_string(),
            };
            push(&mut time, "dayPeriod", v);
        } else if let Some(dp) = c.day_period {
            if has_hms {
                lit(&mut time, " ");
            }
            push(&mut time, "dayPeriod", day_period_name(f.hour, dp).to_string());
        }
        if has_body && !time.is_empty() {
            lit(&mut out, ", ");
        }
        out.extend(time);

        // ---- time zone name ----
        if let Some(style) = c.tz_name {
            lit(&mut out, " ");
            push(&mut out, "timeZoneName", self.time_zone.display_name(style));
        }

        if self.numbering_system != "latn" {
            for p in &mut out {
                p.value = transliterate_digits(&p.value, &self.numbering_system);
            }
        }
        out
    }
}

#[derive(Clone, Copy)]
struct Components {
    weekday: Option<TextStyle>,
    era: Option<TextStyle>,
    year: Option<NumericStyle>,
    month: Option<MonthStyle>,
    day: Option<NumericStyle>,
    day_period: Option<TextStyle>,
    hour: Option<NumericStyle>,
    minute: Option<NumericStyle>,
    second: Option<NumericStyle>,
    fsd: Option<u8>,
    tz_name: Option<TimeZoneNameStyle>,
}

fn to_locale_impl(
    t: f64,
    locales: &[String],
    options: &DateTimeFormatOptions,
    required: RequiredComponents,
    defaults: DefaultComponents,
) -> Result<String, DateTimeError> {
    if time_clip(t).is_nan() {
        return Ok("Invalid Date".to_string());
    }
    let f = DateTimeFormat::with_defaults(locales, options, required, defaults)?;
    f.format(t)
}

/// Date.prototype.toLocaleString(locales, options).  NaN gives
/// "Invalid Date" without looking at locales/options (like the original,
/// which does not even read the options then).  Default output:
/// "1/1/1970, 12:00:00 AM".
pub fn to_locale_string(
    t: f64,
    locales: &[String],
    options: &DateTimeFormatOptions,
) -> Result<String, DateTimeError> {
    to_locale_impl(t, locales, options, RequiredComponents::Any, DefaultComponents::All)
}

/// Date.prototype.toLocaleDateString: default "1/1/1970".
pub fn to_locale_date_string(
    t: f64,
    locales: &[String],
    options: &DateTimeFormatOptions,
) -> Result<String, DateTimeError> {
    to_locale_impl(t, locales, options, RequiredComponents::Date, DefaultComponents::Date)
}

/// Date.prototype.toLocaleTimeString: default "12:00:00 AM".
pub fn to_locale_time_string(
    t: f64,
    locales: &[String],
    options: &DateTimeFormatOptions,
) -> Result<String, DateTimeError> {
    to_locale_impl(t, locales, options, RequiredComponents::Time, DefaultComponents::Time)
}

// ---------------------------------------------------------------------------
// Time zones
// ---------------------------------------------------------------------------

/// A resolved time zone.
#[derive(Clone, Debug, PartialEq)]
pub enum TimeZone {
    /// "UTC" (any case)
    Utc,
    /// "+HH:MM" style offset, in minutes
    Fixed(i32),
    /// IANA zone loaded from the system tz database
    Named(std::sync::Arc<NamedZone>),
}

/// An IANA time zone: UTC offsets as a step function of time.
#[derive(Debug)]
pub struct NamedZone {
    /// identifier as resolved (canonical case, links keep their own name)
    id: String,
    /// transition instants (seconds since the epoch), ascending
    times: Vec<i64>,
    /// UTC offset (seconds) in effect from `times[i]`
    offsets: Vec<i32>,
    /// offset before the first transition
    initial: i32,
}

impl PartialEq for NamedZone {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id
    }
}

impl NamedZone {
    /// UTC offset in seconds at `secs` (seconds since the epoch).  Like the
    /// original, no DST is extrapolated past the last transition (fat TZif
    /// data ends in 2037).
    fn offset_at(&self, secs: i64) -> i32 {
        match self.times.binary_search(&secs) {
            Ok(i) => self.offsets[i],
            Err(0) => self.initial,
            Err(i) => self.offsets[i - 1],
        }
    }
}

impl TimeZone {
    /// Resolve a timeZone option value (case-insensitive IANA name or
    /// offset string).  None = `RangeError: invalid time zone: <name>`.
    pub fn from_name(name: &str) -> Option<TimeZone> {
        if name.eq_ignore_ascii_case("utc") {
            return Some(TimeZone::Utc);
        }
        if let Some(m) = parse_offset_time_zone(name) {
            return Some(TimeZone::Fixed(m));
        }
        load_named_zone(name).map(TimeZone::Named)
    }

    /// Canonical identifier (resolvedOptions().timeZone).
    pub fn id(&self) -> String {
        match self {
            TimeZone::Utc => "UTC".to_string(),
            TimeZone::Fixed(m) => {
                let sign = if *m < 0 { '-' } else { '+' };
                format!("{}{:02}:{:02}", sign, m.abs() / 60, m.abs() % 60)
            }
            TimeZone::Named(z) => z.id.clone(),
        }
    }

    /// Offset from UTC in ms at UTC time `t` (ms).
    pub fn offset_ms(&self, t: f64) -> f64 {
        match self {
            TimeZone::Utc => 0.0,
            TimeZone::Fixed(m) => *m as f64 * MS_PER_MINUTE,
            TimeZone::Named(z) => {
                let secs = (t / 1000.0).floor();
                let secs = if secs.is_finite() { secs as i64 } else { 0 };
                z.offset_at(secs) as f64 * 1000.0
            }
        }
    }

    fn display_name(&self, style: TimeZoneNameStyle) -> String {
        match self {
            TimeZone::Utc => match style {
                TimeZoneNameStyle::Long | TimeZoneNameStyle::LongGeneric => {
                    "Coordinated Universal Time".to_string()
                }
                TimeZoneNameStyle::LongOffset => "GMT".to_string(),
                _ => "UTC".to_string(),
            },
            TimeZone::Fixed(m) => {
                if *m == 0 {
                    "GMT".to_string()
                } else {
                    gmt_offset_name(*m as i64 * 60)
                }
            }
            TimeZone::Named(z) => {
                if style.is_long() {
                    tz_long_name(&z.id).to_string()
                } else {
                    // The original always shows the offset in effect at the
                    // epoch (1970-01-01T00:00Z), not at the formatted date.
                    gmt_offset_name(z.offset_at(0) as i64)
                }
            }
        }
    }
}

fn tz_long_name(id: &str) -> &str {
    for (long, ids) in TZ_LONG_NAMES {
        if ids.contains(&id) {
            return long;
        }
    }
    id
}

const ZONEINFO_DIR: &str = "/usr/share/zoneinfo";

/// Case-insensitive index of zone names -> (canonical name, link target).
struct ZoneIndex {
    names: std::collections::HashMap<String, (String, Option<String>)>,
}

fn zone_index() -> &'static ZoneIndex {
    static INDEX: std::sync::OnceLock<ZoneIndex> = std::sync::OnceLock::new();
    INDEX.get_or_init(|| {
        let mut names = std::collections::HashMap::new();
        let mut add = |name: &str, target: Option<String>| {
            names
                .entry(name.to_ascii_lowercase())
                .or_insert_with(|| (name.to_string(), target));
        };
        let zi = std::fs::read_to_string(format!("{}/tzdata.zi", ZONEINFO_DIR));
        match zi {
            Ok(text) => {
                for line in text.lines() {
                    let mut it = line.split_whitespace();
                    match it.next() {
                        Some("Z") => {
                            if let Some(n) = it.next() {
                                add(n, None);
                            }
                        }
                        Some("L") => {
                            if let (Some(target), Some(n)) = (it.next(), it.next()) {
                                add(n, Some(target.to_string()));
                            }
                        }
                        _ => {}
                    }
                }
                if std::path::Path::new(&format!("{}/posixrules", ZONEINFO_DIR)).is_file() {
                    add("posixrules", None);
                }
            }
            Err(_) => {
                // no tzdata.zi: scan the directory for TZif files
                fn walk(dir: &std::path::Path, prefix: &str, out: &mut Vec<String>) {
                    if let Ok(rd) = std::fs::read_dir(dir) {
                        for e in rd.flatten() {
                            let name = e.file_name().to_string_lossy().to_string();
                            let rel = if prefix.is_empty() {
                                name.clone()
                            } else {
                                format!("{}/{}", prefix, name)
                            };
                            let path = e.path();
                            if path.is_dir() {
                                if prefix.is_empty() && (name == "posix" || name == "right") {
                                    continue;
                                }
                                walk(&path, &rel, out);
                            } else if rel != "localtime" {
                                let mut magic = [0u8; 4];
                                let ok = std::fs::File::open(&path)
                                    .and_then(|mut f| {
                                        use std::io::Read;
                                        f.read_exact(&mut magic)
                                    })
                                    .is_ok();
                                if ok && &magic == b"TZif" {
                                    out.push(rel);
                                }
                            }
                        }
                    }
                }
                let mut found = Vec::new();
                walk(std::path::Path::new(ZONEINFO_DIR), "", &mut found);
                for n in found {
                    add(&n, None);
                }
            }
        }
        ZoneIndex { names }
    })
}

fn load_named_zone(name: &str) -> Option<std::sync::Arc<NamedZone>> {
    use std::collections::HashMap;
    use std::sync::{Arc, Mutex, OnceLock};
    if name.is_empty() || name.len() > 64 {
        return None;
    }
    let (canonical, link) = zone_index().names.get(&name.to_ascii_lowercase())?.clone();
    static CACHE: OnceLock<Mutex<HashMap<String, Arc<NamedZone>>>> = OnceLock::new();
    let cache = CACHE.get_or_init(|| Mutex::new(HashMap::new()));
    if let Ok(c) = cache.lock() {
        if let Some(z) = c.get(&canonical) {
            return Some(z.clone());
        }
    }
    // data source: the original's main-data link target, else the tzdata
    // link target, else the zone itself
    let remapped = TZ_REMAP
        .iter()
        .find(|(n, _)| *n == canonical)
        .map(|(_, t)| t.to_string());
    let file = remapped.or_else(|| link.clone()).unwrap_or_else(|| canonical.clone());
    let mut path = std::path::PathBuf::from(ZONEINFO_DIR).join(&file);
    if !path.is_file() {
        path = std::path::PathBuf::from(ZONEINFO_DIR).join(&canonical);
    }
    let data = std::fs::read(&path).ok()?;
    let (mut times, mut offsets, initial) = parse_tzif(&data)?;
    // tz-database version differences (see TZ_OVERRIDE_*)
    let ov: Option<&[(i64, i32)]> = match file.as_str() {
        "Africa/Casablanca" | "Africa/El_Aaiun" => Some(TZ_OVERRIDE_MOROCCO),
        "America/Edmonton" | "America/Inuvik" | "America/Yellowknife" => Some(TZ_OVERRIDE_MOUNTAIN),
        "America/Winnipeg" | "America/Rainy_River" => Some(TZ_OVERRIDE_CENTRAL),
        _ => None,
    };
    if file == "Europe/Dublin" {
        // the original's data ends DST 1925 on Oct 4 (newer tzdata: Sep 20)
        if let Some(i) = times.iter().position(|&t| t == -1_397_426_400) {
            times[i] = -1_396_216_800;
        }
    }
    if let Some(ov) = ov {
        let keep = times.iter().take_while(|&&t| t < TZ_OVERRIDE_CUTOFF).count();
        times.truncate(keep);
        offsets.truncate(keep);
        for &(t, o) in ov {
            times.push(t);
            offsets.push(o);
        }
    }
    let zone = Arc::new(NamedZone { id: canonical.clone(), times, offsets, initial });
    if let Ok(mut c) = cache.lock() {
        c.insert(canonical, zone.clone());
    }
    Some(zone)
}

/// Parse a TZif (v1/v2+) file: (transition times, offsets, initial offset).
/// Transitions after the explicit data are extrapolated from the POSIX
/// footer only up to the end of 2037 (as "fat" TZif data would be).
fn parse_tzif(data: &[u8]) -> Option<(Vec<i64>, Vec<i32>, i32)> {
    fn be32(b: &[u8], i: usize) -> Option<i32> {
        Some(i32::from_be_bytes(b.get(i..i + 4)?.try_into().ok()?))
    }
    fn be64(b: &[u8], i: usize) -> Option<i64> {
        Some(i64::from_be_bytes(b.get(i..i + 8)?.try_into().ok()?))
    }
    if data.len() < 44 || &data[..4] != b"TZif" {
        return None;
    }
    let version = data[4];
    let counts = |off: usize| -> Option<[usize; 6]> {
        let mut c = [0usize; 6];
        for (k, v) in c.iter_mut().enumerate() {
            *v = be32(data, off + 20 + 4 * k)? as usize;
        }
        Some(c)
    };
    let [isut, isstd, leap, timecnt, typecnt, charcnt] = counts(0)?;
    let v1_len = timecnt * 5 + typecnt * 6 + charcnt + leap * 8 + isstd + isut;
    let (base, tsize) = if version >= b'2' { (44 + v1_len, 8) } else { (0, 4) };
    let [isut, isstd, leap, timecnt, typecnt, charcnt] = counts(base)?;
    let mut p = base + 44;
    let mut times = Vec::with_capacity(timecnt);
    for k in 0..timecnt {
        times.push(if tsize == 8 { be64(data, p + 8 * k)? } else { be32(data, p + 4 * k)? as i64 });
    }
    p += timecnt * tsize;
    let idx = data.get(p..p + timecnt)?.to_vec();
    p += timecnt;
    let mut types = Vec::with_capacity(typecnt);
    for k in 0..typecnt {
        types.push(be32(data, p + 6 * k)?);
    }
    p += typecnt * 6 + charcnt + leap * (tsize + 4) + isstd + isut;
    if typecnt == 0 {
        return None;
    }
    let mut offsets = Vec::with_capacity(timecnt);
    for &i in &idx {
        offsets.push(*types.get(i as usize)?);
    }
    let initial = types[0];
    // footer (v2+): extrapolate DST rules until the end of 2037
    if version >= b'2' {
        if let Some(footer) = data.get(p..).and_then(|f| std::str::from_utf8(f).ok()) {
            let footer = footer.trim_matches('\n');
            if let Some(rule) = PosixTz::parse(footer) {
                let last = times.last().copied().unwrap_or(i64::MIN);
                const END_2037: i64 = 2_145_916_800;
                if rule.dst.is_some() && last < END_2037 {
                    let first_year = if last == i64::MIN {
                        1970
                    } else {
                        civil_from_days(last.div_euclid(86_400)).0
                    };
                    for year in first_year..=2037 {
                        for (t, o) in rule.transitions(year) {
                            if t > last && t < END_2037 {
                                times.push(t);
                                offsets.push(o);
                            }
                        }
                    }
                }
            }
        }
    }
    Some((times, offsets, initial))
}

/// Minimal POSIX TZ string ("EST5EDT,M3.2.0,M11.1.0") evaluator.
struct PosixTz {
    std_offset: i32,
    /// (dst offset, start rule, end rule); rules are (date spec, seconds)
    dst: Option<(i32, (PosixDate, i32), (PosixDate, i32))>,
}

#[derive(Clone, Copy)]
enum PosixDate {
    /// Mm.w.d
    MonthWeekDay(u32, u32, u32),
    /// Jn (1..=365, Feb 29 never counted)
    Julian1(u32),
    /// n (0..=365)
    Julian0(u32),
}

impl PosixTz {
    fn parse(s: &str) -> Option<PosixTz> {
        let b = s.as_bytes();
        let mut i = 0;
        fn name(b: &[u8], i: &mut usize) -> Option<()> {
            if b.get(*i) == Some(&b'<') {
                while *i < b.len() && b[*i] != b'>' {
                    *i += 1;
                }
                *i += 1;
            } else {
                let st = *i;
                while *i < b.len() && b[*i].is_ascii_alphabetic() {
                    *i += 1;
                }
                if *i - st < 3 {
                    return None;
                }
            }
            Some(())
        }
        fn time(b: &[u8], i: &mut usize) -> Option<i32> {
            let mut sign = 1;
            if b.get(*i) == Some(&b'+') {
                *i += 1;
            } else if b.get(*i) == Some(&b'-') {
                sign = -1;
                *i += 1;
            }
            let mut parts = [0i32; 3];
            for (k, part) in parts.iter_mut().enumerate() {
                if k > 0 {
                    if b.get(*i) != Some(&b':') {
                        break;
                    }
                    *i += 1;
                }
                let st = *i;
                while *i < b.len() && b[*i].is_ascii_digit() {
                    *part = *part * 10 + (b[*i] - b'0') as i32;
                    *i += 1;
                }
                if *i == st {
                    return None;
                }
            }
            Some(sign * (parts[0] * 3600 + parts[1] * 60 + parts[2]))
        }
        fn date(b: &[u8], i: &mut usize) -> Option<(PosixDate, i32)> {
            let num = |i: &mut usize| -> Option<u32> {
                let st = *i;
                let mut v = 0u32;
                while *i < b.len() && b[*i].is_ascii_digit() {
                    v = v * 10 + (b[*i] - b'0') as u32;
                    *i += 1;
                }
                if *i == st {
                    None
                } else {
                    Some(v)
                }
            };
            let d = match b.get(*i)? {
                b'M' => {
                    *i += 1;
                    let m = num(i)?;
                    if b.get(*i) != Some(&b'.') {
                        return None;
                    }
                    *i += 1;
                    let w = num(i)?;
                    if b.get(*i) != Some(&b'.') {
                        return None;
                    }
                    *i += 1;
                    PosixDate::MonthWeekDay(m, w, num(i)?)
                }
                b'J' => {
                    *i += 1;
                    PosixDate::Julian1(num(i)?)
                }
                _ => PosixDate::Julian0(num(i)?),
            };
            let t = if b.get(*i) == Some(&b'/') {
                *i += 1;
                time(b, i)?
            } else {
                7200
            };
            Some((d, t))
        }
        name(b, &mut i)?;
        let std_offset = -time(b, &mut i)?;
        if i >= b.len() {
            return Some(PosixTz { std_offset, dst: None });
        }
        name(b, &mut i)?;
        let dst_offset = if i < b.len() && b[i] != b',' {
            -time(b, &mut i)?
        } else {
            std_offset + 3600
        };
        if b.get(i) != Some(&b',') {
            return None;
        }
        i += 1;
        let start = date(b, &mut i)?;
        if b.get(i) != Some(&b',') {
            return None;
        }
        i += 1;
        let end = date(b, &mut i)?;
        Some(PosixTz { std_offset, dst: Some((dst_offset, start, end)) })
    }

    fn day_of(d: PosixDate, year: i64) -> i64 {
        match d {
            PosixDate::MonthWeekDay(m, w, wd) => {
                let first = days_from_civil(year, m, 1);
                let first_wd = (first + 4).rem_euclid(7) as u32;
                let mut day = 1 + (wd + 7 - first_wd) % 7 + (w.max(1) - 1) * 7;
                let next = if m == 12 { days_from_civil(year + 1, 1, 1) } else { days_from_civil(year, m + 1, 1) };
                let len = (next - first) as u32;
                while day > len {
                    day -= 7;
                }
                first + day as i64 - 1
            }
            PosixDate::Julian1(n) => {
                let jan1 = days_from_civil(year, 1, 1);
                let leap = is_leap_year_i(year);
                jan1 + n as i64 - 1 + if leap && n >= 60 { 1 } else { 0 }
            }
            PosixDate::Julian0(n) => days_from_civil(year, 1, 1) + n as i64,
        }
    }

    /// The (up to two) transitions of `year` as (utc seconds, new offset).
    fn transitions(&self, year: i64) -> Vec<(i64, i32)> {
        let Some((dst_off, (sd, st), (ed, et))) = self.dst else {
            return Vec::new();
        };
        let start = Self::day_of(sd, year) * 86_400 + st as i64 - self.std_offset as i64;
        let end = Self::day_of(ed, year) * 86_400 + et as i64 - dst_off as i64;
        let mut v = vec![(start, dst_off), (end, self.std_offset)];
        v.sort();
        v
    }
}

/// "GMT+5:30" / "GMT-8" / "GMT+0" (seconds truncated).
fn gmt_offset_name(offset_seconds: i64) -> String {
    let sign = if offset_seconds < 0 { '-' } else { '+' };
    let a = offset_seconds.abs();
    let (h, m) = (a / 3600, a / 60 % 60);
    if m == 0 {
        format!("GMT{}{}", sign, h)
    } else {
        format!("GMT{}{}:{:02}", sign, h, m)
    }
}

/// "+HH", "+HHMM", "+HH:MM" (also '-'), hours 0..=23, minutes 0..=59.
fn parse_offset_time_zone(s: &str) -> Option<i32> {
    let b = s.as_bytes();
    if b.len() < 3 || !(b[0] == b'+' || b[0] == b'-') {
        return None;
    }
    let digits = |x: &[u8]| -> Option<i32> {
        if x.len() == 2 && x.iter().all(|c| c.is_ascii_digit()) {
            Some(((x[0] - b'0') * 10 + (x[1] - b'0')) as i32)
        } else {
            None
        }
    };
    let h = digits(&b[1..3])?;
    let m = match b.len() {
        3 => 0,
        5 => digits(&b[3..5])?,
        6 if b[3] == b':' => digits(&b[4..6])?,
        _ => return None,
    };
    if h > 23 || m > 59 {
        return None;
    }
    let v = h * 60 + m;
    Some(if b[0] == b'-' { -v } else { v })
}

/// Long time-zone display names used by the original where they differ from
/// the zone id (a few CLDR names, otherwise a representative zone id).
const TZ_LONG_NAMES: &[(&str, &[&str])] = &[
    ("Africa/Abidjan", &["Africa/Accra", "Africa/Bamako", "Africa/Banjul", "Africa/Conakry", "Africa/Dakar", "Africa/Freetown", "Africa/Lome", "Africa/Nouakchott", "Africa/Ouagadougou", "Africa/Timbuktu", "Atlantic/Reykjavik", "Atlantic/St_Helena", "Iceland"]),
    ("Africa/Addis_Ababa", &["Africa/Asmara", "Africa/Asmera", "Africa/Dar_es_Salaam", "Africa/Djibouti", "Africa/Kampala", "Africa/Mogadishu", "Africa/Nairobi", "Indian/Antananarivo", "Indian/Comoro", "Indian/Mayotte"]),
    ("Africa/Bangui", &["Africa/Brazzaville", "Africa/Douala", "Africa/Kinshasa", "Africa/Lagos", "Africa/Libreville", "Africa/Luanda", "Africa/Malabo", "Africa/Niamey", "Africa/Porto-Novo"]),
    ("Africa/Blantyre", &["Africa/Bujumbura", "Africa/Gaborone", "Africa/Harare", "Africa/Kigali", "Africa/Lubumbashi", "Africa/Lusaka", "Africa/Maputo"]),
    ("Africa/Cairo", &["Egypt"]),
    ("Africa/Johannesburg", &["Africa/Maseru", "Africa/Mbabane"]),
    ("Africa/Tripoli", &["Libya"]),
    ("America/Adak", &["America/Atka", "US/Aleutian"]),
    ("America/Anchorage", &["US/Alaska"]),
    ("America/Anguilla", &["America/Antigua", "America/Aruba", "America/Blanc-Sablon", "America/Curacao", "America/Dominica", "America/Grenada", "America/Guadeloupe", "America/Kralendijk", "America/Lower_Princes", "America/Marigot", "America/Montserrat", "America/Port_of_Spain", "America/Puerto_Rico", "America/St_Barthelemy", "America/St_Kitts", "America/St_Lucia", "America/St_Thomas", "America/St_Vincent", "America/Tortola", "America/Virgin"]),
    ("America/Argentina/Buenos_Aires", &["America/Buenos_Aires"]),
    ("America/Argentina/Catamarca", &["America/Argentina/ComodRivadavia", "America/Catamarca"]),
    ("America/Argentina/Cordoba", &["America/Cordoba", "America/Rosario"]),
    ("America/Argentina/Jujuy", &["America/Jujuy"]),
    ("America/Argentina/Mendoza", &["America/Mendoza"]),
    ("America/Atikokan", &["America/Cayman", "America/Coral_Harbour", "America/Panama", "EST"]),
    ("America/Creston", &["America/Phoenix", "MST", "US/Arizona"]),
    ("America/Detroit", &["US/Michigan"]),
    ("America/Edmonton", &["America/Yellowknife", "Canada/Mountain"]),
    ("America/Halifax", &["Canada/Atlantic"]),
    ("America/Havana", &["Cuba"]),
    ("America/Indiana/Indianapolis", &["America/Fort_Wayne", "America/Indianapolis", "US/East-Indiana"]),
    ("America/Indiana/Knox", &["America/Knox_IN", "US/Indiana-Starke"]),
    ("America/Iqaluit", &["America/Pangnirtung"]),
    ("America/Jamaica", &["Jamaica"]),
    ("America/Kentucky/Louisville", &["America/Louisville"]),
    ("America/Manaus", &["Brazil/West"]),
    ("America/Mazatlan", &["Mexico/BajaSur"]),
    ("America/Mexico_City", &["Mexico/General"]),
    ("America/Nassau", &["America/Montreal", "America/Nipigon", "America/Thunder_Bay", "America/Toronto", "Canada/Eastern"]),
    ("America/Noronha", &["Brazil/DeNoronha"]),
    ("America/Nuuk", &["America/Godthab"]),
    ("America/Regina", &["Canada/Saskatchewan"]),
    ("America/Rio_Branco", &["America/Porto_Acre", "Brazil/Acre"]),
    ("America/Santiago", &["Chile/Continental"]),
    ("America/Sao_Paulo", &["Brazil/East"]),
    ("America/St_Johns", &["Canada/Newfoundland"]),
    ("America/Tijuana", &["America/Ensenada", "America/Santa_Isabel", "Mexico/BajaNorte"]),
    ("America/Vancouver", &["Canada/Pacific"]),
    ("America/Whitehorse", &["Canada/Yukon"]),
    ("America/Winnipeg", &["America/Rainy_River", "Canada/Central"]),
    ("Antarctica/DumontDUrville", &["Pacific/Chuuk", "Pacific/Port_Moresby", "Pacific/Truk", "Pacific/Yap"]),
    ("Antarctica/McMurdo", &["Antarctica/South_Pole", "NZ", "Pacific/Auckland"]),
    ("Antarctica/Syowa", &["Asia/Aden", "Asia/Kuwait", "Asia/Riyadh"]),
    ("Arctic/Longyearbyen", &["Atlantic/Jan_Mayen", "Europe/Berlin", "Europe/Copenhagen", "Europe/Oslo", "Europe/Stockholm"]),
    ("Asia/Ashgabat", &["Asia/Ashkhabad"]),
    ("Asia/Bahrain", &["Asia/Qatar"]),
    ("Asia/Bangkok", &["Asia/Phnom_Penh", "Asia/Vientiane", "Indian/Christmas"]),
    ("Asia/Brunei", &["Asia/Kuching"]),
    ("Asia/Dhaka", &["Asia/Dacca"]),
    ("Asia/Dubai", &["Asia/Muscat", "Indian/Mahe", "Indian/Reunion"]),
    ("Asia/Ho_Chi_Minh", &["Asia/Saigon"]),
    ("Asia/Hong_Kong", &["Hongkong"]),
    ("Asia/Jerusalem", &["Asia/Tel_Aviv", "Israel"]),
    ("Asia/Kathmandu", &["Asia/Katmandu"]),
    ("Asia/Kuala_Lumpur", &["Asia/Singapore", "Singapore"]),
    ("Asia/Macau", &["Asia/Macao"]),
    ("Asia/Makassar", &["Asia/Ujung_Pandang"]),
    ("Asia/Nicosia", &["Europe/Nicosia"]),
    ("Asia/Seoul", &["ROK"]),
    ("Asia/Taipei", &["ROC"]),
    ("Asia/Tehran", &["Iran"]),
    ("Asia/Thimphu", &["Asia/Thimbu"]),
    ("Asia/Ulaanbaatar", &["Asia/Choibalsan", "Asia/Ulan_Bator"]),
    ("Asia/Urumqi", &["Asia/Kashgar"]),
    ("Asia/Yangon", &["Asia/Rangoon", "Indian/Cocos"]),
    ("Atlantic/Faroe", &["Atlantic/Faeroe"]),
    ("Australia/Adelaide", &["Australia/South"]),
    ("Australia/Brisbane", &["Australia/Queensland"]),
    ("Australia/Broken_Hill", &["Australia/Yancowinna"]),
    ("Australia/Darwin", &["Australia/North"]),
    ("Australia/Hobart", &["Australia/Currie", "Australia/Tasmania"]),
    ("Australia/Lord_Howe", &["Australia/LHI"]),
    ("Australia/Melbourne", &["Australia/Victoria"]),
    ("Australia/Perth", &["Australia/West"]),
    ("Australia/Sydney", &["Australia/ACT", "Australia/Canberra", "Australia/NSW"]),
    ("Central European Standard Time", &["CET", "Europe/Amsterdam", "Europe/Brussels", "Europe/Budapest", "Europe/Luxembourg", "Europe/Madrid", "Europe/Rome", "Europe/San_Marino", "Europe/Vatican", "Europe/Vienna", "Europe/Warsaw", "MET", "Poland"]),
    ("Central Standard Time", &["America/Chicago", "CST6CDT", "US/Central"]),
    ("China Standard Time", &["Asia/Chongqing", "Asia/Chungking", "Asia/Harbin", "Asia/Shanghai", "PRC"]),
    ("Coordinated Universal Time", &["UTC"]),
    ("Eastern Standard Time", &["America/New_York", "EST5EDT", "US/Eastern", "posixrules"]),
    ("Europe/Athens", &["EET"]),
    ("Europe/Belgrade", &["Europe/Ljubljana", "Europe/Podgorica", "Europe/Sarajevo", "Europe/Skopje", "Europe/Zagreb"]),
    ("Europe/Bratislava", &["Europe/Prague"]),
    ("Europe/Busingen", &["Europe/Vaduz", "Europe/Zurich"]),
    ("Europe/Chisinau", &["Europe/Tiraspol"]),
    ("Europe/Dublin", &["Eire"]),
    ("Europe/Guernsey", &["Europe/Belfast", "Europe/Isle_of_Man", "Europe/Jersey", "Europe/London", "GB", "GB-Eire"]),
    ("Europe/Helsinki", &["Europe/Mariehamn"]),
    ("Europe/Istanbul", &["Asia/Istanbul", "Turkey"]),
    ("Europe/Kyiv", &["Europe/Kiev", "Europe/Uzhgorod", "Europe/Zaporozhye"]),
    ("Europe/Lisbon", &["Portugal", "WET"]),
    ("Europe/Monaco", &["Europe/Paris"]),
    ("Europe/Moscow", &["W-SU"]),
    ("India Standard Time", &["Asia/Calcutta", "Asia/Kolkata"]),
    ("Indian/Kerguelen", &["Indian/Maldives"]),
    ("Japan Standard Time", &["Asia/Tokyo", "Japan"]),
    ("Mountain Standard Time", &["America/Denver", "America/Shiprock", "MST7MDT", "Navajo", "US/Mountain"]),
    ("Pacific Standard Time", &["America/Los_Angeles", "PST8PDT", "US/Pacific"]),
    ("Pacific/Chatham", &["NZ-CHAT"]),
    ("Pacific/Easter", &["Chile/EasterIsland"]),
    ("Pacific/Funafuti", &["Pacific/Majuro", "Pacific/Tarawa", "Pacific/Wake", "Pacific/Wallis"]),
    ("Pacific/Guadalcanal", &["Pacific/Pohnpei", "Pacific/Ponape"]),
    ("Pacific/Guam", &["Pacific/Saipan"]),
    ("Pacific/Honolulu", &["HST", "Pacific/Johnston", "US/Hawaii"]),
    ("Pacific/Kanton", &["Pacific/Enderbury"]),
    ("Pacific/Kwajalein", &["Kwajalein"]),
    ("Pacific/Midway", &["Pacific/Pago_Pago", "Pacific/Samoa", "US/Samoa"]),
    ("UTC", &["Etc/GMT", "Etc/GMT+0", "Etc/GMT-0", "Etc/GMT0", "Etc/Greenwich", "Etc/UCT", "Etc/UTC", "Etc/Universal", "Etc/Zulu", "GMT", "GMT+0", "GMT-0", "GMT0", "Greenwich", "UCT", "Universal", "Zulu"]),
];

/// Names that are links in the original's (non-backzone) tz database but
/// separate zones in a backzone build: name -> zone whose data to use.
const TZ_REMAP: &[(&str, &str)] = &[
    ("Africa/Accra", "Africa/Abidjan"),
    ("Africa/Addis_Ababa", "Africa/Nairobi"),
    ("Africa/Asmara", "Africa/Nairobi"),
    ("Africa/Asmera", "Africa/Nairobi"),
    ("Africa/Bamako", "Africa/Abidjan"),
    ("Africa/Bangui", "Africa/Lagos"),
    ("Africa/Banjul", "Africa/Abidjan"),
    ("Africa/Blantyre", "Africa/Maputo"),
    ("Africa/Brazzaville", "Africa/Lagos"),
    ("Africa/Bujumbura", "Africa/Maputo"),
    ("Africa/Conakry", "Africa/Abidjan"),
    ("Africa/Dakar", "Africa/Abidjan"),
    ("Africa/Dar_es_Salaam", "Africa/Nairobi"),
    ("Africa/Djibouti", "Africa/Nairobi"),
    ("Africa/Douala", "Africa/Lagos"),
    ("Africa/Freetown", "Africa/Abidjan"),
    ("Africa/Gaborone", "Africa/Maputo"),
    ("Africa/Harare", "Africa/Maputo"),
    ("Africa/Kampala", "Africa/Nairobi"),
    ("Africa/Kigali", "Africa/Maputo"),
    ("Africa/Kinshasa", "Africa/Lagos"),
    ("Africa/Libreville", "Africa/Lagos"),
    ("Africa/Lome", "Africa/Abidjan"),
    ("Africa/Luanda", "Africa/Lagos"),
    ("Africa/Lubumbashi", "Africa/Maputo"),
    ("Africa/Lusaka", "Africa/Maputo"),
    ("Africa/Malabo", "Africa/Lagos"),
    ("Africa/Maseru", "Africa/Johannesburg"),
    ("Africa/Mbabane", "Africa/Johannesburg"),
    ("Africa/Mogadishu", "Africa/Nairobi"),
    ("Africa/Niamey", "Africa/Lagos"),
    ("Africa/Nouakchott", "Africa/Abidjan"),
    ("Africa/Ouagadougou", "Africa/Abidjan"),
    ("Africa/Porto-Novo", "Africa/Lagos"),
    ("Africa/Timbuktu", "Africa/Abidjan"),
    ("America/Anguilla", "America/Puerto_Rico"),
    ("America/Antigua", "America/Puerto_Rico"),
    ("America/Aruba", "America/Puerto_Rico"),
    ("America/Atikokan", "America/Panama"),
    ("America/Blanc-Sablon", "America/Puerto_Rico"),
    ("America/Cayman", "America/Panama"),
    ("America/Coral_Harbour", "America/Panama"),
    ("America/Creston", "America/Phoenix"),
    ("America/Curacao", "America/Puerto_Rico"),
    ("America/Dominica", "America/Puerto_Rico"),
    ("America/Grenada", "America/Puerto_Rico"),
    ("America/Guadeloupe", "America/Puerto_Rico"),
    ("America/Kralendijk", "America/Puerto_Rico"),
    ("America/Lower_Princes", "America/Puerto_Rico"),
    ("America/Marigot", "America/Puerto_Rico"),
    ("America/Montserrat", "America/Puerto_Rico"),
    ("America/Nassau", "America/Toronto"),
    ("America/Port_of_Spain", "America/Puerto_Rico"),
    ("America/St_Barthelemy", "America/Puerto_Rico"),
    ("America/St_Kitts", "America/Puerto_Rico"),
    ("America/St_Lucia", "America/Puerto_Rico"),
    ("America/St_Thomas", "America/Puerto_Rico"),
    ("America/St_Vincent", "America/Puerto_Rico"),
    ("America/Tortola", "America/Puerto_Rico"),
    ("America/Virgin", "America/Puerto_Rico"),
    ("Antarctica/DumontDUrville", "Pacific/Port_Moresby"),
    ("Antarctica/McMurdo", "Pacific/Auckland"),
    ("Antarctica/South_Pole", "Pacific/Auckland"),
    ("Antarctica/Syowa", "Asia/Riyadh"),
    ("Arctic/Longyearbyen", "Europe/Berlin"),
    ("Asia/Aden", "Asia/Riyadh"),
    ("Asia/Bahrain", "Asia/Qatar"),
    ("Asia/Brunei", "Asia/Kuching"),
    ("Asia/Kuala_Lumpur", "Asia/Singapore"),
    ("Asia/Kuwait", "Asia/Riyadh"),
    ("Asia/Muscat", "Asia/Dubai"),
    ("Asia/Phnom_Penh", "Asia/Bangkok"),
    ("Asia/Vientiane", "Asia/Bangkok"),
    ("Atlantic/Jan_Mayen", "Europe/Berlin"),
    ("Atlantic/Reykjavik", "Africa/Abidjan"),
    ("Atlantic/St_Helena", "Africa/Abidjan"),
    ("CET", "Europe/Brussels"),
    ("CST6CDT", "America/Chicago"),
    ("EET", "Europe/Athens"),
    ("EST", "America/Panama"),
    ("EST5EDT", "America/New_York"),
    ("Europe/Amsterdam", "Europe/Brussels"),
    ("Europe/Copenhagen", "Europe/Berlin"),
    ("Europe/Guernsey", "Europe/London"),
    ("Europe/Isle_of_Man", "Europe/London"),
    ("Europe/Jersey", "Europe/London"),
    ("Europe/Ljubljana", "Europe/Belgrade"),
    ("Europe/Luxembourg", "Europe/Brussels"),
    ("Europe/Monaco", "Europe/Paris"),
    ("Europe/Oslo", "Europe/Berlin"),
    ("Europe/Sarajevo", "Europe/Belgrade"),
    ("Europe/Skopje", "Europe/Belgrade"),
    ("Europe/Stockholm", "Europe/Berlin"),
    ("Europe/Vaduz", "Europe/Zurich"),
    ("Europe/Zagreb", "Europe/Belgrade"),
    ("HST", "Pacific/Honolulu"),
    ("Iceland", "Africa/Abidjan"),
    ("Indian/Antananarivo", "Africa/Nairobi"),
    ("Indian/Christmas", "Asia/Bangkok"),
    ("Indian/Cocos", "Asia/Yangon"),
    ("Indian/Comoro", "Africa/Nairobi"),
    ("Indian/Kerguelen", "Indian/Maldives"),
    ("Indian/Mahe", "Asia/Dubai"),
    ("Indian/Mayotte", "Africa/Nairobi"),
    ("Indian/Reunion", "Asia/Dubai"),
    ("MET", "Europe/Brussels"),
    ("MST", "America/Phoenix"),
    ("MST7MDT", "America/Denver"),
    ("PST8PDT", "America/Los_Angeles"),
    ("Pacific/Chuuk", "Pacific/Port_Moresby"),
    ("Pacific/Funafuti", "Pacific/Tarawa"),
    ("Pacific/Majuro", "Pacific/Tarawa"),
    ("Pacific/Midway", "Pacific/Pago_Pago"),
    ("Pacific/Pohnpei", "Pacific/Guadalcanal"),
    ("Pacific/Ponape", "Pacific/Guadalcanal"),
    ("Pacific/Saipan", "Pacific/Guam"),
    ("Pacific/Truk", "Pacific/Port_Moresby"),
    ("Pacific/Wake", "Pacific/Tarawa"),
    ("Pacific/Wallis", "Pacific/Tarawa"),
    ("Pacific/Yap", "Pacific/Port_Moresby"),
    ("WET", "Europe/Lisbon"),
];

/// tz-database version differences: the original's data predates the 2026
/// changes for Morocco and Alberta/Manitoba.  (file, cutoff, transitions).
const TZ_OVERRIDE_CUTOFF: i64 = 1_782_864_000; // 2026-07-01T00:00:00Z
const TZ_OVERRIDE_MOROCCO: &[(i64, i32)] = &[
    (1801965600, 0), (1804989600, 3600), (1832205600, 0), (1835834400, 3600), (1863050400, 0), (1866074400, 3600),
    (1893290400, 0), (1896919200, 3600), (1924135200, 0), (1927159200, 3600), (1954980000, 0), (1958004000, 3600),
    (1985220000, 0), (1988848800, 3600), (2016064800, 0), (2019088800, 3600), (2046304800, 0), (2049933600, 3600),
    (2077149600, 0), (2080778400, 3600), (2107994400, 0), (2111018400, 3600), (2138234400, 0), (2141863200, 3600),
    (2169079200, 0), (2172103200, 3600), (2199924000, 0), (2202948000, 3600), (2230164000, 0), (2233792800, 3600),
    (2261008800, 0), (2264032800, 3600), (2291248800, 0), (2294877600, 3600), (2322093600, 0), (2325722400, 3600),
    (2352938400, 0), (2355962400, 3600), (2383178400, 0), (2386807200, 3600), (2414023200, 0), (2417047200, 3600),
    (2444868000, 0), (2447892000, 3600), (2475108000, 0), (2478736800, 3600), (2505952800, 0), (2508976800, 3600),
    (2536192800, 0), (2539821600, 3600), (2567037600, 0), (2570666400, 3600), (2597882400, 0), (2600906400, 3600),
    (2628122400, 0), (2631751200, 3600), (2658967200, 0), (2661991200, 3600), (2689812000, 0), (2692836000, 3600),
    (2720052000, 0), (2723680800, 3600), (2750896800, 0), (2753920800, 3600), (2781136800, 0), (2784765600, 3600),
    (2811981600, 0), (2815610400, 3600), (2842826400, 0), (2845850400, 3600), (2873066400, 0), (2876695200, 3600),
    (2903911200, 0), (2906935200, 3600), (2934756000, 0), (2937780000, 3600), (2964996000, 0), (2968624800, 3600),
    (2995840800, 0), (2998864800, 3600), (3026080800, 0), (3029709600, 3600), (3056925600, 0), (3060554400, 3600),
    (3087770400, 0), (3090794400, 3600), (3118010400, 0), (3121639200, 3600), (3148855200, 0), (3151879200, 3600),
    (3179700000, 0), (3182724000, 3600), (3209940000, 0), (3213568800, 3600), (3240784800, 0), (3243808800, 3600),
    (3271024800, 0), (3274653600, 3600), (3301869600, 0), (3305498400, 3600), (3332714400, 0), (3335738400, 3600),
    (3362954400, 0), (3366583200, 3600), (3393799200, 0), (3396823200, 3600), (3424644000, 0), (3427668000, 3600),
    (3454884000, 0), (3458512800, 3600), (3485728800, 0), (3488752800, 3600), (3515968800, 0), (3519597600, 3600),
    (3546813600, 0), (3549837600, 3600), (3577658400, 0), (3580682400, 3600), (3607898400, 0), (3611527200, 3600),
    (3638743200, 0), (3641767200, 3600), (3669588000, 0), (3672612000, 3600), (3699828000, 0), (3703456800, 3600),
];
const TZ_OVERRIDE_MOUNTAIN: &[(i64, i32)] = &[
    (1793520000, -25200), (1805014800, -21600), (1825574400, -25200), (1836464400, -21600), (1857024000, -25200), (1867914000, -21600),
    (1888473600, -25200), (1899363600, -21600), (1919923200, -25200), (1930813200, -21600), (1951372800, -25200), (1962867600, -21600),
    (1983427200, -25200), (1994317200, -21600), (2014876800, -25200), (2025766800, -21600), (2046326400, -25200), (2057216400, -21600),
    (2077776000, -25200), (2088666000, -21600), (2109225600, -25200), (2120115600, -21600), (2140675200, -25200),
];
const TZ_OVERRIDE_CENTRAL: &[(i64, i32)] = &[
    (1793516400, -21600), (1805011200, -18000), (1825570800, -21600), (1836460800, -18000), (1857020400, -21600), (1867910400, -18000),
    (1888470000, -21600), (1899360000, -18000), (1919919600, -21600), (1930809600, -18000), (1951369200, -21600), (1962864000, -18000),
    (1983423600, -21600), (1994313600, -18000), (2014873200, -21600), (2025763200, -18000), (2046322800, -21600), (2057212800, -18000),
    (2077772400, -21600), (2088662400, -18000), (2109222000, -21600), (2120112000, -18000), (2140671600, -21600),
];

#[cfg(test)]
mod tests {
    use super::*;

    fn opts(pairs: &[(&str, &str)]) -> DateTimeFormatOptions {
        let mut o = DateTimeFormatOptions::new();
        for (k, v) in pairs {
            o.set(k, v).unwrap();
        }
        o
    }

    fn loc(l: &str) -> Vec<String> {
        vec![l.to_string()]
    }

    #[test]
    fn core_algorithms() {
        let t = 951_782_400_000.0; // 2000-02-29
        assert_eq!(year_from_time(t), 2000.0);
        assert_eq!(month_from_time(t), 1.0);
        assert_eq!(date_from_time(t), 29.0);
        assert_eq!(week_day(t), 2.0);
        assert!(in_leap_year(t));
        assert_eq!(days_in_year(1900.0), 365.0);
        assert_eq!(days_in_year(2000.0), 366.0);
        assert_eq!(day_from_year(1970.0), 0.0);
        assert_eq!(hour_from_time(-1.0), 23.0);
        assert_eq!(ms_from_time(-1.0), 999.0);
        assert_eq!(make_date(make_day(2020.0, 12.0, 1.0), 0.0), 1_609_459_200_000.0);
        assert_eq!(make_date(make_day(2020.0, -1.0, 1.0), 0.0), 1_575_158_400_000.0);
        assert!(make_day(300_001.0, 0.0, 1.0).is_nan());
        assert!(!make_day(300_000.0, 0.0, 1.0).is_nan());
        assert_eq!(make_time(1.9, 0.0, 0.0, -0.9), 3_600_000.0);
        assert!(time_clip(8.64e15 + 1.0).is_nan());
        assert_eq!(time_clip(-0.5).to_bits(), 0.0f64.to_bits());
        assert_eq!(time_clip(8.64e15), 8.64e15);
        assert_eq!(local_tza(0.0, true), 0.0);
    }

    #[test]
    fn string_formats() {
        assert_eq!(to_date_string(0.0), "Thu Jan 01 1970 00:00:00 GMT+0000 (Coordinated Universal Time)");
        assert_eq!(to_date_only_string(0.0), "Thu Jan 01 1970");
        assert_eq!(to_time_only_string(0.0), "00:00:00 GMT+0000 (Coordinated Universal Time)");
        assert_eq!(to_utc_string(0.0), "Thu, 01 Jan 1970 00:00:00 GMT");
        assert_eq!(to_iso_string(0.0).unwrap(), "1970-01-01T00:00:00.000Z");
        assert_eq!(to_iso_string(8.64e15).unwrap(), "+275760-09-13T00:00:00.000Z");
        assert_eq!(to_iso_string(-62_198_755_200_000.0).unwrap(), "-000001-01-01T00:00:00.000Z");
        assert_eq!(to_date_string(-62_198_755_200_000.0), "Fri Jan 01 -0001 00:00:00 GMT+0000 (Coordinated Universal Time)");
        assert_eq!(to_utc_string(-8.64e15), "Tue, 20 Apr -271821 00:00:00 GMT");
        assert_eq!(to_date_string(f64::NAN), "Invalid Date");
        assert!(to_iso_string(f64::NAN).is_none());
    }

    #[test]
    fn parse_iso_forms() {
        assert_eq!(parse("2020-01-02"), 1_577_923_200_000.0);
        assert_eq!(parse("2020-01-02T03:04:05.123456Z"), 1_577_934_245_123.0);
        assert_eq!(parse("2020-01-02T03:04:05-01:30"), 1_577_939_645_000.0);
        assert_eq!(parse("2020-13-01"), 1_609_459_200_000.0);
        assert_eq!(parse("2020-01-02T03Z"), 1_577_934_000_000.0);
        assert_eq!(parse("+275760-09-13T00:00:00.000Z"), 8.64e15);
        assert!(parse("+275760-09-13T00:00:00.001Z").is_nan());
        assert!(parse("-000000-01-01T00:00:00Z").is_nan());
        assert!(parse("2020-01-02T03:04:05+0100").is_nan());
        assert!(parse("\u{feff}2020-01-02").is_nan());
        assert_eq!(parse("\u{a0}2020-01-02 "), 1_577_923_200_000.0);
    }

    #[test]
    fn parse_space_separated_forms() {
        assert_eq!(parse("2020-01-02 03:04:05+0100"), 1_577_930_645_000.0);
        assert_eq!(parse("2020-1-2 03:04"), 1_577_934_240_000.0);
        assert_eq!(parse_for_constructor("2020-1-2 03:04"), 1_577_934_240_000.0);
        assert_eq!(parse("1 1"), -62_135_593_200_000.0);
        assert!(parse("2020-01-02  03:04").is_nan());
        assert!(parse("2376 x-5\u{e9}(").is_nan()); // the original panics here
    }

    #[test]
    fn parse_legacy_forms() {
        assert_eq!(parse("Thu Jan 01 1970 00:00:00 GMT+0000 (Coordinated Universal Time)"), 0.0);
        assert_eq!(parse("Sat, 07 Mar 2020 10:00:00 GMT"), 1_583_575_200_000.0);
        assert_eq!(parse("Tue Mar 07 2020 10:00:00 GMT+0200 (EET)"), 1_583_568_000_000.0);
        assert_eq!(parse("March 7, 2020"), 1_583_539_200_000.0);
        assert_eq!(parse("7 March 2020"), 1_583_539_200_000.0);
        assert_eq!(parse("Mar 7 2020 1:00 PM"), 1_583_542_800_000.0); // PM ignored
        assert_eq!(parse("Mar 7 2020 10:00 +0200"), -55_850_133_600_000.0); // year 200
        assert_eq!(parse("Mar 7 2020 10:20:30.5"), 1_583_576_400_000.0);
        assert_eq!(parse("Sep 14 275760"), 8_640_000_086_400_000.0); // no TimeClip
        assert_eq!(parse("Mar 7 2147483647"), -6_019_000_087_225_406_464.0); // i64 wrap
        assert!(parse("2020/03/07").is_nan());
        assert!(parse("Mar 7").is_nan());
        assert!(parse_for_constructor("March 7, 2020").is_nan());
        assert!(parse("").is_nan());
    }

    #[test]
    fn locale_defaults() {
        let o = DateTimeFormatOptions::new();
        assert_eq!(to_locale_string(0.0, &[], &o).unwrap(), "1/1/1970, 12:00:00 AM");
        assert_eq!(to_locale_date_string(0.0, &[], &o).unwrap(), "1/1/1970");
        assert_eq!(to_locale_time_string(0.0, &[], &o).unwrap(), "12:00:00 AM");
        assert_eq!(to_locale_string(f64::NAN, &loc("bad_tag"), &o).unwrap(), "Invalid Date");
        let t = 1_583_593_445_006.0; // 2020-03-07T15:04:05.006Z
        assert_eq!(to_locale_string(t, &loc("de-DE"), &o).unwrap(), "7.3.2020, 15:04:05");
        assert_eq!(to_locale_string(t, &loc("ja-JP"), &o).unwrap(), "2020/3/7, 15:04:05");
        assert_eq!(to_locale_string(t, &loc("ar-EG"), &o).unwrap(), "٧/٣/٢٠٢٠, ١٥:٠٤:٠٥");
        assert_eq!(to_locale_string(t, &loc("en-GB"), &o).unwrap(), "3/7/2020, 3:04:05 PM");
    }

    #[test]
    fn locale_options() {
        let t = 1_583_593_445_006.0;
        let full = opts(&[("weekday", "long"), ("year", "numeric"), ("month", "long"), ("day", "numeric")]);
        assert_eq!(to_locale_date_string(t, &loc("en-US"), &full).unwrap(), "Saturday, March 7, 2020");
        assert_eq!(to_locale_date_string(t, &loc("de-DE"), &full).unwrap(), "Saturday, März 7, 2020");
        let mut h = DateTimeFormatOptions::new();
        h.set_hour12(false);
        assert_eq!(to_locale_time_string(t, &loc("en-US"), &h).unwrap(), "15:04:05");
        let ny = opts(&[("timeZone", "+05:30"), ("timeZoneName", "short")]);
        assert_eq!(to_locale_string(t, &loc("en-US"), &ny).unwrap(), "3/7/2020, 8:34:05 PM GMT+5:30");
        let w = opts(&[("weekday", "long")]);
        assert_eq!(DateTimeFormat::new(&loc("en"), &w).unwrap().format(t).unwrap(), "Saturday, ");
        let s = opts(&[("dateStyle", "medium"), ("timeStyle", "short")]);
        assert_eq!(DateTimeFormat::new(&loc("en"), &s).unwrap().format(t).unwrap(), "Mar 7, 2020, 3:04 PM");
        let e = opts(&[("dateStyle", "full"), ("hour", "numeric")]);
        assert_eq!(DateTimeFormat::new(&loc("en"), &e).unwrap_err().kind, ErrorKind::Type);
        let mut o = DateTimeFormatOptions::new();
        assert_eq!(o.set("month", "foo").unwrap_err().message, "invalid month: foo");
        assert_eq!(o.set("timeZone", "Bad/Zone").unwrap_err().message, "invalid time zone: Bad/Zone");
        assert!(o.set_fractional_second_digits(4.0).is_err());
        assert_eq!(
            canonicalize_locale_list(&loc("en_US")).unwrap_err().message,
            "Incorrect locale information provided: en_US"
        );
        let jp = opts(&[("calendar", "japanese"), ("era", "long"), ("year", "numeric")]);
        assert_eq!(DateTimeFormat::new(&loc("en"), &jp).unwrap().format(t).unwrap(), "2 Reiwa");
    }

    #[test]
    fn named_time_zones() {
        if !std::path::Path::new("/usr/share/zoneinfo/America/New_York").is_file() {
            return;
        }
        let t = 1_594_814_400_000.0; // 2020-07-15T12:00Z
        let o = opts(&[("timeZone", "america/new_york"), ("timeZoneName", "short")]);
        let f = DateTimeFormat::with_defaults(&loc("en-US"), &o, RequiredComponents::Any, DefaultComponents::All).unwrap();
        // EDT is applied, but the zone name is the epoch offset (quirk)
        assert_eq!(f.format(t).unwrap(), "7/15/2020, 8:00:00 AM GMT-5");
        assert_eq!(TimeZone::from_name("US/Eastern").unwrap().id(), "US/Eastern");
        let l = opts(&[("timeZone", "Europe/London"), ("timeZoneName", "long")]);
        assert_eq!(DateTimeFormat::new(&loc("en"), &l).unwrap().format(t).unwrap(), "7/15/2020 Europe/Guernsey");
        // no DST after 2037
        let z = TimeZone::from_name("America/New_York").unwrap();
        assert_eq!(z.offset_ms(2_162_376_000_000.0), -18_000_000.0); // 2038-07-10
        assert_eq!(z.offset_ms(2_131_012_800_000.0), -14_400_000.0); // 2037-07-12
    }
}

// ---------------------------------------------------------------------------
// Accessors used by Temporal (src/builtins/temporal)
// ---------------------------------------------------------------------------

impl TimeZone {
    /// Primary identifier of the zone after resolving links (and the
    /// original's link remapping); all UTC aliases map to "UTC".
    pub fn primary_id(&self) -> String {
        match self {
            TimeZone::Utc => "UTC".to_string(),
            TimeZone::Fixed(_) => self.id(),
            TimeZone::Named(z) => {
                let id = z.id.clone();
                let (canonical, link) = match zone_index().names.get(&id.to_ascii_lowercase()) {
                    Some(e) => e.clone(),
                    None => (id.clone(), None),
                };
                let target = TZ_REMAP
                    .iter()
                    .find(|(n, _)| *n == canonical)
                    .map(|(_, t)| t.to_string())
                    .or(link)
                    .unwrap_or(canonical);
                const UTC_ALIASES: &[&str] = &[
                    "Etc/UTC", "Etc/GMT", "Etc/GMT+0", "Etc/GMT-0", "Etc/GMT0", "Etc/Greenwich", "Etc/UCT",
                    "Etc/Universal", "Etc/Zulu", "GMT", "GMT+0", "GMT-0", "GMT0", "Greenwich", "UCT", "UTC",
                    "Universal", "Zulu",
                ];
                if UTC_ALIASES.contains(&target.as_str()) {
                    "UTC".to_string()
                } else {
                    target
                }
            }
        }
    }

    /// First instant (epoch seconds) strictly after `t` at which the UTC
    /// offset of a named zone changes.
    pub fn next_offset_transition(&self, t: i64) -> Option<i64> {
        let TimeZone::Named(z) = self else { return None };
        let start = match z.times.binary_search(&t) {
            Ok(i) => i + 1,
            Err(i) => i,
        };
        for i in start..z.times.len() {
            let prev = if i == 0 { z.initial } else { z.offsets[i - 1] };
            if z.offsets[i] != prev {
                return Some(z.times[i]);
            }
        }
        None
    }

    /// Last instant (epoch seconds) strictly before `t` at which the UTC
    /// offset of a named zone changes.
    pub fn prev_offset_transition(&self, t: i64) -> Option<i64> {
        let TimeZone::Named(z) = self else { return None };
        let end = match z.times.binary_search(&t) {
            Ok(i) => i,
            Err(i) => i,
        };
        for i in (0..end).rev() {
            let prev = if i == 0 { z.initial } else { z.offsets[i - 1] };
            if z.offsets[i] != prev {
                return Some(z.times[i]);
            }
        }
        None
    }
}
