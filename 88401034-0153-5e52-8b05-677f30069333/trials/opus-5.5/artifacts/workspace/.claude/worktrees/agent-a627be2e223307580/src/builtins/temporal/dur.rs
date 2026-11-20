//! Duration records and the difference / rounding algorithms
//! (DifferenceISODateTime, RoundRelativeDuration, Nudge*, Bubble*, ...).

use super::calendar::{self, Cal};
use super::iso::*;
use super::parse;
use super::tz::Tz;
use super::*;

pub const MSG_DUR_RANGE: &str = "duration is outside the valid range";
pub const MSG_DUR_FIELD_RANGE: &str = "duration field is outside the valid range";
pub const MSG_MIXED_SIGN: &str = "mixed-sign duration";

const TWO_32: f64 = 4294967296.0;

/// Temporal.Duration fields (float64 integers)
#[derive(Clone, Copy, Default, PartialEq, Debug)]
pub struct Dur {
    pub years: f64,
    pub months: f64,
    pub weeks: f64,
    pub days: f64,
    pub hours: f64,
    pub minutes: f64,
    pub seconds: f64,
    pub milliseconds: f64,
    pub microseconds: f64,
    pub nanoseconds: f64,
}

impl Dur {
    pub fn fields(&self) -> [f64; 10] {
        [
            self.years,
            self.months,
            self.weeks,
            self.days,
            self.hours,
            self.minutes,
            self.seconds,
            self.milliseconds,
            self.microseconds,
            self.nanoseconds,
        ]
    }

    pub fn from_fields(f: [f64; 10]) -> Dur {
        let z = |x: f64| x + 0.0;
        Dur {
            years: z(f[0]),
            months: z(f[1]),
            weeks: z(f[2]),
            days: z(f[3]),
            hours: z(f[4]),
            minutes: z(f[5]),
            seconds: z(f[6]),
            milliseconds: z(f[7]),
            microseconds: z(f[8]),
            nanoseconds: z(f[9]),
        }
    }

    /// DurationSign
    pub fn sign(&self) -> i32 {
        for v in self.fields() {
            if v < 0.0 {
                return -1;
            }
            if v > 0.0 {
                return 1;
            }
        }
        0
    }

    /// CreateNegatedTemporalDuration
    pub fn negated(&self) -> Dur {
        let mut f = self.fields();
        for v in f.iter_mut() {
            *v = -*v;
        }
        Dur::from_fields(f)
    }

    pub fn abs(&self) -> Dur {
        let mut f = self.fields();
        for v in f.iter_mut() {
            *v = v.abs();
        }
        Dur::from_fields(f)
    }

    /// IsValidDuration (with the original's messages)
    pub fn validate(&self) -> TRes<()> {
        let f = self.fields();
        let mut sign = 0;
        for v in f {
            if !v.is_finite() {
                return rerr("value must be finite");
            }
            if v > 0.0 {
                if sign < 0 {
                    return rerr(MSG_MIXED_SIGN);
                }
                sign = 1;
            } else if v < 0.0 {
                if sign > 0 {
                    return rerr(MSG_MIXED_SIGN);
                }
                sign = -1;
            }
        }
        if self.years.abs() >= TWO_32 || self.months.abs() >= TWO_32 || self.weeks.abs() >= TWO_32 {
            return rerr(MSG_DUR_FIELD_RANGE);
        }
        for v in &f[3..] {
            if v.abs() >= 1e30 {
                return rerr(MSG_DUR_RANGE);
            }
        }
        let total = self.days as i128 * NS_PER_DAY + time_from_components(self);
        if total.abs() >= 9_007_199_254_740_992 * NS_PER_SECOND {
            return rerr(MSG_DUR_RANGE);
        }
        Ok(())
    }

    /// DefaultTemporalLargestUnit
    pub fn default_largest_unit(&self) -> Unit {
        for (i, v) in self.fields().iter().enumerate() {
            if *v != 0.0 {
                return Unit::ALL[i];
            }
        }
        Unit::Nanosecond
    }

