//! `createCipheriv` / `createDecipheriv` engine: AES-{128,192,256}-{ECB,CBC,CTR,GCM} with
//! the original runtime's streaming, padding, state and error semantics.

use super::aes::Aes;
use super::{CryptoError, ErrorKind};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CipherMode {
    Ecb,
    Cbc,
    Ctr,
    Gcm,
}

impl CipherMode {
    /// `getCipherInfo().mode` string.
    pub fn as_str(&self) -> &'static str {
        match self {
            CipherMode::Ecb => "ecb",
            CipherMode::Cbc => "cbc",
            CipherMode::Ctr => "ctr",
            CipherMode::Gcm => "gcm",
        }
    }
}

/// One row of the original's cipher table (what `getCipherInfo` reports).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CipherInfo {
    /// Name as listed by `getCiphers()` (e.g. `aes-128-gcm`).
    pub name: &'static str,
    /// `getCipherInfo(..).name` (OpenSSL long name; `id-aes128-gcm` for the GCM ciphers).
    pub info_name: &'static str,
    pub nid: u32,
    pub mode: CipherMode,
    /// Key length in bytes.
    pub key_len: usize,
    /// Default IV length in bytes (`None` for ECB, which has no `ivLength` property).
    pub iv_len: Option<usize>,
    /// `getCipherInfo(..).blockSize`: 16 for ECB/CBC, 1 for CTR/GCM.
    pub block_size: usize,
}

const fn ci(
    name: &'static str,
    info_name: &'static str,
    nid: u32,
    mode: CipherMode,
    key_len: usize,
    iv_len: Option<usize>,
    block_size: usize,
) -> CipherInfo {
    CipherInfo { name, info_name, nid, mode, key_len, iv_len, block_size }
}

/// All supported ciphers, sorted by name (this order is `crypto.getCiphers()`).
pub const CIPHERS: [CipherInfo; 12] = [
    ci("aes-128-cbc", "aes-128-cbc", 419, CipherMode::Cbc, 16, Some(16), 16),
    ci("aes-128-ctr", "aes-128-ctr", 904, CipherMode::Ctr, 16, Some(16), 1),
    ci("aes-128-ecb", "aes-128-ecb", 418, CipherMode::Ecb, 16, None, 16),
    ci("aes-128-gcm", "id-aes128-gcm", 895, CipherMode::Gcm, 16, Some(12), 1),
    ci("aes-192-cbc", "aes-192-cbc", 423, CipherMode::Cbc, 24, Some(16), 16),
    ci("aes-192-ctr", "aes-192-ctr", 905, CipherMode::Ctr, 24, Some(16), 1),
    ci("aes-192-ecb", "aes-192-ecb", 422, CipherMode::Ecb, 24, None, 16),
    ci("aes-192-gcm", "id-aes192-gcm", 898, CipherMode::Gcm, 24, Some(12), 1),
    ci("aes-256-cbc", "aes-256-cbc", 427, CipherMode::Cbc, 32, Some(16), 16),
    ci("aes-256-ctr", "aes-256-ctr", 906, CipherMode::Ctr, 32, Some(16), 1),
    ci("aes-256-ecb", "aes-256-ecb", 426, CipherMode::Ecb, 32, None, 16),
    ci("aes-256-gcm", "id-aes256-gcm", 901, CipherMode::Gcm, 32, Some(12), 1),
];

/// `crypto.getCiphers()`.
pub fn cipher_names() -> Vec<&'static str> {
    CIPHERS.iter().map(|c| c.name).collect()
}

/// Resolve a cipher name: case-insensitive; `aes128`/`aes192`/`aes256` are aliases of the
/// CBC ciphers. Nothing else (`id-aes128-gcm`, `aes-256`, `aes-128-cfb`, ...) is accepted.
pub fn cipher_info(name: &str) -> Option<&'static CipherInfo> {
    let lower = name.to_lowercase();
    let canon = match lower.as_str() {
        "aes128" => "aes-128-cbc",
        "aes192" => "aes-192-cbc",
        "aes256" => "aes-256-cbc",
        other => other,
    };
    CIPHERS.iter().find(|c| c.name == canon)
}

