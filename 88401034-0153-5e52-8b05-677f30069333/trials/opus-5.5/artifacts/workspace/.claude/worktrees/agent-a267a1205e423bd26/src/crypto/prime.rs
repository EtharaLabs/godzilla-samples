//! Primality testing (Miller–Rabin) and random prime generation
//! (`crypto.checkPrime[Sync]`, `crypto.generatePrime[Sync]`, RSA/DH key generation).

use super::bigint::{BigUint, Montgomery};

/// Odd primes below 2000 used for trial division.
fn small_primes() -> &'static [u32] {
    use std::sync::OnceLock;
    static P: OnceLock<Vec<u32>> = OnceLock::new();
    P.get_or_init(|| {
        let limit = 2000usize;
        let mut sieve = vec![true; limit];
        let mut out = Vec::new();
        for i in 2..limit {
            if sieve[i] {
                if i > 2 {
                    out.push(i as u32);
                }
                let mut j = i * i;
                while j < limit {
                    sieve[j] = false;
                    j += i;
                }
            }
        }
        out
    })
}

/// Number of Miller–Rabin rounds used for randomly generated candidates (as OpenSSL 1.1's
/// `BN_prime_checks_for_size`; error probability < 2^-80 for random inputs).
pub fn mr_rounds_for_bits(bits: usize) -> usize {
    match bits {
        b if b >= 3747 => 3,
        b if b >= 1345 => 4,
        b if b >= 476 => 5,
        b if b >= 400 => 6,
        b if b >= 347 => 7,
        b if b >= 308 => 8,
        b if b >= 55 => 27,
        _ => 34,
    }
}

/// Trial division; returns `Some(is_prime)` when decided, `None` when inconclusive.
fn trial_division(n: &BigUint) -> Option<bool> {
    if let Some(v) = n.to_u64() {
        if v < 2 {
            return Some(false);
        }
        if v < 4 {
            return Some(true);
        }
        if v % 2 == 0 {
            return Some(false);
        }
        for &p in small_primes() {
            let p = p as u64;
            if p * p > v {
                return Some(true);
            }
            if v % p == 0 {
                return Some(v == p);
            }
        }
        return None;
    }
    if n.is_even() {
        return Some(false);
    }
    for &p in small_primes() {
        if n.rem_u64(p as u64) == 0 {
            return Some(false);
        }
    }
    None
}

fn miller_rabin(n: &BigUint, rounds: usize, use_base2: bool) -> bool {
    let one = BigUint::one();
    let n_minus_1 = n.sub(&one);
    let mut s = 0usize;
    while !n_minus_1.bit(s) {
        s += 1;
    }
    let d = n_minus_1.shr(s);
    let mont = Montgomery::new(n);
    let two = BigUint::from_u64(2);
    let n_minus_3 = n.sub_u64(3);
    for round in 0..rounds {
        let a = if round == 0 && use_base2 {
            two.clone()
        } else {
            // a in [2, n-2]
            two.add(&BigUint::random_below(&n_minus_3))
        };
        let mut x = mont.pow(&a, &d);
        if x.is_one() || x == n_minus_1 {
            continue;
        }
        let mut composite = true;
        for _ in 1..s {
            x = x.mul(&x).rem(n);
            if x == n_minus_1 {
                composite = false;
                break;
            }
            if x.is_one() {
                break;
            }
        }
        if composite {
            return false;
        }
    }
    true
}

/// Probabilistic primality test with `checks` Miller–Rabin rounds (random bases) after trial
/// division. `crypto.checkPrime` uses `checks = options.checks || 40`. Values < 2 are not prime.
pub fn is_probable_prime(n: &BigUint, checks: usize) -> bool {
    if let Some(r) = trial_division(n) {
        return r;
    }
    miller_rabin(n, checks.max(1), false)
}

/// Faster test for random candidates (base-2 round first, size-based round count).
fn is_prime_candidate(n: &BigUint) -> bool {
    if let Some(r) = trial_division(n) {
        return r;
    }
    miller_rabin(n, mr_rounds_for_bits(n.bits()), true)
}

/// Random `bits`-bit number with the two top bits set (bit `bits-1` and `bits-2`) and the low
/// bit set — the candidate shape the original uses (for `bits == 2` this is always 3).
fn random_candidate(bits: usize) -> BigUint {
    let bytes = bits.div_ceil(8);
    let mut buf = vec![0u8; bytes];
    super::random::fill_random(&mut buf);
    let excess = bytes * 8 - bits;
    buf[0] &= 0xffu8 >> excess;
    let mut v = BigUint::from_bytes_be(&buf);
    v.set_bit(bits - 1);
    if bits >= 2 {
        v.set_bit(bits - 2);
    }
    v.set_bit(0);
    v
}

