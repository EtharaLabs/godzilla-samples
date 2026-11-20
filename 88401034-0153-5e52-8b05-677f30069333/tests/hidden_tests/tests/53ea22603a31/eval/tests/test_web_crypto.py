"""Web Crypto surface of lumen-cli: crypto.subtle.digest (SHA-256), getRandomValues, randomUUID and
the shape of the Crypto / SubtleCrypto globals. Random outputs are only checked for shape."""

from conftest import check_script, resources_for

G = resources_for(__file__)

HEX = r'''
const hex = (buf) => Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, '0')).join('');
const enc = (s) => new TextEncoder().encode(s);
'''


def test_subtle_digest_sha256_vectors(run, workdir):
    """CATCHES: a wrong SHA-256 (padding errors at the 55/56/63/64-byte block boundaries, wrong
    length encoding for multi-block input, byte-order mistakes), digest() not returning a 32-byte
    ArrayBuffer, or BufferSource views hashed without honouring byteOffset/byteLength."""
    check_script(run, workdir, G, "subtle_digest_sha256_vectors", HEX + r'''
const d = async (data, alg = 'SHA-256') => hex(await crypto.subtle.digest(alg, data));
console.log('empty', await d(new Uint8Array(0)));
console.log('abc', await d(enc('abc')));
console.log('448-bit', await d(enc('abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq')));
for (const n of [1, 55, 56, 63, 64, 65, 119, 120, 1000]) console.log('a*' + n, await d(enc('a'.repeat(n))));
console.log('utf8', await d(enc('héllo 🌍')));
const r = await crypto.subtle.digest('SHA-256', enc('x'));
console.log(r instanceof ArrayBuffer, r.byteLength, Object.prototype.toString.call(r));
const backing = enc('__abc__');
console.log('subarray', await d(backing.subarray(2, 5)));
console.log('ArrayBuffer', await d(enc('abc').buffer));
console.log('DataView', await d(new DataView(backing.buffer, 2, 3)));
console.log('Uint32Array', await d(new Uint32Array([0x64636261])));
console.log('lowercase name', await d(enc('abc'), 'sha-256'));
console.log('object name', await d(enc('abc'), { name: 'Sha-256' }));
const big = new Uint8Array(100000).map((_, i) => i & 255);
console.log('100000 bytes', await d(big));
''', filename="subtle_digest_sha256_vectors.mjs")


def test_subtle_digest_errors_and_missing_methods(run, workdir):
    """CATCHES: digest() accepting algorithms the reference does not implement (SHA-1/384/512) or
    throwing synchronously instead of rejecting, wrong DOMException name/message for unsupported
    algorithms, non-BufferSource data not rejected with TypeError, or SubtleCrypto exposing
    encrypt/sign/importKey/... stubs that the reference does not have."""
    check_script(run, workdir, G, "subtle_digest_errors_and_missing_methods", r'''
const tryDigest = async (label, alg, data) => {
  let p;
  try { p = crypto.subtle.digest(alg, data); } catch (e) { console.log(label, 'sync throw', e.name); return; }
  console.log(label, 'returns promise', p instanceof Promise);
  try { await p; console.log(label, 'resolved'); }
  catch (e) { console.log(label, 'rejected', e.name, JSON.stringify(e.message), e instanceof DOMException, e instanceof TypeError); }
};
const data = new Uint8Array([1, 2, 3]);
for (const alg of ['SHA-1', 'SHA-384', 'SHA-512', 'MD5', 'SHA256', '']) await tryDigest(alg || '(empty)', alg, data);
await tryDigest('object', { name: 'SHA-512' }, data);
await tryDigest('no name', {}, data);
await tryDigest('undefined alg', undefined, data);
await tryDigest('string data', 'SHA-256', 'abc');
await tryDigest('array data', 'SHA-256', [1, 2, 3]);
await tryDigest('no data', 'SHA-256');
const names = ['digest', 'encrypt', 'decrypt', 'sign', 'verify', 'importKey', 'exportKey', 'generateKey', 'deriveBits', 'deriveKey', 'wrapKey', 'unwrapKey'];
console.log(names.map((n) => n + ':' + typeof crypto.subtle[n]).join(' '));
console.log(Object.getOwnPropertyNames(SubtleCrypto.prototype).join());
''', filename="subtle_digest_errors_and_missing_methods.mjs")


