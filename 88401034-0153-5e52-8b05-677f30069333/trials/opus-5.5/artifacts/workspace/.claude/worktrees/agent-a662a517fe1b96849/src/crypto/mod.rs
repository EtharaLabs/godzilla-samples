//! Pure-Rust (std-only) primitives behind the runtime's `node:crypto`, WebCrypto
//! (`globalThis.crypto`) and `Bun.password`, plus notes on how the ORIGINAL lumen binary
//! behaves at the JS level so the bindings can reproduce it.
//!
//! # Module map
//! | module | provides |
//! |---|---|
//! | [`hash`] | [`HashAlg`], [`Hasher`] (incremental, `Clone` = `Hash#copy`), [`digest`], [`Hmac`], [`hmac`], name resolution |
//! | [`kdf`] | [`pbkdf2`], [`hkdf`] (+ extract/expand) |
//! | [`mod@scrypt`] | [`scrypt()`], [`scrypt_romix`] (the original's `__crypto.scryptRomix`), [`scrypt_check_params`] |
//! | [`mod@argon2`] / [`mod@blake2b`] | Argon2d/i/id (RFC 9106), BLAKE2b |
//! | [`aes`] / [`cipher`] | AES block cipher; [`CipherCtx`] = `Cipheriv`/`Decipheriv` state machine (ECB/CBC/CTR/GCM) |
//! | [`random`] | [`fill_random`] (`/dev/urandom`), [`random_bytes`], [`random_uuid`], [`random_int`], [`timing_safe_eq`] |
//! | [`bigint`] | [`BigUint`] (Montgomery modpow, modinv, …) |
//! | [`prime`] | Miller–Rabin ([`prime::is_probable_prime`]), [`prime::generate_prime`] (safe / add / rem) |
//! | [`rsa`] | keygen, raw ops, PKCS#1 v1.5 & PSS signatures, OAEP / PKCS#1 v1.5 encryption, no-padding |
//! | [`p256`] | P-256 points (SEC1 encode/decode), ECDH, ECDSA (DER and IEEE-P1363) |
//! | [`curve25519`] | Ed25519 sign/verify, X25519 |
//! | [`dh`] | MODP group 14 and generic finite-field DH helpers |
//! | [`asn1`] | DER reader/writer, OIDs, PEM, base64/base64url |
//! | [`keys`] | [`keys::AsymKey`]: SPKI / PKCS#8 / PKCS#1 / SEC1 / JWK import & export |
//! | [`asym`] | `crypto.sign`/`verify`, `publicEncrypt` & co, `diffieHellman` dispatch with the original's error order |
//! | [`x509`] | `X509Certificate` parsing/formatting/verification, SPKAC (`crypto.Certificate`) |
//! | [`password`] | `Bun.password` (`__password` native): Argon2 PHC strings and bcrypt |
//!
//! Errors are [`CryptoError`] = JS constructor ([`ErrorKind`]: `Error`/`TypeError`/
//! `RangeError`) + optional `err.code` + exact message of the original (`String::from(err)`
//! gives the message). Functions that the original implements in JS but whose wording
//! depends on JS values (e.g. a non-integer `authTagLength`) leave that validation to the
//! binding; doc comments say so. Nothing here panics on untrusted input (fuzzed); the only
//! unchecked allocations are sized by the caller (`random_bytes(n)`, `pbkdf2(.., key_len)` —
//! see [`try_pbkdf2`]).
//!
//! Notable API shapes: [`CipherCtx`]'s `update`/`finalize`/`set_aad`/`set_auth_tag`/
//! `auth_tag` return `Result` because the original throws from all of them; [`hkdf`] /
//! [`scrypt()`] / [`argon2()`] return `Result<Vec<u8>, CryptoError>`.
//!
//! # How the original is built (useful for the bindings)
//! Most of the original's `node:crypto` is JavaScript running on a few natives:
//! `__crypto.sha256(u8) -> u8`, `__crypto.sha512(variant, u8)`, `__crypto.fill(u8)`,
//! `__crypto.uuid()`, `__crypto.scryptRomix(B, N, r)`, `__password.argon2[Sync](...)`,
//! `__password.hash[Sync]/verify[Sync](...)` — everything else (MD5/SHA-1/SHA-256 in JS, HMAC,
//! PBKDF2, HKDF, AES modes, RSA/EC/Ed25519 on BigInt, ASN.1, X.509) is JS. This module provides
//! all of it natively; results are bit-identical (verified against the original, node 18 and
//! python's hashlib). Typed arrays in the original are limited to 1 MiB (`new Uint8Array(n)`
//! with n > 1048576 throws `RangeError: Invalid typed array length`; hashing exactly 1 MiB in
//! one `update` fails there because the JS padding buffer exceeds 1 MiB).
//!
//! # JS-level behavior of the original, per export
//! Common helpers (as observed):
//! * `toBytes(data, encoding)`: strings → `Buffer.from(s, encoding || 'utf8')` (bad encoding →
//!   `TypeError: Unknown encoding: <enc>`); any ArrayBuffer view (incl. DataView, Uint16Array,
//!   Float64Array — raw bytes of the view) or ArrayBuffer → bytes; a `KeyObject` → its secret
//!   material. Anything else (numbers, null, undefined, plain objects, arrays, String objects)
//!   → `TypeError: crypto: data must be a string or BufferSource` (no code).
//! * Async variants (`pbkdf2`, `hkdf`, `scrypt`, `randomBytes(n, cb)`, `randomFill`,
//!   `randomInt(..., cb)`, `generateKey`, `generateKeyPair`, `generatePrime`, `checkPrime`,
//!   `sign`/`verify` with cb, `argon2`): the work runs synchronously, then the node-style
//!   callback `(err, result)` is scheduled with `queueMicrotask` (so it runs before
//!   `process.nextTick` callbacks and timers in lumen's loop). Validation errors raised while
//!   computing are delivered to the callback, except where noted. A missing/non-function
//!   callback → `TypeError: callback must be a function` thrown synchronously (pbkdf2, hkdf,
//!   scrypt, randomFill, generateKey, generateKeyPair, generatePrime, checkPrime;
//!   `crypto.argon2: callback must be a function` for argon2). `randomBytes`/`randomInt`/
//!   `sign`/`verify` only treat a *function* last argument as the callback (randomBytes with a
//!   truthy non-function fails later inside the microtask). `generateKeyPair` calls
//!   `cb(null, publicKey, privateKey)`. `argon2` throws its parameter errors synchronously and
//!   calls back with `(null, Buffer)`.
//!
//! ## Hashes: `createHash`, `Hash`, `hash`, `getHashes`
//! * `getHashes()` → `["md5","sha1","sha256","sha384","sha512","sha512-224","sha512-256"]`
//!   ([`HASH_NAMES`]).
//! * Names: `String(alg).toLowerCase()` looked up in {md5, sha1, sha-1, sha256, sha-256,
//!   sha384, sha-384, sha512, sha-512, sha512-224, sha512-256} ([`hash_alg_from_name`]).
//!   NOT accepted: sha224, RSA-SHA256, sha3-*, ripemd160, md4, shake*, blake2*, padded names.
//!   Error (plain `Error`, no code, thrown by the constructor):
//!   `Digest method not supported: <String(alg)> (lumen supports md5, sha1, sha256, sha384, sha512, sha512-224, sha512-256)`
//!   ([`unsupported_digest_error`]).
//! * `createHash(alg)` (options ignored) = `new Hash(alg)`; `Hash(...)` without `new` →
//!   TypeError (class). Prototype: `update, digest, copy` (+ internal `_bytes`); not a stream.
//! * `update(data, inputEncoding)` → `this`; data via `toBytes`. Allowed after `digest()`.
//! * `digest(enc)`: second call → `Error: Digest already called` (no code). `enc`
//!   undefined/null/''/`'buffer'` → Buffer; otherwise `buf.toString(enc)` (case-insensitive:
//!   `'HEX'` ok; hex, base64, base64url (unpadded), latin1/binary, utf8, ascii (7-bit masked),
//!   ucs2/utf16le; unknown → `TypeError: Unknown encoding: <enc>`).
//! * `copy()` → independent Hash with the data so far (works even after `digest()`, and
//!   includes data passed to `update()` after `digest()`). Binding recipe: keep the
//!   [`Hasher`] alive and implement `digest()` as `hasher.clone().finalize()` plus a
//!   `used` flag; `copy()` = `hasher.clone()` with `used = false`.
//! * `crypto.hash(alg, data, outputEncoding = 'hex')`: `'buffer'` (or null) → Buffer, else string.
//!
//! ## HMAC: `createHmac(alg, key)`, `Hmac`
//! Same names/errors as hashes. `key`: KeyObject (secret material) or `toBytes(key)` (utf8 for
//! strings; undefined/null/number → the toBytes TypeError). Prototype: `update, digest` only
//! (no `copy`). `digest` twice → `Error: Digest already called`.
//!
//! ## `pbkdf2Sync(password, salt, iterations, keylen, digest)` / `pbkdf2(..., cb)`
//! `digest === undefined` → `TypeError: The "digest" argument is required` (null → "Digest
//! method not supported: null"); `pbkdf2(p, s, i, k, cb)` (digest omitted) passes that error
//! to cb. No numeric validation — JS coercions: iterations <= 1 (0, -1, NaN) act as 1,
//! fractional iterations round up (1.5 → 2), `keylen` string `'10'` works, negative/undefined
//! keylen → empty Buffer, 1.5 → 1 byte. Returns a Buffer. Rust: [`pbkdf2`] (iterations 0 → 1).
//!
//! ## `hkdfSync(digest, ikm, salt, info, keylen)` / `hkdf(..., cb)`
//! Returns an **ArrayBuffer**. ikm/salt/info via toBytes (KeyObject ok; `info` undefined →
//! toBytes TypeError). Empty salt = HashLen zero bytes. `ceil(keylen/HashLen) > 255` →
//! `RangeError: hkdf: requested key length is too large` (no code). keylen 0/negative → empty,
//! fractional truncates. Rust: [`hkdf`].
//!
//! ## `scryptSync(password, salt, keylen, options)` / `scrypt(p, s, keylen[, options], cb)`
//! Returns a Buffer. Validation (in order):
//! * keylen: not a number → `TypeError [ERR_INVALID_ARG_TYPE]: The "keylen" argument must be
//!   of type number. Received type string ('16')` (Node's wording incl. "Received …");
//!   non-integer → `RangeError [ERR_OUT_OF_RANGE]: The value of "keylen" is out of range. It
//!   must be an integer. Received 1.5`; outside [0, 2147483647] → `... It must be >= 0 && <=
//!   2147483647. Received -1`.
//! * options: N/cost, r/blockSize, p/parallelization (both of a pair set →
//!   `Error [ERR_CRYPTO_SCRYPT_INVALID_PARAMETER]: Invalid scrypt parameter`), each validated
//!   like keylen with max 4294967295 and the option name ("N", "cost", ...); maxmem likewise
//!   (max 2^53-1). Falsy values fall back to defaults N=16384, r=8, p=1, maxmem=32 MiB.
//! * then [`scrypt_check_params`]: N < 2 or not a power of two → `RangeError
//!   [ERR_CRYPTO_INVALID_SCRYPT_PARAMS]: Invalid scrypt params`; `128*r*p + 128*r*(N+2) >
//!   maxmem` → `RangeError [ERR_CRYPTO_INVALID_SCRYPT_PARAMS]: Invalid scrypt params:
//!   error:030000AC:digital envelope routines::memory limit exceeded`.
//! * password/salt via toBytes. Then [`scrypt()`].
//!
//! ## `argon2Sync(algorithm, parameters)` / `argon2(algorithm, parameters, cb)`
//! Returns a Buffer of `tagLength` bytes. Order of checks (prefix `crypto.argon2Sync:` or
//! `crypto.argon2:`): algorithm must be exactly the string `'argon2d'|'argon2i'|'argon2id'`
//! (TypeError `<prefix> algorithm must be 'argon2d', 'argon2i', or 'argon2id'`); parameters must
//! be a non-null object/array (TypeError `<prefix> parameters must be an object`); required
//! (=== undefined → TypeError `<prefix> parameters.<name> is required`) in order message,
//! nonce, parallelism, tagLength, memory, passes; toBytes(message), toBytes(nonce); then
//! RangeErrors `<prefix> parameters.<name> must be an integer between <min> and <max>`:
//! parallelism [1, 16777215], tagLength [4, 4294967295], memory [8*parallelism, 4294967295],
//! passes [1, 4294967295] (non-numbers like `'64'` or `null` fail the same way); then nonce
//! length < 8 → RangeError `<prefix> parameters.nonce must be at least 8 bytes`; then
//! toBytes(secret), toBytes(associatedData) when !== undefined. `version` is ignored (always
//! 0x13). Rust: [`argon2()`] with [`Argon2Params`] (RFC 9106 vectors pass).
//!
//! ## Ciphers: `createCipheriv` / `createDecipheriv` / `Cipheriv` / `Decipheriv`
//! * `getCiphers()` → the 12 names aes-{128,192,256}-{cbc,ctr,ecb,gcm}, sorted
//!   ([`cipher_names`]). Names are case-insensitive; `aes128|aes192|aes256` alias CBC
//!   ([`cipher_info`]).
//! * Construction order: name (`Error: node:crypto cipher '<name>' is not supported in lumen
//!   (aes-{128,192,256}-{ecb,cbc,ctr,gcm} only)`) → toBytes(key) → key length (`RangeError
//!   [ERR_CRYPTO_INVALID_KEYLEN]: Invalid key length`) → toBytes(iv) unless null/undefined →
//!   IV check (`TypeError [ERR_CRYPTO_INVALID_IV]: Invalid initialization vector`; ECB: IV
//!   must be null/undefined/empty; CBC/CTR: 16 bytes; GCM: >= 1 byte, any length) →
//!   `options.authTagLength` (GCM only, when !== undefined): must be one of 4, 8, 12..16 else
//!   `TypeError [ERR_CRYPTO_INVALID_AUTH_TAG]: Invalid authentication tag length: <String(v)>`
//!   (also for `'16'`, `3.5`, `null`). Options for non-GCM ciphers are ignored. Strings for
//!   key/iv are utf8 bytes. Use [`CipherCtx::new`] + [`CipherCtx::set_auth_tag_length`].
//! * `update(data, inputEncoding, outputEncoding)`: data via toBytes(data, inputEncoding);
//!   returns a Buffer, or `buf.toString(outputEncoding)` when outputEncoding is set and not
//!   `'buffer'` — each chunk is encoded independently (NO StringDecoder carry-over for base64).
//!   ECB/CBC return whole blocks only; a decipher with auto-padding holds back the last block
//!   when buffered input is block-aligned; CTR/GCM return exactly as many bytes as given.
//! * `final(outputEncoding)`: see [`CipherCtx::finalize`] for errors (wrong final block length,
//!   bad decrypt, GCM `Unsupported state or unable to authenticate data`, second call →
//!   `Error [ERR_CRYPTO_INVALID_STATE]: Invalid state`); `update` after `final` →
//!   `Error: Trying to add data in unsupported state` (no code).
//! * `setAutoPadding(v)` → `this` (`undefined` → true, else `!!v`); usable any time.
//!   `setAAD(buf, options)` → `this` (GCM, before any update; AAD concatenates; else
//!   `Error [ERR_CRYPTO_INVALID_STATE]: Invalid state for operation setAAD`).
//!   `Cipheriv#getAuthTag()` → Buffer copy (GCM after final, else `... Invalid state for
//!   operation getAuthTag`); Cipheriv has no setAuthTag. `Decipheriv#setAuthTag(tag, enc)` →
//!   `this` (GCM, before final; length rules in [`CipherCtx::set_auth_tag`]); no getAuthTag.
//!   Not streams (no pipe/write/on); classes require `new`.
//! * `getCipherInfo(nameOrNid, {keyLength, ivLength})` → `{mode, name, nid, blockSize,
//!   ivLength?, keyLength}` in that key order ([`get_cipher_info`]; `name` is `id-aes128-gcm`
//!   for GCM; ECB has no ivLength). Unknown → undefined. `keyLength` option ≠ table → undefined;
//!   `ivLength` option: ECB → undefined, GCM → echoed when >= 1 (else undefined), others must
//!   be 16.
//!
//! ## Random: `randomBytes`, `randomFill[Sync]`, `randomInt`, `randomUUID`, `getRandomValues`
//! * `randomBytes(size[, cb])`: `Buffer.alloc(size)` then fill (so size errors are
//!   Buffer.alloc's: negative → `RangeError: index out of range`, > 1 MiB → `RangeError:
//!   Invalid typed array length`; 1.5 → 1 byte; '8' → 8; undefined/NaN → empty). With cb:
//!   returns undefined, cb(null, buf) in a microtask (a non-function truthy cb blows up later).
//! * `randomFillSync(buf, offset = 0, size = len - offset)` fills a view's bytes / an
//!   ArrayBuffer and returns `buf`; non-buffers are returned untouched (`[1,2]` → `[1,2]`).
//! * `randomInt([min = 0,] max[, cb])`: both must be safe integers (`RangeError: randomInt:
//!   min and max must be safe integers`); `max <= min` → `RangeError: The value of "max" is out
//!   of range. It must be greater than the value of "min".`; range may exceed 2^48 (Node
//!   limits it; the original doesn't). Uniform via [`random_int`].
//! * `randomUUID(options)` → v4 lowercase ([`random_uuid`]), options ignored.
//! * `getRandomValues(view)` (= `crypto.getRandomValues`): integer typed arrays only (Int8,
//!   Uint8, Uint8Clamped, Int16, Uint16, Int32, Uint32, BigInt64, BigUint64; Buffer ok), else
//!   `TypeError: getRandomValues expects an integer typed array`; byteLength > 65536 →
//!   `DOMException` name `QuotaExceededError`, message `getRandomValues: quota (65536 bytes)
//!   exceeded`; returns the same object.
//! * `timingSafeEqual(a, b)`: toBytes both (strings allowed); different lengths →
//!   `RangeError: Input buffers must have the same byte length` (no code); [`timing_safe_eq`].
//!
//! ## WebCrypto: `globalThis.crypto` (`=== require('crypto').webcrypto`)
//! `Crypto` instance with `getRandomValues`, `randomUUID`, `subtle` (getter). `crypto.subtle`
//! (`SubtleCrypto`) has ONLY `digest(algorithm, data)`: an async function; algorithm string or
//! `{name}`, upper-cased, must be `SHA-256` else the promise rejects with
//! `DOMException(NotSupportedError)`: `unsupported digest algorithm '<name>' (SHA-256 only for
//! now)` (name `''` when undefined); data must be ArrayBuffer or a view, else rejects with
//! `TypeError: digest expects a BufferSource`; resolves to an ArrayBuffer. `CryptoKey` is an
//! empty class. No encrypt/sign/importKey/generateKey/deriveBits.
//!
//! ## Secret keys: `createSecretKey(key, encoding)`, `KeyObject`, `generateKey[Sync]`
//! * `createSecretKey`: string → `Buffer.from(key, encoding || 'utf8')`, else toBytes (copied;
//!   KeyObject input allowed). `new KeyObject(type, material)` is public.
//! * KeyObject getters: `type` ('secret'|'public'|'private'), `symmetricKeySize` (secret only),
//!   `asymmetricKeyType` ('rsa'|'ec'|'ed25519'|'x25519'), `asymmetricKeyDetails` (rsa:
//!   `{modulusLength, publicExponent: <BigInt>}`, ec: `{namedCurve: 'prime256v1'}`, ed/x25519:
//!   `{}`, secret: undefined). Methods: `export(options)`, `equals(other)` (same type and
//!   bytes; asymmetric compares pkcs8/spki DER). No `toCryptoKey`, no `KeyObject.from`.
//! * Secret `export()`: Buffer copy for anything except `{format:'jwk'}` → `{kty:'oct', k}`.
//! * `generateKeySync(type, {length})`: type lower-cased must be 'hmac'|'aes' (else
//!   `Error: Unsupported key type '<type>' in lumen (secret 'hmac'/'aes' only)`); length must
//!   be an integer (`TypeError: options.length must be an integer number of bits`) and a
//!   multiple of 8 (`RangeError: options.length must be a multiple of 8`); any size otherwise.
//!
//! ## Asymmetric keys: `createPublicKey`, `createPrivateKey`, `KeyObject#export`
//! * Input: KeyObject; PEM string/Buffer; `{key, format: 'pem'|'der'|'jwk', type, passphrase}`.
//!   number/null → `TypeError: crypto: invalid key input`; no PEM block → `Error: crypto: no PEM
//!   data found`; `passphrase` given for an encrypted key → `Error: crypto: encrypted private
//!   keys are not supported in lumen`; JWK not an object → `TypeError: crypto: JWK must be an
//!   object`. Private-from-public KeyObject → `TypeError: crypto: cannot create a private key
//!   from a public key`; public-from-secret → `TypeError: crypto: cannot derive a public key
//!   from this KeyObject`. Parser dispatch by PEM label / DER `type`:
//!   [`keys::parse_private_key`], [`keys::parse_public_key`] (certificates → their SPKI).
//!   Supported: RSA (also RSA-PSS OID, treated as RSA), EC P-256 only (`EC curve secp384r1 is
//!   not supported in lumen (only prime256v1)`), Ed25519, X25519; others → `Private key
//!   algorithm <oid> is not supported in lumen` / `Public key algorithm <oid> is not supported
//!   in lumen`. JWK: [`keys::AsymKey::from_jwk`] (the original barely validates JWK fields).
//! * `export({format, type})`: format required (`TypeError: KeyObject.export: options.format
//!   is required for asymmetric keys`); `'jwk'` → [`keys::AsymKey::jwk_fields`] (passphrase
//!   ignored); `'pem'`/`'der'`: `cipher` or `passphrase` → `Error: KeyObject.export: encrypted
//!   private-key export is not supported in lumen`; type errors per
//!   [`keys::AsymKey::export_der`]; other formats → `Error: KeyObject.export: unsupported
//!   format '<f>'`. PEM = [`asn1::pem_encode`] with [`keys::AsymKey::pem_label`] (64-col, trailing
//!   newline). Encodings are byte-identical to Node/OpenSSL.
//!
//! ## `generateKeyPair[Sync](type, options)`
//! type lower-cased ∈ {ed25519, x25519, rsa, ec}, else `Error: generateKeyPair type '<type>' is
//! not supported in lumen (ed25519, x25519, rsa, ec)`. rsa: `modulusLength` must be an integer
//! (`TypeError: options.modulusLength is required for RSA key generation`) in [512, 8192]
//! (`RangeError: RSA modulusLength must be an integer in [512, 8192]`); `publicExponent`
//! number/bigint/numeric string, default 65537 (even values never terminate in the original);
//! [`rsa::rsa_generate`] (d = e^-1 mod φ, p > q). ec: `namedCurve` ∈ {P-256, prime256v1,
//! secp256r1} else `Error: Named curve '<c>' is not supported in lumen (only prime256v1/P-256)`.
//! `publicKeyEncoding`/`privateKeyEncoding` → results of `export(...)`. Returns
//! `{publicKey, privateKey}`. Use [`keys::AsymKey::generate`].
//!
//! ## `sign`/`verify`/`createSign`/`createVerify`
//! * Digest names go through [`normalize_digest_name`] (`RSA-SHA256`, `sha256WithRSAEncryption`,
//!   `ecdsa-with-SHA256`, `id-sha256` → sha256) then the hash table; errors use the
//!   normalized name. `createSign/createVerify` validate eagerly.
//! * `crypto.sign(alg, data, key[, cb])` → Buffer. Key: anything createPrivateKey accepts, or
//!   an options object carrying `padding`, `saltLength`, `dsaEncoding`. RSA/EC need a digest
//!   (`Error: crypto.sign: a digest algorithm is required for rsa keys` / `... for ec keys`);
//!   Ed25519 requires null/undefined (`Error: crypto.sign: algorithm must be null/undefined
//!   for Ed25519 keys`); X25519 → `Error: crypto.sign: X25519 keys cannot sign`. RSA padding
//!   `RSA_PKCS1_PADDING` (default; md5/sha1/sha256/sha384/sha512 only — [`rsa::rsa_pkcs1v15_sign`])
//!   or `RSA_PKCS1_PSS_PADDING` (any digest, MGF1 same hash; `saltLength` default = digest
//!   length, -1 digest, -2 max — [`rsa::rsa_pss_sign`]); other paddings → `Error:
//!   crypto.sign: RSA padding <n> is not supported in lumen`. ECDSA uses a random nonce;
//!   `dsaEncoding: 'ieee-p1363'` → r‖s ([`p256::ecdsa_sign`]). Ed25519: [`curve25519::ed25519_sign`].
//! * `crypto.verify(alg, data, key, signature[, cb])` → boolean (key may be private; signature
//!   via toBytes — a hex string is NOT decoded). PSS verify `saltLength` default = auto.
//!   RSA signatures must be exactly k bytes.
//! * `createSign(alg).update(d, enc).sign(key, outEnc)`; `createVerify(alg).update(...)
//!   .verify(key, sig, sigEnc)` — a string signature is decoded with `sigEnc || 'hex'`.
//!
//! ## RSA encryption: `publicEncrypt`, `privateDecrypt`, `privateEncrypt`, `publicDecrypt`
//! Non-RSA keys → `Error: <fn>: only RSA keys are supported in lumen`. Defaults: publicEncrypt/
//! privateDecrypt OAEP (`oaepHash` default sha1, `oaepLabel` via toBytes), privateEncrypt/
//! publicDecrypt `RSA_PKCS1_PADDING`. `privateDecrypt` with `RSA_PKCS1_PADDING` →
//! `TypeError: RSA_PKCS1_PADDING is no longer supported for private decryption`;
//! `RSA_NO_PADDING` everywhere; other paddings → `Error: <fn>: padding <n> is not supported in
//! lumen`. Messages: `RSA-OAEP: message too long`, `RSA-OAEP: decryption error`,
//! `RSA-PKCS1: message too long`, `privateEncrypt: message too long`, `publicDecrypt:
//! decryption error`, `RSA: data too large for the modulus`, `RSA_NO_PADDING requires data
//! with the same size as the modulus` — all plain Errors without code (see [`rsa`]).
//!
//! ## ECDH / DH
//! * `getCurves()` → `["P-256","prime256v1","secp256r1"]`. `createECDH(curve)` /
//!   `ECDH.convertKey(key, curve, inEnc, outEnc, format)`: other curves → `Error: Named curve
//!   '<c>' is not supported in lumen (only prime256v1/P-256)`. `generateKeys(enc, format)`,
//!   `getPublicKey(enc, format)` (format 'uncompressed' default | 'compressed' | 'hybrid', else
//!   `TypeError: Invalid EC point conversion form '<f>'`), `getPrivateKey(enc)` (32 bytes),
//!   `setPrivateKey(k, enc)` (`RangeError: Private key is not valid for specified curve` unless
//!   1 <= k < n), `setPublicKey`, `computeSecret(pub, inEnc, outEnc)` (32-byte x). Errors:
//!   `Private key is not set`, `Public key is not set`, point errors from
//!   [`p256::decode_point`], `Failed to compute ECDH key`.
//! * `getDiffieHellman(name)` / `createDiffieHellmanGroup(name)`: only `modp14`
//!   ([`dh::named_group`]). `createDiffieHellman(bits[, gen])` makes a safe prime;
//!   `createDiffieHellman(prime, [enc], [gen], [genEnc])` (`RangeError: Invalid
//!   Diffie-Hellman parameters` if p <= 4, g <= 1 or g >= p). Methods: generateKeys (keeps an
//!   existing private key), computeSecret (`Error: Supplied key is too small`), getPrime,
//!   getGenerator, getPublicKey/getPrivateKey (`Error: No public key - did you forget to
//!   generate one?` / `No private key - ...`), setPublicKey, setPrivateKey; `verifyError` is 0.
//!   See [`dh`].
//! * `diffieHellman({privateKey, publicKey})`: EC P-256 or X25519 KeyObjects ([`p256::ecdh`],
//!   [`curve25519::x25519`]); errors `TypeError: diffieHellman requires privateKey and publicKey
//!   KeyObjects`, `diffieHellman privateKey does not contain a private key`, `diffieHellman keys
//!   must use the same supported curve`.
//!
//! ## Primes: `checkPrime[Sync]`, `generatePrime[Sync]`
//! * `checkPrimeSync(candidate, {checks = 40})`: bigint, or big-endian bytes via toBytes
//!   (a JS number → toBytes TypeError). [`prime::is_probable_prime`].
//! * `generatePrimeSync(size, {add, rem, safe, bigint})`: size integer >= 2 else `RangeError:
//!   prime size must be an integer >= 2 bits`; add/rem bigint or bytes; `add <= 0` →
//!   `RangeError: generatePrime option 'add' must be greater than zero`; rem outside
//!   [0, add) → `RangeError: generatePrime option 'rem' must be non-negative and less than
//!   'add'`; size > 2 with even add and even rem → `RangeError: generatePrime add/rem
//!   constraints cannot produce an odd prime`; rem default 3 when safe else 1. Result: bigint
//!   when `bigint`, else an ArrayBuffer of `ceil(size/8)` big-endian bytes.
//!   [`prime::generate_prime`]; primes always have their two top bits set.
//!
//! ## `X509Certificate`, `Certificate` (SPKAC)
//! See [`x509::Certificate`] for every property's exact formatting and the quirks (only
//! C/ST/L/O/OU/CN/emailAddress short names, no escaping, SAN without URI, `checkHost` returns
//! the input, Ed25519/PSS/ecdsa-sha1 certificate signatures don't verify, non-P-256 EC
//! certificates fail to construct). Instance properties: raw, serialNumber, issuer, subject,
//! validFromDate, validToDate (Date), validFrom, validTo, fingerprint, fingerprint256,
//! fingerprint512, publicKey (KeyObject), ca, keyUsage (undefined), subjectAltName,
//! infoAccess (undefined), issuerCertificate (undefined); methods checkIssued, checkPrivateKey,
//! verify, checkHost, checkEmail, checkIP, toString, toJSON. `Certificate` (callable with or
//! without new; static and prototype `exportChallenge`, `exportPublicKey`, `verifySpkac`):
//! [`x509::parse_spkac`], [`x509::verify_spkac`].
//!
//! ## Misc
//! `getFips()` → 0; `setFips(v)` truthy → `Error: FIPS mode is not supported in lumen`;
//! `secureHeapUsed()` → `{total:0,min:0,used:0,utilization:0}`; `setEngine()` → `Error:
//! node:crypto setEngine is not supported in lumen (no native primitive available)`;
//! `constants` is a plain (not frozen) object, in this key order (56 keys):
//! ```text
//! OPENSSL_VERSION_NUMBER: 805306624, SSL_OP_ALL: 2147485776, SSL_OP_ALLOW_NO_DHE_KEX: 1024,
//! SSL_OP_ALLOW_UNSAFE_LEGACY_RENEGOTIATION: 262144, SSL_OP_CIPHER_SERVER_PREFERENCE: 4194304,
//! SSL_OP_CISCO_ANYCONNECT: 32768, SSL_OP_COOKIE_EXCHANGE: 8192,
//! SSL_OP_CRYPTOPRO_TLSEXT_BUG: 2147483648, SSL_OP_DONT_INSERT_EMPTY_FRAGMENTS: 2048,
//! SSL_OP_LEGACY_SERVER_CONNECT: 4, SSL_OP_NO_COMPRESSION: 131072,
//! SSL_OP_NO_ENCRYPT_THEN_MAC: 524288, SSL_OP_NO_QUERY_MTU: 4096,
//! SSL_OP_NO_RENEGOTIATION: 1073741824, SSL_OP_NO_SESSION_RESUMPTION_ON_RENEGOTIATION: 65536,
//! SSL_OP_NO_SSLv2: 0, SSL_OP_NO_SSLv3: 33554432, SSL_OP_NO_TICKET: 16384,
//! SSL_OP_NO_TLSv1: 67108864, SSL_OP_NO_TLSv1_1: 268435456, SSL_OP_NO_TLSv1_2: 134217728,
//! SSL_OP_NO_TLSv1_3: 536870912, SSL_OP_PRIORITIZE_CHACHA: 2097152,
//! SSL_OP_TLS_ROLLBACK_BUG: 8388608, ENGINE_METHOD_RSA: 1, ENGINE_METHOD_DSA: 2,
//! ENGINE_METHOD_DH: 4, ENGINE_METHOD_RAND: 8, ENGINE_METHOD_EC: 2048,
//! ENGINE_METHOD_CIPHERS: 64, ENGINE_METHOD_DIGESTS: 128, ENGINE_METHOD_PKEY_METHS: 512,
//! ENGINE_METHOD_PKEY_ASN1_METHS: 1024, ENGINE_METHOD_ALL: 65535, ENGINE_METHOD_NONE: 0,
//! DH_CHECK_P_NOT_SAFE_PRIME: 2, DH_CHECK_P_NOT_PRIME: 1, DH_UNABLE_TO_CHECK_GENERATOR: 4,
//! DH_NOT_SUITABLE_GENERATOR: 8, RSA_PKCS1_PADDING: 1, RSA_NO_PADDING: 3,
//! RSA_PKCS1_OAEP_PADDING: 4, RSA_X931_PADDING: 5, RSA_PKCS1_PSS_PADDING: 6,
//! RSA_PSS_SALTLEN_DIGEST: -1, RSA_PSS_SALTLEN_MAX_SIGN: -2, RSA_PSS_SALTLEN_AUTO: -2,
//! TLS1_VERSION: 769, TLS1_1_VERSION: 770, TLS1_2_VERSION: 771, TLS1_3_VERSION: 772,
//! POINT_CONVERSION_COMPRESSED: 2, POINT_CONVERSION_UNCOMPRESSED: 4,
//! POINT_CONVERSION_HYBRID: 6
//! plus two string keys: defaultCoreCipherList (between RSA_PSS_SALTLEN_AUTO and TLS1_VERSION)
//! and defaultCipherList (the last key), both equal to
//!   "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES256-GCM-SHA384:DHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-SHA256:DHE-RSA-AES128-SHA256:ECDHE-RSA-AES256-SHA384:DHE-RSA-AES256-SHA384:ECDHE-RSA-AES256-SHA256:DHE-RSA-AES256-SHA256:HIGH:!aNULL:!eNULL:!EXPORT:!DES:!RC4:!MD5:!PSK:!SRP:!CAMELLIA"
//! ```
//!
//! ## `Bun.password` and `Bun.CryptoHasher`
//! `Bun.password.hash[Sync](pw, algorithm | {algorithm, memoryCost, timeCost, cost})` /
//! `verify[Sync](pw, hash)` — see [`password`]. `Bun.CryptoHasher`, `Bun.MD5`/`SHA1`/…/
//! `SHA512_256` and `Bun.sha` wrap `createHash`/`createHmac` (so `Bun.SHA224`/`Bun.MD4`
//! throw the digest error; digests come back as Uint8Array unless an encoding is given).

