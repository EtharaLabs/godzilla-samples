//! Ed25519 (RFC 8032) and X25519 (RFC 7748).

use super::bigint::BigUint;
use super::hash::{HashAlg, Hasher};

const MASK: u64 = (1u64 << 51) - 1;

#[derive(Clone, Copy, Debug)]
struct F([u64; 5]);

fn load8(b: &[u8]) -> u64 {
    let mut w = [0u8; 8];
    w.copy_from_slice(&b[..8]);
    u64::from_le_bytes(w)
}

impl F {
    const ZERO: F = F([0; 5]);
    const ONE: F = F([1, 0, 0, 0, 0]);

    fn from_bytes(b: &[u8; 32]) -> F {
        F([
            load8(&b[0..8]) & MASK,
            (load8(&b[6..14]) >> 3) & MASK,
            (load8(&b[12..20]) >> 6) & MASK,
            (load8(&b[19..27]) >> 1) & MASK,
            (load8(&b[24..32]) >> 12) & MASK,
        ])
    }

    fn carry(mut t: [u64; 5]) -> F {
        let mut c;
        c = t[0] >> 51;
        t[0] &= MASK;
        t[1] += c;
        c = t[1] >> 51;
        t[1] &= MASK;
        t[2] += c;
        c = t[2] >> 51;
        t[2] &= MASK;
        t[3] += c;
        c = t[3] >> 51;
        t[3] &= MASK;
        t[4] += c;
        c = t[4] >> 51;
        t[4] &= MASK;
        t[0] += c * 19;
        c = t[0] >> 51;
        t[0] &= MASK;
        t[1] += c;
        F(t)
    }

    fn to_bytes(&self) -> [u8; 32] {
        let mut t = F::carry(F::carry(self.0).0).0;
        // Now t < 2^255 + small; subtract p if t >= p.
        let mut q = (t[0] + 19) >> 51;
        q = (t[1] + q) >> 51;
        q = (t[2] + q) >> 51;
        q = (t[3] + q) >> 51;
        q = (t[4] + q) >> 51;
        t[0] += 19 * q;
        let mut c = t[0] >> 51;
        t[0] &= MASK;
        t[1] += c;
        c = t[1] >> 51;
        t[1] &= MASK;
        t[2] += c;
        c = t[2] >> 51;
        t[2] &= MASK;
        t[3] += c;
        c = t[3] >> 51;
        t[3] &= MASK;
        t[4] += c;
        t[4] &= MASK;
        let mut out = [0u8; 32];
        let words = [
            t[0] | (t[1] << 51),
            (t[1] >> 13) | (t[2] << 38),
            (t[2] >> 26) | (t[3] << 25),
            (t[3] >> 39) | (t[4] << 12),
        ];
        for (i, w) in words.iter().enumerate() {
            out[i * 8..i * 8 + 8].copy_from_slice(&w.to_le_bytes());
        }
        out
    }

    fn add(&self, o: &F) -> F {
        let a = self.0;
        let b = o.0;
        F::carry([a[0] + b[0], a[1] + b[1], a[2] + b[2], a[3] + b[3], a[4] + b[4]])
    }

    fn sub(&self, o: &F) -> F {
        // a + 4p - b
        let a = self.0;
        let b = o.0;
        F::carry([
            a[0] + 0x1fffffffffffb4 - b[0],
            a[1] + 0x1ffffffffffffc - b[1],
            a[2] + 0x1ffffffffffffc - b[2],
            a[3] + 0x1ffffffffffffc - b[3],
            a[4] + 0x1ffffffffffffc - b[4],
        ])
    }

    fn neg(&self) -> F {
        F::ZERO.sub(self)
    }

