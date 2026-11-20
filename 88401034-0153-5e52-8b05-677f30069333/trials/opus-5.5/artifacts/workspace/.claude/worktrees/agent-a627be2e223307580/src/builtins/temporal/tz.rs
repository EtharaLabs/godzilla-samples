//! Time zones for Temporal: fixed UTC offsets (minute precision) and named
//! zones resolved through `crate::datetime` (system tz database).

use std::rc::Rc;

use super::iso::*;
use super::parse;
use super::*;
use crate::datetime as dt;

pub struct NamedTz {
    pub id: String,
    pub zone: dt::TimeZone,
    pub primary: String,
}

#[derive(Clone)]
pub enum Tz {
    /// offset in minutes
    Offset(i64),
    Named(Rc<NamedTz>),
}

impl std::fmt::Debug for Tz {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Tz({})", self.id())
    }
}

pub const MSG_GAP: &str = "no such local time (skipped by a DST gap)";
pub const MSG_OVERLAP: &str = "ambiguous local time (DST overlap)";

impl Tz {
    pub fn id(&self) -> String {
        match self {
            Tz::Offset(m) => fmt_offset_minutes(*m),
            Tz::Named(n) => n.id.clone(),
        }
    }

    pub fn utc() -> Tz {
        Tz::named(dt::TimeZone::Utc)
    }

    fn named(zone: dt::TimeZone) -> Tz {
        let id = zone.id();
        let primary = zone.primary_id();
        Tz::Named(Rc::new(NamedTz { id, zone, primary }))
    }

    /// ParseTimeZoneIdentifier + GetAvailableNamedTimeZoneIdentifier.
    /// Err(true) = not identifier syntax, Err(false) = unknown zone.
    pub fn from_identifier_ex(s: &str) -> Result<Tz, bool> {
        if s.starts_with('+') || s.starts_with('-') {
            return match parse::parse_offset_string(s, false) {
                Some(o) => Ok(Tz::Offset((o.ns / NS_PER_MINUTE) as i64)),
                None => Err(true),
            };
        }
        if !parse::is_iana_name_syntax(s.as_bytes()) {
            return Err(true);
        }
        match dt::TimeZone::from_name(s) {
            Some(z @ dt::TimeZone::Utc) | Some(z @ dt::TimeZone::Named(_)) => Ok(Tz::named(z)),
            Some(dt::TimeZone::Fixed(m)) => Ok(Tz::Offset(m as i64)),
            None => Err(false),
        }
    }

    pub fn from_identifier(s: &str) -> Option<Tz> {
        Tz::from_identifier_ex(s).ok()
    }

    /// ParseTemporalTimeZoneString + identifier resolution
    pub fn from_time_zone_string(s: &str) -> Option<Tz> {
        match Tz::from_identifier_ex(s) {
            Ok(tz) => return Some(tz),
            Err(false) => {}
            Err(true) => {}
        }
        let p = parse::parse_dt_or_time(s)?;
        if let Some(a) = &p.tz {
            return Tz::from_identifier(&a.text);
        }
        if p.z {
            return Some(Tz::utc());
        }
        if let Some(o) = &p.offset {
            if o.has_seconds {
                return None;
            }
            return Some(Tz::Offset((o.ns / NS_PER_MINUTE) as i64));
        }
        None
    }

    /// GetOffsetNanosecondsFor
    pub fn offset_ns(&self, ns: i128) -> i128 {
        match self {
            Tz::Offset(m) => *m as i128 * NS_PER_MINUTE,
            Tz::Named(n) => {
                let ms = ns.div_euclid(1_000_000) as f64;
                n.zone.offset_ms(ms) as i128 * 1_000_000
            }
        }
    }

    /// GetISODateTimeFor
    pub fn datetime_for(&self, ns: i128) -> IsoDateTime {
        datetime_from_epoch_ns(ns + self.offset_ns(ns))
    }

    /// GetPossibleEpochNanoseconds
    pub fn possible_epoch_ns(&self, d: &IsoDateTime) -> TRes<Vec<i128>> {
        let v = match self {
            Tz::Offset(m) => {
                let b = balance_datetime(&d.date, &d.time, -(*m as i128) * NS_PER_MINUTE);
                if !days_in_range(&b.date) {
                    return rerr(MSG_INSTANT_RANGE);
                }
                vec![utc_epoch_ns_dt(&b)]
            }
            Tz::Named(_) => {
                if !days_in_range(&d.date) {
                    return rerr(MSG_INSTANT_RANGE);
                }
                let local = utc_epoch_ns_dt(d);
                let before = self.offset_ns(local - NS_PER_DAY);
                let after = self.offset_ns(local + NS_PER_DAY);
                let mut cands = vec![before];
                if after != before {
                    cands.push(after);
                }
                let mut out = Vec::new();
                for o in cands {
                    let e = local - o;
                    if self.datetime_for(e) == *d {
                        out.push(e);
                    }
                }
                out.sort();
                out.dedup();
                out
            }
        };
        for &x in &v {
            if !epoch_ns_valid(x) {
                return rerr(MSG_INSTANT_RANGE);
            }
        }
        Ok(v)
    }

