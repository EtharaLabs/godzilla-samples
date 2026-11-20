"""node:zlib (deflate/zlib/gzip, Brotli, Zstandard: sync, callback and stream forms, crc32,
constants, error messages for corrupt input) and node:crypto (hashes, HMAC, KDFs, AES modes,
signatures with fixed keys, ECDH/X25519, timingSafeEqual, KeyObject, webcrypto digest/HMAC).

Compressed fixtures under test_resources/test_node_zlib_crypto/*.json were produced by foreign
encoders (Python's zlib, Node 18's Brotli and libzstd 1.5.5); each entry carries the length and the
CRC-32 of the original data, so a correct decoder prints `match`."""

from conftest import check_script, resources_for, write_files

G = resources_for(__file__)


def _fixture(workdir, name):
    write_files(workdir, {name: (G / name).read_bytes()})


# ---------------------------------------------------------------------------------------------
# DEFLATE / zlib / gzip
# ---------------------------------------------------------------------------------------------

def test_deflate_encoder_exact_bytes(run, workdir):
    """CATCHES: a deflate encoder that is not this program's single fixed-Huffman block with greedy
    hash-chain LZ77 (different match choices, dynamic blocks, stored fallback), wrong zlib header
    (78 9c) / Adler-32 trailer, gzip header with an OS byte other than 0xff or wrong CRC/ISIZE trailer,
    and honouring level/strategy options (the reference ignores them: level 0 == level 9 output)."""
    check_script(run, workdir, G, "deflate_encoder_exact_bytes", r'''
const zlib = require('zlib');
const inputs = [
  ['empty', ''],
  ['one', 'a'],
  ['hello', 'hello, hello, hello world!'],
  ['run600', 'z'.repeat(600)],
  ['bytes256', Buffer.from(Array.from({ length: 256 }, (_, i) => i))],
  ['period7', Buffer.from(Array.from({ length: 300 }, (_, i) => (i * 37) % 7))],
  ['utf8', 'héllo wörld ☃ ☃ ☃ 😀😀'],
];
for (const [name, data] of inputs) {
  const raw = zlib.deflateRawSync(data);
  const z = zlib.deflateSync(data);
  const g = zlib.gzipSync(data);
  console.log(name, 'raw', raw.length, raw.toString('hex'));
  console.log(name, 'zlib', z.toString('hex').slice(0, 4), z.subarray(z.length - 4).toString('hex'),
    z.subarray(2, z.length - 4).equals(raw));
  console.log(name, 'gzip', g.subarray(0, 10).toString('hex'), g.subarray(g.length - 8).toString('hex'),
    g.subarray(10, g.length - 8).equals(raw));
  const back = [zlib.inflateRawSync(raw), zlib.inflateSync(z), zlib.gunzipSync(g), zlib.unzipSync(g)];
  console.log(name, 'roundtrip', back.map((b) => b.equals(Buffer.from(data))).join(','));
}
// Long-distance matches (distance codes up to 29), 258-byte maximum matches and literal runs.
let s = 12345;
const rnd = Buffer.alloc(26000);
for (let i = 0; i < rnd.length; i++) { s = (s * 1103515245 + 12345) & 0x7fffffff; rnd[i] = 97 + ((s >> 16) % 26); }
const big = Buffer.concat([rnd, rnd.subarray(0, 700), Buffer.alloc(2000, 0x41), rnd.subarray(5000, 5600)]);
const c = zlib.deflateRawSync(big);
console.log('big', big.length, c.length, zlib.crc32(c).toString(16), zlib.crc32(zlib.inflateRawSync(c)) === zlib.crc32(big));
const small = Buffer.from('options are ignored, options are ignored! '.repeat(8));
const ref = zlib.deflateSync(small);
const opts = [{ level: 0 }, { level: 1 }, { level: 9, memLevel: 9, strategy: zlib.constants.Z_HUFFMAN_ONLY }, { windowBits: 9 }];
console.log('options ignored', opts.map((o) => zlib.deflateSync(small, o).equals(ref)).join(','), ref.length);
const bunGz = Bun.gzipSync('bun gzip'), bunDf = Bun.deflateSync('bun deflate');
console.log('Bun', bunGz.constructor.name, Buffer.from(bunGz).equals(zlib.gzipSync('bun gzip')),
  Buffer.from(bunDf).toString('hex'), Buffer.from(Bun.inflateSync(bunDf)).toString(), Buffer.from(Bun.gunzipSync(bunGz)).toString());
''')


def test_inflate_foreign_streams(run, workdir):
    """CATCHES: an inflater that only understands its own fixed-Huffman output: Python-zlib streams with
    dynamic Huffman tables (levels 1/9), stored blocks (level 0), sync/full-flush empty stored blocks,
    small windows, Z_HUFFMAN_ONLY/Z_RLE/Z_FIXED strategies and memLevel 1 gzip, plus gzip header
    parsing (FNAME, FEXTRA, FCOMMENT, FHCRC). Also pins the reference's leniency: only the first gzip
    member is returned, trailing garbage and bad CRC/Adler trailers are ignored."""
    _fixture(workdir, "deflate_streams.json")
    check_script(run, workdir, G, "inflate_foreign_streams", r'''
const zlib = require('zlib');
const fs = require('fs');
const fx = JSON.parse(fs.readFileSync('deflate_streams.json', 'utf8'));
const hex8 = (n) => n.toString(16).padStart(8, '0');
for (const [name, f] of Object.entries(fx)) {
  const out = zlib[f.fn](Buffer.from(f.b64, 'base64'));
  const crc = hex8(zlib.crc32(out));
  console.log(name, f.fn, out.length, crc, crc === f.crc && out.length === f.len ? 'match' : 'MISMATCH');
}
const small = {
  fname: 'H4sICADxU2UAA25vdGVzLnR4dABLy8xJVchLzE1NUShIrMzJT0zhAgCRYHp9EwAAAA==',
  all_fields: 'H4sIHwAAAAAC/wgAQUIEAGRhdGF4LmJpbgBhIGNvbW1lbnQA2PlLLUstqlTISE1MSS1SSMtMzUlRKE4tAQDQGJxGFgAAAA==',
  multi_member: 'H4sIAAAAAAAAA0vLLCouUchNzU1KLbIGAJ30W1sNAAAAH4sIAAAAAAAAAytOTc7PS1HITc1NSi0CACR0+p8NAAAA',
  trailing_garbage: 'H4sIAAAAAAAAAytIrMzJT0wBABVqLEIHAAAAAAFnYXJiYWdl',
  bad_crc: 'H4sIAAAAAAAAA0suSlYoz8zJUcjLL1HITSxJzgAA3q2+7xIAAAA=',
};
for (const [name, b64] of Object.entries(small)) {
  const buf = Buffer.from(b64, 'base64');
  console.log(name, JSON.stringify(zlib.gunzipSync(buf).toString()), JSON.stringify(zlib.unzipSync(buf).toString()));
}
const zl = {
  bad_adler: 'eJxLTMlJLVLIzSzOTSxJzgAAAAAAAA==',
  window9: 'GJUrycyrVCjPzEvJL1cowc4GAPYXDbU=',
  two_stored_blocks_raw: 'AAIA/f9BQgEBAP7/Qw==',
};
console.log('bad_adler', JSON.stringify(zlib.inflateSync(Buffer.from(zl.bad_adler, 'base64')).toString()));
console.log('window9', JSON.stringify(zlib.inflateSync(Buffer.from(zl.window9, 'base64')).toString()));
console.log('two_stored', JSON.stringify(zlib.inflateRawSync(Buffer.from(zl.two_stored_blocks_raw, 'base64')).toString()));
''')


def test_inflate_corrupt_input_errors(run, workdir):
    """CATCHES: wrong error type/message for malformed DEFLATE/zlib/gzip input (the reference throws a
    plain Error with no code/errno and messages like 'inflate: distance too far back'), crashing or
    returning garbage instead of throwing, accepting reserved block types, zlib preset-dictionary
    streams being treated specially, unzip auto-detecting zlib framing (the reference's unzip is gunzip),
    and wrong TypeError for unsupported input types. Note: unlike zlib, the reference accepts a dynamic
    block declaring 32 distance codes and only fails if distance symbol 30/31 is actually used."""
    check_script(run, workdir, G, "inflate_corrupt_input_errors", r'''
const zlib = require('zlib');
const show = (label, fn) => {
  try { const r = fn(); console.log(label, 'OK', JSON.stringify(Buffer.from(r).toString('latin1'))); }
  catch (e) { console.log(label, e.name + ': ' + e.message, 'code=' + e.code, 'errno=' + e.errno, e instanceof Error); }
};
const raw = {
  far_distance: 'SwQSAA==', bad_literal: 'SxwD', bad_distance_code: 'SwQ+AAA=', no_end_of_block: 'SwQ=',
  repeat_without_previous: 'BeADBAAAAAAABAAA', truncated_stored: 'AQU=', stored_overrun: 'AQUA+v9BQg==',
  reserved_block: 'BwA=', fixed_zero_run: 'YwACAA==', empty: '',
  code_length_overrun: 'BQCA5P8fAAA=', dynamic_32_distance_codes_ok: 'Dd+BAAAAAIAg1v0lzqRq',
  dynamic_distance_symbol_30: 'Dd+BAAAAAIAg1v0lzqQCAAA=',
};
for (const [name, b64] of Object.entries(raw)) show('raw ' + name, () => zlib.inflateRawSync(Buffer.from(b64, 'base64')));
show('zlib text', () => zlib.inflateSync(Buffer.from('hello world')));
show('zlib short', () => zlib.inflateSync(Buffer.from('78', 'hex')));
show('zlib method', () => zlib.inflateSync(Buffer.from('7a9c4b04000062006201', 'hex')));
show('zlib preset dict', () => zlib.inflateSync(Buffer.from('eLs1KQZry0DjAwA1KQZr', 'base64')));
show('zlib truncated', () => zlib.inflateSync(zlib.deflateSync('some longer text to truncate').subarray(0, 12)));
show('gzip magic', () => zlib.gunzipSync(Buffer.from('not gzip data at all, nope')));
show('gzip short', () => zlib.gunzipSync(zlib.gzipSync('hello').subarray(0, 15)));
show('gzip method', () => { const g = zlib.gzipSync('abc'); g[2] = 7; return zlib.gunzipSync(g); });
show('gzip extra truncated', () => zlib.gunzipSync(Buffer.from('1f8b0804000000000000ff' + '00'.repeat(6) + 'ff', 'hex')));
show('gzip body truncated', () => zlib.gunzipSync(zlib.gzipSync('x'.repeat(50) + 'abcdefghijklmnop').subarray(0, 20)));
show('unzip of zlib data', () => zlib.unzipSync(zlib.deflateSync('abc')));
show('number input', () => zlib.deflateSync(42));
show('object input', () => zlib.gunzipSync({}));
show('crc32 number', () => zlib.crc32(7));
zlib.inflate(Buffer.from('corrupt!'), (err, res) => console.log('callback', err.name + ': ' + err.message, res));
zlib.gunzip(Buffer.from([1, 2, 3]), (err, res) => console.log('callback', err.name + ': ' + err.message, res));
''')


