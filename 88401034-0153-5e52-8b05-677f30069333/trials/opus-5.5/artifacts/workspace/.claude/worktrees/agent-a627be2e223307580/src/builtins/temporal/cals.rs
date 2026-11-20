//! Non-Gregorian calendars: hebrew, chinese, dangi, islamic-civil,
//! islamic-tbla, islamic-umalqura, persian, indian, coptic, ethiopic,
//! ethioaa.
//!
//! Every calendar year is described by a `Layout` (first day as epoch days,
//! month lengths in ordinal order, ordinal of the leap month).  Arithmetic
//! calendars compute it (Calendrical Calculations formulas); chinese / dangi
//! and the Umm al-Qura years use tables observed from the original.

use std::sync::OnceLock;

use super::calendar::{Cal, MonthCode};
use super::cn_tables::*;
use super::dur::DateDur;
use super::fields::Fields;
use super::iso::*;
use super::*;

/// epoch day of Coptic 1-01-01 (0284-08-29)
const COPTIC_EPOCH: i64 = -615558;
/// epoch day of Ethiopic 1-01-01 (Julian 0008-08-29)
const ETHIOPIC_EPOCH: i64 = -716367;
/// Persian new year: PERSIAN_BASE + 365 (y-1) + floor((8y+21)/33)
const PERSIAN_BASE: i64 = -492268;
/// epoch day of Islamic (civil) 1-01-01 (0622-07-19)
const ISLAMIC_CIVIL_EPOCH: i64 = -492148;
/// Hebrew epoch (RD -1373427) as epoch days
const HEBREW_EPOCH: i64 = -2092590;

#[derive(Clone, Copy, Debug)]
pub struct Layout {
    pub start: i64,
    pub lens: [u8; 13],
    pub n: u8,
    /// ordinal of the leap month (chinese / dangi / hebrew), 0 = none
    pub leap: u8,
}

impl Layout {
    fn total(&self) -> i64 {
        self.lens[..self.n as usize].iter().map(|&l| l as i64).sum()
    }
    fn month_start(&self, m: u8) -> i64 {
        self.start + self.lens[..(m - 1) as usize].iter().map(|&l| l as i64).sum::<i64>()
    }
}

// ---------------------------------------------------------------------------
// Year layouts
// ---------------------------------------------------------------------------

fn coptic_like_start(epoch: i64, y: i64) -> i64 {
    epoch + 365 * (y - 1) + y.div_euclid(4)
}

fn hebrew_elapsed(y: i64) -> i64 {
    let months = (235 * y - 234).div_euclid(19);
    let parts = 12084 + 13753 * months;
    let days = 29 * months + parts.div_euclid(25920);
    if (3 * (days + 1)).rem_euclid(7) < 3 {
        days + 1
    } else {
        days
    }
}

fn hebrew_new_year(y: i64) -> i64 {
    let ny0 = hebrew_elapsed(y - 1);
    let ny1 = hebrew_elapsed(y);
    let ny2 = hebrew_elapsed(y + 1);
    let corr = if ny2 - ny1 == 356 {
        2
    } else if ny1 - ny0 == 382 {
        1
    } else {
        0
    };
    HEBREW_EPOCH + ny1 + corr
}

fn hebrew_leap(y: i64) -> bool {
    (7 * y + 1).rem_euclid(19) < 7
}

fn islamic_start(epoch: i64, y: i64) -> i64 {
    epoch + (y - 1) * 354 + (3 + 11 * y).div_euclid(30)
}

fn islamic_leap(y: i64) -> bool {
    (14 + 11 * y).rem_euclid(30) < 11
}

fn persian_start(y: i64) -> i64 {
    PERSIAN_BASE + 365 * (y - 1) + (8 * y + 21).div_euclid(33)
}

fn persian_leap(y: i64) -> bool {
    (25 * y + 11).rem_euclid(33) < 8
}