    /// ParseTemporalDurationString
    pub fn parse(s: &str) -> TRes<Dur> {
        let p = match parse::parse_duration(s) {
            Some(p) => p,
            None => return rerr("invalid duration"),
        };
        let k = if p.negative { -1.0 } else { 1.0 };
        let d = Dur::from_fields([
            p.years * k,
            p.months * k,
            p.weeks * k,
            p.days * k,
            p.hours * k,
            p.minutes * k,
            p.seconds * k,
            p.milliseconds * k,
            p.microseconds * k,
            p.nanoseconds * k,
        ]);
        d.validate()?;
        Ok(d)
    }

    /// TemporalDurationToString
    pub fn to_string_with(&self, precision: Precision) -> String {
        let sign = self.sign();
        let n = |v: f64| format!("{}", v.abs() as u128);
        let mut date = String::new();
        if self.years != 0.0 {
            date += &format!("{}Y", n(self.years));
        }
        if self.months != 0.0 {
            date += &format!("{}M", n(self.months));
        }
        if self.weeks != 0.0 {
            date += &format!("{}W", n(self.weeks));
        }
        if self.days != 0.0 {
            date += &format!("{}D", n(self.days));
        }
        let mut time = String::new();
        if self.hours != 0.0 {
            time += &format!("{}H", n(self.hours));
        }
        if self.minutes != 0.0 {
            time += &format!("{}M", n(self.minutes));
        }
        let zero_minutes_and_higher = self.fields()[..6].iter().all(|v| *v == 0.0);
        let secs = (self.seconds as i128 * NS_PER_SECOND
            + self.milliseconds as i128 * 1_000_000
            + self.microseconds as i128 * 1000
            + self.nanoseconds as i128)
            .abs();
        if secs != 0 || zero_minutes_and_higher || precision != Precision::Auto {
            let whole = secs / NS_PER_SECOND;
            let frac = (secs % NS_PER_SECOND) as u32;
            time += &format!("{}{}S", whole, fmt_fraction(frac, precision));
        }
        let mut r = String::new();
        if sign < 0 {
            r.push('-');
        }
        r.push('P');
        r += &date;
        if !time.is_empty() {
            r.push('T');
            r += &time;
        }
        r
    }
}

/// TimeDurationFromComponents(hours ... nanoseconds) of a valid duration
pub fn time_from_components(d: &Dur) -> i128 {
    d.hours as i128 * NS_PER_HOUR
        + d.minutes as i128 * NS_PER_MINUTE
        + d.seconds as i128 * NS_PER_SECOND
        + d.milliseconds as i128 * 1_000_000
        + d.microseconds as i128 * 1000
        + d.nanoseconds as i128
}

/// Date Duration Record
#[derive(Clone, Copy, Default, PartialEq, Eq, Debug)]
pub struct DateDur {
    pub years: i64,
    pub months: i64,
    pub weeks: i64,
    pub days: i64,
}

impl DateDur {
    pub fn new(years: i64, months: i64, weeks: i64, days: i64) -> DateDur {
        DateDur { years, months, weeks, days }
    }

    pub fn sign(&self) -> i64 {
        for v in [self.years, self.months, self.weeks, self.days] {
            if v != 0 {
                return v.signum();
            }
        }
        0
    }

    /// CreateDateDurationRecord validation
    pub fn validate(&self) -> TRes<DateDur> {
        let d = Dur {
            years: self.years as f64,
            months: self.months as f64,
            weeks: self.weeks as f64,
            days: self.days as f64,
            ..Dur::default()
        };
        d.validate()?;
        Ok(*self)
    }

    /// AdjustDateDurationRecord(days, weeks, months)
    pub fn adjust(&self, days: i64, weeks: Option<i64>, months: Option<i64>) -> TRes<DateDur> {
        DateDur {
            years: self.years,
            months: months.unwrap_or(self.months),
            weeks: weeks.unwrap_or(self.weeks),
            days,
        }
        .validate()
    }
}

/// Internal Duration Record
#[derive(Clone, Copy, Default, PartialEq, Eq, Debug)]
pub struct IDur {
    pub date: DateDur,
    pub time: i128,
}

impl IDur {
    pub fn sign(&self) -> i64 {
        let s = self.date.sign();
        if s != 0 {
            return s;
        }
        self.time.signum() as i64
    }
}

/// ToInternalDurationRecord
pub fn to_internal(d: &Dur) -> IDur {
    IDur {
        date: DateDur::new(d.years as i64, d.months as i64, d.weeks as i64, d.days as i64),
        time: time_from_components(d),
    }
}

