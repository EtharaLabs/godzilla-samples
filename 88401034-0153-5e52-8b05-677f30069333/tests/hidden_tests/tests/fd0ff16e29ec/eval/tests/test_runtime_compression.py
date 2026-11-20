"""node:zlib (deflate/inflate/raw/gzip/gunzip/unzip, Brotli, Zstandard, crc32; sync, callback, promisified and
Transform-stream forms), CompressionStream/DecompressionStream and Bun's compression helpers.

Decoders are fed streams produced by the reference C libraries (Python's zlib, libbrotlienc and libzstd at many
levels/window sizes/strategies, real-world .br/.gz files and a Go zstd test vector) that live as binary fixtures under
test_resources/test_runtime_compression/; the original plaintexts sit next to them. Corrupt-input tests mutate those
streams or use hand-assembled bitstreams to reach the decoders' error branches. Encoder output is pinned byte-for-byte
(it is the reference behaviour) and always round-tripped. Outputs are kept small: the zlib wrappers copy every
result into a Buffer, which dominates run time (especially under the coverage-instrumented binary).
"""

import shutil

import pytest

from conftest import golden, resources_for, write_files

FIXTURES = resources_for(__file__)


def _copy_fixtures(workdir, names):
    for name in names:
        shutil.copy(FIXTURES / name, workdir / name)


def _ok(r, name):
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, name)


# Decodes every file named on the command line with the codec chosen by its extension and prints the decoded size,
# its CRC-32 and a prefix; `text.txt`/`random.bin` originals are summarised the same way so the golden shows the
# decoded output matches them (underscore.min.js has CRC e4b7c543, text3k is the first 3000 bytes of text.txt).
DECODE_JS = r"""
const fs = require('fs'), zlib = require('zlib');
const dec = { zz: zlib.inflateSync, raw: zlib.inflateRawSync, gz: zlib.gunzipSync, br: zlib.brotliDecompressSync, zst: zlib.zstdDecompressSync };
const hex8 = (n) => n.toString(16).padStart(8, '0');
for (const f of process.argv.slice(2)) {
  const data = fs.readFileSync(f);
  const fn = dec[f.split('.').pop()];
  let line;
  try {
    const out = fn ? fn(data) : data;
    line = `${out.length} crc=${hex8(zlib.crc32(out))} ${Buffer.isBuffer(out)} ${JSON.stringify(out.subarray(0, 32).toString('latin1'))}`;
  } catch (e) {
    line = `${e.name}: ${e.message}`;
  }
  console.log(f, data.length, line);
}
"""


def _decode(run, workdir, files):
    _copy_fixtures(workdir, files)
    write_files(workdir, {"decode.js": DECODE_JS})
    return run(["decode.js", *files])


def test_inflate_reference_zlib_streams(run, workdir):
    """CATCHES: inflate implementations that only handle the encoder's own output and break on zlib-wrapped streams
    using stored blocks (level 0) or the fast/best dynamic Huffman blocks of levels 1 and 9."""
    files = ["text.txt", "text.l0.zz", "text.l1.zz", "text.l9.zz"]
    _ok(_decode(run, workdir, files), "inflate_reference")


def test_inflate_reference_strategy_streams(run, workdir):
    """CATCHES: inflate bugs with the Huffman-only, RLE (distance-1 matches only) and fixed-Huffman-only strategies
    of the zlib library."""
    files = ["text.huff.zz", "runs.rle.zz", "text.fixed.zz"]
    _ok(_decode(run, workdir, files), "inflate_strategies")


def test_inflate_reference_raw_and_small_window_streams(run, workdir):
    """CATCHES: inflate bugs with a 512-byte window (wbits=9, filtered strategy), raw deflate without a zlib wrapper,
    sync/full-flush empty stored blocks between blocks, or incompressible input."""
    files = ["text.filtered.w9.zz", "text.l6.raw", "text.flushes.raw", "random.bin", "random.l9.raw"]
    _ok(_decode(run, workdir, files), "inflate_raw_small_window")


def test_gunzip_reference_streams(run, workdir):
    """CATCHES: gunzip implementations that mishandle optional gzip header fields (FTEXT, FHCRC, FEXTRA, FNAME,
    FCOMMENT) or fail on a real-world .gz file made by the gzip tool."""
    files = ["text.l6.gz", "text3k.headers.gz", "underscore.min.js.gz"]
    _ok(_decode(run, workdir, files), "gunzip_reference")


def test_brotli_reference_streams_fast_levels(run, workdir):
    """CATCHES: Brotli decoders that break on libbrotlienc's fast encoders (quality 0/1: uncompressed and compressed
    meta-blocks, complex prefix codes), quality 4 block splitting, or a 10-bit window at quality 5."""
    files = ["text.q0.br", "text.q1.br", "text.q4.br", "text.q5.w10.br"]
    _ok(_decode(run, workdir, files), "brotli_reference_fast")


def test_brotli_reference_streams_high_levels(run, workdir):
    """CATCHES: Brotli decoders that break on context-modelled quality 9/11 streams (static-dictionary words with
    transforms, literal and distance context maps), text mode, NPOSTFIX/NDIRECT distance parameters, or flushed
    streams made of many meta-blocks."""
    files = ["text.q9.text.br", "text.q9.postfix.br", "text.q5.flushes.br", "text.q11.br"]
    _ok(_decode(run, workdir, files), "brotli_reference_high")


def test_brotli_real_world_streams(run, workdir):
    """CATCHES: Brotli decoders that fail on a real-world .br file shipped by a Linux distribution (made by the
    brotli CLI) or on a font-mode quality-7 stream of the same JavaScript source."""
    files = ["underscore.min.js.br", "underscore.q7.font.br"]
    _ok(_decode(run, workdir, files), "brotli_real_world")


