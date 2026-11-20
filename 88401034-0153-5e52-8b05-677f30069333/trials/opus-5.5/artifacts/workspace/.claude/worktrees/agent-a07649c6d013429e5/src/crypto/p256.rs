//! NIST P-256 (prime256v1 / secp256r1): point arithmetic, encoding, ECDH and ECDSA.

use super::bigint::BigUint;
use super::hash::{digest, HashAlg};
use super::CryptoError;

type Limbs = [u64; 4];

const P: Limbs = [0xffffffffffffffff, 0x00000000ffffffff, 0x0000000000000000, 0xffffffff00000001];
/// -p^{-1} mod 2^64
const P_INV: u64 = 1;

/// Group order n (big-endian bytes).
pub const ORDER_BE: [u8; 32] = [
    0xff, 0xff, 0xff, 0xff, 0x00, 0x00, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xbc, 0xe6, 0xfa, 0xad,
    0xa7, 0x17, 0x9e, 0x84, 0xf3, 0xb9, 0xca, 0xc2, 0xfc, 0x63, 0x25, 0x51,
];
const B_BE: [u8; 32] = [
    0x5a, 0xc6, 0x35, 0xd8, 0xaa, 0x3a, 0x93, 0xe7, 0xb3, 0xeb, 0xbd, 0x55, 0x76, 0x98, 0x86, 0xbc, 0x65, 0x1d, 0x06, 0xb0,
    0xcc, 0x53, 0xb0, 0xf6, 0x3b, 0xce, 0x3c, 0x3e, 0x27, 0xd2, 0x60, 0x4b,
];
const GX_BE: [u8; 32] = [
    0x6b, 0x17, 0xd1, 0xf2, 0xe1, 0x2c, 0x42, 0x47, 0xf8, 0xbc, 0xe6, 0xe5, 0x63, 0xa4, 0x40, 0xf2, 0x77, 0x03, 0x7d, 0x81,
    0x2d, 0xeb, 0x33, 0xa0, 0xf4, 0xa1, 0x39, 0x45, 0xd8, 0x98, 0xc2, 0x96,
];
const GY_BE: [u8; 32] = [
    0x4f, 0xe3, 0x42, 0xe2, 0xfe, 0x1a, 0x7f, 0x9b, 0x8e, 0xe7, 0xeb, 0x4a, 0x7c, 0x0f, 0x9e, 0x16, 0x2b, 0xce, 0x33, 0x57,
    0x6b, 0x31, 0x5e, 0xce, 0xcb, 0xb6, 0x40, 0x68, 0x37, 0xbf, 0x51, 0xf5,
];

fn limbs_from_be(b: &[u8; 32]) -> Limbs {
    let mut l = [0u64; 4];
    for i in 0..4 {
        let mut w = [0u8; 8];
        w.copy_from_slice(&b[32 - 8 * (i + 1)..32 - 8 * i]);
        l[i] = u64::from_be_bytes(w);
    }
    l
}

fn limbs_to_be(l: &Limbs) -> [u8; 32] {
    let mut b = [0u8; 32];
    for i in 0..4 {
        b[32 - 8 * (i + 1)..32 - 8 * i].copy_from_slice(&l[i].to_be_bytes());
    }
    b
}

fn geq(a: &Limbs, b: &Limbs) -> bool {
    for i in (0..4).rev() {
        if a[i] != b[i] {
            return a[i] > b[i];
        }
    }
    true
}

fn sub_limbs(a: &Limbs, b: &Limbs) -> (Limbs, u64) {
    let mut r = [0u64; 4];
    let mut borrow = 0u64;
    for i in 0..4 {
        let (d1, b1) = a[i].overflowing_sub(b[i]);
        let (d2, b2) = d1.overflowing_sub(borrow);
        r[i] = d2;
        borrow = (b1 as u64) + (b2 as u64);
    }
    (r, borrow)
}

fn add_limbs(a: &Limbs, b: &Limbs) -> (Limbs, u64) {
    let mut r = [0u64; 4];
    let mut carry = 0u64;
    for i in 0..4 {
        let (s1, c1) = a[i].overflowing_add(b[i]);
        let (s2, c2) = s1.overflowing_add(carry);
        r[i] = s2;
        carry = (c1 as u64) + (c2 as u64);
    }
    (r, carry)
}

