//! Minimal arbitrary-precision unsigned integers for RSA / DH / prime generation.
//! Little-endian `u64` limbs, always normalized (no high zero limbs; zero = no limbs).

use std::cmp::Ordering;

#[derive(Clone, PartialEq, Eq, Default, Hash)]
pub struct BigUint {
    limbs: Vec<u64>,
}

impl std::fmt::Debug for BigUint {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "0x{}", self.to_hex())
    }
}

fn normalize(v: &mut Vec<u64>) {
    while let Some(&0) = v.last() {
        v.pop();
    }
}

impl BigUint {
    pub fn zero() -> BigUint {
        BigUint { limbs: Vec::new() }
    }

    pub fn one() -> BigUint {
        BigUint { limbs: vec![1] }
    }

    pub fn from_u64(v: u64) -> BigUint {
        let mut b = BigUint { limbs: vec![v] };
        normalize(&mut b.limbs);
        b
    }

    pub fn from_limbs(mut limbs: Vec<u64>) -> BigUint {
        normalize(&mut limbs);
        BigUint { limbs }
    }

    pub fn limbs(&self) -> &[u64] {
        &self.limbs
    }

    /// Big-endian bytes (leading zeros allowed).
    pub fn from_bytes_be(bytes: &[u8]) -> BigUint {
        let mut limbs = Vec::with_capacity(bytes.len() / 8 + 1);
        let mut i = bytes.len();
        while i > 0 {
            let start = i.saturating_sub(8);
            let mut w = 0u64;
            for &b in &bytes[start..i] {
                w = (w << 8) | b as u64;
            }
            limbs.push(w);
            i = start;
        }
        BigUint::from_limbs(limbs)
    }

    /// Little-endian bytes.
    pub fn from_bytes_le(bytes: &[u8]) -> BigUint {
        let mut be = bytes.to_vec();
        be.reverse();
        BigUint::from_bytes_be(&be)
    }

    /// Minimal big-endian encoding (empty for zero).
    pub fn to_bytes_be(&self) -> Vec<u8> {
        let mut out = Vec::with_capacity(self.limbs.len() * 8);
        for w in self.limbs.iter().rev() {
            out.extend_from_slice(&w.to_be_bytes());
        }
        let first = out.iter().position(|&b| b != 0).unwrap_or(out.len());
        out.drain(..first);
        out
    }

    /// Big-endian encoding left-padded with zeros to `len` bytes. If the value needs more
    /// than `len` bytes the minimal encoding is returned (like the original's
    /// `bigIntToBytesBE(v, len)`).
    pub fn to_bytes_be_padded(&self, len: usize) -> Vec<u8> {
        let b = self.to_bytes_be();
        if b.len() >= len {
            return b;
        }
        let mut out = vec![0u8; len - b.len()];
        out.extend_from_slice(&b);
        out
    }

    /// Little-endian encoding of exactly `len` bytes (truncating high bytes).
    pub fn to_bytes_le_padded(&self, len: usize) -> Vec<u8> {
        let mut out = vec![0u8; len];
        for (i, w) in self.limbs.iter().enumerate() {
            for k in 0..8 {
                let idx = i * 8 + k;
                if idx < len {
                    out[idx] = (w >> (8 * k)) as u8;
                }
            }
        }
        out
    }

    pub fn from_hex(s: &str) -> Option<BigUint> {
        let s = s.trim_start_matches("0x");
        let mut limbs = Vec::new();
        let chars: Vec<u8> = s.bytes().collect();
        let mut end = chars.len();
        while end > 0 {
            let start = end.saturating_sub(16);
            let chunk = std::str::from_utf8(&chars[start..end]).ok()?;
            limbs.push(u64::from_str_radix(chunk, 16).ok()?);
            end = start;
        }
        Some(BigUint::from_limbs(limbs))
    }

    /// Lower-case hex without leading zeros (`"0"` for zero).
    pub fn to_hex(&self) -> String {
        if self.limbs.is_empty() {
            return "0".to_string();
        }
        let mut s = format!("{:x}", self.limbs[self.limbs.len() - 1]);
        for w in self.limbs.iter().rev().skip(1) {
            s.push_str(&format!("{:016x}", w));
        }
        s
    }

    /// Decimal string.
    pub fn to_decimal(&self) -> String {
        if self.is_zero() {
            return "0".into();
        }
        let mut parts = Vec::new();
        let mut cur = self.clone();
        let base = 10_000_000_000_000_000_000u64; // 1e19
        while !cur.is_zero() {
            let (q, r) = cur.divrem_u64(base);
            parts.push(r);
            cur = q;
        }
        let mut s = format!("{}", parts[parts.len() - 1]);
        for p in parts.iter().rev().skip(1) {
            s.push_str(&format!("{:019}", p));
        }
        s
    }

