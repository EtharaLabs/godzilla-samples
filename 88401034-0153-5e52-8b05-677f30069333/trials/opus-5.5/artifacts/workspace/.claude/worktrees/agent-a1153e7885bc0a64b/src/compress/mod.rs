//! # `compress` — codecs behind `node:zlib` and `CompressionStream` / `DecompressionStream`
//!
//! Std-only, `unsafe`-free reimplementation of the ORIGINAL lumen runtime's
//! compression codecs. Everything here was derived by black-box experiments
//! against the original binary.
//!
//! * Every encoder reproduces the original's output byte-for-byte. This was
//!   checked on a broad corpus: empty input up to ~1 MB of text, random,
//!   binary and run-heavy data, and matches farther than 32 KiB.
//! * Every decoder reproduces the original's output, its laxness and its
//!   exact error messages. This was checked on ~30,000 crafted, fuzzed and
//!   valid vectors, including node/libzstd/python-zlib streams and all
//!   assets in `assets/test_runtime_compression`.
//!
//! ## 1. Rust API
//!
//! | function | JS API (original) |
//! |---|---|
//! | [`crc32`]`(data, init)` | `zlib.crc32(data, value)`; `init` = `value >>> 0` |
//! | [`adler32`]`(data, init)` | helper; no JS export (start with `init = 1`) |
//! | [`deflate_raw`] / [`zlib_encode`] / [`gzip_encode`] | `deflateRawSync` / `deflateSync` / `gzipSync` |
//! | [`inflate_raw`] / [`zlib_decode`] / [`gzip_decode`] / [`unzip_decode`] | `inflateRawSync` / `inflateSync` / `gunzipSync` / `unzipSync` |
//! | [`brotli_encode`] / [`brotli_decode`] | `brotliCompressSync` / `brotliDecompressSync` |
//! | [`zstd_encode`] / [`zstd_decode`] | `zstdCompressSync` / `zstdDecompressSync` |
//! | [`Codec`], [`BufferedCodec`] | stream classes and Compression/DecompressionStream (see 2.5 and 2.6) |
//! | [`ZLIB_CONSTANTS`] | `zlib.constants`, exact key order and values |
//!
//! **Options.** The original never reads any option: a Proxy passed as
//! options sees zero property accesses. So [`DeflateOptions`],
//! [`BrotliOptions`] and the zstd `level` exist only for API shape and are
//! ignored.
//!
//! **`dictionary`.** The `dictionary` argument of [`inflate_raw`] and
//! [`zlib_decode`] is an extension that the original does not have. Pass
//! `None` to behave like the original.
//!
//! **Decoder errors** are [`CodecError`]s. The original throws a plain
//! `Error` whose only own property is `message`: there is no `code` and no
//! `errno`, and `Object.keys(e)` is `[]`. `code` is therefore always `""` and
//! `errno` always `0`; the binding must NOT define those properties.
//! Messages are prefixed `inflate: `, `zlib: `, `gzip: `, `brotli: ` or
//! `zstd: `; the catalogs are in section 3.
//!
//! **Size cap.** In the original, every Buffer/TypedArray larger than
//! 1,048,576 bytes throws `RangeError: Invalid typed array length`. This is
//! an engine-wide cap; `fs.readFileSync` of a big file fails the same way.
//! Any codec result above that size therefore throws this RangeError, and
//! only after the codec succeeded, so a codec error found later still wins.
//! This module has no such cap. Exactly 1,048,576 bytes is allowed.
//!
//! ## 2. JS-level behaviour of the original (for the bindings)
//!
//! ### 2.1 Module surface
//!
//! `Object.keys(require('zlib'))` is exactly these 47 keys, in this order:
//! `gzipSync gzip Gzip createGzip gunzipSync gunzip Gunzip createGunzip
//! deflateSync deflate Deflate createDeflate inflateSync inflate Inflate
//! createInflate deflateRawSync deflateRaw DeflateRaw createDeflateRaw
//! inflateRawSync inflateRaw InflateRaw createInflateRaw brotliCompressSync
//! brotliCompress BrotliCompress createBrotliCompress brotliDecompressSync
//! brotliDecompress BrotliDecompress createBrotliDecompress zstdCompressSync
//! zstdCompress ZstdCompress createZstdCompress zstdDecompressSync
//! zstdDecompress ZstdDecompress createZstdDecompress unzipSync unzip Unzip
//! createUnzip crc32 constants codes`.
//!
//! * **What is absent:**
//!   * no `zlib.default` (but ESM `import zlib from 'node:zlib'` and named
//!     imports work);
//!   * no `zlib.promises`, and `require('zlib/promises')` is MODULE_NOT_FOUND;
//!   * no top-level `Z_*` constants;
//!   * `require('zlib') === require('node:zlib')`.
//! * **The 36 non-class functions:**
//!   * `name` is `""`;
//!   * `length` is 1 for `xSync`, 3 for async `x`, 1 for `createX`, 1 for
//!     `crc32`;
//!   * not constructible: `new` throws TypeError "object is not a
//!     constructor".
//!   * They are plain writable, enumerable, configurable data properties.
//! * **The 11 classes start as lazy accessors:**
//!   * Each is `{get, enumerable: true, configurable: true}`; the getter is
//!     named "get", length 0.
//!   * The first read redefines the key as a data property
//!     `{value: cls, writable, enumerable, configurable}`.
//!   * Every class has `name === "cls"`, `length === 1`, and
//!     `Object.getPrototypeOf(X) === require('stream').Transform` (the
//!     runtime's own). Instances are `instanceof` Transform, Duplex,
//!     Readable and EventEmitter, but NOT `stream.Writable`.
//!   * `X.prototype` own keys are `[constructor, _transform, _flush]`.
//!   * Calling a class without `new` throws TypeError "Class constructor
//!     cannot be invoked without 'new'".
//!   * `createX(opts)` is `new <exports>.X(opts)`, looked up at call time.
//! * **`zlib.constants`:**
//!   * A plain, mutable, non-frozen object with 170 keys, in the order of
//!     [`ZLIB_CONSTANTS`].
//!   * `Z_MAX_CHUNK` is `null` (not Infinity) and `ZLIB_VERNUM` is 4865.
//!   * The other values are node's, plus the zstd ones.
//! * **`zlib.codes`:** build it by inserting the keys `-6..=2` (number to name)
//!   in ascending order, then `Z_OK…Z_VERSION_ERROR` (name to number).
//!   `JSON.stringify` then gives
//!   `{"0":"Z_OK","1":"Z_STREAM_END","2":"Z_NEED_DICT","-6":"Z_VERSION_ERROR","-5":"Z_BUF_ERROR","-4":"Z_MEM_ERROR","-3":"Z_DATA_ERROR","-2":"Z_STREAM_ERROR","-1":"Z_ERRNO","Z_OK":0,"Z_STREAM_END":1,"Z_NEED_DICT":2,"Z_ERRNO":-1,"Z_STREAM_ERROR":-2,"Z_DATA_ERROR":-3,"Z_MEM_ERROR":-4,"Z_BUF_ERROR":-5,"Z_VERSION_ERROR":-6}`.
//!
//! ### 2.2 Input conversion
//!
//! This applies to every sync, async and stream entry point and to `crc32`.
//!
//! * **`Uint8Array` (including Buffer):** the view's bytes are used directly,
//!   respecting byteOffset and length.
//! * **Anything else:** `Buffer.from(data, undefined)`, with all of the
//!   engine's `Buffer.from` quirks:
//!   * strings become UTF-8 (`'héllo€'` → `68c3a96c6c6fe282ac`);
//!   * other typed arrays are copied element-wise and truncated to bytes
//!     (`Uint16Array[0x4142]` → `42`);
//!   * a DataView becomes empty input;
//!   * ArrayBuffer becomes its whole contents;
//!   * arrays and array-likes are accepted.
//! * **Rejected values:** a number, boolean, null, undefined, plain object,
//!   Symbol, BigInt or SharedArrayBuffer throws TypeError
//!   "Buffer.from: unsupported value".
//! * **Fake Uint8Array:** an object that passes `instanceof Uint8Array` but
//!   is not a typed array throws TypeError
//!   "zlib expects a Buffer/TypedArray". For crc32 the message is
//!   "zlib.crc32 expects a Buffer/TypedArray".
//! * **All of these errors** have `message` as their only own property.
//!
//! ### 2.3 Sync functions
//!
//! `xSync(data, opts)`:
//! * Returns a fresh Buffer copy (byteOffset 0, its own ArrayBuffer), even
//!   for empty output.
//! * Options are ignored entirely. `info: true` still returns a Buffer, and
//!   `maxOutputLength` is not enforced.
//! * Decoder failures throw `Error(<CodecError.message>)`.
//! * Samples (hex):
//!
//! | call | result |
//! |---|---|
//! | `deflateSync('')` | `789c030000000001` |
//! | `deflateSync('hello')` | `789ccb48cdc9c90700062c0215` |
//! | `deflateRawSync('hello')` | `cb48cdc9c90700` |
//! | `gzipSync('hello')` | `1f8b08000000000000ffcb48cdc9c9070086a6103605000000` |
//! | `brotliCompressSync('')` | `3b` |
//! | `brotliCompressSync('hello')` | `0b028068656c6c6f03` |
//! | `zstdCompressSync('hello')` | `28b52ffd240529000068656c6c6fa36d9f88` |
//!
//! ### 2.4 Async functions (`gzip`, `gunzip`, `deflate`, … `zstdDecompress`, `unzip`)
//!
//! `x(data, opts, cb)`:
//! * **Arguments:** if `opts` is a function it is the callback and the third
//!   argument is ignored.
//! * **Return value:** `undefined`. Nothing is ever thrown synchronously.
//! * **Scheduling:** at call time it queues exactly ONE microtask, like
//!   `Promise.resolve().then(job)`. The job reads and converts `data` at that
//!   time (so mutations after the call are seen), runs the codec, and then
//!   calls `cb(null, buf)` (`arguments.length` 2) or `cb(err)`
//!   (`arguments.length` 1), with `this` undefined. Bad input types also
//!   arrive as `cb(err)`.
//! * **Observed order:** `sync code | earlier microtasks | callbacks in call
//!   order | later microtasks | process.nextTick | setTimeout`.
//! * **Throwing callbacks:** if `cb(null, buf)` throws, `cb` is called a
//!   second time with that error. If that call throws too, the error becomes
//!   an unhandled rejection: stderr shows `Uncaught (in promise) …` and the
//!   exit code stays 0.
//! * **Missing callback:** gives an unhandled rejection `TypeError: cb is not
//!   a function`.
//! * `util.promisify(zlib.gzip)` works.
//!
//! ### 2.5 Stream classes (`createGzip()`, `new zlib.Gunzip()`, …)
//!
//! Every class is the following Transform subclass. Timing, backpressure
//! (highWaterMark 65536 both sides) and event order all come from the
//! runtime's `stream.Transform`; reuse it as is.
//! ```js
//! class cls extends Transform {             // every class: name "cls", length 1
//!   constructor(opts) { super(opts); this._chunks = []; }   // zlib options ignored
//!   _transform(chunk, enc, cb) {
//!     this._chunks.push(typeof chunk === 'string' ? Buffer.from(chunk, enc)
//!                     : Buffer.isBuffer(chunk) ? chunk          // kept BY REFERENCE
//!                     : Buffer.from(chunk));                    // invalid -> unhandled TypeError, stream stalls
//!     cb();
//!   }
//!   _flush(cb) {                              // runs once at end(); _chunks is never cleared
//!     let out;
//!     try { out = xSync(Buffer.concat(this._chunks)); } catch (e) { return cb(e); }
//!     this.push(out);                         // exactly ONE 'data' chunk, even when it is 0 bytes long
//!     cb();
//!   }
//! }
//! ```
//! * **Codec per class:** Gzip=gzipSync, Gunzip=gunzipSync, Deflate,
//!   Inflate, DeflateRaw, InflateRaw, Unzip=unzipSync (gzip only),
//!   BrotliCompress, BrotliDecompress, ZstdCompress, ZstdDecompress.
//! * **No intermediate output:** nothing is emitted before `end()`;
//!   `chunkSize` and other options have no effect.
//! * **Missing members:** there are no `flush`, `params`, `reset`, `close`,
//!   `bytesWritten` or `_handle` members, so `s.flush()` throws TypeError.
//! * **Success trace:** `write(a,cb1); write(b,cb2); end(cb3)` emits
//!   `cb1 cb2 data(N) cb3 'finish' 'end'`. There is no 'close' (only
//!   `destroy()` emits it).
//! * **Codec error:** emitted as `'error'` (the plain Error), then `'end'`.
//!   There is no `'finish'`, no end callback and no `'close'`. With no
//!   'error' listener you get `Uncaught (in promise) Error: …` on stderr and
//!   exit code 0. Example: `createGunzip().end(Buffer.from('not gzip data'))`
//!   emits `error("gzip: bad magic")` then `end`.
//! * **Empty output** (e.g. gunzip of `gzipSync('')`) emits `data(0)`, then
//!   `end`.
//! * **Instance own keys:** `_events _eventsCount _maxListeners
//!   _readableState readable _writableState writable _chunks`.
//! * **Invalid chunk types** (number, null, plain object …): `write()`
//!   returns true, then an unhandled rejection `TypeError: Buffer.from:
//!   unsupported value` is printed and the stream stalls forever. There is
//!   no 'error' event.
//! * **Rust side:** [`BufferedCodec`] / [`Codec::run`] give the same
//!   results. The JS layer must keep chunk references until end() if it
//!   wants to reproduce the "mutation before end() is visible" quirk.
//!
//! ### 2.6 `CompressionStream` / `DecompressionStream`
//!
//! * **Shape:**
//!   * Classes named `CompressionStream` / `DecompressionStream`, length 1,
//!     enumerable globals. Calling without `new` throws TypeError.
//!   * Each instance has one own property `_ts = new TransformStream(...)`.
//!   * `readable` / `writable` are non-enumerable prototype getters
//!     returning `_ts.readable` / `_ts.writable`.
//! * **Format:** `String(format)` must be exactly `gzip`, `deflate` or
//!   `deflate-raw` (see [`Codec::for_compression_stream`] /
//!   [`Codec::for_decompression_stream`]). Anything else throws TypeError
//!   `Unsupported CompressionStream format: 'br'` (or
//!   `Unsupported DecompressionStream format: …`). That includes 'brotli',
//!   'zstd', 'GZIP', '' and `undefined` (shown as 'undefined').
//! * **transform(chunk):** an ArrayBuffer or ArrayBufferView is kept by
//!   reference; for a view, its own bytes are used. Anything else throws
//!   TypeError "CompressionStream expects BufferSource chunks" (the same
//!   text in DecompressionStream). Then `write()` and `close()` reject with
//!   that error and `reader.read()` never settles.
//! * **flush():** runs the sync codec on the concatenation.
//!   * A non-empty result is enqueued as ONE plain `Uint8Array` (not a
//!     Buffer); an empty result enqueues nothing.
//!   * A codec error is rethrown as `new TypeError(err.message)`, e.g.
//!     `TypeError: zlib: unsupported compression method`. A RangeError for
//!     more than 1 MiB passes through unchanged.
//!   * The error surfaces as the `writer.close()` rejection. A directly held
//!     `reader.read()` hangs; through `pipeThrough`, `read()` rejects.
//! * **Codecs:** CS gzip/deflate/deflate-raw = gzipSync / deflateSync /
//!   deflateRawSync; DS = gunzipSync / inflateSync / inflateRawSync.
//!   Nothing is output before close.
//! * **Double close:** calling `writer.close()` twice in a row resolves both
//!   and enqueues the output twice (a quirk of the runtime's
//!   TransformStream).
//!
//! ### 2.7 `zlib.crc32(data, value = 0)`
//!
//! * `data` is converted as in 2.2. `value` is converted with `value >>> 0`;
//!   BigInt and Symbol throw the usual TypeErrors.
//! * Returns an unsigned Number.
//! * Examples: `crc32('hello') = 907060870`,
//!   `crc32('hello', -1) = 265137764`,
//!   `crc32('world', crc32('hello ')) = 222957957`, `crc32('', -1) = 4294967295`.
//!
//! ## 3. Codec behaviour (what this module implements)
//!
//! ### 3.1 Deflate encoder (`deflate.rs`)
//!
//! * **Block structure:** one final fixed-Huffman block, built by greedy LZ77
//!   with a 15-bit multiplicative hash and a 128-entry chain walk.
//! * **Window:** unlimited. A distance over 32768 is written with code 29
//!   and unmasked extra bits, which corrupts the stream exactly as the
//!   original does. See the `deflate.rs` docs.
//! * **zlib wrapper:** header `78 9c`.
//! * **gzip wrapper:** header `1f8b 08 00 00000000 00 ff`. This differs from
//!   node, which writes OS byte `03`.
//!
//! ### 3.2 Deflate decoders (`inflate.rs`)
//!
//! * **Huffman decoding:** puff-exact. Code tables are never validated.
//!   NLEN, FCHECK, FDICT, Adler-32, gzip CRC and ISIZE are NOT checked.
//!   Decoding stops at the final block and trailing data is ignored.
//! * **zlib:** fewer than 6 bytes gives `zlib: input too short`. A CM
//!   nibble other than 8 gives `zlib: unsupported compression method`.
//!   Otherwise the decoder inflates `data[2..]`, so a DICTID is decoded as
//!   deflate data.
//! * **gzip:** fewer than 18 bytes or a wrong magic gives `gzip: bad magic`.
//!   Byte 2 other than 8 gives `gzip: unsupported compression method`. Then
//!   FEXTRA, FNAME, FCOMMENT and FHCRC are parsed inside `data[..len-8]`;
//!   running past that limit gives `gzip: truncated`. Finally the decoder
//!   inflates `data[hdr..len-8]`. Only the first member is decoded.
//!   `unzipSync` behaves identically, with no zlib auto-detection.
//! * **inflate messages:** `unexpected end of input`, `reserved block type`,
//!   `truncated stored block` (fewer than 4 LEN/NLEN bytes),
//!   `stored block overruns input`, `invalid Huffman code` (no code within
//!   15 bits), `repeat with no previous length`, `code-length overrun`,
//!   `invalid literal/length symbol` (286/287), `invalid distance symbol`
//!   (30/31), `distance too far back`.
//!
//! ### 3.3 Brotli encoder (`brotli_enc.rs`)
//!
//! * **Stream header:** WBITS is always 22.
//! * **Stored meta-block** when either:
//!   * the input is at most 16 bytes, or
//!   * there are at least 5 distinct byte values and the Huffman bits + 1400
//!     are at least 8 × length.
//! * **Otherwise:** one compressed meta-block holding a single literal-only
//!   command. The `brotli_enc.rs` docs give the exact Huffman,
//!   code-length-code and simple-code rules.
//! * **Samples:**
//!   * `''` → `3b`
//!   * `'a'` → `0b00806103`
//!   * `'abc'×10` → `1b1d000020c3c4c602a300a8b5d65a6bad35`
//!
//! ### 3.4 Brotli decoder (`brotli_dec.rs`)
//!
//! * **Strictness:** as strict as RFC 7932, with one exception: the final
//!   padding after the last meta-block is not checked. So `deadbeef`
//!   decodes to empty output. Trailing bytes are ignored.
//! * **Messages** (all prefixed `brotli: `):
//!   * `unexpected end of input`
//!   * `uncompressed block overruns input`
//!   * `metadata overruns input`
//!   * `large-window streams are not supported`
//!   * `exuberant size nibble`
//!   * `reserved bit set`
//!   * `exuberant metadata size byte`
//!   * `non-zero padding bits`
//!   * `simple code symbol out of range`
//!   * `duplicate simple code symbol`
//!   * `corrupt code-length code`
//!   * `code-length run overflows alphabet`
//!   * `prefix code is under/over-subscribed`
//!   * `context map run overflows`
//!   * `meta-block length mismatch`
//!   * `invalid short distance`
//!   * `invalid dictionary reference length`
//!   * `invalid dictionary transform`
//!   * `block length exhausted with a single block type`
//! * **Insert overrun:** an insert that overruns MLEN is reported only after
//!   all of its literals were decoded. So if the input is truncated there,
//!   the result is "unexpected end of input".
//!
//! ### 3.5 Zstd encoder (`zstd_enc.rs`)
//!
//! * Raw and RLE blocks only.
//! * Single-segment frame header with content size and checksum.
//! * `''` → `28b52ffd240001000099e9d851`
//!
//! ### 3.6 Zstd decoder (`zstd_dec.rs`)
//!
//! * **Frames:** any number of frames and skippable frames. Trailing bytes
//!   give `truncated frame` (1–3 bytes) or `bad magic number`.
//! * **Window:** the window descriptor is ignored.
//! * **Rejected:** a non-zero dictionary id gives
//!   `dictionary frames are not supported`.
//! * **Verified:** the content size and the checksum.
//! * **Messages:** the 55 messages are listed in the `zstd_dec.rs` module
//!   docs, e.g.
//!   `zstd: empty input`, `zstd: truncated raw block`,
//!   `zstd: content checksum mismatch`.
//!
//! ## 4. Known gaps
//!
//! The following cannot be compared with the original, because inputs and
//! outputs above 1 MiB cannot exist there:
//! * brotli inputs over 16 MiB (this module splits them into 16 MiB
//!   meta-blocks);
//! * zstd 8-byte content-size fields;
//! * very long inputs in general.
//!
//! Everything testable matched exactly.