def test_brotli_incompressible_and_large_window(run, workdir):
    """CATCHES: Brotli decoders that mishandle incompressible data (uncompressed meta-blocks) or that silently accept
    large-window streams instead of reporting that they are unsupported."""
    files = ["random.bin", "random.q6.br", "text.largewin.br"]
    _ok(_decode(run, workdir, files), "brotli_incompressible")


def test_zstd_reference_streams(run, workdir):
    """CATCHES: Zstandard decoders that break on libzstd frames at levels 1/3/9/19 (Huffman literals, FSE, RLE,
    predefined and repeat sequence tables, repeat offsets), frames without a content size, or content checksums."""
    files = ["text.l1.zst", "text.l3.check.zst", "text.l9.nosize.zst", "text.l19.check.zst"]
    _ok(_decode(run, workdir, files), "zstd_reference")


def test_zstd_multiblock_streams(run, workdir):
    """CATCHES: Zstandard decoders that mishandle frames made of many blocks (streaming flushes): treeless literals
    and repeat-mode tables reused from the previous block, matches into earlier blocks, a frame-wide checksum."""
    files = ["text.l1.flushes.zst", "text.l6.flushes.zst", "text.l19.flushes.zst"]
    _ok(_decode(run, workdir, files), "zstd_multiblock")


def test_zstd_raw_rle_and_concatenated_frames(run, workdir):
    """CATCHES: Zstandard decoders that fail on raw blocks (incompressible data), RLE blocks (20 KB of zeros),
    concatenated frames with a skippable frame between them, or the Go standard library's zero-dictionary-ID vector."""
    files = ["random.l3.zst", "zeros20k.l3.zst", "multi.zst", "go.zero-dictionary-ids.zst"]
    _ok(_decode(run, workdir, files), "zstd_raw_rle_multi")


# Hand-assembled zstd frames (raw/RLE literals with 1/2/3-byte headers, RLE-mode sequence tables, repeat offsets,
# repeat-mode tables across blocks, every frame-header field size) and minimal corruptions of each structure.
CRAFTED_ZSTD_JS = r"""
const zlib = require('zlib');
for (const [label, hex] of [
  ['seq-rle-copy', '28b52ffd200755000018616263015403020106'],
  ['seq-repeat-offset', '28b52ffd200755000018616263015403000101'],
  ['two-blocks-repeat-tables', '28b52ffd200e540000186162630154030201063d00001861626301fc06'],
  ['lit-rle', '28b52ffd20041d0000217a00'],
  ['lit-raw-2byte-hdr', '28b52ffd2005450000540068656c6c6f00'],
  ['lit-raw-3byte-hdr', '28b52ffd20054d00005c000068656c6c6f00'],
  ['lit-rle-3byte-hdr', '28b52ffd20052d00005d00007100'],
  ['window-descriptor', '28b52ffd00004b000077'],
  ['fcs-4-bytes', '28b52ffda0050000002b000061'],
  ['fcs-8-bytes', '28b52ffde005000000000000002b000061'],
  ['fcs-2-bytes', '28b52ffd60000003080061'],
  ['did-2-bytes-zero', '28b52ffd220000031b000061'],
  ['did-4-bytes-zero', '28b52ffd2300000000031b000061'],
  ['err-trailing-after-empty-seq', '28b52ffd2003350000186162630000'],
  ['err-seq-header-255', '28b52ffd200335000018616263ff01'],
  ['err-seq-header-long', '28b52ffd20033d000018616263ff0000'],
  ['err-seq-header-128', '28b52ffd20032d00001861626380'],
  ['err-missing-seq-header', '28b52ffd200325000018616263'],
  ['err-rle-symbol-range', '28b52ffd200755000018616263015424020106'],
  ['err-rle-table-truncated', '28b52ffd20073d000018616263015403'],
  ['err-fse-table-truncated', '28b52ffd2007350000186162630180'],
  ['err-missing-bitstream', '28b52ffd20074d0000186162630154030201'],
  ['err-no-sentinel', '28b52ffd200755000018616263015403020100'],
  ['err-bitstream-short', '28b52ffd200755000018616263015403020101'],
  ['err-bitstream-leftover', '28b52ffd200755000018616263015403020116'],
  ['err-invalid-repeat-offset', '28b52ffd200755000018616263015400010103'],
  ['err-regenerated-too-large', '28b52ffd0000650000186162630154030234ffff06'],
  ['err-literals-overrun', '28b52ffd20075500001861626301540a020106'],
  ['err-repeat-without-previous', '28b52ffd20073d00001861626301fc06'],
  ['err-reserved-seq-mode-bits', '28b52ffd200755000018616263015703020106'],
  ['err-raw-literals-too-large', '28b52ffd0000250000fcffff00'],
  ['err-compressed-literals-too-large', '28b52ffd0000350000feff7f000000'],
  ['err-literals-jump-table', '28b52ffd00003d000046c60081100000'],
  ['err-treeless-without-table', '28b52ffd0000350000438000008000'],
  ['err-lit-truncated-2byte', '28b52ffd00000d000054'],
  ['err-huffman-direct-truncated', '28b52ffd00004d0000424001ff0102030400'],
  ['err-huffman-fse-truncated', '28b52ffd0000350000428000400100'],
]) {
  try {
    const o = zlib.zstdDecompressSync(Buffer.from(hex, 'hex'));
    console.log(label, 'OK', o.length, JSON.stringify(o.subarray(0, 24).toString('latin1')));
  } catch (e) {
    console.log(label, e.name + ':', e.message);
  }
}
"""


