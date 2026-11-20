//! ISO 8601 / RFC 9557 string parsing for Temporal (no VM access).
//!
//! The grammar follows the Temporal specification.  Each `parse_*` entry
//! point must consume the whole string; callers decide which forms they
//! accept and produce their own error messages.

use super::iso::{days_in_month, is_valid_iso_date, Time};

#[derive(Clone, Debug, Default)]
#[allow(dead_code)]
pub struct Offset {
    /// signed offset in nanoseconds
    pub ns: i128,
    /// written with seconds (sub-minute precision)
    pub has_seconds: bool,
    pub text: String,
}

#[derive(Clone, Debug)]
#[allow(dead_code)]
pub struct TzAnnotation {
    pub critical: bool,
    pub text: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Copy)]
pub enum Form {
    /// Date [T Time [offset]]
    DateTime,
    /// YYYY-MM
    YearMonth,
    /// [--]MM-DD
    MonthDay,
    /// [T] Time [offset]
    Time,
}

#[derive(Clone, Debug)]
pub struct Parsed {
    pub form: Form,
    pub year: Option<i64>,
    pub month: u8,
    pub day: Option<u8>,
    pub time: Option<Time>,
    /// a time designator (T/t) preceded the time (Time form only)
    pub has_designator: bool,
    pub z: bool,
    pub offset: Option<Offset>,
    pub tz: Option<TzAnnotation>,
    pub calendar: Option<String>,
    /// byte length of the "Time UTCOffset" part (Time form, for ambiguity checks)
    pub time_part_end: usize,
}

impl Parsed {
    fn new(form: Form) -> Parsed {
        Parsed {
            form,
            year: None,
            month: 1,
            day: None,
            time: None,
            has_designator: false,
            z: false,
            offset: None,
            tz: None,
            calendar: None,
            time_part_end: 0,
        }
    }
}

struct Cur<'a> {
    b: &'a [u8],
    i: usize,
}

impl<'a> Cur<'a> {
    fn peek(&self) -> Option<u8> {
        self.b.get(self.i).copied()
    }
    fn peek_at(&self, k: usize) -> Option<u8> {
        self.b.get(self.i + k).copied()
    }
    fn eat(&mut self, c: u8) -> bool {
        if self.peek() == Some(c) {
            self.i += 1;
            true
        } else {
            false
        }
    }
    fn done(&self) -> bool {
        self.i >= self.b.len()
    }
    fn digits(&mut self, n: usize) -> Option<i64> {
        let mut v: i64 = 0;
        for k in 0..n {
            let c = self.peek_at(k)?;
            if !c.is_ascii_digit() {
                return None;
            }
            v = v * 10 + (c - b'0') as i64;
        }
        self.i += n;
        Some(v)
    }
    fn is_digit_at(&self, k: usize) -> bool {
        self.peek_at(k).map_or(false, |c| c.is_ascii_digit())
    }
}

fn parse_year(c: &mut Cur) -> Option<i64> {
    match c.peek()? {
        b'+' | b'-' => {
            let neg = c.peek() == Some(b'-');
            let save = c.i;
            c.i += 1;
            match c.digits(6) {
                Some(v) => {
                    if neg && v == 0 {
                        c.i = save;
                        return None;
                    }
                    Some(if neg { -v } else { v })
                }
                None => {
                    c.i = save;
                    None
                }
            }
        }
        _ => c.digits(4),
    }
}

fn parse_month(c: &mut Cur) -> Option<u8> {
    let save = c.i;
    let v = c.digits(2)?;
    if (1..=12).contains(&v) {
        Some(v as u8)
    } else {
        c.i = save;
        None
    }
}

fn parse_day(c: &mut Cur) -> Option<u8> {
    let save = c.i;
    let v = c.digits(2)?;
    if (1..=31).contains(&v) {
        Some(v as u8)
    } else {
        c.i = save;
        None
    }
}

