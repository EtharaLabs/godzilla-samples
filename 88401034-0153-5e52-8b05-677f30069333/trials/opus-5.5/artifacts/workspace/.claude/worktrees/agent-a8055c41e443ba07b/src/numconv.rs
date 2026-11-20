//! JS Number <-> String conversions (std only).
//!
//! Every function here was differential-tested against the original `lumen` binary (the
//! source of truth) and against node. Behaviour of the original that differs from V8 and
//! is reproduced on purpose:
//!
//! * `number_to_string` produces the shortest round-trip digits exactly like Rust's `{:e}`
//!   formatting. When two shortest candidates are equally close to the exact value, Rust
//!   (and lumen) choose the upper one where V8 chooses the even one:
//!   `0.78672027587890625` prints as `"0.7867202758789063"` (V8: `...062`), and
//!   `3.30530548095703125` as `"3.3053054809570313"` (V8: `...312`). The same digits are
//!   used by `to_exponential(x, None)`.
//! * `to_precision` rounds exact decimal ties half-to-even (what Rust's `{:.*e}` does):
//!   `(2.5).toPrecision(1) == "2"`, `(0.125).toPrecision(2) == "0.12"`,
//!   `(-2.5).toPrecision(1) == "-2"` (V8 rounds half up: "3", "0.13", "-3").
//!   `to_fixed` and `to_exponential(x, Some(_))` round half up as the spec says
//!   (`(2.5).toFixed(0) == "3"`, `(25).toExponential(0) == "3e+1"`).
//! * `number_to_string_radix` (radix != 10) is NOT V8's DoubleToRadixCString. The integer
//!   part is `trunc(|x|) as u64` (saturating: every |x| >= 2^64 prints as u64::MAX, e.g.
//!   `(1e21).toString(16) == "ffffffffffffffff"`), printed exactly. The fraction is produced
//!   by repeatedly multiplying by the radix in f64 and peeling off the integer digit, stopping
//!   when the fraction becomes 0 or after 52 digits (no rounding, trailing zeros kept):
//!   `(0.1).toString(2)` has 52 fraction digits, `(1e-300).toString(2) == "0." + 52 zeros`,
//!   `Math.PI.toString(36) == "3.53i5ab8p5fc5vayqter60f6r"`.
//! * `parse_int` accumulates digits in f64 (`acc = acc * radix + digit`) for every radix, so
//!   long inputs are not correctly rounded:
//!   `parseInt("123456789012345678901234567890") == 1.2345678901234566e+29` (V8: ...68e+29).
//! * `string_to_number` uses the same f64 accumulation for `0x`/`0o`/`0b` strings
//!   (`Number("0x8000000000000401") == 9223372036854775808`); decimal strings are correctly
//!   rounded.
//! * `parse_numeric_literal`: `0x`/`0o`/`0b` literals are accumulated in u64 and converted with
//!   correct rounding; a value above u64::MAX returns `None` (lumen reports
//!   "SyntaxError: invalid numeric literal"). Legacy octal literals (`0777`) are accumulated
//!   in i64 and silently become 0 when they overflow i64. A literal starting with `0` that
//!   contains `8`, `9`, `.` or an exponent is decimal (`08` = 8, `07.5` = 7.5, `017e1` = 170).
//! * Whitespace trimmed by `string_to_number`/`parse_float`/`parse_int` (see
//!   [`is_js_whitespace`]) is Rust's `char::is_whitespace` set plus U+FEFF: U+0009-U+000D,
//!   U+0020, U+0085, U+00A0, U+1680, U+2000-U+200A, U+2028, U+2029, U+202F, U+205F, U+3000,
//!   U+FEFF. U+0085 (NEL) is not JS whitespace, but lumen trims it here and in
//!   `String.prototype.trim` (`Number("\u0085 5") == 5`); its RegExp `\s` does not match it.
//!   U+180E and U+200B are not whitespace.

#![allow(dead_code)]

/// RangeError text of lumen's `toFixed` (range checked before NaN, as in the spec:
/// `NaN.toFixed(101)` throws).
pub const MSG_TO_FIXED_RANGE: &str = "toFixed() digits argument must be between 0 and 100";
/// RangeError text of `toExponential` (checked after NaN/Infinity: `NaN.toExponential(101)`
/// is "NaN").
pub const MSG_TO_EXPONENTIAL_RANGE: &str = "toExponential() argument must be between 0 and 100";
/// RangeError text of `toPrecision` (checked after NaN/Infinity; undefined precision means
/// ToString).
pub const MSG_TO_PRECISION_RANGE: &str = "toPrecision() argument must be between 1 and 100";
/// RangeError text of `Number.prototype.toString(radix)` (BigInt's lacks the parentheses).
pub const MSG_TO_STRING_RADIX: &str = "toString() radix must be between 2 and 36";
/// TypeError text when a Number.prototype method gets a non-Number `this`.
pub const MSG_NUMBER_INCOMPATIBLE_RECEIVER: &str = "Number method called on incompatible receiver";

/// Lowercase digit characters for radix output.
const DIGITS: &[u8; 36] = b"0123456789abcdefghijklmnopqrstuvwxyz";