def test_zstd_crafted_blocks(run, workdir):
    """CATCHES: Zstandard decoders that mis-parse literal-section header sizes, RLE/repeat sequence-table modes, the
    repeat-offset history, 2/4/8-byte content sizes, dictionary-ID fields or window descriptors, or that report the
    wrong error for malformed sequence headers, tables, bitstreams and oversized literal sections."""
    write_files(workdir, {"crafted.js": CRAFTED_ZSTD_JS})
    _ok(run(["crafted.js"]), "zstd_crafted")


def test_brotli_block_switching_streams(run, workdir):
    """CATCHES: Brotli decoders whose block-type switching (explicit types, "previous" and "next" type codes, block
    length codes) or per-block-type context maps break on mixed text/digit/binary input split into several literal
    and command block types."""
    _ok(_decode(run, workdir, ["mix.q5.br", "mix3.q11.br", "alt2.q11.br", "tri.q11.br"]), "brotli_block_switching")

# Small streams made by the reference libraries from many kinds of input (runs, digits, numbers, English text that hits
# Brotli's static dictionary, upper-case words, HTML, all byte values, packed doubles, JSON, sparse bytes) at several
# levels/windows; the table is spliced into the program so no large file has to be read at run time.
VECTORS_JS = r"""
const zlib = require('zlib');
const dec = { zz: zlib.inflateSync, br: zlib.brotliDecompressSync, zst: zlib.zstdDecompressSync };
const want = process.argv[2];
for (const [codec, label, b64] of DATA.vectors) {
  if (codec !== want) continue;
  const data = Uint8Array.fromBase64(b64);
  try {
    const out = dec[codec](data);
    const c = zlib.crc32(out);
    console.log(label.padEnd(20), data.length, out.length, c === DATA.crc[label.split('.')[0]] ? 'crc-ok' : 'crc=' + c.toString(16));
  } catch (e) {
    console.log(label, data.length, `${e.name}: ${e.message}`);
  }
}
"""


@pytest.mark.parametrize("codec", ["br", "zst", "zz"])
def test_small_reference_vectors(run, workdir, codec):
    """CATCHES: Brotli/Zstandard/inflate decoders that fail on short streams from the reference encoders: Brotli
    quality 1/5/11 with 10-22 bit windows and text mode (dictionary words, upper-case transforms), zstd negative/3/19
    levels (raw/RLE literals, predefined and RLE sequence tables, checksums), zlib fast/best/fixed-Huffman."""
    data = (FIXTURES / "small_vectors.json").read_text()
    write_files(workdir, {"vectors.js": "const DATA = " + data + ";\n" + VECTORS_JS})
    _ok(run(["vectors.js", codec]), f"small_vectors_{codec}")

ENCODE_JS = r"""
const zlib = require('zlib');
const hex = (b) => Buffer.from(b).toString('hex');
const crc = (b) => zlib.crc32(b).toString(16).padStart(8, '0');
const inputs = [['empty', ''], ['a', 'a'], ['hello', 'hello hello hello hello'], ['abc', 'abc'.repeat(11)], ['bytes', Buffer.from([0, 1, 2, 3, 255, 254])], ['utf8', 'héllo ☃ \u{1F600}']];
for (const [name, inp] of inputs) {
  const b = Buffer.from(inp);
  const d = zlib.deflateSync(b), r = zlib.deflateRawSync(b), g = zlib.gzipSync(b), br = zlib.brotliCompressSync(b), z = zlib.zstdCompressSync(b);
  console.log(name, 'deflate', hex(d));
  console.log(name, 'raw', hex(r));
  console.log(name, 'gzip', hex(g));
  console.log(name, 'brotli', hex(br));
  console.log(name, 'zstd', hex(z));
  console.log(name, 'roundtrip', zlib.inflateSync(d).equals(b), zlib.inflateRawSync(r).equals(b), zlib.gunzipSync(g).equals(b), zlib.unzipSync(g).equals(b), zlib.brotliDecompressSync(br).equals(b), zlib.zstdDecompressSync(z).equals(b), Buffer.isBuffer(d), d.constructor.name);
}
// generated inputs: long runs (back-references at max length), every byte value, a 4-symbol alphabet,
// incompressible LCG noise and repetitive text
let s = 1; const lcg = () => (s = (Math.imul(s, 1103515245) + 12345) >>> 0) >>> 24;
const noise = new Uint8Array(3000); for (let i = 0; i < noise.length; i++) noise[i] = lcg();
const gens = [['run1000', new Uint8Array(1000).fill(120)], ['allbytes', Uint8Array.from({ length: 512 }, (_, i) => i & 255)], ['abcd', Uint8Array.from({ length: 2000 }, (_, i) => 97 + ((i * 7) % 4))], ['noise', noise], ['text', Buffer.from('the quick brown fox jumps over the lazy dog; '.repeat(40))]];
for (const [name, b] of gens) {
  const outs = { deflate: zlib.deflateSync(b), raw: zlib.deflateRawSync(b), gzip: zlib.gzipSync(b), brotli: zlib.brotliCompressSync(b), zstd: zlib.zstdCompressSync(b) };
  const back = { deflate: zlib.inflateSync, raw: zlib.inflateRawSync, gzip: zlib.gunzipSync, brotli: zlib.brotliDecompressSync, zstd: zlib.zstdDecompressSync };
  console.log(name, b.length, crc(b), Object.entries(outs).map(([k, v]) => `${k}=${v.length}/${crc(v)}/${crc(back[k](v)) === crc(b)}`).join(' '));
}
console.log('crc32', zlib.crc32('hello'), zlib.crc32(''), zlib.crc32('123456789').toString(16), zlib.crc32(Buffer.from('world'), zlib.crc32('hello ')), zlib.crc32('hello world'), zlib.crc32(new Uint8Array([1, 2, 3])), zlib.crc32('abc', 0xffffffff), zlib.crc32('é'), zlib.crc32('x', -1));
console.log('constants', zlib.constants.Z_BEST_COMPRESSION, zlib.constants.Z_DEFAULT_COMPRESSION, zlib.constants.Z_SYNC_FLUSH, zlib.constants.BROTLI_PARAM_QUALITY, zlib.constants.BROTLI_MAX_WINDOW_BITS, zlib.constants.ZSTD_e_end, zlib.constants.ZSTD_c_compressionLevel, zlib.codes.Z_DATA_ERROR, zlib.codes['-3'], zlib.codes[2], Object.keys(zlib.constants).length, Object.keys(zlib.codes).length);
console.log('keys', Object.keys(zlib).sort().join(','));
"""


