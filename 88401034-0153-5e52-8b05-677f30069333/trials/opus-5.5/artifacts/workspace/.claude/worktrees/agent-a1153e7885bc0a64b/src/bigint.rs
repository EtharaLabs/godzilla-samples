//! Arbitrary-precision integers for JS BigInt (std only, no `unsafe`).
//!
//! Representation: sign + magnitude in little-endian `u64` limbs, always normalized (no high
//! zero limbs; zero has no limbs and is never negative), so the derived `Eq`/`Hash` are
//! value-based and `-0n` cannot exist.
//!
//! Algorithms: schoolbook multiplication below [`KARATSUBA_THRESHOLD`] limbs, Karatsuba above
//! (unbalanced operands are multiplied in balanced chunks); Knuth algorithm D for division
//! (2-by-1 reciprocal division for single-limb divisors); divide-and-conquer radix conversion
//! in both directions (power-of-two radices are converted bit-wise in linear time).
//!
//! Limits and error texts observed in the original `lumen` binary (reproduced here; the
//! message strings are exported as `MSG_*` constants for the engine to reuse):
//!
//! * `x << n` / `x >> -n` with n > 2^30 (`MAX_SHIFT_BITS`) and x != 0 throws
//!   `RangeError: BigInt is too large to allocate`; the limit is on the shift count only
//!   (`3n << 1073741824n` succeeds). `0n << hugeN` is 0; right shifts by huge counts give 0 or -1.
//! * `BigInt.asUintN(bits, x)` returns x unchanged when `x >= 0` and `bitlen(x) <= bits`;
//!   `BigInt.asIntN(bits, x)` returns x unchanged when `bitlen(|x|) < bits`. Otherwise lumen
//!   throws "BigInt is too large to allocate" if bits > 2^26 (`MAX_AS_N_BITS`), even when the
//!   result would be small (e.g. `BigInt.asUintN(2**26 + 1, -1n)`, `BigInt.asIntN(70000000,
//!   -(1n << 69999999n))`).
//! * `**` in lumen has no size check (huge results just hang); here a result that would need
//!   more than 2^30 bits (`MAX_POW_BITS`) fails with `BigIntError::TooLarge` (same message).
//!   `x ** -1n` -> "Exponent must be non-negative"; `0n ** 0n` is 1.
//! * Division/remainder by zero -> "Division by zero".
//! * `BigInt(1.5)`, `BigInt(NaN)`, `BigInt(Infinity)` -> RangeError
//!   "The number cannot be converted to a BigInt"; `BigInt("x")` -> SyntaxError
//!   "Cannot convert string to a BigInt" (also for `BigInt({})`, whose string is not numeric);
//!   `BigInt(undefined)`/`BigInt(null)`/`BigInt(Symbol())` -> TypeError
//!   "Cannot convert value to a BigInt".
//! * StringToBigInt (see [`BigInt::parse`]): trims whitespace (JS whitespace plus U+0085, like
//!   lumen's ToNumber), "" and "   " are 0n, a sign is allowed only for decimal ("-12" ok,
//!   "-0x10"/"+0x1" rejected), `0x`/`0o`/`0b` prefixes in either case, no separators, no
//!   decimal point/exponent, no `n` suffix, no "Infinity".
//! * `Number(bigint)` ([`BigInt::to_f64`]) rounds half to even; BigInt/Number comparisons
//!   ([`BigInt::cmp_f64`]) are exact.

#![allow(dead_code)]

use std::cmp::Ordering;
use std::fmt;

/// RangeError: `1n / 0n`, `1n % 0n`.
pub const MSG_DIVISION_BY_ZERO: &str = "Division by zero";
/// RangeError: `2n ** -1n`.
pub const MSG_NEGATIVE_EXPONENT: &str = "Exponent must be non-negative";
/// RangeError: `1n << 10000000000n`, `BigInt.asUintN(2**53 - 1, -1n)`.
pub const MSG_TOO_LARGE: &str = "BigInt is too large to allocate";
/// RangeError: `BigInt(1.5)`, `BigInt(NaN)`, `BigInt(Infinity)`.
pub const MSG_NUMBER_NOT_INTEGER: &str = "The number cannot be converted to a BigInt";
/// SyntaxError: `BigInt("x")`, `BigInt("1.5")`, `BigInt({})`.
pub const MSG_INVALID_STRING: &str = "Cannot convert string to a BigInt";
/// TypeError: `BigInt(undefined)`, `BigInt(null)`, `BigInt(Symbol())`, `BigInt.asIntN(64)`.
pub const MSG_CANNOT_CONVERT: &str = "Cannot convert value to a BigInt";
/// TypeError: ToBigInt on a Number, e.g. `BigInt.asIntN(1, 5)`, `new BigInt64Array([1])`.
pub const MSG_NUMBER_TO_BIGINT: &str = "Cannot convert a Number to a BigInt";
/// TypeError: `1n + 1`, `1n * 1.5`.
pub const MSG_MIX_TYPES: &str = "Cannot mix BigInt and other types, use explicit conversions";
/// TypeError: ToNumber on a BigInt, e.g. `+1n`, `Math.max(1n)`.
pub const MSG_TO_NUMBER: &str = "Cannot convert a BigInt value to a number";
/// TypeError: `new BigInt(1)`.
pub const MSG_NOT_CONSTRUCTOR: &str = "BigInt is not a constructor";
/// TypeError: `1n >>> 0n`.
pub const MSG_UNSIGNED_SHIFT: &str = "unsupported BigInt operator";
/// RangeError: `(255n).toString(37)` (note: Number's message is "toString() radix must be
/// between 2 and 36", with parentheses).
pub const MSG_RADIX: &str = "toString radix must be between 2 and 36";
/// TypeError: `BigInt.prototype.toString.call(1)`, `BigInt.prototype.valueOf.call(1)`.
pub const MSG_INCOMPATIBLE_RECEIVER: &str = "BigInt method called on incompatible receiver";
/// TypeError: `JSON.stringify(1n)`.
pub const MSG_JSON_SERIALIZE: &str = "Do not know how to serialize a BigInt";
/// RangeError from ToIndex: `BigInt.asIntN(-1, 1n)`, `BigInt.asIntN(2**53, 1n)`.
pub const MSG_INDEX_OUT_OF_RANGE: &str = "index out of range";

/// Maximum shift count accepted by `<<` (and by `>>` with a negative count).
pub const MAX_SHIFT_BITS: u64 = 1 << 30;
/// Above this many bits `as_int_n`/`as_uint_n` refuse inputs that do not already fit.
pub const MAX_AS_N_BITS: u64 = 1 << 26;
/// Maximum result size of `pow` (lumen itself has no limit and simply hangs).
pub const MAX_POW_BITS: u64 = 1 << 30;

/// Multiplication switches from schoolbook to Karatsuba at this many limbs (of the smaller
/// operand).
pub const KARATSUBA_THRESHOLD: usize = 40;
/// Radix conversion switches to divide-and-conquer above this many limbs.
const DC_TO_STRING_THRESHOLD: usize = 40;
/// Digit-string parsing switches to divide-and-conquer above this many digits.
const DC_PARSE_THRESHOLD: usize = 800;