fn indian_start(y: i64) -> i64 {
    let g = y + 78;
    crate::datetime::days_from_civil(g, 3, if is_leap(g) { 21 } else { 22 })
}

/// Umm al-Qura year starts for the table years (and one past the end)
fn umalqura_starts() -> &'static Vec<i64> {
    static S: OnceLock<Vec<i64>> = OnceLock::new();
    S.get_or_init(|| {
        let mut v = Vec::with_capacity(UMALQURA_MASKS.len() + 1);
        let mut s = UMALQURA_FIRST_START;
        for &m in UMALQURA_MASKS.iter() {
            v.push(s);
            s += 348 + m.count_ones() as i64;
        }
        v.push(s);
        v
    })
}

fn b64(c: u8) -> u32 {
    match c {
        b'A'..=b'Z' => (c - b'A') as u32,
        b'a'..=b'z' => (c - b'a' + 26) as u32,
        b'0'..=b'9' => (c - b'0' + 52) as u32,
        b'+' => 62,
        _ => 63,
    }
}

/// (start, months, length mask, leap ordinal) of a table year
fn lunisolar_record(cal: Cal, y: i64) -> (i64, u8, u16, u8) {
    let (data, base) = if cal == Cal::Dangi { (DANGI_DATA, DANGI_BASE) } else { (CHINESE_DATA, CHINESE_BASE) };
    let i = (y - LUNISOLAR_FIRST_YEAR) as usize;
    let b = &data.as_bytes()[i * 4..i * 4 + 4];
    let v = (b64(b[0]) << 18) | (b64(b[1]) << 12) | (b64(b[2]) << 6) | b64(b[3]);
    let delta = (v & 127) as i64 - 64;
    let mask = ((v >> 7) & 0x1FFF) as u16;
    let leap = ((v >> 20) & 15) as u8;
    let start = base + (i as i64 * 3652422).div_euclid(10000) + delta;
    (start, if leap > 0 { 13 } else { 12 }, mask, leap)
}

/// Start of a chinese / dangi year (table range, else a mean-year model)
fn lunisolar_start(cal: Cal, y: i64) -> i64 {
    if (LUNISOLAR_FIRST_YEAR..=LUNISOLAR_LAST_YEAR).contains(&y) {
        return lunisolar_record(cal, y).0;
    }
    if y == LUNISOLAR_LAST_YEAR + 1 {
        let (s, n, mask, _) = lunisolar_record(cal, LUNISOLAR_LAST_YEAR);
        return s + (0..n).map(|k| 29 + ((mask >> k) & 1) as i64).sum::<i64>();
    }
    // outside the observed range: mean lunisolar years
    let base = lunisolar_record(cal, LUNISOLAR_FIRST_YEAR).0;
    base + ((y - LUNISOLAR_FIRST_YEAR) * 3652422).div_euclid(10000)
}

