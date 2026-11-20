//! Calendar systems: identifiers, field resolution and arithmetic.
//!
//! Every calendar is described by a few primitives on its "arithmetic year"
//! (the `year` property): ordinal months, month codes, days per month and
//! conversion from / to ISO dates.  The Gregorian-based calendars (iso8601,
//! gregory, japanese, buddhist, roc) share the ISO arithmetic; the others
//! live in `cals`.

use super::dur::DateDur;
use super::fields::*;
use super::iso::*;
use super::*;

#[derive(Clone, Copy, PartialEq, Eq, Debug, Hash)]
pub enum Cal {
    Iso8601,
    Gregory,
    Japanese,
    Buddhist,
    Roc,
    Hebrew,
    Chinese,
    Dangi,
    IslamicCivil,
    IslamicTbla,
    IslamicUmalqura,
    Persian,
    Indian,
    Coptic,
    Ethiopic,
    Ethioaa,
}

impl Cal {
    pub fn id(self) -> &'static str {
        match self {
            Cal::Iso8601 => "iso8601",
            Cal::Gregory => "gregory",
            Cal::Japanese => "japanese",
            Cal::Buddhist => "buddhist",
            Cal::Roc => "roc",
            Cal::Hebrew => "hebrew",
            Cal::Chinese => "chinese",
            Cal::Dangi => "dangi",
            Cal::IslamicCivil => "islamic-civil",
            Cal::IslamicTbla => "islamic-tbla",
            Cal::IslamicUmalqura => "islamic-umalqura",
            Cal::Persian => "persian",
            Cal::Indian => "indian",
            Cal::Coptic => "coptic",
            Cal::Ethiopic => "ethiopic",
            Cal::Ethioaa => "ethioaa",
        }
    }

    /// CanonicalizeCalendar (ASCII case-insensitive, CLDR aliases)
    pub fn from_id(s: &str) -> Option<Cal> {
        let l = s.to_ascii_lowercase();
        Some(match l.as_str() {
            "iso8601" => Cal::Iso8601,
            "gregory" | "gregorian" => Cal::Gregory,
            "japanese" => Cal::Japanese,
            "buddhist" => Cal::Buddhist,
            "roc" => Cal::Roc,
            "hebrew" => Cal::Hebrew,
            "chinese" => Cal::Chinese,
            "dangi" => Cal::Dangi,
            "islamic-civil" | "islamicc" => Cal::IslamicCivil,
            "islamic-tbla" => Cal::IslamicTbla,
            "islamic-umalqura" => Cal::IslamicUmalqura,
            "persian" => Cal::Persian,
            "indian" => Cal::Indian,
            "coptic" => Cal::Coptic,
            "ethiopic" => Cal::Ethiopic,
            "ethioaa" | "ethiopic-amete-alem" => Cal::Ethioaa,
            _ => return None,
        })
    }

    /// ParseTemporalCalendarString + CanonicalizeCalendar
    pub fn from_calendar_string(s: &str) -> Option<Cal> {
        if let Some(p) = parse::parse_dt_or_time(s) {
            return match p.calendar {
                None => Some(Cal::Iso8601),
                Some(c) => Cal::from_id(&c),
            };
        }
        if !parse::is_annotation_value(s.as_bytes()) {
            return None;
        }
        Cal::from_id(s)
    }

    pub fn has_eras(self) -> bool {
        !matches!(self, Cal::Iso8601 | Cal::Chinese | Cal::Dangi)
    }

    /// Calendars using the ISO month / day structure.
    pub fn is_gregorian_based(self) -> bool {
        matches!(self, Cal::Iso8601 | Cal::Gregory | Cal::Japanese | Cal::Buddhist | Cal::Roc)
    }

    fn year_offset(self) -> i64 {
        match self {
            Cal::Buddhist => 543,
            Cal::Roc => -1911,
            _ => 0,
        }
    }
}

/// Month code: number and leap flag ("M05L" = (5, true)).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct MonthCode {
    pub num: u8,
    pub leap: bool,
}

