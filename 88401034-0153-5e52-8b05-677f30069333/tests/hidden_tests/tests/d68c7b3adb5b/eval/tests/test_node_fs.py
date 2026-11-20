"""Filesystem and host-backed builtins: the raw lumen-fs `fs` global (sync ops, resource-table
handles, `fs.promises`), node:fs (sync, callback, promises/FileHandle, fd ops, streams, stat
fields, links, errors), node:os facts and node:zlib codecs.

Programs only touch files they create inside the per-test workdir, always through relative
paths, and only print deterministic facts (sizes, modes and times they set themselves, sorted
directory listings, error codes/messages for relative paths).
"""

import base64
import gzip
import zlib

import pytest

from conftest import out

TIERS = [pytest.param((), id="jit"), pytest.param(("--tier=bytecode",), id="bytecode"),
         pytest.param(("--tier=interp",), id="interp")]

TRY = r"""
const tryit = (label, f) => {
  try { const r = f(); console.log(label, '->', r === undefined ? 'ok' : JSON.stringify(r)); }
  catch (e) { console.log(label, '->', e.constructor.name, e.code, e.syscall, e.path, '|', e.message); }
};
"""


# ------------------------------------------------------------------------- raw lumen-fs global
@pytest.mark.parametrize("tier", TIERS)
def test_raw_fs_global_sync_ops_and_handles(js, golden, tier):
    """CATCHES: a raw `fs` global whose write/append/read lose or re-encode UTF-8, whose mkdirSync
    is not recursive/idempotent, whose readdirSync is unsorted, whose handle reads do not consume
    the file, whose open modes (w/a/r+) truncate or append wrongly, or whose positional
    pread/pwrite/fstat/ftruncate ops misbehave."""
    code = r"""
const raw = globalThis.fs;
console.log(raw === require('fs'), typeof raw.readFileSync, typeof raw.promises.writeFile);
raw.writeFileSync('a.txt', 'héllo');
raw.appendFileSync('a.txt', ' wörld');
raw.appendFileSync('new.txt', 'created by append');
console.log(raw.readFileSync('a.txt'), raw.readFileSync('new.txt'), raw.existsSync('a.txt'), raw.existsSync('zz'));
raw.mkdirSync('d/e/f');
raw.mkdirSync('d/e/f');
raw.writeFileSync('d/b', '');
raw.writeFileSync('d/a', 'x');
console.log(JSON.stringify(raw.readdirSync('d')), JSON.stringify(raw.readdirSync('d/e/f')));
const fd = raw.openSync('a.txt');
console.log(JSON.stringify(raw.readSync(fd)), JSON.stringify(raw.readSync(fd)));
raw.closeSync(fd);
raw.closeSync(fd);
const w = raw.openSync('w.txt', 'w');
raw.writeSync(w, 'one ');
raw.writeSync(w, 2);
raw.closeSync(w);
const ap = raw.openSync('w.txt', 'a');
raw.writeSync(ap, ' appended');
raw.closeSync(ap);
const rw = raw.openSync('w.txt', 'r+');
console.log(raw.pwriteSync(rw, 'ONE', 0), Array.from(raw.preadSync(rw, 3, 4)).join(','), raw.fstatSync(rw).size);
console.log(raw.pwriteSync(rw, new Uint8Array([0x21]), -1), Array.from(raw.preadSync(rw, 2, -1)).join(','));
raw.ftruncateSync(rw, 3);
raw.fsyncSync(rw); raw.fdatasyncSync(rw);
raw.closeSync(rw);
const wp = raw.openSync('w.txt', 'w+');
raw.writeSync(wp, 'fresh');
console.log(Array.from(raw.preadSync(wp, 10, 0)).length, raw.readFileSync('w.txt'));
raw.closeSync(wp);
const a2 = raw.openSync('w.txt', 'a+');
raw.writeSync(a2, '+tail');
console.log(JSON.stringify(raw.readSync(a2)), raw.readFileSync('w.txt'));
raw.closeSync(a2);
raw.unlinkSync('new.txt');
console.log(raw.existsSync('new.txt'));
"""
    r = js(code, *tier)
    assert out(r) == golden("raw_fs_sync")
    assert (r.returncode, r.stderr) == (0, b"")