def test_encoders_pinned_output_and_roundtrip(run, workdir):
    """CATCHES: deflate/zlib/gzip/Brotli/Zstandard encoders whose output bytes, headers, checksums (Adler-32, CRC-32,
    XXH64) or block choices differ from the reference, broken round trips, wrong crc32 values/seeding, missing zlib
    exports, or wrong constants/codes tables."""
    write_files(workdir, {"enc.js": ENCODE_JS})
    _ok(run(["enc.js"]), "encoders")


LARGE_JS = r"""
const zlib = require('zlib');
const crc = (b) => zlib.crc32(b).toString(16).padStart(8, '0');
// > 64 KiB: brotli needs 5 length nibbles; > 128 KiB: zstd splits into several RLE blocks and a 4-byte content size.
for (const n of [65537, 140000]) {
  const zeros = new Uint8Array(n);
  const br = zlib.brotliCompressSync(zeros), zs = zlib.zstdCompressSync(zeros), df = zlib.deflateRawSync(zeros);
  console.log(n, 'brotli', br.toString('hex'), 'zstd', zs.toString('hex'), 'deflate', df.length, crc(df));
}
// > 1 MiB: six length nibbles.
const mega = zlib.brotliCompressSync(new Uint8Array(new ArrayBuffer((1 << 20) + 1)));
console.log('1MiB+1 brotli', mega.toString('hex'));
// Brotli literal codes: two symbols, a uniform 8-symbol alphabet, and Fibonacci frequencies that force the
// 15-bit length limit; plus > 64 KiB of noise stored as an uncompressed meta-block.
const fib = []; for (let a = 1, b = 1, sym = 0; sym < 18; sym++, [a, b] = [b, a + b]) for (let k = 0; k < a; k++) fib.push(sym);
let s = 7; const noise = new Uint8Array(66000); for (let i = 0; i < noise.length; i++) noise[i] = (s = (Math.imul(s, 1103515245) + 12345) >>> 0) >>> 24;
for (const [name, data] of [['two', Uint8Array.from({ length: 300 }, (_, i) => (i % 3 ? 120 : 121))], ['uniform8', Uint8Array.from({ length: 400 }, (_, i) => i & 7)], ['fibonacci', Uint8Array.from(fib)], ['noise66k', noise]]) {
  const c = zlib.brotliCompressSync(data);
  console.log(name, data.length, c.length, crc(c), c.subarray(0, 12).toString('hex'));
}
const fb = Uint8Array.from(fib);
console.log('fibonacci back', crc(zlib.brotliDecompressSync(zlib.brotliCompressSync(fb))) === crc(fb));
"""


def test_encoders_large_inputs(run, workdir):
    """CATCHES: Brotli encoders that mis-encode meta-block lengths needing five nibbles (> 64 KiB), Zstandard encoders
    that do not split > 128 KiB inputs into several RLE blocks with a 4-byte content size, or deflate encoders that
    mis-emit runs of 258-byte matches."""
    write_files(workdir, {"large.js": LARGE_JS})
    _ok(run(["large.js"]), "encoders_large")


CORRUPT_DEFLATE_JS = r"""
const fs = require('fs'), zlib = require('zlib');
const tryIt = (label, fn, buf) => { try { const out = fn(buf); console.log(label, 'OK', out.length, JSON.stringify(out.toString('latin1').slice(0, 24))); } catch (e) { console.log(label, e.name + ':', e.message); } };
const H = (h) => Buffer.from(h, 'hex');
for (const [label, hex] of [['empty', ''], ['reserved-btype', '07'], ['stored-truncated', '01'], ['stored-len-only', '0105'], ['stored-overrun', '010500faff6162'], ['stored-then-fixed', '000200fdff4f4bf3c854042200'], ['fixed-bad-symbol', '731c03'], ['fixed-far-distance', '0302'], ['dyn-repeat-first', '05001200'], ['dyn-distance-30', '0ddf210100000080a06dfe3f254f2000'], ['fixed-no-eob', '7304']]) tryIt('raw:' + label, zlib.inflateRawSync, H(hex));
const zz = fs.readFileSync('text.l9.zz');
const cut = zz.subarray(0, 300);
tryIt('zlib:truncated', zlib.inflateSync, cut);
for (const [p, v] of [[138, 39], [8, 175], [42, 192], [56, 216], [2, 159], [2, 57], [297, 54], [0, 185]]) { const b = Uint8Array.prototype.slice.call(cut); b[p] = v; tryIt(`zlib:mut@${p}=${v}`, zlib.inflateSync, b); }
tryIt('zlib:short', zlib.inflateSync, H('789c0300'));
tryIt('zlib:method', zlib.inflateSync, H('7f9c030000000001'));
tryIt('zlib:bad-adler-ignored', zlib.inflateSync, H('789c4b040000000000'));
tryIt('zlib:trailing-garbage', zlib.inflateSync, Buffer.concat([zlib.deflateSync(Buffer.from('ok')), H('deadbeef')]));
const gz = zlib.gzipSync(Buffer.from('gzip payload'));
tryIt('gzip:ok', zlib.gunzipSync, gz);
tryIt('gzip:short', zlib.gunzipSync, gz.subarray(0, 17));
const m = Uint8Array.prototype.slice.call(gz); m[1] = 0x8c; tryIt('gzip:magic', zlib.gunzipSync, m);
const m2 = Uint8Array.prototype.slice.call(gz); m2[2] = 7; tryIt('gzip:method', zlib.gunzipSync, m2);
tryIt('gzip:extra-truncated', zlib.gunzipSync, H('1f8b0804000000000003' + 'ff'.repeat(8)));
tryIt('gzip:name-runs-off', zlib.gunzipSync, H('1f8b0808000000000003' + '41'.repeat(10)));
tryIt('gzip:comment+hcrc', zlib.gunzipSync, Buffer.concat([H('1f8b0812000000000003'), Buffer.from('hi\0'), H('0000'), gz.subarray(10)]));
const badCrc = Uint8Array.prototype.slice.call(gz); badCrc[badCrc.length - 6] ^= 0xff; tryIt('gzip:bad-crc-ignored', zlib.gunzipSync, badCrc);
tryIt('unzip:gzip', zlib.unzipSync, gz);
tryIt('inflate-of-gzip', zlib.inflateSync, gz);
tryIt('gunzip-of-zlib', zlib.gunzipSync, zlib.deflateSync(Buffer.from('zlib payload here')));
"""