impl MonthCode {
    pub fn parse(s: &str) -> MonthCode {
        let b = s.as_bytes();
        MonthCode { num: (b[1] - b'0') * 10 + (b[2] - b'0'), leap: b.len() == 4 }
    }
    pub fn to_string(self) -> String {
        format!("M{:02}{}", self.num, if self.leap { "L" } else { "" })
    }
}

// ---------------------------------------------------------------------------
// Calendar primitives
// ---------------------------------------------------------------------------

/// (arithmetic year, ordinal month, day) of an ISO date
pub fn ymd_from_iso(cal: Cal, d: &IsoDate) -> (i64, u8, u8) {
    if cal.is_gregorian_based() {
        return (d.year + cal.year_offset(), d.month, d.day);
    }
    super::cals::from_iso(cal, d)
}

/// ISO date of a valid calendar date
pub fn iso_from_ymd(cal: Cal, y: i64, m: u8, d: u8) -> IsoDate {
    if cal.is_gregorian_based() {
        return IsoDate::new(y - cal.year_offset(), m, d);
    }
    super::cals::to_iso(cal, y, m, d)
}

pub fn months_in_year(cal: Cal, y: i64) -> u8 {
    if cal.is_gregorian_based() {
        return 12;
    }
    super::cals::months_in_year(cal, y)
}

pub fn days_in_month_cal(cal: Cal, y: i64, m: u8) -> u8 {
    if cal.is_gregorian_based() {
        return days_in_month(y - cal.year_offset(), m);
    }
    super::cals::days_in_month(cal, y, m)
}

pub fn days_in_year_cal(cal: Cal, y: i64) -> u16 {
    if cal.is_gregorian_based() {
        return iso::days_in_year(y - cal.year_offset());
    }
    super::cals::days_in_year(cal, y)
}

pub fn in_leap_year(cal: Cal, y: i64) -> bool {
    if cal.is_gregorian_based() {
        return is_leap(y - cal.year_offset());
    }
    super::cals::in_leap_year(cal, y)
}

pub fn month_code_of(cal: Cal, y: i64, m: u8) -> MonthCode {
    if cal.is_gregorian_based() {
        return MonthCode { num: m, leap: false };
    }
    super::cals::month_code(cal, y, m)
}

/// Ordinal month of a month code in year `y` (None if the year lacks it).
pub fn ordinal_of_code(cal: Cal, y: i64, mc: MonthCode) -> Option<u8> {
    if cal.is_gregorian_based() {
        if !mc.leap && (1..=12).contains(&mc.num) {
            return Some(mc.num);
        }
        return None;
    }
    super::cals::ordinal_of_code(cal, y, mc)
}

/// Is the month code valid in this calendar at all (some year)?
pub fn code_valid_for_calendar(cal: Cal, mc: MonthCode) -> bool {
    if cal.is_gregorian_based() {
        return !mc.leap && (1..=12).contains(&mc.num);
    }
    super::cals::code_valid(cal, mc)
}

/// Era and era year of a date (None for calendars without eras)
pub fn era_of(cal: Cal, d: &IsoDate) -> Option<(String, i64)> {
    let y = d.year;
    match cal {
        Cal::Iso8601 | Cal::Chinese | Cal::Dangi => None,
        Cal::Gregory => Some(if y >= 1 { ("ce".into(), y) } else { ("bce".into(), 1 - y) }),
        Cal::Buddhist => Some(("be".into(), y + 543)),
        Cal::Roc => Some(if y >= 1912 { ("roc".into(), y - 1911) } else { ("broc".into(), 1912 - y) }),
        Cal::Japanese => {
            for &(name, sy, sm, sd) in JAPANESE_ERAS.iter().rev() {
                if (y, d.month, d.day) >= (sy, sm, sd) {
                    let start_year = JAPANESE_ERA_YEAR_ONE.iter().find(|e| e.0 == name).map(|e| e.1).unwrap_or(sy);
                    return Some((name.into(), y - start_year + 1));
                }
            }
            Some(if y >= 1 { ("ce".into(), y) } else { ("bce".into(), 1 - y) })
        }
        _ => super::cals::era_of(cal, d),
    }
}

