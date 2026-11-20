//! Minimal DER reader/writer, OIDs and PEM, as needed for key and certificate formats.

use super::CryptoError;

pub const TAG_BOOLEAN: u8 = 0x01;
pub const TAG_INTEGER: u8 = 0x02;
pub const TAG_BIT_STRING: u8 = 0x03;
pub const TAG_OCTET_STRING: u8 = 0x04;
pub const TAG_NULL: u8 = 0x05;
pub const TAG_OID: u8 = 0x06;
pub const TAG_UTF8_STRING: u8 = 0x0c;
pub const TAG_PRINTABLE_STRING: u8 = 0x13;
pub const TAG_T61_STRING: u8 = 0x14;
pub const TAG_IA5_STRING: u8 = 0x16;
pub const TAG_UTC_TIME: u8 = 0x17;
pub const TAG_GENERALIZED_TIME: u8 = 0x18;
pub const TAG_UNIVERSAL_STRING: u8 = 0x1c;
pub const TAG_BMP_STRING: u8 = 0x1e;
pub const TAG_SEQUENCE: u8 = 0x30;
pub const TAG_SET: u8 = 0x31;

/// `ASN.1: truncated DER` (plain Error) — the original's message when a length runs past
/// the end of the input.
pub fn truncated() -> CryptoError {
    CryptoError::error("ASN.1: truncated DER")
}

/// The original reports most other structural problems through an accidental JS
/// `TypeError: cannot read property 'content' of undefined`; this mirrors it.
pub fn malformed() -> CryptoError {
    CryptoError::type_error("cannot read property 'content' of undefined")
}

/// One parsed TLV element. Offsets are relative to the buffer passed to [`read_tlv`].
#[derive(Clone, Copy, Debug)]
pub struct Tlv<'a> {
    pub tag: u8,
    /// Offset of the tag byte.
    pub start: usize,
    /// Offset of the first content byte.
    pub content_start: usize,
    /// Offset one past the last content byte.
    pub end: usize,
    pub content: &'a [u8],
}

impl<'a> Tlv<'a> {
    /// The complete encoding (header + content) within `buf`.
    pub fn raw<'b>(&self, buf: &'b [u8]) -> &'b [u8] {
        &buf[self.start..self.end]
    }
}

/// Read one TLV at `off`. Supports single-byte tags and short/long definite lengths.
pub fn read_tlv(buf: &[u8], off: usize) -> Result<Tlv<'_>, CryptoError> {
    if off >= buf.len() {
        return Err(malformed());
    }
    let tag = buf[off];
    let mut p = off + 1;
    if p >= buf.len() {
        return Err(malformed());
    }
    let first = buf[p];
    p += 1;
    let len = if first < 0x80 {
        first as usize
    } else {
        let n = (first & 0x7f) as usize;
        if n == 0 {
            return Err(malformed()); // indefinite length is not DER
        }
        if n > 8 || p + n > buf.len() {
            return Err(truncated());
        }
        let mut l: u64 = 0;
        for i in 0..n {
            l = (l << 8) | buf[p + i] as u64;
        }
        p += n;
        if l > usize::MAX as u64 {
            return Err(truncated());
        }
        l as usize
    };
    if len > buf.len() - p {
        return Err(truncated());
    }
    Ok(Tlv { tag, start: off, content_start: p, end: p + len, content: &buf[p..p + len] })
}

/// Read a TLV that must span the whole buffer.
pub fn read_exact(buf: &[u8]) -> Result<Tlv<'_>, CryptoError> {
    let t = read_tlv(buf, 0)?;
    if t.end != buf.len() {
        return Err(malformed());
    }
    Ok(t)
}

/// All TLV children inside `content` (offsets are relative to `content`).
pub fn children(content: &[u8]) -> Result<Vec<Tlv<'_>>, CryptoError> {
    let mut out = Vec::new();
    let mut off = 0;
    while off < content.len() {
        let t = read_tlv(content, off)?;
        off = t.end;
        out.push(t);
    }
    Ok(out)
}