def test_zlib_callback_and_stream_forms(run, workdir):
    """CATCHES: async zlib callbacks invoked synchronously or with the wrong (err, result) shape,
    util.promisify not working on zlib functions, Transform streams (createGzip/createInflateRaw/
    createBrotliCompress/createZstdDecompress/createUnzip) that drop or reorder chunked writes, do not
    work in stream.pipeline, emit data before end(), or do not emit 'error' for corrupt input."""
    check_script(run, workdir, G, "zlib_callback_and_stream_forms", r'''
const zlib = require('zlib');
const { pipeline, Readable, Writable, Transform } = require('stream');
const util = require('util');
console.log('sync start');
zlib.gzip('callback input', (err, out) => console.log('gzip cb', err, out.length, zlib.gunzipSync(out).toString()));
zlib.deflate('with options', { level: 9 }, (err, out) => console.log('deflate cb', err, out.toString('hex')));
zlib.brotliDecompress(zlib.brotliCompressSync('brotli cb'), (err, out) => console.log('brotli cb', err, out.toString()));
zlib.zstdCompress('zstd cb', (err, out) => console.log('zstd cb', err, out.toString('hex')));
zlib.unzip(zlib.gzipSync('unzip cb'), (err, out) => console.log('unzip cb', err, out.toString()));
util.promisify(zlib.inflateRaw)(zlib.deflateRawSync('promisified')).then((b) => console.log('promisify', b.toString()));
const collect = (stream, label) => new Promise((resolve) => {
  const sizes = [];
  const chunks = [];
  stream.on('data', (c) => { sizes.push(c.length); chunks.push(c); });
  stream.on('end', () => { console.log(label, 'chunks', JSON.stringify(sizes)); resolve(Buffer.concat(chunks)); });
});
(async () => {
  const gz = zlib.createGzip({ level: 1 });
  console.log('Gzip is Transform', gz instanceof Transform, typeof zlib.Gzip, gz.constructor.name);
  const p = collect(gz, 'gzip');
  gz.write('abc'); gz.write(Buffer.from('def')); gz.write(new Uint8Array([103, 104, 105]));
  gz.end('jkl');
  const gzOut = await p;
  console.log('gzip stream', gzOut.toString('hex'), zlib.gunzipSync(gzOut).toString());
  const unz = zlib.createUnzip();
  const pu = collect(unz, 'unzip');
  for (let i = 0; i < gzOut.length; i += 7) unz.write(gzOut.subarray(i, i + 7));
  unz.end();
  console.log('unzip stream', (await pu).toString());
  const br = zlib.createBrotliCompress();
  const pb = collect(br, 'brotli');
  br.end(Buffer.from('stream me '.repeat(20)));
  const brOut = await pb;
  console.log('brotli stream', brOut.length, zlib.brotliDecompressSync(brOut).toString().slice(0, 20));
  const received = [];
  await new Promise((resolve) => pipeline(
    Readable.from(['x'.repeat(100), 'y'.repeat(100), 'z'.repeat(56)]),
    zlib.createDeflateRaw(), zlib.createInflateRaw(), zlib.createZstdCompress(), zlib.createZstdDecompress(),
    new Writable({ write(c, e, cb) { received.push(c.length + ':' + c.toString().slice(0, 2) + c.toString().slice(-2)); cb(); } }),
    (err) => { console.log('pipeline done', err, JSON.stringify(received)); resolve(); }));
  const bad = zlib.createGunzip();
  bad.on('data', () => console.log('unexpected data'));
  await new Promise((resolve) => {
    bad.on('error', (e) => { console.log('stream error', e.name + ': ' + e.message); resolve(); });
    bad.write('not gzip, ');
    console.log('written, no error yet');
    bad.end('definitely');
  });
})();
console.log('sync end');
''')


def test_crc32_and_constants(run, workdir):
    """CATCHES: wrong CRC-32 polynomial/finalisation, ignoring or mis-coercing the running-value
    argument (negative values wrap via >>> 0), not accepting strings/TypedArrays/ArrayBuffers (a DataView
    is checksummed as empty by the reference), and missing
    or wrong zlib.constants / zlib.codes entries (Z_* flush and return codes, Brotli and Zstd params)."""
    check_script(run, workdir, G, "crc32_and_constants", r'''
const zlib = require('zlib');
const c = zlib.crc32;
console.log(c(''), c('a'), c('123456789').toString(16), c('hello world'), c('héllo'));
console.log(c('world', c('hello ')) === c('hello world'), c('', 12345), c('a', -1), c('a', 2 ** 32 + 5), c('a', 1.9));
console.log(c(new Uint8Array([1, 2, 3])), c(new Uint8Array([1, 2, 3]).buffer), c(Buffer.alloc(1000, 0xff)), c(new Uint16Array([0x4141, 0x4242])));
// A DataView is not unwrapped: it checksums as if empty.
console.log('dataview', c(new DataView(new Uint8Array([1, 2, 3]).buffer)), c(new DataView(new ArrayBuffer(4)), 77));
let running = 0;
const text = 'The quick brown fox jumps over the lazy dog';
for (const ch of text) running = c(ch, running);
console.log(running, c(text), running === c(text));
const k = zlib.constants;
const names = ['Z_NO_FLUSH', 'Z_SYNC_FLUSH', 'Z_FULL_FLUSH', 'Z_FINISH', 'Z_BLOCK', 'Z_OK', 'Z_STREAM_END',
  'Z_NEED_DICT', 'Z_DATA_ERROR', 'Z_BUF_ERROR', 'Z_BEST_COMPRESSION', 'Z_DEFAULT_COMPRESSION', 'Z_RLE', 'Z_FIXED',
  'Z_DEFAULT_CHUNK', 'Z_MAX_CHUNK', 'Z_MIN_WINDOWBITS', 'GUNZIP', 'UNZIP', 'BROTLI_DECODE', 'BROTLI_ENCODE',
  'BROTLI_PARAM_QUALITY', 'BROTLI_PARAM_LGWIN', 'BROTLI_MAX_QUALITY', 'BROTLI_DEFAULT_WINDOW',
  'BROTLI_LARGE_MAX_WINDOW_BITS', 'BROTLI_DECODER_ERROR_UNREACHABLE', 'ZSTD_COMPRESS', 'ZSTD_DECOMPRESS',
  'ZSTD_c_compressionLevel', 'ZSTD_c_checksumFlag', 'ZSTD_CLEVEL_DEFAULT', 'ZSTD_btultra2', 'ZSTD_error_checksum_wrong'];
console.log(names.map((n) => n + '=' + k[n]).join(' '));
console.log(Object.keys(k).length, Object.keys(k).filter((n) => n.startsWith('BROTLI_DECODER_ERROR')).length);
console.log(JSON.stringify(zlib.codes));
console.log(Object.keys(zlib).filter((n) => typeof zlib[n] === 'function').length, typeof zlib.Inflate, typeof zlib.createBrotliDecompress);
''')


# ---------------------------------------------------------------------------------------------
# Brotli
# ---------------------------------------------------------------------------------------------

def test_brotli_encoder_exact_bytes(run, workdir):
    """CATCHES: a Brotli encoder that differs from the reference's literal-only design: WBITS=22 header,
    ISLAST/ISLASTEMPTY handling, simple prefix codes for <=4 distinct bytes (most frequent first,
    tree-select for 4), complex codes with a balanced code-length code, the uniform-length shortcut,
    length-limited (<=15 bit) Huffman for Fibonacci frequencies, 5-nibble MLEN for >64 KiB and the
    uncompressed meta-block fallback (+ trailing empty last block) when coding would expand."""
    check_script(run, workdir, G, "brotli_encoder_exact_bytes", r'''
const zlib = require('zlib');
const rep = (s, n) => Buffer.from(s.repeat(n));
const inputs = [
  ['empty', Buffer.alloc(0)],
  ['one_byte', Buffer.from('a')],
  ['hello_short_stored', Buffer.from('hello')],
  ['one_symbol', rep('z', 40)],
  ['two_symbols', rep('aab', 20)],
  ['three_symbols', rep('aaabbc', 10)],
  ['four_symbols', rep('aaaabbbccd', 6)],
  ['five_symbols', rep('aaaaaaaabbbbccdee', 6)],
  ['english_stored', rep('The quick brown fox jumps over the lazy dog. ', 6)],
  ['english_coded', rep('The quick brown fox jumps over the lazy dog. ', 40)],
  ['uniform16', Buffer.from(Array.from({ length: 512 }, (_, i) => i % 16))],
  ['all_bytes_stored', Buffer.from(Array.from({ length: 256 }, (_, i) => i))],
];
for (const [name, d] of inputs) {
  const c = zlib.brotliCompressSync(d);
  const hex = c.length <= 72 ? c.toString('hex') : c.toString('hex', 0, 40) + '... crc=' + zlib.crc32(c).toString(16);
  console.log(name, d.length, c.length, hex);
  console.log('  roundtrip', zlib.brotliDecompressSync(c).equals(d), Buffer.compare(zlib.brotliCompressSync(d, { params: { [zlib.constants.BROTLI_PARAM_QUALITY]: 1 } }), c));
}
const same = (a, b) => a.length === b.length && zlib.crc32(a) === zlib.crc32(b);
const fib = [];
{ let a = 1, b = 1; for (let i = 0; i < 20; i++) { fib.push(Buffer.alloc(a, 65 + i)); [a, b] = [b, a + b]; } }
const fibData = Buffer.concat(fib);
const cf = zlib.brotliCompressSync(fibData);
console.log('fibonacci', fibData.length, cf.length, zlib.crc32(cf).toString(16), same(zlib.brotliDecompressSync(cf), fibData));
// > 64 KiB: MLEN needs 5 nibbles. Skewed 20-symbol alphabet -> complex code (no round trip: too slow).
const big = Buffer.concat(new Array(2100).fill(Buffer.from('aaaaabbbbccccddeefghijklmnopqrst')));
const cb = zlib.brotliCompressSync(big);
console.log('big', big.length, cb.length, cb.subarray(0, 12).toString('hex'), zlib.crc32(cb).toString(16));
// Every byte value equally often: coding cannot win, so a stored meta-block + empty last block.
const flat = Buffer.concat(new Array(20).fill(Buffer.from(Array.from({ length: 256 }, (_, i) => i))));
const cr = zlib.brotliCompressSync(flat);
console.log('flat', flat.length, cr.length, cr.subarray(0, 8).toString('hex'), cr.subarray(cr.length - 4).toString('hex'), same(zlib.brotliDecompressSync(cr), flat));
const flatBig = Buffer.concat(new Array(260).fill(flat.subarray(0, 256)));
const crb = zlib.brotliCompressSync(flatBig);
console.log('flat > 64 KiB', flatBig.length, crb.length, crb.subarray(0, 8).toString('hex'), crb.subarray(crb.length - 4).toString('hex'), zlib.crc32(crb).toString(16));
''')


def test_brotli_decoder_reference_streams(run, workdir):
    """CATCHES: a Brotli decoder that only handles its own literal-only output: streams from the real
    encoder at qualities 0-11 use static-dictionary words with transforms, context modelling, block
    switches, NPOSTFIX/NDIRECT distance codes, small/large windows and font/text modes; hand-made
    streams cover metadata and uncompressed meta-blocks. Also pins exact decoder error messages
    (reserved bits, exuberant nibbles, padding, overruns) and the rejection of large-window streams."""
    _fixture(workdir, "brotli_streams.json")
    check_script(run, workdir, G, "brotli_decoder_reference_streams", r'''
const zlib = require('zlib');
const fs = require('fs');
const fx = JSON.parse(fs.readFileSync('brotli_streams.json', 'utf8'));
const hex8 = (n) => n.toString(16).padStart(8, '0');
for (const [name, f] of Object.entries(fx)) {
  try {
    const out = zlib.brotliDecompressSync(Buffer.from(f.b64, 'base64'));
    const crc = hex8(zlib.crc32(out));
    console.log(name, out.length, crc, crc === f.crc && out.length === f.len ? 'match' : 'MISMATCH', JSON.stringify(out.toString('latin1', 0, 12)));
  } catch (e) {
    console.log(name, e.name + ': ' + e.message);
  }
}
const hand = {
  metadata_then_stored: 'LAJtZXRhITAACEhlbGxvLCBYAAhicm90bGkgd29ybGQD',
  window10_stored: 'ISgABHRpbnkgd2luZG93Aw==',
  empty_metadata: 'DAM=',
  only_last_empty: 'Bg==',
  reserved_bit: 'HAA=',
  exuberant_metadata: 'zAIAAA==',
  exuberant_nibble: 'lAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAA',
  stored_overrun: 'MAYQc2hvcnQ=',
  nonzero_padding: 'IADwYWJjAw==',
  metadata_overrun: 'rAR4eHh4eHg=',
  garbage: Buffer.from('hello world').toString('base64'),
  empty_input: '',
};
for (const [name, b64] of Object.entries(hand)) {
  try { console.log(name, JSON.stringify(zlib.brotliDecompressSync(Buffer.from(b64, 'base64')).toString())); }
  catch (e) { console.log(name, e.name + ': ' + e.message); }
}
const good = Buffer.from(fx.text_q11.b64, 'base64');
for (const cut of [1, 2, 10, 100, good.length - 1]) {
  try { console.log('truncated', cut, zlib.brotliDecompressSync(good.subarray(0, cut)).length); }
  catch (e) { console.log('truncated', cut, e.message); }
}
''')