// ---------------------------------------------------------------------------------------
// Whitespace
// ---------------------------------------------------------------------------------------

/// lumen's StrWhiteSpaceChar set (used by ToNumber, parseInt, parseFloat, StringToBigInt and
/// String.prototype.trim): JS `WhiteSpace`/`LineTerminator` plus U+0085, i.e. Rust's
/// `char::is_whitespace` plus U+FEFF.
pub fn is_js_whitespace(c: u16) -> bool {
    matches!(
        c,
        0x0009..=0x000D
            | 0x0020
            | 0x0085
            | 0x00A0
            | 0x1680
            | 0x2000..=0x200A
            | 0x2028
            | 0x2029
            | 0x202F
            | 0x205F
            | 0x3000
            | 0xFEFF
    )
}

/// Trim JS whitespace from both ends.
pub fn trim_js_whitespace(s: &[u16]) -> &[u16] {
    let start = s.iter().position(|&c| !is_js_whitespace(c)).unwrap_or(s.len());
    let end = s.iter().rposition(|&c| !is_js_whitespace(c)).map_or(start, |i| i + 1);
    &s[start..end]
}

fn trim_js_whitespace_start(s: &[u16]) -> &[u16] {
    let start = s.iter().position(|&c| !is_js_whitespace(c)).unwrap_or(s.len());
    &s[start..]
}

// ---------------------------------------------------------------------------------------
// Number -> String
// ---------------------------------------------------------------------------------------

/// Fixed-capacity stack buffer for `write!` (avoids a heap allocation per conversion).
struct StackBuf {
    buf: [u8; 192],
    len: usize,
}

impl StackBuf {
    fn new() -> Self {
        StackBuf { buf: [0; 192], len: 0 }
    }

    fn bytes(&self) -> &[u8] {
        &self.buf[..self.len]
    }
}

impl std::fmt::Write for StackBuf {
    fn write_str(&mut self, s: &str) -> std::fmt::Result {
        let b = s.as_bytes();
        let end = self.len + b.len();
        if end > self.buf.len() {
            return Err(std::fmt::Error);
        }
        self.buf[self.len..end].copy_from_slice(b);
        self.len = end;
        Ok(())
    }
}

/// Decimal digits in scientific form: value = d1.d2..dlen * 10^exp (ASCII digits).
struct DecDigits {
    buf: [u8; 128],
    len: usize,
    exp: i32,
}

impl DecDigits {
    fn digits(&self) -> &[u8] {
        &self.buf[..self.len]
    }

    fn from_ascii(d: &[u8], exp: i32) -> DecDigits {
        let mut buf = [b'0'; 128];
        let len = d.len().min(128);
        buf[..len].copy_from_slice(&d[..len]);
        DecDigits { buf, len, exp }
    }

    /// Parses Rust's `{:e}` / `{:.*e}` output, e.g. "1.2345e-7".
    fn from_rust_sci(s: &[u8]) -> DecDigits {
        let mut buf = [b'0'; 128];
        let mut len = 0;
        let mut i = 0;
        while i < s.len() && s[i] != b'e' {
            if s[i].is_ascii_digit() && len < buf.len() {
                buf[len] = s[i];
                len += 1;
            }
            i += 1;
        }
        i += 1;
        let neg = i < s.len() && s[i] == b'-';
        if neg {
            i += 1;
        }
        let mut exp: i32 = 0;
        while i < s.len() && s[i].is_ascii_digit() {
            exp = exp * 10 + (s[i] - b'0') as i32;
            i += 1;
        }
        DecDigits { buf, len, exp: if neg { -exp } else { exp } }
    }
}

/// Rust's scientific formatting of a finite positive double: shortest round-trip digits for
/// `None`, otherwise exactly `frac + 1` significant digits correctly rounded (ties to even).
fn rust_sci(a: f64, frac: Option<usize>) -> Option<DecDigits> {
    use std::fmt::Write as _;
    let mut buf = StackBuf::new();
    let ok = match frac {
        None => write!(buf, "{:e}", a),
        Some(f) => write!(buf, "{:.*e}", f, a),
    };
    ok.ok().map(|_| DecDigits::from_rust_sci(buf.bytes()))
}

/// Shortest round-trip digits (lumen/Rust tie-breaking, see module docs).
fn shortest(a: f64) -> DecDigits {
    rust_sci(a, None).unwrap_or_else(|| DecDigits::from_ascii(b"0", 0))
}

/// `a = m * 2^e` with `m` odd (finite, non-zero `a`).
fn odd_mantissa(a: f64) -> (u64, i32) {
    let bits = a.to_bits();
    let biased = ((bits >> 52) & 0x7ff) as i32;
    let fraction = bits & ((1u64 << 52) - 1);
    let (m, e) = if biased == 0 {
        (fraction, -1074)
    } else {
        (fraction | (1u64 << 52), biased - 1075)
    };
    if m == 0 {
        return (0, 0);
    }
    let tz = m.trailing_zeros();
    (m >> tz, e + tz as i32)
}