/// Japanese eras: name and the first ISO date on which the era is reported.
const JAPANESE_ERAS: [(&str, i64, u8, u8); 5] = [
    ("meiji", 1873, 1, 1),
    ("taisho", 1912, 7, 30),
    ("showa", 1926, 12, 25),
    ("heisei", 1989, 1, 8),
    ("reiwa", 2019, 5, 1),
];

/// ISO year of era year 1
const JAPANESE_ERA_YEAR_ONE: [(&str, i64); 5] =
    [("meiji", 1868), ("taisho", 1912), ("showa", 1926), ("heisei", 1989), ("reiwa", 2019)];

/// Arithmetic year from (era, eraYear); Ok(None) = unknown era.  Era names
/// are matched ASCII-case-insensitively.
pub fn year_from_era(cal: Cal, era: &str, era_year: i64) -> TRes<Option<i64>> {
    let lower = era.to_ascii_lowercase();
    let era = lower.as_str();
    Ok(match cal {
        Cal::Gregory => match era {
            "ce" | "ad" | "gregory" => Some(era_year),
            "bce" | "bc" | "gregory-inverse" => Some(1 - era_year),
            _ => None,
        },
        Cal::Buddhist => match era {
            "be" => Some(era_year),
            _ => None,
        },
        Cal::Roc => match era {
            "roc" | "minguo" => Some(era_year),
            "broc" | "before-roc" => Some(1 - era_year),
            "roc-inverse" => return rerr(format!("invalid era: {}", era)),
            _ => None,
        },
        Cal::Japanese => {
            if let Some(e) = JAPANESE_ERA_YEAR_ONE.iter().find(|e| e.0 == era) {
                return Ok(Some(e.1 + era_year - 1));
            }
            match era {
                "ce" | "ad" | "gregory" => Some(era_year),
                "bce" | "bc" | "gregory-inverse" => Some(1 - era_year),
                _ => None,
            }
        }
        _ => return super::cals::year_from_era(cal, era, era_year),
    })
}

// ---------------------------------------------------------------------------
// CalendarISOToDate
// ---------------------------------------------------------------------------

pub struct CalDate {
    pub year: i64,
    pub month: u8,
    pub month_code: MonthCode,
    pub day: u8,
}

pub fn iso_to_date(cal: Cal, d: &IsoDate) -> CalDate {
    let (y, m, day) = ymd_from_iso(cal, d);
    CalDate {
        year: y,
        month: m,
        month_code: month_code_of(cal, y, m),
        day,
    }
}

pub fn day_of_week(_cal: Cal, d: &IsoDate) -> u8 {
    iso::day_of_week(d)
}

pub fn day_of_year(cal: Cal, d: &IsoDate) -> u16 {
    if cal.is_gregorian_based() {
        return iso::day_of_year(d);
    }
    let (y, _, _) = ymd_from_iso(cal, d);
    let first = iso_from_ymd(cal, y, 1, 1);
    (epoch_days(*d) - epoch_days(first) + 1) as u16
}

/// (week, year) — only the ISO calendar has week numbering
pub fn week_of_year(cal: Cal, d: &IsoDate) -> Option<(u8, i64)> {
    if cal == Cal::Iso8601 {
        Some(iso::week_of_year(d))
    } else {
        None
    }
}

// ---------------------------------------------------------------------------
// Field resolution (CalendarResolveFields & friends)
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum FieldKind {
    Date,
    YearMonth,
    MonthDay,
}

fn f2i64(x: f64) -> i64 {
    // saturating; out-of-range years are rejected later by the limit checks
    x as i64
}