def test_raw_fs_global_errors_and_promises(js):
    """CATCHES: raw fs ops that swallow OS errors, report them without the op name and path, accept
    an invalid open mode or a stale/negative handle, or fs.promises readFile/writeFile that do not
    settle (or settle with the wrong value/rejection) through the thread pool."""
    code = TRY + r"""
const raw = globalThis.fs;
raw.writeFileSync('a.txt', 'A');
raw.mkdirSync('d');
const h = raw.openSync('a.txt');
raw.closeSync(h);
const cases = {
  'read missing': () => raw.readFileSync('missing'),
  'write in missing dir': () => raw.writeFileSync('nodir/x', 'y'),
  'append to dir': () => raw.appendFileSync('d', 'x'),
  'unlink missing': () => raw.unlinkSync('missing'),
  'mkdir under file': () => raw.mkdirSync('a.txt/sub'),
  'readdir missing': () => raw.readdirSync('missing'),
  'open missing': () => raw.openSync('missing'),
  'bad mode': () => raw.openSync('a.txt', 'z'),
  'stale handle': () => { try { raw.readSync(h); } catch (e) { throw new TypeError(e.message.replace(String(h), '<h>')); } },
  'negative handle': () => raw.writeSync(-1, 'x'),
  'close garbage': () => raw.closeSync('nonsense'),
};
for (const [label, f] of Object.entries(cases)) tryit(label, f);
(async () => {
  await raw.promises.writeFile('p.txt', 42);
  console.log('promises read', JSON.stringify(await raw.promises.readFile('p.txt')));
  try { await raw.promises.readFile('missing'); } catch (e) { console.log('rejected', e.message); }
  try { await raw.promises.writeFile('nodir/p', 'x'); } catch (e) { console.log('rejected', e.message); }
})();
"""
    r = js(code)
    assert out(r) == (
        "read missing -> Error undefined undefined undefined | readFileSync 'missing': No such file or directory (os error 2)\n"
        "write in missing dir -> Error undefined undefined undefined | writeFileSync 'nodir/x': No such file or directory (os error 2)\n"
        "append to dir -> Error undefined undefined undefined | appendFileSync 'd': Is a directory (os error 21)\n"
        "unlink missing -> Error undefined undefined undefined | unlinkSync 'missing': No such file or directory (os error 2)\n"
        "mkdir under file -> Error undefined undefined undefined | mkdirSync 'a.txt/sub': Not a directory (os error 20)\n"
        "readdir missing -> Error undefined undefined undefined | readdirSync 'missing': No such file or directory (os error 2)\n"
        "open missing -> Error undefined undefined undefined | openSync 'missing': No such file or directory (os error 2)\n"
        "bad mode -> TypeError undefined undefined undefined | openSync: bad mode 'z'\n"
        "stale handle -> TypeError undefined undefined undefined | bad file descriptor <h>\n"
        "negative handle -> TypeError undefined undefined undefined | bad file descriptor -1\n"
        "close garbage -> ok\n"
        'promises read "42"\n'
        "rejected readFile 'missing': No such file or directory (os error 2)\n"
        "rejected writeFile 'nodir/p': No such file or directory (os error 2)\n")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------- node:fs sync
def test_read_write_append_with_encodings_flags_and_path_kinds(js, golden):
    """CATCHES: node:fs read/write that mangle binary data, ignore encoding arguments (string or
    options form) or the `flag` option, return strings when no encoding was given, or reject
    Buffer / file: URL paths."""
    code = r"""
const fs = require('fs');
fs.writeFileSync('bin.dat', Buffer.from([0, 1, 254, 255, 0x80]));
const bin = fs.readFileSync('bin.dat');
console.log(Buffer.isBuffer(bin), bin.length, Array.from(bin).join(','), fs.readFileSync('bin.dat', 'hex'));
fs.writeFileSync('h.txt', 'cafe', 'hex');
fs.writeFileSync('b64.txt', 'aGk=', { encoding: 'base64' });
console.log(Array.from(fs.readFileSync('h.txt')).join(','), fs.readFileSync('b64.txt', { encoding: 'utf8' }));
fs.writeFileSync('w.txt', 'abc', { flag: 'a' });
fs.writeFileSync('w.txt', 'def', { flag: 'a' });
fs.appendFileSync('w.txt', Buffer.from('ghi'));
fs.appendFileSync('w.txt', 'é', 'utf8');
console.log(fs.readFileSync('w.txt', 'utf8'), fs.readFileSync('w.txt').length, fs.readFileSync('w.txt', 'latin1').length);
fs.writeFileSync('typed.txt', new TextEncoder().encode('u8 view'));
console.log(fs.readFileSync('typed.txt', 'utf8'));
const url = new URL('file://' + process.cwd() + '/w.txt');
console.log(fs.existsSync(Buffer.from('w.txt')), fs.existsSync(url), fs.readFileSync(url, 'utf8').slice(0, 3), fs.existsSync('nope'), fs.existsSync());
fs.truncateSync('w.txt', 4);
console.log(JSON.stringify(fs.readFileSync('w.txt', 'utf8')));
fs.writeFileSync('w.txt', '');
console.log(fs.readFileSync('w.txt').length, JSON.stringify(fs.readFileSync('w.txt', 'utf8')));
"""
    r = js(code)
    assert out(r) == golden("read_write_encodings")
    assert (r.returncode, r.stderr) == (0, b"")