    pub fn from_decimal(s: &str) -> Option<BigUint> {
        if s.is_empty() {
            return None;
        }
        let mut acc = BigUint::zero();
        for c in s.bytes() {
            if !c.is_ascii_digit() {
                return None;
            }
            acc = acc.mul_u64(10).add_u64((c - b'0') as u64);
        }
        Some(acc)
    }

    pub fn is_zero(&self) -> bool {
        self.limbs.is_empty()
    }

    pub fn is_one(&self) -> bool {
        self.limbs.len() == 1 && self.limbs[0] == 1
    }

    pub fn is_odd(&self) -> bool {
        self.limbs.first().is_some_and(|w| w & 1 == 1)
    }

    pub fn is_even(&self) -> bool {
        !self.is_odd()
    }

    /// Number of significant bits (0 for zero).
    pub fn bits(&self) -> usize {
        match self.limbs.last() {
            None => 0,
            Some(&top) => self.limbs.len() * 64 - top.leading_zeros() as usize,
        }
    }

    pub fn bit(&self, i: usize) -> bool {
        let w = i / 64;
        w < self.limbs.len() && (self.limbs[w] >> (i % 64)) & 1 == 1
    }

    pub fn set_bit(&mut self, i: usize) {
        let w = i / 64;
        if self.limbs.len() <= w {
            self.limbs.resize(w + 1, 0);
        }
        self.limbs[w] |= 1u64 << (i % 64);
    }

    pub fn low_u64(&self) -> u64 {
        self.limbs.first().copied().unwrap_or(0)
    }

    /// `Some(v)` if the value fits in a u64.
    pub fn to_u64(&self) -> Option<u64> {
        match self.limbs.len() {
            0 => Some(0),
            1 => Some(self.limbs[0]),
            _ => None,
        }
    }

    pub fn add(&self, other: &BigUint) -> BigUint {
        let (a, b) = if self.limbs.len() >= other.limbs.len() { (self, other) } else { (other, self) };
        let mut out = Vec::with_capacity(a.limbs.len() + 1);
        let mut carry = 0u64;
        for i in 0..a.limbs.len() {
            let (s1, c1) = a.limbs[i].overflowing_add(*b.limbs.get(i).unwrap_or(&0));
            let (s2, c2) = s1.overflowing_add(carry);
            out.push(s2);
            carry = (c1 as u64) + (c2 as u64);
        }
        if carry > 0 {
            out.push(carry);
        }
        BigUint::from_limbs(out)
    }

    pub fn add_u64(&self, v: u64) -> BigUint {
        self.add(&BigUint::from_u64(v))
    }

    /// `self - other`, or `None` if negative.
    pub fn checked_sub(&self, other: &BigUint) -> Option<BigUint> {
        if self < other {
            return None;
        }
        let mut out = Vec::with_capacity(self.limbs.len());
        let mut borrow = 0u64;
        for i in 0..self.limbs.len() {
            let (d1, b1) = self.limbs[i].overflowing_sub(*other.limbs.get(i).unwrap_or(&0));
            let (d2, b2) = d1.overflowing_sub(borrow);
            out.push(d2);
            borrow = (b1 as u64) + (b2 as u64);
        }
        Some(BigUint::from_limbs(out))
    }

    /// `self - other`; panics if negative.
    pub fn sub(&self, other: &BigUint) -> BigUint {
        self.checked_sub(other).expect("BigUint subtraction underflow")
    }

    pub fn sub_u64(&self, v: u64) -> BigUint {
        self.sub(&BigUint::from_u64(v))
    }

    pub fn mul(&self, other: &BigUint) -> BigUint {
        if self.is_zero() || other.is_zero() {
            return BigUint::zero();
        }
        let mut out = vec![0u64; self.limbs.len() + other.limbs.len()];
        for (i, &a) in self.limbs.iter().enumerate() {
            let mut carry = 0u128;
            for (j, &b) in other.limbs.iter().enumerate() {
                let t = out[i + j] as u128 + (a as u128) * (b as u128) + carry;
                out[i + j] = t as u64;
                carry = t >> 64;
            }
            out[i + other.limbs.len()] = carry as u64;
        }
        BigUint::from_limbs(out)
    }