/// Date: YYYY-MM-DD | YYYYMMDD (validated)
fn parse_date(c: &mut Cur) -> Option<(i64, u8, u8)> {
    let save = c.i;
    let r = (|| {
        let y = parse_year(c)?;
        let ext = c.eat(b'-');
        let m = parse_month(c)?;
        if ext {
            if !c.eat(b'-') {
                return None;
            }
        } else if c.peek() == Some(b'-') {
            return None;
        }
        let d = parse_day(c)?;
        Some((y, m, d))
    })();
    match r {
        Some((y, m, d)) if is_valid_iso_date(y, m as i64, d as i64) => Some((y, m, d)),
        _ => {
            c.i = save;
            None
        }
    }
}

fn parse_fraction(c: &mut Cur) -> Option<Option<u32>> {
    // returns Some(None) if there is no fraction, Some(Some(ns)) if valid,
    // None on a malformed fraction
    match c.peek() {
        Some(b'.') | Some(b',') => {
            let st = c.i + 1;
            let mut k = st;
            while k < c.b.len() && c.b[k].is_ascii_digit() {
                k += 1;
            }
            let n = k - st;
            if n == 0 || n > 9 {
                return None;
            }
            let mut v: u32 = 0;
            for j in 0..9 {
                let d = if j < n { (c.b[st + j] - b'0') as u32 } else { 0 };
                v = v * 10 + d;
            }
            c.i = k;
            Some(Some(v))
        }
        _ => Some(None),
    }
}

fn two_digit_hour(c: &mut Cur) -> Option<u8> {
    let save = c.i;
    let v = c.digits(2)?;
    if v <= 23 {
        Some(v as u8)
    } else {
        c.i = save;
        None
    }
}

fn minute_second(c: &mut Cur) -> Option<u8> {
    let save = c.i;
    let v = c.digits(2)?;
    if v <= 59 {
        Some(v as u8)
    } else {
        c.i = save;
        None
    }
}

/// Time: HH[[:]MM[[:]SS[.fff]]] with consistent separators
fn parse_time(c: &mut Cur) -> Option<Time> {
    let save = c.i;
    let r = (|| {
        let h = two_digit_hour(c)?;
        let mut t = Time { hour: h, ..Time::default() };
        let ext = if c.peek() == Some(b':') {
            true
        } else if c.is_digit_at(0) {
            false
        } else {
            return Some(t);
        };
        if ext {
            c.i += 1;
        }
        t.minute = minute_second(c)?;
        let has_sec = if ext {
            if c.peek() == Some(b':') {
                c.i += 1;
                true
            } else {
                false
            }
        } else {
            c.is_digit_at(0)
        };
        if !has_sec {
            if ext && c.is_digit_at(0) {
                return None;
            }
            return Some(t);
        }
        let s = c.digits(2)?;
        if s > 60 {
            return None;
        }
        t.second = if s == 60 { 59 } else { s as u8 };
        if let Some(f) = parse_fraction(c)? {
            t.millisecond = (f / 1_000_000) as u16;
            t.microsecond = (f / 1000 % 1000) as u16;
            t.nanosecond = (f % 1000) as u16;
        }
        Some(t)
    })();
    if r.is_none() {
        c.i = save;
    }
    r
}

/// UTCOffset with optional sub-minute precision: ±HH[[:]MM[[:]SS[.f]]]
fn parse_offset(c: &mut Cur, allow_sub_minute: bool) -> Option<Offset> {
    let save = c.i;
    let r = (|| {
        let sign: i128 = match c.peek()? {
            b'+' => 1,
            b'-' => -1,
            _ => return None,
        };
        c.i += 1;
        let h = two_digit_hour(c)?;
        let mut ns = h as i128 * 3_600_000_000_000;
        let mut has_seconds = false;
        let ext = if c.peek() == Some(b':') {
            true
        } else if c.is_digit_at(0) {
            false
        } else {
            return Some((sign, ns, has_seconds));
        };
        if ext {
            c.i += 1;
        }
        let m = minute_second(c)?;
        ns += m as i128 * 60_000_000_000;
        let more = if ext { c.peek() == Some(b':') } else { c.is_digit_at(0) };
        if !more {
            if !ext && c.is_digit_at(0) {
                return None;
            }
            return Some((sign, ns, has_seconds));
        }
        if !allow_sub_minute {
            return None;
        }
        if ext {
            c.i += 1;
        }
        let s = minute_second(c)?;
        ns += s as i128 * 1_000_000_000;
        has_seconds = true;
        if let Some(f) = parse_fraction(c)? {
            ns += f as i128;
        }
        Some((sign, ns, has_seconds))
    })();
    match r {
        Some((sign, ns, has_seconds)) => {
            let text = String::from_utf8_lossy(&c.b[save..c.i]).to_string();
            Some(Offset { ns: sign * ns, has_seconds, text })
        }
        None => {
            c.i = save;
            None
        }
    }
}