/// Errors of fallible BigInt operations; all are RangeErrors in JS.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum BigIntError {
    DivisionByZero,
    NegativeExponent,
    TooLarge,
}

impl BigIntError {
    /// The exact message lumen uses.
    pub fn message(self) -> &'static str {
        match self {
            BigIntError::DivisionByZero => MSG_DIVISION_BY_ZERO,
            BigIntError::NegativeExponent => MSG_NEGATIVE_EXPONENT,
            BigIntError::TooLarge => MSG_TOO_LARGE,
        }
    }

    /// The JS error constructor to throw (always "RangeError").
    pub fn js_error_name(self) -> &'static str {
        "RangeError"
    }
}

impl fmt::Display for BigIntError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.message())
    }
}

impl std::error::Error for BigIntError {}

/// Error type of [`BigInt::pow`].
pub type PowError = BigIntError;

#[derive(Clone, PartialEq, Eq, Hash, Debug, Default)]
pub struct BigInt {
    /// True only for values < 0.
    neg: bool,
    /// Magnitude, little-endian, no high zero limbs.
    mag: Vec<u64>,
}

// =========================================================================================
// Magnitude (unsigned limb slice) arithmetic
// =========================================================================================

#[inline]
fn trim(v: &mut Vec<u64>) {
    while let Some(&0) = v.last() {
        v.pop();
    }
}

#[inline]
fn trimmed(a: &[u64]) -> &[u64] {
    let mut n = a.len();
    while n > 0 && a[n - 1] == 0 {
        n -= 1;
    }
    &a[..n]
}

fn bit_len_mag(a: &[u64]) -> u64 {
    match a.last() {
        None => 0,
        Some(&top) => (a.len() as u64 - 1) * 64 + (64 - top.leading_zeros() as u64),
    }
}

fn cmp_mag(a: &[u64], b: &[u64]) -> Ordering {
    if a.len() != b.len() {
        return a.len().cmp(&b.len());
    }
    for i in (0..a.len()).rev() {
        if a[i] != b[i] {
            return a[i].cmp(&b[i]);
        }
    }
    Ordering::Equal
}

/// a += b (requires a.len() >= trimmed length of b); returns the carry out of `a`.
fn add_in_place(a: &mut [u64], b: &[u64]) -> bool {
    let mut carry = false;
    for i in 0..a.len() {
        let bi = if i < b.len() {
            b[i]
        } else if carry {
            0
        } else {
            break;
        };
        let (s1, o1) = a[i].overflowing_add(bi);
        let (s2, o2) = s1.overflowing_add(carry as u64);
        a[i] = s2;
        carry = o1 || o2;
    }
    carry
}

/// a -= b (requires a >= b numerically and a.len() >= trimmed length of b); returns borrow.
fn sub_in_place(a: &mut [u64], b: &[u64]) -> bool {
    let mut borrow = false;
    for i in 0..a.len() {
        let bi = if i < b.len() {
            b[i]
        } else if borrow {
            0
        } else {
            break;
        };
        let (d1, o1) = a[i].overflowing_sub(bi);
        let (d2, o2) = d1.overflowing_sub(borrow as u64);
        a[i] = d2;
        borrow = o1 || o2;
    }
    borrow
}

fn add_mag(a: &[u64], b: &[u64]) -> Vec<u64> {
    let (a, b) = if a.len() >= b.len() { (a, b) } else { (b, a) };
    let mut out = Vec::with_capacity(a.len() + 1);
    out.extend_from_slice(a);
    if add_in_place(&mut out, b) {
        out.push(1);
    }
    trim(&mut out);
    out
}

/// a - b for a >= b.
fn sub_mag(a: &[u64], b: &[u64]) -> Vec<u64> {
    let mut out = a.to_vec();
    sub_in_place(&mut out, b);
    trim(&mut out);
    out
}

fn add_small_mag(a: &[u64], v: u64) -> Vec<u64> {
    add_mag(a, &[v])
}

fn sub_one_mag(a: &[u64]) -> Vec<u64> {
    sub_mag(a, &[1])
}

/// out[..a.len()+b.len()] (zeroed) = a * b.
fn schoolbook(a: &[u64], b: &[u64], out: &mut [u64]) {
    for (i, &bi) in b.iter().enumerate() {
        if bi == 0 {
            continue;
        }
        let row = &mut out[i..i + a.len() + 1];
        let mut carry: u64 = 0;
        for (slot, &aj) in row.iter_mut().zip(a) {
            let t = (aj as u128) * (bi as u128) + (*slot as u128) + (carry as u128);
            *slot = t as u64;
            carry = (t >> 64) as u64;
        }
        row[a.len()] = carry;
    }
}

/// Trimmed product of two (possibly untrimmed) magnitudes.
fn mul_mag(a: &[u64], b: &[u64]) -> Vec<u64> {
    let a = trimmed(a);
    let b = trimmed(b);
    if a.is_empty() || b.is_empty() {
        return Vec::new();
    }
    let (a, b) = if a.len() >= b.len() { (a, b) } else { (b, a) };
    if b.len() == 1 {
        return mul_small_mag(a, b[0]);
    }
    let mut out = vec![0u64; a.len() + b.len()];
    if b.len() < KARATSUBA_THRESHOLD {
        schoolbook(a, b, &mut out);
    } else if a.len() >= 2 * b.len() {
        // Unbalanced: multiply balanced chunks of `a` by `b`.
        let n = b.len();
        let mut i = 0;
        while i < a.len() {
            let end = (i + n).min(a.len());
            let p = mul_mag(&a[i..end], b);
            add_in_place(&mut out[i..], &p);
            i = end;
        }
    } else {
        // Karatsuba: a = a1*B^m + a0, b = b1*B^m + b0 (b.len() > m since b.len() > a.len()/2).
        let m = a.len() / 2;
        let (a0, a1) = a.split_at(m);
        let (b0, b1) = b.split_at(m);
        let z0 = mul_mag(a0, b0);
        let z2 = mul_mag(a1, b1);
        let sa = add_mag(trimmed(a0), a1);
        let sb = add_mag(trimmed(b0), b1);
        let mut z1 = mul_mag(&sa, &sb);
        sub_in_place(&mut z1, &z0);
        sub_in_place(&mut z1, &z2);
        trim(&mut z1);
        add_in_place(&mut out, &z0);
        add_in_place(&mut out[m..], &z1);
        add_in_place(&mut out[2 * m..], &z2);
    }
    trim(&mut out);
    out
}

fn mul_small_mag(a: &[u64], m: u64) -> Vec<u64> {
    let mut out = Vec::with_capacity(a.len() + 1);
    let mut carry: u64 = 0;
    for &x in a {
        let t = (x as u128) * (m as u128) + carry as u128;
        out.push(t as u64);
        carry = (t >> 64) as u64;
    }
    out.push(carry);
    trim(&mut out);
    out
}

/// a = a * m + add, in place.
fn mul_small_add_in_place(a: &mut Vec<u64>, m: u64, add: u64) {
    let mut carry: u64 = add;
    for x in a.iter_mut() {
        let t = (*x as u128) * (m as u128) + carry as u128;
        *x = t as u64;
        carry = (t >> 64) as u64;
    }
    if carry != 0 {
        a.push(carry);
    }
}