/// ToInternalDurationRecordWith24HourDays
pub fn to_internal_24h(d: &Dur) -> TRes<IDur> {
    let t = add_24h_days(time_from_components(d), d.days as i64)?;
    Ok(IDur { date: DateDur::new(d.years as i64, d.months as i64, d.weeks as i64, 0), time: t })
}

/// ToDateDurationRecordWithoutTime
pub fn to_date_duration_without_time(d: &Dur) -> TRes<DateDur> {
    let i = to_internal_24h(d)?;
    let days = i.time / NS_PER_DAY;
    DateDur::new(i.date.years, i.date.months, i.date.weeks, days as i64).validate()
}

pub fn check_time(t: i128) -> TRes<i128> {
    if t.abs() > MAX_TIME_DURATION {
        return rerr(MSG_DUR_RANGE);
    }
    Ok(t)
}

/// Add24HourDaysToTimeDuration
pub fn add_24h_days(t: i128, days: i64) -> TRes<i128> {
    check_time(t + days as i128 * NS_PER_DAY)
}

/// AddTimeDuration
pub fn add_time(a: i128, b: i128) -> TRes<i128> {
    check_time(a + b)
}

/// TemporalDurationFromInternal
pub fn from_internal(i: &IDur, largest: Unit) -> TRes<Dur> {
    let sign = i.time.signum();
    let mut ns = i.time.abs();
    let (mut days, mut hours, mut minutes, mut seconds, mut ms, mut us) = (0i128, 0i128, 0i128, 0i128, 0i128, 0i128);
    match largest {
        Unit::Year | Unit::Month | Unit::Week | Unit::Day | Unit::Hour | Unit::Minute | Unit::Second | Unit::Millisecond | Unit::Microsecond => {
            us = ns / 1000;
            ns %= 1000;
            if largest != Unit::Microsecond {
                ms = us / 1000;
                us %= 1000;
                if largest != Unit::Millisecond {
                    seconds = ms / 1000;
                    ms %= 1000;
                    if largest != Unit::Second {
                        minutes = seconds / 60;
                        seconds %= 60;
                        if largest != Unit::Minute {
                            hours = minutes / 60;
                            minutes %= 60;
                            if largest != Unit::Hour {
                                days = hours / 24;
                                hours %= 24;
                            }
                        }
                    }
                }
            }
        }
        Unit::Nanosecond => {}
    }
    let f = |v: i128| (v * sign) as f64;
    let d = Dur::from_fields([
        i.date.years as f64,
        i.date.months as f64,
        i.date.weeks as f64,
        (i.date.days as i128 + days * sign) as f64,
        f(hours),
        f(minutes),
        f(seconds),
        f(ms),
        f(us),
        f(ns),
    ]);
    d.validate()?;
    Ok(d)
}

/// RoundTimeDurationToIncrement
pub fn round_time_to_increment(t: i128, increment: i128, mode: RoundingMode) -> TRes<i128> {
    check_time(round_to_increment(t, increment, mode))
}

/// RoundTimeDuration
pub fn round_time_duration(t: i128, increment: i128, unit: Unit, mode: RoundingMode) -> TRes<i128> {
    round_time_to_increment(t, unit.ns() * increment, mode)
}

/// TotalTimeDuration
pub fn total_time(t: i128, unit: Unit) -> f64 {
    div_to_f64(t, unit.ns())
}

// ---------------------------------------------------------------------------
// Differences
// ---------------------------------------------------------------------------

/// DifferenceTime
pub fn difference_time(a: &Time, b: &Time) -> i128 {
    b.to_ns() - a.to_ns()
}

/// DifferenceISODateTime
pub fn difference_iso_datetime(a: &IsoDateTime, b: &IsoDateTime, cal: Cal, largest: Unit) -> TRes<IDur> {
    let mut t = difference_time(&a.time, &b.time);
    let time_sign = t.signum() as i64;
    let date_sign = compare_date(&a.date, &b.date) as i64;
    let mut adjusted = b.date;
    if time_sign == date_sign && time_sign != 0 {
        adjusted = add_days(adjusted, time_sign);
        t = add_24h_days(t, -time_sign)?;
    }
    let date_largest = Unit::larger(Unit::Day, largest);
    let mut dd = calendar::date_until(cal, &a.date, &adjusted, date_largest);
    if largest != date_largest {
        t = add_24h_days(t, dd.days)?;
        dd.days = 0;
    }
    Ok(IDur { date: dd, time: t })
}