fn is_tz_leading(c: u8) -> bool {
    c.is_ascii_alphabetic() || c == b'.' || c == b'_'
}

fn is_tz_char(c: u8) -> bool {
    is_tz_leading(c) || c.is_ascii_digit() || c == b'-' || c == b'+'
}

/// TimeZoneIANAName
pub fn is_iana_name_syntax(s: &[u8]) -> bool {
    if s.is_empty() {
        return false;
    }
    for comp in s.split(|&c| c == b'/') {
        if comp.is_empty() || !is_tz_leading(comp[0]) || !comp.iter().all(|&c| is_tz_char(c)) {
            return false;
        }
    }
    true
}

fn is_akey_leading(c: u8) -> bool {
    c.is_ascii_lowercase() || c == b'_'
}

fn is_akey_char(c: u8) -> bool {
    is_akey_leading(c) || c.is_ascii_digit() || c == b'-'
}

/// AnnotationValue: alnum+ ("-" alnum+)*
pub fn is_annotation_value(s: &[u8]) -> bool {
    !s.is_empty() && s.split(|&c| c == b'-').all(|p| !p.is_empty() && p.iter().all(|c| c.is_ascii_alphanumeric()))
}

/// Parse the trailing [time zone] and [key=value] annotations.
fn parse_annotations(c: &mut Cur, p: &mut Parsed) -> Option<()> {
    let mut first = true;
    let mut calendar_critical = false;
    while c.peek() == Some(b'[') {
        let start = c.i + 1;
        let end = start + c.b[start..].iter().position(|&x| x == b']')?;
        let mut content = &c.b[start..end];
        let critical = content.first() == Some(&b'!');
        if critical {
            content = &content[1..];
        }
        if let Some(eq) = content.iter().position(|&x| x == b'=') {
            let key = &content[..eq];
            let value = &content[eq + 1..];
            if key.is_empty() || !is_akey_leading(key[0]) || !key.iter().all(|&x| is_akey_char(x)) {
                return None;
            }
            if !is_annotation_value(value) {
                return None;
            }
            if key == b"u-ca" {
                if p.calendar.is_none() {
                    p.calendar = Some(String::from_utf8_lossy(value).to_string());
                    calendar_critical = critical;
                } else if critical || calendar_critical {
                    return None;
                }
            } else if critical {
                return None;
            }
        } else {
            // time zone annotation: only one, before any other annotation
            if !first {
                return None;
            }
            let ok = if matches!(content.first(), Some(b'+') | Some(b'-')) {
                let mut cc = Cur { b: content, i: 0 };
                parse_offset(&mut cc, true).is_some() && cc.done()
            } else {
                is_iana_name_syntax(content)
            };
            if !ok {
                return None;
            }
            p.tz = Some(TzAnnotation { critical, text: String::from_utf8_lossy(content).to_string() });
        }
        first = false;
        c.i = end + 1;
    }
    Some(())
}

fn parse_utc_offset_or_z(c: &mut Cur, p: &mut Parsed) -> Option<()> {
    match c.peek() {
        Some(b'Z') | Some(b'z') => {
            c.i += 1;
            p.z = true;
        }
        Some(b'+') | Some(b'-') => {
            p.offset = Some(parse_offset(c, true)?);
        }
        _ => {}
    }
    Some(())
}

/// Date [ (T|t|space) Time [Z|offset] ] [annotations]
pub fn parse_date_time(s: &str) -> Option<Parsed> {
    let mut c = Cur { b: s.as_bytes(), i: 0 };
    let mut p = Parsed::new(Form::DateTime);
    let (y, m, d) = parse_date(&mut c)?;
    p.year = Some(y);
    p.month = m;
    p.day = Some(d);
    if matches!(c.peek(), Some(b'T') | Some(b't') | Some(b' ')) {
        c.i += 1;
        p.time = Some(parse_time(&mut c)?);
        parse_utc_offset_or_z(&mut c, &mut p)?;
    }
    parse_annotations(&mut c, &mut p)?;
    if !c.done() {
        return None;
    }
    Some(p)
}