    pub fn mul_u64(&self, v: u64) -> BigUint {
        let mut out = Vec::with_capacity(self.limbs.len() + 1);
        let mut carry = 0u128;
        for &a in &self.limbs {
            let t = (a as u128) * (v as u128) + carry;
            out.push(t as u64);
            carry = t >> 64;
        }
        out.push(carry as u64);
        BigUint::from_limbs(out)
    }

    pub fn shl(&self, bits: usize) -> BigUint {
        if self.is_zero() {
            return BigUint::zero();
        }
        let words = bits / 64;
        let sh = bits % 64;
        let mut out = vec![0u64; words];
        if sh == 0 {
            out.extend_from_slice(&self.limbs);
        } else {
            let mut carry = 0u64;
            for &w in &self.limbs {
                out.push((w << sh) | carry);
                carry = w >> (64 - sh);
            }
            out.push(carry);
        }
        BigUint::from_limbs(out)
    }

    pub fn shr(&self, bits: usize) -> BigUint {
        let words = bits / 64;
        if words >= self.limbs.len() {
            return BigUint::zero();
        }
        let sh = bits % 64;
        let src = &self.limbs[words..];
        let mut out = Vec::with_capacity(src.len());
        if sh == 0 {
            out.extend_from_slice(src);
        } else {
            for i in 0..src.len() {
                let hi = if i + 1 < src.len() { src[i + 1] << (64 - sh) } else { 0 };
                out.push((src[i] >> sh) | hi);
            }
        }
        BigUint::from_limbs(out)
    }

    /// Quotient and remainder by a single word.
    pub fn divrem_u64(&self, d: u64) -> (BigUint, u64) {
        assert!(d != 0, "division by zero");
        let mut q = vec![0u64; self.limbs.len()];
        let mut r: u128 = 0;
        for i in (0..self.limbs.len()).rev() {
            let cur = (r << 64) | self.limbs[i] as u128;
            q[i] = (cur / d as u128) as u64;
            r = cur % d as u128;
        }
        (BigUint::from_limbs(q), r as u64)
    }

    pub fn rem_u64(&self, d: u64) -> u64 {
        let mut r: u128 = 0;
        for i in (0..self.limbs.len()).rev() {
            r = ((r << 64) | self.limbs[i] as u128) % d as u128;
        }
        r as u64
    }

    /// Knuth algorithm D. Panics on division by zero.
    pub fn divrem(&self, d: &BigUint) -> (BigUint, BigUint) {
        assert!(!d.is_zero(), "division by zero");
        if self < d {
            return (BigUint::zero(), self.clone());
        }
        if d.limbs.len() == 1 {
            let (q, r) = self.divrem_u64(d.limbs[0]);
            return (q, BigUint::from_u64(r));
        }
        let n = d.limbs.len();
        let m = self.limbs.len() - n;
        let s = d.limbs[n - 1].leading_zeros();
        let vn: Vec<u64> = shl_words(&d.limbs, s, n);
        let mut un: Vec<u64> = shl_words(&self.limbs, s, self.limbs.len() + 1);
        let mut q = vec![0u64; m + 1];
        let b: u128 = 1u128 << 64;
        for j in (0..=m).rev() {
            let num = ((un[j + n] as u128) << 64) | un[j + n - 1] as u128;
            let mut qhat = num / vn[n - 1] as u128;
            let mut rhat = num % vn[n - 1] as u128;
            while qhat >= b || qhat * vn[n - 2] as u128 > ((rhat << 64) | un[j + n - 2] as u128) {
                qhat -= 1;
                rhat += vn[n - 1] as u128;
                if rhat >= b {
                    break;
                }
            }
            // Multiply and subtract.
            let mut borrow: i128 = 0;
            let mut carry: u128 = 0;
            for i in 0..n {
                let p = qhat * vn[i] as u128 + carry;
                carry = p >> 64;
                let t = un[i + j] as i128 - borrow - (p as u64) as i128;
                un[i + j] = t as u64;
                borrow = if t < 0 { 1 } else { 0 };
            }
            let t = un[j + n] as i128 - borrow - carry as i128;
            un[j + n] = t as u64;
            if t < 0 {
                qhat -= 1;
                let mut c: u128 = 0;
                for i in 0..n {
                    let s2 = un[i + j] as u128 + vn[i] as u128 + c;
                    un[i + j] = s2 as u64;
                    c = s2 >> 64;
                }
                un[j + n] = un[j + n].wrapping_add(c as u64);
            }
            q[j] = qhat as u64;
        }
        // Remainder: un[0..n] >> s.
        let mut r = vec![0u64; n];
        for i in 0..n {
            r[i] = if s == 0 { un[i] } else { (un[i] >> s) | (un[i + 1] << (64 - s)) };
        }
        (BigUint::from_limbs(q), BigUint::from_limbs(r))
    }