pub fn layout(cal: Cal, y: i64) -> Layout {
    let mut lens = [0u8; 13];
    match cal {
        Cal::Coptic | Cal::Ethiopic | Cal::Ethioaa => {
            let (epoch, ey) = match cal {
                Cal::Coptic => (COPTIC_EPOCH, y),
                Cal::Ethiopic => (ETHIOPIC_EPOCH, y),
                _ => (ETHIOPIC_EPOCH, y - 5500),
            };
            for l in lens.iter_mut().take(12) {
                *l = 30;
            }
            lens[12] = if ey.rem_euclid(4) == 3 { 6 } else { 5 };
            Layout { start: coptic_like_start(epoch, ey), lens, n: 13, leap: 0 }
        }
        Cal::Indian => {
            let leap = is_leap(y + 78);
            lens = [if leap { 31 } else { 30 }, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 30, 0];
            Layout { start: indian_start(y), lens, n: 12, leap: 0 }
        }
        Cal::Persian => {
            lens = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, if persian_leap(y) { 30 } else { 29 }, 0];
            Layout { start: persian_start(y), lens, n: 12, leap: 0 }
        }
        Cal::IslamicCivil | Cal::IslamicTbla | Cal::IslamicUmalqura => {
            if cal == Cal::IslamicUmalqura {
                let first = UMALQURA_FIRST_YEAR;
                let last = first + UMALQURA_MASKS.len() as i64 - 1;
                if (first..=last).contains(&y) {
                    let i = (y - first) as usize;
                    let mask = UMALQURA_MASKS[i];
                    for (k, l) in lens.iter_mut().take(12).enumerate() {
                        *l = 29 + ((mask >> k) & 1) as u8;
                    }
                    return Layout { start: umalqura_starts()[i], lens, n: 12, leap: 0 };
                }
            }
            let epoch = if cal == Cal::IslamicTbla { ISLAMIC_CIVIL_EPOCH - 1 } else { ISLAMIC_CIVIL_EPOCH };
            for (k, l) in lens.iter_mut().take(12).enumerate() {
                *l = if k % 2 == 0 { 30 } else { 29 };
            }
            if islamic_leap(y) {
                lens[11] = 30;
            }
            let mut start = islamic_start(epoch, y);
            if cal == Cal::IslamicUmalqura && y == UMALQURA_FIRST_YEAR + UMALQURA_MASKS.len() as i64 {
                start = *umalqura_starts().last().unwrap_or(&start);
            }
            Layout { start, lens, n: 12, leap: 0 }
        }
        Cal::Hebrew => {
            let start = hebrew_new_year(y);
            let len = hebrew_new_year(y + 1) - start;
            let long_heshvan = len % 10 == 5;
            let short_kislev = len % 10 == 3;
            let h = if long_heshvan { 30 } else { 29 };
            let k = if short_kislev { 29 } else { 30 };
            if hebrew_leap(y) {
                lens = [30, h, k, 29, 30, 30, 29, 30, 29, 30, 29, 30, 29];
                Layout { start, lens, n: 13, leap: 6 }
            } else {
                lens = [30, h, k, 29, 30, 29, 30, 29, 30, 29, 30, 29, 0];
                Layout { start, lens, n: 12, leap: 0 }
            }
        }
        Cal::Chinese | Cal::Dangi => {
            if (LUNISOLAR_FIRST_YEAR..=LUNISOLAR_LAST_YEAR).contains(&y) {
                let (start, n, mask, leap) = lunisolar_record(cal, y);
                for (k, l) in lens.iter_mut().take(n as usize).enumerate() {
                    *l = 29 + ((mask >> k) & 1) as u8;
                }
                return Layout { start, lens, n, leap };
            }
            let start = lunisolar_start(cal, y);
            let len = lunisolar_start(cal, y + 1) - start;
            for (k, l) in lens.iter_mut().take(12).enumerate() {
                *l = if k % 2 == 0 { 30 } else { 31 };
            }
            let sum: i64 = lens[..11].iter().map(|&l| l as i64).sum();
            lens[11] = (len - sum).clamp(1, 60) as u8;
            Layout { start, lens, n: 12, leap: 0 }
        }
        _ => {
            // Gregorian-based calendars never get here
            for (k, l) in lens.iter_mut().take(12).enumerate() {
                *l = iso::days_in_month(y, k as u8 + 1);
            }
            Layout { start: crate::datetime::days_from_civil(y, 1, 1), lens, n: 12, leap: 0 }
        }
    }
}

fn year_start(cal: Cal, y: i64) -> i64 {
    match cal {
        Cal::Coptic => coptic_like_start(COPTIC_EPOCH, y),
        Cal::Ethiopic => coptic_like_start(ETHIOPIC_EPOCH, y),
        Cal::Ethioaa => coptic_like_start(ETHIOPIC_EPOCH, y - 5500),
        Cal::Indian => indian_start(y),
        Cal::Persian => persian_start(y),
        Cal::Hebrew => hebrew_new_year(y),
        Cal::Chinese | Cal::Dangi => lunisolar_start(cal, y),
        Cal::IslamicCivil => islamic_start(ISLAMIC_CIVIL_EPOCH, y),
        Cal::IslamicTbla => islamic_start(ISLAMIC_CIVIL_EPOCH - 1, y),
        _ => layout(cal, y).start,
    }
}

