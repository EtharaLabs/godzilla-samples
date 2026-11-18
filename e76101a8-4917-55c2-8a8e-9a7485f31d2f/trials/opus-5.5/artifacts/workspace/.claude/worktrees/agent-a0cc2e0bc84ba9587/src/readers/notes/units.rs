//! Lengths as drawings letter them: in the project's units (mm, cm, m, fractional inches, decimal
//! feet, feet and fractional inches) or a dimension type's own, to its decimals.

use crate::project::Project;

/// The project's length units.
pub fn project_units(pr: &Project) -> String {
    pr.get("units").and_then(|v| v.as_str()).unwrap_or("mm").to_string()
}

fn round_to(x: f64, decimals: u32) -> f64 {
    let k = 10f64.powi(decimals as i32);
    (x * k).round() / k
}

/// Rust's shortest display of a number (`100` for 100.0, `123.5`), no sign on zero.
pub fn shortest(x: f64) -> String {
    let x = if x == 0.0 { 0.0 } else { x };
    format!("{}", x)
}

fn fixed(x: f64, decimals: u32) -> String {
    let v = round_to(x, decimals);
    let v = if v == 0.0 { 0.0 } else { v };
    format!("{:.*}", decimals as usize, v)
}

fn gcd(a: i64, b: i64) -> i64 {
    if b == 0 {
        a
    } else {
        gcd(b, a % b)
    }
}

/// Sixteenths of an inch, `n` of them, as a fraction (`3/8`), or None for none.
fn fraction(n: i64) -> Option<String> {
    if n == 0 {
        return None;
    }
    let g = gcd(n, 16);
    Some(format!("{}/{}", n / g, 16 / g))
}

/// Inches to the nearest sixteenth: `39 3/8"`, `1/8"`, `0"`.
fn inches(mm: f64) -> String {
    let n = (mm / 25.4 * 16.0).round() as i64;
    let neg = n < 0;
    let n = n.abs();
    let whole = n / 16;
    let frac = fraction(n % 16);
    let s = match (whole, frac) {
        (0, Some(f)) => format!("{}\"", f),
        (w, Some(f)) => format!("{} {}\"", w, f),
        (w, None) => format!("{}\"", w),
    };
    if neg {
        format!("-{}", s)
    } else {
        s
    }
}

/// Feet and inches to the nearest sixteenth: `3'-3 3/8"`, `0'-0 1/8"`, `10'-0"`.
fn feet_inches(mm: f64) -> String {
    let n = (mm / 25.4 * 16.0).round() as i64;
    let neg = n < 0;
    let n = n.abs();
    let feet = n / 192;
    let rem = n % 192;
    let whole = rem / 16;
    let s = match fraction(rem % 16) {
        Some(f) => format!("{}'-{} {}\"", feet, whole, f),
        None => format!("{}'-{}\"", feet, whole),
    };
    if neg {
        format!("-{}", s)
    } else {
        s
    }
}

/// A length in mm as a drawing letters it in `units`, to `decimals` where they're given (decimal
/// units only).
pub fn length_text(mm: f64, units: &str, decimals: Option<u64>) -> String {
    let d = decimals.map(|d| d.min(12) as u32);
    match units {
        "cm" => match d {
            Some(d) => fixed(mm / 10.0, d),
            None => shortest(round_to(mm / 10.0, 1)),
        },
        "m" => fixed(mm / 1000.0, d.unwrap_or(2)),
        "in" => inches(mm),
        "ft" => format!("{}'", fixed(mm / 304.8, d.unwrap_or(2))),
        "ft-in" => feet_inches(mm),
        _ => fixed(mm, d.unwrap_or(0)),
    }
}
