//! Exact decimal values and ECMA-402 rounding for Intl.NumberFormat.
//!
//! A [`Decimal`] is a non-negative value `0.d1 d2 ... dn × 10^point` (so
//! `point` digits are in front of the decimal point); `digits` has no
//! leading or trailing zeros and is empty for zero.  Numbers are converted
//! with their shortest round-trip representation (so `1.005` is the decimal
//! 1.005, like the original), BigInts and numeric strings exactly.

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Decimal {
    pub digits: Vec<u8>,
    pub point: i32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
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
    pub fn parse(s: &str) -> Option<RoundingMode> {
        Some(match s {
            "ceil" => RoundingMode::Ceil,
            "floor" => RoundingMode::Floor,
            "expand" => RoundingMode::Expand,
            "trunc" => RoundingMode::Trunc,
            "halfCeil" => RoundingMode::HalfCeil,
            "halfFloor" => RoundingMode::HalfFloor,
            "halfExpand" => RoundingMode::HalfExpand,
            "halfTrunc" => RoundingMode::HalfTrunc,
            "halfEven" => RoundingMode::HalfEven,
            _ => return None,
        })
    }

    /// Whether to round the magnitude up.  `cmp`: discarded part compared
    /// with one half unit (-1, 0, 1); `nonzero`: discarded part is non-zero.
    fn round_up(self, neg: bool, cmp: i32, nonzero: bool, last_odd: bool) -> bool {
        match self {
            RoundingMode::Ceil => nonzero && !neg,
            RoundingMode::Floor => nonzero && neg,
            RoundingMode::Expand => nonzero,
            RoundingMode::Trunc => false,
            RoundingMode::HalfCeil => cmp > 0 || (cmp == 0 && !neg),
            RoundingMode::HalfFloor => cmp > 0 || (cmp == 0 && neg),
            RoundingMode::HalfExpand => cmp >= 0,
            RoundingMode::HalfTrunc => cmp > 0,
            RoundingMode::HalfEven => cmp > 0 || (cmp == 0 && last_odd),
        }
    }
}

impl Decimal {
    pub fn zero() -> Decimal {
        Decimal { digits: Vec::new(), point: 0 }
    }

    pub fn is_zero(&self) -> bool {
        self.digits.is_empty()
    }

    /// Strip leading / trailing zeros.
    pub fn normalize(mut self) -> Decimal {
        let lead = self.digits.iter().take_while(|&&d| d == 0).count();
        if lead == self.digits.len() {
            return Decimal::zero();
        }
        if lead > 0 {
            self.digits.drain(..lead);
            self.point -= lead as i32;
        }
        while self.digits.last() == Some(&0) {
            self.digits.pop();
        }
        self
    }

    /// |x| of a finite double (shortest round-trip digits).
    pub fn from_f64(x: f64) -> Decimal {
        let x = x.abs();
        if x == 0.0 || !x.is_finite() {
            return Decimal::zero();
        }
        let s = format!("{:e}", x);
        let (mant, exp) = match s.split_once('e') {
            Some((m, e)) => (m, e.parse::<i32>().unwrap_or(0)),
            None => (s.as_str(), 0),
        };
        let digits: Vec<u8> = mant.bytes().filter(|b| b.is_ascii_digit()).map(|b| b - b'0').collect();
        Decimal { digits, point: exp + 1 }.normalize()
    }

    /// From a string of ASCII decimal digits (an integer magnitude).
    pub fn from_int_str(s: &str) -> Decimal {
        let digits: Vec<u8> = s.bytes().filter(|b| b.is_ascii_digit()).map(|b| b - b'0').collect();
        let n = digits.len() as i32;
        Decimal { digits, point: n }.normalize()
    }