# ---------------------------------------------------------------------------------------------
# Zstandard
# ---------------------------------------------------------------------------------------------

def test_zstd_encoder_exact_frames(run, workdir):
    """CATCHES: a Zstandard encoder that differs from the reference's raw/RLE-block design: single-segment
    frame header with content checksum, 1/2/4-byte frame-content-size encodings (the 2-byte form is
    size-256), RLE blocks only for uniform chunks of >=4 bytes, 128 KiB block splitting, the XXH64
    checksum trailer; plus the Bun.zstd* wrappers returning Uint8Array/Promise."""
    check_script(run, workdir, G, "zstd_encoder_exact_frames", r'''
const zlib = require('zlib');
const cases = [
  ['empty', Buffer.alloc(0)],
  ['hello', Buffer.from('hello')],
  ['three_same_raw', Buffer.from('aaa')],
  ['four_same_rle', Buffer.from('aaaa')],
  ['size255', Buffer.alloc(255, 0x31).fill(0x32, 100)],
  ['size256_rle', Buffer.alloc(256, 7)],
  ['size300', Buffer.from('0123456789'.repeat(30))],
];
for (const [name, d] of cases) {
  const c = zlib.zstdCompressSync(d);
  console.log(name, c.length, c.toString('hex').slice(0, 90), c.length > 45 ? '...' + c.subarray(c.length - 4).toString('hex') : '');
  console.log('  roundtrip', zlib.zstdDecompressSync(c).equals(d));
}
// Large inputs: only the frame layout is printed (multi-block RLE, 4-byte content size).
const big = [
  ['uniform_140000', new Uint8Array(140000).fill(0x42)],
  ['uniform_70000', new Uint8Array(70000).fill(0x43)],
  ['raw_19000', Buffer.concat(new Array(500).fill(Buffer.from('0123456789abcdefghijklmnopqrstuvwxyz!?')))],
];
for (const [name, d] of big) {
  const c = zlib.zstdCompressSync(d);
  const blocks = [];
  let pos = 4 + 1 + ({ 0: 1, 1: 2, 2: 4, 3: 8 })[c[4] >> 6];
  for (;;) {
    const h = c[pos] | (c[pos + 1] << 8) | (c[pos + 2] << 16);
    const type = (h >> 1) & 3, size = h >>> 3;
    blocks.push(['raw', 'rle', 'cmp'][type] + size);
    pos += 3 + (type === 1 ? 1 : size);
    if (h & 1) break;
  }
  console.log(name, d.length, c.length, c.subarray(0, 10).toString('hex'), blocks.join(','), 'checksum', c.subarray(pos).toString('hex'));
}
const raw = zlib.zstdCompressSync(big[2][1]);
console.log('raw_19000 roundtrip', zlib.crc32(zlib.zstdDecompressSync(raw)) === zlib.crc32(big[2][1]));
const b = Bun.zstdCompressSync('bun zstd');
console.log('Bun sync', b.constructor.name, Buffer.from(b).toString('hex'), Buffer.from(Bun.zstdDecompressSync(b)).toString());
const p = Bun.zstdCompress(Buffer.from('bun async'));
console.log('Bun async returns', p instanceof Promise);
p.then((c) => Bun.zstdDecompress(c)).then((d) => console.log('Bun async', d.constructor.name, Buffer.from(d).toString()));
''')


def test_zstd_decoder_reference_frames(run, workdir):
    """CATCHES: a Zstandard decoder limited to raw/RLE blocks: libzstd frames at levels -5..22 exercise
    Huffman literals (1 and 4 streams, FSE-compressed weights), all sequence table modes, repeat
    offsets, small windows, missing content size and content checksums; concatenated and skippable
    frames must be handled. Also pins exact error messages for checksum/size mismatches, reserved bits,
    dictionary ids, reserved block types, oversized blocks and every truncation point."""
    _fixture(workdir, "zstd_streams.json")
    check_script(run, workdir, G, "zstd_decoder_reference_frames", r'''
const zlib = require('zlib');
const fs = require('fs');
const fx = JSON.parse(fs.readFileSync('zstd_streams.json', 'utf8'));
const hex8 = (n) => n.toString(16).padStart(8, '0');
for (const [name, f] of Object.entries(fx)) {
  const out = zlib.zstdDecompressSync(Buffer.from(f.b64, 'base64'));
  const crc = hex8(zlib.crc32(out));
  console.log(name, out.length, crc, crc === f.crc && out.length === f.len ? 'match' : 'MISMATCH');
}
const hand = {
  window_desc_raw_rle_checksum: 'KLUv/QQAUAAAcmF3IGJsb2NrfKMAAFpzV3tb',
  fcs2_rle300: 'KLUv/WAsAGMJAHE=',
  fcs4_raw: 'KLUv/aAFAAAAKQAAZm91ciE=',
  fcs8_raw: 'KLUv/cAQAwAAAAAAAAAZAABhdGU=',
  dictionary_id_zero: 'KLUv/SEABCEAAGRpY3Q=',
  max_window_descriptor: 'KLUv/QD/GQAAYWJj',
  checksum_mismatch: 'KLUv/SQDGQAAYWJjAAAAAA==',
  content_size_mismatch: 'KLUv/SAJGQAAYWJj',
  reserved_header_bit: 'KLUv/SgDGQAAYWJj',
  dictionary_frame: 'KLUv/SIATQAZAABhYmM=',
  reserved_block_type: 'KLUv/SADHwAAYWJj',
  oversized_block: 'KLUv/QAAAWoYYWJj',
  truncated_raw_block: 'KLUv/SAJSQAAYWJj',
  truncated_block_header: 'KLUv/SAJAQ==',
  truncated_checksum: 'KLUv/SQDGQAAYWJjAA==',
  trailing_partial_magic: 'KLUv/SADGQAAYWJjKLU=',
  truncated_skippable: 'XypNGDIAAABzaG9ydA==',
  truncated_skippable_size: 'XypNGAE=',
  only_magic: 'KLUv/Q==',
  truncated_rle_block: 'KLUv/SADGwAA',
  truncated_compressed_block: 'KLUv/SAD9QAAYWI=',
  not_zstd: Buffer.from('hello world').toString('base64'),
  empty_input: '',
};
for (const [name, b64] of Object.entries(hand)) {
  try {
    const out = zlib.zstdDecompressSync(Buffer.from(b64, 'base64'));
    console.log(name, out.length, JSON.stringify(out.toString().slice(0, 24)));
  } catch (e) {
    console.log(name, e.name + ': ' + e.message);
  }
}
''')