/// Field element mod p in Montgomery form.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Fe(Limbs);

impl Fe {
    const ZERO: Fe = Fe([0; 4]);

    fn mont_mul(a: &Limbs, b: &Limbs) -> Limbs {
        let mut t = [0u64; 6];
        for i in 0..4 {
            let mut c: u128 = 0;
            for j in 0..4 {
                let s = t[j] as u128 + (a[i] as u128) * (b[j] as u128) + c;
                t[j] = s as u64;
                c = s >> 64;
            }
            let s = t[4] as u128 + c;
            t[4] = s as u64;
            t[5] = (s >> 64) as u64;
            let m = t[0].wrapping_mul(P_INV) as u128;
            let s = t[0] as u128 + m * P[0] as u128;
            let mut c = s >> 64;
            for j in 1..4 {
                let s = t[j] as u128 + m * P[j] as u128 + c;
                t[j - 1] = s as u64;
                c = s >> 64;
            }
            let s = t[4] as u128 + c;
            t[3] = s as u64;
            t[4] = t[5] + (s >> 64) as u64;
            t[5] = 0;
        }
        let r = [t[0], t[1], t[2], t[3]];
        if t[4] != 0 || geq(&r, &P) {
            sub_limbs(&r, &P).0
        } else {
            r
        }
    }

    /// R^2 mod p, computed once.
    fn r2() -> Limbs {
        use std::sync::OnceLock;
        static R2: OnceLock<Limbs> = OnceLock::new();
        *R2.get_or_init(|| {
            let p = BigUint::from_limbs(P.to_vec());
            let r2 = BigUint::one().shl(512).rem(&p);
            let mut l = [0u64; 4];
            for (i, w) in r2.limbs().iter().enumerate() {
                l[i] = *w;
            }
            l
        })
    }

    /// From canonical big-endian bytes; `None` if `>= p`.
    pub fn from_be(b: &[u8; 32]) -> Option<Fe> {
        let l = limbs_from_be(b);
        if geq(&l, &P) {
            return None;
        }
        Some(Fe(Self::mont_mul(&l, &Self::r2())))
    }

    pub fn to_be(&self) -> [u8; 32] {
        let l = Self::mont_mul(&self.0, &[1, 0, 0, 0]);
        limbs_to_be(&l)
    }

    fn one() -> Fe {
        Fe(Self::mont_mul(&[1, 0, 0, 0], &Self::r2()))
    }

    fn add(&self, o: &Fe) -> Fe {
        let (r, carry) = add_limbs(&self.0, &o.0);
        if carry != 0 || geq(&r, &P) {
            Fe(sub_limbs(&r, &P).0)
        } else {
            Fe(r)
        }
    }

    fn sub(&self, o: &Fe) -> Fe {
        let (r, borrow) = sub_limbs(&self.0, &o.0);
        if borrow != 0 {
            Fe(add_limbs(&r, &P).0)
        } else {
            Fe(r)
        }
    }

    fn mul(&self, o: &Fe) -> Fe {
        Fe(Self::mont_mul(&self.0, &o.0))
    }

    fn sq(&self) -> Fe {
        self.mul(self)
    }

    fn is_zero(&self) -> bool {
        self.0 == [0; 4]
    }

    fn pow(&self, e_be: &[u8; 32]) -> Fe {
        let mut r = Fe::one();
        for byte in e_be {
            for bit in (0..8).rev() {
                r = r.sq();
                if (byte >> bit) & 1 == 1 {
                    r = r.mul(self);
                }
            }
        }
        r
    }

    fn inv(&self) -> Fe {
        // p - 2
        let mut e = limbs_to_be(&P);
        e[31] -= 2;
        self.pow(&e)
    }

