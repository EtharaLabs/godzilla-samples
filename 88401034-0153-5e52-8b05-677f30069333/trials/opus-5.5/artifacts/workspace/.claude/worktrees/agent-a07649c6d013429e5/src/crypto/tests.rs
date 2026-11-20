use super::test_vectors::*;
use super::*;

pub(crate) fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{:02x}", x)).collect()
}

pub(crate) fn unhex(s: &str) -> Vec<u8> {
    (0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap()).collect()
}

fn data(n: usize) -> Vec<u8> {
    (0..n).map(|i| ((i * 31 + 7) & 0xff) as u8).collect()
}

fn alg(name: &str) -> HashAlg {
    match name {
        "Md5" => HashAlg::Md5,
        "Sha1" => HashAlg::Sha1,
        "Sha224" => HashAlg::Sha224,
        "Sha256" => HashAlg::Sha256,
        "Sha384" => HashAlg::Sha384,
        "Sha512" => HashAlg::Sha512,
        "Sha512_224" => HashAlg::Sha512_224,
        "Sha512_256" => HashAlg::Sha512_256,
        _ => panic!("{}", name),
    }
}

#[test]
fn hash_vectors() {
    for (a, n, expect) in HASH_VECTORS {
        let d = data(*n);
        assert_eq!(hex(&digest(alg(a), &d)), *expect, "{} len {}", a, n);
        // Streaming in odd chunk sizes.
        for chunk in [1usize, 7, 63, 64, 65, 129] {
            let mut h = Hasher::new(alg(a));
            for c in d.chunks(chunk) {
                h.update(c);
            }
            assert_eq!(hex(&h.finalize()), *expect, "{} len {} chunk {}", a, n, chunk);
        }
        assert_eq!(digest(alg(a), &d).len(), alg(a).output_len());
    }
}