def test_zstd_crafted_compressed_blocks(run, workdir):
    """CATCHES: Zstandard compressed-block decoding gaps: RLE and repeat sequence-table modes across
    blocks, repeat-offset history (including the 'offset 1 - 1' rule), 1/2/3-byte literal headers for
    raw/RLE literals, 2-byte sequence counts, direct (4-bit) Huffman weights, treeless literals reusing
    the previous table, 4-stream jump tables; and the exact error for each malformed variant. The valid
    frames decode identically with libzstd; the reference is stricter than libzstd for reserved
    sequence-mode bits and a zero repeat offset (both rejected)."""
    check_script(run, workdir, G, "zstd_crafted_compressed_blocks", r'''
const zlib = require('zlib');
const frames = {
  rle_and_repeat_modes: 'KLUv/SAfVAAAGGFiYwFUAwIGBiwAACl6AfwERQAACCEBVAAAAQE=',
  two_byte_nseq_and_literal_formats: 'KLUv/QAAIAAAUkFXOpUBAIQCMDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDEyMzQ1Njc4OYACVBADAEsB',
  rle_literals_only: 'KLUv/WCIEi0AAI04ASMA',
  raw_literals_fmt3_only: 'KLUv/SARrQAAHAEAdHdlbnR5LWJpdCBoZWFkZXIA',
  err_reserved_seq_modes: 'KLUv/SAMVQAAGGFiYwFVAwIGBg==',
  err_trailing_after_empty_seqs: 'KLUv/SADNQAAGGFiYwCZ',
  err_missing_seq_header: 'KLUv/SADJQAAGGFiYw==',
  err_rle_symbol_range: 'KLUv/SAMVQAAGGFiYwFUJAIGBg==',
  err_treeless_first: 'KLUv/SADJQAAMwAAAA==',
  err_repeat_first: 'KLUv/SAMPQAAGGFiYwH8Bg==',
  err_offset_too_far: 'KLUv/SAMVQAAGGFiYwFUAwYGZA==',
  err_literals_overrun: 'KLUv/SATVQAAGGFiYwFUCgIGBg==',
  err_missing_bitstream: 'KLUv/SAMTQAAGGFiYwFUAwIG',
  err_no_sentinel: 'KLUv/SAMVQAAGGFiYwFUAwIGAA==',
  err_not_consumed: 'KLUv/SAMVQAAGGFiYwFUAwIGNQ==',
  err_truncated_bitstream: 'KLUv/SAMVQAAGGFiYwFUAxQGBg==',
  repeat_offset_minus_one: 'KLUv/SAQVAAAGGFiYwFUAwIGBkUAAAhkAVQAAQAD',
  err_invalid_repeat_offset: 'KLUv/SAQVAAAGGFiYwFUAwIGBEUAAAhkAVQAAQAD',
  err_block_too_large: 'KLUv/QAAdQAADRcRYQFUIwI0AAAAAAQ=',
  err_literals_too_large: 'KLUv/QAALQAADdQwYQA=',
  err_truncated_literals: 'KLUv/SAKJQAAUGFiYw==',
  err_truncated_seq_header: 'KLUv/SADNQAAGGFiY/8B',
  err_truncated_seq_header2: 'KLUv/SADLQAAGGFiY4A=',
  err_missing_modes: 'KLUv/SADLQAAGGFiYwE=',
  err_truncated_rle_table: 'KLUv/SADPQAAGGFiYwFUAw==',
  huffman_direct_weights_then_treeless: 'KLUv/SAHvAEAQsAM4QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEWAC0AADNAAA0A',
  huffman_four_streams: 'KLUv/SAIBQIAhgAP4QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEBAAEAAQAEBwUGAA==',
  huffman_three_symbols_with_sequence: 'KLUv/SAP9QEAYkAN4gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIQjAMBVAYCBgY=',
  huffman_5byte_header_16500: 'KLUv/WB0P3VCAE4HBBIC4QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEEAgQCBAIrkCitAAIATGAooCAUksSEiBWHPzHoWhhUANBtyfZE+NsJEUhAZbfLCJoyKBExnAECAURMTQaoR/BiCwCgRGEpW8xTAWSIQrAZBCAKKaciAFDkWJoRwMNMADAIKkyTJC8UURhZBQpBY36SBEgE6E4QEIAt8VYAKyFIwIF4KGBQGigQSEE1BUSYFEOACTCcS0ADqaxgu0kBDnHPBKzgBCmpXJvRhR1ogQAACNiCQgLNsgAoFIakA0AiYtcFEYJM0CAQxDEAACghkEUPgEcLxmDgncfMNABSggh1OFTUrRQ/5EAsCjVBEOaBAFiIAAQQcgmYEHBAIJAXiLAEA2DZBhUQBIgVENeAOAqEiYEsRSxZ9MEFIAiASPlOAEB2khVFRQSVOxMoEFrDVVQKTIbxCGNCcAawBhiAACWFnCBSCxo4gQgDsCeu7ciGKhUhANEAZWm4CZE4MBQZhIOAQAqCAQCA8AtNQAKACANBA8GEhBiApwJhQmjhAcHgFxHwsBEhnxAOWPRcFZ5YCAAKBkgIKQRg0wAJcAgQapQACRMBSFqkCnIIoEAOQRMGqooiFCAIBAQBoKXCYKSwgDFFiLgnYlCjEiINIiGTQQWGH1Y4rMGLAAMMABoBc0gUDhozIA0CYFl0nguKKI6kjOM4UABTADSIGBMLGQaMgiIihMANADkADJAC4jXRgRtlIVgBnF8CKMooAZoogHyAAdXDKGQEGgfmEgfFBpBgUeT9MgwjwUMJiQG0k1EWAYAAl0QCMFgBSBCPWWkARoYiSJHAc8FQVnZODZAFWAEWRUyUBSh1hTKIiAEMMCjgAmg9BnQbUVFIgmYMSIANMCslT45ZSS8kEAwgCyRgafEd0AEQEDoqLghAQoQGwBAIkABJxwiMQA4oRVIgQSmECghgwAiO1AUXHAgJVVEKkeSROyCWCTaGCGXagSVqBBXDkAqysEBqIKQMOg+RMORtBWCS6EsAGApYGEAZExhkT6qMJDgzxEoQgqR8MwKgwAmBLDgRRIvkJQJBOEIGCSYUimDCQJ4NIDBZAWQLAGWLkJlgoAgE8HCIkwwBz2AqkJWETU+sjLQJHCUJpMX6IoQTQwyciQUIDqhAbYYLymSRMc1GhkAAoEIbuWUhBHIECAwSqFlV5glYlO0EJJEojJWQUlNRGACBPjIUIoRYgow0gg61mUMgJzdwMJEoShIChXDT4gQ4YhkgBW5EK/U6lVIAxQAoA2liEDBEEFwOBSKyrCCJzCVo6qtuMOEi8xQBCEIYNPQDyIJIONKSKj6BSkwMoB0gPosAbhLKgCxiWcKRMEHcSCXijQ0DykgQ2XkpEWDxCHU6lWxMCEKnAQofbmQSBIkKSGBABFICIyCLkXddlgANlSxDhDThJwSHgRhAIkAIHjPcmiAXY2BBk8oKEGcwMAiIAYgsgQsAJKKjhEEBWBESgK5gKUkID0WCFICkQnMEAgEAQKIAFQHAYFBoMJgEQEGQaQCSpKCAICcqEAlEQGKTpWCMSEAmYpoFlQzkIUYvLLdI4sQCIIohFKgNUCSklBwgMKgBas9hAQgGJciFTMMgECIYQkhKYYbaAEYACQ6JAgHYNKSeWIPQzvAgp4Q0ztPYQgBWEIvCAoIPCy7Khp6EotKIBLYUQFP1ZQAkClBpi5YEKcDwEAPEI2gR9IAtAMLkQiQ8AGDpAD2FEhKY1FMJMAiNPAPKowIABIDFVhG2hA0xNLIqI8ixBAUFwLFAAS+kOsDACBw2qayIgZIkyFkSBIhFThMcUOAIydiQMgbQgDIgA6ASLHUIENNhCqJadAdBdg34CQUBLmHEBkoagkRCQ0aYhCKCArABAlCgESOjAOIJGoOCnA64paSAaiO6cLGBrBKBQRdDCNAlI7bKEQ7wAEwwfAwYKKBiB4QBALM2MVgCFKiBkRjSsfGAAIQTYExYEArAxQuQYWTCZNACGIDgRDLOkAwj2HkMBcQGAQSQOGQ7hZJ0QVyZejFoCCYKRofMMNCQXFUKgg4mFyCBYSY1Ygk8IJQ/shRaDAZCrTIsgYOS6GOBVEYBA0SJXAYBAcHjnAUoBDkYkJBYMYx0YAMQuAUPnvaEbSSNEcQwCGWgQVCGmWoYetAABAA8pFAyEYEAAVMmChicCgSUkyXQ2LA4YuIHoCJDkIZAInAEBjwMyBIISQvkaULEgDUokwSMxAh7IWpDIChsAg0gCKIhIJJgFBGwrDWSpxXAYYbYSIchAsb4quRYGCSIIIhCuBcCUIFT1RdTJqakABMQABAjdLD60oASFnFRigQFSi9NBg50sggaRMwzk7I6tJIUl2iGQMcOhBDoCilBiFCdih6kSkAB0iEkRs0OHicIGQkdkdFEiBFgTQsJAgHdMBCCNSzjMYgx2AT3kdAzAhQAgq4nKNDQBCGYzoMXICQIJghcAQjgIEecFiFOkzIjGDYWCEZwARDgIkAKCQSTQiATyQCIiAcYEZrASAlQHAo0lTSBUmIULyIZFVYqACgFlsoHFViWECBGDqRMKiQBUERVVUJTCo2CAmpDwBgdRS/EhFOEYVQQCFkAdXjqDgMweEIAoDwkADkoFgMJCJCo7AgcZIyQU6DMJLRdShJUCE6yBFFHMDJJNJCE20fMfNgoEQwbBhDDuxyMRIVAgRaBAkNsrkYvFQUgrguMbl0gAHeRimGgQRDMJFtIAFVSKyBARJOxAAE2BgaDSCl9bAKSBkVCUIISF2AAvyhrkMyhloQIQoCCEyMYIAgoivAIZI4eizIA',
  err_huf_weight_too_large: 'KLUv/SAEvQEAQsAM4QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAwWAA==',
  err_huf_empty_table: 'KLUv/SAEvQEAQsAM4QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWAA==',
  err_huf_code_too_long: 'KLUv/SAEvQEAQsAM4QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAALsWAA==',
  err_huf_corrupted_weights: 'KLUv/SAEvQEAQsAM4QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAiEWAA==',
  err_huf_truncated_weights: 'KLUv/SAEdQAAQoAC4QAAAAAAAAAAAAA=',
  err_huf_stream_overrun: 'KLUv/SAJvQEAksAM4QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEWAA==',
  err_huf_not_consumed: 'KLUv/SACvQEAIsAM4QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEWAA==',
  err_huf_jump_table_short: 'KLUv/SAIzQEAhkAN4QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEBAAEA',
  err_huf_jump_table_exceeds: 'KLUv/SAIBQIAhgAP4QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEJAAkACQAEBwUGAA==',
  err_huf_fse_desc_truncated: 'KLUv/SAEPQAAQsAAKAECAA==',
  err_huf_missing_tree: 'KLUv/SAEJQAAQgAAAA==',
};
for (const [name, b64] of Object.entries(frames)) {
  try {
    const out = zlib.zstdDecompressSync(Buffer.from(b64, 'base64'));
    console.log(name, out.length, JSON.stringify(out.toString().slice(0, 50)));
  } catch (e) {
    console.log(name, e.name + ': ' + e.message);
  }
}
''')


# Fixed keys generated once with OpenSSL 3.0 (never regenerated: signatures below depend on them).
KEYS = {
    "rsa1024.pem": """-----BEGIN PRIVATE KEY-----
MIICdwIBADANBgkqhkiG9w0BAQEFAASCAmEwggJdAgEAAoGBANJLc8jBc5wpgsoE
iWIdkqDcYYO34UGjVLt9K9iUiFmA5rc8z2Z3gwJk6v+c22xEg1kjV41iIkGQ5Nz/
1uIG2N7GuSIo6Hskm3P9FaJNHL3jNu+dvZqi3Uqf0PFaCpuTeAb3gvl7V6hEF9qp
rp+8IHPunz1MH0rdo5OYTD2A5B4TAgMBAAECgYABuR6MwZEJ8Ykh0KGzjRx7dvLR
mnsdB5KVKrRmROlNGnJJhBUK+OW46kzGpWli3LjazSBVhz1SnjZR3ULMfVPfk54z
LwJKHakCAcN8cMH8PB08cx4odbvS+1EEi3BUuSj+mZbjIMRUVSCkalOZpfwvAeGZ
L4zA5eSbhs3fZ91FMQJBAP0JmDSqmrwc5BB3MdkxghS1f+EYEMNNB67WunvVaITE
I6HzDHx3M7xI5dynkXkAIsYlPz1XWRLqTSaUnht9iWsCQQDUwb+5YRg1bRUJ8NCi
b0oPl5LYe8nORB8evjamfZWBQCioR5lB4GhlBQs4wmtruk1QO4KEFW/QrhxL3akO
UJ/5AkEAiMGSvYQnNNv4dt2010nmoAKoJqO3C5aqPFhZWWwxnO/UwkZ1zR8vmudb
NDJscRUdtjGTSDfZMFvpbpyMBxeGGQJBAK24JdwwM5wsHWmogDKhvE9O7FBngzgw
11g66FS5ZkHLKWd+Tt1DZvpVS/xkg2HLFSXV8ZP4DPzPrbskms1dd8ECQHN0SBGW
noZ9GSuqaYpnkeAhrb5FBTUf1TGu9Nd3TE2v0uAslfv1VDsYHVNi3IVcuPE0i5vn
dZWzzup3JUBWWAs=
-----END PRIVATE KEY-----
""",
    "rsa1024.pkcs1.pem": """-----BEGIN RSA PRIVATE KEY-----
MIICXQIBAAKBgQDSS3PIwXOcKYLKBIliHZKg3GGDt+FBo1S7fSvYlIhZgOa3PM9m
d4MCZOr/nNtsRINZI1eNYiJBkOTc/9biBtjexrkiKOh7JJtz/RWiTRy94zbvnb2a
ot1Kn9DxWgqbk3gG94L5e1eoRBfaqa6fvCBz7p89TB9K3aOTmEw9gOQeEwIDAQAB
AoGAAbkejMGRCfGJIdChs40ce3by0Zp7HQeSlSq0ZkTpTRpySYQVCvjluOpMxqVp
Yty42s0gVYc9Up42Ud1CzH1T35OeMy8CSh2pAgHDfHDB/DwdPHMeKHW70vtRBItw
VLko/pmW4yDEVFUgpGpTmaX8LwHhmS+MwOXkm4bN32fdRTECQQD9CZg0qpq8HOQQ
dzHZMYIUtX/hGBDDTQeu1rp71WiExCOh8wx8dzO8SOXcp5F5ACLGJT89V1kS6k0m
lJ4bfYlrAkEA1MG/uWEYNW0VCfDQom9KD5eS2HvJzkQfHr42pn2VgUAoqEeZQeBo
ZQULOMJra7pNUDuChBVv0K4cS92pDlCf+QJBAIjBkr2EJzTb+HbdtNdJ5qACqCaj
twuWqjxYWVlsMZzv1MJGdc0fL5rnWzQybHEVHbYxk0g32TBb6W6cjAcXhhkCQQCt
uCXcMDOcLB1pqIAyobxPTuxQZ4M4MNdYOuhUuWZByylnfk7dQ2b6VUv8ZINhyxUl
1fGT+Az8z627JJrNXXfBAkBzdEgRlp6GfRkrqmmKZ5HgIa2+RQU1H9UxrvTXd0xN
r9LgLJX79VQ7GB1TYtyFXLjxNIub53WVs87qdyVAVlgL
-----END RSA PRIVATE KEY-----
""",
    "rsa1024.pub.pem": """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDSS3PIwXOcKYLKBIliHZKg3GGD
t+FBo1S7fSvYlIhZgOa3PM9md4MCZOr/nNtsRINZI1eNYiJBkOTc/9biBtjexrki
KOh7JJtz/RWiTRy94zbvnb2aot1Kn9DxWgqbk3gG94L5e1eoRBfaqa6fvCBz7p89
TB9K3aOTmEw9gOQeEwIDAQAB
-----END PUBLIC KEY-----
""",
    "ec.pem": """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgRSOIld071r8X21m8
tINpj7Q9j1BcEepCjBsTKXdAwv+hRANCAARAXKk6dB452nNDeDQXsyRRj3vnAlwL
cXLnmJcw7qCrFAK35srMuH8S6AFrzJIxemNlaVlPAg1U1D0Iv4AWU1zz
-----END PRIVATE KEY-----
""",
    "ec.pub.pem": """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEQFypOnQeOdpzQ3g0F7MkUY975wJc
C3Fy55iXMO6gqxQCt+bKzLh/EugBa8ySMXpjZWlZTwINVNQ9CL+AFlNc8w==
-----END PUBLIC KEY-----
""",
    "ed.pem": """-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIH24LBoOlYjFHVVUnyFrZp9k99VjqQ2/a6+fxZQ1o0nA
-----END PRIVATE KEY-----
""",
    "ed.pub.pem": """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAQ5K/+Lx3LGyCdHkkVdaAaVR7MnOCZ3RdXKDDXMLDUq4=
-----END PUBLIC KEY-----
""",
    "x1.pem": """-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VuBCIEIDCIHxQwSchC0OivaRKZbNWPyMRV2ohwgKOBU1FPBbl7
-----END PRIVATE KEY-----
""",
    "x2.pub.pem": """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VuAyEA1aoxigoUYBg26ACPGz2pYXb2zIfjdbbIywqdR769xwg=
-----END PUBLIC KEY-----
""",
}