    /// Integer value from digits in another radix (hex/octal/binary literals).
    fn from_radix(s: &str, radix: u32) -> Option<Decimal> {
        if s.is_empty() {
            return None;
        }
        // little-endian base-10^9 limbs
        let mut limbs: Vec<u64> = vec![0];
        for c in s.chars() {
            let d = c.to_digit(radix)? as u64;
            let mut carry = d;
            for l in limbs.iter_mut() {
                let v = *l * radix as u64 + carry;
                *l = v % 1_000_000_000;
                carry = v / 1_000_000_000;
            }
            while carry > 0 {
                limbs.push(carry % 1_000_000_000);
                carry /= 1_000_000_000;
            }
        }
        let mut out = String::new();
        for (i, l) in limbs.iter().rev().enumerate() {
            if i == 0 {
                out.push_str(&l.to_string());
            } else {
                out.push_str(&format!("{:09}", l));
            }
        }
        Some(Decimal::from_int_str(&out))
    }

    /// Exact value of a StringNumericLiteral: Some((negative, value)) for
    /// finite values; Err(Some(neg)) for ±Infinity; Err(None) for NaN.
    pub fn parse_numeric_string(s: &str) -> Result<(bool, Decimal), Option<bool>> {
        let t = s.trim_matches(|c: char| crate::unicode::is_js_whitespace(c as u32) || crate::unicode::is_line_terminator(c as u32));
        if t.is_empty() {
            return Ok((false, Decimal::zero()));
        }
        let lower = t.to_ascii_lowercase();
        for (p, r) in [("0x", 16), ("0o", 8), ("0b", 2)] {
            if lower.starts_with(p) {
                return match Decimal::from_radix(&t[2..], r) {
                    Some(d) => Ok((false, d)),
                    None => Err(None),
                };
            }
        }
        let (neg, body) = match t.as_bytes()[0] {
            b'-' => (true, &t[1..]),
            b'+' => (false, &t[1..]),
            _ => (false, t),
        };
        if body == "Infinity" {
            return Err(Some(neg));
        }
        let (mant, exp) = match body.find(|c| c == 'e' || c == 'E') {
            Some(i) => {
                let e = &body[i + 1..];
                let ev = {
                    let (es, eb) = match e.as_bytes().first() {
                        Some(b'-') => (-1i64, &e[1..]),
                        Some(b'+') => (1, &e[1..]),
                        _ => (1, e),
                    };
                    if eb.is_empty() || !eb.bytes().all(|b| b.is_ascii_digit()) {
                        return Err(None);
                    }
                    let v: i64 = eb.parse::<i64>().unwrap_or(i64::MAX / 4).min(1_000_000_000);
                    es * v
                };
                (&body[..i], ev)
            }
            None => (body, 0),
        };
        let (ip, fp) = match mant.find('.') {
            Some(i) => (&mant[..i], &mant[i + 1..]),
            None => (mant, ""),
        };
        if (ip.is_empty() && fp.is_empty())
            || !ip.bytes().all(|b| b.is_ascii_digit())
            || !fp.bytes().all(|b| b.is_ascii_digit())
        {
            return Err(None);
        }
        let mut digits: Vec<u8> = ip.bytes().map(|b| b - b'0').collect();
        digits.extend(fp.bytes().map(|b| b - b'0'));
        let point = ip.len() as i64 + exp;
        let point = point.clamp(-2_000_000_000, 2_000_000_000) as i32;
        let d = Decimal { digits, point }.normalize();
        Ok((neg, d))
    }

    /// Multiply by 10^k.
    pub fn shift(&self, k: i32) -> Decimal {
        if self.is_zero() {
            return Decimal::zero();
        }
        Decimal { digits: self.digits.clone(), point: self.point + k }
    }

    /// floor(log10(x)) for x != 0.
    pub fn magnitude(&self) -> i32 {
        self.point - 1
    }

    /// Number of fraction digits needed to write the value exactly.
    pub fn frac_len(&self) -> i32 {
        (self.digits.len() as i32 - self.point).max(0)
    }