def test_directory_operations(js, golden):
    """CATCHES: mkdir that is not recursive with {recursive:true}, readdir withFileTypes that
    misclassifies entries, rm/rmSync that ignore recursive/force, rename/copyFile/cpSync that
    lose contents, globSync that misses nested matches, or opendir that skips entries."""
    code = r"""
const fs = require('fs');
console.log(fs.mkdirSync('top/mid/leaf', { recursive: true }));
fs.writeFileSync('top/a.txt', 'A');
fs.writeFileSync('top/mid/b.md', 'B');
fs.writeFileSync('top/mid/leaf/c.txt', 'C');
fs.symlinkSync('a.txt', 'top/link');
console.log(fs.readdirSync('top').sort().join(','));
console.log(fs.readdirSync('top', { withFileTypes: true })
  .map((d) => `${d.name}:${d.isFile() ? 'f' : ''}${d.isDirectory() ? 'd' : ''}${d.isSymbolicLink() ? 'l' : ''}:${d.parentPath === 'top'}`)
  .sort().join(' '));
console.log(fs.globSync('top/**/*.txt').sort().join(','), fs.globSync('top/*.md').length);
const dir = fs.opendirSync('top/mid');
const names = [];
for (let e; (e = dir.readSync()); ) names.push(e.name + (e.isDirectory() ? '/' : ''));
dir.closeSync();
console.log(names.sort().join(','));
fs.renameSync('top/a.txt', 'top/renamed.txt');
fs.copyFileSync('top/renamed.txt', 'copy.txt');
console.log(fs.existsSync('top/a.txt'), fs.readFileSync('top/renamed.txt', 'utf8'), fs.readFileSync('copy.txt', 'utf8'));
fs.cpSync('top/mid', 'mirror', { recursive: true });
console.log(fs.readFileSync('mirror/leaf/c.txt', 'utf8'), fs.readdirSync('mirror').sort().join(','));
fs.rmSync('mirror', { recursive: true });
fs.rmSync('does-not-exist', { force: true });
fs.rmSync('copy.txt');
fs.mkdirSync('empty');
fs.rmdirSync('empty');
console.log(fs.existsSync('mirror'), fs.existsSync('copy.txt'), fs.existsSync('empty'));
fs.rmSync('top', { recursive: true, force: true });
console.log(fs.readdirSync('.').sort().join(','));
"""
    r = js(code)
    assert out(r) == golden("directory_ops")
    assert (r.returncode, r.stderr) == (0, b"")


def test_errors_carry_node_codes_and_messages(js, golden):
    """CATCHES: node:fs errors without the errno `code`/`syscall`/`path` fields or with the wrong
    code (ENOENT, EEXIST, ENOTDIR, ENOTEMPTY), recursive mkdir/force rm that throw on existing or
    missing paths, or error messages that do not name the syscall and path."""
    code = TRY + r"""
const fs = require('fs');
fs.writeFileSync('f.txt', 'data');
fs.mkdirSync('d');
fs.writeFileSync('d/inner', 'x');
tryit('readFile missing', () => fs.readFileSync('missing.txt'));
tryit('stat missing', () => fs.statSync('missing.txt'));
tryit('lstat under missing', () => fs.lstatSync('nope/x'));
tryit('mkdir existing', () => fs.mkdirSync('d'));
tryit('mkdir missing parent', () => fs.mkdirSync('x/y'));
tryit('mkdir under file', () => fs.mkdirSync('f.txt/sub'));
try { fs.rmdirSync('d'); } catch (e) { console.log('rmdir non-empty ->', e.code); }
tryit('rm missing', () => fs.rmSync('missing'));
tryit('rm missing force', () => fs.rmSync('missing', { force: true }));
tryit('rename missing', () => fs.renameSync('missing', 'b'));
tryit('copyFile missing', () => fs.copyFileSync('missing', 'b'));
tryit('symlink over existing', () => fs.symlinkSync('f.txt', 'f.txt'));
tryit('link over existing', () => fs.linkSync('f.txt', 'f.txt'));
tryit('access missing', () => fs.accessSync('missing'));
tryit('chmod missing', () => fs.chmodSync('missing', 0o644));
tryit('utimes missing', () => fs.utimesSync('missing', 1, 1));
tryit('statfs missing', () => fs.statfsSync('missing'));
tryit('readdir types missing', () => fs.readdirSync('missing', { withFileTypes: true }));
tryit('lchmod', () => fs.lchmodSync('f.txt', 0o600));
tryit('cp dir without recursive', () => fs.cpSync('d', 'd2'));
tryit('exists', () => fs.existsSync('f.txt'));
"""
    r = js(code)
    assert out(r) == golden("error_codes")
    assert (r.returncode, r.stderr) == (0, b"")