/// DifferenceZonedDateTime
pub fn difference_zoned(ns1: i128, ns2: i128, tz: &Tz, cal: Cal, largest: Unit) -> TRes<IDur> {
    if ns1 == ns2 {
        return Ok(IDur::default());
    }
    let start = tz.datetime_for(ns1);
    let end = tz.datetime_for(ns2);
    if compare_date(&start.date, &end.date) == std::cmp::Ordering::Equal {
        return Ok(IDur { date: DateDur::default(), time: ns2 - ns1 });
    }
    let sign: i64 = if ns2 - ns1 < 0 { -1 } else { 1 };
    let max_correction = if sign == 1 { 2 } else { 1 };
    let mut correction = 0;
    let t = difference_time(&start.time, &end.time);
    if t.signum() as i64 == -sign {
        correction += 1;
    }
    let mut success = false;
    let mut intermediate = start;
    let mut time = 0i128;
    while correction <= max_correction && !success {
        let idate = add_days(end.date, -correction * sign);
        intermediate = IsoDateTime { date: idate, time: start.time };
        let ins = tz.epoch_ns_for(&intermediate, Disambiguation::Compatible)?;
        time = ns2 - ins;
        if time.signum() as i64 != -sign {
            success = true;
        }
        correction += 1;
    }
    if !success {
        return rerr(MSG_DUR_RANGE);
    }
    let date_largest = Unit::larger(largest, Unit::Day);
    let dd = calendar::date_until(cal, &start.date, &intermediate.date, date_largest);
    Ok(IDur { date: dd, time })
}

struct Nudge {
    dur: IDur,
    nudged_ns: i128,
    expanded: bool,
}

fn epoch_for(tz: Option<&Tz>, d: &IsoDateTime) -> TRes<i128> {
    match tz {
        None => Ok(utc_epoch_ns_dt(d)),
        Some(tz) => tz.epoch_ns_for(d, Disambiguation::Compatible),
    }
}

