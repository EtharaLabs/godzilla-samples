//! Pure ISO 8601 calendar / clock arithmetic for Temporal (no VM access).
//!
//! Dates are proleptic Gregorian; epoch nanoseconds and time durations are
//! exact `i128` values.

use std::cmp::Ordering;

pub const NS_PER_SECOND: i128 = 1_000_000_000;
pub const NS_PER_MINUTE: i128 = 60 * NS_PER_SECOND;
pub const NS_PER_HOUR: i128 = 60 * NS_PER_MINUTE;
pub const NS_PER_DAY: i128 = 24 * NS_PER_HOUR;
/// nsMaxInstant = 10^8 days
pub const NS_MAX_INSTANT: i128 = 8_640_000_000_000_000_000_000;
pub const NS_MIN_INSTANT: i128 = -NS_MAX_INSTANT;
/// maxTimeDuration = 2^53 × 10^9 − 1
pub const MAX_TIME_DURATION: i128 = 9_007_199_254_740_992 * NS_PER_SECOND - 1;

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug, Hash)]
pub struct IsoDate {
    pub year: i64,
    pub month: u8,
    pub day: u8,
}

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug, Default, Hash)]
pub struct Time {
    pub hour: u8,
    pub minute: u8,
    pub second: u8,
    pub millisecond: u16,
    pub microsecond: u16,
    pub nanosecond: u16,
}

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug, Hash)]
pub struct IsoDateTime {
    pub date: IsoDate,
    pub time: Time,
}

impl IsoDate {
    pub fn new(year: i64, month: u8, day: u8) -> IsoDate {
        IsoDate { year, month, day }
    }
}

impl Time {
    pub const MIDNIGHT: Time = Time { hour: 0, minute: 0, second: 0, millisecond: 0, microsecond: 0, nanosecond: 0 };
    pub const NOON: Time = Time { hour: 12, minute: 0, second: 0, millisecond: 0, microsecond: 0, nanosecond: 0 };

    /// Nanoseconds since midnight.
    pub fn to_ns(&self) -> i128 {
        (((self.hour as i128 * 60 + self.minute as i128) * 60 + self.second as i128) * 1000 + self.millisecond as i128)
            * 1_000_000
            + self.microsecond as i128 * 1000
            + self.nanosecond as i128
    }

    /// Balance a (possibly negative / overflowing) count of nanoseconds since
    /// midnight into (days, time).
    pub fn balance(ns: i128) -> (i64, Time) {
        let days = ns.div_euclid(NS_PER_DAY);
        let mut r = ns.rem_euclid(NS_PER_DAY);
        let nanosecond = (r % 1000) as u16;
        r /= 1000;
        let microsecond = (r % 1000) as u16;
        r /= 1000;
        let millisecond = (r % 1000) as u16;
        r /= 1000;
        let second = (r % 60) as u8;
        r /= 60;
        let minute = (r % 60) as u8;
        r /= 60;
        let hour = r as u8;
        (days as i64, Time { hour, minute, second, millisecond, microsecond, nanosecond })
    }

    pub fn sub_second_ns(&self) -> u32 {
        self.millisecond as u32 * 1_000_000 + self.microsecond as u32 * 1000 + self.nanosecond as u32
    }
}

pub fn is_leap(y: i64) -> bool {
    y.rem_euclid(4) == 0 && (y.rem_euclid(100) != 0 || y.rem_euclid(400) == 0)
}

pub fn days_in_month(y: i64, m: u8) -> u8 {
    match m {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 => {
            if is_leap(y) {
                29
            } else {
                28
            }
        }
        _ => 30,
    }
}

pub fn days_in_year(y: i64) -> u16 {
    if is_leap(y) {
        366
    } else {
        365
    }
}

/// Days since 1970-01-01 (the date must be balanced).
pub fn epoch_days(d: IsoDate) -> i64 {
    crate::datetime::days_from_civil(d.year, d.month as u32, d.day as i64)
}

pub fn from_epoch_days(days: i64) -> IsoDate {
    let (y, m, d) = crate::datetime::civil_from_days(days);
    IsoDate { year: y, month: m as u8, day: d as u8 }
}

/// BalanceISOYearMonth(year, month)
pub fn balance_year_month(year: i64, month1: i64) -> (i64, u8) {
    let m0 = month1 - 1;
    (year + m0.div_euclid(12), (m0.rem_euclid(12) + 1) as u8)
}

pub fn add_days(d: IsoDate, days: i64) -> IsoDate {
    from_epoch_days(epoch_days(d) + days)
}

pub fn compare_date(a: &IsoDate, b: &IsoDate) -> Ordering {
    (a.year, a.month, a.day).cmp(&(b.year, b.month, b.day))
}

pub fn compare_datetime(a: &IsoDateTime, b: &IsoDateTime) -> Ordering {
    compare_date(&a.date, &b.date).then(a.time.cmp(&b.time))
}

pub fn is_valid_iso_date(year: i64, month: i64, day: i64) -> bool {
    (1..=12).contains(&month) && day >= 1 && day <= days_in_month(year, month as u8) as i64
}

/// GetUTCEpochNanoseconds
pub fn utc_epoch_ns(d: &IsoDate, t: &Time) -> i128 {
    epoch_days(*d) as i128 * NS_PER_DAY + t.to_ns()
}