/// Expect a specific tag.
pub fn expect<'a>(t: Option<&Tlv<'a>>, tag: u8) -> Result<Tlv<'a>, CryptoError> {
    match t {
        Some(t) if t.tag == tag => Ok(*t),
        _ => Err(malformed()),
    }
}

/// Decode an OID's content bytes to dotted form (`1.2.840.113549.1.1.1`).
pub fn decode_oid(content: &[u8]) -> String {
    let mut parts: Vec<u64> = Vec::new();
    let mut v: u64 = 0;
    let mut first = true;
    for &b in content {
        v = (v << 7) | (b & 0x7f) as u64;
        if b & 0x80 == 0 {
            if first {
                let (a, b2) = if v < 40 {
                    (0, v)
                } else if v < 80 {
                    (1, v - 40)
                } else {
                    (2, v - 80)
                };
                parts.push(a);
                parts.push(b2);
                first = false;
            } else {
                parts.push(v);
            }
            v = 0;
        }
    }
    parts.iter().map(|p| p.to_string()).collect::<Vec<_>>().join(".")
}

/// Encode a dotted OID to its content bytes.
pub fn encode_oid(dotted: &str) -> Vec<u8> {
    let nums: Vec<u64> = dotted.split('.').filter_map(|s| s.parse().ok()).collect();
    let mut out = Vec::new();
    if nums.len() < 2 {
        return out;
    }
    let push = |mut v: u64, out: &mut Vec<u8>| {
        let mut tmp = vec![(v & 0x7f) as u8];
        v >>= 7;
        while v > 0 {
            tmp.push(0x80 | (v & 0x7f) as u8);
            v >>= 7;
        }
        tmp.reverse();
        out.extend_from_slice(&tmp);
    };
    push(nums[0] * 40 + nums[1], &mut out);
    for &n in &nums[2..] {
        push(n, &mut out);
    }
    out
}

// ---- writer --------------------------------------------------------------------------

pub fn encode_len(len: usize, out: &mut Vec<u8>) {
    if len < 0x80 {
        out.push(len as u8);
    } else {
        let bytes = len.to_be_bytes();
        let first = bytes.iter().position(|&b| b != 0).unwrap_or(bytes.len() - 1);
        out.push(0x80 | (bytes.len() - first) as u8);
        out.extend_from_slice(&bytes[first..]);
    }
}

/// Encode a TLV.
pub fn tlv(tag: u8, content: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(content.len() + 6);
    out.push(tag);
    encode_len(content.len(), &mut out);
    out.extend_from_slice(content);
    out
}

/// SEQUENCE of already-encoded elements.
pub fn sequence(parts: &[&[u8]]) -> Vec<u8> {
    let content: Vec<u8> = parts.concat();
    tlv(TAG_SEQUENCE, &content)
}

/// INTEGER from unsigned big-endian magnitude bytes (minimal; leading 0x00 when needed).
pub fn integer_unsigned(be: &[u8]) -> Vec<u8> {
    let first = be.iter().position(|&b| b != 0).unwrap_or(be.len());
    let mag = &be[first..];
    let mut content = Vec::with_capacity(mag.len() + 1);
    if mag.is_empty() || mag[0] & 0x80 != 0 {
        content.push(0);
    }
    content.extend_from_slice(mag);
    tlv(TAG_INTEGER, &content)
}

pub fn integer_u64(v: u64) -> Vec<u8> {
    integer_unsigned(&v.to_be_bytes())
}

/// Unsigned magnitude of an INTEGER's content (strips leading zero bytes).
pub fn integer_magnitude(content: &[u8]) -> &[u8] {
    let first = content.iter().position(|&b| b != 0).unwrap_or(content.len());
    &content[first..]
}

pub fn octet_string(b: &[u8]) -> Vec<u8> {
    tlv(TAG_OCTET_STRING, b)
}

/// BIT STRING with zero unused bits.
pub fn bit_string(b: &[u8]) -> Vec<u8> {
    let mut c = Vec::with_capacity(b.len() + 1);
    c.push(0);
    c.extend_from_slice(b);
    tlv(TAG_BIT_STRING, &c)
}

pub fn oid(dotted: &str) -> Vec<u8> {
    tlv(TAG_OID, &encode_oid(dotted))
}