#![allow(dead_code, unused_imports)]

pub mod aes;
pub mod argon2;
pub mod asn1;
pub mod asym;
pub mod bigint;
pub mod blake2b;
mod blowfish_tables;
pub mod cipher;
pub mod curve25519;
pub mod dh;
mod error;
pub mod hash;
pub mod kdf;
pub mod keys;
mod md5;
pub mod p256;
pub mod password;
pub mod prime;
pub mod random;
pub mod rsa;
pub mod scrypt;
mod sha1;
mod sha256;
mod sha512;
pub mod x509;

pub use aes::Aes;
pub use argon2::{argon2, Argon2Params, Argon2Variant};
pub use bigint::BigUint;
pub use blake2b::{blake2b, Blake2b};
pub use cipher::{
    aes_gcm_decrypt, aes_gcm_encrypt, cipher_info, cipher_info_by_nid, cipher_names, get_cipher_info, CipherCtx, CipherInfo,
    CipherInfoReport, CipherMode, CIPHERS, GCM_TAG_LENGTHS,
};
pub use error::{CryptoError, ErrorKind};
pub use hash::{
    digest, hash_alg_from_name, hmac, normalize_digest_name, sign_hash_alg_from_name, unsupported_digest_error,
    HashAlg, Hasher, Hmac, HASH_NAMES,
};
pub use kdf::{hkdf, hkdf_expand, hkdf_extract, pbkdf2, try_pbkdf2};
pub use random::{
    fill_random, format_uuid, parse_uuid, random_bytes, random_int, random_uuid, timing_safe_eq, uuid_namespace, uuid_v5, uuid_v7,
};
pub use scrypt::{scrypt, scrypt_check_params, scrypt_romix, SCRYPT_DEFAULT_MAXMEM};

#[cfg(test)]
mod tests;
#[cfg(test)]
mod test_vectors;
#[cfg(test)]
mod test_vectors_asym;
#[cfg(test)]
mod test_vectors_bigint;
#[cfg(test)]
mod test_vectors_cipher;