/// Precomputed reciprocal for fast division of 128-bit values by a fixed 64-bit divisor
/// (Moller & Granlund, "Improved division by invariant integers").
struct Reciprocal {
    /// Normalized divisor (top bit set).
    d: u64,
    /// floor((2^128 - 1) / d) - 2^64.
    v: u64,
    /// Normalization shift applied to the original divisor.
    shift: u32,
}

impl Reciprocal {
    fn new(divisor: u64) -> Reciprocal {
        debug_assert!(divisor != 0);
        let shift = divisor.leading_zeros();
        let d = divisor << shift;
        let v = (u128::MAX / d as u128 - (1u128 << 64)) as u64;
        Reciprocal { d, v, shift }
    }

    /// Divides (u1:u0) by the normalized divisor; requires u1 < d.
    #[inline]
    fn div_2by1(&self, u1: u64, u0: u64) -> (u64, u64) {
        let q = ((self.v as u128) * (u1 as u128)).wrapping_add(((u1 as u128) << 64) | u0 as u128);
        let mut q1 = ((q >> 64) as u64).wrapping_add(1);
        let q0 = q as u64;
        let mut r = u0.wrapping_sub(q1.wrapping_mul(self.d));
        if r > q0 {
            q1 = q1.wrapping_sub(1);
            r = r.wrapping_add(self.d);
        }
        if r >= self.d {
            q1 = q1.wrapping_add(1);
            r -= self.d;
        }
        (q1, r)
    }
}

/// a /= divisor in place (trimmed afterwards); returns the remainder.
fn div_small_in_place(a: &mut Vec<u64>, rec: &Reciprocal) -> u64 {
    let s = rec.shift;
    let mut rem: u64 = 0;
    if s == 0 {
        for x in a.iter_mut().rev() {
            let (q, r) = rec.div_2by1(rem, *x);
            *x = q;
            rem = r;
        }
    } else {
        // Divide (a << s) by (d << s): same quotient, remainder scaled by 2^s.
        let n = a.len();
        if n > 0 {
            rem = a[n - 1] >> (64 - s);
        }
        for i in (0..n).rev() {
            let lo = if i > 0 { a[i - 1] >> (64 - s) } else { 0 };
            let limb = (a[i] << s) | lo;
            let (q, r) = rec.div_2by1(rem, limb);
            a[i] = q;
            rem = r;
        }
        rem >>= s;
    }
    trim(a);
    rem
}

fn divrem_small_mag(a: &[u64], d: u64) -> (Vec<u64>, u64) {
    let mut q = a.to_vec();
    let r = div_small_in_place(&mut q, &Reciprocal::new(d));
    (q, r)
}

fn shl_mag(a: &[u64], bits: u64) -> Vec<u64> {
    if a.is_empty() {
        return Vec::new();
    }
    let words = (bits / 64) as usize;
    let s = (bits % 64) as u32;
    let mut out = vec![0u64; words];
    out.reserve(a.len() + 1);
    if s == 0 {
        out.extend_from_slice(a);
    } else {
        let mut carry = 0u64;
        for &x in a {
            out.push((x << s) | carry);
            carry = x >> (64 - s);
        }
        out.push(carry);
    }
    trim(&mut out);
    out
}

fn shr_mag(a: &[u64], bits: u64) -> Vec<u64> {
    let words = bits / 64;
    if words >= a.len() as u64 {
        return Vec::new();
    }
    let words = words as usize;
    let s = (bits % 64) as u32;
    let src = &a[words..];
    let mut out = Vec::with_capacity(src.len());
    if s == 0 {
        out.extend_from_slice(src);
    } else {
        for i in 0..src.len() {
            let hi = if i + 1 < src.len() { src[i + 1] << (64 - s) } else { 0 };
            out.push((src[i] >> s) | hi);
        }
    }
    trim(&mut out);
    out
}

/// True if any of the low `bits` bits of `a` is set.
fn any_low_bits(a: &[u64], bits: u64) -> bool {
    let words = (bits / 64) as usize;
    if a.iter().take(words).any(|&x| x != 0) {
        return true;
    }
    let s = bits % 64;
    s != 0 && words < a.len() && (a[words] & ((1u64 << s) - 1)) != 0
}

/// Knuth algorithm D. Requires v.len() >= 2, u >= v (trimmed inputs).
fn divrem_knuth(u: &[u64], v: &[u64]) -> (Vec<u64>, Vec<u64>) {
    let n = v.len();
    let m = u.len() - n;
    let s = v[n - 1].leading_zeros();
    let vn: Vec<u64> = if s == 0 {
        v.to_vec()
    } else {
        (0..n)
            .map(|i| (v[i] << s) | if i > 0 { v[i - 1] >> (64 - s) } else { 0 })
            .collect()
    };
    let mut un: Vec<u64> = Vec::with_capacity(u.len() + 1);
    if s == 0 {
        un.extend_from_slice(u);
        un.push(0);
    } else {
        for i in 0..u.len() {
            un.push((u[i] << s) | if i > 0 { u[i - 1] >> (64 - s) } else { 0 });
        }
        un.push(u[u.len() - 1] >> (64 - s));
    }
    let mut q = vec![0u64; m + 1];
    let vtop = vn[n - 1];
    let vsec = vn[n - 2] as u128;
    let rec = Reciprocal::new(vtop);
    for j in (0..=m).rev() {
        let u2 = un[j + n];
        let u1 = un[j + n - 1];
        let u0 = un[j + n - 2] as u128;
        // Estimate qhat = (u2:u1) / vtop, clamped to 2^64 - 1.
        let (mut qhat, mut rhat, mut rhat_overflow) = if u2 >= vtop {
            // qhat would be >= 2^64; use 2^64 - 1 with rhat = (u2:u1) - qhat*vtop.
            let qh = u64::MAX;
            let num = ((u2 as u128) << 64) | u1 as u128;
            let r = num - (qh as u128) * (vtop as u128);
            (qh, r as u64, r > u64::MAX as u128)
        } else {
            let (qh, r) = rec.div_2by1(u2, u1);
            (qh, r, false)
        };
        while !rhat_overflow && (qhat as u128) * vsec > (((rhat as u128) << 64) | u0) {
            qhat -= 1;
            let (nr, o) = rhat.overflowing_add(vtop);
            rhat = nr;
            rhat_overflow = o;
        }
        // Multiply and subtract: un[j..=j+n] -= qhat * vn.
        let mut borrow = false;
        let mut carry: u64 = 0;
        for i in 0..n {
            let p = (qhat as u128) * (vn[i] as u128) + carry as u128;
            carry = (p >> 64) as u64;
            let (d1, o1) = un[i + j].overflowing_sub(p as u64);
            let (d2, o2) = d1.overflowing_sub(borrow as u64);
            un[i + j] = d2;
            borrow = o1 || o2;
        }
        let (d1, o1) = un[j + n].overflowing_sub(carry);
        let (d2, o2) = d1.overflowing_sub(borrow as u64);
        un[j + n] = d2;
        if o1 || o2 {
            // qhat was one too large: add back.
            qhat -= 1;
            let mut c = false;
            for i in 0..n {
                let (s1, c1) = un[i + j].overflowing_add(vn[i]);
                let (s2, c2) = s1.overflowing_add(c as u64);
                un[i + j] = s2;
                c = c1 || c2;
            }
            un[j + n] = un[j + n].wrapping_add(c as u64);
        }
        q[j] = qhat;
    }
    trim(&mut q);
    // Remainder: un[0..n] >> s.
    let mut r: Vec<u64> = if s == 0 {
        un[..n].to_vec()
    } else {
        (0..n)
            .map(|i| (un[i] >> s) | if i + 1 < n { un[i + 1] << (64 - s) } else { 0 })
            .collect()
    };
    trim(&mut r);
    (q, r)
}