// The parent crate may use only part of this API.
#![allow(dead_code)]

pub mod brotli_dec;
pub mod brotli_enc;
pub mod checksum;
pub mod deflate;
pub mod inflate;
pub mod zstd_dec;
pub mod zstd_enc;

#[allow(unused_imports)]
pub use checksum::{adler32, crc32, xxh64};

/// Decoder failure. `message` is exactly the original's `Error.message`.
/// The original's errors have no `code`/`errno`: `code` is always `""` and
/// `errno` always `0` (do not expose them to JS).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodecError {
    pub message: String,
    pub code: &'static str,
    pub errno: i32,
}

impl CodecError {
    pub(crate) fn new(message: impl Into<String>) -> Self {
        CodecError { message: message.into(), code: "", errno: 0 }
    }
}

impl std::fmt::Display for CodecError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CodecError {}

/// zlib-family options with node's defaults. The original ignores them all.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeflateOptions {
    pub level: i32,
    pub window_bits: i32,
    pub mem_level: i32,
    pub strategy: i32,
    pub dictionary: Option<Vec<u8>>,
}

impl Default for DeflateOptions {
    fn default() -> Self {
        DeflateOptions { level: -1, window_bits: 15, mem_level: 8, strategy: 0, dictionary: None }
    }
}

/// `zlib.deflateRawSync`.
pub fn deflate_raw(data: &[u8], _opts: &DeflateOptions) -> Vec<u8> {
    deflate::deflate_raw_bytes(data)
}