/// Random prime of exactly `bits` bits (`bits >= 2`, the JS layer rejects smaller sizes with
/// RangeError `prime size must be an integer >= 2 bits`). Candidates have their two top bits
/// set (so e.g. 4-bit primes are always 13). `safe` additionally requires `(p-1)/2` prime.
/// With `add`, candidates satisfy `p % add == rem` (`rem` defaults are the binding's job:
/// `3` when `safe`, else `1`). Like the original this loops until it finds a prime — there
/// are parameter combinations with no solution (e.g. 4-bit safe primes), which never return.
pub fn generate_prime(bits: usize, safe: bool, add: Option<&BigUint>, rem: Option<&BigUint>) -> BigUint {
    // The binding rejects bits < 2 and add <= 0; be defensive anyway (never panic).
    let bits = bits.max(2);
    let add = add.filter(|a| !a.is_zero());
    if safe && add.is_none() && bits >= 64 {
        return generate_safe_prime_sieved(bits);
    }
    loop {
        let mut c = random_candidate(bits);
        if let Some(add) = add {
            let r = rem.cloned().unwrap_or_else(|| BigUint::from_u64(if safe { 3 } else { 1 }));
            let m = c.rem(add);
            c = c.sub(&m).add(&r);
            if c.bits() != bits {
                continue;
            }
        } else if safe && bits > 2 {
            // (p-1)/2 must be odd for p > 7 → p ≡ 3 (mod 4).
            c.set_bit(1);
        }
        if safe {
            if c.to_u64().is_some_and(|v| v < 5) {
                // 2 and 3 are not safe primes (5 = 2*2+1 is, 7 = 2*3+1 is).
                continue;
            }
            let q = c.shr(1);
            if trial_division_quick(&c) && trial_division_quick(&q) && is_prime_candidate(&q) && is_prime_candidate(&c) {
                return c;
            }
        } else if is_prime_candidate(&c) {
            return c;
        }
    }
}

/// Large safe primes: pick a random `q` (`bits-1` bits, two top bits set, odd) and scan
/// `q, q+2, ...` with a sieve that removes candidates where `q` or `p = 2q+1` has a small
/// factor, then test `q` (Miller–Rabin) and `p` (base-2 Fermat, which together with a prime
/// `q` proves `p` prime by Pocklington, then Miller–Rabin for good measure).
fn generate_safe_prime_sieved(bits: usize) -> BigUint {
    const WINDOW: usize = 1 << 15; // number of odd q candidates per window
    let primes = small_primes();
    let two = BigUint::from_u64(2);
    loop {
        let q0 = random_candidate(bits - 1);
        let mut composite = vec![false; WINDOW];
        for &s in primes {
            let s = s as u64;
            let r = q0.rem_u64(s);
            let inv2 = s.div_ceil(2); // 2^{-1} mod s for odd s
            // q0 + 2i ≡ 0 (mod s)  →  i ≡ -r * inv2
            let i0 = ((s - r) % s) * inv2 % s;
            // 2(q0 + 2i) + 1 ≡ 0  →  q0 + 2i ≡ (s-1)/2  →  i ≡ ((s-1)/2 - r) * inv2
            let target = ((s - 1) / 2 + s - r) % s;
            let i1 = target * inv2 % s;
            for start in [i0, i1] {
                let mut i = start as usize;
                while i < WINDOW {
                    composite[i] = true;
                    i += s as usize;
                }
            }
        }
        for (i, &c) in composite.iter().enumerate() {
            if c {
                continue;
            }
            let q = q0.add_u64(2 * i as u64);
            if q.bits() != bits - 1 {
                break;
            }
            let p = q.shl(1).add_u64(1);
            if !miller_rabin(&q, 1, true) {
                continue;
            }
            // Fermat base 2 on p.
            if !two.modpow(&p.sub_u64(1), &p).is_one() {
                continue;
            }
            if is_prime_candidate(&q) && is_prime_candidate(&p) {
                return p;
            }
        }
    }
}

/// Cheap pre-filter: false if divisible by a small prime other than itself.
fn trial_division_quick(n: &BigUint) -> bool {
    !matches!(trial_division(n), Some(false))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn primality() {
        let p = |v: u64| is_probable_prime(&BigUint::from_u64(v), 20);
        assert!(!p(0) && !p(1) && p(2) && p(3) && !p(4) && p(5) && p(7) && !p(9) && !p(561) && p(7919));
        assert!(p(1_000_000_007) && !p(1_000_000_007u64 * 3));
        let m127 = BigUint::one().shl(127).sub_u64(1);
        assert!(is_probable_prime(&m127, 20));
        let m128 = BigUint::one().shl(128).add_u64(1);
        assert!(!is_probable_prime(&m128, 20));
        // Carmichael number 3215031751 = 151 * 751 * 28351
        assert!(!p(3215031751));
    }

    #[test]
    fn generation() {
        for bits in [2usize, 3, 4, 5, 6, 8, 16, 33, 64, 100, 256] {
            for _ in 0..5 {
                let q = generate_prime(bits, false, None, None);
                assert_eq!(q.bits(), bits);
                assert!(is_probable_prime(&q, 20));
                assert!(q.bit(bits - 1) && (bits < 2 || q.bit(bits - 2)));
            }
        }
        assert_eq!(generate_prime(2, false, None, None).to_u64(), Some(3));
        assert_eq!(generate_prime(3, false, None, None).to_u64(), Some(7));
        assert_eq!(generate_prime(4, false, None, None).to_u64(), Some(13));
        assert_eq!(generate_prime(6, true, None, None).to_u64(), Some(59));
        assert_eq!(generate_prime(7, true, None, None).to_u64(), Some(107));
        for bits in [10usize, 32, 64, 128] {
            let s = generate_prime(bits, true, None, None);
            assert_eq!(s.bits(), bits);
            assert!(is_probable_prime(&s.shr(1), 20));
        }
        let add = BigUint::from_u64(12);
        let rem = BigUint::from_u64(7);
        for _ in 0..5 {
            let q = generate_prime(32, false, Some(&add), Some(&rem));
            assert_eq!(q.rem_u64(12), 7);
        }
    }
}