    fn mul(&self, o: &F) -> F {
        let a = self.0.map(|x| x as u128);
        let b = o.0.map(|x| x as u128);
        let b1 = b[1] * 19;
        let b2 = b[2] * 19;
        let b3 = b[3] * 19;
        let b4 = b[4] * 19;
        let r0 = a[0] * b[0] + a[1] * b4 + a[2] * b3 + a[3] * b2 + a[4] * b1;
        let r1 = a[0] * b[1] + a[1] * b[0] + a[2] * b4 + a[3] * b3 + a[4] * b2;
        let r2 = a[0] * b[2] + a[1] * b[1] + a[2] * b[0] + a[3] * b4 + a[4] * b3;
        let r3 = a[0] * b[3] + a[1] * b[2] + a[2] * b[1] + a[3] * b[0] + a[4] * b4;
        let r4 = a[0] * b[4] + a[1] * b[3] + a[2] * b[2] + a[3] * b[1] + a[4] * b[0];
        let m = MASK as u128;
        let mut c;
        let mut t = [0u64; 5];
        c = r0 >> 51;
        t[0] = (r0 & m) as u64;
        let r1 = r1 + c;
        c = r1 >> 51;
        t[1] = (r1 & m) as u64;
        let r2 = r2 + c;
        c = r2 >> 51;
        t[2] = (r2 & m) as u64;
        let r3 = r3 + c;
        c = r3 >> 51;
        t[3] = (r3 & m) as u64;
        let r4 = r4 + c;
        c = r4 >> 51;
        t[4] = (r4 & m) as u64;
        let t0 = t[0] as u128 + c * 19;
        t[0] = (t0 & m) as u64;
        t[1] += (t0 >> 51) as u64;
        F(t)
    }

    fn sq(&self) -> F {
        self.mul(self)
    }

    fn mul_small(&self, k: u64) -> F {
        let a = self.0.map(|x| x as u128);
        let k = k as u128;
        let m = MASK as u128;
        let mut t = [0u64; 5];
        let mut c: u128 = 0;
        for i in 0..5 {
            let v = a[i] * k + c;
            t[i] = (v & m) as u64;
            c = v >> 51;
        }
        let t0 = t[0] as u128 + c * 19;
        t[0] = (t0 & m) as u64;
        t[1] += (t0 >> 51) as u64;
        F(t)
    }

    /// `self^e` with `e` given as little-endian bytes.
    fn pow_le(&self, e: &[u8; 32]) -> F {
        let mut r = F::ONE;
        for i in (0..256).rev() {
            r = r.sq();
            if (e[i / 8] >> (i % 8)) & 1 == 1 {
                r = r.mul(self);
            }
        }
        r
    }

    fn invert(&self) -> F {
        // p - 2 = 2^255 - 21
        let mut e = [0xffu8; 32];
        e[0] = 0xeb;
        e[31] = 0x7f;
        self.pow_le(&e)
    }

    fn eq(&self, o: &F) -> bool {
        self.to_bytes() == o.to_bytes()
    }

    fn is_zero(&self) -> bool {
        self.to_bytes() == [0u8; 32]
    }

    fn is_negative(&self) -> bool {
        self.to_bytes()[0] & 1 == 1
    }
}

fn fe_from_hex_le(be_hex: &str) -> F {
    let v = BigUint::from_hex(be_hex).unwrap();
    let mut b = [0u8; 32];
    b.copy_from_slice(&v.to_bytes_le_padded(32));
    F::from_bytes(&b)
}

fn ed_d() -> F {
    fe_from_hex_le("52036cee2b6ffe738cc740797779e89800700a4d4141d8ab75eb4dca135978a3")
}

fn sqrt_m1() -> F {
    fe_from_hex_le("2b8324804fc1df0b2b4d00993dfbd7a72f431806ad2fe478c4ee1b274a0ea0b0")
}

/// Extended twisted Edwards coordinates.
#[derive(Clone, Copy, Debug)]
struct Ep {
    x: F,
    y: F,
    z: F,
    t: F,
}

impl Ep {
    fn identity() -> Ep {
        Ep { x: F::ZERO, y: F::ONE, z: F::ONE, t: F::ZERO }
    }

    fn add(&self, q: &Ep) -> Ep {
        let d2 = ed_d().add(&ed_d());
        let a = self.y.sub(&self.x).mul(&q.y.sub(&q.x));
        let b = self.y.add(&self.x).mul(&q.y.add(&q.x));
        let c = self.t.mul(&d2).mul(&q.t);
        let dd = self.z.add(&self.z).mul(&q.z);
        let e = b.sub(&a);
        let f = dd.sub(&c);
        let g = dd.add(&c);
        let h = b.add(&a);
        Ep { x: e.mul(&f), y: g.mul(&h), z: f.mul(&g), t: e.mul(&h) }
    }