/// (a / b, a % b) for trimmed magnitudes, b != 0.
fn divrem_mag(a: &[u64], b: &[u64]) -> (Vec<u64>, Vec<u64>) {
    debug_assert!(!b.is_empty());
    if cmp_mag(a, b) == Ordering::Less {
        return (Vec::new(), a.to_vec());
    }
    if b.len() == 1 {
        let (q, r) = divrem_small_mag(a, b[0]);
        let r = if r == 0 { Vec::new() } else { vec![r] };
        return (q, r);
    }
    divrem_knuth(a, b)
}

// =========================================================================================
// Radix conversion
// =========================================================================================

/// Largest power of `radix` that fits in a u64, and its exponent.
fn chunk_base(radix: u32) -> (u64, usize) {
    let r = radix as u64;
    let mut base = r;
    let mut k = 1;
    while let Some(nb) = base.checked_mul(r) {
        base = nb;
        k += 1;
    }
    (base, k)
}

fn digit_char(d: u64) -> u8 {
    b"0123456789abcdefghijklmnopqrstuvwxyz"[d as usize]
}

/// Bit-wise conversion for radix 2^bpd.
fn to_string_pow2(mag: &[u64], bpd: u32, out: &mut Vec<u8>) {
    let total = bit_len_mag(mag);
    let bpd64 = bpd as u64;
    let ndigits = total.div_ceil(bpd64);
    let mask = (1u64 << bpd) - 1;
    for k in (0..ndigits).rev() {
        let pos = k * bpd64;
        let limb = (pos / 64) as usize;
        let off = (pos % 64) as u32;
        let mut v = mag[limb] >> off;
        if off + bpd > 64 && limb + 1 < mag.len() {
            v |= mag[limb + 1] << (64 - off);
        }
        out.push(digit_char(v & mask));
    }
}

/// Naive conversion: repeated division by the chunk base. Appends the digits of `x`,
/// left-padded with zeros to `pad_to` digits (0 = no padding).
fn to_string_naive(x: &[u64], radix: u32, pad_to: usize, out: &mut Vec<u8>) {
    let (base, k) = chunk_base(radix);
    let rec = Reciprocal::new(base);
    let r = radix as u64;
    let mut cur = x.to_vec();
    trim(&mut cur);
    let mut chunks: Vec<u64> = Vec::with_capacity(cur.len() + 1);
    while !cur.is_empty() {
        chunks.push(div_small_in_place(&mut cur, &rec));
    }
    let mut digits: Vec<u8> = Vec::with_capacity(chunks.len() * k);
    for (idx, &c) in chunks.iter().rev().enumerate() {
        let mut tmp = [b'0'; 64];
        let mut v = c;
        for slot in tmp[..k].iter_mut().rev() {
            *slot = digit_char(v % r);
            v /= r;
        }
        if idx == 0 {
            let skip = tmp[..k].iter().position(|&ch| ch != b'0').unwrap_or(k);
            digits.extend_from_slice(&tmp[skip..k]);
        } else {
            digits.extend_from_slice(&tmp[..k]);
        }
    }
    if digits.len() < pad_to {
        out.resize(out.len() + (pad_to - digits.len()), b'0');
    }
    out.extend_from_slice(&digits);
}

/// Divide-and-conquer conversion. `powers[i]` = base^(2^i); requires x < powers[k]^2.
/// When `pad` is set the output is left-padded to chunk_digits * 2^(k+1) digits.
fn to_string_dc(
    x: &[u64],
    k: usize,
    pad: bool,
    radix: u32,
    chunk_digits: usize,
    powers: &[Vec<u64>],
    out: &mut Vec<u8>,
) {
    let width = chunk_digits << (k + 1);
    if x.len() <= DC_TO_STRING_THRESHOLD || k == 0 {
        to_string_naive(x, radix, if pad { width } else { 0 }, out);
        return;
    }
    let (q, r) = if x.is_empty() {
        (Vec::new(), Vec::new())
    } else {
        divrem_mag(x, &powers[k])
    };
    if !pad && q.is_empty() {
        to_string_dc(&r, k - 1, false, radix, chunk_digits, powers, out);
    } else {
        to_string_dc(&q, k - 1, pad, radix, chunk_digits, powers, out);
        to_string_dc(&r, k - 1, true, radix, chunk_digits, powers, out);
    }
}

fn mag_to_string(mag: &[u64], radix: u32, out: &mut Vec<u8>) {
    if mag.is_empty() {
        out.push(b'0');
        return;
    }
    if radix.is_power_of_two() {
        to_string_pow2(mag, radix.trailing_zeros(), out);
        return;
    }
    if mag.len() <= DC_TO_STRING_THRESHOLD {
        to_string_naive(mag, radix, 0, out);
        return;
    }
    let (base, chunk_digits) = chunk_base(radix);
    // powers[i] = base^(2^i); stop once powers[k]^2 is certainly > mag.
    let mut powers: Vec<Vec<u64>> = vec![vec![base]];
    loop {
        let last = powers.last().map_or(0, |p| p.len());
        if 2 * last >= mag.len() + 2 {
            break;
        }
        let sq = {
            let p = &powers[powers.len() - 1];
            mul_mag(p, p)
        };
        powers.push(sq);
    }
    let k = powers.len() - 1;
    to_string_dc(mag, k, false, radix, chunk_digits, &powers, out);
}

fn digit_value(c: u8) -> u32 {
    match c {
        b'0'..=b'9' => (c - b'0') as u32,
        b'a'..=b'z' => (c - b'a') as u32 + 10,
        b'A'..=b'Z' => (c - b'A') as u32 + 10,
        _ => 99,
    }
}

/// Magnitude from digit values (each < radix), most significant first.
fn mag_from_digit_values(d: &[u8], radix: u32) -> Vec<u64> {
    let start = d.iter().position(|&x| x != 0).unwrap_or(d.len());
    let d = &d[start..];
    if d.is_empty() {
        return Vec::new();
    }
    if radix.is_power_of_two() {
        let bpd = radix.trailing_zeros() as usize;
        let mut out = vec![0u64; (d.len() * bpd).div_ceil(64)];
        for (k, &v) in d.iter().rev().enumerate() {
            let pos = k * bpd;
            let limb = pos / 64;
            let off = pos % 64;
            out[limb] |= (v as u64) << off;
            if off + bpd > 64 {
                out[limb + 1] |= (v as u64) >> (64 - off);
            }
        }
        trim(&mut out);
        return out;
    }
    let (base, chunk_digits) = chunk_base(radix);
    if d.len() <= DC_PARSE_THRESHOLD {
        return parse_naive(d, radix, chunk_digits);
    }
    let mut powers: Vec<Vec<u64>> = vec![vec![base]];
    parse_dc(d, radix, chunk_digits, &mut powers)
}