def test_stat_fields_modes_times_and_links(js, golden):
    """CATCHES: Stats objects with wrong size/kind predicates, chmod modes not reflected in
    `mode`, utimes/lutimes/futimes that mis-convert seconds, Dates or fractional times, lstat
    that follows symlinks, hard links that do not share the inode/nlink, or statfs without its
    numeric fields."""
    code = r"""
const fs = require('fs');
fs.writeFileSync('f.bin', 'twelve bytes');
fs.mkdirSync('dir');
fs.chmodSync('f.bin', 0o640);
fs.chmodSync('dir', 0o750);
const s = fs.statSync('f.bin'), d = fs.statSync('dir');
console.log(s.size, s.isFile(), s.isDirectory(), s.isSymbolicLink(), s.isFIFO(), s.isSocket(), s.isBlockDevice());
console.log((s.mode & 0o777).toString(8), (s.mode & 0o170000).toString(8), (d.mode & 0o777).toString(8), d.isDirectory());
console.log(s.uid === process.getuid(), s.gid === process.getgid(), s.nlink, typeof s.ino, typeof s.dev, typeof s.blocks, s instanceof fs.Stats);
fs.utimesSync('f.bin', new Date(86400000), 172800.25);
let t = fs.statSync('f.bin');
console.log(t.atimeMs, t.mtimeMs, t.mtime.toISOString(), t.atime instanceof Date);
fs.utimesSync('f.bin', '1000000000', 1234567890);
t = fs.statSync('f.bin');
console.log(t.atimeMs, t.mtime.toISOString());
fs.linkSync('f.bin', 'hard.bin');
console.log(fs.statSync('f.bin').nlink, fs.statSync('hard.bin').ino === t.ino, fs.readFileSync('hard.bin', 'utf8'));
fs.symlinkSync('f.bin', 'sym');
fs.symlinkSync('missing-target', 'dangling');
fs.lutimesSync('sym', 5, 6);
const l = fs.lstatSync('sym');
console.log(l.isSymbolicLink(), l.isFile(), l.mtimeMs, fs.statSync('sym').mtimeMs, fs.readlinkSync('sym'), fs.readlinkSync('dangling'));
console.log(fs.existsSync('dangling'), fs.lstatSync('dangling').isSymbolicLink());
fs.chownSync('f.bin', process.getuid(), process.getgid());
fs.lchownSync('sym', process.getuid(), process.getgid());
fs.accessSync('f.bin', fs.constants.R_OK);
console.log(fs.constants.F_OK, fs.constants.R_OK, fs.constants.W_OK, fs.constants.X_OK);
const sf = fs.statfsSync('.');
console.log(Object.keys(sf).join(','), sf.bsize > 0, Number.isInteger(sf.blocks));
const real = fs.realpathSync('sym');
console.log(real.endsWith('/f.bin'), real === fs.realpathSync('f.bin'));
const tmp = fs.mkdtempSync('tmp-');
console.log(/^tmp-[0-9a-f]{10}$/.test(tmp), fs.statSync(tmp).isDirectory(), fs.readdirSync(tmp).length);
"""
    r = js(code)
    assert out(r) == golden("stat_fields")
    assert (r.returncode, r.stderr) == (0, b"")


def test_fd_level_read_write_and_metadata(js, golden):
    """CATCHES: fd ops that ignore offset/length/position arguments (positional and options
    forms), readv/writev that scatter/gather wrongly, fstat/ftruncate/fchmod/futimes that act on
    the wrong file, numeric open flags mapped to the wrong mode, or use of a closed fd that does
    not throw."""
    code = r"""
const fs = require('fs');
const fd = fs.openSync('f.bin', 'w+');
console.log(typeof fd, fs.writeSync(fd, 'hello world'), fs.writeSync(fd, Buffer.from([0x21, 0x22]), 0, 1), fs.writeSync(fd, 'XY', 0));
const b = Buffer.alloc(20);
console.log(fs.readSync(fd, b, 0, 20, 0), JSON.stringify(b.toString('utf8', 0, 12)));
console.log(fs.readSync(fd, b, { position: 6, length: 3 }), b.toString('utf8', 0, 3));
console.log(fs.fstatSync(fd).size, fs.fstatSync(fd).isFile());
fs.ftruncateSync(fd, 5);
fs.fsyncSync(fd);
fs.fdatasyncSync(fd);
fs.fchmodSync(fd, 0o604);
fs.futimesSync(fd, 1000000000, 1234567890.5);
const st = fs.fstatSync(fd);
console.log(st.size, (st.mode & 0o777).toString(8), st.mtimeMs, st.atimeMs);
fs.fchownSync(fd, process.getuid(), process.getgid());
console.log(fs.writevSync(fd, [Buffer.from('ab'), Buffer.from('cd')], 0));
const p1 = Buffer.alloc(2), p2 = Buffer.alloc(3);
console.log(fs.readvSync(fd, [p1, p2], 0), p1.toString(), p2.toString());
fs.closeSync(fd);
for (const f of [() => fs.fstatSync(fd), () => fs.readSync(fd, Buffer.alloc(1))]) {
  try { f(); } catch (e) { console.log(e.constructor.name, e.message.replace(/-?\d+$/, '<fd>')); }
}
const c = fs.constants;
const fd2 = fs.openSync('num.txt', c.O_CREAT | c.O_WRONLY | c.O_TRUNC);
fs.writeSync(fd2, 'numeric flags');
fs.closeSync(fd2);
const fd3 = fs.openSync('num.txt', c.O_APPEND | c.O_WRONLY);
fs.writeSync(fd3, '+append');
fs.closeSync(fd3);
const fd4 = fs.openSync('num.txt', 'r');
const out = Buffer.alloc(64);
const n = fs.readSync(fd4, out);
fs.closeSync(fd4);
console.log(n, out.toString('utf8', 0, n), fs.readFileSync('f.bin', 'latin1'));
"""
    r = js(code)
    assert out(r) == golden("fd_ops")
    assert (r.returncode, r.stderr) == (0, b"")