/// Resolve era/eraYear/year and month/monthCode.  On success `year` (when
/// relevant) and `month` are set; `month` may still be out of range for
/// the year (constrained later).
pub fn resolve_fields(cal: Cal, f: &mut Fields, kind: FieldKind) -> TRes<()> {
    if cal.has_eras() {
        match (&f.era, f.era_year) {
            (Some(era), Some(ey)) => {
                let era = era.clone();
                match year_from_era(cal, &era, f2i64(ey))? {
                    None => return rerr(format!("{} is not a valid era in calendar {}", era.to_ascii_lowercase(), cal.id())),
                    Some(y) => {
                        if let Some(yy) = f.year {
                            if f2i64(yy) != y {
                                return rerr("year and era/eraYear disagree");
                            }
                        }
                        f.year = Some(y as f64);
                    }
                }
            }
            (Some(_), None) | (None, Some(_)) => {
                if f.year.is_some() {
                    return terr("era and eraYear must be provided together");
                }
                if kind != FieldKind::MonthDay {
                    return terr("missing field 'year'");
                }
            }
            _ => {}
        }
    }
    if kind != FieldKind::MonthDay && f.year.is_none() {
        return terr("missing field 'year'");
    }
    if kind == FieldKind::MonthDay && f.day.is_none() {
        return terr("missing field 'day'");
    }
    if f.month.is_none() && f.month_code.is_none() {
        return terr("missing field 'month'");
    }
    if kind != FieldKind::YearMonth && f.day.is_none() {
        return terr("missing field 'day'");
    }
    if let Some(mc) = &f.month_code {
        let code = MonthCode::parse(mc);
        if !code_valid_for_calendar(cal, code) {
            return rerr("invalid monthCode for this calendar");
        }
        if cal.is_gregorian_based() {
            if let Some(m) = f.month {
                if m != code.num as f64 {
                    return rerr("month and monthCode disagree");
                }
            }
            f.month = Some(code.num as f64);
        }
        // non-ISO calendars resolve the code against the year later
    } else if kind == FieldKind::MonthDay && cal != Cal::Iso8601 && f.year.is_none() {
        return terr("year is required to interpret an ordinal month");
    }
    Ok(())
}

/// RegulateISODate
pub fn regulate_iso_date(year: f64, month: f64, day: f64, overflow: Overflow) -> TRes<IsoDate> {
    let y = f2i64(year);
    match overflow {
        Overflow::Constrain => {
            let m = month.clamp(1.0, 12.0) as u8;
            let dim = days_in_month(y, m) as f64;
            Ok(IsoDate::new(y, m, day.clamp(1.0, dim) as u8))
        }
        Overflow::Reject => {
            if !(1.0..=12.0).contains(&month) {
                return rerr("month out of range");
            }
            let m = month as u8;
            if day < 1.0 || day > days_in_month(y, m) as f64 {
                return rerr("day out of range");
            }
            Ok(IsoDate::new(y, m, day as u8))
        }
    }
}

/// Ordinal month (and the year) of resolved fields for a non-ISO calendar,
/// constraining / rejecting month codes missing from the year.
fn resolve_ordinal_month(cal: Cal, year: i64, f: &Fields, overflow: Overflow) -> TRes<u8> {
    let miy = months_in_year(cal, year);
    if let Some(mc) = &f.month_code {
        let code = MonthCode::parse(mc);
        let ord = match ordinal_of_code(cal, year, code) {
            Some(o) => o,
            None => {
                if overflow == Overflow::Reject {
                    if cal == Cal::Hebrew {
                        return rerr("leap month does not exist in this year");
                    }
                    return rerr("invalid monthCode for this calendar");
                }
                super::cals::constrain_code(cal, year, code)
            }
        };
        if let Some(m) = f.month {
            if m != ord as f64 {
                return rerr("month and monthCode disagree");
            }
        }
        return Ok(ord);
    }
    let m = f.month.unwrap_or(1.0);
    if m > miy as f64 {
        if overflow == Overflow::Reject {
            return rerr("month is out of range");
        }
        return Ok(miy);
    }
    Ok(m as u8)
}

