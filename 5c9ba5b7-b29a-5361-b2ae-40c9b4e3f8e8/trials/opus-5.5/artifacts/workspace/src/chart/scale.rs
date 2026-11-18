// Scales: nice tick steps, domains, and number / date formatting.

use super::model::{civil_from_days, days_from_civil, Fmt};
use crate::util::f4;

// Smallest step from the 1-2-5 ladder that cuts `span` into at most five parts.
pub fn nice_step(span: f64) -> f64 {
    if !(span > 0.0) || !span.is_finite() {
        return 1.0;
    }
    let mut p = 10f64.powf((span / 5.0).log10().floor() - 1.0);
    for _ in 0..40 {
        for m in [1.0, 2.0, 5.0] {
            let s = m * p;
            if span / s <= 5.0 + 1e-9 {
                return s;
            }
        }
        p *= 10.0;
    }
    p
}

pub fn snap(q: f64) -> f64 {
    if (q - q.round()).abs() < 1e-9 {
        q.round()
    } else {
        q
    }
}

// Extend [lo, hi] outward to multiples of `s`.
pub fn nice_domain(lo: f64, hi: f64, s: f64) -> (f64, f64) {
    (snap(lo / s).floor() * s, snap(hi / s).ceil() * s)
}

// Multiples of `s` inside [lo, hi].
pub fn ticks_in(lo: f64, hi: f64, s: f64) -> Vec<f64> {
    let (a, b) = if lo <= hi { (lo, hi) } else { (hi, lo) };
    let k0 = snap(a / s).ceil() as i64;
    let k1 = snap(b / s).floor() as i64;
    let mut out = Vec::new();
    let mut k = k0;
    while k <= k1 && out.len() < 5_000_000 {
        let v = k as f64 * s;
        out.push(if v == 0.0 { 0.0 } else { v });
        k += 1;
    }
    out
}

pub fn decimals_of(s: f64) -> usize {
    for d in 0..12 {
        let x = s * 10f64.powi(d as i32);
        if (x - x.round()).abs() < 1e-6 * x.abs().max(1.0) {
            return d;
        }
    }
    12
}

fn fixed(v: f64, d: usize) -> String {
    let s = format!("{:.*}", d, v);
    if s.starts_with('-') && s[1..].chars().all(|c| c == '0' || c == '.') {
        return s[1..].to_string();
    }
    s
}

fn trim(s: String) -> String {
    if s.contains('.') {
        let t = s.trim_end_matches('0').trim_end_matches('.').to_string();
        if t == "-0" {
            return "0".into();
        }
        return t;
    }
    s
}

fn sci_parts(v: f64, n: usize, eng: bool) -> String {
    if v == 0.0 {
        return format!("{}e0", fixed(0.0, n));
    }
    let mut e = v.abs().log10().floor() as i32;
    if eng {
        e = e.div_euclid(3) * 3;
    }
    let mut m = v / 10f64.powi(e);
    let mut ms = fixed(m, n);
    let lim = if eng { 1000.0 } else { 10.0 };
    if ms.trim_start_matches('-').parse::<f64>().unwrap_or(0.0) >= lim {
        e += if eng { 3 } else { 1 };
        m = v / 10f64.powi(e);
        ms = fixed(m, n);
    }
    format!("{}e{}", ms, e)
}

fn gcd(a: u64, b: u64) -> u64 {
    if b == 0 {
        a
    } else {
        gcd(b, a % b)
    }
}

fn fraction(v: f64, d: u64) -> String {
    let neg = v < 0.0;
    let a = v.abs();
    let mut whole = a.floor();
    let mut num = ((a - whole) * d as f64 + 0.5).floor() as u64;
    if num >= d {
        whole += 1.0;
        num = 0;
    }
    let sign = if neg && (whole > 0.0 || num > 0) { "-" } else { "" };
    if num == 0 {
        return format!("{}{}", sign, whole as i64);
    }
    let g = gcd(num, d);
    let (n2, d2) = (num / g, d / g);
    if whole == 0.0 {
        format!("{}{}/{}", sign, n2, d2)
    } else {
        format!("{}{} {}/{}", sign, whole as i64, n2, d2)
    }
}