/// `getCipherInfo(nid)` lookup.
pub fn cipher_info_by_nid(nid: u32) -> Option<&'static CipherInfo> {
    CIPHERS.iter().find(|c| c.nid == nid)
}

/// `getCipherInfo(nameOrNid, options)` result: the JS object is built in the key order
/// `mode, name, nid, blockSize, ivLength (omitted when None), keyLength`.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CipherInfoReport {
    pub mode: &'static str,
    pub name: &'static str,
    pub nid: u32,
    pub block_size: usize,
    pub iv_length: Option<f64>,
    pub key_length: usize,
}

/// The original's `getCipherInfo` option filtering for a resolved cipher (resolve with
/// [`cipher_info`] for names or [`cipher_info_by_nid`] for numbers; unknown → undefined).
/// `key_length` / `iv_length` are the numeric option values when present (`!== undefined`):
/// a keyLength different from the table → `None`; ivLength given: ECB → `None`, GCM →
/// echoed if `>= 1` else `None`, CBC/CTR → must be 16 else `None`.
pub fn get_cipher_info(info: &CipherInfo, key_length: Option<f64>, iv_length: Option<f64>) -> Option<CipherInfoReport> {
    let mut r = CipherInfoReport {
        mode: info.mode.as_str(),
        name: info.info_name,
        nid: info.nid,
        block_size: info.block_size,
        iv_length: info.iv_len.map(|v| v as f64),
        key_length: info.key_len,
    };
    if let Some(k) = key_length {
        if k != info.key_len as f64 {
            return None;
        }
    }
    if let Some(iv) = iv_length {
        match info.mode {
            CipherMode::Ecb => return None,
            CipherMode::Gcm => {
                if !(iv >= 1.0) {
                    return None;
                }
                r.iv_length = Some(iv);
            }
            _ => {
                if iv != 16.0 {
                    return None;
                }
            }
        }
    }
    Some(r)
}

/// Tag lengths accepted for GCM (`authTagLength` option / `setAuthTag` without an explicit
/// `authTagLength`).
pub const GCM_TAG_LENGTHS: [usize; 7] = [4, 8, 12, 13, 14, 15, 16];

pub fn unsupported_cipher_error(name: &str) -> CryptoError {
    CryptoError::error(format!(
        "node:crypto cipher '{}' is not supported in lumen (aes-{{128,192,256}}-{{ecb,cbc,ctr,gcm}} only)",
        name
    ))
}

pub fn invalid_key_length_error() -> CryptoError {
    CryptoError::coded(ErrorKind::RangeError, "ERR_CRYPTO_INVALID_KEYLEN", "Invalid key length")
}

pub fn invalid_iv_error() -> CryptoError {
    CryptoError::coded(ErrorKind::TypeError, "ERR_CRYPTO_INVALID_IV", "Invalid initialization vector")
}

/// `Invalid authentication tag length: <len>` (TypeError, `ERR_CRYPTO_INVALID_AUTH_TAG`).
/// `len_text` is the JS `String(value)` of the offending length (e.g. `5`, `3.5`, `null`).
pub fn invalid_auth_tag_error(len_text: &str) -> CryptoError {
    CryptoError::coded(
        ErrorKind::TypeError,
        "ERR_CRYPTO_INVALID_AUTH_TAG",
        format!("Invalid authentication tag length: {}", len_text),
    )
}

fn invalid_state_for(op: &str) -> CryptoError {
    CryptoError::coded(ErrorKind::Error, "ERR_CRYPTO_INVALID_STATE", format!("Invalid state for operation {}", op))
}

fn wrong_final_block_length() -> CryptoError {
    CryptoError::coded(
        ErrorKind::Error,
        "ERR_OSSL_WRONG_FINAL_BLOCK_LENGTH",
        "error:1C80006B:Provider routines::wrong final block length",
    )
}

fn bad_decrypt() -> CryptoError {
    CryptoError::coded(ErrorKind::Error, "ERR_OSSL_BAD_DECRYPT", "error:1C800064:Provider routines::bad decrypt")
}

// ---------------------------------------------------------------------------------------
// GHASH (GF(2^128) multiply with 4-bit tables, Shoup's method).