/// `zlib.deflateSync`.
pub fn zlib_encode(data: &[u8], _opts: &DeflateOptions) -> Vec<u8> {
    deflate::zlib_bytes(data)
}

/// `zlib.gzipSync`.
pub fn gzip_encode(data: &[u8], _opts: &DeflateOptions) -> Vec<u8> {
    deflate::gzip_bytes(data)
}

/// `zlib.inflateRawSync`. `dictionary` is an extension (the original
/// ignores the option): pass `None` for fidelity.
pub fn inflate_raw(data: &[u8], dictionary: Option<&[u8]>) -> Result<Vec<u8>, CodecError> {
    inflate::inflate_raw(data, dictionary)
}

/// `zlib.inflateSync`. `dictionary` is an extension (the original ignores
/// the option): pass `None` for fidelity.
pub fn zlib_decode(data: &[u8], dictionary: Option<&[u8]>) -> Result<Vec<u8>, CodecError> {
    inflate::zlib_decode(data, dictionary)
}

/// `zlib.gunzipSync` (first member only).
pub fn gzip_decode(data: &[u8]) -> Result<Vec<u8>, CodecError> {
    inflate::gzip_decode(data)
}

/// `zlib.unzipSync`: in the original this is exactly `gunzipSync` (no zlib
/// auto-detection; a zlib stream fails with `gzip: bad magic`).
pub fn unzip_decode(data: &[u8]) -> Result<Vec<u8>, CodecError> {
    inflate::gzip_decode(data)
}

