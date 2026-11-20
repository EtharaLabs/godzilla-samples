// Byte/string encoding helpers (base64, hex, utf8, latin1).

const B64: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const B64URL: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

pub fn base64_encode(data: &[u8], url: bool) -> String {
    let t = if url { B64URL } else { B64 };
    let mut out = String::with_capacity((data.len() + 2) / 3 * 4);
    for chunk in data.chunks(3) {
        let b0 = chunk[0] as u32;
        let b1 = chunk.get(1).copied().unwrap_or(0) as u32;
        let b2 = chunk.get(2).copied().unwrap_or(0) as u32;
        let n = (b0 << 16) | (b1 << 8) | b2;
        out.push(t[(n >> 18) as usize & 63] as char);
        out.push(t[(n >> 12) as usize & 63] as char);
        if chunk.len() > 1 {
            out.push(t[(n >> 6) as usize & 63] as char);
        } else {
            out.push('=');
        }
        if chunk.len() > 2 {
            out.push(t[n as usize & 63] as char);
        } else {
            out.push('=');
        }
    }
    out
}

fn b64val(c: u8) -> Option<u32> {
    match c {
        b'A'..=b'Z' => Some((c - b'A') as u32),
        b'a'..=b'z' => Some((c - b'a' + 26) as u32),
        b'0'..=b'9' => Some((c - b'0' + 52) as u32),
        b'+' | b'-' => Some(62),
        b'/' | b'_' => Some(63),
        _ => None,
    }
}

/// Lenient decoding (Node Buffer.from(str, 'base64')): skips invalid chars, stops at '='.
pub fn base64_decode_lenient(s: &str) -> Vec<u8> {
    let mut out = Vec::new();
    let mut acc = 0u32;
    let mut bits = 0;
    for &c in s.as_bytes() {
        if c == b'=' {
            break;
        }
        let v = match b64val(c) {
            Some(v) => v,
            None => continue,
        };
        acc = (acc << 6) | v;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push((acc >> bits) as u8);
            acc &= (1 << bits) - 1;
        }
    }
    out
}

/// Strict decoding (atob-like forgiving-base64): whitespace removed; returns None on error.
pub fn base64_decode_strict(s: &str) -> Option<Vec<u8>> {
    let cleaned: Vec<u8> = s.bytes().filter(|c| !matches!(c, b' ' | b'\t' | b'\n' | b'\x0c' | b'\r')).collect();
    let mut data = cleaned;
    if data.len() % 4 == 0 && !data.is_empty() {
        if data.ends_with(b"==") {
            data.truncate(data.len() - 2);
        } else if data.ends_with(b"=") {
            data.truncate(data.len() - 1);
        }
    }
    if data.len() % 4 == 1 {
        return None;
    }
    let mut out = Vec::new();
    let mut acc = 0u32;
    let mut bits = 0;
    for &c in &data {
        let v = match c {
            b'A'..=b'Z' => (c - b'A') as u32,
            b'a'..=b'z' => (c - b'a' + 26) as u32,
            b'0'..=b'9' => (c - b'0' + 52) as u32,
            b'+' => 62,
            b'/' => 63,
            _ => return None,
        };
        acc = (acc << 6) | v;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push((acc >> bits) as u8);
            acc &= (1 << bits) - 1;
        }
    }
    Some(out)
}

pub fn hex_encode(data: &[u8]) -> String {
    let mut s = String::with_capacity(data.len() * 2);
    for b in data {
        s.push_str(&format!("{:02x}", b));
    }
    s
}

pub fn hex_decode(s: &str) -> Option<Vec<u8>> {
    if s.len() % 2 != 0 {
        return None;
    }
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len() / 2);
    for i in (0..b.len()).step_by(2) {
        let h = (b[i] as char).to_digit(16)?;
        let l = (b[i + 1] as char).to_digit(16)?;
        out.push((h * 16 + l) as u8);
    }
    Some(out)
}

/// Lenient hex decoding (Buffer.from(str, 'hex')): stops at first invalid pair.
pub fn hex_decode_lenient(s: &str) -> Vec<u8> {
    let b = s.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i + 1 < b.len() {
        match ((b[i] as char).to_digit(16), (b[i + 1] as char).to_digit(16)) {
            (Some(h), Some(l)) => out.push((h * 16 + l) as u8),
            _ => break,
        }
        i += 2;
    }
    out
}

/// UTF-16 -> UTF-8 with lone surrogates replaced by U+FFFD
pub fn utf16_to_utf8(u: &[u16]) -> Vec<u8> {
    let mut out = Vec::with_capacity(u.len());
    for r in char::decode_utf16(u.iter().copied()) {
        let c = r.unwrap_or('\u{fffd}');
        let mut buf = [0u8; 4];
        out.extend_from_slice(c.encode_utf8(&mut buf).as_bytes());
    }
    out
}

/// UTF-8 bytes -> UTF-16 with WHATWG replacement semantics
pub fn utf8_to_utf16(b: &[u8]) -> Vec<u16> {
    let s = String::from_utf8_lossy(b);
    s.encode_utf16().collect()
}

pub fn latin1_to_utf16(b: &[u8]) -> Vec<u16> {
    b.iter().map(|&x| x as u16).collect()
}