const fn make_rem4() -> [u128; 16] {
    let mut t = [0u128; 16];
    let mut v = 0;
    while v < 16 {
        let mut z = v as u128;
        let mut i = 0;
        while i < 4 {
            z = (z >> 1) ^ (if z & 1 != 0 { 0xe1u128 << 120 } else { 0 });
            i += 1;
        }
        t[v] = z;
        v += 1;
    }
    t
}

const REM4: [u128; 16] = make_rem4();

#[inline]
fn mulx(v: u128) -> u128 {
    (v >> 1) ^ (if v & 1 != 0 { 0xe1u128 << 120 } else { 0 })
}

#[derive(Clone)]
pub(crate) struct Ghash {
    table: [u128; 16],
    y: u128,
    buf: [u8; 16],
    buf_len: usize,
    aad_len: u64,
    ct_len: u64,
    aad_done: bool,
}

impl Ghash {
    pub(crate) fn new(h: &[u8; 16]) -> Ghash {
        let hv = u128::from_be_bytes(*h);
        let mut table = [0u128; 16];
        table[8] = hv;
        table[4] = mulx(table[8]);
        table[2] = mulx(table[4]);
        table[1] = mulx(table[2]);
        for i in [3usize, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15] {
            let mut acc = 0u128;
            for bit in [8usize, 4, 2, 1] {
                if i & bit != 0 {
                    acc ^= table[bit];
                }
            }
            table[i] = acc;
        }
        Ghash { table, y: 0, buf: [0; 16], buf_len: 0, aad_len: 0, ct_len: 0, aad_done: false }
    }

    #[inline]
    fn mul_h(&self, x: u128) -> u128 {
        let mut z: u128 = 0;
        for i in 0..32 {
            let nib = ((x >> (4 * i)) & 0xf) as usize;
            if i > 0 {
                z = (z >> 4) ^ REM4[(z & 0xf) as usize];
            }
            z ^= self.table[nib];
        }
        z
    }

    fn absorb_block(&mut self, block: &[u8; 16]) {
        self.y = self.mul_h(self.y ^ u128::from_be_bytes(*block));
    }

    fn absorb(&mut self, mut data: &[u8]) {
        if self.buf_len > 0 {
            let take = (16 - self.buf_len).min(data.len());
            self.buf[self.buf_len..self.buf_len + take].copy_from_slice(&data[..take]);
            self.buf_len += take;
            data = &data[take..];
            if self.buf_len == 16 {
                let b = self.buf;
                self.absorb_block(&b);
                self.buf_len = 0;
            }
        }
        while data.len() >= 16 {
            let mut b = [0u8; 16];
            b.copy_from_slice(&data[..16]);
            self.absorb_block(&b);
            data = &data[16..];
        }
        if !data.is_empty() {
            self.buf[..data.len()].copy_from_slice(data);
            self.buf_len = data.len();
        }
    }

    fn flush(&mut self) {
        if self.buf_len > 0 {
            let mut b = [0u8; 16];
            b[..self.buf_len].copy_from_slice(&self.buf[..self.buf_len]);
            self.absorb_block(&b);
            self.buf_len = 0;
        }
    }

    pub(crate) fn update_aad(&mut self, data: &[u8]) {
        debug_assert!(!self.aad_done);
        self.aad_len = self.aad_len.wrapping_add(data.len() as u64);
        self.absorb(data);
    }

    fn finish_aad(&mut self) {
        if !self.aad_done {
            self.flush();
            self.aad_done = true;
        }
    }

    pub(crate) fn update_ct(&mut self, data: &[u8]) {
        self.finish_aad();
        self.ct_len = self.ct_len.wrapping_add(data.len() as u64);
        self.absorb(data);
    }

    pub(crate) fn finalize(mut self) -> [u8; 16] {
        self.finish_aad();
        self.flush();
        let mut len_block = [0u8; 16];
        len_block[..8].copy_from_slice(&self.aad_len.wrapping_mul(8).to_be_bytes());
        len_block[8..].copy_from_slice(&self.ct_len.wrapping_mul(8).to_be_bytes());
        self.absorb_block(&len_block);
        self.y.to_be_bytes()
    }
}