    fn double(&self) -> Ep {
        // dbl-2008-hwcd with a = -1
        let a = self.x.sq();
        let b = self.y.sq();
        let c = self.z.sq().add(&self.z.sq());
        let h = a.add(&b);
        let e = h.sub(&self.x.add(&self.y).sq());
        let g = a.sub(&b);
        let f = c.add(&g);
        Ep { x: e.mul(&f), y: g.mul(&h), z: f.mul(&g), t: e.mul(&h) }
    }

    /// `k * self` with `k` little-endian.
    fn mul_scalar_le(&self, k: &[u8]) -> Ep {
        let mut table = [Ep::identity(); 16];
        table[1] = *self;
        for i in 2..16 {
            table[i] = table[i - 1].add(self);
        }
        let mut acc = Ep::identity();
        for i in (0..k.len()).rev() {
            for nib in [k[i] >> 4, k[i] & 15] {
                acc = acc.double().double().double().double();
                if nib != 0 {
                    acc = acc.add(&table[nib as usize]);
                }
            }
        }
        acc
    }

    fn compress(&self) -> [u8; 32] {
        let zi = self.z.invert();
        let x = self.x.mul(&zi);
        let y = self.y.mul(&zi);
        let mut out = y.to_bytes();
        if x.is_negative() {
            out[31] |= 0x80;
        }
        out
    }

    fn decompress(b: &[u8; 32]) -> Option<Ep> {
        let sign = b[31] >> 7;
        let mut yb = *b;
        yb[31] &= 0x7f;
        // Reject non-canonical y (>= p).
        let y = F::from_bytes(&yb);
        if y.to_bytes() != yb {
            return None;
        }
        let y2 = y.sq();
        let u = y2.sub(&F::ONE);
        let v = ed_d().mul(&y2).add(&F::ONE);
        let x2 = u.mul(&v.invert());
        if x2.is_zero() {
            if sign == 1 {
                return None;
            }
            return Some(Ep { x: F::ZERO, y, z: F::ONE, t: F::ZERO });
        }
        // x = x2^((p+3)/8), (p+3)/8 = 2^252 - 2
        let mut e = [0xffu8; 32];
        e[0] = 0xfe;
        e[31] = 0x0f;
        let mut x = x2.pow_le(&e);
        if !x.sq().eq(&x2) {
            x = x.mul(&sqrt_m1());
        }
        if !x.sq().eq(&x2) {
            return None;
        }
        if (x.is_negative() as u8) != sign {
            x = x.neg();
        }
        Some(Ep { x, y, z: F::ONE, t: x.mul(&y) })
    }

    fn eq(&self, o: &Ep) -> bool {
        // X1*Z2 == X2*Z1 && Y1*Z2 == Y2*Z1
        self.x.mul(&o.z).eq(&o.x.mul(&self.z)) && self.y.mul(&o.z).eq(&o.y.mul(&self.z))
    }
}

fn base_point() -> Ep {
    let mut b = [0x66u8; 32];
    b[0] = 0x58;
    Ep::decompress(&b).expect("base point")
}

fn order_l() -> BigUint {
    BigUint::from_hex("1000000000000000000000000000000014def9dea2f79cd65812631a5cf5d3ed").unwrap()
}

fn sha512_parts(parts: &[&[u8]]) -> Vec<u8> {
    let mut h = Hasher::new(HashAlg::Sha512);
    for p in parts {
        h.update(p);
    }
    h.finalize()
}

fn reduce_mod_l(bytes_le: &[u8]) -> BigUint {
    BigUint::from_bytes_le(bytes_le).rem(&order_l())
}

fn expand_secret(seed: &[u8; 32]) -> ([u8; 32], Vec<u8>) {
    let h = sha512_parts(&[seed]);
    let mut a = [0u8; 32];
    a.copy_from_slice(&h[..32]);
    a[0] &= 248;
    a[31] &= 127;
    a[31] |= 64;
    (a, h[32..].to_vec())
}