    pub fn rem(&self, m: &BigUint) -> BigUint {
        self.divrem(m).1
    }

    pub fn div(&self, d: &BigUint) -> BigUint {
        self.divrem(d).0
    }

    /// `(self * other) mod m`.
    pub fn mul_mod(&self, other: &BigUint, m: &BigUint) -> BigUint {
        self.mul(other).rem(m)
    }

    /// `(self + other) mod m` (inputs need not be reduced).
    pub fn add_mod(&self, other: &BigUint, m: &BigUint) -> BigUint {
        self.add(other).rem(m)
    }

    /// `(self - other) mod m` for reduced inputs.
    pub fn sub_mod(&self, other: &BigUint, m: &BigUint) -> BigUint {
        let a = self.rem(m);
        let b = other.rem(m);
        if a >= b {
            a.sub(&b)
        } else {
            a.add(m).sub(&b)
        }
    }

    /// `self^exp mod m` (`m > 0`). Uses Montgomery multiplication for odd `m`.
    pub fn modpow(&self, exp: &BigUint, m: &BigUint) -> BigUint {
        assert!(!m.is_zero(), "modulus is zero");
        if m.is_one() {
            return BigUint::zero();
        }
        if m.is_odd() {
            let ctx = Montgomery::new(m);
            return ctx.pow(&self.rem(m), exp);
        }
        // Plain square-and-multiply for even moduli.
        let mut result = BigUint::one();
        let base = self.rem(m);
        for i in (0..exp.bits()).rev() {
            result = result.mul(&result).rem(m);
            if exp.bit(i) {
                result = result.mul(&base).rem(m);
            }
        }
        result
    }

    pub fn gcd(&self, other: &BigUint) -> BigUint {
        let mut a = self.clone();
        let mut b = other.clone();
        while !b.is_zero() {
            let r = a.rem(&b);
            a = b;
            b = r;
        }
        a
    }

    /// Modular inverse, `None` if `gcd(self, m) != 1`.
    pub fn modinv(&self, m: &BigUint) -> Option<BigUint> {
        if m.is_zero() {
            return None;
        }
        let mut r0 = m.clone();
        let mut r1 = self.rem(m);
        let mut t0 = BigUint::zero();
        let mut t1 = BigUint::one();
        while !r1.is_zero() {
            let (q, r2) = r0.divrem(&r1);
            let qt = q.mul(&t1).rem(m);
            let t2 = if t0 >= qt { t0.sub(&qt) } else { t0.add(m).sub(&qt) };
            r0 = r1;
            r1 = r2;
            t0 = t1;
            t1 = t2;
        }
        if r0.is_one() {
            Some(t0.rem(m))
        } else {
            None
        }
    }

    /// Uniform random value in `[0, bound)` (`bound > 0`).
    pub fn random_below(bound: &BigUint) -> BigUint {
        assert!(!bound.is_zero());
        let bits = bound.bits();
        let bytes = bits.div_ceil(8);
        let excess = bytes * 8 - bits;
        loop {
            let mut buf = vec![0u8; bytes];
            super::random::fill_random(&mut buf);
            if excess > 0 {
                buf[0] &= 0xffu8 >> excess;
            }
            let v = BigUint::from_bytes_be(&buf);
            if &v < bound {
                return v;
            }
        }
    }

    /// Uniform random value in `[low, high)`.
    pub fn random_range(low: &BigUint, high: &BigUint) -> BigUint {
        let span = high.sub(low);
        low.add(&BigUint::random_below(&span))
    }
}

fn shl_words(src: &[u64], s: u32, len: usize) -> Vec<u64> {
    let mut out = vec![0u64; len];
    if s == 0 {
        out[..src.len()].copy_from_slice(src);
    } else {
        let mut carry = 0u64;
        for i in 0..src.len() {
            out[i] = (src[i] << s) | carry;
            carry = src[i] >> (64 - s);
        }
        if src.len() < len {
            out[src.len()] = carry;
        }
    }
    out
}