/// Brotli encoder parameters (node defaults). The original ignores them.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BrotliOptions {
    pub quality: u32,
    pub lgwin: u32,
    pub mode: u32,
    pub size_hint: u64,
}

impl Default for BrotliOptions {
    fn default() -> Self {
        BrotliOptions { quality: 11, lgwin: 22, mode: 0, size_hint: 0 }
    }
}

/// `zlib.brotliCompressSync`.
pub fn brotli_encode(data: &[u8], _opts: &BrotliOptions) -> Vec<u8> {
    brotli_enc::brotli_bytes(data)
}

/// `zlib.brotliDecompressSync`.
pub fn brotli_decode(data: &[u8]) -> Result<Vec<u8>, CodecError> {
    brotli_dec::decode(data)
}

/// `zlib.zstdCompressSync` (`level` and all other parameters are ignored).
pub fn zstd_encode(data: &[u8], _level: i32) -> Vec<u8> {
    zstd_enc::zstd_bytes(data)
}

/// `zlib.zstdDecompressSync`.
pub fn zstd_decode(data: &[u8]) -> Result<Vec<u8>, CodecError> {
    zstd_dec::decode(data)
}

/// The codec behind each zlib stream class and each Compression/
/// DecompressionStream format.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Codec {
    Gzip,
    Gunzip,
    Deflate,
    Inflate,
    DeflateRaw,
    InflateRaw,
    Unzip,
    BrotliCompress,
    BrotliDecompress,
    ZstdCompress,
    ZstdDecompress,
}