def test_get_random_values_contract(run, workdir):
    """CATCHES: getRandomValues that returns a copy instead of the same view, writes outside the
    view's byte range, accepts float arrays/DataView/plain arrays, fails on zero-length views,
    mis-enforces the 65536-byte quota (QuotaExceededError DOMException) or leaves the buffer
    all zeros. Only the shape and statistical non-zeroness of random data is checked."""
    check_script(run, workdir, G, "get_random_values_contract", r'''
const show = (label, f) => { try { console.log(label, f()); } catch (e) { console.log(label, 'THREW', e.name + ': ' + e.message, e instanceof DOMException); } };
const u8 = new Uint8Array(64);
const ret = crypto.getRandomValues(u8);
console.log('same view', ret === u8, u8.length, u8.some((b) => b !== 0));
const backing = new Uint8Array(48);
crypto.getRandomValues(backing.subarray(16, 32));
const outside = [...backing.subarray(0, 16), ...backing.subarray(32)];
console.log('outside untouched', outside.every((b) => b === 0), 'inside nonzero', backing.subarray(16, 32).some((b) => b !== 0));
for (const T of [Int8Array, Uint8Array, Uint8ClampedArray, Int16Array, Uint16Array, Int32Array, Uint32Array, BigInt64Array, BigUint64Array]) {
  const v = new T(8);
  const r = crypto.getRandomValues(v);
  console.log(T.name, r === v, r.length, r.byteLength);
}
for (const [label, mk] of [['Float32Array', () => new Float32Array(4)], ['Float64Array', () => new Float64Array(4)],
                          ['DataView', () => new DataView(new ArrayBuffer(4))], ['Array', () => [0, 0]],
                          ['ArrayBuffer', () => new ArrayBuffer(4)], ['undefined', () => undefined]]) {
  show(label, () => crypto.getRandomValues(mk()));
}
show('empty', () => crypto.getRandomValues(new Uint8Array(0)).length);
show('65536 bytes', () => crypto.getRandomValues(new Uint8Array(65536)).length);
show('16384 u32', () => crypto.getRandomValues(new Uint32Array(16384)).length);
show('65537 bytes', () => crypto.getRandomValues(new Uint8Array(65537)));
show('16385 u32', () => crypto.getRandomValues(new Uint32Array(16385)));
const a = crypto.getRandomValues(new Uint8Array(32)), b = crypto.getRandomValues(new Uint8Array(32));
console.log('two draws differ', a.some((x, i) => x !== b[i]));
''', filename="get_random_values_contract.mjs")


def test_random_uuid_shape(run, workdir):
    """CATCHES: randomUUID not producing lowercase RFC 4122 version-4 strings (version nibble 4,
    variant 8/9/a/b, 8-4-4-4-12 layout), repeating values, or returning a non-string."""
    check_script(run, workdir, G, "random_uuid_shape", r'''
const re = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const ids = Array.from({ length: 200 }, () => crypto.randomUUID());
console.log(typeof ids[0], ids[0].length, ids.every((s) => re.test(s)), new Set(ids).size);
const variants = new Set(ids.map((s) => s[19]));
console.log('variant chars subset of 89ab', [...variants].every((c) => '89ab'.includes(c)));
console.log(crypto.randomUUID.length, typeof crypto.randomUUID.call(crypto));
''', filename="random_uuid_shape.mjs")


def test_crypto_globals_shape(run, workdir):
    """CATCHES: crypto/Crypto/SubtleCrypto/CryptoKey globals with the wrong identity or instanceof
    relationships, a fresh SubtleCrypto per `crypto.subtle` access, node:crypto's webcrypto/subtle
    not being the same global objects, or node:crypto createHash('sha256') disagreeing with
    subtle.digest."""
    check_script(run, workdir, G, "crypto_globals_shape", r'''
const nodeCrypto = require('node:crypto');
console.log(crypto instanceof Crypto, crypto.subtle instanceof SubtleCrypto, crypto.subtle === crypto.subtle);
console.log(typeof CryptoKey, new CryptoKey() instanceof CryptoKey, Object.keys(crypto).length);
console.log(nodeCrypto.webcrypto === globalThis.crypto, nodeCrypto.subtle === crypto.subtle);
console.log(typeof nodeCrypto.randomUUID(), nodeCrypto.getRandomValues(new Uint8Array(4)).length);
(async () => {
  const data = new TextEncoder().encode('cross-check');
  const viaSubtle = Buffer.from(await crypto.subtle.digest('SHA-256', data)).toString('hex');
  const viaNode = nodeCrypto.createHash('sha256').update('cross-check').digest('hex');
  console.log(viaSubtle, viaSubtle === viaNode);
})();
''', filename="crypto_globals_shape.cjs")