/// Is `a * 10^k` exactly halfway between two integers (i.e. is `2 * a * 10^k` an odd
/// integer)? `a = m * 2^e`, `m` odd. Only then can half-up and half-even rounding differ.
fn is_exact_tie(m: u64, e: i32, k: i32) -> bool {
    if m == 0 || e + 1 + k != 0 {
        return false;
    }
    if k >= 0 {
        true // 2 * a * 10^k = m * 5^k, odd
    } else {
        // 2 * a * 10^k = m / 5^-k: an odd integer iff 5^-k divides m (m < 2^53 < 5^23)
        let j = (-k) as u32;
        j <= 22 && m % 5u64.pow(j) == 0
    }
}

fn push_exponent(out: &mut String, e: i32) {
    out.push('e');
    out.push(if e < 0 { '-' } else { '+' });
    out.push_str(&e.unsigned_abs().to_string());
}

fn push_ascii(out: &mut String, digits: &[u8]) {
    // Digits are always ASCII, so this cannot fail.
    out.push_str(std::str::from_utf8(digits).unwrap_or(""));
}

/// Number::toString(x) (radix 10) / ToString(Number).
pub fn number_to_string(x: f64) -> String {
    if x.is_nan() {
        return "NaN".to_string();
    }
    if x == 0.0 {
        return "0".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 { "Infinity" } else { "-Infinity" }.to_string();
    }
    // Integers below 2^53: every digit is significant, so the shortest representation is
    // the plain integer.
    if x.abs() < 9007199254740992.0 && x.fract() == 0.0 {
        return (x as i64).to_string();
    }
    let mut out = String::with_capacity(24);
    if x < 0.0 {
        out.push('-');
    }
    let dd = shortest(x.abs());
    let digits = dd.digits();
    let n = dd.exp + 1;
    let k = digits.len() as i32;
    if k <= n && n <= 21 {
        push_ascii(&mut out, digits);
        for _ in 0..(n - k) {
            out.push('0');
        }
    } else if 0 < n && n <= 21 {
        push_ascii(&mut out, &digits[..n as usize]);
        out.push('.');
        push_ascii(&mut out, &digits[n as usize..]);
    } else if -6 < n && n <= 0 {
        out.push_str("0.");
        for _ in 0..(-n) {
            out.push('0');
        }
        push_ascii(&mut out, digits);
    } else {
        out.push(digits[0] as char);
        if k > 1 {
            out.push('.');
            push_ascii(&mut out, &digits[1..]);
        }
        push_exponent(&mut out, n - 1);
    }
    out
}

/// Number.prototype.toString(radix) for radix 2..=36 (radix 10, or an out-of-range radix,
/// falls back to [`number_to_string`]). Reproduces lumen's algorithm, see the module docs.
pub fn number_to_string_radix(x: f64, radix: u32) -> String {
    if radix == 10 || !(2..=36).contains(&radix) {
        return number_to_string(x);
    }
    if x.is_nan() {
        return "NaN".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 { "Infinity" } else { "-Infinity" }.to_string();
    }
    let mut out = String::new();
    if x < 0.0 {
        out.push('-');
    }
    let a = x.abs();
    let ip = a.trunc();
    let mut int_part = ip as u64; // saturating, as in lumen
    let mut frac = a - ip;
    let r = radix as u64;
    let mut buf = [0u8; 64];
    let mut i = buf.len();
    loop {
        i -= 1;
        buf[i] = DIGITS[(int_part % r) as usize];
        int_part /= r;
        if int_part == 0 {
            break;
        }
    }
    push_ascii(&mut out, &buf[i..]);
    if frac > 0.0 {
        out.push('.');
        let rf = radix as f64;
        let mut count = 0;
        while frac > 0.0 && count < 52 {
            frac *= rf;
            let d = frac.trunc();
            frac -= d;
            out.push(DIGITS[(d as usize).min(radix as usize - 1)] as char);
            count += 1;
        }
    }
    out
}

// ---------------------------------------------------------------------------------------
// Exact decimal expansion (for toFixed / toExponential / toPrecision)
// ---------------------------------------------------------------------------------------

/// Minimal unsigned big integer (little-endian u32 limbs) used for exact expansions.
struct SmallBig {
    limbs: Vec<u32>,
}

impl SmallBig {
    fn from_u64(v: u64) -> SmallBig {
        let mut limbs = vec![v as u32, (v >> 32) as u32];
        while limbs.last() == Some(&0) {
            limbs.pop();
        }
        SmallBig { limbs }
    }

    fn mul_small(&mut self, m: u32) {
        let mut carry: u64 = 0;
        for l in self.limbs.iter_mut() {
            let t = (*l as u64) * (m as u64) + carry;
            *l = t as u32;
            carry = t >> 32;
        }
        if carry != 0 {
            self.limbs.push(carry as u32);
        }
    }

    fn mul_pow5(&mut self, mut k: u32) {
        const POW5_13: u32 = 1_220_703_125; // 5^13, the largest power of 5 below 2^32
        while k >= 13 {
            self.mul_small(POW5_13);
            k -= 13;
        }
        if k > 0 {
            self.mul_small(5u32.pow(k));
        }
    }