pub fn null() -> Vec<u8> {
    vec![TAG_NULL, 0]
}

/// Context-specific constructed tag `[n]`.
pub fn context(n: u8, content: &[u8]) -> Vec<u8> {
    tlv(0xa0 | n, content)
}

// ---- PEM ------------------------------------------------------------------------------

const B64: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

pub fn base64_encode(data: &[u8]) -> String {
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
    for chunk in data.chunks(3) {
        let b = [chunk[0], *chunk.get(1).unwrap_or(&0), *chunk.get(2).unwrap_or(&0)];
        let n = ((b[0] as u32) << 16) | ((b[1] as u32) << 8) | b[2] as u32;
        out.push(B64[(n >> 18) as usize & 63] as char);
        out.push(B64[(n >> 12) as usize & 63] as char);
        out.push(if chunk.len() > 1 { B64[(n >> 6) as usize & 63] as char } else { '=' });
        out.push(if chunk.len() > 2 { B64[n as usize & 63] as char } else { '=' });
    }
    out
}

/// base64url without padding (JWK / `export({format:'jwk'})`).
pub fn base64url_encode(data: &[u8]) -> String {
    base64_encode(data).trim_end_matches('=').replace('+', "-").replace('/', "_")
}

/// Lenient base64 / base64url decoder (ignores whitespace and padding; skips invalid
/// characters like Node's `Buffer.from(s, 'base64')`).
pub fn base64_decode(s: &str) -> Vec<u8> {
    let mut out = Vec::with_capacity(s.len() * 3 / 4);
    let mut acc: u32 = 0;
    let mut nbits = 0;
    for c in s.bytes() {
        let v = match c {
            b'A'..=b'Z' => c - b'A',
            b'a'..=b'z' => c - b'a' + 26,
            b'0'..=b'9' => c - b'0' + 52,
            b'+' | b'-' => 62,
            b'/' | b'_' => 63,
            b'=' => break,
            _ => continue,
        };
        acc = (acc << 6) | v as u32;
        nbits += 6;
        if nbits >= 8 {
            nbits -= 8;
            out.push((acc >> nbits) as u8);
            acc &= (1 << nbits) - 1;
        }
    }
    out
}

/// PEM-encode with 64-column lines and a trailing newline:
/// `-----BEGIN <label>-----\n...\n-----END <label>-----\n`.
pub fn pem_encode(label: &str, der: &[u8]) -> String {
    let b64 = base64_encode(der);
    let mut s = format!("-----BEGIN {}-----\n", label);
    for line in b64.as_bytes().chunks(64) {
        s.push_str(std::str::from_utf8(line).unwrap_or(""));
        s.push('\n');
    }
    s.push_str(&format!("-----END {}-----\n", label));
    s
}

/// Decode the first PEM block: returns `(label, der)`. Error (plain Error)
/// `crypto: no PEM data found` when there is no `-----BEGIN ...-----` / matching END.
pub fn pem_decode(text: &str) -> Result<(String, Vec<u8>), CryptoError> {
    let no_pem = || CryptoError::error("crypto: no PEM data found");
    let begin = text.find("-----BEGIN ").ok_or_else(no_pem)?;
    let after = &text[begin + 11..];
    let label_end = after.find("-----").ok_or_else(no_pem)?;
    let label = &after[..label_end];
    let body_start = begin + 11 + label_end + 5;
    let end_marker = format!("-----END {}-----", label);
    let end = text[body_start..].find(&end_marker).ok_or_else(no_pem)? + body_start;
    let body = &text[body_start..end];
    // Skip RFC 1421 headers (e.g. "Proc-Type:"), present in legacy encrypted PEM.
    let payload: String = if body.contains(':') {
        let mut lines = body.lines().peekable();
        let mut out = String::new();
        let mut in_headers = true;
        while let Some(l) = lines.next() {
            if in_headers {
                if l.contains(':') {
                    continue;
                }
                if l.trim().is_empty() {
                    in_headers = false;
                    continue;
                }
                in_headers = false;
            }
            out.push_str(l);
        }
        out
    } else {
        body.to_string()
    };
    Ok((label.to_string(), base64_decode(&payload)))
}