fn significant(v: f64, n: usize) -> String {
    if v == 0.0 {
        return "0".into();
    }
    let e = v.abs().log10().floor() as i32;
    let dec = n as i32 - 1 - e;
    if dec >= 0 {
        fixed(v, dec as usize)
    } else {
        let p = 10f64.powi(-dec);
        let r = (v / p).round() * p;
        fixed(r, 0)
    }
}

pub fn fmt_with(v: f64, fmt: Option<&Fmt>) -> Option<String> {
    match fmt {
        Some(Fmt::Decimal(n)) => Some(fixed(v, *n)),
        Some(Fmt::Percent(n)) => Some(format!("{}%", fixed(v * 100.0, *n))),
        Some(Fmt::Significant(n)) => Some(significant(v, *n)),
        Some(Fmt::Scientific(n)) => Some(sci_parts(v, *n, false)),
        Some(Fmt::Engineering(n)) => Some(sci_parts(v, *n, true)),
        Some(Fmt::Fraction(d)) => Some(fraction(v, *d)),
        Some(Fmt::Date(p)) => Some(fmt_date_preset(v, p)),
        _ => None,
    }
}

// A tick label on a numeric axis with step `s`.
pub fn fmt_tick(v: f64, s: f64, fmt: Option<&Fmt>) -> String {
    if let Some(x) = fmt_with(v, fmt) {
        return x;
    }
    trim(fixed(v, decimals_of(s)))
}

// A data value (tooltips, titles).
pub fn fmt_value(v: f64, fmt: Option<&Fmt>) -> String {
    if let Some(x) = fmt_with(v, fmt) {
        return x;
    }
    f4(v)
}

// Whole seconds since the epoch of a day count.
fn secs_of(days: f64) -> i64 {
    (days * 86400.0).round() as i64
}

// The day a day count falls on (whole seconds, so no float slivers).
fn day_of(days: f64) -> i64 {
    secs_of(days).div_euclid(86400)
}

// "HH:MM" of a day count; seconds are dropped, not rounded.
pub fn fmt_hm(days: f64) -> String {
    let mins = secs_of(days).rem_euclid(86400) / 60;
    format!("{:02}:{:02}", mins / 60, mins % 60)
}

pub fn fmt_date_preset(days: f64, p: &str) -> String {
    let (y, m, d) = civil_from_days(day_of(days));
    match p {
        "year" => format!("{}", y),
        "month" => format!("{} {}", MONTHS[(m - 1) as usize], y),
        "day" => format!("{} {}", MONTHS[(m - 1) as usize], d),
        _ => fmt_hm(days),
    }
}

pub const MONTHS: [&str; 12] = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

pub fn fmt_date(days: f64) -> String {
    let (y, m, d) = civil_from_days(day_of(days));
    let base = format!("{} {} {}", MONTHS[(m - 1) as usize], d, y);
    if secs_of(days).rem_euclid(86400) != 0 {
        format!("{}, {}", base, fmt_hm(days))
    } else {
        base
    }
}

pub fn fmt_month(days: f64) -> String {
    let (y, m, _) = civil_from_days(day_of(days));
    format!("{} {}", MONTHS[(m - 1) as usize], y)
}

// ------------------------------------------------------------ calendar ticks

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum TUnit {
    Minute,
    Hour,
    Day,
    Week,
    Month,
    Year,
}

pub fn tunit_of(s: &str) -> Option<TUnit> {
    Some(match s {
        "minute" => TUnit::Minute,
        "hour" => TUnit::Hour,
        "day" => TUnit::Day,
        "week" => TUnit::Week,
        "month" => TUnit::Month,
        "year" => TUnit::Year,
        _ => return None,
    })
}

fn tunit_days(u: TUnit) -> f64 {
    match u {
        TUnit::Minute => 1.0 / 1440.0,
        TUnit::Hour => 1.0 / 24.0,
        TUnit::Day => 1.0,
        TUnit::Week => 7.0,
        TUnit::Month => 365.25 / 12.0,
        TUnit::Year => 365.25,
    }
}