fn parse_naive(d: &[u8], radix: u32, chunk_digits: usize) -> Vec<u64> {
    let mut acc: Vec<u64> = Vec::with_capacity(d.len() / chunk_digits + 1);
    let first = match d.len() % chunk_digits {
        0 => chunk_digits.min(d.len()),
        r => r,
    };
    let mut i = 0;
    let mut len = first;
    while i < d.len() {
        let chunk = &d[i..i + len];
        let mut v: u64 = 0;
        for &x in chunk {
            v = v * radix as u64 + x as u64;
        }
        let mul = (radix as u64).pow(len as u32);
        mul_small_add_in_place(&mut acc, mul, v);
        i += len;
        len = chunk_digits;
    }
    trim(&mut acc);
    acc
}

fn parse_dc(d: &[u8], radix: u32, chunk_digits: usize, powers: &mut Vec<Vec<u64>>) -> Vec<u64> {
    if d.len() <= DC_PARSE_THRESHOLD {
        return parse_naive(d, radix, chunk_digits);
    }
    // Low part: chunk_digits * 2^j digits, the largest such count below d.len().
    let mut j = 0;
    while (chunk_digits << (j + 1)) < d.len() {
        j += 1;
    }
    let lo_len = chunk_digits << j;
    let split = d.len() - lo_len;
    let hi = parse_dc(&d[..split], radix, chunk_digits, powers);
    let lo = parse_dc(&d[split..], radix, chunk_digits, powers);
    while powers.len() <= j {
        let sq = {
            let p = &powers[powers.len() - 1];
            mul_mag(p, p)
        };
        powers.push(sq);
    }
    let mut r = mul_mag(&hi, &powers[j]);
    if r.len() < lo.len() {
        r.resize(lo.len(), 0);
    }
    if add_in_place(&mut r, &lo) {
        r.push(1);
    }
    trim(&mut r);
    r
}

// =========================================================================================
// Two's complement helpers for bitwise operations
// =========================================================================================

/// Two's complement limbs of `x` (`len` limbs; the infinite sign extension is implied by
/// `x.neg`). Requires len >= x.mag.len().
fn to_twos(x: &BigInt, len: usize) -> Vec<u64> {
    let mut v = if x.neg { sub_one_mag(&x.mag) } else { x.mag.clone() };
    v.resize(len, 0);
    if x.neg {
        for l in v.iter_mut() {
            *l = !*l;
        }
    }
    v
}

/// Inverse of [`to_twos`]: limbs with an infinite extension of the sign bit `neg`.
fn from_twos(mut v: Vec<u64>, neg: bool) -> BigInt {
    if !neg {
        trim(&mut v);
        return BigInt { neg: false, mag: v };
    }
    for l in v.iter_mut() {
        *l = !*l;
    }
    // value = -(!v + 1)
    trim(&mut v);
    let mag = add_small_mag(&v, 1);
    BigInt { neg: true, mag }
}

// =========================================================================================
// BigInt
// =========================================================================================

impl BigInt {
    fn from_parts(neg: bool, mut mag: Vec<u64>) -> BigInt {
        trim(&mut mag);
        let neg = neg && !mag.is_empty();
        BigInt { neg, mag }
    }

    pub fn zero() -> Self {
        BigInt { neg: false, mag: Vec::new() }
    }

    pub fn one() -> Self {
        BigInt { neg: false, mag: vec![1] }
    }

    pub fn from_i64(v: i64) -> Self {
        Self::from_parts(v < 0, vec![v.unsigned_abs()])
    }

    pub fn from_u64(v: u64) -> Self {
        Self::from_parts(false, vec![v])
    }

    pub fn from_i128(v: i128) -> Self {
        let a = v.unsigned_abs();
        Self::from_parts(v < 0, vec![a as u64, (a >> 64) as u64])
    }

    pub fn from_u128(v: u128) -> Self {
        Self::from_parts(false, vec![v as u64, (v >> 64) as u64])
    }

    /// BigInt(number) / NumberToBigInt: `None` if `x` is NaN, infinite or not an integer
    /// (lumen: RangeError [`MSG_NUMBER_NOT_INTEGER`]). -0 gives 0n.
    pub fn from_f64(x: f64) -> Option<Self> {
        if !x.is_finite() || x.trunc() != x {
            return None;
        }
        if x == 0.0 {
            return Some(Self::zero());
        }
        let bits = x.to_bits();
        let biased = ((bits >> 52) & 0x7ff) as i64;
        let frac = bits & ((1u64 << 52) - 1);
        // Integers are never subnormal, so biased >= 1023 here.
        let m = frac | (1u64 << 52);
        let e = biased - 1075;
        let mag = if e >= 0 {
            shl_mag(&[m], e as u64)
        } else {
            vec![m >> ((-e) as u32)]
        };
        Some(Self::from_parts(x < 0.0, mag))
    }

    /// Number(bigint): correctly rounded (round half to even), +-Infinity when too large.
    pub fn to_f64(&self) -> f64 {
        let bl = bit_len_mag(&self.mag);
        let mag = if bl == 0 {
            0.0
        } else if bl <= 64 {
            self.mag[0] as f64
        } else if bl > 1024 {
            f64::INFINITY
        } else {
            // Top 64 bits plus a sticky bit for everything below; the u64 -> f64 conversion
            // then rounds correctly, and scaling by 2^shift is exact (or overflows to inf).
            let shift = bl - 64;
            let top = shr_mag(&self.mag, shift);
            let sticky = any_low_bits(&self.mag, shift) as u64;
            let t = (top[0] | sticky) as f64;
            t * f64::from_bits((shift + 1023) << 52)
        };
        if self.neg {
            -mag
        } else {
            mag
        }
    }

    /// StringToBigInt (`BigInt(string)`, BigInt == string comparisons): `None` when the
    /// string is not a valid StringIntegerLiteral (lumen: SyntaxError [`MSG_INVALID_STRING`]).
    pub fn parse(s: &[u16]) -> Option<Self> {
        let is_ws = |c: u16| {
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
        };
        let start = s.iter().position(|&c| !is_ws(c)).unwrap_or(s.len());
        let end = s.iter().rposition(|&c| !is_ws(c)).map_or(start, |i| i + 1);
        let t = &s[start..end];
        if t.is_empty() {
            return Some(Self::zero());
        }
        if t.iter().any(|&c| c >= 0x80) {
            return None;
        }
        let b: Vec<u8> = t.iter().map(|&c| c as u8).collect();
        if b.len() >= 2 && b[0] == b'0' {
            let radix = match b[1] {
                b'x' | b'X' => 16,
                b'o' | b'O' => 8,
                b'b' | b'B' => 2,
                _ => 0,
            };
            if radix != 0 {
                return Self::from_str_radix_unsigned(&b[2..], radix);
            }
        }
        let (neg, digits) = match b[0] {
            b'+' => (false, &b[1..]),
            b'-' => (true, &b[1..]),
            _ => (false, &b[..]),
        };
        let v = Self::from_str_radix_unsigned(digits, 10)?;
        Some(if neg { v.neg() } else { v })
    }

