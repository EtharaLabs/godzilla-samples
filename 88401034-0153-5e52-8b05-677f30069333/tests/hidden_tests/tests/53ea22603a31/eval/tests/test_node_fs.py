"""node:fs (sync, callback, promises, streams, file descriptors) and node:path as exposed by lumen-cli.
Every test that writes files also checks the bytes on disk from Python."""

import os

from conftest import check_script, resources_for, write_files

G = resources_for(__file__)

NORM = r'''
const __cwd = require('fs').realpathSync(process.cwd());
const norm = (s) => String(s).split(__cwd).join('<cwd>');
'''


def tree(root):
    """Sorted listing of every file/dir/symlink under root with file contents, for exact comparison."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        rel = os.path.relpath(dirpath, root)
        for d in dirnames:
            p = os.path.join(dirpath, d)
            out.append((os.path.normpath(os.path.join(rel, d)), "link->" + os.readlink(p) if os.path.islink(p) else "dir"))
        for f in sorted(filenames):
            p = os.path.join(dirpath, f)
            if os.path.islink(p):
                out.append((os.path.normpath(os.path.join(rel, f)), "link->" + os.readlink(p)))
            else:
                with open(p, "rb") as fh:
                    out.append((os.path.normpath(os.path.join(rel, f)), fh.read()))
    return sorted(out)


def test_write_read_encodings_append_binary(run, workdir):
    """CATCHES: writeFileSync/readFileSync ignoring the encoding argument (string or {encoding}), the
    'a' flag not appending, readFileSync without encoding not returning a Buffer, text re-encoded
    wrongly (latin1 one byte per char, utf8 multi-byte), appendFileSync overwriting, binary payloads
    (Uint8Array, ArrayBuffer, Buffer slices) mangled by a UTF-8 round trip, or readFileSync(fd) not
    reading the whole file. Pins the reference quirk that appending a DataView writes no bytes."""
    check_script(run, workdir, G, "fs_encodings", r'''
const fs = require('fs');
fs.writeFileSync('utf8.txt', 'héllo \u{1F600}\n');
fs.writeFileSync('hex.txt', '68656c6c6f', 'hex');
fs.writeFileSync('b64.txt', 'aGkgdGhlcmU=', { encoding: 'base64' });
fs.writeFileSync('latin1.txt', 'café', 'latin1');
fs.writeFileSync('flag.txt', 'AAA');
fs.writeFileSync('flag.txt', 'BB', { flag: 'a' });
fs.writeFileSync('over.txt', 'long original content');
fs.writeFileSync('over.txt', 'short');
fs.writeFileSync('empty.txt', '');
const b = fs.readFileSync('utf8.txt');
console.log(b.constructor.name, Buffer.isBuffer(b), b.length, JSON.stringify(fs.readFileSync('utf8.txt', 'utf8')));
console.log(fs.readFileSync('utf8.txt', { encoding: 'hex' }), fs.readFileSync('utf8.txt', 'base64'));
console.log(fs.readFileSync('latin1.txt').length, fs.readFileSync('latin1.txt', 'latin1'), JSON.stringify(fs.readFileSync('latin1.txt', 'utf8')));
console.log(fs.readFileSync('hex.txt', 'utf8'), fs.readFileSync('b64.txt', 'ascii'), fs.readFileSync('flag.txt', 'utf8'), fs.readFileSync('over.txt', 'utf8'));
console.log(JSON.stringify(fs.readFileSync('empty.txt', 'utf8')), fs.readFileSync('empty.txt').length);
console.log(fs.readFileSync('utf8.txt', 'utf16le').length, fs.readFileSync('utf8.txt', { encoding: null }).length);
''')
    files = {p.name: p.read_bytes() for p in workdir.iterdir() if p.suffix == ".txt"}
    assert files == {
        "utf8.txt": "héllo \U0001F600\n".encode(), "hex.txt": b"hello", "b64.txt": b"hi there",
        "latin1.txt": b"caf\xe9", "flag.txt": b"AAABB", "over.txt": b"short", "empty.txt": b"",
    }
    check_script(run, workdir, G, "fs_append_binary", r'''
const fs = require('fs');
fs.appendFileSync('log.txt', 'first\n');
fs.appendFileSync('log.txt', Buffer.from('second\n'));
fs.appendFileSync('log.txt', 'dGhpcmQK', 'base64');
const bytes = new Uint8Array([0, 255, 128, 10, 13, 0x80, 0xc3]);
fs.writeFileSync('bin.dat', bytes);
fs.appendFileSync('bin.dat', new DataView(new Uint8Array([1, 2, 3]).buffer, 1, 2));
fs.appendFileSync('bin.dat', new Uint8Array([9, 9]).buffer);
fs.appendFileSync('bin.dat', Buffer.from('xyzw').subarray(1, 3));
const back = fs.readFileSync('bin.dat');
console.log(back.length, back.toString('hex'), Array.from(back.subarray(0, 4)).join(','));
const fd = fs.openSync('log.txt', 'r');
console.log(JSON.stringify(fs.readFileSync(fd, 'utf8')));
fs.closeSync(fd);
''')
    assert (workdir / "log.txt").read_bytes() == b"first\nsecond\nthird\n"
    # The DataView append writes nothing in the reference (Buffer.from(DataView) is empty there).
    assert (workdir / "bin.dat").read_bytes() == b"\x00\xff\x80\x0a\x0d\x80\xc3\x09\x09yz"


def test_mkdir_readdir_rm(run, workdir):
    """CATCHES: mkdirSync({recursive}) failing on existing dirs or returning the wrong value, readdirSync
    not listing every entry, withFileTypes Dirents with wrong kinds/parentPath, and rmSync/rmdirSync/
    unlinkSync removing too much or too little; pins that the `recursive` readdir option is ignored."""
    write_files(workdir, {"keep/k.txt": "keep me"})
    check_script(run, workdir, G, "fs_mkdir_readdir_rm", r'''
const fs = require('fs');
console.log(JSON.stringify(fs.mkdirSync('a/b/c', { recursive: true })), JSON.stringify(fs.mkdirSync('a/b/c', { recursive: true })));
console.log(JSON.stringify(fs.mkdirSync('plain')));
fs.writeFileSync('a/one.txt', '1');
fs.writeFileSync('a/b/two.txt', '22');
fs.writeFileSync('a/.hidden', 'h');
fs.symlinkSync('one.txt', 'a/link-to-one');
console.log(fs.readdirSync('a').sort().join(','));
console.log(fs.readdirSync('a', { withFileTypes: true })
  .map((d) => `${d.name}:${d.isFile() ? 'F' : ''}${d.isDirectory() ? 'D' : ''}${d.isSymbolicLink() ? 'L' : ''}:${d.parentPath}:${d.path}`)
  .sort().join(' '));
console.log(JSON.stringify(fs.readdirSync('a', { recursive: true }).sort()));
console.log(JSON.stringify(fs.readdirSync('plain')), fs.readdirSync('.').sort().join(','));
fs.unlinkSync('a/link-to-one');
fs.rmSync('a/b', { recursive: true });
fs.rmdirSync('plain');
fs.rmSync('does-not-exist', { force: true });
fs.rmSync('a/.hidden');
console.log(fs.existsSync('a/b'), fs.existsSync('plain'), fs.existsSync('a/one.txt'), fs.readdirSync('a').join(','));
''')
    assert tree(workdir) == sorted([
        ("a", "dir"), ("a/one.txt", b"1"), ("keep", "dir"), ("keep/k.txt", b"keep me"),
        ("fs_mkdir_readdir_rm.js", (workdir / "fs_mkdir_readdir_rm.js").read_bytes()),
    ])


def test_stat_lstat_links_and_times(run, workdir):
    """CATCHES: Stats objects with wrong isFile/isDirectory/isSymbolicLink, size or mode type bits,
    lstat following symlinks, readlink/realpath wrong, utimesSync not setting exact atime/mtime
    (seconds or Date), chmodSync not applying permission bits, or hard links not sharing nlink/data.
    Pins that a string mode is parsed as decimal by the reference ('755' -> 0o363)."""
    write_files(workdir, {"data.txt": "0123456789", "dir/inner.txt": "x"})
    check_script(run, workdir, G, "fs_stat_links", NORM + r'''
const fs = require('fs');
// (directory sizes are filesystem-specific, so only file/symlink sizes are printed)
const show = (label, st) => console.log(label, st.isFile(), st.isDirectory(), st.isSymbolicLink(), st.isDirectory() ? '-' : st.size,
  (st.mode & 0o170000).toString(8), st.isFIFO(), st.isSocket(), st instanceof fs.Stats);
show('file', fs.statSync('data.txt'));
show('dir', fs.statSync('dir'));
fs.symlinkSync('data.txt', 'link.txt');
fs.symlinkSync('dir', 'dirlink');
fs.symlinkSync('missing-target', 'dangling');
show('stat(link)', fs.statSync('link.txt'));
show('lstat(link)', fs.lstatSync('link.txt'));
console.log(fs.readlinkSync('link.txt'), fs.readlinkSync('dangling'), fs.existsSync('dangling'), fs.lstatSync('dangling').isSymbolicLink());
console.log(norm(fs.realpathSync('link.txt')), norm(fs.realpathSync('dirlink/inner.txt')), norm(fs.realpathSync('dir/../data.txt')));
console.log(fs.readdirSync('dirlink').join(','), fs.readFileSync('link.txt', 'utf8'));
fs.utimesSync('dir/inner.txt', 1000000000, new Date(1500000000123));
const st = fs.statSync('dir/inner.txt');
console.log(st.atimeMs, st.mtimeMs, st.mtime.toISOString(), st.atime.getTime(), typeof st.ino, typeof st.dev);
fs.chmodSync('data.txt', 0o640);
console.log((fs.statSync('data.txt').mode & 0o777).toString(8));
fs.chmodSync('data.txt', '755');
console.log((fs.statSync('data.txt').mode & 0o777).toString(8));
fs.chmodSync('data.txt', 0o644);  // readable again: the grader runs the tests as an ordinary user, not root
fs.linkSync('data.txt', 'hard.txt');
fs.appendFileSync('hard.txt', '+');
console.log(fs.statSync('data.txt').nlink, fs.readFileSync('data.txt', 'utf8'), fs.statSync('hard.txt').ino === fs.statSync('data.txt').ino);
''')
    assert os.readlink(workdir / "link.txt") == "data.txt"
    assert os.readlink(workdir / "dangling") == "missing-target"
    assert (workdir / "data.txt").read_bytes() == b"0123456789+"
    assert os.stat(workdir / "dir" / "inner.txt").st_mtime_ns == 1500000000123000000
    assert os.stat(workdir / "dir" / "inner.txt").st_atime_ns == 1000000000000000000
    assert oct(os.stat(workdir / "data.txt").st_mode & 0o777) == "0o644"  # 0o363 is pinned by the printed output


def test_rename_copy_unlink_truncate(run, workdir):
    """CATCHES: renameSync/copyFileSync/unlinkSync/truncateSync/ftruncate doing the wrong thing to the
    files on disk (copy must not move, rename across directories must move, truncate without a length
    empties, truncate past the end pads with NULs)."""
    write_files(workdir, {"src.txt": "source data\n", "sub/.keep": ""})
    check_script(run, workdir, G, "fs_rename_copy", r'''
const fs = require('fs');
fs.copyFileSync('src.txt', 'copy.txt');
fs.renameSync('copy.txt', 'sub/moved.txt');
fs.copyFileSync('src.txt', 'sub/over.txt');
fs.writeFileSync('tmp.txt', 'temp');
fs.copyFileSync('tmp.txt', 'sub/over.txt');
fs.unlinkSync('tmp.txt');
fs.writeFileSync('trunc.txt', 'abcdefgh');
fs.truncateSync('trunc.txt', 3);
fs.writeFileSync('empty.txt', 'will be emptied');
fs.truncateSync('empty.txt');
fs.writeFileSync('pad.txt', 'ab');
fs.truncateSync('pad.txt', 5);
const fd = fs.openSync('src.txt', 'r+');
fs.ftruncateSync(fd, 6);
fs.closeSync(fd);
fs.renameSync('sub', 'renamed-dir');
console.log(fs.readdirSync('.').sort().join(','), fs.readdirSync('renamed-dir').sort().join(','));
console.log(JSON.stringify(fs.readFileSync('pad.txt', 'latin1')), fs.statSync('empty.txt').size);
''')
    assert tree(workdir) == sorted([
        ("src.txt", b"source"), ("trunc.txt", b"abc"), ("empty.txt", b""), ("pad.txt", b"ab\x00\x00\x00"),
        ("renamed-dir", "dir"), ("renamed-dir/.keep", b""), ("renamed-dir/moved.txt", b"source data\n"),
        ("renamed-dir/over.txt", b"temp"), ("fs_rename_copy.js", (workdir / "fs_rename_copy.js").read_bytes()),
    ])


def test_fd_positional_io(run, workdir):
    """CATCHES: writeSync/readSync ignoring explicit positions or buffer offsets/lengths, the
    readSync options-object overload, readv/writev, append-mode descriptors, fstat on a descriptor,
    and the errors for a closed descriptor or writing to a read-only one."""
    check_script(run, workdir, G, "fs_fd_io", r'''
const fs = require('fs');
const fd = fs.openSync('fd.bin', 'w+');
console.log(typeof fd, fs.writeSync(fd, 'abcdef'), fs.writeSync(fd, 'XY', 1), fs.writeSync(fd, Buffer.from('0123456789'), 2, 3, 8));
const b = Buffer.alloc(8, '.');
console.log(fs.readSync(fd, b, 0, 4, 0), JSON.stringify(b.toString('latin1')));
console.log(fs.readSync(fd, b, 4, 4, 6), JSON.stringify(b.toString('latin1')));
console.log(fs.readSync(fd, b, { offset: 1, length: 2, position: 9 }), JSON.stringify(b.toString('latin1')));
console.log(fs.readSync(fd, b, 0, 8, 100), fs.fstatSync(fd).size, fs.fstatSync(fd).isFile());
fs.closeSync(fd);
try { fs.readSync(fd, b, 0, 1, 0); } catch (e) { console.log('closed:', e.name + ': ' + e.message.replace(/\d+$/, 'N')); }
const ap = fs.openSync('fd.bin', 'a');
fs.writeSync(ap, '++');
fs.writeSync(ap, '--', 0);
fs.closeSync(ap);
const ro = fs.openSync('fd.bin', 'r');
try { fs.writeSync(ro, 'no'); } catch (e) { console.log('read-only:', e.name + ': ' + e.message); }
fs.closeSync(ro);
const rw = fs.openSync('vec.bin', 'w+');
console.log(fs.writevSync(rw, [Buffer.from('ab'), Buffer.from('cd'), Buffer.from('ef')], 0));
const p1 = Buffer.alloc(3), p2 = Buffer.alloc(5, '_');
console.log(fs.readvSync(rw, [p1, p2], 1), p1.toString(), JSON.stringify(p2.toString()));
fs.closeSync(rw);
''')
    assert (workdir / "fd.bin").read_bytes() == b"aXYdef\x00\x00234++--"
    assert (workdir / "vec.bin").read_bytes() == b"abcdef"


def test_sync_error_shapes(run, workdir):
    """CATCHES: different error codes/messages/syscall/path properties for the common failures (ENOENT,
    EEXIST, ENOTDIR, EISDIR, ENOTEMPTY...). The reference's shapes vary per operation (some ops have
    no code at all); a reimplementation must match each one, and must not throw where it does not
    (realpathSync of a missing path, closeSync of an unknown fd, the non-exclusive 'wx' flag)."""
    check_script(run, workdir, G, "fs_error_shapes", r'''
const fs = require('fs');
const show = (label, f) => {
  try { const r = f(); console.log(label, 'ok', JSON.stringify(r)); }
  catch (e) { console.log(label, '|', e.name, e.code, e.syscall, JSON.stringify(e.path), '|', e.message); }
};
fs.writeFileSync('f.txt', 'hello');
fs.mkdirSync('d');
fs.mkdirSync('full');
fs.writeFileSync('full/x', '');
show('read missing', () => fs.readFileSync('missing.txt'));
show('read dir', () => fs.readFileSync('d'));
show('read through file', () => fs.readFileSync('f.txt/x'));
show('mkdir exists', () => fs.mkdirSync('d'));
show('mkdir under file', () => fs.mkdirSync('f.txt/sub'));
show('mkdir no parent', () => fs.mkdirSync('p/q/r'));
show('readdir file', () => fs.readdirSync('f.txt'));
show('readdir missing', () => fs.readdirSync('nope'));
show('unlink missing', () => fs.unlinkSync('nope'));
show('unlink dir', () => fs.unlinkSync('d'));
show('rmdir non-empty', () => fs.rmdirSync('full'));
show('rm missing', () => fs.rmSync('nope'));
show('rm dir', () => fs.rmSync('full'));
show('stat missing', () => fs.statSync('nope'));
show('lstat missing', () => fs.lstatSync('nope'));
show('rename missing', () => fs.renameSync('nope', 'x'));
show('copy missing', () => fs.copyFileSync('nope', 'x'));
show('open missing', () => fs.openSync('nope', 'r'));
show('write no dir', () => fs.writeFileSync('nodir/x.txt', 'x'));
show('readlink file', () => fs.readlinkSync('f.txt'));
show('access missing', () => fs.accessSync('nope'));
show('symlink exists', () => fs.symlinkSync('f.txt', 'f.txt'));
show('link exists', () => fs.linkSync('f.txt', 'd'));
show('realpath missing', () => fs.realpathSync('nope'));
show('close unknown', () => fs.closeSync(987654));
show('exists missing', () => fs.existsSync('nope'));
show('open wx existing', () => typeof fs.openSync('f.txt', 'wx'));
console.log(JSON.stringify(fs.readFileSync('f.txt', 'utf8')));
''')


def test_callback_api(run, workdir):
    """CATCHES: callback fs functions that call back synchronously (before the current code finishes),
    do not use error-first callbacks with null on success, report different errors, or missing a
    callback not throwing 'callback is not a function'."""
    check_script(run, workdir, G, "fs_callbacks", r'''
const fs = require('fs');
console.log('start');
fs.writeFile('cb.txt', 'callback data', (err) => {
  console.log('writeFile', err);
  fs.appendFile('cb.txt', '+more', (err) => {
    console.log('appendFile', err);
    fs.readFile('cb.txt', 'utf8', (err, data) => {
      console.log('readFile', err, data);
      fs.stat('cb.txt', (err, st) => {
        console.log('stat', err, st.size, st.isFile());
        fs.readFile('missing', (err, data) => {
          console.log('missing', err.name, err.code, err.message, data);
          fs.mkdir('cbd/e', { recursive: true }, (err) => {
            console.log('mkdir', err);
            fs.readdir('cbd', (err, names) => {
              console.log('readdir', err, JSON.stringify(names));
              fs.rename('cb.txt', 'cbd/cb.txt', (err) => {
                console.log('rename', err);
                fs.exists('cbd/cb.txt', (ex) => {
                  console.log('exists', ex);
                  fs.unlink('cbd/nope', (err) => console.log('unlink missing', err.message));
                });
              });
            });
          });
        });
      });
    });
  });
});
try { fs.readFile('x'); } catch (e) { console.log(e.name + ': ' + e.message); }
console.log('sync end');
''')
    assert (workdir / "cbd" / "cb.txt").read_bytes() == b"callback data+more"
    assert sorted(os.listdir(workdir / "cbd")) == ["cb.txt", "e"]


def test_promises_api(run, workdir):
    """CATCHES: fs.promises / fs/promises not being the same object, promise functions resolving with the
    wrong values or rejecting with different errors, and FileHandle (open/write/read/stat/close)
    misbehaving."""
    check_script(run, workdir, G, "fs_promises", r'''
const fs = require('fs');
const fsp = require('fs/promises');
console.log(fsp === fs.promises, fsp === require('node:fs/promises'));
(async () => {
  console.log(await fsp.writeFile('p.txt', 'promised\n'), await fsp.appendFile('p.txt', 'more\n'));
  console.log(JSON.stringify(await fsp.readFile('p.txt', 'utf8')), (await fsp.readFile('p.txt')).length);
  await fsp.mkdir('pd/x', { recursive: true });
  await fsp.writeFile('pd/x/y.txt', 'y');
  console.log((await fsp.readdir('pd')).join(), (await fsp.stat('pd/x/y.txt')).size, (await fsp.lstat('pd')).isDirectory());
  await fsp.rename('pd/x/y.txt', 'pd/z.txt');
  await fsp.copyFile('pd/z.txt', 'pd/w.txt');
  console.log((await fsp.readdir('pd')).sort().join());
  for (const [label, f] of [['readFile', () => fsp.readFile('nope.txt')], ['access', () => fsp.access('nope.txt')],
                            ['mkdir', () => fsp.mkdir('pd')], ['stat', () => fsp.stat('nope')], ['rm', () => fsp.rm('nope')]]) {
    try { await f(); console.log(label, 'resolved'); } catch (e) { console.log(label, 'rejected', e.code, e.message); }
  }
  await fsp.unlink('pd/w.txt');
  await fsp.rm('pd/x', { recursive: true });
  const fh = await fsp.open('fh.txt', 'w+');
  console.log(typeof fh.fd, (await fh.write('handle data')).bytesWritten);
  const { bytesRead, buffer } = await fh.read(Buffer.alloc(4), 0, 4, 7);
  console.log(bytesRead, buffer.toString(), (await fh.stat()).size);
  await fh.close();
  console.log(await fsp.readFile('fh.txt', 'utf8'));
})();
''')
    assert (workdir / "p.txt").read_bytes() == b"promised\nmore\n"
    assert (workdir / "fh.txt").read_bytes() == b"handle data"
    assert os.listdir(workdir / "pd") == ["z.txt"]
    assert (workdir / "pd" / "z.txt").read_bytes() == b"y"


def test_streams(run, workdir):
    """CATCHES: write streams that reorder or drop chunks, fire write/end callbacks or 'finish'/'close'
    in a different order, read streams not honouring highWaterMark/encoding/start/end, the 'a' flag
    not appending, and a missing file not emitting 'error'."""
    check_script(run, workdir, G, "fs_streams", r'''
const fs = require('fs');
const ws = fs.createWriteStream('s.txt');
ws.write('alpha\n');
ws.write(Buffer.from('beta\n'), () => console.log('write cb'));
ws.end('gamma\n', () => console.log('end cb'));
ws.on('finish', () => console.log('finish', ws.bytesWritten));
ws.on('close', () => {
  console.log('ws close', JSON.stringify(fs.readFileSync('s.txt', 'utf8')));
  const chunks = [];
  const rs = fs.createReadStream('s.txt', { encoding: 'utf8', highWaterMark: 4 });
  rs.on('data', (c) => chunks.push(c));
  rs.on('end', () => console.log('end', JSON.stringify(chunks)));
  rs.on('close', () => {
    console.log('rs close', rs.bytesRead);
    let got = '';
    const part = fs.createReadStream('s.txt', { start: 2, end: 8 });
    part.on('data', (c) => { got += c.toString(); });
    part.on('end', () => {
      console.log('range', JSON.stringify(got));
      const ap = fs.createWriteStream('s.txt', { flags: 'a' });
      ap.end('delta\n');
      ap.on('finish', () => {
        console.log('appended', JSON.stringify(fs.readFileSync('s.txt', 'utf8')));
        fs.createReadStream('nope.txt').on('error', (e) => console.log('error', e.code, e.message));
      });
    });
  });
});
''')
    assert (workdir / "s.txt").read_bytes() == b"alpha\nbeta\ngamma\ndelta\n"


def test_cp_glob_opendir_and_path_forms(run, workdir):
    """CATCHES: cpSync not copying trees recursively (or copying a directory without `recursive`),
    globSync patterns/cwd, opendirSync iteration, mkdtempSync not creating a prefixed directory,
    fs.constants values, and Buffer / file: URL path arguments not being accepted."""
    write_files(workdir, {"src/top.txt": "top", "src/a/mid.js": "mid", "src/a/b/leaf.txt": "leaf"})
    check_script(run, workdir, G, "fs_cp_glob", r'''
const fs = require('fs');
fs.cpSync('src', 'dst', { recursive: true });
try { fs.cpSync('src', 'dst2'); } catch (e) { console.log(e.code, e.message); }
try { fs.cpSync('src/top.txt', 'dst/top.txt', { errorOnExist: true, force: false }); } catch (e) { console.log(e.code, e.message); }
console.log(JSON.stringify(fs.globSync('src/**/*.txt').sort()), JSON.stringify(fs.globSync('*.txt', { cwd: 'src' })));
console.log(JSON.stringify(fs.globSync('src/*/*.js')));
const t = fs.mkdtempSync('tmp-');
console.log(t.length, t.startsWith('tmp-'), fs.statSync(t).isDirectory(), JSON.stringify(fs.readdirSync(t)));
fs.rmdirSync(t);
const d = fs.opendirSync('src');
const names = []; let e;
while ((e = d.readSync())) names.push(e.name + (e.isDirectory() ? '/' : ''));
d.closeSync();
console.log(names.sort().join(','));
const c = fs.constants;
console.log(c.F_OK, c.R_OK, c.W_OK, c.X_OK, c.O_RDONLY, c.O_WRONLY, c.O_RDWR, c.O_CREAT, c.O_APPEND, c.S_IFMT.toString(8), c.S_IFREG.toString(8));
const url = 'file://' + process.cwd() + '/src/top.txt';
console.log(fs.existsSync(Buffer.from('src')), fs.readFileSync(new URL(url), 'utf8'), fs.readFileSync(url, 'utf8'));
console.log(JSON.stringify(fs.readdirSync('src', 'buffer').map((b) => Buffer.isBuffer(b) + ':' + b).sort()));
fs.accessSync('src', fs.constants.R_OK);
console.log('access ok');
''')
    assert tree(workdir / "dst") == tree(workdir / "src")
    assert sorted(os.listdir(workdir)) == ["dst", "fs_cp_glob.js", "src"]


def test_path_string_operations(run, workdir):
    """CATCHES: wrong posix join/normalize ('..' above the root or a relative start, duplicate and trailing
    slashes, empty segments, '.' results), dirname/basename edge cases (trailing slashes, suffix equal
    to the name), extname (dotfiles, trailing dot, '..'), parse/format round trips (root vs dir
    precedence, base over name+ext) and isAbsolute; also that non-string arguments are stringified
    rather than rejected by the reference."""
    check_script(run, workdir, G, "path_join_normalize", r'''
const path = require('path');
const cases = [
  path.join('/a/b', '../c', './d', ''), path.join(), path.join(''), path.join('a', '..', '..', 'b'),
  path.join('a//', '//b/', 'c/'), path.join('/', '..', 'x'), path.join('.', '.'), path.join('a', '', 'b'),
  path.normalize('/../a/./b/../../c//d/'), path.normalize('./x/../../y'), path.normalize(''), path.normalize('.'),
  path.normalize('//double//lead'), path.normalize('a/b/..'), path.normalize('a/b/../'), path.normalize('../../'),
  path.join(1, 'a'), path.join('x', null, 'y'), path.basename(null),
];
console.log(cases.map((c) => JSON.stringify(c)).join('\n'));
console.log(path.sep, path.delimiter, path.posix === path, require('path/posix') === path.posix, require('node:path/win32') === path.win32);
''')
    check_script(run, workdir, G, "path_parse_format", r'''
const path = require('path');
const j = (v) => JSON.stringify(v);
console.log(j(['/a/b/c', '/a/b/c/', 'a', '/', '', '//x', 'a/b'].map(path.dirname)));
console.log(j([path.basename('/a/b.txt'), path.basename('/a/b.txt', '.txt'), path.basename('/a/b.txt', 'b.txt'),
  path.basename('/a/b/'), path.basename(''), path.basename('a.tar.gz', '.gz'), path.basename('x.js', 'js'), path.basename('/')]));
console.log(j(['index.html', 'index.coffee.md', 'index.', 'index', '.index', '.index.md', 'a/b.c/d', '..', 'a/.b', 'a.b/'].map(path.extname)));
console.log(j(path.parse('/home/user/dir/file.txt')));
console.log(j(path.parse('./x/.bashrc')), j(path.parse('/')), j(path.parse('file')), j(path.parse('a/b.c.d')));
console.log(j([path.format({ root: '/ignored', dir: '/home/u', base: 'f.txt' }), path.format({ root: '/', name: 'f', ext: '.txt' }),
  path.format({ name: 'n', ext: 'e' }), path.format({ dir: 'd', name: 'n', ext: '.e', base: 'b.x' }), path.format({ root: '/r/' }), path.format({})]));
console.log(j(['/a', 'a', './a', '', '//', '/..'].map(path.isAbsolute)));
console.log(path.format(path.parse('/round/trip.js')));
''')


def test_path_resolve_and_relative(run, workdir):
    """CATCHES: wrong resolve/relative on absolute inputs; and pins the reference's behaviour for
    relative inputs: resolve() joins onto the cwd but drops the leading '/', so the result is NOT
    absolute (a reimplementation using a correct resolve would print an absolute path here)."""
    check_script(run, workdir, G, "path_resolve_relative", r'''
const path = require('path');
const cwdNoSlash = process.cwd().slice(1);
const parentNoSlash = path.dirname(process.cwd()).slice(1);
const norm = (s) => s.split(process.cwd()).join('<cwd>').split(cwdNoSlash).join('<cwd-without-slash>')
  .split(parentNoSlash).join('<parent-without-slash>');
console.log(path.resolve('/foo/bar', './baz', '..', 'q'), path.resolve('/a', '/b', 'c'), path.resolve('/a/b/', '../../..'));
console.log(norm(path.resolve('x/y')), norm(path.resolve()), norm(path.resolve('..', 'z')), path.isAbsolute(path.resolve('rel')));
console.log(JSON.stringify([path.relative('/data/orandea/test/aaa', '/data/orandea/impl/bbb'), path.relative('/a/b', '/a/b'),
  path.relative('/a', '/a/b/c'), path.relative('/a/b/c', '/a'), path.relative('/a/b', '/a/bc'), path.relative('x', 'x/y')]));
''')


def test_path_win32(run, workdir):
    """CATCHES: a path.win32 that does not use backslashes/';', or that differs from the reference's own
    (non-Node) win32 behaviour for drive letters, UNC prefixes and toNamespacedPath."""
    check_script(run, workdir, G, "path_win32", r'''
const w = require('path').win32;
const j = (v) => JSON.stringify(v);
console.log(j([w.sep, w.delimiter, w.join('a', 'b/c', '..\\d'), w.normalize('a\\\\b/../c\\')]));
console.log(j([w.join('C:\\a', '..', 'b', 'c/d'), w.normalize('C:/x//y/../z\\'), w.resolve('C:\\a', 'b', '..\\c')]));
console.log(j(w.parse('C:\\dir\\file.ext')), j(w.parse('\\\\server\\share\\f.txt')));
console.log(j([w.basename('C:\\a\\b.txt'), w.dirname('C:\\a\\b.txt'), w.extname('x\\y.z'), w.basename('a/b\\c.d', '.d')]));
console.log(j([w.isAbsolute('C:\\'), w.isAbsolute('C:'), w.isAbsolute('\\\\server\\s'), w.isAbsolute('/x'), w.isAbsolute('x\\y')]));
console.log(j([w.relative('C:\\a\\b', 'C:\\a\\c\\d'), w.toNamespacedPath('C:\\x'), w.toNamespacedPath('\\\\srv\\s'), w.toNamespacedPath('rel')]));
''')


def test_global_lumen_fs_object(run, workdir):
    """CATCHES: the runtime's own global `fs` (lumen-fs, distinct from node:fs) missing or behaving like
    node:fs: readFileSync returns a string, readSync(fd) returns the rest of the file as a string,
    writeSync/mkdirSync return undefined, open modes r/w/a/r+/w+/a+ behave like fopen, bad modes and
    descriptors throw TypeErrors, and fs.promises.readFile/writeFile stringify their data."""
    check_script(run, workdir, G, "fs_global_object", r'''
console.log(fs === require('fs'), Object.keys(fs).join(','), Object.getOwnPropertyNames(fs).sort().join(','));
console.log(fs.writeFileSync('a.txt', 'héllo'), fs.appendFileSync('a.txt', ' more'));
console.log(JSON.stringify(fs.readFileSync('a.txt')), typeof fs.readFileSync('a.txt'));
console.log(fs.existsSync('a.txt'), fs.existsSync('nope'), fs.mkdirSync('d'), fs.mkdirSync('d'), JSON.stringify(fs.readdirSync('.').sort()));
const fd = fs.openSync('a.txt', 'r');
console.log(typeof fd, JSON.stringify(fs.readSync(fd)), JSON.stringify(fs.readSync(fd)));
fs.closeSync(fd);
const w = fs.openSync('b.txt', 'w');
console.log(fs.writeSync(w, 'line1\n'), fs.writeSync(w, 'line2\n'));
fs.closeSync(w);
console.log(JSON.stringify(fs.readFileSync('b.txt')));
const errs = [() => fs.readFileSync('nope'), () => fs.openSync('a.txt', 'z'), () => fs.readSync(12345), () => fs.closeSync(12345),
  () => fs.unlinkSync('nope'), () => fs.writeFileSync('d', 'x'), () => fs.appendFileSync('nodir/x', 'y'), () => fs.readdirSync('a.txt')];
for (const f of errs) {
  try { console.log('ok', f()); } catch (e) { console.log(e.name + ': ' + e.message); }
}
fs.writeFileSync('m.txt', 'abc');
for (const m of ['r', 'w', 'a', 'r+', 'w+', 'a+']) {
  const h = fs.openSync('m.txt', m);
  try { fs.writeSync(h, m + ';'); } catch (e) { console.log(m, e.message); }
  fs.closeSync(h);
  console.log(m, JSON.stringify(fs.readFileSync('m.txt')));
}
fs.unlinkSync('b.txt');
console.log(fs.existsSync('b.txt'));
fs.promises.writeFile('p.txt', 12345)
  .then((r) => { console.log('promise write', r); return fs.promises.readFile('p.txt'); })
  .then((t) => console.log('promise read', JSON.stringify(t), typeof t))
  .then(() => fs.promises.readFile('nope'))
  .catch((e) => console.log('rejected', e.name + ': ' + e.message));
''')
    assert sorted(p.name for p in workdir.iterdir()) == ["a.txt", "d", "fs_global_object.js", "m.txt", "p.txt"]
    assert (workdir / "a.txt").read_bytes() == "héllo more".encode()
    assert (workdir / "m.txt").read_bytes() == b"w+;a+;"
    assert (workdir / "p.txt").read_bytes() == b"12345"


def test_fd_metadata_and_unsupported_ops(run, workdir):
    """CATCHES: fchmodSync/futimesSync/fsyncSync/fdatasyncSync on a descriptor not applying (mode and
    mtime must change on disk), statfsSync returning a differently-shaped object, chownSync to the
    current owner failing, and the exact errors for unsupported lchmodSync / fs.watch and statfs of a
    missing path."""
    write_files(workdir, {"meta.txt": "metadata"})
    check_script(run, workdir, G, "fs_fd_metadata", r'''
const fs = require('fs');
const fd = fs.openSync('meta.txt', 'r+');
fs.fchmodSync(fd, 0o604);
fs.futimesSync(fd, 5, 6);
fs.fsyncSync(fd);
fs.fdatasyncSync(fd);
const st = fs.fstatSync(fd);
console.log((st.mode & 0o777).toString(8), st.atimeMs, st.mtimeMs, st.size);
fs.closeSync(fd);
const sf = fs.statfsSync('.');
console.log(Object.keys(sf).join(','), Object.values(sf).every((v) => typeof v === 'number'), sf.type);
fs.chownSync('meta.txt', process.getuid(), process.getgid());
console.log('chown to self ok');
for (const f of [() => fs.lchmodSync('meta.txt', 0o600), () => fs.watch('meta.txt'), () => fs.statfsSync('nope')]) {
  try { f(); console.log('no error'); } catch (e) { console.log(e.name, e.code, e.message); }
}
''')
    st = os.stat(workdir / "meta.txt")
    assert (oct(st.st_mode & 0o777), st.st_mtime_ns, st.st_atime_ns) == ("0o604", 6_000_000_000, 5_000_000_000)
    assert (workdir / "meta.txt").read_bytes() == b"metadata"