def test_deflate_zlib_gzip_corrupt_input_errors(run, workdir):
    """CATCHES: inflate/zlib/gzip decoders that crash, hang or report the wrong error for truncated streams, reserved
    block types, bad stored blocks, invalid Huffman codes, over-long code-length runs, distances before the start,
    bad zlib/gzip headers, and that do not tolerate ignored trailers (bad Adler/CRC, trailing bytes)."""
    _copy_fixtures(workdir, ["text.l9.zz"])
    write_files(workdir, {"corrupt.js": CORRUPT_DEFLATE_JS})
    _ok(run(["corrupt.js"]), "corrupt_deflate")


CORRUPT_BROTLI_JS = r"""
const fs = require('fs'), zlib = require('zlib');
const tryIt = (label, buf) => { try { const out = zlib.brotliDecompressSync(buf); console.log(label, 'OK', out.length, JSON.stringify(out.subarray(0, 24).toString('latin1'))); } catch (e) { console.log(label, e.name + ':', e.message); } };
const H = (h) => Buffer.from(h, 'hex');
for (const [label, hex] of [['empty', ''], ['empty-stream', '06'], ['empty-stream-w10', '3b'], ['hello', '0b028068656c6c6f03'], ['hello-truncated', '0b028068656c6c6f'], ['exuberant-nibble', '04000000'], ['exuberant-metadata', '4c050000'], ['metadata-overrun', '2c09aabb'], ['metadata-then-last', 'ac004d4403'], ['wbits-only', 'a1'], ['last-metadata', '1a'], ['window-17', '81080100200d52e646072672e0d0a2c46ef63e3a2f45d3072e04c2c1d600'], ['trailing-junk', '0b028068656c6c6f036a756e6b'], ['quick-fox', '1b2a0000c4dc46a95e0d0b45712af29c4cfe1c4517a82a5b4956982fbcf174445e94d5c604b7da8131d5fd87c004'], ['abc123x1000', '1b6f17000476c0e62e73216e8b03c90340770c']]) tryIt(label, H(hex));
const muts = {
  'text.q11.br': [[362, 173], [85, 51], [1992, 0], [17, 149], [60, 197], [0, 124], [131, 68], [2485, 39], [3, 209], [3, 112], [3, 15], [0, 17]],
  'text.q1.br': [[1003, 193], [959, 189], [1712, 212], [1517, 195]],
  'underscore.min.js.br': [[2694, 241], [0, 33]],
};
for (const [f, list] of Object.entries(muts)) {
  const base = fs.readFileSync(f);
  tryIt(`${f}:truncated`, base.subarray(0, base.length >> 1));
  for (const [p, v] of list) { const b = Uint8Array.prototype.slice.call(base); b[p] = v; tryIt(`${f}:mut@${p}=${v}`, b); }
}
"""


def test_brotli_corrupt_input_errors(run, workdir):
    """CATCHES: Brotli decoders that crash or report the wrong error for exuberant nibbles, metadata blocks, reserved
    bits, invalid prefix codes, context-map and code-length overruns, bad dictionary references/transforms, invalid
    short distances, padding errors, length mismatches and truncation (and accept the RFC example streams)."""
    _copy_fixtures(workdir, ["text.q11.br", "text.q1.br", "underscore.min.js.br"])
    write_files(workdir, {"corrupt.js": CORRUPT_BROTLI_JS})
    _ok(run(["corrupt.js"]), "corrupt_brotli")