    /// Is the value an integer?
    pub fn is_integer(&self) -> bool {
        self.frac_len() == 0
    }

    pub fn to_f64(&self) -> f64 {
        if self.is_zero() {
            return 0.0;
        }
        let mut s = String::from("0.");
        for d in &self.digits {
            s.push((b'0' + d) as char);
        }
        s.push('e');
        s.push_str(&self.point.to_string());
        s.parse::<f64>().unwrap_or(0.0)
    }

    /// Round to `frac` fraction digits (negative: to tens, hundreds...).
    pub fn round_frac(&self, frac: i32, mode: RoundingMode, neg: bool) -> Decimal {
        if self.is_zero() {
            return Decimal::zero();
        }
        let keep = self.point as i64 + frac as i64; // digits kept
        let n = self.digits.len() as i64;
        if keep >= n {
            return self.clone();
        }
        let (kept, rest): (&[u8], &[u8]) = if keep <= 0 { (&[], &self.digits[..]) } else { self.digits.split_at(keep as usize) };
        // compare the discarded part with one half
        let cmp = if keep < 0 {
            -1
        } else {
            let first = rest[0];
            if first > 5 {
                1
            } else if first < 5 {
                -1
            } else if rest[1..].iter().any(|&d| d != 0) {
                1
            } else {
                0
            }
        };
        let last_odd = kept.last().map(|d| d % 2 == 1).unwrap_or(false);
        let up = mode.round_up(neg, cmp, true, last_odd);
        // value at the rounding position: unit = 10^(-frac)
        let mut digits: Vec<u8> = kept.to_vec();
        let mut point = self.point;
        if keep < 0 {
            digits.clear();
        }
        if up {
            // add one unit at position `keep` (index keep-1)
            let len = keep.max(0) as usize;
            if digits.len() < len {
                digits.resize(len, 0);
            }
            if len == 0 {
                // the unit is 10^(-frac)
                return Decimal { digits: vec![1], point: 1 - frac };
            }
            let mut i = len;
            loop {
                if i == 0 {
                    digits.insert(0, 1);
                    point += 1;
                    break;
                }
                i -= 1;
                if digits[i] == 9 {
                    digits[i] = 0;
                } else {
                    digits[i] += 1;
                    break;
                }
            }
        }
        Decimal { digits, point }.normalize()
    }

    /// Round to `sig` significant digits.
    pub fn round_sig(&self, sig: i32, mode: RoundingMode, neg: bool) -> Decimal {
        if self.is_zero() {
            return Decimal::zero();
        }
        self.round_frac(sig - self.point, mode, neg)
    }

    /// Round to a multiple of `inc` × 10^(-frac).
    pub fn round_increment(&self, frac: i32, inc: u32, mode: RoundingMode, neg: bool) -> Decimal {
        if inc <= 1 {
            return self.round_frac(frac, mode, neg);
        }
        if self.is_zero() {
            return Decimal::zero();
        }
        // n = self × 10^frac: integer part digits + remainder
        let scaled = self.shift(frac);
        let int_len = scaled.point.max(0) as usize;
        let mut int_digits: Vec<u8> = Vec::with_capacity(int_len);
        for i in 0..int_len {
            int_digits.push(*scaled.digits.get(i).unwrap_or(&0));
        }
        let frac_nonzero = scaled.digits.len() > int_len;
        // divide the integer part by inc
        let mut q: Vec<u8> = Vec::with_capacity(int_digits.len());
        let mut r: u64 = 0;
        for d in &int_digits {
            r = r * 10 + *d as u64;
            q.push((r / inc as u64) as u8);
            r %= inc as u64;
        }
        // remainder (r + fraction) compared with inc/2
        let twice = 2 * r;
        let cmp = if twice > inc as u64 {
            1
        } else if twice < inc as u64 {
            -1
        } else if frac_nonzero {
            1
        } else {
            0
        };
        let nonzero = r > 0 || frac_nonzero;
        let qd = Decimal::from_int_str(&q.iter().map(|d| (b'0' + d) as char).collect::<String>());
        let last_odd = q.last().map(|d| d % 2 == 1).unwrap_or(false);
        let mut quotient = qd;
        if nonzero && mode.round_up(neg, cmp, nonzero, last_odd) {
            quotient = quotient.add_one();
        }
        // multiply back by inc × 10^-frac
        quotient.mul_small(inc).shift(-frac)
    }