    /// Unsigned digits (no prefix, sign or separators) in `radix`; `None` if empty or invalid.
    fn from_str_radix_unsigned(digits: &[u8], radix: u32) -> Option<Self> {
        if digits.is_empty() {
            return None;
        }
        let mut vals = Vec::with_capacity(digits.len());
        for &c in digits {
            let d = digit_value(c);
            if d >= radix {
                return None;
            }
            vals.push(d as u8);
        }
        Some(Self::from_parts(false, mag_from_digit_values(&vals, radix)))
    }

    /// Parses an optionally signed digit string in `radix` (2..=36, no prefix/separators).
    pub fn from_str_radix(s: &str, radix: u32) -> Option<Self> {
        if !(2..=36).contains(&radix) {
            return None;
        }
        let b = s.as_bytes();
        let (neg, digits) = match b.first() {
            Some(b'+') => (false, &b[1..]),
            Some(b'-') => (true, &b[1..]),
            _ => (false, b),
        };
        let v = Self::from_str_radix_unsigned(digits, radix)?;
        Some(if neg { v.neg() } else { v })
    }

    /// Value of a BigInt source literal's digits (prefix, separators and `n` already
    /// removed), e.g. `parse_literal("1F", 16)`. Invalid characters are ignored.
    pub fn parse_literal(digits: &str, radix: u32) -> Self {
        let radix = radix.clamp(2, 36);
        let vals: Vec<u8> = digits
            .bytes()
            .map(digit_value)
            .filter(|&d| d < radix)
            .map(|d| d as u8)
            .collect();
        Self::from_parts(false, mag_from_digit_values(&vals, radix))
    }

    /// Lowercase digits with a '-' prefix for negatives. `radix` must be 2..=36 (the caller
    /// throws RangeError [`MSG_RADIX`] otherwise); out-of-range values are clamped.
    pub fn to_string_radix(&self, radix: u32) -> String {
        let radix = radix.clamp(2, 36);
        let mut out: Vec<u8> = Vec::new();
        if self.neg {
            out.push(b'-');
        }
        mag_to_string(&self.mag, radix, &mut out);
        String::from_utf8(out).unwrap_or_default()
    }

    pub fn is_zero(&self) -> bool {
        self.mag.is_empty()
    }

    pub fn is_negative(&self) -> bool {
        self.neg
    }

    /// True for odd values (negative ones included).
    pub fn is_odd(&self) -> bool {
        self.mag.first().is_some_and(|&l| l & 1 == 1)
    }

    /// -1, 0 or 1.
    pub fn signum(&self) -> i32 {
        if self.neg {
            -1
        } else if self.mag.is_empty() {
            0
        } else {
            1
        }
    }

    /// Number of bits of |self| (0 for zero).
    pub fn bit_length(&self) -> u64 {
        bit_len_mag(&self.mag)
    }

    pub fn abs(&self) -> Self {
        BigInt { neg: false, mag: self.mag.clone() }
    }

    /// Exact conversion to i64, if it fits.
    pub fn to_i64(&self) -> Option<i64> {
        match self.mag.len() {
            0 => Some(0),
            1 => {
                let m = self.mag[0];
                if self.neg {
                    if m <= 1u64 << 63 {
                        Some((m as i64).wrapping_neg())
                    } else {
                        None
                    }
                } else {
                    i64::try_from(m).ok()
                }
            }
            _ => None,
        }
    }

    /// Exact conversion to u64, if it fits.
    pub fn to_u64(&self) -> Option<u64> {
        if self.neg {
            return None;
        }
        match self.mag.len() {
            0 => Some(0),
            1 => Some(self.mag[0]),
            _ => None,
        }
    }

    pub fn add(&self, o: &Self) -> Self {
        if self.neg == o.neg {
            return BigInt { neg: self.neg, mag: add_mag(&self.mag, &o.mag) };
        }
        match cmp_mag(&self.mag, &o.mag) {
            Ordering::Equal => Self::zero(),
            Ordering::Greater => Self::from_parts(self.neg, sub_mag(&self.mag, &o.mag)),
            Ordering::Less => Self::from_parts(o.neg, sub_mag(&o.mag, &self.mag)),
        }
    }

    pub fn sub(&self, o: &Self) -> Self {
        if self.neg != o.neg {
            return BigInt { neg: self.neg, mag: add_mag(&self.mag, &o.mag) };
        }
        match cmp_mag(&self.mag, &o.mag) {
            Ordering::Equal => Self::zero(),
            Ordering::Greater => Self::from_parts(self.neg, sub_mag(&self.mag, &o.mag)),
            Ordering::Less => Self::from_parts(!self.neg, sub_mag(&o.mag, &self.mag)),
        }
    }

    pub fn mul(&self, o: &Self) -> Self {
        Self::from_parts(self.neg != o.neg, mul_mag(&self.mag, &o.mag))
    }

    /// Truncating division; `None` on division by zero.
    pub fn div(&self, o: &Self) -> Option<Self> {
        if o.is_zero() {
            return None;
        }
        let (q, _) = divrem_mag(&self.mag, &o.mag);
        Some(Self::from_parts(self.neg != o.neg, q))
    }

    /// Remainder with the sign of the dividend; `None` on division by zero.
    pub fn rem(&self, o: &Self) -> Option<Self> {
        if o.is_zero() {
            return None;
        }
        let (_, r) = divrem_mag(&self.mag, &o.mag);
        Some(Self::from_parts(self.neg, r))
    }

    /// Truncating quotient and remainder at once.
    pub fn div_rem(&self, o: &Self) -> Option<(Self, Self)> {
        if o.is_zero() {
            return None;
        }
        let (q, r) = divrem_mag(&self.mag, &o.mag);
        Some((Self::from_parts(self.neg != o.neg, q), Self::from_parts(self.neg, r)))
    }

    /// `self ** exp`. Negative exponent -> [`BigIntError::NegativeExponent`]; a result
    /// above [`MAX_POW_BITS`] bits -> [`BigIntError::TooLarge`].
    pub fn pow(&self, exp: &Self) -> Result<Self, PowError> {
        if exp.neg {
            return Err(BigIntError::NegativeExponent);
        }
        if exp.is_zero() {
            return Ok(Self::one());
        }
        if self.is_zero() {
            return Ok(Self::zero());
        }
        let neg = self.neg && exp.is_odd();
        if self.mag == [1] {
            return Ok(Self::from_parts(neg, vec![1]));
        }
        // |self| >= 2 from here on, so exponents beyond u64 are certainly too large.
        let e = exp.to_u64().ok_or(BigIntError::TooLarge)?;
        // |self| = odd * 2^tz
        let first = self.mag.iter().position(|&l| l != 0).unwrap_or(0);
        let tz = first as u64 * 64 + self.mag[first].trailing_zeros() as u64;
        let odd = shr_mag(&self.mag, tz);
        let odd_bits = bit_len_mag(&odd);
        // Lower bound of the result's bit length: (odd_bits - 1) * e + tz * e + 1.
        let shift = tz.checked_mul(e).ok_or(BigIntError::TooLarge)?;
        let odd_min = (odd_bits - 1).checked_mul(e).ok_or(BigIntError::TooLarge)?;
        if shift.saturating_add(odd_min) > MAX_POW_BITS {
            return Err(BigIntError::TooLarge);
        }
        let mut result: Vec<u64> = vec![1];
        if odd != [1] {
            let top = 63 - e.leading_zeros();
            for bit in (0..=top).rev() {
                result = mul_mag(&result, &result);
                if (e >> bit) & 1 == 1 {
                    result = mul_mag(&result, &odd);
                }
            }
        }
        Ok(Self::from_parts(neg, shl_mag(&result, shift)))
    }

