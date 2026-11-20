//! AES block cipher (FIPS 197), 128/192/256-bit keys, table-driven.

const fn xtime(a: u8) -> u8 {
    (a << 1) ^ (if a & 0x80 != 0 { 0x1b } else { 0 })
}

const fn gmul(mut a: u8, mut b: u8) -> u8 {
    let mut p = 0u8;
    while b != 0 {
        if b & 1 != 0 {
            p ^= a;
        }
        a = xtime(a);
        b >>= 1;
    }
    p
}

const fn make_sbox() -> [u8; 256] {
    let mut sbox = [0u8; 256];
    let mut p: u8 = 1;
    let mut q: u8 = 1;
    loop {
        // p *= 3
        p = p ^ (p << 1) ^ (if p & 0x80 != 0 { 0x1b } else { 0 });
        // q /= 3
        q ^= q << 1;
        q ^= q << 2;
        q ^= q << 4;
        if q & 0x80 != 0 {
            q ^= 0x09;
        }
        let x = q ^ q.rotate_left(1) ^ q.rotate_left(2) ^ q.rotate_left(3) ^ q.rotate_left(4);
        sbox[p as usize] = x ^ 0x63;
        if p == 1 {
            break;
        }
    }
    sbox[0] = 0x63;
    sbox
}

const fn make_inv_sbox(s: &[u8; 256]) -> [u8; 256] {
    let mut inv = [0u8; 256];
    let mut i = 0;
    while i < 256 {
        inv[s[i] as usize] = i as u8;
        i += 1;
    }
    inv
}

const SBOX: [u8; 256] = make_sbox();
const INV_SBOX: [u8; 256] = make_inv_sbox(&SBOX);

const fn make_te0() -> [u32; 256] {
    let mut t = [0u32; 256];
    let mut i = 0;
    while i < 256 {
        let s = SBOX[i];
        t[i] = ((gmul(s, 2) as u32) << 24) | ((s as u32) << 16) | ((s as u32) << 8) | (gmul(s, 3) as u32);
        i += 1;
    }
    t
}

const fn make_td0() -> [u32; 256] {
    let mut t = [0u32; 256];
    let mut i = 0;
    while i < 256 {
        let s = INV_SBOX[i];
        t[i] = ((gmul(s, 14) as u32) << 24)
            | ((gmul(s, 9) as u32) << 16)
            | ((gmul(s, 13) as u32) << 8)
            | (gmul(s, 11) as u32);
        i += 1;
    }
    t
}

const fn rot_table(t: &[u32; 256], n: u32) -> [u32; 256] {
    let mut r = [0u32; 256];
    let mut i = 0;
    while i < 256 {
        r[i] = t[i].rotate_right(n);
        i += 1;
    }
    r
}

const TE0: [u32; 256] = make_te0();
const TE1: [u32; 256] = rot_table(&TE0, 8);
const TE2: [u32; 256] = rot_table(&TE0, 16);
const TE3: [u32; 256] = rot_table(&TE0, 24);
const TD0: [u32; 256] = make_td0();
const TD1: [u32; 256] = rot_table(&TD0, 8);
const TD2: [u32; 256] = rot_table(&TD0, 16);
const TD3: [u32; 256] = rot_table(&TD0, 24);

const RCON: [u32; 10] = [
    0x01000000, 0x02000000, 0x04000000, 0x08000000, 0x10000000, 0x20000000, 0x40000000, 0x80000000, 0x1b000000,
    0x36000000,
];

fn sub_word(w: u32) -> u32 {
    ((SBOX[(w >> 24) as usize] as u32) << 24)
        | ((SBOX[((w >> 16) & 0xff) as usize] as u32) << 16)
        | ((SBOX[((w >> 8) & 0xff) as usize] as u32) << 8)
        | (SBOX[(w & 0xff) as usize] as u32)
}

/// An expanded AES key (encryption and decryption schedules).
#[derive(Clone)]
pub struct Aes {
    rounds: usize,
    ek: [u32; 60],
    dk: [u32; 60],
}