/// CalendarDateToISO for resolved fields
pub fn date_to_iso(cal: Cal, f: &Fields, overflow: Overflow) -> TRes<IsoDate> {
    let year = f.year.unwrap_or(0.0);
    let day = f.day.unwrap_or(1.0);
    if cal.is_gregorian_based() {
        let iso_year = year - cal.year_offset() as f64;
        return regulate_iso_date(iso_year, f.month.unwrap_or(1.0), day, overflow);
    }
    if year.abs() > 1e6 {
        return rerr(MSG_DATE_RANGE);
    }
    let y = year as i64;
    let m = resolve_ordinal_month(cal, y, f, overflow)?;
    let dim = days_in_month_cal(cal, y, m);
    let d = if day > dim as f64 {
        if overflow == Overflow::Reject {
            return rerr("day is out of range");
        }
        dim
    } else {
        day as u8
    };
    Ok(iso_from_ymd(cal, y, m, d))
}

/// CalendarDateFromFields
pub fn date_from_fields(cal: Cal, f: &mut Fields, overflow: Overflow) -> TRes<IsoDate> {
    resolve_fields(cal, f, FieldKind::Date)?;
    let d = date_to_iso(cal, f, overflow)?;
    if !date_within_limits(&d) {
        return rerr(MSG_DATE_RANGE);
    }
    Ok(d)
}

/// CalendarYearMonthFromFields
pub fn year_month_from_fields(cal: Cal, f: &mut Fields, overflow: Overflow) -> TRes<IsoDate> {
    resolve_fields(cal, f, FieldKind::YearMonth)?;
    f.day = Some(1.0);
    let d = date_to_iso(cal, f, overflow)?;
    if !year_month_within_limits(&d) {
        return rerr(MSG_YM_RANGE);
    }
    Ok(d)
}

/// CalendarMonthDayFromFields
pub fn month_day_from_fields(cal: Cal, f: &mut Fields, overflow: Overflow) -> TRes<IsoDate> {
    resolve_fields(cal, f, FieldKind::MonthDay)?;
    if cal.is_gregorian_based() {
        let year = match f.year {
            Some(y) => y - cal.year_offset() as f64,
            None => 1972.0,
        };
        let r = regulate_iso_date(year, f.month.unwrap_or(1.0), f.day.unwrap_or(1.0), overflow)?;
        return Ok(IsoDate::new(1972, r.month, r.day));
    }
    super::cals::month_day_to_iso_reference(cal, f, overflow)
}

/// ISODateToFields
pub fn iso_to_fields(cal: Cal, d: &IsoDate, kind: FieldKind) -> Fields {
    let cd = iso_to_date(cal, d);
    let mut f = Fields::default();
    f.month_code = Some(cd.month_code.to_string());
    if kind != FieldKind::YearMonth {
        f.day = Some(cd.day as f64);
    }
    if kind != FieldKind::MonthDay {
        f.year = Some(cd.year as f64);
    }
    f
}

/// CalendarFieldKeysToIgnore
fn keys_to_ignore(cal: Cal, keys: u32) -> u32 {
    let mut ignored = 0;
    for flag in ALL_FLAGS {
        if keys & flag == 0 {
            continue;
        }
        ignored |= flag;
        if flag == F_MONTH {
            ignored |= F_MONTH_CODE;
        } else if flag == F_MONTH_CODE {
            ignored |= F_MONTH;
        }
        if cal != Cal::Iso8601 && cal.has_eras() && (flag == F_ERA || flag == F_ERA_YEAR || flag == F_YEAR) {
            ignored |= F_ERA | F_ERA_YEAR | F_YEAR;
        }
        if cal == Cal::Japanese && (flag == F_DAY || flag == F_MONTH || flag == F_MONTH_CODE) {
            ignored |= F_ERA | F_ERA_YEAR;
        }
    }
    ignored
}

/// with(): era and eraYear must come together
pub fn check_with_era(cal: Cal, partial: &Fields) -> TRes<()> {
    if cal.has_eras() && partial.era.is_some() != partial.era_year.is_some() {
        return terr("era and eraYear must both be provided");
    }
    Ok(())
}