# ---------------------------------------------------------------------- async node:fs surfaces
def test_promises_api_and_filehandle(js, golden):
    """CATCHES: fs/promises functions that do not resolve with Node's shapes (read returns
    {bytesRead, buffer}, write returns {bytesWritten}), FileHandle methods that ignore positions
    or do not close, readdir/withFileTypes/cp/rename/rm that misbehave asynchronously, or
    rejections without the errno code."""
    code = r"""
const fs = require('fs');
const fsp = require('fs/promises');
(async () => {
  console.log(fsp === fs.promises, typeof fsp.constants.R_OK);
  await fsp.writeFile('a.txt', 'line1\nline2\n');
  await fsp.appendFile('a.txt', Buffer.from('line3\n'));
  console.log(JSON.stringify(await fsp.readFile('a.txt', 'utf8')), (await fsp.readFile('a.txt')).length);
  const fh = await fsp.open('a.txt', 'r+');
  const buf = Buffer.alloc(5);
  const r = await fh.read(buf, 0, 5, 6);
  console.log(r.bytesRead, buf.toString(), r.buffer === buf, typeof fh.fd);
  console.log((await fh.write('LINE', 0)).bytesWritten, (await fh.stat()).size);
  await fh.truncate(10);
  console.log(JSON.stringify(await fh.readFile('utf8')));
  await fh.close();
  console.log(JSON.stringify(fs.readFileSync('a.txt', 'utf8')));
  await fsp.mkdir('dir/sub', { recursive: true });
  await fsp.writeFile('dir/sub/z.txt', 'z');
  await fsp.writeFile('dir/b.txt', 'b');
  console.log((await fsp.readdir('dir')).sort().join(','),
    (await fsp.readdir('dir', { withFileTypes: true })).map((d) => d.name + ':' + d.isDirectory()).sort().join(','));
  await fsp.cp('dir', 'copy', { recursive: true });
  await fsp.rename('copy/b.txt', 'copy/renamed.txt');
  console.log(fs.readdirSync('copy').sort().join(','), fs.readFileSync('copy/sub/z.txt', 'utf8'));
  await fsp.rm('copy', { recursive: true });
  console.log(fs.existsSync('copy'));
  await fsp.symlink('dir/b.txt', 'link.txt');
  console.log((await fsp.lstat('link.txt')).isSymbolicLink(), await fsp.readlink('link.txt'), (await fsp.stat('link.txt')).size);
  await fsp.chmod('dir/b.txt', 0o600);
  await fsp.utimes('dir/b.txt', 100, 200);
  const st = await fsp.stat('dir/b.txt');
  console.log((st.mode & 0o777).toString(8), st.mtimeMs, await fsp.access('dir/b.txt'));
  await fsp.unlink('link.txt');
  await fsp.rmdir('dir/sub').catch((e) => console.log('rmdir non-empty', e.code));
  for (const f of [() => fsp.readFile('missing'), () => fsp.stat('missing'), () => fsp.mkdir('dir'), () => fsp.rename('missing', 'x')]) {
    try { await f(); } catch (e) { console.log('rejected', e.code); }
  }
})();
"""
    r = js(code)
    assert out(r) == golden("promises_filehandle")
    assert (r.returncode, r.stderr) == (0, b"")


def test_callback_api_is_error_first_and_asynchronous(js, golden):
    """CATCHES: callback-style node:fs functions that call back synchronously, are not
    error-first, pass the wrong result values, or throw instead of passing the error to the
    callback."""
    code = r"""
const fs = require('fs');
const log = [];
fs.writeFile('cb.txt', 'callback data', (err) => {
  log.push('writeFile ' + err);
  fs.readFile('cb.txt', 'utf8', (err2, data) => {
    log.push('readFile ' + err2 + ' ' + data);
    fs.stat('cb.txt', (err3, st) => {
      log.push('stat ' + err3 + ' ' + st.size + ' ' + st.isFile());
      fs.mkdir('cbdir/a', { recursive: true }, (err4) => {
        log.push('mkdir ' + err4);
        fs.readdir('.', (err5, names) => {
          log.push('readdir ' + err5 + ' ' + names.sort().join(','));
          fs.readFile('missing', (err6, data6) => {
            log.push('readFile missing ' + err6.code + ' ' + data6);
            fs.exists('cb.txt', (yes) => {
              log.push('exists ' + yes);
              fs.unlink('cb.txt', (err7) => {
                log.push('unlink ' + err7 + ' ' + fs.existsSync('cb.txt'));
                console.log(log.join('\n'));
              });
            });
          });
        });
      });
    });
  });
});
log.push('sync code finished first');
"""
    r = js(code)
    assert out(r) == golden("callback_api")
    assert (r.returncode, r.stderr) == (0, b"")