#[test]
fn hasher_copy() {
    let mut h = Hasher::new(HashAlg::Sha256);
    h.update(b"ab");
    let mut h2 = h.clone();
    h2.update(b"c");
    assert_eq!(hex(&h.finalize()), "fb8e20fc2e4c3f248c60c39bd652f3c1347298bb977b8b4d5903b85055620603");
    assert_eq!(hex(&h2.finalize()), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
}

#[test]
fn hmac_vectors() {
    for (a, kl, n, expect) in HMAC_VECTORS {
        let key: Vec<u8> = (0..*kl).map(|i| ((i * 7 + 3) & 0xff) as u8).collect();
        let d = data(*n);
        assert_eq!(hex(&hmac(alg(a), &key, &d)), *expect, "{} kl {} n {}", a, kl, n);
        let mut m = Hmac::new(alg(a), &key);
        for c in d.chunks(13) {
            m.update(c);
        }
        assert_eq!(hex(&m.finalize()), *expect);
    }
}

#[test]
fn pbkdf2_vectors() {
    for (a, pw, salt, it, kl, expect) in PBKDF2_VECTORS {
        assert_eq!(hex(&pbkdf2(alg(a), &unhex(pw), &unhex(salt), *it, *kl)), *expect, "{} it {}", a, it);
    }
    // iterations 0 behaves like 1 (original), keylen 0 -> empty
    assert_eq!(
        pbkdf2(HashAlg::Sha1, b"pw", b"salt", 0, 10),
        pbkdf2(HashAlg::Sha1, b"pw", b"salt", 1, 10)
    );
    assert_eq!(hex(&pbkdf2(HashAlg::Sha1, b"pw", b"salt", 1, 10)), "95c9338ea3a049dc400b");
    assert!(pbkdf2(HashAlg::Sha1, b"pw", b"salt", 1, 0).is_empty());
}

#[test]
fn hkdf_vectors() {
    for (a, ikm, salt, info, l, expect) in HKDF_VECTORS {
        assert_eq!(hex(&hkdf(alg(a), &unhex(ikm), &unhex(salt), &unhex(info), *l).unwrap()), *expect);
    }
    assert!(hkdf(HashAlg::Sha256, b"ikm", b"", b"", 255 * 32).is_ok());
    let e = hkdf(HashAlg::Sha256, b"ikm", b"", b"", 255 * 32 + 1).unwrap_err();
    assert_eq!(e.kind, ErrorKind::RangeError);
    assert_eq!(e.message, "hkdf: requested key length is too large");
    assert_eq!(hex(&hkdf(HashAlg::Sha256, b"ikm", b"", b"", 10).unwrap()), "d58e7c1c4394984eb3ca");
}

#[test]
fn names() {
    for (n, a) in [
        ("md5", HashAlg::Md5),
        ("MD5", HashAlg::Md5),
        ("sha-1", HashAlg::Sha1),
        ("SHA-256", HashAlg::Sha256),
        ("sHa384", HashAlg::Sha384),
        ("SHA512-224", HashAlg::Sha512_224),
        ("sha512-256", HashAlg::Sha512_256),
    ] {
        assert_eq!(hash_alg_from_name(n), Some(a), "{}", n);
    }
    for n in ["sha224", "RSA-SHA256", "sha3-256", "sha-512/256", " sha256", "md4", "ripemd160", ""] {
        assert_eq!(hash_alg_from_name(n), None, "{}", n);
    }
    assert_eq!(sign_hash_alg_from_name("RSA-SHA256"), Some(HashAlg::Sha256));
    assert_eq!(sign_hash_alg_from_name("ecdsa-with-SHA1"), Some(HashAlg::Sha1));
    assert_eq!(sign_hash_alg_from_name("rsa-id-sha256"), Some(HashAlg::Sha256));
    assert_eq!(sign_hash_alg_from_name("sha512-256WithRSAEncryption"), Some(HashAlg::Sha512_256));
    assert_eq!(normalize_digest_name("id-rsa-sha256"), "rsa-sha256");
    assert_eq!(normalize_digest_name("id-ecdsa-with-sha256"), "ecdsa-with-sha256");
    assert_eq!(normalize_digest_name("ecdsa-with-id-sha256"), "sha256");
    assert_eq!(
        unsupported_digest_error("SHA224").message,
        "Digest method not supported: SHA224 (lumen supports md5, sha1, sha256, sha384, sha512, sha512-224, sha512-256)"
    );
}

#[test]
fn random_basics() {
    let a = random_bytes(64);
    let b = random_bytes(64);
    assert_ne!(a, b);
    let big = random_bytes(10000);
    assert_eq!(big.len(), 10000);
    let u = random_uuid();
    assert_eq!(u.len(), 36);
    let bytes = u.as_bytes();
    assert_eq!(bytes[14], b'4');
    assert!(matches!(bytes[19], b'8' | b'9' | b'a' | b'b'));
    for _ in 0..1000 {
        let v = random_int(5, 8).unwrap();
        assert!((5..8).contains(&v));
        assert_eq!(random_int(0, 1), Some(0));
        let w = random_int(-(1 << 52), 1 << 52).unwrap();
        assert!((-(1i64 << 52)..(1i64 << 52)).contains(&w));
    }
    assert_eq!(random_int(5, 5), None);
    assert!(timing_safe_eq(b"abc", b"abc"));
    assert!(!timing_safe_eq(b"abc", b"abd"));
    assert!(!timing_safe_eq(b"abc", b"ab"));
}

#[test]
fn scrypt_vectors() {
    for (pw, salt, n, r, p, kl, expect) in SCRYPT_VECTORS {
        assert_eq!(hex(&scrypt(&unhex(pw), &unhex(salt), *n, *r, *p, *kl).unwrap()), *expect, "N {} r {} p {}", n, r, p);
    }
    assert_eq!(scrypt(b"pw", b"salt", 1000, 8, 1, 16).unwrap_err().message, "Invalid scrypt params");
    assert!(scrypt_check_params(16, 1, 1, 128 + 128 * 18).is_ok());
    let e = scrypt_check_params(16, 1, 1, 128 + 128 * 18 - 1).unwrap_err();
    assert_eq!(e.code, Some("ERR_CRYPTO_INVALID_SCRYPT_PARAMS"));
    assert_eq!(e.message, "Invalid scrypt params: error:030000AC:digital envelope routines::memory limit exceeded");
    assert!(scrypt_check_params(1 << 20, 8, 1, SCRYPT_DEFAULT_MAXMEM).is_err());
    assert!(scrypt_check_params(1 << 14, 8, 1, SCRYPT_DEFAULT_MAXMEM).is_ok());
    assert!(scrypt_check_params(1, 8, 1, SCRYPT_DEFAULT_MAXMEM).is_err());
}

#[test]
fn aes_fips197() {
    // FIPS-197 appendix C.
    let pt = unhex("00112233445566778899aabbccddeeff");
    for (key, ct) in [
        ("000102030405060708090a0b0c0d0e0f", "69c4e0d86a7b0430d8cdb78070b4c55a"),
        ("000102030405060708090a0b0c0d0e0f1011121314151617", "dda97ca4864cdfe06eaf70a0ec0d7191"),
        ("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f", "8ea2b7ca516745bfeafc49904b496089"),
    ] {
        let aes = Aes::new(&unhex(key)).unwrap();
        let mut b = [0u8; 16];
        b.copy_from_slice(&pt);
        aes.encrypt_block(&mut b);
        assert_eq!(hex(&b), ct);
        aes.decrypt_block(&mut b);
        assert_eq!(hex(&b), hex(&pt));
    }
}

#[test]
fn cipher_vectors_from_original() {
    use super::test_vectors_cipher::CIPHER_VECTORS;
    for (name, key, iv, decrypt, pad, aad, tag_len, chunks, outs, fin, tag) in CIPHER_VECTORS {
        let iv_bytes = if *iv == "-" { None } else { Some(unhex(iv)) };
        let mut c = CipherCtx::new(name, &unhex(key), iv_bytes.as_deref(), *decrypt).unwrap();
        if *tag_len != 0 {
            c.set_auth_tag_length(*tag_len).unwrap();
        }
        if !*pad {
            c.set_auto_padding(false);
        }
        if *decrypt && name.ends_with("gcm") {
            c.set_auth_tag(&unhex(tag)).unwrap();
        }
        if !aad.is_empty() {
            c.set_aad(&unhex(aad)).unwrap();
        }
        for (i, ch) in chunks.iter().enumerate() {
            assert_eq!(hex(&c.update(&unhex(ch)).unwrap()), outs[i], "{} dec={} chunk {}", name, decrypt, i);
        }
        match c.finalize() {
            Ok(f) => assert_eq!(hex(&f), *fin, "{} dec={} final", name, decrypt),
            Err(e) => assert_eq!(format!("ERR:{}", e.message), *fin, "{} dec={} final err", name, decrypt),
        }
        if !*decrypt && name.ends_with("gcm") {
            assert_eq!(hex(&c.auth_tag().unwrap()), *tag, "{} tag", name);
        }
    }
}

#[test]
fn cipher_semantics() {
    let k16 = [1u8; 16];
    let iv16 = [4u8; 16];
    let iv12 = [5u8; 12];
    // errors at construction
    let e = CipherCtx::new("aes-128-cfb", &k16, Some(&iv16), false).err().unwrap();
    assert_eq!(e.message, "node:crypto cipher 'aes-128-cfb' is not supported in lumen (aes-{128,192,256}-{ecb,cbc,ctr,gcm} only)");
    assert_eq!(e.kind, ErrorKind::Error);
    let e = CipherCtx::new("aes-128-cbc", &[0u8; 24], Some(&iv16), false).err().unwrap();
    assert_eq!((e.kind, e.code, e.message.as_str()), (ErrorKind::RangeError, Some("ERR_CRYPTO_INVALID_KEYLEN"), "Invalid key length"));
    let e = CipherCtx::new("aes-128-cbc", &k16, Some(&iv12), false).err().unwrap();
    assert_eq!((e.kind, e.code, e.message.as_str()), (ErrorKind::TypeError, Some("ERR_CRYPTO_INVALID_IV"), "Invalid initialization vector"));
    assert!(CipherCtx::new("aes-128-cbc", &k16, None, false).is_err());
    assert!(CipherCtx::new("aes-128-ecb", &k16, Some(&iv16), false).is_err());
    assert!(CipherCtx::new("aes-128-ecb", &k16, Some(&[]), false).is_ok());
    assert!(CipherCtx::new("aes-128-gcm", &k16, Some(&[]), false).is_err());
    assert!(CipherCtx::new("AES128", &k16, Some(&iv16), false).is_ok());
    assert_eq!(cipher_info("aes256").unwrap().name, "aes-256-cbc");
    assert!(cipher_info("id-aes128-gcm").is_none());
    // ecb known value (original): key 01*16, '' -> 68434d37...
    let mut c = CipherCtx::new("aes-128-ecb", &k16, None, false).unwrap();
    assert_eq!(hex(&c.finalize().unwrap()), "68434d37d7f69f0e03b75bb15bc94b6c");
    // CBC chunk sizes
    let mut c = CipherCtx::new("aes-128-cbc", &k16, Some(&iv16), false).unwrap();
    let lens: Vec<usize> = [5, 11, 17, 15].iter().map(|n| c.update(&vec![0u8; *n]).unwrap().len()).collect();
    assert_eq!(lens, vec![0, 16, 16, 16]);
    assert_eq!(c.finalize().unwrap().len(), 16);
    let e = c.finalize().unwrap_err();
    assert_eq!((e.code, e.message.as_str()), (Some("ERR_CRYPTO_INVALID_STATE"), "Invalid state"));
    let e = c.update(b"a").unwrap_err();
    assert_eq!((e.code, e.message.as_str()), (None, "Trying to add data in unsupported state"));
    // CTR full 128-bit wrap (original)
    let mut c = CipherCtx::new("aes-128-ctr", &k16, Some(&[0xffu8; 16]), false).unwrap();
    assert_eq!(
        hex(&c.update(&[0u8; 32]).unwrap()),
        "6ad77cdab9adb3bfed21ef94210e121eb6aeaffa752dc08b51639731761aed00"
    );
    let mut iv = [0u8; 16];
    iv[12..].fill(0xff);
    let mut c = CipherCtx::new("aes-128-ctr", &k16, Some(&iv), false).unwrap();
    assert_eq!(
        hex(&c.update(&[0u8; 32]).unwrap()),
        "4645bdff0845e4e7243a9db4f2c47ecd3986cefb702f4d92f30060c00c65038e"
    );
    let mut iv = [0u8; 16];
    iv[8..].fill(0xff);
    let mut c = CipherCtx::new("aes-128-ctr", &k16, Some(&iv), false).unwrap();
    assert_eq!(
        hex(&c.update(&[0u8; 32]).unwrap()),
        "42a4f8a05529dba3f30567ea44786e23b020293487b2c42bdbf3c58494c64e12"
    );
    // GCM: original values
    let mut c = CipherCtx::new("aes-128-gcm", &k16, Some(&iv12), false).unwrap();
    c.set_aad(b"aad").unwrap();
    assert_eq!(hex(&c.update(b"plaintext").unwrap()), "03ca64c6ed4e977982");
    assert!(c.auth_tag().is_err());
    c.finalize().unwrap();
    assert_eq!(hex(&c.auth_tag().unwrap()), "103bb40376684ab00faf7d1906dd257c");
    let e = c.set_aad(b"x").unwrap_err();
    assert_eq!(e.message, "Invalid state for operation setAAD");
    // gcm iv 16 / 64 / 1
    for (ivv, ct, tag) in [
        (vec![4u8; 16], "c47f1ccfbd", "533b47146e053cd369b6bec082061167"),
        (vec![9u8; 64], "d723ad9e2f", "95533af399e7c6b11d264e03c0641e15"),
    ] {
        let mut c = CipherCtx::new("aes-128-gcm", &k16, Some(&ivv), false).unwrap();
        assert_eq!(hex(&c.update(b"hello").unwrap()), ct);
        c.finalize().unwrap();
        assert_eq!(hex(&c.auth_tag().unwrap()), tag);
    }
    let mut c = CipherCtx::new("aes-128-gcm", &k16, Some(&[0u8; 1]), false).unwrap();
    c.update(b"a").unwrap();
    c.finalize().unwrap();
    assert_eq!(hex(&c.auth_tag().unwrap()), "9f00c0ecbeacaf105123191a7ce4e0d9");
    // tag lengths
    let mut c = CipherCtx::new("aes-128-gcm", &k16, Some(&iv12), false).unwrap();
    assert_eq!(c.set_auth_tag_length(5).unwrap_err().message, "Invalid authentication tag length: 5");
    let mut d = CipherCtx::new("aes-128-gcm", &k16, Some(&iv12), true).unwrap();
    assert_eq!(d.set_auth_tag(&[0u8; 3]).unwrap_err().message, "Invalid authentication tag length: 3");
    assert!(d.set_auth_tag(&[0u8; 4]).is_ok());
    d.update(b"abc").unwrap();
    assert_eq!(d.finalize().unwrap_err().message, "Unsupported state or unable to authenticate data");
    assert_eq!(d.set_auth_tag(&[0u8; 16]).unwrap_err().message, "Invalid state for operation setAuthTag");
    // AAD accumulation
    let mut a = CipherCtx::new("aes-128-gcm", &k16, Some(&iv12), false).unwrap();
    a.set_aad(b"a").unwrap();
    a.set_aad(b"b").unwrap();
    a.update(b"a").unwrap();
    a.finalize().unwrap();
    assert_eq!(hex(&a.auth_tag().unwrap()), "aa34b3e0525187773e16a337ea59ec00");
    // padding toggles (original semantics)
    let mut e = CipherCtx::new("aes-128-cbc", &k16, Some(&iv16), false).unwrap();
    e.set_auto_padding(false);
    let mut ct = e.update(&[0u8; 32]).unwrap();
    ct.extend(e.finalize().unwrap());
    assert_eq!(hex(&ct), "5f018e7047fcac18c93b7665bdef49dcabf1ab15766edfbb6d2d6c92b669240f");
    let mut d = CipherCtx::new("aes-128-cbc", &k16, Some(&iv16), true).unwrap();
    assert_eq!(d.update(&ct).unwrap().len(), 16);
    d.set_auto_padding(false);
    assert_eq!(d.finalize().unwrap_err().code, Some("ERR_OSSL_WRONG_FINAL_BLOCK_LENGTH"));
    let mut d = CipherCtx::new("aes-128-cbc", &k16, Some(&iv16), true).unwrap();
    assert_eq!(d.finalize().unwrap_err().code, Some("ERR_OSSL_WRONG_FINAL_BLOCK_LENGTH"));
    let mut d = CipherCtx::new("aes-128-cbc", &k16, Some(&iv16), true).unwrap();
    d.update(&[0u8; 32]).unwrap();
    assert_eq!(d.finalize().unwrap_err().code, Some("ERR_OSSL_BAD_DECRYPT"));
    // one-shot helpers
    let (ct, tag) = aes_gcm_encrypt(&k16, &iv12, b"aad", b"plaintext").unwrap();
    assert_eq!(hex(&ct), "03ca64c6ed4e977982");
    assert_eq!(aes_gcm_decrypt(&k16, &iv12, b"aad", &ct, &tag).unwrap(), b"plaintext");
    assert!(aes_gcm_decrypt(&k16, &iv12, b"aaX", &ct, &tag).is_err());
    assert_eq!(cipher_names().len(), 12);
}

#[test]
fn blake2b_vectors() {
    for (n, l, expect) in BLAKE2B_VECTORS {
        let d = data(*l);
        assert_eq!(hex(&blake2b(*n, &d)), *expect, "n {} len {}", n, l);
        let mut h = Blake2b::new(*n);
        for c in d.chunks(50) {
            h.update(c);
        }
        assert_eq!(hex(&h.finalize()), *expect);
    }
}

fn a2(variant: &str, msg: &[u8], nonce: &[u8], secret: &[u8], ad: &[u8], p: u32, t: u32, m: u32, passes: u32) -> String {
    let v = Argon2Variant::from_name(variant).unwrap();
    let params = Argon2Params {
        message: msg,
        nonce,
        secret,
        associated_data: ad,
        parallelism: p,
        tag_length: t,
        memory: m,
        passes,
        version: 0x13,
    };
    hex(&argon2(v, &params).unwrap())
}

#[test]
fn argon2_vectors() {
    // RFC 9106 §5 test vectors (also what the original returns).
    let (msg, nonce, secret, ad) = ([1u8; 32], [2u8; 16], [3u8; 8], [4u8; 12]);
    assert_eq!(a2("argon2d", &msg, &nonce, &secret, &ad, 4, 32, 32, 3), "512b391b6f1162975371d30919734294f868e3be3984f3c1a13a4db9fabe4acb");
    assert_eq!(a2("argon2i", &msg, &nonce, &secret, &ad, 4, 32, 32, 3), "c814d9d1dc7f37aa13f0d77f2494bda1c8de6b016dd388d29952a4c4672b6ce8");
    assert_eq!(a2("argon2id", &msg, &nonce, &secret, &ad, 4, 32, 32, 3), "0d640df58d78766c08c037a34a8b53c9d01ef0452d75b65eb52520e96b01e659");
    // Values produced by the original binary.
    let (pw, salt) = (b"pw".as_slice(), b"saltsalt".as_slice());
    assert_eq!(a2("argon2id", pw, salt, b"", b"", 1, 16, 64, 1), "a9a5ae58d8d696c9a5934bf0480e8f07");
    assert_eq!(a2("argon2id", pw, salt, b"", b"", 1, 16, 8, 1), "fe970656dd1de4455d6595d52d7b806b");
    assert_eq!(a2("argon2id", pw, salt, b"", b"", 1, 16, 64, 2), "9ac2fa02abf8e90042b213f76bb02ae2");
    assert_eq!(a2("argon2id", pw, salt, b"", b"", 1, 4, 64, 2), "1c277489");
    assert_eq!(
        a2("argon2id", pw, salt, b"", b"", 1, 100, 64, 2),
        "f331d131e47abfb843732fae58ee23aaa1dafb65a1e9ba355375ee065953adbf4316a06c4b7a1651a918f87133e74b8295b45c2e6290f6fd4f27837d707d95b2afcdb12d40855ecd803b6a34b331e811d7c6321922cbf2eee63cc572080f3323fd7394f1"
    );
    assert_eq!(a2("argon2id", pw, salt, b"", b"", 1, 16, 13, 1), "f98114fabcc1783519627de05fdc2af2");
    assert_eq!(a2("argon2id", pw, salt, b"", b"", 2, 16, 17, 1), "c20ae62db994e53bbfd4de7b4825774d");
    assert_eq!(a2("argon2id", pw, salt, b"abc", b"", 1, 16, 64, 1), "1373c72d8fec3764ad3e2db95a0cda1f");
    assert_eq!(a2("argon2id", pw, salt, b"", b"abc", 1, 16, 64, 1), "f2acb709a9f3678322703040d6ee2b1a");
    assert_eq!(a2("argon2id", b"", salt, b"", b"", 1, 16, 64, 1), "0f808e7503865c1ed212b74beced4087");
    assert_eq!(a2("argon2id", pw, &[0u8; 8], b"", b"", 1, 16, 64, 1), "bce45d5a360ad434485d29e4d3266605");
    assert_eq!(a2("argon2id", pw, salt, b"", b"", 3, 16, 24, 1), "72450b813182aaa62d6b27f41726f603");
    assert_eq!(a2("argon2id", pw, salt, b"", b"", 3, 16, 37, 1), "8cb23656e4adbd0baae48e9dd0b8d3a9");
    assert_eq!(a2("argon2i", pw, salt, b"", b"", 2, 16, 32, 3), "9d988de258ec50646a27e09f678c65a3");
    assert_eq!(a2("argon2d", pw, salt, b"", b"", 2, 16, 32, 3), "3a6adec07db3a6c62d50ca31c95fc402");
    assert_eq!(
        a2("argon2id", pw, salt, b"", b"", 4, 64, 256, 2),
        "0e8fc8215f3e1e8af6650226a25f0d459c558e68ad63a3d2efc3be36913c932c721c25cef17a8378680ba2e339f2fbbd9fa12390d1655f381dd26ebd317319fb"
    );
    assert_eq!(
        a2("argon2id", pw, salt, b"", b"", 1, 65, 64, 1),
        "27813870b75005d1c0391e00a45c3ca5c33ea483f85f5de6427ee1db22d62c16b340a565d0eeb9edfa897f8fd5a2ad5acfd0dbf12d6782ac4d37863f5b7103a21e"
    );
    assert_eq!(
        a2("argon2i", pw, salt, b"", b"", 1, 200, 1024, 1),
        "704b4ff1219750057a6ce34e0a42690a1e3a0762ac064bfbf9a3d0bc01ea57ba10fa728f37434392e85b881675751ad2b22487cb899b30f16f23a127109e15fdcea80be930b6eae2f952e5345b8e6f557c8beed5eecd4bb5551068e570a6eb0538c940606543ce566f52049711df42b8ba5d1c53d0e92a4beb89d224ea851b10650ab065ce79db126a57e9e83fd541d3f83d9209a717e794b8acc87ef8c6ead1a342676fd0a1684fa20510f70096c9715341cbb7f514a0ccdcd5e24d6629b92878c6df4524c2e517"
    );
    let x = "x".repeat(1000);
    let y = "y".repeat(100);
    let z = "z".repeat(50);
    let w = "w".repeat(70);
    assert_eq!(a2("argon2id", x.as_bytes(), y.as_bytes(), z.as_bytes(), w.as_bytes(), 3, 16, 300, 4), "4420fa5a654c2f1e862ecb7b183d9cc1");
    assert_eq!(a2("argon2i", pw, salt, b"", b"", 1, 16, 600, 2), "0e6328189e0068f30e52ebdc7518dc4d");
    assert_eq!(a2("argon2id", pw, salt, b"", b"", 1, 16, 1100, 2), "0a32b7a18eb5e929af51b290ce80d8f4");
}

#[test]
fn bigint_vectors() {
    use super::test_vectors_bigint::*;
    let h = |s: &str| BigUint::from_hex(s).unwrap();
    for (a, b, prod, q, r, sum, diff) in BIGINT_VECTORS {
        let (a, b) = (h(a), h(b));
        assert_eq!(a.mul(&b).to_hex(), *prod);
        let (qq, rr) = a.divrem(&b);
        assert_eq!(qq.to_hex(), *q, "a={:?} b={:?}", a, b);
        assert_eq!(rr.to_hex(), *r);
        assert_eq!(a.add(&b).to_hex(), *sum);
        match a.checked_sub(&b) {
            Some(d) => assert_eq!(d.to_hex(), *diff),
            None => assert_eq!(*diff, "-"),
        }
        assert_eq!(BigUint::from_bytes_be(&a.to_bytes_be()), a);
        assert_eq!(a.shl(77).shr(77), a);
        assert_eq!(BigUint::from_decimal(&a.to_decimal()).unwrap(), a);
    }
    for (a, e, m, r) in MODPOW_VECTORS {
        assert_eq!(h(a).modpow(&h(e), &h(m)).to_hex(), *r, "modpow");
    }
    for (a, m, inv) in MODINV_VECTORS {
        match h(a).modinv(&h(m)) {
            Some(v) => assert_eq!(v.to_hex(), *inv),
            None => assert_eq!(*inv, "-"),
        }
    }
    assert_eq!(BigUint::from_u64(255).to_bytes_be_padded(3), vec![0, 0, 255]);
    assert!(BigUint::zero().to_bytes_be().is_empty());
    assert_eq!(BigUint::from_hex("0").unwrap(), BigUint::zero());
}

fn b64u(s: &str) -> Vec<u8> {
    super::asn1::base64_decode(s)
}

fn arr32(v: &[u8]) -> [u8; 32] {
    let mut a = [0u8; 32];
    a.copy_from_slice(v);
    a
}

#[test]
fn ed25519_vectors() {
    use super::curve25519::*;
    // RFC 8032 test 1 and 2
    let sk = arr32(&unhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"));
    assert_eq!(hex(&ed25519_public_key(&sk)), "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a");
    let sig = ed25519_sign(&sk, b"");
    assert_eq!(hex(&sig), "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b");
    assert!(ed25519_verify(&ed25519_public_key(&sk), b"", &sig));
    let sk2 = arr32(&unhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"));
    let sig2 = ed25519_sign(&sk2, &[0x72]);
    assert_eq!(hex(&sig2), "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00");
    let mut bad = sig2;
    bad[5] ^= 1;
    assert!(!ed25519_verify(&ed25519_public_key(&sk2), &[0x72], &bad));
    assert!(!ed25519_verify(&ed25519_public_key(&sk2), &[0x73], &sig2));
    // Original binary values.
    let seed = arr32(&b64u("NF8xANRqJAOHLeZKt6WHRMUr-sBEvWbwMpG50y-9QlI"));
    assert_eq!(ed25519_public_key(&seed).to_vec(), b64u("P9CtSwbhh57CdbDRk-2pEuKtpZEo9k7NyJD-f0tvM_4"));
    assert_eq!(hex(&ed25519_sign(&seed, b"hello")), "eee090436de56ef8e659e94614e92dd0c5691965bfef092dcb11aacbc85b4d67310248b4e90dcc31dfe955964f69174c0f81836768193ebc9a2e3d8dfafac10e");
}

#[test]
fn x25519_vectors() {
    use super::curve25519::*;
    let k = arr32(&unhex("a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4"));
    let u = arr32(&unhex("e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c"));
    assert_eq!(hex(&x25519(&k, &u)), "c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552");
    // RFC 7748 6.1
    let a = arr32(&unhex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"));
    let b = arr32(&unhex("5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb"));
    assert_eq!(hex(&x25519_public_key(&a)), "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a");
    assert_eq!(hex(&x25519(&a, &x25519_public_key(&b))), "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742");
    let d = arr32(&b64u("sGe2Kn_2E6fj0Xedua4aEqCV4WMcjdFCUMuZ54JwXrY"));
    let pubk = x25519_public_key(&d);
    assert_eq!(pubk.to_vec(), b64u("wQ2HUYNRI4TIpQ3qxnUZyqPRl8WWEbCL7ZXxgoeW4SQ"));
    assert_eq!(hex(&x25519(&d, &pubk)), "3584540326bb96d899cecc4075dac7ab2150976db56d34ff5aaacc38d562be46");
}

#[test]
fn p256_vectors() {
    use super::p256::*;
    let d = unhex("c88f01f510d9ac3f70a292daa2316de544e9aab8afe84049c62a9c57862d1433");
    let pubk = public_from_private(&d).unwrap();
    assert_eq!(hex(&pubk), "04dad0b65394221cf9b051e1feca5787d098dfe637fc90b9ef945d0c37725811805271a0461cdb8252d61f1c456fa3e59ab1f45b33accf5f58389e0577b8990bb3");
    let pt = decode_point(&pubk).unwrap();
    assert_eq!(hex(&encode_point(&pt, PointFormat::Compressed)), "03dad0b65394221cf9b051e1feca5787d098dfe637fc90b9ef945d0c3772581180");
    assert_eq!(&hex(&encode_point(&pt, PointFormat::Hybrid))[..4], "07da");
    let comp = encode_point(&pt, PointFormat::Compressed);
    assert_eq!(decode_point(&comp).unwrap(), pt);
    assert_eq!(hex(&ecdh(&d, &pubk).unwrap()), "a692794c8e0ac71ec27eb1b5cebc40a2b196bb6fddd50b44010d5034ee18493b");
    assert_eq!(hex(&public_from_private(&[1]).unwrap()), "046b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c2964fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5");
    assert_eq!(hex(&encode_point(&scalar_mul_base(&[2]), PointFormat::Compressed)), "037cf27b188d034f7e8a52380304b51ac3c08969e277f21b35a60b48fc47669978");
    assert!(public_from_private(&[0]).is_err());
    assert!(public_from_private(&[0xff; 32]).is_err());
    // compressed with wrong parity flips y
    let mut c2 = comp.clone();
    c2[0] ^= 1;
    assert_eq!(hex(&encode_point(&decode_point(&c2).unwrap(), PointFormat::Uncompressed)), "04dad0b65394221cf9b051e1feca5787d098dfe637fc90b9ef945d0c3772581180ad8e5fb8e3247dae29e0e3ba905c1a654e0ba4cd5330a0a7c761fa884766f44c");
    let mut x5 = vec![2u8];
    x5.extend_from_slice(&[0u8; 31]);
    x5.push(5);
    assert_eq!(hex(&encode_point(&decode_point(&x5).unwrap(), PointFormat::Uncompressed)), "040000000000000000000000000000000000000000000000000000000000000005459243b9aa581806fe913bce99817ade11ca503c64d9a3c533415c083248fbcc");
    assert_eq!(hex(&ecdh(&d, &x5).unwrap()), "eb3c22782b1adddb15b360d833e4d29b816b549aed8547d8665dfd8d9ddde8dc");
    assert_eq!(decode_point(&[0]).unwrap_err().message, "crypto: unsupported EC point encoding");
    let mut bad = pubk.clone();
    bad[64] ^= 1;
    assert_eq!(decode_point(&bad).unwrap_err().message, "crypto: EC point is not on the curve");
    let mut hy = encode_point(&pt, PointFormat::Hybrid);
    hy[0] ^= 1;
    assert_eq!(decode_point(&hy).unwrap_err().message, "crypto: invalid hybrid EC point encoding");
    // ECDSA round trips
    for alg in [HashAlg::Sha256, HashAlg::Sha1, HashAlg::Sha512, HashAlg::Md5] {
        for p1363 in [false, true] {
            let sig = ecdsa_sign(&d, alg, b"hello world", p1363).unwrap();
            assert!(ecdsa_verify(&pubk, alg, b"hello world", &sig, p1363));
            assert!(!ecdsa_verify(&pubk, alg, b"hello worle", &sig, p1363));
        }
    }
    let (dd, pp) = generate_keypair();
    assert_eq!(public_from_private(&dd).unwrap(), pp);
    // Original-produced ECDH between JWK keys.
    let ed = b64u("weTIJvmDKUCYvLuW5JA8x8exKJ0PqkW4L2qbBxcyDC8");
    let mut pt2 = vec![4u8];
    pt2.extend(b64u("ERemROMgg4ENVdfWgETXRUlHcdWroE-5gIvIGSRtoC8"));
    pt2.extend(b64u("L_gHoJ1x1ezotLPjjlalWI2NEIORN1wug_UEG1TzlKg"));
    assert_eq!(public_from_private(&ed).unwrap(), pt2);
    assert_eq!(hex(&ecdh(&ed, &pt2).unwrap()), "2760fed2e7bde005db4df718a2ae97dab3f9dedb82ce9294c229c6d023fe01f2");
}

#[test]
fn rsa_and_key_formats() {
    use super::keys::*;
    use super::rsa::*;
    use super::test_vectors_asym::*;
    let (label, der) = super::asn1::pem_decode(RSA_PKCS8_PEM).unwrap();
    assert_eq!(label, "PRIVATE KEY");
    let key = parse_private_key(&der, Some(&label), None).unwrap();
    assert_eq!(key.kind(), KeyKind::Rsa);
    assert_eq!(hex(&key.export_pkcs1().unwrap()), RSA_PKCS1_DER);
    assert_eq!(key.export_pkcs8().unwrap(), der);
    assert_eq!(super::asn1::pem_encode("PRIVATE KEY", &key.export_pkcs8().unwrap()), RSA_PKCS8_PEM);
    assert_eq!(hex(&key.export_spki()), RSA_SPKI_DER);
    assert_eq!(hex(&key.to_public().export_pkcs1().unwrap()), RSA_PUB_PKCS1_DER);
    let jwk = key.jwk_fields();
    let expected: Vec<(String, String)> = RSA_JWK.iter().map(|(a, b)| (a.to_string(), b.to_string())).collect();
    let got: Vec<(String, String)> = jwk.iter().map(|(a, b)| (a.to_string(), b.clone())).collect();
    assert_eq!(got, expected);
    let from_jwk = AsymKey::from_jwk(&|n: &str| RSA_JWK.iter().find(|(k, _)| *k == n).map(|(_, v)| v.to_string()), true).unwrap();
    assert_eq!(from_jwk, key);
    assert_eq!(parse_private_key(&unhex(RSA_PKCS1_DER), Some("RSA PRIVATE KEY"), None).unwrap(), key);
    assert_eq!(parse_public_key(&unhex(RSA_SPKI_DER), Some("PUBLIC KEY"), None).unwrap(), key.to_public());
    assert_eq!(parse_public_key(&unhex(RSA_PUB_PKCS1_DER), None, Some("pkcs1")).unwrap(), key.to_public());
    assert_eq!(parse_public_key(&der, Some("PRIVATE KEY"), None).unwrap(), key.to_public());
    let priv_k = match &key {
        AsymKey::RsaPrivate(k) => k.clone(),
        _ => unreachable!(),
    };
    let pubk = priv_k.public_key();
    let msg = b"hello world";
    for (a, sig) in RSA_SIGS {
        let alg = hash_alg_from_name(a).unwrap();
        assert_eq!(hex(&rsa_pkcs1v15_sign(&priv_k, alg, msg).unwrap()), *sig, "{}", a);
        assert!(rsa_pkcs1v15_verify(&pubk, alg, msg, &unhex(sig)).unwrap());
        assert!(!rsa_pkcs1v15_verify(&pubk, alg, b"hello worle", &unhex(sig)).unwrap());
    }
    assert_eq!(
        rsa_pkcs1v15_sign(&priv_k, HashAlg::Sha512_224, msg).unwrap_err().message,
        "RSA PKCS#1 v1.5 digest 'sha512-224' is not supported in lumen"
    );
    // Without CRT parameters the result must be identical.
    let no_crt = RsaPrivateKey { p: BigUint::zero(), q: BigUint::zero(), dp: BigUint::zero(), dq: BigUint::zero(), qi: BigUint::zero(), ..priv_k.clone() };
    assert_eq!(hex(&rsa_pkcs1v15_sign(&no_crt, HashAlg::Sha256, msg).unwrap()), RSA_SIGS[2].1);
    for (a, sig) in RSA_PSS0_SIGS {
        let alg = hash_alg_from_name(a).unwrap();
        assert_eq!(hex(&rsa_pss_sign(&priv_k, alg, msg, 0).unwrap()), *sig, "pss {}", a);
        assert!(rsa_pss_verify(&pubk, alg, msg, &unhex(sig), None));
        assert!(rsa_pss_verify(&pubk, alg, msg, &unhex(sig), Some(0)));
        assert!(!rsa_pss_verify(&pubk, alg, msg, &unhex(sig), Some(1)));
    }
    for (a, s, sig) in RSA_PSS_RANDOM {
        let alg = hash_alg_from_name(a).unwrap();
        assert!(rsa_pss_verify(&pubk, alg, msg, &unhex(sig), None));
        assert!(rsa_pss_verify(&pubk, alg, msg, &unhex(sig), Some(*s as i64)));
        assert!(!rsa_pss_verify(&pubk, alg, msg, &unhex(sig), Some(*s as i64 + 1)));
        let mine = rsa_pss_sign(&priv_k, alg, msg, *s as i64).unwrap();
        assert!(rsa_pss_verify(&pubk, alg, msg, &mine, Some(*s as i64)));
    }
    // default (digest length) and max salt
    let s1 = rsa_pss_sign(&priv_k, HashAlg::Sha256, msg, PSS_SALTLEN_DIGEST).unwrap();
    assert!(rsa_pss_verify(&pubk, HashAlg::Sha256, msg, &s1, Some(32)));
    let s2 = rsa_pss_sign(&priv_k, HashAlg::Sha256, msg, PSS_SALTLEN_MAX_OR_AUTO).unwrap();
    assert!(rsa_pss_verify(&pubk, HashAlg::Sha256, msg, &s2, Some(128 - 32 - 2)));
    assert_eq!(rsa_pss_sign(&priv_k, HashAlg::Sha256, msg, 1000).unwrap_err().message, "RSA-PSS: salt too long for the modulus");
    for (a, l, ct) in RSA_OAEP_CTS {
        let alg = hash_alg_from_name(a).unwrap();
        assert_eq!(rsa_oaep_decrypt(&priv_k, alg, l.as_bytes(), &unhex(ct)).unwrap(), msg, "oaep {}", a);
        let mine = rsa_oaep_encrypt(&pubk, alg, l.as_bytes(), msg).unwrap();
        assert_eq!(rsa_oaep_decrypt(&priv_k, alg, l.as_bytes(), &mine).unwrap(), msg);
        assert_eq!(rsa_oaep_decrypt(&priv_k, alg, b"zz", &unhex(ct)).unwrap_err().message, "RSA-OAEP: decryption error");
    }
    assert_eq!(rsa_oaep_encrypt(&pubk, HashAlg::Sha1, b"", &[0u8; 87]).unwrap_err().message, "RSA-OAEP: message too long");
    assert!(rsa_oaep_encrypt(&pubk, HashAlg::Sha1, b"", &[0u8; 86]).is_ok());
    assert_eq!(rsa_oaep_decrypt(&priv_k, HashAlg::Sha1, b"", &[0xffu8; 128]).unwrap_err().message, "RSA: data too large for the modulus");
    assert_eq!(rsa_pkcs1v15_decrypt(&priv_k, &unhex(RSA_PKCS1_CT)).unwrap(), msg);
    let ct = rsa_pkcs1v15_encrypt(&pubk, msg).unwrap();
    assert_eq!(rsa_pkcs1v15_decrypt(&priv_k, &ct).unwrap(), msg);
    assert_eq!(rsa_pkcs1v15_encrypt(&pubk, &[1u8; 118]).unwrap_err().message, "RSA-PKCS1: message too long");
    assert_eq!(hex(&rsa_private_encrypt_pkcs1(&priv_k, msg).unwrap()), RSA_PRIV_ENC);
    assert_eq!(rsa_public_decrypt_pkcs1(&pubk, &unhex(RSA_PRIV_ENC)).unwrap(), msg);
    assert_eq!(rsa_public_decrypt_pkcs1(&pubk, &[1u8; 10]).unwrap_err().message, "publicDecrypt: decryption error");
    let block = [1u8; 128];
    let enc = rsa_public_no_padding(&pubk, &block).unwrap();
    assert_eq!(rsa_private_no_padding(&priv_k, &enc).unwrap(), block.to_vec());
    assert_eq!(rsa_public_no_padding(&pubk, &[1u8; 10]).unwrap_err().message, "RSA_NO_PADDING requires data with the same size as the modulus");
    assert_eq!(rsa_public_no_padding(&pubk, &[0xffu8; 128]).unwrap_err().message, "RSA: data too large for the modulus");
}

#[test]
fn rsa_keygen() {
    use super::rsa::*;
    for bits in [512usize, 513, 515, 600, 1024] {
        let k = rsa_generate(bits, &BigUint::from_u64(65537)).unwrap();
        assert_eq!(k.n.bits(), bits);
        assert!(k.p > k.q);
        assert_eq!(k.p.bits(), bits.div_ceil(2));
        let one = BigUint::one();
        let phi = k.p.sub(&one).mul(&k.q.sub(&one));
        assert!(k.e.mul(&k.d).rem(&phi).is_one());
        let sig = rsa_pkcs1v15_sign(&k, HashAlg::Sha256, b"x").unwrap();
        assert!(rsa_pkcs1v15_verify(&k.public_key(), HashAlg::Sha256, b"x", &sig).unwrap());
    }
    assert!(rsa_generate(512, &BigUint::from_u64(4)).is_err());
    let k3 = rsa_generate(512, &BigUint::from_u64(3)).unwrap();
    assert_eq!(k3.e.to_u64(), Some(3));
}

#[test]
fn ec_ed_x_key_formats() {
    use super::keys::*;
    use super::test_vectors_asym::*;
    let ec = parse_pkcs8(&unhex(EC_PKCS8_DER)).unwrap();
    assert_eq!(hex(&ec.export_pkcs8().unwrap()), EC_PKCS8_DER);
    assert_eq!(hex(&ec.export_sec1().unwrap()), EC_SEC1_DER);
    assert_eq!(hex(&ec.export_spki()), EC_SPKI_DER);
    assert_eq!(parse_sec1(&unhex(EC_SEC1_DER), OID_P256).unwrap(), ec);
    assert_eq!(parse_spki(&unhex(EC_SPKI_DER)).unwrap(), ec.to_public());
    let point = ec.ec_point().unwrap().to_vec();
    assert!(super::p256::ecdsa_verify(&point, HashAlg::Sha256, b"hello world", &unhex(EC_SIG_DER), false));
    assert!(super::p256::ecdsa_verify(&point, HashAlg::Sha256, b"hello world", &unhex(EC_SIG_P1363), true));
    let jwk: Vec<(&str, String)> = ec.jwk_fields();
    assert_eq!(jwk[0], ("kty", "EC".to_string()));
    assert_eq!(jwk[2].1, "ERemROMgg4ENVdfWgETXRUlHcdWroE-5gIvIGSRtoC8");
    assert_eq!(jwk[4].1, "weTIJvmDKUCYvLuW5JA8x8exKJ0PqkW4L2qbBxcyDC8");
    let ed = parse_pkcs8(&unhex(ED_PKCS8_DER)).unwrap();
    assert_eq!(hex(&ed.export_pkcs8().unwrap()), ED_PKCS8_DER);
    assert_eq!(hex(&ed.export_spki()), ED_SPKI_DER);
    assert_eq!(ed.kind(), KeyKind::Ed25519);
    let x = parse_pkcs8(&unhex(X_PKCS8_DER)).unwrap();
    assert_eq!(hex(&x.export_pkcs8().unwrap()), X_PKCS8_DER);
    assert_eq!(hex(&x.export_spki()), X_SPKI_DER);
    assert_eq!(x.jwk_fields()[2].1, "wQ2HUYNRI4TIpQ3qxnUZyqPRl8WWEbCL7ZXxgoeW4SQ");
    // errors
    assert_eq!(ed.export_der("pkcs1").unwrap_err().message, "KeyObject.export: 'pkcs1' requires an RSA key");
    assert_eq!(ed.export_der("sec1").unwrap_err().message, "KeyObject.export: 'sec1' requires an EC key");
    assert_eq!(ed.export_der("spki").unwrap_err().message, "KeyObject.export: unsupported private key type 'spki'");
    assert_eq!(ec.to_public().export_der("sec1").unwrap_err().message, "KeyObject.export: unsupported public key type 'sec1'");
    assert_eq!(ec.to_public().export_der("pkcs8").unwrap_err().message, "KeyObject.export: unsupported public key type 'pkcs8'");
    assert_eq!(
        parse_pkcs8(&unhex("300f020100300806062a864886f70d0400")).unwrap_err().message,
        "Private key algorithm 1.2.840.113549 is not supported in lumen"
    );
    assert_eq!(
        parse_spki(&unhex("300d300906072a8648ce380401030000")).unwrap_err().message,
        "Public key algorithm 1.2.840.10040.4.1 is not supported in lumen"
    );
    assert_eq!(parse_pkcs8(&unhex("3005020100")).unwrap_err().message, "ASN.1: truncated DER");
    assert_eq!(super::asn1::pem_decode("garbage").unwrap_err().message, "crypto: no PEM data found");
    // P-384 key → curve error
    let p384 = "3081b6020100301006072a8648ce3d020106052b8104002204819e30819b0201010430".to_string() + &"11".repeat(48) + "a16403620004" + &"22".repeat(96);
    assert_eq!(parse_pkcs8(&unhex(&p384)).unwrap_err().message, "EC curve secp384r1 is not supported in lumen (only prime256v1)");
    for kind in [KeyKind::Ec, KeyKind::Ed25519, KeyKind::X25519] {
        let k = AsymKey::generate(kind, 0, &BigUint::zero()).unwrap();
        let back = parse_pkcs8(&k.export_pkcs8().unwrap()).unwrap();
        assert_eq!(back, k);
        assert_eq!(parse_spki(&k.export_spki()).unwrap(), k.to_public());
    }
}

#[test]
fn x509_certs() {
    use super::test_vectors_asym::*;
    use super::x509::Certificate;
    let ca = Certificate::from_input(CERT_RSA_CERT.as_bytes(), true).unwrap();
    assert_eq!(ca.subject, "C=US\nST=California\nL=San Francisco\nO=Example Inc\nOU=Eng\nCN=example.com\nemailAddress=admin@example.com");
    assert_eq!(ca.issuer, ca.subject);
    assert_eq!(ca.serial_number, "0123456789ABCDEF");
    assert_eq!(ca.valid_from, "Nov 19 13:18:07 2026 GMT");
    assert_eq!(ca.valid_to, "Nov 19 13:18:07 2027 GMT");
    assert_eq!(ca.fingerprint, "42:10:84:F2:19:60:BD:4E:E1:5B:FF:C8:A5:83:83:7F:BD:AF:8E:40");
    assert_eq!(ca.fingerprint256, "A7:ED:62:A4:CC:65:BC:2B:8E:5A:97:9C:43:8D:6E:55:C8:9A:3F:05:60:ED:36:63:E6:F5:85:BD:04:7F:A5:84");
    assert!(ca.ca);
    assert_eq!(ca.subject_alt_name.as_deref(), Some("DNS:example.com, DNS:*.example.org, IP Address:127.0.0.1, email:a@b.com"));
    assert_eq!(ca.check_host("a.example.org").as_deref(), Some("a.example.org"));
    assert_eq!(ca.check_host("EXAMPLE.COM").as_deref(), Some("EXAMPLE.COM"));
    assert_eq!(ca.check_host("b.a.example.org"), None);
    assert_eq!(ca.check_ip("127.0.0.1").as_deref(), Some("127.0.0.1"));
    assert_eq!(ca.check_email("a@b.com").as_deref(), Some("a@b.com"));
    assert!(ca.verify(&ca.public_key().unwrap()));
    assert_eq!(ca.to_pem(), CERT_RSA_CERT);
    let leaf = Certificate::from_input(CERT_LEAF_CERT.as_bytes(), true).unwrap();
    assert_eq!(leaf.serial_number, "05");
    assert!(!leaf.ca);
    assert!(leaf.verify(&ca.public_key().unwrap()));
    assert!(!leaf.verify(&leaf.public_key().unwrap()));
    assert!(leaf.check_issued(&ca));
    assert!(!ca.check_issued(&leaf));
    assert_eq!(leaf.valid_to, "Nov 29 13:18:07 2026 GMT");
    let ec = Certificate::from_input(CERT_EC_CERT.as_bytes(), true).unwrap();
    assert_eq!(ec.subject, "CN=ec.test\nO=EC Org");
    assert_eq!(ec.serial_number, "267725A10FB1CDF8270A295A1B59A88BA72EA200");
    assert!(ec.verify(&ec.public_key().unwrap()));
    assert_eq!(ec.check_host("ec.test").as_deref(), Some("ec.test"));
    let attr = Certificate::from_input(CERT_ATTR_CERT.as_bytes(), true).unwrap();
    assert_eq!(attr.subject, "0.9.2342.19200300.100.1.25=com\n0.9.2342.19200300.100.1.25=example\nC=US\nST=CA\nL=SF\n2.5.4.9=1 Main St\n2.5.4.17=94105\nO=Org, Inc.\nOU=Unit\nOU=Second\n2.5.4.12=Dr\n2.5.4.42=John\n2.5.4.4=Doe\n2.5.4.43=JD\n2.5.4.65=jd\n2.5.4.44=Jr\n2.5.4.46=q1\n0.9.2342.19200300.100.1.1=jdoe\n2.5.4.5=12345\n2.5.4.15=Private\n2.5.4.13=desc\n2.5.4.41=nm\nCN=multi, comma=x\nemailAddress=jd@example.com");
    assert_eq!(attr.subject_alt_name.as_deref(), Some("DNS:a.example.com, IP Address:0:0:0:0:0:0:0:1, IP Address:2001:db8:0:0:0:0:0:1, IP Address:10.0.0.1, email:x@y.z"));
    assert_eq!(attr.serial_number, "448E5017891785542D72DD107D9A2A0FD2148742");
    let md5 = Certificate::from_input(CERT_RSA_MD5.as_bytes(), true).unwrap();
    assert!(md5.verify(&md5.public_key().unwrap()));
    let e384 = Certificate::from_input(CERT_EC_SHA384.as_bytes(), true).unwrap();
    assert!(e384.verify(&e384.public_key().unwrap()));
    assert_eq!(super::x509::format_time(super::x509::parse_time(&super::asn1::read_tlv(b"\x17\x0d090901000000Z", 0).unwrap()).unwrap()), "Sep  1 00:00:00 2009 GMT");
    assert_eq!(super::x509::format_time(super::x509::parse_time(&super::asn1::read_tlv(b"\x18\x0f20500101000000Z", 0).unwrap()).unwrap()), "Jan  1 00:00:00 2050 GMT");
    assert_eq!(Certificate::from_input(b"garbage", true).unwrap_err().message, "crypto: no PEM data found");
    assert_eq!(Certificate::from_input(&[1, 2, 3], false).unwrap_err().message, "ASN.1: truncated DER");
}

#[test]
fn bun_password() {
    use super::password::*;
    // Hashes produced by the original's Bun.password.
    // Heavy vectors (bcrypt cost 10, argon2 with 64 MiB) only in optimized builds.
    let heavy = !cfg!(debug_assertions);
    if heavy {
        assert!(password_verify(b"password", "$2b$10$6O4ciTYhPbUDNy8FJPXaFuxjhh/j41F5bopfuFKnFegosn9n.Vx2S").unwrap());
        assert!(password_verify(b"password", "$argon2id$v=19$m=65536,t=2,p=1$rUWUqt2wGUfWqRyvvOz7bGj67eYcR7YpQGSRHLydhEM$OHl2GqaJp1ELZ/IJoei3Ga7+jDaK1UqrmB8EKR7vc5E").unwrap());
        assert!(password_verify(b"password", "$argon2i$v=19$m=65536,t=2,p=1$H9n8E+mLpbFk3/X14mK7uC0RU5M1FC/yDrlAMlgcURI$h2lCWuhC0RNrA8jkMQrc3m7X1QX3JSKLDMxVM9IkYtY").unwrap());
    }
    for (pw, h) in [
        ("password".to_string(), "$2b$04$XKAybWkNIiT.M/JCirm/IOVuf/j5XHCh6Y/qwS//K7tbJ58UrlHN2"),
        ("x".repeat(100), "$2b$04$AM2pFI4o10fRLL6sLWhIVOvAoyxJK8Aco2rS1oxKbou2x.CXe.ypK"),
        ("y".repeat(72), "$2b$04$L9YvQXJpzmnXGCvYF7cVgeZflkkeM9VYOCH.N70PiRjNqnhB/uYgW"),
        ("z".repeat(73), "$2b$04$UUd.Sc7.XveSZfmWL.sqLOeVBnRBqDNKrH6XC9jECIjerwEg/bbOG"),
        ("x".repeat(100), "$2b$04$IG6KBROnYcwMsiTyMNFJw.kkGSQSPddQUEoqdFif99etnmbpqPsOm"),
    ] {
        assert!(password_verify(pw.as_bytes(), h).unwrap(), "{}", h);
        let mut wrong = pw.clone().into_bytes();
        wrong[0] ^= 1;
        assert!(!password_verify(&wrong, h).unwrap());
    }
    assert!(!password_verify(&"z".repeat(72).into_bytes(), "$2b$04$UUd.Sc7.XveSZfmWL.sqLOeVBnRBqDNKrH6XC9jECIjerwEg/bbOG").unwrap());
    assert!(!password_verify(&"y".repeat(73).into_bytes(), "$2b$04$L9YvQXJpzmnXGCvYF7cVgeZflkkeM9VYOCH.N70PiRjNqnhB/uYgW").unwrap());
    for (pw, h) in [
        ("pw", "$argon2id$v=19$m=8,t=1,p=1$DWalEYi9zcnMinDDHC0ZJ3xBqXvj0TBqwU4fYU572xA$dVNOs53tq5lZZFTjAgzYL2xDuNzVy2dkmLyUItxDbYs"),
        ("pw", "$argon2id$v=19$m=7,t=1,p=1$lWCI/y8SixSrMJT0cvsua1dYLbR9MwgDHDObWB20FEY$vfS7QqFfe67l3eVs3IRQAPUItuvh4x/UiY9xjxe3UGs"),
        ("password", "$argon2d$v=19$m=1024,t=1,p=1$Yr+Eg6OTIBCwg8fbeSzSdemt2izuMHhNskcHovu5oM0$RVgsV7DPf2Ti62IqWY9vP2owpeETr7SAwpTjAExEh2s"),
    ] {
        assert!(password_verify(pw.as_bytes(), h).unwrap(), "{}", h);
        assert!(!password_verify(b"nope", h).unwrap());
    }
    let unsupported = "Password verification failed with error \"UnsupportedAlgorithm\"";
    let invalid = "Password verification failed with error \"InvalidEncoding\"";
    assert_eq!(password_verify(b"x", "bogus").unwrap_err().message, unsupported);
    assert_eq!(password_verify(b"x", "").unwrap_err().message, unsupported);
    assert_eq!(password_verify(b"x", "$scrypt$ln=1$abc$def").unwrap_err().message, unsupported);
    assert_eq!(password_verify(b"x", "$argon2id$v=16$m=16,t=2,p=1$c29tZXNhbHRzb21lc2FsdA$abc").unwrap_err().message, invalid);
    assert_eq!(password_verify(b"x", "$argon2id$m=16,t=2,p=1$c29tZXNhbHRzb21lc2FsdA$abc").unwrap_err().message, invalid);
    assert_eq!(password_verify(b"x", "$argon2id$v=19$m=16,t=2,p=1$!!!$abc").unwrap_err().message, invalid);
    assert_eq!(password_verify(b"x", "$2b$04$short").unwrap_err().message, invalid);
    let h = password_hash(b"secret", PasswordAlgorithm::Bcrypt, 0, 0, 4).unwrap();
    assert!(h.starts_with("$2b$04$") && h.len() == 60);
    assert!(password_verify(b"secret", &h).unwrap());
    let h = password_hash(b"secret", PasswordAlgorithm::Argon2id, 64, 1, 0).unwrap();
    assert!(h.starts_with("$argon2id$v=19$m=64,t=1,p=1$"));
    assert!(password_verify(b"secret", &h).unwrap());
    assert_eq!(PasswordAlgorithm::from_name("ARGON2ID").unwrap(), PasswordAlgorithm::Argon2id);
    assert!(password_verify(b"password", "$argon2id$v=19$m=16,t=2,p=2$c29tZXNhbHRzb21lc2FsdA$qeKn9CseN+ud+LvWYX4VJwO+/mxCtmZ7F+tc3M9ssGA").unwrap());
    assert!(password_verify(b"password", "$argon2id$v=19$m=16,t=2,p=1$c29tZXNhbHRzb21lc2FsdA$uzIMsC/noL+RNMXrwus9Kw").unwrap());
    assert!(password_verify(b"password", "$argon2id$v=19$t=2,m=16,p=1$c29tZXNhbHRzb21lc2FsdA$uzIMsC/noL+RNMXrwus9Kw").unwrap());
    assert!(!password_verify(b"password", "$argon2id$v=19$m=16,t=2,p=1$c2FsdA$uzIMsC/noL+RNMXrwus9Kw").unwrap());
    assert_eq!(password_verify(b"x", "$argon2id$v=19$m=16,t=2$c29tZXNhbHRzb21lc2FsdA$uzIMsC/noL+RNMXrwus9Kw").unwrap_err().message, invalid);
    assert_eq!(password_verify(b"x", "$2$04$XKAybWkNIiT.M/JCirm/IOVuf/j5XHCh6Y/qwS//K7tbJ58UrlHN2").unwrap_err().message, unsupported);
    assert_eq!(password_verify(b"x", "$2c$04$XKAybWkNIiT.M/JCirm/IOVuf/j5XHCh6Y/qwS//K7tbJ58UrlHN2").unwrap_err().message, unsupported);
    assert!(password_verify(b"password", "$2y$04$XKAybWkNIiT.M/JCirm/IOVuf/j5XHCh6Y/qwS//K7tbJ58UrlHN2").unwrap());
    assert_eq!(password_verify(b"x", "$2b$03$XKAybWkNIiT.M/JCirm/IOVuf/j5XHCh6Y/qwS//K7tbJ58UrlHN2").unwrap_err().message, invalid);
    assert_eq!(PasswordAlgorithm::from_name("scrypt").unwrap_err().message, "Unsupported password hashing algorithm 'scrypt'");
}

#[test]
fn spkac() {
    use super::x509::*;
    let s = "MIICRTCCAS0wggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQC12wugAfvr+IzUOLRvHvfnIhqqjz0PYauqAkvn9+ShoO5pJYJjlVGsL6ScX8elkrstTsc030ZwYSz9ShVdh2L30reLaihDGHcGLWBqAkyu8FgWDmbJfgoRkNdPvYoChNH4HOcjYikgeyjWs7DuIadT1m02m5f82HeEXz3+/FxsElPOu+6uXiP0ltc6TMWXEqvHVC+TgcVmOOEoqsLIxCcYrKw4WMGLQtvnHAfKVYl+WxREISxEy2kcep5tLYNGIpSaYpujau/NWYQhbk+hkgelFFpYShE3SdNjluNpHl82rnv/vF+UAQi/ob/Tqngx3Vo0LBoNOs4sGDXZa5X4jb8xAgMBAAEWBWhlbGxvMA0GCSqGSIb3DQEBBAUAA4IBAQBOJtCFc9Dk13SWGliWQt3fs8cmx3SNBBjGGjZmIWQJlKrTdHTVgV270BGObLb1KkLI9ROjcYW3D4XuuaaMe8NbmCXTVO/wSlSxCjlBYoUNssIJgCSyg17Gf4x32FgB/w5NSitWnzvuusBlzgI7rgfnw/IhiXJzrsiR8OTCck+UHS4Dmrks/3eZ5sbOkh5dJqZ7134VmrkeBNaia7w6++GR0SJTxYfdnXTVOfJKiZlv45MBNZ0ZFDZ0n2S0I57djmRuep+wQlAxabEikThq8x9jhWHQuWQfLhpF1fm3utQsgfQ40BOeEcjjwTwVH8OqodLIxX/BGIR/lhHKEVEcmKvf";
    assert!(verify_spkac(s.as_bytes()));
    assert!(verify_spkac(format!("SPKAC={}\n", s).as_bytes()));
    let der = super::asn1::base64_decode(s);
    assert!(verify_spkac(&der));
    let p = parse_spkac(s.as_bytes()).unwrap();
    assert_eq!(p.challenge, b"hello");
    assert!(super::asn1::pem_encode("PUBLIC KEY", &p.public_key_der).contains("MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAtdsLoAH76/iM1Di0bx73"));
    let s5 = "MIICRzCCAS8wggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQC12wugAfvr+IzUOLRvHvfnIhqqjz0PYauqAkvn9+ShoO5pJYJjlVGsL6ScX8elkrstTsc030ZwYSz9ShVdh2L30reLaihDGHcGLWBqAkyu8FgWDmbJfgoRkNdPvYoChNH4HOcjYikgeyjWs7DuIadT1m02m5f82HeEXz3+/FxsElPOu+6uXiP0ltc6TMWXEqvHVC+TgcVmOOEoqsLIxCcYrKw4WMGLQtvnHAfKVYl+WxREISxEy2kcep5tLYNGIpSaYpujau/NWYQhbk+hkgelFFpYShE3SdNjluNpHl82rnv/vF+UAQi/ob/Tqngx3Vo0LBoNOs4sGDXZa5X4jb8xAgMBAAEWB21kNWNoYWwwDQYJKoZIhvcNAQEEBQADggEBAIidwR/EfdzQDgM9dutt9/dvfiW7h/bLJOgXkU+//cLTZhmdy9AvAA7esdcLsbRKnNqSXjayzsRSgdDKjaIRFkX1NCaH5YXLhxUJ93XlZZ2SYl69BbUVh9O3P9J29kMA3/H1X3RW637yZ7XI1WRJd9A3An8vzikTBUC1IhteVdv1yLy+ybAkSE+GDrY90GWr08yQpr8rbt49w/MTI4YUc3d/DLwucy4OKfKYCXKaGTinKqF+UBUR4tw4iVDL8wqmaOFQV0OEk0shtIwzOjaIlkXeXR6xrVKGpyXhIF+2ic+UlmfZqPzRGb13sArcf9+/zGQMdC/03KoJph0IDeNf5NU=";
    assert!(verify_spkac(s5.as_bytes()));
    assert_eq!(parse_spkac(s5.as_bytes()).unwrap().challenge, b"md5chal");
    let mut bad = der.clone();
    let n = bad.len();
    bad[n - 1] ^= 1;
    assert!(!verify_spkac(&bad));
    assert!(!verify_spkac(b"garbage"));
}

#[test]
fn cipher_info_reports() {
    let gcm = cipher_info("AES-128-GCM").unwrap();
    let r = get_cipher_info(gcm, None, None).unwrap();
    assert_eq!((r.mode, r.name, r.nid, r.block_size, r.iv_length, r.key_length), ("gcm", "id-aes128-gcm", 895, 1, Some(12.0), 16));
    assert_eq!(get_cipher_info(gcm, None, Some(7.0)).unwrap().iv_length, Some(7.0));
    assert!(get_cipher_info(gcm, None, Some(0.0)).is_none());
    let cbc = cipher_info("aes-128-cbc").unwrap();
    assert!(get_cipher_info(cbc, None, Some(12.0)).is_none());
    assert!(get_cipher_info(cbc, Some(16.0), Some(16.0)).is_some());
    assert!(get_cipher_info(cbc, Some(24.0), None).is_none());
    let ecb = cipher_info("aes-256-ecb").unwrap();
    assert_eq!(get_cipher_info(ecb, None, None).unwrap().iv_length, None);
    assert!(get_cipher_info(ecb, None, Some(16.0)).is_none());
    assert_eq!(cipher_info_by_nid(419).unwrap().name, "aes-128-cbc");
}

#[test]
fn uuids() {
    let dns = uuid_namespace("dns").unwrap();
    assert_eq!(format_uuid(&uuid_v5(&dns, b"hello")), "9342d47a-1bab-5709-9869-c840b2eac501");
    let v7 = format_uuid(&uuid_v7(1700000000000));
    assert_eq!(&v7[..15], "018bcfe5-6800-7");
    assert_eq!(parse_uuid("9342D47A-1bab-5709-9869-c840b2eac501").unwrap(), uuid_v5(&dns, b"hello"));
    assert!(parse_uuid("not-a-uuid").is_none());
}

#[test]
fn no_panics_on_garbage() {
    use super::keys::*;
    use super::test_vectors_asym::*;
    use super::x509::*;
    let mut seeds: Vec<Vec<u8>> = vec![
        unhex(RSA_PKCS1_DER),
        unhex(RSA_SPKI_DER),
        unhex(RSA_PUB_PKCS1_DER),
        unhex(EC_PKCS8_DER),
        unhex(EC_SEC1_DER),
        unhex(EC_SPKI_DER),
        unhex(ED_PKCS8_DER),
        unhex(X_SPKI_DER),
        super::asn1::pem_decode(CERT_RSA_CERT).unwrap().1,
        super::asn1::pem_decode(CERT_EC_CERT).unwrap().1,
        super::asn1::pem_decode(RSA_PKCS8_PEM).unwrap().1,
    ];
    let mut rng: u64 = 0x1234_5678_9abc_def0;
    let mut next = move || {
        rng ^= rng << 13;
        rng ^= rng >> 7;
        rng ^= rng << 17;
        rng
    };
    for _ in 0..40 {
        let n = (next() % 200) as usize;
        seeds.push((0..n).map(|_| next() as u8).collect());
    }
    let try_key = |k: &AsymKey| {
        let _ = k.export_spki();
        let _ = k.export_der("pkcs8");
        let _ = k.export_der("pkcs1");
        let _ = k.export_der("sec1");
        let _ = k.jwk_fields();
        let o = super::asym::SignOptions::default();
        for alg in [None, Some("sha256")] {
            if let Ok(s) = super::asym::sign(alg, b"m", k, &o) {
                let _ = super::asym::verify(alg, b"m", k, &s, &o);
            }
            let _ = super::asym::verify(alg, b"m", k, &[1, 2, 3], &o);
        }
        for op in [super::asym::RsaOp::PublicEncrypt, super::asym::RsaOp::PrivateDecrypt, super::asym::RsaOp::PrivateEncrypt, super::asym::RsaOp::PublicDecrypt] {
            for pad in [None, Some(1), Some(3), Some(4)] {
                let _ = super::asym::rsa_encrypt_op(op, k, b"0123456789", pad, HashAlg::Sha1, b"");
            }
        }
    };
    for seed in &seeds {
        for variant in 0..16 {
            let mut d = seed.clone();
            match variant % 4 {
                0 if !d.is_empty() => {
                    let i = (next() as usize) % d.len();
                    d[i] ^= 1 << (next() % 8);
                }
                1 => {
                    let cut = (next() as usize) % (d.len() + 1);
                    d.truncate(cut);
                }
                2 if !d.is_empty() => {
                    let i = (next() as usize) % d.len();
                    d[i] = next() as u8;
                }
                _ => {}
            }
            for r in [parse_spki(&d), parse_pkcs8(&d), parse_pkcs1_public(&d), parse_pkcs1_private(&d), parse_sec1(&d, OID_P256)] {
                if let Ok(k) = r {
                    try_key(&k);
                }
            }
            if let Ok(c) = Certificate::parse(&d) {
                let _ = c.public_key();
                let _ = c.check_host("a.b");
            }
            let _ = parse_spkac(&d);
            let _ = verify_spkac(&d);
            let _ = super::p256::decode_point(&d);
            let _ = super::p256::signature_from_der(&d);
            let _ = super::asn1::pem_decode(&String::from_utf8_lossy(&d));
            let s = String::from_utf8_lossy(&d).to_string();
            let _ = super::password::password_verify(b"pw", &format!("$2b$04${}", s));
            let _ = super::password::password_verify(b"pw", &format!("$argon2id$v=19$m=8,t=1,p=1${}", s));
        }
    }
    // Degenerate JWK RSA keys.
    for (n, e, d, p, q) in [("", "", "AQ", "AQ", "AQ"), ("Aw", "AQ", "AQ", "", ""), ("AA", "AA", "AA", "AA", "AA"), ("_w", "Aw", "Bw", "Aw", "AQ")] {
        let get = |k: &str| match k {
            "kty" => Some("RSA".to_string()),
            "n" => Some(n.to_string()),
            "e" => Some(e.to_string()),
            "d" => Some(d.to_string()),
            "p" => Some(p.to_string()),
            "q" => Some(q.to_string()),
            _ => None,
        };
        if let Ok(k) = AsymKey::from_jwk(&get, true) {
            try_key(&k);
        }
    }
    // DH with degenerate primes.
    for p in [0u64, 1, 2, 3, 4, 5] {
        let p = BigUint::from_u64(p);
        let x = super::dh::generate_private(&p);
        let _ = super::dh::public_key(&p, &BigUint::from_u64(2), &x);
        let _ = super::dh::compute_secret(&p, &x, &BigUint::from_u64(2));
        let _ = super::dh::check_private(&p, &x);
    }
    let _ = super::prime::generate_prime(0, false, Some(&BigUint::zero()), None);
}

#[test]
fn rsa_odd_sizes_and_ecdsa_hashes() {
    use super::keys::*;
    use super::rsa::*;
    use super::test_vectors_asym::*;
    let msg = b"odd sizes";
    for (bits, der, pk1, pss0, pss_max, oaep) in RSA_ODD {
        let k = match parse_pkcs8(&unhex(der)).unwrap() {
            AsymKey::RsaPrivate(k) => k,
            _ => unreachable!(),
        };
        assert_eq!(k.n.bits(), *bits);
        let pubk = k.public_key();
        assert_eq!(hex(&rsa_pkcs1v15_sign(&k, HashAlg::Sha256, msg).unwrap()), *pk1);
        assert_eq!(hex(&rsa_pss_sign(&k, HashAlg::Sha256, msg, 0).unwrap()), *pss0, "pss0 {}", bits);
        assert!(rsa_pss_verify(&pubk, HashAlg::Sha512, msg, &unhex(pss_max), None), "pssmax {}", bits);
        let mine = rsa_pss_sign(&k, HashAlg::Sha512, msg, PSS_SALTLEN_MAX_OR_AUTO).unwrap();
        assert!(rsa_pss_verify(&pubk, HashAlg::Sha512, msg, &mine, None));
        assert_eq!(rsa_oaep_decrypt(&k, HashAlg::Sha256, b"", &unhex(oaep)).unwrap(), msg);
    }
    let ec = parse_spki(&unhex(EC2_SPKI)).unwrap();
    let point = ec.ec_point().unwrap().to_vec();
    for (a, sig) in EC2_SIGS {
        let alg = hash_alg_from_name(a).unwrap();
        assert!(super::p256::ecdsa_verify(&point, alg, msg, &unhex(sig), false), "{}", a);
        assert!(!super::p256::ecdsa_verify(&point, alg, b"other", &unhex(sig), false));
    }
}