CORRUPT_ZSTD_JS = r"""
const fs = require('fs'), zlib = require('zlib');
const tryIt = (label, buf) => { try { const out = zlib.zstdDecompressSync(buf); console.log(label, 'OK', out.length, JSON.stringify(out.subarray(0, 24).toString('latin1'))); } catch (e) { console.log(label, e.name + ':', e.message); } };
const H = (h) => Buffer.from(h, 'hex');
for (const [label, hex] of [['empty', ''], ['magic-only', '28b52ffd'], ['valid-a', '28b52ffd2401090000615b6e8ca9'], ['reserved-bit', '28b52ffd2c01090000615b6e8ca9'], ['dictionary', '28b52ffd250701090000615b6e8ca9'], ['reserved-block', '28b52ffd2401070000615b6e8ca9'], ['size-mismatch', '28b52ffd2402090000615b6e8ca9'], ['checksum-mismatch', '28b52ffd2401090000615b6e8caa'], ['checksum-truncated', '28b52ffd2401090000615b6e'], ['block-header-truncated', '28b52ffd2401'], ['rle-truncated', '28b52ffd2001030000'], ['rle-valid', '28b52ffd20052b000061'], ['raw-truncated', '28b52ffd2005290000616263'], ['raw-size-mismatch', '28b52ffd20051100006162'], ['skippable-truncated', '502a4d1864000000aabb'], ['skippable-header-only', '502a4d18'], ['skippable-then-frame', '512a4d1802000000aabb28b52ffd2401090000615b6e8ca9'], ['second-frame-truncated', '28b52ffd2401090000615b6e8ca928b52ffd2001'], ['bad-magic', 'deadbeef'], ['trailing-garbage', '28b52ffd2401090000615b6e8ca90102']]) tryIt(label, H(hex));
const muts = {
  'text.l19.check.zst': [[1988, 39], [449, 150], [777, 175], [271, 136], [513, 47], [38, 17], [680, 23], [698, 244], [717, 99], [6, 107], [4, 96]],
  'text.l6.flushes.zst': [[2137, 11], [840, 130], [1645, 241], [2140, 154], [636, 29], [12, 200]],
};
for (const [f, list] of Object.entries(muts)) {
  const base = fs.readFileSync(f);
  tryIt(`${f}:truncated`, base.subarray(0, base.length >> 1));
  for (const [p, v] of list) { const b = Uint8Array.prototype.slice.call(base); b[p] = v; tryIt(`${f}:mut@${p}=${v}`, b); }
}
"""


def test_zstd_corrupt_input_errors(run, workdir):
    """CATCHES: Zstandard decoders that crash or report the wrong error for bad magic, reserved header bits,
    dictionary frames, reserved/oversized/truncated blocks, content-size and checksum mismatches, skippable-frame
    truncation, and corrupted Huffman/FSE tables, literals sections and sequence bitstreams."""
    _copy_fixtures(workdir, ["text.l19.check.zst", "text.l6.flushes.zst"])
    write_files(workdir, {"corrupt.js": CORRUPT_ZSTD_JS})
    _ok(run(["corrupt.js"]), "corrupt_zstd")


API_JS = r"""
const zlib = require('zlib');
const util = require('util');
const hex = (b) => Buffer.from(b).toString('hex');
const input = Buffer.from('callback api '.repeat(4));
const log = [];
console.log('start');
zlib.gzip(input, (err, out) => {
  console.log('gzip cb', err, out.length, Buffer.isBuffer(out), hex(out.subarray(0, 10)));
  zlib.gunzip(out, (err2, back) => console.log('gunzip cb', err2, JSON.stringify(back.toString())));
});
zlib.deflate(input, { level: 9 }, (err, out) => console.log('deflate opts cb', err, hex(out)));
zlib.inflate(Buffer.from('78da0000', 'hex'), (err, out) => console.log('inflate bad cb', err instanceof Error, err.name, err.message, out));
zlib.brotliDecompress(Buffer.from('0b0280', 'hex'), (err, out) => console.log('brotli bad cb', err.name, err.message, out));
zlib.zstdDecompress(Buffer.from('28b52ffd2401090000615b6e8caa', 'hex'), (err) => console.log('zstd bad cb', err.message));
zlib.zstdCompress('a string input', (err, out) => console.log('zstd str cb', err, hex(out)));
zlib.deflateRaw(new Uint8Array([1, 2, 3]), (err, out) => console.log('raw u8 cb', hex(out)));
zlib.unzip(zlib.gzipSync('unzipped'), (err, out) => console.log('unzip cb', out.toString()));
zlib.inflateRaw(zlib.deflateRawSync('raw back'), (err, out) => console.log('inflateRaw cb', out.toString()));
zlib.brotliCompress('brotli cb', (err, out) => zlib.brotliDecompress(out, (e2, back) => console.log('brotli cb chain', hex(out), back.toString())));
util.promisify(zlib.brotliCompress)('promisified').then((o) => console.log('promisify', hex(o)));
util.promisify(zlib.gunzip)(Buffer.from('nope')).catch((e) => console.log('promisify reject', e.name, e.message));
queueMicrotask(() => console.log('microtask queued after calls'));
console.log('sync str', hex(zlib.deflateSync('abc')), hex(zlib.gzipSync('ab', { level: 1 })), zlib.inflateSync(zlib.deflateSync('héllo')).toString(), zlib.gunzipSync(zlib.gzipSync(new Uint8Array([104, 105]))).toString());
const opt = { level: 0, windowBits: 9, memLevel: 1, strategy: zlib.constants.Z_HUFFMAN_ONLY, chunkSize: 64 };
console.log('options ignored', hex(zlib.deflateSync('aaaaaaaa', opt)) === hex(zlib.deflateSync('aaaaaaaa')), hex(zlib.deflateRawSync('aaaaaaaa', opt)), hex(zlib.brotliCompressSync('aaaaaaaa', { params: { [zlib.constants.BROTLI_PARAM_QUALITY]: 0 } })), zlib.inflateSync(zlib.deflateSync('x'), { finishFlush: zlib.constants.Z_SYNC_FLUSH }).toString());
for (const [label, f] of [['gzip num', () => zlib.gzipSync(12)], ['deflate obj', () => zlib.deflateSync({})], ['crc32 num', () => zlib.crc32(5)], ['inflate undefined', () => zlib.inflateSync()], ['brotli null', () => zlib.brotliCompressSync(null)]]) {
  try { f(); console.log(label, 'no error'); } catch (e) { console.log(label, e.name, e.message); }
}
console.log('end of sync');
"""