    fn shl(&mut self, bits: u32) {
        let words = (bits / 32) as usize;
        let rem = bits % 32;
        if rem != 0 {
            let mut carry = 0u32;
            for l in self.limbs.iter_mut() {
                let nl = (*l << rem) | carry;
                carry = *l >> (32 - rem);
                *l = nl;
            }
            if carry != 0 {
                self.limbs.push(carry);
            }
        }
        if words > 0 {
            let mut v = vec![0u32; words];
            v.extend_from_slice(&self.limbs);
            self.limbs = v;
        }
    }

    /// Decimal digits (values 0..=9, most significant first) of a non-zero number.
    fn into_decimal(mut self) -> Vec<u8> {
        const BASE: u64 = 1_000_000_000;
        let mut chunks: Vec<u32> = Vec::with_capacity(self.limbs.len() * 32 / 29 + 1);
        while !self.limbs.is_empty() {
            let mut rem: u64 = 0;
            for l in self.limbs.iter_mut().rev() {
                let cur = (rem << 32) | (*l as u64);
                *l = (cur / BASE) as u32;
                rem = cur % BASE;
            }
            chunks.push(rem as u32);
            while self.limbs.last() == Some(&0) {
                self.limbs.pop();
            }
        }
        let mut out = Vec::with_capacity(chunks.len() * 9);
        for (idx, &c) in chunks.iter().rev().enumerate() {
            let mut tmp = [0u8; 9];
            let mut v = c;
            for slot in tmp.iter_mut().rev() {
                *slot = (v % 10) as u8;
                v /= 10;
            }
            if idx == 0 {
                let skip = tmp.iter().position(|&d| d != 0).unwrap_or(8);
                out.extend_from_slice(&tmp[skip..]);
            } else {
                out.extend_from_slice(&tmp);
            }
        }
        out
    }
}

/// Exact decimal expansion of a finite positive double: value = 0.d1 d2 ... dk * 10^point,
/// with d1 != 0 and dk != 0 (digit values 0..=9).
struct ExactDecimal {
    digits: Vec<u8>,
    point: i32,
}