/// Calendar year containing an epoch day
fn year_of(cal: Cal, ed: i64) -> i64 {
    let iso_year = from_epoch_days(ed).year;
    let mut y = match cal {
        Cal::Coptic => (4 * (ed - COPTIC_EPOCH) + 1463).div_euclid(1461),
        Cal::Ethiopic => (4 * (ed - ETHIOPIC_EPOCH) + 1463).div_euclid(1461),
        Cal::Ethioaa => (4 * (ed - ETHIOPIC_EPOCH) + 1463).div_euclid(1461) + 5500,
        Cal::Indian => iso_year - 78,
        Cal::Persian => iso_year - 621,
        Cal::Hebrew => iso_year + 3760,
        Cal::IslamicCivil | Cal::IslamicUmalqura => (30 * (ed - ISLAMIC_CIVIL_EPOCH) + 10646).div_euclid(10631),
        Cal::IslamicTbla => (30 * (ed - ISLAMIC_CIVIL_EPOCH + 1) + 10646).div_euclid(10631),
        _ => iso_year,
    };
    let mut guard = 0;
    while year_start(cal, y) > ed && guard < 1000 {
        y -= 1;
        guard += 1;
    }
    while year_start(cal, y + 1) <= ed && guard < 2000 {
        y += 1;
        guard += 1;
    }
    y
}

// ---------------------------------------------------------------------------
// Primitives used by `calendar`
// ---------------------------------------------------------------------------

pub fn from_iso(cal: Cal, d: &IsoDate) -> (i64, u8, u8) {
    let ed = epoch_days(*d);
    let y = year_of(cal, ed);
    let l = layout(cal, y);
    let mut off = ed - l.start;
    for m in 0..l.n as usize {
        let len = l.lens[m] as i64;
        if off < len {
            return (y, m as u8 + 1, off as u8 + 1);
        }
        off -= len;
    }
    (y, l.n, l.lens[l.n as usize - 1])
}

pub fn to_iso(cal: Cal, y: i64, m: u8, d: u8) -> IsoDate {
    let l = layout(cal, y);
    from_epoch_days(l.month_start(m.clamp(1, l.n)) + d as i64 - 1)
}

pub fn months_in_year(cal: Cal, y: i64) -> u8 {
    layout(cal, y).n
}

pub fn days_in_month(cal: Cal, y: i64, m: u8) -> u8 {
    let l = layout(cal, y);
    l.lens[(m.clamp(1, l.n) - 1) as usize]
}

pub fn days_in_year(cal: Cal, y: i64) -> u16 {
    layout(cal, y).total() as u16
}

pub fn in_leap_year(cal: Cal, y: i64) -> bool {
    match cal {
        Cal::Hebrew | Cal::Chinese | Cal::Dangi => layout(cal, y).n == 13,
        Cal::Coptic | Cal::Ethiopic => y.rem_euclid(4) == 3,
        Cal::Ethioaa => (y - 5500).rem_euclid(4) == 3,
        Cal::Indian => is_leap(y + 78),
        Cal::Persian => persian_leap(y),
        Cal::IslamicUmalqura => layout(cal, y).total() == 355,
        Cal::IslamicCivil | Cal::IslamicTbla => islamic_leap(y),
        _ => false,
    }
}

pub fn month_code(cal: Cal, y: i64, m: u8) -> MonthCode {
    let l = layout(cal, y);
    if l.leap == 0 || m < l.leap {
        return MonthCode { num: m, leap: false };
    }
    if cal == Cal::Hebrew {
        // ordinal 6 = Adar I (M05L), 7.. = M06..
        if m == 6 {
            return MonthCode { num: 5, leap: true };
        }
        return MonthCode { num: m - 1, leap: false };
    }
    if m == l.leap {
        MonthCode { num: m - 1, leap: true }
    } else {
        MonthCode { num: m - 1, leap: false }
    }
}