/// NudgeToCalendarUnit → (nudge, total)
#[allow(clippy::too_many_arguments)]
fn nudge_to_calendar_unit(
    sign: i64,
    d: &IDur,
    dest_ns: i128,
    dt: &IsoDateTime,
    tz: Option<&Tz>,
    cal: Cal,
    increment: i64,
    unit: Unit,
    mode: RoundingMode,
) -> TRes<(Nudge, f64)> {
    let inc = increment as i128;
    let (r1, _r2, start_dur, end_dur) = match unit {
        Unit::Year => {
            let y = round_to_increment(d.date.years as i128, inc, RoundingMode::Trunc) as i64;
            let r2 = y + increment * sign;
            (y, r2, DateDur::new(y, 0, 0, 0).validate()?, DateDur::new(r2, 0, 0, 0).validate()?)
        }
        Unit::Month => {
            let m = round_to_increment(d.date.months as i128, inc, RoundingMode::Trunc) as i64;
            let r2 = m + increment * sign;
            (m, r2, d.date.adjust(0, Some(0), Some(m))?, d.date.adjust(0, Some(0), Some(r2))?)
        }
        Unit::Week => {
            let ym = d.date.adjust(0, Some(0), None)?;
            let weeks_start = calendar::date_add(cal, &dt.date, &ym, Overflow::Constrain)?;
            let weeks_end = add_days(weeks_start, d.date.days);
            let until = calendar::date_until(cal, &weeks_start, &weeks_end, Unit::Week);
            let w = round_to_increment((d.date.weeks + until.weeks) as i128, inc, RoundingMode::Trunc) as i64;
            let r2 = w + increment * sign;
            (w, r2, d.date.adjust(0, Some(w), None)?, d.date.adjust(0, Some(r2), None)?)
        }
        _ => {
            let dd = round_to_increment(d.date.days as i128, inc, RoundingMode::Trunc) as i64;
            let r2 = dd + increment * sign;
            (dd, r2, d.date.adjust(dd, None, None)?, d.date.adjust(r2, None, None)?)
        }
    };
    let (mut r1, mut start_dur, mut end_dur) = (r1, start_dur, end_dur);
    let start = calendar::date_add(cal, &dt.date, &start_dur, Overflow::Constrain)?;
    let end = calendar::date_add(cal, &dt.date, &end_dur, Overflow::Constrain)?;
    let mut start_ns = epoch_for(tz, &IsoDateTime { date: start, time: dt.time })?;
    let mut end_ns = epoch_for(tz, &IsoDateTime { date: end, time: dt.time })?;
    // When the duration's calendar part was clamped (month ends) the
    // destination can lie beyond `end`; the original then moves on to the
    // next interval.
    let mut guard = 0;
    while guard < 4 && ((sign == 1 && dest_ns > end_ns) || (sign == -1 && dest_ns < end_ns)) {
        guard += 1;
        r1 += increment * sign;
        start_dur = end_dur;
        let r2n = r1 + increment * sign;
        end_dur = match unit {
            Unit::Year => DateDur::new(r2n, 0, 0, 0).validate()?,
            Unit::Month => d.date.adjust(0, Some(0), Some(r2n))?,
            Unit::Week => d.date.adjust(0, Some(r2n), None)?,
            _ => d.date.adjust(r2n, None, None)?,
        };
        start_ns = end_ns;
        let end = calendar::date_add(cal, &dt.date, &end_dur, Overflow::Constrain)?;
        end_ns = epoch_for(tz, &IsoDateTime { date: end, time: dt.time })?;
    }
    if sign == 1 {
        if !(start_ns <= dest_ns && dest_ns <= end_ns) {
            return rerr(MSG_DUR_RANGE);
        }
    } else if !(end_ns <= dest_ns && dest_ns <= start_ns) {
        return rerr(MSG_DUR_RANGE);
    }
    if end_ns == start_ns {
        return rerr(MSG_DUR_RANGE);
    }
    let num = dest_ns - start_ns;
    let den = end_ns - start_ns;
    let total = div_to_f64(r1 as i128 * den + num * inc * sign as i128, den);
    let um = unsigned_mode(mode, sign < 0);
    let upper = if num == den { true } else { choose_upper(num.abs(), den.abs(), um, (r1.abs() / increment) % 2 == 0) };
    let n = if upper {
        Nudge { dur: IDur { date: end_dur, time: 0 }, nudged_ns: end_ns, expanded: true }
    } else {
        Nudge { dur: IDur { date: start_dur, time: 0 }, nudged_ns: start_ns, expanded: false }
    };
    Ok((n, total))
}

/// NudgeToZonedTime
#[allow(clippy::too_many_arguments)]
fn nudge_to_zoned_time(
    sign: i64,
    d: &IDur,
    dt: &IsoDateTime,
    tz: &Tz,
    cal: Cal,
    increment: i64,
    unit: Unit,
    mode: RoundingMode,
) -> TRes<Nudge> {
    let start = calendar::date_add(cal, &dt.date, &d.date, Overflow::Constrain)?;
    let end_date = add_days(start, sign);
    let start_ns = tz.epoch_ns_for(&IsoDateTime { date: start, time: dt.time }, Disambiguation::Compatible)?;
    let end_ns = tz.epoch_ns_for(&IsoDateTime { date: end_date, time: dt.time }, Disambiguation::Compatible)?;
    let day_span = end_ns - start_ns;
    let step = increment as i128 * unit.ns();
    let mut rounded = round_time_to_increment(d.time, step, mode)?;
    let beyond = add_time(rounded, -day_span)?;
    let (expanded, day_delta, nudged) = if beyond.signum() as i64 != -sign {
        rounded = round_time_to_increment(beyond, step, mode)?;
        (true, sign, rounded + end_ns)
    } else {
        (false, 0, rounded + start_ns)
    };
    let date = d.date.adjust(d.date.days + day_delta, None, None)?;
    Ok(Nudge { dur: IDur { date, time: rounded }, nudged_ns: nudged, expanded })
}