    fn add_one(&self) -> Decimal {
        // integer + 1
        if self.is_zero() {
            return Decimal { digits: vec![1], point: 1 };
        }
        let mut digits = self.digits.clone();
        let len = self.point.max(0) as usize;
        digits.resize(len, 0);
        let mut point = self.point;
        let mut i = len;
        loop {
            if i == 0 {
                digits.insert(0, 1);
                point += 1;
                break;
            }
            i -= 1;
            if digits[i] == 9 {
                digits[i] = 0;
            } else {
                digits[i] += 1;
                break;
            }
        }
        Decimal { digits, point }.normalize()
    }

    fn mul_small(&self, m: u32) -> Decimal {
        if self.is_zero() || m == 0 {
            return Decimal::zero();
        }
        let mut out: Vec<u8> = Vec::new();
        let mut carry: u64 = 0;
        for d in self.digits.iter().rev() {
            let v = *d as u64 * m as u64 + carry;
            out.push((v % 10) as u8);
            carry = v / 10;
        }
        let mut extra = 0;
        while carry > 0 {
            out.push((carry % 10) as u8);
            carry /= 10;
            extra += 1;
        }
        out.reverse();
        Decimal { digits: out, point: self.point + extra }.normalize()
    }

    /// Digits of the integer part (at least "0").
    pub fn int_string(&self) -> String {
        if self.point <= 0 {
            return "0".to_string();
        }
        let mut s = String::with_capacity(self.point as usize);
        for i in 0..self.point as usize {
            s.push((b'0' + self.digits.get(i).copied().unwrap_or(0)) as char);
        }
        s
    }

    /// Fraction digits (exact, no padding).
    pub fn frac_string(&self) -> String {
        let mut s = String::new();
        let fl = self.frac_len();
        for k in 0..fl {
            let idx = self.point as i64 + k as i64;
            let d = if idx < 0 { 0 } else { self.digits.get(idx as usize).copied().unwrap_or(0) };
            s.push((b'0' + d) as char);
        }
        s
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn s(d: &Decimal) -> String {
        let f = d.frac_string();
        if f.is_empty() {
            d.int_string()
        } else {
            format!("{}.{}", d.int_string(), f)
        }
    }
    #[test]
    fn rounding() {
        let x = Decimal::from_f64(1.005);
        assert_eq!(s(&x.round_frac(2, RoundingMode::HalfExpand, false)), "1.01");
        let y = Decimal::from_f64(99.995);
        assert_eq!(s(&y.round_frac(2, RoundingMode::HalfExpand, false)), "100");
        let z = Decimal::from_f64(0.004);
        assert_eq!(s(&z.round_frac(2, RoundingMode::HalfExpand, false)), "0");
        assert_eq!(s(&z.round_frac(2, RoundingMode::Ceil, false)), "0.01");
        let w = Decimal::from_f64(1234.5678);
        assert_eq!(s(&w.round_increment(2, 25, RoundingMode::HalfExpand, false)), "1234.5");
        assert_eq!(s(&Decimal::from_f64(123.456).round_increment(0, 50, RoundingMode::HalfExpand, false)), "100");
        assert_eq!(s(&Decimal::from_f64(2.5).round_frac(0, RoundingMode::HalfEven, false)), "2");
        assert_eq!(s(&Decimal::from_f64(123456.0).round_sig(2, RoundingMode::HalfExpand, false)), "120000");
    }
}