impl Aes {
    /// `key` must be 16, 24 or 32 bytes; returns `None` otherwise.
    pub fn new(key: &[u8]) -> Option<Aes> {
        let nk = match key.len() {
            16 => 4,
            24 => 6,
            32 => 8,
            _ => return None,
        };
        let rounds = nk + 6;
        let total = 4 * (rounds + 1);
        let mut ek = [0u32; 60];
        for i in 0..nk {
            ek[i] = u32::from_be_bytes([key[4 * i], key[4 * i + 1], key[4 * i + 2], key[4 * i + 3]]);
        }
        for i in nk..total {
            let mut temp = ek[i - 1];
            if i % nk == 0 {
                temp = sub_word(temp.rotate_left(8)) ^ RCON[i / nk - 1];
            } else if nk > 6 && i % nk == 4 {
                temp = sub_word(temp);
            }
            ek[i] = ek[i - nk] ^ temp;
        }
        // Equivalent inverse cipher key schedule.
        let mut dk = [0u32; 60];
        for r in 0..=rounds {
            for j in 0..4 {
                let w = ek[4 * (rounds - r) + j];
                dk[4 * r + j] = if r == 0 || r == rounds {
                    w
                } else {
                    TD0[SBOX[(w >> 24) as usize] as usize]
                        ^ TD1[SBOX[((w >> 16) & 0xff) as usize] as usize]
                        ^ TD2[SBOX[((w >> 8) & 0xff) as usize] as usize]
                        ^ TD3[SBOX[(w & 0xff) as usize] as usize]
                };
            }
        }
        Some(Aes { rounds, ek, dk })
    }

    pub fn key_len(&self) -> usize {
        (self.rounds - 6) * 4
    }

    #[inline]
    pub fn encrypt_block(&self, block: &mut [u8; 16]) {
        let rk = &self.ek;
        let mut s0 = u32::from_be_bytes([block[0], block[1], block[2], block[3]]) ^ rk[0];
        let mut s1 = u32::from_be_bytes([block[4], block[5], block[6], block[7]]) ^ rk[1];
        let mut s2 = u32::from_be_bytes([block[8], block[9], block[10], block[11]]) ^ rk[2];
        let mut s3 = u32::from_be_bytes([block[12], block[13], block[14], block[15]]) ^ rk[3];
        for r in 1..self.rounds {
            let k = 4 * r;
            let t0 = TE0[(s0 >> 24) as usize]
                ^ TE1[((s1 >> 16) & 0xff) as usize]
                ^ TE2[((s2 >> 8) & 0xff) as usize]
                ^ TE3[(s3 & 0xff) as usize]
                ^ rk[k];
            let t1 = TE0[(s1 >> 24) as usize]
                ^ TE1[((s2 >> 16) & 0xff) as usize]
                ^ TE2[((s3 >> 8) & 0xff) as usize]
                ^ TE3[(s0 & 0xff) as usize]
                ^ rk[k + 1];
            let t2 = TE0[(s2 >> 24) as usize]
                ^ TE1[((s3 >> 16) & 0xff) as usize]
                ^ TE2[((s0 >> 8) & 0xff) as usize]
                ^ TE3[(s1 & 0xff) as usize]
                ^ rk[k + 2];
            let t3 = TE0[(s3 >> 24) as usize]
                ^ TE1[((s0 >> 16) & 0xff) as usize]
                ^ TE2[((s1 >> 8) & 0xff) as usize]
                ^ TE3[(s2 & 0xff) as usize]
                ^ rk[k + 3];
            s0 = t0;
            s1 = t1;
            s2 = t2;
            s3 = t3;
        }
        let k = 4 * self.rounds;
        let sb = |x: u32| SBOX[x as usize] as u32;
        let o0 = (sb(s0 >> 24) << 24) ^ (sb((s1 >> 16) & 0xff) << 16) ^ (sb((s2 >> 8) & 0xff) << 8) ^ sb(s3 & 0xff) ^ rk[k];
        let o1 = (sb(s1 >> 24) << 24) ^ (sb((s2 >> 16) & 0xff) << 16) ^ (sb((s3 >> 8) & 0xff) << 8) ^ sb(s0 & 0xff) ^ rk[k + 1];
        let o2 = (sb(s2 >> 24) << 24) ^ (sb((s3 >> 16) & 0xff) << 16) ^ (sb((s0 >> 8) & 0xff) << 8) ^ sb(s1 & 0xff) ^ rk[k + 2];
        let o3 = (sb(s3 >> 24) << 24) ^ (sb((s0 >> 16) & 0xff) << 16) ^ (sb((s1 >> 8) & 0xff) << 8) ^ sb(s2 & 0xff) ^ rk[k + 3];
        block[0..4].copy_from_slice(&o0.to_be_bytes());
        block[4..8].copy_from_slice(&o1.to_be_bytes());
        block[8..12].copy_from_slice(&o2.to_be_bytes());
        block[12..16].copy_from_slice(&o3.to_be_bytes());
    }