# ---------------------------------------------------------------------------------------------
# node:crypto
# ---------------------------------------------------------------------------------------------

def test_hash_digests_and_encodings(run, workdir):
    """CATCHES: wrong MD5/SHA-1/SHA-256/SHA-384/SHA-512/SHA-512-224/SHA-512-256 results at padding
    boundaries (55/56/63/64/111/112/127/128 bytes), wrong digest encodings (hex/base64/base64url/latin1/
    ucs2/buffer), update() not concatenating mixed input encodings and TypedArray/DataView/ArrayBuffer
    views, copy() sharing state, missing 'Digest already called' error, unsupported-algorithm message
    (the reference lists its algorithms; sha224/sha3/ripemd are absent), crypto.hash one-shot defaults."""
    check_script(run, workdir, G, "hash_digests_and_encodings", r'''
const crypto = require('crypto');
const algs = crypto.getHashes();
console.log(JSON.stringify(algs));
for (const a of algs) console.log(a, crypto.createHash(a).update('abc').digest('hex'));
for (const a of algs) console.log(a, 'empty', crypto.createHash(a).digest('base64'));
for (const n of [55, 56, 63, 64, 111, 112, 127, 128, 200]) {
  const data = Buffer.alloc(n, 0x61);
  console.log(n, algs.map((a) => crypto.createHash(a).update(data).digest('hex').slice(0, 16)).join(' '));
}
for (const enc of ['hex', 'base64', 'base64url', 'latin1', 'binary', 'ucs2', 'ascii', 'buffer', undefined]) {
  const d = crypto.createHash('md5').update('x').digest(enc);
  console.log('enc', enc, typeof d, JSON.stringify(Buffer.isBuffer(d) ? 'buf:' + d.toString('hex') : d));
}
try { crypto.createHash('md5').update('x').digest('bogus'); } catch (e) { console.log('enc bogus', e.name + ': ' + e.message); }
const mixed = crypto.createHash('sha1').update('68656c6c6f', 'hex').update('d29ybGQ=', 'base64').update('!', 'latin1')
  .update(new Uint16Array([0x4241])).update(new DataView(new Uint8Array([0x43]).buffer)).update(new Uint8Array([0x44]).buffer).digest('hex');
console.log('mixed', mixed === crypto.createHash('sha1').update('helloworld!ABCD').digest('hex'), mixed);
const base = crypto.createHash('sha512-256').update('part1');
const fork = base.copy();
fork.update('part2');
console.log('copy', base.digest('hex').slice(0, 16), fork.digest('hex').slice(0, 16), crypto.createHash('sha512-256').update('part1part2').digest('hex').slice(0, 16));
const h = crypto.createHash('SHA-256');
h.update('a');
console.log('names', h.digest('hex').slice(0, 16), crypto.createHash('Sha512').digest('hex').slice(0, 8), crypto.createHash('ssl3-md5').digest('hex').slice(0, 8));
try { h.digest(); } catch (e) { console.log('twice', e.name + ': ' + e.message, e.code); }
console.log('update after digest returns', h.update('more') === h);
for (const a of ['sha224', 'sha3-256', 'ripemd160', 'RSA-SHA256', undefined]) {
  try { crypto.createHash(a); console.log(a, 'supported'); } catch (e) { console.log(a, e.name + ': ' + e.message); }
}
for (const v of [123, null, {}, true]) {
  try { crypto.createHash('sha256').update(v); console.log('accepted', v); } catch (e) { console.log('update', JSON.stringify(v), e.name + ': ' + e.message); }
}
console.log('one-shot', crypto.hash('sha1', 'abc'), crypto.hash('md5', 'abc', 'base64'), crypto.hash('sha384', Buffer.from('abc'), 'buffer').length);
console.log(crypto.createHash('sha256').constructor.name, crypto.createHash('md5') instanceof crypto.Hash);
''')


def test_hmac_pbkdf2_hkdf_vectors(run, workdir):
    """CATCHES: HMAC that does not hash keys longer than the block size (64 vs 128 bytes for the SHA-512
    family), wrong ipad/opad, KeyObject keys not accepted; PBKDF2 block counting/truncation errors
    (RFC 6070 and multi-block 70-byte output), missing digest argument error, async pbkdf2/hkdf callbacks
    not deferred; HKDF (RFC 5869) extract/expand errors, ArrayBuffer result type and length limit."""
    check_script(run, workdir, G, "hmac_pbkdf2_hkdf_vectors", r'''
const crypto = require('crypto');
const hx = (s) => Buffer.from(s, 'hex');
const fox = 'The quick brown fox jumps over the lazy dog';
console.log('hmac-md5', crypto.createHmac('md5', 'key').update(fox).digest('hex'));
console.log('hmac-sha1', crypto.createHmac('sha1', 'key').update(fox).digest('hex'));
console.log('hmac-sha256', crypto.createHmac('sha256', 'key').update('The quick brown ').update('fox jumps over the lazy dog').digest('hex'));
// RFC 4231 test case 6: 131-byte key (longer than both block sizes).
const longKey = Buffer.alloc(131, 0xaa);
const tc6 = 'Test Using Larger Than Block-Size Key - Hash Key First';
for (const a of ['sha256', 'sha384', 'sha512']) console.log('rfc4231-6', a, crypto.createHmac(a, longKey).update(tc6).digest('hex'));
console.log('rfc4231-2', crypto.createHmac('sha512', 'Jefe').update('what do ya want for nothing?').digest('base64'));
console.log('hmac-sha512-224', crypto.createHmac('sha512-224', 'k').update('d').digest('hex'));
console.log('key 64 vs 65', crypto.createHmac('sha256', Buffer.alloc(64, 1)).digest('hex').slice(0, 16), crypto.createHmac('sha256', Buffer.alloc(65, 1)).digest('hex').slice(0, 16));
console.log('empty', crypto.createHmac('sha1', '').digest('hex'));
console.log('keyobject', crypto.createHmac('sha384', crypto.createSecretKey(Buffer.from('k'))).update('d').digest('hex') === crypto.createHmac('sha384', 'k').update('d').digest('hex'));
const hm = crypto.createHmac('sha256', 'k');
hm.digest();
try { hm.digest(); } catch (e) { console.log('hmac twice', e.name + ': ' + e.message); }
try { crypto.createHmac('sha256'); } catch (e) { console.log('hmac no key', e.name + ': ' + e.message); }
try { crypto.createHmac('whirlpool', 'k'); } catch (e) { console.log('hmac alg', e.name + ': ' + e.message); }
console.log('pbkdf2 rfc6070-1', crypto.pbkdf2Sync('password', 'salt', 1, 20, 'sha1').toString('hex'));
console.log('pbkdf2 rfc6070-2', crypto.pbkdf2Sync('password', 'salt', 2, 20, 'sha1').toString('hex'));
console.log('pbkdf2 rfc6070-5', crypto.pbkdf2Sync('pass\0word', 'sa\0lt', 3, 16, 'sha1').toString('hex'));
console.log('pbkdf2 sha256', crypto.pbkdf2Sync('passwordPASSWORDpassword', 'saltSALTsaltSALTsaltSALTsaltSALTsalt', 4, 40, 'sha256').toString('hex'));
console.log('pbkdf2 sha512 70', crypto.pbkdf2Sync(Buffer.from('p'), new Uint8Array([115]), 3, 70, 'sha512').toString('base64'));
console.log('pbkdf2 md5/384', crypto.pbkdf2Sync('p', 's', 2, 8, 'md5').toString('hex'), crypto.pbkdf2Sync('p', 's', 2, 8, 'SHA384').toString('hex'));
console.log('pbkdf2 zero length', crypto.pbkdf2Sync('p', 's', 1, 0, 'sha256').length);
try { crypto.pbkdf2Sync('p', 's', 1, 10); } catch (e) { console.log('pbkdf2 no digest', e.name + ': ' + e.message); }
try { crypto.pbkdf2Sync('p', 's', 1, 10, 'sha3'); } catch (e) { console.log('pbkdf2 bad digest', e.name + ': ' + e.message); }
try { crypto.pbkdf2('p', 's', 1, 10, 'sha1'); } catch (e) { console.log('pbkdf2 no callback', e.name + ': ' + e.message); }
const hkdf1 = crypto.hkdfSync('sha256', hx('0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b'), hx('000102030405060708090a0b0c'), hx('f0f1f2f3f4f5f6f7f8f9'), 42);
console.log('hkdf rfc5869-1', hkdf1.constructor.name, Buffer.from(hkdf1).toString('hex'));
console.log('hkdf rfc5869-3', Buffer.from(crypto.hkdfSync('sha256', hx('0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b'), '', '', 42)).toString('hex'));
console.log('hkdf sha1 long', Buffer.from(crypto.hkdfSync('sha1', 'ikm', 'salt', 'info', 50)).toString('base64'));
console.log('hkdf keyobject', Buffer.from(crypto.hkdfSync('sha512', crypto.createSecretKey(Buffer.from('ikm')), 's', 'i', 16)).toString('hex'));
try { crypto.hkdfSync('sha256', 'ikm', 'salt', 'info', 255 * 32 + 1); } catch (e) { console.log('hkdf too long', e.name + ': ' + e.message); }
try { crypto.hkdfSync('sha1', 'ikm', 'salt', 'info', 255 * 20 + 1); } catch (e) { console.log('hkdf sha1 too long', e.name + ': ' + e.message); }
crypto.pbkdf2('p', 's', 2, 16, 'sha256', (err, key) => console.log('pbkdf2 cb', err, key.toString('hex')));
crypto.pbkdf2('p', 's', 2, 16, 'nope', (err, key) => console.log('pbkdf2 cb err', err.name + ': ' + err.message, key));
crypto.hkdf('sha1', 'k', 's', 'i', 8, (err, key) => console.log('hkdf cb', err, key.constructor.name, Buffer.from(key).toString('hex')));
console.log('sync code done');
''')


def test_scrypt_and_argon2_vectors(run, workdir):
    """CATCHES: scrypt ROMix/BlockMix/Salsa20-8 bugs (RFC 7914 vector 1 and a multi-lane r=4,p=2 case),
    option aliases (cost/blockSize/parallelization) and their conflict error, Node-compatible validation
    messages/codes for N/r/p/maxmem, deferred callbacks; Argon2d/i/id disagreeing with the RFC 9106
    test vectors (secret + associated data, 4 lanes, 3 passes) and wrong parameter validation messages."""
    check_script(run, workdir, G, "scrypt_and_argon2_vectors", r'''
const crypto = require('crypto');
console.log('scrypt rfc7914-1', crypto.scryptSync('', '', 64, { N: 16, r: 1, p: 1 }).toString('hex'));
console.log('scrypt r4 p2', crypto.scryptSync('password', 'NaCl', 32, { N: 64, r: 4, p: 2 }).toString('hex'));
console.log('scrypt aliases', crypto.scryptSync('pw', 'salt', 16, { cost: 32, blockSize: 2, parallelization: 2 }).equals(crypto.scryptSync('pw', 'salt', 16, { N: 32, r: 2, p: 2 })));
console.log('scrypt zero r/p fall back', crypto.scryptSync('a', 'b', 8, { N: 16, r: 0, p: 0, maxmem: 0 }).equals(crypto.scryptSync('a', 'b', 8, { N: 16, r: 8, p: 1 })));
const bad = [[{ N: 3 }], [{ N: 1 }], [{ N: 2 ** 20 }], [{ N: 16, cost: 16 }], [{ N: '16' }], [{ r: 1.5 }], [{ p: -1 }],
  [{ maxmem: 1024, N: 16 }], [{ N: null }], [{}, -1], [{}, 'x']];
for (const [opts, len] of bad) {
  try { crypto.scryptSync('a', 'b', len === undefined ? 8 : len, opts); console.log('accepted', JSON.stringify(opts)); }
  catch (e) { console.log('scrypt', JSON.stringify(opts), len, e.name, e.code, e.message); }
}
const p = { message: Buffer.alloc(32, 1), nonce: Buffer.alloc(16, 2), secret: Buffer.alloc(8, 3), associatedData: Buffer.alloc(12, 4),
  parallelism: 4, tagLength: 32, memory: 32, passes: 3 };
for (const alg of ['argon2d', 'argon2i', 'argon2id']) console.log(alg, crypto.argon2Sync(alg, p).toString('hex'));
console.log('argon2id small', crypto.argon2Sync('argon2id', { message: 'password', nonce: 'somesalt', parallelism: 1, tagLength: 16, memory: 64, passes: 2 }).toString('hex'));
const badArgon = [['argon2x', p], ['argon2id', null], ['argon2id', { message: 'a', nonce: 'saltsalt' }],
  ['argon2id', { ...p, nonce: 'short' }], ['argon2id', { ...p, memory: 16 }], ['argon2id', { ...p, tagLength: 3 }],
  ['argon2id', { ...p, passes: 0 }], ['argon2id', { ...p, parallelism: 1.5 }]];
for (const [alg, params] of badArgon) {
  try { crypto.argon2Sync(alg, params); console.log('accepted'); } catch (e) { console.log('argon2', e.name + ': ' + e.message); }
}
crypto.scrypt('a', 'b', 8, { N: 16 }, (err, key) => console.log('scrypt cb', err, key.toString('hex')));
crypto.scrypt('a', 'b', 8, { N: 5 }, (err, key) => console.log('scrypt cb err', err.code, key));
crypto.argon2('argon2i', { message: 'pw', nonce: 'saltsalt', parallelism: 1, tagLength: 16, memory: 8, passes: 1 }, (err, out) => console.log('argon2 cb', err, out.toString('hex')));
try { crypto.scrypt('a', 'b', 8); } catch (e) { console.log('scrypt no cb', e.name + ': ' + e.message); }
console.log('sync code done');
''')