impl Codec {
    /// Process a whole input exactly like the corresponding `*Sync` function.
    pub fn run(self, input: &[u8]) -> Result<Vec<u8>, CodecError> {
        let o = DeflateOptions::default();
        Ok(match self {
            Codec::Gzip => gzip_encode(input, &o),
            Codec::Gunzip => return gzip_decode(input),
            Codec::Deflate => zlib_encode(input, &o),
            Codec::Inflate => return zlib_decode(input, None),
            Codec::DeflateRaw => deflate_raw(input, &o),
            Codec::InflateRaw => return inflate_raw(input, None),
            Codec::Unzip => return unzip_decode(input),
            Codec::BrotliCompress => brotli_encode(input, &BrotliOptions::default()),
            Codec::BrotliDecompress => return brotli_decode(input),
            Codec::ZstdCompress => zstd_encode(input, 3),
            Codec::ZstdDecompress => return zstd_decode(input),
        })
    }

    /// True for the compressing direction.
    pub fn is_compressor(self) -> bool {
        matches!(
            self,
            Codec::Gzip | Codec::Deflate | Codec::DeflateRaw | Codec::BrotliCompress | Codec::ZstdCompress
        )
    }

    /// `new CompressionStream(format)`: `format` is `String(arg)`; `None`
    /// means TypeError `Unsupported CompressionStream format: '<format>'`.
    pub fn for_compression_stream(format: &str) -> Option<Codec> {
        match format {
            "gzip" => Some(Codec::Gzip),
            "deflate" => Some(Codec::Deflate),
            "deflate-raw" => Some(Codec::DeflateRaw),
            _ => None,
        }
    }

    /// `new DecompressionStream(format)`: `None` means TypeError
    /// `Unsupported DecompressionStream format: '<format>'`.
    pub fn for_decompression_stream(format: &str) -> Option<Codec> {
        match format {
            "gzip" => Some(Codec::Gunzip),
            "deflate" => Some(Codec::Inflate),
            "deflate-raw" => Some(Codec::InflateRaw),
            _ => None,
        }
    }
}

/// Stream driver matching the original: buffer every chunk, run the codec
/// once at the end, produce a single output chunk. `finish` does not clear
/// the buffered input (the original's `_chunks` is never cleared).
#[derive(Debug, Clone)]
pub struct BufferedCodec {
    codec: Codec,
    input: Vec<u8>,
}

impl BufferedCodec {
    pub fn new(codec: Codec) -> Self {
        BufferedCodec { codec, input: Vec::new() }
    }

    pub fn codec(&self) -> Codec {
        self.codec
    }

    pub fn write(&mut self, chunk: &[u8]) {
        self.input.extend_from_slice(chunk);
    }

    pub fn finish(&self) -> Result<Vec<u8>, CodecError> {
        self.codec.run(&self.input)
    }
}