/// DateSpecYearMonth [annotations]
pub fn parse_year_month(s: &str) -> Option<Parsed> {
    let mut c = Cur { b: s.as_bytes(), i: 0 };
    let mut p = Parsed::new(Form::YearMonth);
    let y = parse_year(&mut c)?;
    c.eat(b'-');
    let m = parse_month(&mut c)?;
    p.year = Some(y);
    p.month = m;
    parse_annotations(&mut c, &mut p)?;
    if !c.done() {
        return None;
    }
    Some(p)
}

fn month_day_prefix(c: &mut Cur) -> Option<(u8, u8)> {
    if c.peek() == Some(b'-') && c.peek_at(1) == Some(b'-') {
        c.i += 2;
    }
    let m = parse_month(c)?;
    c.eat(b'-');
    let d = parse_day(c)?;
    let max = if m == 2 { 29 } else { days_in_month(1972, m) };
    if d > max {
        return None;
    }
    Some((m, d))
}

/// DateSpecMonthDay [annotations]
pub fn parse_month_day(s: &str) -> Option<Parsed> {
    let mut c = Cur { b: s.as_bytes(), i: 0 };
    let mut p = Parsed::new(Form::MonthDay);
    let (m, d) = month_day_prefix(&mut c)?;
    p.month = m;
    p.day = Some(d);
    parse_annotations(&mut c, &mut p)?;
    if !c.done() {
        return None;
    }
    Some(p)
}

/// [T] Time [Z|offset] [annotations]
pub fn parse_time_only(s: &str) -> Option<Parsed> {
    let mut c = Cur { b: s.as_bytes(), i: 0 };
    let mut p = Parsed::new(Form::Time);
    if matches!(c.peek(), Some(b'T') | Some(b't')) {
        c.i += 1;
        p.has_designator = true;
    }
    p.time = Some(parse_time(&mut c)?);
    parse_utc_offset_or_z(&mut c, &mut p)?;
    p.time_part_end = c.i;
    parse_annotations(&mut c, &mut p)?;
    if !c.done() {
        return None;
    }
    Some(p)
}

/// Is the "Time UTCOffset" part of an undesignated time string also a valid
/// DateSpecMonthDay or DateSpecYearMonth?
pub fn time_is_ambiguous(s: &str, p: &Parsed) -> bool {
    if p.has_designator {
        return false;
    }
    let part = &s[..p.time_part_end];
    let b = part.as_bytes();
    // DateSpecYearMonth
    {
        let mut c = Cur { b, i: 0 };
        if parse_year(&mut c).is_some() {
            c.eat(b'-');
            if parse_month(&mut c).is_some() && c.done() {
                return true;
            }
        }
    }
    {
        let mut c = Cur { b, i: 0 };
        if month_day_prefix(&mut c).is_some() && c.done() {
            return true;
        }
    }
    false
}

/// Exactly a UTC offset string (DateTimeUTCOffset, sub-minute allowed)
pub fn parse_offset_string(s: &str, allow_sub_minute: bool) -> Option<Offset> {
    let mut c = Cur { b: s.as_bytes(), i: 0 };
    let o = parse_offset(&mut c, allow_sub_minute)?;
    if !c.done() {
        return None;
    }
    Some(o)
}

/// Date-time or time forms, as the original accepts them for calendar and
/// time zone strings (no year-month / month-day forms, no ambiguity check).
pub fn parse_dt_or_time(s: &str) -> Option<Parsed> {
    parse_date_time(s).or_else(|| parse_time_only(s))
}