    #[inline]
    pub fn decrypt_block(&self, block: &mut [u8; 16]) {
        let rk = &self.dk;
        let mut s0 = u32::from_be_bytes([block[0], block[1], block[2], block[3]]) ^ rk[0];
        let mut s1 = u32::from_be_bytes([block[4], block[5], block[6], block[7]]) ^ rk[1];
        let mut s2 = u32::from_be_bytes([block[8], block[9], block[10], block[11]]) ^ rk[2];
        let mut s3 = u32::from_be_bytes([block[12], block[13], block[14], block[15]]) ^ rk[3];
        for r in 1..self.rounds {
            let k = 4 * r;
            let t0 = TD0[(s0 >> 24) as usize]
                ^ TD1[((s3 >> 16) & 0xff) as usize]
                ^ TD2[((s2 >> 8) & 0xff) as usize]
                ^ TD3[(s1 & 0xff) as usize]
                ^ rk[k];
            let t1 = TD0[(s1 >> 24) as usize]
                ^ TD1[((s0 >> 16) & 0xff) as usize]
                ^ TD2[((s3 >> 8) & 0xff) as usize]
                ^ TD3[(s2 & 0xff) as usize]
                ^ rk[k + 1];
            let t2 = TD0[(s2 >> 24) as usize]
                ^ TD1[((s1 >> 16) & 0xff) as usize]
                ^ TD2[((s0 >> 8) & 0xff) as usize]
                ^ TD3[(s3 & 0xff) as usize]
                ^ rk[k + 2];
            let t3 = TD0[(s3 >> 24) as usize]
                ^ TD1[((s2 >> 16) & 0xff) as usize]
                ^ TD2[((s1 >> 8) & 0xff) as usize]
                ^ TD3[(s0 & 0xff) as usize]
                ^ rk[k + 3];
            s0 = t0;
            s1 = t1;
            s2 = t2;
            s3 = t3;
        }
        let k = 4 * self.rounds;
        let ib = |x: u32| INV_SBOX[x as usize] as u32;
        let o0 = (ib(s0 >> 24) << 24) ^ (ib((s3 >> 16) & 0xff) << 16) ^ (ib((s2 >> 8) & 0xff) << 8) ^ ib(s1 & 0xff) ^ rk[k];
        let o1 = (ib(s1 >> 24) << 24) ^ (ib((s0 >> 16) & 0xff) << 16) ^ (ib((s3 >> 8) & 0xff) << 8) ^ ib(s2 & 0xff) ^ rk[k + 1];
        let o2 = (ib(s2 >> 24) << 24) ^ (ib((s1 >> 16) & 0xff) << 16) ^ (ib((s0 >> 8) & 0xff) << 8) ^ ib(s3 & 0xff) ^ rk[k + 2];
        let o3 = (ib(s3 >> 24) << 24) ^ (ib((s2 >> 16) & 0xff) << 16) ^ (ib((s1 >> 8) & 0xff) << 8) ^ ib(s0 & 0xff) ^ rk[k + 3];
        block[0..4].copy_from_slice(&o0.to_be_bytes());
        block[4..8].copy_from_slice(&o1.to_be_bytes());
        block[8..12].copy_from_slice(&o2.to_be_bytes());
        block[12..16].copy_from_slice(&o3.to_be_bytes());
    }
}