    /// Square root (p ≡ 3 mod 4): `a^((p+1)/4)`, `None` if `a` is not a square.
    fn sqrt(&self) -> Option<Fe> {
        // (p + 1) / 4
        let p = BigUint::from_limbs(P.to_vec());
        let e = p.add_u64(1).shr(2).to_bytes_be_padded(32);
        let mut eb = [0u8; 32];
        eb.copy_from_slice(&e);
        let r = self.pow(&eb);
        if r.sq() == *self {
            Some(r)
        } else {
            None
        }
    }
}

fn fe_b() -> Fe {
    Fe::from_be(&B_BE).unwrap()
}

/// Affine point (x, y), or the point at infinity.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum AffinePoint {
    Infinity,
    Point { x: [u8; 32], y: [u8; 32] },
}

#[derive(Clone, Copy, Debug)]
struct Jac {
    x: Fe,
    y: Fe,
    z: Fe,
}

impl Jac {
    fn infinity() -> Jac {
        Jac { x: Fe::one(), y: Fe::one(), z: Fe::ZERO }
    }

    fn is_inf(&self) -> bool {
        self.z.is_zero()
    }

    fn from_affine(x: &Fe, y: &Fe) -> Jac {
        Jac { x: *x, y: *y, z: Fe::one() }
    }

    fn double(&self) -> Jac {
        if self.is_inf() || self.y.is_zero() {
            return Jac::infinity();
        }
        let delta = self.z.sq();
        let gamma = self.y.sq();
        let beta = self.x.mul(&gamma);
        let t = self.x.sub(&delta).mul(&self.x.add(&delta));
        let alpha = t.add(&t).add(&t);
        let beta4 = beta.add(&beta).add(&beta.add(&beta));
        let beta8 = beta4.add(&beta4);
        let x3 = alpha.sq().sub(&beta8);
        let z3 = self.y.add(&self.z).sq().sub(&gamma).sub(&delta);
        let g2 = gamma.sq();
        let g8 = {
            let g2x2 = g2.add(&g2);
            let g2x4 = g2x2.add(&g2x2);
            g2x4.add(&g2x4)
        };
        let y3 = alpha.mul(&beta4.sub(&x3)).sub(&g8);
        Jac { x: x3, y: y3, z: z3 }
    }

    fn add(&self, o: &Jac) -> Jac {
        if self.is_inf() {
            return *o;
        }
        if o.is_inf() {
            return *self;
        }
        let z1z1 = self.z.sq();
        let z2z2 = o.z.sq();
        let u1 = self.x.mul(&z2z2);
        let u2 = o.x.mul(&z1z1);
        let s1 = self.y.mul(&o.z).mul(&z2z2);
        let s2 = o.y.mul(&self.z).mul(&z1z1);
        let h = u2.sub(&u1);
        let rr = s2.sub(&s1);
        if h.is_zero() {
            if rr.is_zero() {
                return self.double();
            }
            return Jac::infinity();
        }
        let h2 = h.add(&h);
        let i = h2.sq();
        let j = h.mul(&i);
        let r = rr.add(&rr);
        let v = u1.mul(&i);
        let x3 = r.sq().sub(&j).sub(&v).sub(&v);
        let s1j = s1.mul(&j);
        let y3 = r.mul(&v.sub(&x3)).sub(&s1j).sub(&s1j);
        let z3 = self.z.add(&o.z).sq().sub(&z1z1).sub(&z2z2).mul(&h);
        Jac { x: x3, y: y3, z: z3 }
    }

    fn to_affine(&self) -> AffinePoint {
        if self.is_inf() {
            return AffinePoint::Infinity;
        }
        let zi = self.z.inv();
        let zi2 = zi.sq();
        let x = self.x.mul(&zi2);
        let y = self.y.mul(&zi2).mul(&zi);
        AffinePoint::Point { x: x.to_be(), y: y.to_be() }
    }

    /// `k * self` with a 4-bit fixed window; `k` big-endian (any length).
    fn mul_scalar(&self, k: &[u8]) -> Jac {
        let mut table = [Jac::infinity(); 16];
        table[1] = *self;
        for i in 2..16 {
            table[i] = table[i - 1].add(self);
        }
        let mut acc = Jac::infinity();
        for &byte in k {
            for nib in [byte >> 4, byte & 15] {
                acc = acc.double().double().double().double();
                if nib != 0 {
                    acc = acc.add(&table[nib as usize]);
                }
            }
        }
        acc
    }
}