/// NudgeToDayOrTime
fn nudge_to_day_or_time(d: &IDur, dest_ns: i128, largest: Unit, increment: i64, smallest: Unit, mode: RoundingMode) -> TRes<Nudge> {
    let time = add_24h_days(d.time, d.date.days)?;
    let rounded = round_time_to_increment(time, smallest.ns() * increment as i128, mode)?;
    let diff = add_time(rounded, -time)?;
    let whole_days = time / NS_PER_DAY;
    let rounded_whole_days = rounded / NS_PER_DAY;
    let day_delta = rounded_whole_days - whole_days;
    let expanded = day_delta.signum() == time.signum();
    let nudged = diff + dest_ns;
    let (days, remainder) = if largest.is_date() {
        (rounded_whole_days, add_time(rounded, -rounded_whole_days * NS_PER_DAY)?)
    } else {
        (0, rounded)
    };
    let date = d.date.adjust(days as i64, None, None)?;
    Ok(Nudge { dur: IDur { date, time: remainder }, nudged_ns: nudged, expanded })
}

/// BubbleRelativeDuration
#[allow(clippy::too_many_arguments)]
fn bubble_relative(
    sign: i64,
    d: IDur,
    nudged_ns: i128,
    dt: &IsoDateTime,
    tz: Option<&Tz>,
    cal: Cal,
    largest: Unit,
    smallest: Unit,
) -> TRes<IDur> {
    if smallest == largest {
        return Ok(d);
    }
    let mut d = d;
    let mut idx = smallest as i64 - 1;
    while idx >= largest as i64 {
        let unit = Unit::ALL[idx as usize];
        idx -= 1;
        if unit == Unit::Week && largest != Unit::Week {
            continue;
        }
        let end_dur = match unit {
            Unit::Year => DateDur::new(d.date.years + sign, 0, 0, 0).validate()?,
            Unit::Month => d.date.adjust(0, Some(0), Some(d.date.months + sign))?,
            _ => d.date.adjust(0, Some(d.date.weeks + sign), None)?,
        };
        let end = calendar::date_add(cal, &dt.date, &end_dur, Overflow::Constrain)?;
        let end_ns = epoch_for(tz, &IsoDateTime { date: end, time: dt.time })?;
        let beyond = nudged_ns - end_ns;
        if beyond.signum() as i64 != -sign {
            d = IDur { date: end_dur, time: 0 };
        } else {
            break;
        }
    }
    Ok(d)
}

/// RoundRelativeDuration
#[allow(clippy::too_many_arguments)]
pub fn round_relative(
    d: IDur,
    dest_ns: i128,
    dt: &IsoDateTime,
    tz: Option<&Tz>,
    cal: Cal,
    largest: Unit,
    increment: i64,
    smallest: Unit,
    mode: RoundingMode,
) -> TRes<IDur> {
    let irregular = smallest.is_calendar() || (tz.is_some() && smallest == Unit::Day);
    let sign = if d.sign() < 0 { -1 } else { 1 };
    let nudge = if irregular {
        nudge_to_calendar_unit(sign, &d, dest_ns, dt, tz, cal, increment, smallest, mode)?.0
    } else if let Some(tz) = tz {
        nudge_to_zoned_time(sign, &d, dt, tz, cal, increment, smallest, mode)?
    } else {
        nudge_to_day_or_time(&d, dest_ns, largest, increment, smallest, mode)?
    };
    let mut r = nudge.dur;
    if nudge.expanded {
        let start_unit = Unit::larger(smallest, Unit::Day);
        r = bubble_relative(sign, r, nudge.nudged_ns, dt, tz, cal, largest, start_unit)?;
    }
    Ok(r)
}

/// TotalRelativeDuration
pub fn total_relative(d: IDur, dest_ns: i128, dt: &IsoDateTime, tz: Option<&Tz>, cal: Cal, unit: Unit) -> TRes<f64> {
    if unit.is_calendar() || (tz.is_some() && unit == Unit::Day) {
        let sign = if d.sign() < 0 { -1 } else { 1 };
        let (_, total) = nudge_to_calendar_unit(sign, &d, dest_ns, dt, tz, cal, 1, unit, RoundingMode::Trunc)?;
        return Ok(total);
    }
    let t = add_24h_days(d.time, d.date.days)?;
    Ok(total_time(t, unit))
}