def test_aes_ecb_cbc_ctr_vectors_and_errors(run, workdir):
    """CATCHES: AES key-schedule/round bugs for 128/192/256-bit keys (NIST SP 800-38A ECB/CBC/CTR vectors),
    CBC chaining or CTR keystream state lost across arbitrary update() splits, wrong PKCS#7 padding and
    hold-back of the last block when decrypting, setAutoPadding(false) semantics, cipher name aliases
    and case-insensitivity, and the exact Node/OpenSSL-style error names, codes and messages (invalid key
    length, invalid IV, wrong final block length, bad decrypt, unsupported state/cipher)."""
    check_script(run, workdir, G, "aes_ecb_cbc_ctr_vectors_and_errors", r'''
const crypto = require('crypto');
const hx = (s) => Buffer.from(s, 'hex');
const pt = hx('6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e5130c81c46a35ce411e5fbc1191a0a52eff69f2445df4f9b17ad2b417be66c3710');
const keys = { 128: hx('2b7e151628aed2a6abf7158809cf4f3c'), 192: hx('8e73b0f7da0e6452c810f32b809079e562f8ead2522c6b7b'),
  256: hx('603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4') };
const cbcIv = hx('000102030405060708090a0b0c0d0e0f'), ctrIv = hx('f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff');
const splits = [0, 1, 15, 16, 17, 31, 40, 64];
for (const bits of [128, 192, 256]) {
  for (const mode of ['ecb', 'cbc', 'ctr']) {
    const name = `aes-${bits}-${mode}`;
    const iv = mode === 'ecb' ? null : mode === 'cbc' ? cbcIv : ctrIv;
    const c = crypto.createCipheriv(name, keys[bits], iv).setAutoPadding(false);
    const parts = [];
    for (let i = 0; i + 1 < splits.length; i++) parts.push(c.update(pt.subarray(splits[i], splits[i + 1])));
    parts.push(c.final());
    const ct = Buffer.concat(parts);
    console.log(name, ct.toString('hex'), JSON.stringify(parts.map((p) => p.length)));
    const d = crypto.createDecipheriv(name, keys[bits], iv).setAutoPadding(false);
    console.log('  decrypt', Buffer.concat([d.update(ct.subarray(0, 23)), d.update(ct.subarray(23)), d.final()]).equals(pt));
  }
}
const key = keys[256];
for (const msg of ['', 'hello world', 'exactly 16 bytes', 'a'.repeat(33)]) {
  const c = crypto.createCipheriv('aes-256-cbc', key, cbcIv);
  const ct = c.update(msg, 'utf8', 'hex') + c.final('hex');
  const d = crypto.createDecipheriv('aes-256-cbc', key, cbcIv);
  console.log('padded', JSON.stringify(msg).slice(0, 20), ct, JSON.stringify(d.update(ct, 'hex', 'utf8') + d.final('utf8')));
}
// Each update()/final() chunk is encoded on its own, so base64 output can contain '=' mid-string.
const c64 = crypto.createCipheriv('aes-256-cbc', key, cbcIv);
const ct64 = c64.update('exactly 16 bytes', 'utf8', 'base64') + c64.final('base64');
console.log('base64 chunks', ct64);
try {
  const d64 = crypto.createDecipheriv('aes-256-cbc', key, cbcIv);
  console.log('base64 roundtrip', JSON.stringify(d64.update(ct64, 'base64', 'utf8') + d64.final('utf8')));
} catch (e) { console.log('base64 roundtrip', e.name, e.code, e.message); }
const ctEcb = crypto.createCipheriv('aes-128-ecb', keys[128], '').update('sixteen byte msg', 'latin1', 'hex');
console.log('ecb update holds nothing', ctEcb);
const dd = crypto.createDecipheriv('aes-256-cbc', key, cbcIv);
const one = Buffer.concat([crypto.createCipheriv('aes-256-cbc', key, cbcIv).update('0123456789abcdef'), Buffer.alloc(0)]);
console.log('decipher holds back last block', dd.update(one).length, dd.update(one).length);
const raw = crypto.createDecipheriv('aes-256-cbc', key, cbcIv).setAutoPadding(false);
const padded = crypto.createCipheriv('aes-256-cbc', key, cbcIv);
console.log('padding visible', Buffer.concat([raw.update(Buffer.concat([padded.update('hello world'), padded.final()])), raw.final()]).toString('hex'));
console.log('alias', crypto.createCipheriv('AES128', keys[128], cbcIv).update(pt).toString('hex').slice(0, 32), crypto.createCipheriv('AES-256-CTR', key, ctrIv).update('x').toString('hex'));
const tryIt = (label, fn) => { try { fn(); console.log(label, 'no error'); } catch (e) { console.log(label, e.name, e.code, e.message); } };
tryIt('key length', () => crypto.createCipheriv('aes-256-cbc', keys[128], cbcIv));
tryIt('iv length', () => crypto.createCipheriv('aes-128-cbc', keys[128], cbcIv.subarray(0, 8)));
tryIt('missing iv', () => crypto.createCipheriv('aes-128-ctr', keys[128], null));
tryIt('ecb with iv', () => crypto.createCipheriv('aes-128-ecb', keys[128], cbcIv));
tryIt('unknown cipher', () => crypto.createCipheriv('chacha20-poly1305', Buffer.alloc(32), Buffer.alloc(12)));
tryIt('des', () => crypto.createDecipheriv('des-ede3-cbc', Buffer.alloc(24), Buffer.alloc(8)));
tryIt('no padding partial block', () => { const c = crypto.createCipheriv('aes-128-cbc', keys[128], cbcIv).setAutoPadding(false); c.update('abc'); c.final(); });
tryIt('decrypt partial block', () => { const d = crypto.createDecipheriv('aes-128-cbc', keys[128], cbcIv); d.update(Buffer.alloc(20)); d.final(); });
tryIt('bad padding', () => { const d = crypto.createDecipheriv('aes-128-ecb', keys[128], null); d.update(Buffer.alloc(16)); d.final(); });
tryIt('final twice', () => { const c = crypto.createCipheriv('aes-128-ctr', keys[128], ctrIv); c.final(); c.final(); });
tryIt('update after final', () => { const c = crypto.createCipheriv('aes-128-ctr', keys[128], ctrIv); c.final(); c.update('x'); });
tryIt('getAuthTag on cbc', () => crypto.createCipheriv('aes-128-cbc', keys[128], cbcIv).getAuthTag());
tryIt('setAuthTag on ctr', () => crypto.createDecipheriv('aes-128-ctr', keys[128], ctrIv).setAuthTag(Buffer.alloc(16)));
const ctrWrap = crypto.createCipheriv('aes-128-ctr', keys[128], hx('ffffffffffffffffffffffffffffffff'));
console.log('ctr counter wraps', ctrWrap.update(Buffer.alloc(48)).toString('hex'));
console.log(JSON.stringify(crypto.getCiphers()));
console.log(JSON.stringify(crypto.getCipherInfo('aes-256-gcm')), JSON.stringify(crypto.getCipherInfo('AES192')), JSON.stringify(crypto.getCipherInfo(904)));
console.log(crypto.getCipherInfo('des'), crypto.getCipherInfo(1), JSON.stringify(crypto.getCipherInfo('aes-128-gcm', { ivLength: 8 })),
  crypto.getCipherInfo('aes-128-cbc', { keyLength: 24 }), crypto.getCipherInfo('aes-128-ecb', { ivLength: 16 }), crypto.getCipherInfo('aes-128-cbc', { ivLength: 12 }));
''')


def test_aes_gcm_vectors_and_errors(run, workdir):
    """CATCHES: GCM bugs in GHASH, J0 derivation for non-96-bit IVs (McGrew-Viega test case 6, 60-byte IV),
    AAD handling (multiple setAAD calls concatenate), the 32-bit counter increment, truncated tag lengths,
    streaming decryption with setAuthTag, and wrong errors: tag mismatch ('Unsupported state or unable to
    authenticate data'), invalid authTagLength, setAAD after update, getAuthTag before final."""
    check_script(run, workdir, G, "aes_gcm_vectors_and_errors", r'''
const crypto = require('crypto');
const hx = (s) => Buffer.from(s, 'hex');
const K = hx('feffe9928665731c6d6a8f9467308308');
const P = hx('d9313225f88406e5a55909c5aff5269a86a7a9531534f7da2e4c303d8a318a721c3c0c95956809532fcf0e2449a6b525b16aedf5aa0de657ba637b39');
const A = hx('feedfacedeadbeeffeedfacedeadbeefabaddad2');
const IV = hx('cafebabefacedbaddecaf888');
const run = (name, key, iv, aad, pt, opts) => {
  const c = crypto.createCipheriv(name, key, iv, opts);
  if (aad) c.setAAD(aad);
  const ct = Buffer.concat([c.update(pt.subarray(0, 7)), c.update(pt.subarray(7)), c.final()]);
  return [ct, c.getAuthTag()];
};
let [ct, tag] = run('aes-128-gcm', Buffer.alloc(16), Buffer.alloc(12), null, Buffer.alloc(0));
console.log('tc1', ct.toString('hex'), tag.toString('hex'));
[ct, tag] = run('aes-128-gcm', Buffer.alloc(16), Buffer.alloc(12), null, Buffer.alloc(16));
console.log('tc2', ct.toString('hex'), tag.toString('hex'));
[ct, tag] = run('aes-128-gcm', K, IV, A, P);
console.log('tc4', ct.toString('hex'), tag.toString('hex'));
const tc4 = [ct, tag];
[ct, tag] = run('aes-128-gcm', K, hx('cafebabefacedbad'), A, P);
console.log('tc5 64-bit iv', ct.toString('hex').slice(0, 32), tag.toString('hex'));
[ct, tag] = run('aes-128-gcm', K, hx('9313225df88406e555909c5aff5269aa6a7a9538534f7da1e4c303d2a318a728c3c0c95156809539fcf0e2429a6b525416aedbf5a0de6a57a637b39b'), A, P);
console.log('tc6 60-byte iv', ct.toString('hex').slice(0, 32), tag.toString('hex'));
[ct, tag] = run('aes-192-gcm', hx('feffe9928665731c6d6a8f9467308308feffe9928665731c'), IV, A, P);
console.log('tc10', ct.toString('hex').slice(0, 32), tag.toString('hex'));
[ct, tag] = run('aes-256-gcm', hx('feffe9928665731c6d6a8f9467308308feffe9928665731c6d6a8f9467308308'), IV, A, P);
console.log('tc16', ct.toString('hex').slice(0, 32), tag.toString('hex'));
[ct, tag] = run('aes-256-gcm', Buffer.alloc(32, 7), Buffer.alloc(12, 9), Buffer.alloc(100, 1), Buffer.alloc(1000, 3));
console.log('long', ct.length, crypto.createHash('sha256').update(ct).digest('hex').slice(0, 32), tag.toString('hex'));
for (const n of [4, 8, 12, 13, 16]) {
  const [, t] = run('aes-128-gcm', K, IV, A, P, { authTagLength: n });
  console.log('tag length', n, t.toString('hex'));
}
const d = crypto.createDecipheriv('aes-128-gcm', K, IV);
d.setAAD(A.subarray(0, 5));
d.setAAD(A.subarray(5));
d.setAuthTag(tc4[1]);
console.log('decrypt', Buffer.concat([d.update(tc4[0].subarray(0, 13)), d.update(tc4[0].subarray(13)), d.final()]).equals(P));
const dt = crypto.createDecipheriv('aes-128-gcm', K, IV);
dt.setAAD(A);
dt.setAuthTag(tc4[1].subarray(0, 12));
dt.update(tc4[0]);
console.log('truncated 12-byte tag accepted', Buffer.from(dt.final()).length);
const fail = (label, fn) => { try { fn(); console.log(label, 'no error'); } catch (e) { console.log(label, e.name, e.code, e.message); } };
fail('wrong tag', () => { const x = crypto.createDecipheriv('aes-128-gcm', K, IV); x.setAAD(A); const t = Buffer.from(tc4[1]); t[15] ^= 1; x.setAuthTag(t); x.update(tc4[0]); x.final(); });
fail('wrong aad', () => { const x = crypto.createDecipheriv('aes-128-gcm', K, IV); x.setAAD(Buffer.from('nope')); x.setAuthTag(tc4[1]); x.update(tc4[0]); x.final(); });
fail('missing tag', () => { const x = crypto.createDecipheriv('aes-128-gcm', K, IV); x.update(tc4[0]); x.final(); });
fail('authTagLength 7', () => crypto.createCipheriv('aes-128-gcm', K, IV, { authTagLength: 7 }));
fail('setAuthTag 5 bytes', () => crypto.createDecipheriv('aes-128-gcm', K, IV).setAuthTag(Buffer.alloc(5)));
fail('setAuthTag length mismatch', () => crypto.createDecipheriv('aes-128-gcm', K, IV, { authTagLength: 8 }).setAuthTag(Buffer.alloc(16)));
fail('getAuthTag early', () => crypto.createCipheriv('aes-128-gcm', K, IV).getAuthTag());
fail('setAAD after update', () => { const c = crypto.createCipheriv('aes-128-gcm', K, IV); c.update('x'); c.setAAD(A); });
fail('setAAD on cbc', () => crypto.createCipheriv('aes-128-cbc', K, Buffer.alloc(16)).setAAD(A));
fail('empty iv', () => crypto.createCipheriv('aes-128-gcm', K, Buffer.alloc(0)));
console.log('decipher has getAuthTag', typeof crypto.createDecipheriv('aes-128-gcm', K, IV).getAuthTag, 'cipher has setAuthTag', typeof crypto.createCipheriv('aes-128-gcm', K, IV).setAuthTag);
''')