fn generator() -> Jac {
    Jac::from_affine(&Fe::from_be(&GX_BE).unwrap(), &Fe::from_be(&GY_BE).unwrap())
}

fn order() -> BigUint {
    BigUint::from_bytes_be(&ORDER_BE)
}

fn on_curve(x: &Fe, y: &Fe) -> bool {
    // y^2 = x^3 - 3x + b
    let x3 = x.sq().mul(x);
    let three_x = x.add(x).add(x);
    let rhs = x3.sub(&three_x).add(&fe_b());
    y.sq() == rhs
}

fn unsupported_encoding() -> CryptoError {
    CryptoError::error("crypto: unsupported EC point encoding")
}

fn not_on_curve() -> CryptoError {
    CryptoError::error("crypto: EC point is not on the curve")
}

/// Decode an SEC1 point: `04|X|Y` (65 bytes), `02/03|X` (33), `06/07|X|Y` hybrid (65).
/// Errors: `crypto: unsupported EC point encoding`, `crypto: EC point is not on the curve`,
/// `crypto: invalid hybrid EC point encoding`.
pub fn decode_point(bytes: &[u8]) -> Result<AffinePoint, CryptoError> {
    match (bytes.first(), bytes.len()) {
        (Some(0x04), 65) | (Some(0x06), 65) | (Some(0x07), 65) => {
            let mut xb = [0u8; 32];
            let mut yb = [0u8; 32];
            xb.copy_from_slice(&bytes[1..33]);
            yb.copy_from_slice(&bytes[33..65]);
            let x = Fe::from_be(&xb).ok_or_else(not_on_curve)?;
            let y = Fe::from_be(&yb).ok_or_else(not_on_curve)?;
            if !on_curve(&x, &y) {
                return Err(not_on_curve());
            }
            if bytes[0] != 0x04 && (yb[31] & 1) != (bytes[0] & 1) {
                return Err(CryptoError::error("crypto: invalid hybrid EC point encoding"));
            }
            Ok(AffinePoint::Point { x: xb, y: yb })
        }
        (Some(0x02), 33) | (Some(0x03), 33) => {
            let mut xb = [0u8; 32];
            xb.copy_from_slice(&bytes[1..33]);
            let x = Fe::from_be(&xb).ok_or_else(not_on_curve)?;
            let rhs = x.sq().mul(&x).sub(&x.add(&x).add(&x)).add(&fe_b());
            let y = rhs.sqrt().ok_or_else(not_on_curve)?;
            let mut yb = y.to_be();
            if (yb[31] & 1) != (bytes[0] & 1) {
                yb = Fe::ZERO.sub(&y).to_be();
            }
            Ok(AffinePoint::Point { x: xb, y: yb })
        }
        _ => Err(unsupported_encoding()),
    }
}

/// Point conversion forms (`'uncompressed'` default, `'compressed'`, `'hybrid'`).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum PointFormat {
    Uncompressed,
    Compressed,
    Hybrid,
}

impl PointFormat {
    /// `undefined`/`null` → uncompressed is the binding's job; unknown names → TypeError
    /// `Invalid EC point conversion form '<name>'` (see [`invalid_point_format_error`]).
    pub fn from_name(name: &str) -> Option<PointFormat> {
        match name {
            "uncompressed" => Some(PointFormat::Uncompressed),
            "compressed" => Some(PointFormat::Compressed),
            "hybrid" => Some(PointFormat::Hybrid),
            _ => None,
        }
    }
}

pub fn invalid_point_format_error(name: &str) -> CryptoError {
    CryptoError::type_error(format!("Invalid EC point conversion form '{}'", name))
}