def test_read_and_write_streams(js, golden):
    """CATCHES: createReadStream that ignores start/end/highWaterMark/encoding or never emits
    open/end/close, createWriteStream that loses chunks, ignores the append flag or never emits
    finish/close, or stream.pipeline that does not connect file streams through a Transform."""
    code = r"""
const fs = require('fs');
const { pipeline, Transform } = require('stream');
fs.writeFileSync('src.txt', 'abcdefghijklmnopqrstuvwxyz');
const rs = fs.createReadStream('src.txt', { start: 2, end: 9, highWaterMark: 3 });
const got = [];
rs.on('open', () => got.push('open'));
rs.on('data', (c) => got.push(c.toString()));
rs.on('end', () => got.push('end'));
rs.on('close', () => {
  got.push('close');
  console.log(got.join('|'));
  const upper = new Transform({ transform(chunk, enc, cb) { cb(null, chunk.toString().toUpperCase()); } });
  pipeline(fs.createReadStream('src.txt', { highWaterMark: 10 }), upper, fs.createWriteStream('out.txt'), (err) => {
    console.log('pipeline done', err, fs.readFileSync('out.txt', 'utf8'));
    const ws = fs.createWriteStream('out.txt', { flags: 'a' });
    ws.write('-');
    ws.write(Buffer.from('more'));
    ws.on('finish', () => console.log('finish', ws.bytesWritten, fs.readFileSync('out.txt', 'utf8').slice(24)));
    ws.on('close', () => {
      const parts = [];
      const r2 = fs.createReadStream('out.txt', { encoding: 'utf8', highWaterMark: 8 });
      r2.on('data', (c) => parts.push(c));
      r2.on('end', () => console.log('encoded chunks', JSON.stringify(parts)));
    });
    ws.end('!');
  });
});
"""
    r = js(code)
    assert out(r) == golden("streams")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------------ node:os
def test_os_facts_and_priorities(js, golden):
    """CATCHES: node:os facts inconsistent with process (platform/arch), a homedir that is not
    $HOME, a hostname that ignores $HOSTNAME, wrong EOL/endianness/devNull, priority calls that
    do not round-trip through setpriority/getpriority, or missing ERR_SYSTEM_ERROR /
    ERR_INVALID_ARG_TYPE / ERR_OUT_OF_RANGE errors."""
    code = r"""
const os = require('os');
console.log(os.platform() === process.platform, os.arch() === process.arch, JSON.stringify(os.EOL), os.endianness(), os.devNull);
console.log(os.homedir() === process.env.HOME, os.hostname(), typeof os.tmpdir(), os.tmpdir().length > 0);
console.log(os.type() === (process.platform === 'linux' ? 'Linux' : os.type()), typeof os.release(), os.version() === os.release());
console.log(os.availableParallelism() >= 1, os.cpus().length === os.availableParallelism(), JSON.stringify(Object.keys(os.cpus()[0])));
const lo = Object.values(os.networkInterfaces())[0];
console.log(lo.map((i) => `${i.family} ${i.address} ${i.internal}`).join(', '));
console.log(typeof os.machine(), os.userInfo().homedir === os.homedir(), JSON.stringify(os.loadavg()));
os.setPriority(19);
console.log('after setPriority(19):', os.getPriority(), os.getPriority(0), os.getPriority(process.pid));
os.setPriority(process.pid, 19);
for (const f of [() => os.getPriority('x'), () => os.setPriority('x'), () => os.setPriority(0, 20),
                 () => os.getPriority(2147483646), () => os.setPriority(2147483646, 19)]) {
  try { f(); console.log('no error'); } catch (e) { console.log(e.constructor.name, e.code, e.message, e.info ? e.info.code : ''); }
}
"""
    r = js(code, env_overrides={"HOSTNAME": "suite-host"})
    assert out(r) == golden("os_facts")
    assert (r.returncode, r.stderr) == (0, b"")


