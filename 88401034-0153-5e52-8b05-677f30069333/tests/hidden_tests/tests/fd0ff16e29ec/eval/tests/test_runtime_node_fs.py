"""node:fs (sync, fd, callback, promises, streams, cp/glob/opendir) and the native `fs` global (lumen-fs)."""

import pytest

from conftest import golden, write_files

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]


def _ok(r):
    assert (r.returncode, r.stderr) == (0, b""), r.stderr


PROG_SYNC_BASICS = r"""
const fs = require("fs");
const path = require("path");
const out = (...a) => console.log(...a);
fs.writeFileSync("a.txt", "hello\nworld\n");
out("read", JSON.stringify(fs.readFileSync("a.txt", "utf8")));
out("buf", fs.readFileSync("a.txt").toString("hex"), Buffer.isBuffer(fs.readFileSync("a.txt")));
fs.appendFileSync("a.txt", "more");
out("append", JSON.stringify(fs.readFileSync("a.txt", {encoding: "utf8"})));
fs.writeFileSync("bin.dat", Buffer.from([0, 255, 128, 10, 13]));
out("bin", fs.readFileSync("bin.dat").toString("hex"));
fs.writeFileSync("u.txt", new Uint8Array([104, 105]));
out("u8", fs.readFileSync("u.txt", "latin1"));
fs.writeFileSync("b64.txt", "aGVsbG8=", "base64");
out("b64", fs.readFileSync("b64.txt", "utf8"), fs.readFileSync("b64.txt", "base64"));
out("exists", fs.existsSync("a.txt"), fs.existsSync("nope"), fs.existsSync());
out("mkdir", fs.mkdirSync("d1/d2/d3", { recursive: true }), fs.mkdirSync("d1/d2/d3", { recursive: true }));
out("mkdir1", fs.mkdirSync("solo"));
fs.writeFileSync("d1/x.txt", "x");
fs.writeFileSync("d1/d2/y.txt", "yy");
out("readdir", fs.readdirSync("d1").join(","));
out("types", fs.readdirSync("d1", { withFileTypes: true }).sort((a,b)=>a.name<b.name?-1:1).map(d => `${d.name}:${d.isFile()}:${d.isDirectory()}:${d.isSymbolicLink()}:${d.parentPath}:${d.path}`).join(" "));
out("bufnames", fs.readdirSync("d1", "buffer").map(b => Buffer.isBuffer(b) + b.toString()).join(","));
const st = fs.statSync("d1/d2/y.txt");
out("stat", st.size, st.isFile(), st.isDirectory(), (st.mode & 0o170000).toString(8), st.nlink, st.isBlockDevice(), st.isCharacterDevice(), st.isFIFO(), st.isSocket(), st.mtime instanceof Date, typeof st.mtimeMs, typeof st.ino, typeof st.blksize);
const sd = fs.statSync("d1");
out("statdir", sd.isDirectory(), sd.isFile(), (sd.mode & 0o170000).toString(8));
fs.renameSync("d1/x.txt", "d1/z.txt");
out("rename", fs.readdirSync("d1").join(","));
fs.copyFileSync("d1/z.txt", "copy.txt");
out("copy", fs.readFileSync("copy.txt", "utf8"));
fs.unlinkSync("copy.txt");
out("unlinked", fs.existsSync("copy.txt"));
fs.symlinkSync("a.txt", "link.txt");
out("link", fs.readlinkSync("link.txt"), fs.lstatSync("link.txt").isSymbolicLink(), fs.statSync("link.txt").isSymbolicLink(), fs.readFileSync("link.txt", "utf8").length);
out("realpath", path.basename(fs.realpathSync("link.txt")), path.isAbsolute(fs.realpathSync("link.txt")), fs.realpathSync.native === fs.realpathSync);
fs.linkSync("a.txt", "hard.txt");
out("hard", fs.statSync("a.txt").nlink, fs.statSync("hard.txt").ino === fs.statSync("a.txt").ino);
fs.chmodSync("a.txt", 0o640);
out("chmod", (fs.statSync("a.txt").mode & 0o777).toString(8));
fs.chmodSync("a.txt", "755");
out("chmod string is decimal", (fs.statSync("a.txt").mode & 0o777).toString(8));
fs.chmodSync("a.txt", 0o644); // keep the file readable for non-root users
fs.utimesSync("a.txt", 1000000000, new Date(1500000000000));
const s2 = fs.statSync("a.txt");
out("utimes", s2.atimeMs, s2.mtimeMs, s2.mtime.toISOString(), s2.atime.toISOString());
fs.utimesSync("a.txt", "1234567890", 1600000000000);
out("utimes coerced", fs.statSync("a.txt").atimeMs, fs.statSync("a.txt").mtimeMs);
fs.truncateSync("a.txt", 3);
out("trunc", JSON.stringify(fs.readFileSync("a.txt", "utf8")));
fs.rmSync("d1", { recursive: true });
out("rm", fs.existsSync("d1"));
fs.rmSync("nothing", { force: true });
fs.rmdirSync("solo");
out("rmdir", fs.existsSync("solo"));
fs.accessSync("a.txt");
out("access ok", fs.constants.F_OK, fs.R_OK, fs.W_OK, fs.X_OK, fs.constants.O_APPEND, fs.constants.S_IFLNK);
const t = fs.mkdtempSync("tmp-");
out("mkdtemp", t.startsWith("tmp-"), t.length, fs.statSync(t).isDirectory(), /^tmp-[0-9a-f]{10}$/.test(t));
const tb = fs.mkdtempSync("tmb-", "buffer");
out("mkdtemp buffer", Buffer.isBuffer(tb), tb.length);
out("final", fs.readdirSync(".").filter(n => !n.startsWith("tm")).join(","));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_fs_sync_basics(run, workdir, tier):
    """CATCHES: node:fs sync ops (read/write/append encodings, mkdir recursive return values, readdir
    withFileTypes/buffer, stat mode/nlink, rename/copy/unlink, symlink/readlink, hard links, chmod with a
    decimal-coerced string, utimes, truncate, rm/rmdir, mkdtemp naming) that diverge from the reference."""
    r = run([*tier, "-e", PROG_SYNC_BASICS])
    _ok(r)
    assert r.stdout == golden(__file__, "sync_basics")
    assert (workdir / "a.txt").read_bytes() == b"hel"
    assert (workdir / "hard.txt").read_bytes() == b"hel"
    assert (workdir / "bin.dat").read_bytes() == b"\x00\xff\x80\n\r"
    assert (workdir / "b64.txt").read_bytes() == b"hello"
    assert (workdir / "link.txt").is_symlink()


PROG_ERRORS = r"""
const fs = require("fs");
const out = (...a) => console.log(...a);
const show = (label, f) => { try { out(label, "ok", JSON.stringify(f())); } catch (e) { out(label, e.name, e.code, e.syscall, e.path, "|", e.message); } };
show("readMissing", () => fs.readFileSync("missing.txt"));
show("readMissingUtf8", () => fs.readFileSync("missing.txt", "utf8"));
show("statMissing", () => fs.statSync("sub/missing"));
show("lstatMissing", () => fs.lstatSync("missing"));
fs.mkdirSync("dir");
fs.writeFileSync("file.txt", "abc");
show("mkdirExists", () => fs.mkdirSync("dir"));
show("mkdirNoParent", () => fs.mkdirSync("a/b/c"));
show("mkdirRecursiveOverFile", () => fs.mkdirSync("file.txt/sub", { recursive: true }));
show("readdirMissing", () => fs.readdirSync("nodir"));
show("readdirFile", () => fs.readdirSync("file.txt"));
show("readdirTypesFile", () => fs.readdirSync("file.txt", {withFileTypes:true}));
show("unlinkMissing", () => fs.unlinkSync("missing"));
show("rmMissing", () => fs.rmSync("missing"));
fs.writeFileSync("dir/inner", "1");
show("rmdirNotEmpty", () => fs.rmdirSync("dir"));
show("rmDirNoRecursive", () => fs.rmSync("dir"));
show("renameMissing", () => fs.renameSync("missing", "other"));
show("copyMissing", () => fs.copyFileSync("missing", "other"));
show("readlinkNotLink", () => fs.readlinkSync("file.txt"));
show("symlinkExists", () => fs.symlinkSync("file.txt", "dir"));
show("accessMissing", () => fs.accessSync("missing"));
show("chmodMissing", () => fs.chmodSync("missing", 0o644));
show("linkMissing", () => fs.linkSync("missing", "x"));
show("utimesMissing", () => fs.utimesSync("missing", 1, 1));
show("lutimesMissing", () => fs.lutimesSync("missing", 1, 1));
show("openMissing", () => fs.openSync("missing", "r"));
show("readFileDir", () => fs.readFileSync("dir"));
show("writeIntoFile", () => fs.writeFileSync("file.txt/x", "a"));
show("statNotDir", () => fs.statSync("file.txt/x"));
show("closeBad", () => fs.closeSync(9999));
show("fstatBad", () => fs.fstatSync(9999));
show("readSyncBad", () => fs.readSync(12345, Buffer.alloc(4)));
show("writeSyncBad", () => fs.writeSync(-1, "x"));
show("cpDirNoRecursive", () => fs.cpSync("dir", "dir2"));
show("watch", () => fs.watch("file.txt"));
show("promisesWatch", () => fs.promises.watch("file.txt"));
show("lchmod", () => fs.lchmodSync("file.txt", 0o644));
show("statfs", () => { const s = fs.statfsSync("."); return [typeof s.bsize, typeof s.blocks, typeof s.type]; });
show("statfsMissing", () => fs.statfsSync("missing"));
show("cbNotFunction", () => fs.stat("file.txt"));
"""


def test_fs_error_shapes(run, workdir):
    """CATCHES: wrong errno codes/syscall names/messages on node:fs failures (ENOENT, EEXIST, ENOTDIR,
    ENOTEMPTY, EIO for readlink of a file, ENOSYS for watch/lchmod, TypeError for bad fds), or errors
    that are thrown where the reference succeeds (closeSync of an unknown fd)."""
    r = run(["-e", PROG_ERRORS])
    _ok(r)
    assert r.stdout == golden(__file__, "errors")


PROG_FD = r"""
const fs = require("fs");
const out = (...a) => console.log(...a);
let fd = fs.openSync("f.bin", "w+");
out("fdtype", typeof fd, Number.isInteger(fd));
out("w1", fs.writeSync(fd, "Hello, "));
out("w2", fs.writeSync(fd, Buffer.from("World!!"), 0, 6));
out("w3", fs.writeSync(fd, "XY", 0));
const b = Buffer.alloc(20);
out("r1", fs.readSync(fd, b, 0, 20, 0), JSON.stringify(b.toString("utf8", 0, 13)));
const b2 = Buffer.alloc(5, 0x2e);
out("r2", fs.readSync(fd, b2, 1, 3, 7), b2.toString());
out("r3", fs.readSync(fd, b2, { offset: 0, length: 2, position: 2 }), b2.toString());
out("r4 eof", fs.readSync(fd, Buffer.alloc(4), 0, 4, 100));
out("fstat", fs.fstatSync(fd).size, fs.fstatSync(fd).isFile(), fs.fstatSync(fd).isDirectory());
fs.ftruncateSync(fd, 5);
out("ftrunc", fs.fstatSync(fd).size, fs.readFileSync(fd, "utf8"));
out("wv", fs.writevSync(fd, [Buffer.from("ab"), Buffer.from("cd")], 1));
const v1 = Buffer.alloc(2), v2 = Buffer.alloc(3);
out("rv", fs.readvSync(fd, [v1, v2], 0), v1.toString(), v2.toString());
fs.fsyncSync(fd); fs.fdatasyncSync(fd);
fs.fchmodSync(fd, 0o600);
out("fchmod", (fs.fstatSync(fd).mode & 0o777).toString(8));
fs.futimesSync(fd, 86400, 172800.5);
out("futimes", fs.fstatSync(fd).mtimeMs, fs.fstatSync(fd).atimeMs);
fs.futimesSync(fd, new Date(5000), "7");
out("futimes coerced", fs.fstatSync(fd).atimeMs, fs.fstatSync(fd).mtimeMs);
fs.closeSync(fd);
out("afterclose", fs.readFileSync("f.bin", "utf8"));
fd = fs.openSync("f.bin", "a");
fs.writeSync(fd, "++");
fs.closeSync(fd);
out("append", fs.readFileSync("f.bin", "utf8"));
fd = fs.openSync("f.bin", "r+");
fs.writeSync(fd, "Z", 0);
fs.closeSync(fd);
out("rplus", fs.readFileSync("f.bin", "utf8"));
fd = fs.openSync("f.bin", "a+");
fs.writeSync(fd, "#");
out("aplus read", fs.readFileSync(fd, "utf8"));
fs.closeSync(fd);
const C = fs.constants;
fd = fs.openSync("num.txt", C.O_WRONLY | C.O_CREAT | C.O_TRUNC);
fs.writeSync(fd, "numeric");
fs.closeSync(fd);
fd = fs.openSync("num.txt", C.O_RDWR | C.O_APPEND);
fs.writeSync(fd, "+app");
fs.closeSync(fd);
fd = fs.openSync("num.txt", C.O_RDWR);
fs.writeSync(fd, "N", 0);
fs.closeSync(fd);
out("numflags", fs.readFileSync("num.txt", "utf8"));
fs.writeFileSync("flag.txt", "one");
fs.writeFileSync("flag.txt", "two", { flag: "a" });
out("flaga", fs.readFileSync("flag.txt", "utf8"));
fd = fs.openSync("flag.txt", "r");
out("readfd", fs.readFileSync(fd).toString());
fs.closeSync(fd);
fd = fs.openSync("fdw.txt", "w");
fs.writeFileSync(fd, "via fd ");
fs.appendFileSync(fd, Buffer.from("appended"));
fs.closeSync(fd);
out("fd write", fs.readFileSync("fdw.txt", "utf8"));
fs.truncateSync("fdw.txt");
out("truncate default", fs.statSync("fdw.txt").size);
fd = fs.openSync("fdw.txt", "r+");
fs.truncateSync(fd, 0);
fs.closeSync(fd);
out("ids distinct", (() => { const a = fs.openSync("flag.txt"); const b = fs.openSync("flag.txt"); const d = a !== b; fs.closeSync(a); fs.closeSync(b); return d; })());
"""


def test_fs_fd_operations(run, workdir):
    """CATCHES: broken positional reads/writes on numeric fds (offset/length/position handling, the
    options-object overload, EOF), readv/writev, ftruncate/fchmod/futimes, numeric O_* flags, the
    'a'/'a+'/'r+'/'w+' open modes, and readFileSync/writeFileSync/appendFileSync given an fd."""
    r = run(["-e", PROG_FD])
    _ok(r)
    assert r.stdout == golden(__file__, "fd_ops")
    assert (workdir / "f.bin").read_bytes() == b"Zabcd++#"
    assert (workdir / "num.txt").read_bytes() == b"Numeric+app"
    assert (workdir / "fdw.txt").read_bytes() == b""


PROG_PROMISES = r"""
import fs from "node:fs";
import fsp from "node:fs/promises";
import { readFile, writeFile } from "fs/promises";
const out = (...a) => console.log(...a);
await fsp.mkdir("src/sub/deep", { recursive: true });
await writeFile("src/a.txt", "A");
await fsp.writeFile("src/sub/b.js", "B");
await fsp.appendFile("src/sub/b.js", "+b");
await fsp.writeFile("src/sub/deep/c.md", new Uint8Array([67]));
out("read", await readFile("src/sub/b.js", "utf8"), (await fsp.readFile("src/a.txt")).toString("hex"));
out("readdir", (await fsp.readdir("src")).join(","));
const st = await fsp.stat("src/sub");
out("stat", st.isDirectory(), fsp.constants === fs.constants);
await fsp.copyFile("src/a.txt", "src/a2.txt");
await fsp.rename("src/a2.txt", "src/a3.txt");
await fsp.symlink("a.txt", "src/ln");
out("lstat", (await fsp.lstat("src/ln")).isSymbolicLink(), await fsp.readlink("src/ln"));
await fsp.link("src/a.txt", "src/hard");
await fsp.access("src/a3.txt");
await fsp.unlink("src/a3.txt");
await fsp.unlink("src/hard");
try { await fsp.access("src/a3.txt"); } catch (e) { out("accessErr", e.code); }
fs.cpSync("src", "dst", { recursive: true });
const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).sort((a,b)=>a.name<b.name?-1:1).flatMap(e => e.isDirectory() ? [d + "/" + e.name + "/", ...walk(d + "/" + e.name)] : [d + "/" + e.name + (e.isSymbolicLink() ? "@" + fs.readlinkSync(d + "/" + e.name) : "=" + fs.readFileSync(d + "/" + e.name, "utf8"))]);
out("cp", walk("dst").join(" "));
fs.cpSync("src", "dst2", { recursive: true, filter: (s) => !s.endsWith(".js") });
out("cpfilter", walk("dst2").join(" "));
fs.cpSync("src", "dst4", { recursive: true, dereference: true });
out("cpderef", walk("dst4").join(" "));
fs.cpSync("src/a.txt", "single/x/a.txt");
out("cpfile", fs.readFileSync("single/x/a.txt", "utf8"));
try { fs.cpSync("src/a.txt", "single/x/a.txt", { errorOnExist: true, force: false }); } catch (e) { out("cpExist", e.code, e.syscall, e.message); }
fs.writeFileSync("single/x/a.txt", "old");
fs.cpSync("src/a.txt", "single/x/a.txt", { force: false });
out("cp force:false keeps", fs.readFileSync("single/x/a.txt", "utf8"));
await fsp.cp("src/sub", "dst3", { recursive: true });
out("cpp", walk("dst3").join(" "));
out("glob", JSON.stringify(fs.globSync("src/**/*.{js,md}")), "|", fs.globSync("src/**/*").sort().join(","));
out("glob2", fs.globSync("**/*.md").sort().join(","), "|", fs.globSync("src/?.txt").join(","), "|", fs.globSync("src/[ab].txt").join(","), "|", fs.globSync("src/[!a].txt").join(","));
out("globmulti", fs.globSync(["src/*.txt", "dst3/*.js"]).sort().join(","));
out("globcwd", fs.globSync("*", { cwd: "src/sub" }).sort().join(","));
out("globex", fs.globSync("src/*", { exclude: (p) => p.endsWith("ln") }).sort().join(","));
out("globtypes", fs.globSync("src/*", { withFileTypes: true }).map(d => d.name + ":" + d.isFile() + ":" + d.isSymbolicLink()).sort().join(","));
const ga = [];
for await (const m of fsp.glob("dst/**/*.txt")) ga.push(m);
out("globasync", ga.sort().join(","));
const dir = fs.opendirSync("src");
const names = [];
let e;
while ((e = dir.readSync()) !== null) names.push(e.name + (e.isDirectory() ? "/" : ""));
dir.closeSync();
out("opendir", names.sort().join(","), dir.path, dir.readSync());
const d2 = await fsp.opendir("src/sub");
const n2 = [];
for await (const ent of d2) n2.push(ent.name);
out("opendirAsync", n2.sort().join(","));
const d3 = fs.opendirSync("src/sub");
const first = await d3.read();
out("dir.read promise", typeof first.name, (await d3.read()) !== null, await d3.read());
await d3.close();
const fh = await fsp.open("fh.txt", "w+");
out("fh", typeof fh.fd, fh instanceof fsp.FileHandle);
out("fhw", (await fh.write(Buffer.from("filehandle!"))).bytesWritten);
const r = await fh.read(Buffer.alloc(4), 0, 4, 4);
out("fhr", r.bytesRead, r.buffer.toString());
const r2 = await fh.read({ buffer: Buffer.alloc(3), position: 0 });
out("fhr2", r2.bytesRead, r2.buffer.toString());
out("fhstat", (await fh.stat()).size);
await fh.truncate(4);
out("fhreadFile", await fh.readFile("utf8"));
await fh.writeFile("WXYZ");
await fh.appendFile("++");
out("fhwv", (await fh.writev([Buffer.from("1"), Buffer.from("2")], 0)).bytesWritten);
const bufs = [Buffer.alloc(3), Buffer.alloc(3)];
out("fhrv", (await fh.readv(bufs, 0)).bytesRead, bufs.map(String).join("|"));
await fh.chmod(0o604);
out("fhmode", ((await fh.stat()).mode & 0o777).toString(8));
await fh.utimes(10, 20);
out("fhtimes", (await fh.stat()).atimeMs, (await fh.stat()).mtimeMs);
await fh.sync(); await fh.datasync();
await fh.close();
await fh.close();
out("fhafter", fh.fd, fs.readFileSync("fh.txt", "utf8"));
const fh2 = await fsp.open("fh.txt");
out("readFileFH", await fsp.readFile(fh2, "utf8"));
await fh2.close();
const fh3 = await fsp.open("fh3.txt", "w");
await fsp.writeFile(fh3, "written through handle");
await fsp.appendFile(fh3, "+more");
await fh3[Symbol.asyncDispose]();
out("fh3", fs.readFileSync("fh3.txt", "utf8"), fh3.fd);
await fsp.rm("dst", { recursive: true });
await fsp.rm("nothing", { force: true });
out("rm", fs.existsSync("dst"));
const tmp = await fsp.mkdtemp("tt-");
out("mkdtemp", tmp.length, (await fsp.realpath(tmp)).endsWith("/" + tmp));
await fsp.rmdir(tmp);
await fsp.truncate("src/sub/b.js", 1);
await fsp.utimes("src/sub/b.js", 5, 6);
out("trunc", await fsp.readFile("src/sub/b.js", "utf8"), (await fsp.stat("src/sub/b.js")).mtimeMs);
await fsp.chmod("src/sub/b.js", 0o611);
out("chmod", ((await fsp.stat("src/sub/b.js")).mode & 0o777).toString(8));
try { await fsp.readFile("nope.txt"); } catch (err) { out("err", err.code, err.message); }
try { await fsp.mkdir("src"); } catch (err) { out("err2", err.code, err.message); }
try { await fsp.open("nope/x.txt"); } catch (err) { out("err3", err.code, err.message); }
try { await fsp.lchmod("src/a.txt", 0o600); } catch (err) { out("err4", err.message); }
const blob = await fs.openAsBlob("src/a.txt", { type: "text/plain" });
out("blob", blob.size, blob.type, await blob.text(), blob instanceof Blob);
try { await fs.openAsBlob("missing.bin"); } catch (err) { out("blob err", err.code); }
"""


def test_fs_promises_cp_glob_opendir(run, workdir):
    """CATCHES: fs/promises (FileHandle read/write/readv/writev/readFile/truncate/close idempotence),
    cpSync/cp recursion with filter/dereference/errorOnExist/force, globSync pattern translation (**, ?,
    [..], [!..], no brace expansion, exclude, withFileTypes, cwd), opendir/Dir iteration and openAsBlob."""
    write_files(workdir, {"main.mjs": PROG_PROMISES})
    r = run(["main.mjs"])
    _ok(r)
    assert r.stdout == golden(__file__, "promises_cp_glob")
    assert (workdir / "fh.txt").read_bytes() == b"12leWXYZ++"
    assert (workdir / "fh3.txt").read_bytes() == b"written through handle+more"
    assert (workdir / "dst3" / "deep" / "c.md").read_bytes() == b"C"
    assert (workdir / "dst4" / "ln").read_bytes() == b"A"
    assert not (workdir / "dst4" / "ln").is_symlink()


PROG_CALLBACKS = r"""
const fs = require("fs");
const out = (...a) => console.log(...a);
const steps = [];
const step = (f) => steps.push(f);
const next = () => { const f = steps.shift(); if (f) f(); else out("all done"); };
let sync = true;
step(() => fs.writeFile("cb.txt", "callback data", (err) => { out("writeFile", err, sync); next(); }));
step(() => fs.appendFile("cb.txt", "!", (err) => { out("appendFile", err); next(); }));
step(() => fs.readFile("cb.txt", "utf8", (err, d) => { out("readFile", err, d); next(); }));
step(() => fs.readFile("cb.txt", (err, d) => { out("readFile buf", Buffer.isBuffer(d), d.length); next(); }));
step(() => fs.mkdir("cbdir/a", { recursive: true }, (err, p) => { out("mkdir", err, p); next(); }));
step(() => fs.readdir(".", (err, names) => { out("readdir", err, names.join(",")); next(); }));
step(() => fs.readdir("cbdir", { withFileTypes: true }, (err, ents) => { out("readdir types", ents.map((e) => e.name + e.isDirectory()).join()); next(); }));
step(() => fs.stat("cb.txt", (err, st) => { out("stat", err, st.size, st.isFile()); next(); }));
step(() => fs.lstat("nope", (err) => { out("lstat err", err.code, err.message); next(); }));
step(() => fs.exists("cb.txt", (ex) => { out("exists", ex); next(); }));
step(() => fs.access("nope", (err) => { out("access", err.code); next(); }));
step(() => fs.copyFile("cb.txt", "cb2.txt", (err) => { out("copyFile", err); next(); }));
step(() => fs.rename("cb2.txt", "cbdir/cb3.txt", (err) => { out("rename", err, fs.existsSync("cbdir/cb3.txt")); next(); }));
step(() => fs.symlink("cb.txt", "cblink", (err) => { out("symlink", err); next(); }));
step(() => fs.readlink("cblink", (err, t) => { out("readlink", err, t); next(); }));
step(() => fs.realpath("cblink", (err, p) => { out("realpath", err, p.endsWith("/cb.txt"), fs.realpath.native === fs.realpath); next(); }));
step(() => fs.open("cb.txt", "r+", (err, fd) => {
  out("open", err, typeof fd);
  fs.read(fd, Buffer.alloc(8), 0, 8, 0, (err2, n, buf) => {
    out("read", err2, n, buf.toString());
    fs.write(fd, "CALL", 0, (err3, written, str) => {
      out("write str", err3, written, str);
      fs.write(fd, Buffer.from("xyz"), 0, 2, 4, (err4, w2, b) => {
        out("write buf", err4, w2, b.toString());
        fs.read(fd, { buffer: Buffer.alloc(4), position: 0 }, (e5, n5, b5) => {
          out("read opts", e5, n5, b5.toString());
          fs.writev(fd, [Buffer.from("V1"), Buffer.from("V2")], 9, (e6, n6) => {
            out("writev", e6, n6);
            const bufs = [Buffer.alloc(5), Buffer.alloc(20)];
            fs.readv(fd, bufs, 0, (e7, n7) => {
              out("readv", e7, n7, bufs[0].toString(), JSON.stringify(bufs[1].toString("utf8", 0, n7 - 5)));
              fs.fstat(fd, (e8, st) => {
                out("fstat", e8, st.size);
                fs.ftruncate(fd, 4, (e9) => {
                  fs.fchmod(fd, 0o640, () => fs.futimes(fd, 1, 2, () => fs.fsync(fd, () => fs.fdatasync(fd, () => fs.close(fd, (e10) => { out("close", e9, e10, fs.readFileSync("cb.txt", "utf8"), fs.statSync("cb.txt").mtimeMs); next(); })))));
                });
              });
            });
          });
        });
      });
    });
  });
}));
step(() => fs.open("cb.txt", (err, fd) => { out("open default", err, typeof fd); fs.read(fd, (e, n, b) => { out("read default", e, n, b.length, b.toString("utf8", 0, n)); fs.closeSync(fd); next(); }); }));
step(() => fs.open("nope/x", "r", (err) => { out("open err", err.message); next(); }));
step(() => fs.read(4242, Buffer.alloc(1), 0, 1, 0, (err) => { out("read err", err.name, err.message); next(); }));
step(() => fs.truncate("cb.txt", 2, (err) => { out("truncate", err, fs.readFileSync("cb.txt", "utf8")); next(); }));
step(() => fs.chmod("cb.txt", 0o700, (err) => { out("chmod", err, (fs.statSync("cb.txt").mode & 0o777).toString(8)); next(); }));
step(() => fs.utimes("cb.txt", 100, 200, (err) => { out("utimes", err, fs.statSync("cb.txt").mtimeMs); next(); }));
step(() => fs.mkdtemp("cbtmp-", (err, p) => { out("mkdtemp", err, p.length); fs.rmdirSync(p); next(); }));
step(() => fs.cp("cbdir", "cbdir-copy", { recursive: true }, (err) => { out("cp", err, fs.readdirSync("cbdir-copy").join()); next(); }));
step(() => fs.cp("cbdir", "cbdir-copy2", (err) => { out("cp no recursive", err.code); next(); }));
step(() => fs.glob("cbdir*/**", (err, m) => { out("glob", err, m.sort().join()); next(); }));
step(() => fs.opendir("cbdir", (err, d) => { const n = []; let e; while ((e = d.readSync())) n.push(e.name); d.read((e2, v) => d.close(() => { out("opendir", err, n.sort().join(), e2, v); next(); })); }));
step(() => fs.unlink("cblink", (err) => { out("unlink", err); next(); }));
step(() => fs.rm("cbdir-copy", { recursive: true }, (err) => { out("rm", err); next(); }));
step(() => fs.rmdir("cbdir", { recursive: true }, (err) => { out("rmdir", err, fs.readdirSync(".").join()); next(); }));
step(() => fs.readFile("nope", (err, d) => { out("readFile err", err.code, d); next(); }));
step(() => { try { fs.readFile("x"); } catch (e) { out("no cb", e.name, e.message); } next(); });
next();
sync = false;
"""


def test_fs_callback_api(run, workdir):
    """CATCHES: callback-style fs functions that call back synchronously, use the wrong argument
    order ((err, bytesRead, buffer) for read/readv/write), mishandle optional flags/position overloads
    for open/read/write, or fail to route errors to the callback."""
    r = run(["-e", PROG_CALLBACKS])
    _ok(r)
    assert r.stdout == golden(__file__, "callbacks")
    assert (workdir / "cb.txt").read_bytes() == b"CA"


PROG_STREAMS = r"""
const fs = require("fs");
const out = (...a) => console.log(...a);
fs.writeFileSync("in.txt", "0123456789abcdefghij");
const ws = fs.createWriteStream("out.txt");
ws.on("open", (fd) => out("ws open", typeof fd));
ws.write("alpha ");
ws.write(Buffer.from("beta "));
ws.end("gamma", () => out("ws end cb"));
ws.on("finish", () => out("ws finish", ws.bytesWritten, ws.path));
ws.on("close", () => {
  out("ws close", JSON.stringify(fs.readFileSync("out.txt", "utf8")), ws instanceof fs.WriteStream);
  const rs = fs.createReadStream("in.txt", { highWaterMark: 6 });
  const chunks = [];
  rs.on("open", (fd) => out("rs open", typeof fd));
  rs.on("ready", () => out("rs ready"));
  rs.on("data", (c) => chunks.push(c.toString()));
  rs.on("end", () => out("rs end", chunks.join("|"), rs.bytesRead, rs instanceof fs.ReadStream));
  rs.on("close", () => {
    out("rs close");
    const rs2 = fs.createReadStream("in.txt", { start: 3, end: 7, encoding: "utf8" });
    let s = "";
    rs2.on("data", (c) => { s += c; out("typeof chunk", typeof c); });
    rs2.on("end", () => {
      out("range", s);
      const bad = fs.createReadStream("missing.txt");
      bad.on("error", (e) => {
        out("rs error", e.code, e.message);
        const ws2 = fs.createWriteStream("out.txt", { flags: "a" });
        ws2.end("!", () => {
          out("appended", fs.readFileSync("out.txt", "utf8"));
          const { pipeline } = require("stream");
          pipeline(fs.createReadStream("in.txt"), fs.createWriteStream("piped.txt"), (err) => {
            out("pipeline", err, fs.readFileSync("piped.txt", "utf8"));
            const rs3 = fs.createReadStream("in.txt", "latin1");
            let t = "";
            rs3.on("data", (c) => (t += c + "/"));
            rs3.on("end", () => {
              out("string opts", t);
              const ws3 = fs.createWriteStream("pos.txt", { flags: "w" });
              ws3.write("abcdef");
              ws3.end(() => {
                const ws4 = fs.createWriteStream("pos.txt", { flags: "r+", start: 2 });
                ws4.write("XY");
                ws4.end("Z", () => {
                  out("positional", fs.readFileSync("pos.txt", "utf8"), ws4.bytesWritten);
                  const wbad = fs.createWriteStream("nodir/x.txt");
                  wbad.on("error", (e) => out("ws error", e.message));
                });
              });
            });
          });
        });
      });
    });
  });
});
"""


def test_fs_read_write_streams(run, workdir):
    """CATCHES: fs.createReadStream/createWriteStream that chunk at the wrong highWaterMark, ignore
    start/end/encoding/flags options, emit events in a different order (the reference never emits
    'open' for a write stream drained synchronously), or report open failures differently."""
    r = run(["-e", PROG_STREAMS])
    _ok(r)
    assert r.stdout == golden(__file__, "streams")
    assert (workdir / "out.txt").read_bytes() == b"alpha beta gamma!"
    assert (workdir / "piped.txt").read_bytes() == b"0123456789abcdefghij"
    assert (workdir / "pos.txt").read_bytes() == b"abXYZf"


PROG_NATIVE_FS = r"""
const out = (...a) => console.log(...a);
const g = globalThis.fs;
out("shape", typeof g, Object.keys(g).join(","), typeof g.readFileSync, typeof g.promises.readFile, typeof __fs_native);
const show = (label, f) => { try { out(label, "ok", JSON.stringify(f())); } catch (e) { out(label, e.name, e.code, "|", e.message); } };
const h = g.openSync("g.txt", "w");
g.writeSync(h, "native ");
g.writeSync(h, 42);
g.closeSync(h);
const h2 = g.openSync("g.txt");
out("gread", JSON.stringify(g.readSync(h2)), JSON.stringify(g.readSync(h2)));
g.closeSync(h2);
show("read closed", () => g.readSync(h2));
g.appendFileSync("g.txt", "!");
g.writeFileSync("w.txt", "écrit");
g.mkdirSync("gx/gy");
g.mkdirSync("gx/gy");
g.writeFileSync("gx/gy/z", "zz");
g.writeFileSync("gx/a", "a");
out("glist", g.readdirSync("gx").join(), g.existsSync("gx/gy/z"), g.readFileSync("g.txt"), g.readFileSync("w.txt"));
g.unlinkSync("gx/gy/z");
out("gex", g.existsSync("gx/gy/z"));
const rw = g.openSync("rw.txt", "w+");
g.writeSync(rw, "read-write");
out("w+ pread", JSON.stringify(String.fromCharCode(...__fs_native.preadSync(rw, 4, 0))));
g.closeSync(rw);
const ap = g.openSync("rw.txt", "a+");
g.writeSync(ap, "+");
g.closeSync(ap);
const rp = g.openSync("rw.txt", "r+");
g.writeSync(rp, "R");
g.closeSync(rp);
const ao = g.openSync("rw.txt", "a");
g.writeSync(ao, "#");
g.closeSync(ao);
out("modes", g.readFileSync("rw.txt"));
show("globalFsMissing", () => g.readFileSync("missing"));
show("globalFsBadMode", () => g.openSync("g.txt", "zz"));
show("globalOpenMissing", () => g.openSync("missing"));
show("globalUnlinkMissing", () => g.unlinkSync("missing"));
show("globalReaddirMissing", () => g.readdirSync("missing"));
show("globalWriteBad", () => g.writeFileSync("nodir/x", "a"));
show("globalAppendBad", () => g.appendFileSync("nodir/x", "a"));
show("globalMkdirBad", () => g.mkdirSync("g.txt/x"));
show("badFd", () => g.writeSync(77, "x"));
show("nanFd", () => g.readSync("abc"));
g.closeSync(-5);
(async () => {
  await g.promises.writeFile("gp.txt", 12345);
  const t = await g.promises.readFile("gp.txt");
  out("gprom", t, typeof t);
  try { await g.promises.writeFile("nodir/x", "a"); } catch (e) { out("gpromerr", e.name, e.message); }
  try { await g.promises.readFile("nodir/x"); } catch (e) { out("gpromerr2", e.message); }
})();
"""


def test_native_fs_global(run, workdir):
    """CATCHES: the lumen-fs `fs` global (text-only sync ops, handle table ids with sequential reads,
    'op path: OS message' error format without codes, TypeError for bad modes/fds, recursive mkdirSync,
    sorted readdirSync, and the threadpool-backed fs.promises readFile/writeFile)."""
    r = run(["-e", PROG_NATIVE_FS])
    _ok(r)
    assert r.stdout == golden(__file__, "native_fs")
    assert (workdir / "g.txt").read_bytes() == b"native 42!"
    assert (workdir / "w.txt").read_bytes() == "écrit".encode()
    assert (workdir / "rw.txt").read_bytes() == b"Read-write+#"
    assert (workdir / "gp.txt").read_bytes() == b"12345"


PROG_ESM_URL_WATCH = r"""
import { readFileSync, writeFileSync, existsSync, promises, constants, Stats, Dirent, Dir, statSync, watchFile, unwatchFile, writeSync, openSync, closeSync, readdirSync, opendirSync } from "node:fs";
import * as fsNs from "fs";
import { pathToFileURL } from "node:url";
const out = (...a) => console.log(...a);
writeFileSync("urlfile.txt", "via url");
const u = new URL("urlfile.txt", pathToFileURL(process.cwd() + "/"));
out("url", u.protocol, readFileSync(u, "utf8"), existsSync(u), readFileSync(u.href, "utf8"));
out("bufpath", readFileSync(Buffer.from("urlfile.txt"), "utf8"));
out("ns", typeof fsNs.default.readFileSync, fsNs.readFileSync === readFileSync, promises === fsNs.default.promises, constants.O_CREAT, constants.S_IFDIR);
out("classes", statSync(".") instanceof Stats, readdirSync(".", { withFileTypes: true })[0] instanceof Dirent, opendirSync(".") instanceof Dir);
const fd = openSync("w.txt", "w"); writeSync(fd, "1"); closeSync(fd);
let fired = 0;
const listener = (cur, prev) => {
  fired++;
  out("watchFile change", cur.size, prev.size, cur.isFile());
  unwatchFile("w.txt", listener);
};
const watcher = watchFile("w.txt", { interval: 20 }, listener);
out("watcher", typeof watcher.on, watcher.unref() === watcher, watchFile("w.txt", () => {}) === watcher);
unwatchFile("never-watched.txt");
setTimeout(() => writeFileSync("w.txt", "12345"), 80);
setTimeout(() => { unwatchFile("w.txt"); out("fired", fired); }, 900);
"""


def test_fs_esm_url_paths_and_watchfile(run, workdir):
    """CATCHES: node:fs named ESM exports, file: URL and Buffer path arguments, exported classes, and
    the polling watchFile/unwatchFile (listener sees size change with (cur, prev) stats; the reference
    invokes a listener both directly and via the watcher's 'change' event)."""
    write_files(workdir, {"main.mjs": PROG_ESM_URL_WATCH})
    r = run(["main.mjs"])
    _ok(r)
    assert r.stdout == golden(__file__, "esm_url_watch")


PROG_FS_EXTRAS = r"""const fs = require("fs");
const os = require("os");
const zlib = require("zlib");
const out = (...a) => console.log(...a);
const show = (label, f) => { try { out(label, "ok", JSON.stringify(f())); } catch (e) { out(label, e.name, e.code, "|", e.message); } };
fs.writeFileSync("file.txt", "abc");
fs.mkdirSync("dir"); fs.writeFileSync("dir/x", "1");
show("rename file onto dir", () => fs.renameSync("file.txt", "dir"));
show("mkdir recursive over file", () => fs.mkdirSync("file.txt", { recursive: true }));
show("realpath missing", () => fs.realpathSync("does/not/exist"));
show("utimes nul", () => fs.utimesSync("a\0b", 1, 1));
show("statfs nul", () => fs.statfsSync("a\0b"));
const dn = fs.statSync("/dev/null");
show("dev null stat", () => [dn.isFile(), dn.isDirectory(), dn.isCharacterDevice(), dn.isSymbolicLink(), dn.size]);
const uid = process.getuid(), gid = process.getgid();
show("chown self", () => fs.chownSync("file.txt", uid, gid));
fs.symlinkSync("file.txt", "ln");
show("lchown self", () => fs.lchownSync("ln", uid, gid));
show("chown missing", () => fs.chownSync("missing", uid, gid));
show("lchown missing", () => fs.lchownSync("missing", uid, gid));
const fd = fs.openSync("file.txt", "r+");
show("fchown self", () => fs.fchownSync(fd, uid, gid));
show("read zero length", () => fs.readSync(fd, Buffer.alloc(4), 0, 0, 0));
show("ftruncate negative", () => { fs.ftruncateSync(fd, -5); return fs.fstatSync(fd).size; });
fs.closeSync(fd);
show("fchown closed", () => fs.fchownSync(fd, uid, gid));
const dfd = fs.openSync(".", "r");
const ds = fs.fstatSync(dfd);
show("fstat dir", () => [ds.isDirectory(), ds.isFile(), ds.isSymbolicLink()]);
show("read dir fd", () => fs.readSync(dfd, Buffer.alloc(4)));
show("fsync dir fd", () => fs.fsyncSync(dfd));
fs.closeSync(dfd);
const nfd = fs.openSync("/dev/null", "r");
const ns = fs.fstatSync(nfd);
show("fstat devnull", () => [ns.isDirectory(), ns.isFile(), ns.size]);
fs.closeSync(nfd);
fs.promises.chown("file.txt", uid, gid).then(() => out("promises chown ok"));
fs.lchown("ln", uid, gid, (e) => out("cb lchown", e));
show("getPriority bad pid", () => os.getPriority(2147483647));
show("setPriority bad pid", () => os.setPriority(2147483647, 0));
show("setPriority range", () => os.setPriority(0, 100));
show("zlib number", () => zlib.deflateSync(123));
show("zlib object", () => zlib.inflateSync({}));
show("crc32 number", () => zlib.crc32(5));
show("gunzip null", () => zlib.gunzipSync(null));
"""


def test_fs_ownership_devices_and_edge_errors(run, workdir):
    """CATCHES: chown/lchown/fchown to the caller's own uid/gid (sync, callback, promise), EISDIR from
    renaming a file onto a directory, mkdir {recursive} over a file returning undefined, realpath of a
    missing path echoing it back, NUL-byte paths, device/directory fstat kinds, zero-length and
    negative-length fd ops, and os.get/setPriority ESRCH/range errors."""
    r = run(["-e", PROG_FS_EXTRAS])
    _ok(r)
    assert r.stdout == golden(__file__, "fs_extras")
    assert (workdir / "file.txt").read_bytes() == b""