pub fn ordinal_of_code(cal: Cal, y: i64, mc: MonthCode) -> Option<u8> {
    if !code_valid(cal, mc) {
        return None;
    }
    let l = layout(cal, y);
    if mc.leap {
        if l.leap != 0 && month_code(cal, y, l.leap) == mc {
            return Some(l.leap);
        }
        return None;
    }
    if l.leap == 0 || mc.num < l.leap {
        if mc.num <= l.n {
            return Some(mc.num);
        }
        return None;
    }
    Some(mc.num + 1)
}

pub fn code_valid(cal: Cal, mc: MonthCode) -> bool {
    match cal {
        Cal::Hebrew => (1..=12).contains(&mc.num) && (!mc.leap || mc.num == 5),
        Cal::Chinese | Cal::Dangi => (1..=12).contains(&mc.num),
        Cal::Coptic | Cal::Ethiopic | Cal::Ethioaa => (1..=13).contains(&mc.num) && !mc.leap,
        _ => (1..=12).contains(&mc.num) && !mc.leap,
    }
}

/// ConstrainMonthCode (constrain) for a code missing from year `y`
pub fn constrain_code(cal: Cal, y: i64, mc: MonthCode) -> u8 {
    if cal == Cal::Hebrew && mc.leap {
        return ordinal_of_code(cal, y, MonthCode { num: 6, leap: false }).unwrap_or(6);
    }
    let base = MonthCode { num: mc.num, leap: false };
    ordinal_of_code(cal, y, base).unwrap_or(mc.num.min(months_in_year(cal, y)))
}

pub fn era_of(cal: Cal, d: &IsoDate) -> Option<(String, i64)> {
    let (y, _, _) = from_iso(cal, d);
    match cal {
        Cal::Hebrew | Cal::Coptic => Some(("am".into(), y)),
        Cal::Ethiopic => Some(if y >= 1 { ("am".into(), y) } else { ("aa".into(), y + 5500) }),
        Cal::Ethioaa => Some(("aa".into(), y)),
        Cal::Indian => Some(("shaka".into(), y)),
        Cal::Persian => Some(("ap".into(), y)),
        Cal::IslamicCivil | Cal::IslamicTbla | Cal::IslamicUmalqura => {
            Some(if y >= 1 { ("ah".into(), y) } else { ("bh".into(), 1 - y) })
        }
        _ => None,
    }
}

/// Arithmetic year of (era, eraYear); Ok(None) = unknown era
pub fn year_from_era(cal: Cal, era: &str, ey: i64) -> TRes<Option<i64>> {
    Ok(match (cal, era) {
        (Cal::Hebrew, "am") | (Cal::Coptic, "am") => Some(ey),
        (Cal::Ethiopic, "am") => Some(ey),
        (Cal::Ethiopic, "aa") => Some(ey - 5500),
        (Cal::Ethiopic, "mundi") | (Cal::Ethiopic, "incar") | (Cal::Ethioaa, "mundi") => {
            return terr("year is required")
        }
        (Cal::Ethioaa, "aa") => Some(ey),
        (Cal::Indian, "shaka") => Some(ey),
        (Cal::Persian, "ap") => Some(ey),
        (Cal::IslamicCivil, "ah") | (Cal::IslamicTbla, "ah") | (Cal::IslamicUmalqura, "ah") => Some(ey),
        (Cal::IslamicCivil, "bh") | (Cal::IslamicTbla, "bh") | (Cal::IslamicUmalqura, "bh") => Some(1 - ey),
        _ => None,
    })
}

// ---------------------------------------------------------------------------
// PlainMonthDay reference dates
// ---------------------------------------------------------------------------