/// `zlib.constants` in the original's exact key order (`None` = `null`, the
/// value of `Z_MAX_CHUNK`).
pub const ZLIB_CONSTANTS: &[(&str, Option<i64>)] = &[
    ("Z_NO_FLUSH", Some(0)),
    ("Z_PARTIAL_FLUSH", Some(1)),
    ("Z_SYNC_FLUSH", Some(2)),
    ("Z_FULL_FLUSH", Some(3)),
    ("Z_FINISH", Some(4)),
    ("Z_BLOCK", Some(5)),
    ("Z_OK", Some(0)),
    ("Z_STREAM_END", Some(1)),
    ("Z_NEED_DICT", Some(2)),
    ("Z_ERRNO", Some(-1)),
    ("Z_STREAM_ERROR", Some(-2)),
    ("Z_DATA_ERROR", Some(-3)),
    ("Z_MEM_ERROR", Some(-4)),
    ("Z_BUF_ERROR", Some(-5)),
    ("Z_VERSION_ERROR", Some(-6)),
    ("Z_NO_COMPRESSION", Some(0)),
    ("Z_BEST_SPEED", Some(1)),
    ("Z_BEST_COMPRESSION", Some(9)),
    ("Z_DEFAULT_COMPRESSION", Some(-1)),
    ("Z_FILTERED", Some(1)),
    ("Z_HUFFMAN_ONLY", Some(2)),
    ("Z_RLE", Some(3)),
    ("Z_FIXED", Some(4)),
    ("Z_DEFAULT_STRATEGY", Some(0)),
    ("ZLIB_VERNUM", Some(4865)),
    ("DEFLATE", Some(1)),
    ("INFLATE", Some(2)),
    ("GZIP", Some(3)),
    ("GUNZIP", Some(4)),
    ("DEFLATERAW", Some(5)),
    ("INFLATERAW", Some(6)),
    ("UNZIP", Some(7)),
    ("BROTLI_DECODE", Some(8)),
    ("BROTLI_ENCODE", Some(9)),
    ("ZSTD_DECOMPRESS", Some(11)),
    ("ZSTD_COMPRESS", Some(10)),
    ("Z_MIN_WINDOWBITS", Some(8)),
    ("Z_MAX_WINDOWBITS", Some(15)),
    ("Z_DEFAULT_WINDOWBITS", Some(15)),
    ("Z_MIN_CHUNK", Some(64)),
    ("Z_MAX_CHUNK", None),
    ("Z_DEFAULT_CHUNK", Some(16384)),
    ("Z_MIN_MEMLEVEL", Some(1)),
    ("Z_MAX_MEMLEVEL", Some(9)),
    ("Z_DEFAULT_MEMLEVEL", Some(8)),
    ("Z_MIN_LEVEL", Some(-1)),
    ("Z_MAX_LEVEL", Some(9)),
    ("Z_DEFAULT_LEVEL", Some(-1)),
    ("BROTLI_OPERATION_PROCESS", Some(0)),
    ("BROTLI_OPERATION_FLUSH", Some(1)),
    ("BROTLI_OPERATION_FINISH", Some(2)),
    ("BROTLI_OPERATION_EMIT_METADATA", Some(3)),
    ("BROTLI_PARAM_MODE", Some(0)),
    ("BROTLI_MODE_GENERIC", Some(0)),
    ("BROTLI_MODE_TEXT", Some(1)),
    ("BROTLI_MODE_FONT", Some(2)),
    ("BROTLI_DEFAULT_MODE", Some(0)),
    ("BROTLI_PARAM_QUALITY", Some(1)),
    ("BROTLI_MIN_QUALITY", Some(0)),
    ("BROTLI_MAX_QUALITY", Some(11)),
    ("BROTLI_DEFAULT_QUALITY", Some(11)),
    ("BROTLI_PARAM_LGWIN", Some(2)),
    ("BROTLI_MIN_WINDOW_BITS", Some(10)),
    ("BROTLI_MAX_WINDOW_BITS", Some(24)),
    ("BROTLI_LARGE_MAX_WINDOW_BITS", Some(30)),
    ("BROTLI_DEFAULT_WINDOW", Some(22)),
    ("BROTLI_PARAM_LGBLOCK", Some(3)),
    ("BROTLI_MIN_INPUT_BLOCK_BITS", Some(16)),
    ("BROTLI_MAX_INPUT_BLOCK_BITS", Some(24)),
    ("BROTLI_PARAM_DISABLE_LITERAL_CONTEXT_MODELING", Some(4)),
    ("BROTLI_PARAM_SIZE_HINT", Some(5)),
    ("BROTLI_PARAM_LARGE_WINDOW", Some(6)),
    ("BROTLI_PARAM_NPOSTFIX", Some(7)),
    ("BROTLI_PARAM_NDIRECT", Some(8)),
    ("BROTLI_DECODER_RESULT_ERROR", Some(0)),
    ("BROTLI_DECODER_RESULT_SUCCESS", Some(1)),
    ("BROTLI_DECODER_RESULT_NEEDS_MORE_INPUT", Some(2)),
    ("BROTLI_DECODER_RESULT_NEEDS_MORE_OUTPUT", Some(3)),
    ("BROTLI_DECODER_PARAM_DISABLE_RING_BUFFER_REALLOCATION", Some(0)),
    ("BROTLI_DECODER_PARAM_LARGE_WINDOW", Some(1)),
    ("BROTLI_DECODER_NO_ERROR", Some(0)),
    ("BROTLI_DECODER_SUCCESS", Some(1)),
    ("BROTLI_DECODER_NEEDS_MORE_INPUT", Some(2)),
    ("BROTLI_DECODER_NEEDS_MORE_OUTPUT", Some(3)),
    ("BROTLI_DECODER_ERROR_FORMAT_EXUBERANT_NIBBLE", Some(-1)),
    ("BROTLI_DECODER_ERROR_FORMAT_RESERVED", Some(-2)),
    ("BROTLI_DECODER_ERROR_FORMAT_EXUBERANT_META_NIBBLE", Some(-3)),
    ("BROTLI_DECODER_ERROR_FORMAT_SIMPLE_HUFFMAN_ALPHABET", Some(-4)),
    ("BROTLI_DECODER_ERROR_FORMAT_SIMPLE_HUFFMAN_SAME", Some(-5)),
    ("BROTLI_DECODER_ERROR_FORMAT_CL_SPACE", Some(-6)),
    ("BROTLI_DECODER_ERROR_FORMAT_HUFFMAN_SPACE", Some(-7)),
    ("BROTLI_DECODER_ERROR_FORMAT_CONTEXT_MAP_REPEAT", Some(-8)),
    ("BROTLI_DECODER_ERROR_FORMAT_BLOCK_LENGTH_1", Some(-9)),
    ("BROTLI_DECODER_ERROR_FORMAT_BLOCK_LENGTH_2", Some(-10)),
    ("BROTLI_DECODER_ERROR_FORMAT_TRANSFORM", Some(-11)),
    ("BROTLI_DECODER_ERROR_FORMAT_DICTIONARY", Some(-12)),
    ("BROTLI_DECODER_ERROR_FORMAT_WINDOW_BITS", Some(-13)),
    ("BROTLI_DECODER_ERROR_FORMAT_PADDING_1", Some(-14)),
    ("BROTLI_DECODER_ERROR_FORMAT_PADDING_2", Some(-15)),
    ("BROTLI_DECODER_ERROR_FORMAT_DISTANCE", Some(-16)),
    ("BROTLI_DECODER_ERROR_DICTIONARY_NOT_SET", Some(-19)),
    ("BROTLI_DECODER_ERROR_INVALID_ARGUMENTS", Some(-20)),
    ("BROTLI_DECODER_ERROR_ALLOC_CONTEXT_MODES", Some(-21)),
    ("BROTLI_DECODER_ERROR_ALLOC_TREE_GROUPS", Some(-22)),
    ("BROTLI_DECODER_ERROR_ALLOC_CONTEXT_MAP", Some(-25)),
    ("BROTLI_DECODER_ERROR_ALLOC_RING_BUFFER_1", Some(-26)),
    ("BROTLI_DECODER_ERROR_ALLOC_RING_BUFFER_2", Some(-27)),
    ("BROTLI_DECODER_ERROR_ALLOC_BLOCK_TYPE_TREES", Some(-30)),
    ("BROTLI_DECODER_ERROR_UNREACHABLE", Some(-31)),
    ("ZSTD_e_continue", Some(0)),
    ("ZSTD_e_flush", Some(1)),
    ("ZSTD_e_end", Some(2)),
    ("ZSTD_fast", Some(1)),
    ("ZSTD_dfast", Some(2)),
    ("ZSTD_greedy", Some(3)),
    ("ZSTD_lazy", Some(4)),
    ("ZSTD_lazy2", Some(5)),
    ("ZSTD_btlazy2", Some(6)),
    ("ZSTD_btopt", Some(7)),
    ("ZSTD_btultra", Some(8)),
    ("ZSTD_btultra2", Some(9)),
    ("ZSTD_c_compressionLevel", Some(100)),
    ("ZSTD_c_windowLog", Some(101)),
    ("ZSTD_c_hashLog", Some(102)),
    ("ZSTD_c_chainLog", Some(103)),
    ("ZSTD_c_searchLog", Some(104)),
    ("ZSTD_c_minMatch", Some(105)),
    ("ZSTD_c_targetLength", Some(106)),
    ("ZSTD_c_strategy", Some(107)),
    ("ZSTD_c_enableLongDistanceMatching", Some(160)),
    ("ZSTD_c_ldmHashLog", Some(161)),
    ("ZSTD_c_ldmMinMatch", Some(162)),
    ("ZSTD_c_ldmBucketSizeLog", Some(163)),
    ("ZSTD_c_ldmHashRateLog", Some(164)),
    ("ZSTD_c_contentSizeFlag", Some(200)),
    ("ZSTD_c_checksumFlag", Some(201)),
    ("ZSTD_c_dictIDFlag", Some(202)),
    ("ZSTD_c_nbWorkers", Some(400)),
    ("ZSTD_c_jobSize", Some(401)),
    ("ZSTD_c_overlapLog", Some(402)),
    ("ZSTD_d_windowLogMax", Some(100)),
    ("ZSTD_CLEVEL_DEFAULT", Some(3)),
    ("ZSTD_error_no_error", Some(0)),
    ("ZSTD_error_GENERIC", Some(1)),
    ("ZSTD_error_prefix_unknown", Some(10)),
    ("ZSTD_error_version_unsupported", Some(12)),
    ("ZSTD_error_frameParameter_unsupported", Some(14)),
    ("ZSTD_error_frameParameter_windowTooLarge", Some(16)),
    ("ZSTD_error_corruption_detected", Some(20)),
    ("ZSTD_error_checksum_wrong", Some(22)),
    ("ZSTD_error_literals_headerWrong", Some(24)),
    ("ZSTD_error_dictionary_corrupted", Some(30)),
    ("ZSTD_error_dictionary_wrong", Some(32)),
    ("ZSTD_error_dictionaryCreation_failed", Some(34)),
    ("ZSTD_error_parameter_unsupported", Some(40)),
    ("ZSTD_error_parameter_combination_unsupported", Some(41)),
    ("ZSTD_error_parameter_outOfBound", Some(42)),
    ("ZSTD_error_tableLog_tooLarge", Some(44)),
    ("ZSTD_error_maxSymbolValue_tooLarge", Some(46)),
    ("ZSTD_error_maxSymbolValue_tooSmall", Some(48)),
    ("ZSTD_error_stabilityCondition_notRespected", Some(50)),
    ("ZSTD_error_stage_wrong", Some(60)),
    ("ZSTD_error_init_missing", Some(62)),
    ("ZSTD_error_memory_allocation", Some(64)),
    ("ZSTD_error_workSpace_tooSmall", Some(66)),
    ("ZSTD_error_dstSize_tooSmall", Some(70)),
    ("ZSTD_error_srcSize_wrong", Some(72)),
    ("ZSTD_error_dstBuffer_null", Some(74)),
    ("ZSTD_error_noForwardProgress_destFull", Some(80)),
    ("ZSTD_error_noForwardProgress_inputEmpty", Some(82)),
];