fn exact_decimal(a: f64) -> ExactDecimal {
    let (m, e) = odd_mantissa(a);
    if m == 0 {
        return ExactDecimal { digits: vec![0], point: 1 };
    }
    let mut big = SmallBig::from_u64(m);
    let (mut digits, point) = if e >= 0 {
        big.shl(e as u32);
        let d = big.into_decimal();
        let p = d.len() as i32;
        (d, p)
    } else {
        // m * 2^e = m * 5^-e / 10^-e
        big.mul_pow5((-e) as u32);
        let d = big.into_decimal();
        let p = d.len() as i32 + e;
        (d, p)
    };
    while digits.len() > 1 && digits.last() == Some(&0) {
        digits.pop();
    }
    ExactDecimal { digits, point }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Rounding {
    HalfUp,
    HalfEven,
}

/// Increment a digit string (values 0..=9) by one unit in the last place. Returns true if
/// a carry came out of the most significant digit (the digits are then all zero).
fn increment_digits(d: &mut [u8]) -> bool {
    for slot in d.iter_mut().rev() {
        if *slot == 9 {
            *slot = 0;
        } else {
            *slot += 1;
            return false;
        }
    }
    true
}

/// Round to exactly `p` (>= 1) significant digits. Returns ASCII digits and the decimal
/// exponent `e` such that the rounded value is d1.d2..dp * 10^e.
fn round_significant(dec: &ExactDecimal, p: usize, mode: Rounding) -> (Vec<u8>, i32) {
    let mut d: Vec<u8> = dec.digits.iter().take(p).copied().collect();
    d.resize(p, 0);
    let mut e = dec.point - 1;
    if dec.digits.len() > p {
        let next = dec.digits[p];
        let more = dec.digits.len() > p + 1; // digits are stripped of trailing zeros
        let up = match mode {
            Rounding::HalfUp => next >= 5,
            Rounding::HalfEven => next > 5 || (next == 5 && (more || d[p - 1] % 2 == 1)),
        };
        if up && increment_digits(&mut d) {
            d[0] = 1;
            e += 1;
        }
    }
    for c in d.iter_mut() {
        *c += b'0';
    }
    (d, e)
}

/// Exactly rounded significant digits via the bignum expansion.
fn exact_sci(a: f64, p: usize, mode: Rounding) -> DecDigits {
    let (d, e) = round_significant(&exact_decimal(a), p, mode);
    DecDigits::from_ascii(&d, e)
}

/// toFixed digits via the exact expansion with round-half-up: appends the digits of
/// round(a * 10^f) laid out with `f` fraction digits.
fn to_fixed_exact(a: f64, f: usize, out: &mut String) {
    // n = round-half-up(a * 10^f), as digit values.
    let mut n: Vec<u8> = Vec::new();
    if a != 0.0 {
        let dec = exact_decimal(a);
        let pos = dec.point + f as i32;
        if pos >= 0 {
            let pos = pos as usize;
            n = (0..pos).map(|i| dec.digits.get(i).copied().unwrap_or(0)).collect();
            let next = dec.digits.get(pos).copied().unwrap_or(0);
            // (An empty `n` - pos == 0 - "carries out" and becomes [1].)
            if next >= 5 && increment_digits(&mut n) {
                n.insert(0, 1);
            }
        }
    }
    // Strip leading zeros, keep at least one digit.
    let first = n.iter().position(|&d| d != 0).unwrap_or(n.len());
    let mut s: Vec<u8> = n[first..].iter().map(|d| d + b'0').collect();
    if s.is_empty() {
        s.push(b'0');
    }
    if f == 0 {
        push_ascii(out, &s);
        return;
    }
    if s.len() <= f {
        let mut padded = vec![b'0'; f + 1 - s.len()];
        padded.extend_from_slice(&s);
        s = padded;
    }
    let int_len = s.len() - f;
    push_ascii(out, &s[..int_len]);
    out.push('.');
    push_ascii(out, &s[int_len..]);
}

/// Number.prototype.toFixed(digits). The caller validates `digits` (0..=100).
pub fn to_fixed(x: f64, digits: u32) -> String {
    if x.is_nan() {
        return "NaN".to_string();
    }
    if !x.is_finite() || x.abs() >= 1e21 {
        return number_to_string(x);
    }
    let f = digits as usize;
    let mut out = String::new();
    if x < 0.0 {
        out.push('-');
    }
    let a = x.abs();
    // Rust's exact `{:.*}` rounds ties to even; it is used unless the value is an exact tie
    // at the rounding position, where JS rounds up.
    let (m, e) = odd_mantissa(a);
    if !is_exact_tie(m, e, f as i32) {
        use std::fmt::Write as _;
        let mut buf = StackBuf::new();
        if write!(buf, "{:.*}", f, a).is_ok() {
            push_ascii(&mut out, buf.bytes());
            return out;
        }
    }
    to_fixed_exact(a, f, &mut out);
    out
}

/// Number.prototype.toExponential(digits). `None` = as many digits as necessary (shortest
/// round-trip). The caller validates `digits` (0..=100).
pub fn to_exponential(x: f64, digits: Option<u32>) -> String {
    if x.is_nan() {
        return "NaN".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 { "Infinity" } else { "-Infinity" }.to_string();
    }
    let mut out = String::new();
    if x < 0.0 {
        out.push('-');
    }
    let a = x.abs();
    let dd = if a == 0.0 {
        let zeros = [b'0'; 101];
        DecDigits::from_ascii(&zeros[..(digits.unwrap_or(0) as usize + 1).min(101)], 0)
    } else {
        match digits {
            None => shortest(a),
            Some(f) => {
                let f = f as usize;
                // Rust rounds ties to even; JS rounds them up. The true decimal exponent is
                // the formatted one or one less (if rounding carried into a new digit).
                let (m, e) = odd_mantissa(a);
                match rust_sci(a, Some(f)) {
                    Some(dd)
                        if !is_exact_tie(m, e, f as i32 - dd.exp)
                            && !is_exact_tie(m, e, f as i32 - dd.exp + 1) =>
                    {
                        dd
                    }
                    _ => exact_sci(a, f + 1, Rounding::HalfUp),
                }
            }
        }
    };
    let d = dd.digits();
    out.push(d[0] as char);
    if d.len() > 1 {
        out.push('.');
        push_ascii(&mut out, &d[1..]);
    }
    push_exponent(&mut out, dd.exp);
    out
}

/// Number.prototype.toPrecision(precision). The caller validates `precision` (1..=100) and
/// handles an undefined precision (ToString). Exact ties round half-to-even (lumen quirk).
pub fn to_precision(x: f64, precision: u32) -> String {
    if x.is_nan() {
        return "NaN".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 { "Infinity" } else { "-Infinity" }.to_string();
    }
    let p = precision.clamp(1, 101) as usize;
    let mut out = String::new();
    if x < 0.0 {
        out.push('-');
    }
    let a = x.abs();
    let dd = if a == 0.0 {
        let zeros = [b'0'; 101];
        DecDigits::from_ascii(&zeros[..p], 0)
    } else {
        rust_sci(a, Some(p - 1)).unwrap_or_else(|| exact_sci(a, p, Rounding::HalfEven))
    };
    let d = dd.digits();
    let e = dd.exp;
    if e < -6 || e >= p as i32 {
        out.push(d[0] as char);
        if p > 1 {
            out.push('.');
            push_ascii(&mut out, &d[1..]);
        }
        push_exponent(&mut out, e);
    } else if e == p as i32 - 1 {
        push_ascii(&mut out, d);
    } else if e >= 0 {
        let k = e as usize + 1;
        push_ascii(&mut out, &d[..k]);
        out.push('.');
        push_ascii(&mut out, &d[k..]);
    } else {
        out.push_str("0.");
        for _ in 0..(-(e + 1)) {
            out.push('0');
        }
        push_ascii(&mut out, d);
    }
    out
}

// ---------------------------------------------------------------------------------------
// String -> Number
// ---------------------------------------------------------------------------------------

fn digit_value(c: u16) -> u32 {
    match c {
        0x30..=0x39 => (c - 0x30) as u32,
        0x61..=0x7A => (c - 0x61) as u32 + 10,
        0x41..=0x5A => (c - 0x41) as u32 + 10,
        _ => 99,
    }
}

/// Length of the longest prefix of `s` that is a StrUnsignedDecimalLiteral without the
/// `Infinity` alternative (digits, optional fraction, optional exponent); 0 if none.
fn scan_unsigned_decimal<T: Copy + Into<u32>>(s: &[T]) -> usize {
    let at = |i: usize| -> u32 { s.get(i).map_or(0, |&c| c.into()) };
    let is_digit = |c: u32| (0x30..=0x39).contains(&c);
    let mut i = 0;
    while i < s.len() && is_digit(at(i)) {
        i += 1;
    }
    let int_digits = i;
    let mut frac_digits = 0;
    if i < s.len() && at(i) == u32::from(b'.') {
        let mut k = i + 1;
        while k < s.len() && is_digit(at(k)) {
            k += 1;
        }
        frac_digits = k - (i + 1);
        if int_digits > 0 || frac_digits > 0 {
            i = k;
        }
    }
    if int_digits == 0 && frac_digits == 0 {
        return 0;
    }
    if i < s.len() && (at(i) == u32::from(b'e') || at(i) == u32::from(b'E')) {
        let mut k = i + 1;
        if k < s.len() && (at(k) == u32::from(b'+') || at(k) == u32::from(b'-')) {
            k += 1;
        }
        let start = k;
        while k < s.len() && is_digit(at(k)) {
            k += 1;
        }
        if k > start {
            i = k;
        }
    }
    i
}

/// Correctly rounded value of a validated unsigned decimal literal (ASCII bytes).
fn parse_decimal_ascii(b: &[u8]) -> f64 {
    if b.len() <= 15 && b.iter().all(|c| c.is_ascii_digit()) {
        let mut v: u64 = 0;
        for &c in b {
            v = v * 10 + (c - b'0') as u64;
        }
        return v as f64;
    }
    std::str::from_utf8(b)
        .ok()
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(f64::NAN)
}

fn parse_decimal_units(s: &[u16]) -> f64 {
    let mut stack = [0u8; 64];
    if s.len() <= stack.len() {
        for (slot, &c) in stack.iter_mut().zip(s) {
            *slot = c as u8;
        }
        parse_decimal_ascii(&stack[..s.len()])
    } else {
        let v: Vec<u8> = s.iter().map(|&c| c as u8).collect();
        parse_decimal_ascii(&v)
    }
}

fn starts_with_ascii(s: &[u16], lit: &[u8]) -> bool {
    s.len() >= lit.len() && s.iter().zip(lit).all(|(&a, &b)| a == b as u16)
}

/// ToNumber applied to a String (StringToNumber).
pub fn string_to_number(s: &[u16]) -> f64 {
    let t = trim_js_whitespace(s);
    if t.is_empty() {
        return 0.0;
    }
    if t.len() >= 2 && t[0] == u16::from(b'0') {
        let radix = match t[1] {
            0x78 | 0x58 => 16, // x X
            0x6F | 0x4F => 8,  // o O
            0x62 | 0x42 => 2,  // b B
            _ => 0,
        };
        if radix != 0 {
            let digits = &t[2..];
            if digits.is_empty() {
                return f64::NAN;
            }
            let mut acc = 0.0f64;
            for &c in digits {
                let d = digit_value(c);
                if d >= radix {
                    return f64::NAN;
                }
                acc = acc * radix as f64 + d as f64;
            }
            return acc;
        }
    }
    let (neg, rest) = match t[0] {
        0x2B => (false, &t[1..]),
        0x2D => (true, &t[1..]),
        _ => (false, t),
    };
    let v = if starts_with_ascii(rest, b"Infinity") && rest.len() == 8 {
        f64::INFINITY
    } else {
        let len = scan_unsigned_decimal(rest);
        if len == 0 || len != rest.len() {
            return f64::NAN;
        }
        parse_decimal_units(rest)
    };
    if neg {
        -v
    } else {
        v
    }
}

/// Global `parseFloat(string)` (the argument already converted with ToString).
pub fn parse_float(s: &[u16]) -> f64 {
    let t = trim_js_whitespace_start(s);
    let (neg, rest) = match t.first() {
        Some(&0x2B) => (false, &t[1..]),
        Some(&0x2D) => (true, &t[1..]),
        _ => (false, t),
    };
    let v = if starts_with_ascii(rest, b"Infinity") {
        f64::INFINITY
    } else {
        let len = scan_unsigned_decimal(rest);
        if len == 0 {
            return f64::NAN;
        }
        parse_decimal_units(&rest[..len])
    };
    if neg {
        -v
    } else {
        v
    }
}

/// Global `parseInt(string, radix)`; `radix` is ToInt32(radix) (0 = auto-detect). Digits are
/// accumulated in f64 exactly like lumen (see module docs).
pub fn parse_int(s: &[u16], radix: i32) -> f64 {
    let mut t = trim_js_whitespace_start(s);
    let mut neg = false;
    match t.first() {
        Some(&0x2D) => {
            neg = true;
            t = &t[1..];
        }
        Some(&0x2B) => t = &t[1..],
        _ => {}
    }
    let mut r = radix;
    let mut strip_prefix = true;
    if r != 0 {
        if !(2..=36).contains(&r) {
            return f64::NAN;
        }
        if r != 16 {
            strip_prefix = false;
        }
    } else {
        r = 10;
    }
    if strip_prefix && t.len() >= 2 && t[0] == u16::from(b'0') && (t[1] == 0x78 || t[1] == 0x58) {
        t = &t[2..];
        r = 16;
    }
    let rf = r as f64;
    let mut acc = 0.0f64;
    let mut any = false;
    for &c in t {
        let d = digit_value(c);
        if d >= r as u32 {
            break;
        }
        acc = acc * rf + d as f64;
        any = true;
    }
    if !any {
        return f64::NAN;
    }
    if neg {
        -acc
    } else {
        acc
    }
}

fn parse_u64_radix(digits: &[u8], radix: u32) -> Option<u64> {
    if digits.is_empty() {
        return None;
    }
    let mut acc: u64 = 0;
    for &c in digits {
        let d = digit_value(c as u16);
        if d >= radix {
            return None;
        }
        acc = acc.checked_mul(radix as u64)?.checked_add(d as u64)?;
    }
    Some(acc)
}

/// Value of a JS source NumericLiteral (without a BigInt `n` suffix): decimal (`1`, `.5`,
/// `5.`, `1e-7`), `0x`/`0o`/`0b`, legacy octal `017`, decimal-like `08`/`09.5`; numeric
/// separators `_` are ignored (the caller validated their placement). Returns `None` for
/// malformed text or a `0x`/`0o`/`0b` literal above u64::MAX (lumen: "SyntaxError: invalid
/// numeric literal").
pub fn parse_numeric_literal(src: &str) -> Option<f64> {
    let owned;
    let s = if src.contains('_') {
        owned = src.replace('_', "");
        owned.as_str()
    } else {
        src
    };
    let b = s.as_bytes();
    if b.is_empty() {
        return None;
    }
    if b.len() >= 2 && b[0] == b'0' {
        let radix = match b[1] {
            b'x' | b'X' => 16,
            b'o' | b'O' => 8,
            b'b' | b'B' => 2,
            _ => 0,
        };
        if radix != 0 {
            return parse_u64_radix(&b[2..], radix).map(|v| v as f64);
        }
        if b[1..].iter().all(|c| (b'0'..=b'7').contains(c)) {
            // Legacy octal integer literal; overflowing i64 yields 0 like lumen.
            let mut acc: i64 = 0;
            for &c in &b[1..] {
                match acc.checked_mul(8).and_then(|v| v.checked_add((c - b'0') as i64)) {
                    Some(v) => acc = v,
                    None => return Some(0.0),
                }
            }
            return Some(acc as f64);
        }
    }
    let len = scan_unsigned_decimal(b);
    if len == 0 || len != b.len() {
        return None;
    }
    Some(parse_decimal_ascii(b))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn u(s: &str) -> Vec<u16> {
        s.encode_utf16().collect()
    }

    #[test]
    fn to_string_basic() {
        assert_eq!(number_to_string(0.1 + 0.2), "0.30000000000000004");
        assert_eq!(number_to_string(1e21), "1e+21");
        assert_eq!(number_to_string(1e-7), "1e-7");
        assert_eq!(number_to_string(-0.0), "0");
        assert_eq!(number_to_string(123456789012345680000.0), "123456789012345680000");
        assert_eq!(number_to_string(0.000001), "0.000001");
        assert_eq!(number_to_string(f64::from_bits(0x400a714400000000)), "3.3053054809570313");
        assert_eq!(number_to_string(5e-324), "5e-324");
        assert_eq!(number_to_string(-1.5e300), "-1.5e+300");
    }

    #[test]
    fn radix() {
        assert_eq!(number_to_string_radix(255.5, 16), "ff.8");
        assert_eq!(number_to_string_radix(-1e21, 36), "-3w5e11264sgsf");
        assert_eq!(number_to_string_radix(std::f64::consts::PI, 36), "3.53i5ab8p5fc5vayqter60f6r");
        assert_eq!(number_to_string_radix(0.1, 2), "0.0001100110011001100110011001100110011001100110011001");
        assert_eq!(number_to_string_radix(1.0 / 3.0, 3), "0.1");
    }

    #[test]
    fn fixed_exp_prec() {
        assert_eq!(to_fixed(2.5, 0), "3");
        assert_eq!(to_fixed(1.005, 2), "1.00");
        assert_eq!(to_fixed(1.45, 1), "1.4");
        assert_eq!(to_fixed(-1e-7, 2), "-0.00");
        assert_eq!(to_fixed(0.5, 0), "1");
        assert_eq!(to_fixed(1e21, 2), "1e+21");
        assert_eq!(to_exponential(123.456, None), "1.23456e+2");
        assert_eq!(to_exponential(123.456, Some(0)), "1e+2");
        assert_eq!(to_exponential(25.0, Some(0)), "3e+1");
        assert_eq!(to_exponential(0.0, Some(2)), "0.00e+0");
        assert_eq!(to_precision(123.456, 2), "1.2e+2");
        assert_eq!(to_precision(0.000001, 2), "0.0000010");
        assert_eq!(to_precision(1e-7, 2), "1.0e-7");
        assert_eq!(to_precision(2.5, 1), "2");
        assert_eq!(to_precision(9.5, 1), "1e+1");
        assert_eq!(to_precision(0.0, 3), "0.00");
    }


    /// Reference toFixed/toExponential/toPrecision built only on the exact expansion.
    fn reference(a: f64, kind: u8, n: usize) -> String {
        let mut out = String::new();
        match kind {
            0 => to_fixed_exact(a, n, &mut out),
            1 | 2 => {
                let (mode, p) = if kind == 1 { (Rounding::HalfUp, n + 1) } else { (Rounding::HalfEven, n) };
                let dd = exact_sci(a, p, mode);
                out.push_str(std::str::from_utf8(dd.digits()).unwrap());
                out.push_str(&format!("e{}", dd.exp));
            }
            _ => unreachable!(),
        }
        out
    }

    #[test]
    fn fast_paths_match_exact() {
        // xorshift PRNG
        let mut st: u64 = 0x9E3779B97F4A7C15;
        let mut next = move || {
            st ^= st << 13;
            st ^= st >> 7;
            st ^= st << 17;
            st
        };
        for i in 0..300_000u32 {
            let r = next();
            let a = match i % 4 {
                0 => f64::from_bits(r >> 1),                                  // any positive double
                1 => ((r >> 40) as f64) / 2f64.powi((r % 40) as i32),        // short dyadic values (ties)
                2 => ((r >> 44) as f64) * 10f64.powi((r % 30) as i32 - 15), // decimal-ish
                _ => ((r >> 50) as f64 + 0.5) * 2f64.powi((r % 20) as i32 - 10),
            };
            if !a.is_finite() || a == 0.0 {
                continue;
            }
            let n = (next() % 101) as usize;
            if a < 1e21 {
                assert_eq!(to_fixed(a, n as u32), reference(a, 0, n), "toFixed {:e} {}", a, n);
            }
            let e = to_exponential(a, Some(n as u32));
            let (m, ex) = e.split_once('e').unwrap();
            let got = format!("{}e{}", m.replace('.', ""), ex.trim_start_matches('+'));
            assert_eq!(got, reference(a, 1, n), "toExponential {:e} {}", a, n);
            let p = n.max(1);
            let dd = rust_sci(a, Some(p - 1)).unwrap();
            let got = format!("{}e{}", std::str::from_utf8(dd.digits()).unwrap(), dd.exp);
            assert_eq!(got, reference(a, 2, p), "toPrecision {:e} {}", a, p);
        }
    }

    #[test]
    fn parsing() {
        assert_eq!(string_to_number(&u("  0x10  ")), 16.0);
        assert!(string_to_number(&u("1_000")).is_nan());
        assert_eq!(string_to_number(&u("\u{feff} 12 \u{3000}")), 12.0);
        assert!(string_to_number(&u("-0x10")).is_nan());
        assert_eq!(string_to_number(&u(".5")), 0.5);
        assert_eq!(string_to_number(&u("")), 0.0);
        assert!(string_to_number(&u(".")).is_nan());
        assert_eq!(string_to_number(&u("-Infinity")), f64::NEG_INFINITY);
        assert!(string_to_number(&u("infinity")).is_nan());
        assert_eq!(string_to_number(&u("-0")).to_bits(), (-0.0f64).to_bits());
        assert_eq!(parse_float(&u("  3.14abc")), 3.14);
        assert_eq!(parse_float(&u("1e+")), 1.0);
        assert!(parse_float(&u(".e1")).is_nan());
        assert_eq!(parse_float(&u("-Infinityx")), f64::NEG_INFINITY);
        assert_eq!(parse_int(&u("123456789012345678901234567890"), 0), 1.2345678901234566e29);
        assert_eq!(parse_int(&u(" -0x1F"), 0), -31.0);
        assert!(parse_int(&u("0x"), 16).is_nan());
        assert_eq!(parse_int(&u("0x1F"), 10), 0.0);
        assert!(parse_int(&u("1"), 37).is_nan());
        assert_eq!(parse_numeric_literal("017"), Some(15.0));
        assert_eq!(parse_numeric_literal("09.5"), Some(9.5));
        assert_eq!(parse_numeric_literal("1_000_000.5"), Some(1000000.5));
        assert_eq!(parse_numeric_literal("0x10000000000000000"), None);
        assert_eq!(parse_numeric_literal("0x8000000000000401"), Some(9223372036854777856.0));
        assert_eq!(parse_numeric_literal("01000000000000000000000"), Some(0.0));
        assert_eq!(parse_numeric_literal("1e"), None);
        assert_eq!(parse_numeric_literal(".5"), Some(0.5));
        assert_eq!(parse_numeric_literal("5."), Some(5.0));
    }
}