/// Encode an affine point. Infinity encodes as a single `0x00` byte.
pub fn encode_point(p: &AffinePoint, format: PointFormat) -> Vec<u8> {
    match p {
        AffinePoint::Infinity => vec![0],
        AffinePoint::Point { x, y } => {
            let odd = y[31] & 1;
            match format {
                PointFormat::Uncompressed => [&[0x04u8][..], x, y].concat(),
                PointFormat::Compressed => [&[0x02u8 | odd][..], x].concat(),
                PointFormat::Hybrid => [&[0x06u8 | odd][..], x, y].concat(),
            }
        }
    }
}

fn jac_from(p: &AffinePoint) -> Jac {
    match p {
        AffinePoint::Infinity => Jac::infinity(),
        AffinePoint::Point { x, y } => Jac::from_affine(&Fe::from_be(x).unwrap(), &Fe::from_be(y).unwrap()),
    }
}

/// `k * P` for an arbitrary big-endian scalar.
pub fn scalar_mul(p: &AffinePoint, k: &[u8]) -> AffinePoint {
    jac_from(p).mul_scalar(k).to_affine()
}

/// `k * G`.
pub fn scalar_mul_base(k: &[u8]) -> AffinePoint {
    generator().mul_scalar(k).to_affine()
}

/// `true` if `1 <= d < n` (big-endian, any length).
pub fn is_valid_private_scalar(d: &[u8]) -> bool {
    let v = BigUint::from_bytes_be(d);
    !v.is_zero() && v < order()
}

/// Public point (uncompressed encoding) for a private scalar. Errors with RangeError
/// `Private key is not valid for specified curve` unless `1 <= d < n`.
pub fn public_from_private(d: &[u8]) -> Result<Vec<u8>, CryptoError> {
    if !is_valid_private_scalar(d) {
        return Err(CryptoError::range_error("Private key is not valid for specified curve"));
    }
    Ok(encode_point(&scalar_mul_base(d), PointFormat::Uncompressed))
}

/// New key pair `(d (32 bytes), uncompressed public point)`. Like the original:
/// `d = random32 mod n`, retried while zero.
pub fn generate_keypair() -> ([u8; 32], Vec<u8>) {
    let n = order();
    loop {
        let r = super::random::random_bytes(32);
        let d = BigUint::from_bytes_be(&r).rem(&n);
        if d.is_zero() {
            continue;
        }
        let mut db = [0u8; 32];
        db.copy_from_slice(&d.to_bytes_be_padded(32));
        let public = encode_point(&scalar_mul_base(&db), PointFormat::Uncompressed);
        return (db, public);
    }
}

/// ECDH: x-coordinate (32 bytes) of `d * Q`, where `Q` is an encoded peer point.
/// Errors: point decoding errors, `Failed to compute ECDH key` if the result is infinity.
pub fn ecdh(d: &[u8], peer_point: &[u8]) -> Result<[u8; 32], CryptoError> {
    let q = decode_point(peer_point)?;
    match scalar_mul(&q, d) {
        AffinePoint::Point { x, .. } => Ok(x),
        AffinePoint::Infinity => Err(CryptoError::error("Failed to compute ECDH key")),
    }
}

fn bits2int(hash: &[u8]) -> BigUint {
    // Leftmost 256 bits of the hash.
    if hash.len() > 32 {
        BigUint::from_bytes_be(&hash[..32])
    } else {
        BigUint::from_bytes_be(hash)
    }
}

/// ECDSA signature as `(r, s)` (32-byte big-endian each) over an already-computed hash.
/// Uses a random nonce (signatures are not deterministic, like the original).
pub fn ecdsa_sign_prehashed(d: &[u8], hash: &[u8]) -> Result<([u8; 32], [u8; 32]), CryptoError> {
    let n = order();
    let dv = BigUint::from_bytes_be(d);
    if dv.is_zero() || dv >= n {
        return Err(CryptoError::range_error("Private key is not valid for specified curve"));
    }
    let e = bits2int(hash).rem(&n);
    loop {
        let k = BigUint::random_range(&BigUint::one(), &n);
        let kb = k.to_bytes_be_padded(32);
        let x = match scalar_mul_base(&kb) {
            AffinePoint::Point { x, .. } => x,
            AffinePoint::Infinity => continue,
        };
        let r = BigUint::from_bytes_be(&x).rem(&n);
        if r.is_zero() {
            continue;
        }
        let kinv = match k.modinv(&n) {
            Some(v) => v,
            None => continue,
        };
        let s = kinv.mul(&e.add(&r.mul(&dv))).rem(&n);
        if s.is_zero() {
            continue;
        }
        let mut rb = [0u8; 32];
        let mut sb = [0u8; 32];
        rb.copy_from_slice(&r.to_bytes_be_padded(32));
        sb.copy_from_slice(&s.to_bytes_be_padded(32));
        return Ok((rb, sb));
    }
}