pub fn utc_epoch_ns_dt(dt: &IsoDateTime) -> i128 {
    utc_epoch_ns(&dt.date, &dt.time)
}

pub fn epoch_ns_valid(ns: i128) -> bool {
    (NS_MIN_INSTANT..=NS_MAX_INSTANT).contains(&ns)
}

/// ISODateTimeWithinLimits
pub fn datetime_within_limits(d: &IsoDate, t: &Time) -> bool {
    if d.year.abs() > 300_000 {
        return false;
    }
    let days = epoch_days(*d);
    if days.abs() > 100_000_001 {
        return false;
    }
    let ns = utc_epoch_ns(d, t);
    ns > NS_MIN_INSTANT - NS_PER_DAY && ns < NS_MAX_INSTANT + NS_PER_DAY
}

/// ISODateWithinLimits
pub fn date_within_limits(d: &IsoDate) -> bool {
    datetime_within_limits(d, &Time::NOON)
}

/// ISOYearMonthWithinLimits
pub fn year_month_within_limits(d: &IsoDate) -> bool {
    if d.year < -271821 || d.year > 275760 {
        return false;
    }
    if d.year == -271821 && d.month < 4 {
        return false;
    }
    if d.year == 275760 && d.month > 9 {
        return false;
    }
    true
}

/// CheckISODaysRange: |epoch days| <= 10^8
pub fn days_in_range(d: &IsoDate) -> bool {
    d.year.abs() <= 300_000 && epoch_days(*d).abs() <= 100_000_000
}

/// Date-time of an epoch-nanoseconds value plus an offset.
pub fn datetime_from_epoch_ns(ns: i128) -> IsoDateTime {
    let days = ns.div_euclid(NS_PER_DAY);
    let rem = ns.rem_euclid(NS_PER_DAY);
    let (_, time) = Time::balance(rem);
    IsoDateTime { date: from_epoch_days(days as i64), time }
}

/// BalanceISODateTime(date, time + extra nanoseconds)
pub fn balance_datetime(d: &IsoDate, t: &Time, extra_ns: i128) -> IsoDateTime {
    let (days, time) = Time::balance(t.to_ns() + extra_ns);
    IsoDateTime { date: add_days(*d, days), time }
}

/// 1 = Monday ... 7 = Sunday
pub fn day_of_week(d: &IsoDate) -> u8 {
    // 1970-01-01 was a Thursday (4)
    ((epoch_days(*d) + 3).rem_euclid(7) + 1) as u8
}

pub fn day_of_year(d: &IsoDate) -> u16 {
    (epoch_days(*d) - crate::datetime::days_from_civil(d.year, 1, 1) + 1) as u16
}

/// ISO week number and week-year.
pub fn week_of_year(d: &IsoDate) -> (u8, i64) {
    let doy = day_of_year(d) as i64;
    let dow = day_of_week(d) as i64;
    let doj = day_of_week(&IsoDate::new(d.year, 1, 1)) as i64;
    let week = (doy - dow + 10).div_euclid(7);
    if week < 1 {
        if doj == 5 || (doj == 6 && is_leap(d.year - 1)) {
            return (53, d.year - 1);
        }
        return (52, d.year - 1);
    }
    if week == 53 && (days_in_year(d.year) as i64 - doy) < 4 - dow {
        return (1, d.year + 1);
    }
    (week as u8, d.year)
}

/// RegulateISODate with "constrain"
pub fn constrain_date(year: i64, month: i64, day: i64) -> IsoDate {
    let m = month.clamp(1, 12) as u8;
    let dim = days_in_month(year, m) as i64;
    IsoDate { year, month: m, day: day.clamp(1, dim) as u8 }
}

/// Exact quotient num/den (den > 0) rounded to the nearest f64 (ties to even).
pub fn div_to_f64(num: i128, den: i128) -> f64 {
    if den == 0 {
        return f64::NAN;
    }
    let neg = (num < 0) != (den < 0);
    let n = num.unsigned_abs();
    let d = den.unsigned_abs();
    let r = udiv_to_f64(n, d);
    if neg {
        -r
    } else {
        r
    }
}

fn bitlen(x: u128) -> u32 {
    128 - x.leading_zeros()
}

fn udiv_to_f64(n: u128, d: u128) -> f64 {
    if n == 0 {
        return 0.0;
    }
    let mut m = n / d;
    let mut rem = n % d;
    let mut e: i32 = 0;
    // collect at least 55 significant bits
    while bitlen(m) < 55 {
        // rem < d <= 2^127 so 2*rem fits
        let r2 = rem << 1;
        m <<= 1;
        if r2 >= d {
            m |= 1;
            rem = r2 - d;
        } else {
            rem = r2;
        }
        e -= 1;
        if e < -1200 {
            break;
        }
    }
    let sticky = rem != 0;
    let bl = bitlen(m);
    if bl > 53 {
        let extra = bl - 53;
        let low = m & ((1u128 << extra) - 1);
        let half = 1u128 << (extra - 1);
        m >>= extra;
        e += extra as i32;
        if low > half || (low == half && (sticky || (m & 1) == 1)) {
            m += 1;
        }
    }
    (m as f64) * 2f64.powi(e)
}