/// Parsed duration string fields (unsigned magnitudes + sign).
#[derive(Clone, Debug, Default)]
pub struct DurationParts {
    pub negative: bool,
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

fn digits_value(d: &[u8]) -> f64 {
    // decimal digit string -> nearest f64 (exact for <= 2^53)
    let s = std::str::from_utf8(d).unwrap_or("0");
    s.parse::<f64>().unwrap_or(0.0)
}

/// ISO 8601 duration: [+-]P[nY][nM][nW][nD][T[nH][nM][nS]] with an optional
/// fraction on the last time component.
pub fn parse_duration(s: &str) -> Option<DurationParts> {
    let b = s.as_bytes();
    let mut i = 0;
    let mut r = DurationParts::default();
    if i < b.len() && (b[i] == b'+' || b[i] == b'-') {
        r.negative = b[i] == b'-';
        i += 1;
    }
    if i >= b.len() || !(b[i] == b'P' || b[i] == b'p') {
        return None;
    }
    i += 1;
    let mut any = false;
    // date part
    let date_designators = [b'Y', b'M', b'W', b'D'];
    let mut next_date = 0;
    let mut in_time = false;
    let mut next_time = 0;
    let time_designators = [b'H', b'M', b'S'];
    let mut time_any = false;
    let mut had_fraction = false;
    // fraction handling: total nanoseconds contributed by a fraction
    while i < b.len() {
        let c = b[i];
        if c == b'T' || c == b't' {
            if in_time {
                return None;
            }
            in_time = true;
            i += 1;
            continue;
        }
        if had_fraction {
            return None;
        }
        let st = i;
        while i < b.len() && b[i].is_ascii_digit() {
            i += 1;
        }
        if i == st {
            return None;
        }
        let int_digits = &b[st..i];
        let mut frac: Option<(u64, u32)> = None;
        if i < b.len() && (b[i] == b'.' || b[i] == b',') {
            let fs = i + 1;
            let mut k = fs;
            while k < b.len() && b[k].is_ascii_digit() {
                k += 1;
            }
            let n = k - fs;
            if n == 0 || n > 9 {
                return None;
            }
            let mut v: u64 = 0;
            for j in 0..n {
                v = v * 10 + (b[fs + j] - b'0') as u64;
            }
            frac = Some((v, n as u32));
            i = k;
        }
        if i >= b.len() {
            return None;
        }
        let d = b[i].to_ascii_uppercase();
        i += 1;
        let v = digits_value(int_digits);
        if !in_time {
            if frac.is_some() {
                return None;
            }
            let pos = date_designators.iter().position(|&x| x == d)?;
            if pos < next_date {
                return None;
            }
            next_date = pos + 1;
            match pos {
                0 => r.years = v,
                1 => r.months = v,
                2 => r.weeks = v,
                _ => r.days = v,
            }
            any = true;
        } else {
            let pos = time_designators.iter().position(|&x| x == d)?;
            if pos < next_time {
                return None;
            }
            next_time = pos + 1;
            time_any = true;
            any = true;
            // fraction contribution in nanoseconds
            let unit_ns: u128 = match pos {
                0 => 3_600_000_000_000,
                1 => 60_000_000_000,
                _ => 1_000_000_000,
            };
            let frac_ns: u128 = match frac {
                Some((fv, n)) => {
                    had_fraction = true;
                    (fv as u128) * unit_ns / 10u128.pow(n)
                }
                None => 0,
            };
            match pos {
                0 => {
                    r.hours = v;
                    let mins = frac_ns / 60_000_000_000;
                    let rem = frac_ns % 60_000_000_000;
                    r.minutes = mins as f64;
                    r.seconds = (rem / 1_000_000_000) as f64;
                    let rem = rem % 1_000_000_000;
                    r.milliseconds = (rem / 1_000_000) as f64;
                    r.microseconds = (rem / 1000 % 1000) as f64;
                    r.nanoseconds = (rem % 1000) as f64;
                }
                1 => {
                    r.minutes = v;
                    r.seconds = (frac_ns / 1_000_000_000) as f64;
                    let rem = frac_ns % 1_000_000_000;
                    r.milliseconds = (rem / 1_000_000) as f64;
                    r.microseconds = (rem / 1000 % 1000) as f64;
                    r.nanoseconds = (rem % 1000) as f64;
                }
                _ => {
                    r.seconds = v;
                    r.milliseconds = (frac_ns / 1_000_000) as f64;
                    r.microseconds = (frac_ns / 1000 % 1000) as f64;
                    r.nanoseconds = (frac_ns % 1000) as f64;
                }
            }
        }
    }
    if !any || (in_time && !time_any) {
        return None;
    }
    Some(r)
}