def test_callback_and_promisified_api(run, workdir):
    """CATCHES: node:zlib async APIs that call back synchronously or out of order, mis-parse the optional options
    argument (level/windowBits/strategy/params are accepted but do not change the output), report decode errors with
    the wrong class/message, reject string/Uint8Array inputs, or break util.promisify."""
    write_files(workdir, {"api.js": API_JS})
    _ok(run(["api.js"]), "callback_api")


STREAMS_JS = r"""
const zlib = require('zlib');
const { Readable, Writable, Transform, pipeline } = require('stream');
const gz = zlib.createGzip();
const chunks = [];
gz.on('data', (c) => chunks.push(c));
gz.on('end', () => { const all = Buffer.concat(chunks); console.log('gzip stream', chunks.length, all.toString('hex'), zlib.gunzipSync(all).toString()); });
gz.write('stream '); gz.write(Buffer.from('data ')); gz.end('end');
const sink = [];
pipeline(Readable.from([Buffer.from('pipe'), Buffer.from('line '), Buffer.from('x'.repeat(40))]), zlib.createDeflate(), zlib.createInflate(), new Writable({ write(c, e, cb) { sink.push(c); cb(); } }), (err) => console.log('pipeline deflate', err, Buffer.concat(sink).toString()));
const sink2 = [];
pipeline(Readable.from(['brotli ', 'and ', 'zstd']), zlib.createBrotliCompress(), zlib.createBrotliDecompress(), zlib.createZstdCompress(), zlib.createZstdDecompress(), zlib.createDeflateRaw(), zlib.createInflateRaw(), zlib.createGzip(), zlib.createUnzip(), new Writable({ write(c, e, cb) { sink2.push(c); cb(); } }), (err) => console.log('pipeline chain', err, Buffer.concat(sink2).toString()));
const bad = zlib.createGunzip();
bad.on('error', (e) => console.log('stream error', e.name, e.message));
bad.on('data', () => console.log('unexpected data'));
bad.end(Buffer.from('not gzip at all, sorry'));
const badBr = zlib.createBrotliDecompress();
badBr.on('error', (e) => console.log('brotli stream error', e.message));
badBr.end(Buffer.from([0x0b, 0x02]));
const z = new zlib.Inflate();
z.on('data', (d) => console.log('Inflate class data', d.toString()));
z.end(zlib.deflateSync('via new zlib.Inflate'));
console.log('classes', typeof zlib.Gzip, zlib.createBrotliCompress() instanceof Transform, zlib.createZstdDecompress() instanceof zlib.ZstdDecompress, new zlib.Gunzip() instanceof zlib.Gunzip, zlib.Deflate === zlib.Deflate);
console.log('end of sync');
"""


def test_transform_stream_classes(run, workdir):
    """CATCHES: zlib Transform streams (createGzip/createDeflate/createInflate/createBrotli*/createZstd*/createUnzip
    and the classes) that do not compress the concatenated writes, break inside stream.pipeline chains, or fail to
    emit 'error' for corrupt input."""
    write_files(workdir, {"streams.js": STREAMS_JS})
    _ok(run(["streams.js"]), "transform_streams")


CSTREAM_JS = r"""
const hex = (u8) => Array.from(u8, (b) => b.toString(16).padStart(2, '0')).join('');
async function collect(readable) {
  const r = readable.getReader(); const parts = []; let n = 0;
  for (;;) { const { value, done } = await r.read(); if (done) break; parts.push(value); n += value.length; }
  const out = new Uint8Array(n); let o = 0; for (const p of parts) { out.set(p, o); o += p.length; }
  return [out, parts.length, parts.length && Object.prototype.toString.call(parts[0])];
}
async function through(stream, chunks) {
  const w = stream.writable.getWriter();
  const done = collect(stream.readable);
  for (const c of chunks) w.write(c);
  w.close();
  return done;
}
async function main() {
  const enc = new TextEncoder(), dec = new TextDecoder();
  const input = enc.encode('hello hello hello world, compression streams!');
  for (const fmt of ['gzip', 'deflate', 'deflate-raw']) {
    const buf = new ArrayBuffer(8); new Uint8Array(buf).set(input.subarray(10, 18));
    const [out, nparts, kind] = await through(new CompressionStream(fmt), [input.subarray(0, 10), buf, new DataView(input.buffer, 18), new Uint8Array(0)]);
    const [back] = await through(new DecompressionStream(fmt), [out.subarray(0, 3), out.subarray(3)]);
    console.log(fmt, nparts, kind, hex(out), JSON.stringify(dec.decode(back)));
  }
  const [empty, n0] = await through(new CompressionStream('gzip'), []);
  console.log('empty gzip', n0, hex(empty));
  const [emptyBack, n1] = await through(new DecompressionStream('deflate-raw'), [new Uint8Array([3, 0])]);
  console.log('empty inflate', n1, emptyBack.length);
  const blob = new Blob(['blob data '.repeat(5)]);
  const [piped] = await collect(blob.stream().pipeThrough(new CompressionStream('deflate')).pipeThrough(new DecompressionStream('deflate')));
  console.log('pipeThrough', dec.decode(piped));
  for (const fmt of ['brotli', 'GZIP', '', undefined]) {
    for (const C of [CompressionStream, DecompressionStream]) {
      try { new C(fmt); console.log(C.name, String(fmt), 'accepted'); } catch (e) { console.log(C.name, String(fmt), e.name, e.message); }
    }
  }
  {
    const ds = new DecompressionStream('gzip');
    collect(ds.readable).then(() => console.log('unexpected read success'));
    const w = ds.writable.getWriter();
    await w.write(new Uint8Array([1, 2, 3]));
    await w.close().then(() => console.log('unexpected close'), (e) => console.log('corrupt gzip close rejected', e.name, e.message));
  }
  {
    const ds = new DecompressionStream('deflate');
    collect(ds.readable);
    const w = ds.writable.getWriter();
    w.write(new Uint8Array([0x78, 0x9c, 0x07, 0, 0, 0, 0]));
    await w.close().catch((e) => console.log('corrupt deflate close rejected', e.name, e.message));
  }
  {
    const cs = new CompressionStream('deflate-raw');
    collect(cs.readable);
    const w = cs.writable.getWriter();
    await w.write('a string').catch((e) => console.log('string chunk rejected', e.name, e.message));
    await w.close().catch((e) => console.log('close after bad chunk', e.name, e.message));
  }
  console.log('done');
}
main();
"""