#[cfg(test)]
mod tests {
    use super::*;

    fn hex(b: &[u8]) -> String {
        b.iter().map(|x| format!("{:02x}", x)).collect()
    }

    #[test]
    fn documented_samples() {
        let o = DeflateOptions::default();
        assert_eq!(hex(&zlib_encode(b"", &o)), "789c030000000001");
        assert_eq!(hex(&zlib_encode(b"hello", &o)), "789ccb48cdc9c90700062c0215");
        assert_eq!(hex(&deflate_raw(b"hello", &o)), "cb48cdc9c90700");
        assert_eq!(hex(&gzip_encode(b"hello", &o)), "1f8b08000000000000ffcb48cdc9c9070086a6103605000000");
        assert_eq!(hex(&brotli_encode(b"", &BrotliOptions::default())), "3b");
        assert_eq!(hex(&brotli_encode(b"hello", &BrotliOptions::default())), "0b028068656c6c6f03");
        assert_eq!(hex(&zstd_encode(b"hello", 3)), "28b52ffd240529000068656c6c6fa36d9f88");
        assert_eq!(crc32(b"hello", 0), 907060870);
        assert_eq!(crc32(b"hello", 0xffff_ffff), 265137764);
        assert_eq!(crc32(b"world", crc32(b"hello ", 0)), 222957957);
        assert_eq!(crc32(b"", 0xffff_ffff), 4294967295);
    }