    pub fn neg(&self) -> Self {
        Self::from_parts(!self.neg, self.mag.clone())
    }

    pub fn bitand(&self, o: &Self) -> Self {
        if !self.neg && !o.neg {
            let n = self.mag.len().min(o.mag.len());
            let v: Vec<u64> = (0..n).map(|i| self.mag[i] & o.mag[i]).collect();
            return Self::from_parts(false, v);
        }
        let len = self.mag.len().max(o.mag.len());
        let a = to_twos(self, len);
        let b = to_twos(o, len);
        let v: Vec<u64> = a.iter().zip(&b).map(|(x, y)| x & y).collect();
        from_twos(v, self.neg && o.neg)
    }

    pub fn bitor(&self, o: &Self) -> Self {
        if !self.neg && !o.neg {
            let (long, short) = if self.mag.len() >= o.mag.len() { (self, o) } else { (o, self) };
            let mut v = long.mag.clone();
            for (x, y) in v.iter_mut().zip(&short.mag) {
                *x |= *y;
            }
            return BigInt { neg: false, mag: v };
        }
        let len = self.mag.len().max(o.mag.len());
        let a = to_twos(self, len);
        let b = to_twos(o, len);
        let v: Vec<u64> = a.iter().zip(&b).map(|(x, y)| x | y).collect();
        from_twos(v, self.neg || o.neg)
    }

    pub fn bitxor(&self, o: &Self) -> Self {
        let len = self.mag.len().max(o.mag.len());
        let a = to_twos(self, len);
        let b = to_twos(o, len);
        let v: Vec<u64> = a.iter().zip(&b).map(|(x, y)| x ^ y).collect();
        from_twos(v, self.neg != o.neg)
    }

    /// `~x` = -x - 1.
    pub fn not(&self) -> Self {
        if self.neg {
            // x = -m (m > 0): ~x = m - 1.
            Self::from_parts(false, sub_one_mag(&self.mag))
        } else {
            Self::from_parts(true, add_small_mag(&self.mag, 1))
        }
    }

    /// Left shift by a non-negative bit count with lumen's size check.
    fn shl_bits(&self, n: &[u64]) -> Result<Self, BigIntError> {
        if self.is_zero() {
            return Ok(Self::zero());
        }
        let n = match n.len() {
            0 => 0,
            1 => n[0],
            _ => u64::MAX,
        };
        if n > MAX_SHIFT_BITS {
            return Err(BigIntError::TooLarge);
        }
        Ok(BigInt { neg: self.neg, mag: shl_mag(&self.mag, n) })
    }

    /// Arithmetic (flooring) right shift by a non-negative bit count of any size.
    fn shr_bits(&self, n: &[u64]) -> Self {
        let bl = bit_len_mag(&self.mag);
        let n = match n.len() {
            0 => 0,
            1 => n[0],
            _ => u64::MAX,
        };
        if n >= bl {
            return if self.neg { Self::from_i64(-1) } else { Self::zero() };
        }
        if !self.neg {
            return Self::from_parts(false, shr_mag(&self.mag, n));
        }
        // floor(-m / 2^n) = -(((m - 1) >> n) + 1)
        let t = shr_mag(&sub_one_mag(&self.mag), n);
        Self::from_parts(true, add_small_mag(&t, 1))
    }

    /// `self << bits` (a negative count shifts right). Fails with [`BigIntError::TooLarge`]
    /// when shifting a non-zero value left by more than [`MAX_SHIFT_BITS`].
    pub fn shl(&self, bits: &Self) -> Result<Self, BigIntError> {
        if bits.neg {
            Ok(self.shr_bits(&bits.mag))
        } else {
            self.shl_bits(&bits.mag)
        }
    }

    /// `self >> bits`: arithmetic (flooring) shift; a negative count shifts left.
    pub fn shr(&self, bits: &Self) -> Result<Self, BigIntError> {
        if bits.neg {
            self.shl_bits(&bits.mag)
        } else {
            Ok(self.shr_bits(&bits.mag))
        }
    }

    /// `self mod 2^bits` as a non-negative magnitude. Negative values need ceil(bits / 64)
    /// limbs, so callers bound `bits` first.
    fn mod_pow2(&self, bits: u64) -> Vec<u64> {
        let words = bits.div_ceil(64) as usize;
        let mut v = if self.neg {
            to_twos(self, words.max(self.mag.len()))
        } else {
            self.mag.clone()
        };
        v.truncate(words);
        let rem = bits % 64;
        if rem != 0 && v.len() == words {
            if let Some(last) = v.last_mut() {
                *last &= (1u64 << rem) - 1;
            }
        }
        trim(&mut v);
        v
    }

    /// BigInt.asIntN(bits, self). `Err(TooLarge)` reproduces lumen's refusal for
    /// bits > [`MAX_AS_N_BITS`] when the value does not already fit (see module docs).
    pub fn as_int_n(&self, bits: u64) -> Result<Self, BigIntError> {
        if bits > 0 && bit_len_mag(&self.mag) < bits {
            return Ok(self.clone());
        }
        if bits > MAX_AS_N_BITS {
            return Err(BigIntError::TooLarge);
        }
        if bits == 0 {
            return Ok(Self::zero());
        }
        let r = self.mod_pow2(bits);
        // r in [0, 2^bits); values >= 2^(bits-1) wrap to r - 2^bits.
        if bit_len_mag(&r) == bits {
            let p = shl_mag(&[1], bits);
            Ok(Self::from_parts(true, sub_mag(&p, &r)))
        } else {
            Ok(Self::from_parts(false, r))
        }
    }

    /// BigInt.asUintN(bits, self). `Err(TooLarge)` reproduces lumen's refusal for
    /// bits > [`MAX_AS_N_BITS`] when the value does not already fit (see module docs).
    pub fn as_uint_n(&self, bits: u64) -> Result<Self, BigIntError> {
        if !self.neg && bit_len_mag(&self.mag) <= bits {
            return Ok(self.clone());
        }
        if bits > MAX_AS_N_BITS {
            return Err(BigIntError::TooLarge);
        }
        Ok(Self::from_parts(false, self.mod_pow2(bits)))
    }

    /// Low 64 bits as a signed value (BigInt64Array element conversion, ToBigInt64).
    pub fn to_i64_wrapping(&self) -> i64 {
        self.to_u64_wrapping() as i64
    }

    /// Low 64 bits of the two's complement value (BigUint64Array, ToBigUint64).
    pub fn to_u64_wrapping(&self) -> u64 {
        let lo = self.mag.first().copied().unwrap_or(0);
        if self.neg {
            lo.wrapping_neg()
        } else {
            lo
        }
    }