/// GCM pre-counter block J0 for an arbitrary-length IV.
pub(crate) fn gcm_j0(aes: &Aes, h: &[u8; 16], iv: &[u8]) -> [u8; 16] {
    if iv.len() == 12 {
        let mut j0 = [0u8; 16];
        j0[..12].copy_from_slice(iv);
        j0[15] = 1;
        j0
    } else {
        let _ = aes;
        let mut g = Ghash::new(h);
        g.update_ct(iv);
        // GHASH(IV || pad || 0^64 || [len(IV)]_64): reuse finalize with aad_len = 0.
        g.finalize()
    }
}

#[inline]
fn inc32(block: &mut [u8; 16]) {
    let c = u32::from_be_bytes([block[12], block[13], block[14], block[15]]).wrapping_add(1);
    block[12..].copy_from_slice(&c.to_be_bytes());
}

#[inline]
fn inc128(block: &mut [u8; 16]) {
    let c = u128::from_be_bytes(*block).wrapping_add(1);
    *block = c.to_be_bytes();
}

// ---------------------------------------------------------------------------------------

const STATE_INIT: u8 = 0;
const STATE_UPDATING: u8 = 1;
const STATE_FINAL: u8 = 2;

/// A cipher/decipher instance (`Cipheriv` / `Decipheriv`).
#[derive(Clone)]
pub struct CipherCtx {
    info: &'static CipherInfo,
    aes: Aes,
    decrypt: bool,
    auto_padding: bool,
    state: u8,
    /// ECB/CBC: pending input bytes.
    buf: Vec<u8>,
    /// CBC: chaining value. CTR/GCM: next counter block.
    chain: [u8; 16],
    /// CTR/GCM: current keystream block and how much of it is used.
    ks: [u8; 16],
    ks_pos: usize,
    ghash: Option<Ghash>,
    j0: [u8; 16],
    tag_len: usize,
    tag_len_explicit: bool,
    tag: Option<Vec<u8>>,
    expected_tag: Option<Vec<u8>>,
}

impl CipherCtx {
    /// Validates like the original's `initCipher` (name → key length → IV) and creates the
    /// context. `iv: None` stands for a JS `null`/`undefined` IV.
    ///
    /// Errors: unknown name → `Error` (no code)
    /// `node:crypto cipher '<name>' is not supported in lumen (aes-{128,192,256}-{ecb,cbc,ctr,gcm} only)`;
    /// wrong key size → `RangeError` `ERR_CRYPTO_INVALID_KEYLEN` `Invalid key length`;
    /// bad IV (ECB: must be absent or empty; CBC/CTR: exactly 16 bytes; GCM: at least 1 byte,
    /// no upper bound) → `TypeError` `ERR_CRYPTO_INVALID_IV` `Invalid initialization vector`.
    pub fn new(name: &str, key: &[u8], iv: Option<&[u8]>, decrypt: bool) -> Result<CipherCtx, CryptoError> {
        let info = cipher_info(name).ok_or_else(|| unsupported_cipher_error(name))?;
        Self::with_info(info, key, iv, decrypt)
    }

    /// Like [`CipherCtx::new`] with an already-resolved cipher.
    pub fn with_info(info: &'static CipherInfo, key: &[u8], iv: Option<&[u8]>, decrypt: bool) -> Result<CipherCtx, CryptoError> {
        if key.len() != info.key_len {
            return Err(invalid_key_length_error());
        }
        let aes = Aes::new(key).ok_or_else(invalid_key_length_error)?;
        let iv_ok = match info.mode {
            CipherMode::Ecb => iv.map_or(true, |v| v.is_empty()),
            CipherMode::Cbc | CipherMode::Ctr => iv.is_some_and(|v| v.len() == 16),
            CipherMode::Gcm => iv.is_some_and(|v| !v.is_empty()),
        };
        if !iv_ok {
            return Err(invalid_iv_error());
        }
        let mut chain = [0u8; 16];
        let mut ghash = None;
        let mut j0 = [0u8; 16];
        match info.mode {
            CipherMode::Ecb => {}
            CipherMode::Cbc | CipherMode::Ctr => chain.copy_from_slice(iv.unwrap_or(&[0u8; 16])),
            CipherMode::Gcm => {
                let mut h = [0u8; 16];
                aes.encrypt_block(&mut h);
                j0 = gcm_j0(&aes, &h, iv.unwrap_or(&[]));
                chain = j0;
                inc32(&mut chain);
                ghash = Some(Ghash::new(&h));
            }
        }
        Ok(CipherCtx {
            info,
            aes,
            decrypt,
            auto_padding: true,
            state: STATE_INIT,
            buf: Vec::new(),
            chain,
            ks: [0; 16],
            ks_pos: 16,
            ghash,
            j0,
            tag_len: 16,
            tag_len_explicit: false,
            tag: None,
            expected_tag: None,
        })
    }