    #[test]
    fn round_trips() {
        let mut data = Vec::new();
        for i in 0..20000u32 {
            data.extend_from_slice(format!("line {} {}\n", i % 97, i * 7 % 13).as_bytes());
        }
        for codec in [Codec::Gzip, Codec::Deflate, Codec::DeflateRaw, Codec::BrotliCompress, Codec::ZstdCompress] {
            let c = codec.run(&data).unwrap();
            let back = match codec {
                Codec::Gzip => Codec::Gunzip,
                Codec::Deflate => Codec::Inflate,
                Codec::DeflateRaw => Codec::InflateRaw,
                Codec::BrotliCompress => Codec::BrotliDecompress,
                _ => Codec::ZstdDecompress,
            }
            .run(&c)
            .unwrap();
            assert_eq!(back, data, "{:?}", codec);
        }
    }

    #[test]
    fn buffered_stream() {
        let mut s = BufferedCodec::new(Codec::Gzip);
        s.write(b"hello ");
        s.write(b"world");
        assert_eq!(s.finish().unwrap(), gzip_encode(b"hello world", &DeflateOptions::default()));
        assert_eq!(Codec::for_compression_stream("deflate-raw"), Some(Codec::DeflateRaw));
        assert_eq!(Codec::for_decompression_stream("br"), None);
        let e = Codec::Gunzip.run(b"not gzip data").unwrap_err();
        assert_eq!(e.message, "gzip: bad magic");
        assert_eq!((e.code, e.errno), ("", 0));
    }

    #[test]
    fn constants_table() {
        assert_eq!(ZLIB_CONSTANTS.len(), 170);
        assert_eq!(ZLIB_CONSTANTS[0], ("Z_NO_FLUSH", Some(0)));
        assert!(ZLIB_CONSTANTS.contains(&("Z_MAX_CHUNK", None)));
        assert!(ZLIB_CONSTANTS.contains(&("ZLIB_VERNUM", Some(4865))));
    }

    /// Decodes every file of `assets/test_runtime_compression` (skipped when
    /// the directory is absent) and compares length + CRC-32 of the output
    /// with what the original runtime produced.
    #[test]
    fn bundled_assets() {
        let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("assets/test_runtime_compression");
        if !dir.is_dir() {
            return;
        }
        let expected: &[(&str, Result<(usize, u32), &str>)] = &[
        ("alt2.q11.br", Ok((7200, 4077415593))),
        ("go.zero-dictionary-ids.zst", Ok((18, 1030108986))),
        ("mix.q5.br", Ok((10500, 1731470084))),
        ("mix3.q11.br", Ok((7500, 1994588667))),
        ("multi.zst", Ok((4000, 2907092674))),
        ("random.l3.zst", Ok((3000, 4255845390))),
        ("random.l9.raw", Ok((3000, 4255845390))),
        ("random.q6.br", Ok((3000, 4255845390))),
        ("runs.rle.zz", Ok((6006, 3591602844))),
        ("text.filtered.w9.zz", Ok((8000, 1978999316))),
        ("text.fixed.zz", Ok((8000, 1978999316))),
        ("text.flushes.raw", Ok((8000, 1978999316))),
        ("text.huff.zz", Ok((8000, 1978999316))),
        ("text.l0.zz", Ok((8000, 1978999316))),
        ("text.l1.flushes.zst", Ok((8000, 1978999316))),
        ("text.l1.zst", Ok((8000, 1978999316))),
        ("text.l1.zz", Ok((8000, 1978999316))),
        ("text.l19.check.zst", Ok((8000, 1978999316))),
        ("text.l19.flushes.zst", Ok((8000, 1978999316))),
        ("text.l3.check.zst", Ok((8000, 1978999316))),
        ("text.l6.flushes.zst", Ok((8000, 1978999316))),
        ("text.l6.gz", Ok((8000, 1978999316))),
        ("text.l6.raw", Ok((8000, 1978999316))),
        ("text.l9.nosize.zst", Ok((8000, 1978999316))),
        ("text.l9.zz", Ok((8000, 1978999316))),
        ("text.largewin.br", Err("brotli: large-window streams are not supported")),
        ("text.q0.br", Ok((8000, 1978999316))),
        ("text.q1.br", Ok((8000, 1978999316))),
        ("text.q11.br", Ok((8000, 1978999316))),
        ("text.q4.br", Ok((8000, 1978999316))),
        ("text.q5.flushes.br", Ok((8000, 1978999316))),
        ("text.q5.w10.br", Ok((8000, 1978999316))),
        ("text.q9.postfix.br", Ok((8000, 1978999316))),
        ("text.q9.text.br", Ok((8000, 1978999316))),
        ("text3k.headers.gz", Ok((3000, 3865584539))),
        ("tri.q11.br", Ok((3600, 1754491527))),
        ("underscore.min.js.br", Ok((18798, 3837248835))),
        ("underscore.min.js.gz", Ok((18798, 3837248835))),
        ("underscore.q7.font.br", Ok((18798, 3837248835))),
        ("zeros20k.l3.zst", Ok((20000, 2536461058))),
        ];
        for (name, want) in expected {
            let data = std::fs::read(dir.join(name)).unwrap();
            let got = match name.rsplit('.').next().unwrap() {
                "gz" => gzip_decode(&data),
                "zz" => zlib_decode(&data, None),
                "raw" => inflate_raw(&data, None),
                "br" => brotli_decode(&data),
                _ => zstd_decode(&data),
            };
            match (got, want) {
                (Ok(o), Ok((n, c))) => assert_eq!((o.len(), crc32(&o, 0)), (*n, *c), "{}", name),
                (Err(e), Err(m)) => assert_eq!(e.message, *m, "{}", name),
                (g, w) => panic!("{}: got {:?}, want {:?}", name, g.map(|o| o.len()), w),
            }
        }
    }
}