/// Largest day count a month code can have in this calendar
fn max_days_of_code(cal: Cal, mc: MonthCode) -> u8 {
    match cal {
        Cal::Hebrew => match (mc.num, mc.leap) {
            (5, true) => 30,
            (2, false) | (3, false) => 30,
            (n, false) => [30, 30, 30, 29, 30, 29, 30, 29, 30, 29, 30, 29][(n - 1) as usize],
            _ => 30,
        },
        Cal::Coptic | Cal::Ethiopic | Cal::Ethioaa => {
            if mc.num == 13 {
                6
            } else {
                30
            }
        }
        Cal::Indian => {
            if (1..=6).contains(&mc.num) {
                31
            } else {
                30
            }
        }
        Cal::Persian => {
            if mc.num <= 6 {
                31
            } else {
                30
            }
        }
        _ => 30,
    }
}

const REF_LIMIT: i64 = 1972 * 10000 + 12 * 100 + 31;

fn ymd_key(d: &IsoDate) -> i64 {
    d.year * 10000 + d.month as i64 * 100 + d.day as i64
}

/// Latest ISO date <= 1972-12-31 (searching back to `min_iso_year`) on
/// which (code, day) occurs.
fn search_back(cal: Cal, mc: MonthCode, day: u8, min_iso_year: i64) -> Option<IsoDate> {
    let mut y = from_iso(cal, &IsoDate::new(1972, 12, 31)).0;
    loop {
        if let Some(o) = ordinal_of_code(cal, y, mc) {
            if days_in_month(cal, y, o) >= day {
                let d = to_iso(cal, y, o, day);
                if ymd_key(&d) <= REF_LIMIT {
                    return Some(d);
                }
            }
        }
        y -= 1;
        if to_iso(cal, y, 1, 1).year < min_iso_year {
            return None;
        }
    }
}

fn search_forward(cal: Cal, mc: MonthCode, day: u8, max_iso_year: i64) -> Option<IsoDate> {
    let mut y = from_iso(cal, &IsoDate::new(1972, 12, 31)).0;
    loop {
        if let Some(o) = ordinal_of_code(cal, y, mc) {
            if days_in_month(cal, y, o) >= day {
                let d = to_iso(cal, y, o, day);
                if ymd_key(&d) > REF_LIMIT {
                    return Some(d);
                }
            }
        }
        y += 1;
        if to_iso(cal, y, 1, 1).year > max_iso_year {
            return None;
        }
    }
}