    pub fn info(&self) -> &'static CipherInfo {
        self.info
    }

    pub fn is_decipher(&self) -> bool {
        self.decrypt
    }

    /// The `authTagLength` constructor option (only meaningful for GCM; ignored — no
    /// validation at all — for other modes, like the original). For GCM the value must be
    /// one of [`GCM_TAG_LENGTHS`], else `TypeError ERR_CRYPTO_INVALID_AUTH_TAG
    /// Invalid authentication tag length: <n>` (the JS layer must produce the same error
    /// itself for non-integer values such as `3.5`, `"16"` or `null`).
    pub fn set_auth_tag_length(&mut self, len: usize) -> Result<(), CryptoError> {
        if self.info.mode != CipherMode::Gcm {
            return Ok(());
        }
        if !GCM_TAG_LENGTHS.contains(&len) {
            return Err(invalid_auth_tag_error(&len.to_string()));
        }
        self.tag_len = len;
        self.tag_len_explicit = true;
        Ok(())
    }

    /// `setAutoPadding(on)` — allowed in any state; read by every later `update`/`final`.
    pub fn set_auto_padding(&mut self, on: bool) {
        self.auto_padding = on;
    }

    /// `setAAD(buf)`: GCM only and only before any `update`/`final` (multiple calls
    /// concatenate). Otherwise `Error ERR_CRYPTO_INVALID_STATE
    /// Invalid state for operation setAAD`. The `plaintextLength` option is ignored.
    pub fn set_aad(&mut self, aad: &[u8]) -> Result<(), CryptoError> {
        if self.info.mode != CipherMode::Gcm || self.state != STATE_INIT {
            return Err(invalid_state_for("setAAD"));
        }
        if let Some(g) = self.ghash.as_mut() {
            g.update_aad(aad);
        }
        Ok(())
    }

    /// `Decipheriv#setAuthTag(tag)`: GCM decipher only, any time before `final`
    /// (re-setting replaces the tag). Errors: wrong mode/state (or called on a cipher) →
    /// `Error ERR_CRYPTO_INVALID_STATE Invalid state for operation setAuthTag`; bad length
    /// (must equal an explicit `authTagLength`, else be one of [`GCM_TAG_LENGTHS`]) →
    /// `TypeError ERR_CRYPTO_INVALID_AUTH_TAG Invalid authentication tag length: <len>`.
    pub fn set_auth_tag(&mut self, tag: &[u8]) -> Result<(), CryptoError> {
        if self.info.mode != CipherMode::Gcm || self.state == STATE_FINAL || !self.decrypt {
            return Err(invalid_state_for("setAuthTag"));
        }
        let valid = if self.tag_len_explicit { tag.len() == self.tag_len } else { GCM_TAG_LENGTHS.contains(&tag.len()) };
        if !valid {
            return Err(invalid_auth_tag_error(&tag.len().to_string()));
        }
        self.expected_tag = Some(tag.to_vec());
        Ok(())
    }

    /// `Cipheriv#getAuthTag()`: GCM cipher after a successful `final`; returns `tag_len`
    /// bytes. Otherwise `Error ERR_CRYPTO_INVALID_STATE Invalid state for operation getAuthTag`.
    pub fn auth_tag(&self) -> Result<Vec<u8>, CryptoError> {
        if self.info.mode != CipherMode::Gcm || self.state != STATE_FINAL || self.decrypt {
            return Err(invalid_state_for("getAuthTag"));
        }
        self.tag.clone().ok_or_else(|| invalid_state_for("getAuthTag"))
    }

    fn next_keystream_block(&mut self) {
        self.ks = self.chain;
        self.aes.encrypt_block(&mut self.ks);
        if self.info.mode == CipherMode::Gcm {
            inc32(&mut self.chain);
        } else {
            inc128(&mut self.chain);
        }
        self.ks_pos = 0;
    }

    fn keystream_xor(&mut self, mut data: &[u8], out: &mut Vec<u8>) {
        // Use up a partially consumed keystream block first.
        while self.ks_pos < 16 && !data.is_empty() {
            out.push(data[0] ^ self.ks[self.ks_pos]);
            self.ks_pos += 1;
            data = &data[1..];
        }
        while data.len() >= 16 {
            self.next_keystream_block();
            for i in 0..16 {
                out.push(data[i] ^ self.ks[i]);
            }
            self.ks_pos = 16;
            data = &data[16..];
        }
        if !data.is_empty() {
            self.next_keystream_block();
            for (i, b) in data.iter().enumerate() {
                out.push(b ^ self.ks[i]);
            }
            self.ks_pos = data.len();
        }
    }

    fn process_blocks(&mut self, data: &[u8], out: &mut Vec<u8>) {
        for chunk in data.chunks(16) {
            let mut block = [0u8; 16];
            block.copy_from_slice(chunk);
            match (self.info.mode, self.decrypt) {
                (CipherMode::Ecb, false) => self.aes.encrypt_block(&mut block),
                (CipherMode::Ecb, true) => self.aes.decrypt_block(&mut block),
                (CipherMode::Cbc, false) => {
                    for i in 0..16 {
                        block[i] ^= self.chain[i];
                    }
                    self.aes.encrypt_block(&mut block);
                    self.chain = block;
                }
                (CipherMode::Cbc, true) => {
                    let saved = block;
                    self.aes.decrypt_block(&mut block);
                    for i in 0..16 {
                        block[i] ^= self.chain[i];
                    }
                    self.chain = saved;
                }
                _ => unreachable!(),
            }
            out.extend_from_slice(&block);
        }
    }

    /// `update(data)`. ECB/CBC return only whole blocks (a decipher with auto-padding on
    /// holds back the last whole block when the buffered input is block-aligned); CTR/GCM
    /// return exactly `data.len()` bytes. After `final`: `Error` (no code)
    /// `Trying to add data in unsupported state`.
    pub fn update(&mut self, data: &[u8]) -> Result<Vec<u8>, CryptoError> {
        if self.state == STATE_FINAL {
            return Err(CryptoError::error("Trying to add data in unsupported state"));
        }
        self.state = STATE_UPDATING;
        let mut out = Vec::with_capacity(data.len() + 16);
        match self.info.mode {
            CipherMode::Ecb | CipherMode::Cbc => {
                self.buf.extend_from_slice(data);
                let mut n = self.buf.len() / 16 * 16;
                if self.decrypt && self.auto_padding && n == self.buf.len() && n > 0 {
                    n -= 16;
                }
                if n > 0 {
                    let pending: Vec<u8> = self.buf.drain(..n).collect();
                    self.process_blocks(&pending, &mut out);
                }
            }
            CipherMode::Ctr => self.keystream_xor(data, &mut out),
            CipherMode::Gcm => {
                if self.decrypt {
                    if let Some(g) = self.ghash.as_mut() {
                        g.update_ct(data);
                    }
                    self.keystream_xor(data, &mut out);
                } else {
                    self.keystream_xor(data, &mut out);
                    if let Some(g) = self.ghash.as_mut() {
                        g.update_ct(&out);
                    }
                }
            }
        }
        Ok(out)
    }

    /// `final()`. The context is finalized even when this fails. Errors:
    /// second call → `Error ERR_CRYPTO_INVALID_STATE Invalid state`;
    /// ECB/CBC leftover not usable → `Error ERR_OSSL_WRONG_FINAL_BLOCK_LENGTH
    /// error:1C80006B:Provider routines::wrong final block length`;
    /// bad PKCS#7 padding → `Error ERR_OSSL_BAD_DECRYPT error:1C800064:Provider routines::bad decrypt`;
    /// GCM decipher without/with a wrong tag → `Error` (no code)
    /// `Unsupported state or unable to authenticate data`.
    pub fn finalize(&mut self) -> Result<Vec<u8>, CryptoError> {
        if self.state == STATE_FINAL {
            return Err(CryptoError::coded(ErrorKind::Error, "ERR_CRYPTO_INVALID_STATE", "Invalid state"));
        }
        self.state = STATE_FINAL;
        match self.info.mode {
            CipherMode::Ecb | CipherMode::Cbc => {
                let mut out = Vec::new();
                if !self.decrypt {
                    if self.auto_padding {
                        let pad = 16 - (self.buf.len() % 16);
                        let mut block = std::mem::take(&mut self.buf);
                        block.extend(std::iter::repeat(pad as u8).take(pad));
                        self.process_blocks(&block, &mut out);
                    } else if !self.buf.is_empty() {
                        return Err(wrong_final_block_length());
                    }
                } else if self.auto_padding {
                    if self.buf.len() != 16 {
                        return Err(wrong_final_block_length());
                    }
                    let block = std::mem::take(&mut self.buf);
                    self.process_blocks(&block, &mut out);
                    let n = out[15] as usize;
                    if n == 0 || n > 16 || out[16 - n..].iter().any(|&b| b as usize != n) {
                        return Err(bad_decrypt());
                    }
                    out.truncate(16 - n);
                } else if !self.buf.is_empty() {
                    return Err(wrong_final_block_length());
                }
                Ok(out)
            }
            CipherMode::Ctr => Ok(Vec::new()),
            CipherMode::Gcm => {
                let s = self.ghash.take().map(|g| g.finalize()).unwrap_or([0u8; 16]);
                let mut ekj0 = self.j0;
                self.aes.encrypt_block(&mut ekj0);
                let mut full = [0u8; 16];
                for i in 0..16 {
                    full[i] = ekj0[i] ^ s[i];
                }
                if self.decrypt {
                    match &self.expected_tag {
                        Some(t) if super::random::timing_safe_eq(t, &full[..t.len()]) => Ok(Vec::new()),
                        _ => Err(CryptoError::error("Unsupported state or unable to authenticate data")),
                    }
                } else {
                    self.tag = Some(full[..self.tag_len].to_vec());
                    Ok(Vec::new())
                }
            }
        }
    }
}