/// CalendarMergeFields
pub fn merge_fields(cal: Cal, base: &Fields, add: &Fields) -> Fields {
    let add_keys = add.present();
    let overridden = keys_to_ignore(cal, add_keys);
    let base_keys = base.present();
    let mut m = Fields::default();
    for flag in ALL_FLAGS {
        if base_keys & flag != 0 && overridden & flag == 0 {
            m.copy_from(base, flag);
        }
        if add_keys & flag != 0 {
            m.copy_from(add, flag);
        }
    }
    m
}

// ---------------------------------------------------------------------------
// Arithmetic
// ---------------------------------------------------------------------------

/// CalendarDateAdd
pub fn date_add(cal: Cal, d: &IsoDate, dd: &DateDur, overflow: Overflow) -> TRes<IsoDate> {
    let r = if cal.is_gregorian_based() {
        let (y, m) = balance_year_month(d.year.saturating_add(dd.years), d.month as i64 + dd.months);
        if y.abs() > 1_000_000 {
            return rerr(MSG_DATE_RANGE);
        }
        let dim = days_in_month(y, m);
        let day = if d.day > dim {
            if overflow == Overflow::Reject {
                return rerr("date day out of range");
            }
            dim
        } else {
            d.day
        };
        let days = dd.days + 7 * dd.weeks;
        if days.abs() > 400_000_000 {
            return rerr(MSG_DATE_RANGE);
        }
        add_days(IsoDate::new(y, m, day), days)
    } else {
        super::cals::date_add(cal, d, dd, overflow)?
    };
    if !date_within_limits(&r) {
        return rerr(MSG_DATE_RANGE);
    }
    Ok(r)
}

/// ISODateSurpasses
fn surpasses(sign: i64, y1: i64, m1: u8, d1: u8, two: &IsoDate) -> bool {
    let c = (y1, m1, d1).cmp(&(two.year, two.month, two.day));
    let r = match c {
        std::cmp::Ordering::Equal => false,
        std::cmp::Ordering::Greater => sign > 0,
        std::cmp::Ordering::Less => sign < 0,
    };
    // The original also rejects, going backwards, a candidate whose day is
    // clamped to the end of the month and then lands exactly on the target
    // (2024-03-31 until 2024-02-29 is -P31D, not -P1M).
    if !r && sign < 0 && y1 == two.year && m1 == two.month {
        let dim = days_in_month(y1, m1);
        if d1 > dim && dim == two.day {
            return true;
        }
    }
    r
}

/// CalendarDateUntil
pub fn date_until(cal: Cal, one: &IsoDate, two: &IsoDate, largest: Unit) -> DateDur {
    if !cal.is_gregorian_based() {
        return super::cals::date_until(cal, one, two, largest);
    }
    let sign = -(compare_date(one, two) as i64);
    if sign == 0 {
        return DateDur::default();
    }
    let mut years = 0i64;
    if largest == Unit::Year {
        let mut cand = two.year - one.year;
        if cand != 0 && surpasses(sign, one.year + cand, one.month, one.day, two) {
            cand -= sign;
        }
        years = cand;
    }
    let mut months = 0i64;
    if largest == Unit::Year || largest == Unit::Month {
        let base_y = one.year + years;
        let mut cand = (two.year - base_y) * 12 + (two.month as i64 - one.month as i64);
        if cand != 0 {
            let (iy, im) = balance_year_month(base_y, one.month as i64 + cand);
            if surpasses(sign, iy, im, one.day, two) {
                cand -= sign;
            }
        }
        months = cand;
    }
    let (iy, im) = balance_year_month(one.year + years, one.month as i64 + months);
    let constrained = constrain_date(iy, im as i64, one.day as i64);
    let total = epoch_days(*two) - epoch_days(constrained);
    let mut weeks = 0;
    if largest == Unit::Week {
        weeks = total / 7;
    }
    let days = total - weeks * 7;
    DateDur { years, months, weeks, days }
}