/// CalendarMonthDayToISOReferenceDate for non-Gregorian calendars
pub fn month_day_to_iso_reference(cal: Cal, f: &Fields, overflow: Overflow) -> TRes<IsoDate> {
    let day_f = f.day.unwrap_or(1.0);
    // determine (code, day) — from the year when given
    let (mc, mut day) = match f.year {
        Some(yf) => {
            if yf.abs() > 1e6 {
                return rerr(MSG_DATE_RANGE);
            }
            let y = yf as i64;
            let ord = if let Some(code) = &f.month_code {
                let code = MonthCode::parse(code);
                match ordinal_of_code(cal, y, code) {
                    Some(o) => o,
                    None => {
                        if overflow == Overflow::Reject {
                            if cal == Cal::Hebrew {
                                return rerr("leap month does not exist in this year");
                            }
                            return rerr("invalid monthCode for this calendar");
                        }
                        constrain_code(cal, y, code)
                    }
                }
            } else {
                let m = f.month.unwrap_or(1.0);
                let miy = months_in_year(cal, y);
                if m > miy as f64 {
                    if overflow == Overflow::Reject {
                        return rerr("month is out of range");
                    }
                    miy
                } else {
                    m as u8
                }
            };
            if let (Some(code), Some(m)) = (&f.month_code, f.month) {
                if ordinal_of_code(cal, y, MonthCode::parse(code)) != Some(m as u8) && f.month.is_some() {
                    if MonthCode::parse(code) != month_code(cal, y, m.min(13.0) as u8) {
                        return rerr("month and monthCode disagree");
                    }
                }
            }
            let dim = days_in_month(cal, y, ord);
            let d = if day_f > dim as f64 {
                if overflow == Overflow::Reject {
                    return rerr("day is out of range");
                }
                dim
            } else {
                day_f as u8
            };
            (month_code(cal, y, ord), d)
        }
        None => {
            let code = MonthCode::parse(f.month_code.as_deref().unwrap_or("M01"));
            if overflow == Overflow::Reject {
                // validated against the calendar year containing 1972-12-31
                let y0 = from_iso(cal, &IsoDate::new(1972, 12, 31)).0;
                let ord = match ordinal_of_code(cal, y0, code) {
                    Some(o) => o,
                    None => {
                        if cal == Cal::Hebrew {
                            return rerr("leap month does not exist in this year");
                        }
                        return rerr("invalid monthCode for this calendar");
                    }
                };
                if day_f > days_in_month(cal, y0, ord) as f64 {
                    return rerr("day is out of range");
                }
            }
            let max = max_days_of_code(cal, code);
            let d = if day_f > max as f64 { max } else { day_f as u8 };
            (code, d)
        }
    };
    if day < 1 {
        day = 1;
    }
    if let Some(d) = search_back(cal, mc, day, 1900) {
        return Ok(d);
    }
    if let Some(d) = search_forward(cal, mc, day, 2100) {
        return Ok(d);
    }
    // leap month that never has that many days: use the regular month
    let base = MonthCode { num: mc.num, leap: false };
    if let Some(d) = search_back(cal, base, day, 1700) {
        return Ok(d);
    }
    if let Some(d) = search_back(cal, base, day.min(29), 1700) {
        return Ok(d);
    }
    rerr(MSG_DATE_RANGE)
}

// ---------------------------------------------------------------------------
// Arithmetic
// ---------------------------------------------------------------------------

/// BalanceNonISODate(year, month) for an ordinal month that may overflow
fn balance_months(cal: Cal, y: i64, m: i64) -> TRes<(i64, u8)> {
    let mut y = y;
    let mut m = m;
    let mut guard = 0u64;
    while m < 1 {
        y -= 1;
        m += months_in_year(cal, y) as i64;
        guard += 1;
        if guard > 700_000 {
            return rerr(MSG_DATE_RANGE);
        }
    }
    loop {
        let miy = months_in_year(cal, y) as i64;
        if m <= miy {
            break;
        }
        m -= miy;
        y += 1;
        guard += 1;
        if guard > 700_000 {
            return rerr(MSG_DATE_RANGE);
        }
    }
    Ok((y, m as u8))
}

/// NonISODateAdd
pub fn date_add(cal: Cal, d: &IsoDate, dd: &DateDur, overflow: Overflow) -> TRes<IsoDate> {
    if dd.years.abs() > 1_000_000 || dd.months.abs() > 13_000_000 {
        return rerr(MSG_DATE_RANGE);
    }
    let (y, m, day) = from_iso(cal, d);
    let mc = month_code(cal, y, m);
    let y0 = y + dd.years;
    let m0 = match ordinal_of_code(cal, y0, mc) {
        Some(o) => o,
        None => {
            if overflow == Overflow::Reject {
                return rerr("leap month does not exist in the target year");
            }
            constrain_code(cal, y0, mc)
        }
    };
    let (y1, m1) = balance_months(cal, y0, m0 as i64 + dd.months)?;
    let dim = days_in_month(cal, y1, m1);
    let day1 = if day > dim {
        if overflow == Overflow::Reject {
            return rerr("day is out of range in the target month");
        }
        dim
    } else {
        day
    };
    let days = dd.days + 7 * dd.weeks;
    if days.abs() > 400_000_000 {
        return rerr(MSG_DATE_RANGE);
    }
    let base = to_iso(cal, y1, m1, day1);
    Ok(add_days(base, days))
}