def test_rsa_pkcs1v15_signatures_fixed_key(run, workdir):
    """CATCHES: RSA PKCS#1 v1.5 signatures that differ from OpenSSL's for the same key (they are
    deterministic), wrong DigestInfo prefixes per hash, createSign/createVerify streaming with base64
    signatures, and PKCS#1 vs PKCS#8 key input."""
    write_files(workdir, {k: v for k, v in KEYS.items() if k.startswith("rsa")})
    check_script(run, workdir, G, "rsa_signatures_fixed_key_a", r'''
const crypto = require('crypto');
const fs = require('fs');
const priv = fs.readFileSync('rsa1024.pem', 'utf8'), pkcs1 = fs.readFileSync('rsa1024.pkcs1.pem', 'utf8'), pub = fs.readFileSync('rsa1024.pub.pem', 'utf8');
const msg = Buffer.from('hello signed world');
const opensslSig = '3209a2f1ebdfa69b197f4755a5918a385ba9d1814cea676f0fa7ddfad7bfeea16a3a7603201e359507da1e53c79dc604a31b6552b5200ec9b19cc3df0038ff26e1f9c0507ea6c601491baeb5de0480bd2cac996dd91899a9981df90be0bdde9b564c2077cb17ebadbaaff7cadfe2255efb54b0be500f0d7228ab1a88f25571ce';
const sig = crypto.sign('sha256', msg, priv);
console.log('pkcs1v15 sha256 equals openssl', sig.toString('hex') === opensslSig, sig.toString('base64'));
console.log('verify', crypto.verify('sha256', msg, pub, sig), crypto.verify('sha256', Buffer.from('tampered'), pub, sig), crypto.verify('sha1', msg, pub, sig));
console.log('sha512', crypto.sign('sha512', msg, pkcs1).toString('hex').slice(0, 48));
const s = crypto.createSign('RSA-SHA256');
s.update('hello ');
s.update('signed world');
const sigB64 = s.sign(pkcs1, 'base64');
const v = crypto.createVerify('sha256');
v.update('hello signed ');
v.update(Buffer.from('world'));
console.log('createSign', sigB64 === sig.toString('base64'), 'createVerify', v.verify(pub, sigB64, 'base64'));
''')


def test_rsa_pss_signatures_fixed_key(run, workdir):
    """CATCHES: RSA-PSS with saltLength 0 (deterministic, equal to OpenSSL's) or a random 32-byte salt not
    verifying, or verifying under the wrong salt length or padding."""
    write_files(workdir, {k: v for k, v in KEYS.items() if k.startswith("rsa")})
    check_script(run, workdir, G, "rsa_signatures_fixed_key_b", r'''
const crypto = require('crypto');
const fs = require('fs');
const priv = fs.readFileSync('rsa1024.pem', 'utf8'), pkcs1 = fs.readFileSync('rsa1024.pkcs1.pem', 'utf8'), pub = fs.readFileSync('rsa1024.pub.pem', 'utf8');
const msg = Buffer.from('hello signed world');
const opensslSig = '3209a2f1ebdfa69b197f4755a5918a385ba9d1814cea676f0fa7ddfad7bfeea16a3a7603201e359507da1e53c79dc604a31b6552b5200ec9b19cc3df0038ff26e1f9c0507ea6c601491baeb5de0480bd2cac996dd91899a9981df90be0bdde9b564c2077cb17ebadbaaff7cadfe2255efb54b0be500f0d7228ab1a88f25571ce';
const P = crypto.constants;
const pss0 = crypto.sign('sha256', msg, { key: priv, padding: P.RSA_PKCS1_PSS_PADDING, saltLength: 0 });
console.log('pss salt0 equals openssl', pss0.toString('hex').slice(0, 40) === '776f39447a1a94be94a2b017bd5089505488b1a2', crypto.verify('sha256', msg, { key: pub, padding: P.RSA_PKCS1_PSS_PADDING, saltLength: 0 }, pss0));
const pssR = crypto.sign('sha256', msg, { key: priv, padding: P.RSA_PKCS1_PSS_PADDING, saltLength: 32 });
console.log('pss salt32', pssR.length, crypto.verify('sha256', msg, { key: pub, padding: P.RSA_PKCS1_PSS_PADDING, saltLength: 32 }, pssR),
  crypto.verify('sha256', msg, { key: pub, padding: P.RSA_PKCS1_PSS_PADDING, saltLength: 0 }, pssR), crypto.verify('sha256', msg, pub, pssR));
''')


def test_rsa_encryption_fixed_key(run, workdir):
    """CATCHES: broken RSA-OAEP (SHA-1 default, SHA-256 with label) and raw no-padding round trips,
    privateEncrypt/publicDecrypt, and the Node 22 refusal of RSA_PKCS1_PADDING for private decryption."""
    write_files(workdir, {k: v for k, v in KEYS.items() if k.startswith("rsa")})
    check_script(run, workdir, G, "rsa_encryption_and_key_formats_a", r'''
const crypto = require('crypto');
const fs = require('fs');
const priv = fs.readFileSync('rsa1024.pem', 'utf8'), pkcs1 = fs.readFileSync('rsa1024.pkcs1.pem', 'utf8'), pub = fs.readFileSync('rsa1024.pub.pem', 'utf8');
const P = crypto.constants;
const k = crypto.createPrivateKey(priv);
const pk = crypto.createPublicKey(pub);
const oaep = crypto.publicEncrypt(pub, Buffer.from('secret message'));
console.log('oaep', oaep.length, crypto.privateDecrypt(k, oaep).toString());
const oaep256 = crypto.publicEncrypt({ key: pk, oaepHash: 'sha256', oaepLabel: Buffer.from('label') }, Buffer.from('labelled'));
try { crypto.privateDecrypt({ key: k, oaepHash: 'sha256' }, oaep256); } catch (e) { console.log('oaep wrong label', e.name, e.message); }
const pkcs1Enc = crypto.publicEncrypt({ key: pub, padding: P.RSA_PKCS1_PADDING }, Buffer.from('pkcs1 msg'));
console.log('pkcs1 encrypt length', pkcs1Enc.length);
try { crypto.privateDecrypt({ key: priv, padding: P.RSA_PKCS1_PADDING }, pkcs1Enc); } catch (e) { console.log('pkcs1 decrypt', e.name, e.message); }
const pe = crypto.privateEncrypt(k, Buffer.from('private enc'));
console.log('privateEncrypt', pe.toString('hex').slice(0, 40), crypto.publicDecrypt(pub, pe).toString());
const raw = Buffer.alloc(128, 0); raw[127] = 42;
console.log('no padding public', crypto.publicEncrypt({ key: pub, padding: P.RSA_NO_PADDING }, raw).toString('hex').slice(0, 40));
''')


def test_rsa_key_formats_fixed_key(run, workdir):
    """CATCHES: wrong RSA asymmetricKeyDetails and PKCS#1/PKCS#8/SPKI PEM+DER and JWK import/export that
    does not reproduce OpenSSL's encodings byte for byte, or a malformed PEM being accepted."""
    write_files(workdir, {k: v for k, v in KEYS.items() if k.startswith("rsa")})
    check_script(run, workdir, G, "rsa_encryption_and_key_formats_b", r'''
const crypto = require('crypto');
const fs = require('fs');
const priv = fs.readFileSync('rsa1024.pem', 'utf8'), pkcs1 = fs.readFileSync('rsa1024.pkcs1.pem', 'utf8'), pub = fs.readFileSync('rsa1024.pub.pem', 'utf8');
const P = crypto.constants;
const k = crypto.createPrivateKey(priv);
const pk = crypto.createPublicKey(pub);
console.log(k.type, k.asymmetricKeyType, JSON.stringify(k.asymmetricKeyDetails, (_, x) => (typeof x === 'bigint' ? 'bigint:' + x : x)));
console.log('pkcs1 pem', k.export({ type: 'pkcs1', format: 'pem' }) === pkcs1, 'pkcs8 pem', k.export({ type: 'pkcs8', format: 'pem' }) === priv);
console.log('pkcs1 import', crypto.createPrivateKey(pkcs1).export({ type: 'pkcs8', format: 'der' }).equals(k.export({ type: 'pkcs8', format: 'der' })));
const derived = crypto.createPublicKey(priv);
console.log(derived.type, 'spki pem', derived.export({ type: 'spki', format: 'pem' }) === pub, derived.export({ type: 'pkcs1', format: 'der' }).toString('hex').slice(0, 24));
const jwk = pk.export({ format: 'jwk' });
console.log(JSON.stringify(jwk));
console.log('jwk roundtrip', crypto.createPublicKey({ key: jwk, format: 'jwk' }).export({ type: 'spki', format: 'pem' }) === pub);
console.log('der import', crypto.createPublicKey({ key: pk.export({ type: 'spki', format: 'der' }), format: 'der', type: 'spki' }).equals(pk));
try { crypto.createPrivateKey('not a pem'); } catch (e) { console.log('bad pem', e.name, e.message); }
''')