impl PartialOrd for BigUint {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for BigUint {
    fn cmp(&self, other: &Self) -> Ordering {
        if self.limbs.len() != other.limbs.len() {
            return self.limbs.len().cmp(&other.limbs.len());
        }
        for i in (0..self.limbs.len()).rev() {
            match self.limbs[i].cmp(&other.limbs[i]) {
                Ordering::Equal => continue,
                o => return o,
            }
        }
        Ordering::Equal
    }
}

/// Montgomery arithmetic context for an odd modulus.
#[derive(Clone)]
pub struct Montgomery {
    m: Vec<u64>,
    n: usize,
    m_inv: u64,
    r2: Vec<u64>,
    modulus: BigUint,
}

impl Montgomery {
    pub fn new(m: &BigUint) -> Montgomery {
        assert!(m.is_odd(), "Montgomery modulus must be odd");
        let n = m.limbs.len();
        // -m^{-1} mod 2^64 by Newton iteration.
        let m0 = m.limbs[0];
        let mut inv: u64 = 1;
        for _ in 0..6 {
            inv = inv.wrapping_mul(2u64.wrapping_sub(m0.wrapping_mul(inv)));
        }
        let m_inv = inv.wrapping_neg();
        let r2 = BigUint::one().shl(128 * n).rem(m);
        let mut r2l = r2.limbs.clone();
        r2l.resize(n, 0);
        Montgomery { m: m.limbs.clone(), n, m_inv, r2: r2l, modulus: m.clone() }
    }

    fn mont_mul(&self, a: &[u64], b: &[u64], out: &mut [u64]) {
        let n = self.n;
        let m = &self.m;
        let mut t = vec![0u64; n + 2];
        for i in 0..n {
            let ai = a[i] as u128;
            let mut c: u128 = 0;
            for j in 0..n {
                let s = t[j] as u128 + ai * b[j] as u128 + c;
                t[j] = s as u64;
                c = s >> 64;
            }
            let s = t[n] as u128 + c;
            t[n] = s as u64;
            t[n + 1] = (s >> 64) as u64;
            let mq = t[0].wrapping_mul(self.m_inv) as u128;
            let s = t[0] as u128 + mq * m[0] as u128;
            let mut c = s >> 64;
            for j in 1..n {
                let s = t[j] as u128 + mq * m[j] as u128 + c;
                t[j - 1] = s as u64;
                c = s >> 64;
            }
            let s = t[n] as u128 + c;
            t[n - 1] = s as u64;
            let s2 = t[n + 1] as u128 + (s >> 64);
            t[n] = s2 as u64;
            t[n + 1] = 0;
        }
        // Conditional subtraction.
        let ge = if t[n] != 0 {
            true
        } else {
            let mut ge = true;
            for i in (0..n).rev() {
                if t[i] != m[i] {
                    ge = t[i] > m[i];
                    break;
                }
            }
            ge
        };
        if ge {
            let mut borrow = 0u64;
            for i in 0..n {
                let (d1, b1) = t[i].overflowing_sub(m[i]);
                let (d2, b2) = d1.overflowing_sub(borrow);
                t[i] = d2;
                borrow = (b1 as u64) + (b2 as u64);
            }
        }
        out.copy_from_slice(&t[..n]);
    }

    fn to_mont(&self, a: &BigUint) -> Vec<u64> {
        let mut al = a.limbs.clone();
        al.resize(self.n, 0);
        let mut out = vec![0u64; self.n];
        self.mont_mul(&al, &self.r2, &mut out);
        out
    }

    fn from_mont(&self, a: &[u64]) -> BigUint {
        let mut one = vec![0u64; self.n];
        one[0] = 1;
        let mut out = vec![0u64; self.n];
        self.mont_mul(a, &one, &mut out);
        BigUint::from_limbs(out)
    }

    /// `base^exp mod m` for `base < m`, 4-bit fixed window.
    pub fn pow(&self, base: &BigUint, exp: &BigUint) -> BigUint {
        if exp.is_zero() {
            return BigUint::one().rem(&self.modulus);
        }
        let n = self.n;
        let bm = self.to_mont(base);
        let one_m = self.to_mont(&BigUint::one());
        let mut table = vec![one_m.clone()];
        table.push(bm.clone());
        for i in 2..16 {
            let mut t = vec![0u64; n];
            self.mont_mul(&table[i - 1], &bm, &mut t);
            table.push(t);
        }
        let mut acc = one_m;
        let mut tmp = vec![0u64; n];
        let bits = exp.bits();
        let windows = bits.div_ceil(4);
        for w in (0..windows).rev() {
            for _ in 0..4 {
                self.mont_mul(&acc, &acc, &mut tmp);
                std::mem::swap(&mut acc, &mut tmp);
            }
            let mut idx = 0usize;
            for k in 0..4 {
                if exp.bit(w * 4 + k) {
                    idx |= 1 << k;
                }
            }
            if idx != 0 {
                self.mont_mul(&acc, &table[idx], &mut tmp);
                std::mem::swap(&mut acc, &mut tmp);
            }
        }
        self.from_mont(&acc)
    }
}
