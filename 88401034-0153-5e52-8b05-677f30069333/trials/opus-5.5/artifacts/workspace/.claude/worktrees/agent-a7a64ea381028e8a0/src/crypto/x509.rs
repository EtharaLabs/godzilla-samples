//! X.509 certificate parsing as done by the original's `X509Certificate` class.

use super::asn1::{self, Tlv};
use super::hash::{digest, HashAlg};
use super::keys::{self, AsymKey};
use super::CryptoError;

/// Parsed certificate. String fields are already formatted exactly like the original.
#[derive(Clone, Debug)]
pub struct Certificate {
    /// Full DER (`x509.raw`).
    pub raw: Vec<u8>,
    /// `serialNumber`: upper-case hex of the INTEGER content with ONE leading `00` byte
    /// removed (`"00"` when that leaves nothing).
    pub serial_number: String,
    /// `issuer` / `subject`: one `NAME=value` per attribute (multi-valued RDNs are split
    /// into separate lines), joined with `\n`, no escaping. Only C, ST, L, O, OU, CN and
    /// emailAddress get short names; other attribute types print as dotted OIDs.
    pub issuer: String,
    pub subject: String,
    /// `validFromDate` / `validToDate` as milliseconds since the Unix epoch.
    pub valid_from_ms: i64,
    pub valid_to_ms: i64,
    /// `validFrom` / `validTo`, e.g. `Sep  1 00:00:00 2009 GMT`.
    pub valid_from: String,
    pub valid_to: String,
    /// Colon-separated upper-case hex digests of the DER.
    pub fingerprint: String,
    pub fingerprint256: String,
    pub fingerprint512: String,
    /// DER of the SubjectPublicKeyInfo (`publicKey = createPublicKey({key: spki, format:'der', type:'spki'})`).
    pub spki: Vec<u8>,
    /// basicConstraints cA (false when absent).
    pub ca: bool,
    /// SAN entries `(type, value)`: types `DNS`, `email`, `IP Address` only (URI, dirName,
    /// otherName are dropped). IPv6 is printed as 8 lower-case groups without compression.
    pub alt_names: Vec<(String, String)>,
    /// `subjectAltName`: `type:value` joined by `, `, `None` (undefined) when empty.
    pub subject_alt_name: Option<String>,
    /// Encoded TBSCertificate (signed bytes).
    pub tbs: Vec<u8>,
    /// Signature algorithm OID.
    pub signature_algorithm_oid: String,
    /// Digest the original verifies with (`X509_SIGNATURE_OIDS`): md5/sha1/sha256/sha384/
    /// sha512 with RSA, sha256/sha384/sha512 with ECDSA. `None` → `verify()` returns false.
    pub signature_digest: Option<HashAlg>,
    /// Signature BIT STRING content without the unused-bits byte.
    pub signature: Vec<u8>,
}

fn invalid_der() -> CryptoError {
    CryptoError::error("X509: invalid certificate DER")
}

fn attr_name(oid: &str) -> String {
    match oid {
        "2.5.4.6" => "C".into(),
        "2.5.4.8" => "ST".into(),
        "2.5.4.7" => "L".into(),
        "2.5.4.10" => "O".into(),
        "2.5.4.11" => "OU".into(),
        "2.5.4.3" => "CN".into(),
        "1.2.840.113549.1.9.1" => "emailAddress".into(),
        other => other.into(),
    }
}

/// Decode an ASN.1 string value (UTF8/Printable/IA5/T61 as bytes→UTF-8/Latin-1, BMP as
/// UTF-16BE, Universal as UTF-32BE).
pub fn decode_string(t: &Tlv<'_>) -> String {
    match t.tag {
        asn1::TAG_BMP_STRING => {
            let units: Vec<u16> = t.content.chunks(2).map(|c| u16::from_be_bytes([c[0], *c.get(1).unwrap_or(&0)])).collect();
            String::from_utf16_lossy(&units)
        }
        asn1::TAG_UNIVERSAL_STRING => t
            .content
            .chunks(4)
            .filter_map(|c| {
                if c.len() == 4 {
                    char::from_u32(u32::from_be_bytes([c[0], c[1], c[2], c[3]]))
                } else {
                    None
                }
            })
            .collect(),
        _ => match std::str::from_utf8(t.content) {
            Ok(s) => s.to_string(),
            Err(_) => t.content.iter().map(|&b| b as char).collect(),
        },
    }
}