def test_ed25519_fixed_key(run, workdir):
    """CATCHES: Ed25519 signatures differing from OpenSSL's for the same seed (RFC 8032 is
    deterministic), verify accepting a different message, and wrong OKP JWK/SPKI export (public x / private d)."""
    write_files(workdir, {k: v for k, v in KEYS.items() if k.startswith(("ed", "x"))})
    check_script(run, workdir, G, "ed25519_and_x25519_fixed_keys_a", r'''
const crypto = require('crypto');
const fs = require('fs');
const read = (f) => fs.readFileSync(f, 'utf8');
const msg = Buffer.from('hello signed world');
const edKey = crypto.createPrivateKey(read('ed.pem')), edPub = crypto.createPublicKey(read('ed.pub.pem'));
const edSig = crypto.sign(null, msg, edKey);
console.log('ed25519 equals openssl', edSig.toString('hex') === 'd41be7610372ff4b6a6f930aeb44d9da990b2a31eb814baa5a861a6cfe4b7fac90b73b9284a9b5937da40922a53276f734c98c7f1ee6031b0024bf958a820603', edSig.toString('base64url'));
console.log('ed25519 verify', crypto.verify(null, msg, edPub, edSig), crypto.verify(undefined, Buffer.from('other'), edPub, edSig));
console.log(edKey.type, edKey.asymmetricKeyType, edPub.type, JSON.stringify(edPub.export({ format: 'jwk' })), JSON.stringify(edKey.export({ format: 'jwk' })));
console.log('spki', edPub.export({ type: 'spki', format: 'der' }).toString('hex'));
''')


def test_x25519_fixed_keys(run, workdir):
    """CATCHES: X25519 shared secrets differing from OpenSSL's for the same key pair, a wrong X25519
    public JWK export, or crypto.diffieHellman not rejecting a call without a public key."""
    write_files(workdir, {k: v for k, v in KEYS.items() if k.startswith(("ed", "x"))})
    check_script(run, workdir, G, "ed25519_and_x25519_fixed_keys_b", r'''
const crypto = require('crypto');
const fs = require('fs');
const read = (f) => fs.readFileSync(f, 'utf8');
const msg = Buffer.from('hello signed world');
const x1 = crypto.createPrivateKey(read('x1.pem')), x2 = crypto.createPublicKey(read('x2.pub.pem'));
const shared = crypto.diffieHellman({ privateKey: x1, publicKey: x2 });
console.log('x25519 equals openssl', shared.toString('hex') === '72262f1ba539bcdc9d4154e51b08c9e89fb3484a182c636a673004bea2590f49', shared.length, x1.asymmetricKeyType, JSON.stringify(x2.export({ format: 'jwk' })));
try { crypto.diffieHellman({ privateKey: x1 }); } catch (e) { console.log('missing key', e.name, e.message); }
''')


def test_ecdsa_p256_der_signatures(run, workdir):
    """CATCHES: ECDSA P-256 DER signatures (random nonce, so only the DER framing and verification are
    asserted) that do not verify, or that verify a different message."""
    write_files(workdir, {k: v for k, v in KEYS.items() if k.startswith("ec")})
    check_script(run, workdir, G, "ecdsa_p256_fixed_key_a", r'''
const crypto = require('crypto');
const fs = require('fs');
const ec = crypto.createPrivateKey(fs.readFileSync('ec.pem', 'utf8')), ecPubPem = fs.readFileSync('ec.pub.pem', 'utf8');
const ecPub = crypto.createPublicKey(ecPubPem);
const msg = Buffer.from('hello signed world');
const der = crypto.sign('sha256', msg, ec);
console.log('der', der[0].toString(16), der[2].toString(16), crypto.verify('sha256', msg, ecPub, der), crypto.verify('sha256', Buffer.from('x'), ecPub, der));
''')


def test_ecdsa_p256_p1363_and_key_export(run, workdir):
    """CATCHES: ECDSA P-256 IEEE-P1363 signatures of the wrong length or that do not verify, wrong EC key
    details/JWK/SEC1 export, and SPKI export that differs from OpenSSL's PEM."""
    write_files(workdir, {k: v for k, v in KEYS.items() if k.startswith("ec")})
    check_script(run, workdir, G, "ecdsa_p256_fixed_key_b", r'''
const crypto = require('crypto');
const fs = require('fs');
const ec = crypto.createPrivateKey(fs.readFileSync('ec.pem', 'utf8')), ecPubPem = fs.readFileSync('ec.pub.pem', 'utf8');
const ecPub = crypto.createPublicKey(ecPubPem);
const msg = Buffer.from('hello signed world');
const p1363 = crypto.sign('sha256', msg, { key: ec, dsaEncoding: 'ieee-p1363' });
console.log('p1363', p1363.length, crypto.verify('sha256', msg, { key: ecPub, dsaEncoding: 'ieee-p1363' }, p1363));
console.log(ec.asymmetricKeyType, JSON.stringify(ec.asymmetricKeyDetails), JSON.stringify(ec.export({ format: 'jwk' })));
console.log('spki pem', ecPub.export({ type: 'spki', format: 'pem' }) === ecPubPem, ec.export({ type: 'sec1', format: 'der' }).toString('hex').slice(0, 20));
''')


def test_ecdh_p256_fixed_private_keys(run, workdir):
    """CATCHES: ECDH on P-256 with fixed private keys producing wrong public points or shared secrets,
    wrong compressed/hybrid point encodings and their acceptance as computeSecret input, encodings on
    get/set/computeSecret, and the exact errors for unsupported curves, out-of-range private keys,
    points not on the curve, unknown encodings and missing keys."""
    check_script(run, workdir, G, "ecdh_p256_fixed_private_keys", r'''
const crypto = require('crypto');
const a = crypto.createECDH('prime256v1');
a.setPrivateKey(Buffer.alloc(32, 1));
const b = crypto.createECDH('P-256');
b.setPrivateKey('02'.repeat(32), 'hex');
console.log('pubA', a.getPublicKey('hex'));
console.log('pubB', b.getPublicKey('hex', 'compressed'), b.getPublicKey('base64', 'hybrid'));
const s1 = a.computeSecret(b.getPublicKey());
console.log('secret', s1.toString('hex'), s1.toString('hex') === b.computeSecret(a.getPublicKey('hex', 'compressed'), 'hex', 'hex'));
console.log('hybrid input', a.computeSecret(b.getPublicKey(null, 'hybrid')).equals(s1), a.getPrivateKey('base64'));
const tryIt = (label, fn) => { try { fn(); console.log(label, 'no error'); } catch (e) { console.log(label, e.name, e.message); } };
tryIt('curve', () => crypto.createECDH('secp384r1'));
tryIt('zero private', () => a.setPrivateKey(Buffer.alloc(32, 0)));
tryIt('private >= n', () => a.setPrivateKey(Buffer.alloc(32, 0xff)));
tryIt('off curve', () => a.computeSecret(Buffer.from('04' + '11'.repeat(64), 'hex')));
tryIt('bad encoding', () => a.computeSecret(Buffer.from('05' + '11'.repeat(32), 'hex')));
tryIt('no private', () => crypto.createECDH('prime256v1').computeSecret(b.getPublicKey()));
tryIt('no public', () => crypto.createECDH('prime256v1').getPublicKey());
tryIt('bad format', () => a.getPublicKey('hex', 'squashed'));
''')

def test_secret_keys_dh_timing_safe_and_webcrypto(run, workdir):
    """CATCHES: KeyObject secret keys with wrong type/size/export/JWK/equals, generateKeySync validation,
    finite-field Diffie-Hellman with fixed private keys (modp14 group and a tiny explicit group, including
    the reference quirk that a Buffer generator in the 2nd argument is treated as an encoding and the
    default generator 2 is used), DH error messages, timingSafeEqual length errors, random* output shapes,
    and the reference's WebCrypto subtle surface (SHA-256 digest only, NotSupportedError otherwise)."""
    check_script(run, workdir, G, "secret_keys_dh_timing_safe_and_webcrypto", r'''
const crypto = require('crypto');
const sk = crypto.createSecretKey(Buffer.from('my secret key'));
console.log(sk.type, sk.symmetricKeySize, sk.asymmetricKeyType, sk instanceof crypto.KeyObject, sk.export().toString(), JSON.stringify(sk.export({ format: 'jwk' })));
console.log('equals', sk.equals(crypto.createSecretKey('my secret key', 'utf8')), sk.equals(crypto.createSecretKey(Buffer.from('other'))), sk.equals(crypto.createSecretKey('6d7920736563726574206b6579', 'hex')));
const gk = crypto.generateKeySync('hmac', { length: 64 });
const ak = crypto.generateKeySync('aes', { length: 256 });
console.log('generated', gk.type, gk.symmetricKeySize, ak.symmetricKeySize, ak.export().length);
for (const [t, o] of [['aes', { length: 100 }], ['rsa', { length: 128 }], ['hmac', { length: 1.5 }]]) {
  try { crypto.generateKeySync(t, o); console.log('accepted'); } catch (e) { console.log('generateKeySync', t, e.name + ': ' + e.message); }
}
const a = crypto.getDiffieHellman('modp14'), b = crypto.createDiffieHellmanGroup('MODP14');
a.setPrivateKey(Buffer.alloc(32, 0x11));
b.setPublicKey(Buffer.from('ab'.repeat(256), 'hex'));
const s = a.computeSecret(b.getPublicKey('base64'), 'base64');
console.log('modp14', s.length, s.toString('hex').slice(0, 48));
console.log('modp14 params', a.getPrime('hex').slice(0, 24), a.getPrime().length, a.getGenerator('hex'), a.verifyError, a.getPublicKey('hex').slice(0, 24), a.getPrivateKey('hex').slice(0, 8));
const g1 = crypto.createDiffieHellman(Buffer.from([23]), Buffer.from([5]));
console.log('buffer generator ignored', g1.getGenerator('hex'), g1.getPrime('hex'));
const e = crypto.createDiffieHellman(Buffer.from([23]), 5);
e.setPrivateKey(Buffer.from([6]));
const f = crypto.createDiffieHellman('17', 'hex', '05', 'hex');
f.setPrivateKey(Buffer.from([15]));
console.log('tiny group', e.getGenerator('hex'), e.getPublicKey('hex'), f.getPublicKey('hex'), f.computeSecret(e.getPublicKey()).toString('hex'), e.computeSecret(f.getPublicKey(), null, 'hex'));
const tryIt = (label, fn) => { try { const r = fn(); console.log(label, 'ok', r); } catch (x) { console.log(label, x.name + ': ' + x.message); } };
tryIt('group', () => crypto.getDiffieHellman('modp2'));
tryIt('small key', () => e.computeSecret(Buffer.from([1])));
tryIt('private range', () => e.setPrivateKey(Buffer.from([22])));
tryIt('bad params', () => crypto.createDiffieHellman(Buffer.from([3])));
tryIt('no public', () => crypto.createDiffieHellman(Buffer.from([23])).getPublicKey());
tryIt('no private', () => crypto.createDiffieHellman(Buffer.from([23])).computeSecret(Buffer.from([5])));
console.log('timingSafeEqual', crypto.timingSafeEqual(Buffer.from('abc'), Buffer.from('abc')), crypto.timingSafeEqual(new Uint8Array([1, 2]), new Uint8Array([1, 3])), crypto.timingSafeEqual(new Uint16Array([1]), Buffer.from([1, 0])));
tryIt('timingSafeEqual lengths', () => crypto.timingSafeEqual(Buffer.from('a'), Buffer.from('ab')));
console.log('random shapes', crypto.randomBytes(8).length, crypto.randomUUID().replace(/[0-9a-f]/g, 'x'), /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(crypto.randomUUID()),
  Number.isInteger(crypto.randomInt(10)), crypto.randomInt(5, 6), crypto.getRandomValues(new Uint8Array(4)).length, crypto.randomFillSync(Buffer.alloc(3)).length);
tryIt('randomInt range', () => crypto.randomInt(5, 5));
console.log('webcrypto', crypto.webcrypto === globalThis.crypto, typeof crypto.subtle.digest, typeof crypto.subtle.importKey, typeof crypto.subtle.sign);
(async () => {
  for (const alg of ['SHA-256', { name: 'SHA-256' }, 'SHA-1', 'SHA-512']) {
    try {
      const d = await crypto.subtle.digest(alg, new TextEncoder().encode('abc'));
      console.log('subtle', JSON.stringify(alg), d.constructor.name, Buffer.from(d).toString('hex'));
    } catch (x) { console.log('subtle', JSON.stringify(alg), x.name + ': ' + x.message); }
  }
})();
''')