/// DifferencePlainDateTimeWithRounding
#[allow(clippy::too_many_arguments)]
pub fn difference_plain_datetime_with_rounding(
    a: &IsoDateTime,
    b: &IsoDateTime,
    cal: Cal,
    largest: Unit,
    increment: i64,
    smallest: Unit,
    mode: RoundingMode,
) -> TRes<IDur> {
    if compare_datetime(a, b) == std::cmp::Ordering::Equal {
        return Ok(IDur::default());
    }
    if !datetime_within_limits(&a.date, &a.time) || !datetime_within_limits(&b.date, &b.time) {
        return rerr("date-time is outside the supported range");
    }
    let diff = difference_iso_datetime(a, b, cal, largest)?;
    if smallest == Unit::Nanosecond && increment == 1 {
        return Ok(diff);
    }
    let dest = utc_epoch_ns_dt(b);
    round_relative(diff, dest, a, None, cal, largest, increment, smallest, mode)
}

/// DifferencePlainDateTimeWithTotal
pub fn difference_plain_datetime_with_total(a: &IsoDateTime, b: &IsoDateTime, cal: Cal, unit: Unit) -> TRes<f64> {
    if compare_datetime(a, b) == std::cmp::Ordering::Equal {
        return Ok(0.0);
    }
    if !datetime_within_limits(&a.date, &a.time) || !datetime_within_limits(&b.date, &b.time) {
        return rerr("date-time is outside the supported range");
    }
    let diff = difference_iso_datetime(a, b, cal, unit)?;
    if unit == Unit::Nanosecond {
        return Ok(diff.time as f64);
    }
    let dest = utc_epoch_ns_dt(b);
    total_relative(diff, dest, a, None, cal, unit)
}

/// DifferenceInstant
pub fn difference_instant(ns1: i128, ns2: i128, increment: i64, smallest: Unit, mode: RoundingMode) -> TRes<IDur> {
    let t = round_time_duration(ns2 - ns1, increment as i128, smallest, mode)?;
    Ok(IDur { date: DateDur::default(), time: t })
}

/// DifferenceZonedDateTimeWithRounding
#[allow(clippy::too_many_arguments)]
pub fn difference_zoned_with_rounding(
    ns1: i128,
    ns2: i128,
    tz: &Tz,
    cal: Cal,
    largest: Unit,
    increment: i64,
    smallest: Unit,
    mode: RoundingMode,
) -> TRes<IDur> {
    if !largest.is_date() {
        return difference_instant(ns1, ns2, increment, smallest, mode);
    }
    let diff = difference_zoned(ns1, ns2, tz, cal, largest)?;
    if smallest == Unit::Nanosecond && increment == 1 {
        return Ok(diff);
    }
    let dt = tz.datetime_for(ns1);
    round_relative(diff, ns2, &dt, Some(tz), cal, largest, increment, smallest, mode)
}

/// DifferenceZonedDateTimeWithTotal
pub fn difference_zoned_with_total(ns1: i128, ns2: i128, tz: &Tz, cal: Cal, unit: Unit) -> TRes<f64> {
    if !unit.is_date() {
        return Ok(total_time(ns2 - ns1, unit));
    }
    let diff = difference_zoned(ns1, ns2, tz, cal, unit)?;
    let dt = tz.datetime_for(ns1);
    total_relative(diff, ns2, &dt, Some(tz), cal, unit)
}

/// AddInstant
pub fn add_instant(ns: i128, t: i128) -> TRes<i128> {
    let r = ns + t;
    if !epoch_ns_valid(r) {
        return rerr(MSG_INSTANT_RANGE);
    }
    Ok(r)
}

/// AddZonedDateTime
pub fn add_zoned(ns: i128, tz: &Tz, cal: Cal, d: &IDur, overflow: Overflow) -> TRes<i128> {
    if d.date.sign() == 0 {
        return add_instant(ns, d.time);
    }
    let dt = tz.datetime_for(ns);
    let added = calendar::date_add(cal, &dt.date, &d.date, overflow)?;
    let inter = IsoDateTime { date: added, time: dt.time };
    if !datetime_within_limits(&inter.date, &inter.time) {
        return rerr(MSG_DATETIME_RANGE);
    }
    let ins = tz.epoch_ns_for(&inter, Disambiguation::Compatible)?;
    add_instant(ins, d.time)
}