/// Format a Name (SEQUENCE OF SET OF AttributeTypeAndValue) like the original.
pub fn format_name(name_content: &[u8]) -> Result<String, CryptoError> {
    let mut lines = Vec::new();
    for rdn in asn1::children(name_content)? {
        for atv in asn1::children(rdn.content)? {
            let kids = asn1::children(atv.content)?;
            if kids.len() < 2 || kids[0].tag != asn1::TAG_OID {
                continue;
            }
            lines.push(format!("{}={}", attr_name(&asn1::decode_oid(kids[0].content)), decode_string(&kids[1])));
        }
    }
    Ok(lines.join("\n"))
}

fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let mp = (m + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

fn civil_from_days(z: i64) -> (i64, i64, i64) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// Parse UTCTime (`YYMMDDHHMM[SS]Z`, YY < 50 → 20YY) or GeneralizedTime
/// (`YYYYMMDDHHMM[SS[.fff]]Z`) into epoch milliseconds.
pub fn parse_time(t: &Tlv<'_>) -> Result<i64, CryptoError> {
    let s = std::str::from_utf8(t.content).map_err(|_| invalid_der())?;
    let digits: Vec<i64> = s.bytes().take_while(|b| b.is_ascii_digit()).map(|b| (b - b'0') as i64).collect();
    let num = |i: usize, n: usize| -> i64 { digits[i..i + n].iter().fold(0, |a, d| a * 10 + d) };
    let (year, rest) = if t.tag == asn1::TAG_UTC_TIME {
        if digits.len() < 10 {
            return Err(invalid_der());
        }
        let yy = num(0, 2);
        (if yy >= 50 { 1900 + yy } else { 2000 + yy }, 2)
    } else {
        if digits.len() < 12 {
            return Err(invalid_der());
        }
        (num(0, 4), 4)
    };
    let month = num(rest, 2);
    let day = num(rest + 2, 2);
    let hour = num(rest + 4, 2);
    let minute = num(rest + 6, 2);
    let second = if digits.len() >= rest + 10 { num(rest + 8, 2) } else { 0 };
    let days = days_from_civil(year, month, day);
    Ok(((days * 24 + hour) * 60 + minute) * 60_000 + second * 1000)
}

/// `Mon DD HH:MM:SS YYYY GMT` with a space-padded day (OpenSSL / Node style).
pub fn format_time(ms: i64) -> String {
    const MONTHS: [&str; 12] = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    let secs = ms.div_euclid(1000);
    let days = secs.div_euclid(86400);
    let sod = secs.rem_euclid(86400);
    let (y, m, d) = civil_from_days(days);
    format!("{} {:>2} {:02}:{:02}:{:02} {} GMT", MONTHS[(m - 1) as usize], d, sod / 3600, (sod / 60) % 60, sod % 60, y)
}

/// `AB:CD:...` upper-case hex digest.
pub fn fingerprint(der: &[u8], alg: HashAlg) -> String {
    digest(alg, der).iter().map(|b| format!("{:02X}", b)).collect::<Vec<_>>().join(":")
}

fn format_ip(b: &[u8]) -> Option<String> {
    match b.len() {
        4 => Some(format!("{}.{}.{}.{}", b[0], b[1], b[2], b[3])),
        16 => Some(
            b.chunks(2)
                .map(|c| format!("{:x}", u16::from_be_bytes([c[0], c[1]])))
                .collect::<Vec<_>>()
                .join(":"),
        ),
        _ => None,
    }
}

fn signature_digest_for(oid: &str) -> Option<HashAlg> {
    Some(match oid {
        "1.2.840.113549.1.1.4" => HashAlg::Md5,
        "1.2.840.113549.1.1.5" => HashAlg::Sha1,
        "1.2.840.113549.1.1.11" => HashAlg::Sha256,
        "1.2.840.113549.1.1.12" => HashAlg::Sha384,
        "1.2.840.113549.1.1.13" => HashAlg::Sha512,
        "1.2.840.10045.4.3.2" => HashAlg::Sha256,
        "1.2.840.10045.4.3.3" => HashAlg::Sha384,
        "1.2.840.10045.4.3.4" => HashAlg::Sha512,
        _ => return None,
    })
}

impl Certificate {
    /// Parse DER. Errors: `X509: invalid certificate DER` (outer element not a SEQUENCE
    /// spanning the input), `X509: invalid certificate structure` (not 3 children), DER
    /// errors (`ASN.1: truncated DER`), and key-parsing errors for the SPKI (e.g.
    /// `EC curve secp384r1 is not supported in lumen (only prime256v1)` — the original
    /// cannot construct certificates with non-P-256 EC keys).
    pub fn parse(der: &[u8]) -> Result<Certificate, CryptoError> {
        let cert = asn1::read_tlv(der, 0)?;
        if cert.tag != asn1::TAG_SEQUENCE || cert.end != der.len() {
            return Err(invalid_der());
        }
        let outer = asn1::children(cert.content)?;
        if outer.len() != 3 {
            return Err(CryptoError::error("X509: invalid certificate structure"));
        }
        let tbs = outer[0];
        let fields = asn1::children(tbs.content)?;
        let mut i = if fields.first().map(|f| f.tag) == Some(0xa0) { 1 } else { 0 };
        let get = |i: usize| fields.get(i).copied().ok_or_else(asn1::malformed);
        let serial = get(i)?;
        i += 2; // serial, TBS signature algorithm
        let issuer = get(i)?;
        i += 1;
        let validity = asn1::children(get(i)?.content)?;
        i += 1;
        let subject = get(i)?;
        i += 1;
        let spki_t = get(i)?;
        i += 1;
        let hex: String = serial.content.iter().map(|b| format!("{:02x}", b)).collect();
        let hex = hex.strip_prefix("00").unwrap_or(&hex).to_uppercase();
        let serial_number = if hex.is_empty() { "00".to_string() } else { hex };
        let valid_from_ms = parse_time(validity.first().ok_or_else(asn1::malformed)?)?;
        let valid_to_ms = parse_time(validity.get(1).ok_or_else(asn1::malformed)?)?;
        let spki = spki_t.raw(tbs.content).to_vec();
        // Validate the key like `createPublicKey` would.
        keys::parse_spki(&spki)?;

        let mut ca = false;
        let mut alt_names = Vec::new();
        for f in &fields[i..] {
            if f.tag != 0xa3 {
                continue;
            }
            let exts_seq = asn1::read_tlv(f.content, 0)?;
            for ext in asn1::children(exts_seq.content)? {
                let parts = asn1::children(ext.content)?;
                let oid = match parts.first() {
                    Some(p) if p.tag == asn1::TAG_OID => asn1::decode_oid(p.content),
                    _ => continue,
                };
                let value = match parts.iter().rev().find(|p| p.tag == asn1::TAG_OCTET_STRING) {
                    Some(v) => v.content,
                    None => continue,
                };
                match oid.as_str() {
                    "2.5.29.19" => {
                        let bc = asn1::read_tlv(value, 0)?;
                        let kids = asn1::children(bc.content)?;
                        ca = kids.first().is_some_and(|k| k.tag == asn1::TAG_BOOLEAN && k.content.first().is_some_and(|&b| b != 0));
                    }
                    "2.5.29.17" => {
                        let gn = asn1::read_tlv(value, 0)?;
                        for name in asn1::children(gn.content)? {
                            match name.tag {
                                0x81 => alt_names.push(("email".to_string(), String::from_utf8_lossy(name.content).into_owned())),
                                0x82 => alt_names.push(("DNS".to_string(), String::from_utf8_lossy(name.content).into_owned())),
                                0x87 => {
                                    if let Some(ip) = format_ip(name.content) {
                                        alt_names.push(("IP Address".to_string(), ip));
                                    }
                                }
                                _ => {}
                            }
                        }
                    }
                    _ => {}
                }
            }
        }
        let subject_alt_name = if alt_names.is_empty() {
            None
        } else {
            Some(alt_names.iter().map(|(t, v)| format!("{}:{}", t, v)).collect::<Vec<_>>().join(", "))
        };
        let alg = asn1::children(outer[1].content)?;
        let signature_algorithm_oid = match alg.first() {
            Some(a) if a.tag == asn1::TAG_OID => asn1::decode_oid(a.content),
            _ => String::new(),
        };
        let signature = if outer[2].tag == asn1::TAG_BIT_STRING && !outer[2].content.is_empty() {
            outer[2].content[1..].to_vec()
        } else {
            Vec::new()
        };
        Ok(Certificate {
            raw: der.to_vec(),
            serial_number,
            issuer: format_name(issuer.content)?,
            subject: format_name(subject.content)?,
            valid_from_ms,
            valid_to_ms,
            valid_from: format_time(valid_from_ms),
            valid_to: format_time(valid_to_ms),
            fingerprint: fingerprint(der, HashAlg::Sha1),
            fingerprint256: fingerprint(der, HashAlg::Sha256),
            fingerprint512: fingerprint(der, HashAlg::Sha512),
            spki,
            ca,
            alt_names,
            subject_alt_name,
            tbs: tbs.raw(cert.content).to_vec(),
            signature_digest: signature_digest_for(&signature_algorithm_oid),
            signature_algorithm_oid,
            signature,
        })
    }

    /// The constructor's input handling: a JS string (`is_string`), or a Uint8Array/Buffer
    /// whose UTF-8 text contains `BEGIN CERTIFICATE`, is PEM-decoded (label must be
    /// `CERTIFICATE`, else `X509: expected a CERTIFICATE PEM block`; no PEM at all →
    /// `crypto: no PEM data found`); other bytes are DER. (ArrayBuffer/DataView inputs are
    /// always DER in the original: call [`Certificate::parse`] for those.)
    pub fn from_input(input: &[u8], is_string: bool) -> Result<Certificate, CryptoError> {
        let text = String::from_utf8_lossy(input);
        if is_string || text.contains("BEGIN CERTIFICATE") {
            let (label, der) = asn1::pem_decode(&text)?;
            if label != "CERTIFICATE" {
                return Err(CryptoError::error("X509: expected a CERTIFICATE PEM block"));
            }
            Certificate::parse(&der)
        } else {
            Certificate::parse(input)
        }
    }

    pub fn public_key(&self) -> Result<AsymKey, CryptoError> {
        keys::parse_spki(&self.spki)
    }

    /// `x509.verify(publicKey)`: false when the signature algorithm is not in the
    /// original's table; otherwise RSA PKCS#1 v1.5 / ECDSA (DER) verification of the TBS.
    pub fn verify(&self, key: &AsymKey) -> bool {
        let alg = match self.signature_digest {
            Some(a) => a,
            None => return false,
        };
        match key {
            AsymKey::RsaPublic(_) | AsymKey::RsaPrivate(_) => {
                let pk = key.rsa_public().unwrap();
                super::rsa::rsa_pkcs1v15_verify(&pk, alg, &self.tbs, &self.signature).unwrap_or(false)
            }
            AsymKey::EcPublic { point } | AsymKey::EcPrivate { point, .. } => {
                super::p256::ecdsa_verify(point, alg, &self.tbs, &self.signature, false)
            }
            _ => false,
        }
    }

    /// `checkIssued(other)`: `this.issuer === other.subject`.
    pub fn check_issued(&self, other: &Certificate) -> bool {
        self.issuer == other.subject
    }

    /// `checkHost(name)`: candidates are the SAN DNS names, or the subject CN when there are
    /// none; case-insensitive exact match or a `*.` wildcard matching exactly one label.
    /// Returns the *input* name on success.
    pub fn check_host(&self, name: &str) -> Option<String> {
        let host = name.to_lowercase();
        let mut candidates: Vec<String> = self.alt_names.iter().filter(|(t, _)| t == "DNS").map(|(_, v)| v.clone()).collect();
        if candidates.is_empty() {
            if let Some(cn) = self.subject.split('\n').find(|f| f.starts_with("CN=")) {
                candidates.push(cn[3..].to_string());
            }
        }
        for c in candidates {
            let pattern = c.to_lowercase();
            if pattern == host {
                return Some(name.to_string());
            }
            if let Some(suffix) = pattern.strip_prefix('*') {
                if pattern.starts_with("*.")
                    && host.ends_with(suffix)
                    && host.split('.').count() == pattern.split('.').count()
                {
                    return Some(name.to_string());
                }
            }
        }
        None
    }

    /// `checkEmail(email)`: case-insensitive match against SAN email entries.
    pub fn check_email(&self, email: &str) -> Option<String> {
        let target = email.to_lowercase();
        self.alt_names
            .iter()
            .any(|(t, v)| t == "email" && v.to_lowercase() == target)
            .then(|| email.to_string())
    }

    /// `checkIP(ip)`: string comparison against SAN IP entries (IPv6 must be written in the
    /// uncompressed 8-group form to match).
    pub fn check_ip(&self, ip: &str) -> Option<String> {
        let target = ip.to_lowercase();
        self.alt_names
            .iter()
            .any(|(t, v)| t == "IP Address" && v.to_lowercase() == target)
            .then(|| ip.to_string())
    }

    /// `toString()` / `toJSON()`: PEM.
    pub fn to_pem(&self) -> String {
        asn1::pem_encode("CERTIFICATE", &self.raw)
    }
}

/// Parsed Netscape SPKAC (`SignedPublicKeyAndChallenge`) for `crypto.Certificate`.
#[derive(Clone, Debug)]
pub struct Spkac {
    /// Challenge string bytes (`exportChallenge`).
    pub challenge: Vec<u8>,
    /// SubjectPublicKeyInfo DER (`exportPublicKey` PEM-encodes it as `PUBLIC KEY`).
    pub public_key_der: Vec<u8>,
    /// Encoded `PublicKeyAndChallenge` (the signed bytes).
    pub signed: Vec<u8>,
    pub signature: Vec<u8>,
    /// Digest per the same OID table as certificates (`None` → `verifySpkac` is false).
    pub signature_digest: Option<HashAlg>,
}

/// Parse an SPKAC the way the original's lenient `parseSpkac` does: input bytes that start
/// with `0x30` are DER; otherwise they are text — trimmed, an optional `SPKAC=` prefix
/// removed — and base64-decoded. (The JS layer first converts string inputs with the given
/// `encoding`, e.g. `'hex'`.) The SPKAC functions never throw: `exportChallenge` /
/// `exportPublicKey` return an empty Buffer and `verifySpkac` returns false on any error.
pub fn parse_spkac(input: &[u8]) -> Result<Spkac, CryptoError> {
    let der: Vec<u8> = if input.first() == Some(&0x30) {
        input.to_vec()
    } else {
        let text = String::from_utf8_lossy(input);
        let t = text.trim();
        let t = t.strip_prefix("SPKAC=").unwrap_or(t);
        asn1::base64_decode(t)
    };
    let outer = asn1::read_tlv(&der, 0)?;
    if outer.tag != asn1::TAG_SEQUENCE {
        return Err(asn1::malformed());
    }
    let kids = asn1::children(outer.content)?;
    let pkac = asn1::expect(kids.first(), asn1::TAG_SEQUENCE)?;
    let pk_kids = asn1::children(pkac.content)?;
    let spki = asn1::expect(pk_kids.first(), asn1::TAG_SEQUENCE)?;
    let challenge = pk_kids.get(1).ok_or_else(asn1::malformed)?;
    let alg = asn1::expect(kids.get(1), asn1::TAG_SEQUENCE)?;
    let alg_kids = asn1::children(alg.content)?;
    let oid = match alg_kids.first() {
        Some(a) if a.tag == asn1::TAG_OID => asn1::decode_oid(a.content),
        _ => String::new(),
    };
    let sig = asn1::expect(kids.get(2), asn1::TAG_BIT_STRING)?;
    Ok(Spkac {
        challenge: challenge.content.to_vec(),
        public_key_der: spki.raw(pkac.content).to_vec(),
        signed: pkac.raw(outer.content).to_vec(),
        signature: sig.content.get(1..).unwrap_or(&[]).to_vec(),
        signature_digest: signature_digest_for(&oid),
    })
}

/// `Certificate.verifySpkac(spkac)`.
pub fn verify_spkac(input: &[u8]) -> bool {
    let s = match parse_spkac(input) {
        Ok(s) => s,
        Err(_) => return false,
    };
    let alg = match s.signature_digest {
        Some(a) => a,
        None => return false,
    };
    match keys::parse_spki(&s.public_key_der) {
        Ok(AsymKey::RsaPublic(k)) => super::rsa::rsa_pkcs1v15_verify(&k, alg, &s.signed, &s.signature).unwrap_or(false),
        Ok(AsymKey::EcPublic { point }) => super::p256::ecdsa_verify(&point, alg, &s.signed, &s.signature, false),
        _ => false,
    }
}