# ---------------------------------------------------------------------------------- node:zlib
def test_zlib_codecs_round_trip_and_interoperate(js):
    """CATCHES: zlib codecs that cannot inflate standard zlib/raw-deflate/gzip streams produced
    by another implementation, whose compressors do not round-trip (deflate, raw, gzip, brotli,
    zstd), whose crc32 is wrong or ignores the running seed, or that accept corrupt input."""
    text = b"hello hello hello zlib interop " * 3
    raw = zlib.compressobj(9, zlib.DEFLATED, -15)
    vectors = {
        "inflateSync": base64.b64encode(zlib.compress(text)).decode(),
        "inflateRawSync": base64.b64encode(raw.compress(text) + raw.flush()).decode(),
        "gunzipSync": base64.b64encode(gzip.compress(text, mtime=0)).decode(),
    }
    code = r"""
const zlib = require('zlib');
const vectors = VECTORS;
for (const [fn, b64] of Object.entries(vectors)) console.log(fn, JSON.stringify(zlib[fn](Buffer.from(b64, 'base64')).toString()));
const s = Buffer.from('round trip ' + 'x'.repeat(300) + ' é');
for (const [c, d] of [['deflateSync', 'inflateSync'], ['deflateRawSync', 'inflateRawSync'], ['gzipSync', 'gunzipSync'],
                      ['brotliCompressSync', 'brotliDecompressSync'], ['zstdCompressSync', 'zstdDecompressSync']]) {
  const z = zlib[c](s);
  console.log(c, Buffer.isBuffer(z), zlib[d](z).equals(s), zlib[d](zlib[c](z)).equals(z));
}
const gz = zlib.gzipSync('hdr');
console.log(gz[0], gz[1], gz[2]);
console.log(zlib.crc32('hello'), zlib.crc32(Buffer.from('world'), zlib.crc32('hello ')), zlib.crc32(''));
for (const f of [() => zlib.inflateSync(Buffer.from('not compressed')), () => zlib.gunzipSync(Buffer.from([1, 2, 3]))]) {
  try { f(); console.log('no error'); } catch (e) { console.log(e.constructor.name, e.message); }
}
zlib.gzip('callback api', (err, buf) => zlib.gunzip(buf, (e2, res) => console.log('callbacks', err, e2, res.toString())));
""".replace("VECTORS", repr(vectors).replace("'", '"'))
    r = js(code)
    expected_text = '"' + (text.decode()) + '"'
    assert out(r) == (
        f"inflateSync {expected_text}\ninflateRawSync {expected_text}\ngunzipSync {expected_text}\n"
        "deflateSync true true true\ndeflateRawSync true true true\ngzipSync true true true\n"
        "brotliCompressSync true true true\nzstdCompressSync true true true\n"
        "31 139 8\n"
        f"{zlib.crc32(b'hello')} {zlib.crc32(b'world', zlib.crc32(b'hello '))} 0\n"
        "Error zlib: unsupported compression method\nError gzip: bad magic\n"
        "callbacks null null callback api\n")
    assert (r.returncode, r.stderr) == (0, b"")


def test_fd_callback_api_round_trip(js, golden):
    """CATCHES: callback-style fd functions (open/write/read/fstat/ftruncate/fsync/close) that
    pass the wrong values (fd type, bytes written/read, the same buffer back), ignore the read
    position, or invoke callbacks synchronously."""
    code = r"""
const fs = require('fs');
const log = [];
fs.open('cb.txt', 'w+', (err, fd) => {
  log.push(`open ${err} ${typeof fd}`);
  fs.write(fd, 'callback write', (err2, n, str) => {
    log.push(`write ${err2} ${n} ${str}`);
    const buf = Buffer.alloc(8);
    fs.read(fd, buf, 0, 8, 9, (err3, bytes, b) => {
      log.push(`read ${err3} ${bytes} ${JSON.stringify(b.toString('utf8', 0, bytes))} ${b === buf}`);
      fs.fstat(fd, (err4, st) => {
        log.push(`fstat ${err4} ${st.size} ${st.isFile()}`);
        fs.ftruncate(fd, 8, (err5) => {
          fs.fsync(fd, (err6) => {
            log.push(`ftruncate+fsync ${err5} ${err6} ${fs.readFileSync('cb.txt', 'utf8')}`);
            fs.close(fd, (err7) => {
              log.push(`close ${err7}`);
              fs.truncate('cb.txt', 3, (err8) => {
                log.push(`truncate ${err8} ${JSON.stringify(fs.readFileSync('cb.txt', 'utf8'))}`);
                fs.open('missing/x', 'r', (err9, fd9) => { log.push(`open missing ${err9 instanceof Error} ${fd9}`); console.log(log.join('\n')); });
              });
            });
          });
        });
      });
    });
  });
});
log.push('callbacks are asynchronous');
"""
    r = js(code)
    assert out(r) == golden("fd_callbacks")
    assert (r.returncode, r.stderr) == (0, b"")