def test_compression_streams(run, workdir):
    """CATCHES: CompressionStream/DecompressionStream implementations that mishandle gzip/deflate/deflate-raw, mixed
    BufferSource chunk types, empty input, pipeThrough chains, case-sensitive format names, or that do not reject
    the writer for corrupt input and non-BufferSource chunks."""
    write_files(workdir, {"cs.js": CSTREAM_JS})
    _ok(run(["cs.js"]), "compression_streams")


DSTREAM_FIXTURE_JS = r"""
const fs = require('fs'), zlib = require('zlib');
async function decode(fmt, file, chunk) {
  const data = fs.readFileSync(file);
  const ds = new DecompressionStream(fmt);
  const w = ds.writable.getWriter();
  for (let i = 0; i < data.length; i += chunk) w.write(data.subarray(i, i + chunk));
  w.close();
  const r = ds.readable.getReader();
  let n = 0, crc = 0, first = null;
  for (;;) {
    const { value, done } = await r.read();
    if (done) break;
    if (!first) first = new TextDecoder().decode(value.subarray(0, 30));
    crc = zlib.crc32(value, crc); n += value.length;
  }
  console.log(fmt, file, chunk, n, crc.toString(16), JSON.stringify(first));
}
(async () => {
  await decode('gzip', 'text.l6.gz', 1000);
  await decode('gzip', 'text3k.headers.gz', 7);
  await decode('deflate', 'text.l9.zz', 4096);
  await decode('deflate', 'text.filtered.w9.zz', 333);
  await decode('deflate-raw', 'text.flushes.raw', 64);
  await decode('deflate-raw', 'random.l9.raw', 100000);
})();
"""


def test_decompression_stream_reference_input(run, workdir):
    """CATCHES: DecompressionStream implementations that cannot decode zlib-library output (dynamic Huffman, flushed
    blocks, small windows, gzip header fields) when it arrives split into arbitrary chunks."""
    _copy_fixtures(workdir, ["text.l6.gz", "text3k.headers.gz", "text.l9.zz", "text.filtered.w9.zz",
                             "text.flushes.raw", "random.l9.raw"])
    write_files(workdir, {"ds.js": DSTREAM_FIXTURE_JS})
    _ok(run(["ds.js"]), "decompression_stream_fixtures")


BUN_JS = r"""
const hex = (u8) => Array.from(u8, (b) => b.toString(16).padStart(2, '0')).join('');
const data = new TextEncoder().encode('bun compression helpers');
const g = Bun.gzipSync(data), d = Bun.deflateSync(data), z = Bun.zstdCompressSync(data);
console.log('gzip', Object.prototype.toString.call(g), hex(g));
console.log('deflate', hex(d));
console.log('zstd', hex(z));
console.log('back', new TextDecoder().decode(Bun.gunzipSync(g)), new TextDecoder().decode(Bun.inflateSync(d)), new TextDecoder().decode(Bun.zstdDecompressSync(z)), Bun.zstdDecompressSync(z) instanceof Uint8Array);
console.log('string input', hex(Bun.zstdCompressSync('str')), hex(Bun.gzipSync('str')));
try { Bun.zstdDecompressSync(new Uint8Array([1, 2, 3, 4])); } catch (e) { console.log('zstd error', e.name, e.message); }
try { Bun.gunzipSync(new Uint8Array(20)); } catch (e) { console.log('gunzip error', e.name, e.message); }
Bun.zstdCompress(data).then((c) => Bun.zstdDecompress(c)).then((b) => console.log('async zstd', new TextDecoder().decode(b)));
Bun.zstdDecompress(new Uint8Array([0x28, 0xb5, 0x2f, 0xfd])).catch((e) => console.log('async zstd reject', e.message));
"""


def test_bun_compression_helpers(run, workdir):
    """CATCHES: Bun.gzipSync/gunzipSync/deflateSync/inflateSync/zstdCompressSync/zstdDecompressSync and the async
    zstd helpers returning the wrong framing, the wrong type, or the wrong errors for corrupt input."""
    write_files(workdir, {"bun.js": BUN_JS})
    _ok(run(["bun.js"]), "bun_helpers")


def test_uncaught_decode_error_exits_nonzero(run, workdir):
    """CATCHES: runtimes that swallow a synchronous zlib decode error instead of reporting it as an uncaught Error on
    stderr with exit status 1 (and stopping the script there)."""
    write_files(workdir, {"u.js": "const zlib = require('zlib');\nconsole.log('before');\n"
                                    "zlib.inflateRawSync(Buffer.from([0x07]));\nconsole.log('not reached');\n"})
    r = run(["u.js"])
    assert (r.returncode, r.stdout, r.stderr) == (1, b"before\n", b"Uncaught Error: inflate: reserved block type\n")