/// Verify `(r, s)` against an already-computed hash and an encoded public point.
pub fn ecdsa_verify_prehashed(point: &[u8], hash: &[u8], r: &[u8], s: &[u8]) -> bool {
    let q = match decode_point(point) {
        Ok(AffinePoint::Point { x, y }) => AffinePoint::Point { x, y },
        _ => return false,
    };
    let n = order();
    let r = BigUint::from_bytes_be(r);
    let s = BigUint::from_bytes_be(s);
    if r.is_zero() || s.is_zero() || r >= n || s >= n {
        return false;
    }
    let e = bits2int(hash).rem(&n);
    let w = match s.modinv(&n) {
        Some(w) => w,
        None => return false,
    };
    let u1 = e.mul(&w).rem(&n).to_bytes_be_padded(32);
    let u2 = r.mul(&w).rem(&n).to_bytes_be_padded(32);
    let x = generator().mul_scalar(&u1).add(&jac_from(&q).mul_scalar(&u2));
    match x.to_affine() {
        AffinePoint::Infinity => false,
        AffinePoint::Point { x, .. } => BigUint::from_bytes_be(&x).rem(&n) == r,
    }
}

/// DER `ECDSA-Sig-Value ::= SEQUENCE { r INTEGER, s INTEGER }`.
pub fn signature_to_der(r: &[u8], s: &[u8]) -> Vec<u8> {
    super::asn1::sequence(&[&super::asn1::integer_unsigned(r), &super::asn1::integer_unsigned(s)])
}

/// Parse a DER ECDSA signature into 32-byte `(r, s)`; `None` if malformed or out of range.
pub fn signature_from_der(sig: &[u8]) -> Option<([u8; 32], [u8; 32])> {
    let t = super::asn1::read_exact(sig).ok()?;
    if t.tag != super::asn1::TAG_SEQUENCE {
        return None;
    }
    let kids = super::asn1::children(t.content).ok()?;
    if kids.len() != 2 || kids[0].tag != 2 || kids[1].tag != 2 {
        return None;
    }
    let to32 = |c: &[u8]| -> Option<[u8; 32]> {
        let m = super::asn1::integer_magnitude(c);
        if m.len() > 32 {
            return None;
        }
        let mut out = [0u8; 32];
        out[32 - m.len()..].copy_from_slice(m);
        Some(out)
    };
    Some((to32(kids[0].content)?, to32(kids[1].content)?))
}

/// `crypto.sign(alg, data, ecKey)`: hash then sign; `p1363` selects `dsaEncoding:
/// 'ieee-p1363'` (r||s, 64 bytes) instead of DER.
pub fn ecdsa_sign(d: &[u8], alg: HashAlg, msg: &[u8], p1363: bool) -> Result<Vec<u8>, CryptoError> {
    let (r, s) = ecdsa_sign_prehashed(d, &digest(alg, msg))?;
    Ok(if p1363 { [r, s].concat() } else { signature_to_der(&r, &s) })
}

/// `crypto.verify(alg, data, ecKey, sig)`.
pub fn ecdsa_verify(point: &[u8], alg: HashAlg, msg: &[u8], sig: &[u8], p1363: bool) -> bool {
    let (r, s) = if p1363 {
        if sig.len() != 64 {
            return false;
        }
        (sig[..32].to_vec(), sig[32..].to_vec())
    } else {
        match signature_from_der(sig) {
            Some((r, s)) => (r.to_vec(), s.to_vec()),
            None => return false,
        }
    };
    ecdsa_verify_prehashed(point, &digest(alg, msg), &r, &s)
}