const AUTO_TSTEPS: &[(TUnit, i64)] = &[
    (TUnit::Minute, 1),
    (TUnit::Minute, 2),
    (TUnit::Minute, 5),
    (TUnit::Minute, 10),
    (TUnit::Minute, 15),
    (TUnit::Minute, 30),
    (TUnit::Hour, 1),
    (TUnit::Hour, 2),
    (TUnit::Hour, 3),
    (TUnit::Hour, 6),
    (TUnit::Hour, 12),
    (TUnit::Day, 1),
    (TUnit::Day, 2),
    (TUnit::Week, 1),
    (TUnit::Week, 2),
    (TUnit::Month, 1),
    (TUnit::Month, 2),
    (TUnit::Month, 3),
    (TUnit::Month, 6),
    (TUnit::Year, 1),
    (TUnit::Year, 2),
    (TUnit::Year, 5),
    (TUnit::Year, 10),
    (TUnit::Year, 20),
    (TUnit::Year, 50),
    (TUnit::Year, 100),
    (TUnit::Year, 200),
    (TUnit::Year, 500),
    (TUnit::Year, 1000),
];

pub fn auto_tstep(span: f64) -> (TUnit, i64) {
    for &(u, n) in AUTO_TSTEPS {
        if span / (n as f64 * tunit_days(u)) <= 5.0 + 1e-9 {
            return (u, n);
        }
    }
    (TUnit::Year, 1000)
}

// a time axis draws at most this many ticks
const MAX_TTICKS: usize = 4000;

pub fn time_ticks(lo: f64, hi: f64, u: TUnit, n: i64) -> Vec<f64> {
    let (lo, hi) = if lo <= hi { (lo, hi) } else { (hi, lo) };
    let n = n.max(1);
    let eps = 1e-9;
    let mut out = Vec::new();
    match u {
        TUnit::Minute | TUnit::Hour | TUnit::Day => {
            let per = match u {
                TUnit::Minute => 1440.0,
                TUnit::Hour => 24.0,
                _ => 1.0,
            };
            // whole units since the epoch, on multiples of n
            let a = (lo * per - eps).ceil() as i64;
            let b = (hi * per + eps).floor() as i64;
            let mut k = a.div_euclid(n) * n;
            if k < a {
                k += n;
            }
            while k <= b && out.len() < MAX_TTICKS {
                out.push(k as f64 / per);
                k += n;
            }
        }
        TUnit::Week => {
            // weeks start on Monday (1970-01-05 is day 4)
            let step = 7 * n;
            let a = (lo - eps).ceil() as i64;
            let b = (hi + eps).floor() as i64;
            let mut k = 4 + (a - 4).div_euclid(step) * step;
            if k < a {
                k += step;
            }
            while k <= b && out.len() < MAX_TTICKS {
                out.push(k as f64);
                k += step;
            }
        }
        TUnit::Month => {
            // from the first month boundary on or after the start
            let (y0, m0, d0) = civil_from_days(lo.floor() as i64);
            let (mut y, mut m) = (y0, m0);
            let first = days_from_civil(y0, m0, 1) as f64;
            if !(d0 == 1 && (lo - first).abs() < eps) {
                m += 1;
                if m > 12 {
                    m = 1;
                    y += 1;
                }
            }
            while out.len() < MAX_TTICKS {
                let d = days_from_civil(y, m, 1) as f64;
                if d > hi + eps {
                    break;
                }
                out.push(d);
                m += n;
                while m > 12 {
                    m -= 12;
                    y += 1;
                }
            }
        }
        TUnit::Year => {
            // years on multiples of n
            let (y0, _, _) = civil_from_days(lo.floor() as i64);
            let mut y = y0.div_euclid(n) * n;
            while out.len() < MAX_TTICKS {
                let d = days_from_civil(y, 1, 1) as f64;
                if d > hi + eps {
                    break;
                }
                if d >= lo - eps {
                    out.push(d);
                }
                y += n;
            }
        }
    }
    if out.is_empty() {
        out = vec![lo, hi];
    }
    out
}

pub fn time_label(v: f64, u: TUnit) -> String {
    let p = match u {
        TUnit::Minute | TUnit::Hour => "hour",
        TUnit::Day | TUnit::Week => "day",
        TUnit::Month => "month",
        TUnit::Year => "year",
    };
    fmt_date_preset(v, p)
}