/// One-shot AES-GCM encryption: returns `(ciphertext, 16-byte tag)`.
pub fn aes_gcm_encrypt(key: &[u8], iv: &[u8], aad: &[u8], plaintext: &[u8]) -> Result<(Vec<u8>, Vec<u8>), CryptoError> {
    let info = match key.len() {
        16 => &CIPHERS[3],
        24 => &CIPHERS[7],
        32 => &CIPHERS[11],
        _ => return Err(invalid_key_length_error()),
    };
    let mut c = CipherCtx::with_info(info, key, Some(iv), false)?;
    c.set_aad(aad)?;
    let mut ct = c.update(plaintext)?;
    ct.extend(c.finalize()?);
    Ok((ct, c.auth_tag()?))
}

/// One-shot AES-GCM decryption with tag verification (tag may be 4..=16 bytes, see
/// [`GCM_TAG_LENGTHS`]).
pub fn aes_gcm_decrypt(key: &[u8], iv: &[u8], aad: &[u8], ciphertext: &[u8], tag: &[u8]) -> Result<Vec<u8>, CryptoError> {
    let info = match key.len() {
        16 => &CIPHERS[3],
        24 => &CIPHERS[7],
        32 => &CIPHERS[11],
        _ => return Err(invalid_key_length_error()),
    };
    let mut c = CipherCtx::with_info(info, key, Some(iv), true)?;
    c.set_auth_tag(tag)?;
    c.set_aad(aad)?;
    let mut pt = c.update(ciphertext)?;
    pt.extend(c.finalize()?);
    Ok(pt)
}