/// CompareSurpasses with a month code (string comparison) or ordinal
fn compare_surpasses(sign: i64, year: i64, month_key: (u8, bool), day: u8, target: (i64, (u8, bool), u8)) -> bool {
    if year != target.0 {
        return sign * (year - target.0) > 0;
    }
    if month_key != target.1 {
        let c = if month_key > target.1 { 1 } else { -1 };
        return sign * c > 0;
    }
    if day != target.2 {
        return sign * (day as i64 - target.2 as i64) > 0;
    }
    false
}

/// NonISODateSurpasses for (years, months) candidates
fn surpasses_ym(cal: Cal, sign: i64, one: (i64, u8, u8), two: &IsoDate, years: i64, months: i64) -> bool {
    let (y1, m1, d1) = one;
    let code1 = month_code(cal, y1, m1);
    let (ty, tm, td) = from_iso(cal, two);
    let tcode = month_code(cal, ty, tm);
    let y0 = y1 + years;
    if compare_surpasses(sign, y0, (code1.num, code1.leap), d1, (ty, (tcode.num, tcode.leap), td)) {
        return true;
    }
    let m0 = ordinal_of_code(cal, y0, code1).unwrap_or_else(|| constrain_code(cal, y0, code1));
    let (ya, ma) = match balance_months(cal, y0, m0 as i64 + months) {
        Ok(x) => x,
        Err(_) => return true,
    };
    // compare ordinal months
    if ya != ty {
        return sign * (ya - ty) > 0;
    }
    if ma != tm {
        return sign * (ma as i64 - tm as i64) > 0;
    }
    if d1 != td {
        return sign * (d1 as i64 - td as i64) > 0;
    }
    false
}

/// NonISODateUntil
pub fn date_until(cal: Cal, one: &IsoDate, two: &IsoDate, largest: Unit) -> DateDur {
    let sign = -(compare_date(one, two) as i64);
    if sign == 0 {
        return DateDur::default();
    }
    let p1 = from_iso(cal, one);
    let (ty, _, _) = from_iso(cal, two);
    let mut years = 0i64;
    let mut months = 0i64;
    if largest == Unit::Year || largest == Unit::Month {
        if largest == Unit::Year {
            let mut cand = ty - p1.0;
            // step back until it no longer surpasses, then forward as far as possible
            while cand != 0 && surpasses_ym(cal, sign, p1, two, cand, 0) {
                cand -= sign;
            }
            while !surpasses_ym(cal, sign, p1, two, cand + sign, 0) {
                cand += sign;
            }
            years = cand;
        }
        // months: estimate from the day distance
        let y0 = p1.0 + years;
        let code1 = month_code(cal, p1.0, p1.1);
        let m0 = ordinal_of_code(cal, y0, code1).unwrap_or_else(|| constrain_code(cal, y0, code1));
        let start = to_iso(cal, y0, m0, 1);
        let est = ((epoch_days(*two) - epoch_days(start)) as f64 / 29.53).trunc() as i64;
        let mut cand = est;
        if cand.signum() != sign && cand != 0 {
            cand = 0;
        }
        while cand != 0 && surpasses_ym(cal, sign, p1, two, years, cand) {
            cand -= sign;
        }
        while !surpasses_ym(cal, sign, p1, two, years, cand + sign) {
            cand += sign;
        }
        months = cand;
    }
    // date after years / months (regulated day)
    let y0 = p1.0 + years;
    let code1 = month_code(cal, p1.0, p1.1);
    let m0 = ordinal_of_code(cal, y0, code1).unwrap_or_else(|| constrain_code(cal, y0, code1));
    let (ya, ma) = balance_months(cal, y0, m0 as i64 + months).unwrap_or((y0, m0));
    let dim = days_in_month(cal, ya, ma);
    let inter = to_iso(cal, ya, ma, p1.2.min(dim));
    let total = epoch_days(*two) - epoch_days(inter);
    let mut weeks = 0;
    if largest == Unit::Week {
        weeks = total / 7;
    }
    DateDur { years, months, weeks, days: total - weeks * 7 }
}