    /// DisambiguatePossibleEpochNanoseconds
    pub fn disambiguate(&self, possible: Vec<i128>, d: &IsoDateTime, dis: Disambiguation) -> TRes<i128> {
        let n = possible.len();
        if n == 1 {
            return Ok(possible[0]);
        }
        if n != 0 {
            return match dis {
                Disambiguation::Earlier | Disambiguation::Compatible => Ok(possible[0]),
                Disambiguation::Later => Ok(possible[n - 1]),
                Disambiguation::Reject => rerr(MSG_OVERLAP),
            };
        }
        if dis == Disambiguation::Reject {
            return rerr(MSG_GAP);
        }
        let utc = utc_epoch_ns_dt(d);
        let day_before = utc - NS_PER_DAY;
        let day_after = utc + NS_PER_DAY;
        if !epoch_ns_valid(day_before) || !epoch_ns_valid(day_after) {
            return rerr(MSG_INSTANT_RANGE);
        }
        let nanos = self.offset_ns(day_after) - self.offset_ns(day_before);
        if dis == Disambiguation::Earlier {
            let e = balance_datetime(&d.date, &d.time, -nanos);
            let p = self.possible_epoch_ns(&e)?;
            return match p.first() {
                Some(&x) => Ok(x),
                None => rerr(MSG_GAP),
            };
        }
        let l = balance_datetime(&d.date, &d.time, nanos);
        let p = self.possible_epoch_ns(&l)?;
        match p.last() {
            Some(&x) => Ok(x),
            None => rerr(MSG_GAP),
        }
    }

    /// GetEpochNanosecondsFor
    pub fn epoch_ns_for(&self, d: &IsoDateTime, dis: Disambiguation) -> TRes<i128> {
        let p = self.possible_epoch_ns(d)?;
        self.disambiguate(p, d, dis)
    }

    /// GetStartOfDay
    pub fn start_of_day(&self, date: &IsoDate) -> TRes<i128> {
        let d = IsoDateTime { date: *date, time: Time::MIDNIGHT };
        let p = self.possible_epoch_ns(&d)?;
        if let Some(&x) = p.first() {
            return Ok(x);
        }
        let utc = utc_epoch_ns_dt(&d);
        match self.next_transition(utc - NS_PER_DAY) {
            Some(t) => Ok(t),
            None => rerr(MSG_INSTANT_RANGE),
        }
    }

    /// GetNamedTimeZoneNextTransition (strictly after `ns`)
    pub fn next_transition(&self, ns: i128) -> Option<i128> {
        match self {
            Tz::Offset(_) => None,
            Tz::Named(n) => {
                let secs = ns.div_euclid(NS_PER_SECOND);
                let secs = secs.clamp(i64::MIN as i128, i64::MAX as i128) as i64;
                let t = n.zone.next_offset_transition(secs)? as i128 * NS_PER_SECOND;
                if t > NS_MAX_INSTANT {
                    None
                } else {
                    Some(t)
                }
            }
        }
    }

    /// GetNamedTimeZonePreviousTransition (strictly before `ns`)
    pub fn prev_transition(&self, ns: i128) -> Option<i128> {
        match self {
            Tz::Offset(_) => None,
            Tz::Named(n) => {
                let secs = -((-ns).div_euclid(NS_PER_SECOND)); // ceil
                let secs = secs.clamp(i64::MIN as i128, i64::MAX as i128) as i64;
                let t = n.zone.prev_offset_transition(secs)? as i128 * NS_PER_SECOND;
                if t < NS_MIN_INSTANT {
                    None
                } else {
                    Some(t)
                }
            }
        }
    }

    /// TimeZoneEquals
    pub fn equals(&self, other: &Tz) -> bool {
        match (self, other) {
            (Tz::Offset(a), Tz::Offset(b)) => a == b,
            (Tz::Named(a), Tz::Named(b)) => a.id == b.id || a.primary == b.primary,
            _ => false,
        }
    }
}