/// Ed25519 public key for a 32-byte private seed.
pub fn ed25519_public_key(seed: &[u8; 32]) -> [u8; 32] {
    let (a, _) = expand_secret(seed);
    base_point().mul_scalar_le(&a).compress()
}

/// Ed25519 signature (deterministic, 64 bytes).
pub fn ed25519_sign(seed: &[u8; 32], msg: &[u8]) -> [u8; 64] {
    let (a, prefix) = expand_secret(seed);
    let b = base_point();
    let pk = b.mul_scalar_le(&a).compress();
    let r = reduce_mod_l(&sha512_parts(&[&prefix, msg]));
    let rb = r.to_bytes_le_padded(32);
    let big_r = b.mul_scalar_le(&rb).compress();
    let k = reduce_mod_l(&sha512_parts(&[&big_r, &pk, msg]));
    let s = r.add(&k.mul(&BigUint::from_bytes_le(&a))).rem(&order_l());
    let mut sig = [0u8; 64];
    sig[..32].copy_from_slice(&big_r);
    sig[32..].copy_from_slice(&s.to_bytes_le_padded(32));
    sig
}

/// Ed25519 verification (cofactorless, `[s]B == R + [k]A`, rejects `s >= L` and
/// non-canonical / undecodable points).
pub fn ed25519_verify(public: &[u8], msg: &[u8], sig: &[u8]) -> bool {
    if public.len() != 32 || sig.len() != 64 {
        return false;
    }
    let mut pk = [0u8; 32];
    pk.copy_from_slice(public);
    let a = match Ep::decompress(&pk) {
        Some(a) => a,
        None => return false,
    };
    let mut rb = [0u8; 32];
    rb.copy_from_slice(&sig[..32]);
    let r = match Ep::decompress(&rb) {
        Some(r) => r,
        None => return false,
    };
    let s = BigUint::from_bytes_le(&sig[32..]);
    if s >= order_l() {
        return false;
    }
    let k = reduce_mod_l(&sha512_parts(&[&rb, &pk, msg]));
    let sb = base_point().mul_scalar_le(&sig[32..]);
    let ka = a.mul_scalar_le(&k.to_bytes_le_padded(32));
    sb.eq(&r.add(&ka))
}

/// X25519 scalar multiplication (RFC 7748): clamps `k`, masks the top bit of `u`.
pub fn x25519(k: &[u8; 32], u: &[u8; 32]) -> [u8; 32] {
    let mut kk = *k;
    kk[0] &= 248;
    kk[31] &= 127;
    kk[31] |= 64;
    let mut ub = *u;
    ub[31] &= 0x7f;
    let x1 = F::from_bytes(&ub);
    let mut x2 = F::ONE;
    let mut z2 = F::ZERO;
    let mut x3 = x1;
    let mut z3 = F::ONE;
    let mut swap = 0u8;
    for t in (0..255).rev() {
        let kt = (kk[t / 8] >> (t % 8)) & 1;
        swap ^= kt;
        if swap == 1 {
            std::mem::swap(&mut x2, &mut x3);
            std::mem::swap(&mut z2, &mut z3);
        }
        swap = kt;
        let a = x2.add(&z2);
        let aa = a.sq();
        let b = x2.sub(&z2);
        let bb = b.sq();
        let e = aa.sub(&bb);
        let c = x3.add(&z3);
        let d = x3.sub(&z3);
        let da = d.mul(&a);
        let cb = c.mul(&b);
        x3 = da.add(&cb).sq();
        z3 = x1.mul(&da.sub(&cb).sq());
        x2 = aa.mul(&bb);
        z2 = e.mul(&aa.add(&e.mul_small(121665)));
    }
    if swap == 1 {
        std::mem::swap(&mut x2, &mut x3);
        std::mem::swap(&mut z2, &mut z3);
    }
    x2.mul(&z2.invert()).to_bytes()
}

/// X25519 public key: `x25519(k, 9)`.
pub fn x25519_public_key(k: &[u8; 32]) -> [u8; 32] {
    let mut nine = [0u8; 32];
    nine[0] = 9;
    x25519(k, &nine)
}