    /// Exact comparison with a Number; `None` if `x` is NaN.
    pub fn cmp_f64(&self, x: f64) -> Option<Ordering> {
        if x.is_nan() {
            return None;
        }
        if x == f64::INFINITY {
            return Some(Ordering::Less);
        }
        if x == f64::NEG_INFINITY {
            return Some(Ordering::Greater);
        }
        let xs = if x > 0.0 {
            1
        } else if x < 0.0 {
            -1
        } else {
            0
        };
        let ss = self.signum();
        if ss != xs {
            return Some(ss.cmp(&xs));
        }
        if ss == 0 {
            return Some(Ordering::Equal);
        }
        // Same non-zero sign: compare magnitudes.
        let a = x.abs();
        let fl = a.floor();
        let flb = Self::from_f64(fl).unwrap_or_default();
        let mut ord = cmp_mag(&self.mag, &flb.mag);
        if ord == Ordering::Equal && fl != a {
            ord = Ordering::Less;
        }
        Some(if self.neg { ord.reverse() } else { ord })
    }

    /// Exact equality with a Number (false for NaN, infinities and non-integers).
    pub fn eq_f64(&self, x: f64) -> bool {
        self.cmp_f64(x) == Some(Ordering::Equal)
    }
}

impl Ord for BigInt {
    fn cmp(&self, o: &Self) -> Ordering {
        match (self.neg, o.neg) {
            (false, true) => Ordering::Greater,
            (true, false) => Ordering::Less,
            (false, false) => cmp_mag(&self.mag, &o.mag),
            (true, true) => cmp_mag(&o.mag, &self.mag),
        }
    }
}

impl PartialOrd for BigInt {
    fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
        Some(self.cmp(o))
    }
}

impl fmt::Display for BigInt {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.to_string_radix(10))
    }
}

impl From<i64> for BigInt {
    fn from(v: i64) -> Self {
        BigInt::from_i64(v)
    }
}

impl From<u64> for BigInt {
    fn from(v: u64) -> Self {
        BigInt::from_u64(v)
    }
}

impl From<i128> for BigInt {
    fn from(v: i128) -> Self {
        BigInt::from_i128(v)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn b(s: &str) -> BigInt {
        BigInt::from_str_radix(s, 10).unwrap()
    }

    fn u(s: &str) -> Vec<u16> {
        s.encode_utf16().collect()
    }

    #[test]
    fn basics() {
        assert_eq!(b("-5").div(&b("2")).unwrap(), b("-2"));
        assert_eq!(b("-5").rem(&b("2")).unwrap(), b("-1"));
        assert_eq!(b("5").rem(&b("-2")).unwrap(), b("1"));
        assert!(b("1").div(&BigInt::zero()).is_none());
        assert_eq!(b("-7").shr(&b("1")).unwrap(), b("-4"));
        assert_eq!(b("-7").shl(&b("-1")).unwrap(), b("-4"));
        assert_eq!(b("5").not(), b("-6"));
        assert_eq!(b("-5").bitand(&b("3")), b("3"));
        assert_eq!(b("-5").bitor(&b("3")), b("-5"));
        assert_eq!(b("-5").bitxor(&b("3")), b("-8"));
        assert_eq!(b("2").pow(&b("64")).unwrap().to_string_radix(36), "3w5e11264sgsg");
        assert_eq!(b("-2").pow(&b("3")).unwrap(), b("-8"));
        assert_eq!(BigInt::zero().pow(&BigInt::zero()).unwrap(), BigInt::one());
        assert_eq!(b("2").pow(&b("-1")), Err(BigIntError::NegativeExponent));
        assert_eq!(b("1").shl(&b("10000000000")), Err(BigIntError::TooLarge));
        assert_eq!(b("-1").shr(&b("10000000000")).unwrap(), b("-1"));
        assert_eq!(BigInt::zero().shl(&b("10000000000")).unwrap(), BigInt::zero());
    }

    #[test]
    fn as_n() {
        assert_eq!(b("9223372036854775808").as_int_n(64).unwrap(), b("-9223372036854775808"));
        assert_eq!(b("-1").as_uint_n(64).unwrap(), b("18446744073709551615"));
        assert_eq!(b("5").as_int_n(3).unwrap(), b("-3"));
        assert_eq!(b("-5").as_int_n(3).unwrap(), b("3"));
        assert_eq!(b("-5").as_uint_n(3).unwrap(), b("3"));
        assert_eq!(b("1").as_int_n(1).unwrap(), b("-1"));
        assert_eq!(b("5").as_int_n(0).unwrap(), BigInt::zero());
        assert_eq!(b("-1").as_uint_n((1 << 53) - 1), Err(BigIntError::TooLarge));
        assert_eq!(b("-1").as_int_n((1 << 53) - 1).unwrap(), b("-1"));
    }

    #[test]
    fn conversions() {
        assert_eq!(BigInt::parse(&u(" 12 ")), Some(b("12")));
        assert_eq!(BigInt::parse(&u("")), Some(BigInt::zero()));
        assert_eq!(BigInt::parse(&u("-0x10")), None);
        assert_eq!(BigInt::parse(&u("0X1F")), Some(b("31")));
        assert_eq!(BigInt::parse(&u("1e3")), None);
        assert_eq!(BigInt::parse(&u("-")), None);
        assert_eq!(BigInt::from_f64(1.5), None);
        assert_eq!(BigInt::from_f64(-0.0), Some(BigInt::zero()));
        assert_eq!(BigInt::from_f64(1e21).unwrap(), b("1000000000000000000000"));
        assert_eq!(b("2").pow(&b("1024")).unwrap().to_f64(), f64::INFINITY);
        let near = b("2").pow(&b("1024")).unwrap().sub(&b("2").pow(&b("970")).unwrap());
        assert_eq!(near.to_f64(), f64::INFINITY);
        assert_eq!(near.sub(&BigInt::one()).to_f64(), f64::MAX);
        assert_eq!(b("1").cmp_f64(1.5), Some(Ordering::Less));
        assert_eq!(b("2").cmp_f64(1.5), Some(Ordering::Greater));
        assert_eq!(b("-2").cmp_f64(-1.5), Some(Ordering::Less));
        assert!(b("18446744073709551616").eq_f64(18446744073709551616.0));
        assert_eq!(b("1").cmp_f64(f64::NAN), None);
        assert_eq!(BigInt::parse_literal("1F", 16), b("31"));
        assert_eq!(b("-255").to_string_radix(16), "-ff");
        assert_eq!(b("-1").to_i64_wrapping(), -1);
        assert_eq!(b("-1").to_u64_wrapping(), u64::MAX);
    }

    #[test]
    fn big_roundtrip() {
        let x = b("3").pow(&b("20000")).unwrap();
        for radix in [2u32, 3, 7, 10, 16, 36] {
            let s = x.to_string_radix(radix);
            assert_eq!(BigInt::from_str_radix(&s, radix).unwrap(), x);
        }
        let y = b("7").pow(&b("5000")).unwrap();
        let (q, r) = x.div_rem(&y).unwrap();
        assert_eq!(q.mul(&y).add(&r), x);
        assert!(r < y);
    }
}