def test_opendir_and_glob_async_iteration(js, golden):
    """CATCHES: opendir handles that cannot be async-iterated (promise and callback forms),
    globs that miss nested files or match directories wrongly, or async glob variants whose
    results differ from globSync."""
    code = r"""
const fs = require('fs');
const fsp = fs.promises;
fs.mkdirSync('tree/a/b', { recursive: true });
for (const f of ['tree/x.js', 'tree/a/y.js', 'tree/a/b/z.txt', 'tree/a/b/w.js']) fs.writeFileSync(f, f);
(async () => {
  const dir = await fsp.opendir('tree');
  const names = [];
  for await (const e of dir) names.push(e.name + (e.isDirectory() ? '/' : ''));
  console.log('opendir', names.sort().join(','));
  const g = [];
  for await (const f of fsp.glob('tree/**/*.js')) g.push(f);
  console.log('glob async', g.sort().join(','));
  console.log('globSync', fs.globSync('tree/**/*.js').sort().join(','), fs.globSync('tree/a/b/*').sort().join(','));
  fs.opendir('tree/a', (err, d) => {
    const entry = d.readSync();
    const rest = [];
    for (let e; (e = d.readSync()); ) rest.push(e.name);
    d.closeSync();
    console.log('opendir cb', err, [entry.name, ...rest].sort().join(','));
    fs.glob('tree/a/*', (err2, m) => console.log('glob cb', err2, m.sort().join(',')));
  });
})();
"""
    r = js(code)
    assert out(r) == golden("opendir_glob")
    assert (r.returncode, r.stderr) == (0, b"")


def test_copy_rename_overwrite_and_blob(js):
    """CATCHES: renameSync/copyFileSync that refuse to replace an existing file (or leave the
    source behind), rename of a file over a directory that does not fail with EISDIR, cpSync that
    ignores its filter or errorOnExist options, or openAsBlob that does not expose the file's
    size and text."""
    code = r"""
const fs = require('fs');
fs.writeFileSync('s1', 'one'); fs.writeFileSync('s2', 'two');
fs.renameSync('s1', 's2');
console.log(fs.readFileSync('s2', 'utf8'), fs.existsSync('s1'));
fs.writeFileSync('s3', 'three');
fs.copyFileSync('s3', 's2');
console.log(fs.readFileSync('s2', 'utf8'), fs.readFileSync('s3', 'utf8'));
fs.mkdirSync('dd');
try { fs.renameSync('s3', 'dd'); } catch (e) { console.log('rename file over dir', e.code); }
fs.mkdirSync('tree/sub', { recursive: true });
fs.writeFileSync('tree/keep.js', 'k'); fs.writeFileSync('tree/sub/drop.txt', 'd'); fs.writeFileSync('tree/sub/keep2.js', 'k2');
fs.cpSync('tree', 'filtered', { recursive: true, filter: (src) => !src.endsWith('.txt') });
console.log(fs.existsSync('filtered/sub/drop.txt'), fs.readFileSync('filtered/sub/keep2.js', 'utf8'));
try { fs.cpSync('tree/keep.js', 'filtered/keep.js', { errorOnExist: true, force: false }); } catch (e) { console.log('cp onto existing', e.code); }
fs.cpSync('tree/keep.js', 'single-copy.js');
console.log(fs.readFileSync('single-copy.js', 'utf8'));
fs.openAsBlob('tree/sub/keep2.js').then(async (blob) => console.log('blob', blob.size, await blob.text(), blob instanceof Blob));
"""
    r = js(code)
    assert out(r) == ("one false\nthree three\nrename file over dir EISDIR\nfalse k2\n"
                      "cp onto existing ERR_FS_CP_EEXIST\nk\nblob 2 k2 true\n")
    assert (r.returncode, r.stderr) == (0, b"")


def test_binary_file_round_trip_and_stream_chunking(js):
    """CATCHES: binary writes that corrupt or truncate a multi-chunk buffer, positional reads that
    return the wrong bytes deep in the file, or a createReadStream that does not split the file
    into highWaterMark-sized chunks (20000 bytes at 8 KiB must arrive as 8192 + 8192 + 3616)."""
    code = r"""
const fs = require('fs');
const big = Buffer.alloc(20000);
for (let i = 0; i < big.length; i++) big[i] = (i * 7) % 251;
fs.writeFileSync('big.bin', big);
const fd = fs.openSync('big.bin', 'r');
const probe = Buffer.alloc(4);
fs.readSync(fd, probe, 0, 4, 17001);
fs.closeSync(fd);
console.log(fs.statSync('big.bin').size, Array.from(probe).join(','));
let sum = 0;
const sizes = [];
fs.createReadStream('big.bin', { highWaterMark: 8192 })
  .on('data', (c) => { sizes.push(c.length); for (let i = 0; i < c.length; i++) sum = (sum * 31 + c[i]) % 1000003; })
  .on('end', () => console.log(sizes.join('+'), sum));
"""
    r = js(code)
    probe = ",".join(str(((17001 + k) * 7) % 251) for k in range(4))
    checksum = 0
    for i in range(20000):
        checksum = (checksum * 31 + (i * 7) % 251) % 1000003
    assert out(r) == f"20000 {probe}\n8192+8192+3616 {checksum}\n"
    assert (r.returncode, r.stderr) == (0, b"")
